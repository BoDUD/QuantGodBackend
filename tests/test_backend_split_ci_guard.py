from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_SOURCE = (ROOT / "tools/ci_guard.py").read_text(encoding="utf-8")


class BackendSplitCiGuardTest(unittest.TestCase):
    def test_guard_no_longer_depends_on_frontend_source(self) -> None:
        stale_frontend_markers = (
            "frontend/src/App.vue",
            "routeDowngradeLabel(row)",
            "routeNextStepText(row)",
            "routeShortName(row) === route",
            "MA 已从实盘降级到模拟/候选观察",
            "保持模拟/候选观察",
        )
        for marker in stale_frontend_markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, GUARD_SOURCE)

    def test_guard_keeps_backend_safety_checks(self) -> None:
        required_backend_markers = (
            "QuantGod_MultiStrategy.mq5",
            "QuantGod_MT5_HFM_LivePilot.set",
            "tradeStatus = \"STARTUP_GUARD\";",
            "PilotRsiBlockSellInUptrend",
            "PilotRsiRangeTightBuyOnly",
            ".env.ai.local.example",
            "check_secret_file_hygiene",
            "check_backend_split_boundaries",
        )
        for marker in required_backend_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, GUARD_SOURCE)

    def test_guard_rejects_frontend_build_and_split_helpers(self) -> None:
        split_out_markers = (
            "Dashboard/vue-dist/",
            "Dashboard/QuantGod_",
            "tools/responsive_check.mjs",
            "tools/install_phase1_frontend.py",
        )
        for marker in split_out_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, GUARD_SOURCE)


if __name__ == "__main__":
    unittest.main()
