from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from .io_utils import append_jsonl, append_jsonl_unique, read_jsonl_tail, utc_now_iso, write_json
from .schema import AGENT_VERSION, SAFETY_BOUNDARY, gateway_ledger_path, gateway_queue_path, gateway_status_path

try:
    from telegram_safety import (
        FORBIDDEN_TELEGRAM_TRUTHY_ENV,
        unsafe_telegram_environment_keys,
    )
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_safety import (
        FORBIDDEN_TELEGRAM_TRUTHY_ENV,
        unsafe_telegram_environment_keys,
    )

try:
    from telegram_digest import sanitize_telegram_message
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import sanitize_telegram_message

MAX_EVENTS_PER_RUN = 8
TELEGRAM_TEXT_MAX_CHARS = 3900
TELEGRAM_MESSAGE_PREVIEW_MAX_CHARS = 160
TELEGRAM_SAFETY_FOOTER = "边界：永久 Shadow｜无执行通道｜Telegram 只推送、不接收命令。"
TELEGRAM_TRUNCATION_NOTICE = "…（内容已安全裁剪，完整详情见本地面板）"
_TELEGRAM_BOT_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])\d{5,}:[A-Za-z0-9_-]{10,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|secret|password|api[_-]?key)\s*([:=])\s*([^\s,;]+)"
)
FORBIDDEN_TELEGRAM_GATEWAY_TRUTHY_ENV = FORBIDDEN_TELEGRAM_TRUTHY_ENV
SCHEDULED_REPORT_TOPICS = (
    "DAILY_AUTOPILOT_V2_REPORT",
    "GA_EVOLUTION_REPORT",
    "USDJPY_AUTONOMOUS_AGENT_REPORT",
)


def build_notification_event(
    source: str,
    topic: str,
    severity: str,
    text: str,
    payload: Dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> Dict[str, Any]:
    safe_text = _safe_event_text(text)
    digest_material = dedupe_key or f"{source}|{topic}|{severity}|{safe_text[:1000]}"
    digest = hashlib.sha256(digest_material.encode("utf-8")).hexdigest()
    return {
        "schema": "quantgod.notification.v1",
        "agentVersion": AGENT_VERSION,
        "eventId": digest[:24],
        "dedupeKey": dedupe_key,
        "createdAt": utc_now_iso(),
        "source": source,
        "topic": topic,
        "severity": severity,
        "lang": "zh-CN",
        "text": safe_text,
        "payload": payload or {},
        "safety": dict(SAFETY_BOUNDARY),
    }


def dispatch_text(
    runtime_dir: Path,
    source: str,
    topic: str,
    severity: str,
    text: str,
    payload: Dict[str, Any] | None = None,
    send: bool = False,
    dedupe_key: str | None = None,
) -> Dict[str, Any]:
    event = build_notification_event(source, topic, severity, text, payload=payload, dedupe_key=dedupe_key)
    return dispatch_event(runtime_dir, event, send=send)


def collect_scheduled_events(
    runtime_dir: Path,
    repo_root: Path | None = None,
    refresh: bool = True,
) -> Dict[str, Any]:
    """Collect operator reports into the Gateway queue.

    The scheduled agent loop should not call individual Telegram senders. It
    should build auditable reports, enqueue them with stable dedupe keys, and
    let the Gateway handle rate limiting and delivery.
    """
    runtime_dir = Path(runtime_dir)
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    _ensure_import_paths(repo_root)
    collected: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for builder in (
        _build_daily_autopilot_event,
        _build_ga_event,
        _build_autonomous_agent_event,
    ):
        try:
            event = builder(runtime_dir, repo_root, refresh)
            if not event:
                continue
            enqueue_result = enqueue_event(runtime_dir, event)
            collected.append(
                {
                    "topic": event.get("topic"),
                    "source": event.get("source"),
                    "eventId": event.get("eventId"),
                    "dedupeKey": event.get("dedupeKey"),
                    "queued": enqueue_result.get("queued", 0),
                }
            )
        except Exception as exc:
            errors.append({"builder": getattr(builder, "__name__", "unknown"), "error": f"{type(exc).__name__}: {exc}"})
    status = gateway_status(runtime_dir)
    status.update(
        {
            "scheduledCollector": True,
            "scheduledTopics": list(SCHEDULED_REPORT_TOPICS),
            "collectedCount": len(collected),
            "collectedEvents": collected,
            "collectErrors": errors,
            "reasonZh": "Telegram Gateway 已收集日报、GA 与 Agent 回滚/patch 报告；统一排队、去重、限频和投递。",
        }
    )
    write_json(gateway_status_path(runtime_dir), status)
    return status


def dispatch_event(runtime_dir: Path, event: Dict[str, Any], send: bool = False) -> Dict[str, Any]:
    event = dict(event)
    event["text"] = _safe_event_text(event.get("text", ""))
    ledger = gateway_ledger_path(runtime_dir)
    recent_ids = {
        row.get("eventId")
        for row in read_jsonl_tail(ledger, 200)
        if _delivery_counts_as_processed(row)
    }
    duplicate = event.get("eventId") in recent_ids
    rate_limited = _rate_limited(ledger)
    raw_delivery = {"ok": False, "skipped": True, "reason": "send_not_requested"}
    processed_at = utc_now_iso()
    if send and not duplicate and not rate_limited:
        raw_delivery = _send_telegram(event.get("text", ""))
    elif duplicate:
        raw_delivery = {"ok": False, "skipped": True, "reason": "duplicate_suppressed"}
    elif rate_limited:
        raw_delivery = {"ok": False, "skipped": True, "reason": "rate_limited"}
    delivery = _minimal_delivery_summary(raw_delivery, processed_at=processed_at)
    row = _minimal_ledger_row(event, delivery, processed_at=processed_at)
    append_jsonl(ledger, [row])
    blocked_environment_keys = _unsafe_environment_keys()
    status = {
        "ok": True,
        "schema": "quantgod.telegram_gateway_status.v1",
        "agentVersion": AGENT_VERSION,
        "lastEventId": event.get("eventId"),
        "duplicateSuppressed": duplicate,
        "rateLimited": rate_limited,
        "sendRequested": bool(send),
        "delivery": delivery,
        "environmentSafe": not blocked_environment_keys,
        "blockedUnsafeEnvironmentKeys": blocked_environment_keys,
        "reasonZh": "独立 Telegram Gateway 统一做中文模板、去重、限频、投递账本；不接收 Telegram 交易命令。",
        "safety": dict(SAFETY_BOUNDARY),
    }
    write_json(gateway_status_path(runtime_dir), status)
    return status


def enqueue_event(runtime_dir: Path, event: Dict[str, Any]) -> Dict[str, Any]:
    event = dict(event)
    event["text"] = _safe_event_text(event.get("text", ""))
    queued = append_jsonl_unique(gateway_queue_path(runtime_dir), [event], "eventId")
    status = gateway_status(runtime_dir)
    status.update(
        {
            "queued": queued,
            "lastQueuedEventId": event.get("eventId"),
            "reasonZh": "NotificationEvent 已进入独立 Telegram Gateway 队列，等待统一投递。",
        }
    )
    write_json(gateway_status_path(runtime_dir), status)
    return status


def dispatch_pending(
    runtime_dir: Path,
    send: bool = False,
    limit: int = MAX_EVENTS_PER_RUN,
    allowed_topics: List[str] | None = None,
) -> Dict[str, Any]:
    queue = read_jsonl_tail(gateway_queue_path(runtime_dir), 1000)
    ledger_ids = {
        row.get("eventId")
        for row in read_jsonl_tail(gateway_ledger_path(runtime_dir), 2000)
        if _delivery_counts_as_processed(row)
    }
    pending = [row for row in queue if row.get("eventId") not in ledger_ids]
    if allowed_topics is not None:
        allowed = set(allowed_topics)
        pending = [row for row in pending if row.get("topic") in allowed]
    dispatched = []
    for event in pending[: max(1, min(int(limit), MAX_EVENTS_PER_RUN))]:
        dispatched.append(dispatch_event(runtime_dir, event, send=send))
    status = gateway_status(runtime_dir)
    post_dispatch_pending = status.get("pendingCount", max(0, len(pending)))
    status.update(
        {
            "pendingCount": post_dispatch_pending,
            "dispatchedCount": len(dispatched),
            "sendRequested": bool(send),
            "dispatchResults": dispatched,
            "reasonZh": "独立 Telegram Gateway 已处理队列；只 push 中文通知，不接收交易命令。",
        }
    )
    write_json(gateway_status_path(runtime_dir), status)
    return status


def gateway_status(runtime_dir: Path) -> Dict[str, Any]:
    queue = read_jsonl_tail(gateway_queue_path(runtime_dir), 1000)
    ledger = read_jsonl_tail(gateway_ledger_path(runtime_dir), 1000)
    delivered_rows = [row for row in ledger if _delivery_counts_as_processed(row)]
    delivered_ids = {row.get("eventId") for row in delivered_rows}
    pending = [row for row in queue if row.get("eventId") not in delivered_ids]
    last = ledger[-1] if ledger else {}
    observability = _delivery_observability(queue, ledger, pending)
    blocked_environment_keys = _unsafe_environment_keys()
    commands_env_requested = "QG_TELEGRAM_COMMANDS_ALLOWED" in blocked_environment_keys
    last_delivery = last.get("delivery") if isinstance(last.get("delivery"), dict) else None
    return {
        "ok": True,
        "schema": "quantgod.telegram_gateway_status.v1",
        "agentVersion": AGENT_VERSION,
        "queuedCount": len(queue),
        "ledgerCount": len(ledger),
        "deliveredCount": len(delivered_rows),
        "pendingCount": len(pending),
        "lastEventId": last.get("eventId"),
        "lastTopic": last.get("topic"),
        "lastDelivery": (
            _minimal_delivery_summary(
                last_delivery,
                processed_at=str(last.get("createdAt") or utc_now_iso()),
            )
            if last_delivery
            else None
        ),
        **observability,
        "pushAllowed": os.environ.get("QG_TELEGRAM_PUSH_ALLOWED", "0").strip() == "1",
        "pushOnly": True,
        "notificationPushOnly": True,
        "commandsAllowed": False,
        "executionLaneExists": False,
        "commandsEnvRequested": commands_env_requested,
        "commandsBlockedReason": "telegram_command_execution_disabled" if commands_env_requested else None,
        "environmentSafe": not blocked_environment_keys,
        "blockedUnsafeEnvironmentKeys": blocked_environment_keys,
        "reasonZh": "独立 Telegram Gateway 当前可审计；负责去重、限频、投递 ledger，不接收命令。",
        "safety": dict(SAFETY_BOUNDARY),
    }


def _delivery_observability(queue: List[Dict[str, Any]], ledger: List[Dict[str, Any]], pending: List[Dict[str, Any]]) -> Dict[str, Any]:
    actual_sent_rows = [row for row in ledger if _delivery_counts_as_processed(row)]
    suppressed_rows = [
        row
        for row in ledger
        if (row.get("delivery") or {}).get("skipped") is True and not (row.get("delivery") or {}).get("ok")
    ]
    failed_rows = [
        row
        for row in ledger
        if row.get("delivery")
        and not _delivery_counts_as_processed(row)
        and not (row.get("delivery") or {}).get("skipped")
    ]
    last_actual = actual_sent_rows[-1] if actual_sent_rows else {}
    last_suppressed = suppressed_rows[-1] if suppressed_rows else {}
    last_failure = failed_rows[-1] if failed_rows else {}
    actual_delivery = last_actual.get("delivery") if isinstance(last_actual.get("delivery"), dict) else {}
    suppressed_delivery = last_suppressed.get("delivery") if isinstance(last_suppressed.get("delivery"), dict) else {}
    failure_delivery = last_failure.get("delivery") if isinstance(last_failure.get("delivery"), dict) else {}
    sent_count_by_topic = _count_by_topic(actual_sent_rows)
    suppressed_count_by_topic = _count_by_topic(suppressed_rows)
    pending_by_topic = _count_by_topic(pending)
    latest_by_topic = _latest_delivery_by_topic(ledger)
    rate_limited = _rate_limited_rows(ledger)
    next_eligible = _next_eligible_send_at() if rate_limited else None
    if pending:
        state_zh = "有待投递消息"
    elif last_suppressed and suppressed_delivery.get("reason") == "duplicate_suppressed":
        state_zh = "最近报告已去重"
    elif last_suppressed and suppressed_delivery.get("reason") == "rate_limited":
        state_zh = "最近投递被限频"
    elif actual_sent_rows:
        state_zh = "最近已真实发送"
    elif queue:
        state_zh = "队列已处理"
    else:
        state_zh = "等待新报告"
    return {
        "deliveryObservability": {
            "stateZh": state_zh,
            "actualSentCount": len(actual_sent_rows),
            "suppressedCount": len(suppressed_rows),
            "failedCount": len(failed_rows),
            "lastActualSentAtIso": _delivery_time(last_actual, actual_delivery, ("sentAtIso", "processedAtIso")),
            "lastActualSentTopic": last_actual.get("topic"),
            "lastSuppressedAtIso": _delivery_time(last_suppressed, suppressed_delivery, ("suppressedAtIso", "processedAtIso")),
            "lastSuppressedTopic": last_suppressed.get("topic"),
            "lastSuppressedReason": suppressed_delivery.get("reason"),
            "lastFailureAtIso": _delivery_time(last_failure, failure_delivery, ("processedAtIso",)),
            "lastFailureTopic": last_failure.get("topic"),
            "lastFailureReason": failure_delivery.get("reason") or failure_delivery.get("error"),
            "sentCountByTopic": sent_count_by_topic,
            "suppressedCountByTopic": suppressed_count_by_topic,
            "pendingByTopic": pending_by_topic,
            "latestByTopic": latest_by_topic,
            "nextEligibleSendAtIso": next_eligible,
        },
        "lastActualSentAtIso": _delivery_time(last_actual, actual_delivery, ("sentAtIso", "processedAtIso")),
        "lastSuppressedAtIso": _delivery_time(last_suppressed, suppressed_delivery, ("suppressedAtIso", "processedAtIso")),
        "lastSuppressedReason": suppressed_delivery.get("reason"),
        "suppressedCount": len(suppressed_rows),
        "sentCountByTopic": sent_count_by_topic,
        "pendingByTopic": pending_by_topic,
        "nextEligibleSendAtIso": next_eligible,
    }


def _count_by_topic(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        topic = str(row.get("topic") or "UNKNOWN")
        counts[topic] = counts.get(topic, 0) + 1
    return dict(sorted(counts.items()))


def _delivery_time(row: Dict[str, Any], delivery: Dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if delivery.get(key):
            return str(delivery.get(key))
    for key in ("createdAt", "createdAtIso", "generatedAtIso"):
        if row.get(key):
            return str(row.get(key))
    return None


def _latest_delivery_by_topic(ledger: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in ledger:
        topic = str(row.get("topic") or "UNKNOWN")
        delivery = row.get("delivery") if isinstance(row.get("delivery"), dict) else {}
        latest[topic] = {
            "eventId": row.get("eventId"),
            "deliveryOk": _delivery_is_confirmed(delivery),
            "reason": delivery.get("reason") or delivery.get("error"),
            "processedAtIso": _delivery_time(row, delivery, ("sentAtIso", "suppressedAtIso", "processedAtIso")),
        }
    return latest


def _rate_limited_rows(ledger: List[Dict[str, Any]]) -> bool:
    current_hour = utc_now_iso()[:13]
    sent = [
        row
        for row in ledger[-200:]
        if _delivery_counts_as_processed(row)
        and str(row.get("createdAt") or "").startswith(current_hour)
    ]
    return len(sent) >= MAX_EVENTS_PER_RUN


def _next_eligible_send_at() -> str:
    next_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_hour.isoformat().replace("+00:00", "Z")


def _build_daily_autopilot_event(runtime_dir: Path, repo_root: Path, refresh: bool) -> Dict[str, Any]:
    from daily_autopilot_v2.report import build_daily_autopilot_v2
    from daily_autopilot_v2.telegram_text import daily_autopilot_v2_to_chinese_text

    payload = build_daily_autopilot_v2(runtime_dir, repo_root=repo_root, write=refresh)
    text = daily_autopilot_v2_to_chinese_text(payload)
    return build_notification_event(
        "daily_autopilot_v2",
        "DAILY_AUTOPILOT_V2_REPORT",
        "INFO",
        text,
        payload={"dailyAutopilotV2": payload},
        dedupe_key=f"{_local_day()}|DAILY_AUTOPILOT_V2_REPORT",
    )


def _build_ga_event(runtime_dir: Path, repo_root: Path, refresh: bool) -> Dict[str, Any]:
    del repo_root, refresh
    from strategy_ga.generation_runner import build_ga_status
    from strategy_ga.telegram_text import ga_to_chinese_text

    ga_status = build_ga_status(runtime_dir)
    payload = {
        "status": ga_status.get("status") if isinstance(ga_status.get("status"), dict) else {},
        "generation": ga_status.get("generation") if isinstance(ga_status.get("generation"), dict) else {},
        "blockers": ga_status.get("blockers") if isinstance(ga_status.get("blockers"), dict) else {},
        "evolutionPath": ga_status.get("evolutionPath") if isinstance(ga_status.get("evolutionPath"), dict) else {},
    }
    text = ga_to_chinese_text(payload)
    status = payload["status"]
    dedupe_key = "|".join(
        [
            "GA_EVOLUTION_REPORT",
            str(status.get("currentGeneration") or 0),
            str(status.get("bestSeedId") or "none"),
            str(status.get("bestFitness") or 0),
            str(status.get("blockedCandidates") or 0),
        ]
    )
    severity = "WARN" if int(status.get("blockedCandidates") or 0) else "INFO"
    return build_notification_event(
        "strategy_ga",
        "GA_EVOLUTION_REPORT",
        severity,
        text,
        payload={"strategyGa": ga_status},
        dedupe_key=dedupe_key,
    )


def _build_autonomous_agent_event(runtime_dir: Path, repo_root: Path, refresh: bool) -> Dict[str, Any]:
    del repo_root
    from usdjpy_autonomous_agent.agent_state import build_agent_state
    from usdjpy_autonomous_agent.telegram_text import autonomous_agent_to_chinese_text

    payload = build_agent_state(runtime_dir, write=refresh)
    text = autonomous_agent_to_chinese_text(payload)
    patch = payload.get("currentPatch") if isinstance(payload.get("currentPatch"), dict) else {}
    rollback = patch.get("rollback") if isinstance(patch.get("rollback"), dict) else {}
    hard_blockers = rollback.get("hardBlockers") if isinstance(rollback.get("hardBlockers"), list) else []
    severity = "WARN" if hard_blockers or "ROLLBACK" in str(payload.get("stage") or "") else "INFO"
    blocker_signature = _blocker_signature(hard_blockers)
    dedupe_key = "|".join(
        [
            _local_day(),
            "USDJPY_AUTONOMOUS_AGENT_REPORT",
            str(payload.get("stage") or "UNKNOWN"),
            str(patch.get("patchId") or "no_patch"),
            blocker_signature,
        ]
    )
    return build_notification_event(
        "usdjpy_autonomous_agent",
        "USDJPY_AUTONOMOUS_AGENT_REPORT",
        severity,
        text,
        payload={"autonomousAgent": payload},
        dedupe_key=dedupe_key,
    )


def _send_telegram(text: str) -> Dict[str, Any]:
    blocked_environment_keys = _unsafe_environment_keys()
    if blocked_environment_keys:
        reason = "unsafe_environment_flags_enabled: " + ",".join(blocked_environment_keys)
        if blocked_environment_keys == ["QG_TELEGRAM_COMMANDS_ALLOWED"]:
            reason = "Telegram command execution must stay disabled"
        return {
            "ok": False,
            "skipped": True,
            "blocked": True,
            "reason": reason,
            "blockedUnsafeEnvironmentKeys": blocked_environment_keys,
        }
    if os.environ.get("QG_TELEGRAM_PUSH_ALLOWED", "0").strip() != "1":
        return {"ok": False, "skipped": True, "reason": "QG_TELEGRAM_PUSH_ALLOWED is not 1"}
    token = os.environ.get("QG_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("QG_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return {"ok": False, "skipped": True, "reason": "Telegram token/chat_id missing"}
    safe_text = prepare_telegram_text(_redact_sensitive_text(text, explicit_secret=token))
    url = f"https://api.telegram.org/bot{urllib.parse.quote(token, safe=':')}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": safe_text}).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=body, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            telegram_ok = payload.get("ok") is True
            message_id = _extract_telegram_message_id(payload)
            if not telegram_ok:
                return {
                    "ok": False,
                    "reason": "telegram_api_rejected",
                    "transport": "urllib",
                }
            if message_id is None:
                return {
                    "ok": False,
                    "reason": "telegram_delivery_unconfirmed_missing_message_id",
                    "transport": "urllib",
                }
            return {
                "ok": True,
                "messageId": message_id,
                "transport": "urllib",
            }
    except Exception as exc:
        return {
            "ok": False,
            "error": _redact_sensitive_text(f"{type(exc).__name__}: {exc}", explicit_secret=token)[:300],
            "transport": "urllib",
        }


def prepare_telegram_text(text: Any) -> str:
    """Bound Telegram text while preserving the permanent push-only boundary."""
    normalized = sanitize_telegram_message(_redact_sensitive_text(str(text or "")))
    body = "\n".join(
        line for line in normalized.splitlines() if line.strip() != TELEGRAM_SAFETY_FOOTER
    ).rstrip()
    max_body_chars = TELEGRAM_TEXT_MAX_CHARS - len(TELEGRAM_SAFETY_FOOTER) - 1
    if len(body) > max_body_chars:
        notice = f"\n{TELEGRAM_TRUNCATION_NOTICE}"
        prefix_budget = max(0, max_body_chars - len(notice))
        prefix = body[:prefix_budget].rstrip()
        body = f"{prefix}{notice}" if prefix else TELEGRAM_TRUNCATION_NOTICE[:max_body_chars]
    result = f"{body}\n{TELEGRAM_SAFETY_FOOTER}" if body else TELEGRAM_SAFETY_FOOTER
    return result


def _unsafe_environment_keys() -> List[str]:
    """Use the shared process + local-file safety scan as the send gate."""
    return unsafe_telegram_environment_keys()


def _minimal_ledger_row(
    event: Dict[str, Any],
    delivery: Dict[str, Any],
    *,
    processed_at: str,
) -> Dict[str, Any]:
    text = str(event.get("text") or "")
    created_at = str(event.get("createdAt") or processed_at)[:64]
    return {
        "schema": "quantgod.telegram_gateway_ledger.v2",
        "eventId": _bounded_label(event.get("eventId"), 128),
        "topic": _bounded_label(event.get("topic"), 96),
        "severity": _bounded_label(event.get("severity"), 32),
        "messageLength": len(text),
        "messagePreview": _message_preview(text),
        "createdAt": created_at,
        "delivery": delivery,
    }


def _minimal_delivery_summary(delivery: Dict[str, Any], *, processed_at: str) -> Dict[str, Any]:
    raw = delivery if isinstance(delivery, dict) else {}
    message_id = _extract_delivery_message_id(raw)
    ok = _delivery_is_confirmed(raw)
    skipped = raw.get("skipped") is True and not ok
    summary: Dict[str, Any] = {
        "ok": ok,
        "skipped": skipped,
        "status": "SENT" if ok else "SUPPRESSED" if skipped else "FAILED",
        "processedAtIso": _bounded_label(raw.get("processedAtIso") or processed_at, 64),
    }
    if ok:
        summary["sentAtIso"] = _bounded_label(raw.get("sentAtIso") or processed_at, 64)
    elif skipped:
        summary["suppressedAtIso"] = _bounded_label(raw.get("suppressedAtIso") or processed_at, 64)
    reason = raw.get("reason")
    if raw.get("ok") is True and message_id is None:
        reason = "telegram_delivery_unconfirmed_missing_message_id"
    if reason:
        summary["reason"] = _redact_sensitive_text(str(reason))[:160]
    elif not ok and not skipped:
        summary["reason"] = "telegram_delivery_failed"
    if message_id is not None:
        summary["messageId"] = message_id
    transport = str(raw.get("transport") or "").strip().lower()
    if transport in {"urllib"}:
        summary["transport"] = transport
    return summary


def _message_preview(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    return _redact_sensitive_text(normalized)[:TELEGRAM_MESSAGE_PREVIEW_MAX_CHARS]


def _bounded_label(value: Any, max_chars: int) -> str:
    return str(value or "")[:max_chars]


def _redact_sensitive_text(value: str, *, explicit_secret: str = "") -> str:
    text = str(value or "")
    if explicit_secret:
        text = text.replace(explicit_secret, "[REDACTED]")
        quoted_secret = urllib.parse.quote(explicit_secret, safe=":")
        if quoted_secret != explicit_secret:
            text = text.replace(quoted_secret, "[REDACTED]")
    text = _TELEGRAM_BOT_TOKEN_RE.sub("[REDACTED_BOT_TOKEN]", text)
    return _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)


def _safe_event_text(value: Any) -> str:
    return sanitize_telegram_message(_redact_sensitive_text(str(value or "")))


def _extract_telegram_message_id(payload: Dict[str, Any]) -> int | str | None:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return _safe_message_id(result.get("message_id"))


def _extract_delivery_message_id(delivery: Dict[str, Any]) -> int | str | None:
    for candidate in (delivery.get("messageId"), delivery.get("message_id")):
        safe = _safe_message_id(candidate)
        if safe is not None:
            return safe
    telegram = delivery.get("telegram") if isinstance(delivery.get("telegram"), dict) else {}
    return _extract_telegram_message_id(telegram)


def _safe_message_id(value: Any) -> int | str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return text[:32] if text.isdigit() else None


def _fmt(value: Any, default: str = "—") -> str:
    if value in (None, ""):
        return default
    return str(value)


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def _blocker_signature(blockers: List[Any]) -> str:
    if not blockers:
        return "no_blockers"
    normalized: List[str] = []
    for item in blockers[:8]:
        text = str(item)
        for sep in ("：", ":"):
            if sep in text:
                text = text.split(sep, 1)[0]
                break
        normalized.append(text.strip() or "UNKNOWN")
    return _short_hash("|".join(normalized))


def _local_day() -> str:
    return date.today().isoformat()


def _ensure_import_paths(repo_root: Path) -> None:
    for candidate in (repo_root, repo_root / "tools"):
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)


def _rate_limited(ledger: Path) -> bool:
    current_hour = utc_now_iso()[:13]
    recent = read_jsonl_tail(ledger, 200)
    sent = [
        row
        for row in recent
        if _delivery_counts_as_processed(row)
        and str(row.get("createdAt") or "").startswith(current_hour)
    ]
    return len(sent) >= MAX_EVENTS_PER_RUN


def _delivery_counts_as_processed(row: Dict[str, Any]) -> bool:
    delivery = row.get("delivery") if isinstance(row.get("delivery"), dict) else {}
    return _delivery_is_confirmed(delivery)


def _delivery_is_confirmed(delivery: Dict[str, Any]) -> bool:
    """Only a positive Telegram API result with a message receipt is SENT."""
    telegram = delivery.get("telegram") if isinstance(delivery.get("telegram"), dict) else None
    telegram_ok = telegram.get("ok") is True if telegram is not None else True
    return (
        delivery.get("ok") is True
        and telegram_ok
        and _extract_delivery_message_id(delivery) is not None
    )
