from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class MacroNarrative:
    sentiment: str
    news_risk: float
    bias: str
    trade_blocked: bool


class MacroNarrativeEngine:
    """Builds deterministic macro narrative context from macro bias and market shock profile."""

    def analyze(self, candles: List, macro_bias: str, event_minutes_to_high_impact: Optional[int] = None) -> MacroNarrative:
        if not candles or len(candles) < 20:
            return MacroNarrative(sentiment="neutral", news_risk=0.0, bias="neutral", trade_blocked=False)

        recent = candles[-20:]
        ranges = [c.high - c.low for c in recent]
        avg_range = sum(ranges[:-1]) / max(len(ranges[:-1]), 1)
        last_range = ranges[-1]

        shock_ratio = (last_range / max(avg_range, 1e-9)) if avg_range > 0 else 0.0
        news_risk = max(0.0, min(1.0, (shock_ratio - 1.0) / 2.0))

        bias = "neutral"
        if macro_bias == "BULLISH_GOLD":
            bias = "bullish_gold"
        elif macro_bias == "BEARISH_GOLD":
            bias = "bearish_gold"

        sentiment = "neutral"
        if bias == "bullish_gold":
            sentiment = "risk_off"
        elif bias == "bearish_gold":
            sentiment = "risk_on"

        event_block = event_minutes_to_high_impact is not None and event_minutes_to_high_impact <= 15
        shock_block = news_risk >= 0.85
        trade_blocked = bool(event_block or shock_block)

        return MacroNarrative(
            sentiment=sentiment,
            news_risk=round(news_risk, 4),
            bias=bias,
            trade_blocked=trade_blocked,
        )
