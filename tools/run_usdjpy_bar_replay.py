#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict

from telegram_cli_truth import explicit_send_exit_code, normalize_cli_payload
from telegram_gateway_cli import dispatch_cli_text
from usdjpy_bar_replay.dataset_loader import sample_runtime
from usdjpy_bar_replay.replay_engine import build_bar_replay_report, build_entry_comparison, build_exit_comparison
from usdjpy_bar_replay.schema import FOCUS_SYMBOL, READ_ONLY_SAFETY
from usdjpy_bar_replay.telegram_text import bar_replay_to_chinese_text


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def emit(payload) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def send_telegram(runtime_dir: Path, text: str) -> Dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    return dispatch_cli_text(
        runtime_dir=runtime_dir,
        source="usdjpy_bar_replay",
        topic="USDJPY_BAR_REPLAY_REPORT",
        severity="INFO",
        text=text,
        repo_root=root,
    )


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env.usdjpy.local")
    parser = argparse.ArgumentParser(description="QuantGod P3-19 USDJPY causal bar replay simulator")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    parser.add_argument("--symbol", default=FOCUS_SYMBOL)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config")
    sample = sub.add_parser("sample")
    sample.add_argument("--overwrite", action="store_true")
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--write", action="store_true")
    entry = sub.add_parser("entry")
    entry.add_argument("--write", action="store_true")
    exit_cmd = sub.add_parser("exit")
    exit_cmd.add_argument("--write", action="store_true")
    text = sub.add_parser("telegram-text")
    text.add_argument("--refresh", action="store_true")
    text.add_argument("--write", action="store_true")
    text.add_argument("--send", action="store_true")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    if args.symbol.upper() not in {"USDJPY", "USDJPYC"}:
        return emit({"ok": False, "error": "P3-19 只允许 USDJPY/USDJPYc", "symbol": args.symbol})
    if args.command == "config":
        return emit({"ok": True, "focusSymbol": FOCUS_SYMBOL, "runtimeDir": str(runtime_dir), "safety": READ_ONLY_SAFETY})
    if args.command == "sample":
        return emit(sample_runtime(runtime_dir, overwrite=args.overwrite))
    if args.command in {"build", "status"}:
        return emit(build_bar_replay_report(runtime_dir, write=args.write))
    if args.command == "entry":
        return emit(build_entry_comparison(runtime_dir, write=args.write))
    if args.command == "exit":
        return emit(build_exit_comparison(runtime_dir, write=args.write))
    if args.command == "telegram-text":
        payload = build_bar_replay_report(runtime_dir, write=args.write or args.refresh)
        content = bar_replay_to_chinese_text(payload)
        result = {"ok": True, "text": content, "report": payload}
        if args.send:
            result["telegramGateway"] = send_telegram(runtime_dir, content)
        result = normalize_cli_payload(result, send_requested=args.send)
        emit(result)
        return explicit_send_exit_code(args.send, result.get("telegramGateway"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
