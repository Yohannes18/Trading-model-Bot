"""
Liquidity Map Engine
Detects concentrated liquidity pools and nearest magnets for likely price targeting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass(frozen=True)
class LiquidityPool:
    price: float
    strength: float
    type: str


@dataclass(frozen=True)
class LiquidityMapResult:
    pools: List[LiquidityPool]
    nearest_above: Optional[LiquidityPool]
    nearest_below: Optional[LiquidityPool]


class LiquidityMapEngine:
    def analyze(
        self,
        candles: List,
        current_price: float,
        atr: float,
        session,
        session_high: float | None = None,
        session_low: float | None = None,
        tolerance_factor: float = 0.05,
    ) -> LiquidityMapResult:
        if not candles:
            return LiquidityMapResult([], None, None)

        candles = candles[-160:] if len(candles) > 160 else candles

        highs = np.array([float(c.high) for c in candles], dtype=np.float64)
        lows = np.array([float(c.low) for c in candles], dtype=np.float64)
        ranges = highs - lows

        atr_value = float(max(atr, 1e-9))
        tolerance = max(float(tolerance_factor) * atr_value, 1e-6)

        pools: list[LiquidityPool] = []
        pools.extend(self._equal_levels(highs, tolerance, current_price, atr_value, "equal_highs"))
        pools.extend(self._equal_levels(lows, tolerance, current_price, atr_value, "equal_lows"))
        pools.extend(self._swing_levels(highs, lows, current_price, atr_value))

        sh, sl = self._session_levels(candles, session, session_high, session_low)
        if sh is not None:
            pools.append(self._build_pool(sh, 1.0, current_price, atr_value, "session_high", session_boost=0.22))
        if sl is not None:
            pools.append(self._build_pool(sl, 1.0, current_price, atr_value, "session_low", session_boost=0.22))

        pools.extend(self._consolidation_levels(highs, lows, ranges, current_price, atr_value))
        pools.extend(self._round_number_levels(current_price, atr_value))

        pools = self._apply_cluster_density(pools, atr_value)
        pools = self._deduplicate_pools(pools, tolerance)

        nearest_above = self._nearest_pool(pools, current_price, above=True)
        nearest_below = self._nearest_pool(pools, current_price, above=False)
        return LiquidityMapResult(pools=sorted(pools, key=lambda p: p.price), nearest_above=nearest_above, nearest_below=nearest_below)

    def _equal_levels(self, xs: np.ndarray, tolerance: float, current_price: float, atr: float, pool_type: str) -> list[LiquidityPool]:
        if xs.size < 4:
            return []
        if xs.size > 120:
            xs = xs[-120:]
        bins = np.rint(xs / tolerance).astype(np.int64)
        uniq, counts = np.unique(bins, return_counts=True)

        pools: list[LiquidityPool] = []
        qualified = list(zip(uniq[counts >= 2], counts[counts >= 2]))
        qualified.sort(key=lambda x: x[1], reverse=True)
        for bucket, count in qualified[:6]:
            if count < 2:
                continue
            idx = np.where(bins == bucket)[0]
            level = float(np.mean(xs[idx]))
            touch_weight = min(0.45, 0.12 * float(count))
            pools.append(self._build_pool(level, touch_weight, current_price, atr, pool_type))
        return pools

    def _swing_levels(self, highs: np.ndarray, lows: np.ndarray, current_price: float, atr: float) -> list[LiquidityPool]:
        if highs.size < 5:
            return []
        h_mid = highs[1:-1]
        swing_high_idx = np.where((h_mid > highs[:-2]) & (h_mid > highs[2:]))[0] + 1
        l_mid = lows[1:-1]
        swing_low_idx = np.where((l_mid < lows[:-2]) & (l_mid < lows[2:]))[0] + 1

        pools: list[LiquidityPool] = []
        for idx in swing_high_idx[-4:]:
            pools.append(self._build_pool(float(highs[idx]), 0.28, current_price, atr, "swing_high"))
        for idx in swing_low_idx[-4:]:
            pools.append(self._build_pool(float(lows[idx]), 0.28, current_price, atr, "swing_low"))
        return pools

    def _session_levels(self, candles: List, session, session_high: float | None, session_low: float | None) -> tuple[float | None, float | None]:
        if session_high is not None and session_high > 0 and session_low is not None and session_low > 0:
            return float(session_high), float(session_low)

        session_name = str(getattr(session, "value", session)).upper()
        if session_name == "ASIA":
            hours = (0, 7)
        elif session_name == "LONDON":
            hours = (7, 13)
        elif session_name == "NEW_YORK":
            hours = (12, 17)
        elif session_name == "LONDON_NY_OVERLAP":
            hours = (12, 15)
        else:
            hours = (0, 24)

        filtered = [c for c in candles[-80:] if hours[0] <= c.time.hour < hours[1]]
        if not filtered:
            return None, None
        return max(float(c.high) for c in filtered), min(float(c.low) for c in filtered)

    def _consolidation_levels(self, highs: np.ndarray, lows: np.ndarray, ranges: np.ndarray, current_price: float, atr: float) -> list[LiquidityPool]:
        if highs.size < 24:
            return []
        recent_h = highs[-20:]
        recent_l = lows[-20:]
        recent_r = ranges[-20:]

        total_range = float(np.max(recent_h) - np.min(recent_l))
        avg_range = float(np.mean(recent_r))
        overlap = np.minimum(recent_h[1:], recent_h[:-1]) - np.maximum(recent_l[1:], recent_l[:-1])
        overlap_ratio = float(np.mean(np.clip(overlap / np.maximum(recent_r[1:], 1e-9), 0.0, 1.0)))

        compression = total_range < 2.2 * atr and avg_range < 0.8 * atr and overlap_ratio > 0.55
        if not compression:
            return []

        range_high = float(np.max(recent_h))
        range_low = float(np.min(recent_l))
        return [
            self._build_pool(range_high, 0.30, current_price, atr, "range_high"),
            self._build_pool(range_low, 0.30, current_price, atr, "range_low"),
        ]

    def _round_number_levels(self, current_price: float, atr: float) -> list[LiquidityPool]:
        step = 0.5
        start = np.floor((current_price - 3 * atr) / step) * step
        end = np.ceil((current_price + 3 * atr) / step) * step
        levels = np.arange(start, end + step / 2, step)
        near = levels[np.abs(levels - current_price) <= 0.25 * atr]
        if near.size > 4:
            near = near[:4]
        return [self._build_pool(float(level), 0.20, current_price, atr, "round_number") for level in near]

    def _build_pool(self, level: float, touch_weight: float, current_price: float, atr: float, pool_type: str, session_boost: float = 0.0) -> LiquidityPool:
        distance_r = abs(level - current_price) / max(atr, 1e-9)
        distance_weight = max(0.0, 0.30 * (1.0 / (1.0 + distance_r)))
        strength = max(0.0, min(1.0, touch_weight + distance_weight + session_boost))
        return LiquidityPool(price=round(level, 2), strength=round(strength, 4), type=pool_type)

    def _apply_cluster_density(self, pools: list[LiquidityPool], atr: float) -> list[LiquidityPool]:
        if not pools:
            return []
        band = max(0.25 * atr, 1e-6)
        prices = np.array([p.price for p in pools], dtype=np.float64)
        bucket = np.rint(prices / band).astype(np.int64)
        uniq, counts = np.unique(bucket, return_counts=True)
        bucket_counts = {int(b): int(c) for b, c in zip(uniq, counts)}

        out: list[LiquidityPool] = []
        for pool, b in zip(pools, bucket):
            density = max(0, bucket_counts.get(int(b), 1) - 1)
            cluster_boost = min(0.2, 0.05 * float(density))
            strength = max(0.0, min(1.0, pool.strength + cluster_boost))
            out.append(LiquidityPool(pool.price, round(strength, 4), pool.type))
        return out

    def _deduplicate_pools(self, pools: list[LiquidityPool], tolerance: float) -> list[LiquidityPool]:
        if not pools:
            return []
        pools_sorted = sorted(pools, key=lambda p: (p.type, p.price))
        dedup: list[LiquidityPool] = []
        for pool in pools_sorted:
            if not dedup:
                dedup.append(pool)
                continue
            prev = dedup[-1]
            if prev.type == pool.type and abs(prev.price - pool.price) <= tolerance:
                merged = LiquidityPool(
                    price=round((prev.price + pool.price) / 2, 2),
                    strength=round(max(prev.strength, pool.strength), 4),
                    type=pool.type,
                )
                dedup[-1] = merged
            else:
                dedup.append(pool)
        return dedup

    def _nearest_pool(self, pools: list[LiquidityPool], current_price: float, above: bool) -> Optional[LiquidityPool]:
        if above:
            cands = [p for p in pools if p.price > current_price]
            if not cands:
                return None
            return min(cands, key=lambda p: p.price)
        cands = [p for p in pools if p.price < current_price]
        if not cands:
            return None
        return max(cands, key=lambda p: p.price)
