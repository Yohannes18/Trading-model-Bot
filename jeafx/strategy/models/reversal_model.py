from __future__ import annotations
import logging
from ..types import Direction,LiquidityLevel,ModelResult,ModelType,NarrativePattern,SessionType,TradeSetupProposal
log=logging.getLogger("jeafx.reversal_model")
MAX_SL=150.0; PIP=0.1; MIN_RR=3.0; PREF_RR=4.0

class ReversalModel:
    def evaluate(self,session,sweep_detected,sweep_side,liquidity_trap,crt_direction,
                 hs_direction,hs_confidence,mss_direction,fib_entry_price,ob_high,ob_low,
                 htf_bias,
                 current_price,atr,sell_side_levels,buy_side_levels,narrative_pattern,macro_bias) -> ModelResult:
        signals=[]; score=0.0
        if session==SessionType.ASIA:
            return ModelResult(ModelType.REVERSAL,0.0,Direction.NONE,None,[],"No reversals in Asia")
        if htf_bias not in ("BUY","SELL"):
            return ModelResult(ModelType.REVERSAL,0.0,Direction.NONE,None,[],"Missing HTF bias")
        if not sweep_detected:
            return ModelResult(ModelType.REVERSAL,0.0,Direction.NONE,None,[],"No liquidity sweep")
        score+=0.20; signals.append(f"Liquidity sweep ({sweep_side}) ✓")
        if liquidity_trap: score+=0.10; signals.append("Trap confirmed ✓")
        direction=Direction.SELL if sweep_side=="sell" else Direction.BUY
        if htf_bias!=direction.value:
            return ModelResult(ModelType.REVERSAL,score,direction,None,signals,f"HTF bias {htf_bias} misaligned")
        score+=0.20; signals.append(f"HTF {htf_bias} ✓")
        if crt_direction!=direction.value:
            return ModelResult(ModelType.REVERSAL,score,direction,None,signals,"CRT exhaustion missing")
        score+=0.15; signals.append("CRT exhaustion ✓")
        if not (hs_direction==direction.value and hs_confidence>0.6):
            return ModelResult(ModelType.REVERSAL,score,direction,None,signals,"H&S confirmation missing")
        score+=hs_confidence*0.20; signals.append(f"H&S {hs_confidence:.0%} ✓")
        if ob_high<=0 or ob_low<=0:
            return ModelResult(ModelType.REVERSAL,score,direction,None,signals,"Order block retest missing")
        signals.append(f"OB {ob_low:.2f}-{ob_high:.2f} ✓")
        if fib_entry_price<=0:
            return ModelResult(ModelType.REVERSAL,score,direction,None,signals,"Fib 0.618-0.79 entry missing")
        signals.append(f"Fib entry {fib_entry_price:.2f} ✓")
        if mss_direction==direction.value: score+=0.15; signals.append("MSS ✓")
        if narrative_pattern in (NarrativePattern.LONDON_SWEEP,NarrativePattern.LONDON_TRAP,NarrativePattern.NY_REVERSAL):
            score+=0.10; signals.append(f"Narrative {narrative_pattern.value} ✓")
        if macro_bias=="BULLISH_GOLD" and direction==Direction.BUY:    score+=0.05; signals.append("Macro ✓")
        elif macro_bias=="BEARISH_GOLD" and direction==Direction.SELL: score+=0.05; signals.append("Macro ✓")
        entry=fib_entry_price if fib_entry_price>0 else current_price
        sl_pips=min(max(atr*1.8/PIP,25.0),MAX_SL)
        if direction==Direction.BUY:
            sl=round(entry-sl_pips*PIP,2)
            tl=[l for l in sell_side_levels if l.price>entry+sl_pips*PIP*MIN_RR]
            tp=round(tl[0].price-3.0,2) if tl else round(entry+sl_pips*PIP*PREF_RR,2)
        else:
            sl=round(entry+sl_pips*PIP,2)
            tl=[l for l in buy_side_levels if l.price<entry-sl_pips*PIP*MIN_RR]
            tp=round(tl[0].price+3.0,2) if tl else round(entry-sl_pips*PIP*PREF_RR,2)
        rr=round(abs(tp-entry)/abs(sl-entry),2) if abs(sl-entry)>0 else 0.0
        if rr<MIN_RR: return ModelResult(ModelType.REVERSAL,score,direction,None,signals,f"RR {rr}<{MIN_RR}")
        if rr>=PREF_RR: score+=0.10
        score=min(round(score,3),1.0)
        setup=TradeSetupProposal(direction,round(entry,2),sl,tp,rr,1.0,0.01,
                                  f"Reversal: {', '.join(signals[:4])}",f"SL {sl_pips:.0f}pips","TP at liquidity")
        log.info("reversal conf=%.2f dir=%s rr=%.1f",score,direction.value,rr)
        return ModelResult(ModelType.REVERSAL,score,direction,setup,signals)
