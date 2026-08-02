from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from telegram_notifier.config import parse_env_file
    from usdjpy_evidence_os.telegram_gateway import dispatch_text
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_notifier.config import parse_env_file
    from tools.usdjpy_evidence_os.telegram_gateway import dispatch_text


_ALLOWED_LOCAL_KEYS = {
    "QG_TELEGRAM_BOT_TOKEN",
    "QG_TELEGRAM_CHAT_ID",
    "QG_TELEGRAM_PUSH_ALLOWED",
    "QG_TELEGRAM_COMMANDS_ALLOWED",
    "QG_TELEGRAM_API_BASE_URL",
    "QG_TELEGRAM_TIMEOUT_SECONDS",
}


def load_local_telegram_env(repo_root: Path | str | None = None) -> None:
    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
    for key, value in parse_env_file(root / ".env.telegram.local").items():
        if key in _ALLOWED_LOCAL_KEYS and key not in os.environ:
            os.environ[key] = value


def dispatch_cli_text(
    *,
    runtime_dir: Path | str,
    source: str,
    topic: str,
    severity: str,
    text: str,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Send an explicitly requested CLI push through the canonical Gateway."""
    load_local_telegram_env(repo_root)
    result = dispatch_text(
        Path(runtime_dir),
        source,
        topic,
        severity,
        text,
        send=True,
    )
    normalized = dict(result) if isinstance(result, dict) else {"gatewayResult": result}
    delivery = normalized.get("delivery") if isinstance(normalized.get("delivery"), dict) else {}
    message_id = delivery.get("messageId")
    delivery_ok = delivery.get("ok") is True and message_id not in (None, "")
    normalized.update(
        {
            "sendRequested": True,
            "sent": delivery_ok,
            "deliveryOk": delivery_ok,
        }
    )
    return normalized
