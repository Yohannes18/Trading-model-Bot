from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Optional


TRADE_HISTORY_FIELDS = [
    "timestamp",
    "symbol",
    "session",
    "amd_phase",
    "volatility_regime",
    "liquidity_regime",
    "model_used",
    "confidence",
    "rr",
    "result_R",
    "win_loss",
    "trap_risk",
    "displacement_strength",
    "liquidity_alignment",
]


@dataclass(frozen=True)
class ModelPerformance:
    win_rate: float
    average_r: float
    expectancy: float
    profit_factor: float
    trades: int


class MetaLearningEngine:
    """Post-trade adaptive model weighting using historical closed-trade outcomes."""

    def __init__(
        self,
        trade_history_path: Path | str = "data/trade_history.csv",
        model_weights_path: Path | str = "config/model_weights.yaml",
        learning_rate: float = 0.02,
        target_expectancy: float = 1.0,
        min_trades_per_model: int = 50,
    ) -> None:
        self.trade_history_path = Path(trade_history_path)
        self.model_weights_path = Path(model_weights_path)
        self.learning_rate = learning_rate
        self.target_expectancy = target_expectancy
        self.min_trades_per_model = min_trades_per_model
        self.learning_bounds = (0.5, 1.5)
        self.state_path = Path("data/meta_update_state.json")
        self.trade_history_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_weights_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_files()

    def log_trade(self, row: dict[str, object]) -> None:
        record = {k: row.get(k, "") for k in TRADE_HISTORY_FIELDS}
        if not self.trade_history_path.exists() or self.trade_history_path.stat().st_size == 0:
            with self.trade_history_path.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=TRADE_HISTORY_FIELDS)
                writer.writeheader()
                writer.writerow(record)
            return
        with self.trade_history_path.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRADE_HISTORY_FIELDS)
            writer.writerow(record)

    def load_trade_history(self) -> list[dict[str, str]]:
        if not self.trade_history_path.exists():
            return []
        with self.trade_history_path.open("r", newline="") as fh:
            reader = csv.DictReader(fh)
            return [dict(r) for r in reader]

    def compute_performance(self) -> dict[tuple[str, str, str, str], ModelPerformance]:
        rows = self.load_trade_history()
        buckets: dict[tuple[str, str, str, str], list[float]] = {}
        for row in rows:
            key = (
                row.get("model_used", "unknown"),
                row.get("volatility_regime", "unknown"),
                row.get("liquidity_regime", "unknown"),
                row.get("session", "unknown"),
            )
            try:
                result_r = float(row.get("result_R", 0.0) or 0.0)
            except ValueError:
                result_r = 0.0
            buckets.setdefault(key, []).append(result_r)

        out: dict[tuple[str, str, str, str], ModelPerformance] = {}
        for key, rs in buckets.items():
            if not rs:
                continue
            wins = [r for r in rs if r > 0]
            losses = [r for r in rs if r < 0]
            win_rate = len(wins) / len(rs)
            average_r = sum(rs) / len(rs)
            expectancy = average_r
            gross_profit = sum(wins)
            gross_loss = abs(sum(losses))
            pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
            out[key] = ModelPerformance(
                win_rate=round(win_rate, 4),
                average_r=round(average_r, 4),
                expectancy=round(expectancy, 4),
                profit_factor=round(pf, 4) if pf != float("inf") else pf,
                trades=len(rs),
            )
        return out

    def update_model_weights(self) -> dict[str, float]:
        if self._drawdown_last_n_trades(30) > 15.0:
            return self.load_model_weights()

        perf = self.compute_performance()
        weights = self.load_model_weights()

        trades_by_model: dict[str, int] = {}
        expectancy_by_model: dict[str, list[float]] = {}
        for (model, _vol, _liq, _session), stats in perf.items():
            trades_by_model[model] = trades_by_model.get(model, 0) + stats.trades
            expectancy_by_model.setdefault(model, []).append(stats.expectancy)

        for model, old_weight in list(weights.items()):
            model_trades = trades_by_model.get(model, 0)
            if model_trades < self.min_trades_per_model:
                continue
            avg_expectancy = sum(expectancy_by_model.get(model, [0.0])) / max(len(expectancy_by_model.get(model, [])), 1)
            score = avg_expectancy / max(self.target_expectancy, 1e-9)
            score = max(-1.0, min(1.0, score))
            new_weight = old_weight * (1.0 + self.learning_rate * score)
            weights[model] = round(max(self.learning_bounds[0], min(self.learning_bounds[1], new_weight)), 4)

        self.save_model_weights(weights)
        return weights

    def load_weights(self) -> dict[str, float]:
        internal = self.load_model_weights()
        return {
            "reversal_model": internal.get("REVERSAL", 1.0),
            "continuation_model": internal.get("EXPANSION", 1.0),
            "raid_model": internal.get("LIQUIDITY_TRAP", 1.0),
        }

    def samples_per_model(self) -> dict[str, int]:
        rows = self.load_trade_history()
        counters = {
            "reversal_model": 0,
            "continuation_model": 0,
            "raid_model": 0,
        }
        aliases = {
            "REVERSAL": "reversal_model",
            "EXPANSION": "continuation_model",
            "LIQUIDITY_TRAP": "raid_model",
        }
        for row in rows:
            model = self._canonical_model_key(str(row.get("model_used", "")))
            alias = aliases.get(model)
            if alias:
                counters[alias] += 1
        return counters

    def meta_state(self) -> str:
        samples = self.samples_per_model()
        return "active" if all(v >= self.min_trades_per_model for v in samples.values()) else "warming_up"

    def last_update_time(self) -> str:
        if not self.state_path.exists():
            return ""
        try:
            data = json.loads(self.state_path.read_text())
            ts = data.get("last_update_at")
            if isinstance(ts, str):
                return ts
            day = data.get("last_update_day")
            if isinstance(day, str) and day:
                return f"{day}T00:00:00Z"
        except Exception:
            return ""
        return ""

    def status(self) -> dict[str, object]:
        dd30 = self._drawdown_last_n_trades(30)
        return {
            "meta_learning": True,
            "last_update": self.last_update_time(),
            "model_weights": self.load_weights(),
            "learning_bounds": [self.learning_bounds[0], self.learning_bounds[1]],
            "min_samples_required": self.min_trades_per_model,
            "samples_per_model": self.samples_per_model(),
            "meta_state": self.meta_state(),
            "update_frozen": dd30 > 15.0,
            "drawdown_last_30_trades_r": round(dd30, 4),
        }

    def load_model_weights(self) -> dict[str, float]:
        defaults = {
            "EXPANSION": 1.0,
            "REVERSAL": 1.0,
            "LIQUIDITY_TRAP": 1.0,
        }
        if not self.model_weights_path.exists():
            return defaults

        parsed = defaults.copy()
        for line in self.model_weights_path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or ":" not in s:
                continue
            key, val = s.split(":", 1)
            key = self._canonical_model_key(key.strip())
            try:
                parsed[key] = float(val.strip())
            except ValueError:
                continue
        return parsed

    def save_model_weights(self, weights: dict[str, float]) -> None:
        aliases = {
            "EXPANSION": "continuation_model",
            "REVERSAL": "reversal_model",
            "LIQUIDITY_TRAP": "raid_model",
        }
        lines = [f"{aliases.get(k, k.lower())}: {v}" for k, v in sorted(weights.items())]
        self.model_weights_path.write_text("\n".join(lines) + "\n")

    def _ensure_files(self) -> None:
        if not self.trade_history_path.exists():
            with self.trade_history_path.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=TRADE_HISTORY_FIELDS)
                writer.writeheader()
        if not self.model_weights_path.exists():
            self.save_model_weights(
                {
                    "EXPANSION": 1.0,
                    "REVERSAL": 1.0,
                    "LIQUIDITY_TRAP": 1.0,
                }
            )

    def _canonical_model_key(self, key: str) -> str:
        k = key.strip().upper()
        alias = {
            "REVERSAL_MODEL": "REVERSAL",
            "CONTINUATION_MODEL": "EXPANSION",
            "RAID_MODEL": "LIQUIDITY_TRAP",
            "LIQUIDITY_TRAP_MODEL": "LIQUIDITY_TRAP",
        }
        return alias.get(k, k)

    def _drawdown_last_n_trades(self, n: int) -> float:
        rows = self.load_trade_history()
        if not rows:
            return 0.0
        tail = rows[-n:]
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for row in tail:
            try:
                r = float(row.get("result_R", 0.0) or 0.0)
            except ValueError:
                r = 0.0
            equity += r
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        return max_dd


def make_trade_history_row(
    symbol: str,
    session: str,
    amd_phase: str,
    volatility_regime: str,
    liquidity_regime: str,
    model_used: str,
    confidence: float,
    rr: float,
    result_r: float,
    trap_risk: float,
    displacement_strength: float,
    liquidity_alignment: float,
    timestamp: Optional[datetime] = None,
) -> dict[str, object]:
    ts = timestamp or datetime.now(tz=timezone.utc)
    return {
        "timestamp": ts.isoformat(),
        "symbol": symbol,
        "session": session,
        "amd_phase": amd_phase,
        "volatility_regime": volatility_regime,
        "liquidity_regime": liquidity_regime,
        "model_used": model_used,
        "confidence": round(confidence, 2),
        "rr": round(rr, 4),
        "result_R": round(result_r, 4),
        "win_loss": "win" if result_r > 0 else "loss",
        "trap_risk": round(trap_risk, 4),
        "displacement_strength": round(displacement_strength, 4),
        "liquidity_alignment": round(liquidity_alignment, 4),
    }
