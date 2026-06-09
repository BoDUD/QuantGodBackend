#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools.forex_simulation_profile.builder import (
        build_forex_simulation_profile_review,
        read_forex_simulation_profile_review,
    )
except ModuleNotFoundError:  # pragma: no cover
    from forex_simulation_profile.builder import (
        build_forex_simulation_profile_review,
        read_forex_simulation_profile_review,
    )


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod USDJPY/forex MT5 simulation profile")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    if args.command == "build":
        return emit(build_forex_simulation_profile_review(runtime_dir, write=args.write))
    if args.command == "status":
        return emit(read_forex_simulation_profile_review(runtime_dir))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
