#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict

from usdjpy_autonomous_agent.agent_state import build_agent_state
from usdjpy_autonomous_agent.config_patch import build_config_patch
from usdjpy_autonomous_agent.promotion_gate import build_promotion_decision
from usdjpy_autonomous_agent.schema import FOCUS_SYMBOL, HARD_SAFETY
from usdjpy_autonomous_agent.telegram_text import autonomous_agent_to_chinese_text
from autonomous_lifecycle.cent_account_rules import cent_account_config
from autonomous_lifecycle.ea_reproducibility import build_ea_reproducibility
from autonomous_lifecycle.hfm_crypto_shadow_lane import build_hfm_crypto_shadow_lane
from autonomous_lifecycle.lifecycle import build_autonomous_lifecycle
from autonomous_lifecycle.mt5_shadow_lane import build_mt5_shadow_lane
from usdjpy_evidence_os.telegram_gateway import dispatch_text
from usdjpy_walk_forward.selector import sample_walk_forward_runtime
from hfm_crypto_cfd.runtime_scope import hfm_crypto_runtime_scope_meta, resolve_hfm_crypto_runtime_dir


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def emit(payload) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def send_telegram(runtime_dir: Path, text: str) -> Dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env.telegram.local")
    return dispatch_text(runtime_dir, "usdjpy_autonomous_agent", "USDJPY_AUTONOMOUS_AGENT_REPORT", "INFO", text, send=True)


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env.usdjpy.local")
    parser = argparse.ArgumentParser(description="QuantGod P3-20 USDJPY autonomous walk-forward promotion gate")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    parser.add_argument("--hfm-crypto-runtime-dir", default=os.environ.get("QG_HFM_CRYPTO_RUNTIME_DIR", ""))
    parser.add_argument("--symbol", default=FOCUS_SYMBOL)
    parser.add_argument("--repo-root", default=str(root))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config")
    sample = sub.add_parser("sample")
    sample.add_argument("--overwrite", action="store_true")
    decision = sub.add_parser("decision")
    decision.add_argument("--write", action="store_true")
    patch = sub.add_parser("patch")
    patch.add_argument("--write", action="store_true")
    state = sub.add_parser("state")
    state.add_argument("--write", action="store_true")
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    lifecycle = sub.add_parser("lifecycle")
    lifecycle.add_argument("--write", action="store_true")
    lanes = sub.add_parser("lanes")
    lanes.add_argument("--write", action="store_true")
    mt5_shadow = sub.add_parser("mt5-shadow")
    mt5_shadow.add_argument("--write", action="store_true")
    hfm_crypto_shadow = sub.add_parser("hfm-crypto-shadow")
    hfm_crypto_shadow.add_argument("--write", action="store_true")
    repro = sub.add_parser("ea-repro")
    repro.add_argument("--write", action="store_true")
    text = sub.add_parser("telegram-text")
    text.add_argument("--refresh", action="store_true")
    text.add_argument("--write", action="store_true")
    text.add_argument("--send", action="store_true")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    hfm_crypto_runtime_dir = resolve_hfm_crypto_runtime_dir(runtime_dir, args.hfm_crypto_runtime_dir)
    hfm_crypto_runtime_scope = hfm_crypto_runtime_scope_meta(runtime_dir, args.hfm_crypto_runtime_dir)
    if args.symbol.upper() not in {"USDJPY", "USDJPYC"}:
        return emit({"ok": False, "error": "P3-20 只允许 USDJPY/USDJPYc", "symbol": args.symbol})
    if args.command == "config":
        return emit({
            "ok": True,
            "focusSymbol": FOCUS_SYMBOL,
            "runtimeDir": str(runtime_dir),
            "hfmCryptoRuntimeScope": hfm_crypto_runtime_scope,
            "centAccount": cent_account_config(),
            "safety": HARD_SAFETY,
        })
    if args.command == "sample":
        return emit(sample_walk_forward_runtime(runtime_dir, overwrite=args.overwrite))
    if args.command == "decision":
        return emit(build_promotion_decision(runtime_dir, write=args.write))
    if args.command == "patch":
        return emit(build_config_patch(runtime_dir, write=args.write))
    if args.command in {"state", "build"}:
        payload = build_agent_state(runtime_dir, write=args.write, hfm_crypto_runtime_dir=hfm_crypto_runtime_dir)
        payload["hfmCryptoRuntimeScope"] = hfm_crypto_runtime_scope
        return emit(payload)
    if args.command == "lifecycle":
        payload = build_autonomous_lifecycle(
            runtime_dir,
            repo_root=Path(args.repo_root),
            write=args.write,
            hfm_crypto_runtime_dir=hfm_crypto_runtime_dir,
        )
        payload["hfmCryptoRuntimeScope"] = hfm_crypto_runtime_scope
        return emit(payload)
    if args.command == "lanes":
        lifecycle_payload = build_autonomous_lifecycle(
            runtime_dir,
            repo_root=Path(args.repo_root),
            write=args.write,
            hfm_crypto_runtime_dir=hfm_crypto_runtime_dir,
        )
        return emit({"ok": True, "lanes": lifecycle_payload.get("lanes"), "centAccount": lifecycle_payload.get("centAccount")})
    if args.command == "mt5-shadow":
        return emit(build_mt5_shadow_lane(runtime_dir, write=args.write))
    if args.command == "hfm-crypto-shadow":
        payload = build_hfm_crypto_shadow_lane(hfm_crypto_runtime_dir, write=args.write)
        payload["hfmCryptoRuntimeScope"] = hfm_crypto_runtime_scope
        return emit(payload)
    if args.command == "ea-repro":
        return emit(build_ea_reproducibility(runtime_dir, repo_root=Path(args.repo_root), write=args.write))
    if args.command == "telegram-text":
        payload = build_agent_state(runtime_dir, write=args.write or args.refresh)
        content = autonomous_agent_to_chinese_text(payload)
        result = {"ok": True, "text": content, "state": payload}
        if args.send:
            result["telegramGateway"] = send_telegram(runtime_dir, content)
        return emit(result)
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
