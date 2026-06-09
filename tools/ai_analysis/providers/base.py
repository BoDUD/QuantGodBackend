from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping


class AIProviderError(RuntimeError):
    """Raised when an AI provider cannot produce a usable response."""


@dataclass(frozen=True)
class AIProviderConfig:
    enabled: bool = False
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    timeout_seconds: int = 45
    max_tokens: int = 1800
    temperature: float = 0.25
    require_json: bool = True
    daily_call_limit: int = 50
    daily_budget_usd: float = 2.0
    env_file: str = ".env.ai.local"
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        if self.provider == "mock":
            return True
        return bool(self.api_key.strip())

    def redacted(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_key"] = redact_secret(self.api_key)
        if data.get("extra_headers"):
            data["extra_headers"] = {k: redact_secret(v) for k, v in self.extra_headers.items()}
        data["configured"] = self.configured
        return data


@dataclass(frozen=True)
class AIProviderResponse:
    ok: bool
    provider: str
    model: str
    status: str
    parsed: dict[str, Any] | None = None
    content: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "parsed": self.parsed if isinstance(self.parsed, dict) else None,
            "content": self.content,
            "usage": self.usage,
            "error": self.error,
            "safety": provider_safety_payload(),
        }


def truthy(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def falsy(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"0", "false", "no", "n", "off", "disabled"}


def read_env_file(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    values: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def redact_secret(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return f"{text[:3]}***{text[-4:]}"


SECRET_MARKERS = ("api_key", "apikey", "token", "secret", "authorization", "bearer", "private_key", "password")


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in SECRET_MARKERS):
            redacted[str(key)] = redact_secret(str(value or ""))
        elif isinstance(value, Mapping):
            redacted[str(key)] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[str(key)] = [redact_mapping(item) if isinstance(item, Mapping) else item for item in value]
        else:
            redacted[str(key)] = value
    return redacted


def parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    first = raw.find("{")
    last = raw.rfind("}")
    if first >= 0 and last > first:
        raw = raw[first : last + 1]
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise AIProviderError("AI provider JSON response must be an object")
    return parsed


def provider_safety_payload() -> dict[str, Any]:
    return {
        "localOnly": True,
        "advisoryOnly": True,
        "researchOnly": True,
        "readOnlyDataPlane": True,
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
        "walletIntegrationAllowed": False,
        "externalMarketOrderAllowed": False,
    }


FORBIDDEN_TRUTHY_ENV = {
    "QG_ORDER_SEND_ALLOWED": "orderSendAllowed",
    "QG_CLOSE_ALLOWED": "closeAllowed",
    "QG_CANCEL_ALLOWED": "cancelAllowed",
    "QG_CREDENTIAL_STORAGE_ALLOWED": "credentialStorageAllowed",
    "QG_LIVE_PRESET_MUTATION_ALLOWED": "livePresetMutationAllowed",
    "QG_CAN_OVERRIDE_KILL_SWITCH": "canOverrideKillSwitch",
    "QG_TELEGRAM_COMMANDS_ALLOWED": "telegramCommandExecutionAllowed",
    "QG_TELEGRAM_WEBHOOK_RECEIVER_ALLOWED": "telegramWebhookReceiverAllowed",
    "QG_WEBHOOK_RECEIVER_ALLOWED": "webhookReceiverAllowed",
    "QG_EMAIL_DELIVERY_ALLOWED": "emailDeliveryAllowed",
    "QG_EXTERNAL_MARKET_ORDER_ALLOWED": "externalMarketOrderAllowed",
    "QG_WALLET_INTEGRATION_ALLOWED": "walletIntegrationAllowed",
}


def assert_ai_provider_safety(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(environ or {})
    violations: list[str] = []
    for key, flag in FORBIDDEN_TRUTHY_ENV.items():
        if truthy(env.get(key), False):
            violations.append(f"{key} would enable {flag}")
    if violations:
        raise AIProviderError("AI provider safety violation: " + "; ".join(violations))
    return provider_safety_payload()
