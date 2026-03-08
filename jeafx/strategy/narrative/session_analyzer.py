from __future__ import annotations
import logging
from datetime import datetime, timezone
from ..types import AsiaSession
log = logging.getLogger("jeafx.session_analyzer")
GOLD_PIP=0.1

class SessionAnalyzer:
    COMP_MULT=0.5; EXP_MULT=1.5
    def analyze_asia(self, candles_h1) -> AsiaSession:
        now=datetime.now(tz=timezone.utc)
        asia=[c for c in candles_h1 if 0<=c.time.hour<7 and c.time.date()==now.date()]
        if not asia: asia=candles_h1[-7:] if len(candles_h1)>=7 else candles_h1
        if not asia: return AsiaSession()
        ah=max(c.high for c in asia); al=min(c.low for c in asia)
        rp=round((ah-al)/GOLD_PIP,1)
        atr=sum(c.high-c.low for c in candles_h1[-20:])/max(len(candles_h1[-20:]),1)
        rng=ah-al
        if atr>0:
            if rng<atr*self.COMP_MULT:   cls="COMPRESSION"
            elif rng>atr*self.EXP_MULT:  cls="EXPANSION"
            else:                         cls="NORMAL"
        else: cls="NORMAL"
        mid=(ah+al)/2; lc=asia[-1].close
        direction="BULLISH" if lc>mid else ("BEARISH" if lc<mid else "NEUTRAL")
        log.info("asia high=%.2f low=%.2f range=%.0f pips class=%s",ah,al,rp,cls)
        return AsiaSession(round(ah,2),round(al,2),rp,cls,direction)
