from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine.meta_learning_engine import MetaLearningEngine


_STATE_PATH = Path("data/meta_update_state.json")


def run_daily_meta_update() -> bool:
    """Runs meta model-weight update once per UTC day. Returns True when update executed."""
    today = datetime.now(tz=timezone.utc).date().isoformat()
    last_day = _read_last_day()
    if last_day == today:
        return False

    engine = MetaLearningEngine()
    engine.update_model_weights()
    _write_last_day(today)
    return True


def _read_last_day() -> str:
    if not _STATE_PATH.exists():
        return ""
    try:
        data = json.loads(_STATE_PATH.read_text())
        return str(data.get("last_update_day", ""))
    except Exception:
        return ""


def _write_last_day(day: str) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(
            {
                "last_update_day": day,
                "last_update_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            },
            indent=2,
        )
    )
