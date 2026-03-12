from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Impact, log


@dataclass(frozen=True)
class RiskAdjustment:
    allowed: bool
    multiplier: float
    reason: str
    components: dict[str, float]


class DynamicRiskEngine:
    _REGIME_MULTIPLIERS: dict[str, float] = {
        "trend": 1.0,
        "range": 0.85,
        "expansion": 0.9,
        "compression": 0.75,
    }

    _VOLATILITY_MULTIPLIERS: dict[str, float] = {
        "EXPANSION": 0.95,
        "NORMAL": 1.0,
        "COMPRESSION": 0.8,
    }

    def evaluate(
        self,
        *,
        session_multiplier: float,
        regime_name: str,
        volatility_regime: str,
        imminent_events: list[Any],
    ) -> RiskAdjustment:
        high_impact_count = self._high_impact_count(imminent_events)
        if high_impact_count > 0:
            log.info("risk_gate_high_impact_news events=%s", high_impact_count)
            return RiskAdjustment(
                allowed=False,
                multiplier=0.0,
                reason=f"high_impact_news:{high_impact_count}",
                components={
                    "session": max(0.0, float(session_multiplier)),
                    "regime": self._REGIME_MULTIPLIERS.get(str(regime_name).lower(), 0.85),
                    "volatility": self._VOLATILITY_MULTIPLIERS.get(str(volatility_regime).upper(), 0.9),
                    "news": 0.0,
                },
            )

        regime_mult = self._REGIME_MULTIPLIERS.get(str(regime_name).lower(), 0.85)
        volatility_mult = self._VOLATILITY_MULTIPLIERS.get(str(volatility_regime).upper(), 0.9)
        session_mult = max(0.0, float(session_multiplier))

        multiplier = max(0.0, min(1.5, session_mult * regime_mult * volatility_mult))
        reason = (
            f"risk_mult session={session_mult:.2f} regime={regime_mult:.2f} "
            f"volatility={volatility_mult:.2f}"
        )
        return RiskAdjustment(
            allowed=True,
            multiplier=round(multiplier, 4),
            reason=reason,
            components={
                "session": round(session_mult, 4),
                "regime": round(regime_mult, 4),
                "volatility": round(volatility_mult, 4),
                "news": 1.0,
            },
        )

    def _high_impact_count(self, imminent_events: list[Any]) -> int:
        count = 0
        for event in imminent_events:
            impact = getattr(event, "impact", None)
            if impact == Impact.HIGH or str(getattr(impact, "value", impact)).upper() == "HIGH":
                count += 1
        return count


# === UPGRADE STEP 9 COMPLETED ===
