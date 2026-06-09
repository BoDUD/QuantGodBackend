from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .forex_live12_capacity_expansion_review import build_forex_live12_capacity_expansion_review
from .forex_live12_runtime_handoff import build_forex_live12_runtime_handoff
from .schema import (
    FOREX_LIVE12_CAPACITY_EXPANSION_ROADMAP_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_capacity_expansion_roadmap_path,
    utc_now_iso,
)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if numeric == numeric else default


def _phase_rows(current_limit: int, target_limit: int) -> list[dict[str, Any]]:
    candidates = [3, 4, 6, 8, 10]
    phases: list[dict[str, Any]] = []
    previous = current_limit or 2
    for candidate in candidates:
        if candidate <= previous or candidate > target_limit:
            continue
        phases.append({
            "fromMaxTotalTrades": previous,
            "toMaxTotalTrades": candidate,
            "maxExpansionMultipleFromCurrent": round(candidate / max(current_limit or 1, 1), 2),
            "requiredEvidence": {
                "minNaturalClosedTrades": 5 if candidate <= 3 else 10,
                "minNoHardRollbackDays": 1 if candidate <= 3 else 3,
                "maxObservedDrawdownPct": 1.5 if candidate <= 3 else 2.5,
                "maxConsecutiveLosses": 2,
                "spreadTierAllowed": ["NORMAL", "SOFT_WIDE"] if candidate <= 3 else ["NORMAL"],
            },
            "rollbackRule": {
                "autoRevertToMaxTotalTrades": previous,
                "triggerZh": "若出现硬回滚、连续亏损超限、点差异常或日内亏损超限，回退到上一档。",
            },
            "applyAllowedHere": False,
        })
        previous = candidate
    return phases


def build_forex_live12_capacity_expansion_roadmap(
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
    review = build_forex_live12_capacity_expansion_review(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    current_limit = _int_value(handoff.get("positionSummary", {}).get("maxTotalTrades"), 2)
    open_count = _int_value(handoff.get("positionSummary", {}).get("openPositionCount"), 0)
    target_limit = max(current_limit, _int_value(review.get("request", {}).get("requestedMaxTotalTrades"), 10))
    guards = handoff.get("noEntryDiagnostics", {}).get("guards", {}) if isinstance(handoff.get("noEntryDiagnostics"), dict) else {}
    spread_tier = str(guards.get("spreadTier") or "")
    spread_pips = _float_value(guards.get("spreadPips"), 0.0)
    phases = _phase_rows(current_limit, target_limit)
    next_phase = phases[0] if phases else {}
    spread_blocks_next = bool(next_phase and spread_tier not in next_phase.get("requiredEvidence", {}).get("spreadTierAllowed", []))
    current_capacity_room = max(0, current_limit - open_count)
    status = "ROADMAP_WAITING_SPREAD_NORMALIZATION" if spread_blocks_next else "ROADMAP_READY_FOR_MICRO_REVIEW"
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_CAPACITY_EXPANSION_ROADMAP_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": status,
        "statusZh": (
            "扩仓路线已生成；当前点差等级不适合推进下一档"
            if spread_blocks_next
            else "扩仓路线已生成；可继续准备下一档微仓评审"
        ),
        "request": {
            "laneId": "forexMt5",
            "currentMaxTotalTrades": current_limit,
            "requestedMaxTotalTrades": target_limit,
            "openPositionCount": open_count,
            "currentCapacityRoom": current_capacity_room,
        },
        "currentMarketGate": {
            "spreadTier": spread_tier,
            "spreadPips": spread_pips,
            "blocksNextPhase": spread_blocks_next,
        },
        "nextPhase": next_phase,
        "phases": phases,
        "decision": {
            "canApplyHere": False,
            "canWritePresetHere": False,
            "nextRecommendedMaxTotalTrades": next_phase.get("toMaxTotalTrades") if next_phase and not spread_blocks_next else current_limit,
            "nextRequiredActionZh": (
                "等待点差从 SOFT_WIDE_HIGH/HARD_WIDE 回到下一档允许范围，再继续 2→3 微仓评审。"
                if spread_blocks_next
                else "先准备 2→3 的微仓评审：小样本、回撤、连亏、点差和回滚条件都通过后，再由独立 execution lane 处理 preset 变更。"
            ),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
        },
        "sourceArtifacts": {
            "handoffSchema": handoff.get("schema"),
            "capacityReviewSchema": review.get("schema"),
            "handoffGeneratedAtIso": handoff.get("generatedAtIso"),
            "capacityReviewGeneratedAtIso": review.get("generatedAtIso"),
        },
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = forex_live12_capacity_expansion_roadmap_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_capacity_expansion_roadmap(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_capacity_expansion_roadmap_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_capacity_expansion_roadmap(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_CAPACITY_EXPANSION_ROADMAP_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 capacity expansion roadmap artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_capacity_expansion_roadmap(runtime, write=False)
