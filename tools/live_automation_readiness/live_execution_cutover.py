from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approval import build_live_operator_approval_evidence_review, read_live_operator_approval_evidence_review
from .ea_request_reader_review import build_ea_request_reader_review, read_ea_request_reader_review
from .execution_adapter_harness import build_execution_adapter_harness, read_execution_adapter_harness
from .live_pilot_activation import build_live_pilot_activation_review, read_live_pilot_activation_review
from .orchestrator import build_sim_to_live_orchestrator, read_sim_to_live_orchestrator
from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
from .receipt_reconciliation import build_receipt_reconciliation_review, read_receipt_reconciliation_review
from .schema import (
    LIVE_EXECUTION_CUTOVER_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    live_execution_cutover_review_path,
    utc_now_iso,
)


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
        "generatedAtIso",
        "nextRequiredActionZh",
        *extra_keys,
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _check(check_id: str, label_zh: str, passed: bool, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {
        "id": check_id,
        "labelZh": label_zh,
        "passed": bool(passed),
        "status": "PASS" if passed else "BLOCKED",
        "reasonZh": reason_zh,
    }
    if value not in (None, "", []):
        row["value"] = value
    return row


def _all_false(payloads: list[dict[str, Any]], keys: tuple[str, ...]) -> bool:
    for payload in payloads:
        payload = _safe_dict(payload)
        for key in keys:
            if key in payload and bool(payload.get(key)):
                return False
    return True


def _operator_approval_id(approval: dict[str, Any]) -> str:
    for key in ("operatorApprovalId", "operatorId", "approvalId"):
        value = approval.get(key)
        if value:
            return str(value)
    return ""


def _ready_or_execution_mode_only(payload: dict[str, Any], ready_key: str, data_plane_key: str) -> bool:
    payload = _safe_dict(payload)
    return bool(
        payload.get(ready_key)
        or (
            payload.get(data_plane_key)
            and payload.get("executionModeOnlyBlocked")
        )
    )


def _review_checklist(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    orchestrator = _safe_dict(artifacts.get("orchestrator"))
    activation = _safe_dict(artifacts.get("livePilotActivationReview"))
    receipt = _safe_dict(artifacts.get("receiptReconciliationReview"))
    broker_send = _safe_dict(artifacts.get("brokerOrderSendReview"))
    rollback = _safe_dict(artifacts.get("liveExecutionRollbackReview"))
    ea_reader = _safe_dict(artifacts.get("eaRequestReaderReview"))
    preflight = _safe_dict(artifacts.get("runtimePreflight"))
    approval = _safe_dict(artifacts.get("approvalEvidence"))
    order_contract = _safe_dict(artifacts.get("orderRequestContract"))
    harness = _safe_dict(artifacts.get("adapterHarness"))
    payloads = [orchestrator, activation, receipt, broker_send, rollback, ea_reader, preflight, approval, order_contract, harness]
    no_side_effects = _all_false(payloads, (
        "executionReady",
        "canPromoteToLiveNow",
        "autoPromotionToLiveAllowed",
        "livePilotActivationAllowed",
        "requestWritesAllowed",
        "requestFilesWritten",
        "receiptWritesAllowed",
        "receiptFilesWritten",
        "brokerCallsMade",
        "adapterExecutionAllowed",
        "orderSendAllowed",
        "mt5OrderSendAllowed",
        "writesMt5OrderRequest",
        "mt5PendingOrderIntentsWritten",
        "brokerExecutionAllowed",
        "eaRequestReaderAllowed",
        "eaRequestReaderEnabled",
        "eaRequestFilesRead",
        "eaRequestFilesConsumed",
        "eaOrderSendAllowed",
    ))
    return [
        _check(
            "sim_to_live_orchestrator_live_ready",
            "总控到达 live execution implementation review 边界",
            bool(orchestrator.get("readyForLiveExecutionImplementationReview")),
            "需要证据、审批、dry-run、preflight、adapter、receipt、EA request reader 全链路通过。",
            orchestrator.get("status", ""),
        ),
        _check(
            "live_pilot_activation_review_ready",
            "live pilot 激活评审通过",
            bool(activation.get("readyForLivePilotActivationReview")),
            "需要 activation review 汇总总控、preflight、审批、validator 和 disabled harness。",
            activation.get("status", ""),
        ),
        _check(
            "receipt_reconciliation_review_ready",
            "receipt reconciliation 评审通过",
            _ready_or_execution_mode_only(
                receipt,
                "readyForReceiptReconciliationReview",
                "dataPlaneReconciliationReady",
            ),
            "需要 planned request、broker send plan 与 review-only receipt 完整匹配且无孤儿回执。",
            receipt.get("status", ""),
        ),
        _check(
            "broker_order_send_review_ready",
            "broker order send wrapper 评审通过",
            _ready_or_execution_mode_only(
                broker_send,
                "readyForBrokerOrderSendReview",
                "dataPlaneBrokerOrderSendReady",
            ),
            "需要 broker send plan 绑定 account/server、runtime、request fuses、hash-current 与 no-broker-call 证明。",
            broker_send.get("status", ""),
        ),
        _check(
            "rollback_auto_disable_review_ready",
            "rollback/auto-disable 评审通过",
            _ready_or_execution_mode_only(
                rollback,
                "readyForLiveExecutionRollbackReview",
                "dataPlaneRollbackReady",
            ),
            "需要 receipt、broker send、EA reader、runtime 和审批证据全部形成无副作用回滚规则。",
            rollback.get("status", ""),
        ),
        _check(
            "ea_request_reader_review_ready",
            "EA request reader 实现评审入口通过",
            _ready_or_execution_mode_only(
                ea_reader,
                "readyForEaRequestReaderImplementationReview",
                "dataPlaneEaRequestReaderReady",
            ),
            "需要 EA 源码安全标记和运行时 status 证明 request reader 仍默认关闭。",
            ea_reader.get("status", ""),
        ),
        _check(
            "runtime_preflight_live_pilot_ready",
            "live pilot 运行时预检通过",
            bool(preflight.get("runtimeProbePassed")),
            "需要新鲜 dashboard、livePilotMode、tradeAllowed、kill switch、symbol、spread 和 risk limits。",
            preflight.get("status", ""),
        ),
        _check(
            "operator_approval_evidence_accepted",
            "人工审批证据已验收",
            bool(approval.get("operatorApprovalProvided")),
            "需要 operator approval JSON 绑定当前 reviewPacketHash 并确认所有必需项。",
            approval.get("status", ""),
        ),
        _check(
            "order_request_contract_ready",
            "MT5 request/receipt 合同可用于实现评审",
            bool(order_contract.get("readyForAdapterCodeReview")),
            "需要 runtime preflight 通过后固定 request schema、receipt schema、幂等键和 atomic write。",
            order_contract.get("status", ""),
        ),
        _check(
            "disabled_adapter_harness_ready",
            "禁用态 adapter harness 已通过",
            bool(harness.get("readyForDisabledAdapterImplementationReview")),
            "需要 request/receipt 路径计划、review-only receipts、幂等和 no-side-effect 校验通过。",
            harness.get("status", ""),
        ),
        _check(
            "no_execution_side_effects_in_review_artifacts",
            "所有前置 artifact 仍无执行副作用",
            no_side_effects,
            "最终 cutover 审查前，前置 artifact 必须仍然不写 request/receipt、不调用 broker、不启用 EA reader。",
        ),
    ]


def _blockers(checklist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _blocker("LIVE_EXECUTION_CUTOVER_CHECK_NOT_PASSED", str(row.get("reasonZh") or ""), row.get("id"))
        for row in checklist
        if not row.get("passed")
    ]


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
                "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF",
                "DEPLOYED_PRESET_READ_ONLY_TRUE",
                "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF",
                "DEPLOYED_PRESET_RSI_LIVE_OFF",
                "DEPLOYED_PRESET_EA_REQUEST_READER_OFF",
            }:
                continue
            key = (code, str(row.get("reasonZh") or ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _handoff(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    approval = _safe_dict(artifacts.get("approvalEvidence"))
    order_contract = _safe_dict(artifacts.get("orderRequestContract"))
    request_contract = _safe_dict(order_contract.get("requestContract"))
    preflight = _safe_dict(artifacts.get("runtimePreflight"))
    harness = _safe_dict(artifacts.get("adapterHarness"))
    broker_send = _safe_dict(artifacts.get("brokerOrderSendReview"))
    rollback = _safe_dict(artifacts.get("liveExecutionRollbackReview"))
    ea_reader = _safe_dict(artifacts.get("eaRequestReaderReview"))
    reader_contract = _safe_dict(ea_reader.get("readerImplementationContract"))
    return {
        "handoffMode": "SEPARATE_LIVE_EXECUTION_CUTOVER_IMPLEMENTATION_REVIEW_ONLY",
        "approvedLanes": _safe_list(preflight.get("approvedLanes") or approval.get("approvedLanes")),
        "operatorApprovalId": _operator_approval_id(approval),
        "reviewPacketHash": preflight.get("reviewPacketHash") or order_contract.get("reviewPacketHash", ""),
        "runtimePreflightHash": order_contract.get("runtimePreflightHash") or harness.get("runtimePreflightHash", ""),
        "requestDirectory": request_contract.get("requestDirectory") or reader_contract.get("requestDirectory") or "runtime/agent/mt5_order_requests",
        "receiptDirectory": request_contract.get("receiptDirectory") or reader_contract.get("receiptDirectory") or "runtime/agent/mt5_order_receipts",
        "plannedWriteCount": int(harness.get("plannedWriteCount") or 0),
        "brokerSendPlanCount": int(broker_send.get("brokerSendPlanCount") or 0),
        "rollbackRuleCount": len(_safe_list(rollback.get("rollbackMatrix"))),
        "reviewOnlyReceiptCount": int(harness.get("reviewOnlyReceiptCount") or 0),
        "validatedRequestIds": _safe_list(reader_contract.get("validatedRequestIds")),
        "implementationMustStaySeparate": True,
        "requiredFuturePrs": [
            "live_execution_adapter_write_path",
            "ea_request_reader_consumption_path",
            "broker_order_send_path",
            "receipt_writer_and_reconciliation_path",
            "rollback_and_auto_disable_path",
        ],
    }


def build_live_execution_cutover_review(
    runtime_dir: Path,
    *,
    ea_source_path: str = "",
    ea_status_json: str = "",
    receipt_json: str = "",
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
    from .broker_order_send import build_broker_order_send_review, read_broker_order_send_review
    from .live_execution_rollback import build_live_execution_rollback_review, read_live_execution_rollback_review

    should_rebuild = bool(
        refresh_sources
        or ea_source_path
        or ea_status_json
        or receipt_json
        or request_json
        or operator_approval_json
        or moss_backtest_json
        or hfm_simulation_profile_json
        or hfm_contract_spec_json
        or extra_bases_roots
    )
    common = {
        "operator_approval_json": operator_approval_json,
        "write": bool(write or refresh_sources),
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots or [],
    }
    adapter = {**common, "request_json": request_json}
    if should_rebuild:
        runtime_preflight = build_live_runtime_preflight_probe(runtime_dir, **common)
        approval_evidence = build_live_operator_approval_evidence_review(runtime_dir, **common)
        order_contract = build_mt5_order_request_contract(runtime_dir, **common)
        adapter_harness = build_execution_adapter_harness(runtime_dir, **adapter)
        activation = build_live_pilot_activation_review(runtime_dir, **adapter)
        broker_send = build_broker_order_send_review(runtime_dir, **adapter)
        receipt_review = build_receipt_reconciliation_review(
            runtime_dir,
            receipt_json=receipt_json,
            request_json=request_json,
            **common,
        )
        rollback_review = build_live_execution_rollback_review(
            runtime_dir,
            ea_source_path=ea_source_path,
            ea_status_json=ea_status_json,
            receipt_json=receipt_json,
            request_json=request_json,
            **common,
        )
        ea_reader = build_ea_request_reader_review(
            runtime_dir,
            ea_source_path=ea_source_path,
            ea_status_json=ea_status_json,
            receipt_json=receipt_json,
            request_json=request_json,
            **common,
        )
        orchestrator = build_sim_to_live_orchestrator(runtime_dir, **adapter)
    else:
        runtime_preflight = read_live_runtime_preflight_probe(runtime_dir)
        approval_evidence = read_live_operator_approval_evidence_review(runtime_dir)
        order_contract = read_mt5_order_request_contract(runtime_dir)
        adapter_harness = read_execution_adapter_harness(runtime_dir)
        activation = read_live_pilot_activation_review(runtime_dir)
        broker_send = read_broker_order_send_review(runtime_dir)
        receipt_review = read_receipt_reconciliation_review(runtime_dir)
        rollback_review = read_live_execution_rollback_review(runtime_dir)
        ea_reader = read_ea_request_reader_review(runtime_dir)
        orchestrator = read_sim_to_live_orchestrator(runtime_dir)
    artifacts = {
        "orchestrator": orchestrator,
        "livePilotActivationReview": activation,
        "receiptReconciliationReview": receipt_review,
        "brokerOrderSendReview": broker_send,
        "liveExecutionRollbackReview": rollback_review,
        "eaRequestReaderReview": ea_reader,
        "runtimePreflight": runtime_preflight,
        "approvalEvidence": approval_evidence,
        "orderRequestContract": order_contract,
        "adapterHarness": adapter_harness,
    }
    activation_package = _safe_dict(activation.get("presetActivationPackage"))
    checklist = _review_checklist(artifacts)
    ready = bool(checklist and all(row.get("passed") for row in checklist))
    no_side_effects = bool(
        next(
            (row.get("passed") for row in checklist if row.get("id") == "no_execution_side_effects_in_review_artifacts"),
            False,
        )
    )
    data_plane_cutover_ready = bool(
        activation.get("dataPlaneActivationReady")
        and receipt_review.get("dataPlaneReconciliationReady")
        and broker_send.get("dataPlaneBrokerOrderSendReady")
        and rollback_review.get("dataPlaneRollbackReady")
        and ea_reader.get("dataPlaneEaRequestReaderReady")
        and runtime_preflight.get("dataPlaneReadyForLivePilotReview")
        and order_contract.get("runtimePreflightDataPlaneReadyForReview")
        and adapter_harness.get("dataPlaneHarnessReady")
        and no_side_effects
    )
    execution_mode_only_blocked = bool(
        activation.get("executionModeOnlyBlocked")
        or receipt_review.get("executionModeOnlyBlocked")
        or broker_send.get("executionModeOnlyBlocked")
        or rollback_review.get("executionModeOnlyBlocked")
        or ea_reader.get("executionModeOnlyBlocked")
        or runtime_preflight.get("executionModeOnlyBlocked")
        or order_contract.get("runtimePreflightExecutionModeOnlyBlocked")
        or adapter_harness.get("executionModeOnlyBlocked")
    )
    blockers = _blockers(checklist)
    if data_plane_cutover_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "live execution cutover 数据面、审批、harness、receipt 对账和 EA reader 已具备；仅等待执行模式闸门。",
                runtime_preflight.get("status") or activation.get("status"),
            )
        ]
        blockers.extend(_execution_mode_blockers(
            runtime_preflight,
            order_contract,
            adapter_harness,
            activation,
            receipt_review,
            broker_send,
            rollback_review,
            ea_reader,
        ))
    payload = {
        "ok": True,
        "schema": LIVE_EXECUTION_CUTOVER_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_SEPARATE_LIVE_EXECUTION_CUTOVER_IMPLEMENTATION_REVIEW"
            if ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_cutover_ready and execution_mode_only_blocked
            else "WAITING_LIVE_EXECUTION_CUTOVER_INPUTS"
        ),
        "statusZh": (
            "可进入单独 live execution cutover 实现评审"
            if ready
            else "live execution cutover 数据面已通过，等待执行模式闸门"
            if data_plane_cutover_ready and execution_mode_only_blocked
            else "等待 live execution cutover 审查输入"
        ),
        "reviewMode": "LIVE_EXECUTION_CUTOVER_REVIEW_ONLY_NO_SIDE_EFFECTS",
        "readyForSeparateLiveExecutionCutoverImplementationReview": ready,
        "dataPlaneCutoverReady": data_plane_cutover_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "liveExecutionCutoverAllowed": False,
        "livePilotActivationAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "brokerExecutionAllowed": False,
        "autoDisableMutationAllowed": False,
        "eaRequestReaderAllowed": False,
        "eaRequestReaderEnabled": False,
        "eaRequestFilesRead": False,
        "eaRequestFilesConsumed": False,
        "eaOrderSendAllowed": False,
        "cutoverChecklist": checklist,
        "implementationHandoff": _handoff(artifacts),
        "executionModeFileEvidence": _safe_dict(activation_package.get("liveRuntimeFileEvidence")),
        "artifacts": {
            "orchestrator": _artifact_summary(artifacts["orchestrator"], ("readyForLiveExecutionImplementationReview", "currentLiveExecutionStage")),
            "livePilotActivationReview": _artifact_summary(artifacts["livePilotActivationReview"], ("readyForLivePilotActivationReview",)),
            "receiptReconciliationReview": _artifact_summary(
                artifacts["receiptReconciliationReview"],
                ("readyForReceiptReconciliationReview", "reconciliationPassed", "dataPlaneReconciliationReady", "executionModeOnlyBlocked"),
            ),
            "brokerOrderSendReview": _artifact_summary(
                artifacts["brokerOrderSendReview"],
                ("readyForBrokerOrderSendReview", "dataPlaneBrokerOrderSendReady", "brokerSendPlanCount", "executionModeOnlyBlocked"),
            ),
            "liveExecutionRollbackReview": _artifact_summary(
                artifacts["liveExecutionRollbackReview"],
                ("readyForLiveExecutionRollbackReview", "dataPlaneRollbackReady", "executionModeOnlyBlocked"),
            ),
            "eaRequestReaderReview": _artifact_summary(
                artifacts["eaRequestReaderReview"],
                ("readyForEaRequestReaderImplementationReview", "readyForRuntimeEaRequestReaderStatusReview", "dataPlaneEaRequestReaderReady", "executionModeOnlyBlocked"),
            ),
            "runtimePreflight": _artifact_summary(artifacts["runtimePreflight"], ("runtimeProbePassed", "reviewPacketHash")),
            "approvalEvidence": _artifact_summary(artifacts["approvalEvidence"], ("operatorApprovalProvided", "reviewPacketHash")),
            "orderRequestContract": _artifact_summary(artifacts["orderRequestContract"], ("readyForAdapterCodeReview", "runtimePreflightHash")),
            "adapterHarness": _artifact_summary(artifacts["adapterHarness"], ("readyForDisabledAdapterImplementationReview", "plannedWriteCount")),
        },
        "blockers": blockers[:32],
        "nextRequiredActionZh": (
            "进入单独 live execution cutover implementation PR；本审查包仍不会写 request/receipt 文件或调用 broker。"
            if ready
            else "live execution cutover 数据面已具备；仅剩执行模式闸门，当前仍不会写 request/receipt 或调用 broker。"
            if data_plane_cutover_ready and execution_mode_only_blocked
            else "先让 orchestrator、live pilot activation、receipt reconciliation、EA request reader、runtime preflight 和人工审批全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_execution_cutover_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_execution_cutover_review(runtime_dir: Path) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    path = live_execution_cutover_review_path(runtime_dir)
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {
        "ok": True,
        "schema": LIVE_EXECUTION_CUTOVER_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "WAITING_LIVE_EXECUTION_CUTOVER_INPUTS",
        "statusZh": "等待 live execution cutover 审查输入",
        "reviewMode": "LIVE_EXECUTION_CUTOVER_REVIEW_ONLY_NO_SIDE_EFFECTS",
        "readyForSeparateLiveExecutionCutoverImplementationReview": False,
        "dataPlaneCutoverReady": False,
        "executionModeOnlyBlocked": False,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "liveExecutionCutoverAllowed": False,
        "livePilotActivationAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "brokerExecutionAllowed": False,
        "autoDisableMutationAllowed": False,
        "eaRequestReaderAllowed": False,
        "eaRequestReaderEnabled": False,
        "eaRequestFilesRead": False,
        "eaRequestFilesConsumed": False,
        "eaOrderSendAllowed": False,
        "cutoverChecklist": [],
        "implementationHandoff": {
            "handoffMode": "WAITING_FOR_CUTOVER_REVIEW_INPUTS",
            "implementationMustStaySeparate": True,
            "requiredFuturePrs": [
                "live_execution_adapter_write_path",
                "ea_request_reader_consumption_path",
                "broker_order_send_path",
                "receipt_writer_and_reconciliation_path",
                "rollback_and_auto_disable_path",
            ],
        },
        "blockers": [
            _blocker(
                "LIVE_EXECUTION_CUTOVER_REVIEW_ARTIFACT_MISSING",
                "缺少 live execution cutover review artifact；不会递归重建以避免 broker/spec/cutover 循环。",
                str(path),
            )
        ],
        "nextRequiredActionZh": "先生成 live execution cutover review；当前不会写 request/receipt 或调用 broker。",
        "safety": dict(SAFETY),
    }
