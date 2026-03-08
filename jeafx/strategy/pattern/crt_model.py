from __future__ import annotations
import logging
from dataclasses import dataclass
log = logging.getLogger("jeafx.crt")

@dataclass
class CRTResult:
    signal:bool; direction:str; exhaustion:bool; key_candle_idx:int; description:str

class CRTModel:
    RATIO=2.0
    def detect(self, candles) -> CRTResult:
        null=CRTResult(False,"NONE",False,-1,"")
        if len(candles)<5: return null
        c=candles[-1]; body=abs(c.close-c.open)
        uw=c.high-max(c.open,c.close); dw=min(c.open,c.close)-c.low; tr=c.high-c.low
        if tr==0: return null
        if uw>body*self.RATIO and uw>tr*0.4:
            return CRTResult(True,"SELL",True,len(candles)-1,f"Bearish exhaustion wick={uw:.2f}")
        if dw>body*self.RATIO and dw>tr*0.4:
            return CRTResult(True,"BUY",True,len(candles)-1,f"Bullish exhaustion wick={dw:.2f}")
        if c.high<candles[-2].high and c.low>candles[-2].low:
            return CRTResult(True,"NONE",False,len(candles)-1,"Inside bar compression")
        return null
