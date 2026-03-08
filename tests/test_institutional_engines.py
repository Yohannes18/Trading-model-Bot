from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.displacement_engine import DisplacementEngine
from engine.liquidity_magnet_engine import LiquidityMagnetEngine
from engine.macro_narrative_engine import MacroNarrativeEngine
from jeafx.strategy.smc_engine import Candle


class _Pool:
    def __init__(self, price: float, strength: float, pool_type: str) -> None:
        self.price = price
        self.strength = strength
        self.type = pool_type


class _Map:
    def __init__(self, pools) -> None:
        self.pools = pools


def _candles(n: int, base: float = 2300.0, step: float = 0.2, vol: float = 1000.0) -> list[Candle]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out: list[Candle] = []
    p = base
    for i in range(n):
        o = p
        c = p + step
        h = max(o, c) + 0.4
        l = min(o, c) - 0.4
        out.append(Candle(time=t0 + timedelta(minutes=30 * i), open=o, high=h, low=l, close=c, volume=vol + i * 5))
        p = c
    return out


def test_displacement_engine_detects_impulse() -> None:
    candles = _candles(40, step=0.1, vol=1000)
    candles[-1] = Candle(candles[-1].time, 2305.0, 2312.0, 2304.8, 2311.2, 4200)
    result = DisplacementEngine().analyze(candles, atr=1.8, break_of_structure=True)
    assert result.displacement_detected is True
    assert result.direction in ("UP", "DOWN")
    assert result.strength > 0


def test_liquidity_magnet_prefers_aligned_pool() -> None:
    liquidity_map = _Map([
        _Pool(2312.0, 0.8, "equal_highs"),
        _Pool(2298.0, 0.9, "equal_lows"),
    ])
    displacement = type("D", (), {"direction": "UP", "strength": 0.8})()
    result = LiquidityMagnetEngine().analyze(liquidity_map, "EXPANSION", displacement, current_price=2304.0)
    assert result.primary_magnet is not None
    assert result.primary_magnet.target_price >= 2304.0


def test_macro_narrative_blocks_news_risk() -> None:
    candles = _candles(30)
    result = MacroNarrativeEngine().analyze(candles, macro_bias="BULLISH_GOLD", event_minutes_to_high_impact=10)
    assert result.trade_blocked is True
    assert result.bias == "bullish_gold"
