from __future__ import annotations
import logging
from ..types import Direction,LiquidityBias,LiquidityLevel,ModelResult,ModelType,NarrativePattern,SessionType,TradeSetupProposal,VolatilityRegime
log=logging.getLogger("jeafx.expansion_model")
MAX_SL=150.0; PIP=0.1; MIN_RR=3.0; PREF_RR=4.0

class ExpansionModel:
    def evaluate(self,session,vol_regime,sweep_detected,sweep_side,narrative_pattern,bos_direction,
                 breakout_direction,asia_compression,displacement,fvg_high,fvg_low,pullback_entry,
                 order_block_high,order_block_low,current_price,atr,
                 sell_side_levels,buy_side_levels,liquidity_bias,macro_bias) -> ModelResult:
        signals=[]; score=0.0
        if session not in (SessionType.LONDON,SessionType.LONDON_NY_OVERLAP):
            return ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"Not London/Overlap")
        if not asia_compression:
            return ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"Asia not compressed")
        if breakout_direction not in ("BUY","SELL"):
            return ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"No London breakout")
        if not displacement:
            return ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"No displacement candle")
        if not (fvg_high>0 and fvg_low>0 and fvg_high>fvg_low):
            return ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"No FVG detected")
        if not pullback_entry:
            return ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"No FVG pullback entry")
        if vol_regime not in (VolatilityRegime.COMPRESSION,VolatilityRegime.EXPANSION,VolatilityRegime.NORMAL):
            return ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],f"Vol {vol_regime.value} not suitable")
        score+=0.20; signals.append("Asia compression ✓")
        score+=0.20; signals.append(f"London breakout {breakout_direction} ✓")
        score+=0.15; signals.append("Displacement ✓")
        score+=0.15; signals.append(f"FVG {fvg_low:.2f}-{fvg_high:.2f} ✓")
        score+=0.10; signals.append("FVG pullback ✓")
        if narrative_pattern in (NarrativePattern.LONDON_EXPANSION,NarrativePattern.ASIA_COMPRESSION):
            score+=0.20; signals.append(f"Narrative {narrative_pattern.value} ✓")
        direction=Direction.BUY if breakout_direction=="BUY" else Direction.SELL
        if bos_direction==direction.value:
            score+=0.10; signals.append(f"BOS {bos_direction} ✓")
        if sweep_detected:
            if (direction==Direction.BUY and sweep_side=="buy") or (direction==Direction.SELL and sweep_side=="sell"):
                score+=0.10; signals.append("Sweep aligned ✓")
        if macro_bias=="BULLISH_GOLD" and direction==Direction.BUY:   score+=0.10; signals.append("Macro aligned ✓")
        elif macro_bias=="BEARISH_GOLD" and direction==Direction.SELL: score+=0.10; signals.append("Macro aligned ✓")
        entry=current_price
        if order_block_high>0: signals.append(f"OB {order_block_low:.2f}-{order_block_high:.2f}")
        sl_pips=min(max(atr*1.5/PIP,20.0),MAX_SL)
        if direction==Direction.BUY:
            sl=round(entry-sl_pips*PIP,2)
            tl=[l for l in sell_side_levels if l.price>entry+sl_pips*PIP*MIN_RR]
            tp=round(tl[0].price-3.0,2) if tl else round(entry+sl_pips*PIP*PREF_RR,2)
        else:
            sl=round(entry+sl_pips*PIP,2)
            tl=[l for l in buy_side_levels if l.price<entry-sl_pips*PIP*MIN_RR]
            tp=round(tl[0].price+3.0,2) if tl else round(entry-sl_pips*PIP*PREF_RR,2)
        rr=round(abs(tp-entry)/abs(sl-entry),2) if abs(sl-entry)>0 else 0.0
        if rr<MIN_RR: return ModelResult(ModelType.EXPANSION,score,direction,None,signals,f"RR {rr}<{MIN_RR}")
        if rr>=PREF_RR: score+=0.10
        score=min(round(score,3),1.0)
        setup=TradeSetupProposal(direction,round(entry,2),sl,tp,rr,1.0,0.01,
                                  f"Expansion: {', '.join(signals[:3])}",f"SL {sl_pips:.0f}pips","TP at liquidity")
        log.info("expansion conf=%.2f dir=%s rr=%.1f",score,direction.value,rr)
        return ModelResult(ModelType.EXPANSION,score,direction,setup,signals)
