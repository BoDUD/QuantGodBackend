from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any

from .schema import PolicyThresholds

def _consecutive_losses(items: list[dict[str, Any]]) -> int:
    count = 0
    for row in reversed(items):
        if row.get("scoreR", 0.0) < 0:
            count += 1
        else:
            break
    return count

def _status_for(samples: int, win_rate: float, avg_r: float, consecutive_losses: int, thresholds: PolicyThresholds) -> tuple[str, str, float]:
    if samples < thresholds.min_samples:
        return "INSUFFICIENT_DATA", "样本不足，仅允许观察复核", 0.0
    if avg_r <= thresholds.pause_avg_score_r:
        return "PAUSED", "近期平均影子收益为负，暂停该方向建议", 0.0
    if win_rate < thresholds.pause_win_rate:
        return "PAUSED", "近期胜率低于暂停阈值，暂停该方向建议", 0.0
    if consecutive_losses >= thresholds.max_consecutive_losses:
        return "PAUSED", "连续负向样本过多，暂停该方向建议", 0.0
    if samples >= thresholds.active_min_samples and win_rate >= thresholds.min_win_rate and avg_r >= thresholds.min_avg_score_r:
        return "ACTIVE_SHADOW_OK", "影子样本通过，允许继续观察", min(1.5, max(0.1, 0.5 + avg_r))
    return "WATCH_ONLY", "样本未达主动标准，仅保留观察", 0.25

def score_routes(observations: list[dict[str, Any]], thresholds: PolicyThresholds) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        direction = obs.get("direction", "FLAT")
        if direction == "FLAT":
            continue
        key = (
            str(obs.get("symbol") or "UNKNOWN"),
            str(obs.get("strategy") or "UNKNOWN"),
            direction,
            str(obs.get("regime") or "UNKNOWN"),
        )
        groups[key].append(obs)

    scored: list[dict[str, Any]] = []
    for (symbol, strategy, direction, regime), items in sorted(groups.items()):
        samples = len(items)
        wins = sum(1 for item in items if item.get("scoreR", 0.0) > 0)
        win_rate = wins / samples if samples else 0.0
        avg_r = mean(float(item.get("scoreR", 0.0)) for item in items) if items else 0.0
        median_r = median(float(item.get("scoreR", 0.0)) for item in items) if items else 0.0
        avg_mfe = mean(abs(float(item.get("mfe", 0.0))) for item in items) if items else 0.0
        avg_mae = mean(abs(float(item.get("mae", 0.0))) for item in items) if items else 0.0
        consecutive_losses = _consecutive_losses(items)
        status, reason, risk_multiplier = _status_for(samples, win_rate, avg_r, consecutive_losses, thresholds)
        quality_profile = _memory_quality_profile(items)
        scored.append({
            "symbol": symbol,
            "strategy": strategy,
            "direction": direction,
            "directionLabel": "买入观察" if direction == "LONG" else "卖出观察",
            "regime": regime,
            "samples": samples,
            "wins": wins,
            "losses": samples - wins,
            "winRate": round(win_rate, 4),
            "avgScoreR": round(avg_r, 4),
            "medianScoreR": round(median_r, 4),
            "avgMfe": round(avg_mfe, 4),
            "avgMae": round(avg_mae, 4),
            "consecutiveLosses": consecutive_losses,
            "memoryQualityProfile": quality_profile,
            "state": status,
            "riskMultiplier": round(risk_multiplier, 4),
            "reason": reason,
        })
    scored.sort(key=lambda row: (row["state"] == "PAUSED", -row["avgScoreR"], -row["winRate"], row["symbol"]))
    return scored


def _memory_quality_profile(items: list[dict[str, Any]]) -> dict[str, Any]:
    data_gaps: Counter[str] = Counter()
    adverse_factors: Counter[str] = Counter()
    exit_quality: Counter[str] = Counter()
    for item in items:
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        coverage = _raw_float(raw, "dataCoverageScore", "dataCoverage", "coverageScore")
        professional = _raw_float(raw, "professionalScore", "proScore")
        if coverage is not None and coverage < 0.7:
            data_gaps["dataCoverage"] += 1
        if professional is not None and professional < 0.65:
            data_gaps["professionalScore"] += 1
        for factor, spec in _ADVERSE_FACTOR_DEFS.items():
            value = _raw_factor_float(raw, *spec["keys"])
            if value is None:
                data_gaps[f"missingFactor:{factor}"] += 1
                continue
            if _is_adverse_factor(value, spec):
                adverse_factors[factor] += 1
        for tag in _loss_tags(raw):
            if tag == "LOW_COVERAGE_LOSS":
                data_gaps["dataCoverage"] += 1
            elif tag == "FLOW_ADVERSE":
                adverse_factors["fundFlow"] += 1
            elif tag == "NEWS_ADVERSE":
                adverse_factors["news"] += 1
            elif tag == "SMART_MONEY_ADVERSE":
                adverse_factors["smartMoney"] += 1
            elif tag == "KRONOS_ADVERSE":
                adverse_factors["kronos"] += 1
            elif tag == "FAKE_BREAKOUT":
                adverse_factors["breakoutConfirmation"] += 1
            elif tag == "CHASE_PULLBACK":
                adverse_factors["entryTiming"] += 1
            elif tag == "HIGH_EXECUTION_RISK":
                adverse_factors["executionRisk"] += 1
        for tag in _exit_quality_tags(raw):
            exit_quality[tag] += 1
    sample_count = len(items)
    return {
        "schema": "quantgod.adaptive_route_memory_quality_profile.v1",
        "sampleCount": sample_count,
        "dataGaps": _counter_rows(data_gaps, sample_count, "gap"),
        "adverseFactors": _counter_rows(adverse_factors, sample_count, "factor"),
        "exitQualityPatterns": _counter_rows(exit_quality, sample_count, "tag"),
    }


def _counter_rows(counter: Counter[str], sample_count: int, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, count in counter.most_common():
        rows.append({key: name, "count": count, "ratio": round(count / sample_count, 4) if sample_count else 0.0})
    return rows[:12]


def _loss_tags(raw: dict[str, Any]) -> list[str]:
    value = raw.get("lossTags") if isinstance(raw, dict) else []
    return _tag_list(value)


def _exit_quality_tags(raw: dict[str, Any]) -> list[str]:
    value = raw.get("exitQualityTags") if isinstance(raw, dict) else []
    return _tag_list(value)


def _tag_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).upper() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        normalized = value.replace("；", ",").replace(";", ",").replace("|", ",")
        return [part.strip().upper() for part in normalized.split(",") if part.strip()]
    return []


_ADVERSE_FACTOR_DEFS = {
    "atr": {"keys": ("atr", "ATR", "atrPips"), "mode": "none", "threshold": 0.0},
    "trend": {"keys": ("trendScore", "trend"), "mode": "lt", "threshold": -0.15},
    "sentiment": {"keys": ("sentimentScore", "sentiment"), "mode": "lt", "threshold": -0.15},
    "openInterest": {"keys": ("openInterestChange", "oiChange", "openInterest"), "mode": "lt", "threshold": -0.15},
    "fundFlow": {"keys": ("fundFlowScore", "fundFlow"), "mode": "lt", "threshold": -0.15},
    "news": {"keys": ("newsScore", "news"), "mode": "lt", "threshold": -0.15},
    "smartMoney": {"keys": ("smartMoneyScore", "smartMoney"), "mode": "lt", "threshold": -0.15},
    "predictionMarket": {"keys": ("predictionMarketScore", "predictionMarket"), "mode": "lt", "threshold": -0.15},
    "kronos": {"keys": ("kronosScore", "kronos"), "mode": "lt", "threshold": -0.15},
    "executionRisk": {"keys": ("executionRiskScore", "executionRisk"), "mode": "gt", "threshold": 0.60},
    "entryTiming": {"keys": ("entryTimingScore", "entryTiming"), "mode": "lt", "threshold": 0.45},
}


def _is_adverse_factor(value: float, spec: dict[str, Any]) -> bool:
    if spec.get("mode") == "none":
        return False
    threshold = float(spec.get("threshold", 0.0))
    if spec.get("mode") == "gt":
        return value > threshold
    return value < threshold


def _raw_factor_float(raw: dict[str, Any], *keys: str) -> float | None:
    value = _raw_float(raw, *keys)
    if value is not None:
        return value
    factors = raw.get("factors") if isinstance(raw.get("factors"), dict) else {}
    return _raw_float(factors, *keys)


def _raw_float(raw: dict[str, Any], *keys: str) -> float | None:
    value = _first_value(raw, *keys)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _first_value(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    lower = {str(key).lower(): value for key, value in raw.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def best_route_for_symbol(scored_routes: list[dict[str, Any]], symbol: str, direction: str | None = None) -> dict[str, Any] | None:
    routes = [r for r in scored_routes if str(r.get("symbol", "")).upper() == symbol.upper()]
    if direction:
        routes = [r for r in routes if r.get("direction") == direction]
    if not routes:
        return None
    allowed = [r for r in routes if r.get("state") in {"ACTIVE_SHADOW_OK", "WATCH_ONLY"}]
    source = allowed or routes
    return sorted(source, key=lambda r: (r.get("state") != "ACTIVE_SHADOW_OK", -float(r.get("avgScoreR", 0)), -float(r.get("winRate", 0))))[0]
