from __future__ import annotations

import asyncio

from ..config import DAILY_RISK_CAP, MAX_OPEN_TRADES
from ..database.db_manager import DatabaseManager


class RiskValidator:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        self._lock = asyncio.Lock()

    async def validate_new_trade(self) -> tuple[bool, str]:
        async with self._lock:
            daily_used = self._db.get_today_risk()
            if daily_used >= DAILY_RISK_CAP:
                return False, f"Daily hard stop reached ({daily_used:.1f}%/{DAILY_RISK_CAP}%)"

            open_trades = self._db.get_open_trade_count()
            if open_trades >= MAX_OPEN_TRADES:
                return False, f"Max open trades reached ({open_trades}/{MAX_OPEN_TRADES})"

            return True, "OK"
