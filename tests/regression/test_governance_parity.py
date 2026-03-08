from __future__ import annotations

import unittest

import jeafx_engine as legacy

from jeafx.governance.governance_engine import GovernanceEngine
from jeafx.state_machine import StressState
from tests.regression._harness import FakeDB, write_artifact


class GovernanceParityTest(unittest.TestCase):
    def test_governance_parity(self) -> None:
        stress_seq = [
            legacy.StressLevel.NONE,
            legacy.StressLevel.SEVERE,
            legacy.StressLevel.NONE,
            legacy.StressLevel.SEVERE,
            legacy.StressLevel.NONE,
        ]

        fake_legacy = FakeDB()
        original_legacy_db = legacy.db
        legacy.db = fake_legacy
        fake_ref = FakeDB()

        try:
            legacy_engine = legacy.GovernanceEngine()
            ref_engine = GovernanceEngine(fake_ref)  # type: ignore[arg-type]

            legacy_states: list[dict[str, object]] = []
            ref_states: list[dict[str, object]] = []

            for level in stress_seq:
                ls = legacy_engine.evaluate(legacy.StressState(level=level))
                rs = ref_engine.evaluate(StressState(level=type(StressState().level)[level.value]))

                legacy_states.append(
                    {
                        "status": ls.status.value,
                        "can_trade": ls.can_trade,
                        "severe_count_ytd": ls.severe_count_ytd,
                        "reason": ls.reason,
                    }
                )
                ref_states.append(
                    {
                        "status": rs.status.value,
                        "can_trade": rs.can_trade,
                        "severe_count_ytd": rs.severe_count_ytd,
                        "reason": rs.reason,
                    }
                )

            write_artifact("governance.json", {"legacy": legacy_states, "refactor": ref_states})
            self.assertEqual(legacy_states, ref_states)
        finally:
            legacy.db = original_legacy_db


if __name__ == "__main__":
    unittest.main()
