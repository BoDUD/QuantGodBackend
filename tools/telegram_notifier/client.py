"""Small Telegram Bot API client for configuration and chat-link queries.

Outbound messages intentionally do not use this client. All delivery transport
is owned by the canonical QuantGod Telegram Gateway.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any


class TelegramApiError(RuntimeError):
    """Raised when Telegram returns an API error or non-JSON response."""

Opener = Callable[[urllib.request.Request, int], Any]


def default_urlopen(request: urllib.request.Request, timeout_seconds: int) -> Any:
    context = None
    try:
        import certifi  # type: ignore

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    return urllib.request.urlopen(request, timeout=timeout_seconds, context=context)


def validate_message_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("Telegram message text must not be empty")
    if len(cleaned) > 4096:
        raise ValueError("Telegram message text must be 4096 characters or fewer")
    return cleaned


class TelegramClient:
    def __init__(self, *, token: str, api_base_url: str = "https://api.telegram.org", timeout_seconds: int = 15, opener: Opener | None = None):
        self.token = token.strip()
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.opener = opener or default_urlopen

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise TelegramApiError("Telegram bot token is not configured")
        encoded = urllib.parse.urlencode(params or {}, doseq=True).encode("utf-8")
        url = f"{self.api_base_url}/bot{self.token}/{method}"
        request = urllib.request.Request(url, data=encoded, headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}, method="POST")
        try:
            with self.opener(request, self.timeout_seconds) as response:  # type: ignore[misc]
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise TelegramApiError(self._error_message(method, raw, fallback=str(exc))) from exc
        except urllib.error.URLError as exc:
            raise TelegramApiError(f"{method} failed: {exc.reason}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TelegramApiError(f"{method} returned non-JSON response") from exc
        if not payload.get("ok"):
            raise TelegramApiError(self._error_message(method, raw, fallback=str(payload)))
        return payload

    @staticmethod
    def _error_message(method: str, raw: str, *, fallback: str) -> str:
        try:
            payload = json.loads(raw)
            description = payload.get("description") or payload.get("error")
            if description:
                return f"{method} failed: {description}"
        except json.JSONDecodeError:
            pass
        return f"{method} failed: {fallback}"

    def get_me(self) -> dict[str, Any]:
        return self.request("getMe")

    def get_webhook_info(self) -> dict[str, Any]:
        return self.request("getWebhookInfo")

    def delete_webhook(self, *, drop_pending_updates: bool = False) -> dict[str, Any]:
        return self.request("deleteWebhook", {"drop_pending_updates": "true" if drop_pending_updates else "false"})

    def get_updates(self, *, offset: int | None = None, timeout: int = 0, limit: int = 100, allowed_updates: Iterable[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"timeout": max(0, int(timeout)), "limit": max(1, min(int(limit), 100))}
        if offset is not None:
            params["offset"] = int(offset)
        if allowed_updates is not None:
            params["allowed_updates"] = json.dumps(list(allowed_updates), separators=(",", ":"))
        return self.request("getUpdates", params)

def extract_chat_candidates(updates: Iterable[dict[str, Any]], *, private_only: bool = True) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for update in updates:
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        chat_type = chat.get("type") or ""
        if chat_id is None:
            continue
        if private_only and chat_type != "private":
            continue
        candidates.append({
            "updateId": update.get("update_id"),
            "chatId": str(chat_id),
            "chatType": chat_type,
            "chatUsername": chat.get("username") or "",
            "chatTitle": chat.get("title") or chat.get("first_name") or "",
            "messageId": message.get("message_id"),
            "textPreview": str(message.get("text") or "")[:80],
        })
    return candidates
