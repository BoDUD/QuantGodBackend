#!/usr/bin/env python3
"""CLI for the read-only G0077 champion tester run gate."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools.champion_tester_run_gate import build_champion_tester_run_gate, read_champion_tester_run_gate
except ModuleNotFoundError:  # pragma: no cover
    from champion_tester_run_gate import build_champion_tester_run_gate, read_champion_tester_run_gate


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod read-only G0077 champion tester run gate")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    parser.add_argument("--primary-dashboard-json", default=os.environ.get("QG_PRIMARY_DASHBOARD_JSON", ""))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    build.add_argument("--allow-outside-window", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(
            build_champion_tester_run_gate(
                runtime_dir,
                primary_dashboard_json=args.primary_dashboard_json,
                allow_outside_window=args.allow_outside_window,
                write=args.write,
            )
        )
    if args.command == "status":
        return emit(read_champion_tester_run_gate(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
