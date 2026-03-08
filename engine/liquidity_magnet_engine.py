from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LiquidityMagnet:
    target_price: float
    magnet_strength: float
    pool_type: str


@dataclass(frozen=True)
class LiquidityMagnetResult:
    primary_magnet: Optional[LiquidityMagnet]
    secondary_magnet: Optional[LiquidityMagnet]


class LiquidityMagnetEngine:
    """Ranks likely liquidity magnets from mapped pools and market context."""

    def analyze(self, liquidity_map, volatility_regime: str, displacement, current_price: float) -> LiquidityMagnetResult:
        if liquidity_map is None or not getattr(liquidity_map, "pools", None):
            return LiquidityMagnetResult(None, None)

        regime = (volatility_regime or "NORMAL").upper()
        direction = getattr(displacement, "direction", "NONE")
        displacement_strength = float(getattr(displacement, "strength", 0.0) or 0.0)

        scored: list[tuple[float, object]] = []
        for pool in liquidity_map.pools:
            distance = abs(pool.price - current_price)
            distance_weight = self._distance_weight(distance, regime)
            regime_weight = 1.15 if regime == "EXPANSION" else (0.95 if regime == "COMPRESSION" else 1.0)
            displacement_alignment = self._displacement_alignment(pool.price, current_price, direction, displacement_strength)
            score = max(0.0, min(1.0, pool.strength * distance_weight * regime_weight * displacement_alignment))
            scored.append((score, pool))

        scored.sort(key=lambda x: x[0], reverse=True)
        primary = self._to_magnet(scored[0]) if scored else None
        secondary = self._to_magnet(scored[1]) if len(scored) > 1 else None
        return LiquidityMagnetResult(primary_magnet=primary, secondary_magnet=secondary)

    def _distance_weight(self, distance: float, regime: str) -> float:
        if regime == "EXPANSION":
            return min(1.4, 0.9 + distance / 12.0)
        if regime == "COMPRESSION":
            return max(0.6, 1.2 - distance / 10.0)
        return max(0.7, min(1.2, 1.0 - distance / 40.0))

    def _displacement_alignment(self, level: float, current_price: float, direction: str, strength: float) -> float:
        if direction == "UP":
            return 1.0 + 0.45 * strength if level > current_price else 0.85
        if direction == "DOWN":
            return 1.0 + 0.45 * strength if level < current_price else 0.85
        return 1.0

    def _to_magnet(self, scored_entry: tuple[float, object]) -> LiquidityMagnet:
        score, pool = scored_entry
        return LiquidityMagnet(target_price=pool.price, magnet_strength=round(score, 4), pool_type=pool.type)
