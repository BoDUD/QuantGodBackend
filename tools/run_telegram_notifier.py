#!/usr/bin/env python3
"""QuantGod P3-2 Telegram push-only CLI.

This tool links a local Telegram bot chat and sends push-only notifications.
It does not run a webhook receiver, parse trading commands, or mutate trading state.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import webbrowser
from pathlib import Path
from typing import Any

from telegram_digest import build_digest
from telegram_gateway_cli import dispatch_cli_text
from telegram_notifier.client import TelegramApiError, TelegramClient, extract_chat_candidates, validate_message_text
from telegram_notifier.config import TelegramConfig, load_config, update_env_file
from telegram_notifier.records import record_notification
from telegram_notifier.safety import assert_telegram_safety, require_token, safety_payload

BOTFATHER_URL = "https://t.me/BotFather"


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def build_client(config: TelegramConfig) -> TelegramClient:
    return TelegramClient(token=config.bot_token, api_base_url=config.api_base_url, timeout_seconds=config.timeout_seconds)


def bot_url_from_get_me(result: dict[str, Any]) -> str:
    username = ((result.get("result") or {}).get("username") or "").strip()
    return f"https://t.me/{username}" if username else ""


def command_status(args: argparse.Namespace) -> int:
    config = load_config(repo_root=args.repo_root, env_file=args.env_file)
    try:
        assert_telegram_safety(config)
        ok = True
        error = ""
    except Exception as exc:
        ok = False
        error = str(exc)
    emit({"ok": ok, "config": config.as_safe_dict(), "safety": safety_payload(config), "error": error})
    return 0 if ok else 1


def command_open_botfather(args: argparse.Namespace) -> int:
    opened = False if args.no_open else bool(webbrowser.open(BOTFATHER_URL))
    emit({"ok": True, "opened": opened, "url": BOTFATHER_URL, "safety": safety_payload()})
    return 0


def command_get_me(args: argparse.Namespace) -> int:
    config = load_config(repo_root=args.repo_root, env_file=args.env_file)
    assert_telegram_safety(config)
    require_token(config)
    payload = build_client(config).get_me()
    result = payload.get("result") or {}
    emit({"ok": True, "bot": {"id": result.get("id"), "isBot": result.get("is_bot"), "username": result.get("username"), "firstName": result.get("first_name"), "canJoinGroups": result.get("can_join_groups"), "canReadAllGroupMessages": result.get("can_read_all_group_messages")}, "botUrl": bot_url_from_get_me(payload), "safety": safety_payload(config)})
    return 0


def command_webhook_info(args: argparse.Namespace) -> int:
    config = load_config(repo_root=args.repo_root, env_file=args.env_file)
    assert_telegram_safety(config)
    require_token(config)
    payload = build_client(config).get_webhook_info()
    emit({"ok": True, "webhook": payload.get("result") or {}, "safety": safety_payload(config)})
    return 0


def command_clear_webhook(args: argparse.Namespace) -> int:
    config = load_config(repo_root=args.repo_root, env_file=args.env_file)
    assert_telegram_safety(config)
    require_token(config)
    payload = build_client(config).delete_webhook(drop_pending_updates=args.drop_pending_updates)
    emit({"ok": True, "result": payload.get("result"), "dropPendingUpdates": args.drop_pending_updates, "safety": safety_payload(config)})
    return 0


def command_link(args: argparse.Namespace) -> int:
    config = load_config(repo_root=args.repo_root, env_file=args.env_file)
    assert_telegram_safety(config)
    require_token(config)
    client = build_client(config)
    if args.delete_webhook:
        client.delete_webhook(drop_pending_updates=False)
    me = client.get_me()
    bot_url = bot_url_from_get_me(me)
    opened = bool(webbrowser.open(bot_url)) if bot_url and args.open else False
    deadline = time.monotonic() + max(0, args.poll_seconds)
    offset: int | None = None
    selected: dict[str, Any] | None = None
    updates_seen = 0
    private_only = not args.allow_group
    while True:
        remaining = max(0, int(deadline - time.monotonic()))
        timeout = min(10, remaining) if remaining > 0 else 0
        payload = client.get_updates(offset=offset, timeout=timeout, limit=100, allowed_updates=["message", "channel_post"])
        updates = payload.get("result") or []
        updates_seen += len(updates)
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = max(offset or 0, update_id + 1)
        candidates = extract_chat_candidates(updates, private_only=private_only)
        if candidates:
            selected = candidates[-1]
            break
        if time.monotonic() >= deadline:
            break
    written = False
    if selected and args.write_env:
        updates: dict[str, str] = {"QG_TELEGRAM_CHAT_ID": str(selected["chatId"]), "QG_TELEGRAM_COMMANDS_ALLOWED": "0"}
        if args.enable_push:
            updates["QG_TELEGRAM_PUSH_ALLOWED"] = "1"
        update_env_file(config.env_file, updates)
        written = True
    emit({"ok": bool(selected), "botUrl": bot_url, "opened": opened, "updatesSeen": updates_seen, "selectedChat": selected, "writeEnv": written, "envFile": str(config.env_file), "hint": "Send /start to the bot chat and rerun link if selectedChat is null.", "safety": safety_payload(config)})
    return 0 if selected else 1


def _send_message(args: argparse.Namespace, *, event_type: str, message: str) -> int:
    config = load_config(repo_root=args.repo_root, env_file=args.env_file)
    assert_telegram_safety(config)
    message = validate_message_text(message)
    if not args.send:
        record = {"ok": True, "recorded": False, "dryRun": True}
        if not args.no_record:
            record = record_notification(config, event_type=event_type, status="dry_run", payload={"messagePreview": message[:160]})
        emit(
            {
                "ok": True,
                "status": "preview",
                "dryRun": True,
                "sendRequested": False,
                "sent": False,
                "deliveryOk": False,
                "messagePreview": message,
                "record": record,
                "safety": safety_payload(config),
            }
        )
        return 0
    gateway = dispatch_cli_text(
        runtime_dir=Path(os.environ.get("QG_RUNTIME_DIR") or config.repo_root / "runtime"),
        source="telegram_notifier_cli",
        topic=event_type,
        severity="INFO",
        text=message,
        repo_root=config.repo_root,
    )
    nested_delivery = gateway.get("delivery") if isinstance(gateway.get("delivery"), dict) else {}
    confirmed = gateway.get("sent") is True and gateway.get("deliveryOk") is True
    status = "sent" if confirmed else "send_suppressed" if nested_delivery.get("skipped") is True else "send_failed"
    record = {"ok": True, "recorded": False}
    if not args.no_record:
        record = record_notification(
            config,
            event_type=event_type,
            status="sent" if confirmed else status,
            payload={
                "telegramMessageId": nested_delivery.get("messageId") if confirmed else None,
                "messagePreview": message[:160],
                "reason": nested_delivery.get("reason"),
            },
        )
    gateway.update(
        {
            "ok": confirmed,
            "status": status,
            "sent": confirmed,
            "deliveryOk": confirmed,
            "telegramMessageId": nested_delivery.get("messageId") if confirmed else None,
            "record": record,
            "safety": safety_payload(config),
        }
    )
    emit(gateway)
    return 0 if confirmed else 2


def command_test(args: argparse.Namespace) -> int:
    message = args.message or build_digest(
        title="Telegram 预览测试",
        level="info",
        conclusion="本地通知格式检查完成；默认未请求外发。",
        metrics=["模式 Shadow", "命令接收 关闭"],
        reasons=["该消息仅用于检查中文摘要可读性。"],
        next_action="确认预览无误后，只有显式使用 --send 才会请求投递。",
    )
    return _send_message(args, event_type="TELEGRAM_PUSH_TEST", message=message)


def command_notify(args: argparse.Namespace) -> int:
    severity = args.severity.strip().lower()
    title = args.title.strip()
    body = args.body.strip()
    message = build_digest(
        title=title,
        level="danger" if severity == "critical" else severity,
        conclusion=body or "本地通知已生成，等待操作员复核。",
        metrics=["模式 Shadow"],
        reasons=["由本地通知 CLI 生成。"],
        next_action="在本地面板核对完整上下文。",
    )
    return _send_message(args, event_type="TELEGRAM_NOTIFICATION", message=message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuantGod P3-2 Telegram push-only notifier")
    parser.add_argument("--repo-root", type=Path, default=None, help="Path to QuantGodBackend repo root")
    parser.add_argument("--env-file", type=Path, default=None, help="Path to local Telegram env file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show safe local Telegram config status").set_defaults(func=command_status)
    open_botfather = sub.add_parser("open-botfather", help="Open @BotFather in Telegram/browser")
    open_botfather.add_argument("--no-open", action="store_true", help="Only print the BotFather URL")
    open_botfather.set_defaults(func=command_open_botfather)
    sub.add_parser("get-me", help="Call Bot API getMe to validate token").set_defaults(func=command_get_me)
    sub.add_parser("webhook-info", help="Show current Bot API webhook info").set_defaults(func=command_webhook_info)
    clear_webhook = sub.add_parser("clear-webhook", help="Delete an existing Telegram webhook so local getUpdates linking can work")
    clear_webhook.add_argument("--drop-pending-updates", action="store_true", help="Ask Telegram to drop pending updates")
    clear_webhook.set_defaults(func=command_clear_webhook)
    link = sub.add_parser("link", help="Poll getUpdates to discover chat_id after you send /start to the bot")
    link.add_argument("--open", action="store_true", help="Open the bot chat URL from getMe")
    link.add_argument("--poll-seconds", type=int, default=45, help="Seconds to poll for a /start or other message")
    link.add_argument("--allow-group", action="store_true", help="Allow linking a group/channel chat instead of private chat only")
    link.add_argument("--write-env", action="store_true", help="Write QG_TELEGRAM_CHAT_ID to .env.telegram.local")
    link.add_argument("--enable-push", action="store_true", help="When used with --write-env, set QG_TELEGRAM_PUSH_ALLOWED=1")
    link.add_argument("--delete-webhook", action="store_true", help="Delete existing webhook before polling getUpdates")
    link.set_defaults(func=command_link)
    def add_send_args(p: argparse.ArgumentParser) -> None:
        delivery = p.add_mutually_exclusive_group()
        delivery.add_argument("--send", action="store_true", help="Explicitly request Telegram delivery")
        delivery.add_argument("--dry-run", dest="send", action="store_false", help="Preview only (default)")
        p.set_defaults(send=False)
        p.add_argument("--disable-notification", action="store_true", help="Send silently")
        p.add_argument("--no-record", action="store_true", help="Do not write notification evidence to SQLite")
    test = sub.add_parser("test", help="Send a push-only test message")
    test.add_argument("--message", default="", help="Optional custom test message")
    add_send_args(test)
    test.set_defaults(func=command_test)
    notify = sub.add_parser("notify", help="Send a push-only advisory notification")
    notify.add_argument("--severity", default="info", choices=["info", "warning", "critical"], help="Notification severity label")
    notify.add_argument("--title", required=True, help="Notification title")
    notify.add_argument("--body", default="", help="Notification body")
    add_send_args(notify)
    notify.set_defaults(func=command_notify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, TelegramApiError) as exc:
        config = load_config(repo_root=getattr(args, "repo_root", None), env_file=getattr(args, "env_file", None))
        emit({"ok": False, "error": str(exc), "safety": safety_payload(config)})
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
