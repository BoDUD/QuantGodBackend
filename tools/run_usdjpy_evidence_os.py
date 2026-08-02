#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from usdjpy_evidence_os.case_memory import build_case_memory
from usdjpy_evidence_os.execution_feedback import build_execution_feedback
from usdjpy_evidence_os.parity import build_parity_report
from usdjpy_evidence_os.report import build_evidence_os, status
from usdjpy_evidence_os.telegram_gateway import build_notification_event, dispatch_event
from usdjpy_evidence_os.telegram_text import evidence_os_to_chinese_text
from telegram_cli_truth import explicit_send_exit_code, normalize_cli_payload


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def emit(payload) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env.usdjpy.local")
    load_env(root / ".env.telegram.local")
    parser = argparse.ArgumentParser(description="QuantGod USDJPY evidence OS audit runner")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    once = sub.add_parser("once")
    once.add_argument("--write", action="store_true")
    once.add_argument("--send", action="store_true")
    sub.add_parser("parity")
    sub.add_parser("execution-feedback")
    sub.add_parser("case-memory")
    text = sub.add_parser("telegram-text")
    text.add_argument("--refresh", action="store_true")
    text.add_argument("--send", action="store_true")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir)

    if args.command == "status":
        return emit(status(runtime_dir))
    if args.command == "once":
        payload = build_evidence_os(runtime_dir, write=True if args.write else True, send=args.send)
        payload = normalize_cli_payload(payload, send_requested=args.send)
        emit(payload)
        return explicit_send_exit_code(args.send, payload.get("telegramGateway"))
    if args.command == "parity":
        return emit(build_parity_report(runtime_dir, write=True))
    if args.command == "execution-feedback":
        return emit(build_execution_feedback(runtime_dir, write=True))
    if args.command == "case-memory":
        return emit(build_case_memory(runtime_dir, write=True))
    if args.command == "telegram-text":
        report = build_evidence_os(runtime_dir, write=True) if args.refresh else status(runtime_dir)
        text_content = evidence_os_to_chinese_text(report)
        payload = {"ok": True, "text": text_content, "report": report}
        if args.send:
            event = build_notification_event("usdjpy_evidence_os", "USDJPY_EVIDENCE_OS_REPORT", "INFO", text_content)
            payload["telegramGateway"] = dispatch_event(runtime_dir, event, send=True)
        payload = normalize_cli_payload(payload, send_requested=args.send)
        emit(payload)
        return explicit_send_exit_code(args.send, payload.get("telegramGateway"))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
