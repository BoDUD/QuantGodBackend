from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from .personality_lock import personality_lock_report


def mutate_seed(parent: Dict[str, Any], seed_id: str, generation: int, offset: int) -> Dict[str, Any]:
    """Mutate only strategy parameters, never safety or live permissions."""
    seed = deepcopy(parent)
    seed["seedId"] = seed_id
    seed["source"] = "MUTATION"
    seed["parentSeedId"] = parent.get("seedId")
    seed["strategyId"] = f"{parent.get('strategyId', 'USDJPY_STRATEGY')}_MUT_{generation:03d}_{offset:03d}"
    rsi = seed.setdefault("indicators", {}).setdefault("rsi", {})
    indicators = seed.setdefault("indicators", {})
    exit_cfg = seed.setdefault("exit", {})
    risk = seed.setdefault("risk", {})

    rsi["period"] = max(2, min(50, int(rsi.get("period", 14)) + ((offset % 3) - 1)))
    rsi["buyBand"] = max(20, min(45, float(rsi.get("buyBand", 34)) + ((offset % 5) - 2)))
    rsi["crossbackThreshold"] = round(max(0, min(3, float(rsi.get("crossbackThreshold", 0.8)) + (offset % 4 - 1) * 0.1)), 2)
    _mutate_family_parameters(indicators, offset)
    exit_cfg["breakevenDelayR"] = round(max(0, min(3, float(exit_cfg.get("breakevenDelayR", 1.0)) + (offset % 3) * 0.05)), 2)
    exit_cfg["trailStartR"] = round(max(0, min(5, float(exit_cfg.get("trailStartR", 1.5)) + (offset % 4 - 1) * 0.1)), 2)
    exit_cfg["mfeGivebackPct"] = round(max(0.1, min(0.9, float(exit_cfg.get("mfeGivebackPct", 0.6)) + (offset % 5 - 2) * 0.02)), 2)
    risk["opportunityLotMultiplier"] = float((parent.get("risk") or {}).get("opportunityLotMultiplier", risk.get("opportunityLotMultiplier", 0.35)))
    risk["stage"] = "SHADOW"
    risk["maxLot"] = min(2.0, float(risk.get("maxLot", 2.0)))
    seed["personalityLockAudit"] = personality_lock_report(parent, seed)
    return seed


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _mutate_int(config: Dict[str, Any], key: str, default: int, delta: int, low: int, high: int) -> None:
    value = int(_num(config.get(key), default)) + delta
    config[key] = max(low, min(high, value))


def _mutate_float(config: Dict[str, Any], key: str, default: float, delta: float, low: float, high: float, digits: int = 3) -> None:
    value = _num(config.get(key), default) + delta
    config[key] = round(max(low, min(high, value)), digits)


def _mutate_family_parameters(indicators: Dict[str, Any], offset: int) -> None:
    """Mutate family-specific Strategy JSON knobs without touching safety."""
    step = (offset % 5) - 2

    ma = indicators.setdefault("ma", {})
    _mutate_int(ma, "fastPeriod", 9, step, 2, 80)
    _mutate_int(ma, "slowPeriod", 21, step * 2, 3, 240)
    if int(ma["fastPeriod"]) >= int(ma["slowPeriod"]):
        ma["slowPeriod"] = int(ma["fastPeriod"]) + 1

    bollinger = indicators.setdefault("bollinger", {})
    _mutate_int(bollinger, "period", 20, step * 2, 5, 120)
    _mutate_float(bollinger, "deviations", 2.0, step * 0.1, 0.5, 4.0, 2)
    _mutate_float(bollinger, "reclaimBufferPips", 0.0, max(0, offset % 4) * 0.25, 0.0, 30.0, 2)

    macd = indicators.setdefault("macd", {})
    _mutate_int(macd, "fastPeriod", 12, step, 2, 80)
    _mutate_int(macd, "slowPeriod", 26, step * 2, 3, 160)
    if int(macd["fastPeriod"]) >= int(macd["slowPeriod"]):
        macd["slowPeriod"] = int(macd["fastPeriod"]) + 1
    _mutate_int(macd, "signalPeriod", 9, (offset % 3) - 1, 2, 80)
    _mutate_float(macd, "minHistogramAbs", 0.0, (offset % 4) * 0.0005, 0.0, 1.0, 4)

    support_resistance = indicators.setdefault("supportResistance", {})
    _mutate_int(support_resistance, "lookbackBars", 24, step * 4, 4, 240)
    _mutate_float(support_resistance, "breakoutBufferPips", 0.0, (offset % 4) * 0.5, 0.0, 50.0, 2)

    tokyo = indicators.setdefault("tokyoRange", {})
    _mutate_int(tokyo, "tradeStartHourUtc", 3, step, 0, 23)
    _mutate_int(tokyo, "tradeEndHourUtc", 6, step, 0, 23)
    tokyo["rangeStartHourUtc"] = max(0, int(tokyo.get("tradeStartHourUtc", 3)) - 3)
    tokyo["rangeEndHourUtc"] = max(0, int(tokyo.get("tradeStartHourUtc", 3)) - 1)
    _mutate_int(tokyo, "lookbackBars", 8, step * 2, 2, 96)
    _mutate_float(tokyo, "bufferPips", 0.0, (offset % 5) * 0.5, 0.0, 50.0, 2)

    night = indicators.setdefault("nightReversion", {})
    _mutate_int(night, "startHourUtc", 20, step, 0, 23)
    _mutate_int(night, "endHourUtc", 2, step, 0, 23)
    _mutate_int(night, "bollingerPeriod", 20, step * 2, 5, 120)
    _mutate_float(night, "deviations", 1.8, step * 0.1, 0.5, 4.0, 2)
    _mutate_float(night, "entryBufferPips", 0.0, (offset % 4) * 0.25, 0.0, 30.0, 2)

    h4 = indicators.setdefault("h4Pullback", {})
    _mutate_int(h4, "fastEmaPeriod", 20, step * 2, 2, 120)
    _mutate_int(h4, "slowEmaPeriod", 50, step * 3, 3, 240)
    if int(h4["fastEmaPeriod"]) >= int(h4["slowEmaPeriod"]):
        h4["slowEmaPeriod"] = int(h4["fastEmaPeriod"]) + 1
    _mutate_int(h4, "pullbackEmaPeriod", 20, step * 2, 2, 120)
    _mutate_int(h4, "rsiPeriod", 14, (offset % 3) - 1, 2, 50)
    _mutate_float(h4, "longRsiMin", 38, step, 5, 65, 1)
    _mutate_float(h4, "shortRsiMax", 62, -step, 35, 95, 1)
