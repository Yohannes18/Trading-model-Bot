from __future__ import annotations
from ..types import NarrativePattern
PATTERN_DESCRIPTIONS: dict[NarrativePattern, str] = {
    NarrativePattern.ASIA_COMPRESSION:  "Asia compressed — London likely to expand",
    NarrativePattern.ASIA_EXPANSION:    "Asia expanded — London may continue or reverse",
    NarrativePattern.LONDON_SWEEP:      "London swept Asia liquidity — reversal probable",
    NarrativePattern.LONDON_EXPANSION:  "London broke out — momentum day",
    NarrativePattern.LONDON_TRAP:       "London fake breakout — NY may reverse",
    NarrativePattern.NY_REVERSAL:       "NY reversing London direction",
    NarrativePattern.NY_CONTINUATION:   "NY continuing London direction",
    NarrativePattern.UNKNOWN:           "No clear narrative pattern",
}
EXPANSION_COMPATIBLE = {NarrativePattern.ASIA_COMPRESSION, NarrativePattern.LONDON_EXPANSION}
REVERSAL_COMPATIBLE  = {NarrativePattern.LONDON_SWEEP, NarrativePattern.LONDON_TRAP, NarrativePattern.NY_REVERSAL}
