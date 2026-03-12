from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

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

        dxy, dxy_change_pct = self._fetch_yahoo_symbol("DX-Y.NYB")
        us10y, us10y_change_pct = self._fetch_yahoo_symbol("^TNX")
        us10y_change_bps = None if us10y_change_pct is None else us10y_change_pct * 100.0
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

    def _fetch_yahoo_symbol(self, symbol: str) -> tuple[float | None, float | None]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            result = payload.get("chart", {}).get("result", [])
            if not result:
                raise RuntimeError("missing chart result")

            quotes = result[0].get("indicators", {}).get("quote", [])
            if not quotes:
                raise RuntimeError("missing quote payload")
            closes = [x for x in (quotes[0].get("close") or []) if isinstance(x, (int, float))]
            if len(closes) < 2:
                raise RuntimeError("not enough close points")

            current = float(closes[-1])
            previous = float(closes[-2])
            change_pct = ((current - previous) / max(abs(previous), 1e-9)) * 100.0
            return current, round(change_pct, 4)
        except Exception as exc:
            log.error("macro_symbol_fetch_failed symbol=%s error=%s", symbol, exc)
            return None, None

    def _fetch_high_impact_usd_events(self) -> int:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        now = datetime.now(tz=timezone.utc)
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            events = response.json()
            if not isinstance(events, list):
                return 0

            high_impact_count = 0
            for event in events:
                if not isinstance(event, dict):
                    continue
                if str(event.get("country", "")).upper() not in ("USD", "US"):
                    continue
                if str(event.get("impact", "")).strip().lower() != "high":
                    continue
                date_value = str(event.get("date", "")).strip()
                if not date_value:
                    continue
                parsed = self._parse_event_time(date_value)
                if parsed is None:
                    continue
                if abs((parsed - now).total_seconds()) <= 3 * 3600:
                    high_impact_count += 1
            return high_impact_count
        except Exception as exc:
            log.error("macro_calendar_fetch_failed error=%s", exc)
            return 0

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



