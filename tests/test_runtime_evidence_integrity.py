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
                timeframe: {"passed": True, "freshnessOk": True}
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
        runtime_dir / "case_memory" / "QuantGod_CaseMemoryArtifactManifest.json",
        {
            "schema": "quantgod.case_memory_artifact_manifest.v1",
            "schemaVersion": 1,
            "artifacts": [{"artifactId": "candidateReport", "exists": True, "sha256": "def"}],
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
            self.assertFalse(manifest["safety"]["orderSendAllowed"])
            self.assertEqual(manifest["hashAlgorithm"], "sha256")
            self.assertEqual(manifest["artifactCount"], 11)
            self.assertIn("historyProductionStatus", {row["artifactId"] for row in manifest["artifacts"]})
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


if __name__ == "__main__":
    unittest.main()
