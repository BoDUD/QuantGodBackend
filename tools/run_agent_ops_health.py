#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent_ops_health import build_agent_ops_health
from hfm_crypto_cfd.runtime_scope import hfm_crypto_runtime_scope_meta, resolve_hfm_crypto_runtime_dir


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env")
    load_env(root / ".env.local")
    load_env(root / ".env.telegram.local")
    load_env(root / ".env.usdjpy.local")
    parser = argparse.ArgumentParser(description="QuantGod Agent Ops Health")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    parser.add_argument("--hfm-crypto-runtime-dir", default=os.environ.get("QG_HFM_CRYPTO_RUNTIME_DIR", ""))
    parser.add_argument("--repo-root", default=str(root))
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    hfm_crypto_runtime_dir = resolve_hfm_crypto_runtime_dir(runtime_dir, args.hfm_crypto_runtime_dir)
    hfm_crypto_runtime_scope = hfm_crypto_runtime_scope_meta(runtime_dir, args.hfm_crypto_runtime_dir)
    repo_root = Path(args.repo_root)
    if args.command == "status":
        payload = build_agent_ops_health(
            runtime_dir,
            repo_root=repo_root,
            write=args.write,
            hfm_crypto_runtime_dir=hfm_crypto_runtime_dir,
        )
        payload["hfmCryptoRuntimeScope"] = hfm_crypto_runtime_scope
        return emit(payload)
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
