from __future__ import annotations

import logging
import importlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from quantara.strategy.types import MacroBias

log = logging.getLogger("quantara.macro.v2")


@dataclass(frozen=True)
class MacroSnapshot:
    dxy: float | None
    dxy_change_pct: float | None
    us10y: float | None
    us10y_change_bps: float | None
    high_impact_events: int
    calendar_risk: bool
    gold_bias: MacroBias
    pressure: float
    fetched_at: datetime

    def to_context(self) -> dict[str, object]:
        return {
            "dxy": self.dxy,
            "dxy_change_pct": self.dxy_change_pct,
            "us10y": self.us10y,
            "us10y_change_bps": self.us10y_change_bps,
            "high_impact_events": self.high_impact_events,
            "calendar_risk": self.calendar_risk,
            "gold_bias": self.gold_bias.value,
            "pressure": self.pressure,
            "fetched_at": self.fetched_at.isoformat(),
        }


class MacroEngine:
    def __init__(self) -> None:
        self._cache: MacroSnapshot | None = None
        self._cache_ts: float = 0.0

    def get_snapshot(self, cache_ttl_seconds: int = 180) -> MacroSnapshot:
        now = time.time()
        if self._cache is not None and now - self._cache_ts <= float(cache_ttl_seconds):
            return self._cache

        dxy, dxy_change_pct = self._fetch_dxy_data()
        us10y, us10y_change_bps = self._fetch_us10y_data()
        high_impact_events = self._fetch_high_impact_usd_events()
        calendar_risk = high_impact_events > 0

        pressure = self._compute_gold_pressure(dxy_change_pct, us10y_change_bps, calendar_risk)
        bias = self._bias_from_pressure(pressure)

        snapshot = MacroSnapshot(
            dxy=dxy,
            dxy_change_pct=dxy_change_pct,
            us10y=us10y,
            us10y_change_bps=us10y_change_bps,
            high_impact_events=high_impact_events,
            calendar_risk=calendar_risk,
            gold_bias=bias,
            pressure=pressure,
            fetched_at=datetime.now(tz=timezone.utc),
        )
        self._cache = snapshot
        self._cache_ts = now
        log.info(
            "macro_snapshot dxy=%s dxy_change_pct=%s us10y=%s us10y_change_bps=%s calendar_risk=%s pressure=%s bias=%s",
            dxy,
            dxy_change_pct,
            us10y,
            us10y_change_bps,
            calendar_risk,
            pressure,
            bias.value,
        )
        return snapshot

    def evaluate(self, snapshot: MacroSnapshot | None = None) -> MacroBias:
        snap = snapshot or self.get_snapshot()
        return snap.gold_bias

    def _fetch_dxy_data(self) -> tuple[float | None, float | None]:
        dxy, dxy_change_pct = self._fetch_mt5_series(
            candidates=("DXY", "USDX", "DX", "DX-Y.NYB", "^DXY"),
            as_yield=False,
        )
        if dxy is not None and self._is_plausible_dxy(dxy):
            return dxy, dxy_change_pct

        dxy = self._fetch_investing_last("https://www.investing.com/indices/usdollar", low=70.0, high=140.0)
        if dxy is not None and self._is_plausible_dxy(dxy):
            previous_dxy = self._cache.dxy if self._cache is not None else None
            if previous_dxy is None or abs(previous_dxy) < 1e-9:
                return dxy, None

            dxy_change_pct = ((dxy - previous_dxy) / abs(previous_dxy)) * 100.0
            return dxy, round(dxy_change_pct, 4)

        return None, None

    def _fetch_us10y_data(self) -> tuple[float | None, float | None]:
        us10y, us10y_change_pct = self._fetch_mt5_series(
            candidates=("US10Y", "UST10Y", "TNX", "^TNX"),
            as_yield=True,
        )
        if us10y is not None and self._is_plausible_us10y(us10y):
            us10y_change_bps = None if us10y_change_pct is None else us10y * us10y_change_pct
            return us10y, us10y_change_bps

        us10y = self._fetch_investing_last("https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield", low=0.0, high=15.0)
        if us10y is not None and self._is_plausible_us10y(us10y):
            previous_us10y = self._cache.us10y if self._cache is not None else None
            if previous_us10y is None:
                return us10y, None

            us10y_change_bps = (us10y - previous_us10y) * 100.0
            return us10y, round(us10y_change_bps, 4)

        return None, None

    def _is_plausible_dxy(self, value: float) -> bool:
        return 70.0 <= value <= 140.0

    def _is_plausible_us10y(self, value: float) -> bool:
        return 0.0 <= value <= 15.0

    def _fetch_investing_last(self, url: str, low: float | None = None, high: float | None = None) -> float | None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        try:
            response = requests.get(url, headers=headers, timeout=8)
            response.raise_for_status()

            def _in_range(value: float) -> bool:
                if low is not None and value < low:
                    return False
                if high is not None and value > high:
                    return False
                return True

            soup = BeautifulSoup(response.text, "html.parser")
            node = soup.select_one('[data-test="instrument-price-last"]')
            if node is not None:
                text_value = str(node.get_text(strip=True)).replace(",", "")
                try:
                    parsed = float(text_value)
                    if _in_range(parsed):
                        return parsed
                except ValueError:
                    pass

            for match in re.finditer(r'"last":"([0-9,.]+)"', response.text):
                try:
                    parsed = float(match.group(1).replace(",", ""))
                    if _in_range(parsed):
                        return parsed
                except ValueError:
                    continue

            raise RuntimeError("missing in-range last value in payload")
        except Exception as exc:
            log.error("macro_investing_fetch_failed url=%s error=%s", url, exc)
            return None

    def _fetch_mt5_series(self, candidates: tuple[str, ...], as_yield: bool) -> tuple[float | None, float | None]:
        try:
            mt5 = importlib.import_module("MetaTrader5")
        except Exception:
            return None, None

        try:
            if hasattr(mt5, "terminal_info") and mt5.terminal_info() is None:
                return None, None

            tf_d1 = getattr(mt5, "TIMEFRAME_D1", None)
            if tf_d1 is None:
                return None, None

            for symbol in candidates:
                try:
                    if hasattr(mt5, "symbol_select") and not mt5.symbol_select(symbol, True):
                        continue

                    tick = mt5.symbol_info_tick(symbol)
                    if tick is None:
                        continue

                    current = float(getattr(tick, "last", 0.0) or getattr(tick, "bid", 0.0) or getattr(tick, "ask", 0.0) or 0.0)
                    if current <= 0:
                        continue

                    rates = mt5.copy_rates_from_pos(symbol, tf_d1, 0, 3)
                    previous = None
                    if rates is not None and len(rates) >= 2:
                        close_now = float(rates[-1]["close"])
                        close_prev = float(rates[-2]["close"])
                        previous = close_prev if close_prev > 0 else None
                        current = close_now if close_now > 0 else current

                    if as_yield and current > 20.0:
                        current = current / 10.0
                    if as_yield and previous is not None and previous > 20.0:
                        previous = previous / 10.0

                    if previous is None or abs(previous) < 1e-9:
                        return current, None

                    change_pct = ((current - previous) / abs(previous)) * 100.0
                    return current, round(change_pct, 4)
                except Exception:
                    continue

            return None, None
        except Exception as exc:
            log.error("macro_mt5_fetch_failed candidates=%s error=%s", candidates, exc)
            return None, None

    def _fetch_high_impact_usd_events(self) -> int:
        url = "https://www.investing.com/economic-calendar/"
        now = datetime.now(tz=timezone.utc)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("tr.js-event-item")
            if not rows:
                return 0

            high_impact_count = 0
            for row in rows:
                currency = str(row.get("data-event-currency", "")).strip().upper()
                if not currency:
                    cur_node = row.select_one("td.flagCur")
                    currency = str(cur_node.get_text(strip=True) if cur_node else "").upper()
                if currency != "USD":
                    continue

                impact_score_raw = str(row.get("data-event-importance", "")).strip()
                impact_score = int(impact_score_raw) if impact_score_raw.isdigit() else 0
                if impact_score < 3:
                    bulls = len(row.select("td.sentiment i.grayFullBullishIcon"))
                    if bulls < 3:
                        continue

                date_value = str(row.get("data-event-datetime", "")).strip()
                if not date_value:
                    time_node = row.select_one("td.time")
                    date_value = str(time_node.get("data-value", "") if time_node else "").strip()
                parsed = self._parse_investing_event_time(date_value)
                if parsed is None:
                    continue

                if abs((parsed - now).total_seconds()) <= 3 * 3600:
                    high_impact_count += 1
            return high_impact_count
        except Exception as exc:
            log.error("macro_calendar_fetch_failed url=%s error=%s", url, exc)
            return 0

    def _parse_investing_event_time(self, value: str) -> datetime | None:
        if not value:
            return None
        formats = (
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        )
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return self._parse_event_time(value)

    def _parse_event_time(self, value: str) -> datetime | None:
        formats = (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S%z",
        )
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).astimezone(timezone.utc)
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def _compute_gold_pressure(self, dxy_change_pct: float | None, us10y_change_bps: float | None, calendar_risk: bool) -> float:
        dxy_norm = 0.0
        us10y_norm = 0.0

        if dxy_change_pct is not None:
            dxy_norm = max(-1.0, min(1.0, -(dxy_change_pct / 0.5)))
        if us10y_change_bps is not None:
            us10y_norm = max(-1.0, min(1.0, -(us10y_change_bps / 7.5)))

        pressure = (0.6 * dxy_norm) + (0.4 * us10y_norm)
        if calendar_risk:
            pressure *= 0.7
        return round(max(-1.0, min(1.0, pressure)), 4)

    def _bias_from_pressure(self, pressure: float) -> MacroBias:
        if pressure >= 0.2:
            return MacroBias.BULLISH_GOLD
        if pressure <= -0.2:
            return MacroBias.BEARISH_GOLD
        return MacroBias.NEUTRAL



