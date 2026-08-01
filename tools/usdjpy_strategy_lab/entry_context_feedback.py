from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .schema import FOCUS_SYMBOL, READ_ONLY_SAFETY


ENTRY_CONTEXT_LEDGER = "QuantGod_LiveExecutionFeedback.jsonl"


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _unit(value: Any, default: float | None = None) -> float | None:
    number = _num(value, default)
    if number is None:
        return None
    if 1.0 < number <= 100.0:
        number = number / 100.0
    return round(max(0.0, min(1.0, number)), 4)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _side(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"BUY", "LONG", "1"}:
        return "LONG"
    if text in {"SELL", "SHORT", "-1"}:
        return "SHORT"
    return text or "UNKNOWN"


def _regime_trend_score(regime: Any) -> float | None:
    text = str(regime or "").upper()
    if not text or text == "UNKNOWN":
        return None
    if "TREND" in text and ("UP" in text or "BULL" in text):
        return 0.72
    if "TREND" in text and ("DOWN" in text or "BEAR" in text):
        return 0.28
    if "TREND" in text:
        return 0.62
    if "RANGE" in text:
        return 0.42
    return 0.50


def _news_score(news_gate: dict[str, Any]) -> float | None:
    if not news_gate:
        return None
    if news_gate.get("hardBlock"):
        return 0.05
    risk = str(news_gate.get("riskLevel") or news_gate.get("mode") or "").upper()
    if risk in {"NONE", "LOW", "NORMAL", "ALLOW"}:
        return 0.85
    if risk in {"MEDIUM", "WATCH", "SOFT"}:
        return 0.55
    if risk in {"HIGH", "BLOCK"}:
        return 0.20
    return 0.65


def _spread_execution_risk(spread_gate: dict[str, Any], runtime_tier: str, news_gate: dict[str, Any]) -> float:
    tier = str(spread_gate.get("tier") or "").upper()
    if tier == "NORMAL":
        risk = 0.15
    elif tier == "SOFT_WIDE":
        risk = 0.35
    elif tier == "SOFT_WIDE_HIGH":
        risk = 0.55
    elif tier == "HARD_WIDE":
        risk = 0.90
    else:
        risk = 0.45
    runtime = str(runtime_tier or "").upper()
    if runtime == "SOFT_STALE":
        risk += 0.12
    elif runtime not in {"FRESH", "OK", "GOOD"}:
        risk += 0.22
    if news_gate.get("hardBlock"):
        risk += 0.25
    return round(_clamp(risk), 4)


def _sltp_number(top_policy: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _num(top_policy.get(key))
        if value is not None:
            return value
    return None


def _risk_plan(top_policy: dict[str, Any]) -> dict[str, Any]:
    stop_pips = _sltp_number(top_policy, "initialStopPips", "stopLossPips", "stopLossPriceMove")
    tp1_pips = _sltp_number(top_policy, "target1Pips", "firstTakeProfitPips", "takeProfitPips")
    tp2_pips = _sltp_number(top_policy, "target2Pips", "secondTakeProfitPips", "takeProfitPriceMove")
    if tp2_pips is None:
        tp2_pips = tp1_pips
    target_r = None
    if stop_pips and tp2_pips:
        target_r = round(max(0.1, tp2_pips / stop_pips), 4)
    return {
        "stopLossR": 1.0,
        "targetR": target_r,
        "firstTakeProfitR": round(tp1_pips / stop_pips, 4) if stop_pips and tp1_pips else None,
        "secondTakeProfitR": target_r,
        "trailStartR": _num(top_policy.get("trailStartR")),
        "givebackPct": _num(top_policy.get("mfeGivebackPct"), 0.35),
        "timeoutMinutes": (_num(top_policy.get("timeStopBars"), 0.0) or 0.0) * 15.0,
        "stopLossPips": stop_pips,
        "takeProfitPips": tp2_pips,
    }


def _availability(context: dict[str, Any]) -> dict[str, Any]:
    groups = {
        "scores": ("totalScore", "dataCoverage", "proScore", "marketQuality", "entryTiming", "fundFlow", "executionRisk", "resonanceCount"),
        "factors": ("atrPips", "trend", "sentiment", "oiChange", "news", "smartMoney", "kronos"),
        "estimates": ("ev", "winProbability", "riskReward", "positionScale"),
        "riskPlan": ("stopLossR", "targetR", "firstTakeProfitR", "secondTakeProfitR", "trailStartR", "givebackPct", "timeoutMinutes", "stopLossPips", "takeProfitPips"),
    }
    rows: list[dict[str, Any]] = []
    total = 0
    present = 0
    for name, fields in groups.items():
        section = context.get(name) if isinstance(context.get(name), dict) else {}
        available = sum(1 for field in fields if section.get(field) not in (None, ""))
        total += len(fields)
        present += available
        rows.append(
            {
                "category": name,
                "availableCount": available,
                "fieldCount": len(fields),
                "coverageRatio": round(available / len(fields), 4),
            }
        )
    return {
        "coverageRatio": round(present / total, 4) if total else 0.0,
        "categories": rows,
        "noteZh": "RAW 表示决策时真实写入；缺失外部因子保持空值，不用中性值伪造。",
    }


def build_entry_context_feedback_event(
    *,
    policy: dict[str, Any],
    top_policy: dict[str, Any],
    generated_at: str,
    event_type: str,
    source_name: str,
) -> dict[str, Any]:
    top_policy = dict(top_policy or {})
    evidence = policy.get("evidence") if isinstance(policy.get("evidence"), dict) else {}
    news_gate = top_policy.get("newsGate") if isinstance(top_policy.get("newsGate"), dict) else policy.get("newsGate") or {}
    spread_gate = top_policy.get("spreadGate") if isinstance(top_policy.get("spreadGate"), dict) else policy.get("spreadGate") or {}
    runtime_tier = str(top_policy.get("runtimeFreshnessTier") or evidence.get("runtimeFreshnessTier") or "UNKNOWN")
    score = _unit(top_policy.get("score"), 0.0) or 0.0
    quorum = _num(top_policy.get("signalQuorum"), 0.0) or 0.0
    quorum_required = max(1.0, _num(top_policy.get("signalQuorumRequired"), 2.0) or 2.0)
    trigger_score = _unit((top_policy.get("tacticalConfirmations") or {}).get("triggerScore"), None) if isinstance(top_policy.get("tacticalConfirmations"), dict) else None
    entry_timing = round(_clamp(((quorum / quorum_required) * 0.65) + ((trigger_score if trigger_score is not None else score) * 0.35)), 4)
    execution_risk = _spread_execution_risk(spread_gate, runtime_tier, news_gate if isinstance(news_gate, dict) else {})
    market_quality = round(_clamp((score * 0.45) + (entry_timing * 0.25) + ((1.0 - execution_risk) * 0.30)), 4)
    risk_plan = _risk_plan(top_policy)
    risk_reward = _num(risk_plan.get("targetR"), 1.5) or 1.5
    win_probability = round(_clamp(0.42 + score * 0.22 + entry_timing * 0.20 + market_quality * 0.16 - execution_risk * 0.12), 4)
    ev = round((win_probability * risk_reward) - (1.0 - win_probability), 4)
    max_lot = max(0.01, _num(top_policy.get("maxLot") or policy.get("maxLot"), 1.0) or 1.0)
    recommended_lot = _num(top_policy.get("recommendedLot"), 0.0) or 0.0
    context = {
        "contextQuality": "RAW",
        "contextQualityReasonZh": "USDJPY policy dry-run/live-loop 在决策时写入的只读入场上下文；仅供复盘、A/B 和升级证据，不代表已下单。",
        "proxySource": "",
        "entryTime": generated_at,
        "symbol": FOCUS_SYMBOL,
        "side": _side(top_policy.get("direction")),
        "strategyVersion": top_policy.get("strategy") or "UNKNOWN_STRATEGY",
        "leverage": 0.0,
        "marginUsd": 0.0,
        "notionalUsd": 0.0,
        "candidateSource": source_name,
        "reasons": list(top_policy.get("reasons") or [])[:12],
        "scores": {
            "totalScore": score,
            "dataCoverage": None,
            "proScore": score,
            "marketQuality": market_quality,
            "entryTiming": entry_timing,
            "fundFlow": None,
            "executionRisk": execution_risk,
            "resonanceCount": int(quorum),
        },
        "factors": {
            "atrPips": _sltp_number(top_policy, "atrPips", "atr"),
            "trend": _regime_trend_score(top_policy.get("regime")),
            "sentiment": None,
            "oiChange": None,
            "news": _news_score(news_gate if isinstance(news_gate, dict) else {}),
            "smartMoney": None,
            "kronos": None,
        },
        "estimates": {
            "ev": ev,
            "winProbability": win_probability,
            "riskReward": risk_reward,
            "positionScale": round(_clamp(recommended_lot / max_lot), 4),
        },
        "riskPlan": risk_plan,
        "factorAttributionSummary": f"policy={top_policy.get('strategy') or 'UNKNOWN'} {top_policy.get('direction') or 'UNKNOWN'} score={score:.2f} quorum={int(quorum)}/{int(quorum_required)} spread={spread_gate.get('tier') or 'UNKNOWN'} news={news_gate.get('mode') if isinstance(news_gate, dict) else 'UNKNOWN'}",
    }
    context["factorAvailability"] = _availability(context)
    context["scores"]["dataCoverage"] = context["factorAvailability"]["coverageRatio"]
    event = {
        "schema": "quantgod.execution_feedback.v1",
        "timestamp": generated_at,
        "symbol": FOCUS_SYMBOL,
        "strategyId": context["strategyVersion"],
        "eventType": event_type,
        "executionMode": "SHADOW",
        "side": context["side"],
        "policyId": str(top_policy.get("entryStrictness") or top_policy.get("entryMode") or ""),
        "intentId": "",
        "expectedPrice": 0.0,
        "fillPrice": 0.0,
        "slippagePips": 0.0,
        "latencyMs": 0.0,
        "spreadAtEntry": _num(spread_gate.get("spreadPips"), 0.0) if isinstance(spread_gate, dict) else 0.0,
        "profitR": 0.0,
        "mfeR": 0.0,
        "maeR": 0.0,
        "rejectReason": "",
        "exitReason": "",
        "source": source_name,
        "sourceKind": "entry_context",
        "sourceTier": "policy_decision_raw",
        "entryContext": context,
        "safety": dict(READ_ONLY_SAFETY),
    }
    key = json.dumps(
        {
            "timestamp": generated_at,
            "eventType": event_type,
            "strategy": event["strategyId"],
            "side": event["side"],
            "entryMode": top_policy.get("entryMode"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    event["feedbackId"] = "entry-context-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return event


def append_entry_context_feedback(
    runtime_dir: Path,
    *,
    policy: dict[str, Any],
    top_policy: dict[str, Any],
    generated_at: str,
    event_type: str,
    source_name: str,
) -> dict[str, Any]:
    event = build_entry_context_feedback_event(
        policy=policy,
        top_policy=top_policy,
        generated_at=generated_at,
        event_type=event_type,
        source_name=source_name,
    )
    ledger = Path(runtime_dir) / "evidence_os" / ENTRY_CONTEXT_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event
