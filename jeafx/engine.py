from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import (
    EVENT_LOOP_LAG_WARN_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    KILL_ZONES_UTC,
    MIN_RR,
    PAIRS,
    SCAN_INTERVAL,
    SESSION_FILTER,
    SETUP_TTL_SECONDS,
    SIGNAL_COOLDOWN,
    TIMEFRAMES,
    ModelStatus,
    TradeState,
    log,
    log_structured,
)
from .database.db_manager import DatabaseManager
from .event_bus import EventBus
from .execution.mt5_executor import MT5Executor
from .execution.position_monitor import PositionMonitor
from .governance.governance_engine import GovernanceEngine
from .risk.position_sizer import PositionSizer
from .risk.risk_validator import RiskValidator
from .state_machine import Trade, TradeSetup, transition_trade_state
from .strategy.analysis_engine import AnalysisEngine
from .strategy.confidence_engine import ConfidenceEngine
from .strategy.fundamental_filter import FundamentalContext, FundamentalFilter
from .strategy.smc_engine import Candle
from .strategy.types import Direction, ModelType
from .stress.stress_engine import StressEngine
from .telegram.bot_handler import CommandListener, TelegramBot
from scheduler.meta_update import run_daily_meta_update


class JEAfxEngine:
    def __init__(
        self,
        db: DatabaseManager,
        event_bus: EventBus,
        strategy: AnalysisEngine,
        confidence: ConfidenceEngine,
        fundamentals: FundamentalFilter,
        risk_sizer: PositionSizer,
        risk_validator: RiskValidator,
        stress: StressEngine,
        governance: GovernanceEngine,
        execution: MT5Executor,
        command_listener: CommandListener,
        monitor: PositionMonitor,
        bot: TelegramBot,
    ) -> None:
        self._db = db
        self._bus = event_bus
        self._strategy = strategy
        self._confidence = confidence
        self._fundamentals = fundamentals
        self._risk_sizer = risk_sizer
        self._risk_validator = risk_validator
        self._stress = stress
        self._governance = governance
        self._execution = execution
        self._command_listener = command_listener
        self._monitor = monitor
        self._bot = bot

        self._running = False
        self._cooldown: dict[str, datetime] = {}

    async def run(self) -> None:
        self._running = True
        await asyncio.gather(
            self.scan_loop(),
            self.telegram_listener_loop(),
            self.position_monitor_loop(),
            self.heartbeat_loop(),
        )

    async def stop(self) -> None:
        self._running = False

    async def run_once(self) -> None:
        await self._scan_cycle()

    async def scan_loop(self) -> None:
        was_sleeping = False
        while self._running:
            wait = seconds_until_next_session()
            if wait > 0:
                if not was_sleeping:
                    self._bus.publish("session.sleep", {"wait_seconds": wait})
                    was_sleeping = True
                await asyncio.sleep(min(wait, 60))
                continue

            if was_sleeping:
                self._bus.publish("session.open", {"session": session_name()})
                was_sleeping = False

            await self._scan_cycle()
            await asyncio.sleep(SCAN_INTERVAL)

    async def telegram_listener_loop(self) -> None:
        await self._command_listener.run_async()

    async def position_monitor_loop(self) -> None:
        await self._monitor.run_async()

    async def heartbeat_loop(self) -> None:
        while self._running:
            start = time.monotonic()
            if not self._execution.is_healthy():
                self._execution.reconnect_if_needed()
            else:
                self._execution.reconnect_if_needed()

            last_tick = self._execution.last_tick_at()
            if last_tick is not None:
                age = time.time() - last_tick
                if age > HEARTBEAT_INTERVAL_SECONDS * 3:
                    log.warning("heartbeat_stale_tick age=%s", round(age, 2))

            try:
                updated = run_daily_meta_update()
                if updated:
                    log.info("meta_learning_daily_update executed=true")
            except Exception as exc:
                log.warning("meta_learning_daily_update_error error=%s", exc)

            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            lag = time.monotonic() - start - HEARTBEAT_INTERVAL_SECONDS
            if lag > EVENT_LOOP_LAG_WARN_SECONDS:
                log.warning("event_loop_lag lag=%s", round(lag, 3))

    async def _scan_cycle(self) -> None:
        equity = self._execution.get_equity()
        stress_state = self._stress.evaluate(equity)
        governance_state = self._governance.evaluate(stress_state)
        if not governance_state.can_trade and governance_state.status == ModelStatus.DISABLED:
            log.warning("cycle_blocked governance=%s reason=%s", governance_state.status.value, governance_state.reason)
            return

        try:
            context = self._fundamentals.get_context()
        except Exception as exc:
            log.warning("fund_context_error error=%s", exc)
            return

        if context.blackout_active:
            self._bus.publish("fundamental.blackout", {"reason": context.blackout_reason})
            Path("signals/blackout.json").write_text(
                json.dumps({"active": True, "reason": context.blackout_reason, "timestamp": now_utc().isoformat()})
            )
            return

        primary_tf = TIMEFRAMES[0] if TIMEFRAMES else "M30"

        for pair in PAIRS:
            if not self._can_emit(pair):
                continue
            try:
                await self._analyze_pair(pair, primary_tf, context, stress_state, governance_state, equity)
            except Exception as exc:
                log.warning("analyze_error pair=%s tf=%s error=%s", pair, primary_tf, exc)

    def _can_emit(self, pair: str) -> bool:
        if pair not in self._cooldown:
            return True
        return (datetime.now() - self._cooldown[pair]).total_seconds() >= SIGNAL_COOLDOWN

    async def _analyze_pair(
        self,
        pair: str,
        timeframe: str,
        context: FundamentalContext,
        stress_state,
        governance_state,
        equity: float,
    ) -> None:
        allowed, reason = await self._risk_validator.validate_new_trade()
        if not allowed and governance_state.status != ModelStatus.SHADOW:
            log.info("daily_hard_stop blocked=%s", reason)
            return

        # Fetch multi-timeframe candles for institutional analysis
        candles_m30 = self._execution.get_candles(pair, "M30", 200)
        candles_h1  = self._execution.get_candles(pair, "H1",  100)
        candles_h4  = self._execution.get_candles(pair, "H4",   60)
        candles_d1  = self._execution.get_candles(pair, "D1",   30)

        if len(candles_m30) < 50:
            return

        # Run full institutional analysis pipeline with explicit timeframe context
        analysis = self._strategy.analyze(candles_m30, candles_h1, candles_h4, candles_d1, pair, timeframe=timeframe)

        # Send briefing to Telegram every cycle (even without setup)
        if analysis.briefing:
            log.info("briefing pair=%s model=%s setup=%s",
                     pair, analysis.recommended_model.value, analysis.has_trade_setup)
            # Only send briefing to Telegram if there's a trade setup or it changed significantly
            if analysis.has_trade_setup:
                self._bot.send(f"```\n{analysis.briefing}\n```")

        # No trade setup — analysis only
        if not analysis.has_trade_setup or analysis.model_result is None or analysis.model_result.setup is None:
            return

        model_result = analysis.model_result
        setup_proposal = model_result.setup

        # Risk check
        entry = setup_proposal.entry
        sl    = setup_proposal.stop_loss
        tp    = setup_proposal.take_profit
        rr    = setup_proposal.rr

        fund_score = context.fund_score(pair, setup_proposal.direction.value)
        confidence_eval = self._confidence.score_live(
            model_result.confidence,
            model_result.signals,
            rr,
            fund_score,
            stress_state.level,
            analysis.volatility_regime.value,
            allowed,
        )
        if not confidence_eval.passed:
            log.info("confidence_reject pair=%s tf=%s score=%s reason=%s", pair, timeframe, confidence_eval.score, confidence_eval.reason)
            return

        if rr < MIN_RR:
            return

        is_shadow = governance_state.status == ModelStatus.SHADOW
        size = self._risk_sizer.calculate(pair, entry, sl, equity, stress_state)
        if not size.allowed and not is_shadow:
            return

        exposure_used = self._db.get_today_risk()
        self._cooldown[pair] = datetime.now()

        setup = TradeSetup(
            id=f"{pair}_{int(time.time())}",
            pair=pair,
            direction=setup_proposal.direction.value,
            entry=round(entry, 2),
            sl=round(sl, 2),
            tp1=round(entry + (tp - entry) * 0.5, 2),  # TP1 at 50% of TP2
            tp2=round(tp, 2),
            rr=rr,
            confidence=confidence_eval.score,
            stress_level=stress_state.level.value,
            model_status=governance_state.status.value,
            is_shadow=is_shadow,
            session=analysis.session.value,
            timeframe=timeframe,
            confluences=model_result.signals,
            narrative=f"[{analysis.recommended_model.value}] {analysis.narrative_pattern.value} | "
                      + (analysis.model_result.setup.entry_reason if analysis.model_result.setup else ""),
            fundamental_risk="NORMAL",
            meta_features={
                "amd_phase": analysis.amd_phase.value,
                "volatility_regime": analysis.volatility_regime.value,
                "liquidity_regime": analysis.liquidity_regime.regime.value if analysis.liquidity_regime else "unknown",
                "model_used": analysis.recommended_model.value,
                "trap_risk": round(min(1.0, (analysis.trap_analysis.trap_probability / 100.0)), 4),
                "displacement_strength": round(analysis.displacement.strength if analysis.displacement else 0.0, 4),
                "liquidity_alignment": round(
                    analysis.liquidity_magnet.primary_magnet.magnet_strength if analysis.liquidity_magnet and analysis.liquidity_magnet.primary_magnet else 0.0,
                    4,
                ),
            },
            expires_at=now_utc() + timedelta(seconds=SETUP_TTL_SECONDS),
        )

        trade = Trade(setup=setup, lot=size.lot_size if size.allowed else 0.01, risk_pct=size.adjusted_risk_percent)
        trade.opened_at = now_utc()
        transition_trade_state(trade, TradeState.AWAITING_CONFIRM, "setup_found")

        self._db.log_trade(trade.to_record())
        self._db.log_event(
            trade.id, "SETUP_FOUND", TradeState.IDLE.value, TradeState.AWAITING_CONFIRM.value,
            {"confidence": setup.confidence, "rr": rr, "model": analysis.recommended_model.value},
        )
        self._bus.publish("trade.setup", {"trade_id": trade.id, "pair": pair, "direction": trade.setup.direction})
        self._write_signal(trade, analysis)

        log_structured(
            "setup_found",
            trade_id=trade.id,
            model=analysis.recommended_model.value,
            stress_level=setup.stress_level,
            confidence=setup.confidence,
            rr=rr,
            risk_percent=trade.risk_pct,
            exposure_used=round(exposure_used, 3),
        )

        # Send rich confirmation to Telegram (includes full briefing)
        self._bot.send_confirmation_v2(trade, analysis, stress_state, governance_state)

        confirmed_event = asyncio.Event()
        decision_holder: list[bool | None] = [None]

        def on_decision(confirmed: bool) -> None:
            if trade.confirmed_once:
                return
            trade.confirmed_once = True
            decision_holder[0] = confirmed
            confirmed_event.set()

        self._command_listener.register(trade.setup, on_decision)
        wait_seconds = max(0, int((trade.setup.expires_at - now_utc()).total_seconds()))

        try:
            await asyncio.wait_for(confirmed_event.wait(), timeout=wait_seconds)
        except TimeoutError:
            pass

        if decision_holder[0] is None or now_utc() > trade.setup.expires_at:
            transition_trade_state(trade, TradeState.CANCELLED, "setup_expired")
            self._db.log_trade(trade.to_record())
            self._db.log_event(trade.id, "TIMEOUT", TradeState.AWAITING_CONFIRM.value, TradeState.CANCELLED.value)
            self._command_listener.unregister(trade.id)
            self._bot.send(f"⏰ *Trade `{trade.id[:8]}` expired* — no response in time.")
            return

        if not decision_holder[0]:
            transition_trade_state(trade, TradeState.REJECTED, "manual_reject")
            self._db.log_trade(trade.to_record())
            self._db.log_event(trade.id, "REJECTED", TradeState.AWAITING_CONFIRM.value, TradeState.REJECTED.value)
            return

        transition_trade_state(trade, TradeState.EXECUTING, "manual_confirm")
        self._db.log_event(trade.id, "CONFIRMED", TradeState.AWAITING_CONFIRM.value, TradeState.EXECUTING.value)

        if is_shadow:
            trade.mt5_ticket = None
            transition_trade_state(trade, TradeState.MANAGING, "shadow_manage")
            self._db.log_trade(trade.to_record())
            self._monitor.register(trade)
            self._bus.publish("execution.shadow", {"trade_id": trade.id})
            return

        precheck = self._execution.validate_market(trade.setup.pair, trade.setup.direction)
        if not precheck.allowed:
            transition_trade_state(trade, TradeState.CANCELLED, "execution_precheck_failed")
            self._db.log_trade(trade.to_record())
            self._db.log_event(
                trade.id, "EXEC_BLOCKED", TradeState.EXECUTING.value, TradeState.CANCELLED.value,
                {"reason": precheck.reason, "spread": precheck.spread_points, "slippage": precheck.slippage_points},
            )
            self._bot.send(f"❌ *Execution blocked* `{trade.id[:8]}` — {precheck.reason}")
            return

        ticket = self._execution.place_order(
            trade.setup.pair, trade.setup.direction, trade.lot,
            trade.setup.sl, trade.setup.tp2,
        )
        if ticket:
            trade.mt5_ticket = ticket
            transition_trade_state(trade, TradeState.MANAGING, "order_executed")
            self._db.log_trade(trade.to_record())
            self._db.log_event(trade.id, "EXECUTED", TradeState.EXECUTING.value, TradeState.MANAGING.value, {"ticket": ticket})
            self._monitor.register(trade)
            self._bus.publish("execution.ok", {"trade_id": trade.id, "ticket": ticket})
            log_structured(
                "execution_ok", trade_id=trade.id, model=analysis.recommended_model.value,
                confidence=setup.confidence, rr=rr, risk_percent=trade.risk_pct,
                exposure_used=round(self._db.get_today_risk(), 3),
            )
        else:
            transition_trade_state(trade, TradeState.CANCELLED, "order_failed")
            self._db.log_trade(trade.to_record())
            self._db.log_event(trade.id, "EXEC_FAILED", TradeState.EXECUTING.value, TradeState.CANCELLED.value)
            self._bot.send(f"❌ *Execution failed* for `{trade.id[:8]}`")

    def _write_signal(self, trade: Trade, analysis) -> None:
        try:
            _upsert_signal_file(_signal_record(trade, analysis))
        except Exception as exc:
            log.warning("signal_write_error trade_id=%s error=%s", trade.id, exc)


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def session_name() -> str:
    hour = now_utc().hour
    if 6 <= hour < 9:
        return "London Pre-Open"
    if 7 <= hour < 12:
        return "London Session"
    if 12 <= hour < 13:
        return "NY/London Overlap"
    if 12 <= hour < 17:
        return "New York Session"
    if 20 <= hour or hour < 1:
        return "Asian Session"
    return "Off-Session"


def in_kill_zone() -> bool:
    if not SESSION_FILTER:
        return True
    hour = now_utc().hour
    return any(start <= hour < end for start, end in KILL_ZONES_UTC)


def seconds_until_next_session() -> float:
    if not SESSION_FILTER:
        return 0.0
    now = now_utc()
    now_seconds = now.hour * 3600 + now.minute * 60 + now.second
    windows = [(start_h * 3600, end_h * 3600) for start_h, end_h in KILL_ZONES_UTC]
    for op, cl in windows:
        if op <= now_seconds < cl:
            return 0.0
    future = [op for op, _ in windows if op > now_seconds]
    if future:
        return float(min(future) - now_seconds)
    return float(86400 - now_seconds + min(op for op, _ in windows))


def calc_levels(candles: list[Candle], direction: str) -> tuple[float, float, float, float]:
    recent = candles[-10:]
    close = candles[-1].close
    ranges = [c.high - c.low for c in candles[-14:]]
    atr = float((sum(ranges) / len(ranges)) if ranges else 1e-9)
    if direction == "BUY":
        sl = min(c.low for c in recent) - atr * 0.3
        return close, sl, close + (close - sl) * 1.5, close + (close - sl) * 3.0
    sl = max(c.high for c in recent) + atr * 0.3
    return close, sl, close - (sl - close) * 1.5, close - (sl - close) * 3.0


def _signal_record(trade: Trade, analysis) -> dict[str, object]:
    return {
        "id": trade.id,
        "pair": trade.setup.pair,
        "direction": trade.setup.direction,
        "entry": trade.setup.entry,
        "sl": trade.setup.sl,
        "tp": trade.setup.tp2,
        "rr": trade.setup.rr,
        "confidence": trade.setup.confidence,
        "model": analysis.recommended_model.value,
        "session": analysis.session.value,
        "timeframe": trade.setup.timeframe,
        "timestamp": now_utc().isoformat(),
    }


def _upsert_signal_file(record: dict[str, object]) -> None:
    path = Path("signals/signals.json")
    existing: list[dict[str, object]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, list):
                existing = [x for x in loaded if isinstance(x, dict)]
        except Exception:
            existing = []
    existing = [x for x in existing if x.get("id") != record.get("id")]
    existing.insert(0, record)
    path.write_text(json.dumps(existing[:200], indent=2))
