from __future__ import annotations

from dataclasses import dataclass, field

from ..config import CONFIDENCE_MIN, CONFIDENCE_MIN_SEVERE, StressLevel
from .smc_engine import SMCAnalysis


@dataclass
class ConfidenceResult:
    score: int = 0
    components: dict[str, int] = field(default_factory=dict)
    passed: bool = False
    reason: str = ""


class ConfidenceEngine:
    WEIGHTS: dict[str, int] = {
        "htf_bias": 20,
        "liquidity": 15,
        "bos_strength": 15,
        "ob_quality": 10,
        "fvg": 10,
        "volume": 10,
        "rr_potential": 10,
        "fundamentals": 10,
    }

    def score(
        self,
        analysis: SMCAnalysis,
        rr: float,
        fund_score: int,
        stress: StressLevel,
    ) -> ConfidenceResult:
        result = ConfidenceResult()
        confluences = analysis.confluences
        sub: dict[str, float] = {}

        sub["htf_bias"] = 1.0 if any("BOS" in x or "CHoCH" in x for x in confluences) else 0.0
        sub["liquidity"] = 1.0 if any("Swept" in x for x in confluences) else 0.0

        if any("CHoCH" in x for x in confluences):
            sub["bos_strength"] = 1.0
        elif any("BOS" in x for x in confluences):
            sub["bos_strength"] = 0.7
        else:
            sub["bos_strength"] = 0.0

        sub["ob_quality"] = 1.0 if analysis.ob_high > 0 else 0.0
        sub["fvg"] = 1.0 if analysis.fvg_high > 0 else 0.0
        sub["volume"] = min(analysis.score / 80.0, 1.0)

        if rr >= 5:
            sub["rr_potential"] = 1.0
        elif rr >= 3:
            sub["rr_potential"] = 0.8
        elif rr >= 2:
            sub["rr_potential"] = 0.6
        else:
            sub["rr_potential"] = 0.0

        sub["fundamentals"] = min(fund_score / 10.0, 1.0)

        total = sum(self.WEIGHTS[k] * sub[k] for k in sub)
        result.score = round(total)
        result.components = {k: round(sub[k] * self.WEIGHTS[k]) for k in sub}

        threshold = CONFIDENCE_MIN_SEVERE if stress == StressLevel.SEVERE else CONFIDENCE_MIN
        result.passed = result.score >= threshold
        result.reason = (
            f"Score {result.score} ≥ {threshold} ✓"
            if result.passed
            else f"Score {result.score} < {threshold} threshold ✗"
        )
        return result

    def score_live(
        self,
        model_confidence: float,
        model_signals: list[str],
        rr: float,
        fund_score: int,
        stress: StressLevel,
        volatility_regime: str,
        risk_conditions_ok: bool,
    ) -> ConfidenceResult:
        result = ConfidenceResult()
        structure = 18 if any("BOS" in s or "MSS" in s or "H&S" in s for s in model_signals) else 8
        liquidity = 18 if any("Liquidity" in s or "Sweep" in s or "Trap" in s for s in model_signals) else 8
        fundamentals = max(0, min(20, 10 + fund_score))
        if volatility_regime == "EXPANSION":
            volatility = 16
        elif volatility_regime == "COMPRESSION":
            volatility = 12
        else:
            volatility = 8
        risk_conditions = 20 if (risk_conditions_ok and rr >= 3.0) else 8

        model_component = max(0, min(20, round(model_confidence * 20)))

        result.components = {
            "structure": structure,
            "liquidity": liquidity,
            "fundamentals": fundamentals,
            "volatility": volatility,
            "risk_conditions": risk_conditions,
            "model": model_component,
        }
        result.score = min(100, sum(result.components.values()))

        threshold = CONFIDENCE_MIN_SEVERE if stress == StressLevel.SEVERE else CONFIDENCE_MIN
        result.passed = result.score >= threshold
        result.reason = (
            f"Live confidence {result.score} ≥ {threshold} ✓"
            if result.passed
            else f"Live confidence {result.score} < {threshold} ✗"
        )
        return result
