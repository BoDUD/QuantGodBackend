from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ea_request_consumption import (
    build_ea_request_consumption_review,
    read_existing_ea_request_consumption_review,
    read_ea_request_consumption_review,
)
from .live_execution_adapter import (
    build_live_execution_adapter_write_review,
    read_existing_live_execution_adapter_write_review,
    read_live_execution_adapter_write_review,
)
from .live_execution_implementation_spec import (
    build_live_execution_implementation_spec,
    build_live_execution_implementation_spec_cutover_proxy,
    read_existing_live_execution_implementation_spec,
    read_live_execution_implementation_spec,
)
from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
from .schema import (
    BROKER_ORDER_SEND_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    broker_order_send_review_path,
    utc_now_iso,
)

BROKER_ORDER_SEND_RELEASE_TOKEN_NAME = "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1"
BROKER_ORDER_SEND_RELEASE_BLOCKER = "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING"


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    return row


def _step_ids(implementation_spec: dict[str, Any]) -> set[str]:
    return {
        str(row.get("stepId") or "")
        for row in _safe_list(implementation_spec.get("implementationSteps"))
        if isinstance(row, dict)
    }


def _parse_preview(write_plan: dict[str, Any]) -> dict[str, Any]:
    raw = str(write_plan.get("canonicalJsonPreview") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _by_request_id(rows: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("requestId"):
            result[str(row["requestId"])] = row
    return result


def _lane_runtime_map(preflight: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _safe_list(preflight.get("laneRuntimeChecks")):
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("lane") or ""),
            str(row.get("brokerSymbol") or ""),
            str(row.get("canonicalSymbol") or ""),
        )
        rows[key] = row
    return rows


def _contract_lane_map(order_contract: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _safe_list(order_contract.get("laneContracts")):
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("lane") or ""),
            str(row.get("brokerSymbol") or ""),
            str(row.get("canonicalSymbol") or ""),
        )
        rows[key] = row
    return rows


def _account_summary(preflight: dict[str, Any]) -> dict[str, Any]:
    dashboard = _safe_dict(preflight.get("dashboardSnapshot"))
    account = _safe_dict(dashboard.get("account"))
    return {
        "number": account.get("number"),
        "server": account.get("server", ""),
        "currency": account.get("currency", ""),
        "dashboardFresh": bool(dashboard.get("fresh")),
        "livePilotMode": dashboard.get("livePilotMode"),
        "tradeAllowed": dashboard.get("tradeAllowed"),
        "executionEnabled": dashboard.get("executionEnabled"),
        "readOnlyMode": dashboard.get("readOnlyMode"),
    }


def _broker_release_gate(ea_consumption: dict[str, Any]) -> dict[str, Any]:
    runtime_status = _safe_dict(ea_consumption.get("runtimeStatusReview"))
    broker_wrapper = _safe_dict(runtime_status.get("brokerOrderSendWrapper"))
    release_gate = _safe_dict(broker_wrapper.get("releaseGate"))
    token_required = release_gate.get("tokenRequired")
    token_provided = release_gate.get("tokenProvided")
    return {
        "tokenRequired": True if token_required is None else bool(token_required),
        "tokenProvided": bool(token_provided),
        "tokenName": str(release_gate.get("tokenName") or BROKER_ORDER_SEND_RELEASE_TOKEN_NAME),
        "blockerCode": str(release_gate.get("blockerCode") or BROKER_ORDER_SEND_RELEASE_BLOCKER),
        "reasonZh": (
            release_gate.get("reasonZh")
            or release_gate.get("reason")
            or "没有单独审查 release token 时，broker OrderSend wrapper 不能调用 OrderSend。"
        ),
        "source": "runtimeStatusReview.brokerOrderSendWrapper.releaseGate"
        if release_gate
        else "default_missing_runtime_broker_release_gate",
    }


def _adapter_write_hashes_current(adapter_write: dict[str, Any]) -> bool:
    write_plans = [row for row in _safe_list(adapter_write.get("writePlans")) if isinstance(row, dict)]
    return bool(write_plans) and all(row.get("validatorHashMatches") is True for row in write_plans)


def _ea_consumption_hashes_current(ea_consumption: dict[str, Any]) -> bool:
    plans = [row for row in _safe_list(ea_consumption.get("consumptionPlans")) if isinstance(row, dict)]
    return bool(plans) and all(row.get("adapterWriterValidatorHashMatches") is True for row in plans)


def _broker_send_plan(
    consumption_plan: dict[str, Any],
    *,
    write_plan: dict[str, Any],
    preflight: dict[str, Any],
    order_contract: dict[str, Any],
    release_gate: dict[str, Any],
) -> dict[str, Any]:
    request = _parse_preview(write_plan)
    lane = str(request.get("lane") or write_plan.get("lane") or "")
    broker_symbol = str(request.get("brokerSymbol") or write_plan.get("brokerSymbol") or "")
    canonical_symbol = str(request.get("canonicalSymbol") or write_plan.get("canonicalSymbol") or "")
    runtime_row = _lane_runtime_map(preflight).get((lane, broker_symbol, canonical_symbol), {})
    contract_row = _contract_lane_map(order_contract).get((lane, broker_symbol, canonical_symbol), {})
    account = _account_summary(preflight)
    return {
        "requestId": str(consumption_plan.get("requestId") or write_plan.get("requestId") or ""),
        "lane": lane,
        "brokerSymbol": broker_symbol,
        "canonicalSymbol": canonical_symbol,
        "side": str(request.get("side") or ""),
        "orderType": str(request.get("orderType") or ""),
        "volumeLots": request.get("volumeLots"),
        "slPrice": request.get("slPrice"),
        "tpPrice": request.get("tpPrice"),
        "maxSlippagePoints": request.get("maxSlippagePoints"),
        "maxSpreadPoints": request.get("maxSpreadPoints"),
        "maxDailyLossPct": request.get("maxDailyLossPct"),
        "maxDailyLossR": request.get("maxDailyLossR"),
        "maxConsecutiveLosses": request.get("maxConsecutiveLosses"),
        "requestPath": consumption_plan.get("requestPath", ""),
        "receiptPath": consumption_plan.get("receiptPath", ""),
        "requestDirectory": consumption_plan.get("requestDirectory", ""),
        "receiptDirectory": consumption_plan.get("receiptDirectory", ""),
        "idempotencyKey": consumption_plan.get("idempotencyKey", ""),
        "adapterWriterValidatorHashMatches": consumption_plan.get("adapterWriterValidatorHashMatches") is True,
        "writePlanValidatorHashMatches": write_plan.get("validatorHashMatches") is True,
        "reviewPacketHash": request.get("reviewPacketHash", ""),
        "runtimePreflightHash": request.get("runtimePreflightHash", ""),
        "operatorApprovalId": request.get("operatorApprovalId", ""),
        "accountNumber": account.get("number"),
        "brokerServer": account.get("server", ""),
        "accountCurrency": account.get("currency", ""),
        "dashboardFreshRequired": True,
        "livePilotModeRequired": True,
        "tradeAllowedRequired": True,
        "executionEnabledRequired": True,
        "readOnlyModeOffRequired": True,
        "schemaValidationRequired": True,
        "idempotencyRequired": True,
        "killSwitchRequired": True,
        "runtimeFreshRequired": True,
        "spreadProbeRequired": True,
        "symbolMappingRequired": True,
        "volumeStepValidationRequired": True,
        "positionCapRequired": True,
        "dailyLossValidationRequired": True,
        "slippageValidationRequired": True,
        "receiptRequired": True,
        "receiptMustContainTicketAfterFutureExecution": True,
        "separateWrapperCodeReviewRequired": True,
        "releaseTokenRequired": bool(release_gate.get("tokenRequired", True)),
        "releaseTokenProvided": bool(release_gate.get("tokenProvided")),
        "releaseTokenName": str(release_gate.get("tokenName") or BROKER_ORDER_SEND_RELEASE_TOKEN_NAME),
        "releaseTokenBlockerCode": str(release_gate.get("blockerCode") or BROKER_ORDER_SEND_RELEASE_BLOCKER),
        "sourcePathLockedToEaConsumption": bool(consumption_plan.get("defaultAction") == "REJECT_REVIEW_ONLY"),
        "runtimeProbePassed": bool(preflight.get("runtimeProbePassed")),
        "orderContractReady": bool(order_contract.get("readyForAdapterCodeReview")),
        "laneRuntimePassed": bool(runtime_row.get("passed")),
        "laneContractMatch": bool(contract_row),
        "requestFusesOk": all(
            request.get(key) is True
            for key in ("killSwitchOk", "runtimeFresh", "spreadProbeOk", "symbolMappingOk", "dryRunReplayPassed")
        ),
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
    }


def _checklist(
    *,
    implementation_spec: dict[str, Any],
    ea_consumption: dict[str, Any],
    preflight: dict[str, Any],
    order_contract: dict[str, Any],
    adapter_write: dict[str, Any],
    broker_send_plans: list[dict[str, Any]],
    release_gate: dict[str, Any],
) -> list[dict[str, Any]]:
    steps = _step_ids(implementation_spec)
    return [
        {
            "id": "implementation_spec_ready",
            "labelZh": "live execution implementation spec 可评审",
            "passed": bool(implementation_spec.get("readyForLiveExecutionImplementationSpecReview")),
            "value": implementation_spec.get("status", ""),
        },
        {
            "id": "broker_order_send_step_declared",
            "labelZh": "broker_order_send_path PR 合同已声明",
            "passed": "broker_order_send_path" in steps,
        },
        {
            "id": "ea_consumption_review_ready",
            "labelZh": "EA request consumption 审查已通过",
            "passed": bool(ea_consumption.get("readyForEaRequestConsumptionReview")),
            "value": ea_consumption.get("status", ""),
        },
        {
            "id": "runtime_preflight_ready",
            "labelZh": "运行时预检已通过",
            "passed": bool(preflight.get("runtimeProbePassed")),
            "value": preflight.get("status", ""),
        },
        {
            "id": "order_request_contract_ready",
            "labelZh": "MT5 request contract 已通过",
            "passed": bool(order_contract.get("readyForAdapterCodeReview")),
            "value": order_contract.get("status", ""),
        },
        {
            "id": "adapter_write_review_ready",
            "labelZh": "adapter writer 计划可审查",
            "passed": bool(adapter_write.get("readyForLiveExecutionAdapterWriteReview")),
            "value": adapter_write.get("status", ""),
        },
        {
            "id": "adapter_writer_validator_hashes_current",
            "labelZh": "adapter writer validator hash 与当前 request 一致",
            "passed": _adapter_write_hashes_current(adapter_write),
        },
        {
            "id": "ea_consumption_adapter_hashes_current",
            "labelZh": "EA consumption 继承的 adapter hash 证明当前一致",
            "passed": _ea_consumption_hashes_current(ea_consumption),
        },
        {
            "id": "broker_send_plans_present",
            "labelZh": "broker send wrapper 合同计划已生成",
            "passed": bool(broker_send_plans),
            "value": len(broker_send_plans),
        },
        {
            "id": "runtime_account_bound",
            "labelZh": "broker account/server 已绑定到 fresh dashboard",
            "passed": bool(broker_send_plans)
            and all(row.get("accountNumber") and row.get("brokerServer") for row in broker_send_plans),
        },
        {
            "id": "request_fuses_bound",
            "labelZh": "每个 request 都绑定 kill switch、runtime、spread、symbol、dry-run fuse",
            "passed": bool(broker_send_plans)
            and all(row.get("requestFusesOk") is True for row in broker_send_plans),
        },
        {
            "id": "lane_runtime_and_contract_bound",
            "labelZh": "每个 request 都匹配 runtime symbol 和 request contract",
            "passed": bool(broker_send_plans)
            and all(row.get("laneRuntimePassed") is True and row.get("laneContractMatch") is True for row in broker_send_plans),
        },
        {
            "id": "risk_controls_required",
            "labelZh": "lot、position、daily loss、spread/slippage、receipt 控制均为强制项",
            "passed": bool(broker_send_plans)
            and all(
                row.get("volumeStepValidationRequired") is True
                and row.get("positionCapRequired") is True
                and row.get("dailyLossValidationRequired") is True
                and row.get("spreadProbeRequired") is True
                and row.get("slippageValidationRequired") is True
                and row.get("receiptRequired") is True
                for row in broker_send_plans
            ),
        },
        {
            "id": "broker_order_send_release_token_missing_by_default",
            "labelZh": "Broker OrderSend release token 未提供，当前不能调用 OrderSend",
            "passed": bool(release_gate.get("tokenRequired")) and not bool(release_gate.get("tokenProvided")),
            "value": release_gate.get("blockerCode") or BROKER_ORDER_SEND_RELEASE_BLOCKER,
        },
        {
            "id": "source_path_locked_to_ea_consumption",
            "labelZh": "broker wrapper 只能从已验收 EA consumption 路径进入",
            "passed": bool(broker_send_plans)
            and all(
                row.get("sourcePathLockedToEaConsumption") is True
                and row.get("adapterWriterValidatorHashMatches") is True
                and row.get("writePlanValidatorHashMatches") is True
                and row.get("releaseTokenRequired") is True
                and row.get("releaseTokenProvided") is False
                for row in broker_send_plans
            ),
        },
        {
            "id": "no_broker_side_effects",
            "labelZh": "本 artifact 不调用 broker、不写 request/receipt、不打开下单权限",
            "passed": bool(broker_send_plans)
            and all(
                row.get("wouldCallBroker") is False
                and row.get("brokerCallsMade") is False
                and row.get("orderSendAllowed") is False
                and row.get("mt5OrderSendAllowed") is False
                and row.get("requestFilesWritten") is False
                and row.get("receiptFilesWritten") is False
                for row in broker_send_plans
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
    ea_consumption: dict[str, Any],
    preflight: dict[str, Any],
    order_contract: dict[str, Any],
    adapter_write: dict[str, Any],
    checklist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not implementation_spec.get("readyForLiveExecutionImplementationSpecReview"):
        blockers.append(_blocker(
            "LIVE_EXECUTION_IMPLEMENTATION_SPEC_NOT_READY",
            "live execution implementation spec 尚未可评审。",
            implementation_spec.get("status", ""),
        ))
    if "broker_order_send_path" not in _step_ids(implementation_spec):
        blockers.append(_blocker("BROKER_ORDER_SEND_STEP_MISSING", "implementation spec 尚未声明 broker_order_send_path。"))
    if not ea_consumption.get("readyForEaRequestConsumptionReview"):
        blockers.append(_blocker(
            "EA_REQUEST_CONSUMPTION_REVIEW_NOT_READY",
            "EA request consumption 审查尚未通过。",
            ea_consumption.get("status", ""),
        ))
    if not preflight.get("runtimeProbePassed"):
        blockers.append(_blocker("RUNTIME_PREFLIGHT_NOT_READY", "运行时预检尚未通过。", preflight.get("status", "")))
    if not order_contract.get("readyForAdapterCodeReview"):
        blockers.append(_blocker(
            "ORDER_REQUEST_CONTRACT_NOT_READY",
            "MT5 request contract 尚未通过。",
            order_contract.get("status", ""),
        ))
    if not adapter_write.get("readyForLiveExecutionAdapterWriteReview"):
        blockers.append(_blocker(
            "LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_NOT_READY",
            "adapter writer 审查尚未通过。",
            adapter_write.get("status", ""),
        ))
    for row in checklist:
        if row.get("passed"):
            continue
        blockers.append(_blocker(
            "BROKER_ORDER_SEND_CHECK_NOT_PASSED",
            str(row.get("labelZh") or row.get("id") or "broker order send check 未通过。"),
            row.get("value") or row.get("id"),
        ))
    return blockers[:32]


def build_broker_order_send_review(
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
        "extra_bases_roots": extra_bases_roots or [],
    }
    common = {
        "operator_approval_json": operator_approval_json,
        "write": bool(write and refresh_sources),
        "refresh_sources": refresh_sources,
        "extra_bases_roots": extra_bases_roots or [],
    }
    implementation_spec = (
        read_live_execution_implementation_spec(runtime_dir)
        if _allow_implementation_spec_rebuild
        else read_existing_live_execution_implementation_spec(runtime_dir)
    )
    if should_rebuild and not implementation_spec.get("readyForLiveExecutionImplementationSpecReview"):
        if _allow_implementation_spec_rebuild:
            implementation_spec = build_live_execution_implementation_spec(runtime_dir, **kwargs)
        elif not (
            implementation_spec.get("dataPlaneImplementationSpecReady")
            and "broker_order_send_path" in _step_ids(implementation_spec)
        ):
            implementation_spec = build_live_execution_implementation_spec_cutover_proxy(runtime_dir)
    ea_consumption = (
        read_ea_request_consumption_review(runtime_dir)
        if _allow_implementation_spec_rebuild
        else read_existing_ea_request_consumption_review(runtime_dir)
    )
    if should_rebuild and (
        not ea_consumption.get("readyForEaRequestConsumptionReview")
        or not _ea_consumption_hashes_current(ea_consumption)
    ):
        ea_consumption = build_ea_request_consumption_review(
            runtime_dir,
            **kwargs,
            _allow_implementation_spec_rebuild=_allow_implementation_spec_rebuild,
        )
    preflight = read_live_runtime_preflight_probe(runtime_dir)
    if should_rebuild and not preflight.get("runtimeProbePassed"):
        preflight = build_live_runtime_preflight_probe(runtime_dir, **common)
    order_contract = read_mt5_order_request_contract(runtime_dir)
    if should_rebuild and not order_contract.get("readyForAdapterCodeReview"):
        order_contract = build_mt5_order_request_contract(runtime_dir, **common)
    adapter_write = (
        read_live_execution_adapter_write_review(runtime_dir)
        if _allow_implementation_spec_rebuild
        else read_existing_live_execution_adapter_write_review(runtime_dir)
    )
    if should_rebuild and (
        not adapter_write.get("readyForLiveExecutionAdapterWriteReview")
        or not _adapter_write_hashes_current(adapter_write)
    ):
        adapter_write = build_live_execution_adapter_write_review(
            runtime_dir,
            **kwargs,
            _allow_implementation_spec_rebuild=_allow_implementation_spec_rebuild,
        )
    write_by_id = _by_request_id(_safe_list(adapter_write.get("writePlans")))
    release_gate = _broker_release_gate(ea_consumption)
    broker_send_plans = [
        _broker_send_plan(
            row,
            write_plan=write_by_id.get(str(row.get("requestId") or ""), {}),
            preflight=preflight,
            order_contract=order_contract,
            release_gate=release_gate,
        )
        for row in _safe_list(ea_consumption.get("consumptionPlans"))
        if isinstance(row, dict)
    ]
    checklist = _checklist(
        implementation_spec=implementation_spec,
        ea_consumption=ea_consumption,
        preflight=preflight,
        order_contract=order_contract,
        adapter_write=adapter_write,
        broker_send_plans=broker_send_plans,
        release_gate=release_gate,
    )
    blockers = _blockers(
        implementation_spec=implementation_spec,
        ea_consumption=ea_consumption,
        preflight=preflight,
        order_contract=order_contract,
        adapter_write=adapter_write,
        checklist=checklist,
    )
    broker_send_plans_data_plane_ready = bool(
        broker_send_plans
        and all(
            row.get("accountNumber")
            and row.get("brokerServer")
            and row.get("adapterWriterValidatorHashMatches") is True
            and row.get("writePlanValidatorHashMatches") is True
            and row.get("requestFusesOk") is True
            and row.get("laneRuntimePassed") is True
            and row.get("laneContractMatch") is True
            and row.get("volumeStepValidationRequired") is True
            and row.get("positionCapRequired") is True
            and row.get("dailyLossValidationRequired") is True
            and row.get("spreadProbeRequired") is True
            and row.get("slippageValidationRequired") is True
            and row.get("receiptRequired") is True
            and row.get("releaseTokenRequired") is True
            and row.get("releaseTokenProvided") is False
            and row.get("sourcePathLockedToEaConsumption") is True
            and row.get("defaultAction") == "BLOCK_REVIEW_ONLY_NO_BROKER_CALL"
            and row.get("wouldCallBroker") is False
            and row.get("brokerCallsMade") is False
            and row.get("orderSendAllowed") is False
            and row.get("mt5OrderSendAllowed") is False
            and row.get("requestFilesWritten") is False
            and row.get("receiptFilesWritten") is False
            and row.get("writesMt5OrderRequest") is False
            for row in broker_send_plans
        )
    )
    data_plane_broker_order_send_ready = bool(
        (
            implementation_spec.get("readyForLiveExecutionImplementationSpecReview")
            or implementation_spec.get("dataPlaneImplementationSpecReady")
        )
        and (
            ea_consumption.get("readyForEaRequestConsumptionReview")
            or ea_consumption.get("dataPlaneEaRequestConsumptionReady")
        )
        and (
            preflight.get("runtimeProbePassed")
            or preflight.get("dataPlaneReadyForLivePilotReview")
        )
        and (
            order_contract.get("readyForAdapterCodeReview")
            or order_contract.get("runtimePreflightDataPlaneReadyForReview")
        )
        and (
            adapter_write.get("readyForLiveExecutionAdapterWriteReview")
            or adapter_write.get("dataPlaneAdapterWriteReady")
        )
        and "broker_order_send_path" in _step_ids(implementation_spec)
        and broker_send_plans_data_plane_ready
    )
    execution_mode_only_blocked = bool(
        implementation_spec.get("executionModeOnlyBlocked")
        or ea_consumption.get("executionModeOnlyBlocked")
        or preflight.get("executionModeOnlyBlocked")
        or order_contract.get("runtimePreflightExecutionModeOnlyBlocked")
        or adapter_write.get("executionModeOnlyBlocked")
        or bool(release_gate.get("tokenRequired", True) and not release_gate.get("tokenProvided"))
    )
    if data_plane_broker_order_send_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "broker order send 数据面、request fuse、风险控制和 no-broker-call 计划已具备；仅等待执行模式闸门。",
                preflight.get("status") or order_contract.get("status"),
            )
        ]
        if release_gate.get("tokenRequired") and not release_gate.get("tokenProvided"):
            blockers.append(_blocker(
                str(release_gate.get("blockerCode") or BROKER_ORDER_SEND_RELEASE_BLOCKER),
                str(release_gate.get("reasonZh") or "Broker OrderSend release token 未提供，当前不能调用 OrderSend。"),
                release_gate.get("source", ""),
            ))
        blockers.extend(_execution_mode_blockers(
            implementation_spec,
            ea_consumption,
            preflight,
            order_contract,
            adapter_write,
        ))
    ready = bool(checklist and all(row.get("passed") for row in checklist) and not blockers)
    payload = {
        "ok": True,
        "schema": BROKER_ORDER_SEND_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_BROKER_ORDER_SEND_REVIEW"
            if ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_broker_order_send_ready and execution_mode_only_blocked
            else "WAITING_BROKER_ORDER_SEND_INPUTS"
        ),
        "statusZh": (
            "可进入 broker order send wrapper 代码评审"
            if ready
            else "broker order send 数据面已通过，等待执行模式闸门"
            if data_plane_broker_order_send_ready and execution_mode_only_blocked
            else "等待 broker order send 输入"
        ),
        "reviewMode": "BROKER_ORDER_SEND_REVIEW_ONLY_NO_BROKER_CALLS",
        "readyForBrokerOrderSendReview": ready,
        "dataPlaneBrokerOrderSendReady": data_plane_broker_order_send_ready,
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
        "implementationSpecStatus": implementation_spec.get("status", ""),
        "eaRequestConsumptionStatus": ea_consumption.get("status", ""),
        "runtimePreflightStatus": preflight.get("status", ""),
        "orderRequestContractStatus": order_contract.get("status", ""),
        "adapterWriteReviewStatus": adapter_write.get("status", ""),
        "brokerSendPlanCount": len(broker_send_plans),
        "brokerReleaseGate": release_gate,
        "releaseTokenRequired": bool(release_gate.get("tokenRequired", True)),
        "releaseTokenProvided": bool(release_gate.get("tokenProvided")),
        "releaseTokenBlockerCode": str(release_gate.get("blockerCode") or BROKER_ORDER_SEND_RELEASE_BLOCKER),
        "brokerSendPlans": broker_send_plans,
        "brokerOrderSendChecklist": checklist,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "broker send wrapper 合同已可单独代码评审；下一步仍必须保持无 broker 调用，并先补 receipt writer/rollback 审查。"
            if ready
            else "broker order send wrapper 数据面、fuse 和风险控制计划已具备；仅剩执行模式闸门，当前仍不会调用 broker 或写 request/receipt。"
            if data_plane_broker_order_send_ready and execution_mode_only_blocked
            else "先让 implementation spec、EA consumption、runtime preflight、request contract 和 adapter writer 全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = broker_order_send_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_broker_order_send_review(runtime_dir: Path) -> dict[str, Any]:
    path = broker_order_send_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_broker_order_send_review(Path(runtime_dir), write=False)
