"""Read-only TP/SL optimizer for current QuantGod ace candidates.

The optimizer is an evidence artifact, not an execution adapter. Forex scoring
uses local historical trade MFE/MAE ledgers as a coarse screen for Strategy
Tester variants.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "quantgod.tp_sl_optimizer.report.v1"
REPORT_PATH = Path("agent") / "QuantGod_TpSlOptimizerReport.json"

SAFETY = {
    "readOnly": True,
    "shadowOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "livePresetMutationAllowed": False,
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
        "decision": {
            "mayWriteTesterConfigs": True,
            "mayMutateLivePreset": False,
            "mayPlaceOrders": False,
            "mayModifyOrders": False,
            "nextActionZh": "USDJPY 推荐组合进入隔离 tester/forward；真实 preset 与订单保持禁止。",
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
