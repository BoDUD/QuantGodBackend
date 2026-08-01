from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import (
    LIVE_EXECUTION_LANE_SELECTOR_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    live_execution_lane_selector_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _derived_primary_dashboard_path(runtime_dir: Path) -> Path:
    text = str(Path(runtime_dir))
    if "net.metaquotes.wine.metatrader5-live16" in text:
        return Path(text.replace("net.metaquotes.wine.metatrader5-live16", "net.metaquotes.wine.metatrader5")) / "QuantGod_Dashboard.json"
    return Path(runtime_dir) / "QuantGod_Dashboard.json"


def _primary_dashboard_path(runtime_dir: Path, explicit_path: str = "") -> Path:
    if explicit_path:
        return Path(explicit_path)
    return _derived_primary_dashboard_path(runtime_dir)


def _bool(value: Any) -> bool:
    return value is True or value == "true" or value == "1" or value == 1


def _blocker(code: str, reason_zh: str, value: Any = None, source: str = "") -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    if source:
        row["source"] = source
    return row


def _money(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if numeric == numeric else 0.0


def _why_no_entry_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _safe_list(value):
        if isinstance(item, dict):
            rows.append({
                "code": item.get("code") or "",
                "label": item.get("label") or "",
                "detail": item.get("detail") or item.get("reason") or "",
            })
    return rows


def _forex_no_entry_diagnostics(dashboard: dict[str, Any]) -> dict[str, Any]:
    diagnostics = _safe_dict(dashboard.get("usdJpyRsiEntryDiagnostics"))
    if not diagnostics:
        return {}
    guards = _safe_dict(diagnostics.get("guards"))
    rsi = _safe_dict(diagnostics.get("rsi"))
    route = _safe_dict(diagnostics.get("route"))
    permissions = _safe_dict(diagnostics.get("permissions"))
    return {
        "schema": diagnostics.get("schema") or "",
        "generatedAtLocal": diagnostics.get("generatedAtLocal") or "",
        "generatedAtServer": diagnostics.get("generatedAtServer") or "",
        "symbol": diagnostics.get("symbol") or "",
        "strategy": diagnostics.get("strategy") or "RSI_Reversal",
        "state": diagnostics.get("state") or "",
        "stateZh": diagnostics.get("stateZh") or "",
        "summary": diagnostics.get("summary") or "",
        "whyNoEntry": _why_no_entry_rows(diagnostics.get("whyNoEntry")),
        "route": {
            "liveEnabled": bool(route.get("liveEnabled")),
            "candidateEnabled": bool(route.get("candidateEnabled")),
            "lastStatus": route.get("lastStatus") or "",
            "lastReason": route.get("lastReason") or "",
            "lastDirection": route.get("lastDirection") or "",
            "lastEvalTime": route.get("lastEvalTime") or "",
            "lastSignalTime": route.get("lastSignalTime") or "",
        },
        "guards": {
            "startupGuardActive": bool(guards.get("startupGuardActive")),
            "startupGuardReason": guards.get("startupGuardReason") or "",
            "newsBlocked": bool(guards.get("newsBlocked")),
            "newsReason": guards.get("newsReason") or "",
            "spreadAllowed": guards.get("spreadAllowed"),
            "spreadTier": guards.get("spreadTier") or "",
            "spreadPips": guards.get("spreadPips"),
            "maxSpreadPips": guards.get("maxSpreadPips"),
            "softMaxSpreadPips": guards.get("softMaxSpreadPips"),
            "hardMaxSpreadPips": guards.get("hardMaxSpreadPips"),
            "cooldownActive": bool(guards.get("cooldownActive")),
            "manualPositionBlock": bool(guards.get("manualPositionBlock")),
            "portfolioPositions": guards.get("portfolioPositions"),
            "symbolPositions": guards.get("symbolPositions"),
        },
        "rsi": {
            "indicatorReady": bool(rsi.get("indicatorReady")),
            "timeframe": rsi.get("timeframe") or "",
            "period": rsi.get("period"),
            "signalReady": bool(rsi.get("signalReady")),
            "signalDirection": rsi.get("signalDirection") or "",
            "signalScore": rsi.get("signalScore"),
            "evalCode": rsi.get("evalCode") or "",
            "evalReason": rsi.get("evalReason") or "",
            "trigger": rsi.get("trigger") or "",
            "rsiClosed1": rsi.get("rsiClosed1"),
            "rsiClosed2": rsi.get("rsiClosed2"),
        },
        "permissions": {
            "liveMode": bool(permissions.get("liveMode")),
            "readOnlyMode": bool(permissions.get("readOnlyMode")),
            "tradeAllowed": bool(permissions.get("tradeAllowed")),
            "blocker": permissions.get("blocker") or "",
            "terminalTradeAllowed": bool(permissions.get("terminalTradeAllowed")),
            "programTradeAllowed": bool(permissions.get("programTradeAllowed")),
            "accountTradeAllowed": bool(permissions.get("accountTradeAllowed")),
            "accountExpertTradeAllowed": bool(permissions.get("accountExpertTradeAllowed")),
            "symbolTradeMode": permissions.get("symbolTradeMode") or "",
        },
    }


def _forex_current_strategy(rsi: dict[str, Any], no_entry: dict[str, Any]) -> dict[str, Any]:
    rsi_signal = _safe_dict(no_entry.get("rsi"))
    route = _safe_dict(no_entry.get("route"))
    state = str(no_entry.get("state") or "").upper()
    signal_ready = bool(rsi_signal.get("signalReady"))
    return {
        "strategy": no_entry.get("strategy") or "RSI_Reversal",
        "status": state or route.get("lastStatus") or rsi.get("status") or "",
        "reason": no_entry.get("summary") or route.get("lastReason") or rsi.get("reason") or "",
        "riskMultiplier": rsi.get("riskMultiplier"),
        "signalReady": signal_ready,
        "signalDirection": rsi_signal.get("signalDirection") or route.get("lastDirection") or "",
        "signalScore": rsi_signal.get("signalScore"),
        "evalCode": rsi_signal.get("evalCode") or "",
    }


def _lane_profit(profit_target: dict[str, Any], lane_id: str) -> dict[str, Any]:
    lane = _safe_dict(_safe_dict(profit_target.get("laneTargets")).get(lane_id))
    return {
        "targetReached": bool(lane.get("targetReached")),
        "simulationVerifiedUsdProfit": round(_money(lane.get("simulationVerifiedUsdProfit")), 2),
        "status": lane.get("status") or "",
        "statusZh": lane.get("statusZh") or "",
        "strategyId": _safe_list(lane.get("evidence"))[0].get("strategyId") if _safe_list(lane.get("evidence")) and isinstance(_safe_list(lane.get("evidence"))[0], dict) else "",
    }


def _forex_lane(dashboard: dict[str, Any], profit_target: dict[str, Any], dashboard_path: Path) -> dict[str, Any]:
    runtime = _safe_dict(dashboard.get("runtime"))
    account = _safe_dict(dashboard.get("account"))
    symbols = _safe_list(dashboard.get("symbols"))
    focus_symbol = symbols[0] if symbols and isinstance(symbols[0], dict) else {}
    strategies = _safe_dict(focus_symbol.get("strategies") or dashboard.get("strategies"))
    rsi = _safe_dict(strategies.get("RSI_Reversal"))
    no_entry = _forex_no_entry_diagnostics(dashboard)
    current_strategy = _forex_current_strategy(rsi, no_entry)
    blockers: list[dict[str, Any]] = []
    if not dashboard:
        blockers.append(_blocker("FOREX_PRIMARY_DASHBOARD_MISSING", "未找到 Live12 外币 dashboard JSON。", str(dashboard_path)))
    if not _bool(runtime.get("livePilotMode")):
        blockers.append(_blocker("FOREX_LIVE_PILOT_MODE_NOT_CONFIRMED", "Live12 外币 runtime 尚未证明 livePilotMode=true。", runtime.get("livePilotMode")))
    if _bool(runtime.get("readOnlyMode")):
        blockers.append(_blocker("FOREX_READ_ONLY_MODE_ACTIVE", "Live12 外币 runtime 仍为 readOnlyMode=true。", runtime.get("readOnlyMode")))
    if not _bool(runtime.get("executionEnabled")):
        blockers.append(_blocker("FOREX_EXECUTION_NOT_ENABLED", "Live12 外币 runtime 尚未证明 executionEnabled=true。", runtime.get("executionEnabled")))
    if not _bool(runtime.get("tradeAllowed")):
        blockers.append(_blocker("FOREX_TRADE_NOT_ALLOWED", "Live12 外币 runtime 尚未证明综合 tradeAllowed=true。", runtime.get("tradeAllowed")))
    news = _safe_dict(dashboard.get("news"))
    if _bool(news.get("blocked")):
        blockers.append(_blocker("FOREX_NEWS_BLOCK_ACTIVE", news.get("reason") or "USDJPY 新闻过滤正在阻断新入场。", news.get("eventCode"), "news"))
    if str(runtime.get("tradeStatus") or "").upper() == "NEWS_BLOCK":
        blockers.append(_blocker("FOREX_TRADE_STATUS_NEWS_BLOCK", "Live12 外币当前 tradeStatus=NEWS_BLOCK。", runtime.get("tradeStatus")))
    diag_guards = _safe_dict(no_entry.get("guards"))
    if no_entry and diag_guards.get("spreadAllowed") is False:
        blockers.append(_blocker(
            "FOREX_RSI_ENTRY_SPREAD_BLOCK",
            "EA RSI 入场诊断显示当前点差未通过。",
            diag_guards.get("spreadPips"),
            "usdJpyRsiEntryDiagnostics",
        ))
    diag_state = str(no_entry.get("state") or "").upper()
    diag_eval_code = str(_safe_dict(no_entry.get("rsi")).get("evalCode") or "").upper()
    diag_is_waiting = diag_state in {"WAIT_SIGNAL", "WAIT_BAR", "NO_SIGNAL"} or diag_eval_code in {"WAIT_SIGNAL", "WAIT_BAR", "NO_SIGNAL"}
    if (not no_entry or diag_is_waiting) and str(rsi.get("status") or "").upper() in {"WAIT_SIGNAL", "WAIT_BAR"}:
        blockers.append(_blocker("FOREX_WAITING_STRATEGY_SIGNAL", rsi.get("reason") or "外币 EA 正在等待策略信号。", rsi.get("status"), "RSI_Reversal"))
    if _money(focus_symbol.get("spread")) > _money(focus_symbol.get("maxSpreadPips") or 0) and _money(focus_symbol.get("maxSpreadPips")):
        blockers.append(_blocker("FOREX_SPREAD_WIDE", "USDJPY 当前点差超过 normal spread；只允许等待或 mirror。", focus_symbol.get("spread")))
    hard_switches_ok = bool(
        _bool(runtime.get("livePilotMode"))
        and not _bool(runtime.get("readOnlyMode"))
        and _bool(runtime.get("executionEnabled"))
        and _bool(runtime.get("tradeAllowed"))
    )
    profit = _lane_profit(profit_target, "forexMt5")
    score = 0
    score += 35 if profit["targetReached"] else 0
    score += 35 if hard_switches_ok else 0
    score += 10 if account.get("server") else 0
    score += 10 if focus_symbol.get("symbol") else 0
    score -= 8 * len(blockers)
    return {
        "laneId": "forexMt5",
        "labelZh": "外币 MT5 Live12",
        "rankScore": max(score, 0),
        "profitEvidence": profit,
        "account": {
            "number": account.get("number"),
            "server": account.get("server"),
            "currency": account.get("currency"),
        },
        "runtimeSwitches": {
            "livePilotMode": _bool(runtime.get("livePilotMode")),
            "readOnlyMode": _bool(runtime.get("readOnlyMode")),
            "executionEnabled": _bool(runtime.get("executionEnabled")),
            "tradeAllowed": _bool(runtime.get("tradeAllowed")),
            "tradeStatus": runtime.get("tradeStatus") or "",
        },
        "currentStrategy": current_strategy,
        "noEntryDiagnostics": no_entry,
        "primaryBlocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "nearestSafeActionZh": (
            "外币车道硬执行开关已开，只需等待新闻/点差/策略信号等 EA 守门自然通过；本 selector 不写订单。"
            if hard_switches_ok
            else "先补齐外币 Live12 livePilot/readOnly/execution/tradeAllowed runtime 证据；本 selector 不改 preset。"
        ),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
    }


def build_live_execution_lane_selector(
    runtime_dir: Path,
    *,
    primary_dashboard_json: str = "",
    profit_target_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    dashboard_path = _primary_dashboard_path(runtime, primary_dashboard_json)
    dashboard = _read_json(dashboard_path)
    profit_target = _read_json(Path(profit_target_json)) if profit_target_json else _read_json(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json")
    if not profit_target:
        profit_target = _read_json(Path.cwd() / "runtime" / "profit_target" / "QuantGod_ProfitTargetTracker.json")
    lanes = [_forex_lane(dashboard, profit_target, dashboard_path)]
    ranked = sorted(lanes, key=lambda row: float(row.get("rankScore") or 0), reverse=True)
    selected = ranked[0] if ranked else {}
    payload: dict[str, Any] = {
        "ok": True,
        "schema": LIVE_EXECUTION_LANE_SELECTOR_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "primaryDashboardPath": str(dashboard_path),
        "status": "LANE_SELECTOR_REVIEW_ONLY",
        "statusZh": "外汇车道只读评审已刷新。",
        "selectedLaneId": selected.get("laneId") or "",
        "selectedLaneLabelZh": selected.get("labelZh") or "",
        "selectedLanePrimaryBlocker": selected.get("primaryBlocker") or {},
        "selectedLaneNearestSafeActionZh": selected.get("nearestSafeActionZh") or "",
        "lanes": ranked,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "nextRequiredActionZh": (
            "优先推进 rankScore 最高的 lane 的非副作用卡点；真实订单、preset 改写、request/receipt 写入仍关闭。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_execution_lane_selector_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_live_execution_lane_selector(runtime_dir: Path) -> dict[str, Any]:
    path = live_execution_lane_selector_path(Path(runtime_dir))
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {
            "ok": False,
            "schema": LIVE_EXECUTION_LANE_SELECTOR_SCHEMA_VERSION,
            "status": "MISSING",
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return {
        "ok": False,
        "schema": LIVE_EXECUTION_LANE_SELECTOR_SCHEMA_VERSION,
        "status": "INVALID",
        "path": str(path),
        "safety": dict(SAFETY),
    }
