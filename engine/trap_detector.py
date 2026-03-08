from __future__ import annotations

from jeafx.strategy.types import TrapAnalysis


class LiquidityTrapDetector:
    """Detects fake breakout / stop-hunt trap conditions."""

    def analyze(
        self,
        candles,
        sweep_detected: bool,
        displacement_detected: bool,
        nearest_liquidity_score: int,
        session: str | None = None,
        sensitivity: float = 1.0,
    ) -> TrapAnalysis:
        if not candles or len(candles) < 24:
            return TrapAnalysis(0.0, "NONE", "Insufficient candles", "LOW")

        last = candles[-1]
        ranges = [c.high - c.low for c in candles[-21:-1]]
        bodies = [abs(c.close - c.open) for c in candles[-21:-1]]
        avg_range = sum(ranges) / max(len(ranges), 1)
        avg_body = sum(bodies) / max(len(bodies), 1)
        tr = max(last.high - last.low, 1e-9)
        body = abs(last.close - last.open)
        wick = max(last.high - max(last.open, last.close), min(last.open, last.close) - last.low)
        vols = [float(c.volume or 0.0) for c in candles[-21:-1]]
        avg_vol = sum(vols) / max(len(vols), 1)

        weak_follow = body < max(avg_range * 0.45, avg_body * 0.7)
        rejection = wick / tr > 0.45
        momentum_decay = self._momentum_decay(candles)
        trend_continuation = self._strong_trend_continuation(candles)
        news_candle = tr > avg_range * 2.8 and body > avg_body * 2.6 and avg_range > 0 and avg_body > 0
        volume_spike = avg_vol > 0 and float(last.volume or 0.0) > avg_vol * 1.35

        p = 0.0
        t = "NONE"
        reason = "No trap structure"

        if not sweep_detected:
            return TrapAnalysis(0.0, "NONE", "No liquidity sweep", "LOW")

        if trend_continuation:
            return TrapAnalysis(8.0, "NONE", "Strong trend continuation", "LOW")

        if news_candle and not volume_spike:
            return TrapAnalysis(10.0, "NONE", "News expansion profile", "LOW")

        if weak_follow and momentum_decay and rejection:
            p = 52.0
            t = "STOP_HUNT_WEAK_FOLLOW"
            reason = "Sweep + weak follow-through + momentum collapse"

            if nearest_liquidity_score >= 7:
                p += 12.0
            if displacement_detected:
                p += 10.0
            if volume_spike:
                p += 8.0
            if session in ("LONDON", "LONDON_NY_OVERLAP", "NEW_YORK"):
                p += 6.0
        else:
            p = 18.0 if weak_follow or momentum_decay else 6.0
            t = "NONE"
            reason = "Sweep present but no full trap confirmation"

        p = p * max(0.5, min(1.5, sensitivity))
        p = max(0.0, min(100.0, p))
        risk = "LOW"
        if p >= 70:
            risk = "HIGH"
        elif p >= 40:
            risk = "MEDIUM"
        return TrapAnalysis(round(p, 2), t, reason, risk)

    def _momentum_decay(self, candles) -> bool:
        if len(candles) < 6:
            return False
        last3 = candles[-3:]
        ranges = [max(c.high - c.low, 1e-9) for c in last3]
        bodies = [abs(c.close - c.open) for c in last3]
        range_decay = ranges[2] < ranges[1] < ranges[0]
        body_decay = bodies[2] < bodies[1] < bodies[0]
        return range_decay or body_decay

    def _strong_trend_continuation(self, candles) -> bool:
        if len(candles) < 8:
            return False
        seq = candles[-5:]
        up_closes = all(seq[i].close >= seq[i - 1].close for i in range(1, len(seq)))
        down_closes = all(seq[i].close <= seq[i - 1].close for i in range(1, len(seq)))
        body_strength = sum(abs(c.close - c.open) for c in seq)
        range_strength = sum(max(c.high - c.low, 1e-9) for c in seq)
        directional_body = body_strength / max(range_strength, 1e-9)
        return (up_closes or down_closes) and directional_body > 0.62
