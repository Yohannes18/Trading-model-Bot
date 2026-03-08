from __future__ import annotations
import logging
from ..types import LiquidityBias, LiquidityLevel
log = logging.getLogger("jeafx.liquidity")

_SCORES: dict[str, int] = {
    "WeeklyHigh":5,"WeeklyLow":5,"DailyHigh":4,"DailyLow":4,
    "EqualHighs":3,"EqualLows":3,"AsiaHigh":2,"AsiaLow":2,
    "LondonHigh":2,"LondonLow":2,"SwingHigh":2,"SwingLow":2,
    "RangeHigh":1,"RangeLow":1,
}
EQUAL_TOL = 1.0  # $1 tolerance for gold

class LiquidityMap:
    def build(self, candles_m30, candles_h4, candles_d1,
              asia_high=0.0, asia_low=0.0, london_high=0.0, london_low=0.0):
        buy_side: list[LiquidityLevel] = []
        sell_side: list[LiquidityLevel] = []
        def add(side, price, ltype, tf):
            if price > 0:
                side.append(LiquidityLevel(round(price,2), ltype, tf, _SCORES.get(ltype,1), "buy" if side is buy_side else "sell"))
        if len(candles_d1) >= 5:
            week = candles_d1[-5:]
            add(sell_side, max(c.high for c in week), "WeeklyHigh", "1W")
            add(buy_side,  min(c.low  for c in week), "WeeklyLow",  "1W")
        if len(candles_d1) >= 2:
            pd = candles_d1[-2]
            add(sell_side, pd.high, "DailyHigh", "1D")
            add(buy_side,  pd.low,  "DailyLow",  "1D")
        if asia_high:   add(sell_side, asia_high,   "AsiaHigh",   "SESS")
        if asia_low:    add(buy_side,  asia_low,    "AsiaLow",    "SESS")
        if london_high: add(sell_side, london_high, "LondonHigh", "SESS")
        if london_low:  add(buy_side,  london_low,  "LondonLow",  "SESS")
        cs = candles_h4 or candles_m30
        eq_h, eq_l = self._equal_levels(cs)
        for p in eq_h: add(sell_side, p, "EqualHighs", "4H")
        for p in eq_l: add(buy_side,  p, "EqualLows",  "4H")
        sh, sl = self._swing_levels(candles_m30)
        for p in sh[:3]: add(sell_side, p, "SwingHigh", "M30")
        for p in sl[:3]: add(buy_side,  p, "SwingLow",  "M30")
        rh, rl = self._range_levels(candles_m30)
        if rh: add(sell_side, rh, "RangeHigh", "M30")
        if rl: add(buy_side,  rl, "RangeLow",  "M30")
        buy_side.sort(key=lambda x: x.score, reverse=True)
        sell_side.sort(key=lambda x: x.score, reverse=True)
        log.info("liquidity_map buy=%s sell=%s", len(buy_side), len(sell_side))
        return buy_side, sell_side
    def gravity_bias(self, buy, sell) -> LiquidityBias:
        bs = sum(l.score for l in buy); ss = sum(l.score for l in sell)
        if bs > ss*1.3: return LiquidityBias.BUY_SIDE
        if ss > bs*1.3: return LiquidityBias.SELL_SIDE
        return LiquidityBias.NEUTRAL
    def _equal_levels(self, candles):
        if len(candles) < 10: return [], []
        highs = [c.high for c in candles[-40:]]; lows = [c.low for c in candles[-40:]]
        eq_h = list({round(h,2) for h in highs if sum(1 for h2 in highs if abs(h-h2)<EQUAL_TOL)>=2})
        eq_l = list({round(l,2) for l in lows  if sum(1 for l2 in lows  if abs(l-l2)<EQUAL_TOL)>=2})
        return eq_h[:5], eq_l[:5]
    def _swing_levels(self, candles):
        if len(candles)<5: return [],[]
        cs = candles[-60:] if len(candles)>=60 else candles
        h=[]; l=[]
        for i in range(2,len(cs)-2):
            if cs[i].high>cs[i-1].high and cs[i].high>cs[i+1].high: h.append(round(cs[i].high,2))
            if cs[i].low<cs[i-1].low   and cs[i].low<cs[i+1].low:   l.append(round(cs[i].low,2))
        return h[-5:], l[-5:]
    def _range_levels(self, candles):
        if len(candles)<20: return 0.0,0.0
        last=candles[-20:]; rh=max(c.high for c in last); rl=min(c.low for c in last)
        atr=sum(c.high-c.low for c in last)/20
        return (round(rh,2),round(rl,2)) if (rh-rl)<atr*2.5 else (0.0,0.0)
