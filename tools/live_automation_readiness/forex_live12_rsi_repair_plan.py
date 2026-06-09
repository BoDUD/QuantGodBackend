from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .forex_live12_micro_expansion_review import (
    _ea_rsi_rows,
    _evidence_metrics,
    _float_value,
    _primary_close_history_path,
    _read_csv_rows,
    build_forex_live12_micro_expansion_review,
)
from .schema import (
    FOREX_LIVE12_RSI_REPAIR_PLAN_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_rsi_repair_plan_path,
    utc_now_iso,
)


def _loss_clusters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "entryRegime": "",
        "exitRegime": "",
        "trades": 0,
        "losses": 0,
        "netProfitUSC": 0.0,
        "lossUSC": 0.0,
    })
    for row in rows:
        entry = str(row.get("EntryRegime") or "UNKNOWN")
        exit_regime = str(row.get("ExitRegime") or "UNKNOWN")
        key = (entry, exit_regime)
        profit = _float_value(row.get("NetProfit") if row.get("NetProfit") is not None else row.get("profit"))
        bucket = grouped[key]
        bucket["entryRegime"] = entry
        bucket["exitRegime"] = exit_regime
        bucket["trades"] += 1
        bucket["netProfitUSC"] = round(bucket["netProfitUSC"] + profit, 2)
        if profit < 0:
            bucket["losses"] += 1
            bucket["lossUSC"] = round(bucket["lossUSC"] + abs(profit), 2)
    clusters = list(grouped.values())
    clusters.sort(key=lambda item: (item["lossUSC"], item["losses"], -item["netProfitUSC"]), reverse=True)
    return clusters[:5]


def _repair_actions(metrics: dict[str, Any], blockers: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocker_codes = {str(row.get("code")) for row in blockers}
    actions: list[dict[str, Any]] = []
    if "MICRO_CONSECUTIVE_LOSSES_GT_MAX" in blocker_codes:
        actions.append({
            "code": "RSI_ADD_CONSECUTIVE_LOSS_COOLDOWN",
            "status": "RECOMMENDED_SHADOW_ONLY",
            "reasonZh": "RSI_Reversal 最大连续亏损超过 2→3 扩仓阈值，先在影子策略里加入 2 连亏冷却。",
            "shadowPatchZh": "同一策略出现 2 次自然亏损后，暂停新增 RSI_Reversal BUY 信号 1 个 H1 bar，并要求下一次信号分数恢复到 100。",
        })
    if "MICRO_OPEN_FLOATING_LOSS_ACTIVE" in blocker_codes:
        actions.append({
            "code": "RSI_BLOCK_EXPANSION_WHILE_FLOATING_LOSS",
            "status": "ACTIVE_REVIEW_GATE",
            "reasonZh": "当前仍有浮亏持仓，扩仓前先等待持仓自然结束或恢复非负。",
            "shadowPatchZh": "扩仓评审继续要求 floatingProfit >= 0；不平仓、不改仓、不加仓。",
        })
    worst = clusters[0] if clusters else {}
    if worst and (str(worst.get("entryRegime")) == "TREND_DOWN" or str(worst.get("exitRegime")) == "TREND_DOWN"):
        actions.append({
            "code": "RSI_PENALIZE_TREND_DOWN_BUY",
            "status": "RECOMMENDED_SHADOW_ONLY",
            "reasonZh": "亏损样本集中碰到 TREND_DOWN，RSI 反转 BUY 在顺势下跌环境里需要降权。",
            "shadowPatchZh": "当 EntryRegime 或 ExitRegime 为 TREND_DOWN 时，将 BUY 入场阈值提高一档，或只允许微型观察仓。",
        })
    profit_factor = metrics.get("profitFactor")
    if isinstance(profit_factor, (int, float)) and profit_factor < 1:
        actions.append({
            "code": "RSI_REQUIRE_PROFIT_FACTOR_RECOVERY",
            "status": "RECOMMENDED_SHADOW_ONLY",
            "reasonZh": "当前 RSI_Reversal profit factor 低于 1，说明盈利单还没覆盖亏损单。",
            "shadowPatchZh": "扩仓前要求新增自然样本把 profitFactor 拉回 1.05 以上，且 netProfitUSC 非负。",
        })
    if not actions:
        actions.append({
            "code": "RSI_KEEP_MAX_TOTAL_TRADES_REVIEW_ONLY",
            "status": "READY_FOR_SEPARATE_EXECUTION_REVIEW",
            "reasonZh": "修复 blocker 未触发；仍需要独立 execution lane 才能改实盘 preset。",
            "shadowPatchZh": "保持当前策略，只生成 2→3 扩仓候选，不在此处写 preset。",
        })
    return actions


def build_forex_live12_rsi_repair_plan(
    runtime_dir: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    micro = build_forex_live12_micro_expansion_review(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    close_history_path = _primary_close_history_path(runtime, primary_dashboard_json)
    rows = _ea_rsi_rows(_read_csv_rows(close_history_path))
    metrics = _evidence_metrics(rows)
    clusters = _loss_clusters(rows)
    blockers = micro.get("blockers") if isinstance(micro.get("blockers"), list) else []
    actions = _repair_actions(metrics, blockers, clusters)
    needs_repair = any(str(action.get("status")) == "RECOMMENDED_SHADOW_ONLY" for action in actions)
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_RSI_REPAIR_PLAN_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": "RSI_REPAIR_RECOMMENDED" if needs_repair else "RSI_REPAIR_NOT_REQUIRED",
        "statusZh": "RSI_Reversal 需要先修复再扩仓" if needs_repair else "RSI_Reversal 未触发修复 blocker",
        "request": {
            "requestedMaxTotalTrades": requested_max_total_trades,
            "currentRecommendedMaxTotalTrades": micro.get("decision", {}).get("nextRecommendedMaxTotalTrades"),
            "targetPlanZh": "目标仍是 10 个仓位，但必须按 2→3→4→6→8→10 阶梯推进。",
        },
        "evidence": {
            "closeHistoryPath": str(close_history_path),
            "metrics": metrics,
            "microBlockers": blockers,
            "lossClusters": clusters,
        },
        "repairActions": actions,
        "decision": {
            "canApplyHere": False,
            "canWritePresetHere": False,
            "canExpandToTenHere": False,
            "nextRecommendedMaxTotalTrades": micro.get("decision", {}).get("nextRecommendedMaxTotalTrades"),
            "nextRequiredActionZh": "先按 RSI 修复计划做影子迭代；等连续亏损 <=2、浮盈非负、PF 恢复后再评审 2→3。",
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
        out = forex_live12_rsi_repair_plan_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_rsi_repair_plan(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_rsi_repair_plan_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_rsi_repair_plan(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_RSI_REPAIR_PLAN_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 RSI repair plan artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_rsi_repair_plan(runtime, write=False)
