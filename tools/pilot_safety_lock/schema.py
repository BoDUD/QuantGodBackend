from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

SCHEMA = "quantgod.pilot_safety_lock.v1"
DEFAULT_CONFIRMATION_PHRASE = "我确认仅允许最小仓位试点，禁止自动扩大风险"
DEFAULT_MAX_LOT = 0.01
DEFAULT_MAX_DAILY_TRADES = 3
DEFAULT_MAX_DAILY_LOSS_R = 1.0
DEFAULT_MAX_SPREAD_MULTIPLIER = 1.5

SAFETY_DEFAULTS: Dict[str, Any] = {
    "localOnly": True,
    "advisoryOnly": True,
    "humanApprovalRequired": True,
    "pilotSafetyLockOnly": True,
    "orderSendAllowedByThisTool": False,
    "closeAllowedByThisTool": False,
    "cancelAllowedByThisTool": False,
    "modifyAllowedByThisTool": False,
    "writesMt5OrderRequest": False,
    "writesMt5Preset": False,
    "telegramCommandExecutionAllowed": False,
    "webhookReceiverAllowed": False,
    "credentialStorageAllowed": False,
    "walletIntegrationAllowed": False,
    "externalMarketOrderAllowed": False,
}

DANGEROUS_KEYS = {
    "password",
    "passwd",
    "token",
    "apikey",
    "api_key",
    "secret",
    "authorization",
    "bearer",
    "privatekey",
    "private_key",
    "walletprivatekey",
}

EXECUTION_TRUE_KEYS = {
    "orderSendAllowed",
    "closeAllowed",
    "cancelAllowed",
    "modifyAllowed",
    "brokerExecutionAllowed",
    "writesMt5OrderRequest",
    "writesMt5Preset",
    "telegramCommandExecutionAllowed",
    "webhookReceiverAllowed",
    "credentialStorageAllowed",
    "externalMarketOrderAllowed",
    "walletIntegrationAllowed",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def base_report() -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "generatedAt": utc_now(),
        "decision": "BLOCKED",
        "decisionZh": "阻断",
        "safety": dict(SAFETY_DEFAULTS),
        "checks": [],
        "reasons": [],
        "pilotEnvelope": {},
        "runtimeEvidence": {},
    }


def add_check(report: Dict[str, Any], name: str, passed: bool, detail: str, severity: str = "BLOCKER") -> None:
    report.setdefault("checks", []).append({
        "name": name,
        "passed": bool(passed),
        "severity": severity,
        "detail": detail,
    })
    if not passed:
        report.setdefault("reasons", []).append(detail)


def validate_no_secret_or_execution_flags(payload: Any, path: str = "root", errors: List[str] | None = None) -> List[str]:
    if errors is None:
        errors = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).replace("-", "_").lower()
            compact = normalized.replace("_", "")
            if normalized in DANGEROUS_KEYS or compact in DANGEROUS_KEYS:
                errors.append(f"发现疑似凭据字段：{path}.{key}")
            if key in EXECUTION_TRUE_KEYS and value is True:
                errors.append(f"发现执行能力被打开：{path}.{key}=true")
            validate_no_secret_or_execution_flags(value, f"{path}.{key}", errors)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            validate_no_secret_or_execution_flags(item, f"{path}[{index}]", errors)
    return errors
