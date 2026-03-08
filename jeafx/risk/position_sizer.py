from __future__ import annotations

from dataclasses import dataclass

from ..config import DAILY_RISK_CAP, MAX_OPEN_TRADES, RISK_PERCENT
from ..database.db_manager import DatabaseManager
from ..state_machine import StressState


@dataclass
class PositionSize:
    lot_size: float
    risk_amount: float
    risk_percent: float
    adjusted_risk_percent: float
    stress_multiplier: float
    allowed: bool
    reason: str


class PositionSizer:
    PIP_VALUES = {"EURUSD": 10.0, "GBPUSD": 10.0}
    XAUUSD_DOLLAR_PER_LOT = 100.0

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def calculate(self, pair: str, entry: float, sl: float, equity: float, stress: StressState) -> PositionSize:
        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            return PositionSize(0, 0, 0, 0, 1.0, False, "SL distance is zero")

        daily_used = self._db.get_today_risk()
        if daily_used >= DAILY_RISK_CAP:
            return PositionSize(0, 0, 0, 0, 1.0, False, f"Daily risk cap hit ({daily_used:.1f}% / {DAILY_RISK_CAP}%)")

        open_trades = self._db.get_open_trade_count()
        if open_trades >= MAX_OPEN_TRADES:
            return PositionSize(0, 0, 0, 0, 1.0, False, f"Max open trades reached ({open_trades}/{MAX_OPEN_TRADES})")

        mult = stress.risk_multiplier
        adj_risk = RISK_PERCENT * mult
        remaining = DAILY_RISK_CAP - daily_used
        final_risk = min(adj_risk, remaining)

        risk_amt = equity * (final_risk / 100)
        if pair == "XAUUSD":
            risk_per_lot = sl_dist * self.XAUUSD_DOLLAR_PER_LOT
            lot = round(risk_amt / risk_per_lot, 2) if risk_per_lot > 0 else 0.0
        else:
            pip_val = self.PIP_VALUES.get(pair, 10.0)
            sl_pips = sl_dist * (100 if "JPY" not in pair else 1)
            lot = round(risk_amt / (sl_pips * pip_val), 2)
        lot = max(0.01, min(lot, 10.0))

        return PositionSize(
            lot_size=lot,
            risk_amount=round(risk_amt, 2),
            risk_percent=RISK_PERCENT,
            adjusted_risk_percent=round(final_risk, 3),
            stress_multiplier=mult,
            allowed=True,
            reason=f"{lot} lots | {final_risk:.2f}% risk | stress {stress.level.value}",
        )
