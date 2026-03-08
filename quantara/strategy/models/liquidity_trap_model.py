from __future__ import annotations
import logging
from ..types import Direction,ModelResult,ModelType,NarrativePattern,SessionType,TradeSetupProposal

log=logging.getLogger("quantara.trap_model")
MAX_SL=150.0; PIP=0.1; MIN_RR=3.0; PREF_RR=4.0


class LiquidityTrapModel:
    def evaluate(self,session,narrative_pattern,sweep_detected,liquidity_trap,mss_direction,
                 london_breakout_direction,current_price,atr,sell_side_levels,buy_side_levels,macro_bias) -> ModelResult:
        signals=[]; score=0.0
        if session not in (SessionType.NEW_YORK,SessionType.LONDON_NY_OVERLAP):
            return ModelResult(ModelType.LIQUIDITY_TRAP,0.0,Direction.NONE,None,[],"Trap model active in NY/Overlap only")
        if london_breakout_direction not in ("BUY","SELL"):
            return ModelResult(ModelType.LIQUIDITY_TRAP,0.0,Direction.NONE,None,[],"No London breakout context")
        if not sweep_detected:
            return ModelResult(ModelType.LIQUIDITY_TRAP,0.0,Direction.NONE,None,[],"No liquidity sweep")
        score+=0.20; signals.append("Liquidity sweep ✓")
        if not liquidity_trap:
            return ModelResult(ModelType.LIQUIDITY_TRAP,score,Direction.NONE,None,signals,"No trap confirmation")
        score+=0.20; signals.append("Trap candle follow-through ✓")

        expected = "SELL" if london_breakout_direction=="BUY" else "BUY"
        if mss_direction!=expected:
            return ModelResult(ModelType.LIQUIDITY_TRAP,score,Direction.NONE,None,signals,"No NY structure shift vs London breakout")

        direction = Direction.BUY if expected=="BUY" else Direction.SELL
        score+=0.20; signals.append(f"NY MSS {expected} ✓")

        if narrative_pattern in (NarrativePattern.LONDON_TRAP,NarrativePattern.NY_REVERSAL,NarrativePattern.LONDON_SWEEP):
            score+=0.15; signals.append(f"Narrative {narrative_pattern.value} ✓")
        if macro_bias=="BULLISH_GOLD" and direction==Direction.BUY:
            score+=0.05; signals.append("Macro ✓")
        elif macro_bias=="BEARISH_GOLD" and direction==Direction.SELL:
            score+=0.05; signals.append("Macro ✓")

        sl_pips=min(max(atr*1.8/PIP,25.0),MAX_SL)
        entry=current_price
        if direction==Direction.BUY:
            sl=round(entry-sl_pips*PIP,2)
            tl=[l for l in sell_side_levels if l.price>entry+sl_pips*PIP*MIN_RR]
            tp=round(tl[0].price-3.0,2) if tl else round(entry+sl_pips*PIP*PREF_RR,2)
        else:
            sl=round(entry+sl_pips*PIP,2)
            tl=[l for l in buy_side_levels if l.price<entry-sl_pips*PIP*MIN_RR]
            tp=round(tl[0].price+3.0,2) if tl else round(entry-sl_pips*PIP*PREF_RR,2)

        rr=round(abs(tp-entry)/abs(sl-entry),2) if abs(sl-entry)>0 else 0.0
        if rr<MIN_RR:
            return ModelResult(ModelType.LIQUIDITY_TRAP,score,direction,None,signals,f"RR {rr}<{MIN_RR}")

        if rr>=PREF_RR:
            score+=0.10
        score=min(round(score,3),1.0)
        setup=TradeSetupProposal(direction,round(entry,2),sl,tp,rr,1.0,0.01,
                                 f"Liquidity trap: {', '.join(signals[:4])}",f"SL {sl_pips:.0f}pips","TP at opposite liquidity")
        log.info("trap conf=%.2f dir=%s rr=%.1f",score,direction.value,rr)
        return ModelResult(ModelType.LIQUIDITY_TRAP,score,direction,setup,signals)
