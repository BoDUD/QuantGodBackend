from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "quantgod.live_automation_readiness.v1"
REVIEW_PACKET_SCHEMA_VERSION = "quantgod.live_execution_review_packet.v1"
APPROVAL_DRAFT_SCHEMA_VERSION = "quantgod.live_operator_approval_draft.v1"
APPROVAL_EVIDENCE_REVIEW_SCHEMA_VERSION = "quantgod.live_operator_approval_evidence_review.v1"
DRY_RUN_PLAN_SCHEMA_VERSION = "quantgod.dry_run_live_execution_plan.v1"
EXECUTION_LANE_SPEC_SCHEMA_VERSION = "quantgod.live_execution_lane_spec.v1"
DRY_RUN_INTENT_REPLAY_SCHEMA_VERSION = "quantgod.live_dry_run_intent_replay.v1"
RUNTIME_PREFLIGHT_SCHEMA_VERSION = "quantgod.live_runtime_preflight_probe.v1"
ORDER_REQUEST_CONTRACT_SCHEMA_VERSION = "quantgod.mt5_order_request_contract.v1"
SIM_TO_LIVE_PIPELINE_SCHEMA_VERSION = "quantgod.sim_to_live_automation_pipeline.v1"
EXECUTION_ADAPTER_REVIEW_SCHEMA_VERSION = "quantgod.execution_adapter_review.v1"
LIVE_EVIDENCE_INTAKE_SCHEMA_VERSION = "quantgod.live_evidence_intake.v1"
LIVE_PROMOTION_CANDIDATES_SCHEMA_VERSION = "quantgod.live_promotion_candidates.v1"
LIVE_PROMOTION_CONTROLLER_SCHEMA_VERSION = "quantgod.live_promotion_controller.v1"
ADAPTER_SANDBOX_REVIEW_SCHEMA_VERSION = "quantgod.adapter_sandbox_review_bundle.v1"
ADAPTER_CONTRACT_VALIDATOR_SCHEMA_VERSION = "quantgod.adapter_contract_validator.v1"
SIM_TO_LIVE_ORCHESTRATOR_SCHEMA_VERSION = "quantgod.sim_to_live_orchestrator.v1"
EXECUTION_ADAPTER_HARNESS_SCHEMA_VERSION = "quantgod.execution_adapter_harness.v1"
LIVE_PILOT_ACTIVATION_REVIEW_SCHEMA_VERSION = "quantgod.live_pilot_activation_review.v1"
RECEIPT_RECONCILIATION_REVIEW_SCHEMA_VERSION = "quantgod.receipt_reconciliation_review.v1"
EA_REQUEST_READER_REVIEW_SCHEMA_VERSION = "quantgod.ea_request_reader_review.v1"
LIVE_EXECUTION_CUTOVER_REVIEW_SCHEMA_VERSION = "quantgod.live_execution_cutover_review.v1"
LIVE_EXECUTION_IMPLEMENTATION_SPEC_SCHEMA_VERSION = "quantgod.live_execution_implementation_spec.v1"
LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_SCHEMA_VERSION = "quantgod.live_execution_adapter_write_review.v1"
EA_REQUEST_CONSUMPTION_REVIEW_SCHEMA_VERSION = "quantgod.ea_request_consumption_review.v1"
BROKER_ORDER_SEND_REVIEW_SCHEMA_VERSION = "quantgod.broker_order_send_review.v1"
LIVE_EXECUTION_ROLLBACK_REVIEW_SCHEMA_VERSION = "quantgod.live_execution_rollback_review.v1"
RELEASE_READINESS_REFRESH_SCHEMA_VERSION = "quantgod.release_readiness_refresh.v1"
RELEASE_MINIMAL_DIFF_REVIEW_SCHEMA_VERSION = "quantgod.release_minimal_diff_review.v1"
RELEASE_TOKEN_EVIDENCE_REVIEW_SCHEMA_VERSION = "quantgod.release_token_evidence_review.v1"
RELEASE_TOKEN_SIGNOFF_DRAFT_SCHEMA_VERSION = "quantgod.release_token_signoff_draft.v1"
RELEASE_TOKEN_SIGNOFF_INPUT_TEMPLATE_SCHEMA_VERSION = "quantgod.release_token_signoff_input_template.v1"
RELEASE_TOKEN_SIGNOFF_INPUT_REVIEW_SCHEMA_VERSION = "quantgod.release_token_signoff_input_review.v1"
RELEASE_TOKEN_SIGNOFF_HANDOFF_SCHEMA_VERSION = "quantgod.release_token_signoff_handoff.v1"
RELEASE_TOKEN_SIGNOFF_EVIDENCE_MATRIX_SCHEMA_VERSION = "quantgod.release_token_signoff_evidence_matrix.v1"
LIVE_EXECUTION_LANE_SELECTOR_SCHEMA_VERSION = "quantgod.live_execution_lane_selector.v1"
FOREX_LIVE12_RUNTIME_HANDOFF_SCHEMA_VERSION = "quantgod.forex_live12_runtime_handoff.v1"
FOREX_LIVE12_CAPACITY_EXPANSION_REVIEW_SCHEMA_VERSION = "quantgod.forex_live12_capacity_expansion_review.v1"
FOREX_LIVE12_CAPACITY_EXPANSION_ROADMAP_SCHEMA_VERSION = "quantgod.forex_live12_capacity_expansion_roadmap.v1"
FOREX_LIVE12_MICRO_EXPANSION_REVIEW_SCHEMA_VERSION = "quantgod.forex_live12_micro_expansion_review.v1"
FOREX_LIVE12_RSI_REPAIR_PLAN_SCHEMA_VERSION = "quantgod.forex_live12_rsi_repair_plan.v1"
FOREX_LIVE12_RSI_SHADOW_CANDIDATE_SCHEMA_VERSION = "quantgod.forex_live12_rsi_shadow_candidate.v1"
FOREX_LIVE12_RSI_TESTER_REQUEST_SCHEMA_VERSION = "quantgod.forex_live12_rsi_tester_request.v1"
FOREX_LIVE12_RSI_TESTER_RUN_GATE_SCHEMA_VERSION = "quantgod.forex_live12_rsi_tester_run_gate.v1"
FOREX_LIVE12_RSI_CANDIDATE_PROMOTION_GATE_SCHEMA_VERSION = "quantgod.forex_live12_rsi_candidate_promotion_gate.v1"
FOREX_LIVE12_RSI_TESTER_LOCK_DRAFT_SCHEMA_VERSION = "quantgod.forex_live12_rsi_tester_lock_draft.v1"
SIM_TARGET_EXECUTION_REVIEW_SUMMARY_SCHEMA_VERSION = "quantgod.sim_target_execution_review_summary.v1"
DOSSIER_FILE = "QuantGod_LiveAutomationReadiness.json"
REVIEW_PACKET_FILE = "QuantGod_LiveExecutionReviewPacket.json"
APPROVAL_DRAFT_FILE = "QuantGod_LiveOperatorApprovalDraft.json"
APPROVAL_EVIDENCE_REVIEW_FILE = "QuantGod_LiveOperatorApprovalEvidenceReview.json"
DRY_RUN_PLAN_FILE = "QuantGod_DryRunLiveExecutionPlan.json"
EXECUTION_LANE_SPEC_FILE = "QuantGod_LiveExecutionLaneSpec.json"
DRY_RUN_INTENT_REPLAY_FILE = "QuantGod_LiveDryRunIntentReplay.json"
RUNTIME_PREFLIGHT_FILE = "QuantGod_LiveRuntimePreflightProbe.json"
ORDER_REQUEST_CONTRACT_FILE = "QuantGod_MT5OrderRequestContract.json"
SIM_TO_LIVE_PIPELINE_FILE = "QuantGod_SimToLiveAutomationPipeline.json"
EXECUTION_ADAPTER_REVIEW_FILE = "QuantGod_ExecutionAdapterReview.json"
LIVE_EVIDENCE_INTAKE_FILE = "QuantGod_LiveEvidenceIntake.json"
LIVE_PROMOTION_CANDIDATES_FILE = "QuantGod_LivePromotionCandidates.json"
LIVE_PROMOTION_CONTROLLER_FILE = "QuantGod_LivePromotionController.json"
ADAPTER_SANDBOX_REVIEW_FILE = "QuantGod_AdapterSandboxReviewBundle.json"
ADAPTER_CONTRACT_VALIDATOR_FILE = "QuantGod_AdapterContractValidator.json"
SIM_TO_LIVE_ORCHESTRATOR_FILE = "QuantGod_SimToLiveOrchestrator.json"
EXECUTION_ADAPTER_HARNESS_FILE = "QuantGod_ExecutionAdapterHarness.json"
LIVE_PILOT_ACTIVATION_REVIEW_FILE = "QuantGod_LivePilotActivationReview.json"
RECEIPT_RECONCILIATION_REVIEW_FILE = "QuantGod_ReceiptReconciliationReview.json"
EA_REQUEST_READER_REVIEW_FILE = "QuantGod_EARequestReaderReview.json"
LIVE_EXECUTION_CUTOVER_REVIEW_FILE = "QuantGod_LiveExecutionCutoverReview.json"
LIVE_EXECUTION_IMPLEMENTATION_SPEC_FILE = "QuantGod_LiveExecutionImplementationSpec.json"
LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_FILE = "QuantGod_LiveExecutionAdapterWriteReview.json"
EA_REQUEST_CONSUMPTION_REVIEW_FILE = "QuantGod_EARequestConsumptionReview.json"
BROKER_ORDER_SEND_REVIEW_FILE = "QuantGod_BrokerOrderSendReview.json"
LIVE_EXECUTION_ROLLBACK_REVIEW_FILE = "QuantGod_LiveExecutionRollbackReview.json"
RELEASE_READINESS_REFRESH_FILE = "QuantGod_ReleaseReadinessRefresh.json"
RELEASE_MINIMAL_DIFF_REVIEW_FILE = "QuantGod_ReleaseMinimalDiffReview.json"
RELEASE_TOKEN_EVIDENCE_REVIEW_FILE = "QuantGod_ReleaseTokenEvidenceReview.json"
RELEASE_TOKEN_SIGNOFF_DRAFT_FILE = "QuantGod_ReleaseTokenSignoffDraft.json"
RELEASE_TOKEN_SIGNOFF_INPUT_TEMPLATE_FILE = "QuantGod_ReleaseTokenSignoffInputTemplate.json"
RELEASE_TOKEN_SIGNOFF_INPUT_REVIEW_FILE = "QuantGod_ReleaseTokenSignoffInputReview.json"
RELEASE_TOKEN_SIGNOFF_HANDOFF_FILE = "QuantGod_ReleaseTokenSignoffHandoff.json"
RELEASE_TOKEN_SIGNOFF_EVIDENCE_MATRIX_FILE = "QuantGod_ReleaseTokenSignoffEvidenceMatrix.json"
LIVE_EXECUTION_LANE_SELECTOR_FILE = "QuantGod_LiveExecutionLaneSelector.json"
FOREX_LIVE12_RUNTIME_HANDOFF_FILE = "QuantGod_ForexLive12RuntimeHandoff.json"
FOREX_LIVE12_CAPACITY_EXPANSION_REVIEW_FILE = "QuantGod_ForexLive12CapacityExpansionReview.json"
FOREX_LIVE12_CAPACITY_EXPANSION_ROADMAP_FILE = "QuantGod_ForexLive12CapacityExpansionRoadmap.json"
FOREX_LIVE12_MICRO_EXPANSION_REVIEW_FILE = "QuantGod_ForexLive12MicroExpansionReview.json"
FOREX_LIVE12_RSI_REPAIR_PLAN_FILE = "QuantGod_ForexLive12RsiRepairPlan.json"
FOREX_LIVE12_RSI_SHADOW_CANDIDATE_FILE = "QuantGod_ForexLive12RsiShadowCandidate.json"
FOREX_LIVE12_RSI_TESTER_REQUEST_FILE = "QuantGod_ForexLive12RsiTesterRequest.json"
FOREX_LIVE12_RSI_TESTER_RUN_GATE_FILE = "QuantGod_ForexLive12RsiTesterRunGate.json"
FOREX_LIVE12_RSI_CANDIDATE_PROMOTION_GATE_FILE = "QuantGod_ForexLive12RsiCandidatePromotionGate.json"
FOREX_LIVE12_RSI_TESTER_LOCK_DRAFT_FILE = "QuantGod_ForexLive12RsiTesterLockDraft.json"
SIM_TARGET_EXECUTION_REVIEW_SUMMARY_FILE = "QuantGod_SimTargetExecutionReviewSummary.json"

SAFETY: dict[str, Any] = {
    "localOnly": True,
    "readOnlyDataPlane": True,
    "advisoryOnly": True,
    "dryRunOnly": True,
    "operatorApprovalRequired": True,
    "executionLaneSpecRequired": True,
    "separateExecutionLaneReviewRequired": True,
    "autoPromotionToLiveAllowed": False,
    "unattendedLiveExpansionAllowed": False,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "mt5OrderSendAllowed": False,
    "hfmCryptoExecutionAllowed": False,
    "copyTradeExecutionAllowed": False,
    "mossExecutionAllowed": False,
    "hyperliquidExecutionAllowed": False,
    "walletAuthorizationAllowed": False,
    "livePresetMutationAllowed": False,
    "livePilotActivationAllowed": False,
    "receiptWritesAllowed": False,
    "receiptFilesWritten": False,
    "autoDisableMutationAllowed": False,
    "eaRequestReaderAllowed": False,
    "eaRequestReaderEnabled": False,
    "eaRequestFilesRead": False,
    "eaRequestFilesConsumed": False,
    "eaOrderSendAllowed": False,
    "liveExecutionCutoverAllowed": False,
    "writesMt5Preset": False,
    "writesMt5OrderRequest": False,
    "telegramCommandExecutionAllowed": False,
    "webhookReceiverAllowed": False,
    "credentialStorageAllowed": False,
    "externalMarketRemoved": True,
}

EXECUTION_FLAG_KEYS = {
    "autoPromotionToLiveAllowed",
    "approvalCanUnlockLiveExecution",
    "canPromoteToLiveNow",
    "mt5PendingOrderIntentsWritten",
    "orderSendAllowed",
    "closeAllowed",
    "cancelAllowed",
    "modifyAllowed",
    "mt5OrderSendAllowed",
    "hfmCryptoExecutionAllowed",
    "copyTradeExecutionAllowed",
    "mossExecutionAllowed",
    "hyperliquidExecutionAllowed",
    "walletAuthorizationAllowed",
    "livePresetMutationAllowed",
    "livePilotActivationAllowed",
    "receiptWritesAllowed",
    "receiptFilesWritten",
    "autoDisableMutationAllowed",
    "eaRequestReaderAllowed",
    "eaRequestReaderEnabled",
    "eaRequestFilesRead",
    "eaRequestFilesConsumed",
    "eaOrderSendAllowed",
    "liveExecutionCutoverAllowed",
    "writesMt5Preset",
    "writesMt5OrderRequest",
    "requestWritesAllowed",
    "requestFilesWritten",
    "brokerCallsMade",
    "adapterExecutionAllowed",
    "telegramCommandExecutionAllowed",
    "webhookReceiverAllowed",
    "credentialStorageAllowed",
    "storesCredentials",
    "brokerExecutionAllowed",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def readiness_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / DOSSIER_FILE


def review_packet_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / REVIEW_PACKET_FILE


def approval_draft_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / APPROVAL_DRAFT_FILE


def approval_evidence_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / APPROVAL_EVIDENCE_REVIEW_FILE


def dry_run_plan_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / DRY_RUN_PLAN_FILE


def execution_lane_spec_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / EXECUTION_LANE_SPEC_FILE


def dry_run_intent_replay_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / DRY_RUN_INTENT_REPLAY_FILE


def runtime_preflight_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RUNTIME_PREFLIGHT_FILE


def order_request_contract_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / ORDER_REQUEST_CONTRACT_FILE


def sim_to_live_pipeline_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / SIM_TO_LIVE_PIPELINE_FILE


def execution_adapter_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / EXECUTION_ADAPTER_REVIEW_FILE


def live_evidence_intake_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_EVIDENCE_INTAKE_FILE


def live_promotion_candidates_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_PROMOTION_CANDIDATES_FILE


def live_promotion_controller_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_PROMOTION_CONTROLLER_FILE


def adapter_sandbox_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / ADAPTER_SANDBOX_REVIEW_FILE


def adapter_contract_validator_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / ADAPTER_CONTRACT_VALIDATOR_FILE


def sim_to_live_orchestrator_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / SIM_TO_LIVE_ORCHESTRATOR_FILE


def execution_adapter_harness_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / EXECUTION_ADAPTER_HARNESS_FILE


def live_pilot_activation_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_PILOT_ACTIVATION_REVIEW_FILE


def receipt_reconciliation_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RECEIPT_RECONCILIATION_REVIEW_FILE


def ea_request_reader_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / EA_REQUEST_READER_REVIEW_FILE


def live_execution_cutover_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_EXECUTION_CUTOVER_REVIEW_FILE


def live_execution_implementation_spec_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_EXECUTION_IMPLEMENTATION_SPEC_FILE


def live_execution_adapter_write_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_FILE


def ea_request_consumption_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / EA_REQUEST_CONSUMPTION_REVIEW_FILE


def broker_order_send_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / BROKER_ORDER_SEND_REVIEW_FILE


def live_execution_rollback_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_EXECUTION_ROLLBACK_REVIEW_FILE


def release_readiness_refresh_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RELEASE_READINESS_REFRESH_FILE


def release_minimal_diff_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RELEASE_MINIMAL_DIFF_REVIEW_FILE


def release_token_evidence_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RELEASE_TOKEN_EVIDENCE_REVIEW_FILE


def release_token_signoff_draft_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RELEASE_TOKEN_SIGNOFF_DRAFT_FILE


def release_token_signoff_input_template_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RELEASE_TOKEN_SIGNOFF_INPUT_TEMPLATE_FILE


def release_token_signoff_input_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RELEASE_TOKEN_SIGNOFF_INPUT_REVIEW_FILE


def release_token_signoff_handoff_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RELEASE_TOKEN_SIGNOFF_HANDOFF_FILE


def release_token_signoff_evidence_matrix_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / RELEASE_TOKEN_SIGNOFF_EVIDENCE_MATRIX_FILE


def live_execution_lane_selector_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / LIVE_EXECUTION_LANE_SELECTOR_FILE


def forex_live12_runtime_handoff_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_RUNTIME_HANDOFF_FILE


def forex_live12_capacity_expansion_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_CAPACITY_EXPANSION_REVIEW_FILE


def forex_live12_capacity_expansion_roadmap_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_CAPACITY_EXPANSION_ROADMAP_FILE


def forex_live12_micro_expansion_review_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_MICRO_EXPANSION_REVIEW_FILE


def forex_live12_rsi_repair_plan_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_RSI_REPAIR_PLAN_FILE


def forex_live12_rsi_shadow_candidate_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_RSI_SHADOW_CANDIDATE_FILE


def forex_live12_rsi_tester_request_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_RSI_TESTER_REQUEST_FILE


def forex_live12_rsi_tester_run_gate_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_RSI_TESTER_RUN_GATE_FILE


def forex_live12_rsi_candidate_promotion_gate_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_RSI_CANDIDATE_PROMOTION_GATE_FILE


def forex_live12_rsi_tester_lock_draft_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / FOREX_LIVE12_RSI_TESTER_LOCK_DRAFT_FILE


def sim_target_execution_review_summary_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "agent" / SIM_TARGET_EXECUTION_REVIEW_SUMMARY_FILE


def assert_no_execution_flags(payload: Any, path: str = "root") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in EXECUTION_FLAG_KEYS and bool(value):
                raise ValueError(f"truthy execution flag is forbidden at {path}.{key}")
            assert_no_execution_flags(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            assert_no_execution_flags(item, f"{path}[{idx}]")
