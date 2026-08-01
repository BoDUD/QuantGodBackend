#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
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
    from tools.live_automation_readiness.builder import (
        build_live_automation_readiness,
        read_live_automation_readiness,
    )
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
    from tools.champion_promotion_gate import (
        build_champion_promotion_gate,
        read_champion_promotion_gate,
    )
    from tools.champion_tester_forward_request import (
        build_champion_tester_forward_request,
        read_champion_tester_forward_request,
    )
    from tools.champion_tester_run_gate import (
        build_champion_tester_run_gate,
        read_champion_tester_run_gate,
    )
    from tools.champion_tester_lock_draft import (
        build_champion_tester_lock_draft,
        read_champion_tester_lock_draft,
    )
    from tools.ace_execution_candidate_pack import (
        build_ace_execution_candidate_pack,
        read_ace_execution_candidate_pack,
    )
    from tools.ace_upgrade_action_plan import (
        build_ace_upgrade_action_plan,
        read_ace_upgrade_action_plan,
    )
except ModuleNotFoundError:  # pragma: no cover
    from live_automation_readiness.adapter_sandbox import (
        build_adapter_sandbox_review_bundle,
        read_adapter_sandbox_review_bundle,
    )
    from live_automation_readiness.adapter_contract_validator import (
        build_adapter_contract_validator,
        read_adapter_contract_validator,
    )
    from live_automation_readiness.execution_adapter_harness import (
        build_execution_adapter_harness,
        read_execution_adapter_harness,
    )
    from live_automation_readiness.live_pilot_activation import (
        build_live_pilot_activation_review,
        read_live_pilot_activation_review,
    )
    from live_automation_readiness.receipt_reconciliation import (
        build_receipt_reconciliation_review,
        read_receipt_reconciliation_review,
    )
    from live_automation_readiness.ea_request_reader_review import (
        build_ea_request_reader_review,
        read_ea_request_reader_review,
    )
    from live_automation_readiness.live_execution_cutover import (
        build_live_execution_cutover_review,
        read_live_execution_cutover_review,
    )
    from live_automation_readiness.live_execution_implementation_spec import (
        build_live_execution_implementation_spec,
        read_live_execution_implementation_spec,
    )
    from live_automation_readiness.live_execution_adapter import (
        build_live_execution_adapter_write_review,
        read_live_execution_adapter_write_review,
    )
    from live_automation_readiness.ea_request_consumption import (
        build_ea_request_consumption_review,
        read_ea_request_consumption_review,
    )
    from live_automation_readiness.broker_order_send import (
        build_broker_order_send_review,
        read_broker_order_send_review,
    )
    from live_automation_readiness.live_execution_rollback import (
        build_live_execution_rollback_review,
        read_live_execution_rollback_review,
    )
    from live_automation_readiness.release_readiness_refresh import (
        build_release_readiness_refresh,
        read_release_readiness_refresh,
    )
    from live_automation_readiness.release_minimal_diff_review import (
        build_release_minimal_diff_review,
        read_release_minimal_diff_review,
    )
    from live_automation_readiness.release_token_evidence_review import (
        build_release_token_evidence_review,
        read_release_token_evidence_review,
    )
    from live_automation_readiness.release_token_signoff_draft import (
        build_release_token_signoff_draft,
        read_release_token_signoff_draft,
    )
    from live_automation_readiness.release_token_signoff_input_template import (
        build_release_token_signoff_input_template,
        read_release_token_signoff_input_template,
    )
    from live_automation_readiness.release_token_signoff_input_review import (
        build_release_token_signoff_input_review,
        read_release_token_signoff_input_review,
    )
    from live_automation_readiness.release_token_signoff_handoff import (
        build_release_token_signoff_handoff,
        read_release_token_signoff_handoff,
    )
    from live_automation_readiness.release_token_signoff_evidence_matrix import (
        build_release_token_signoff_evidence_matrix,
        read_release_token_signoff_evidence_matrix,
    )
    from live_automation_readiness.lane_selector import (
        build_live_execution_lane_selector,
        read_live_execution_lane_selector,
    )
    from live_automation_readiness.forex_live12_runtime_handoff import (
        build_forex_live12_runtime_handoff,
        read_forex_live12_runtime_handoff,
    )
    from live_automation_readiness.forex_live12_capacity_expansion_review import (
        build_forex_live12_capacity_expansion_review,
        read_forex_live12_capacity_expansion_review,
    )
    from live_automation_readiness.forex_live12_capacity_expansion_roadmap import (
        build_forex_live12_capacity_expansion_roadmap,
        read_forex_live12_capacity_expansion_roadmap,
    )
    from live_automation_readiness.forex_live12_micro_expansion_review import (
        build_forex_live12_micro_expansion_review,
        read_forex_live12_micro_expansion_review,
    )
    from live_automation_readiness.forex_live12_rsi_repair_plan import (
        build_forex_live12_rsi_repair_plan,
        read_forex_live12_rsi_repair_plan,
    )
    from live_automation_readiness.forex_live12_rsi_shadow_candidate import (
        build_forex_live12_rsi_shadow_candidate,
        read_forex_live12_rsi_shadow_candidate,
    )
    from live_automation_readiness.forex_live12_rsi_tester_request import (
        build_forex_live12_rsi_tester_request,
        read_forex_live12_rsi_tester_request,
    )
    from live_automation_readiness.forex_live12_rsi_tester_run_gate import (
        build_forex_live12_rsi_tester_run_gate,
        read_forex_live12_rsi_tester_run_gate,
    )
    from live_automation_readiness.forex_live12_rsi_candidate_promotion_gate import (
        build_forex_live12_rsi_candidate_promotion_gate,
        read_forex_live12_rsi_candidate_promotion_gate,
    )
    from live_automation_readiness.forex_live12_rsi_tester_lock_draft import (
        build_forex_live12_rsi_tester_lock_draft,
        read_forex_live12_rsi_tester_lock_draft,
    )
    from live_automation_readiness.sim_target_execution_review_summary import (
        build_sim_target_execution_review_summary,
        read_sim_target_execution_review_summary,
    )
    from live_automation_readiness.approval import (
        build_dry_run_live_execution_plan,
        build_live_operator_approval_evidence_review,
        build_live_operator_approval_draft,
        read_dry_run_live_execution_plan,
        read_live_operator_approval_evidence_review,
        read_live_operator_approval_draft,
    )
    from live_automation_readiness.builder import build_live_automation_readiness, read_live_automation_readiness
    from live_automation_readiness.dry_run_replay import build_dry_run_intent_replay, read_dry_run_intent_replay
    from live_automation_readiness.execution_adapter_review import build_execution_adapter_review, read_execution_adapter_review
    from live_automation_readiness.evidence_intake import build_live_evidence_intake, read_live_evidence_intake
    from live_automation_readiness.execution_lane import build_live_execution_lane_spec, read_live_execution_lane_spec
    from live_automation_readiness.order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
    from live_automation_readiness.orchestrator import build_sim_to_live_orchestrator, read_sim_to_live_orchestrator
    from live_automation_readiness.pipeline import build_sim_to_live_automation_pipeline, read_sim_to_live_automation_pipeline
    from live_automation_readiness.promotion_candidates import (
        build_live_promotion_candidates,
        read_live_promotion_candidates,
    )
    from live_automation_readiness.promotion_controller import (
        build_live_promotion_controller,
        read_live_promotion_controller,
    )
    from live_automation_readiness.preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
    from live_automation_readiness.review_packet import build_live_execution_review_packet, read_live_execution_review_packet
    from champion_promotion_gate import build_champion_promotion_gate, read_champion_promotion_gate
    from champion_tester_forward_request import build_champion_tester_forward_request, read_champion_tester_forward_request
    from champion_tester_run_gate import build_champion_tester_run_gate, read_champion_tester_run_gate
    from champion_tester_lock_draft import build_champion_tester_lock_draft, read_champion_tester_lock_draft
    from ace_execution_candidate_pack import build_ace_execution_candidate_pack, read_ace_execution_candidate_pack
    from ace_upgrade_action_plan import build_ace_upgrade_action_plan, read_ace_upgrade_action_plan


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod live automation readiness dossier")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    build.add_argument("--refresh-sources", action="store_true")
    build.add_argument("--extra-bases-root", action="append", default=[])
    review = sub.add_parser("review-packet")
    review.add_argument("--write", action="store_true")
    review.add_argument("--refresh-sources", action="store_true")
    review.add_argument("--extra-bases-root", action="append", default=[])
    approval = sub.add_parser("approval-draft")
    approval.add_argument("--write", action="store_true")
    approval.add_argument("--refresh-sources", action="store_true")
    approval.add_argument("--extra-bases-root", action="append", default=[])
    approval_evidence = sub.add_parser("approval-evidence")
    approval_evidence.add_argument("--write", action="store_true")
    approval_evidence.add_argument("--refresh-sources", action="store_true")
    approval_evidence.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    approval_evidence.add_argument("--extra-bases-root", action="append", default=[])
    plan = sub.add_parser("dry-run-plan")
    plan.add_argument("--write", action="store_true")
    plan.add_argument("--refresh-sources", action="store_true")
    plan.add_argument("--extra-bases-root", action="append", default=[])
    execution_lane = sub.add_parser("execution-lane-spec")
    execution_lane.add_argument("--write", action="store_true")
    execution_lane.add_argument("--refresh-sources", action="store_true")
    execution_lane.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    execution_lane.add_argument("--extra-bases-root", action="append", default=[])
    replay = sub.add_parser("dry-run-replay")
    replay.add_argument("--write", action="store_true")
    replay.add_argument("--refresh-sources", action="store_true")
    replay.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    replay.add_argument("--extra-bases-root", action="append", default=[])
    preflight = sub.add_parser("runtime-preflight")
    preflight.add_argument("--write", action="store_true")
    preflight.add_argument("--refresh-sources", action="store_true")
    preflight.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    preflight.add_argument("--extra-bases-root", action="append", default=[])
    order_contract = sub.add_parser("order-request-contract")
    order_contract.add_argument("--write", action="store_true")
    order_contract.add_argument("--refresh-sources", action="store_true")
    order_contract.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    order_contract.add_argument("--extra-bases-root", action="append", default=[])
    pipeline = sub.add_parser("pipeline")
    pipeline.add_argument("--write", action="store_true")
    pipeline.add_argument("--refresh-sources", action="store_true")
    pipeline.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    pipeline.add_argument("--extra-bases-root", action="append", default=[])
    adapter_review = sub.add_parser("adapter-review")
    adapter_review.add_argument("--write", action="store_true")
    adapter_review.add_argument("--refresh-sources", action="store_true")
    adapter_review.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    adapter_review.add_argument("--extra-bases-root", action="append", default=[])
    evidence_intake = sub.add_parser("evidence-intake")
    evidence_intake.add_argument("--write", action="store_true")
    evidence_intake.add_argument("--refresh-sources", action="store_true")
    evidence_intake.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    evidence_intake.add_argument("--extra-bases-root", action="append", default=[])
    promotion_candidates = sub.add_parser("promotion-candidates")
    promotion_candidates.add_argument("--write", action="store_true")
    promotion_candidates.add_argument("--refresh-sources", action="store_true")
    promotion_candidates.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    promotion_candidates.add_argument("--extra-bases-root", action="append", default=[])
    promotion_controller = sub.add_parser("promotion-controller")
    promotion_controller.add_argument("--write", action="store_true")
    promotion_controller.add_argument("--refresh-sources", action="store_true")
    promotion_controller.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    promotion_controller.add_argument("--extra-bases-root", action="append", default=[])
    adapter_sandbox = sub.add_parser("adapter-sandbox")
    adapter_sandbox.add_argument("--write", action="store_true")
    adapter_sandbox.add_argument("--refresh-sources", action="store_true")
    adapter_sandbox.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    adapter_sandbox.add_argument("--extra-bases-root", action="append", default=[])
    adapter_validator = sub.add_parser("adapter-contract-validator")
    adapter_validator.add_argument("--write", action="store_true")
    adapter_validator.add_argument("--refresh-sources", action="store_true")
    adapter_validator.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    adapter_validator.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    adapter_validator.add_argument("--extra-bases-root", action="append", default=[])
    orchestrator = sub.add_parser("orchestrator")
    orchestrator.add_argument("--write", action="store_true")
    orchestrator.add_argument("--refresh-sources", action="store_true")
    orchestrator.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    orchestrator.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    orchestrator.add_argument("--extra-bases-root", action="append", default=[])
    adapter_harness = sub.add_parser("adapter-harness")
    adapter_harness.add_argument("--write", action="store_true")
    adapter_harness.add_argument("--refresh-sources", action="store_true")
    adapter_harness.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    adapter_harness.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    adapter_harness.add_argument("--extra-bases-root", action="append", default=[])
    live_pilot_activation = sub.add_parser("live-pilot-activation-review")
    live_pilot_activation.add_argument("--write", action="store_true")
    live_pilot_activation.add_argument("--refresh-sources", action="store_true")
    live_pilot_activation.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    live_pilot_activation.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    live_pilot_activation.add_argument("--extra-bases-root", action="append", default=[])
    receipt_reconciliation = sub.add_parser("receipt-reconciliation-review")
    receipt_reconciliation.add_argument("--write", action="store_true")
    receipt_reconciliation.add_argument("--refresh-sources", action="store_true")
    receipt_reconciliation.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    receipt_reconciliation.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    receipt_reconciliation.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    receipt_reconciliation.add_argument("--extra-bases-root", action="append", default=[])
    ea_request_reader = sub.add_parser("ea-request-reader-review")
    ea_request_reader.add_argument("--write", action="store_true")
    ea_request_reader.add_argument("--refresh-sources", action="store_true")
    ea_request_reader.add_argument("--ea-source-path", default=os.environ.get("QG_EA_SOURCE_PATH", ""))
    ea_request_reader.add_argument("--ea-status-json", default=os.environ.get("QG_EA_REQUEST_READER_STATUS_JSON", ""))
    ea_request_reader.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    ea_request_reader.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    ea_request_reader.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    ea_request_reader.add_argument("--extra-bases-root", action="append", default=[])
    live_cutover = sub.add_parser("live-execution-cutover-review")
    live_cutover.add_argument("--write", action="store_true")
    live_cutover.add_argument("--refresh-sources", action="store_true")
    live_cutover.add_argument("--ea-source-path", default=os.environ.get("QG_EA_SOURCE_PATH", ""))
    live_cutover.add_argument("--ea-status-json", default=os.environ.get("QG_EA_REQUEST_READER_STATUS_JSON", ""))
    live_cutover.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    live_cutover.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    live_cutover.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    live_cutover.add_argument("--extra-bases-root", action="append", default=[])
    live_impl = sub.add_parser("live-execution-implementation-spec")
    live_impl.add_argument("--write", action="store_true")
    live_impl.add_argument("--refresh-sources", action="store_true")
    live_impl.add_argument("--ea-source-path", default=os.environ.get("QG_EA_SOURCE_PATH", ""))
    live_impl.add_argument("--ea-status-json", default=os.environ.get("QG_EA_REQUEST_READER_STATUS_JSON", ""))
    live_impl.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    live_impl.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    live_impl.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    live_impl.add_argument("--extra-bases-root", action="append", default=[])
    live_adapter = sub.add_parser("live-execution-adapter-write-review")
    live_adapter.add_argument("--write", action="store_true")
    live_adapter.add_argument("--refresh-sources", action="store_true")
    live_adapter.add_argument("--ea-source-path", default=os.environ.get("QG_EA_SOURCE_PATH", ""))
    live_adapter.add_argument("--ea-status-json", default=os.environ.get("QG_EA_REQUEST_READER_STATUS_JSON", ""))
    live_adapter.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    live_adapter.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    live_adapter.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    live_adapter.add_argument("--extra-bases-root", action="append", default=[])
    ea_consumption = sub.add_parser("ea-request-consumption-review")
    ea_consumption.add_argument("--write", action="store_true")
    ea_consumption.add_argument("--refresh-sources", action="store_true")
    ea_consumption.add_argument("--ea-source-path", default=os.environ.get("QG_EA_SOURCE_PATH", ""))
    ea_consumption.add_argument("--ea-status-json", default=os.environ.get("QG_EA_REQUEST_READER_STATUS_JSON", ""))
    ea_consumption.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    ea_consumption.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    ea_consumption.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    ea_consumption.add_argument("--extra-bases-root", action="append", default=[])
    broker_send = sub.add_parser("broker-order-send-review")
    broker_send.add_argument("--write", action="store_true")
    broker_send.add_argument("--refresh-sources", action="store_true")
    broker_send.add_argument("--ea-source-path", default=os.environ.get("QG_EA_SOURCE_PATH", ""))
    broker_send.add_argument("--ea-status-json", default=os.environ.get("QG_EA_REQUEST_READER_STATUS_JSON", ""))
    broker_send.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    broker_send.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    broker_send.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    broker_send.add_argument("--extra-bases-root", action="append", default=[])
    rollback = sub.add_parser("live-execution-rollback-review")
    rollback.add_argument("--write", action="store_true")
    rollback.add_argument("--refresh-sources", action="store_true")
    rollback.add_argument("--ea-source-path", default=os.environ.get("QG_EA_SOURCE_PATH", ""))
    rollback.add_argument("--ea-status-json", default=os.environ.get("QG_EA_REQUEST_READER_STATUS_JSON", ""))
    rollback.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    rollback.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    rollback.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    rollback.add_argument("--extra-bases-root", action="append", default=[])
    release_refresh = sub.add_parser("release-readiness-refresh")
    release_refresh.add_argument("--write", action="store_true")
    release_refresh.add_argument("--refresh-sources", action="store_true")
    release_refresh.add_argument("--ea-source-path", default=os.environ.get("QG_EA_SOURCE_PATH", ""))
    release_refresh.add_argument("--ea-status-json", default=os.environ.get("QG_EA_REQUEST_READER_STATUS_JSON", ""))
    release_refresh.add_argument("--receipt-json", default=os.environ.get("QG_RECEIPT_JSON", ""))
    release_refresh.add_argument("--request-json", default=os.environ.get("QG_ADAPTER_REQUEST_JSON", ""))
    release_refresh.add_argument("--operator-approval-json", default=os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""))
    release_refresh.add_argument("--extra-bases-root", action="append", default=[])
    release_minimal_diff = sub.add_parser("release-minimal-diff-review")
    release_minimal_diff.add_argument("--write", action="store_true")
    release_token_evidence = sub.add_parser("release-token-evidence-review")
    release_token_evidence.add_argument("--write", action="store_true")
    release_token_signoff = sub.add_parser("release-token-signoff-draft")
    release_token_signoff.add_argument("--write", action="store_true")
    release_signoff_template = sub.add_parser("release-token-signoff-input-template")
    release_signoff_template.add_argument("--write", action="store_true")
    release_signoff_input = sub.add_parser("release-token-signoff-input-review")
    release_signoff_input.add_argument("--write", action="store_true")
    release_signoff_input.add_argument("--signoff-json", default=os.environ.get("QG_RELEASE_TOKEN_SIGNOFF_JSON", ""))
    release_signoff_handoff = sub.add_parser("release-token-signoff-handoff")
    release_signoff_handoff.add_argument("--write", action="store_true")
    release_signoff_evidence_matrix = sub.add_parser("release-token-signoff-evidence-matrix")
    release_signoff_evidence_matrix.add_argument("--write", action="store_true")
    lane_selector = sub.add_parser("lane-selector")
    lane_selector.add_argument("--write", action="store_true")
    lane_selector.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    lane_selector.add_argument("--profit-target-json", default=os.environ.get("QG_PROFIT_TARGET_JSON", ""))
    forex_handoff = sub.add_parser("forex-live12-runtime-handoff")
    forex_handoff.add_argument("--write", action="store_true")
    forex_handoff.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_capacity = sub.add_parser("forex-live12-capacity-expansion-review")
    forex_capacity.add_argument("--write", action="store_true")
    forex_capacity.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_capacity.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_capacity_roadmap = sub.add_parser("forex-live12-capacity-expansion-roadmap")
    forex_capacity_roadmap.add_argument("--write", action="store_true")
    forex_capacity_roadmap.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_capacity_roadmap.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_micro = sub.add_parser("forex-live12-micro-expansion-review")
    forex_micro.add_argument("--write", action="store_true")
    forex_micro.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_micro.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_rsi_repair = sub.add_parser("forex-live12-rsi-repair-plan")
    forex_rsi_repair.add_argument("--write", action="store_true")
    forex_rsi_repair.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_rsi_repair.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_rsi_candidate = sub.add_parser("forex-live12-rsi-shadow-candidate")
    forex_rsi_candidate.add_argument("--write", action="store_true")
    forex_rsi_candidate.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_rsi_candidate.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_rsi_tester = sub.add_parser("forex-live12-rsi-tester-request")
    forex_rsi_tester.add_argument("--write", action="store_true")
    forex_rsi_tester.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_rsi_tester.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_rsi_tester_gate = sub.add_parser("forex-live12-rsi-tester-run-gate")
    forex_rsi_tester_gate.add_argument("--write", action="store_true")
    forex_rsi_tester_gate.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_rsi_tester_gate.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_rsi_candidate_gate = sub.add_parser("forex-live12-rsi-candidate-promotion-gate")
    forex_rsi_candidate_gate.add_argument("--write", action="store_true")
    forex_rsi_candidate_gate.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_rsi_candidate_gate.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    forex_rsi_tester_lock_draft = sub.add_parser("forex-live12-rsi-tester-lock-draft")
    forex_rsi_tester_lock_draft.add_argument("--write", action="store_true")
    forex_rsi_tester_lock_draft.add_argument("--requested-max-total-trades", type=int, default=10)
    forex_rsi_tester_lock_draft.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    sim_target_summary = sub.add_parser("sim-target-execution-review-summary")
    sim_target_summary.add_argument("--write", action="store_true")
    sim_target_summary.add_argument("--target-usd", type=float, default=50.0)
    sim_target_summary.add_argument("--requested-max-total-trades", type=int, default=10)
    sim_target_summary.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    ace_candidate_pack = sub.add_parser("ace-execution-candidate-pack")
    ace_candidate_pack.add_argument("--write", action="store_true")
    ace_upgrade_action_plan = sub.add_parser("ace-upgrade-action-plan")
    ace_upgrade_action_plan.add_argument("--write", action="store_true")
    champion_gate = sub.add_parser("champion-promotion-gate")
    champion_gate.add_argument("--write", action="store_true")
    champion_tester_forward = sub.add_parser("champion-tester-forward-request")
    champion_tester_forward.add_argument("--write", action="store_true")
    champion_tester_run_gate = sub.add_parser("champion-tester-run-gate")
    champion_tester_run_gate.add_argument("--write", action="store_true")
    champion_tester_run_gate.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    champion_tester_run_gate.add_argument("--allow-outside-window", action="store_true")
    champion_tester_lock_draft = sub.add_parser("champion-tester-lock-draft")
    champion_tester_lock_draft.add_argument("--write", action="store_true")
    champion_tester_lock_draft.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    sub.add_parser("review-packet-status")
    sub.add_parser("approval-draft-status")
    sub.add_parser("approval-evidence-status")
    sub.add_parser("dry-run-plan-status")
    sub.add_parser("execution-lane-spec-status")
    sub.add_parser("dry-run-replay-status")
    sub.add_parser("runtime-preflight-status")
    sub.add_parser("order-request-contract-status")
    sub.add_parser("pipeline-status")
    sub.add_parser("adapter-review-status")
    sub.add_parser("evidence-intake-status")
    sub.add_parser("promotion-candidates-status")
    sub.add_parser("promotion-controller-status")
    sub.add_parser("adapter-sandbox-status")
    sub.add_parser("adapter-contract-validator-status")
    sub.add_parser("orchestrator-status")
    sub.add_parser("adapter-harness-status")
    sub.add_parser("live-pilot-activation-review-status")
    sub.add_parser("receipt-reconciliation-review-status")
    sub.add_parser("ea-request-reader-review-status")
    sub.add_parser("live-execution-cutover-review-status")
    sub.add_parser("live-execution-implementation-spec-status")
    sub.add_parser("live-execution-adapter-write-review-status")
    sub.add_parser("ea-request-consumption-review-status")
    sub.add_parser("broker-order-send-review-status")
    sub.add_parser("live-execution-rollback-review-status")
    sub.add_parser("release-readiness-refresh-status")
    sub.add_parser("release-minimal-diff-review-status")
    sub.add_parser("release-token-evidence-review-status")
    sub.add_parser("release-token-signoff-draft-status")
    sub.add_parser("release-token-signoff-input-template-status")
    sub.add_parser("release-token-signoff-input-review-status")
    sub.add_parser("release-token-signoff-handoff-status")
    sub.add_parser("release-token-signoff-evidence-matrix-status")
    sub.add_parser("lane-selector-status")
    sub.add_parser("forex-live12-runtime-handoff-status")
    sub.add_parser("forex-live12-capacity-expansion-review-status")
    sub.add_parser("forex-live12-capacity-expansion-roadmap-status")
    sub.add_parser("forex-live12-micro-expansion-review-status")
    sub.add_parser("forex-live12-rsi-repair-plan-status")
    sub.add_parser("forex-live12-rsi-shadow-candidate-status")
    sub.add_parser("forex-live12-rsi-tester-request-status")
    sub.add_parser("forex-live12-rsi-tester-run-gate-status")
    sub.add_parser("forex-live12-rsi-candidate-promotion-gate-status")
    sub.add_parser("forex-live12-rsi-tester-lock-draft-status")
    sub.add_parser("sim-target-execution-review-summary-status")
    sub.add_parser("ace-execution-candidate-pack-status")
    sub.add_parser("ace-upgrade-action-plan-status")
    sub.add_parser("champion-promotion-gate-status")
    sub.add_parser("champion-tester-forward-request-status")
    sub.add_parser("champion-tester-run-gate-status")
    sub.add_parser("champion-tester-lock-draft-status")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(build_live_automation_readiness(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "status":
        return emit(read_live_automation_readiness(runtime_dir))
    if args.command == "review-packet":
        return emit(build_live_execution_review_packet(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "review-packet-status":
        return emit(read_live_execution_review_packet(runtime_dir))
    if args.command == "approval-draft":
        return emit(build_live_operator_approval_draft(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "approval-draft-status":
        return emit(read_live_operator_approval_draft(runtime_dir))
    if args.command == "approval-evidence":
        return emit(build_live_operator_approval_evidence_review(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "approval-evidence-status":
        return emit(read_live_operator_approval_evidence_review(runtime_dir))
    if args.command == "dry-run-plan":
        return emit(build_dry_run_live_execution_plan(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "dry-run-plan-status":
        return emit(read_dry_run_live_execution_plan(runtime_dir))
    if args.command == "execution-lane-spec":
        return emit(build_live_execution_lane_spec(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "execution-lane-spec-status":
        return emit(read_live_execution_lane_spec(runtime_dir))
    if args.command == "dry-run-replay":
        return emit(build_dry_run_intent_replay(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "dry-run-replay-status":
        return emit(read_dry_run_intent_replay(runtime_dir))
    if args.command == "runtime-preflight":
        return emit(build_live_runtime_preflight_probe(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "runtime-preflight-status":
        return emit(read_live_runtime_preflight_probe(runtime_dir))
    if args.command == "order-request-contract":
        return emit(build_mt5_order_request_contract(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "order-request-contract-status":
        return emit(read_mt5_order_request_contract(runtime_dir))
    if args.command == "pipeline":
        return emit(build_sim_to_live_automation_pipeline(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "pipeline-status":
        return emit(read_sim_to_live_automation_pipeline(runtime_dir))
    if args.command == "adapter-review":
        return emit(build_execution_adapter_review(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "adapter-review-status":
        return emit(read_execution_adapter_review(runtime_dir))
    if args.command == "evidence-intake":
        return emit(build_live_evidence_intake(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "evidence-intake-status":
        return emit(read_live_evidence_intake(runtime_dir))
    if args.command == "promotion-candidates":
        return emit(build_live_promotion_candidates(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "promotion-candidates-status":
        return emit(read_live_promotion_candidates(runtime_dir))
    if args.command == "promotion-controller":
        return emit(build_live_promotion_controller(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "promotion-controller-status":
        return emit(read_live_promotion_controller(runtime_dir))
    if args.command == "adapter-sandbox":
        return emit(build_adapter_sandbox_review_bundle(
            runtime_dir,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "adapter-sandbox-status":
        return emit(read_adapter_sandbox_review_bundle(runtime_dir))
    if args.command == "adapter-contract-validator":
        return emit(build_adapter_contract_validator(
            runtime_dir,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "adapter-contract-validator-status":
        return emit(read_adapter_contract_validator(runtime_dir))
    if args.command == "orchestrator":
        return emit(build_sim_to_live_orchestrator(
            runtime_dir,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "orchestrator-status":
        return emit(read_sim_to_live_orchestrator(runtime_dir))
    if args.command == "adapter-harness":
        return emit(build_execution_adapter_harness(
            runtime_dir,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "adapter-harness-status":
        return emit(read_execution_adapter_harness(runtime_dir))
    if args.command == "live-pilot-activation-review":
        return emit(build_live_pilot_activation_review(
            runtime_dir,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "live-pilot-activation-review-status":
        return emit(read_live_pilot_activation_review(runtime_dir))
    if args.command == "receipt-reconciliation-review":
        return emit(build_receipt_reconciliation_review(
            runtime_dir,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "receipt-reconciliation-review-status":
        return emit(read_receipt_reconciliation_review(runtime_dir))
    if args.command == "ea-request-reader-review":
        return emit(build_ea_request_reader_review(
            runtime_dir,
            ea_source_path=args.ea_source_path,
            ea_status_json=args.ea_status_json,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "ea-request-reader-review-status":
        return emit(read_ea_request_reader_review(runtime_dir))
    if args.command == "live-execution-cutover-review":
        return emit(build_live_execution_cutover_review(
            runtime_dir,
            ea_source_path=args.ea_source_path,
            ea_status_json=args.ea_status_json,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "live-execution-cutover-review-status":
        return emit(read_live_execution_cutover_review(runtime_dir))
    if args.command == "live-execution-implementation-spec":
        return emit(build_live_execution_implementation_spec(
            runtime_dir,
            ea_source_path=args.ea_source_path,
            ea_status_json=args.ea_status_json,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "live-execution-implementation-spec-status":
        return emit(read_live_execution_implementation_spec(runtime_dir))
    if args.command == "live-execution-adapter-write-review":
        return emit(build_live_execution_adapter_write_review(
            runtime_dir,
            ea_source_path=args.ea_source_path,
            ea_status_json=args.ea_status_json,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "live-execution-adapter-write-review-status":
        return emit(read_live_execution_adapter_write_review(runtime_dir))
    if args.command == "ea-request-consumption-review":
        return emit(build_ea_request_consumption_review(
            runtime_dir,
            ea_source_path=args.ea_source_path,
            ea_status_json=args.ea_status_json,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "ea-request-consumption-review-status":
        return emit(read_ea_request_consumption_review(runtime_dir))
    if args.command == "broker-order-send-review":
        return emit(build_broker_order_send_review(
            runtime_dir,
            ea_source_path=args.ea_source_path,
            ea_status_json=args.ea_status_json,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "broker-order-send-review-status":
        return emit(read_broker_order_send_review(runtime_dir))
    if args.command == "live-execution-rollback-review":
        return emit(build_live_execution_rollback_review(
            runtime_dir,
            ea_source_path=args.ea_source_path,
            ea_status_json=args.ea_status_json,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "live-execution-rollback-review-status":
        return emit(read_live_execution_rollback_review(runtime_dir))
    if args.command == "release-readiness-refresh":
        return emit(build_release_readiness_refresh(
            runtime_dir,
            ea_source_path=args.ea_source_path,
            ea_status_json=args.ea_status_json,
            receipt_json=args.receipt_json,
            request_json=args.request_json,
            write=args.write,
            refresh_sources=args.refresh_sources,
            operator_approval_json=args.operator_approval_json,
            extra_bases_roots=args.extra_bases_root,
        ))
    if args.command == "release-readiness-refresh-status":
        return emit(read_release_readiness_refresh(runtime_dir))
    if args.command == "release-minimal-diff-review":
        return emit(build_release_minimal_diff_review(runtime_dir, write=args.write))
    if args.command == "release-minimal-diff-review-status":
        return emit(read_release_minimal_diff_review(runtime_dir))
    if args.command == "release-token-evidence-review":
        return emit(build_release_token_evidence_review(runtime_dir, write=args.write))
    if args.command == "release-token-evidence-review-status":
        return emit(read_release_token_evidence_review(runtime_dir))
    if args.command == "release-token-signoff-draft":
        return emit(build_release_token_signoff_draft(runtime_dir, write=args.write))
    if args.command == "release-token-signoff-draft-status":
        return emit(read_release_token_signoff_draft(runtime_dir))
    if args.command == "release-token-signoff-input-template":
        return emit(build_release_token_signoff_input_template(runtime_dir, write=args.write))
    if args.command == "release-token-signoff-input-template-status":
        return emit(read_release_token_signoff_input_template(runtime_dir))
    if args.command == "release-token-signoff-input-review":
        return emit(build_release_token_signoff_input_review(
            runtime_dir,
            signoff_json=args.signoff_json,
            write=args.write,
        ))
    if args.command == "release-token-signoff-input-review-status":
        return emit(read_release_token_signoff_input_review(runtime_dir))
    if args.command == "release-token-signoff-handoff":
        return emit(build_release_token_signoff_handoff(runtime_dir, write=args.write))
    if args.command == "release-token-signoff-handoff-status":
        return emit(read_release_token_signoff_handoff(runtime_dir))
    if args.command == "release-token-signoff-evidence-matrix":
        return emit(build_release_token_signoff_evidence_matrix(runtime_dir, write=args.write))
    if args.command == "release-token-signoff-evidence-matrix-status":
        return emit(read_release_token_signoff_evidence_matrix(runtime_dir))
    if args.command == "lane-selector":
        return emit(build_live_execution_lane_selector(
            runtime_dir,
            primary_dashboard_json=args.primary_dashboard_json,
            profit_target_json=args.profit_target_json,
            write=args.write,
        ))
    if args.command == "lane-selector-status":
        return emit(read_live_execution_lane_selector(runtime_dir))
    if args.command == "forex-live12-runtime-handoff":
        return emit(build_forex_live12_runtime_handoff(
            runtime_dir,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-runtime-handoff-status":
        return emit(read_forex_live12_runtime_handoff(runtime_dir))
    if args.command == "forex-live12-capacity-expansion-review":
        return emit(build_forex_live12_capacity_expansion_review(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-capacity-expansion-review-status":
        return emit(read_forex_live12_capacity_expansion_review(runtime_dir))
    if args.command == "forex-live12-capacity-expansion-roadmap":
        return emit(build_forex_live12_capacity_expansion_roadmap(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-capacity-expansion-roadmap-status":
        return emit(read_forex_live12_capacity_expansion_roadmap(runtime_dir))
    if args.command == "forex-live12-micro-expansion-review":
        return emit(build_forex_live12_micro_expansion_review(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-micro-expansion-review-status":
        return emit(read_forex_live12_micro_expansion_review(runtime_dir))
    if args.command == "forex-live12-rsi-repair-plan":
        return emit(build_forex_live12_rsi_repair_plan(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-rsi-repair-plan-status":
        return emit(read_forex_live12_rsi_repair_plan(runtime_dir))
    if args.command == "forex-live12-rsi-shadow-candidate":
        return emit(build_forex_live12_rsi_shadow_candidate(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-rsi-shadow-candidate-status":
        return emit(read_forex_live12_rsi_shadow_candidate(runtime_dir))
    if args.command == "forex-live12-rsi-tester-request":
        return emit(build_forex_live12_rsi_tester_request(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-rsi-tester-request-status":
        return emit(read_forex_live12_rsi_tester_request(runtime_dir))
    if args.command == "forex-live12-rsi-tester-run-gate":
        return emit(build_forex_live12_rsi_tester_run_gate(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-rsi-tester-run-gate-status":
        return emit(read_forex_live12_rsi_tester_run_gate(runtime_dir))
    if args.command == "forex-live12-rsi-candidate-promotion-gate":
        return emit(build_forex_live12_rsi_candidate_promotion_gate(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-rsi-candidate-promotion-gate-status":
        return emit(read_forex_live12_rsi_candidate_promotion_gate(runtime_dir))
    if args.command == "forex-live12-rsi-tester-lock-draft":
        return emit(build_forex_live12_rsi_tester_lock_draft(
            runtime_dir,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "forex-live12-rsi-tester-lock-draft-status":
        return emit(read_forex_live12_rsi_tester_lock_draft(runtime_dir))
    if args.command == "sim-target-execution-review-summary":
        return emit(build_sim_target_execution_review_summary(
            runtime_dir,
            target_usd=args.target_usd,
            requested_max_total_trades=args.requested_max_total_trades,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "sim-target-execution-review-summary-status":
        return emit(read_sim_target_execution_review_summary(runtime_dir))
    if args.command == "ace-execution-candidate-pack":
        return emit(build_ace_execution_candidate_pack(runtime_dir, write=args.write))
    if args.command == "ace-execution-candidate-pack-status":
        return emit(read_ace_execution_candidate_pack(runtime_dir))
    if args.command == "ace-upgrade-action-plan":
        return emit(build_ace_upgrade_action_plan(runtime_dir, write=args.write))
    if args.command == "ace-upgrade-action-plan-status":
        return emit(read_ace_upgrade_action_plan(runtime_dir))
    if args.command == "champion-promotion-gate":
        return emit(build_champion_promotion_gate(runtime_dir, write=args.write))
    if args.command == "champion-promotion-gate-status":
        return emit(read_champion_promotion_gate(runtime_dir))
    if args.command == "champion-tester-forward-request":
        return emit(build_champion_tester_forward_request(runtime_dir, write=args.write))
    if args.command == "champion-tester-forward-request-status":
        return emit(read_champion_tester_forward_request(runtime_dir))
    if args.command == "champion-tester-run-gate":
        return emit(build_champion_tester_run_gate(
            runtime_dir,
            primary_dashboard_json=args.primary_dashboard_json,
            allow_outside_window=args.allow_outside_window,
            write=args.write,
        ))
    if args.command == "champion-tester-run-gate-status":
        return emit(read_champion_tester_run_gate(runtime_dir))
    if args.command == "champion-tester-lock-draft":
        return emit(build_champion_tester_lock_draft(
            runtime_dir,
            primary_dashboard_json=args.primary_dashboard_json,
            write=args.write,
        ))
    if args.command == "champion-tester-lock-draft-status":
        return emit(read_champion_tester_lock_draft(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
