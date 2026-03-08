"""
Legacy compatibility shim for regression tests.

WARNING:
This module exists only for legacy regression tests.
It will be removed in future versions.
"""

from __future__ import annotations

from jeafx.config import StressLevel
from jeafx.database.db_manager import DatabaseManager
from jeafx.engine import calc_levels as _calc_levels
from jeafx.governance.governance_engine import GovernanceEngine as _GovernanceEngine
from jeafx.risk.position_sizer import PositionSizer as _PositionSizer
from jeafx.risk.risk_validator import RiskValidator as _RiskValidator
from jeafx.state_machine import StressState
from jeafx.stress.stress_engine import StressEngine as _StressEngine
from jeafx.strategy.analysis_engine import AnalysisEngine
from jeafx.strategy.confidence_engine import ConfidenceEngine as _ConfidenceEngine
from jeafx.strategy.smc_engine import Candle, Direction, SMCEngine as _SMCEngine
from jeafx.strategy.types import MarketAnalysis


db = DatabaseManager()


class JeaFXEngine:
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
    "JeaFXEngine",
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
