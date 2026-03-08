from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable

from .walk_forward import run_walk_forward


@dataclass(frozen=True)
class OptimizationResult:
    best_params: dict[str, float]
    best_expectancy: float
    best_win_rate: float
    best_profit_factor: float


def optimize_parameters(
    evaluator: Callable[[dict[str, float]], list[float]],
    param_grid: dict[str, list[float]],
) -> OptimizationResult:
    if not param_grid:
        return OptimizationResult({}, 0.0, 0.0, 0.0)

    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]

    best_params: dict[str, float] = {}
    best_metric = float("-inf")
    best_wr = 0.0
    best_pf = 0.0

    for combo in product(*values):
        params = {k: float(v) for k, v in zip(keys, combo)}
        results = evaluator(params)
        metrics = run_walk_forward(results)
        metric = metrics.expectancy
        if metric > best_metric:
            best_metric = metric
            best_params = params
            best_wr = metrics.win_rate
            best_pf = metrics.profit_factor if metrics.profit_factor != float("inf") else 999.0

    return OptimizationResult(best_params, round(best_metric, 4), round(best_wr, 4), round(best_pf, 4))
