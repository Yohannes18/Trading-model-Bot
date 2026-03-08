from __future__ import annotations

import filecmp
import unittest
from pathlib import Path

from tests.regression._harness import LEGACY_ROOT, REFACTOR_ROOT


class FullRegressionIntegrityTest(unittest.TestCase):
    ARTIFACTS = [
        "setups.json",
        "confidence.json",
        "trades.json",
        "stress_log.json",
        "governance.json",
    ]

    def test_full_regression_integrity(self) -> None:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        suite.addTests(loader.loadTestsFromName("tests.regression.test_setup_parity.SetupParityTest"))
        suite.addTests(loader.loadTestsFromName("tests.regression.test_confidence_parity.ConfidenceParityTest"))
        suite.addTests(loader.loadTestsFromName("tests.regression.test_risk_parity.RiskParityTest"))
        suite.addTests(loader.loadTestsFromName("tests.regression.test_stress_parity.StressParityTest"))
        suite.addTests(loader.loadTestsFromName("tests.regression.test_governance_parity.GovernanceParityTest"))

        result = unittest.TextTestRunner(verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(), "Precondition parity tests failed")

        missing: list[str] = []
        diffs: list[str] = []
        for artifact in self.ARTIFACTS:
            legacy_path = LEGACY_ROOT / artifact
            refactor_path = REFACTOR_ROOT / artifact
            if not legacy_path.exists() or not refactor_path.exists():
                missing.append(artifact)
                continue
            if not filecmp.cmp(legacy_path, refactor_path, shallow=False):
                diffs.append(artifact)

        self.assertFalse(missing, f"Missing artifact pairs: {missing}")
        self.assertFalse(diffs, f"Artifact byte mismatch: {diffs}")


if __name__ == "__main__":
    unittest.main()
