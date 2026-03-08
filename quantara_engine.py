"""
Legacy compatibility shim for regression tests.

WARNING:
This module exists only for legacy regression tests.
It will be removed in future versions.
"""

from __future__ import annotations

from quantara.config import StressLevel
from quantara.database.db_manager import DatabaseManager
from quantara.engine import calc_levels as _calc_levels
from quantara.governance.governance_engine import GovernanceEngine as _GovernanceEngine
from quantara.risk.position_sizer import PositionSizer as _PositionSizer
from quantara.risk.risk_validator import RiskValidator as _RiskValidator
from quantara.state_machine import StressState
from quantara.stress.stress_engine import StressEngine as _StressEngine
from quantara.strategy.analysis_engine import AnalysisEngine
from quantara.strategy.confidence_engine import ConfidenceEngine as _ConfidenceEngine
from quantara.strategy.smc_engine import Candle, Direction, SMCEngine as _SMCEngine
from quantara.strategy.types import MarketAnalysis


db = DatabaseManager()


class QuantaraEngine:
    def __init__(self) -> None:
        self.engine = AnalysisEngine()

    def analyze(self, candles, pair: str = "XAUUSD", timeframe: str = "M30") -> MarketAnalysis:
        return self.engine.analyze_market(candles, candles, candles, candles, pair=pair, timeframe=timeframe)


class SMCEngine(_SMCEngine):
    pass


class ConfidenceEngine(_ConfidenceEngine):
    pass


class PositionSizer(_PositionSizer):
    def __init__(self, injected_db=None) -> None:
        super().__init__(injected_db or db)


class RiskValidator(_RiskValidator):
    def __init__(self, injected_db=None) -> None:
        super().__init__(injected_db or db)


class StressEngine(_StressEngine):
    def __init__(self, injected_db=None) -> None:
        super().__init__(injected_db or db)


class GovernanceEngine(_GovernanceEngine):
    def __init__(self, injected_db=None) -> None:
        super().__init__(injected_db or db)


__all__ = [
    "QuantaraEngine",
    "SMCEngine",
    "ConfidenceEngine",
    "PositionSizer",
    "RiskValidator",
    "StressEngine",
    "GovernanceEngine",
    "Candle",
    "Direction",
    "StressLevel",
    "StressState",
    "MarketAnalysis",
    "_calc_levels",
    "db",
]
