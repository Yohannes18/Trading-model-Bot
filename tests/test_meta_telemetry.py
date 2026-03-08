from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine.meta_learning_engine import MetaLearningEngine, make_trade_history_row


def test_meta_status_has_required_fields(tmp_path: Path) -> None:
    history = tmp_path / "trade_history.csv"
    weights = tmp_path / "model_weights.yaml"
    state = tmp_path / "meta_update_state.json"

    engine = MetaLearningEngine(trade_history_path=history, model_weights_path=weights, min_trades_per_model=50)
    engine.state_path = state
    state.write_text(json.dumps({"last_update_day": "2026-03-06", "last_update_at": "2026-03-06T00:00:00Z"}))

    row = make_trade_history_row(
        symbol="XAUUSD",
        session="LONDON",
        amd_phase="MANIPULATION",
        volatility_regime="EXPANSION",
        liquidity_regime="expansion",
        model_used="REVERSAL",
        confidence=78,
        rr=3.4,
        result_r=1.0,
        trap_risk=0.2,
        displacement_strength=0.7,
        liquidity_alignment=0.8,
        timestamp=datetime.now(tz=timezone.utc),
    )
    engine.log_trade(row)

    status = engine.status()
    assert status["meta_learning"] is True
    assert "last_update" in status
    assert "model_weights" in status
    assert "samples_per_model" in status
    assert status["meta_state"] in ("warming_up", "active")


def test_meta_update_freezes_on_large_drawdown(tmp_path: Path) -> None:
    history = tmp_path / "trade_history.csv"
    weights = tmp_path / "model_weights.yaml"
    engine = MetaLearningEngine(trade_history_path=history, model_weights_path=weights, min_trades_per_model=5)

    for i in range(35):
        row = make_trade_history_row(
            symbol="XAUUSD",
            session="LONDON",
            amd_phase="MANIPULATION",
            volatility_regime="EXPANSION",
            liquidity_regime="expansion",
            model_used="REVERSAL",
            confidence=70,
            rr=3.0,
            result_r=-1.0 if i < 25 else 0.2,
            trap_risk=0.2,
            displacement_strength=0.5,
            liquidity_alignment=0.6,
            timestamp=datetime.now(tz=timezone.utc),
        )
        engine.log_trade(row)

    before = engine.load_model_weights()
    after = engine.update_model_weights()
    assert before == after
