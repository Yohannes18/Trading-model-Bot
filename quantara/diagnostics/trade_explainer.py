from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TradeExplanation:
    decision: str
    decision_reason: str
    model_scores: dict[str, float]
    threshold: float
    confidence_score: float
    reasons: dict[str, str]

    def to_payload(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "model_scores": self.model_scores,
            "threshold": self.threshold,
            "confidence_score": self.confidence_score,
            "reasons": self.reasons,
        }


class TradeExplainer:
    def build(
        self,
        *,
        analysis: Any,
        decision: str,
        decision_reason: str,
        threshold: float,
        confidence_score: float,
        session_name: str,
        regime_name: str,
    ) -> TradeExplanation:
        model_scores = {
            "EXPANSION": round(float(getattr(analysis, "expansion_confidence", 0.0)) * 100.0, 2),
            "REVERSAL": round(float(getattr(analysis, "reversal_confidence", 0.0)) * 100.0, 2),
            "LIQUIDITY_TRAP": round(float(getattr(analysis, "trap_confidence", 0.0)) * 100.0, 2),
        }

        narrative = getattr(analysis, "narrative", None)
        narrative_bias = getattr(narrative, "bias", "NEUTRAL") if narrative is not None else "NEUTRAL"
        narrative_strength = getattr(narrative, "strength", 0.0) if narrative is not None else 0.0
        structure_reason = f"{getattr(analysis, 'narrative_pattern', type('obj', (), {'value': 'UNKNOWN'})) .value} | bias={narrative_bias} | strength={float(narrative_strength):.2f}"

        liquidity_bias = getattr(getattr(analysis, "liquidity_bias", None), "value", "NEUTRAL")
        liquidity_reason = (
            f"bias={liquidity_bias} | above={len(getattr(analysis, 'liquidity_zones_above', []) or [])} "
            f"below={len(getattr(analysis, 'liquidity_zones_below', []) or [])}"
        )

        macro_reason = getattr(getattr(analysis, "macro_bias", None), "value", "NEUTRAL")
        volatility_reason = getattr(getattr(analysis, "volatility_regime", None), "value", "NORMAL")

        reasons = {
            "structure": structure_reason,
            "liquidity": liquidity_reason,
            "macro": str(macro_reason),
            "session": session_name,
            "regime": regime_name,
            "volatility": volatility_reason,
        }

        return TradeExplanation(
            decision=decision,
            decision_reason=decision_reason,
            model_scores=model_scores,
            threshold=round(float(threshold), 2),
            confidence_score=round(float(confidence_score), 2),
            reasons=reasons,
        )


# === UPGRADE STEP 7 COMPLETED ===
