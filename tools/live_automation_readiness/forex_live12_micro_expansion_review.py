from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .forex_live12_capacity_expansion_roadmap import build_forex_live12_capacity_expansion_roadmap
from .forex_live12_runtime_handoff import build_forex_live12_runtime_handoff
from .lane_selector import _derived_primary_dashboard_path
from .schema import (
    FOREX_LIVE12_MICRO_EXPANSION_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_micro_expansion_review_path,
    utc_now_iso,
)


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if numeric == numeric else default


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _primary_close_history_path(runtime_dir: Path, primary_dashboard_json: str = "") -> Path:
    dashboard_path = Path(primary_dashboard_json) if primary_dashboard_json else _derived_primary_dashboard_path(runtime_dir)
    return dashboard_path.parent / "QuantGod_CloseHistory.csv"


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _ea_rsi_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = []
    for row in rows:
        symbol = str(row.get("Symbol") or row.get("symbol") or "")
        source = str(row.get("Source") or row.get("source") or "")
        strategy = str(row.get("Strategy") or row.get("strategy") or "")
        if symbol.upper() != "USDJPYC":
            continue
        if source.upper() != "EA":
            continue
        if strategy != "RSI_Reversal":
            continue
        filtered.append(row)
    return filtered


def _evidence_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    profits = [_float_value(row.get("NetProfit") if row.get("NetProfit") is not None else row.get("profit")) for row in rows]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    consecutive_losses = 0
    max_consecutive_losses = 0
    for profit in profits:
        if profit < 0:
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "naturalClosedTrades": len(rows),
        "netProfitUSC": round(sum(profits), 2),
        "wins": len(wins),
        "losses": len(losses),
        "winRatePct": round((len(wins) / len(rows)) * 100, 2) if rows else None,
        "profitFactor": round(gross_win / gross_loss, 4) if gross_loss > 0 else (None if gross_win <= 0 else 999.0),
        "maxConsecutiveLosses": max_consecutive_losses,
        "latestRows": rows[:5],
    }


def build_forex_live12_micro_expansion_review(
    runtime_dir: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    handoff = build_forex_live12_runtime_handoff(runtime, primary_dashboard_json=primary_dashboard_json, write=False)
    roadmap = build_forex_live12_capacity_expansion_roadmap(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    next_phase = roadmap.get("nextPhase") if isinstance(roadmap.get("nextPhase"), dict) else {}
    required = next_phase.get("requiredEvidence") if isinstance(next_phase.get("requiredEvidence"), dict) else {}
    close_history_path = _primary_close_history_path(runtime, primary_dashboard_json)
    metrics = _evidence_metrics(_ea_rsi_rows(_read_csv_rows(close_history_path)))
    spread_tier = str(roadmap.get("currentMarketGate", {}).get("spreadTier") or "")
    allowed_spreads = required.get("spreadTierAllowed") if isinstance(required.get("spreadTierAllowed"), list) else []
    min_trades = _int_value(required.get("minNaturalClosedTrades"), 5)
    max_losses = _int_value(required.get("maxConsecutiveLosses"), 2)
    blockers: list[dict[str, Any]] = []
    if metrics["naturalClosedTrades"] < min_trades:
        blockers.append({
            "code": "MICRO_CLOSED_TRADES_LT_MIN",
            "value": metrics["naturalClosedTrades"],
            "limit": min_trades,
            "reasonZh": "2→3 扩仓前需要更多 USDJPYc RSI_Reversal EA 自然平仓样本。",
        })
    if metrics["maxConsecutiveLosses"] > max_losses:
        blockers.append({
            "code": "MICRO_CONSECUTIVE_LOSSES_GT_MAX",
            "value": metrics["maxConsecutiveLosses"],
            "limit": max_losses,
            "reasonZh": "连续亏损超出下一档扩仓允许范围。",
        })
    if allowed_spreads and spread_tier not in allowed_spreads:
        blockers.append({
            "code": "MICRO_SPREAD_TIER_NOT_ALLOWED",
            "value": spread_tier,
            "limit": allowed_spreads,
            "reasonZh": "当前点差等级不适合推进下一档扩仓评审。",
        })
    if _float_value(handoff.get("positionSummary", {}).get("floatingProfit")) < 0:
        blockers.append({
            "code": "MICRO_OPEN_FLOATING_LOSS_ACTIVE",
            "value": handoff.get("positionSummary", {}).get("floatingProfit"),
            "limit": ">=0",
            "reasonZh": "当前仍有浮亏持仓，扩仓前先等待持仓自然结束或恢复。",
        })
    status = "MICRO_EXPANSION_WAITING_EVIDENCE" if blockers else "MICRO_EXPANSION_REVIEW_READY"
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_MICRO_EXPANSION_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": status,
        "statusZh": "2→3 微仓扩仓证据不足" if blockers else "2→3 微仓扩仓证据已满足评审条件",
        "phase": {
            "fromMaxTotalTrades": next_phase.get("fromMaxTotalTrades"),
            "toMaxTotalTrades": next_phase.get("toMaxTotalTrades"),
            "requestedMaxTotalTrades": requested_max_total_trades,
        },
        "evidence": {
            "closeHistoryPath": str(close_history_path),
            "metrics": metrics,
            "required": required,
            "currentSpreadTier": spread_tier,
            "currentFloatingProfit": handoff.get("positionSummary", {}).get("floatingProfit"),
        },
        "blockers": blockers,
        "decision": {
            "canApplyHere": False,
            "canWritePresetHere": False,
            "microReviewPassed": not blockers,
            "nextRecommendedMaxTotalTrades": next_phase.get("toMaxTotalTrades") if not blockers else next_phase.get("fromMaxTotalTrades"),
            "nextRequiredActionZh": (
                "2→3 微仓扩仓证据已满足；仍需独立 execution lane 才能改实盘 preset。"
                if not blockers
                else "继续收集自然平仓样本并等待当前持仓/点差/回撤条件满足；本 artifact 不改 preset、不下单。"
            ),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
        },
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = forex_live12_micro_expansion_review_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_micro_expansion_review(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_micro_expansion_review_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_micro_expansion_review(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_MICRO_EXPANSION_REVIEW_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 micro expansion review artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_micro_expansion_review(runtime, write=False)
