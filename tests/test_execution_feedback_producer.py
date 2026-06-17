from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.case_memory.report import build_case_memory_report
from tools.execution_feedback_producer import producer
from tools.usdjpy_strategy_lab.entry_context_feedback import build_entry_context_feedback_event


class ExecutionFeedbackProducerTests(unittest.TestCase):
    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_sample_generates_complete_shadow_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            producer.write_sample(runtime, overwrite=True)
            with patch.object(producer, "_source_dirs", return_value=[runtime]):
                report = producer.build_feedback(runtime, write=True)
            self.assertEqual(report["status"], "WARN")
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(report["generatedCount"], 2)
            self.assertEqual(report["completeSampleCount"], 2)
            ledger = runtime / "execution" / "QuantGod_LiveExecutionFeedback.jsonl"
            self.assertTrue(ledger.exists())
            self.assertIn("USDJPY_RSI_REVERSAL_LONG_V1", ledger.read_text(encoding="utf-8"))
            manifest_path = runtime / "execution" / "QuantGod_LiveExecutionFeedbackArtifactManifest.json"
            report_path = runtime / "execution" / "QuantGod_LiveExecutionFeedbackProducerReport.json"
            self.assertTrue(manifest_path.exists())
            self.assertEqual(report["artifactManifest"]["schemaVersion"], 1)
            self.assertEqual(
                report["artifactManifest"]["schema"],
                "quantgod.execution_feedback_producer.artifact_manifest.v1",
            )
            self.assertEqual(
                report["artifactManifest"]["path"],
                "execution/QuantGod_LiveExecutionFeedbackArtifactManifest.json",
            )
            self.assertTrue(report["artifactManifest"]["present"])
            self.assertEqual(report["artifactManifest"]["hashAlgorithm"], "sha256")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schemaVersion"], 1)
            self.assertEqual(manifest["artifactCount"], 2)
            self.assertFalse(manifest["safety"]["orderSendAllowed"])
            rows = {row["artifactId"]: row for row in manifest["artifacts"]}
            self.assertEqual(rows["ledger"]["path"], "execution/QuantGod_LiveExecutionFeedback.jsonl")
            self.assertEqual(
                rows["producerReport"]["path"],
                "execution/QuantGod_LiveExecutionFeedbackProducerReport.json",
            )
            self.assertEqual(rows["ledger"]["sha256"], self._sha256(ledger))
            self.assertEqual(rows["producerReport"]["sha256"], self._sha256(report_path))
            self.assertGreater(rows["ledger"]["sizeBytes"], 0)
            self.assertGreater(rows["producerReport"]["sizeBytes"], 0)

    def test_shadow_candidate_mfe_mae_pips_backfill_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            csv_path = runtime / "QuantGod_ShadowCandidateOutcomeLedger.csv"
            csv_path.write_text(
                "EventId,Symbol,CandidateRoute,Timeframe,CandidateDirection,CandidateScore,"
                "Regime,ReferencePrice,HorizonMinutes,FutureClose,LongClosePips,"
                "ShortClosePips,LongMFEPips,LongMAEPips,ShortMFEPips,ShortMAEPips\n"
                "evt-1,USDJPYc,RSI_Reversal,M15,BUY,54.0,RANGE,155.10,15,155.00,-10.0,10.0,2.5,12.0,12.0,2.5\n",
                encoding="utf-8",
            )

            with patch.object(producer, "_source_dirs", return_value=[runtime]):
                report = producer.build_feedback(runtime, write=True)

            self.assertEqual(report["generatedCount"], 1)
            ledger = runtime / "execution" / "QuantGod_LiveExecutionFeedback.jsonl"
            rows = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 1)
            event = json.loads(rows[0])
            self.assertEqual(event["schemaVersion"], 1)
            self.assertEqual(event["side"], "LONG")
            self.assertEqual(event["strategyId"], "RSI_Reversal")
            self.assertEqual(event["sourceEventId"], "evt-1")
            self.assertEqual(event["horizonBars"], 0.0)
            self.assertEqual(event["expectedPrice"], 155.10)
            self.assertEqual(event["fillPrice"], 155.00)
            self.assertAlmostEqual(event["profitR"], -0.689655, places=6)
            self.assertAlmostEqual(event["mfeR"], 0.172414, places=6)
            self.assertAlmostEqual(event["maeR"], 0.827586, places=6)
            self.assertEqual(event["entryContext"]["contextQuality"], "SHADOW_PROXY")
            self.assertEqual(event["entryContext"]["scores"]["dataCoverage"], 0.42)
            self.assertGreater(event["entryContext"]["estimates"]["ev"], 0.0)
            self.assertEqual(event["entryContext"]["riskPlan"]["timeoutMinutes"], 15.0)
            coverage = {
                row["category"]: row["coverageRatio"]
                for row in report["entryContextCoverage"]["categories"]
            }
            self.assertEqual(report["entryContextCoverage"]["proxyContextCount"], 1)
            self.assertEqual(report["entryContextCoverage"]["proxyContextRatio"], 1.0)
            self.assertEqual(report["entryContextSourceAudit"]["qualityCounts"]["SHADOW_PROXY"], 1)
            self.assertEqual(report["entryContextSourceAudit"]["contextLimitedRatio"], 1.0)
            self.assertEqual(report["entryContextSourceAudit"]["status"], "NEEDS_RAW_ENTRY_CONTEXT")
            self.assertEqual(coverage["scores"], 1.0)
            self.assertEqual(coverage["factors"], 1.0)
            self.assertEqual(coverage["estimates"], 1.0)
            self.assertEqual(coverage["riskPlan"], 1.0)

            with patch.object(producer, "_source_dirs", return_value=[runtime]):
                second_report = producer.build_feedback(runtime, write=True)
            second_rows = [
                line
                for line in ledger.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(second_report["generatedCount"], 0)
            self.assertEqual(len(second_rows), 1)

    def test_shadow_feedback_writes_entry_context_for_long_term_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            csv_path = runtime / "QuantGod_ShadowCandidateOutcomeLedger.csv"
            csv_path.write_text(
                "timestamp,symbol,strategy,side,entryPrice,exitPrice,profitR,mfeR,maeR,spreadAtEntry,"
                "totalScore,dataCoverageScore,professionalScore,marketQualityScore,entryTimingScore,"
                "fundFlowScore,executionRiskScore,resonanceCount,atrPips,trendScore,sentimentScore,"
                "openInterestChange,newsScore,smartMoneyScore,predictionMarketScore,kronosScore,"
                "estimatedEV,estimatedWinProbability,estimatedRiskReward,positionScaling,"
                "stopLossR,takeProfitR,tp1R,tp2R,trailingStartR,mfeGivebackPct,maxHoldMinutes,"
                "stopLossPips,takeProfitPips,entryReasons,factorAttributionSummary\n"
                + "\n".join(
                    "2026-06-04T00:{idx:02d}:00Z,USDJPYc,RSI_Reversal,LONG,155.10,155.18,{profit},1.2,-0.4,0.8,"
                    "0.82,0.93,0.88,0.71,0.66,0.22,0.18,5,1.4,0.41,0.16,0.12,0.08,0.2,0.09,0.31,"
                    "0.18,0.62,1.8,0.32,1.0,1.9,0.7,1.25,0.9,0.42,180,22,41,"
                    "clean setup|memory rich,full factor context"
                    .format(idx=index, profit="0.24" if index >= 6 else "-0.16")
                    for index in range(12)
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(producer, "_source_dirs", return_value=[runtime]):
                feedback_report = producer.build_feedback(runtime, write=True)
            memory_report = build_case_memory_report(runtime, write=False)

            self.assertEqual(feedback_report["generatedCount"], 12)
            self.assertEqual(feedback_report["entryContextCoverage"]["status"], "GOOD")
            self.assertEqual(feedback_report["entryContextSourceAudit"]["status"], "GOOD")
            self.assertEqual(feedback_report["entryContextSourceAudit"]["qualityCounts"]["RAW"], 12)
            self.assertEqual(feedback_report["entryContextSourceAudit"]["rawContextRatio"], 1.0)
            coverage_rows = {
                row["category"]: row["coverageRatio"]
                for row in feedback_report["entryContextCoverage"]["categories"]
            }
            self.assertEqual(coverage_rows["scores"], 1.0)
            self.assertEqual(coverage_rows["factors"], 1.0)
            ledger = runtime / "execution" / "QuantGod_LiveExecutionFeedback.jsonl"
            first_event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(first_event["entryContext"]["scores"]["totalScore"], 0.82)
            self.assertEqual(first_event["entryContext"]["factors"]["kronos"], 0.31)
            memory = memory_report["longTermTradeMemory"]
            completeness = memory["rollingReview"]["entryMemoryCompleteness"]
            coverage = {row["category"]: row["coverageRatio"] for row in completeness["categories"]}
            self.assertEqual(coverage["scores"], 1.0)
            self.assertEqual(coverage["factors"], 1.0)
            self.assertEqual(coverage["estimates"], 1.0)
            self.assertEqual(coverage["riskPlan"], 1.0)
            self.assertFalse(memory["safety"]["orderSendAllowed"])

    def test_basic_feedback_without_factor_snapshot_is_not_marked_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            feedback_dir = runtime / "evidence_os"
            feedback_dir.mkdir(parents=True)
            (feedback_dir / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                json.dumps({
                    "feedbackId": "basic-1",
                    "timestamp": "2026-06-04T01:00:00Z",
                    "symbol": "USDJPYc",
                    "strategyId": "RSI_Reversal",
                    "eventType": "ORDER_SEND",
                    "executionMode": "SHADOW",
                    "side": "LONG",
                    "expectedPrice": 155.10,
                    "fillPrice": 155.10,
                    "slippagePips": 0.0,
                    "latencyMs": 12,
                    "spreadAtEntry": 0.8,
                    "profitR": 0.0,
                    "mfeR": 0.0,
                    "maeR": 0.0,
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with patch.object(producer, "_source_dirs", return_value=[runtime]):
                report = producer.build_feedback(runtime, write=True)

            ledger = runtime / "execution" / "QuantGod_LiveExecutionFeedback.jsonl"
            event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(event["entryContext"]["contextQuality"], "EXECUTION_FEEDBACK_CONTEXT")
            self.assertEqual(report["entryContextSourceAudit"]["qualityCounts"]["EXECUTION_FEEDBACK_CONTEXT"], 1)
            self.assertEqual(report["entryContextSourceAudit"]["rawContextRatio"], 0.0)
            self.assertEqual(report["entryContextSourceAudit"]["status"], "NEEDS_RAW_ENTRY_CONTEXT")

    def test_policy_entry_context_feedback_is_raw_but_entry_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            event = build_entry_context_feedback_event(
                policy={
                    "maxLot": 2.0,
                    "newsGate": {"mode": "ALLOW", "riskLevel": "LOW", "hardBlock": False},
                    "spreadGate": {"tier": "NORMAL", "spreadPips": 1.2, "hardBlock": False},
                    "evidence": {"runtimeFreshnessTier": "FRESH"},
                },
                top_policy={
                    "strategy": "RSI_Reversal",
                    "direction": "LONG",
                    "regime": "RANGE",
                    "entryMode": "OPPORTUNITY_ENTRY",
                    "entryStrictness": "OPPORTUNITY_HARD_GATE_PASS_QUORUM_2_OF_3",
                    "score": 71,
                    "recommendedLot": 0.2,
                    "maxLot": 2.0,
                    "signalQuorum": 2,
                    "signalQuorumRequired": 3,
                    "tacticalConfirmations": {"triggerScore": 0.86},
                    "newsGate": {"mode": "ALLOW", "riskLevel": "LOW", "hardBlock": False},
                    "spreadGate": {"tier": "NORMAL", "spreadPips": 1.2, "hardBlock": False},
                    "trailStartR": 1.1,
                    "timeStopBars": 4,
                    "initialStopPips": 3.2,
                    "target1Pips": 4.8,
                    "target2Pips": 6.4,
                    "reasons": ["policy context test"],
                },
                generated_at="2026-06-08T07:40:00Z",
                event_type="DRY_RUN_ENTRY_CONTEXT",
                source_name="QuantGod_USDJPYEADryRunDecision.json",
            )
            feedback_dir = runtime / "evidence_os"
            feedback_dir.mkdir(parents=True)
            (feedback_dir / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                json.dumps(event, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with patch.object(producer, "_source_dirs", return_value=[runtime]):
                report = producer.build_feedback(runtime, write=True)

            ledger = runtime / "execution" / "QuantGod_LiveExecutionFeedback.jsonl"
            row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["eventType"], "DRY_RUN_ENTRY_CONTEXT")
            self.assertEqual(row["entryContext"]["contextQuality"], "RAW")
            self.assertEqual(row["entryContext"]["riskPlan"]["stopLossPips"], 3.2)
            self.assertEqual(report["entryContextSourceAudit"]["qualityCounts"]["RAW"], 1)
            self.assertEqual(report["entryContextSourceAudit"]["rawContextRatio"], 1.0)

    def test_existing_empty_raw_context_is_corrected_on_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            ledger = runtime / "execution" / "QuantGod_LiveExecutionFeedback.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                json.dumps({
                    "feedbackId": "legacy-empty-raw",
                    "timestamp": "2026-06-04T02:00:00Z",
                    "symbol": "USDJPYc",
                    "strategyId": "RSI_Reversal",
                    "eventType": "ORDER_SEND",
                    "executionMode": "SHADOW",
                    "side": "LONG",
                    "expectedPrice": 155.10,
                    "fillPrice": 155.10,
                    "slippagePips": 0.0,
                    "latencyMs": 12,
                    "spreadAtEntry": 0.8,
                    "profitR": 0.0,
                    "mfeR": 0.0,
                    "maeR": 0.0,
                    "source": "legacy",
                    "sourceKind": "existing_feedback",
                    "entryContext": {
                        "contextQuality": "RAW",
                        "symbol": "USDJPYc",
                        "side": "LONG",
                    },
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with patch.object(producer, "_source_dirs", return_value=[runtime]):
                report = producer.build_feedback(runtime, write=True)

            event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(event["entryContext"]["contextQuality"], "EXECUTION_FEEDBACK_CONTEXT")
            self.assertEqual(report["correctedEmptyRawContextCount"], 1)
            self.assertEqual(report["entryContextSourceAudit"]["rawContextRatio"], 0.0)


if __name__ == "__main__":
    unittest.main()
