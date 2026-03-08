from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Optional

from ..config import ModelStatus, StressLevel, TradeState, log, log_structured
from ..database.db_manager import DatabaseManager
from ..governance.governance_engine import GovernanceEngine
from ..state_machine import Trade, transition_trade_state
from ..stress.stress_engine import StressEngine
from ..telegram.bot_handler import StatusNotifier
from .mt5_executor import MT5Executor
from engine.meta_learning_engine import MetaLearningEngine, make_trade_history_row


class PositionMonitor:
    def __init__(
        self,
        db: DatabaseManager,
        mt5: MT5Executor,
        stress: StressEngine,
        governance: GovernanceEngine,
        notifier: Optional[StatusNotifier] = None,
    ) -> None:
        self._db = db
        self._mt5 = mt5
        self._stress = stress
        self._governance = governance
        self._notifier = notifier
        self._open: dict[str, Trade] = {}
        self._meta_learning = MetaLearningEngine()

    def register(self, trade: Trade) -> None:
        self._open[trade.id] = trade

    def run(self, interval: int = 15) -> None:
        while True:
            try:
                self.check_once()
            except Exception as exc:
                log.debug("monitor_error %s", exc)
            time.sleep(interval)

    async def run_async(self, interval: int = 15) -> None:
        while True:
            try:
                self.check_once()
            except Exception as exc:
                log.debug("monitor_error %s", exc)
            await asyncio.sleep(interval)

    def check_once(self) -> None:
        for trade in list(self._open.values()):
            if trade.state != TradeState.MANAGING:
                continue
            if trade.mt5_ticket is None:
                self._sim_check(trade)
                continue
            if not self._mt5.is_healthy():
                continue
            pos = self._mt5.get_position(trade.mt5_ticket)
            if pos is None:
                self._handle_close(trade, None)
            else:
                self._apply_be(trade, float(pos["price_current"]))

    def _sim_check(self, trade: Trade) -> None:
        if not trade.opened_at:
            return
        age_h = (datetime.now(tz=timezone.utc) - trade.opened_at).total_seconds() / 3600
        if age_h > 2:
            rng = random.Random(int(time.time()) % 9999)
            draw = rng.random()
            if draw < 0.35:
                result_r = -1.0
            elif draw < 0.70:
                result_r = 1.5
            else:
                result_r = 3.0
            trade.close_price = trade.setup.tp2 if result_r > 0 else trade.setup.sl
            self._handle_close(trade, result_r)

    def _apply_be(self, trade: Trade, current_price: float) -> None:
        entry = trade.setup.entry
        sl = trade.setup.sl
        risk = abs(entry - sl)
        if trade.setup.direction == "BUY" and current_price >= entry + risk:
            return
        if trade.setup.direction == "SELL" and current_price <= entry - risk:
            return

    def _handle_close(self, trade: Trade, result_r: Optional[float]) -> None:
        transition_trade_state(trade, TradeState.CLOSED, "position_closed")
        trade.closed_at = datetime.now(tz=timezone.utc)
        if result_r is not None:
            trade.result_r = result_r
        elif trade.close_price:
            entry = trade.setup.entry
            sl = trade.setup.sl
            risk = abs(entry - sl)
            if risk > 0:
                if trade.setup.direction == "BUY":
                    trade.result_r = (trade.close_price - entry) / risk
                else:
                    trade.result_r = (entry - trade.close_price) / risk

        self._db.log_trade(trade.to_record())
        self._db.log_event(trade.id, "TRADE_CLOSED", TradeState.MANAGING.value, TradeState.CLOSED.value, {"result_r": trade.result_r})

        equity = self._mt5.get_equity()
        self._stress.record_result(trade.result_r or 0, equity)
        stress = self._stress.evaluate(equity)
        gov = self._governance.evaluate(stress)

        # Notify Telegram
        if self._notifier:
            if trade.close_price is not None:
                self._notifier.trade_closed(
                    trade.setup.pair, trade.setup.direction,
                    trade.setup.entry, trade.close_price,
                    trade.result_r or 0, trade.id, trade.setup.is_shadow
                )
            if stress.level != StressLevel.NONE:
                self._notifier.stress_update(
                    stress.level.value, stress.rolling_expectancy,
                    stress.rolling_winrate, stress.drawdown,
                    stress.risk_multiplier, stress.triggers
                )
            if gov.status != ModelStatus.ACTIVE:
                self._notifier.governance_update(gov.status.value, gov.reason)
        log_structured(
            "execution_result",
            trade_id=trade.id,
            model_state=trade.setup.model_status,
            stress_level=stress.level.value,
            confidence=trade.setup.confidence,
            risk_percent=trade.risk_pct,
            exposure_used=round(self._db.get_today_risk(), 3),
            result_r=trade.result_r,
            governance_state=gov.status.value,
        )

        if gov.status != ModelStatus.ACTIVE or stress.level != StressLevel.NONE:
            log.warning("post_close_controls status=%s stress=%s", gov.status.value, stress.level.value)

        try:
            features = trade.setup.meta_features if hasattr(trade.setup, "meta_features") else {}
            row = make_trade_history_row(
                symbol=trade.setup.pair,
                session=trade.setup.session,
                amd_phase=str(features.get("amd_phase", "UNKNOWN")),
                volatility_regime=str(features.get("volatility_regime", "UNKNOWN")),
                liquidity_regime=str(features.get("liquidity_regime", "UNKNOWN")),
                model_used=str(features.get("model_used", "UNKNOWN")),
                confidence=float(trade.setup.confidence),
                rr=float(trade.setup.rr),
                result_r=float(trade.result_r or 0.0),
                trap_risk=float(features.get("trap_risk", 0.0) or 0.0),
                displacement_strength=float(features.get("displacement_strength", 0.0) or 0.0),
                liquidity_alignment=float(features.get("liquidity_alignment", 0.0) or 0.0),
                timestamp=trade.closed_at,
            )
            self._meta_learning.log_trade(row)
        except Exception as exc:
            log.warning("meta_learning_log_error trade_id=%s error=%s", trade.id, exc)

        self._open.pop(trade.id, None)
