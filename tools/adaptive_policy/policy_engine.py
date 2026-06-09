from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .data_loader import collect_observations, load_runtime_evidence
from .dynamic_sltp import build_dynamic_sltp_plan
from .entry_gate import evaluate_entry_gate
from .route_score import best_route_for_symbol, score_routes
from .schema import assert_safe_payload, safety_payload, thresholds_from_env, utc_now_iso

MISSING_FINE_FACTOR_PENALTY_CAP = 0.24

def _output_dir(runtime_dir: Path) -> Path:
    path = runtime_dir / "adaptive"
    path.mkdir(parents=True, exist_ok=True)
    return path

def build_adaptive_policy(
    runtime_dir: str | Path = "runtime",
    symbols: list[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    thresholds = thresholds_from_env()
    evidence = load_runtime_evidence(runtime_dir, max_records=thresholds.max_plan_records)
    memory_feedback = _load_long_term_memory_feedback(evidence.runtime_dir)
    memory_observations = _long_term_memory_observations(evidence.runtime_dir)
    observations = collect_observations(evidence) + memory_observations
    memory_feedback["memoryObservationCount"] = len(memory_observations)
    memory_feedback["memoryObservationSource"] = _long_term_memory_observation_source(evidence.runtime_dir)
    scored_routes = _apply_long_term_memory_feedback(score_routes(observations, thresholds), memory_feedback, thresholds)

    selected_symbols = symbols or evidence.symbols or sorted({route["symbol"] for route in scored_routes})
    gates: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    for symbol in selected_symbols:
        route = best_route_for_symbol(scored_routes, symbol)
        gates.append(evaluate_entry_gate(evidence, route, thresholds, symbol=symbol))
        direction = route.get("direction") if route else None
        plans.append(
            build_dynamic_sltp_plan(
                route,
                observations,
                thresholds,
                symbol=symbol,
                direction=direction,
                memory_feedback=memory_feedback,
            )
        )

    payload: dict[str, Any] = {
        "schema": "quantgod.adaptive_policy.v1",
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(Path(runtime_dir).expanduser()),
        "symbols": selected_symbols,
        "dataQuality": {
            "runtimeFound": Path(runtime_dir).exists(),
            "snapshotCount": len(evidence.snapshots),
            "dashboardFound": evidence.dashboard is not None,
            "outcomeRows": len(evidence.outcome_rows),
            "closeHistoryRows": len(evidence.close_history_rows),
            "strategyEvalRows": len(evidence.strategy_eval_rows),
            "journalRows": len(evidence.journal_rows),
            "fastlaneQualityFound": evidence.fastlane_quality is not None,
            "fastlaneHeartbeatFresh": bool((evidence.fastlane_quality or {}).get("heartbeatFresh")),
            "observationCount": len(observations),
        },
        "thresholds": thresholds.__dict__,
        "longTermMemoryFeedback": memory_feedback,
        "routes": scored_routes,
        "entryGates": gates,
        "dynamicSltpPlans": plans,
        "safety": safety_payload(),
    }
    assert_safe_payload(payload)

    if write:
        out = _output_dir(evidence.runtime_dir)
        (out / "QuantGod_AdaptivePolicy.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "QuantGod_DynamicEntryGate.json").write_text(json.dumps({"schema": payload["schema"], "generatedAt": payload["generatedAt"], "entryGates": gates, "safety": safety_payload()}, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "QuantGod_DynamicSLTPPlan.json").write_text(json.dumps({"schema": payload["schema"], "generatedAt": payload["generatedAt"], "dynamicSltpPlans": plans, "safety": safety_payload()}, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_policy_ledger(out / "QuantGod_AdaptivePolicyLedger.csv", scored_routes, payload["generatedAt"])

    return payload

def _load_long_term_memory_feedback(runtime_dir: Path) -> dict[str, Any]:
    path = Path(runtime_dir) / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "status": "MISSING",
            "memoryFound": False,
            "candidatePenaltyRules": [],
            "defenseMode": {"enabled": False},
            "reasonZh": "尚未生成长期交易记忆，adaptive policy 使用原始 route score。",
        }
    memory = payload.get("longTermTradeMemory") if isinstance(payload.get("longTermTradeMemory"), dict) else {}
    feedback = memory.get("entryFeedbackPolicy") if isinstance(memory.get("entryFeedbackPolicy"), dict) else {}
    rolling = memory.get("rollingReview") if isinstance(memory.get("rollingReview"), dict) else {}
    return {
        "status": feedback.get("status") or memory.get("status") or "UNKNOWN",
        "memoryFound": bool(memory),
        "memoryGeneratedAt": memory.get("generatedAt"),
        "rollingReviewStatus": rolling.get("status"),
        "sampleCount": feedback.get("sampleCount") or rolling.get("sampleCount") or 0,
        "winRate": rolling.get("winRate"),
        "totalProfitR": rolling.get("totalProfitR"),
        "candidatePenaltyRules": feedback.get("candidatePenaltyRules") if isinstance(feedback.get("candidatePenaltyRules"), list) else [],
        "adverseFactorPenalties": feedback.get("adverseFactorPenalties") if isinstance(feedback.get("adverseFactorPenalties"), list) else [],
        "defenseMode": feedback.get("defenseMode") if isinstance(feedback.get("defenseMode"), dict) else {"enabled": False},
        "aggressionControl": feedback.get("aggressionControl") if isinstance(feedback.get("aggressionControl"), dict) else {},
        "tpSlGuidance": feedback.get("tpSlGuidance") if isinstance(feedback.get("tpSlGuidance"), dict) else {},
        "reasonZh": memory.get("nextActionZh") or "长期记忆已加载。",
        "safety": safety_payload(),
    }

def _long_term_memory_observations(runtime_dir: Path) -> list[dict[str, Any]]:
    path = Path(runtime_dir) / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    memory = payload.get("longTermTradeMemory") if isinstance(payload.get("longTermTradeMemory"), dict) else {}
    exits = _long_term_memory_exit_rows(memory)
    entries = memory.get("entryMemory") if isinstance(memory.get("entryMemory"), list) else []
    entries_by_id = {
        str(row.get("tradeId")): row
        for row in entries
        if isinstance(row, dict) and row.get("tradeId")
    }
    observations: list[dict[str, Any]] = []
    for row in exits[-36:]:
        if not isinstance(row, dict):
            continue
        direction = str(row.get("side") or "").upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        profit = safe_memory_float(row.get("profitR"), 0.0)
        if abs(profit) <= 0.0000001 and str(row.get("exitType") or "") == "FLAT_EXIT":
            continue
        entry = entries_by_id.get(str(row.get("tradeId"))) or {}
        mfe_r = safe_memory_float(row.get("mfeR"), 0.0)
        mae_r = safe_memory_float(row.get("maeR"), 0.0)
        close_move = row.get("closeMove") if isinstance(row.get("closeMove"), dict) else {}
        close_move_r = safe_memory_float(close_move.get("closeMoveR"), 0.0) if close_move else 0.0
        observations.append(
            {
                "source": "long_term_trade_memory",
                "symbol": str(row.get("symbol") or "UNKNOWN"),
                "strategy": str(row.get("strategyVersion") or "UNKNOWN"),
                "direction": direction,
                "regime": "MEMORY_REPLAY",
                "scoreR": profit,
                "win": profit > 0,
                "mfe": mfe_r,
                "mae": mae_r,
                "closeMoveR": close_move_r,
                "spread": 0.0,
                "raw": {
                    "tradeId": row.get("tradeId"),
                    "exitType": row.get("exitType"),
                    "lossTags": row.get("lossTags") if isinstance(row.get("lossTags"), list) else [],
                    "exitQualityTags": row.get("exitQualityTags") if isinstance(row.get("exitQualityTags"), list) else [],
                    "movementQuality": row.get("movementQuality"),
                    "closeMove": close_move,
                    "capturedMfeRatio": row.get("capturedMfeRatio"),
                    "givebackR": row.get("givebackR"),
                    "dataCoverageScore": entry.get("dataCoverageScore"),
                    "professionalScore": entry.get("professionalScore"),
                    "fundFlowScore": entry.get("fundFlowScore"),
                    "executionRiskScore": entry.get("executionRiskScore"),
                    "factors": entry.get("factors") if isinstance(entry.get("factors"), dict) else {},
                },
            }
        )
    return observations

def _long_term_memory_exit_rows(memory: dict[str, Any]) -> list[Any]:
    review_exits = memory.get("reviewExitMemory") if isinstance(memory.get("reviewExitMemory"), list) else []
    if review_exits:
        return review_exits
    return memory.get("exitMemory") if isinstance(memory.get("exitMemory"), list) else []

def _long_term_memory_observation_source(runtime_dir: Path) -> str:
    path = Path(runtime_dir) / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "missing"
    memory = payload.get("longTermTradeMemory") if isinstance(payload.get("longTermTradeMemory"), dict) else {}
    review_exits = memory.get("reviewExitMemory") if isinstance(memory.get("reviewExitMemory"), list) else []
    if review_exits:
        return "reviewExitMemory"
    exits = memory.get("exitMemory") if isinstance(memory.get("exitMemory"), list) else []
    return "exitMemory" if exits else "none"

def _apply_long_term_memory_feedback(
    routes: list[dict[str, Any]],
    memory_feedback: dict[str, Any],
    thresholds: Any,
) -> list[dict[str, Any]]:
    rules = memory_feedback.get("candidatePenaltyRules") if isinstance(memory_feedback.get("candidatePenaltyRules"), list) else []
    defense = memory_feedback.get("defenseMode") if isinstance(memory_feedback.get("defenseMode"), dict) else {}
    defense_enabled = bool(defense.get("enabled"))
    risk_cap = safe_memory_float(defense.get("riskMultiplierCap"), 1.0) if defense_enabled else 1.0
    score_buffer = safe_memory_float(defense.get("entryScoreBufferAdd"), 0.0) if defense_enabled else 0.0
    adjusted: list[dict[str, Any]] = []
    for route in routes:
        row = dict(route)
        applied = _matching_memory_rules(row, rules)
        penalty_breakdown = _memory_penalty_breakdown(applied)
        penalty = penalty_breakdown["total"]
        raw_avg = safe_memory_float(row.get("avgScoreR"), 0.0)
        raw_risk = safe_memory_float(row.get("riskMultiplier"), 0.0)
        adjusted_score = round(raw_avg - penalty - score_buffer, 4)
        adjusted_risk = raw_risk
        if penalty > 0:
            adjusted_risk = max(0.0, raw_risk * max(0.0, 1.0 - min(0.9, penalty)))
        if defense_enabled:
            adjusted_risk = min(adjusted_risk, risk_cap)
        state_before = str(row.get("state") or "UNKNOWN")
        state_after = _memory_adjusted_state(state_before, adjusted_score, applied, defense_enabled, thresholds)
        reason = str(row.get("reason") or "")
        if applied or defense_enabled:
            reason = (
                f"{reason}；长期记忆扣分={penalty:.4g}；"
                f"防守={'开' if defense_enabled else '关'}；调整后均值R={adjusted_score:.4g}"
            )
        row.update(
            {
                "rawAvgScoreR": row.get("avgScoreR"),
                "avgScoreR": adjusted_score,
                "memoryPenalty": penalty,
                "memoryEntryScoreBuffer": round(score_buffer, 4),
                "stateBeforeMemory": state_before,
                "state": state_after,
                "riskMultiplierBeforeMemory": row.get("riskMultiplier"),
                "riskMultiplier": round(adjusted_risk, 4),
                "memoryFeedback": {
                    "applied": bool(applied or defense_enabled),
                    "appliedRules": applied,
                    "penaltyBreakdown": penalty_breakdown,
                    "defenseModeEnabled": defense_enabled,
                    "riskMultiplierCap": risk_cap,
                    "reasonZh": memory_feedback.get("reasonZh") or "",
                },
                "reason": reason,
            }
        )
        adjusted.append(row)
    adjusted.sort(key=lambda row: (row["state"] == "PAUSED", -float(row.get("avgScoreR", 0)), -float(row.get("winRate", 0)), row["symbol"]))
    return adjusted

def _memory_penalty_breakdown(applied_rules: list[dict[str, Any]]) -> dict[str, Any]:
    regular = 0.0
    missing_fine_factor = 0.0
    missing_fine_factor_count = 0
    for item in applied_rules:
        penalty = safe_memory_float(item.get("penalty"), 0.0)
        match = item.get("match") if isinstance(item.get("match"), dict) else {}
        data_gap = str(match.get("dataGap") or "")
        if data_gap.startswith("missingFactor:"):
            missing_fine_factor += penalty
            missing_fine_factor_count += 1
        else:
            regular += penalty
    capped_missing = min(MISSING_FINE_FACTOR_PENALTY_CAP, missing_fine_factor)
    return {
        "regularPenalty": round(regular, 4),
        "missingFineFactorRawPenalty": round(missing_fine_factor, 4),
        "missingFineFactorAppliedPenalty": round(capped_missing, 4),
        "missingFineFactorPenaltyCap": MISSING_FINE_FACTOR_PENALTY_CAP,
        "missingFineFactorRuleCount": missing_fine_factor_count,
        "total": round(regular + capped_missing, 4),
    }

def _memory_adjusted_state(
    state_before: str,
    adjusted_score: float,
    applied_rules: list[dict[str, Any]],
    defense_enabled: bool,
    thresholds: Any,
) -> str:
    if state_before in {"PAUSED", "INSUFFICIENT_DATA"}:
        return state_before
    if applied_rules and adjusted_score <= safe_memory_float(getattr(thresholds, "pause_avg_score_r", -0.25), -0.25):
        return "PAUSED"
    if defense_enabled and state_before == "ACTIVE_SHADOW_OK":
        return "WATCH_ONLY"
    if applied_rules and adjusted_score < safe_memory_float(getattr(thresholds, "min_avg_score_r", 0.05), 0.05):
        return "WATCH_ONLY"
    return state_before

def _matching_memory_rules(route: dict[str, Any], rules: list[Any]) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        match = rule.get("match") if isinstance(rule.get("match"), dict) else {}
        symbol = match.get("symbol")
        side = match.get("side")
        data_gap = match.get("dataGap")
        adverse_factor = match.get("adverseFactor")
        if symbol and str(symbol).upper() != str(route.get("symbol") or "").upper():
            continue
        if side and str(side).upper() != str(route.get("direction") or "").upper():
            continue
        observed_count = 0
        observed_ratio = 0.0
        if data_gap:
            observed_count, observed_ratio = _quality_profile_match(route, "dataGaps", "gap", data_gap)
            if observed_count <= 0:
                continue
        if adverse_factor:
            observed_count, observed_ratio = _quality_profile_match(route, "adverseFactors", "factor", adverse_factor)
            if observed_count <= 0:
                continue
        if not symbol and not side and not data_gap and not adverse_factor:
            continue
        applied.append(
            {
                "match": match,
                "penalty": safe_memory_float(rule.get("penalty"), 0.0),
                "observedCount": observed_count,
                "observedRatio": observed_ratio,
                "reasonZh": rule.get("reasonZh") or "",
            }
        )
    return applied

def _quality_profile_match(
    route: dict[str, Any],
    section_name: str,
    key: str,
    expected: Any,
) -> tuple[int, float]:
    profile = route.get("memoryQualityProfile") if isinstance(route.get("memoryQualityProfile"), dict) else {}
    rows = profile.get(section_name) if isinstance(profile.get(section_name), list) else []
    expected_text = str(expected or "").upper()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get(key) or "").upper() != expected_text:
            continue
        return int(safe_memory_float(row.get("count"), 0.0)), safe_memory_float(row.get("ratio"), 0.0)
    return 0, 0.0

def safe_memory_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default

def _write_policy_ledger(path: Path, routes: list[dict[str, Any]], generated_at: str) -> None:
    import csv

    fields = ["generatedAt", "symbol", "strategy", "direction", "regime", "samples", "winRate", "avgScoreR", "state", "riskMultiplier", "reason"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for route in routes:
            writer.writerow({field: generated_at if field == "generatedAt" else route.get(field, "") for field in fields})

def load_policy_file(runtime_dir: str | Path = "runtime") -> dict[str, Any] | None:
    path = Path(runtime_dir).expanduser() / "adaptive" / "QuantGod_AdaptivePolicy.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
