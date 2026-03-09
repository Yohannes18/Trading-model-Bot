from __future__ import annotations
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from quantara.context.session_engine import get_session_context
from quantara.context.volatility_regime_engine import detect_volatility_regime
from quantara.liquidity.liquidity_memory_engine import LiquidityMemoryEngine
from quantara.narrative.fundamental_narrative_engine import get_daily_narrative

from .entry.fibonacci_engine import FibonacciEngine
from .amd.phase_detector import AMDPhaseDetector
from .entry.orderblock_engine import OrderBlockEngine
from .liquidity_heatmap import LiquidityHeatmapEngine
from .liquidity.liquidity_map import LiquidityMap
from .liquidity.sweep_detector import SweepDetector
from .macro.macro_engine import MacroEngine
from .models.expansion_model import ExpansionModel
from .models.liquidity_trap_model import LiquidityTrapModel
from .models.reversal_model import ReversalModel
from .narrative.session_analyzer import SessionAnalyzer
from .pattern.crt_model import CRTModel
from .pattern.head_shoulders import HeadShoulders
from .pattern.structure_shift import StructureShift
from .sessions.session_engine import SessionEngine
from .types import (AMDPhase, Direction, MacroBias, MarketAnalysis, ModelType,
                    NarrativeEvent, NarrativePattern, SessionType, VolatilityRegime)

log = logging.getLogger("quantara.analysis")
MIN_CONF = 0.55


class AnalysisEngine:
    """Master orchestrator: 15-step institutional analysis pipeline for Gold."""

    def __init__(self) -> None:
        from engine.confidence_engine import TradeConfidenceEngine
        from engine.displacement_engine import DisplacementEngine
        from engine.inefficiency_engine import MarketInefficiencyEngine
        from engine.liquidity_map_engine import LiquidityMapEngine
        from engine.liquidity_magnet_engine import LiquidityMagnetEngine
        from engine.liquidity_regime_engine import LiquidityRegimeEngine
        from engine.liquidity_raid_predictor import LiquidityRaidPredictor
        from engine.macro_narrative_engine import MacroNarrativeEngine
        from engine.narrative_engine import NarrativeEngineV2
        from engine.trap_detector import LiquidityTrapDetector
        from engine.volatility_engine import VolatilityExpansionEngine

        self._macro     = MacroEngine()
        self._session   = SessionEngine()
        self._sess_anal = SessionAnalyzer()
        self._narrative = NarrativeEngineV2()
        self._liq_map   = LiquidityMap()
        self._liq_pools = LiquidityMapEngine()
        self._liq_regime = LiquidityRegimeEngine()
        self._liq_magnet = LiquidityMagnetEngine()
        self._heatmap   = LiquidityHeatmapEngine()
        self._raid      = LiquidityRaidPredictor()
        self._ime       = MarketInefficiencyEngine()
        self._trap_det  = LiquidityTrapDetector()
        self._disp      = DisplacementEngine()
        self._macro_narr= MacroNarrativeEngine()
        self._trade_conf= TradeConfidenceEngine()
        self._sweep     = SweepDetector()
        self._volx      = VolatilityExpansionEngine()
        self._structure = StructureShift()
        self._crt       = CRTModel()
        self._hs        = HeadShoulders()
        self._fib       = FibonacciEngine()
        self._amd       = AMDPhaseDetector()
        self._ob        = OrderBlockEngine()
        self._exp_model = ExpansionModel()
        self._rev_model = ReversalModel()
        self._trap_model = LiquidityTrapModel()
        self._liquidity_memory = LiquidityMemoryEngine()
        self._params    = self._load_trading_parameters()
        self._model_weights = self._load_model_weights()

    def analyze(
        self,
        candles_m30,
        candles_h1,
        candles_h4,
        candles_d1,
        pair: str = "XAUUSD",
        timeframe: str = "M30",
    ) -> MarketAnalysis:
        return self.analyze_market(candles_m30, candles_h1, candles_h4, candles_d1, pair, timeframe=timeframe)

    def analyze_market(
        self,
        candles_m30,
        candles_h1,
        candles_h4,
        candles_d1,
        pair: str = "XAUUSD",
        timeframe: str = "M30",
    ) -> MarketAnalysis:
        now = datetime.now(tz=timezone.utc)
        result = MarketAnalysis(timestamp=now, pair=pair, timeframe=timeframe)
        analysis_cache: dict[str, object] = {}
        ok, integrity_reason = self._validate_candles(candles_m30)
        if not ok:
            result.briefing = f"Candle integrity check failed: {integrity_reason}"
            return result
        if len(candles_m30)<50:
            result.briefing="Insufficient candle data."
            return result
        price=candles_m30[-1].close
        session_context = get_session_context(now)
        session_weight = float(session_context.get("weight", 1.0))
        volatility_context = detect_volatility_regime(candles_m30)
        volatility_weight = float(volatility_context.get("weight", 1.0))
        daily_narrative = get_daily_narrative(pair)
        narrative_score = float(daily_narrative.get("score", 1.0))

        # 1. Macro
        try: macro=self._macro.evaluate()
        except Exception as e: log.warning("macro_err %s",e); macro=MacroBias.NEUTRAL
        result.macro_bias=macro

        # 2. Session
        session,behavior=self._session.get_session()
        result.session=session; result.session_behavior=behavior

        # 3. Asia analysis
        asia=self._sess_anal.analyze_asia(candles_h1 or candles_m30)
        result.asia_session=asia

        # 3. Preliminary breakout/displacement/FVG for AMD + model context
        brk_dir,displacement=self._london_breakout(candles_m30,asia.high,asia.low)
        if "fvg_core" not in analysis_cache:
            analysis_cache["fvg_core"] = self._find_fvg(candles_m30,brk_dir)
        fvg_low,fvg_high=analysis_cache["fvg_core"]

        # 4. AMD phase detection
        amd=self._amd.detect(
            pair=pair,
            session=session,
            candles_m30=candles_m30,
            candles_d1=candles_d1,
            asia_range=(asia.high-asia.low) if asia and asia.high>asia.low else 0.0,
            buy_levels=[],
            sell_levels=[],
            sweep_detected=False,
            sweep_trap=False,
            mss_detected=False,
            volatility_regime="NORMAL",
            displacement=displacement,
            fvg_detected=(fvg_high>0 and fvg_low>0),
        )
        result.amd_phase=amd.phase
        result.amd_confidence=amd.confidence
        result.accumulation_confidence=amd.accumulation_confidence
        result.manipulation_confidence=amd.manipulation_confidence
        result.distribution_confidence=amd.distribution_confidence
        result.amd_reason=amd.reason

        # 5. Volatility expansion
        if "volatility" not in analysis_cache:
            analysis_cache["volatility"] = self._volx.analyze(candles_m30,session)
        volx=analysis_cache["volatility"]
        result.volatility=volx
        result.volatility_regime=volx.regime
        atr=volx.atr

        # 6. Liquidity Regime
        result.liquidity_regime = self._liq_regime.analyze(
            candles=candles_m30,
            session=session,
            volatility_profile=volx,
            amd_state=amd,
            heatmap_zones=[],
            raid_signals=None,
        )

        # 7. Narrative engine
        narr=self._narrative.analyze(candles_m30, session)
        result.narrative=narr
        result.narrative_pattern=self._map_narrative_pattern(narr,session)
        result.narrative_scores=[]

        # Supporting liquidity map + sweep for model/risk context
        buy,sell=self._liq_map.build(candles_m30,candles_h4,candles_d1,asia.high,asia.low)
        result.buy_side_levels=buy; result.sell_side_levels=sell
        sweep=self._sweep.detect(candles_m30,buy,sell)
        result.sweep_detected=sweep.detected; result.liquidity_trap=sweep.trap

        # 7. HTF bias (H4 + D1)
        htf_bias=self._htf_bias(candles_h4,candles_d1)

        # 8. CRT
        crt=self._crt.detect(candles_m30)

        # 9. H&S
        hs=self._hs.detect(candles_h1 or candles_m30)

        conflicting=self._has_conflicting_narrative(narr)
        if narr.bias == "NEUTRAL" and narrative_score > 0.8:
            narrative_score = 0.8
        if narr.strength < self._params.get("narrative_strength_min", 0.45):
            narrative_score = min(narrative_score, max(0.55, narr.strength + 0.2))
        if conflicting:
            narrative_score *= 0.8

        liquidity_memory = self._liquidity_memory.update(candles_d1, price)

        # 8. Liquidity heatmap
        if "heatmap_base" not in analysis_cache:
            analysis_cache["heatmap_base"] = self._heatmap.build(price,buy,sell,candles_m30,candles_d1,fvg_low,fvg_high,0.0,0.0)
        hm=analysis_cache["heatmap_base"]
        result.liquidity_bias=hm.bias
        result.liquidity_zones_above=hm.zones_above
        result.liquidity_zones_below=hm.zones_below

        # 9. Liquidity Map
        liq_map = self._liq_pools.analyze(
            candles=candles_m30,
            current_price=price,
            atr=max(atr, 0.1),
            session=session,
            session_high=asia.high if asia and asia.high > 0 else None,
            session_low=asia.low if asia and asia.low > 0 else None,
            tolerance_factor=self._params.get("liquidity_tolerance", 0.05),
        )
        result.liquidity_map = liq_map

        # 10. Liquidity raid predictor
        raid=self._raid.predict(
            current_price=price,
            zones_above=result.liquidity_zones_above,
            zones_below=result.liquidity_zones_below,
            narrative=narr,
            amd_phase=amd.phase,
            volatility=volx,
            session=session,
            risk_unit=max(atr, 0.1),
        )
        result.raid_prediction=raid

        # 11. Inefficiency engine (IME)
        ineff=self._ime.build_map(candles_m30, price, max(atr, 0.1), session=session.value)
        result.inefficiency_map=ineff

        result.liquidity_regime = self._liq_regime.analyze(
            candles=candles_m30,
            session=session,
            volatility_profile=volx,
            amd_state=amd,
            heatmap_zones=(hm.zones_above + hm.zones_below),
            raid_signals=raid,
        )

        # 12. Trap detector
        nearest_liq_score = raid.target_zone.score if raid.target_zone.zone_type != "NONE" else 0
        trap_analysis=self._trap_det.analyze(
            candles=candles_m30,
            sweep_detected=sweep.detected,
            displacement_detected=narr.displacement_detected,
            nearest_liquidity_score=nearest_liq_score,
            session=session.value,
            sensitivity=self._params.get("trap_sensitivity", 1.0),
        )
        result.trap_analysis=trap_analysis

        if amd.phase == AMDPhase.ACCUMULATION or raid.probability < 0.40 or not raid.path_clear:
            from .types import ModelResult, ModelType, Direction
            reason = "amd_accumulation" if amd.phase == AMDPhase.ACCUMULATION else (
                "raid_probability_low" if raid.probability < 0.40 else "raid_path_blocked"
            )
            result.recommended_model=ModelType.NO_TRADE
            result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],reason)
            result.has_trade_setup=False
            result.briefing=self._briefing(result,
                                          ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"Blocked by raid predictor"),
                                          ModelResult(ModelType.REVERSAL,0.0,Direction.NONE,None,[],"Blocked by raid predictor"),
                                          ModelResult(ModelType.LIQUIDITY_TRAP,0.0,Direction.NONE,None,[],"Blocked by raid predictor"),
                                          result.model_result,atr,narr,hm,buy,sell,price)
            return result

        # Volatility compression gate
        if volx.regime == VolatilityRegime.COMPRESSION:
            from .types import ModelResult, ModelType, Direction
            result.recommended_model=ModelType.NO_TRADE
            result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],"volatility_compression")
            result.has_trade_setup=False
            result.briefing=self._briefing(result,
                                          ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"Blocked by volatility"),
                                          ModelResult(ModelType.REVERSAL,0.0,Direction.NONE,None,[],"Blocked by volatility"),
                                          ModelResult(ModelType.LIQUIDITY_TRAP,0.0,Direction.NONE,None,[],"Blocked by volatility"),
                                          result.model_result,atr,None,hm,buy,sell,price)
            return result

        # 14. Structure
        struct=self._structure.detect(candles_m30)

        # 15. Fib
        fib_dir="BUY"
        if struct.direction!="NONE":  fib_dir=struct.direction
        elif sweep.side=="sell":      fib_dir="SELL"
        fib=self._fib.analyze(candles_m30,fib_dir)

        # 16. OB
        obs=self._ob.find_order_blocks(candles_m30,fib_dir)
        ob=obs[0] if obs else None
        ob_h=ob.high if ob else 0.0; ob_l=ob.low if ob else 0.0

        # Recompute heatmap with OB/FVG magnets enriched
        hm=self._heatmap.build(price,buy,sell,candles_m30,candles_d1,fvg_low,fvg_high,ob_l,ob_h)
        result.liquidity_bias=hm.bias
        result.liquidity_zones_above=hm.zones_above
        result.liquidity_zones_below=hm.zones_below
        pullback_entry = fvg_low>0 and fvg_high>0 and fvg_low<=price<=fvg_high

        # Accumulation phase: monitor only, skip trade suggestions
        if amd.phase==AMDPhase.ACCUMULATION:
            from .types import ModelResult, ModelType, Direction
            result.recommended_model=ModelType.NO_TRADE
            result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],"AMD Accumulation — monitor only")
            result.has_trade_setup=False
            result.briefing=self._briefing(result,
                                          ModelResult(ModelType.EXPANSION,0.0,Direction.NONE,None,[],"Blocked by AMD"),
                                          ModelResult(ModelType.REVERSAL,0.0,Direction.NONE,None,[],"Blocked by AMD"),
                                          ModelResult(ModelType.LIQUIDITY_TRAP,0.0,Direction.NONE,None,[],"Blocked by AMD"),
                                          result.model_result,atr,narr,hm,buy,sell,price)
            return result

        # 18. Expansion model
        exp=self._exp_model.evaluate(
            session,volx.regime,sweep.detected,sweep.side,result.narrative_pattern,
            struct.direction,brk_dir,asia.classification=="COMPRESSION",displacement,
            fvg_high,fvg_low,pullback_entry,
            ob_h,ob_l,price,atr,sell,buy,hm.bias,macro.value)

        # 19. Reversal model
        rev=self._rev_model.evaluate(
            session,sweep.detected,sweep.side,sweep.trap,crt.direction,
            hs.direction if hs.detected else "NONE",hs.confidence,
            struct.direction if struct.mss_detected else "NONE",
            fib.entry_zone.price if fib.entry_zone else 0.0,
            ob_h,ob_l,htf_bias,price,atr,sell,buy,result.narrative_pattern,macro.value)

        # 20. Liquidity trap model
        trap=self._trap_model.evaluate(
            session,result.narrative_pattern,sweep.detected,sweep.trap,
            struct.direction if struct.mss_detected else "NONE",
            brk_dir,price,atr,sell,buy,macro.value)

        exp=self._apply_raid_direction_gate(exp,result.raid_prediction.raid_direction)
        rev=self._apply_raid_direction_gate(rev,result.raid_prediction.raid_direction)
        trap=self._apply_raid_direction_gate(trap,result.raid_prediction.raid_direction)

        if trap_analysis.trap_probability > 60:
            if exp.setup is not None:
                exp.confidence = round(max(0.0, exp.confidence * 0.70), 3)
            rev.confidence = round(min(1.0, rev.confidence + 0.12), 3)
            trap.confidence = round(min(1.0, trap.confidence + 0.08), 3)

        ineff_dir = self._inefficiency_direction(price, ineff)
        exp = self._apply_direction_alignment(exp, ineff_dir)
        rev = self._apply_direction_alignment(rev, ineff_dir)
        trap = self._apply_direction_alignment(trap, ineff_dir)

        # 13. Macro Narrative engine
        macro_narrative = self._macro_narr.analyze(candles_m30, macro.value)
        result.macro_narrative = macro_narrative
        if macro_narrative.trade_blocked:
            from .types import ModelResult, ModelType, Direction
            result.recommended_model=ModelType.NO_TRADE
            result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],"macro_news_risk_block")
            result.has_trade_setup=False
            result.briefing=self._briefing(result,exp,rev,trap,result.model_result,atr,narr,hm,buy,sell,price)
            return result

        # 14. Displacement engine
        displacement_result = self._disp.analyze(
            candles=candles_m30,
            atr=max(atr, 0.1),
            break_of_structure=bool(struct.mss_detected or narr.bos_detected),
            volume_multiplier=self._params.get("displacement_volume_multiplier", 1.5),
        )
        result.displacement = displacement_result

        # 15. Liquidity magnet engine
        magnet_result = self._liq_magnet.analyze(
            liquidity_map=liq_map,
            volatility_regime=volx.regime.value,
            displacement=displacement_result,
            current_price=price,
        )
        result.liquidity_magnet = magnet_result

        # 16. Confidence factors preparation
        base_liquidity_strength = min(1.0, (raid.target_zone.score / 10.0) if raid.target_zone.zone_type != "NONE" else 0.0)
        liquidity_bias = self._liquidity_map_confidence_bias(liq_map, raid.raid_direction, price, max(atr, 0.1))
        magnet_bonus = magnet_result.primary_magnet.magnet_strength * 0.2 if magnet_result.primary_magnet is not None else 0.0
        adjusted_liquidity_strength = max(0.0, min(1.0, base_liquidity_strength + liquidity_bias + magnet_bonus))
        session_weight = float(session_context.get("weight", 1.0))
        volatility_alignment = float(volatility_context.get("weight", 1.0))
        macro_alignment = self._macro_alignment(macro_narrative, narr)
        trap_risk_01 = min(1.0, trap_analysis.trap_probability / 100.0)

        result.expansion_confidence=exp.confidence
        result.reversal_confidence=rev.confidence
        result.trap_confidence=trap.confidence

        # 17. Model selector
        exp, rev, trap = self.adjust_for_liquidity(exp, rev, trap, result.liquidity_regime)
        exp, rev, trap = self._adjust_models_with_liquidity_map(exp, rev, trap, liq_map, price)
        exp, rev, trap = self._adjust_models_with_displacement(exp, rev, trap, displacement_result)
        exp, rev, trap = self._adjust_models_with_magnet(exp, rev, trap, magnet_result)
        exp, rev, trap = self._apply_meta_model_weights(exp, rev, trap)
        liquidity_memory_score = float(liquidity_memory.get("score", 0.5))
        liquidity_memory_side = str(liquidity_memory.get("side", "NONE"))

        for model in (exp, rev, trap):
            base_confidence = model.confidence
            confidence = base_confidence
            confidence *= narrative_score
            confidence *= session_weight
            confidence *= volatility_weight
            if model.setup is not None:
                direction = model.setup.direction.value
                if (direction == "BUY" and liquidity_memory_side == "BUY") or (direction == "SELL" and liquidity_memory_side == "SELL"):
                    confidence *= (1.0 + 0.1 * liquidity_memory_score)
                elif liquidity_memory_side in ("BUY", "SELL"):
                    confidence *= max(0.7, 1.0 - 0.15 * liquidity_memory_score)
            model.confidence = round(max(0.0, min(1.0, confidence)), 3)

        best=self._select_competitive_model(
            exp=exp,
            rev=rev,
            trap=trap,
            amd_phase=amd.phase,
            narr=narr,
            raid=raid,
            volx=volx,
            macro_bias=macro.value,
            trap_analysis=trap_analysis,
            ineff=ineff,
            liq_map=liq_map,
            current_price=price,
            atr=max(atr, 0.1),
            pair=pair,
        )
        result.recommended_model=best.model_type
        result.model_result=best
        result.has_trade_setup=best.setup is not None
        result.confidence_result = self._confidence_from_selected_model(
            best,
            threshold=self._params.get("model_confidence_threshold", 70.0),
        )

        if result.model_result and result.model_result.setup:
            setup=result.model_result.setup
            target,dist_r,path_clear=self._heatmap.pick_target(
                setup.direction.value,
                setup.entry,
                setup.stop_loss,
                result.liquidity_zones_above,
                result.liquidity_zones_below,
                min_score=5,
            )
            result.nearest_magnet=target
            result.nearest_magnet_distance_r=dist_r
            result.liquidity_path_clear=path_clear
            from .types import ModelResult, ModelType, Direction
            if target is None:
                result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],"No strong liquidity target (score<5)")
                result.recommended_model=ModelType.NO_TRADE
                result.has_trade_setup=False
            elif dist_r<3.0:
                result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],f"Liquidity distance {dist_r:.1f}R < 3R")
                result.recommended_model=ModelType.NO_TRADE
                result.has_trade_setup=False
            elif not path_clear:
                result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],"Liquidity path blocked")
                result.recommended_model=ModelType.NO_TRADE
                result.has_trade_setup=False
            else:
                expected_move=atr*2.0
                liq_distance=abs(target.price-setup.entry)
                if liq_distance<expected_move:
                    result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],f"Target below expected volatility move ({liq_distance:.2f}<{expected_move:.2f})")
                    result.recommended_model=ModelType.NO_TRADE
                    result.has_trade_setup=False
                    best=result.model_result
                    result.briefing=self._briefing(result,exp,rev,trap,best,atr,narr,hm,buy,sell,price)
                    return result
                setup.take_profit=target.price
                rr=round(abs(setup.take_profit-setup.entry)/abs(setup.stop_loss-setup.entry),2) if abs(setup.stop_loss-setup.entry)>0 else 0.0
                setup.rr=rr
                if rr<3.0:
                    result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],f"Target RR {rr}<3")
                    result.recommended_model=ModelType.NO_TRADE
                    result.has_trade_setup=False
                sl_pips = abs(setup.entry - setup.stop_loss) / 0.1
                if pair == "XAUUSD" and sl_pips > 150:
                    result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],f"SL {sl_pips:.0f} pips > 150")
                    result.recommended_model=ModelType.NO_TRADE
                    result.has_trade_setup=False
                if result.confidence_result.score >= 75 and setup.rr < 4.0:
                    result.model_result=ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],f"Preferred setup requires RR>=4 at confidence {result.confidence_result.score:.0f}")
                    result.recommended_model=ModelType.NO_TRADE
                    result.has_trade_setup=False

        best=result.model_result if result.model_result is not None else best
        result.briefing=self._briefing(result,exp,rev,trap,best,atr,narr,hm,buy,sell,price)
        log.info(
            "Session: %s | Volatility: %s | Narrative: %s | Liquidity Target: %s | Confidence: %.2f",
            session_context.get("session", session.value),
            volatility_context.get("regime", volx.regime.value),
            str(daily_narrative.get("bias", narr.bias)).upper(),
            liquidity_memory.get("target", "NONE"),
            result.confidence_result.score / 100.0,
        )
        log.info("analysis pair=%s session=%s vol=%s exp=%.2f rev=%.2f trap=%.2f model=%s setup=%s",
             pair,session.value,volx.regime.value,exp.confidence,rev.confidence,trap.confidence,
                 best.model_type.value,result.has_trade_setup)
        return result

    def adjust_for_liquidity(self, exp, rev, trap, regime_result):
        if regime_result is None:
            return exp, rev, trap
        regime = regime_result.regime.value

        if regime == "accumulation":
            exp.confidence = round(max(0.0, exp.confidence - 0.10), 3)
            rev.confidence = round(min(1.0, rev.confidence + 0.06), 3)
            trap.confidence = round(min(1.0, trap.confidence + 0.05), 3)
        elif regime == "expansion":
            exp.confidence = round(min(1.0, exp.confidence + 0.12), 3)
            rev.confidence = round(max(0.0, rev.confidence - 0.07), 3)
            trap.confidence = round(max(0.0, trap.confidence - 0.05), 3)
        elif regime == "manipulation":
            exp.confidence = round(max(0.0, exp.confidence - 0.12), 3)
            rev.confidence = round(min(1.0, rev.confidence + 0.06), 3)
            trap.confidence = round(min(1.0, trap.confidence + 0.10), 3)
        elif regime == "distribution":
            exp.confidence = round(max(0.0, exp.confidence - 0.09), 3)
            rev.confidence = round(min(1.0, rev.confidence + 0.11), 3)
            trap.confidence = round(min(1.0, trap.confidence + 0.03), 3)

        return exp, rev, trap

    def _liquidity_map_confidence_bias(self, liq_map, raid_direction: str, current_price: float, atr: float) -> float:
        if liq_map is None:
            return 0.0
        if raid_direction == "UP":
            aligned = liq_map.nearest_above
            opposing = liq_map.nearest_below
        elif raid_direction == "DOWN":
            aligned = liq_map.nearest_below
            opposing = liq_map.nearest_above
        else:
            return 0.0

        boost = 0.0
        if aligned is not None and aligned.strength >= 0.55:
            boost += 0.1

        if opposing is not None:
            distance_r = abs(opposing.price - current_price) / max(atr, 1e-9)
            if opposing.strength >= 0.75 and distance_r <= 1.2:
                boost -= 0.2
        return boost

    def _adjust_models_with_liquidity_map(self, exp, rev, trap, liq_map, current_price: float):
        if liq_map is None:
            return exp, rev, trap

        nearest_above = liq_map.nearest_above
        nearest_below = liq_map.nearest_below

        if nearest_above is not None and nearest_above.strength >= 0.65:
            if exp.setup is not None and exp.setup.direction.value == "BUY":
                exp.confidence = round(min(1.0, exp.confidence + 0.05), 3)
            if rev.setup is not None and rev.setup.direction.value == "SELL":
                rev.confidence = round(max(0.0, rev.confidence - 0.04), 3)

        if nearest_below is not None and nearest_below.strength >= 0.65:
            if exp.setup is not None and exp.setup.direction.value == "SELL":
                exp.confidence = round(min(1.0, exp.confidence + 0.05), 3)
            if rev.setup is not None and rev.setup.direction.value == "BUY":
                rev.confidence = round(max(0.0, rev.confidence - 0.04), 3)

        return exp, rev, trap

    def _adjust_models_with_displacement(self, exp, rev, trap, displacement):
        if displacement is None or not displacement.displacement_detected:
            return exp, rev, trap
        if displacement.direction == "UP":
            if exp.setup is not None and exp.setup.direction.value == "BUY":
                exp.confidence = round(min(1.0, exp.confidence + 0.08 * displacement.strength), 3)
            if rev.setup is not None and rev.setup.direction.value == "SELL":
                rev.confidence = round(max(0.0, rev.confidence - 0.06 * displacement.strength), 3)
        elif displacement.direction == "DOWN":
            if exp.setup is not None and exp.setup.direction.value == "SELL":
                exp.confidence = round(min(1.0, exp.confidence + 0.08 * displacement.strength), 3)
            if rev.setup is not None and rev.setup.direction.value == "BUY":
                rev.confidence = round(max(0.0, rev.confidence - 0.06 * displacement.strength), 3)
        return exp, rev, trap

    def _adjust_models_with_magnet(self, exp, rev, trap, magnet_result):
        if magnet_result is None or magnet_result.primary_magnet is None:
            return exp, rev, trap
        strength = magnet_result.primary_magnet.magnet_strength
        if strength >= 0.6:
            exp.confidence = round(min(1.0, exp.confidence + 0.05), 3)
        return exp, rev, trap

    def _macro_alignment(self, macro_narrative, narr) -> float:
        if macro_narrative is None:
            return 0.5
        if macro_narrative.bias == "neutral" or narr.bias == "NEUTRAL":
            return 0.5
        if macro_narrative.bias == "bullish_gold" and narr.bias == "BULLISH":
            return 1.0
        if macro_narrative.bias == "bearish_gold" and narr.bias == "BEARISH":
            return 1.0
        return 0.3

    def _validate_candles(self, candles) -> tuple[bool, str]:
        if not candles or len(candles) < 5:
            return False, "insufficient_candles"

        times = [c.time for c in candles]
        if len(set(times)) != len(times):
            return False, "duplicate_timestamps"

        diffs = [(times[i] - times[i - 1]).total_seconds() for i in range(1, len(times))]
        if any(d <= 0 for d in diffs):
            return False, "non_monotonic_timestamps"

        median_gap = sorted(diffs)[len(diffs) // 2]
        if any(d > max(2 * median_gap, 3600) for d in diffs):
            return False, "timestamp_gaps"

        if any(getattr(c, "volume", None) is None for c in candles):
            return False, "missing_volume"

        return True, "ok"

    def _load_trading_parameters(self) -> dict[str, float]:
        defaults = {
            "atr_window": 14.0,
            "liquidity_tolerance": 0.05,
            "trap_sensitivity": 1.0,
            "confidence_threshold": 72.0,
            "displacement_volume_multiplier": 1.5,
            "model_confidence_threshold": 70.0,
            "model_rr_min": 3.0,
            "model_ambiguity_delta": 10.0,
            "max_xau_sl_pips": 150.0,
            "session_mode_enabled": 1.0,
            "narrative_strength_min": 0.45,
            "low_risk_session_threshold": 0.52,
            "low_risk_position_multiplier": 0.3,
            "low_risk_sl_multiplier": 0.8,
        }
        cfg_path = Path("config/trading_parameters.yaml")
        if not cfg_path.exists():
            return defaults

        parsed = defaults.copy()
        try:
            for line in cfg_path.read_text().splitlines():
                s = line.strip()
                if not s or s.startswith("#") or ":" not in s:
                    continue
                key, value = s.split(":", 1)
                key = key.strip()
                value = value.strip()
                if not value:
                    continue
                try:
                    parsed[key] = float(value)
                except ValueError:
                    lower = value.lower().strip('"').strip("'")
                    if lower in ("true", "false"):
                        parsed[key] = 1.0 if lower == "true" else 0.0
                    continue
        except Exception:
            return defaults
        return parsed

    def _load_model_weights(self) -> dict[str, float]:
        defaults = {
            "EXPANSION": 1.0,
            "REVERSAL": 1.0,
            "LIQUIDITY_TRAP": 1.0,
        }
        path = Path("config/model_weights.yaml")
        if not path.exists():
            return defaults
        parsed = defaults.copy()
        try:
            for line in path.read_text().splitlines():
                s = line.strip()
                if not s or s.startswith("#") or ":" not in s:
                    continue
                k, v = s.split(":", 1)
                k = k.strip().upper()
                k = {
                    "REVERSAL_MODEL": "REVERSAL",
                    "CONTINUATION_MODEL": "EXPANSION",
                    "RAID_MODEL": "LIQUIDITY_TRAP",
                    "LIQUIDITY_TRAP_MODEL": "LIQUIDITY_TRAP",
                }.get(k, k)
                try:
                    parsed[k] = float(v.strip())
                except ValueError:
                    continue
        except Exception:
            return defaults
        return parsed

    def _apply_meta_model_weights(self, exp, rev, trap):
        self._model_weights = self._load_model_weights()

        def _adjust(conf: float, weight: float) -> float:
            adjusted = conf * (1.0 + (weight - 1.0) * 0.25)
            return round(max(0.0, min(1.0, adjusted)), 3)

        exp.confidence = _adjust(max(0.0, exp.confidence), self._model_weights.get("EXPANSION", 1.0))
        rev.confidence = _adjust(max(0.0, rev.confidence), self._model_weights.get("REVERSAL", 1.0))
        trap.confidence = _adjust(max(0.0, trap.confidence), self._model_weights.get("LIQUIDITY_TRAP", 1.0))
        return exp, rev, trap

    def _confidence_from_selected_model(self, best, threshold: float):
        from .types import ConfidenceResult

        score = round(max(0.0, min(100.0, best.confidence * 100.0)), 2)
        if best.model_type == ModelType.NO_TRADE or best.setup is None:
            return ConfidenceResult(score, "NO_TRADE", False, best.blocked_reason or "No valid model")

        if score < threshold:
            return ConfidenceResult(score, "NO_TRADE", False, f"Selected model confidence {score:.1f} < {threshold:.1f}")
        if score < 80.0:
            return ConfidenceResult(score, "VALID_SETUP", True, "Selected model passed competition")
        return ConfidenceResult(score, "HIGH_PROBABILITY", True, "Selected model high confidence")

    def _select_competitive_model(
        self,
        exp,
        rev,
        trap,
        amd_phase,
        narr,
        raid,
        volx,
        macro_bias: str,
        trap_analysis,
        ineff,
        liq_map,
        current_price: float,
        atr: float,
        pair: str,
    ):
        from .types import Direction, ModelResult, ModelType

        candidates = [exp, rev, trap]
        for model in candidates:
            score = self._model_competitive_confidence(
                model_result=model,
                amd_phase=amd_phase,
                narr=narr,
                raid=raid,
                volx=volx,
                macro_bias=macro_bias,
                trap_analysis=trap_analysis,
                ineff=ineff,
                liq_map=liq_map,
                current_price=current_price,
                atr=atr,
            )
            model.confidence = round(score / 100.0, 3)

        min_confidence_pct = self._params.get("model_confidence_threshold", 70.0)
        min_rr = self._params.get("model_rr_min", 3.0)
        max_xau_sl_pips = self._params.get("max_xau_sl_pips", 150.0)
        ambiguity_delta_pct = self._params.get("model_ambiguity_delta", 10.0)

        valid_models = []
        blocked_reasons: list[str] = []
        for model in candidates:
            setup = model.setup
            if setup is None:
                blocked_reasons.append(f"{model.model_type.value}:no_setup")
                continue
            conf_pct = model.confidence * 100.0
            if conf_pct < min_confidence_pct:
                blocked_reasons.append(f"{model.model_type.value}:conf<{min_confidence_pct:.0f}")
                continue
            if setup.rr < min_rr:
                blocked_reasons.append(f"{model.model_type.value}:rr<{min_rr:.1f}")
                continue
            sl_pips = abs(setup.entry - setup.stop_loss) / 0.1
            if pair == "XAUUSD" and sl_pips > max_xau_sl_pips:
                blocked_reasons.append(f"{model.model_type.value}:sl>{max_xau_sl_pips:.0f}p")
                continue
            valid_models.append(model)

        if not valid_models:
            return ModelResult(
                ModelType.NO_TRADE,
                0.0,
                Direction.NONE,
                None,
                [],
                "competitive_gate: " + ", ".join(blocked_reasons[:4]),
            )

        ranked = sorted(valid_models, key=lambda m: m.confidence, reverse=True)
        if len(ranked) >= 2:
            delta_pct = (ranked[0].confidence - ranked[1].confidence) * 100.0
            if delta_pct < ambiguity_delta_pct:
                return ModelResult(
                    ModelType.NO_TRADE,
                    0.0,
                    Direction.NONE,
                    None,
                    [],
                    f"model_ambiguity delta={delta_pct:.1f}%<{ambiguity_delta_pct:.1f}%",
                )
        return ranked[0]

    def _model_competitive_confidence(
        self,
        model_result,
        amd_phase,
        narr,
        raid,
        volx,
        macro_bias: str,
        trap_analysis,
        ineff,
        liq_map,
        current_price: float,
        atr: float,
    ) -> float:
        if model_result is None or model_result.setup is None:
            return 0.0

        model_type = model_result.model_type
        setup_direction = model_result.setup.direction.value
        raid_direction = raid.raid_direction if raid is not None else "NONE"

        amd_alignment = self._amd_alignment_for_model(amd_phase, model_type)
        narrative_alignment = self._narrative_alignment_for_model(narr, setup_direction, model_type)
        liquidity_strength = self._liquidity_alignment_for_model(liq_map, raid_direction, setup_direction, current_price, atr)
        raid_probability = self._raid_alignment_for_model(raid, setup_direction)
        volatility_expansion = self._volatility_alignment_for_model(volx.regime, model_type)
        fundamental_bias = self._fundamental_alignment_for_direction(macro_bias, setup_direction)
        trap_risk = self._trap_risk_for_model(trap_analysis, model_type)
        inefficiency_magnet = self._inefficiency_alignment_for_direction(ineff, current_price, setup_direction)

        confidence = self._trade_conf.evaluate(
            amd_alignment=amd_alignment,
            narrative_alignment=narrative_alignment,
            liquidity_strength=liquidity_strength,
            raid_prediction=raid_probability,
            volatility_expansion=volatility_expansion,
            fundamental_bias=fundamental_bias,
            trap_risk=trap_risk,
            inefficiency_magnet=inefficiency_magnet,
        )
        base_conf = max(0.0, min(100.0, model_result.confidence * 100.0))
        return round((confidence.score * 0.70) + (base_conf * 0.30), 2)

    def _amd_alignment_for_model(self, phase: AMDPhase, model_type: ModelType) -> float:
        if model_type == ModelType.REVERSAL:
            if phase == AMDPhase.MANIPULATION:
                return 1.0
            if phase == AMDPhase.DISTRIBUTION:
                return 0.85
            if phase == AMDPhase.ACCUMULATION:
                return 0.2
            return 0.5
        if model_type == ModelType.EXPANSION:
            if phase == AMDPhase.DISTRIBUTION:
                return 1.0
            if phase == AMDPhase.MANIPULATION:
                return 0.55
            if phase == AMDPhase.ACCUMULATION:
                return 0.2
            return 0.5
        if model_type == ModelType.LIQUIDITY_TRAP:
            if phase == AMDPhase.MANIPULATION:
                return 1.0
            if phase == AMDPhase.DISTRIBUTION:
                return 0.7
            if phase == AMDPhase.ACCUMULATION:
                return 0.25
            return 0.5
        return 0.5

    def _narrative_alignment_for_model(self, narr, setup_direction: str, model_type: ModelType) -> float:
        if narr is None or narr.bias == "NEUTRAL":
            return 0.3
        dir_bias = "BULLISH" if setup_direction == "BUY" else "BEARISH"
        aligned = narr.bias == dir_bias
        base = min(1.0, max(0.0, narr.strength + 0.15)) if aligned else 0.25
        if model_type == ModelType.REVERSAL and NarrativeEvent.TRAP in narr.events:
            return min(1.0, base + 0.15)
        if model_type == ModelType.EXPANSION and NarrativeEvent.CONTINUATION in narr.events:
            return min(1.0, base + 0.15)
        if model_type == ModelType.LIQUIDITY_TRAP and NarrativeEvent.LIQUIDITY_SWEEP in narr.events:
            return min(1.0, base + 0.15)
        return base

    def _liquidity_alignment_for_model(self, liq_map, raid_direction: str, setup_direction: str, current_price: float, atr: float) -> float:
        if liq_map is None:
            return 0.35
        aligned_pool = liq_map.nearest_above if setup_direction == "BUY" else liq_map.nearest_below
        opposing_pool = liq_map.nearest_below if setup_direction == "BUY" else liq_map.nearest_above
        score = 0.45
        if aligned_pool is not None:
            score += min(0.35, max(0.0, aligned_pool.strength * 0.4))
        if opposing_pool is not None:
            distance_r = abs(opposing_pool.price - current_price) / max(atr, 1e-9)
            if opposing_pool.strength >= 0.75 and distance_r <= 1.2:
                score -= 0.2
        if raid_direction == "UP" and setup_direction == "BUY":
            score += 0.1
        if raid_direction == "DOWN" and setup_direction == "SELL":
            score += 0.1
        return max(0.0, min(1.0, score))

    def _raid_alignment_for_model(self, raid, setup_direction: str) -> float:
        if raid is None:
            return 0.4
        if raid.raid_direction == "UP" and setup_direction == "BUY":
            return max(0.0, min(1.0, raid.probability))
        if raid.raid_direction == "DOWN" and setup_direction == "SELL":
            return max(0.0, min(1.0, raid.probability))
        return max(0.0, min(1.0, 1.0 - raid.probability))

    def _volatility_alignment_for_model(self, regime: VolatilityRegime, model_type: ModelType) -> float:
        if regime == VolatilityRegime.EXPANSION:
            return 0.95 if model_type in (ModelType.EXPANSION, ModelType.LIQUIDITY_TRAP) else 0.8
        if regime == VolatilityRegime.NORMAL:
            return 0.7
        return 0.35

    def _fundamental_alignment_for_direction(self, macro_bias: str, setup_direction: str) -> float:
        if macro_bias == "NEUTRAL":
            return 0.5
        if setup_direction == "BUY" and macro_bias == "BULLISH_GOLD":
            return 1.0
        if setup_direction == "SELL" and macro_bias == "BEARISH_GOLD":
            return 1.0
        return 0.3

    def _trap_risk_for_model(self, trap_analysis, model_type: ModelType) -> float:
        if trap_analysis is None:
            return 0.4
        raw = max(0.0, min(1.0, trap_analysis.trap_probability / 100.0))
        if model_type == ModelType.EXPANSION:
            return min(1.0, raw * 1.2)
        if model_type == ModelType.REVERSAL:
            return min(1.0, raw * 0.9)
        if model_type == ModelType.LIQUIDITY_TRAP:
            return min(1.0, raw * 0.8)
        return raw

    def _inefficiency_alignment_for_direction(self, ineff, current_price: float, setup_direction: str) -> float:
        if ineff is None or ineff.nearest_inefficiency is None:
            return 0.35
        nearest = ineff.nearest_inefficiency
        target_direction = "UP" if nearest.midpoint > current_price else "DOWN"
        aligned = (target_direction == "UP" and setup_direction == "BUY") or (
            target_direction == "DOWN" and setup_direction == "SELL"
        )
        base = max(0.0, min(1.0, ineff.magnet_score))
        return min(1.0, base + 0.2) if aligned else max(0.0, base - 0.2)

    def _compare(self,exp,rev,trap,narr,amd_phase,trap_probability):
        from .types import ModelResult, ModelType, Direction
        if amd_phase==AMDPhase.ACCUMULATION:
            return ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],"AMD accumulation gate")
        if narr.strength < 0.35 or narr.bias == "NEUTRAL" or self._has_conflicting_narrative(narr):
            return ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],"Narrative gate")
        if exp.confidence<MIN_CONF and rev.confidence<MIN_CONF and trap.confidence<MIN_CONF:
            return ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],
                               f"All models below {MIN_CONF:.0%}")
        has_sweep = NarrativeEvent.LIQUIDITY_SWEEP in narr.events
        has_disp = NarrativeEvent.DISPLACEMENT in narr.events
        has_bos = NarrativeEvent.BREAK_OF_STRUCTURE in narr.events
        has_cont = NarrativeEvent.CONTINUATION in narr.events
        has_trap = NarrativeEvent.TRAP in narr.events
        if amd_phase==AMDPhase.MANIPULATION:
            if trap.setup and trap.confidence>=max(exp.confidence,rev.confidence)*0.85:
                return trap
            if rev.setup and rev.confidence>=exp.confidence*0.75:
                return rev
        if has_sweep and rev.setup and rev.confidence>=exp.confidence*0.80:
            return rev
        if has_disp and has_bos and exp.setup and exp.confidence>=max(rev.confidence,trap.confidence)*0.80:
            return exp
        if has_cont and exp.setup and narr.bias == "BULLISH" and exp.direction.value == "BUY":
            return exp
        if has_cont and exp.setup and narr.bias == "BEARISH" and exp.direction.value == "SELL":
            return exp
        if has_trap and trap.setup:
            return trap
        if trap_probability > 60 and rev.setup:
            return rev
        if amd_phase==AMDPhase.DISTRIBUTION:
            if exp.setup and exp.confidence>=max(rev.confidence,trap.confidence)*0.75:
                return exp
        if trap.setup and (not exp.setup and not rev.setup):
            return trap
        if trap.setup and trap.confidence>=max(exp.confidence if exp.setup else 0.0,rev.confidence if rev.setup else 0.0):
            return trap
        if exp.setup and (not rev.setup or exp.confidence>=rev.confidence): return exp
        if rev.setup: return rev
        if trap.setup: return trap
        return ModelResult(ModelType.NO_TRADE,0.0,Direction.NONE,None,[],"No valid setup")

    def _apply_raid_direction_gate(self, model_result, raid_direction: str):
        if not model_result or model_result.setup is None:
            return model_result
        if raid_direction not in ("UP", "DOWN"):
            return model_result
        setup_dir = model_result.setup.direction.value
        if raid_direction == "UP" and setup_dir == "SELL":
            model_result.setup = None
            model_result.blocked_reason = "Raid direction UP"
            model_result.confidence = min(model_result.confidence, 0.35)
        elif raid_direction == "DOWN" and setup_dir == "BUY":
            model_result.setup = None
            model_result.blocked_reason = "Raid direction DOWN"
            model_result.confidence = min(model_result.confidence, 0.35)
        return model_result

    def _apply_direction_alignment(self, model_result, direction: str):
        if model_result is None or model_result.setup is None:
            return model_result
        if direction not in ("UP", "DOWN"):
            return model_result
        setup_dir = model_result.setup.direction.value
        if direction == "UP" and setup_dir == "BUY":
            model_result.confidence = round(min(1.0, model_result.confidence + 0.05), 3)
        elif direction == "DOWN" and setup_dir == "SELL":
            model_result.confidence = round(min(1.0, model_result.confidence + 0.05), 3)
        else:
            model_result.confidence = round(max(0.0, model_result.confidence - 0.08), 3)
        return model_result

    def _inefficiency_direction(self, price: float, ineff) -> str:
        nz = ineff.nearest_inefficiency
        if nz is None:
            return "NONE"
        return "UP" if nz.midpoint > price else "DOWN"

    def _amd_alignment(self, phase: AMDPhase) -> float:
        if phase == AMDPhase.DISTRIBUTION:
            return 1.0
        if phase == AMDPhase.MANIPULATION:
            return 0.75
        if phase == AMDPhase.ACCUMULATION:
            return 0.2
        return 0.5

    def _narrative_alignment(self, narr) -> float:
        if narr.bias == "NEUTRAL":
            return 0.3
        return min(1.0, max(0.0, narr.strength + 0.2))

    def _fundamental_alignment(self, macro_bias: str, narr_bias: str) -> float:
        if narr_bias == "BULLISH" and macro_bias == "BULLISH_GOLD":
            return 1.0
        if narr_bias == "BEARISH" and macro_bias == "BEARISH_GOLD":
            return 1.0
        if macro_bias == "NEUTRAL":
            return 0.5
        return 0.3

    def _has_conflicting_narrative(self, narr) -> bool:
        has_cont = NarrativeEvent.CONTINUATION in narr.events
        has_trap = NarrativeEvent.TRAP in narr.events
        has_sweep = NarrativeEvent.LIQUIDITY_SWEEP in narr.events
        return (has_cont and has_trap) or (has_sweep and has_cont and narr.bias == "NEUTRAL")

    def _map_narrative_pattern(self, narr, session) -> NarrativePattern:
        if NarrativeEvent.TRAP in narr.events:
            return NarrativePattern.LONDON_TRAP
        if NarrativeEvent.LIQUIDITY_SWEEP in narr.events:
            return NarrativePattern.LONDON_SWEEP if session in (SessionType.LONDON, SessionType.LONDON_NY_OVERLAP) else NarrativePattern.NY_REVERSAL
        if NarrativeEvent.DISPLACEMENT in narr.events and NarrativeEvent.BREAK_OF_STRUCTURE in narr.events:
            return NarrativePattern.LONDON_EXPANSION if session in (SessionType.LONDON, SessionType.LONDON_NY_OVERLAP) else NarrativePattern.NY_CONTINUATION
        if NarrativeEvent.CONTINUATION in narr.events:
            return NarrativePattern.NY_CONTINUATION
        return NarrativePattern.UNKNOWN

    def _briefing(self,r,exp,rev,trap,best,atr,narr,hm,buy,sell,price) -> str:
        L=[]
        L.append("━"*48)
        L.append("  J E A F X   M A R K E T   B R I E F I N G")
        L.append("━"*48)
        L.append(f"  {r.timestamp.strftime('%Y-%m-%d  %H:%M UTC')}   {r.pair}")
        L.append("")
        L.append(f"Macro:       {r.macro_bias.value.replace('_',' ')}")
        L.append(f"Session:     {r.session.value.replace('_',' ')}")
        L.append(f"Volatility:  {r.volatility_regime.value}")
        if r.liquidity_regime is not None:
            L.append(f"Liq Regime:  {r.liquidity_regime.regime.value.upper()}")
        L.append(f"ATR:         ${atr:.2f} ({atr/0.1:.0f} pips)")
        if r.macro_narrative is not None:
            L.append(f"Macro Sent:  {r.macro_narrative.sentiment} | Bias: {r.macro_narrative.bias}")
            L.append(f"News Risk:   {r.macro_narrative.news_risk:.0%} | Block: {r.macro_narrative.trade_blocked}")
        if r.asia_session and r.asia_session.high>0:
            a=r.asia_session
            L.append(f"Asia Range:  {a.low:.2f}–{a.high:.2f} ({a.range_pips:.0f}p) [{a.classification}]")
        L.append("")
        L.append("Volatility Engine")
        L.append(f"  Regime: {r.volatility.regime.value}")
        L.append(f"  ATR: {r.volatility.atr:.2f} | Baseline: {r.volatility.atr_baseline:.2f}")
        L.append(f"  ATR Ratio: {r.volatility.atr_ratio:.2f}")
        L.append(f"  Range Ratio: {r.volatility.range_ratio:.2f}")
        L.append(f"  Expansion Probability: {r.volatility.expansion_probability:.0%}")
        L.append("")
        L.append("Market Narrative")
        if narr is not None:
            L.append(f"  Pattern: {r.narrative_pattern.value.replace('_',' ')}")
            evs = ", ".join(e.value for e in narr.events)
            L.append(f"  Events: {evs}")
            L.append(f"  Bias: {narr.bias}")
            L.append(f"  Strength: {narr.strength:.2f}")
            L.append(f"  Sweep={narr.sweep_detected} Displacement={narr.displacement_detected} BOS={narr.bos_detected} Inducement={narr.inducement_detected}")
            L.append(f"  Interpretation: {self._narrative_interpretation(narr)}")
        else:
            L.append("  Narrative not evaluated due to volatility gate")
        L.append("")
        L.append(f"Liquidity Heatmap   [Bias: {r.liquidity_bias.value.replace('_',' ')}]")
        if r.sweep_detected:
            trap_tag=" [TRAP]" if r.liquidity_trap else ""
            L.append(f"  ⚡ Liquidity sweep detected{trap_tag}")
        L.append("  Above Price")
        for z in r.liquidity_zones_above[:4]:
            L.append(f"    {z.price:.2f}  {z.zone_type:<16} Score:{z.score} [{z.strength}]")
        L.append("  Below Price")
        for z in r.liquidity_zones_below[:4]:
            L.append(f"    {z.price:.2f}  {z.zone_type:<16} Score:{z.score} [{z.strength}]")
        if r.nearest_magnet:
            L.append(f"  Nearest Magnet: {r.nearest_magnet.price:.2f} ({r.nearest_magnet.zone_type})")
            L.append(f"  Distance: {r.nearest_magnet_distance_r:.1f}R | Path Clear: {r.liquidity_path_clear}")
        L.append("")
        L.append("Liquidity Raid Prediction")
        rp=r.raid_prediction
        L.append(f"  Target: {rp.target_zone.zone_type if rp.target_zone.zone_type!='NONE' else 'NONE'}")
        L.append(f"  Direction: {rp.raid_direction}")
        L.append(f"  Probability: {rp.probability:.0%}")
        L.append(f"  Distance: {rp.distance_r:.1f}R")
        L.append(f"  Path: {'CLEAR' if rp.path_clear else 'BLOCKED'}")
        L.append(f"  Time Window: {rp.estimated_time_window}")
        L.append("")
        L.append("Inefficiency Map")
        ni = r.inefficiency_map.nearest_inefficiency
        if ni is not None:
            L.append(f"  Nearest: {ni.type} {ni.direction} mid={ni.midpoint:.2f}")
            L.append(f"  Distance: {ni.distance_r:.1f}R | Fill Prob: {ni.probability_of_fill:.0%}")
        else:
            L.append("  Nearest: NONE")
        L.append(f"  Magnet Score: {r.inefficiency_map.magnet_score:.2f}")
        L.append("")
        L.append("Trap Analysis")
        L.append(f"  Probability: {r.trap_analysis.trap_probability:.0f}% ({r.trap_analysis.risk_level})")
        L.append(f"  Type: {r.trap_analysis.trap_type}")
        L.append(f"  Reason: {r.trap_analysis.trap_reason}")
        L.append("")
        if r.displacement is not None:
            L.append("Displacement Engine")
            L.append(f"  Detected: {r.displacement.displacement_detected}")
            L.append(f"  Direction: {r.displacement.direction}")
            L.append(f"  Strength: {r.displacement.strength:.2f} | Impulse: {r.displacement.impulse_size:.2f}")
            L.append("")
        if r.liquidity_magnet is not None:
            L.append("Liquidity Magnet")
            pm = r.liquidity_magnet.primary_magnet
            sm = r.liquidity_magnet.secondary_magnet
            if pm is not None:
                L.append(f"  Primary: {pm.target_price:.2f} ({pm.pool_type}) [{pm.magnet_strength:.2f}]")
            if sm is not None:
                L.append(f"  Secondary: {sm.target_price:.2f} ({sm.pool_type}) [{sm.magnet_strength:.2f}]")
            if pm is None and sm is None:
                L.append("  No active magnet")
            L.append("")
        L.append("Confidence Score")
        L.append(f"  Score: {r.confidence_result.score:.1f}%")
        L.append(f"  Level: {r.confidence_result.confidence_level}")
        L.append(f"  Action: {'ALLOW' if r.confidence_result.allowed_trade else 'NO_TRADE'} ({r.confidence_result.reason})")
        L.append("")
        L.append("AMD Market State")
        L.append(f"  Phase: {r.amd_phase.value} ({r.amd_confidence:.0%})")
        L.append(f"  Accumulation: {r.accumulation_confidence:.0%}")
        L.append(f"  Manipulation: {r.manipulation_confidence:.0%}")
        L.append(f"  Distribution: {r.distribution_confidence:.0%}")
        L.append("")
        L.append("Model Probabilities")
        def _mline(name,m):
            ok="✓" if m.setup else "✗"
            rsn=("" if m.setup else f" — {m.blocked_reason[:35]}")
            return f"  {name:<18} {m.confidence:.0%}  {ok}{rsn}"
        L.append(_mline("Expansion Model:",exp))
        L.append(_mline("Reversal Model: ",rev))
        L.append(_mline("Liquidity Trap: ",trap))
        L.append("")
        L.append(f"Recommended: {best.model_type.value.replace('_',' ')}")
        if best.model_type==ModelType.NO_TRADE:
            L.append(f"  {best.blocked_reason}")
        elif best.setup:
            s=best.setup
            em="▲ BUY" if s.direction==Direction.BUY else "▼ SELL"
            L.append("")
            L.append("Trade Setup")
            L.append(f"  Direction:   {em}")
            L.append(f"  Entry:       {s.entry:.2f}")
            L.append(f"  Stop Loss:   {s.stop_loss:.2f}  ({abs(s.entry-s.stop_loss)/0.1:.0f} pips)")
            L.append(f"  Take Profit: {s.take_profit:.2f}")
            L.append(f"  R:R          1:{s.rr}")
            L.append(f"  Risk:        {s.risk_percent}%")
            L.append("")
            L.append("  Confluences")
            for sig in best.signals[:6]: L.append(f"    • {sig}")
            L.append("")
            L.append(f"  Entry: {s.entry_reason[:55]}")
            L.append(f"  SL:    {s.sl_reason}")
            L.append(f"  TP:    {s.tp_reason}")
            L.append("")
            L.append("  ⏳ Reply /confirm or /reject in Telegram")
        L.append("━"*48)
        return "\n".join(L)

    def _htf_bias(self,candles_h4,candles_d1) -> str:
        bias_h4=self._simple_bias(candles_h4)
        bias_d1=self._simple_bias(candles_d1)
        if bias_h4==bias_d1 and bias_h4 in ("BUY","SELL"):
            return bias_h4
        return "NONE"

    def _simple_bias(self,candles) -> str:
        if not candles or len(candles)<12:
            return "NONE"
        recent=candles[-6:]
        prev=candles[-12:-6]
        rh=max(c.high for c in recent); rl=min(c.low for c in recent)
        ph=max(c.high for c in prev); pl=min(c.low for c in prev)
        if rh>ph and rl>pl:
            return "BUY"
        if rh<ph and rl<pl:
            return "SELL"
        return "NONE"

    def _london_breakout(self,candles,asia_high,asia_low) -> tuple[str,bool]:
        if not candles or len(candles)<6 or not asia_high or not asia_low:
            return "NONE",False
        c=candles[-1]
        prev=candles[-2]
        atr=sum(x.high-x.low for x in candles[-14:])/max(len(candles[-14:]),1)
        displacement=(c.high-c.low)>(atr*1.2) and abs(c.close-c.open)>(atr*0.7)
        if c.close>asia_high and prev.close<=asia_high:
            return "BUY",displacement
        if c.close<asia_low and prev.close>=asia_low:
            return "SELL",displacement
        return "NONE",False

    def _find_fvg(self,candles,direction) -> tuple[float,float]:
        if not candles or len(candles)<5 or direction not in ("BUY","SELL"):
            return 0.0,0.0
        for i in range(len(candles)-3,1,-1):
            c1=candles[i-1]
            c3=candles[i+1]
            if direction=="BUY" and c1.high<c3.low:
                return round(c1.high,2),round(c3.low,2)
            if direction=="SELL" and c1.low>c3.high:
                return round(c3.high,2),round(c1.low,2)
        return 0.0,0.0

    def _narrative_interpretation(self, narr) -> str:
        if narr.bias == "NEUTRAL":
            return "No clear institutional narrative confirmed."
        if NarrativeEvent.LIQUIDITY_SWEEP in narr.events and NarrativeEvent.DISPLACEMENT in narr.events:
            return f"Smart money sweep followed by {narr.bias.lower()} displacement."
        if NarrativeEvent.BREAK_OF_STRUCTURE in narr.events and NarrativeEvent.CONTINUATION in narr.events:
            return f"Structure break with {narr.bias.lower()} continuation context."
        if NarrativeEvent.TRAP in narr.events:
            return f"Trap conditions detected with {narr.bias.lower()} reversal intent."
        return f"Narrative favors {narr.bias.lower()} continuation."
