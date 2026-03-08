from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from engine.liquidity_regime_engine import LiquidityRegime, LiquidityRegimeEngine
from jeafx.strategy.smc_engine import Candle


def _base_candles(n: int, start: float = 2300.0, step: float = 0.25, wick: float = 0.2) -> list[Candle]:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out: list[Candle] = []
    p = start
    for i in range(n):
        o = p
        c = p + step
        h = max(o, c) + wick
        l = min(o, c) - wick
        out.append(Candle(time=ts + timedelta(minutes=30 * i), open=o, high=h, low=l, close=c, volume=1000 + i * 8))
        p = c
    return out


def test_liquidity_regime_accumulation_on_compression() -> None:
    candles = _base_candles(60, step=0.03, wick=0.03)
    vol = SimpleNamespace(regime=SimpleNamespace(value="COMPRESSION"), expansion_probability=0.15)
    amd = SimpleNamespace(phase=SimpleNamespace(value="ACCUMULATION"))

    res = LiquidityRegimeEngine().analyze(candles, "ASIA", vol, amd, [], None)
    assert res.regime == LiquidityRegime.ACCUMULATION


def test_liquidity_regime_expansion_on_displacement() -> None:
    candles = _base_candles(60, step=0.35, wick=0.15)
    candles[-1] = Candle(candles[-1].time, candles[-2].close, candles[-2].close + 4.0, candles[-2].close - 0.2, candles[-2].close + 3.2, 2500)
    vol = SimpleNamespace(regime=SimpleNamespace(value="EXPANSION"), expansion_probability=0.9)
    amd = SimpleNamespace(phase=SimpleNamespace(value="DISTRIBUTION"))

    res = LiquidityRegimeEngine().analyze(candles, "LONDON", vol, amd, [1, 2, 3], None)
    assert res.regime == LiquidityRegime.EXPANSION


def test_liquidity_regime_manipulation_on_sweep_no_follow() -> None:
    candles = _base_candles(60, step=0.18, wick=0.25)
    candles[-2] = Candle(candles[-2].time, 2310.0, 2311.4, 2309.8, 2310.9, 2200)
    candles[-1] = Candle(candles[-1].time, 2310.9, 2311.0, 2310.4, 2310.92, 2100)
    vol = SimpleNamespace(regime=SimpleNamespace(value="NORMAL"), expansion_probability=0.45)
    amd = SimpleNamespace(phase=SimpleNamespace(value="MANIPULATION"))
    raid = SimpleNamespace(probability=0.85, raid_direction="UP")

    res = LiquidityRegimeEngine().analyze(candles, "LONDON", vol, amd, [], raid)
    assert res.regime == LiquidityRegime.MANIPULATION


def test_liquidity_regime_distribution_on_exhaustion() -> None:
    candles = _base_candles(60, step=0.22, wick=0.15)
    last = candles[-8:]
    highs = [2320.0, 2320.6, 2321.2, 2321.8, 2322.3, 2322.8, 2323.1, 2323.3]
    closes = [2319.6, 2320.1, 2320.5, 2320.8, 2321.0, 2321.05, 2321.07, 2321.08]
    for i, c in enumerate(last):
        candles[-8 + i] = Candle(c.time, closes[i] - 0.25, highs[i], closes[i] - 0.55, closes[i], 1400)

    vol = SimpleNamespace(regime=SimpleNamespace(value="NORMAL"), expansion_probability=0.35)
    amd = SimpleNamespace(phase=SimpleNamespace(value="DISTRIBUTION"))

    res = LiquidityRegimeEngine().analyze(candles, "NEW_YORK", vol, amd, [], None)
    assert res.regime == LiquidityRegime.DISTRIBUTION
