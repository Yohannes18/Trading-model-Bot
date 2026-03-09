from __future__ import annotations


def detect_volatility_regime(candles) -> dict[str, object]:
	if not candles or len(candles) < 30:
		return {"regime": "NORMAL", "weight": 0.92, "ratio": 1.0}

	recent = candles[-20:]
	baseline = candles[-80:-20] if len(candles) >= 80 else candles[:-20]
	if not baseline:
		baseline = recent

	recent_mean = sum(max(0.0, c.high - c.low) for c in recent) / max(1, len(recent))
	base_mean = sum(max(0.0, c.high - c.low) for c in baseline) / max(1, len(baseline))
	ratio = recent_mean / max(base_mean, 1e-9)

	if ratio >= 1.25:
		return {"regime": "EXPANSION", "weight": 1.08, "ratio": ratio}
	if ratio <= 0.85:
		return {"regime": "COMPRESSION", "weight": 0.78, "ratio": ratio}
	return {"regime": "NORMAL", "weight": 0.95, "ratio": ratio}
