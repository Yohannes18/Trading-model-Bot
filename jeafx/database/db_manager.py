from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import DB_PATH


class DatabaseManager:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = str(path)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id              TEXT PRIMARY KEY,
                    pair            TEXT,
                    direction       TEXT,
                    entry_price     REAL,
                    stop_loss       REAL,
                    take_profit1    REAL,
                    take_profit2    REAL,
                    lot_size        REAL,
                    risk_percent    REAL,
                    rr_planned      REAL,
                    confidence      INTEGER,
                    stress_level    TEXT,
                    model_status    TEXT,
                    trade_state     TEXT,
                    is_shadow       INTEGER DEFAULT 0,
                    mt5_ticket      INTEGER,
                    opened_at       TEXT,
                    closed_at       TEXT,
                    close_price     REAL,
                    result_r        REAL,
                    result_amount   REAL,
                    session         TEXT,
                    timeframe       TEXT,
                    fundamental_risk TEXT,
                    notes           TEXT
                );

                CREATE TABLE IF NOT EXISTS trade_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id    TEXT,
                    event_type  TEXT,
                    state_from  TEXT,
                    state_to    TEXT,
                    timestamp   TEXT,
                    metadata    TEXT
                );

                CREATE TABLE IF NOT EXISTS stress_logs (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    stress_level        TEXT,
                    rolling_expectancy  REAL,
                    rolling_winrate     REAL,
                    drawdown            REAL,
                    peak_equity         REAL,
                    current_equity      REAL,
                    timestamp           TEXT
                );

                CREATE TABLE IF NOT EXISTS governance_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    event           TEXT,
                    model_status    TEXT,
                    severe_count    INTEGER,
                    lock_until      TEXT,
                    timestamp       TEXT,
                    notes           TEXT
                );
                """
            )

    def log_trade(self, trade: dict[str, object]) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO trades
                (id,pair,direction,entry_price,stop_loss,take_profit1,take_profit2,
                 lot_size,risk_percent,rr_planned,confidence,stress_level,model_status,
                 trade_state,is_shadow,mt5_ticket,opened_at,closed_at,close_price,
                 result_r,result_amount,session,timeframe,fundamental_risk,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trade.get("id"),
                    trade.get("pair"),
                    trade.get("direction"),
                    trade.get("entry_price"),
                    trade.get("stop_loss"),
                    trade.get("take_profit1"),
                    trade.get("take_profit2"),
                    trade.get("lot_size"),
                    trade.get("risk_percent"),
                    trade.get("rr_planned"),
                    trade.get("confidence"),
                    trade.get("stress_level"),
                    trade.get("model_status"),
                    trade.get("trade_state"),
                    trade.get("is_shadow", 0),
                    trade.get("mt5_ticket"),
                    trade.get("opened_at"),
                    trade.get("closed_at"),
                    trade.get("close_price"),
                    trade.get("result_r"),
                    trade.get("result_amount"),
                    trade.get("session"),
                    trade.get("timeframe"),
                    trade.get("fundamental_risk"),
                    trade.get("notes"),
                ),
            )

    def log_event(
        self,
        trade_id: str,
        event_type: str,
        state_from: str,
        state_to: str,
        meta: Optional[dict[str, object]] = None,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO trade_events (trade_id,event_type,state_from,state_to,timestamp,metadata)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    trade_id,
                    event_type,
                    state_from,
                    state_to,
                    datetime.now(tz=timezone.utc).isoformat(),
                    json.dumps(meta or {}),
                ),
            )

    def log_stress(
        self,
        stress_level: str,
        rolling_expect: float,
        rolling_wr: float,
        dd: float,
        peak_eq: float,
        cur_eq: float,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO stress_logs (stress_level,rolling_expectancy,rolling_winrate,
                drawdown,peak_equity,current_equity,timestamp)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    stress_level,
                    rolling_expect,
                    rolling_wr,
                    dd,
                    peak_eq,
                    cur_eq,
                    datetime.now(tz=timezone.utc).isoformat(),
                ),
            )

    def log_governance(
        self,
        event: str,
        status: str,
        severe_count: int,
        lock_until: Optional[datetime] = None,
        notes: str = "",
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO governance_log (event,model_status,severe_count,lock_until,timestamp,notes)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    event,
                    status,
                    severe_count,
                    lock_until.isoformat() if lock_until else None,
                    datetime.now(tz=timezone.utc).isoformat(),
                    notes,
                ),
            )

    def get_recent_trades(self, n: int = 50, shadow: Optional[bool] = None) -> list[dict[str, object]]:
        with self._conn() as c:
            if shadow is None:
                rows = c.execute("SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?", (n,)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM trades WHERE is_shadow=? ORDER BY opened_at DESC LIMIT ?",
                    (1 if shadow else 0, n),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_closed_trades(self, n: int = 100, shadow: bool = False) -> list[dict[str, object]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM trades WHERE trade_state='CLOSED' AND is_shadow=?
                ORDER BY closed_at DESC LIMIT ?
                """,
                (1 if shadow else 0, n),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_today_risk(self) -> float:
        today = datetime.now(tz=timezone.utc).date().isoformat()
        with self._conn() as c:
            row = c.execute(
                """
                SELECT COALESCE(SUM(risk_percent),0) FROM trades
                WHERE date(opened_at)=? AND is_shadow=0 AND trade_state NOT IN ('REJECTED','CANCELLED')
                """,
                (today,),
            ).fetchone()
        return float(row[0] if row else 0.0)

    def get_open_trade_count(self) -> int:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT COUNT(*) FROM trades
                WHERE trade_state IN ('EXECUTING','MANAGING') AND is_shadow=0
                """
            ).fetchone()
        return int(row[0] if row else 0)

    def get_open_trades(self) -> list[dict[str, object]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM trades
                WHERE trade_state IN ('EXECUTING','MANAGING') AND is_shadow=0
                """
            ).fetchall()
        return [dict(r) for r in rows]
