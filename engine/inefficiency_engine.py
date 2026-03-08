from __future__ import annotations

from quantara.strategy.types import InefficiencyMap, InefficiencyZone


class MarketInefficiencyEngine:
    """Detects institutional price inefficiencies that can act as fill magnets."""

    def build_map(self, candles, current_price: float, risk_unit: float, session: str | None = None) -> InefficiencyMap:
        if not candles or len(candles) < 10:
            return InefficiencyMap([], [], None, 0.0)

        zones: list[InefficiencyZone] = []
        recent = candles[-180:] if len(candles) > 180 else candles
        avg_range = sum((c.high - c.low) for c in recent[-30:]) / max(len(recent[-30:]), 1)
        avg_vol = sum(float(c.volume or 0.0) for c in recent[-30:]) / max(len(recent[-30:]), 1)
        min_gap = max(avg_range * 0.15, 1e-9)
        session_weight = self._session_weight(session)

        for i in range(2, len(recent) - 1):
            c1 = recent[i - 1]
            c2 = recent[i]
            c3 = recent[i + 1]

            # Fair Value Gap (3-candle)
            if c1.high < c3.low:
                top = c3.low
                bottom = c1.high
                if abs(top - bottom) >= min_gap:
                    zones.append(self._zone("FVG", "BUY", top, bottom, current_price, risk_unit, avg_range, c2, avg_vol, session_weight))
            elif c1.low > c3.high:
                top = c1.low
                bottom = c3.high
                if abs(top - bottom) >= min_gap:
                    zones.append(self._zone("FVG", "SELL", top, bottom, current_price, risk_unit, avg_range, c2, avg_vol, session_weight))

            # Volume imbalance proxy: large body + underlapping wick structure
            body = abs(c2.close - c2.open)
            rng = c2.high - c2.low
            if rng > 0 and body > rng * 0.7 and avg_vol > 0 and float(c2.volume or 0.0) > avg_vol * 1.4:
                if c2.close > c2.open:
                    top = c2.high
                    bottom = max(c2.open, c2.close)
                    if abs(top - bottom) >= min_gap:
                        zones.append(self._zone("VOLUME_IMBALANCE", "BUY", top, bottom, current_price, risk_unit, avg_range, c2, avg_vol, session_weight))
                else:
                    top = min(c2.open, c2.close)
                    bottom = c2.low
                    if abs(top - bottom) >= min_gap:
                        zones.append(self._zone("VOLUME_IMBALANCE", "SELL", top, bottom, current_price, risk_unit, avg_range, c2, avg_vol, session_weight))

            # Liquidity void / displacement gap proxy
            if i >= 3:
                prev = recent[i - 2]
                gap_up = c2.low > prev.high
                gap_down = c2.high < prev.low
                if gap_up:
                    top = c2.low
                    bottom = prev.high
                    if abs(top - bottom) >= min_gap:
                        zones.append(self._zone("LIQUIDITY_VOID", "BUY", top, bottom, current_price, risk_unit, avg_range, c2, avg_vol, session_weight))
                if gap_down:
                    top = prev.low
                    bottom = c2.high
                    if abs(top - bottom) >= min_gap:
                        zones.append(self._zone("LIQUIDITY_VOID", "SELL", top, bottom, current_price, risk_unit, avg_range, c2, avg_vol, session_weight))

        dedup = self._deduplicate(zones, avg_range)
        above = sorted([z for z in dedup if z.midpoint > current_price], key=lambda z: z.midpoint)
        below = sorted([z for z in dedup if z.midpoint < current_price], key=lambda z: z.midpoint, reverse=True)

        nearest = None
        if above and below:
            nearest = min((above[0], below[0]), key=lambda z: abs(z.midpoint - current_price))
        elif above:
            nearest = above[0]
        elif below:
            nearest = below[0]

        magnet = nearest.strength if nearest else 0.0
        return InefficiencyMap(above[:10], below[:10], nearest, round(max(0.0, min(magnet, 1.0)), 3))

    def _zone(self, zone_type: str, direction: str, top: float, bottom: float, current_price: float, risk_unit: float, avg_range: float, candle, avg_vol: float, session_weight: float) -> InefficiencyZone:
        midpoint = (top + bottom) / 2
        width = abs(top - bottom)
        distance_r = abs(midpoint - current_price) / max(risk_unit, 1e-9)

        displacement_size = width / max(avg_range, 1e-9)
        volume_delta = (float(candle.volume or 0.0) / max(avg_vol, 1e-9)) if avg_vol > 0 else 0.8
        structural_cleanliness = self._structural_cleanliness(candle)
        raw_strength = displacement_size * volume_delta * session_weight * structural_cleanliness
        strength = max(0.1, min(1.0, raw_strength))
        probability = max(0.05, min(0.95, 0.65 * strength + 0.35 * (1 / (1 + distance_r))))

        return InefficiencyZone(
            type=zone_type,
            direction=direction,
            top=round(max(top, bottom), 2),
            bottom=round(min(top, bottom), 2),
            midpoint=round(midpoint, 2),
            strength=round(strength, 3),
            probability_of_fill=round(probability, 3),
            distance_r=round(distance_r, 2),
        )

    def _deduplicate(self, zones: list[InefficiencyZone], avg_range: float) -> list[InefficiencyZone]:
        if not zones:
            return []

        band = max(avg_range * 0.25, 1e-6)
        out: list[InefficiencyZone] = []
        for z in sorted(zones, key=lambda x: x.midpoint):
            if not out:
                out.append(z)
                continue
            prev = out[-1]
            same_side = prev.direction == z.direction and prev.type == z.type
            if same_side and abs(prev.midpoint - z.midpoint) < band:
                out[-1] = InefficiencyZone(
                    type=prev.type,
                    direction=prev.direction,
                    top=round(max(prev.top, z.top), 2),
                    bottom=round(min(prev.bottom, z.bottom), 2),
                    midpoint=round((max(prev.top, z.top) + min(prev.bottom, z.bottom)) / 2, 2),
                    strength=round(min(1.0, max(prev.strength, z.strength) * 1.05), 3),
                    probability_of_fill=round(min(0.95, max(prev.probability_of_fill, z.probability_of_fill)), 3),
                    distance_r=round(min(prev.distance_r, z.distance_r), 2),
                )
            else:
                out.append(z)
        return out

    def _structural_cleanliness(self, candle) -> float:
        tr = max(candle.high - candle.low, 1e-9)
        body = abs(candle.close - candle.open)
        return max(0.5, min(1.2, body / tr + 0.35))

    def _session_weight(self, session: str | None) -> float:
        key = (session or "").upper()
        if key == "ASIA":
            return 0.6
        if key == "LONDON":
            return 1.0
        if key in ("NEW_YORK", "LONDON_NY_OVERLAP"):
            return 0.9
        return 0.8
