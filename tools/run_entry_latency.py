#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from entry_latency.report import FOCUS_SYMBOL, build_report, load_or_build, report_path, safety_payload
from entry_latency.telegram_text import build_telegram_text


def emit(payload: object) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def runtime_dir(value: str) -> Path:
    return Path(value).expanduser().resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantGod USDJPY entry latency attribution")
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--symbol", default=FOCUS_SYMBOL)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    text = sub.add_parser("telegram-text")
    text.add_argument("--refresh", action="store_true")
    text.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    runtime = runtime_dir(args.runtime_dir)
    if args.command == "status":
        path = report_path(runtime)
        payload = load_or_build(runtime, symbol=args.symbol)
        return emit({
            "schema": "quantgod.entry_latency.status.v1",
            "runtimeDir": str(runtime),
            "reportExists": path.exists(),
            "reportPath": str(path),
            "summary": payload.get("summary", {}),
            "safety": safety_payload(),
        })
    if args.command == "build":
        return emit(build_report(runtime, symbol=args.symbol, write=args.write))
    if args.command == "telegram-text":
        payload = build_report(runtime, symbol=args.symbol, write=args.write or args.refresh) if args.refresh else load_or_build(runtime, symbol=args.symbol)
        print(build_telegram_text(payload))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
