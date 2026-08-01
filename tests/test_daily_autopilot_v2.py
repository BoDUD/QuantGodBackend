import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import agent_ops_health
from tools.daily_autopilot_v2 import orchestrator, report


class DailyAutopilotV2EvidenceTests(unittest.TestCase):
    def test_zero_step_cycle_is_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.object(orchestrator, "_build_steps", return_value=[]):
            payload = orchestrator.run_daily_autopilot_cycle(
                Path(temp),
                repo_root=Path(__file__).resolve().parents[1],
                write=False,
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "NOT_STARTED")
        self.assertFalse(payload["completedByAgent"])
        self.assertEqual(payload["stepCount"], 0)

    def test_top_level_report_does_not_claim_zero_step_completion(self) -> None:
        latest = {
            "status": "COMPLETED_BY_AGENT",
            "completedByAgent": True,
            "completedAtIso": "2026-08-01T00:00:00Z",
            "steps": [],
        }
        lifecycle = {"lanes": {}, "centAccount": {}, "accountRegistry": {}, "eaReproducibility": {}}
        agent = {"stage": "SHADOW", "currentPatch": {}, "autoAppliedByAgent": False}
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(report, "read_latest_run", return_value=latest),
            patch.object(report, "build_autonomous_lifecycle", return_value=lifecycle),
            patch.object(report, "build_agent_state", return_value=agent),
            patch.object(report, "_runtime_metrics", return_value={}),
            patch.object(report, "_news_gate_summary", return_value={}),
            patch.object(report, "_spread_gate_summary", return_value={}),
            patch.object(report, "_usd_deployment_gate_summary", return_value={}),
            patch.object(report, "_ga_summary", return_value={}),
            patch.object(report, "_execution_consistency_review", return_value={}),
        ):
            payload = report.build_daily_autopilot_v2(Path(temp), write=False)

        self.assertEqual(payload["status"], "NOT_STARTED")
        self.assertFalse(payload["cycleStarted"])
        self.assertFalse(payload["completedByAgent"])
        self.assertFalse(payload["autonomousAgent"]["completedByAgent"])

    def test_health_get_time_is_not_used_as_last_run(self) -> None:
        generated_report = {
            "generatedAtIso": "2099-01-01T00:00:00Z",
            "completedByAgent": True,
            "autoAppliedByAgent": True,
        }
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(agent_ops_health, "build_daily_autopilot_v2", return_value=generated_report),
            patch.object(agent_ops_health, "read_latest_run", return_value={}),
        ):
            health = agent_ops_health._daily_autopilot_health(
                Path(temp),
                Path(__file__).resolve().parents[1],
            )

        self.assertEqual(health["status"], "NOT_STARTED")
        self.assertFalse(health["cycleFound"])
        self.assertFalse(health["completedByAgent"])
        self.assertIsNone(health["lastRunAtIso"])
        self.assertEqual(health["reportGeneratedAtIso"], "2099-01-01T00:00:00Z")

    def test_health_requires_nonempty_persisted_cycle(self) -> None:
        latest = {
            "status": "COMPLETED_BY_AGENT",
            "completedByAgent": True,
            "completedAtIso": "2099-01-01T00:00:00Z",
            "steps": [],
        }
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(agent_ops_health, "build_daily_autopilot_v2", return_value={}),
            patch.object(agent_ops_health, "read_latest_run", return_value=latest),
        ):
            health = agent_ops_health._daily_autopilot_health(
                Path(temp),
                Path(__file__).resolve().parents[1],
            )

        self.assertEqual(health["status"], "NOT_STARTED")
        self.assertFalse(health["completedByAgent"])
        self.assertEqual(health["stepCount"], 0)

    def test_health_fails_closed_for_noncanonical_or_malformed_steps(self) -> None:
        latest = {
            "status": "COMPLETED_BY_AGENT",
            "completedByAgent": True,
            "completedAtIso": "2099-01-01T00:00:00Z",
            "steps": [
                {"action": "legacy_skip", "status": "SKIPPED"},
                "malformed-step",
            ],
        }
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(agent_ops_health, "build_daily_autopilot_v2", return_value={}),
            patch.object(agent_ops_health, "read_latest_run", return_value=latest),
        ):
            health = agent_ops_health._daily_autopilot_health(
                Path(temp),
                Path(__file__).resolve().parents[1],
            )

        self.assertEqual(health["status"], "BLOCKED")
        self.assertFalse(health["completedByAgent"])
        self.assertEqual(health["completedStepCount"], 0)
        self.assertEqual(health["failedSteps"], ["legacy_skip", "invalid_step_2"])


if __name__ == "__main__":
    unittest.main()
