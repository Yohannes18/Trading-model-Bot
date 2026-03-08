from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from .api.server import run_api_server
from .backtest.backtester import Backtester
from backtester import PipelineBacktester
from .config import API_HOST, API_PORT, log
from .database.db_manager import DatabaseManager
from .engine import JEAfxEngine
from .event_bus import EventBus
from .execution.mt5_executor import MT5Executor
from .execution.position_monitor import PositionMonitor
from .governance.governance_engine import GovernanceEngine
from .risk.position_sizer import PositionSizer
from .risk.risk_validator import RiskValidator
from .strategy.analysis_engine import AnalysisEngine
from .strategy.confidence_engine import ConfidenceEngine
from .strategy.fundamental_filter import FundamentalFilter
from .stress.stress_engine import StressEngine
from .telegram.bot_handler import CommandListener, StatusNotifier, TelegramBot


def _build_engine(sim_only: bool = False, no_telegram: bool = False) -> tuple[JEAfxEngine, DatabaseManager, MT5Executor, StressEngine, GovernanceEngine]:
    db = DatabaseManager()
    bus = EventBus()
    execution = MT5Executor(force_simulation=sim_only)
    if not execution.connect():
        raise RuntimeError("MT5 connection failed")

    stress = StressEngine(db)
    governance = GovernanceEngine(db)

    bot = TelegramBot(enabled=not no_telegram)
    command_listener = CommandListener(bot)
    notifier = StatusNotifier(bot)
    monitor = PositionMonitor(db, execution, stress, governance, notifier)

    def _notify_degraded(reason: str) -> None:
        bot.send(f"MT5 DEGRADED: {reason}")

    def _notify_recovered() -> None:
        bot.send("MT5 RECOVERED")

    execution.set_status_callbacks(on_degraded=_notify_degraded, on_recovered=_notify_recovered)

    engine = JEAfxEngine(
        db=db,
        event_bus=bus,
        strategy=AnalysisEngine(),
        confidence=ConfidenceEngine(),
        fundamentals=FundamentalFilter(),
        risk_sizer=PositionSizer(db),
        risk_validator=RiskValidator(db),
        stress=stress,
        governance=governance,
        execution=execution,
        command_listener=command_listener,
        monitor=monitor,
        bot=bot,
    )

    notifier.engine_started()

    # Wire event bus → Telegram notifications
    def _fmt_dur(s: float) -> str:
        s = int(s); h, r = divmod(s, 3600); m, sc = divmod(r, 60)
        return f"{h}h {m:02d}m" if h else (f"{m}m {sc:02d}s" if m else f"{sc}s")

    def _on_session_sleep(payload: dict) -> None:
        from datetime import datetime, timezone, timedelta
        wait = payload.get("wait_seconds", 0)
        wake = (datetime.now(tz=timezone.utc) + timedelta(seconds=wait)).strftime("%H:%M")
        notifier.going_to_sleep(wake, _fmt_dur(wait))
        log.info("session_sleep payload=%s", payload)

    def _on_session_open(payload: dict) -> None:
        notifier.session_opening(str(payload.get("session", "Session")))
        log.info("session_open payload=%s", payload)

    def _on_trade_setup(payload: dict) -> None:
        log.info("trade_setup payload=%s", payload)

    def _on_execution_ok(payload: dict) -> None:
        log.info("execution_ok payload=%s", payload)

    def _on_execution_shadow(payload: dict) -> None:
        log.info("execution_shadow payload=%s", payload)

    bus.subscribe("session.sleep",  _on_session_sleep)
    bus.subscribe("session.open",   _on_session_open)
    bus.subscribe("trade.setup",    _on_trade_setup)
    bus.subscribe("execution.ok",   _on_execution_ok)
    bus.subscribe("execution.shadow", _on_execution_shadow)

    # Bind live state to command listener so /status and /trades work
    command_listener.bind_state(db, stress, governance, execution)

    if not execution.reconcile_state(db, monitor):
        raise RuntimeError("Reconciliation failed; refusing to trade")

    return engine, db, execution, stress, governance


def _setup_telegram() -> None:
    token = input("Paste bot token (from @BotFather): ").strip()
    bot = TelegramBot(token=token, chat_id="")
    input("Send any message to your bot on Telegram, then press Enter…")
    chat_id = bot.get_chat_id()
    if not chat_id:
        print("Could not get chat ID.")
        return
    print(f"TELEGRAM_TOKEN={token}")
    print(f"TELEGRAM_CHAT_ID={chat_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="JeaFX modular trading engine")
    parser.add_argument("--all", action="store_true", help="Run full engine")
    parser.add_argument("--test", action="store_true", help="Run one scan cycle")
    parser.add_argument("--api", action="store_true", help="Run API server only")
    parser.add_argument("--backtest", action="store_true", help="Run backtest")
    parser.add_argument("--sim-only", action="store_true", help="Force simulation mode (no MT5 connection attempts)")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram network calls")
    parser.add_argument("--setup-telegram", action="store_true", help="Configure Telegram")
    parser.add_argument("--pair", default="XAUUSD", help="Pair for backtest")
    parser.add_argument("--tf", default="M30", help="Timeframe for backtest")
    parser.add_argument("--candles", type=int, default=0, help="Backtest candle count (0=auto by timeframe)")
    parser.add_argument("--backtest-debug", action="store_true", help="Enable per-candle backtest diagnostics")
    parser.add_argument("--backtest-loose", action="store_true", help="Use loose backtest filters for diagnostics")
    args = parser.parse_args()

    if args.setup_telegram:
        _setup_telegram()
        return

    if args.api:
        engine, db, execution, stress, governance = _build_engine(sim_only=args.sim_only, no_telegram=args.no_telegram)
        try:
            started_at = datetime.now(tz=timezone.utc)
            run_api_server(db, execution, stress, governance, API_HOST, API_PORT, started_at)
        finally:
            execution.disconnect()
        return

    if args.backtest:
        engine, db, execution, stress, governance = _build_engine(sim_only=args.sim_only, no_telegram=args.no_telegram)
        try:
            # Legacy SMC backtester remains available for diagnostics,
            # but main backtest path now uses the full hybrid pipeline.
            candles_m30 = execution.get_candles(args.pair, "M30", 15000 if args.candles <= 0 else args.candles)
            candles_h1 = execution.get_candles(args.pair, "H1", 8000 if args.candles <= 0 else min(args.candles, 8000))
            candles_h4 = execution.get_candles(args.pair, "H4", 3000 if args.candles <= 0 else min(args.candles, 3000))
            candles_d1 = execution.get_candles(args.pair, "D1", 1500 if args.candles <= 0 else min(args.candles, 1500))

            result = PipelineBacktester().run(
                candles_m30=candles_m30,
                candles_h1=candles_h1,
                candles_h4=candles_h4,
                candles_d1=candles_d1,
                pair=args.pair,
            )

            print("\n" + "═" * 50)
            print(f"  PIPELINE BACKTEST — {args.pair} M30 (hybrid engine)")
            print("═" * 50)
            print(f"  Trades:          {result.trades}")
            print(f"  Win rate:        {result.win_rate:.1%}")
            print(f"  Expectancy:      {result.expectancy:.3f}R")
            print(f"  Profit factor:   {result.profit_factor:.3f}")
            print(f"  Max drawdown:    {result.max_drawdown:.3f}R")
            print(f"  Sharpe (R units):{result.sharpe_ratio:.3f}")
            print(f"  Risk of ruin:    {result.risk_of_ruin:.3%}")
            print("═" * 50 + "\n")
        finally:
            execution.disconnect()
        return

    if args.test:
        engine, db, execution, stress, governance = _build_engine(sim_only=args.sim_only, no_telegram=args.no_telegram)
        try:
            asyncio.run(engine.run_once())
        finally:
            execution.disconnect()
        return

    if args.all:
        engine, db, execution, stress, governance = _build_engine(sim_only=args.sim_only, no_telegram=args.no_telegram)
        try:
            asyncio.run(engine.run())
        except KeyboardInterrupt:
            log.info("JeaFX stopped")
        finally:
            execution.disconnect()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
