from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .adapter_contract_validator import build_adapter_contract_validator, read_adapter_contract_validator
from .adapter_sandbox import build_adapter_sandbox_review_bundle, read_adapter_sandbox_review_bundle
from .approval_context import operator_approval_json_for_refresh
from .orchestrator import build_sim_to_live_orchestrator, read_sim_to_live_orchestrator
from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .schema import (
    EXECUTION_ADAPTER_HARNESS_SCHEMA_VERSION,
    SAFETY,
    adapter_contract_validator_path,
    adapter_sandbox_review_path,
    assert_no_execution_flags,
    execution_adapter_harness_path,
    order_request_contract_path,
    sim_to_live_orchestrator_path,
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


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_filename(value: Any) -> str:
    text = str(value or "request").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text[:96] or "request"


def _read_json(path: str) -> Any:
    source = Path(path).expanduser()
    return json.loads(source.read_text(encoding="utf-8-sig"))


def _read_existing_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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
                _blocker("ADAPTER_HARNESS_REQUEST_JSON_UNREADABLE", "harness request JSON 无法读取或解析。", str(exc))
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


def _validation_map(validator: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _safe_list(validator.get("validationResults")):
        if isinstance(row, dict) and row.get("requestId"):
            rows[str(row["requestId"])] = row
    return rows


def _validated_requests_from_validator(validator: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in _safe_list(validator.get("validatedRequests"))
        if isinstance(row, dict)
    ]


def _review_receipt(request: dict[str, Any], *, safety_hash: str) -> dict[str, Any]:
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
        "rejectedReasonCode": "DISABLED_ADAPTER_HARNESS_NO_SIDE_EFFECTS",
        "brokerSymbol": str(request.get("brokerSymbol") or ""),
        "side": str(request.get("side") or ""),
        "volumeLots": volume,
        "safetySnapshotHash": safety_hash,
        "ticket": None,
    }


def _planned_write(
    request: dict[str, Any],
    *,
    contract: dict[str, Any],
    safety_hash: str,
) -> dict[str, Any]:
    request_contract = _safe_dict(contract.get("requestContract"))
    request_id = str(request.get("requestId") or "")
    filename = f"{_safe_filename(request_id)}.json"
    receipt_filename = f"{_safe_filename(request_id)}.receipt.json"
    request_dir = str(request_contract.get("requestDirectory") or "runtime/agent/mt5_order_requests")
    receipt_dir = str(request_contract.get("receiptDirectory") or "runtime/agent/mt5_order_receipts")
    request_hash = _digest(request)
    receipt = _review_receipt(request, safety_hash=safety_hash)
    return {
        "requestId": request_id,
        "lane": str(request.get("lane") or ""),
        "brokerSymbol": str(request.get("brokerSymbol") or ""),
        "canonicalSymbol": str(request.get("canonicalSymbol") or ""),
        "targetRequestDir": request_dir,
        "targetReceiptDir": receipt_dir,
        "requestFilename": filename,
        "receiptFilename": receipt_filename,
        "plannedRequestPath": str(Path(request_dir) / filename),
        "plannedReceiptPath": str(Path(receipt_dir) / receipt_filename),
        "atomicTempFilePattern": f"{filename}.tmp.<pid>",
        "atomicWriteRequired": True,
        "idempotencyKey": request_id,
        "idempotencyHash": _digest({
            "requestId": request_id,
            "reviewPacketHash": request.get("reviewPacketHash", ""),
            "runtimePreflightHash": request.get("runtimePreflightHash", ""),
            "payloadHash": request_hash,
        }),
        "requestPayloadHash": request_hash,
        "requestPayload": request,
        "wouldWriteRequestFile": False,
        "wouldWriteReceiptFile": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "receipt": receipt,
    }


def _harness_validation(
    planned: dict[str, Any],
    *,
    validator_rows: dict[str, dict[str, Any]],
    orchestrator_ready: bool,
) -> dict[str, Any]:
    request_id = str(planned.get("requestId") or "")
    validator_row = validator_rows.get(request_id, {})
    receipt = _safe_dict(planned.get("receipt"))
    checks = {
        "orchestratorReady": bool(orchestrator_ready),
        "contractValidationPassed": bool(validator_row.get("passed")),
        "idempotencyKeyPresent": bool(planned.get("idempotencyKey")),
        "atomicWriteRequired": planned.get("atomicWriteRequired") is True,
        "targetDirectoriesPresent": bool(planned.get("targetRequestDir") and planned.get("targetReceiptDir")),
        "receiptRejectedReviewOnly": receipt.get("acceptedByAdapter") is False,
        "wouldNotWriteRequestFile": planned.get("wouldWriteRequestFile") is False,
        "wouldNotWriteReceiptFile": planned.get("wouldWriteReceiptFile") is False,
        "noBrokerCalls": planned.get("brokerCallsMade") is False,
        "adapterExecutionDisabled": planned.get("adapterExecutionAllowed") is False,
    }
    data_plane_checks = {
        key: value
        for key, value in checks.items()
        if key != "orchestratorReady"
    }
    return {
        "requestId": request_id,
        "passed": all(checks.values()),
        "dataPlanePassed": all(data_plane_checks.values()),
        "checks": checks,
        "validatorPayloadHash": validator_row.get("payloadHash", ""),
        "requestPayloadHash": planned.get("requestPayloadHash", ""),
    }


def _implementation_checklist(
    *,
    orchestrator: dict[str, Any],
    validator: dict[str, Any],
    planned_writes: list[dict[str, Any]],
    validations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": "orchestrator_review_chain",
            "labelZh": "总控状态机到达 adapter 实现评审边界",
            "passed": bool(orchestrator.get("readyForExecutionAdapterImplementationReview")),
        },
        {
            "id": "adapter_contract_validation",
            "labelZh": "request/receipt 合同已离线验证",
            "passed": bool(validator.get("validationPassed")),
        },
        {
            "id": "planned_write_map",
            "labelZh": "生成 request/receipt 路径计划但不写文件",
            "passed": bool(planned_writes) and all(row.get("wouldWriteRequestFile") is False for row in planned_writes),
        },
        {
            "id": "idempotency_and_atomicity",
            "labelZh": "每个 request 都有幂等键和原子写入计划",
            "passed": bool(planned_writes) and all(row.get("idempotencyKey") and row.get("atomicWriteRequired") is True for row in planned_writes),
        },
        {
            "id": "receipt_reconciliation",
            "labelZh": "每个 request 都有 review-only receipt 回执计划",
            "passed": bool(planned_writes) and all(_safe_dict(row.get("receipt")).get("acceptedByAdapter") is False for row in planned_writes),
        },
        {
            "id": "side_effects_disabled",
            "labelZh": "请求写入、回执写入和 broker 调用全部关闭",
            "passed": bool(validations) and all(row.get("passed") for row in validations),
        },
    ]


def build_execution_adapter_harness(
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
    should_rebuild = bool(refresh_sources or request_json)
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    common = {
        "operator_approval_json": operator_approval_json,
        "write": bool(write and refresh_sources),
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots or [],
    }
    adapter = {**common, "request_json": request_json}
    orchestrator = {} if should_rebuild else _read_existing_json(sim_to_live_orchestrator_path(runtime_dir))
    contract = {} if should_rebuild else _read_existing_json(order_request_contract_path(runtime_dir))
    sandbox = {} if should_rebuild else _read_existing_json(adapter_sandbox_review_path(runtime_dir))
    validator = {} if should_rebuild else _read_existing_json(adapter_contract_validator_path(runtime_dir))
    if not orchestrator:
        orchestrator = build_sim_to_live_orchestrator(runtime_dir, **adapter) if should_rebuild or operator_approval_json or moss_backtest_json or hfm_simulation_profile_json or hfm_contract_spec_json or extra_bases_roots else read_sim_to_live_orchestrator(runtime_dir)
    if not contract:
        contract = build_mt5_order_request_contract(runtime_dir, **common) if should_rebuild or operator_approval_json or moss_backtest_json or hfm_simulation_profile_json or hfm_contract_spec_json or extra_bases_roots else read_mt5_order_request_contract(runtime_dir)
    if not sandbox:
        sandbox = build_adapter_sandbox_review_bundle(runtime_dir, **common) if should_rebuild or operator_approval_json or moss_backtest_json or hfm_simulation_profile_json or hfm_contract_spec_json or extra_bases_roots else read_adapter_sandbox_review_bundle(runtime_dir)
    if not validator:
        validator = build_adapter_contract_validator(runtime_dir, **adapter) if should_rebuild or operator_approval_json or moss_backtest_json or hfm_simulation_profile_json or hfm_contract_spec_json or extra_bases_roots else read_adapter_contract_validator(runtime_dir)
    requests, request_source, load_blockers = _load_request_rows(request_json, sandbox)
    requests = _align_sandbox_requests_with_contract(requests, request_source=request_source, contract=contract)
    validator_requests = _validated_requests_from_validator(validator)
    if request_source == "adapter_sandbox_sample_requests" and validator_requests:
        requests = validator_requests
    safety_hash = _digest({
        "orchestratorStatus": orchestrator.get("status", ""),
        "validatorStatus": validator.get("status", ""),
        "reviewPacketHash": contract.get("reviewPacketHash", ""),
        "runtimePreflightHash": contract.get("runtimePreflightHash", ""),
        "requestSource": request_source,
    })
    planned_writes = [_planned_write(row, contract=contract, safety_hash=safety_hash) for row in requests]
    validations = [
        _harness_validation(
            row,
            validator_rows=_validation_map(validator),
            orchestrator_ready=bool(orchestrator.get("readyForExecutionAdapterImplementationReview")),
        )
        for row in planned_writes
    ]
    checklist = _implementation_checklist(
        orchestrator=orchestrator,
        validator=validator,
        planned_writes=planned_writes,
        validations=validations,
    )
    execution_mode_only_blocked = bool(
        contract.get("runtimePreflightExecutionModeOnlyBlocked")
        or validator.get("contractExecutionModeOnlyBlocked")
    )
    sample_validation_passed = bool(
        validator.get("sampleValidationPassed") or validator.get("validationPassed")
    )
    data_plane_harness_ready = bool(
        planned_writes
        and validations
        and all(row.get("dataPlanePassed") for row in validations)
        and sample_validation_passed
        and not load_blockers
    )
    blockers: list[dict[str, Any]] = list(load_blockers)
    if not bool(orchestrator.get("readyForExecutionAdapterImplementationReview")):
        blockers.append(_blocker("SIM_TO_LIVE_ORCHESTRATOR_NOT_READY", "总控状态机尚未到达 adapter 实现评审边界。", orchestrator.get("status")))
        blockers.extend(item for item in _safe_list(orchestrator.get("blockers"))[:8] if isinstance(item, dict))
    if not bool(validator.get("validationPassed")):
        blockers.append(_blocker("ADAPTER_CONTRACT_VALIDATOR_NOT_PASSED", "adapter contract validator 尚未通过。", validator.get("status")))
    if not requests:
        blockers.append(_blocker("ADAPTER_HARNESS_REQUESTS_MISSING", "缺少 adapter sandbox sampleRequests 或本地 request JSON。", request_source))
    for row in validations:
        if not row.get("passed"):
            blockers.append(_blocker("ADAPTER_HARNESS_VALIDATION_FAILED", "禁用态 adapter harness 校验未通过。", row))
    if data_plane_harness_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "禁用态 adapter harness 数据面、样本、路径、幂等和 review-only receipt 已具备；仅等待 MT5/EA 执行模式闸门。",
                contract.get("status"),
            )
        ]
        blockers.extend(
            item
            for item in _safe_list(contract.get("runtimePreflightExecutionModeBlockers"))
            if isinstance(item, dict)
        )
    harness_ready = bool(
        orchestrator.get("readyForExecutionAdapterImplementationReview")
        and validator.get("validationPassed")
        and planned_writes
        and validations
        and all(row.get("passed") for row in validations)
        and not load_blockers
    )
    payload = {
        "ok": True,
        "schema": EXECUTION_ADAPTER_HARNESS_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_DISABLED_ADAPTER_IMPLEMENTATION_HARNESS_REVIEW"
            if harness_ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_harness_ready and execution_mode_only_blocked
            else "WAITING_EXECUTION_ADAPTER_HARNESS_INPUTS"
        ),
        "statusZh": (
            "可进入禁用态 adapter 实现 harness 评审"
            if harness_ready
            else "禁用态 adapter harness 已生成，等待执行模式闸门"
            if data_plane_harness_ready and execution_mode_only_blocked
            else "等待 execution adapter harness 输入"
        ),
        "harnessMode": "DISABLED_REVIEW_ONLY_NO_SIDE_EFFECTS",
        "readyForDisabledAdapterImplementationReview": harness_ready,
        "dataPlaneHarnessReady": data_plane_harness_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "sampleValidationPassed": sample_validation_passed,
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
        "requestSource": request_source,
        "requestCount": len(requests),
        "plannedWriteCount": len(planned_writes),
        "reviewOnlyReceiptCount": len(planned_writes),
        "orchestratorStatus": orchestrator.get("status", ""),
        "adapterContractValidatorStatus": validator.get("status", ""),
        "requestDirectoryTarget": _safe_dict(contract.get("requestContract")).get("requestDirectory", ""),
        "receiptDirectoryTarget": _safe_dict(contract.get("requestContract")).get("receiptDirectory", ""),
        "reviewPacketHash": contract.get("reviewPacketHash", ""),
        "runtimePreflightHash": contract.get("runtimePreflightHash", ""),
        "implementationChecklist": checklist,
        "plannedWrites": planned_writes,
        "validationResults": validations,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "可以单独评审禁用态 adapter 实现；当前 harness 仍不会写 request/receipt 文件或调用 broker。"
            if harness_ready
            else "禁用态 request/receipt 路径、幂等、原子写计划和 review-only receipt 已具备；仅剩执行模式闸门，当前仍不会写文件或调用 broker。"
            if data_plane_harness_ready and execution_mode_only_blocked
            else "先让 orchestrator、adapter sandbox 和 adapter contract validator 全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = execution_adapter_harness_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_execution_adapter_harness(runtime_dir: Path) -> dict[str, Any]:
    path = execution_adapter_harness_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_execution_adapter_harness(Path(runtime_dir), write=False)
