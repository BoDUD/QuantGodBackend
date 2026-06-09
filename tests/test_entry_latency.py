from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from tools.entry_latency.report import build_report, report_path
from tools.entry_latency.telegram_text import build_telegram_text


class EntryLatencyTests(unittest.TestCase):
    def test_build_report_attributes_startup_guard_and_writes_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "quality").mkdir(parents=True)
            (runtime / "adaptive").mkdir(parents=True)
            (runtime / "quality" / "QuantGod_MT5FastLaneQuality.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:00Z",
                    "heartbeatFresh": True,
                    "symbols": [{"symbol": "USDJPYc", "quality": "FAST", "tickAgeSeconds": 1, "indicatorAgeSeconds": 1, "spreadPoints": 2}],
                }),
                encoding="utf-8",
            )
            (runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:02Z",
                    "topLiveEligiblePolicy": {
                        "symbol": "USDJPYc",
                        "strategy": "RSI_Reversal",
                        "direction": "LONG",
                        "entryMode": "OPPORTUNITY_ENTRY",
                        "allowed": True,
                        "recommendedLot": 0.05,
                    },
                }),
                encoding="utf-8",
            )
            (runtime / "QuantGod_USDJPYRsiEntryDiagnostics.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:04Z",
                    "state": "STARTUP_GUARD",
                    "guards": {
                        "startupGuardActive": True,
                        "startupGuardReason": "Pilot startup entry guard active",
                        "spreadPips": 2.1,
                        "spreadAllowed": True,
                    },
                    "whyNoEntry": [{"label": "启动保护中", "detail": "Pilot startup entry guard active"}],
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            payload = build_report(runtime, write=True)

            self.assertEqual(payload["summary"]["primaryStage"], "ea_guard")
            self.assertEqual(payload["summary"]["state"], "STARTUP_GUARD")
            self.assertTrue(payload["summary"]["startupGuardActive"])
            self.assertEqual(payload["summary"]["nextRequiredActionZh"], payload["nextRequiredActionZh"])
            self.assertFalse(payload["summary"]["readyForEntryReview"])
            startup_gap = next(item for item in payload["readinessGaps"] if item["gapId"] == "ea_startup_guard_clear")
            self.assertFalse(startup_gap["passed"])
            self.assertEqual(startup_gap["required"], "startupGuardActive=false")
            self.assertEqual(payload["entryReadiness"]["firstFailedGapId"], "ea_startup_guard_clear")
            self.assertEqual(payload["recoveryActions"][0]["actionId"], "wait_or_refresh_ea_startup_guard")
            self.assertIn("startupGuardActive=false", payload["recoveryActions"][0]["expectedEvidence"]["fields"])
            self.assertEqual(payload["latency"]["policyToEaMs"], 2000)
            self.assertTrue(report_path(runtime).exists())
            self.assertTrue((runtime / "latency" / "QuantGod_EntryLatencyLedger.csv").exists())

    def test_global_dashboard_embedded_ea_diagnostics_replaces_stale_standalone(self):
        old_env = {
            key: os.environ.get(key)
            for key in ("QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY", "QG_RUNTIME_DIR", "QG_MT5_FILES_DIR")
        }
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                runtime = root / "runtime"
                mt5_files = root / "mt5_files"
                (runtime / "quality").mkdir(parents=True)
                (runtime / "adaptive").mkdir(parents=True)
                mt5_files.mkdir(parents=True)
                os.environ["QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY"] = "1"
                os.environ["QG_RUNTIME_DIR"] = ""
                os.environ["QG_MT5_FILES_DIR"] = str(mt5_files)
                (runtime / "quality" / "QuantGod_MT5FastLaneQuality.json").write_text(
                    json.dumps({
                        "generatedAt": "2026-05-27T10:00:00Z",
                        "heartbeatFresh": True,
                        "symbols": [{"symbol": "USDJPYc", "quality": "FAST", "tickAgeSeconds": 1, "indicatorAgeSeconds": 1}],
                    }),
                    encoding="utf-8",
                )
                (runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json").write_text(
                    json.dumps({
                        "generatedAt": "2026-05-27T10:00:02Z",
                        "topPolicy": {"symbol": "USDJPYc", "strategy": "RSI_Reversal", "direction": "LONG", "entryMode": "WATCH_ONLY", "allowed": False},
                    }),
                    encoding="utf-8",
                )
                stale_path = runtime / "QuantGod_USDJPYRsiEntryDiagnostics.json"
                stale_path.write_text(
                    json.dumps({
                        "generatedAt": "2026-05-09T14:30:32Z",
                        "state": "STARTUP_GUARD",
                        "guards": {"startupGuardActive": True, "spreadAllowed": False, "spreadPips": 6.5},
                    }, ensure_ascii=False),
                    encoding="utf-8",
                )
                old_time = time.time() - 3600
                os.utime(stale_path, (old_time, old_time))
                (mt5_files / "QuantGod_Dashboard.json").write_text(
                    json.dumps({
                        "watchlist": "USDJPYc",
                        "runtime": {"tradeStatus": "READY", "tickAgeSeconds": 1},
                        "market": {"bid": 159.95, "ask": 159.972, "spread": 2.2},
                        "usdJpyRsiEntryDiagnostics": {
                            "state": "WAITING_RSI_SIGNAL",
                            "guards": {"startupGuardActive": False, "spreadAllowed": True, "spreadPips": 2.2},
                            "rsi": {"signalReady": False, "signalDirection": "NONE"},
                            "whyNoEntry": [{"detail": "RSI H1 BUY bias 50/100 | reversal=N band=Y"}],
                        },
                    }, ensure_ascii=False),
                    encoding="utf-8",
                )

                payload = build_report(runtime, write=False)
                ea_stage = next(item for item in payload["timeline"] if item["stage"] == "ea_guard")
                self.assertEqual(ea_stage["state"], "WAITING_RSI_SIGNAL")
                self.assertFalse(ea_stage["startupGuardActive"])
                self.assertTrue(ea_stage["spreadAllowed"])
                self.assertEqual(ea_stage["spreadPips"], 2.2)
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_missing_evidence_fails_closed_without_execution_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_report(Path(tmp), write=False)
            self.assertEqual(payload["summary"]["primaryStage"], "market_data")
            self.assertFalse(payload["safety"]["orderSendAllowed"])
            self.assertIn("缺少快通道", payload["summary"]["primaryReasonZh"])
            self.assertFalse(payload["entryReadiness"]["readyForEntryReview"])
            self.assertIn("market_data_ready", payload["entryReadiness"]["failedGapIds"])
            market_gap = next(item for item in payload["readinessGaps"] if item["gapId"] == "market_data_ready")
            self.assertFalse(market_gap["passed"])
            self.assertEqual(market_gap["current"], "MISSING")
            self.assertEqual(payload["recoveryActions"][0]["actionId"], "restore_fastlane_quality_report")
            self.assertIn("恢复 MT5 快通道", payload["nextRequiredActionZh"])
            text = build_telegram_text(payload)
            self.assertIn("入场延迟归因", text)
            self.assertIn("不会下单", text)

    def test_policy_blocker_prefers_quorum_reason_over_hard_gate_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "quality").mkdir(parents=True)
            (runtime / "adaptive").mkdir(parents=True)
            (runtime / "quality" / "QuantGod_MT5FastLaneQuality.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:00Z",
                    "heartbeatFresh": True,
                    "symbols": [{"symbol": "USDJPYc", "quality": "FAST", "tickAgeSeconds": 1, "indicatorAgeSeconds": 1, "spreadPoints": 2}],
                }),
                encoding="utf-8",
            )
            (runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:02Z",
                    "topPolicy": {
                        "symbol": "USDJPYc",
                        "strategy": "RSI_Reversal",
                        "direction": "LONG",
                        "entryMode": "WATCH_ONLY",
                        "allowed": False,
                        "hardGateStatus": "PASS",
                        "hardGateReasons": ["硬风控通过"],
                        "signalQuorum": 1,
                        "signalQuorumRequired": 2,
                        "reasons": ["硬风控通过但 quorum/分数不足，保持观察不入场"],
                        "tacticalConfirmations": {
                            "confirmations": {"影子样本未显示负期望": False},
                        },
                    },
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            (runtime / "QuantGod_USDJPYRsiEntryDiagnostics.json").write_text(
                json.dumps({"generatedAt": "2026-05-27T10:00:04Z", "state": "WAIT_SIGNAL"}, ensure_ascii=False),
                encoding="utf-8",
            )

            payload = build_report(runtime, write=False)

            self.assertEqual(payload["summary"]["primaryStage"], "policy")
            self.assertIn("signal quorum 未满足", payload["summary"]["primaryReasonZh"])
            self.assertNotEqual(payload["summary"]["primaryReasonZh"], "硬风控通过")
            self.assertFalse(payload["summary"]["readyForEntryReview"])
            self.assertIn("signal_quorum", payload["summary"]["failedReadinessGapIds"])
            signal_gap = next(item for item in payload["readinessGaps"] if item["gapId"] == "signal_quorum")
            self.assertFalse(signal_gap["passed"])
            self.assertEqual(signal_gap["current"], "1/2")
            self.assertEqual(signal_gap["detail"]["signalQuorumGap"], 1.0)
            shadow_gap = next(item for item in payload["readinessGaps"] if item["gapId"] == "shadow_sample_non_negative")
            self.assertFalse(shadow_gap["passed"])
            self.assertEqual(payload["recoveryActions"][0]["actionId"], "wait_for_signal_quorum_or_shadow_sample")
            self.assertIn("signalQuorum >= signalQuorumRequired", payload["recoveryActions"][0]["expectedEvidence"]["fields"])

    def test_stale_order_feedback_is_historical_evidence_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "quality").mkdir(parents=True)
            (runtime / "adaptive").mkdir(parents=True)
            (runtime / "execution").mkdir(parents=True)
            (runtime / "quality" / "QuantGod_MT5FastLaneQuality.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:00Z",
                    "heartbeatFresh": True,
                    "symbols": [{"symbol": "USDJPYc", "quality": "FAST", "tickAgeSeconds": 1, "indicatorAgeSeconds": 1, "spreadPoints": 2}],
                }),
                encoding="utf-8",
            )
            (runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:02Z",
                    "topLiveEligiblePolicy": {
                        "symbol": "USDJPYc",
                        "strategy": "RSI_Reversal",
                        "direction": "LONG",
                        "entryMode": "STANDARD_ENTRY",
                        "allowed": True,
                        "recommendedLot": 0.05,
                    },
                }),
                encoding="utf-8",
            )
            (runtime / "QuantGod_USDJPYRsiEntryDiagnostics.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:04Z",
                    "state": "READY",
                    "guards": {"startupGuardActive": False, "spreadPips": 1.8, "spreadAllowed": True},
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            (runtime / "execution" / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                json.dumps({"eventType": "ORDER_ACCEPTED", "eventTime": "2020-01-01T00:00:00Z"}) + "\n",
                encoding="utf-8",
            )

            payload = build_report(runtime, write=False)

            order_stage = next(item for item in payload["timeline"] if item["stage"] == "order_attempt")
            order_gap = next(item for item in payload["readinessGaps"] if item["gapId"] == "order_attempt_feedback_seen")
            self.assertEqual(order_stage["status"], "STALE_ATTEMPT")
            self.assertEqual(payload["summary"]["primaryStage"], "order_attempt")
            self.assertFalse(payload["summary"]["orderAttemptSeen"])
            self.assertIsNone(payload["latency"]["eaToOrderAttemptMs"])
            self.assertFalse(order_gap["passed"])
            self.assertFalse(order_gap["essential"])

    def test_policy_ea_signal_direction_mismatch_stays_shadow_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "quality").mkdir(parents=True)
            (runtime / "adaptive").mkdir(parents=True)
            (runtime / "quality" / "QuantGod_MT5FastLaneQuality.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:00Z",
                    "heartbeatFresh": True,
                    "symbols": [{"symbol": "USDJPYc", "quality": "FAST", "tickAgeSeconds": 1, "indicatorAgeSeconds": 1, "spreadPoints": 2}],
                }),
                encoding="utf-8",
            )
            (runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:02Z",
                    "topLiveEligiblePolicy": {
                        "symbol": "USDJPYc",
                        "strategy": "RSI_Reversal",
                        "direction": "LONG",
                        "entryMode": "STANDARD_ENTRY",
                        "allowed": True,
                        "recommendedLot": 0.05,
                    },
                    "topShadowPolicy": {
                        "symbol": "USDJPYc",
                        "strategy": "RSI_Reversal",
                        "direction": "SHORT",
                        "entryMode": "WATCH_ONLY",
                        "entryStrictness": "SHADOW_ONLY_NON_RSI_LIVE_ROUTE",
                        "signalQuorum": 3,
                        "signalQuorumRequired": 2,
                        "reasons": ["非 RSI_Reversal LONG 不进入 MT5 live；只保留 shadow/replay/GA 研究。"],
                    },
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            (runtime / "QuantGod_USDJPYRsiEntryDiagnostics.json").write_text(
                json.dumps({
                    "generatedAt": "2026-05-27T10:00:04Z",
                    "state": "READY",
                    "direction": "LONG",
                    "guards": {"startupGuardActive": False, "spreadPips": 1.8, "spreadAllowed": True},
                    "rsi": {
                        "signalReady": True,
                        "signalDirection": "SELL",
                        "signalScore": 100,
                        "evalCode": "SIGNAL_SELL",
                        "evalReason": "USDJPY RSI_Reversal H1 sell setup ported from MT4",
                    },
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            payload = build_report(runtime, write=False)

            gap = next(item for item in payload["readinessGaps"] if item["gapId"] == "policy_ea_signal_alignment")
            self.assertFalse(gap["passed"])
            self.assertEqual(gap["current"], "policy=LONG / ea=SHORT")
            self.assertEqual(gap["detail"]["eaEvalCode"], "SIGNAL_SELL")
            self.assertEqual(gap["detail"]["topShadowPolicy"]["direction"], "SHORT")
            self.assertTrue(gap["detail"]["demotedOutOfScopeSignal"]["demoted"])
            self.assertEqual(gap["detail"]["demotedOutOfScopeSignal"]["code"], "sell_side_demoted_after_loss_review")
            self.assertIn("policy_ea_signal_alignment", payload["summary"]["failedReadinessGapIds"])
            self.assertFalse(payload["entryReadiness"]["readyForEntryReview"])
            self.assertEqual(payload["recoveryActions"][0]["actionId"], "evaluate_signal_direction_shadow_lane")
            self.assertIn("live loss review", payload["recoveryActions"][0]["reasonZh"])
            self.assertFalse(payload["safety"]["orderSendAllowed"])


if __name__ == "__main__":
    unittest.main()
