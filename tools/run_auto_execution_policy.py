#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from auto_execution_policy.data_loader import write_json
from auto_execution_policy.policy_engine import AutoExecutionPolicyEngine, load_lot_config
from auto_execution_policy.telegram_text import build_telegram_text
from telegram_cli_truth import explicit_send_exit_code, normalize_delivery
from telegram_gateway_cli import dispatch_cli_text


def parse_symbols(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def cmd_config(args: argparse.Namespace) -> int:
    config = load_lot_config()
    payload = {
        "schema": "quantgod.auto_execution_policy.config.v1",
        "maxLot": config.max_lot,
        "riskPerTradePct": config.risk_per_trade_pct,
        "opportunityMultiplier": config.opportunity_multiplier,
        "standardMultiplier": config.standard_multiplier,
        "minimumLot": config.minimum_lot,
        "lotStep": config.lot_step,
        "accountEquity": config.account_equity,
        "safety": {
            "policyOnly": True,
            "doesNotPlaceOrders": True,
            "doesNotModifyPreset": True,
            "telegramCommandsAllowed": False,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    engine = AutoExecutionPolicyEngine(args.runtime_dir, max_age_seconds=args.max_age_seconds)
    document = engine.build(parse_symbols(args.symbols), directions=parse_symbols(args.directions), write=args.write)
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    engine = AutoExecutionPolicyEngine(args.runtime_dir, max_age_seconds=args.max_age_seconds)
    row = engine.build_row(args.symbol, args.direction).to_dict()
    print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_telegram_text(args: argparse.Namespace) -> int:
    engine = AutoExecutionPolicyEngine(args.runtime_dir, max_age_seconds=args.max_age_seconds)
    document = engine.build(parse_symbols(args.symbols), directions=parse_symbols(args.directions), write=args.write)
    text = build_telegram_text(document, symbol_filter=args.symbol if args.symbol else None)
    print(text)
    if args.send:
        result = dispatch_cli_text(
            runtime_dir=args.runtime_dir,
            source="auto_execution_policy",
            topic="AUTO_EXECUTION_POLICY_REPORT",
            severity="WARN",
            text=text,
        )
        result = normalize_delivery(result, send_requested=True)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return explicit_send_exit_code(True, result)
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir)
    if runtime_dir.exists() and not args.overwrite:
        print("sample runtime already exists; pass --overwrite to replace", file=sys.stderr)
        return 2
    (runtime_dir / "adaptive").mkdir(parents=True, exist_ok=True)
    write_json(runtime_dir / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json", {
        "schema": "quantgod.mt5.runtime_snapshot.v1",
        "source": "hfm_ea_runtime",
        "generatedAt": "2099-01-01T00:00:00Z",
        "symbol": "USDJPYc",
        "fallback": False,
        "current_price": {"bid": 155.12, "ask": 155.14, "spread": 0.02, "timeIso": "2099-01-01T00:00:00Z"},
    })
    write_json(runtime_dir / "quality" / "QuantGod_MT5FastLaneQuality.json", {"quality": "OK", "reason": "sample"})
    write_json(runtime_dir / "adaptive" / "QuantGod_DynamicEntryGate.json", {
        "entryGates": [
            {"symbol": "USDJPYc", "direction": "LONG", "status": "WAIT", "passed": False, "reason": "M1/M5二次确认缺一项，等待bar close"},
            {"symbol": "USDJPYc", "direction": "SHORT", "status": "PAUSED", "passed": False, "reason": "方向历史负期望，暂停"},
        ]
    })
    write_json(runtime_dir / "adaptive" / "QuantGod_DynamicSLTPCalibration.json", {
        "plans": [
            {"symbol": "USDJPYc", "direction": "LONG", "status": "CALIBRATED", "initialStop": "ATR × 1.35", "targets": "MFE p50/p70/p85"},
            {"symbol": "USDJPYc", "direction": "SHORT", "status": "CALIBRATED", "initialStop": "ATR × 1.35", "targets": "MFE p50/p70/p85"},
        ]
    })
    (runtime_dir / "ShadowCandidateOutcomeLedger.csv").write_text(
        "symbol,direction,scoreR,pips\n" + "\n".join(["USDJPYc,LONG,0.35,3.5"] * 8 + ["USDJPYc,SHORT,-0.40,-4.0"] * 8),
        encoding="utf-8",
    )
    print(f"sample runtime written: {runtime_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuantGod auto execution policy tuner")
    parser.add_argument("--runtime-dir", default="runtime", help="Runtime evidence directory")
    parser.add_argument("--max-age-seconds", type=int, default=180)
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config")
    config.set_defaults(func=cmd_config)

    sample = sub.add_parser("sample")
    sample.add_argument("--overwrite", action="store_true")
    sample.set_defaults(func=cmd_sample)

    build = sub.add_parser("build")
    build.add_argument("--symbols", default="USDJPYc")
    build.add_argument("--directions", default="LONG,SHORT")
    build.add_argument("--write", action="store_true")
    build.set_defaults(func=cmd_build)

    plan = sub.add_parser("plan")
    plan.add_argument("--symbol", required=True)
    plan.add_argument("--direction", default="LONG")
    plan.set_defaults(func=cmd_plan)

    text = sub.add_parser("telegram-text")
    text.add_argument("--symbols", default="USDJPYc")
    text.add_argument("--directions", default="LONG,SHORT")
    text.add_argument("--symbol", default="")
    text.add_argument("--write", action="store_true")
    text.add_argument("--send", action="store_true")
    text.set_defaults(func=cmd_telegram_text)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
