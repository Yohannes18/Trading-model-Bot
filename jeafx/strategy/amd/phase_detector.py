from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..types import AMDPhase, SessionType


@dataclass
class AMDPhaseResult:
    phase: AMDPhase
    confidence: float
    accumulation_confidence: float
    manipulation_confidence: float
    distribution_confidence: float
    reason: str


class AMDPhaseDetector:
    def __init__(self) -> None:
        self._last_phase_by_pair: dict[str, AMDPhase] = {}

    def detect(
        self,
        pair: str,
        session: SessionType,
        candles_m30,
        candles_d1,
        asia_range: float,
        buy_levels,
        sell_levels,
        sweep_detected: bool,
        sweep_trap: bool,
        mss_detected: bool,
        volatility_regime: str,
        displacement: bool,
        fvg_detected: bool,
    ) -> AMDPhaseResult:
        now = datetime.now(tz=timezone.utc)
        hour = now.hour

        atr_m30 = self._atr(candles_m30, 14)
        daily_atr = self._atr(candles_d1, 14) if candles_d1 else 0.0
        atr_ratio = (atr_m30 / daily_atr) if daily_atr > 0 else 1.0
        range_small = (asia_range / daily_atr) < 0.40 if daily_atr > 0 and asia_range > 0 else False
        equal_levels = self._equal_liquidity_present(buy_levels, sell_levels)
        vol_contract = self._volume_contraction(candles_m30)

        accumulation = 0.0
        if session == SessionType.ASIA:
            accumulation += 0.30
        if volatility_regime == "COMPRESSION":
            accumulation += 0.25
        if atr_ratio < 0.40:
            accumulation += 0.20
        if range_small:
            accumulation += 0.15
        if equal_levels:
            accumulation += 0.05
        if vol_contract:
            accumulation += 0.05

        wick_ratio = self._last_wick_ratio(candles_m30)
        manipulation = 0.0
        if sweep_detected:
            manipulation += 0.35
        if wick_ratio > 0.40:
            manipulation += 0.20
        if sweep_trap:
            manipulation += 0.25
        if mss_detected:
            manipulation += 0.15
        if session in (SessionType.LONDON, SessionType.LONDON_NY_OVERLAP):
            manipulation += 0.05

        distribution = 0.0
        if displacement:
            distribution += 0.30
        if fvg_detected:
            distribution += 0.25
        if volatility_regime == "EXPANSION":
            distribution += 0.20
        if session in (SessionType.LONDON, SessionType.NEW_YORK, SessionType.LONDON_NY_OVERLAP):
            distribution += 0.10
        if not sweep_detected:
            distribution += 0.05
        if not vol_contract:
            distribution += 0.10

        last_phase = self._last_phase_by_pair.get(pair, AMDPhase.UNKNOWN)
        if session in (SessionType.LONDON, SessionType.LONDON_NY_OVERLAP) and last_phase == AMDPhase.ACCUMULATION:
            manipulation += 0.08
        if session == SessionType.NEW_YORK and last_phase in (AMDPhase.MANIPULATION, AMDPhase.DISTRIBUTION):
            distribution += 0.08
        if session == SessionType.ASIA:
            accumulation += 0.05

        accumulation = min(accumulation, 1.0)
        manipulation = min(manipulation, 1.0)
        distribution = min(distribution, 1.0)

        best = max(
            (AMDPhase.ACCUMULATION, accumulation),
            (AMDPhase.MANIPULATION, manipulation),
            (AMDPhase.DISTRIBUTION, distribution),
            key=lambda x: x[1],
        )

        reason = (
            f"session={session.value} atr_ratio={atr_ratio:.2f} range_small={range_small} "
            f"sweep={sweep_detected} wick={wick_ratio:.2f} displacement={displacement} fvg={fvg_detected} last={last_phase.value}"
        )

        self._last_phase_by_pair[pair] = best[0]

        return AMDPhaseResult(
            phase=best[0],
            confidence=round(best[1], 2),
            accumulation_confidence=round(accumulation, 2),
            manipulation_confidence=round(manipulation, 2),
            distribution_confidence=round(distribution, 2),
            reason=reason,
        )

    def _atr(self, candles, n: int) -> float:
        if not candles:
            return 0.0
        xs = candles[-n:] if len(candles) >= n else candles
        if not xs:
            return 0.0
        return sum((c.high - c.low) for c in xs) / len(xs)

    def _equal_liquidity_present(self, buy_levels, sell_levels) -> bool:
        return any("Equal" in x.level_type for x in buy_levels[:8]) or any("Equal" in x.level_type for x in sell_levels[:8])

    def _volume_contraction(self, candles) -> bool:
        if not candles or len(candles) < 40:
            return False
        recent = candles[-20:]
        prev = candles[-40:-20]
        r = sum(float(c.volume or 0.0) for c in recent) / max(len(recent), 1)
        p = sum(float(c.volume or 0.0) for c in prev) / max(len(prev), 1)
        return p > 0 and r < p * 0.85

    def _last_wick_ratio(self, candles) -> float:
        if not candles:
            return 0.0
        c = candles[-1]
        tr = c.high - c.low
        if tr <= 0:
            return 0.0
        uw = c.high - max(c.open, c.close)
        lw = min(c.open, c.close) - c.low
        return max(uw, lw) / tr
