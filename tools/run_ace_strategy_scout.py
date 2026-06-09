#!/usr/bin/env python3
"""CLI for the read-only ace strategy scout report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools.ace_strategy_scout import build_ace_strategy_scout, read_ace_strategy_scout
except ModuleNotFoundError:  # pragma: no cover
    from ace_strategy_scout import build_ace_strategy_scout, read_ace_strategy_scout


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod read-only ace strategy scout")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(build_ace_strategy_scout(runtime_dir, write=args.write))
    if args.command == "status":
        return emit(read_ace_strategy_scout(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
