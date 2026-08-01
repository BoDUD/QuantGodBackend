from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.case_memory.report import build_case_memory_report, status as case_memory_status
from tools.run_case_memory import main as run_case_memory_main, write_sample_runtime
from tools.strategy_ga.seed_generator import case_memory_seed_pool
from tools.strategy_structure_lab.report import build_report as build_strategy_structure_report


def _write_long_term_memory_sample(runtime: Path) -> None:
    journal = runtime / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(12):
        loss = index < 8
        side = "LONG" if index < 9 else "SHORT"
        symbol = "EURUSD" if index < 9 else "USDJPYc"
        rows.append(
            {
                "schema": "quantgod.ai_advisory_outcome.v1",
                "tradeId": f"T-{index + 1:03d}",
                "entryTime": f"2026-06-01T00:{index:02d}:00Z",
                "exitTime": f"2026-06-01T00:{index + 10:02d}:00Z",
                "symbol": symbol,
                "side": side,
                "strategyVersion": "ACE_MEMORY_V1",
                "leverage": 3,
                "margin": 25,
                "notional": 75,
                "compositeScore": 0.82 if not loss else 0.54,
                "dataCoverageScore": 0.92 if not loss else 0.48,
                "professionalScore": 0.9 if not loss else 0.55,
                "marketQualityScore": 0.72,
                "entryTimingScore": 0.42 if loss else 0.76,
                "fundFlowScore": -0.35 if loss else 0.24,
                "executionRiskScore": 0.72 if loss else 0.18,
                "resonanceCount": 4 if not loss else 1,
                "candidateSource": "ACE_SCOUT",
                "entryReasons": ["breakout", "memory-test"],
                "atr": 1.6,
                "trendScore": 0.2,
                "sentimentScore": -0.2 if loss else 0.2,
                "openInterestChange": -0.3 if loss else 0.1,
                "newsScore": -0.4 if loss else 0.1,
                "smartMoneyScore": -0.25 if loss else 0.2,
                "kronosScore": -0.45 if loss else 0.25,
                "estimatedEV": 0.18,
                "estimatedWinProbability": 0.62,
                "estimatedRiskReward": 1.8,
                "positionScaling": 0.35,
                "stopLossR": 1.0,
                "tp1R": 0.6,
                "takeProfitR": 1.8,
                "trailingStartR": 0.8,
                "mfeGivebackPct": 0.55,
                "factorAttributionSummary": "breakout with weak flow and kronos adverse" if loss else "clean positive follow-through",
                "profitR": -0.42 if loss else 0.15,
                "pnlPercent": -1.2 if loss else 0.45,
                "mfeR": 0.2 if loss else 1.2,
                "maeR": -1.2 if loss else -1.05,
                "exitType": "STOP_LOSS" if loss else "TRAILING_TAKE_PROFIT",
                "exitReason": "fake breakout pullback kronos news flow stop" if loss else "trailing take profit",
            }
        )
    (journal / "QuantGod_AIAdvisoryOutcomes.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_nested_entry_memory_sample(runtime: Path) -> None:
    journal = runtime / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(12):
        rows.append(
            {
                "schema": "quantgod.ai_advisory_outcome.v1",
                "tradeId": f"NEST-{index + 1:03d}",
                "profitR": 0.22 if index >= 6 else -0.18,
                "pnlPercent": 0.66 if index >= 6 else -0.54,
                "mfeR": 1.15 if index >= 6 else 0.25,
                "maeR": -0.35 if index >= 6 else -0.95,
                "exitType": "TAKE_PROFIT" if index >= 6 else "STOP_LOSS",
                "entryContext": {
                    "entryTime": f"2026-06-03T00:{index:02d}:00Z",
                    "symbol": "EURUSD",
                    "side": "LONG",
                    "strategyVersion": "NESTED_MEMORY_V1",
                    "leverage": 2,
                    "marginUsd": 30,
                    "notionalUsd": 60,
                    "reasons": ["nested-score", "factor-rich"],
                    "scores": {
                        "totalScore": 0.78,
                        "dataCoverage": 0.91,
                        "proScore": 0.86,
                        "marketQuality": 0.72,
                        "entryTiming": 0.67,
                        "fundFlow": 0.18,
                        "executionRisk": 0.22,
                        "resonanceCount": 5,
                    },
                    "factors": {
                        "atrPips": 1.4,
                        "trend": 0.42,
                        "sentiment": 0.16,
                        "oiChange": 0.12,
                        "news": 0.08,
                        "smartMoney": 0.21,
                        "kronos": 0.31,
                    },
                    "estimates": {
                        "ev": 0.19,
                        "winProbability": 0.61,
                        "riskReward": 1.7,
                        "positionScale": 0.28,
                    },
                    "riskPlan": {
                        "stopLossR": 1.0,
                        "targetR": 1.8,
                        "firstTakeProfitR": 0.7,
                        "secondTakeProfitR": 1.25,
                        "trailStartR": 0.9,
                        "givebackPct": 0.42,
                        "timeoutMinutes": 180,
                        "stopLossPips": 22,
                        "takeProfitPips": 39,
                    },
                    "factorAttributionSummary": "nested context captured cleanly",
                },
            }
        )
    (journal / "QuantGod_AIAdvisoryOutcomes.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_proxy_entry_memory_sample(runtime: Path) -> None:
    execution = runtime / "execution"
    execution.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(12):
        loss = index < 7
        rows.append(
            {
                "schema": "quantgod.execution_feedback.v1",
                "feedbackId": f"PROXY-{index + 1:03d}",
                "timestamp": f"2026-06-04T00:{index:02d}:00Z",
                "symbol": "USDJPYc",
                "strategyId": "USDJPY_PROXY_MEMORY_V1",
                "eventType": "SHADOW_EXIT",
                "executionMode": "SHADOW",
                "side": "SHORT",
                "expectedPrice": 155.0,
                "fillPrice": 154.9,
                "slippagePips": 0,
                "latencyMs": 0,
                "spreadAtEntry": 0.8,
                "profitR": -0.22 if loss else 0.28,
                "mfeR": 0.18 if loss else 0.8,
                "maeR": 0.72 if loss else 0.2,
                "source": "QuantGod_ShadowCandidateOutcomeLedger.csv",
                "sourceKind": "shadow_outcome",
                "entryContext": {
                    "contextQuality": "SHADOW_PROXY",
                    "contextQualityReasonZh": "旧版 shadow outcome 代理回填。",
                    "proxySource": "legacy_shadow_candidate_outcome",
                    "entryTime": f"2026-06-04T00:{index:02d}:00Z",
                    "symbol": "USDJPYc",
                    "side": "SHORT",
                    "strategyVersion": "USDJPY_PROXY_MEMORY_V1",
                    "scores": {
                        "totalScore": 0.62,
                        "dataCoverage": 0.42,
                        "proScore": 0.55,
                        "marketQuality": 0.48,
                        "entryTiming": 0.62,
                        "fundFlow": 0.5,
                        "executionRisk": 0.52,
                        "resonanceCount": 2,
                    },
                    "factors": {
                        "atrPips": 8.2,
                        "trend": 0.35,
                        "sentiment": 0.5,
                        "oiChange": 0,
                        "news": 0.5,
                        "smartMoney": 0.5,
                        "kronos": 0.5,
                    },
                    "estimates": {
                        "ev": 0.08,
                        "winProbability": 0.51,
                        "riskReward": 1.3,
                        "positionScale": 0.5,
                    },
                    "riskPlan": {
                        "stopLossR": 1.0,
                        "targetR": 1.3,
                        "firstTakeProfitR": 0.7,
                        "secondTakeProfitR": 1.3,
                        "trailStartR": 0.8,
                        "givebackPct": 0.35,
                        "timeoutMinutes": 15,
                        "stopLossPips": 8.2,
                        "takeProfitPips": 10.66,
                    },
                },
            }
        )
    (execution / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_history_context_missing_sample(runtime: Path) -> None:
    evidence = runtime / "evidence_os"
    evidence.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(12):
        loss = index < 8
        rows.append(
            {
                "schema": "quantgod.execution_feedback.v1",
                "feedbackId": f"history-CTXMISS-{index + 1:03d}-ORDER_CLOSE",
                "createdAt": f"2026-06-05T00:{index:02d}:00Z",
                "entrySignalTime": f"2026-06-05T00:{index:02d}:00Z",
                "fillTime": f"2026-06-05T01:{index:02d}:00Z",
                "eventType": "ORDER_CLOSE",
                "symbol": "USDJPYc",
                "side": "BUY" if index < 9 else "SELL",
                "strategyId": "RSI_Reversal",
                "expectedPrice": 155.0,
                "fillPrice": 155.05,
                "profitR": -0.06 if loss else 0.04,
                "mfeR": 0.0,
                "maeR": 0.0,
                "source": "QuantGod_LiveExecutionFeedbackHistory.jsonl",
                "safety": {"orderSendAllowed": False},
            }
        )
    (evidence / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_bridged_history_context_sample(runtime: Path) -> None:
    evidence = runtime / "evidence_os"
    evidence.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(12):
        loss = index < 7
        rows.append(
            {
                "schema": "quantgod.execution_feedback.v1",
                "feedbackId": f"history-BRIDGE-{index + 1:03d}-ORDER_CLOSE",
                "createdAt": f"2026-06-06T00:{index:02d}:00Z",
                "entrySignalTime": f"2026-06-06T00:{index:02d}:00Z",
                "fillTime": f"2026-06-06T01:{index:02d}:00Z",
                "eventType": "ORDER_CLOSE",
                "symbol": "USDJPYc",
                "side": "BUY",
                "strategyId": "RSI_Reversal",
                "expectedPrice": 159.965,
                "fillPrice": 159.889 if loss else 160.02,
                "profitR": -0.0553 if loss else 0.04,
                "mfeR": 0.12 if loss else 0.65,
                "maeR": -0.65 if loss else -0.2,
                "source": "QuantGod_LiveExecutionFeedbackHistory.jsonl",
                "entryContext": {
                    "contextQuality": "BRIDGED_HISTORY_CONTEXT",
                    "contextQualityReasonZh": "历史桥接上下文，只可用于复盘/降级。",
                    "entryTime": f"2026-06-06T00:{index:02d}:00Z",
                    "symbol": "USDJPYc",
                    "side": "BUY",
                    "strategyVersion": "RSI_Reversal",
                    "scores": {
                        "totalScore": 0.5,
                        "dataCoverage": 0.55,
                        "proScore": 0.5,
                        "marketQuality": 0.5,
                        "entryTiming": 0.35 if loss else 0.65,
                        "fundFlow": 0,
                        "executionRisk": 0.35,
                        "resonanceCount": 1,
                    },
                    "factors": {
                        "atrPips": 0,
                        "trend": 0,
                        "sentiment": 0,
                        "oiChange": 0,
                        "news": 0,
                        "smartMoney": 0,
                        "kronos": 0,
                    },
                    "estimates": {
                        "ev": -0.0553 if loss else 0.04,
                        "winProbability": 0.45 if loss else 0.55,
                        "riskReward": 1.2,
                        "positionScale": 0.2,
                    },
                    "riskPlan": {
                        "stopLossR": 1,
                        "targetR": 1.2,
                        "firstTakeProfitR": 0.6,
                        "secondTakeProfitR": 1.2,
                        "trailStartR": 0.8,
                        "givebackPct": 0.45,
                        "timeoutMinutes": 90,
                        "stopLossPips": 7.6,
                        "takeProfitPips": 10.64,
                    },
                },
            }
        )
    (evidence / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class CaseMemoryCandidateTests(unittest.TestCase):
    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_cli_build_respects_write_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            report_path = runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"
            ledger_path = runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidateLedger.jsonl"
            manifest_path = runtime / "case_memory" / "QuantGod_CaseMemoryArtifactManifest.json"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = run_case_memory_main(["--runtime-dir", str(runtime), "build", "--limit", "4"])

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["safety"]["orderSendAllowed"])
            self.assertFalse(report_path.exists())
            self.assertFalse(ledger_path.exists())
            self.assertFalse(manifest_path.exists())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = run_case_memory_main(
                    ["--runtime-dir", str(runtime), "build", "--write", "--limit", "4"]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "READY")
            self.assertTrue(report_path.exists())
            self.assertTrue(ledger_path.exists())
            self.assertTrue(manifest_path.exists())

    def test_builds_shadow_strategy_json_candidates_from_case_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)

            report = build_case_memory_report(runtime, write=True)

            self.assertEqual(report["status"], "READY")
            self.assertGreaterEqual(report["candidateCount"], 1)
            self.assertGreaterEqual(report["gaSeedCount"], 1)
            self.assertEqual(report["coveragePlan"]["schema"], "quantgod.case_memory_coverage_plan.v1")
            self.assertEqual(report["coveragePlan"]["status"], "BLOCKED")
            self.assertFalse(report["coveragePlan"]["promotionAllowed"])
            self.assertIn("BAD_ENTRY", report["coveragePlan"]["missingCategories"])
            self.assertIn("SPREAD_DAMAGE", report["coveragePlan"]["categoryCounts"])
            self.assertTrue(
                all("ORDER_SEND" in row["forbiddenSideEffects"] for row in report["coveragePlan"]["rows"])
            )
            self.assertIn("只允许 shadow/tester", report["nextActionZh"])
            candidate = report["candidates"][0]
            self.assertEqual(candidate["status"], "SHADOW_STRATEGY_JSON_CANDIDATE")
            self.assertTrue(candidate["validation"]["valid"])
            self.assertEqual(candidate["strategyJson"]["lane"], "MT5_SHADOW")
            self.assertFalse(candidate["safety"]["orderSendAllowed"])
            self.assertTrue((runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json").exists())
            self.assertTrue(
                (runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidateLedger.jsonl").exists()
            )
            manifest_path = runtime / "case_memory" / "QuantGod_CaseMemoryArtifactManifest.json"
            report_path = runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"
            ledger_path = runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidateLedger.jsonl"
            self.assertTrue(manifest_path.exists())
            self.assertEqual(report["artifactManifest"]["schema"], "quantgod.case_memory_artifact_manifest.v1")
            self.assertEqual(report["artifactManifest"]["schemaVersion"], 1)
            self.assertEqual(report["artifactManifest"]["path"], "case_memory/QuantGod_CaseMemoryArtifactManifest.json")
            self.assertTrue(report["artifactManifest"]["present"])
            self.assertEqual(report["artifactManifest"]["hashAlgorithm"], "sha256")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schemaVersion"], 1)
            self.assertEqual(manifest["artifactCount"], 2)
            self.assertFalse(manifest["safety"]["orderSendAllowed"])
            rows = {row["artifactId"]: row for row in manifest["artifacts"]}
            self.assertEqual(rows["candidateReport"]["path"], "case_memory/QuantGod_CaseMemoryStrategyCandidates.json")
            self.assertEqual(
                rows["candidateLedger"]["path"],
                "case_memory/QuantGod_CaseMemoryStrategyCandidateLedger.jsonl",
            )
            self.assertEqual(rows["candidateReport"]["sha256"], self._sha256(report_path))
            self.assertEqual(rows["candidateLedger"]["sha256"], self._sha256(ledger_path))
            self.assertGreater(rows["candidateReport"]["sizeBytes"], 0)
            self.assertGreater(rows["candidateLedger"]["sizeBytes"], 0)

    def test_case_memory_preserves_non_rsi_strategy_family_for_ga_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            evidence_dir = runtime / "evidence_os"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "QuantGod_CaseMemorySummary.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.case_memory_summary.v1",
                        "gaSeedHints": [
                            {
                                "caseId": "USDJPY-BB-SHADOW-001",
                                "caseType": "STRATEGY_CONTRACT_SHADOW_SIGNAL",
                                "status": "QUEUED_FOR_GA",
                                "strategyFamily": "BB_Triple",
                                "direction": "LONG",
                                "mutationHint": "promote_contract_candidate_to_tester",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            seeds = case_memory_seed_pool(runtime)

            self.assertEqual(len(seeds), 1)
            self.assertEqual(seeds[0]["strategyFamily"], "BB_Triple")
            self.assertIn("BB_TRIPLE", seeds[0]["strategyId"])

    def test_case_memory_skips_governance_only_live_lane_hints_for_ga_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            evidence_dir = runtime / "evidence_os"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "QuantGod_CaseMemorySummary.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.case_memory_summary.v1",
                        "gaSeedHints": [
                            {
                                "caseId": "USDJPY-POLICY-MISMATCH-001",
                                "caseType": "POLICY_MISMATCH",
                                "status": "QUEUED_FOR_GA",
                                "mutationHint": "verify_live_lane_strategy_lock",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(case_memory_seed_pool(runtime), [])

    def test_parity_fail_blocks_candidate_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            parity_path = runtime / "parity" / "QuantGod_StrategyParityReport.json"
            parity_path.write_text(
                json.dumps(
                    {
                        "status": "PARITY_FAIL",
                        "promotionGate": {"status": "BLOCKED", "promotionAllowed": False},
                        "reasonZh": "Strategy JSON 与 EA 不一致。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = build_case_memory_report(runtime, write=True)

            self.assertFalse(report["ok"])
            self.assertEqual(report["status"], "BLOCKED_BY_PARITY")
            self.assertEqual(report["candidateCount"], 0)
            self.assertTrue(report["parityGate"]["blocked"])

    def test_strategy_structure_lab_wraps_existing_case_memory_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)

            report = build_strategy_structure_report(runtime, write=True)

            self.assertTrue(report["strategyStructureProduction"])
            self.assertEqual(report["p4Stage"], "P4-7")
            self.assertGreaterEqual(report["candidateCount"], 1)
            self.assertTrue(report["safety"]["strategyStructureProductionOnly"])
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["livePresetMutationAllowed"])

    def test_long_term_memory_records_entry_exit_context_and_loss_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            _write_long_term_memory_sample(runtime)

            report = build_case_memory_report(runtime, write=True)

            memory = report["longTermTradeMemory"]
            self.assertEqual(memory["status"], "READY_TO_ADJUST")
            self.assertEqual(memory["tradeMemoryCount"], 12)
            entry = memory["entryMemory"][0]
            self.assertEqual(entry["tradeId"], "T-001")
            self.assertEqual(entry["symbol"], "EURUSD")
            self.assertEqual(entry["strategyVersion"], "ACE_MEMORY_V1")
            self.assertEqual(entry["factors"]["kronosScore"], -0.45)
            self.assertIn("breakout", entry["entryReasons"])
            self.assertEqual(entry["riskPlan"]["takeProfitR"], 1.8)
            self.assertEqual(entry["riskPlan"]["mfeGivebackPct"], 0.55)
            exit_memory = memory["exitMemory"][0]
            self.assertEqual(exit_memory["exitType"], "STOP_LOSS")
            self.assertEqual(exit_memory["mfeR"], 0.2)
            self.assertEqual(exit_memory["maeR"], 1.2)
            self.assertIn("FAST_LOSS", exit_memory["lossTags"])
            self.assertIn("FAKE_BREAKOUT", exit_memory["lossTags"])
            self.assertIn("KRONOS_ADVERSE", exit_memory["lossTags"])
            self.assertIn("LOW_COVERAGE_LOSS", exit_memory["lossTags"])
            win_exit = next(row for row in memory["exitMemory"] if row["profitR"] > 0)
            self.assertIn("PROFIT_GIVEBACK", win_exit["exitQualityTags"])
            self.assertIn("LOW_MFE_CAPTURE", win_exit["exitQualityTags"])
            self.assertIn("RECOVERED_TO_SMALL_WIN", win_exit["exitQualityTags"])
            self.assertLess(win_exit["capturedMfeRatio"], 0.2)
            self.assertFalse(memory["safety"]["orderSendAllowed"])
            self.assertFalse(memory["safety"]["writesMt5OrderRequest"])

    def test_long_term_memory_rolls_up_and_feeds_candidate_penalties(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            _write_long_term_memory_sample(runtime)

            report = build_case_memory_report(runtime, write=True)

            memory = report["longTermTradeMemory"]
            rolling = memory["rollingReview"]
            self.assertTrue(rolling["eligibleToAdjust"])
            self.assertEqual(rolling["sampleCount"], 12)
            self.assertLess(rolling["winRate"], 0.5)
            self.assertTrue(any(item["name"] == "LOW_COVERAGE_LOSS" for item in rolling["commonLossPatterns"]))
            self.assertTrue(any(item["trigger"] == "LOW_COVERAGE_LOSS" for item in rolling["suggestions"]))
            exit_efficiency = rolling["exitEfficiency"]
            self.assertEqual(exit_efficiency["profitGivebackCount"], 4)
            self.assertEqual(exit_efficiency["lowMfeCaptureCount"], 4)
            self.assertEqual(exit_efficiency["recoveredSmallWinCount"], 4)
            self.assertTrue(any(item["trigger"] == "RECOVERED_TO_SMALL_WIN" for item in rolling["tpSlOptimizationHints"]))
            fine_factors = rolling["fineFactorMemoryHealth"]
            self.assertEqual(fine_factors["schema"], "quantgod.fine_factor_memory_health.v1")
            adverse = {item["factor"]: item for item in fine_factors["topAdverseInLosses"]}
            factor_rows = {item["factor"]: item for item in fine_factors["factors"]}
            self.assertIn("atr", factor_rows)
            self.assertEqual(factor_rows["kronos"]["rawCoverageRatio"], 1.0)
            self.assertGreaterEqual(adverse["kronos"]["lossAdverseCount"], 8)
            self.assertGreaterEqual(adverse["news"]["lossAdverseCount"], 8)
            self.assertGreaterEqual(adverse["fundFlow"]["lossAdverseCount"], 8)
            completeness = rolling["entryMemoryCompleteness"]
            self.assertEqual(completeness["sampleCount"], 12)
            factors = next(item for item in completeness["categories"] if item["category"] == "factors")
            self.assertEqual(factors["coverageRatio"], 1.0)
            self.assertTrue(any(item["field"] == "tp2R" for item in completeness["topMissingFields"]))
            self.assertTrue(any(item["field"] == "tp2R" for item in completeness["lowCoverageFields"]))
            self.assertTrue(any(item["trigger"].startswith("LOW_FIELD_COVERAGE_") for item in rolling["suggestions"]))
            feedback = memory["entryFeedbackPolicy"]
            self.assertEqual(feedback["status"], "DEFENSE_MODE")
            self.assertTrue(feedback["defenseMode"]["enabled"])
            self.assertTrue(any(item.get("symbol") == "EURUSD" for item in feedback["symbolPenalties"]))
            self.assertTrue(any(item.get("side") == "LONG" for item in feedback["directionPenalties"]))
            self.assertTrue(any(item.get("factor") == "fundFlow" for item in feedback["fineFactorPenalties"]))
            self.assertTrue(any(rule["match"].get("adverseFactor") == "kronos" for rule in feedback["candidatePenaltyRules"]))
            self.assertTrue(any(rule["match"].get("adverseFactor") == "fundFlow" for rule in feedback["candidatePenaltyRules"]))
            self.assertEqual(feedback["tpSlGuidance"]["mode"], "DEFENSIVE_TP_SL_REVIEW")
            self.assertTrue(any("扛单恢复" in action for action in feedback["tpSlGuidance"]["actionsZh"]))

            cooldown_report = build_case_memory_report(runtime, write=False)
            cooldown = cooldown_report["longTermTradeMemory"]["rollingReview"]
            self.assertEqual(cooldown["status"], "COOLDOWN_ACTIVE")
            self.assertFalse(cooldown["eligibleToAdjust"])

    def test_taxonomy_counts_long_term_loss_and_exit_quality_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            _write_long_term_memory_sample(runtime)

            report = build_case_memory_report(runtime, write=True)
            counts = report["coveragePlan"]["categoryCounts"]

            self.assertGreater(counts["BAD_ENTRY"], 0)
            self.assertGreater(counts["EARLY_EXIT"], 0)
            self.assertGreater(counts["NEWS_DAMAGE"], 0)
            self.assertFalse(report["safety"]["orderSendAllowed"])

            report["coveragePlan"] = {
                "schema": "quantgod.case_memory_coverage_plan.v1",
                "categoryCounts": {category: 0 for category in report["coveragePlan"]["requiredCategories"]},
                "missingCategories": list(report["coveragePlan"]["requiredCategories"]),
            }
            report_path = runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

            hydrated = case_memory_status(runtime)
            hydrated_counts = hydrated["coveragePlan"]["categoryCounts"]
            self.assertGreater(hydrated_counts["BAD_ENTRY"], 0)
            self.assertGreater(hydrated_counts["EARLY_EXIT"], 0)
            self.assertGreater(hydrated_counts["NEWS_DAMAGE"], 0)

    def test_fine_factor_health_marks_bridged_context_as_not_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            execution = runtime / "execution"
            execution.mkdir(parents=True, exist_ok=True)
            rows = []
            for index in range(12):
                rows.append(
                    {
                        "schema": "quantgod.execution_feedback.v1",
                        "eventType": "HISTORY_CLOSE",
                        "tradeId": f"BRIDGE-{index:03d}",
                        "timestamp": f"2026-06-02T01:{index:02d}:00Z",
                        "symbol": "USDJPYc",
                        "side": "LONG",
                        "strategyVersion": "BRIDGED_CONTEXT_TEST",
                        "profitR": -0.1 if index < 6 else 0.2,
                        "pnlPercent": -0.3 if index < 6 else 0.6,
                        "openTime": f"2026-06-02T00:{index:02d}:00Z",
                        "closeTime": f"2026-06-02T01:{index:02d}:00Z",
                        "openPrice": 155.0,
                        "closePrice": 154.98 if index < 6 else 155.04,
                    }
                )
            (execution / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )

            report = build_case_memory_report(runtime, write=False)
            memory = report["longTermTradeMemory"]
            factors = {
                item["factor"]: item
                for item in memory["rollingReview"]["fineFactorMemoryHealth"]["factors"]
            }
            top_raw_missing = memory["rollingReview"]["fineFactorMemoryHealth"]["topRawMissingInLosses"]
            feedback = memory["entryFeedbackPolicy"]

            self.assertEqual(factors["kronos"]["presentCount"], 12)
            self.assertEqual(factors["kronos"]["rawPresentCount"], 0)
            self.assertEqual(factors["kronos"]["rawCoverageRatio"], 0.0)
            self.assertEqual(factors["kronos"]["contextLimitedPresentCount"], 12)
            self.assertEqual(factors["kronos"]["lossMissingCount"], 0)
            self.assertEqual(factors["kronos"]["lossRawMissingCount"], 6)
            self.assertTrue(any(item["factor"] == "kronos" for item in top_raw_missing))
            self.assertTrue(any(item.get("lossTag") == "FINE_FACTOR_kronos_RAW_MISSING" for item in feedback["fineFactorPenalties"]))
            self.assertTrue(any(rule["match"].get("dataGap") == "missingFactor:kronos" for rule in feedback["candidatePenaltyRules"]))

    def test_long_term_memory_review_window_ignores_unknown_flat_shadow_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            _write_long_term_memory_sample(runtime)
            execution = runtime / "execution"
            execution.mkdir(parents=True, exist_ok=True)
            noise_rows = []
            for index in range(40):
                noise_rows.append(
                    {
                        "schema": "quantgod.execution_feedback.v1",
                        "feedbackId": f"NOISE-{index:03d}",
                        "timestamp": f"2026-06-02T01:{index % 60:02d}:00Z",
                        "symbol": "USDJPYc",
                        "strategyId": "USDJPY_SHADOW_OUTCOME_NOISE",
                        "eventType": "SHADOW_EXIT",
                        "executionMode": "SHADOW",
                        "side": "UNKNOWN",
                        "expectedPrice": 0,
                        "fillPrice": 0,
                        "slippagePips": 0,
                        "latencyMs": 0,
                        "spreadAtEntry": 0,
                        "profitR": 0,
                        "mfeR": 1.4,
                        "maeR": 0.7,
                        "source": "QuantGod_ShadowOutcomeLedger.csv",
                    }
                )
            (execution / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in noise_rows) + "\n",
                encoding="utf-8",
            )

            report = build_case_memory_report(runtime, write=True)

            memory = report["longTermTradeMemory"]
            self.assertEqual(memory["reviewWindowTrades"], 12)
            self.assertEqual(len(memory["reviewExitMemory"]), 12)
            rolling = memory["rollingReview"]
            self.assertEqual(rolling["sampleCount"], 12)
            self.assertGreater(rolling["exitEfficiency"]["avgMfeR"], 0)
            self.assertEqual(rolling["exitEfficiency"]["mfeMaeAvailableCount"], 12)
            self.assertEqual(rolling["exitEfficiency"]["missingMfeMaeCount"], 0)

    def test_long_term_memory_backfills_nested_entry_context_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            _write_nested_entry_memory_sample(runtime)

            report = build_case_memory_report(runtime, write=True)

            memory = report["longTermTradeMemory"]
            entry = memory["entryMemory"][0]
            self.assertEqual(entry["symbol"], "EURUSD")
            self.assertEqual(entry["strategyVersion"], "NESTED_MEMORY_V1")
            self.assertEqual(entry["compositeScore"], 0.78)
            self.assertEqual(entry["dataCoverageScore"], 0.91)
            self.assertEqual(entry["professionalScore"], 0.86)
            self.assertEqual(entry["fundFlowScore"], 0.18)
            self.assertEqual(entry["resonanceCount"], 5)
            self.assertEqual(entry["factors"]["atr"], 1.4)
            self.assertEqual(entry["factors"]["smartMoneyScore"], 0.21)
            self.assertEqual(entry["factors"]["kronosScore"], 0.31)
            self.assertEqual(entry["estimatedEV"], 0.19)
            self.assertEqual(entry["estimatedWinProbability"], 0.61)
            self.assertEqual(entry["estimatedRiskReward"], 1.7)
            self.assertEqual(entry["positionScaling"], 0.28)
            self.assertEqual(entry["riskPlan"]["tp2R"], 1.25)
            self.assertEqual(entry["riskPlan"]["takeProfitPriceMove"], 39)
            self.assertIn("nested-score", entry["entryReasons"])
            self.assertEqual(entry["factorAttributionSummary"], "nested context captured cleanly")
            completeness = memory["rollingReview"]["entryMemoryCompleteness"]
            category_coverage = {row["category"]: row["coverageRatio"] for row in completeness["categories"]}
            self.assertEqual(category_coverage["scores"], 1.0)
            self.assertEqual(category_coverage["estimates"], 1.0)
            self.assertEqual(category_coverage["factors"], 1.0)
            self.assertEqual(category_coverage["riskPlan"], 1.0)
            self.assertFalse(memory["safety"]["orderSendAllowed"])

    def test_long_term_memory_marks_proxy_context_as_low_quality_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            _write_proxy_entry_memory_sample(runtime)

            report = build_case_memory_report(runtime, write=True)

            memory = report["longTermTradeMemory"]
            entry = memory["entryMemory"][0]
            self.assertEqual(entry["contextQuality"], "SHADOW_PROXY")
            completeness = memory["rollingReview"]["entryMemoryCompleteness"]
            self.assertEqual(completeness["proxySampleCount"], 12)
            self.assertEqual(completeness["rawSampleCount"], 0)
            self.assertEqual(completeness["overallCoverageRatio"], 1.0)
            self.assertEqual(completeness["rawCoverageRatio"], 0.0)
            self.assertEqual(completeness["proxyCoverageRatio"], 1.0)
            self.assertEqual(completeness["status"], "LOW_RAW_COVERAGE")
            self.assertFalse(completeness["qualityGate"]["rawCoveragePass"])
            self.assertFalse(completeness["qualityGate"]["proxySampleRatioPass"])
            rolling = memory["rollingReview"]
            self.assertTrue(any(item["name"] == "SHADOW_PROXY_CONTEXT" for item in rolling["commonDataGaps"]))
            self.assertTrue(any(item["trigger"] == "LOW_RAW_ENTRY_MEMORY_COVERAGE" for item in rolling["suggestions"]))
            self.assertTrue(any(item["trigger"] == "HIGH_PROXY_ENTRY_MEMORY_RATIO" for item in rolling["suggestions"]))
            self.assertFalse(memory["safety"]["orderSendAllowed"])

    def test_long_term_memory_marks_history_feedback_without_entry_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            _write_history_context_missing_sample(runtime)

            report = build_case_memory_report(runtime, write=True)

            memory = report["longTermTradeMemory"]
            entry = memory["entryMemory"][0]
            self.assertEqual(entry["contextQuality"], "BRIDGED_HISTORY_CONTEXT")
            self.assertIn("只可用于复盘/降级", entry["contextQualityReasonZh"])
            self.assertEqual(entry["dataCoverageScore"], 0.55)
            self.assertGreater(entry["riskPlan"]["takeProfitPriceMove"], 0)
            self.assertIn("历史桥接", entry["factorAttributionSummary"])
            exit_memory = memory["exitMemory"][0]
            self.assertEqual(exit_memory["movementQuality"], "BRIDGED_CLOSE_MOVE_ONLY")
            self.assertTrue(exit_memory["closeMove"]["available"])
            self.assertNotEqual(exit_memory["closeMove"]["closeMoveR"], 0)
            completeness = memory["rollingReview"]["entryMemoryCompleteness"]
            self.assertEqual(completeness["sampleCount"], 12)
            self.assertEqual(completeness["rawSampleCount"], 0)
            self.assertEqual(completeness["usableRawSampleCount"], 0)
            self.assertEqual(completeness["contextMissingSampleCount"], 12)
            self.assertEqual(completeness["contextMissingSampleRatio"], 1.0)
            self.assertEqual(completeness["overallCoverageRatio"], 1.0)
            self.assertFalse(completeness["qualityGate"]["rawCoveragePass"])
            self.assertFalse(completeness["qualityGate"]["contextMissingRatioPass"])
            rolling = memory["rollingReview"]
            exit_efficiency = rolling["exitEfficiency"]
            self.assertEqual(exit_efficiency["mfeMaeAvailableCount"], 0)
            self.assertEqual(exit_efficiency["closeMoveAvailableCount"], 12)
            self.assertEqual(exit_efficiency["closeMoveBridgeOnlyCount"], 12)
            self.assertTrue(any(item["trigger"] == "CLOSE_MOVE_BRIDGE_AVAILABLE" for item in rolling["tpSlOptimizationHints"]))
            self.assertTrue(any(item["name"] == "HISTORY_CONTEXT_MISSING" for item in rolling["commonDataGaps"]))
            self.assertTrue(any(item["trigger"] == "HIGH_HISTORY_CONTEXT_MISSING_RATIO" for item in rolling["suggestions"]))
            self.assertTrue(any(item["trigger"] == "HISTORY_CONTEXT_MISSING" for item in rolling["suggestions"]))
            self.assertFalse(memory["safety"]["orderSendAllowed"])

    def test_long_term_memory_uses_bridged_history_context_without_promotion_quality(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            _write_bridged_history_context_sample(runtime)

            report = build_case_memory_report(runtime, write=True)

            memory = report["longTermTradeMemory"]
            entry = memory["entryMemory"][0]
            self.assertEqual(entry["contextQuality"], "BRIDGED_HISTORY_CONTEXT")
            self.assertEqual(entry["dataCoverageScore"], 0.55)
            self.assertEqual(entry["riskPlan"]["takeProfitPriceMove"], 10.64)
            exit_memory = memory["exitMemory"][0]
            self.assertEqual(exit_memory["movementQuality"], "RAW_MFE_MAE")
            self.assertTrue(exit_memory["closeMove"]["available"])
            self.assertLess(exit_memory["closeMove"]["closeMoveR"], 0)
            completeness = memory["rollingReview"]["entryMemoryCompleteness"]
            self.assertEqual(completeness["sampleCount"], 12)
            self.assertEqual(completeness["rawSampleCount"], 0)
            self.assertEqual(completeness["contextMissingSampleCount"], 12)
            self.assertEqual(completeness["overallCoverageRatio"], 1.0)
            self.assertEqual(completeness["rawCoverageRatio"], 0.0)
            self.assertFalse(completeness["qualityGate"]["rawCoveragePass"])
            self.assertFalse(completeness["qualityGate"]["contextMissingRatioPass"])
            exit_efficiency = memory["rollingReview"]["exitEfficiency"]
            self.assertEqual(exit_efficiency["mfeMaeAvailableCount"], 12)
            self.assertEqual(exit_efficiency["closeMoveAvailableCount"], 12)
            self.assertEqual(exit_efficiency["closeMoveBridgeOnlyCount"], 0)
            self.assertTrue(any(item["name"] == "HISTORY_CONTEXT_MISSING" for item in memory["rollingReview"]["commonDataGaps"]))
            self.assertFalse(memory["safety"]["orderSendAllowed"])

    def test_long_term_memory_ignores_entry_context_only_events_as_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            execution = runtime / "execution"
            execution.mkdir(parents=True, exist_ok=True)
            rows = []
            for index in range(8):
                rows.append(
                    {
                        "schema": "quantgod.execution_feedback.v1",
                        "feedbackId": f"ENTRY-CONTEXT-{index:03d}",
                        "timestamp": f"2026-06-08T07:{index:02d}:00Z",
                        "symbol": "USDJPYc",
                        "strategyId": "RSI_Reversal",
                        "eventType": "DRY_RUN_ENTRY_CONTEXT",
                        "executionMode": "SHADOW",
                        "side": "LONG",
                        "expectedPrice": 0,
                        "fillPrice": 0,
                        "slippagePips": 0,
                        "latencyMs": 0,
                        "spreadAtEntry": 1.2,
                        "profitR": 0,
                        "mfeR": 0,
                        "maeR": 0,
                        "source": "QuantGod_USDJPYEADryRunDecision.json",
                        "sourceKind": "entry_context",
                        "entryContext": {
                            "contextQuality": "RAW",
                            "symbol": "USDJPYc",
                            "side": "LONG",
                            "strategyVersion": "RSI_Reversal",
                            "scores": {"totalScore": 0.71, "dataCoverage": 0.72},
                        },
                    }
                )
            (execution / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )

            report = build_case_memory_report(runtime, write=False)

            memory = report["longTermTradeMemory"]
            self.assertEqual(memory["tradeMemoryCount"], 0)
            self.assertEqual(memory["reviewWindowTrades"], 0)
            self.assertEqual(memory["entryMemory"], [])
            self.assertFalse(memory["safety"]["orderSendAllowed"])

    def test_status_hydrates_legacy_coverage_plan_with_collection_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            write_sample_runtime(runtime, overwrite=True)
            report = build_case_memory_report(runtime, write=True)
            report["coveragePlan"] = {
                "schema": "quantgod.case_memory_coverage_plan.v1",
                "status": "BLOCKED",
                "missingCategories": ["BAD_ENTRY"],
                "rows": [{"category": "BAD_ENTRY", "status": "MISSING", "observedCount": 0}],
            }
            report_path = runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

            hydrated = case_memory_status(runtime)

            coverage = hydrated["coveragePlan"]
            self.assertIn("nextCollectionQueue", coverage)
            self.assertIn("targetSampleCount", coverage)
            self.assertEqual(coverage["nextCollectionQueue"][0]["category"], "BAD_ENTRY")
            self.assertEqual(coverage["nextCollectionQueue"][0]["priority"], "HIGH")
            self.assertIn("collectionEndpoint", coverage["nextCollectionQueue"][0])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_status_hydrates_taxonomy_from_candidate_ledger_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            case_memory_dir = runtime / "case_memory"
            case_memory_dir.mkdir(parents=True, exist_ok=True)
            report = {
                "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                "candidateCount": 2,
                "gaSeedCount": 2,
                "caseSummary": {"caseTypeCounts": {"EXECUTION_SLIPPAGE": 2}},
                "candidates": [{"caseType": "EXECUTION_SLIPPAGE"}],
                "gaSeeds": [{"caseType": "EXECUTION_SLIPPAGE"}],
                "safety": {"orderSendAllowed": False},
            }
            (case_memory_dir / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (case_memory_dir / "QuantGod_CaseMemoryStrategyCandidateLedger.jsonl").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.case_memory_strategy_candidate.v1",
                        "candidateId": "CM-GA-001",
                        "caseType": "GA_OVERFIT",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            hydrated = case_memory_status(runtime)

            self.assertEqual(hydrated["candidateLedgerSummary"]["caseTypeCounts"]["GA_OVERFIT"], 1)
            counts = hydrated["coveragePlan"]["categoryCounts"]
            self.assertGreater(counts["GA_OVERFIT"], 0)
            self.assertNotIn("GA_OVERFIT", hydrated["coveragePlan"]["missingCategories"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_status_explains_source_gaps_for_missing_case_memory_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            case_memory_dir = runtime / "case_memory"
            replay_dir = runtime / "replay" / "usdjpy"
            ga_dir = runtime / "ga"
            ga_factory_dir = runtime / "ga_factory"
            validation_dir = runtime / "production_validation"
            case_memory_dir.mkdir(parents=True, exist_ok=True)
            replay_dir.mkdir(parents=True, exist_ok=True)
            ga_dir.mkdir(parents=True, exist_ok=True)
            ga_factory_dir.mkdir(parents=True, exist_ok=True)
            validation_dir.mkdir(parents=True, exist_ok=True)
            (case_memory_dir / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                        "candidateCount": 2,
                        "gaSeedCount": 2,
                        "caseSummary": {"caseTypeCounts": {"EXECUTION_SLIPPAGE": 2}},
                        "candidates": [{"caseType": "EXECUTION_SLIPPAGE"}],
                        "gaSeeds": [{"caseType": "EXECUTION_SLIPPAGE"}],
                        "safety": {"orderSendAllowed": False},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (replay_dir / "QuantGod_USDJPYEntryVariantComparison.json").write_text(
                json.dumps(
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
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (replay_dir / "QuantGod_USDJPYExitVariantComparison.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.usdjpy_exit_variant_comparison.v1",
                        "variants": [{"name": "let_profit_run_v1", "metrics": {"sampleCount": 0}}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (replay_dir / "QuantGod_USDJPYNewsGateReplayReport.json").write_text(
                json.dumps(
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
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (validation_dir / "QuantGod_GAMultiGenerationStabilityReport.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.ga_multi_generation_stability.report.v1",
                        "stabilityGrade": "NEGATIVE_SELECTION_CLOSED",
                        "closureMode": "NO_ELITE_NEGATIVE_SELECTION",
                        "generationCount": 336,
                        "candidateCount": 1005,
                        "eliteCount": 0,
                        "blockerCounts": {"HISTORY_PRODUCTION_NOT_READY": 1005},
                        "safety": {"orderSendAllowed": False},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (ga_dir / "QuantGod_GABlockerSummary.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.ga.blockers.v1",
                        "summary": [
                            {
                                "blockerCode": "HISTORY_PRODUCTION_NOT_READY",
                                "count": 16,
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (ga_factory_dir / "QuantGod_GAStrategyGraveyard.json").write_text(
                json.dumps(
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
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            hydrated = case_memory_status(runtime)

            gaps = hydrated["sourceEvidenceGaps"]
            self.assertEqual(gaps["MISSED_OPPORTUNITY"]["status"], "BLOCKED_BY_REPLAY_SCORING_GAP")
            self.assertIn("0 个可评分", gaps["MISSED_OPPORTUNITY"]["evidenceGapZh"])
            self.assertEqual(gaps["MISSED_OPPORTUNITY"]["inputCoverage"]["missingEntryScoreCount"], 32)
            self.assertIn("posteriorR15/30/60/120", " ".join(gaps["MISSED_OPPORTUNITY"]["requiredOutcomeFields"]))
            self.assertEqual(gaps["EARLY_EXIT"]["status"], "WAITING_EXIT_REPLAY_SAMPLES")
            self.assertIn("0 样本", gaps["EARLY_EXIT"]["evidenceGapZh"])
            self.assertEqual(gaps["NEWS_DAMAGE"]["status"], "WAITING_NEWS_DAMAGE_DELTA")
            self.assertIn("未发现普通新闻", gaps["NEWS_DAMAGE"]["evidenceGapZh"])
            self.assertEqual(gaps["GA_OVERFIT"]["status"], "BLOCKED_BY_HISTORY_FRESHNESS")
            self.assertTrue(gaps["GA_OVERFIT"]["historyFreshnessBlocked"])
            self.assertEqual(gaps["GA_OVERFIT"]["overfitSampleCount"], 0)
            self.assertIn("不是可转写的 GA_OVERFIT", gaps["GA_OVERFIT"]["evidenceGapZh"])
            self.assertIn("run_usdjpy_strategy_backtest.py", gaps["GA_OVERFIT"]["prerequisiteCommand"])
            queue = {row["category"]: row for row in hydrated["coveragePlan"]["nextCollectionQueue"]}
            self.assertEqual(
                queue["MISSED_OPPORTUNITY"]["sourceGap"]["status"],
                "BLOCKED_BY_REPLAY_SCORING_GAP",
            )
            self.assertIn("0 个可评分", queue["MISSED_OPPORTUNITY"]["evidenceGapZh"])
            self.assertIn("run_usdjpy_runtime_dataset.py", queue["MISSED_OPPORTUNITY"]["prerequisiteCommand"])
            self.assertIn("posteriorR15/30/60/120", " ".join(queue["MISSED_OPPORTUNITY"]["requiredOutcomeFields"]))
            self.assertIn("profitR", queue["MISSED_OPPORTUNITY"]["nextActionZh"])
            self.assertIn("run_usdjpy_bar_replay.py", queue["MISSED_OPPORTUNITY"]["collectionCommand"])
            self.assertIn("entry --write", queue["MISSED_OPPORTUNITY"]["collectionCommand"])
            self.assertIn("run_case_memory.py", queue["MISSED_OPPORTUNITY"]["caseMemoryBuildCommand"])
            self.assertIn("run_runtime_evidence_integrity.py", queue["MISSED_OPPORTUNITY"]["verifyCommand"])
            self.assertIn("run_usdjpy_bar_replay.py", queue["EARLY_EXIT"]["collectionCommand"])
            self.assertIn("exit --write", queue["EARLY_EXIT"]["collectionCommand"])
            self.assertIn("run_usdjpy_bar_replay.py", queue["NEWS_DAMAGE"]["collectionCommand"])
            self.assertEqual(queue["GA_OVERFIT"]["sourceGap"]["status"], "BLOCKED_BY_HISTORY_FRESHNESS")
            self.assertIn("stale-history", queue["GA_OVERFIT"]["nextActionZh"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])


if __name__ == "__main__":
    unittest.main()
