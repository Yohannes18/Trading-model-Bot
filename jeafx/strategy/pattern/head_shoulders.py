from __future__ import annotations
import logging
from dataclasses import dataclass
log = logging.getLogger("jeafx.hs")

@dataclass
class HSResult:
    detected:bool; pattern_type:str; direction:str; neckline:float; confidence:float; description:str

class HeadShoulders:
    TOL=0.4
    def detect(self, candles) -> HSResult:
        null=HSResult(False,"","NONE",0.0,0.0,"")
        if len(candles)<30: return null
        hs=self._hs(candles,self._swing_highs(candles))
        ih=self._ihs(candles,self._swing_lows(candles))
        if hs.confidence>=ih.confidence and hs.detected: return hs
        return ih if ih.detected else null
    def _swing_highs(self,c):
        return [i for i in range(2,len(c)-2) if c[i].high>c[i-1].high and c[i].high>c[i-2].high and c[i].high>c[i+1].high and c[i].high>c[i+2].high]
    def _swing_lows(self,c):
        return [i for i in range(2,len(c)-2) if c[i].low<c[i-1].low and c[i].low<c[i-2].low and c[i].low<c[i+1].low and c[i].low<c[i+2].low]
    def _hs(self,c,idx):
        null=HSResult(False,"","NONE",0.0,0.0,"")
        if len(idx)<3: return null
        l,h,r=idx[-3],idx[-2],idx[-1]
        lh,hh,rh=c[l].high,c[h].high,c[r].high
        if not(hh>lh and hh>rh): return null
        diff=abs(lh-rh)/hh
        if diff>self.TOL: return null
        nl=round((min(c.low for c in c[l:h]+[c[l]])+(min(c.low for c in c[h:r]+[c[r]])))/2,2)
        broken=c[-1].close<nl
        conf=0.85 if broken else 0.60
        if diff<0.1: conf=min(conf+0.1,1.0)
        return HSResult(True,"HEAD_AND_SHOULDERS","SELL",nl,conf,f"H&S neckline={nl:.2f} broken={broken}")
    def _ihs(self,c,idx):
        null=HSResult(False,"","NONE",0.0,0.0,"")
        if len(idx)<3: return null
        l,h,r=idx[-3],idx[-2],idx[-1]
        ll,hl,rl=c[l].low,c[h].low,c[r].low
        if not(hl<ll and hl<rl): return null
        diff=abs(ll-rl)/abs(hl) if hl!=0 else 1.0
        if diff>self.TOL: return null
        nl=round((max(c.high for c in c[l:h]+[c[l]])+(max(c.high for c in c[h:r]+[c[r]])))/2,2)
        broken=c[-1].close>nl
        conf=0.85 if broken else 0.60
        if diff<0.1: conf=min(conf+0.1,1.0)
        return HSResult(True,"INVERSE_HEAD_AND_SHOULDERS","BUY",nl,conf,f"IH&S neckline={nl:.2f} broken={broken}")
