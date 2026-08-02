#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from adaptive_policy.policy_engine import build_adaptive_policy, load_policy_file
from adaptive_policy.telegram_text import build_policy_telegram_text
from telegram_cli_truth import explicit_send_exit_code, normalize_delivery
from telegram_gateway_cli import dispatch_cli_text

def _json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))

def _symbols(text: str | None) -> list[str] | None:
    if not text:
        return None
    return [part.strip() for part in text.split(",") if part.strip()]

def cmd_status(args: argparse.Namespace) -> int:
    policy = load_policy_file(args.runtime_dir)
    if not policy:
        _json({"ok": True, "policyFound": False, "message": "尚未生成自适应策略，请先运行 build。"})
        return 0
    _json({
        "ok": True,
        "policyFound": True,
        "generatedAt": policy.get("generatedAt"),
        "dataQuality": policy.get("dataQuality", {}),
        "routeCount": len(policy.get("routes", [])),
        "gateCount": len(policy.get("entryGates", [])),
        "planCount": len(policy.get("dynamicSltpPlans", [])),
        "safety": policy.get("safety", {}),
    })
    return 0

def cmd_build(args: argparse.Namespace) -> int:
    policy = build_adaptive_policy(args.runtime_dir, symbols=_symbols(args.symbols), write=not args.no_write)
    _json(policy if args.verbose else {
        "ok": True,
        "generatedAt": policy.get("generatedAt"),
        "dataQuality": policy.get("dataQuality", {}),
        "routeCount": len(policy.get("routes", [])),
        "gateCount": len(policy.get("entryGates", [])),
        "planCount": len(policy.get("dynamicSltpPlans", [])),
        "outputDir": str(Path(args.runtime_dir).expanduser() / "adaptive"),
    })
    return 0

def cmd_score(args: argparse.Namespace) -> int:
    policy = build_adaptive_policy(args.runtime_dir, symbols=_symbols(args.symbols), write=False)
    routes = policy.get("routes", [])
    if args.symbol:
        routes = [r for r in routes if str(r.get("symbol", "")).upper() == args.symbol.upper()]
    _json({"ok": True, "routes": routes})
    return 0

def cmd_gate(args: argparse.Namespace) -> int:
    policy = build_adaptive_policy(args.runtime_dir, symbols=_symbols(args.symbols), write=False)
    gates = policy.get("entryGates", [])
    if args.symbol:
        gates = [g for g in gates if str(g.get("symbol", "")).upper() == args.symbol.upper()]
    _json({"ok": True, "entryGates": gates})
    return 0

def cmd_sltp(args: argparse.Namespace) -> int:
    policy = build_adaptive_policy(args.runtime_dir, symbols=_symbols(args.symbols), write=False)
    plans = policy.get("dynamicSltpPlans", [])
    if args.symbol:
        plans = [p for p in plans if str(p.get("symbol", "")).upper() == args.symbol.upper()]
    _json({"ok": True, "dynamicSltpPlans": plans})
    return 0

def cmd_telegram_text(args: argparse.Namespace) -> int:
    policy = build_adaptive_policy(args.runtime_dir, symbols=_symbols(args.symbols), write=not args.no_write)
    text = build_policy_telegram_text(policy, symbol=args.symbol)
    print(text)
    if args.send:
        result = dispatch_cli_text(
            runtime_dir=args.runtime_dir,
            source="adaptive_policy",
            topic="ADAPTIVE_POLICY_REPORT",
            severity="WARN",
            text=text,
        )
        result = normalize_delivery(result, send_requested=True)
        _json(result)
        return explicit_send_exit_code(True, result)
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuantGod P3-6 adaptive policy engine")
    parser.add_argument("--runtime-dir", default="runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    build = sub.add_parser("build")
    build.add_argument("--symbols", default=None, help="逗号分隔品种，例如 USDJPYc,XAUUSDc")
    build.add_argument("--no-write", action="store_true")
    build.add_argument("--verbose", action="store_true")
    build.set_defaults(func=cmd_build)

    score = sub.add_parser("score")
    score.add_argument("--symbols", default=None)
    score.add_argument("--symbol", default=None)
    score.set_defaults(func=cmd_score)

    gate = sub.add_parser("gate")
    gate.add_argument("--symbols", default=None)
    gate.add_argument("--symbol", default=None)
    gate.set_defaults(func=cmd_gate)

    sltp = sub.add_parser("sltp")
    sltp.add_argument("--symbols", default=None)
    sltp.add_argument("--symbol", default=None)
    sltp.set_defaults(func=cmd_sltp)

    text = sub.add_parser("telegram-text")
    text.add_argument("--symbols", default=None)
    text.add_argument("--symbol", default=None)
    text.add_argument("--no-write", action="store_true")
    text.add_argument("--send", action="store_true")
    text.set_defaults(func=cmd_telegram_text)

    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))

if __name__ == "__main__":
    raise SystemExit(main())
