from __future__ import annotations

from quantara.strategy.types import ConfidenceResult


class TradeConfidenceEngine:
    """Aggregates intelligence layers into a final trade confidence decision."""

    WEIGHTS = {
        "amd": 0.18,
        "narrative": 0.18,
        "liquidity": 0.16,
        "raid": 0.14,
        "volatility": 0.12,
        "fundamental": 0.10,
        "trap": 0.07,
        "inefficiency": 0.05,
    }

    def evaluate(
        self,
        amd_alignment: float,
        narrative_alignment: float,
        liquidity_strength: float,
        raid_prediction: float,
        volatility_expansion: float,
        fundamental_bias: float,
        trap_risk: float,
        inefficiency_magnet: float,
    ) -> ConfidenceResult:
        score_0_1 = (
            self.WEIGHTS["amd"] * self._clamp01(amd_alignment)
            + self.WEIGHTS["narrative"] * self._clamp01(narrative_alignment)
            + self.WEIGHTS["liquidity"] * self._clamp01(liquidity_strength)
            + self.WEIGHTS["raid"] * self._clamp01(raid_prediction)
            + self.WEIGHTS["volatility"] * self._clamp01(volatility_expansion)
            + self.WEIGHTS["fundamental"] * self._clamp01(fundamental_bias)
            + self.WEIGHTS["trap"] * self._clamp01(1.0 - trap_risk)
            + self.WEIGHTS["inefficiency"] * self._clamp01(inefficiency_magnet)
        )

        score = round(max(0.0, min(100.0, score_0_1 * 100.0)), 2)
        if score < 60:
            return ConfidenceResult(score, "NO_TRADE", False, "Confidence below 60")
        if score < 70:
            return ConfidenceResult(score, "MONITOR", False, "Confidence 60-69")
        if score < 80:
            return ConfidenceResult(score, "VALID_SETUP", True, "Confidence 70-79")
        return ConfidenceResult(score, "HIGH_PROBABILITY", True, "Confidence 80+")

    def _clamp01(self, x: float) -> float:
        return max(0.0, min(1.0, x))

    def evaluate_institutional(
        self,
        liquidity_alignment: float,
        raid_probability: float,
        inefficiency_magnet: float,
        displacement_strength: float,
        trap_safety: float,
        volatility_regime_alignment: float,
        macro_bias_alignment: float,
        session_weight: float,
        rr: float,
        sl_ok: bool,
        trap_risk: float,
        threshold: float = 72.0,
    ) -> ConfidenceResult:
        weights = {
            "liquidity": 0.20,
            "raid": 0.15,
            "inefficiency": 0.15,
            "displacement": 0.15,
            "trap": 0.10,
            "volatility": 0.10,
            "macro": 0.10,
            "session": 0.05,
        }

        score_0_1 = (
            weights["liquidity"] * self._clamp01(liquidity_alignment)
            + weights["raid"] * self._clamp01(raid_probability)
            + weights["inefficiency"] * self._clamp01(inefficiency_magnet)
            + weights["displacement"] * self._clamp01(displacement_strength)
            + weights["trap"] * self._clamp01(trap_safety)
            + weights["volatility"] * self._clamp01(volatility_regime_alignment)
            + weights["macro"] * self._clamp01(macro_bias_alignment)
            + weights["session"] * self._clamp01(session_weight)
        )
        score = round(max(0.0, min(100.0, score_0_1 * 100.0)), 2)

        allowed_trade = score >= threshold and rr >= 3.0 and sl_ok and trap_risk < 0.35
        if not allowed_trade:
            reason = f"threshold={threshold:.0f} rr={rr:.2f} sl_ok={sl_ok} trap_risk={trap_risk:.2f}"
            return ConfidenceResult(score, "NO_TRADE", False, reason)
        if score >= 85:
            return ConfidenceResult(score, "HIGH_PROBABILITY", True, "Institutional confluence high")
        return ConfidenceResult(score, "VALID_SETUP", True, "Institutional confluence valid")
