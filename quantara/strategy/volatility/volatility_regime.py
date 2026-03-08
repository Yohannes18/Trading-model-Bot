from __future__ import annotations
import logging
from ..types import VolatilityRegime
log = logging.getLogger("quantara.volatility")

class VolatilityEngine:
    ATR_PERIOD=14; EXPAND_MULT=1.4; COMP_MULT=0.7
    def classify(self, candles) -> tuple[VolatilityRegime, float]:
        if len(candles)<self.ATR_PERIOD+5: return VolatilityRegime.NORMAL,0.0
        ranges=[c.high-c.low for c in candles]
        cur=sum(ranges[-self.ATR_PERIOD:])/self.ATR_PERIOD
        base=(sum(ranges[-self.ATR_PERIOD*2:-self.ATR_PERIOD])/self.ATR_PERIOD
              if len(ranges)>=self.ATR_PERIOD*2 else cur)
        ratio=cur/base if base>0 else 1.0
        if ratio>self.EXPAND_MULT:   regime=VolatilityRegime.EXPANSION
        elif ratio<self.COMP_MULT:   regime=VolatilityRegime.COMPRESSION
        else: regime=VolatilityRegime.NORMAL
        log.info("volatility regime=%s atr=%.2f ratio=%.2f",regime.value,cur,ratio)
        return regime, round(cur,4)
