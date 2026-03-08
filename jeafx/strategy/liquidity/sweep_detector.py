from __future__ import annotations
import logging
from dataclasses import dataclass
from ..types import LiquidityLevel
log = logging.getLogger("jeafx.sweep")

@dataclass
class SweepEvent:
    detected: bool; swept_level: float; side: str; trap: bool; candle_index: int

class SweepDetector:
    def detect(self, candles, buy_side, sell_side, lookback=10) -> SweepEvent:
        if len(candles)<lookback: return SweepEvent(False,0.0,"",False,-1)
        recent=candles[-lookback:]
        for lv in buy_side:
            for i,c in enumerate(recent):
                if c.low<lv.price and c.close>lv.price:
                    return SweepEvent(True,lv.price,"sell",self._trap(recent,i,"buy"),i)
        for lv in sell_side:
            for i,c in enumerate(recent):
                if c.high>lv.price and c.close<lv.price:
                    return SweepEvent(True,lv.price,"buy",self._trap(recent,i,"sell"),i)
        return SweepEvent(False,0.0,"",False,-1)
    def _trap(self,candles,idx,side):
        if idx>=len(candles)-1: return False
        n=candles[idx+1]; rng=n.high-n.low
        if side=="sell": return n.close>n.open and (n.close-n.open)>rng*0.5
        return n.close<n.open and (n.open-n.close)>rng*0.5
