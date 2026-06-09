"""Bounded read-only BTC crypto CFD strategy scanner.

The scanner turns ad-hoc BTC CopyRates parameter sweeps into a repeatable
artifact. It only reads local rate/spec files and writes an optional report; it
never writes MT5 order requests, receipts, live presets, or broker commands.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.champion_retest import (
        BTC_PROFILE_CONFIGS,
        SAFETY,
        _btc_candidate_retest,
        _contract_specs,
        _ranked_btc_retests,
        _rate_csv_candidates,
        _read_rate_rows,
    )
except ModuleNotFoundError:  # pragma: no cover
    from champion_retest import (
        BTC_PROFILE_CONFIGS,
        SAFETY,
        _btc_candidate_retest,
        _contract_specs,
        _ranked_btc_retests,
        _rate_csv_candidates,
        _read_rate_rows,
    )


REPORT_SCHEMA = "quantgod.btc_strategy_scan.report.v1"
REPORT_PATH = Path("agent") / "QuantGod_BtcStrategyScanReport.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _unique_strategy_id_order(*strategy_ids: Any) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in strategy_ids:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").replace(",", "").strip())
        except ValueError:
            return default
    return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _candidate_key(config: dict[str, Any]) -> tuple[str, tuple[tuple[str, Any], ...]]:
    return (
        str(config.get("strategyFamily") or ""),
        tuple(sorted((config.get("parameters") or {}).items())),
    )


def _priority_stability_configs() -> list[dict[str, Any]]:
    seeds = [
        (
            "hfm_crypto_btc_stability_short_window_shadow_v1",
            "BTCUSD short-window stability shadow simulation",
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 48,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 300.0,
                "maxHoldBars": 8,
                "cooldownBars": 6,
            },
        ),
        (
            "hfm_crypto_btc_sample_balanced_both_shadow_v1",
            "BTCUSD sample-balanced bidirectional shadow simulation",
            {
                "bias": "both",
                "emaSpan": 36,
                "slopeLookbackBars": 144,
                "slopeThresholdPrice": 75.0,
                "takeProfitPriceMove": 900.0,
                "stopLossPriceMove": 500.0,
                "maxHoldBars": 16,
                "cooldownBars": 4,
            },
        ),
        (
            "hfm_crypto_btc_yield_balanced_both_shadow_v1",
            "BTCUSD yield-balanced bidirectional shadow simulation",
            {
                "bias": "both",
                "emaSpan": 36,
                "slopeLookbackBars": 144,
                "slopeThresholdPrice": 75.0,
                "takeProfitPriceMove": 750.0,
                "stopLossPriceMove": 400.0,
                "maxHoldBars": 36,
                "cooldownBars": 6,
            },
        ),
        (
            "hfm_crypto_btc_short_sample_repair_shadow_v1",
            "BTCUSD short sample-repair shadow simulation",
            {
                "bias": "short",
                "emaSpan": 36,
                "slopeLookbackBars": 48,
                "slopeThresholdPrice": 50.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 300.0,
                "maxHoldBars": 8,
                "cooldownBars": 4,
            },
        ),
    ]
    return [
        {
            "strategyId": strategy_id,
            "strategyName": strategy_name,
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        }
        for strategy_id, strategy_name, parameters in seeds
    ]


def _champion_repair_configs() -> list[dict[str, Any]]:
    """Dense local search around the current BTC stability champion.

    The broad grid is useful for discovery, but the current blocker is specific:
    the middle-third window needs more trades and higher Sharpe. These configs
    keep the champion's short-bias/short-hold personality while nudging the
    tactical entry and exit controls around the winning neighborhood.
    """

    configs: list[dict[str, Any]] = []
    index = 0
    for ema_span in (12, 15, 18, 21, 24, 30):
        for lookback in (36, 42, 48, 60, 72):
            for threshold in (50.0, 75.0, 90.0, 100.0, 125.0, 150.0):
                for take_profit, stop_loss in (
                    (350.0, 250.0),
                    (400.0, 250.0),
                    (450.0, 250.0),
                    (450.0, 300.0),
                    (500.0, 300.0),
                    (600.0, 350.0),
                ):
                    for hold_bars in (6, 8, 10, 12):
                        for cooldown in (2, 3, 4, 5, 6):
                            index += 1
                            configs.append({
                                "strategyId": f"hfm_crypto_btc_champion_repair_{index:04d}",
                                "strategyName": "BTCUSD champion-neighborhood repair scan",
                                "strategyFamily": "ema_slope_regime",
                                "parameters": {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                },
                            })
    return configs


def _balanced_yield_repair_configs(max_count: int = 160) -> list[dict[str, Any]]:
    """Local repair grid for high-PnL bidirectional BTC candidates.

    The scanner already protects the current short-bias stability champion.
    These configs cover the nearby parameter space for the `$50+` bidirectional
    candidates whose remaining blocker is window-level Sharpe/trade count.
    """

    bases = [
        {
            "label": "sample_balanced",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 900.0,
            "stopLossPriceMove": 500.0,
            "maxHoldBars": 16,
            "cooldownBars": 4,
        },
        {
            "label": "yield_balanced",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
    ]
    value_sets = {
        "emaSpan": (30, 36, 42, 48),
        "slopeLookbackBars": (96, 120, 144, 168),
        "slopeThresholdPrice": (50.0, 75.0, 100.0, 125.0),
        "takeProfitPriceMove": (600.0, 750.0, 900.0, 1050.0),
        "stopLossPriceMove": (350.0, 400.0, 500.0, 600.0),
        "maxHoldBars": (12, 16, 24, 36),
        "cooldownBars": (3, 4, 6, 8),
    }

    raw: list[tuple[float, str, dict[str, Any]]] = []
    for base in bases:
        for ema_span in value_sets["emaSpan"]:
            for lookback in value_sets["slopeLookbackBars"]:
                for threshold in value_sets["slopeThresholdPrice"]:
                    for take_profit in value_sets["takeProfitPriceMove"]:
                        for stop_loss in value_sets["stopLossPriceMove"]:
                            for hold_bars in value_sets["maxHoldBars"]:
                                for cooldown in value_sets["cooldownBars"]:
                                    distance = (
                                        abs(ema_span - base["emaSpan"]) / 6.0
                                        + abs(lookback - base["slopeLookbackBars"]) / 24.0
                                        + abs(threshold - base["slopeThresholdPrice"]) / 25.0
                                        + abs(take_profit - base["takeProfitPriceMove"]) / 150.0
                                        + abs(stop_loss - base["stopLossPriceMove"]) / 100.0
                                        + abs(hold_bars - base["maxHoldBars"]) / 8.0
                                        + abs(cooldown - base["cooldownBars"]) / 2.0
                                    )
                                    parameters = {
                                        "bias": "both",
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }
                                    raw.append((distance, str(base["label"]), parameters))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, label, parameters in sorted(raw, key=lambda item: (item[0], item[1])):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_balanced_yield_repair_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD balanced-yield stability repair scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _balanced_sample_density_repair_configs(max_count: int = 160) -> list[dict[str, Any]]:
    """Repair grid for high-yield BTC configs with low sub-window samples."""

    bases = [
        {
            "label": "sample_balanced_density",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 900.0,
            "stopLossPriceMove": 500.0,
            "maxHoldBars": 16,
            "cooldownBars": 4,
        },
        {
            "label": "yield_balanced_density",
            "emaSpan": 42,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
    ]
    value_sets = {
        "emaSpan": (24, 30, 36, 42),
        "slopeLookbackBars": (72, 96, 120, 144),
        "slopeThresholdPrice": (25.0, 50.0, 75.0, 100.0),
        "takeProfitPriceMove": (350.0, 450.0, 600.0, 750.0),
        "stopLossPriceMove": (250.0, 300.0, 400.0, 500.0),
        "maxHoldBars": (6, 8, 10, 12, 16),
        "cooldownBars": (0, 1, 2, 3, 4),
    }

    raw: list[tuple[float, str, dict[str, Any]]] = []
    for base in bases:
        for ema_span in value_sets["emaSpan"]:
            for lookback in value_sets["slopeLookbackBars"]:
                for threshold in value_sets["slopeThresholdPrice"]:
                    for take_profit in value_sets["takeProfitPriceMove"]:
                        for stop_loss in value_sets["stopLossPriceMove"]:
                            for hold_bars in value_sets["maxHoldBars"]:
                                for cooldown in value_sets["cooldownBars"]:
                                    density_bonus = (
                                        (16 - min(hold_bars, 16)) / 4.0
                                        + (4 - min(cooldown, 4)) / 2.0
                                        + (75.0 - min(threshold, 75.0)) / 25.0
                                    )
                                    distance = (
                                        abs(ema_span - base["emaSpan"]) / 6.0
                                        + abs(lookback - base["slopeLookbackBars"]) / 24.0
                                        + abs(threshold - base["slopeThresholdPrice"]) / 25.0
                                        + abs(take_profit - base["takeProfitPriceMove"]) / 150.0
                                        + abs(stop_loss - base["stopLossPriceMove"]) / 100.0
                                        + abs(hold_bars - base["maxHoldBars"]) / 8.0
                                        + abs(cooldown - base["cooldownBars"]) / 2.0
                                        - density_bonus
                                    )
                                    parameters = {
                                        "bias": "both",
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }
                                    raw.append((distance, str(base["label"]), parameters))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, label, parameters in sorted(raw, key=lambda item: (item[0], item[1])):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_balanced_sample_density_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD balanced sample-density repair scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _middle_window_rescue_repair_configs(max_count: int = 220) -> list[dict[str, Any]]:
    """Target the BTC middle-third weakness without abandoning stability.

    The current BTC champion is positive in every window, but the middle-third
    window repeatedly fails Sharpe/trade-count gates. This focused family keeps
    the existing short-window champion and high-PnL bidirectional candidates as
    anchors, then nudges cycle length and cooldown down just enough to add
    samples in the weak window.
    """

    bases = [
        {
            "label": "short_champion_middle",
            "bias": "short",
            "emaSpan": 18,
            "slopeLookbackBars": 48,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 450.0,
            "stopLossPriceMove": 300.0,
            "maxHoldBars": 8,
            "cooldownBars": 6,
        },
        {
            "label": "sample_balanced_middle",
            "bias": "both",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 900.0,
            "stopLossPriceMove": 500.0,
            "maxHoldBars": 16,
            "cooldownBars": 4,
        },
        {
            "label": "yield_balanced_middle",
            "bias": "both",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
    ]
    value_sets = {
        "short": {
            "emaSpan": (15, 18, 21, 24),
            "slopeLookbackBars": (36, 42, 48, 60),
            "slopeThresholdPrice": (75.0, 90.0, 100.0, 125.0),
            "takeProfitPriceMove": (350.0, 400.0, 450.0, 500.0, 600.0),
            "stopLossPriceMove": (250.0, 300.0, 350.0),
            "maxHoldBars": (6, 8, 10, 12, 16),
            "cooldownBars": (1, 2, 3, 4, 5, 6),
        },
        "both": {
            "emaSpan": (30, 36, 42),
            "slopeLookbackBars": (96, 120, 144),
            "slopeThresholdPrice": (50.0, 75.0, 100.0),
            "takeProfitPriceMove": (450.0, 600.0, 750.0, 900.0),
            "stopLossPriceMove": (300.0, 400.0, 500.0),
            "maxHoldBars": (8, 12, 16, 24, 36),
            "cooldownBars": (1, 2, 3, 4, 6),
        },
    }

    raw: list[tuple[float, str, dict[str, Any]]] = []
    for base in bases:
        sets = value_sets[str(base["bias"])]
        for ema_span in sets["emaSpan"]:
            for lookback in sets["slopeLookbackBars"]:
                for threshold in sets["slopeThresholdPrice"]:
                    for take_profit in sets["takeProfitPriceMove"]:
                        for stop_loss in sets["stopLossPriceMove"]:
                            for hold_bars in sets["maxHoldBars"]:
                                for cooldown in sets["cooldownBars"]:
                                    sample_bonus = (
                                        max(0.0, float(base["maxHoldBars"]) - hold_bars) / 4.0
                                        + max(0.0, float(base["cooldownBars"]) - cooldown) / 2.0
                                    )
                                    risk_penalty = 0.0
                                    if stop_loss >= take_profit:
                                        risk_penalty += 2.5
                                    if threshold < 50.0:
                                        risk_penalty += 2.0
                                    if hold_bars <= 6 and cooldown <= 1:
                                        risk_penalty += 1.5
                                    distance = (
                                        abs(ema_span - float(base["emaSpan"])) / 6.0
                                        + abs(lookback - float(base["slopeLookbackBars"])) / 24.0
                                        + abs(threshold - float(base["slopeThresholdPrice"])) / 25.0
                                        + abs(take_profit - float(base["takeProfitPriceMove"])) / 150.0
                                        + abs(stop_loss - float(base["stopLossPriceMove"])) / 100.0
                                        + abs(hold_bars - float(base["maxHoldBars"])) / 8.0
                                        + abs(cooldown - float(base["cooldownBars"])) / 2.0
                                        + risk_penalty
                                        - sample_bonus
                                    )
                                    parameters = {
                                        "bias": base["bias"],
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }
                                    raw.append((distance, str(base["label"]), parameters))

    anchors = [
        {
            "bias": "short",
            "emaSpan": 18,
            "slopeLookbackBars": 48,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 450.0,
            "stopLossPriceMove": 300.0,
            "maxHoldBars": 8,
            "cooldownBars": 3,
        },
        {
            "bias": "both",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 8,
            "cooldownBars": 3,
        },
        {
            "bias": "both",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 900.0,
            "stopLossPriceMove": 500.0,
            "maxHoldBars": 8,
            "cooldownBars": 3,
        },
    ]

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()

    def append(parameters: dict[str, Any]) -> None:
        key = tuple(sorted(parameters.items()))
        if key in seen or len(configs) >= max_count:
            return
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_middle_window_rescue_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD middle-window stability rescue scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })

    for parameters in anchors:
        append(parameters)

    for _, label, parameters in sorted(raw, key=lambda item: (item[0], item[1])):
        append(parameters)
        if len(configs) >= max_count:
            break
    return configs


def _balanced_quality_repair_configs(max_count: int = 180) -> list[dict[str, Any]]:
    """Quality-first repair grid for profitable slow BTC candidates.

    The density grid proved that forcing more trades can destroy edge. This
    grid stays near the high-PnL bidirectional candidates, nudging thresholds,
    exits, and hold time without collapsing into short noisy cycles.
    """

    bases = [
        {
            "label": "quality_yield_base",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
        {
            "label": "quality_yield_alt",
            "emaSpan": 42,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
        {
            "label": "quality_balanced_window",
            "emaSpan": 48,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 600.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 48,
            "cooldownBars": 8,
        },
    ]
    value_sets = {
        "emaSpan": (30, 36, 42, 48, 54),
        "slopeLookbackBars": (120, 144, 168, 192),
        "slopeThresholdPrice": (75.0, 100.0, 125.0, 150.0),
        "takeProfitPriceMove": (600.0, 750.0, 900.0, 1050.0),
        "stopLossPriceMove": (350.0, 400.0, 450.0, 500.0),
        "maxHoldBars": (24, 36, 48, 60),
        "cooldownBars": (5, 6, 8, 10),
    }

    raw: list[tuple[float, str, dict[str, Any]]] = []
    for base in bases:
        for ema_span in value_sets["emaSpan"]:
            for lookback in value_sets["slopeLookbackBars"]:
                for threshold in value_sets["slopeThresholdPrice"]:
                    for take_profit in value_sets["takeProfitPriceMove"]:
                        for stop_loss in value_sets["stopLossPriceMove"]:
                            for hold_bars in value_sets["maxHoldBars"]:
                                for cooldown in value_sets["cooldownBars"]:
                                    quality_penalty = 0.0
                                    if hold_bars < 24:
                                        quality_penalty += 3.0
                                    if cooldown < 5:
                                        quality_penalty += 3.0
                                    if stop_loss > take_profit:
                                        quality_penalty += 2.0
                                    if threshold < 75.0:
                                        quality_penalty += 2.0
                                    distance = (
                                        abs(ema_span - base["emaSpan"]) / 6.0
                                        + abs(lookback - base["slopeLookbackBars"]) / 24.0
                                        + abs(threshold - base["slopeThresholdPrice"]) / 25.0
                                        + abs(take_profit - base["takeProfitPriceMove"]) / 150.0
                                        + abs(stop_loss - base["stopLossPriceMove"]) / 50.0
                                        + abs(hold_bars - base["maxHoldBars"]) / 12.0
                                        + abs(cooldown - base["cooldownBars"]) / 2.0
                                        + quality_penalty
                                    )
                                    parameters = {
                                        "bias": "both",
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }
                                    raw.append((distance, str(base["label"]), parameters))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, label, parameters in sorted(raw, key=lambda item: (item[0], item[1])):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_balanced_quality_repair_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD balanced quality-first repair scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _sample_rich_quality_repair_configs(max_count: int = 260) -> list[dict[str, Any]]:
    """Bridge high-yield and sample-rich BTC neighborhoods.

    The strongest high-PnL configs keep good full-window Sharpe but fail
    sub-window sample gates. Pure density search damaged the edge, so this
    family stays near quality-first setups while adding the sample-rich TP/SL
    shape that appeared in the optimizer leaderboard.
    """

    anchors = [
        {
            "label": "optimizer_sample_rich",
            "emaSpan": 42,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 400.0,
            "stopLossPriceMove": 600.0,
            "maxHoldBars": 16,
            "cooldownBars": 4,
        },
        {
            "label": "optimizer_high_sharpe_low_sample",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 600.0,
            "stopLossPriceMove": 600.0,
            "maxHoldBars": 36,
            "cooldownBars": 10,
        },
        {
            "label": "quality_first_high_yield",
            "emaSpan": 42,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
        {
            "label": "target_seeking_sample_bridge",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 900.0,
            "stopLossPriceMove": 425.0,
            "maxHoldBars": 24,
            "cooldownBars": 9,
        },
    ]
    value_sets = {
        "emaSpan": (30, 36, 42, 48),
        "slopeLookbackBars": (120, 144, 168),
        "slopeThresholdPrice": (75.0, 100.0, 125.0),
        "takeProfitPriceMove": (400.0, 500.0, 600.0, 750.0, 900.0),
        "stopLossPriceMove": (325.0, 400.0, 425.0, 500.0, 600.0),
        "maxHoldBars": (12, 16, 20, 24, 32, 36),
        "cooldownBars": (4, 6, 8, 10, 12),
    }

    raw: list[tuple[float, str, dict[str, Any]]] = []
    for base in anchors:
        for ema_span in value_sets["emaSpan"]:
            for lookback in value_sets["slopeLookbackBars"]:
                for threshold in value_sets["slopeThresholdPrice"]:
                    for take_profit in value_sets["takeProfitPriceMove"]:
                        for stop_loss in value_sets["stopLossPriceMove"]:
                            for hold_bars in value_sets["maxHoldBars"]:
                                for cooldown in value_sets["cooldownBars"]:
                                    sample_bridge_bonus = 0.0
                                    if 12 <= hold_bars <= 24:
                                        sample_bridge_bonus += 1.0
                                    if 4 <= cooldown <= 8:
                                        sample_bridge_bonus += 0.75
                                    if 400.0 <= take_profit <= 900.0:
                                        sample_bridge_bonus += 0.5
                                    risk_penalty = 0.0
                                    if stop_loss > take_profit * 1.5:
                                        risk_penalty += 2.0
                                    if take_profit < 400.0:
                                        risk_penalty += 1.0
                                    if cooldown < 4:
                                        risk_penalty += 2.0
                                    distance = (
                                        abs(ema_span - base["emaSpan"]) / 6.0
                                        + abs(lookback - base["slopeLookbackBars"]) / 24.0
                                        + abs(threshold - base["slopeThresholdPrice"]) / 25.0
                                        + abs(take_profit - base["takeProfitPriceMove"]) / 150.0
                                        + abs(stop_loss - base["stopLossPriceMove"]) / 100.0
                                        + abs(hold_bars - base["maxHoldBars"]) / 8.0
                                        + abs(cooldown - base["cooldownBars"]) / 2.0
                                        + risk_penalty
                                        - sample_bridge_bonus
                                    )
                                    parameters = {
                                        "bias": "both",
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }
                                    raw.append((distance, str(base["label"]), parameters))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, label, parameters in sorted(raw, key=lambda item: (item[0], item[1])):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_sample_rich_quality_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD sample-rich quality repair scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _frontier_high_yield_confirmation_configs(max_count: int = 120) -> list[dict[str, Any]]:
    """Densify the current high-yield frontier neighborhood.

    Once the scan surfaces a distinct high-yield challenger, the next highest
    value search is not another broad sweep. It is a local confirmation pass
    around that challenger, the prior optimizer target, and the sample-rich
    bridge so we can tell whether the frontier is stable or just a one-off.
    """

    anchors = [
        {
            "label": "frontier_sample_rich_0209",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 500.0,
            "stopLossPriceMove": 600.0,
            "maxHoldBars": 36,
            "cooldownBars": 10,
        },
        {
            "label": "quality_target_baseline",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
        {
            "label": "sample_rich_bridge_baseline",
            "emaSpan": 42,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 400.0,
            "stopLossPriceMove": 600.0,
            "maxHoldBars": 16,
            "cooldownBars": 4,
        },
    ]
    value_sets = {
        "emaSpan": (30, 36, 42),
        "slopeLookbackBars": (120, 144, 168),
        "slopeThresholdPrice": (50.0, 75.0, 100.0, 125.0),
        "takeProfitPriceMove": (450.0, 500.0, 600.0, 750.0),
        "stopLossPriceMove": (400.0, 500.0, 600.0),
        "maxHoldBars": (24, 36, 48),
        "cooldownBars": (6, 8, 10, 12),
    }

    raw: list[tuple[float, str, dict[str, Any]]] = []
    for base in anchors:
        for ema_span in value_sets["emaSpan"]:
            for lookback in value_sets["slopeLookbackBars"]:
                for threshold in value_sets["slopeThresholdPrice"]:
                    for take_profit in value_sets["takeProfitPriceMove"]:
                        for stop_loss in value_sets["stopLossPriceMove"]:
                            for hold_bars in value_sets["maxHoldBars"]:
                                for cooldown in value_sets["cooldownBars"]:
                                    frontier_bonus = 0.0
                                    if take_profit in (500.0, 600.0):
                                        frontier_bonus += 1.5
                                    if stop_loss in (500.0, 600.0):
                                        frontier_bonus += 1.0
                                    if hold_bars >= 36:
                                        frontier_bonus += 0.75
                                    if cooldown in (8, 10):
                                        frontier_bonus += 0.75
                                    risk_penalty = 0.0
                                    if stop_loss > take_profit * 1.35:
                                        risk_penalty += 2.5
                                    if cooldown < 6:
                                        risk_penalty += 2.0
                                    distance = (
                                        abs(ema_span - base["emaSpan"]) / 6.0
                                        + abs(lookback - base["slopeLookbackBars"]) / 24.0
                                        + abs(threshold - base["slopeThresholdPrice"]) / 25.0
                                        + abs(take_profit - base["takeProfitPriceMove"]) / 125.0
                                        + abs(stop_loss - base["stopLossPriceMove"]) / 75.0
                                        + abs(hold_bars - base["maxHoldBars"]) / 8.0
                                        + abs(cooldown - base["cooldownBars"]) / 2.0
                                        + risk_penalty
                                        - frontier_bonus
                                    )
                                    parameters = {
                                        "bias": "both",
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }
                                    raw.append((distance, str(base["label"]), parameters))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, label, parameters in sorted(raw, key=lambda item: (item[0], item[1])):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_frontier_yield_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD frontier high-yield confirmation scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _yield_leader_confirmation_configs(max_count: int = 120) -> list[dict[str, Any]]:
    """Locally confirm whether the current yield leader is still the right one.

    The broader high-yield repair families are useful for discovery, but once
    the scan reconverges on a concrete yield leader we need a tighter answer:
    does a close neighborhood variant beat the leader on stability-adjusted
    quality, or is the current leader still the right high-yield reference?
    """

    anchors = [
        {
            "label": "yield_leader_current",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
        {
            "label": "yield_leader_quality_variant",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 36,
            "cooldownBars": 6,
        },
        {
            "label": "yield_leader_bridge_variant",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 600.0,
            "stopLossPriceMove": 500.0,
            "maxHoldBars": 36,
            "cooldownBars": 8,
        },
    ]
    value_sets = {
        "emaSpan": (30, 36, 42),
        "slopeLookbackBars": (120, 144, 168),
        "slopeThresholdPrice": (50.0, 75.0, 100.0),
        "takeProfitPriceMove": (600.0, 750.0, 900.0),
        "stopLossPriceMove": (350.0, 400.0, 450.0, 500.0),
        "maxHoldBars": (24, 30, 36, 42, 48),
        "cooldownBars": (4, 6, 8, 10),
    }

    raw: list[tuple[float, str, dict[str, Any]]] = []
    for base in anchors:
        for ema_span in value_sets["emaSpan"]:
            for lookback in value_sets["slopeLookbackBars"]:
                for threshold in value_sets["slopeThresholdPrice"]:
                    for take_profit in value_sets["takeProfitPriceMove"]:
                        for stop_loss in value_sets["stopLossPriceMove"]:
                            for hold_bars in value_sets["maxHoldBars"]:
                                for cooldown in value_sets["cooldownBars"]:
                                    yield_bonus = 0.0
                                    if take_profit in (750.0, 900.0):
                                        yield_bonus += 1.25
                                    if stop_loss in (400.0, 450.0):
                                        yield_bonus += 1.0
                                    if hold_bars in (30, 36, 42):
                                        yield_bonus += 0.75
                                    if cooldown in (6, 8):
                                        yield_bonus += 0.75
                                    if threshold in (75.0, 100.0):
                                        yield_bonus += 0.5
                                    risk_penalty = 0.0
                                    if stop_loss >= take_profit:
                                        risk_penalty += 2.0
                                    if take_profit <= 600.0 and stop_loss >= 500.0:
                                        risk_penalty += 1.0
                                    if hold_bars < 24:
                                        risk_penalty += 1.0
                                    distance = (
                                        abs(ema_span - base["emaSpan"]) / 6.0
                                        + abs(lookback - base["slopeLookbackBars"]) / 24.0
                                        + abs(threshold - base["slopeThresholdPrice"]) / 25.0
                                        + abs(take_profit - base["takeProfitPriceMove"]) / 125.0
                                        + abs(stop_loss - base["stopLossPriceMove"]) / 75.0
                                        + abs(hold_bars - base["maxHoldBars"]) / 8.0
                                        + abs(cooldown - base["cooldownBars"]) / 2.0
                                        + risk_penalty
                                        - yield_bonus
                                    )
                                    parameters = {
                                        "bias": "both",
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }
                                    raw.append((distance, str(base["label"]), parameters))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, label, parameters in sorted(raw, key=lambda item: (item[0], item[1])):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_yield_leader_confirmation_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD yield-leader confirmation scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_stability_confirmation_configs(max_count: int = 120) -> list[dict[str, Any]]:
    """Densify the current near-live stability challenger neighborhood.

    The active second-line BTC candidate is no longer the sample-rich bridge.
    It is the bidirectional sample-balanced challenger that sits between the
    stable short-bias champion and the slower high-yield frontier. This batch
    keeps the search local to that neighborhood so we can tell whether a more
    stable second candidate exists without collapsing into a density-only path.
    It now also includes a short-bias tradeoff bridge so the confirmation pass
    can decide whether the second candidate should stay bidirectional or move
    closer to the stable short anchor.
    """

    anchors = [
        {
            "label": "near_live_sample_balanced",
            "bias": "both",
            "emaSpan": 36,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 900.0,
            "stopLossPriceMove": 500.0,
            "maxHoldBars": 16,
            "cooldownBars": 4,
        },
        {
            "label": "near_live_sample_rich_bridge",
            "bias": "both",
            "emaSpan": 42,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 400.0,
            "stopLossPriceMove": 600.0,
            "maxHoldBars": 16,
            "cooldownBars": 4,
        },
        {
            "label": "near_live_stable_bridge",
            "bias": "both",
            "emaSpan": 30,
            "slopeLookbackBars": 96,
            "slopeThresholdPrice": 75.0,
            "takeProfitPriceMove": 750.0,
            "stopLossPriceMove": 450.0,
            "maxHoldBars": 12,
            "cooldownBars": 4,
        },
        {
            "label": "near_live_tradeoff_bridge",
            "bias": "short",
            "emaSpan": 18,
            "slopeLookbackBars": 57,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 450.0,
            "stopLossPriceMove": 350.0,
            "maxHoldBars": 8,
            "cooldownBars": 4,
        },
    ]
    value_sets = {
        "emaSpan": (18, 24, 30, 36, 42),
        "slopeLookbackBars": (57, 72, 96, 120, 144, 168),
        "slopeThresholdPrice": (50.0, 75.0, 100.0),
        "takeProfitPriceMove": (400.0, 450.0, 500.0, 600.0, 750.0, 900.0, 1050.0),
        "stopLossPriceMove": (350.0, 400.0, 450.0, 500.0, 600.0),
        "maxHoldBars": (8, 10, 12, 16, 20, 24),
        "cooldownBars": (3, 4, 5, 6),
    }

    raw: list[tuple[float, str, dict[str, Any]]] = []
    for base in anchors:
        for ema_span in value_sets["emaSpan"]:
            for lookback in value_sets["slopeLookbackBars"]:
                for threshold in value_sets["slopeThresholdPrice"]:
                    for take_profit in value_sets["takeProfitPriceMove"]:
                        for stop_loss in value_sets["stopLossPriceMove"]:
                            for hold_bars in value_sets["maxHoldBars"]:
                                for cooldown in value_sets["cooldownBars"]:
                                    stability_bonus = 0.0
                                    if base["bias"] == "short":
                                        stability_bonus += 0.75
                                    if take_profit in (400.0, 500.0):
                                        stability_bonus += 0.5
                                    if take_profit in (750.0, 900.0):
                                        stability_bonus += 1.0
                                    if take_profit == 450.0:
                                        stability_bonus += 0.75
                                    if stop_loss == 350.0:
                                        stability_bonus += 0.75
                                    if stop_loss in (450.0, 500.0):
                                        stability_bonus += 1.0
                                    if stop_loss == 600.0 and take_profit in (400.0, 500.0):
                                        stability_bonus += 0.5
                                    if 12 <= hold_bars <= 20:
                                        stability_bonus += 0.75
                                    if hold_bars == 8:
                                        stability_bonus += 0.5
                                    if cooldown in (4, 5):
                                        stability_bonus += 0.75
                                    risk_penalty = 0.0
                                    if stop_loss > take_profit * 0.9:
                                        risk_penalty += 1.5
                                    if base["bias"] == "short" and stop_loss > 450.0:
                                        risk_penalty += 0.75
                                    if cooldown < 3:
                                        risk_penalty += 1.0
                                    distance = (
                                        abs(ema_span - base["emaSpan"]) / 6.0
                                        + abs(lookback - base["slopeLookbackBars"]) / 24.0
                                        + abs(threshold - base["slopeThresholdPrice"]) / 25.0
                                        + abs(take_profit - base["takeProfitPriceMove"]) / 150.0
                                        + abs(stop_loss - base["stopLossPriceMove"]) / 75.0
                                        + abs(hold_bars - base["maxHoldBars"]) / 6.0
                                        + abs(cooldown - base["cooldownBars"]) / 1.5
                                        + risk_penalty
                                        - stability_bonus
                                    )
                                    parameters = {
                                        "bias": base["bias"],
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }
                                    raw.append((distance, str(base["label"]), parameters))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, label, parameters in sorted(raw, key=lambda item: (item[0], item[1])):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_stability_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live stability confirmation scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_stability_followup_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Local follow-up search around the near-live repair winner.

    The near-live repair line already moved the second candidate away from the
    old sample-balanced challenger. This follow-up keeps the search tightly
    centered on that short-bias neighborhood so we can test whether a nearby
    variant can either recover a fifth valid window or improve the weak windows
    without giving back the aggregate stability gain.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 350.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (54, 57, 60),
        "slopeThresholdPrice": (90.0, 100.0, 110.0),
        "takeProfitPriceMove": (450.0, 500.0),
        "stopLossPriceMove": (325.0, 350.0, 375.0),
        "maxHoldBars": (8, 10),
        "cooldownBars": (3, 4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                followup_bonus = 0.0
                                if lookback in (57, 60):
                                    followup_bonus += 1.0
                                if threshold in (90.0, 100.0):
                                    followup_bonus += 0.5
                                if take_profit == 450.0:
                                    followup_bonus += 0.5
                                if stop_loss in (350.0, 375.0):
                                    followup_bonus += 0.75
                                if hold_bars == 8:
                                    followup_bonus += 0.5
                                if cooldown in (4, 5):
                                    followup_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 1.75
                                if hold_bars == 10 and cooldown == 3:
                                    risk_penalty += 0.5
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 3.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 12.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 50.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 30.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 2.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - followup_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_followup_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live stability follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_followup_refinement_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Refine the promoted near-live follow-up winner around its local optimum.

    The first follow-up pass can still leave a better nearby short-bias variant
    undiscovered. This family tightens around the promoted follow-up winner so
    the reports can automatically promote a successor if a close refinement
    beats the current near-live follow-up.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (54, 57, 60),
        "slopeThresholdPrice": (90.0, 100.0, 110.0),
        "takeProfitPriceMove": (425.0, 450.0, 500.0),
        "stopLossPriceMove": (300.0, 325.0, 350.0),
        "maxHoldBars": (8, 10),
        "cooldownBars": (3, 4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                refinement_bonus = 0.0
                                if lookback == 57:
                                    refinement_bonus += 1.0
                                if threshold == 100.0:
                                    refinement_bonus += 0.75
                                if take_profit == 450.0:
                                    refinement_bonus += 0.75
                                if stop_loss in (300.0, 325.0):
                                    refinement_bonus += 1.0
                                if hold_bars == 8:
                                    refinement_bonus += 0.5
                                if cooldown in (4, 5):
                                    refinement_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if take_profit == 425.0 and stop_loss == 350.0:
                                    risk_penalty += 0.5
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 3.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 12.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 40.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 25.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 2.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - refinement_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_refinement_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live stability refinement scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_middle_window_followup_configs(max_count: int = 96) -> list[dict[str, Any]]:
    """Target the current near-live follow-up winner's weakest middle window.

    The promoted near-live challenger already preserves four valid windows, but
    its middle-third still fails on both Sharpe and sample count. This family
    stays tightly centered on that winner while biasing toward slightly faster
    trade cadence and small threshold adjustments that may improve the weak
    window without collapsing aggregate stability back to the old sample-rich
    path.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (51, 54, 57, 60),
        "slopeThresholdPrice": (95.0, 100.0, 105.0, 110.0),
        "takeProfitPriceMove": (425.0, 450.0, 475.0),
        "stopLossPriceMove": (300.0, 325.0, 350.0),
        "maxHoldBars": (6, 8, 10),
        "cooldownBars": (3, 4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                cadence_bonus = 0.0
                                if hold_bars in (6, 8):
                                    cadence_bonus += 1.0
                                if cooldown in (3, 4):
                                    cadence_bonus += 1.0
                                if lookback in (54, 57):
                                    cadence_bonus += 0.75
                                if threshold in (100.0, 105.0):
                                    cadence_bonus += 0.75
                                if take_profit == 450.0:
                                    cadence_bonus += 0.5
                                if stop_loss in (300.0, 325.0):
                                    cadence_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 6 and cooldown == 3:
                                    risk_penalty += 0.35
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 3.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 30.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 20.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.5
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - cadence_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_middle_window_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live middle-window follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_middle_window_cluster_refinement_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Densify the converged near-live cluster around the current top SL ladder.

    The scan has already converged to a tight trio around the same short-bias
    regime: `0003 / 0021 / 0040`. At this stage the useful question is no
    longer whether the family is viable, but whether a very close local variant
    can overtake the current distinct contender without replacing the current
    anchor outright.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (54, 57, 60),
        "slopeThresholdPrice": (100.0, 105.0, 110.0),
        "takeProfitPriceMove": (425.0, 450.0, 475.0),
        "stopLossPriceMove": (300.0, 325.0, 350.0),
        "maxHoldBars": (7, 8, 9),
        "cooldownBars": (3, 4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                cluster_bonus = 0.0
                                if ema_span == 18:
                                    cluster_bonus += 0.5
                                if lookback == 57:
                                    cluster_bonus += 1.0
                                if threshold == 105.0:
                                    cluster_bonus += 1.0
                                if take_profit == 450.0:
                                    cluster_bonus += 0.75
                                if stop_loss in (300.0, 325.0, 350.0):
                                    cluster_bonus += 1.0
                                if hold_bars == 8:
                                    cluster_bonus += 0.5
                                if cooldown == 4:
                                    cluster_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 7 and cooldown == 3:
                                    risk_penalty += 0.35
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.2
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 4.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 25.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 15.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - cluster_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_cluster_refinement_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live converged-cluster refinement scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_signal_refinement_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Refine the converged near-live signal kernel without widening risk too far.

    The current `0003 / 0021` pair already settled the broad TP/SL shape. This
    family asks a narrower question: can a nearby EMA/lookback/threshold kernel
    improve the weak middle-third while preserving the current 5-valid-window
    profile, without leaning on a larger stop-loss or a density-only shortcut.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (15, 18, 21),
        "slopeLookbackBars": (54, 57, 60, 63),
        "slopeThresholdPrice": (100.0, 105.0, 110.0, 115.0),
        "takeProfitPriceMove": (425.0, 450.0),
        "stopLossPriceMove": (300.0, 325.0),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                signal_bonus = 0.0
                                if ema_span == 18:
                                    signal_bonus += 1.0
                                if lookback in (57, 60):
                                    signal_bonus += 1.0
                                if threshold in (105.0, 110.0):
                                    signal_bonus += 1.0
                                if take_profit == 450.0:
                                    signal_bonus += 0.5
                                if stop_loss in (300.0, 325.0):
                                    signal_bonus += 0.75
                                if hold_bars == 8:
                                    signal_bonus += 0.5
                                if cooldown == 4:
                                    signal_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 4.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 5.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 8.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 20.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 12.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - signal_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_signal_refinement_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live signal refinement scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_signal_refinement_followup_configs(max_count: int = 36) -> list[dict[str, Any]]:
    """Ultra-local signal follow-up around the current signal-refinement winner.

    The first signal refinement family proved the best nearby signal kernel is
    still below the current next-distinct contender. This follow-up does not
    widen the search again. It only densifies the `425/325` neighborhood with
    smaller lookback/threshold steps and a tighter TP ladder to see whether a
    true signal-kernel micro winner exists.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 425.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 19, 20),
        "slopeLookbackBars": (56, 57, 58, 60),
        "slopeThresholdPrice": (102.5, 105.0, 107.5, 110.0),
        "takeProfitPriceMove": (425.0, 437.5, 450.0),
        "stopLossPriceMove": (312.5, 325.0),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                signal_bonus = 0.0
                                if ema_span == 18:
                                    signal_bonus += 1.0
                                if lookback == 57:
                                    signal_bonus += 1.0
                                if threshold == 105.0:
                                    signal_bonus += 1.0
                                if take_profit in (425.0, 437.5):
                                    signal_bonus += 0.75
                                if stop_loss == 325.0:
                                    signal_bonus += 0.75
                                if hold_bars == 8:
                                    signal_bonus += 0.5
                                if cooldown == 4:
                                    signal_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 2.5
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 3.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 4.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 10.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 8.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - signal_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_signal_refinement_followup_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live signal refinement follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_high_yield_neighborhood_configs(max_count: int = 48) -> list[dict[str, Any]]:
    """Locally confirm the converged leader's quality-first high-yield neighborhood.

    Once `0003` becomes both the stability anchor and the current high-yield
    frontier, the useful next question is no longer broad discovery. It is a
    short-bias local confirmation pass around the leader's `450/325/8/4`
    kernel, with just enough TP/SL ladder width to detect a nearby yield-tilted
    successor without collapsing back into the old wide quality scan.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 19, 21),
        "slopeLookbackBars": (54, 57, 60),
        "slopeThresholdPrice": (100.0, 105.0, 110.0),
        "takeProfitPriceMove": (437.5, 450.0, 462.5, 475.0),
        "stopLossPriceMove": (300.0, 312.5, 325.0),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                yield_bonus = 0.0
                                if ema_span == 18:
                                    yield_bonus += 0.75
                                if lookback == 57:
                                    yield_bonus += 1.0
                                if threshold == 105.0:
                                    yield_bonus += 1.0
                                if take_profit in (450.0, 462.5):
                                    yield_bonus += 1.0
                                elif take_profit == 475.0:
                                    yield_bonus += 0.5
                                if stop_loss in (312.5, 325.0):
                                    yield_bonus += 1.0
                                elif stop_loss == 300.0:
                                    yield_bonus += 0.5
                                if hold_bars == 8:
                                    yield_bonus += 0.5
                                if cooldown == 4:
                                    yield_bonus += 0.5
                                asymmetry_bonus = 0.0
                                if stop_loss and 1.35 <= (take_profit / stop_loss) <= 1.52:
                                    asymmetry_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if take_profit == 475.0 and stop_loss == 300.0:
                                    risk_penalty += 0.25
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 2.5
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 4.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 6.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 12.5
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 10.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - yield_bonus
                                    - asymmetry_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_high_yield_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live high-yield neighborhood scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_high_yield_neighborhood_followup_configs(max_count: int = 36) -> list[dict[str, Any]]:
    """Ultra-local follow-up around the current high-yield neighborhood winner.

    The first neighborhood pass already proved that `312.5` belongs in the
    converged near-live ladder. This follow-up does not broaden the search
    again. It only densifies the `312.5 / 450 / 8 / 4` pocket with tighter
    TP/SL microsteps so we can tell whether there is a real local yield leader
    hiding inside the same short-bias kernel.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 312.5,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 19),
        "slopeLookbackBars": (56, 57, 58),
        "slopeThresholdPrice": (102.5, 105.0, 107.5),
        "takeProfitPriceMove": (443.75, 450.0, 456.25, 462.5),
        "stopLossPriceMove": (306.25, 309.375, 312.5, 315.625),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                yield_bonus = 0.0
                                if ema_span == 18:
                                    yield_bonus += 0.75
                                if lookback == 57:
                                    yield_bonus += 1.0
                                if threshold == 105.0:
                                    yield_bonus += 1.0
                                if take_profit in (450.0, 456.25):
                                    yield_bonus += 1.0
                                elif take_profit == 462.5:
                                    yield_bonus += 0.5
                                if stop_loss in (309.375, 312.5):
                                    yield_bonus += 1.0
                                elif stop_loss == 306.25:
                                    yield_bonus += 0.5
                                if hold_bars == 8:
                                    yield_bonus += 0.5
                                if cooldown == 4:
                                    yield_bonus += 0.5
                                asymmetry_bonus = 0.0
                                if stop_loss and 1.4 <= (take_profit / stop_loss) <= 1.5:
                                    asymmetry_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if take_profit == 462.5 and stop_loss == 306.25:
                                    risk_penalty += 0.2
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 2.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 2.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 3.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 8.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 6.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - yield_bonus
                                    - asymmetry_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_high_yield_followup_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live high-yield neighborhood follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_high_yield_neighborhood_followup_micro_configs(max_count: int = 24) -> list[dict[str, Any]]:
    """Ultra-local micro pass around the current high-yield follow-up winner.

    The previous follow-up pass isolated a tighter `~309.375 / 450 / 8 / 4`
    pocket. This micro family only densifies that pocket with even smaller TP/SL
    steps so we can test whether the neighborhood contains a true local winner
    instead of just equivalent aliases of the same converged short-bias kernel.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 309.375,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 19),
        "slopeLookbackBars": (57, 58),
        "slopeThresholdPrice": (103.75, 105.0, 106.25),
        "takeProfitPriceMove": (446.875, 450.0, 453.125, 456.25),
        "stopLossPriceMove": (307.8125, 309.375, 310.9375, 312.5),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                yield_bonus = 0.0
                                if ema_span == 18:
                                    yield_bonus += 0.75
                                if lookback == 57:
                                    yield_bonus += 0.75
                                if threshold == 105.0:
                                    yield_bonus += 1.0
                                if take_profit in (450.0, 453.125):
                                    yield_bonus += 1.0
                                elif take_profit == 456.25:
                                    yield_bonus += 0.5
                                if stop_loss in (309.375, 310.9375):
                                    yield_bonus += 1.0
                                elif stop_loss == 307.8125:
                                    yield_bonus += 0.5
                                if hold_bars == 8:
                                    yield_bonus += 0.5
                                if cooldown == 4:
                                    yield_bonus += 0.5
                                asymmetry_bonus = 0.0
                                if stop_loss and 1.43 <= (take_profit / stop_loss) <= 1.47:
                                    asymmetry_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if take_profit == 456.25 and stop_loss == 307.8125:
                                    risk_penalty += 0.2
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 1.5
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 1.5
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 2.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 4.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 2.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - yield_bonus
                                    - asymmetry_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_high_yield_followup_micro_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live high-yield neighborhood follow-up micro scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_high_yield_neighborhood_followup_micro_followup_configs(
    max_count: int = 24,
) -> list[dict[str, Any]]:
    """Second-stage micro pass around the fresh 318.75 same-cluster pocket.

    The first micro pass stayed anchored near the earlier 309.375/310.9375
    local pocket. Fresh scan output has since converged the third same-parameter
    variant to 318.75, so this batch tightens around that newer pocket to test
    whether a slightly wider but still near-live high-yield micro ladder can
    improve the current local follow-up without replacing the stable anchor.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 318.75,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 19),
        "slopeLookbackBars": (57, 58),
        "slopeThresholdPrice": (103.75, 105.0, 106.25),
        "takeProfitPriceMove": (446.875, 450.0, 453.125, 456.25),
        "stopLossPriceMove": (315.625, 317.1875, 318.75, 320.3125),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                yield_bonus = 0.0
                                if ema_span == 18:
                                    yield_bonus += 0.75
                                if lookback == 57:
                                    yield_bonus += 0.75
                                if threshold == 105.0:
                                    yield_bonus += 1.0
                                if take_profit in (450.0, 453.125):
                                    yield_bonus += 1.0
                                elif take_profit == 456.25:
                                    yield_bonus += 0.5
                                if stop_loss in (317.1875, 318.75):
                                    yield_bonus += 1.0
                                elif stop_loss == 320.3125:
                                    yield_bonus += 0.5
                                if hold_bars == 8:
                                    yield_bonus += 0.5
                                if cooldown == 4:
                                    yield_bonus += 0.5
                                asymmetry_bonus = 0.0
                                if stop_loss and 1.40 <= (take_profit / stop_loss) <= 1.44:
                                    asymmetry_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if take_profit == 456.25 and stop_loss == 315.625:
                                    risk_penalty += 0.2
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 1.5
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 1.5
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 2.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 4.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 2.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - yield_bonus
                                    - asymmetry_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": (
                f"hfm_crypto_btc_near_live_high_yield_followup_micro_followup_{len(configs) + 1:04d}"
            ),
            "strategyName": "BTCUSD near-live high-yield neighborhood follow-up micro follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_middle_tradeoff_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Search a weak-window tradeoff inside the converged near-live cluster.

    The current `0003 / 0021 / 0012` cluster has already converged on the same
    short-bias regime. The unresolved question is narrower: can a nearby
    tradeoff improve the `middle_third` blockers without giving up the cluster's
    5-valid-window shape.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 300.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (51, 54, 57, 60),
        "slopeThresholdPrice": (95.0, 100.0, 105.0, 110.0),
        "takeProfitPriceMove": (400.0, 425.0, 450.0, 475.0),
        "stopLossPriceMove": (275.0, 300.0, 325.0, 350.0),
        "maxHoldBars": (8, 9, 10),
        "cooldownBars": (3, 4, 5, 6),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                weak_window_bonus = 0.0
                                if lookback in (54, 57):
                                    weak_window_bonus += 1.0
                                if threshold in (100.0, 105.0):
                                    weak_window_bonus += 1.0
                                if take_profit in (425.0, 450.0):
                                    weak_window_bonus += 0.75
                                if stop_loss in (300.0, 325.0):
                                    weak_window_bonus += 1.0
                                if hold_bars in (8, 9):
                                    weak_window_bonus += 0.75
                                if cooldown in (4, 5):
                                    weak_window_bonus += 1.0
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 8 and cooldown == 3:
                                    risk_penalty += 0.35
                                if hold_bars == 10 and cooldown == 6:
                                    risk_penalty += 0.25
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 4.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 25.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 15.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - weak_window_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_middle_tradeoff_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live weak-window tradeoff scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_tempo_refinement_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Refine the converged near-live cluster on hold/cooldown tempo.

    The current `0003 / 0021 / 0012 / 0070` family has already explored signal,
    stop-loss, and weak-window tradeoff axes. The remaining underexplored
    question is whether a tighter hold/cooldown cadence can improve the
    `middle_third` without knocking the lane out of its 5-valid-window shape.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 300.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (54, 57, 60),
        "slopeThresholdPrice": (100.0, 105.0, 110.0),
        "takeProfitPriceMove": (425.0, 450.0, 475.0),
        "stopLossPriceMove": (300.0, 325.0, 350.0),
        "maxHoldBars": (7, 8, 9, 10),
        "cooldownBars": (3, 4, 5, 6),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                tempo_bonus = 0.0
                                if ema_span == 18:
                                    tempo_bonus += 0.5
                                if lookback == 57:
                                    tempo_bonus += 0.75
                                if threshold in (100.0, 105.0):
                                    tempo_bonus += 0.75
                                if take_profit == 450.0:
                                    tempo_bonus += 0.5
                                if stop_loss in (300.0, 325.0):
                                    tempo_bonus += 0.75
                                if hold_bars in (8, 9):
                                    tempo_bonus += 1.0
                                if cooldown in (4, 5):
                                    tempo_bonus += 1.0
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 7 and cooldown == 3:
                                    risk_penalty += 0.45
                                if hold_bars == 10 and cooldown == 6:
                                    risk_penalty += 0.35
                                if hold_bars == 10 and take_profit == 475.0:
                                    risk_penalty += 0.2
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 4.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 25.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 15.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - tempo_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_tempo_refinement_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live tempo refinement scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_exit_refinement_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Densify the converged near-live cluster on pure exit asymmetry.

    The current near-live trio has already been stressed on signal, cluster,
    weak-window, and tempo axes. The remaining narrow question is whether a
    tighter TP/SL ladder alone can improve the current distinct contender
    without changing the signal kernel or leaning on extra trade density.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 300.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18,),
        "slopeLookbackBars": (54, 57, 60),
        "slopeThresholdPrice": (100.0, 105.0, 110.0),
        "takeProfitPriceMove": (400.0, 425.0, 450.0, 475.0, 500.0),
        "stopLossPriceMove": (275.0, 300.0, 325.0, 350.0),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                exit_bonus = 0.0
                                if lookback == 57:
                                    exit_bonus += 0.75
                                if threshold == 105.0:
                                    exit_bonus += 0.75
                                if take_profit in (425.0, 450.0):
                                    exit_bonus += 1.25
                                elif take_profit == 475.0:
                                    exit_bonus += 0.5
                                if stop_loss in (300.0, 325.0):
                                    exit_bonus += 1.25
                                elif stop_loss == 350.0:
                                    exit_bonus += 0.5
                                if hold_bars == 8:
                                    exit_bonus += 0.5
                                if cooldown == 4:
                                    exit_bonus += 0.5
                                asymmetry_bonus = 0.0
                                if 1.25 <= (take_profit / stop_loss if stop_loss else 0.0) <= 1.55:
                                    asymmetry_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if take_profit == 500.0 and stop_loss == 275.0:
                                    risk_penalty += 0.25
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 20.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 12.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - exit_bonus
                                    - asymmetry_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_exit_refinement_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live exit refinement scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_stoploss_ladder_refinement_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Densify the converged near-live stop-loss ladder at micro-step resolution.

    The current lead pair `0003 / 0021` is effectively tied on full-window
    metrics and differs mainly on stop-loss placement. This family isolates that
    question by keeping the signal kernel anchored and scanning only a tighter
    stop-loss ladder, with minimal TP/tempo drift.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 312.5,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18,),
        "slopeLookbackBars": (54, 57, 60),
        "slopeThresholdPrice": (100.0, 105.0, 110.0),
        "takeProfitPriceMove": (425.0, 450.0),
        "stopLossPriceMove": (287.5, 300.0, 312.5, 325.0, 337.5, 350.0),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                ladder_bonus = 0.0
                                if lookback == 57:
                                    ladder_bonus += 0.75
                                if threshold == 105.0:
                                    ladder_bonus += 0.75
                                if take_profit == 450.0:
                                    ladder_bonus += 0.75
                                if stop_loss in (300.0, 312.5, 325.0):
                                    ladder_bonus += 1.5
                                elif stop_loss in (287.5, 337.5):
                                    ladder_bonus += 0.75
                                if hold_bars == 8:
                                    ladder_bonus += 0.5
                                if cooldown == 4:
                                    ladder_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if stop_loss in (287.5, 350.0):
                                    risk_penalty += 0.1
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 20.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 9.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - ladder_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_stoploss_ladder_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live stop-loss ladder refinement scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_stoploss_ladder_followup_configs(max_count: int = 48) -> list[dict[str, Any]]:
    """Second-pass local search around the current 312.5 stop-loss ladder rung.

    The first ladder pass answered that `312.5` belongs in the converged near-live
    cluster, but did not beat the current distinct contender `0021`. This
    follow-up keeps the signal kernel nearly fixed and narrows the search around
    the 300/312.5/325 stop-loss band to test whether a smaller local tweak can
    overtake the current contender without collapsing the 5-valid-window shape.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 312.5,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18,),
        "slopeLookbackBars": (57, 60),
        "slopeThresholdPrice": (100.0, 105.0, 110.0),
        "takeProfitPriceMove": (437.5, 450.0, 462.5),
        "stopLossPriceMove": (300.0, 306.25, 312.5, 318.75, 325.0),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                ladder_bonus = 0.0
                                if lookback == 57:
                                    ladder_bonus += 0.9
                                if threshold == 105.0:
                                    ladder_bonus += 0.9
                                if take_profit == 450.0:
                                    ladder_bonus += 0.8
                                if stop_loss == 312.5:
                                    ladder_bonus += 1.5
                                elif stop_loss in (306.25, 318.75):
                                    ladder_bonus += 1.0
                                elif stop_loss in (300.0, 325.0):
                                    ladder_bonus += 0.75
                                if hold_bars == 8:
                                    ladder_bonus += 0.5
                                if cooldown == 4:
                                    ladder_bonus += 0.6
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if stop_loss in (300.0, 325.0) and take_profit != 450.0:
                                    risk_penalty += 0.15
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(lookback - anchor["slopeLookbackBars"]) / 4.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 8.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 12.5
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 6.25
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - ladder_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_stoploss_ladder_followup_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live stop-loss ladder follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_stoploss_ladder_followup_micro_configs(max_count: int = 36) -> list[dict[str, Any]]:
    """Third-pass micro ladder around the current 306.25 stop-loss rung.

    The second-pass stop-loss follow-up confirmed that `306.25` belongs in the
    converged near-live cluster, but it still did not displace the current
    distinct contender. This micro family keeps the signal kernel nearly fixed
    and only probes a narrower 306.25-centered substep ladder to test whether a
    tighter local rung can overtake `0021` without breaking the 5-window shape.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 306.25,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18,),
        "slopeLookbackBars": (57, 60),
        "slopeThresholdPrice": (102.5, 105.0, 107.5),
        "takeProfitPriceMove": (443.75, 450.0, 456.25),
        "stopLossPriceMove": (303.125, 306.25, 309.375, 312.5),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                micro_bonus = 0.0
                                if lookback == 57:
                                    micro_bonus += 1.0
                                if threshold == 105.0:
                                    micro_bonus += 1.0
                                elif threshold in (102.5, 107.5):
                                    micro_bonus += 0.5
                                if take_profit == 450.0:
                                    micro_bonus += 0.9
                                elif take_profit in (443.75, 456.25):
                                    micro_bonus += 0.4
                                if stop_loss == 306.25:
                                    micro_bonus += 1.6
                                elif stop_loss in (303.125, 309.375):
                                    micro_bonus += 1.0
                                elif stop_loss == 312.5:
                                    micro_bonus += 0.65
                                if hold_bars == 8:
                                    micro_bonus += 0.55
                                if cooldown == 4:
                                    micro_bonus += 0.65
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if stop_loss in (303.125, 312.5) and take_profit != 450.0:
                                    risk_penalty += 0.1
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(lookback - anchor["slopeLookbackBars"]) / 3.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 5.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 6.25
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 3.125
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - micro_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live stop-loss ladder follow-up micro scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_stoploss_ladder_followup_micro_followup_configs(
    max_count: int = 24,
) -> list[dict[str, Any]]:
    """Fourth-pass micro ladder around the fresh 318.75 stop-loss rung.

    The prior micro pass moved the best same-cluster stop-loss rung up to
    `318.75`, but it still did not displace the current distinct contender.
    This second-stage micro family densifies only that newer pocket so we can
    test whether the refreshed 318.75 neighborhood contains a true local
    winner instead of another equivalent alias of the same converged kernel.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 318.75,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18,),
        "slopeLookbackBars": (57, 58),
        "slopeThresholdPrice": (103.75, 105.0, 106.25),
        "takeProfitPriceMove": (446.875, 450.0, 453.125),
        "stopLossPriceMove": (315.625, 317.1875, 318.75, 320.3125),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                ladder_bonus = 0.0
                                if lookback == 57:
                                    ladder_bonus += 0.9
                                elif lookback == 58:
                                    ladder_bonus += 0.4
                                if threshold == 105.0:
                                    ladder_bonus += 1.0
                                elif threshold in (103.75, 106.25):
                                    ladder_bonus += 0.45
                                if take_profit == 450.0:
                                    ladder_bonus += 1.0
                                elif take_profit in (446.875, 453.125):
                                    ladder_bonus += 0.45
                                if stop_loss == 318.75:
                                    ladder_bonus += 1.7
                                elif stop_loss in (317.1875, 320.3125):
                                    ladder_bonus += 1.0
                                elif stop_loss == 315.625:
                                    ladder_bonus += 0.55
                                if hold_bars == 8:
                                    ladder_bonus += 0.55
                                if cooldown == 4:
                                    ladder_bonus += 0.65
                                asymmetry_bonus = 0.0
                                if stop_loss and 1.40 <= (take_profit / stop_loss) <= 1.43:
                                    asymmetry_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(lookback - anchor["slopeLookbackBars"]) / 1.5
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 2.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 4.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 2.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - ladder_bonus
                                    - asymmetry_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": (
                f"hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_followup_{len(configs) + 1:04d}"
            ),
            "strategyName": "BTCUSD near-live stop-loss ladder follow-up micro follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_middle_window_contender_micro_configs(max_count: int = 24) -> list[dict[str, Any]]:
    """Ultra-local contender search around the current 325.0 middle-window lane.

    After the 318.75 stop-loss ladder pocket became the default stable anchor,
    the most useful unresolved question is whether the former 325.0 contender
    still has a tighter local neighborhood that can reclaim the distinct
    contender slot or even retake the anchor without drifting into a different
    personality. This batch stays narrowly centered on that 325.0 pocket.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18,),
        "slopeLookbackBars": (57, 58),
        "slopeThresholdPrice": (103.75, 105.0, 106.25),
        "takeProfitPriceMove": (446.875, 450.0, 453.125),
        "stopLossPriceMove": (321.875, 323.4375, 325.0, 326.5625, 328.125),
        "maxHoldBars": (8, 9),
        "cooldownBars": (4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                contender_bonus = 0.0
                                if lookback == 57:
                                    contender_bonus += 0.9
                                elif lookback == 58:
                                    contender_bonus += 0.35
                                if threshold == 105.0:
                                    contender_bonus += 1.0
                                elif threshold in (103.75, 106.25):
                                    contender_bonus += 0.45
                                if take_profit == 450.0:
                                    contender_bonus += 1.0
                                elif take_profit in (446.875, 453.125):
                                    contender_bonus += 0.45
                                if stop_loss == 325.0:
                                    contender_bonus += 1.6
                                elif stop_loss in (323.4375, 326.5625):
                                    contender_bonus += 1.0
                                elif stop_loss in (321.875, 328.125):
                                    contender_bonus += 0.55
                                if hold_bars == 8:
                                    contender_bonus += 0.55
                                if cooldown == 4:
                                    contender_bonus += 0.65
                                asymmetry_bonus = 0.0
                                if stop_loss and 1.37 <= (take_profit / stop_loss) <= 1.40:
                                    asymmetry_bonus += 0.7
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 9 and cooldown == 5:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(lookback - anchor["slopeLookbackBars"]) / 1.5
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 2.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 4.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 2.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - contender_bonus
                                    - asymmetry_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_middle_window_contender_micro_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live middle-window contender micro scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _near_live_middle_density_lift_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Try to lift middle-third trade density inside the converged near-live lane.

    The current `0003 / 0021 / 0012 / 0070` near-live cluster still lands on
    the same `middle_third` blockers. This family pushes a narrower cadence /
    threshold axis to see whether the cluster can add samples in the weak
    window without collapsing the 5-valid-window profile.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 57,
        "slopeThresholdPrice": 105.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 300.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (15, 18, 21),
        "slopeLookbackBars": (45, 48, 51, 54, 57),
        "slopeThresholdPrice": (85.0, 90.0, 95.0, 100.0, 105.0),
        "takeProfitPriceMove": (400.0, 425.0, 450.0),
        "stopLossPriceMove": (275.0, 300.0, 325.0),
        "maxHoldBars": (6, 7, 8),
        "cooldownBars": (2, 3, 4),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                density_bonus = 0.0
                                if ema_span in (18, 21):
                                    density_bonus += 0.5
                                if lookback in (48, 51, 54):
                                    density_bonus += 1.0
                                if threshold in (90.0, 95.0, 100.0):
                                    density_bonus += 1.0
                                if take_profit in (425.0, 450.0):
                                    density_bonus += 0.75
                                if stop_loss in (300.0, 325.0):
                                    density_bonus += 0.75
                                if hold_bars == 6:
                                    density_bonus += 1.75
                                elif hold_bars == 7:
                                    density_bonus += 1.0
                                if cooldown == 2:
                                    density_bonus += 1.75
                                elif cooldown == 3:
                                    density_bonus += 1.25
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 6 and cooldown == 2:
                                    risk_penalty += 0.15
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 4.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 25.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 15.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - density_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_near_live_middle_density_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD near-live middle-density lift scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_third_confirmation_configs(max_count: int = 120) -> list[dict[str, Any]]:
    """Densify the current 0302 stable champion around its weakest window.

    The broad middle-window rescue family still mixes short-champion, balanced,
    and yield neighborhoods. This confirmation batch stays narrowly centered on
    the current short-bias stable anchor so we can answer a sharper question:
    did a close local variant actually improve the middle-third weakness enough
    to challenge 0302, or is 0302 still the best stability anchor?
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 48,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 300.0,
        "maxHoldBars": 8,
        "cooldownBars": 6,
    }
    value_sets = {
        "emaSpan": (15, 18, 21, 24),
        "slopeLookbackBars": (36, 42, 48, 54, 60),
        "slopeThresholdPrice": (75.0, 90.0, 100.0, 110.0, 125.0),
        "takeProfitPriceMove": (400.0, 450.0, 500.0, 550.0),
        "stopLossPriceMove": (250.0, 275.0, 300.0, 325.0, 350.0),
        "maxHoldBars": (8, 10, 12, 14),
        "cooldownBars": (4, 5, 6, 7),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                rescue_bonus = 0.0
                                if hold_bars in (10, 12):
                                    rescue_bonus += 0.75
                                if cooldown in (4, 5):
                                    rescue_bonus += 1.0
                                if threshold in (90.0, 100.0):
                                    rescue_bonus += 0.5
                                if take_profit in (450.0, 500.0):
                                    rescue_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars >= 14 and cooldown >= 7:
                                    risk_penalty += 1.0
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 6.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 18.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 20.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 100.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 75.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 4.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.5
                                    + risk_penalty
                                    - rescue_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_third_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle-third confirmation scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_third_followup_configs(max_count: int = 96) -> list[dict[str, Any]]:
    """Second-pass local search around the best 0302 middle-third repair neighbor.

    The first confirmation pass showed that a close stop-loss variant can climb
    the overall stability ranking without actually fixing the middle-third
    weakness itself. This follow-up stays even tighter around that `0067`-like
    neighborhood so we can answer whether a small local adjustment can improve
    the weak window rather than just reshuffle the stronger windows.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 48,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 6,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (42, 48, 54),
        "slopeThresholdPrice": (90.0, 100.0, 110.0),
        "takeProfitPriceMove": (450.0, 500.0),
        "stopLossPriceMove": (300.0, 325.0, 350.0),
        "maxHoldBars": (8, 10, 12),
        "cooldownBars": (4, 5, 6),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                repair_bonus = 0.0
                                if stop_loss == 325.0:
                                    repair_bonus += 1.0
                                if threshold in (100.0, 110.0):
                                    repair_bonus += 0.5
                                if hold_bars in (8, 10):
                                    repair_bonus += 0.75
                                if cooldown in (4, 5):
                                    repair_bonus += 1.0
                                if take_profit == 500.0:
                                    repair_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 12 and cooldown == 6:
                                    risk_penalty += 0.75
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 3.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 12.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 15.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 75.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 50.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 2.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - repair_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_followup_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle-third follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_followup_refinement_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Tight local search around the current aggregate-stability fallback.

    Once the third lane converges to the `stable_middle_followup` family, the
    next useful question is no longer whether tradeoff/bridge can beat it, but
    whether a very small neighborhood around the chosen fallback can keep the
    same aggregate stability while improving Sharpe/trade-count or slightly
    reducing the weak-window burden. This batch intentionally stays narrower
    than the original follow-up search.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 48,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 6,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (48, 54),
        "slopeThresholdPrice": (95.0, 100.0, 105.0),
        "takeProfitPriceMove": (425.0, 450.0, 475.0),
        "stopLossPriceMove": (300.0, 312.5, 325.0, 337.5),
        "maxHoldBars": (8, 10),
        "cooldownBars": (5, 6, 7),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                refinement_bonus = 0.0
                                if stop_loss in (312.5, 325.0):
                                    refinement_bonus += 1.0
                                if take_profit in (450.0, 475.0):
                                    refinement_bonus += 0.5
                                if hold_bars == 8:
                                    refinement_bonus += 0.5
                                if cooldown in (5, 6):
                                    refinement_bonus += 1.0
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 10 and cooldown == 7:
                                    risk_penalty += 0.5
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 3.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 12.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 50.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 25.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.5
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - refinement_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_followup_refinement_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle-third follow-up refinement scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_followup_refinement_followup_configs(max_count: int = 48) -> list[dict[str, Any]]:
    """Ultra-local search around the current refinement winner.

    Once the third lane converges again to a `stable_middle_followup_refinement`
    winner, the next useful question is whether an even tighter neighborhood
    around that winner can preserve the same aggregate stability while nudging
    trade count or weak-window Sharpe slightly higher. This family intentionally
    avoids the broader parameter drift from the earlier follow-up batches.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 48,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 312.5,
        "maxHoldBars": 8,
        "cooldownBars": 6,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (48, 54),
        "slopeThresholdPrice": (100.0, 105.0),
        "takeProfitPriceMove": (437.5, 450.0, 462.5),
        "stopLossPriceMove": (300.0, 312.5, 325.0),
        "maxHoldBars": (8, 9, 10),
        "cooldownBars": (5, 6, 7),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                refinement_bonus = 0.0
                                if stop_loss == 312.5:
                                    refinement_bonus += 1.25
                                elif stop_loss == 325.0:
                                    refinement_bonus += 0.5
                                if take_profit == 450.0:
                                    refinement_bonus += 1.0
                                if hold_bars in (8, 9):
                                    refinement_bonus += 0.75
                                if cooldown in (5, 6):
                                    refinement_bonus += 1.0
                                if threshold == 100.0:
                                    refinement_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 10 and cooldown == 7:
                                    risk_penalty += 0.5
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 3.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 12.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 37.5
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 12.5
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 1.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - refinement_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_followup_refinement_followup_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle-third refinement follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_followup_refinement_micro_configs(max_count: int = 36) -> list[dict[str, Any]]:
    """Micro-step search around the current third-line refinement winner.

    The current third line has already converged to a tight refinement winner.
    This batch asks a narrower question than the broader follow-up family:
    can very small TP/SL, hold, or cooldown nudges improve the same aggregate
    fallback without drifting into a different personality?
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 48,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 312.5,
        "maxHoldBars": 8,
        "cooldownBars": 6,
    }
    value_sets = {
        "emaSpan": (18,),
        "slopeLookbackBars": (48, 51),
        "slopeThresholdPrice": (100.0, 102.5, 105.0),
        "takeProfitPriceMove": (437.5, 450.0, 462.5),
        "stopLossPriceMove": (306.25, 312.5, 318.75, 325.0),
        "maxHoldBars": (8, 9),
        "cooldownBars": (5, 6),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                refinement_bonus = 0.0
                                if stop_loss == 312.5:
                                    refinement_bonus += 1.25
                                elif stop_loss in (306.25, 318.75):
                                    refinement_bonus += 0.75
                                if take_profit == 450.0:
                                    refinement_bonus += 1.0
                                if hold_bars == 8:
                                    refinement_bonus += 0.75
                                if cooldown == 6:
                                    refinement_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 2.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 6.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 5.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 12.5
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 6.25
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 0.75
                                    + abs(cooldown - anchor["cooldownBars"]) / 0.75
                                    + risk_penalty
                                    - refinement_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_followup_refinement_micro_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle-third refinement micro scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_followup_refinement_micro_followup_configs(max_count: int = 24) -> list[dict[str, Any]]:
    """Ultra-local micro ladder search around the current micro winner.

    The first micro pass already tests a 306.25-centered stop-loss ladder.
    This batch tightens the neighborhood again so we can answer a narrower
    question: is there a tiny TP/SL or tempo nudge near that micro winner
    that finally beats the current refinement leader rather than merely
    matching it?
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 48,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 306.25,
        "maxHoldBars": 8,
        "cooldownBars": 6,
    }
    value_sets = {
        "emaSpan": (18,),
        "slopeLookbackBars": (48, 51),
        "slopeThresholdPrice": (100.0, 101.25, 102.5),
        "takeProfitPriceMove": (443.75, 450.0, 456.25),
        "stopLossPriceMove": (303.125, 306.25, 309.375, 312.5),
        "maxHoldBars": (8, 9),
        "cooldownBars": (5, 6),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                refinement_bonus = 0.0
                                if stop_loss == 306.25:
                                    refinement_bonus += 1.5
                                elif stop_loss in (303.125, 309.375):
                                    refinement_bonus += 0.9
                                if take_profit == 450.0:
                                    refinement_bonus += 1.0
                                elif take_profit in (443.75, 456.25):
                                    refinement_bonus += 0.4
                                if hold_bars == 8:
                                    refinement_bonus += 0.75
                                if cooldown == 6:
                                    refinement_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 1.5
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 4.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 2.5
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 6.25
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 3.125
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 0.5
                                    + abs(cooldown - anchor["cooldownBars"]) / 0.5
                                    + risk_penalty
                                    - refinement_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_followup_refinement_micro_followup_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle-third refinement micro follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_weak_window_confirmation_configs(max_count: int = 48) -> list[dict[str, Any]]:
    """Third-pass search that prioritizes the weak window itself over aggregate rank.

    The second-pass follow-up found a variant that improves aggregate stability,
    but it did not improve the actual `middle_third` Sharpe/trade-count profile.
    This batch stays tightly anchored on the best weak-window candidates that
    surfaced in the broader scan, so we can test whether a nearby short-bias
    neighborhood can raise the weak window without collapsing the overall lane.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 54,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 4,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (48, 54),
        "slopeThresholdPrice": (100.0, 110.0),
        "takeProfitPriceMove": (450.0, 500.0),
        "stopLossPriceMove": (300.0, 325.0, 350.0),
        "maxHoldBars": (6, 8, 10),
        "cooldownBars": (3, 4, 5),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                weak_window_bonus = 0.0
                                if lookback == 54:
                                    weak_window_bonus += 1.0
                                if cooldown in (4, 5):
                                    weak_window_bonus += 1.0
                                if hold_bars in (6, 8):
                                    weak_window_bonus += 0.75
                                if threshold in (100.0, 110.0):
                                    weak_window_bonus += 0.5
                                if take_profit in (450.0, 500.0):
                                    weak_window_bonus += 0.5
                                if stop_loss == 325.0:
                                    weak_window_bonus += 0.75
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 2.0
                                if hold_bars == 10 and cooldown == 3:
                                    risk_penalty += 0.75
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 3.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 10.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 12.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 60.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 40.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 2.0
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                    + risk_penalty
                                    - weak_window_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_weak_window_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle weak-window confirmation scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_weak_window_bridge_configs(max_count: int = 48) -> list[dict[str, Any]]:
    """Bridge search between the weak-window spike and the stable anchor.

    The weak-window confirmation batch found candidates with meaningfully
    stronger `middle_third` metrics, but they collapsed overall lane stability.
    This bridge batch stays between the 0302 anchor and the best weak-window
    spike so we can test whether a slightly slower / safer short-bias regime can
    preserve more valid windows while still improving the weak window itself.
    """

    anchor = {
        "emaSpan": 18,
        "slopeLookbackBars": 48,
        "slopeThresholdPrice": 100.0,
        "takeProfitPriceMove": 450.0,
        "stopLossPriceMove": 325.0,
        "maxHoldBars": 8,
        "cooldownBars": 5,
    }
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (48, 54),
        "slopeThresholdPrice": (90.0, 100.0, 110.0),
        "takeProfitPriceMove": (450.0, 500.0),
        "stopLossPriceMove": (300.0, 325.0, 350.0),
        "maxHoldBars": (8, 10, 12),
        "cooldownBars": (4, 5, 6),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for ema_span in value_sets["emaSpan"]:
        for lookback in value_sets["slopeLookbackBars"]:
            for threshold in value_sets["slopeThresholdPrice"]:
                for take_profit in value_sets["takeProfitPriceMove"]:
                    for stop_loss in value_sets["stopLossPriceMove"]:
                        for hold_bars in value_sets["maxHoldBars"]:
                            for cooldown in value_sets["cooldownBars"]:
                                bridge_bonus = 0.0
                                if cooldown in (5, 6):
                                    bridge_bonus += 1.0
                                if hold_bars in (8, 10):
                                    bridge_bonus += 0.75
                                if stop_loss in (325.0, 350.0):
                                    bridge_bonus += 0.75
                                if lookback in (48, 54):
                                    bridge_bonus += 0.5
                                if take_profit == 450.0:
                                    bridge_bonus += 0.5
                                if threshold == 100.0:
                                    bridge_bonus += 0.5
                                risk_penalty = 0.0
                                if stop_loss >= take_profit:
                                    risk_penalty += 1.75
                                if hold_bars == 12 and cooldown == 4:
                                    risk_penalty += 0.5
                                distance = (
                                    abs(ema_span - anchor["emaSpan"]) / 3.0
                                    + abs(lookback - anchor["slopeLookbackBars"]) / 12.0
                                    + abs(threshold - anchor["slopeThresholdPrice"]) / 14.0
                                    + abs(take_profit - anchor["takeProfitPriceMove"]) / 60.0
                                    + abs(stop_loss - anchor["stopLossPriceMove"]) / 35.0
                                    + abs(hold_bars - anchor["maxHoldBars"]) / 2.5
                                    + abs(cooldown - anchor["cooldownBars"]) / 1.25
                                    + risk_penalty
                                    - bridge_bonus
                                )
                                raw.append((distance, {
                                    "bias": "short",
                                    "emaSpan": ema_span,
                                    "slopeLookbackBars": lookback,
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": hold_bars,
                                    "cooldownBars": cooldown,
                                }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_bridge_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle weak-window bridge scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _stable_middle_tradeoff_followup_configs(max_count: int = 72) -> list[dict[str, Any]]:
    """Follow-up bridge search for a real middle-third tradeoff candidate.

    The first weak-window bridge confirmed two useful facts:
    bridge_0015 can preserve `2+` valid windows, while bridge_0003 can improve
    middle-third Sharpe/trade count. This follow-up batch searches the small
    neighborhood between those two shapes and the best aggregate follow-up
    candidate so we can test whether a short-bias variant can improve the weak
    window without collapsing first-half / first-third quality.
    """

    anchors = [
        {
            "emaSpan": 18,
            "slopeLookbackBars": 48,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 450.0,
            "stopLossPriceMove": 350.0,
            "maxHoldBars": 8,
            "cooldownBars": 5,
        },
        {
            "emaSpan": 18,
            "slopeLookbackBars": 54,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 450.0,
            "stopLossPriceMove": 350.0,
            "maxHoldBars": 8,
            "cooldownBars": 4,
        },
        {
            "emaSpan": 21,
            "slopeLookbackBars": 48,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 500.0,
            "stopLossPriceMove": 325.0,
            "maxHoldBars": 8,
            "cooldownBars": 6,
        },
    ]
    value_sets = {
        "emaSpan": (18, 21),
        "slopeLookbackBars": (48, 51, 54, 57),
        "slopeThresholdPrice": (90.0, 100.0, 110.0),
        "takeProfitPriceMove": (450.0, 500.0),
        "stopLossPriceMove": (325.0, 350.0),
        "maxHoldBars": (8, 10),
        "cooldownBars": (4, 5, 6),
    }

    raw: list[tuple[float, dict[str, Any]]] = []
    for anchor in anchors:
        for ema_span in value_sets["emaSpan"]:
            for lookback in value_sets["slopeLookbackBars"]:
                for threshold in value_sets["slopeThresholdPrice"]:
                    for take_profit in value_sets["takeProfitPriceMove"]:
                        for stop_loss in value_sets["stopLossPriceMove"]:
                            for hold_bars in value_sets["maxHoldBars"]:
                                for cooldown in value_sets["cooldownBars"]:
                                    tradeoff_bonus = 0.0
                                    if cooldown in (5, 6):
                                        tradeoff_bonus += 1.0
                                    if lookback in (51, 54):
                                        tradeoff_bonus += 0.75
                                    if stop_loss == 350.0:
                                        tradeoff_bonus += 0.75
                                    if take_profit == 450.0:
                                        tradeoff_bonus += 0.5
                                    if hold_bars == 8:
                                        tradeoff_bonus += 0.5
                                    if threshold == 100.0:
                                        tradeoff_bonus += 0.5
                                    risk_penalty = 0.0
                                    if stop_loss >= take_profit:
                                        risk_penalty += 1.5
                                    if cooldown == 4 and hold_bars == 10:
                                        risk_penalty += 0.75
                                    if lookback == 57 and threshold == 110.0:
                                        risk_penalty += 0.5
                                    distance = (
                                        abs(ema_span - anchor["emaSpan"]) / 3.0
                                        + abs(lookback - anchor["slopeLookbackBars"]) / 8.0
                                        + abs(threshold - anchor["slopeThresholdPrice"]) / 10.0
                                        + abs(take_profit - anchor["takeProfitPriceMove"]) / 50.0
                                        + abs(stop_loss - anchor["stopLossPriceMove"]) / 30.0
                                        + abs(hold_bars - anchor["maxHoldBars"]) / 2.0
                                        + abs(cooldown - anchor["cooldownBars"]) / 1.0
                                        + risk_penalty
                                        - tradeoff_bonus
                                    )
                                    raw.append((distance, {
                                        "bias": "short",
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    }))

    configs: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for _, parameters in sorted(raw, key=lambda item: item[0]):
        key = tuple(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        configs.append({
            "strategyId": f"hfm_crypto_btc_stable_middle_tradeoff_{len(configs) + 1:04d}",
            "strategyName": "BTCUSD stable middle tradeoff follow-up scan",
            "strategyFamily": "ema_slope_regime",
            "parameters": parameters,
        })
        if len(configs) >= max_count:
            break
    return configs


def _focused_scan_configs(max_configs: int) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[tuple[str, Any], ...]]] = set()

    def add(config: dict[str, Any]) -> None:
        key = _candidate_key(config)
        if key in seen or len(configs) >= max_configs:
            return
        seen.add(key)
        configs.append(config)

    for config in BTC_PROFILE_CONFIGS:
        add(dict(config))
    for config in _priority_stability_configs():
        add(config)
    champion_repair_configs = _champion_repair_configs()
    for config in champion_repair_configs[:6]:
        add(config)
    balanced_yield_configs = _balanced_yield_repair_configs()
    yield_leader_confirmation_configs = _yield_leader_confirmation_configs()
    frontier_confirmation_configs = _frontier_high_yield_confirmation_configs()
    near_live_stability_configs = _near_live_stability_confirmation_configs()
    near_live_stability_followup_configs = _near_live_stability_followup_configs()
    near_live_refinement_configs = _near_live_followup_refinement_configs()
    near_live_middle_window_configs = _near_live_middle_window_followup_configs()
    near_live_signal_refinement_configs = _near_live_signal_refinement_configs()
    near_live_signal_refinement_followup_configs = _near_live_signal_refinement_followup_configs()
    near_live_high_yield_neighborhood_configs = _near_live_high_yield_neighborhood_configs()
    near_live_high_yield_neighborhood_followup_configs = _near_live_high_yield_neighborhood_followup_configs()
    near_live_high_yield_neighborhood_followup_micro_configs = (
        _near_live_high_yield_neighborhood_followup_micro_configs()
    )
    near_live_high_yield_neighborhood_followup_micro_followup_configs = (
        _near_live_high_yield_neighborhood_followup_micro_followup_configs()
    )
    near_live_cluster_refinement_configs = _near_live_middle_window_cluster_refinement_configs()
    near_live_tempo_refinement_configs = _near_live_tempo_refinement_configs()
    near_live_exit_refinement_configs = _near_live_exit_refinement_configs()
    near_live_stoploss_ladder_configs = _near_live_stoploss_ladder_refinement_configs()
    near_live_stoploss_ladder_followup_configs = _near_live_stoploss_ladder_followup_configs()
    near_live_stoploss_ladder_followup_micro_configs = _near_live_stoploss_ladder_followup_micro_configs()
    near_live_stoploss_ladder_followup_micro_followup_configs = (
        _near_live_stoploss_ladder_followup_micro_followup_configs()
    )
    near_live_middle_window_contender_micro_configs = (
        _near_live_middle_window_contender_micro_configs()
    )
    near_live_middle_tradeoff_configs = _near_live_middle_tradeoff_configs()
    near_live_middle_density_configs = _near_live_middle_density_lift_configs()
    stable_middle_confirmation_configs = _stable_middle_third_confirmation_configs()
    stable_middle_followup_configs = _stable_middle_third_followup_configs()
    stable_middle_followup_refinement_configs = _stable_middle_followup_refinement_configs()
    stable_middle_followup_refinement_followup_configs = _stable_middle_followup_refinement_followup_configs()
    stable_middle_followup_refinement_micro_configs = _stable_middle_followup_refinement_micro_configs()
    stable_middle_followup_refinement_micro_followup_configs = (
        _stable_middle_followup_refinement_micro_followup_configs()
    )
    stable_middle_weak_window_configs = _stable_middle_weak_window_confirmation_configs()
    stable_middle_bridge_configs = _stable_middle_weak_window_bridge_configs()
    stable_middle_tradeoff_configs = _stable_middle_tradeoff_followup_configs()
    middle_window_rescue_configs = _middle_window_rescue_repair_configs()
    balanced_quality_configs = _balanced_quality_repair_configs()
    sample_rich_quality_configs = _sample_rich_quality_repair_configs()
    balanced_sample_density_configs = _balanced_sample_density_repair_configs()
    prioritized_repair_batches = [
        balanced_yield_configs[:64],
        yield_leader_confirmation_configs[:64],
        frontier_confirmation_configs[:64],
        near_live_stability_configs[:64],
        near_live_stability_followup_configs[:32],
        near_live_refinement_configs[:24],
        near_live_middle_window_configs[:24],
        near_live_signal_refinement_configs[:24],
        near_live_signal_refinement_followup_configs[:12],
        near_live_high_yield_neighborhood_configs[:16],
        near_live_high_yield_neighborhood_followup_configs[:12],
        near_live_high_yield_neighborhood_followup_micro_configs[:8],
        near_live_high_yield_neighborhood_followup_micro_followup_configs[:8],
        near_live_cluster_refinement_configs[:24],
        near_live_tempo_refinement_configs[:24],
        near_live_stoploss_ladder_configs[:24],
        near_live_stoploss_ladder_followup_configs[:16],
        near_live_stoploss_ladder_followup_micro_configs[:8],
        near_live_stoploss_ladder_followup_micro_followup_configs[:8],
        near_live_middle_window_contender_micro_configs[:8],
        near_live_exit_refinement_configs[:24],
        near_live_middle_tradeoff_configs[:24],
        near_live_middle_density_configs[:24],
        middle_window_rescue_configs[:8],
        stable_middle_confirmation_configs[:12],
        stable_middle_followup_configs[:6],
        stable_middle_followup_refinement_configs[:6],
        stable_middle_followup_refinement_followup_configs[:6],
        stable_middle_followup_refinement_micro_configs[:6],
        stable_middle_followup_refinement_micro_followup_configs[:6],
        stable_middle_weak_window_configs[:6],
        stable_middle_bridge_configs[:6],
        stable_middle_tradeoff_configs[:4],
        sample_rich_quality_configs[:8],
        balanced_quality_configs[:4],
        balanced_sample_density_configs[:8],
        balanced_sample_density_configs[8:16],
        balanced_quality_configs[4:64],
        sample_rich_quality_configs[8:43],
        balanced_sample_density_configs[16:48],
        balanced_yield_configs[64:112],
        yield_leader_confirmation_configs[64:96],
        frontier_confirmation_configs[64:],
        near_live_stability_configs[64:],
        near_live_stability_followup_configs[32:],
        near_live_refinement_configs[24:],
        near_live_middle_window_configs[24:],
        near_live_signal_refinement_configs[24:],
        near_live_signal_refinement_followup_configs[12:],
        near_live_high_yield_neighborhood_configs[16:],
        near_live_high_yield_neighborhood_followup_configs[12:],
        near_live_high_yield_neighborhood_followup_micro_configs[8:],
        near_live_high_yield_neighborhood_followup_micro_followup_configs[8:],
        near_live_cluster_refinement_configs[24:],
        near_live_tempo_refinement_configs[24:],
        near_live_stoploss_ladder_configs[24:],
        near_live_stoploss_ladder_followup_configs[16:],
        near_live_stoploss_ladder_followup_micro_configs[8:],
        near_live_stoploss_ladder_followup_micro_followup_configs[8:],
        near_live_middle_window_contender_micro_configs[8:],
        near_live_exit_refinement_configs[24:],
        near_live_middle_tradeoff_configs[24:],
        near_live_middle_density_configs[24:],
        stable_middle_confirmation_configs[12:],
        stable_middle_followup_configs[6:64],
        stable_middle_followup_refinement_configs[6:48],
        stable_middle_followup_refinement_followup_configs[6:32],
        stable_middle_followup_refinement_micro_configs[6:24],
        stable_middle_followup_refinement_micro_followup_configs[6:18],
        stable_middle_weak_window_configs[6:],
        stable_middle_bridge_configs[6:],
        middle_window_rescue_configs[8:72],
        balanced_quality_configs[64:128],
        sample_rich_quality_configs[43:160],
        balanced_sample_density_configs[48:96],
        stable_middle_tradeoff_configs[4:],
        yield_leader_confirmation_configs[96:],
        stable_middle_followup_configs[64:],
        stable_middle_followup_refinement_configs[48:],
        stable_middle_followup_refinement_followup_configs[32:],
        stable_middle_followup_refinement_micro_configs[24:],
        stable_middle_followup_refinement_micro_followup_configs[18:],
        balanced_yield_configs[112:],
        middle_window_rescue_configs[72:],
        balanced_quality_configs[128:],
        sample_rich_quality_configs[160:],
        balanced_sample_density_configs[96:],
    ]
    for batch in prioritized_repair_batches:
        for config in batch:
            add(config)
    for config in champion_repair_configs[6:]:
        add(config)

    index = 0
    for bias in ("short", "both"):
        for ema_span in (18, 30, 36):
            for lookback in (48, 144):
                for threshold in (25.0, 50.0, 75.0, 100.0):
                    for take_profit, stop_loss in (
                        (450.0, 300.0),
                        (750.0, 400.0),
                        (900.0, 500.0),
                    ):
                        for hold_bars in (8, 16, 36):
                            for cooldown in (4, 6):
                                index += 1
                                add({
                                    "strategyId": f"hfm_crypto_btc_scan_stability_{index:04d}",
                                    "strategyName": "BTCUSD short-window stability scan",
                                    "strategyFamily": "ema_slope_regime",
                                    "parameters": {
                                        "bias": bias,
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    },
                                })
                                if len(configs) >= max_configs:
                                    return configs

    for bias in ("both", "short"):
        for ema_span in (36, 48, 72):
            for lookback in (96, 144, 192):
                for threshold in (75.0, 100.0, 150.0, 200.0, 250.0, 300.0):
                    for take_profit, stop_loss in (
                        (450.0, 300.0),
                        (600.0, 400.0),
                        (600.0, 500.0),
                        (900.0, 500.0),
                        (900.0, 650.0),
                        (1200.0, 600.0),
                        (1500.0, 500.0),
                    ):
                        for hold_bars in (18, 24, 36, 48):
                            for cooldown in (0, 2, 4, 8):
                                index += 1
                                add({
                                    "strategyId": f"hfm_crypto_btc_scan_focused_{index:04d}",
                                    "strategyName": "BTCUSD focused stability scan",
                                    "strategyFamily": "ema_slope_regime",
                                    "parameters": {
                                        "bias": bias,
                                        "emaSpan": ema_span,
                                        "slopeLookbackBars": lookback,
                                        "slopeThresholdPrice": threshold,
                                        "takeProfitPriceMove": take_profit,
                                        "stopLossPriceMove": stop_loss,
                                        "maxHoldBars": hold_bars,
                                        "cooldownBars": cooldown,
                                    },
                                })
                                if len(configs) >= max_configs:
                                    return configs
    return configs


def _compact_retest(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("fullWindowMetrics") if isinstance(row.get("fullWindowMetrics"), dict) else {}
    tradeoff_repair_label = "stable middle tradeoff repair line"
    return {
        "strategyId": row.get("strategyId"),
        "strategyName": row.get("strategyName"),
        "strategyFamily": row.get("strategyFamily"),
        "status": row.get("status"),
        "validWindowCount": row.get("validWindowCount"),
        "windowCount": row.get("windowCount"),
        "positiveWindowCount": row.get("positiveWindowCount"),
        "negativeWindowCount": row.get("negativeWindowCount"),
        "negativeWindows": row.get("negativeWindows", []),
        "positiveMajorWindowCount": row.get("positiveMajorWindowCount"),
        "majorWindowFailureCount": row.get("majorWindowFailureCount"),
        "negativeMajorWindows": row.get("negativeMajorWindows", []),
        "score": row.get("score"),
        "fullWindowMetrics": {
            "pnlUsd": metrics.get("pnlUsd"),
            "roiPct": metrics.get("roiPct"),
            "sharpe": metrics.get("sharpe"),
            "maxDrawdownPct": metrics.get("maxDrawdownPct"),
            "tradeCount": metrics.get("tradeCount"),
            "liquidationCount": metrics.get("liquidationCount"),
        },
        "parameters": row.get("parameters", {}),
        "blockers": row.get("blockers", []),
        "windowSummary": [
            {
                "window": window.get("window"),
                "pnlUsd": (window.get("metrics") or {}).get("pnlUsd"),
                "sharpe": (window.get("metrics") or {}).get("sharpe"),
                "tradeCount": (window.get("metrics") or {}).get("tradeCount"),
                "blockers": window.get("blockers", []),
            }
            for window in row.get("windows", [])
            if isinstance(window, dict)
        ],
    }


def _repair_diagnostics(retests: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {
        "shortChampionRepair": "hfm_crypto_btc_champion_repair_",
        "balancedYieldRepair": "hfm_crypto_btc_balanced_yield_repair_",
        "yieldLeaderConfirmation": "hfm_crypto_btc_yield_leader_confirmation_",
        "nearLiveStabilityRepair": "hfm_crypto_btc_near_live_stability_",
        "nearLiveStabilityFollowup": "hfm_crypto_btc_near_live_followup_",
        "nearLiveStabilityRefinement": "hfm_crypto_btc_near_live_refinement_",
        "nearLiveMiddleWindowFollowup": "hfm_crypto_btc_near_live_middle_window_",
        "nearLiveSignalRefinement": "hfm_crypto_btc_near_live_signal_refinement_",
        "nearLiveSignalRefinementFollowup": "hfm_crypto_btc_near_live_signal_refinement_followup_",
        "nearLiveHighYieldNeighborhood": "hfm_crypto_btc_near_live_high_yield_",
        "nearLiveHighYieldNeighborhoodFollowup": "hfm_crypto_btc_near_live_high_yield_followup_",
        "nearLiveHighYieldNeighborhoodFollowupMicro": "hfm_crypto_btc_near_live_high_yield_followup_micro_",
        "nearLiveHighYieldNeighborhoodFollowupMicroFollowup": (
            "hfm_crypto_btc_near_live_high_yield_followup_micro_followup_"
        ),
        "nearLiveClusterRefinement": "hfm_crypto_btc_near_live_cluster_refinement_",
        "nearLiveTempoRefinement": "hfm_crypto_btc_near_live_tempo_refinement_",
        "nearLiveStoplossLadderRefinement": "hfm_crypto_btc_near_live_stoploss_ladder_",
        "nearLiveStoplossLadderFollowup": "hfm_crypto_btc_near_live_stoploss_ladder_followup_",
        "nearLiveStoplossLadderFollowupMicro": "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_",
        "nearLiveStoplossLadderFollowupMicroFollowup": (
            "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_followup_"
        ),
        "nearLiveMiddleWindowContenderMicro": "hfm_crypto_btc_near_live_middle_window_contender_micro_",
        "nearLiveExitRefinement": "hfm_crypto_btc_near_live_exit_refinement_",
        "nearLiveMiddleTradeoff": "hfm_crypto_btc_near_live_middle_tradeoff_",
        "nearLiveMiddleDensityLift": "hfm_crypto_btc_near_live_middle_density_",
        "stableMiddleThirdConfirmation": "hfm_crypto_btc_stable_middle_third_",
        "stableMiddleThirdFollowup": "hfm_crypto_btc_stable_middle_followup_",
        "stableMiddleThirdFollowupRefinement": "hfm_crypto_btc_stable_middle_followup_refinement_",
        "stableMiddleThirdFollowupRefinementFollowup": "hfm_crypto_btc_stable_middle_followup_refinement_followup_",
        "stableMiddleThirdFollowupRefinementMicro": "hfm_crypto_btc_stable_middle_followup_refinement_micro_",
        "stableMiddleThirdFollowupRefinementMicroFollowup": "hfm_crypto_btc_stable_middle_followup_refinement_micro_followup_",
        "stableMiddleWeakWindowConfirmation": "hfm_crypto_btc_stable_middle_weak_window_",
        "stableMiddleWeakWindowBridge": "hfm_crypto_btc_stable_middle_bridge_",
        "stableMiddleTradeoffFollowup": "hfm_crypto_btc_stable_middle_tradeoff_",
        "middleWindowRescueRepair": "hfm_crypto_btc_middle_window_rescue_",
        "balancedQualityRepair": "hfm_crypto_btc_balanced_quality_repair_",
        "sampleRichQualityRepair": "hfm_crypto_btc_sample_rich_quality_",
        "balancedSampleDensityRepair": "hfm_crypto_btc_balanced_sample_density_",
    }
    diagnostics: dict[str, Any] = {}
    for group_id, prefix in groups.items():
        group = [row for row in retests if str(row.get("strategyId") or "").startswith(prefix)]
        ranked_group = _ranked_btc_retests(group)
        highest_trade = max(
            group,
            key=lambda row: (
                float((row.get("fullWindowMetrics") or {}).get("tradeCount") or 0.0),
                float((row.get("fullWindowMetrics") or {}).get("pnlUsd") or 0.0),
            ),
            default={},
        )
        diagnostics[group_id] = {
            "candidateCount": len(group),
            "bestByStabilityRank": _compact_retest(ranked_group[0]) if ranked_group else {},
            "highestTradeCountCandidate": _compact_retest(highest_trade) if highest_trade else {},
        }

    density_best = diagnostics["balancedSampleDensityRepair"].get("bestByStabilityRank", {})
    density_metrics = density_best.get("fullWindowMetrics") if isinstance(density_best.get("fullWindowMetrics"), dict) else {}
    diagnostics["conclusionZh"] = (
        "样本密度修复能提高交易数，但当前最佳 density 候选 Sharpe/窗口质量不足；BTC 下一步优先看 quality-first 高收益慢频修复，或补更长 CopyRates。"
        if density_metrics and float(density_metrics.get("sharpe") or 0.0) < 1.0
        else "样本密度修复仍可继续观察。"
    )
    return diagnostics


def _window_failure_profile(candidate: dict[str, Any]) -> dict[str, Any]:
    windows = [window for window in candidate.get("windows", []) if isinstance(window, dict)]
    weak_windows: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    for window in windows:
        blockers = [str(blocker) for blocker in window.get("blockers", [])]
        if not blockers:
            continue
        for blocker in blockers:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        metrics = window.get("metrics") if isinstance(window.get("metrics"), dict) else {}
        weak_windows.append({
            "window": window.get("window"),
            "pnlUsd": metrics.get("pnlUsd"),
            "sharpe": metrics.get("sharpe"),
            "tradeCount": metrics.get("tradeCount"),
            "blockers": blockers,
        })
    primary_blockers = [
        blocker
        for blocker, _ in sorted(blocker_counts.items(), key=lambda item: (-item[1], item[0]))
    ][:5]
    return {
        "strategyId": candidate.get("strategyId"),
        "weakWindowCount": len(weak_windows),
        "weakWindows": weak_windows,
        "primaryBlockers": primary_blockers,
    }


def _tradeoff_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    metrics = candidate.get("fullWindowMetrics") if isinstance(candidate.get("fullWindowMetrics"), dict) else {}
    parameters = candidate.get("parameters") if isinstance(candidate.get("parameters"), dict) else {}
    return {
        "strategyId": candidate.get("strategyId"),
        "pnlUsd": metrics.get("pnlUsd"),
        "sharpe": metrics.get("sharpe"),
        "maxDrawdownPct": metrics.get("maxDrawdownPct"),
        "tradeCount": metrics.get("tradeCount"),
        "validWindowCount": candidate.get("validWindowCount"),
        "windowCount": candidate.get("windowCount"),
        "bias": parameters.get("bias"),
        "takeProfitPriceMove": parameters.get("takeProfitPriceMove"),
        "stopLossPriceMove": parameters.get("stopLossPriceMove"),
        "maxHoldBars": parameters.get("maxHoldBars"),
        "cooldownBars": parameters.get("cooldownBars"),
    }


def _tradeoff_identity(candidate: dict[str, Any]) -> tuple[str, float, float, float, float]:
    row = _dict(candidate)
    return (
        str(row.get("bias") or ""),
        _num(row.get("takeProfitPriceMove")),
        _num(row.get("stopLossPriceMove")),
        _num(row.get("maxHoldBars")),
        _num(row.get("cooldownBars")),
    )


def _has_meaningful_tradeoff_identity(candidate: dict[str, Any]) -> bool:
    bias, take_profit, stop_loss, max_hold, cooldown = _tradeoff_identity(candidate)
    return bool(
        bias
        or take_profit > 0
        or stop_loss > 0
        or max_hold > 0
        or cooldown > 0
    )


def _window_summary_entry(candidate: dict[str, Any], window_name: str) -> dict[str, Any]:
    for window in _list(candidate.get("windowSummary")):
        row = _dict(window)
        if str(row.get("window") or "") == window_name:
            return row
    for window in _list(candidate.get("windows")):
        row = _dict(window)
        metrics = _dict(row.get("metrics"))
        if str(row.get("window") or "") == window_name:
            return {
                "window": row.get("window"),
                "pnlUsd": metrics.get("pnlUsd"),
                "sharpe": metrics.get("sharpe"),
                "tradeCount": metrics.get("tradeCount"),
                "blockers": _list(row.get("blockers")),
            }
    return {}


def _near_live_stability_candidate(
    top_candidates: list[dict[str, Any]],
    *,
    most_stable_strategy_id: Any,
    high_yield_strategy_id: Any,
) -> dict[str, Any]:
    excluded_ids = {
        str(most_stable_strategy_id or "").strip(),
        str(high_yield_strategy_id or "").strip(),
    }
    candidates: list[dict[str, Any]] = []
    for row in top_candidates:
        candidate = _dict(row)
        strategy_id = str(candidate.get("strategyId") or "").strip()
        if not strategy_id or strategy_id in excluded_ids:
            continue
        candidates.append(candidate)
    if not candidates:
        return {}

    def rank(row: dict[str, Any]) -> tuple[float, float, float, float, float, float, float]:
        metrics = _dict(row.get("fullWindowMetrics"))
        return (
            _num(row.get("validWindowCount")),
            -_num(row.get("majorWindowFailureCount")),
            -float(len(_list(row.get("blockers")))),
            _num(metrics.get("tradeCount")),
            _num(metrics.get("sharpe")),
            -_num(metrics.get("maxDrawdownPct"), default=999),
            _num(metrics.get("pnlUsd")),
        )

    return max(candidates, key=rank, default={})


def _next_focused_search_plan(ranked: list[dict[str, Any]], diagnostics: dict[str, Any]) -> dict[str, Any]:
    top_candidates = ranked[:8]
    high_yield = max(
        top_candidates,
        key=lambda row: float((row.get("fullWindowMetrics") or {}).get("pnlUsd") or 0.0),
        default={},
    )
    most_stable = max(
        top_candidates,
        key=lambda row: (
            int(row.get("validWindowCount") or 0),
            -int(row.get("majorWindowFailureCount") or 0),
            float((row.get("fullWindowMetrics") or {}).get("sharpe") or 0.0),
        ),
        default={},
    )
    stable_yield_converged = bool(
        most_stable
        and high_yield
        and _has_meaningful_tradeoff_identity(_tradeoff_summary(most_stable))
        and _has_meaningful_tradeoff_identity(_tradeoff_summary(high_yield))
        and _tradeoff_identity(_tradeoff_summary(most_stable)) == _tradeoff_identity(_tradeoff_summary(high_yield))
    )
    near_live_stability = _near_live_stability_candidate(
        top_candidates,
        most_stable_strategy_id=most_stable.get("strategyId"),
        high_yield_strategy_id=high_yield.get("strategyId"),
    )
    quality = _dict(diagnostics.get("balancedQualityRepair"))
    sample_rich = _dict(diagnostics.get("sampleRichQualityRepair"))
    density = _dict(diagnostics.get("balancedSampleDensityRepair"))
    yield_leader_confirmation = _dict(diagnostics.get("yieldLeaderConfirmation"))
    near_live_repair = _dict(diagnostics.get("nearLiveStabilityRepair"))
    near_live_followup = _dict(diagnostics.get("nearLiveStabilityFollowup"))
    near_live_refinement = _dict(diagnostics.get("nearLiveStabilityRefinement"))
    near_live_middle_window = _dict(diagnostics.get("nearLiveMiddleWindowFollowup"))
    near_live_signal_refinement = _dict(diagnostics.get("nearLiveSignalRefinement"))
    near_live_signal_refinement_followup = _dict(diagnostics.get("nearLiveSignalRefinementFollowup"))
    near_live_high_yield_neighborhood = _dict(diagnostics.get("nearLiveHighYieldNeighborhood"))
    near_live_high_yield_neighborhood_followup = _dict(
        diagnostics.get("nearLiveHighYieldNeighborhoodFollowup")
    )
    near_live_high_yield_neighborhood_followup_micro = _dict(
        diagnostics.get("nearLiveHighYieldNeighborhoodFollowupMicro")
    )
    near_live_high_yield_neighborhood_followup_micro_followup = _dict(
        diagnostics.get("nearLiveHighYieldNeighborhoodFollowupMicroFollowup")
    )
    near_live_cluster_refinement = _dict(diagnostics.get("nearLiveClusterRefinement"))
    near_live_tempo_refinement = _dict(diagnostics.get("nearLiveTempoRefinement"))
    near_live_stoploss_ladder = _dict(diagnostics.get("nearLiveStoplossLadderRefinement"))
    near_live_stoploss_ladder_followup = _dict(diagnostics.get("nearLiveStoplossLadderFollowup"))
    near_live_stoploss_ladder_followup_micro = _dict(
        diagnostics.get("nearLiveStoplossLadderFollowupMicro")
    )
    near_live_stoploss_ladder_followup_micro_followup = _dict(
        diagnostics.get("nearLiveStoplossLadderFollowupMicroFollowup")
    )
    near_live_middle_window_contender_micro = _dict(
        diagnostics.get("nearLiveMiddleWindowContenderMicro")
    )
    near_live_exit_refinement = _dict(diagnostics.get("nearLiveExitRefinement"))
    near_live_middle_tradeoff = _dict(diagnostics.get("nearLiveMiddleTradeoff"))
    near_live_middle_density = _dict(diagnostics.get("nearLiveMiddleDensityLift"))
    stable_middle_repair = _dict(diagnostics.get("stableMiddleThirdConfirmation"))
    stable_middle_followup = _dict(diagnostics.get("stableMiddleThirdFollowup"))
    stable_middle_followup_refinement = _dict(diagnostics.get("stableMiddleThirdFollowupRefinement"))
    stable_middle_followup_refinement_followup = _dict(diagnostics.get("stableMiddleThirdFollowupRefinementFollowup"))
    stable_middle_followup_refinement_micro = _dict(diagnostics.get("stableMiddleThirdFollowupRefinementMicro"))
    stable_middle_followup_refinement_micro_followup = _dict(
        diagnostics.get("stableMiddleThirdFollowupRefinementMicroFollowup")
    )
    stable_middle_weak_window = _dict(diagnostics.get("stableMiddleWeakWindowConfirmation"))
    stable_middle_bridge = _dict(diagnostics.get("stableMiddleWeakWindowBridge"))
    stable_middle_tradeoff = _dict(diagnostics.get("stableMiddleTradeoffFollowup"))
    quality_best = _dict(quality.get("bestByStabilityRank"))
    yield_leader_confirmation_best = _dict(yield_leader_confirmation.get("bestByStabilityRank"))
    near_live_repair_best = _dict(near_live_repair.get("bestByStabilityRank"))
    near_live_followup_best = _dict(near_live_followup.get("bestByStabilityRank"))
    near_live_refinement_best = _dict(near_live_refinement.get("bestByStabilityRank"))
    near_live_middle_window_best = _dict(near_live_middle_window.get("bestByStabilityRank"))
    near_live_signal_refinement_best = _dict(near_live_signal_refinement.get("bestByStabilityRank"))
    near_live_signal_refinement_followup_best = _dict(near_live_signal_refinement_followup.get("bestByStabilityRank"))
    near_live_high_yield_neighborhood_best = _dict(
        near_live_high_yield_neighborhood.get("bestByStabilityRank")
    )
    near_live_high_yield_neighborhood_followup_best = _dict(
        near_live_high_yield_neighborhood_followup.get("bestByStabilityRank")
    )
    near_live_high_yield_neighborhood_followup_micro_best = _dict(
        near_live_high_yield_neighborhood_followup_micro.get("bestByStabilityRank")
    )
    near_live_high_yield_neighborhood_followup_micro_followup_best = _dict(
        near_live_high_yield_neighborhood_followup_micro_followup.get("bestByStabilityRank")
    )
    near_live_cluster_refinement_best = _dict(near_live_cluster_refinement.get("bestByStabilityRank"))
    near_live_tempo_refinement_best = _dict(near_live_tempo_refinement.get("bestByStabilityRank"))
    near_live_stoploss_ladder_best = _dict(near_live_stoploss_ladder.get("bestByStabilityRank"))
    near_live_stoploss_ladder_followup_best = _dict(near_live_stoploss_ladder_followup.get("bestByStabilityRank"))
    near_live_stoploss_ladder_followup_micro_best = _dict(
        near_live_stoploss_ladder_followup_micro.get("bestByStabilityRank")
    )
    near_live_stoploss_ladder_followup_micro_followup_best = _dict(
        near_live_stoploss_ladder_followup_micro_followup.get("bestByStabilityRank")
    )
    near_live_middle_window_contender_micro_best = _dict(
        near_live_middle_window_contender_micro.get("bestByStabilityRank")
    )
    near_live_exit_refinement_best = _dict(near_live_exit_refinement.get("bestByStabilityRank"))
    near_live_middle_tradeoff_best = _dict(near_live_middle_tradeoff.get("bestByStabilityRank"))
    near_live_middle_density_best = _dict(near_live_middle_density.get("bestByStabilityRank"))
    stable_middle_repair_best = _dict(stable_middle_repair.get("bestByStabilityRank"))
    stable_middle_followup_best = _dict(stable_middle_followup.get("bestByStabilityRank"))
    stable_middle_followup_refinement_best = _dict(stable_middle_followup_refinement.get("bestByStabilityRank"))
    stable_middle_followup_refinement_followup_best = _dict(
        stable_middle_followup_refinement_followup.get("bestByStabilityRank")
    )
    stable_middle_followup_refinement_micro_best = _dict(
        stable_middle_followup_refinement_micro.get("bestByStabilityRank")
    )
    stable_middle_followup_refinement_micro_followup_best = _dict(
        stable_middle_followup_refinement_micro_followup.get("bestByStabilityRank")
    )
    stable_middle_weak_window_best = _dict(stable_middle_weak_window.get("bestByStabilityRank"))
    stable_middle_bridge_best = _dict(stable_middle_bridge.get("bestByStabilityRank"))
    stable_middle_tradeoff_best = _dict(stable_middle_tradeoff.get("bestByStabilityRank"))
    sample_rich_best = _dict(sample_rich.get("bestByStabilityRank"))
    density_best = _dict(density.get("bestByStabilityRank"))
    density_metrics = _dict(density_best.get("fullWindowMetrics"))
    quality_metrics = _dict(quality_best.get("fullWindowMetrics"))
    high_yield_metrics = _dict(high_yield.get("fullWindowMetrics"))
    yield_leader_confirmation_metrics = _dict(yield_leader_confirmation_best.get("fullWindowMetrics"))
    near_live_baseline_metrics = _dict(near_live_stability.get("fullWindowMetrics"))
    near_live_repair_metrics = _dict(near_live_repair_best.get("fullWindowMetrics"))
    near_live_followup_metrics = _dict(near_live_followup_best.get("fullWindowMetrics"))
    near_live_refinement_metrics = _dict(near_live_refinement_best.get("fullWindowMetrics"))
    near_live_middle_window_metrics = _dict(near_live_middle_window_best.get("fullWindowMetrics"))
    near_live_signal_refinement_metrics = _dict(near_live_signal_refinement_best.get("fullWindowMetrics"))
    near_live_signal_refinement_followup_metrics = _dict(near_live_signal_refinement_followup_best.get("fullWindowMetrics"))
    near_live_high_yield_neighborhood_metrics = _dict(
        near_live_high_yield_neighborhood_best.get("fullWindowMetrics")
    )
    near_live_high_yield_neighborhood_followup_metrics = _dict(
        near_live_high_yield_neighborhood_followup_best.get("fullWindowMetrics")
    )
    near_live_high_yield_neighborhood_followup_micro_metrics = _dict(
        near_live_high_yield_neighborhood_followup_micro_best.get("fullWindowMetrics")
    )
    near_live_high_yield_neighborhood_followup_micro_followup_metrics = _dict(
        near_live_high_yield_neighborhood_followup_micro_followup_best.get("fullWindowMetrics")
    )
    near_live_cluster_refinement_metrics = _dict(near_live_cluster_refinement_best.get("fullWindowMetrics"))
    near_live_tempo_refinement_metrics = _dict(near_live_tempo_refinement_best.get("fullWindowMetrics"))
    near_live_stoploss_ladder_metrics = _dict(near_live_stoploss_ladder_best.get("fullWindowMetrics"))
    near_live_stoploss_ladder_followup_metrics = _dict(near_live_stoploss_ladder_followup_best.get("fullWindowMetrics"))
    near_live_stoploss_ladder_followup_micro_metrics = _dict(
        near_live_stoploss_ladder_followup_micro_best.get("fullWindowMetrics")
    )
    near_live_stoploss_ladder_followup_micro_followup_metrics = _dict(
        near_live_stoploss_ladder_followup_micro_followup_best.get("fullWindowMetrics")
    )
    near_live_middle_window_contender_micro_metrics = _dict(
        near_live_middle_window_contender_micro_best.get("fullWindowMetrics")
    )
    near_live_exit_refinement_metrics = _dict(near_live_exit_refinement_best.get("fullWindowMetrics"))
    near_live_middle_tradeoff_metrics = _dict(near_live_middle_tradeoff_best.get("fullWindowMetrics"))
    near_live_middle_density_metrics = _dict(near_live_middle_density_best.get("fullWindowMetrics"))
    stable_baseline_metrics = _dict(most_stable.get("fullWindowMetrics"))
    stable_middle_repair_metrics = _dict(stable_middle_repair_best.get("fullWindowMetrics"))
    stable_middle_followup_metrics = _dict(stable_middle_followup_best.get("fullWindowMetrics"))
    stable_middle_followup_refinement_metrics = _dict(stable_middle_followup_refinement_best.get("fullWindowMetrics"))
    stable_middle_followup_refinement_followup_metrics = _dict(
        stable_middle_followup_refinement_followup_best.get("fullWindowMetrics")
    )
    stable_middle_followup_refinement_micro_metrics = _dict(
        stable_middle_followup_refinement_micro_best.get("fullWindowMetrics")
    )
    stable_middle_followup_refinement_micro_followup_metrics = _dict(
        stable_middle_followup_refinement_micro_followup_best.get("fullWindowMetrics")
    )
    stable_middle_weak_window_metrics = _dict(stable_middle_weak_window_best.get("fullWindowMetrics"))
    stable_middle_bridge_metrics = _dict(stable_middle_bridge_best.get("fullWindowMetrics"))
    stable_middle_tradeoff_metrics = _dict(stable_middle_tradeoff_best.get("fullWindowMetrics"))

    recommendations: list[dict[str, Any]] = []
    near_live_first = bool(near_live_stability)
    high_yield_priority = 2 if near_live_first else 1
    near_live_priority = 1 if near_live_first else 2
    yield_leader_confirmation_improves_baseline = bool(
        high_yield
        and yield_leader_confirmation_best
        and yield_leader_confirmation_best.get("strategyId")
        and (
            _num(yield_leader_confirmation_best.get("validWindowCount")) > _num(high_yield.get("validWindowCount"))
            or (
                _num(yield_leader_confirmation_best.get("validWindowCount")) == _num(high_yield.get("validWindowCount"))
                and _num(yield_leader_confirmation_metrics.get("sharpe")) > _num(high_yield_metrics.get("sharpe"))
            )
            or (
                _num(yield_leader_confirmation_best.get("validWindowCount")) == _num(high_yield.get("validWindowCount"))
                and _num(yield_leader_confirmation_metrics.get("sharpe")) == _num(high_yield_metrics.get("sharpe"))
                and _num(yield_leader_confirmation_metrics.get("pnlUsd")) > _num(high_yield_metrics.get("pnlUsd"))
            )
        )
    )
    yield_leader_confirmation_outcome_zh = (
        "yield leader 局部确认已找到比当前高收益 leader 更稳的高收益变体；下一轮优先围绕修复版复验。"
        if yield_leader_confirmation_improves_baseline
        else "yield leader 局部确认暂未推翻当前高收益 leader；继续把它作为高收益参考。"
    )
    most_stable_middle_window = _window_summary_entry(most_stable, "middle_third")
    near_live_high_yield_neighborhood_window = _window_summary_entry(
        near_live_high_yield_neighborhood_best, "middle_third"
    )
    near_live_high_yield_neighborhood_followup_window = _window_summary_entry(
        near_live_high_yield_neighborhood_followup_best, "middle_third"
    )
    near_live_high_yield_neighborhood_followup_micro_window = _window_summary_entry(
        near_live_high_yield_neighborhood_followup_micro_best, "middle_third"
    )
    near_live_high_yield_neighborhood_followup_micro_followup_window = _window_summary_entry(
        near_live_high_yield_neighborhood_followup_micro_followup_best, "middle_third"
    )
    near_live_high_yield_neighborhood_improves_anchor = bool(
        stable_yield_converged
        and most_stable
        and near_live_high_yield_neighborhood_best
        and near_live_high_yield_neighborhood_best.get("strategyId")
        and near_live_high_yield_neighborhood_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_high_yield_neighborhood_best.get("validWindowCount")) >= _num(most_stable.get("validWindowCount"))
        and (
            _num(near_live_high_yield_neighborhood_metrics.get("sharpe")) > _num(near_live_baseline_metrics.get("sharpe"))
            or (
                _num(near_live_high_yield_neighborhood_metrics.get("sharpe")) == _num(near_live_baseline_metrics.get("sharpe"))
                and _num(near_live_high_yield_neighborhood_metrics.get("pnlUsd")) > _num(near_live_baseline_metrics.get("pnlUsd"))
            )
            or (
                _num(near_live_high_yield_neighborhood_metrics.get("sharpe")) >= _num(near_live_baseline_metrics.get("sharpe"))
                and len(_list(near_live_high_yield_neighborhood_window.get("blockers")))
                < len(_list(most_stable_middle_window.get("blockers")))
            )
            or (
                len(_list(near_live_high_yield_neighborhood_window.get("blockers")))
                == len(_list(most_stable_middle_window.get("blockers")))
                and _num(near_live_high_yield_neighborhood_window.get("sharpe"))
                > _num(most_stable_middle_window.get("sharpe"))
                and _num(near_live_high_yield_neighborhood_window.get("tradeCount"))
                >= _num(most_stable_middle_window.get("tradeCount"))
                and _num(near_live_high_yield_neighborhood_metrics.get("pnlUsd")) >= _num(near_live_baseline_metrics.get("pnlUsd"))
            )
        )
    )
    near_live_high_yield_neighborhood_outcome_zh = (
        "quality-first high-yield neighborhood 已在不替换收敛主簇的前提下找到更强的局部 leader；下一轮优先围绕这个 near-live leader 继续局部确认。"
        if near_live_high_yield_neighborhood_improves_anchor
        else (
            "quality-first high-yield neighborhood 细化了当前 near-live leader 的 TP/SL 邻域，但还没推翻现任收敛锚点。"
            if stable_yield_converged
            else "quality-first high-yield neighborhood 目前只作为补充观测，不改变当前高收益 leader。"
        )
    )
    near_live_high_yield_neighborhood_followup_improves_neighborhood = bool(
        stable_yield_converged
        and near_live_high_yield_neighborhood_best
        and near_live_high_yield_neighborhood_followup_best
        and near_live_high_yield_neighborhood_followup_best.get("strategyId")
        and near_live_high_yield_neighborhood_followup_best.get("strategyId") != near_live_high_yield_neighborhood_best.get("strategyId")
        and near_live_high_yield_neighborhood_followup_best.get("strategyId") != most_stable.get("strategyId")
        and (
            _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
            > _num(near_live_high_yield_neighborhood_best.get("validWindowCount"))
            or (
                _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_best.get("validWindowCount"))
                and _num(near_live_high_yield_neighborhood_followup_metrics.get("sharpe"))
                > _num(near_live_high_yield_neighborhood_metrics.get("sharpe"))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_best.get("validWindowCount"))
                and _num(near_live_high_yield_neighborhood_followup_metrics.get("sharpe"))
                == _num(near_live_high_yield_neighborhood_metrics.get("sharpe"))
                and _num(near_live_high_yield_neighborhood_followup_metrics.get("pnlUsd"))
                > _num(near_live_high_yield_neighborhood_metrics.get("pnlUsd"))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_best.get("validWindowCount"))
                and len(_list(near_live_high_yield_neighborhood_followup_window.get("blockers")))
                < len(_list(near_live_high_yield_neighborhood_window.get("blockers")))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_best.get("validWindowCount"))
                and len(_list(near_live_high_yield_neighborhood_followup_window.get("blockers")))
                == len(_list(near_live_high_yield_neighborhood_window.get("blockers")))
                and _num(near_live_high_yield_neighborhood_followup_window.get("sharpe"))
                > _num(near_live_high_yield_neighborhood_window.get("sharpe"))
                and _num(near_live_high_yield_neighborhood_followup_window.get("tradeCount"))
                >= _num(near_live_high_yield_neighborhood_window.get("tradeCount"))
                and _num(near_live_high_yield_neighborhood_followup_metrics.get("pnlUsd"))
                >= _num(near_live_high_yield_neighborhood_metrics.get("pnlUsd"))
            )
        )
    )
    near_live_high_yield_neighborhood_followup_outcome_zh = (
        "quality-first high-yield neighborhood follow-up 已在不替换收敛主簇的前提下找到更强的局部 leader；下一轮优先围绕更窄的 near-live 邻域继续局部确认。"
        if near_live_high_yield_neighborhood_followup_improves_neighborhood
        else (
            "quality-first high-yield neighborhood follow-up 细化了当前 312.5 high-yield 邻域，但还没推翻现任局部 leader。"
            if stable_yield_converged
            else "quality-first high-yield neighborhood follow-up 目前只作为补充观测，不改变当前高收益 leader。"
        )
    )
    near_live_high_yield_neighborhood_followup_micro_improves_followup = bool(
        stable_yield_converged
        and near_live_high_yield_neighborhood_followup_best
        and near_live_high_yield_neighborhood_followup_micro_best
        and near_live_high_yield_neighborhood_followup_micro_best.get("strategyId")
        and near_live_high_yield_neighborhood_followup_micro_best.get("strategyId")
        != near_live_high_yield_neighborhood_followup_best.get("strategyId")
        and near_live_high_yield_neighborhood_followup_micro_best.get("strategyId") != most_stable.get("strategyId")
        and (
            _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
            > _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
            or (
                _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
                and _num(near_live_high_yield_neighborhood_followup_micro_metrics.get("sharpe"))
                > _num(near_live_high_yield_neighborhood_followup_metrics.get("sharpe"))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
                and _num(near_live_high_yield_neighborhood_followup_micro_metrics.get("sharpe"))
                == _num(near_live_high_yield_neighborhood_followup_metrics.get("sharpe"))
                and _num(near_live_high_yield_neighborhood_followup_micro_metrics.get("pnlUsd"))
                > _num(near_live_high_yield_neighborhood_followup_metrics.get("pnlUsd"))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
                and len(_list(near_live_high_yield_neighborhood_followup_micro_window.get("blockers")))
                < len(_list(near_live_high_yield_neighborhood_followup_window.get("blockers")))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_followup_best.get("validWindowCount"))
                and len(_list(near_live_high_yield_neighborhood_followup_micro_window.get("blockers")))
                == len(_list(near_live_high_yield_neighborhood_followup_window.get("blockers")))
                and _num(near_live_high_yield_neighborhood_followup_micro_window.get("sharpe"))
                > _num(near_live_high_yield_neighborhood_followup_window.get("sharpe"))
                and _num(near_live_high_yield_neighborhood_followup_micro_window.get("tradeCount"))
                >= _num(near_live_high_yield_neighborhood_followup_window.get("tradeCount"))
                and _num(near_live_high_yield_neighborhood_followup_micro_metrics.get("pnlUsd"))
                >= _num(near_live_high_yield_neighborhood_followup_metrics.get("pnlUsd"))
            )
        )
    )
    near_live_high_yield_neighborhood_followup_micro_outcome_zh = (
        "quality-first high-yield neighborhood follow-up micro 已在不替换收敛主簇的前提下找到更强的 ultra-local leader；下一轮优先围绕更窄的微阶梯继续确认。"
        if near_live_high_yield_neighborhood_followup_micro_improves_followup
        else (
            "quality-first high-yield neighborhood follow-up micro 细化了当前 follow-up winner 的 ultra-local TP/SL 口袋，但还没推翻现任局部 leader。"
            if stable_yield_converged
            else "quality-first high-yield neighborhood follow-up micro 目前只作为补充观测，不改变当前高收益 leader。"
        )
    )
    near_live_high_yield_neighborhood_followup_micro_followup_improves_micro = bool(
        stable_yield_converged
        and near_live_high_yield_neighborhood_followup_micro_best
        and near_live_high_yield_neighborhood_followup_micro_followup_best
        and near_live_high_yield_neighborhood_followup_micro_followup_best.get("strategyId")
        and near_live_high_yield_neighborhood_followup_micro_followup_best.get("strategyId")
        != near_live_high_yield_neighborhood_followup_micro_best.get("strategyId")
        and near_live_high_yield_neighborhood_followup_micro_followup_best.get("strategyId")
        != most_stable.get("strategyId")
        and (
            _num(near_live_high_yield_neighborhood_followup_micro_followup_best.get("validWindowCount"))
            > _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
            or (
                _num(near_live_high_yield_neighborhood_followup_micro_followup_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
                and _num(near_live_high_yield_neighborhood_followup_micro_followup_metrics.get("sharpe"))
                > _num(near_live_high_yield_neighborhood_followup_micro_metrics.get("sharpe"))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_micro_followup_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
                and _num(near_live_high_yield_neighborhood_followup_micro_followup_metrics.get("sharpe"))
                == _num(near_live_high_yield_neighborhood_followup_micro_metrics.get("sharpe"))
                and _num(near_live_high_yield_neighborhood_followup_micro_followup_metrics.get("pnlUsd"))
                > _num(near_live_high_yield_neighborhood_followup_micro_metrics.get("pnlUsd"))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_micro_followup_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
                and len(_list(near_live_high_yield_neighborhood_followup_micro_followup_window.get("blockers")))
                < len(_list(near_live_high_yield_neighborhood_followup_micro_window.get("blockers")))
            )
            or (
                _num(near_live_high_yield_neighborhood_followup_micro_followup_best.get("validWindowCount"))
                == _num(near_live_high_yield_neighborhood_followup_micro_best.get("validWindowCount"))
                and len(_list(near_live_high_yield_neighborhood_followup_micro_followup_window.get("blockers")))
                == len(_list(near_live_high_yield_neighborhood_followup_micro_window.get("blockers")))
                and _num(near_live_high_yield_neighborhood_followup_micro_followup_window.get("sharpe"))
                > _num(near_live_high_yield_neighborhood_followup_micro_window.get("sharpe"))
                and _num(near_live_high_yield_neighborhood_followup_micro_followup_window.get("tradeCount"))
                >= _num(near_live_high_yield_neighborhood_followup_micro_window.get("tradeCount"))
                and _num(near_live_high_yield_neighborhood_followup_micro_followup_metrics.get("pnlUsd"))
                >= _num(near_live_high_yield_neighborhood_followup_micro_metrics.get("pnlUsd"))
            )
        )
    )
    near_live_high_yield_neighborhood_followup_micro_followup_outcome_zh = (
        "quality-first high-yield neighborhood follow-up micro follow-up 已在不替换收敛主簇的前提下找到更强的 318.75 ultra-local leader；下一轮优先围绕更窄的 318.75 微阶梯继续确认。"
        if near_live_high_yield_neighborhood_followup_micro_followup_improves_micro
        else (
            "quality-first high-yield neighborhood follow-up micro follow-up 细化了当前 318.75 same-cluster TP/SL 口袋，但还没推翻现任局部 leader。"
            if stable_yield_converged
            else "quality-first high-yield neighborhood follow-up micro follow-up 目前只作为补充观测，不改变当前高收益 leader。"
        )
    )
    if high_yield:
        frontier_strategy_id = high_yield.get("strategyId")
        quality_strategy_id = quality_best.get("strategyId")
        yield_confirmation_strategy_id = yield_leader_confirmation_best.get("strategyId")
        near_live_high_yield_neighborhood_strategy_id = near_live_high_yield_neighborhood_best.get("strategyId")
        near_live_high_yield_neighborhood_followup_strategy_id = (
            near_live_high_yield_neighborhood_followup_best.get("strategyId")
        )
        near_live_high_yield_neighborhood_followup_micro_strategy_id = (
            near_live_high_yield_neighborhood_followup_micro_best.get("strategyId")
        )
        near_live_high_yield_neighborhood_followup_micro_followup_strategy_id = (
            near_live_high_yield_neighborhood_followup_micro_followup_best.get("strategyId")
        )
        frontier_differs_from_quality = bool(
            frontier_strategy_id and quality_strategy_id and frontier_strategy_id != quality_strategy_id
        )
        high_yield_basis_strategy_id = (
            near_live_high_yield_neighborhood_followup_micro_followup_strategy_id
            if stable_yield_converged
            and near_live_high_yield_neighborhood_followup_micro_followup_improves_micro
            and near_live_high_yield_neighborhood_followup_micro_followup_strategy_id
            else (
            near_live_high_yield_neighborhood_followup_micro_strategy_id
            if stable_yield_converged
            and near_live_high_yield_neighborhood_followup_micro_improves_followup
            and near_live_high_yield_neighborhood_followup_micro_strategy_id
            else (
            near_live_high_yield_neighborhood_followup_strategy_id
            if stable_yield_converged
            and near_live_high_yield_neighborhood_followup_improves_neighborhood
            and near_live_high_yield_neighborhood_followup_strategy_id
            else (
            near_live_high_yield_neighborhood_strategy_id
            if stable_yield_converged
            and near_live_high_yield_neighborhood_improves_anchor
            and near_live_high_yield_neighborhood_strategy_id
            else (
            yield_confirmation_strategy_id
            if yield_leader_confirmation_improves_baseline and yield_confirmation_strategy_id
            else frontier_strategy_id
            )
            )
            )
            )
        )
        high_yield_converged_to_near_live = bool(
            stable_yield_converged
            and high_yield_basis_strategy_id
            and str(high_yield_basis_strategy_id).startswith("hfm_crypto_btc_near_live_")
        )
        high_yield_baseline_strategy_id = (
            most_stable.get("strategyId")
            if stable_yield_converged
            and near_live_high_yield_neighborhood_improves_anchor
            and high_yield_basis_strategy_id != most_stable.get("strategyId")
            else (
            frontier_strategy_id
            if yield_leader_confirmation_improves_baseline and high_yield_basis_strategy_id != frontier_strategy_id
            else (quality_strategy_id if frontier_differs_from_quality else None)
            )
        )
        recommendations.append({
            "id": "quality_first_high_yield_neighborhood",
            "label": "quality_first_high_yield_neighborhood",
            "priority": high_yield_priority,
            "basisStrategyId": high_yield_basis_strategy_id,
            "baselineStrategyId": high_yield_baseline_strategy_id,
            "reasonZh": (
                "quality-first high-yield neighborhood follow-up micro follow-up 已在不替换收敛主簇的前提下找到更强的 318.75 ultra-local leader；下一轮围绕更新后的 318.75 微阶梯继续确认，并保留当前锚点做对照。"
                if stable_yield_converged and near_live_high_yield_neighborhood_followup_micro_followup_improves_micro
                else (
                "quality-first high-yield neighborhood follow-up micro 已在不替换收敛主簇的前提下找到更强的 ultra-local leader；下一轮围绕更窄的微阶梯继续确认，并保留当前锚点做对照。"
                if stable_yield_converged and near_live_high_yield_neighborhood_followup_micro_improves_followup
                else (
                "quality-first high-yield neighborhood follow-up 已在不替换收敛主簇的前提下找到更强的局部 leader；下一轮围绕更窄的 near-live 邻域微调，并保留当前锚点做对照。"
                if stable_yield_converged and near_live_high_yield_neighborhood_followup_improves_neighborhood
                else (
                "quality-first high-yield neighborhood 已在不替换收敛主簇的前提下找到更强的局部 leader；下一轮围绕这个 near-live leader 微调，并保留当前锚点做对照。"
                if stable_yield_converged and near_live_high_yield_neighborhood_improves_anchor
                else (
                "yield leader 局部确认已找到更稳的高收益变体；下一轮围绕修复版做局部复验，并保留当前高收益 leader 做对照。"
                if yield_leader_confirmation_improves_baseline
                else (
                "当前高收益 leader 已收敛到 near-live 主锚点；下一轮围绕同簇 TP/SL/hold/cooldown 微调做局部确认，同时保留旧 baseline 做对照。"
                if high_yield_converged_to_near_live
                else (
                "当前高收益领先簇已偏离旧 quality-first baseline；下一轮围绕当前收益 leader 做局部确认，同时保留旧 baseline 做对照。"
                if frontier_differs_from_quality
                else "高收益慢频候选的全窗口 Sharpe 更强，但分段样本数不足；下一轮围绕它补窗口样本，不直接实盘。"
                )
                )
                )
                )
                )
                )
            ),
            "parameterFocus": (
                [
                    "preserve_short_bias_signal_kernel",
                    "keep_take_profit_446_875_to_456_25",
                    "keep_stop_loss_315_625_to_320_3125",
                    "nudge_max_hold_8_to_9",
                    "nudge_cooldown_4_to_5",
                ]
                if stable_yield_converged and near_live_high_yield_neighborhood_followup_micro_followup_improves_micro
                else (
                [
                    "preserve_short_bias_signal_kernel",
                    "keep_take_profit_446_875_to_456_25",
                    "keep_stop_loss_307_8125_to_312_5",
                    "nudge_max_hold_8_to_9",
                    "nudge_cooldown_4_to_5",
                ]
                if stable_yield_converged and near_live_high_yield_neighborhood_followup_micro_improves_followup
                else (
                [
                    "preserve_short_bias_signal_kernel",
                    "keep_take_profit_443_75_to_462_5",
                    "keep_stop_loss_306_25_to_315_625",
                    "nudge_max_hold_8_to_9",
                    "nudge_cooldown_4_to_5",
                ]
                if stable_yield_converged and near_live_high_yield_neighborhood_followup_improves_neighborhood
                else (
                [
                    "preserve_short_bias_signal_kernel",
                    "keep_take_profit_437_5_to_475",
                    "keep_stop_loss_300_to_325",
                    "nudge_max_hold_8_to_9",
                    "nudge_cooldown_4_to_5",
                ]
                if stable_yield_converged and near_live_high_yield_neighborhood_improves_anchor
                else (
                [
                    "keep_take_profit_600_to_900",
                    "keep_stop_loss_350_to_500",
                    "nudge_max_hold_24_to_48",
                    "nudge_cooldown_4_to_10",
                ]
                if yield_leader_confirmation_improves_baseline
                else (
                [
                    "preserve_short_bias_signal_kernel",
                    "keep_take_profit_425_to_475",
                    "keep_stop_loss_300_to_325",
                    "nudge_max_hold_8_to_9",
                    "nudge_cooldown_4_to_5",
                ]
                if high_yield_converged_to_near_live
                else (
                [
                    "keep_take_profit_450_to_600",
                    "keep_stop_loss_500_to_600",
                    "nudge_max_hold_24_to_48",
                    "nudge_cooldown_8_to_12",
                ]
                if frontier_differs_from_quality
                else [
                    "keep_take_profit_600_to_900",
                    "keep_stop_loss_350_to_450",
                    "nudge_max_hold_24_to_48",
                    "nudge_cooldown_4_to_8",
                ]
                )
                )
                )
                )
                )
                )
            ),
        })
    near_live_repair_improves_baseline = bool(
        near_live_stability
        and near_live_repair_best
        and near_live_repair_best.get("strategyId")
        and (
            _num(near_live_repair_best.get("validWindowCount")) > _num(near_live_stability.get("validWindowCount"))
            or (
                _num(near_live_repair_best.get("validWindowCount")) == _num(near_live_stability.get("validWindowCount"))
                and _num(near_live_repair_metrics.get("sharpe")) > _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_repair_outcome_zh = (
        "near-live stability 局部搜索已找到比当前 sample-balanced challenger 更强的第二候选；下一轮优先围绕修复版做复验。"
        if near_live_repair_improves_baseline and not stable_yield_converged
        else (
            "near-live stability 局部搜索属于旧第二候选修复线；当前主线已收敛到 next distinct contender，继续保留现任 contender。"
            if stable_yield_converged
            else "near-live stability 局部搜索（含 sample-balanced / sample-rich bridge 邻域）暂未推翻当前 sample-balanced challenger；继续把它作为第二候选。"
        )
    )
    near_live_followup_improves_repair = bool(
        near_live_repair_best
        and near_live_followup_best
        and near_live_followup_best.get("strategyId")
        and (
            _num(near_live_followup_best.get("validWindowCount")) > _num(near_live_repair_best.get("validWindowCount"))
            or (
                _num(near_live_followup_best.get("validWindowCount")) == _num(near_live_repair_best.get("validWindowCount"))
                and _num(near_live_followup_metrics.get("sharpe")) > _num(near_live_repair_metrics.get("sharpe"))
                and _num(near_live_followup_metrics.get("tradeCount")) >= _num(near_live_repair_metrics.get("tradeCount"))
            )
        )
    )
    near_live_followup_outcome_zh = (
        "near-live stability follow-up 已找到比当前修复版更强的第二候选；下一轮优先围绕 follow-up 版本继续复验。"
        if near_live_followup_improves_repair and not stable_yield_converged
        else (
            "near-live stability follow-up 确实优于旧 repair 线，但当前主线已收敛到 next distinct contender；保留为 lineage 证据，不再当当前第二候选。"
            if stable_yield_converged
            else (
                "near-live stability follow-up 保住了修复版的稳定形状，但还没推翻当前 near-live repair winner；继续把现任修复版作为第二候选。"
                if near_live_repair_improves_baseline
                else "near-live stability follow-up 暂无必要提升优先级；先保持当前 near-live baseline。"
            )
        )
    )
    near_live_refinement_improves_followup = bool(
        near_live_followup_best
        and near_live_refinement_best
        and near_live_refinement_best.get("strategyId")
        and (
            _num(near_live_refinement_best.get("validWindowCount")) > _num(near_live_followup_best.get("validWindowCount"))
            or (
                _num(near_live_refinement_best.get("validWindowCount")) == _num(near_live_followup_best.get("validWindowCount"))
                and _num(near_live_refinement_metrics.get("sharpe")) > _num(near_live_followup_metrics.get("sharpe"))
                and _num(near_live_refinement_metrics.get("tradeCount")) >= _num(near_live_followup_metrics.get("tradeCount"))
            )
        )
    )
    near_live_refinement_outcome_zh = (
        "near-live stability refinement 已找到比当前 follow-up winner 更强的第二候选；下一轮优先围绕 refinement 版本继续复验。"
        if near_live_refinement_improves_followup and not stable_yield_converged
        else (
            "near-live stability refinement 细化了旧 follow-up 路径，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else (
                "near-live stability refinement 保住了 follow-up 的稳定形状，但还没推翻当前 near-live follow-up winner；继续把现任 follow-up 作为第二候选。"
                if near_live_followup_improves_repair
                else (
                    "near-live stability refinement 暂未推翻当前 near-live repair winner；先保持现任修复版/后继版。"
                    if near_live_repair_improves_baseline
                    else "near-live stability refinement 暂无必要提升优先级；先保持当前 near-live baseline。"
                )
            )
        )
    )
    near_live_followup_window = _window_summary_entry(near_live_followup_best, "middle_third")
    near_live_middle_window_row = _window_summary_entry(near_live_middle_window_best, "middle_third")
    near_live_middle_window_improves_followup = bool(
        near_live_followup_best
        and near_live_middle_window_best
        and near_live_middle_window_best.get("strategyId")
        and _num(near_live_middle_window_best.get("validWindowCount")) >= _num(near_live_followup_best.get("validWindowCount"))
        and (
            len(_list(near_live_middle_window_row.get("blockers"))) < len(_list(near_live_followup_window.get("blockers")))
            or (
                len(_list(near_live_middle_window_row.get("blockers"))) == len(_list(near_live_followup_window.get("blockers")))
                and _num(near_live_middle_window_row.get("sharpe")) > _num(near_live_followup_window.get("sharpe"))
                and _num(near_live_middle_window_row.get("tradeCount")) >= _num(near_live_followup_window.get("tradeCount"))
            )
        )
    )
    near_live_middle_window_outcome_zh = (
        "near-live middle-window follow-up 已在保住当前有效窗口数的前提下改善 middle_third；下一轮优先围绕 middle-window 版本复验。"
        if near_live_middle_window_improves_followup and not stable_yield_converged
        else (
            "near-live middle-window follow-up 细化了收敛簇的 weak-window 形状，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else (
                "near-live middle-window follow-up 提高了局部 middle_third 读数，但还没在不牺牲整体稳定性的前提下推翻当前 follow-up winner；继续把现任 follow-up 作为第二候选。"
                if near_live_followup_improves_repair
                else "near-live middle-window follow-up 暂无必要提升优先级；先保持当前 near-live baseline。"
            )
        )
    )
    near_live_cluster_refinement_window = _window_summary_entry(near_live_cluster_refinement_best, "middle_third")
    near_live_stability_window = _window_summary_entry(near_live_stability, "middle_third")
    near_live_signal_refinement_window = _window_summary_entry(near_live_signal_refinement_best, "middle_third")
    near_live_signal_refinement_followup_window = _window_summary_entry(
        near_live_signal_refinement_followup_best, "middle_third"
    )
    near_live_signal_refinement_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_signal_refinement_best
        and near_live_signal_refinement_best.get("strategyId")
        and near_live_signal_refinement_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_signal_refinement_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_signal_refinement_best.get("validWindowCount")) >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_signal_refinement_window.get("blockers"))) < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_signal_refinement_window.get("blockers"))) == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_signal_refinement_window.get("sharpe")) > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_signal_refinement_window.get("tradeCount")) >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_signal_refinement_metrics.get("sharpe")) >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_signal_refinement_followup_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_signal_refinement_followup_best
        and near_live_signal_refinement_followup_best.get("strategyId")
        and near_live_signal_refinement_followup_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_signal_refinement_followup_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_signal_refinement_followup_best.get("validWindowCount")) >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_signal_refinement_followup_window.get("blockers"))) < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_signal_refinement_followup_window.get("blockers"))) == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_signal_refinement_followup_window.get("sharpe")) > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_signal_refinement_followup_window.get("tradeCount")) >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_signal_refinement_followup_metrics.get("sharpe")) >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_signal_refinement_outcome_zh = (
        "near-live signal refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 signal-kernel 版本做 near-live 复验。"
        if near_live_signal_refinement_improves_contender
        else (
            "near-live signal refinement 细化了收敛簇的 EMA/slope 信号核，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else "near-live signal refinement 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_signal_refinement_followup_outcome_zh = (
        "near-live signal refinement follow-up 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 signal-kernel 微阶梯版本做 near-live 复验。"
        if near_live_signal_refinement_followup_improves_contender
        else (
            "near-live signal refinement follow-up 细化了当前 signal-kernel winner 的局部邻域，但还没推翻当前 next distinct contender。"
            if stable_yield_converged
            else "near-live signal refinement follow-up 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_cluster_refinement_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_cluster_refinement_best
        and near_live_cluster_refinement_best.get("strategyId")
        and near_live_cluster_refinement_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_cluster_refinement_best.get("strategyId") != most_stable.get("strategyId")
        and (
            _num(near_live_cluster_refinement_best.get("validWindowCount")) > _num(near_live_stability.get("validWindowCount"))
            or (
                _num(near_live_cluster_refinement_best.get("validWindowCount")) == _num(near_live_stability.get("validWindowCount"))
                and _num(near_live_cluster_refinement_metrics.get("sharpe")) > _num(near_live_baseline_metrics.get("sharpe"))
            )
            or (
                _num(near_live_cluster_refinement_best.get("validWindowCount")) == _num(near_live_stability.get("validWindowCount"))
                and _num(near_live_cluster_refinement_metrics.get("sharpe")) == _num(near_live_baseline_metrics.get("sharpe"))
                and _num(near_live_cluster_refinement_metrics.get("pnlUsd")) > _num(near_live_baseline_metrics.get("pnlUsd"))
            )
            or (
                _num(near_live_cluster_refinement_best.get("validWindowCount")) == _num(near_live_stability.get("validWindowCount"))
                and _num(near_live_cluster_refinement_metrics.get("sharpe")) == _num(near_live_baseline_metrics.get("sharpe"))
                and _num(near_live_cluster_refinement_metrics.get("pnlUsd")) == _num(near_live_baseline_metrics.get("pnlUsd"))
                and (
                    len(_list(near_live_cluster_refinement_window.get("blockers"))) < len(_list(near_live_stability_window.get("blockers")))
                    or (
                        len(_list(near_live_cluster_refinement_window.get("blockers"))) == len(_list(near_live_stability_window.get("blockers")))
                        and _num(near_live_cluster_refinement_window.get("sharpe")) > _num(near_live_stability_window.get("sharpe"))
                        and _num(near_live_cluster_refinement_window.get("tradeCount")) >= _num(near_live_stability_window.get("tradeCount"))
                    )
                )
            )
        )
    )
    near_live_cluster_refinement_outcome_zh = (
        "near-live converged-cluster refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕该变体继续 near-live 复验。"
        if near_live_cluster_refinement_improves_contender
        else (
            "near-live converged-cluster refinement 细化了 0003/0021/0040 的 stop-loss 梯度，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else "near-live converged-cluster refinement 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_tempo_refinement_window = _window_summary_entry(near_live_tempo_refinement_best, "middle_third")
    near_live_tempo_refinement_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_tempo_refinement_best
        and near_live_tempo_refinement_best.get("strategyId")
        and near_live_tempo_refinement_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_tempo_refinement_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_tempo_refinement_best.get("validWindowCount")) >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_tempo_refinement_window.get("blockers"))) < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_tempo_refinement_window.get("blockers"))) == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_tempo_refinement_window.get("sharpe")) > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_tempo_refinement_window.get("tradeCount")) >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_tempo_refinement_metrics.get("sharpe")) >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_tempo_refinement_outcome_zh = (
        "near-live tempo refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 hold/cooldown 版本做 near-live 复验。"
        if near_live_tempo_refinement_improves_contender
        else (
            "near-live tempo refinement 细化了收敛簇的 hold/cooldown 节奏，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else "near-live tempo refinement 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_stoploss_ladder_window = _window_summary_entry(near_live_stoploss_ladder_best, "middle_third")
    near_live_stoploss_ladder_followup_window = _window_summary_entry(
        near_live_stoploss_ladder_followup_best, "middle_third"
    )
    near_live_stoploss_ladder_followup_micro_window = _window_summary_entry(
        near_live_stoploss_ladder_followup_micro_best, "middle_third"
    )
    near_live_stoploss_ladder_followup_micro_followup_window = _window_summary_entry(
        near_live_stoploss_ladder_followup_micro_followup_best, "middle_third"
    )
    near_live_middle_window_contender_micro_window = _window_summary_entry(
        near_live_middle_window_contender_micro_best, "middle_third"
    )
    near_live_stoploss_ladder_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_stoploss_ladder_best
        and near_live_stoploss_ladder_best.get("strategyId")
        and near_live_stoploss_ladder_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_stoploss_ladder_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_stoploss_ladder_best.get("validWindowCount")) >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_stoploss_ladder_window.get("blockers"))) < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_stoploss_ladder_window.get("blockers"))) == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_stoploss_ladder_window.get("sharpe")) > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_stoploss_ladder_window.get("tradeCount")) >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_stoploss_ladder_metrics.get("sharpe")) >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_stoploss_ladder_outcome_zh = (
        "near-live stop-loss ladder refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 stop-loss ladder 版本做 near-live 复验。"
        if near_live_stoploss_ladder_improves_contender
        else (
            "near-live stop-loss ladder refinement 细化了收敛簇的 stop-loss 梯度，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else "near-live stop-loss ladder refinement 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_stoploss_ladder_followup_improves_refinement = bool(
        stable_yield_converged
        and near_live_stoploss_ladder_best
        and near_live_stoploss_ladder_followup_best
        and near_live_stoploss_ladder_followup_best.get("strategyId")
        and near_live_stoploss_ladder_followup_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_stoploss_ladder_followup_best.get("strategyId") != most_stable.get("strategyId")
        and (
            _num(near_live_stoploss_ladder_followup_best.get("validWindowCount"))
            > _num(near_live_stoploss_ladder_best.get("validWindowCount"))
            or (
                _num(near_live_stoploss_ladder_followup_best.get("validWindowCount"))
                == _num(near_live_stoploss_ladder_best.get("validWindowCount"))
                and len(_list(near_live_stoploss_ladder_followup_window.get("blockers")))
                < len(_list(near_live_stoploss_ladder_window.get("blockers")))
            )
            or (
                _num(near_live_stoploss_ladder_followup_best.get("validWindowCount"))
                == _num(near_live_stoploss_ladder_best.get("validWindowCount"))
                and len(_list(near_live_stoploss_ladder_followup_window.get("blockers")))
                == len(_list(near_live_stoploss_ladder_window.get("blockers")))
                and _num(near_live_stoploss_ladder_followup_window.get("sharpe"))
                > _num(near_live_stoploss_ladder_window.get("sharpe"))
                and _num(near_live_stoploss_ladder_followup_window.get("tradeCount"))
                >= _num(near_live_stoploss_ladder_window.get("tradeCount"))
                and _num(near_live_stoploss_ladder_followup_metrics.get("sharpe"))
                >= _num(near_live_stoploss_ladder_metrics.get("sharpe"))
            )
        )
    )
    near_live_stoploss_ladder_followup_outcome_zh = (
        "near-live stop-loss ladder follow-up 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕更窄的 stop-loss ladder 邻域做 near-live 复验。"
        if near_live_stoploss_ladder_followup_improves_refinement
        else (
            "near-live stop-loss ladder follow-up 细化了当前 stop-loss ladder winner 的局部梯度，但还没推翻现任 next distinct contender。"
            if stable_yield_converged
            else "near-live stop-loss ladder follow-up 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_stoploss_ladder_followup_micro_improves_refinement = bool(
        stable_yield_converged
        and near_live_stoploss_ladder_followup_best
        and near_live_stoploss_ladder_followup_micro_best
        and near_live_stoploss_ladder_followup_micro_best.get("strategyId")
        and near_live_stoploss_ladder_followup_micro_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_stoploss_ladder_followup_micro_best.get("strategyId") != most_stable.get("strategyId")
        and (
            _num(near_live_stoploss_ladder_followup_micro_best.get("validWindowCount"))
            > _num(near_live_stoploss_ladder_followup_best.get("validWindowCount"))
            or (
                _num(near_live_stoploss_ladder_followup_micro_best.get("validWindowCount"))
                == _num(near_live_stoploss_ladder_followup_best.get("validWindowCount"))
                and len(_list(near_live_stoploss_ladder_followup_micro_window.get("blockers")))
                < len(_list(near_live_stoploss_ladder_followup_window.get("blockers")))
            )
            or (
                _num(near_live_stoploss_ladder_followup_micro_best.get("validWindowCount"))
                == _num(near_live_stoploss_ladder_followup_best.get("validWindowCount"))
                and len(_list(near_live_stoploss_ladder_followup_micro_window.get("blockers")))
                == len(_list(near_live_stoploss_ladder_followup_window.get("blockers")))
                and _num(near_live_stoploss_ladder_followup_micro_window.get("sharpe"))
                > _num(near_live_stoploss_ladder_followup_window.get("sharpe"))
                and _num(near_live_stoploss_ladder_followup_micro_window.get("tradeCount"))
                >= _num(near_live_stoploss_ladder_followup_window.get("tradeCount"))
                and _num(near_live_stoploss_ladder_followup_micro_metrics.get("sharpe"))
                >= _num(near_live_stoploss_ladder_followup_metrics.get("sharpe"))
            )
        )
    )
    near_live_stoploss_ladder_followup_micro_followup_improves_micro = bool(
        stable_yield_converged
        and near_live_stoploss_ladder_followup_micro_best
        and near_live_stoploss_ladder_followup_micro_followup_best
        and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId")
        and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId") != most_stable.get("strategyId")
        and (
            _num(near_live_stoploss_ladder_followup_micro_followup_best.get("validWindowCount"))
            > _num(near_live_stoploss_ladder_followup_micro_best.get("validWindowCount"))
            or (
                _num(near_live_stoploss_ladder_followup_micro_followup_best.get("validWindowCount"))
                == _num(near_live_stoploss_ladder_followup_micro_best.get("validWindowCount"))
                and len(_list(near_live_stoploss_ladder_followup_micro_followup_window.get("blockers")))
                < len(_list(near_live_stoploss_ladder_followup_micro_window.get("blockers")))
            )
            or (
                _num(near_live_stoploss_ladder_followup_micro_followup_best.get("validWindowCount"))
                == _num(near_live_stoploss_ladder_followup_micro_best.get("validWindowCount"))
                and len(_list(near_live_stoploss_ladder_followup_micro_followup_window.get("blockers")))
                == len(_list(near_live_stoploss_ladder_followup_micro_window.get("blockers")))
                and _num(near_live_stoploss_ladder_followup_micro_followup_window.get("sharpe"))
                > _num(near_live_stoploss_ladder_followup_micro_window.get("sharpe"))
                and _num(near_live_stoploss_ladder_followup_micro_followup_window.get("tradeCount"))
                >= _num(near_live_stoploss_ladder_followup_micro_window.get("tradeCount"))
                and _num(near_live_stoploss_ladder_followup_micro_followup_metrics.get("sharpe"))
                >= _num(near_live_stoploss_ladder_followup_micro_metrics.get("sharpe"))
            )
        )
    )
    near_live_stoploss_ladder_followup_micro_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_stoploss_ladder_followup_micro_best
        and near_live_stoploss_ladder_followup_micro_best.get("strategyId")
        and near_live_stoploss_ladder_followup_micro_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_stoploss_ladder_followup_micro_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_stoploss_ladder_followup_micro_best.get("validWindowCount"))
        >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_stoploss_ladder_followup_micro_window.get("blockers")))
            < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_stoploss_ladder_followup_micro_window.get("blockers")))
                == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_stoploss_ladder_followup_micro_window.get("sharpe"))
                > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_stoploss_ladder_followup_micro_window.get("tradeCount"))
                >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_stoploss_ladder_followup_micro_metrics.get("sharpe"))
                >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_stoploss_ladder_followup_micro_followup_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_stoploss_ladder_followup_micro_followup_best
        and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId")
        and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_stoploss_ladder_followup_micro_followup_best.get("validWindowCount"))
        >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_stoploss_ladder_followup_micro_followup_window.get("blockers")))
            < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_stoploss_ladder_followup_micro_followup_window.get("blockers")))
                == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_stoploss_ladder_followup_micro_followup_window.get("sharpe"))
                > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_stoploss_ladder_followup_micro_followup_window.get("tradeCount"))
                >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_stoploss_ladder_followup_micro_followup_metrics.get("sharpe"))
                >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_stoploss_ladder_followup_micro_outcome_zh = (
        "near-live stop-loss ladder follow-up micro 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 306.25 邻近更窄的 stop-loss substep 做 near-live 复验。"
        if near_live_stoploss_ladder_followup_micro_improves_contender
        else (
            "near-live stop-loss ladder follow-up micro 细化了当前 306.25 ladder winner 的更窄 substep，但还没推翻现任 next distinct contender。"
            if stable_yield_converged
            else "near-live stop-loss ladder follow-up micro 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_stoploss_ladder_followup_micro_followup_outcome_zh = (
        "near-live stop-loss ladder follow-up micro-followup 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 318.75 邻近更窄的 stop-loss substep 做 near-live 复验。"
        if near_live_stoploss_ladder_followup_micro_followup_improves_contender
        else (
            "near-live stop-loss ladder follow-up micro-followup 已优于上一轮 318.75 micro winner，但还没推翻现任 next distinct contender。"
            if near_live_stoploss_ladder_followup_micro_followup_improves_micro
            else (
                "near-live stop-loss ladder follow-up micro-followup 细化了当前 318.75 ladder winner 的更窄 substep，但还没推翻现任 next distinct contender。"
                if stable_yield_converged
                else "near-live stop-loss ladder follow-up micro-followup 目前只作为补充观测，不改变当前 near-live contender。"
            )
        )
    )
    near_live_middle_window_contender_micro_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_middle_window_contender_micro_best
        and near_live_middle_window_contender_micro_best.get("strategyId")
        and near_live_middle_window_contender_micro_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_middle_window_contender_micro_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_middle_window_contender_micro_best.get("validWindowCount"))
        >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_middle_window_contender_micro_window.get("blockers")))
            < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_middle_window_contender_micro_window.get("blockers")))
                == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_middle_window_contender_micro_window.get("sharpe"))
                > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_middle_window_contender_micro_window.get("tradeCount"))
                >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_middle_window_contender_micro_metrics.get("sharpe"))
                >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_middle_window_contender_micro_outcome_zh = (
        "near-live middle-window contender micro 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 325.0 邻近更窄的 middle-window pocket 做 near-live 复验。"
        if near_live_middle_window_contender_micro_improves_contender
        else (
            "near-live middle-window contender micro 细化了当前 325.0 contender pocket，但还没推翻现任 next distinct contender。"
            if stable_yield_converged
            else "near-live middle-window contender micro 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_exit_refinement_window = _window_summary_entry(near_live_exit_refinement_best, "middle_third")
    near_live_exit_refinement_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_exit_refinement_best
        and near_live_exit_refinement_best.get("strategyId")
        and near_live_exit_refinement_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_exit_refinement_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_exit_refinement_best.get("validWindowCount")) >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_exit_refinement_window.get("blockers"))) < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_exit_refinement_window.get("blockers"))) == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_exit_refinement_window.get("sharpe")) > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_exit_refinement_window.get("tradeCount")) >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_exit_refinement_metrics.get("sharpe")) >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_exit_refinement_outcome_zh = (
        "near-live exit refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 TP/SL exit 版本做 near-live 复验。"
        if near_live_exit_refinement_improves_contender
        else (
            "near-live exit refinement 细化了收敛簇的 TP/SL exit 形状，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else "near-live exit refinement 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_middle_tradeoff_window = _window_summary_entry(near_live_middle_tradeoff_best, "middle_third")
    near_live_middle_tradeoff_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_middle_tradeoff_best
        and near_live_middle_tradeoff_best.get("strategyId")
        and near_live_middle_tradeoff_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_middle_tradeoff_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_middle_tradeoff_best.get("validWindowCount")) >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_middle_tradeoff_window.get("blockers"))) < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_middle_tradeoff_window.get("blockers"))) == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_middle_tradeoff_window.get("sharpe")) > _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_middle_tradeoff_window.get("tradeCount")) >= _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_middle_tradeoff_metrics.get("sharpe")) >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_middle_tradeoff_outcome_zh = (
        "near-live middle tradeoff 已在保住收敛簇有效窗口数的前提下改善 middle_third；下一轮优先围绕该 next distinct contender 继续 near-live 复验。"
        if near_live_middle_tradeoff_improves_contender
        else (
            "near-live middle tradeoff 细化了 converged-cluster 的 weak-window 修复形状，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else "near-live middle tradeoff 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_middle_density_window = _window_summary_entry(near_live_middle_density_best, "middle_third")
    near_live_middle_density_improves_contender = bool(
        stable_yield_converged
        and near_live_stability
        and near_live_middle_density_best
        and near_live_middle_density_best.get("strategyId")
        and near_live_middle_density_best.get("strategyId") != near_live_stability.get("strategyId")
        and near_live_middle_density_best.get("strategyId") != most_stable.get("strategyId")
        and _num(near_live_middle_density_best.get("validWindowCount")) >= _num(near_live_stability.get("validWindowCount"))
        and (
            len(_list(near_live_middle_density_window.get("blockers"))) < len(_list(near_live_stability_window.get("blockers")))
            or (
                len(_list(near_live_middle_density_window.get("blockers"))) == len(_list(near_live_stability_window.get("blockers")))
                and _num(near_live_middle_density_window.get("tradeCount")) > _num(near_live_stability_window.get("tradeCount"))
                and _num(near_live_middle_density_window.get("sharpe")) >= _num(near_live_stability_window.get("sharpe"))
                and _num(near_live_middle_density_metrics.get("sharpe")) >= _num(near_live_baseline_metrics.get("sharpe"))
            )
        )
    )
    near_live_middle_density_outcome_zh = (
        "near-live middle-density lift 已在保住收敛簇有效窗口数的前提下改善 middle_third 样本密度；下一轮优先围绕该 next distinct contender 继续 near-live 复验。"
        if near_live_middle_density_improves_contender
        else (
            "near-live middle-density lift 针对 middle_third 的样本密度做了更激进的 cadence 调整，但还没推翻当前 next distinct contender；继续保留现任 contender。"
            if stable_yield_converged
            else "near-live middle-density lift 目前只作为补充观测，不改变当前 near-live contender。"
        )
    )
    near_live_challenger_basis = (
        near_live_signal_refinement_followup_best
        if stable_yield_converged and near_live_signal_refinement_followup_improves_contender and near_live_signal_refinement_followup_best.get("strategyId")
        else (
        near_live_signal_refinement_best
        if stable_yield_converged and near_live_signal_refinement_improves_contender and near_live_signal_refinement_best.get("strategyId")
        else (
        near_live_tempo_refinement_best
        if stable_yield_converged and near_live_tempo_refinement_improves_contender and near_live_tempo_refinement_best.get("strategyId")
        else (
        near_live_middle_window_contender_micro_best
        if stable_yield_converged and near_live_middle_window_contender_micro_improves_contender and near_live_middle_window_contender_micro_best.get("strategyId")
        else (
        near_live_stoploss_ladder_followup_micro_followup_best
        if stable_yield_converged and near_live_stoploss_ladder_followup_micro_followup_improves_contender and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId")
        else (
        near_live_stoploss_ladder_followup_micro_best
        if stable_yield_converged and near_live_stoploss_ladder_followup_micro_improves_contender and near_live_stoploss_ladder_followup_micro_best.get("strategyId")
        else (
        near_live_stoploss_ladder_followup_best
        if stable_yield_converged and near_live_stoploss_ladder_followup_improves_refinement and near_live_stoploss_ladder_followup_best.get("strategyId")
        else (
        near_live_stoploss_ladder_best
        if stable_yield_converged and near_live_stoploss_ladder_improves_contender and near_live_stoploss_ladder_best.get("strategyId")
        else (
        near_live_exit_refinement_best
        if stable_yield_converged and near_live_exit_refinement_improves_contender and near_live_exit_refinement_best.get("strategyId")
        else (
        near_live_middle_density_best
        if stable_yield_converged and near_live_middle_density_improves_contender and near_live_middle_density_best.get("strategyId")
        else (
        near_live_middle_tradeoff_best
        if stable_yield_converged and near_live_middle_tradeoff_improves_contender and near_live_middle_tradeoff_best.get("strategyId")
        else (
        near_live_cluster_refinement_best
        if stable_yield_converged and near_live_cluster_refinement_improves_contender and near_live_cluster_refinement_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_stability.get("strategyId")
        else (
            near_live_middle_window_best
            if near_live_middle_window_improves_followup and near_live_middle_window_best.get("strategyId")
            else (
                near_live_refinement_best
                if near_live_refinement_improves_followup and near_live_refinement_best.get("strategyId")
                else (
                    near_live_followup_best
                    if near_live_followup_improves_repair and near_live_followup_best.get("strategyId")
                    else (
                        near_live_repair_best
                        if near_live_repair_improves_baseline and near_live_repair_best.get("strategyId")
                        else near_live_stability
                    )
                )
            )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
    )
    near_live_challenger_baseline = (
        near_live_stability
        if stable_yield_converged and near_live_signal_refinement_followup_improves_contender and near_live_signal_refinement_followup_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_signal_refinement_improves_contender and near_live_signal_refinement_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_tempo_refinement_improves_contender and near_live_tempo_refinement_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_middle_window_contender_micro_improves_contender and near_live_middle_window_contender_micro_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_stoploss_ladder_followup_micro_followup_improves_contender and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_stoploss_ladder_followup_micro_improves_contender and near_live_stoploss_ladder_followup_micro_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_stoploss_ladder_followup_improves_refinement and near_live_stoploss_ladder_followup_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_stoploss_ladder_improves_contender and near_live_stoploss_ladder_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_exit_refinement_improves_contender and near_live_exit_refinement_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_middle_density_improves_contender and near_live_middle_density_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_middle_tradeoff_improves_contender and near_live_middle_tradeoff_best.get("strategyId")
        else (
        near_live_stability
        if stable_yield_converged and near_live_cluster_refinement_improves_contender and near_live_cluster_refinement_best.get("strategyId")
        else (
        most_stable
        if stable_yield_converged and near_live_challenger_basis.get("strategyId")
        else (
            near_live_followup_best
            if near_live_middle_window_improves_followup and near_live_middle_window_best.get("strategyId")
            and near_live_middle_window_best.get("strategyId") != near_live_followup_best.get("strategyId")
            else (
                near_live_followup_best
                if near_live_refinement_improves_followup and near_live_refinement_best.get("strategyId")
                and near_live_refinement_best.get("strategyId") != near_live_followup_best.get("strategyId")
                else (
                    near_live_repair_best
                    if near_live_followup_improves_repair and near_live_followup_best.get("strategyId")
                    and near_live_followup_best.get("strategyId") != near_live_repair_best.get("strategyId")
                    else (
                        near_live_stability
                        if near_live_repair_improves_baseline and near_live_repair_best.get("strategyId")
                        and near_live_repair_best.get("strategyId") != near_live_stability.get("strategyId")
                        else {}
                    )
                )
            )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
    )
    if near_live_stability:
        if stable_yield_converged and near_live_signal_refinement_followup_improves_contender:
            near_live_challenger_reason_zh = "near-live signal refinement follow-up 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 signal-kernel 微阶梯版本做 near-live 复验。"
        elif stable_yield_converged and near_live_signal_refinement_improves_contender:
            near_live_challenger_reason_zh = "near-live signal refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 signal-kernel 版本做 near-live 复验。"
        elif stable_yield_converged and near_live_tempo_refinement_improves_contender:
            near_live_challenger_reason_zh = "near-live tempo refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 hold/cooldown 节奏版本做 near-live 复验。"
        elif stable_yield_converged and near_live_middle_window_contender_micro_improves_contender:
            near_live_challenger_reason_zh = "near-live middle-window contender micro 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 325.0 邻近更窄的 middle-window pocket 做 near-live 复验。"
        elif stable_yield_converged and near_live_stoploss_ladder_followup_micro_followup_improves_contender:
            near_live_challenger_reason_zh = "near-live stop-loss ladder follow-up micro-followup 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 318.75 邻近更窄的 stop-loss substep 做 near-live 复验。"
        elif stable_yield_converged and near_live_stoploss_ladder_followup_micro_improves_contender:
            near_live_challenger_reason_zh = "near-live stop-loss ladder follow-up micro 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 306.25 邻近更窄的 stop-loss substep 做 near-live 复验。"
        elif stable_yield_converged and near_live_stoploss_ladder_followup_improves_refinement:
            near_live_challenger_reason_zh = "near-live stop-loss ladder follow-up 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕更窄的 stop-loss ladder 邻域做 near-live 复验。"
        elif stable_yield_converged and near_live_stoploss_ladder_improves_contender:
            near_live_challenger_reason_zh = "near-live stop-loss ladder refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 stop-loss ladder 版本做 near-live 复验。"
        elif stable_yield_converged and near_live_exit_refinement_improves_contender:
            near_live_challenger_reason_zh = "near-live exit refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 TP/SL exit 版本做 near-live 复验。"
        elif stable_yield_converged and near_live_middle_density_improves_contender:
            near_live_challenger_reason_zh = "near-live middle-density lift 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 weak-window density 版本做 near-live 复验。"
        elif stable_yield_converged and near_live_middle_tradeoff_improves_contender:
            near_live_challenger_reason_zh = "near-live middle tradeoff 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 weak-window tradeoff 版本做 near-live 复验。"
        elif stable_yield_converged and near_live_cluster_refinement_improves_contender:
            near_live_challenger_reason_zh = "near-live converged-cluster refinement 已找到更强的 next distinct contender；下一轮优先围绕收敛簇新 contender 做 near-live 复验。"
        elif stable_yield_converged and near_live_stability.get("strategyId"):
            near_live_challenger_reason_zh = "稳定锚点与收益 frontier 已收敛到同一参数簇；下一轮优先围绕当前 next distinct contender 做 near-live 复验，避免继续重复已收敛的主锚点。"
        elif near_live_middle_window_improves_followup:
            near_live_challenger_reason_zh = "near-live middle-window follow-up 已找到更像真实可落地的第二候选；下一轮优先围绕 middle-window 版本验证它能否在保住 4 个 valid windows 的前提下继续改善 weak window。"
        elif near_live_refinement_improves_followup:
            near_live_challenger_reason_zh = "near-live stability refinement 已找到更强的第二候选；下一轮优先围绕 refinement 版本验证它能否在不明显牺牲窗口质量的前提下稳住第二候选位置。"
        elif near_live_followup_improves_repair:
            near_live_challenger_reason_zh = "near-live stability follow-up 已找到更强的第二候选；下一轮优先围绕 follow-up 版本验证它能否在不明显牺牲窗口质量的前提下稳住第二候选位置。"
        elif near_live_repair_improves_baseline:
            near_live_challenger_reason_zh = "near-live stability 局部搜索已找到更强的第二候选；下一轮优先围绕修复版验证它能否在不明显牺牲窗口质量的前提下稳住第二候选位置。"
        else:
            near_live_challenger_reason_zh = "该候选比当前收益前沿更接近稳定落地；下一轮先验证它能否在不明显牺牲窗口质量的前提下稳住第二候选位置。"
        recommendations.append({
            "id": "near_live_stability_challenger",
            "label": "near_live_stability_challenger",
            "priority": near_live_priority,
            "basisStrategyId": near_live_challenger_basis.get("strategyId"),
            "baselineStrategyId": near_live_challenger_baseline.get("strategyId"),
            "reasonZh": near_live_challenger_reason_zh,
            "parameterFocus": [
                "preserve_valid_window_count_advantage",
                "improve_middle_third_trade_count",
                "improve_middle_third_sharpe",
                "nudge_hold_bars_6_to_10",
                "nudge_cooldown_3_to_5",
            ],
        })
    active_near_live_tradeoff = (
        near_live_signal_refinement_followup_best
        if stable_yield_converged and near_live_signal_refinement_followup_improves_contender and near_live_signal_refinement_followup_best.get("strategyId")
        else (
        near_live_signal_refinement_best
        if stable_yield_converged and near_live_signal_refinement_improves_contender and near_live_signal_refinement_best.get("strategyId")
        else (
        near_live_tempo_refinement_best
        if stable_yield_converged and near_live_tempo_refinement_improves_contender and near_live_tempo_refinement_best.get("strategyId")
        else (
        near_live_middle_window_contender_micro_best
        if stable_yield_converged and near_live_middle_window_contender_micro_improves_contender and near_live_middle_window_contender_micro_best.get("strategyId")
        else (
        near_live_stoploss_ladder_followup_micro_followup_best
        if stable_yield_converged and near_live_stoploss_ladder_followup_micro_followup_improves_contender and near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId")
        else (
        near_live_stoploss_ladder_followup_micro_best
        if stable_yield_converged and near_live_stoploss_ladder_followup_micro_improves_contender and near_live_stoploss_ladder_followup_micro_best.get("strategyId")
        else (
        near_live_stoploss_ladder_followup_best
        if stable_yield_converged and near_live_stoploss_ladder_followup_improves_refinement and near_live_stoploss_ladder_followup_best.get("strategyId")
        else (
        near_live_stoploss_ladder_best
        if stable_yield_converged and near_live_stoploss_ladder_improves_contender and near_live_stoploss_ladder_best.get("strategyId")
        else (
        near_live_exit_refinement_best
        if stable_yield_converged and near_live_exit_refinement_improves_contender and near_live_exit_refinement_best.get("strategyId")
        else (
        near_live_middle_density_best
        if stable_yield_converged and near_live_middle_density_improves_contender and near_live_middle_density_best.get("strategyId")
        else (
        near_live_middle_tradeoff_best
        if stable_yield_converged and near_live_middle_tradeoff_improves_contender and near_live_middle_tradeoff_best.get("strategyId")
        else (
        near_live_cluster_refinement_best
        if stable_yield_converged and near_live_cluster_refinement_improves_contender and near_live_cluster_refinement_best.get("strategyId")
        else (
        near_live_middle_window_best
        if near_live_middle_window_improves_followup and near_live_middle_window_best.get("strategyId")
        else (
            near_live_refinement_best
            if near_live_refinement_improves_followup and near_live_refinement_best.get("strategyId")
            else (
                near_live_followup_best
                if near_live_followup_improves_repair and near_live_followup_best.get("strategyId")
                else (
                    near_live_repair_best
                    if near_live_repair_improves_baseline and near_live_repair_best.get("strategyId")
                    else near_live_stability
                )
            )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
        )
    )
    near_live_challenger_converged_with_yield = bool(
        active_near_live_tradeoff
        and high_yield
        and active_near_live_tradeoff.get("strategyId")
        and high_yield.get("strategyId")
        and _has_meaningful_tradeoff_identity(_tradeoff_summary(active_near_live_tradeoff))
        and _has_meaningful_tradeoff_identity(_tradeoff_summary(high_yield))
        and _tradeoff_identity(_tradeoff_summary(active_near_live_tradeoff)) == _tradeoff_identity(_tradeoff_summary(high_yield))
    )
    stable_yield_converged_next_distinct_ready = bool(
        stable_yield_converged
        and near_live_challenger_basis.get("strategyId")
        and near_live_challenger_basis.get("strategyId") != most_stable.get("strategyId")
        and not near_live_signal_refinement_followup_improves_contender
        and not near_live_signal_refinement_improves_contender
        and not near_live_tempo_refinement_improves_contender
        and not near_live_middle_window_contender_micro_improves_contender
        and not near_live_stoploss_ladder_followup_micro_followup_improves_contender
        and not near_live_stoploss_ladder_followup_micro_improves_contender
        and not near_live_stoploss_ladder_followup_improves_refinement
        and not near_live_stoploss_ladder_improves_contender
        and not near_live_exit_refinement_improves_contender
        and not near_live_middle_density_improves_contender
        and not near_live_middle_tradeoff_improves_contender
        and not near_live_cluster_refinement_improves_contender
    )
    stable_middle_baseline_window = _window_summary_entry(most_stable, "middle_third")
    stable_middle_repair_window = _window_summary_entry(stable_middle_repair_best, "middle_third")
    stable_anchor_strategy_id = str(_dict(most_stable).get("strategyId") or "").strip()
    stable_anchor_label = stable_anchor_strategy_id or "当前稳健锚点"
    stable_middle_repair_improves_baseline = bool(
        most_stable
        and stable_middle_repair_best
        and stable_middle_repair_best.get("strategyId")
        and (
            _num(stable_middle_repair_best.get("validWindowCount")) > _num(most_stable.get("validWindowCount"))
            or (
                _num(stable_middle_repair_best.get("validWindowCount")) == _num(most_stable.get("validWindowCount"))
                and len(_list(stable_middle_repair_window.get("blockers"))) < len(_list(stable_middle_baseline_window.get("blockers")))
            )
            or (
                _num(stable_middle_repair_best.get("validWindowCount")) == _num(most_stable.get("validWindowCount"))
                and len(_list(stable_middle_repair_window.get("blockers"))) == len(_list(stable_middle_baseline_window.get("blockers")))
                and _num(stable_middle_repair_window.get("sharpe")) > _num(stable_middle_baseline_window.get("sharpe"))
                and _num(stable_middle_repair_window.get("tradeCount")) >= _num(stable_middle_baseline_window.get("tradeCount"))
            )
            or (
                _num(stable_middle_repair_best.get("validWindowCount")) == _num(most_stable.get("validWindowCount"))
                and _num(stable_middle_repair_metrics.get("sharpe")) > _num(stable_baseline_metrics.get("sharpe"))
                and _num(stable_middle_repair_metrics.get("tradeCount")) > _num(stable_baseline_metrics.get("tradeCount"))
            )
        )
    )
    stable_middle_repair_outcome_zh = (
        f"stable middle-third focused search 已找到比当前 {stable_anchor_label} 更强的稳健修复候选；下一轮优先围绕修复版复验。"
        if stable_middle_repair_improves_baseline
        else f"stable middle-third focused search 暂未推翻当前 {stable_anchor_label} 稳健锚点；继续把 {stable_anchor_label} 作为主锚点。"
    )
    stable_middle_followup_window = _window_summary_entry(stable_middle_followup_best, "middle_third")
    stable_middle_followup_refinement_window = _window_summary_entry(stable_middle_followup_refinement_best, "middle_third")
    stable_middle_followup_refinement_followup_window = _window_summary_entry(
        stable_middle_followup_refinement_followup_best, "middle_third"
    )
    stable_middle_followup_refinement_micro_window = _window_summary_entry(
        stable_middle_followup_refinement_micro_best, "middle_third"
    )
    stable_middle_followup_refinement_micro_followup_window = _window_summary_entry(
        stable_middle_followup_refinement_micro_followup_best, "middle_third"
    )
    stable_middle_followup_improves_weak_window = bool(
        stable_middle_repair_best
        and stable_middle_followup_best
        and stable_middle_followup_best.get("strategyId")
        and (
            len(_list(stable_middle_followup_window.get("blockers"))) < len(_list(stable_middle_repair_window.get("blockers")))
            or (
                len(_list(stable_middle_followup_window.get("blockers"))) == len(_list(stable_middle_repair_window.get("blockers")))
                and _num(stable_middle_followup_window.get("sharpe")) > _num(stable_middle_repair_window.get("sharpe"))
                and _num(stable_middle_followup_window.get("tradeCount")) >= _num(stable_middle_repair_window.get("tradeCount"))
            )
        )
    )
    stable_middle_followup_improves_aggregate = bool(
        stable_middle_repair_best
        and stable_middle_followup_best
        and stable_middle_followup_best.get("strategyId")
        and (
            _num(stable_middle_followup_best.get("validWindowCount")) > _num(stable_middle_repair_best.get("validWindowCount"))
            and _num(stable_middle_followup_metrics.get("sharpe")) >= _num(stable_middle_repair_metrics.get("sharpe"))
        )
    )
    stable_middle_followup_improves_repair = stable_middle_followup_improves_weak_window
    stable_middle_followup_outcome_zh = (
        "stable middle-third follow-up 局部搜索已找到比当前 repair 候选更像真实中段修复的变体；下一轮优先围绕 follow-up 版本复验。"
        if stable_middle_followup_improves_weak_window
        else (
            "stable middle-third follow-up 局部搜索提升了整体稳定性，但 middle_third 弱窗口本身没有改善；把它当作锚点保守变体，不当作真实 weak-window 修复。"
            if stable_middle_followup_improves_aggregate
            else f"stable middle-third follow-up 局部搜索暂未推翻当前 repair 候选；继续把 {stable_anchor_label} 和现有 repair 版本作为主锚点。"
        )
    )
    stable_middle_followup_refinement_improves_followup = bool(
        stable_middle_followup_best
        and stable_middle_followup_refinement_best
        and stable_middle_followup_refinement_best.get("strategyId")
        and (
            _num(stable_middle_followup_refinement_best.get("validWindowCount")) > _num(stable_middle_followup_best.get("validWindowCount"))
            or (
                _num(stable_middle_followup_refinement_best.get("validWindowCount")) == _num(stable_middle_followup_best.get("validWindowCount"))
                and _num(stable_middle_followup_refinement_metrics.get("sharpe")) > _num(stable_middle_followup_metrics.get("sharpe"))
                and _num(stable_middle_followup_refinement_metrics.get("tradeCount")) >= _num(stable_middle_followup_metrics.get("tradeCount"))
            )
            or (
                _num(stable_middle_followup_refinement_best.get("validWindowCount")) == _num(stable_middle_followup_best.get("validWindowCount"))
                and len(_list(stable_middle_followup_refinement_window.get("blockers"))) < len(_list(stable_middle_followup_window.get("blockers")))
                and _num(stable_middle_followup_refinement_window.get("sharpe")) >= _num(stable_middle_followup_window.get("sharpe"))
            )
        )
    )
    stable_middle_followup_refinement_outcome_zh = (
        "stable middle-third aggregate-stability refinement 已在不牺牲整体稳定性的前提下找到更强的第三候选；下一轮优先围绕 refinement 版本复验。"
        if stable_middle_followup_refinement_improves_followup
        else (
            "stable middle-third aggregate-stability refinement 细化了 fallback 邻域，但还没推翻当前第三候选；继续保留现任 aggregate-stability fallback。"
            if stable_middle_followup_refinement_best.get("strategyId")
            else "stable middle-third aggregate-stability refinement 当前尚未形成可比较候选。"
        )
    )
    stable_middle_followup_refinement_followup_improves_refinement = bool(
        stable_middle_followup_refinement_best
        and stable_middle_followup_refinement_followup_best
        and stable_middle_followup_refinement_followup_best.get("strategyId")
        and (
            _num(stable_middle_followup_refinement_followup_best.get("validWindowCount"))
            > _num(stable_middle_followup_refinement_best.get("validWindowCount"))
            or (
                _num(stable_middle_followup_refinement_followup_best.get("validWindowCount"))
                == _num(stable_middle_followup_refinement_best.get("validWindowCount"))
                and _num(stable_middle_followup_refinement_followup_metrics.get("sharpe"))
                > _num(stable_middle_followup_refinement_metrics.get("sharpe"))
                and _num(stable_middle_followup_refinement_followup_metrics.get("tradeCount"))
                >= _num(stable_middle_followup_refinement_metrics.get("tradeCount"))
            )
            or (
                _num(stable_middle_followup_refinement_followup_best.get("validWindowCount"))
                == _num(stable_middle_followup_refinement_best.get("validWindowCount"))
                and len(_list(stable_middle_followup_refinement_followup_window.get("blockers")))
                < len(_list(stable_middle_followup_refinement_window.get("blockers")))
                and _num(stable_middle_followup_refinement_followup_window.get("sharpe"))
                >= _num(stable_middle_followup_refinement_window.get("sharpe"))
            )
        )
    )
    stable_middle_followup_refinement_micro_improves_refinement = bool(
        stable_middle_followup_refinement_best
        and stable_middle_followup_refinement_micro_best
        and stable_middle_followup_refinement_micro_best.get("strategyId")
        and (
            _num(stable_middle_followup_refinement_micro_best.get("validWindowCount"))
            > _num(stable_middle_followup_refinement_best.get("validWindowCount"))
            or (
                _num(stable_middle_followup_refinement_micro_best.get("validWindowCount"))
                == _num(stable_middle_followup_refinement_best.get("validWindowCount"))
                and _num(stable_middle_followup_refinement_micro_metrics.get("sharpe"))
                > _num(stable_middle_followup_refinement_metrics.get("sharpe"))
                and _num(stable_middle_followup_refinement_micro_metrics.get("tradeCount"))
                >= _num(stable_middle_followup_refinement_metrics.get("tradeCount"))
            )
            or (
                _num(stable_middle_followup_refinement_micro_best.get("validWindowCount"))
                == _num(stable_middle_followup_refinement_best.get("validWindowCount"))
                and len(_list(stable_middle_followup_refinement_micro_window.get("blockers")))
                < len(_list(stable_middle_followup_refinement_window.get("blockers")))
                and _num(stable_middle_followup_refinement_micro_window.get("sharpe"))
                >= _num(stable_middle_followup_refinement_window.get("sharpe"))
            )
        )
    )
    stable_middle_followup_refinement_micro_followup_improves_micro = bool(
        stable_middle_followup_refinement_micro_best
        and stable_middle_followup_refinement_micro_followup_best
        and stable_middle_followup_refinement_micro_followup_best.get("strategyId")
        and (
            _num(stable_middle_followup_refinement_micro_followup_best.get("validWindowCount"))
            > _num(stable_middle_followup_refinement_micro_best.get("validWindowCount"))
            or (
                _num(stable_middle_followup_refinement_micro_followup_best.get("validWindowCount"))
                == _num(stable_middle_followup_refinement_micro_best.get("validWindowCount"))
                and _num(stable_middle_followup_refinement_micro_followup_metrics.get("sharpe"))
                > _num(stable_middle_followup_refinement_micro_metrics.get("sharpe"))
                and _num(stable_middle_followup_refinement_micro_followup_metrics.get("tradeCount"))
                >= _num(stable_middle_followup_refinement_micro_metrics.get("tradeCount"))
            )
            or (
                _num(stable_middle_followup_refinement_micro_followup_best.get("validWindowCount"))
                == _num(stable_middle_followup_refinement_micro_best.get("validWindowCount"))
                and len(_list(stable_middle_followup_refinement_micro_followup_window.get("blockers")))
                < len(_list(stable_middle_followup_refinement_micro_window.get("blockers")))
                and _num(stable_middle_followup_refinement_micro_followup_window.get("sharpe"))
                >= _num(stable_middle_followup_refinement_micro_window.get("sharpe"))
            )
        )
    )
    stable_middle_followup_refinement_micro_followup_improves_refinement = bool(
        stable_middle_followup_refinement_best
        and stable_middle_followup_refinement_micro_followup_best
        and stable_middle_followup_refinement_micro_followup_best.get("strategyId")
        and (
            _num(stable_middle_followup_refinement_micro_followup_best.get("validWindowCount"))
            > _num(stable_middle_followup_refinement_best.get("validWindowCount"))
            or (
                _num(stable_middle_followup_refinement_micro_followup_best.get("validWindowCount"))
                == _num(stable_middle_followup_refinement_best.get("validWindowCount"))
                and _num(stable_middle_followup_refinement_micro_followup_metrics.get("sharpe"))
                > _num(stable_middle_followup_refinement_metrics.get("sharpe"))
                and _num(stable_middle_followup_refinement_micro_followup_metrics.get("tradeCount"))
                >= _num(stable_middle_followup_refinement_metrics.get("tradeCount"))
            )
            or (
                _num(stable_middle_followup_refinement_micro_followup_best.get("validWindowCount"))
                == _num(stable_middle_followup_refinement_best.get("validWindowCount"))
                and len(_list(stable_middle_followup_refinement_micro_followup_window.get("blockers")))
                < len(_list(stable_middle_followup_refinement_window.get("blockers")))
                and _num(stable_middle_followup_refinement_micro_followup_window.get("sharpe"))
                >= _num(stable_middle_followup_refinement_window.get("sharpe"))
            )
        )
    )
    stable_middle_followup_refinement_followup_outcome_zh = (
        "stable middle-third aggregate-stability refinement follow-up 已进一步强化当前第三候选；下一轮优先围绕这个更窄的 refinement 邻域继续复验。"
        if stable_middle_followup_refinement_followup_improves_refinement
        else (
            "stable middle-third aggregate-stability refinement follow-up 细化了当前 refinement winner 的局部邻域，但还没推翻现任第三候选。"
            if stable_middle_followup_refinement_followup_best.get("strategyId")
            else "stable middle-third aggregate-stability refinement follow-up 当前尚未形成可比较候选。"
        )
    )
    stable_middle_followup_refinement_micro_outcome_zh = (
        "stable middle-third micro-refinement 已在当前 third-line winner 周围找到更强的微阶梯候选；下一轮优先围绕这个更窄的 ladder 邻域继续复验。"
        if stable_middle_followup_refinement_micro_improves_refinement
        else (
            "stable middle-third micro-refinement 细化了当前 refinement winner 的 TP/SL/hold/cooldown 微阶梯，但还没推翻现任第三候选。"
            if stable_middle_followup_refinement_micro_best.get("strategyId")
            else "stable middle-third micro-refinement 当前尚未形成可比较候选。"
        )
    )
    stable_middle_followup_refinement_micro_followup_outcome_zh = (
        "stable middle-third micro-followup 已在 306.25 附近的更窄 ladder 邻域找到更强的第三候选；下一轮优先围绕这个 ultra-local 版本继续复验。"
        if stable_middle_followup_refinement_micro_followup_improves_refinement
        else (
            "stable middle-third micro-followup 进一步细化了 micro winner 的 ultra-local ladder，并优于上一轮 micro 候选，但还没推翻现任第三候选。"
            if stable_middle_followup_refinement_micro_followup_improves_micro
            else (
                "stable middle-third micro-followup 细化了当前 306.25 微阶梯邻域，但还没推翻现任第三候选。"
                if stable_middle_followup_refinement_micro_followup_best.get("strategyId")
                else "stable middle-third micro-followup 当前尚未形成可比较候选。"
            )
        )
    )
    stable_middle_weak_window_window = _window_summary_entry(stable_middle_weak_window_best, "middle_third")
    stable_middle_weak_window_improves_baseline = bool(
        most_stable
        and stable_middle_weak_window_best
        and stable_middle_weak_window_best.get("strategyId")
        and (
            len(_list(stable_middle_weak_window_window.get("blockers"))) < len(_list(stable_middle_baseline_window.get("blockers")))
            or (
                len(_list(stable_middle_weak_window_window.get("blockers"))) == len(_list(stable_middle_baseline_window.get("blockers")))
                and _num(stable_middle_weak_window_window.get("sharpe")) > _num(stable_middle_baseline_window.get("sharpe"))
                and _num(stable_middle_weak_window_window.get("tradeCount")) >= _num(stable_middle_baseline_window.get("tradeCount"))
            )
        )
    )
    stable_middle_weak_window_outcome_zh = (
        f"stable middle weak-window confirmation 已找到比 {stable_anchor_label} 更强的 middle_third 候选；下一轮围绕弱窗口确认版本继续复验。"
        if stable_middle_weak_window_improves_baseline
        else f"stable middle weak-window confirmation 暂未在保持稳健个性的前提下修掉 middle_third；继续把 {stable_anchor_label} 作为主锚点。"
    )
    stable_middle_bridge_window = _window_summary_entry(stable_middle_bridge_best, "middle_third")
    stable_middle_bridge_improves_weak_window = bool(
        most_stable
        and stable_middle_bridge_best
        and stable_middle_bridge_best.get("strategyId")
        and (
            len(_list(stable_middle_bridge_window.get("blockers"))) < len(_list(stable_middle_baseline_window.get("blockers")))
            or (
                len(_list(stable_middle_bridge_window.get("blockers"))) == len(_list(stable_middle_baseline_window.get("blockers")))
                and _num(stable_middle_bridge_window.get("sharpe")) > _num(stable_middle_baseline_window.get("sharpe"))
                and _num(stable_middle_bridge_window.get("tradeCount")) >= _num(stable_middle_baseline_window.get("tradeCount"))
            )
        )
    )
    stable_middle_bridge_improves_aggregate = bool(
        stable_middle_weak_window_best
        and stable_middle_bridge_best
        and stable_middle_bridge_best.get("strategyId")
        and (
            _num(stable_middle_bridge_best.get("validWindowCount")) > _num(stable_middle_weak_window_best.get("validWindowCount"))
            and _num(stable_middle_bridge_metrics.get("sharpe")) >= _num(stable_middle_weak_window_metrics.get("sharpe"))
        )
    )
    stable_middle_bridge_improves_baseline = bool(
        most_stable
        and stable_middle_bridge_best
        and stable_middle_bridge_best.get("strategyId")
        and _num(stable_middle_bridge_best.get("validWindowCount")) >= 2
        and stable_middle_bridge_improves_weak_window
    )
    stable_middle_bridge_outcome_zh = (
        "stable middle weak-window bridge 已找到兼顾更多有效窗口与 middle_third 改善的折中候选；下一轮优先围绕 bridge 版本复验。"
        if stable_middle_bridge_improves_baseline
        else (
            "stable middle weak-window bridge 提高了整体有效窗口数，但 middle_third 弱窗口本身没有改善；把它当作折中观察线，不当作真实 weak-window 修复。"
            if stable_middle_bridge_improves_aggregate
            else f"stable middle weak-window bridge 暂未找到同时保住 2+ valid windows 且修掉 middle_third 的折中候选；继续把 {stable_anchor_label} 作为主锚点。"
        )
    )
    stable_middle_tradeoff_window = _window_summary_entry(stable_middle_tradeoff_best, "middle_third")
    stable_middle_tradeoff_improves_weak_window = bool(
        most_stable
        and stable_middle_tradeoff_best
        and stable_middle_tradeoff_best.get("strategyId")
        and (
            len(_list(stable_middle_tradeoff_window.get("blockers"))) < len(_list(stable_middle_baseline_window.get("blockers")))
            or (
                len(_list(stable_middle_tradeoff_window.get("blockers"))) == len(_list(stable_middle_baseline_window.get("blockers")))
                and _num(stable_middle_tradeoff_window.get("sharpe")) > _num(stable_middle_baseline_window.get("sharpe"))
                and _num(stable_middle_tradeoff_window.get("tradeCount")) >= _num(stable_middle_baseline_window.get("tradeCount"))
            )
        )
    )
    stable_middle_tradeoff_improves_bridge = bool(
        stable_middle_bridge_best
        and stable_middle_tradeoff_best
        and stable_middle_tradeoff_best.get("strategyId")
        and (
            _num(stable_middle_tradeoff_best.get("validWindowCount")) > _num(stable_middle_bridge_best.get("validWindowCount"))
            or (
                _num(stable_middle_tradeoff_best.get("validWindowCount")) == _num(stable_middle_bridge_best.get("validWindowCount"))
                and _num(stable_middle_tradeoff_window.get("sharpe")) > _num(stable_middle_bridge_window.get("sharpe"))
                and _num(stable_middle_tradeoff_window.get("tradeCount")) >= _num(stable_middle_bridge_window.get("tradeCount"))
            )
        )
    )
    stable_middle_tradeoff_improves_baseline = bool(
        most_stable
        and stable_middle_tradeoff_best
        and stable_middle_tradeoff_best.get("strategyId")
        and _num(stable_middle_tradeoff_best.get("validWindowCount")) >= 2
        and stable_middle_tradeoff_improves_weak_window
    )
    stable_middle_tradeoff_outcome_zh = (
        "stable middle tradeoff repair line 已找到兼顾 2+ valid windows 与 middle_third 改善的折中候选；下一轮优先围绕 tradeoff 版本复验。"
        if stable_middle_tradeoff_improves_baseline
        else (
            "stable middle tradeoff repair line 改善了 bridge 线，但 middle_third 仍未真正修复；把它当作下一条折中观察线。"
            if stable_middle_tradeoff_improves_bridge
            else "stable middle tradeoff repair line 暂未优于现有 bridge 线；继续保留当前稳健锚点和 near-live contender。"
        )
    )
    stable_middle_followup_stability_fallback_available = bool(
        stable_middle_followup_best.get("strategyId")
        and (
            stable_middle_followup_improves_aggregate
            or (
                _num(stable_middle_followup_best.get("validWindowCount")) >= 3
                and _num(stable_middle_followup_metrics.get("sharpe")) >= 1.0
                and (
                    not stable_middle_tradeoff_best.get("strategyId")
                    or _num(stable_middle_followup_best.get("validWindowCount"))
                    > _num(stable_middle_tradeoff_best.get("validWindowCount"))
                    or (
                        _num(stable_middle_followup_best.get("validWindowCount"))
                        == _num(stable_middle_tradeoff_best.get("validWindowCount"))
                        and _num(stable_middle_followup_metrics.get("sharpe"))
                        > _num(stable_middle_tradeoff_metrics.get("sharpe"))
                        and _num(stable_middle_followup_metrics.get("tradeCount"))
                        >= _num(stable_middle_tradeoff_metrics.get("tradeCount"))
                    )
                )
                and not stable_middle_tradeoff_improves_baseline
                and not stable_middle_bridge_improves_baseline
                and not stable_middle_weak_window_improves_baseline
            )
        )
    )
    stable_middle_tradeoff_distinct_repair_available = bool(
        stable_middle_tradeoff_best.get("strategyId")
        and (
            stable_middle_tradeoff_improves_baseline
            or stable_middle_tradeoff_improves_bridge
            or stable_middle_tradeoff_improves_weak_window
        )
    )
    stable_middle_basis_strategy_id = most_stable.get("strategyId")
    stable_middle_basis_label = "stable anchor fallback"
    stable_middle_basis_role_zh = "第三条稳定观察线"
    if most_stable:
        if stable_middle_tradeoff_improves_baseline and stable_middle_tradeoff_best.get("strategyId"):
            stable_middle_basis_strategy_id = stable_middle_tradeoff_best.get("strategyId")
            stable_middle_basis_label = "stable middle tradeoff repair line"
            stable_middle_basis_role_zh = "第三条 distinct 弱窗口修复路径"
        elif stable_middle_tradeoff_improves_bridge and stable_middle_tradeoff_best.get("strategyId"):
            stable_middle_basis_strategy_id = stable_middle_tradeoff_best.get("strategyId")
            stable_middle_basis_label = "stable middle tradeoff repair line"
            stable_middle_basis_role_zh = "第三条 distinct 弱窗口修复路径"
        elif stable_middle_bridge_improves_baseline and stable_middle_bridge_best.get("strategyId"):
            stable_middle_basis_strategy_id = stable_middle_bridge_best.get("strategyId")
            stable_middle_basis_label = "stable middle weak-window bridge"
            stable_middle_basis_role_zh = "第三条 distinct 弱窗口修复路径"
        elif stable_middle_weak_window_improves_baseline and stable_middle_weak_window_best.get("strategyId"):
            stable_middle_basis_strategy_id = stable_middle_weak_window_best.get("strategyId")
            stable_middle_basis_label = "stable middle weak-window confirmation"
            stable_middle_basis_role_zh = "第三条 distinct 弱窗口修复路径"
        elif stable_middle_followup_improves_weak_window and stable_middle_followup_best.get("strategyId"):
            stable_middle_basis_strategy_id = stable_middle_followup_best.get("strategyId")
            stable_middle_basis_label = "stable middle-third follow-up"
            stable_middle_basis_role_zh = "第三条 distinct 弱窗口修复路径"
        elif (
            stable_middle_followup_refinement_micro_followup_improves_refinement
            and stable_middle_followup_refinement_micro_followup_best.get("strategyId")
        ):
            stable_middle_basis_strategy_id = stable_middle_followup_refinement_micro_followup_best.get("strategyId")
            stable_middle_basis_label = "stable middle-third micro-followup"
            stable_middle_basis_role_zh = "第三条 distinct 稳定 fallback 路径"
        elif (
            stable_middle_followup_refinement_micro_improves_refinement
            and stable_middle_followup_refinement_micro_best.get("strategyId")
        ):
            stable_middle_basis_strategy_id = stable_middle_followup_refinement_micro_best.get("strategyId")
            stable_middle_basis_label = "stable middle-third micro-refinement"
            stable_middle_basis_role_zh = "第三条 distinct 稳定 fallback 路径"
        elif (
            stable_middle_followup_refinement_followup_improves_refinement
            and stable_middle_followup_refinement_followup_best.get("strategyId")
        ):
            stable_middle_basis_strategy_id = stable_middle_followup_refinement_followup_best.get("strategyId")
            stable_middle_basis_label = "stable middle-third aggregate-stability refinement follow-up"
            stable_middle_basis_role_zh = "第三条 distinct 稳定 fallback 路径"
        elif stable_middle_followup_refinement_improves_followup and stable_middle_followup_refinement_best.get("strategyId"):
            stable_middle_basis_strategy_id = stable_middle_followup_refinement_best.get("strategyId")
            stable_middle_basis_label = "stable middle-third aggregate-stability refinement"
            stable_middle_basis_role_zh = "第三条 distinct 稳定 fallback 路径"
        elif stable_middle_followup_stability_fallback_available and stable_middle_followup_best.get("strategyId"):
            stable_middle_basis_strategy_id = stable_middle_followup_best.get("strategyId")
            stable_middle_basis_label = "stable middle-third aggregate-stability fallback"
            stable_middle_basis_role_zh = "第三条 distinct 稳定 fallback 路径"
        elif stable_middle_tradeoff_distinct_repair_available and stable_middle_tradeoff_best.get("strategyId"):
            stable_middle_basis_strategy_id = stable_middle_tradeoff_best.get("strategyId")
            stable_middle_basis_label = "stable middle tradeoff repair line"
            stable_middle_basis_role_zh = "第三条 distinct 弱窗口修复路径"
        stable_middle_distinct_repair_selected = bool(
            stable_middle_basis_strategy_id
            and stable_middle_basis_strategy_id not in {
                most_stable.get("strategyId"),
                near_live_stability.get("strategyId"),
            }
        )
        if stable_middle_tradeoff_improves_baseline:
            stable_middle_reason_zh = (
                "stable middle tradeoff repair line 已找到更像真实可落地中段修复的折中候选；下一轮围绕 tradeoff 版本继续局部复验。"
            )
        elif near_live_challenger_converged_with_yield and stable_middle_tradeoff_improves_bridge:
            stable_middle_reason_zh = (
                "near-live challenger 与高收益 frontier 已收敛到同一参数簇；把 stable middle tradeoff repair line 提升为第三条 distinct 修复线继续复验。"
            )
        elif stable_middle_bridge_improves_baseline:
            stable_middle_reason_zh = (
                "stable middle weak-window bridge 已找到更像真实可落地中段修复的折中候选；下一轮围绕 bridge 版本继续局部复验。"
            )
        elif stable_middle_weak_window_improves_baseline:
            stable_middle_reason_zh = (
                "stable middle weak-window confirmation 已找到更像真实中段修复的候选；下一轮围绕该版本继续局部复验。"
            )
        elif stable_middle_followup_refinement_micro_followup_improves_refinement:
            stable_middle_reason_zh = (
                "stable middle-third micro-followup 已在 306.25 附近的更窄 ladder 邻域找到更强的第三候选；下一轮优先围绕这个 ultra-local 版本继续局部复验。"
            )
        elif stable_middle_followup_refinement_micro_improves_refinement:
            stable_middle_reason_zh = (
                "stable middle-third micro-refinement 已在当前 third-line winner 周围找到更强的微阶梯候选；下一轮优先围绕这个更窄的 ladder 邻域继续局部复验。"
            )
        elif stable_middle_followup_refinement_micro_followup_improves_micro:
            stable_middle_reason_zh = (
                "stable middle-third micro-followup 已优于上一轮 micro 候选，但还没推翻当前第三候选；这一 ultra-local ladder 继续保留为第四观察线。"
            )
        elif stable_middle_followup_refinement_followup_improves_refinement:
            stable_middle_reason_zh = (
                "stable middle-third aggregate-stability refinement follow-up 已进一步强化当前第三候选；下一轮优先围绕这个更窄的 refinement 邻域继续局部复验。"
            )
        elif stable_middle_followup_refinement_improves_followup:
            stable_middle_reason_zh = (
                "stable middle-third aggregate-stability refinement 已在不替换主锚点的前提下找到更强的第三候选；下一轮优先围绕 refinement 版本继续局部复验。"
            )
        elif stable_middle_followup_stability_fallback_available:
            stable_middle_reason_zh = (
                "stable middle-third follow-up 当前主要提升整体稳定性，但它仍比 tradeoff/bridge 更接近可复验的第三条稳定 fallback 线；先作为第三顺位 aggregate-stability candidate 继续复验。"
            )
        elif stable_middle_tradeoff_improves_bridge:
            stable_middle_reason_zh = (
                "stable middle tradeoff repair line 比现有 bridge 更接近真实折中线，但还没修掉 middle_third；这一线继续作为第四顺位观察线。"
            )
        elif stable_middle_followup_improves_weak_window:
            stable_middle_reason_zh = (
                "stable middle-third follow-up 已找到更像真实中段修复的变体；下一轮围绕 follow-up 版本继续局部复验。"
            )
        elif stable_middle_followup_improves_aggregate:
            stable_middle_reason_zh = (
                "stable middle-third follow-up 目前只提高整体稳定性，没有修掉 middle_third；这一线暂不高于 sample-rich bridge。"
            )
        else:
            stable_middle_reason_zh = "现任稳健候选没有亏损窗口，但 middle_third Sharpe/交易数弱；只做中段修复，不放大仓位。"
        recommendations.append({
            "id": "stable_champion_middle_third_rescue",
            "label": "stable_champion_middle_third_rescue",
            "priority": (
                3
                if stable_middle_distinct_repair_selected
                else 4
            ),
            "basisStrategyId": stable_middle_basis_strategy_id,
            "reasonZh": stable_middle_reason_zh,
            "parameterFocus": [
                "short_bias_or_low_noise_both_bias",
                "hold_bars_8_to_16",
                "cooldown_3_to_6",
                "avoid_density_only_search",
            ],
        })
    if sample_rich_best:
        recommendations.append({
            "id": "sample_rich_quality_bridge",
            "label": "sample_rich_quality_bridge",
            "priority": (
                4
                if stable_middle_distinct_repair_selected
                else 3
            ),
            "basisStrategyId": sample_rich_best.get("strategyId"),
            "reasonZh": (
                "样本丰富候选能补交易数，但当前先让位于已证明能改善 weak-window baseline 的 tradeoff 修复线；这一线保留为第四顺位质量/样本桥接。"
                if stable_middle_tradeoff_improves_baseline
                else (
                    f"near-live challenger 与收益 frontier 已收敛到同一参数簇；sample-rich bridge 暂退到第四顺位，让位给当前{stable_middle_basis_role_zh}。"
                    if stable_middle_distinct_repair_selected
                    else (
                    "near-live challenger 与收益 frontier 已收敛到同一参数簇；sample-rich bridge 暂退到第四顺位，保留为质量/样本补强线。"
                    if near_live_challenger_converged_with_yield and stable_middle_tradeoff_improves_bridge
                    else "样本丰富候选能补交易数，但不能牺牲窗口 Sharpe；下一轮围绕样本丰富且仍保留质量的桥接区域。"
                    )
                )
            ),
            "parameterFocus": [
                "both_bias_only",
                "take_profit_400_to_900",
                "stop_loss_325_to_600",
                "max_hold_12_to_36",
                "cooldown_4_to_12",
            ],
        })
    if density_metrics and float(density_metrics.get("sharpe") or 0.0) < 1.0:
        recommendations.append({
            "id": "reject_density_only_path",
            "label": "reject_density_only_path",
            "priority": 5,
            "basisStrategyId": density_best.get("strategyId"),
            "reasonZh": "单纯提高交易密度会显著拉低 Sharpe，暂不作为王牌升级方向。",
            "parameterFocus": [
                "do_not_force_cooldown_0_to_1",
                "do_not_force_max_hold_6_only",
            ],
        })

    recommendations.sort(key=lambda row: (_num(row.get("priority"), default=999), str(row.get("id") or "")))

    repair_strategy_candidates = [
        (stable_middle_basis_strategy_id, stable_middle_basis_label, stable_middle_basis_role_zh),
        (
            stable_middle_followup_refinement_micro_followup_best.get("strategyId"),
            "stable middle-third micro-followup",
            "第三条 distinct 稳定 fallback 路径",
        ),
        (
            stable_middle_followup_refinement_followup_best.get("strategyId"),
            "stable middle-third aggregate-stability refinement follow-up",
            "第三条 distinct 稳定 fallback 路径",
        ),
        (
            stable_middle_followup_refinement_best.get("strategyId"),
            "stable middle-third aggregate-stability refinement",
            "第三条 distinct 稳定 fallback 路径",
        ),
        (
            stable_middle_followup_best.get("strategyId"),
            (
                "stable middle-third aggregate-stability fallback"
                if stable_middle_followup_stability_fallback_available
                else "stable middle-third follow-up"
            ),
            (
                "第三条 distinct 稳定 fallback 路径"
                if stable_middle_followup_stability_fallback_available
                else "第三条 distinct 弱窗口修复路径"
            ),
        ),
        (
            stable_middle_tradeoff_best.get("strategyId"),
            "stable middle tradeoff repair line",
            "第三条 distinct 弱窗口修复路径",
        ),
        (
            stable_middle_bridge_best.get("strategyId"),
            "stable middle weak-window bridge",
            "第三条 distinct 弱窗口修复路径",
        ),
        (
            stable_middle_weak_window_best.get("strategyId"),
            "stable middle weak-window confirmation",
            "第三条 distinct 弱窗口修复路径",
        ),
        (
            stable_middle_repair_best.get("strategyId"),
            "stable middle-third focused repair",
            "第三条 distinct 弱窗口修复路径",
        ),
        (
            sample_rich_best.get("strategyId"),
            "sample-rich quality bridge fallback",
            "第三线质量/样本桥接路径",
        ),
        (
            quality_best.get("strategyId"),
            "quality repair fallback",
            "第三线质量稳健补强路径",
        ),
        (
            density_best.get("strategyId"),
            "density repair fallback",
            "第三线密度观察路径",
        ),
    ]
    focused_retest_order = _unique_strategy_id_order(
        most_stable.get("strategyId"),
        near_live_stability.get("strategyId"),
        *[row[0] for row in repair_strategy_candidates],
    )
    if len(focused_retest_order) < 3:
        focused_retest_order = _unique_strategy_id_order(
            *focused_retest_order,
            *[str(_dict(row).get("strategyId") or "").strip() for row in ranked],
        )
    focused_retest_order = focused_retest_order[:3]
    repair_strategy_id = (
        focused_retest_order[2]
        if len(focused_retest_order) > 2
        else stable_middle_basis_strategy_id
    )
    repair_line_label = stable_middle_basis_label
    repair_strategy_role_zh = stable_middle_basis_role_zh
    for candidate_strategy_id, candidate_label, candidate_role_zh in repair_strategy_candidates:
        if candidate_strategy_id and candidate_strategy_id == repair_strategy_id:
            repair_line_label = candidate_label
            repair_strategy_role_zh = candidate_role_zh
            break
    repair_strategy_action_role_zh = (
        "第三线弱窗口修复路径"
        if repair_strategy_role_zh == "第三条 distinct 弱窗口修复路径"
        else repair_strategy_role_zh
    )

    if stable_yield_converged_next_distinct_ready:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验当前 next distinct near-live contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，stable middle-third follow-up 先按锚点保守变体观察，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_signal_refinement_followup_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live signal refinement follow-up 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_signal_refinement_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live signal refinement 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_tempo_refinement_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live tempo refinement 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_middle_window_contender_micro_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live middle-window contender micro 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_stoploss_ladder_followup_micro_followup_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live stop-loss ladder follow-up micro-followup 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_stoploss_ladder_followup_micro_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live stop-loss ladder follow-up micro 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_stoploss_ladder_followup_improves_refinement:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live stop-loss ladder follow-up 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_stoploss_ladder_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live stop-loss ladder refinement 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_exit_refinement_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live exit refinement 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_middle_density_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live middle-density lift 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_middle_tradeoff_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 near-live middle tradeoff 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_yield_converged and near_live_cluster_refinement_improves_contender:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 converged-cluster refinement 找到的 next distinct contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif near_live_challenger_converged_with_yield and stable_middle_tradeoff_improves_bridge:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 next distinct near-live contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif near_live_challenger_converged_with_yield and stable_middle_distinct_repair_selected:
        next_action_zh = (
            "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
            "下一轮继续拿该收敛锚点做主线，优先复验 next distinct near-live contender，"
            f"再把 {repair_line_label} 提升为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif near_live_middle_window_improves_followup:
        next_action_zh = (
            "下一轮优先围绕 near-live middle-window follow-up 与当前高收益 leader 做局部复验；"
            f"再把 {repair_line_label} 作为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，stable middle-third follow-up 先按锚点保守变体观察，"
            "避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif near_live_refinement_improves_followup:
        next_action_zh = (
            "下一轮优先围绕 near-live stability refinement 与当前高收益 leader 做局部复验；"
            f"再把 {repair_line_label} 作为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，stable middle-third follow-up 先按锚点保守变体观察，"
            "避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif near_live_followup_improves_repair:
        next_action_zh = (
            "下一轮优先围绕 near-live stability follow-up 与当前高收益 leader 做局部复验；"
            f"再把 {repair_line_label} 作为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，stable middle-third follow-up 先按锚点保守变体观察，"
            "避免只靠缩短冷却/持仓来堆交易数。"
        )
    elif stable_middle_tradeoff_improves_baseline:
        next_action_zh = (
            "下一轮优先围绕更接近稳定落地的 near-live challenger 与当前高收益 leader 做局部复验；"
            f"再把 {repair_line_label} 作为{repair_strategy_action_role_zh}，"
            "sample-rich bridge 退到第四线质量/样本桥接，stable middle-third follow-up 先按锚点保守变体观察，"
            "避免只靠缩短冷却/持仓来堆交易数。"
        )
    else:
        next_action_zh = (
            "下一轮优先围绕更接近稳定落地的 near-live challenger 与当前高收益 leader 做局部复验；"
            "保留 sample-rich bridge 作为第四线，"
            f"{repair_line_label} 作为{repair_strategy_action_role_zh}，"
            "避免只靠缩短冷却/持仓来堆交易数。"
        )

    return {
        "status": "BTC_NEXT_FOCUSED_SEARCH_READY",
        "topStrategyId": most_stable.get("strategyId"),
        "nextDistinctStrategyId": near_live_stability.get("strategyId"),
        "repairStrategyId": repair_strategy_id,
        "repairStrategyLabelZh": repair_line_label,
        "repairStrategyRoleZh": repair_strategy_role_zh,
        "recommendedFocusedRetestOrder": focused_retest_order,
        "stabilityFirstTop3StrategyIds": focused_retest_order,
        "highYieldTradeoff": _tradeoff_summary(high_yield),
        "yieldLeaderConfirmationBestTradeoff": _tradeoff_summary(yield_leader_confirmation_best),
        "yieldLeaderConfirmationImprovesBaseline": yield_leader_confirmation_improves_baseline,
        "yieldLeaderConfirmationOutcomeZh": yield_leader_confirmation_outcome_zh,
        "mostStableTradeoff": _tradeoff_summary(most_stable),
        "nearLiveStabilityTradeoff": _tradeoff_summary(near_live_stability),
        "nearLiveStabilityRepairBestTradeoff": _tradeoff_summary(near_live_repair_best),
        "nearLiveStabilityRepairImprovesBaseline": near_live_repair_improves_baseline,
        "nearLiveStabilityRepairOutcomeZh": near_live_repair_outcome_zh,
        "nearLiveStabilityFollowupBestTradeoff": _tradeoff_summary(near_live_followup_best),
        "nearLiveStabilityFollowupBestStrategyId": near_live_followup_best.get("strategyId"),
        "nearLiveStabilityFollowupImprovesRepair": near_live_followup_improves_repair,
        "nearLiveStabilityFollowupOutcomeZh": near_live_followup_outcome_zh,
        "nearLiveStabilityRefinementBestTradeoff": _tradeoff_summary(near_live_refinement_best),
        "nearLiveStabilityRefinementBestStrategyId": near_live_refinement_best.get("strategyId"),
        "nearLiveStabilityRefinementImprovesFollowup": near_live_refinement_improves_followup,
        "nearLiveStabilityRefinementOutcomeZh": near_live_refinement_outcome_zh,
        "nearLiveMiddleWindowFollowupBestTradeoff": _tradeoff_summary(near_live_middle_window_best),
        "nearLiveMiddleWindowFollowupBestStrategyId": near_live_middle_window_best.get("strategyId"),
        "nearLiveMiddleWindowFollowupImprovesFollowup": near_live_middle_window_improves_followup,
        "nearLiveMiddleWindowFollowupOutcomeZh": near_live_middle_window_outcome_zh,
        "nearLiveSignalRefinementBestTradeoff": _tradeoff_summary(near_live_signal_refinement_best),
        "nearLiveSignalRefinementBestStrategyId": near_live_signal_refinement_best.get("strategyId"),
        "nearLiveSignalRefinementImprovesContender": near_live_signal_refinement_improves_contender,
        "nearLiveSignalRefinementOutcomeZh": near_live_signal_refinement_outcome_zh,
        "nearLiveSignalRefinementFollowupBestTradeoff": _tradeoff_summary(near_live_signal_refinement_followup_best),
        "nearLiveSignalRefinementFollowupBestStrategyId": near_live_signal_refinement_followup_best.get("strategyId"),
        "nearLiveSignalRefinementFollowupImprovesContender": near_live_signal_refinement_followup_improves_contender,
        "nearLiveSignalRefinementFollowupOutcomeZh": near_live_signal_refinement_followup_outcome_zh,
        "nearLiveHighYieldNeighborhoodBestTradeoff": _tradeoff_summary(near_live_high_yield_neighborhood_best),
        "nearLiveHighYieldNeighborhoodBestStrategyId": near_live_high_yield_neighborhood_best.get("strategyId"),
        "nearLiveHighYieldNeighborhoodImprovesAnchor": near_live_high_yield_neighborhood_improves_anchor,
        "nearLiveHighYieldNeighborhoodOutcomeZh": near_live_high_yield_neighborhood_outcome_zh,
        "nearLiveHighYieldNeighborhoodFollowupBestTradeoff": _tradeoff_summary(
            near_live_high_yield_neighborhood_followup_best
        ),
        "nearLiveHighYieldNeighborhoodFollowupBestStrategyId": (
            near_live_high_yield_neighborhood_followup_best.get("strategyId")
        ),
        "nearLiveHighYieldNeighborhoodFollowupImprovesNeighborhood": (
            near_live_high_yield_neighborhood_followup_improves_neighborhood
        ),
        "nearLiveHighYieldNeighborhoodFollowupOutcomeZh": (
            near_live_high_yield_neighborhood_followup_outcome_zh
        ),
        "nearLiveHighYieldNeighborhoodFollowupMicroBestTradeoff": _tradeoff_summary(
            near_live_high_yield_neighborhood_followup_micro_best
        ),
        "nearLiveHighYieldNeighborhoodFollowupMicroBestStrategyId": (
            near_live_high_yield_neighborhood_followup_micro_best.get("strategyId")
        ),
        "nearLiveHighYieldNeighborhoodFollowupMicroImprovesFollowup": (
            near_live_high_yield_neighborhood_followup_micro_improves_followup
        ),
        "nearLiveHighYieldNeighborhoodFollowupMicroOutcomeZh": (
            near_live_high_yield_neighborhood_followup_micro_outcome_zh
        ),
        "nearLiveHighYieldNeighborhoodFollowupMicroFollowupBestTradeoff": _tradeoff_summary(
            near_live_high_yield_neighborhood_followup_micro_followup_best
        ),
        "nearLiveHighYieldNeighborhoodFollowupMicroFollowupBestStrategyId": (
            near_live_high_yield_neighborhood_followup_micro_followup_best.get("strategyId")
        ),
        "nearLiveHighYieldNeighborhoodFollowupMicroFollowupImprovesMicro": (
            near_live_high_yield_neighborhood_followup_micro_followup_improves_micro
        ),
        "nearLiveHighYieldNeighborhoodFollowupMicroFollowupOutcomeZh": (
            near_live_high_yield_neighborhood_followup_micro_followup_outcome_zh
        ),
        "nearLiveClusterRefinementBestTradeoff": _tradeoff_summary(near_live_cluster_refinement_best),
        "nearLiveClusterRefinementBestStrategyId": near_live_cluster_refinement_best.get("strategyId"),
        "nearLiveClusterRefinementImprovesContender": near_live_cluster_refinement_improves_contender,
        "nearLiveClusterRefinementOutcomeZh": near_live_cluster_refinement_outcome_zh,
        "nearLiveTempoRefinementBestTradeoff": _tradeoff_summary(near_live_tempo_refinement_best),
        "nearLiveTempoRefinementBestStrategyId": near_live_tempo_refinement_best.get("strategyId"),
        "nearLiveTempoRefinementImprovesContender": near_live_tempo_refinement_improves_contender,
        "nearLiveTempoRefinementOutcomeZh": near_live_tempo_refinement_outcome_zh,
        "nearLiveMiddleWindowContenderMicroBestTradeoff": _tradeoff_summary(
            near_live_middle_window_contender_micro_best
        ),
        "nearLiveMiddleWindowContenderMicroBestStrategyId": (
            near_live_middle_window_contender_micro_best.get("strategyId")
        ),
        "nearLiveMiddleWindowContenderMicroImprovesContender": (
            near_live_middle_window_contender_micro_improves_contender
        ),
        "nearLiveMiddleWindowContenderMicroOutcomeZh": (
            near_live_middle_window_contender_micro_outcome_zh
        ),
        "nearLiveStoplossLadderRefinementBestTradeoff": _tradeoff_summary(near_live_stoploss_ladder_best),
        "nearLiveStoplossLadderRefinementBestStrategyId": near_live_stoploss_ladder_best.get("strategyId"),
        "nearLiveStoplossLadderRefinementImprovesContender": near_live_stoploss_ladder_improves_contender,
        "nearLiveStoplossLadderRefinementOutcomeZh": near_live_stoploss_ladder_outcome_zh,
        "nearLiveStoplossLadderFollowupBestTradeoff": _tradeoff_summary(near_live_stoploss_ladder_followup_best),
        "nearLiveStoplossLadderFollowupBestStrategyId": near_live_stoploss_ladder_followup_best.get("strategyId"),
        "nearLiveStoplossLadderFollowupImprovesRefinement": near_live_stoploss_ladder_followup_improves_refinement,
        "nearLiveStoplossLadderFollowupOutcomeZh": near_live_stoploss_ladder_followup_outcome_zh,
        "nearLiveStoplossLadderFollowupMicroBestTradeoff": _tradeoff_summary(
            near_live_stoploss_ladder_followup_micro_best
        ),
        "nearLiveStoplossLadderFollowupMicroBestStrategyId": near_live_stoploss_ladder_followup_micro_best.get("strategyId"),
        "nearLiveStoplossLadderFollowupMicroImprovesRefinement": near_live_stoploss_ladder_followup_micro_improves_refinement,
        "nearLiveStoplossLadderFollowupMicroImprovesContender": near_live_stoploss_ladder_followup_micro_improves_contender,
        "nearLiveStoplossLadderFollowupMicroOutcomeZh": near_live_stoploss_ladder_followup_micro_outcome_zh,
        "nearLiveStoplossLadderFollowupMicroFollowupBestTradeoff": _tradeoff_summary(
            near_live_stoploss_ladder_followup_micro_followup_best
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId": (
            near_live_stoploss_ladder_followup_micro_followup_best.get("strategyId")
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro": (
            near_live_stoploss_ladder_followup_micro_followup_improves_micro
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupImprovesContender": (
            near_live_stoploss_ladder_followup_micro_followup_improves_contender
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh": (
            near_live_stoploss_ladder_followup_micro_followup_outcome_zh
        ),
        "nearLiveExitRefinementBestTradeoff": _tradeoff_summary(near_live_exit_refinement_best),
        "nearLiveExitRefinementBestStrategyId": near_live_exit_refinement_best.get("strategyId"),
        "nearLiveExitRefinementImprovesContender": near_live_exit_refinement_improves_contender,
        "nearLiveExitRefinementOutcomeZh": near_live_exit_refinement_outcome_zh,
        "nearLiveMiddleTradeoffBestTradeoff": _tradeoff_summary(near_live_middle_tradeoff_best),
        "nearLiveMiddleTradeoffBestStrategyId": near_live_middle_tradeoff_best.get("strategyId"),
        "nearLiveMiddleTradeoffImprovesContender": near_live_middle_tradeoff_improves_contender,
        "nearLiveMiddleTradeoffOutcomeZh": near_live_middle_tradeoff_outcome_zh,
        "nearLiveMiddleDensityLiftBestTradeoff": _tradeoff_summary(near_live_middle_density_best),
        "nearLiveMiddleDensityLiftBestStrategyId": near_live_middle_density_best.get("strategyId"),
        "nearLiveMiddleDensityLiftImprovesContender": near_live_middle_density_improves_contender,
        "nearLiveMiddleDensityLiftOutcomeZh": near_live_middle_density_outcome_zh,
        "nearLiveChallengerConvergedWithYieldFrontier": near_live_challenger_converged_with_yield,
        "stableMiddleThirdRepairBestTradeoff": _tradeoff_summary(stable_middle_repair_best),
        "stableMiddleThirdRepairImprovesBaseline": stable_middle_repair_improves_baseline,
        "stableMiddleThirdRepairOutcomeZh": stable_middle_repair_outcome_zh,
        "stableMiddleThirdFollowupBestTradeoff": _tradeoff_summary(stable_middle_followup_best),
        "stableMiddleThirdFollowupImprovesAggregate": stable_middle_followup_improves_aggregate,
        "stableMiddleThirdFollowupImprovesWeakWindow": stable_middle_followup_improves_weak_window,
        "stableMiddleThirdFollowupImprovesRepair": stable_middle_followup_improves_repair,
        "stableMiddleThirdFollowupOutcomeZh": stable_middle_followup_outcome_zh,
        "stableMiddleThirdFollowupRefinementBestTradeoff": _tradeoff_summary(stable_middle_followup_refinement_best),
        "stableMiddleThirdFollowupRefinementBestStrategyId": stable_middle_followup_refinement_best.get("strategyId"),
        "stableMiddleThirdFollowupRefinementImprovesFollowup": stable_middle_followup_refinement_improves_followup,
        "stableMiddleThirdFollowupRefinementOutcomeZh": stable_middle_followup_refinement_outcome_zh,
        "stableMiddleThirdFollowupRefinementFollowupBestTradeoff": _tradeoff_summary(stable_middle_followup_refinement_followup_best),
        "stableMiddleThirdFollowupRefinementFollowupBestStrategyId": stable_middle_followup_refinement_followup_best.get("strategyId"),
        "stableMiddleThirdFollowupRefinementFollowupImprovesRefinement": stable_middle_followup_refinement_followup_improves_refinement,
        "stableMiddleThirdFollowupRefinementFollowupOutcomeZh": stable_middle_followup_refinement_followup_outcome_zh,
        "stableMiddleThirdFollowupRefinementMicroBestTradeoff": _tradeoff_summary(stable_middle_followup_refinement_micro_best),
        "stableMiddleThirdFollowupRefinementMicroBestStrategyId": stable_middle_followup_refinement_micro_best.get("strategyId"),
        "stableMiddleThirdFollowupRefinementMicroImprovesRefinement": stable_middle_followup_refinement_micro_improves_refinement,
        "stableMiddleThirdFollowupRefinementMicroOutcomeZh": stable_middle_followup_refinement_micro_outcome_zh,
        "stableMiddleThirdFollowupRefinementMicroFollowupBestTradeoff": _tradeoff_summary(
            stable_middle_followup_refinement_micro_followup_best
        ),
        "stableMiddleThirdFollowupRefinementMicroFollowupBestStrategyId": (
            stable_middle_followup_refinement_micro_followup_best.get("strategyId")
        ),
        "stableMiddleThirdFollowupRefinementMicroFollowupImprovesMicro": (
            stable_middle_followup_refinement_micro_followup_improves_micro
        ),
        "stableMiddleThirdFollowupRefinementMicroFollowupImprovesRefinement": (
            stable_middle_followup_refinement_micro_followup_improves_refinement
        ),
        "stableMiddleThirdFollowupRefinementMicroFollowupOutcomeZh": (
            stable_middle_followup_refinement_micro_followup_outcome_zh
        ),
        "stableMiddleWeakWindowConfirmationBestTradeoff": _tradeoff_summary(stable_middle_weak_window_best),
        "stableMiddleWeakWindowConfirmationImprovesBaseline": stable_middle_weak_window_improves_baseline,
        "stableMiddleWeakWindowConfirmationOutcomeZh": stable_middle_weak_window_outcome_zh,
        "stableMiddleWeakWindowBridgeBestTradeoff": _tradeoff_summary(stable_middle_bridge_best),
        "stableMiddleWeakWindowBridgeImprovesAggregate": stable_middle_bridge_improves_aggregate,
        "stableMiddleWeakWindowBridgeImprovesWeakWindow": stable_middle_bridge_improves_weak_window,
        "stableMiddleWeakWindowBridgeImprovesBaseline": stable_middle_bridge_improves_baseline,
        "stableMiddleWeakWindowBridgeOutcomeZh": stable_middle_bridge_outcome_zh,
        "stableMiddleTradeoffFollowupBestTradeoff": _tradeoff_summary(stable_middle_tradeoff_best),
        "stableMiddleTradeoffFollowupBestStrategyId": stable_middle_tradeoff_best.get("strategyId"),
        "stableMiddleTradeoffFollowupImprovesBridge": stable_middle_tradeoff_improves_bridge,
        "stableMiddleTradeoffFollowupImprovesWeakWindow": stable_middle_tradeoff_improves_weak_window,
        "stableMiddleTradeoffFollowupImprovesBaseline": stable_middle_tradeoff_improves_baseline,
        "stableMiddleTradeoffFollowupOutcomeZh": stable_middle_tradeoff_outcome_zh,
        "qualityRepairTradeoff": _tradeoff_summary(quality_best),
        "sampleRichQualityTradeoff": _tradeoff_summary(sample_rich_best),
        "densityRepairTradeoff": _tradeoff_summary(density_best),
        "windowFailureProfiles": [
            _window_failure_profile(row)
            for row in top_candidates[:4]
            if row
        ],
        "recommendations": recommendations,
        "nextActionZh": next_action_zh,
        "safety": SAFETY,
    }


def build_btc_strategy_scan_report(
    runtime_dir: Path,
    *,
    max_configs: int = 512,
    top_n: int = 12,
    write: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    max_configs = max(1, int(max_configs))
    top_n = max(1, int(top_n))
    generated_at = _now_iso()
    csv_path = next((path for path in _rate_csv_candidates(runtime_dir) if "BTCUSD" in path.name.upper()), None)
    if not csv_path:
        report = {
            "ok": False,
            "schema": REPORT_SCHEMA,
            "generatedAt": generated_at,
            "generatedAtIso": generated_at,
            "status": "BTC_SCAN_RATES_MISSING",
            "blockers": ["BTC_RATES_CSV_MISSING"],
            "safety": SAFETY,
            "reportPath": str(runtime_dir / REPORT_PATH),
        }
        if write:
            _write_json(runtime_dir / REPORT_PATH, report)
        return report
    rows = _read_rate_rows(csv_path, limit=50_000)
    specs = _contract_specs(runtime_dir)
    spec = specs.get("BTCUSD") or specs.get("#BTCUSD")
    if not spec:
        report = {
            "ok": False,
            "schema": REPORT_SCHEMA,
            "generatedAt": generated_at,
            "generatedAtIso": generated_at,
            "status": "BTC_SCAN_CONTRACT_SPEC_MISSING",
            "csvPath": str(csv_path),
            "barCount": len(rows),
            "blockers": ["BTC_CONTRACT_SPEC_MISSING"],
            "safety": SAFETY,
            "reportPath": str(runtime_dir / REPORT_PATH),
        }
        if write:
            _write_json(runtime_dir / REPORT_PATH, report)
        return report

    configs = _focused_scan_configs(max_configs)
    retests = [_btc_candidate_retest(rows, spec, config) for config in configs]
    ranked = _ranked_btc_retests(retests)
    top = ranked[0] if ranked else {}
    current = _read_json(runtime_dir / "agent" / "QuantGod_ChampionRetestReport.json")
    current_crypto = current.get("cryptoChampion") if isinstance(current.get("cryptoChampion"), dict) else {}
    current_valid = int(current_crypto.get("validWindowCount") or 0)
    top_valid = int(top.get("validWindowCount") or 0)
    top_major_fail = int(top.get("majorWindowFailureCount") or 0)
    current_major_fail = int(current_crypto.get("majorWindowFailureCount") or 0)
    improvement = bool(
        top
        and (
            top_valid > current_valid
            or (top_valid == current_valid and top_major_fail < current_major_fail)
        )
    )
    diagnostics = _repair_diagnostics(retests)
    next_focused_search_plan = _next_focused_search_plan(ranked, diagnostics)
    most_stable_tradeoff = _dict(next_focused_search_plan.get("mostStableTradeoff"))
    near_live_stability_tradeoff = _dict(next_focused_search_plan.get("nearLiveStabilityTradeoff"))
    report = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAt": generated_at,
        "generatedAtIso": generated_at,
        "status": "BTC_SCAN_IMPROVEMENT_FOUND" if improvement else "BTC_SCAN_COMPLETE_NO_CLEAR_UPGRADE",
        "csvPath": str(csv_path),
        "barCount": len(rows),
        "scannedConfigCount": len(configs),
        "rankedCandidateCount": len(ranked),
        "currentChampion": {
            "strategyId": current_crypto.get("strategyId"),
            "validWindowCount": current_crypto.get("validWindowCount"),
            "windowCount": current_crypto.get("windowCount"),
            "majorWindowFailureCount": current_crypto.get("majorWindowFailureCount"),
            "blockers": current_crypto.get("blockers", []),
        },
        "topCandidateStrategyId": top.get("strategyId") if isinstance(top, dict) else None,
        "topRecommendation": _compact_retest(top) if top else {},
        "mostStableTradeoff": most_stable_tradeoff,
        "currentHighestYieldTradeoff": _dict(next_focused_search_plan.get("highYieldTradeoff")),
        "recommendedFocusedRetestOrder": list(next_focused_search_plan.get("recommendedFocusedRetestOrder") or []),
        "topCandidate": _compact_retest(top) if top else {},
        "topCandidates": [_compact_retest(row) for row in ranked[:top_n]],
        "repairDiagnostics": diagnostics,
        "nextFocusedSearchPlan": next_focused_search_plan,
        "nextActionZh": (
            "将 topCandidate 纳入 ChampionRetest 正式候选池，再刷新 Ace/Promotion。"
            if improvement
            else next_focused_search_plan.get("nextActionZh")
            or "继续扩大 focused scan 或补更长 CopyRates；当前扫描未发现明确超过现任 BTC 王牌的候选。"
        ),
        "safety": SAFETY,
        "reportPath": str(runtime_dir / REPORT_PATH),
    }
    if write:
        _write_json(runtime_dir / REPORT_PATH, report)
    return report


def read_btc_strategy_scan_report(runtime_dir: Path) -> dict[str, Any]:
    report = _read_json(Path(runtime_dir) / REPORT_PATH)
    if report and not report.get("generatedAtIso") and report.get("generatedAt"):
        report["generatedAtIso"] = report.get("generatedAt")
    return report if report else build_btc_strategy_scan_report(Path(runtime_dir), write=False)
