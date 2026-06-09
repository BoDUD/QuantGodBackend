from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .forex_live12_runtime_handoff import build_forex_live12_runtime_handoff, read_forex_live12_runtime_handoff
from .schema import (
    FOREX_LIVE12_CAPACITY_EXPANSION_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_capacity_expansion_review_path,
    utc_now_iso,
)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_forex_live12_capacity_expansion_review(
    runtime_dir: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    handoff = build_forex_live12_runtime_handoff(
        runtime,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    current_limit = _int_value(handoff.get("positionSummary", {}).get("maxTotalTrades"), 0)
    open_count = _int_value(handoff.get("positionSummary", {}).get("openPositionCount"), 0)
    requested_limit = max(1, int(requested_max_total_trades or 10))
    expansion_multiple = round(requested_limit / current_limit, 2) if current_limit else None
    risk_notes = [
        {
            "code": "LIVE_PRESET_MUTATION_FORBIDDEN_HERE",
            "reasonZh": "把 maxTotalTrades 从当前值改到 10 属于真实 EA 风险参数变更；本 review artifact 不写 preset。",
        },
        {
            "code": "POSITION_CAPACITY_RISK_MULTIPLIER",
            "reasonZh": f"若从 {current_limit or '未知'} 扩到 {requested_limit}，最大并发仓位风险会同步放大，需要单独 execution lane 评审。",
        },
        {
            "code": "CENT_OR_MICRO_PROOF_REQUIRED",
            "reasonZh": "扩仓前应先有美分/微仓真实样本、回撤、连亏和风控自动停手机制证据。",
        },
    ]
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_CAPACITY_EXPANSION_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": "CAPACITY_EXPANSION_REVIEW_ONLY",
        "statusZh": "已记录扩仓到 10 的请求；当前只做评审，不改实盘 preset",
        "request": {
            "laneId": "forexMt5",
            "accountServer": handoff.get("account", {}).get("server"),
            "accountNumber": handoff.get("account", {}).get("number"),
            "symbol": handoff.get("market", {}).get("symbol"),
            "requestedMaxTotalTrades": requested_limit,
            "currentMaxTotalTrades": current_limit,
            "openPositionCount": open_count,
            "expansionMultiple": expansion_multiple,
        },
        "currentRuntime": {
            "status": handoff.get("status"),
            "statusZh": handoff.get("statusZh"),
            "runtimeSwitches": handoff.get("runtimeSwitches", {}),
            "capacityReleaseWatch": handoff.get("capacityReleaseWatch", {}),
            "noEntryState": handoff.get("noEntryDiagnostics", {}).get("state"),
            "noEntryStateZh": handoff.get("noEntryDiagnostics", {}).get("stateZh"),
        },
        "decision": {
            "canApplyHere": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "requestFilesWritten": False,
            "brokerCallsMade": False,
            "nextRequiredActionZh": "扩仓意图已记录；下一步只能做独立 execution lane 的风险评审、微仓样本验证和回滚设计，不能在本 lane 直接把实盘仓位上限改成 10。",
        },
        "riskNotes": risk_notes,
        "recommendedReviewChecklist": [
            "确认扩仓后最大总手数、单笔手数、同向仓位和保证金占用上限。",
            "确认连续亏损、日内亏损、点差异常、新闻事件和异常滑点时自动停手。",
            "确认扩仓先从 micro/cent 样本递进，而不是一次性从 2 扩到 10。",
            "确认任何 preset 改写都有独立 release token、回滚脚本和 no-side-effect 测试。",
        ],
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = forex_live12_capacity_expansion_review_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_capacity_expansion_review(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_capacity_expansion_review_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_capacity_expansion_review(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_CAPACITY_EXPANSION_REVIEW_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 capacity expansion review artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_capacity_expansion_review(runtime, write=False)
