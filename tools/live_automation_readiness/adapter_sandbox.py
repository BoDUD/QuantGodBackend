from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .execution_adapter_review import build_execution_adapter_review, read_execution_adapter_review
from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .schema import (
    ADAPTER_SANDBOX_REVIEW_SCHEMA_VERSION,
    SAFETY,
    adapter_sandbox_review_path,
    assert_no_execution_flags,
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


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _names(rows: list[Any]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            result.add(str(row["name"]))
    return result


def _sample_request(lane: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    intent_id = str(lane.get("intentId") or lane.get("lane") or "intent")
    return {
        "requestId": f"sandbox-review-{intent_id}",
        "schema": "quantgod.mt5_reviewed_order_request.v1",
        "createdAtIso": "1970-01-01T00:00:00Z",
        "reviewPacketHash": contract.get("reviewPacketHash", ""),
        "runtimePreflightHash": contract.get("runtimePreflightHash", ""),
        "operatorApprovalId": "review-only-operator-approval",
        "lane": lane.get("lane", ""),
        "brokerSymbol": lane.get("brokerSymbol", ""),
        "canonicalSymbol": lane.get("canonicalSymbol", ""),
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


def _sample_receipt(request: dict[str, Any], safety_hash: str) -> dict[str, Any]:
    return {
        "requestId": request.get("requestId", ""),
        "schema": "quantgod.mt5_execution_receipt.v1",
        "receivedAtIso": utc_now_iso(),
        "adapterMode": "REVIEW_ONLY",
        "acceptedByAdapter": False,
        "rejectedReasonCode": "SANDBOX_REVIEW_ONLY_NO_SIDE_EFFECTS",
        "brokerSymbol": request.get("brokerSymbol", ""),
        "side": request.get("side", ""),
        "volumeLots": request.get("volumeLots", 0.0),
        "safetySnapshotHash": safety_hash,
        "ticket": None,
    }


def _validation_rows(samples: list[dict[str, Any]], contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    request_contract = _safe_dict(contract.get("requestContract"))
    required = {
        row.get("name")
        for row in _safe_list(request_contract.get("allowedRequestFields"))
        if isinstance(row, dict) and row.get("required") is True and row.get("name")
    }
    allowed = _names(_safe_list(request_contract.get("allowedRequestFields")))
    rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for sample in samples:
        keys = set(sample.keys())
        missing = sorted(required - keys)
        unknown = sorted(keys - allowed)
        request_id = str(sample.get("requestId") or "")
        row = {
            "requestId": request_id,
            "requiredFieldsPresent": not missing,
            "unknownFieldCount": len(unknown),
            "missingRequiredFields": missing,
            "unknownFields": unknown,
            "idempotencyKeyPresent": bool(request_id),
            "payloadHash": _digest(sample),
            "passed": bool(not missing and not unknown and request_id),
        }
        if not row["passed"]:
            blockers.append(_blocker("SANDBOX_SAMPLE_REQUEST_INVALID", "沙盒 request 样本未通过字段合同校验。", row))
        rows.append(row)
    return rows, blockers


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


def build_adapter_sandbox_review_bundle(
    runtime_dir: Path,
    *,
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    should_rebuild = bool(
        refresh_sources
        or operator_approval_json
        or extra_bases_roots
    )
    kwargs = {
        "operator_approval_json": operator_approval_json,
        "write": bool(write and refresh_sources),
        "refresh_sources": refresh_sources,
        "extra_bases_roots": extra_bases_roots or [],
    }
    contract = build_mt5_order_request_contract(runtime_dir, **kwargs) if should_rebuild else read_mt5_order_request_contract(runtime_dir)
    adapter_review = build_execution_adapter_review(runtime_dir, **kwargs) if should_rebuild else read_execution_adapter_review(runtime_dir)
    blockers: list[dict[str, Any]] = []
    if not bool(contract.get("readyForAdapterCodeReview")):
        blockers.append(_blocker("ORDER_REQUEST_CONTRACT_NOT_READY", "MT5 request contract 尚未可进入沙盒序列化审查。", contract.get("status")))
        blockers.extend(item for item in _safe_list(contract.get("blockers")) if isinstance(item, dict))
    if not bool(adapter_review.get("readyForExecutionAdapterCodeReview")):
        blockers.append(_blocker("ADAPTER_REVIEW_NOT_READY", "execution adapter review 尚未到达代码评审边界。", adapter_review.get("status")))
        blockers.extend(item for item in _safe_list(adapter_review.get("blockers")) if isinstance(item, dict))
    lane_rows = [row for row in _safe_list(contract.get("laneContracts")) if isinstance(row, dict)]
    samples = [_sample_request(row, contract) for row in lane_rows]
    safety_hash = _digest({
        "contractStatus": contract.get("status", ""),
        "adapterStatus": adapter_review.get("status", ""),
        "reviewPacketHash": contract.get("reviewPacketHash", ""),
        "runtimePreflightHash": contract.get("runtimePreflightHash", ""),
    })
    receipts = [_sample_receipt(sample, safety_hash) for sample in samples]
    validations, validation_blockers = _validation_rows(samples, contract)
    blockers.extend(validation_blockers)
    data_plane_sandbox_ready = bool(
        contract.get("runtimePreflightDataPlaneReadyForReview")
        and (
            adapter_review.get("readyForExecutionAdapterCodeReview")
            or adapter_review.get("dataPlaneAdapterReviewReady")
        )
        and samples
        and validations
        and all(row.get("passed") for row in validations)
        and not validation_blockers
    )
    execution_mode_only_blocked = bool(
        contract.get("runtimePreflightExecutionModeOnlyBlocked")
        or adapter_review.get("executionModeOnlyBlocked")
    )
    if data_plane_sandbox_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "adapter sandbox 数据面、样本序列化和 review-only receipts 已具备；仅等待执行模式闸门。",
                contract.get("status") or adapter_review.get("status"),
            )
        ]
        blockers.extend(_execution_mode_blockers(contract, adapter_review))
    sandbox_ready = bool(contract.get("readyForAdapterCodeReview") and adapter_review.get("readyForExecutionAdapterCodeReview") and samples and not blockers)
    payload = {
        "ok": True,
        "schema": ADAPTER_SANDBOX_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_ADAPTER_SANDBOX_REVIEW"
            if sandbox_ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_sandbox_ready and execution_mode_only_blocked
            else "WAITING_ADAPTER_SANDBOX_INPUTS"
        ),
        "statusZh": (
            "adapter 沙盒序列化审查通过"
            if sandbox_ready
            else "adapter sandbox 数据面已通过，等待执行模式闸门"
            if data_plane_sandbox_ready and execution_mode_only_blocked
            else "等待 adapter 沙盒审查输入"
        ),
        "sandboxReadyForCodeReview": sandbox_ready,
        "dataPlaneSandboxReady": data_plane_sandbox_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "reviewBundleWritten": bool(write),
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
        "reviewMode": "SANDBOX_REVIEW_ONLY",
        "requestDirectoryTarget": _safe_dict(contract.get("requestContract")).get("requestDirectory", ""),
        "receiptDirectoryTarget": _safe_dict(contract.get("requestContract")).get("receiptDirectory", ""),
        "reviewBundlePath": str(adapter_sandbox_review_path(runtime_dir)),
        "sampleRequestCount": len(samples),
        "sampleReceiptCount": len(receipts),
        "sampleRequests": samples,
        "sampleReceipts": receipts,
        "validationResults": validations,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "沙盒序列化已通过；下一步仍是单独 adapter 代码评审，不能直接写 MT5 请求目录。"
            if sandbox_ready
            else "adapter sandbox 数据面、样本和 review-only receipts 已具备；仅剩执行模式闸门，当前仍不会写 MT5 request 或调用 broker。"
            if data_plane_sandbox_ready and execution_mode_only_blocked
            else "先让 request contract、runtime preflight 和 execution adapter review 全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = adapter_sandbox_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_adapter_sandbox_review_bundle(runtime_dir: Path) -> dict[str, Any]:
    path = adapter_sandbox_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_adapter_sandbox_review_bundle(Path(runtime_dir), write=False)
