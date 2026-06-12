from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapter_contract_validator import build_adapter_contract_validator, read_adapter_contract_validator
from .adapter_sandbox import build_adapter_sandbox_review_bundle, read_adapter_sandbox_review_bundle
from .approval import (
    build_dry_run_live_execution_plan,
    build_live_operator_approval_draft,
    build_live_operator_approval_evidence_review,
    read_dry_run_live_execution_plan,
    read_live_operator_approval_draft,
    read_live_operator_approval_evidence_review,
)
from .approval_context import operator_approval_json_for_refresh
from .builder import build_live_automation_readiness, read_live_automation_readiness
from .dry_run_replay import build_dry_run_intent_replay, read_dry_run_intent_replay
from .evidence_intake import build_live_evidence_intake, read_live_evidence_intake
from .execution_adapter_review import build_execution_adapter_review, read_execution_adapter_review
from .execution_lane import build_live_execution_lane_spec, read_live_execution_lane_spec
from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .pipeline import build_sim_to_live_automation_pipeline, read_sim_to_live_automation_pipeline
from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
from .promotion_candidates import build_live_promotion_candidates, read_live_promotion_candidates
from .promotion_controller import build_live_promotion_controller, read_live_promotion_controller
from .review_packet import build_live_execution_review_packet, read_live_execution_review_packet
from .schema import (
    SAFETY,
    SIM_TO_LIVE_ORCHESTRATOR_SCHEMA_VERSION,
    adapter_contract_validator_path,
    adapter_sandbox_review_path,
    approval_draft_path,
    approval_evidence_review_path,
    broker_order_send_review_path,
    assert_no_execution_flags,
    dry_run_intent_replay_path,
    dry_run_plan_path,
    ea_request_consumption_review_path,
    ea_request_reader_review_path,
    execution_adapter_harness_path,
    execution_adapter_review_path,
    execution_lane_spec_path,
    live_pilot_activation_review_path,
    live_execution_cutover_review_path,
    live_execution_adapter_write_review_path,
    live_execution_rollback_review_path,
    live_evidence_intake_path,
    live_promotion_candidates_path,
    live_promotion_controller_path,
    order_request_contract_path,
    receipt_reconciliation_review_path,
    readiness_path,
    review_packet_path,
    runtime_preflight_path,
    sim_to_live_pipeline_path,
    sim_to_live_orchestrator_path,
    utc_now_iso,
)

try:
    from tools.hfm_crypto_cfd.filled_input_validator import (
        build_hfm_crypto_filled_input_validator,
        read_hfm_crypto_filled_input_validator,
    )
    from tools.hfm_crypto_cfd.schema import filled_input_validator_path as hfm_filled_input_validator_path
except ModuleNotFoundError:  # pragma: no cover
    from hfm_crypto_cfd.filled_input_validator import (
        build_hfm_crypto_filled_input_validator,
        read_hfm_crypto_filled_input_validator,
    )
    from hfm_crypto_cfd.schema import filled_input_validator_path as hfm_filled_input_validator_path


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    return row


def _artifact_summary(payload: dict[str, Any], extra_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    keys = (
        "schema",
        "status",
        "statusZh",
        "generatedAt",
        "generatedAtIso",
        "nextRequiredActionZh",
        *extra_keys,
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _stage(
    stage_id: str,
    label_zh: str,
    payload: dict[str, Any],
    *,
    passed: bool,
    blocking: bool = True,
    next_action_zh: str = "",
) -> dict[str, Any]:
    blockers = [row for row in _safe_list(payload.get("blockers")) if isinstance(row, dict)]
    return {
        "stageId": stage_id,
        "labelZh": label_zh,
        "status": payload.get("status", ""),
        "statusZh": payload.get("statusZh", ""),
        "passed": bool(passed),
        "blocking": bool(blocking),
        "blockerCodes": [] if passed else [row.get("code") for row in blockers[:12]],
        "nextRequiredActionZh": payload.get("nextRequiredActionZh", "") or next_action_zh,
    }


def _ready_or_execution_mode_only(payload: dict[str, Any], ready_key: str, data_plane_key: str, execution_key: str = "executionModeOnlyBlocked") -> bool:
    payload = _safe_dict(payload)
    return bool(payload.get(ready_key) or (payload.get(data_plane_key) and payload.get(execution_key)))


def _first_blocking_stage(stages: list[dict[str, Any]]) -> dict[str, Any]:
    for row in stages:
        if row.get("blocking") and not row.get("passed"):
            return row
    return {}


def _normalize_autonomy_stage_rows(
    stages: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    approval = _safe_dict(artifacts.get("approvalEvidence"))
    approval_accepted = bool(approval.get("operatorApprovalProvided"))
    if not approval_accepted:
        return stages
    resolved_next_action = (
        "审批证据已验收；不再等待用户确认。当前继续卡在执行模式闸门和 release token，"
        "不会写 MT5 request、不会调用 broker。"
    )
    resolved_stage_ids = {"promotion_controller", "review_packet", "approval_evidence"}
    normalized = []
    for row in stages:
        if row.get("stageId") in resolved_stage_ids and row.get("passed"):
            row = {
                **row,
                "nextRequiredActionZh": resolved_next_action,
                "approvalWaitResolved": True,
            }
            if row.get("stageId") == "approval_evidence":
                row["statusZh"] = row.get("statusZh") or "审批证据已验收，但真实执行仍关闭"
        normalized.append(row)
    return normalized


def _saved_or_built(
    runtime_dir: Path,
    path: Path,
    read_fn,
    build_fn,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    explicit_inputs_present = any(
        bool(kwargs.get(key))
        for key in (
            "operator_approval_json",
            "request_json",
            "moss_backtest_json",
            "hfm_simulation_profile_json",
            "hfm_contract_spec_json",
        )
    ) or bool(kwargs.get("extra_bases_roots"))
    if not bool(kwargs.get("refresh_sources")) and not explicit_inputs_present and path.exists() and path.is_file():
        payload = read_fn(runtime_dir)
    else:
        payload = build_fn(runtime_dir, **kwargs)
    return payload if isinstance(payload, dict) else {}


def _read_existing_artifact(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_artifacts(
    runtime_dir: Path,
    *,
    request_json: str,
    operator_approval_json: str,
    write: bool,
    refresh_sources: bool,
    moss_backtest_json: str,
    hfm_simulation_profile_json: str,
    hfm_contract_spec_json: str,
    extra_bases_roots: list[str],
) -> dict[str, dict[str, Any]]:
    common = {
        "write": write,
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots,
    }
    approval = {**common, "operator_approval_json": operator_approval_json}
    adapter = {**approval, "request_json": request_json}
    hfm_filled = (
        read_hfm_crypto_filled_input_validator(runtime_dir)
        if not refresh_sources and hfm_filled_input_validator_path(runtime_dir).exists()
        else build_hfm_crypto_filled_input_validator(runtime_dir, write=write)
    )
    return {
        "hfmFilledInputValidator": hfm_filled,
        "evidenceIntake": _saved_or_built(runtime_dir, live_evidence_intake_path(runtime_dir), read_live_evidence_intake, build_live_evidence_intake, approval),
        "readiness": _saved_or_built(runtime_dir, readiness_path(runtime_dir), read_live_automation_readiness, build_live_automation_readiness, common),
        "promotionCandidates": _saved_or_built(runtime_dir, live_promotion_candidates_path(runtime_dir), read_live_promotion_candidates, build_live_promotion_candidates, approval),
        "promotionController": _saved_or_built(runtime_dir, live_promotion_controller_path(runtime_dir), read_live_promotion_controller, build_live_promotion_controller, approval),
        "reviewPacket": _saved_or_built(runtime_dir, review_packet_path(runtime_dir), read_live_execution_review_packet, build_live_execution_review_packet, common),
        "approvalDraft": _saved_or_built(runtime_dir, approval_draft_path(runtime_dir), read_live_operator_approval_draft, build_live_operator_approval_draft, common),
        "approvalEvidence": _saved_or_built(runtime_dir, approval_evidence_review_path(runtime_dir), read_live_operator_approval_evidence_review, build_live_operator_approval_evidence_review, approval),
        "dryRunPlan": _saved_or_built(runtime_dir, dry_run_plan_path(runtime_dir), read_dry_run_live_execution_plan, build_dry_run_live_execution_plan, common),
        "executionLaneSpec": _saved_or_built(runtime_dir, execution_lane_spec_path(runtime_dir), read_live_execution_lane_spec, build_live_execution_lane_spec, approval),
        "dryRunReplay": _saved_or_built(runtime_dir, dry_run_intent_replay_path(runtime_dir), read_dry_run_intent_replay, build_dry_run_intent_replay, approval),
        "runtimePreflight": _saved_or_built(runtime_dir, runtime_preflight_path(runtime_dir), read_live_runtime_preflight_probe, build_live_runtime_preflight_probe, approval),
        "orderRequestContract": _saved_or_built(runtime_dir, order_request_contract_path(runtime_dir), read_mt5_order_request_contract, build_mt5_order_request_contract, approval),
        "pipeline": _saved_or_built(runtime_dir, sim_to_live_pipeline_path(runtime_dir), read_sim_to_live_automation_pipeline, build_sim_to_live_automation_pipeline, approval),
        "adapterReview": _saved_or_built(runtime_dir, execution_adapter_review_path(runtime_dir), read_execution_adapter_review, build_execution_adapter_review, approval),
        "adapterSandbox": _saved_or_built(runtime_dir, adapter_sandbox_review_path(runtime_dir), read_adapter_sandbox_review_bundle, build_adapter_sandbox_review_bundle, approval),
        "adapterContractValidator": _saved_or_built(runtime_dir, adapter_contract_validator_path(runtime_dir), read_adapter_contract_validator, build_adapter_contract_validator, adapter),
        "adapterHarness": _read_existing_artifact(execution_adapter_harness_path(runtime_dir)),
        "liveExecutionAdapterWriteReview": _read_existing_artifact(live_execution_adapter_write_review_path(runtime_dir)),
        "eaRequestConsumptionReview": _read_existing_artifact(ea_request_consumption_review_path(runtime_dir)),
        "livePilotActivation": _read_existing_artifact(live_pilot_activation_review_path(runtime_dir)),
        "receiptReconciliation": _read_existing_artifact(receipt_reconciliation_review_path(runtime_dir)),
        "brokerOrderSendReview": _read_existing_artifact(broker_order_send_review_path(runtime_dir)),
        "eaRequestReaderReview": _read_existing_artifact(ea_request_reader_review_path(runtime_dir)),
        "liveExecutionRollbackReview": _read_existing_artifact(live_execution_rollback_review_path(runtime_dir)),
        "liveExecutionCutoverReview": _read_existing_artifact(live_execution_cutover_review_path(runtime_dir)),
    }


def _read_artifacts(runtime_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        "hfmFilledInputValidator": read_hfm_crypto_filled_input_validator(runtime_dir),
        "evidenceIntake": read_live_evidence_intake(runtime_dir),
        "readiness": read_live_automation_readiness(runtime_dir),
        "promotionCandidates": read_live_promotion_candidates(runtime_dir),
        "promotionController": read_live_promotion_controller(runtime_dir),
        "reviewPacket": read_live_execution_review_packet(runtime_dir),
        "approvalDraft": read_live_operator_approval_draft(runtime_dir),
        "approvalEvidence": read_live_operator_approval_evidence_review(runtime_dir),
        "dryRunPlan": read_dry_run_live_execution_plan(runtime_dir),
        "executionLaneSpec": read_live_execution_lane_spec(runtime_dir),
        "dryRunReplay": read_dry_run_intent_replay(runtime_dir),
        "runtimePreflight": read_live_runtime_preflight_probe(runtime_dir),
        "orderRequestContract": read_mt5_order_request_contract(runtime_dir),
        "pipeline": read_sim_to_live_automation_pipeline(runtime_dir),
        "adapterReview": read_execution_adapter_review(runtime_dir),
        "adapterSandbox": read_adapter_sandbox_review_bundle(runtime_dir),
        "adapterContractValidator": read_adapter_contract_validator(runtime_dir),
        "adapterHarness": _read_existing_artifact(execution_adapter_harness_path(runtime_dir)),
        "liveExecutionAdapterWriteReview": _read_existing_artifact(live_execution_adapter_write_review_path(runtime_dir)),
        "eaRequestConsumptionReview": _read_existing_artifact(ea_request_consumption_review_path(runtime_dir)),
        "livePilotActivation": _read_existing_artifact(live_pilot_activation_review_path(runtime_dir)),
        "receiptReconciliation": _read_existing_artifact(receipt_reconciliation_review_path(runtime_dir)),
        "brokerOrderSendReview": _read_existing_artifact(broker_order_send_review_path(runtime_dir)),
        "eaRequestReaderReview": _read_existing_artifact(ea_request_reader_review_path(runtime_dir)),
        "liveExecutionRollbackReview": _read_existing_artifact(live_execution_rollback_review_path(runtime_dir)),
        "liveExecutionCutoverReview": _read_existing_artifact(live_execution_cutover_review_path(runtime_dir)),
    }


def _stage_rows(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    readiness = _safe_dict(artifacts.get("readiness"))
    lanes = _safe_dict(readiness.get("lanes"))
    usd_lane = _safe_dict(lanes.get("usdjpyMt5"))
    hfm_intake = _safe_dict(artifacts.get("evidenceIntake"))
    hfm_filled = _safe_dict(artifacts.get("hfmFilledInputValidator"))
    hfm_inputs_present = hfm_intake.get("status") == "HFM_REVIEW_INPUTS_PRESENT"
    usd_candidate = bool(usd_lane.get("reviewCandidate"))
    input_source_passed = bool(hfm_inputs_present or hfm_filled.get("filledInputsValid") or usd_candidate)
    stages = [
        _stage(
            "input_source",
            "证据输入源",
            hfm_intake,
            passed=input_source_passed,
            next_action_zh=(
                "HFM specs/profile 或 USDJPY deployment gate 至少一路先过线。"
                if not input_source_passed
                else "证据输入已足够进入候选选择。"
            ),
        ),
        _stage(
            "promotion_candidates",
            "候选选择",
            _safe_dict(artifacts.get("promotionCandidates")),
            passed=int(_safe_dict(artifacts.get("promotionCandidates")).get("reviewCandidateCount") or 0) > 0,
        ),
        _stage(
            "promotion_controller",
            "审查包自动生成",
            _safe_dict(artifacts.get("promotionController")),
            passed=bool(_safe_dict(artifacts.get("promotionController")).get("reviewAutomationRequested")),
        ),
        _stage(
            "review_packet",
            "执行审查包",
            _safe_dict(artifacts.get("reviewPacket")),
            passed=int(_safe_dict(artifacts.get("reviewPacket")).get("reviewCandidateCount") or 0) > 0,
        ),
        _stage(
            "approval_evidence",
            "人工审批证据",
            _safe_dict(artifacts.get("approvalEvidence")),
            passed=bool(_safe_dict(artifacts.get("approvalEvidence")).get("operatorApprovalProvided")),
        ),
        _stage(
            "dry_run_replay",
            "dry-run 回放",
            _safe_dict(artifacts.get("dryRunReplay")),
            passed=bool(_safe_dict(artifacts.get("dryRunReplay")).get("replayPassed")),
        ),
        _stage(
            "runtime_preflight",
            "MT5 运行时预检",
            _safe_dict(artifacts.get("runtimePreflight")),
            passed=_ready_or_execution_mode_only(
                _safe_dict(artifacts.get("runtimePreflight")),
                "runtimeProbePassed",
                "dataPlaneReadyForLivePilotReview",
            ),
        ),
        _stage(
            "order_request_contract",
            "MT5 请求合约",
            _safe_dict(artifacts.get("orderRequestContract")),
            passed=_ready_or_execution_mode_only(
                _safe_dict(artifacts.get("orderRequestContract")),
                "readyForAdapterCodeReview",
                "runtimePreflightDataPlaneReadyForReview",
                "runtimePreflightExecutionModeOnlyBlocked",
            ),
        ),
        _stage(
            "pipeline",
            "sim-to-live pipeline",
            _safe_dict(artifacts.get("pipeline")),
            passed=_ready_or_execution_mode_only(
                _safe_dict(artifacts.get("pipeline")),
                "readyForSeparateExecutionAdapterReview",
                "dataPlanePipelineReady",
            ),
        ),
        _stage(
            "adapter_review",
            "adapter 代码评审边界",
            _safe_dict(artifacts.get("adapterReview")),
            passed=_ready_or_execution_mode_only(
                _safe_dict(artifacts.get("adapterReview")),
                "readyForExecutionAdapterCodeReview",
                "dataPlaneAdapterReviewReady",
            ),
        ),
        _stage(
            "adapter_sandbox",
            "adapter 沙盒",
            _safe_dict(artifacts.get("adapterSandbox")),
            passed=_ready_or_execution_mode_only(
                _safe_dict(artifacts.get("adapterSandbox")),
                "sandboxReadyForCodeReview",
                "dataPlaneSandboxReady",
            ),
        ),
        _stage(
            "adapter_contract_validator",
            "adapter 合同验证",
            _safe_dict(artifacts.get("adapterContractValidator")),
            passed=_ready_or_execution_mode_only(
                _safe_dict(artifacts.get("adapterContractValidator")),
                "validationPassed",
                "dataPlaneValidationReady",
                "contractExecutionModeOnlyBlocked",
            ),
        ),
    ]
    return _normalize_autonomy_stage_rows(stages, artifacts)


def _live_execution_stage_rows(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _stage(
            "disabled_adapter_harness",
            "禁用态 adapter harness",
            _safe_dict(artifacts.get("adapterHarness")),
            passed=bool(_safe_dict(artifacts.get("adapterHarness")).get("readyForDisabledAdapterImplementationReview")),
            next_action_zh="先生成禁用态 adapter harness；它只规划 request/receipt，不写 MT5 Files。",
        ),
        _stage(
            "live_pilot_activation_review",
            "live pilot 激活评审",
            _safe_dict(artifacts.get("livePilotActivation")),
            passed=bool(_safe_dict(artifacts.get("livePilotActivation")).get("readyForLivePilotActivationReview")),
            next_action_zh="disabled harness、preflight、审批和合同验证都通过后，生成 live pilot activation review。",
        ),
        _stage(
            "receipt_reconciliation_review",
            "receipt 对账评审",
            _safe_dict(artifacts.get("receiptReconciliation")),
            passed=bool(_safe_dict(artifacts.get("receiptReconciliation")).get("readyForReceiptReconciliationReview")),
            next_action_zh="用 review-only receipts 与 planned requests 对账，确认异常能被阻断。",
        ),
        _stage(
            "broker_order_send_review",
            "broker order send 评审",
            _safe_dict(artifacts.get("brokerOrderSendReview")),
            passed=bool(_safe_dict(artifacts.get("brokerOrderSendReview")).get("readyForBrokerOrderSendReview")),
            next_action_zh="确认 broker send wrapper 只形成 no-broker-call 计划，不触发 OrderSend。",
        ),
        _stage(
            "ea_request_reader_review",
            "EA request reader 运行时评审",
            _safe_dict(artifacts.get("eaRequestReaderReview")),
            passed=bool(_safe_dict(artifacts.get("eaRequestReaderReview")).get("readyForEaRequestReaderImplementationReview")),
            next_action_zh="部署/编译/加载新版 EA，并同步 QuantGod_EARequestReaderReviewStatus.json 或 Dashboard.eaRequestReaderReview。",
        ),
        _stage(
            "live_execution_rollback_review",
            "rollback/auto-disable 评审",
            _safe_dict(artifacts.get("liveExecutionRollbackReview")),
            passed=bool(_safe_dict(artifacts.get("liveExecutionRollbackReview")).get("readyForLiveExecutionRollbackReview")),
            next_action_zh="形成缺失 receipt、broker wrapper 异常和 EA reader 异常的自动禁用规则，但当前不修改任何实盘状态。",
        ),
        _stage(
            "live_execution_cutover_review",
            "live execution cutover 评审",
            _safe_dict(artifacts.get("liveExecutionCutoverReview")),
            passed=bool(_safe_dict(artifacts.get("liveExecutionCutoverReview")).get("readyForSeparateLiveExecutionCutoverImplementationReview")),
            next_action_zh="进入单独 cutover implementation review；当前仍不会写 request 或调用 broker。",
        ),
    ]


def _live_execution_terminal_stage(live_stages: list[dict[str, Any]]) -> dict[str, Any]:
    if live_stages and all(row.get("passed") for row in live_stages):
        return {
            "stageId": "live_execution_implementation_review",
            "labelZh": "live execution 实现评审",
            "nextRequiredActionZh": "进入单独 live execution implementation PR；当前 artifact 仍不会写 request 或调用 broker。",
        }
    return _first_blocking_stage(live_stages)


def _commands(current_stage: str) -> list[dict[str, Any]]:
    rows = [
        {
            "id": "validate_hfm_filled_inputs",
            "stageId": "input_source",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime filled-input-validator --write",
            "whenZh": "人工 filled specs/profile 改过后先校验。",
        },
        {
            "id": "refresh_evidence_intake",
            "stageId": "input_source",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
            "whenZh": "刷新 HFM/USDJPY 证据输入。",
        },
        {
            "id": "run_orchestrator",
            "stageId": current_stage or "input_source",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime orchestrator --write --refresh-sources",
            "whenZh": "跑完整模拟转实盘总控状态机。",
        },
    ]
    if current_stage in {"approval_evidence", "dry_run_replay", "runtime_preflight", "order_request_contract"}:
        rows.append({
            "id": "build_pipeline",
            "stageId": "pipeline",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime pipeline --write --refresh-sources",
            "whenZh": "审批或预检证据补齐后刷新 pipeline。",
        })
    if current_stage in {"adapter_review", "adapter_sandbox", "adapter_contract_validator"}:
        rows.append({
            "id": "validate_adapter_contract",
            "stageId": "adapter_contract_validator",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime adapter-contract-validator --write --refresh-sources",
            "whenZh": "request contract 与 sandbox 就绪后做离线合同验证。",
        })
    if current_stage in {"adapter_implementation_review", "adapter_contract_validator"}:
        rows.append({
            "id": "build_disabled_adapter_harness",
            "stageId": "adapter_implementation_review",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime adapter-harness --write --refresh-sources",
            "whenZh": "总控和合同验证通过后生成禁用态 adapter 实现 harness。",
        })
    return rows


def _live_execution_commands(current_live_stage: str) -> list[dict[str, Any]]:
    rows = [
        {
            "id": "build_disabled_adapter_harness",
            "stageId": "disabled_adapter_harness",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime adapter-harness --write --refresh-sources",
            "whenZh": "生成禁用态 request/receipt 写入计划和 review-only receipts。",
        },
        {
            "id": "build_live_pilot_activation_review",
            "stageId": "live_pilot_activation_review",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime live-pilot-activation-review --write --refresh-sources",
            "whenZh": "disabled harness 和前置证据通过后，生成 live pilot 激活评审包。",
        },
        {
            "id": "build_receipt_reconciliation_review",
            "stageId": "receipt_reconciliation_review",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime receipt-reconciliation-review --write --refresh-sources",
            "whenZh": "把 review-only receipts 与 planned requests 对账。",
        },
        {
            "id": "build_ea_request_reader_review",
            "stageId": "ea_request_reader_review",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime ea-request-reader-review --write",
            "whenZh": "验证 EA 源码标记和 MT5 运行时 request-reader status 仍默认关闭。",
        },
    ]
    if not current_live_stage:
        return rows
    ordered = [row for row in rows if row.get("stageId") == current_live_stage]
    ordered.extend(row for row in rows if row.get("stageId") != current_live_stage)
    return ordered


def _blockers(stages: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    current = _first_blocking_stage(stages)
    rows: list[dict[str, Any]] = []
    if current:
        rows.append(_blocker("SIM_TO_LIVE_ORCHESTRATOR_STAGE_BLOCKED", "模拟转实盘总控停在当前阶段。", current.get("stageId")))
    live_stages = _live_execution_stage_rows(artifacts)
    live_current = _first_blocking_stage(live_stages)
    if live_current and not current:
        rows.append(_blocker("LIVE_EXECUTION_REVIEW_STAGE_BLOCKED", "live execution 后半段评审停在当前阶段。", live_current.get("stageId")))
    for payload_key in (
        "evidenceIntake",
        "promotionCandidates",
        "approvalEvidence",
        "dryRunReplay",
        "runtimePreflight",
        "orderRequestContract",
        "adapterContractValidator",
        "adapterHarness",
        "liveExecutionAdapterWriteReview",
        "eaRequestConsumptionReview",
        "livePilotActivation",
        "receiptReconciliation",
        "brokerOrderSendReview",
        "eaRequestReaderReview",
        "liveExecutionRollbackReview",
        "liveExecutionCutoverReview",
    ):
        payload = _safe_dict(artifacts.get(payload_key))
        for row in _safe_list(payload.get("blockers"))[:8]:
            if isinstance(row, dict):
                rows.append({**row, "sourceArtifact": payload_key})
    rows.extend(_release_gate_blockers(_release_gate_checklist(artifacts)))
    return rows[:24]


def _execution_mode_blockers(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for payload in artifacts.values():
        for row in _safe_list(_safe_dict(payload).get("blockers")):
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "")
            if code not in {
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
                "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
                "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
            }:
                continue
            key = (code, str(row.get("reasonZh") or ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows[:24]


def _release_gate_from_payload(payload: dict[str, Any], gate_key: str = "") -> dict[str, Any]:
    payload = _safe_dict(payload)
    release_gate = _safe_dict(payload.get(gate_key)) if gate_key else {}
    token_required = payload.get("releaseTokenRequired")
    token_provided = payload.get("releaseTokenProvided")
    blocker_code = payload.get("releaseTokenBlockerCode")
    if not release_gate and gate_key == "writerReleaseGate":
        release_gate = _safe_dict(_safe_dict(payload.get("disabledWriterImplementationContract")).get("releaseGate"))
        writer_preflight = _safe_dict(payload.get("writerRuntimePreflight"))
        token_required = release_gate.get("tokenRequired", writer_preflight.get("releaseTokenRequired", token_required))
        token_provided = release_gate.get("tokenProvidedInThisArtifact", writer_preflight.get("releaseTokenProvided", token_provided))
        blocker_code = release_gate.get("blockerCode", writer_preflight.get("releaseTokenBlockerCode", blocker_code))
    else:
        token_required = release_gate.get("tokenRequired", token_required)
        token_provided = release_gate.get("tokenProvided", token_provided)
        blocker_code = release_gate.get("blockerCode", blocker_code)
    return {
        "tokenRequired": True if token_required is None else bool(token_required),
        "tokenProvided": bool(token_provided),
        "tokenName": str(release_gate.get("tokenName") or ""),
        "blockerCode": str(blocker_code or release_gate.get("blockerCode") or ""),
        "reasonZh": str(release_gate.get("reasonZh") or release_gate.get("reason") or ""),
        "source": str(release_gate.get("source") or gate_key or "payload_release_gate"),
    }


_RELEASE_TOKEN_NAME_BY_GATE_ID = {
    "request_writer_release": "QG_REVIEWED_MT5_REQUEST_WRITE_RELEASE_V1",
    "ea_reader_release": "QG_REVIEWED_EA_REQUEST_READER_RELEASE_V1",
    "broker_order_send_release": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
    "receipt_writer_release": "QG_REVIEWED_RECEIPT_WRITER_RELEASE_V1",
    "rollback_auto_disable_release": "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1",
}

_RELEASE_TOKEN_NAME_BY_BLOCKER = {
    "REQUEST_WRITE_RELEASE_TOKEN_MISSING": "QG_REVIEWED_MT5_REQUEST_WRITE_RELEASE_V1",
    "REQUEST_READER_RELEASE_TOKEN_MISSING": "QG_REVIEWED_EA_REQUEST_READER_RELEASE_V1",
    "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING": "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
    "RECEIPT_WRITER_RELEASE_TOKEN_MISSING": "QG_REVIEWED_RECEIPT_WRITER_RELEASE_V1",
    "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING": "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1",
}


def _release_token_name(gate_id: str, blocker_code: str, release_gate: dict[str, Any]) -> str:
    return str(
        release_gate.get("tokenName")
        or _RELEASE_TOKEN_NAME_BY_GATE_ID.get(gate_id)
        or _RELEASE_TOKEN_NAME_BY_BLOCKER.get(blocker_code)
        or ""
    )


def _release_gate_checklist(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = [
        (
            "request_writer_release",
            "Python request writer",
            "liveExecutionAdapterWriteReview",
            "writerReleaseGate",
            "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
            "写 MT5 request 文件",
        ),
        (
            "ea_reader_release",
            "EA request reader",
            "eaRequestConsumptionReview",
            "readerReleaseGate",
            "REQUEST_READER_RELEASE_TOKEN_MISSING",
            "读取/消费 MT5 request 文件",
        ),
        (
            "broker_order_send_release",
            "Broker OrderSend",
            "brokerOrderSendReview",
            "brokerReleaseGate",
            "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
            "调用 MT5 OrderSend",
        ),
        (
            "receipt_writer_release",
            "Receipt writer",
            "receiptReconciliation",
            "receiptReleaseGate",
            "RECEIPT_WRITER_RELEASE_TOKEN_MISSING",
            "写入/对账真实 receipt",
        ),
        (
            "rollback_auto_disable_release",
            "Rollback auto-disable",
            "liveExecutionRollbackReview",
            "rollbackReleaseGate",
            "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
            "修改实盘状态或 preset",
        ),
    ]
    rows: list[dict[str, Any]] = []
    for gate_id, label_zh, artifact_key, gate_key, fallback_blocker, side_effect_zh in definitions:
        payload = _safe_dict(artifacts.get(artifact_key))
        release_gate = _release_gate_from_payload(payload, gate_key)
        token_required = bool(release_gate.get("tokenRequired", True))
        token_provided = bool(release_gate.get("tokenProvided"))
        blocker_code = str(release_gate.get("blockerCode") or fallback_blocker)
        token_name = _release_token_name(gate_id, blocker_code, release_gate)
        rows.append({
            "gateId": gate_id,
            "labelZh": label_zh,
            "sourceArtifact": artifact_key,
            "status": payload.get("status", ""),
            "dataPlaneReady": bool(
                payload.get("dataPlaneAdapterWriteReady")
                or payload.get("dataPlaneEaRequestConsumptionReady")
                or payload.get("dataPlaneBrokerOrderSendReady")
                or payload.get("dataPlaneReconciliationReady")
                or payload.get("dataPlaneRollbackReady")
            ),
            "sideEffectZh": side_effect_zh,
            "tokenRequired": token_required,
            "tokenProvided": token_provided,
            "tokenName": token_name,
            "blockerCode": "" if not token_required or token_provided else blocker_code,
            "reasonZh": release_gate.get("reasonZh") or f"{label_zh} release token 未提供，当前不能{side_effect_zh}。",
            "source": release_gate.get("source", ""),
            "passed": bool((not token_required) or token_provided),
        })
    return rows


def _release_gate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    blocked = [row for row in rows if row.get("tokenRequired") and not row.get("tokenProvided")]
    return {
        "total": len(rows),
        "released": len(rows) - len(blocked),
        "blocked": len(blocked),
        "allReleased": bool(rows and not blocked),
        "blockedGateIds": [row.get("gateId") for row in blocked if row.get("gateId")],
        "blockerCodes": [row.get("blockerCode") for row in blocked if row.get("blockerCode")],
        "statusZh": "所有执行 release token 已释放" if rows and not blocked else f"{len(blocked)} 个执行 release token 未释放",
    }


def _execution_release_readiness_packet(
    rows: list[dict[str, Any]],
    activation_gate_summary: dict[str, Any],
) -> dict[str, Any]:
    blocked = [row for row in rows if row.get("tokenRequired") and not row.get("tokenProvided")]
    activation_blocked = int(activation_gate_summary.get("blocked") or 0)
    if blocked and activation_blocked:
        status = "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE"
        status_zh = f"{len(blocked)} 个 release token 未释放，且 {activation_blocked} 个 MT5 执行模式闸门未通过"
    elif blocked:
        status = "WAITING_RELEASE_TOKENS"
        status_zh = f"{len(blocked)} 个 release token 未释放"
    elif activation_blocked:
        status = "WAITING_EXECUTION_MODE"
        status_zh = f"{activation_blocked} 个 MT5 执行模式闸门未通过"
    else:
        status = "RELEASE_INPUTS_PRESENT_REVIEW_ONLY"
        status_zh = "release 输入已出现，但本总控仍保持 review-only"
    return {
        "schema": "quantgod.execution_release_readiness_packet.v1",
        "status": status,
        "statusZh": status_zh,
        "releaseReady": False,
        "canReleaseExecutionNow": False,
        "safeAutomationCanContinue": True,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "activationGateSummary": activation_gate_summary,
        "releaseGateSummary": _release_gate_summary(rows),
        "gateCount": len(rows),
        "blockedGateCount": len(blocked),
        "blockedGateIds": [row.get("gateId") for row in blocked if row.get("gateId")],
        "blockedReleaseTokenCodes": [row.get("blockerCode") for row in blocked if row.get("blockerCode")],
        "gates": [
            {
                "gateId": row.get("gateId", ""),
                "labelZh": row.get("labelZh", ""),
                "sourceArtifact": row.get("sourceArtifact", ""),
                "status": row.get("status", ""),
                "dataPlaneReady": bool(row.get("dataPlaneReady")),
                "tokenRequired": bool(row.get("tokenRequired", True)),
                "tokenProvided": bool(row.get("tokenProvided")),
                "tokenName": row.get("tokenName", ""),
                "blockerCode": row.get("blockerCode", ""),
                "sideEffectZh": row.get("sideEffectZh", ""),
                "sideEffectAllowedNow": False,
                "nextAutomationActionZh": (
                    "继续刷新该 artifact 的 disabled-first 证据、样本校验和 no-side-effect 测试；"
                    "release token 未释放前不能执行该副作用。"
                    if row.get("tokenRequired") and not row.get("tokenProvided")
                    else "保持 review-only 复核，等待单独 execution lane 评审。"
                ),
            }
            for row in rows
        ],
        "nextRequiredActionZh": (
            "继续自动刷新 disabled-first execution artifacts、样本合同和安全测试；"
            "当前不写 MT5 request、不读取 request、不调用 broker、不写 receipt、不修改 preset。"
        ),
    }


def _release_gate_blockers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("tokenRequired") or row.get("tokenProvided"):
            continue
        blockers.append(_blocker(
            str(row.get("blockerCode") or "EXECUTION_RELEASE_TOKEN_MISSING"),
            str(row.get("reasonZh") or "执行 release token 未提供。"),
            row.get("sourceArtifact", ""),
        ))
    return blockers


def _execution_activation_gate_checklist(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    runtime_preflight = _safe_dict(artifacts.get("runtimePreflight"))
    dashboard = _safe_dict(runtime_preflight.get("dashboardSnapshot"))
    if not dashboard:
        return []
    blocker_rows = [
        row
        for row in [
            *_safe_list(runtime_preflight.get("executionModeBlockers")),
            *_safe_list(runtime_preflight.get("blockers")),
            *_execution_mode_blockers(artifacts),
        ]
        if isinstance(row, dict)
    ]
    blockers = {str(row.get("code") or ""): row for row in blocker_rows}
    definitions = [
        (
            "livePilotMode",
            "livePilotModeFieldPresent",
            True,
            "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
            "MT5_LIVE_PILOT_MODE_FIELD_MISSING",
            "MT5 dashboard 必须证明 livePilotMode=true。",
            "MT5 dashboard 缺少 livePilotMode 字段，不能证明终端处在实盘 pilot 配置。",
        ),
        (
            "readOnlyMode",
            "readOnlyModeFieldPresent",
            False,
            "MT5_READ_ONLY_MODE_STILL_ACTIVE",
            "MT5_READ_ONLY_MODE_FIELD_MISSING",
            "MT5 dashboard 必须证明 readOnlyMode=false。",
            "MT5 dashboard 缺少 readOnlyMode 字段，不能确认 live pilot 执行环境。",
        ),
        (
            "executionEnabled",
            "executionEnabledFieldPresent",
            True,
            "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
            "MT5_EXECUTION_ENABLED_FIELD_MISSING",
            "MT5 dashboard 必须证明 executionEnabled=true。",
            "MT5 dashboard 缺少 executionEnabled 字段。",
        ),
        (
            "tradeAllowed",
            "tradeAllowedFieldPresent",
            True,
            "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
            "MT5_TRADE_ALLOWED_FIELD_MISSING",
            "MT5 dashboard 必须证明账户、终端、EA 和 symbol tradeAllowed=true。",
            "MT5 dashboard 缺少 tradeAllowed 字段。",
        ),
    ]
    rows: list[dict[str, Any]] = []
    for field, present_field, expected, blocker_code, missing_code, reason_zh, missing_reason_zh in definitions:
        field_present = dashboard.get(present_field)
        current = dashboard.get(field)
        diagnostics = _safe_dict(_safe_dict(dashboard.get("executionGateDiagnostics")).get(field))
        passed = bool(field_present is not False and current is expected)
        if passed:
            code = ""
            reason = ""
        elif field_present is False:
            blocker = blockers.get(missing_code, {})
            code = missing_code
            reason = str(blocker.get("reasonZh") or missing_reason_zh)
        else:
            blocker = blockers.get(blocker_code, {})
            code = blocker_code
            reason = str(blocker.get("reasonZh") or reason_zh)
        rows.append(
            {
                "field": field,
                "expected": expected,
                "current": current,
                "passed": passed,
                "blockerCode": code,
                "reasonZh": reason,
                "layer": diagnostics.get("layer", ""),
                "detailZh": diagnostics.get("detailZh", ""),
                "rawValue": diagnostics.get("rawValue"),
                "permissionLayers": diagnostics.get("permissionLayers", {}),
                "source": "runtimePreflight.dashboardSnapshot",
            }
        )
    return rows


def _execution_activation_gate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in rows if not row.get("passed")]
    return {
        "total": len(rows),
        "passed": len(rows) - len(failed),
        "blocked": len(failed),
        "allPassed": bool(rows and not failed),
        "failedGateFields": [row.get("field") for row in failed if row.get("field")],
        "blockerCodes": [row.get("blockerCode") for row in failed if row.get("blockerCode")],
        "source": "runtimePreflight.dashboardSnapshot",
    }


def _data_plane_orchestrator_ready(stages: list[dict[str, Any]], live_stages: list[dict[str, Any]]) -> bool:
    main_ready = bool(stages) and all(
        row.get("passed") or row.get("status") == "WAITING_EXECUTION_MODE_ACTIVATION"
        for row in stages
    )
    visible_live_stages = [row for row in live_stages if row.get("status")]
    live_ready = not visible_live_stages or all(
        row.get("passed") or row.get("status") == "WAITING_EXECUTION_MODE_ACTIVATION"
        for row in visible_live_stages
    )
    return bool(main_ready and live_ready)


def build_sim_to_live_orchestrator(
    runtime_dir: Path,
    *,
    request_json: str = "",
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    artifacts = _build_artifacts(
        runtime_dir,
        request_json=request_json,
        operator_approval_json=operator_approval_json,
        write=write,
        refresh_sources=refresh_sources,
        moss_backtest_json=moss_backtest_json,
        hfm_simulation_profile_json=hfm_simulation_profile_json,
        hfm_contract_spec_json=hfm_contract_spec_json,
        extra_bases_roots=extra_bases_roots or [],
    )
    stages = _stage_rows(artifacts)
    current = _first_blocking_stage(stages)
    live_stages = _live_execution_stage_rows(artifacts)
    live_current = _live_execution_terminal_stage(live_stages)
    adapter_review_ready = bool(
        _safe_dict(artifacts.get("pipeline")).get("readyForSeparateExecutionAdapterReview")
        and _safe_dict(artifacts.get("adapterReview")).get("readyForExecutionAdapterCodeReview")
        and _safe_dict(artifacts.get("adapterSandbox")).get("sandboxReadyForCodeReview")
        and _safe_dict(artifacts.get("adapterContractValidator")).get("validationPassed")
    )
    live_execution_ready = bool(adapter_review_ready and live_stages and all(row.get("passed") for row in live_stages))
    data_plane_orchestrator_ready = _data_plane_orchestrator_ready(stages, live_stages)
    execution_mode_only_blocked = bool(data_plane_orchestrator_ready and not live_execution_ready)
    execution_mode_status_blocked = bool(
        data_plane_orchestrator_ready
        and execution_mode_only_blocked
        and (not adapter_review_ready or live_current.get("stageId") not in {"", "disabled_adapter_harness"})
    )
    activation_gate_checklist = _execution_activation_gate_checklist(artifacts)
    activation_gate_summary = _execution_activation_gate_summary(activation_gate_checklist)
    release_gate_checklist = _release_gate_checklist(artifacts)
    release_gate_summary = _release_gate_summary(release_gate_checklist)
    release_readiness_packet = _execution_release_readiness_packet(
        release_gate_checklist,
        activation_gate_summary,
    )
    if live_execution_ready:
        status = "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_REVIEW"
        status_zh = "可进入 live execution 实现评审"
    elif execution_mode_status_blocked:
        status = "WAITING_EXECUTION_MODE_ACTIVATION"
        status_zh = "sim-to-live 总控数据面已通过，等待执行模式闸门"
    elif adapter_review_ready:
        status = "READY_FOR_EXECUTION_ADAPTER_IMPLEMENTATION_REVIEW"
        status_zh = "可进入 execution adapter 实现评审"
    else:
        status = "WAITING_SIM_TO_LIVE_ORCHESTRATOR_INPUTS"
        status_zh = "等待模拟转实盘总控输入"
    if live_execution_ready:
        next_required_action_zh = "进入单独 live execution implementation PR；本总控仍不会写 MT5 请求文件或调用 broker。"
    elif execution_mode_status_blocked:
        next_required_action_zh = "HFM/BTC 总控数据面、审批、dry-run、adapter review、sandbox、validator 和 live execution review-only artifacts 已具备；仅剩执行模式闸门。"
    elif adapter_review_ready:
        next_required_action_zh = live_current.get("nextRequiredActionZh") or "继续补齐 live execution 后半段评审证据。"
    else:
        next_required_action_zh = current.get("nextRequiredActionZh") or "继续补齐当前阶段证据。"
    blockers = _blockers(stages, artifacts)
    if execution_mode_status_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "sim-to-live 总控数据面已具备；仅等待 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 执行模式闸门。",
                current.get("status") or live_current.get("status"),
            ),
            *_release_gate_blockers(release_gate_checklist),
            *_execution_mode_blockers(artifacts),
        ][:24]
    payload = {
        "ok": True,
        "schema": SIM_TO_LIVE_ORCHESTRATOR_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "orchestratorMode": "SIM_TO_LIVE_REVIEW_AUTOMATION_ONLY",
        "currentStage": current.get("stageId") or "adapter_implementation_review",
        "currentStageZh": current.get("labelZh") or "execution adapter 实现评审",
        "currentLiveExecutionStage": live_current.get("stageId") or "disabled_adapter_harness",
        "currentLiveExecutionStageZh": live_current.get("labelZh") or "禁用态 adapter harness",
        "stageCount": len(stages),
        "passedStageCount": sum(1 for row in stages if row.get("passed")),
        "liveExecutionStageCount": len(live_stages),
        "liveExecutionPassedStageCount": sum(1 for row in live_stages if row.get("passed")),
        "readyForExecutionAdapterImplementationReview": adapter_review_ready,
        "readyForLiveExecutionImplementationReview": live_execution_ready,
        "readyForEaRequestReaderImplementationReview": bool(_safe_dict(artifacts.get("eaRequestReaderReview")).get("readyForEaRequestReaderImplementationReview")),
        "readyForSeparateExecutionAdapterReview": bool(_safe_dict(artifacts.get("pipeline")).get("readyForSeparateExecutionAdapterReview")),
        "dataPlaneOrchestratorReady": data_plane_orchestrator_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "allExecutionActivationGatesPassed": bool(activation_gate_summary.get("allPassed")),
        "executionActivationGateSummary": activation_gate_summary,
        "executionActivationGateChecklist": activation_gate_checklist,
        "allExecutionReleaseTokensProvided": bool(release_gate_summary.get("allReleased")),
        "executionReleaseGateSummary": release_gate_summary,
        "executionReleaseGateChecklist": release_gate_checklist,
        "executionReleaseReadinessPacket": release_readiness_packet,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerExecutionAllowed": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "requestJsonProvided": bool(request_json),
        "stages": stages,
        "liveExecutionStages": live_stages,
        "artifacts": {
            "hfmFilledInputValidator": _artifact_summary(artifacts["hfmFilledInputValidator"], ("filledInputsValid", "readyForEvidenceIntakeRefresh")),
            "evidenceIntake": _artifact_summary(artifacts["evidenceIntake"], ("fileInputSummary",)),
            "readiness": _artifact_summary(artifacts["readiness"], ("reviewCandidateCount", "simulationQualifiedCount")),
            "promotionCandidates": _artifact_summary(artifacts["promotionCandidates"], ("reviewCandidateCount", "readyForOperatorReviewPacket")),
            "promotionController": _artifact_summary(artifacts["promotionController"], ("reviewAutomationRequested", "eligibleLaneCount")),
            "reviewPacket": _artifact_summary(artifacts["reviewPacket"], ("reviewCandidateCount",)),
            "approvalDraft": _artifact_summary(artifacts["approvalDraft"], ("reviewPacketHash",)),
            "approvalEvidence": _artifact_summary(artifacts["approvalEvidence"], ("operatorApprovalProvided",)),
            "dryRunPlan": _artifact_summary(artifacts["dryRunPlan"], ("summary",)),
            "executionLaneSpec": _artifact_summary(artifacts["executionLaneSpec"], ("readyForImplementationReview",)),
            "dryRunReplay": _artifact_summary(artifacts["dryRunReplay"], ("replayPassed",)),
            "runtimePreflight": _artifact_summary(artifacts["runtimePreflight"], ("runtimeProbePassed",)),
            "orderRequestContract": _artifact_summary(artifacts["orderRequestContract"], ("readyForAdapterCodeReview",)),
            "pipeline": _artifact_summary(artifacts["pipeline"], ("autoStage", "readyForSeparateExecutionAdapterReview")),
            "adapterReview": _artifact_summary(artifacts["adapterReview"], ("readyForExecutionAdapterCodeReview",)),
            "adapterSandbox": _artifact_summary(artifacts["adapterSandbox"], ("sandboxReadyForCodeReview", "sampleRequestCount", "sampleReceiptCount")),
            "adapterContractValidator": _artifact_summary(
                artifacts["adapterContractValidator"],
                (
                    "validationPassed",
                    "sampleValidationPassed",
                    "dataPlaneValidationReady",
                    "contractExecutionModeOnlyBlocked",
                    "requestCount",
                    "receiptCount",
                ),
            ),
            "adapterHarness": _artifact_summary(
                artifacts["adapterHarness"],
                (
                    "readyForDisabledAdapterImplementationReview",
                    "dataPlaneHarnessReady",
                    "executionModeOnlyBlocked",
                    "sampleValidationPassed",
                    "plannedWriteCount",
                    "reviewOnlyReceiptCount",
                ),
            ),
            "liveExecutionAdapterWriteReview": _artifact_summary(
                artifacts["liveExecutionAdapterWriteReview"],
                (
                    "readyForLiveExecutionAdapterWriteReview",
                    "dataPlaneAdapterWriteReady",
                    "executionModeOnlyBlocked",
                    "releaseTokenRequired",
                    "releaseTokenProvided",
                    "releaseTokenBlockerCode",
                ),
            ),
            "eaRequestConsumptionReview": _artifact_summary(
                artifacts["eaRequestConsumptionReview"],
                (
                    "readyForEaRequestConsumptionReview",
                    "dataPlaneEaRequestConsumptionReady",
                    "executionModeOnlyBlocked",
                    "releaseTokenRequired",
                    "releaseTokenProvided",
                    "releaseTokenBlockerCode",
                ),
            ),
            "livePilotActivation": _artifact_summary(artifacts["livePilotActivation"], ("readyForLivePilotActivationReview",)),
            "receiptReconciliation": _artifact_summary(
                artifacts["receiptReconciliation"],
                (
                    "readyForReceiptReconciliationReview",
                    "reconciliationPassed",
                    "dataPlaneReconciliationReady",
                    "executionModeOnlyBlocked",
                    "reviewOnlyReceiptsReconciled",
                    "releaseTokenRequired",
                    "releaseTokenProvided",
                    "releaseTokenBlockerCode",
                ),
            ),
            "brokerOrderSendReview": _artifact_summary(
                artifacts["brokerOrderSendReview"],
                (
                    "readyForBrokerOrderSendReview",
                    "dataPlaneBrokerOrderSendReady",
                    "executionModeOnlyBlocked",
                    "brokerSendPlanCount",
                    "releaseTokenRequired",
                    "releaseTokenProvided",
                    "releaseTokenBlockerCode",
                ),
            ),
            "eaRequestReaderReview": _artifact_summary(
                artifacts["eaRequestReaderReview"],
                (
                    "readyForEaRequestReaderImplementationReview",
                    "readyForRuntimeEaRequestReaderStatusReview",
                    "dataPlaneEaRequestReaderReady",
                    "executionModeOnlyBlocked",
                ),
            ),
            "liveExecutionRollbackReview": _artifact_summary(
                artifacts["liveExecutionRollbackReview"],
                (
                    "readyForLiveExecutionRollbackReview",
                    "dataPlaneRollbackReady",
                    "executionModeOnlyBlocked",
                    "rollbackRuleCount",
                    "releaseTokenRequired",
                    "releaseTokenProvided",
                    "releaseTokenBlockerCode",
                ),
            ),
            "liveExecutionCutoverReview": _artifact_summary(
                artifacts["liveExecutionCutoverReview"],
                (
                    "readyForSeparateLiveExecutionCutoverImplementationReview",
                    "dataPlaneCutoverReady",
                    "executionModeOnlyBlocked",
                ),
            ),
        },
        "readOnlyReviewCommands": [
            *_commands(current.get("stageId") or ""),
            *_live_execution_commands(live_current.get("stageId") or ""),
        ],
        "blockers": blockers,
        "nextRequiredActionZh": next_required_action_zh,
        "adapterNextRequiredActionZh": (
            "进入单独 execution adapter 实现评审；本总控仍不会写 MT5 请求文件或调用 broker。"
            if adapter_review_ready
            else "adapter review/sandbox/validator 数据面已具备；仅剩执行模式闸门。"
            if data_plane_orchestrator_ready and execution_mode_only_blocked
            else current.get("nextRequiredActionZh") or "继续补齐当前阶段证据。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = sim_to_live_orchestrator_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_sim_to_live_orchestrator(runtime_dir: Path) -> dict[str, Any]:
    path = sim_to_live_orchestrator_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    artifacts = _read_artifacts(Path(runtime_dir))
    stages = _stage_rows(artifacts)
    current = _first_blocking_stage(stages)
    live_stages = _live_execution_stage_rows(artifacts)
    live_current = _live_execution_terminal_stage(live_stages)
    data_plane_orchestrator_ready = _data_plane_orchestrator_ready(stages, live_stages)
    execution_mode_only_blocked = bool(data_plane_orchestrator_ready)
    activation_gate_checklist = _execution_activation_gate_checklist(artifacts)
    activation_gate_summary = _execution_activation_gate_summary(activation_gate_checklist)
    blockers = _blockers(stages, artifacts)
    if data_plane_orchestrator_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "sim-to-live 总控数据面已具备；仅等待 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 执行模式闸门。",
                current.get("status") or live_current.get("status"),
            ),
            *_execution_mode_blockers(artifacts),
        ][:24]
    payload = {
        "ok": True,
        "schema": SIM_TO_LIVE_ORCHESTRATOR_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_orchestrator_ready and execution_mode_only_blocked
            else "WAITING_SIM_TO_LIVE_ORCHESTRATOR_INPUTS"
        ),
        "statusZh": (
            "sim-to-live 总控数据面已通过，等待执行模式闸门"
            if data_plane_orchestrator_ready and execution_mode_only_blocked
            else "等待模拟转实盘总控输入"
        ),
        "orchestratorMode": "SIM_TO_LIVE_REVIEW_AUTOMATION_ONLY",
        "currentStage": current.get("stageId") or "input_source",
        "currentStageZh": current.get("labelZh") or "证据输入源",
        "currentLiveExecutionStage": live_current.get("stageId") or "disabled_adapter_harness",
        "currentLiveExecutionStageZh": live_current.get("labelZh") or "禁用态 adapter harness",
        "stageCount": len(stages),
        "passedStageCount": sum(1 for row in stages if row.get("passed")),
        "liveExecutionStageCount": len(live_stages),
        "liveExecutionPassedStageCount": sum(1 for row in live_stages if row.get("passed")),
        "readyForExecutionAdapterImplementationReview": False,
        "readyForLiveExecutionImplementationReview": False,
        "readyForEaRequestReaderImplementationReview": bool(_safe_dict(artifacts.get("eaRequestReaderReview")).get("readyForEaRequestReaderImplementationReview")),
        "dataPlaneOrchestratorReady": data_plane_orchestrator_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "allExecutionActivationGatesPassed": bool(activation_gate_summary.get("allPassed")),
        "executionActivationGateSummary": activation_gate_summary,
        "executionActivationGateChecklist": activation_gate_checklist,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerExecutionAllowed": False,
        "stages": stages,
        "liveExecutionStages": live_stages,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "HFM/BTC 总控数据面、审批、dry-run、adapter review、sandbox、validator 和 live execution review-only artifacts 已具备；仅剩执行模式闸门。"
            if data_plane_orchestrator_ready and execution_mode_only_blocked
            else current.get("nextRequiredActionZh") or live_current.get("nextRequiredActionZh") or "运行 orchestrator --write 刷新完整状态机。"
        ),
        "adapterNextRequiredActionZh": (
            "adapter review/sandbox/validator 数据面已具备；仅剩执行模式闸门。"
            if data_plane_orchestrator_ready and execution_mode_only_blocked
            else current.get("nextRequiredActionZh") or "运行 orchestrator --write 刷新 adapter 状态机。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    return payload
