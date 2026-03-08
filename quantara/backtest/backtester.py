from __future__ import annotations

import json
from pathlib import Path

from ..config import CONFIDENCE_MIN, MIN_RR, StressLevel, log
from ..engine import calc_levels
from ..execution.mt5_executor import MT5Executor
from ..strategy.confidence_engine import ConfidenceEngine
from ..strategy.fundamental_filter import FundamentalFilter
from ..strategy.smc_engine import Direction, SMCEngine


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


class Backtester:
    def __init__(self, mt5: MT5Executor) -> None:
        self._smc = SMCEngine()
        self._conf = ConfidenceEngine()
        self._fund = FundamentalFilter()
        self._mt5 = mt5

    _DEFAULT_CANDLES_BY_TF: dict[str, int] = {
        "D1": 1500,
        "H4": 3000,
        "H1": 8000,
        "M30": 15000,
    }

    def run(
        self,
        pair: str = "XAUUSD",
        tf: str = "M30",
        n_candles: int | None = None,
        *,
        debug: bool = False,
        loose_mode: bool = False,
    ) -> None:
        candle_count = n_candles if n_candles and n_candles > 0 else self._DEFAULT_CANDLES_BY_TF.get(tf.upper(), 500)
        min_rr = 2.0 if loose_mode else MIN_RR
        confidence_min = 55 if loose_mode else CONFIDENCE_MIN

        log.info(
            "backtest_start pair=%s tf=%s candles=%s debug=%s loose_mode=%s min_rr=%.1f confidence_min=%s",
            pair,
            tf,
            candle_count,
            debug,
            loose_mode,
            min_rr,
            confidence_min,
        )
        candles = self._mt5.get_candles(pair, tf, candle_count)

        results: list[dict[str, object]] = []
        window = 100
        rejected_no_signal = 0
        rejected_rr = 0
        rejected_confidence = 0
        signal_candidates = 0

        for i in range(window, len(candles) - 10):
            chunk = candles[:i]
            analysis = self._smc.analyze(chunk, pair, tf)

            if debug:
                log.info(
                    "backtest_stage idx=%s direction=%s score=%s confluences=%s equal_highs=%s equal_lows=%s tol=%.4f",
                    i,
                    analysis.signal_direction.value,
                    analysis.score,
                    len(analysis.confluences),
                    analysis.equal_highs,
                    analysis.equal_lows,
                    analysis.equal_level_tolerance,
                )

            if analysis.signal_direction == Direction.NONE:
                rejected_no_signal += 1
                continue
            signal_candidates += 1

            entry, sl, _tp1, tp2 = calc_levels(chunk, analysis.signal_direction.value)
            rr = round(abs(tp2 - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0
            if rr < min_rr:
                rejected_rr += 1
                if debug:
                    log.info("backtest_reject idx=%s reason=rr rr=%.2f min_rr=%.2f", i, rr, min_rr)
                continue

            confidence = self._conf.score(analysis, rr, 5, StressLevel.NONE)
            passed_confidence = confidence.score >= confidence_min
            if not passed_confidence:
                rejected_confidence += 1
                if debug:
                    log.info(
                        "backtest_reject idx=%s reason=confidence score=%s min=%s components=%s",
                        i,
                        confidence.score,
                        confidence_min,
                        confidence.components,
                    )
                continue

            future = candles[i : i + 10]
            outcome = self._simulate(analysis.signal_direction.value, entry, sl, tp2, future)
            results.append(
                {
                    "pair": pair,
                    "tf": tf,
                    "direction": analysis.signal_direction.value,
                    "confidence": confidence.score,
                    "rr": rr,
                    "outcome": outcome,
                    "time": chunk[-1].time.isoformat(),
                }
            )

        if not results:
            log.info(
                "backtest_diagnostics tf=%s total_windows=%s signal_candidates=%s rejected_no_signal=%s rejected_rr=%s rejected_confidence=%s",
                tf,
                max(0, len(candles) - 10 - window),
                signal_candidates,
                rejected_no_signal,
                rejected_rr,
                rejected_confidence,
            )
            log.info("backtest_no_setups")
            return

        wins = [r for r in results if _to_float(r.get("outcome"), 0.0) > 0]
        losses = [r for r in results if _to_float(r.get("outcome"), 0.0) <= 0]
        wr = len(wins) / len(results)
        avg_win = sum(_to_float(r.get("outcome"), 0.0) for r in wins) / len(wins) if wins else 0.0
        avg_loss = sum(_to_float(r.get("outcome"), 0.0) for r in losses) / len(losses) if losses else 0.0
        expectancy = wr * avg_win - (1 - wr) * abs(avg_loss)

        print("\n" + "═" * 50)
        print(f"  BACKTEST RESULTS — {pair} {tf}")
        print("═" * 50)
        print(f"  Setups found:    {len(results)}")
        print(f"  Win rate:        {wr:.1%}")
        print(f"  Avg win:         {avg_win:.2f}R")
        print(f"  Avg loss:        {avg_loss:.2f}R")
        print(f"  Expectancy:      {expectancy:.3f}R")
        print(f"  Total R:         {sum(_to_float(r.get('outcome'), 0.0) for r in results):.2f}R")
        print("═" * 50 + "\n")

        Path("data/backtest_results.json").write_text(json.dumps(results, indent=2, default=str))
        log.info("backtest_saved path=data/backtest_results.json")

    def _simulate(self, direction: str, entry: float, sl: float, tp: float, future) -> float:
        for candle in future:
            if direction == "BUY":
                if candle.low <= sl:
                    return -1.0
                if candle.high >= tp:
                    return round(abs(tp - entry) / abs(entry - sl), 2)
            else:
                if candle.high >= sl:
                    return -1.0
                if candle.low <= tp:
                    return round(abs(entry - tp) / abs(sl - entry), 2)
        return 0.0
