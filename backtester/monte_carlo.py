from __future__ import annotations

import random
from dataclasses import dataclass

from .walk_forward import run_walk_forward


@dataclass(frozen=True)
class MonteCarloSummary:
    mean_expectancy: float
    worst_drawdown: float
    p05_expectancy: float


def run_monte_carlo(trade_results_r: list[float], runs: int = 200, seed: int = 42) -> MonteCarloSummary:
    if not trade_results_r:
        return MonteCarloSummary(0.0, 0.0, 0.0)

    rng = random.Random(seed)
    expectancies: list[float] = []
    drawdowns: list[float] = []

    for _ in range(max(runs, 1)):
        sample = trade_results_r[:]
        rng.shuffle(sample)
        m = run_walk_forward(sample)
        expectancies.append(m.expectancy)
        drawdowns.append(m.max_drawdown)

    expectancies_sorted = sorted(expectancies)
    p05_idx = max(0, int(0.05 * len(expectancies_sorted)) - 1)

    return MonteCarloSummary(
        mean_expectancy=round(sum(expectancies) / len(expectancies), 4),
        worst_drawdown=round(max(drawdowns), 4),
        p05_expectancy=round(expectancies_sorted[p05_idx], 4),
    )


def run_pipeline_monte_carlo(result_rr: list[float], runs: int = 200, seed: int = 42) -> MonteCarloSummary:
    """
    Convenience wrapper to run Monte Carlo on rr_distribution from PipelineBacktestResult.
    """
    return run_monte_carlo(result_rr, runs=runs, seed=seed)
