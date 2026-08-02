#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pilot_safety_lock.checks import evaluate_pilot_safety_lock
from tools.pilot_safety_lock.lockfile import read_report, write_report
from tools.pilot_safety_lock.schema import DEFAULT_CONFIRMATION_PHRASE, SAFETY_DEFAULTS
from tools.pilot_safety_lock.telegram_text import build_telegram_text
from tools.telegram_cli_truth import explicit_send_exit_code, normalize_delivery
from tools.telegram_gateway_cli import dispatch_cli_text


def _send_telegram(runtime_dir: Path, text: str) -> dict:
    try:
        result = dispatch_cli_text(
            runtime_dir=runtime_dir,
            source="pilot_safety_lock",
            topic="PILOT_SAFETY_LOCK_REPORT",
            severity="WARN",
            text=text,
            repo_root=ROOT,
        )
        result = normalize_delivery(result, send_requested=True)
        output = {
            "ok": result["deliveryOk"],
            "sendRequested": True,
            "sent": result["sent"],
            "deliveryOk": result["deliveryOk"],
            "telegramGateway": result,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return output
    except Exception as exc:
        print(f"Telegram 发送失败：{exc}", file=sys.stderr)
        return {
            "ok": False,
            "sendRequested": True,
            "sent": False,
            "deliveryOk": False,
            "error": str(exc),
        }


def cmd_config(args: argparse.Namespace) -> int:
    payload = {
        "schema": "quantgod.pilot_safety_lock.config.v1",
        "confirmationPhraseRequired": DEFAULT_CONFIRMATION_PHRASE,
        "safety": SAFETY_DEFAULTS,
        "env": {
            "QG_PILOT_EXECUTION_ALLOWED": "0 默认阻断；设为 1 仍需其他证据通过",
            "QG_PILOT_CONFIRMATION_PHRASE": DEFAULT_CONFIRMATION_PHRASE,
            "QG_PILOT_MAX_LOT": "默认 0.01，且不可超过 0.01",
            "QG_PILOT_MAX_DAILY_TRADES": "默认 3，且不可超过 3",
            "QG_PILOT_MAX_DAILY_LOSS_R": "默认 1.0，且不可超过 1.0",
            "QG_PILOT_ALLOWED_SYMBOLS": "逗号分隔白名单，例如 USDJPYc",
            "QG_PILOT_ALLOWED_STRATEGIES": "逗号分隔白名单，例如 RSI_Reversal",
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    report = evaluate_pilot_safety_lock(Path(args.runtime_dir), args.symbol, args.direction, Path.cwd())
    if args.write:
        path = write_report(Path(args.runtime_dir), report)
        report["writtenTo"] = str(path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("decision") != "ARMABLE_FOR_MANUAL_PILOT" else 0


def cmd_status(args: argparse.Namespace) -> int:
    report = read_report(Path(args.runtime_dir))
    if report is None:
        report = {"schema": "quantgod.pilot_safety_lock.status.v1", "decision": "BLOCKED", "decisionZh": "阻断", "reasons": ["尚未生成 QuantGod_PilotSafetyLock.json"]}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_telegram_text(args: argparse.Namespace) -> int:
    report = read_report(Path(args.runtime_dir))
    if report is None or args.refresh:
        report = evaluate_pilot_safety_lock(Path(args.runtime_dir), args.symbol, args.direction, Path.cwd())
        if args.write:
            write_report(Path(args.runtime_dir), report)
    text = build_telegram_text(report)
    print(text)
    if args.send:
        delivery = _send_telegram(Path(args.runtime_dir), text)
        return explicit_send_exit_code(True, delivery)
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    runtime = Path(args.runtime_dir)
    symbol = args.symbol
    (runtime / "quality").mkdir(parents=True, exist_ok=True)
    (runtime / "adaptive").mkdir(parents=True, exist_ok=True)
    snapshot = {
        "schema": "quantgod.mt5.runtime_snapshot.v1",
        "symbol": symbol,
        "source": "hfm_ea_runtime",
        "fallback": False,
        "runtimeFresh": True,
        "current_price": {"bid": 155.12, "ask": 155.14, "spread": 0.02},
        "safety": {"readOnly": True, "orderSendAllowed": False, "closeAllowed": False, "cancelAllowed": False},
    }
    fastlane = {"schema": "quantgod.mt5_fastlane.quality.v1", "symbols": {symbol: {"quality": "OK", "tickFresh": True, "indicatorFresh": True, "spreadOk": True}}}
    gate = {"schema": "quantgod.dynamic_entry_gate.v1", "gates": [{"symbol": symbol, "direction": args.direction.upper(), "state": "PASS", "passed": True}]}
    trigger = {"schema": "quantgod.entry_trigger_lab.v1", "decisions": [{"symbol": symbol, "direction": args.direction.upper(), "state": "WAIT_TRIGGER_CONFIRMATION"}]}
    sltp = {"schema": "quantgod.dynamic_sltp_calibration.v1", "plans": [{"symbol": symbol, "direction": args.direction.upper(), "status": "CALIBRATED"}]}
    files = {
        runtime / f"QuantGod_MT5RuntimeSnapshot_{symbol}.json": snapshot,
        runtime / "quality" / "QuantGod_MT5FastLaneQuality.json": fastlane,
        runtime / "adaptive" / "QuantGod_DynamicEntryGate.json": gate,
        runtime / "adaptive" / "QuantGod_EntryTriggerPlan.json": trigger,
        runtime / "adaptive" / "QuantGod_DynamicSLTPCalibration.json": sltp,
    }
    for path, payload in files.items():
        if path.exists() and not args.overwrite:
            continue
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": [str(path) for path in files]}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuantGod P3-10 pilot safety lock")
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--symbol", default="USDJPYc")
    parser.add_argument("--direction", default="LONG", choices=["LONG", "SHORT", "long", "short"])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config").set_defaults(func=cmd_config)
    sample = sub.add_parser("sample"); sample.add_argument("--overwrite", action="store_true"); sample.set_defaults(func=cmd_sample)
    check = sub.add_parser("check"); check.add_argument("--write", action="store_true"); check.set_defaults(func=cmd_check)
    sub.add_parser("status").set_defaults(func=cmd_status)
    text = sub.add_parser("telegram-text"); text.add_argument("--send", action="store_true"); text.add_argument("--refresh", action="store_true"); text.add_argument("--write", action="store_true"); text.set_defaults(func=cmd_telegram_text)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
