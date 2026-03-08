from __future__ import annotations

from dataclasses import dataclass

from quantara.strategy.types import AMDPhase, LiquidityRaidPrediction, LiquidityZone, SessionType, VolatilityAnalysis


@dataclass(frozen=True)
class RaidScoringConfig:
    weight_strength: float = 0.35
    weight_distance: float = 0.20
    weight_narrative: float = 0.20
    weight_path: float = 0.15
    weight_session: float = 0.10
    min_probability: float = 0.40


class LiquidityRaidPredictor:
    def __init__(self, config: RaidScoringConfig | None = None) -> None:
        self.cfg = config or RaidScoringConfig()

    def predict(
        self,
        current_price: float,
        zones_above: list[LiquidityZone],
        zones_below: list[LiquidityZone],
        narrative,
        amd_phase: AMDPhase,
        volatility: VolatilityAnalysis,
        session: SessionType,
        risk_unit: float,
    ) -> LiquidityRaidPrediction:
        if amd_phase == AMDPhase.ACCUMULATION:
            return self._empty_prediction("Next Session")

        candidates = zones_above + zones_below
        if not candidates:
            return self._empty_prediction(self._time_window(session, volatility))

        ranked: list[tuple[float, LiquidityZone, float, bool]] = []
        for zone in candidates:
            raid_direction = "UP" if zone.price > current_price else "DOWN"
            distance_r = abs(zone.price - current_price) / max(risk_unit, 1e-9)
            path_clear = self._path_clear(current_price, zone, zones_above, zones_below)

            strength_score = self.score_liquidity_strength(zone)
            distance_score = self.score_distance(distance_r)
            narrative_score = self.score_narrative_alignment(zone, raid_direction, narrative, amd_phase)
            path_score = self.score_path_clarity(path_clear)
            session_score = self.score_session_alignment(zone, raid_direction, session, narrative)

            raid_score = (
                self.cfg.weight_strength * strength_score
                + self.cfg.weight_distance * distance_score
                + self.cfg.weight_narrative * narrative_score
                + self.cfg.weight_path * path_score
                + self.cfg.weight_session * session_score
            )

            if not path_clear:
                raid_score *= 0.5

            if volatility.regime.value == "EXPANSION":
                raid_score *= 1.08
            elif volatility.regime.value == "COMPRESSION":
                raid_score *= 0.80

            ranked.append((max(0.0, min(raid_score, 1.0)), zone, distance_r, path_clear))

        ranked.sort(key=lambda x: x[0], reverse=True)
        best_score, best_zone, distance_r, path_clear = ranked[0]
        return LiquidityRaidPrediction(
            target_zone=best_zone,
            raid_direction="UP" if best_zone.price > current_price else "DOWN",
            probability=round(best_score, 3),
            distance_r=round(distance_r, 2),
            path_clear=path_clear,
            estimated_time_window=self._time_window(session, volatility),
        )

    def score_liquidity_strength(self, zone: LiquidityZone) -> float:
        return max(0.0, min(zone.score / 10.0, 1.0))

    def score_distance(self, distance_r: float) -> float:
        return 1.0 / (1.0 + max(distance_r, 0.0))

    def score_narrative_alignment(self, zone: LiquidityZone, raid_direction: str, narrative, amd_phase: AMDPhase) -> float:
        score = 0.5
        bias = getattr(narrative, "bias", "NEUTRAL")
        events = getattr(narrative, "events", [])

        if bias == "BULLISH" and raid_direction == "UP":
            score += 0.3
        if bias == "BEARISH" and raid_direction == "DOWN":
            score += 0.3

        event_names = {getattr(e, "value", str(e)) for e in events}
        if "LIQUIDITY_SWEEP" in event_names:
            score += 0.1
        if "DISPLACEMENT" in event_names and "BREAK_OF_STRUCTURE" in event_names:
            score += 0.15
        if "TRAP" in event_names:
            score += 0.1 if raid_direction == "DOWN" and bias == "BEARISH" else 0.0

        if amd_phase == AMDPhase.MANIPULATION:
            score += 0.1
        elif amd_phase == AMDPhase.DISTRIBUTION:
            score += 0.05

        return max(0.0, min(score, 1.0))

    def score_path_clarity(self, path_clear: bool) -> float:
        return 1.0 if path_clear else 0.5

    def score_session_alignment(self, zone: LiquidityZone, raid_direction: str, session: SessionType, narrative) -> float:
        bias = getattr(narrative, "bias", "NEUTRAL")
        zone_t = zone.zone_type
        if session == SessionType.LONDON:
            if raid_direction == "UP" and ("AsiaHigh" in zone_t or "EqualHighs" in zone_t):
                return 1.0
            if raid_direction == "DOWN" and ("AsiaLow" in zone_t or "EqualLows" in zone_t):
                return 0.8
            return 0.6
        if session in (SessionType.NEW_YORK, SessionType.LONDON_NY_OVERLAP):
            if bias == "BEARISH" and raid_direction == "DOWN":
                return 0.9
            if bias == "BULLISH" and raid_direction == "UP":
                return 0.9
            return 0.65
        if session == SessionType.ASIA:
            return 0.45
        return 0.5

    def _path_clear(self, current_price: float, target: LiquidityZone, zones_above: list[LiquidityZone], zones_below: list[LiquidityZone]) -> bool:
        blocker_threshold = 7
        if target.price > current_price:
            blockers = [z for z in zones_above if current_price < z.price < target.price and z.score >= blocker_threshold]
        else:
            blockers = [z for z in zones_below if target.price < z.price < current_price and z.score >= blocker_threshold]
        return len(blockers) == 0

    def _time_window(self, session: SessionType, volatility: VolatilityAnalysis) -> str:
        if session == SessionType.LONDON and volatility.regime.value == "EXPANSION":
            return "London Killzone"
        if session in (SessionType.NEW_YORK, SessionType.LONDON_NY_OVERLAP) and volatility.regime.value == "EXPANSION":
            return "New York Expansion"
        if session == SessionType.LONDON:
            return "London Session"
        if session == SessionType.NEW_YORK:
            return "New York Session"
        return "Next Session"

    def _empty_prediction(self, time_window: str) -> LiquidityRaidPrediction:
        return LiquidityRaidPrediction(
            target_zone=LiquidityZone(0.0, 0, "NONE", 0.0, "NONE", "LOW"),
            raid_direction="NONE",
            probability=0.0,
            distance_r=0.0,
            path_clear=False,
            estimated_time_window=time_window,
        )
