"""Champion retest report for QuantGod strategy candidates.

The report is intentionally read-only. It compares the current best USDJPY GA
candidate with the current HFM BTC crypto shadow candidate, and records the next
safe validation action without writing live presets or order files.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.hfm_crypto_cfd.rates_export import (
        MIN_BTC_BARS,
        SIM_INITIAL_EQUITY_USD,
        SIM_TARGET_NOTIONAL_USD,
        _align_lot,
        _contract_specs,
        _ema,
        _rate_csv_candidates,
        _read_rate_rows,
        _safe_float,
    )
    from tools.hfm_crypto_cfd.simulation_profile import simulation_metric_blockers
except ModuleNotFoundError:  # pragma: no cover
    from hfm_crypto_cfd.rates_export import (
        MIN_BTC_BARS,
        SIM_INITIAL_EQUITY_USD,
        SIM_TARGET_NOTIONAL_USD,
        _align_lot,
        _contract_specs,
        _ema,
        _rate_csv_candidates,
        _read_rate_rows,
        _safe_float,
    )
    from hfm_crypto_cfd.simulation_profile import simulation_metric_blockers


REPORT_SCHEMA = "quantgod.champion_retest.report.v1"
REPORT_PATH = Path("agent") / "QuantGod_ChampionRetestReport.json"
DEFAULT_FOREX_CHAMPION_SEED_ID = "GA-USDJPY-G0077-C0002"
BTC_CHAMPION_STRATEGY_ID = "hfm_crypto_btc_regime_stability_shadow_v1"
BTC_PROFILE_CONFIGS: list[dict[str, Any]] = [
    {
        "strategyId": "hfm_crypto_btc_copyrates_ema_shadow_v1",
        "strategyName": "BTCUSD EMA 12/36 crossover shadow simulation",
        "strategyFamily": "ema_crossover",
        "parameters": {"fastSpan": 12, "slowSpan": 36},
    },
    {
        "strategyId": "hfm_crypto_btc_regime_stability_shadow_v1",
        "strategyName": "BTCUSD EMA-slope short regime stability shadow simulation",
        "strategyFamily": "ema_slope_regime",
        "parameters": {
            "bias": "short",
            "emaSpan": 48,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 200.0,
            "takeProfitPriceMove": 1500.0,
            "stopLossPriceMove": 500.0,
            "maxHoldBars": 24,
            "cooldownBars": 8,
        },
    },
    {
        "strategyId": "hfm_crypto_btc_regime_bidirectional_shadow_v1",
        "strategyName": "BTCUSD EMA-slope bidirectional regime shadow simulation",
        "strategyFamily": "ema_slope_regime",
        "parameters": {
            "bias": "both",
            "emaSpan": 48,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 50.0,
            "takeProfitPriceMove": 600.0,
            "stopLossPriceMove": 1200.0,
            "maxHoldBars": 72,
            "cooldownBars": 8,
        },
    },
    {
        "strategyId": "hfm_crypto_btc_regime_balanced_window_shadow_v1",
        "strategyName": "BTCUSD EMA-slope balanced-window shadow simulation",
        "strategyFamily": "ema_slope_regime",
        "parameters": {
            "bias": "both",
            "emaSpan": 48,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 100.0,
            "takeProfitPriceMove": 600.0,
            "stopLossPriceMove": 400.0,
            "maxHoldBars": 48,
            "cooldownBars": 8,
        },
    },
    {
        "strategyId": "hfm_crypto_btc_regime_short_yield_shadow_v1",
        "strategyName": "BTCUSD EMA-slope short yield shadow simulation",
        "strategyFamily": "ema_slope_regime",
        "parameters": {
            "bias": "short",
            "emaSpan": 48,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 300.0,
            "takeProfitPriceMove": 600.0,
            "stopLossPriceMove": 1200.0,
            "maxHoldBars": 96,
            "cooldownBars": 8,
        },
    },
    {
        "strategyId": "hfm_crypto_btc_regime_sample_rich_shadow_v1",
        "strategyName": "BTCUSD EMA-slope sample-rich regime shadow simulation",
        "strategyFamily": "ema_slope_regime",
        "parameters": {
            "bias": "both",
            "emaSpan": 48,
            "slopeLookbackBars": 144,
            "slopeThresholdPrice": 150.0,
            "takeProfitPriceMove": 1500.0,
            "stopLossPriceMove": 800.0,
            "maxHoldBars": 24,
            "cooldownBars": 8,
        },
    },
]
BTC_SCAN_REPORT_PATH = Path("agent") / "QuantGod_BtcStrategyScanReport.json"

SAFETY = {
    "readOnly": True,
    "shadowOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "livePresetMutationAllowed": False,
    "walletAuthorizationAllowed": False,
    "hyperliquidExecutionAllowed": False,
    "mossExecutionAllowed": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").replace(",", "").strip())
        except ValueError:
            return default
    return default


def _selected_forex_seed_id(runtime_dir: Path) -> str:
    scout = _read_json(runtime_dir / "agent" / "QuantGod_AceStrategyScout.json")
    top_forex = scout.get("topQualifiedForex") if isinstance(scout.get("topQualifiedForex"), dict) else {}
    seed_id = str(top_forex.get("seedId") or "").strip()
    return seed_id or DEFAULT_FOREX_CHAMPION_SEED_ID


def _forex_contender_review(runtime_dir: Path) -> dict[str, Any]:
    scout = _read_json(runtime_dir / "agent" / "QuantGod_AceStrategyScout.json")
    review = scout.get("forexContenderReview")
    if isinstance(review, dict) and review:
        return review
    return {
        "schema": "quantgod.ace_strategy_scout.forex_contender_review.v1",
        "status": "WAITING_ACE_FOREX_CONTENDER_REVIEW",
        "statusZh": "等待 Ace 外汇候选复核",
        "contenderCount": 0,
        "tiedTopCount": 0,
        "requiresParallelTesterForward": False,
        "contenders": [],
        "safety": SAFETY,
    }


def _effective_sample_count(backtest: dict[str, Any], summary: dict[str, Any], walk_forward: dict[str, Any]) -> int:
    backtest_trades = int(_num(backtest.get("tradeCount")))
    wf_samples = int(_num(summary.get("sampleCount")))
    segment_trades = sum(
        int(_num(segment.get("tradeCount")))
        for segment in walk_forward.get("segments", [])
        if isinstance(segment, dict)
    )
    return max(backtest_trades, wf_samples, segment_trades)


def _forex_champion(runtime_dir: Path) -> dict[str, Any]:
    payload = _read_json(runtime_dir / "ga" / "QuantGod_GAEliteStrategies.json")
    elites = payload.get("elites") if isinstance(payload.get("elites"), list) else []
    selected_seed_id = _selected_forex_seed_id(runtime_dir)
    champion = next((row for row in elites if row.get("seedId") == selected_seed_id), {})
    if not champion:
        return {
            "status": "FOREX_CHAMPION_MISSING",
            "seedId": selected_seed_id,
            "blockers": ["FOREX_CHAMPION_METRICS_MISSING"],
            "safety": SAFETY,
        }
    breakdown = champion.get("fitnessBreakdown") or {}
    backtest = breakdown.get("strategyBacktest") or {}
    walk_forward = breakdown.get("walkForward") or {}
    summary = walk_forward.get("summary") or {}
    segments = []
    blockers: list[str] = []
    for segment in walk_forward.get("segments") or []:
        net_r = _num(segment.get("netR"))
        profit_factor = _num(segment.get("profitFactor"))
        trade_count = int(_num(segment.get("tradeCount")))
        segment_blockers = []
        if net_r <= 0:
            segment_blockers.append("SEGMENT_NET_R_NOT_POSITIVE")
        if profit_factor < 1.05:
            segment_blockers.append("SEGMENT_PROFIT_FACTOR_LT_1_05")
        if trade_count < 3:
            segment_blockers.append("SEGMENT_LOW_SAMPLE_LT_3")
        segments.append(
            {
                "segment": segment.get("segment"),
                "start": segment.get("start"),
                "end": segment.get("end"),
                "netR": round(net_r, 4),
                "profitFactor": round(profit_factor, 4),
                "sharpe": round(_num(segment.get("sharpe")), 4),
                "maxDrawdownR": round(_num(segment.get("maxDrawdownR")), 4),
                "tradeCount": trade_count,
                "lossStreak": int(_num(segment.get("lossStreak"))),
                "blockers": segment_blockers,
            }
        )
        blockers.extend(segment_blockers)
    total_trades = int(_num(backtest.get("tradeCount")))
    effective_samples = _effective_sample_count(backtest, summary, walk_forward)
    stability = _num(summary.get("stabilityScore"))
    if effective_samples < 20:
        blockers.append("FOREX_TRADE_COUNT_LT_20")
    if stability < 0.8:
        blockers.append("FOREX_STABILITY_LT_0_8")
    if summary.get("promotionAllowed") is False:
        blockers.append(summary.get("blockerCode") or "FOREX_WALK_FORWARD_BLOCKED")
    return {
        "status": "FOREX_CHAMPION_RETEST_PASS" if not blockers else "FOREX_CHAMPION_RETEST_BLOCKED",
        "seedId": champion.get("seedId"),
        "strategyId": champion.get("strategyId"),
        "fitness": round(_num(champion.get("fitness")), 4),
        "backtest": {
            "netR": round(_num(backtest.get("netR")), 4),
            "profitFactor": round(_num(backtest.get("profitFactor")), 4),
            "sharpe": round(_num(backtest.get("sharpe")), 4),
            "maxDrawdownR": round(_num(backtest.get("maxDrawdownR")), 4),
            "tradeCount": total_trades,
            "effectiveSampleCount": effective_samples,
            "evidenceQuality": backtest.get("evidenceQuality"),
        },
        "walkForward": {
            "sampleCount": int(_num(summary.get("sampleCount"))),
            "stabilityScore": round(stability, 4),
            "trainNetR": round(_num(summary.get("trainNetR")), 4),
            "validationNetR": round(_num(summary.get("validationNetR")), 4),
            "forwardNetR": round(_num(summary.get("forwardNetR")), 4),
            "maxDrawdownR": round(_num(summary.get("maxDrawdownR")), 4),
            "promotionAllowed": bool(summary.get("promotionAllowed")),
            "evidenceQuality": summary.get("evidenceQuality"),
            "segments": segments,
        },
        "blockers": sorted(set(blockers)),
        "nextActionZh": "进入隔离 MT5 Strategy Tester / forward 复验；本报告不写 preset、不下单。",
        "safety": SAFETY,
    }


def _summarize_trade_pnls(trade_pnls: list[float], strategy_id: str) -> dict[str, Any]:
    pnl_usd = round(sum(trade_pnls), 4)
    trade_count = len(trade_pnls)
    equity = SIM_INITIAL_EQUITY_USD
    peak = equity
    max_drawdown_pct = 0.0
    for item in trade_pnls:
        equity += item
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100.0)
    if trade_count >= 2:
        mean = sum(trade_pnls) / trade_count
        variance = sum((item - mean) ** 2 for item in trade_pnls) / (trade_count - 1)
        stdev = math.sqrt(variance)
        sharpe = (mean / stdev) * math.sqrt(trade_count) if stdev > 0 else (9.99 if mean > 0 else 0.0)
    else:
        sharpe = 0.0
    return {
        "agentId": strategy_id,
        "symbol": "BTCUSD",
        "pnlUsd": pnl_usd,
        "pnl": pnl_usd,
        "roiPct": round((pnl_usd / SIM_INITIAL_EQUITY_USD) * 100.0, 4),
        "sharpe": round(sharpe, 4),
        "maxDrawdownPct": round(max_drawdown_pct, 4),
        "tradeCount": trade_count,
        "liquidationCount": 0,
    }


def _btc_lot(rows: list[dict[str, Any]], spec: dict[str, Any]) -> tuple[float, float, float]:
    contract_size = _safe_float(spec.get("contractSize")) or 1.0
    min_lot = _safe_float(spec.get("minLot")) or 0.01
    lot_step = _safe_float(spec.get("lotStep")) or min_lot
    max_lot = _safe_float(spec.get("maxLot")) or min_lot
    first_price = float(rows[0]["close"])
    lot = _align_lot(SIM_TARGET_NOTIONAL_USD / max(first_price * contract_size, 1e-9), min_lot, lot_step, max_lot)
    point = _safe_float(spec.get("tickSize")) or 0.01
    return contract_size, point, lot


def _close_btc_pnl(
    *,
    position: int,
    entry_price: float,
    price: float,
    spread_points: float,
    contract_size: float,
    point: float,
    lot: float,
) -> float:
    spread_price = max(spread_points, 0.0) * point
    gross = (price - entry_price) * position * contract_size * lot
    cost = spread_price * contract_size * lot
    return gross - cost


def _run_btc_ema_cross_strategy(rows: list[dict[str, Any]], spec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    contract_size, point, lot = _btc_lot(rows, spec)
    parameters = config["parameters"]
    fast_span = int(parameters["fastSpan"])
    slow_span = int(parameters["slowSpan"])
    fast: float | None = None
    slow: float | None = None
    position = 0
    entry_price = 0.0
    trade_pnls: list[float] = []
    warmup = max(48, slow_span)
    for index, row in enumerate(rows):
        price = float(row["close"])
        fast = _ema(fast, price, fast_span)
        slow = _ema(slow, price, slow_span)
        if index < warmup:
            continue
        desired = 1 if fast > slow else -1 if fast < slow else 0
        if desired != position:
            if position != 0:
                trade_pnls.append(
                    _close_btc_pnl(
                        position=position,
                        entry_price=entry_price,
                        price=price,
                        spread_points=float(row.get("spread") or 0.0),
                        contract_size=contract_size,
                        point=point,
                        lot=lot,
                    )
                )
            position = desired
            entry_price = price if desired != 0 else 0.0
    if position != 0:
        trade_pnls.append(
            _close_btc_pnl(
                position=position,
                entry_price=entry_price,
                price=float(rows[-1]["close"]),
                spread_points=float(rows[-1].get("spread") or 0.0),
                contract_size=contract_size,
                point=point,
                lot=lot,
            )
        )
    strategy_id = str(config["strategyId"])
    return {
        "strategyId": strategy_id,
        "strategyName": config["strategyName"],
        "strategyFamily": config["strategyFamily"],
        "parameters": {**parameters, "lot": lot},
        "metrics": _summarize_trade_pnls(trade_pnls, strategy_id),
        "tradePnls": trade_pnls,
    }


def _run_btc_regime_strategy(rows: list[dict[str, Any]], spec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    contract_size, point, lot = _btc_lot(rows, spec)
    parameters = config["parameters"]
    bias = str(parameters["bias"])
    ema_span = int(parameters["emaSpan"])
    slope_lookback = int(parameters["slopeLookbackBars"])
    slope_threshold = float(parameters["slopeThresholdPrice"])
    take_profit_move = float(parameters["takeProfitPriceMove"])
    stop_loss_move = float(parameters["stopLossPriceMove"])
    max_hold_bars = int(parameters["maxHoldBars"])
    cooldown_bars = int(parameters["cooldownBars"])
    ema_values: list[float] = []
    ema_value: float | None = None
    for row in rows:
        ema_value = _ema(ema_value, float(row["close"]), ema_span)
        ema_values.append(ema_value)
    position = 0
    entry_price = 0.0
    entry_index = 0
    last_change_index = -10**9
    trade_pnls: list[float] = []
    warmup = max(ema_span, slope_lookback)
    for index, row in enumerate(rows):
        if index < warmup:
            continue
        price = float(row["close"])
        slope = ema_values[index] - ema_values[index - slope_lookback]
        regime = 1 if slope > slope_threshold else -1 if slope < -slope_threshold else 0
        if bias == "short":
            regime = -1 if regime < 0 else 0
        elif bias == "long":
            regime = 1 if regime > 0 else 0
        desired = position
        if position != 0:
            move = (price - entry_price) * position
            if (
                move >= take_profit_move
                or move <= -stop_loss_move
                or index - entry_index >= max_hold_bars
                or regime != position
            ):
                desired = 0
        elif regime != 0 and index - last_change_index >= cooldown_bars:
            desired = regime
        if desired != position:
            if position != 0:
                trade_pnls.append(
                    _close_btc_pnl(
                        position=position,
                        entry_price=entry_price,
                        price=price,
                        spread_points=float(row.get("spread") or 0.0),
                        contract_size=contract_size,
                        point=point,
                        lot=lot,
                    )
                )
            position = desired
            entry_price = price if desired != 0 else 0.0
            entry_index = index
            last_change_index = index
    if position != 0:
        trade_pnls.append(
            _close_btc_pnl(
                position=position,
                entry_price=entry_price,
                price=float(rows[-1]["close"]),
                spread_points=float(rows[-1].get("spread") or 0.0),
                contract_size=contract_size,
                point=point,
                lot=lot,
            )
        )
    strategy_id = str(config["strategyId"])
    metrics = _summarize_trade_pnls(trade_pnls, strategy_id)
    return {
        "strategyId": strategy_id,
        "strategyName": config["strategyName"],
        "strategyFamily": config["strategyFamily"],
        "parameters": {**parameters, "lot": lot},
        "metrics": metrics,
        "tradePnls": trade_pnls,
    }


def _run_btc_strategy(rows: list[dict[str, Any]], spec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if config.get("strategyFamily") == "ema_crossover":
        return _run_btc_ema_cross_strategy(rows, spec, config)
    return _run_btc_regime_strategy(rows, spec, config)


def _window_rows(rows: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    count = len(rows)
    if count < MIN_BTC_BARS:
        return []
    windows: list[tuple[str, list[dict[str, Any]]]] = [("full", rows)]
    half = count // 2
    if half >= MIN_BTC_BARS:
        windows.extend([("first_half", rows[:half]), ("second_half", rows[half:])])
    third = count // 3
    if third >= MIN_BTC_BARS:
        windows.extend([
            ("first_third", rows[:third]),
            ("middle_third", rows[third:third * 2]),
            ("last_third", rows[third * 2:]),
        ])
    return windows


def _btc_candidate_retest(rows: list[dict[str, Any]], spec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    windows = []
    blockers: list[str] = []
    for name, subset in _window_rows(rows):
        result = _run_btc_strategy(subset, spec, config)
        metrics = result["metrics"]
        metric_blockers = [item.get("code") for item in simulation_metric_blockers(metrics, True)]
        if name != "full":
            if metrics["tradeCount"] < 3:
                metric_blockers.append("WINDOW_LOW_SAMPLE_LT_3")
            if metrics["pnlUsd"] <= 0:
                metric_blockers.append("WINDOW_PNL_NOT_POSITIVE")
        windows.append(
            {
                "window": name,
                "start": subset[0].get("timestamp") or subset[0].get("epoch"),
                "end": subset[-1].get("timestamp") or subset[-1].get("epoch"),
                "barCount": len(subset),
                "metrics": metrics,
                "blockers": sorted(set(filter(None, metric_blockers))),
                "tradePnlPreview": [round(item, 4) for item in result["tradePnls"][:10]],
            }
        )
        blockers.extend(metric_blockers)
    valid_windows = [row for row in windows if not row["blockers"]]
    negative_windows = [
        str(row.get("window"))
        for row in windows
        if _num(row.get("metrics", {}).get("pnlUsd", row.get("metrics", {}).get("pnl"))) <= 0
    ]
    positive_window_count = len(windows) - len(negative_windows)
    major_windows = [row for row in windows if row.get("window") in {"full", "first_half", "second_half"}]
    negative_major_windows = [
        str(row.get("window"))
        for row in major_windows
        if _num(row.get("metrics", {}).get("pnlUsd", row.get("metrics", {}).get("pnl"))) <= 0
    ]
    positive_major_window_count = len(major_windows) - len(negative_major_windows)
    full_window = next((row for row in windows if row["window"] == "full"), {})
    if not windows:
        blockers.append("BTC_WINDOW_ROWS_LT_MIN")
    if full_window and full_window["metrics"].get("tradeCount", 0) < 20:
        blockers.append("BTC_FULL_TRADE_COUNT_LT_20")
    if len(valid_windows) < 2:
        blockers.append("BTC_MULTI_WINDOW_VALID_WINDOWS_LT_2")
    full_metrics = full_window.get("metrics", {})
    return {
        "status": "BTC_CHAMPION_RETEST_PASS" if not blockers else "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
        "strategyId": config["strategyId"],
        "strategyName": config["strategyName"],
        "strategyFamily": config["strategyFamily"],
        "parameters": config["parameters"],
        "windowCount": len(windows),
        "validWindowCount": len(valid_windows),
        "positiveWindowCount": positive_window_count,
        "negativeWindowCount": len(negative_windows),
        "negativeWindows": negative_windows,
        "positiveMajorWindowCount": positive_major_window_count,
        "majorWindowFailureCount": len(negative_major_windows),
        "negativeMajorWindows": negative_major_windows,
        "fullWindowMetrics": full_metrics,
        "windows": windows,
        "blockers": sorted(set(filter(None, blockers))),
        "score": _btc_retest_score(full_metrics, len(valid_windows), blockers),
        "safety": SAFETY,
    }


def _btc_retest_score(metrics: dict[str, Any], valid_window_count: int, blockers: list[str]) -> float:
    pnl = _num(metrics.get("pnlUsd", metrics.get("pnl")))
    sharpe = _num(metrics.get("sharpe"))
    drawdown = _num(metrics.get("maxDrawdownPct"))
    trades = _num(metrics.get("tradeCount"))
    blocker_penalty = len(set(filter(None, blockers))) * 1.5
    return round(
        max(pnl, 0.0) / 10.0
        + max(sharpe, 0.0) * 2.0
        + math.log10(max(trades, 1.0)) * 1.4
        + valid_window_count * 2.0
        - max(drawdown, 0.0)
        - blocker_penalty,
        4,
    )


def _btc_retest_rank_key(item: dict[str, Any]) -> tuple[bool, bool, bool, int, int, int, float, float, float, float]:
    return (
        item.get("status") == "BTC_CHAMPION_RETEST_PASS",
        int(_num(item.get("majorWindowFailureCount"))) == 0,
        int(_num(item.get("negativeWindowCount"))) == 0,
        int(_num(item.get("positiveWindowCount"))),
        int(_num(item.get("positiveMajorWindowCount"))),
        int(_num(item.get("validWindowCount"))),
        _num(item.get("score")),
        _num(item.get("fullWindowMetrics", {}).get("pnlUsd")),
        _num(item.get("fullWindowMetrics", {}).get("sharpe")),
        -_num(item.get("fullWindowMetrics", {}).get("maxDrawdownPct")),
    )


def _ranked_btc_retests(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=_btc_retest_rank_key, reverse=True)


def _scanner_btc_configs(runtime_dir: Path) -> list[dict[str, Any]]:
    scan = _read_json(runtime_dir / BTC_SCAN_REPORT_PATH)
    rows = scan.get("topCandidates") if isinstance(scan.get("topCandidates"), list) else []
    configs: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[tuple[str, Any], ...]]] = set()
    existing = {
        (
            str(config.get("strategyFamily") or ""),
            tuple(sorted((config.get("parameters") or {}).items())),
        )
        for config in BTC_PROFILE_CONFIGS
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        parameters = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}
        strategy_family = str(row.get("strategyFamily") or "")
        key = (strategy_family, tuple(sorted(parameters.items())))
        if not parameters or key in existing or key in seen:
            continue
        strategy_id = str(row.get("strategyId") or "").strip()
        if not strategy_id:
            continue
        seen.add(key)
        configs.append(
            {
                "strategyId": strategy_id,
                "strategyName": row.get("strategyName") or "BTCUSD scanner-discovered shadow simulation",
                "strategyFamily": strategy_family,
                "parameters": parameters,
            }
        )
    return configs


def _select_btc_retest(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = _ranked_btc_retests(candidates)
    return ranked[0] if ranked else {}


def _btc_champion(runtime_dir: Path) -> dict[str, Any]:
    csv_path = next((path for path in _rate_csv_candidates(runtime_dir) if "BTCUSD" in path.name.upper()), None)
    if not csv_path:
        return {
            "status": "BTC_CHAMPION_RATES_MISSING",
            "strategyId": BTC_CHAMPION_STRATEGY_ID,
            "blockers": ["BTC_RATES_CSV_MISSING"],
            "safety": SAFETY,
        }
    rows = _read_rate_rows(csv_path, limit=50_000)
    specs = _contract_specs(runtime_dir)
    spec = specs.get("BTCUSD") or specs.get("#BTCUSD")
    if not spec:
        return {
            "status": "BTC_CHAMPION_CONTRACT_SPEC_MISSING",
            "strategyId": BTC_CHAMPION_STRATEGY_ID,
            "csvPath": str(csv_path),
            "barCount": len(rows),
            "blockers": ["BTC_CONTRACT_SPEC_MISSING"],
            "safety": SAFETY,
        }
    profile_configs = BTC_PROFILE_CONFIGS + _scanner_btc_configs(runtime_dir)
    candidate_retests = _ranked_btc_retests([_btc_candidate_retest(rows, spec, config) for config in profile_configs])
    selected = _select_btc_retest(candidate_retests)
    blockers = list(selected.get("blockers", []))
    return {
        "status": selected.get("status", "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS"),
        "strategyId": selected.get("strategyId", BTC_CHAMPION_STRATEGY_ID),
        "strategyName": selected.get("strategyName", ""),
        "strategyFamily": selected.get("strategyFamily", ""),
        "parameters": selected.get("parameters", {}),
        "csvPath": str(csv_path),
        "barCount": len(rows),
        "windowCount": selected.get("windowCount", 0),
        "validWindowCount": selected.get("validWindowCount", 0),
        "positiveWindowCount": selected.get("positiveWindowCount", 0),
        "negativeWindowCount": selected.get("negativeWindowCount", 0),
        "negativeWindows": selected.get("negativeWindows", []),
        "positiveMajorWindowCount": selected.get("positiveMajorWindowCount", 0),
        "majorWindowFailureCount": selected.get("majorWindowFailureCount", 0),
        "negativeMajorWindows": selected.get("negativeMajorWindows", []),
        "fullWindowMetrics": selected.get("fullWindowMetrics", {}),
        "windows": selected.get("windows", []),
        "candidateRetests": candidate_retests,
        "blockers": sorted(set(filter(None, blockers))),
        "nextActionZh": "继续补更长 BTC CopyRates 窗口并优先跟踪 candidateRetests 第一名；本报告不授权钱包、不写订单。",
        "safety": SAFETY,
    }


def build_champion_retest_report(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    forex = _forex_champion(runtime_dir)
    forex_review = _forex_contender_review(runtime_dir)
    crypto = _btc_champion(runtime_dir)
    blockers = []
    blockers.extend(f"forex:{item}" for item in forex.get("blockers", []))
    blockers.extend(f"crypto:{item}" for item in crypto.get("blockers", []))
    contender_ids = [
        str(row.get("seedId"))
        for row in forex_review.get("contenders", [])
        if isinstance(row, dict) and row.get("seedId")
    ]
    forex_action = (
        f"外汇优先并列候选 {' / '.join(contender_ids)} 做隔离 tester/forward A/B 复验"
        if forex_review.get("requiresParallelTesterForward") and contender_ids
        else f"外汇优先 {forex.get('seedId') or '当前冠军'} 隔离 tester/forward"
    )
    report = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAt": _now_iso(),
        "status": "CHAMPION_RETEST_PASS" if not blockers else "CHAMPION_RETEST_NEEDS_MORE_EVIDENCE",
        "statusZh": "冠军复验证据通过" if not blockers else "冠军复验仍需补证据",
        "forexChampion": forex,
        "forexContenderReview": forex_review,
        "cryptoChampion": crypto,
        "blockers": blockers,
        "nextSafeActionZh": f"{forex_action}；BTC 优先补更长 CopyRates 多窗口。继续禁止实盘订单和 live preset 变更。",
        "safety": SAFETY,
        "reportPath": str(runtime_dir / REPORT_PATH),
    }
    if write:
        _write_json(runtime_dir / REPORT_PATH, report)
    return report


def read_champion_retest_report(runtime_dir: Path) -> dict[str, Any]:
    report = _read_json(Path(runtime_dir) / REPORT_PATH)
    if report:
        return report
    return build_champion_retest_report(Path(runtime_dir), write=False)
