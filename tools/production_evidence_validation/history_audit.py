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
        return {
            "status": "WARN",
            "reason": "USDJPY SQLite history database not found in expected runtime paths",
            "databaseFound": False,
            "backtestReportFound": bool(backtest_report),
            "productionStatusFound": bool(production_status),
            "recommendation": "Run USDJPY history sync and strategy backtest before trusting GA fitness.",
        }
    summaries = sqlite_table_summary(existing, BAR_TABLES)
    timeframe_rows = _status_timeframe_rows(production_status, summaries)
    blockers = _blockers(timeframe_rows, production_status)
    status = "PASS" if not blockers else "WARN"
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
        "blockersZh": blockers,
        "backtestReportFound": bool(backtest_report),
        "recommendation": "History looks production-ready." if status == "PASS" else "History exists but GA/promotion must stay blocked until M1/M5/M15/H1 coverage and freshness all pass.",
    }
