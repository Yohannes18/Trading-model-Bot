from __future__ import annotations

import unittest

import jeafx_engine as legacy

from jeafx.config import StressLevel
from jeafx.database.db_manager import DatabaseManager
from jeafx.risk.position_sizer import PositionSizer
from jeafx.state_machine import StressState
from tests.regression._harness import FakeDB, write_artifact


class RiskParityTest(unittest.TestCase):
    def test_position_sizing_parity(self) -> None:
        fake_legacy = FakeDB(today_risk=1.2, open_trades=1)
        original_legacy_db = legacy.db
        legacy.db = fake_legacy
        try:
            legacy_sizer = legacy.PositionSizer()
            ref_db = DatabaseManager()
            ref_db.get_today_risk = lambda: 1.2  # type: ignore[assignment]
            ref_db.get_open_trade_count = lambda: 1  # type: ignore[assignment]
            ref_sizer = PositionSizer(ref_db)

            legacy_stress = legacy.StressState(level=legacy.StressLevel.MODERATE, risk_multiplier=0.7)
            ref_stress = StressState(level=StressLevel.MODERATE, risk_multiplier=0.7)

            lp = legacy_sizer.calculate("XAUUSD", 2312.25, 2306.75, 10000.0, legacy_stress)
            rp = ref_sizer.calculate("XAUUSD", 2312.25, 2306.75, 10000.0, ref_stress)

            payload = {
                "legacy": lp.__dict__,
                "refactor": rp.__dict__,
            }
            write_artifact("trades.json", payload)

            self.assertAlmostEqual(lp.lot_size, rp.lot_size, places=4)
            self.assertAlmostEqual(lp.risk_percent, rp.risk_percent, places=4)
            self.assertAlmostEqual(lp.adjusted_risk_percent, rp.adjusted_risk_percent, places=4)
            self.assertAlmostEqual(lp.risk_amount, rp.risk_amount, places=4)
            self.assertEqual(lp.allowed, rp.allowed)
        finally:
            legacy.db = original_legacy_db


if __name__ == "__main__":
    unittest.main()
