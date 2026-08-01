"""Plain-language Strategy Factory intent planner.

This module turns an operator's plain-language trading intent into safe
Strategy JSON seeds plus an evolution contract. It does not run a model, place
orders, authorize wallets, or mutate live presets.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

try:
    from tools.strategy_ga.personality_lock import build_personality_lock
    from tools.strategy_json.schema import FOCUS_SYMBOL, base_strategy_seed
    from tools.strategy_json.validator import validate_strategy_json
except ModuleNotFoundError:  # pragma: no cover
    from strategy_ga.personality_lock import build_personality_lock
    from strategy_json.schema import FOCUS_SYMBOL, base_strategy_seed
    from strategy_json.validator import validate_strategy_json

from .archive import load_json, write_json
from .schema import SAFETY, SCHEMA_INTENT_PLAN, intent_plan_path, utc_now_iso


def _stable_id(prompt: str) -> str:
    digest = hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()[:12]
    return f"QG-INTENT-{digest.upper()}"


def _contains_any(text: str, words: List[str]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _infer_directions(text: str) -> List[str]:
    if _contains_any(text, ["多空", "双向", "both", "long and short"]):
        return ["LONG", "SHORT"]
    if _contains_any(text, ["做空", "偏空", "short", "sell"]):
        return ["SHORT"]
    return ["LONG"]


def _infer_family(text: str) -> str:
    if _contains_any(text, ["震荡", "均值", "回归", "range", "mean"]):
        return "RSI_Reversal"
    if _contains_any(text, ["突破", "breakout", "箱体"]):
        return "USDJPY_TOKYO_RANGE_BREAKOUT"
    if _contains_any(text, ["趋势", "trend", "回调"]):
        return "USDJPY_H4_TREND_PULLBACK"
    return "RSI_Reversal"


def _infer_risk_profile(text: str) -> Dict[str, Any]:
    low_risk = _contains_any(text, ["稳健", "保守", "别太高", "低杠杆", "低风险", "conservative"])
    aggressive = _contains_any(text, ["激进", "高杠杆", "aggressive"])
    drawdown_stop_pct = 10.0 if _contains_any(text, ["10", "百分之十", "10%"]) else (6.0 if low_risk else 12.0)
    return {
        "profile": "AGGRESSIVE" if aggressive else ("CONSERVATIVE" if low_risk else "BALANCED"),
        "maxDrawdownStopPct": drawdown_stop_pct,
        "leverageBand": "LOW" if low_risk else ("HIGH" if aggressive else "MEDIUM"),
        "opportunityLotMultiplierLocked": True,
    }


def _signal_weight(value: float) -> float:
    return round(max(0.05, min(0.50, value)), 2)


def _infer_signal_system(text: str, family: str, risk_profile: Dict[str, Any]) -> Dict[str, Any]:
    range_style = family == "RSI_Reversal"
    breakout_style = family == "USDJPY_TOKYO_RANGE_BREAKOUT"
    trend_style = family == "USDJPY_H4_TREND_PULLBACK"
    conservative = risk_profile["profile"] == "CONSERVATIVE"
    weights = {
        "trend": _signal_weight(0.18 + (0.10 if trend_style else 0.0) + (0.04 if breakout_style else 0.0)),
        "momentum": _signal_weight(0.24 + (0.04 if breakout_style else 0.0)),
        "meanReversion": _signal_weight(0.26 + (0.10 if range_style else 0.0)),
        "volume": _signal_weight(0.12 + (0.04 if breakout_style else 0.0)),
        "volatility": _signal_weight(0.20 + (0.05 if conservative else 0.0)),
    }
    total = sum(weights.values()) or 1.0
    normalized = {key: round(value / total, 3) for key, value in weights.items()}
    return {
        "schema": "quantgod.strategy_factory.five_dimensional_signal.v1",
        "normalization": "weighted_sum_0_to_100",
        "dimensions": {
            "trend": {
                "weight": normalized["trend"],
                "features": ["ema_fast_slow_cross", "supertrend_direction", "h4_pullback_alignment"],
            },
            "momentum": {
                "weight": normalized["momentum"],
                "features": ["rsi_crossback", "macd_histogram_slope", "rsi_divergence_hint"],
            },
            "meanReversion": {
                "weight": normalized["meanReversion"],
                "features": ["bollinger_reclaim", "rsi_band_reentry", "night_reversion_window"],
            },
            "volume": {
                "weight": normalized["volume"],
                "features": ["obv_slope_proxy", "tick_density", "volume_price_confirmation"],
            },
            "volatility": {
                "weight": normalized["volatility"],
                "features": ["atr_expansion", "spread_tier", "range_contraction_breakout"],
            },
        },
        "thresholds": {
            "standardEntryScore": 70,
            "opportunityEntryScore": 45,
            "blockScoreBelow": 35,
            "riskOffScorePenalty": 15 if conservative else 8,
        },
    }


def _structured_parameters(family: str, directions: List[str], risk_profile: Dict[str, Any]) -> Dict[str, Any]:
    conservative = risk_profile["profile"] == "CONSERVATIVE"
    parameters: Dict[str, Any] = {
        "symbol": FOCUS_SYMBOL,
        "strategyFamily": family,
        "directions": directions,
        "entryMode": "OPPORTUNITY_ENTRY",
        "entryPosture": "CENT_OPPORTUNITY_SAMPLE_FIRST",
        "maxDrawdownStopPct": risk_profile["maxDrawdownStopPct"],
        "leverageBand": risk_profile["leverageBand"],
        "riskProfile": risk_profile["profile"],
        "opportunityLotMultiplier": 0.20 if conservative else 0.28,
        "standardEntryScore": 70,
        "opportunityEntryScore": 45,
        "signalQuorumStandard": 3,
        "signalQuorumOpportunity": 2,
        "runtimeFreshSoftSeconds": 30,
        "runtimeHardStaleSeconds": 90,
        "spreadNormalPips": 2.2,
        "spreadSoftPips": 2.7,
        "spreadHardPips": 3.0,
        "newsHardBlock": True,
        "newsSoftDowngrade": True,
        "rsiPeriod": 14,
        "rsiBuyBand": 34,
        "rsiCrossbackThreshold": 0.8,
        "emaFastPeriod": 20,
        "emaSlowPeriod": 50,
        "supertrendPeriod": 10,
        "supertrendMultiplier": 3.0,
        "macdFastPeriod": 12,
        "macdSlowPeriod": 26,
        "macdSignalPeriod": 9,
        "bollingerPeriod": 20,
        "bollingerDeviation": 2.0,
        "obvLookbackBars": 24,
        "volumePriceConfirmBars": 3,
        "atrPeriod": 14,
        "atrBreakoutMultiplier": 1.2,
        "breakevenDelayR": 1.0,
        "trailStartR": 1.5,
        "mfeGivebackPct": 0.6,
        "timeStopM15Bars": 6,
    }
    locked = [
        "symbol",
        "strategyFamily",
        "directions",
        "riskProfile",
        "leverageBand",
        "maxDrawdownStopPct",
        "opportunityLotMultiplier",
    ]
    return {
        "schema": "quantgod.strategy_factory.structured_parameters.v1",
        "parameterCount": len(parameters),
        "parameters": parameters,
        "lockedParameterKeys": locked,
        "mutableParameterFamilies": ["indicators", "thresholds", "exit", "session_windows"],
    }


def _seed_for_direction(intent_id: str, family: str, direction: str, risk_profile: Dict[str, Any]) -> Dict[str, Any]:
    seed = base_strategy_seed(f"{intent_id}-{direction}", family=family, direction=direction)
    seed["source"] = "PLAIN_LANGUAGE_INTENT"
    seed["intentId"] = intent_id
    seed["risk"]["stage"] = "SHADOW"
    if risk_profile["profile"] == "CONSERVATIVE":
        seed["risk"]["opportunityLotMultiplier"] = 0.20
    elif risk_profile["profile"] == "AGGRESSIVE":
        seed["risk"]["opportunityLotMultiplier"] = 0.35
    else:
        seed["risk"]["opportunityLotMultiplier"] = 0.28
    seed["risk"]["maxDrawdownStopPct"] = risk_profile["maxDrawdownStopPct"]
    return seed


def build_intent_plan(runtime_dir, prompt: str, *, write: bool = True) -> Dict[str, Any]:
    text = str(prompt or "").strip()
    if not text:
        text = "USDJPY RSI 反转，低风险，小仓机会入场，先 shadow/replay 验证。"
    intent_id = _stable_id(text)
    directions = _infer_directions(text)
    family = _infer_family(text)
    risk_profile = _infer_risk_profile(text)
    signal_system = _infer_signal_system(text, family, risk_profile)
    structured_parameters = _structured_parameters(family, directions, risk_profile)
    seeds = [_seed_for_direction(intent_id, family, direction, risk_profile) for direction in directions]
    validations = [validate_strategy_json(seed) for seed in seeds]
    personality_locks = [
        {
            "seedId": seed.get("seedId"),
            "strategyId": seed.get("strategyId"),
            "personalityLock": build_personality_lock(seed),
        }
        for seed in seeds
    ]
    plan = {
        "ok": True,
        "schema": SCHEMA_INTENT_PLAN,
        "generatedAt": utc_now_iso(),
        "intentId": intent_id,
        "prompt": text,
        "scope": {
            "tradableImplementation": "MT5_USDJPY_STRATEGY_JSON_ONLY",
            "symbol": FOCUS_SYMBOL,
            "reasonZh": "本系统当前只把自然语言意图落到 USDJPY Strategy JSON。",
        },
        "inferredPersonality": {
            "strategyFamily": family,
            "directions": directions,
            "riskProfile": risk_profile,
            "entryPosture": "CENT_OPPORTUNITY_SAMPLE_FIRST",
        },
        "signalSystem": signal_system,
        "structuredParameters": structured_parameters,
        "lockedPersonality": {
            "symbol": FOCUS_SYMBOL,
            "strategyFamily": family,
            "directions": directions,
            "riskProfile": risk_profile["profile"],
            "riskKernelLocked": True,
            "directionBiasLocked": True,
            "maxDrawdownStopPct": risk_profile["maxDrawdownStopPct"],
        },
        "evolutionPolicy": {
            "schema": "quantgod.strategy_factory.evolution_policy.v1",
            "personalityLocked": True,
            "tacticalMutationBoundsPct": 30.0,
            "walkForwardRequired": True,
            "reflectionCadence": "after_each_walk_forward_segment",
            "forbiddenOptimizations": [
                "change_symbol",
                "change_direction_bias",
                "raise_risk_kernel_to_fit_history",
                "enable_order_send",
            ],
            "reasonZh": "进化只能微调指标、入场确认和出场节奏；不能为了历史收益改方向、风险内核或执行权限。",
        },
        "seedStrategies": seeds,
        "seedPersonalityLocks": personality_locks,
        "validation": {
            "validSeedCount": sum(1 for row in validations if row.get("valid")),
            "results": validations,
        },
        "nextActions": [
            "run_strategy_ga.py run-generation --write",
            "run_strategy_ga_factory.py build --write",
            "run_entry_latency.py build --write",
        ],
        "safety": dict(SAFETY),
    }
    if write:
        write_json(intent_plan_path(runtime_dir), plan)
    return plan


def read_intent_plan(runtime_dir) -> Dict[str, Any]:
    payload = load_json(intent_plan_path(runtime_dir))
    if payload:
        return {"ok": True, **payload}
    return {
        "ok": True,
        "schema": SCHEMA_INTENT_PLAN,
        "status": "WAITING_INTENT_PLAN",
        "reasonZh": "尚未生成自然语言 Strategy Factory intent plan。",
        "safety": dict(SAFETY),
    }
