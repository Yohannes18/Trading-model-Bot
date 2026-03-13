from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:
    BackgroundScheduler = None

from .api.server import run_api_server
from .backtest.backtester import Backtester
from backtester import PipelineBacktester
from .config import API_HOST, API_PORT, log
from .database.db_manager import DatabaseManager
from .engine import QuantaraEngine
from .event_bus import EventBus
from .execution.mt5_executor import MT5Executor
from .execution.position_monitor import PositionMonitor
from .governance.governance_engine import GovernanceEngine
from .risk.position_sizer import PositionSizer
from .risk.risk_validator import RiskValidator
from .strategy.analysis_engine import AnalysisEngine
from .strategy.confidence_engine import ConfidenceEngine
from .strategy.fundamental_filter import FundamentalFilter
from .strategy.liquidity.liquidity_map import LiquidityMap
from .strategy.narrative.session_analyzer import SessionAnalyzer
from .strategy.smc_engine import Candle
from .stress.stress_engine import StressEngine
from .telegram.bot_handler import CommandListener, StatusNotifier, TelegramBot
from .macro.macro_engine import MacroEngine


_SCHEDULER: Any | None = None


def _format_liquidity_pool(levels: list[object], max_items: int = 3) -> str:
    if not levels:
        return "N/A"
    shown = levels[:max_items]
    chunks: list[str] = []
    for level in shown:
        price = float(getattr(level, "price", 0.0))
        level_type = str(getattr(level, "level_type", "POOL"))
        score = int(getattr(level, "score", 0))
        chunks.append(f"{level_type}@{price:.2f}(S{score})")
    return ", ".join(chunks)


def _build_pre_london_market_brief(execution: MT5Executor, pair: str = "XAUUSD") -> str:
    macro_snapshot = MacroEngine().get_snapshot()

    candles_m30 = execution.get_candles(pair, "M30", 320)
    candles_h1 = execution.get_candles(pair, "H1", 220)
    candles_h4 = execution.get_candles(pair, "H4", 120)
    candles_d1 = execution.get_candles(pair, "D1", 40)

    asia = SessionAnalyzer().analyze_asia(candles_h1)
    buy_levels, sell_levels = LiquidityMap().build(candles_m30, candles_h4, candles_d1, asia.high, asia.low)

    dxy_text = "N/A" if macro_snapshot.dxy is None else f"{macro_snapshot.dxy:.2f} ({(macro_snapshot.dxy_change_pct or 0.0):+.2f}%)"
    us10y_text = "N/A" if macro_snapshot.us10y is None else f"{macro_snapshot.us10y:.2f} ({(macro_snapshot.us10y_change_bps or 0.0):+.1f}bps)"
    asia_text = f"{asia.low:.2f} - {asia.high:.2f} ({asia.range_pips:.0f} pips, {asia.classification})"

    return (
        "📘 *Quantara Market Brief*\n"
        f"Pair: `{pair}`\n"
        f"DXY: `{dxy_text}`\n"
        f"US10Y: `{us10y_text}`\n"
        f"Asia Range: `{asia_text}`\n"
        f"Liquidity Pools Above: `{_format_liquidity_pool(sell_levels)}`\n"
        f"Liquidity Pools Below: `{_format_liquidity_pool(buy_levels)}`\n"
        f"Bias: `{macro_snapshot.gold_bias.value} | pressure={macro_snapshot.pressure:+.2f}`\n"
        f"Calendar Risk: `{'HIGH' if macro_snapshot.calendar_risk else 'LOW'}` (high impact events: {macro_snapshot.high_impact_events})"
    )


def _build_intraday_macro_delta(previous: Any, current: Any) -> str | None:
    if previous is None or current is None:
        return None

    changes: list[str] = []

    if previous.gold_bias != current.gold_bias:
        changes.append(f"Bias: `{previous.gold_bias.value}` → `{current.gold_bias.value}`")

    if abs(float(previous.pressure) - float(current.pressure)) >= 0.08:
        changes.append(f"Pressure: `{previous.pressure:+.2f}` → `{current.pressure:+.2f}`")

    if previous.dxy is None and current.dxy is not None:
        changes.append(f"DXY: `N/A` → `{current.dxy:.2f}`")
    elif previous.dxy is not None and current.dxy is None:
        changes.append(f"DXY: `{previous.dxy:.2f}` → `N/A`")
    elif previous.dxy is not None and current.dxy is not None and abs(float(previous.dxy) - float(current.dxy)) >= 0.05:
        changes.append(f"DXY: `{previous.dxy:.2f}` → `{current.dxy:.2f}`")

    if previous.us10y is None and current.us10y is not None:
        changes.append(f"US10Y: `N/A` → `{current.us10y:.3f}%`")
    elif previous.us10y is not None and current.us10y is None:
        changes.append(f"US10Y: `{previous.us10y:.3f}%` → `N/A`")
    elif previous.us10y is not None and current.us10y is not None and abs(float(previous.us10y) - float(current.us10y)) >= 0.005:
        changes.append(f"US10Y: `{previous.us10y:.3f}%` → `{current.us10y:.3f}%`")

    if previous.calendar_risk != current.calendar_risk or previous.high_impact_events != current.high_impact_events:
        changes.append(
            f"Calendar Risk: `{'HIGH' if previous.calendar_risk else 'LOW'}` ({previous.high_impact_events}) → `{'HIGH' if current.calendar_risk else 'LOW'}` ({current.high_impact_events})"
        )

    if not changes:
        return None

    ts = current.fetched_at.strftime("%H:%M UTC")
    return "📡 *Macro Change Alert*\n" + f"Time: `{ts}`\n\n" + "\n".join(f"- {line}" for line in changes)


def _start_daily_macro_scheduler(bot: TelegramBot, execution: MT5Executor) -> None:
    global _SCHEDULER
    if BackgroundScheduler is None:
        log.warning("daily_macro_scheduler_unavailable apscheduler_not_installed")
        return
    if _SCHEDULER is not None:
        return

    macro_engine = MacroEngine()
    last_sent_snapshot: Any | None = None

    def send_daily_macro_report() -> None:
        nonlocal last_sent_snapshot
        try:
            msg = _build_pre_london_market_brief(execution, pair="XAUUSD")
            bot.send(msg)
            last_sent_snapshot = macro_engine.get_snapshot(cache_ttl_seconds=30)
            log.info("pre_london_market_brief_sent pair=%s", "XAUUSD")
        except Exception as exc:
            log.error("pre_london_market_brief_failed error=%s", exc)

    def send_intraday_macro_changes() -> None:
        nonlocal last_sent_snapshot
        try:
            current = macro_engine.get_snapshot(cache_ttl_seconds=30)
            if last_sent_snapshot is None:
                last_sent_snapshot = current
                return

            delta_msg = _build_intraday_macro_delta(last_sent_snapshot, current)
            if delta_msg:
                bot.send(delta_msg)
                log.info("intraday_macro_delta_sent")
            last_sent_snapshot = current
        except Exception as exc:
            log.error("intraday_macro_delta_failed error=%s", exc)

    _SCHEDULER = BackgroundScheduler(timezone="UTC")
    _SCHEDULER.add_job(send_daily_macro_report, "cron", hour=6, minute=0)
    _SCHEDULER.add_job(send_intraday_macro_changes, "cron", hour="*/4", minute=5)
    _SCHEDULER.start()
    log.info("macro_scheduler_started daily_utc=06:00 intraday_every_hours=4")


def _stop_daily_macro_scheduler() -> None:
    global _SCHEDULER
    if _SCHEDULER is None:
        return
    try:
        _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = None


# === UPGRADE STEP 6 COMPLETED ===


def _candles_to_frame(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [c.time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    )


def _frame_to_candles(df: pd.DataFrame) -> list[Candle]:
    candles: list[Candle] = []
    for row in df.itertuples(index=False):
        t = pd.to_datetime(getattr(row, "time"), utc=True).to_pydatetime()
        candles.append(
            Candle(
                time=t,
                open=float(getattr(row, "open")),
                high=float(getattr(row, "high")),
                low=float(getattr(row, "low")),
                close=float(getattr(row, "close")),
                volume=float(getattr(row, "volume", 0.0)),
            )
        )
    return candles


def _load_cached_or_mt5_candles(execution: MT5Executor, pair: str, tf: str, n: int) -> list[Candle]:
    cache_dir = Path("data")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{pair.lower()}_{tf.lower()}.parquet"

    for legacy_cache in cache_dir.glob("*.parquet"):
        try:
            legacy_cache.unlink(missing_ok=True)
            log.info("legacy_candle_cache_removed path=%s", legacy_cache)
        except Exception as exc:
            log.error("legacy_candle_cache_remove_failed path=%s error=%s", legacy_cache, exc)

    candles = execution.get_candles(pair, tf, n)
    try:
        _candles_to_frame(candles).to_parquet(cache_path, index=False)
        log.info("backtest_cache_saved path=%s rows=%s", cache_path, len(candles))
    except Exception as exc:
        log.warning("backtest_cache_write_failed path=%s error=%s", cache_path, exc)
    return candles





def _build_engine(sim_only: bool = False, no_telegram: bool = False) -> tuple[QuantaraEngine, DatabaseManager, MT5Executor, StressEngine, GovernanceEngine]:
    db = DatabaseManager()
    bus = EventBus()
    execution = MT5Executor(force_simulation=sim_only)
    if not execution.connect():
        raise RuntimeError("MT5 connection failed")

    stress = StressEngine(db)
    governance = GovernanceEngine(db)

    bot = TelegramBot(enabled=not no_telegram)
    _start_daily_macro_scheduler(bot, execution)
    command_listener = CommandListener(bot)
    notifier = StatusNotifier(bot)
    monitor = PositionMonitor(db, execution, stress, governance, notifier)

    def _notify_degraded(reason: str) -> None:
        bot.send(f"MT5 DEGRADED: {reason}")

    def _notify_recovered() -> None:
        bot.send("MT5 RECOVERED")

    execution.set_status_callbacks(on_degraded=_notify_degraded, on_recovered=_notify_recovered)

    engine = QuantaraEngine(
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


def run_full_market_intelligence_smoke_test(no_telegram: bool = False) -> None:
    engine, db, execution, stress, governance = _build_engine(sim_only=False, no_telegram=no_telegram)
    try:
        asyncio.run(engine.run_once())
        print("Quantara v6 — FULL MARKET INTELLIGENCE ACTIVE")
    finally:
        execution.disconnect()
        _stop_daily_macro_scheduler()


def main() -> None:
    parser = argparse.ArgumentParser(description="Quantara modular trading engine")
    parser.add_argument("--all", action="store_true", help="Run full engine")
    parser.add_argument("--test", action="store_true", help="Run one scan cycle")
    parser.add_argument("--api", action="store_true", help="Run API server only")
    parser.add_argument("--backtest", action="store_true", help="Run backtest")
    parser.add_argument("--sim-only", action="store_true", help="Force simulation mode (no MT5 connection attempts)")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram network calls")
    parser.add_argument("--setup-telegram", action="store_true", help="Configure Telegram")
    parser.add_argument("--smoke-test", action="store_true", help="Run full-intelligence smoke test in real mode")
    parser.add_argument("--pair", default="XAUUSD", help="Pair for backtest")
    parser.add_argument("--tf", default="M30", help="Timeframe for backtest")
    parser.add_argument("--candles", type=int, default=0, help="Backtest candle count (0=auto by timeframe)")
    parser.add_argument("--backtest-debug", action="store_true", help="Enable per-candle backtest diagnostics")
    parser.add_argument("--backtest-loose", action="store_true", help="Use loose backtest filters for diagnostics")
    args = parser.parse_args()

    if args.setup_telegram:
        _setup_telegram()
        return

    if args.smoke_test:
        run_full_market_intelligence_smoke_test(no_telegram=args.no_telegram)
        return

    if args.api:
        engine, db, execution, stress, governance = _build_engine(sim_only=args.sim_only, no_telegram=args.no_telegram)
        try:
            started_at = datetime.now(tz=timezone.utc)
            run_api_server(db, execution, stress, governance, API_HOST, API_PORT, started_at)
        finally:
            execution.disconnect()
            _stop_daily_macro_scheduler()
        return

    if args.backtest:
        engine, db, execution, stress, governance = _build_engine(sim_only=args.sim_only, no_telegram=args.no_telegram)
        try:
            # Legacy SMC backtester remains available for diagnostics,
            # but main backtest path now uses the full hybrid pipeline.
            candles_m30 = _load_cached_or_mt5_candles(execution, args.pair, "M30", 15000 if args.candles <= 0 else args.candles)
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
            _stop_daily_macro_scheduler()
        return

    if args.test:
        engine, db, execution, stress, governance = _build_engine(sim_only=args.sim_only, no_telegram=args.no_telegram)
        try:
            asyncio.run(engine.run_once())
        finally:
            execution.disconnect()
            _stop_daily_macro_scheduler()
        return

    if args.all:
        engine, db, execution, stress, governance = _build_engine(sim_only=args.sim_only, no_telegram=args.no_telegram)
        try:
            asyncio.run(engine.run())
        except KeyboardInterrupt:
            log.info("Quantara stopped")
        finally:
            execution.disconnect()
            _stop_daily_macro_scheduler()
        return

    parser.print_help()


if __name__ == "__main__":
    main()


# === UPGRADE FINALIZATION COMPLETED ===
