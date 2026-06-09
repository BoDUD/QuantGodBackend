#!/usr/bin/env python3
"""CLI for the read-only ace execution candidate pack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from tools.ace_execution_candidate_pack import (
        build_ace_execution_candidate_pack,
        read_ace_execution_candidate_pack,
    )
except ModuleNotFoundError:  # pragma: no cover
    from ace_execution_candidate_pack import (
        build_ace_execution_candidate_pack,
        read_ace_execution_candidate_pack,
    )


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod read-only ace execution candidate pack")
    parser.add_argument("--runtime-dir", default=str(root / "runtime"))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(build_ace_execution_candidate_pack(runtime_dir, write=args.write))
    if args.command == "status":
        return emit(read_ace_execution_candidate_pack(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
