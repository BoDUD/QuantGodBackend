from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_RECEIPT_KEYS = ("telegramMessageId", "messageId")
_NESTED_KEYS = ("delivery", "gateway", "telegramGateway", "results")


def confirmed_message_id(payload: Any) -> Any | None:
    """Return a receipt only when every explicit delivery flag is affirmative."""
    if isinstance(payload, str):
        has_receipt = re.search(r'"(?:telegramMessageId|messageId)"\s*:\s*(?!null)["\d]', payload)
        has_truth = re.search(r'"(?:deliveryOk|sent)"\s*:\s*true', payload, flags=re.IGNORECASE)
        return "stdout_receipt" if has_receipt and has_truth else None
    if isinstance(payload, list):
        receipts = [confirmed_message_id(item) for item in payload]
        return "multiple_receipts" if receipts and all(item not in (None, "") for item in receipts) else None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("sent") is False or payload.get("deliveryOk") is False or payload.get("ok") is False:
        return None
    for key in _RECEIPT_KEYS:
        message_id = payload.get(key)
        if message_id not in (None, ""):
            return message_id
    for key in _NESTED_KEYS:
        message_id = confirmed_message_id(payload.get(key))
        if message_id not in (None, ""):
            return message_id
    return None


def normalize_delivery(payload: Any, *, send_requested: bool) -> dict[str, Any]:
    normalized = dict(payload) if isinstance(payload, Mapping) else {"result": payload}
    confirmed = confirmed_message_id(normalized) not in (None, "") if send_requested else False
    normalized.update(
        {
            "sendRequested": bool(send_requested),
            "sent": confirmed,
            "deliveryOk": confirmed,
        }
    )
    if send_requested and not confirmed:
        normalized["ok"] = False
        normalized.setdefault("error", "TELEGRAM_DELIVERY_NOT_CONFIRMED")
    return normalized


def normalize_cli_payload(
    payload: Mapping[str, Any],
    *,
    send_requested: bool,
    delivery_key: str = "telegramGateway",
) -> dict[str, Any]:
    """Expose one fail-closed delivery truth at the CLI's outer result level."""
    normalized = dict(payload)
    delivery = normalized.get(delivery_key)
    confirmed = bool(send_requested and confirmed_message_id(delivery) not in (None, ""))
    normalized.update(
        {
            "sendRequested": bool(send_requested),
            "sent": confirmed,
            "deliveryOk": confirmed,
            "ok": normalized.get("ok") is not False and (not send_requested or confirmed),
        }
    )
    if send_requested and not confirmed:
        normalized.setdefault("error", "TELEGRAM_DELIVERY_NOT_CONFIRMED")
    return normalized


def explicit_send_exit_code(send_requested: bool, payload: Any) -> int:
    if not send_requested:
        return 0
    return 0 if confirmed_message_id(payload) not in (None, "") else 2
