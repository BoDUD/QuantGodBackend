from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.usdjpy_autonomous_agent.agent_state import build_agent_state
from tools.usdjpy_autonomous_agent.config_patch import build_config_patch
from tools.usdjpy_autonomous_agent.promotion_gate import build_promotion_decision
from tools.usdjpy_autonomous_agent.rollback import evaluate_hard_rollback
from tools.usdjpy_walk_forward.selector import sample_walk_forward_runtime


class USDJPYAutonomousAgentTests(unittest.TestCase):
    def test_builds_stage_gated_agent_files_without_execution_rights(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            sample_walk_forward_runtime(runtime, overwrite=True)

            decision = build_promotion_decision(runtime, write=True)
            patch = build_config_patch(runtime, write=True)
            state = build_agent_state(runtime, write=True)

            self.assertEqual(decision["symbol"], "USDJPYc")
            self.assertTrue(decision["requiresAutonomousGovernance"])
            self.assertEqual(decision["safety"]["autoApplyAllowed"], "stage_gated")
            self.assertFalse(decision["safety"]["operatorApprovalRequired"])
            self.assertTrue(decision["safety"]["unattendedLiveExpansionAllowed"])
            self.assertFalse(decision["safety"]["orderSendAllowed"])
            self.assertFalse(decision["safety"]["livePresetMutationAllowed"])

            self.assertEqual(patch["schema"], "quantgod.autonomous_config_patch.v1")
            self.assertIn("patchWritable", patch)
            self.assertNotIn("patchAllowed", patch)
            self.assertEqual(patch["executionStage"], patch["stage"])
            self.assertFalse(patch["operatorApprovalRequired"])
            self.assertTrue(patch["unattendedLiveExpansionAllowed"])
            self.assertFalse(patch["liveMutationAllowed"])
            self.assertTrue(patch["completedByAgent"])
            self.assertFalse(patch["safety"]["agentMayMutateSource"])
            self.assertFalse(patch["safety"]["agentMayMutateLivePreset"])
            self.assertFalse(patch["safety"]["agentMaySendOrder"])
            self.assertLessEqual(patch["limits"]["maxLot"], 2.0)

            self.assertEqual(state["schema"], "quantgod.autonomous_agent_state.v1")
            self.assertTrue(state["requiresAutonomousGovernance"])
            self.assertTrue(state["completedByAgent"])
            self.assertNotIn("patchAllowed", state)
            self.assertIn("lanes", state)
            self.assertIn("mt5Shadow", state["lanes"])
            self.assertIn("hfmCryptoShadow", state["lanes"])
            self.assertEqual(state["centAccount"]["accountMode"], "cent")
            self.assertTrue((runtime / "agent" / "QuantGod_AutonomousPromotionDecision.json").exists())
            self.assertTrue((runtime / "agent" / "QuantGod_AutonomousConfigPatch.json").exists())
            ea_patch = runtime / "QuantGod_AutonomousConfigPatch_EA.txt"
            self.assertTrue(ea_patch.exists())
            ea_text = ea_patch.read_text(encoding="utf-8")
            self.assertIn("schema=quantgod.autonomous_config_patch_ea.v1", ea_text)
            self.assertIn("symbol=USDJPYc", ea_text)
            self.assertIn("strategy=RSI_Reversal", ea_text)
            self.assertIn("direction=LONG", ea_text)
            self.assertIn("operatorApprovalRequired=false", ea_text)
            self.assertIn("unattendedLiveExpansionAllowed=true", ea_text)
            self.assertIn("liveMutationAllowed=false", ea_text)
            self.assertIn("livePresetMutationAllowed=false", ea_text)
            self.assertIn("newsHardBypassAllowed=false", ea_text)
            self.assertIn("runtimeFreshnessBypassAllowed=false", ea_text)
            self.assertIn("fastlaneBypassAllowed=false", ea_text)
            self.assertTrue((runtime / "agent" / "QuantGod_AutonomousAgentState.json").exists())

    def test_hard_rollback_fails_closed_without_runtime_quality(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            sample_walk_forward_runtime(runtime, overwrite=True)

            rollback = evaluate_hard_rollback(runtime)

            self.assertFalse(rollback["ok"])
            self.assertTrue(any("运行快照" in item or "快通道" in item for item in rollback["hardBlockers"]))


if __name__ == "__main__":
    unittest.main()
