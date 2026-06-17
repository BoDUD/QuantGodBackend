from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.runtime_evidence_integrity.report import build_core_evidence_manifest, build_core_evidence_summary


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_complete_runtime(runtime_dir: Path) -> None:
    write_json(
        runtime_dir / "live" / "QuantGod_USDJPYLiveLoopStatus.json",
        {
            "schema": "quantgod.usdjpy_live_loop_status.v1",
            "schemaVersion": 1,
            "generatedAt": "2026-06-01T00:00:00Z",
        },
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
        {
            "schema": "quantgod.usdjpy_auto_execution_policy.v1",
            "schemaVersion": 1,
            "generatedAt": "2026-06-01T00:00:00Z",
        },
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
        runtime_dir / "production_validation" / "QuantGod_GAMultiGenerationStabilityReport.json",
        {
            "schema": "quantgod.ga_multi_generation_stability.report.v1",
            "agentVersion": "test-ga-stability-v1",
            "status": "PASS",
            "stabilityGrade": "PRODUCTION_READY",
            "promotionAllowed": True,
            "generationCount": 5,
            "candidateCount": 24,
            "eliteCount": 3,
            "eliteRepeatCount": 1,
            "lineageDepth": 3,
            "factoryLedgerRows": 3,
            "blockers": [],
            "recommendationsZh": ["GA 多代稳定性已达到生产观察门槛。"],
            "safety": {
                "orderSendAllowed": False,
                "closeAllowed": False,
                "cancelAllowed": False,
                "livePresetMutationAllowed": False,
                "telegramCommandExecutionAllowed": False,
                "writesMt5OrderRequest": False,
            },
        },
    )
    write_text(
        runtime_dir / "production_validation" / "QuantGod_GAMultiGenerationStabilityLedger.csv",
        "generatedAt,status,stabilityGrade,closureMode,promotionAllowed,generationCount,candidateCount,eliteCount\n"
        "2026-06-01T00:00:00Z,PASS,PRODUCTION_READY,ELITE_STABILITY,true,5,24,3\n",
    )
    write_json(
        runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json",
        {
            "schema": "quantgod.usdjpy_history_production_status.v1",
            "agentVersion": "test-history-v1",
            "status": "PASS",
            "historyTargetSatisfied": True,
            "timeframes": {
                timeframe: {"passed": True, "spanOk": True, "densityOk": True, "freshnessOk": True}
                for timeframe in ("M1", "M5", "M15", "H1")
            },
        },
    )
    write_json(
        runtime_dir / "parity" / "QuantGod_StrategyParityReport.json",
        {
            "schema": "quantgod.strategy_parity_report.v1",
            "agentVersion": "test-parity-v1",
            "status": "PARITY_PASS",
            "promotionGate": {
                "schema": "quantgod.strategy_parity_promotion_gate.v1",
                "status": "PASS",
                "promotionAllowed": True,
                "blockers": [],
                "reasonZh": "Strategy JSON / Python Replay / MQL5 EA 关键口径一致。",
            },
            "safety": {
                "orderSendAllowed": False,
                "closeAllowed": False,
                "cancelAllowed": False,
                "livePresetMutationAllowed": False,
                "telegramCommandExecutionAllowed": False,
            },
        },
    )
    write_text(
        runtime_dir / "parity" / "QuantGod_StrategyParityLedger.csv",
        "createdAt,symbol,parityStatus,promotionGateStatus\n"
        "2026-06-01T00:00:00Z,USDJPYc,PARITY_PASS,PASS\n",
    )
    write_json(
        runtime_dir / "execution" / "QuantGod_LiveExecutionQualityReport.json",
        {
            "schema": "quantgod.live_execution_quality_report.v1",
            "agentVersion": "test-execution-v1",
            "sampleCount": 1,
        },
    )
    write_text(
        runtime_dir / "execution" / "QuantGod_LiveExecutionFeedback.jsonl",
        json.dumps({"schema": "quantgod.execution_feedback.v1", "schemaVersion": 1, "feedbackId": "F-001"}) + "\n",
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
        {"schema": "quantgod.production_evidence_validation.v1", "schemaVersion": 1, "status": "WARN"},
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
            self.assertEqual(manifest["promotionBlockerSummaryCount"], 0)
            self.assertEqual(manifest["promotionBlockerSummary"], [])
            self.assertEqual(manifest["promotionRecoveryQueueCount"], 0)
            self.assertEqual(manifest["promotionRecoveryQueue"], [])
            self.assertEqual(manifest["jsonArtifactCount"], 11)
            self.assertEqual(manifest["jsonDeclaredVersionCount"], 11)
            self.assertEqual(manifest["versionCoverageStatus"], "PASS")
            self.assertEqual(manifest["versionMissingArtifacts"], [])
            self.assertEqual(manifest["declaredVersionRequiredCount"], 11)
            self.assertEqual(manifest["declaredVersionRequiredMissingCount"], 0)
            self.assertEqual(manifest["declaredVersionRequiredStatus"], "PASS")
            self.assertFalse(manifest["safety"]["orderSendAllowed"])
            self.assertEqual(manifest["hashAlgorithm"], "sha256")
            self.assertEqual(manifest["artifactCount"], 15)
            self.assertIn("historyProductionStatus", {row["artifactId"] for row in manifest["artifacts"]})
            ga_stability_row = next(
                row for row in manifest["artifacts"] if row["artifactId"] == "gaMultiGenerationStabilityReport"
            )
            self.assertEqual(ga_stability_row["promotionGate"]["status"], "PASS")
            self.assertEqual(ga_stability_row["promotionGate"]["stabilityGrade"], "PRODUCTION_READY")
            parity_row = next(row for row in manifest["artifacts"] if row["artifactId"] == "strategyParityReport")
            self.assertEqual(parity_row["promotionGate"]["status"], "PASS")
            self.assertEqual(parity_row["promotionGate"]["reportStatus"], "PARITY_PASS")
            case_memory_row = next(row for row in manifest["artifacts"] if row["artifactId"] == "caseMemoryArtifactManifest")
            self.assertEqual(case_memory_row["promotionGate"]["status"], "PASS")
            self.assertEqual(case_memory_row["promotionGate"]["missingCategories"], [])
            for row in manifest["artifacts"]:
                self.assertEqual(row["status"], "PASS", row)
                self.assertEqual(row["hashAlgorithm"], "sha256")
                self.assertTrue(row["sha256"], row)
                if row["requiresDeclaredVersion"]:
                    self.assertTrue(row["declaredVersionPresent"], row)
                    self.assertEqual(row["versionStatus"], "DECLARED_VERSION_PRESENT", row)
                self.assertFalse(row["path"].startswith("/"), row["path"])
                self.assertEqual(
                    row["sha256"],
                    hashlib.sha256((runtime_dir / row["path"]).read_bytes()).hexdigest(),
                )
            self.assertTrue((runtime_dir / "integrity" / "QuantGod_CoreRuntimeEvidenceManifest.json").exists())

    def test_required_declared_version_blocks_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "case_memory" / "QuantGod_CaseMemoryArtifactManifest.json",
                {
                    "schema": "quantgod.case_memory_artifact_manifest.v1",
                    "artifacts": [
                        {
                            "artifactId": "candidateReport",
                            "path": "case_memory/QuantGod_CaseMemoryStrategyCandidates.json",
                            "exists": True,
                            "sha256": "def",
                        }
                    ],
                },
            )

            manifest = build_core_evidence_manifest(runtime_dir)
            case_memory_row = next(
                row for row in manifest["artifacts"] if row["artifactId"] == "caseMemoryArtifactManifest"
            )

            self.assertEqual(manifest["status"], "FAIL")
            self.assertIn("caseMemoryArtifactManifest:missing_declared_version", manifest["blockers"])
            self.assertEqual(manifest["declaredVersionRequiredStatus"], "FAIL")
            self.assertEqual(
                manifest["declaredVersionRequiredMissingArtifacts"],
                ["caseMemoryArtifactManifest"],
            )
            self.assertFalse(case_memory_row["declaredVersionPresent"])
            self.assertEqual(case_memory_row["versionStatus"], "MISSING_REQUIRED_VERSION")

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

    def test_ga_negative_selection_blocks_promotion_gate_without_failing_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "production_validation" / "QuantGod_GAMultiGenerationStabilityReport.json",
                {
                    "schema": "quantgod.ga_multi_generation_stability.report.v1",
                    "agentVersion": "test-ga-stability-v1",
                    "status": "PASS",
                    "stabilityGrade": "NEGATIVE_SELECTION_CLOSED",
                    "closureMode": "NO_ELITE_NEGATIVE_SELECTION",
                    "promotionAllowed": False,
                    "generationCount": 336,
                    "candidateCount": 1005,
                    "eliteCount": 0,
                    "eliteRepeatCount": 0,
                    "lineageDepth": 2,
                    "factoryLedgerRows": 312,
                    "blockers": [],
                    "recommendationsZh": [
                        "GA 已完成多代负筛选闭环：当前没有可晋级 elite，保持禁止晋级并扩大下一轮搜索。"
                    ],
                    "safety": {
                        "orderSendAllowed": False,
                        "closeAllowed": False,
                        "cancelAllowed": False,
                        "livePresetMutationAllowed": False,
                        "telegramCommandExecutionAllowed": False,
                        "writesMt5OrderRequest": False,
                    },
                },
            )

            manifest = build_core_evidence_manifest(runtime_dir)

            self.assertEqual(manifest["status"], "PASS")
            self.assertTrue(manifest["ok"])
            self.assertFalse(manifest["promotionGatePassed"])
            self.assertEqual(manifest["promotionGateStatus"], "BLOCKED")
            self.assertIn(
                "gaMultiGenerationStabilityReport:stability_grade:NEGATIVE_SELECTION_CLOSED",
                manifest["promotionBlockers"],
            )
            self.assertIn(
                "gaMultiGenerationStabilityReport:promotion_not_allowed",
                manifest["promotionBlockers"],
            )
            ga_row = next(
                row for row in manifest["artifacts"] if row["artifactId"] == "gaMultiGenerationStabilityReport"
            )
            self.assertEqual(ga_row["promotionGate"]["status"], "BLOCKED")
            self.assertEqual(ga_row["promotionGate"]["closureMode"], "NO_ELITE_NEGATIVE_SELECTION")
            blocker_summary = next(
                row for row in manifest["promotionBlockerSummary"]
                if row["artifactId"] == "gaMultiGenerationStabilityReport"
            )
            self.assertEqual(blocker_summary["priority"], "HIGH")
            self.assertEqual(blocker_summary["stabilityGrade"], "NEGATIVE_SELECTION_CLOSED")
            self.assertEqual(blocker_summary["closureMode"], "NO_ELITE_NEGATIVE_SELECTION")
            self.assertIn("ga_promotion", blocker_summary["requiredFor"])
            self.assertIn("ORDER_SEND", blocker_summary["forbiddenSideEffects"])
            recovery_row = next(
                row for row in manifest["promotionRecoveryQueue"] if row["kind"] == "ga_multi_generation_stability"
            )
            self.assertEqual(recovery_row["priority"], "HIGH")
            self.assertEqual(recovery_row["stabilityGrade"], "NEGATIVE_SELECTION_CLOSED")
            self.assertIn("run_ga_multi_generation_stability.py", recovery_row["refreshCommand"])
            self.assertIn("ORDER_SEND", recovery_row["forbiddenSideEffects"])

    def test_stale_history_blocks_promotion_gate_without_failing_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json",
                {
                    "schema": "quantgod.usdjpy_history_production_status.v1",
                    "agentVersion": "test-history-v1",
                    "status": "WARN",
                    "historyTargetSatisfied": False,
                    "copyRatesExportFreshness": {
                        "schema": "quantgod.mql5_copyrates_export_freshness.v1",
                        "status": "STALE",
                        "stale": True,
                        "generatedAtServer": "2026-06-05T11:56:59Z",
                        "generatedLagHours": 263.4,
                        "latestLagHoursByTimeframe": {"M1": 263.4},
                        "staleTimeframes": ["M1"],
                        "nextActionZh": "先刷新 MQL5 CopyRates exporter，再运行 sync-klines 与 production-status。",
                    },
                    "continuousSync": {
                        "expected": True,
                        "mode": "READ_ONLY_HISTORY_SYNC_LOOP",
                        "status": "MISSING",
                        "running": False,
                        "script": "tools/run_mac_usdjpy_history_sync_loop.sh --loop",
                        "startupCommand": "tools/run_mac_usdjpy_history_sync_loop.sh --loop",
                        "onceCommand": "tools/run_mac_usdjpy_history_sync_loop.sh --once",
                        "launchdService": "com.quantgod.usdjpy-history-sync",
                        "matchingProcessCount": 0,
                        "allowedLanes": ["READ_ONLY_RESEARCH", "SHADOW", "TESTER_ONLY"],
                        "forbiddenSideEffects": [
                            "ORDER_SEND",
                            "POSITION_CLOSE",
                            "LIVE_PRESET_MUTATION",
                            "MT5_REQUEST_WRITE",
                            "WALLET_AUTHORIZATION",
                        ],
                        "requiresFreshCopyRatesExporter": True,
                        "safety": {
                            "orderSendAllowed": False,
                            "closeAllowed": False,
                            "cancelAllowed": False,
                            "livePresetMutationAllowed": False,
                            "telegramCommandExecutionAllowed": False,
                        },
                        "nextActionZh": "启动只读 history sync loop，并先刷新 MQL5 CopyRates exporter；不写订单、不改 preset。",
                        "acceptanceZh": "continuousSync.running=true、CopyRates exporter 新鲜。",
                    },
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
            self.assertEqual(manifest["promotionBlockerSummaryCount"], 1)
            self.assertEqual(manifest["promotionBlockerSummary"][0]["artifactId"], "historyProductionStatus")
            self.assertEqual(manifest["promotionBlockerSummary"][0]["priority"], "HIGH")
            self.assertEqual(manifest["promotionBlockerSummary"][0]["staleTimeframes"], ["M1"])
            self.assertEqual(
                manifest["promotionBlockerSummary"][0]["copyRatesExportFreshnessStatus"],
                "STALE",
            )
            self.assertEqual(manifest["promotionBlockerSummary"][0]["continuousSyncStatus"], "MISSING")
            self.assertFalse(manifest["promotionBlockerSummary"][0]["continuousSyncRunning"])
            self.assertIn("ga_promotion", manifest["promotionBlockerSummary"][0]["requiredFor"])
            self.assertIn("ORDER_SEND", manifest["promotionBlockerSummary"][0]["forbiddenSideEffects"])
            self.assertEqual(manifest["promotionRecoveryQueueCount"], 1)
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["kind"], "history_freshness")
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["artifactId"], "historyProductionStatus")
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["timeframe"], "M1")
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["copyRatesExportFreshnessStatus"], "STALE")
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["copyRatesExportLatestLagHours"], 263.4)
            self.assertEqual(manifest["promotionRecoveryQueue"][0]["continuousSyncStatus"], "MISSING")
            self.assertFalse(manifest["promotionRecoveryQueue"][0]["continuousSyncRunning"])
            self.assertEqual(
                manifest["promotionRecoveryQueue"][0]["continuousSyncMode"],
                "READ_ONLY_HISTORY_SYNC_LOOP",
            )
            self.assertEqual(
                manifest["promotionRecoveryQueue"][0]["continuousSyncScript"],
                "tools/run_mac_usdjpy_history_sync_loop.sh --loop",
            )
            self.assertEqual(
                manifest["promotionRecoveryQueue"][0]["continuousSyncStartupCommand"],
                "tools/run_mac_usdjpy_history_sync_loop.sh --loop",
            )
            self.assertEqual(
                manifest["promotionRecoveryQueue"][0]["continuousSyncOnceCommand"],
                "tools/run_mac_usdjpy_history_sync_loop.sh --once",
            )
            self.assertIn("history sync loop", manifest["promotionRecoveryQueue"][0]["continuousSyncNextActionZh"])
            self.assertIn("CopyRates exporter", manifest["promotionRecoveryQueue"][0]["continuousSyncAcceptanceZh"])
            self.assertIn("READ_ONLY_RESEARCH", manifest["promotionRecoveryQueue"][0]["continuousSyncAllowedLanes"])
            self.assertIn(
                "ORDER_SEND",
                manifest["promotionRecoveryQueue"][0]["continuousSyncForbiddenSideEffects"],
            )
            self.assertTrue(
                manifest["promotionRecoveryQueue"][0]["continuousSyncRequiresFreshCopyRatesExporter"]
            )
            self.assertIn("CopyRates exporter", manifest["promotionRecoveryQueue"][0]["copyRatesExportNextActionZh"])
            self.assertIn("ORDER_SEND", manifest["promotionRecoveryQueue"][0]["forbiddenSideEffects"])
            self.assertEqual(history_row["status"], "PASS")
            self.assertEqual(history_row["promotionGate"]["status"], "BLOCKED")
            self.assertIn("ga_promotion", history_row["promotionGate"]["requiredFor"])
            self.assertEqual(history_row["promotionGate"]["staleTimeframes"], ["M1"])
            self.assertEqual(history_row["promotionGate"]["copyRatesExportFreshness"]["status"], "STALE")
            self.assertEqual(history_row["promotionGate"]["continuousSync"]["status"], "MISSING")
            recovery_row = history_row["promotionGate"]["freshnessRecoveryQueue"][0]
            self.assertEqual(recovery_row["timeframe"], "M1")
            self.assertEqual(recovery_row["status"], "FRESHNESS_STALE")
            self.assertEqual(recovery_row["priority"], "HIGH")
            self.assertEqual(recovery_row["copyRatesExportFreshnessStatus"], "STALE")
            self.assertTrue(recovery_row["copyRatesExportStale"])
            self.assertEqual(recovery_row["copyRatesExportGeneratedAtServer"], "2026-06-05T11:56:59Z")
            self.assertEqual(recovery_row["copyRatesExportGeneratedLagHours"], 263.4)
            self.assertEqual(recovery_row["copyRatesExportLatestLagHours"], 263.4)
            self.assertEqual(recovery_row["copyRatesExportStaleTimeframes"], ["M1"])
            self.assertEqual(recovery_row["continuousSyncStatus"], "MISSING")
            self.assertFalse(recovery_row["continuousSyncRunning"])
            self.assertEqual(recovery_row["continuousSyncMode"], "READ_ONLY_HISTORY_SYNC_LOOP")
            self.assertEqual(
                recovery_row["continuousSyncStartupCommand"],
                "tools/run_mac_usdjpy_history_sync_loop.sh --loop",
            )
            self.assertEqual(
                recovery_row["continuousSyncOnceCommand"],
                "tools/run_mac_usdjpy_history_sync_loop.sh --once",
            )
            self.assertIn("READ_ONLY_RESEARCH", recovery_row["continuousSyncAllowedLanes"])
            self.assertIn("ORDER_SEND", recovery_row["continuousSyncForbiddenSideEffects"])
            self.assertTrue(recovery_row["continuousSyncRequiresFreshCopyRatesExporter"])
            self.assertIn("CopyRates exporter", recovery_row["copyRatesExportNextActionZh"])
            self.assertIn("sync-klines", recovery_row["refreshCommand"])
            self.assertIn("production-status", recovery_row["verifyCommand"])
            self.assertIn("freshnessOk=true", recovery_row["acceptanceZh"])
            self.assertIn("ORDER_SEND", recovery_row["forbiddenSideEffects"])

            summary = build_core_evidence_summary(manifest, queue_limit=1, blocker_limit=1)

            self.assertEqual(summary["schema"], "quantgod.core_runtime_evidence_summary.v1")
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["promotionGateStatus"], "BLOCKED")
            self.assertEqual(summary["promotionBlockerCount"], len(manifest["promotionBlockers"]))
            self.assertEqual(summary["promotionBlockerOverflowCount"], len(manifest["promotionBlockers"]) - 1)
            self.assertEqual(summary["promotionBlockerSummaryCount"], 1)
            self.assertEqual(summary["promotionBlockerSummary"][0]["artifactId"], "historyProductionStatus")
            self.assertEqual(summary["promotionBlockerSummary"][0]["staleTimeframes"], ["M1"])
            self.assertEqual(summary["promotionBlockerSummary"][0]["continuousSyncStatus"], "MISSING")
            self.assertEqual(summary["promotionRecoveryQueueCount"], 1)
            self.assertEqual(len(summary["promotionRecoveryQueue"]), 1)
            self.assertEqual(summary["promotionRecoveryQueue"][0]["kind"], "history_freshness")
            self.assertEqual(summary["promotionRecoveryQueue"][0]["timeframe"], "M1")
            self.assertEqual(summary["promotionRecoveryQueue"][0]["copyRatesExportLatestLagHours"], 263.4)
            self.assertEqual(summary["promotionRecoveryQueue"][0]["continuousSyncStatus"], "MISSING")
            self.assertEqual(
                summary["promotionRecoveryQueue"][0]["continuousSyncMode"],
                "READ_ONLY_HISTORY_SYNC_LOOP",
            )
            self.assertEqual(
                summary["promotionRecoveryQueue"][0]["continuousSyncOnceCommand"],
                "tools/run_mac_usdjpy_history_sync_loop.sh --once",
            )
            self.assertIn("READ_ONLY_RESEARCH", summary["promotionRecoveryQueue"][0]["continuousSyncAllowedLanes"])
            self.assertIn("ORDER_SEND", summary["promotionRecoveryQueue"][0]["forbiddenSideEffects"])
            self.assertNotIn("artifacts", summary)

    def test_stale_history_requires_read_only_sync_recovery_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json",
                {
                    "schema": "quantgod.usdjpy_history_production_status.v1",
                    "agentVersion": "test-history-v1",
                    "status": "WARN",
                    "historyTargetSatisfied": False,
                    "copyRatesExportFreshness": {
                        "schema": "quantgod.mql5_copyrates_export_freshness.v1",
                        "status": "STALE",
                        "stale": True,
                        "latestLagHoursByTimeframe": {"M1": 120.0},
                        "staleTimeframes": ["M1"],
                    },
                    "continuousSync": {
                        "expected": True,
                        "status": "MISSING",
                        "running": False,
                        "script": "tools/run_mac_usdjpy_history_sync_loop.sh --loop",
                    },
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
            self.assertFalse(manifest["promotionGatePassed"])
            self.assertIn(
                "historyProductionStatus:history_sync_recovery_contract_mode_missing",
                manifest["promotionBlockers"],
            )
            self.assertIn(
                "historyProductionStatus:history_sync_recovery_contract_once_missing",
                manifest["promotionBlockers"],
            )
            self.assertIn(
                "historyProductionStatus:history_sync_recovery_contract_forbidden_side_effects_missing",
                manifest["promotionBlockers"],
            )
            self.assertIn(
                "historyProductionStatus:history_sync_recovery_contract_safety_unlock:orderSendAllowed",
                manifest["promotionBlockers"],
            )
            self.assertIn(
                "history_sync_recovery_contract_mode_missing",
                history_row["promotionGate"]["blockers"],
            )
            recovery_row = history_row["promotionGate"]["freshnessRecoveryQueue"][0]
            self.assertEqual(recovery_row["continuousSyncStartupCommand"], "tools/run_mac_usdjpy_history_sync_loop.sh --loop")
            self.assertEqual(recovery_row["continuousSyncOnceCommand"], "")
            self.assertEqual(recovery_row["continuousSyncMode"], "")

    def test_missing_required_history_timeframe_blocks_promotion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json",
                {
                    "schema": "quantgod.usdjpy_history_production_status.v1",
                    "agentVersion": "test-history-v1",
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

    def test_parity_failure_blocks_promotion_gate_without_failing_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            write_complete_runtime(runtime_dir)
            write_json(
                runtime_dir / "parity" / "QuantGod_StrategyParityReport.json",
                {
                    "schema": "quantgod.strategy_parity_report.v1",
                    "agentVersion": "test-parity-v1",
                    "status": "PARITY_FAIL",
                    "promotionGate": {
                        "schema": "quantgod.strategy_parity_promotion_gate.v1",
                        "status": "BLOCKED",
                        "promotionAllowed": False,
                        "blockers": [
                            {
                                "name": "strategy_json_python_replay_mql5_gate_matrix",
                                "status": "FAIL",
                                "reasonZh": "MQL5 EA diagnostics 与 Python replay 不一致。",
                            }
                        ],
                    },
                    "safety": {
                        "orderSendAllowed": False,
                        "closeAllowed": False,
                        "cancelAllowed": False,
                        "livePresetMutationAllowed": False,
                        "telegramCommandExecutionAllowed": False,
                    },
                },
            )

            manifest = build_core_evidence_manifest(runtime_dir)
            parity_row = next(row for row in manifest["artifacts"] if row["artifactId"] == "strategyParityReport")
            parity_recovery = next(row for row in manifest["promotionRecoveryQueue"] if row["kind"] == "strategy_parity")

            self.assertEqual(manifest["status"], "PASS")
            self.assertTrue(manifest["ok"])
            self.assertFalse(manifest["promotionGatePassed"])
            self.assertEqual(parity_row["status"], "PASS")
            self.assertEqual(parity_row["promotionGate"]["status"], "BLOCKED")
            self.assertIn(
                "strategyParityReport:parity_status:PARITY_FAIL",
                manifest["promotionBlockers"],
            )
            self.assertIn(
                "strategyParityReport:strategy_json_python_replay_mql5_gate_matrix",
                manifest["promotionBlockers"],
            )
            self.assertEqual(parity_recovery["priority"], "HIGH")
            self.assertIn("run_strategy_parity.py", parity_recovery["refreshCommand"])
            self.assertIn("ORDER_SEND", parity_recovery["forbiddenSideEffects"])

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
            write_json(
                runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYEntryVariantComparison.json",
                {
                    "schema": "quantgod.usdjpy_entry_variant_comparison.v1",
                    "inputCoverage": {
                        "schema": "quantgod.usdjpy_bar_replay_input_coverage.v1",
                        "sampleCount": 32,
                        "entryScoreReadyCount": 0,
                        "missingEntryScoreCount": 32,
                        "actualProfitRReadyCount": 0,
                        "posteriorReadyCount": 0,
                        "requiredOutcomeFields": [
                            "didEnter=true rows need profitR/rMultiple/signedR",
                            "missed-entry rows need posteriorR15/30/60/120 or posteriorPips15/30/60/120 plus riskPips",
                        ],
                    },
                    "variants": [
                        {
                            "name": "relaxed_entry_v1",
                            "metrics": {
                                "sampleCount": 32,
                                "scoredSampleCount": 0,
                                "unresolvedSampleCount": 32,
                                "entryCountDelta": 0,
                                "netRDelta": 0,
                                "evidenceQuality": "NEEDS_BAR_REPLAY",
                            },
                        }
                    ],
                },
            )
            write_json(
                runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYExitVariantComparison.json",
                {
                    "schema": "quantgod.usdjpy_exit_variant_comparison.v1",
                    "variants": [{"name": "let_profit_run_v1", "metrics": {"sampleCount": 0}}],
                },
            )
            write_json(
                runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYNewsGateReplayReport.json",
                {
                    "schema": "quantgod.usdjpy_news_gate_replay.v2_5_1",
                    "variants": [
                        {
                            "variant": "soft_news_gate_v1",
                            "entryCountDelta": 0,
                            "netRDelta": 0,
                            "softNewsOpportunityR": 0,
                            "maxAdverseRDelta": 0,
                        }
                    ],
                },
            )
            write_json(
                runtime_dir / "production_validation" / "QuantGod_GAMultiGenerationStabilityReport.json",
                {
                    "schema": "quantgod.ga_multi_generation_stability.report.v1",
                    "agentVersion": "test-ga-stability-v1",
                    "status": "PASS",
                    "stabilityGrade": "PRODUCTION_READY",
                    "closureMode": "ELITE_STABILITY",
                    "promotionAllowed": True,
                    "generationCount": 336,
                    "candidateCount": 1005,
                    "eliteCount": 2,
                    "blockerCounts": {"HISTORY_PRODUCTION_NOT_READY": 1005},
                    "safety": {
                        "orderSendAllowed": False,
                        "closeAllowed": False,
                        "cancelAllowed": False,
                        "livePresetMutationAllowed": False,
                        "telegramCommandExecutionAllowed": False,
                        "writesMt5OrderRequest": False,
                    },
                },
            )
            write_json(
                runtime_dir / "ga" / "QuantGod_GABlockerSummary.json",
                {
                    "schema": "quantgod.ga.blockers.v1",
                    "summary": [{"blockerCode": "HISTORY_PRODUCTION_NOT_READY", "count": 16}],
                },
            )
            write_json(
                runtime_dir / "ga_factory" / "QuantGod_GAStrategyGraveyard.json",
                {
                    "schema": "quantgod.strategy_ga_factory.strategy_graveyard.v1",
                    "graveyardCount": 1,
                    "strategies": [
                        {
                            "seedId": "GA-USDJPY-G0336-X0005",
                            "strategyId": "USDJPY_RSI_REVERSAL_SHORT_EXPLORE_336_005",
                            "generation": 336,
                            "blockerCode": "HISTORY_PRODUCTION_NOT_READY",
                            "status": "NEEDS_MORE_DATA",
                            "directLiveAllowed": False,
                        }
                    ],
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
            self.assertIn("run_live_execution_feedback.py", bad_entry_row["collectionCommand"])
            self.assertIn("run_case_memory.py", bad_entry_row["caseMemoryBuildCommand"])
            self.assertIn("run_runtime_evidence_integrity.py", bad_entry_row["verifyCommand"])
            self.assertIn("MT5_REQUEST_WRITE", bad_entry_row["forbiddenSideEffects"])
            rows_by_category = {row.get("category"): row for row in recovery_rows}
            self.assertEqual(
                rows_by_category["MISSED_OPPORTUNITY"]["sourceGapStatus"],
                "BLOCKED_BY_REPLAY_SCORING_GAP",
            )
            self.assertIn("0 个可评分", rows_by_category["MISSED_OPPORTUNITY"]["evidenceGapZh"])
            self.assertIn(
                "run_usdjpy_runtime_dataset.py",
                rows_by_category["MISSED_OPPORTUNITY"]["prerequisiteCommand"],
            )
            self.assertIn(
                "posteriorR15/30/60/120",
                " ".join(rows_by_category["MISSED_OPPORTUNITY"]["requiredOutcomeFields"]),
            )
            self.assertIn("run_usdjpy_bar_replay.py", rows_by_category["MISSED_OPPORTUNITY"]["collectionCommand"])
            self.assertIn("entry --write", rows_by_category["MISSED_OPPORTUNITY"]["collectionCommand"])
            self.assertEqual(
                rows_by_category["MISSED_OPPORTUNITY"]["sourceGapArtifact"],
                "replay/usdjpy/QuantGod_USDJPYEntryVariantComparison.json",
            )
            self.assertEqual(rows_by_category["EARLY_EXIT"]["sourceGapStatus"], "WAITING_EXIT_REPLAY_SAMPLES")
            self.assertIn("0 样本", rows_by_category["EARLY_EXIT"]["evidenceGapZh"])
            self.assertIn("exit --write", rows_by_category["EARLY_EXIT"]["collectionCommand"])
            self.assertEqual(rows_by_category["NEWS_DAMAGE"]["sourceGapStatus"], "WAITING_NEWS_DAMAGE_DELTA")
            self.assertIn("未发现普通新闻", rows_by_category["NEWS_DAMAGE"]["evidenceGapZh"])
            self.assertIn("build --write", rows_by_category["NEWS_DAMAGE"]["collectionCommand"])
            self.assertEqual(rows_by_category["GA_OVERFIT"]["sourceGapStatus"], "BLOCKED_BY_HISTORY_FRESHNESS")
            self.assertIn("不是可转写的 GA_OVERFIT", rows_by_category["GA_OVERFIT"]["evidenceGapZh"])
            self.assertIn(
                "run_usdjpy_strategy_backtest.py",
                rows_by_category["GA_OVERFIT"]["prerequisiteCommand"],
            )
            coverage_queue = {
                row["category"]: row
                for row in case_memory_row["promotionGate"]["coveragePlan"]["nextCollectionQueue"]
            }
            self.assertIn("0 个可评分", coverage_queue["MISSED_OPPORTUNITY"]["evidenceGapZh"])
            self.assertIn("profitR", coverage_queue["MISSED_OPPORTUNITY"]["nextActionZh"])
            self.assertIn("run_case_memory.py", coverage_queue["MISSED_OPPORTUNITY"]["caseMemoryBuildCommand"])
            self.assertEqual(coverage_queue["GA_OVERFIT"]["sourceGap"]["status"], "BLOCKED_BY_HISTORY_FRESHNESS")

    def test_case_memory_ledger_summary_counts_historical_ga_overfit_samples(self) -> None:
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
            write_text(
                runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidateLedger.jsonl",
                json.dumps(
                    {
                        "schema": "quantgod.case_memory_strategy_candidate.v1",
                        "candidateId": "CM-GA-001",
                        "caseType": "GA_OVERFIT",
                    }
                )
                + "\n",
            )

            manifest = build_core_evidence_manifest(runtime_dir)
            case_memory_row = next(row for row in manifest["artifacts"] if row["artifactId"] == "caseMemoryArtifactManifest")

            self.assertFalse(manifest["promotionGatePassed"])
            self.assertNotIn("caseMemoryArtifactManifest:missing_category:GA_OVERFIT", manifest["promotionBlockers"])
            self.assertGreater(case_memory_row["promotionGate"]["categoryCounts"]["GA_OVERFIT"], 0)
            self.assertNotIn("GA_OVERFIT", case_memory_row["promotionGate"]["missingCategories"])
            self.assertIn("caseMemoryArtifactManifest:missing_category:BAD_ENTRY", manifest["promotionBlockers"])

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
