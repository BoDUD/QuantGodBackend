from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import read_json, sqlite_table_summary

REQUIRED_TIMEFRAMES = ["M1", "M5", "M15", "H1"]
TABLE_BY_TIMEFRAME = {
    "M1": "bars_m1",
    "M5": "bars_m5",
    "M15": "bars_m15",
    "H1": "bars_h1",
}
BAR_TABLES = [TABLE_BY_TIMEFRAME[timeframe] for timeframe in REQUIRED_TIMEFRAMES]
PRODUCTION_STATUS_FILE = "QuantGod_USDJPYHistoryProductionStatus.json"
HISTORY_SYNC_REPORT_FILE = "QuantGod_USDJPYHistoricalKlineSyncReport.json"
DEFAULT_REQUIRED_SPAN_DAYS = 180.0
DEFAULT_MAX_LATEST_LAG_HOURS = 96.0


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _span_days(min_time: Any, max_time: Any) -> float:
    start = _parse_time(min_time)
    end = _parse_time(max_time)
    if not start or not end or end < start:
        return 0.0
    return round((end - start).total_seconds() / 86400.0, 3)


def _latest_lag_hours(max_time: Any) -> float | None:
    end = _parse_time(max_time)
    if not end:
        return None
    return round(max(0.0, (datetime.now(timezone.utc) - end).total_seconds() / 3600.0), 3)


def _relative_to_runtime(runtime_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(runtime_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _status_timeframe_rows(
    production_status: dict[str, Any],
    summaries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    production_timeframes = production_status.get("timeframes")
    if isinstance(production_timeframes, dict):
        rows = {
            timeframe: dict(production_timeframes.get(timeframe) or {})
            for timeframe in REQUIRED_TIMEFRAMES
        }
    else:
        by_table = {str(row.get("table") or ""): row for row in summaries}
        rows = {}
        for timeframe in REQUIRED_TIMEFRAMES:
            table = TABLE_BY_TIMEFRAME[timeframe]
            summary = by_table.get(table) or {}
            span = _span_days(summary.get("minTime"), summary.get("maxTime"))
            latest_lag = _latest_lag_hours(summary.get("maxTime"))
            rows[timeframe] = {
                "timeframe": timeframe,
                "barCount": int(summary.get("rows") or 0),
                "earliestBar": summary.get("minTime"),
                "latestBar": summary.get("maxTime"),
                "spanDays": span,
                "requiredSpanDays": DEFAULT_REQUIRED_SPAN_DAYS,
                "latestLagHours": latest_lag,
                "maxLatestLagHours": DEFAULT_MAX_LATEST_LAG_HOURS,
                "spanOk": span >= DEFAULT_REQUIRED_SPAN_DAYS,
                "densityOk": int(summary.get("rows") or 0) > 0,
                "freshnessOk": latest_lag is not None and latest_lag <= DEFAULT_MAX_LATEST_LAG_HOURS,
            }
    normalized: dict[str, dict[str, Any]] = {}
    for timeframe in REQUIRED_TIMEFRAMES:
        row = rows.get(timeframe) if isinstance(rows.get(timeframe), dict) else {}
        normalized[timeframe] = {
            "timeframe": timeframe,
            "barCount": int(row.get("barCount") or row.get("rows") or 0),
            "earliestBar": row.get("earliestBar") or row.get("minTime"),
            "latestBar": row.get("latestBar") or row.get("maxTime"),
            "spanDays": float(row.get("spanDays") or 0.0),
            "requiredSpanDays": float(row.get("requiredSpanDays") or production_status.get("requiredSpanDays") or DEFAULT_REQUIRED_SPAN_DAYS),
            "latestLagHours": row.get("latestLagHours"),
            "maxLatestLagHours": float(row.get("maxLatestLagHours") or production_status.get("maxLatestLagHours") or DEFAULT_MAX_LATEST_LAG_HOURS),
            "spanOk": bool(row.get("spanOk")),
            "densityOk": bool(row.get("densityOk")),
            "freshnessOk": bool(row.get("freshnessOk")),
            "passed": bool(row.get("passed")) or bool(row.get("spanOk") and row.get("densityOk") and row.get("freshnessOk")),
            "reasonZh": str(row.get("reasonZh") or ""),
        }
    return normalized


def _blockers(rows: dict[str, dict[str, Any]], production_status: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for timeframe, row in rows.items():
        if not row.get("spanOk"):
            blockers.append(f"{timeframe} 历史覆盖不足")
        if not row.get("densityOk"):
            blockers.append(f"{timeframe} K 线密度不足")
        if not row.get("freshnessOk"):
            blockers.append(f"{timeframe} 最新 K 线延迟超阈值")
    if production_status and not production_status.get("historyTargetSatisfied"):
        blockers.append("historyProductionStatus 未达到 PASS")
    return blockers


def _row_recovery_status(row: dict[str, Any], database_found: bool) -> str:
    if not database_found:
        return "DATABASE_MISSING"
    if row.get("passed"):
        return "PASS"
    if row.get("spanOk") and row.get("densityOk") and not row.get("freshnessOk"):
        return "FRESHNESS_STALE"
    if not row.get("spanOk"):
        return "SPAN_INSUFFICIENT"
    if not row.get("densityOk"):
        return "DENSITY_INSUFFICIENT"
    return "BLOCKED"


def _history_freshness_recovery_queue(
    runtime_dir: Path,
    rows: dict[str, dict[str, Any]],
    *,
    database_found: bool,
    database_path: Path | None = None,
) -> list[dict[str, Any]]:
    db_rel = _relative_to_runtime(runtime_dir, database_path) if database_path else "backtest/usdjpy.sqlite"
    status_rel = _relative_to_runtime(runtime_dir, runtime_dir / "backtest" / PRODUCTION_STATUS_FILE)
    sync_rel = _relative_to_runtime(runtime_dir, runtime_dir / "backtest" / HISTORY_SYNC_REPORT_FILE)
    refresh_command = (
        "python3 tools/run_usdjpy_strategy_backtest.py --runtime-dir ./runtime "
        "sync-klines --months 12 --timeframes M1,M5,M15,H1"
    )
    verify_command = (
        "python3 tools/run_usdjpy_strategy_backtest.py --runtime-dir ./runtime production-status "
        "--months 12 --max-latest-lag-hours 96"
    )
    queue: list[dict[str, Any]] = []
    for timeframe in REQUIRED_TIMEFRAMES:
        row = rows.get(timeframe, {"timeframe": timeframe})
        latest_lag = row.get("latestLagHours")
        max_lag = row.get("maxLatestLagHours")
        excess_lag = None
        if isinstance(latest_lag, (int, float)) and isinstance(max_lag, (int, float)):
            excess_lag = round(max(0.0, float(latest_lag) - float(max_lag)), 3)
        status = _row_recovery_status(row, database_found)
        priority = "OK" if status == "PASS" else "HIGH" if status == "FRESHNESS_STALE" else "MEDIUM"
        if status == "PASS":
            next_action = "该周期历史 freshness 已通过；保持后台增量同步。"
        elif status == "FRESHNESS_STALE":
            next_action = (
                f"{timeframe} 覆盖和密度已满足，但最新 K 线延迟超阈值；恢复 MT5/MQL5 CopyRates 导出或 "
                "MT5 Python 数据源后运行 sync-klines，再刷新 production-status。"
            )
        elif status == "DATABASE_MISSING":
            next_action = (
                "未找到 USDJPY SQLite 历史库；先运行只读历史同步生成 backtest/usdjpy.sqlite，"
                "再运行 production-status。"
            )
        else:
            next_action = (
                f"{timeframe} 覆盖或密度未通过；运行更长 lookback 的 sync-klines 并确认表内 bar count。"
            )
        queue.append(
            {
                "timeframe": timeframe,
                "status": status,
                "priority": priority,
                "barCount": int(row.get("barCount") or 0),
                "spanDays": row.get("spanDays") or 0.0,
                "requiredSpanDays": row.get("requiredSpanDays") or DEFAULT_REQUIRED_SPAN_DAYS,
                "latestLagHours": latest_lag,
                "maxLatestLagHours": max_lag or DEFAULT_MAX_LATEST_LAG_HOURS,
                "excessLagHours": excess_lag,
                "spanOk": bool(row.get("spanOk")),
                "densityOk": bool(row.get("densityOk")),
                "freshnessOk": bool(row.get("freshnessOk")),
                "passed": bool(row.get("passed")),
                "sourceArtifacts": [db_rel, status_rel, sync_rel],
                "refreshCommand": refresh_command,
                "verifyCommand": verify_command,
                "nextActionZh": next_action,
                "acceptanceZh": (
                    f"{timeframe} spanOk=true、densityOk=true、freshnessOk=true、passed=true，且 "
                    "historyTargetSatisfied=true。"
                ),
                "allowedLanes": ["READ_ONLY_RESEARCH", "SHADOW", "TESTER_ONLY"],
                "forbiddenSideEffects": [
                    "ORDER_SEND",
                    "POSITION_CLOSE",
                    "LIVE_PRESET_MUTATION",
                    "MT5_REQUEST_WRITE",
                    "WALLET_AUTHORIZATION",
                ],
            }
        )
    return queue


def audit_history(runtime_dir: Path) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    candidates = [
        runtime_dir / "backtest" / "usdjpy.sqlite",
        runtime_dir / "history" / "usdjpy.sqlite",
        runtime_dir / "usdjpy.sqlite",
    ]
    existing = next((path for path in candidates if path.exists()), None)
    backtest_report = read_json(runtime_dir / "backtest" / "QuantGod_StrategyBacktestReport.json", {}) or {}
    production_status_path = runtime_dir / "backtest" / PRODUCTION_STATUS_FILE
    production_status = read_json(production_status_path, {}) or {}
    if not existing:
        empty_rows = {
            timeframe: {
                "timeframe": timeframe,
                "spanOk": False,
                "densityOk": False,
                "freshnessOk": False,
                "passed": False,
            }
            for timeframe in REQUIRED_TIMEFRAMES
        }
        return {
            "status": "WARN",
            "reason": "USDJPY SQLite history database not found in expected runtime paths",
            "databaseFound": False,
            "backtestReportFound": bool(backtest_report),
            "productionStatusFound": bool(production_status),
            "requiredTimeframes": REQUIRED_TIMEFRAMES,
            "freshnessRecoveryQueue": _history_freshness_recovery_queue(
                runtime_dir,
                empty_rows,
                database_found=False,
            ),
            "staleTimeframes": REQUIRED_TIMEFRAMES,
            "recommendation": "Run USDJPY history sync and strategy backtest before trusting GA fitness.",
        }
    summaries = sqlite_table_summary(existing, BAR_TABLES)
    timeframe_rows = _status_timeframe_rows(production_status, summaries)
    blockers = _blockers(timeframe_rows, production_status)
    status = "PASS" if not blockers else "WARN"
    recovery_queue = _history_freshness_recovery_queue(
        runtime_dir,
        timeframe_rows,
        database_found=True,
        database_path=existing,
    )
    stale_timeframes = [
        timeframe for timeframe, row in timeframe_rows.items() if not row.get("freshnessOk")
    ]
    return {
        "status": status,
        "databaseFound": True,
        "databasePath": _relative_to_runtime(runtime_dir, existing),
        "requiredTimeframes": REQUIRED_TIMEFRAMES,
        "tables": summaries,
        "timeframes": timeframe_rows,
        "passedTimeframes": sum(1 for row in timeframe_rows.values() if row.get("passed")),
        "productionStatusFound": bool(production_status),
        "productionStatusPath": _relative_to_runtime(runtime_dir, production_status_path),
        "historyTargetSatisfied": bool(production_status.get("historyTargetSatisfied")),
        "freshnessGatePassed": all(row.get("freshnessOk") for row in timeframe_rows.values()),
        "coverageGatePassed": all(row.get("spanOk") and row.get("densityOk") for row in timeframe_rows.values()),
        "staleTimeframes": stale_timeframes,
        "freshnessRecoveryQueue": recovery_queue,
        "nextRecoveryActionZh": (
            "History looks production-ready."
            if status == "PASS"
            else "按 freshnessRecoveryQueue 刷新落后周期：先恢复 MT5/MQL5 CopyRates 数据源，再运行 sync-klines 和 production-status。"
        ),
        "blockersZh": blockers,
        "backtestReportFound": bool(backtest_report),
        "recommendation": "History looks production-ready." if status == "PASS" else "History exists but GA/promotion must stay blocked until M1/M5/M15/H1 coverage and freshness all pass.",
    }
