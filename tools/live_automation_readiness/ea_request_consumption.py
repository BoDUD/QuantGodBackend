from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ea_request_reader_review import build_ea_request_reader_review, read_ea_request_reader_review
from .live_execution_adapter import (
    build_live_execution_adapter_write_review,
    read_live_execution_adapter_write_review,
)
from .live_execution_implementation_spec import (
    build_live_execution_implementation_spec,
    read_live_execution_implementation_spec,
)
from .schema import (
    EA_REQUEST_CONSUMPTION_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    ea_request_consumption_review_path,
    utc_now_iso,
)

EA_REQUEST_READER_RELEASE_TOKEN_NAME = "QG_REVIEWED_EA_REQUEST_READER_RELEASE_V1"
EA_REQUEST_READER_RELEASE_BLOCKER = "REQUEST_READER_RELEASE_TOKEN_MISSING"


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    return row


def _dir_from_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return str(Path(text).parent)


def _step_ids(implementation_spec: dict[str, Any]) -> set[str]:
    return {
        str(row.get("stepId") or "")
        for row in _safe_list(implementation_spec.get("implementationSteps"))
        if isinstance(row, dict)
    }


def _reader_contract(ea_reader: dict[str, Any]) -> dict[str, Any]:
    return _safe_dict(ea_reader.get("readerImplementationContract"))


def _adapter_write_hashes_current(adapter_write: dict[str, Any]) -> bool:
    write_plans = [row for row in _safe_list(adapter_write.get("writePlans")) if isinstance(row, dict)]
    return bool(write_plans) and all(row.get("validatorHashMatches") is True for row in write_plans)


def _runtime_status(ea_reader: dict[str, Any]) -> dict[str, Any]:
    return _safe_dict(ea_reader.get("runtimeStatusReview"))


def _reader_release_gate(runtime_status: dict[str, Any]) -> dict[str, Any]:
    release_gate = _safe_dict(runtime_status.get("releaseGate"))
    token_required = release_gate.get("tokenRequired")
    token_provided = release_gate.get("tokenProvided")
    return {
        "tokenRequired": True if token_required is None else bool(token_required),
        "tokenProvided": bool(token_provided),
        "tokenName": str(release_gate.get("tokenName") or EA_REQUEST_READER_RELEASE_TOKEN_NAME),
        "blockerCode": str(release_gate.get("blockerCode") or EA_REQUEST_READER_RELEASE_BLOCKER),
        "reasonZh": (
            release_gate.get("reasonZh")
            or release_gate.get("reason")
            or "没有单独审查 release token 时，EA request reader 不能读取或消费 request 文件。"
        ),
        "source": "runtimeStatusReview.releaseGate" if release_gate else "default_missing_runtime_release_gate",
    }


def _plan_receipt_path(write_plan: dict[str, Any], receipt_dir: str) -> str:
    planned = str(write_plan.get("plannedReceiptPath") or "")
    if planned:
        return planned
    request_id = str(write_plan.get("requestId") or "request")
    return str(Path(receipt_dir or "runtime/agent/mt5_order_receipts") / f"{request_id}.receipt.json")


def _normalized_dir(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.rstrip("/")


def _consumption_plan(
    write_plan: dict[str, Any],
    *,
    reader_contract: dict[str, Any],
    release_gate: dict[str, Any],
) -> dict[str, Any]:
    request_path = str(write_plan.get("finalRequestPath") or "")
    request_dir = str(write_plan.get("requestDirectory") or _dir_from_path(request_path))
    receipt_dir = str(write_plan.get("receiptDirectory") or reader_contract.get("receiptDirectory") or "")
    return {
        "requestId": str(write_plan.get("requestId") or ""),
        "requestPath": request_path,
        "receiptPath": _plan_receipt_path(write_plan, receipt_dir),
        "requestDirectory": request_dir,
        "receiptDirectory": receipt_dir,
        "idempotencyKey": str(write_plan.get("idempotencyKey") or ""),
        "schemaValidationRequired": True,
        "killSwitchRequired": True,
        "receiptRequired": True,
        "idempotencyRequired": True,
        "defaultAction": "REJECT_REVIEW_ONLY",
        "releaseTokenRequired": bool(release_gate.get("tokenRequired", True)),
        "releaseTokenProvided": bool(release_gate.get("tokenProvided")),
        "releaseTokenBlockerCode": str(release_gate.get("blockerCode") or EA_REQUEST_READER_RELEASE_BLOCKER),
        "contractValidationPassed": bool(write_plan.get("contractValidationPassed")),
        "adapterWriterValidatorHashMatches": write_plan.get("validatorHashMatches") is True,
        "atomicWriteRequired": write_plan.get("atomicWriteRequired") is True,
        "stableSerializationRequired": bool(write_plan.get("serializedPayloadHash")),
        "wouldReadRequestFile": False,
        "wouldConsumeRequestFile": False,
        "wouldWriteReceiptFile": False,
        "receiptFilesWritten": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "eaRequestReaderAllowed": False,
        "eaRequestReaderEnabled": False,
        "eaRequestFilesRead": False,
        "eaRequestFilesConsumed": False,
        "eaOrderSendAllowed": False,
        "writesMt5OrderRequest": False,
    }


def _duplicate_request_ids(write_plans: list[dict[str, Any]]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in write_plans:
        request_id = str(row.get("requestId") or "")
        if not request_id:
            continue
        if request_id in seen:
            duplicates.add(request_id)
        seen.add(request_id)
    return duplicates


def _rejection_receipt_rules(*, duplicate_request_id_observed: bool) -> list[dict[str, Any]]:
    scenarios = [
        (
            "schema_validation_failed",
            "SCHEMA_VALIDATION_FAILED",
            "request JSON schema、validator hash 或稳定序列化校验失败。",
            "schema/contract/hash mismatch",
            True,
        ),
        (
            "duplicate_request_id",
            "DUPLICATE_REQUEST_ID",
            "同一个 requestId 已经处理过或计划中重复出现。",
            "idempotency cache hit or duplicate planned requestId",
            duplicate_request_id_observed,
        ),
        (
            "expired_or_stale_request",
            "EXPIRED_OR_STALE_REQUEST",
            "request 超过最大可接受年龄，或 runtime/preflight hash 已过期。",
            "request age or runtime hash stale",
            True,
        ),
        (
            "reader_disabled_review_only",
            "READER_DISABLED_REVIEW_ONLY",
            "EA request reader 仍处于默认关闭/review-only 状态。",
            "reader effectiveEnabled=false",
            True,
        ),
        (
            "reader_release_token_missing",
            EA_REQUEST_READER_RELEASE_BLOCKER,
            "EA request reader 缺少单独审查 release token。",
            "runtime releaseGate.tokenProvided=false",
            True,
        ),
        (
            "kill_switch_active",
            "KILL_SWITCH_ACTIVE",
            "kill switch、daily loss、spread/slippage 或交易权限 fuse 阻断。",
            "risk fuse or kill switch active",
            True,
        ),
    ]
    return [
        {
            "id": row_id,
            "rejectedReasonCode": reason_code,
            "reasonZh": reason_zh,
            "futureDetectionSource": detection_source,
            "coveredByPlan": True,
            "observedInCurrentPlan": bool(observed),
            "receiptAction": "WRITE_REJECTED_RECEIPT_AFTER_FUTURE_REVIEWED_READER_ONLY",
            "wouldReadRequestFile": False,
            "wouldWriteReceiptFile": False,
            "receiptFilesWritten": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "brokerCallsMade": False,
            "eaRequestReaderEnabled": False,
            "eaRequestFilesRead": False,
            "eaRequestFilesConsumed": False,
            "eaOrderSendAllowed": False,
        }
        for row_id, reason_code, reason_zh, detection_source, observed in scenarios
    ]


def _rejection_receipt_plan(
    consumption_plan: dict[str, Any],
    *,
    duplicate_request_id_observed: bool,
) -> dict[str, Any]:
    rules = _rejection_receipt_rules(duplicate_request_id_observed=duplicate_request_id_observed)
    request_id = str(consumption_plan.get("requestId") or "")
    receipt_path = str(consumption_plan.get("receiptPath") or "")
    receipt_preview = {
        "schema": "quantgod.mt5_execution_receipt.v1",
        "requestId": request_id,
        "adapterMode": "REVIEW_ONLY",
        "acceptedByAdapter": False,
        "ticket": "",
        "rejectedReasonCode": "READER_DISABLED_REVIEW_ONLY",
        "receiptPath": receipt_path,
        "brokerSymbol": "",
        "side": "",
        "volumeLots": 0,
        "safetySnapshotHash": "",
        "wouldReadRequestFile": False,
        "wouldWriteReceiptFile": False,
        "receiptFilesWritten": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerCallsMade": False,
        "eaRequestReaderEnabled": False,
        "eaRequestFilesRead": False,
        "eaRequestFilesConsumed": False,
        "eaOrderSendAllowed": False,
    }
    reason_codes = {str(row.get("rejectedReasonCode") or "") for row in rules}
    required_reason_codes = {
        "SCHEMA_VALIDATION_FAILED",
        "DUPLICATE_REQUEST_ID",
        "EXPIRED_OR_STALE_REQUEST",
        "READER_DISABLED_REVIEW_ONLY",
        EA_REQUEST_READER_RELEASE_BLOCKER,
        "KILL_SWITCH_ACTIVE",
    }
    complete = bool(
        request_id
        and receipt_path
        and required_reason_codes.issubset(reason_codes)
        and all(
            row.get("coveredByPlan") is True
            and row.get("wouldReadRequestFile") is False
            and row.get("wouldWriteReceiptFile") is False
            and row.get("receiptFilesWritten") is False
            and row.get("orderSendAllowed") is False
            and row.get("brokerCallsMade") is False
            and row.get("eaRequestReaderEnabled") is False
            for row in rules
        )
    )
    return {
        "mode": "REJECTION_RECEIPT_PLAN_REVIEW_ONLY_NO_FILE_WRITES",
        "complete": complete,
        "requestId": request_id,
        "receiptPath": receipt_path,
        "plannedReceiptSchema": "quantgod.mt5_execution_receipt.v1",
        "duplicateRequestIdObserved": duplicate_request_id_observed,
        "receiptRequiredForEveryRejectedRequest": True,
        "acceptedReceiptRequiresFutureBrokerTicket": True,
        "reviewOnlyReceiptMustNotContainTicket": True,
        "rules": rules,
        "receiptPreview": receipt_preview,
        "wouldReadRequestFile": False,
        "wouldWriteReceiptFile": False,
        "receiptFilesWritten": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerCallsMade": False,
        "eaRequestReaderEnabled": False,
        "eaRequestFilesRead": False,
        "eaRequestFilesConsumed": False,
        "eaOrderSendAllowed": False,
    }


def _all_same(values: list[str]) -> bool:
    filtered = [_normalized_dir(value) for value in values if _normalized_dir(value)]
    return bool(filtered) and len(set(filtered)) == 1


def _directories_match(
    *,
    plans: list[dict[str, Any]],
    reader_contract: dict[str, Any],
    runtime_status: dict[str, Any],
    key: str,
) -> bool:
    contract_value = str(reader_contract.get(key) or "")
    runtime_value = str(runtime_status.get(key) or "")
    plan_values = [str(row.get(key) or "") for row in plans]
    values = [contract_value, *plan_values]
    if runtime_value:
        values.append(runtime_value)
    return _all_same(values)


def _checklist(
    *,
    implementation_spec: dict[str, Any],
    adapter_write: dict[str, Any],
    ea_reader: dict[str, Any],
    consumption_plans: list[dict[str, Any]],
    reader_contract: dict[str, Any],
    runtime_status: dict[str, Any],
    release_gate: dict[str, Any],
    duplicate_request_ids: set[str],
) -> list[dict[str, Any]]:
    steps = _step_ids(implementation_spec)
    write_plans = _safe_list(adapter_write.get("writePlans"))
    return [
        {
            "id": "implementation_spec_ready",
            "labelZh": "live execution implementation spec 可评审",
            "passed": bool(implementation_spec.get("readyForLiveExecutionImplementationSpecReview")),
            "value": implementation_spec.get("status", ""),
        },
        {
            "id": "ea_consumption_step_declared",
            "labelZh": "EA request consumption PR 合同已声明",
            "passed": "ea_request_reader_consumption_path" in steps,
        },
        {
            "id": "adapter_write_review_ready",
            "labelZh": "adapter writer 审查已通过",
            "passed": bool(adapter_write.get("readyForLiveExecutionAdapterWriteReview")),
            "value": adapter_write.get("status", ""),
        },
        {
            "id": "ea_request_reader_review_ready",
            "labelZh": "EA request reader 审查已通过",
            "passed": bool(ea_reader.get("readyForEaRequestReaderImplementationReview")),
            "value": ea_reader.get("status", ""),
        },
        {
            "id": "runtime_status_found",
            "labelZh": "EA runtime reader status 已找到",
            "passed": bool(ea_reader.get("runtimeStatusFound")),
            "value": _safe_dict(ea_reader.get("runtimeStatusSource")).get("path", ""),
        },
        {
            "id": "runtime_status_schema_ok",
            "labelZh": "EA runtime reader status schema 正确",
            "passed": bool(ea_reader.get("runtimeStatusSchemaOk")),
        },
        {
            "id": "runtime_effective_disabled",
            "labelZh": "EA reader 运行时仍有效关闭",
            "passed": bool(ea_reader.get("runtimeStatusDisabled")),
            "value": runtime_status.get("effectiveEnabled"),
        },
        {
            "id": "runtime_safety_passed",
            "labelZh": "EA runtime safety 检查通过",
            "passed": bool(ea_reader.get("runtimeStatusSafetyPassed")),
        },
        {
            "id": "write_plans_present",
            "labelZh": "adapter writer 已生成 request 写入计划",
            "passed": bool(write_plans),
            "value": len(write_plans),
        },
        {
            "id": "write_plans_review_only",
            "labelZh": "adapter writer 计划仍不写 request、不调用 broker",
            "passed": bool(write_plans)
            and all(
                isinstance(row, dict)
                and row.get("allowedToWriteLiveRequest") is False
                and row.get("requestFilesWritten") is False
                and row.get("brokerCallsMade") is False
                and row.get("adapterExecutionAllowed") is False
                and row.get("contractValidationPassed") is True
                and row.get("validatorHashMatches") is True
                for row in write_plans
            ),
        },
        {
            "id": "adapter_writer_validator_hashes_current",
            "labelZh": "adapter writer validator hash 与当前 request 一致",
            "passed": _adapter_write_hashes_current(adapter_write),
        },
        {
            "id": "request_directory_matches",
            "labelZh": "requestDirectory 在 adapter writer、EA contract、runtime status 中一致",
            "passed": bool(consumption_plans)
            and _directories_match(
                plans=consumption_plans,
                reader_contract=reader_contract,
                runtime_status=runtime_status,
                key="requestDirectory",
            ),
            "value": {
                "contract": reader_contract.get("requestDirectory", ""),
                "runtime": runtime_status.get("requestDirectory", ""),
                "plans": [row.get("requestDirectory", "") for row in consumption_plans],
            },
        },
        {
            "id": "receipt_directory_matches",
            "labelZh": "receiptDirectory 在 adapter writer、EA contract、runtime status 中一致",
            "passed": bool(consumption_plans)
            and _directories_match(
                plans=consumption_plans,
                reader_contract=reader_contract,
                runtime_status=runtime_status,
                key="receiptDirectory",
            ),
            "value": {
                "contract": reader_contract.get("receiptDirectory", ""),
                "runtime": runtime_status.get("receiptDirectory", ""),
                "plans": [row.get("receiptDirectory", "") for row in consumption_plans],
            },
        },
        {
            "id": "consumption_plans_review_only",
            "labelZh": "EA consumption 计划只做拒绝回执设计，不读文件不写 receipt",
            "passed": bool(consumption_plans)
            and all(
                row.get("defaultAction") == "REJECT_REVIEW_ONLY"
                and row.get("wouldReadRequestFile") is False
                and row.get("wouldConsumeRequestFile") is False
                and row.get("wouldWriteReceiptFile") is False
                and row.get("releaseTokenRequired") is True
                and row.get("releaseTokenProvided") is False
                and row.get("receiptFilesWritten") is False
                and row.get("orderSendAllowed") is False
                and row.get("brokerCallsMade") is False
                and row.get("eaRequestReaderEnabled") is False
                for row in consumption_plans
            ),
        },
        {
            "id": "reader_release_token_missing_by_default",
            "labelZh": "EA reader release token 未提供，当前不能读 request 文件",
            "passed": bool(release_gate.get("tokenRequired")) and not bool(release_gate.get("tokenProvided")),
            "value": release_gate.get("blockerCode"),
        },
        {
            "id": "rejection_receipt_plan_complete",
            "labelZh": "坏 request、重复 request、过期 request 都有 review-only 拒绝 receipt 计划",
            "passed": bool(consumption_plans)
            and all(
                _safe_dict(row.get("rejectionReceiptPlan")).get("complete") is True
                and _safe_dict(row.get("rejectionReceiptPlan")).get("wouldReadRequestFile") is False
                and _safe_dict(row.get("rejectionReceiptPlan")).get("wouldWriteReceiptFile") is False
                and _safe_dict(row.get("rejectionReceiptPlan")).get("receiptFilesWritten") is False
                and _safe_dict(row.get("rejectionReceiptPlan")).get("brokerCallsMade") is False
                for row in consumption_plans
            ),
        },
        {
            "id": "duplicate_request_ids_absent",
            "labelZh": "planned requestId 没有重复",
            "passed": not duplicate_request_ids,
            "value": sorted(duplicate_request_ids),
        },
        {
            "id": "idempotency_and_serialization_present",
            "labelZh": "每个 consumption plan 都有幂等键和稳定序列化证据",
            "passed": bool(consumption_plans)
            and all(
                row.get("idempotencyKey")
                and row.get("atomicWriteRequired") is True
                and row.get("stableSerializationRequired") is True
                for row in consumption_plans
            ),
        },
        {
            "id": "no_execution_side_effects",
            "labelZh": "本 artifact 不读取 request、不写 receipt、不下单",
            "passed": bool(consumption_plans)
            and all(
                row.get("eaRequestFilesRead") is False
                and row.get("eaRequestFilesConsumed") is False
                and row.get("eaOrderSendAllowed") is False
                and row.get("writesMt5OrderRequest") is False
                for row in consumption_plans
            ),
        },
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
            }:
                continue
            key = (code, str(row.get("reasonZh") or ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _blockers(
    *,
    implementation_spec: dict[str, Any],
    adapter_write: dict[str, Any],
    ea_reader: dict[str, Any],
    checklist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not implementation_spec.get("readyForLiveExecutionImplementationSpecReview"):
        blockers.append(_blocker(
            "LIVE_EXECUTION_IMPLEMENTATION_SPEC_NOT_READY",
            "live execution implementation spec 尚未可评审。",
            implementation_spec.get("status", ""),
        ))
    if "ea_request_reader_consumption_path" not in _step_ids(implementation_spec):
        blockers.append(_blocker(
            "EA_REQUEST_CONSUMPTION_STEP_MISSING",
            "implementation spec 尚未声明 ea_request_reader_consumption_path。",
        ))
    if not adapter_write.get("readyForLiveExecutionAdapterWriteReview"):
        blockers.append(_blocker(
            "LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_NOT_READY",
            "adapter writer 审查尚未通过。",
            adapter_write.get("status", ""),
        ))
    if not ea_reader.get("readyForEaRequestReaderImplementationReview"):
        blockers.append(_blocker(
            "EA_REQUEST_READER_REVIEW_NOT_READY",
            "EA request reader 审查尚未通过。",
            ea_reader.get("status", ""),
        ))
    for row in checklist:
        if row.get("passed"):
            continue
        blockers.append(_blocker(
            "EA_REQUEST_CONSUMPTION_CHECK_NOT_PASSED",
            str(row.get("labelZh") or row.get("id") or "EA consumption check 未通过。"),
            row.get("value") or row.get("id"),
        ))
    return blockers[:32]


def build_ea_request_consumption_review(
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
        "write": bool(write or refresh_sources),
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots or [],
    }
    implementation_spec = read_live_execution_implementation_spec(runtime_dir)
    if should_rebuild and not implementation_spec.get("readyForLiveExecutionImplementationSpecReview"):
        implementation_spec = build_live_execution_implementation_spec(runtime_dir, **kwargs)
    adapter_write = read_live_execution_adapter_write_review(runtime_dir)
    if should_rebuild and (
        not adapter_write.get("readyForLiveExecutionAdapterWriteReview")
        or not _adapter_write_hashes_current(adapter_write)
    ):
        adapter_write = build_live_execution_adapter_write_review(runtime_dir, **kwargs)
    ea_reader = read_ea_request_reader_review(runtime_dir)
    if should_rebuild and not ea_reader.get("readyForEaRequestReaderImplementationReview"):
        ea_reader = build_ea_request_reader_review(runtime_dir, **kwargs)
    reader_contract = _reader_contract(ea_reader)
    runtime_status = _runtime_status(ea_reader)
    release_gate = _reader_release_gate(runtime_status)
    write_plans = [row for row in _safe_list(adapter_write.get("writePlans")) if isinstance(row, dict)]
    duplicate_request_ids = _duplicate_request_ids(write_plans)
    consumption_plans = [
        _consumption_plan(row, reader_contract=reader_contract, release_gate=release_gate)
        for row in write_plans
    ]
    for row in consumption_plans:
        row["rejectionReceiptPlan"] = _rejection_receipt_plan(
            row,
            duplicate_request_id_observed=str(row.get("requestId") or "") in duplicate_request_ids,
        )
    checklist = _checklist(
        implementation_spec=implementation_spec,
        adapter_write=adapter_write,
        ea_reader=ea_reader,
        consumption_plans=consumption_plans,
        reader_contract=reader_contract,
        runtime_status=runtime_status,
        release_gate=release_gate,
        duplicate_request_ids=duplicate_request_ids,
    )
    blockers = _blockers(
        implementation_spec=implementation_spec,
        adapter_write=adapter_write,
        ea_reader=ea_reader,
        checklist=checklist,
    )
    data_plane_ea_request_consumption_ready = bool(
        (
            implementation_spec.get("readyForLiveExecutionImplementationSpecReview")
            or implementation_spec.get("dataPlaneImplementationSpecReady")
        )
        and (
            adapter_write.get("readyForLiveExecutionAdapterWriteReview")
            or adapter_write.get("dataPlaneAdapterWriteReady")
        )
        and (
            ea_reader.get("readyForEaRequestReaderImplementationReview")
            or ea_reader.get("dataPlaneEaRequestReaderReady")
        )
        and "ea_request_reader_consumption_path" in _step_ids(implementation_spec)
        and ea_reader.get("runtimeStatusFound")
        and ea_reader.get("runtimeStatusSchemaOk")
        and ea_reader.get("runtimeStatusDisabled")
        and ea_reader.get("runtimeStatusSafetyPassed")
        and consumption_plans
        and _directories_match(
            plans=consumption_plans,
            reader_contract=reader_contract,
            runtime_status=runtime_status,
            key="requestDirectory",
        )
        and _directories_match(
            plans=consumption_plans,
            reader_contract=reader_contract,
            runtime_status=runtime_status,
            key="receiptDirectory",
        )
        and all(
            row.get("defaultAction") == "REJECT_REVIEW_ONLY"
            and row.get("contractValidationPassed") is True
            and row.get("adapterWriterValidatorHashMatches") is True
            and row.get("releaseTokenRequired") is True
            and row.get("releaseTokenProvided") is False
            and row.get("atomicWriteRequired") is True
            and row.get("stableSerializationRequired") is True
            and row.get("idempotencyKey")
            and _safe_dict(row.get("rejectionReceiptPlan")).get("complete") is True
            and _safe_dict(row.get("rejectionReceiptPlan")).get("receiptFilesWritten") is False
            and _safe_dict(row.get("rejectionReceiptPlan")).get("brokerCallsMade") is False
            and row.get("wouldReadRequestFile") is False
            and row.get("wouldConsumeRequestFile") is False
            and row.get("wouldWriteReceiptFile") is False
            and row.get("receiptFilesWritten") is False
            and row.get("orderSendAllowed") is False
            and row.get("brokerCallsMade") is False
            and row.get("eaRequestReaderEnabled") is False
            and row.get("eaRequestFilesRead") is False
            and row.get("eaRequestFilesConsumed") is False
            and row.get("eaOrderSendAllowed") is False
            and row.get("writesMt5OrderRequest") is False
            for row in consumption_plans
        )
        and not duplicate_request_ids
    )
    execution_mode_only_blocked = bool(
        implementation_spec.get("executionModeOnlyBlocked")
        or adapter_write.get("executionModeOnlyBlocked")
        or ea_reader.get("executionModeOnlyBlocked")
    )
    if data_plane_ea_request_consumption_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "EA request consumption 数据面、目录合同、幂等和 review-only 消费计划已具备；仅等待执行模式闸门。",
                implementation_spec.get("status") or adapter_write.get("status") or ea_reader.get("status"),
            )
        ]
        blockers.extend(_execution_mode_blockers(implementation_spec, adapter_write, ea_reader))
    ready = bool(checklist and all(row.get("passed") for row in checklist) and not blockers)
    payload = {
        "ok": True,
        "schema": EA_REQUEST_CONSUMPTION_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_EA_REQUEST_CONSUMPTION_REVIEW"
            if ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_ea_request_consumption_ready and execution_mode_only_blocked
            else "WAITING_EA_REQUEST_CONSUMPTION_INPUTS"
        ),
        "statusZh": (
            "可进入 EA request consumption 代码评审"
            if ready
            else "EA request consumption 数据面已通过，等待执行模式闸门"
            if data_plane_ea_request_consumption_ready and execution_mode_only_blocked
            else "等待 EA request consumption 输入"
        ),
        "reviewMode": "EA_REQUEST_CONSUMPTION_REVIEW_ONLY_NO_FILE_READS",
        "readyForEaRequestConsumptionReview": ready,
        "dataPlaneEaRequestConsumptionReady": data_plane_ea_request_consumption_ready,
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
        "adapterWriteReviewStatus": adapter_write.get("status", ""),
        "eaRequestReaderReviewStatus": ea_reader.get("status", ""),
        "implementationSpecStatus": implementation_spec.get("status", ""),
        "requestDirectoryContract": reader_contract.get("requestDirectory", ""),
        "receiptDirectoryContract": reader_contract.get("receiptDirectory", ""),
        "requestDirectoryRuntime": runtime_status.get("requestDirectory", ""),
        "receiptDirectoryRuntime": runtime_status.get("receiptDirectory", ""),
        "readerReleaseGate": release_gate,
        "releaseTokenRequired": bool(release_gate.get("tokenRequired", True)),
        "releaseTokenProvided": bool(release_gate.get("tokenProvided")),
        "releaseTokenBlockerCode": str(release_gate.get("blockerCode") or EA_REQUEST_READER_RELEASE_BLOCKER),
        "consumptionPlanCount": len(consumption_plans),
        "duplicateRequestIds": sorted(duplicate_request_ids),
        "rejectionReceiptPlanMode": "REJECTION_RECEIPT_PLAN_REVIEW_ONLY_NO_FILE_WRITES",
        "consumptionPlans": consumption_plans,
        "eaRequestConsumptionChecklist": checklist,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "EA request consumption 合同已可单独代码评审；下一步仍必须保持 reader 默认关闭，并单独实现拒绝 receipt 测试。"
            if ready
            else "EA request consumption 数据面、目录合同和拒绝消费计划已具备；仅剩执行模式闸门，当前仍不会读取 request、写 receipt 或调用 broker。"
            if data_plane_ea_request_consumption_ready and execution_mode_only_blocked
            else "先让 implementation spec、adapter writer review、EA request reader review 和 runtime disabled status 全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = ea_request_consumption_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_ea_request_consumption_review(runtime_dir: Path) -> dict[str, Any]:
    path = ea_request_consumption_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_ea_request_consumption_review(Path(runtime_dir), write=False)
