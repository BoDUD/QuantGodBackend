#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from telegram_cli_truth import explicit_send_exit_code, normalize_cli_payload
from telegram_gateway_cli import dispatch_cli_text
from usdjpy_live_loop.runner import build_live_loop
from usdjpy_live_loop.telegram_text import live_loop_to_chinese_text


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def emit(payload: Any) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def send_telegram(runtime_dir: Path, text: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    return dispatch_cli_text(
        runtime_dir=runtime_dir,
        source="usdjpy_live_loop",
        topic="USDJPY_LIVE_LOOP_REPORT",
        severity="INFO",
        text=text,
        repo_root=root,
    )


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    load_env(repo_root / ".env.usdjpy.local")
    load_env(repo_root / ".env.auto.local")
    parser = argparse.ArgumentParser(description="QuantGod USDJPY live loop evidence runner")
    parser.add_argument("--repo-root", default=str(repo_root))
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(repo_root / "runtime")))
    parser.add_argument("--min-samples", type=int, default=int(os.environ.get("QG_USDJPY_MIN_SAMPLES", "5")))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "once", "build"):
        item = sub.add_parser(name)
        item.add_argument("--write", action="store_true")
    text = sub.add_parser("telegram-text")
    text.add_argument("--refresh", action="store_true")
    text.add_argument("--write", action="store_true")
    text.add_argument("--send", action="store_true")
    loop = sub.add_parser("loop")
    loop.add_argument("--interval-seconds", type=int, default=300)
    loop.add_argument("--send", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).expanduser().resolve()
    runtime = Path(args.runtime_dir).expanduser()
    if not runtime.is_absolute():
        runtime = repo / runtime

    if args.command in {"status", "once", "build"}:
        payload = build_live_loop(repo, runtime, write=getattr(args, "write", False) or args.command in {"once", "build"}, min_samples=args.min_samples)
        return emit(payload)
    if args.command == "telegram-text":
        payload = build_live_loop(repo, runtime, write=args.write or args.refresh, min_samples=args.min_samples)
        content = live_loop_to_chinese_text(payload)
        result = {"ok": True, "text": content, "status": payload}
        if args.send:
            result["telegramGateway"] = send_telegram(runtime, content)
        result = normalize_cli_payload(result, send_requested=args.send)
        emit(result)
        return explicit_send_exit_code(args.send, result.get("telegramGateway"))
    if args.command == "loop":
        while True:
            payload = build_live_loop(repo, runtime, write=True, min_samples=args.min_samples)
            content = live_loop_to_chinese_text(payload)
            result = {"ok": True, "generatedAt": payload.get("generatedAt"), "state": payload.get("state"), "textPreview": content[:500]}
            if args.send:
                result["telegramGateway"] = send_telegram(runtime, content)
            result = normalize_cli_payload(result, send_requested=args.send)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if explicit_send_exit_code(args.send, result.get("telegramGateway")):
                return 2
            time.sleep(max(30, args.interval_seconds))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
