from __future__ import annotations

import time
import random
import importlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from ..config import (
    MAX_SLIPPAGE_POINTS,
    MAX_SPREAD_POINTS,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    ModelStatus,
    StressLevel,
    TradeState,
    log,
)
from ..database.db_manager import DatabaseManager
from ..state_machine import Trade, TradeSetup, transition_trade_state
from ..strategy.smc_engine import Candle


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


@dataclass
class ExecutionPrecheck:
    allowed: bool
    reason: str
    spread_points: float = 0.0
    slippage_points: float = 0.0


class MT5Executor:
    def __init__(self, force_simulation: bool = False) -> None:
        self.ok = False
        self._sim = force_simulation
        self._degraded = False
        self._last_error: str | None = None
        self._last_success_at: float | None = None
        self._last_tick_at: float | None = None
        self._reconnect_attempt = 0
        self._next_retry_at: float | None = None
        self._on_degraded: Callable[[str], None] | None = None
        self._on_recovered: Callable[[], None] | None = None
        self._reconciliation_ok = False
        try:
            self._mt5: Any = importlib.import_module("MetaTrader5")
        except ImportError:
            self._mt5 = None
        # Small, bounded retry budget for order placement so that we
        # can survive transient MT5 glitches without stalling the engine.
        self._max_order_retries = 3

    def connect(self) -> bool:
        if self._sim:
            # In simulation mode we do not require a real MT5 instance.
            # This allows Linux environments without MetaTrader5 installed
            # to run the engine, backtests and API using synthetic data.
            self.ok = True
            log.info("mt5_simulation_mode_enabled")
            self._mark_recovered()
            return True
        if not self._mt5:
            log.error("MT5 not installed — cannot proceed without real MT5.")
            raise RuntimeError("MT5 not installed — real mode required.")
        if not self._mt5.initialize():
            log.error("MT5 init failed — cannot proceed without real MT5.")
            raise RuntimeError("MT5 initialization failed — real mode required.")
        if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
            if not self._mt5.login(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
                log.error("MT5 login failed — cannot proceed without real MT5.")
                raise RuntimeError("MT5 login failed — real mode required.")
        self.ok = True
        log.info("mt5_connected")
        self._mark_recovered()
        return True

    def disconnect(self) -> None:
        if self._mt5 and not self._sim:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
        self._mark_degraded("manual_disconnect")

    def set_status_callbacks(
        self,
        on_degraded: Optional[Callable[[str], None]] = None,
        on_recovered: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_degraded = on_degraded
        self._on_recovered = on_recovered

    def is_healthy(self) -> bool:
        return not self._degraded

    def last_error(self) -> str | None:
        return self._last_error

    def last_tick_at(self) -> float | None:
        return self._last_tick_at

    def reconciliation_ok(self) -> bool:
        return self._reconciliation_ok

    def _mark_degraded(self, reason: str) -> None:
        if not self._degraded:
            self._degraded = True
            self._last_error = reason
            if self._on_degraded:
                self._on_degraded(reason)

    def _mark_recovered(self) -> None:
        if self._degraded:
            self._degraded = False
            self._last_error = None
            self._reconnect_attempt = 0
            self._next_retry_at = None
            if self._on_recovered:
                self._on_recovered()

    def _handle_failure(self, reason: str) -> None:
        self._mark_degraded(reason)
        if self._next_retry_at is None:
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        delay = min(2 ** self._reconnect_attempt, 60)
        self._reconnect_attempt += 1
        self._next_retry_at = time.time() + delay

    def reconnect_if_needed(self) -> bool:
        if self._sim:
            self._mark_recovered()
            return True
        if self._next_retry_at is None:
            return True
        if time.time() < self._next_retry_at:
            return False
        try:
            ok = self.connect()
            if ok:
                return True
        except Exception as exc:
            self._handle_failure(f"reconnect_failed:{exc}")
        self._schedule_reconnect()
        return False

    def get_equity(self) -> float:
        if self._sim:
            return 10000.0
        try:
            info = self._mt5.account_info()
            if info:
                self._last_success_at = time.time()
            return float(info.equity if info else 10000.0)
        except Exception as exc:
            self._handle_failure(f"equity_failed:{exc}")
            return 10000.0

    def get_candles(self, pair: str, tf: str, n: int = 200) -> list[Candle]:
        if self._sim:
            return self._sim_candles(pair, tf, n)
        tf_map = {
            "M30": self._mt5.TIMEFRAME_M30,
            "H1": self._mt5.TIMEFRAME_H1,
            "H4": self._mt5.TIMEFRAME_H4,
            "D1": self._mt5.TIMEFRAME_D1,
        }
        tf_id = tf_map.get(tf, self._mt5.TIMEFRAME_M30)
        try:
            rates = self._mt5.copy_rates_from_pos(pair, tf_id, 0, n)
            if rates is None:
                return self._sim_candles(pair, tf, n)
            self._last_success_at = time.time()
            return [
                Candle(
                    time=datetime.fromtimestamp(r["time"], tz=timezone.utc),
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["tick_volume"],
                )
                for r in rates
            ]
        except Exception as exc:
            self._handle_failure(f"candles_failed:{exc}")
            return self._sim_candles(pair, tf, n)

    def validate_market(self, pair: str, direction: str) -> ExecutionPrecheck:
        if self._sim:
            return ExecutionPrecheck(True, "SIM mode", 0.0, 0.0)
        if self._degraded:
            return ExecutionPrecheck(False, "Execution degraded", 0.0, 0.0)
        try:
            tick = self._mt5.symbol_info_tick(pair)
            if not tick:
                return ExecutionPrecheck(False, "No symbol tick")
            symbol = self._mt5.symbol_info(pair)
            if not symbol:
                return ExecutionPrecheck(False, "No symbol info")

            self._last_tick_at = time.time()

            spread_points = (tick.ask - tick.bid) / symbol.point
            ref_price = tick.ask if direction == "BUY" else tick.bid
            market_price = symbol.ask if direction == "BUY" else symbol.bid
            slippage_points = abs(ref_price - market_price) / symbol.point

            if spread_points > MAX_SPREAD_POINTS:
                return ExecutionPrecheck(False, f"Spread too high: {spread_points:.1f}", spread_points, slippage_points)
            if slippage_points > MAX_SLIPPAGE_POINTS:
                return ExecutionPrecheck(False, f"Slippage too high: {slippage_points:.1f}", spread_points, slippage_points)
            return ExecutionPrecheck(True, "OK", spread_points, slippage_points)
        except Exception as exc:
            self._handle_failure(f"validate_failed:{exc}")
            return ExecutionPrecheck(False, f"Precheck failed: {exc}")

    def place_order(self, pair: str, direction: str, lot: float, sl: float, tp: float, comment: str = "Quantara") -> Optional[int]:
        if self._sim:
            ticket = int(time.time()) % 999999
            log.info("sim_order pair=%s direction=%s lot=%s ticket=%s", pair, direction, lot, ticket)
            return ticket
        # Respect current health but always try to recover gracefully before bailing.
        if self._degraded and not self.reconnect_if_needed():
            log.warning("order_blocked degraded=true pair=%s direction=%s", pair, direction)
            return None

        last_error: str | None = None
        for attempt in range(1, self._max_order_retries + 1):
            # Inline spread / slippage guard just before each attempt to keep
            # protection close to the actual order_send call.
            precheck = self.validate_market(pair, direction)
            if not precheck.allowed:
                log.warning(
                    "order_precheck_blocked pair=%s direction=%s attempt=%s reason=%s spread=%.1f slippage=%.1f",
                    pair,
                    direction,
                    attempt,
                    precheck.reason,
                    precheck.spread_points,
                    precheck.slippage_points,
                )
                last_error = precheck.reason
                # No amount of retry will fix a structurally bad market; stop early.
                break

            try:
                sym = self._mt5.symbol_info(pair)
                if not sym:
                    last_error = "no_symbol_info"
                    log.error("order_failed pair=%s direction=%s reason=no_symbol_info", pair, direction)
                    break

                price = sym.ask if direction == "BUY" else sym.bid
                order_type = self._mt5.ORDER_TYPE_BUY if direction == "BUY" else self._mt5.ORDER_TYPE_SELL
                req = {
                    "action": self._mt5.TRADE_ACTION_DEAL,
                    "symbol": pair,
                    "volume": lot,
                    "type": order_type,
                    "price": price,
                    "sl": sl,
                    "tp": tp,
                    "comment": comment,
                    "type_time": self._mt5.ORDER_TIME_GTC,
                    "type_filling": self._mt5.ORDER_FILLING_IOC,
                }
                result = self._mt5.order_send(req)
                if result and result.retcode == self._mt5.TRADE_RETCODE_DONE:
                    self._last_success_at = time.time()
                    log.info(
                        "order_executed pair=%s direction=%s ticket=%s attempt=%s",
                        pair,
                        direction,
                        result.order,
                        attempt,
                    )
                    return int(result.order)

                last_error = f"retcode={getattr(result, 'retcode', None)}"
                log.error(
                    "order_failed pair=%s direction=%s attempt=%s result=%s",
                    pair,
                    direction,
                    attempt,
                    result,
                )
                # Mark executor as degraded on hard MT5 errors so that heartbeat
                # can drive reconnection; keep retry bounded.
                self._handle_failure(f"order_failed:{last_error}")
            except Exception as exc:
                last_error = f"order_exc:{exc}"
                self._handle_failure(last_error)
                log.error("mt5_order_error pair=%s direction=%s attempt=%s error=%s", pair, direction, attempt, exc)

            if attempt < self._max_order_retries:
                # Small backoff; this is sync and runs rarely at trade time.
                time.sleep(min(1.0, 0.2 * attempt))

        if last_error:
            log.error(
                "order_give_up pair=%s direction=%s attempts=%s last_error=%s",
                pair,
                direction,
                self._max_order_retries,
                last_error,
            )
        return None

    def get_position(self, ticket: int) -> Optional[dict[str, float]]:
        if self._sim:
            return None
        if self._degraded:
            return None
        try:
            pos = self._mt5.positions_get(ticket=ticket)
            if not pos:
                return None
            p = pos[0]
            self._last_success_at = time.time()
            return {
                "ticket": float(ticket),
                "profit": float(p.profit),
                "price_current": float(p.price_current),
                "volume": float(p.volume),
            }
        except Exception as exc:
            self._handle_failure(f"get_position_failed:{exc}")
            return None

    def list_open_positions(self) -> list[dict[str, object]]:
        if self._sim or self._degraded:
            return []
        try:
            positions = self._mt5.positions_get()
            if not positions:
                return []
            self._last_success_at = time.time()
            results: list[dict[str, object]] = []
            for p in positions:
                direction = "BUY" if p.type == 0 else "SELL"
                results.append(
                    {
                        "ticket": int(p.ticket),
                        "symbol": p.symbol,
                        "direction": direction,
                        "volume": float(p.volume),
                        "price_open": float(p.price_open),
                        "price_current": float(p.price_current),
                        "sl": float(p.sl),
                        "tp": float(p.tp),
                    }
                )
            return results
        except Exception as exc:
            self._handle_failure(f"list_positions_failed:{exc}")
            return []

    def reconcile_state(self, db: DatabaseManager, monitor: Any) -> bool:
        if self._degraded and not self.reconnect_if_needed():
            self._reconciliation_ok = False
            return False
        try:
            open_positions = self.list_open_positions()
            db_open = db.get_open_trades()
            db_by_ticket = {t.get("mt5_ticket"): t for t in db_open if t.get("mt5_ticket")}
            mt5_tickets = {p["ticket"] for p in open_positions}

            for pos in open_positions:
                ticket = pos["ticket"]
                db_trade = db_by_ticket.get(ticket)
                if db_trade:
                    trade = self._trade_from_db(db_trade)
                    monitor.register(trade)
                    continue

                setup = TradeSetup(
                    id=f"REC_{ticket}",
                    pair=str(pos["symbol"]),
                    direction=str(pos["direction"]),
                    entry=_to_float(pos.get("price_open"), 0.0),
                    sl=_to_float(pos.get("sl"), 0.0),
                    tp1=_to_float(pos.get("tp"), 0.0),
                    tp2=_to_float(pos.get("tp"), 0.0),
                    rr=0.0,
                    confidence=0,
                    stress_level=StressLevel.NONE.value,
                    model_status=ModelStatus.ACTIVE.value,
                    is_shadow=False,
                    session="RECOVERY",
                    timeframe="N/A",
                    confluences=[],
                    narrative="Recovered position",
                    fundamental_risk="NORMAL",
                )
                trade = Trade(setup=setup, lot=_to_float(pos.get("volume"), 0.0), risk_pct=0.0)
                trade.mt5_ticket = _to_int(ticket, 0)
                transition_trade_state(trade, TradeState.MANAGING, "recovered_open")
                db.log_trade(trade.to_record())
                db.log_event(trade.id, "RECOVERED_OPEN", TradeState.EXECUTING.value, TradeState.MANAGING.value)
                monitor.register(trade)

            for db_trade in db_open:
                ticket = db_trade.get("mt5_ticket")
                if ticket and ticket in mt5_tickets:
                    continue
                trade = self._trade_from_db(db_trade)
                trade.close_price = trade.setup.entry
                transition_trade_state(trade, TradeState.CLOSED, "recovered_closed")
                db.log_trade(trade.to_record())
                db.log_event(trade.id, "RECOVERED_CLOSED", TradeState.MANAGING.value, TradeState.CLOSED.value)

            self._reconciliation_ok = True
            self._mark_recovered()
            return True
        except Exception as exc:
            self._handle_failure(f"reconcile_failed:{exc}")
            self._reconciliation_ok = False
            return False

    def _trade_from_db(self, record: dict[str, object]) -> Trade:
        setup = TradeSetup(
            id=str(record.get("id")),
            pair=str(record.get("pair")),
            direction=str(record.get("direction")),
            entry=_to_float(record.get("entry_price"), 0.0),
            sl=_to_float(record.get("stop_loss"), 0.0),
            tp1=_to_float(record.get("take_profit1"), 0.0),
            tp2=_to_float(record.get("take_profit2"), 0.0),
            rr=_to_float(record.get("rr_planned"), 0.0),
            confidence=_to_int(record.get("confidence"), 0),
            stress_level=str(record.get("stress_level") or StressLevel.NONE.value),
            model_status=str(record.get("model_status") or ModelStatus.ACTIVE.value),
            is_shadow=bool(record.get("is_shadow") or 0),
            session=str(record.get("session") or ""),
            timeframe=str(record.get("timeframe") or ""),
            confluences=[],
            narrative=str(record.get("notes") or ""),
            fundamental_risk=str(record.get("fundamental_risk") or "NORMAL"),
        )
        trade = Trade(setup=setup, lot=_to_float(record.get("lot_size"), 0.0), risk_pct=_to_float(record.get("risk_percent"), 0.0))
        if record.get("mt5_ticket"):
            trade.mt5_ticket = _to_int(record.get("mt5_ticket"), 0)
        state_value = str(record.get("trade_state") or TradeState.MANAGING.value)
        try:
            trade.state = TradeState(state_value)
        except ValueError:
            trade.state = TradeState.MANAGING
        return trade

    def _sim_candles(self, pair: str, tf: str, n: int) -> list[Candle]:
        seed = hash(f"{pair}{tf}{datetime.now(tz=timezone.utc).hour}") % 9999
        rng = random.Random(seed)
        base = {"XAUUSD": 2300, "EURUSD": 1.085, "GBPUSD": 1.270}.get(pair, 1.0)
        atr = {"XAUUSD": 8.0, "EURUSD": 0.0008, "GBPUSD": 0.001}.get(pair, 0.001)
        candles: list[Candle] = []
        price = float(base)
        trend = rng.choice([-1, 1])
        for i in range(n):
            if i % 30 == 0:
                trend = rng.choice([-1, 1])
            o = price
            c = o + trend * atr * rng.uniform(0.1, 0.9) + rng.gauss(0, atr * 0.3)
            h = max(o, c) + atr * rng.uniform(0.1, 0.5)
            l = min(o, c) - atr * rng.uniform(0.1, 0.5)
            candles.append(
                Candle(
                    time=datetime.now(tz=timezone.utc) - timedelta(minutes=(n - i) * 30),
                    open=round(o, 5),
                    high=round(h, 5),
                    low=round(l, 5),
                    close=round(c, 5),
                    volume=float(rng.randint(100, 5000)),
                )
            )
            price = c
        return candles
