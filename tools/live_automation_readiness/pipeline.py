from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
from .execution_lane import build_live_execution_lane_spec, read_live_execution_lane_spec
from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
from .review_packet import build_live_execution_review_packet, read_live_execution_review_packet
from .schema import (
    SAFETY,
    SIM_TO_LIVE_PIPELINE_SCHEMA_VERSION,
    assert_no_execution_flags,
    sim_to_live_pipeline_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def _stage_row(stage_id: str, name_zh: str, payload: dict[str, Any], pass_key: str = "") -> dict[str, Any]:
    blockers = [item for item in _safe_list(payload.get("blockers")) if isinstance(item, dict)]
    if pass_key:
        passed = bool(payload.get(pass_key))
    else:
        status = str(payload.get("status") or "")
        passed = "READY" in status or "ACCEPTED" in status
    return {
        "stageId": stage_id,
        "nameZh": name_zh,
        "status": payload.get("status", ""),
        "statusZh": payload.get("statusZh", ""),
        "passed": passed,
        "blockerCodes": [item.get("code") for item in blockers],
        "nextRequiredActionZh": payload.get("nextRequiredActionZh", ""),
    }


def _first_failed_stage(stages: list[dict[str, Any]]) -> dict[str, Any]:
    for stage in stages:
        if not stage.get("passed"):
            return stage
    return stages[-1] if stages else {}


def _global_blockers(stages: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    failed = _first_failed_stage(stages)
    rows = []
    if failed and not failed.get("passed"):
        rows.append(_blocker("PIPELINE_STAGE_NOT_PASSED", "sim-to-live 流水线停在当前未通过阶段。", failed.get("stageId")))
    readiness = _safe_dict(artifacts.get("readiness"))
    if not int(readiness.get("reviewCandidateCount") or 0):
        rows.append(_blocker("NO_REVIEW_CANDIDATE_LANES", "还没有 lane 达到模拟转实盘审查候选条件。"))
    approval = _safe_dict(artifacts.get("approvalEvidence"))
    if not bool(approval.get("operatorApprovalProvided")):
        rows.append(_blocker("OPERATOR_APPROVAL_EVIDENCE_NOT_ACCEPTED", "人工审批证据尚未通过。"))
    preflight = _safe_dict(artifacts.get("runtimePreflight"))
    if not bool(preflight.get("runtimeProbePassed")):
        if bool(preflight.get("executionModeOnlyBlocked")):
            rows.append(_blocker("EXECUTION_MODE_GATES_NOT_ACTIVE", "数据面预检已通过，但执行模式闸门尚未打开。", preflight.get("status")))
        else:
            rows.append(_blocker("RUNTIME_PREFLIGHT_NOT_PASSED", "运行时预检尚未通过。", preflight.get("status")))
    return rows


def _execution_mode_blockers(*payloads: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for payload in payloads:
        for row in _safe_list(payload.get("blockers")):
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
    return rows


def _artifact_summary(payload: dict[str, Any], extra_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    keys = ("schema", "status", "statusZh", "generatedAtIso", "nextRequiredActionZh", *extra_keys)
    return {key: payload.get(key) for key in keys if key in payload}


def _checklist_item(check_id: str, label_zh: str, passed: bool, reason_zh: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "labelZh": label_zh,
        "passed": bool(passed),
        "status": "PASS" if passed else "MISSING",
        "reasonZh": reason_zh,
    }


def _evidence_checklist(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    readiness = _safe_dict(artifacts.get("readiness"))
    lanes = _safe_dict(readiness.get("lanes"))
    hfm = _safe_dict(lanes.get("hfmCryptoCfd"))
    usd = _safe_dict(lanes.get("usdjpyMt5"))
    approval = _safe_dict(artifacts.get("approvalEvidence"))
    replay = _safe_dict(artifacts.get("dryRunReplay"))
    preflight = _safe_dict(artifacts.get("runtimePreflight"))
    order_contract = _safe_dict(artifacts.get("orderRequestContract"))
    review_candidate_count = int(readiness.get("reviewCandidateCount") or 0)
    runtime_preflight_reason = "需要新鲜 dashboard、kill switch 未触发、账户/server、symbol 映射和价差字段。"
    if bool(preflight.get("executionModeOnlyBlocked")):
        runtime_preflight_reason = "数据面已通过；仅剩 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 执行模式闸门。"
    order_contract_reason = "需要 runtime preflight 通过后才能审查请求/回执合同。"
    if bool(order_contract.get("runtimePreflightExecutionModeOnlyBlocked")):
        order_contract_reason = "请求合约数据面已具备；仅等待执行模式闸门通过后进入 adapter 评审。"
    return [
        _checklist_item(
            "review_candidate_lane",
            "至少一个 lane 达到模拟转实盘审查候选",
            review_candidate_count > 0,
            "需要 USDJPY deployment gate 或 HFM crypto simulation/contract evidence 先过线。",
        ),
        _checklist_item(
            "hfm_crypto_symbol_evidence",
            "HFM crypto broker symbol 证据",
            bool(hfm.get("symbolEvidenceFound")),
            "需要 HFM MT5 下载 crypto 历史/tick，或导入 EA 导出的 crypto symbol specs。",
        ),
        _checklist_item(
            "hfm_crypto_simulation_profile",
            "HFM crypto 模拟表现达标",
            bool(hfm.get("simulationProfileQualified") or hfm.get("simulationQualified")),
            "需要 ROI、Sharpe、最大回撤、交易笔数、爆仓次数字段过准入线。",
        ),
        _checklist_item(
            "hfm_crypto_contract_spec",
            "HFM crypto 合约规格可审查",
            bool(hfm.get("executionSpecReady")),
            "需要 brokerSymbol、contractSize、tickSize、tickValue、minLot、lotStep、maxLot。",
        ),
        _checklist_item(
            "usdjpy_live_candidate",
            "USDJPY MT5 live candidate",
            bool(usd.get("reviewCandidate")),
            "需要 USDJPY policy、promotion gate、rollback、runtime 与执行反馈全部通过。",
        ),
        _checklist_item(
            "operator_approval_evidence",
            "人工审批证据已验收",
            bool(approval.get("operatorApprovalProvided")),
            "需要按 approval draft 填写 operator approval JSON，并匹配当前 reviewPacketHash。",
        ),
        _checklist_item(
            "dry_run_replay",
            "dry-run intent 回放通过",
            bool(replay.get("replayPassed")),
            "需要 review candidate、审批证据和 dry-run intent 同时可用。",
        ),
        _checklist_item(
            "runtime_preflight",
            "MT5 运行时预检通过",
            bool(preflight.get("runtimeProbePassed")),
            runtime_preflight_reason,
        ),
        _checklist_item(
            "order_request_contract",
            "MT5 请求合约可进入 adapter 评审",
            bool(order_contract.get("readyForAdapterCodeReview")),
            order_contract_reason,
        ),
    ]


def _next_action_from_checklist(checklist: list[dict[str, Any]], fallback: str) -> str:
    for item in checklist:
        if not item.get("passed"):
            return str(item.get("reasonZh") or fallback)
    return fallback


def _build_artifacts(
    runtime_dir: Path,
    *,
    operator_approval_json: str,
    write: bool,
    refresh_sources: bool,
    moss_backtest_json: str,
    hfm_simulation_profile_json: str,
    hfm_contract_spec_json: str,
    extra_bases_roots: list[str],
) -> dict[str, dict[str, Any]]:
    kwargs = {
        "write": write,
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots,
    }
    approval_kwargs = {**kwargs, "operator_approval_json": operator_approval_json}
    return {
        "readiness": build_live_automation_readiness(runtime_dir, **kwargs),
        "reviewPacket": build_live_execution_review_packet(runtime_dir, **kwargs),
        "approvalDraft": build_live_operator_approval_draft(runtime_dir, **kwargs),
        "approvalEvidence": build_live_operator_approval_evidence_review(runtime_dir, **approval_kwargs),
        "dryRunPlan": build_dry_run_live_execution_plan(runtime_dir, **kwargs),
        "executionLaneSpec": build_live_execution_lane_spec(runtime_dir, **approval_kwargs),
        "dryRunReplay": build_dry_run_intent_replay(runtime_dir, **approval_kwargs),
        "runtimePreflight": build_live_runtime_preflight_probe(runtime_dir, **approval_kwargs),
        "orderRequestContract": build_mt5_order_request_contract(runtime_dir, **approval_kwargs),
    }


def _read_artifacts(runtime_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        "readiness": read_live_automation_readiness(runtime_dir),
        "reviewPacket": read_live_execution_review_packet(runtime_dir),
        "approvalDraft": read_live_operator_approval_draft(runtime_dir),
        "approvalEvidence": read_live_operator_approval_evidence_review(runtime_dir),
        "dryRunPlan": read_dry_run_live_execution_plan(runtime_dir),
        "executionLaneSpec": read_live_execution_lane_spec(runtime_dir),
        "dryRunReplay": read_dry_run_intent_replay(runtime_dir),
        "runtimePreflight": read_live_runtime_preflight_probe(runtime_dir),
        "orderRequestContract": read_mt5_order_request_contract(runtime_dir),
    }


def build_sim_to_live_automation_pipeline(
    runtime_dir: Path,
    *,
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    extra_roots = extra_bases_roots or []
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    artifacts = _build_artifacts(
        runtime_dir,
        operator_approval_json=operator_approval_json,
        write=write,
        refresh_sources=refresh_sources,
        moss_backtest_json=moss_backtest_json,
        hfm_simulation_profile_json=hfm_simulation_profile_json,
        hfm_contract_spec_json=hfm_contract_spec_json,
        extra_bases_roots=extra_roots,
    )
    stages = [
        _stage_row("readiness", "模拟/执行反馈准入", artifacts["readiness"]),
        _stage_row("review_packet", "执行审查包", artifacts["reviewPacket"]),
        _stage_row("operator_approval", "人工审批证据", artifacts["approvalEvidence"], "operatorApprovalProvided"),
        _stage_row("dry_run_plan", "dry-run intent 计划", artifacts["dryRunPlan"]),
        _stage_row("execution_lane_spec", "执行通道规格", artifacts["executionLaneSpec"], "readyForImplementationReview"),
        _stage_row("dry_run_replay", "dry-run 回放", artifacts["dryRunReplay"], "replayPassed"),
        _stage_row("runtime_preflight", "运行时预检", artifacts["runtimePreflight"], "runtimeProbePassed"),
        _stage_row("order_request_contract", "MT5 请求合约", artifacts["orderRequestContract"], "readyForAdapterCodeReview"),
    ]
    failed = _first_failed_stage(stages)
    auto_stage = failed.get("stageId") or "unknown"
    ready_for_adapter_review = bool(artifacts["orderRequestContract"].get("readyForAdapterCodeReview"))
    blockers = _global_blockers(stages, artifacts)
    earlier_stage_ids = {
        "readiness",
        "review_packet",
        "operator_approval",
        "dry_run_plan",
        "execution_lane_spec",
        "dry_run_replay",
    }
    earlier_stages_passed = all(
        row.get("passed")
        for row in stages
        if row.get("stageId") in earlier_stage_ids
    )
    data_plane_pipeline_ready = bool(
        earlier_stages_passed
        and artifacts["runtimePreflight"].get("dataPlaneReadyForLivePilotReview")
        and artifacts["orderRequestContract"].get("runtimePreflightDataPlaneReadyForReview")
    )
    execution_mode_only_blocked = bool(
        artifacts["runtimePreflight"].get("executionModeOnlyBlocked")
        or artifacts["orderRequestContract"].get("runtimePreflightExecutionModeOnlyBlocked")
    )
    approval_evidence = _safe_dict(artifacts.get("approvalEvidence"))
    operator_approval_evidence_accepted = bool(approval_evidence.get("operatorApprovalProvided"))
    operator_approval_json_present = bool(operator_approval_json)
    operator_approval_json_stale_or_rejected = bool(
        operator_approval_json_present and not operator_approval_evidence_accepted
    )
    if data_plane_pipeline_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "sim-to-live pipeline 数据面、审批、dry-run、preflight 和 request contract 已具备；仅等待执行模式闸门。",
                artifacts["runtimePreflight"].get("status") or artifacts["orderRequestContract"].get("status"),
            )
        ]
        blockers.extend(_execution_mode_blockers(
            artifacts["runtimePreflight"],
            artifacts["orderRequestContract"],
        ))
    checklist = _evidence_checklist(artifacts)
    next_action = (
        "进入单独 execution adapter 代码评审；流水线本身仍不会写 MT5 请求文件。"
        if ready_for_adapter_review
        else "HFM/BTC 数据面、审批、dry-run、preflight 和 request contract 已具备；仅剩执行模式闸门，当前仍不会写订单。"
        if data_plane_pipeline_ready and execution_mode_only_blocked
        else failed.get("nextRequiredActionZh") or _next_action_from_checklist(checklist, "继续补齐当前阶段所需证据。")
    )
    payload = {
        "ok": True,
        "schema": SIM_TO_LIVE_PIPELINE_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_SEPARATE_EXECUTION_ADAPTER_REVIEW"
            if ready_for_adapter_review
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_pipeline_ready and execution_mode_only_blocked
            else "WAITING_SIM_TO_LIVE_PIPELINE_INPUTS"
        ),
        "statusZh": (
            "可进入单独 execution adapter 评审"
            if ready_for_adapter_review
            else "sim-to-live pipeline 数据面已通过，等待执行模式闸门"
            if data_plane_pipeline_ready and execution_mode_only_blocked
            else "等待模拟转实盘流水线证据"
        ),
        "autoStage": auto_stage,
        "readyForSeparateExecutionAdapterReview": ready_for_adapter_review,
        "dataPlanePipelineReady": data_plane_pipeline_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "requestWritesAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerExecutionAllowed": False,
        "operatorApprovalJsonProvided": operator_approval_json_present,
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "operatorApprovalEvidenceAccepted": operator_approval_evidence_accepted,
        "operatorApprovalJsonStaleOrRejected": operator_approval_json_stale_or_rejected,
        "operatorApprovalReviewPacketHash": approval_evidence.get("reviewPacketHash", ""),
        "operatorApprovalProvidedReviewPacketHash": approval_evidence.get("providedReviewPacketHash", ""),
        "operatorApprovalBoundToReviewPacket": bool(approval_evidence.get("approvalBoundToReviewPacket")),
        "evidenceInputs": {
            "mossBacktestJson": moss_backtest_json,
            "hfmSimulationProfileJson": hfm_simulation_profile_json,
            "hfmContractSpecJson": hfm_contract_spec_json,
            "extraBasesRootCount": len(extra_roots),
        },
        "stages": stages,
        "evidenceChecklist": checklist,
        "artifacts": {
            "readiness": _artifact_summary(artifacts["readiness"], ("reviewCandidateCount", "canPromoteToLiveNow")),
            "reviewPacket": _artifact_summary(artifacts["reviewPacket"], ("reviewCandidateCount", "canPromoteToLiveNow")),
            "approvalDraft": _artifact_summary(artifacts["approvalDraft"], ("reviewPacketHash",)),
            "approvalEvidence": _artifact_summary(
                artifacts["approvalEvidence"],
                ("operatorApprovalProvided", "reviewPacketHash", "providedReviewPacketHash", "approvalBoundToReviewPacket"),
            ),
            "dryRunPlan": _artifact_summary(artifacts["dryRunPlan"]),
            "executionLaneSpec": _artifact_summary(artifacts["executionLaneSpec"], ("readyForImplementationReview",)),
            "dryRunReplay": _artifact_summary(artifacts["dryRunReplay"], ("replayPassed",)),
            "runtimePreflight": _artifact_summary(
                artifacts["runtimePreflight"],
                ("runtimeProbePassed", "dataPlaneReadyForLivePilotReview", "executionModeOnlyBlocked"),
            ),
            "orderRequestContract": _artifact_summary(
                artifacts["orderRequestContract"],
                ("readyForAdapterCodeReview", "runtimePreflightDataPlaneReadyForReview", "runtimePreflightExecutionModeOnlyBlocked"),
            ),
        },
        "blockers": blockers,
        "nextRequiredActionZh": next_action,
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = sim_to_live_pipeline_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_sim_to_live_automation_pipeline(runtime_dir: Path) -> dict[str, Any]:
    path = sim_to_live_pipeline_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    artifacts = _read_artifacts(Path(runtime_dir))
    stages = [
        _stage_row("readiness", "模拟/执行反馈准入", artifacts["readiness"]),
        _stage_row("review_packet", "执行审查包", artifacts["reviewPacket"]),
        _stage_row("operator_approval", "人工审批证据", artifacts["approvalEvidence"], "operatorApprovalProvided"),
        _stage_row("dry_run_plan", "dry-run intent 计划", artifacts["dryRunPlan"]),
        _stage_row("execution_lane_spec", "执行通道规格", artifacts["executionLaneSpec"], "readyForImplementationReview"),
        _stage_row("dry_run_replay", "dry-run 回放", artifacts["dryRunReplay"], "replayPassed"),
        _stage_row("runtime_preflight", "运行时预检", artifacts["runtimePreflight"], "runtimeProbePassed"),
        _stage_row("order_request_contract", "MT5 请求合约", artifacts["orderRequestContract"], "readyForAdapterCodeReview"),
    ]
    failed = _first_failed_stage(stages)
    checklist = _evidence_checklist(artifacts)
    earlier_stage_ids = {
        "readiness",
        "review_packet",
        "operator_approval",
        "dry_run_plan",
        "execution_lane_spec",
        "dry_run_replay",
    }
    earlier_stages_passed = all(
        row.get("passed")
        for row in stages
        if row.get("stageId") in earlier_stage_ids
    )
    data_plane_pipeline_ready = bool(
        earlier_stages_passed
        and artifacts["runtimePreflight"].get("dataPlaneReadyForLivePilotReview")
        and artifacts["orderRequestContract"].get("runtimePreflightDataPlaneReadyForReview")
    )
    execution_mode_only_blocked = bool(
        artifacts["runtimePreflight"].get("executionModeOnlyBlocked")
        or artifacts["orderRequestContract"].get("runtimePreflightExecutionModeOnlyBlocked")
    )
    approval_evidence = _safe_dict(artifacts.get("approvalEvidence"))
    blockers = _global_blockers(stages, artifacts)
    if data_plane_pipeline_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "sim-to-live pipeline 数据面、审批、dry-run、preflight 和 request contract 已具备；仅等待执行模式闸门。",
                artifacts["runtimePreflight"].get("status") or artifacts["orderRequestContract"].get("status"),
            )
        ]
        blockers.extend(_execution_mode_blockers(
            artifacts["runtimePreflight"],
            artifacts["orderRequestContract"],
        ))
    payload = {
        "ok": True,
        "schema": SIM_TO_LIVE_PIPELINE_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_pipeline_ready and execution_mode_only_blocked
            else "WAITING_SIM_TO_LIVE_PIPELINE_INPUTS"
        ),
        "statusZh": (
            "sim-to-live pipeline 数据面已通过，等待执行模式闸门"
            if data_plane_pipeline_ready and execution_mode_only_blocked
            else "等待模拟转实盘流水线证据"
        ),
        "autoStage": failed.get("stageId") or "unknown",
        "readyForSeparateExecutionAdapterReview": False,
        "dataPlanePipelineReady": data_plane_pipeline_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "requestWritesAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerExecutionAllowed": False,
        "operatorApprovalEvidenceAccepted": bool(approval_evidence.get("operatorApprovalProvided")),
        "operatorApprovalJsonStaleOrRejected": False,
        "operatorApprovalReviewPacketHash": approval_evidence.get("reviewPacketHash", ""),
        "operatorApprovalProvidedReviewPacketHash": approval_evidence.get("providedReviewPacketHash", ""),
        "operatorApprovalBoundToReviewPacket": bool(approval_evidence.get("approvalBoundToReviewPacket")),
        "stages": stages,
        "evidenceChecklist": checklist,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "HFM/BTC 数据面、审批、dry-run、preflight 和 request contract 已具备；仅剩执行模式闸门，当前仍不会写订单。"
            if data_plane_pipeline_ready and execution_mode_only_blocked
            else failed.get("nextRequiredActionZh") or _next_action_from_checklist(checklist, "运行 build 写入最新流水线证据。")
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    return payload
