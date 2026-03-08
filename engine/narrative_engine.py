from __future__ import annotations

from dataclasses import dataclass

from jeafx.strategy.types import NarrativeAnalysis, NarrativeEvent, SessionType


@dataclass(frozen=True)
class _Thresholds:
    sweep_lookback: int = 20
    wick_ratio_min: float = 0.45
    volume_spike_mult: float = 1.4
    inducement_window: int = 12
    inducement_break_pct: float = 0.15
    displacement_body_mult: float = 2.0
    displacement_range_mult: float = 1.8
    continuation_pullback_mult: float = 0.6


class NarrativeEngineV2:
    SWEEP_WEIGHT = 0.25
    INDUCEMENT_WEIGHT = 0.10
    DISPLACEMENT_WEIGHT = 0.35
    BOS_WEIGHT = 0.20
    CONTINUATION_WEIGHT = 0.10

    def __init__(self, thresholds: _Thresholds | None = None) -> None:
        self.t = thresholds or _Thresholds()

    def analyze(self, candles_m30, session: SessionType) -> NarrativeAnalysis:
        if not candles_m30 or len(candles_m30) < 50:
            return NarrativeAnalysis(
                events=[NarrativeEvent.NONE],
                bias="NEUTRAL",
                strength=0.0,
                sweep_detected=False,
                displacement_detected=False,
                bos_detected=False,
                inducement_detected=False,
            )

        sweep_event, sweep_dir = self.detect_liquidity_sweep(candles_m30)
        inducement = self.detect_inducement(candles_m30)
        displacement, disp_dir = self.detect_displacement(candles_m30)
        bos, bos_dir = self.detect_bos(candles_m30)
        continuation = self.detect_continuation(candles_m30, bos_dir)
        trap, trap_dir = self.detect_trap(candles_m30)

        events: list[NarrativeEvent] = []
        if sweep_event:
            events.append(NarrativeEvent.LIQUIDITY_SWEEP)
        if inducement:
            events.append(NarrativeEvent.INDUCEMENT)
        if displacement:
            events.append(NarrativeEvent.DISPLACEMENT)
        if bos:
            events.append(NarrativeEvent.BREAK_OF_STRUCTURE)
        if continuation:
            events.append(NarrativeEvent.CONTINUATION)
        if trap:
            events.append(NarrativeEvent.TRAP)
        if not events:
            events = [NarrativeEvent.NONE]

        strength = self._strength(events)
        bias = self._bias(sweep_dir, disp_dir, bos_dir, continuation, trap_dir)

        return NarrativeAnalysis(
            events=events,
            bias=bias,
            strength=round(strength, 3),
            sweep_detected=sweep_event,
            displacement_detected=displacement,
            bos_detected=bos,
            inducement_detected=inducement,
        )

    def detect_liquidity_sweep(self, candles) -> tuple[bool, str]:
        if len(candles) < self.t.sweep_lookback + 2:
            return False, "NONE"
        c = candles[-1]
        lookback = candles[-(self.t.sweep_lookback + 1):-1]
        prev_high = max(x.high for x in lookback)
        prev_low = min(x.low for x in lookback)

        avg_vol = sum(float(x.volume or 0.0) for x in candles[-21:-1]) / max(len(candles[-21:-1]), 1)
        vol_spike = float(c.volume or 0.0) > avg_vol * self.t.volume_spike_mult if avg_vol > 0 else False

        tr = c.high - c.low
        if tr <= 0:
            return False, "NONE"
        uw = c.high - max(c.open, c.close)
        lw = min(c.open, c.close) - c.low

        sweep_high = c.high > prev_high and c.close < prev_high and (uw / tr) >= self.t.wick_ratio_min
        sweep_low = c.low < prev_low and c.close > prev_low and (lw / tr) >= self.t.wick_ratio_min
        if (sweep_high or sweep_low) and (vol_spike or max(uw, lw) / tr > 0.55):
            return True, "SELL" if sweep_high else "BUY"
        return False, "NONE"

    def detect_inducement(self, candles) -> bool:
        if len(candles) < self.t.inducement_window + 3:
            return False
        window = candles[-(self.t.inducement_window + 2):-2]
        h = max(c.high for c in window)
        l = min(c.low for c in window)
        rng = h - l
        if rng <= 0:
            return False

        b = candles[-2]
        last = candles[-1]
        breakout_up = b.close > h + rng * self.t.inducement_break_pct and last.close < h
        breakout_down = b.close < l - rng * self.t.inducement_break_pct and last.close > l
        return breakout_up or breakout_down

    def detect_displacement(self, candles) -> tuple[bool, str]:
        if len(candles) < 30:
            return False, "NONE"
        last = candles[-1]
        bodies = [abs(c.close - c.open) for c in candles[-21:-1]]
        ranges = [c.high - c.low for c in candles[-21:-1]]
        avg_body = sum(bodies) / max(len(bodies), 1)
        avg_range = sum(ranges) / max(len(ranges), 1)

        body = abs(last.close - last.open)
        rng = last.high - last.low
        is_disp = (avg_body > 0 and body > self.t.displacement_body_mult * avg_body) or (
            avg_range > 0 and rng > self.t.displacement_range_mult * avg_range
        )
        if not is_disp:
            return False, "NONE"

        if last.close > last.open:
            return True, "BUY"
        return True, "SELL"

    def detect_bos(self, candles) -> tuple[bool, str]:
        if len(candles) < 45:
            return False, "NONE"
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        sh_r = max(highs[-20:])
        sl_r = min(lows[-20:])
        sh_p = max(highs[-40:-20])
        sl_p = min(lows[-40:-20])
        last = candles[-1]

        if sh_r > sh_p and sl_r > sl_p and last.close > sh_r:
            return True, "BUY"
        if sh_r < sh_p and sl_r < sl_p and last.close < sl_r:
            return True, "SELL"
        return False, "NONE"

    def detect_continuation(self, candles, trend_dir: str) -> bool:
        if trend_dir not in ("BUY", "SELL") or len(candles) < 25:
            return False
        last5 = candles[-5:]
        retr = candles[-10:-5]
        retr_range = max(c.high for c in retr) - min(c.low for c in retr)
        last_range = max(c.high for c in last5) - min(c.low for c in last5)
        if retr_range <= 0:
            return False

        pullback_ok = last_range > retr_range * self.t.continuation_pullback_mult
        if trend_dir == "BUY":
            return pullback_ok and candles[-1].close > max(c.high for c in retr)
        return pullback_ok and candles[-1].close < min(c.low for c in retr)

    def detect_trap(self, candles) -> tuple[bool, str]:
        if len(candles) < 8:
            return False, "NONE"
        prev = candles[-2]
        last = candles[-1]
        tr = max(last.high - last.low, 1e-9)
        bearish_disp = last.close < last.open and abs(last.close - last.open) > tr * 0.6
        bullish_disp = last.close > last.open and abs(last.close - last.open) > tr * 0.6

        trap_bull = prev.close > max(c.high for c in candles[-8:-2]) and bearish_disp
        trap_bear = prev.close < min(c.low for c in candles[-8:-2]) and bullish_disp
        if trap_bull:
            return True, "SELL"
        if trap_bear:
            return True, "BUY"
        return False, "NONE"

    def _strength(self, events: list[NarrativeEvent]) -> float:
        s = 0.0
        if NarrativeEvent.DISPLACEMENT in events:
            s += self.DISPLACEMENT_WEIGHT
        if NarrativeEvent.LIQUIDITY_SWEEP in events:
            s += self.SWEEP_WEIGHT
        if NarrativeEvent.BREAK_OF_STRUCTURE in events:
            s += self.BOS_WEIGHT
        if NarrativeEvent.INDUCEMENT in events:
            s += self.INDUCEMENT_WEIGHT
        if NarrativeEvent.CONTINUATION in events:
            s += self.CONTINUATION_WEIGHT
        return min(1.0, s)

    def _bias(self, sweep_dir: str, disp_dir: str, bos_dir: str, continuation: bool, trap_dir: str) -> str:
        if sweep_dir == "SELL" and disp_dir == "SELL":
            return "BEARISH"
        if sweep_dir == "BUY" and disp_dir == "BUY":
            return "BULLISH"
        if bos_dir in ("BUY", "SELL") and continuation:
            return "BULLISH" if bos_dir == "BUY" else "BEARISH"
        if trap_dir in ("BUY", "SELL"):
            return "BULLISH" if trap_dir == "BUY" else "BEARISH"
        return "NEUTRAL"
