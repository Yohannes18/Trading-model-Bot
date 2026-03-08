from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import ModelStatus, StressLevel, TradeState, log


@dataclass
class TradeSetup:
    id: str
    pair: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr: float
    confidence: int
    stress_level: str
    model_status: str
    is_shadow: bool
    session: str
    timeframe: str
    confluences: list[str]
    narrative: str
    fundamental_risk: str
    meta_features: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc) + timedelta(minutes=5))


@dataclass
class Trade:
    setup: TradeSetup
    lot: float
    risk_pct: float
    state: TradeState = TradeState.IDLE
    mt5_ticket: Optional[int] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_price: Optional[float] = None
    result_r: Optional[float] = None
    confirmed_once: bool = False

    @property
    def id(self) -> str:
        return self.setup.id

    def to_record(self) -> dict[str, object]:
        return {
            "id": self.setup.id,
            "pair": self.setup.pair,
            "direction": self.setup.direction,
            "entry_price": self.setup.entry,
            "stop_loss": self.setup.sl,
            "take_profit1": self.setup.tp1,
            "take_profit2": self.setup.tp2,
            "lot_size": self.lot,
            "risk_percent": self.risk_pct,
            "rr_planned": self.setup.rr,
            "confidence": self.setup.confidence,
            "stress_level": self.setup.stress_level,
            "model_status": self.setup.model_status,
            "is_shadow": 1 if self.setup.is_shadow else 0,
            "trade_state": self.state.value,
            "mt5_ticket": self.mt5_ticket,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "close_price": self.close_price,
            "result_r": self.result_r,
            "session": self.setup.session,
            "timeframe": self.setup.timeframe,
            "fundamental_risk": self.setup.fundamental_risk,
            "notes": self.setup.narrative,
        }


@dataclass
class StressState:
    level: StressLevel = StressLevel.NONE
    rolling_expectancy: float = 0.0
    rolling_winrate: float = 0.0
    drawdown: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    risk_multiplier: float = 1.0
    triggers: list[str] = field(default_factory=list)


@dataclass
class GovernanceState:
    status: ModelStatus = ModelStatus.ACTIVE
    severe_count_ytd: int = 0
    lock_until: Optional[datetime] = None
    shadow_trades: int = 0
    shadow_winrate: float = 0.0
    shadow_expectancy: float = 0.0
    can_trade: bool = True
    reason: str = ""


def transition_trade_state(trade: Trade, new_state: TradeState, reason: str = "") -> TradeState:
    previous = trade.state
    trade.state = new_state
    log.info(
        "state_transition trade_id=%s from=%s to=%s reason=%s",
        trade.id,
        previous.value,
        new_state.value,
        reason,
    )
    return previous
