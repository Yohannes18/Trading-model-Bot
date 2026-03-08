"""
Liquidity Regime Engine
Detects market liquidity environment based on volatility, sweeps,
inefficiencies and displacement to guide model selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

import numpy as np


class LiquidityRegime(Enum):
    ACCUMULATION = "accumulation"
    EXPANSION = "expansion"
    MANIPULATION = "manipulation"
    DISTRIBUTION = "distribution"


@dataclass(frozen=True)
class LiquidityRegimeResult:
    regime: LiquidityRegime
    accumulation_score: float
    expansion_score: float
    manipulation_score: float
    distribution_score: float


class LiquidityRegimeEngine:
    def analyze(
        self,
        candles: List,
        session,
        volatility_profile,
        amd_state,
        heatmap_zones,
        raid_signals,
    ) -> LiquidityRegimeResult:
        if not candles or len(candles) < 20:
            return LiquidityRegimeResult(LiquidityRegime.ACCUMULATION, 1.0, 0.0, 0.0, 0.0)

        highs = np.array([float(c.high) for c in candles], dtype=np.float64)
        lows = np.array([float(c.low) for c in candles], dtype=np.float64)
        closes = np.array([float(c.close) for c in candles], dtype=np.float64)
        opens = np.array([float(c.open) for c in candles], dtype=np.float64)
        volumes = np.array([float(getattr(c, "volume", 0.0) or 0.0) for c in candles], dtype=np.float64)

        ranges = highs - lows
        bodies = np.abs(closes - opens)
        atr = float(np.mean(ranges[-14:])) if len(ranges) >= 14 else float(np.mean(ranges))
        atr = max(atr, 1e-9)

        current_range = float(ranges[-1])
        rolling_mean_range = float(np.mean(ranges[-20:]))
        compression_raw = max(0.0, min(1.0, 1.0 - (current_range / max(rolling_mean_range * 0.6, 1e-9))))

        close_change = float(abs(closes[-1] - closes[-2]))
        displacement_signal = max(0.0, min(1.0, (close_change / (1.2 * atr)) - 1.0))
        trend_continuation = self._trend_continuation(closes)

        raid_detected = bool(getattr(raid_signals, "probability", 0.0) >= 0.4) if raid_signals is not None else False
        sweep_detected = bool(getattr(raid_signals, "raid_direction", "NONE") in ("UP", "DOWN")) if raid_signals is not None else False
        follow_through = float(abs(closes[-1] - closes[-2]))
        sweep_fail = 1.0 if (raid_detected and sweep_detected and follow_through < 0.5 * atr) else 0.0

        recent_ranges = ranges[-6:]
        recent_bodies = bodies[-6:]
        decreasing_vol = float(np.mean(recent_ranges[-3:]) < np.mean(recent_ranges[:3]))
        wick_ratio = np.where(ranges > 0, (ranges - bodies) / np.maximum(ranges, 1e-9), 0.0)
        wick_increase = float(np.mean(wick_ratio[-3:]) > np.mean(wick_ratio[-8:-3])) if len(wick_ratio) >= 8 else 0.0
        hh_weak_close = float(self._higher_highs_weak_closes(highs, closes))
        momentum_decay = max(0.0, min(1.0, 0.4 * decreasing_vol + 0.3 * wick_increase + 0.3 * hh_weak_close))

        ineff_clusters = self._ime_cluster_signal(heatmap_zones)
        vacuum_expansion = max(0.0, min(1.0, 0.55 * ineff_clusters + 0.45 * displacement_signal))

        vol_regime = str(getattr(getattr(volatility_profile, "regime", "NORMAL"), "value", "NORMAL")).upper()
        vol_expansion_prob = float(getattr(volatility_profile, "expansion_probability", 0.5) or 0.5)
        amd_phase = str(getattr(getattr(amd_state, "phase", "UNKNOWN"), "value", "UNKNOWN")).upper()

        accumulation = 0.45 * compression_raw + 0.20 * (1.0 - vol_expansion_prob) + 0.20 * (1.0 - displacement_signal) + 0.15 * (1.0 if amd_phase == "ACCUMULATION" else 0.0)
        expansion = 0.45 * displacement_signal + 0.20 * trend_continuation + 0.20 * vol_expansion_prob + 0.15 * vacuum_expansion
        manipulation = 0.50 * sweep_fail + 0.20 * (1.0 - trend_continuation) + 0.15 * wick_increase + 0.15 * (1.0 if amd_phase == "MANIPULATION" else 0.0)
        distribution = 0.50 * momentum_decay + 0.20 * (1.0 - trend_continuation) + 0.15 * wick_increase + 0.15 * (1.0 if amd_phase == "DISTRIBUTION" else 0.0)

        if vol_regime == "COMPRESSION":
            accumulation += 0.08
        elif vol_regime == "EXPANSION":
            expansion += 0.08

        session_value = str(getattr(session, "value", session)).upper()
        if session_value == "ASIA":
            accumulation += 0.05
        elif session_value in ("LONDON", "LONDON_NY_OVERLAP"):
            expansion += 0.04

        scores = np.array([
            max(0.0, accumulation),
            max(0.0, expansion),
            max(0.0, manipulation),
            max(0.0, distribution),
        ], dtype=np.float64)
        total = float(np.sum(scores))
        if total <= 1e-9:
            normalized = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        else:
            normalized = scores / total

        regimes = [
            LiquidityRegime.ACCUMULATION,
            LiquidityRegime.EXPANSION,
            LiquidityRegime.MANIPULATION,
            LiquidityRegime.DISTRIBUTION,
        ]
        regime = regimes[int(np.argmax(normalized))]

        return LiquidityRegimeResult(
            regime=regime,
            accumulation_score=round(float(normalized[0]), 4),
            expansion_score=round(float(normalized[1]), 4),
            manipulation_score=round(float(normalized[2]), 4),
            distribution_score=round(float(normalized[3]), 4),
        )

    def _trend_continuation(self, closes: np.ndarray) -> float:
        if len(closes) < 6:
            return 0.0
        diffs = np.diff(closes[-6:])
        same_dir = max(np.sum(diffs > 0), np.sum(diffs < 0)) / max(len(diffs), 1)
        return float(max(0.0, min(1.0, same_dir)))

    def _higher_highs_weak_closes(self, highs: np.ndarray, closes: np.ndarray) -> bool:
        if len(highs) < 6:
            return False
        recent_highs = highs[-6:]
        close_strength = np.diff(closes[-6:])
        hh = np.sum(np.diff(recent_highs) > 0) >= 3
        weak = np.sum(close_strength <= 0) >= 3
        return bool(hh and weak)

    def _ime_cluster_signal(self, heatmap_zones) -> float:
        if not heatmap_zones:
            return 0.0
        count = float(len(heatmap_zones))
        return float(max(0.0, min(1.0, count / 4.0)))
