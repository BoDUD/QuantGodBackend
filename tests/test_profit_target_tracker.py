from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from tools.profit_target_tracker.builder import build_profit_target_tracker, read_profit_target_tracker
from tools.profit_target_tracker.schema import report_path
from tools.run_profit_target_tracker import main as run_profit_target_tracker_main


def _write_waiting_orchestrator_fixture(hfm: Path) -> None:
    (hfm / "agent" / "QuantGod_SimToLiveOrchestrator.json").write_text(
        json.dumps({
            "status": "WAITING_EXECUTION_MODE_ACTIVATION",
            "dataPlaneOrchestratorReady": True,
            "executionModeOnlyBlocked": True,
            "allExecutionActivationGatesPassed": False,
            "executionActivationGateSummary": {
                "total": 4,
                "passed": 0,
                "blocked": 4,
                "allPassed": False,
                "failedGateFields": ["livePilotMode", "readOnlyMode", "executionEnabled", "tradeAllowed"],
                "blockerCodes": [
                    "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
                    "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                    "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
                    "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
                ],
            },
            "allExecutionReleaseTokensProvided": False,
            "executionReleaseGateSummary": {
                "total": 5,
                "released": 0,
                "blocked": 5,
                "allReleased": False,
                "blockerCodes": [
                    "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
                    "REQUEST_READER_RELEASE_TOKEN_MISSING",
                    "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                    "RECEIPT_WRITER_RELEASE_TOKEN_MISSING",
                    "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
                ],
            },
            "executionReleaseGateChecklist": [
                {
                    "gateId": "broker_order_send_release",
                    "labelZh": "Broker OrderSend",
                    "sourceArtifact": "brokerOrderSendReview",
                    "dataPlaneReady": True,
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "passed": False,
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                    "sideEffectZh": "调用 MT5 OrderSend",
                },
            ],
            "executionReleaseReadinessPacket": {
                "schema": "quantgod.execution_release_readiness_packet.v1",
                "status": "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE",
                "statusZh": "5 个 release token 未释放，且 4 个 MT5 执行模式闸门未通过",
                "releaseReady": False,
                "canReleaseExecutionNow": False,
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "requestFilesWritten": False,
                "brokerCallsMade": False,
                "blockedGateCount": 5,
                "blockedGateIds": ["broker_order_send_release"],
                "blockedReleaseTokenCodes": ["BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING"],
                "gates": [{
                    "gateId": "broker_order_send_release",
                    "sideEffectAllowedNow": False,
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                }],
            },
            "stages": [
                {"stageId": "promotion_controller", "approvalWaitResolved": True},
                {"stageId": "review_packet", "approvalWaitResolved": True},
                {"stageId": "approval_evidence", "approvalWaitResolved": True},
            ],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "requestFilesWritten": False,
            "brokerCallsMade": False,
        }),
        encoding="utf-8",
    )


class ProfitTargetTrackerTests(unittest.TestCase):
    def test_status_reads_report_runtime_dir_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = root / "primary"
            report_runtime = root / "hfm"
            payload = {
                "schema": "quantgod.profit_target_tracker.v1",
                "status": "TARGET_REACHED",
                "runtimeDir": str(primary),
            }
            report_path(report_runtime).parent.mkdir(parents=True)
            report_path(report_runtime).write_text(json.dumps(payload), encoding="utf-8")

            import contextlib
            import io

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = run_profit_target_tracker_main([
                    "--runtime-dir",
                    str(primary),
                    "--report-runtime-dir",
                    str(report_runtime),
                    "status",
                ])

            self.assertEqual(exit_code, 0)
            status = json.loads(stdout.getvalue())
            self.assertEqual(status["status"], "TARGET_REACHED")
            self.assertEqual(status["statusLookupRuntimeDir"], str(report_runtime.resolve()))

    def test_tracks_verified_usd_without_counting_cent_as_usd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            execution = runtime / "execution"
            execution.mkdir(parents=True)
            rows = [
                {"eventType": "TRADE_OUTCOME", "symbol": "USDJPY", "profitUsd": 7.5, "ticket": "usd-1"},
                {"eventType": "HISTORY_CLOSE", "symbol": "USDJPYc", "profitUSC": 250, "ticket": "cent-1"},
                {"eventType": "ORDER_SEND", "symbol": "USDJPY", "profitUsd": 99, "ticket": "send-not-counted"},
            ]
            (execution / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows),
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, target_usd=20, write=True)

            self.assertEqual(payload["schema"], "quantgod.profit_target_tracker.v1")
            self.assertEqual(payload["progress"]["verifiedUsdProfit"], 7.5)
            self.assertEqual(payload["progress"]["centAccountProfitUSC"], 250.0)
            self.assertEqual(payload["progress"]["estimatedUsdFromCentAccount"], 2.5)
            self.assertEqual(payload["progress"]["remainingUsd"], 12.5)
            self.assertFalse(payload["targetReached"])
            self.assertFalse(payload["safety"]["orderSendAllowed"])
            self.assertFalse(payload["safety"]["writesMt5OrderRequest"])
            self.assertTrue(report_path(runtime).exists())
            saved = read_profit_target_tracker(runtime)
            self.assertEqual(saved["progress"]["verifiedUsdProfit"], 7.5)

    def test_reaches_target_only_with_explicit_usd_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            evidence = runtime / "evidence_os"
            evidence.mkdir(parents=True)
            rows = [
                {"eventType": "TRADE_OUTCOME", "currency": "USD", "profit": "11.25", "ticket": "a"},
                {"eventType": "POSITION_CLOSE", "netProfitUsd": "9.00", "ticket": "b"},
            ]
            (evidence / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows),
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, target_usd=20, write=False)

            self.assertEqual(payload["status"], "TARGET_REACHED")
            self.assertTrue(payload["targetReached"])
            self.assertEqual(payload["progress"]["verifiedUsdProfit"], 20.25)
            self.assertEqual(payload["progress"]["remainingUsd"], 0.0)
            self.assertTrue(payload["laneTargets"]["forexMt5"]["targetReached"])

    def test_collects_hfm_and_spread_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "primary"
            hfm = root / "hfm"
            (runtime / "adaptive").mkdir(parents=True)
            (hfm / "hfm_crypto").mkdir(parents=True)
            (runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json").write_text(
                json.dumps({"topPolicy": {"spreadGate": {"tier": "HARD_WIDE", "spreadPips": 5.5}}}),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps({
                    "status": "WAITING_HFM_CRYPTO_SIMULATION_PROFILE",
                    "qualified": False,
                    "reasonZh": "缺少模拟 profile",
                }),
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, hfm_runtime_dir=hfm, target_usd=20, write=False)
            codes = {row["code"] for row in payload["blockers"]}

            self.assertIn("USDJPY_SPREAD_GATE_ACTIVE", codes)
            self.assertIn("WAITING_HFM_CRYPTO_SIMULATION_PROFILE", codes)
            self.assertEqual(payload["status"], "TRACKING_BLOCKED_NOT_REACHED")
            self.assertFalse(payload["safety"]["mt5OrderSendAllowed"])

    def test_latest_dashboard_diagnostics_can_clear_stale_spread_blocker(self) -> None:
        old_env = {
            "QG_PROFIT_TRACKER_INCLUDE_GLOBAL_MT5": os.environ.get("QG_PROFIT_TRACKER_INCLUDE_GLOBAL_MT5"),
            "QG_MT5_FILES_DIR": os.environ.get("QG_MT5_FILES_DIR"),
            "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": os.environ.get("QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY"),
        }
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                runtime = root / "runtime"
                mt5_files = root / "mt5_files"
                runtime.mkdir()
                mt5_files.mkdir()
                stale_diag = runtime / "QuantGod_USDJPYRsiEntryDiagnostics.json"
                stale_diag.write_text(
                    json.dumps(
                        {
                            "schema": "quantgod.mt5.usdjpy_rsi_entry_diagnostics.v1",
                            "symbol": "USDJPYc",
                            "state": "SPREAD_BLOCK",
                            "guards": {"spreadPips": 6.5, "spreadAllowed": False},
                        }
                    ),
                    encoding="utf-8",
                )
                dashboard = mt5_files / "QuantGod_Dashboard.json"
                dashboard.write_text(
                    json.dumps(
                        {
                            "timestamp": "2026.06.05 12:00:00",
                            "watchlist": "USDJPYc",
                            "runtime": {"tradeStatus": "READY", "tickAgeSeconds": 1},
                            "market": {"symbol": "USDJPYc", "spread": 0.2},
                            "usdJpyRsiEntryDiagnostics": {
                                "schema": "quantgod.mt5.usdjpy_rsi_entry_diagnostics.v1",
                                "symbol": "USDJPYc",
                                "state": "WAITING_RSI_SIGNAL",
                                "guards": {"spreadPips": 0.2, "spreadAllowed": True},
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                now = time.time()
                os.utime(stale_diag, (now - 3600, now - 3600))
                os.utime(dashboard, (now, now))
                os.environ["QG_PROFIT_TRACKER_INCLUDE_GLOBAL_MT5"] = "1"
                os.environ["QG_MT5_FILES_DIR"] = str(mt5_files)
                os.environ["QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY"] = "1"

                payload = build_profit_target_tracker(runtime, target_usd=20, write=False)
                codes = {row["code"] for row in payload["blockers"]}

                self.assertNotIn("USDJPY_SPREAD_GATE_ACTIVE", codes)
                self.assertFalse(payload["safety"]["orderSendAllowed"])
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_allows_one_profitable_lane_to_reach_execution_review_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "primary"
            hfm = root / "hfm"
            (runtime / "execution").mkdir(parents=True)
            (hfm / "hfm_crypto").mkdir(parents=True)
            (runtime / "execution" / "QuantGod_LiveExecutionFeedback.jsonl").write_text(
                json.dumps({"eventType": "TRADE_OUTCOME", "symbol": "USDJPY", "profitUsd": 25, "ticket": "fx"}) + "\n",
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, hfm_runtime_dir=hfm, target_usd=20, write=False)

            self.assertTrue(payload["laneTargets"]["forexMt5"]["targetReached"])
            self.assertFalse(payload["laneTargets"]["btcCryptoCfd"]["targetReached"])
            self.assertTrue(payload["targetReached"])
            self.assertTrue(payload["executionTargetReached"])
            self.assertTrue(payload["dualTargetReached"])
            self.assertEqual(payload["combinedTarget"]["qualifyingLaneIds"], ["forexMt5"])
            self.assertTrue(payload["combinedTarget"]["singleLaneTargetReached"])
            self.assertFalse(payload["combinedTarget"]["allRequiredLanesMustBePositive"])

            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "btc-agent", "pnl": 21.5, "tradeCount": 30}},
                }),
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, hfm_runtime_dir=hfm, target_usd=20, write=False)

            self.assertTrue(payload["laneTargets"]["forexMt5"]["targetReached"])
            self.assertTrue(payload["laneTargets"]["btcCryptoCfd"]["targetReached"])
            self.assertTrue(payload["targetReached"])
            self.assertTrue(payload["executionTargetReached"])
            self.assertTrue(payload["dualTargetReached"])
            self.assertNotIn(
                "HFM_SIMULATION_PROFILE_MISSING",
                {row["code"] for row in payload["blockers"]},
            )

    def test_counts_qualified_forex_simulation_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "primary"
            hfm = root / "hfm"
            (runtime / "forex").mkdir(parents=True)
            (hfm / "hfm_crypto").mkdir(parents=True)
            (runtime / "forex" / "QuantGod_ForexMt5SimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "fx-agent", "symbol": "USDJPYc", "pnlUsd": 22.25}},
                }),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "btc-agent", "symbol": "BTCUSD", "pnlUsd": 21.5}},
                }),
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, hfm_runtime_dir=hfm, target_usd=20, write=False)

            self.assertTrue(payload["laneTargets"]["forexMt5"]["targetReached"])
            self.assertEqual(payload["laneTargets"]["forexMt5"]["simulationVerifiedUsdProfit"], 22.25)
            self.assertEqual(payload["laneTargets"]["forexMt5"]["evidence"][0]["evidenceType"], "simulation_profile")
            self.assertTrue(payload["laneTargets"]["btcCryptoCfd"]["targetReached"])
            self.assertTrue(payload["dualTargetReached"])

    def test_profit_tracker_surfaces_cutover_and_rollback_ready_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "primary"
            hfm = root / "hfm"
            (runtime / "forex").mkdir(parents=True)
            (hfm / "hfm_crypto").mkdir(parents=True)
            (hfm / "agent").mkdir(parents=True)
            (runtime / "forex" / "QuantGod_ForexMt5SimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "fx-agent", "symbol": "USDJPYc", "pnlUsd": 72.0}},
                }),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "btc-agent", "symbol": "BTCUSD", "pnlUsd": 65.22}},
                }),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json").write_text(
                json.dumps({"standaloneExporterBundle": {"runtimeProbeTickDetected": True}}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionReviewPacket.json").write_text(json.dumps({"status": "READY"}), encoding="utf-8")
            (hfm / "agent" / "QuantGod_LiveOperatorApprovalEvidenceReview.json").write_text(
                json.dumps({"status": "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED", "operatorApprovalProvided": True, "reviewPacketHash": "hash-ready"}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_DryRunLiveExecutionPlan.json").write_text(
                json.dumps({
                    "reviewPacketHash": "hash-ready",
                    "dryRunIntents": [{
                        "intentId": "intent-btc",
                        "lane": "HFM_CRYPTO_CFD",
                        "canonicalSymbol": "BTCUSD",
                        "brokerSymbol": "#BTCUSD",
                        "volumeLots": 0,
                        "orderType": "dry_run_market_or_limit",
                        "dryRunOnly": True,
                        "orderSendAllowed": False,
                    }],
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionLaneSpec.json").write_text(
                json.dumps({"reviewPacketHash": "hash-ready", "readyForImplementationReview": True, "approvalEvidenceAccepted": True, "orderSendAllowed": False}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveDryRunIntentReplay.json").write_text(
                json.dumps({"reviewPacketHash": "hash-ready", "replayPassed": True}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveRuntimePreflightProbe.json").write_text(
                json.dumps({
                    "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                    "reviewPacketHash": "hash-ready",
                    "runtimeProbePassed": True,
                    "dataPlaneReadyForLivePilotReview": True,
                    "executionModeReady": True,
                    "orderSendAllowed": False,
                    "dashboardSnapshot": {
                        "found": True,
                        "fresh": True,
                        "livePilotMode": True,
                        "readOnlyMode": False,
                        "executionEnabled": True,
                        "tradeAllowed": True,
                    },
                    "laneRuntimeChecks": [{
                        "lane": "HFM_CRYPTO_CFD",
                        "canonicalSymbol": "BTCUSD",
                        "brokerSymbol": "#BTCUSD",
                        "symbolPresentInSidecarSpecs": True,
                        "symbolPresentInRuntimeProbe": True,
                        "symbolMappingOk": True,
                        "runtimeProbeFresh": True,
                        "riskLimitsPresent": True,
                        "passed": True,
                    }],
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_MT5OrderRequestContract.json").write_text(
                json.dumps({
                    "status": "READY_FOR_ORDER_REQUEST_CONTRACT_REVIEW",
                    "statusZh": "可进入 MT5 请求合约代码评审",
                    "reviewPacketHash": "hash-ready",
                    "readyForAdapterCodeReview": True,
                    "runtimePreflightDataPlaneReadyForReview": True,
                    "orderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LivePilotActivationReview.json").write_text(
                json.dumps({"status": "READY_FOR_LIVE_PILOT_ACTIVATION_REVIEW", "orderSendAllowed": False}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionRollbackReview.json").write_text(
                json.dumps({
                    "status": "READY_FOR_LIVE_EXECUTION_ROLLBACK_REVIEW",
                    "readyForLiveExecutionRollbackReview": True,
                    "dataPlaneRollbackReady": True,
                    "orderSendAllowed": False,
                    "autoDisableMutationAllowed": False,
                    "rollbackMatrix": [
                        {"id": "missing_or_failed_receipt", "passed": True},
                        {"id": "broker_send_wrapper_not_ready", "passed": True},
                        {"id": "ea_reader_unexpectedly_enabled_or_consuming", "passed": True},
                    ],
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionCutoverReview.json").write_text(
                json.dumps({
                    "status": "READY_FOR_SEPARATE_LIVE_EXECUTION_CUTOVER_IMPLEMENTATION_REVIEW",
                    "statusZh": "可进入单独 live execution cutover 实现评审",
                    "readyForSeparateLiveExecutionCutoverImplementationReview": True,
                    "dataPlaneCutoverReady": True,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                    "implementationHandoff": {
                        "approvedLanes": ["hfmCryptoCfd"],
                        "plannedWriteCount": 1,
                        "brokerSendPlanCount": 1,
                        "rollbackRuleCount": 3,
                        "reviewOnlyReceiptCount": 1,
                        "implementationMustStaySeparate": True,
                        "requiredFuturePrs": ["rollback_and_auto_disable_path"],
                    },
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionImplementationSpec.json").write_text(
                json.dumps({
                    "status": "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW",
                    "readyForLiveExecutionImplementationSpecReview": True,
                    "microLiveExecutionBlueprint": {
                        "mode": "MICRO_LIVE_EXECUTION_IMPLEMENTATION_BLUEPRINT_REVIEW_ONLY",
                        "status": "READY_TO_IMPLEMENT_DISABLED_FIRST",
                        "statusZh": "可开始拆分实现真实执行 lane，但本 artifact 仍不启用下单",
                        "selectedLane": "HFM_CRYPTO_CFD",
                        "requestId": "intent-btc",
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                        "accountNumber": 186054398,
                        "brokerServer": "HFMarketsGlobal-Live12",
                        "initialLiveVolumeLotsCandidate": 0.01,
                        "initialLiveVolumeRequiresSeparateRiskReview": True,
                        "packageCount": 5,
                        "allRequiredStepsMapped": True,
                        "rejectionReceiptPlanComplete": True,
                        "duplicateRequestIds": [],
                        "hardBlocksBeforeAnyLiveOrder": [
                            {"code": "EXECUTION_CODE_NOT_DEPLOYED", "reasonZh": "执行代码未部署。"},
                        ],
                        "orderSendAllowed": False,
                        "mt5OrderSendAllowed": False,
                        "requestFilesWritten": False,
                        "receiptFilesWritten": False,
                        "brokerCallsMade": False,
                    },
                }),
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, hfm_runtime_dir=hfm, target_usd=50, write=False)
            review = payload["liveExecutionReview"]
            decision = payload["simToLiveDecision"]

            self.assertEqual(review["status"], "READY_FOR_SEPARATE_LIVE_EXECUTION_CUTOVER_IMPLEMENTATION_REVIEW")
            self.assertTrue(review["readyForLiveExecutionCutoverReview"])
            self.assertTrue(review["readyForLiveExecutionRollbackReview"])
            self.assertTrue(review["separateExecutionImplementationReviewReady"])
            self.assertTrue(review["readyForLiveExecutionImplementationSpecReview"])
            self.assertEqual(review["implementationSpecStatus"], "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW")
            self.assertEqual(
                review["microLiveExecutionBlueprint"]["mode"],
                "MICRO_LIVE_EXECUTION_IMPLEMENTATION_BLUEPRINT_REVIEW_ONLY",
            )
            self.assertEqual(review["microLiveExecutionBlueprint"]["selectedLane"], "HFM_CRYPTO_CFD")
            self.assertEqual(review["microLiveExecutionBlueprint"]["brokerSymbol"], "#BTCUSD")
            self.assertEqual(review["microLiveExecutionBlueprint"]["initialLiveVolumeLotsCandidate"], 0.01)
            self.assertEqual(review["microLiveExecutionBlueprint"]["packageCount"], 5)
            self.assertTrue(review["microLiveExecutionBlueprint"]["allRequiredStepsMapped"])
            self.assertFalse(review["microLiveExecutionBlueprint"]["orderSendAllowed"])
            self.assertFalse(review["microLiveExecutionBlueprint"]["brokerCallsMade"])
            self.assertEqual(review["cutoverHandoff"]["rollbackRuleCount"], 3)
            self.assertEqual(review["rollbackSummary"]["rollbackRuleCount"], 3)
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])
            self.assertEqual(decision["status"], "TARGET_REACHED_READY_FOR_CUTOVER_IMPLEMENTATION_REVIEW")
            self.assertTrue(decision["cutoverReady"])
            self.assertTrue(decision["rollbackReady"])
            self.assertTrue(decision["separateExecutionImplementationReviewReady"])
            self.assertEqual(payload["liveCutoverGate"]["status"], "READY_FOR_CUTOVER_IMPLEMENTATION_REVIEW")
            self.assertTrue(payload["liveCutoverGate"]["cutoverReady"])
            self.assertTrue(payload["liveCutoverGate"]["rollbackReady"])
            self.assertTrue(payload["liveCutoverGate"]["separateExecutionImplementationReviewReady"])
            self.assertFalse(decision["orderSendAllowed"])
            self.assertFalse(decision["mt5OrderSendAllowed"])
            self.assertFalse(decision["brokerCallsMade"])
            self.assertIn("cutover/rollback", decision["authorizationVsExecution"]["whyNotLiveNowZh"])

    def test_secondary_hfm_readiness_suppresses_primary_crypto_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "primary"
            hfm = root / "hfm"
            (runtime / "agent").mkdir(parents=True)
            (hfm / "agent").mkdir(parents=True)
            (runtime / "forex").mkdir(parents=True)
            (hfm / "hfm_crypto").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_LiveAutomationReadiness.json").write_text(
                json.dumps({
                    "status": "WAITING_FOR_EVIDENCE",
                    "globalBlockers": [
                        {"code": "EXECUTION_LANE_NOT_ENABLED", "reasonZh": "只读"},
                        {"code": "NO_LANE_READY_FOR_REVIEW", "reasonZh": "primary 没有候选"},
                    ],
                    "lanes": {
                        "usdjpyMt5": {
                            "reviewBlockers": [
                                {"code": "USD_STANDARD_ENTRY_REQUIRED", "reasonZh": "外币仍需标准入场"},
                            ],
                        },
                        "hfmCryptoCfd": {
                            "reviewBlockers": [
                                {"code": "HFM_CRYPTO_LOCAL_SYMBOL_EVIDENCE_MISSING", "reasonZh": "primary 无 crypto"},
                            ],
                        },
                    },
                    "safety": {"orderSendAllowed": False},
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveAutomationReadiness.json").write_text(
                json.dumps({
                    "status": "READY_FOR_EXECUTION_REVIEW",
                    "statusZh": "可进入实盘执行审查",
                    "globalBlockers": [
                        {"code": "EXECUTION_LANE_NOT_ENABLED", "reasonZh": "只读"},
                        {"code": "SEPARATE_REVIEW_REQUIRED", "reasonZh": "需要独立执行 lane"},
                    ],
                    "lanes": {
                        "hfmCryptoCfd": {
                            "reviewCandidate": True,
                            "reviewBlockers": [
                                {"code": "HFM_CRYPTO_EXECUTION_LANE_REVIEW_REQUIRED", "reasonZh": "需执行 lane 评审"},
                            ],
                        },
                    },
                    "safety": {"orderSendAllowed": False},
                }),
                encoding="utf-8",
            )
            (runtime / "forex" / "QuantGod_ForexMt5SimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "fx-agent", "symbol": "USDJPYc", "pnlUsd": 22.25}},
                }),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "btc-agent", "symbol": "BTCUSD", "pnlUsd": 21.5}},
                }),
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, hfm_runtime_dir=hfm, target_usd=20, write=False)
            codes = {row["code"] for row in payload["blockers"]}

            self.assertTrue(payload["dualTargetReached"])
            self.assertEqual(payload["researchProgress"]["liveReadiness"]["status"], "READY_FOR_EXECUTION_REVIEW")
            self.assertIn("USD_STANDARD_ENTRY_REQUIRED", codes)
            self.assertIn("HFM_CRYPTO_EXECUTION_LANE_REVIEW_REQUIRED", codes)
            self.assertNotIn("NO_LANE_READY_FOR_REVIEW", codes)
            self.assertNotIn("HFM_CRYPTO_LOCAL_SYMBOL_EVIDENCE_MISSING", codes)

    def test_surfaces_hfm_btc_live_execution_review_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "primary"
            hfm = root / "hfm"
            (runtime / "forex").mkdir(parents=True)
            (hfm / "hfm_crypto").mkdir(parents=True)
            (hfm / "agent").mkdir(parents=True)
            (runtime / "forex" / "QuantGod_ForexMt5SimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "fx-agent", "symbol": "USDJPYc", "pnlUsd": 22.25}},
                }),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "btc-agent", "symbol": "BTCUSD", "pnlUsd": 21.5}},
                }),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json").write_text(
                json.dumps({
                    "standaloneExporterBundle": {
                        "status": "WAITING_STANDALONE_MT5_RUNTIME_PROBE_INSTALL",
                        "nextRequiredActionZh": "staged EA 已包含 runtime probe；当前 MT5 Experts 里的 EA 不是最新版或尚未编译。",
                        "runtimeProbeMissingAfterSpecs": True,
                        "runtimeProbeTickDetected": False,
                        "startupSymbol": "#BTCUSD",
                        "target": {
                            "targetExpertPath": "/tmp/Experts/QuantGod_HFMCryptoSpecExporterEA.mq5",
                            "targetExpertInstalledMatchesBundle": False,
                        },
                        "output": {
                            "expectedRuntimeProbePath": "/tmp/Files/hfm_crypto/QuantGod_HFMCryptoRuntimeProbe.json",
                        },
                    },
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_DryRunLiveExecutionPlan.json").write_text(
                json.dumps({
                    "reviewPacketHash": "hash-btc",
                    "dryRunIntents": [{
                        "intentId": "intent-btc",
                        "lane": "HFM_CRYPTO_CFD",
                        "canonicalSymbol": "BTCUSD",
                        "brokerSymbol": "#BTCUSD",
                        "volumeLots": 0,
                        "orderType": "dry_run_market_or_limit",
                        "dryRunOnly": True,
                        "orderSendAllowed": False,
                    }],
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionLaneSpec.json").write_text(
                json.dumps({"reviewPacketHash": "hash-btc", "readyForImplementationReview": True, "approvalEvidenceAccepted": True}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveDryRunIntentReplay.json").write_text(
                json.dumps({"reviewPacketHash": "hash-btc", "replayPassed": True}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveRuntimePreflightProbe.json").write_text(
                json.dumps({
                    "reviewPacketHash": "hash-btc",
                    "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                    "statusZh": "等待运行时预检证据",
                    "runtimeProbePassed": False,
                    "dashboardSnapshot": {
                        "found": True,
                        "fresh": True,
                        "tradeStatus": "SHADOW",
                        "livePilotMode": False,
                        "readOnlyMode": True,
                        "executionEnabled": False,
                        "tradeAllowed": False,
                        "permissionLayers": {
                            "terminalConnected": True,
                            "accountAuthorized": True,
                            "terminalTradeAllowed": True,
                            "programTradeAllowed": True,
                            "accountTradeAllowed": True,
                            "accountExpertTradeAllowed": True,
                            "focusSymbolTradeAllowed": True,
                            "focusSymbolTradeMode": "FULL",
                            "tradePermissionBlocker": "READ_ONLY_MODE",
                        },
                        "executionGateDiagnostics": {
                            "livePilotMode": {
                                "layer": "EA live-pilot mode",
                                "detailZh": "EA runtime 仍未确认 livePilotMode=true；当前 tradeStatus=SHADOW。",
                                "rawValue": False,
                            },
                            "tradeAllowed": {
                                "layer": "MT5 permission composite",
                                "detailZh": "MT5 terminal/account/program/symbol 交易权限均已通过；当前 composite tradeAllowed=false 的直接阻塞为 READ_ONLY_MODE。",
                                "rawValue": False,
                                "permissionLayers": {
                                    "terminalConnected": True,
                                    "accountAuthorized": True,
                                    "terminalTradeAllowed": True,
                                    "programTradeAllowed": True,
                                    "accountTradeAllowed": True,
                                    "accountExpertTradeAllowed": True,
                                    "focusSymbolTradeAllowed": True,
                                    "focusSymbolTradeMode": "FULL",
                                    "tradePermissionBlocker": "READ_ONLY_MODE",
                                },
                            },
                        },
                        "symbolNames": ["USDJPY"],
                    },
                    "laneRuntimeChecks": [{
                        "lane": "HFM_CRYPTO_CFD",
                        "canonicalSymbol": "BTCUSD",
                        "brokerSymbol": "#BTCUSD",
                        "symbolPresentInSnapshot": False,
                        "symbolPresentInSidecarSpecs": True,
                        "symbolMappingOk": True,
                        "spreadFieldPresent": False,
                        "sidecarLiveTickPresent": False,
                        "passed": False,
                    }],
                    "blockers": [
                        {
                            "code": "MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD",
                            "reasonZh": "HFM specs 已证明 broker symbol 存在，但当前 MT5 dashboard/watchlist 尚未选中该 symbol 并输出实时 tick。",
                            "value": "#BTCUSD",
                        },
                        {
                            "code": "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING",
                            "reasonZh": "当前 MT5 dashboard 尚未输出该 symbol 的实时 bid/ask 或 spread，无法做价差预检。",
                            "value": "#BTCUSD",
                        },
                    ],
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_MT5OrderRequestContract.json").write_text(
                json.dumps({
                    "status": "WAITING_ORDER_REQUEST_CONTRACT_INPUTS",
                    "statusZh": "等待运行时预检通过",
                    "reviewPacketHash": "hash-btc",
                    "readyForAdapterCodeReview": False,
                    "orderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                    "blockers": [
                        {"code": "RUNTIME_PREFLIGHT_NOT_PASSED", "reasonZh": "运行时预检尚未通过。"},
                    ],
                }),
                encoding="utf-8",
            )
            payload = build_profit_target_tracker(runtime, hfm_runtime_dir=hfm, target_usd=20, write=False)
            review = payload["liveExecutionReview"]

            self.assertEqual(review["dryRunIntent"]["canonicalSymbol"], "BTCUSD")
            self.assertEqual(review["dryRunIntent"]["brokerSymbol"], "#BTCUSD")
            self.assertTrue(review["readyForImplementationReview"])
            self.assertTrue(review["replayPassed"])
            self.assertFalse(review["runtimeProbePassed"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertEqual(
                review["primaryActionableBlocker"]["code"],
                "HFM_CRYPTO_RUNTIME_PROBE_EXPORTER_NOT_CURRENT",
            )
            self.assertEqual(
                review["summaryZh"],
                "#BTCUSD runtime probe 缺失：当前 MT5 Experts 里的 exporter EA 不是最新版，需要安装/编译带 runtime probe 的只读 HFM crypto exporter EA。",
            )
            self.assertEqual(review["primaryActionableBlocker"]["source"], "hfm_crypto_standalone_exporter_bundle")
            self.assertTrue(review["runtimeCheck"]["symbolPresentInSidecarSpecs"])
            self.assertTrue(review["runtimeCheck"]["symbolMappingOk"])
            self.assertFalse(review["runtimeCheck"]["symbolPresentInSnapshot"])
            self.assertFalse(review["runtimeCheck"]["sidecarLiveTickPresent"])
            review_codes = {row["code"] for row in review["blockers"]}
            top_level_codes = {row["code"] for row in payload["blockers"]}
            self.assertIn("HFM_CRYPTO_RUNTIME_PROBE_EXPORTER_NOT_CURRENT", review_codes)
            self.assertIn("RUNTIME_PREFLIGHT_NOT_PASSED", review_codes)
            self.assertIn("HFM_CRYPTO_RUNTIME_PROBE_EXPORTER_NOT_CURRENT", top_level_codes)

    def test_live_execution_review_surfaces_data_plane_ready_execution_gate_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "primary"
            hfm = root / "hfm"
            (runtime / "forex").mkdir(parents=True)
            (hfm / "hfm_crypto").mkdir(parents=True)
            (hfm / "agent").mkdir(parents=True)
            (runtime / "forex" / "QuantGod_ForexMt5SimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "fx-agent", "symbol": "USDJPYc", "pnlUsd": 22.25}},
                }),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps({
                    "simulationQualified": True,
                    "profile": {"metrics": {"agentId": "btc-agent", "symbol": "BTCUSD", "pnlUsd": 21.5}},
                }),
                encoding="utf-8",
            )
            (hfm / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json").write_text(
                json.dumps({"standaloneExporterBundle": {"runtimeProbeTickDetected": True}}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_DryRunLiveExecutionPlan.json").write_text(
                json.dumps({
                    "reviewPacketHash": "hash-btc",
                    "dryRunIntents": [{
                        "intentId": "intent-btc",
                        "lane": "HFM_CRYPTO_CFD",
                        "canonicalSymbol": "BTCUSD",
                        "brokerSymbol": "#BTCUSD",
                        "volumeLots": 0,
                        "orderType": "dry_run_market_or_limit",
                        "dryRunOnly": True,
                        "orderSendAllowed": False,
                    }],
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionLaneSpec.json").write_text(
                json.dumps({"reviewPacketHash": "hash-btc", "readyForImplementationReview": True, "approvalEvidenceAccepted": True}),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveDryRunIntentReplay.json").write_text(
                json.dumps({"reviewPacketHash": "hash-btc", "replayPassed": True}),
                encoding="utf-8",
            )
            execution_blockers = [
                {"code": "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED", "reasonZh": "MT5 dashboard 尚未证明 livePilotMode=true。"},
                {"code": "MT5_READ_ONLY_MODE_STILL_ACTIVE", "reasonZh": "MT5 dashboard 仍处于 readOnly/shadow 模式。"},
            ]
            file_evidence_blockers = [
                {
                    "code": "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF",
                    "reasonZh": "Live16 启动 ini 的 [Experts] AllowLiveTrading=0。",
                    "value": "0",
                },
                {
                    "code": "DEPLOYED_PRESET_READ_ONLY_TRUE",
                    "reasonZh": "当前部署 preset 仍为 ReadOnlyMode=true。",
                    "value": "true",
                },
                {
                    "code": "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF",
                    "reasonZh": "当前部署 preset 仍为 EnablePilotAutoTrading=false。",
                    "value": "false",
                },
            ]
            file_evidence = {
                "startupConfig": {
                    "path": str(hfm / "drive_c" / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"),
                    "exists": True,
                    "values": {
                        "AllowLiveTrading": "0",
                        "ExpertParameters": "QuantGod_MT5_HFM_LiveSecondary.set",
                    },
                },
                "deployedPreset": {
                    "path": str(hfm / "MQL5" / "Presets" / "QuantGod_MT5_HFM_LiveSecondary.set"),
                    "exists": True,
                    "values": {
                        "ReadOnlyMode": "true",
                        "EnablePilotAutoTrading": "false",
                    },
                },
                "restartWouldKeepExecutionDisabled": True,
                "blockingEvidence": file_evidence_blockers,
            }
            (hfm / "agent" / "QuantGod_LiveRuntimePreflightProbe.json").write_text(
                json.dumps({
                    "reviewPacketHash": "hash-btc",
                    "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                    "statusZh": "数据面预检已通过，等待执行模式闸门",
                    "runtimeProbePassed": False,
                    "dataPlaneReadyForLivePilotReview": True,
                    "executionModeReady": False,
                    "executionModeOnlyBlocked": True,
                    "nonExecutionBlockers": [],
                    "executionModeBlockers": execution_blockers,
                    "dashboardSnapshot": {
                        "found": True,
                        "fresh": True,
                        "tradeStatus": "SHADOW",
                        "livePilotMode": False,
                        "readOnlyMode": True,
                        "executionEnabled": False,
                        "tradeAllowed": False,
                        "permissionLayers": {
                            "terminalConnected": True,
                            "accountAuthorized": True,
                            "terminalTradeAllowed": True,
                            "programTradeAllowed": True,
                            "accountTradeAllowed": True,
                            "accountExpertTradeAllowed": True,
                            "focusSymbolTradeAllowed": True,
                            "focusSymbolTradeMode": "FULL",
                            "tradePermissionBlocker": "READ_ONLY_MODE",
                        },
                        "executionGateDiagnostics": {
                            "livePilotMode": {
                                "layer": "EA live-pilot mode",
                                "detailZh": "EA runtime 仍未确认 livePilotMode=true；当前 tradeStatus=SHADOW。",
                                "rawValue": False,
                            },
                            "tradeAllowed": {
                                "layer": "MT5 permission composite",
                                "detailZh": "MT5 terminal/account/program/symbol 交易权限均已通过；当前 composite tradeAllowed=false 的直接阻塞为 READ_ONLY_MODE。",
                                "rawValue": False,
                                "permissionLayers": {
                                    "terminalConnected": True,
                                    "accountAuthorized": True,
                                    "terminalTradeAllowed": True,
                                    "programTradeAllowed": True,
                                    "accountTradeAllowed": True,
                                    "accountExpertTradeAllowed": True,
                                    "focusSymbolTradeAllowed": True,
                                    "focusSymbolTradeMode": "FULL",
                                    "tradePermissionBlocker": "READ_ONLY_MODE",
                                },
                            },
                        },
                        "symbolNames": ["USDJPY"],
                    },
                    "laneRuntimeChecks": [{
                        "lane": "HFM_CRYPTO_CFD",
                        "canonicalSymbol": "BTCUSD",
                        "brokerSymbol": "#BTCUSD",
                        "symbolPresentInSnapshot": False,
                        "symbolPresentInSidecarSpecs": True,
                        "symbolPresentInRuntimeProbe": True,
                        "symbolMappingOk": True,
                        "sidecarLiveTickPresent": True,
                        "sidecarSpreadValue": 61.0,
                        "runtimeProbeSource": "dashboard",
                        "runtimeProbeFresh": True,
                        "riskLimitsPresent": True,
                        "passed": True,
                    }],
                    "blockers": execution_blockers,
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_MT5OrderRequestContract.json").write_text(
                json.dumps({
                    "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                    "statusZh": "数据面已通过，等待执行模式闸门",
                    "reviewPacketHash": "hash-btc",
                    "readyForAdapterCodeReview": False,
                    "runtimePreflightDataPlaneReadyForReview": True,
                    "runtimePreflightExecutionModeOnlyBlocked": True,
                    "runtimePreflightNonExecutionBlockers": [],
                    "runtimePreflightExecutionModeBlockers": execution_blockers,
                    "orderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                    "blockers": [
                        {"code": "EXECUTION_MODE_GATES_NOT_ACTIVE", "reasonZh": "数据面预检已通过，但 MT5/EA 执行模式闸门尚未打开。"},
                        *execution_blockers,
                    ],
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LivePilotActivationReview.json").write_text(
                json.dumps({
                    "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                    "presetActivationPackage": {
                        "liveRuntimeFileEvidence": file_evidence,
                    },
                    "blockers": [
                        {"code": "EXECUTION_MODE_GATES_NOT_ACTIVE", "reasonZh": "等待执行模式闸门。"},
                        *file_evidence_blockers,
                    ],
                    "orderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionCutoverReview.json").write_text(
                json.dumps({
                    "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                    "executionModeFileEvidence": file_evidence,
                    "blockers": [
                        {"code": "EXECUTION_MODE_GATES_NOT_ACTIVE", "reasonZh": "等待执行模式闸门。"},
                        *file_evidence_blockers,
                    ],
                    "orderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                }),
                encoding="utf-8",
            )
            (hfm / "agent" / "QuantGod_LiveExecutionImplementationSpec.json").write_text(
                json.dumps({
                    "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                    "statusZh": "live execution implementation spec 数据面已通过，等待执行模式闸门",
                    "readyForLiveExecutionImplementationSpecReview": False,
                    "dataPlaneImplementationSpecReady": True,
                    "executionModeOnlyBlocked": True,
                    "disabledFirstImplementationWorkReady": True,
                    "nextCodeWorkAllowedInReviewOnly": True,
                    "liveExecutionStillForbidden": True,
                    "implementationReadinessSummary": {
                        "status": "READY_TO_IMPLEMENT_DISABLED_FIRST",
                        "statusZh": "可继续 disabled-first 实现，但真实订单仍禁止",
                        "allowedWorkType": "CODE_AND_REVIEW_ARTIFACTS_ONLY",
                        "forbiddenWorkType": "LIVE_ORDER_EXECUTION",
                        "packageCount": 5,
                        "allRequiredStepsMapped": True,
                        "nextRequiredActionZh": "继续实现 request writer/EA reader/broker wrapper 的禁用态代码和审查 artifact。",
                    },
                    "microLiveExecutionBlueprint": {
                        "mode": "DISABLED_FIRST_REVIEW_ONLY",
                        "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                        "statusZh": "等待执行模式闸门",
                        "selectedLane": "HFM_CRYPTO_CFD",
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                        "packageCount": 5,
                        "allRequiredStepsMapped": True,
                        "rejectionReceiptPlanComplete": True,
                        "disabledFirstImplementationWorkReady": True,
                        "nextCodeWorkAllowedInReviewOnly": True,
                        "liveExecutionStillForbidden": True,
                        "orderSendAllowed": False,
                        "mt5OrderSendAllowed": False,
                        "requestFilesWritten": False,
                        "receiptFilesWritten": False,
                        "brokerCallsMade": False,
                    },
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                    "requestFilesWritten": False,
                    "receiptFilesWritten": False,
                    "brokerCallsMade": False,
                }),
                encoding="utf-8",
            )
            _write_waiting_orchestrator_fixture(hfm)

            payload = build_profit_target_tracker(runtime, hfm_runtime_dir=hfm, target_usd=20, write=False)
            review = payload["liveExecutionReview"]
            codes = {row["code"] for row in review["blockers"]}

            self.assertEqual(review["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertEqual(review["statusZh"], "数据面已通过，等待执行模式闸门")
            self.assertTrue(review["runtimePreflightDataPlaneReadyForReview"])
            self.assertTrue(review["runtimePreflightExecutionModeOnlyBlocked"])
            self.assertEqual(review["runtimePreflightNonExecutionBlockers"], [])
            self.assertEqual(review["primaryActionableBlocker"]["code"], "DEPLOYED_PRESET_READ_ONLY_TRUE")
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", codes)
            self.assertIn("STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF", codes)
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", codes)
            self.assertNotIn("RUNTIME_PREFLIGHT_NOT_PASSED", codes)
            self.assertEqual(
                review["executionModeFileEvidence"]["deployedPreset"]["values"]["ReadOnlyMode"],
                "true",
            )
            self.assertTrue(review["disabledFirstImplementationWorkReady"])
            self.assertTrue(review["nextCodeWorkAllowedInReviewOnly"])
            self.assertTrue(review["liveExecutionStillForbidden"])
            self.assertEqual(
                review["implementationReadinessSummary"]["status"],
                "READY_TO_IMPLEMENT_DISABLED_FIRST",
            )
            self.assertEqual(review["microLiveExecutionBlueprint"]["packageCount"], 5)
            self.assertTrue(review["microLiveExecutionBlueprint"]["disabledFirstImplementationWorkReady"])
            self.assertFalse(review["microLiveExecutionBlueprint"]["orderSendAllowed"])
            self.assertFalse(review["microLiveExecutionBlueprint"]["brokerCallsMade"])
            self.assertTrue(review["approvalWaitResolved"])
            self.assertEqual(
                review["approvalWaitResolvedStages"],
                ["promotion_controller", "review_packet", "approval_evidence"],
            )
            self.assertEqual(review["executionReleaseGateSummary"]["blocked"], 5)
            self.assertEqual(
                review["executionReleaseReadinessPacket"]["status"],
                "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE",
            )
            self.assertFalse(review["executionReleaseReadinessPacket"]["canReleaseExecutionNow"])
            self.assertFalse(review["executionReleaseReadinessPacket"]["brokerCallsMade"])
            self.assertFalse(review["allExecutionReleaseTokensProvided"])
            self.assertFalse(review["orderSendAllowed"])
            decision = payload["simToLiveDecision"]
            self.assertEqual(decision["status"], "TARGET_REACHED_WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(decision["targetReached"])
            self.assertTrue(decision["dataPlaneReady"])
            self.assertTrue(decision["disabledFirstImplementationWorkReady"])
            self.assertTrue(decision["nextCodeWorkAllowedInReviewOnly"])
            self.assertTrue(decision["liveExecutionStillForbidden"])
            self.assertEqual(
                decision["implementationReadinessSummary"]["allowedWorkType"],
                "CODE_AND_REVIEW_ARTIFACTS_ONLY",
            )
            self.assertTrue(decision["executionModeOnlyBlocked"])
            self.assertFalse(decision["allActivationGatesPassed"])
            auth_vs_execution = decision["authorizationVsExecution"]
            self.assertEqual(auth_vs_execution["schema"], "quantgod.authorization_vs_execution.v1")
            self.assertTrue(auth_vs_execution["chatAuthorizationAcknowledged"])
            self.assertTrue(auth_vs_execution["operatorApprovalEvidenceAccepted"])
            self.assertTrue(auth_vs_execution["approvalWaitResolved"])
            self.assertTrue(auth_vs_execution["simulationTargetReached"])
            self.assertTrue(auth_vs_execution["executionModeOnlyBlocked"])
            self.assertTrue(auth_vs_execution["releaseTokensBlocked"])
            self.assertFalse(auth_vs_execution["executionCanStartNow"])
            self.assertIn("聊天/操作员授权证据已接受", auth_vs_execution["whyNotLiveNowZh"])
            self.assertIn("不再等待用户确认", auth_vs_execution["whyNotLiveNowZh"])
            self.assertIn("执行模式闸门", auth_vs_execution["whyNotLiveNowZh"])
            self.assertIn("execution release token", auth_vs_execution["whyNotLiveNowZh"])
            self.assertEqual(
                auth_vs_execution["remainingGateFields"],
                ["livePilotMode", "readOnlyMode", "executionEnabled", "tradeAllowed"],
            )
            self.assertIn("MT5_READ_ONLY_MODE_STILL_ACTIVE", auth_vs_execution["remainingBlockerCodes"])
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", auth_vs_execution["releaseTokenBlockerCodes"])
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", auth_vs_execution["fileBlockerCodes"])
            self.assertEqual(
                auth_vs_execution["primaryActionableBlocker"]["code"],
                "DEPLOYED_PRESET_READ_ONLY_TRUE",
            )
            self.assertEqual(decision["activationGateSummary"]["blocked"], 4)
            self.assertEqual(decision["executionActivationGateSummary"]["blocked"], 4)
            self.assertEqual(
                decision["executionActivationGateSummary"]["failedGateFields"],
                ["livePilotMode", "readOnlyMode", "executionEnabled", "tradeAllowed"],
            )
            self.assertEqual(
                decision["executionActivationGateChecklist"],
                decision["activationGateChecklist"],
            )
            self.assertTrue(decision["approvalWaitResolved"])
            self.assertEqual(
                decision["approvalWaitResolvedStages"],
                ["promotion_controller", "review_packet", "approval_evidence"],
            )
            self.assertFalse(decision["allExecutionReleaseTokensProvided"])
            self.assertEqual(decision["executionReleaseGateSummary"]["blocked"], 5)
            self.assertEqual(
                decision["executionReleaseReadinessPacket"]["status"],
                "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE",
            )
            self.assertFalse(decision["executionReleaseReadinessPacket"]["canReleaseExecutionNow"])
            self.assertFalse(decision["executionReleaseReadinessPacket"]["orderSendAllowed"])
            self.assertFalse(decision["executionReleaseReadinessPacket"]["brokerCallsMade"])
            self.assertIn(
                "broker_order_send_release",
                decision["executionReleaseReadinessPacket"]["blockedGateIds"],
            )
            self.assertIn(
                "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                decision["executionReleaseGateSummary"]["blockerCodes"],
            )
            self.assertEqual(
                decision["executionModeFileEvidence"]["startupConfig"]["values"]["AllowLiveTrading"],
                "0",
            )
            decision_file_codes = {row["code"] for row in decision["fileEvidenceBlockers"]}
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", decision_file_codes)
            gate_by_field = {row["field"]: row for row in decision["activationGateChecklist"]}
            self.assertEqual(gate_by_field["livePilotMode"]["expected"], True)
            self.assertEqual(gate_by_field["livePilotMode"]["current"], False)
            self.assertFalse(gate_by_field["livePilotMode"]["passed"])
            self.assertEqual(gate_by_field["livePilotMode"]["layer"], "EA live-pilot mode")
            self.assertIn("tradeStatus=SHADOW", gate_by_field["livePilotMode"]["detailZh"])
            self.assertEqual(gate_by_field["readOnlyMode"]["expected"], False)
            self.assertEqual(gate_by_field["readOnlyMode"]["current"], True)
            self.assertFalse(gate_by_field["readOnlyMode"]["passed"])
            self.assertEqual(gate_by_field["executionEnabled"]["current"], False)
            self.assertEqual(gate_by_field["tradeAllowed"]["current"], False)
            self.assertEqual(gate_by_field["tradeAllowed"]["layer"], "MT5 permission composite")
            self.assertEqual(
                gate_by_field["tradeAllowed"]["permissionLayers"]["tradePermissionBlocker"],
                "READ_ONLY_MODE",
            )
            self.assertFalse(decision["orderSendAllowed"])
            self.assertFalse(decision["writesMt5OrderRequest"])
            self.assertFalse(decision["requestFilesWritten"])
            self.assertIn("不再等待用户确认", decision["nextRequiredActionZh"])
            self.assertIn("执行模式闸门", decision["nextRequiredActionZh"])
            self.assertIn("执行模式闸门", payload["nextRequiredActionZh"])

    def test_research_progress_reports_best_ga_candidate_by_fitness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "ga_factory").mkdir(parents=True)
            (runtime / "ga_factory" / "QuantGod_GAFactoryState.json").write_text(
                json.dumps({
                    "status": "FACTORY_READY",
                    "currentGeneration": 24,
                    "candidateCount": 3,
                    "eliteCount": 0,
                    "lineageTree": {
                        "nodes": [
                            {
                                "seedId": "GA-WORSE",
                                "strategyId": "USDJPY_WORSE",
                                "generation": 24,
                                "fitness": -25.0,
                                "status": "REJECTED",
                                "blockerCode": "WALK_FORWARD_UNSTABLE",
                            },
                            {
                                "seedId": "GA-BEST",
                                "strategyId": "USDJPY_BEST",
                                "generation": 24,
                                "fitness": -1.25,
                                "status": "REJECTED",
                                "promotionStage": "REJECTED",
                                "blockerCode": "OVERFIT_RISK",
                            },
                        ],
                    },
                    "graveyard": {
                        "strategies": [
                            {
                                "seedId": "GA-FIRST-GRAVEYARD",
                                "strategyId": "USDJPY_FIRST_GRAVEYARD",
                                "generation": 23,
                                "fitness": 7.0,
                                "status": "REJECTED",
                                "blockerCode": "WALK_FORWARD_UNSTABLE",
                            }
                        ],
                    },
                    "safety": {"orderSendAllowed": False, "allowedPromotionStages": ["SHADOW"]},
                }),
                encoding="utf-8",
            )

            payload = build_profit_target_tracker(runtime, target_usd=20, write=False)
            ga = payload["researchProgress"]["gaFactory"]

            self.assertEqual(ga["bestSeedId"], "GA-BEST")
            self.assertEqual(ga["bestStrategyId"], "USDJPY_BEST")
            self.assertEqual(ga["bestFitness"], -1.25)
            self.assertEqual(ga["bestGeneration"], 24.0)
            self.assertEqual(ga["bestBlockerCode"], "OVERFIT_RISK")
            self.assertEqual(ga["bestPromotionStage"], "REJECTED")
            self.assertEqual(ga["bestOverallSeedId"], "GA-FIRST-GRAVEYARD")
            self.assertEqual(ga["bestOverallFitness"], 7.0)
            self.assertEqual(ga["bestOverallGeneration"], 23.0)


if __name__ == "__main__":
    unittest.main()
