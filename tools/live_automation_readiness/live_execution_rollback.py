from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import (
    LIVE_EXECUTION_ROLLBACK_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    live_execution_rollback_review_path,
    utc_now_iso,
)

ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_NAME = "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1"
ROLLBACK_AUTO_DISABLE_RELEASE_BLOCKER = "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING"


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    return row


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
                "DEPLOYED_PRESET_EA_REQUEST_READER_OFF",
            }:
                continue
            key = (code, str(row.get("reasonZh") or ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _ready_or_execution_mode_only(payload: dict[str, Any], ready_key: str, data_plane_key: str) -> bool:
    payload = _safe_dict(payload)
    return bool(
        payload.get(ready_key)
        or (
            payload.get(data_plane_key)
            and payload.get("executionModeOnlyBlocked")
        )
    )


def _rollback_release_gate() -> dict[str, Any]:
    return {
        "tokenRequired": True,
        "tokenProvided": False,
        "tokenName": ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_NAME,
        "blockerCode": ROLLBACK_AUTO_DISABLE_RELEASE_BLOCKER,
        "reasonZh": "没有单独审查 release token 时，rollback/auto-disable 不能修改实盘状态或 preset。",
        "source": "default_missing_runtime_rollback_release_gate",
    }


def _rollback_matrix(receipt: dict[str, Any], broker: dict[str, Any], ea_reader: dict[str, Any]) -> list[dict[str, Any]]:
    policy = _safe_dict(receipt.get("autoDisablePolicy"))
    return [
        {
            "id": "missing_or_failed_receipt",
            "triggerZh": "planned request 缺失 receipt、receipt 校验失败或出现孤儿 receipt。",
            "evidence": {
                "missingReceiptCount": policy.get("missingReceiptCount", 0),
                "failedReceiptCount": policy.get("failedReceiptCount", receipt.get("failedReceiptCount", 0)),
                "extraReceiptCount": policy.get("extraReceiptCount", receipt.get("extraReceiptCount", 0)),
                "wouldTriggerAutoDisable": bool(policy.get("wouldTriggerAutoDisable")),
            },
            "futureActionZh": "未来实盘执行 lane 必须自动暂停并要求人工复核；当前 artifact 只声明规则。",
            "autoDisableMutationAllowed": False,
            "passed": _ready_or_execution_mode_only(
                receipt,
                "readyForReceiptReconciliationReview",
                "dataPlaneReconciliationReady",
            ),
        },
        {
            "id": "broker_send_wrapper_not_ready",
            "triggerZh": "broker send plan、hash-current 或 no-broker-call fuse 不完整。",
            "evidence": {
                "brokerOrderSendStatus": broker.get("status", ""),
                "brokerSendPlanCount": broker.get("brokerSendPlanCount", 0),
                "dataPlaneBrokerOrderSendReady": bool(broker.get("dataPlaneBrokerOrderSendReady")),
            },
            "futureActionZh": "阻断 broker 调用路径，直到 broker order send review 重新通过。",
            "autoDisableMutationAllowed": False,
            "passed": _ready_or_execution_mode_only(
                broker,
                "readyForBrokerOrderSendReview",
                "dataPlaneBrokerOrderSendReady",
            ),
        },
        {
            "id": "ea_reader_unexpectedly_enabled_or_consuming",
            "triggerZh": "EA request reader 在单独实现评审前被启用、读取或消费 request。",
            "evidence": {
                "eaRequestReaderStatus": ea_reader.get("status", ""),
                "runtimeStatusDisabled": bool(ea_reader.get("runtimeStatusDisabled")),
                "eaRequestReaderEnabled": bool(ea_reader.get("eaRequestReaderEnabled")),
                "eaRequestFilesRead": bool(ea_reader.get("eaRequestFilesRead")),
                "eaRequestFilesConsumed": bool(ea_reader.get("eaRequestFilesConsumed")),
            },
            "futureActionZh": "阻断 cutover，并要求恢复禁用态后重新跑 request reader review。",
            "autoDisableMutationAllowed": False,
            "passed": (
                _ready_or_execution_mode_only(
                    ea_reader,
                    "readyForEaRequestReaderImplementationReview",
                    "dataPlaneEaRequestReaderReady",
                )
                and ea_reader.get("eaRequestReaderEnabled") is False
                and ea_reader.get("eaRequestFilesRead") is False
                and ea_reader.get("eaRequestFilesConsumed") is False
            ),
        },
    ]


def _review_checklist(artifacts: dict[str, dict[str, Any]], matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    receipt = _safe_dict(artifacts.get("receiptReconciliationReview"))
    broker = _safe_dict(artifacts.get("brokerOrderSendReview"))
    ea_reader = _safe_dict(artifacts.get("eaRequestReaderReview"))
    preflight = _safe_dict(artifacts.get("runtimePreflight"))
    approval = _safe_dict(artifacts.get("approvalEvidence"))
    payloads = [receipt, broker, ea_reader, preflight, approval]
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
        "autoDisableMutationAllowed",
        "eaRequestReaderAllowed",
        "eaRequestReaderEnabled",
        "eaRequestFilesRead",
        "eaRequestFilesConsumed",
        "eaOrderSendAllowed",
    ))
    return [
        _check(
            "receipt_reconciliation_review_ready",
            "receipt 对账与自动停机触发源已通过",
            _ready_or_execution_mode_only(
                receipt,
                "readyForReceiptReconciliationReview",
                "dataPlaneReconciliationReady",
            ),
            "需要 planned request、broker plan 与 review-only receipt 全部匹配。",
            receipt.get("status", ""),
        ),
        _check(
            "broker_order_send_review_ready",
            "broker send wrapper 评审已通过",
            _ready_or_execution_mode_only(
                broker,
                "readyForBrokerOrderSendReview",
                "dataPlaneBrokerOrderSendReady",
            ),
            "需要 broker send plan、hash-current、request fuse 与 no-broker-call 证明。",
            broker.get("status", ""),
        ),
        _check(
            "ea_request_reader_review_ready",
            "EA reader 仍处于禁用可评审状态",
            _ready_or_execution_mode_only(
                ea_reader,
                "readyForEaRequestReaderImplementationReview",
                "dataPlaneEaRequestReaderReady",
            ),
            "需要 EA request reader 源码标记与运行时 disabled status。",
            ea_reader.get("status", ""),
        ),
        _check(
            "runtime_preflight_ready",
            "live runtime preflight 数据面通过",
            bool(preflight.get("runtimeProbePassed") or preflight.get("dataPlaneReadyForLivePilotReview")),
            "需要 fresh dashboard、account/server、symbol、spread、risk 和 kill switch 证据。",
            preflight.get("status", ""),
        ),
        _check(
            "operator_approval_evidence_accepted",
            "人工审批证据已纳入回滚评审上下文",
            bool(approval.get("operatorApprovalProvided")),
            "需要 operator approval JSON 绑定当前 review packet。",
            approval.get("status", ""),
        ),
        _check(
            "rollback_matrix_complete",
            "回滚与自动停机规则矩阵完整",
            bool(matrix and all(row.get("passed") for row in matrix)),
            "必须覆盖缺失/失败 receipt、broker send 不可用、EA reader 异常启用。",
        ),
        _check(
            "no_execution_side_effects_in_rollback_review",
            "rollback review 本身无执行副作用",
            no_side_effects,
            "该 artifact 不能写 preset/request/receipt，不能启用 reader，不能调用 broker。",
        ),
    ]


def _blockers(checklist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _blocker("LIVE_EXECUTION_ROLLBACK_CHECK_NOT_PASSED", str(row.get("reasonZh") or ""), row.get("id"))
        for row in checklist
        if not row.get("passed")
    ]


def build_live_execution_rollback_review(
    runtime_dir: Path,
    *,
    ea_source_path: str = "",
    ea_status_json: str = "",
    receipt_json: str = "",
    request_json: str = "",
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    from .approval import build_live_operator_approval_evidence_review, read_live_operator_approval_evidence_review
    from .broker_order_send import build_broker_order_send_review, read_broker_order_send_review
    from .ea_request_reader_review import build_ea_request_reader_review, read_ea_request_reader_review
    from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
    from .receipt_reconciliation import build_receipt_reconciliation_review, read_receipt_reconciliation_review

    should_rebuild = bool(
        refresh_sources
        or ea_source_path
        or ea_status_json
        or receipt_json
        or request_json
        or operator_approval_json
        or extra_bases_roots
    )
    common = {
        "operator_approval_json": operator_approval_json,
        "write": bool(write and refresh_sources),
        "refresh_sources": refresh_sources,
        "extra_bases_roots": extra_bases_roots or [],
    }
    adapter = {**common, "request_json": request_json}
    if should_rebuild:
        preflight = build_live_runtime_preflight_probe(runtime_dir, **common)
        approval = build_live_operator_approval_evidence_review(runtime_dir, **common)
        broker = build_broker_order_send_review(
            runtime_dir,
            ea_source_path=ea_source_path,
            ea_status_json=ea_status_json,
            receipt_json=receipt_json,
            **adapter,
            _allow_implementation_spec_rebuild=False,
        )
        receipt = build_receipt_reconciliation_review(
            runtime_dir,
            receipt_json=receipt_json,
            **adapter,
        )
        ea_reader = build_ea_request_reader_review(
            runtime_dir,
            ea_source_path=ea_source_path,
            ea_status_json=ea_status_json,
            receipt_json=receipt_json,
            **adapter,
        )
    else:
        preflight = read_live_runtime_preflight_probe(runtime_dir)
        approval = read_live_operator_approval_evidence_review(runtime_dir)
        broker = read_broker_order_send_review(runtime_dir)
        receipt = read_receipt_reconciliation_review(runtime_dir)
        ea_reader = read_ea_request_reader_review(runtime_dir)
    artifacts = {
        "runtimePreflight": preflight,
        "approvalEvidence": approval,
        "brokerOrderSendReview": broker,
        "receiptReconciliationReview": receipt,
        "eaRequestReaderReview": ea_reader,
    }
    matrix = _rollback_matrix(receipt, broker, ea_reader)
    release_gate = _rollback_release_gate()
    checklist = _review_checklist(artifacts, matrix)
    receipt_data_plane_ready = _ready_or_execution_mode_only(
        receipt,
        "readyForReceiptReconciliationReview",
        "dataPlaneReconciliationReady",
    )
    broker_data_plane_ready = _ready_or_execution_mode_only(
        broker,
        "readyForBrokerOrderSendReview",
        "dataPlaneBrokerOrderSendReady",
    )
    ea_reader_data_plane_ready = _ready_or_execution_mode_only(
        ea_reader,
        "readyForEaRequestReaderImplementationReview",
        "dataPlaneEaRequestReaderReady",
    )
    data_plane_ready = bool(
        receipt_data_plane_ready
        and broker_data_plane_ready
        and ea_reader_data_plane_ready
        and (preflight.get("dataPlaneReadyForLivePilotReview") or preflight.get("runtimeProbePassed"))
        and matrix
        and all(row.get("passed") for row in matrix)
        and next((row.get("passed") for row in checklist if row.get("id") == "no_execution_side_effects_in_rollback_review"), False)
    )
    execution_mode_only_blocked = bool(
        receipt.get("executionModeOnlyBlocked")
        or broker.get("executionModeOnlyBlocked")
        or ea_reader.get("executionModeOnlyBlocked")
        or preflight.get("executionModeOnlyBlocked")
        or bool(release_gate.get("tokenRequired", True) and not release_gate.get("tokenProvided"))
    )
    blockers = _blockers(checklist)
    if data_plane_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "rollback/auto-disable 数据面已具备；仅等待执行模式闸门。",
                preflight.get("status") or broker.get("status"),
            )
        ]
        if release_gate.get("tokenRequired") and not release_gate.get("tokenProvided"):
            blockers.append(_blocker(
                str(release_gate.get("blockerCode") or ROLLBACK_AUTO_DISABLE_RELEASE_BLOCKER),
                str(release_gate.get("reasonZh") or "Rollback release token 未提供，当前不能修改实盘状态。"),
                release_gate.get("source", ""),
            ))
        blockers.extend(_execution_mode_blockers(receipt, broker, ea_reader, preflight))
    ready = bool(
        checklist
        and all(row.get("passed") for row in checklist)
        and not blockers
        and not bool(release_gate.get("tokenRequired", True) and not release_gate.get("tokenProvided"))
    )
    payload = {
        "ok": True,
        "schema": LIVE_EXECUTION_ROLLBACK_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_LIVE_EXECUTION_ROLLBACK_REVIEW"
            if ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_ready and execution_mode_only_blocked
            else "WAITING_LIVE_EXECUTION_ROLLBACK_INPUTS"
        ),
        "statusZh": (
            "可进入 rollback/auto-disable 单独实现评审"
            if ready
            else "rollback/auto-disable 数据面已通过，等待执行模式闸门"
            if data_plane_ready and execution_mode_only_blocked
            else "等待 rollback/auto-disable 审查输入"
        ),
        "reviewMode": "LIVE_EXECUTION_ROLLBACK_REVIEW_ONLY_NO_MUTATION",
        "readyForLiveExecutionRollbackReview": ready,
        "dataPlaneRollbackReady": data_plane_ready,
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
        "receiptReconciliationStatus": receipt.get("status", ""),
        "brokerOrderSendStatus": broker.get("status", ""),
        "eaRequestReaderStatus": ea_reader.get("status", ""),
        "runtimePreflightStatus": preflight.get("status", ""),
        "operatorApprovalStatus": approval.get("status", ""),
        "rollbackReleaseGate": release_gate,
        "releaseTokenRequired": bool(release_gate.get("tokenRequired", True)),
        "releaseTokenProvided": bool(release_gate.get("tokenProvided")),
        "releaseTokenBlockerCode": str(release_gate.get("blockerCode") or ROLLBACK_AUTO_DISABLE_RELEASE_BLOCKER),
        "reviewPacketHash": preflight.get("reviewPacketHash") or approval.get("reviewPacketHash", ""),
        "runtimePreflightHash": receipt.get("runtimePreflightHash") or broker.get("runtimePreflightHash", ""),
        "rollbackMatrix": matrix,
        "manualRearmRequirements": [
            "operator approval JSON must be refreshed against the current reviewPacketHash",
            "runtime preflight must be regenerated and pass",
            "broker order send review must pass with no broker calls",
            "receipt reconciliation must pass with no missing, failed, or extra receipts",
        ],
        "rollbackChecklist": checklist,
        "blockers": blockers[:32],
        "nextRequiredActionZh": (
            "rollback/auto-disable 合同已可单独代码评审；当前 artifact 不会修改 preset、request、receipt 或 broker 状态。"
            if ready
            else "rollback/auto-disable 数据面已具备；仅剩执行模式闸门，当前仍不会修改任何实盘状态。"
            if data_plane_ready and execution_mode_only_blocked
            else "先让 receipt reconciliation、broker order send、EA reader、runtime preflight 和审批证据全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_execution_rollback_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_execution_rollback_review(runtime_dir: Path) -> dict[str, Any]:
    path = live_execution_rollback_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_live_execution_rollback_review(Path(runtime_dir), write=False)
