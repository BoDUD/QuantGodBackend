#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools.hyperliquid_shadow_lane.builder import (
        build_hyperliquid_shadow_lane,
        read_hyperliquid_shadow_lane,
    )
except ModuleNotFoundError:  # pragma: no cover
    from hyperliquid_shadow_lane.builder import (
        build_hyperliquid_shadow_lane,
        read_hyperliquid_shadow_lane,
    )


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod Hyperliquid/Moss read-only shadow lane")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--target-agent-url", default=os.environ.get("QG_MOSS_TARGET_AGENT_URL", ""))
    build.add_argument(
        "--target-agent-profile-json",
        default=os.environ.get("QG_MOSS_TARGET_AGENT_PROFILE_JSON", ""),
    )
    build.add_argument("--write", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(build_hyperliquid_shadow_lane(
            runtime_dir,
            target_agent_url=args.target_agent_url,
            target_agent_profile_json=args.target_agent_profile_json,
            write=args.write,
        ))
    if args.command == "status":
        return emit(read_hyperliquid_shadow_lane(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
