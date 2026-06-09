#!/usr/bin/env python3
"""CLI for the read-only G0077 champion tester/forward request."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools.champion_tester_forward_request import (
        build_champion_tester_forward_request,
        read_champion_tester_forward_request,
    )
except ModuleNotFoundError:  # pragma: no cover
    from champion_tester_forward_request import (
        build_champion_tester_forward_request,
        read_champion_tester_forward_request,
    )


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod read-only G0077 champion tester/forward request")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(build_champion_tester_forward_request(runtime_dir, write=args.write))
    if args.command == "status":
        return emit(read_champion_tester_forward_request(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
