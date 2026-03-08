from __future__ import annotations

import inspect
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from engine.confidence_engine import TradeConfidenceEngine
from engine.inefficiency_engine import MarketInefficiencyEngine
from engine.trap_detector import LiquidityTrapDetector
from jeafx.strategy.analysis_engine import AnalysisEngine
from jeafx.strategy.smc_engine import Candle
from jeafx.strategy.types import AMDPhase, Direction, ModelResult, ModelType, NarrativeAnalysis, NarrativeEvent, TradeSetupProposal, VolatilityRegime


def _candles(n: int, base: float = 2300.0) -> list[Candle]:
    out: list[Candle] = []
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p = base
    for i in range(n):
        o = p
        c = p + (0.4 if i % 2 == 0 else -0.2)
        h = max(o, c) + 0.6
        l = min(o, c) - 0.6
        out.append(Candle(time=t0 + timedelta(minutes=30 * i), open=o, high=h, low=l, close=c, volume=1000 + i * 5))
        p = c
    return out


def test_inefficiency_engine_detects_zones() -> None:
    candles = _candles(80)
    candles[-3] = Candle(candles[-3].time, 2300.0, 2301.0, 2299.5, 2300.8, 1500)
    candles[-2] = Candle(candles[-2].time, 2301.2, 2303.0, 2301.1, 2302.8, 2200)
    candles[-1] = Candle(candles[-1].time, 2302.9, 2304.0, 2302.2, 2303.7, 1800)

    ime = MarketInefficiencyEngine()
    m = ime.build_map(candles, current_price=2302.5, risk_unit=1.0)
    assert m.nearest_inefficiency is not None
    assert len(m.zones_above) + len(m.zones_below) > 0


def test_trap_detector_scores_high_for_sweep_rejection() -> None:
    candles = _candles(30)
    candles[-3] = Candle(candles[-3].time, 2300.0, 2307.6, 2299.5, 2306.9, 3400)
    candles[-2] = Candle(candles[-2].time, 2306.9, 2307.4, 2303.4, 2304.0, 3200)
    candles[-1] = Candle(candles[-1].time, 2304.0, 2306.8, 2303.6, 2303.9, 3600)

    det = LiquidityTrapDetector()
    trap = det.analyze(candles, sweep_detected=True, displacement_detected=True, nearest_liquidity_score=8)
    assert trap.trap_probability >= 40


def test_trade_confidence_thresholds() -> None:
    eng = TradeConfidenceEngine()
    low = eng.evaluate(0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.8, 0.2)
    high = eng.evaluate(1.0, 1.0, 0.9, 0.9, 1.0, 0.8, 0.1, 0.8)
    assert low.allowed_trade is False
    assert high.allowed_trade is True
    assert high.score >= 70


def test_trap_requires_sweep() -> None:
    candles = _candles(35)
    candles[-3] = Candle(candles[-3].time, 2303.0, 2308.0, 2302.5, 2307.5, 3500)
    candles[-2] = Candle(candles[-2].time, 2307.4, 2308.3, 2303.0, 2303.4, 3600)
    candles[-1] = Candle(candles[-1].time, 2303.3, 2303.9, 2302.7, 2302.9, 3200)

    det = LiquidityTrapDetector()
    trap = det.analyze(candles, sweep_detected=False, displacement_detected=True, nearest_liquidity_score=9)
    assert trap.trap_probability == 0.0
    assert trap.trap_type == "NONE"


def test_ime_micro_gap_is_filtered() -> None:
    candles = _candles(90)
    candles[-3] = Candle(candles[-3].time, 2300.0, 2301.0, 2299.5, 2300.9, 1200)
    candles[-2] = Candle(candles[-2].time, 2300.9, 2301.1, 2300.8, 2300.95, 1150)
    candles[-1] = Candle(candles[-1].time, 2301.02, 2301.2, 2301.01, 2301.15, 1180)

    ime = MarketInefficiencyEngine()
    m = ime.build_map(candles, current_price=2300.8, risk_unit=1.0, session="LONDON")
    all_fvg = [z for z in (m.zones_above + m.zones_below) if z.type == "FVG"]
    assert all(abs(z.top - z.bottom) >= 0.15 for z in all_fvg)


def test_pipeline_order_markers() -> None:
    src = inspect.getsource(AnalysisEngine.analyze_market)
    stages = [
        "# 2. Session",
        "# 4. AMD phase detection",
        "# 5. Volatility expansion",
        "# 6. Liquidity Regime",
        "# 7. Narrative engine",
        "# 8. Liquidity heatmap",
        "# 9. Liquidity Map",
        "# 10. Liquidity raid predictor",
        "# 11. Inefficiency engine (IME)",
        "# 12. Trap detector",
        "# 13. Macro Narrative engine",
        "# 14. Displacement engine",
        "# 15. Liquidity magnet engine",
        "# 16. Confidence factors preparation",
        "# 17. Model selector",
    ]
    positions = [src.index(stage) for stage in stages]
    assert positions == sorted(positions)


def test_competitive_selector_picks_highest_valid_model() -> None:
    engine = AnalysisEngine()
    engine._params.update(
        {
            "model_confidence_threshold": 60.0,
            "model_rr_min": 3.0,
            "model_ambiguity_delta": 5.0,
            "max_xau_sl_pips": 150.0,
        }
    )

    def _setup(direction: Direction, rr: float) -> TradeSetupProposal:
        return TradeSetupProposal(
            direction=direction,
            entry=2300.0,
            stop_loss=2298.5 if direction == Direction.BUY else 2301.5,
            take_profit=2306.0 if direction == Direction.BUY else 2294.0,
            rr=rr,
            risk_percent=1.0,
            position_size=0.1,
        )

    exp = ModelResult(ModelType.EXPANSION, 0.78, Direction.BUY, _setup(Direction.BUY, 3.5), ["Continuation"]) 
    rev = ModelResult(ModelType.REVERSAL, 0.65, Direction.SELL, _setup(Direction.SELL, 3.2), ["Sweep", "Trap"]) 
    trap = ModelResult(ModelType.LIQUIDITY_TRAP, 0.82, Direction.SELL, _setup(Direction.SELL, 2.2), ["Raid"]) 

    narr = NarrativeAnalysis(
        events=[NarrativeEvent.DISPLACEMENT, NarrativeEvent.BREAK_OF_STRUCTURE, NarrativeEvent.CONTINUATION],
        bias="BULLISH",
        strength=0.8,
        sweep_detected=False,
        displacement_detected=True,
        bos_detected=True,
        inducement_detected=False,
    )
    raid = SimpleNamespace(raid_direction="UP", probability=0.82)
    volx = SimpleNamespace(regime=VolatilityRegime.EXPANSION)
    trap_analysis = SimpleNamespace(trap_probability=25.0)
    ineff = SimpleNamespace(nearest_inefficiency=SimpleNamespace(midpoint=2308.0), magnet_score=0.75)
    liq_map = SimpleNamespace(
        nearest_above=SimpleNamespace(price=2307.0, strength=0.8),
        nearest_below=SimpleNamespace(price=2295.0, strength=0.45),
    )

    best = engine._select_competitive_model(
        exp=exp,
        rev=rev,
        trap=trap,
        amd_phase=AMDPhase.DISTRIBUTION,
        narr=narr,
        raid=raid,
        volx=volx,
        macro_bias="BULLISH_GOLD",
        trap_analysis=trap_analysis,
        ineff=ineff,
        liq_map=liq_map,
        current_price=2300.0,
        atr=2.0,
        pair="XAUUSD",
    )

    assert best.model_type == ModelType.EXPANSION
    assert best.setup is not None


def test_competitive_selector_ambiguity_returns_no_trade() -> None:
    engine = AnalysisEngine()
    engine._params.update(
        {
            "model_confidence_threshold": 60.0,
            "model_rr_min": 3.0,
            "model_ambiguity_delta": 20.0,
            "max_xau_sl_pips": 150.0,
        }
    )

    setup_buy = TradeSetupProposal(Direction.BUY, 2300.0, 2298.5, 2306.0, 3.2, 1.0, 0.1)
    setup_sell = TradeSetupProposal(Direction.SELL, 2300.0, 2301.5, 2294.0, 3.2, 1.0, 0.1)

    exp = ModelResult(ModelType.EXPANSION, 0.74, Direction.BUY, setup_buy, ["Continuation"])
    rev = ModelResult(ModelType.REVERSAL, 0.72, Direction.SELL, setup_sell, ["Sweep", "Trap"])
    trap = ModelResult(ModelType.LIQUIDITY_TRAP, 0.20, Direction.NONE, None, [])

    def _fake_competitive_confidence(**kwargs):
        model = kwargs["model_result"]
        mapping = {
            ModelType.EXPANSION: 74.0,
            ModelType.REVERSAL: 69.0,
            ModelType.LIQUIDITY_TRAP: 20.0,
        }
        return mapping[model.model_type]

    engine._model_competitive_confidence = _fake_competitive_confidence

    narr = NarrativeAnalysis(
        events=[NarrativeEvent.LIQUIDITY_SWEEP, NarrativeEvent.DISPLACEMENT],
        bias="NEUTRAL",
        strength=0.7,
        sweep_detected=True,
        displacement_detected=True,
        bos_detected=False,
        inducement_detected=False,
    )
    raid = SimpleNamespace(raid_direction="NONE", probability=0.55)
    volx = SimpleNamespace(regime=VolatilityRegime.NORMAL)
    trap_analysis = SimpleNamespace(trap_probability=40.0)
    ineff = SimpleNamespace(nearest_inefficiency=SimpleNamespace(midpoint=2302.0), magnet_score=0.55)
    liq_map = SimpleNamespace(
        nearest_above=SimpleNamespace(price=2304.0, strength=0.65),
        nearest_below=SimpleNamespace(price=2296.0, strength=0.65),
    )

    best = engine._select_competitive_model(
        exp=exp,
        rev=rev,
        trap=trap,
        amd_phase=AMDPhase.MANIPULATION,
        narr=narr,
        raid=raid,
        volx=volx,
        macro_bias="NEUTRAL",
        trap_analysis=trap_analysis,
        ineff=ineff,
        liq_map=liq_map,
        current_price=2300.0,
        atr=2.0,
        pair="XAUUSD",
    )

    assert best.model_type == ModelType.NO_TRADE
    assert "model_ambiguity" in best.blocked_reason
