"""Read-only TP/SL optimizer for current QuantGod ace candidates.

The optimizer is an evidence artifact, not an execution adapter. Forex scoring
uses local historical trade MFE/MAE ledgers as a coarse screen for Strategy
Tester variants. BTC scoring reruns local CopyRates multi-window retests.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.btc_strategy_scanner import _compact_retest
    from tools.champion_retest import (
        SAFETY as RETEST_SAFETY,
        _btc_candidate_retest,
        _contract_specs,
        _ranked_btc_retests,
        _rate_csv_candidates,
        _read_rate_rows,
    )
except ModuleNotFoundError:  # pragma: no cover
    from btc_strategy_scanner import _compact_retest
    from champion_retest import (
        SAFETY as RETEST_SAFETY,
        _btc_candidate_retest,
        _contract_specs,
        _ranked_btc_retests,
        _rate_csv_candidates,
        _read_rate_rows,
    )


REPORT_SCHEMA = "quantgod.tp_sl_optimizer.report.v1"
REPORT_PATH = Path("agent") / "QuantGod_TpSlOptimizerReport.json"

SAFETY = {
    **RETEST_SAFETY,
    "testerOnly": True,
    "configOnly": True,
    "advisoryOnly": True,
    "writesMt5OrderReceipt": False,
    "writesLivePreset": False,
    "brokerCallsMade": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").replace(",", "").strip())
        except ValueError:
            return default
    return default


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses <= 0:
        return 999.0 if wins > 0 else 0.0
    return wins / losses


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _sharpe(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    stdev = math.sqrt(variance)
    if stdev <= 0:
        return 9.99 if avg > 0 else 0.0
    return avg / stdev * math.sqrt(len(values))


def _forex_source_trades(runtime_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    path = runtime_dir / "backtest" / "QuantGod_StrategyTrades.csv"
    rows: list[dict[str, Any]] = []
    for row in _read_csv(path):
        if str(row.get("symbol") or "").upper() != "USDJPYC":
            continue
        risk_pips = _num(row.get("riskPips"), 0.0)
        mfe_r = _num(row.get("mfeR"), 0.0)
        mae_r = abs(_num(row.get("maeR"), 0.0))
        if risk_pips <= 0 or (mfe_r <= 0 and mae_r <= 0):
            continue
        rows.append({
            "riskPips": risk_pips,
            "mfePips": max(0.0, mfe_r * risk_pips),
            "maePips": max(0.0, mae_r * risk_pips),
            "grossProfitPips": _num(row.get("grossProfitPips"), _num(row.get("profitPips"), 0.0)),
            "profitPips": _num(row.get("profitPips"), 0.0),
            "costPips": max(0.0, _num(row.get("costPips"), 0.0)),
            "exitReason": str(row.get("exitReason") or ""),
        })
    return path, rows


def _score_forex_candidate(rows: list[dict[str, Any]], risk_pips: float, reward_ratio: float) -> dict[str, Any]:
    tp_pips = risk_pips * reward_ratio
    outcomes: list[float] = []
    exit_counts = {"take_profit": 0, "stop_loss": 0, "clamped_original": 0}
    for row in rows:
        mfe = float(row["mfePips"])
        mae = float(row["maePips"])
        cost = float(row["costPips"])
        original_gross = float(row["grossProfitPips"])
        if mfe >= tp_pips and mae < risk_pips:
            gross = tp_pips
            exit_counts["take_profit"] += 1
        elif mae >= risk_pips:
            gross = -risk_pips
            exit_counts["stop_loss"] += 1
        elif mfe >= tp_pips and mae >= risk_pips:
            gross = -risk_pips
            exit_counts["stop_loss"] += 1
        else:
            gross = max(-risk_pips, min(tp_pips, original_gross))
            exit_counts["clamped_original"] += 1
        outcomes.append(gross - cost)
    pf = _profit_factor(outcomes)
    wins = [value for value in outcomes if value > 0]
    net = sum(outcomes)
    dd = _max_drawdown(outcomes)
    sharpe = _sharpe(outcomes)
    blockers: list[str] = []
    if len(outcomes) < 20:
        blockers.append("FOREX_TPSL_SAMPLE_LT_20")
    if net <= 0:
        blockers.append("FOREX_TPSL_NET_PIPS_NOT_POSITIVE")
    if pf < 1.25:
        blockers.append("FOREX_TPSL_PF_LT_1_25")
    if sharpe < 1.0:
        blockers.append("FOREX_TPSL_SHARPE_LT_1")
    score = (
        min(pf, 5.0) * 15.0
        + sharpe * 8.0
        + net * 0.06
        + (len(wins) / len(outcomes) * 100.0 if outcomes else 0.0) * 0.15
        - dd * 0.25
        - len(blockers) * 8.0
    )
    return {
        "riskPips": round(risk_pips, 3),
        "rewardRatio": round(reward_ratio, 3),
        "tpPips": round(tp_pips, 3),
        "sampleCount": len(outcomes),
        "netPips": round(net, 3),
        "profitFactor": round(pf, 4),
        "sharpe": round(sharpe, 4),
        "winRatePct": round((len(wins) / len(outcomes) * 100.0) if outcomes else 0.0, 2),
        "maxDrawdownPips": round(dd, 3),
        "exitCounts": exit_counts,
        "blockers": blockers,
        "score": round(score, 4),
        "testerOverrides": {
            "ChampionRiskPips": str(int(round(risk_pips))),
            "PilotRewardRatio": str(round(reward_ratio, 2)),
            "PilotRsiATRMultiplierSL": "1.5",
        },
        "requiresTesterValidation": True,
    }


def _forex_grid(rows: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    candidates = [
        _score_forex_candidate(rows, risk_pips, reward_ratio)
        for risk_pips in (14.0, 16.0, 18.0, 20.0, 21.0, 22.0, 24.0, 26.0, 28.0, 30.0, 32.0)
        for reward_ratio in (1.2, 1.35, 1.5, 1.65, 1.8, 2.0, 2.2)
    ]
    ranked = sorted(
        candidates,
        key=lambda row: (
            not row["blockers"],
            row["score"],
            row["profitFactor"],
            row["netPips"],
            -row["maxDrawdownPips"],
        ),
        reverse=True,
    )
    passing = [row for row in ranked if not row["blockers"]]
    current_control = next(
        (
            row for row in ranked
            if row["riskPips"] == 21.0 and row["rewardRatio"] == 1.5
        ),
        {},
    )
    tester_variants = _forex_tester_variants(ranked, current_control, limit=6)
    return {
        "status": (
            "FOREX_TPSL_SCREEN_READY"
            if passing
            else "FOREX_TPSL_NO_PASSING_COARSE_COMBO"
            if rows
            else "FOREX_TPSL_SOURCE_TRADES_MISSING"
        ),
        "sourceEvidence": "runtime/backtest/QuantGod_StrategyTrades.csv MFE/MAE coarse screen",
        "evidenceLevel": "COARSE_SCREEN_REQUIRES_ISOLATED_TESTER",
        "sourceTradeCount": len(rows),
        "recommended": passing[0] if passing else {},
        "bestBlockedCandidate": ranked[0] if ranked else {},
        "currentControl": current_control,
        "testerVariantQueue": tester_variants,
        "topCandidates": ranked[:top_n],
        "nextActionZh": (
            "粗筛已有通过组合，可写入下一批隔离 Strategy Tester/forward 参数队列；仍不能直接改 live preset。"
            if passing
            else "粗筛没有找到可直接推荐的 USDJPY TP/SL；保留当前 G0093/G0102 风险核，先把 testerVariantQueue 送隔离 Strategy Tester A/B。"
        ),
    }


def _forex_tester_variants(
    ranked: list[dict[str, Any]],
    current_control: dict[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()

    def append_variant(candidate: dict[str, Any], source: str) -> None:
        risk = _num(candidate.get("riskPips"))
        reward = _num(candidate.get("rewardRatio"))
        if risk <= 0 or reward <= 0:
            return
        key = (risk, reward)
        if key in seen:
            return
        seen.add(key)
        variant = {
            "variantId": f"usdjpy_tpsl_{risk:g}r_{str(reward).replace('.', '_')}",
            "riskPips": risk,
            "rewardRatio": reward,
            "tpPips": round(risk * reward, 3),
            "coarseScreenSource": source,
            "coarseScreenScore": candidate.get("score"),
            "coarseScreenBlockers": candidate.get("blockers", []),
            "testerOverrides": {
                "ChampionRiskPips": str(int(round(risk))),
                "PilotRewardRatio": str(round(reward, 2)),
                "PilotRsiATRMultiplierSL": "1.5",
            },
            "testerOnly": True,
            "livePresetMutation": False,
        }
        variants.append(variant)

    for candidate in ranked[:limit]:
        append_variant(candidate, "ranked_coarse_screen")
    append_variant(current_control, "current_control")
    return variants[:limit]


def _btc_base_configs(runtime_dir: Path) -> list[dict[str, Any]]:
    scan = _read_json(runtime_dir / "agent" / "QuantGod_BtcStrategyScanReport.json")
    seeds = []
    seed_keys: set[tuple[tuple[str, Any], ...]] = set()

    def append_seed(candidate: dict[str, Any], *, source_role: str) -> None:
        params = candidate.get("parameters") if isinstance(candidate.get("parameters"), dict) else {}
        if not params:
            params = candidate.get("params") if isinstance(candidate.get("params"), dict) else {}
        if not params:
            return
        key = tuple(sorted(params.items()))
        if key in seed_keys:
            return
        seed_keys.add(key)
        seed = dict(candidate)
        seed["parameters"] = dict(params)
        seed["sourceRepairRole"] = source_role
        seeds.append(seed)

    top = scan.get("topCandidate") if isinstance(scan.get("topCandidate"), dict) else {}
    if top:
        append_seed(top, source_role="btcStrategyScannerTop")
    diagnostics = scan.get("repairDiagnostics") if isinstance(scan.get("repairDiagnostics"), dict) else {}
    for group_name in (
        "balancedQualityRepair",
        "balancedYieldRepair",
        "middleWindowRescueRepair",
        "balancedSampleDensityRepair",
    ):
        group = diagnostics.get(group_name) if isinstance(diagnostics.get(group_name), dict) else {}
        best = group.get("bestByStabilityRank") if isinstance(group.get("bestByStabilityRank"), dict) else {}
        if best:
            append_seed(best, source_role=group_name)

    prior_report = _read_json(runtime_dir / REPORT_PATH)
    prior_btc = prior_report.get("btcCryptoCfd") if isinstance(prior_report.get("btcCryptoCfd"), dict) else {}
    prior_middle = prior_btc.get("middleWindowLeaders") if isinstance(prior_btc.get("middleWindowLeaders"), dict) else {}
    for key in ("bestTargetMiddleQuality", "bestMiddleQuality", "bestBalanced"):
        card = prior_middle.get(key) if isinstance(prior_middle.get(key), dict) else {}
        if card:
            append_seed(card, source_role=f"priorOptimizerMiddleWindow:{key}")
    configs = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    tp_values = (350.0, 400.0, 450.0, 500.0, 600.0, 750.0, 900.0, 1050.0)
    sl_values = (250.0, 300.0, 350.0, 400.0, 450.0, 500.0, 600.0)
    hold_values = (8, 12, 16, 24, 36)
    cooldown_values = (4, 6, 8, 10)
    for seed in seeds:
        params = seed.get("parameters") if isinstance(seed.get("parameters"), dict) else {}
        if not params or "takeProfitPriceMove" not in params or "stopLossPriceMove" not in params:
            continue
        source_role = str(seed.get("sourceRepairRole") or "")
        prior_middle_seed = source_role.startswith("priorOptimizerMiddleWindow:")
        seed_hold = int(_num(params.get("maxHoldBars"), 0))
        seed_cooldown = int(_num(params.get("cooldownBars"), 0))
        seed_tp = _num(params.get("takeProfitPriceMove"), 0.0)
        seed_sl = _num(params.get("stopLossPriceMove"), 0.0)
        seed_threshold = _num(params.get("slopeThresholdPrice"), 0.0)
        if prior_middle_seed:
            neighborhood_tp = {seed_tp + delta for delta in (-150.0, -100.0, 0.0, 100.0, 150.0) if seed_tp + delta > 0}
            neighborhood_sl = {seed_sl + delta for delta in (-75.0, -50.0, 0.0, 50.0, 75.0) if seed_sl + delta > 0}
            neighborhood_hold = {seed_hold + delta for delta in (-12, 0, 12) if seed_hold + delta > 0}
            neighborhood_cooldown = {seed_cooldown + delta for delta in (-2, -1, 0, 1, 2) if seed_cooldown + delta >= 0}
            neighborhood_threshold = {
                seed_threshold + delta
                for delta in (-25.0, 0.0, 25.0)
                if seed_threshold + delta > 0
            }
            candidate_tp_values = sorted({600.0, 650.0, 750.0, 850.0, 900.0, *neighborhood_tp})
            candidate_sl_values = sorted({350.0, 400.0, 450.0, *neighborhood_sl})
            candidate_hold_values = sorted({24, 36, 48, *neighborhood_hold})
            candidate_cooldown_values = sorted({4, 6, 8, 10, *neighborhood_cooldown})
            candidate_threshold_values = sorted({75.0, 100.0, 125.0, *neighborhood_threshold})
        else:
            candidate_tp_values = sorted({*tp_values, *([seed_tp] if seed_tp > 0 else [])})
            candidate_sl_values = sorted({*sl_values, *([seed_sl] if seed_sl > 0 else [])})
            candidate_hold_values = sorted({*hold_values, *([seed_hold] if seed_hold > 0 else [])})
            candidate_cooldown_values = sorted({*cooldown_values, *([seed_cooldown] if seed_cooldown > 0 else [])})
            candidate_threshold_values = [seed_threshold] if seed_threshold > 0 else [100.0]
        for take_profit in candidate_tp_values:
            for stop_loss in candidate_sl_values:
                for max_hold in candidate_hold_values:
                    for cooldown in candidate_cooldown_values:
                        for threshold in candidate_threshold_values:
                            candidate_params = {
                                **params,
                                "slopeThresholdPrice": threshold,
                                "takeProfitPriceMove": take_profit,
                                "stopLossPriceMove": stop_loss,
                                "maxHoldBars": max_hold,
                                "cooldownBars": cooldown,
                            }
                            key = tuple(sorted(candidate_params.items()))
                            if key in seen:
                                continue
                            seen.add(key)
                            configs.append({
                                "strategyId": f"hfm_crypto_btc_tpsl_{len(configs) + 1:04d}",
                                "strategyName": "BTCUSD TP/SL optimizer scan",
                                "strategyFamily": seed.get("strategyFamily") or "ema_slope_regime",
                                "parameters": candidate_params,
                                "sourceStrategyId": seed.get("strategyId"),
                                "sourceRepairRole": seed.get("sourceRepairRole"),
                                "scanDimensions": {
                                    "slopeThresholdPrice": threshold,
                                    "takeProfitPriceMove": take_profit,
                                    "stopLossPriceMove": stop_loss,
                                    "maxHoldBars": max_hold,
                                    "cooldownBars": cooldown,
                                },
                            })
    return configs


def _btc_full_pnl(candidate: dict[str, Any]) -> float:
    return float((candidate.get("fullWindowMetrics") or {}).get("pnlUsd") or 0.0)


def _btc_window_count(candidate: dict[str, Any], key: str) -> int:
    return int(candidate.get(key) or 0)


def _btc_max_drawdown(candidate: dict[str, Any]) -> float:
    return float((candidate.get("fullWindowMetrics") or {}).get("maxDrawdownPct") or 999.0)


def _btc_pick_with_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    if not candidate:
        return {}
    pick = dict(candidate)
    parameters = pick.get("parameters") if isinstance(pick.get("parameters"), dict) else {}
    if parameters:
        pick["params"] = dict(parameters)
        pick["tpSlSummary"] = {
            "bias": parameters.get("bias"),
            "takeProfitPriceMove": parameters.get("takeProfitPriceMove"),
            "stopLossPriceMove": parameters.get("stopLossPriceMove"),
            "maxHoldBars": parameters.get("maxHoldBars"),
            "cooldownBars": parameters.get("cooldownBars"),
        }
    return pick


def _btc_window_health(candidate: dict[str, Any]) -> dict[str, Any]:
    if not candidate:
        return {}
    windows = candidate.get("windowSummary") if isinstance(candidate.get("windowSummary"), list) else []
    weak_windows = []
    blocker_counts: dict[str, int] = {}
    sharpe_values: list[float] = []
    trade_counts: list[int] = []
    pnl_values: list[float] = []
    for row in windows:
        if not isinstance(row, dict):
            continue
        blockers = [str(item) for item in row.get("blockers", []) if item]
        for blocker in blockers:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        sharpe = _num(row.get("sharpe"))
        trades = int(_num(row.get("tradeCount")))
        pnl = _num(row.get("pnlUsd"))
        sharpe_values.append(sharpe)
        trade_counts.append(trades)
        pnl_values.append(pnl)
        if blockers:
            weak_windows.append({
                "window": row.get("window"),
                "pnlUsd": round(pnl, 4),
                "sharpe": round(sharpe, 4),
                "tradeCount": trades,
                "blockers": blockers,
            })
    middle = next((row for row in weak_windows if row.get("window") == "middle_third"), {})
    all_positive = bool(pnl_values) and all(value > 0 for value in pnl_values)
    valid = int(candidate.get("validWindowCount") or 0)
    total = int(candidate.get("windowCount") or len(windows) or 0)
    repair_focus = []
    if blocker_counts.get("HFM_SHARPE_LT_MIN"):
        repair_focus.append("raise_window_sharpe")
    if blocker_counts.get("HFM_TRADE_COUNT_LT_MIN") or blocker_counts.get("WINDOW_LOW_SAMPLE_LT_3"):
        repair_focus.append("increase_window_sample_density")
    if middle:
        repair_focus.append("middle_third_rescue")
    if not repair_focus:
        repair_focus.append("extend_forward_window_confirmation")
    return {
        "allWindowsPositive": all_positive,
        "validWindowRatio": round(valid / total, 4) if total else 0.0,
        "weakWindowCount": len(weak_windows),
        "weakWindows": weak_windows,
        "middleThirdWeak": bool(middle),
        "middleThirdWeakness": middle,
        "minWindowSharpe": round(min(sharpe_values), 4) if sharpe_values else None,
        "minWindowTradeCount": min(trade_counts) if trade_counts else None,
        "blockerHistogram": blocker_counts,
        "repairFocus": repair_focus,
        "diagnosisZh": (
            "所有窗口为正，但 middle_third 仍是主要弱点；下一步优先围绕该窗口提高 Sharpe/样本密度。"
            if middle and all_positive
            else "窗口收益存在负值或阻塞，先继续多窗口修复，不进入执行默认。"
            if weak_windows
            else "未发现弱窗口；下一步补更长 forward 数据确认。"
        ),
    }


def _btc_focused_retest_queue(
    stable: dict[str, Any],
    target_seeking: dict[str, Any],
    aggressive: dict[str, Any],
    final_pick: dict[str, Any],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append(candidate: dict[str, Any], role: str, priority: int) -> None:
        strategy_id = str(candidate.get("strategyId") or "")
        if not strategy_id or strategy_id in seen:
            return
        seen.add(strategy_id)
        params = candidate.get("params") if isinstance(candidate.get("params"), dict) else {}
        if not params:
            params = candidate.get("parameters") if isinstance(candidate.get("parameters"), dict) else {}
        health = _btc_window_health(candidate)
        queue.append({
            "priority": priority,
            "role": role,
            "strategyId": strategy_id,
            "tpSlSummary": {
                "bias": params.get("bias"),
                "takeProfitPriceMove": params.get("takeProfitPriceMove"),
                "stopLossPriceMove": params.get("stopLossPriceMove"),
                "maxHoldBars": params.get("maxHoldBars"),
                "cooldownBars": params.get("cooldownBars"),
            },
            "metrics": candidate.get("fullWindowMetrics", {}),
            "validWindowCount": candidate.get("validWindowCount"),
            "windowCount": candidate.get("windowCount"),
            "windowHealth": health,
            "testerOnly": True,
            "livePresetMutation": False,
            "orderSendAllowed": False,
            "nextActionZh": (
                "作为默认稳健候选继续补 middle_third 复验。"
                if role == "selectedDefault"
                else "作为冲目标候选补窗口稳定性，不直接替代默认。"
                if role == "targetSeeking"
                else "仅保留高收益对照，先观察样本密度和窗口 Sharpe。"
            ),
        })

    append(final_pick, "selectedDefault", 1)
    append(target_seeking, "targetSeeking", 2)
    append(aggressive, "aggressiveHighPnl", 3)
    append(stable, "stableDefault", 4)
    return sorted(queue, key=lambda row: int(row.get("priority") or 99))


def _btc_window_metrics(candidate: dict[str, Any], window_name: str) -> dict[str, Any]:
    windows = candidate.get("windows") if isinstance(candidate.get("windows"), list) else []
    for row in windows:
        if isinstance(row, dict) and row.get("window") == window_name:
            metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
            return {
                "window": window_name,
                "pnlUsd": round(_num(metrics.get("pnlUsd", metrics.get("pnl"))), 4),
                "sharpe": round(_num(metrics.get("sharpe")), 4),
                "tradeCount": int(_num(metrics.get("tradeCount"))),
                "maxDrawdownPct": round(_num(metrics.get("maxDrawdownPct")), 4),
                "blockers": row.get("blockers", []),
            }
    compact_windows = candidate.get("windowSummary") if isinstance(candidate.get("windowSummary"), list) else []
    for row in compact_windows:
        if isinstance(row, dict) and row.get("window") == window_name:
            return {
                "window": window_name,
                "pnlUsd": round(_num(row.get("pnlUsd")), 4),
                "sharpe": round(_num(row.get("sharpe")), 4),
                "tradeCount": int(_num(row.get("tradeCount"))),
                "maxDrawdownPct": round(_num(row.get("maxDrawdownPct")), 4),
                "blockers": row.get("blockers", []),
            }
    return {}


def _btc_leader_card(candidate: dict[str, Any], *, role: str) -> dict[str, Any]:
    if not candidate:
        return {}
    compact = _compact_retest(candidate) if "windows" in candidate else dict(candidate)
    middle = _btc_window_metrics(candidate, "middle_third") or _btc_window_metrics(compact, "middle_third")
    parameters = compact.get("parameters") if isinstance(compact.get("parameters"), dict) else {}
    return {
        "role": role,
        "strategyId": compact.get("strategyId"),
        "strategyName": compact.get("strategyName"),
        "strategyFamily": compact.get("strategyFamily"),
        "parameters": parameters,
        "tpSlSummary": {
            "bias": parameters.get("bias"),
            "takeProfitPriceMove": parameters.get("takeProfitPriceMove"),
            "stopLossPriceMove": parameters.get("stopLossPriceMove"),
            "maxHoldBars": parameters.get("maxHoldBars"),
            "cooldownBars": parameters.get("cooldownBars"),
        },
        "fullWindowMetrics": compact.get("fullWindowMetrics", {}),
        "middleThirdMetrics": middle,
        "validWindowCount": compact.get("validWindowCount"),
        "windowCount": compact.get("windowCount"),
        "positiveWindowCount": compact.get("positiveWindowCount"),
        "negativeWindowCount": compact.get("negativeWindowCount"),
        "blockers": compact.get("blockers", []),
        "windowHealth": _btc_window_health(compact),
        "testerOnly": True,
        "livePresetMutation": False,
        "orderSendAllowed": False,
    }


def _btc_middle_window_leaders(retests: list[dict[str, Any]]) -> dict[str, Any]:
    def middle(row: dict[str, Any]) -> dict[str, Any]:
        return _btc_window_metrics(row, "middle_third")

    def full(row: dict[str, Any]) -> dict[str, Any]:
        return row.get("fullWindowMetrics") if isinstance(row.get("fullWindowMetrics"), dict) else {}

    eligible = [row for row in retests if middle(row)]
    all_positive = [
        row for row in eligible
        if int(row.get("positiveWindowCount") or 0) == int(row.get("windowCount") or 0)
        and int(row.get("negativeWindowCount") or 0) == 0
        and int(row.get("majorWindowFailureCount") or 0) == 0
        and _num(full(row).get("liquidationCount")) == 0
    ]
    target_positive = [
        row for row in all_positive
        if _num(full(row).get("pnlUsd", full(row).get("pnl"))) >= 50.0
        and _num(full(row).get("maxDrawdownPct"), 999.0) <= 2.25
    ]

    def middle_quality_key(row: dict[str, Any]) -> tuple[int, float, int, int, float, float, float, float]:
        m = middle(row)
        blocker_count = len(m.get("blockers", []))
        return (
            -blocker_count,
            _num(m.get("sharpe")),
            int(_num(m.get("tradeCount"))),
            int(row.get("validWindowCount") or 0),
            _num(m.get("pnlUsd")),
            _num(full(row).get("pnlUsd", full(row).get("pnl"))),
            _num(full(row).get("sharpe")),
            -_num(full(row).get("maxDrawdownPct")),
        )

    def balanced_key(row: dict[str, Any]) -> tuple[int, int, int, float, float, int, float, float]:
        m = middle(row)
        return (
            int(row.get("validWindowCount") or 0),
            int(row.get("positiveWindowCount") or 0),
            -len(m.get("blockers", [])),
            _num(m.get("sharpe")),
            _num(m.get("pnlUsd")),
            int(_num(m.get("tradeCount"))),
            _num(full(row).get("pnlUsd", full(row).get("pnl"))),
            -_num(full(row).get("maxDrawdownPct")),
        )

    best_middle_quality = max(all_positive, key=middle_quality_key, default={})
    best_target_middle_quality = max(target_positive, key=middle_quality_key, default={})
    best_balanced = max(all_positive, key=balanced_key, default={})
    return {
        "status": "BTC_MIDDLE_WINDOW_LEADERS_READY" if eligible else "BTC_MIDDLE_WINDOW_LEADERS_MISSING",
        "leaderBasisZh": "优先筛选全窗口正收益、零爆仓、无 major window 负收益的候选，再按 middle_third blocker 数、Sharpe、交易数、valid windows 和总收益排序。",
        "bestBalanced": _btc_leader_card(best_balanced, role="bestBalancedMiddleWindow"),
        "bestMiddleQuality": _btc_leader_card(best_middle_quality, role="bestMiddleQuality"),
        "bestTargetMiddleQuality": _btc_leader_card(best_target_middle_quality, role="bestTargetMiddleQuality"),
        "nextRepairHypothesisZh": (
            "当前不是缺总收益，而是 middle_third 的 Sharpe/样本数不够；下一轮优先围绕 bestTargetMiddleQuality 的参数邻域微调冷却、持仓时长和 TP/SL。"
            if best_target_middle_quality
            else "当前未找到 50 USD 以上且中段窗口质量更好的候选；下一轮继续扩大中段窗口修复扫描或补更长 CopyRates。"
        ),
    }


def _btc_final_advisory_pick(stable: dict[str, Any], target_seeking: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    if not stable:
        if target_seeking:
            return (
                _btc_pick_with_summary(target_seeking),
                "TARGET_SEEKING_ONLY",
                "缺少稳健候选时才采用冲目标候选；仍需要继续多窗口复验，不允许直接实盘。",
            )
        return {}, "NO_CANDIDATE", "没有可推荐 BTC TP/SL 候选。"
    if not target_seeking:
        return (
            _btc_pick_with_summary(stable),
            "STABLE_DEFAULT",
            "默认采用稳健候选；没有满足 50 USD 目标且全窗口为正的替代组合。",
        )
    stable_valid = _btc_window_count(stable, "validWindowCount")
    target_valid = _btc_window_count(target_seeking, "validWindowCount")
    stable_major = _btc_window_count(stable, "positiveMajorWindowCount")
    target_major = _btc_window_count(target_seeking, "positiveMajorWindowCount")
    stable_negative = _btc_window_count(stable, "negativeWindowCount")
    target_negative = _btc_window_count(target_seeking, "negativeWindowCount")
    stable_dd = _btc_max_drawdown(stable)
    target_dd = _btc_max_drawdown(target_seeking)
    target_is_at_least_as_stable = (
        target_valid >= stable_valid
        and target_major >= stable_major
        and target_negative <= stable_negative
        and target_dd <= max(2.25, stable_dd + 0.35)
    )
    if target_is_at_least_as_stable:
        return (
            _btc_pick_with_summary(target_seeking),
            "TARGET_SEEKING_STABILITY_NOT_WORSE",
            "冲目标候选达到 50 USD 且窗口稳定性不弱于默认稳健候选，可作为默认模拟复验对象。",
        )
    return (
        _btc_pick_with_summary(stable),
        "STABLE_OVER_TARGET_SEEKING",
        "冲目标候选虽然达到 50 USD，但窗口通过数或回撤稳定性弱于稳健候选；默认继续复验稳健组合。",
    )


def _btc_grid(runtime_dir: Path, top_n: int) -> dict[str, Any]:
    csv_path = next((path for path in _rate_csv_candidates(runtime_dir) if "BTCUSD" in path.name.upper()), None)
    if not csv_path:
        return {"status": "BTC_TPSL_RATES_MISSING", "blockers": ["BTC_RATES_CSV_MISSING"]}
    rows = _read_rate_rows(csv_path, limit=50_000)
    specs = _contract_specs(runtime_dir)
    spec = specs.get("BTCUSD") or specs.get("#BTCUSD")
    if not spec:
        return {"status": "BTC_TPSL_CONTRACT_SPEC_MISSING", "blockers": ["BTC_CONTRACT_SPEC_MISSING"]}
    configs = _btc_base_configs(runtime_dir)
    retests = [_btc_candidate_retest(rows, spec, config) for config in configs]
    ranked = _ranked_btc_retests(retests)
    top = ranked[0] if ranked else {}
    best_high_pnl = max(
        ranked,
        key=lambda row: (
            float((row.get("fullWindowMetrics") or {}).get("pnlUsd") or 0.0),
            int(row.get("validWindowCount") or 0),
            float((row.get("fullWindowMetrics") or {}).get("sharpe") or 0.0),
        ),
        default={},
    )
    target_seekers = [
        row for row in ranked
        if float((row.get("fullWindowMetrics") or {}).get("pnlUsd") or 0.0) >= 50.0
        and int((row.get("fullWindowMetrics") or {}).get("liquidationCount") or 0) == 0
        and int(row.get("positiveWindowCount") or 0) == int(row.get("windowCount") or 0)
        and float((row.get("fullWindowMetrics") or {}).get("maxDrawdownPct") or 999.0) <= 2.25
    ]
    best_target_seeking = max(
        target_seekers,
        key=lambda row: (
            int(row.get("validWindowCount") or 0),
            float((row.get("fullWindowMetrics") or {}).get("pnlUsd") or 0.0),
            float((row.get("fullWindowMetrics") or {}).get("sharpe") or 0.0),
            -float((row.get("fullWindowMetrics") or {}).get("maxDrawdownPct") or 999.0),
        ),
        default={},
    )
    stable = _compact_retest(top) if top else {}
    target_seeking = _compact_retest(best_target_seeking) if best_target_seeking else {}
    aggressive = _compact_retest(best_high_pnl) if best_high_pnl else {}
    final_pick, final_pick_policy, final_pick_reason = _btc_final_advisory_pick(stable, target_seeking)
    stable_health = _btc_window_health(stable)
    target_health = _btc_window_health(target_seeking)
    aggressive_health = _btc_window_health(aggressive)
    final_health = _btc_window_health(final_pick)
    focused_queue = _btc_focused_retest_queue(stable, target_seeking, aggressive, final_pick)
    middle_leaders = _btc_middle_window_leaders(retests)
    target_tradeoff: dict[str, Any] = {}
    if stable and target_seeking:
        target_tradeoff = {
            "stablePnlUsd": round(_btc_full_pnl(stable), 4),
            "targetSeekingPnlUsd": round(_btc_full_pnl(target_seeking), 4),
            "stableValidWindowCount": _btc_window_count(stable, "validWindowCount"),
            "targetSeekingValidWindowCount": _btc_window_count(target_seeking, "validWindowCount"),
            "stableMaxDrawdownPct": round(_btc_max_drawdown(stable), 4),
            "targetSeekingMaxDrawdownPct": round(_btc_max_drawdown(target_seeking), 4),
            "defaultPolicy": final_pick_policy,
            "stableWindowHealth": stable_health,
            "targetSeekingWindowHealth": target_health,
        }
    return {
        "status": "BTC_TPSL_SCAN_READY" if ranked else "BTC_TPSL_CONFIGS_MISSING",
        "csvPath": str(csv_path),
        "barCount": len(rows),
        "scannedConfigCount": len(configs),
        "recommendedStable": stable,
        "recommendedTargetSeeking": target_seeking,
        "bestHighPnl": aggressive,
        "windowHealth": {
            "stable": stable_health,
            "targetSeeking": target_health,
            "aggressive": aggressive_health,
            "selectedDefault": final_health,
        },
        "middleWindowLeaders": middle_leaders,
        "focusedRetestQueue": focused_queue,
        "recommendedProfiles": {
            "stable": {
                "labelZh": "稳健优先",
                "candidate": stable,
                "reasonZh": "优先多窗口通过数、低回撤、零爆仓；适合作为默认模拟跟踪候选。",
            },
            "targetSeeking": {
                "labelZh": "冲 50 美元目标",
                "candidate": target_seeking,
                "reasonZh": "要求全窗口为正、零爆仓、回撤受控，并优先选择 full-window pnl >= 50 USD 的组合。",
            },
            "aggressive": {
                "labelZh": "进攻收益",
                "candidate": aggressive,
                "reasonZh": "只按 full-window pnl 优先，必须继续补窗口，不能直接晋级。",
            },
        },
        "finalAdvisoryPick": final_pick,
        "finalAdvisoryPickPolicy": final_pick_policy,
        "finalAdvisoryPickReasonZh": final_pick_reason,
        "targetTradeoff": target_tradeoff,
        "topCandidates": [_compact_retest(row) for row in ranked[:top_n]],
        "nextActionZh": "BTC 默认采用 finalAdvisoryPick 做模拟/复验；下一步按 focusedRetestQueue 优先修复 middle_third 的 Sharpe/样本密度，再决定是否让冲目标组合替代默认。",
    }


def build_tp_sl_optimizer_report(
    runtime_dir: Path,
    *,
    top_n: int = 8,
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    forex_source_path, forex_rows = _forex_source_trades(runtime)
    report = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "status": "TPSL_OPTIMIZER_READY",
        "statusZh": "止盈止损优化报告已生成",
        "forexMt5": {
            "sourcePath": str(forex_source_path),
            **_forex_grid(forex_rows, top_n),
        },
        "btcCryptoCfd": _btc_grid(runtime, top_n),
        "decision": {
            "mayWriteTesterConfigs": True,
            "mayMutateLivePreset": False,
            "mayPlaceOrders": False,
            "mayModifyOrders": False,
            "nextActionZh": "USDJPY 推荐组合进入隔离 tester/forward；BTC 推荐组合继续 CopyRates 多窗口复验。",
        },
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, report)
    return report


def read_tp_sl_optimizer_report(runtime_dir: Path) -> dict[str, Any]:
    path = Path(runtime_dir) / REPORT_PATH
    payload = _read_json(path)
    return payload if payload else build_tp_sl_optimizer_report(Path(runtime_dir), write=False)
