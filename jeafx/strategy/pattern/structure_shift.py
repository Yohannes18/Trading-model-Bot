from __future__ import annotations
import logging
from dataclasses import dataclass
log = logging.getLogger("jeafx.structure")

@dataclass
class StructureResult:
    bos_detected:bool; mss_detected:bool; direction:str; key_level:float; score:float

class StructureShift:
    def detect(self, candles) -> StructureResult:
        null=StructureResult(False,False,"NONE",0.0,0.0)
        if len(candles)<40: return null
        highs=[c.high for c in candles]; lows=[c.low for c in candles]; last=candles[-1]
        sh_r=max(highs[-20:]); sl_r=min(lows[-20:])
        sh_p=max(highs[-40:-20]); sl_p=min(lows[-40:-20])
        up=sh_r>sh_p and sl_r>sl_p; dn=sh_r<sh_p and sl_r<sl_p
        if up and last.close>sh_r:   return StructureResult(True,False,"BUY",round(sh_r,2),0.7)
        if dn and last.close<sl_r:   return StructureResult(True,False,"SELL",round(sl_r,2),0.7)
        if up and last.close<sl_p:   return StructureResult(False,True,"SELL",round(sl_p,2),0.9)
        if dn and last.close>sh_p:   return StructureResult(False,True,"BUY",round(sh_p,2),0.9)
        return null
