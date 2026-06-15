#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from runtime_evidence_integrity.report import build_core_evidence_manifest


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod core runtime evidence integrity guard")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(repo_root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "build", "verify"):
        item = sub.add_parser(command)
        item.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir).expanduser()
    if not runtime_dir.is_absolute():
        runtime_dir = repo_root / runtime_dir
    payload = build_core_evidence_manifest(
        runtime_dir,
        write=args.write or args.command == "build",
    )
    emit(payload)
    if args.command == "verify" and payload.get("status") != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

