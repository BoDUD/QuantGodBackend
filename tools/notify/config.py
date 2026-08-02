from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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


FORBIDDEN_NOTIFY_TRUTHY_ENV = FORBIDDEN_TELEGRAM_TRUTHY_ENV


def _bool_env(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _bool_value(raw: str | None, default: bool = True) -> bool:
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on", "allow", "allowed"}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _local_telegram_env_values() -> dict[str, str]:
    raw = os.getenv("QG_TELEGRAM_ENV_FILE") or ".env.telegram.local"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return _read_env_file(path)


def _env_or_file(keys: list[str], file_values: dict[str, str], default: str = "") -> str:
    for key in keys:
        raw = os.getenv(key)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    for key in keys:
        raw = file_values.get(key)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return default


def notify_safety_violations(file_values: dict[str, str] | None = None) -> tuple[str, ...]:
    if file_values is None:
        return tuple(unsafe_telegram_environment_keys())
    values = file_values
    return tuple(
        key
        for key in FORBIDDEN_NOTIFY_TRUTHY_ENV
        if _bool_value(_env_or_file([key], values, "0"), False)
    )


def _redact(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]}"


def _default_runtime_dir() -> Path:
    raw = os.getenv("QG_RUNTIME_DIR") or os.getenv("QG_MT5_FILES_DIR") or os.getenv("QG_HFM_FILES")
    if raw and os.name != "nt" and ":\\" in str(raw):
        return Path.cwd() / "runtime" / "notify"
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / "runtime" / "notify"


@dataclass(frozen=True)
class NotifyConfig:
    bot_token: str
    chat_id: str
    enabled: bool
    runtime_dir: Path
    history_path: Path
    request_timeout: float
    max_retries: int
    notify_trade_signal: bool
    notify_risk_alert: bool
    notify_ai_summary: bool
    notify_daily_digest: bool
    notify_governance: bool
    telegram_push_allowed: bool
    safety_violations: tuple[str, ...]

    @classmethod
    def from_env(cls) -> NotifyConfig:
        local_telegram_env = _local_telegram_env_values()
        runtime_dir = _default_runtime_dir()
        history_path = Path(os.getenv("QG_NOTIFY_HISTORY_PATH", str(runtime_dir / "QuantGod_NotifyHistory.json"))).expanduser()
        bot_token = _env_or_file(["TELEGRAM_BOT_TOKEN", "QG_TELEGRAM_BOT_TOKEN"], local_telegram_env)
        chat_id = _env_or_file(["TELEGRAM_CHAT_ID", "QG_TELEGRAM_CHAT_ID"], local_telegram_env)
        return cls(
            bot_token=bot_token,
            chat_id=chat_id,
            enabled=_bool_value(_env_or_file(["QG_NOTIFY_ENABLED"], local_telegram_env, "true"), True),
            runtime_dir=runtime_dir,
            history_path=history_path,
            request_timeout=float(os.getenv("QG_NOTIFY_TIMEOUT", "10") or 10),
            max_retries=max(0, int(os.getenv("QG_NOTIFY_MAX_RETRIES", "2") or 2)),
            notify_trade_signal=_bool_env("NOTIFY_TRADE_SIGNAL", True),
            notify_risk_alert=_bool_env("NOTIFY_RISK_ALERT", True),
            notify_ai_summary=_bool_env("NOTIFY_AI_SUMMARY", True),
            notify_daily_digest=_bool_env("NOTIFY_DAILY_DIGEST", True),
            notify_governance=_bool_env("NOTIFY_GOVERNANCE", False),
            telegram_push_allowed=_bool_value(_env_or_file(["QG_TELEGRAM_PUSH_ALLOWED"], local_telegram_env, "0"), False),
            safety_violations=notify_safety_violations(),
        )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    @property
    def telegram_environment_safe(self) -> bool:
        return not self.safety_violations

    @property
    def commands_env_requested(self) -> bool:
        return "QG_TELEGRAM_COMMANDS_ALLOWED" in self.safety_violations

    def event_enabled(self, event_type: str) -> bool:
        event = str(event_type or "").upper()
        if event in {"TEST"}:
            return True
        if event in {"TRADE_OPEN", "TRADE_CLOSE"}:
            return self.notify_trade_signal
        if event in {"KILL_SWITCH", "NEWS_BLOCK", "CONSECUTIVE_LOSS"}:
            return self.notify_risk_alert
        if event == "AI_ANALYSIS":
            return self.notify_ai_summary
        if event == "DAILY_DIGEST":
            return self.notify_daily_digest
        if event == "GOVERNANCE":
            return self.notify_governance
        return True

    def public_dict(self) -> dict:
        return {
            "ok": True,
            "mode": "QUANTGOD_NOTIFY_CONFIG_V1",
            "enabled": self.enabled,
            "telegramConfigured": self.telegram_configured,
            "telegramPushAllowed": self.telegram_push_allowed,
            "telegramEnvironmentSafe": self.telegram_environment_safe,
            "commandsEnvRequested": self.commands_env_requested,
            "blockedUnsafeEnvironmentKeys": list(self.safety_violations),
            "tokenConfigured": bool(self.bot_token),
            "chatConfigured": bool(self.chat_id),
            "chatIdRedacted": _redact(self.chat_id, keep=3),
            "runtimeDir": str(self.runtime_dir),
            "historyPath": str(self.history_path),
            "requestTimeout": self.request_timeout,
            "maxRetries": self.max_retries,
            "events": {
                "tradeSignal": self.notify_trade_signal,
                "riskAlert": self.notify_risk_alert,
                "aiSummary": self.notify_ai_summary,
                "dailyDigest": self.notify_daily_digest,
                "governance": self.notify_governance,
            },
            "safety": {
                "pushOnly": True,
                "notificationPushOnly": True,
                "commandsAllowed": False,
                "telegramCommandsAccepted": False,
                "commandsEnvRequested": self.commands_env_requested,
                "gatewayReceivesCommands": False,
                "telegramCommandExecutionAllowed": False,
                "unsafeEnvironmentBlocked": not self.telegram_environment_safe,
                "orderSendAllowed": False,
                "closeAllowed": False,
                "cancelAllowed": False,
                "livePresetMutationAllowed": False,
                "writesMt5OrderRequest": False,
                "externalMarketRealMoneyAllowed": False,
            },
        }
