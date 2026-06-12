from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List

try:
    from tools.adaptive_policy.data_loader import first_value, load_runtime_evidence
    from tools.adaptive_policy.schema import normalize_direction, safe_float
except ModuleNotFoundError:  # pragma: no cover
    from adaptive_policy.data_loader import first_value, load_runtime_evidence
    from adaptive_policy.schema import normalize_direction, safe_float

from .io_utils import load_json, read_jsonl, utc_now_iso
from .schema import SAFETY


SCHEMA_LONG_TERM_MEMORY = "quantgod.long_term_trade_memory.v1"
ROLLING_WINDOW_TRADES = 36
MIN_REVIEW_SAMPLES = 12
REVIEW_COOLDOWN_MINUTES = 360
FEEDBACK_SCAN_LIMIT = 5000
NESTED_ENTRY_CONTEXT_KEYS = (
    "entryMemory",
    "entryContext",
    "signalContext",
    "marketContext",
    "scoreBreakdown",
    "scores",
    "factors",
    "factorSnapshot",
    "riskPlan",
    "risk",
    "estimates",
    "prediction",
    "decision",
    "ai",
    "context",
    "trade",
    "order",
    "position",
    "strategyJson",
    "entry",
    "exit",
)
SCALAR_VALUE_KEYS = ("value", "score", "raw", "normalized", "r", "pct", "pips", "priceMove")
ENTRY_COMPLETENESS_FIELDS = {
    "base": ("tradeId", "entryTime", "symbol", "side", "strategyVersion", "leverage", "margin", "notional"),
    "scores": (
        "compositeScore",
        "dataCoverageScore",
        "professionalScore",
        "marketQualityScore",
        "entryTimingScore",
        "fundFlowScore",
        "executionRiskScore",
        "resonanceCount",
    ),
    "estimates": ("estimatedEV", "estimatedWinProbability", "estimatedRiskReward", "positionScaling"),
    "factors": (
        "atr",
        "trendScore",
        "sentimentScore",
        "openInterestChange",
        "newsScore",
        "smartMoneyScore",
        "predictionMarketScore",
        "kronosScore",
    ),
    "riskPlan": (
        "stopLossR",
        "takeProfitR",
        "tp1R",
        "tp2R",
        "trailingStartR",
        "mfeGivebackPct",
        "maxHoldMinutes",
        "stopLossPriceMove",
        "takeProfitPriceMove",
    ),
}
FINE_FACTOR_DEFS = {
    "atr": {"category": "factors", "field": "atr", "adverse": "none", "threshold": 0.0},
    "trend": {"category": "factors", "field": "trendScore", "adverse": "lt", "threshold": -0.15},
    "sentiment": {"category": "factors", "field": "sentimentScore", "adverse": "lt", "threshold": -0.15},
    "openInterest": {"category": "factors", "field": "openInterestChange", "adverse": "lt", "threshold": -0.15},
    "news": {"category": "factors", "field": "newsScore", "adverse": "lt", "threshold": -0.15},
    "smartMoney": {"category": "factors", "field": "smartMoneyScore", "adverse": "lt", "threshold": -0.15},
    "predictionMarket": {"category": "factors", "field": "predictionMarketScore", "adverse": "lt", "threshold": -0.15},
    "kronos": {"category": "factors", "field": "kronosScore", "adverse": "lt", "threshold": -0.15},
    "fundFlow": {"category": "entry", "field": "fundFlowScore", "adverse": "lt", "threshold": -0.15},
    "entryTiming": {"category": "entry", "field": "entryTimingScore", "adverse": "lt", "threshold": 0.45},
    "executionRisk": {"category": "entry", "field": "executionRiskScore", "adverse": "gt", "threshold": 0.60},
}


def build_long_term_trade_memory(runtime_dir: Path, *, now_iso: str | None = None) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    evidence = load_runtime_evidence(runtime_dir, max_records=1200)
    raw_rows = _collect_trade_rows(runtime_dir, evidence)
    trades = _dedupe_trades(_trade_memory_from_rows(raw_rows))
    trades.sort(key=lambda row: str(row.get("exitTime") or row.get("entryTime") or ""))
    recent = trades[-ROLLING_WINDOW_TRADES:]
    review_trades = _review_trade_window(trades)
    previous = _previous_long_term_memory(runtime_dir)
    rolling = _rolling_review(review_trades, previous, now_iso=now_iso or utc_now_iso())
    feedback = _entry_feedback_policy(review_trades, rolling)
    return {
        "schema": SCHEMA_LONG_TERM_MEMORY,
        "generatedAt": now_iso or utc_now_iso(),
        "status": _status(trades, rolling),
        "tradeMemoryCount": len(trades),
        "rollingWindowTrades": len(recent),
        "reviewWindowTrades": len(review_trades),
        "minReviewSamples": MIN_REVIEW_SAMPLES,
        "reviewCooldownMinutes": REVIEW_COOLDOWN_MINUTES,
        "entryMemory": [row["entryMemory"] for row in recent],
        "exitMemory": [row["exitMemory"] for row in recent if row.get("exitMemory")],
        "reviewExitMemory": [row["exitMemory"] for row in review_trades if row.get("exitMemory")],
        "rollingReview": rolling,
        "entryFeedbackPolicy": feedback,
        "nextActionZh": _next_action(rolling, feedback),
        "safety": dict(SAFETY),
    }


def _collect_trade_rows(runtime_dir: Path, evidence: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for source, source_rows in (
        ("adaptive_outcome", evidence.outcome_rows),
        ("close_history", evidence.close_history_rows),
        ("ai_journal", evidence.journal_rows),
    ):
        for row in source_rows:
            if isinstance(row, dict):
                item = dict(row)
                item.setdefault("_source", source)
                rows.append(item)
    for path in _feedback_jsonl_paths(runtime_dir):
        for row in read_jsonl(path)[-FEEDBACK_SCAN_LIMIT:]:
            item = dict(row)
            item.setdefault("_source", path.name)
            rows.append(item)
    return rows


def _feedback_jsonl_paths(runtime_dir: Path) -> List[Path]:
    names = (
        runtime_dir / "execution" / "QuantGod_LiveExecutionFeedback.jsonl",
        runtime_dir / "evidence_os" / "QuantGod_LiveExecutionFeedback.jsonl",
        runtime_dir / "QuantGod_LiveExecutionFeedback.jsonl",
        runtime_dir / "journal" / "QuantGod_AIAdvisoryOutcomes.jsonl",
    )
    return [path for path in names if path.exists()]


def _trade_memory_from_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    trades: List[Dict[str, Any]] = []
    for row in rows:
        if not _looks_like_trade_outcome(row):
            continue
        entry = _entry_memory(row)
        exit_memory = _exit_memory(row, entry)
        trades.append(
            {
                "tradeId": entry["tradeId"],
                "entryTime": entry.get("entryTime"),
                "exitTime": exit_memory.get("exitTime"),
                "entryMemory": entry,
                "exitMemory": exit_memory,
            }
        )
    return trades


def _looks_like_trade_outcome(row: Dict[str, Any]) -> bool:
    event = str(first_value(row, "eventType", "type", "event", default="")).upper()
    entry_context_events = {
        "DRY_RUN_ENTRY_CONTEXT",
        "LIVE_LOOP_ENTRY_CONTEXT",
        "SHADOW_ENTRY_CONTEXT",
        "POLICY_ENTRY_CONTEXT",
    }
    if event in entry_context_events:
        return False
    exit_events = {
        "LIVE_EXIT",
        "SHADOW_EXIT",
        "TRADE_OUTCOME",
        "HISTORY_CLOSE",
        "ORDER_CLOSE",
        "POSITION_CLOSE",
        "HISTORY_OUTCOME",
    }
    if event in exit_events:
        return True
    profit_value = first_value(row, "profitR", "ProfitR", "pnlPercent", "pnlPct", "profitPct", "scoreR")
    if profit_value is None:
        return False
    if abs(safe_float(profit_value, 0.0)) > 0:
        return True
    source = str(first_value(row, "_source", "sourceKind", "source", default="")).lower()
    return any(token in source for token in ("outcome", "close_history", "trade_journal"))


def _entry_memory(row: Dict[str, Any]) -> Dict[str, Any]:
    memory_row = _row_with_bridged_history_context(row)
    trade_id = _trade_id(memory_row)
    symbol = str(_value(memory_row, "symbol", "Symbol", "instrument", default="UNKNOWN") or "UNKNOWN")
    side = normalize_direction(_value(memory_row, "side", "Side", "direction", "Direction", "action", "type"))
    factors = _factor_snapshot(memory_row)
    entry_reasons = _list_value(_value(memory_row, "entryReasons", "reasons", "entryReason", "reasonZh", default=[]))
    context_quality = _entry_context_quality(memory_row)
    return {
        "schema": "quantgod.trade_entry_memory.v1",
        "tradeId": trade_id,
        "contextQuality": context_quality,
        "contextQualityReasonZh": _entry_context_quality_reason(memory_row, context_quality),
        "proxySource": str(_value(memory_row, "proxySource", default="") or ""),
        "entryTime": _value(memory_row, "entryTime", "entrySignalTime", "openTime", "timestamp", "time", "createdAt"),
        "symbol": symbol,
        "side": side,
        "strategyVersion": _value(memory_row, "strategyVersion", "strategyId", "strategy", "comment", default="UNKNOWN"),
        "leverage": safe_float(_value(memory_row, "leverage", "Leverage", default=0), 0),
        "margin": safe_float(_value(memory_row, "margin", "Margin", "marginUsd", default=0), 0),
        "notional": safe_float(_value(memory_row, "notional", "Notional", "notionalUsd", default=0), 0),
        "compositeScore": _score(memory_row, "compositeScore", "totalScore", "score", "signalScore"),
        "dataCoverageScore": _score(memory_row, "dataCoverageScore", "dataCoverage", "coverageScore"),
        "professionalScore": _score(memory_row, "professionalScore", "proScore"),
        "marketQualityScore": _score(memory_row, "marketQualityScore", "marketQuality"),
        "entryTimingScore": _score(memory_row, "entryTimingScore", "entryTiming"),
        "fundFlowScore": _score(memory_row, "fundFlowScore", "fundFlow"),
        "executionRiskScore": _score(memory_row, "executionRiskScore", "executionRisk"),
        "resonanceCount": int(safe_float(_value(memory_row, "resonanceCount", "resonance", default=0), 0)),
        "candidateSource": _value(memory_row, "candidateSource", "source", "_source", default="UNKNOWN"),
        "entryReasons": entry_reasons,
        "factors": factors,
        "estimatedEV": _score(memory_row, "estimatedEV", "ev", "expectedValue"),
        "estimatedWinProbability": _score(memory_row, "estimatedWinProbability", "winProbability", "winProb"),
        "estimatedRiskReward": _score(memory_row, "estimatedRiskReward", "riskReward", "rr"),
        "positionScaling": _score(memory_row, "positionScaling", "positionScale", "riskMultiplier"),
        "riskPlan": _risk_plan_snapshot(memory_row),
        "factorAttributionSummary": _factor_attribution_summary(memory_row, factors, entry_reasons),
        "safety": dict(SAFETY),
    }


def _exit_memory(row: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    profit_r = safe_float(first_value(row, "profitR", "ProfitR", "scoreR", "r", default=0), 0)
    pnl_percent = safe_float(first_value(row, "pnlPercent", "pnlPct", "profitPct", default=profit_r * 100), profit_r * 100)
    exit_type = _exit_type(row, profit_r)
    duration = _duration_minutes(entry.get("entryTime"), first_value(row, "exitTime", "closeTime", "fillTime", "timestamp", "time"))
    mfe_r = max(0.0, safe_float(first_value(row, "mfeR", "MfeR", "mfe", "maxFavorableR", default=0), 0))
    mae_r = abs(safe_float(first_value(row, "maeR", "MaeR", "mae", "maxAdverseR", default=0), 0))
    close_move = _exit_close_move(row, entry, profit_r)
    giveback_r = max(0.0, mfe_r - max(0.0, profit_r))
    captured_mfe_ratio = round(max(0.0, profit_r) / mfe_r, 6) if mfe_r > 0 else None
    tags = _loss_tags(row, entry, profit_r, pnl_percent, exit_type)
    return {
        "schema": "quantgod.trade_exit_memory.v1",
        "tradeId": entry["tradeId"],
        "exitTime": first_value(row, "exitTime", "closeTime", "fillTime", "timestamp", "time", "createdAt"),
        "symbol": entry["symbol"],
        "side": entry["side"],
        "strategyVersion": entry["strategyVersion"],
        "profitR": round(profit_r, 6),
        "pnlPercent": round(pnl_percent, 6),
        "exitType": exit_type,
        "durationMinutes": duration,
        "mfeR": round(mfe_r, 6),
        "maeR": round(mae_r, 6),
        "mfeMaeAvailable": bool(mfe_r > 0.0 or mae_r > 0.0),
        "movementQuality": _exit_movement_quality(entry, mfe_r, mae_r, close_move),
        "closeMove": close_move,
        "givebackR": round(giveback_r, 6),
        "capturedMfeRatio": captured_mfe_ratio,
        "lossTags": tags,
        "exitQualityTags": _exit_quality_tags(profit_r, mfe_r, mae_r, giveback_r, captured_mfe_ratio, duration, exit_type),
        "exitReason": first_value(row, "exitReason", "reason", "reasonZh", default=""),
        "safety": dict(SAFETY),
    }


def _loss_tags(
    row: Dict[str, Any],
    entry: Dict[str, Any],
    profit_r: float,
    pnl_percent: float,
    exit_type: str,
) -> List[str]:
    if profit_r >= 0 and pnl_percent >= 0:
        return []
    text = _row_text(row)
    tags: List[str] = []
    duration = _duration_minutes(entry.get("entryTime"), first_value(row, "exitTime", "closeTime", "fillTime", "timestamp", "time"))
    mfe = safe_float(first_value(row, "mfeR", "MfeR", "mfe", default=0), 0)
    mae = safe_float(first_value(row, "maeR", "MaeR", "mae", default=0), 0)
    if duration is not None and duration <= 30:
        tags.append("FAST_LOSS")
    if "stop" in text or "sl" in text or exit_type == "STOP_LOSS":
        tags.append("STOP_LOSS")
    if "pullback" in text or "chase" in text or (mfe > 0.15 and profit_r < 0):
        tags.append("CHASE_PULLBACK")
    if "breakout" in text or "fake" in text:
        tags.append("FAKE_BREAKOUT")
    if _score_value(entry.get("fundFlowScore")) < -0.15 or "flow" in text or "oi" in text:
        tags.append("FLOW_ADVERSE")
    if "news" in text or _score_value((entry.get("factors") or {}).get("newsScore")) < -0.15:
        tags.append("NEWS_ADVERSE")
    if "smart" in text or _score_value((entry.get("factors") or {}).get("smartMoneyScore")) < -0.15:
        tags.append("SMART_MONEY_ADVERSE")
    if "kronos" in text or _score_value((entry.get("factors") or {}).get("kronosScore")) < -0.15:
        tags.append("KRONOS_ADVERSE")
    if _score_value(entry.get("dataCoverageScore")) < 0.7 or _score_value(entry.get("professionalScore")) < 0.65:
        tags.append("LOW_COVERAGE_LOSS")
    if _score_value(entry.get("executionRiskScore")) > 0.6 or abs(mae) > 1.0:
        tags.append("HIGH_EXECUTION_RISK")
    return _unique(tags) or ["UNTAGGED_LOSS"]


def _exit_close_move(row: Dict[str, Any], entry: Dict[str, Any], profit_r: float) -> Dict[str, Any]:
    raw_pips = _history_price_move_pips(row)
    side = str(entry.get("side") or "").upper()
    favorable_pips = -raw_pips if side == "SHORT" else raw_pips if side == "LONG" else raw_pips
    risk_plan = entry.get("riskPlan") if isinstance(entry.get("riskPlan"), dict) else {}
    stop_pips = abs(safe_float(risk_plan.get("stopLossPriceMove"), 0))
    target_pips = abs(safe_float(risk_plan.get("takeProfitPriceMove"), 0))
    source = "history_price_move_bridge"
    close_move_available = abs(raw_pips) > 0.0
    if close_move_available:
        close_move_r = round(favorable_pips / stop_pips, 6) if stop_pips > 0 else None
        target_capture = round(favorable_pips / target_pips, 6) if target_pips > 0 else None
    elif abs(profit_r) > 0.0:
        source = "profit_r_bridge"
        close_move_available = True
        close_move_r = round(profit_r, 6)
        favorable_pips = round(profit_r * stop_pips, 4) if stop_pips > 0 else 0.0
        target_capture = round(favorable_pips / target_pips, 6) if target_pips > 0 and favorable_pips else None
    else:
        close_move_r = None
        target_capture = None
    return {
        "schema": "quantgod.close_move_exit_bridge.v1",
        "available": close_move_available,
        "source": source,
        "rawPriceMovePips": round(raw_pips, 4),
        "favorablePriceMovePips": round(favorable_pips, 4),
        "closeMoveR": close_move_r,
        "profitR": round(profit_r, 6),
        "plannedStopPips": round(stop_pips, 4),
        "plannedTakeProfitPips": round(target_pips, 4),
        "targetCaptureRatio": target_capture,
        "reasonZh": (
            "真实 MFE/MAE 缺失时，使用开/平价格移动或 profitR 做保守离场桥接；这不是盘中最大有利/不利波动。"
            if close_move_available
            else "缺少可用开/平价格移动，离场效率只能等待真实 MFE/MAE 采集。"
        ),
    }


def _exit_movement_quality(
    entry: Dict[str, Any],
    mfe_r: float,
    mae_r: float,
    close_move: Dict[str, Any],
) -> str:
    if mfe_r > 0.0 or mae_r > 0.0:
        return "RAW_MFE_MAE"
    if close_move.get("available") and str(entry.get("contextQuality") or "").upper() == "BRIDGED_HISTORY_CONTEXT":
        return "BRIDGED_CLOSE_MOVE_ONLY"
    if close_move.get("available"):
        return "CLOSE_MOVE_ONLY"
    return "MFE_MAE_MISSING"


def _rolling_review(trades: List[Dict[str, Any]], previous: Dict[str, Any], *, now_iso: str) -> Dict[str, Any]:
    exits = _valid_review_exits(trades)
    sample_count = len(exits)
    profits = [float(row.get("profitR") or 0.0) for row in exits]
    wins = [value for value in profits if value > 0]
    losses = [row for row in exits if float(row.get("profitR") or 0.0) < 0]
    by_direction = _group_performance(exits, "side")
    by_symbol = _group_performance(exits, "symbol")
    loss_tags = Counter(tag for row in losses for tag in row.get("lossTags", []))
    exit_types = Counter(str(row.get("exitType") or "UNKNOWN") for row in losses)
    data_gaps = _data_gap_counts(trades, losses)
    exit_efficiency = _exit_efficiency(exits)
    fine_factor_health = _fine_factor_memory_health(trades, exits)
    memory_completeness = _entry_memory_completeness(trades)
    cooldown = _cooldown_state(previous, now_iso)
    eligible = sample_count >= MIN_REVIEW_SAMPLES and not cooldown["active"]
    suggestions = _review_suggestions(loss_tags, by_symbol, by_direction, data_gaps, fine_factor_health, memory_completeness, sample_count)
    status = "READY_TO_ADJUST" if eligible and suggestions else "OBSERVE_ONLY"
    if sample_count < MIN_REVIEW_SAMPLES:
        status = "INSUFFICIENT_SAMPLES"
    elif cooldown["active"]:
        status = "COOLDOWN_ACTIVE"
    return {
        "schema": "quantgod.rolling_trade_review.v1",
        "status": status,
        "sampleCount": sample_count,
        "windowSize": ROLLING_WINDOW_TRADES,
        "eligibleToAdjust": eligible,
        "cooldown": cooldown,
        "totalProfitR": round(sum(profits), 6),
        "winRate": round(len(wins) / sample_count, 4) if sample_count else 0.0,
        "longShortPerformance": by_direction,
        "symbolPerformance": by_symbol,
        "worstSymbols": _worst_groups(by_symbol),
        "failureExitTypes": _counter_rows(exit_types),
        "commonLossPatterns": _counter_rows(loss_tags),
        "commonDataGaps": _counter_rows(data_gaps),
        "fineFactorMemoryHealth": fine_factor_health,
        "entryMemoryCompleteness": memory_completeness,
        "exitEfficiency": exit_efficiency,
        "tpSlOptimizationHints": exit_efficiency.get("hints", []),
        "suggestions": suggestions,
    }


def _entry_feedback_policy(trades: List[Dict[str, Any]], rolling: Dict[str, Any]) -> Dict[str, Any]:
    exits = _valid_review_exits(trades)
    entries = {str(trade["tradeId"]): trade["entryMemory"] for trade in trades}
    symbol_penalties = _penalties_for_group(exits, "symbol")
    direction_penalties = _penalties_for_group(exits, "side")
    factor_penalties = _factor_penalties(exits)
    data_gap_penalties = _data_gap_penalties(exits, entries)
    fine_factor_penalties = _fine_factor_penalties(trades, exits)
    loss_streak = _loss_streak(exits)
    win_rate = float(rolling.get("winRate") or 0)
    sample_count = int(rolling.get("sampleCount") or 0)
    total_profit = float(rolling.get("totalProfitR") or 0)
    exit_efficiency = rolling.get("exitEfficiency") if isinstance(rolling.get("exitEfficiency"), dict) else {}
    defense = sample_count >= MIN_REVIEW_SAMPLES and (loss_streak >= 3 or win_rate < 0.45 or total_profit < 0)
    aggression = sample_count >= MIN_REVIEW_SAMPLES and win_rate >= 0.58 and total_profit > 0 and loss_streak == 0
    return {
        "schema": "quantgod.entry_feedback_policy.v1",
        "status": "DEFENSE_MODE" if defense else "AGGRESSION_ALLOWED" if aggression else "MEMORY_ACTIVE_OBSERVE",
        "sampleCount": sample_count,
        "lossStreak": loss_streak,
        "symbolPenalties": symbol_penalties,
        "directionPenalties": direction_penalties,
        "dataGapPenalties": data_gap_penalties,
        "fineFactorPenalties": fine_factor_penalties,
        "adverseFactorPenalties": _merge_factor_penalties(factor_penalties, fine_factor_penalties),
        "defenseMode": {
            "enabled": defense,
            "riskMultiplierCap": 0.45 if defense else 1.0,
            "entryScoreBufferAdd": 0.12 if defense else 0.0,
            "reasonZh": "连续亏损/胜率/总收益触发防守，后续候选只做扣分和观察。" if defense else "未触发防守模式。",
        },
        "aggressionControl": {
            "manualAggressiveTierPreserved": True,
            "memoryCanIncreaseAggression": aggression,
            "reasonZh": "表现稳定才允许提高进攻建议；手动 aggressive 档位仍由用户控制。",
        },
        "tpSlGuidance": _tp_sl_guidance(
            _merge_factor_penalties(factor_penalties, fine_factor_penalties),
            data_gap_penalties,
            loss_streak,
            exit_efficiency,
        ),
        "candidatePenaltyRules": _candidate_penalty_rules(
            symbol_penalties,
            direction_penalties,
            data_gap_penalties,
            _merge_factor_penalties(factor_penalties, fine_factor_penalties),
        ),
        "safety": dict(SAFETY),
    }


def _penalties_for_group(exits: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in exits:
        if key == "side" and str(row.get(key) or "").upper() not in {"LONG", "SHORT"}:
            continue
        grouped[str(row.get(key) or "UNKNOWN")].append(row)
    results: List[Dict[str, Any]] = []
    for name, rows in grouped.items():
        if len(rows) < 3:
            continue
        profits = [float(row.get("profitR") or 0.0) for row in rows]
        avg_r = mean(profits)
        win_rate = sum(1 for value in profits if value > 0) / len(profits)
        if avg_r < 0 or win_rate < 0.45:
            results.append(
                {
                    key: name,
                    "sampleCount": len(rows),
                    "avgProfitR": round(avg_r, 6),
                    "winRate": round(win_rate, 4),
                    "penalty": round(min(0.25, max(0.05, abs(avg_r) * 0.08 + (0.45 - win_rate) * 0.2)), 4),
                    "reasonZh": f"{name} 近期拖累，下一轮候选扣分。",
                }
            )
    return sorted(results, key=lambda item: (-float(item.get("penalty") or 0), str(item.get(key) or "")))[:8]


def _valid_review_exits(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    exits: List[Dict[str, Any]] = []
    for trade in trades:
        row = trade.get("exitMemory") if isinstance(trade.get("exitMemory"), dict) else None
        if not row:
            continue
        side = str(row.get("side") or "").upper()
        if side not in {"LONG", "SHORT"}:
            continue
        profit = float(row.get("profitR") or 0.0)
        if abs(profit) <= 0.0000001 and str(row.get("exitType") or "") == "FLAT_EXIT":
            continue
        exits.append(row)
    return exits


def _review_trade_window(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    review_trades: List[Dict[str, Any]] = []
    for trade in trades:
        row = trade.get("exitMemory") if isinstance(trade.get("exitMemory"), dict) else None
        if not row:
            continue
        side = str(row.get("side") or "").upper()
        if side not in {"LONG", "SHORT"}:
            continue
        profit = float(row.get("profitR") or 0.0)
        if abs(profit) <= 0.0000001 and str(row.get("exitType") or "") == "FLAT_EXIT":
            continue
        review_trades.append(trade)
    return review_trades[-ROLLING_WINDOW_TRADES:]


def _factor_penalties(exits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    losses = [row for row in exits if float(row.get("profitR") or 0.0) < 0]
    counts = Counter(tag for row in losses for tag in row.get("lossTags", []))
    mapping = {
        "FLOW_ADVERSE": "fundFlow",
        "NEWS_ADVERSE": "news",
        "SMART_MONEY_ADVERSE": "smartMoney",
        "KRONOS_ADVERSE": "kronos",
        "FAKE_BREAKOUT": "breakoutConfirmation",
        "CHASE_PULLBACK": "entryTiming",
        "HIGH_EXECUTION_RISK": "executionRisk",
    }
    penalties: List[Dict[str, Any]] = []
    for tag, factor in mapping.items():
        count = counts.get(tag, 0)
        if count >= 2:
            penalties.append(
                {
                    "factor": factor,
                    "lossTag": tag,
                    "lossCount": count,
                    "penalty": round(min(0.28, 0.06 + count * 0.035), 4),
                    "reasonZh": f"{factor} 逆风亏损重复出现，同类信号降权。",
                }
            )
    return penalties


def _fine_factor_memory_health(trades: List[Dict[str, Any]], exits: List[Dict[str, Any]]) -> Dict[str, Any]:
    entries = {str(trade["tradeId"]): trade["entryMemory"] for trade in trades}
    losses = [row for row in exits if float(row.get("profitR") or 0.0) < 0]
    factor_rows: List[Dict[str, Any]] = []
    for factor, spec in FINE_FACTOR_DEFS.items():
        present_values: List[float] = []
        raw_present_values: List[float] = []
        loss_values: List[float] = []
        loss_missing = 0
        loss_raw_missing = 0
        loss_adverse = 0
        context_limited = 0
        for row in exits:
            entry = entries.get(str(row.get("tradeId"))) or {}
            value = _entry_factor_value(entry, spec)
            if value is not None:
                present_values.append(value)
                if not _entry_is_proxy(entry) and not _entry_is_context_missing(entry):
                    raw_present_values.append(value)
                else:
                    context_limited += 1
        for row in losses:
            entry = entries.get(str(row.get("tradeId"))) or {}
            value = _entry_factor_value(entry, spec)
            if value is None:
                loss_missing += 1
                loss_raw_missing += 1
                continue
            if not _entry_factor_is_raw(entry):
                loss_raw_missing += 1
            loss_values.append(value)
            if _factor_is_adverse(value, spec):
                loss_adverse += 1
        sample_count = len(exits)
        factor_rows.append(
            {
                "factor": factor,
                "field": spec["field"],
                "sampleCount": sample_count,
                "lossCount": len(losses),
                "presentCount": len(present_values),
                "rawPresentCount": len(raw_present_values),
                "contextLimitedPresentCount": context_limited,
                "coverageRatio": round(len(present_values) / sample_count, 4) if sample_count else 0.0,
                "rawCoverageRatio": round(len(raw_present_values) / sample_count, 4) if sample_count else 0.0,
                "lossMissingCount": loss_missing,
                "lossMissingRatio": round(loss_missing / len(losses), 4) if losses else 0.0,
                "lossRawMissingCount": loss_raw_missing,
                "lossRawMissingRatio": round(loss_raw_missing / len(losses), 4) if losses else 0.0,
                "lossAdverseCount": loss_adverse,
                "lossAdverseRatio": round(loss_adverse / len(losses), 4) if losses else 0.0,
                "avgValue": round(mean(present_values), 6) if present_values else None,
                "avgLossValue": round(mean(loss_values), 6) if loss_values else None,
                "adverseRule": f"{spec['field']} {'>' if spec['adverse'] == 'gt' else '<'} {spec['threshold']}",
            }
        )
    top_missing = sorted(factor_rows, key=lambda row: (-int(row["lossMissingCount"]), str(row["factor"])))[:8]
    top_raw_missing = sorted(factor_rows, key=lambda row: (-int(row["lossRawMissingCount"]), str(row["factor"])))[:8]
    top_adverse = sorted(factor_rows, key=lambda row: (-int(row["lossAdverseCount"]), str(row["factor"])))[:8]
    return {
        "schema": "quantgod.fine_factor_memory_health.v1",
        "sampleCount": len(exits),
        "lossCount": len(losses),
        "factors": factor_rows,
        "topMissingInLosses": [row for row in top_missing if int(row["lossMissingCount"]) > 0],
        "topRawMissingInLosses": [row for row in top_raw_missing if int(row["lossRawMissingCount"]) > 0],
        "topAdverseInLosses": [row for row in top_adverse if int(row["lossAdverseCount"]) > 0],
        "reasonZh": "逐因子统计亏损单里的缺失和逆风，用于下一轮候选扣分与采集优先级排序。",
    }


def _fine_factor_penalties(trades: List[Dict[str, Any]], exits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    health = _fine_factor_memory_health(trades, exits)
    penalties: List[Dict[str, Any]] = []
    for row in health.get("factors", []):
        adverse_count = int(row.get("lossAdverseCount") or 0)
        missing_count = int(row.get("lossMissingCount") or 0)
        raw_missing_count = int(row.get("lossRawMissingCount") or 0)
        factor = str(row.get("factor") or "")
        if adverse_count >= 2:
            penalties.append(
                {
                    "factor": factor,
                    "lossTag": f"FINE_FACTOR_{factor}_ADVERSE",
                    "lossCount": adverse_count,
                    "penalty": round(min(0.22, 0.05 + adverse_count * 0.03), 4),
                    "reasonZh": f"{factor} 细因子在亏损单中重复逆风，同类信号降权。",
                }
            )
        if missing_count >= 2:
            penalties.append(
                {
                    "factor": factor,
                    "dataGap": f"missingFactor:{factor}",
                    "lossTag": f"FINE_FACTOR_{factor}_MISSING",
                    "lossCount": missing_count,
                    "penalty": round(min(0.14, 0.04 + missing_count * 0.02), 4),
                    "reasonZh": f"{factor} 细因子在亏损单中反复缺失，信息不完整的同类信号降权。",
                }
            )
        elif raw_missing_count >= 2:
            penalties.append(
                {
                    "factor": factor,
                    "dataGap": f"missingFactor:{factor}",
                    "lossTag": f"FINE_FACTOR_{factor}_RAW_MISSING",
                    "lossCount": raw_missing_count,
                    "penalty": round(min(0.08, 0.025 + raw_missing_count * 0.006), 4),
                    "reasonZh": f"{factor} 细因子在亏损单中缺少原始开仓快照，桥接值只可研究，同类信号小幅降权。",
                }
            )
    return sorted(penalties, key=lambda item: (-float(item.get("penalty") or 0), str(item.get("factor") or "")))[:12]


def _merge_factor_penalties(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[tuple[str, str], Dict[str, Any]] = {}
    for group in groups:
        for row in group:
            factor = str(row.get("factor") or "")
            kind = str(row.get("dataGap") or row.get("lossTag") or factor)
            key = (factor, kind)
            existing = merged.get(key)
            if not existing or float(row.get("penalty") or 0) > float(existing.get("penalty") or 0):
                merged[key] = row
    return sorted(merged.values(), key=lambda item: (-float(item.get("penalty") or 0), str(item.get("factor") or "")))[:16]


def _entry_factor_value(entry: Dict[str, Any], spec: Dict[str, Any]) -> float | None:
    if spec.get("category") == "factors":
        factors = entry.get("factors") if isinstance(entry.get("factors"), dict) else {}
        value = factors.get(str(spec.get("field") or ""))
    else:
        value = entry.get(str(spec.get("field") or ""))
    if value in (None, ""):
        return None
    return _score_value(value)


def _entry_factor_is_raw(entry: Dict[str, Any]) -> bool:
    return not _entry_is_proxy(entry) and not _entry_is_context_missing(entry)


def _factor_is_adverse(value: float, spec: Dict[str, Any]) -> bool:
    if spec.get("adverse") == "none":
        return False
    threshold = float(spec.get("threshold") or 0.0)
    if spec.get("adverse") == "gt":
        return value > threshold
    return value < threshold


def _data_gap_penalties(exits: List[Dict[str, Any]], entries: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    penalties: List[Dict[str, Any]] = []
    low_coverage_losses = 0
    low_professional_losses = 0
    for row in exits:
        if float(row.get("profitR") or 0.0) >= 0:
            continue
        entry = entries.get(str(row.get("tradeId"))) or {}
        if _score_value(entry.get("dataCoverageScore")) < 0.7:
            low_coverage_losses += 1
        if _score_value(entry.get("professionalScore")) < 0.65:
            low_professional_losses += 1
    if low_coverage_losses >= 2:
        penalties.append(
            {
                "gap": "dataCoverage",
                "lossCount": low_coverage_losses,
                "penalty": 0.12,
                "reasonZh": "低覆盖亏损偏多，提高覆盖门槛。",
            }
        )
    if low_professional_losses >= 2:
        penalties.append(
            {
                "gap": "professionalScore",
                "lossCount": low_professional_losses,
                "penalty": 0.1,
                "reasonZh": "专业评分不足的亏损偏多，降低弱信号权重。",
            }
        )
    return penalties


def _tp_sl_guidance(
    factor_penalties: List[Dict[str, Any]],
    data_gap_penalties: List[Dict[str, Any]],
    loss_streak: int,
    exit_efficiency: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    exit_efficiency = exit_efficiency or {}
    factors = {str(row.get("lossTag") or row.get("factor")) for row in factor_penalties}
    actions: List[str] = []
    if "CHASE_PULLBACK" in factors or "FAKE_BREAKOUT" in factors:
        actions.append("提高入场缓冲，TP1 前不追价；假突破重复时缩短无效突破持仓时间。")
    if "HIGH_EXECUTION_RISK" in factors:
        actions.append("高执行风险期间降低仓位缩放并收紧最大滑点/点差门槛。")
    if data_gap_penalties:
        actions.append("低覆盖信号只允许观察或更小风险，避免用宽止损掩盖数据缺口。")
    if int(exit_efficiency.get("profitGivebackCount") or 0) >= 2:
        actions.append("盈利回吐偏多，提高分批止盈优先级，并收紧 MFE 回吐追踪比例。")
    if int(exit_efficiency.get("lowMfeCaptureCount") or 0) >= 2:
        actions.append("MFE 捕获率偏低，TP1 应更早落袋，后续仓位用更紧 trailing 管理。")
    if int(exit_efficiency.get("recoveredSmallWinCount") or 0) >= 2:
        actions.append("扛单恢复后多为小赚，恢复到微利区先降仓或直接小赚离场。")
    if int(exit_efficiency.get("heldWinnerWellCount") or 0) >= 3:
        actions.append("高捕获盈利样本足够，强趋势且覆盖完整时允许 runner 多拿一段。")
    if loss_streak >= 3:
        actions.append("连续亏损后进入防守，止损保持纪律，止盈优先分批兑现。")
    return {
        "mode": "DEFENSIVE_TP_SL_REVIEW" if actions else "KEEP_CURRENT_AND_OBSERVE",
        "actionsZh": actions or ["样本未显示明确 TP/SL 偏差，继续积累。"],
        "exitEfficiency": exit_efficiency,
    }


def _candidate_penalty_rules(
    symbol_penalties: List[Dict[str, Any]],
    direction_penalties: List[Dict[str, Any]],
    data_gap_penalties: List[Dict[str, Any]],
    factor_penalties: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    for row in symbol_penalties:
        rules.append({"match": {"symbol": row.get("symbol")}, "penalty": row.get("penalty"), "reasonZh": row.get("reasonZh")})
    for row in direction_penalties:
        rules.append({"match": {"side": row.get("side")}, "penalty": row.get("penalty"), "reasonZh": row.get("reasonZh")})
    for row in data_gap_penalties:
        rules.append({"match": {"dataGap": row.get("gap")}, "penalty": row.get("penalty"), "reasonZh": row.get("reasonZh")})
    for row in factor_penalties:
        if row.get("dataGap"):
            rules.append({"match": {"dataGap": row.get("dataGap")}, "penalty": row.get("penalty"), "reasonZh": row.get("reasonZh")})
        else:
            rules.append({"match": {"adverseFactor": row.get("factor")}, "penalty": row.get("penalty"), "reasonZh": row.get("reasonZh")})
    return rules[:16]


def _group_performance(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "UNKNOWN")].append(float(row.get("profitR") or 0.0))
    output: List[Dict[str, Any]] = []
    for name, values in grouped.items():
        output.append(
            {
                key: name,
                "sampleCount": len(values),
                "totalProfitR": round(sum(values), 6),
                "avgProfitR": round(mean(values), 6),
                "winRate": round(sum(1 for value in values if value > 0) / len(values), 4) if values else 0,
            }
        )
    return sorted(output, key=lambda item: (float(item.get("totalProfitR") or 0), str(item.get(key) or "")))


def _data_gap_counts(trades: List[Dict[str, Any]], losses: List[Dict[str, Any]]) -> Counter:
    loss_ids = {str(row.get("tradeId")) for row in losses}
    counts: Counter = Counter()
    for trade in trades:
        if str(trade.get("tradeId")) not in loss_ids:
            continue
        entry = trade.get("entryMemory") or {}
        if _entry_is_proxy(entry):
            counts["SHADOW_PROXY_CONTEXT"] += 1
        if _entry_is_context_missing(entry):
            counts["HISTORY_CONTEXT_MISSING"] += 1
        if _score_value(entry.get("dataCoverageScore")) < 0.7:
            counts["LOW_DATA_COVERAGE"] += 1
        if _score_value(entry.get("professionalScore")) < 0.65:
            counts["LOW_PROFESSIONAL_SCORE"] += 1
        factors = entry.get("factors") if isinstance(entry.get("factors"), dict) else {}
        for name in ("sentimentScore", "openInterestChange", "newsScore", "smartMoneyScore", "predictionMarketScore", "kronosScore"):
            if factors.get(name) in (None, ""):
                counts[f"MISSING_{name}"] += 1
        for factor, spec in FINE_FACTOR_DEFS.items():
            if _entry_factor_value(entry, spec) is None:
                counts[f"missingFactor:{factor}"] += 1
    return counts


def _entry_memory_completeness(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    entries = [
        trade.get("entryMemory")
        for trade in trades
        if isinstance(trade.get("entryMemory"), dict)
    ]
    if not entries:
        return {
            "schema": "quantgod.entry_memory_completeness.v1",
            "sampleCount": 0,
            "rawSampleCount": 0,
            "contextMissingSampleCount": 0,
            "contextMissingSampleRatio": 0.0,
            "proxySampleCount": 0,
            "usableRawSampleCount": 0,
            "overallCoverageRatio": 0.0,
            "rawCoverageRatio": 0.0,
            "proxyCoverageRatio": 0.0,
            "categories": [],
            "topMissingFields": [],
            "lowCoverageFields": [],
            "status": "NO_ENTRY_MEMORY",
        }
    proxy_entries = [entry for entry in entries if _entry_is_proxy(entry)]
    context_missing_entries = [entry for entry in entries if _entry_is_context_missing(entry)]
    raw_entries = [
        entry
        for entry in entries
        if not _entry_is_proxy(entry) and not _entry_is_context_missing(entry)
    ]
    field_rows: List[Dict[str, Any]] = []
    category_rows: List[Dict[str, Any]] = []
    total_available = 0
    total_possible = 0
    raw_available_total = 0
    raw_possible_total = 0
    proxy_available_total = 0
    proxy_possible_total = 0
    for category, fields in ENTRY_COMPLETENESS_FIELDS.items():
        category_available = 0
        category_possible = len(fields) * len(entries)
        category_raw_available = 0
        category_raw_possible = len(fields) * len(raw_entries)
        category_proxy_available = 0
        category_proxy_possible = len(fields) * len(proxy_entries)
        for field in fields:
            available = sum(1 for entry in entries if _entry_field_present(entry, category, field))
            raw_available = sum(1 for entry in raw_entries if _entry_field_present(entry, category, field))
            proxy_available = sum(1 for entry in proxy_entries if _entry_field_present(entry, category, field))
            missing = len(entries) - available
            ratio = round(available / len(entries), 4) if entries else 0.0
            raw_ratio = round(raw_available / len(raw_entries), 4) if raw_entries else 0.0
            proxy_ratio = round(proxy_available / len(proxy_entries), 4) if proxy_entries else 0.0
            category_available += available
            category_raw_available += raw_available
            category_proxy_available += proxy_available
            field_rows.append(
                {
                    "category": category,
                    "field": field,
                    "availableCount": available,
                    "rawAvailableCount": raw_available,
                    "proxyAvailableCount": proxy_available,
                    "missingCount": missing,
                    "coverageRatio": ratio,
                    "rawCoverageRatio": raw_ratio,
                    "proxyCoverageRatio": proxy_ratio,
                }
            )
        total_available += category_available
        total_possible += category_possible
        raw_available_total += category_raw_available
        raw_possible_total += category_raw_possible
        proxy_available_total += category_proxy_available
        proxy_possible_total += category_proxy_possible
        category_rows.append(
            {
                "category": category,
                "fieldCount": len(fields),
                "availableCount": category_available,
                "rawAvailableCount": category_raw_available,
                "proxyAvailableCount": category_proxy_available,
                "missingCount": category_possible - category_available,
                "coverageRatio": round(category_available / category_possible, 4) if category_possible else 0.0,
                "rawCoverageRatio": round(category_raw_available / category_raw_possible, 4) if category_raw_possible else 0.0,
                "proxyCoverageRatio": round(category_proxy_available / category_proxy_possible, 4) if category_proxy_possible else 0.0,
            }
        )
    low_coverage = [
        row
        for row in field_rows
        if row["coverageRatio"] < 0.7
    ]
    top_missing = sorted(field_rows, key=lambda row: (-int(row["missingCount"]), str(row["category"]), str(row["field"])))[:12]
    overall = round(total_available / total_possible, 4) if total_possible else 0.0
    raw_overall = round(raw_available_total / raw_possible_total, 4) if raw_possible_total else 0.0
    proxy_overall = round(proxy_available_total / proxy_possible_total, 4) if proxy_possible_total else 0.0
    proxy_ratio = round(len(proxy_entries) / len(entries), 4) if entries else 0.0
    context_missing_ratio = round(len(context_missing_entries) / len(entries), 4) if entries else 0.0
    status = "OK"
    if raw_overall < 0.7:
        status = "LOW_RAW_COVERAGE"
    if context_missing_ratio > 0.25:
        status = "LOW_CONTEXT_QUALITY"
    if overall < 0.7 or low_coverage:
        status = "LOW_COVERAGE"
    raw_pass = raw_overall >= 0.7
    proxy_pass = proxy_ratio <= 0.25
    context_missing_pass = context_missing_ratio <= 0.25
    return {
        "schema": "quantgod.entry_memory_completeness.v1",
        "sampleCount": len(entries),
        "rawSampleCount": len(raw_entries),
        "usableRawSampleCount": len(raw_entries),
        "contextMissingSampleCount": len(context_missing_entries),
        "contextMissingSampleRatio": context_missing_ratio,
        "proxySampleCount": len(proxy_entries),
        "proxySampleRatio": proxy_ratio,
        "overallCoverageRatio": overall,
        "rawCoverageRatio": raw_overall,
        "proxyCoverageRatio": proxy_overall,
        "categories": category_rows,
        "topMissingFields": top_missing,
        "lowCoverageFields": low_coverage[:16],
        "status": status,
        "qualityGate": {
            "rawCoveragePass": raw_pass,
            "proxySampleRatioPass": proxy_pass,
            "contextMissingRatioPass": context_missing_pass,
            "reasonZh": (
                "真实采集覆盖率达标，代理样本和历史缺上下文样本占比受控。"
                if raw_pass and proxy_pass and context_missing_pass
                else "代理样本和历史裸盈亏样本可用于研究/降级，但不能作为升实盘/升王牌的完整证据。"
            ),
        },
    }


def _entry_is_proxy(entry: Dict[str, Any]) -> bool:
    return str(entry.get("contextQuality") or "").upper() == "SHADOW_PROXY"


def _entry_is_context_missing(entry: Dict[str, Any]) -> bool:
    return str(entry.get("contextQuality") or "").upper() in {
        "HISTORY_CONTEXT_MISSING",
        "ENTRY_CONTEXT_MISSING",
        "BRIDGED_HISTORY_CONTEXT",
    }


def _entry_context_quality(row: Dict[str, Any]) -> str:
    explicit = _value(row, "contextQuality", default="")
    if explicit:
        return str(explicit)
    if _has_structured_entry_context(row):
        return "RAW"
    source_text = " ".join(
        str(value)
        for value in (
            first_value(row, "_source", "source", "sourceKind", "sourceTier", default=""),
            first_value(row, "eventType", "type", "event", default=""),
        )
        if value not in (None, "")
    ).lower()
    if any(token in source_text for token in ("liveexecutionfeedback", "close_history", "order_close", "history")):
        return "HISTORY_CONTEXT_MISSING"
    return "RAW"


def _entry_context_quality_reason(row: Dict[str, Any], quality: str) -> str:
    explicit = _value(row, "contextQualityReasonZh", default="")
    if explicit:
        return str(explicit)
    if quality == "HISTORY_CONTEXT_MISSING":
        return (
            "历史平仓/执行反馈只有结果字段，缺少入场评分、因子、EV 和 TP/SL 计划；"
            "只能用于保守复盘/降级，不能作为升王牌证据。"
        )
    if quality == "BRIDGED_HISTORY_CONTEXT":
        return (
            "历史平仓/执行反馈已桥接部分入场上下文，但不是原始开仓快照；"
            "只能用于复盘/降级，不能作为升王牌证据。"
        )
    if quality == "SHADOW_PROXY":
        return "代理上下文只可辅助研究，不能作为升实盘/升王牌的完整证据。"
    return ""


def _row_with_bridged_history_context(row: Dict[str, Any]) -> Dict[str, Any]:
    if _has_structured_entry_context(row):
        return row
    if _entry_context_quality(row) != "HISTORY_CONTEXT_MISSING":
        return row
    bridged = _bridged_history_entry_context(row)
    if not bridged:
        return row
    wrapped = dict(row)
    wrapped["entryContext"] = bridged
    return wrapped


def _bridged_history_entry_context(row: Dict[str, Any]) -> Dict[str, Any]:
    profit_r = safe_float(first_value(row, "profitR", "ProfitR", "scoreR", "r", default=0), 0)
    mfe_r = max(0.0, safe_float(first_value(row, "mfeR", "MfeR", "mfe", "maxFavorableR", default=0), 0))
    mae_r = abs(safe_float(first_value(row, "maeR", "MaeR", "mae", "maxAdverseR", default=0), 0))
    price_move_pips = _history_price_move_pips(row)
    duration = _duration_minutes(
        first_value(row, "entryTime", "entrySignalTime", "openTime", "timestamp", "time", "createdAt"),
        first_value(row, "exitTime", "closeTime", "fillTime", "timestamp", "time", "createdAt"),
    )
    entry_regime = str(first_value(row, "entryRegime", "EntryRegime", "regime", "Regime", default="") or "")
    exit_regime = str(first_value(row, "exitRegime", "ExitRegime", default="") or "")
    comment = str(first_value(row, "comment", "Comment", "exitReason", "ExitReason", "reason", default="") or "")
    return {
        "contextQuality": "BRIDGED_HISTORY_CONTEXT",
        "contextQualityReasonZh": (
            "历史平仓/执行反馈缺少原始入场快照；case memory 已桥接基础上下文、regime、"
            "MFE/MAE 和保守 TP/SL 估算，只可用于复盘/降级，不能作为升王牌证据。"
        ),
        "bridgeSource": "case_memory.long_term_memory",
        "entryTime": first_value(row, "entryTime", "entrySignalTime", "openTime", "timestamp", "time", "createdAt"),
        "symbol": first_value(row, "symbol", "Symbol", "instrument", default="UNKNOWN"),
        "side": first_value(row, "side", "Side", "direction", "Direction", "action", "type"),
        "strategyVersion": first_value(row, "strategyVersion", "strategyId", "strategy", "comment", default="UNKNOWN"),
        "leverage": safe_float(first_value(row, "leverage", "Leverage", default=0), 0),
        "marginUsd": safe_float(first_value(row, "margin", "Margin", "marginUsd", "MarginUsd", default=0), 0),
        "notionalUsd": safe_float(first_value(row, "notional", "Notional", "notionalUsd", "NotionalUsd", default=0), 0),
        "candidateSource": first_value(row, "candidateSource", "source", "_source", default="UNKNOWN"),
        "reasons": _history_reasons(row, entry_regime, exit_regime, comment),
        "scores": {
            "totalScore": _history_score_or_default(row, 0.50, "compositeScore", "totalScore", "score", "signalScore"),
            "dataCoverage": _history_score_or_default(row, 0.55, "dataCoverageScore", "dataCoverage", "coverageScore"),
            "proScore": _history_score_or_default(row, 0.50, "professionalScore", "proScore"),
            "marketQuality": _history_score_or_default(row, _history_regime_quality(entry_regime, exit_regime), "marketQualityScore", "marketQuality"),
            "entryTiming": _history_score_or_default(row, _history_entry_timing(profit_r, mfe_r, mae_r), "entryTimingScore", "entryTiming"),
            "fundFlow": _history_score_or_default(row, 0.0, "fundFlowScore", "fundFlow"),
            "executionRisk": _history_score_or_default(row, _history_execution_risk(row, mae_r), "executionRiskScore", "executionRisk"),
            "resonanceCount": safe_float(first_value(row, "resonanceCount", "resonance", default=1), 1),
        },
        "factors": {
            "atrPips": _history_score_or_default(row, 0.0, "atr", "ATR", "atrPips"),
            "trend": _history_trend_score_from_regime(entry_regime, first_value(row, "side", "Side", "direction", "Direction")),
            "sentiment": _history_score_or_default(row, 0.0, "sentimentScore", "sentiment"),
            "oiChange": _history_score_or_default(row, 0.0, "openInterestChange", "oiChange", "openInterest"),
            "news": _history_score_or_default(row, 0.0, "newsScore", "news"),
            "smartMoney": _history_score_or_default(row, 0.0, "smartMoneyScore", "smartMoney"),
            "predictionMarket": _history_score_or_default(row, 0.0, "predictionMarketScore", "predictionMarket"),
            "kronos": _history_score_or_default(row, 0.0, "kronosScore", "kronos"),
            "entryRegime": entry_regime,
            "exitRegime": exit_regime,
        },
        "estimates": {
            "ev": _history_score_or_default(row, profit_r, "estimatedEV", "ev", "expectedValue"),
            "winProbability": _history_score_or_default(
                row,
                0.55 if profit_r > 0 else 0.45 if profit_r < 0 else 0.50,
                "estimatedWinProbability",
                "winProbability",
                "winProb",
            ),
            "riskReward": _history_score_or_default(
                row,
                _history_risk_reward(profit_r, mfe_r, mae_r),
                "estimatedRiskReward",
                "riskReward",
                "rr",
            ),
            "positionScale": _history_score_or_default(row, 0.20, "positionScaling", "positionScale", "riskMultiplier"),
        },
        "riskPlan": {
            "stopLossR": _history_score_or_default(
                row,
                max(1.0, mae_r) if mae_r else 1.0,
                "stopLossR",
                "slR",
                "initialStopR",
            ),
            "targetR": _history_score_or_default(
                row,
                max(1.2, mfe_r, abs(profit_r)) if (mfe_r or profit_r) else 1.2,
                "takeProfitR",
                "tpR",
                "targetR",
            ),
            "firstTakeProfitR": _history_score_or_default(row, 0.6, "tp1R", "firstTakeProfitR"),
            "secondTakeProfitR": _history_score_or_default(
                row,
                max(1.2, mfe_r, abs(profit_r)) if (mfe_r or profit_r) else 1.2,
                "tp2R",
                "secondTakeProfitR",
            ),
            "trailStartR": _history_score_or_default(row, 0.8, "trailingStartR", "trailStartR"),
            "givebackPct": _history_score_or_default(row, 0.45, "mfeGivebackPct", "givebackPct"),
            "timeoutMinutes": _history_score_or_default(
                row,
                float(duration or 90),
                "maxHoldMinutes",
                "timeoutMinutes",
                "durationMinutes",
            ),
            "stopLossPips": _history_score_or_default(
                row,
                abs(price_move_pips) if price_move_pips else 6.0,
                "stopLossPriceMove",
                "stopLossPips",
                "slPips",
            ),
            "takeProfitPips": _history_score_or_default(
                row,
                max(abs(price_move_pips) * 1.4, 8.0) if price_move_pips else 8.0,
                "takeProfitPriceMove",
                "takeProfitPips",
                "tpPips",
            ),
        },
        "factorAttributionSummary": _history_attribution_summary(row, entry_regime, exit_regime, profit_r, mfe_r, mae_r, comment),
    }


def _history_score_or_default(row: Dict[str, Any], bridge_value: float, *keys: str) -> float:
    value = first_value(row, *keys, default=None)
    if value not in (None, ""):
        return round(safe_float(value, 0), 6)
    return round(float(bridge_value or 0.0), 6)


def _history_price_move_pips(row: Dict[str, Any]) -> float:
    explicit = first_value(row, "priceMovePips", "PriceMovePips", "netPips", "NetPips")
    if explicit not in (None, ""):
        return round(safe_float(explicit, 0), 4)
    expected = safe_float(first_value(row, "expectedPrice", "ExpectedPrice", "openPrice", "OpenPrice", default=0), 0)
    fill = safe_float(first_value(row, "fillPrice", "FillPrice", "closePrice", "ClosePrice", default=0), 0)
    if not expected or not fill:
        return 0.0
    return round((fill - expected) / 0.01, 4)


def _history_reasons(row: Dict[str, Any], entry_regime: str, exit_regime: str, comment: str) -> List[str]:
    reasons = [
        "history_feedback_bridge",
        f"event={first_value(row, 'eventType', 'type', 'event', default='UNKNOWN') or 'UNKNOWN'}",
    ]
    if entry_regime:
        reasons.append(f"entryRegime={entry_regime}")
    if exit_regime:
        reasons.append(f"exitRegime={exit_regime}")
    if comment:
        reasons.append(comment[:80])
    return reasons


def _history_regime_quality(entry_regime: str, exit_regime: str) -> float:
    entry = entry_regime.upper()
    exit_ = exit_regime.upper()
    if entry and exit_ and entry == exit_:
        return 0.62
    if "TREND" in entry and "RANGE" in exit_:
        return 0.42
    if "RANGE" in entry and "TREND" in exit_:
        return 0.45
    return 0.50


def _history_entry_timing(profit_r: float, mfe_r: float, mae_r: float) -> float:
    if profit_r > 0 and mae_r <= 0.35:
        return 0.65
    if profit_r < 0 and mae_r >= 0.65:
        return 0.35
    if mfe_r > 0.5 and profit_r <= 0:
        return 0.42
    return 0.50


def _history_execution_risk(row: Dict[str, Any], mae_r: float) -> float:
    spread = abs(safe_float(first_value(row, "spreadAtEntry", "SpreadAtEntry", default=0), 0))
    slippage = abs(safe_float(first_value(row, "slippagePips", "SlippagePips", default=0), 0))
    risk = 0.20 + min(0.30, spread / 10.0) + min(0.30, slippage / 5.0) + min(0.20, mae_r / 5.0)
    return min(1.0, risk)


def _history_trend_score_from_regime(entry_regime: str, side: Any) -> float:
    regime = entry_regime.upper()
    direction = normalize_direction(side)
    if "TREND_DOWN" in regime:
        return -0.35 if direction == "LONG" else 0.35
    if "TREND_UP" in regime:
        return 0.35 if direction == "LONG" else -0.35
    return 0.0


def _history_risk_reward(profit_r: float, mfe_r: float, mae_r: float) -> float:
    if mae_r > 0:
        return max(0.5, min(3.0, mfe_r / mae_r))
    if profit_r > 0:
        return max(1.0, min(3.0, profit_r + 1.0))
    return 1.2


def _history_attribution_summary(
    row: Dict[str, Any],
    entry_regime: str,
    exit_regime: str,
    profit_r: float,
    mfe_r: float,
    mae_r: float,
    comment: str,
) -> str:
    pieces = [
        f"历史桥接 {first_value(row, 'strategyVersion', 'strategyId', 'strategy', default='UNKNOWN') or 'UNKNOWN'}",
        f"{normalize_direction(first_value(row, 'side', 'Side', 'direction', 'Direction')) or 'UNKNOWN'}",
        f"profitR={profit_r:.4g}",
        f"mfeR={mfe_r:.4g}",
        f"maeR={mae_r:.4g}",
    ]
    if entry_regime:
        pieces.append(f"entryRegime={entry_regime}")
    if exit_regime:
        pieces.append(f"exitRegime={exit_regime}")
    if comment:
        pieces.append(f"comment={comment[:80]}")
    return "；".join(pieces)


def _has_structured_entry_context(row: Dict[str, Any]) -> bool:
    for key in ("entryContext", "entryMemory", "signalContext"):
        value = _case_insensitive_get(row, key)
        if isinstance(value, dict):
            return True
    return False


def _entry_field_present(entry: Dict[str, Any], category: str, field: str) -> bool:
    if category == "factors":
        factors = entry.get("factors") if isinstance(entry.get("factors"), dict) else {}
        return factors.get(field) not in (None, "")
    if category == "riskPlan":
        risk_plan = entry.get("riskPlan") if isinstance(entry.get("riskPlan"), dict) else {}
        return risk_plan.get(field) not in (None, "")
    return entry.get(field) not in (None, "")


def _review_suggestions(
    loss_tags: Counter,
    symbol_perf: List[Dict[str, Any]],
    direction_perf: List[Dict[str, Any]],
    data_gaps: Counter,
    fine_factor_health: Dict[str, Any],
    memory_completeness: Dict[str, Any],
    sample_count: int,
) -> List[Dict[str, Any]]:
    if sample_count < MIN_REVIEW_SAMPLES:
        return []
    suggestions: List[Dict[str, Any]] = []
    tag_actions = {
        "LOW_COVERAGE_LOSS": "提高数据覆盖门槛，低覆盖候选降权。",
        "FAST_LOSS": "快速亏损偏多，追价过滤和入场缓冲更严。",
        "CHASE_PULLBACK": "追高回撤偏多，要求回踩或二次确认。",
        "FAKE_BREAKOUT": "假突破偏多，提高突破确认和时间过滤。",
        "HIGH_EXECUTION_RISK": "执行风险偏高，降低仓位缩放并收紧点差/滑点。",
        "KRONOS_ADVERSE": "Kronos 逆风亏损重复，下轮同类信号降权。",
        "NEWS_ADVERSE": "新闻逆风亏损重复，新闻分低时降权。",
        "FLOW_ADVERSE": "资金流逆风亏损重复，资金流分低时降权。",
        "SHADOW_PROXY_CONTEXT": "旧 shadow 代理上下文亏损偏多，先补真实采集，不把代理样本当升王牌证据。",
        "HISTORY_CONTEXT_MISSING": "历史平仓裸数据缺少入场上下文，只能用于保守降级，不能用于王牌晋级。",
    }
    for tag, action in tag_actions.items():
        if loss_tags.get(tag, 0) >= 2:
            suggestions.append({"trigger": tag, "actionZh": action, "confidence": "MEDIUM"})
    for row in symbol_perf[:3]:
        if float(row.get("totalProfitR") or 0) < 0 and int(row.get("sampleCount") or 0) >= 3:
            suggestions.append(
                {
                    "trigger": f"SYMBOL_{row.get('symbol')}",
                    "actionZh": f"{row.get('symbol')} 持续拖累，降低开仓权重。",
                    "confidence": "MEDIUM",
                }
            )
    for row in direction_perf:
        if float(row.get("totalProfitR") or 0) < 0 and int(row.get("sampleCount") or 0) >= 3:
            suggestions.append(
                {
                    "trigger": f"DIRECTION_{row.get('side')}",
                    "actionZh": f"{row.get('side')} 近期弱，降低这一侧进攻欲望。",
                    "confidence": "MEDIUM",
                }
            )
    for row in memory_completeness.get("lowCoverageFields", [])[:4]:
        field = row.get("field")
        category = row.get("category")
        ratio = row.get("coverageRatio")
        suggestions.append(
            {
                "trigger": f"LOW_FIELD_COVERAGE_{category}_{field}",
                "actionZh": f"{category}.{field} 覆盖率仅 {ratio}，先补采集/回填，再允许同类信号加权。",
                "confidence": "MEDIUM",
            }
        )
    quality_gate = memory_completeness.get("qualityGate") if isinstance(memory_completeness.get("qualityGate"), dict) else {}
    if not quality_gate.get("rawCoveragePass", True):
        suggestions.append(
            {
                "trigger": "LOW_RAW_ENTRY_MEMORY_COVERAGE",
                "actionZh": "真实采集字段覆盖不足，SHADOW_PROXY 只能辅助研究，禁止把它当作升实盘证据。",
                "confidence": "HIGH",
            }
        )
    if not quality_gate.get("proxySampleRatioPass", True):
        suggestions.append(
            {
                "trigger": "HIGH_PROXY_ENTRY_MEMORY_RATIO",
                "actionZh": "代理上下文占比过高，优先等待新 EA 输出完整上下文再升级王牌。",
                "confidence": "HIGH",
            }
        )
    if not quality_gate.get("contextMissingRatioPass", True):
        suggestions.append(
            {
                "trigger": "HIGH_HISTORY_CONTEXT_MISSING_RATIO",
                "actionZh": "历史裸盈亏样本占比过高，先补 entryContext/MFE/MAE 采集或前向 tester 证据，再允许升级王牌。",
                "confidence": "HIGH",
            }
        )
    for gap, count in data_gaps.items():
        if count >= 2:
            suggestions.append({"trigger": gap, "actionZh": f"{gap} 反复出现在亏损单，下一轮数据缺口降权。", "confidence": "MEDIUM"})
    for row in fine_factor_health.get("topAdverseInLosses", [])[:4]:
        if int(row.get("lossAdverseCount") or 0) >= 2:
            suggestions.append(
                {
                    "trigger": f"FINE_FACTOR_ADVERSE_{row.get('factor')}",
                    "actionZh": f"{row.get('factor')} 细因子在亏损单中逆风 {row.get('lossAdverseCount')} 次，下一轮同类信号降权。",
                    "confidence": "MEDIUM",
                }
            )
    for row in fine_factor_health.get("topMissingInLosses", [])[:4]:
        if int(row.get("lossMissingCount") or 0) >= 2:
            suggestions.append(
                {
                    "trigger": f"FINE_FACTOR_MISSING_{row.get('factor')}",
                    "actionZh": (
                        f"{row.get('factor')} 细因子在亏损单中缺失 {row.get('lossMissingCount')} 次，"
                        "优先补采集并降低信息不完整信号权重。"
                    ),
                    "confidence": "MEDIUM",
                }
            )
    for row in fine_factor_health.get("topRawMissingInLosses", [])[:4]:
        if int(row.get("lossRawMissingCount") or 0) >= 2:
            suggestions.append(
                {
                    "trigger": f"FINE_FACTOR_RAW_MISSING_{row.get('factor')}",
                    "actionZh": (
                        f"{row.get('factor')} 细因子在亏损单中缺少原始开仓快照 "
                        f"{row.get('lossRawMissingCount')} 次，桥接值只可研究，优先补真实采集。"
                    ),
                    "confidence": "HIGH" if float(row.get("rawCoverageRatio") or 0) < 0.5 else "MEDIUM",
                }
            )
    return suggestions[:12]


def _previous_long_term_memory(runtime_dir: Path) -> Dict[str, Any]:
    report = load_json(runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json")
    memory = report.get("longTermTradeMemory") if isinstance(report.get("longTermTradeMemory"), dict) else {}
    rolling = memory.get("rollingReview") if isinstance(memory.get("rollingReview"), dict) else {}
    return {"generatedAt": memory.get("generatedAt") or report.get("createdAt"), "rollingReview": rolling}


def _cooldown_state(previous: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    generated = previous.get("generatedAt")
    if not generated:
        return {"active": False, "minutesRemaining": 0, "lastReviewAt": None}
    elapsed = _minutes_between(generated, now_iso)
    if elapsed is None:
        return {"active": False, "minutesRemaining": 0, "lastReviewAt": generated}
    remaining = max(0, REVIEW_COOLDOWN_MINUTES - int(elapsed))
    return {"active": remaining > 0, "minutesRemaining": remaining, "lastReviewAt": generated}


def _status(trades: List[Dict[str, Any]], rolling: Dict[str, Any]) -> str:
    if not trades:
        return "WAITING_TRADE_MEMORY"
    return str(rolling.get("status") or "MEMORY_ACTIVE_OBSERVE")


def _next_action(rolling: Dict[str, Any], feedback: Dict[str, Any]) -> str:
    if rolling.get("status") == "INSUFFICIENT_SAMPLES":
        return "继续累计交易样本；不足 12 笔不自动调系统。"
    if rolling.get("status") == "COOLDOWN_ACTIVE":
        return "冷却期内只记录不调参，防止一两笔交易导致过度反应。"
    if feedback.get("status") == "DEFENSE_MODE":
        return "已生成防守扣分策略；后续候选需要更高入场分和更小风险缩放。"
    return "长期记忆已生成候选扣分规则，等待下一轮策略评分/复盘消费。"


def _trade_id(row: Dict[str, Any]) -> str:
    explicit = first_value(row, "tradeId", "positionId", "orderTicket", "dealTicket", "feedbackId", "intentId")
    if explicit:
        return str(explicit)
    fingerprint = "|".join(
        str(first_value(row, key, default=""))
        for key in ("symbol", "strategyId", "side", "entryTime", "exitTime", "profitR", "timestamp")
    )
    return "TRADE-" + hashlib.sha256(fingerprint.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _dedupe_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for trade in trades:
        trade_id = str(trade.get("tradeId") or "")
        if not trade_id:
            continue
        by_id[trade_id] = trade
    return list(by_id.values())


def _factor_snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "atr": _score(row, "atr", "ATR", "atr14", "atrPips"),
        "trendScore": _score(row, "trendScore", "trend"),
        "sentimentScore": _score(row, "sentimentScore", "sentiment"),
        "openInterestChange": _score(row, "openInterestChange", "oiChange", "openInterest"),
        "newsScore": _score(row, "newsScore", "news"),
        "smartMoneyScore": _score(row, "smartMoneyScore", "smartMoney"),
        "predictionMarketScore": _score(row, "predictionMarketScore", "predictionMarket"),
        "kronosScore": _score(row, "kronosScore", "kronos"),
    }


def _risk_plan_snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "stopLossR": _score(row, "stopLossR", "slR", "initialStopR"),
        "takeProfitR": _score(row, "takeProfitR", "tpR", "targetR"),
        "tp1R": _score(row, "tp1R", "firstTakeProfitR"),
        "tp2R": _score(row, "tp2R", "secondTakeProfitR"),
        "trailingStartR": _score(row, "trailingStartR", "trailStartR"),
        "mfeGivebackPct": _score(row, "mfeGivebackPct", "givebackPct"),
        "maxHoldMinutes": _score(row, "maxHoldMinutes", "timeoutMinutes"),
        "stopLossPriceMove": _score(row, "stopLossPriceMove", "stopLossPips", "slPips"),
        "takeProfitPriceMove": _score(row, "takeProfitPriceMove", "takeProfitPips", "tpPips"),
    }


def _factor_attribution_summary(row: Dict[str, Any], factors: Dict[str, Any], reasons: List[str]) -> str:
    explicit = _value(row, "factorAttributionSummary", "attributionSummary", default="")
    if explicit:
        return str(explicit)
    positives = [name for name, value in factors.items() if _score_value(value) > 0.15]
    negatives = [name for name, value in factors.items() if _score_value(value) < -0.15]
    if positives or negatives:
        return f"正向={','.join(positives) or '无'}；逆风={','.join(negatives) or '无'}"
    return "；".join(reasons[:3]) if reasons else "等待更完整因子归因。"


def _exit_type(row: Dict[str, Any], profit_r: float) -> str:
    raw = str(first_value(row, "exitType", "exitReason", "reason", default="")).strip().upper()
    if "TRAIL" in raw:
        return "TRAILING_TAKE_PROFIT"
    if "PARTIAL" in raw or "TP1" in raw:
        return "PARTIAL_TAKE_PROFIT"
    if "TAKE" in raw or raw == "TP":
        return "TAKE_PROFIT"
    if "TIME" in raw:
        return "TIME_EXIT"
    if "WEAK" in raw:
        return "WEAKNESS_EXIT"
    if "STOP" in raw or raw == "SL":
        return "STOP_LOSS"
    return "PROFIT_EXIT" if profit_r > 0 else "LOSS_EXIT" if profit_r < 0 else "FLAT_EXIT"


def _exit_quality_tags(
    profit_r: float,
    mfe_r: float,
    mae_r: float,
    giveback_r: float,
    captured_mfe_ratio: float | None,
    duration_minutes: int | None,
    exit_type: str,
) -> List[str]:
    tags: List[str] = []
    if profit_r > 0 and mfe_r >= 0.75 and giveback_r >= 0.45:
        tags.append("PROFIT_GIVEBACK")
    if profit_r > 0 and mfe_r >= 0.75 and captured_mfe_ratio is not None and captured_mfe_ratio < 0.35:
        tags.append("LOW_MFE_CAPTURE")
    if profit_r > 0 and mae_r >= 0.8 and profit_r <= 0.25:
        tags.append("RECOVERED_TO_SMALL_WIN")
    if profit_r > 0 and captured_mfe_ratio is not None and captured_mfe_ratio >= 0.65:
        tags.append("HELD_WINNER_WELL")
    if exit_type == "TIME_EXIT" and profit_r < 0:
        tags.append("TIMEOUT_LOSS")
    if duration_minutes is not None and duration_minutes <= 15 and profit_r < 0:
        tags.append("ULTRA_FAST_LOSS")
    return _unique(tags)


def _exit_efficiency(exits: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not exits:
        return {
            "schema": "quantgod.exit_efficiency_memory.v1",
            "sampleCount": 0,
            "mfeMaeAvailableCount": 0,
            "missingMfeMaeCount": 0,
            "missingMfeMaeRatio": 0.0,
            "closeMoveAvailableCount": 0,
            "missingCloseMoveCount": 0,
            "closeMoveAvailableRatio": 0.0,
            "hints": [],
        }
    mfes = [float(row.get("mfeR") or 0.0) for row in exits]
    maes = [float(row.get("maeR") or 0.0) for row in exits]
    movement_rows = [
        row
        for row in exits
        if float(row.get("mfeR") or 0.0) > 0.0 or float(row.get("maeR") or 0.0) > 0.0
    ]
    missing_movement = len(exits) - len(movement_rows)
    close_move_rows = [
        row
        for row in exits
        if isinstance(row.get("closeMove"), dict) and row["closeMove"].get("available")
    ]
    close_move_values = [
        float(row["closeMove"].get("closeMoveR"))
        for row in close_move_rows
        if row["closeMove"].get("closeMoveR") not in (None, "")
    ]
    positive_close_moves = [value for value in close_move_values if value > 0]
    adverse_close_moves = [abs(value) for value in close_move_values if value < 0]
    bridge_only_rows = [
        row
        for row in close_move_rows
        if str(row.get("movementQuality") or "").upper() in {"BRIDGED_CLOSE_MOVE_ONLY", "CLOSE_MOVE_ONLY"}
    ]
    ratios = [
        float(row.get("capturedMfeRatio"))
        for row in exits
        if row.get("capturedMfeRatio") is not None
    ]
    quality_tags = Counter(tag for row in exits for tag in row.get("exitQualityTags", []))
    movement_quality = Counter(str(row.get("movementQuality") or "UNKNOWN") for row in exits)
    hints: List[Dict[str, Any]] = []
    if exits and len(movement_rows) / len(exits) < 0.5:
        hints.append({"trigger": "MFE_MAE_COVERAGE_LOW", "actionZh": "MFE/MAE 覆盖不足，TP/SL 只能保守估算；优先修采集或回填链路。"})
    if bridge_only_rows and len(movement_rows) / len(exits) < 0.5:
        hints.append(
            {
                "trigger": "CLOSE_MOVE_BRIDGE_AVAILABLE",
                "actionZh": "历史单已有 close-move 桥接，可辅助 TP/SL 保守复盘；但它不是盘中 MFE/MAE，不能替代真实采集。",
            }
        )
    if len(adverse_close_moves) >= 3 and not movement_rows:
        hints.append(
            {
                "trigger": "ADVERSE_CLOSE_MOVE_CLUSTER",
                "actionZh": "多笔历史单以负 close-move 收尾，止损/入场缓冲先按保守分位估算，等待真实 MFE/MAE 校准。",
            }
        )
    if quality_tags.get("PROFIT_GIVEBACK", 0) >= 2:
        hints.append({"trigger": "PROFIT_GIVEBACK", "actionZh": "盈利回吐重复出现，降低 MFE 回吐容忍度。"})
    if quality_tags.get("LOW_MFE_CAPTURE", 0) >= 2:
        hints.append({"trigger": "LOW_MFE_CAPTURE", "actionZh": "MFE 捕获率偏低，提前 TP1 并收紧 trailing。"})
    if quality_tags.get("RECOVERED_TO_SMALL_WIN", 0) >= 2:
        hints.append({"trigger": "RECOVERED_TO_SMALL_WIN", "actionZh": "扛单恢复后小赚优先走，不继续幻想大行情。"})
    if quality_tags.get("HELD_WINNER_WELL", 0) >= 3:
        hints.append({"trigger": "HELD_WINNER_WELL", "actionZh": "强趋势盈利捕获稳定，可保留 runner 继续观察。"})
    return {
        "schema": "quantgod.exit_efficiency_memory.v1",
        "sampleCount": len(exits),
        "mfeMaeAvailableCount": len(movement_rows),
        "missingMfeMaeCount": missing_movement,
        "missingMfeMaeRatio": round(missing_movement / len(exits), 4) if exits else 0.0,
        "closeMoveAvailableCount": len(close_move_rows),
        "missingCloseMoveCount": len(exits) - len(close_move_rows),
        "closeMoveAvailableRatio": round(len(close_move_rows) / len(exits), 4) if exits else 0.0,
        "closeMoveBridgeOnlyCount": len(bridge_only_rows),
        "avgCloseMoveR": round(mean(close_move_values), 6) if close_move_values else 0.0,
        "avgPositiveCloseMoveR": round(mean(positive_close_moves), 6) if positive_close_moves else 0.0,
        "avgAdverseCloseMoveR": round(mean(adverse_close_moves), 6) if adverse_close_moves else 0.0,
        "avgMfeR": round(mean(mfes), 6) if mfes else 0.0,
        "avgMaeR": round(mean(maes), 6) if maes else 0.0,
        "avgCapturedMfeRatio": round(mean(ratios), 6) if ratios else 0.0,
        "profitGivebackCount": quality_tags.get("PROFIT_GIVEBACK", 0),
        "lowMfeCaptureCount": quality_tags.get("LOW_MFE_CAPTURE", 0),
        "recoveredSmallWinCount": quality_tags.get("RECOVERED_TO_SMALL_WIN", 0),
        "heldWinnerWellCount": quality_tags.get("HELD_WINNER_WELL", 0),
        "qualityTags": _counter_rows(quality_tags),
        "movementQualityCounts": _counter_rows(movement_quality),
        "hints": hints[:8],
    }


def _list_value(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        separators = ["|", ";", "；", ","]
        parts = [value]
        for sep in separators:
            if sep in value:
                parts = value.split(sep)
                break
        return [part.strip() for part in parts if part.strip()]
    return []


def _score(row: Dict[str, Any], *keys: str) -> float | None:
    value = _value(row, *keys, default=None)
    if value in (None, ""):
        return None
    return round(safe_float(value, 0), 6)


def _value(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    value = first_value(row, *keys, default=None)
    if value not in (None, ""):
        return _scalar_value(value)
    for key in keys:
        path_value = _path_value(row, key)
        if path_value not in (None, ""):
            return _scalar_value(path_value)
    nested = _nested_first_value(row, keys)
    if nested not in (None, ""):
        return _scalar_value(nested)
    return default


def _path_value(row: Dict[str, Any], key: str) -> Any:
    if "." not in key:
        return None
    current: Any = row
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = _case_insensitive_get(current, part)
        if current in (None, ""):
            return None
    return current


def _nested_first_value(row: Dict[str, Any], keys: Iterable[str]) -> Any:
    queue: List[tuple[Any, int]] = []
    for context_key in NESTED_ENTRY_CONTEXT_KEYS:
        value = _case_insensitive_get(row, context_key)
        if isinstance(value, (dict, list)):
            queue.append((value, 0))
    seen: set[int] = set()
    while queue:
        current, depth = queue.pop(0)
        if depth > 4:
            continue
        object_id = id(current)
        if object_id in seen:
            continue
        seen.add(object_id)
        if isinstance(current, dict):
            direct = first_value(current, *keys, default=None)
            if direct not in (None, ""):
                return direct
            for key in keys:
                path_value = _path_value(current, key)
                if path_value not in (None, ""):
                    return path_value
            for child in current.values():
                if isinstance(child, (dict, list)):
                    queue.append((child, depth + 1))
        elif isinstance(current, list):
            for child in current:
                if isinstance(child, (dict, list)):
                    queue.append((child, depth + 1))
    return None


def _case_insensitive_get(row: Dict[str, Any], key: str) -> Any:
    if key in row:
        return row.get(key)
    lower_key = key.lower()
    for item_key, value in row.items():
        if str(item_key).lower() == lower_key:
            return value
    return None


def _scalar_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in SCALAR_VALUE_KEYS:
            nested = _case_insensitive_get(value, key)
            if nested not in (None, "") and not isinstance(nested, (dict, list)):
                return nested
    return value


def _score_value(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return safe_float(value, 0.0)


def _loss_streak(exits: List[Dict[str, Any]]) -> int:
    count = 0
    for row in reversed(exits):
        if float(row.get("profitR") or 0.0) < 0:
            count += 1
        else:
            break
    return count


def _counter_rows(counter: Counter) -> List[Dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(12)]


def _worst_groups(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in groups if float(row.get("totalProfitR") or 0) < 0][:5]


def _row_text(row: Dict[str, Any]) -> str:
    pieces = []
    for key in ("exitReason", "reason", "reasonZh", "entryReason", "entryReasons", "strategyId", "candidateSource"):
        value = row.get(key)
        if value not in (None, ""):
            pieces.append(str(value))
    return " ".join(pieces).lower()


def _duration_minutes(start: Any, end: Any) -> int | None:
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    if not start_dt or not end_dt:
        return None
    return max(0, int((end_dt - start_dt).total_seconds() / 60))


def _minutes_between(start: Any, end: Any) -> int | None:
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    if not start_dt or not end_dt:
        return None
    return max(0, int((end_dt - start_dt).total_seconds() / 60))


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _unique(values: Iterable[str]) -> List[str]:
    output: List[str] = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
