"""Schema and safety helpers for QuantGod auto execution policy.

This module produces an EA-readable policy, but it does not place orders.
The generated policy is an advisory/control-plane artifact that an EA may read
only after the operator explicitly wires it into EA logic.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

SCHEMA_VERSION = "quantgod.auto_execution_policy.v1"
DEFAULT_MAX_LOT = 2.0
DEFAULT_RISK_PCT = 0.5
DEFAULT_OPPORTUNITY_MULTIPLIER = 0.35
DEFAULT_STANDARD_MULTIPLIER = 1.0

ENTRY_STANDARD = "STANDARD_ENTRY"
ENTRY_OPPORTUNITY = "OPPORTUNITY_ENTRY"
ENTRY_BLOCKED = "BLOCKED"

ACTION_LABELS_ZH = {
    ENTRY_STANDARD: "标准入场",
    ENTRY_OPPORTUNITY: "机会入场",
    ENTRY_BLOCKED: "阻断",
    "LONG": "买入观察",
    "SHORT": "卖出观察",
    "BUY": "买入观察",
    "SELL": "卖出观察",
}

EXECUTION_FLAG_KEYS = {
    "orderSendAllowed",
    "closeAllowed",
    "cancelAllowed",
    "modifyAllowed",
    "brokerExecutionAllowed",
    "telegramCommandExecutionAllowed",
    "telegramWebhookReceiverAllowed",
    "webhookReceiverAllowed",
    "credentialStorageAllowed",
    "livePresetMutationAllowed",
    "canOverrideKillSwitch",
    "writesMt5Preset",
    "writesMt5OrderRequest",
    "externalMarketOrderAllowed",
    "walletIntegrationAllowed",
}
SECRET_LIKE_KEYS = {
    "password",
    "passwd",
    "token",
    "apiKey",
    "apikey",
    "secret",
    "authorization",
    "bearer",
    "private_key",
    "privateKey",
    "access_key",
    "accessKey",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safety_payload() -> Dict[str, Any]:
    return {
        "localOnly": True,
        "readOnlyDataPlane": True,
        "advisoryOnly": True,
        "autoExecutionPolicyOnly": True,
        "eaMayReadPolicy": True,
        "orderSendAllowed": False,
        "closeAllowed": False,
        "cancelAllowed": False,
        "modifyAllowed": False,
        "brokerExecutionAllowed": False,
        "credentialStorageAllowed": False,
        "livePresetMutationAllowed": False,
        "canOverrideKillSwitch": False,
        "telegramCommandExecutionAllowed": False,
        "telegramWebhookReceiverAllowed": False,
        "webhookReceiverAllowed": False,
        "emailDeliveryAllowed": False,
        "writesMt5Preset": False,
        "writesMt5OrderRequest": False,
        "externalMarketOrderAllowed": False,
        "walletIntegrationAllowed": False,
    }


def normalize_direction(direction: str | None) -> str:
    value = str(direction or "LONG").upper()
    if value in {"BUY", "LONG"}:
        return "LONG"
    if value in {"SELL", "SHORT"}:
        return "SHORT"
    return value


def zh_direction(direction: str | None) -> str:
    return ACTION_LABELS_ZH.get(normalize_direction(direction), str(direction or "未知方向"))


def zh_entry_mode(mode: str | None) -> str:
    return ACTION_LABELS_ZH.get(str(mode or ENTRY_BLOCKED), str(mode or "阻断"))


def iter_nested(obj: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_path = f"{path}.{key}" if path else str(key)
            yield next_path, value
            yield from iter_nested(value, next_path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            next_path = f"{path}[{index}]"
            yield next_path, value
            yield from iter_nested(value, next_path)


def validate_safe_payload(payload: Dict[str, Any]) -> None:
    for path, value in iter_nested(payload):
        key = path.split(".")[-1].split("[")[0]
        if key in SECRET_LIKE_KEYS and value not in (None, "", "***", "REDACTED"):
            raise ValueError(f"secret-like field is not allowed in auto execution policy: {path}")
        if key in EXECUTION_FLAG_KEYS and bool(value):
            raise ValueError(f"execution flag must remain false in policy artifact: {path}")


@dataclass
class AutoPolicyRow:
    symbol: str
    direction: str
    strategy: str = "AUTO_POLICY"
    regime: str = "UNKNOWN"
    entryMode: str = ENTRY_BLOCKED
    allowed: bool = False
    score: float = 0.0
    maxLot: float = DEFAULT_MAX_LOT
    recommendedLot: float = 0.0
    riskPerTradePct: float = DEFAULT_RISK_PCT
    entryStrictness: str = "BLOCKED"
    exitMode: str = "PROTECT_CAPITAL"
    breakevenDelayR: float = 0.8
    trailStartR: float = 1.4
    timeStopBars: int = 6
    initialStopReference: str = "动态止损计划待确认"
    targetReference: str = "动态止盈计划待确认"
    reason: str = "缺少核心证据，阻断"
    blockers: List[str] | None = None
    warnings: List[str] | None = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["directionLabelZh"] = zh_direction(self.direction)
        data["entryModeLabelZh"] = zh_entry_mode(self.entryMode)
        data["safety"] = safety_payload()
        return data


def build_policy_document(rows: List[AutoPolicyRow], runtime_dir: str, generated_by: str = "run_auto_execution_policy.py") -> Dict[str, Any]:
    payload = {
        "schema": SCHEMA_VERSION,
        "generatedAt": now_iso(),
        "generatedBy": generated_by,
        "runtimeDir": runtime_dir,
        "summary": {
            "rows": len(rows),
            "standardEntries": sum(1 for r in rows if r.entryMode == ENTRY_STANDARD),
            "opportunityEntries": sum(1 for r in rows if r.entryMode == ENTRY_OPPORTUNITY),
            "blocked": sum(1 for r in rows if r.entryMode == ENTRY_BLOCKED),
        },
        "policies": [r.to_dict() for r in rows],
        "safety": safety_payload(),
    }
    validate_safe_payload(payload)
    return payload
