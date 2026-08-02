#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from notify.config import NotifyConfig
from notify.notify_service import (
    load_history,
    run_async,
    scan_once,
    send_ai_analysis_summary,
    send_daily_digest,
    send_event,
)
from telegram_cli_truth import explicit_send_exit_code, normalize_delivery


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def emit_delivery(payload: dict, *, dry_run: bool) -> int:
    send_requested = not dry_run
    normalized = normalize_delivery(payload, send_requested=send_requested)
    emit(normalized)
    return explicit_send_exit_code(send_requested, normalized)


def parse_json_arg(value: str) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("JSON payload must be an object")
    return parsed


def add_safe_delivery_flags(command: argparse.ArgumentParser) -> None:
    delivery = command.add_mutually_exclusive_group()
    delivery.add_argument("--dry-run", dest="dry_run", action="store_true", help="preview only (default)")
    delivery.add_argument("--send", dest="dry_run", action="store_false", help="explicitly request Telegram delivery")
    command.set_defaults(dry_run=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantGod Telegram notification CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("config", help="print redacted notification configuration")

    hist = sub.add_parser("history", help="print notification history")
    hist.add_argument("--limit", type=int, default=50)

    test = sub.add_parser("test", help="preview a Telegram test message")
    test.add_argument("--message", default="QuantGod Telegram notification test")
    test.add_argument("--event-type", default="TEST")
    add_safe_delivery_flags(test)

    send = sub.add_parser("send-event", help="preview a formatted event")
    send.add_argument("--event-type", required=True)
    send.add_argument("--data-json", type=parse_json_arg, default={})
    add_safe_delivery_flags(send)

    ai = sub.add_parser("ai-summary", help="preview an AI analysis summary from a report JSON")
    ai.add_argument("--report-file", required=True)
    add_safe_delivery_flags(ai)

    digest = sub.add_parser("daily-digest", help="preview a daily digest from runtime ledgers")
    add_safe_delivery_flags(digest)

    scan = sub.add_parser("scan-once", help="best-effort one-shot runtime scan (preview by default)")
    add_safe_delivery_flags(scan)

    args = parser.parse_args(argv)
    config = NotifyConfig.from_env()

    if args.cmd == "config":
        emit(config.public_dict())
        return 0
    if args.cmd == "history":
        emit(load_history(config, limit=args.limit))
        return 0
    if args.cmd == "test":
        payload = run_async(send_event(args.event_type, {"message": args.message}, config=config, dry_run=args.dry_run))
        return emit_delivery(payload, dry_run=args.dry_run)
    if args.cmd == "send-event":
        payload = run_async(send_event(args.event_type, args.data_json, config=config, dry_run=args.dry_run))
        return emit_delivery(payload, dry_run=args.dry_run)
    if args.cmd == "ai-summary":
        try:
            report = json.loads(Path(args.report_file).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            emit({"ok": False, "error": f"report_read_failed: {exc}"})
            return 2
        payload = run_async(send_ai_analysis_summary(report, config=config, dry_run=args.dry_run))
        return emit_delivery(payload, dry_run=args.dry_run)
    if args.cmd == "daily-digest":
        payload = run_async(send_daily_digest(config=config, dry_run=args.dry_run))
        return emit_delivery(payload, dry_run=args.dry_run)
    if args.cmd == "scan-once":
        payload = run_async(scan_once(config=config, dry_run=args.dry_run))
        return emit_delivery(payload, dry_run=args.dry_run)
    emit({"ok": False, "error": "unknown_command"})
    return 2


if __name__ == "__main__":
    sys.exit(main())
