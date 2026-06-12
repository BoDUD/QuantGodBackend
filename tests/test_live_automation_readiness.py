from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from tools.live_automation_readiness.adapter_sandbox import (
    build_adapter_sandbox_review_bundle,
    read_adapter_sandbox_review_bundle,
)
from tools.live_automation_readiness.adapter_contract_validator import (
    build_adapter_contract_validator,
    read_adapter_contract_validator,
)
from tools.live_automation_readiness.execution_adapter_harness import (
    build_execution_adapter_harness,
    read_execution_adapter_harness,
)
from tools.live_automation_readiness.live_pilot_activation import (
    build_live_pilot_activation_review,
    read_live_pilot_activation_review,
)
from tools.live_automation_readiness.receipt_reconciliation import (
    build_receipt_reconciliation_review,
    read_receipt_reconciliation_review,
)
from tools.live_automation_readiness.ea_request_reader_review import (
    build_ea_request_reader_review,
    read_ea_request_reader_review,
)
from tools.live_automation_readiness.live_execution_cutover import (
    _execution_mode_blockers,
    build_live_execution_cutover_review,
    read_live_execution_cutover_review,
)
from tools.live_automation_readiness.live_execution_implementation_spec import (
    build_live_execution_implementation_spec,
    read_live_execution_implementation_spec,
)
from tools.live_automation_readiness.live_execution_adapter import (
    build_live_execution_adapter_write_review,
    read_live_execution_adapter_write_review,
)
from tools.live_automation_readiness.ea_request_consumption import (
    build_ea_request_consumption_review,
    read_ea_request_consumption_review,
)
from tools.live_automation_readiness.broker_order_send import (
    build_broker_order_send_review,
    read_broker_order_send_review,
)
from tools.live_automation_readiness.live_execution_rollback import (
    build_live_execution_rollback_review,
    read_live_execution_rollback_review,
)
from tools.live_automation_readiness.release_readiness_refresh import (
    build_release_readiness_refresh,
    read_release_readiness_refresh,
)
from tools.live_automation_readiness.release_minimal_diff_review import (
    build_release_minimal_diff_review,
    read_release_minimal_diff_review,
)
from tools.live_automation_readiness.release_token_evidence_review import (
    build_release_token_evidence_review,
    read_release_token_evidence_review,
)
from tools.live_automation_readiness.release_token_signoff_draft import (
    build_release_token_signoff_draft,
    read_release_token_signoff_draft,
)
from tools.live_automation_readiness.release_token_signoff_input_template import (
    build_release_token_signoff_input_template,
    read_release_token_signoff_input_template,
)
from tools.live_automation_readiness.release_token_signoff_input_review import (
    build_release_token_signoff_input_review,
    read_release_token_signoff_input_review,
)
from tools.live_automation_readiness.release_token_signoff_handoff import (
    build_release_token_signoff_handoff,
    read_release_token_signoff_handoff,
)
from tools.live_automation_readiness.release_token_signoff_evidence_matrix import (
    build_release_token_signoff_evidence_matrix,
    read_release_token_signoff_evidence_matrix,
)
from tools.live_automation_readiness.lane_selector import (
    build_live_execution_lane_selector,
    read_live_execution_lane_selector,
)
from tools.live_automation_readiness.forex_live12_runtime_handoff import (
    build_forex_live12_runtime_handoff,
    read_forex_live12_runtime_handoff,
)
from tools.live_automation_readiness.forex_live12_capacity_expansion_review import (
    build_forex_live12_capacity_expansion_review,
    read_forex_live12_capacity_expansion_review,
)
from tools.live_automation_readiness.forex_live12_capacity_expansion_roadmap import (
    build_forex_live12_capacity_expansion_roadmap,
    read_forex_live12_capacity_expansion_roadmap,
)
from tools.live_automation_readiness.forex_live12_micro_expansion_review import (
    build_forex_live12_micro_expansion_review,
    read_forex_live12_micro_expansion_review,
)
from tools.live_automation_readiness.forex_live12_rsi_repair_plan import (
    build_forex_live12_rsi_repair_plan,
    read_forex_live12_rsi_repair_plan,
)
from tools.live_automation_readiness.forex_live12_rsi_shadow_candidate import (
    build_forex_live12_rsi_shadow_candidate,
    read_forex_live12_rsi_shadow_candidate,
)
from tools.live_automation_readiness.forex_live12_rsi_tester_request import (
    build_forex_live12_rsi_tester_request,
    read_forex_live12_rsi_tester_request,
)
from tools.live_automation_readiness.forex_live12_rsi_tester_run_gate import (
    _account_context_status,
    build_forex_live12_rsi_tester_run_gate,
    read_forex_live12_rsi_tester_run_gate,
)
from tools.live_automation_readiness.forex_live12_rsi_candidate_promotion_gate import (
    build_forex_live12_rsi_candidate_promotion_gate,
    read_forex_live12_rsi_candidate_promotion_gate,
)
from tools.live_automation_readiness.forex_live12_rsi_tester_lock_draft import (
    build_forex_live12_rsi_tester_lock_draft,
    read_forex_live12_rsi_tester_lock_draft,
)
from tools.live_automation_readiness.sim_target_execution_review_summary import (
    _ranked_blockers,
    build_sim_target_execution_review_summary,
    read_sim_target_execution_review_summary,
)
from tools.live_automation_readiness.approval import (
    build_dry_run_live_execution_plan,
    build_live_operator_approval_evidence_review,
    build_live_operator_approval_draft,
    read_dry_run_live_execution_plan,
    read_live_operator_approval_evidence_review,
    read_live_operator_approval_draft,
)
from tools.live_automation_readiness.builder import build_live_automation_readiness, read_live_automation_readiness
from tools.live_automation_readiness.dry_run_replay import (
    build_dry_run_intent_replay,
    read_dry_run_intent_replay,
)
from tools.live_automation_readiness.execution_lane import (
    build_live_execution_lane_spec,
    read_live_execution_lane_spec,
)
from tools.live_automation_readiness.execution_adapter_review import (
    build_execution_adapter_review,
    read_execution_adapter_review,
)
from tools.live_automation_readiness.evidence_intake import (
    build_live_evidence_intake,
    read_live_evidence_intake,
)
from tools.live_automation_readiness.order_request_contract import (
    build_mt5_order_request_contract,
    read_mt5_order_request_contract,
)
from tools.live_automation_readiness.orchestrator import (
    _execution_release_readiness_packet,
    _release_gate_blockers,
    _release_gate_checklist,
    _release_gate_summary,
    _saved_or_built,
    _stage_rows,
    build_sim_to_live_orchestrator,
    read_sim_to_live_orchestrator,
)
from tools.live_automation_readiness.pipeline import (
    build_sim_to_live_automation_pipeline,
    read_sim_to_live_automation_pipeline,
)
from tools.live_automation_readiness.promotion_candidates import (
    build_live_promotion_candidates,
    read_live_promotion_candidates,
)
from tools.live_automation_readiness.promotion_controller import (
    build_live_promotion_controller,
    read_live_promotion_controller,
)
from tools.live_automation_readiness.preflight import (
    build_live_runtime_preflight_probe,
    read_live_runtime_preflight_probe,
)
from tools.live_automation_readiness.review_packet import (
    build_live_execution_review_packet,
    read_live_execution_review_packet,
)
from tools.live_automation_readiness.schema import (
    adapter_sandbox_review_path,
    adapter_contract_validator_path,
    approval_evidence_review_path,
    broker_order_send_review_path,
    ea_request_consumption_review_path,
    ea_request_reader_review_path,
    execution_adapter_harness_path,
    live_execution_adapter_write_review_path,
    live_execution_implementation_spec_path,
    live_execution_cutover_review_path,
    live_execution_rollback_review_path,
    live_pilot_activation_review_path,
    order_request_contract_path,
    receipt_reconciliation_review_path,
    release_minimal_diff_review_path,
    release_token_evidence_review_path,
    release_token_signoff_draft_path,
    release_token_signoff_input_template_path,
    release_token_signoff_input_review_path,
    release_token_signoff_handoff_path,
    release_token_signoff_evidence_matrix_path,
    release_readiness_refresh_path,
    live_execution_lane_selector_path,
    forex_live12_runtime_handoff_path,
    forex_live12_capacity_expansion_review_path,
    forex_live12_capacity_expansion_roadmap_path,
    forex_live12_micro_expansion_review_path,
    forex_live12_rsi_repair_plan_path,
    forex_live12_rsi_shadow_candidate_path,
    forex_live12_rsi_tester_request_path,
    forex_live12_rsi_tester_run_gate_path,
    forex_live12_rsi_candidate_promotion_gate_path,
    forex_live12_rsi_tester_lock_draft_path,
    sim_target_execution_review_summary_path,
    runtime_preflight_path,
    sim_to_live_orchestrator_path,
    sim_to_live_pipeline_path,
)
from tools.hfm_crypto_cfd.schema import (
    contract_spec_export_path,
    ea_symbol_specs_path,
    filled_contract_spec_path,
    filled_simulation_profile_path,
)
from tools.usdjpy_walk_forward.selector import sample_walk_forward_runtime


class LiveAutomationReadinessTests(unittest.TestCase):
    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _ea_request_reader_runtime_status() -> dict:
        return {
            "schema": "quantgod.mql5.ea_request_reader_review_status.v1",
            "status": "DISABLED_BY_DEFAULT",
            "operatorRequested": False,
            "effectiveEnabled": False,
            "configuredMode": "DISABLED_REVIEW_ONLY",
            "requestDirectory": "runtime\\agent\\mt5_order_requests",
            "receiptDirectory": "runtime\\agent\\mt5_order_receipts",
            "markerChecks": {
                "disabledByDefault": True,
                "schemaValidationRequired": True,
                "idempotencyRequestIdRequired": True,
                "killSwitchRequired": True,
                "receiptWriterRequired": True,
                "orderSendRequiresSeparateReview": True,
            },
            "safety": {
                "reviewOnly": True,
                "requestFilesRead": False,
                "requestFilesConsumed": False,
                "receiptFilesWritten": False,
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "livePresetMutationAllowed": False,
                "credentialStorageAllowed": False,
            },
        }

    def test_live_execution_implementation_spec_reports_profit_reached_execution_gate_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(live_execution_cutover_review_path(runtime), {
                "schema": "quantgod.live_execution_cutover_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForSeparateLiveExecutionCutoverImplementationReview": False,
                "dataPlaneCutoverReady": True,
                "executionModeOnlyBlocked": True,
                "implementationHandoff": {},
                "executionModeFileEvidence": {
                    "startupConfig": {
                        "path": "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
                        "exists": True,
                        "values": {
                            "AllowLiveTrading": "0",
                            "ExpertParameters": "QuantGod_MT5_HFM_LiveSecondary.set",
                        },
                    },
                    "deployedPreset": {
                        "path": "/tmp/MetaTrader 5/MQL5/Presets/QuantGod_MT5_HFM_LiveSecondary.set",
                        "exists": True,
                        "values": {
                            "ReadOnlyMode": "true",
                            "EnablePilotAutoTrading": "false",
                            "PilotStartupEntryGuardMode": "H1_STRICT",
                        },
                    },
                    "restartWouldKeepExecutionDisabled": True,
                    "blockingEvidence": [
                        {"code": "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF", "reasonZh": "ini off", "value": "0"},
                        {"code": "DEPLOYED_PRESET_READ_ONLY_TRUE", "reasonZh": "preset read-only", "value": "true"},
                    ],
                    "writesMt5Preset": False,
                    "writesStartupConfig": False,
                },
                "blockers": [
                    {"code": "MT5_READ_ONLY_MODE_STILL_ACTIVE", "reasonZh": "read-only", "value": True},
                    {"code": "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED", "reasonZh": "pilot off", "value": False},
                    {"code": "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT", "reasonZh": "execution off", "value": False},
                    {"code": "MT5_TRADE_ALLOWED_NOT_CONFIRMED", "reasonZh": "trade off", "value": False},
                    {"code": "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF", "reasonZh": "ini off", "value": "0"},
                    {"code": "DEPLOYED_PRESET_READ_ONLY_TRUE", "reasonZh": "preset read-only", "value": "true"},
                ],
            })
            self._write_json(live_pilot_activation_review_path(runtime), {
                "schema": "quantgod.live_pilot_activation_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "presetActivationPackage": {
                    "reviewOnlyPresetDiffPackage": {
                        "mode": "REVIEW_ONLY_PRESET_DIFF_PACKAGE_NO_FILE_WRITE",
                        "candidateFileWritten": False,
                        "writesMt5Preset": False,
                        "orderSendAllowed": False,
                        "laneDiffs": [
                            {
                                "lane": "btcCryptoCfd",
                                "canAttachNow": False,
                                "implementationPrerequisites": ["broker_order_send_path"],
                            }
                        ],
                    }
                },
            })

            spec = build_live_execution_implementation_spec(runtime, write=False)

            self.assertEqual(spec["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(spec["dataPlaneImplementationSpecReady"])
            self.assertTrue(spec["executionModeOnlyBlocked"])
            self.assertFalse(spec["implementationCanStart"])
            self.assertTrue(spec["disabledFirstImplementationWorkReady"])
            self.assertTrue(spec["nextCodeWorkAllowedInReviewOnly"])
            self.assertTrue(spec["liveExecutionStillForbidden"])
            readiness = spec["implementationReadinessSummary"]
            self.assertEqual(readiness["status"], "READY_TO_IMPLEMENT_DISABLED_FIRST")
            self.assertEqual(readiness["allowedWorkType"], "CODE_AND_REVIEW_ARTIFACTS_ONLY")
            self.assertEqual(readiness["forbiddenWorkType"], "LIVE_ORDER_EXECUTION")
            self.assertFalse(readiness["orderSendAllowed"])
            self.assertFalse(readiness["mt5OrderSendAllowed"])
            self.assertFalse(readiness["writesMt5OrderRequest"])
            gap_audit = spec["executionActivationGapAudit"]
            self.assertEqual(gap_audit["status"], "PROFIT_TARGET_REACHED_EXECUTION_GATES_OFF")
            self.assertFalse(gap_audit["goLiveAllowedNow"])
            self.assertEqual(
                gap_audit["profitGateConclusionZh"],
                "不再要求每条 lane 都达到 50 USD；当前只要求必需 lane 为正收益且合计达到 50 USD。",
            )
            self.assertEqual(
                {row["field"] for row in gap_audit["gates"]},
                {"readOnlyMode", "livePilotMode", "executionEnabled", "tradeAllowed"},
            )
            live_pilot_gate = next(row for row in gap_audit["gates"] if row["field"] == "livePilotMode")
            self.assertEqual(live_pilot_gate["currentPresetSetting"], "EnablePilotAutoTrading=false, ReadOnlyMode=true")
            self.assertEqual(gap_audit["sourceOfTruth"]["presetFile"], "MQL5/Presets/QuantGod_MT5_HFM_LiveSecondary.set")
            self.assertEqual(
                gap_audit["sourceOfTruth"]["actualStartupConfigPath"],
                "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
            )
            self.assertTrue(gap_audit["actualRuntimeFileEvidence"]["restartWouldKeepExecutionDisabled"])
            self.assertIn(
                "DEPLOYED_PRESET_READ_ONLY_TRUE",
                {row["code"] for row in gap_audit["fileEvidenceBlockers"]},
            )
            transition_plan = gap_audit["livePilotGateTransitionPlan"]
            self.assertEqual(transition_plan["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertFalse(transition_plan["canBeAppliedByThisArtifact"])
            self.assertFalse(transition_plan["writesMt5Preset"])
            self.assertFalse(transition_plan["writesMt5OrderRequest"])
            self.assertFalse(transition_plan["brokerCallsMade"])
            self.assertFalse(transition_plan["orderSendAllowed"])
            self.assertTrue(transition_plan["actualRuntimeFileEvidence"]["restartWouldKeepExecutionDisabled"])
            self.assertEqual(
                transition_plan["reviewedPresetDiffPreview"]["changes"][0]["key"],
                "ReadOnlyMode",
            )
            self.assertFalse(transition_plan["reviewedPresetDiffPreview"]["writesMt5Preset"])
            self.assertEqual(
                transition_plan["reviewOnlyPresetDiffPackage"]["mode"],
                "REVIEW_ONLY_PRESET_DIFF_PACKAGE_NO_FILE_WRITE",
            )
            self.assertFalse(transition_plan["reviewOnlyPresetDiffPackage"]["candidateFileWritten"])
            self.assertFalse(spec["cutoverReview"]["reviewOnlyPresetDiffPackage"]["orderSendAllowed"])
            self.assertEqual(
                set(transition_plan["gateFields"]),
                {"readOnlyMode", "livePilotMode", "executionEnabled", "tradeAllowed"},
            )
            self.assertEqual(
                [row["stepId"] for row in transition_plan["transitionSteps"]],
                [
                    "operator_approval_bound",
                    "reviewed_preset_diff",
                    "manual_mt5_attach_and_runtime_proof",
                    "request_reader_and_broker_send_reviews",
                    "post_attach_preflight_rerun",
                ],
            )
            self.assertTrue(all(row["canBeAppliedByThisArtifact"] is False for row in transition_plan["transitionSteps"]))
            self.assertIn(
                "refresh_runtime_preflight",
                {row["id"] for row in transition_plan["validationCommands"]},
            )
            traceability = spec["executionSafetyTraceabilityMatrix"]
            self.assertEqual(
                {row["stepId"] for row in traceability},
                {
                    "broker_order_send_path",
                    "receipt_writer_and_reconciliation_path",
                    "rollback_and_auto_disable_path",
                },
            )
            self.assertTrue(all(row["requiredBeforeLive"] for row in traceability))
            self.assertTrue(all(row["currentArtifactAllowedToApply"] is False for row in traceability))
            self.assertTrue(all(row["orderSendAllowed"] is False for row in traceability))
            self.assertTrue(all(row["mt5OrderSendAllowed"] is False for row in traceability))
            self.assertTrue(all(row["writesMt5OrderRequest"] is False for row in traceability))
            self.assertTrue(all(row["requestFilesWritten"] is False for row in traceability))
            self.assertTrue(all(row["receiptFilesWritten"] is False for row in traceability))
            self.assertTrue(all(row["brokerCallsMade"] is False for row in traceability))
            broker_trace = next(row for row in traceability if row["stepId"] == "broker_order_send_path")
            self.assertTrue(broker_trace["declaredInImplementationSteps"])
            self.assertIn("account/server/symbol bound", broker_trace["mustProve"])
            rollback_trace = next(row for row in traceability if row["stepId"] == "rollback_and_auto_disable_path")
            self.assertEqual(rollback_trace["blockingIfMissing"], "ROLLBACK_AUTO_DISABLE_PATH_NOT_REVIEWED")
            self.assertTrue(all(row["disabledFirstImplementationWorkReady"] for row in spec["acceptanceMatrix"]))
            self.assertTrue(all(row["nextCodeWorkAllowedInReviewOnly"] for row in spec["acceptanceMatrix"]))
            self.assertFalse(spec["orderSendAllowed"])
            self.assertFalse(spec["writesMt5OrderRequest"])

    def test_adapter_write_review_blocks_stale_validator_payload_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request = {
                "requestId": "sandbox-review-stale-validator",
                "schema": "quantgod.mt5_reviewed_order_request.v1",
                "createdAtIso": "1970-01-01T00:00:00Z",
                "reviewPacketHash": "review-current",
                "runtimePreflightHash": "preflight-current",
                "operatorApprovalId": "review-only-operator-approval",
                "lane": "HFM_CRYPTO_CFD",
                "brokerSymbol": "#BTCUSD",
                "canonicalSymbol": "BTCUSD",
                "side": "BUY",
                "orderType": "MARKET",
                "volumeLots": 0.0,
                "slPrice": None,
                "tpPrice": None,
                "maxSlippagePoints": 0.0,
                "maxSpreadPoints": 0.0,
                "maxDailyLossPct": 0.0,
                "maxDailyLossR": 0.0,
                "maxConsecutiveLosses": 0,
                "killSwitchOk": True,
                "runtimeFresh": True,
                "spreadProbeOk": True,
                "symbolMappingOk": True,
                "dryRunReplayPassed": True,
            }
            self._write_json(adapter_sandbox_review_path(runtime), {
                "schema": "quantgod.adapter_sandbox_review_bundle.v1",
                "status": "READY_FOR_ADAPTER_SANDBOX_REVIEW",
                "sampleRequests": [request],
            })
            self._write_json(live_execution_implementation_spec_path(runtime), {
                "schema": "quantgod.live_execution_implementation_spec.v1",
                "status": "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW",
                "readyForLiveExecutionImplementationSpecReview": True,
                "dataPlaneImplementationSpecReady": True,
                "implementationSteps": [{"stepId": "live_execution_adapter_write_path"}],
                "cutoverReview": {
                    "implementationHandoff": {
                        "reviewPacketHash": "review-current",
                        "runtimePreflightHash": "preflight-current",
                    }
                },
            })
            self._write_json(adapter_contract_validator_path(runtime), {
                "schema": "quantgod.adapter_contract_validator.v1",
                "status": "READY_FOR_ADAPTER_CONTRACT_VALIDATION_REVIEW",
                "validationPassed": True,
                "dataPlaneValidationReady": True,
                "validationResults": [{
                    "requestId": request["requestId"],
                    "passed": True,
                    "payloadHash": "stale-payload-hash",
                }],
            })
            self._write_json(execution_adapter_harness_path(runtime), {
                "schema": "quantgod.execution_adapter_harness.v1",
                "status": "READY_FOR_DISABLED_ADAPTER_IMPLEMENTATION_HARNESS_REVIEW",
                "readyForDisabledAdapterImplementationReview": True,
                "dataPlaneHarnessReady": True,
                "plannedWrites": [{
                    "requestId": request["requestId"],
                    "targetRequestDir": "runtime/agent/mt5_order_requests",
                    "targetReceiptDir": "runtime/agent/mt5_order_receipts",
                    "plannedRequestPath": f"runtime/agent/mt5_order_requests/{request['requestId']}.json",
                    "plannedReceiptPath": f"runtime/agent/mt5_order_receipts/{request['requestId']}.receipt.json",
                    "atomicWriteRequired": True,
                    "idempotencyKey": request["requestId"],
                }],
            })

            review = build_live_execution_adapter_write_review(runtime, write=True)

            self.assertEqual(review["schema"], "quantgod.live_execution_adapter_write_review.v1")
            self.assertEqual(review["status"], "WAITING_LIVE_EXECUTION_ADAPTER_WRITE_INPUTS")
            self.assertFalse(review["readyForLiveExecutionAdapterWriteReview"])
            self.assertFalse(review["dataPlaneAdapterWriteReady"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["requestFilesWritten"])
            self.assertFalse(review["brokerCallsMade"])
            self.assertFalse(review["writePlans"][0]["validatorHashMatches"])
            checklist_by_id = {row["id"]: row for row in review["adapterWriteChecklist"]}
            self.assertFalse(checklist_by_id["validator_payload_hashes_current"]["passed"])
            self.assertIn("LIVE_ADAPTER_WRITE_PLAN_INVALID", {row["code"] for row in review["blockers"]})
            saved = read_live_execution_adapter_write_review(runtime)
            self.assertEqual(saved["schema"], review["schema"])

    def test_ea_consumption_blocks_stale_adapter_writer_validator_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(live_execution_implementation_spec_path(runtime), {
                "schema": "quantgod.live_execution_implementation_spec.v1",
                "status": "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW",
                "readyForLiveExecutionImplementationSpecReview": True,
                "dataPlaneImplementationSpecReady": True,
                "implementationSteps": [{"stepId": "ea_request_reader_consumption_path"}],
            })
            self._write_json(ea_request_reader_review_path(runtime), {
                "schema": "quantgod.ea_request_reader_review.v1",
                "status": "READY_FOR_EA_REQUEST_READER_IMPLEMENTATION_REVIEW",
                "readyForEaRequestReaderImplementationReview": True,
                "dataPlaneEaRequestReaderReady": True,
                "runtimeStatusFound": True,
                "runtimeStatusSchemaOk": True,
                "runtimeStatusDisabled": True,
                "runtimeStatusSafetyPassed": True,
                "readerImplementationContract": {
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                },
                "runtimeStatusReview": {
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                    "effectiveEnabled": False,
                },
            })
            self._write_json(live_execution_adapter_write_review_path(runtime), {
                "schema": "quantgod.live_execution_adapter_write_review.v1",
                "status": "READY_FOR_LIVE_EXECUTION_ADAPTER_WRITE_REVIEW",
                "readyForLiveExecutionAdapterWriteReview": True,
                "dataPlaneAdapterWriteReady": True,
                "writePlans": [{
                    "requestId": "sandbox-review-stale-consumption",
                    "finalRequestPath": "runtime/agent/mt5_order_requests/sandbox-review-stale-consumption.json",
                    "plannedReceiptPath": "runtime/agent/mt5_order_receipts/sandbox-review-stale-consumption.receipt.json",
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                    "idempotencyKey": "sandbox-review-stale-consumption",
                    "contractValidationPassed": True,
                    "validatorHashMatches": False,
                    "atomicWriteRequired": True,
                    "serializedPayloadHash": "serialized",
                    "allowedToWriteLiveRequest": False,
                    "requestFilesWritten": False,
                    "brokerCallsMade": False,
                    "adapterExecutionAllowed": False,
                }],
            })

            review = build_ea_request_consumption_review(runtime, write=True)

            self.assertEqual(review["schema"], "quantgod.ea_request_consumption_review.v1")
            self.assertEqual(review["status"], "WAITING_EA_REQUEST_CONSUMPTION_INPUTS")
            self.assertFalse(review["readyForEaRequestConsumptionReview"])
            self.assertFalse(review["dataPlaneEaRequestConsumptionReady"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["eaRequestFilesRead"])
            self.assertFalse(review["consumptionPlans"][0]["adapterWriterValidatorHashMatches"])
            self.assertEqual(review["rejectionReceiptPlanMode"], "REJECTION_RECEIPT_PLAN_REVIEW_ONLY_NO_FILE_WRITES")
            self.assertTrue(review["consumptionPlans"][0]["rejectionReceiptPlan"]["complete"])
            self.assertFalse(review["consumptionPlans"][0]["rejectionReceiptPlan"]["receiptFilesWritten"])
            checklist_by_id = {row["id"]: row for row in review["eaRequestConsumptionChecklist"]}
            self.assertFalse(checklist_by_id["adapter_writer_validator_hashes_current"]["passed"])
            self.assertIn("EA_REQUEST_CONSUMPTION_CHECK_NOT_PASSED", {row["code"] for row in review["blockers"]})
            saved = read_ea_request_consumption_review(runtime)
            self.assertEqual(saved["schema"], review["schema"])

    def test_ea_consumption_blocks_duplicate_request_ids_with_rejection_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request_id = "sandbox-review-duplicate-consumption"
            self._write_json(live_execution_implementation_spec_path(runtime), {
                "schema": "quantgod.live_execution_implementation_spec.v1",
                "status": "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW",
                "readyForLiveExecutionImplementationSpecReview": True,
                "dataPlaneImplementationSpecReady": True,
                "implementationSteps": [{"stepId": "ea_request_reader_consumption_path"}],
            })
            self._write_json(ea_request_reader_review_path(runtime), {
                "schema": "quantgod.ea_request_reader_review.v1",
                "status": "READY_FOR_EA_REQUEST_READER_IMPLEMENTATION_REVIEW",
                "readyForEaRequestReaderImplementationReview": True,
                "dataPlaneEaRequestReaderReady": True,
                "runtimeStatusFound": True,
                "runtimeStatusSchemaOk": True,
                "runtimeStatusDisabled": True,
                "runtimeStatusSafetyPassed": True,
                "readerImplementationContract": {
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                },
                "runtimeStatusReview": {
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                    "effectiveEnabled": False,
                },
            })
            write_plan = {
                "requestId": request_id,
                "finalRequestPath": f"runtime/agent/mt5_order_requests/{request_id}.json",
                "plannedReceiptPath": f"runtime/agent/mt5_order_receipts/{request_id}.receipt.json",
                "requestDirectory": "runtime/agent/mt5_order_requests",
                "receiptDirectory": "runtime/agent/mt5_order_receipts",
                "idempotencyKey": request_id,
                "contractValidationPassed": True,
                "validatorHashMatches": True,
                "atomicWriteRequired": True,
                "serializedPayloadHash": "serialized",
                "allowedToWriteLiveRequest": False,
                "requestFilesWritten": False,
                "brokerCallsMade": False,
                "adapterExecutionAllowed": False,
            }
            self._write_json(live_execution_adapter_write_review_path(runtime), {
                "schema": "quantgod.live_execution_adapter_write_review.v1",
                "status": "READY_FOR_LIVE_EXECUTION_ADAPTER_WRITE_REVIEW",
                "readyForLiveExecutionAdapterWriteReview": True,
                "dataPlaneAdapterWriteReady": True,
                "writePlans": [dict(write_plan), dict(write_plan)],
            })

            review = build_ea_request_consumption_review(runtime, write=True)

            self.assertEqual(review["status"], "WAITING_EA_REQUEST_CONSUMPTION_INPUTS")
            self.assertFalse(review["readyForEaRequestConsumptionReview"])
            self.assertFalse(review["dataPlaneEaRequestConsumptionReady"])
            self.assertEqual(review["duplicateRequestIds"], [request_id])
            self.assertTrue(all(row["rejectionReceiptPlan"]["complete"] for row in review["consumptionPlans"]))
            self.assertTrue(all(row["rejectionReceiptPlan"]["duplicateRequestIdObserved"] for row in review["consumptionPlans"]))
            duplicate_rules = [
                rule
                for rule in review["consumptionPlans"][0]["rejectionReceiptPlan"]["rules"]
                if rule["rejectedReasonCode"] == "DUPLICATE_REQUEST_ID"
            ]
            self.assertEqual(len(duplicate_rules), 1)
            self.assertTrue(duplicate_rules[0]["observedInCurrentPlan"])
            checklist_by_id = {row["id"]: row for row in review["eaRequestConsumptionChecklist"]}
            self.assertFalse(checklist_by_id["duplicate_request_ids_absent"]["passed"])
            self.assertFalse(review["receiptFilesWritten"])
            self.assertFalse(review["eaRequestFilesRead"])
            self.assertIn("EA_REQUEST_CONSUMPTION_CHECK_NOT_PASSED", {row["code"] for row in review["blockers"]})

    def test_broker_send_blocks_stale_ea_consumption_adapter_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request_id = "sandbox-review-stale-broker"
            self._write_json(live_execution_implementation_spec_path(runtime), {
                "schema": "quantgod.live_execution_implementation_spec.v1",
                "status": "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW",
                "readyForLiveExecutionImplementationSpecReview": True,
                "dataPlaneImplementationSpecReady": True,
                "implementationSteps": [{"stepId": "broker_order_send_path"}],
            })
            self._write_json(ea_request_consumption_review_path(runtime), {
                "schema": "quantgod.ea_request_consumption_review.v1",
                "status": "READY_FOR_EA_REQUEST_CONSUMPTION_REVIEW",
                "readyForEaRequestConsumptionReview": True,
                "dataPlaneEaRequestConsumptionReady": True,
                "consumptionPlans": [{
                    "requestId": request_id,
                    "requestPath": f"runtime/agent/mt5_order_requests/{request_id}.json",
                    "receiptPath": f"runtime/agent/mt5_order_receipts/{request_id}.receipt.json",
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                    "idempotencyKey": request_id,
                    "defaultAction": "REJECT_REVIEW_ONLY",
                    "adapterWriterValidatorHashMatches": False,
                }],
            })
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                "runtimeProbePassed": True,
                "dashboardSnapshot": {
                    "fresh": True,
                    "account": {"number": 186054398, "server": "HFMarketsGlobal-Live12", "currency": "USC"},
                },
                "laneRuntimeChecks": [{
                    "lane": "HFM_CRYPTO_CFD",
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "passed": True,
                }],
            })
            self._write_json(order_request_contract_path(runtime), {
                "schema": "quantgod.mt5_order_request_contract.v1",
                "status": "READY_FOR_ORDER_REQUEST_CONTRACT_REVIEW",
                "readyForAdapterCodeReview": True,
                "laneContracts": [{
                    "lane": "HFM_CRYPTO_CFD",
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                }],
            })
            canonical_preview = json.dumps({
                "requestId": request_id,
                "lane": "HFM_CRYPTO_CFD",
                "brokerSymbol": "#BTCUSD",
                "canonicalSymbol": "BTCUSD",
                "side": "BUY",
                "orderType": "MARKET",
                "volumeLots": 0.0,
                "maxSlippagePoints": 0.0,
                "maxSpreadPoints": 0.0,
                "maxDailyLossPct": 0.0,
                "maxDailyLossR": 0.0,
                "maxConsecutiveLosses": 0,
                "reviewPacketHash": "review-current",
                "runtimePreflightHash": "preflight-current",
                "operatorApprovalId": "review-only-operator-approval",
                "killSwitchOk": True,
                "runtimeFresh": True,
                "spreadProbeOk": True,
                "symbolMappingOk": True,
                "dryRunReplayPassed": True,
            })
            self._write_json(live_execution_adapter_write_review_path(runtime), {
                "schema": "quantgod.live_execution_adapter_write_review.v1",
                "status": "READY_FOR_LIVE_EXECUTION_ADAPTER_WRITE_REVIEW",
                "readyForLiveExecutionAdapterWriteReview": True,
                "dataPlaneAdapterWriteReady": True,
                "writePlans": [{
                    "requestId": request_id,
                    "lane": "HFM_CRYPTO_CFD",
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "validatorHashMatches": True,
                    "canonicalJsonPreview": canonical_preview,
                }],
            })

            review = build_broker_order_send_review(runtime, write=True)

            self.assertEqual(review["schema"], "quantgod.broker_order_send_review.v1")
            self.assertEqual(review["status"], "WAITING_BROKER_ORDER_SEND_INPUTS")
            self.assertFalse(review["readyForBrokerOrderSendReview"])
            self.assertFalse(review["dataPlaneBrokerOrderSendReady"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["brokerCallsMade"])
            self.assertFalse(review["brokerSendPlans"][0]["adapterWriterValidatorHashMatches"])
            checklist_by_id = {row["id"]: row for row in review["brokerOrderSendChecklist"]}
            self.assertFalse(checklist_by_id["ea_consumption_adapter_hashes_current"]["passed"])
            self.assertIn("BROKER_ORDER_SEND_CHECK_NOT_PASSED", {row["code"] for row in review["blockers"]})
            saved = read_broker_order_send_review(runtime)
            self.assertEqual(saved["schema"], review["schema"])

    def test_broker_send_cutover_internal_mode_uses_non_recursive_spec_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request_id = "sandbox-review-cutover-proxy"
            canonical_preview = json.dumps({
                "requestId": request_id,
                "lane": "HFM_CRYPTO_CFD",
                "brokerSymbol": "#BTCUSD",
                "canonicalSymbol": "BTCUSD",
                "side": "BUY",
                "orderType": "MARKET",
                "volumeLots": 0.01,
                "reviewPacketHash": "review-hash",
                "runtimePreflightHash": "preflight-hash",
                "killSwitchOk": True,
                "runtimeFresh": True,
                "spreadProbeOk": True,
                "symbolMappingOk": True,
                "dryRunReplayPassed": True,
            })
            self._write_json(ea_request_consumption_review_path(runtime), {
                "schema": "quantgod.ea_request_consumption_review.v1",
                "status": "READY_FOR_EA_REQUEST_CONSUMPTION_REVIEW",
                "readyForEaRequestConsumptionReview": True,
                "dataPlaneEaRequestConsumptionReady": True,
                "runtimeStatusReview": {
                    "brokerOrderSendWrapper": {
                        "releaseGate": {
                            "tokenRequired": True,
                            "tokenProvided": False,
                        }
                    }
                },
                "consumptionPlans": [{
                    "requestId": request_id,
                    "requestPath": f"runtime/agent/mt5_order_requests/{request_id}.json",
                    "receiptPath": f"runtime/agent/mt5_order_receipts/{request_id}.receipt.json",
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                    "idempotencyKey": request_id,
                    "defaultAction": "REJECT_REVIEW_ONLY",
                    "adapterWriterValidatorHashMatches": True,
                }],
            })
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                "runtimeProbePassed": True,
                "dataPlaneReadyForLivePilotReview": True,
                "dashboardSnapshot": {
                    "fresh": True,
                    "account": {"number": 186054398, "server": "HFMarketsGlobal-Live16", "currency": "USD"},
                },
                "laneRuntimeChecks": [{
                    "lane": "HFM_CRYPTO_CFD",
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "passed": True,
                }],
            })
            self._write_json(order_request_contract_path(runtime), {
                "schema": "quantgod.mt5_order_request_contract.v1",
                "status": "READY_FOR_ORDER_REQUEST_CONTRACT_REVIEW",
                "readyForAdapterCodeReview": True,
                "runtimePreflightDataPlaneReadyForReview": True,
                "laneContracts": [{
                    "lane": "HFM_CRYPTO_CFD",
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                }],
            })
            self._write_json(live_execution_adapter_write_review_path(runtime), {
                "schema": "quantgod.live_execution_adapter_write_review.v1",
                "status": "READY_FOR_LIVE_EXECUTION_ADAPTER_WRITE_REVIEW",
                "readyForLiveExecutionAdapterWriteReview": True,
                "dataPlaneAdapterWriteReady": True,
                "writePlans": [{
                    "requestId": request_id,
                    "lane": "HFM_CRYPTO_CFD",
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "validatorHashMatches": True,
                    "canonicalJsonPreview": canonical_preview,
                }],
            })

            review = build_broker_order_send_review(
                runtime,
                request_json="trigger-rebuild-without-spec.json",
                write=True,
                _allow_implementation_spec_rebuild=False,
            )

            self.assertEqual(review["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(review["dataPlaneBrokerOrderSendReady"])
            self.assertTrue(review["executionModeOnlyBlocked"])
            self.assertEqual(review["implementationSpecStatus"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", {row["code"] for row in review["blockers"]})
            self.assertFalse(live_execution_implementation_spec_path(runtime).exists())
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["brokerCallsMade"])
            self.assertFalse(review["writesMt5OrderRequest"])

    def test_receipt_reconciliation_requires_ready_broker_send_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request_id = "sandbox-review-receipt-broker"
            self._write_json(live_pilot_activation_review_path(runtime), {
                "schema": "quantgod.live_pilot_activation_review.v1",
                "status": "READY_FOR_LIVE_PILOT_ACTIVATION_REVIEW",
                "readyForLivePilotActivationReview": True,
                "dataPlaneActivationReady": True,
            })
            self._write_json(execution_adapter_harness_path(runtime), {
                "schema": "quantgod.execution_adapter_harness.v1",
                "status": "READY_FOR_DISABLED_ADAPTER_IMPLEMENTATION_HARNESS_REVIEW",
                "readyForDisabledAdapterImplementationReview": True,
                "dataPlaneHarnessReady": True,
                "plannedWrites": [{
                    "requestId": request_id,
                    "brokerSymbol": "#BTCUSD",
                    "side": "BUY",
                    "plannedReceiptPath": f"runtime/agent/mt5_order_receipts/{request_id}.receipt.json",
                    "wouldWriteRequestFile": False,
                    "wouldWriteReceiptFile": False,
                    "brokerCallsMade": False,
                    "adapterExecutionAllowed": False,
                    "receipt": {
                        "requestId": request_id,
                        "schema": "quantgod.mt5_execution_receipt.v1",
                        "adapterMode": "REVIEW_ONLY",
                        "acceptedByAdapter": False,
                        "rejectedReasonCode": "DISABLED_ADAPTER_HARNESS_NO_SIDE_EFFECTS",
                        "brokerSymbol": "#BTCUSD",
                        "side": "BUY",
                        "volumeLots": 0.0,
                        "safetySnapshotHash": "safety",
                        "ticket": None,
                    },
                }],
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_BROKER_ORDER_SEND_INPUTS",
                "readyForBrokerOrderSendReview": False,
                "dataPlaneBrokerOrderSendReady": False,
                "brokerSendPlanCount": 1,
                "brokerSendPlans": [{
                    "requestId": request_id,
                    "adapterWriterValidatorHashMatches": False,
                    "writePlanValidatorHashMatches": False,
                    "sourcePathLockedToEaConsumption": True,
                    "wouldCallBroker": False,
                    "brokerCallsMade": False,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "requestFilesWritten": False,
                    "receiptFilesWritten": False,
                }],
            })

            review = build_receipt_reconciliation_review(runtime, write=True)

            self.assertEqual(review["schema"], "quantgod.receipt_reconciliation_review.v1")
            self.assertEqual(review["status"], "WAITING_RECEIPT_RECONCILIATION_INPUTS")
            self.assertFalse(review["readyForReceiptReconciliationReview"])
            self.assertFalse(review["dataPlaneReconciliationReady"])
            self.assertFalse(review["reviewOnlyReceiptsReconciled"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["receiptFilesWritten"])
            self.assertFalse(review["reconciliationResults"][0]["brokerSendPlanHashCurrent"])
            self.assertIn("BROKER_ORDER_SEND_REVIEW_NOT_READY", {row["code"] for row in review["blockers"]})
            self.assertIn("RECONCILIATION_RECEIPT_VALIDATION_FAILED", {row["code"] for row in review["blockers"]})
            saved = read_receipt_reconciliation_review(runtime)
            self.assertEqual(saved["schema"], review["schema"])

    def test_live_pilot_activation_review_includes_review_only_preset_activation_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(sim_to_live_orchestrator_path(runtime), {
                "schema": "quantgod.sim_to_live_orchestrator.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForExecutionAdapterImplementationReview": False,
            })
            self._write_json(sim_to_live_pipeline_path(runtime), {
                "schema": "quantgod.sim_to_live_automation_pipeline.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForSeparateExecutionAdapterReview": False,
            })
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneReadyForLivePilotReview": True,
                "executionModeOnlyBlocked": True,
                "runtimeProbePassed": False,
                "executionModeBlockers": [
                    {"code": "MT5_READ_ONLY_MODE_STILL_ACTIVE", "reasonZh": "read-only", "value": True},
                ],
                "dashboardSnapshot": {
                    "readOnlyMode": True,
                    "livePilotMode": False,
                    "executionEnabled": False,
                    "tradeAllowed": False,
                    "tradeStatus": "SHADOW",
                    "permissionLayers": {"tradePermissionBlocker": "READ_ONLY_MODE"},
                    "account": {"number": 198135388, "server": "HFMarketsGlobal-Live16", "currency": "USD"},
                },
            })
            self._write_json(approval_evidence_review_path(runtime), {
                "schema": "quantgod.live_operator_approval_evidence_review.v1",
                "status": "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED",
                "operatorApprovalProvided": True,
                "approvedLanes": ["hfmCryptoCfd"],
            })
            self._write_json(adapter_contract_validator_path(runtime), {
                "schema": "quantgod.adapter_contract_validator.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneValidationReady": True,
                "contractExecutionModeOnlyBlocked": True,
                "sampleValidationPassed": True,
                "requestCount": 1,
            })
            self._write_json(execution_adapter_harness_path(runtime), {
                "schema": "quantgod.execution_adapter_harness.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneHarnessReady": True,
                "executionModeOnlyBlocked": True,
                "readyForDisabledAdapterImplementationReview": False,
                "requestWritesAllowed": False,
                "requestFilesWritten": False,
                "brokerCallsMade": False,
                "adapterExecutionAllowed": False,
                "plannedWriteCount": 1,
                "reviewOnlyReceiptCount": 1,
                "requestDirectoryTarget": "runtime/agent/mt5_order_requests",
                "receiptDirectoryTarget": "runtime/agent/mt5_order_receipts",
            })
            qg_dir = runtime / "drive_c" / "qg"
            qg_dir.mkdir(parents=True)
            (qg_dir / "QuantGod_MT5_HFM_LiveSecondary_mac.ini").write_text(
                "\n".join([
                    "[Common]",
                    "Login=198135388",
                    "Server=HFMarketsGlobal-Live16",
                    "",
                    "[Experts]",
                    "AllowLiveTrading=0",
                    "Enabled=1",
                    "",
                    "[StartUp]",
                    "Expert=QuantGod_MultiStrategy",
                    "ExpertParameters=QuantGod_MT5_HFM_LiveSecondary.set",
                    "Symbol=USDJPY",
                    "Period=M1",
                ]),
                encoding="utf-8",
            )
            presets_dir = runtime / "MQL5" / "Presets"
            presets_dir.mkdir(parents=True)
            (presets_dir / "QuantGod_MT5_HFM_LiveSecondary.set").write_text(
                "\n".join([
                    "Watchlist=USDJPY",
                    "ReadOnlyMode=true",
                    "EnablePilotAutoTrading=false",
                    "EnablePilotRsiH1Live=false",
                    "EnableEARequestReaderReviewHarness=false",
                    "PilotStartupEntryGuardMode=H1_STRICT",
                    "PilotStartupEntryWaitNextH1Bar=true",
                    "PilotLotSize=0.01",
                ]),
                encoding="utf-8",
            )

            activation = build_live_pilot_activation_review(runtime, write=False)

            package = activation["presetActivationPackage"]
            self.assertEqual(package["packageMode"], "REVIEW_ONLY_PRESET_ACTIVATION_PACKAGE_NO_MUTATION")
            self.assertEqual(package["status"], "PROFIT_TARGET_REACHED_PRESET_GATES_OFF")
            self.assertFalse(package["writesMt5Preset"])
            self.assertFalse(package["writesMt5OrderRequest"])
            self.assertFalse(package["orderSendAllowed"])
            self.assertEqual(package["currentRuntimeGateState"]["tradePermissionBlocker"], "READ_ONLY_MODE")
            current_evidence = package["currentPresetEvidence"]
            self.assertTrue(current_evidence["actualStartupConfig"]["exists"])
            self.assertTrue(current_evidence["actualDeployedPreset"]["exists"])
            self.assertEqual(
                current_evidence["actualStartupConfig"]["values"]["AllowLiveTrading"],
                "0",
            )
            self.assertEqual(
                current_evidence["actualStartupConfig"]["values"]["ExpertParameters"],
                "QuantGod_MT5_HFM_LiveSecondary.set",
            )
            self.assertEqual(
                current_evidence["actualDeployedPreset"]["values"]["ReadOnlyMode"],
                "true",
            )
            self.assertTrue(current_evidence["restartWouldKeepExecutionDisabled"])
            file_blocker_codes = {row["code"] for row in current_evidence["fileEvidenceBlockers"]}
            self.assertIn("STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF", file_blocker_codes)
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", file_blocker_codes)
            self.assertIn("DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF", file_blocker_codes)
            diff_package = package["reviewOnlyPresetDiffPackage"]
            self.assertEqual(diff_package["mode"], "REVIEW_ONLY_PRESET_DIFF_PACKAGE_NO_FILE_WRITE")
            self.assertEqual(diff_package["status"], "READY_FOR_HUMAN_DIFF_REVIEW")
            self.assertTrue(diff_package["sourcePresetPath"].endswith("QuantGod_MT5_HFM_LiveSecondary.set"))
            self.assertTrue(diff_package["startupConfigPath"].endswith("QuantGod_MT5_HFM_LiveSecondary_mac.ini"))
            self.assertFalse(diff_package["candidateFileWritten"])
            self.assertFalse(diff_package["writesMt5Preset"])
            self.assertFalse(diff_package["writesStartupConfig"])
            self.assertFalse(diff_package["writesMt5OrderRequest"])
            self.assertFalse(diff_package["orderSendAllowed"])
            self.assertIn("kill switch", diff_package["safetyRetained"])
            self.assertIn("MT5 OrderSend", diff_package["mustStayOffInThisArtifact"])
            diff_lanes = {row["lane"] for row in diff_package["laneDiffs"]}
            self.assertEqual(diff_lanes, {"forexMt5", "btcCryptoCfd"})
            forex_diff = next(row for row in diff_package["laneDiffs"] if row["lane"] == "forexMt5")
            forex_changes = {row["key"]: row for row in forex_diff["changes"]}
            self.assertEqual(forex_changes["ReadOnlyMode"]["current"], "true")
            self.assertEqual(forex_changes["ReadOnlyMode"]["candidate"], "false")
            self.assertEqual(forex_changes["EnablePilotAutoTrading"]["current"], "false")
            self.assertEqual(forex_changes["EnablePilotAutoTrading"]["candidate"], "true")
            self.assertEqual(forex_changes["PilotStartupEntryGuardMode"]["current"], "H1_STRICT")
            self.assertEqual(forex_changes["PilotStartupEntryGuardMode"]["candidate"], "FAST_WARMUP")
            self.assertEqual(forex_changes["PilotStartupEntryWaitNextH1Bar"]["current"], "true")
            self.assertEqual(forex_changes["PilotStartupEntryWaitNextH1Bar"]["candidate"], "false")
            self.assertFalse(forex_diff["canAttachNow"])
            btc_diff = next(row for row in diff_package["laneDiffs"] if row["lane"] == "btcCryptoCfd")
            btc_changes = {row["key"]: row for row in btc_diff["changes"]}
            self.assertEqual(btc_changes["Watchlist"]["candidate"], "#BTCUSD or reviewed broker crypto symbol")
            self.assertEqual(btc_changes["EnableEARequestReaderReviewHarness"]["candidate"], "reviewed staged enablement")
            self.assertFalse(btc_diff["canAttachNow"])
            self.assertIn("broker_order_send_path", btc_diff["implementationPrerequisites"])
            top_level_blockers = {row["code"] for row in activation["blockers"]}
            self.assertIn("STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF", top_level_blockers)
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", top_level_blockers)
            change_lanes = {row["lane"] for row in package["reviewedPresetChangePlan"]}
            self.assertEqual(change_lanes, {"forexMt5", "btcCryptoCfd"})
            forex_plan = next(row for row in package["reviewedPresetChangePlan"] if row["lane"] == "forexMt5")
            self.assertIn("EnablePilotRsiH1Live", {row["key"] for row in forex_plan["changes"]})
            btc_plan = next(row for row in package["reviewedPresetChangePlan"] if row["lane"] == "btcCryptoCfd")
            self.assertIn("EnableEARequestReaderReviewHarness", {row["key"] for row in btc_plan["changes"]})
            self.assertIn("MT5 OrderSend", btc_plan["mustStayOffUntilBrokerSendReview"])
            self.assertEqual(package["reviewOnlyPresetCandidateCount"], 2)
            self.assertTrue(package["candidateSafetyValidation"]["passed"])
            candidates = package["reviewOnlyPresetCandidates"]
            self.assertTrue(all(candidate["canAttachNow"] is False for candidate in candidates))
            self.assertTrue(all(candidate["candidateFileWritten"] is False for candidate in candidates))
            self.assertTrue(all(candidate["writesMt5Preset"] is False for candidate in candidates))
            forex_candidate = next(row for row in candidates if row["lane"] == "forexMt5")
            forex_settings = {row["key"]: row["candidateValue"] for row in forex_candidate["candidateSettings"]}
            self.assertEqual(forex_settings["ReadOnlyMode"], "false")
            self.assertEqual(forex_settings["EnablePilotRsiH1Live"], "true")
            self.assertEqual(forex_settings["EnableEARequestReaderReviewHarness"], "false")
            btc_candidate = next(row for row in candidates if row["lane"] == "btcCryptoCfd")
            btc_settings = {row["key"]: row["candidateValue"] for row in btc_candidate["candidateSettings"]}
            self.assertEqual(btc_settings["Watchlist"], "#BTCUSD or reviewed broker crypto symbol")
            self.assertIn("broker_order_send_path", btc_candidate["implementationPrerequisites"])
            self.assertFalse(activation["orderSendAllowed"])
            self.assertFalse(activation["writesMt5OrderRequest"])

            written_activation = build_live_pilot_activation_review(runtime, write=True)
            file_package = written_activation["presetActivationPackage"]["reviewOnlyCandidateFilePackage"]
            self.assertEqual(
                file_package["packageMode"],
                "REVIEW_ONLY_ACTIVATION_CANDIDATE_FILES_NO_MT5_MUTATION",
            )
            self.assertTrue(file_package["reviewArtifactFilesWritten"])
            self.assertFalse(file_package["safety"]["writesMt5Preset"])
            self.assertFalse(file_package["safety"]["writesMt5OrderRequest"])
            self.assertFalse(file_package["safety"]["orderSendAllowed"])
            self.assertEqual(file_package["candidateCount"], 2)
            manifest_path = Path(file_package["manifestPath"])
            self.assertTrue(manifest_path.exists())
            self.assertIn("review_only_activation_candidates", str(manifest_path))
            self.assertNotIn("MQL5/Presets", str(manifest_path))
            for row in file_package["files"]:
                self.assertTrue(Path(row["previewPath"]).exists())
                self.assertIn("review_only_activation_candidates", row["previewPath"])
                self.assertNotIn("MQL5/Presets", row["previewPath"])
                self.assertFalse(row["candidateFileWritten"])
                self.assertFalse(row["writesMt5Preset"])
                self.assertFalse(row["writesMt5OrderRequest"])
                self.assertFalse(row["orderSendAllowed"])

    def test_cutover_execution_mode_blockers_preserve_runtime_file_evidence(self) -> None:
        blockers = _execution_mode_blockers({
            "blockers": [
                {"code": "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF", "reasonZh": "ini off", "value": "0"},
                {"code": "DEPLOYED_PRESET_READ_ONLY_TRUE", "reasonZh": "preset read-only", "value": "true"},
                {"code": "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF", "reasonZh": "pilot off", "value": "false"},
                {"code": "UNRELATED_REVIEW_BLOCKER", "reasonZh": "not execution mode"},
            ],
        })

        codes = {row["code"] for row in blockers}
        self.assertIn("STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF", codes)
        self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", codes)
        self.assertIn("DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF", codes)
        self.assertNotIn("UNRELATED_REVIEW_BLOCKER", codes)

    def test_live_execution_rollback_review_ready_with_review_only_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(receipt_reconciliation_review_path(runtime), {
                "schema": "quantgod.receipt_reconciliation_review.v1",
                "status": "READY_FOR_RECEIPT_RECONCILIATION_REVIEW",
                "readyForReceiptReconciliationReview": True,
                "dataPlaneReconciliationReady": True,
                "autoDisablePolicy": {
                    "mode": "PLAN_ONLY_NO_MUTATION",
                    "autoDisableMutationAllowed": False,
                    "wouldTriggerAutoDisable": False,
                    "missingReceiptCount": 0,
                    "failedReceiptCount": 0,
                    "extraReceiptCount": 0,
                },
                "requestWritesAllowed": False,
                "receiptWritesAllowed": False,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "READY_FOR_BROKER_ORDER_SEND_REVIEW",
                "readyForBrokerOrderSendReview": True,
                "dataPlaneBrokerOrderSendReady": True,
                "brokerSendPlanCount": 1,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(ea_request_reader_review_path(runtime), {
                "schema": "quantgod.ea_request_reader_review.v1",
                "status": "READY_FOR_EA_REQUEST_READER_IMPLEMENTATION_REVIEW",
                "readyForEaRequestReaderImplementationReview": True,
                "dataPlaneEaRequestReaderReady": True,
                "runtimeStatusDisabled": True,
                "eaRequestReaderEnabled": False,
                "eaRequestFilesRead": False,
                "eaRequestFilesConsumed": False,
                "orderSendAllowed": False,
            })
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                "runtimeProbePassed": True,
                "dataPlaneReadyForLivePilotReview": True,
                "reviewPacketHash": "abc123",
                "orderSendAllowed": False,
            })
            self._write_json(approval_evidence_review_path(runtime), {
                "schema": "quantgod.live_operator_approval_evidence_review.v1",
                "status": "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED",
                "operatorApprovalProvided": True,
                "reviewPacketHash": "abc123",
                "orderSendAllowed": False,
            })

            rollback = build_live_execution_rollback_review(runtime, write=True)
            self.assertEqual(rollback["schema"], "quantgod.live_execution_rollback_review.v1")
            self.assertEqual(rollback["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertFalse(rollback["readyForLiveExecutionRollbackReview"])
            self.assertTrue(rollback["dataPlaneRollbackReady"])
            self.assertTrue(rollback["executionModeOnlyBlocked"])
            self.assertTrue(rollback["releaseTokenRequired"])
            self.assertFalse(rollback["releaseTokenProvided"])
            self.assertEqual(rollback["releaseTokenBlockerCode"], "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING")
            self.assertIn("ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING", {row["code"] for row in rollback["blockers"]})
            self.assertEqual(len(rollback["rollbackMatrix"]), 3)
            self.assertTrue(all(row["passed"] for row in rollback["rollbackChecklist"]))
            self.assertFalse(rollback["executionReady"])
            self.assertFalse(rollback["requestWritesAllowed"])
            self.assertFalse(rollback["receiptWritesAllowed"])
            self.assertFalse(rollback["brokerCallsMade"])
            self.assertFalse(rollback["autoDisableMutationAllowed"])
            self.assertFalse(rollback["eaRequestReaderEnabled"])
            self.assertFalse(rollback["orderSendAllowed"])
            saved = read_live_execution_rollback_review(runtime)
            self.assertEqual(saved["schema"], rollback["schema"])

    def test_live_execution_rollback_review_blocks_missing_broker_send_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(receipt_reconciliation_review_path(runtime), {
                "schema": "quantgod.receipt_reconciliation_review.v1",
                "status": "READY_FOR_RECEIPT_RECONCILIATION_REVIEW",
                "readyForReceiptReconciliationReview": True,
                "dataPlaneReconciliationReady": True,
                "autoDisablePolicy": {"autoDisableMutationAllowed": False, "wouldTriggerAutoDisable": False},
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_BROKER_ORDER_SEND_INPUTS",
                "readyForBrokerOrderSendReview": False,
                "dataPlaneBrokerOrderSendReady": False,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
            })
            self._write_json(ea_request_reader_review_path(runtime), {
                "schema": "quantgod.ea_request_reader_review.v1",
                "status": "READY_FOR_EA_REQUEST_READER_IMPLEMENTATION_REVIEW",
                "readyForEaRequestReaderImplementationReview": True,
                "dataPlaneEaRequestReaderReady": True,
                "runtimeStatusDisabled": True,
                "eaRequestReaderEnabled": False,
                "eaRequestFilesRead": False,
                "eaRequestFilesConsumed": False,
            })
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                "runtimeProbePassed": True,
                "dataPlaneReadyForLivePilotReview": True,
            })
            self._write_json(approval_evidence_review_path(runtime), {
                "schema": "quantgod.live_operator_approval_evidence_review.v1",
                "status": "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED",
                "operatorApprovalProvided": True,
            })

            rollback = build_live_execution_rollback_review(runtime, write=True)
            self.assertEqual(rollback["status"], "WAITING_LIVE_EXECUTION_ROLLBACK_INPUTS")
            self.assertFalse(rollback["readyForLiveExecutionRollbackReview"])
            self.assertFalse(rollback["dataPlaneRollbackReady"])
            self.assertIn(
                "broker_order_send_review_ready",
                {row["value"] for row in rollback["blockers"]},
            )
            self.assertFalse(rollback["brokerCallsMade"])
            self.assertFalse(rollback["autoDisableMutationAllowed"])
            self.assertFalse(rollback["orderSendAllowed"])

    def test_live_execution_rollback_review_data_plane_ready_without_operator_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(receipt_reconciliation_review_path(runtime), {
                "schema": "quantgod.receipt_reconciliation_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForReceiptReconciliationReview": False,
                "dataPlaneReconciliationReady": True,
                "executionModeOnlyBlocked": True,
                "autoDisablePolicy": {
                    "mode": "PLAN_ONLY_NO_MUTATION",
                    "autoDisableMutationAllowed": False,
                    "wouldTriggerAutoDisable": False,
                    "missingReceiptCount": 0,
                    "failedReceiptCount": 0,
                    "extraReceiptCount": 0,
                },
                "requestWritesAllowed": False,
                "receiptWritesAllowed": False,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForBrokerOrderSendReview": False,
                "dataPlaneBrokerOrderSendReady": True,
                "executionModeOnlyBlocked": True,
                "brokerSendPlanCount": 1,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(ea_request_reader_review_path(runtime), {
                "schema": "quantgod.ea_request_reader_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForEaRequestReaderImplementationReview": False,
                "dataPlaneEaRequestReaderReady": True,
                "executionModeOnlyBlocked": True,
                "runtimeStatusDisabled": True,
                "eaRequestReaderEnabled": False,
                "eaRequestFilesRead": False,
                "eaRequestFilesConsumed": False,
                "orderSendAllowed": False,
            })
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                "runtimeProbePassed": True,
                "dataPlaneReadyForLivePilotReview": True,
                "orderSendAllowed": False,
            })
            self._write_json(approval_evidence_review_path(runtime), {
                "schema": "quantgod.live_operator_approval_evidence_review.v1",
                "status": "WAITING_OPERATOR_APPROVAL_EVIDENCE",
                "operatorApprovalProvided": False,
                "orderSendAllowed": False,
            })

            rollback = build_live_execution_rollback_review(runtime, write=True)
            self.assertEqual(rollback["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertFalse(rollback["readyForLiveExecutionRollbackReview"])
            self.assertTrue(rollback["dataPlaneRollbackReady"])
            self.assertTrue(rollback["executionModeOnlyBlocked"])
            self.assertEqual(
                {row["code"] for row in rollback["blockers"]},
                {"EXECUTION_MODE_GATES_NOT_ACTIVE", "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING"},
            )
            by_check = {row["id"]: row for row in rollback["rollbackChecklist"]}
            self.assertTrue(by_check["receipt_reconciliation_review_ready"]["passed"])
            self.assertTrue(by_check["broker_order_send_review_ready"]["passed"])
            self.assertTrue(by_check["ea_request_reader_review_ready"]["passed"])
            self.assertFalse(by_check["operator_approval_evidence_accepted"]["passed"])
            self.assertTrue(all(row["passed"] for row in rollback["rollbackMatrix"]))
            self.assertFalse(rollback["orderSendAllowed"])
            self.assertFalse(rollback["brokerCallsMade"])
            self.assertFalse(rollback["autoDisableMutationAllowed"])

    def test_live_execution_cutover_data_plane_ready_without_operator_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            execution_blocker = {"code": "EXECUTION_MODE_GATES_NOT_ACTIVE", "reasonZh": "fixture"}
            self._write_json(sim_to_live_orchestrator_path(runtime), {
                "schema": "quantgod.sim_to_live_orchestrator.v1",
                "status": "READY_FOR_EXECUTION_ADAPTER_IMPLEMENTATION_REVIEW",
                "readyForLiveExecutionImplementationReview": False,
                "executionReady": False,
                "orderSendAllowed": False,
            })
            self._write_json(live_pilot_activation_review_path(runtime), {
                "schema": "quantgod.live_pilot_activation_review.v1",
                "status": "READY_FOR_LIVE_PILOT_ACTIVATION_REVIEW",
                "readyForLivePilotActivationReview": True,
                "dataPlaneActivationReady": True,
                "executionModeOnlyBlocked": True,
                "blockers": [execution_blocker],
                "orderSendAllowed": False,
            })
            self._write_json(receipt_reconciliation_review_path(runtime), {
                "schema": "quantgod.receipt_reconciliation_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForReceiptReconciliationReview": False,
                "dataPlaneReconciliationReady": True,
                "executionModeOnlyBlocked": True,
                "blockers": [execution_blocker],
                "requestWritesAllowed": False,
                "receiptWritesAllowed": False,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForBrokerOrderSendReview": False,
                "dataPlaneBrokerOrderSendReady": True,
                "executionModeOnlyBlocked": True,
                "blockers": [execution_blocker],
                "brokerSendPlanCount": 1,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(live_execution_rollback_review_path(runtime), {
                "schema": "quantgod.live_execution_rollback_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForLiveExecutionRollbackReview": False,
                "dataPlaneRollbackReady": True,
                "executionModeOnlyBlocked": True,
                "blockers": [execution_blocker],
                "rollbackMatrix": [{"id": "missing_or_failed_receipt", "passed": True}],
                "autoDisableMutationAllowed": False,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
            })
            self._write_json(ea_request_reader_review_path(runtime), {
                "schema": "quantgod.ea_request_reader_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForEaRequestReaderImplementationReview": False,
                "dataPlaneEaRequestReaderReady": True,
                "executionModeOnlyBlocked": True,
                "blockers": [execution_blocker],
                "eaRequestReaderEnabled": False,
                "eaRequestFilesRead": False,
                "eaRequestFilesConsumed": False,
                "orderSendAllowed": False,
            })
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                "runtimeProbePassed": True,
                "dataPlaneReadyForLivePilotReview": True,
                "executionModeOnlyBlocked": True,
                "blockers": [execution_blocker],
                "orderSendAllowed": False,
            })
            self._write_json(approval_evidence_review_path(runtime), {
                "schema": "quantgod.live_operator_approval_evidence_review.v1",
                "status": "WAITING_OPERATOR_APPROVAL_EVIDENCE",
                "operatorApprovalProvided": False,
                "orderSendAllowed": False,
            })
            self._write_json(order_request_contract_path(runtime), {
                "schema": "quantgod.mt5_order_request_contract.v1",
                "status": "READY_FOR_ORDER_REQUEST_CONTRACT_REVIEW",
                "readyForAdapterCodeReview": True,
                "runtimePreflightDataPlaneReadyForReview": True,
                "runtimePreflightExecutionModeOnlyBlocked": True,
                "orderSendAllowed": False,
            })
            self._write_json(execution_adapter_harness_path(runtime), {
                "schema": "quantgod.execution_adapter_harness.v1",
                "status": "READY_FOR_DISABLED_ADAPTER_IMPLEMENTATION_HARNESS_REVIEW",
                "readyForDisabledAdapterImplementationReview": True,
                "dataPlaneHarnessReady": True,
                "executionModeOnlyBlocked": True,
                "requestWritesAllowed": False,
                "requestFilesWritten": False,
                "receiptWritesAllowed": False,
                "receiptFilesWritten": False,
                "brokerCallsMade": False,
                "adapterExecutionAllowed": False,
                "writesMt5OrderRequest": False,
                "orderSendAllowed": False,
            })

            cutover = build_live_execution_cutover_review(runtime, write=True)
            self.assertEqual(cutover["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(cutover["dataPlaneCutoverReady"])
            self.assertTrue(cutover["executionModeOnlyBlocked"])
            self.assertFalse(cutover["readyForSeparateLiveExecutionCutoverImplementationReview"])
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", {row["code"] for row in cutover["blockers"]})
            self.assertNotIn("LIVE_EXECUTION_CUTOVER_CHECK_NOT_PASSED", {row["code"] for row in cutover["blockers"]})
            by_check = {row["id"]: row for row in cutover["cutoverChecklist"]}
            self.assertFalse(by_check["sim_to_live_orchestrator_live_ready"]["passed"])
            self.assertFalse(by_check["operator_approval_evidence_accepted"]["passed"])
            self.assertTrue(by_check["receipt_reconciliation_review_ready"]["passed"])
            self.assertTrue(by_check["broker_order_send_review_ready"]["passed"])
            self.assertTrue(by_check["rollback_auto_disable_review_ready"]["passed"])
            self.assertTrue(by_check["ea_request_reader_review_ready"]["passed"])
            self.assertFalse(cutover["orderSendAllowed"])
            self.assertFalse(cutover["writesMt5OrderRequest"])
            self.assertFalse(cutover["brokerCallsMade"])

    def test_receipt_and_ea_reader_refresh_reuse_existing_review_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            approval_json = runtime / "operator_approval.json"
            approval_json.write_text(json.dumps({"reviewPacketHash": "packet"}), encoding="utf-8")
            self._write_json(approval_evidence_review_path(runtime), {
                "schema": "quantgod.live_operator_approval_evidence_review.v1",
                "status": "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED",
                "operatorApprovalProvided": True,
                "operatorApprovalJsonPath": str(approval_json),
                "reviewPacketHash": "packet",
            })
            self._write_json(live_pilot_activation_review_path(runtime), {
                "schema": "quantgod.live_pilot_activation_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneActivationReady": True,
                "executionModeOnlyBlocked": True,
                "readyForLivePilotActivationReview": False,
                "requestFilesWritten": False,
                "brokerCallsMade": False,
                "adapterExecutionAllowed": False,
                "blockers": [{"code": "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED", "reasonZh": "fixture"}],
            })
            self._write_json(execution_adapter_harness_path(runtime), {
                "schema": "quantgod.execution_adapter_harness.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneHarnessReady": True,
                "executionModeOnlyBlocked": True,
                "readyForDisabledAdapterImplementationReview": False,
                "requestFilesWritten": False,
                "brokerCallsMade": False,
                "adapterExecutionAllowed": False,
                "plannedWrites": [{
                    "requestId": "qg-test-1",
                    "brokerSymbol": "#BTCUSD",
                    "side": "BUY",
                    "brokerCallsMade": False,
                    "adapterExecutionAllowed": False,
                    "wouldWriteRequestFile": False,
                    "wouldWriteReceiptFile": False,
                    "receipt": {
                        "schema": "quantgod.mt5_execution_receipt.v1",
                        "requestId": "qg-test-1",
                        "adapterMode": "REVIEW_ONLY",
                        "acceptedByAdapter": False,
                        "ticket": "",
                        "safetySnapshotHash": "hash",
                        "brokerSymbol": "#BTCUSD",
                        "side": "BUY",
                        "volumeLots": 0.01,
                    },
                }],
            })
            receipt = build_receipt_reconciliation_review(runtime, refresh_sources=True, write=True)
            self.assertEqual(receipt["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(receipt["dataPlaneReconciliationReady"])
            self.assertTrue(receipt["executionModeOnlyBlocked"])
            self.assertTrue(receipt["operatorApprovalJsonReusedFromPriorEvidence"])
            self.assertEqual(receipt["dependencyRefreshMode"]["activationReview"], "existing_artifact")
            self.assertEqual(receipt["dependencyRefreshMode"]["adapterHarness"], "existing_artifact")
            self.assertFalse(receipt["orderSendAllowed"])
            self.assertFalse(receipt["writesMt5OrderRequest"])
            self.assertFalse(receipt["receiptFilesWritten"])

            self._write_json(order_request_contract_path(runtime), {
                "schema": "quantgod.mt5_order_request_contract.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "runtimePreflightDataPlaneReadyForReview": True,
                "runtimePreflightExecutionModeOnlyBlocked": True,
                "readyForAdapterCodeReview": False,
                "requestContract": {
                    "inputSchema": "quantgod.mt5_reviewed_order_request.v1",
                    "receiptSchema": "quantgod.mt5_execution_receipt.v1",
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                },
            })
            ea_source = runtime / "QuantGod_MultiStrategy.request_reader_review.mq5"
            ea_source.write_text("\n".join([
                "// QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT",
                "// QG_EA_REQUEST_SCHEMA_VALIDATION_REQUIRED",
                "// QG_EA_IDEMPOTENCY_REQUEST_ID_REQUIRED",
                "// QG_EA_KILL_SWITCH_REQUIRED",
                "// QG_EA_RECEIPT_WRITER_REQUIRED",
                "// QG_EA_ORDER_SEND_REQUIRES_SEPARATE_REVIEW",
            ]), encoding="utf-8")
            ea_status = runtime / "QuantGod_EARequestReaderReviewStatus.json"
            ea_status.write_text(json.dumps(self._ea_request_reader_runtime_status()), encoding="utf-8")
            ea_reader = build_ea_request_reader_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                refresh_sources=True,
                write=True,
            )
            self.assertEqual(ea_reader["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(ea_reader["dataPlaneEaRequestReaderReady"])
            self.assertTrue(ea_reader["executionModeOnlyBlocked"])
            self.assertTrue(ea_reader["operatorApprovalJsonReusedFromPriorEvidence"])
            self.assertEqual(ea_reader["dependencyRefreshMode"]["activationReview"], "existing_artifact")
            self.assertEqual(ea_reader["dependencyRefreshMode"]["orderRequestContract"], "existing_artifact")
            self.assertEqual(ea_reader["dependencyRefreshMode"]["receiptReconciliationReview"], "existing_artifact")
            self.assertFalse(ea_reader["orderSendAllowed"])
            self.assertFalse(ea_reader["writesMt5OrderRequest"])
            self.assertFalse(ea_reader["eaRequestReaderEnabled"])

    def test_activation_and_receipt_refresh_keep_ready_artifacts_with_hfm_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            hfm_spec = runtime / "hfm_contract_spec.json"
            hfm_spec.write_text(json.dumps({"brokerSymbol": "#BTCUSD"}), encoding="utf-8")
            self._write_json(sim_to_live_orchestrator_path(runtime), {
                "schema": "quantgod.sim_to_live_orchestrator.v1",
                "status": "READY_FOR_EXECUTION_ADAPTER_IMPLEMENTATION_REVIEW",
                "readyForExecutionAdapterImplementationReview": True,
                "currentStage": "adapter_implementation_review",
            })
            self._write_json(sim_to_live_pipeline_path(runtime), {
                "schema": "quantgod.sim_to_live_automation_pipeline.v1",
                "status": "READY_FOR_SEPARATE_EXECUTION_ADAPTER_REVIEW",
                "readyForSeparateExecutionAdapterReview": True,
                "autoStage": "adapter_review",
            })
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                "runtimeProbePassed": True,
                "dataPlaneReadyForLivePilotReview": True,
                "reviewPacketHash": "packet",
            })
            self._write_json(approval_evidence_review_path(runtime), {
                "schema": "quantgod.live_operator_approval_evidence_review.v1",
                "status": "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED",
                "operatorApprovalProvided": True,
                "reviewPacketHash": "packet",
            })
            self._write_json(adapter_contract_validator_path(runtime), {
                "schema": "quantgod.adapter_contract_validator.v1",
                "status": "READY_FOR_ADAPTER_CONTRACT_VALIDATION_REVIEW",
                "validationPassed": True,
                "sampleValidationPassed": True,
                "dataPlaneValidationReady": True,
                "requestCount": 1,
                "receiptCount": 1,
            })
            self._write_json(execution_adapter_harness_path(runtime), {
                "schema": "quantgod.execution_adapter_harness.v1",
                "status": "READY_FOR_DISABLED_ADAPTER_IMPLEMENTATION_HARNESS_REVIEW",
                "readyForDisabledAdapterImplementationReview": True,
                "dataPlaneHarnessReady": True,
                "requestWritesAllowed": False,
                "requestFilesWritten": False,
                "brokerCallsMade": False,
                "adapterExecutionAllowed": False,
                "plannedWriteCount": 1,
                "reviewOnlyReceiptCount": 1,
                "plannedWrites": [{
                    "requestId": "qg-ready-1",
                    "brokerSymbol": "#BTCUSD",
                    "side": "BUY",
                    "brokerCallsMade": False,
                    "adapterExecutionAllowed": False,
                    "wouldWriteRequestFile": False,
                    "wouldWriteReceiptFile": False,
                    "receipt": {
                        "schema": "quantgod.mt5_execution_receipt.v1",
                        "requestId": "qg-ready-1",
                        "adapterMode": "REVIEW_ONLY",
                        "acceptedByAdapter": False,
                        "ticket": "",
                        "safetySnapshotHash": "hash",
                        "brokerSymbol": "#BTCUSD",
                        "side": "BUY",
                        "volumeLots": 0.01,
                    },
                }],
            })

            activation = build_live_pilot_activation_review(
                runtime,
                refresh_sources=True,
                hfm_contract_spec_json=str(hfm_spec),
                write=True,
            )
            self.assertEqual(activation["status"], "READY_FOR_LIVE_PILOT_ACTIVATION_REVIEW")
            self.assertTrue(activation["readyForLivePilotActivationReview"])
            self.assertEqual(activation["dependencyRefreshMode"]["orchestrator"], "existing_artifact")
            self.assertEqual(activation["dependencyRefreshMode"]["pipeline"], "existing_artifact")
            self.assertEqual(activation["dependencyRefreshMode"]["runtimePreflight"], "existing_artifact")
            self.assertEqual(activation["dependencyRefreshMode"]["adapterHarness"], "existing_artifact")
            self.assertFalse(activation["orderSendAllowed"])
            self.assertFalse(activation["writesMt5OrderRequest"])

            receipt = build_receipt_reconciliation_review(
                runtime,
                refresh_sources=True,
                hfm_contract_spec_json=str(hfm_spec),
                write=True,
            )
            self.assertEqual(receipt["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertFalse(receipt["readyForReceiptReconciliationReview"])
            self.assertTrue(receipt["dataPlaneReconciliationReady"])
            self.assertTrue(receipt["executionModeOnlyBlocked"])
            self.assertEqual(receipt["releaseTokenBlockerCode"], "RECEIPT_WRITER_RELEASE_TOKEN_MISSING")
            self.assertEqual(receipt["dependencyRefreshMode"]["activationReview"], "existing_artifact")
            self.assertEqual(receipt["dependencyRefreshMode"]["adapterHarness"], "existing_artifact")
            self.assertFalse(receipt["orderSendAllowed"])
            self.assertFalse(receipt["writesMt5OrderRequest"])

    def test_ea_request_reader_review_autodiscovers_secondary_live16_runtime_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            secondary_files = Path(tmp) / "live16" / "MQL5" / "Files"
            secondary_files.mkdir(parents=True)
            self._write_json(live_pilot_activation_review_path(runtime), {
                "schema": "quantgod.live_pilot_activation_review.v1",
                "status": "READY_FOR_LIVE_PILOT_ACTIVATION_REVIEW",
                "readyForLivePilotActivationReview": True,
                "dataPlaneActivationReady": True,
            })
            self._write_json(order_request_contract_path(runtime), {
                "schema": "quantgod.mt5_order_request_contract.v1",
                "status": "READY_FOR_ORDER_REQUEST_CONTRACT_REVIEW",
                "readyForAdapterCodeReview": True,
                "requestContract": {
                    "requestDirectory": "runtime/agent/mt5_order_requests",
                    "receiptDirectory": "runtime/agent/mt5_order_receipts",
                },
            })
            self._write_json(receipt_reconciliation_review_path(runtime), {
                "schema": "quantgod.receipt_reconciliation_review.v1",
                "status": "READY_FOR_RECEIPT_RECONCILIATION_REVIEW",
                "readyForReceiptReconciliationReview": True,
                "reconciliationPassed": True,
                "plannedRequestCount": 1,
                "receiptCount": 1,
            })
            self._write_json(secondary_files / "QuantGod_EARequestReaderReviewStatus.json", self._ea_request_reader_runtime_status())
            ea_source = runtime / "QuantGod_MultiStrategy.request_reader_review.mq5"
            ea_source.write_text("\n".join([
                "// QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT",
                "// QG_EA_REQUEST_SCHEMA_VALIDATION_REQUIRED",
                "// QG_EA_IDEMPOTENCY_REQUEST_ID_REQUIRED",
                "// QG_EA_KILL_SWITCH_REQUIRED",
                "// QG_EA_RECEIPT_WRITER_REQUIRED",
                "// QG_EA_ORDER_SEND_REQUIRES_SEPARATE_REVIEW",
            ]), encoding="utf-8")

            previous_env = os.environ.get("QG_HFM_CRYPTO_RUNTIME_DIR")
            os.environ["QG_HFM_CRYPTO_RUNTIME_DIR"] = str(secondary_files)
            try:
                review = build_ea_request_reader_review(
                    runtime,
                    ea_source_path=str(ea_source),
                    write=True,
                )
            finally:
                if previous_env is None:
                    os.environ.pop("QG_HFM_CRYPTO_RUNTIME_DIR", None)
                else:
                    os.environ["QG_HFM_CRYPTO_RUNTIME_DIR"] = previous_env

            self.assertEqual(review["status"], "READY_FOR_EA_REQUEST_READER_IMPLEMENTATION_REVIEW")
            self.assertTrue(review["readyForRuntimeEaRequestReaderStatusReview"])
            self.assertTrue(review["readyForEaRequestReaderImplementationReview"])
            self.assertIn(str(secondary_files), review["runtimeStatusSource"]["path"])
            self.assertFalse(review["eaRequestReaderEnabled"])
            self.assertFalse(review["eaRequestFilesRead"])
            self.assertFalse(review["receiptFilesWritten"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])

    def test_builds_dossier_without_execution_rights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            sample_walk_forward_runtime(runtime, overwrite=True)

            payload = build_live_automation_readiness(runtime, write=True)

            self.assertEqual(payload["schema"], "quantgod.live_automation_readiness.v1")
            self.assertFalse(payload["canPromoteToLiveNow"])
            self.assertFalse(payload["autoPromotionToLiveAllowed"])
            self.assertTrue(payload["safety"]["operatorApprovalRequired"])
            self.assertTrue(payload["safety"]["executionLaneSpecRequired"])
            self.assertFalse(payload["safety"]["orderSendAllowed"])
            self.assertFalse(payload["safety"]["mt5OrderSendAllowed"])
            self.assertFalse(payload["safety"]["hfmCryptoExecutionAllowed"])
            self.assertFalse(payload["approvalPacket"]["writesOrders"])
            self.assertIn("usdjpyMt5", payload["lanes"])
            self.assertIn("hfmCryptoCfd", payload["lanes"])
            self.assertTrue((runtime / "agent" / "QuantGod_LiveAutomationReadiness.json").exists())

            saved = read_live_automation_readiness(runtime)
            self.assertEqual(saved["schema"], payload["schema"])

            review = build_live_execution_review_packet(runtime, write=True)
            self.assertEqual(review["schema"], "quantgod.live_execution_review_packet.v1")
            self.assertFalse(review["canPromoteToLiveNow"])
            self.assertFalse(review["autoPromotionToLiveAllowed"])
            self.assertIn("dryRunOrderIntentSpec", review["contracts"]["usdjpyMt5"])
            self.assertFalse(review["contracts"]["usdjpyMt5"]["dryRunOrderIntentSpec"]["writesMt5OrderRequest"])
            self.assertFalse(review["contracts"]["hfmCryptoCfd"]["dryRunOrderIntentSpec"]["writesMt5OrderRequest"])
            self.assertTrue((runtime / "agent" / "QuantGod_LiveExecutionReviewPacket.json").exists())
            saved_review = read_live_execution_review_packet(runtime)
            self.assertEqual(saved_review["schema"], review["schema"])

            approval = build_live_operator_approval_draft(runtime, write=True)
            self.assertEqual(approval["schema"], "quantgod.live_operator_approval_draft.v1")
            self.assertFalse(approval["operatorApprovalProvided"])
            self.assertFalse(approval["approvalCanUnlockLiveExecution"])
            self.assertFalse(approval["canPromoteToLiveNow"])
            self.assertFalse(approval["writesMt5OrderRequest"])
            self.assertFalse(approval["mt5PendingOrderIntentsWritten"])
            self.assertIn("reviewPacketHash", approval["manualApprovalTemplate"])
            self.assertTrue((runtime / "agent" / "QuantGod_LiveOperatorApprovalDraft.json").exists())
            saved_approval = read_live_operator_approval_draft(runtime)
            self.assertEqual(saved_approval["schema"], approval["schema"])

            plan = build_dry_run_live_execution_plan(runtime, write=True)
            self.assertEqual(plan["schema"], "quantgod.dry_run_live_execution_plan.v1")
            self.assertFalse(plan["mt5PendingOrderIntentsWritten"])
            self.assertFalse(plan["writesMt5OrderRequest"])
            self.assertFalse(plan["canPromoteToLiveNow"])
            self.assertTrue((runtime / "agent" / "QuantGod_DryRunLiveExecutionPlan.json").exists())
            saved_plan = read_dry_run_live_execution_plan(runtime)
            self.assertEqual(saved_plan["schema"], plan["schema"])

            execution_lane = build_live_execution_lane_spec(runtime, write=True)
            self.assertEqual(execution_lane["schema"], "quantgod.live_execution_lane_spec.v1")
            self.assertFalse(execution_lane["readyForImplementationReview"])
            self.assertFalse(execution_lane["executionReady"])
            self.assertFalse(execution_lane["implementationContract"]["orderSendAllowed"])
            self.assertFalse(execution_lane["implementationContract"]["writesMt5OrderRequest"])
            self.assertTrue((runtime / "agent" / "QuantGod_LiveExecutionLaneSpec.json").exists())
            saved_execution_lane = read_live_execution_lane_spec(runtime)
            self.assertEqual(saved_execution_lane["schema"], execution_lane["schema"])

            replay = build_dry_run_intent_replay(runtime, write=True)
            self.assertEqual(replay["schema"], "quantgod.live_dry_run_intent_replay.v1")
            self.assertFalse(replay["replayPassed"])
            self.assertFalse(replay["executionReady"])
            self.assertFalse(replay["writesMt5OrderRequest"])
            self.assertTrue((runtime / "agent" / "QuantGod_LiveDryRunIntentReplay.json").exists())
            saved_replay = read_dry_run_intent_replay(runtime)
            self.assertEqual(saved_replay["schema"], replay["schema"])

            order_contract = build_mt5_order_request_contract(runtime, write=True)
            self.assertEqual(order_contract["schema"], "quantgod.mt5_order_request_contract.v1")
            self.assertFalse(order_contract["readyForAdapterCodeReview"])
            self.assertFalse(order_contract["executionReady"])
            self.assertFalse(order_contract["requestWritesAllowed"])
            self.assertFalse(order_contract["writesMt5OrderRequest"])
            self.assertFalse(order_contract["mt5PendingOrderIntentsWritten"])
            self.assertFalse(order_contract["orderSendAllowed"])
            self.assertFalse(order_contract["brokerExecutionAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_MT5OrderRequestContract.json").exists())
            saved_order_contract = read_mt5_order_request_contract(runtime)
            self.assertEqual(saved_order_contract["schema"], order_contract["schema"])

            pipeline = build_sim_to_live_automation_pipeline(runtime, write=True)
            self.assertEqual(pipeline["schema"], "quantgod.sim_to_live_automation_pipeline.v1")
            self.assertFalse(pipeline["readyForSeparateExecutionAdapterReview"])
            self.assertFalse(pipeline["executionReady"])
            self.assertFalse(pipeline["requestWritesAllowed"])
            self.assertFalse(pipeline["writesMt5OrderRequest"])
            self.assertFalse(pipeline["orderSendAllowed"])
            self.assertFalse(pipeline["brokerExecutionAllowed"])
            self.assertFalse(pipeline["operatorApprovalEvidenceAccepted"])
            self.assertEqual(
                pipeline["operatorApprovalJsonStaleOrRejected"],
                pipeline["operatorApprovalJsonProvided"],
            )
            self.assertTrue((runtime / "agent" / "QuantGod_SimToLiveAutomationPipeline.json").exists())
            saved_pipeline = read_sim_to_live_automation_pipeline(runtime)
            self.assertEqual(saved_pipeline["schema"], pipeline["schema"])

            adapter_review = build_execution_adapter_review(runtime, write=True)
            self.assertEqual(adapter_review["schema"], "quantgod.execution_adapter_review.v1")
            self.assertFalse(adapter_review["readyForExecutionAdapterCodeReview"])
            self.assertFalse(adapter_review["executionReady"])
            self.assertFalse(adapter_review["adapterExecutionAllowed"])
            self.assertFalse(adapter_review["requestWritesAllowed"])
            self.assertFalse(adapter_review["requestFilesWritten"])
            self.assertFalse(adapter_review["brokerCallsMade"])
            self.assertFalse(adapter_review["writesMt5OrderRequest"])
            self.assertFalse(adapter_review["orderSendAllowed"])
            self.assertFalse(adapter_review["brokerExecutionAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_ExecutionAdapterReview.json").exists())
            saved_adapter_review = read_execution_adapter_review(runtime)
            self.assertEqual(saved_adapter_review["schema"], adapter_review["schema"])

            evidence_intake = build_live_evidence_intake(runtime, write=True)
            self.assertEqual(evidence_intake["schema"], "quantgod.live_evidence_intake.v1")
            self.assertFalse(evidence_intake["executionReady"])
            self.assertFalse(evidence_intake["requestWritesAllowed"])
            self.assertFalse(evidence_intake["requestFilesWritten"])
            self.assertFalse(evidence_intake["brokerCallsMade"])
            self.assertFalse(evidence_intake["adapterExecutionAllowed"])
            self.assertFalse(evidence_intake["writesMt5OrderRequest"])
            self.assertFalse(evidence_intake["orderSendAllowed"])
            self.assertFalse(evidence_intake["brokerExecutionAllowed"])
            self.assertTrue(evidence_intake["externalMarketRemoved"])
            self.assertGreaterEqual(evidence_intake["fileInputSummary"]["missingChecklistCount"], 1)
            self.assertTrue((runtime / "agent" / "QuantGod_LiveEvidenceIntake.json").exists())
            saved_evidence_intake = read_live_evidence_intake(runtime)
            self.assertEqual(saved_evidence_intake["schema"], evidence_intake["schema"])

            promotion_candidates = build_live_promotion_candidates(runtime, write=True)
            self.assertEqual(promotion_candidates["schema"], "quantgod.live_promotion_candidates.v1")
            self.assertEqual(promotion_candidates["status"], "WAITING_LIVE_PROMOTION_CANDIDATES")
            self.assertFalse(promotion_candidates["readyForOperatorReviewPacket"])
            self.assertFalse(promotion_candidates["executionReady"])
            self.assertFalse(promotion_candidates["requestWritesAllowed"])
            self.assertFalse(promotion_candidates["requestFilesWritten"])
            self.assertFalse(promotion_candidates["brokerCallsMade"])
            self.assertFalse(promotion_candidates["adapterExecutionAllowed"])
            self.assertFalse(promotion_candidates["writesMt5OrderRequest"])
            self.assertFalse(promotion_candidates["orderSendAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_LivePromotionCandidates.json").exists())
            saved_promotion_candidates = read_live_promotion_candidates(runtime)
            self.assertEqual(saved_promotion_candidates["schema"], promotion_candidates["schema"])

            promotion_controller = build_live_promotion_controller(runtime, write=True)
            self.assertEqual(promotion_controller["schema"], "quantgod.live_promotion_controller.v1")
            self.assertEqual(promotion_controller["status"], "WAITING_PROMOTION_CANDIDATE")
            self.assertFalse(promotion_controller["reviewAutomationRequested"])
            self.assertFalse(promotion_controller["reviewArtifactsWrittenByThisRun"])
            self.assertFalse(promotion_controller["executionReady"])
            self.assertFalse(promotion_controller["requestWritesAllowed"])
            self.assertFalse(promotion_controller["requestFilesWritten"])
            self.assertFalse(promotion_controller["brokerCallsMade"])
            self.assertFalse(promotion_controller["adapterExecutionAllowed"])
            self.assertFalse(promotion_controller["writesMt5OrderRequest"])
            self.assertFalse(promotion_controller["orderSendAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_LivePromotionController.json").exists())
            saved_promotion_controller = read_live_promotion_controller(runtime)
            self.assertEqual(saved_promotion_controller["schema"], promotion_controller["schema"])

            adapter_sandbox = build_adapter_sandbox_review_bundle(runtime, write=True)
            self.assertEqual(adapter_sandbox["schema"], "quantgod.adapter_sandbox_review_bundle.v1")
            self.assertEqual(adapter_sandbox["status"], "WAITING_ADAPTER_SANDBOX_INPUTS")
            self.assertFalse(adapter_sandbox["sandboxReadyForCodeReview"])
            self.assertFalse(adapter_sandbox["executionReady"])
            self.assertFalse(adapter_sandbox["requestWritesAllowed"])
            self.assertFalse(adapter_sandbox["requestFilesWritten"])
            self.assertFalse(adapter_sandbox["brokerCallsMade"])
            self.assertFalse(adapter_sandbox["adapterExecutionAllowed"])
            self.assertFalse(adapter_sandbox["writesMt5OrderRequest"])
            self.assertFalse(adapter_sandbox["orderSendAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_AdapterSandboxReviewBundle.json").exists())
            saved_adapter_sandbox = read_adapter_sandbox_review_bundle(runtime)
            self.assertEqual(saved_adapter_sandbox["schema"], adapter_sandbox["schema"])

            adapter_validator = build_adapter_contract_validator(runtime, write=True)
            self.assertEqual(adapter_validator["schema"], "quantgod.adapter_contract_validator.v1")
            self.assertEqual(adapter_validator["status"], "WAITING_ADAPTER_CONTRACT_VALIDATION_INPUTS")
            self.assertFalse(adapter_validator["validationPassed"])
            self.assertFalse(adapter_validator["executionReady"])
            self.assertFalse(adapter_validator["requestWritesAllowed"])
            self.assertFalse(adapter_validator["requestFilesWritten"])
            self.assertFalse(adapter_validator["brokerCallsMade"])
            self.assertFalse(adapter_validator["adapterExecutionAllowed"])
            self.assertFalse(adapter_validator["writesMt5OrderRequest"])
            self.assertFalse(adapter_validator["orderSendAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_AdapterContractValidator.json").exists())
            saved_adapter_validator = read_adapter_contract_validator(runtime)
            self.assertEqual(saved_adapter_validator["schema"], adapter_validator["schema"])

            orchestrator = build_sim_to_live_orchestrator(runtime, write=True)
            self.assertEqual(orchestrator["schema"], "quantgod.sim_to_live_orchestrator.v1")
            self.assertEqual(orchestrator["status"], "WAITING_SIM_TO_LIVE_ORCHESTRATOR_INPUTS")
            self.assertEqual(orchestrator["orchestratorMode"], "SIM_TO_LIVE_REVIEW_AUTOMATION_ONLY")
            self.assertFalse(orchestrator["readyForExecutionAdapterImplementationReview"])
            self.assertFalse(orchestrator["executionReady"])
            self.assertFalse(orchestrator["requestWritesAllowed"])
            self.assertFalse(orchestrator["requestFilesWritten"])
            self.assertFalse(orchestrator["brokerCallsMade"])
            self.assertFalse(orchestrator["adapterExecutionAllowed"])
            self.assertFalse(orchestrator["writesMt5OrderRequest"])
            self.assertFalse(orchestrator["orderSendAllowed"])
            self.assertGreaterEqual(orchestrator["stageCount"], 12)
            self.assertGreaterEqual(orchestrator["liveExecutionStageCount"], 4)
            self.assertFalse(orchestrator["readyForLiveExecutionImplementationReview"])
            self.assertEqual(orchestrator["currentLiveExecutionStage"], "disabled_adapter_harness")
            self.assertTrue((runtime / "agent" / "QuantGod_SimToLiveOrchestrator.json").exists())
            saved_orchestrator = read_sim_to_live_orchestrator(runtime)
            self.assertEqual(saved_orchestrator["schema"], orchestrator["schema"])

            harness = build_execution_adapter_harness(runtime, write=True)
            self.assertEqual(harness["schema"], "quantgod.execution_adapter_harness.v1")
            self.assertEqual(harness["status"], "WAITING_EXECUTION_ADAPTER_HARNESS_INPUTS")
            self.assertFalse(harness["readyForDisabledAdapterImplementationReview"])
            self.assertFalse(harness["executionReady"])
            self.assertFalse(harness["requestWritesAllowed"])
            self.assertFalse(harness["requestFilesWritten"])
            self.assertFalse(harness["brokerCallsMade"])
            self.assertFalse(harness["adapterExecutionAllowed"])
            self.assertFalse(harness["writesMt5OrderRequest"])
            self.assertFalse(harness["orderSendAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_ExecutionAdapterHarness.json").exists())
            saved_harness = read_execution_adapter_harness(runtime)
            self.assertEqual(saved_harness["schema"], harness["schema"])

            activation = build_live_pilot_activation_review(runtime, write=True)
            self.assertEqual(activation["schema"], "quantgod.live_pilot_activation_review.v1")
            self.assertEqual(activation["status"], "WAITING_LIVE_PILOT_ACTIVATION_INPUTS")
            self.assertFalse(activation["readyForLivePilotActivationReview"])
            self.assertFalse(activation["executionReady"])
            self.assertFalse(activation["livePilotActivationAllowed"])
            self.assertFalse(activation["requestWritesAllowed"])
            self.assertFalse(activation["requestFilesWritten"])
            self.assertFalse(activation["brokerCallsMade"])
            self.assertFalse(activation["adapterExecutionAllowed"])
            self.assertFalse(activation["writesMt5OrderRequest"])
            self.assertFalse(activation["orderSendAllowed"])
            saved_activation = read_live_pilot_activation_review(runtime)
            self.assertEqual(saved_activation["schema"], activation["schema"])

            receipt_review = build_receipt_reconciliation_review(runtime, write=True)
            self.assertEqual(receipt_review["schema"], "quantgod.receipt_reconciliation_review.v1")
            self.assertEqual(receipt_review["status"], "WAITING_RECEIPT_RECONCILIATION_INPUTS")
            self.assertFalse(receipt_review["readyForReceiptReconciliationReview"])
            self.assertFalse(receipt_review["reconciliationPassed"])
            self.assertFalse(receipt_review["executionReady"])
            self.assertFalse(receipt_review["livePilotActivationAllowed"])
            self.assertFalse(receipt_review["requestWritesAllowed"])
            self.assertFalse(receipt_review["requestFilesWritten"])
            self.assertFalse(receipt_review["receiptWritesAllowed"])
            self.assertFalse(receipt_review["receiptFilesWritten"])
            self.assertFalse(receipt_review["brokerCallsMade"])
            self.assertFalse(receipt_review["adapterExecutionAllowed"])
            self.assertFalse(receipt_review["autoDisableMutationAllowed"])
            self.assertFalse(receipt_review["writesMt5OrderRequest"])
            self.assertFalse(receipt_review["orderSendAllowed"])
            saved_receipt_review = read_receipt_reconciliation_review(runtime)
            self.assertEqual(saved_receipt_review["schema"], receipt_review["schema"])

            ea_reader = build_ea_request_reader_review(runtime, write=True)
            self.assertEqual(ea_reader["schema"], "quantgod.ea_request_reader_review.v1")
            self.assertEqual(ea_reader["status"], "WAITING_EA_REQUEST_READER_INPUTS")
            self.assertFalse(ea_reader["readyForEaRequestReaderImplementationReview"])
            self.assertFalse(ea_reader["executionReady"])
            self.assertFalse(ea_reader["livePilotActivationAllowed"])
            self.assertFalse(ea_reader["requestWritesAllowed"])
            self.assertFalse(ea_reader["requestFilesWritten"])
            self.assertFalse(ea_reader["receiptWritesAllowed"])
            self.assertFalse(ea_reader["receiptFilesWritten"])
            self.assertFalse(ea_reader["brokerCallsMade"])
            self.assertFalse(ea_reader["adapterExecutionAllowed"])
            self.assertFalse(ea_reader["autoDisableMutationAllowed"])
            self.assertFalse(ea_reader["eaRequestReaderAllowed"])
            self.assertFalse(ea_reader["eaRequestReaderEnabled"])
            self.assertFalse(ea_reader["eaRequestFilesRead"])
            self.assertFalse(ea_reader["eaRequestFilesConsumed"])
            self.assertFalse(ea_reader["eaOrderSendAllowed"])
            self.assertFalse(ea_reader["writesMt5OrderRequest"])
            self.assertFalse(ea_reader["orderSendAllowed"])
            self.assertEqual(ea_reader["missingMarkerCount"], 0)
            self.assertTrue(all(row["present"] for row in ea_reader["markerChecks"]))
            self.assertFalse(ea_reader["runtimeStatusFound"])
            self.assertFalse(ea_reader["readyForRuntimeEaRequestReaderStatusReview"])
            self.assertFalse(ea_reader["runtimeStatusSafetyPassed"])
            self.assertIn(
                "EA_REQUEST_READER_RUNTIME_STATUS_MISSING",
                {row["code"] for row in ea_reader["blockers"]},
            )
            saved_ea_reader = read_ea_request_reader_review(runtime)
            self.assertEqual(saved_ea_reader["schema"], ea_reader["schema"])

            cutover = build_live_execution_cutover_review(runtime, write=True)
            self.assertEqual(cutover["schema"], "quantgod.live_execution_cutover_review.v1")
            self.assertEqual(cutover["status"], "WAITING_LIVE_EXECUTION_CUTOVER_INPUTS")
            self.assertFalse(cutover["readyForSeparateLiveExecutionCutoverImplementationReview"])
            self.assertFalse(cutover["executionReady"])
            self.assertFalse(cutover["liveExecutionCutoverAllowed"])
            self.assertFalse(cutover["livePilotActivationAllowed"])
            self.assertFalse(cutover["requestWritesAllowed"])
            self.assertFalse(cutover["requestFilesWritten"])
            self.assertFalse(cutover["receiptWritesAllowed"])
            self.assertFalse(cutover["receiptFilesWritten"])
            self.assertFalse(cutover["brokerCallsMade"])
            self.assertFalse(cutover["adapterExecutionAllowed"])
            self.assertFalse(cutover["eaRequestReaderAllowed"])
            self.assertFalse(cutover["writesMt5OrderRequest"])
            self.assertFalse(cutover["orderSendAllowed"])
            self.assertGreaterEqual(len(cutover["cutoverChecklist"]), 8)
            self.assertTrue((runtime / "agent" / "QuantGod_LiveExecutionCutoverReview.json").exists())
            saved_cutover = read_live_execution_cutover_review(runtime)
            self.assertEqual(saved_cutover["schema"], cutover["schema"])

            implementation_spec = build_live_execution_implementation_spec(runtime, write=True)
            self.assertEqual(implementation_spec["schema"], "quantgod.live_execution_implementation_spec.v1")
            self.assertEqual(implementation_spec["status"], "WAITING_LIVE_EXECUTION_IMPLEMENTATION_SPEC_INPUTS")
            self.assertFalse(implementation_spec["readyForLiveExecutionImplementationSpecReview"])
            self.assertFalse(implementation_spec["executionReady"])
            self.assertFalse(implementation_spec["liveExecutionCutoverAllowed"])
            self.assertFalse(implementation_spec["requestWritesAllowed"])
            self.assertFalse(implementation_spec["receiptWritesAllowed"])
            self.assertFalse(implementation_spec["brokerCallsMade"])
            self.assertFalse(implementation_spec["eaRequestReaderAllowed"])
            self.assertFalse(implementation_spec["writesMt5OrderRequest"])
            self.assertFalse(implementation_spec["orderSendAllowed"])
            self.assertGreaterEqual(len(implementation_spec["implementationSteps"]), 5)
            self.assertIn(
                "LIVE_EXECUTION_CUTOVER_REVIEW_NOT_READY",
                {row["code"] for row in implementation_spec["blockers"]},
            )
            self.assertTrue((runtime / "agent" / "QuantGod_LiveExecutionImplementationSpec.json").exists())
            saved_implementation_spec = read_live_execution_implementation_spec(runtime)
            self.assertEqual(saved_implementation_spec["schema"], implementation_spec["schema"])

            adapter_write = build_live_execution_adapter_write_review(runtime, write=True)
            self.assertEqual(adapter_write["schema"], "quantgod.live_execution_adapter_write_review.v1")
            self.assertEqual(adapter_write["status"], "WAITING_LIVE_EXECUTION_ADAPTER_WRITE_INPUTS")
            self.assertFalse(adapter_write["readyForLiveExecutionAdapterWriteReview"])
            self.assertFalse(adapter_write["executionReady"])
            self.assertFalse(adapter_write["requestWritesAllowed"])
            self.assertFalse(adapter_write["requestFilesWritten"])
            self.assertFalse(adapter_write["brokerCallsMade"])
            self.assertFalse(adapter_write["adapterExecutionAllowed"])
            self.assertFalse(adapter_write["writesMt5OrderRequest"])
            self.assertFalse(adapter_write["orderSendAllowed"])
            self.assertIn(
                "LIVE_EXECUTION_IMPLEMENTATION_SPEC_NOT_READY",
                {row["code"] for row in adapter_write["blockers"]},
            )
            self.assertTrue((runtime / "agent" / "QuantGod_LiveExecutionAdapterWriteReview.json").exists())
            saved_adapter_write = read_live_execution_adapter_write_review(runtime)
            self.assertEqual(saved_adapter_write["schema"], adapter_write["schema"])

            ea_consumption = build_ea_request_consumption_review(runtime, write=True)
            self.assertEqual(ea_consumption["schema"], "quantgod.ea_request_consumption_review.v1")
            self.assertEqual(ea_consumption["status"], "WAITING_EA_REQUEST_CONSUMPTION_INPUTS")
            self.assertFalse(ea_consumption["readyForEaRequestConsumptionReview"])
            self.assertFalse(ea_consumption["executionReady"])
            self.assertFalse(ea_consumption["requestWritesAllowed"])
            self.assertFalse(ea_consumption["requestFilesWritten"])
            self.assertFalse(ea_consumption["receiptWritesAllowed"])
            self.assertFalse(ea_consumption["receiptFilesWritten"])
            self.assertFalse(ea_consumption["brokerCallsMade"])
            self.assertFalse(ea_consumption["adapterExecutionAllowed"])
            self.assertFalse(ea_consumption["eaRequestReaderAllowed"])
            self.assertFalse(ea_consumption["eaRequestReaderEnabled"])
            self.assertFalse(ea_consumption["eaRequestFilesRead"])
            self.assertFalse(ea_consumption["eaRequestFilesConsumed"])
            self.assertFalse(ea_consumption["eaOrderSendAllowed"])
            self.assertFalse(ea_consumption["writesMt5OrderRequest"])
            self.assertFalse(ea_consumption["orderSendAllowed"])
            self.assertIn(
                "EA_REQUEST_READER_REVIEW_NOT_READY",
                {row["code"] for row in ea_consumption["blockers"]},
            )
            self.assertTrue((runtime / "agent" / "QuantGod_EARequestConsumptionReview.json").exists())
            saved_ea_consumption = read_ea_request_consumption_review(runtime)
            self.assertEqual(saved_ea_consumption["schema"], ea_consumption["schema"])

            broker_send = build_broker_order_send_review(runtime, write=True)
            self.assertEqual(broker_send["schema"], "quantgod.broker_order_send_review.v1")
            self.assertEqual(broker_send["status"], "WAITING_BROKER_ORDER_SEND_INPUTS")
            self.assertFalse(broker_send["readyForBrokerOrderSendReview"])
            self.assertFalse(broker_send["executionReady"])
            self.assertFalse(broker_send["requestWritesAllowed"])
            self.assertFalse(broker_send["requestFilesWritten"])
            self.assertFalse(broker_send["receiptWritesAllowed"])
            self.assertFalse(broker_send["receiptFilesWritten"])
            self.assertFalse(broker_send["brokerCallsMade"])
            self.assertFalse(broker_send["adapterExecutionAllowed"])
            self.assertFalse(broker_send["brokerExecutionAllowed"])
            self.assertFalse(broker_send["eaOrderSendAllowed"])
            self.assertFalse(broker_send["writesMt5OrderRequest"])
            self.assertFalse(broker_send["orderSendAllowed"])
            self.assertIn(
                "EA_REQUEST_CONSUMPTION_REVIEW_NOT_READY",
                {row["code"] for row in broker_send["blockers"]},
            )
            self.assertTrue((runtime / "agent" / "QuantGod_BrokerOrderSendReview.json").exists())
            saved_broker_send = read_broker_order_send_review(runtime)
            self.assertEqual(saved_broker_send["schema"], broker_send["schema"])

    def test_orchestrator_aggregates_execution_release_gate_blockers(self) -> None:
        artifacts = {
            "liveExecutionAdapterWriteReview": {
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneAdapterWriteReady": True,
                "disabledWriterImplementationContract": {
                    "releaseGate": {
                        "tokenRequired": True,
                        "tokenProvidedInThisArtifact": False,
                        "blockerCode": "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
                    },
                },
            },
            "eaRequestConsumptionReview": {
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneEaRequestConsumptionReady": True,
                "readerReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "REQUEST_READER_RELEASE_TOKEN_MISSING",
                },
            },
            "brokerOrderSendReview": {
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneBrokerOrderSendReady": True,
                "brokerReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                },
            },
            "receiptReconciliation": {
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneReconciliationReady": True,
                "receiptReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "RECEIPT_WRITER_RELEASE_TOKEN_MISSING",
                },
            },
            "liveExecutionRollbackReview": {
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneRollbackReady": True,
                "rollbackReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
                },
            },
        }

        rows = _release_gate_checklist(artifacts)
        summary = _release_gate_summary(rows)
        packet = _execution_release_readiness_packet(
            rows,
            {
                "blocked": 4,
                "blockerCodes": [
                    "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
                    "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                    "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
                    "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
                ],
            },
        )
        blockers = _release_gate_blockers(rows)
        codes = {row["code"] for row in blockers}

        self.assertEqual(len(rows), 5)
        self.assertEqual(summary["blocked"], 5)
        self.assertFalse(summary["allReleased"])
        self.assertEqual(packet["status"], "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE")
        self.assertFalse(packet["releaseReady"])
        self.assertFalse(packet["canReleaseExecutionNow"])
        self.assertFalse(packet["orderSendAllowed"])
        self.assertFalse(packet["mt5OrderSendAllowed"])
        self.assertFalse(packet["requestFilesWritten"])
        self.assertFalse(packet["brokerCallsMade"])
        self.assertEqual(packet["blockedGateCount"], 5)
        self.assertIn("broker_order_send_release", packet["blockedGateIds"])
        self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", packet["blockedReleaseTokenCodes"])
        self.assertTrue(all(not row["sideEffectAllowedNow"] for row in packet["gates"]))
        self.assertIn("REQUEST_WRITE_RELEASE_TOKEN_MISSING", codes)
        self.assertIn("REQUEST_READER_RELEASE_TOKEN_MISSING", codes)
        self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", codes)
        self.assertIn("RECEIPT_WRITER_RELEASE_TOKEN_MISSING", codes)
        self.assertIn("ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING", codes)
        self.assertTrue(all(row["tokenRequired"] is True for row in rows))
        self.assertTrue(all(row["tokenProvided"] is False for row in rows))
        self.assertEqual(
            {row["gateId"]: row["tokenName"] for row in rows},
            {
                "request_writer_release": "QG_REVIEWED_MT5_REQUEST_WRITE_RELEASE_V1",
                "ea_reader_release": "QG_REVIEWED_EA_REQUEST_READER_RELEASE_V1",
                "broker_order_send_release": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                "receipt_writer_release": "QG_REVIEWED_RECEIPT_WRITER_RELEASE_V1",
                "rollback_auto_disable_release": "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1",
            },
        )

    def test_release_token_evidence_review_maps_missing_tokens_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "combinedVerifiedUsdProfit": 137.22,
                "qualifyingLaneIds": ["forexMt5", "btcCryptoCfd"],
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "releaseTokens": [
                        {
                            "gateId": "broker_order_send_release",
                            "labelZh": "Broker OrderSend",
                            "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                            "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                            "sideEffectZh": "调用 MT5 OrderSend",
                            "sourceArtifact": "brokerOrderSendReview",
                            "dataPlaneReady": True,
                            "tokenProvided": False,
                        },
                        {
                            "gateId": "rollback_auto_disable_release",
                            "labelZh": "Rollback auto-disable",
                            "tokenName": "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1",
                            "blockerCode": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
                            "sideEffectZh": "修改实盘状态或 preset",
                            "sourceArtifact": "liveExecutionRollbackReview",
                            "dataPlaneReady": True,
                            "tokenProvided": False,
                        },
                    ],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "safety": {},
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneBrokerOrderSendReady": True,
                "brokerReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "requestFilesWritten": False,
                "receiptWritesAllowed": False,
            })
            self._write_json(live_execution_rollback_review_path(runtime), {
                "schema": "quantgod.live_execution_rollback_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneRollbackReady": True,
                "rollbackReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "requestFilesWritten": False,
                "receiptWritesAllowed": False,
                "livePresetMutationAllowed": False,
            })

            review = build_release_token_evidence_review(runtime, write=True)
            self.assertEqual(review["schema"], "quantgod.release_token_evidence_review.v1")
            self.assertEqual(review["status"], "WAITING_RELEASE_TOKEN_EVIDENCE_AND_SEPARATE_REVIEW")
            self.assertEqual(review["combinedVerifiedUsdProfit"], 137.22)
            self.assertEqual(review["releaseTokenCount"], 2)
            self.assertEqual(review["missingEvidenceCount"], 2)
            self.assertEqual(review["tokenOrEvidenceMissingCount"], 2)
            self.assertEqual(review["incompleteEvidenceCount"], 0)
            self.assertEqual(review["evidenceCompleteCount"], 2)
            self.assertEqual(review["noSideEffectEvidenceCompleteCount"], 2)
            self.assertEqual(review["tokenProvidedCount"], 0)
            self.assertEqual(review["tokenMissingCount"], 2)
            self.assertTrue(review["tokenMissingOnly"])
            self.assertTrue(review["releaseTokenMissingOnlyAfterEvidenceComplete"])
            self.assertTrue(review["sourceReleaseMinimalDiffReviewPath"].endswith("QuantGod_ReleaseMinimalDiffReview.json"))
            self.assertEqual(
                review["releaseBlockerClass"],
                "TOKEN_MISSING_ONLY_AFTER_NO_SIDE_EFFECT_EVIDENCE",
            )
            self.assertIn("无副作用证据已完成 2/2", review["statusZh"])
            self.assertIn("release token 已提供 0/2", review["statusZh"])
            self.assertEqual(review["manualReleaseReviewReadyCount"], 2)
            self.assertEqual(review["manualReleaseReviewStatus"], "READY_FOR_SEPARATE_SIGNOFF_REVIEW")
            self.assertIn("2/2 个 release token 可进入单独签收评审", review["manualReleaseReviewStatusZh"])
            self.assertFalse(review["canReleaseExecutionNow"])
            self.assertFalse(review["releaseTokenCanBeAutoMinted"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])
            self.assertFalse(review["brokerCallsMade"])
            self.assertFalse(review["receiptWritesAllowed"])
            by_gate = {row["gateId"]: row for row in review["evidenceRows"]}
            self.assertIn("OrderSend plan is schema-validated", by_gate["broker_order_send_release"]["requiredChecks"])
            self.assertIn("rollback cannot increase risk or lot size", by_gate["rollback_auto_disable_release"]["requiredChecks"])
            self.assertTrue(by_gate["broker_order_send_release"]["noSideEffectEvidenceComplete"])
            self.assertTrue(by_gate["rollback_auto_disable_release"]["noSideEffectEvidenceComplete"])
            broker_check_ids = {
                row["id"] for row in by_gate["broker_order_send_release"]["evidenceChecks"] if row["passed"]
            }
            self.assertIn("source_artifact_present", broker_check_ids)
            self.assertIn("source_artifact_data_plane_ready", broker_check_ids)
            self.assertIn("source_artifact_no_execution_flags", broker_check_ids)
            self.assertIn("release_gate_still_blocked", broker_check_ids)
            self.assertIn("mt5_order_requests_empty", broker_check_ids)
            self.assertIn("mt5_order_receipts_empty", broker_check_ids)
            self.assertTrue(all(row["canMintNow"] is False for row in review["evidenceRows"]))
            self.assertTrue(all(row["releaseAllowedNow"] is False for row in review["evidenceRows"]))
            signoff_by_gate = {row["gateId"]: row for row in review["manualReleaseReviewRows"]}
            self.assertEqual(
                signoff_by_gate["broker_order_send_release"]["status"],
                "READY_FOR_SEPARATE_SIGNOFF_REVIEW",
            )
            self.assertFalse(signoff_by_gate["broker_order_send_release"]["canSignOffHere"])
            self.assertFalse(signoff_by_gate["broker_order_send_release"]["canMintTokenHere"])
            self.assertFalse(signoff_by_gate["broker_order_send_release"]["orderSendAllowed"])
            self.assertIn(
                "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                signoff_by_gate["broker_order_send_release"]["signoffQuestionZh"],
            )
            self.assertIn(
                "mt5OrderSendAllowed",
                signoff_by_gate["broker_order_send_release"]["mustRemainFalseHere"],
            )
            self.assertTrue(release_token_evidence_review_path(runtime).exists())
            hydrated = read_release_token_evidence_review(runtime)
            self.assertEqual(hydrated["schema"], review["schema"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_release_token_evidence_recovers_tokens_from_readiness_when_minimal_diff_is_stale_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            release_tokens = [
                {
                    "gateId": "broker_order_send_release",
                    "labelZh": "Broker OrderSend",
                    "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                    "sideEffectZh": "调用 MT5 OrderSend",
                    "sourceArtifact": "brokerOrderSendReview",
                    "dataPlaneReady": True,
                    "tokenProvided": False,
                    "tokenRequired": True,
                },
                {
                    "gateId": "rollback_auto_disable_release",
                    "labelZh": "Rollback auto-disable",
                    "tokenName": "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1",
                    "blockerCode": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
                    "sideEffectZh": "修改实盘状态或 preset",
                    "sourceArtifact": "liveExecutionRollbackReview",
                    "dataPlaneReady": True,
                    "tokenProvided": False,
                    "tokenRequired": True,
                },
            ]
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "combinedVerifiedUsdProfit": 137.22,
                "releaseBlockedCount": 0,
                "executionModeBlockedCount": 0,
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "changeCount": 0,
                    "releaseTokenCount": 0,
                    "proposedChanges": [],
                    "releaseTokens": [],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerCallsMade": False,
            })
            self._write_json(release_readiness_refresh_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_readiness_refresh.v1",
                "status": "WAITING_RELEASE_TOKENS",
                "releaseUnblockPlan": {
                    "schema": "quantgod.release_unblock_plan.v1",
                    "profitTargetReached": True,
                    "combinedVerifiedUsdProfit": 137.22,
                    "releaseTokenReviewRows": release_tokens,
                    "releaseBlockedCount": 2,
                    "executionModeBlockedCount": 0,
                    "canReleaseExecutionNow": False,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                    "brokerCallsMade": False,
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerCallsMade": False,
            })

            review = build_release_token_evidence_review(runtime, write=False)

            self.assertEqual(review["releaseTokenCount"], 2)
            self.assertEqual(review["tokenMissingCount"], 2)
            self.assertEqual(review["missingEvidenceCount"], 2)
            self.assertEqual(review["tokenOrEvidenceMissingCount"], 2)
            self.assertEqual(review["incompleteEvidenceCount"], 2)
            self.assertFalse(review["releaseTokenMissingOnlyAfterEvidenceComplete"])
            self.assertEqual(
                review["blockedReleaseTokenCodes"],
                [
                    "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                    "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
                ],
            )
            self.assertEqual(
                [row["gateId"] for row in review["manualReleaseReviewRows"]],
                ["broker_order_send_release", "rollback_auto_disable_release"],
            )
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])

    def test_release_token_evidence_recovers_tokens_from_orchestrator_when_refresh_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            release_tokens = [
                {
                    "gateId": "request_writer_release",
                    "labelZh": "Python request writer",
                    "tokenName": "QG_REVIEWED_REQUEST_WRITER_RELEASE_V1",
                    "blockerCode": "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
                    "sideEffectZh": "写 MT5 request 文件",
                    "sourceArtifact": "liveExecutionAdapterWriteReview",
                    "dataPlaneReady": True,
                    "tokenProvided": False,
                    "tokenRequired": True,
                },
                {
                    "gateId": "broker_order_send_release",
                    "labelZh": "Broker OrderSend",
                    "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                    "sideEffectZh": "调用 MT5 OrderSend",
                    "sourceArtifact": "brokerOrderSendReview",
                    "dataPlaneReady": True,
                    "tokenProvided": False,
                    "tokenRequired": True,
                },
            ]
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "releaseTokenCount": 0,
                    "releaseTokens": [],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerCallsMade": False,
            })
            self._write_json(release_readiness_refresh_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_readiness_refresh.v1",
                "releaseUnblockPlan": {
                    "schema": "quantgod.release_unblock_plan.v1",
                    "releaseTokenReviewRows": [],
                    "canReleaseExecutionNow": False,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                    "brokerCallsMade": False,
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerCallsMade": False,
            })
            self._write_json(sim_to_live_orchestrator_path(runtime), {
                "ok": True,
                "schema": "quantgod.sim_to_live_orchestrator.v1",
                "executionReleaseGateChecklist": release_tokens,
                "executionReleaseReadinessPacket": {
                    "schema": "quantgod.execution_release_readiness_packet.v1",
                    "gateCount": 2,
                    "blockedGateCount": 2,
                    "gates": release_tokens,
                    "canReleaseExecutionNow": False,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "requestFilesWritten": False,
                    "brokerCallsMade": False,
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerCallsMade": False,
            })

            review = build_release_token_evidence_review(runtime, write=False)

            self.assertEqual(review["releaseTokenCount"], 2)
            self.assertEqual(
                review["blockedReleaseTokenCodes"],
                ["REQUEST_WRITE_RELEASE_TOKEN_MISSING", "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING"],
            )
            self.assertEqual(
                [row["gateId"] for row in review["evidenceRows"]],
                ["request_writer_release", "broker_order_send_release"],
            )
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])

    def test_release_token_signoff_evidence_matrix_maps_acknowledgements_without_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            release_tokens = [
                {
                    "gateId": "broker_order_send_release",
                    "labelZh": "Broker OrderSend",
                    "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                    "sideEffectZh": "调用 MT5 OrderSend",
                    "sourceArtifact": "brokerOrderSendReview",
                    "dataPlaneReady": True,
                    "tokenProvided": False,
                },
                {
                    "gateId": "rollback_auto_disable_release",
                    "labelZh": "Rollback auto-disable",
                    "tokenName": "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1",
                    "blockerCode": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
                    "sideEffectZh": "修改实盘状态或 preset",
                    "sourceArtifact": "liveExecutionRollbackReview",
                    "dataPlaneReady": True,
                    "tokenProvided": False,
                },
            ]
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "releaseBlockedCount": 2,
                "executionModeBlockedCount": 4,
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "changeCount": 2,
                    "releaseTokenCount": 2,
                    "proposedChanges": [
                        {"key": "ReadOnlyMode", "from": "true", "to": "false"},
                        {"key": "EnablePilotAutoTrading", "from": "false", "to": "true"},
                    ],
                    "releaseTokens": release_tokens,
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerCallsMade": False,
            })
            self._write_json(release_token_evidence_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_token_evidence_review.v1",
                "status": "WAITING_RELEASE_TOKEN_EVIDENCE_AND_SEPARATE_REVIEW",
                "releaseTokenCount": 2,
                "noSideEffectEvidenceCompleteCount": 2,
                "tokenProvidedCount": 0,
                "tokenMissingCount": 2,
                "manualReleaseReviewReadyCount": 2,
                "manualReleaseReviewRows": [
                    {
                        **release_tokens[0],
                        "readyForSeparateSignoffReview": True,
                        "sourceArtifactPath": str(broker_order_send_review_path(runtime)),
                    },
                    {
                        **release_tokens[1],
                        "readyForSeparateSignoffReview": True,
                        "sourceArtifactPath": str(live_execution_rollback_review_path(runtime)),
                    },
                ],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerCallsMade": False,
            })
            self._write_json(runtime_preflight_path(runtime), {
                "ok": True,
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "READY_FOR_RUNTIME_PREFLIGHT_REVIEW",
                "probeResults": {
                    "killSwitchOk": True,
                    "riskLimitsOk": True,
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "brokerSendPlans": [
                    {
                        "killSwitchRequired": True,
                        "brokerCallsMade": False,
                        "orderSendAllowed": False,
                        "mt5OrderSendAllowed": False,
                    }
                ],
                "checklist": [
                    {"id": "risk_controls_required", "passed": True},
                    {"id": "request_fuses_bound", "passed": True},
                ],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "writesMt5OrderRequest": False,
            })
            self._write_json(live_execution_rollback_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.live_execution_rollback_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneRollbackReady": True,
                "executionModeOnlyBlocked": True,
                "releaseTokenProvided": False,
                "rollbackChecklist": [
                    {"id": "receipt_reconciliation_review_ready", "passed": True},
                    {"id": "no_execution_side_effects_in_rollback_review", "passed": True},
                ],
                "rollbackMatrix": [
                    {"id": "missing_or_failed_receipt", "passed": True},
                    {"id": "broker_send_wrapper_not_ready", "passed": True},
                    {"id": "ea_reader_unexpectedly_enabled_or_consuming", "passed": True},
                ],
                "blockers": [{"code": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING"}],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "writesMt5OrderRequest": False,
                "autoDisableMutationAllowed": False,
            })

            matrix = build_release_token_signoff_evidence_matrix(runtime, write=True)
            self.assertEqual(matrix["schema"], "quantgod.release_token_signoff_evidence_matrix.v1")
            self.assertEqual(matrix["status"], "SIGNOFF_EVIDENCE_PARTIAL_REVIEW_ONLY")
            self.assertEqual(matrix["releaseTokenCount"], 2)
            self.assertEqual(matrix["acknowledgementReadyCount"], 4)
            by_ack = {row["acknowledgement"]: row for row in matrix["acknowledgementRows"]}
            self.assertTrue(by_ack["acknowledgeNoSideEffectEvidence"]["evidenceReadyForSignoff"])
            self.assertEqual(
                by_ack["acknowledgeNoSideEffectEvidence"]["details"]["tokenOrEvidenceMissingCount"],
                None,
            )
            self.assertTrue(
                by_ack["acknowledgeNoSideEffectEvidence"]["details"]["releaseTokenMissingOnlyAfterEvidenceComplete"]
            )
            self.assertTrue(by_ack["acknowledgeKillSwitch"]["evidenceReadyForSignoff"])
            self.assertTrue(by_ack["acknowledgeRollback"]["evidenceReadyForSignoff"])
            self.assertTrue(by_ack["acknowledgeRiskLimits"]["evidenceReadyForSignoff"])
            self.assertFalse(by_ack["acknowledgeExecutionModeSeparatelyReviewed"]["evidenceReadyForSignoff"])
            self.assertEqual(
                by_ack["acknowledgeExecutionModeSeparatelyReviewed"]["status"],
                "REVIEW_PACKAGE_READY_WAITING_SEPARATE_SIGNOFF",
            )
            self.assertEqual(matrix["gatesWithCompleteEvidence"], 0)
            self.assertTrue(matrix["gateRows"])
            self.assertEqual(
                matrix["gateRows"][0]["missingEvidenceAcknowledgements"],
                ["acknowledgeExecutionModeSeparatelyReviewed"],
            )
            self.assertFalse(matrix["decision"]["canAcceptSignoffHere"])
            self.assertFalse(matrix["decision"]["canMintTokenHere"])
            self.assertFalse(matrix["decision"]["orderSendAllowed"])
            self.assertFalse(matrix["decision"]["writesMt5OrderRequest"])
            self.assertTrue(release_token_signoff_evidence_matrix_path(runtime).exists())
            hydrated = read_release_token_signoff_evidence_matrix(runtime)
            self.assertEqual(hydrated["schema"], matrix["schema"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_release_token_signoff_matrix_counts_complete_handoff_as_execution_review_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            release_token = {
                "gateId": "broker_order_send_release",
                "labelZh": "Broker OrderSend",
                "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                "sideEffectZh": "调用 MT5 OrderSend",
                "sourceArtifact": "brokerOrderSendReview",
                "dataPlaneReady": True,
                "tokenProvided": False,
            }
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "releaseBlockedCount": 1,
                "executionModeBlockedCount": 4,
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "proposedChanges": [{"key": "ReadOnlyMode", "from": "true", "to": "false"}],
                    "releaseTokens": [release_token],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(release_token_evidence_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_token_evidence_review.v1",
                "releaseTokenCount": 1,
                "noSideEffectEvidenceCompleteCount": 1,
                "tokenProvidedCount": 0,
                "tokenMissingCount": 1,
                "manualReleaseReviewReadyCount": 1,
                "manualReleaseReviewRows": [{
                    **release_token,
                    "readyForSeparateSignoffReview": True,
                    "sourceArtifactPath": str(broker_order_send_review_path(runtime)),
                }],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(runtime_preflight_path(runtime), {
                "ok": True,
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "probeResults": {"killSwitchOk": True, "riskLimitsOk": True},
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "brokerSendPlans": [{"killSwitchRequired": True}],
                "checklist": [
                    {"id": "risk_controls_required", "passed": True},
                    {"id": "request_fuses_bound", "passed": True},
                ],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
            })
            self._write_json(live_execution_rollback_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.live_execution_rollback_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneRollbackReady": True,
                "executionModeOnlyBlocked": True,
                "releaseTokenProvided": False,
                "rollbackChecklist": [
                    {"id": "receipt_reconciliation_review_ready", "passed": True},
                    {"id": "broker_order_send_review_ready", "passed": True},
                    {"id": "ea_request_reader_review_ready", "passed": True},
                    {"id": "no_execution_side_effects_in_rollback_review", "passed": True},
                ],
                "rollbackMatrix": [
                    {"id": "missing_or_failed_receipt", "passed": True},
                    {"id": "broker_send_wrapper_not_ready", "passed": True},
                    {"id": "ea_reader_unexpectedly_enabled_or_consuming", "passed": True},
                ],
                "blockers": [{"code": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING"}],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
            })
            build_release_token_signoff_input_review(
                runtime,
                signoff_json=json.dumps({
                    "schema": "quantgod.release_token_signoff_input.v1",
                    "operatorId": "operator-review-only",
                    "reviewedAtIso": "2026-06-03T00:00:00Z",
                    "releaseTokenSignoffs": [{
                        "gateId": "broker_order_send_release",
                        "acknowledgeNoSideEffectEvidence": True,
                        "acknowledgeKillSwitch": True,
                        "acknowledgeRollback": True,
                        "acknowledgeRiskLimits": True,
                        "acknowledgeExecutionModeSeparatelyReviewed": True,
                        "finalSignoffText": (
                            "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1 "
                            "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING reviewed for separate release lane"
                        ),
                    }],
                }),
                write=True,
            )

            matrix = build_release_token_signoff_evidence_matrix(runtime, write=False)
            by_ack = {row["acknowledgement"]: row for row in matrix["acknowledgementRows"]}
            execution_row = by_ack["acknowledgeExecutionModeSeparatelyReviewed"]
            self.assertEqual(matrix["status"], "SIGNOFF_EVIDENCE_AND_INPUT_READY_FOR_SEPARATE_RELEASE_LANE")
            self.assertEqual(matrix["acknowledgementReadyCount"], 5)
            self.assertEqual(matrix["gatesWithCompleteEvidence"], 1)
            self.assertEqual(
                matrix["gateRows"][0]["status"],
                "EVIDENCE_AND_INPUT_READY_FOR_SEPARATE_RELEASE_LANE",
            )
            self.assertTrue(execution_row["evidenceReadyForSignoff"])
            self.assertEqual(execution_row["status"], "SEPARATE_SIGNOFF_INPUT_READY_FOR_RELEASE_LANE")
            self.assertEqual(execution_row["details"]["completeSignoffCount"], 1)
            self.assertEqual(execution_row["details"]["releaseTokenCount"], 1)
            self.assertFalse(matrix["decision"]["canReleaseExecutionNow"])
            self.assertFalse(matrix["decision"]["orderSendAllowed"])
            self.assertFalse(matrix["decision"]["canMintTokenHere"])

    def test_release_token_signoff_matrix_counts_execution_wait_only_rollback_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            release_token = {
                "gateId": "rollback_auto_disable_release",
                "labelZh": "Rollback auto-disable",
                "tokenName": "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1",
                "blockerCode": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
                "sideEffectZh": "修改实盘状态或 preset",
                "sourceArtifact": "liveExecutionRollbackReview",
                "dataPlaneReady": True,
                "tokenProvided": False,
            }
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "releaseBlockedCount": 1,
                "executionModeBlockedCount": 4,
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "proposedChanges": [{"key": "ReadOnlyMode", "from": "true", "to": "false"}],
                    "releaseTokens": [release_token],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(release_token_evidence_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_token_evidence_review.v1",
                "releaseTokenCount": 1,
                "noSideEffectEvidenceCompleteCount": 1,
                "tokenProvidedCount": 0,
                "tokenMissingCount": 1,
                "manualReleaseReviewReadyCount": 1,
                "manualReleaseReviewRows": [{
                    **release_token,
                    "readyForSeparateSignoffReview": True,
                    "sourceArtifactPath": str(live_execution_rollback_review_path(runtime)),
                }],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(runtime_preflight_path(runtime), {
                "ok": True,
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "probeResults": {
                    "killSwitchOk": True,
                    "riskLimitsOk": True,
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "brokerSendPlans": [{"killSwitchRequired": True}],
                "checklist": [
                    {"id": "risk_controls_required", "passed": True},
                    {"id": "request_fuses_bound", "passed": True},
                ],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
            })
            self._write_json(live_execution_rollback_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.live_execution_rollback_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneRollbackReady": True,
                "executionModeOnlyBlocked": True,
                "releaseTokenProvided": False,
                "rollbackChecklist": [
                    {"id": "receipt_reconciliation_review_ready", "passed": False},
                    {"id": "broker_order_send_review_ready", "passed": False},
                    {"id": "ea_request_reader_review_ready", "passed": False},
                    {"id": "no_execution_side_effects_in_rollback_review", "passed": True},
                ],
                "rollbackMatrix": [
                    {"id": "missing_or_failed_receipt", "passed": False},
                    {"id": "broker_send_wrapper_not_ready", "passed": False},
                    {"id": "ea_reader_unexpectedly_enabled_or_consuming", "passed": False},
                ],
                "blockers": [
                    {"code": "EXECUTION_MODE_GATES_NOT_ACTIVE"},
                    {"code": "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING"},
                    {"code": "DEPLOYED_PRESET_READ_ONLY_TRUE"},
                ],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "writesMt5OrderRequest": False,
                "autoDisableMutationAllowed": False,
            })

            matrix = build_release_token_signoff_evidence_matrix(runtime, write=False)
            by_ack = {row["acknowledgement"]: row for row in matrix["acknowledgementRows"]}
            rollback_row = by_ack["acknowledgeRollback"]
            self.assertEqual(matrix["acknowledgementReadyCount"], 4)
            self.assertTrue(rollback_row["evidenceReadyForSignoff"])
            self.assertTrue(rollback_row["details"]["executionWaitOnly"])
            self.assertFalse(rollback_row["details"]["checklistPassed"])
            self.assertFalse(rollback_row["details"]["matrixPassed"])
            self.assertFalse(matrix["decision"]["canReleaseExecutionNow"])
            self.assertFalse(matrix["decision"]["orderSendAllowed"])

    def test_release_token_signoff_matrix_recovers_preflight_from_local_approval_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            repo_approval_dir = Path("runtime") / "agent"
            repo_approval_dir.mkdir(parents=True, exist_ok=True)
            approval_path = repo_approval_dir / "QuantGod_UserChatOperatorApproval_Live16.json"
            previous = approval_path.read_text(encoding="utf-8") if approval_path.exists() else None
            try:
                self._write_json(approval_path, {
                    "operatorId": "test-live16-operator",
                    "approvedAtIso": "2026-06-03T00:00:00Z",
                    "approvedLanes": ["hfmCryptoCfd"],
                    "reviewPacketHash": "test-hash",
                    "maxDailyLossAck": True,
                    "killSwitchAck": True,
                    "credentialsExternalAck": True,
                    "dryRunFirstAck": True,
                    "hfmContractSpecAck": True,
                    "finalHumanApprovalText": "测试用本地 Live16 approval evidence，不开启实盘、不写订单、不改 live preset。",
                })
                self._write_json(runtime / "QuantGod_Dashboard.json", {
                    "timestamp": "2026-06-03T16:00:00+09:00",
                    "tradeStatus": "SHADOW",
                    "executionEnabled": False,
                    "readOnlyMode": True,
                    "livePilotMode": False,
                    "tradeAllowed": False,
                    "pilotKillSwitch": False,
                    "account": {
                        "number": 198135388,
                        "server": "HFMarketsGlobal-Live16",
                        "currency": "USD",
                    },
                    "symbols": [{"symbol": "#BTCUSD", "brokerSymbol": "#BTCUSD", "canonicalSymbol": "BTCUSD", "spread": 62}],
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
                })
                self._write_json(runtime_preflight_path(runtime), {
                    "ok": True,
                    "schema": "quantgod.live_runtime_preflight_probe.v1",
                    "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                    "operatorApprovalJsonProvided": False,
                    "probeResults": {"killSwitchOk": True, "riskLimitsOk": False},
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                })
                release_tokens = [{
                    "gateId": "broker_order_send_release",
                    "labelZh": "Broker OrderSend",
                    "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                    "sideEffectZh": "调用 MT5 OrderSend",
                    "sourceArtifact": "brokerOrderSendReview",
                    "dataPlaneReady": True,
                    "tokenProvided": False,
                }]
                self._write_json(release_minimal_diff_review_path(runtime), {
                    "ok": True,
                    "schema": "quantgod.release_minimal_diff_review.v1",
                    "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                    "profitTargetReached": True,
                    "releaseBlockedCount": 1,
                    "executionModeBlockedCount": 4,
                    "reviewPackage": {"proposedChanges": [{"key": "ReadOnlyMode"}], "releaseTokens": release_tokens},
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                })
                self._write_json(release_token_evidence_review_path(runtime), {
                    "ok": True,
                    "schema": "quantgod.release_token_evidence_review.v1",
                    "releaseTokenCount": 1,
                    "noSideEffectEvidenceCompleteCount": 1,
                    "tokenProvidedCount": 0,
                    "tokenMissingCount": 1,
                    "manualReleaseReviewReadyCount": 1,
                    "manualReleaseReviewRows": [{**release_tokens[0], "readyForSeparateSignoffReview": True}],
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                })
                self._write_json(broker_order_send_review_path(runtime), {
                    "ok": True,
                    "schema": "quantgod.broker_order_send_review.v1",
                    "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                    "brokerSendPlans": [{"killSwitchRequired": True}],
                    "checklist": [
                        {"id": "risk_controls_required", "passed": True},
                        {"id": "request_fuses_bound", "passed": True},
                    ],
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                })
                self._write_json(live_execution_rollback_review_path(runtime), {
                    "ok": True,
                    "schema": "quantgod.live_execution_rollback_review.v1",
                    "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                    "dataPlaneRollbackReady": True,
                    "executionModeOnlyBlocked": True,
                    "rollbackChecklist": [],
                    "rollbackMatrix": [],
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                })

                replay_payload = {
                    "replayPassed": True,
                    "reviewPacketHash": "test-hash",
                    "intentCount": 1,
                    "passedIntentCount": 1,
                    "replayedIntents": [{
                        "intentId": "intent-1",
                        "lane": "HFM_CRYPTO_CFD",
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                    }],
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                }
                lane_spec_payload = {
                    "readyForImplementationReview": True,
                    "reviewPacketHash": "test-hash",
                    "approvedLanes": ["hfmCryptoCfd"],
                    "laneContracts": [{
                        "dryRunIntentId": "intent-1",
                        "lane": "HFM_CRYPTO_CFD",
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                        "riskLimits": {
                            "maxNotionalUsd": 100,
                            "maxDailyLossPct": 1,
                            "maxDailyLossR": 1,
                            "maxConsecutiveLosses": 2,
                        },
                    }],
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                }
                with mock.patch(
                    "tools.live_automation_readiness.preflight.build_dry_run_intent_replay",
                    return_value=replay_payload,
                ), mock.patch(
                    "tools.live_automation_readiness.preflight.build_live_execution_lane_spec",
                    return_value=lane_spec_payload,
                ):
                    matrix = build_release_token_signoff_evidence_matrix(runtime, write=False)
                by_ack = {row["acknowledgement"]: row for row in matrix["acknowledgementRows"]}
                self.assertEqual(matrix["acknowledgementReadyCount"], 3)
                self.assertTrue(by_ack["acknowledgeKillSwitch"]["evidenceReadyForSignoff"])
                self.assertTrue(by_ack["acknowledgeRiskLimits"]["evidenceReadyForSignoff"])
                self.assertEqual(
                    by_ack["acknowledgeRiskLimits"]["details"]["preflightStatus"],
                    "WAITING_EXECUTION_MODE_ACTIVATION",
                )
                self.assertFalse(matrix["decision"]["orderSendAllowed"])
            finally:
                if previous is None:
                    approval_path.unlink(missing_ok=True)
                else:
                    approval_path.write_text(previous, encoding="utf-8")

    def test_release_token_signoff_draft_is_input_template_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "combinedVerifiedUsdProfit": 137.22,
                "qualifyingLaneIds": ["forexMt5", "btcCryptoCfd"],
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "releaseTokens": [
                        {
                            "gateId": "broker_order_send_release",
                            "labelZh": "Broker OrderSend",
                            "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                            "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                            "sideEffectZh": "调用 MT5 OrderSend",
                            "sourceArtifact": "brokerOrderSendReview",
                            "dataPlaneReady": True,
                            "tokenProvided": False,
                        },
                    ],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneBrokerOrderSendReady": True,
                "brokerReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "requestFilesWritten": False,
                "receiptWritesAllowed": False,
            })
            evidence = build_release_token_evidence_review(runtime, write=True)
            self.assertEqual(evidence["manualReleaseReviewStatus"], "READY_FOR_SEPARATE_SIGNOFF_REVIEW")

            draft = build_release_token_signoff_draft(runtime, write=True)
            self.assertEqual(draft["schema"], "quantgod.release_token_signoff_draft.v1")
            self.assertEqual(draft["status"], "READY_FOR_SEPARATE_SIGNOFF_INPUT")
            self.assertEqual(draft["releaseTokenCount"], 1)
            self.assertEqual(draft["readyForSeparateSignoffCount"], 1)
            self.assertTrue(draft["cannotBeUsedAsReleaseToken"])
            self.assertFalse(draft["canAcceptSignoffHere"])
            self.assertFalse(draft["canSignOffHere"])
            self.assertFalse(draft["canMintTokenHere"])
            self.assertFalse(draft["canReleaseExecutionNow"])
            self.assertFalse(draft["releaseTokenCanBeAutoMinted"])
            self.assertFalse(draft["orderSendAllowed"])
            self.assertFalse(draft["mt5OrderSendAllowed"])
            self.assertFalse(draft["writesMt5OrderRequest"])
            self.assertFalse(draft["brokerCallsMade"])
            self.assertFalse(draft["receiptWritesAllowed"])
            self.assertIn("finalSignoffText", draft["requiredSignoffFields"])
            rows = draft["signoffDraftTemplate"]["releaseTokenSignoffs"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["gateId"], "broker_order_send_release")
            self.assertFalse(rows[0]["acknowledgeNoSideEffectEvidence"])
            self.assertFalse(rows[0]["acknowledgeExecutionModeSeparatelyReviewed"])
            self.assertFalse(rows[0]["canSignOffHere"])
            self.assertFalse(rows[0]["canMintTokenHere"])
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", rows[0]["signoffQuestionZh"])
            self.assertTrue(release_token_signoff_draft_path(runtime).exists())
            hydrated = read_release_token_signoff_draft(runtime)
            self.assertEqual(hydrated["schema"], draft["schema"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_release_token_signoff_input_template_exports_blank_rows_without_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "combinedVerifiedUsdProfit": 137.22,
                "qualifyingLaneIds": ["forexMt5", "btcCryptoCfd"],
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "releaseTokens": [
                        {
                            "gateId": "broker_order_send_release",
                            "labelZh": "Broker OrderSend",
                            "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                            "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                            "sideEffectZh": "调用 MT5 OrderSend",
                            "sourceArtifact": "brokerOrderSendReview",
                            "dataPlaneReady": True,
                            "tokenProvided": False,
                        },
                    ],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneBrokerOrderSendReady": True,
                "brokerReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "requestFilesWritten": False,
                "receiptWritesAllowed": False,
            })
            build_release_token_evidence_review(runtime, write=True)
            build_release_token_signoff_draft(runtime, write=True)

            template = build_release_token_signoff_input_template(runtime, write=True)
            self.assertEqual(template["schema"], "quantgod.release_token_signoff_input_template.v1")
            self.assertEqual(template["status"], "READY_FOR_SIGNOFF_INPUT_FILL")
            self.assertEqual(template["releaseTokenCount"], 1)
            self.assertEqual(template["readyForInputCount"], 1)
            self.assertTrue(template["cannotBeUsedAsReleaseToken"])
            self.assertFalse(template["canAcceptSignoffHere"])
            self.assertFalse(template["canMintTokenHere"])
            self.assertFalse(template["canReleaseExecutionNow"])
            self.assertFalse(template["releaseTokenCanBeAutoMinted"])
            self.assertFalse(template["orderSendAllowed"])
            self.assertFalse(template["mt5OrderSendAllowed"])
            self.assertFalse(template["writesMt5OrderRequest"])
            self.assertFalse(template["brokerCallsMade"])
            rows = template["signoffInputTemplate"]["releaseTokenSignoffs"]
            self.assertEqual(rows[0]["gateId"], "broker_order_send_release")
            self.assertFalse(rows[0]["acknowledgeNoSideEffectEvidence"])
            self.assertFalse(rows[0]["acknowledgeRollback"])
            self.assertEqual(rows[0]["finalSignoffText"], "")
            self.assertIn("不要填写", template["forbiddenSecretFieldsZh"])
            self.assertTrue(release_token_signoff_input_template_path(runtime).exists())
            hydrated = read_release_token_signoff_input_template(runtime)
            self.assertEqual(hydrated["schema"], template["schema"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_release_token_signoff_input_review_validates_without_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "combinedVerifiedUsdProfit": 137.22,
                "qualifyingLaneIds": ["forexMt5", "btcCryptoCfd"],
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "releaseTokens": [
                        {
                            "gateId": "broker_order_send_release",
                            "labelZh": "Broker OrderSend",
                            "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                            "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                            "sideEffectZh": "调用 MT5 OrderSend",
                            "sourceArtifact": "brokerOrderSendReview",
                            "dataPlaneReady": True,
                            "tokenProvided": False,
                        },
                    ],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneBrokerOrderSendReady": True,
                "brokerReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "requestFilesWritten": False,
                "receiptWritesAllowed": False,
            })
            build_release_token_evidence_review(runtime, write=True)
            build_release_token_signoff_draft(runtime, write=True)
            signoff_json = json.dumps({
                "schema": "quantgod.release_token_signoff_input.v1",
                "operatorId": "operator-review-only",
                "reviewedAtIso": "2026-06-03T00:00:00Z",
                "releaseTokenSignoffs": [
                    {
                        "gateId": "broker_order_send_release",
                        "acknowledgeNoSideEffectEvidence": True,
                        "acknowledgeKillSwitch": True,
                        "acknowledgeRollback": True,
                        "acknowledgeRiskLimits": True,
                        "acknowledgeExecutionModeSeparatelyReviewed": True,
                        "finalSignoffText": (
                            "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1 "
                            "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING reviewed for separate release lane"
                        ),
                    },
                ],
            })

            review = build_release_token_signoff_input_review(runtime, signoff_json=signoff_json, write=True)
            self.assertEqual(review["schema"], "quantgod.release_token_signoff_input_review.v1")
            self.assertEqual(review["status"], "SIGNOFF_INPUT_READY_FOR_SEPARATE_RELEASE_REVIEW")
            self.assertEqual(review["completeSignoffCount"], 1)
            self.assertEqual(review["releaseTokenCount"], 1)
            self.assertEqual(review["forbiddenSecretFieldPaths"], [])
            self.assertFalse(review["canAcceptSignoffHere"])
            self.assertFalse(review["canMintTokenHere"])
            self.assertFalse(review["canReleaseExecutionNow"])
            self.assertFalse(review["releaseTokenCanBeAutoMinted"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])
            self.assertFalse(review["brokerCallsMade"])
            self.assertTrue(review["reviewRows"][0]["completeForSeparateReleaseReview"])
            self.assertEqual(review["reviewRows"][0]["status"], "SIGNOFF_INPUT_COMPLETE")
            self.assertTrue(release_token_signoff_input_review_path(runtime).exists())
            hydrated = read_release_token_signoff_input_review(runtime)
            self.assertEqual(hydrated["schema"], review["schema"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

            unsafe = build_release_token_signoff_input_review(
                runtime,
                signoff_json=json.dumps({
                    "releaseTokenSignoffs": [
                        {
                            "gateId": "broker_order_send_release",
                            "tokenValue": "do-not-store",
                        },
                    ],
                }),
            )
            self.assertIn("root.releaseTokenSignoffs[0].tokenValue", unsafe["forbiddenSecretFieldPaths"])
            self.assertEqual(unsafe["status"], "WAITING_SIGNOFF_INPUT")

    def test_release_token_signoff_handoff_summarizes_missing_and_complete_inputs_without_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(release_minimal_diff_review_path(runtime), {
                "ok": True,
                "schema": "quantgod.release_minimal_diff_review.v1",
                "status": "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
                "profitTargetReached": True,
                "combinedVerifiedUsdProfit": 137.22,
                "qualifyingLaneIds": ["forexMt5", "btcCryptoCfd"],
                "reviewPackage": {
                    "schema": "quantgod.release_minimal_diff_package.v1",
                    "releaseTokens": [
                        {
                            "gateId": "broker_order_send_release",
                            "labelZh": "Broker OrderSend",
                            "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                            "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                            "sideEffectZh": "调用 MT5 OrderSend",
                            "sourceArtifact": "brokerOrderSendReview",
                            "dataPlaneReady": True,
                            "tokenProvided": False,
                        },
                    ],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(broker_order_send_review_path(runtime), {
                "schema": "quantgod.broker_order_send_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneBrokerOrderSendReady": True,
                "brokerReleaseGate": {
                    "tokenRequired": True,
                    "tokenProvided": False,
                    "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "brokerCallsMade": False,
                "requestFilesWritten": False,
                "receiptWritesAllowed": False,
            })
            build_release_token_evidence_review(runtime, write=True)
            build_release_token_signoff_draft(runtime, write=True)
            build_release_token_signoff_input_template(runtime, write=True)
            build_release_token_signoff_input_review(runtime, write=True)

            waiting = build_release_token_signoff_handoff(runtime, write=True)
            self.assertEqual(waiting["schema"], "quantgod.release_token_signoff_handoff.v1")
            self.assertEqual(waiting["status"], "WAITING_SIGNOFF_INPUT_HANDOFF")
            self.assertEqual(waiting["releaseTokenCount"], 1)
            self.assertEqual(waiting["readyForInputCount"], 1)
            self.assertEqual(waiting["completeSignoffCount"], 0)
            self.assertEqual(waiting["missingSignoffCount"], 1)
            self.assertEqual(waiting["missingSignoffRows"][0]["gateId"], "broker_order_send_release")
            self.assertFalse(waiting["canReleaseExecutionNow"])
            self.assertFalse(waiting["orderSendAllowed"])
            self.assertFalse(waiting["mt5OrderSendAllowed"])
            self.assertFalse(waiting["writesMt5OrderRequest"])
            self.assertFalse(waiting["brokerCallsMade"])
            self.assertIn("不要提交", waiting["handoffInstructions"][1])

            build_release_token_signoff_input_review(
                runtime,
                signoff_json=json.dumps({
                    "schema": "quantgod.release_token_signoff_input.v1",
                    "operatorId": "operator-review-only",
                    "reviewedAtIso": "2026-06-03T00:00:00Z",
                    "releaseTokenSignoffs": [
                        {
                            "gateId": "broker_order_send_release",
                            "acknowledgeNoSideEffectEvidence": True,
                            "acknowledgeKillSwitch": True,
                            "acknowledgeRollback": True,
                            "acknowledgeRiskLimits": True,
                            "acknowledgeExecutionModeSeparatelyReviewed": True,
                            "finalSignoffText": (
                                "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1 "
                                "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING reviewed for separate release lane"
                            ),
                        },
                    ],
                }),
                write=True,
            )
            complete = build_release_token_signoff_handoff(runtime, write=True)
            self.assertEqual(complete["status"], "SIGNOFF_HANDOFF_READY_FOR_SEPARATE_RELEASE_LANE")
            self.assertEqual(complete["completeSignoffCount"], 1)
            self.assertEqual(complete["missingSignoffCount"], 0)
            self.assertEqual(complete["missingSignoffRows"], [])
            self.assertFalse(complete["canReleaseExecutionNow"])
            self.assertFalse(complete["canProceedToLiveExecutionHere"])
            self.assertFalse(complete["orderSendAllowed"])
            self.assertFalse(complete["mt5OrderSendAllowed"])
            self.assertFalse(complete["writesMt5OrderRequest"])
            self.assertFalse(complete["brokerCallsMade"])
            self.assertTrue(release_token_signoff_handoff_path(runtime).exists())
            hydrated = read_release_token_signoff_handoff(runtime)
            self.assertEqual(hydrated["schema"], complete["schema"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_runtime_handoff_reports_portfolio_full_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "_file": {"mtimeIso": "2026-06-03T03:17:11Z"},
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                    "pilotKillSwitch": False,
                    "tradePermissionBlocker": "",
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.81,
                    "equity": 10222.70,
                    "profit": -0.11,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.871, "ask": 159.895, "spread": 2.4},
                "openTrades": [
                    {
                        "ticket": 697738560,
                        "positionId": 697738560,
                        "type": "BUY",
                        "symbol": "USDJPYc",
                        "lots": 0.01,
                        "openPrice": 159.874,
                        "sl": 159.762,
                        "tp": 160.04,
                        "profit": -0.02,
                        "strategy": "RSI_Reversal",
                        "source": "EA",
                    },
                    {
                        "ticket": 697870941,
                        "positionId": 697870941,
                        "type": "BUY",
                        "symbol": "USDJPYc",
                        "lots": 0.01,
                        "openPrice": 159.886,
                        "sl": 159.776,
                        "tp": 160.052,
                        "profit": -0.09,
                        "strategy": "RSI_Reversal",
                        "source": "EA",
                    },
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "schema": "quantgod.mt5.usdjpy_rsi_entry_diagnostics.v1",
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "state": "PORTFOLIO_FULL",
                    "stateZh": "EA 仓位容量已满",
                    "summary": "EA 已达到自动仓位上限，等待释放容量。",
                    "whyNoEntry": [{"code": "PORTFOLIO_FULL", "label": "EA 总仓位已满", "detail": "2/2"}],
                    "guards": {"portfolioPositions": 2, "maxTotalPositions": 2, "spreadAllowed": True},
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })

            with mock.patch(
                "tools.live_automation_readiness.forex_live12_runtime_handoff._process_evidence",
                return_value={
                    "mode": "READ_ONLY_PROCESS_SCAN",
                    "mainMt5TerminalRunning": True,
                    "isolatedTesterTerminalRunning": False,
                    "dashboardServerRunning": True,
                    "blockers": [],
                },
            ):
                handoff = build_forex_live12_runtime_handoff(
                    runtime,
                    primary_dashboard_json=str(primary_dashboard),
                    write=True,
                )
            self.assertEqual(handoff["schema"], "quantgod.forex_live12_runtime_handoff.v1")
            self.assertEqual(handoff["status"], "FOREX_LIVE12_ACTIVE_PORTFOLIO_FULL")
            self.assertEqual(handoff["artifactFreshness"]["mode"], "SOURCE_DASHBOARD_MTIME_WATCH")
            self.assertEqual(handoff["runtimeFreshness"]["mode"], "LIVE12_DASHBOARD_AND_PROCESS_WATCH")
            self.assertTrue(handoff["runtimeFreshness"]["fresh"])
            self.assertEqual(handoff["runtimeFreshness"]["blockers"], [])
            self.assertFalse(handoff["artifactFreshness"]["staleSourceDetected"])
            self.assertTrue(handoff["runtimeSwitches"]["hardSwitchesActive"])
            self.assertTrue(handoff["positionSummary"]["portfolioFull"])
            self.assertEqual(handoff["positionSummary"]["openPositionCount"], 2)
            self.assertEqual(handoff["positionSummary"]["maxTotalTrades"], 2)
            self.assertEqual(handoff["positionSummary"]["floatingProfit"], -0.11)
            self.assertEqual(handoff["capacityReleaseWatch"]["mode"], "READ_ONLY_CAPACITY_RELEASE_WATCH")
            self.assertEqual(handoff["capacityReleaseWatch"]["capacityUsed"], 2)
            self.assertEqual(handoff["capacityReleaseWatch"]["capacityLimit"], 2)
            self.assertEqual(handoff["capacityReleaseWatch"]["nearestTpPips"], 16.9)
            self.assertEqual(handoff["capacityReleaseWatch"]["nearestSlPips"], 9.5)
            self.assertEqual(handoff["capacityReleaseWatch"]["watchedPositions"][0]["distanceToTpPips"], 16.9)
            self.assertEqual(handoff["capacityReleaseWatch"]["watchedPositions"][1]["distanceToSlPips"], 9.5)
            self.assertIn("2/2 已占用", handoff["capacityReleaseWatch"]["capacityLineZh"])
            self.assertFalse(handoff["capacityReleaseWatch"]["orderSendAllowed"])
            self.assertFalse(handoff["capacityReleaseWatch"]["closeAllowed"])
            self.assertFalse(handoff["capacityReleaseWatch"]["modifyAllowed"])
            self.assertFalse(handoff["capacityReleaseWatch"]["writesMt5OrderRequest"])
            self.assertFalse(handoff["canAddPositionHere"])
            self.assertFalse(handoff["canClosePositionHere"])
            self.assertFalse(handoff["canModifyPositionHere"])
            self.assertFalse(handoff["orderSendAllowed"])
            self.assertFalse(handoff["mt5OrderSendAllowed"])
            self.assertFalse(handoff["closeAllowed"])
            self.assertFalse(handoff["writesMt5OrderRequest"])
            self.assertFalse(handoff["brokerCallsMade"])
            self.assertTrue(forex_live12_runtime_handoff_path(runtime).exists())
            hydrated = read_forex_live12_runtime_handoff(runtime)
            self.assertEqual(hydrated["schema"], handoff["schema"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_runtime_handoff_blocks_stale_dashboard_and_missing_mt5_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.81,
                    "equity": 10222.70,
                    "profit": 0,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.871, "ask": 159.895, "spread": 2.4},
                "openTrades": [],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY_BUY_SIGNAL",
                    "stateZh": "RSI 买入信号已触发，等待 EA 守门执行",
                    "summary": "旧 dashboard 不应被当成可执行新鲜信号。",
                    "whyNoEntry": [{"code": "BUY_SIGNAL_READY", "label": "买入信号已触发"}],
                    "guards": {"portfolioPositions": 0, "maxTotalPositions": 2, "spreadAllowed": True},
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })
            stale_time = time.time() - 3600
            os.utime(primary_dashboard, (stale_time, stale_time))

            with mock.patch(
                "tools.live_automation_readiness.forex_live12_runtime_handoff._process_evidence",
                return_value={
                    "mode": "READ_ONLY_PROCESS_SCAN",
                    "mainMt5TerminalRunning": False,
                    "isolatedTesterTerminalRunning": False,
                    "dashboardServerRunning": True,
                    "blockers": ["mt5_terminal_process_missing"],
                },
            ):
                handoff = build_forex_live12_runtime_handoff(
                    runtime,
                    primary_dashboard_json=str(primary_dashboard),
                    write=True,
                )

            self.assertEqual(handoff["status"], "FOREX_LIVE12_RUNTIME_REFRESH_BLOCKED")
            self.assertFalse(handoff["runtimeFreshness"]["fresh"])
            self.assertFalse(handoff["runtimeFreshness"]["dashboardFresh"])
            self.assertIn("live_dashboard_snapshot_stale", handoff["runtimeFreshness"]["blockers"])
            self.assertIn("mt5_terminal_process_missing", handoff["runtimeFreshness"]["blockers"])
            self.assertIn("运行时刷新阻塞", handoff["statusZh"])
            self.assertIn("恢复 MT5/EA 持续刷新", handoff["nextRequiredActionZh"])
            self.assertFalse(handoff["orderSendAllowed"])
            self.assertFalse(handoff["mt5OrderSendAllowed"])
            self.assertFalse(handoff["writesMt5OrderRequest"])
            self.assertFalse(handoff["brokerCallsMade"])

    def test_forex_live12_runtime_handoff_rebuilds_read_when_dashboard_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            base_dashboard = {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.81,
                    "equity": 10222.70,
                    "profit": -0.11,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.871, "ask": 159.895, "spread": 2.4},
                "openTrades": [
                    {"ticket": 1, "positionId": 1, "type": "BUY", "symbol": "USDJPYc", "lots": 0.01, "tp": 160.04, "sl": 159.762},
                    {"ticket": 2, "positionId": 2, "type": "BUY", "symbol": "USDJPYc", "lots": 0.01, "tp": 160.052, "sl": 159.776},
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "PORTFOLIO_FULL",
                    "stateZh": "EA 仓位容量已满",
                    "summary": "EA 已达到自动仓位上限，等待释放容量。",
                    "whyNoEntry": [{"code": "PORTFOLIO_FULL", "label": "EA 总仓位已满", "detail": "2/2"}],
                    "guards": {"portfolioPositions": 2, "maxTotalPositions": 2, "spreadAllowed": True},
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            }
            self._write_json(primary_dashboard, base_dashboard)
            process_ready = {
                "mode": "READ_ONLY_PROCESS_SCAN",
                "mainMt5TerminalRunning": True,
                "isolatedTesterTerminalRunning": False,
                "dashboardServerRunning": True,
                "blockers": [],
            }
            with mock.patch(
                "tools.live_automation_readiness.forex_live12_runtime_handoff._process_evidence",
                return_value=process_ready,
            ):
                first = build_forex_live12_runtime_handoff(runtime, primary_dashboard_json=str(primary_dashboard), write=True)
            self.assertEqual(first["positionSummary"]["openPositionCount"], 2)

            newer_dashboard = dict(base_dashboard)
            newer_dashboard["openTrades"] = [base_dashboard["openTrades"][1]]
            newer_dashboard["usdJpyRsiEntryDiagnostics"] = {
                **base_dashboard["usdJpyRsiEntryDiagnostics"],
                "state": "READY_BUY_SIGNAL",
                "stateZh": "RSI 买入信号已触发，等待 EA 守门执行",
                "whyNoEntry": [{"code": "BUY_SIGNAL_READY", "label": "买入信号已触发"}],
                "guards": {"portfolioPositions": 1, "maxTotalPositions": 2, "spreadAllowed": True},
            }
            self._write_json(primary_dashboard, newer_dashboard)
            artifact_path = forex_live12_runtime_handoff_path(runtime)
            now = time.time()
            os.utime(artifact_path, (now - 10, now - 10))
            os.utime(primary_dashboard, (now, now))

            with mock.patch(
                "tools.live_automation_readiness.forex_live12_runtime_handoff._process_evidence",
                return_value=process_ready,
            ):
                hydrated = read_forex_live12_runtime_handoff(runtime)
            self.assertEqual(hydrated["positionSummary"]["openPositionCount"], 1)
            self.assertEqual(hydrated["status"], "FOREX_LIVE12_ACTIVE_WAITING_EA_GUARDS")
            self.assertTrue(hydrated["artifactFreshness"]["staleSourceDetected"])
            self.assertTrue(hydrated["artifactFreshness"]["autoRebuiltForRead"])
            self.assertFalse(hydrated["orderSendAllowed"])
            self.assertFalse(hydrated["writesMt5OrderRequest"])

    def test_forex_live12_runtime_handoff_auto_discovers_global_mt5_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "repo_runtime"
            mt5_files = Path(tmp) / "mt5_files"
            primary_dashboard = mt5_files / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                    "pilotKillSwitch": False,
                    "tradePermissionBlocker": "",
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.81,
                    "equity": 10222.70,
                    "profit": 0.0,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.871, "ask": 159.895, "spread": 2.4},
                "openTrades": [],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY",
                    "stateZh": "等待 EA 守门自然通过",
                    "summary": "Live12 dashboard 已同步。",
                    "guards": {"portfolioPositions": 0, "maxTotalPositions": 2, "spreadAllowed": True},
                    "rsi": {"signalReady": False, "signalDirection": "NONE", "signalScore": 0},
                },
            })
            with mock.patch(
                "tools.live_automation_readiness.forex_live12_runtime_handoff.runtime_dir_candidates",
                return_value=[mt5_files],
            ):
                with mock.patch(
                    "tools.live_automation_readiness.forex_live12_runtime_handoff._process_evidence",
                    return_value={
                        "mode": "READ_ONLY_PROCESS_SCAN",
                        "mainMt5TerminalRunning": True,
                        "isolatedTesterTerminalRunning": False,
                        "dashboardServerRunning": True,
                        "blockers": [],
                    },
                ):
                    with mock.patch.dict(os.environ, {"QG_LIVE_PREFLIGHT_INCLUDE_GLOBAL_MT5": "1"}):
                        handoff = build_forex_live12_runtime_handoff(runtime, write=True)

            self.assertEqual(handoff["sourceDashboardPath"], str(primary_dashboard))
            self.assertEqual(handoff["status"], "FOREX_LIVE12_ACTIVE_WAITING_EA_GUARDS")
            self.assertEqual(handoff["account"]["number"], 186054398)
            self.assertTrue(handoff["runtimeSwitches"]["hardSwitchesActive"])
            self.assertIn(str(primary_dashboard), handoff["artifactFreshness"]["checkedDashboardPaths"])
            self.assertFalse(handoff["orderSendAllowed"])
            self.assertFalse(handoff["writesMt5OrderRequest"])

    def test_readiness_includes_live12_runtime_handoff_without_execution_rights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "repo_runtime"
            mt5_files = Path(tmp) / "mt5_files"
            self._write_json(mt5_files / "QuantGod_Dashboard.json", {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10220.99,
                    "equity": 10220.99,
                    "profit": 0.0,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.948, "ask": 159.975, "spread": 2.7},
                "openTrades": [],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "WAITING_RSI_SIGNAL",
                    "stateZh": "RSI 买入路线已恢复，等待 H1 信号",
                    "guards": {"portfolioPositions": 0, "maxTotalPositions": 2, "spreadAllowed": True},
                    "rsi": {"signalReady": False, "signalDirection": "NONE", "signalScore": 50},
                },
            })

            with mock.patch(
                "tools.live_automation_readiness.forex_live12_runtime_handoff.runtime_dir_candidates",
                return_value=[mt5_files],
            ):
                with mock.patch(
                    "tools.live_automation_readiness.forex_live12_runtime_handoff._process_evidence",
                    return_value={
                        "mode": "READ_ONLY_PROCESS_SCAN",
                        "mainMt5TerminalRunning": True,
                        "isolatedTesterTerminalRunning": False,
                        "dashboardServerRunning": True,
                        "blockers": [],
                    },
                ):
                    with mock.patch.dict(os.environ, {"QG_LIVE_PREFLIGHT_INCLUDE_GLOBAL_MT5": "1"}):
                        payload = build_live_automation_readiness(runtime, write=False)

            usdjpy = payload["lanes"]["usdjpyMt5"]
            handoff = usdjpy["live12RuntimeHandoff"]
            self.assertTrue(usdjpy["sourceStatus"]["live12RuntimeHandoffReadable"])
            self.assertTrue(usdjpy["sourceStatus"]["live12RuntimeHandoffOk"])
            self.assertTrue(usdjpy["sourceStatus"]["live12RuntimeHandoffFresh"])
            self.assertEqual(handoff["account"]["number"], 186054398)
            self.assertTrue(handoff["runtimeFresh"])
            self.assertTrue(handoff["runtimeSwitches"]["hardSwitchesActive"])
            self.assertEqual(handoff["positionSummary"]["openPositionCount"], 0)
            self.assertEqual(handoff["noEntryState"], "WAITING_RSI_SIGNAL")
            self.assertFalse(usdjpy["executionReady"])
            self.assertFalse(handoff["orderSendAllowed"])
            self.assertFalse(handoff["writesMt5OrderRequest"])
            self.assertFalse(payload["canPromoteToLiveNow"])

    def test_readiness_marks_readable_but_stale_live12_handoff_not_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "repo_runtime"
            mt5_files = Path(tmp) / "mt5_files"
            dashboard = mt5_files / "QuantGod_Dashboard.json"
            self._write_json(dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10220.99,
                    "equity": 10220.99,
                    "profit": 0.0,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.948, "ask": 159.975, "spread": 2.7},
                "openTrades": [],
            })
            stale_mtime = time.time() - 7200
            os.utime(dashboard, (stale_mtime, stale_mtime))

            with mock.patch(
                "tools.live_automation_readiness.forex_live12_runtime_handoff.runtime_dir_candidates",
                return_value=[mt5_files],
            ):
                with mock.patch(
                    "tools.live_automation_readiness.forex_live12_runtime_handoff._process_evidence",
                    return_value={
                        "mode": "READ_ONLY_PROCESS_SCAN",
                        "mainMt5TerminalRunning": False,
                        "isolatedTesterTerminalRunning": False,
                        "dashboardServerRunning": True,
                        "blockers": ["mt5_terminal_process_missing"],
                    },
                ):
                    with mock.patch.dict(os.environ, {"QG_LIVE_PREFLIGHT_INCLUDE_GLOBAL_MT5": "1"}):
                        payload = build_live_automation_readiness(runtime, write=False)

            usdjpy = payload["lanes"]["usdjpyMt5"]
            source_status = usdjpy["sourceStatus"]
            self.assertTrue(source_status["live12RuntimeHandoffReadable"])
            self.assertFalse(source_status["live12RuntimeHandoffOk"])
            self.assertFalse(source_status["live12RuntimeHandoffFresh"])
            self.assertEqual(source_status["live12RuntimeHandoffStatus"], "FOREX_LIVE12_RUNTIME_REFRESH_BLOCKED")
            self.assertIn("live_dashboard_snapshot_stale", source_status["live12RuntimeHandoffBlockers"])
            self.assertIn("mt5_terminal_process_missing", source_status["live12RuntimeHandoffBlockers"])
            handoff = usdjpy["live12RuntimeHandoff"]
            self.assertFalse(handoff["runtimeFresh"])
            self.assertIn("live_dashboard_snapshot_stale", handoff["runtimeFreshnessBlockers"])
            self.assertIn("LIVE12_RUNTIME_REFRESH_BLOCKED", {row["code"] for row in usdjpy["reviewBlockers"]})
            self.assertFalse(usdjpy["executionReady"])
            self.assertFalse(usdjpy["safety"]["orderSendAllowed"])
            self.assertFalse(payload["canPromoteToLiveNow"])

    def test_forex_live12_capacity_expansion_review_records_request_without_mutating_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.86,
                    "profit": -0.01,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.885, "ask": 159.910, "spread": 2.5},
                "openTrades": [
                    {"ticket": 697870941, "positionId": 697870941, "type": "BUY", "symbol": "USDJPYc", "lots": 0.01, "tp": 160.052, "sl": 159.776}
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY_BUY_SIGNAL",
                    "stateZh": "RSI 买入信号已触发，等待 EA 守门执行",
                    "summary": "RSI 买入信号已触发；EA 守门通过后可按自身逻辑入场。",
                    "whyNoEntry": [{"code": "BUY_SIGNAL_READY", "label": "买入信号已触发"}],
                    "guards": {"portfolioPositions": 1, "maxTotalPositions": 2, "spreadAllowed": True},
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })

            review = build_forex_live12_capacity_expansion_review(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(review["schema"], "quantgod.forex_live12_capacity_expansion_review.v1")
            self.assertEqual(review["request"]["requestedMaxTotalTrades"], 10)
            self.assertEqual(review["request"]["currentMaxTotalTrades"], 2)
            self.assertEqual(review["request"]["openPositionCount"], 1)
            self.assertFalse(review["decision"]["canApplyHere"])
            self.assertFalse(review["decision"]["writesMt5Preset"])
            self.assertFalse(review["decision"]["livePresetMutationAllowed"])
            self.assertFalse(review["decision"]["orderSendAllowed"])
            self.assertFalse(review["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(review["decision"]["requestFilesWritten"])
            self.assertFalse(review["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_capacity_expansion_review_path(runtime).exists())
            hydrated = read_forex_live12_capacity_expansion_review(runtime)
            self.assertEqual(hydrated["request"]["requestedMaxTotalTrades"], 10)
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_capacity_expansion_roadmap_stages_to_ten_without_live_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.86,
                    "profit": -0.01,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.884, "ask": 159.913, "spread": 2.9},
                "openTrades": [
                    {"ticket": 697870941, "positionId": 697870941, "type": "BUY", "symbol": "USDJPYc", "lots": 0.01, "tp": 160.052, "sl": 159.776}
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY_BUY_SIGNAL",
                    "stateZh": "RSI 买入信号已触发，等待 EA 守门执行",
                    "summary": "RSI 买入信号已触发；EA 守门通过后可按自身逻辑入场。",
                    "whyNoEntry": [{"code": "BUY_SIGNAL_READY", "label": "买入信号已触发"}],
                    "guards": {
                        "portfolioPositions": 1,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "SOFT_WIDE_HIGH",
                        "spreadPips": 2.9,
                    },
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })

            roadmap = build_forex_live12_capacity_expansion_roadmap(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(roadmap["schema"], "quantgod.forex_live12_capacity_expansion_roadmap.v1")
            self.assertEqual(roadmap["status"], "ROADMAP_WAITING_SPREAD_NORMALIZATION")
            self.assertEqual(roadmap["request"]["currentMaxTotalTrades"], 2)
            self.assertEqual(roadmap["request"]["requestedMaxTotalTrades"], 10)
            self.assertEqual(roadmap["nextPhase"]["toMaxTotalTrades"], 3)
            self.assertEqual(roadmap["decision"]["nextRecommendedMaxTotalTrades"], 2)
            self.assertFalse(roadmap["decision"]["canApplyHere"])
            self.assertFalse(roadmap["decision"]["canWritePresetHere"])
            self.assertFalse(roadmap["decision"]["writesMt5Preset"])
            self.assertFalse(roadmap["decision"]["orderSendAllowed"])
            self.assertFalse(roadmap["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(roadmap["decision"]["writesMt5OrderRequest"])
            self.assertFalse(roadmap["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_capacity_expansion_roadmap_path(runtime).exists())
            hydrated = read_forex_live12_capacity_expansion_roadmap(runtime)
            self.assertEqual(hydrated["request"]["requestedMaxTotalTrades"], 10)
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_micro_expansion_review_requires_samples_and_no_open_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.80,
                    "profit": -0.07,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.875, "ask": 159.897, "spread": 2.2},
                "openTrades": [
                    {
                        "ticket": 697870941,
                        "positionId": 697870941,
                        "type": "BUY",
                        "symbol": "USDJPYc",
                        "lots": 0.01,
                        "tp": 160.052,
                        "sl": 159.776,
                        "profit": -0.07,
                    }
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY_BUY_SIGNAL",
                    "stateZh": "RSI 买入信号已触发，等待 EA 守门执行",
                    "summary": "RSI 买入信号已触发；EA 守门通过后可按自身逻辑入场。",
                    "whyNoEntry": [{"code": "BUY_SIGNAL_READY", "label": "买入信号已触发"}],
                    "guards": {
                        "portfolioPositions": 1,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.2,
                    },
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })
            close_history = primary_dashboard.parent / "QuantGod_CloseHistory.csv"
            close_history.write_text(
                "\n".join([
                    "ExitTicket,PositionId,Type,Symbol,Lots,OpenTime,CloseTime,DurationMinutes,OpenPrice,ClosePrice,GrossProfit,Commission,Swap,NetProfit,Strategy,Source,EntryRegime,ExitRegime,RegimeTimeframe,Comment",
                    '1,11,"BUY","USDJPYc",0.01,"2026.06.03 05:00","2026.06.03 06:31",91,159.874,159.884,0.06,0.00,0.00,0.06,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '2,12,"BUY","USDJPYc",0.01,"2026.05.28 14:00","2026.05.28 15:30",89,159.473,159.332,-0.88,0.00,0.00,-0.88,"RSI_Reversal","EA","RANGE","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '3,13,"BUY","USDJPYc",0.01,"2026.05.28 13:00","2026.05.28 14:30",90,159.429,159.445,0.10,0.00,0.00,0.10,"RSI_Reversal","EA","TREND_DOWN","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                ]),
                encoding="utf-8",
            )

            review = build_forex_live12_micro_expansion_review(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(review["schema"], "quantgod.forex_live12_micro_expansion_review.v1")
            self.assertEqual(review["status"], "MICRO_EXPANSION_WAITING_EVIDENCE")
            self.assertEqual(review["phase"]["fromMaxTotalTrades"], 2)
            self.assertEqual(review["phase"]["toMaxTotalTrades"], 3)
            self.assertEqual(review["evidence"]["metrics"]["naturalClosedTrades"], 3)
            blocker_codes = {row["code"] for row in review["blockers"]}
            self.assertIn("MICRO_CLOSED_TRADES_LT_MIN", blocker_codes)
            self.assertIn("MICRO_OPEN_FLOATING_LOSS_ACTIVE", blocker_codes)
            self.assertFalse(review["decision"]["microReviewPassed"])
            self.assertEqual(review["decision"]["nextRecommendedMaxTotalTrades"], 2)
            self.assertFalse(review["decision"]["canApplyHere"])
            self.assertFalse(review["decision"]["canWritePresetHere"])
            self.assertFalse(review["decision"]["writesMt5Preset"])
            self.assertFalse(review["decision"]["orderSendAllowed"])
            self.assertFalse(review["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(review["decision"]["writesMt5OrderRequest"])
            self.assertFalse(review["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_micro_expansion_review_path(runtime).exists())
            hydrated = read_forex_live12_micro_expansion_review(runtime)
            self.assertEqual(hydrated["evidence"]["metrics"]["naturalClosedTrades"], 3)
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_rsi_repair_plan_targets_loss_streak_without_live_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.80,
                    "profit": -0.07,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.875, "ask": 159.897, "spread": 2.2},
                "openTrades": [
                    {
                        "ticket": 697870941,
                        "positionId": 697870941,
                        "type": "BUY",
                        "symbol": "USDJPYc",
                        "lots": 0.01,
                        "tp": 160.052,
                        "sl": 159.776,
                        "profit": -0.07,
                    }
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY_BUY_SIGNAL",
                    "stateZh": "RSI 买入信号已触发，等待 EA 守门执行",
                    "summary": "RSI 买入信号已触发；EA 守门通过后可按自身逻辑入场。",
                    "whyNoEntry": [{"code": "BUY_SIGNAL_READY", "label": "买入信号已触发"}],
                    "guards": {
                        "portfolioPositions": 1,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.2,
                    },
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })
            close_history = primary_dashboard.parent / "QuantGod_CloseHistory.csv"
            close_history.write_text(
                "\n".join([
                    "ExitTicket,PositionId,Type,Symbol,Lots,OpenTime,CloseTime,DurationMinutes,OpenPrice,ClosePrice,GrossProfit,Commission,Swap,NetProfit,Strategy,Source,EntryRegime,ExitRegime,RegimeTimeframe,Comment",
                    '1,11,"BUY","USDJPYc",0.01,"2026.06.03 05:00","2026.06.03 06:31",91,159.874,159.884,0.06,0.00,0.00,0.06,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '2,12,"BUY","USDJPYc",0.01,"2026.05.28 14:00","2026.05.28 15:30",89,159.473,159.332,-0.88,0.00,0.00,-0.88,"RSI_Reversal","EA","RANGE","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '3,13,"BUY","USDJPYc",0.01,"2026.05.28 12:00","2026.05.28 13:30",90,159.473,159.385,-0.55,0.00,0.00,-0.55,"RSI_Reversal","EA","TREND_DOWN","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '4,14,"BUY","USDJPYc",0.01,"2026.05.11 11:00","2026.05.11 11:37",37,157.144,156.936,-1.33,0.00,0.00,-1.33,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '5,15,"BUY","USDJPYc",0.01,"2026.05.28 13:00","2026.05.28 14:30",90,159.429,159.445,0.10,0.00,0.00,0.10,"RSI_Reversal","EA","TREND_DOWN","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                ]),
                encoding="utf-8",
            )

            plan = build_forex_live12_rsi_repair_plan(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(plan["schema"], "quantgod.forex_live12_rsi_repair_plan.v1")
            self.assertEqual(plan["status"], "RSI_REPAIR_RECOMMENDED")
            self.assertEqual(plan["request"]["requestedMaxTotalTrades"], 10)
            self.assertEqual(plan["decision"]["nextRecommendedMaxTotalTrades"], 2)
            action_codes = {row["code"] for row in plan["repairActions"]}
            self.assertIn("RSI_ADD_CONSECUTIVE_LOSS_COOLDOWN", action_codes)
            self.assertIn("RSI_BLOCK_EXPANSION_WHILE_FLOATING_LOSS", action_codes)
            self.assertIn("RSI_REQUIRE_PROFIT_FACTOR_RECOVERY", action_codes)
            self.assertGreaterEqual(len(plan["evidence"]["lossClusters"]), 1)
            self.assertFalse(plan["decision"]["canApplyHere"])
            self.assertFalse(plan["decision"]["canWritePresetHere"])
            self.assertFalse(plan["decision"]["writesMt5Preset"])
            self.assertFalse(plan["decision"]["orderSendAllowed"])
            self.assertFalse(plan["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(plan["decision"]["writesMt5OrderRequest"])
            self.assertFalse(plan["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_rsi_repair_plan_path(runtime).exists())
            hydrated = read_forex_live12_rsi_repair_plan(runtime)
            self.assertEqual(hydrated["status"], "RSI_REPAIR_RECOMMENDED")
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_rsi_shadow_candidate_filters_risky_history_without_live_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.80,
                    "profit": -0.07,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.875, "ask": 159.897, "spread": 2.2},
                "openTrades": [
                    {
                        "ticket": 697870941,
                        "positionId": 697870941,
                        "type": "BUY",
                        "symbol": "USDJPYc",
                        "lots": 0.01,
                        "tp": 160.052,
                        "sl": 159.776,
                        "profit": -0.07,
                    }
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY_BUY_SIGNAL",
                    "stateZh": "RSI 买入信号已触发，等待 EA 守门执行",
                    "summary": "RSI 买入信号已触发；EA 守门通过后可按自身逻辑入场。",
                    "whyNoEntry": [{"code": "BUY_SIGNAL_READY", "label": "买入信号已触发"}],
                    "guards": {
                        "portfolioPositions": 1,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.2,
                    },
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })
            close_history = primary_dashboard.parent / "QuantGod_CloseHistory.csv"
            close_history.write_text(
                "\n".join([
                    "ExitTicket,PositionId,Type,Symbol,Lots,OpenTime,CloseTime,DurationMinutes,OpenPrice,ClosePrice,GrossProfit,Commission,Swap,NetProfit,Strategy,Source,EntryRegime,ExitRegime,RegimeTimeframe,Comment",
                    '1,11,"BUY","USDJPYc",0.01,"2026.06.03 05:00","2026.06.03 06:31",91,159.874,159.884,0.06,0.00,0.00,0.06,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '2,12,"BUY","USDJPYc",0.01,"2026.05.28 14:00","2026.05.28 15:30",89,159.473,159.332,-0.88,0.00,0.00,-0.88,"RSI_Reversal","EA","RANGE","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '3,13,"BUY","USDJPYc",0.01,"2026.05.28 12:00","2026.05.28 13:30",90,159.473,159.385,-0.55,0.00,0.00,-0.55,"RSI_Reversal","EA","TREND_DOWN","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '4,14,"BUY","USDJPYc",0.01,"2026.05.11 11:00","2026.05.11 11:37",37,157.144,156.936,-1.33,0.00,0.00,-1.33,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '5,15,"BUY","USDJPYc",0.01,"2026.05.28 13:00","2026.05.28 14:30",90,159.429,159.445,0.10,0.00,0.00,0.10,"RSI_Reversal","EA","TREND_DOWN","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                ]),
                encoding="utf-8",
            )

            candidate = build_forex_live12_rsi_shadow_candidate(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(candidate["schema"], "quantgod.forex_live12_rsi_shadow_candidate.v1")
            self.assertEqual(candidate["candidate"]["lane"], "FAST_SHADOW")
            self.assertEqual(candidate["candidate"]["targetMaxTotalTrades"], 10)
            self.assertEqual(candidate["candidate"]["stageMaxTotalTrades"], 2)
            self.assertGreaterEqual(candidate["proxyReplay"]["blockedTradeCount"], 2)
            self.assertLessEqual(candidate["proxyReplay"]["afterMetrics"]["maxConsecutiveLosses"], 2)
            self.assertFalse(candidate["decision"]["canApplyHere"])
            self.assertFalse(candidate["decision"]["canWritePresetHere"])
            self.assertFalse(candidate["decision"]["canPromoteToLiveHere"])
            self.assertFalse(candidate["decision"]["writesMt5Preset"])
            self.assertFalse(candidate["decision"]["orderSendAllowed"])
            self.assertFalse(candidate["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(candidate["decision"]["writesMt5OrderRequest"])
            self.assertFalse(candidate["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_rsi_shadow_candidate_path(runtime).exists())
            hydrated = read_forex_live12_rsi_shadow_candidate(runtime)
            self.assertEqual(hydrated["candidate"]["id"], "forex-live12-rsi-loss-cooldown-v1")
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_rsi_tester_request_is_paramlab_config_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.80,
                    "profit": -0.07,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.875, "ask": 159.897, "spread": 2.2},
                "openTrades": [
                    {
                        "ticket": 697870941,
                        "positionId": 697870941,
                        "type": "BUY",
                        "symbol": "USDJPYc",
                        "lots": 0.01,
                        "profit": -0.07,
                    }
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY_BUY_SIGNAL",
                    "guards": {
                        "portfolioPositions": 1,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.2,
                    },
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })
            close_history = primary_dashboard.parent / "QuantGod_CloseHistory.csv"
            close_history.write_text(
                "\n".join([
                    "ExitTicket,PositionId,Type,Symbol,Lots,OpenTime,CloseTime,DurationMinutes,OpenPrice,ClosePrice,GrossProfit,Commission,Swap,NetProfit,Strategy,Source,EntryRegime,ExitRegime,RegimeTimeframe,Comment",
                    '1,11,"BUY","USDJPYc",0.01,"2026.06.03 05:00","2026.06.03 06:31",91,159.874,159.884,0.06,0.00,0.00,0.06,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '2,12,"BUY","USDJPYc",0.01,"2026.05.28 14:00","2026.05.28 15:30",89,159.473,159.332,-0.88,0.00,0.00,-0.88,"RSI_Reversal","EA","RANGE","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                ]),
                encoding="utf-8",
            )

            request = build_forex_live12_rsi_tester_request(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(request["schema"], "quantgod.forex_live12_rsi_tester_request.v1")
            self.assertEqual(request["mode"], "PARAM_LAB_COMPATIBLE_CONFIG_ONLY_REQUEST")
            self.assertTrue(request["summary"]["configOnly"])
            self.assertTrue(request["summary"]["testerOnly"])
            self.assertFalse(request["summary"]["runTerminal"])
            self.assertFalse(request["summary"]["livePresetMutation"])
            self.assertEqual(len(request["backtestTasks"]), 1)
            task = request["backtestTasks"][0]
            self.assertEqual(task["candidateId"], "forex-live12-rsi-loss-cooldown-v1")
            self.assertEqual(task["routeKey"], "RSI_Reversal")
            self.assertTrue(task["testerOnly"])
            self.assertFalse(task["livePresetMutation"])
            self.assertIn("run_param_lab.py", task["configOnlyCommand"])
            self.assertIn("--hfm-root", task["configOnlyCommand"])
            self.assertIn("HFM_MT5_Tester_Isolated", task["configOnlyCommand"])
            self.assertIn(f'--runtime-dir "{request["testerIsolation"]["isolatedRuntimeDir"]}"', task["configOnlyCommand"])
            self.assertIn(f'--runtime-dir "{primary_dashboard.parent}"', task["guardedRunTerminalCommand"])
            self.assertIn("--run-terminal", task["guardedRunTerminalCommand"])
            self.assertIn("--authorized-strategy-tester", task["guardedRunTerminalCommand"])
            self.assertIn("--wineprefix", task["guardedRunTerminalCommand"])
            self.assertIn(request["testerIsolation"]["isolatedWinePrefix"], task["guardedRunTerminalCommand"])
            self.assertIn("isolatedPlanPath", request["testerIsolation"])
            self.assertEqual(request["testerIsolation"]["liveRuntimeDir"], str(primary_dashboard.parent))
            self.assertFalse(request["decision"]["canRunTerminalHere"])
            self.assertFalse(request["decision"]["canApplyHere"])
            self.assertFalse(request["decision"]["canWritePresetHere"])
            self.assertFalse(request["decision"]["writesMt5Preset"])
            self.assertFalse(request["decision"]["orderSendAllowed"])
            self.assertFalse(request["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(request["decision"]["writesMt5OrderRequest"])
            self.assertFalse(request["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_rsi_tester_request_path(runtime).exists())
            hydrated = read_forex_live12_rsi_tester_request(runtime)
            self.assertEqual(hydrated["summary"]["topCandidateId"], "forex-live12-rsi-loss-cooldown-v1")
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_rsi_tester_run_gate_blocks_while_live_position_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "runtime": {
                    "connected": True,
                    "terminalConnected": True,
                    "accountAuthorized": True,
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.80,
                    "profit": -0.07,
                    "margin": 1.0,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.875, "ask": 159.897, "spread": 2.2},
                "openTrades": [
                    {
                        "ticket": 697870941,
                        "positionId": 697870941,
                        "type": "BUY",
                        "symbol": "USDJPYc",
                        "lots": 0.01,
                        "profit": -0.07,
                    }
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "READY_BUY_SIGNAL",
                    "guards": {
                        "portfolioPositions": 1,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.2,
                    },
                    "rsi": {"signalReady": True, "signalDirection": "BUY", "signalScore": 100},
                },
            })
            close_history = primary_dashboard.parent / "QuantGod_CloseHistory.csv"
            close_history.write_text(
                "\n".join([
                    "ExitTicket,PositionId,Type,Symbol,Lots,OpenTime,CloseTime,DurationMinutes,OpenPrice,ClosePrice,GrossProfit,Commission,Swap,NetProfit,Strategy,Source,EntryRegime,ExitRegime,RegimeTimeframe,Comment",
                    '1,11,"BUY","USDJPYc",0.01,"2026.06.03 05:00","2026.06.03 06:31",91,159.874,159.884,0.06,0.00,0.00,0.06,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '2,12,"BUY","USDJPYc",0.01,"2026.05.28 14:00","2026.05.28 15:30",89,159.473,159.332,-0.88,0.00,0.00,-0.88,"RSI_Reversal","EA","RANGE","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                ]),
                encoding="utf-8",
            )

            gate = build_forex_live12_rsi_tester_run_gate(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(gate["schema"], "quantgod.forex_live12_rsi_tester_run_gate.v1")
            self.assertEqual(gate["status"], "RSI_TESTER_RUN_GATE_BLOCKED")
            self.assertEqual(gate["artifactFreshness"]["mode"], "TIME_SENSITIVE_TESTER_GATE_READ_REBUILD")
            self.assertIn("primaryDashboardPath", gate["artifactFreshness"])
            self.assertIn(gate["nextTesterWindow"]["status"], {"open_now", "waiting", "unknown"})
            self.assertFalse(gate["decision"]["canRunIsolatedTester"])
            self.assertFalse(gate["decision"]["canRunTerminalHere"])
            self.assertIn("open_live_positions_present", gate["gate"]["blockers"])
            self.assertTrue(any(str(item).startswith("authorization_lock_") for item in gate["gate"]["blockers"]))
            self.assertFalse(gate["decision"]["orderSendAllowed"])
            self.assertFalse(gate["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(gate["decision"]["writesMt5Preset"])
            self.assertFalse(gate["decision"]["writesMt5OrderRequest"])
            self.assertFalse(gate["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_rsi_tester_run_gate_path(runtime).exists())
            hydrated = read_forex_live12_rsi_tester_run_gate(runtime)
            self.assertEqual(hydrated["status"], "RSI_TESTER_RUN_GATE_BLOCKED")
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_rsi_tester_account_context_status_blocks_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            status = _account_context_status(repo_root)
            self.assertFalse(status["exists"])
            self.assertFalse(status["ready"])
            self.assertIn("isolated_tester_account_context_not_ready", status["blockers"])

            account_status_path = repo_root / "runtime" / "QuantGod_IsolatedTesterAccountContextStatus.json"
            account_status_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_json(account_status_path, {
                "mode": "PREFLIGHT_ONLY_NO_SENSITIVE_COPY",
                "ready": False,
                "missingTarget": ["Config/accounts.dat"],
                "nextActionZh": "等待单独审查的隔离 tester 账户上下文同步动作；当前不复制敏感账户文件。",
            })

            status = _account_context_status(repo_root)
            self.assertTrue(status["exists"])
            self.assertFalse(status["ready"])
            self.assertEqual(status["missingTarget"], ["Config/accounts.dat"])
            self.assertIn("isolated_tester_account_context_not_ready", status["blockers"])

    def test_forex_live12_rsi_candidate_promotion_gate_separates_raw_and_repaired_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "runtime": {
                    "connected": True,
                    "terminalConnected": True,
                    "accountAuthorized": True,
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.87,
                    "profit": 0.0,
                    "margin": 0.0,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.875, "ask": 159.897, "spread": 2.2},
                "openTrades": [],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "WAITING_RSI_SIGNAL",
                    "guards": {
                        "portfolioPositions": 0,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.2,
                    },
                    "rsi": {"signalReady": False, "signalDirection": "NONE", "signalScore": 50},
                },
            })
            close_history = primary_dashboard.parent / "QuantGod_CloseHistory.csv"
            close_history.write_text(
                "\n".join([
                    "ExitTicket,PositionId,Type,Symbol,Lots,OpenTime,CloseTime,DurationMinutes,OpenPrice,ClosePrice,GrossProfit,Commission,Swap,NetProfit,Strategy,Source,EntryRegime,ExitRegime,RegimeTimeframe,Comment",
                    '1,11,"BUY","USDJPYc",0.01,"2026.05.01 05:00","2026.05.01 06:00",60,159.80,159.85,0.50,0.00,0.00,0.50,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '2,12,"BUY","USDJPYc",0.01,"2026.05.02 05:00","2026.05.02 06:00",60,159.80,159.77,-0.30,0.00,0.00,-0.30,"RSI_Reversal","EA","RANGE","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '3,13,"BUY","USDJPYc",0.01,"2026.05.03 05:00","2026.05.03 06:00",60,159.80,159.78,-0.20,0.00,0.00,-0.20,"RSI_Reversal","EA","TREND_DOWN","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '4,14,"BUY","USDJPYc",0.01,"2026.05.04 05:00","2026.05.04 06:00",60,159.80,159.79,-0.10,0.00,0.00,-0.10,"RSI_Reversal","EA","RANGE","TREND_EXP_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '5,15,"BUY","USDJPYc",0.01,"2026.05.05 05:00","2026.05.05 06:00",60,159.80,159.83,0.30,0.00,0.00,0.30,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                ]),
                encoding="utf-8",
            )

            gate = build_forex_live12_rsi_candidate_promotion_gate(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(gate["schema"], "quantgod.forex_live12_rsi_candidate_promotion_gate.v1")
            self.assertEqual(gate["status"], "RSI_REPAIRED_CANDIDATE_READY_FOR_TESTER")
            self.assertEqual(gate["target"]["requestedMaxTotalTrades"], 10)
            self.assertEqual(gate["target"]["directJumpToTargetStatus"], "BLOCKED_BY_STAGED_RISK_RULES")
            self.assertEqual(gate["rawExpansionEvidence"]["rawExpansionStage"], "BLOCKED")
            self.assertEqual(gate["repairedCandidateEvidence"]["validationStage"], "READY_FOR_TESTER_VALIDATION")
            self.assertGreaterEqual(gate["repairedCandidateEvidence"]["afterMetrics"]["profitFactor"], 1.05)
            self.assertLessEqual(gate["repairedCandidateEvidence"]["afterMetrics"]["maxConsecutiveLosses"], 2)
            self.assertTrue(gate["decision"]["candidateReadyForTesterValidation"])
            self.assertFalse(gate["decision"]["canApplyHere"])
            self.assertFalse(gate["decision"]["canWritePresetHere"])
            self.assertFalse(gate["decision"]["canPromoteToLiveHere"])
            self.assertFalse(gate["decision"]["orderSendAllowed"])
            self.assertFalse(gate["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(gate["decision"]["writesMt5Preset"])
            self.assertFalse(gate["decision"]["writesMt5OrderRequest"])
            self.assertFalse(gate["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_rsi_candidate_promotion_gate_path(runtime).exists())
            hydrated = read_forex_live12_rsi_candidate_promotion_gate(runtime)
            self.assertEqual(hydrated["status"], "RSI_REPAIRED_CANDIDATE_READY_FOR_TESTER")
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_forex_live12_rsi_tester_lock_draft_is_non_writing_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "runtime": {
                    "connected": True,
                    "terminalConnected": True,
                    "accountAuthorized": True,
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.87,
                    "profit": 0.0,
                    "margin": 0.0,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.875, "ask": 159.897, "spread": 2.2},
                "openTrades": [],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "WAITING_RSI_SIGNAL",
                    "guards": {
                        "portfolioPositions": 0,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.2,
                    },
                    "rsi": {"signalReady": False, "signalDirection": "NONE", "signalScore": 50},
                },
            })
            close_history = primary_dashboard.parent / "QuantGod_CloseHistory.csv"
            close_history.write_text(
                "\n".join([
                    "ExitTicket,PositionId,Type,Symbol,Lots,OpenTime,CloseTime,DurationMinutes,OpenPrice,ClosePrice,GrossProfit,Commission,Swap,NetProfit,Strategy,Source,EntryRegime,ExitRegime,RegimeTimeframe,Comment",
                    '1,11,"BUY","USDJPYc",0.01,"2026.05.01 05:00","2026.05.01 06:00",60,159.80,159.85,0.50,0.00,0.00,0.50,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '2,12,"BUY","USDJPYc",0.01,"2026.05.02 05:00","2026.05.02 06:00",60,159.80,159.77,-0.30,0.00,0.00,-0.30,"RSI_Reversal","EA","RANGE","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '3,13,"BUY","USDJPYc",0.01,"2026.05.03 05:00","2026.05.03 06:00",60,159.80,159.78,-0.20,0.00,0.00,-0.20,"RSI_Reversal","EA","TREND_DOWN","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '4,14,"BUY","USDJPYc",0.01,"2026.05.04 05:00","2026.05.04 06:00",60,159.80,159.79,-0.10,0.00,0.00,-0.10,"RSI_Reversal","EA","RANGE","TREND_EXP_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '5,15,"BUY","USDJPYc",0.01,"2026.05.05 05:00","2026.05.05 06:00",60,159.80,159.83,0.30,0.00,0.00,0.30,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                ]),
                encoding="utf-8",
            )

            draft = build_forex_live12_rsi_tester_lock_draft(
                runtime,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(draft["schema"], "quantgod.forex_live12_rsi_tester_lock_draft.v1")
            self.assertEqual(draft["status"], "RSI_TESTER_LOCK_DRAFT_READY")
            self.assertFalse(draft["lockFileWritten"])
            self.assertIn("QuantGod_AutoTesterWindow.lock.json", draft["targetLockPath"])
            self.assertEqual(draft["draftPayload"]["purpose"], "PARAM_LAB_STRATEGY_TESTER_ONLY")
            self.assertTrue(draft["draftPayload"]["testerOnly"])
            self.assertTrue(draft["draftPayload"]["allowRunTerminal"])
            self.assertFalse(draft["draftPayload"]["livePresetMutation"])
            self.assertFalse(draft["draftPayload"]["allowOutsideWindow"])
            self.assertEqual(draft["draftPayload"]["maxTasks"], 1)
            self.assertFalse(draft["decision"]["canRunTerminalHere"])
            self.assertFalse(draft["decision"]["canApplyHere"])
            self.assertFalse(draft["decision"]["orderSendAllowed"])
            self.assertFalse(draft["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(draft["decision"]["writesMt5Preset"])
            self.assertFalse(draft["decision"]["writesMt5OrderRequest"])
            self.assertFalse(draft["decision"]["brokerCallsMade"])
            self.assertTrue(forex_live12_rsi_tester_lock_draft_path(runtime).exists())
            hydrated = read_forex_live12_rsi_tester_lock_draft(runtime)
            self.assertEqual(hydrated["status"], "RSI_TESTER_LOCK_DRAFT_READY")
            self.assertEqual(hydrated["sourceTesterGate"]["liveSession"]["path"], str(primary_dashboard))
            self.assertEqual(hydrated["draftPayload"]["runtimeDir"], str(primary_dashboard.parent))
            self.assertTrue(hydrated["artifactFreshness"]["autoRebuiltForRead"])
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])

    def test_sim_target_execution_review_summary_compacts_target_and_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json", {
                "schema": "quantgod.profit_target_tracker.v1",
                "status": "TARGET_REACHED",
                "targetReached": True,
                "combinedTarget": {
                    "status": "TARGET_REACHED",
                    "statusZh": "任一 lane 或多 lane 净合计已达到 50 USD",
                    "targetReached": True,
                    "combinedVerifiedUsdProfit": 137.22,
                },
                "laneTargets": {
                    "forexMt5": {
                        "labelZh": "外币 MT5 模拟/纸盘",
                        "marketType": "forex_cfd",
                        "status": "LANE_POSITIVE",
                        "targetReached": True,
                        "lanePositive": True,
                        "simulationVerifiedUsdProfit": 72.0,
                        "targetUsd": 50.0,
                        "evidenceCount": 1,
                    },
                    "btcCryptoCfd": {
                        "labelZh": "BTC / HFM crypto CFD 模拟",
                        "marketType": "crypto_cfd",
                        "status": "LANE_POSITIVE",
                        "targetReached": True,
                        "lanePositive": True,
                        "simulationVerifiedUsdProfit": 65.22,
                        "targetUsd": 50.0,
                        "evidenceCount": 1,
                    },
                },
                "liveExecutionReview": {
                    "status": "TARGET_REACHED_WAITING_EXECUTION_MODE_ACTIVATION",
                    "statusZh": "模拟收益目标已达成，等待执行模式闸门",
                    "cutoverStatus": "WAITING_EXECUTION_MODE_ACTIVATION",
                    "dataPlaneCutoverReady": True,
                    "disabledFirstImplementationWorkReady": True,
                    "executionModeOnlyBlocked": True,
                    "primaryActionableBlocker": {
                        "code": "DEPLOYED_PRESET_READ_ONLY_TRUE",
                        "reasonZh": "当前部署 preset 仍为 ReadOnlyMode=true。",
                    },
                    "blockers": [
                        {
                            "code": "EXECUTION_MODE_GATES_NOT_ACTIVE",
                            "reasonZh": "仅等待执行模式闸门。",
                            "source": "live_execution_review",
                        },
                        {
                            "code": "DEPLOYED_PRESET_READ_ONLY_TRUE",
                            "reasonZh": "当前部署 preset 仍为 ReadOnlyMode=true。",
                            "source": "live_execution_review",
                        },
                    ],
                    "executionReleaseReadinessPacket": {
                        "releaseReady": False,
                        "releaseGateSummary": {
                            "blocked": 1,
                            "blockerCodes": ["BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING"],
                        },
                    },
                },
            })
            self._write_json(release_readiness_refresh_path(runtime), {
                "schema": "quantgod.release_readiness_refresh.v1",
                "status": "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE",
                "releaseUnblockPlan": {
                    "profitTargetReached": True,
                    "combinedVerifiedUsdProfit": 137.22,
                    "qualifyingLaneIds": ["forexMt5", "btcCryptoCfd"],
                    "releaseBlockedCount": 1,
                    "executionModeBlockedCount": 1,
                    "reviewOnlyProposedFileChanges": [
                        {
                            "artifact": "deployedPreset",
                            "path": "/tmp/QuantGod_MT5_HFM_LiveSecondary.set",
                            "section": "",
                            "key": "ReadOnlyMode",
                            "currentValue": "true",
                            "targetValue": "false",
                            "blockerCode": "DEPLOYED_PRESET_READ_ONLY_TRUE",
                            "reasonZh": "当前部署 preset 仍为 ReadOnlyMode=true。",
                            "reviewRequirementZh": "单独评审 ReadOnlyMode=false。",
                        },
                    ],
                    "releaseTokenReviewRows": [
                        {
                            "gateId": "broker_order_send_release",
                            "labelZh": "Broker OrderSend",
                            "tokenName": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
                            "blockerCode": "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                            "sideEffectZh": "调用 MT5 OrderSend",
                            "sourceArtifact": "brokerOrderSendReview",
                            "dataPlaneReady": True,
                            "tokenProvided": False,
                            "requiredEvidenceZh": "需要单独审查的 release token。",
                        },
                    ],
                },
                "safety": {"orderSendAllowed": False},
            })
            self._write_json(runtime / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json", {
                "schema": "quantgod.hfm_crypto_cfd.state.v1",
                "status": "READY_FOR_SHADOW_RESEARCH",
                "statusZh": "HFM Crypto CFD 影子研究就绪",
                "symbolEvidence": {
                    "found": True,
                    "brokerSymbols": ["#BTCUSD"],
                },
                "simulationProfileReview": {
                    "simulationQualified": True,
                    "metrics": {
                        "agentId": "hfm_crypto_btc_regime_stability_shadow_v1",
                        "pnl": 65.2172,
                        "sharpe": 2.7529,
                        "maxDrawdownPct": 0.7974,
                        "tradeCount": 29,
                        "liquidationCount": 0,
                    },
                },
                "executionSpecReview": {
                    "coveredBrokerSymbols": ["#BTCUSD"],
                },
            })
            self._write_json(runtime / "agent" / "QuantGod_TpSlOptimizerReport.json", {
                "schema": "quantgod.tp_sl_optimizer.report.v1",
                "btcCryptoCfd": {
                    "finalAdvisoryPickPolicy": "STABLE_OVER_TARGET_SEEKING",
                    "finalAdvisoryPickReasonZh": "默认继续复验稳健组合。",
                    "finalAdvisoryPick": {
                        "strategyId": "hfm_crypto_btc_tpsl_0016",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "params": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "tpSlSummary": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "fullWindowMetrics": {
                            "pnlUsd": 38.7432,
                            "sharpe": 1.326,
                            "maxDrawdownPct": 1.5619,
                            "tradeCount": 69,
                            "liquidationCount": 0,
                        },
                        "blockers": ["HFM_SHARPE_LT_MIN"],
                    },
                    "targetTradeoff": {"targetSeekingPnlUsd": 83.0437},
                    "middleWindowLeaders": {
                        "status": "BTC_MIDDLE_WINDOW_LEADERS_READY",
                        "bestTargetMiddleQuality": {
                            "strategyId": "hfm_crypto_btc_tpsl_3018",
                            "middleThirdMetrics": {"sharpe": 1.3058, "tradeCount": 15},
                            "orderSendAllowed": False,
                        },
                    },
                },
            })
            self._write_json(runtime / "agent" / "QuantGod_AceExecutionCandidatePack.json", {
                "schema": "quantgod.ace_execution_candidate_pack.v1",
                "status": "ACE_EXECUTION_CANDIDATE_PACK_READY",
                "rsiDemotionReview": {
                    "status": "RSI_LIVE_LOGIC_DEMOTE_REVIEW",
                    "decision": "DISCARD_AS_ACE",
                    "recommendedAction": "DEMOTE_RAW_RSI_FROM_ACE",
                    "currentEvidence": {
                        "strategyId": "live12_raw_rsi",
                        "netProfitUSC": 0.0,
                        "profitFactor": 0.0,
                        "tradeCount": 0,
                        "blockers": ["NET_PROFIT_NOT_POSITIVE", "PROFIT_FACTOR_LT_1_05"],
                    },
                    "replacementPlan": {
                        "primaryForexAce": {
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                            "status": "FOREX_CHAMPION_RETEST_PASS",
                            "contenderTieBreakRequired": True,
                            "metrics": {"profitFactor": 2.6998, "sharpe": 2.0702},
                        },
                        "btcTargetMiddleQuality": {
                            "strategyId": "hfm_crypto_btc_tpsl_3018",
                            "role": "bestTargetMiddleQuality",
                            "validWindowCount": 2,
                            "windowCount": 6,
                            "fullWindowMetrics": {"pnlUsd": 61.0484, "sharpe": 1.6788},
                            "middleThirdMetrics": {"pnlUsd": 23.0369, "sharpe": 1.5591},
                            "parameters": {"takeProfitPriceMove": 750.0, "stopLossPriceMove": 375.0},
                        },
                        "nextActionZh": "raw RSI 降级后优先复验 G0093/G0102 和 BTC 中段候选。",
                    },
                },
                "liveUpgradeSelection": {
                    "status": "RSI_DEMOTED_FOREX_AB_READY",
                    "statusZh": "raw RSI 已排除；G0093/G0102 作为外汇王牌 A/B 进入 tester-forward。",
                    "selectedLane": "forexMt5",
                    "selectedStrategy": {
                        "lane": "forexMt5",
                        "seedId": "GA-USDJPY-G0093-C0004",
                        "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                        "contenderTieBreakRequired": True,
                    },
                    "excludedAceCandidates": [
                        {
                            "lane": "live12_raw_rsi",
                            "strategyId": "live12_raw_rsi",
                            "reason": "DEMOTE_RAW_RSI_FROM_ACE",
                        }
                    ],
                    "upgradePrerequisites": [
                        "isolated_tester_forward_report_ready",
                        "champion_tester_run_gate_ready",
                        "separate_execution_release_lane_ready",
                    ],
                    "nextActionZh": "先跑 G0093/G0102 隔离 tester-forward A/B。",
                },
            })
            self._write_json(runtime / "agent" / "QuantGod_ChampionTesterForwardRequest.json", {
                "schema": "quantgod.champion_tester_forward_request.v1",
                "status": "CHAMPION_TESTER_FORWARD_REQUEST_READY",
                "statusZh": "G0093/G0102 tester 请求已生成",
                "summary": {
                    "candidateIds": [
                        "g0093-usdjpy-rsi-champion-tester-forward-v1",
                        "g0102-usdjpy-rsi-champion-tester-forward-v1",
                    ],
                    "queueCount": 2,
                },
                "decision": {
                    "canMaterializeConfigHere": True,
                    "canRunTerminalHere": False,
                    "canPromoteToLiveHere": False,
                },
            })
            self._write_json(runtime / "agent" / "QuantGod_ChampionTesterRunGate.json", {
                "schema": "quantgod.champion_tester_run_gate.v1",
                "status": "CHAMPION_TESTER_RUN_GATE_BLOCKED",
                "statusZh": "G0093 隔离 Strategy Tester 启动条件未满足",
                "gate": {
                    "blockers": ["outside_strategy_tester_window", "authorization_lock_expired"],
                },
                "testerAccountContext": {
                    "blockers": ["isolated_tester_account_context_not_ready"],
                },
                "decision": {
                    "canRunIsolatedTester": False,
                    "canRunTerminalHere": False,
                },
            })
            self._write_json(runtime / "agent" / "QuantGod_ChampionTesterLockDraft.json", {
                "schema": "quantgod.champion_tester_lock_draft.v1",
                "status": "CHAMPION_TESTER_LOCK_DRAFT_READY",
                "statusZh": "G0093 tester lock 草案已生成",
                "decision": {
                    "draftReadyForSeparateLockWriter": True,
                    "lockFileWritten": False,
                    "canRunTerminalHere": False,
                },
            })
            self._write_json(runtime / "agent" / "QuantGod_ChampionPromotionGate.json", {
                "schema": "quantgod.champion_promotion_gate.v1",
                "status": "WAITING_ISOLATED_TESTER_FORWARD_REPORT",
                "statusZh": "G0093/G0102 tester 请求已准备，等待前向报告",
                "blockers": ["isolated_tester_forward_report_ready", "champion_tester_run_gate_ready"],
                "promotionDecision": {
                    "canRunIsolatedTesterForwardNext": True,
                    "canRunIsolatedTesterNow": False,
                    "testerLockDraftReady": True,
                    "canPromoteToLiveNow": False,
                    "autoPromotionToLiveAllowed": False,
                    "reasonZh": "先把 G0093/G0102 补成 tester/forward 级冠军。",
                },
            })
            self._write_json(runtime / "QuantGod_IsolatedTesterAccountContextStatus.json", {
                "schemaVersion": 1,
                "mode": "PREFLIGHT_ONLY_NO_SENSITIVE_COPY",
                "source": {
                    "accountContextExists": True,
                    "serverContextExists": True,
                    "missing": [],
                },
                "target": {
                    "accountContextExists": False,
                    "serverContextExists": True,
                    "missing": ["Config/accounts.dat"],
                },
                "missingTarget": ["Config/accounts.dat"],
                "missingSource": [],
                "ready": False,
                "sensitiveAccountContextSyncRequired": True,
                "copiedFileCount": 0,
                "copiedTreeCount": 0,
                "separateSyncReview": {
                    "status": "SEPARATE_SENSITIVE_ACCOUNT_CONTEXT_SYNC_REQUIRED",
                    "requiresSeparateControlledSync": True,
                    "sensitiveCopyAllowedHere": False,
                    "commandPreview": [
                        "python3",
                        "tools/sync_isolated_mt5_account_context.py",
                        "--allow-sensitive-account-context",
                    ],
                    "launchesTerminal": False,
                    "writesLivePreset": False,
                    "writesMt5OrderRequest": False,
                },
                "nextActionZh": "隔离 tester 账户上下文不完整；需要单独受控同步账户上下文后再重试 Strategy Tester。",
            })
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                    "balance": 10222.87,
                    "equity": 10222.87,
                    "profit": 0.0,
                    "maxTotalTrades": 2,
                },
                "market": {"symbol": "USDJPYc", "bid": 159.875, "ask": 159.897, "spread": 2.2},
                "openTrades": [],
                "usdJpyRsiEntryDiagnostics": {
                    "state": "WAIT_SIGNAL",
                    "guards": {
                        "portfolioPositions": 0,
                        "maxTotalPositions": 2,
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.2,
                    },
                    "rsi": {"signalReady": False, "signalDirection": "NONE", "signalScore": 50},
                },
            })
            (primary_dashboard.parent / "QuantGod_CloseHistory.csv").write_text(
                "\n".join([
                    "ExitTicket,PositionId,Type,Symbol,Lots,OpenTime,CloseTime,DurationMinutes,OpenPrice,ClosePrice,GrossProfit,Commission,Swap,NetProfit,Strategy,Source,EntryRegime,ExitRegime,RegimeTimeframe,Comment",
                    '1,11,"BUY","USDJPYc",0.01,"2026.05.01 05:00","2026.05.01 06:00",60,159.80,159.85,0.50,0.00,0.00,0.50,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                    '2,12,"BUY","USDJPYc",0.01,"2026.05.02 05:00","2026.05.02 06:00",60,159.80,159.77,-0.30,0.00,0.00,-0.30,"RSI_Reversal","EA","RANGE","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '3,13,"BUY","USDJPYc",0.01,"2026.05.03 05:00","2026.05.03 06:00",60,159.80,159.78,-0.20,0.00,0.00,-0.20,"RSI_Reversal","EA","TREND_DOWN","TREND_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '4,14,"BUY","USDJPYc",0.01,"2026.05.04 05:00","2026.05.04 06:00",60,159.80,159.79,-0.10,0.00,0.00,-0.10,"RSI_Reversal","EA","RANGE","TREND_EXP_DOWN","H1","QG_RSI_Rev_MT5_BUY"',
                    '5,15,"BUY","USDJPYc",0.01,"2026.05.05 05:00","2026.05.05 06:00",60,159.80,159.83,0.30,0.00,0.00,0.30,"RSI_Reversal","EA","RANGE","RANGE","H1","QG_RSI_Rev_MT5_BUY"',
                ]),
                encoding="utf-8",
            )

            summary = build_sim_target_execution_review_summary(
                runtime,
                target_usd=50.0,
                requested_max_total_trades=10,
                primary_dashboard_json=str(primary_dashboard),
                write=True,
            )
            self.assertEqual(summary["schema"], "quantgod.sim_target_execution_review_summary.v1")
            self.assertEqual(summary["status"], "TARGET_REACHED_WAITING_EXECUTION_MODE")
            self.assertTrue(summary["targetEvidence"]["targetReached"])
            self.assertEqual(summary["targetEvidence"]["combinedVerifiedUsdProfit"], 137.22)
            self.assertEqual(summary["request"]["requestedMaxTotalTrades"], 10)
            btc_candidate = summary["btcTpSlExecutionCandidate"]
            self.assertEqual(btc_candidate["strategyId"], "hfm_crypto_btc_tpsl_0016")
            self.assertEqual(btc_candidate["tpSlSummary"]["takeProfitPriceMove"], 450.0)
            self.assertEqual(
                btc_candidate["middleWindowLeaders"]["bestTargetMiddleQuality"]["strategyId"],
                "hfm_crypto_btc_tpsl_3018",
            )
            self.assertFalse(btc_candidate["orderSendAllowed"])
            ace_upgrade = summary["aceStrategyUpgradeReview"]
            self.assertEqual(ace_upgrade["status"], "ACE_RSI_DEMOTION_REPLACEMENT_READY")
            self.assertTrue(ace_upgrade["rsiDemoted"])
            self.assertEqual(ace_upgrade["rsiRecommendedAction"], "DEMOTE_RAW_RSI_FROM_ACE")
            self.assertEqual(
                ace_upgrade["primaryForexReplacement"]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                ace_upgrade["btcReplacement"]["strategyId"],
                "hfm_crypto_btc_tpsl_3018",
            )
            self.assertEqual(
                ace_upgrade["btcReplacement"]["params"]["takeProfitPriceMove"],
                750.0,
            )
            live_upgrade = ace_upgrade["liveUpgradeSelection"]
            self.assertEqual(live_upgrade["status"], "RSI_DEMOTED_FOREX_AB_READY")
            self.assertEqual(live_upgrade["selectedLane"], "forexMt5")
            self.assertEqual(live_upgrade["selectedStrategy"]["seedId"], "GA-USDJPY-G0093-C0004")
            self.assertEqual(
                live_upgrade["excludedAceCandidates"][0]["reason"],
                "DEMOTE_RAW_RSI_FROM_ACE",
            )
            self.assertIn("champion_tester_run_gate_ready", live_upgrade["upgradePrerequisites"])
            self.assertFalse(live_upgrade["orderSendAllowed"])
            champion_forward = ace_upgrade["championForwardReview"]
            self.assertEqual(champion_forward["status"], "WAITING_ISOLATED_TESTER_FORWARD_REPORT")
            self.assertTrue(champion_forward["promotionDecision"]["canRunIsolatedTesterForwardNext"])
            self.assertFalse(champion_forward["promotionDecision"]["canRunIsolatedTesterNow"])
            self.assertTrue(champion_forward["promotionDecision"]["testerLockDraftReady"])
            self.assertEqual(champion_forward["testerRequest"]["queueCount"], 2)
            self.assertFalse(champion_forward["testerRunGate"]["canRunIsolatedTester"])
            self.assertIn("outside_strategy_tester_window", champion_forward["testerRunGate"]["blockers"])
            self.assertIn(
                "isolated_tester_account_context_not_ready",
                champion_forward["testerRunGate"]["accountContextBlockers"],
            )
            account_plan = champion_forward["accountContextSyncPlan"]
            self.assertEqual(account_plan["status"], "ACCOUNT_CONTEXT_SYNC_REQUIRED")
            self.assertTrue(account_plan["sourceAccountContextExists"])
            self.assertFalse(account_plan["targetAccountContextExists"])
            self.assertEqual(account_plan["missingTarget"], ["Config/accounts.dat"])
            self.assertTrue(account_plan["sensitiveAccountContextSyncRequired"])
            self.assertFalse(account_plan["sensitiveCopyAllowedHere"])
            self.assertEqual(account_plan["copiedFileCount"], 0)
            sync_review = account_plan["separateSyncReview"]
            self.assertEqual(sync_review["status"], "SEPARATE_SENSITIVE_ACCOUNT_CONTEXT_SYNC_REQUIRED")
            self.assertTrue(sync_review["requiresSeparateControlledSync"])
            self.assertFalse(sync_review["sensitiveCopyAllowedHere"])
            self.assertIn("--allow-sensitive-account-context", sync_review["commandPreview"])
            self.assertFalse(sync_review["launchesTerminal"])
            self.assertFalse(sync_review["writesMt5OrderRequest"])
            self.assertTrue(champion_forward["testerLockDraft"]["draftReadyForSeparateLockWriter"])
            self.assertFalse(champion_forward["orderSendAllowed"])
            self.assertFalse(ace_upgrade["orderSendAllowed"])
            self.assertFalse(ace_upgrade["writesLivePreset"])
            capacity = summary["capacityExpansionEvidence"]
            self.assertEqual(capacity["sourceDashboardPath"], str(primary_dashboard))
            self.assertEqual(capacity["currentStage"], "2_TO_3_REPAIR")
            self.assertEqual(capacity["rawNaturalClosedTrades"], 5)
            self.assertEqual(capacity["rawMaxConsecutiveLosses"], 3)
            self.assertEqual(capacity["nextRecommendedMaxTotalTrades"], 2)
            blocker_codes = [row["code"] for row in summary["executionReview"]["topBlockers"]]
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", blocker_codes)
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", blocker_codes)
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", blocker_codes)
            minimal_diff = summary["executionReview"]["minimalDiffReview"]
            self.assertEqual(minimal_diff["changeCount"], 1)
            self.assertEqual(minimal_diff["releaseTokenCount"], 1)
            self.assertEqual(minimal_diff["proposedChanges"][0]["key"], "ReadOnlyMode")
            self.assertEqual(minimal_diff["releaseTokens"][0]["gateId"], "broker_order_send_release")
            self.assertFalse(minimal_diff["canApplyDiffNow"])
            self.assertFalse(minimal_diff["canReleaseExecutionNow"])
            release_evidence = summary["executionReview"]["releaseTokenEvidenceReview"]
            self.assertEqual(release_evidence["releaseTokenCount"], 1)
            self.assertEqual(release_evidence["incompleteEvidenceCount"], 1)
            self.assertEqual(release_evidence["tokenMissingCount"], 1)
            self.assertFalse(release_evidence["releaseTokenMissingOnlyAfterEvidenceComplete"])
            self.assertEqual(
                release_evidence["releaseBlockerClass"],
                "EVIDENCE_OR_TOKEN_MISSING",
            )
            self.assertFalse(release_evidence["canReleaseExecutionNow"])
            self.assertFalse(release_evidence["mt5OrderSendAllowed"])
            signoff_matrix = summary["executionReview"]["signoffEvidenceMatrix"]
            self.assertIn(signoff_matrix["status"], {
                "SIGNOFF_EVIDENCE_MATRIX_UNAVAILABLE_REVIEW_ONLY",
                "SIGNOFF_EVIDENCE_PARTIAL_REVIEW_ONLY",
            })
            self.assertFalse(signoff_matrix["canReleaseExecutionNow"])
            signoff = summary["executionReview"]["signoffHandoff"]
            self.assertEqual(signoff["releaseTokenCount"], 1)
            self.assertEqual(signoff["completeSignoffCount"], 0)
            self.assertEqual(signoff["missingSignoffCount"], 1)
            self.assertFalse(signoff["canAcceptSignoffHere"])
            self.assertFalse(signoff["canMintTokenHere"])
            self.assertFalse(signoff["canReleaseExecutionNow"])
            self.assertFalse(summary["decision"]["orderSendAllowed"])
            self.assertFalse(summary["decision"]["mt5OrderSendAllowed"])
            self.assertFalse(summary["decision"]["writesMt5Preset"])
            self.assertFalse(summary["decision"]["writesMt5OrderRequest"])
            self.assertFalse(summary["decision"]["brokerCallsMade"])
            self.assertTrue(sim_target_execution_review_summary_path(runtime).exists())
            hydrated = read_sim_target_execution_review_summary(runtime)
            self.assertEqual(hydrated["status"], "TARGET_REACHED_WAITING_EXECUTION_MODE")
            self.assertFalse(hydrated["safety"]["orderSendAllowed"])
            summary_path = sim_target_execution_review_summary_path(runtime)
            sentinel = {**summary, "status": "SENTINEL_READ_ONLY_STATUS"}
            summary_path.write_text(json.dumps(sentinel), encoding="utf-8")
            self.assertEqual(
                read_sim_target_execution_review_summary(runtime)["status"],
                "SENTINEL_READ_ONLY_STATUS",
            )

    def test_sim_target_execution_review_summary_uses_cutover_fallback_when_profit_tracker_has_no_live_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json", {
                "schema": "quantgod.profit_target_tracker.v1",
                "status": "TARGET_REACHED",
                "targetReached": True,
                "combinedTarget": {
                    "status": "TARGET_REACHED",
                    "statusZh": "任一 lane 或多 lane 净合计已达到 50 USD",
                    "targetReached": True,
                    "combinedVerifiedUsdProfit": 72.0,
                },
                "laneTargets": {
                    "forexMt5": {
                        "labelZh": "外币 MT5 模拟/纸盘",
                        "marketType": "forex_cfd",
                        "status": "LANE_POSITIVE",
                        "targetReached": True,
                        "lanePositive": True,
                        "simulationVerifiedUsdProfit": 72.0,
                        "targetUsd": 50.0,
                        "evidenceCount": 1,
                    },
                },
            })
            self._write_json(live_execution_cutover_review_path(runtime), {
                "schema": "quantgod.live_execution_cutover_review.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "statusZh": "live execution cutover 数据面已通过，等待执行模式闸门",
                "dataPlaneCutoverReady": True,
                "executionModeOnlyBlocked": True,
                "blockers": [
                    {
                        "code": "EXECUTION_MODE_GATES_NOT_ACTIVE",
                        "reasonZh": "live execution cutover 数据面已具备；仅等待执行模式闸门。",
                    },
                ],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerCallsMade": False,
            })
            self._write_json(release_readiness_refresh_path(runtime), {
                "schema": "quantgod.release_readiness_refresh.v1",
                "status": "WAITING_RELEASE_TOKENS",
                "executionReleaseReadinessPacket": {
                    "releaseReady": False,
                    "releaseGateSummary": {
                        "blocked": 5,
                        "blockerCodes": [
                            "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
                            "REQUEST_READER_RELEASE_TOKEN_MISSING",
                        ],
                    },
                },
                "postTargetExecutionSummary": {
                    "status": "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE",
                    "statusZh": "收益目标已达成，执行仍锁定",
                    "dataPlaneReady": True,
                    "executionModeOnlyBlocked": True,
                },
                "releaseUnblockPlan": {
                    "profitTargetReached": True,
                    "combinedVerifiedUsdProfit": 72.0,
                    "qualifyingLaneIds": ["forexMt5"],
                    "releaseBlockedCount": 5,
                    "executionModeBlockedCount": 0,
                    "reviewOnlyProposedFileChanges": [],
                    "releaseTokenReviewRows": [],
                },
                "safety": {"orderSendAllowed": False},
            })
            self._write_json(runtime / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json", {
                "schema": "quantgod.hfm_crypto_cfd.state.v1",
                "status": "READY_FOR_SHADOW_RESEARCH",
                "statusZh": "HFM Crypto CFD 影子研究就绪",
                "symbolEvidence": {"found": True, "brokerSymbols": ["#BTCUSD"]},
                "simulationProfileReview": {
                    "simulationQualified": True,
                    "metrics": {
                        "agentId": "hfm_crypto_btc_regime_stability_shadow_v1",
                        "pnl": 65.2172,
                        "sharpe": 2.7529,
                        "maxDrawdownPct": 0.7974,
                        "tradeCount": 29,
                        "liquidationCount": 0,
                    },
                },
                "executionSpecReview": {"coveredBrokerSymbols": ["#BTCUSD"]},
            })
            self._write_json(forex_live12_rsi_candidate_promotion_gate_path(runtime), {
                "schema": "quantgod.forex_live12_rsi_candidate_promotion_gate.v1",
                "target": {
                    "requestedMaxTotalTrades": 10,
                    "currentStage": "2_TO_3_REPAIR",
                    "directJumpToTargetStatus": "BLOCKED_BY_STAGED_RISK_RULES",
                },
                "rawExpansionEvidence": {
                    "rawExpansionStage": "BLOCKED",
                    "blockerCodes": [],
                    "metrics": {
                        "naturalClosedTrades": 0,
                        "profitFactor": None,
                        "maxConsecutiveLosses": 0,
                    },
                },
                "repairedCandidateEvidence": {
                    "validationStage": "WAITING_SHADOW_EVIDENCE",
                    "candidateId": "forex-live12-rsi-loss-cooldown-v1",
                    "afterMetrics": {
                        "naturalClosedTrades": 0,
                        "profitFactor": None,
                        "maxConsecutiveLosses": 0,
                    },
                },
                "artifactFreshness": {
                    "primaryDashboardPath": "",
                    "primaryDashboardMtimeIso": "",
                    "closeHistoryPath": "",
                    "closeHistoryMtimeIso": "",
                },
                "decision": {
                    "candidateReadyForTesterValidation": False,
                    "nextRecommendedMaxTotalTrades": 2,
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(release_token_signoff_input_template_path(runtime), {
                "schema": "quantgod.release_token_signoff_input_template.v1",
                "status": "SIGNOFF_INPUT_TEMPLATE_READY",
                "releaseTokenCount": 2,
                "readyForInputCount": 2,
                "signoffInputTemplate": {
                    "releaseTokenSignoffs": [
                        {"gateId": "request_writer_release", "blockerCode": "REQUEST_WRITE_RELEASE_TOKEN_MISSING"},
                        {"gateId": "ea_reader_release", "blockerCode": "REQUEST_READER_RELEASE_TOKEN_MISSING"},
                    ],
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(release_token_signoff_input_review_path(runtime), {
                "schema": "quantgod.release_token_signoff_input_review.v1",
                "status": "SIGNOFF_INPUT_COMPLETE_FOR_SEPARATE_RELEASE_LANE",
                "releaseTokenCount": 2,
                "completeSignoffCount": 2,
                "forbiddenSecretFieldPaths": [],
                "reviewRows": [
                    {
                        "gateId": "request_writer_release",
                        "blockerCode": "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
                        "inputProvided": True,
                        "completeForSeparateReleaseReview": True,
                    },
                    {
                        "gateId": "ea_reader_release",
                        "blockerCode": "REQUEST_READER_RELEASE_TOKEN_MISSING",
                        "inputProvided": True,
                        "completeForSeparateReleaseReview": True,
                    },
                ],
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(release_token_signoff_handoff_path(runtime), {
                "schema": "quantgod.release_token_signoff_handoff.v1",
                "status": "SIGNOFF_HANDOFF_READY_FOR_SEPARATE_RELEASE_LANE",
                "releaseTokenCount": 2,
                "readyForInputCount": 2,
                "completeSignoffCount": 2,
                "missingSignoffCount": 0,
                "missingSignoffRows": [],
                "handoffInstructions": [],
                "canProceedToLiveExecutionHere": False,
                "canAcceptSignoffHere": False,
                "canMintTokenHere": False,
                "canReleaseExecutionNow": False,
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })
            self._write_json(release_token_signoff_evidence_matrix_path(runtime), {
                "schema": "quantgod.release_token_signoff_evidence_matrix.v1",
                "status": "SIGNOFF_EVIDENCE_AND_INPUT_READY_FOR_SEPARATE_RELEASE_LANE",
                "releaseTokenCount": 2,
                "completeSignoffCount": 2,
                "acknowledgementReadyCount": 5,
                "acknowledgementCount": 5,
                "gatesWithCompleteEvidence": 2,
                "acknowledgementRows": [],
                "gateRows": [],
                "decision": {
                    "canReleaseExecutionNow": False,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                },
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            })

            summary = build_sim_target_execution_review_summary(runtime, write=True)
            review = summary["executionReview"]
            self.assertEqual(review["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertEqual(review["cutoverStatus"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(review["dataPlaneReady"])
            self.assertTrue(review["executionModeOnlyBlocked"])
            self.assertFalse(review["releaseReady"])
            self.assertEqual(review["blockedReleaseGateCount"], 5)
            blocker_codes = [row["code"] for row in review["topBlockers"]]
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", blocker_codes)
            self.assertIn("REQUEST_WRITE_RELEASE_TOKEN_MISSING", blocker_codes)
            self.assertIn("REQUEST_READER_RELEASE_TOKEN_MISSING", blocker_codes)
            self.assertFalse(summary["decision"]["orderSendAllowed"])
            self.assertFalse(summary["decision"]["writesMt5OrderRequest"])

    def test_sim_target_execution_review_summary_ranks_release_packet_fallback_blockers(self) -> None:
        rows = _ranked_blockers(
            {"liveExecutionReview": {}},
            release_packet={
                "releaseGateSummary": {
                    "blockerCodes": [
                        "REQUEST_READER_RELEASE_TOKEN_MISSING",
                        "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                    ],
                },
            },
            cutover_review={
                "blockers": [
                    {
                        "code": "EXECUTION_MODE_GATES_NOT_ACTIVE",
                        "reasonZh": "cutover data plane ready; execution still gated",
                        "source": "liveExecutionCutoverReview",
                    },
                ],
            },
        )
        codes = [row["code"] for row in rows]
        self.assertEqual(codes[:3], [
            "EXECUTION_MODE_GATES_NOT_ACTIVE",
            "REQUEST_READER_RELEASE_TOKEN_MISSING",
            "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
        ])
        self.assertFalse(any(row.get("orderSendAllowed") for row in rows))

    def test_release_readiness_refresh_is_lightweight_and_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            startup_config = runtime / "drive_c" / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"
            startup_config.parent.mkdir(parents=True)
            startup_config.write_text(
                "\n".join([
                    "[Experts]",
                    "AllowLiveTrading=0",
                    "Enabled=1",
                    "[StartUp]",
                    "Expert=QuantGod_MT5_HFM_LiveSecondary.ex5",
                    "ExpertParameters=QuantGod_MT5_HFM_LiveSecondary.set",
                    "Symbol=#BTCUSD",
                    "Period=M15",
                ]),
                encoding="utf-8",
            )
            presets_dir = runtime / "MQL5" / "Presets"
            presets_dir.mkdir(parents=True)
            (presets_dir / "QuantGod_MT5_HFM_LiveSecondary.set").write_text(
                "\n".join([
                    "Watchlist=#BTCUSD",
                    "ReadOnlyMode=true",
                    "EnablePilotAutoTrading=false",
                    "EnablePilotRsiH1Live=false",
                    "EnableEARequestReaderReviewHarness=false",
                    "PilotStartupEntryGuardMode=H1_STRICT",
                ]),
                encoding="utf-8",
            )
            self._write_json(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json", {
                "schema": "quantgod.profit_target_tracker.v1",
                "status": "TARGET_REACHED",
                "statusZh": "已达到合计 50 USD 目标",
                "targetReached": True,
                "dualTargetReached": True,
                "target": {
                    "targetUsd": 50,
                    "aggregationMode": "ANY_LANE_OR_COMBINED_NET_PROFIT",
                },
                "combinedTarget": {
                    "targetReached": True,
                    "combinedVerifiedUsdProfit": 137.22,
                    "targetUsd": 50,
                    "qualifyingLaneIds": ["forexMt5", "btcCryptoCfd"],
                },
                "laneTargets": {
                    "forexMt5": {
                        "labelZh": "外币 MT5 模拟/纸盘",
                        "simulationVerifiedUsdProfit": 72,
                        "targetReached": True,
                        "lanePositive": True,
                        "status": "LANE_POSITIVE",
                    },
                    "btcCryptoCfd": {
                        "labelZh": "BTC / HFM crypto CFD 模拟",
                        "simulationVerifiedUsdProfit": 65.22,
                        "targetReached": True,
                        "lanePositive": True,
                        "status": "LANE_POSITIVE",
                    },
                },
            })
            refresh = build_release_readiness_refresh(runtime, write=True)

            self.assertEqual(refresh["schema"], "quantgod.release_readiness_refresh.v1")
            self.assertEqual(refresh["refreshMode"], "DISABLED_FIRST_REVIEW_ONLY")
            self.assertEqual(refresh["refreshedArtifactCount"], 5)
            self.assertEqual(refresh["status"], "MISSING")
            self.assertFalse(refresh["canReleaseExecutionNow"])
            self.assertFalse(refresh["orderSendAllowed"])
            self.assertFalse(refresh["mt5OrderSendAllowed"])
            self.assertFalse(refresh["requestFilesWritten"])
            self.assertFalse(refresh["brokerCallsMade"])
            self.assertFalse(refresh["writesMt5OrderRequest"])
            self.assertEqual(refresh["primaryActionableBlocker"]["code"], "DEPLOYED_PRESET_READ_ONLY_TRUE")
            file_blocker_codes = {row["code"] for row in refresh["fileEvidenceBlockers"]}
            self.assertIn("STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF", file_blocker_codes)
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", file_blocker_codes)
            self.assertIn("DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF", file_blocker_codes)
            self.assertTrue(refresh["executionModeFileEvidence"]["restartWouldKeepExecutionDisabled"])
            self.assertEqual(
                refresh["executionModeFileEvidence"]["startupConfig"]["values"]["AllowLiveTrading"],
                "0",
            )
            self.assertEqual(
                refresh["executionModeFileEvidence"]["deployedPreset"]["values"]["ReadOnlyMode"],
                "true",
            )
            unblock_plan = refresh["releaseUnblockPlan"]
            self.assertEqual(unblock_plan["schema"], "quantgod.release_unblock_plan.v1")
            self.assertEqual(unblock_plan["status"], "TARGET_REACHED_REVIEW_ONLY_UNBLOCK_PLAN")
            self.assertEqual(unblock_plan["combinedVerifiedUsdProfit"], 137.22)
            self.assertFalse(unblock_plan["canReleaseExecutionNow"])
            self.assertFalse(unblock_plan["orderSendAllowed"])
            self.assertFalse(unblock_plan["mt5OrderSendAllowed"])
            self.assertFalse(unblock_plan["writesMt5OrderRequest"])
            self.assertFalse(unblock_plan["requestFilesWritten"])
            self.assertFalse(unblock_plan["brokerCallsMade"])
            self.assertFalse(unblock_plan["livePresetMutationAllowed"])
            self.assertFalse(unblock_plan["startupConfigMutationAllowed"])
            self.assertFalse(unblock_plan["releaseTokenCanBeAutoMinted"])
            proposed_changes = {
                row["blockerCode"]: row for row in unblock_plan["reviewOnlyProposedFileChanges"]
            }
            self.assertEqual(
                proposed_changes["STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF"]["targetValue"],
                "1",
            )
            self.assertEqual(
                proposed_changes["DEPLOYED_PRESET_READ_ONLY_TRUE"]["targetValue"],
                "false",
            )
            self.assertTrue(all(row["requiresSeparateReview"] for row in proposed_changes.values()))
            self.assertTrue(all(row["mutationAllowedNow"] is False for row in proposed_changes.values()))
            self.assertIn("当前主 blocker", refresh["nextRequiredActionZh"])
            post_target = refresh["postTargetExecutionSummary"]
            self.assertEqual(post_target["schema"], "quantgod.post_target_execution_summary.v1")
            self.assertEqual(post_target["stage"], "TARGET_REACHED_EXECUTION_LOCKED_REVIEW_ONLY")
            self.assertEqual(post_target["profitTarget"]["combinedVerifiedUsdProfit"], 137.22)
            self.assertTrue(post_target["profitTarget"]["targetReached"])
            self.assertEqual(post_target["profitTarget"]["qualifyingLaneIds"], ["forexMt5", "btcCryptoCfd"])
            self.assertFalse(post_target["dataPlaneReady"])
            self.assertFalse(post_target["executionModeOnlyBlocked"])
            self.assertFalse(post_target["canReleaseExecutionNow"])
            self.assertFalse(post_target["orderSendAllowed"])
            self.assertFalse(post_target["mt5OrderSendAllowed"])
            self.assertFalse(post_target["writesMt5OrderRequest"])
            self.assertFalse(post_target["brokerCallsMade"])
            self.assertFalse(post_target["livePresetMutationAllowed"])
            self.assertIn("write_mt5_order_request", post_target["forbiddenUntilRelease"])
            self.assertIn("wait_for_separately_reviewed_execution_release_tokens", post_target["safeNextAutomationActions"])
            self.assertEqual(len(refresh["refreshedArtifacts"]), 5)
            self.assertTrue(release_readiness_refresh_path(runtime).exists())
            hydrated_release = read_release_readiness_refresh(runtime)
            self.assertEqual(hydrated_release["schema"], refresh["schema"])
            self.assertEqual(hydrated_release["releaseUnblockPlan"]["schema"], "quantgod.release_unblock_plan.v1")
            self.assertFalse(hydrated_release["releaseUnblockPlan"]["orderSendAllowed"])
            diff_review = build_release_minimal_diff_review(runtime, write=True)
            self.assertEqual(diff_review["schema"], "quantgod.release_minimal_diff_review.v1")
            self.assertEqual(
                diff_review["status"],
                "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW",
            )
            self.assertEqual(diff_review["combinedVerifiedUsdProfit"], 137.22)
            self.assertEqual(diff_review["releaseBlockedCount"], 0)
            self.assertGreaterEqual(diff_review["executionModeBlockedCount"], 3)
            self.assertFalse(diff_review["canApplyDiffNow"])
            self.assertFalse(diff_review["canReleaseExecutionNow"])
            self.assertFalse(diff_review["orderSendAllowed"])
            self.assertFalse(diff_review["mt5OrderSendAllowed"])
            self.assertFalse(diff_review["writesStartupConfig"])
            self.assertFalse(diff_review["writesMt5Preset"])
            self.assertFalse(diff_review["writesMt5OrderRequest"])
            self.assertFalse(diff_review["brokerCallsMade"])
            package = diff_review["reviewPackage"]
            self.assertEqual(package["schema"], "quantgod.release_minimal_diff_package.v1")
            self.assertEqual(package["mode"], "REVIEW_ONLY_MINIMAL_DIFF_NO_FILE_WRITE")
            self.assertFalse(package["candidateFileWritten"])
            self.assertFalse(package["writesStartupConfig"])
            self.assertFalse(package["writesMt5Preset"])
            self.assertFalse(package["orderSendAllowed"])
            package_changes = {row["key"]: row for row in package["proposedChanges"]}
            self.assertEqual(package_changes["AllowLiveTrading"]["to"], "1")
            self.assertEqual(package_changes["ReadOnlyMode"]["to"], "false")
            self.assertTrue(all(row["canApplyNow"] is False for row in package["proposedChanges"]))
            self.assertTrue(release_minimal_diff_review_path(runtime).exists())
            hydrated_diff_review = read_release_minimal_diff_review(runtime)
            self.assertEqual(hydrated_diff_review["schema"], diff_review["schema"])
            self.assertFalse(hydrated_diff_review["reviewPackage"]["writesMt5Preset"])
            self.assertFalse((runtime / "agent" / "mt5_order_requests").exists())
            self.assertFalse((runtime / "agent" / "mt5_order_receipts").exists())

            legacy_approval_path = runtime / "agent" / "QuantGod_LiveOperatorApprovalEvidenceReview.json"
            self._write_json(legacy_approval_path, {
                "schema": "quantgod.live_operator_approval_evidence_review.v1",
                "status": "WAITING_OPERATOR_APPROVAL_EVIDENCE",
                "operatorApprovalProvided": False,
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
            })
            hydrated_approval = read_live_operator_approval_evidence_review(runtime)
            self.assertEqual(
                hydrated_approval["authorizationBoundary"]["schema"],
                "quantgod.authorization_boundary.v1",
            )
            self.assertTrue(hydrated_approval["authorizationBoundary"]["chatAuthorizationAcknowledged"])
            self.assertFalse(hydrated_approval["authorizationBoundary"]["chatAuthorizationCanUnlockLiveExecution"])
            self.assertFalse(hydrated_approval["authorizationBoundary"]["orderSendAllowed"])

            execution_lane = build_live_execution_lane_spec(runtime, write=False)
            release_audit = execution_lane["postTargetReleaseAudit"]
            authorization_boundary = execution_lane["authorizationBoundary"]
            self.assertEqual(authorization_boundary["schema"], "quantgod.authorization_boundary.v1")
            self.assertTrue(authorization_boundary["chatAuthorizationAcknowledged"])
            self.assertFalse(authorization_boundary["chatAuthorizationCanUnlockLiveExecution"])
            self.assertFalse(authorization_boundary["operatorApprovalJsonCanUnlockLiveExecution"])
            self.assertTrue(authorization_boundary["releaseTokensStillRequired"])
            self.assertTrue(authorization_boundary["executionModeProofStillRequired"])
            self.assertFalse(authorization_boundary["canReleaseExecutionNow"])
            self.assertFalse(authorization_boundary["orderSendAllowed"])
            self.assertFalse(authorization_boundary["mt5OrderSendAllowed"])
            self.assertFalse(authorization_boundary["writesMt5OrderRequest"])
            self.assertFalse(authorization_boundary["brokerCallsMade"])
            self.assertEqual(
                release_audit["schema"],
                "quantgod.execution_lane_post_target_release_audit.v1",
            )
            self.assertEqual(release_audit["status"], "TARGET_REACHED_EXECUTION_RELEASE_BLOCKED")
            self.assertTrue(release_audit["profitTargetReached"])
            self.assertEqual(release_audit["combinedVerifiedUsdProfit"], 137.22)
            self.assertEqual(release_audit["qualifyingLaneIds"], ["forexMt5", "btcCryptoCfd"])
            self.assertEqual(release_audit["releaseBlockedCount"], 0)
            self.assertGreaterEqual(release_audit["activationBlockedCount"], 3)
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", release_audit["executionModeBlockerCodes"])
            self.assertFalse(release_audit["releaseReady"])
            self.assertFalse(release_audit["executionReady"])
            self.assertFalse(release_audit["canReleaseExecutionNow"])
            self.assertFalse(release_audit["orderSendAllowed"])
            self.assertFalse(release_audit["mt5OrderSendAllowed"])
            self.assertFalse(release_audit["writesMt5OrderRequest"])
            self.assertFalse(release_audit["brokerCallsMade"])
            self.assertFalse(release_audit["livePresetMutationAllowed"])

            legacy_execution_lane_path = runtime / "agent" / "QuantGod_LiveExecutionLaneSpec.json"
            self._write_json(legacy_execution_lane_path, {
                "schema": "quantgod.live_execution_lane_spec.v1",
                "status": "WAITING_EXECUTION_LANE_SPEC_INPUTS",
                "executionReady": False,
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
            })
            hydrated = read_live_execution_lane_spec(runtime)
            self.assertEqual(
                hydrated["postTargetReleaseAudit"]["status"],
                "TARGET_REACHED_EXECUTION_RELEASE_BLOCKED",
            )
            self.assertFalse(hydrated["postTargetReleaseAudit"]["orderSendAllowed"])
            self.assertEqual(
                hydrated["authorizationBoundary"]["schema"],
                "quantgod.authorization_boundary.v1",
            )
            self.assertFalse(hydrated["authorizationBoundary"]["canReleaseExecutionNow"])
            self.assertFalse(hydrated["authorizationBoundary"]["orderSendAllowed"])

    def test_live_execution_lane_selector_picks_nearest_review_only_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            primary_dashboard = runtime / "primary" / "QuantGod_Dashboard.json"
            self._write_json(primary_dashboard, {
                "runtime": {
                    "tradeStatus": "NEWS_BLOCK",
                    "livePilotMode": True,
                    "readOnlyMode": False,
                    "executionEnabled": True,
                    "tradeAllowed": True,
                },
                "news": {
                    "blocked": True,
                    "eventCode": "jolts-job-openings",
                    "reason": "USDJPY news pre-block: jolts-job-openings in 41m",
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USC",
                },
                "symbols": [
                    {
                        "symbol": "USDJPYc",
                        "spread": 2.3,
                        "strategies": {
                            "RSI_Reversal": {
                                "status": "WAIT_SIGNAL",
                                "reason": "Waiting for first H1 RSI evaluation",
                                "riskMultiplier": 1,
                            }
                        },
                    }
                ],
                "usdJpyRsiEntryDiagnostics": {
                    "schema": "quantgod.mt5.usdjpy_rsi_entry_diagnostics.v1",
                    "generatedAtLocal": "2026.06.02 22:56:28",
                    "generatedAtServer": "2026.06.02 16:56:28",
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "state": "NEWS_BLOCK",
                    "stateZh": "新闻过滤阻断中",
                    "summary": "USDJPY 高影响新闻过滤正在阻断新入场。",
                    "route": {
                        "candidateEnabled": True,
                        "liveEnabled": True,
                        "lastStatus": "NEWS_BLOCK",
                        "lastReason": "USDJPY news pre-block: jolts-job-openings in 41m",
                        "lastDirection": "NONE",
                    },
                    "permissions": {
                        "liveMode": True,
                        "readOnlyMode": False,
                        "tradeAllowed": True,
                        "terminalTradeAllowed": True,
                        "programTradeAllowed": True,
                        "accountTradeAllowed": True,
                        "accountExpertTradeAllowed": True,
                        "symbolTradeMode": "FULL",
                    },
                    "guards": {
                        "startupGuardActive": False,
                        "newsBlocked": True,
                        "newsReason": "USDJPY news pre-block: jolts-job-openings in 41m",
                        "spreadAllowed": True,
                        "spreadTier": "NORMAL",
                        "spreadPips": 2.3,
                        "maxSpreadPips": 2.7,
                        "portfolioPositions": 0,
                        "symbolPositions": 0,
                    },
                    "rsi": {
                        "indicatorReady": True,
                        "timeframe": "H1",
                        "period": 2,
                        "signalReady": True,
                        "signalDirection": "SELL",
                        "signalScore": 100,
                        "evalCode": "SIGNAL_SELL",
                        "evalReason": "USDJPY RSI_Reversal H1 sell setup ported from MT4",
                        "trigger": "RSI2 H1 overbought/crossback with upper Bollinger touch",
                    },
                    "whyNoEntry": [
                        {
                            "code": "NEWS_BLOCK",
                            "label": "新闻过滤阻断",
                            "detail": "USDJPY news pre-block: jolts-job-openings in 41m",
                        }
                    ],
                },
            })
            profit_target = runtime / "profit.json"
            self._write_json(profit_target, {
                "laneTargets": {
                    "forexMt5": {
                        "targetReached": True,
                        "simulationVerifiedUsdProfit": 72.0,
                        "status": "LANE_POSITIVE",
                        "statusZh": "该 lane 已证明正收益",
                        "evidence": [{"strategyId": "qg_usdjpy_h1_ema_trend_long_tp60_sl32_hold8_v1"}],
                    },
                    "btcCryptoCfd": {
                        "targetReached": True,
                        "simulationVerifiedUsdProfit": 65.22,
                        "status": "LANE_POSITIVE",
                        "statusZh": "该 lane 已证明正收益",
                        "evidence": [{"strategyId": "hfm_crypto_btc_regime_stability_shadow_v1"}],
                    },
                }
            })
            self._write_json(runtime / "agent" / "QuantGod_TpSlOptimizerReport.json", {
                "schema": "quantgod.tp_sl_optimizer.report.v1",
                "btcCryptoCfd": {
                    "finalAdvisoryPickPolicy": "STABLE_OVER_TARGET_SEEKING",
                    "finalAdvisoryPick": {
                        "strategyId": "hfm_crypto_btc_tpsl_0016",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "params": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "fullWindowMetrics": {
                            "pnlUsd": 38.7432,
                            "sharpe": 1.326,
                            "maxDrawdownPct": 1.5619,
                            "tradeCount": 69,
                            "liquidationCount": 0,
                        },
                    },
                },
            })
            startup_config = runtime / "drive_c" / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"
            startup_config.parent.mkdir(parents=True)
            startup_config.write_text(
                "\n".join([
                    "[Experts]",
                    "AllowLiveTrading=0",
                    "[StartUp]",
                    "ExpertParameters=QuantGod_MT5_HFM_LiveSecondary.set",
                ]),
                encoding="utf-8",
            )
            presets_dir = runtime / "MQL5" / "Presets"
            presets_dir.mkdir(parents=True)
            (presets_dir / "QuantGod_MT5_HFM_LiveSecondary.set").write_text(
                "\n".join([
                    "ReadOnlyMode=true",
                    "EnablePilotAutoTrading=false",
                    "EnablePilotRsiH1Live=false",
                ]),
                encoding="utf-8",
            )
            build_release_readiness_refresh(runtime, write=True)

            selector = build_live_execution_lane_selector(
                runtime,
                primary_dashboard_json=str(primary_dashboard),
                profit_target_json=str(profit_target),
                write=True,
            )

            self.assertEqual(selector["schema"], "quantgod.live_execution_lane_selector.v1")
            self.assertEqual(selector["selectedLaneId"], "forexMt5")
            self.assertFalse(selector["orderSendAllowed"])
            self.assertFalse(selector["mt5OrderSendAllowed"])
            self.assertFalse(selector["requestFilesWritten"])
            self.assertFalse(selector["brokerCallsMade"])
            self.assertTrue(live_execution_lane_selector_path(runtime).exists())
            self.assertEqual(read_live_execution_lane_selector(runtime)["selectedLaneId"], "forexMt5")
            lanes = {row["laneId"]: row for row in selector["lanes"]}
            self.assertIn("FOREX_NEWS_BLOCK_ACTIVE", {row["code"] for row in lanes["forexMt5"]["blockers"]})
            self.assertNotIn("FOREX_WAITING_STRATEGY_SIGNAL", {row["code"] for row in lanes["forexMt5"]["blockers"]})
            self.assertEqual(lanes["forexMt5"]["currentStrategy"]["status"], "NEWS_BLOCK")
            self.assertTrue(lanes["forexMt5"]["currentStrategy"]["signalReady"])
            self.assertEqual(lanes["forexMt5"]["currentStrategy"]["signalDirection"], "SELL")
            self.assertEqual(lanes["forexMt5"]["noEntryDiagnostics"]["rsi"]["evalCode"], "SIGNAL_SELL")
            self.assertEqual(lanes["forexMt5"]["noEntryDiagnostics"]["whyNoEntry"][0]["code"], "NEWS_BLOCK")
            self.assertTrue(lanes["forexMt5"]["runtimeSwitches"]["livePilotMode"])
            self.assertFalse(lanes["forexMt5"]["runtimeSwitches"]["readOnlyMode"])
            self.assertEqual(lanes["btcCryptoCfd"]["strategyCandidate"]["strategyId"], "hfm_crypto_btc_tpsl_0016")
            self.assertEqual(
                lanes["btcCryptoCfd"]["strategyCandidate"]["tpSlSummary"]["stopLossPriceMove"],
                300.0,
            )
            self.assertFalse(lanes["btcCryptoCfd"]["strategyCandidate"]["orderSendAllowed"])
            self.assertIn("DEPLOYED_PRESET_READ_ONLY_TRUE", {row["code"] for row in lanes["btcCryptoCfd"]["blockers"]})
            self.assertFalse((runtime / "agent" / "mt5_order_requests").exists())
            self.assertFalse((runtime / "agent" / "mt5_order_receipts").exists())

    def test_orchestrator_marks_operator_approval_wait_resolved_after_evidence_acceptance(self) -> None:
        artifacts = {
            "readiness": {
                "lanes": {"usdjpyMt5": {}},
            },
            "evidenceIntake": {
                "status": "HFM_REVIEW_INPUTS_PRESENT",
            },
            "hfmFilledInputValidator": {},
            "promotionCandidates": {
                "status": "READY_FOR_OPERATOR_REVIEW_PACKET",
                "reviewCandidateCount": 1,
                "nextRequiredActionZh": "生成人工审批草案，等待 operator 明确确认。",
            },
            "promotionController": {
                "status": "OPERATOR_REVIEW_PACKET_AUTOMATED",
                "statusZh": "已自动生成实盘评审包",
                "reviewAutomationRequested": True,
                "nextRequiredActionZh": "等待人工审批 JSON，然后继续 dry-run replay。",
            },
            "reviewPacket": {
                "status": "READY_FOR_OPERATOR_REVIEW",
                "statusZh": "等待操作者审查",
                "reviewCandidateCount": 1,
                "nextRequiredActionZh": "审查风险限制和最终 operator approval。",
            },
            "approvalEvidence": {
                "status": "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED",
                "statusZh": "人工审批证据已验收，但真实执行仍关闭",
                "operatorApprovalProvided": True,
                "nextRequiredActionZh": "审批证据可审计；下一步仍必须单独实现并评审真实 MT5 execution lane。",
            },
            "dryRunReplay": {},
            "runtimePreflight": {},
            "orderRequestContract": {},
            "pipeline": {},
            "adapterReview": {},
            "adapterSandbox": {},
            "adapterContractValidator": {},
        }

        rows = _stage_rows(artifacts)
        by_id = {row["stageId"]: row for row in rows}

        for stage_id in ("promotion_controller", "review_packet", "approval_evidence"):
            self.assertTrue(by_id[stage_id]["approvalWaitResolved"])
            self.assertIn("不再等待用户确认", by_id[stage_id]["nextRequiredActionZh"])
            self.assertNotIn("等待人工审批 JSON", by_id[stage_id]["nextRequiredActionZh"])
            self.assertNotIn("等待操作者审查", by_id[stage_id]["nextRequiredActionZh"])

    def test_orchestrator_rebuilds_saved_artifact_when_explicit_inputs_are_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            artifact_path = runtime / "stale.json"
            artifact_path.write_text(json.dumps({"source": "stale"}), encoding="utf-8")
            calls = {"read": 0, "build": 0}

            def read_fn(_runtime: Path) -> dict:
                calls["read"] += 1
                return {"source": "stale"}

            def build_fn(_runtime: Path, **_kwargs) -> dict:
                calls["build"] += 1
                return {"source": "rebuilt"}

            stale = _saved_or_built(
                runtime,
                artifact_path,
                read_fn,
                build_fn,
                {"refresh_sources": False},
            )
            rebuilt = _saved_or_built(
                runtime,
                artifact_path,
                read_fn,
                build_fn,
                {
                    "refresh_sources": False,
                    "operator_approval_json": str(runtime / "approval.json"),
                },
            )

            self.assertEqual(stale["source"], "stale")
            self.assertEqual(rebuilt["source"], "rebuilt")
            self.assertEqual(calls, {"read": 1, "build": 1})

    def test_hfm_crypto_profile_without_usd_pnl_cannot_enter_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases"
            btc_history = bases / "HFMarketsGlobal-Live12" / "history" / "#BTCUSD"
            btc_history.mkdir(parents=True)
            (btc_history / "2026.hcc").write_text("fixture", encoding="utf-8")
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "agt_crypto_no_usd_pnl",
                "metrics": {
                    "roi": "18.2%",
                    "sharpe": "1.6",
                    "maxDrawdown": "7.2%",
                    "liquidations": 0,
                    "trades": 48,
                },
            }), encoding="utf-8")

            payload = build_live_automation_readiness(
                runtime,
                moss_backtest_json=str(profile),
                write=False,
            )

            hfm = payload["lanes"]["hfmCryptoCfd"]
            self.assertFalse(hfm["simulationQualified"])
            self.assertFalse(hfm["simulationProfileQualified"])
            self.assertFalse(hfm["reviewCandidate"])
            codes = {row["code"] for row in hfm["reviewBlockers"]}
            self.assertIn("HFM_PNL_USD_NOT_POSITIVE", codes)
            self.assertFalse(hfm["safety"]["orderSendAllowed"])

    def test_hfm_crypto_good_profile_becomes_review_candidate_not_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases"
            btc_history = bases / "HFMarketsGlobal-Live12" / "history" / "#BTCUSD"
            btc_history.mkdir(parents=True)
            (btc_history / "2026.hcc").write_text("fixture", encoding="utf-8")
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "agt_crypto_ready",
                "metrics": {
                    "pnlUsd": 68.4,
                    "roi": "18.2%",
                    "sharpe": "1.6",
                    "maxDrawdown": "7.2%",
                    "liquidations": 0,
                    "trades": 48,
                },
            }), encoding="utf-8")

            payload = build_live_automation_readiness(
                runtime,
                moss_backtest_json=str(profile),
                write=False,
            )

            hfm = payload["lanes"]["hfmCryptoCfd"]
            self.assertTrue(hfm["simulationQualified"])
            self.assertTrue(hfm["simulationProfileQualified"])
            self.assertTrue(hfm["reviewCandidate"])
            self.assertFalse(hfm["executionReady"])
            self.assertFalse(hfm["safety"]["orderSendAllowed"])
            self.assertFalse(hfm["safety"]["copyTradeExecutionAllowed"])
            self.assertFalse(payload["canPromoteToLiveNow"])
            self.assertFalse(payload["liveExecutionAllowed"])
            self.assertFalse(payload["orderSendAllowed"])
            self.assertFalse(payload["mt5OrderSendAllowed"])
            execution_summary = payload["executionReviewSummary"]
            self.assertEqual(execution_summary["status"], "SIMULATION_READY_EXECUTION_BLOCKED")
            self.assertTrue(execution_summary["hfmCryptoReviewCandidate"])
            self.assertFalse(execution_summary["hfmCryptoExecutionSpecReady"])
            self.assertFalse(execution_summary["liveExecutionAllowed"])
            self.assertFalse(execution_summary["orderSendAllowed"])
            self.assertIn("hfmCryptoCfd", execution_summary["reviewReadyLaneIds"])
            self.assertIn("HFM_CRYPTO_EXECUTION_SPEC_REVIEW_REQUIRED", execution_summary["primaryBlockerCodes"])
            self.assertIn(
                "HFM_CRYPTO_EXECUTION_SPEC_REVIEW_REQUIRED",
                execution_summary["blockerCodesByLane"]["hfmCryptoCfd"],
            )
            self.assertIn("USD_RUNTIME_FRESH_REQUIRED", execution_summary["blockerCodesByLane"]["usdjpyMt5"])
            self.assertIn("execution lane", payload["nextRequiredActionZh"])
            codes = {row["code"] for row in hfm["reviewBlockers"]}
            self.assertIn("HFM_CRYPTO_EXECUTION_SPEC_REVIEW_REQUIRED", codes)

            review = build_live_execution_review_packet(
                runtime,
                moss_backtest_json=str(profile),
                write=False,
            )
            hfm_contract = review["contracts"]["hfmCryptoCfd"]
            self.assertEqual(review["status"], "READY_FOR_OPERATOR_REVIEW")
            self.assertTrue(hfm_contract["reviewCandidate"])
            self.assertTrue(hfm_contract["contractSpecReview"]["currentEvidence"]["simulationProfileQualified"])
            self.assertFalse(hfm_contract["dryRunOrderIntentSpec"]["writesMt5OrderRequest"])
            self.assertEqual(hfm_contract["dryRunOrderIntentSpec"]["example"]["maxNotionalUsd"], 0.0)
            self.assertIn("contract_size_and_tick_value", hfm_contract["contractSpecReview"]["requiredBeforeAnyLiveOrder"])

            approval = build_live_operator_approval_draft(
                runtime,
                moss_backtest_json=str(profile),
                write=False,
            )
            self.assertEqual(approval["status"], "WAITING_OPERATOR_APPROVAL")
            self.assertFalse(approval["operatorApprovalProvided"])
            self.assertIn("hfmCryptoCfd", approval["reviewCandidateLanes"])

            plan = build_dry_run_live_execution_plan(
                runtime,
                moss_backtest_json=str(profile),
                write=False,
            )
            self.assertEqual(plan["status"], "READY_FOR_DRY_RUN_REVIEW")
            self.assertEqual(plan["summary"]["intentCount"], 1)
            self.assertFalse(plan["mt5PendingOrderIntentsWritten"])
            self.assertFalse(plan["dryRunIntents"][0]["writesMt5OrderRequest"])
            self.assertEqual(plan["dryRunIntents"][0]["lane"], "HFM_CRYPTO_CFD")
            self.assertEqual(plan["dryRunIntents"][0]["status"], "BLOCKED_PENDING_OPERATOR_APPROVAL")

            candidates = build_live_promotion_candidates(
                runtime,
                moss_backtest_json=str(profile),
                write=False,
            )
            self.assertEqual(candidates["status"], "READY_FOR_OPERATOR_REVIEW_PACKET")
            self.assertTrue(candidates["readyForOperatorReviewPacket"])
            self.assertEqual(candidates["reviewCandidateCount"], 1)
            self.assertFalse(candidates["executionReady"])
            self.assertFalse(candidates["requestWritesAllowed"])
            self.assertFalse(candidates["brokerCallsMade"])
            hfm_candidate = next(row for row in candidates["candidateLanes"] if row["lane"] == "HFM_CRYPTO_CFD")
            self.assertTrue(hfm_candidate["canEnterLiveReviewNow"])
            self.assertFalse(hfm_candidate["canPromoteToLiveNow"])

            controller = build_live_promotion_controller(
                runtime,
                moss_backtest_json=str(profile),
                write=True,
            )
            self.assertEqual(controller["schema"], "quantgod.live_promotion_controller.v1")
            self.assertEqual(controller["status"], "OPERATOR_REVIEW_PACKET_AUTOMATED")
            self.assertTrue(controller["reviewAutomationRequested"])
            self.assertTrue(controller["reviewArtifactsWrittenByThisRun"])
            self.assertEqual(controller["eligibleLaneCount"], 1)
            self.assertFalse(controller["executionReady"])
            self.assertFalse(controller["requestWritesAllowed"])
            self.assertFalse(controller["brokerCallsMade"])
            self.assertFalse(controller["writesMt5OrderRequest"])
            run_ids = {row["artifactId"] for row in controller["reviewArtifactRuns"]}
            self.assertEqual(run_ids, {"reviewPacket", "approvalDraft", "dryRunPlan", "pipeline"})
            self.assertTrue((runtime / "agent" / "QuantGod_LivePromotionController.json").exists())

    def test_readiness_status_build_does_not_recompute_usdjpy_research(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases" / "HFMarketsGlobal-Live12" / "history" / "#BTCUSD"
            bases.mkdir(parents=True)
            (bases / "2026.hcc").write_text("fixture", encoding="utf-8")
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "agt_crypto_ready",
                "metrics": {
                    "pnlUsd": 68.4,
                    "roi": "18.2%",
                    "sharpe": "1.6",
                    "maxDrawdown": "7.2%",
                    "liquidations": 0,
                    "trades": 48,
                },
            }), encoding="utf-8")

            with mock.patch(
                "tools.live_automation_readiness.builder.build_usdjpy_policy",
                side_effect=AssertionError("USDJPY policy should be read-only in status build"),
            ) as policy_mock:
                with mock.patch(
                    "tools.live_automation_readiness.builder.build_promotion_decision",
                    side_effect=AssertionError("USDJPY promotion should be read-only in status build"),
                ) as promotion_mock:
                    payload = build_live_automation_readiness(
                        runtime,
                        moss_backtest_json=str(profile),
                        write=False,
                    )

            policy_mock.assert_not_called()
            promotion_mock.assert_not_called()
            self.assertEqual(payload["lanes"]["usdjpyMt5"]["promotionStage"], "UNKNOWN")
            self.assertTrue(payload["lanes"]["hfmCryptoCfd"]["simulationQualified"])
            self.assertFalse(payload["orderSendAllowed"])
            self.assertFalse(payload["mt5OrderSendAllowed"])

    def test_hfm_crypto_btc_profile_prefers_btc_dry_run_intent_when_many_symbols_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases" / "HFMarketsGlobal-Live12" / "history"
            for symbol in ("#AAVEUSD", "#BTCUSD", "#ETHUSD"):
                folder = bases / symbol
                folder.mkdir(parents=True)
                (folder / "2026.hcc").write_text("fixture", encoding="utf-8")
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "hfm_crypto_btc_regime_stability_shadow_v1",
                "metrics": {
                    "strategyName": "BTCUSD EMA-slope short regime stability shadow simulation",
                    "pnlUsd": 68.4,
                    "roi": "18.2%",
                    "sharpe": "1.6",
                    "maxDrawdown": "7.2%",
                    "liquidations": 0,
                    "trades": 48,
                },
            }), encoding="utf-8")

            review = build_live_execution_review_packet(
                runtime,
                moss_backtest_json=str(profile),
                write=False,
            )
            hfm_contract = review["contracts"]["hfmCryptoCfd"]
            self.assertEqual(hfm_contract["scope"]["canonicalSymbols"][0], "BTCUSD")
            self.assertEqual(hfm_contract["scope"]["brokerSymbols"][0], "#BTCUSD")
            self.assertEqual(hfm_contract["dryRunOrderIntentSpec"]["example"]["canonicalSymbol"], "BTCUSD")
            self.assertEqual(hfm_contract["dryRunOrderIntentSpec"]["example"]["brokerSymbol"], "#BTCUSD")

            plan = build_dry_run_live_execution_plan(
                runtime,
                moss_backtest_json=str(profile),
                write=False,
            )
            self.assertEqual(plan["dryRunIntents"][0]["canonicalSymbol"], "BTCUSD")
            self.assertEqual(plan["dryRunIntents"][0]["brokerSymbol"], "#BTCUSD")

    def test_hfm_account_without_crypto_symbols_blocks_live_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            specs_path = ea_symbol_specs_path(runtime)
            specs_path.parent.mkdir(parents=True)
            specs_path.write_text(json.dumps({
                "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                "source": "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA",
                "enabled": True,
                "scanAllBrokerSymbols": True,
                "brokerSymbolTotalAll": 3,
                "brokerSymbolTotalMarketWatch": 2,
                "brokerCryptoLikeCountAll": 0,
                "brokerCryptoLikeCountMarketWatch": 0,
                "brokerSymbolSampleCount": 3,
                "symbols": [],
                "brokerSymbolSamples": [
                    {"brokerSymbol": "EURUSDc", "path": "Forex", "looksLikeCrypto": False},
                    {"brokerSymbol": "USDJPYc", "path": "Forex", "looksLikeCrypto": False},
                    {"brokerSymbol": "XAUUSDc", "path": "Metals", "looksLikeCrypto": False},
                ],
                "safety": {
                    "readOnly": True,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                },
            }), encoding="utf-8")

            payload = build_live_automation_readiness(runtime, write=False)
            hfm = payload["lanes"]["hfmCryptoCfd"]

            self.assertEqual(hfm["status"], "WAITING_HFM_ACCOUNT_CRYPTO_CFD_SYMBOLS")
            self.assertEqual(hfm["statusZh"], "当前 HFM 账号未下发 Crypto CFD symbols")
            self.assertTrue(hfm["accountNoCryptoSymbols"])
            self.assertFalse(hfm["reviewCandidate"])
            self.assertFalse(hfm["executionReady"])
            self.assertFalse(hfm["safety"]["mt5OrderSendAllowed"])
            codes = [row["code"] for row in hfm["reviewBlockers"]]
            self.assertEqual(codes[0], "HFM_MT5_ACCOUNT_NO_CRYPTO_CFD_SYMBOLS")
            self.assertNotIn("HFM_CRYPTO_STANDALONE_EXPORTER_READY_TO_RUN", codes)
            self.assertIn("HFM_CRYPTO_EXECUTION_SPEC_REVIEW_REQUIRED", codes)
            availability = hfm["accountCryptoAvailability"]
            self.assertEqual(
                availability["brokerSymbolDiagnostics"]["brokerCryptoLikeCountAll"],
                0,
            )
            checklist = {row["id"]: row for row in availability["operatorChecklist"]}
            self.assertEqual(checklist["hfm_account_crypto_cfd_symbols"]["status"], "BLOCKED")
            self.assertIn("换用开通 HFM crypto CFD", hfm["nextRequiredActionZh"])

    def test_hfm_crypto_contract_spec_reduces_spec_gap_but_keeps_live_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases"
            btc_history = bases / "HFMarketsGlobal-Live12" / "history" / "#BTCUSD"
            btc_history.mkdir(parents=True)
            (btc_history / "2026.hcc").write_text("fixture", encoding="utf-8")
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "agt_crypto_ready",
                "metrics": {
                    "pnlUsd": 68.4,
                    "roi": "18.2%",
                    "sharpe": "1.6",
                    "maxDrawdown": "7.2%",
                    "liquidations": 0,
                    "trades": 48,
                },
            }), encoding="utf-8")
            spec = runtime / "hfm_crypto_specs.json"
            spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 10,
                    "spreadMaxPips": 50,
                }],
            }), encoding="utf-8")

            payload = build_live_automation_readiness(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            hfm = payload["lanes"]["hfmCryptoCfd"]
            self.assertTrue(hfm["simulationQualified"])
            self.assertTrue(hfm["simulationProfileQualified"])
            self.assertTrue(hfm["reviewCandidate"])
            self.assertTrue(hfm["executionSpecReady"])
            self.assertFalse(hfm["executionReady"])
            self.assertFalse(payload["canPromoteToLiveNow"])
            codes = {row["code"] for row in hfm["reviewBlockers"]}
            self.assertNotIn("HFM_CRYPTO_EXECUTION_SPEC_REVIEW_REQUIRED", codes)
            self.assertIn("HFM_CRYPTO_EXECUTION_LANE_REVIEW_REQUIRED", codes)

            review = build_live_execution_review_packet(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            evidence = review["contracts"]["hfmCryptoCfd"]["contractSpecReview"]["currentEvidence"]
            self.assertTrue(evidence["executionSpecReady"])
            self.assertEqual(evidence["executionSpecValidRowCount"], 1)
            self.assertFalse(review["contracts"]["hfmCryptoCfd"]["dryRunOrderIntentSpec"]["writesMt5OrderRequest"])

            intake = build_live_evidence_intake(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(intake["schema"], "quantgod.live_evidence_intake.v1")
            self.assertEqual(intake["status"], "HFM_REVIEW_INPUTS_PRESENT")
            self.assertFalse(intake["executionReady"])
            self.assertFalse(intake["requestWritesAllowed"])
            self.assertFalse(intake["brokerCallsMade"])
            checks = {row["id"]: row for row in intake["intakeChecklist"]}
            self.assertTrue(checks["hfm_crypto_symbol_evidence"]["passed"])
            self.assertTrue(checks["hfm_crypto_contract_spec"]["passed"])
            self.assertTrue(checks["hfm_crypto_simulation_profile"]["passed"])

    def test_filled_hfm_inputs_override_empty_export_and_auto_select_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            export_path = contract_spec_export_path(runtime)
            export_path.parent.mkdir(parents=True)
            export_path.write_text(json.dumps({
                "schema": "quantgod.hfm_crypto_cfd.contract_spec_export.v1",
                "status": "WAITING_HFM_CRYPTO_CONTRACT_SPEC_EXPORT",
                "readyForContractSpecReviewInput": False,
                "symbols": [],
            }), encoding="utf-8")
            filled_spec = filled_contract_spec_path(runtime)
            filled_spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#ETHUSD",
                    "canonicalSymbol": "ETHUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 3,
                    "spreadMaxPips": 60,
                }],
            }), encoding="utf-8")
            filled_profile = filled_simulation_profile_path(runtime)
            filled_profile.write_text(json.dumps({
                "agentId": "agt_filled_hfm_crypto",
                "metrics": {
                    "pnlUsd": 64.0,
                    "roiPct": 16.0,
                    "sharpe": 1.5,
                    "maxDrawdownPct": 8.0,
                    "tradeCount": 55,
                    "liquidationCount": 0,
                },
            }), encoding="utf-8")

            intake = build_live_evidence_intake(runtime, write=False)

            self.assertEqual(intake["inputs"]["effectiveContractSpecJson"], str(filled_spec))
            self.assertEqual(intake["inputs"]["effectiveContractSpecSource"], "filled_contract_spec")
            self.assertEqual(intake["inputs"]["effectiveSimulationProfileJson"], str(filled_profile))
            self.assertEqual(intake["inputs"]["effectiveSimulationProfileSource"], "filled_simulation_profile")
            self.assertEqual(intake["artifacts"]["executionSpec"]["validRowCount"], 1)
            self.assertTrue(intake["artifacts"]["filledInputValidator"]["filledInputsValid"])
            self.assertTrue(intake["artifacts"]["filledInputValidator"]["readyForEvidenceIntakeRefresh"])
            checks = {row["id"]: row for row in intake["intakeChecklist"]}
            self.assertTrue(checks["hfm_crypto_symbol_evidence"]["passed"])
            self.assertTrue(checks["hfm_crypto_contract_spec"]["passed"])
            self.assertTrue(checks["hfm_crypto_simulation_profile"]["passed"])
            self.assertFalse(intake["orderSendAllowed"])
            self.assertFalse(intake["writesMt5OrderRequest"])

            candidates = build_live_promotion_candidates(runtime, write=False)
            self.assertEqual(candidates["status"], "READY_FOR_OPERATOR_REVIEW_PACKET")
            self.assertEqual(candidates["reviewCandidateCount"], 1)
            hfm_candidate = next(row for row in candidates["candidateLanes"] if row["lane"] == "HFM_CRYPTO_CFD")
            self.assertTrue(hfm_candidate["canEnterLiveReviewNow"])
            self.assertFalse(hfm_candidate["canPromoteToLiveNow"])
            self.assertFalse(candidates["requestWritesAllowed"])
            self.assertFalse(candidates["brokerCallsMade"])

    def test_invalid_filled_hfm_inputs_do_not_pass_evidence_intake(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            filled_spec = filled_contract_spec_path(runtime)
            filled_spec.parent.mkdir(parents=True)
            filled_spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#ETHUSD",
                    "canonicalSymbol": "ETHUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 3,
                }],
            }), encoding="utf-8")
            filled_profile = filled_simulation_profile_path(runtime)
            filled_profile.write_text(json.dumps({
                "agentId": "agt_bad_hfm_crypto",
                "metrics": {
                    "roiPct": -2.0,
                    "sharpe": 0.4,
                    "maxDrawdownPct": 24.0,
                    "tradeCount": 4,
                    "liquidationCount": 1,
                },
            }), encoding="utf-8")

            intake = build_live_evidence_intake(runtime, write=False)

            self.assertEqual(intake["status"], "WAITING_HFM_LIVE_EVIDENCE_INPUTS")
            self.assertFalse(intake["artifacts"]["filledInputValidator"]["filledInputsValid"])
            checks = {row["id"]: row for row in intake["intakeChecklist"]}
            self.assertFalse(checks["hfm_crypto_symbol_evidence"]["passed"])
            self.assertFalse(checks["hfm_crypto_contract_spec"]["passed"])
            self.assertFalse(checks["hfm_crypto_simulation_profile"]["passed"])
            codes = {row["code"] for row in intake["blockers"]}
            self.assertIn("HFM_CRYPTO_CONTRACT_SPEC_MISSING", codes)
            self.assertIn("HFM_CRYPTO_SIMULATION_PROFILE_MISSING", codes)
            self.assertFalse(intake["orderSendAllowed"])
            self.assertFalse(intake["writesMt5OrderRequest"])

    def test_live_evidence_intake_exposes_runtime_preflight_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_json(runtime_preflight_path(runtime), {
                "schema": "quantgod.live_runtime_preflight_probe.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "runtimeProbePassed": True,
                "dashboardSnapshot": {
                    "fresh": False,
                    "ageSeconds": 123.4,
                    "tradeStatus": "SHADOW",
                    "livePilotMode": False,
                    "readOnlyMode": True,
                    "executionEnabled": False,
                    "tradeAllowed": False,
                    "permissionLayers": {
                        "tradePermissionBlocker": "READ_ONLY_MODE",
                    },
                },
                "probeResults": {
                    "sidecarLiveTickOk": True,
                    "spreadProbeOk": True,
                },
                "laneRuntimeChecks": [
                    {
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                    }
                ],
            })

            intake = build_live_evidence_intake(runtime, write=False)

            self.assertEqual(intake["dashboardSnapshot"]["tradeStatus"], "SHADOW")
            self.assertTrue(intake["probeResults"]["sidecarLiveTickOk"])
            self.assertEqual(intake["tradeStatus"], "SHADOW")
            self.assertFalse(intake["livePilotMode"])
            self.assertTrue(intake["readOnlyMode"])
            self.assertFalse(intake["executionEnabled"])
            self.assertFalse(intake["tradeAllowed"])
            self.assertEqual(intake["tradePermissionBlocker"], "READ_ONLY_MODE")
            self.assertEqual(intake["targetSymbols"], ["#BTCUSD"])
            self.assertIn("READ_ONLY_MODE", intake["summaryZh"])

    def test_operator_approval_evidence_can_be_validated_without_unlocking_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases"
            btc_history = bases / "HFMarketsGlobal-Live12" / "history" / "#BTCUSD"
            btc_history.mkdir(parents=True)
            (btc_history / "2026.hcc").write_text("fixture", encoding="utf-8")
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "agt_crypto_ready",
                "metrics": {
                    "pnlUsd": 68.4,
                    "roi": "18.2%",
                    "sharpe": "1.6",
                    "maxDrawdown": "7.2%",
                    "liquidations": 0,
                    "trades": 48,
                },
            }), encoding="utf-8")
            spec = runtime / "hfm_crypto_specs.json"
            spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 10,
                    "spreadMaxPips": 50,
                }],
            }), encoding="utf-8")
            draft = build_live_operator_approval_draft(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            approval_json = runtime / "operator_approval.json"
            approval_json.write_text(json.dumps({
                "operatorId": "operator_demo",
                "approvedAtIso": "2026-05-28T00:00:00Z",
                "reviewPacketHash": draft["reviewPacketHash"],
                "approvedLanes": draft["reviewCandidateLanes"],
                "maxDailyLossAck": True,
                "killSwitchAck": True,
                "credentialsExternalAck": True,
                "dryRunFirstAck": True,
                "hfmContractSpecAck": True,
                "finalHumanApprovalText": "我确认这只是审批证据审查，不会自动开启实盘下单。",
            }), encoding="utf-8")

            review = build_live_operator_approval_evidence_review(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )

            self.assertEqual(review["schema"], "quantgod.live_operator_approval_evidence_review.v1")
            self.assertEqual(review["status"], "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED")
            self.assertTrue(review["operatorApprovalProvided"])
            self.assertEqual(review["operatorApprovalId"], "operator_demo")
            self.assertEqual(review["operatorId"], "operator_demo")
            self.assertEqual(review["approvedAtIso"], "2026-05-28T00:00:00Z")
            self.assertTrue(review["approvalBoundToReviewPacket"])
            self.assertIn("hfmCryptoCfd", review["approvedLanes"])
            self.assertFalse(review["approvalCanUnlockLiveExecution"])
            self.assertFalse(review["canPromoteToLiveNow"])
            self.assertFalse(review["writesMt5OrderRequest"])
            self.assertFalse(review["mt5PendingOrderIntentsWritten"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertEqual(review["blockers"], [])

            execution_lane = build_live_execution_lane_spec(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(execution_lane["schema"], "quantgod.live_execution_lane_spec.v1")
            self.assertEqual(execution_lane["status"], "READY_FOR_EXECUTION_LANE_IMPLEMENTATION_REVIEW")
            self.assertTrue(execution_lane["readyForImplementationReview"])
            self.assertTrue(execution_lane["approvalEvidenceAccepted"])
            self.assertGreaterEqual(execution_lane["approvedDryRunIntentCount"], 1)
            self.assertFalse(execution_lane["executionReady"])
            self.assertFalse(execution_lane["implementationContract"]["orderSendAllowed"])
            self.assertFalse(execution_lane["implementationContract"]["brokerExecutionAllowed"])
            self.assertFalse(execution_lane["implementationContract"]["writesMt5OrderRequest"])
            self.assertIn("separate_execution_lane_code_review", execution_lane["implementationContract"]["requiredBeforeCodeCanWriteOrders"])
            self.assertEqual(execution_lane["blockers"], [])

            replay = build_dry_run_intent_replay(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(replay["schema"], "quantgod.live_dry_run_intent_replay.v1")
            self.assertEqual(replay["status"], "DRY_RUN_INTENT_REPLAY_ACCEPTED_EXECUTION_STILL_DISABLED")
            self.assertTrue(replay["replayPassed"])
            self.assertTrue(replay["readyForImplementationReview"])
            self.assertGreaterEqual(replay["passedIntentCount"], 1)
            self.assertFalse(replay["executionReady"])
            self.assertFalse(replay["writesMt5OrderRequest"])
            self.assertFalse(replay["mt5PendingOrderIntentsWritten"])
            self.assertFalse(replay["orderSendAllowed"])
            self.assertFalse(replay["brokerExecutionAllowed"])
            self.assertEqual(replay["blockers"], [])

            preflight = build_live_runtime_preflight_probe(runtime, write=True)
            self.assertEqual(preflight["schema"], "quantgod.live_runtime_preflight_probe.v1")
            self.assertFalse(preflight["runtimeProbePassed"])
            self.assertFalse(preflight["executionReady"])
            self.assertFalse(preflight["writesMt5OrderRequest"])
            self.assertFalse(preflight["requestFilesWritten"])
            self.assertFalse(preflight["brokerCallsMade"])
            self.assertFalse(preflight["mt5PendingOrderIntentsWritten"])
            self.assertFalse(preflight["orderSendAllowed"])
            self.assertFalse(preflight["brokerExecutionAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_LiveRuntimePreflightProbe.json").exists())
            saved_preflight = read_live_runtime_preflight_probe(runtime)
            self.assertEqual(saved_preflight["schema"], preflight["schema"])

            order_contract = build_mt5_order_request_contract(runtime, write=True)
            self.assertEqual(order_contract["schema"], "quantgod.mt5_order_request_contract.v1")
            self.assertFalse(order_contract["readyForAdapterCodeReview"])
            self.assertFalse(order_contract["executionReady"])
            self.assertFalse(order_contract["requestWritesAllowed"])
            self.assertFalse(order_contract["writesMt5OrderRequest"])
            self.assertFalse(order_contract["orderSendAllowed"])

            pipeline = build_sim_to_live_automation_pipeline(runtime, write=True)
            self.assertEqual(pipeline["schema"], "quantgod.sim_to_live_automation_pipeline.v1")
            self.assertFalse(pipeline["readyForSeparateExecutionAdapterReview"])
            self.assertFalse(pipeline["executionReady"])
            self.assertFalse(pipeline["requestWritesAllowed"])
            self.assertFalse(pipeline["writesMt5OrderRequest"])
            self.assertFalse(pipeline["operatorApprovalEvidenceAccepted"])
            self.assertEqual(
                pipeline["operatorApprovalJsonStaleOrRejected"],
                pipeline["operatorApprovalJsonProvided"],
            )

            adapter_review = build_execution_adapter_review(runtime, write=True)
            self.assertEqual(adapter_review["schema"], "quantgod.execution_adapter_review.v1")
            self.assertFalse(adapter_review["readyForExecutionAdapterCodeReview"])
            self.assertFalse(adapter_review["executionReady"])
            self.assertFalse(adapter_review["requestFilesWritten"])
            self.assertFalse(adapter_review["brokerCallsMade"])

            saved = read_live_operator_approval_evidence_review(runtime)
            self.assertEqual(saved["schema"], review["schema"])

    def test_pipeline_marks_stale_operator_approval_json_as_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases"
            btc_history = bases / "HFMarketsGlobal-Live12" / "history" / "#BTCUSD"
            btc_history.mkdir(parents=True)
            (btc_history / "2026.hcc").write_text("fixture", encoding="utf-8")
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "agt_crypto_ready",
                "metrics": {
                    "pnlUsd": 68.4,
                    "roi": "18.2%",
                    "sharpe": "1.6",
                    "maxDrawdown": "7.2%",
                    "liquidations": 0,
                    "trades": 48,
                },
            }), encoding="utf-8")
            spec = runtime / "hfm_crypto_specs.json"
            spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 10,
                    "spreadMaxPips": 50,
                }],
            }), encoding="utf-8")
            draft = build_live_operator_approval_draft(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            approval_json = runtime / "operator_approval_stale.json"
            approval_json.write_text(json.dumps({
                "operatorId": "operator_demo",
                "approvedAtIso": "2026-05-28T00:00:00Z",
                "reviewPacketHash": f"stale-{draft['reviewPacketHash']}",
                "approvedLanes": draft["reviewCandidateLanes"],
                "maxDailyLossAck": True,
                "killSwitchAck": True,
                "credentialsExternalAck": True,
                "dryRunFirstAck": True,
                "hfmContractSpecAck": True,
                "finalHumanApprovalText": "我确认这只是审批证据审查，不会自动开启实盘下单。",
            }), encoding="utf-8")

            pipeline = build_sim_to_live_automation_pipeline(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )

            self.assertTrue(pipeline["operatorApprovalJsonProvided"])
            self.assertFalse(pipeline["operatorApprovalEvidenceAccepted"])
            self.assertTrue(pipeline["operatorApprovalJsonStaleOrRejected"])
            self.assertEqual(pipeline["operatorApprovalReviewPacketHash"], draft["reviewPacketHash"])
            self.assertEqual(pipeline["operatorApprovalProvidedReviewPacketHash"], f"stale-{draft['reviewPacketHash']}")
            self.assertFalse(pipeline["operatorApprovalBoundToReviewPacket"])
            stage_codes = {
                code
                for stage in pipeline["stages"]
                for code in stage.get("blockerCodes", [])
            }
            self.assertIn("REVIEW_PACKET_HASH_MISMATCH", stage_codes)
            self.assertFalse(pipeline["orderSendAllowed"])
            self.assertFalse(pipeline["writesMt5OrderRequest"])
            self.assertFalse(pipeline["brokerExecutionAllowed"])

    def test_runtime_preflight_uses_hfm_sidecar_specs_without_passing_unselected_btc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "hfm_crypto_btc_regime_stability_shadow_v1",
                "metrics": {
                    "strategyName": "BTCUSD EMA-slope short regime stability shadow simulation",
                    "pnlUsd": 61.8,
                    "roi": "6.3%",
                    "sharpe": "1.9",
                    "maxDrawdown": "2.1%",
                    "liquidations": 0,
                    "trades": 35,
                },
            }), encoding="utf-8")
            spec = runtime / "hfm_crypto_specs.json"
            spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 50,
                    "spreadMaxPips": 50,
                }],
            }), encoding="utf-8")
            sidecar = {
                "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "tradeEnabled": True,
                    "visible": False,
                    "selected": False,
                    "tickOk": False,
                    "bid": 0,
                    "ask": 0,
                    "spread": 0,
                    "volumeMin": 0.01,
                    "volumeMax": 50,
                    "volumeStep": 0.01,
                }],
            }
            ea_symbol_specs_path(runtime).parent.mkdir(parents=True, exist_ok=True)
            ea_symbol_specs_path(runtime).write_text(json.dumps(sidecar), encoding="utf-8")
            contract_spec_export_path(runtime).write_text(json.dumps(sidecar), encoding="utf-8")
            dashboard = {
                "timestamp": "2026.05.28 12:00:00",
                "runtime": {
                    "tradeStatus": "READY",
                    "executionEnabled": True,
                    "readOnlyMode": False,
                    "livePilotMode": True,
                    "pilotKillSwitch": False,
                    "tradeAllowed": True,
                    "tickAgeSeconds": 2,
                },
                "account": {
                    "number": 198135388,
                    "server": "HFMarketsGlobal-Live16",
                    "currency": "USD",
                },
                "symbols": [{
                    "symbol": "USDJPY",
                    "canonicalSymbol": "USDJPY",
                    "bid": 157.0,
                    "ask": 157.055,
                    "spreadPoints": 55,
                }],
            }
            (runtime / "QuantGod_Dashboard.json").write_text(json.dumps(dashboard), encoding="utf-8")
            draft = build_live_operator_approval_draft(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            approval_json = runtime / "operator_approval.json"
            approval_json.write_text(json.dumps({
                "operatorId": "operator_demo",
                "approvedAtIso": "2026-05-28T00:00:00Z",
                "reviewPacketHash": draft["reviewPacketHash"],
                "approvedLanes": draft["reviewCandidateLanes"],
                "maxDailyLossAck": True,
                "killSwitchAck": True,
                "credentialsExternalAck": True,
                "dryRunFirstAck": True,
                "hfmContractSpecAck": True,
                "finalHumanApprovalText": "我确认这只是审批证据审查，不会自动开启实盘下单。",
            }), encoding="utf-8")

            preflight = build_live_runtime_preflight_probe(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )

            self.assertFalse(preflight["runtimeProbePassed"])
            self.assertFalse(preflight["dataPlaneReadyForLivePilotReview"])
            self.assertFalse(preflight["executionModeOnlyBlocked"])
            self.assertFalse(preflight["executionReady"])
            self.assertFalse(preflight["orderSendAllowed"])
            self.assertTrue(preflight["probeResults"]["symbolMappingOk"])
            self.assertTrue(preflight["probeResults"]["symbolSidecarSpecOk"])
            self.assertFalse(preflight["probeResults"]["symbolSelectedInDashboardOk"])
            self.assertFalse(preflight["probeResults"]["spreadProbeOk"])
            codes = {row["code"] for row in preflight["blockers"]}
            self.assertIn("MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD", codes)
            self.assertIn("MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING", codes)
            self.assertNotIn("MT5_SYMBOL_NOT_IN_RUNTIME_SNAPSHOT", codes)
            self.assertEqual(len(preflight["laneRuntimeChecks"]), 1)
            check = preflight["laneRuntimeChecks"][0]
            self.assertEqual(check["brokerSymbol"], "#BTCUSD")
            self.assertTrue(check["symbolPresentInSidecarSpecs"])
            self.assertTrue(check["symbolMappingOk"])
            self.assertFalse(check["symbolPresentInSnapshot"])
            self.assertFalse(check["sidecarLiveTickPresent"])
            self.assertFalse(check["passed"])
            order_contract = build_mt5_order_request_contract(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertFalse(order_contract["readyForAdapterCodeReview"])
            lane_contract = order_contract["laneContracts"][0]
            self.assertEqual(lane_contract["brokerSymbol"], "#BTCUSD")
            self.assertTrue(lane_contract["symbolPresentInSidecarSpecs"])
            self.assertTrue(lane_contract["symbolMappingOk"])
            self.assertFalse(lane_contract["symbolPresentInSnapshot"])
            self.assertFalse(lane_contract["symbolPresentInRuntimeProbe"])
            self.assertFalse(lane_contract["sidecarLiveTickPresent"])
            self.assertFalse(lane_contract["spreadFieldPresent"])
            self.assertTrue(lane_contract["riskLimitsPresent"])
            self.assertFalse(lane_contract["passed"])

    def test_runtime_preflight_accepts_fresh_hfm_crypto_runtime_probe_tick(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "hfm_crypto_btc_regime_stability_shadow_v1",
                "metrics": {
                    "strategyName": "BTCUSD EMA-slope short regime stability shadow simulation",
                    "pnlUsd": 63.5,
                    "roi": "6.8%",
                    "sharpe": "2.1",
                    "maxDrawdown": "2.5%",
                    "liquidations": 0,
                    "trades": 42,
                },
            }), encoding="utf-8")
            spec = runtime / "hfm_crypto_specs.json"
            spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 50,
                    "spreadMaxPips": 50,
                }],
            }), encoding="utf-8")
            (runtime / "hfm_crypto").mkdir(parents=True)
            (runtime / "hfm_crypto" / "QuantGod_HFMCryptoRuntimeProbe.json").write_text(json.dumps({
                "schema": "quantgod.mql5.hfm_crypto_runtime_probe.v1",
                "source": "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA_RUNTIME_PROBE",
                "chartSymbol": "#BTCUSD",
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "symbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "source": "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA_RUNTIME_PROBE",
                    "selected": True,
                    "tickOk": True,
                    "bid": 65000.0,
                    "ask": 65012.5,
                    "spreadPoints": 1250,
                    "tradeMode": 4,
                    "tradeEnabled": True,
                }],
                "safety": {
                    "readOnly": True,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                },
            }), encoding="utf-8")
            dashboard = {
                "timestamp": "2026.05.28 12:00:00",
                "runtime": {
                    "tradeStatus": "READY",
                    "executionEnabled": True,
                    "readOnlyMode": False,
                    "livePilotMode": True,
                    "pilotKillSwitch": False,
                    "tradeAllowed": True,
                    "tickAgeSeconds": 2,
                },
                "account": {
                    "number": 198135388,
                    "server": "HFMarketsGlobal-Live16",
                    "currency": "USD",
                },
                "symbols": [{
                    "symbol": "USDJPY",
                    "canonicalSymbol": "USDJPY",
                    "bid": 157.0,
                    "ask": 157.055,
                    "spreadPoints": 55,
                }],
            }
            (runtime / "QuantGod_Dashboard.json").write_text(json.dumps(dashboard), encoding="utf-8")
            draft = build_live_operator_approval_draft(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            approval_json = runtime / "operator_approval.json"
            approval_json.write_text(json.dumps({
                "operatorId": "operator_demo",
                "approvedAtIso": "2026-05-28T00:00:00Z",
                "reviewPacketHash": draft["reviewPacketHash"],
                "approvedLanes": draft["reviewCandidateLanes"],
                "maxDailyLossAck": True,
                "killSwitchAck": True,
                "credentialsExternalAck": True,
                "dryRunFirstAck": True,
                "hfmContractSpecAck": True,
                "finalHumanApprovalText": "我确认这只是审批证据审查，不会自动开启实盘下单。",
            }), encoding="utf-8")

            preflight = build_live_runtime_preflight_probe(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )

            self.assertTrue(preflight["runtimeProbePassed"])
            self.assertTrue(preflight["dataPlaneReadyForLivePilotReview"])
            self.assertTrue(preflight["executionModeReady"])
            self.assertFalse(preflight["executionModeOnlyBlocked"])
            self.assertTrue(preflight["probeResults"]["symbolMappingOk"])
            self.assertFalse(preflight["probeResults"]["symbolSelectedInDashboardOk"])
            self.assertTrue(preflight["probeResults"]["symbolRuntimeProbeOk"])
            self.assertTrue(preflight["probeResults"]["sidecarLiveTickOk"])
            self.assertTrue(preflight["probeResults"]["spreadProbeOk"])
            self.assertEqual(preflight["blockers"], [])
            check = preflight["laneRuntimeChecks"][0]
            self.assertTrue(check["symbolPresentInRuntimeProbe"])
            self.assertTrue(check["sidecarLiveTickPresent"])
            self.assertTrue(check["runtimeProbeFresh"])
            self.assertTrue(check["passed"])

    def test_runtime_preflight_prefers_external_fresh_hfm_crypto_probe_over_local_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "hfm_crypto_btc_regime_stability_shadow_v1",
                "metrics": {
                    "strategyName": "BTCUSD EMA-slope short regime stability shadow simulation",
                    "pnlUsd": 64.2,
                    "roi": "7.1%",
                    "sharpe": "2.2",
                    "maxDrawdown": "2.4%",
                    "liquidations": 0,
                    "trades": 44,
                },
            }), encoding="utf-8")
            spec = runtime / "hfm_crypto_specs.json"
            spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 50,
                    "spreadMaxPips": 50,
                }],
            }), encoding="utf-8")
            dashboard = {
                "timestamp": "2026.05.28 12:00:00",
                "runtime": {
                    "tradeStatus": "READY",
                    "executionEnabled": True,
                    "readOnlyMode": False,
                    "livePilotMode": True,
                    "pilotKillSwitch": False,
                    "tradeAllowed": True,
                    "tickAgeSeconds": 2,
                },
                "account": {
                    "number": 198135388,
                    "server": "HFMarketsGlobal-Live16",
                    "currency": "USD",
                },
                "symbols": [{
                    "symbol": "USDJPY",
                    "canonicalSymbol": "USDJPY",
                    "bid": 157.0,
                    "ask": 157.055,
                    "spreadPoints": 55,
                }],
            }
            (runtime / "QuantGod_Dashboard.json").write_text(json.dumps(dashboard), encoding="utf-8")
            stale_dir = runtime / "hfm_crypto"
            stale_dir.mkdir(parents=True)
            stale_probe = stale_dir / "QuantGod_HFMCryptoRuntimeProbe.json"
            stale_probe.write_text(json.dumps({
                "schema": "quantgod.mql5.hfm_crypto_runtime_probe.v1",
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "symbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "selected": True,
                    "tickOk": True,
                    "bid": 0,
                    "ask": 0,
                    "spreadPoints": 0,
                }],
            }), encoding="utf-8")
            stale_mtime = time.time() - 600
            os.utime(stale_probe, (stale_mtime, stale_mtime))

            external_files = runtime / "live16_files"
            external_probe_dir = external_files / "hfm_crypto"
            external_probe_dir.mkdir(parents=True)
            external_dashboard = external_files / "QuantGod_Dashboard.json"
            external_dashboard.write_text(json.dumps({
                "timestamp": "2026.05.28 12:00:05",
                "runtime": {
                    "tradeStatus": "READY",
                    "executionEnabled": True,
                    "readOnlyMode": False,
                    "livePilotMode": True,
                    "pilotKillSwitch": False,
                    "tradeAllowed": True,
                    "tickAgeSeconds": 1,
                },
                "account": {
                    "number": 198135388,
                    "server": "HFMarketsGlobal-Live16",
                    "currency": "USD",
                },
                "symbols": [{
                    "symbol": "#BTCUSD",
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "bid": 65000.0,
                    "ask": 65010.0,
                    "spreadPoints": 1000,
                    "entryTradeAllowed": True,
                }],
            }), encoding="utf-8")
            external_probe = external_probe_dir / "QuantGod_HFMCryptoRuntimeProbe.json"
            external_probe.write_text(json.dumps({
                "schema": "quantgod.mql5.hfm_crypto_runtime_probe.v1",
                "source": "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA_RUNTIME_PROBE",
                "chartSymbol": "#BTCUSD",
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "symbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "source": "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA_RUNTIME_PROBE",
                    "selected": True,
                    "tickOk": True,
                    "bid": 65000.0,
                    "ask": 65010.0,
                    "spreadPoints": 1000,
                    "tradeMode": 4,
                    "tradeEnabled": True,
                }],
                "safety": {
                    "readOnly": True,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                },
            }), encoding="utf-8")

            draft = build_live_operator_approval_draft(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            approval_json = runtime / "operator_approval.json"
            approval_json.write_text(json.dumps({
                "operatorId": "operator_demo",
                "approvedAtIso": "2026-05-28T00:00:00Z",
                "reviewPacketHash": draft["reviewPacketHash"],
                "approvedLanes": draft["reviewCandidateLanes"],
                "maxDailyLossAck": True,
                "killSwitchAck": True,
                "credentialsExternalAck": True,
                "dryRunFirstAck": True,
                "hfmContractSpecAck": True,
                "finalHumanApprovalText": "我确认这只是审批证据审查，不会自动开启实盘下单。",
            }), encoding="utf-8")

            previous_env = os.environ.get("QG_HFM_CRYPTO_RUNTIME_DIR")
            os.environ["QG_HFM_CRYPTO_RUNTIME_DIR"] = str(external_files)
            try:
                preflight = build_live_runtime_preflight_probe(
                    runtime,
                    operator_approval_json=str(approval_json),
                    moss_backtest_json=str(profile),
                    hfm_contract_spec_json=str(spec),
                    write=False,
                )
            finally:
                if previous_env is None:
                    os.environ.pop("QG_HFM_CRYPTO_RUNTIME_DIR", None)
                else:
                    os.environ["QG_HFM_CRYPTO_RUNTIME_DIR"] = previous_env

            self.assertTrue(preflight["runtimeProbePassed"])
            self.assertTrue(preflight["probeResults"]["symbolRuntimeProbeOk"])
            self.assertTrue(preflight["probeResults"]["sidecarLiveTickOk"])
            self.assertEqual(preflight["blockers"], [])
            self.assertIn(str(external_dashboard), preflight["dashboardSnapshot"]["path"])
            check = preflight["laneRuntimeChecks"][0]
            self.assertTrue(check["symbolPresentInRuntimeProbe"])
            self.assertTrue(check["sidecarLiveTickPresent"])
            self.assertTrue(check["runtimeProbeFresh"])
            self.assertIn(str(external_probe), check["runtimeProbeSource"])
            self.assertTrue(check["passed"])

    def test_runtime_preflight_accepts_fresh_dashboard_without_unlocking_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases"
            btc_history = bases / "HFMarketsGlobal-Live12" / "history" / "#BTCUSD"
            btc_history.mkdir(parents=True)
            (btc_history / "2026.hcc").write_text("fixture", encoding="utf-8")
            profile = runtime / "moss_backtest.json"
            profile.write_text(json.dumps({
                "agentId": "agt_crypto_ready",
                "metrics": {
                    "pnlUsd": 68.4,
                    "roi": "18.2%",
                    "sharpe": "1.6",
                    "maxDrawdown": "7.2%",
                    "liquidations": 0,
                    "trades": 48,
                },
            }), encoding="utf-8")
            spec = runtime / "hfm_crypto_specs.json"
            spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 10,
                    "spreadMaxPips": 50,
                }],
            }), encoding="utf-8")
            live_dashboard = {
                "timestamp": "2026.05.28 12:00:00",
                "runtime": {
                    "tradeStatus": "READY",
                    "executionEnabled": True,
                    "readOnlyMode": False,
                    "livePilotMode": True,
                    "pilotKillSwitch": False,
                    "tradeAllowed": True,
                    "tickAgeSeconds": 3,
                },
                "account": {
                    "number": 123456,
                    "server": "HFMarketsGlobal-Live12",
                    "currency": "USD",
                },
                "symbols": [{
                    "symbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "bid": 65000.0,
                    "ask": 65010.0,
                    "spreadPoints": 10.0,
                }],
            }

            def refresh_live_dashboard() -> None:
                (runtime / "QuantGod_Dashboard.json").write_text(json.dumps(live_dashboard), encoding="utf-8")

            refresh_live_dashboard()
            draft = build_live_operator_approval_draft(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            approval_json = runtime / "operator_approval.json"
            approval_json.write_text(json.dumps({
                "operatorId": "operator_demo",
                "approvedAtIso": "2026-05-28T00:00:00Z",
                "reviewPacketHash": draft["reviewPacketHash"],
                "approvedLanes": draft["reviewCandidateLanes"],
                "maxDailyLossAck": True,
                "killSwitchAck": True,
                "credentialsExternalAck": True,
                "dryRunFirstAck": True,
                "hfmContractSpecAck": True,
                "finalHumanApprovalText": "我确认这只是审批证据审查，不会自动开启实盘下单。",
            }), encoding="utf-8")

            shadow_dashboard = {
                **live_dashboard,
                "runtime": {
                    **live_dashboard["runtime"],
                    "tradeStatus": "SHADOW",
                    "executionEnabled": False,
                    "readOnlyMode": True,
                    "livePilotMode": False,
                    "tradeAllowed": False,
                },
            }
            def refresh_shadow_dashboard() -> None:
                (runtime / "QuantGod_Dashboard.json").write_text(json.dumps(shadow_dashboard), encoding="utf-8")

            refresh_shadow_dashboard()
            shadow_preflight = build_live_runtime_preflight_probe(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertFalse(shadow_preflight["runtimeProbePassed"])
            self.assertEqual(shadow_preflight["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_preflight["dataPlaneReadyForLivePilotReview"])
            self.assertFalse(shadow_preflight["executionModeReady"])
            self.assertTrue(shadow_preflight["executionModeOnlyBlocked"])
            shadow_codes = {row["code"] for row in shadow_preflight["blockers"]}
            self.assertIn("MT5_LIVE_PILOT_MODE_NOT_CONFIRMED", shadow_codes)
            self.assertIn("MT5_READ_ONLY_MODE_STILL_ACTIVE", shadow_codes)
            self.assertIn("MT5_EXECUTION_NOT_ENABLED_FOR_PILOT", shadow_codes)
            self.assertIn("MT5_TRADE_ALLOWED_NOT_CONFIRMED", shadow_codes)
            self.assertEqual(shadow_preflight["nonExecutionBlockers"], [])
            self.assertEqual(len(shadow_preflight["executionModeBlockers"]), 4)
            self.assertFalse(shadow_preflight["orderSendAllowed"])
            self.assertFalse(shadow_preflight["requestFilesWritten"])
            self.assertFalse(shadow_preflight["brokerCallsMade"])
            shadow_order_contract = build_mt5_order_request_contract(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_order_contract["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertEqual(shadow_order_contract["statusZh"], "数据面已通过，等待执行模式闸门")
            self.assertTrue(shadow_order_contract["runtimePreflightDataPlaneReadyForReview"])
            self.assertTrue(shadow_order_contract["runtimePreflightExecutionModeOnlyBlocked"])
            self.assertEqual(shadow_order_contract["runtimePreflightNonExecutionBlockers"], [])
            shadow_contract_codes = {row["code"] for row in shadow_order_contract["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_contract_codes)
            self.assertIn("MT5_LIVE_PILOT_MODE_NOT_CONFIRMED", shadow_contract_codes)
            self.assertNotIn("RUNTIME_PREFLIGHT_NOT_PASSED", shadow_contract_codes)
            self.assertFalse(shadow_order_contract["readyForAdapterCodeReview"])
            self.assertFalse(shadow_order_contract["orderSendAllowed"])

            shadow_intake = build_live_evidence_intake(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            shadow_intake_codes = {row["code"] for row in shadow_intake["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_intake_codes)
            self.assertNotIn("RUNTIME_PREFLIGHT_MISSING", shadow_intake_codes)
            self.assertNotIn("ORDER_REQUEST_CONTRACT_MISSING", shadow_intake_codes)

            shadow_orchestrator = build_sim_to_live_orchestrator(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_orchestrator["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_orchestrator["dataPlaneOrchestratorReady"])
            self.assertTrue(shadow_orchestrator["executionModeOnlyBlocked"])
            self.assertFalse(shadow_orchestrator["allExecutionActivationGatesPassed"])
            self.assertEqual(shadow_orchestrator["executionActivationGateSummary"]["blocked"], 4)
            self.assertFalse(shadow_orchestrator["allExecutionReleaseTokensProvided"])
            self.assertGreaterEqual(shadow_orchestrator["executionReleaseGateSummary"]["blocked"], 3)
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", shadow_orchestrator["executionReleaseGateSummary"]["blockerCodes"])
            release_packet = shadow_orchestrator["executionReleaseReadinessPacket"]
            self.assertEqual(release_packet["status"], "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE")
            self.assertFalse(release_packet["canReleaseExecutionNow"])
            self.assertFalse(release_packet["orderSendAllowed"])
            self.assertFalse(release_packet["requestFilesWritten"])
            self.assertFalse(release_packet["brokerCallsMade"])
            self.assertIn("broker_order_send_release", release_packet["blockedGateIds"])
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", release_packet["blockedReleaseTokenCodes"])
            self.assertTrue(all(not row["sideEffectAllowedNow"] for row in release_packet["gates"]))
            release_by_id = {row["gateId"]: row for row in shadow_orchestrator["executionReleaseGateChecklist"]}
            self.assertEqual(release_by_id["broker_order_send_release"]["tokenProvided"], False)
            self.assertEqual(release_by_id["broker_order_send_release"]["blockerCode"], "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING")
            gate_by_field = {row["field"]: row for row in shadow_orchestrator["executionActivationGateChecklist"]}
            self.assertEqual(set(gate_by_field), {"livePilotMode", "readOnlyMode", "executionEnabled", "tradeAllowed"})
            self.assertEqual(gate_by_field["livePilotMode"]["current"], False)
            self.assertEqual(gate_by_field["livePilotMode"]["expected"], True)
            self.assertEqual(gate_by_field["livePilotMode"]["blockerCode"], "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED")
            self.assertEqual(gate_by_field["readOnlyMode"]["current"], True)
            self.assertEqual(gate_by_field["readOnlyMode"]["expected"], False)
            self.assertEqual(gate_by_field["readOnlyMode"]["blockerCode"], "MT5_READ_ONLY_MODE_STILL_ACTIVE")
            self.assertTrue(all(not row["passed"] for row in shadow_orchestrator["executionActivationGateChecklist"]))
            shadow_input_stage = next(row for row in shadow_orchestrator["stages"] if row["stageId"] == "input_source")
            self.assertTrue(shadow_input_stage["passed"])
            self.assertEqual(shadow_input_stage["blockerCodes"], [])
            shadow_orchestrator_codes = {row["code"] for row in shadow_orchestrator["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_orchestrator_codes)
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", shadow_orchestrator_codes)
            self.assertNotIn("RUNTIME_PREFLIGHT_MISSING", shadow_orchestrator_codes)
            self.assertNotIn("ORDER_REQUEST_CONTRACT_MISSING", shadow_orchestrator_codes)

            build_sim_to_live_orchestrator(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            refresh_shadow_dashboard()
            reused_approval_orchestrator = build_sim_to_live_orchestrator(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                refresh_sources=True,
                write=False,
            )
            self.assertEqual(reused_approval_orchestrator["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(reused_approval_orchestrator["dataPlaneOrchestratorReady"])
            self.assertTrue(reused_approval_orchestrator["executionModeOnlyBlocked"])
            self.assertTrue(reused_approval_orchestrator["operatorApprovalJsonProvided"])
            self.assertTrue(reused_approval_orchestrator["operatorApprovalJsonReusedFromPriorEvidence"])
            self.assertEqual(
                reused_approval_orchestrator["operatorApprovalJsonRefreshContext"]["mode"],
                "reused_prior_accepted_evidence",
            )
            self.assertFalse(reused_approval_orchestrator["orderSendAllowed"])
            self.assertFalse(reused_approval_orchestrator["writesMt5OrderRequest"])

            refresh_shadow_dashboard()
            reused_approval_pipeline = build_sim_to_live_automation_pipeline(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                refresh_sources=True,
                write=False,
            )
            self.assertEqual(reused_approval_pipeline["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(reused_approval_pipeline["dataPlanePipelineReady"])
            self.assertTrue(reused_approval_pipeline["executionModeOnlyBlocked"])
            self.assertTrue(reused_approval_pipeline["operatorApprovalJsonProvided"])
            self.assertTrue(reused_approval_pipeline["operatorApprovalJsonReusedFromPriorEvidence"])
            self.assertFalse(reused_approval_pipeline["orderSendAllowed"])
            self.assertFalse(reused_approval_pipeline["writesMt5OrderRequest"])

            refresh_shadow_dashboard()
            reused_approval_harness = build_execution_adapter_harness(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                refresh_sources=True,
                write=False,
            )
            self.assertEqual(reused_approval_harness["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(reused_approval_harness["dataPlaneHarnessReady"])
            self.assertTrue(reused_approval_harness["executionModeOnlyBlocked"])
            self.assertTrue(reused_approval_harness["operatorApprovalJsonProvided"])
            self.assertTrue(reused_approval_harness["operatorApprovalJsonReusedFromPriorEvidence"])
            self.assertFalse(reused_approval_harness["orderSendAllowed"])
            self.assertFalse(reused_approval_harness["writesMt5OrderRequest"])
            self.assertFalse(reused_approval_harness["requestFilesWritten"])

            refresh_shadow_dashboard()
            reused_approval_activation = build_live_pilot_activation_review(
                runtime,
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                refresh_sources=True,
                write=False,
            )
            self.assertEqual(reused_approval_activation["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(reused_approval_activation["dataPlaneActivationReady"])
            self.assertTrue(reused_approval_activation["executionModeOnlyBlocked"])
            self.assertTrue(reused_approval_activation["operatorApprovalJsonProvided"])
            self.assertTrue(reused_approval_activation["operatorApprovalJsonReusedFromPriorEvidence"])
            self.assertFalse(reused_approval_activation["orderSendAllowed"])
            self.assertFalse(reused_approval_activation["writesMt5OrderRequest"])
            self.assertFalse(reused_approval_activation["requestFilesWritten"])

            refresh_shadow_dashboard()
            shadow_pipeline = build_sim_to_live_automation_pipeline(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_pipeline["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_pipeline["dataPlanePipelineReady"])
            self.assertTrue(shadow_pipeline["executionModeOnlyBlocked"])
            self.assertFalse(shadow_pipeline["readyForSeparateExecutionAdapterReview"])
            shadow_pipeline_codes = {row["code"] for row in shadow_pipeline["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_pipeline_codes)
            self.assertNotIn("PIPELINE_STAGE_NOT_PASSED", shadow_pipeline_codes)
            self.assertFalse(shadow_pipeline["orderSendAllowed"])
            self.assertFalse(shadow_pipeline["writesMt5OrderRequest"])

            shadow_adapter_review = build_execution_adapter_review(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_adapter_review["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_adapter_review["dataPlaneAdapterReviewReady"])
            self.assertTrue(shadow_adapter_review["executionModeOnlyBlocked"])
            self.assertFalse(shadow_adapter_review["readyForExecutionAdapterCodeReview"])
            shadow_adapter_review_codes = {row["code"] for row in shadow_adapter_review["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_adapter_review_codes)
            self.assertNotIn("SIM_TO_LIVE_PIPELINE_NOT_READY", shadow_adapter_review_codes)
            self.assertNotIn("ORDER_REQUEST_CONTRACT_NOT_READY", shadow_adapter_review_codes)
            self.assertFalse(shadow_adapter_review["orderSendAllowed"])
            self.assertFalse(shadow_adapter_review["writesMt5OrderRequest"])

            shadow_sandbox = build_adapter_sandbox_review_bundle(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_sandbox["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_sandbox["dataPlaneSandboxReady"])
            self.assertTrue(shadow_sandbox["executionModeOnlyBlocked"])
            self.assertFalse(shadow_sandbox["sandboxReadyForCodeReview"])
            self.assertGreaterEqual(shadow_sandbox["sampleRequestCount"], 1)
            shadow_sandbox_codes = {row["code"] for row in shadow_sandbox["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_sandbox_codes)
            self.assertNotIn("ADAPTER_REVIEW_NOT_READY", shadow_sandbox_codes)
            self.assertNotIn("ORDER_REQUEST_CONTRACT_NOT_READY", shadow_sandbox_codes)
            self.assertFalse(shadow_sandbox["orderSendAllowed"])
            self.assertFalse(shadow_sandbox["writesMt5OrderRequest"])

            shadow_validator = build_adapter_contract_validator(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_validator["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_validator["sampleValidationPassed"])
            self.assertTrue(shadow_validator["dataPlaneValidationReady"])
            self.assertTrue(shadow_validator["contractExecutionModeOnlyBlocked"])
            self.assertFalse(shadow_validator["validationPassed"])
            shadow_validator_codes = {row["code"] for row in shadow_validator["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_validator_codes)
            self.assertNotIn("ORDER_REQUEST_CONTRACT_NOT_READY", shadow_validator_codes)
            self.assertNotIn("ADAPTER_VALIDATOR_REQUEST_FAILED", shadow_validator_codes)
            self.assertTrue(all(row["runtimePreflightHashCurrent"] for row in shadow_validator["validationResults"]))
            self.assertTrue(all("runtimePreflightHash:STALE" not in row["fieldErrors"] for row in shadow_validator["validationResults"]))
            refresh_shadow_dashboard()
            shadow_validator_refresh = build_adapter_contract_validator(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                refresh_sources=True,
                write=False,
            )
            self.assertEqual(shadow_validator_refresh["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_validator_refresh["sampleValidationPassed"])
            self.assertTrue(shadow_validator_refresh["dataPlaneValidationReady"])
            self.assertTrue(all(row["runtimePreflightHashCurrent"] for row in shadow_validator_refresh["validationResults"]))
            self.assertTrue(all("runtimePreflightHash:STALE" not in row["fieldErrors"] for row in shadow_validator_refresh["validationResults"]))

            build_live_operator_approval_evidence_review(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            build_live_runtime_preflight_probe(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            build_adapter_contract_validator(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            shadow_harness = build_execution_adapter_harness(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_harness["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_harness["dataPlaneHarnessReady"])
            self.assertTrue(shadow_harness["executionModeOnlyBlocked"])
            self.assertTrue(shadow_harness["sampleValidationPassed"])
            self.assertFalse(shadow_harness["readyForDisabledAdapterImplementationReview"])
            shadow_harness_codes = {row["code"] for row in shadow_harness["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_harness_codes)
            self.assertNotIn("ADAPTER_HARNESS_VALIDATION_FAILED", shadow_harness_codes)
            self.assertFalse(shadow_harness["orderSendAllowed"])
            self.assertFalse(shadow_harness["writesMt5OrderRequest"])
            refresh_shadow_dashboard()
            shadow_harness_refresh = build_execution_adapter_harness(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                refresh_sources=True,
                write=False,
            )
            self.assertEqual(shadow_harness_refresh["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_harness_refresh["dataPlaneHarnessReady"])
            self.assertTrue(shadow_harness_refresh["sampleValidationPassed"])
            self.assertTrue(all(row["dataPlanePassed"] for row in shadow_harness_refresh["validationResults"]))
            refresh_harness_codes = {row["code"] for row in shadow_harness_refresh["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", refresh_harness_codes)
            self.assertNotIn("ADAPTER_HARNESS_VALIDATION_FAILED", refresh_harness_codes)
            self.assertFalse(shadow_harness_refresh["orderSendAllowed"])
            self.assertFalse(shadow_harness_refresh["writesMt5OrderRequest"])

            shadow_activation = build_live_pilot_activation_review(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_activation["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_activation["dataPlaneActivationReady"])
            self.assertTrue(shadow_activation["executionModeOnlyBlocked"])
            self.assertFalse(shadow_activation["readyForLivePilotActivationReview"])
            shadow_activation_codes = {row["code"] for row in shadow_activation["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_activation_codes)
            self.assertNotIn("LIVE_PILOT_ACTIVATION_CHECK_NOT_PASSED", shadow_activation_codes)
            self.assertFalse(shadow_activation["orderSendAllowed"])
            self.assertFalse(shadow_activation["writesMt5OrderRequest"])
            refresh_shadow_dashboard()
            shadow_receipt_review = build_receipt_reconciliation_review(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_receipt_review["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_receipt_review["dataPlaneReconciliationReady"])
            self.assertTrue(shadow_receipt_review["executionModeOnlyBlocked"])
            self.assertTrue(shadow_receipt_review["reviewOnlyReceiptsReconciled"])
            self.assertTrue(all(row["passed"] for row in shadow_receipt_review["reconciliationResults"]))
            shadow_receipt_codes = {row["code"] for row in shadow_receipt_review["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_receipt_codes)
            self.assertNotIn("RECONCILIATION_RECEIPT_VALIDATION_FAILED", shadow_receipt_codes)
            self.assertFalse(shadow_receipt_review["orderSendAllowed"])
            self.assertFalse(shadow_receipt_review["writesMt5OrderRequest"])

            ea_source = runtime / "QuantGod_MultiStrategy.request_reader_review.mq5"
            ea_source.write_text(
                "\n".join([
                    "// QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT",
                    "// QG_EA_REQUEST_SCHEMA_VALIDATION_REQUIRED",
                    "// QG_EA_IDEMPOTENCY_REQUEST_ID_REQUIRED",
                    "// QG_EA_KILL_SWITCH_REQUIRED",
                    "// QG_EA_RECEIPT_WRITER_REQUIRED",
                    "// QG_EA_ORDER_SEND_REQUIRES_SEPARATE_REVIEW",
                ]),
                encoding="utf-8",
            )
            ea_status = runtime / "QuantGod_EARequestReaderReviewStatus.json"
            ea_status.write_text(json.dumps(self._ea_request_reader_runtime_status()), encoding="utf-8")
            refresh_shadow_dashboard()
            shadow_ea_reader = build_ea_request_reader_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_ea_reader["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_ea_reader["dataPlaneEaRequestReaderReady"])
            self.assertTrue(shadow_ea_reader["executionModeOnlyBlocked"])
            self.assertTrue(shadow_ea_reader["readyForRuntimeEaRequestReaderStatusReview"])
            self.assertFalse(shadow_ea_reader["readyForEaRequestReaderImplementationReview"])
            shadow_ea_codes = {row["code"] for row in shadow_ea_reader["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_ea_codes)
            self.assertNotIn("EA_REQUEST_READER_REQUIRED_MARKERS_MISSING", shadow_ea_codes)
            self.assertFalse(shadow_ea_reader["orderSendAllowed"])
            self.assertFalse(shadow_ea_reader["eaRequestReaderEnabled"])
            self.assertFalse(shadow_ea_reader["writesMt5OrderRequest"])

            refresh_shadow_dashboard()
            shadow_cutover = build_live_execution_cutover_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_cutover["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_cutover["dataPlaneCutoverReady"])
            self.assertTrue(shadow_cutover["executionModeOnlyBlocked"])
            self.assertFalse(shadow_cutover["readyForSeparateLiveExecutionCutoverImplementationReview"])
            shadow_cutover_codes = {row["code"] for row in shadow_cutover["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_cutover_codes)
            self.assertIn("MT5_LIVE_PILOT_MODE_NOT_CONFIRMED", shadow_cutover_codes)
            self.assertNotIn("LIVE_EXECUTION_CUTOVER_CHECK_NOT_PASSED", shadow_cutover_codes)
            self.assertFalse(shadow_cutover["orderSendAllowed"])
            self.assertFalse(shadow_cutover["writesMt5OrderRequest"])

            shadow_implementation_spec = build_live_execution_implementation_spec(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_implementation_spec["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_implementation_spec["dataPlaneImplementationSpecReady"])
            self.assertTrue(shadow_implementation_spec["executionModeOnlyBlocked"])
            self.assertFalse(shadow_implementation_spec["readyForLiveExecutionImplementationSpecReview"])
            self.assertGreaterEqual(len(shadow_implementation_spec["implementationSteps"]), 5)
            shadow_spec_codes = {row["code"] for row in shadow_implementation_spec["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_spec_codes)
            self.assertNotIn("LIVE_EXECUTION_CUTOVER_REVIEW_NOT_READY", shadow_spec_codes)
            gap_audit = shadow_implementation_spec["executionActivationGapAudit"]
            self.assertEqual(gap_audit["status"], "PROFIT_TARGET_REACHED_EXECUTION_GATES_OFF")
            self.assertFalse(gap_audit["goLiveAllowedNow"])
            self.assertEqual(
                {row["field"] for row in gap_audit["gates"]},
                {"readOnlyMode", "livePilotMode", "executionEnabled", "tradeAllowed"},
            )
            self.assertEqual(
                gap_audit["sourceOfTruth"]["presetFile"],
                "MQL5/Presets/QuantGod_MT5_HFM_LiveSecondary.set",
            )
            self.assertEqual(
                gap_audit["requestReaderGap"]["currentPresetSetting"],
                "EnableEARequestReaderReviewHarness=false by default",
            )
            self.assertFalse(shadow_implementation_spec["orderSendAllowed"])
            self.assertFalse(shadow_implementation_spec["writesMt5OrderRequest"])

            shadow_adapter_write = build_live_execution_adapter_write_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_adapter_write["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_adapter_write["dataPlaneAdapterWriteReady"])
            self.assertTrue(shadow_adapter_write["executionModeOnlyBlocked"])
            self.assertFalse(shadow_adapter_write["readyForLiveExecutionAdapterWriteReview"])
            self.assertGreaterEqual(shadow_adapter_write["writePlanCount"], 1)
            self.assertTrue(all(row["contractValidationPassed"] for row in shadow_adapter_write["writePlans"]))
            shadow_adapter_codes = {row["code"] for row in shadow_adapter_write["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_adapter_codes)
            self.assertNotIn("LIVE_ADAPTER_WRITE_PLAN_INVALID", shadow_adapter_codes)
            self.assertFalse(shadow_adapter_write["orderSendAllowed"])
            self.assertFalse(shadow_adapter_write["writesMt5OrderRequest"])

            shadow_ea_consumption = build_ea_request_consumption_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_ea_consumption["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_ea_consumption["dataPlaneEaRequestConsumptionReady"])
            self.assertTrue(shadow_ea_consumption["executionModeOnlyBlocked"])
            self.assertFalse(shadow_ea_consumption["readyForEaRequestConsumptionReview"])
            self.assertGreaterEqual(shadow_ea_consumption["consumptionPlanCount"], 1)
            shadow_consumption_codes = {row["code"] for row in shadow_ea_consumption["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_consumption_codes)
            self.assertNotIn("EA_REQUEST_CONSUMPTION_CHECK_NOT_PASSED", shadow_consumption_codes)
            self.assertFalse(shadow_ea_consumption["orderSendAllowed"])
            self.assertFalse(shadow_ea_consumption["eaRequestFilesRead"])
            self.assertFalse(shadow_ea_consumption["writesMt5OrderRequest"])

            shadow_broker_send = build_broker_order_send_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=False,
            )
            self.assertEqual(shadow_broker_send["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(shadow_broker_send["dataPlaneBrokerOrderSendReady"])
            self.assertTrue(shadow_broker_send["executionModeOnlyBlocked"])
            self.assertFalse(shadow_broker_send["readyForBrokerOrderSendReview"])
            self.assertGreaterEqual(shadow_broker_send["brokerSendPlanCount"], 1)
            shadow_broker_codes = {row["code"] for row in shadow_broker_send["blockers"]}
            self.assertIn("EXECUTION_MODE_GATES_NOT_ACTIVE", shadow_broker_codes)
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", shadow_broker_codes)
            self.assertNotIn("BROKER_ORDER_SEND_CHECK_NOT_PASSED", shadow_broker_codes)
            self.assertFalse(shadow_broker_send["orderSendAllowed"])
            self.assertFalse(shadow_broker_send["brokerCallsMade"])
            self.assertFalse(shadow_broker_send["writesMt5OrderRequest"])
            refresh_live_dashboard()

            preflight = build_live_runtime_preflight_probe(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )

            self.assertEqual(preflight["schema"], "quantgod.live_runtime_preflight_probe.v1")
            self.assertEqual(preflight["status"], "READY_FOR_RUNTIME_PREFLIGHT_REVIEW")
            self.assertTrue(preflight["runtimeProbePassed"])
            self.assertTrue(preflight["dataPlaneReadyForLivePilotReview"])
            self.assertTrue(preflight["executionModeReady"])
            self.assertFalse(preflight["executionModeOnlyBlocked"])
            self.assertTrue(preflight["replayPassed"])
            self.assertTrue(preflight["probeResults"]["livePilotModeOk"])
            self.assertTrue(preflight["probeResults"]["readOnlyModeOff"])
            self.assertTrue(preflight["probeResults"]["executionEnabledOk"])
            self.assertTrue(preflight["probeResults"]["tradeAllowedOk"])
            self.assertTrue(preflight["probeResults"]["symbolMappingOk"])
            self.assertTrue(preflight["probeResults"]["spreadProbeOk"])
            self.assertFalse(preflight["executionReady"])
            self.assertFalse(preflight["writesMt5OrderRequest"])
            self.assertFalse(preflight["mt5PendingOrderIntentsWritten"])
            self.assertFalse(preflight["orderSendAllowed"])
            self.assertFalse(preflight["brokerExecutionAllowed"])
            self.assertEqual(preflight["blockers"], [])
            saved = read_live_runtime_preflight_probe(runtime)
            self.assertEqual(saved["schema"], preflight["schema"])

            order_contract = build_mt5_order_request_contract(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(order_contract["schema"], "quantgod.mt5_order_request_contract.v1")
            self.assertEqual(order_contract["status"], "READY_FOR_ORDER_REQUEST_CONTRACT_REVIEW")
            self.assertTrue(order_contract["readyForAdapterCodeReview"])
            self.assertTrue(order_contract["runtimePreflightPassed"])
            self.assertTrue(order_contract["runtimePreflightDataPlaneReadyForReview"])
            self.assertTrue(order_contract["runtimePreflightExecutionModeReady"])
            self.assertFalse(order_contract["runtimePreflightExecutionModeOnlyBlocked"])
            self.assertFalse(order_contract["executionReady"])
            self.assertFalse(order_contract["requestWritesAllowed"])
            self.assertFalse(order_contract["writesMt5OrderRequest"])
            self.assertFalse(order_contract["mt5PendingOrderIntentsWritten"])
            self.assertFalse(order_contract["orderSendAllowed"])
            self.assertFalse(order_contract["brokerExecutionAllowed"])
            self.assertGreaterEqual(len(order_contract["requestContract"]["allowedRequestFields"]), 20)
            self.assertIn("runtime_preflight_passed", order_contract["requestContract"]["requiredRuntimeFuses"])
            self.assertEqual(order_contract["blockers"], [])
            saved_contract = read_mt5_order_request_contract(runtime)
            self.assertEqual(saved_contract["schema"], order_contract["schema"])

            pipeline = build_sim_to_live_automation_pipeline(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(pipeline["schema"], "quantgod.sim_to_live_automation_pipeline.v1")
            self.assertEqual(pipeline["status"], "READY_FOR_SEPARATE_EXECUTION_ADAPTER_REVIEW")
            self.assertEqual(pipeline["autoStage"], "order_request_contract")
            self.assertTrue(pipeline["readyForSeparateExecutionAdapterReview"])
            self.assertFalse(pipeline["executionReady"])
            self.assertFalse(pipeline["requestWritesAllowed"])
            self.assertFalse(pipeline["writesMt5OrderRequest"])
            self.assertFalse(pipeline["orderSendAllowed"])
            self.assertFalse(pipeline["brokerExecutionAllowed"])
            self.assertGreaterEqual(len(pipeline["stages"]), 8)
            saved_pipeline = read_sim_to_live_automation_pipeline(runtime)
            self.assertEqual(saved_pipeline["schema"], pipeline["schema"])

            adapter_review = build_execution_adapter_review(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(adapter_review["schema"], "quantgod.execution_adapter_review.v1")
            self.assertEqual(adapter_review["status"], "READY_FOR_EXECUTION_ADAPTER_CODE_REVIEW")
            self.assertTrue(adapter_review["readyForExecutionAdapterCodeReview"])
            self.assertFalse(adapter_review["executionReady"])
            self.assertFalse(adapter_review["adapterExecutionAllowed"])
            self.assertFalse(adapter_review["requestWritesAllowed"])
            self.assertFalse(adapter_review["requestFilesWritten"])
            self.assertFalse(adapter_review["brokerCallsMade"])
            self.assertFalse(adapter_review["writesMt5OrderRequest"])
            self.assertFalse(adapter_review["orderSendAllowed"])
            self.assertFalse(adapter_review["brokerExecutionAllowed"])
            self.assertEqual(adapter_review["reviewMode"], "REVIEW_ONLY")
            self.assertGreaterEqual(len(adapter_review["reviewOnlySampleReceipts"]), 1)
            self.assertEqual(adapter_review["blockers"], [])
            saved_adapter_review = read_execution_adapter_review(runtime)
            self.assertEqual(saved_adapter_review["schema"], adapter_review["schema"])

            sandbox = build_adapter_sandbox_review_bundle(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(sandbox["schema"], "quantgod.adapter_sandbox_review_bundle.v1")
            self.assertEqual(sandbox["status"], "READY_FOR_ADAPTER_SANDBOX_REVIEW")
            self.assertTrue(sandbox["sandboxReadyForCodeReview"])
            self.assertTrue(sandbox["reviewBundleWritten"])
            self.assertFalse(sandbox["executionReady"])
            self.assertFalse(sandbox["requestWritesAllowed"])
            self.assertFalse(sandbox["requestFilesWritten"])
            self.assertFalse(sandbox["brokerCallsMade"])
            self.assertFalse(sandbox["adapterExecutionAllowed"])
            self.assertFalse(sandbox["writesMt5OrderRequest"])
            self.assertFalse(sandbox["orderSendAllowed"])
            self.assertGreaterEqual(sandbox["sampleRequestCount"], 1)
            self.assertGreaterEqual(sandbox["sampleReceiptCount"], 1)
            self.assertTrue(all(row["passed"] for row in sandbox["validationResults"]))
            self.assertEqual(sandbox["blockers"], [])
            saved_sandbox = read_adapter_sandbox_review_bundle(runtime)
            self.assertEqual(saved_sandbox["schema"], sandbox["schema"])

            validator = build_adapter_contract_validator(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(validator["schema"], "quantgod.adapter_contract_validator.v1")
            self.assertEqual(validator["status"], "READY_FOR_ADAPTER_CONTRACT_VALIDATION_REVIEW")
            self.assertTrue(validator["validationPassed"])
            self.assertGreaterEqual(validator["requestCount"], 1)
            self.assertGreaterEqual(validator["receiptCount"], 1)
            self.assertTrue(validator["reviewOnlyReceiptsGenerated"])
            self.assertTrue(all(row["passed"] for row in validator["validationResults"]))
            self.assertFalse(validator["executionReady"])
            self.assertFalse(validator["requestWritesAllowed"])
            self.assertFalse(validator["requestFilesWritten"])
            self.assertFalse(validator["brokerCallsMade"])
            self.assertFalse(validator["adapterExecutionAllowed"])
            self.assertFalse(validator["writesMt5OrderRequest"])
            self.assertFalse(validator["orderSendAllowed"])
            self.assertEqual(validator["blockers"], [])
            saved_validator = read_adapter_contract_validator(runtime)
            self.assertEqual(saved_validator["schema"], validator["schema"])

            refresh_live_dashboard()
            orchestrator = build_sim_to_live_orchestrator(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(orchestrator["schema"], "quantgod.sim_to_live_orchestrator.v1")
            self.assertEqual(
                orchestrator["status"],
                "READY_FOR_EXECUTION_ADAPTER_IMPLEMENTATION_REVIEW",
                json.dumps({
                    "stages": orchestrator.get("stages"),
                    "blockers": orchestrator.get("blockers"),
                }, ensure_ascii=False, indent=2),
            )
            self.assertTrue(orchestrator["readyForExecutionAdapterImplementationReview"])
            self.assertFalse(orchestrator["readyForLiveExecutionImplementationReview"])
            self.assertEqual(orchestrator["currentStage"], "adapter_implementation_review")
            self.assertEqual(orchestrator["currentLiveExecutionStage"], "disabled_adapter_harness")
            self.assertFalse(orchestrator["executionReady"])
            self.assertFalse(orchestrator["requestWritesAllowed"])
            self.assertFalse(orchestrator["requestFilesWritten"])
            self.assertFalse(orchestrator["brokerCallsMade"])
            self.assertFalse(orchestrator["adapterExecutionAllowed"])
            self.assertFalse(orchestrator["writesMt5OrderRequest"])
            self.assertFalse(orchestrator["orderSendAllowed"])
            self.assertTrue(all(row["passed"] for row in orchestrator["stages"]))
            self.assertFalse(all(row["passed"] for row in orchestrator["liveExecutionStages"]))
            saved_orchestrator = read_sim_to_live_orchestrator(runtime)
            self.assertEqual(saved_orchestrator["schema"], orchestrator["schema"])

            harness = build_execution_adapter_harness(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(harness["schema"], "quantgod.execution_adapter_harness.v1")
            self.assertEqual(harness["status"], "READY_FOR_DISABLED_ADAPTER_IMPLEMENTATION_HARNESS_REVIEW")
            self.assertTrue(harness["readyForDisabledAdapterImplementationReview"])
            self.assertGreaterEqual(harness["plannedWriteCount"], 1)
            self.assertGreaterEqual(harness["reviewOnlyReceiptCount"], 1)
            self.assertTrue(all(row["passed"] for row in harness["validationResults"]))
            self.assertTrue(all(row["wouldWriteRequestFile"] is False for row in harness["plannedWrites"]))
            self.assertTrue(all(row["wouldWriteReceiptFile"] is False for row in harness["plannedWrites"]))
            self.assertTrue(all(row["brokerCallsMade"] is False for row in harness["plannedWrites"]))
            self.assertTrue(all(row["adapterExecutionAllowed"] is False for row in harness["plannedWrites"]))
            self.assertFalse(harness["executionReady"])
            self.assertFalse(harness["requestWritesAllowed"])
            self.assertFalse(harness["requestFilesWritten"])
            self.assertFalse(harness["brokerCallsMade"])
            self.assertFalse(harness["adapterExecutionAllowed"])
            self.assertFalse(harness["writesMt5OrderRequest"])
            self.assertFalse(harness["orderSendAllowed"])
            self.assertEqual(harness["blockers"], [])
            saved_harness = read_execution_adapter_harness(runtime)
            self.assertEqual(saved_harness["schema"], harness["schema"])

            activation = build_live_pilot_activation_review(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(activation["schema"], "quantgod.live_pilot_activation_review.v1")
            self.assertEqual(activation["status"], "READY_FOR_LIVE_PILOT_ACTIVATION_REVIEW")
            self.assertTrue(activation["readyForLivePilotActivationReview"])
            self.assertGreaterEqual(len(activation["reviewChecklist"]), 8)
            self.assertTrue(all(row["passed"] for row in activation["reviewChecklist"]))
            self.assertGreaterEqual(len(activation["deploymentRunbook"]), 5)
            self.assertFalse(activation["executionReady"])
            self.assertFalse(activation["livePilotActivationAllowed"])
            self.assertFalse(activation["requestWritesAllowed"])
            self.assertFalse(activation["requestFilesWritten"])
            self.assertFalse(activation["brokerCallsMade"])
            self.assertFalse(activation["adapterExecutionAllowed"])
            self.assertFalse(activation["writesMt5OrderRequest"])
            self.assertFalse(activation["orderSendAllowed"])
            self.assertEqual(activation["blockers"], [])
            saved_activation = read_live_pilot_activation_review(runtime)
            self.assertEqual(saved_activation["schema"], activation["schema"])

            receipt_review = build_receipt_reconciliation_review(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(receipt_review["schema"], "quantgod.receipt_reconciliation_review.v1")
            self.assertEqual(receipt_review["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertFalse(receipt_review["readyForReceiptReconciliationReview"])
            self.assertFalse(receipt_review["reconciliationPassed"])
            self.assertTrue(receipt_review["dataPlaneReconciliationReady"])
            self.assertTrue(receipt_review["executionModeOnlyBlocked"])
            self.assertTrue(receipt_review["releaseTokenRequired"])
            self.assertFalse(receipt_review["releaseTokenProvided"])
            self.assertEqual(receipt_review["releaseTokenBlockerCode"], "RECEIPT_WRITER_RELEASE_TOKEN_MISSING")
            self.assertIn("RECEIPT_WRITER_RELEASE_TOKEN_MISSING", {row["code"] for row in receipt_review["blockers"]})
            self.assertGreaterEqual(receipt_review["plannedRequestCount"], 1)
            self.assertGreaterEqual(receipt_review["receiptCount"], 1)
            self.assertTrue(all(row["passed"] for row in receipt_review["reconciliationResults"]))
            self.assertFalse(receipt_review["executionReady"])
            self.assertFalse(receipt_review["livePilotActivationAllowed"])
            self.assertFalse(receipt_review["requestWritesAllowed"])
            self.assertFalse(receipt_review["requestFilesWritten"])
            self.assertFalse(receipt_review["receiptWritesAllowed"])
            self.assertFalse(receipt_review["receiptFilesWritten"])
            self.assertFalse(receipt_review["brokerCallsMade"])
            self.assertFalse(receipt_review["adapterExecutionAllowed"])
            self.assertFalse(receipt_review["autoDisableMutationAllowed"])
            self.assertFalse(receipt_review["writesMt5OrderRequest"])
            self.assertFalse(receipt_review["orderSendAllowed"])
            saved_receipt_review = read_receipt_reconciliation_review(runtime)
            self.assertEqual(saved_receipt_review["schema"], receipt_review["schema"])

            ea_source = runtime / "QuantGod_MultiStrategy.request_reader_review.mq5"
            ea_source.write_text(
                "\n".join([
                    "// QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT",
                    "// QG_EA_REQUEST_SCHEMA_VALIDATION_REQUIRED",
                    "// QG_EA_IDEMPOTENCY_REQUEST_ID_REQUIRED",
                    "// QG_EA_KILL_SWITCH_REQUIRED",
                    "// QG_EA_RECEIPT_WRITER_REQUIRED",
                    "// QG_EA_ORDER_SEND_REQUIRES_SEPARATE_REVIEW",
                ]),
                encoding="utf-8",
            )
            ea_status = runtime / "QuantGod_EARequestReaderReviewStatus.json"
            ea_status.write_text(json.dumps(self._ea_request_reader_runtime_status()), encoding="utf-8")
            ea_reader = build_ea_request_reader_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                write=True,
            )
            self.assertEqual(ea_reader["schema"], "quantgod.ea_request_reader_review.v1")
            self.assertEqual(ea_reader["status"], "READY_FOR_EA_REQUEST_READER_IMPLEMENTATION_REVIEW")
            self.assertTrue(ea_reader["readyForEaRequestReaderImplementationReview"])
            self.assertEqual(ea_reader["missingMarkerCount"], 0)
            self.assertTrue(all(row["present"] for row in ea_reader["markerChecks"]))
            self.assertTrue(ea_reader["runtimeStatusFound"])
            self.assertTrue(ea_reader["runtimeStatusSchemaOk"])
            self.assertTrue(ea_reader["runtimeStatusDisabled"])
            self.assertTrue(ea_reader["runtimeStatusSafetyPassed"])
            self.assertTrue(ea_reader["readyForRuntimeEaRequestReaderStatusReview"])
            self.assertTrue(all(row["passed"] for row in ea_reader["runtimeStatusSafetyChecks"]))
            self.assertTrue(all(row["passed"] for row in ea_reader["reviewChecklist"]))
            self.assertFalse(ea_reader["executionReady"])
            self.assertFalse(ea_reader["livePilotActivationAllowed"])
            self.assertFalse(ea_reader["requestWritesAllowed"])
            self.assertFalse(ea_reader["requestFilesWritten"])
            self.assertFalse(ea_reader["receiptWritesAllowed"])
            self.assertFalse(ea_reader["receiptFilesWritten"])
            self.assertFalse(ea_reader["brokerCallsMade"])
            self.assertFalse(ea_reader["adapterExecutionAllowed"])
            self.assertFalse(ea_reader["autoDisableMutationAllowed"])
            self.assertFalse(ea_reader["eaRequestReaderAllowed"])
            self.assertFalse(ea_reader["eaRequestReaderEnabled"])
            self.assertFalse(ea_reader["eaRequestFilesRead"])
            self.assertFalse(ea_reader["eaRequestFilesConsumed"])
            self.assertFalse(ea_reader["eaOrderSendAllowed"])
            self.assertFalse(ea_reader["writesMt5OrderRequest"])
            self.assertFalse(ea_reader["orderSendAllowed"])
            self.assertEqual(ea_reader["blockers"], [])
            saved_ea_reader = read_ea_request_reader_review(runtime)
            self.assertEqual(saved_ea_reader["schema"], ea_reader["schema"])

            final_orchestrator = build_sim_to_live_orchestrator(
                runtime,
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(final_orchestrator["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(final_orchestrator["readyForExecutionAdapterImplementationReview"])
            self.assertFalse(final_orchestrator["readyForLiveExecutionImplementationReview"])
            self.assertFalse(final_orchestrator["allExecutionReleaseTokensProvided"])
            self.assertIn("RECEIPT_WRITER_RELEASE_TOKEN_MISSING", final_orchestrator["executionReleaseGateSummary"]["blockerCodes"])
            self.assertEqual(final_orchestrator["currentLiveExecutionStage"], "receipt_reconciliation_review")
            self.assertTrue(all(row["passed"] for row in final_orchestrator["stages"]))
            self.assertFalse(all(row["passed"] for row in final_orchestrator["liveExecutionStages"]))
            self.assertFalse(final_orchestrator["executionReady"])
            self.assertFalse(final_orchestrator["requestWritesAllowed"])
            self.assertFalse(final_orchestrator["requestFilesWritten"])
            self.assertFalse(final_orchestrator["brokerCallsMade"])
            self.assertFalse(final_orchestrator["adapterExecutionAllowed"])
            self.assertFalse(final_orchestrator["writesMt5OrderRequest"])
            self.assertFalse(final_orchestrator["orderSendAllowed"])

            cutover = build_live_execution_cutover_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(cutover["schema"], "quantgod.live_execution_cutover_review.v1")
            self.assertEqual(cutover["status"], "READY_FOR_SEPARATE_LIVE_EXECUTION_CUTOVER_IMPLEMENTATION_REVIEW")
            self.assertTrue(cutover["readyForSeparateLiveExecutionCutoverImplementationReview"])
            self.assertTrue(all(row["passed"] for row in cutover["cutoverChecklist"]))
            self.assertGreaterEqual(cutover["implementationHandoff"]["plannedWriteCount"], 1)
            self.assertTrue(cutover["implementationHandoff"]["implementationMustStaySeparate"])
            self.assertFalse(cutover["executionReady"])
            self.assertFalse(cutover["liveExecutionCutoverAllowed"])
            self.assertFalse(cutover["livePilotActivationAllowed"])
            self.assertFalse(cutover["requestWritesAllowed"])
            self.assertFalse(cutover["requestFilesWritten"])
            self.assertFalse(cutover["receiptWritesAllowed"])
            self.assertFalse(cutover["receiptFilesWritten"])
            self.assertFalse(cutover["brokerCallsMade"])
            self.assertFalse(cutover["adapterExecutionAllowed"])
            self.assertFalse(cutover["autoDisableMutationAllowed"])
            self.assertFalse(cutover["eaRequestReaderAllowed"])
            self.assertFalse(cutover["eaRequestReaderEnabled"])
            self.assertFalse(cutover["eaRequestFilesRead"])
            self.assertFalse(cutover["eaRequestFilesConsumed"])
            self.assertFalse(cutover["eaOrderSendAllowed"])
            self.assertFalse(cutover["writesMt5OrderRequest"])
            self.assertFalse(cutover["orderSendAllowed"])
            self.assertEqual(cutover["blockers"], [])
            saved_cutover = read_live_execution_cutover_review(runtime)
            self.assertEqual(saved_cutover["schema"], cutover["schema"])

            implementation_spec = build_live_execution_implementation_spec(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(implementation_spec["schema"], "quantgod.live_execution_implementation_spec.v1")
            self.assertEqual(implementation_spec["status"], "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW")
            self.assertTrue(implementation_spec["readyForLiveExecutionImplementationSpecReview"])
            self.assertTrue(implementation_spec["implementationMustStaySeparate"])
            self.assertGreaterEqual(len(implementation_spec["implementationSteps"]), 5)
            micro_blueprint = implementation_spec["microLiveExecutionBlueprint"]
            self.assertEqual(
                micro_blueprint["mode"],
                "MICRO_LIVE_EXECUTION_IMPLEMENTATION_BLUEPRINT_REVIEW_ONLY",
            )
            self.assertEqual(micro_blueprint["status"], "READY_TO_IMPLEMENT_DISABLED_FIRST")
            self.assertEqual(micro_blueprint["selectedLane"], "HFM_CRYPTO_CFD")
            self.assertEqual(micro_blueprint["brokerSymbol"], "#BTCUSD")
            self.assertEqual(micro_blueprint["initialLiveVolumeLotsCandidate"], 0.01)
            self.assertTrue(micro_blueprint["initialLiveVolumeRequiresSeparateRiskReview"])
            self.assertTrue(micro_blueprint["allRequiredStepsMapped"])
            self.assertTrue(micro_blueprint["rejectionReceiptPlanComplete"])
            self.assertEqual(micro_blueprint["duplicateRequestIds"], [])
            self.assertEqual(
                {row["packageId"] for row in micro_blueprint["implementationPackages"]},
                {
                    "python_request_writer",
                    "mql5_request_reader",
                    "mql5_broker_order_send_wrapper",
                    "receipt_writer_and_reconciliation",
                    "rollback_auto_disable",
                },
            )
            self.assertFalse(micro_blueprint["requestWritesAllowed"])
            self.assertFalse(micro_blueprint["requestFilesWritten"])
            self.assertFalse(micro_blueprint["receiptFilesWritten"])
            self.assertFalse(micro_blueprint["brokerCallsMade"])
            self.assertFalse(micro_blueprint["orderSendAllowed"])
            self.assertFalse(micro_blueprint["mt5OrderSendAllowed"])
            self.assertEqual(
                implementation_spec["requiredFuturePrs"],
                [
                    "live_execution_adapter_write_path",
                    "ea_request_reader_consumption_path",
                    "broker_order_send_path",
                    "receipt_writer_and_reconciliation_path",
                    "rollback_and_auto_disable_path",
                ],
            )
            self.assertFalse(implementation_spec["executionReady"])
            self.assertFalse(implementation_spec["liveExecutionCutoverAllowed"])
            self.assertFalse(implementation_spec["requestWritesAllowed"])
            self.assertFalse(implementation_spec["requestFilesWritten"])
            self.assertFalse(implementation_spec["receiptWritesAllowed"])
            self.assertFalse(implementation_spec["receiptFilesWritten"])
            self.assertFalse(implementation_spec["brokerCallsMade"])
            self.assertFalse(implementation_spec["adapterExecutionAllowed"])
            self.assertFalse(implementation_spec["autoDisableMutationAllowed"])
            self.assertFalse(implementation_spec["eaRequestReaderAllowed"])
            self.assertFalse(implementation_spec["eaRequestReaderEnabled"])
            self.assertFalse(implementation_spec["eaRequestFilesRead"])
            self.assertFalse(implementation_spec["eaRequestFilesConsumed"])
            self.assertFalse(implementation_spec["eaOrderSendAllowed"])
            self.assertFalse(implementation_spec["writesMt5OrderRequest"])
            self.assertFalse(implementation_spec["orderSendAllowed"])
            traceability = implementation_spec["executionSafetyTraceabilityMatrix"]
            self.assertEqual(len(traceability), 3)
            self.assertTrue(all(row["declaredInImplementationSteps"] for row in traceability))
            self.assertTrue(all(row["reviewOnlyStatus"] == "PENDING_SEPARATE_PR_REVIEW" for row in traceability))
            self.assertTrue(all(row["orderSendAllowed"] is False for row in traceability))
            self.assertTrue(all(row["brokerCallsMade"] is False for row in traceability))
            self.assertIn(
                "receipt_writer_and_reconciliation_path",
                {row["stepId"] for row in traceability},
            )
            self.assertEqual(implementation_spec["blockers"], [])
            saved_implementation_spec = read_live_execution_implementation_spec(runtime)
            self.assertEqual(saved_implementation_spec["schema"], implementation_spec["schema"])

            adapter_write = build_live_execution_adapter_write_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(adapter_write["schema"], "quantgod.live_execution_adapter_write_review.v1")
            self.assertEqual(adapter_write["status"], "READY_FOR_LIVE_EXECUTION_ADAPTER_WRITE_REVIEW")
            self.assertTrue(adapter_write["readyForLiveExecutionAdapterWriteReview"])
            self.assertGreaterEqual(adapter_write["writePlanCount"], 1)
            self.assertTrue(all(row["passed"] for row in adapter_write["adapterWriteChecklist"]))
            self.assertTrue(all(row["contractValidationPassed"] for row in adapter_write["writePlans"]))
            self.assertTrue(all(row["atomicWriteRequired"] for row in adapter_write["writePlans"]))
            self.assertTrue(all(row["allowedToWriteLiveRequest"] is False for row in adapter_write["writePlans"]))
            self.assertTrue(all(row["wouldWriteToMt5RequestDirectory"] is False for row in adapter_write["writePlans"]))
            self.assertTrue(all(row["requestFilesWritten"] is False for row in adapter_write["writePlans"]))
            self.assertFalse(adapter_write["executionReady"])
            self.assertFalse(adapter_write["requestWritesAllowed"])
            self.assertFalse(adapter_write["requestFilesWritten"])
            self.assertFalse(adapter_write["receiptWritesAllowed"])
            self.assertFalse(adapter_write["brokerCallsMade"])
            self.assertFalse(adapter_write["adapterExecutionAllowed"])
            self.assertFalse(adapter_write["eaRequestReaderAllowed"])
            self.assertFalse(adapter_write["eaRequestFilesRead"])
            self.assertFalse(adapter_write["writesMt5OrderRequest"])
            self.assertFalse(adapter_write["orderSendAllowed"])
            self.assertEqual(adapter_write["blockers"], [])
            saved_adapter_write = read_live_execution_adapter_write_review(runtime)
            self.assertEqual(saved_adapter_write["schema"], adapter_write["schema"])

            ea_consumption = build_ea_request_consumption_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(ea_consumption["schema"], "quantgod.ea_request_consumption_review.v1")
            self.assertEqual(ea_consumption["status"], "READY_FOR_EA_REQUEST_CONSUMPTION_REVIEW")
            self.assertTrue(ea_consumption["readyForEaRequestConsumptionReview"])
            self.assertGreaterEqual(ea_consumption["consumptionPlanCount"], 1)
            self.assertTrue(all(row["passed"] for row in ea_consumption["eaRequestConsumptionChecklist"]))
            self.assertTrue(all(row["defaultAction"] == "REJECT_REVIEW_ONLY" for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["wouldReadRequestFile"] is False for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["wouldConsumeRequestFile"] is False for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["wouldWriteReceiptFile"] is False for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["releaseTokenRequired"] is True for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["releaseTokenProvided"] is False for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["releaseTokenBlockerCode"] == "REQUEST_READER_RELEASE_TOKEN_MISSING" for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["orderSendAllowed"] is False for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["brokerCallsMade"] is False for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(ea_consumption["releaseTokenRequired"])
            self.assertFalse(ea_consumption["releaseTokenProvided"])
            self.assertEqual(ea_consumption["releaseTokenBlockerCode"], "REQUEST_READER_RELEASE_TOKEN_MISSING")
            self.assertEqual(ea_consumption["readerReleaseGate"]["blockerCode"], "REQUEST_READER_RELEASE_TOKEN_MISSING")
            self.assertEqual(ea_consumption["duplicateRequestIds"], [])
            self.assertEqual(ea_consumption["rejectionReceiptPlanMode"], "REJECTION_RECEIPT_PLAN_REVIEW_ONLY_NO_FILE_WRITES")
            self.assertTrue(all(row["rejectionReceiptPlan"]["complete"] for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["rejectionReceiptPlan"]["wouldReadRequestFile"] is False for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["rejectionReceiptPlan"]["wouldWriteReceiptFile"] is False for row in ea_consumption["consumptionPlans"]))
            self.assertTrue(all(row["rejectionReceiptPlan"]["receiptFilesWritten"] is False for row in ea_consumption["consumptionPlans"]))
            reason_codes = {
                rule["rejectedReasonCode"]
                for row in ea_consumption["consumptionPlans"]
                for rule in row["rejectionReceiptPlan"]["rules"]
            }
            self.assertIn("SCHEMA_VALIDATION_FAILED", reason_codes)
            self.assertIn("DUPLICATE_REQUEST_ID", reason_codes)
            self.assertIn("EXPIRED_OR_STALE_REQUEST", reason_codes)
            self.assertIn("READER_DISABLED_REVIEW_ONLY", reason_codes)
            self.assertIn("REQUEST_READER_RELEASE_TOKEN_MISSING", reason_codes)
            self.assertFalse(ea_consumption["executionReady"])
            self.assertFalse(ea_consumption["requestWritesAllowed"])
            self.assertFalse(ea_consumption["requestFilesWritten"])
            self.assertFalse(ea_consumption["receiptWritesAllowed"])
            self.assertFalse(ea_consumption["receiptFilesWritten"])
            self.assertFalse(ea_consumption["brokerCallsMade"])
            self.assertFalse(ea_consumption["adapterExecutionAllowed"])
            self.assertFalse(ea_consumption["autoDisableMutationAllowed"])
            self.assertFalse(ea_consumption["eaRequestReaderAllowed"])
            self.assertFalse(ea_consumption["eaRequestReaderEnabled"])
            self.assertFalse(ea_consumption["eaRequestFilesRead"])
            self.assertFalse(ea_consumption["eaRequestFilesConsumed"])
            self.assertFalse(ea_consumption["eaOrderSendAllowed"])
            self.assertFalse(ea_consumption["writesMt5OrderRequest"])
            self.assertFalse(ea_consumption["orderSendAllowed"])
            self.assertEqual(ea_consumption["blockers"], [])
            saved_ea_consumption = read_ea_request_consumption_review(runtime)
            self.assertEqual(saved_ea_consumption["schema"], ea_consumption["schema"])

            broker_send = build_broker_order_send_review(
                runtime,
                ea_source_path=str(ea_source),
                ea_status_json=str(ea_status),
                operator_approval_json=str(approval_json),
                moss_backtest_json=str(profile),
                hfm_contract_spec_json=str(spec),
                write=True,
            )
            self.assertEqual(broker_send["schema"], "quantgod.broker_order_send_review.v1")
            self.assertEqual(broker_send["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertFalse(broker_send["readyForBrokerOrderSendReview"])
            self.assertTrue(broker_send["dataPlaneBrokerOrderSendReady"])
            self.assertTrue(broker_send["executionModeOnlyBlocked"])
            self.assertGreaterEqual(broker_send["brokerSendPlanCount"], 1)
            self.assertTrue(all(row["passed"] for row in broker_send["brokerOrderSendChecklist"]))
            self.assertTrue(broker_send["releaseTokenRequired"])
            self.assertFalse(broker_send["releaseTokenProvided"])
            self.assertEqual(broker_send["releaseTokenBlockerCode"], "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING")
            self.assertEqual(broker_send["brokerReleaseGate"]["blockerCode"], "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING")
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", {row["code"] for row in broker_send["blockers"]})
            self.assertTrue(all(row["defaultAction"] == "BLOCK_REVIEW_ONLY_NO_BROKER_CALL" for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["wouldCallBroker"] is False for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["brokerCallsMade"] is False for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["orderSendAllowed"] is False for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["mt5OrderSendAllowed"] is False for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["releaseTokenRequired"] is True for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["releaseTokenProvided"] is False for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["releaseTokenBlockerCode"] == "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING" for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["sourcePathLockedToEaConsumption"] is True for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["requestFusesOk"] is True for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["laneRuntimePassed"] is True for row in broker_send["brokerSendPlans"]))
            self.assertTrue(all(row["laneContractMatch"] is True for row in broker_send["brokerSendPlans"]))
            self.assertFalse(broker_send["executionReady"])
            self.assertFalse(broker_send["requestWritesAllowed"])
            self.assertFalse(broker_send["requestFilesWritten"])
            self.assertFalse(broker_send["receiptWritesAllowed"])
            self.assertFalse(broker_send["receiptFilesWritten"])
            self.assertFalse(broker_send["brokerCallsMade"])
            self.assertFalse(broker_send["adapterExecutionAllowed"])
            self.assertFalse(broker_send["autoDisableMutationAllowed"])
            self.assertFalse(broker_send["eaRequestReaderAllowed"])
            self.assertFalse(broker_send["eaRequestReaderEnabled"])
            self.assertFalse(broker_send["eaRequestFilesRead"])
            self.assertFalse(broker_send["eaRequestFilesConsumed"])
            self.assertFalse(broker_send["eaOrderSendAllowed"])
            self.assertFalse(broker_send["brokerExecutionAllowed"])
            self.assertFalse(broker_send["writesMt5OrderRequest"])
            self.assertFalse(broker_send["orderSendAllowed"])
            self.assertTrue(all(
                row["code"] in {
                    "EXECUTION_MODE_GATES_NOT_ACTIVE",
                    "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                }
                for row in broker_send["blockers"]
            ))
            saved_broker_send = read_broker_order_send_review(runtime)
            self.assertEqual(saved_broker_send["schema"], broker_send["schema"])


if __name__ == "__main__":
    unittest.main()
