#!/usr/bin/env python3
"""CLI for the read-only QuantGod TP/SL optimizer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from tools.tp_sl_optimizer import build_tp_sl_optimizer_report, read_tp_sl_optimizer_report
except ModuleNotFoundError:  # pragma: no cover
    from tp_sl_optimizer import build_tp_sl_optimizer_report, read_tp_sl_optimizer_report


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod read-only TP/SL optimizer")
    parser.add_argument("--runtime-dir", default=str(root / "runtime"))
    parser.add_argument("--top-n", type=int, default=8)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(build_tp_sl_optimizer_report(runtime_dir, top_n=args.top_n, write=args.write))
    if args.command == "status":
        return emit(read_tp_sl_optimizer_report(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
