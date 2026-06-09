from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .approval_context import operator_approval_json_for_refresh
from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
from .schema import (
    ORDER_REQUEST_CONTRACT_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    order_request_contract_path,
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


def _stable_digest(payload: Any) -> str:
    volatile_keys = {
        "generatedAt",
        "generatedAtIso",
        "ageSeconds",
        "mtimeIso",
        "tickAgeSeconds",
        "runtimeProbeAgeSeconds",
    }

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: normalize(val)
                for key, val in sorted(value.items())
                if key not in volatile_keys
            }
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    raw = json.dumps(normalize(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _request_fields() -> list[dict[str, Any]]:
    return [
        {"name": "requestId", "required": True, "type": "string", "source": "adapter_generated_idempotency_key"},
        {"name": "schema", "required": True, "type": "string", "constant": "quantgod.mt5_reviewed_order_request.v1"},
        {"name": "createdAtIso", "required": True, "type": "string", "source": "adapter_clock_utc"},
        {"name": "reviewPacketHash", "required": True, "type": "string", "source": "runtime_preflight"},
        {"name": "runtimePreflightHash", "required": True, "type": "string", "source": "runtime_preflight"},
        {"name": "operatorApprovalId", "required": True, "type": "string", "source": "approval_evidence"},
        {"name": "lane", "required": True, "type": "enum", "allowed": ["USDJPY_MT5", "HFM_CRYPTO_CFD"]},
        {"name": "brokerSymbol", "required": True, "type": "string", "source": "approved_lane_contract"},
        {"name": "canonicalSymbol", "required": True, "type": "string", "source": "approved_lane_contract"},
        {"name": "side", "required": True, "type": "enum", "allowed": ["BUY", "SELL", "CLOSE_ONLY"]},
        {"name": "orderType", "required": True, "type": "enum", "allowed": ["MARKET", "LIMIT", "STOP", "CLOSE_ONLY"]},
        {"name": "volumeLots", "required": True, "type": "number", "minimum": 0},
        {"name": "slPrice", "required": False, "type": "number_or_null"},
        {"name": "tpPrice", "required": False, "type": "number_or_null"},
        {"name": "maxSlippagePoints", "required": True, "type": "number", "minimum": 0},
        {"name": "maxSpreadPoints", "required": True, "type": "number", "minimum": 0},
        {"name": "maxDailyLossPct", "required": True, "type": "number", "minimum": 0},
        {"name": "maxDailyLossR", "required": True, "type": "number", "minimum": 0},
        {"name": "maxConsecutiveLosses", "required": True, "type": "integer", "minimum": 0},
        {"name": "killSwitchOk", "required": True, "type": "boolean", "mustEqual": True},
        {"name": "runtimeFresh", "required": True, "type": "boolean", "mustEqual": True},
        {"name": "spreadProbeOk", "required": True, "type": "boolean", "mustEqual": True},
        {"name": "symbolMappingOk", "required": True, "type": "boolean", "mustEqual": True},
        {"name": "dryRunReplayPassed", "required": True, "type": "boolean", "mustEqual": True},
    ]


def _receipt_fields() -> list[dict[str, Any]]:
    return [
        {"name": "requestId", "required": True, "type": "string"},
        {"name": "schema", "required": True, "type": "string", "constant": "quantgod.mt5_execution_receipt.v1"},
        {"name": "receivedAtIso", "required": True, "type": "string"},
        {"name": "adapterMode", "required": True, "type": "enum", "allowed": ["REVIEW_ONLY", "DRY_RUN", "LIVE_REVIEWED"]},
        {"name": "acceptedByAdapter", "required": True, "type": "boolean"},
        {"name": "rejectedReasonCode", "required": False, "type": "string"},
        {"name": "brokerSymbol", "required": True, "type": "string"},
        {"name": "side", "required": True, "type": "string"},
        {"name": "volumeLots", "required": True, "type": "number"},
        {"name": "safetySnapshotHash", "required": True, "type": "string"},
        {"name": "ticket", "required": False, "type": "string_or_null", "allowedBeforeLiveReview": False},
    ]


def _lane_contract_rows(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _safe_list(preflight.get("laneRuntimeChecks")):
        if not isinstance(item, dict):
            continue
        rows.append({
            "intentId": item.get("intentId", ""),
            "lane": item.get("lane", ""),
            "brokerSymbol": item.get("brokerSymbol", ""),
            "canonicalSymbol": item.get("canonicalSymbol", ""),
            "symbolPresentInSnapshot": bool(item.get("symbolPresentInSnapshot")),
            "symbolPresentInSidecarSpecs": bool(item.get("symbolPresentInSidecarSpecs")),
            "symbolPresentInRuntimeProbe": bool(item.get("symbolPresentInRuntimeProbe")),
            "symbolMappingOk": bool(item.get("symbolMappingOk")),
            "spreadFieldPresent": bool(item.get("spreadFieldPresent")),
            "spreadValue": item.get("spreadValue"),
            "sidecarLiveTickPresent": bool(item.get("sidecarLiveTickPresent")),
            "sidecarSpreadValue": item.get("sidecarSpreadValue"),
            "runtimeProbeSource": item.get("runtimeProbeSource", ""),
            "runtimeProbeFresh": bool(item.get("runtimeProbeFresh")),
            "runtimeProbeAgeSeconds": item.get("runtimeProbeAgeSeconds"),
            "riskLimitsPresent": bool(item.get("riskLimitsPresent")),
            "passed": bool(item.get("passed")),
        })
    return rows


def build_mt5_order_request_contract(
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
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    should_rebuild = bool(
        refresh_sources
        or operator_approval_json
        or moss_backtest_json
        or hfm_simulation_profile_json
        or hfm_contract_spec_json
        or extra_bases_roots
    )
    preflight = (
        build_live_runtime_preflight_probe(
            runtime_dir,
            write=bool(refresh_sources),
            refresh_sources=refresh_sources,
            operator_approval_json=operator_approval_json,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_live_runtime_preflight_probe(runtime_dir)
    )
    preflight_passed = bool(preflight.get("runtimeProbePassed"))
    preflight_data_plane_ready = bool(preflight.get("dataPlaneReadyForLivePilotReview"))
    preflight_execution_mode_ready = bool(preflight.get("executionModeReady"))
    preflight_execution_mode_only_blocked = bool(preflight.get("executionModeOnlyBlocked"))
    preflight_non_execution_blockers = [
        item for item in _safe_list(preflight.get("nonExecutionBlockers")) if isinstance(item, dict)
    ]
    preflight_execution_mode_blockers = [
        item for item in _safe_list(preflight.get("executionModeBlockers")) if isinstance(item, dict)
    ]
    blockers: list[dict[str, Any]] = []
    if not preflight_passed:
        if preflight_execution_mode_only_blocked:
            blockers.append(_blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "数据面预检已通过，但 MT5/EA 执行模式闸门尚未打开。",
                preflight.get("status"),
            ))
            blockers.extend(preflight_execution_mode_blockers)
        else:
            blockers.append(_blocker("RUNTIME_PREFLIGHT_NOT_PASSED", "运行时预检尚未通过，不能进入 MT5 request contract 代码评审。", preflight.get("status")))
            blockers.extend(item for item in _safe_list(preflight.get("blockers")) if isinstance(item, dict))
    lane_rows = _lane_contract_rows(preflight)
    ready_for_adapter_review = bool(preflight_passed and lane_rows and not blockers)
    preflight_hash = _stable_digest(preflight)
    status = "READY_FOR_ORDER_REQUEST_CONTRACT_REVIEW" if ready_for_adapter_review else "WAITING_ORDER_REQUEST_CONTRACT_INPUTS"
    status_zh = "可进入 MT5 请求合约代码评审" if ready_for_adapter_review else "等待运行时预检通过"
    next_required_action_zh = (
        "进入单独 execution adapter 代码评审；这个合约本身仍不会生成 MT5 请求文件。"
        if ready_for_adapter_review
        else "先让 runtime preflight 通过，再审查 MT5 请求文件与回执合同。"
    )
    if preflight_execution_mode_only_blocked:
        status = "WAITING_EXECUTION_MODE_ACTIVATION"
        status_zh = "数据面已通过，等待执行模式闸门"
        next_required_action_zh = (
            "HFM/BTC 数据、symbol、tick、spread、审批和 dry-run 回放已通过；"
            "剩余 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 执行模式闸门。"
        )
    payload = {
        "ok": True,
        "schema": ORDER_REQUEST_CONTRACT_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "readyForAdapterCodeReview": ready_for_adapter_review,
        "runtimePreflightPassed": preflight_passed,
        "runtimePreflightDataPlaneReadyForReview": preflight_data_plane_ready,
        "runtimePreflightExecutionModeReady": preflight_execution_mode_ready,
        "runtimePreflightExecutionModeOnlyBlocked": preflight_execution_mode_only_blocked,
        "runtimePreflightNonExecutionBlockers": preflight_non_execution_blockers,
        "runtimePreflightExecutionModeBlockers": preflight_execution_mode_blockers,
        "executionReady": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "requestWritesAllowed": False,
        "reviewPacketHash": preflight.get("reviewPacketHash", ""),
        "runtimePreflightHash": preflight_hash,
        "approvedLanes": _safe_list(preflight.get("approvedLanes")),
        "laneContracts": lane_rows,
        "requestContract": {
            "inputSchema": "quantgod.mt5_reviewed_order_request.v1",
            "receiptSchema": "quantgod.mt5_execution_receipt.v1",
            "requestDirectory": "runtime/agent/mt5_order_requests",
            "receiptDirectory": "runtime/agent/mt5_order_receipts",
            "contractOnly": True,
            "requestFilesProducedByThisTool": False,
            "idempotencyKey": "requestId",
            "oneRequestPerIntentId": True,
            "atomicWriteRequired": True,
            "allowedRequestFields": _request_fields(),
            "receiptFields": _receipt_fields(),
            "requiredRuntimeFuses": [
                "runtime_preflight_passed",
                "operator_approval_hash_current",
                "kill_switch_inactive",
                "dashboard_snapshot_fresh",
                "symbol_mapping_probe_passed",
                "spread_probe_passed",
                "daily_loss_probe_passed",
                "separate_execution_adapter_code_review",
            ],
            "forbiddenBeforeSeparateLiveReview": [
                "broker call side effects",
                "MT5 terminal mutation",
                "credential persistence",
                "live preset mutation",
                "Telegram command execution",
                "webhook-triggered execution",
            ],
        },
        "remainingReviewGates": [
            "separate_execution_adapter_code_review",
            "EA request reader implementation review",
            "receipt reconciliation review",
            "rollback and auto-disable review",
            "operator deployment checklist",
        ],
        "blockers": blockers,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerExecutionAllowed": False,
        "nextRequiredActionZh": next_required_action_zh,
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = order_request_contract_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_mt5_order_request_contract(runtime_dir: Path) -> dict[str, Any]:
    path = order_request_contract_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_mt5_order_request_contract(Path(runtime_dir), write=False)
