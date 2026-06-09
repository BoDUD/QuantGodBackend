from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import ensure_dir, read_csv_rows, read_json, read_jsonl, write_json, write_jsonl
from .schema import CORE_FIELDS, FEEDBACK_LEDGER, FOCUS_SYMBOL, OUTPUT_DIR, PRODUCER_REPORT, SAFETY, SCHEMA


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(row: dict[str, Any], *keys: str, default: float | None = None) -> float | None:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except Exception:
            continue
    return default


def _unit_float(row: dict[str, Any], *keys: str, default: float | None = None) -> float | None:
    value = _float(row, *keys, default=default)
    if value is None:
        return value
    if 1.0 < value <= 100.0:
        return round(value / 100.0, 4)
    return value


def _text(row: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _list_value(row: dict[str, Any], *keys: str) -> list[str]:
    value = None
    for key in keys:
        if row.get(key) not in (None, ""):
            value = row.get(key)
            break
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        parts = [value]
        for sep in ("|", ";", "；", ","):
            if sep in value:
                parts = value.split(sep)
                break
        return [part.strip() for part in parts if part.strip()]
    return []


def _nested_dict(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _is_usdjpy(row: dict[str, Any]) -> bool:
    symbol = _text(row, "symbol", "Symbol", "instrument", "pair").upper()
    return symbol in {"USDJPY", "USDJPYC", "USDJPY.C", FOCUS_SYMBOL.upper()}


def _direction(row: dict[str, Any]) -> str:
    text = _text(row, "side", "Side", "direction", "Direction", "CandidateDirection", "type", "Type").upper()
    if text in {"BUY", "LONG", "BULL", "1"}:
        return "LONG"
    if text in {"SELL", "SHORT", "BEAR", "-1"}:
        return "SHORT"
    return text or "UNKNOWN"


def _movement_pair(row: dict[str, Any], direction: str, profit_r: float | None) -> tuple[float, float]:
    if direction == "LONG":
        mfe = _float(row, "mfeR", "MFER", "maxFavorableR", "mfe", "LongMFEPips", "mfePips", "MfePips")
        mae = _float(row, "maeR", "MAER", "maxAdverseR", "mae", "LongMAEPips", "maePips", "MaePips")
    elif direction == "SHORT":
        mfe = _float(row, "mfeR", "MFER", "maxFavorableR", "mfe", "ShortMFEPips", "mfePips", "MfePips")
        mae = _float(row, "maeR", "MAER", "maxAdverseR", "mae", "ShortMAEPips", "maePips", "MaePips")
    else:
        mfe = _float(row, "mfeR", "MFER", "maxFavorableR", "mfe", "LongMFEPips", "ShortMFEPips", "mfePips", "MfePips")
        mae = _float(row, "maeR", "MAER", "maxAdverseR", "mae", "LongMAEPips", "ShortMAEPips", "maePips", "MaePips")
    profit = float(profit_r or 0.0)
    if mfe is None or (mfe == 0.0 and profit > 0.0):
        mfe = max(profit, 0.0)
    if mae is None or (mae == 0.0 and profit < 0.0):
        mae = abs(min(profit, 0.0))
    return max(float(mfe or 0.0), 0.0), abs(float(mae or 0.0))


def _shadow_pip_outcome_as_r(row: dict[str, Any], direction: str) -> tuple[float | None, float | None, float | None]:
    if direction == "LONG":
        close_pips = _float(row, "LongClosePips")
        mfe_pips = _float(row, "LongMFEPips")
        mae_pips = _float(row, "LongMAEPips")
    elif direction == "SHORT":
        close_pips = _float(row, "ShortClosePips")
        mfe_pips = _float(row, "ShortMFEPips")
        mae_pips = _float(row, "ShortMAEPips")
    else:
        close_pips = _float(row, "LongClosePips", "ShortClosePips")
        mfe_pips = _float(row, "LongMFEPips", "ShortMFEPips")
        mae_pips = _float(row, "LongMAEPips", "ShortMAEPips")
    if close_pips is None:
        return None, None, None
    risk_pips = max(6.0, abs(float(mfe_pips or 0.0)) + abs(float(mae_pips or 0.0)))
    return (
        round(float(close_pips) / risk_pips, 6),
        round(max(float(mfe_pips or 0.0), 0.0) / risk_pips, 6),
        round(abs(float(mae_pips or 0.0)) / risk_pips, 6),
    )


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _route_trend_score(route: str, regime: str) -> float:
    route_upper = route.upper()
    regime_upper = regime.upper()
    if "TREND" in route_upper or "BREAKOUT" in route_upper:
        return 0.85
    if "TREND" in regime_upper:
        return 0.70
    if "RANGE" in regime_upper:
        return 0.35
    return 0.50


def _route_risk_reward(route: str, score: float) -> float:
    route_upper = route.upper()
    if "TREND" in route_upper or "BREAKOUT" in route_upper:
        return 1.80
    if score >= 0.70:
        return 1.65
    if "REVERSAL" in route_upper or "RANGE" in route_upper:
        return 1.30
    return 1.50


def _legacy_shadow_proxy_context(row: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    route = _text(row, "CandidateRoute", "route", "strategy", "strategyId")
    score = _unit_float(row, "CandidateScore", "SignalScore", "score", "signalScore")
    if not route or score is None:
        return {}
    regime = _text(row, "Regime", "regime", default="UNKNOWN")
    direction = _direction(row)
    mfe_r, mae_r = _movement_pair(row, direction, event.get("profitR"))
    horizon_minutes = _float(row, "HorizonMinutes", "horizonMinutes", default=15.0) or 15.0
    atr_proxy = max(0.1, float(mfe_r) + float(mae_r))
    trend = _route_trend_score(route, regime)
    market_quality = _clamp((trend * 0.55) + (score * 0.35) + 0.10)
    professional = _clamp((score * 0.65) + (market_quality * 0.35))
    risk_reward = _route_risk_reward(route, score)
    win_probability = _clamp((score * 0.50) + (market_quality * 0.25) + (trend * 0.25))
    expected_value = (win_probability * risk_reward) - (1.0 - win_probability)
    stop_loss_pips = max(6.0, atr_proxy * (1.3 if risk_reward >= 1.65 else 1.0))
    trigger = _text(row, "Trigger", "trigger", "entryReasons", "OutcomeReason", default=f"{route} legacy shadow outcome")
    return {
        "contextQuality": "SHADOW_PROXY",
        "contextQualityReasonZh": "旧版 shadow outcome 缺少完整进场因子，已用 route/regime/score/MFE/MAE 做低置信度代理回填。",
        "proxySource": "legacy_shadow_candidate_outcome",
        "reasons": [trigger],
        "scores": {
            "totalScore": round(score, 4),
            "dataCoverage": 0.42,
            "proScore": round(professional, 4),
            "marketQuality": round(market_quality, 4),
            "entryTiming": round(score, 4),
            "fundFlow": 0.50,
            "executionRisk": round(_clamp(1.0 - market_quality), 4),
            "resonanceCount": 2 if score >= 0.60 else 1,
        },
        "factors": {
            "atrPips": round(atr_proxy, 4),
            "trend": round(trend, 4),
            "sentiment": 0.50,
            "oiChange": 0.0,
            "news": 0.50,
            "smartMoney": 0.50,
            "predictionMarket": 0.50,
            "kronos": 0.50,
        },
        "estimates": {
            "ev": round(expected_value, 4),
            "winProbability": round(win_probability, 4),
            "riskReward": round(risk_reward, 4),
            "positionScale": round(_clamp((professional * 0.70) + (market_quality * 0.30)), 4),
        },
        "riskPlan": {
            "stopLossR": 1.0,
            "targetR": round(risk_reward, 4),
            "firstTakeProfitR": 0.70,
            "secondTakeProfitR": round(risk_reward, 4),
            "trailStartR": 0.80,
            "givebackPct": 0.35,
            "timeoutMinutes": max(15.0, horizon_minutes),
            "stopLossPips": round(stop_loss_pips, 4),
            "takeProfitPips": round(stop_loss_pips * risk_reward, 4),
        },
        "factorAttributionSummary": f"{route} proxy score={score:.2f}; regime={regime}; mfe={mfe_r:.2f}; mae={mae_r:.2f}",
    }


def _entry_context(row: dict[str, Any], event: dict[str, Any], source: str) -> dict[str, Any]:
    existing = _nested_dict(row, "entryContext", "entryMemory", "signalContext")
    proxy = _legacy_shadow_proxy_context(row, event)
    scores = _nested_dict(existing, "scores", "scoreBreakdown")
    proxy_scores = proxy.get("scores") if isinstance(proxy.get("scores"), dict) else {}
    factors = _nested_dict(existing, "factors", "factorSnapshot")
    proxy_factors = proxy.get("factors") if isinstance(proxy.get("factors"), dict) else {}
    estimates = _nested_dict(existing, "estimates", "prediction", "decision")
    proxy_estimates = proxy.get("estimates") if isinstance(proxy.get("estimates"), dict) else {}
    risk_plan = _nested_dict(existing, "riskPlan", "risk", "exit")
    proxy_risk_plan = proxy.get("riskPlan") if isinstance(proxy.get("riskPlan"), dict) else {}
    symbol = _first_non_empty(existing.get("symbol"), row.get("symbol"), row.get("Symbol"), event.get("symbol"), FOCUS_SYMBOL)
    direction = _first_non_empty(existing.get("side"), row.get("side"), row.get("Side"), row.get("direction"), row.get("Direction"), event.get("side"))
    context = {
        **existing,
        "contextQuality": _first_non_empty(existing.get("contextQuality"), row.get("contextQuality"), proxy.get("contextQuality"), "RAW"),
        "contextQualityReasonZh": _first_non_empty(existing.get("contextQualityReasonZh"), row.get("contextQualityReasonZh"), proxy.get("contextQualityReasonZh"), ""),
        "proxySource": _first_non_empty(existing.get("proxySource"), row.get("proxySource"), proxy.get("proxySource"), ""),
        "entryTime": _first_non_empty(existing.get("entryTime"), row.get("entryTime"), row.get("openTime"), row.get("timestamp"), event.get("timestamp")),
        "symbol": symbol,
        "side": direction,
        "strategyVersion": _first_non_empty(existing.get("strategyVersion"), row.get("strategyVersion"), row.get("strategyId"), row.get("strategy"), event.get("strategyId")),
        "leverage": _float({**row, **existing}, "leverage", "Leverage", default=0.0),
        "marginUsd": _float({**row, **existing}, "marginUsd", "margin", "Margin", default=0.0),
        "notionalUsd": _float({**row, **existing}, "notionalUsd", "notional", "Notional", default=0.0),
        "candidateSource": _first_non_empty(existing.get("candidateSource"), row.get("candidateSource"), source),
        "reasons": _list_value(row, "entryReasons", "reasons", "entryReason", "reasonZh", "Trigger", "trigger") or proxy.get("reasons", []),
        "scores": {
            **scores,
            "totalScore": _first_non_empty(scores.get("totalScore"), _unit_float(row, "compositeScore", "totalScore", "CandidateScore", "SignalScore", "score", "signalScore"), proxy_scores.get("totalScore")),
            "dataCoverage": _first_non_empty(scores.get("dataCoverage"), _unit_float(row, "dataCoverageScore", "dataCoverage", "coverageScore"), proxy_scores.get("dataCoverage")),
            "proScore": _first_non_empty(scores.get("proScore"), _unit_float(row, "professionalScore", "proScore"), proxy_scores.get("proScore")),
            "marketQuality": _first_non_empty(scores.get("marketQuality"), _unit_float(row, "marketQualityScore", "marketQuality"), proxy_scores.get("marketQuality")),
            "entryTiming": _first_non_empty(scores.get("entryTiming"), _unit_float(row, "entryTimingScore", "entryTiming"), proxy_scores.get("entryTiming")),
            "fundFlow": _first_non_empty(scores.get("fundFlow"), _unit_float(row, "fundFlowScore", "fundFlow"), proxy_scores.get("fundFlow")),
            "executionRisk": _first_non_empty(scores.get("executionRisk"), _unit_float(row, "executionRiskScore", "executionRisk"), proxy_scores.get("executionRisk")),
            "resonanceCount": _first_non_empty(scores.get("resonanceCount"), _float(row, "resonanceCount", "resonance"), proxy_scores.get("resonanceCount")),
        },
        "factors": {
            **factors,
            "atrPips": _first_non_empty(factors.get("atrPips"), _float(row, "atr", "ATR", "atr14", "atrPips"), proxy_factors.get("atrPips")),
            "trend": _first_non_empty(factors.get("trend"), _float(row, "trendScore", "trend"), proxy_factors.get("trend")),
            "sentiment": _first_non_empty(factors.get("sentiment"), _float(row, "sentimentScore", "sentiment"), proxy_factors.get("sentiment")),
            "oiChange": _first_non_empty(factors.get("oiChange"), _float(row, "openInterestChange", "oiChange", "openInterest"), proxy_factors.get("oiChange")),
            "news": _first_non_empty(factors.get("news"), _float(row, "newsScore", "news"), proxy_factors.get("news")),
            "smartMoney": _first_non_empty(factors.get("smartMoney"), _float(row, "smartMoneyScore", "smartMoney"), proxy_factors.get("smartMoney")),
            "predictionMarket": _first_non_empty(factors.get("predictionMarket"), _float(row, "predictionMarketScore", "predictionMarket"), proxy_factors.get("predictionMarket")),
            "kronos": _first_non_empty(factors.get("kronos"), _float(row, "kronosScore", "kronos"), proxy_factors.get("kronos")),
        },
        "estimates": {
            **estimates,
            "ev": _first_non_empty(estimates.get("ev"), _float(row, "estimatedEV", "ev", "expectedValue"), proxy_estimates.get("ev")),
            "winProbability": _first_non_empty(estimates.get("winProbability"), _float(row, "estimatedWinProbability", "winProbability", "winProb"), proxy_estimates.get("winProbability")),
            "riskReward": _first_non_empty(estimates.get("riskReward"), _float(row, "estimatedRiskReward", "riskReward", "rr"), proxy_estimates.get("riskReward")),
            "positionScale": _first_non_empty(estimates.get("positionScale"), _float(row, "positionScaling", "positionScale", "riskMultiplier"), proxy_estimates.get("positionScale")),
        },
        "riskPlan": {
            **risk_plan,
            "stopLossR": _first_non_empty(risk_plan.get("stopLossR"), _float(row, "stopLossR", "slR", "initialStopR"), proxy_risk_plan.get("stopLossR")),
            "targetR": _first_non_empty(risk_plan.get("targetR"), _float(row, "takeProfitR", "tpR", "targetR"), proxy_risk_plan.get("targetR")),
            "firstTakeProfitR": _first_non_empty(risk_plan.get("firstTakeProfitR"), _float(row, "tp1R", "firstTakeProfitR"), proxy_risk_plan.get("firstTakeProfitR")),
            "secondTakeProfitR": _first_non_empty(risk_plan.get("secondTakeProfitR"), _float(row, "tp2R", "secondTakeProfitR"), proxy_risk_plan.get("secondTakeProfitR")),
            "trailStartR": _first_non_empty(risk_plan.get("trailStartR"), _float(row, "trailingStartR", "trailStartR"), proxy_risk_plan.get("trailStartR")),
            "givebackPct": _first_non_empty(risk_plan.get("givebackPct"), _float(row, "mfeGivebackPct", "givebackPct"), proxy_risk_plan.get("givebackPct")),
            "timeoutMinutes": _first_non_empty(risk_plan.get("timeoutMinutes"), _float(row, "maxHoldMinutes", "timeoutMinutes"), proxy_risk_plan.get("timeoutMinutes")),
            "stopLossPips": _first_non_empty(risk_plan.get("stopLossPips"), _float(row, "stopLossPriceMove", "stopLossPips", "slPips"), proxy_risk_plan.get("stopLossPips")),
            "takeProfitPips": _first_non_empty(risk_plan.get("takeProfitPips"), _float(row, "takeProfitPriceMove", "takeProfitPips", "tpPips"), proxy_risk_plan.get("takeProfitPips")),
        },
        "factorAttributionSummary": _first_non_empty(existing.get("factorAttributionSummary"), row.get("factorAttributionSummary"), row.get("attributionSummary"), proxy.get("factorAttributionSummary"), ""),
    }
    if not existing and not proxy and _context_available_count(context) == 0:
        context["contextQuality"] = "EXECUTION_FEEDBACK_CONTEXT"
        context["contextQualityReasonZh"] = "执行反馈行缺少完整进场因子；仅保留基础身份字段，不能作为升王牌/升实盘证据。"
    return context


def _fingerprint(row: dict[str, Any]) -> str:
    key = "|".join(
        str(row.get(name, ""))
        for name in (
            "feedbackId",
            "timestamp",
            "createdAt",
            "strategyId",
            "eventType",
            "executionMode",
            "expectedPrice",
            "fillPrice",
            "profitR",
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _dedupe_key(row: dict[str, Any]) -> str:
    if row.get("sourceKind") == "shadow_outcome":
        stable = "|".join(
            str(row.get(name, ""))
            for name in (
                "source",
                "sourceEventId",
                "timestamp",
                "horizonBars",
                "strategyId",
                "side",
                "expectedPrice",
                "fillPrice",
            )
        )
        return "shadow|" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return str(row.get("feedbackId") or _fingerprint(row))


def _complete(row: dict[str, Any]) -> bool:
    return all(row.get(field) not in (None, "") for field in CORE_FIELDS)


def _entry_context_categories() -> dict[str, tuple[str, ...]]:
    return {
        "scores": ("totalScore", "dataCoverage", "proScore", "marketQuality", "entryTiming", "fundFlow", "executionRisk", "resonanceCount"),
        "factors": ("atrPips", "trend", "sentiment", "oiChange", "news", "smartMoney", "predictionMarket", "kronos"),
        "estimates": ("ev", "winProbability", "riskReward", "positionScale"),
        "riskPlan": ("stopLossR", "targetR", "firstTakeProfitR", "secondTakeProfitR", "trailStartR", "givebackPct", "timeoutMinutes", "stopLossPips", "takeProfitPips"),
    }


def _entry_context_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "schema": "quantgod.execution_feedback_entry_context_coverage.v1",
            "sampleCount": 0,
            "entryContextRatio": 0.0,
            "categories": [],
            "status": "NO_SAMPLES",
        }
    categories = _entry_context_categories()
    contexts = [row.get("entryContext") for row in rows if isinstance(row.get("entryContext"), dict)]
    proxy_contexts = [context for context in contexts if context.get("contextQuality") == "SHADOW_PROXY"]
    category_rows: list[dict[str, Any]] = []
    for name, fields in categories.items():
        available = 0
        possible = len(fields) * len(rows)
        for row in rows:
            context = row.get("entryContext") if isinstance(row.get("entryContext"), dict) else {}
            section = context.get(name) if isinstance(context.get(name), dict) else {}
            available += sum(1 for field in fields if section.get(field) not in (None, ""))
        category_rows.append(
            {
                "category": name,
                "fieldCount": len(fields),
                "availableCount": available,
                "missingCount": possible - available,
                "coverageRatio": round(available / possible, 4) if possible else 0.0,
            }
        )
    overall = round(sum(row["coverageRatio"] for row in category_rows) / len(category_rows), 4)
    status = "GOOD" if overall >= 0.8 else "LOW_ENTRY_CONTEXT_COVERAGE"
    return {
        "schema": "quantgod.execution_feedback_entry_context_coverage.v1",
        "sampleCount": len(rows),
        "entryContextCount": len(contexts),
        "entryContextRatio": round(len(contexts) / len(rows), 4),
        "proxyContextCount": len(proxy_contexts),
        "proxyContextRatio": round(len(proxy_contexts) / len(rows), 4),
        "overallNestedCoverageRatio": overall,
        "categories": category_rows,
        "status": status,
        "reasonZh": (
            "entryContext 因子覆盖达标。"
            if status == "GOOD"
            else "entryContext 已写入；SHADOW_PROXY 为旧样本低置信度代理，真实评分/因子/EV/风险计划仍需采集端继续补列。"
        ),
    }


def _entry_context_source_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "schema": "quantgod.execution_feedback_entry_context_source_audit.v1",
            "sampleCount": 0,
            "status": "NO_SAMPLES",
        }
    categories = _entry_context_categories()
    quality_counts: dict[str, int] = {}
    source_groups: dict[str, dict[str, Any]] = {}
    missing_fields: dict[str, int] = {}
    total_possible = 0
    total_available = 0
    raw_count = 0
    limited_count = 0
    limited_qualities = {"BRIDGED_HISTORY_CONTEXT", "EXECUTION_FEEDBACK_CONTEXT", "SHADOW_PROXY", "MISSING"}

    for row in rows:
        context = row.get("entryContext") if isinstance(row.get("entryContext"), dict) else {}
        quality = str(context.get("contextQuality") or "MISSING").upper()
        quality_counts[quality] = quality_counts.get(quality, 0) + 1
        if quality == "RAW":
            raw_count += 1
        if quality in limited_qualities:
            limited_count += 1
        source = str(row.get("source") or "unknown")
        source_kind = str(row.get("sourceKind") or "unknown")
        source_tier = str(row.get("sourceTier") or "unknown")
        group_key = f"{source}|{source_kind}|{source_tier}|{quality}"
        group = source_groups.setdefault(
            group_key,
            {
                "source": source,
                "sourceKind": source_kind,
                "sourceTier": source_tier,
                "contextQuality": quality,
                "sampleCount": 0,
                "availableCount": 0,
                "missingCount": 0,
            },
        )
        group["sampleCount"] += 1
        for category, fields in categories.items():
            section = context.get(category) if isinstance(context.get(category), dict) else {}
            for field in fields:
                total_possible += 1
                value = section.get(field)
                present = value not in (None, "")
                if present:
                    total_available += 1
                    group["availableCount"] += 1
                else:
                    group["missingCount"] += 1
                    field_key = f"{category}.{field}"
                    missing_fields[field_key] = missing_fields.get(field_key, 0) + 1

    for group in source_groups.values():
        possible = group["availableCount"] + group["missingCount"]
        group["coverageRatio"] = round(group["availableCount"] / possible, 4) if possible else 0.0

    raw_ratio = round(raw_count / len(rows), 4)
    overall = round(total_available / total_possible, 4) if total_possible else 0.0
    status = "GOOD" if raw_ratio >= 0.7 and overall >= 0.8 else "NEEDS_RAW_ENTRY_CONTEXT"
    return {
        "schema": "quantgod.execution_feedback_entry_context_source_audit.v1",
        "sampleCount": len(rows),
        "status": status,
        "statusZh": "raw entryContext 覆盖达标" if status == "GOOD" else "raw entryContext 覆盖不足",
        "rawContextCount": raw_count,
        "rawContextRatio": raw_ratio,
        "contextLimitedCount": limited_count,
        "contextLimitedRatio": round(limited_count / len(rows), 4),
        "overallNestedCoverageRatio": overall,
        "qualityCounts": dict(sorted(quality_counts.items())),
        "topMissingFields": [
            {"field": field, "missingCount": count, "missingRatio": round(count / len(rows), 4)}
            for field, count in sorted(missing_fields.items(), key=lambda item: (-item[1], item[0]))[:12]
        ],
        "sourceQualityRows": sorted(
            source_groups.values(),
            key=lambda item: (-int(item["sampleCount"]), str(item["source"]), str(item["contextQuality"])),
        )[:16],
        "nextActionsZh": [
            "优先让 EA / shadow 候选日志在开仓时写入 scores、factors、estimates、riskPlan。",
            "SHADOW_PROXY、BRIDGED_HISTORY_CONTEXT、EXECUTION_FEEDBACK_CONTEXT 只可用于复盘/降级，不能作为升王牌证据。",
            "rawContextRatio 与 overallNestedCoverageRatio 达标后，再允许候选进入更高等级 promotion 审查。",
        ],
    }


def _context_available_count(context: dict[str, Any]) -> int:
    count = 0
    for section_name in ("scores", "factors", "estimates", "riskPlan"):
        section = context.get(section_name) if isinstance(context.get(section_name), dict) else {}
        count += sum(1 for value in section.values() if value not in (None, ""))
    return count


def _merge_context_missing(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if isinstance(value, dict):
            existing_section = merged.get(key) if isinstance(merged.get(key), dict) else {}
            merged[key] = _merge_context_missing(existing_section, value)
        elif merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    return merged


def _maybe_enrich_entry_context(existing_event: dict[str, Any], incoming_event: dict[str, Any]) -> bool:
    incoming = incoming_event.get("entryContext")
    if not isinstance(incoming, dict):
        return False
    existing = existing_event.get("entryContext") if isinstance(existing_event.get("entryContext"), dict) else {}
    merged = _merge_context_missing(existing, incoming)
    if _context_available_count(merged) <= _context_available_count(existing):
        return False
    existing_event["entryContext"] = merged
    return True


def _correct_empty_raw_entry_context(event: dict[str, Any]) -> bool:
    context = event.get("entryContext") if isinstance(event.get("entryContext"), dict) else {}
    if str(context.get("contextQuality") or "").upper() != "RAW":
        return False
    if _context_available_count(context) > 0:
        return False
    context["contextQuality"] = "EXECUTION_FEEDBACK_CONTEXT"
    context["contextQualityReasonZh"] = "执行反馈行缺少完整进场因子；仅保留基础身份字段，不能作为升王牌/升实盘证据。"
    event["entryContext"] = context
    return True


def _maybe_update_shadow_measurement(existing_event: dict[str, Any], incoming_event: dict[str, Any]) -> bool:
    if existing_event.get("sourceKind") != "shadow_outcome" or incoming_event.get("sourceKind") != "shadow_outcome":
        return False
    changed = False
    for field in (
        "feedbackId",
        "timestamp",
        "sourceEventId",
        "horizonBars",
        "expectedPrice",
        "fillPrice",
        "profitR",
        "mfeR",
        "maeR",
    ):
        incoming_value = incoming_event.get(field)
        if incoming_value not in (None, "") and existing_event.get(field) != incoming_value:
            existing_event[field] = incoming_value
            changed = True
    return changed


def _event_from_shadow(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    if not _is_usdjpy(row):
        return None
    strategy = _text(row, "strategyId", "strategy", "strategyName", "CandidateRoute", "route", default="USDJPY_SHADOW_STRATEGY")
    direction = _direction(row)
    expected = _float(row, "expectedPrice", "entryPrice", "priceAtSignal", "signalPrice", "ReferencePrice", "open", "currentPrice")
    fill = _float(row, "fillPrice", "exitPrice", "closePrice", "FutureClose", "currentPrice", "priceAfter60m", "price")
    explicit_profit_r = _float(row, "profitR", "scoreR", "r", "posteriorR", "netR")
    pip_profit_r, pip_mfe_r, pip_mae_r = _shadow_pip_outcome_as_r(row, direction)
    profit_r = explicit_profit_r if explicit_profit_r is not None else (pip_profit_r if pip_profit_r is not None else 0.0)
    if explicit_profit_r is not None:
        mfe_r, mae_r = _movement_pair(row, direction, profit_r)
    else:
        mfe_r = float(pip_mfe_r or max(float(profit_r or 0.0), 0.0))
        mae_r = float(pip_mae_r or abs(min(float(profit_r or 0.0), 0.0)))
    timestamp = _text(row, "timestamp", "time", "generatedAt", "OutcomeLabelTimeServer", "EventBarTime", default="")
    if not timestamp:
        timestamp = f"SHADOW_NO_TS:{source}:{strategy}:{direction}:{expected}:{fill}:{profit_r}:{mfe_r}:{mae_r}"
    if expected is None and fill is None:
        expected = 0.0
        fill = 0.0
    elif expected is None:
        expected = fill
    elif fill is None:
        fill = expected
    event = {
        "schema": "quantgod.execution_feedback.v1",
        "timestamp": timestamp,
        "symbol": FOCUS_SYMBOL,
        "strategyId": strategy,
        "eventType": "SHADOW_EXIT",
        "executionMode": "SHADOW",
        "side": direction,
        "sourceEventId": _text(row, "EventId", "eventId", default=""),
        "horizonBars": _float(row, "HorizonBars", "horizonBars", default=0.0),
        "expectedPrice": expected,
        "fillPrice": fill,
        "slippagePips": _float(row, "slippagePips", "slippage", default=0.0),
        "latencyMs": _float(row, "latencyMs", "latency", default=0.0),
        "spreadAtEntry": _float(row, "spreadAtEntry", "spread", "spreadPips", "SpreadPips", default=0.0),
        "profitR": profit_r,
        "mfeR": mfe_r,
        "maeR": mae_r,
        "source": source,
        "sourceKind": "shadow_outcome",
        "sourceTier": "strategy_shadow",
    }
    event["entryContext"] = _entry_context(row, event, source)
    event["feedbackId"] = _dedupe_key(event).replace("shadow|", "")
    return event if _complete(event) else None


def _event_from_close_history(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    if not _is_usdjpy(row):
        return None
    strategy = _text(row, "strategyId", "strategy", "comment", "magic", default="USDJPY_LIVE_UNKNOWN")
    direction = _direction(row)
    expected = _float(row, "expectedPrice", "entryPrice", "openPrice", "priceOpen")
    fill = _float(row, "fillPrice", "closePrice", "priceClose", "exitPrice")
    profit_r = _float(row, "profitR", "r", "scoreR")
    if profit_r is None:
        profit = _float(row, "profit", "profitUSC", "pnl", default=0.0)
        profit_r = float(profit or 0.0) / 10.0
    if expected is None and fill is None:
        return None
    if expected is None:
        expected = fill
    if fill is None:
        fill = expected
    mfe_r, mae_r = _movement_pair(row, direction, profit_r)
    event = {
        "schema": "quantgod.execution_feedback.v1",
        "timestamp": _text(row, "timestamp", "closeTime", "time", default=_now_iso()),
        "symbol": FOCUS_SYMBOL,
        "strategyId": strategy,
        "eventType": "LIVE_EXIT",
        "executionMode": "LIVE",
        "side": direction,
        "expectedPrice": expected,
        "fillPrice": fill,
        "slippagePips": _float(row, "slippagePips", "slippage", default=0.0),
        "latencyMs": _float(row, "latencyMs", default=0.0),
        "spreadAtEntry": _float(row, "spreadAtEntry", "spread", default=0.0),
        "profitR": profit_r,
        "mfeR": mfe_r,
        "maeR": mae_r,
        "exitReason": _text(row, "exitReason", "reason", default="UNKNOWN"),
        "source": source,
        "sourceKind": "close_history",
        "sourceTier": "mt5_close_history",
    }
    event["entryContext"] = _entry_context(row, event, source)
    event["feedbackId"] = _fingerprint(event)
    return event if _complete(event) else None


def _default_mt5_files_dir() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "net.metaquotes.wine.metatrader5"
        / "drive_c"
        / "Program Files"
        / "MetaTrader 5"
        / "MQL5"
        / "Files"
    )


def _source_dirs(runtime_dir: Path) -> list[Path]:
    raw_dirs = [
        runtime_dir,
        Path(os.environ.get("QG_MT5_FILES_DIR", "")).expanduser() if os.environ.get("QG_MT5_FILES_DIR") else None,
        Path(os.environ.get("QG_HFM_FILES_DIR", "")).expanduser() if os.environ.get("QG_HFM_FILES_DIR") else None,
        _default_mt5_files_dir(),
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in raw_dirs:
        if not path:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _candidate_csvs(runtime_dir: Path) -> list[Path]:
    names = [
        "ShadowCandidateOutcomeLedger.csv",
        "QuantGod_ShadowCandidateOutcomeLedger.csv",
        "QuantGod_ShadowOutcomeLedger.csv",
        "QuantGod_CloseHistory.csv",
    ]
    paths: list[Path] = []
    for directory in _source_dirs(runtime_dir):
        paths.extend(directory / name for name in names)
        paths.extend(directory.glob("QuantGod_CloseHistory*.csv"))
        paths.extend((directory / "adaptive").glob("*Outcome*.csv") if (directory / "adaptive").exists() else [])
        paths.extend((directory / "journal").glob("*Outcome*.csv") if (directory / "journal").exists() else [])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _candidate_feedback_jsonl(runtime_dir: Path) -> list[Path]:
    names = [
        "QuantGod_LiveExecutionFeedback.jsonl",
        "QuantGod_LiveExecutionFeedbackHistory.jsonl",
        "execution/QuantGod_LiveExecutionFeedback.jsonl",
        "evidence_os/QuantGod_LiveExecutionFeedback.jsonl",
    ]
    paths = [directory / name for directory in _source_dirs(runtime_dir) for name in names]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _event_from_feedback(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    if not _is_usdjpy(row):
        return None
    profit_r = _float(row, "profitR", "r", "scoreR", default=0.0)
    direction = _direction(row)
    mfe_r, mae_r = _movement_pair(row, direction, profit_r)
    event = {
        "schema": "quantgod.execution_feedback.v1",
        "timestamp": _text(row, "timestamp", "createdAt", "generatedAt", "generatedAtServer", "eventTimeServer", default=_now_iso()),
        "symbol": FOCUS_SYMBOL,
        "strategyId": _text(row, "strategyId", "strategy", default="USDJPY_FEEDBACK_UNKNOWN"),
        "eventType": _text(row, "eventType", "event", "type", default="FEEDBACK_EVENT").upper(),
        "executionMode": _text(row, "executionMode", "lane", "mode", default="LIVE" if _text(row, "orderTicket", "dealTicket") else "SHADOW").upper(),
        "side": direction,
        "policyId": _text(row, "policyId", default=""),
        "intentId": _text(row, "intentId", default=""),
        "expectedPrice": _float(row, "expectedPrice", default=0.0),
        "fillPrice": _float(row, "fillPrice", default=0.0),
        "slippagePips": _float(row, "slippagePips", "slippage", default=0.0),
        "latencyMs": _float(row, "latencyMs", "latency", default=0.0),
        "spreadAtEntry": _float(row, "spreadAtEntry", "spread", "spreadPips", "SpreadPips", default=0.0),
        "profitR": profit_r,
        "mfeR": mfe_r,
        "maeR": mae_r,
        "rejectReason": _text(row, "rejectReason", default=""),
        "exitReason": _text(row, "exitReason", default=""),
        "source": source,
        "sourceKind": "existing_feedback",
        "sourceTier": _text(row, "sourceTier", "sourceAttribution", default="backfilled_history"),
    }
    event["entryContext"] = _entry_context(row, event, source)
    event["feedbackId"] = _text(row, "feedbackId", default="") or _fingerprint(event)
    return event if _complete(event) else None


def build_feedback(runtime_dir: Path, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    out_dir = ensure_dir(runtime_dir / OUTPUT_DIR)
    ledger_path = out_dir / FEEDBACK_LEDGER
    existing = read_jsonl(ledger_path, 10000)
    by_id = {_dedupe_key(row): row for row in existing if isinstance(row, dict)}
    source_counts: dict[str, int] = {}
    skipped = 0
    generated = 0
    for jsonl_path in _candidate_feedback_jsonl(runtime_dir):
        if jsonl_path == ledger_path:
            continue
        for row in read_jsonl(jsonl_path, 10000):
            source_name = str(jsonl_path.relative_to(jsonl_path.parent.parent)) if jsonl_path.parent.name in {"execution", "evidence_os"} else jsonl_path.name
            event = _event_from_feedback(row, source_name)
            if event is None:
                skipped += 1
                continue
            dedupe_key = _dedupe_key(event)
            if dedupe_key not in by_id:
                by_id[dedupe_key] = event
                generated += 1
                source_counts[source_name] = source_counts.get(source_name, 0) + 1
            else:
                updated = _maybe_update_shadow_measurement(by_id[dedupe_key], event)
                enriched = _maybe_enrich_entry_context(by_id[dedupe_key], event)
                if updated or enriched:
                    source_counts[source_name] = source_counts.get(source_name, 0) + 1
    for csv_path in _candidate_csvs(runtime_dir):
        for row in read_csv_rows(csv_path):
            source_name = csv_path.name
            event = None
            if "CloseHistory" in source_name:
                event = _event_from_close_history(row, source_name)
            if event is None:
                event = _event_from_shadow(row, source_name)
            if event is None:
                skipped += 1
                continue
            dedupe_key = _dedupe_key(event)
            if dedupe_key not in by_id:
                by_id[dedupe_key] = event
                generated += 1
                source_counts[source_name] = source_counts.get(source_name, 0) + 1
            else:
                updated = _maybe_update_shadow_measurement(by_id[dedupe_key], event)
                enriched = _maybe_enrich_entry_context(by_id[dedupe_key], event)
                if updated or enriched:
                    source_counts[source_name] = source_counts.get(source_name, 0) + 1
    rows = list(by_id.values())
    corrected = sum(1 for row in rows if isinstance(row, dict) and _correct_empty_raw_entry_context(row))
    complete_rows = [row for row in rows if _complete(row)]
    entry_context_coverage = _entry_context_coverage(complete_rows)
    entry_context_source_audit = _entry_context_source_audit(complete_rows)
    report = {
        "schema": SCHEMA,
        "generatedAt": _now_iso(),
        "status": "PASS" if len(complete_rows) >= 5 else "WARN",
        "summaryZh": "执行反馈样本已自动补齐" if len(complete_rows) >= 5 else "执行反馈样本仍需积累",
        "ledgerPath": str(ledger_path),
        "existingCount": len(existing),
        "generatedCount": generated,
        "sampleCount": len(rows),
        "completeSampleCount": len(complete_rows),
        "entryContextCoverage": entry_context_coverage,
        "entryContextSourceAudit": entry_context_source_audit,
        "correctedEmptyRawContextCount": corrected,
        "skippedRows": skipped,
        "sourceCounts": source_counts,
        "safety": SAFETY,
        "nextActionsZh": [
            "继续让 EA / shadow 链路写入 execution feedback",
            "P4-6 会读取该 ledger 并更新覆盖率",
        ],
    }
    if write:
        write_jsonl(ledger_path, rows)
        write_json(out_dir / PRODUCER_REPORT, report)
    return report


def load_latest(runtime_dir: Path) -> dict[str, Any] | None:
    return read_json(Path(runtime_dir) / OUTPUT_DIR / PRODUCER_REPORT, None)


def write_sample(runtime_dir: Path, overwrite: bool = False) -> dict[str, str]:
    runtime_dir = Path(runtime_dir)
    csv_path = runtime_dir / "ShadowCandidateOutcomeLedger.csv"
    if csv_path.exists() and not overwrite:
        return {"sample": str(csv_path)}
    ensure_dir(runtime_dir)
    csv_path.write_text(
        "timestamp,symbol,strategy,entryPrice,exitPrice,profitR,mfeR,maeR,spreadAtEntry\n"
        "2026-05-13T00:00:00Z,USDJPYc,USDJPY_RSI_REVERSAL_LONG_V1,155.10,155.18,0.32,0.58,-0.12,0.8\n"
        "2026-05-13T01:00:00Z,USDJPYc,USDJPY_RSI_REVERSAL_LONG_V1,155.20,155.14,-0.24,0.10,-0.35,0.9\n",
        encoding="utf-8",
    )
    return {"sample": str(csv_path)}
