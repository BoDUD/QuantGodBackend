from __future__ import annotations

from statistics import median
from typing import Any

from .schema import PolicyThresholds

CLOSE_MOVE_FALLBACK_FLOORS = {
    "stop": 0.55,
    "tp1": 0.35,
    "tp2": 0.70,
    "tp3": 1.00,
}

def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * pct))
    return float(ordered[max(0, min(index, len(ordered) - 1))])

def build_dynamic_sltp_plan(
    scored_route: dict[str, Any] | None,
    observations: list[dict[str, Any]],
    thresholds: PolicyThresholds,
    symbol: str | None = None,
    direction: str | None = None,
    memory_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if scored_route:
        symbol = symbol or scored_route.get("symbol")
        direction = direction or scored_route.get("direction")
    relevant = [
        obs for obs in observations
        if (not symbol or str(obs.get("symbol", "")).upper() == str(symbol).upper())
        and (not direction or obs.get("direction") == direction)
    ][-thresholds.max_plan_records:]

    mfes = [abs(float(obs.get("mfe", 0.0))) for obs in relevant if abs(float(obs.get("mfe", 0.0))) > 0]
    maes = [abs(float(obs.get("mae", 0.0))) for obs in relevant if abs(float(obs.get("mae", 0.0))) > 0]
    close_moves = [float(obs.get("closeMoveR", 0.0)) for obs in relevant if abs(float(obs.get("closeMoveR", 0.0))) > 0]
    favorable_close_moves = [value for value in close_moves if value > 0]
    adverse_close_moves = [abs(value) for value in close_moves if value < 0]
    scores = [float(obs.get("scoreR", 0.0)) for obs in relevant]
    close_move_fallback_used = bool(not mfes and not maes and close_moves)

    if not relevant:
        basis = "样本不足，使用保守 ATR 倍数模板"
    elif close_move_fallback_used:
        basis = "基于长期记忆 close-move 桥接样本；缺真实 MFE/MAE，TP/SL 保守估算"
    else:
        basis = "基于近期 MFE/MAE 影子样本"

    memory_plan = _memory_tp_sl_adjustments(scored_route, memory_feedback)

    stop_basis = _percentile(maes, 0.70) or _percentile(adverse_close_moves, 0.70) or 1.35
    tp1 = _percentile(mfes, 0.50) or _percentile(favorable_close_moves, 0.40) or 0.70
    tp2 = _percentile(mfes, 0.70) or _percentile(favorable_close_moves, 0.60) or 1.20
    tp3 = _percentile(mfes, 0.85) or _percentile(favorable_close_moves, 0.80) or 1.80
    if memory_plan["earlyProfitTaking"]:
        tp1 = max(0.35, min(tp1, _percentile(mfes, 0.40) or tp1) * 0.9)
    if memory_plan["tightenStop"]:
        stop_basis = max(0.55, min(stop_basis, _percentile(maes, 0.60) or stop_basis))
    avg_score = sum(scores) / len(scores) if scores else 0.0
    fallback_pre_floor = {
        "stop": round(stop_basis, 4),
        "tp1": round(tp1, 4),
        "tp2": round(tp2, 4),
        "tp3": round(tp3, 4),
    } if close_move_fallback_used else {}
    fallback_floor_applied = False
    if close_move_fallback_used:
        floored_stop = max(stop_basis, CLOSE_MOVE_FALLBACK_FLOORS["stop"])
        floored_tp1 = max(tp1, CLOSE_MOVE_FALLBACK_FLOORS["tp1"])
        floored_tp2 = max(tp2, CLOSE_MOVE_FALLBACK_FLOORS["tp2"])
        floored_tp3 = max(tp3, CLOSE_MOVE_FALLBACK_FLOORS["tp3"])
        fallback_floor_applied = any(
            abs(before - after) > 1e-9
            for before, after in [
                (stop_basis, floored_stop),
                (tp1, floored_tp1),
                (tp2, floored_tp2),
                (tp3, floored_tp3),
            ]
        )
        stop_basis, tp1, tp2, tp3 = floored_stop, floored_tp1, floored_tp2, floored_tp3
        if fallback_floor_applied:
            basis = f"{basis}；已启用桥接样本安全地板"

    risk_mode = "保守"
    if scored_route and scored_route.get("state") == "ACTIVE_SHADOW_OK" and avg_score > thresholds.min_avg_score_r:
        risk_mode = "标准观察"
    if scored_route and scored_route.get("state") == "PAUSED":
        risk_mode = "暂停"
    if memory_plan["defensive"]:
        risk_mode = "记忆防守"

    breakeven_at = 0.70
    protect_at = 1.20
    giveback_pct = 0.45
    if memory_plan["earlyProfitTaking"]:
        breakeven_at = 0.55
        protect_at = 0.95
    if memory_plan["tightenTrailing"]:
        giveback_pct = 0.32
    if memory_plan["runnerAllowed"] and not memory_plan["defensive"]:
        protect_at = max(protect_at, 1.35)
        giveback_pct = max(giveback_pct, 0.50)

    return {
        "symbol": symbol or "UNKNOWN",
        "direction": direction or "FLAT",
        "directionLabel": "买入观察" if direction == "LONG" else "卖出观察" if direction == "SHORT" else "观望",
        "riskMode": risk_mode,
        "sampleCount": len(relevant),
        "basis": basis,
        "movementEvidence": {
            "mfeMaeSampleCount": max(len(mfes), len(maes)),
            "closeMoveSampleCount": len(close_moves),
            "favorableCloseMoveCount": len(favorable_close_moves),
            "adverseCloseMoveCount": len(adverse_close_moves),
            "closeMoveFallbackUsed": close_move_fallback_used,
            "fallbackQuality": "CLOSE_MOVE_BRIDGE_ONLY" if close_move_fallback_used else "RAW_MFE_MAE_OR_ATR",
            "fallbackFloorApplied": fallback_floor_applied,
            "fallbackPreFloor": fallback_pre_floor,
            "fallbackFloors": CLOSE_MOVE_FALLBACK_FLOORS if close_move_fallback_used else {},
        },
        "initialStop": {
            "label": "初始止损建议",
            "value": round(stop_basis, 4),
            "unit": "shadow_move_or_atr_multiple",
            "description": "取近期 MAE 七成分位或 ATR 保守倍数，仍仅为人工复核参考",
        },
        "targets": [
            {"name": "第一目标", "value": round(tp1, 4), "description": "近期 MFE 中位数"},
            {"name": "第二目标", "value": round(tp2, 4), "description": "近期 MFE 七成分位"},
            {"name": "第三目标", "value": round(tp3, 4), "description": "近期 MFE 八五分位"},
        ],
        "trailing": {
            "breakevenAtR": round(breakeven_at, 4),
            "protectAtR": round(protect_at, 4),
            "givebackPct": round(giveback_pct, 4),
            "description": "达到 0.7R 后保护本金；达到 1.2R 后使用波动跟踪；MFE 回撤过大时保护利润",
        },
        "timeStop": {
            "m15Bars": 4,
            "h1Bars": 3,
            "description": "超过指定 bar 数仍无正向 MFE，则降级为观望复核",
        },
        "memoryTpSlOverlay": memory_plan,
        "advisoryOnly": True,
    }


def _memory_tp_sl_adjustments(
    scored_route: dict[str, Any] | None,
    memory_feedback: dict[str, Any] | None,
) -> dict[str, Any]:
    feedback = memory_feedback if isinstance(memory_feedback, dict) else {}
    guidance = feedback.get("tpSlGuidance") if isinstance(feedback.get("tpSlGuidance"), dict) else {}
    exit_efficiency = guidance.get("exitEfficiency") if isinstance(guidance.get("exitEfficiency"), dict) else {}
    global_factor_penalties = feedback.get("adverseFactorPenalties") if isinstance(feedback.get("adverseFactorPenalties"), list) else []
    profile = scored_route.get("memoryQualityProfile") if isinstance(scored_route, dict) and isinstance(scored_route.get("memoryQualityProfile"), dict) else {}
    exit_quality = profile.get("exitQualityPatterns") if isinstance(profile.get("exitQualityPatterns"), list) else []
    adverse = profile.get("adverseFactors") if isinstance(profile.get("adverseFactors"), list) else []

    def count_quality(tag: str) -> int:
        for row in exit_quality:
            if isinstance(row, dict) and str(row.get("tag") or "").upper() == tag:
                return int(_num(row.get("count")))
        return 0

    def has_adverse(factor: str) -> bool:
        route_match = any(isinstance(row, dict) and str(row.get("factor") or "") == factor and _num(row.get("count")) > 0 for row in adverse)
        global_match = any(isinstance(row, dict) and str(row.get("factor") or "") == factor and _num(row.get("lossCount")) > 0 for row in global_factor_penalties)
        return route_match or global_match

    defensive = str(guidance.get("mode") or "").upper() == "DEFENSIVE_TP_SL_REVIEW"
    profit_giveback = int(_num(exit_efficiency.get("profitGivebackCount"))) + count_quality("PROFIT_GIVEBACK")
    low_capture = int(_num(exit_efficiency.get("lowMfeCaptureCount"))) + count_quality("LOW_MFE_CAPTURE")
    recovered_small_win = int(_num(exit_efficiency.get("recoveredSmallWinCount"))) + count_quality("RECOVERED_TO_SMALL_WIN")
    held_winner_well = int(_num(exit_efficiency.get("heldWinnerWellCount"))) + count_quality("HELD_WINNER_WELL")
    high_execution = has_adverse("executionRisk")
    chase_or_fake = has_adverse("entryTiming") or has_adverse("breakoutConfirmation")

    early_profit = defensive and (low_capture >= 2 or recovered_small_win >= 2 or chase_or_fake)
    tighten_trailing = defensive and (profit_giveback >= 2 or low_capture >= 2)
    tighten_stop = defensive and high_execution
    runner_allowed = held_winner_well >= 3 and not (profit_giveback >= 2 or recovered_small_win >= 2)
    actions = guidance.get("actionsZh") if isinstance(guidance.get("actionsZh"), list) else []
    reasons = [str(item) for item in actions if str(item).strip()]
    if early_profit:
        reasons.append("长期记忆显示低 MFE 捕获/扛单小赚，第一目标与保本线提前。")
    if tighten_trailing:
        reasons.append("长期记忆显示盈利回吐，收紧 MFE giveback trailing。")
    if tighten_stop:
        reasons.append("长期记忆显示执行风险逆风，止损参考取更保守分位。")
    if runner_allowed:
        reasons.append("长期记忆显示赢家持有质量足够，强趋势 runner 可多拿一段。")

    return {
        "schema": "quantgod.memory_tp_sl_overlay.v1",
        "applied": bool(defensive or early_profit or tighten_trailing or tighten_stop or runner_allowed),
        "sourceStatus": feedback.get("status") or "UNKNOWN",
        "guidanceMode": guidance.get("mode") or "UNKNOWN",
        "defensive": defensive,
        "earlyProfitTaking": early_profit,
        "tightenTrailing": tighten_trailing,
        "tightenStop": tighten_stop,
        "runnerAllowed": runner_allowed,
        "exitEfficiencyCounts": {
            "profitGivebackCount": profit_giveback,
            "lowMfeCaptureCount": low_capture,
            "recoveredSmallWinCount": recovered_small_win,
            "heldWinnerWellCount": held_winner_well,
            "closeMoveAvailableCount": int(_num(exit_efficiency.get("closeMoveAvailableCount"))),
            "closeMoveBridgeOnlyCount": int(_num(exit_efficiency.get("closeMoveBridgeOnlyCount"))),
        },
        "actionsZh": _unique(reasons)[:8],
    }


def _num(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
