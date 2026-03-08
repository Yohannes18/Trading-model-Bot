from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import (
    GOVERNANCE_LOCKOUT_DAYS,
    GOVERNANCE_YEARLY_LIMIT,
    ModelStatus,
    SHADOW_QUALIFY_EXPECT,
    SHADOW_QUALIFY_TRADES,
    SHADOW_QUALIFY_WINRATE,
    StressLevel,
    log,
)
from ..database.db_manager import DatabaseManager
from ..state_machine import GovernanceState, StressState


class GovernanceEngine:
    def __init__(self, db: DatabaseManager) -> None:
        self._state = GovernanceState()
        self._shadow_results: list[float] = []
        self._db = db
        self._last_stress_level: StressLevel = StressLevel.NONE

    @property
    def state(self) -> GovernanceState:
        return self._state

    def evaluate(self, stress: StressState) -> GovernanceState:
        state = self._state
        now = datetime.now(tz=timezone.utc)

        if now.month == 1 and now.day == 1:
            state.severe_count_ytd = 0

        if state.status == ModelStatus.DISABLED and state.lock_until and now >= state.lock_until:
            state.status = ModelStatus.SHADOW
            state.lock_until = None
            self._db.log_governance("lockout_expired", state.status.value, state.severe_count_ytd, notes="Entering shadow requalification")

        severe_transition = stress.level == StressLevel.SEVERE and self._last_stress_level != StressLevel.SEVERE
        if severe_transition and state.status == ModelStatus.ACTIVE:
            state.severe_count_ytd += 1
            if state.severe_count_ytd >= GOVERNANCE_YEARLY_LIMIT:
                lock_until = now + timedelta(days=GOVERNANCE_LOCKOUT_DAYS)
                state.status = ModelStatus.DISABLED
                state.lock_until = lock_until
                state.can_trade = False
                state.reason = (
                    f"SEVERE stress triggered {state.severe_count_ytd}× this year — locked {GOVERNANCE_LOCKOUT_DAYS}d"
                )
                self._db.log_governance("model_disabled", state.status.value, state.severe_count_ytd, lock_until, state.reason)
                log.warning("governance_disabled reason=%s", state.reason)
                return state

        if state.status == ModelStatus.SHADOW:
            self._check_shadow_requalify(state)

        if state.status == ModelStatus.ACTIVE:
            state.can_trade = True
            state.reason = ""
        elif state.status == ModelStatus.DISABLED:
            state.can_trade = False
            lock_str = state.lock_until.strftime("%d %b %H:%M UTC") if state.lock_until else "indefinite"
            state.reason = f"Model DISABLED — locked until {lock_str}"
        elif state.status == ModelStatus.SHADOW:
            state.can_trade = False
            state.reason = (
                f"SHADOW mode — {state.shadow_trades}/{SHADOW_QUALIFY_TRADES} shadow trades | "
                f"WR {state.shadow_winrate:.0%} | E {state.shadow_expectancy:.2f}R"
            )

        self._last_stress_level = stress.level
        log.info("governance_decision status=%s can_trade=%s reason=%s", state.status.value, state.can_trade, state.reason)
        return state

    def record_shadow_trade(self, result_r: float) -> None:
        self._shadow_results.append(result_r)
        state = self._state
        state.shadow_trades = len(self._shadow_results)
        wins = sum(1 for r in self._shadow_results if r > 0)
        state.shadow_winrate = wins / len(self._shadow_results)
        state.shadow_expectancy = sum(self._shadow_results) / len(self._shadow_results)

    def _check_shadow_requalify(self, state: GovernanceState) -> None:
        if (
            state.shadow_trades >= SHADOW_QUALIFY_TRADES
            and state.shadow_winrate >= SHADOW_QUALIFY_WINRATE
            and state.shadow_expectancy >= SHADOW_QUALIFY_EXPECT
        ):
            state.status = ModelStatus.ACTIVE
            state.can_trade = True
            self._shadow_results.clear()
            self._db.log_governance(
                "requalified",
                state.status.value,
                state.severe_count_ytd,
                notes=f"WR={state.shadow_winrate:.0%} E={state.shadow_expectancy:.2f}R",
            )
            log.info("governance_requalified")
