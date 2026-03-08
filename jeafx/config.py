from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Final

try:
    from dotenv import load_dotenv
    # Walk up from this file to find .env at project root
    _here = Path(__file__).resolve().parent
    for _p in [_here, _here.parent, _here.parent.parent]:
        _env = _p / ".env"
        if _env.exists():
            load_dotenv(_env)
            break
except ImportError:
    pass


class EngineError(Exception):
    pass


class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class Impact(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Sentiment(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class StressLevel(Enum):
    NONE = "NONE"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ModelStatus(Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    SHADOW = "SHADOW"


class TradeState(Enum):
    IDLE = "IDLE"
    ANALYZING = "ANALYZING"
    AWAITING_CONFIRM = "AWAITING_CONFIRM"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    MANAGING = "MANAGING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0") or 0) or None
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "") or None
MT5_SERVER = os.getenv("MT5_SERVER", "") or None
TG_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

PAIRS: Final[list[str]] = ["XAUUSD", "EURUSD", "GBPUSD"]
TIMEFRAMES: Final[list[str]] = ["M30", "H1"]
KILL_ZONES_UTC: Final[list[tuple[int, int]]] = [(6, 9), (12, 15)]
SESSION_FILTER = os.getenv("SESSION_FILTER", "true").lower() != "false"

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "90"))
SIGNAL_COOLDOWN = int(os.getenv("SIGNAL_COOLDOWN", "5400"))
BLACKOUT_MINUTES = int(os.getenv("BLACKOUT_MINUTES", "15"))
CONFIRM_TIMEOUT = int(os.getenv("CONFIRM_TIMEOUT", "300"))
SETUP_TTL_SECONDS = int(os.getenv("SETUP_TTL_SECONDS", str(CONFIRM_TIMEOUT)))

CONFIDENCE_MIN = int(os.getenv("CONFIDENCE_MIN", "70"))
CONFIDENCE_MIN_SEVERE = int(os.getenv("CONFIDENCE_MIN_SEVERE", "80"))

RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1.0"))
DAILY_RISK_CAP = float(os.getenv("DAILY_RISK_CAP", "3.0"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "2"))
MIN_RR = float(os.getenv("MIN_RR", "3.0"))

STRESS_ROLLING_N = int(os.getenv("STRESS_ROLLING_N", "20"))
STRESS_MILD_EXPECT = float(os.getenv("STRESS_MILD_EXPECT", "0.3"))
STRESS_MODERATE_EXPECT = float(os.getenv("STRESS_MODERATE_EXPECT", "0.0"))
STRESS_SEVERE_WINRATE = float(os.getenv("STRESS_SEVERE_WINRATE", "0.25"))
STRESS_SEVERE_DD = float(os.getenv("STRESS_SEVERE_DD", "2.0"))
STRESS_RISK_MULT: Final[dict[str, float]] = {
    "NONE": 1.0,
    "MILD": 0.8,
    "MODERATE": 0.7,
    "SEVERE": 0.5,
}

GOVERNANCE_YEARLY_LIMIT = int(os.getenv("GOVERNANCE_YEARLY_LIMIT", "2"))
GOVERNANCE_LOCKOUT_DAYS = int(os.getenv("GOVERNANCE_LOCKOUT_DAYS", "7"))
SHADOW_QUALIFY_TRADES = int(os.getenv("SHADOW_QUALIFY_TRADES", "20"))
SHADOW_QUALIFY_WINRATE = float(os.getenv("SHADOW_QUALIFY_WINRATE", "0.50"))
SHADOW_QUALIFY_EXPECT = float(os.getenv("SHADOW_QUALIFY_EXPECT", "0.5"))

MAX_SPREAD_POINTS = float(os.getenv("MAX_SPREAD_POINTS", "35"))
MAX_SLIPPAGE_POINTS = float(os.getenv("MAX_SLIPPAGE_POINTS", "50"))

HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "10"))
EVENT_LOOP_LAG_WARN_SECONDS = float(os.getenv("EVENT_LOOP_LAG_WARN_SECONDS", "2.0"))

API_HOST = "0.0.0.0"
API_PORT = int(os.getenv("API_PORT", "8000"))

for d in ["signals", "logs", "cache", "data"]:
    Path(d).mkdir(exist_ok=True)

DB_PATH = Path("data/jeafx.db")


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        handlers=[
            logging.FileHandler("logs/jeafx.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("jeafx")


log = setup_logging()


def log_structured(event: str, **fields: object) -> None:
    ordered = " ".join(f"{k}={fields[k]}" for k in sorted(fields))
    log.info("%s %s", event, ordered)


@dataclass(frozen=True)
class RuntimeContext:
    started_at: datetime
