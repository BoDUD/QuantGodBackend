from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import notify_safety_violations
from .event_formatter import format_event

try:
    from telegram_gateway_cli import dispatch_cli_text
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_gateway_cli import dispatch_cli_text

TELEGRAM_MAX_CHARS = 4096
TELEGRAM_SAFETY_FOOTER = "边界：永久 Shadow｜无执行通道｜Telegram 只推送、不接收命令。"
TELEGRAM_TRUNCATION_NOTICE = "…（内容已安全裁剪，完整详情见本地面板）"


def prepare_telegram_message(text: Any) -> str:
    """Bound outgoing text while keeping the permanent Shadow footer last."""
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    body = "\n".join(
        line for line in normalized.splitlines() if line.strip() != TELEGRAM_SAFETY_FOOTER
    ).rstrip()
    max_body_chars = TELEGRAM_MAX_CHARS - len(TELEGRAM_SAFETY_FOOTER) - 1
    if len(body) > max_body_chars:
        notice = f"\n{TELEGRAM_TRUNCATION_NOTICE}"
        prefix_budget = max(0, max_body_chars - len(notice))
        prefix = body[:prefix_budget].rstrip()
        body = f"{prefix}{notice}" if prefix else TELEGRAM_TRUNCATION_NOTICE[:max_body_chars]
    return f"{body}\n{TELEGRAM_SAFETY_FOOTER}" if body else TELEGRAM_SAFETY_FOOTER


@dataclass
class TelegramSendResult:
    ok: bool
    error: str = ""
    status_code: int | None = None


class TelegramBot:
    def __init__(self, token: str, chat_id: str, timeout: float = 10, max_retries: int = 2):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.last_error = ""

    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        result = await self.send_message_result(text, parse_mode=parse_mode, disable_notification=disable_notification)
        return result.ok

    async def send_message_result(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> TelegramSendResult:
        violations = notify_safety_violations()
        if violations:
            self.last_error = "unsafe_telegram_environment:" + ",".join(violations)
            return TelegramSendResult(ok=False, error=self.last_error)
        if not self.token or not self.chat_id:
            self.last_error = "telegram_not_configured"
            return TelegramSendResult(ok=False, error=self.last_error)
        payload = {
            "chat_id": self.chat_id,
            "text": prepare_telegram_message(text),
            "parse_mode": parse_mode,
            "disable_notification": bool(disable_notification),
            "disable_web_page_preview": True,
        }
        return await asyncio.to_thread(self._post_with_retries, payload)

    async def send_alert(self, event_type: str, data: dict[str, Any]) -> bool:
        return await self.send_message(format_event(event_type, data))

    def _post_with_retries(self, payload: dict[str, Any]) -> TelegramSendResult:
        runtime_dir = Path(
            os.environ.get("QG_RUNTIME_DIR")
            or os.environ.get("QG_MT5_FILES_DIR")
            or Path.cwd() / "runtime"
        )
        gateway = dispatch_cli_text(
            runtime_dir=runtime_dir,
            source="notify_telegram_bot_adapter",
            topic="LEGACY_NOTIFY_ADAPTER",
            severity="INFO",
            text=str(payload.get("text") or ""),
        )
        delivery = gateway.get("delivery") if isinstance(gateway.get("delivery"), dict) else {}
        confirmed = gateway.get("sent") is True and gateway.get("deliveryOk") is True
        error = "" if confirmed else str(delivery.get("reason") or "telegram_delivery_not_confirmed")
        self.last_error = error
        return TelegramSendResult(ok=confirmed, error=error)
