from __future__ import annotations

import unittest

import quantara_engine as legacy

from quantara.engine import calc_levels
from quantara.strategy.smc_engine import Direction, SMCEngine
from tests.regression._harness import as_legacy_candles, as_ref_candles, generate_ohlcv, write_artifact


class SetupParityTest(unittest.TestCase):
    def test_setup_detection_parity(self) -> None:
        rows = generate_ohlcv(260, seed=17)
        legacy_candles = as_legacy_candles(rows)
        ref_candles = as_ref_candles(rows)

        legacy_engine = legacy.SMCEngine()
        ref_engine = SMCEngine()

        legacy_setups: list[dict[str, object]] = []
        ref_setups: list[dict[str, object]] = []

        for i in range(100, len(rows) - 1):
            lc = legacy_candles[:i]
            rc = ref_candles[:i]

            la = legacy_engine.analyze(lc, "XAUUSD", "M30")
            ra = ref_engine.analyze(rc, "XAUUSD", "M30")

            if la.signal_direction != legacy.Direction.NONE:
                le, lsl, _, ltp2 = legacy._calc_levels(lc, la.signal_direction.value)
                legacy_setups.append(
                    {
                        "pair": "XAUUSD",
                        "direction": la.signal_direction.value,
                        "entry": round(le, 5),
                        "sl": round(lsl, 5),
                        "tp": round(ltp2, 5),
                    }
                )

            if ra.signal_direction != Direction.NONE:
                re, rsl, _, rtp2 = calc_levels(rc, ra.signal_direction.value)
                ref_setups.append(
                    {
                        "pair": "XAUUSD",
                        "direction": ra.signal_direction.value,
                        "entry": round(re, 5),
                        "sl": round(rsl, 5),
                        "tp": round(rtp2, 5),
                    }
                )

        write_artifact("setups.json", {"legacy": legacy_setups, "refactor": ref_setups})
        self.assertEqual(len(legacy_setups), len(ref_setups))
        self.assertEqual(legacy_setups, ref_setups)


if __name__ == "__main__":
    unittest.main()
