from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class WalkForwardMetrics:
    win_rate: float
    expectancy: float
    max_drawdown: float
    profit_factor: float


def run_walk_forward(trade_results_r: Iterable[float]) -> WalkForwardMetrics:
    results = list(trade_results_r)
    if not results:
        return WalkForwardMetrics(0.0, 0.0, 0.0, 0.0)

    wins = [r for r in results if r > 0]
    losses = [r for r in results if r < 0]
    win_rate = len(wins) / len(results)
    expectancy = sum(results) / len(results)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    eq = 0.0
    peak = 0.0
    dd = 0.0
    for r in results:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)

    return WalkForwardMetrics(
        win_rate=round(win_rate, 4),
        expectancy=round(expectancy, 4),
        max_drawdown=round(abs(dd), 4),
        profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else profit_factor,
    )
