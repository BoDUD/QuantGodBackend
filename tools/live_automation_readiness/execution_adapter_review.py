from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .pipeline import build_sim_to_live_automation_pipeline, read_sim_to_live_automation_pipeline
from .schema import (
    EXECUTION_ADAPTER_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    execution_adapter_review_path,
    utc_now_iso,
)


REQUIRED_REQUEST_FIELDS = {
    "requestId",
    "schema",
    "reviewPacketHash",
    "runtimePreflightHash",
    "operatorApprovalId",
    "lane",
    "brokerSymbol",
    "canonicalSymbol",
    "side",
    "orderType",
    "volumeLots",
    "maxSlippagePoints",
    "maxSpreadPoints",
    "killSwitchOk",
    "runtimeFresh",
    "spreadProbeOk",
    "symbolMappingOk",
    "dryRunReplayPassed",
}
REQUIRED_RECEIPT_FIELDS = {
    "requestId",
    "schema",
    "receivedAtIso",
    "adapterMode",
    "acceptedByAdapter",
    "rejectedReasonCode",
    "brokerSymbol",
    "side",
    "volumeLots",
    "safetySnapshotHash",
}
REQUIRED_FUSES = {
    "runtime_preflight_passed",
    "operator_approval_hash_current",
    "kill_switch_inactive",
    "dashboard_snapshot_fresh",
    "symbol_mapping_probe_passed",
    "spread_probe_passed",
    "daily_loss_probe_passed",
    "separate_execution_adapter_code_review",
}


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def _names(rows: list[Any]) -> set[str]:
    names: set[str] = set()
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            names.add(str(row.get("name")))
    return names


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _review_receipts(contract: dict[str, Any], safety_hash: str) -> list[dict[str, Any]]:
    rows = []
    for lane in _safe_list(contract.get("laneContracts")):
        if not isinstance(lane, dict):
            continue
        request_id = f"review-only-{lane.get('intentId') or lane.get('lane') or 'intent'}"
        rows.append({
            "requestId": request_id,
            "schema": "quantgod.mt5_execution_receipt.v1",
            "receivedAtIso": utc_now_iso(),
            "adapterMode": "REVIEW_ONLY",
            "acceptedByAdapter": False,
            "rejectedReasonCode": "REVIEW_ONLY_ADAPTER_NO_SIDE_EFFECTS",
            "brokerSymbol": lane.get("brokerSymbol", ""),
            "side": "REVIEW_ONLY",
            "volumeLots": 0.0,
            "safetySnapshotHash": safety_hash,
            "ticket": None,
        })
    return rows


def _contract_blockers(contract: dict[str, Any]) -> list[dict[str, Any]]:
    request_contract = _safe_dict(contract.get("requestContract"))
    request_fields = _names(_safe_list(request_contract.get("allowedRequestFields")))
    receipt_fields = _names(_safe_list(request_contract.get("receiptFields")))
    fuses = {str(item) for item in _safe_list(request_contract.get("requiredRuntimeFuses"))}
    blockers = []
    missing_request = sorted(REQUIRED_REQUEST_FIELDS - request_fields)
    missing_receipt = sorted(REQUIRED_RECEIPT_FIELDS - receipt_fields)
    missing_fuses = sorted(REQUIRED_FUSES - fuses)
    if missing_request:
        blockers.append(_blocker("ADAPTER_REQUEST_FIELDS_INCOMPLETE", "MT5 request contract 缺少 adapter 必须验证的字段。", missing_request))
    if missing_receipt:
        blockers.append(_blocker("ADAPTER_RECEIPT_FIELDS_INCOMPLETE", "MT5 receipt contract 缺少 adapter 必须输出的字段。", missing_receipt))
    if missing_fuses:
        blockers.append(_blocker("ADAPTER_RUNTIME_FUSES_INCOMPLETE", "MT5 request contract 缺少必需运行时 fuse。", missing_fuses))
    if not bool(request_contract.get("contractOnly")):
        blockers.append(_blocker("ADAPTER_CONTRACT_NOT_MARKED_CONTRACT_ONLY", "MT5 request contract 必须保持 contractOnly=true。"))
    if bool(request_contract.get("requestFilesProducedByThisTool")):
        blockers.append(_blocker("ADAPTER_CONTRACT_PRODUCES_REQUEST_FILES", "当前工具不能生成 MT5 请求文件。"))
    return blockers


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


def build_execution_adapter_review(
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
    should_rebuild = bool(
        refresh_sources
        or operator_approval_json
        or moss_backtest_json
        or hfm_simulation_profile_json
        or hfm_contract_spec_json
        or extra_bases_roots
    )
    kwargs = {
        "operator_approval_json": operator_approval_json,
        "write": bool(write and refresh_sources),
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots or [],
    }
    pipeline = build_sim_to_live_automation_pipeline(runtime_dir, **kwargs) if should_rebuild else read_sim_to_live_automation_pipeline(runtime_dir)
    contract = build_mt5_order_request_contract(runtime_dir, **kwargs) if should_rebuild else read_mt5_order_request_contract(runtime_dir)
    blockers: list[dict[str, Any]] = []
    if not bool(pipeline.get("readyForSeparateExecutionAdapterReview")):
        blockers.append(_blocker("SIM_TO_LIVE_PIPELINE_NOT_READY", "sim-to-live 流水线尚未到达 adapter 评审边界。", pipeline.get("status")))
        blockers.extend(item for item in _safe_list(pipeline.get("blockers")) if isinstance(item, dict))
    if not bool(contract.get("readyForAdapterCodeReview")):
        blockers.append(_blocker("ORDER_REQUEST_CONTRACT_NOT_READY", "MT5 request contract 尚未可进入 adapter 代码评审。", contract.get("status")))
        blockers.extend(item for item in _safe_list(contract.get("blockers")) if isinstance(item, dict))
    contract_blockers = _contract_blockers(contract)
    blockers.extend(contract_blockers)
    safety_hash = _digest({
        "pipelineStatus": pipeline.get("status"),
        "contractStatus": contract.get("status"),
        "reviewPacketHash": contract.get("reviewPacketHash"),
        "runtimePreflightHash": contract.get("runtimePreflightHash"),
    })
    data_plane_adapter_review_ready = bool(
        (
            pipeline.get("readyForSeparateExecutionAdapterReview")
            or pipeline.get("dataPlanePipelineReady")
        )
        and contract.get("runtimePreflightDataPlaneReadyForReview")
        and not contract_blockers
    )
    execution_mode_only_blocked = bool(
        pipeline.get("executionModeOnlyBlocked")
        or contract.get("runtimePreflightExecutionModeOnlyBlocked")
    )
    if data_plane_adapter_review_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "execution adapter review 数据面、pipeline 和 request contract 已具备；仅等待执行模式闸门。",
                pipeline.get("status") or contract.get("status"),
            )
        ]
        blockers.extend(_execution_mode_blockers(pipeline, contract))
    review_ready = bool(
        pipeline.get("readyForSeparateExecutionAdapterReview")
        and contract.get("readyForAdapterCodeReview")
        and not blockers
    )
    payload = {
        "ok": True,
        "schema": EXECUTION_ADAPTER_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_EXECUTION_ADAPTER_CODE_REVIEW"
            if review_ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_adapter_review_ready and execution_mode_only_blocked
            else "WAITING_EXECUTION_ADAPTER_REVIEW_INPUTS"
        ),
        "statusZh": (
            "可进入 execution adapter 代码评审"
            if review_ready
            else "execution adapter review 数据面已通过，等待执行模式闸门"
            if data_plane_adapter_review_ready and execution_mode_only_blocked
            else "等待 adapter 评审输入"
        ),
        "readyForExecutionAdapterCodeReview": review_ready,
        "dataPlaneAdapterReviewReady": data_plane_adapter_review_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "executionReady": False,
        "adapterExecutionAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "reviewMode": "REVIEW_ONLY",
        "reviewPacketHash": contract.get("reviewPacketHash", ""),
        "runtimePreflightHash": contract.get("runtimePreflightHash", ""),
        "pipelineAutoStage": pipeline.get("autoStage", ""),
        "adapterReviewContract": {
            "adapterName": "MT5_EXECUTION_ADAPTER_FUTURE_REVIEW_ONLY",
            "inputSchema": "quantgod.mt5_reviewed_order_request.v1",
            "receiptSchema": "quantgod.mt5_execution_receipt.v1",
            "requestValidationRequired": True,
            "receiptEmissionRequired": True,
            "idempotencyRequired": True,
            "sideEffectsAllowedInThisReview": False,
            "requestFilesProducedByThisTool": False,
            "brokerCallsAllowedInThisReview": False,
            "credentialStorageAllowed": False,
        },
        "reviewOnlySampleReceipts": _review_receipts(contract, safety_hash),
        "blockers": blockers,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerExecutionAllowed": False,
        "nextRequiredActionZh": (
            "进入单独 adapter 实现评审；评审壳本身仍不写请求、不连接 broker。"
            if review_ready
            else "execution adapter review 数据面、pipeline 和 request contract 已具备；仅剩执行模式闸门，当前仍不会写 request 或调用 broker。"
            if data_plane_adapter_review_ready and execution_mode_only_blocked
            else "先让 sim-to-live pipeline 和 MT5 request contract 全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = execution_adapter_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_execution_adapter_review(runtime_dir: Path) -> dict[str, Any]:
    path = execution_adapter_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_execution_adapter_review(Path(runtime_dir), write=False)
