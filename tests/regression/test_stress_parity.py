from __future__ import annotations

import unittest

import quantara_engine as legacy

from quantara.stress.stress_engine import StressEngine
from tests.regression._harness import FakeDB, write_artifact


class StressParityTest(unittest.TestCase):
    def test_stress_engine_parity(self) -> None:
        sequence = [1.5, -1.0, 3.0, -1.0, -1.0, 1.5, -1.0, 3.0, -1.0, 1.5]
        equities = [10000, 9900, 10200, 10050, 9800, 9950, 9700, 10010, 9820, 10120]

        fake_legacy = FakeDB()
        original_legacy_db = legacy.db
        legacy.db = fake_legacy
        fake_ref = FakeDB()

        try:
            legacy_engine = legacy.StressEngine()
            ref_engine = StressEngine(fake_ref)  # type: ignore[arg-type]

            legacy_states: list[dict[str, object]] = []
            ref_states: list[dict[str, object]] = []

            for result_r, equity in zip(sequence, equities, strict=True):
                legacy_engine.record_result(result_r, equity)
                ref_engine.record_result(result_r, equity)

                ls = legacy_engine.evaluate(equity)
                rs = ref_engine.evaluate(equity)

                legacy_states.append(
                    {
                        "level": ls.level.value,
                        "rolling_expectancy": ls.rolling_expectancy,
                        "rolling_winrate": ls.rolling_winrate,
                        "drawdown": ls.drawdown,
                        "risk_multiplier": ls.risk_multiplier,
                    }
                )
                ref_states.append(
                    {
                        "level": rs.level.value,
                        "rolling_expectancy": rs.rolling_expectancy,
                        "rolling_winrate": rs.rolling_winrate,
                        "drawdown": rs.drawdown,
                        "risk_multiplier": rs.risk_multiplier,
                    }
                )

            write_artifact("stress_log.json", {"legacy": legacy_states, "refactor": ref_states})
            self.assertEqual(legacy_states, ref_states)
        finally:
            legacy.db = original_legacy_db


if __name__ == "__main__":
    unittest.main()
