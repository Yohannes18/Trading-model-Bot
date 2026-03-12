from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StructuredLiquidityZone:
    zone_type: str
    side: str
    price_low: float
    price_high: float
    timeframe: str
    score: int
    metadata: dict[str, float | str] = field(default_factory=dict)

    @property
    def midpoint(self) -> float:
        return round((self.price_low + self.price_high) / 2.0, 5)


class InstitutionalLiquidityHeatmapEngine:
    """Builds structured institutional liquidity zones for narrative and model context."""

    def build_zones(
        self,
        candles_m30: list[Any],
        candles_d1: list[Any],
        fvg_ranges: list[tuple[float, float, str]],
        order_blocks: list[tuple[float, float, str, float]],
    ) -> list[StructuredLiquidityZone]:
        zones: list[StructuredLiquidityZone] = []
        zones.extend(self._weekly_levels(candles_d1))
        zones.extend(self._equal_levels(candles_m30))
        zones.extend(self._fvg_zones(fvg_ranges))
        zones.extend(self._order_block_zones(order_blocks))
        return self._merge_zones(zones)

    def _weekly_levels(self, candles_d1: list[Any]) -> list[StructuredLiquidityZone]:
        if len(candles_d1) < 5:
            return []
        week = candles_d1[-5:]
        weekly_high = max(float(c.high) for c in week)
        weekly_low = min(float(c.low) for c in week)
        return [
            StructuredLiquidityZone(
                zone_type="WeeklyHigh",
                side="ABOVE",
                price_low=weekly_high,
                price_high=weekly_high,
                timeframe="W1",
                score=8,
                metadata={"source": "last_5_daily"},
            ),
            StructuredLiquidityZone(
                zone_type="WeeklyLow",
                side="BELOW",
                price_low=weekly_low,
                price_high=weekly_low,
                timeframe="W1",
                score=8,
                metadata={"source": "last_5_daily"},
            ),
        ]

    def _equal_levels(self, candles_m30: list[Any]) -> list[StructuredLiquidityZone]:
        if len(candles_m30) < 20:
            return []
        lookback = candles_m30[-120:]
        avg_range = sum(max(0.0, float(c.high) - float(c.low)) for c in lookback) / max(1, len(lookback))
        tolerance = max(avg_range * 0.08, 0.05)

        highs: list[float] = []
        lows: list[float] = []
        for candle in lookback:
            high = float(candle.high)
            low = float(candle.low)
            if not any(abs(high - x) <= tolerance for x in highs):
                highs.append(high)
            if not any(abs(low - x) <= tolerance for x in lows):
                lows.append(low)

        eq_high_zones = [
            StructuredLiquidityZone(
                zone_type="EqualHighs",
                side="ABOVE",
                price_low=level,
                price_high=level,
                timeframe="M30",
                score=6,
                metadata={"tolerance": round(tolerance, 5)},
            )
            for level in highs
            if sum(1 for c in lookback if abs(float(c.high) - level) <= tolerance) >= 2
        ]
        eq_low_zones = [
            StructuredLiquidityZone(
                zone_type="EqualLows",
                side="BELOW",
                price_low=level,
                price_high=level,
                timeframe="M30",
                score=6,
                metadata={"tolerance": round(tolerance, 5)},
            )
            for level in lows
            if sum(1 for c in lookback if abs(float(c.low) - level) <= tolerance) >= 2
        ]
        return eq_high_zones[:6] + eq_low_zones[:6]

    def _fvg_zones(self, fvg_ranges: list[tuple[float, float, str]]) -> list[StructuredLiquidityZone]:
        zones: list[StructuredLiquidityZone] = []
        for low, high, direction in fvg_ranges:
            if low <= 0 or high <= 0 or high <= low:
                continue
            side = "ABOVE" if direction == "BUY" else "BELOW"
            zones.append(
                StructuredLiquidityZone(
                    zone_type="FVG",
                    side=side,
                    price_low=round(low, 5),
                    price_high=round(high, 5),
                    timeframe="M30",
                    score=5,
                    metadata={"direction": direction},
                )
            )
        return zones

    def _order_block_zones(self, order_blocks: list[tuple[float, float, str, float]]) -> list[StructuredLiquidityZone]:
        zones: list[StructuredLiquidityZone] = []
        for low, high, direction, quality in order_blocks:
            if low <= 0 or high <= 0 or high <= low:
                continue
            side = "ABOVE" if direction == "BUY" else "BELOW"
            score = 5 if quality >= 0.5 else 4
            zones.append(
                StructuredLiquidityZone(
                    zone_type="OrderBlock",
                    side=side,
                    price_low=round(low, 5),
                    price_high=round(high, 5),
                    timeframe="M30",
                    score=score,
                    metadata={"direction": direction, "quality": round(quality, 4)},
                )
            )
        return zones

    def _merge_zones(self, zones: list[StructuredLiquidityZone]) -> list[StructuredLiquidityZone]:
        merged: dict[tuple[str, str, float, float], StructuredLiquidityZone] = {}
        for zone in zones:
            key = (zone.zone_type, zone.side, round(zone.price_low, 2), round(zone.price_high, 2))
            existing = merged.get(key)
            if existing is None:
                merged[key] = zone
                continue
            merged[key] = StructuredLiquidityZone(
                zone_type=zone.zone_type,
                side=zone.side,
                price_low=zone.price_low,
                price_high=zone.price_high,
                timeframe=zone.timeframe,
                score=max(existing.score, zone.score),
                metadata={**existing.metadata, **zone.metadata},
            )
        return sorted(merged.values(), key=lambda z: z.score, reverse=True)


