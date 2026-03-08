from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ..types import AsiaSession, NarrativePattern, NarrativeScore
from .narrative_patterns import EXPANSION_COMPATIBLE, PATTERN_DESCRIPTIONS, REVERSAL_COMPATIBLE
log = logging.getLogger("quantara.narrative")

@dataclass
class NarrativeContext:
    primary_pattern: NarrativePattern
    narrative_bias: str
    expansion_probability: float
    reversal_probability: float
    pattern_scores: list[NarrativeScore]
    description: str

class NarrativeEngine:
    def evaluate(self,asia,candles_m30,asia_high,asia_low,sweep_detected,sweep_side,vol_regime) -> NarrativeContext:
        hour=datetime.now(tz=timezone.utc).hour; scores=[]
        comp=asia.classification=="COMPRESSION"; exp=asia.classification=="EXPANSION"
        if comp: scores.append(NarrativeScore(NarrativePattern.ASIA_COMPRESSION,0.80,"Asia compressed"))
        if exp:  scores.append(NarrativeScore(NarrativePattern.ASIA_EXPANSION,0.60,"Asia expanded"))
        if 7<=hour<12 and sweep_detected:
            p=0.75 if comp else 0.55
            scores.append(NarrativeScore(NarrativePattern.LONDON_SWEEP,p,f"London swept Asia {sweep_side}"))
        if 7<=hour<13 and vol_regime=="EXPANSION" and not sweep_detected:
            scores.append(NarrativeScore(NarrativePattern.LONDON_EXPANSION,0.72 if comp else 0.50,"London expansion"))
        if 7<=hour<13 and vol_regime=="EXPANSION" and sweep_detected:
            scores.append(NarrativeScore(NarrativePattern.LONDON_TRAP,0.55,"Possible London trap"))
        if 12<=hour<17 and candles_m30:
            rev=self._ny_rev(candles_m30,asia_high,asia_low)
            scores.append(NarrativeScore(NarrativePattern.NY_REVERSAL if rev>0.4 else NarrativePattern.NY_CONTINUATION,rev if rev>0.4 else 1-rev,"NY session"))
        if not scores: scores.append(NarrativeScore(NarrativePattern.UNKNOWN,0.3,""))
        scores.sort(key=lambda s:s.probability,reverse=True)
        primary=scores[0].pattern
        ep=max((s.probability for s in scores if s.pattern in EXPANSION_COMPATIBLE),default=0.0)
        rp=max((s.probability for s in scores if s.pattern in REVERSAL_COMPATIBLE),default=0.0)
        if primary==NarrativePattern.LONDON_SWEEP:     bias="SHORT" if sweep_side=="sell" else "LONG"
        elif primary==NarrativePattern.LONDON_EXPANSION: bias="LONG" if asia.direction=="BULLISH" else "SHORT"
        elif primary==NarrativePattern.NY_REVERSAL:    bias="SHORT" if asia.direction=="BULLISH" else "LONG"
        else: bias="NEUTRAL"
        log.info("narrative primary=%s bias=%s",primary.value,bias)
        return NarrativeContext(primary,bias,round(ep,2),round(rp,2),scores,PATTERN_DESCRIPTIONS.get(primary,""))
    def _ny_rev(self,c,ah,al):
        if len(c)<10: return 0.3
        lr=max(x.high for x in c[-8:])-min(x.low for x in c[-8:])
        ar=ah-al if ah>al else 1.0
        r=lr/ar
        return 0.70 if r>2.5 else (0.55 if r>1.8 else 0.30)
