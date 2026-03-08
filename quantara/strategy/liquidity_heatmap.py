from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .types import LiquidityBias, LiquidityZone


@dataclass
class HeatmapResult:
    zones_above: list[LiquidityZone]
    zones_below: list[LiquidityZone]
    nearest_above: LiquidityZone | None
    nearest_below: LiquidityZone | None
    bias: LiquidityBias


class LiquidityHeatmapEngine:
    WEIGHTS = {
        "EqualHighs": 3,
        "EqualLows": 3,
        "AsiaHigh": 2,
        "AsiaLow": 2,
        "LondonHigh": 2,
        "LondonLow": 2,
        "NYHigh": 2,
        "NYLow": 2,
        "DailyHigh": 3,
        "DailyLow": 3,
        "WeeklyHigh": 4,
        "WeeklyLow": 4,
        "FVG": 2,
        "OrderBlock": 2,
    }

    def build(self, current_price: float, base_buy_levels, base_sell_levels, candles_m30, candles_d1, fvg_low: float, fvg_high: float, ob_low: float, ob_high: float) -> HeatmapResult:
        above: list[LiquidityZone] = []
        below: list[LiquidityZone] = []

        def add_zone(price: float, zone_type: str) -> None:
            if price <= 0:
                return
            distance = abs(price - current_price)
            direction = "ABOVE" if price > current_price else "BELOW"
            score = self.WEIGHTS.get(zone_type, 1)
            strength = self._strength(score)
            zone = LiquidityZone(round(price, 2), score, zone_type, round(distance, 2), direction, strength)
            (above if direction == "ABOVE" else below).append(zone)

        for lv in base_sell_levels:
            add_zone(lv.price, lv.level_type)
        for lv in base_buy_levels:
            add_zone(lv.price, lv.level_type)

        london_h, london_l, ny_h, ny_l = self._session_levels(candles_m30)
        add_zone(london_h, "LondonHigh")
        add_zone(london_l, "LondonLow")
        add_zone(ny_h, "NYHigh")
        add_zone(ny_l, "NYLow")

        if len(candles_d1) >= 2:
            pd = candles_d1[-2]
            add_zone(pd.high, "DailyHigh")
            add_zone(pd.low, "DailyLow")
        if len(candles_d1) >= 5:
            week = candles_d1[-5:]
            add_zone(max(c.high for c in week), "WeeklyHigh")
            add_zone(min(c.low for c in week), "WeeklyLow")

        if fvg_low > 0 and fvg_high > 0 and fvg_high > fvg_low:
            add_zone(fvg_low, "FVG")
            add_zone(fvg_high, "FVG")

        if ob_low > 0 and ob_high > 0 and ob_high > ob_low:
            add_zone(ob_low, "OrderBlock")
            add_zone(ob_high, "OrderBlock")

        above = self._merge_and_sort(above, ascending=True)
        below = self._merge_and_sort(below, ascending=False)

        buy_total = sum(z.score for z in below)
        sell_total = sum(z.score for z in above)
        bias = LiquidityBias.NEUTRAL
        if buy_total > sell_total * 1.2:
            bias = LiquidityBias.BUY_SIDE
        elif sell_total > buy_total * 1.2:
            bias = LiquidityBias.SELL_SIDE

        nearest_above = above[0] if above else None
        nearest_below = below[0] if below else None
        return HeatmapResult(above[:12], below[:12], nearest_above, nearest_below, bias)

    def pick_target(self, direction: str, current_price: float, stop_loss: float, zones_above: list[LiquidityZone], zones_below: list[LiquidityZone], min_score: int = 5) -> tuple[LiquidityZone | None, float, bool]:
        risk = abs(current_price - stop_loss)
        if risk <= 0:
            return None, 0.0, False
        candidates = zones_above if direction == "BUY" else zones_below
        candidates = [z for z in candidates if z.score >= min_score]
        if not candidates:
            return None, 0.0, False

        target = candidates[0]
        distance_r = abs(target.price - current_price) / risk
        path_clear = self.path_clear(direction, current_price, target.price, zones_above, zones_below, blocker_score=5)
        return target, round(distance_r, 2), path_clear

    def path_clear(self, direction: str, entry: float, target: float, zones_above: list[LiquidityZone], zones_below: list[LiquidityZone], blocker_score: int = 5) -> bool:
        if direction == "BUY":
            blockers = [z for z in zones_above if entry < z.price < target and z.score >= blocker_score]
        else:
            blockers = [z for z in zones_below if target < z.price < entry and z.score >= blocker_score]
        return len(blockers) == 0

    def _merge_and_sort(self, zones: list[LiquidityZone], ascending: bool) -> list[LiquidityZone]:
        merged: dict[float, LiquidityZone] = {}
        for z in zones:
            key = round(z.price, 2)
            if key not in merged:
                merged[key] = z
                continue
            prev = merged[key]
            merged[key] = LiquidityZone(
                price=prev.price,
                score=prev.score + z.score,
                zone_type=f"{prev.zone_type}+{z.zone_type}",
                distance=min(prev.distance, z.distance),
                direction=prev.direction,
                strength=self._strength(prev.score + z.score),
            )
        return sorted(merged.values(), key=lambda x: x.price, reverse=not ascending)

    def _strength(self, score: int) -> str:
        if score >= 7:
            return "HIGH"
        if score >= 5:
            return "MEDIUM"
        return "LOW"

    def _session_levels(self, candles_m30) -> tuple[float, float, float, float]:
        if not candles_m30:
            return 0.0, 0.0, 0.0, 0.0
        now_date = datetime.now(tz=timezone.utc).date()
        london = [c for c in candles_m30 if c.time.date() == now_date and 6 <= c.time.hour < 13]
        ny = [c for c in candles_m30 if c.time.date() == now_date and 13 <= c.time.hour < 21]
        london_h = max((c.high for c in london), default=0.0)
        london_l = min((c.low for c in london), default=0.0)
        ny_h = max((c.high for c in ny), default=0.0)
        ny_l = min((c.low for c in ny), default=0.0)
        return london_h, london_l, ny_h, ny_l
