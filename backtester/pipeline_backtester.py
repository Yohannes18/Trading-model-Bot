from __future__ import annotations

import random
from dataclasses import dataclass
import statistics

from quantara.strategy.analysis_engine import AnalysisEngine
from engine.meta_learning_engine import MetaLearningEngine, make_trade_history_row
from .parameter_optimizer import OptimizationResult, optimize_parameters


@dataclass(frozen=True)
class PipelineBacktestResult:
    trades: int
    win_rate: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    rr_distribution: list[float]
    equity_curve: list[float]
    drawdown_distribution: list[float]
    risk_of_ruin: float


class PipelineBacktester:
    def __init__(self, analysis_engine: AnalysisEngine | None = None) -> None:
        self._analysis = analysis_engine or AnalysisEngine()

    def run(
        self,
        candles_m30,
        candles_h1,
        candles_h4,
        candles_d1,
        pair: str = "XAUUSD",
        warmup: int = 80,
        enable_meta_learning: bool = False,
        ) -> PipelineBacktestResult:
        if not candles_m30 or len(candles_m30) <= warmup + 5:
            return PipelineBacktestResult(0, 0.0, 0.0, 0.0, 0.0, 0.0, [], [0.0], [], 0.0)

        trades_r: list[float] = []
        equity_curve: list[float] = [0.0]
        meta = MetaLearningEngine() if enable_meta_learning else None

        for idx in range(warmup, len(candles_m30) - 1):
            window_m30 = candles_m30[: idx + 1]
            window_h1 = [c for c in candles_h1 if c.time <= window_m30[-1].time] if candles_h1 else []
            window_h4 = [c for c in candles_h4 if c.time <= window_m30[-1].time] if candles_h4 else []
            window_d1 = [c for c in candles_d1 if c.time <= window_m30[-1].time] if candles_d1 else []

            analysis = self._analysis.analyze_market(window_m30, window_h1, window_h4, window_d1, pair, timeframe="M30")
            setup = analysis.model_result.setup if analysis.model_result and analysis.model_result.setup else None
            if not analysis.has_trade_setup or setup is None:
                continue

            outcome_r = self._simulate_trade(setup.direction.value, setup.entry, setup.stop_loss, setup.take_profit, candles_m30[idx + 1 : idx + 16])
            if outcome_r is None:
                continue
            trades_r.append(outcome_r)
            equity_curve.append(equity_curve[-1] + outcome_r)

            if meta is not None:
                row = make_trade_history_row(
                    symbol=pair,
                    session=analysis.session.value,
                    amd_phase=analysis.amd_phase.value,
                    volatility_regime=analysis.volatility_regime.value,
                    liquidity_regime=analysis.liquidity_regime.regime.value if analysis.liquidity_regime else "unknown",
                    model_used=analysis.recommended_model.value,
                    confidence=analysis.confidence_result.score,
                    rr=setup.rr,
                    result_r=outcome_r,
                    trap_risk=min(1.0, analysis.trap_analysis.trap_probability / 100.0),
                    displacement_strength=analysis.displacement.strength if analysis.displacement else 0.0,
                    liquidity_alignment=analysis.liquidity_magnet.primary_magnet.magnet_strength if analysis.liquidity_magnet and analysis.liquidity_magnet.primary_magnet else 0.0,
                    timestamp=window_m30[-1].time,
                )
                meta.log_trade(row)
                if len(trades_r) % 25 == 0:
                    meta.update_model_weights()

        return self._metrics(trades_r, equity_curve)

    def optimize_parameters(
        self,
        candles_m30,
        candles_h1,
        candles_h4,
        candles_d1,
        pair: str,
        param_grid: dict[str, list[float]],
        warmup: int = 80,
    ) -> OptimizationResult:
        """
        Run grid-search parameter optimization on the hybrid pipeline.

        The param_grid keys must correspond to numeric entries in AnalysisEngine._params.
        """

        def _evaluator(params: dict[str, float]) -> list[float]:
            engine = AnalysisEngine()
            engine._params.update(params)
            bt = PipelineBacktester(engine)
            result = bt.run(candles_m30, candles_h1, candles_h4, candles_d1, pair=pair, warmup=warmup)
            return result.rr_distribution

        return optimize_parameters(_evaluator, param_grid)

    def _simulate_trade(self, direction: str, entry: float, sl: float, tp: float, future_candles):
        if not future_candles:
            return None
        rr = abs(tp - entry) / max(abs(entry - sl), 1e-9)
        for candle in future_candles:
            if direction == "BUY":
                if candle.low <= sl:
                    return -1.0
                if candle.high >= tp:
                    return round(rr, 2)
            else:
                if candle.high >= sl:
                    return -1.0
                if candle.low <= tp:
                    return round(rr, 2)
        return 0.0

    def _metrics(self, results_r: list[float], equity_curve: list[float]) -> PipelineBacktestResult:
        if not results_r:
            return PipelineBacktestResult(0, 0.0, 0.0, 0.0, 0.0, 0.0, [], equity_curve, [], 0.0)

        wins = [r for r in results_r if r > 0]
        losses = [r for r in results_r if r < 0]
        win_rate = len(wins) / len(results_r)
        expectancy = sum(results_r) / len(results_r)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
        mean_r = expectancy
        std_r = statistics.pstdev(results_r) if len(results_r) > 1 else 0.0
        sharpe_ratio = (mean_r / std_r) if std_r > 0 else 0.0

        max_drawdown = 0.0
        peak = equity_curve[0]
        for eq in equity_curve:
            peak = max(peak, eq)
            max_drawdown = max(max_drawdown, peak - eq)

        drawdown_distribution, risk_of_ruin = self._monte_carlo(results_r, runs=1000)

        return PipelineBacktestResult(
            trades=len(results_r),
            win_rate=round(win_rate, 4),
            expectancy=round(expectancy, 4),
            profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else profit_factor,
            max_drawdown=round(max_drawdown, 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            rr_distribution=[round(x, 2) for x in results_r],
            equity_curve=[round(x, 4) for x in equity_curve],
            drawdown_distribution=[round(x, 4) for x in drawdown_distribution],
            risk_of_ruin=round(risk_of_ruin, 4),
        )

    def _monte_carlo(self, results_r: list[float], runs: int = 1000) -> tuple[list[float], float]:
        if not results_r:
            return [], 0.0

        rng = random.Random(42)
        drawdowns: list[float] = []
        ruin_count = 0
        ruin_threshold = -10.0

        for _ in range(max(runs, 1)):
            sample = results_r[:]
            rng.shuffle(sample)
            eq = 0.0
            peak = 0.0
            max_dd = 0.0
            for r in sample:
                eq += r
                peak = max(peak, eq)
                max_dd = max(max_dd, peak - eq)
            drawdowns.append(max_dd)
            if eq <= ruin_threshold:
                ruin_count += 1

        return drawdowns, ruin_count / max(runs, 1)
