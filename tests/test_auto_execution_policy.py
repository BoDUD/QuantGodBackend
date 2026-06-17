from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.run_auto_execution_policy import cmd_sample
from tools.auto_execution_policy.policy_engine import AutoExecutionPolicyEngine
from argparse import Namespace


class AutoExecutionPolicyTests(unittest.TestCase):
    def test_opportunity_entry_when_core_passes_but_one_tactical_confirmation_missing(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            cmd_sample(Namespace(runtime_dir=str(runtime), overwrite=True))
            doc = AutoExecutionPolicyEngine(runtime).build(["USDJPYc"], directions=["LONG"], write=True)
            self.assertEqual(doc["schemaVersion"], 1)
            row = doc["policies"][0]
            self.assertEqual(row["entryMode"], "OPPORTUNITY_ENTRY")
            self.assertTrue(row["allowed"])
            self.assertGreater(row["recommendedLot"], 0)
            self.assertLessEqual(row["recommendedLot"], row["maxLot"])

    def test_negative_direction_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            cmd_sample(Namespace(runtime_dir=str(runtime), overwrite=True))
            row = AutoExecutionPolicyEngine(runtime).build_row("USDJPYc", "SHORT").to_dict()
            self.assertEqual(row["entryMode"], "BLOCKED")
            self.assertFalse(row["allowed"])
            self.assertEqual(row["recommendedLot"], 0.0)

    def test_missing_runtime_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            row = AutoExecutionPolicyEngine(td).build_row("USDJPYc", "LONG").to_dict()
            self.assertEqual(row["entryMode"], "BLOCKED")
            self.assertFalse(row["allowed"])
            self.assertTrue(any("缺少运行快照" in item for item in row["blockers"]))

    def test_policy_safety_flags_are_false(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            cmd_sample(Namespace(runtime_dir=str(runtime), overwrite=True))
            doc = AutoExecutionPolicyEngine(runtime).build(["USDJPYc"], write=True)
            self.assertFalse(doc["safety"]["orderSendAllowed"])
            self.assertFalse(doc["safety"]["writesMt5OrderRequest"])
            self.assertFalse(doc["safety"]["livePresetMutationAllowed"])

    def test_fastlane_quality_accepts_p3_7_symbol_list_payload(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            cmd_sample(Namespace(runtime_dir=str(runtime), overwrite=True))
            quality_dir = runtime / "quality"
            quality_dir.mkdir(parents=True, exist_ok=True)
            (quality_dir / "QuantGod_MT5FastLaneQuality.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.mt5.fast_lane_quality.v1",
                        "symbols": [
                            {"symbol": "EURUSDc", "quality": "DEGRADED"},
                            {"symbol": "USDJPYc", "quality": "OK", "reason": "快通道质量通过"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            row = AutoExecutionPolicyEngine(runtime).build_row("USDJPYc", "LONG").to_dict()
            self.assertFalse(any("快通道" in item for item in row["blockers"]))


if __name__ == "__main__":
    unittest.main()
