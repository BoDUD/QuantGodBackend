#!/usr/bin/env python3
"""CLI for the read-only BTC strategy scanner."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools.btc_strategy_scanner import build_btc_strategy_scan_report, read_btc_strategy_scan_report
except ModuleNotFoundError:  # pragma: no cover
    from btc_strategy_scanner import build_btc_strategy_scan_report, read_btc_strategy_scan_report


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod read-only BTC strategy scanner")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    build.add_argument("--max-configs", type=int, default=512)
    build.add_argument("--top-n", type=int, default=12)
    sub.add_parser("status")
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(build_btc_strategy_scan_report(
            runtime_dir,
            max_configs=args.max_configs,
            top_n=args.top_n,
            write=args.write,
        ))
    if args.command == "status":
        return emit(read_btc_strategy_scan_report(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
