from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.production_evidence_validation.report import build_report, write_reports
from tools.production_evidence_validation.schema import REQUIRED_STRATEGY_FAMILIES


class ProductionEvidenceValidationTests(unittest.TestCase):
    def test_builds_warn_report_without_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_report(Path(tmp))
            self.assertEqual(report["schema"], "quantgod.production_evidence_validation.v1")
            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertEqual(report["coreRuntimeEvidenceIntegrity"]["status"], "FAIL")
            self.assertIn("核心运行证据 integrity 未通过", report["blockersZh"])
            self.assertIn(
                "先修复核心 runtime evidence integrity",
                report["nextActionsZh"][0],
            )

    def test_writes_reports_with_sqlite_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "backtest" / "usdjpy.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db))
            conn.execute("CREATE TABLE bars_m1 (time TEXT, close REAL)")
            conn.execute("CREATE TABLE bars_m5 (time TEXT, close REAL)")
            conn.execute("INSERT INTO bars_m1 VALUES ('2026-05-12T00:00:00Z', 155.0)")
            conn.execute("INSERT INTO bars_m5 VALUES ('2026-05-12T00:00:00Z', 155.0)")
            conn.commit()
            conn.close()
            report = build_report(root)
            paths = write_reports(root, report)
            self.assertTrue(Path(paths["latest"]).exists())
            self.assertTrue(Path(paths["coreRuntimeEvidenceManifest"]).exists())
            saved = json.loads(Path(paths["latest"]).read_text(encoding="utf-8"))
            self.assertIn("historyProduction", saved)
            self.assertIn("coreRuntimeEvidenceIntegrity", saved)
            self.assertEqual(saved["historyProduction"]["status"], "WARN")
            self.assertIn("M15 历史覆盖不足", saved["historyProduction"]["blockersZh"])

    def test_history_audit_requires_all_core_timeframes_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "backtest" / "usdjpy.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db))
            for table in ("bars_m1", "bars_m5", "bars_m15", "bars_h1"):
                conn.execute(f"CREATE TABLE {table} (time TEXT, close REAL)")
                conn.execute(f"INSERT INTO {table} VALUES ('2026-06-01T00:00:00Z', 155.0)")
            conn.commit()
            conn.close()
            (root / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.usdjpy_history_production_status.v1",
                        "status": "PASS",
                        "historyTargetSatisfied": True,
                        "requiredSpanDays": 316.2,
                        "maxLatestLagHours": 96.0,
                        "timeframes": {
                            timeframe: {
                                "timeframe": timeframe,
                                "barCount": 1000,
                                "earliestBar": "2025-06-01T00:00:00Z",
                                "latestBar": "2026-06-01T00:00:00Z",
                                "spanDays": 365.0,
                                "requiredSpanDays": 316.2,
                                "latestLagHours": 12.0,
                                "maxLatestLagHours": 96.0,
                                "spanOk": True,
                                "densityOk": True,
                                "freshnessOk": True,
                                "passed": True,
                            }
                            for timeframe in ("M1", "M5", "M15", "H1")
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(root)

            history = report["historyProduction"]
            self.assertEqual(history["status"], "PASS")
            self.assertTrue(history["coverageGatePassed"])
            self.assertTrue(history["freshnessGatePassed"])
            self.assertEqual(history["passedTimeframes"], 4)
            self.assertEqual(history["databasePath"], "backtest/usdjpy.sqlite")

    def test_history_audit_blocks_when_production_freshness_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "backtest" / "usdjpy.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db))
            for table in ("bars_m1", "bars_m5", "bars_m15", "bars_h1"):
                conn.execute(f"CREATE TABLE {table} (time TEXT, close REAL)")
                conn.execute(f"INSERT INTO {table} VALUES ('2026-06-01T00:00:00Z', 155.0)")
            conn.commit()
            conn.close()
            (root / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.usdjpy_history_production_status.v1",
                        "status": "WARN",
                        "historyTargetSatisfied": False,
                        "requiredSpanDays": 316.2,
                        "maxLatestLagHours": 96.0,
                        "timeframes": {
                            timeframe: {
                                "timeframe": timeframe,
                                "barCount": 1000,
                                "earliestBar": "2025-06-01T00:00:00Z",
                                "latestBar": "2026-06-01T00:00:00Z",
                                "spanDays": 365.0,
                                "requiredSpanDays": 316.2,
                                "latestLagHours": 240.0,
                                "maxLatestLagHours": 96.0,
                                "spanOk": True,
                                "densityOk": True,
                                "freshnessOk": False,
                                "passed": False,
                            }
                            for timeframe in ("M1", "M5", "M15", "H1")
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(root)

            history = report["historyProduction"]
            self.assertEqual(history["status"], "WARN")
            self.assertFalse(history["freshnessGatePassed"])
            self.assertIn("M1 最新 K 线延迟超阈值", history["blockersZh"])
            self.assertEqual(history["staleTimeframes"], ["M1", "M5", "M15", "H1"])
            self.assertEqual(len(history["freshnessRecoveryQueue"]), 4)
            queue_row = history["freshnessRecoveryQueue"][0]
            self.assertEqual(queue_row["timeframe"], "M1")
            self.assertEqual(queue_row["status"], "FRESHNESS_STALE")
            self.assertEqual(queue_row["priority"], "HIGH")
            self.assertEqual(queue_row["excessLagHours"], 144.0)
            self.assertIn("sync-klines", queue_row["refreshCommand"])
            self.assertIn("production-status", queue_row["verifyCommand"])
            self.assertIn("backtest/usdjpy.sqlite", queue_row["sourceArtifacts"])
            self.assertIn("freshnessOk=true", queue_row["acceptanceZh"])
            self.assertIn("ORDER_SEND", queue_row["forbiddenSideEffects"])
            self.assertIn("按 freshnessRecoveryQueue", history["nextRecoveryActionZh"])
            self.assertIn("USDJPY 历史数据覆盖或 freshness 未通过", report["blockersZh"])

    def test_case_memory_coverage_blocks_production_evidence_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_memory_dir = root / "case_memory"
            case_memory_dir.mkdir(parents=True, exist_ok=True)
            (case_memory_dir / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                        "status": "READY",
                        "candidateCount": 2,
                        "gaSeedCount": 2,
                        "caseSummary": {
                            "caseTypeCounts": {
                                "EXECUTION_SLIPPAGE": 2,
                            }
                        },
                        "coveragePlan": {
                            "schema": "quantgod.case_memory_coverage_plan.v1",
                            "status": "BLOCKED",
                            "statusZh": "Case Memory 样本类型不足，继续只读补证",
                            "requiredCategories": [
                                "BAD_ENTRY",
                                "MISSED_OPPORTUNITY",
                                "EARLY_EXIT",
                                "SPREAD_DAMAGE",
                                "NEWS_DAMAGE",
                                "GA_OVERFIT",
                            ],
                            "categoryCounts": {
                                "BAD_ENTRY": 0,
                                "MISSED_OPPORTUNITY": 0,
                                "EARLY_EXIT": 0,
                                "SPREAD_DAMAGE": 2,
                                "NEWS_DAMAGE": 0,
                                "GA_OVERFIT": 0,
                            },
                            "missingCategories": [
                                "BAD_ENTRY",
                                "MISSED_OPPORTUNITY",
                                "EARLY_EXIT",
                                "NEWS_DAMAGE",
                                "GA_OVERFIT",
                            ],
                            "coveredCategoryCount": 1,
                            "requiredCategoryCount": 6,
                            "coverageRatio": 0.1667,
                            "promotionAllowed": False,
                            "rows": [
                                {
                                    "category": "BAD_ENTRY",
                                    "status": "MISSING",
                                    "observedCount": 0,
                                    "targetCount": 3,
                                    "remainingCount": 3,
                                    "priority": "HIGH",
                                    "source": "entry-context feedback / bar replay adverse-entry audit",
                                    "sourceArtifacts": [
                                        "replay/usdjpy/QuantGod_USDJPYBarReplayReport.json",
                                        "execution/QuantGod_LiveExecutionFeedback.jsonl",
                                    ],
                                    "collectionEndpoint": "/api/usdjpy-strategy-lab/evidence-os/execution-feedback",
                                    "nextActionZh": "收集入场后快速进入 MAE 的影子/执行反馈样本。",
                                    "acceptanceZh": "至少 3 条含 entryContext、MAE/MFE、入场原因和后续走势的 shadow/tester 样本。",
                                    "allowedLanes": ["SHADOW", "TESTER_ONLY", "PAPER_LIVE_SIM"],
                                    "forbiddenSideEffects": ["ORDER_SEND", "LIVE_PRESET_MUTATION"],
                                }
                            ],
                            "missingRows": [
                                {
                                    "category": "BAD_ENTRY",
                                    "status": "MISSING",
                                    "observedCount": 0,
                                    "targetCount": 3,
                                    "remainingCount": 3,
                                    "priority": "HIGH",
                                    "source": "entry-context feedback / bar replay adverse-entry audit",
                                    "sourceArtifacts": [
                                        "replay/usdjpy/QuantGod_USDJPYBarReplayReport.json",
                                        "execution/QuantGod_LiveExecutionFeedback.jsonl",
                                    ],
                                    "collectionEndpoint": "/api/usdjpy-strategy-lab/evidence-os/execution-feedback",
                                    "nextActionZh": "收集入场后快速进入 MAE 的影子/执行反馈样本。",
                                    "acceptanceZh": "至少 3 条含 entryContext、MAE/MFE、入场原因和后续走势的 shadow/tester 样本。",
                                }
                            ],
                            "nextCollectionQueue": [
                                {
                                    "category": "BAD_ENTRY",
                                    "priority": "HIGH",
                                    "remainingCount": 3,
                                    "source": "entry-context feedback / bar replay adverse-entry audit",
                                    "sourceArtifacts": [
                                        "replay/usdjpy/QuantGod_USDJPYBarReplayReport.json",
                                        "execution/QuantGod_LiveExecutionFeedback.jsonl",
                                    ],
                                    "collectionEndpoint": "/api/usdjpy-strategy-lab/evidence-os/execution-feedback",
                                    "nextActionZh": "收集入场后快速进入 MAE 的影子/执行反馈样本。",
                                    "acceptanceZh": "至少 3 条含 entryContext、MAE/MFE、入场原因和后续走势的 shadow/tester 样本。",
                                }
                            ],
                            "targetSampleCount": 16,
                            "observedSampleCount": 2,
                            "remainingTargetSampleCount": 14,
                            "nextActionZh": "按缺失分类补充 shadow/tester 证据，不放开真实执行。",
                        },
                        "safety": {
                            "orderSendAllowed": False,
                            "livePresetMutationAllowed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(root)

            case_memory = report["caseMemoryCoverage"]
            self.assertEqual(case_memory["schema"], "quantgod.production_evidence_case_memory_coverage.v1")
            self.assertEqual(case_memory["status"], "BLOCKED")
            self.assertEqual(case_memory["candidateCount"], 2)
            self.assertIn("BAD_ENTRY", case_memory["missingCategories"])
            self.assertIn("Case Memory 缺少 BAD_ENTRY 样本", case_memory["blockersZh"])
            self.assertEqual(case_memory["targetSampleCount"], 16)
            self.assertEqual(case_memory["observedSampleCount"], 2)
            self.assertEqual(case_memory["remainingTargetSampleCount"], 14)
            self.assertEqual(case_memory["nextCollectionQueue"][0]["category"], "BAD_ENTRY")
            self.assertEqual(case_memory["nextCollectionQueue"][0]["priority"], "HIGH")
            self.assertEqual(
                case_memory["nextCollectionQueue"][0]["collectionEndpoint"],
                "/api/usdjpy-strategy-lab/evidence-os/execution-feedback",
            )
            self.assertIn("QuantGod_USDJPYBarReplayReport.json", " ".join(case_memory["nextCollectionQueue"][0]["sourceArtifacts"]))
            self.assertIn("Case Memory 样本类型覆盖不足", report["blockersZh"])
            self.assertIn("按缺失分类补充 shadow/tester 证据", "；".join(report["nextActionsZh"]))

    def test_strategy_family_parity_uses_backtest_coverage_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for family in REQUIRED_STRATEGY_FAMILIES:
                for direction in ("LONG", "SHORT"):
                    rows.append(
                        {
                            "strategyFamily": family,
                            "direction": direction,
                            "ok": True,
                            "status": "PASS",
                            "tradeCount": 0,
                            "parityVectorPresent": True,
                        }
                    )

            report_path = root / "backtest" / "QuantGod_StrategyBacktestReport.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "strategyCoverageMatrix": {
                            "schema": "quantgod.strategy_backtest_coverage_matrix.v1",
                            "status": "PASS",
                            "rows": rows,
                            "summary": {
                                "familyCount": len(REQUIRED_STRATEGY_FAMILIES),
                                "routeCount": len(rows),
                                "coveredFamilyCount": len(REQUIRED_STRATEGY_FAMILIES),
                                "okRouteCount": len(rows),
                                "parityVectorRouteCount": len(rows),
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            parity_dir = root / "parity"
            parity_dir.mkdir(parents=True, exist_ok=True)
            (parity_dir / "QuantGod_StrategyParityReport.json").write_text(
                json.dumps(
                    {
                        "families": [
                            {
                                "strategyFamily": "RSI_Reversal",
                                "status": "PARITY_PASS",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(root)
            parity = report["strategyFamilyParity"]
            statuses = {row["strategyFamily"]: row["parityStatus"] for row in parity["matrix"]}
            self.assertEqual(parity["missingCount"], 0)
            self.assertEqual(parity["status"], "PASS")
            self.assertEqual(statuses["RSI_Reversal"], "PASS")
            self.assertIn("SHADOW_RESEARCH_ONLY", set(statuses.values()))


if __name__ == "__main__":
    unittest.main()
