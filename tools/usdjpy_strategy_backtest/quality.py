from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .schema import SAFETY_BOUNDARY, atomic_write_json, quality_report_path


def build_quality_report(status_payload: Dict[str, Any], latest_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    latest_report = latest_report if isinstance(latest_report, dict) else {}
    coverage = status_payload.get("historyCoverage") if isinstance(status_payload.get("historyCoverage"), dict) else {}
    timeframes = coverage.get("timeframes") if isinstance(coverage.get("timeframes"), dict) else {}
    latest_sync = status_payload.get("historySyncReport") if isinstance(status_payload.get("historySyncReport"), dict) else {}
    production_status = (
        status_payload.get("historyProductionStatus")
        if isinstance(status_payload.get("historyProductionStatus"), dict)
        else {}
    )
    production_timeframes = (
        production_status.get("timeframes")
        if isinstance(production_status.get("timeframes"), dict)
        else {}
    )
    production_freshness_ok = bool(production_timeframes) and all(
        isinstance(row, dict) and row.get("freshnessOk") is True
        for row in production_timeframes.values()
    )
    checks = []
    for timeframe in ("M1", "M5", "M15", "H1"):
        row = timeframes.get(timeframe) if isinstance(timeframes.get(timeframe), dict) else {}
        checks.append(
            {
                "check": f"{timeframe}_HISTORY_DEPTH",
                "passed": float(row.get("spanDays") or 0) >= 180 and int(row.get("barCount") or 0) > 0,
                "detailZh": f"{timeframe} 覆盖 {row.get('spanDays', 0)} 天 / {row.get('barCount', 0)} 根。",
            }
        )
    engine = latest_report.get("engine") if isinstance(latest_report.get("engine"), dict) else {}
    cost_model = engine.get("costModel") if isinstance(engine.get("costModel"), dict) else {}
    news_gate = engine.get("newsGateBacktest") if isinstance(engine.get("newsGateBacktest"), dict) else {}
    checks.extend(
        [
            {
                "check": "DYNAMIC_COST_MODEL",
                "passed": bool(cost_model.get("dynamicSpreadFromBars")),
                "detailZh": "回测成本已使用 bar spread + slippage + commission 口径。" if cost_model else "等待回测成本模型输出。",
            },
            {
                "check": "HISTORICAL_NEWS_GATE_AUDIT",
                "passed": bool(news_gate.get("sourceAvailable")) and int(news_gate.get("eventCount") or 0) > 0,
                "detailZh": news_gate.get("reasonZh") or "等待历史新闻门禁审计输出。",
            },
            {
                "check": "HISTORY_SYNC_TARGET",
                "passed": bool(latest_sync.get("historyTargetSatisfied")),
                "detailZh": latest_sync.get("reasonZh") or "等待历史 K 线同步报告。",
            },
            {
                "check": "HISTORY_PRODUCTION_STATUS",
                "passed": bool(production_status.get("historyTargetSatisfied"))
                and str(production_status.get("status") or "").upper() == "PASS"
                and production_freshness_ok,
                "detailZh": production_status.get("reasonZh") or "等待 USDJPY 历史数据生产状态报告。",
            },
        ]
    )
    failed = [item for item in checks if not item.get("passed")]
    payload = {
        "ok": not failed,
        "schema": "quantgod.strategy_backtest_quality.v1",
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if not failed else "BLOCKED",
        "checkCount": len(checks),
        "failedCount": len(failed),
        "checks": checks,
        "historyTargetSatisfied": bool(latest_sync.get("historyTargetSatisfied")),
        "historyProductionStatus": {
            "present": bool(production_status),
            "status": production_status.get("status") or "MISSING",
            "historyTargetSatisfied": bool(production_status.get("historyTargetSatisfied")),
            "failedCount": int(production_status.get("failedCount") or 0),
            "source": production_status.get("source") if isinstance(production_status.get("source"), dict) else {},
        },
        "cache": latest_report.get("cache") if isinstance(latest_report.get("cache"), dict) else {},
        "reasonZh": (
            "Backtest Engine 生产化检查通过：历史深度、动态成本、新闻门禁和同步状态可用于 GA 评分。"
            if not failed
            else "Backtest Engine 生产证据未通过；冻结 GA 晋级与代数推进，直到历史、新闻、成本和新鲜度全部恢复。"
        ),
        "safety": dict(SAFETY_BOUNDARY),
    }
    return payload


def write_quality_report(runtime_dir: Path, payload: Dict[str, Any]) -> None:
    atomic_write_json(quality_report_path(runtime_dir), payload)
