from __future__ import annotations
"""Status builders for Telegram Gateway queue and ledger observability."""

from pathlib import Path
from typing import Any, Dict, List

try:
    from tools.usdjpy_evidence_os.io_utils import utc_now_iso
    from tools.usdjpy_evidence_os.schema import (
        gateway_ledger_path,
        gateway_queue_path,
        gateway_status_path,
    )
    from tools.usdjpy_evidence_os.telegram_gateway import (
        collect_scheduled_events,
        gateway_status,
    )
except ModuleNotFoundError:  # pragma: no cover
    from usdjpy_evidence_os.io_utils import utc_now_iso
    from usdjpy_evidence_os.schema import (
        gateway_ledger_path,
        gateway_queue_path,
        gateway_status_path,
    )
    from usdjpy_evidence_os.telegram_gateway import (
        collect_scheduled_events,
        gateway_status,
    )

from .io_utils import count_by_topic, load_json, read_jsonl_tail
from .schema import AGENT_VERSION, OPS_TOPICS, SAFETY, SCHEMA_OPS_STATUS


def build_gateway_ops_status(runtime_dir: Path) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    base_status = gateway_status(runtime_dir)
    stored_status = load_json(gateway_status_path(runtime_dir))
    queue = read_jsonl_tail(gateway_queue_path(runtime_dir), 1000)
    ledger = read_jsonl_tail(gateway_ledger_path(runtime_dir), 1000)
    processed_ids = {
        row.get("eventId")
        for row in ledger
        if _delivery_counts_as_processed(row)
    }
    pending_rows = [row for row in queue if row.get("eventId") not in processed_ids]
    sent_rows = [row for row in ledger if _delivery(row).get("ok") is True]
    suppressed_rows = [
        row
        for row in ledger
        if _delivery(row).get("skipped") is True and not _delivery(row).get("ok")
    ]
    failed_rows = [
        row
        for row in ledger
        if row.get("delivery") and not _delivery(row).get("ok") and not _delivery(row).get("skipped")
    ]
    topic_delivery_rows = _topic_delivery_rows(ledger)
    topic_pending_rows = _topic_pending_rows(pending_rows)
    delivery_observability = base_status.get("deliveryObservability")
    if not isinstance(delivery_observability, dict):
        delivery_observability = {}
    return {
        "ok": True,
        "schema": SCHEMA_OPS_STATUS,
        "agentVersion": AGENT_VERSION,
        "generatedAt": utc_now_iso(),
        "status": _ops_status(base_status, pending_rows, failed_rows),
        "statusZh": _ops_status_zh(base_status, pending_rows, failed_rows),
        "queuedCount": len(queue),
        "pendingCount": len(pending_rows),
        "ledgerCount": len(ledger),
        "actualSentCount": len(sent_rows),
        "suppressedCount": len(suppressed_rows),
        "failedCount": len(failed_rows),
        "latestTopicRows": topic_delivery_rows,
        "pendingTopicRows": topic_pending_rows,
        "pendingByTopic": count_by_topic(pending_rows),
        "sentCountByTopic": count_by_topic(sent_rows),
        "suppressedCountByTopic": count_by_topic(suppressed_rows),
        "failedCountByTopic": count_by_topic(failed_rows),
        "deliveryObservability": delivery_observability,
        "lastEventId": base_status.get("lastEventId") or stored_status.get("lastEventId"),
        "lastTopic": base_status.get("lastTopic") or stored_status.get("lastTopic"),
        "lastDelivery": base_status.get("lastDelivery") or stored_status.get("lastDelivery"),
        "pushAllowed": bool(base_status.get("pushAllowed")),
        "commandsAllowed": False,
        "commandsEnvRequested": bool(base_status.get("commandsEnvRequested")),
        "commandsBlockedReason": base_status.get("commandsBlockedReason"),
        "gatewayFiles": {
            "status": str(gateway_status_path(runtime_dir)),
            "ledger": str(gateway_ledger_path(runtime_dir)),
            "queue": str(gateway_queue_path(runtime_dir)),
        },
        "managedTopics": list(OPS_TOPICS),
        "reasonZh": (
            "Telegram Gateway Ops 只做队列、去重、限频、失败和 topic 状态观测；"
            "不接收 Telegram 交易命令。"
        ),
        "safety": dict(SAFETY),
    }


def collect_gateway_ops(
    runtime_dir: Path,
    repo_root: Path | None = None,
    *,
    refresh: bool = True,
) -> Dict[str, Any]:
    collect_status = collect_scheduled_events(Path(runtime_dir), repo_root=repo_root, refresh=refresh)
    status = build_gateway_ops_status(Path(runtime_dir))
    return {
        **status,
        "collectedCount": collect_status.get("collectedCount", 0),
        "collectedEvents": collect_status.get("collectedEvents", []),
        "collectErrors": collect_status.get("collectErrors", []),
        "collectStatus": collect_status,
    }


def _delivery(row: Dict[str, Any]) -> Dict[str, Any]:
    delivery = row.get("delivery")
    return delivery if isinstance(delivery, dict) else {}


def _delivery_counts_as_processed(row: Dict[str, Any]) -> bool:
    delivery = _delivery(row)
    # Only successful sends clear a queue item from the pending view.
    return bool(delivery.get("ok"))


def _topic_delivery_rows(ledger: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in ledger:
        topic = str(row.get("topic") or "UNKNOWN")
        delivery = _delivery(row)
        latest[topic] = {
            "topic": topic,
            "eventId": row.get("eventId"),
            "source": row.get("source"),
            "severity": row.get("severity"),
            "deliveryOk": bool(delivery.get("ok")),
            "skipped": bool(delivery.get("skipped")),
            "reason": delivery.get("reason") or delivery.get("error"),
            "processedAtIso": _delivery_time(row, delivery),
        }
    return sorted(latest.values(), key=lambda row: str(row.get("topic") or ""))


def _topic_pending_rows(pending: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in pending:
        topic = str(row.get("topic") or "UNKNOWN")
        latest[topic] = {
            "topic": topic,
            "eventId": row.get("eventId"),
            "source": row.get("source"),
            "severity": row.get("severity"),
            "createdAt": row.get("createdAt"),
            "textPreview": str(row.get("text") or "")[:160],
        }
    return sorted(latest.values(), key=lambda row: str(row.get("topic") or ""))


def _delivery_time(row: Dict[str, Any], delivery: Dict[str, Any]) -> str | None:
    for key in ("sentAtIso", "suppressedAtIso", "processedAtIso"):
        if delivery.get(key):
            return str(delivery.get(key))
    return row.get("createdAt") or row.get("createdAtIso") or row.get("generatedAtIso")


def _ops_status(base_status: Dict[str, Any], pending: List[Dict[str, Any]], failed: List[Dict[str, Any]]) -> str:
    if base_status.get("commandsEnvRequested"):
        return "COMMAND_ENV_BLOCKED_WARN"
    if failed:
        return "DELIVERY_WARN"
    if pending:
        return "PENDING_DELIVERY"
    return "GATEWAY_OBSERVABLE"


def _ops_status_zh(base_status: Dict[str, Any], pending: List[Dict[str, Any]], failed: List[Dict[str, Any]]) -> str:
    if base_status.get("commandsEnvRequested"):
        return "Telegram 命令开关被误设，但执行入口已硬阻断"
    if failed:
        return "有投递失败需要复核"
    if pending:
        return "有待投递消息"
    return "Gateway 可观测"
