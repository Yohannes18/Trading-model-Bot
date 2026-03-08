from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from ..config import Direction


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open


@dataclass
class SMCAnalysis:
    pair: str
    timeframe: str
    signal_direction: Direction = Direction.NONE
    score: int = 0
    confluences: list[str] = field(default_factory=list)
    narrative: str = ""
    swing_high: float = 0
    swing_low: float = 0
    ob_high: float = 0
    ob_low: float = 0
    fvg_high: float = 0
    fvg_low: float = 0
    equal_highs: int = 0
    equal_lows: int = 0
    equal_level_tolerance: float = 0


class SMCEngine:
    def analyze(self, candles: list[Candle], pair: str, tf: str) -> SMCAnalysis:
        analysis = SMCAnalysis(pair=pair, timeframe=tf)
        if len(candles) < 50:
            return analysis
        self._structure(candles, analysis)
        self._liquidity(candles, analysis)
        self._ob(candles, analysis)
        self._fvg(candles, analysis)
        self._equal_levels(candles, analysis)
        self._narrative(analysis)
        return analysis

    def _structure(self, cs: list[Candle], a: SMCAnalysis) -> None:
        highs = [c.high for c in cs]
        lows = [c.low for c in cs]
        sw_h = max(highs[-20:])
        sw_l = min(lows[-20:])
        a.swing_high = sw_h
        a.swing_low = sw_l
        prev_sw_h = max(highs[-40:-20])
        prev_sw_l = min(lows[-40:-20])
        last = cs[-1]

        bias: Direction | None = None
        if sw_h > prev_sw_h and sw_l > prev_sw_l:
            bias = Direction.BUY
            a.score += 5
        elif sw_h < prev_sw_h and sw_l < prev_sw_l:
            bias = Direction.SELL
            a.score += 5

        if bias == Direction.BUY and last.close > sw_h:
            a.score += 15
            a.confluences.append("BOS Bullish ✓")
            a.signal_direction = Direction.BUY
        elif bias == Direction.SELL and last.close < sw_l:
            a.score += 15
            a.confluences.append("BOS Bearish ✓")
            a.signal_direction = Direction.SELL

        if bias == Direction.BUY and last.close < prev_sw_l:
            a.score += 20
            a.confluences.append("CHoCH Bearish ✓")
            a.signal_direction = Direction.SELL
        elif bias == Direction.SELL and last.close > prev_sw_h:
            a.score += 20
            a.confluences.append("CHoCH Bullish ✓")
            a.signal_direction = Direction.BUY

    def _liquidity(self, cs: list[Candle], a: SMCAnalysis) -> None:
        highs = [c.high for c in cs[-30:]]
        lows = [c.low for c in cs[-30:]]
        sw_h = max(highs[:-5])
        sw_l = min(lows[:-5])
        last5_h = max(c.high for c in cs[-5:])
        last5_l = min(c.low for c in cs[-5:])
        if last5_h > sw_h and cs[-1].close < sw_h:
            a.score += 25
            a.confluences.append("BSL Swept ✓")
            if a.signal_direction == Direction.NONE:
                a.signal_direction = Direction.SELL
        if last5_l < sw_l and cs[-1].close > sw_l:
            a.score += 25
            a.confluences.append("SSL Swept ✓")
            if a.signal_direction == Direction.NONE:
                a.signal_direction = Direction.BUY

    def _ob(self, cs: list[Candle], a: SMCAnalysis) -> None:
        for i in range(len(cs) - 10, len(cs) - 1):
            c = cs[i]
            nxt = cs[i + 1]
            if not c.bullish and nxt.close > c.high and a.signal_direction == Direction.BUY:
                if cs[-1].low <= c.high and cs[-1].low >= c.low:
                    a.score += 20
                    a.ob_high = c.high
                    a.ob_low = c.low
                    a.confluences.append("Demand OB ✓")
                    break
            if c.bullish and nxt.close < c.low and a.signal_direction == Direction.SELL:
                if cs[-1].high >= c.low and cs[-1].high <= c.high:
                    a.score += 20
                    a.ob_high = c.high
                    a.ob_low = c.low
                    a.confluences.append("Supply OB ✓")
                    break

    def _fvg(self, cs: list[Candle], a: SMCAnalysis) -> None:
        for i in range(len(cs) - 3, len(cs) - 1):
            c1 = cs[i - 1]
            c3 = cs[i + 1] if i + 1 < len(cs) else cs[i]
            if c3.low > c1.high:
                a.fvg_low = c1.high
                a.fvg_high = c3.low
                if a.signal_direction == Direction.BUY:
                    a.score += 15
                    a.confluences.append("Bullish FVG ✓")
            if c3.high < c1.low:
                a.fvg_high = c1.low
                a.fvg_low = c3.high
                if a.signal_direction == Direction.SELL:
                    a.score += 15
                    a.confluences.append("Bearish FVG ✓")

    def _equal_levels(self, cs: list[Candle], a: SMCAnalysis) -> None:
        highs = [c.high for c in cs[-20:]]
        lows = [c.low for c in cs[-20:]]
        tol = float(np.mean([c.high - c.low for c in cs[-20:]]) * 0.15)
        eq_h = sum(1 for h in highs if abs(h - highs[-1]) < tol)
        eq_l = sum(1 for l in lows if abs(l - lows[-1]) < tol)
        a.equal_highs = eq_h
        a.equal_lows = eq_l
        a.equal_level_tolerance = tol
        if eq_h >= 2:
            a.score += 10
            a.confluences.append("Equal Highs ✓")
        if eq_l >= 2:
            a.score += 10
            a.confluences.append("Equal Lows ✓")

    def _narrative(self, a: SMCAnalysis) -> None:
        if a.signal_direction == Direction.NONE or not a.confluences:
            a.narrative = "No clear SMC setup on this timeframe."
            return
        side = "bullish" if a.signal_direction == Direction.BUY else "bearish"
        parts: list[str] = []
        if any("Swept" in c for c in a.confluences):
            liq = "BSL" if a.signal_direction == Direction.SELL else "SSL"
            parts.append(f"Liquidity sweep of {liq} confirmed")
        if any("CHoCH" in c for c in a.confluences):
            parts.append(f"CHoCH confirms {side} bias shift")
        elif any("BOS" in c for c in a.confluences):
            parts.append(f"BOS confirms {side} structure")
        if a.ob_high:
            zone = "supply" if a.signal_direction == Direction.SELL else "demand"
            parts.append(f"Price at {zone} OB ({a.ob_low:.2f}–{a.ob_high:.2f})")
        if a.fvg_high:
            label = "Bearish" if a.signal_direction == Direction.SELL else "Bullish"
            parts.append(f"{label} FVG present ({a.fvg_low:.2f}–{a.fvg_high:.2f})")
        a.narrative = ". ".join(parts) + "."
