#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List

CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from automation_chain.runner import AutomationChainRunner, loop_forever
from automation_chain.telegram_text import build_automation_telegram_text
from telegram_cli_truth import explicit_send_exit_code, normalize_delivery
from telegram_gateway_cli import dispatch_cli_text


def parse_symbols(value: str) -> List[str]:
    symbols = [x.strip() for x in str(value or "").split(",") if x.strip()]
    focus = [symbol for symbol in symbols if symbol.upper().startswith("USDJPY")]
    return focus or ["USDJPYc"]


def build_runner(args: argparse.Namespace) -> AutomationChainRunner:
    return AutomationChainRunner(
        repo_root=REPO_ROOT,
        runtime_dir=args.runtime_dir,
        symbols=parse_symbols(args.symbols),
        python_bin=os.environ.get("QG_PYTHON_BIN") or sys.executable,
        max_age_seconds=args.max_age_seconds,
    )


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_status(args: argparse.Namespace) -> int:
    print_json(build_runner(args).build_status())
    return 0


def annotate_chain_delivery(report: dict, *, send_requested: bool) -> dict:
    if not send_requested:
        report.update({"sendRequested": False, "sent": False, "deliveryOk": False})
        return report
    telegram_step = next(
        (step for step in report.get("steps", []) if step.get("name") == "usdjpy_live_loop_telegram"),
        {},
    )
    stdout = telegram_step.get("stdoutPreview", "")
    delivery = normalize_delivery(
        {"ok": True, "telegramGateway": stdout},
        send_requested=True,
    )
    report.update(
        {
            "sendRequested": True,
            "sent": delivery["sent"],
            "deliveryOk": delivery["deliveryOk"],
            "telegramGateway": stdout,
        }
    )
    if not delivery["deliveryOk"]:
        report["ok"] = False
        report["telegramDeliveryError"] = "TELEGRAM_DELIVERY_NOT_CONFIRMED"
    return report


def cmd_once(args: argparse.Namespace) -> int:
    report = build_runner(args).run_once(send=args.send, write=not args.no_write)
    report = annotate_chain_delivery(report, send_requested=bool(args.send))
    print_json(report)
    if report.get("runStatus") != "COMPLETED":
        return 2
    return explicit_send_exit_code(bool(args.send), report)


def cmd_safe_iteration_cycle(args: argparse.Namespace) -> int:
    report = build_runner(args).run_safe_iteration_cycle(
        refresh_before=not args.no_refresh_before,
        refresh_after=not args.no_refresh_after,
        max_actions=args.max_actions,
        write=not args.no_write,
    )
    print_json(report)
    return 0


def cmd_safe_iteration_loop(args: argparse.Namespace) -> int:
    report = build_runner(args).run_safe_iteration_loop(
        cycles=args.cycles,
        max_actions=args.max_actions,
        write=not args.no_write,
    )
    print_json(report)
    return 0


def cmd_telegram_text(args: argparse.Namespace) -> int:
    runner = build_runner(args)
    report = runner.run_once(send=False, write=not args.no_write) if args.refresh else runner.build_status()
    text = build_automation_telegram_text(report)
    print(text)
    if args.send:
        result = dispatch_cli_text(
            runtime_dir=args.runtime_dir,
            source="automation_chain",
            topic="AUTOMATION_CHAIN_REPORT",
            severity="WARN",
            text=text,
            repo_root=REPO_ROOT,
        )
        result = normalize_delivery(result, send_requested=True)
        print_json(result)
        return explicit_send_exit_code(True, result)
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    runner = build_runner(args)
    if not args.send:
        loop_forever(runner, interval_seconds=args.interval_seconds, send=False)
        return 0
    while True:
        report = annotate_chain_delivery(
            runner.run_once(send=True, write=True),
            send_requested=True,
        )
        print_json(report)
        if explicit_send_exit_code(True, report) != 0:
            return 2
        time.sleep(max(5, int(args.interval_seconds)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuantGod P3-12 automation chain runner")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", "runtime"))
    parser.add_argument("--symbols", default=os.environ.get("QG_AUTOMATION_SYMBOLS", "USDJPYc"))
    parser.add_argument("--max-age-seconds", type=int, default=int(os.environ.get("QG_AUTOMATION_MAX_AGE_SECONDS", "180")))
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    once = sub.add_parser("once")
    once.add_argument("--send", action="store_true")
    once.add_argument("--no-write", action="store_true")
    once.set_defaults(func=cmd_once)
    cycle = sub.add_parser("safe-iteration-cycle")
    cycle.add_argument("--max-actions", type=int, default=None)
    cycle.add_argument("--no-refresh-before", action="store_true")
    cycle.add_argument("--no-refresh-after", action="store_true")
    cycle.add_argument("--no-write", action="store_true")
    cycle.set_defaults(func=cmd_safe_iteration_cycle)
    iteration_loop = sub.add_parser("safe-iteration-loop")
    iteration_loop.add_argument("--cycles", type=int, default=2)
    iteration_loop.add_argument("--max-actions", type=int, default=None)
    iteration_loop.add_argument("--no-write", action="store_true")
    iteration_loop.set_defaults(func=cmd_safe_iteration_loop)
    text = sub.add_parser("telegram-text")
    text.add_argument("--refresh", action="store_true")
    text.add_argument("--send", action="store_true")
    text.add_argument("--no-write", action="store_true")
    text.set_defaults(func=cmd_telegram_text)
    loop = sub.add_parser("loop")
    loop.add_argument("--interval-seconds", type=int, default=int(os.environ.get("QG_AUTOMATION_INTERVAL_SECONDS", "300")))
    loop.add_argument("--send", action="store_true")
    loop.set_defaults(func=cmd_loop)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
