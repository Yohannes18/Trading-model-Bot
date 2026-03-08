from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.liquidity_map_engine import LiquidityMapEngine
from jeafx.strategy.smc_engine import Candle


def _candles(n: int, base: float = 2300.0) -> list[Candle]:
    out: list[Candle] = []
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p = base
    for i in range(n):
        o = p
        c = p + (0.3 if i % 2 == 0 else -0.2)
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        out.append(Candle(time=t0 + timedelta(minutes=30 * i), open=o, high=h, low=l, close=c, volume=900 + i * 6))
        p = c
    return out


def test_equal_highs_detection() -> None:
    candles = _candles(70)
    candles[-8] = Candle(candles[-8].time, 2301.0, 2310.0, 2300.2, 2308.0, 1300)
    candles[-5] = Candle(candles[-5].time, 2302.0, 2310.03, 2301.4, 2307.5, 1250)

    res = LiquidityMapEngine().analyze(candles, current_price=2305.0, atr=2.0, session="LONDON")
    assert any(p.type == "equal_highs" for p in res.pools)


def test_equal_lows_detection() -> None:
    candles = _candles(70)
    candles[-9] = Candle(candles[-9].time, 2305.0, 2306.0, 2298.0, 2299.2, 1200)
    candles[-6] = Candle(candles[-6].time, 2304.0, 2305.0, 2298.03, 2299.1, 1180)

    res = LiquidityMapEngine().analyze(candles, current_price=2302.0, atr=2.0, session="LONDON")
    assert any(p.type == "equal_lows" for p in res.pools)


def test_swing_liquidity_detection() -> None:
    candles = _candles(60)
    candles[-4] = Candle(candles[-4].time, 2302.0, 2312.0, 2301.7, 2304.0, 1400)
    candles[-3] = Candle(candles[-3].time, 2304.0, 2307.0, 2300.4, 2301.2, 1300)
    candles[-2] = Candle(candles[-2].time, 2301.2, 2306.8, 2297.8, 2299.1, 1350)

    res = LiquidityMapEngine().analyze(candles, current_price=2303.0, atr=2.5, session="NEW_YORK")
    assert any(p.type == "swing_high" for p in res.pools)
    assert any(p.type == "swing_low" for p in res.pools)


def test_session_liquidity_detection() -> None:
    candles = _candles(50)
    res = LiquidityMapEngine().analyze(candles, current_price=2301.0, atr=1.8, session="ASIA", session_high=2310.0, session_low=2290.0)
    assert any(p.type == "session_high" and p.price == 2310.0 for p in res.pools)
    assert any(p.type == "session_low" and p.price == 2290.0 for p in res.pools)


def test_nearest_target_logic() -> None:
    candles = _candles(80)
    candles[-5] = Candle(candles[-5].time, 2300.0, 2308.0, 2298.0, 2302.0, 1200)
    candles[-4] = Candle(candles[-4].time, 2302.0, 2310.0, 2300.0, 2308.0, 1500)
    candles[-3] = Candle(candles[-3].time, 2308.0, 2309.0, 2299.0, 2300.0, 1500)

    price = 2304.5
    res = LiquidityMapEngine().analyze(candles, current_price=price, atr=2.0, session="LONDON")
    assert res.nearest_above is None or res.nearest_above.price > price
    assert res.nearest_below is None or res.nearest_below.price < price
