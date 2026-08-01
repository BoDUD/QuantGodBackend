#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from tools.profit_target_tracker.builder import build_profit_target_tracker, read_profit_target_tracker
    from tools.profit_target_tracker.schema import report_path
except ModuleNotFoundError:  # pragma: no cover
    from profit_target_tracker.builder import build_profit_target_tracker, read_profit_target_tracker
    from profit_target_tracker.schema import report_path


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantGod read-only profit target tracker")
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--mt5-runtime-dir", default="", help="optional secondary MT5 forex runtime")
    parser.add_argument("--report-runtime-dir", default="")
    parser.add_argument("--target-usd", type=float, default=50.0)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    secondary_runtime_dir = Path(args.mt5_runtime_dir).expanduser().resolve() if args.mt5_runtime_dir else None
    report_runtime_dir = Path(args.report_runtime_dir).expanduser().resolve() if args.report_runtime_dir else None
    if args.command == "status":
        lookup_dir = report_runtime_dir or runtime_dir
        payload = read_profit_target_tracker(lookup_dir)
        payload.setdefault("runtimeDir", str(runtime_dir))
        payload.setdefault("reportPath", str(report_path(lookup_dir)))
        payload["statusLookupRuntimeDir"] = str(lookup_dir)
        if report_runtime_dir:
            payload["reportRuntimeDir"] = str(report_runtime_dir)
        return emit(payload)
    if args.command == "build":
        return emit(build_profit_target_tracker(
            runtime_dir,
            secondary_runtime_dir=secondary_runtime_dir,
            report_runtime_dir=report_runtime_dir,
            target_usd=args.target_usd,
            write=args.write,
        ))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
