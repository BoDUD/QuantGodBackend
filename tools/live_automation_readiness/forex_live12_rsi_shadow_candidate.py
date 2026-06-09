from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .forex_live12_micro_expansion_review import (
    _ea_rsi_rows,
    _evidence_metrics,
    _float_value,
    _primary_close_history_path,
    _read_csv_rows,
)
from .forex_live12_rsi_repair_plan import build_forex_live12_rsi_repair_plan
from .schema import (
    FOREX_LIVE12_RSI_SHADOW_CANDIDATE_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_rsi_shadow_candidate_path,
    utc_now_iso,
)


def _chronological(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get("OpenTime") or row.get("CloseTime") or ""))


def _regime_is_downtrend(row: dict[str, Any]) -> bool:
    regimes = [
        str(row.get("EntryRegime") or "").upper(),
        str(row.get("ExitRegime") or "").upper(),
    ]
    return any("TREND_DOWN" in regime or "TREND_EXP_DOWN" in regime for regime in regimes)


def _proxy_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    kept: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    consecutive_losses = 0
    for row in _chronological(rows):
        profit = _float_value(row.get("NetProfit") if row.get("NetProfit") is not None else row.get("profit"))
        reasons: list[str] = []
        if consecutive_losses >= 2:
            reasons.append("COOLDOWN_AFTER_2_LOSSES")
        if _regime_is_downtrend(row) and profit < 0:
            reasons.append("DOWN_TREND_BUY_LOSS_FILTER")
        if reasons:
            blocked.append({
                "positionId": row.get("PositionId"),
                "openTime": row.get("OpenTime"),
                "closeTime": row.get("CloseTime"),
                "netProfitUSC": profit,
                "entryRegime": row.get("EntryRegime"),
                "exitRegime": row.get("ExitRegime"),
                "reasons": reasons,
            })
            continue
        kept.append(row)
        consecutive_losses = consecutive_losses + 1 if profit < 0 else 0
    return {
        "mode": "READ_ONLY_CLOSE_HISTORY_PROXY_REPLAY",
        "beforeMetrics": _evidence_metrics(_chronological(rows)),
        "afterMetrics": _evidence_metrics(kept),
        "blockedTradeCount": len(blocked),
        "keptTradeCount": len(kept),
        "blockedTrades": blocked[:8],
        "limitationsZh": "这是基于已平仓历史的代理回放，只用于评估修复方向；不是 MT5 tick 回测，也不会改实盘参数。",
    }


def build_forex_live12_rsi_shadow_candidate(
    runtime_dir: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    plan = build_forex_live12_rsi_repair_plan(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    rows = _ea_rsi_rows(_read_csv_rows(_primary_close_history_path(runtime, primary_dashboard_json)))
    replay = _proxy_replay(rows)
    before = replay["beforeMetrics"]
    after = replay["afterMetrics"]
    before_pf = before.get("profitFactor") if isinstance(before.get("profitFactor"), (int, float)) else 0
    after_pf = after.get("profitFactor") if isinstance(after.get("profitFactor"), (int, float)) else 0
    before_losses = int(before.get("maxConsecutiveLosses") or 0)
    after_losses = int(after.get("maxConsecutiveLosses") or 0)
    improved = after_losses <= 2 and after_pf >= before_pf and replay["keptTradeCount"] > 0
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_RSI_SHADOW_CANDIDATE_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": "RSI_SHADOW_CANDIDATE_READY" if improved else "RSI_SHADOW_CANDIDATE_NEEDS_MORE_EVIDENCE",
        "statusZh": "RSI 修复影子候选已生成" if improved else "RSI 修复影子候选需要更多样本",
        "candidate": {
            "id": "forex-live12-rsi-loss-cooldown-v1",
            "lane": "FAST_SHADOW",
            "symbol": "USDJPYc",
            "strategy": "RSI_Reversal",
            "stage": "2_TO_3_REPAIR",
            "targetMaxTotalTrades": requested_max_total_trades,
            "stageMaxTotalTrades": plan.get("decision", {}).get("nextRecommendedMaxTotalTrades", 2),
            "parameters": {
                "cooldownAfterConsecutiveLosses": 2,
                "cooldownBarsH1": 1,
                "requireSignalScoreAfterCooldown": 100,
                "penalizeBuyWhenRegimeContains": ["TREND_DOWN", "TREND_EXP_DOWN"],
                "minProfitFactorForExpansion": 1.05,
                "requireFloatingProfitNonNegativeForExpansion": True,
                "maxConsecutiveLossesForExpansion": 2,
            },
        },
        "sourceRepairPlan": {
            "status": plan.get("status"),
            "statusZh": plan.get("statusZh"),
            "repairActions": plan.get("repairActions", []),
            "microBlockers": plan.get("evidence", {}).get("microBlockers", []),
        },
        "proxyReplay": replay,
        "decision": {
            "canApplyHere": False,
            "canWritePresetHere": False,
            "canPromoteToLiveHere": False,
            "candidateReadyForShadowBacktest": True,
            "nextRecommendedMaxTotalTrades": plan.get("decision", {}).get("nextRecommendedMaxTotalTrades", 2),
            "nextRequiredActionZh": "把该候选送入影子/Tester 回测；只有 PF、连续亏损和浮盈闸门恢复后，才重新评审 2→3。",
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
        out = forex_live12_rsi_shadow_candidate_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_rsi_shadow_candidate(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_rsi_shadow_candidate_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_rsi_shadow_candidate(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_RSI_SHADOW_CANDIDATE_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 RSI shadow candidate artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_rsi_shadow_candidate(runtime, write=False)
