import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CONTRACT_FILES = (
    "tools/autonomous_lifecycle/account_registry.py",
    "tools/autonomous_lifecycle/cent_account_rules.py",
    "tools/autonomous_lifecycle/lifecycle.py",
    "tools/autonomous_lifecycle/mt5_shadow_lane.py",
    "tools/daily_autopilot_v2/orchestrator.py",
    "tools/daily_autopilot_v2/report.py",
    "tools/live_automation_readiness/schema.py",
    "tools/usdjpy_autonomous_agent/agent_state.py",
    "tools/usdjpy_autonomous_agent/config_patch.py",
    "tools/usdjpy_autonomous_agent/promotion_gate.py",
    "tools/usdjpy_autonomous_agent/schema.py",
    "tools/usdjpy_runtime_dataset/schema.py",
    "tools/usdjpy_strategy_lab/policy_builder.py",
    "tools/usdjpy_strategy_lab/schema.py",
    "tools/usdjpy_walk_forward/schema.py",
    "tools/usdjpy_walk_forward/selector.py",
)


class ShadowReadOnlyContractTests(unittest.TestCase):
    def test_active_contracts_do_not_publish_unattended_live_permissions(self) -> None:
        for relative_path in ACTIVE_CONTRACT_FILES:
            source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(file=relative_path):
                self.assertNotRegex(source, r'["\']operatorApprovalRequired["\']\s*:\s*False')
                self.assertNotRegex(source, r'["\']unattendedLiveExpansionAllowed["\']\s*:\s*True')
                self.assertNotRegex(source, r'["\']liveExpansionAllowed["\']\s*:\s*True')
                self.assertRegex(source, r'["\']operatorApprovalRequired["\']')
                self.assertRegex(source, r'["\']liveExpansionAllowed["\']')

    def test_ea_rejects_live_stage_patch_under_active_contract(self) -> None:
        source = (REPO_ROOT / "MQL5/Experts/QuantGod_MultiStrategy.mq5").read_text(encoding="utf-8")
        self.assertIn('AutonomousPatchAddRejectedField("executionStage_live_disabled"', source)
        self.assertNotIn("g_autonomousPatchRuntimeActive = true;", source)
        self.assertNotIn('g_autonomousPatchStatus = "PATCH_ACTIVE";', source)
        self.assertIn('"operatorApprovalRequired\\":true', source)
        self.assertIn('"unattendedLiveExpansionAllowed\\":false', source)
        self.assertIn('"liveExpansionAllowed\\":false', source)

    def test_ea_news_calendar_is_fail_closed_for_trading_readiness(self) -> None:
        source = (REPO_ROOT / "MQL5/Experts/QuantGod_MultiStrategy.mq5").read_text(encoding="utf-8")
        refresh_start = source.index("void RefreshNewsFilterState")
        no_calendar_start = source.index("if(ArraySize(g_usdTrackedEventIds) == 0)", refresh_start)
        no_calendar_end = source.index("g_newsState.calendarAvailable = true", no_calendar_start)
        no_calendar_block = source[no_calendar_start:no_calendar_end]
        self.assertIn('g_newsState.status = "NO_CALENDAR"', no_calendar_block)
        self.assertIn("g_newsState.blocked = true", no_calendar_block)

        gate_start = source.index("bool PilotNewsBlocksSymbol")
        gate_end = source.index("bool IsDisplaySafeAscii", gate_start)
        gate_body = source[gate_start:gate_end]
        self.assertIn("!EnablePilotNewsFilter", gate_body)
        self.assertIn("!g_newsState.calendarAvailable", gate_body)
        self.assertIn("return true", gate_body)
        self.assertIn("trading readiness fails closed", gate_body)

        self.assertIn("bool tradingReady = EnablePilotNewsFilter && calendarAvailable && !g_newsState.blocked", source)
        self.assertIn("tradePermissionsAllowed && !g_pilotKillSwitch && !newsTradingBlocked", source)


if __name__ == "__main__":
    unittest.main()
