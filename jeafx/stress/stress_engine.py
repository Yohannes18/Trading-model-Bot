from __future__ import annotations

from collections import deque

from ..config import (
    STRESS_MILD_EXPECT,
    STRESS_MODERATE_EXPECT,
    STRESS_ROLLING_N,
    STRESS_RISK_MULT,
    STRESS_SEVERE_DD,
    STRESS_SEVERE_WINRATE,
    StressLevel,
    log,
)
from ..database.db_manager import DatabaseManager
from ..state_machine import StressState


class StressEngine:
    def __init__(self, db: DatabaseManager) -> None:
        self._results: deque[float] = deque(maxlen=STRESS_ROLLING_N)
        self._peak_equity: float = 0.0
        self._db = db

    def record_result(self, result_r: float, equity: float) -> None:
        self._results.append(result_r)
        if equity > self._peak_equity:
            self._peak_equity = equity

    def evaluate(self, current_equity: float) -> StressState:
        state = StressState(peak_equity=self._peak_equity, current_equity=current_equity)
        results = list(self._results)

        if len(results) < 5:
            state.level = StressLevel.NONE
            state.risk_multiplier = STRESS_RISK_MULT["NONE"]
            return state

        state.rolling_expectancy = round(sum(results) / len(results), 3)
        wins = sum(1 for r in results if r > 0)
        state.rolling_winrate = round(wins / len(results), 3)

        if self._peak_equity > 0:
            state.drawdown = round((self._peak_equity - current_equity) / self._peak_equity, 4)

        avg_dd = 0.05
        triggers: list[str] = []
        if state.rolling_winrate < STRESS_SEVERE_WINRATE or state.drawdown > avg_dd * STRESS_SEVERE_DD:
            state.level = StressLevel.SEVERE
            if state.rolling_winrate < STRESS_SEVERE_WINRATE:
                triggers.append(f"WR {state.rolling_winrate:.0%} < {STRESS_SEVERE_WINRATE:.0%}")
            if state.drawdown > avg_dd * STRESS_SEVERE_DD:
                triggers.append(f"DD {state.drawdown:.1%} > 2× avg")
        elif state.rolling_expectancy < STRESS_MODERATE_EXPECT:
            state.level = StressLevel.MODERATE
            triggers.append(f"Expectancy {state.rolling_expectancy:.2f}R < 0")
        elif state.rolling_expectancy < STRESS_MILD_EXPECT:
            state.level = StressLevel.MILD
            triggers.append(f"Expectancy {state.rolling_expectancy:.2f}R < {STRESS_MILD_EXPECT}R")
        else:
            state.level = StressLevel.NONE

        state.risk_multiplier = STRESS_RISK_MULT[state.level.value]
        state.triggers = triggers

        self._db.log_stress(
            state.level.value,
            state.rolling_expectancy,
            state.rolling_winrate,
            state.drawdown,
            state.peak_equity,
            current_equity,
        )
        log.info("stress_update level=%s expectancy=%s winrate=%s dd=%s", state.level.value, state.rolling_expectancy, state.rolling_winrate, state.drawdown)
        return state
