from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PdhPdlSweep:
    detected: bool
    side: str
    swept_level: float
    candle_time: str


class PdhPdlSweepDetector:
    def detect(self, candles_m30: list[Any], candles_d1: list[Any], lookback: int = 12) -> PdhPdlSweep:
        if len(candles_m30) < 2 or len(candles_d1) < 2:
            return PdhPdlSweep(False, "NONE", 0.0, "")

        previous_day = candles_d1[-2]
        pdh = float(previous_day.high)
        pdl = float(previous_day.low)

        recent = candles_m30[-lookback:] if len(candles_m30) >= lookback else candles_m30
        for candle in reversed(recent):
            high = float(candle.high)
            low = float(candle.low)
            close = float(candle.close)
            if high > pdh and close < pdh:
                return PdhPdlSweep(True, "PDH", pdh, candle.time.isoformat())
            if low < pdl and close > pdl:
                return PdhPdlSweep(True, "PDL", pdl, candle.time.isoformat())

        return PdhPdlSweep(False, "NONE", 0.0, "")


# === UPGRADE STEP 10 COMPLETED ===
