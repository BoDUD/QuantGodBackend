from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .adapter_contract_validator import build_adapter_contract_validator, read_adapter_contract_validator
from .adapter_sandbox import build_adapter_sandbox_review_bundle, read_adapter_sandbox_review_bundle
from .execution_adapter_harness import build_execution_adapter_harness, read_execution_adapter_harness
from .live_execution_implementation_spec import (
    build_live_execution_implementation_spec,
    build_live_execution_implementation_spec_cutover_proxy,
    read_existing_live_execution_implementation_spec,
    read_live_execution_implementation_spec,
)
from .schema import (
    LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    live_execution_adapter_write_review_path,
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


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


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
                _blocker("LIVE_ADAPTER_REQUEST_JSON_UNREADABLE", "adapter request JSON 无法读取或解析。", str(exc))
            ]
        return _request_rows_from_payload(payload), str(Path(request_json).expanduser()), []
    return [row for row in _safe_list(sandbox.get("sampleRequests")) if isinstance(row, dict)], "adapter_sandbox_sample_requests", []


def _align_sandbox_requests_with_artifacts(
    requests: list[dict[str, Any]],
    *,
    request_source: str,
    implementation_spec: dict[str, Any],
    harness: dict[str, Any],
) -> list[dict[str, Any]]:
    if request_source != "adapter_sandbox_sample_requests":
        return requests
    handoff = _safe_dict(_safe_dict(implementation_spec.get("cutoverReview")).get("implementationHandoff"))
    review_hash = handoff.get("reviewPacketHash") or harness.get("reviewPacketHash")
    preflight_hash = handoff.get("runtimePreflightHash") or harness.get("runtimePreflightHash")
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


def _by_request_id(rows: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("requestId"):
            result[str(row["requestId"])] = row
    return result


def _requests_from_harness(harness: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for row in _safe_list(harness.get("plannedWrites")):
        if not isinstance(row, dict):
            continue
        payload = row.get("requestPayload")
        if isinstance(payload, dict):
            requests.append(dict(payload))
    return requests


def _validator_payload_hashes_current(requests: list[dict[str, Any]], validator: dict[str, Any]) -> bool:
    if not requests:
        return True
    validation_by_id = _by_request_id(_safe_list(validator.get("validationResults")))
    for request in requests:
        request_id = str(request.get("requestId") or "")
        validation = validation_by_id.get(request_id, {})
        if not validation.get("payloadHash"):
            return False
        if validation.get("payloadHash") != _digest(request):
            return False
    return True


def _prefer_ready(
    existing: dict[str, Any],
    ready_key: str,
    builder,
) -> dict[str, Any]:
    if existing.get(ready_key):
        return existing
    return builder()


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


def _write_plan(
    request: dict[str, Any],
    *,
    planned: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    payload = _canonical_json(request)
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    temp_pattern = str(planned.get("atomicTempFilePattern") or f"{planned.get('requestFilename', 'request.json')}.tmp.<pid>")
    final_path = str(planned.get("plannedRequestPath") or "")
    idempotency_key = str(planned.get("idempotencyKey") or request.get("requestId") or "")
    idempotency_payload = {
        "requestId": request.get("requestId", ""),
        "reviewPacketHash": request.get("reviewPacketHash", ""),
        "runtimePreflightHash": request.get("runtimePreflightHash", ""),
        "payloadHash": payload_hash,
    }
    return {
        "requestId": str(request.get("requestId") or ""),
        "schema": request.get("schema", ""),
        "brokerSymbol": str(request.get("brokerSymbol") or ""),
        "canonicalSymbol": str(request.get("canonicalSymbol") or ""),
        "lane": str(request.get("lane") or ""),
        "requestDirectory": str(planned.get("targetRequestDir") or (str(Path(final_path).parent) if final_path else "")),
        "receiptDirectory": str(planned.get("targetReceiptDir") or ""),
        "finalRequestPath": final_path,
        "plannedReceiptPath": str(planned.get("plannedReceiptPath") or ""),
        "tempFilePattern": temp_pattern,
        "atomicWriteRequired": planned.get("atomicWriteRequired") is True,
        "idempotencyKey": idempotency_key,
        "idempotencyHash": _digest(idempotency_payload),
        "serializedPayloadHash": payload_hash,
        "serializedByteLength": len(payload.encode("utf-8")),
        "canonicalJsonPreview": payload,
        "pathMatchesHarness": bool(final_path and final_path == str(planned.get("plannedRequestPath") or "")),
        "validatorHashMatches": bool(
            not validation.get("payloadHash")
            or validation.get("payloadHash") == _digest(request)
        ),
        "contractValidationPassed": bool(validation.get("passed")),
        "allowedToWriteLiveRequest": False,
        "wouldWriteToMt5RequestDirectory": False,
        "wouldWriteReceiptFile": False,
        "requestFilesWritten": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
    }


def _normalised_relative_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.lstrip("./")


def _relative_path_blockers(value: Any, *, expected_prefix: str) -> list[str]:
    text = _normalised_relative_path(value)
    blockers: list[str] = []
    if not text:
        blockers.append("PATH_EMPTY")
        return blockers
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        blockers.append("PATH_ABSOLUTE_FORBIDDEN")
    parts = [part for part in text.split("/") if part]
    if any(part == ".." for part in parts):
        blockers.append("PATH_TRAVERSAL_FORBIDDEN")
    if not text.startswith(expected_prefix.rstrip("/") + "/"):
        blockers.append("PATH_PREFIX_MISMATCH")
    return blockers


def _writer_runtime_preflight(runtime_dir: Path, write_plans: list[dict[str, Any]]) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    request_ids = [str(row.get("requestId") or "") for row in write_plans]
    final_paths = [_normalised_relative_path(row.get("finalRequestPath")) for row in write_plans]
    duplicate_request_ids = sorted({value for value in request_ids if value and request_ids.count(value) > 1})
    duplicate_final_paths = sorted({value for value in final_paths if value and final_paths.count(value) > 1})
    rows: list[dict[str, Any]] = []
    for plan in write_plans:
        request_id = str(plan.get("requestId") or "")
        final_path = _normalised_relative_path(plan.get("finalRequestPath"))
        receipt_path = _normalised_relative_path(plan.get("plannedReceiptPath"))
        temp_pattern = str(plan.get("tempFilePattern") or "").strip().replace("\\", "/")
        final_target = runtime_dir / final_path if final_path else runtime_dir
        temp_pattern_ok = bool(
            temp_pattern
            and "/" not in temp_pattern
            and ".tmp." in temp_pattern
            and temp_pattern.startswith(Path(final_path).name + ".tmp.")
        )
        row_blockers = [
            *_relative_path_blockers(final_path, expected_prefix="runtime/agent/mt5_order_requests"),
            *_relative_path_blockers(receipt_path, expected_prefix="runtime/agent/mt5_order_receipts"),
        ]
        if not temp_pattern_ok:
            row_blockers.append("TEMP_PATTERN_NOT_ATOMIC_SAME_DIRECTORY")
        if request_id in duplicate_request_ids:
            row_blockers.append("DUPLICATE_REQUEST_ID_IN_BATCH")
        if final_path in duplicate_final_paths:
            row_blockers.append("DUPLICATE_FINAL_REQUEST_PATH_IN_BATCH")
        if final_path and final_target.exists():
            row_blockers.append("FINAL_REQUEST_FILE_ALREADY_EXISTS")
        rows.append({
            "requestId": request_id,
            "finalRequestPath": final_path,
            "plannedReceiptPath": receipt_path,
            "tempFilePattern": temp_pattern,
            "finalRequestFileExists": bool(final_path and final_target.exists()),
            "tempPatternAtomic": temp_pattern_ok,
            "pathGuardPassed": not row_blockers,
            "blockerCodes": row_blockers,
            "requestFilesWritten": False,
            "receiptFilesWritten": False,
            "brokerCallsMade": False,
            "orderSendAllowed": False,
        })
    failed_rows = [row for row in rows if not row.get("pathGuardPassed")]
    return {
        "mode": "WRITER_RUNTIME_PREFLIGHT_ONLY_NO_FILE_WRITES",
        "status": "PASS" if rows and not failed_rows else "BLOCKED",
        "statusZh": "writer runtime 路径/幂等预检通过" if rows and not failed_rows else "writer runtime 路径/幂等预检阻断",
        "requestPlanCount": len(write_plans),
        "checkedRequestPathCount": len(rows),
        "duplicateRequestIds": duplicate_request_ids,
        "duplicateFinalRequestPaths": duplicate_final_paths,
        "pathGuardPassed": bool(rows and not failed_rows),
        "rows": rows,
        "requestWritesAllowed": False,
        "releaseTokenRequired": True,
        "releaseTokenProvided": False,
        "releaseTokenBlockerCode": "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
    }


def _checklist(
    *,
    implementation_spec: dict[str, Any],
    harness: dict[str, Any],
    validator: dict[str, Any],
    write_plans: list[dict[str, Any]],
    writer_runtime_preflight: dict[str, Any],
) -> list[dict[str, Any]]:
    steps = {
        str(row.get("stepId") or "")
        for row in _safe_list(implementation_spec.get("implementationSteps"))
        if isinstance(row, dict)
    }
    return [
        {
            "id": "implementation_spec_ready",
            "labelZh": "live execution implementation spec 可评审",
            "passed": bool(implementation_spec.get("readyForLiveExecutionImplementationSpecReview")),
            "value": implementation_spec.get("status", ""),
        },
        {
            "id": "adapter_write_step_declared",
            "labelZh": "adapter request writer PR 合同已声明",
            "passed": "live_execution_adapter_write_path" in steps,
        },
        {
            "id": "disabled_harness_ready",
            "labelZh": "disabled adapter harness 已通过",
            "passed": bool(harness.get("readyForDisabledAdapterImplementationReview")),
            "value": harness.get("status", ""),
        },
        {
            "id": "adapter_contract_validator_ready",
            "labelZh": "adapter contract validator 已通过",
            "passed": bool(validator.get("validationPassed")),
            "value": validator.get("status", ""),
        },
        {
            "id": "canonical_payloads_serialized",
            "labelZh": "request payload 可稳定序列化和哈希",
            "passed": bool(write_plans) and all(row.get("serializedPayloadHash") for row in write_plans),
        },
        {
            "id": "validator_payload_hashes_current",
            "labelZh": "validator payload hash 与当前 request 一致",
            "passed": bool(write_plans) and all(row.get("validatorHashMatches") is True for row in write_plans),
        },
        {
            "id": "atomic_write_plan_only",
            "labelZh": "仅生成原子写入计划，不写 MT5 request 文件",
            "passed": bool(write_plans)
            and all(
                row.get("atomicWriteRequired") is True
                and row.get("requestFilesWritten") is False
                and row.get("wouldWriteToMt5RequestDirectory") is False
                for row in write_plans
            ),
        },
        {
            "id": "idempotency_keys_present",
            "labelZh": "每个 request 都有幂等键和幂等 hash",
            "passed": bool(write_plans) and all(row.get("idempotencyKey") and row.get("idempotencyHash") for row in write_plans),
        },
        {
            "id": "writer_runtime_preflight_path_guard",
            "labelZh": "writer runtime 路径、tmp 模式和重复 request 预检通过",
            "passed": bool(writer_runtime_preflight.get("pathGuardPassed")),
            "value": writer_runtime_preflight.get("status", ""),
        },
        {
            "id": "no_execution_side_effects",
            "labelZh": "adapter write review 无执行副作用",
            "passed": bool(write_plans)
            and all(
                row.get("allowedToWriteLiveRequest") is False
                and row.get("brokerCallsMade") is False
                and row.get("adapterExecutionAllowed") is False
                for row in write_plans
            ),
        },
    ]


def _disabled_writer_contract(write_plans: list[dict[str, Any]]) -> dict[str, Any]:
    request_directories = sorted({
        str(row.get("requestDirectory") or "")
        for row in write_plans
        if row.get("requestDirectory")
    })
    receipt_directories = sorted({
        str(row.get("receiptDirectory") or "")
        for row in write_plans
        if row.get("receiptDirectory")
    })
    return {
        "mode": "DISABLED_WRITER_CONTRACT_ONLY",
        "status": "REVIEW_ONLY_NO_MT5_REQUEST_WRITES",
        "canWriteNow": False,
        "requestWritesAllowed": False,
        "receiptWritesAllowed": False,
        "brokerCallsAllowed": False,
        "orderSendAllowed": False,
        "releaseGate": {
            "tokenRequired": True,
            "tokenProvidedInThisArtifact": False,
            "tokenName": "QG_REVIEWED_MT5_REQUEST_WRITE_RELEASE_V1",
            "blockerCode": "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
            "reasonZh": "即使 execution_enabled 与 allow_request_write 同时为 true，没有单独审查 release token 也不能写 MT5 request 文件。",
        },
        "requestDirectories": request_directories,
        "receiptDirectories": receipt_directories,
        "commitAlgorithm": [
            "validate request schema and runtime fuse snapshot",
            "serialize canonical JSON with sorted keys and trailing newline",
            "write to requestFilename.tmp.<pid> only after a future reviewed execution gate",
            "fsync and atomic rename tmp file to final request path",
            "never write receipt files from the Python writer",
        ],
        "idempotencyPolicy": {
            "key": "requestId",
            "hashFields": [
                "requestId",
                "reviewPacketHash",
                "runtimePreflightHash",
                "payloadHash",
            ],
            "duplicatePolicy": "future writer must reject duplicate requestId without overwriting an existing request file",
        },
        "pathGuard": {
            "allowRelativeFinalPathsOnly": True,
            "allowedRequestDirectorySuffix": "runtime/agent/mt5_order_requests",
            "allowedReceiptDirectorySuffix": "runtime/agent/mt5_order_receipts",
            "absolutePathWritesForbiddenInThisArtifact": True,
        },
        "sideEffectProof": {
            "requestFilesWritten": False,
            "receiptFilesWritten": False,
            "brokerCallsMade": False,
            "livePresetMutationAllowed": False,
        },
        "writePlanHashes": [
            {
                "requestId": row.get("requestId", ""),
                "serializedPayloadHash": row.get("serializedPayloadHash", ""),
                "idempotencyHash": row.get("idempotencyHash", ""),
            }
            for row in write_plans
        ],
    }


def build_live_execution_adapter_write_review(
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
    _allow_implementation_spec_rebuild: bool = True,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
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
    kwargs = {
        "ea_source_path": ea_source_path,
        "ea_status_json": ea_status_json,
        "receipt_json": receipt_json,
        "request_json": request_json,
        "operator_approval_json": operator_approval_json,
        "write": bool(write and refresh_sources),
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots or [],
    }
    common = {
        "request_json": request_json,
        "operator_approval_json": operator_approval_json,
        "write": bool(write and refresh_sources),
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots or [],
    }
    sandbox = (
        build_adapter_sandbox_review_bundle(
            runtime_dir,
            operator_approval_json=operator_approval_json,
            write=bool(write and refresh_sources),
            refresh_sources=refresh_sources,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_adapter_sandbox_review_bundle(runtime_dir)
    )
    if should_rebuild:
        implementation_spec = (
            read_live_execution_implementation_spec(runtime_dir)
            if _allow_implementation_spec_rebuild
            else read_existing_live_execution_implementation_spec(runtime_dir)
        )
        if not implementation_spec.get("readyForLiveExecutionImplementationSpecReview"):
            implementation_spec = (
                build_live_execution_implementation_spec(runtime_dir, **kwargs)
                if _allow_implementation_spec_rebuild
                else build_live_execution_implementation_spec_cutover_proxy(runtime_dir)
            )
    else:
        implementation_spec = read_live_execution_implementation_spec(runtime_dir)
    validator = (
        _prefer_ready(
            read_adapter_contract_validator(runtime_dir),
            "validationPassed",
            lambda: build_adapter_contract_validator(runtime_dir, **common),
        )
        if should_rebuild
        else read_adapter_contract_validator(runtime_dir)
    )
    harness = (
        _prefer_ready(
            read_execution_adapter_harness(runtime_dir),
            "readyForDisabledAdapterImplementationReview",
            lambda: build_execution_adapter_harness(runtime_dir, **common),
        )
        if should_rebuild
        else read_execution_adapter_harness(runtime_dir)
    )
    requests, request_source, load_blockers = _load_request_rows(request_json, sandbox)
    harness_requests = _requests_from_harness(harness)
    if request_source == "adapter_sandbox_sample_requests" and harness_requests:
        requests = harness_requests
    else:
        requests = _align_sandbox_requests_with_artifacts(
            requests,
            request_source=request_source,
            implementation_spec=implementation_spec,
            harness=harness,
        )
    if should_rebuild and requests and not _validator_payload_hashes_current(requests, validator):
        validator = build_adapter_contract_validator(runtime_dir, **common)
    planned_by_id = _by_request_id(_safe_list(harness.get("plannedWrites")))
    validation_by_id = _by_request_id(_safe_list(validator.get("validationResults")))
    write_plans = [
        _write_plan(
            request,
            planned=planned_by_id.get(str(request.get("requestId") or ""), {}),
            validation=validation_by_id.get(str(request.get("requestId") or ""), {}),
        )
        for request in requests
    ]
    writer_runtime_preflight = _writer_runtime_preflight(runtime_dir, write_plans)
    checklist = _checklist(
        implementation_spec=implementation_spec,
        harness=harness,
        validator=validator,
        write_plans=write_plans,
        writer_runtime_preflight=writer_runtime_preflight,
    )
    blockers: list[dict[str, Any]] = list(load_blockers)
    if not (
        implementation_spec.get("readyForLiveExecutionImplementationSpecReview")
        or implementation_spec.get("dataPlaneImplementationSpecReady")
    ):
        blockers.append(_blocker(
            "LIVE_EXECUTION_IMPLEMENTATION_SPEC_NOT_READY",
            "live execution implementation spec 尚未可评审。",
            implementation_spec.get("status", ""),
        ))
    if not (
        harness.get("readyForDisabledAdapterImplementationReview")
        or harness.get("dataPlaneHarnessReady")
    ):
        blockers.append(_blocker(
            "DISABLED_ADAPTER_HARNESS_NOT_READY",
            "disabled adapter harness 尚未通过。",
            harness.get("status", ""),
        ))
    if not (
        validator.get("validationPassed")
        or validator.get("dataPlaneValidationReady")
    ):
        blockers.append(_blocker(
            "ADAPTER_CONTRACT_VALIDATOR_NOT_READY",
            "adapter contract validator 尚未通过。",
            validator.get("status", ""),
        ))
    if not requests:
        blockers.append(_blocker("LIVE_ADAPTER_REQUESTS_MISSING", "缺少 adapter request 样本或本地 request JSON。", request_source))
    for row in write_plans:
        if (
            not row.get("contractValidationPassed")
            or not row.get("validatorHashMatches")
            or not row.get("idempotencyKey")
            or not row.get("atomicWriteRequired")
        ):
            blockers.append(_blocker("LIVE_ADAPTER_WRITE_PLAN_INVALID", "adapter request 写入计划未通过校验。", row))
    if not writer_runtime_preflight.get("pathGuardPassed"):
        blockers.append(_blocker(
            "LIVE_ADAPTER_WRITER_PREFLIGHT_BLOCKED",
            "adapter writer runtime 路径、幂等或原子 tmp 模式预检未通过。",
            writer_runtime_preflight,
        ))
    data_plane_adapter_write_ready = bool(
        (
            implementation_spec.get("readyForLiveExecutionImplementationSpecReview")
            or implementation_spec.get("dataPlaneImplementationSpecReady")
        )
        and (
            harness.get("readyForDisabledAdapterImplementationReview")
            or harness.get("dataPlaneHarnessReady")
        )
        and (
            validator.get("validationPassed")
            or validator.get("dataPlaneValidationReady")
        )
        and requests
        and write_plans
        and writer_runtime_preflight.get("pathGuardPassed")
        and all(
            row.get("serializedPayloadHash")
            and row.get("contractValidationPassed") is True
            and row.get("validatorHashMatches") is True
            and row.get("idempotencyKey")
            and row.get("atomicWriteRequired") is True
            and row.get("requestFilesWritten") is False
            and row.get("wouldWriteToMt5RequestDirectory") is False
            and row.get("wouldWriteReceiptFile") is False
            and row.get("brokerCallsMade") is False
            and row.get("adapterExecutionAllowed") is False
            for row in write_plans
        )
        and not load_blockers
    )
    execution_mode_only_blocked = bool(
        implementation_spec.get("executionModeOnlyBlocked")
        or harness.get("executionModeOnlyBlocked")
        or validator.get("contractExecutionModeOnlyBlocked")
    )
    ready = bool(checklist and all(row.get("passed") for row in checklist) and not blockers)
    if data_plane_adapter_write_ready and execution_mode_only_blocked and not ready:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "adapter writer 数据面、序列化、幂等和原子写计划已具备；仅等待执行模式闸门。",
                implementation_spec.get("status") or harness.get("status") or validator.get("status"),
            )
        ]
        blockers.extend(_execution_mode_blockers(implementation_spec, harness, validator))
    payload = {
        "ok": True,
        "schema": LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_LIVE_EXECUTION_ADAPTER_WRITE_REVIEW"
            if ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_adapter_write_ready and execution_mode_only_blocked
            else "WAITING_LIVE_EXECUTION_ADAPTER_WRITE_INPUTS"
        ),
        "statusZh": (
            "可进入 live execution adapter writer 代码评审"
            if ready
            else "adapter writer 数据面已通过，等待执行模式闸门"
            if data_plane_adapter_write_ready and execution_mode_only_blocked
            else "等待 live execution adapter writer 输入"
        ),
        "reviewMode": "ADAPTER_WRITE_REVIEW_ONLY_NO_MT5_REQUEST_FILES",
        "readyForLiveExecutionAdapterWriteReview": ready,
        "dataPlaneAdapterWriteReady": data_plane_adapter_write_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "requestSource": request_source,
        "requestCount": len(requests),
        "writePlanCount": len(write_plans),
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
        "implementationSpecStatus": implementation_spec.get("status", ""),
        "adapterHarnessStatus": harness.get("status", ""),
        "adapterContractValidatorStatus": validator.get("status", ""),
        "adapterWriteChecklist": checklist,
        "disabledWriterImplementationContract": _disabled_writer_contract(write_plans),
        "writerRuntimePreflight": writer_runtime_preflight,
        "writePlans": write_plans,
        "blockers": blockers[:32],
        "nextRequiredActionZh": (
            "adapter writer 序列化/幂等/原子写计划已可代码评审；下一步仍必须单独实现并评审真实写入开关。"
            if ready
            else "adapter writer 序列化、幂等和原子写计划已具备；仅剩执行模式闸门，当前仍不会写 MT5 request。"
            if data_plane_adapter_write_ready and execution_mode_only_blocked
            else "先让 implementation spec、disabled adapter harness、contract validator 和 request 样本全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_execution_adapter_write_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_execution_adapter_write_review(runtime_dir: Path) -> dict[str, Any]:
    path = live_execution_adapter_write_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_live_execution_adapter_write_review(Path(runtime_dir), write=False)


def read_existing_live_execution_adapter_write_review(runtime_dir: Path) -> dict[str, Any]:
    path = live_execution_adapter_write_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {}
