from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "quantgod.adaptive_policy.v1"

SAFETY_DEFAULTS: dict[str, bool] = {
    "localOnly": True,
    "readOnlyDataPlane": True,
    "advisoryOnly": True,
    "shadowTradingOnly": True,
    "adaptivePolicyOnly": True,
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
    "writesMt5Preset": False,
    "writesMt5OrderRequest": False,
}

FORBIDDEN_KEY_PATTERNS = (
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
    "wallet",
    "mnemonic",
)

EXECUTION_FLAG_KEYS = (
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
    "writesMt5Preset",
    "writesMt5OrderRequest",
)

SAFE_EXECUTION_FLAG_KEYS = set(EXECUTION_FLAG_KEYS)

DIRECTION_ALIASES = {
    "BUY": "LONG",
    "LONG": "LONG",
    "WATCH_LONG": "LONG",
    "偏多观察": "LONG",
    "买入": "LONG",
    "SELL": "SHORT",
    "SHORT": "SHORT",
    "WATCH_SHORT": "SHORT",
    "偏空观察": "SHORT",
    "卖出": "SHORT",
    "HOLD": "FLAT",
    "PAUSED": "FLAT",
    "观望": "FLAT",
    "暂停": "FLAT",
}

@dataclass(frozen=True)
class PolicyThresholds:
    min_samples: int = 5
    active_min_samples: int = 7
    min_win_rate: float = 0.52
    pause_win_rate: float = 0.40
    min_avg_score_r: float = 0.05
    pause_avg_score_r: float = -0.25
    max_consecutive_losses: int = 5
    max_runtime_age_seconds: int = 90
    max_spread_multiplier: float = 1.8
    min_atr: float = 0.0
    cooldown_seconds: int = 86400
    max_plan_records: int = 500

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def normalize_direction(value: Any) -> str:
    text = str(value or "").strip()
    upper = text.upper()
    if upper in DIRECTION_ALIASES:
        return DIRECTION_ALIASES[upper]
    if text in DIRECTION_ALIASES:
        return DIRECTION_ALIASES[text]
    if "LONG" in upper or "BUY" in upper or "偏多" in text or "买" in text:
        return "LONG"
    if "SHORT" in upper or "SELL" in upper or "偏空" in text or "卖" in text:
        return "SHORT"
    return "FLAT"

def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "").replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default

def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default

def assert_safe_payload(payload: Any, path: str = "$") -> None:
    """Reject secrets and execution capability flags in output payloads."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            compact = key_text.replace("-", "").replace("_", "").lower()
            if key_text not in SAFE_EXECUTION_FLAG_KEYS and any(pattern in compact for pattern in FORBIDDEN_KEY_PATTERNS):
                raise ValueError(f"forbidden secret-like key at {path}.{key_text}")
            if key_text in EXECUTION_FLAG_KEYS and bool(value):
                raise ValueError(f"forbidden execution flag {path}.{key_text}=true")
            assert_safe_payload(value, f"{path}.{key_text}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            assert_safe_payload(item, f"{path}[{index}]")

def safety_payload() -> dict[str, bool]:
    return dict(SAFETY_DEFAULTS)

def thresholds_from_env(env: Mapping[str, str] | None = None) -> PolicyThresholds:
    import os

    source = env or os.environ
    return PolicyThresholds(
        min_samples=safe_int(source.get("QG_ADAPTIVE_MIN_SAMPLES"), 5),
        active_min_samples=safe_int(source.get("QG_ADAPTIVE_ACTIVE_MIN_SAMPLES"), 7),
        min_win_rate=safe_float(source.get("QG_ADAPTIVE_MIN_WIN_RATE"), 0.52),
        pause_win_rate=safe_float(source.get("QG_ADAPTIVE_PAUSE_WIN_RATE"), 0.40),
        min_avg_score_r=safe_float(source.get("QG_ADAPTIVE_MIN_AVG_R"), 0.05),
        pause_avg_score_r=safe_float(source.get("QG_ADAPTIVE_PAUSE_AVG_R"), -0.25),
        max_consecutive_losses=safe_int(source.get("QG_ADAPTIVE_MAX_CONSECUTIVE_LOSSES"), 5),
        max_runtime_age_seconds=safe_int(source.get("QG_ADAPTIVE_MAX_RUNTIME_AGE_SECONDS"), 90),
        max_spread_multiplier=safe_float(source.get("QG_ADAPTIVE_MAX_SPREAD_MULTIPLIER"), 1.8),
        min_atr=safe_float(source.get("QG_ADAPTIVE_MIN_ATR"), 0.0),
        cooldown_seconds=safe_int(source.get("QG_ADAPTIVE_COOLDOWN_SECONDS"), 86400),
        max_plan_records=safe_int(source.get("QG_ADAPTIVE_MAX_PLAN_RECORDS"), 500),
    )

def dataclass_to_dict(value: Any) -> dict[str, Any]:
    data = asdict(value)
    assert_safe_payload(data)
    return data
