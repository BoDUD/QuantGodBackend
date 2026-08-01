from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .adapter_sandbox import build_adapter_sandbox_review_bundle, read_adapter_sandbox_review_bundle
from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .schema import (
    ADAPTER_CONTRACT_VALIDATOR_SCHEMA_VERSION,
    SAFETY,
    adapter_contract_validator_path,
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


def _read_json(path: str) -> Any:
    source = Path(path).expanduser()
    return json.loads(source.read_text(encoding="utf-8-sig"))


def _request_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("requests", "sampleRequests", "dryRunRequests", "items", "rows"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        if payload.get("requestId") or payload.get("schema") == "quantgod.mt5_reviewed_order_request.v1":
            return [payload]
    return []


def _load_request_rows(request_json: str, sandbox: dict[str, Any]) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    if request_json:
        try:
            payload = _read_json(request_json)
        except Exception as exc:
            return [], str(Path(request_json).expanduser()), [
                _blocker("ADAPTER_VALIDATOR_REQUEST_JSON_UNREADABLE", "request JSON 无法读取或解析。", str(exc))
            ]
        return _request_rows_from_payload(payload), str(Path(request_json).expanduser()), []
    return [row for row in _safe_list(sandbox.get("sampleRequests")) if isinstance(row, dict)], "adapter_sandbox_sample_requests", []


def _align_sandbox_requests_with_contract(
    requests: list[dict[str, Any]],
    *,
    request_source: str,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    if request_source != "adapter_sandbox_sample_requests":
        return requests
    review_hash = contract.get("reviewPacketHash")
    preflight_hash = contract.get("runtimePreflightHash")
    if not review_hash and not preflight_hash:
        return requests
    aligned: list[dict[str, Any]] = []
    for request in requests:
        row = dict(request)
        if review_hash:
            row["reviewPacketHash"] = review_hash
        if preflight_hash:
            row["runtimePreflightHash"] = preflight_hash
        aligned.append(row)
    return aligned


def _field_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("name")): row
        for row in _safe_list(_safe_dict(contract.get("requestContract")).get("allowedRequestFields"))
        if isinstance(row, dict) and row.get("name")
    }


def _lane_keys(contract: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {
        (
            str(row.get("lane") or ""),
            str(row.get("brokerSymbol") or ""),
            str(row.get("canonicalSymbol") or ""),
        )
        for row in _safe_list(contract.get("laneContracts"))
        if isinstance(row, dict)
    }


def _type_ok(value: Any, spec: dict[str, Any]) -> bool:
    field_type = str(spec.get("type") or "")
    if field_type == "string":
        return isinstance(value, str) and bool(value)
    if field_type == "enum":
        return isinstance(value, str) and value in set(_safe_list(spec.get("allowed")))
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "number_or_null":
        return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))
    if field_type == "string_or_null":
        return value is None or isinstance(value, str)
    return True


def _value_errors(name: str, value: Any, spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not _type_ok(value, spec):
        errors.append(f"{name}:TYPE_MISMATCH")
    if spec.get("constant") not in (None, "") and value != spec.get("constant"):
        errors.append(f"{name}:CONSTANT_MISMATCH")
    if "mustEqual" in spec and value != spec.get("mustEqual"):
        errors.append(f"{name}:MUST_EQUAL_MISMATCH")
    if "minimum" in spec and isinstance(value, (int, float)) and not isinstance(value, bool) and value < float(spec["minimum"]):
        errors.append(f"{name}:BELOW_MINIMUM")
    return errors


def _validate_request(
    request: dict[str, Any],
    *,
    contract: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    lane_keys: set[tuple[str, str, str]],
) -> dict[str, Any]:
    required = {name for name, spec in fields.items() if spec.get("required") is True}
    keys = set(request.keys())
    missing = sorted(required - keys)
    unknown = sorted(keys - set(fields.keys()))
    field_errors: list[str] = []
    for name, spec in fields.items():
        if name in request:
            field_errors.extend(_value_errors(name, request[name], spec))
    lane_key = (
        str(request.get("lane") or ""),
        str(request.get("brokerSymbol") or ""),
        str(request.get("canonicalSymbol") or ""),
    )
    lane_contract_match = bool(lane_key in lane_keys)
    if lane_keys and not lane_contract_match:
        field_errors.append("lane/brokerSymbol/canonicalSymbol:LANE_CONTRACT_MISMATCH")
    review_hash_current = bool(
        not contract.get("reviewPacketHash")
        or request.get("reviewPacketHash") == contract.get("reviewPacketHash")
    )
    preflight_hash_current = bool(
        not contract.get("runtimePreflightHash")
        or request.get("runtimePreflightHash") == contract.get("runtimePreflightHash")
    )
    if not review_hash_current:
        field_errors.append("reviewPacketHash:STALE")
    if not preflight_hash_current:
        field_errors.append("runtimePreflightHash:STALE")
    fuses_ok = all(bool(request.get(name)) is True for name in (
        "killSwitchOk",
        "runtimeFresh",
        "spreadProbeOk",
        "symbolMappingOk",
        "dryRunReplayPassed",
    ))
    passed = bool(not missing and not unknown and not field_errors and fuses_ok and request.get("requestId"))
    return {
        "requestId": str(request.get("requestId") or ""),
        "passed": passed,
        "requiredFieldsPresent": not missing,
        "unknownFieldCount": len(unknown),
        "fieldErrorCount": len(field_errors),
        "laneContractMatch": lane_contract_match,
        "reviewPacketHashCurrent": review_hash_current,
        "runtimePreflightHashCurrent": preflight_hash_current,
        "runtimeFusesOk": fuses_ok,
        "missingRequiredFields": missing,
        "unknownFields": unknown,
        "fieldErrors": field_errors,
        "payloadHash": _digest(request),
    }


def _receipt_for(request: dict[str, Any], validation: dict[str, Any], safety_hash: str) -> dict[str, Any]:
    try:
        volume = float(request.get("volumeLots") or 0)
    except (TypeError, ValueError):
        volume = 0.0
    return {
        "requestId": str(request.get("requestId") or ""),
        "schema": "quantgod.mt5_execution_receipt.v1",
        "receivedAtIso": utc_now_iso(),
        "adapterMode": "REVIEW_ONLY",
        "acceptedByAdapter": False,
        "rejectedReasonCode": (
            "REVIEW_ONLY_CONTRACT_VALIDATOR_NO_SIDE_EFFECTS"
            if validation.get("passed")
            else "REVIEW_ONLY_CONTRACT_VALIDATION_FAILED"
        ),
        "brokerSymbol": str(request.get("brokerSymbol") or ""),
        "side": str(request.get("side") or ""),
        "volumeLots": volume,
        "safetySnapshotHash": safety_hash,
        "ticket": None,
    }


def build_adapter_contract_validator(
    runtime_dir: Path,
    *,
    request_json: str = "",
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
    sandbox = build_adapter_sandbox_review_bundle(runtime_dir, **kwargs) if should_rebuild else read_adapter_sandbox_review_bundle(runtime_dir)
    requests, request_source, load_blockers = _load_request_rows(request_json, sandbox)
    requests = _align_sandbox_requests_with_contract(requests, request_source=request_source, contract=contract)
    fields = _field_map(contract)
    lane_keys = _lane_keys(contract)
    validation_rows = [
        _validate_request(request, contract=contract, fields=fields, lane_keys=lane_keys)
        for request in requests
    ]
    safety_hash = _digest({
        "contractStatus": contract.get("status", ""),
        "sandboxStatus": sandbox.get("status", ""),
        "reviewPacketHash": contract.get("reviewPacketHash", ""),
        "runtimePreflightHash": contract.get("runtimePreflightHash", ""),
        "requestSource": request_source,
    })
    receipts = [
        _receipt_for(request, validation, safety_hash)
        for request, validation in zip(requests, validation_rows)
    ]
    contract_data_plane_ready = bool(contract.get("runtimePreflightDataPlaneReadyForReview"))
    contract_execution_mode_only_blocked = bool(contract.get("runtimePreflightExecutionModeOnlyBlocked"))
    sample_validation_passed = bool(
        requests and validation_rows and all(row.get("passed") for row in validation_rows) and not load_blockers
    )
    blockers: list[dict[str, Any]] = list(load_blockers)
    if not bool(contract.get("readyForAdapterCodeReview")):
        if contract_execution_mode_only_blocked and contract_data_plane_ready:
            blockers.append(_blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "request 合同数据面和样本校验已具备；仅等待 MT5/EA 执行模式闸门。",
                contract.get("status"),
            ))
        else:
            blockers.append(_blocker("ORDER_REQUEST_CONTRACT_NOT_READY", "MT5 request contract 尚未可用于 adapter request validation。", contract.get("status")))
    if not requests:
        blockers.append(_blocker("ADAPTER_VALIDATOR_REQUESTS_MISSING", "缺少待验证的 request JSON 或 adapter sandbox sampleRequests。", request_source))
    for row in validation_rows:
        if not row.get("passed"):
            blockers.append(_blocker("ADAPTER_VALIDATOR_REQUEST_FAILED", "request 未通过 adapter contract validation。", row))
    validation_ready = bool(contract.get("readyForAdapterCodeReview") and sample_validation_passed)
    data_plane_validation_ready = bool(sample_validation_passed and contract_data_plane_ready)
    if validation_ready:
        status = "READY_FOR_ADAPTER_CONTRACT_VALIDATION_REVIEW"
        status_zh = "adapter request 合同验证通过"
        next_required_action_zh = "request/receipt 合同已离线验收；下一步仍是单独 adapter 代码评审和人工部署检查。"
    elif data_plane_validation_ready and contract_execution_mode_only_blocked:
        status = "WAITING_EXECUTION_MODE_ACTIVATION"
        status_zh = "adapter request 样本已通过，等待执行模式闸门"
        next_required_action_zh = (
            "adapter request/receipt 样本已离线验收；仅剩 livePilotMode/readOnlyMode/"
            "executionEnabled/tradeAllowed 执行模式闸门，当前仍不写 MT5 request。"
        )
    else:
        status = "WAITING_ADAPTER_CONTRACT_VALIDATION_INPUTS"
        status_zh = "等待 adapter request 合同验证输入"
        next_required_action_zh = "先让 order request contract 通过，并提供 adapter sandbox sampleRequests 或本地 request JSON。"
    payload = {
        "ok": True,
        "schema": ADAPTER_CONTRACT_VALIDATOR_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "validatorMode": "REVIEW_ONLY_CONTRACT_VALIDATION",
        "requestSource": request_source,
        "requestCount": len(requests),
        "receiptCount": len(receipts),
        "validationPassed": validation_ready,
        "sampleValidationPassed": sample_validation_passed,
        "dataPlaneValidationReady": data_plane_validation_ready,
        "contractDataPlaneReadyForReview": contract_data_plane_ready,
        "contractExecutionModeOnlyBlocked": contract_execution_mode_only_blocked,
        "reviewOnlyReceiptsGenerated": bool(receipts),
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
        "contractStatus": contract.get("status", ""),
        "sandboxStatus": sandbox.get("status", ""),
        "reviewPacketHash": contract.get("reviewPacketHash", ""),
        "runtimePreflightHash": contract.get("runtimePreflightHash", ""),
        "validatedRequests": requests,
        "validationResults": validation_rows,
        "reviewOnlyReceipts": receipts,
        "blockers": blockers,
        "nextRequiredActionZh": next_required_action_zh,
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = adapter_contract_validator_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_adapter_contract_validator(runtime_dir: Path) -> dict[str, Any]:
    path = adapter_contract_validator_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_adapter_contract_validator(Path(runtime_dir), write=False)
