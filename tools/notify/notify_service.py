from __future__ import annotations

import asyncio
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import NotifyConfig
from .event_formatter import format_event

try:
    from telegram_gateway_cli import dispatch_cli_text
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_gateway_cli import dispatch_cli_text


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_history(config: NotifyConfig | None = None, limit: int = 50) -> dict[str, Any]:
    cfg = config or NotifyConfig.from_env()
    payload = _read_json(cfg.history_path, {"mode": "QUANTGOD_NOTIFY_HISTORY_V1", "items": []})
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return {"ok": True, "mode": "QUANTGOD_NOTIFY_HISTORY_V1", "items": list(items)[-max(1, limit):], "historyPath": str(cfg.history_path)}


def append_history(config: NotifyConfig, record: dict[str, Any]) -> None:
    payload = _read_json(config.history_path, {"mode": "QUANTGOD_NOTIFY_HISTORY_V1", "items": []})
    if not isinstance(payload, dict):
        payload = {"mode": "QUANTGOD_NOTIFY_HISTORY_V1", "items": []}
    items = payload.setdefault("items", [])
    items.append(record)
    payload["items"] = items[-500:]
    payload["updatedAt"] = utc_now()
    _write_json(config.history_path, payload)


UNSAFE_AI_TEXT_PATTERNS = (
    ("mock decision", "mock_decision_text"),
    ("mock_fallback", "mock_fallback_text"),
    ("fallback evidence", "fallback_evidence_text"),
    ("runtime_files_missing_or_stale", "stale_runtime_text"),
    ("运行快照不新鲜", "stale_runtime_text"),
    ("回退模式", "fallback_evidence_text"),
)

UNSAFE_AI_EXECUTION_PATTERNS = (
    ("立即下单", "execution_instruction"),
    ("自动下单", "execution_instruction"),
    ("建议下单", "execution_instruction"),
    ("执行交易", "execution_instruction"),
    ("立即开仓", "execution_instruction"),
    ("自动开仓", "execution_instruction"),
    ("立即平仓", "execution_instruction"),
    ("自动平仓", "execution_instruction"),
    ("place order", "execution_instruction"),
    ("execute trade", "execution_instruction"),
    ("open position now", "execution_instruction"),
    ("close position now", "execution_instruction"),
)


def _event_payload_from_analysis(report: dict[str, Any]) -> dict[str, Any]:
    decision = report.get("decision") or report.get("decision_report") or report.get("DecisionReport") or {}
    risk = report.get("risk") or report.get("risk_report") or report.get("RiskReport") or {}
    entry = decision.get("entryZone") or decision.get("entry_zone") or decision.get("entry_price")
    stop_loss = decision.get("stopLoss") or decision.get("stop_loss")
    take_profit = decision.get("takeProfit") or decision.get("take_profit")
    targets = decision.get("targets")
    if not isinstance(targets, list):
        targets = [take_profit] if take_profit not in (None, "") else []
    risk_reward = decision.get("riskReward") or decision.get("risk_reward_ratio")
    invalidation = (
        decision.get("invalidation")
        or decision.get("suggested_wait_condition")
        or decision.get("reasoning")
        or report.get("summary")
        or "analysis complete"
    )
    action = decision.get("action") or decision.get("decision") or "HOLD"
    confidence = decision.get("confidence") or 0
    return {
        "symbol": report.get("symbol") or decision.get("symbol") or report.get("Symbol") or "--",
        "action": action,
        "confidence": confidence,
        "risk": risk.get("risk_level") or risk.get("riskLevel") or risk.get("level") or "unknown",
        "note": invalidation,
        "decision": {
            "action": action,
            "confidence": confidence,
            "entryZone": entry,
            "stopLoss": stop_loss,
            "targets": targets,
            "riskReward": risk_reward,
            "invalidation": invalidation,
        },
    }


def unsafe_ai_notification_reason(event_type: str, payload: dict[str, Any], text: str) -> str | None:
    if str(event_type or "").upper() != "AI_ANALYSIS":
        return None
    haystack = "\n".join(
        [
            str(text or ""),
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
        ]
    ).lower()
    for needle, reason in UNSAFE_AI_TEXT_PATTERNS:
        if needle in haystack:
            return reason
    for marker, reason in UNSAFE_AI_EXECUTION_PATTERNS:
        if marker in haystack:
            return reason
    return None


def _should_disable_notification(event_type: str) -> bool:
    return str(event_type or "").upper() in {"DAILY_DIGEST"}


async def send_event(
    event_type: str,
    data: dict[str, Any] | None = None,
    config: NotifyConfig | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    cfg = config or NotifyConfig.from_env()
    event = str(event_type or "TEST").upper()
    payload = data or {}
    text = format_event(event, payload)

    record = {
        "timestamp": utc_now(),
        "eventType": event,
        "dryRun": bool(dry_run),
        "text": text,
        "sent": False,
        "ok": False,
        "error": "",
    }

    # HOLD → skip push (renderer returned None, wrapper gave us "")
    if not text.strip():
        record.update({"ok": True, "skipped": True, "status": "skipped_hold", "error": "action=HOLD"})
        append_history(cfg, record)
        return {"ok": True, "sent": False, "skipped": True, "status": "skipped_hold", "reason": "action=HOLD", "record": record}

    unsafe_reason = unsafe_ai_notification_reason(event, payload, text)
    if unsafe_reason:
        record.update({"ok": True, "skipped": True, "status": "blocked_unsafe_message", "error": unsafe_reason})
        append_history(cfg, record)
        return {
            "ok": True,
            "sent": False,
            "skipped": True,
            "status": "blocked_unsafe_message",
            "reason": unsafe_reason,
            "record": record,
        }

    if not cfg.enabled:
        record.update({"ok": True, "skipped": True, "error": "notify_disabled"})
        append_history(cfg, record)
        return {"ok": True, "sent": False, "skipped": True, "reason": "notify_disabled", "record": record}

    if not cfg.event_enabled(event):
        record.update({"ok": True, "skipped": True, "error": "event_disabled"})
        append_history(cfg, record)
        return {"ok": True, "sent": False, "skipped": True, "reason": "event_disabled", "record": record}

    if not cfg.telegram_environment_safe:
        reason = "unsafe_telegram_environment:" + ",".join(cfg.safety_violations)
        record.update({"ok": False, "sent": False, "status": "blocked_unsafe_environment", "error": reason})
        append_history(cfg, record)
        return {
            "ok": False,
            "sent": False,
            "skipped": True,
            "status": "blocked_unsafe_environment",
            "error": reason,
            "record": record,
        }

    if dry_run:
        record.update({"ok": True, "sent": False, "dryRun": True})
        append_history(cfg, record)
        return {"ok": True, "sent": False, "dryRun": True, "record": record}

    if not cfg.telegram_configured:
        record.update({"ok": False, "sent": False, "error": "telegram_not_configured"})
        append_history(cfg, record)
        return {"ok": False, "sent": False, "error": "telegram_not_configured", "record": record}

    if not cfg.telegram_push_allowed:
        record.update({"ok": False, "sent": False, "error": "telegram_push_disabled"})
        append_history(cfg, record)
        return {"ok": False, "sent": False, "error": "telegram_push_disabled", "record": record}

    gateway = await asyncio.to_thread(
        dispatch_cli_text,
        runtime_dir=cfg.runtime_dir,
        source="notify_service",
        topic=event,
        severity="WARN" if event in {"KILL_SWITCH", "NEWS_BLOCK", "CONSECUTIVE_LOSS"} else "INFO",
        text=text,
    )
    delivery = gateway.get("delivery") if isinstance(gateway.get("delivery"), dict) else {}
    confirmed = gateway.get("sent") is True and gateway.get("deliveryOk") is True
    if confirmed:
        status = "sent"
        error = ""
    elif delivery.get("skipped") is True:
        status = "send_suppressed"
        error = str(delivery.get("reason") or "telegram_send_suppressed")
    else:
        status = "send_failed"
        error = str(delivery.get("reason") or "telegram_delivery_not_confirmed")
    record.update(
        {
            "ok": confirmed,
            "sent": confirmed,
            "status": status,
            "error": error,
            "telegramMessageId": delivery.get("messageId") if confirmed else None,
        }
    )
    append_history(cfg, record)
    return {
        "ok": confirmed,
        "sent": confirmed,
        "deliveryOk": confirmed,
        "status": status,
        "error": error,
        "gateway": gateway,
        "record": record,
    }


async def send_ai_analysis_summary(report: dict[str, Any], config: NotifyConfig | None = None, dry_run: bool = True) -> dict[str, Any]:
    return await send_event("AI_ANALYSIS", _event_payload_from_analysis(report), config=config, dry_run=dry_run)


def _read_csv_rows(path: Path, limit: int = 500) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return []
    return rows[-limit:]


def build_daily_digest(config: NotifyConfig | None = None) -> dict[str, Any]:
    cfg = config or NotifyConfig.from_env()
    journal = _read_csv_rows(cfg.runtime_dir / "QuantGod_TradeJournal.csv")
    closes = _read_csv_rows(cfg.runtime_dir / "QuantGod_CloseHistory.csv")
    shadow = _read_csv_rows(cfg.runtime_dir / "QuantGod_ShadowSignalLedger.csv")
    pnl = 0.0
    wins = 0
    losses = 0
    for row in closes:
        raw = row.get("Profit") or row.get("profit") or row.get("PnL") or row.get("pnl") or "0"
        try:
            value = float(str(raw).replace("$", "").replace(",", ""))
        except ValueError:
            continue
        pnl += value
        if value > 0:
            wins += 1
        elif value < 0:
            losses += 1
    route_counts: dict[str, int] = {}
    for row in journal:
        route = row.get("Route") or row.get("route") or row.get("Strategy") or "unknown"
        route_counts[route] = route_counts.get(route, 0) + 1
    route_summary = " ".join(f"{route}: {count}" for route, count in sorted(route_counts.items())[:5]) or "routes: --"
    return {"pnl": pnl, "wins": wins, "losses": losses, "routes": route_summary, "shadowSignals": len(shadow)}


async def send_daily_digest(config: NotifyConfig | None = None, dry_run: bool = True) -> dict[str, Any]:
    cfg = config or NotifyConfig.from_env()
    return await send_event("DAILY_DIGEST", build_daily_digest(cfg), config=cfg, dry_run=dry_run)


def scan_runtime_events(config: NotifyConfig | None = None) -> list[dict[str, Any]]:
    """Best-effort one-shot scanner used by Task Scheduler or manual smoke tests."""
    cfg = config or NotifyConfig.from_env()
    events: list[dict[str, Any]] = []
    dashboard = _read_json(cfg.runtime_dir / "QuantGod_Dashboard.json", {})
    if isinstance(dashboard, dict):
        if dashboard.get("killSwitchActive") or dashboard.get("KillSwitchActive"):
            events.append({"eventType": "KILL_SWITCH", "data": {"reason": dashboard.get("killSwitchReason") or dashboard.get("KillSwitchReason") or "dashboard", "pnl": dashboard.get("dailyPnl") or dashboard.get("DailyPnl") or 0}})
        news = dashboard.get("news") or {}
        news_active = news.get("blocked") or news.get("active")
        if news_active:
            events.append({
                "eventType": "NEWS_BLOCK",
                "data": {
                    "label": news.get("eventLabel") or news.get("eventName") or "tracked USD event",
                    "eta": news.get("minutesToEvent") or "--",
                    "phase": news.get("phase"),
                    "actual": news.get("actual"),
                    "forecast": news.get("forecast"),
                    "previous": news.get("previous"),
                    "reason": news.get("reason"),
                },
            })
    return events


async def scan_once(config: NotifyConfig | None = None, dry_run: bool = True) -> dict[str, Any]:
    cfg = config or NotifyConfig.from_env()
    results = []
    for event in scan_runtime_events(cfg):
        results.append(await send_event(event["eventType"], event.get("data", {}), config=cfg, dry_run=dry_run))
    return {"ok": True, "count": len(results), "results": results}


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)
