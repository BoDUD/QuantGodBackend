from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.hyperliquid_shadow_lane.builder import (
    build_hyperliquid_shadow_lane,
    read_hyperliquid_shadow_lane,
)


class HyperliquidShadowLaneTests(unittest.TestCase):
    def test_moss_agent_url_builds_readonly_shadow_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            report = build_hyperliquid_shadow_lane(
                runtime,
                target_agent_url="https://moss.site/agent/agt_demo_123",
                write=True,
            )

            self.assertEqual(report["schema"], "quantgod.hyperliquid_shadow_lane.v1")
            self.assertEqual(report["status"], "READY_FOR_READONLY_SIGNAL_MAPPING")
            self.assertEqual(report["targetAgent"]["agentId"], "agt_demo_123")
            self.assertEqual(report["shadowPlan"]["mode"], "READONLY_SIGNAL_MIRROR")
            self.assertEqual(report["shadowPlan"]["priceDiffProtectionPct"], 3.0)
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["walletAuthorizationAllowed"])
            self.assertFalse(report["safety"]["hyperliquidOrderSendAllowed"])

            saved = read_hyperliquid_shadow_lane(runtime)
            self.assertEqual(saved["targetAgent"]["agentId"], "agt_demo_123")

    def test_local_profile_json_adds_readonly_moss_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            profile_path = runtime / "moss_agent_profile.json"
            profile_path.write_text(json.dumps({
                "strategyName": "Range Scalper",
                "style": "short-term range",
                "metrics": {
                    "roiPct": "18.5%",
                    "maxDrawdownPct": "7.2",
                    "runtimeHours": 144,
                    "liquidations": 0,
                    "trades": 31,
                },
            }), encoding="utf-8")

            report = build_hyperliquid_shadow_lane(
                runtime,
                target_agent_url="https://moss.site/agent/agt_demo_456",
                target_agent_profile_json=str(profile_path),
                write=False,
            )

            metrics = report["targetAgent"]["metrics"]
            self.assertTrue(report["targetAgent"]["profileFound"])
            self.assertEqual(metrics["strategyName"], "Range Scalper")
            self.assertEqual(metrics["roiPct"], 18.5)
            self.assertEqual(metrics["maxDrawdownPct"], 7.2)
            self.assertEqual(metrics["liquidationCount"], 0)
            self.assertEqual(metrics["tradeCount"], 31)
            self.assertFalse(report["safety"]["walletAuthorizationAllowed"])

    def test_missing_agent_url_waits_without_execution_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_hyperliquid_shadow_lane(Path(tmp), target_agent_url="", write=False)

            self.assertEqual(report["status"], "WAITING_MOSS_AGENT_URL")
            self.assertGreaterEqual(len(report["blockers"]), 1)
            self.assertFalse(report["riskBoundary"]["autoFlattenAllowed"])
            self.assertFalse(report["safety"]["copyTradeExecutionAllowed"])


if __name__ == "__main__":
    unittest.main()
