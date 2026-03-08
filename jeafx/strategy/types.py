from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine.displacement_engine import DisplacementResult
    from engine.liquidity_magnet_engine import LiquidityMagnetResult
    from engine.liquidity_map_engine import LiquidityMapResult
    from engine.liquidity_regime_engine import LiquidityRegimeResult
    from engine.macro_narrative_engine import MacroNarrative

class SessionType(Enum):
    ASIA             = "ASIA"
    LONDON           = "LONDON"
    NEW_YORK         = "NEW_YORK"
    LONDON_NY_OVERLAP= "LONDON_NY_OVERLAP"
    OFF              = "OFF"

class SessionBehavior(Enum):
    LIQUIDITY_BUILD = "LIQUIDITY_BUILD"
    EXPANSION       = "EXPANSION"
    CONTINUATION    = "CONTINUATION"
    REVERSAL        = "REVERSAL"
    OVERLAP         = "OVERLAP"
    INACTIVE        = "INACTIVE"

class VolatilityRegime(Enum):
    COMPRESSION = "COMPRESSION"
    NORMAL      = "NORMAL"
    EXPANSION   = "EXPANSION"

@dataclass(frozen=True)
class VolatilityAnalysis:
    regime: VolatilityRegime
    atr: float
    atr_baseline: float
    atr_ratio: float
    expansion_probability: float
    range_ratio: float
    compression_score: float
    expansion_score: float

class MacroBias(Enum):
    BULLISH_GOLD = "BULLISH_GOLD"
    BEARISH_GOLD = "BEARISH_GOLD"
    NEUTRAL      = "NEUTRAL"

class LiquidityBias(Enum):
    BUY_SIDE  = "BUY_SIDE"
    SELL_SIDE = "SELL_SIDE"
    NEUTRAL   = "NEUTRAL"

class NarrativePattern(Enum):
    ASIA_COMPRESSION = "ASIA_COMPRESSION"
    ASIA_EXPANSION   = "ASIA_EXPANSION"
    LONDON_SWEEP     = "LONDON_SWEEP"
    LONDON_EXPANSION = "LONDON_EXPANSION"
    LONDON_TRAP      = "LONDON_TRAP"
    NY_REVERSAL      = "NY_REVERSAL"
    NY_CONTINUATION  = "NY_CONTINUATION"
    UNKNOWN          = "UNKNOWN"

class NarrativeEvent(Enum):
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    INDUCEMENT = "INDUCEMENT"
    DISPLACEMENT = "DISPLACEMENT"
    BREAK_OF_STRUCTURE = "BREAK_OF_STRUCTURE"
    CONTINUATION = "CONTINUATION"
    TRAP = "TRAP"
    NONE = "NONE"

@dataclass(frozen=True)
class NarrativeAnalysis:
    events: list[NarrativeEvent]
    bias: str
    strength: float
    sweep_detected: bool
    displacement_detected: bool
    bos_detected: bool
    inducement_detected: bool

class ModelType(Enum):
    EXPANSION      = "EXPANSION"
    REVERSAL       = "REVERSAL"
    LIQUIDITY_TRAP = "LIQUIDITY_TRAP"
    NO_TRADE       = "NO_TRADE"

class Direction(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    NONE = "NONE"

class AMDPhase(Enum):
    ACCUMULATION = "ACCUMULATION"
    MANIPULATION = "MANIPULATION"
    DISTRIBUTION = "DISTRIBUTION"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class LiquidityLevel:
    price: float
    level_type: str
    timeframe: str
    score: int
    side: str

@dataclass(frozen=True)
class LiquidityZone:
    price: float
    score: int
    zone_type: str
    distance: float
    direction: str
    strength: str

@dataclass(frozen=True)
class LiquidityRaidPrediction:
    target_zone: LiquidityZone
    raid_direction: str
    probability: float
    distance_r: float
    path_clear: bool
    estimated_time_window: str

@dataclass(frozen=True)
class InefficiencyZone:
    type: str
    direction: str
    top: float
    bottom: float
    midpoint: float
    strength: float
    probability_of_fill: float
    distance_r: float

@dataclass(frozen=True)
class InefficiencyMap:
    zones_above: list[InefficiencyZone]
    zones_below: list[InefficiencyZone]
    nearest_inefficiency: Optional[InefficiencyZone]
    magnet_score: float

@dataclass(frozen=True)
class TrapAnalysis:
    trap_probability: float
    trap_type: str
    trap_reason: str
    risk_level: str

@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    confidence_level: str
    allowed_trade: bool
    reason: str

@dataclass
class AsiaSession:
    high: float = 0.0
    low: float = 0.0
    range_pips: float = 0.0
    classification: str = "UNKNOWN"
    direction: str = "NEUTRAL"

@dataclass
class NarrativeScore:
    pattern: NarrativePattern
    probability: float
    description: str = ""

@dataclass
class TradeSetupProposal:
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    rr: float
    risk_percent: float
    position_size: float
    entry_reason: str = ""
    sl_reason: str = ""
    tp_reason: str = ""

@dataclass
class ModelResult:
    model_type: ModelType
    confidence: float
    direction: Direction
    setup: Optional[TradeSetupProposal]
    signals: list[str] = field(default_factory=list)
    blocked_reason: str = ""

@dataclass
class MarketAnalysis:
    timestamp: datetime
    pair: str
    timeframe: str
    session: SessionType = SessionType.OFF
    session_behavior: SessionBehavior = SessionBehavior.INACTIVE
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    volatility: VolatilityAnalysis = field(default_factory=lambda: VolatilityAnalysis(
        regime=VolatilityRegime.NORMAL,
        atr=0.0,
        atr_baseline=0.0,
        atr_ratio=1.0,
        expansion_probability=0.0,
        range_ratio=1.0,
        compression_score=0.0,
        expansion_score=0.0,
    ))
    liquidity_regime: Optional["LiquidityRegimeResult"] = None
    liquidity_map: Optional["LiquidityMapResult"] = None
    displacement: Optional["DisplacementResult"] = None
    liquidity_magnet: Optional["LiquidityMagnetResult"] = None
    macro_narrative: Optional["MacroNarrative"] = None
    macro_bias: MacroBias = MacroBias.NEUTRAL
    liquidity_bias: LiquidityBias = LiquidityBias.NEUTRAL
    buy_side_levels: list[LiquidityLevel] = field(default_factory=list)
    sell_side_levels: list[LiquidityLevel] = field(default_factory=list)
    liquidity_zones_above: list[LiquidityZone] = field(default_factory=list)
    liquidity_zones_below: list[LiquidityZone] = field(default_factory=list)
    raid_prediction: LiquidityRaidPrediction = field(default_factory=lambda: LiquidityRaidPrediction(
        target_zone=LiquidityZone(0.0, 0, "NONE", 0.0, "NONE", "LOW"),
        raid_direction="NONE",
        probability=0.0,
        distance_r=0.0,
        path_clear=False,
        estimated_time_window="Next Session",
    ))
    inefficiency_map: InefficiencyMap = field(default_factory=lambda: InefficiencyMap(
        zones_above=[],
        zones_below=[],
        nearest_inefficiency=None,
        magnet_score=0.0,
    ))
    trap_analysis: TrapAnalysis = field(default_factory=lambda: TrapAnalysis(
        trap_probability=0.0,
        trap_type="NONE",
        trap_reason="",
        risk_level="LOW",
    ))
    confidence_result: ConfidenceResult = field(default_factory=lambda: ConfidenceResult(
        score=0.0,
        confidence_level="NO_TRADE",
        allowed_trade=False,
        reason="Not evaluated",
    ))
    nearest_magnet: Optional[LiquidityZone] = None
    nearest_magnet_distance_r: float = 0.0
    liquidity_path_clear: bool = False
    sweep_detected: bool = False
    liquidity_trap: bool = False
    asia_session: Optional[AsiaSession] = None
    narrative_pattern: NarrativePattern = NarrativePattern.UNKNOWN
    narrative: NarrativeAnalysis = field(default_factory=lambda: NarrativeAnalysis(
        events=[NarrativeEvent.NONE],
        bias="NEUTRAL",
        strength=0.0,
        sweep_detected=False,
        displacement_detected=False,
        bos_detected=False,
        inducement_detected=False,
    ))
    narrative_scores: list[NarrativeScore] = field(default_factory=list)
    expansion_confidence: float = 0.0
    reversal_confidence: float = 0.0
    trap_confidence: float = 0.0
    amd_phase: AMDPhase = AMDPhase.UNKNOWN
    amd_confidence: float = 0.0
    accumulation_confidence: float = 0.0
    manipulation_confidence: float = 0.0
    distribution_confidence: float = 0.0
    amd_reason: str = ""
    recommended_model: ModelType = ModelType.NO_TRADE
    model_result: Optional[ModelResult] = None
    has_trade_setup: bool = False
    briefing: str = ""
