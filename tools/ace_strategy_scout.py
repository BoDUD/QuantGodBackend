"""Read-only scout for USDJPY forex strategy candidates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "quantgod.ace_strategy_scout.report.v1"
REPORT_PATH = Path("agent") / "QuantGod_AceStrategyScout.json"

SAFETY = {
    "readOnly": True,
    "shadowOnly": True,
    "testerOnly": True,
    "advisoryOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "writesLivePreset": False,
    "livePresetMutationAllowed": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _elite_rows(runtime: Path) -> tuple[str, list[dict[str, Any]]]:
    for path in (
        runtime / "ga" / "QuantGod_GAEliteStrategies.json",
        runtime / "ga_factory" / "QuantGod_GAEliteArchive.json",
    ):
        payload = _read_json(path)
        rows = _list(payload.get("elites")) or _list(payload.get("strategies")) or _list(payload.get("candidates"))
        normalized = [_dict(row) for row in rows if _dict(row)]
        if normalized:
            return str(path), normalized
    return "", []


def _candidate(row: dict[str, Any]) -> dict[str, Any]:
    breakdown = _dict(row.get("fitnessBreakdown"))
    backtest = _dict(breakdown.get("strategyBacktest")) or _dict(row.get("backtest"))
    walk_forward = _dict(breakdown.get("walkForward")) or _dict(row.get("walkForward"))
    summary = _dict(walk_forward.get("summary")) or walk_forward
    sample_count = int(max(
        _num(backtest.get("tradeCount")),
        _num(summary.get("sampleCount")),
    ))
    stability = _num(summary.get("stabilityScore"))
    blockers: list[str] = []
    if sample_count < 20:
        blockers.append("FOREX_EFFECTIVE_SAMPLE_LT_20")
    if stability < 0.8:
        blockers.append("FOREX_WALK_FORWARD_STABILITY_LT_0_8")
    if summary.get("promotionAllowed") is False:
        blockers.append(str(summary.get("blockerCode") or "FOREX_WALK_FORWARD_BLOCKED"))
    return {
        "lane": "usdjpy_ga_elite",
        "laneZh": "USDJPY GA 外汇候选",
        "seedId": row.get("seedId"),
        "strategyId": row.get("strategyId"),
        "strategyFamily": row.get("strategyFamily") or "RSI_Reversal",
        "direction": row.get("direction") or "LONG",
        "fitness": round(_num(row.get("fitness")), 4),
        "profitFactor": round(_num(backtest.get("profitFactor")), 4),
        "sharpe": round(_num(backtest.get("sharpe")), 4),
        "netR": round(_num(backtest.get("netR")), 4),
        "maxDrawdownR": round(_num(backtest.get("maxDrawdownR")), 4),
        "tradeCount": int(_num(backtest.get("tradeCount"))),
        "effectiveSampleCount": sample_count,
        "walkForwardStability": round(stability, 4),
        "forwardNetR": round(_num(summary.get("forwardNetR")), 4),
        "blockers": sorted(set(blockers)),
        "qualified": not blockers,
        "decision": "PRIORITIZE_FOR_TESTER_FORWARD" if not blockers else "REPAIR_OR_DISCARD",
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _contender_review(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    qualified = [row for row in candidates if row.get("qualified")]
    top_fitness = max((_num(row.get("fitness")) for row in qualified), default=0.0)
    contenders = [row for row in qualified if top_fitness - _num(row.get("fitness")) <= 0.25][:3]
    return {
        "schema": "quantgod.ace_strategy_scout.forex_contender_review.v1",
        "status": "FOREX_CONTENDERS_READY" if contenders else "FOREX_CONTENDERS_MISSING",
        "statusZh": "外汇候选已完成只读复核" if contenders else "等待外汇候选证据",
        "contenderCount": len(contenders),
        "tiedTopCount": len(contenders),
        "requiresParallelTesterForward": len(contenders) > 1,
        "contenders": contenders,
        "safety": dict(SAFETY),
    }


def build_ace_strategy_scout(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    source_path, rows = _elite_rows(runtime)
    candidates = sorted((_candidate(row) for row in rows), key=lambda row: _num(row.get("fitness")), reverse=True)
    qualified = [row for row in candidates if row.get("qualified")]
    top = qualified[0] if qualified else {}
    report = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "status": "ACE_FOREX_SCOUT_READY" if top else "ACE_FOREX_SCOUT_WAITING_EVIDENCE",
        "statusZh": "USDJPY 外汇王牌候选已完成排序" if top else "等待合格 USDJPY 外汇候选",
        "sourcePath": source_path,
        "candidates": candidates,
        "topQualifiedForex": top,
        "topObservedForex": candidates[0] if candidates else {},
        "forexContenderReview": _contender_review(candidates),
        "nextActionZh": "合格候选进入隔离 MT5 tester/forward；不得直接修改 live preset 或发送订单。",
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, report)
    return report


def read_ace_strategy_scout(runtime_dir: Path) -> dict[str, Any]:
    report = _read_json(Path(runtime_dir) / REPORT_PATH)
    return report if report else build_ace_strategy_scout(Path(runtime_dir), write=False)
