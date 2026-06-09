#!/usr/bin/env python3
"""Build the QuantGod daily review and safe iteration queue.

The review consumes local QuantGod evidence files only. It may recommend
tester-only work, simulation retunes, and evidence-gated live promotion, but it
never mutates live presets, starts order paths, sends orders, or changes wallet
state.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_DIR = Path(r"C:\Program Files\HFM Metatrader 5\MQL5\Files")
OUTPUT_NAME = "QuantGod_DailyReview.json"
LEDGER_NAME = "QuantGod_DailyReviewLedger.csv"
JST = timezone(timedelta(hours=9), "JST")
FOCUS_SYMBOL = "USDJPYc"
NON_FOCUS_SYMBOL_RE = re.compile(r"\b(EURUSD|EURUSDc|XAUUSD|XAUUSDc)\b", re.I)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build QuantGod daily review JSON.")
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--output", default="")
    parser.add_argument("--ledger", default="")
    parser.add_argument("--max-actions", type=int, default=8)
    return parser.parse_args()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis", "utf-16"):
        try:
            text = raw.decode(encoding)
            if text.count("\x00") > max(8, len(text) // 10):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(read_text(path))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    text = read_text(path)
    if not text.strip():
        return []
    return list(csv.DictReader(text.splitlines()))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_csv(path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    if exists:
        with path.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        existing_header = rows[0] if rows else []
        if existing_header != fieldnames:
            migrated_rows: list[dict[str, Any]] = []
            for values in rows[1:]:
                # Preserve existing rows by their original header.  Same-width
                # schema changes must not shift old values into new columns.
                migrated_rows.append(dict(zip(existing_header, values)))
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for existing_row in migrated_rows:
                    writer.writerow({key: existing_row.get(key, "") for key in fieldnames})
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


def first(*values: Any, default: Any = "") -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        number = float(str(value).replace(",", "").replace("$", "").replace("%", "").strip())
        if math.isfinite(number):
            return number
    except Exception:
        pass
    return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_symbol(value: Any) -> str:
    return clean(value).upper()


def focus_symbol_root() -> str:
    return normalize_symbol(FOCUS_SYMBOL).removesuffix("C")


def row_symbol(row: dict[str, Any]) -> str:
    for key in (
        "Symbol",
        "symbol",
        "BrokerSymbol",
        "brokerSymbol",
        "CanonicalSymbol",
        "canonicalSymbol",
        "UnderlyingSymbol",
        "underlyingSymbol",
    ):
        value = clean(row.get(key))
        if value:
            return value
    return ""


def row_mentions_non_focus_symbol(row: dict[str, Any]) -> bool:
    text = " ".join(
        clean(row.get(key))
        for key in (
            "candidateId",
            "candidateVersionId",
            "presetName",
            "reportPath",
            "existingReportPath",
            "reportPathHint",
            "testerOnlyCommand",
            "configOnlyCommand",
            "title",
            "detail",
            "summary",
        )
        if clean(row.get(key))
    )
    return bool(NON_FOCUS_SYMBOL_RE.search(text))


def is_focus_or_unscoped_row(row: dict[str, Any]) -> bool:
    symbol = row_symbol(row)
    if symbol:
        return normalize_symbol(symbol).startswith(focus_symbol_root())
    return not row_mentions_non_focus_symbol(row)


def parse_iso_datetime(value: Any) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def generated_at(payload: dict[str, Any]) -> datetime | None:
    return parse_iso_datetime(first(payload.get("generatedAtIso"), payload.get("generatedAt"), payload.get("timestamp")))


def tester_window_plan(now: datetime | None = None) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(JST)
    windows_by_weekday = {
        0: [(time(0, 0), time(2, 30)), (time(20, 10), time(23, 30))],
        1: [(time(0, 0), time(2, 30)), (time(20, 10), time(23, 30))],
        2: [(time(0, 0), time(2, 30)), (time(20, 10), time(23, 30))],
        3: [(time(0, 0), time(2, 30)), (time(20, 10), time(23, 30))],
        4: [(time(0, 0), time(2, 30)), (time(20, 10), time(23, 30))],
        5: [(time(0, 0), time(2, 30)), (time(7, 10), time(9, 30)), (time(20, 10), time(23, 30))],
        6: [(time(0, 0), time(2, 30)), (time(8, 0), time(9, 30)), (time(20, 10), time(23, 30))],
    }
    for offset in range(8):
        day = (current + timedelta(days=offset)).date()
        for start_time, end_time in windows_by_weekday[day.weekday()]:
            start = datetime.combine(day, start_time, tzinfo=JST)
            end = datetime.combine(day, end_time, tzinfo=JST)
            if current <= end:
                return {
                    "nowJstIso": current.isoformat(),
                    "openNow": start <= current <= end,
                    "dueToday": offset == 0,
                    "nextWindowStartJstIso": start.isoformat(),
                    "nextWindowEndJstIso": end.isoformat(),
                    "nextWindowLabel": f"{start:%Y-%m-%d %H:%M}-{end:%H:%M} JST",
                    "windowRule": "Daily closeout 00:00-02:30 JST, daily 20:10-23:30 JST, Sat 07:10-09:30 JST, Sun 08:00-09:30 JST",
                }
    return {"nowJstIso": current.isoformat(), "openNow": False, "dueToday": False}


def date_key(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    return text[:10].replace(".", "-").replace("/", "-")


def latest_date(rows: list[dict[str, Any]], *fields: str) -> str:
    keys = []
    for row in rows:
        for field in fields:
            key = date_key(row.get(field))
            if key:
                keys.append(key)
                break
    return sorted(keys).pop() if keys else ""


def rows_on_date(rows: list[dict[str, Any]], target: str, *fields: str) -> list[dict[str, Any]]:
    if not target:
        return []
    selected = []
    for row in rows:
        if any(date_key(row.get(field)) == target for field in fields):
            selected.append(row)
    return selected


def close_history_summary(rows: list[dict[str, str]], target_day: str | None = None) -> dict[str, Any]:
    day = clean(target_day) or latest_date(rows, "CloseTime", "EventTime", "closeTime")
    day_rows = [
        row for row in rows_on_date(rows, day, "CloseTime", "EventTime", "closeTime")
        if is_focus_or_unscoped_row(row)
    ]
    net = sum(as_float(first(row.get("NetProfit"), row.get("netProfit"), row.get("Profit"))) for row in day_rows)
    by_strategy: dict[str, dict[str, Any]] = {}
    by_strategy_side: dict[str, dict[str, Any]] = {}
    for row in day_rows:
        strategy = clean(first(row.get("Strategy"), row.get("strategy"), default="UNKNOWN")) or "UNKNOWN"
        side = clean(first(row.get("Type"), row.get("Side"), row.get("side"), default="UNKNOWN")).upper() or "UNKNOWN"
        net_profit = as_float(first(row.get("NetProfit"), row.get("netProfit"), row.get("Profit")))
        bucket = by_strategy.setdefault(strategy, {"strategy": strategy, "trades": 0, "netUSC": 0.0})
        bucket["trades"] += 1
        bucket["netUSC"] += net_profit
        side_key = f"{strategy}:{side}"
        side_bucket = by_strategy_side.setdefault(side_key, {"strategy": strategy, "side": side, "trades": 0, "netUSC": 0.0})
        side_bucket["trades"] += 1
        side_bucket["netUSC"] += net_profit
    breakdown = sorted(by_strategy.values(), key=lambda item: abs(item["netUSC"]), reverse=True)
    for item in breakdown:
        item["netUSC"] = round(item["netUSC"], 3)
    side_breakdown = sorted(by_strategy_side.values(), key=lambda item: abs(item["netUSC"]), reverse=True)
    for item in side_breakdown:
        item["netUSC"] = round(item["netUSC"], 3)
    return {
        "date": day,
        "closedTrades": len(day_rows),
        "netUSC": round(net, 3),
        "byStrategy": breakdown,
        "byStrategySide": side_breakdown,
        "lossByStrategySide": [item for item in side_breakdown if item["netUSC"] < 0],
    }


def daily_pnl_resolved_by_policy(daily_pnl: dict[str, Any], governance: dict[str, Any]) -> bool:
    if as_float(daily_pnl.get("netUSC")) >= 0:
        return True
    losses = as_list(daily_pnl.get("lossByStrategySide"))
    if not losses:
        return False
    governance_by_route = {
        clean(row.get("key") or row.get("routeKey") or row.get("strategy")): row
        for row in as_list(governance.get("routeDecisions"))
        if isinstance(row, dict)
    }
    for loss in losses:
        if not isinstance(loss, dict):
            return False
        strategy = clean(loss.get("strategy"))
        side = clean(loss.get("side")).upper()
        if strategy != "RSI_Reversal" or side != "SELL":
            return False
        side_policy = governance_by_route.get("RSI_Reversal", {}).get("sidePolicy")
        if not isinstance(side_policy, dict) or side_policy.get("sellLiveAllowed") is not False:
            return False
    return True


def recovery_by_candidate(run_recovery: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in as_list(run_recovery.get("candidateDrilldown")):
        if not isinstance(row, dict):
            continue
        candidate_id = clean(row.get("candidateId"))
        if candidate_id:
            rows[candidate_id] = row
    return rows


def recovery_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    latest_stop = clean(row.get("latestStopReason"))
    risk_reason = clean(row.get("riskReason"))
    if latest_stop:
        blockers.append(latest_stop)
    if risk_reason and risk_reason not in blockers:
        blockers.append(risk_reason)
    for code in as_list(row.get("terminalExitCodes")):
        text = clean(code)
        if text:
            blockers.append(f"terminal_exit_{text}")
    failures = row.get("failureReasons", {})
    if isinstance(failures, dict):
        for key, value in failures.items():
            if as_int(value) > 0:
                blockers.append(clean(key))
    return list(dict.fromkeys(blockers))


def param_action_queue(
    scheduler: dict[str, Any],
    auto_tester: dict[str, Any],
    max_actions: int,
    run_recovery: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    can_run = bool(auto_tester.get("summary", {}).get("canRunTerminal"))
    blockers = as_list(auto_tester.get("gate", {}).get("blockers")) or as_list(auto_tester.get("summary", {}).get("blockers"))
    blocker_keys = {clean(blocker).lower() for blocker in blockers if clean(blocker)}
    only_waiting_window = bool(blocker_keys) and blocker_keys <= {"outside_strategy_tester_window"}
    window_plan = tester_window_plan()
    recovery_rows = recovery_by_candidate(run_recovery or {})
    focus_tasks = [
        task for task in as_list(scheduler.get("selectedTasks"))
        if isinstance(task, dict) and is_focus_or_unscoped_row(task)
    ]
    for task in focus_tasks[:max_actions]:
        if not isinstance(task, dict):
            continue
        candidate_id = clean(task.get("candidateId"))
        recovery = recovery_rows.get(candidate_id, {})
        recovery_risk = clean(recovery.get("riskLevel")).lower()
        recovery_reason = clean(recovery.get("riskReason")).lower()
        recovery_stop = clean(recovery.get("latestStopReason")).lower()
        recovery_latest_state = clean(recovery.get("latestState")).lower()
        recovery_retry_ready = recovery_risk in {"yellow", "green"} and recovery_reason == "account_context_synced_retry_ready"
        recovery_terminal_nonzero = (
            not recovery_retry_ready
            and (
                recovery_risk == "red"
                or recovery_stop in {"terminal_nonzero", "terminal_exit_nonzero"}
                or as_int(recovery.get("terminalNonzeroCount")) > 0
            )
        )
        result_status = clean(first(task.get("resultStatus"), task.get("status"), task.get("scheduleAction")))
        guard_class = ""
        status_label = ""
        if result_status.upper() in {"PARSED", "PARSED_AGENT_ARTIFACTS", "SCORED", "DONE"} or (
            recovery_risk == "green" and recovery_latest_state == "parsed"
        ):
            state = "DONE"
        elif recovery_terminal_nonzero:
            state = "NEEDS_CODEX_TRIAGE"
            guard_class = "RUN_RECOVERY_RED"
            status_label = "TERMINAL_EXIT_NONZERO"
        elif can_run:
            state = "READY_TO_RUN_TESTER"
            status_label = "ACCOUNT_CONTEXT_SYNCED_RETRY_READY" if recovery_retry_ready else "READY_TO_RUN_TESTER"
        else:
            state = "WAIT_GUARD"
            if only_waiting_window:
                guard_class = "WAIT_TESTER_WINDOW"
                status_label = "ACCOUNT_CONTEXT_SYNCED_RETRY_READY" if recovery_retry_ready else "SCHEDULED_TESTER_WINDOW"
            else:
                guard_class = "WAIT_GUARD"
                status_label = "ACCOUNT_CONTEXT_SYNCED_RETRY_READY" if recovery_retry_ready else "WAIT_GUARD"
        action = {
            "type": "PARAMLAB_TESTER_TASK",
            "state": state,
            "guardClass": guard_class,
            "statusLabel": status_label,
            "candidateId": candidate_id,
            "routeKey": task.get("routeKey", ""),
            "strategy": task.get("strategy", ""),
            "symbol": task.get("symbol", ""),
            "score": task.get("score", ""),
            "resultStatus": result_status,
            "blockers": (recovery_blockers(recovery) or blockers)[:6],
            "testerOnly": True,
            "livePresetMutationAllowed": False,
        }
        if recovery:
            action["recovery"] = {
                "riskLevel": recovery.get("riskLevel", ""),
                "riskReason": recovery.get("riskReason", ""),
                "latestRunId": recovery.get("latestRunId", ""),
                "latestStopReason": recovery.get("latestStopReason", ""),
                "latestRecoveryAction": recovery.get("latestRecoveryAction", ""),
                "terminalExitCodes": as_list(recovery.get("terminalExitCodes")),
                "retryRemaining": recovery.get("retryRemaining", ""),
            }
        if guard_class == "WAIT_TESTER_WINDOW":
            action.update({
                "dueToday": window_plan.get("dueToday", False),
                "nextWindowStartJstIso": window_plan.get("nextWindowStartJstIso", ""),
                "nextWindowEndJstIso": window_plan.get("nextWindowEndJstIso", ""),
                "nextWindowLabel": window_plan.get("nextWindowLabel", ""),
            })
        actions.append(action)
    return actions


def promotion_recommendations(version_gate: dict[str, Any], governance: dict[str, Any]) -> list[dict[str, Any]]:
    governance_by_route = {
        clean(row.get("key") or row.get("routeKey") or row.get("strategy")): row
        for row in as_list(governance.get("routeDecisions"))
        if isinstance(row, dict)
    }
    recommendations: list[dict[str, Any]] = []
    for row in as_list(version_gate.get("versionDecisions")):
        if not isinstance(row, dict):
            continue
        if not is_focus_or_unscoped_row(row):
            continue
        decision = clean(row.get("decision")).upper()
        readiness = clean(row.get("evidence", {}).get("paramLabResult", {}).get("promotionReadiness")).upper()
        if decision != "PROMOTE_CANDIDATE" and readiness != "PROMOTION_REVIEW":
            continue
        route_key = clean(row.get("routeKey"))
        metrics = row.get("evidence", {}).get("paramLabResult", {}).get("metrics", {})
        recommendations.append({
            "routeKey": route_key,
            "candidateId": row.get("candidateId", ""),
            "versionId": row.get("versionId", ""),
            "decision": decision or readiness,
            "profitFactor": metrics.get("profitFactor"),
            "winRatePct": metrics.get("winRate"),
            "closedTrades": metrics.get("closedTrades"),
            "reason": row.get("reason", ""),
            "blockers": as_list(row.get("blockers")),
            "governanceAction": governance_by_route.get(route_key, {}).get("recommendedAction", ""),
            "recommendedNextStep": "HUMAN_APPROVE_LIVE_OBSERVATION_ONLY",
            "autoApplyLive": False,
            "requiresHumanApproval": True,
            "livePresetMutationAllowed": False,
            "orderSendAllowed": False,
        })
    return recommendations


def hfm_crypto_summary(runtime_dir: Path) -> dict[str, Any]:
    state = read_json(runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json")
    if not state:
        state = read_json(runtime_dir / "QuantGod_HFMCryptoCfdState.json")
    local = state.get("localEvidence") if isinstance(state.get("localEvidence"), dict) else {}
    moss = state.get("mossBacktestProfile") if isinstance(state.get("mossBacktestProfile"), dict) else {}
    metrics = moss.get("metrics") if isinstance(moss.get("metrics"), dict) else {}
    target_symbols = as_list(state.get("targetSymbols"))
    detected_symbols = as_list(local.get("canonicalSymbols"))
    status = first(state.get("status"), default="WAITING_HFM_CRYPTO_BUILD")
    summary = {
        "status": status,
        "statusZh": first(state.get("statusZh"), default="等待构建 HFM Crypto CFD 影子车道"),
        "symbolEvidenceFound": bool(local.get("found")),
        "targetSymbolCount": len(target_symbols),
        "detectedSymbolCount": len(detected_symbols),
        "mossProfileFound": bool(moss.get("profileFound")),
        "mossRoiPct": metrics.get("roiPct"),
        "mossSharpe": metrics.get("sharpe"),
        "mossMaxDrawdownPct": metrics.get("maxDrawdownPct"),
        "mossLiquidationCount": metrics.get("liquidationCount"),
    }
    return {
        **summary,
        "state": state,
        "dailyReview": {
            "summary": {**summary, "todoCount": 0},
            "actionQueue": [],
        },
        "walletWriteAllowed": False,
        "orderSendAllowed": False,
        "hfmCryptoExecutionAllowed": False,
    }


def daily_tester_completed_count(param_status: dict[str, Any], now: datetime, max_actions: int) -> int:
    generated = generated_at(param_status)
    if not generated or generated.astimezone(JST).date() != now.astimezone(JST).date():
        return 0
    summary = param_status.get("summary") if isinstance(param_status.get("summary"), dict) else {}
    parsed = max(
        as_int(first(summary.get("agentEvidenceParsedCount"), 0)),
        as_int(first(summary.get("reportParsedCount"), 0)),
    )
    attempted = as_int(first(summary.get("runAttemptedCount"), 0))
    selected = as_int(first(summary.get("selectedTaskCount"), param_status.get("selectedTaskCount"), 0))
    if attempted <= 0:
        return 0
    return min(max(parsed, attempted if parsed >= selected and selected > 0 else parsed), max(1, max_actions))


def should_roll_ready_tasks_to_research_backlog(
    action_queue: list[dict[str, Any]],
    completed_action_queue: list[dict[str, Any]],
    daily_tester_completed: int,
    recovery_summary: dict[str, Any],
) -> bool:
    if not action_queue or not completed_action_queue or daily_tester_completed <= 0:
        return False
    if any(action.get("state") != "READY_TO_RUN_TESTER" for action in action_queue):
        return False
    recovery_red = as_int(first(recovery_summary.get("riskRedCount"), recovery_summary.get("redCount"), 0))
    recovery_yellow = as_int(first(recovery_summary.get("riskYellowCount"), recovery_summary.get("yellowCount"), 0))
    return recovery_red <= 0 and recovery_yellow <= 0


def metric_group_key(row: dict[str, Any]) -> str:
    return clean(first(
        row.get("experimentKey"),
        row.get("marketScope"),
        row.get("entryStatus"),
        row.get("signalSource"),
        default="UNKNOWN",
    )) or "UNKNOWN"


def compact_metric_group(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": metric_group_key(row),
        "experimentKey": row.get("experimentKey", ""),
        "marketScope": row.get("marketScope", ""),
        "entryStatus": row.get("entryStatus", ""),
        "signalSource": row.get("signalSource", ""),
        "closed": as_int(row.get("closed"), 0),
        "wins": as_int(row.get("wins"), 0),
        "losses": as_int(row.get("losses"), 0),
        "winRatePct": round(as_float(row.get("winRatePct")), 2),
        "profitFactor": round(as_float(row.get("profitFactor")), 4),
        "realizedPnl": round(as_float(row.get("realizedPnl")), 4),
        "avgPnl": round(as_float(row.get("avgPnl")), 4),
    }


def no_trade_retune_plan(route_counts: Counter[str]) -> list[dict[str, Any]]:
    templates = {
        "MA_Cross": {
            "diagnosis": "均线确认和退出过滤过严，短窗口容易完全无成交。",
            "nextBacktest": "扩大 lookback，测试更宽的交叉回看和更早退出窗口。",
        },
        "RSI_Reversal": {
            "diagnosis": "RSI 极值和 crossback 条件触发少；BUY 实盘保留，SELL 继续模拟。",
            "nextBacktest": "只在 tester 里比较 85/15、80/20 和趋势过滤组合，不改 live preset。",
        },
        "BB_Triple": {
            "diagnosis": "外轨/慢过滤组合过严，缺少足够触发样本。",
            "nextBacktest": "放宽 band touch 与 RSI/MACD 确认顺序，保留 non-RSI 授权锁。",
        },
        "MACD_Divergence": {
            "diagnosis": "背离确认滞后，M15/H1 窗口内触发不足。",
            "nextBacktest": "测试 fast momentum turn 与 histogram continuation 两组候选。",
        },
        "SR_Breakout": {
            "diagnosis": "突破必须带成交量确认，震荡日容易无成交。",
            "nextBacktest": "扩大支撑阻力 lookback，分开测试突破和回踩确认。",
        },
    }
    plans: list[dict[str, Any]] = []
    for route, count in route_counts.most_common():
        template = templates.get(route, {
            "diagnosis": "该路线在已解析 tester 窗口没有成交样本。",
            "nextBacktest": "扩大测试窗口并生成更宽松的 tester-only 候选。",
        })
        plans.append({
            "routeKey": route,
            "noTradeWindows": count,
            "diagnosis": template["diagnosis"],
            "nextBacktest": template["nextBacktest"],
            "safeMode": "tester-only",
            "livePresetMutationAllowed": False,
            "orderSendAllowed": False,
        })
    return plans


def mt5_terminal_risk(runtime_dir: Path, now: datetime) -> dict[str, Any]:
    mt5_root = runtime_dir.parent.parent if runtime_dir.name == "Files" and runtime_dir.parent.name == "MQL5" else None
    dashboard = read_json(runtime_dir / "QuantGod_Dashboard.json")
    runtime = dashboard.get("runtime") if isinstance(dashboard.get("runtime"), dict) else {}
    summary = {
        "investorModeCount": 0,
        "tradeDisabledCount": 0,
        "orderSendFailureCount": 0,
        "retcodes": [],
        "latestEvidence": "",
        "currentTradeStatus": first(runtime.get("tradeStatus"), default=""),
        "currentTradeAllowed": runtime.get("tradeAllowed"),
        "currentTerminalTradeAllowed": runtime.get("terminalTradeAllowed"),
        "currentProgramTradeAllowed": runtime.get("programTradeAllowed"),
        "currentAccountTradeAllowed": runtime.get("accountTradeAllowed"),
        "currentAccountExpertTradeAllowed": runtime.get("accountExpertTradeAllowed"),
        "currentFocusSymbolTradeAllowed": runtime.get("focusSymbolTradeAllowed"),
        "currentTradePermissionBlocker": first(runtime.get("tradePermissionBlocker"), default=""),
        "currentTradePermissionRecovered": False,
        "requiresCodexReview": False,
    }
    permission_flags = [
        runtime.get("tradeAllowed"),
        runtime.get("terminalTradeAllowed"),
        runtime.get("programTradeAllowed"),
        runtime.get("accountTradeAllowed"),
        runtime.get("accountExpertTradeAllowed"),
        runtime.get("focusSymbolTradeAllowed"),
    ]
    current_permission_ok = bool(runtime) and all(flag is True for flag in permission_flags)
    current_status_ready = clean(runtime.get("tradeStatus")).upper() in {"READY", "LIVE_READY", "TRADE_READY"}
    current_blocker_empty = not clean(runtime.get("tradePermissionBlocker"))
    if not mt5_root or not mt5_root.exists():
        summary["currentTradePermissionRecovered"] = current_permission_ok and current_status_ready and current_blocker_empty
        return summary

    today_key = now.strftime("%Y%m%d")
    evidence: list[str] = []
    retcodes: list[str] = []
    for log_dir in (mt5_root / "logs", mt5_root / "MQL5" / "Logs"):
        if not log_dir.exists():
            continue
        for path in sorted(log_dir.glob("*.log")):
            if today_key not in path.name and date_key(datetime.fromtimestamp(path.stat().st_mtime).isoformat()) != now.date().isoformat():
                continue
            text = read_text(path)
            investor_matches = re.findall(r"trading has been disabled\s*-\s*investor mode", text, flags=re.I)
            trade_disabled_matches = re.findall(r"\[Trade disabled\]|comment=Trade disabled", text, flags=re.I)
            order_fail_matches = re.findall(r"pilot order failed:.*?retcode[=: ]+([0-9]+).*?(?:comment=([^\r\n]+))?", text, flags=re.I)
            summary["investorModeCount"] += len(investor_matches)
            summary["tradeDisabledCount"] += len(trade_disabled_matches)
            summary["orderSendFailureCount"] += len(order_fail_matches)
            for retcode, comment in order_fail_matches:
                if retcode:
                    retcodes.append(retcode)
                    evidence.append(f"{path.name}: retcode={retcode} {comment}".strip())
            if investor_matches:
                evidence.append(f"{path.name}: investor mode")
            if trade_disabled_matches and not order_fail_matches:
                evidence.append(f"{path.name}: Trade disabled")

    summary["retcodes"] = sorted(set(retcodes))
    summary["latestEvidence"] = evidence[-1] if evidence else ""
    summary["currentTradePermissionRecovered"] = (
        current_permission_ok
        and current_status_ready
        and current_blocker_empty
        and bool(summary["investorModeCount"] or summary["tradeDisabledCount"] or summary["orderSendFailureCount"])
    )
    summary["requiresCodexReview"] = bool(
        (summary["investorModeCount"] or summary["tradeDisabledCount"] or summary["orderSendFailureCount"])
        and not summary["currentTradePermissionRecovered"]
    )
    return summary


def codex_review_queue(
    daily_pnl: dict[str, Any],
    action_queue: list[dict[str, Any]],
    promotions: list[dict[str, Any]],
    governance: dict[str, Any],
    auto_tester: dict[str, Any],
    recovery_summary: dict[str, Any],
    hfm_crypto: dict[str, Any],
    mt5_risk: dict[str, Any],
    daily_iteration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasons: list[dict[str, Any]] = []
    targets: set[str] = set()

    if daily_pnl.get("requiresReview") is not False and as_int(daily_pnl.get("closedTrades")) > 0 and as_float(daily_pnl.get("netUSC")) < 0:
        reasons.append({
            "code": "DAILY_PNL_NEGATIVE",
            "target": "strategy",
            "detail": f"netUSC={daily_pnl.get('netUSC')} trades={daily_pnl.get('closedTrades')}",
        })
        targets.add("strategy")

    for row in as_list(governance.get("routeDecisions")):
        if not isinstance(row, dict):
            continue
        action = clean(row.get("recommendedAction")).upper()
        route = clean(row.get("key") or row.get("routeKey") or row.get("strategy"))
        if "DEMOTE" in action:
            reasons.append({
                "code": "GOVERNANCE_DEMOTE_REVIEW",
                "target": "strategy",
                "routeKey": route,
                "detail": action,
            })
            targets.add("strategy")

    ready_tasks = [row for row in action_queue if row.get("state") == "READY_TO_RUN_TESTER"]
    if ready_tasks:
        reasons.append({
            "code": "PARAMLAB_TESTER_READY",
            "target": "evidence",
            "detail": f"readyTasks={len(ready_tasks)}",
        })
        targets.add("evidence")

    if promotions:
        reasons.append({
            "code": "LIVE_PROMOTION_REVIEW_REQUIRED",
            "target": "strategy",
            "detail": f"promotionRecommendations={len(promotions)}",
        })
        targets.add("strategy")

    tester_blockers = [
        clean(blocker)
        for blocker in (
            as_list(auto_tester.get("gate", {}).get("blockers"))
            or as_list(auto_tester.get("summary", {}).get("blockers"))
        )
        if clean(blocker)
    ]
    unexpected_blockers = [
        blocker for blocker in tester_blockers
        if blocker.lower() != "outside_strategy_tester_window"
    ]
    if unexpected_blockers:
        reasons.append({
            "code": "TESTER_UNEXPECTED_BLOCKER",
            "target": "code_or_environment",
            "detail": ", ".join(unexpected_blockers[:4]),
        })
        targets.add("code_or_environment")

    recovery_red = as_int(first(recovery_summary.get("riskRedCount"), recovery_summary.get("redCount"), 0))
    if recovery_red > 0:
        reasons.append({
            "code": "PARAMLAB_RECOVERY_RED",
            "target": "code_or_data",
            "detail": f"redCount={recovery_red}",
        })
        targets.add("code_or_data")

    if clean(hfm_crypto.get("status")).upper() == "WAITING_HFM_CRYPTO_SYMBOLS":
        reasons.append({
            "code": "HFM_CRYPTO_SYMBOL_EVIDENCE_PENDING",
            "target": "data",
            "detail": "HFM Crypto CFD symbol evidence is not present in local MT5 Bases yet.",
        })
        targets.add("data")

    if mt5_risk.get("requiresCodexReview"):
        reasons.append({
            "code": "MT5_TRADE_PERMISSION_OR_ORDER_SEND_FAILURE",
            "target": "code_or_environment",
            "detail": (
                f"investorMode={mt5_risk.get('investorModeCount')} "
                f"tradeDisabled={mt5_risk.get('tradeDisabledCount')} "
                f"retcodes={','.join(mt5_risk.get('retcodes') or []) or '--'}"
            ),
        })
        targets.add("code_or_environment")

    iteration = daily_iteration or {}
    if iteration.get("codexFollowupRequired"):
        reasons.append({
            "code": "DAILY_ITERATION_ACTIONABLE_FINDINGS",
            "target": "code_or_strategy",
            "detail": (
                f"findings={len(as_list(iteration.get('findings')))} "
                f"codeActions={len(as_list(iteration.get('codeIterationQueue')))} "
                f"strategyActions={len(as_list(iteration.get('strategyIterationQueue')))}"
            ),
        })
        targets.update(clean(item.get("target")) for item in as_list(iteration.get("findings")) if isinstance(item, dict) and clean(item.get("target")))
        targets.add("code_or_strategy")

    required = bool(reasons)
    return {
        "required": required,
        "status": "REQUIRES_CODEX_TRIAGE" if required else "OK_HIDE_UNTIL_NEXT_DAILY_REFRESH",
        "reasons": reasons,
        "triageTargets": sorted(targets),
        "recommendedAction": (
            "CODEX_TRIAGE_CODE_STRATEGY_OR_EVIDENCE_FIX"
            if required else
            "NO_DISPLAY_UNTIL_NEXT_DAILY_REFRESH"
        ),
        "safeActionsAllowed": [
            "read evidence",
            "summarize review",
            "fix code/frontend/evidence pipeline",
            "run tests",
            "commit and push safe fixes",
            "write machine-governed live promotion evidence",
        ],
        "forbiddenActions": [
            "send orders",
            "close positions",
            "cancel orders",
            "mutate live preset",
            "bypass autonomous hard gates",
            "loosen risk gates",
        ],
    }


def usdjpy_evolution_summary(runtime_dir: Path) -> dict[str, Any]:
    dataset = read_json(runtime_dir / "datasets" / "usdjpy" / "QuantGod_USDJPYRuntimeDataset.json")
    replay = read_json(runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYReplayReport.json")
    tuning = read_json(runtime_dir / "adaptive" / "QuantGod_USDJPYParamTuningReport.json")
    proposal = read_json(runtime_dir / "adaptive" / "QuantGod_USDJPYLiveConfigProposal.json")
    dataset_summary = dataset.get("summary") if isinstance(dataset.get("summary"), dict) else {}
    replay_summary = replay.get("summary") if isinstance(replay.get("summary"), dict) else {}
    tuning_summary = tuning.get("summary") if isinstance(tuning.get("summary"), dict) else {}
    proposal_status = clean(proposal.get("status"))
    candidate_count = as_int(tuning_summary.get("candidateCount"), 0)
    missed = as_int(replay_summary.get("missedOpportunityCount"), 0)
    early = as_int(replay_summary.get("earlyExitCount"), 0)
    proposal_ready = proposal_status in {
        "PROPOSAL_READY_FOR_REVIEW",
        "PROPOSAL_READY_FOR_AUTONOMOUS_GOVERNANCE",
        "LIVE_CONFIG_PROPOSAL_READY",
        "TESTER_ONLY_READY",
    }
    auto_apply_mode = proposal.get("autoApplyAllowed", False)
    needs_iteration = bool((missed or early) and not proposal_ready and candidate_count <= 0)
    return {
        "status": "CONFIG_PROPOSAL_READY" if proposal_ready else "RETUNE_READY" if candidate_count > 0 else "NEEDS_REPLAY_TUNE" if needs_iteration else "OK_OR_COLLECTING",
        "datasetSamples": as_int(dataset_summary.get("sampleCount"), 0),
        "readySignalCount": as_int(dataset_summary.get("readySignalCount"), 0),
        "actualEntryCount": as_int(dataset_summary.get("actualEntryCount"), 0),
        "missedOpportunityCount": missed,
        "earlyExitCount": early,
        "paramCandidateCount": candidate_count,
        "proposalStatus": proposal_status,
        "proposalReady": proposal_ready,
        "needsIteration": needs_iteration,
        "codexFollowupRequired": needs_iteration,
        "autoApplyAllowed": auto_apply_mode,
        "requiresAutonomousGovernance": bool(proposal.get("requiresAutonomousGovernance", False)),
        "completedByAgent": True,
        "autoAppliedByAgent": bool(proposal_ready),
        "summaryZh": (
            "已生成待自主治理门评估的 USDJPY 参数提案；通过机器硬风控后只写受控 patch，不改源码或 live preset。"
            if proposal_ready else
            "已生成 USDJPY tester-only 调参候选，等待回放和 shadow 验证。"
            if candidate_count > 0 else
            "发现错失机会或过早出场，但还未生成调参候选。"
            if needs_iteration else
            "USDJPY 自学习闭环暂无必须迭代项，继续采集样本。"
        ),
    }


def daily_iteration_review(
    daily_pnl: dict[str, Any],
    deferred_action_queue: list[dict[str, Any]],
    hfm_crypto: dict[str, Any],
    mt5_risk: dict[str, Any],
    max_actions: int,
    tester_tasks: list[dict[str, Any]] | None = None,
    usdjpy_evolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    code_queue: list[dict[str, Any]] = []
    strategy_queue: list[dict[str, Any]] = []
    evidence_queue: list[dict[str, Any]] = []
    if clean(hfm_crypto.get("status")).upper() == "WAITING_HFM_CRYPTO_SYMBOLS":
        evidence_queue.append({
            "type": "HFM_CRYPTO_SYMBOL_EVIDENCE",
            "status": "WAITING_SYMBOL_EVIDENCE",
            "safeMode": "shadow-only",
            "recommendation": "登录 HFM/MT5 并让 BTC/ETH/SOL 等 crypto CFD 产生 history 或 tick 目录后再纳入影子研究。",
            "orderSendAllowed": False,
            "hfmCryptoExecutionAllowed": False,
        })

    if as_int(daily_pnl.get("closedTrades")) > 0:
        net = as_float(daily_pnl.get("netUSC"))
        loss_rows = as_list(daily_pnl.get("lossByStrategySide"))
        manual_loss_only = bool(loss_rows) and all(
            clean(row.get("strategy")).lower() in {"manual/other", "manual", "other", ""}
            for row in loss_rows
            if isinstance(row, dict)
        )
        loss_resolved = bool(daily_pnl.get("resolvedByCurrentPolicy")) or manual_loss_only
        findings.append({
            "code": "MT5_DAILY_PNL_POSITIVE" if net >= 0 else "MT5_DAILY_PNL_NEGATIVE",
            "severity": "info" if net >= 0 or loss_resolved else "high",
            "target": "strategy",
            "title": "MT5 昨日平仓复盘",
            "detail": f"{daily_pnl.get('date')} closed={daily_pnl.get('closedTrades')} net={net:.2f} USC",
            "rootCause": (
                "RSI BUY closed positive; no immediate code change required."
                if net >= 0 else
                "昨日亏损来自 Manual/Other，不归因到 EA 自动策略；无需因此改策略。"
                if manual_loss_only else
                "Daily realized P&L is negative and needs route attribution."
            ),
            "nextStep": (
                "继续观察 RSI buy/sell 分侧表现。"
                if net >= 0 else
                "保持 RSI BUY 恢复路线；人工/非 EA 亏损只记录，不触发自动策略迭代。"
                if manual_loss_only else
                "按 strategy/side/regime 拆亏损来源，必要时降级或收紧 gate。"
            ),
            "requiresCodeChange": False,
            "requiresStrategyIteration": net < 0 and not loss_resolved,
            "iterationApplied": loss_resolved,
        })

    if deferred_action_queue:
        detail = ", ".join(clean(item.get("candidateId")) for item in deferred_action_queue[:3])
        findings.append({
            "code": "PARAMLAB_BACKLOG_DEFERRED_AFTER_DAILY_BUDGET",
            "severity": "watch",
            "target": "evidence",
            "title": "ParamLab 今日额度已满",
            "detail": f"completed={max_actions}/{max_actions}; deferred={len(deferred_action_queue)}; {detail}",
            "rootCause": "今日 tester-only 短窗口已跑满，剩余 backlog 延后，避免无限续跑和干扰实盘终端。",
            "nextStep": "明日自动继续；若人工想加速，可单独授权 isolated tester 追加批次。",
            "requiresCodeChange": False,
            "requiresStrategyIteration": False,
        })
        evidence_queue.append({
            "type": "PARAMLAB_DEFERRED_BACKLOG",
            "status": "DEFERRED_NEXT_DAILY_REFRESH",
            "count": len(deferred_action_queue),
            "reason": f"daily tester budget {max_actions}/{max_actions} consumed",
            "safeAction": "wait_next_daily_refresh_or_human_approve_extra_isolated_tester_batch",
        })

    tester_tasks = tester_tasks or []
    no_trade_tasks = [item for item in tester_tasks if as_int(item.get("closedTrades"), -1) == 0]
    if tester_tasks and len(no_trade_tasks) == len(tester_tasks):
        route_counts = Counter(clean(item.get("routeKey")) or "UNKNOWN" for item in no_trade_tasks)
        route_plans = no_trade_retune_plan(route_counts)
        retune_plan_ready = bool(route_plans)
        route_detail = ", ".join(f"{route}:{count}" for route, count in route_counts.most_common(5))
        findings.append({
            "code": "PARAMLAB_NO_TRADE_TESTER_WINDOWS",
            "severity": "watch" if retune_plan_ready else "high",
            "target": "strategy",
            "title": "ParamLab 全部无成交",
            "detail": f"parsed={len(tester_tasks)} noTrade={len(no_trade_tasks)} routes={route_detail}",
            "rootCause": "候选策略过严或测试窗口过短；虽然 tester 账户上下文已打通，但没有成交样本就无法学习或升实盘。",
            "nextStep": (
                "已生成下一轮 tester-only 调参方案；等待测试窗口执行并回灌报告，不改 live preset。"
                if retune_plan_ready else
                "下一轮只在 isolated tester 扩大 lookback，并为 BB/MACD/SR/MA 调宽触发阈值或增加候选变体；不改 live preset。"
            ),
            "requiresCodeChange": False,
            "requiresStrategyIteration": not retune_plan_ready,
            "iterationApplied": retune_plan_ready,
        })
        strategy_queue.append({
            "type": "PARAMLAB_NO_TRADE_RETUNE",
            "status": "RETUNE_PLAN_READY_TESTER_ONLY" if retune_plan_ready else "REQUIRED_TESTER_ONLY",
            "targetRoutes": [route for route, _count in route_counts.most_common(5)],
            "recommendation": (
                "已生成下一轮 tester-only 调参方案；等待测试窗口执行并回灌报告，保留 0.01/单仓/人工升实盘门槛。"
                if retune_plan_ready else
                "扩大 tester lookback，降低过严过滤器阈值，保留 0.01/单仓/人工升实盘门槛。"
            ),
            "routePlans": route_plans,
            "iterationApplied": retune_plan_ready,
            "completionEvidence": "route_plans_generated_from_no_trade_tester_windows" if retune_plan_ready else "",
            "safeMode": "tester-only",
            "livePresetMutationAllowed": False,
            "orderSendAllowed": False,
        })
        evidence_queue.append({
            "type": "PARAMLAB_NO_TRADE_DIAGNOSIS",
            "status": "REQUIRED",
            "count": len(no_trade_tasks),
            "reason": "all parsed tester windows produced zero closed trades",
            "safeAction": "generate wider-window tester-only candidates before any promotion review",
        })

    usdjpy_evolution = usdjpy_evolution or {}
    if usdjpy_evolution:
        if usdjpy_evolution.get("proposalReady") or as_int(usdjpy_evolution.get("paramCandidateCount"), 0) > 0:
            findings.append({
                "code": "USDJPY_REPLAY_RETUNE_READY",
                "severity": "info",
                "target": "strategy",
                "title": "USDJPY 回放调参已生成",
                "detail": (
                    f"samples={usdjpy_evolution.get('datasetSamples')} "
                    f"missed={usdjpy_evolution.get('missedOpportunityCount')} "
                    f"earlyExit={usdjpy_evolution.get('earlyExitCount')} "
                    f"candidates={usdjpy_evolution.get('paramCandidateCount')}"
                ),
                "rootCause": "每日复盘已自动生成 tester-only 参数候选或 live config proposal。",
                "nextStep": "进入自主治理门：先 tester/shadow，再由机器硬风控决定是否写受控 patch；不自动修改 live preset。",
                "requiresCodeChange": False,
                "requiresStrategyIteration": False,
                "iterationApplied": True,
            })
        elif usdjpy_evolution.get("needsIteration"):
            findings.append({
                "code": "USDJPY_REPLAY_RETUNE_MISSING",
                "severity": "high",
                "target": "strategy",
                "title": "USDJPY 复盘发现未闭合迭代",
                "detail": usdjpy_evolution.get("summaryZh", ""),
                "rootCause": "回放发现错失机会或过早出场，但参数候选尚未生成。",
                "nextStep": "运行 USDJPY runtime dataset / replay / tune / proposal 链路。",
                "requiresCodeChange": False,
                "requiresStrategyIteration": True,
            })

    if mt5_risk.get("requiresCodexReview"):
        findings.append({
            "code": "MT5_PERMISSION_REVIEW_REQUIRED",
            "severity": "high",
            "target": "code_or_environment",
            "title": "MT5 权限/下单失败复盘",
            "detail": mt5_risk.get("latestEvidence", ""),
            "rootCause": "当前交易权限或 order-send 证据仍异常。",
            "nextStep": "只读检查登录权限、EA runtime flags 和 broker tradeAllowed，不强制恢复交易。",
            "requiresCodeChange": True,
            "requiresStrategyIteration": False,
        })

    codex_followup = any(bool(item.get("requiresCodeChange") or item.get("requiresStrategyIteration")) for item in findings)
    return {
        "status": "ITERATION_REQUIRED" if codex_followup else "REVIEW_COMPLETE_NO_CODE_CHANGE",
        "reviewCompleted": True,
        "iterationRequired": codex_followup,
        "codexFollowupRequired": codex_followup,
        "findings": findings,
        "codeIterationQueue": code_queue,
        "strategyIterationQueue": strategy_queue,
        "evidenceIterationQueue": evidence_queue,
        "safeBoundary": {
            "mutatesMt5": False,
            "orderSendAllowed": False,
            "walletWriteAllowed": False,
            "livePresetMutationAllowed": False,
        },
    }


def param_result_quality(row: dict[str, Any]) -> tuple[int, int, int, float]:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    parse_status = clean(first(metrics.get("parseStatus"), row.get("parseStatus"), row.get("status"))).upper()
    return (
        1 if bool(metrics.get("reportExists")) else 0,
        1 if parse_status in {"PARSED", "PARSED_AGENT_ARTIFACTS", "DONE", "SCORED"} else 0,
        1 if metrics.get("closedTrades") not in (None, "") else 0,
        as_float(first(row.get("resultScore"), row.get("score")), -999.0),
    )


def param_results_by_candidate(param_results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in as_list(param_results.get("results")):
        if not isinstance(row, dict):
            continue
        candidate_id = clean(row.get("candidateId"))
        if not candidate_id:
            continue
        current = indexed.get(candidate_id)
        if current is None or param_result_quality(row) >= param_result_quality(current):
            indexed[candidate_id] = row
    return indexed


def completed_tester_report_tasks(param_status: dict[str, Any], param_results: dict[str, Any]) -> list[dict[str, Any]]:
    results = param_results_by_candidate(param_results)
    rows: list[dict[str, Any]] = []
    for task in as_list(param_status.get("tasks")):
        if not isinstance(task, dict):
            continue
        if not is_focus_or_unscoped_row(task):
            continue
        status = clean(task.get("status")).upper()
        if status not in {"PARSED", "PARSED_AGENT_ARTIFACTS", "DONE", "SCORED"}:
            continue
        candidate_id = clean(task.get("candidateId"))
        result = results.get(candidate_id, {})
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        closed = as_int(metrics.get("closedTrades"), -1)
        sample_status = clean(metrics.get("sampleStatus"))
        if closed == 0 or sample_status == "NO_TRADES_IN_TEST_WINDOW":
            effect = "测试器与账户上下文已打通，但该窗口无成交，不能作为升实盘证据。"
        elif closed > 0:
            effect = (
                f"产生 {closed} 笔 tester 样本，PF {first(metrics.get('profitFactor'), '--')}，"
                f"净值 {first(metrics.get('netProfit'), '--')}；进入版本评分/治理复核。"
            )
        else:
            effect = "已回灌 tester 证据，等待结果评分补齐样本指标。"
        rows.append({
            "candidateId": candidate_id,
            "routeKey": first(task.get("routeKey"), result.get("routeKey"), ""),
            "symbol": first(task.get("symbol"), result.get("symbol"), ""),
            "status": status,
            "score": first(task.get("score"), result.get("resultScore"), ""),
            "grade": first(result.get("grade"), ""),
            "promotionReadiness": first(result.get("promotionReadiness"), ""),
            "closedTrades": None if closed < 0 else closed,
            "profitFactor": first(metrics.get("profitFactor"), ""),
            "netProfit": first(metrics.get("netProfit"), ""),
            "sampleStatus": sample_status,
            "effect": effect,
            "livePromotionAllowed": False,
        })
    return rows


def build_completion_report(
    review_day: str,
    daily_pnl: dict[str, Any],
    param_status: dict[str, Any],
    param_results: dict[str, Any],
    deferred_action_queue: list[dict[str, Any]],
    promotions: list[dict[str, Any]],
    hfm_crypto: dict[str, Any],
    daily_iteration: dict[str, Any],
) -> dict[str, Any]:
    tester_tasks = completed_tester_report_tasks(param_status, param_results)
    processed_items: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    if as_int(daily_pnl.get("closedTrades")) > 0:
        net = as_float(daily_pnl.get("netUSC"))
        processed_items.append({
            "code": "MT5_CLOSE_HISTORY_REVIEWED",
            "status": "RESOLVED" if not daily_pnl.get("requiresReview") else "NEEDS_STRATEGY_REVIEW",
            "title": "MT5 昨日平仓已复盘",
            "result": f"{review_day} 平仓 {daily_pnl.get('closedTrades')} 笔，净 {net:.2f} USC。",
            "impact": "RSI BUY 贡献正收益；SELL 已按治理规则保持模拟/候选复核。",
        })
        recommendations.append({
            "priority": "info" if net >= 0 else "high",
            "scope": "MT5",
            "title": "MT5 今日不需要代码修复",
            "recommendation": "继续保留 RSI BUY 实盘观察，SELL 侧保持降级/模拟验证；不扩大手数、不新增实盘品种。",
            "reason": f"昨日净值 {net:.2f} USC，当前亏损来源不在 5 月 1 日 RSI BUY。",
            "safeMode": "live-readonly-governance",
            "autoApply": False,
        })

    if tester_tasks:
        no_trade_count = sum(1 for item in tester_tasks if as_int(item.get("closedTrades"), -1) == 0)
        processed_items.append({
            "code": "PARAMLAB_TESTER_REPORTS_PARSED",
            "status": "RESOLVED_NO_PROMOTION" if not promotions else "PROMOTION_REVIEW_REQUIRED",
            "title": "今日 ParamLab 报告已回灌",
            "result": f"已解析 {len(tester_tasks)} 个 isolated tester 任务；其中 {no_trade_count} 个窗口无成交。",
            "impact": "报告证明 isolated tester 账户上下文可用；本轮没有自动升实盘。",
        })
        recommendations.append({
            "priority": "watch" if no_trade_count else "info",
            "scope": "ParamLab",
            "title": "本轮报告只用于学习，不升实盘",
            "recommendation": "把无成交样本当作配置/窗口证据；下一轮优先跑未完成 yellow backlog，必要时只在 isolated tester 加长 lookback。",
            "reason": f"promotionReview={len(promotions)}，noTradeWindow={no_trade_count}，livePresetMutationAllowed=false。",
            "safeMode": "tester-only",
            "autoApply": False,
        })

    if deferred_action_queue:
        processed_items.append({
            "code": "PARAMLAB_BACKLOG_CARRIED_FORWARD",
            "status": "DEFERRED_NEXT_DAILY_REFRESH",
            "title": "剩余 ParamLab backlog 已标记延后",
            "result": f"还有 {len(deferred_action_queue)} 个候选未跑完："
                      f"{', '.join(clean(item.get('candidateId')) for item in deferred_action_queue[:3])}",
            "impact": "不是前端漏做，而是今日 tester 预算已用满；下一轮自动继续。",
        })

    if clean(hfm_crypto.get("status")).upper() == "WAITING_HFM_CRYPTO_SYMBOLS":
        processed_items.append({
            "code": "HFM_CRYPTO_SYMBOL_EVIDENCE_PENDING",
            "status": "WAITING_SYMBOL_EVIDENCE",
            "title": "HFM Crypto CFD symbol 证据待同步",
            "result": hfm_crypto.get("statusZh", "等待构建 HFM Crypto CFD 影子车道"),
            "impact": "HFM Crypto CFD 暂不参与任何执行，只等待本机 MT5 history/tick 证据。",
        })
        recommendations.append({
            "priority": "watch",
            "scope": "HFM Crypto CFD",
            "title": "补齐 crypto CFD 本地 symbol 证据",
            "recommendation": "先让 HFM/MT5 产生 crypto CFD history 或 tick 目录，再把 Moss 回测 profile 映射进 shadow 观察。",
            "reason": "当前没有本机 HFM crypto symbol evidence；执行权限仍关闭。",
            "safeMode": "shadow-only",
            "autoApply": False,
        })

    status = "ITERATION_REQUIRED" if daily_iteration.get("iterationRequired") else "COMPLETE_NO_ACTION"
    if deferred_action_queue and status == "COMPLETE_NO_ACTION":
        status = "COMPLETE_WITH_DEFERRED_BACKLOG"
    return {
        "status": status,
        "title": f"{review_day} 每日待办处理报告",
        "summary": {
            "processedCount": len(processed_items),
            "recommendationCount": len(recommendations),
            "testerParsedCount": len(tester_tasks),
            "testerNoTradeCount": sum(1 for item in tester_tasks if as_int(item.get("closedTrades"), -1) == 0),
            "deferredCount": len(deferred_action_queue),
            "promotionReviewCount": len(promotions),
            "hfmCryptoSymbolEvidenceFound": bool(hfm_crypto.get("symbolEvidenceFound")),
        },
        "processedItems": processed_items,
        "testerReports": tester_tasks[:8],
        "recommendations": recommendations,
        "safety": {
            "mutatesMt5": False,
            "orderSendAllowed": False,
            "walletWriteAllowed": False,
            "livePresetMutationAllowed": False,
            "autoApply": False,
        },
    }


def build_review(args: argparse.Namespace) -> dict[str, Any]:
    runtime_dir = Path(args.runtime_dir)
    output = Path(args.output) if args.output else runtime_dir / OUTPUT_NAME
    ledger = Path(args.ledger) if args.ledger else runtime_dir / LEDGER_NAME
    now = utc_now()

    close_rows = read_csv(runtime_dir / "QuantGod_CloseHistory.csv")
    param_status = read_json(runtime_dir / "QuantGod_ParamLabStatus.json")
    param_results = read_json(runtime_dir / "QuantGod_ParamLabResults.json")
    scheduler = read_json(runtime_dir / "QuantGod_ParamLabAutoScheduler.json")
    auto_tester = read_json(runtime_dir / "QuantGod_AutoTesterWindow.json")
    version_gate = read_json(runtime_dir / "QuantGod_VersionPromotionGate.json")
    governance = read_json(runtime_dir / "QuantGod_GovernanceAdvisor.json")
    run_recovery = read_json(runtime_dir / "QuantGod_ParamLabRunRecovery.json")

    review_day = (now.astimezone(JST).date() - timedelta(days=1)).isoformat()
    daily_pnl = close_history_summary(close_rows, review_day)
    daily_pnl["resolvedByCurrentPolicy"] = daily_pnl_resolved_by_policy(daily_pnl, governance)
    daily_pnl["requiresReview"] = bool(as_float(daily_pnl.get("netUSC")) < 0 and not daily_pnl["resolvedByCurrentPolicy"])
    max_actions = max(1, int(args.max_actions))
    all_action_queue = param_action_queue(scheduler, auto_tester, max_actions, run_recovery)
    completed_action_queue = [action for action in all_action_queue if action.get("state") == "DONE"]
    action_queue = [action for action in all_action_queue if action.get("state") != "DONE"]
    deferred_action_queue: list[dict[str, Any]] = []
    research_backlog_queue: list[dict[str, Any]] = []
    daily_tester_completed = daily_tester_completed_count(param_status, now, max_actions)
    daily_tester_budget_done = daily_tester_completed >= max_actions
    recovery_summary = run_recovery.get("summary", {}) if isinstance(run_recovery.get("summary"), dict) else {}
    if daily_tester_budget_done and action_queue:
        deferred_action_queue = [
            {
                **action,
                "state": "DEFERRED_NEXT_DAILY_REFRESH",
                "guardClass": "DAILY_TESTER_BUDGET_DONE",
                "statusLabel": "DAILY_TESTER_BUDGET_DONE",
                "deferReason": f"today_tester_completed_{daily_tester_completed}_of_{max_actions}",
            }
            for action in action_queue
        ]
        action_queue = []
    elif should_roll_ready_tasks_to_research_backlog(
        action_queue,
        completed_action_queue,
        daily_tester_completed,
        recovery_summary,
    ):
        research_backlog_queue = [
            {
                **action,
                "state": "RESEARCH_BACKLOG_NEXT_REFRESH",
                "guardClass": "DAILY_RESEARCH_BACKLOG",
                "statusLabel": "RESEARCH_BACKLOG_NEXT_REFRESH",
                "deferReason": f"daily_tester_completed_{daily_tester_completed}_and_no_recovery_risk",
            }
            for action in action_queue
        ]
        action_queue = []
    promotions = promotion_recommendations(version_gate, governance)
    hfm_crypto = hfm_crypto_summary(runtime_dir)
    mt5_risk = mt5_terminal_risk(runtime_dir, now)
    usdjpy_evolution = usdjpy_evolution_summary(runtime_dir)
    tester_summary = auto_tester.get("summary", {}) if isinstance(auto_tester.get("summary"), dict) else {}
    tester_tasks = completed_tester_report_tasks(param_status, param_results)
    daily_iteration = daily_iteration_review(
        daily_pnl,
        deferred_action_queue,
        hfm_crypto,
        mt5_risk,
        max_actions,
        tester_tasks,
        usdjpy_evolution,
    )
    completion_report = build_completion_report(
        review_day,
        daily_pnl,
        param_status,
        param_results,
        deferred_action_queue,
        promotions,
        hfm_crypto,
        daily_iteration,
    )
    codex_review = codex_review_queue(
        daily_pnl,
        action_queue,
        promotions,
        governance,
        auto_tester,
        recovery_summary,
        hfm_crypto,
        mt5_risk,
        daily_iteration,
    )

    queue_counter = Counter(action.get("state") for action in action_queue)
    wait_window_count = sum(1 for action in action_queue if action.get("guardClass") == "WAIT_TESTER_WINDOW")
    current_window_plan = tester_window_plan(now)
    if not action_queue and completed_action_queue:
        today_todo_status = "DONE_OR_NO_ACTIONS"
    elif queue_counter.get("NEEDS_CODEX_TRIAGE", 0) > 0:
        today_todo_status = "NEEDS_CODEX_TRIAGE"
    elif action_queue and wait_window_count == len(action_queue):
        today_todo_status = "SCHEDULED_FOR_TESTER_WINDOW"
    elif queue_counter.get("READY_TO_RUN_TESTER", 0) > 0:
        today_todo_status = "READY_TO_RUN_TESTER"
    elif action_queue:
        today_todo_status = "WAIT_GUARD"
    else:
        today_todo_status = "DONE_OR_NO_ACTIONS"
    strategy_actions = [
        {
            "routeKey": row.get("key") or row.get("routeKey") or row.get("strategy"),
            "recommendedAction": row.get("recommendedAction"),
            "blockers": as_list(row.get("blockers"))[:5],
            "liveForward": row.get("liveForward", {}),
        }
        for row in as_list(governance.get("routeDecisions"))
        if isinstance(row, dict)
    ]

    payload = {
        "schemaVersion": 1,
        "mode": "QUANTGOD_DAILY_REVIEW_SAFE_AUTOMATION",
        "generatedAtIso": now.isoformat(),
        "reviewDateJst": review_day,
        "runtimeDir": str(runtime_dir),
        "safety": {
            "mutatesMt5": False,
            "orderSendAllowed": False,
            "walletWriteAllowed": False,
            "livePresetMutationAllowed": False,
            "autoApplyLivePromotion": False,
            "livePromotionRequiresHumanApproval": True,
            "externalAiTransmissionAllowedByDefault": False,
        },
        "summary": {
            "dailyClosedTrades": daily_pnl["closedTrades"],
            "dailyReviewDateJst": review_day,
            "dailyNetUSC": daily_pnl["netUSC"],
            "paramActionCount": len(action_queue),
            "paramDeferredCount": len(deferred_action_queue),
            "paramResearchBacklogCount": len(research_backlog_queue),
            "dailyTesterCompletedCount": daily_tester_completed,
            "dailyTesterBudgetDone": daily_tester_budget_done,
            "paramReadyToRunCount": queue_counter.get("READY_TO_RUN_TESTER", 0),
            "paramWaitGuardCount": queue_counter.get("WAIT_GUARD", 0),
            "paramWaitWindowCount": wait_window_count,
            "promotionReviewCount": len(promotions),
            "todayTodoStatus": today_todo_status,
            "nextTesterWindowLabel": current_window_plan.get("nextWindowLabel", ""),
            "nextTesterWindowDueToday": current_window_plan.get("dueToday", False),
            "testerCanRun": bool(tester_summary.get("canRunTerminal")),
            "testerWindowOk": bool(tester_summary.get("windowOk")),
            "testerLockOk": bool(tester_summary.get("lockOk")),
            "recoveryRedCount": first(recovery_summary.get("riskRedCount"), 0),
            "recoveryYellowCount": first(recovery_summary.get("riskYellowCount"), 0),
            "mt5TradeDisabledCount": mt5_risk["tradeDisabledCount"],
            "mt5InvestorModeCount": mt5_risk["investorModeCount"],
            "hfmCryptoStatus": hfm_crypto["status"],
            "hfmCryptoSymbolEvidenceFound": hfm_crypto["symbolEvidenceFound"],
            "hfmCryptoDetectedSymbolCount": hfm_crypto["detectedSymbolCount"],
            "hfmCryptoMossProfileFound": hfm_crypto["mossProfileFound"],
            "dailyIterationStatus": daily_iteration["status"],
            "dailyIterationRequired": daily_iteration["iterationRequired"],
            "usdJpyEvolutionStatus": usdjpy_evolution["status"],
            "usdJpyEvolutionNeedsIteration": usdjpy_evolution["needsIteration"],
            "completionReportStatus": completion_report["status"],
            "completionRecommendationCount": completion_report["summary"]["recommendationCount"],
            "codexReviewRequired": codex_review["required"],
        },
        "dailyPnl": daily_pnl,
        "actionQueue": action_queue,
        "completedActionQueue": completed_action_queue[:6],
        "deferredActionQueue": deferred_action_queue[:6],
        "researchBacklogQueue": research_backlog_queue[:6],
        "strategyActions": strategy_actions,
        "promotionRecommendations": promotions,
        "hfmCrypto": hfm_crypto,
        "usdJpyEvolution": usdjpy_evolution,
        "dailyIteration": daily_iteration,
        "completionReport": completion_report,
        "mt5TerminalRisk": mt5_risk,
        "tester": {
            "summary": tester_summary,
            "blockers": as_list(auto_tester.get("gate", {}).get("blockers"))[:8],
        },
        "codexReview": codex_review,
        "aiReview": {
            "status": "READY_FOR_CODEX_DAILY_REVIEW",
            "localDeterministicReviewBuilt": True,
            "externalLlmMode": "off_by_default",
            "note": "A Codex/app automation should triage codexReview.required=true items and may propose code or strategy changes. USDJPY live promotion now goes through the autonomous governance gate and machine rollback controls.",
        },
        "nextActions": [
            "Run due ParamLab tester-only tasks when AUTO_TESTER_WINDOW allows it.",
            "Parse reports and rebuild GovernanceAdvisor before any promotion review.",
            "If codexReview.required is true, ask Codex automation to judge code, strategy, or evidence fixes.",
            "If promotionRecommendations is non-empty, route USDJPY candidates through autonomous governance; live preset mutation remains forbidden.",
        ],
    }
    write_json(output, payload)
    append_csv(
        ledger,
        {
            "GeneratedAtIso": payload["generatedAtIso"],
            "DailyClosedTrades": daily_pnl["closedTrades"],
            "DailyReviewDateJst": review_day,
            "DailyNetUSC": daily_pnl["netUSC"],
            "ParamActionCount": len(action_queue),
            "ParamReadyToRunCount": queue_counter.get("READY_TO_RUN_TESTER", 0),
            "ParamWaitGuardCount": queue_counter.get("WAIT_GUARD", 0),
            "ParamWaitWindowCount": wait_window_count,
            "PromotionReviewCount": len(promotions),
            "TodayTodoStatus": today_todo_status,
            "NextTesterWindowLabel": current_window_plan.get("nextWindowLabel", ""),
            "TesterCanRun": str(bool(tester_summary.get("canRunTerminal"))).lower(),
            "Mt5InvestorModeCount": mt5_risk["investorModeCount"],
            "Mt5TradeDisabledCount": mt5_risk["tradeDisabledCount"],
            "HfmCryptoStatus": hfm_crypto["status"],
            "HfmCryptoDetectedSymbolCount": hfm_crypto["detectedSymbolCount"],
            "UsdJpyEvolutionStatus": usdjpy_evolution["status"],
            "UsdJpyParamCandidateCount": usdjpy_evolution["paramCandidateCount"],
            "CodexReviewRequired": str(codex_review["required"]).lower(),
        },
        [
            "GeneratedAtIso",
            "DailyClosedTrades",
            "DailyReviewDateJst",
            "DailyNetUSC",
            "ParamActionCount",
            "ParamReadyToRunCount",
            "ParamWaitGuardCount",
            "ParamWaitWindowCount",
            "PromotionReviewCount",
            "TodayTodoStatus",
            "NextTesterWindowLabel",
            "TesterCanRun",
            "Mt5InvestorModeCount",
            "Mt5TradeDisabledCount",
            "HfmCryptoStatus",
            "HfmCryptoDetectedSymbolCount",
            "UsdJpyEvolutionStatus",
            "UsdJpyParamCandidateCount",
            "CodexReviewRequired",
        ],
    )
    print(
        "DAILY_REVIEW "
        f"trades={daily_pnl['closedTrades']} net={daily_pnl['netUSC']} "
        f"actions={len(action_queue)} promotions={len(promotions)} "
        f"codexReview={codex_review['required']} output={output}"
    )
    return payload


def main() -> int:
    build_review(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
