from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
log = logging.getLogger("quantara.fib")
FIB_LEVELS=[0.236,0.382,0.5,0.618,0.705,0.786,0.886]
PRECISION=[0.618,0.786]
ZONE_TOL=0.5

@dataclass
class FibZone:
    level_pct:float; price:float; in_zone:bool; description:str

@dataclass
class FibResult:
    impulse_high:float; impulse_low:float; direction:str
    zones:list[FibZone]; entry_zone:Optional[FibZone]; in_retracement:bool

class FibonacciEngine:
    def analyze(self, candles, direction) -> FibResult:
        if len(candles)<20: return FibResult(0,0,direction,[],None,False)
        hi,lo=self._impulse(candles,direction)
        if not hi or not lo: return FibResult(0,0,direction,[],None,False)
        imp=hi-lo; cur=candles[-1].close; zones=[]; entry=None
        for lvl in FIB_LEVELS:
            price=round((hi-imp*lvl if direction=="BUY" else lo+imp*lvl),2)
            in_z=abs(cur-price)<=ZONE_TOL
            z=FibZone(lvl,price,in_z,f"Fib {lvl:.3f} @ {price:.2f}")
            zones.append(z)
            if lvl in PRECISION and in_z: entry=z
        log.info("fib dir=%s hi=%.2f lo=%.2f entry=%s",direction,hi,lo,entry.price if entry else None)
        return FibResult(hi,lo,direction,zones,entry,any(z.in_zone for z in zones))
    def _impulse(self,c,direction):
        r=c[-30:]
        if direction=="BUY":
            li=min(range(len(r)),key=lambda i:r[i].low)
            return round(max(x.high for x in r[li:]),2), round(r[li].low,2)
        hi=max(range(len(r)),key=lambda i:r[i].high)
        return round(r[hi].high,2), round(min(x.low for x in r[hi:]),2)
