from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from quantara.strategy.types import SessionType, VolatilityAnalysis, VolatilityRegime


class VolatilityExpansionEngine:
    """Detects volatility regime and expansion probability for model gating."""

    def analyze(self, candles_m30, session: SessionType) -> VolatilityAnalysis:
        if not candles_m30 or len(candles_m30) < 60:
            return VolatilityAnalysis(
                regime=VolatilityRegime.NORMAL,
                atr=0.0,
                atr_baseline=0.0,
                atr_ratio=1.0,
                expansion_probability=0.0,
                range_ratio=1.0,
                compression_score=0.0,
                expansion_score=0.0,
            )

        atr = self._atr(candles_m30, 14)
        atr_baseline = self._atr_series_baseline(candles_m30, period=14, lookback=50)
        atr_ratio = atr / atr_baseline if atr_baseline > 0 else 1.0

        current_range, avg_range = self._session_range_ratio(candles_m30, session)
        range_ratio = current_range / avg_range if avg_range > 0 else 1.0

        impulse_signal = 1.0 if self._impulse_detected(candles_m30) else 0.0
        small_ratio = self._small_candle_ratio(candles_m30)

        compression_flags = [
            1.0 if atr_ratio < 0.75 else 0.0,
            1.0 if range_ratio < 0.80 else 0.0,
            small_ratio,
        ]
        compression_score = min(1.0, sum(compression_flags) / 3.0)

        atr_norm = min(1.0, max(0.0, atr_ratio / 1.5))
        range_norm = min(1.0, max(0.0, range_ratio / 1.5))
        expansion_score = min(1.0, 0.4 * atr_norm + 0.3 * range_norm + 0.3 * impulse_signal)

        if compression_score > 0.65:
            regime = VolatilityRegime.COMPRESSION
        elif expansion_score > 0.65:
            regime = VolatilityRegime.EXPANSION
        else:
            regime = VolatilityRegime.NORMAL

        return VolatilityAnalysis(
            regime=regime,
            atr=round(atr, 4),
            atr_baseline=round(atr_baseline, 4),
            atr_ratio=round(atr_ratio, 4),
            expansion_probability=round(expansion_score, 4),
            range_ratio=round(range_ratio, 4),
            compression_score=round(compression_score, 4),
            expansion_score=round(expansion_score, 4),
        )

    def _atr(self, candles, period: int) -> float:
        xs = candles[-period:] if len(candles) >= period else candles
        if not xs:
            return 0.0
        return sum((c.high - c.low) for c in xs) / len(xs)

    def _atr_series_baseline(self, candles, period: int, lookback: int) -> float:
        if len(candles) < period + 2:
            return self._atr(candles, period)
        end = len(candles)
        start = max(period, end - lookback)
        values: list[float] = []
        for idx in range(start, end):
            window = candles[max(0, idx - period + 1): idx + 1]
            if len(window) < period:
                continue
            values.append(sum((c.high - c.low) for c in window) / period)
        if not values:
            return self._atr(candles, period)
        return sum(values) / len(values)

    def _session_range_ratio(self, candles, session: SessionType) -> tuple[float, float]:
        start_h, end_h = self._session_window(session)
        now_date = datetime.now(tz=timezone.utc).date()

        def in_window(candle, day):
            if candle.time.date() != day:
                return False
            h = candle.time.hour
            if start_h <= end_h:
                return start_h <= h < end_h
            return h >= start_h or h < end_h

        current = [c for c in candles if in_window(c, now_date)]
        current_range = (max((c.high for c in current), default=0.0) - min((c.low for c in current), default=0.0)) if current else 0.0

        unique_days = sorted({c.time.date() for c in candles if c.time.date() < now_date}, reverse=True)
        hist_ranges: list[float] = []
        for d in unique_days[:10]:
            cs = [c for c in candles if in_window(c, d)]
            if not cs:
                continue
            hist_ranges.append(max(c.high for c in cs) - min(c.low for c in cs))

        avg_range = sum(hist_ranges) / len(hist_ranges) if hist_ranges else (current_range if current_range > 0 else 1.0)
        return current_range, avg_range

    def _session_window(self, session: SessionType) -> tuple[int, int]:
        if session == SessionType.ASIA:
            return (0, 6)
        if session == SessionType.LONDON:
            return (6, 13)
        if session == SessionType.NEW_YORK:
            return (13, 21)
        if session == SessionType.LONDON_NY_OVERLAP:
            return (12, 15)
        return (0, 24)

    def _impulse_detected(self, candles) -> bool:
        if len(candles) < 30:
            return False
        last = candles[-1]
        bodies = [abs(c.close - c.open) for c in candles[-21:-1]]
        ranges = [(c.high - c.low) for c in candles[-21:-1]]
        avg_body = (sum(bodies) / len(bodies)) if bodies else 0.0
        avg_range = (sum(ranges) / len(ranges)) if ranges else 0.0
        body = abs(last.close - last.open)
        rng = (last.high - last.low)
        return (avg_body > 0 and body > 2 * avg_body) or (avg_range > 0 and rng > 1.8 * avg_range)

    def _small_candle_ratio(self, candles) -> float:
        if len(candles) < 20:
            return 0.0
        recent = candles[-12:]
        avg_range = sum((c.high - c.low) for c in candles[-50:]) / max(len(candles[-50:]), 1)
        if avg_range <= 0:
            return 0.0
        small = sum(1 for c in recent if (c.high - c.low) < avg_range * 0.6)
        return small / len(recent)
