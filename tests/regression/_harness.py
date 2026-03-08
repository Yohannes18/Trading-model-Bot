from __future__ import annotations

import json
import random
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jeafx_engine as legacy

from jeafx.config import StressLevel
from jeafx.strategy.smc_engine import Candle as RefCandle


ARTIFACT_ROOT = Path("tests/regression/artifacts")
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
LEGACY_ROOT = ARTIFACT_ROOT / "legacy"
REFACTOR_ROOT = ARTIFACT_ROOT / "refactor"
LEGACY_ROOT.mkdir(parents=True, exist_ok=True)
REFACTOR_ROOT.mkdir(parents=True, exist_ok=True)


class FakeDB:
    def __init__(self, today_risk: float = 0.0, open_trades: int = 0) -> None:
        self.today_risk = today_risk
        self.open_trades = open_trades
        self.stress_logs: list[tuple[Any, ...]] = []
        self.governance_logs: list[tuple[Any, ...]] = []

    def get_today_risk(self) -> float:
        return self.today_risk

    def get_open_trade_count(self) -> int:
        return self.open_trades

    def log_stress(self, *args: Any) -> None:
        self.stress_logs.append(args)

    def log_governance(self, *args: Any, **kwargs: Any) -> None:
        self.governance_logs.append(args + (kwargs,))


def write_artifact(name: str, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, default=str)
    (ARTIFACT_ROOT / name).write_text(serialized)
    legacy_payload = payload.get("legacy")
    refactor_payload = payload.get("refactor")
    if legacy_payload is not None and refactor_payload is not None:
        legacy_serialized = json.dumps(legacy_payload, indent=2, default=str)
        refactor_serialized = json.dumps(refactor_payload, indent=2, default=str)
        (LEGACY_ROOT / name).write_text(legacy_serialized)
        (REFACTOR_ROOT / name).write_text(refactor_serialized)


def generate_ohlcv(n: int, seed: int = 7, start: float = 2300.0) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    price = start
    rows: list[dict[str, Any]] = []
    trend = 1
    for i in range(n):
        if i % 25 == 0:
            trend = rng.choice([-1, 1])
        move = trend * rng.uniform(0.1, 1.6) + rng.uniform(-0.8, 0.8)
        open_p = price
        close_p = max(0.0001, open_p + move)
        high_p = max(open_p, close_p) + rng.uniform(0.1, 0.9)
        low_p = min(open_p, close_p) - rng.uniform(0.1, 0.9)
        volume = rng.randint(100, 5000)
        rows.append(
            {
                "time": ts + timedelta(minutes=i * 30),
                "open": round(open_p, 5),
                "high": round(high_p, 5),
                "low": round(low_p, 5),
                "close": round(close_p, 5),
                "volume": volume,
            }
        )
        price = close_p
    return rows


def as_legacy_candles(rows: list[dict[str, Any]]) -> list[Any]:
    return [
        legacy.Candle(
            time=r["time"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
        )
        for r in rows
    ]


def as_ref_candles(rows: list[dict[str, Any]]) -> list[RefCandle]:
    return [
        RefCandle(
            time=r["time"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
        )
        for r in rows
    ]


def normalize_setup(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair": data["pair"],
        "direction": data["direction"],
        "entry": round(float(data["entry"]), 5),
        "sl": round(float(data["sl"]), 5),
        "tp": round(float(data["tp"]), 5),
    }


def stress_level_to_legacy(level: StressLevel):
    return legacy.StressLevel[level.value]
