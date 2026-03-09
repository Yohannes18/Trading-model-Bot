from __future__ import annotations

from datetime import datetime, timezone


def get_daily_narrative(pair: str = "XAUUSD") -> dict[str, object]:
	now = datetime.now(tz=timezone.utc)
	hour = now.hour

	bias = "NEUTRAL"
	score = 0.85
	summary = "Balanced macro tone"

	if pair.upper() == "XAUUSD":
		if 11 <= hour <= 14:
			bias = "BEARISH"
			score = 0.92
			summary = "US session risk-on pulse weighs on gold"
		elif 0 <= hour <= 4:
			bias = "BULLISH"
			score = 0.90
			summary = "Early session defensiveness supports gold"

	return {
		"pair": pair.upper(),
		"bias": bias,
		"score": max(0.3, min(1.2, float(score))),
		"summary": summary,
		"timestamp": now.isoformat(),
	}
