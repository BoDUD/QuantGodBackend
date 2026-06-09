"""Schema and safety helpers for AI advisory outcome journal."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

JOURNAL_SCHEMA = "quantgod.ai_advisory_journal.v1"
OUTCOME_SCHEMA = "quantgod.ai_advisory_outcome.v1"
SUMMARY_SCHEMA = "quantgod.ai_advisory_summary.v1"
MODE = "QUANTGOD_AI_ADVISORY_JOURNAL_V1"

EXECUTION_FLAGS = {
    "orderSendAllowed",
    "closeAllowed",
    "cancelAllowed",
    "modifyAllowed",
    "credentialStorageAllowed",
    "livePresetMutationAllowed",
    "canOverrideKillSwitch",
    "telegramCommandExecutionAllowed",
    "telegramWebhookReceiverAllowed",
    "webhookReceiverAllowed",
    "emailDeliveryAllowed",
    "brokerExecutionAllowed",
    "externalMarketOrderAllowed",
    "walletIntegrationAllowed",
}

SECRET_KEYS = {
    "password",
    "passwd",
    "token",
    "apiKey",
    "api_key",
    "secret",
    "authorization",
    "bearer",
    "private_key",
    "privateKey",
    "wallet",
    "seed",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safety_payload() -> dict[str, Any]:
    return {
        "mode": MODE,
        "localOnly": True,
        "readOnlyDataPlane": True,
        "advisoryOnly": True,
        "shadowTradingOnly": True,
        "outcomeJournalOnly": True,
        "telegramPushOnly": True,
        "orderSendAllowed": False,
        "closeAllowed": False,
        "cancelAllowed": False,
        "modifyAllowed": False,
        "credentialStorageAllowed": False,
        "livePresetMutationAllowed": False,
        "canOverrideKillSwitch": False,
        "telegramCommandExecutionAllowed": False,
        "telegramWebhookReceiverAllowed": False,
        "webhookReceiverAllowed": False,
        "emailDeliveryAllowed": False,
        "brokerExecutionAllowed": False,
        "externalMarketOrderAllowed": False,
        "walletIntegrationAllowed": False,
    }


def _walk(value: Any, path: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            items.append((child_path, child))
            items.extend(_walk(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            items.append((child_path, child))
            items.extend(_walk(child, child_path))
    return items


def validate_no_secrets(payload: dict[str, Any]) -> None:
    """Reject journal payloads that accidentally contain credentials."""
    violations: list[str] = []
    for path, value in _walk(payload):
        key = path.split(".")[-1].split("[")[0]
        normalized = key.lower().replace("-", "_")
        if normalized in {item.lower() for item in SECRET_KEYS}:
            violations.append(path)
        if isinstance(value, str):
            lowered = value.lower()
            if "bearer " in lowered or "api_key=" in lowered or "private key" in lowered:
                violations.append(path)
    if violations:
        raise ValueError("AI journal payload contains secret-like fields: " + ", ".join(sorted(set(violations))[:8]))


def validate_safety_flags(payload: dict[str, Any]) -> None:
    """Reject any truthy execution capability in journal records."""
    violations: list[str] = []
    for path, value in _walk(payload):
        key = path.split(".")[-1].split("[")[0]
        if key in EXECUTION_FLAGS and bool(value):
            violations.append(path)
    if violations:
        raise ValueError("AI journal payload contains enabled execution flags: " + ", ".join(sorted(set(violations))[:8]))


def validate_record(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise TypeError("journal record must be a dict")
    if payload.get("schema") not in {JOURNAL_SCHEMA, OUTCOME_SCHEMA, SUMMARY_SCHEMA}:
        raise ValueError(f"unsupported journal schema: {payload.get('schema')}")
    validate_no_secrets(payload)
    validate_safety_flags(payload)
