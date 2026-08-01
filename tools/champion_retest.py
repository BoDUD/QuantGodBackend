"""Read-only champion retest report for USDJPY forex strategy candidates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "quantgod.champion_retest.report.v1"
REPORT_PATH = Path("agent") / "QuantGod_ChampionRetestReport.json"
DEFAULT_FOREX_CHAMPION_SEED_ID = "GA-USDJPY-G0077-C0002"

SAFETY = {
    "readOnly": True,
    "shadowOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "livePresetMutationAllowed": False,
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
    segments: list[dict[str, Any]] = []
    blockers: list[str] = []
    for segment in walk_forward.get("segments") or []:
        net_r = _num(segment.get("netR"))
        profit_factor = _num(segment.get("profitFactor"))
        trade_count = int(_num(segment.get("tradeCount")))
        segment_blockers: list[str] = []
        if net_r <= 0:
            segment_blockers.append("SEGMENT_NET_R_NOT_POSITIVE")
        if profit_factor < 1.05:
            segment_blockers.append("SEGMENT_PROFIT_FACTOR_LT_1_05")
        if trade_count < 3:
            segment_blockers.append("SEGMENT_LOW_SAMPLE_LT_3")
        segments.append({
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
        })
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


def build_champion_retest_report(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    forex = _forex_champion(runtime)
    forex_review = _forex_contender_review(runtime)
    blockers = [f"forex:{item}" for item in forex.get("blockers", [])]
    contender_ids = [
        str(row.get("seedId"))
        for row in forex_review.get("contenders", [])
        if isinstance(row, dict) and row.get("seedId")
    ]
    next_action = (
        f"外汇并列候选 {' / '.join(contender_ids)} 做隔离 tester/forward A/B 复验"
        if forex_review.get("requiresParallelTesterForward") and contender_ids
        else f"外汇候选 {forex.get('seedId') or '当前冠军'} 做隔离 tester/forward 复验"
    )
    report = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAt": _now_iso(),
        "status": "CHAMPION_RETEST_PASS" if not blockers else "CHAMPION_RETEST_NEEDS_MORE_EVIDENCE",
        "statusZh": "外汇冠军复验证据通过" if not blockers else "外汇冠军复验仍需补证据",
        "forexChampion": forex,
        "forexContenderReview": forex_review,
        "blockers": blockers,
        "nextSafeActionZh": f"{next_action}；继续禁止实盘订单和 live preset 变更。",
        "safety": SAFETY,
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, report)
    return report


def read_champion_retest_report(runtime_dir: Path) -> dict[str, Any]:
    report = _read_json(Path(runtime_dir) / REPORT_PATH)
    return report if report else build_champion_retest_report(Path(runtime_dir), write=False)
