from __future__ import annotations

import unittest

import jeafx_engine as legacy

from jeafx.config import StressLevel
from jeafx.strategy.confidence_engine import ConfidenceEngine
from jeafx.strategy.smc_engine import SMCEngine
from tests.regression._harness import as_legacy_candles, as_ref_candles, generate_ohlcv, stress_level_to_legacy, write_artifact


class ConfidenceParityTest(unittest.TestCase):
    def test_confidence_parity(self) -> None:
        rows = generate_ohlcv(220, seed=23)
        legacy_candles = as_legacy_candles(rows)
        ref_candles = as_ref_candles(rows)

        legacy_smc = legacy.SMCEngine()
        ref_smc = SMCEngine()
        legacy_conf = legacy.ConfidenceEngine()
        ref_conf = ConfidenceEngine()

        legacy_out: list[dict[str, object]] = []
        ref_out: list[dict[str, object]] = []

        rr = 3.2
        fund_score = 7
        stress = StressLevel.NONE

        for i in range(100, len(rows) - 1):
            la = legacy_smc.analyze(legacy_candles[:i], "XAUUSD", "M30")
            ra = ref_smc.analyze(ref_candles[:i], "XAUUSD", "M30")
            lc = legacy_conf.score(la, rr, fund_score, stress_level_to_legacy(stress))
            rc = ref_conf.score(ra, rr, fund_score, stress)
            legacy_out.append({"score": lc.score, "components": lc.components})
            ref_out.append({"score": rc.score, "components": rc.components})

        write_artifact("confidence.json", {"legacy": legacy_out, "refactor": ref_out})
        self.assertEqual(legacy_out, ref_out)


if __name__ == "__main__":
    unittest.main()
