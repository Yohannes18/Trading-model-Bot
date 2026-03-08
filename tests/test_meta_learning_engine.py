from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from engine.meta_learning_engine import MetaLearningEngine, make_trade_history_row
from scheduler.meta_update import run_daily_meta_update


def test_meta_learning_updates_weights_with_minimum_trades(tmp_path: Path) -> None:
    history = tmp_path / "trade_history.csv"
    weights = tmp_path / "model_weights.yaml"
    engine = MetaLearningEngine(
        trade_history_path=history,
        model_weights_path=weights,
        min_trades_per_model=50,
        learning_rate=0.05,
        target_expectancy=1.0,
    )

    for i in range(60):
        row = make_trade_history_row(
            symbol="XAUUSD",
            session="LONDON",
            amd_phase="MANIPULATION",
            volatility_regime="EXPANSION",
            liquidity_regime="expansion",
            model_used="REVERSAL",
            confidence=75,
            rr=3.5,
            result_r=1.2 if i % 3 else -1.0,
            trap_risk=0.2,
            displacement_strength=0.7,
            liquidity_alignment=0.8,
            timestamp=datetime.now(tz=timezone.utc),
        )
        engine.log_trade(row)

    before = engine.load_model_weights()["REVERSAL"]
    updated = engine.update_model_weights()
    after = updated["REVERSAL"]
    assert 0.5 <= after <= 1.5
    assert after != before


def test_meta_scheduler_runs_once_per_day(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "meta_update_state.json"
    monkeypatch.setattr("scheduler.meta_update._STATE_PATH", state)

    run1 = run_daily_meta_update()
    run2 = run_daily_meta_update()
    assert run1 is True
    assert run2 is False
