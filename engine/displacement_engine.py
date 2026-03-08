from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class DisplacementResult:
    displacement_detected: bool
    direction: str
    strength: float
    impulse_size: float


class DisplacementEngine:
    """Detects institutional displacement using body expansion, volume surge and structure break."""

    def analyze(self, candles: List, atr: float, break_of_structure: bool, volume_multiplier: float = 1.5) -> DisplacementResult:
        if not candles or len(candles) < 20:
            return DisplacementResult(False, "NONE", 0.0, 0.0)

        last = candles[-1]
        body = abs(last.close - last.open)
        atr_value = max(float(atr), 1e-9)

        recent_vol = [float(c.volume or 0.0) for c in candles[-21:-1]]
        avg_volume = sum(recent_vol) / max(len(recent_vol), 1)
        vol_ratio = (float(last.volume or 0.0) / max(avg_volume, 1e-9)) if avg_volume > 0 else 0.0

        body_ratio = body / atr_value
        structure_break_weight = 1.0 if break_of_structure else 0.5

        displacement_detected = body_ratio > 2.5 and vol_ratio > volume_multiplier and break_of_structure
        raw_strength = body_ratio * vol_ratio * structure_break_weight
        strength = max(0.0, min(1.0, raw_strength / 10.0))
        impulse_size = body_ratio

        direction = "NONE"
        if displacement_detected:
            direction = "UP" if last.close > last.open else "DOWN"

        return DisplacementResult(
            displacement_detected=displacement_detected,
            direction=direction,
            strength=round(strength, 4),
            impulse_size=round(impulse_size, 4),
        )
