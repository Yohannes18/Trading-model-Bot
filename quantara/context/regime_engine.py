from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RegimeContext:
    regime: str
    atr_ratio: float
    trend_strength: float


def _average_true_range(candles: list[Any], period: int) -> float:
    if len(candles) < 2:
        return 0.0
    start_index = max(1, len(candles) - period)
    true_ranges: list[float] = []
    for index in range(start_index, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        high = float(current.high)
        low = float(current.low)
        prev_close = float(previous.close)
        true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(max(0.0, true_range))
    if not true_ranges:
        return 0.0
    return sum(true_ranges) / len(true_ranges)


def _compute_trend_strength(candles: list[Any], lookback: int = 20) -> float:
    if len(candles) < lookback + 1:
        return 0.0
    window = candles[-(lookback + 1) :]
    closes = [float(c.close) for c in window]
    net_move = abs(closes[-1] - closes[0])
    path_move = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if path_move <= 1e-9:
        return 0.0
    return max(0.0, min(1.0, net_move / path_move))


def get_current_regime(candles: list[Any]) -> RegimeContext:
    if len(candles) < 50:
        return RegimeContext(regime="range", atr_ratio=1.0, trend_strength=0.0)

    short_atr = _average_true_range(candles, period=14)
    long_atr = _average_true_range(candles, period=50)
    atr_ratio = short_atr / max(long_atr, 1e-9)
    trend_strength = _compute_trend_strength(candles, lookback=20)

    if atr_ratio > 1.5:
        regime = "expansion"
    elif atr_ratio < 0.75:
        regime = "compression"
    elif trend_strength > 0.6:
        regime = "trend"
    else:
        regime = "range"

    return RegimeContext(regime=regime, atr_ratio=round(atr_ratio, 4), trend_strength=round(trend_strength, 4))



