from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approval_context import operator_approval_json_for_refresh
from .execution_adapter_harness import build_execution_adapter_harness, read_execution_adapter_harness
from .live_pilot_activation import build_live_pilot_activation_review, read_live_pilot_activation_review
from .schema import (
    RECEIPT_RECONCILIATION_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    broker_order_send_review_path,
    execution_adapter_harness_path,
    live_pilot_activation_review_path,
    receipt_reconciliation_review_path,
    utc_now_iso,
)

RECEIPT_WRITER_RELEASE_TOKEN_NAME = "QG_REVIEWED_RECEIPT_WRITER_RELEASE_V1"
RECEIPT_WRITER_RELEASE_BLOCKER = "RECEIPT_WRITER_RELEASE_TOKEN_MISSING"


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    return row


def _read_existing_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dependency_source(payload: dict[str, Any], *, prefer_existing: bool) -> str:
    if payload:
        return "existing_artifact"
    return "rebuilt_after_explicit_input" if not prefer_existing else "rebuilt_missing_artifact"


def _ready_existing_json(path: Path, ready_key: str) -> dict[str, Any]:
    payload = _read_existing_json(path)
    return payload if payload.get(ready_key) is True else {}


def _read_json(path: str) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8-sig"))


def _receipt_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("receipts", "reviewOnlyReceipts", "sampleReceipts", "items", "rows"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        if payload.get("requestId") or payload.get("schema") == "quantgod.mt5_execution_receipt.v1":
            return [payload]
    return []


def _receipts_from_harness(harness: dict[str, Any]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for row in _safe_list(harness.get("plannedWrites")):
        receipt = _safe_dict(_safe_dict(row).get("receipt"))
        if receipt:
            receipts.append(receipt)
    return receipts


def _load_receipts(receipt_json: str, harness: dict[str, Any]) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    if receipt_json:
        try:
            payload = _read_json(receipt_json)
        except Exception as exc:
            return [], str(Path(receipt_json).expanduser()), [
                _blocker("RECEIPT_JSON_UNREADABLE", "receipt JSON 无法读取或解析。", str(exc))
            ]
        return _receipt_rows_from_payload(payload), str(Path(receipt_json).expanduser()), []
    return _receipts_from_harness(harness), "execution_adapter_harness_review_only_receipts", []


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric


def _same_number(left: Any, right: Any) -> bool:
    left_num = _number(left)
    right_num = _number(right)
    if left_num is None or right_num is None:
        return left in (None, "", right) and right in (None, "", left)
    return abs(left_num - right_num) <= 1e-9


def _receipt_map(receipts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        request_id = str(receipt.get("requestId") or "")
        if request_id and request_id not in rows:
            rows[request_id] = receipt
    return rows


def _planned_rows(harness: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _safe_list(harness.get("plannedWrites")) if isinstance(row, dict)]


def _broker_plan_map(broker_send: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _safe_list(broker_send.get("brokerSendPlans")):
        if isinstance(row, dict) and row.get("requestId"):
            rows[str(row["requestId"])] = row
    return rows


def _broker_plan_current(plan: dict[str, Any]) -> bool:
    return bool(
        plan
        and plan.get("adapterWriterValidatorHashMatches") is True
        and plan.get("writePlanValidatorHashMatches") is True
        and plan.get("sourcePathLockedToEaConsumption") is True
        and plan.get("wouldCallBroker") is False
        and plan.get("brokerCallsMade") is False
        and plan.get("orderSendAllowed") is False
        and plan.get("mt5OrderSendAllowed") is False
        and plan.get("requestFilesWritten") is False
        and plan.get("receiptFilesWritten") is False
    )


def _broker_send_review_from_harness(harness: dict[str, Any]) -> dict[str, Any]:
    planned = _planned_rows(harness)
    if not planned:
        return {}
    broker_send_plans = []
    for row in planned:
        receipt = _safe_dict(row.get("receipt"))
        broker_send_plans.append({
            "requestId": str(row.get("requestId") or receipt.get("requestId") or ""),
            "brokerSymbol": row.get("brokerSymbol") or receipt.get("brokerSymbol", ""),
            "side": row.get("side") or receipt.get("side", ""),
            "volumeLots": receipt.get("volumeLots"),
            "adapterWriterValidatorHashMatches": True,
            "writePlanValidatorHashMatches": True,
            "sourcePathLockedToEaConsumption": True,
            "defaultAction": "BLOCK_REVIEW_ONLY_NO_BROKER_CALL",
            "wouldCallBroker": False,
            "brokerCallsMade": False,
            "adapterExecutionAllowed": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "brokerExecutionAllowed": False,
            "eaOrderSendAllowed": False,
            "requestWritesAllowed": False,
            "requestFilesWritten": False,
            "receiptWritesAllowed": False,
            "receiptFilesWritten": False,
            "writesMt5OrderRequest": False,
        })
    return {
        "schema": "quantgod.broker_order_send_review.v1",
        "status": "READY_FOR_BROKER_ORDER_SEND_REVIEW",
        "statusZh": "由 disabled harness plannedWrites 派生的 no-broker-call broker plan 快照",
        "reviewMode": "BROKER_ORDER_SEND_REVIEW_ONLY_NO_BROKER_CALLS",
        "readyForBrokerOrderSendReview": True,
        "dataPlaneBrokerOrderSendReady": True,
        "executionModeOnlyBlocked": bool(harness.get("executionModeOnlyBlocked")),
        "brokerSendPlanCount": len(broker_send_plans),
        "brokerSendPlans": broker_send_plans,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerExecutionAllowed": False,
        "blockers": [],
        "nextRequiredActionZh": "receipt 对账使用 disabled harness 的 no-broker-call 快照；完整 broker wrapper 仍需单独评审。",
        "safety": dict(SAFETY),
    }


def _blocked_broker_send_review_stub(reason_zh: str) -> dict[str, Any]:
    return {
        "schema": "quantgod.broker_order_send_review.v1",
        "status": "BROKER_ORDER_SEND_REVIEW_MISSING",
        "statusZh": "broker order send review 缺失，receipt 对账保持阻断",
        "reviewMode": "BROKER_ORDER_SEND_REVIEW_ONLY_NO_BROKER_CALLS",
        "readyForBrokerOrderSendReview": False,
        "dataPlaneBrokerOrderSendReady": False,
        "executionModeOnlyBlocked": True,
        "brokerSendPlanCount": 0,
        "brokerSendPlans": [],
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerExecutionAllowed": False,
        "blockers": [_blocker("BROKER_ORDER_SEND_REVIEW_MISSING", reason_zh)],
        "nextRequiredActionZh": "先生成 broker order send review 或 disabled harness broker plan；receipt 对账不会递归构建 broker review。",
        "safety": dict(SAFETY),
    }


def _validation_row(planned: dict[str, Any], receipt: dict[str, Any] | None, broker_plan: dict[str, Any] | None) -> dict[str, Any]:
    receipt = _safe_dict(receipt)
    broker_plan = _safe_dict(broker_plan)
    request_id = str(planned.get("requestId") or "")
    broker_symbol = str(planned.get("brokerSymbol") or "")
    checks = {
        "receiptFound": bool(receipt),
        "schemaOk": receipt.get("schema") == "quantgod.mt5_execution_receipt.v1",
        "adapterModeReviewOnly": receipt.get("adapterMode") == "REVIEW_ONLY",
        "acceptedByAdapterFalse": receipt.get("acceptedByAdapter") is False,
        "ticketAbsent": receipt.get("ticket") in (None, ""),
        "safetySnapshotHashPresent": bool(receipt.get("safetySnapshotHash")),
        "requestIdMatches": str(receipt.get("requestId") or "") == request_id,
        "brokerSymbolMatches": str(receipt.get("brokerSymbol") or "") == broker_symbol,
        "sideMatches": str(receipt.get("side") or "") == str(planned.get("side") or _safe_dict(planned.get("receipt")).get("side") or ""),
        "volumeMatches": _same_number(receipt.get("volumeLots"), _safe_dict(planned.get("receipt")).get("volumeLots")),
        "noBrokerSideEffects": planned.get("brokerCallsMade") is False and planned.get("adapterExecutionAllowed") is False,
        "noFileWrites": planned.get("wouldWriteRequestFile") is False and planned.get("wouldWriteReceiptFile") is False,
        "brokerSendPlanFound": bool(broker_plan),
        "brokerSendPlanHashCurrent": _broker_plan_current(broker_plan),
    }
    return {
        "requestId": request_id,
        "brokerSymbol": broker_symbol,
        "plannedReceiptPath": planned.get("plannedReceiptPath", ""),
        "receiptFound": checks["receiptFound"],
        "brokerSendPlanFound": checks["brokerSendPlanFound"],
        "brokerSendPlanHashCurrent": checks["brokerSendPlanHashCurrent"],
        "passed": all(checks.values()),
        "checks": checks,
        "receiptRejectedReasonCode": receipt.get("rejectedReasonCode", ""),
    }


def _extra_receipt_rows(receipts: list[dict[str, Any]], planned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    planned_ids = {str(row.get("requestId") or "") for row in planned if row.get("requestId")}
    rows = []
    for receipt in receipts:
        request_id = str(receipt.get("requestId") or "")
        if request_id and request_id not in planned_ids:
            rows.append({
                "requestId": request_id,
                "brokerSymbol": receipt.get("brokerSymbol", ""),
                "reasonZh": "receipt 没有匹配的 planned request。",
            })
    return rows


def _auto_disable_policy(validations: list[dict[str, Any]], extra_receipts: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in validations if not row.get("passed")]
    missing = [row for row in validations if not row.get("receiptFound")]
    return {
        "mode": "PLAN_ONLY_NO_MUTATION",
        "autoDisableMutationAllowed": False,
        "autoDisableTriggered": False,
        "wouldTriggerAutoDisable": bool(failed or extra_receipts),
        "missingReceiptCount": len(missing),
        "failedReceiptCount": len(failed),
        "extraReceiptCount": len(extra_receipts),
        "rules": [
            {
                "id": "missing_receipt",
                "triggerZh": "planned request 没有对应 receipt。",
                "plannedActionZh": "未来实盘 adapter 必须自动暂停并要求人工复核。",
            },
            {
                "id": "unexpected_live_acceptance",
                "triggerZh": "review-only 阶段出现 acceptedByAdapter=true 或 ticket。",
                "plannedActionZh": "立即阻断激活评审；当前工具不会修改任何 MT5/EA 状态。",
            },
            {
                "id": "extra_receipt",
                "triggerZh": "receipt 没有匹配的 planned requestId。",
                "plannedActionZh": "未来实盘 adapter 必须标记为孤儿回执并停止继续处理。",
            },
        ],
    }


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


def _receipt_release_gate() -> dict[str, Any]:
    return {
        "tokenRequired": True,
        "tokenProvided": False,
        "tokenName": RECEIPT_WRITER_RELEASE_TOKEN_NAME,
        "blockerCode": RECEIPT_WRITER_RELEASE_BLOCKER,
        "reasonZh": "没有单独审查 release token 时，receipt writer 不能写入或对账真实 receipt。",
        "source": "default_missing_runtime_receipt_release_gate",
    }


def build_receipt_reconciliation_review(
    runtime_dir: Path,
    *,
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

    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    upstream_inputs_provided = bool(
        request_json
        or moss_backtest_json
        or hfm_simulation_profile_json
        or hfm_contract_spec_json
        or extra_bases_roots
    )
    prefer_existing_dependencies = not upstream_inputs_provided
    common = {
        "operator_approval_json": operator_approval_json,
        "write": bool(refresh_sources),
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots or [],
    }
    adapter = {**common, "request_json": request_json}
    activation = (
        _read_existing_json(live_pilot_activation_review_path(runtime_dir))
        if prefer_existing_dependencies
        else _ready_existing_json(live_pilot_activation_review_path(runtime_dir), "readyForLivePilotActivationReview")
    )
    harness = (
        _read_existing_json(execution_adapter_harness_path(runtime_dir))
        if prefer_existing_dependencies
        else _ready_existing_json(execution_adapter_harness_path(runtime_dir), "readyForDisabledAdapterImplementationReview")
    )
    broker_send = (
        _read_existing_json(broker_order_send_review_path(runtime_dir))
        if prefer_existing_dependencies
        else {}
    )
    activation_source = _dependency_source(activation, prefer_existing=prefer_existing_dependencies)
    harness_source = _dependency_source(harness, prefer_existing=prefer_existing_dependencies)
    if not activation:
        activation = (
            build_live_pilot_activation_review(runtime_dir, **adapter)
            if refresh_sources or operator_approval_json or upstream_inputs_provided
            else read_live_pilot_activation_review(runtime_dir)
        )
    if not harness:
        harness = (
            build_execution_adapter_harness(runtime_dir, **adapter)
            if refresh_sources or operator_approval_json or upstream_inputs_provided
            else read_execution_adapter_harness(runtime_dir)
        )
    if not broker_send:
        broker_send = _broker_send_review_from_harness(harness)
    if not broker_send:
        broker_send = _blocked_broker_send_review_stub("缺少 broker order send review artifact，且 disabled harness 没有可派生 broker plan。")
    receipts, receipt_source, load_blockers = _load_receipts(receipt_json, harness)
    planned = _planned_rows(harness)
    receipt_by_request = _receipt_map(receipts)
    broker_by_request = _broker_plan_map(broker_send)
    validations = [
        _validation_row(
            row,
            receipt_by_request.get(str(row.get("requestId") or "")),
            broker_by_request.get(str(row.get("requestId") or "")),
        )
        for row in planned
    ]
    extra_receipts = _extra_receipt_rows(receipts, planned)
    release_gate = _receipt_release_gate()
    blockers: list[dict[str, Any]] = list(load_blockers)
    if not bool(activation.get("readyForLivePilotActivationReview")):
        blockers.append(_blocker("LIVE_PILOT_ACTIVATION_REVIEW_NOT_READY", "live pilot activation review 尚未通过。", activation.get("status")))
    if not bool(harness.get("readyForDisabledAdapterImplementationReview")):
        blockers.append(_blocker("DISABLED_ADAPTER_HARNESS_NOT_READY", "禁用态 adapter harness 尚未可评审。", harness.get("status")))
    if not bool(broker_send.get("readyForBrokerOrderSendReview")):
        blockers.append(_blocker("BROKER_ORDER_SEND_REVIEW_NOT_READY", "broker order send review 尚未通过。", broker_send.get("status")))
    if not planned:
        blockers.append(_blocker("RECONCILIATION_PLANNED_REQUESTS_MISSING", "缺少 planned request/receipt 路径计划。", harness.get("status")))
    if planned and not receipts:
        blockers.append(_blocker("RECONCILIATION_RECEIPTS_MISSING", "缺少 review-only receipts。", receipt_source))
    for row in validations:
        if not row.get("passed"):
            blockers.append(_blocker("RECONCILIATION_RECEIPT_VALIDATION_FAILED", "receipt 对账校验未通过。", row))
    for row in extra_receipts:
        blockers.append(_blocker("RECONCILIATION_EXTRA_RECEIPT", "receipt 没有匹配的 planned request。", row))
    broker_send_data_plane_ready = bool(
        broker_send.get("readyForBrokerOrderSendReview")
        or (
            broker_send.get("dataPlaneBrokerOrderSendReady")
            and broker_send.get("executionModeOnlyBlocked")
        )
    )
    review_only_receipts_reconciled = bool(
        planned
        and receipts
        and validations
        and all(row.get("passed") for row in validations)
        and not extra_receipts
        and not load_blockers
        and broker_send_data_plane_ready
    )
    execution_mode_only_blocked = bool(
        activation.get("executionModeOnlyBlocked")
        or harness.get("executionModeOnlyBlocked")
        or broker_send.get("executionModeOnlyBlocked")
        or bool(release_gate.get("tokenRequired", True) and not release_gate.get("tokenProvided"))
    )
    data_plane_reconciliation_ready = bool(
        activation.get("dataPlaneActivationReady")
        and harness.get("dataPlaneHarnessReady")
        and broker_send.get("dataPlaneBrokerOrderSendReady")
        and review_only_receipts_reconciled
    )
    if data_plane_reconciliation_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "receipt 对账数据面、planned request 和 review-only receipt 已具备；仅等待执行模式闸门。",
                activation.get("status") or harness.get("status"),
            )
        ]
        if release_gate.get("tokenRequired") and not release_gate.get("tokenProvided"):
            blockers.append(_blocker(
                str(release_gate.get("blockerCode") or RECEIPT_WRITER_RELEASE_BLOCKER),
                str(release_gate.get("reasonZh") or "Receipt writer release token 未提供，当前不能写 receipt。"),
                release_gate.get("source", ""),
            ))
        blockers.extend(_execution_mode_blockers(activation, harness))
    reconciliation_passed = bool(
        activation.get("readyForLivePilotActivationReview")
        and harness.get("readyForDisabledAdapterImplementationReview")
        and broker_send.get("readyForBrokerOrderSendReview")
        and review_only_receipts_reconciled
        and not bool(release_gate.get("tokenRequired", True) and not release_gate.get("tokenProvided"))
    )
    payload = {
        "ok": True,
        "schema": RECEIPT_RECONCILIATION_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_RECEIPT_RECONCILIATION_REVIEW"
            if reconciliation_passed
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_reconciliation_ready and execution_mode_only_blocked
            else "WAITING_RECEIPT_RECONCILIATION_INPUTS"
        ),
        "statusZh": (
            "可进入 receipt reconciliation 评审"
            if reconciliation_passed
            else "receipt 对账数据面已通过，等待执行模式闸门"
            if data_plane_reconciliation_ready and execution_mode_only_blocked
            else "等待 receipt reconciliation 输入"
        ),
        "reviewMode": "RECEIPT_RECONCILIATION_REVIEW_ONLY_NO_SIDE_EFFECTS",
        "reconciliationPassed": reconciliation_passed,
        "readyForReceiptReconciliationReview": reconciliation_passed,
        "dataPlaneReconciliationReady": data_plane_reconciliation_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "reviewOnlyReceiptsReconciled": review_only_receipts_reconciled,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "livePilotActivationAllowed": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "dependencyRefreshMode": {
            "refreshSources": bool(refresh_sources),
            "upstreamInputsProvided": upstream_inputs_provided,
            "activationReview": activation_source,
            "adapterHarness": harness_source,
        },
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
        "receiptSource": receipt_source,
        "plannedRequestCount": len(planned),
        "receiptCount": len(receipts),
        "matchedReceiptCount": sum(1 for row in validations if row.get("receiptFound")),
        "failedReceiptCount": sum(1 for row in validations if not row.get("passed")),
        "extraReceiptCount": len(extra_receipts),
        "activationReviewStatus": activation.get("status", ""),
        "adapterHarnessStatus": harness.get("status", ""),
        "brokerOrderSendStatus": broker_send.get("status", ""),
        "brokerSendPlanCount": len(_safe_list(broker_send.get("brokerSendPlans"))),
        "receiptReleaseGate": release_gate,
        "releaseTokenRequired": bool(release_gate.get("tokenRequired", True)),
        "releaseTokenProvided": bool(release_gate.get("tokenProvided")),
        "releaseTokenBlockerCode": str(release_gate.get("blockerCode") or RECEIPT_WRITER_RELEASE_BLOCKER),
        "reviewPacketHash": harness.get("reviewPacketHash", ""),
        "runtimePreflightHash": harness.get("runtimePreflightHash", ""),
        "reconciliationResults": validations,
        "extraReceipts": extra_receipts,
        "autoDisablePolicy": _auto_disable_policy(validations, extra_receipts),
        "blockers": blockers[:32],
        "nextRequiredActionZh": (
            "receipt 对账规则已可评审；下一步仍是单独真实 adapter/EA request reader/rollback 实现评审。"
            if reconciliation_passed
            else "receipt planned request 与 review-only receipt 已对账；仅剩执行模式闸门，当前仍不会写 receipt 或调用 broker。"
            if data_plane_reconciliation_ready and execution_mode_only_blocked
            else "先让 live pilot activation review 和 disabled harness 通过，并提供可匹配的 review-only receipts。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = receipt_reconciliation_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_receipt_reconciliation_review(runtime_dir: Path) -> dict[str, Any]:
    path = receipt_reconciliation_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_receipt_reconciliation_review(Path(runtime_dir), write=False)
