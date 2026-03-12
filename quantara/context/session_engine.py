from __future__ import annotations

from datetime import datetime, timezone

SESSION_PROFILES = {
	"ASIA": {"risk_multiplier": 0.35, "allowed_models": ["mean_reversion", "range_liquidity", "continuation"], "volatility": "medium"},
	"LONDON": {"risk_multiplier": 1.0, "allowed_models": ["smc", "liquidity_sweep"], "volatility": "high"},
	"NEWYORK": {"risk_multiplier": 0.8, "allowed_models": ["smc", "continuation"], "volatility": "medium"},
}


def get_session_context(now: datetime | None = None) -> dict[str, object]:
	ts = now or datetime.now(tz=timezone.utc)
	hour = ts.hour

	if 7 <= hour < 12:
		session = "LONDON"
	elif 12 <= hour < 17:
		session = "NEWYORK"
	else:
		session = "ASIA"

	profile = SESSION_PROFILES[session]
	return {
		"session": session,
		"risk_multiplier": float(profile["risk_multiplier"]),
		"allowed_models": list(profile["allowed_models"]),
		"volatility": str(profile["volatility"]),
		"weight": float(profile["risk_multiplier"]),
		"risk_mode": "NORMAL" if session in ("LONDON", "NEWYORK") else "LOW_RISK",
	}



