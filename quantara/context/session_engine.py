from __future__ import annotations

from datetime import datetime, timezone


def get_session_context(now: datetime | None = None) -> dict[str, object]:
	ts = now or datetime.now(tz=timezone.utc)
	hour = ts.hour

	if 7 <= hour < 10:
		return {"session": "LONDON_OPEN", "weight": 1.08, "risk_mode": "NORMAL"}
	if 12 <= hour < 16:
		return {"session": "NEW_YORK", "weight": 1.0, "risk_mode": "NORMAL"}
	if 10 <= hour < 12:
		return {"session": "LONDON_NY_OVERLAP", "weight": 1.05, "risk_mode": "NORMAL"}
	if 22 <= hour or hour < 6:
		return {"session": "ASIA", "weight": 0.82, "risk_mode": "LOW_RISK"}
	return {"session": "TRANSITION", "weight": 0.9, "risk_mode": "LOW_RISK"}
