from __future__ import annotations

import time
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
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
        self._symbol_map: dict[str, str] = {}
        self._available_symbols: list[str] = []
        # Small, bounded retry budget for order placement so that we
        # can survive transient MT5 glitches without stalling the engine.
        self._max_order_retries = 3

    def _refresh_available_symbols(self) -> list[str]:
        if self._sim or not self._mt5:
            return []
        try:
            symbols = self._mt5.symbols_get() or []
            names = [str(getattr(s, "name", "") or "") for s in symbols]
            self._available_symbols = [name for name in names if name]
        except Exception:
            self._available_symbols = []
        return self._available_symbols

    def _candidate_symbols(self, canonical: str) -> list[str]:
        if not self._available_symbols:
            self._refresh_available_symbols()
        needle = canonical.upper()
        exact = [s for s in self._available_symbols if s.upper() == needle]
        starts = [s for s in self._available_symbols if s.upper().startswith(needle)]
        ends = [s for s in self._available_symbols if s.upper().endswith(needle)]
        contains = [s for s in self._available_symbols if needle in s.upper()]
        dedup: dict[str, None] = {}
        for name in [canonical, *exact, *starts, *ends, *contains]:
            dedup.setdefault(name, None)
        return list(dedup.keys())

    def _try_select_symbol(self, symbol: str, retries: int = 3) -> bool:
        if self._sim:
            return True
        for attempt in range(retries):
            try:
                if self._mt5.symbol_select(symbol, True):
                    return True
            except Exception:
                pass
            if attempt < retries - 1:
                time.sleep(0.2 * (attempt + 1))
        return False

    def _resolve_and_select_symbol(self, canonical: str) -> str:
        if self._sim:
            return canonical
        mapped = self._symbol_map.get(canonical)
        if mapped:
            if self._try_select_symbol(mapped):
                return mapped

        candidates = self._candidate_symbols(canonical)
        for candidate in candidates:
            if self._try_select_symbol(candidate):
                if candidate != canonical:
                    log.info("mt5_symbol_mapped canonical=%s broker_symbol=%s", canonical, candidate)
                self._symbol_map[canonical] = candidate
                return candidate

        select_error = self._mt5.last_error() if hasattr(self._mt5, "last_error") else None
        preview = candidates[:8]
        raise RuntimeError(
            f"MT5 symbol_select failed for required symbol: {canonical}; last_error={select_error}; candidates={preview}"
        )

    def _broker_symbol(self, pair: str) -> str:
        if self._sim:
            return pair
        mapped = self._symbol_map.get(pair)
        if mapped:
            return mapped
        return self._resolve_and_select_symbol(pair)

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
            init_error = self._mt5.last_error() if hasattr(self._mt5, "last_error") else None
            try:
                self._mt5.shutdown()
            except Exception:
                pass
            if not self._mt5.initialize():
                retry_error = self._mt5.last_error() if hasattr(self._mt5, "last_error") else None
                log.error(
                    "MT5 init failed — cannot proceed without real MT5. initial_last_error=%s retry_last_error=%s",
                    init_error,
                    retry_error,
                )
                raise RuntimeError("MT5 initialization failed — real mode required.")
        if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
            if not self._mt5.login(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
                login_error = self._mt5.last_error() if hasattr(self._mt5, "last_error") else None
                log.error("MT5 login failed — cannot proceed without real MT5. last_error=%s", login_error)
                raise RuntimeError("MT5 login failed — real mode required.")

        self._refresh_available_symbols()
        required_symbols: tuple[str, ...] = ("XAUUSD", "EURUSD", "GBPUSD")
        for symbol in required_symbols:
            try:
                self._resolve_and_select_symbol(symbol)
            except RuntimeError as exc:
                log.error("mt5_symbol_select_failed symbol=%s error=%s", symbol, exc)
                raise

        self._last_success_at = time.time()
        self.ok = True
        log.info("mt5_connected symbols=%s symbol_map=%s", required_symbols, self._symbol_map)
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
        return bool(self.health_check().get("healthy", False))

    def last_success_at(self) -> float | None:
        return self._last_success_at

    def health_check(self, max_stale_seconds: int = 300) -> dict[str, object]:
        now = time.time()
        stale_seconds = None if self._last_success_at is None else max(0.0, now - self._last_success_at)
        stale = stale_seconds is None or stale_seconds > float(max_stale_seconds)
        healthy = self.ok and (not self._degraded) and (not stale)
        return {
            "healthy": healthy,
            "degraded": self._degraded,
            "ok": self.ok,
            "last_error": self._last_error,
            "last_success_at": self._last_success_at,
            "stale_seconds": stale_seconds,
            "max_stale_seconds": max_stale_seconds,
        }

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
            raise RuntimeError("Simulation candles are disabled in MT5Executor.get_candles(). Use real MT5 market data.")
        if not self.ok:
            raise RuntimeError("MT5 executor is not connected. Call connect() before requesting candles.")
        tf_map = {
            "M30": self._mt5.TIMEFRAME_M30,
            "H1": self._mt5.TIMEFRAME_H1,
            "H4": self._mt5.TIMEFRAME_H4,
            "D1": self._mt5.TIMEFRAME_D1,
        }
        tf_id = tf_map.get(tf, self._mt5.TIMEFRAME_M30)
        try:
            broker_symbol = self._broker_symbol(pair)
            requested = max(1, int(n))
            min_required = min(requested, 50)
            rates = None
            for attempt in range(3):
                rates = self._mt5.copy_rates_from_pos(broker_symbol, tf_id, 0, requested)
                if rates is not None and len(rates) >= min_required:
                    break
                if attempt < 2:
                    time.sleep(0.35 * (attempt + 1))
            got = 0 if rates is None else len(rates)
            if rates is None or got < min_required:
                raise RuntimeError(
                    f"NO REAL MT5 DATA for {pair} ({broker_symbol}) {tf} "
                    f"(requested={requested}, min_required={min_required}, got={got}). "
                    "Fix: MT5 terminal open + logged in? Symbols visible in Market Watch? "
                    "History Center (F2) downloaded for M30/H1/D1?"
                )

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
            raise RuntimeError(f"MT5 real data failed: {exc}") from exc

    def validate_market(self, pair: str, direction: str) -> ExecutionPrecheck:
        if self._sim:
            return ExecutionPrecheck(True, "SIM mode", 0.0, 0.0)
        if self._degraded:
            return ExecutionPrecheck(False, "Execution degraded", 0.0, 0.0)
        try:
            broker_symbol = self._broker_symbol(pair)
            tick = self._mt5.symbol_info_tick(broker_symbol)
            if not tick:
                return ExecutionPrecheck(False, "No symbol tick")
            symbol = self._mt5.symbol_info(broker_symbol)
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

        if not self._mt5.initialize():
            try:
                self._mt5.shutdown()
            except Exception:
                pass
            self._mt5.initialize()

        last_error: str | None = None
        broker_symbol = pair
        try:
            broker_symbol = self._broker_symbol(pair)
        except Exception as exc:
            last_error = f"symbol_resolution_failed:{exc}"
            log.error("order_failed pair=%s direction=%s reason=%s", pair, direction, last_error)
            return None

        for attempt in range(3):
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
                tick = self._mt5.symbol_info_tick(broker_symbol)
                sym = self._mt5.symbol_info(broker_symbol)
                if not tick or not sym:
                    last_error = "no_tick_or_symbol"
                    break
                max_spread = MAX_SPREAD_POINTS * float(getattr(sym, "point", 0.0) or 0.0)
                spread = float(tick.ask) - float(tick.bid)
                if max_spread > 0 and spread > max_spread:
                    last_error = f"spread_too_high:{spread:.6f}>{max_spread:.6f}"
                    log.warning("order_spread_blocked pair=%s direction=%s spread=%.6f max=%.6f", pair, direction, spread, max_spread)
                    return None

                sym = self._mt5.symbol_info(broker_symbol)
                if not sym:
                    last_error = "no_symbol_info"
                    log.error("order_failed pair=%s direction=%s reason=no_symbol_info", pair, direction)
                    break

                price = sym.ask if direction == "BUY" else sym.bid
                order_type = self._mt5.ORDER_TYPE_BUY if direction == "BUY" else self._mt5.ORDER_TYPE_SELL
                req = {
                    "action": self._mt5.TRADE_ACTION_DEAL,
                    "symbol": broker_symbol,
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
                        attempt + 1,
                    )
                    return int(result.order)

                last_error = f"retcode={getattr(result, 'retcode', None)}"
                log.error(
                    "order_failed pair=%s direction=%s attempt=%s result=%s",
                    pair,
                    direction,
                    attempt + 1,
                    result,
                )
                # Mark executor as degraded on hard MT5 errors so that heartbeat
                # can drive reconnection; keep retry bounded.
                self._handle_failure(f"order_failed:{last_error}")
            except Exception as exc:
                last_error = f"order_exc:{exc}"
                self._handle_failure(last_error)
                log.error("mt5_order_error pair=%s direction=%s attempt=%s error=%s", pair, direction, attempt + 1, exc)

            if attempt < 2:
                time.sleep(2 ** attempt)

        if last_error:
            log.error(
                "order_give_up pair=%s direction=%s attempts=%s last_error=%s",
                pair,
                direction,
                3,
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

    # === UPGRADE STEP 1 COMPLETED ===
