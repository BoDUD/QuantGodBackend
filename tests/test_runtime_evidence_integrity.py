from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.runtime_evidence_integrity.report import build_core_evidence_manifest


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_complete_runtime(runtime_dir: Path) -> None:
    write_json(
        runtime_dir / "live" / "QuantGod_USDJPYLiveLoopStatus.json",
        {"schema": "quantgod.usdjpy_live_loop_status.v1", "generatedAt": "2026-06-01T00:00:00Z"},
    )
    write_text(
        runtime_dir / "live" / "QuantGod_USDJPYLiveLoopLedger.csv",
        "generatedAt,state\n2026-06-01T00:00:00Z,EVIDENCE_MISSING\n",
    )
    write_json(
        runtime_dir / "agent" / "QuantGod_ProductionExecutionPolicy.json",
        {"schema": "quantgod.production_execution_policy.v1", "version": 1, "status": "BLOCKED"},
    )
    write_json(
        runtime_dir / "adaptive" / "QuantGod_AutoExecutionPolicy.json",
        {"schema": "quantgod.usdjpy_auto_execution_policy.v1", "generatedAt": "2026-06-01T00:00:00Z"},
    )
    write_text(
        runtime_dir / "adaptive" / "QuantGod_AutoExecutionPolicyLedger.csv",
        "generatedAt,symbol,entryMode\n2026-06-01T00:00:00Z,USDJPYc,BLOCKED\n",
    )
    write_json(
        runtime_dir / "ga_factory" / "QuantGod_GAFactoryArtifactManifest.json",
        {
            "schema": "quantgod.strategy_ga_factory.artifact_manifest.v1",
            "schemaVersion": 1,
            "artifacts": [{"artifactId": "state", "exists": True, "sha256": "abc"}],
        },
    )
    write_json(
        runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json",
        {
            "schema": "quantgod.usdjpy_history_production_status.v1",
            "status": "PASS",
            "historyTargetSatisfied": True,
            "timeframes": {
                timeframe: {"passed": True, "spanOk": True, "densityOk": True, "freshnessOk": True}
                for timeframe in ("M1", "M5", "M15", "H1")
            },
        },
    )
    write_json(
        runtime_dir / "execution" / "QuantGod_LiveExecutionQualityReport.json",
        {"schema": "quantgod.live_execution_quality_report.v1", "sampleCount": 1},
    )
    write_text(
        runtime_dir / "execution" / "QuantGod_LiveExecutionFeedback.jsonl",
        json.dumps({"schema": "quantgod.execution_feedback.v1", "feedbackId": "F-001"}) + "\n",
    )
    write_json(
        runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json",
        {
            "schema": "quantgod.case_memory_strategy_candidate_report.v1",
            "candidateCount": 6,
            "gaSeedCount": 6,
            "caseSummary": {
                "caseTypeCounts": {
                    "BAD_ENTRY": 1,
                    "MISSED_OPPORTUNITY": 1,
                    "EARLY_EXIT": 1,
                    "SPREAD_DAMAGE": 1,
                    "NEWS_DAMAGE": 1,
                    "GA_OVERFIT": 1,
                },
                "cases": [
                    {"type": "BAD_ENTRY"},
                    {"type": "MISSED_OPPORTUNITY"},
                    {"type": "EARLY_EXIT"},
                    {"type": "SPREAD_DAMAGE"},
                    {"type": "NEWS_DAMAGE"},
                    {"type": "GA_OVERFIT"},
                ],
            },
            "candidates": [{"caseType": "BAD_ENTRY"}],
            "gaSeeds": [{"caseType": "GA_OVERFIT"}],
        },
    )
    write_text(
        runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidateLedger.jsonl",
        json.dumps({"schema": "quantgod.case_memory_strategy_candidate_ledger.v1", "candidateId": "CM-001"}) + "\n",
    )
    write_json(
        runtime_dir / "case_memory" / "QuantGod_CaseMemoryArtifactManifest.json",
        {
            "schema": "quantgod.case_memory_artifact_manifest.v1",
            "schemaVersion": 1,
            "artifacts": [
                {
                    "artifactId": "candidateReport",
                    "path": "case_memory/QuantGod_CaseMemoryStrategyCandidates.json",
                    "exists": True,
                    "sha256": "def",
                },
                {
                    "artifactId": "candidateLedger",
                    "path": "case_memory/QuantGod_CaseMemoryStrategyCandidateLedger.jsonl",
                    "exists": True,
                    "sha256": "ghi",
                },
            ],
        },
    )
    write_json(
        runtime_dir / "production_validation" / "QuantGod_ProductionEvidenceValidationReport.json",
        {"schema": "quantgod.production_evidence_validation.v1", "status": "WARN"},
    )


class RuntimeEvidenceIntegrityTests(unittest.TestCase):
    def test_complete_core_evidence_manifest_hashes_every_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)

            manifest = build_core_evidence_manifest(runtime_dir, write=True)

            self.assertEqual(manifest["schema"], "quantgod.core_runtime_evidence_manifest.v1")
            self.assertEqual(manifest["schemaVersion"], 1)
            self.assertEqual(manifest["status"], "PASS")
            self.assertTrue(manifest["ok"])
            self.assertTrue(manifest["promotionGatePassed"])
            self.assertEqual(manifest["promotionGateStatus"], "PASS")
            self.assertEqual(manifest["promotionRecoveryQueueCount"], 0)
            self.assertEqual(manifest["promotionRecoveryQueue"], [])
            self.assertFalse(manifest["safety"]["orderSendAllowed"])
            self.assertEqual(manifest["hashAlgorithm"], "sha256")
            self.assertEqual(manifest["artifactCount"], 11)
            self.assertIn("historyProductionStatus", {row["artifactId"] for row in manifest["artifacts"]})
            case_memory_row = next(row for row in manifest["artifacts"] if row["artifactId"] == "caseMemoryArtifactManifest")
            self.assertEqual(case_memory_row["promotionGate"]["status"], "PASS")
            self.assertEqual(case_memory_row["promotionGate"]["missingCategories"], [])
            for row in manifest["artifacts"]:
                self.assertEqual(row["status"], "PASS", row)
                self.assertEqual(row["hashAlgorithm"], "sha256")
                self.assertTrue(row["sha256"], row)
                self.assertFalse(row["path"].startswith("/"), row["path"])
                self.assertEqual(
                    row["sha256"],
                    hashlib.sha256((runtime_dir / row["path"]).read_bytes()).hexdigest(),
                )
            self.assertTrue((runtime_dir / "integrity" / "QuantGod_CoreRuntimeEvidenceManifest.json").exists())

    def test_legacy_quantgod_absolute_path_blocks_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "agent" / "QuantGod_ProductionExecutionPolicy.json",
                {
                    "schema": "quantgod.production_execution_policy.v1",
                    "legacyPath": "/Users/bowen/Desktop/Quard/" + "QuantGod/runtime/old.json",
                },
            )

            manifest = build_core_evidence_manifest(runtime_dir)

            self.assertEqual(manifest["status"], "FAIL")
            self.assertIn(
                "productionExecutionPolicy:legacy_quantgod_absolute_path",
                manifest["blockers"],
            )

    def test_missing_required_core_artifact_blocks_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            (runtime_dir / "execution" / "QuantGod_LiveExecutionFeedback.jsonl").unlink()

            manifest = build_core_evidence_manifest(runtime_dir)

            self.assertEqual(manifest["status"], "FAIL")
            self.assertIn("executionFeedbackLedger:missing_required_artifact", manifest["blockers"])

    def test_missing_history_production_status_blocks_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            (runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json").unlink()

            manifest = build_core_evidence_manifest(runtime_dir)

            self.assertEqual(manifest["status"], "FAIL")
            self.assertIn("historyProductionStatus:missing_required_artifact", manifest["blockers"])

    def test_stale_history_blocks_promotion_gate_without_failing_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json",
                {
                    "schema": "quantgod.usdjpy_history_production_status.v1",
                    "status": "WARN",
                    "historyTargetSatisfied": False,
                    "timeframes": {
                        "M1": {"passed": False, "spanOk": True, "densityOk": True, "freshnessOk": False},
                        "M5": {"passed": True, "spanOk": True, "densityOk": True, "freshnessOk": True},
                        "M15": {"passed": True, "spanOk": True, "densityOk": True, "freshnessOk": True},
                        "H1": {"passed": True, "spanOk": True, "densityOk": True, "freshnessOk": True},
                    },
                },
            )

            manifest = build_core_evidence_manifest(runtime_dir)
            history_row = next(row for row in manifest["artifacts"] if row["artifactId"] == "historyProductionStatus")

            self.assertEqual(manifest["status"], "PASS")
            self.assertTrue(manifest["ok"])
            self.assertFalse(manifest["promotionGatePassed"])
            self.assertEqual(manifest["promotionGateStatus"], "BLOCKED")
            self.assertIn("historyProductionStatus:history_status_not_pass", manifest["promotionBlockers"])
            self.assertIn("historyProductionStatus:M1:freshness_not_ok", manifest["promotionBlockers"])
            self.assertEqual(manifest["promotionRecoveryQueueCount"], 1)
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["kind"], "history_freshness")
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["artifactId"], "historyProductionStatus")
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["timeframe"], "M1")
            self.assertIn("ORDER_SEND", manifest["promotionRecoveryQueue"][0]["forbiddenSideEffects"])
            self.assertEqual(history_row["status"], "PASS")
            self.assertEqual(history_row["promotionGate"]["status"], "BLOCKED")
            self.assertIn("ga_promotion", history_row["promotionGate"]["requiredFor"])
            self.assertEqual(history_row["promotionGate"]["staleTimeframes"], ["M1"])
            recovery_row = history_row["promotionGate"]["freshnessRecoveryQueue"][0]
            self.assertEqual(recovery_row["timeframe"], "M1")
            self.assertEqual(recovery_row["status"], "FRESHNESS_STALE")
            self.assertEqual(recovery_row["priority"], "HIGH")
            self.assertIn("sync-klines", recovery_row["refreshCommand"])
            self.assertIn("production-status", recovery_row["verifyCommand"])
            self.assertIn("freshnessOk=true", recovery_row["acceptanceZh"])
            self.assertIn("ORDER_SEND", recovery_row["forbiddenSideEffects"])

    def test_missing_required_history_timeframe_blocks_promotion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json",
                {
                    "schema": "quantgod.usdjpy_history_production_status.v1",
                    "status": "PASS",
                    "historyTargetSatisfied": True,
                    "timeframes": {
                        "M1": {"passed": True, "spanOk": True, "densityOk": True, "freshnessOk": True},
                        "M5": {"passed": True, "spanOk": True, "densityOk": True, "freshnessOk": True},
                        "M15": {"passed": True, "spanOk": True, "densityOk": True, "freshnessOk": True},
                    },
                },
            )

            manifest = build_core_evidence_manifest(runtime_dir)

            self.assertEqual(manifest["status"], "PASS")
            self.assertFalse(manifest["promotionGatePassed"])
            self.assertIn("historyProductionStatus:H1:span_not_ok", manifest["promotionBlockers"])
            self.assertIn("historyProductionStatus:H1:density_not_ok", manifest["promotionBlockers"])
            self.assertIn("historyProductionStatus:H1:freshness_not_ok", manifest["promotionBlockers"])

    def test_case_memory_missing_taxonomy_blocks_promotion_gate_without_failing_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json",
                {
                    "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                    "candidateCount": 2,
                    "gaSeedCount": 2,
                    "caseSummary": {"caseTypeCounts": {"EXECUTION_SLIPPAGE": 2}},
                    "candidates": [{"caseType": "EXECUTION_SLIPPAGE"}],
                    "gaSeeds": [{"caseType": "EXECUTION_SLIPPAGE"}],
                },
            )

            manifest = build_core_evidence_manifest(runtime_dir)
            case_memory_row = next(row for row in manifest["artifacts"] if row["artifactId"] == "caseMemoryArtifactManifest")

            self.assertEqual(manifest["status"], "PASS")
            self.assertTrue(manifest["ok"])
            self.assertFalse(manifest["promotionGatePassed"])
            self.assertEqual(case_memory_row["status"], "PASS")
            self.assertEqual(case_memory_row["promotionGate"]["status"], "BLOCKED")
            self.assertIn("caseMemoryArtifactManifest:missing_category:BAD_ENTRY", manifest["promotionBlockers"])
            self.assertIn("caseMemoryArtifactManifest:missing_category:GA_OVERFIT", manifest["promotionBlockers"])
            self.assertGreater(case_memory_row["promotionGate"]["categoryCounts"]["SPREAD_DAMAGE"], 0)
            recovery_rows = manifest["promotionRecoveryQueue"]
            self.assertEqual(manifest["promotionRecoveryQueueCount"], 5)
            self.assertIn("case_memory_category", {row["kind"] for row in recovery_rows})
            self.assertIn("BAD_ENTRY", {row.get("category") for row in recovery_rows})
            bad_entry_row = next(row for row in recovery_rows if row.get("category") == "BAD_ENTRY")
            self.assertEqual(bad_entry_row["status"], "MISSING_CATEGORY")
            self.assertEqual(bad_entry_row["priority"], "HIGH")
            self.assertEqual(bad_entry_row["collectionEndpoint"], "/api/usdjpy-strategy-lab/evidence-os/execution-feedback")
            self.assertIn("MT5_REQUEST_WRITE", bad_entry_row["forbiddenSideEffects"])

    def test_case_memory_missing_candidate_report_blocks_promotion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            (runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json").unlink()

            manifest = build_core_evidence_manifest(runtime_dir)

            self.assertEqual(manifest["status"], "PASS")
            self.assertFalse(manifest["promotionGatePassed"])
            self.assertIn(
                "caseMemoryArtifactManifest:candidate_report_missing_or_unreadable",
                manifest["promotionBlockers"],
            )
            self.assertEqual(manifest["promotionRecoveryQueueCount"], 7)
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["kind"], "case_memory_category")
            self.assertTrue(any(row["kind"] == "case_memory_report" for row in manifest["promotionRecoveryQueue"]))


if __name__ == "__main__":
    unittest.main()
