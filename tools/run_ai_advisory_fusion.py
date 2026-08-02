#!/usr/bin/env python3
"""Run a read-only MT5 + DeepSeek advisory fusion pass.

This CLI is intentionally single-user and local-only.  It exists to smoke-test
and inspect the same fusion layer that the Telegram MT5 monitor uses after this
overlay patches it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
for candidate in (str(REPO_ROOT), str(TOOLS_DIR)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from ai_analysis.advisory_fusion import (  # noqa: E402
    compact_fusion_payload,
    fuse_advisory_report,
    fusion_summary_for_message,
)
from ai_analysis.analysis_service_v2 import AnalysisServiceV2, phase3_ai_safety  # noqa: E402
from ai_analysis.deepseek_mt5_advisor import (  # noqa: E402
    DeepSeekAdvisorError,
    DeepSeekMt5Advisor,
    load_deepseek_config,
)
from telegram_digest import build_digest  # noqa: E402
from telegram_gateway_cli import dispatch_cli_text  # noqa: E402
from telegram_notifier.config import load_config  # noqa: E402
from telegram_notifier.records import record_notification  # noqa: E402
from telegram_notifier.safety import (  # noqa: E402
    assert_telegram_safety,
)
from telegram_notifier.safety import (  # noqa: E402
    safety_payload as telegram_safety_payload,
)

MODE = "QUANTGOD_AI_ADVISORY_FUSION_V1"
DEFAULT_SYMBOLS = "USDJPYc"
DEFAULT_TIMEFRAMES = "M15,H1,H4,D1"


def safety_payload() -> dict[str, Any]:
    payload = {
        "mode": MODE,
        "localOnly": True,
        "readOnlyDataPlane": True,
        "advisoryOnly": True,
        "telegramPushOnlyCompatible": True,
        "orderSendAllowed": False,
        "closeAllowed": False,
        "cancelAllowed": False,
        "credentialStorageAllowed": False,
        "livePresetMutationAllowed": False,
        "canOverrideKillSwitch": False,
        "telegramCommandExecutionAllowed": False,
        "telegramWebhookReceiverAllowed": False,
        "webhookReceiverAllowed": False,
        "emailDeliveryAllowed": False,
        "multiUserAllowed": False,
        "billingAllowed": False,
    }
    payload["ai"] = phase3_ai_safety()
    return payload


def parse_csv_list(value: str | None, fallback: str) -> list[str]:
    raw = value if value not in (None, "") else fallback
    items: list[str] = []
    for part in str(raw).split(","):
        item = part.strip()
        if item and item not in items:
            items.append(item)
    return items


def runtime_dir_from_args(args: argparse.Namespace) -> Path:
    value = args.runtime_dir or os.environ.get("QG_RUNTIME_DIR") or os.environ.get("QG_MT5_FILES_DIR")
    return Path(value or (REPO_ROOT / "runtime")).expanduser().resolve()


def latest_path(args: argparse.Namespace) -> Path:
    if args.latest_file:
        return Path(args.latest_file).expanduser().resolve()
    return runtime_dir_from_args(args) / "QuantGod_AIAdvisoryFusionLatest.json"


def attach_deepseek(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(report)
    if args.no_deepseek:
        enriched["deepseek_advice"] = {"ok": False, "status": "disabled_by_cli", "provider": "deepseek"}
        return fuse_advisory_report(enriched)
    try:
        config = load_deepseek_config(repo_root=REPO_ROOT, env_file=args.deepseek_env_file)
        advice = DeepSeekMt5Advisor(config).analyze(enriched)
    except (DeepSeekAdvisorError, ValueError, OSError) as error:
        advice = {"ok": False, "status": "error", "provider": "deepseek", "error": str(error)[:240]}
    enriched["deepseek_advice"] = advice
    return fuse_advisory_report(enriched)


def build_compact_message(report: dict[str, Any]) -> str:
    compact = compact_fusion_payload(report)
    quality = compact.get("evidenceQuality") if isinstance(compact.get("evidenceQuality"), dict) else {}
    action = str(compact.get("finalAction") or "HOLD").upper()
    action_zh = {
        "WATCH_LONG": "偏多观察",
        "WATCH_SHORT": "偏空观察",
        "BUY": "偏多观察",
        "SELL": "偏空观察",
        "HOLD": "继续观望",
    }.get(action, "继续观望")
    validator = str(compact.get("validatorStatus") or "unknown")
    freshness = "新鲜" if quality.get("runtimeFresh") is True else "待刷新"
    source = str(quality.get("source") or "unknown")
    agreement = str(compact.get("agreement") or "unknown")
    fallback = "是" if quality.get("fallback") is True else "否"
    reasons = [
        f"校验 {validator}；共识 {agreement}。",
        f"证据来源 {source}；回退 {fallback}。",
    ]
    return build_digest(
        title="AI 融合观察",
        level="warning" if action == "HOLD" or validator != "pass" else "info",
        conclusion=f"{compact.get('symbol') or 'UNKNOWN'} {action_zh}；仅保存只读 Shadow 证据。",
        metrics=[
            f"证据 {freshness}",
            f"风险级别 {compact.get('notifySeverity') or 'unknown'}",
            f"校验 {validator}",
        ],
        reasons=reasons,
        next_action="在本地面板复核证据新鲜度与风险门禁；不触发任何交易动作。",
        generated_at=report.get("generatedAt"),
    )


def maybe_send(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    message = build_compact_message(report)
    if not args.send:
        return {
            "ok": True,
            "status": "preview",
            "dryRun": True,
            "sendRequested": False,
            "sent": False,
            "deliveryOk": False,
            "messagePreview": message,
        }

    config = load_config(repo_root=args.repo_root, env_file=args.env_file)
    assert_telegram_safety(config)
    gateway = dispatch_cli_text(
        runtime_dir=runtime_dir_from_args(args),
        source="ai_advisory_fusion",
        topic="AI_ADVISORY_FUSION",
        severity="INFO",
        text=message,
        repo_root=args.repo_root or REPO_ROOT,
    )
    nested_delivery = gateway.get("delivery") if isinstance(gateway.get("delivery"), dict) else {}
    confirmed = gateway.get("sent") is True and gateway.get("deliveryOk") is True
    status = "sent" if confirmed else "send_suppressed" if nested_delivery.get("skipped") is True else "send_failed"
    record = {"ok": True, "recorded": False}
    if not args.no_record:
        record = record_notification(
            config,
            event_type="AI_ADVISORY_FUSION",
            status="sent" if confirmed else status,
            payload={
                "telegramMessageId": nested_delivery.get("messageId") if confirmed else None,
                "messagePreview": message[:160],
                "reason": nested_delivery.get("reason"),
            },
        )
    gateway.update(
        {
            "ok": confirmed,
            "status": status,
            "sent": confirmed,
            "deliveryOk": confirmed,
            "telegramMessageId": nested_delivery.get("messageId") if confirmed else None,
            "record": record,
            "safety": telegram_safety_payload(config),
        }
    )
    return gateway


async def scan_once(args: argparse.Namespace) -> dict[str, Any]:
    runtime_dir = runtime_dir_from_args(args)
    symbols = parse_csv_list(args.symbols or os.environ.get("QG_MT5_AI_MONITOR_SYMBOLS"), DEFAULT_SYMBOLS)
    timeframes = parse_csv_list(args.timeframes, DEFAULT_TIMEFRAMES)
    service = AnalysisServiceV2(runtime_dir=runtime_dir)
    items: list[dict[str, Any]] = []
    for symbol in symbols:
        report = await service.run_analysis(symbol, timeframes)
        fused = attach_deepseek(args, report)
        delivery = maybe_send(args, fused) if args.send or args.delivery_preview else {"ok": True, "status": "not_requested"}
        items.append(
            {
                "symbol": symbol,
                "fusion": compact_fusion_payload(fused),
                "summary": fusion_summary_for_message(fused),
                "delivery": delivery,
            }
        )
    deliveries = [item.get("delivery") for item in items if isinstance(item.get("delivery"), dict)]
    attempted = [delivery for delivery in deliveries if delivery.get("sendRequested") is True]
    confirmed_count = sum(
        delivery.get("sent") is True and delivery.get("deliveryOk") is True
        for delivery in attempted
    )
    failed_count = len(attempted) - confirmed_count
    payload = {
        "ok": failed_count == 0,
        "mode": MODE,
        "runtimeDir": str(runtime_dir),
        "symbols": symbols,
        "timeframes": timeframes,
        "items": items,
        "sendRequested": bool(args.send),
        "deliveryAttemptedCount": len(attempted),
        "sent": confirmed_count > 0,
        "sentCount": confirmed_count,
        "deliveryOk": (failed_count == 0 and bool(attempted)) if args.send else False,
        "failedDeliveryCount": failed_count,
        "safety": safety_payload(),
    }
    target = latest_path(args)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    payload["latestPath"] = str(target)
    return payload


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuantGod DeepSeek Telegram advisory fusion")
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config", help="Show fusion safety/config")
    config.set_defaults(func=lambda args: {"ok": True, "mode": MODE, "defaultSymbols": DEFAULT_SYMBOLS, "safety": safety_payload()})

    once = sub.add_parser("scan-once", help="Run one MT5 + DeepSeek fusion pass")
    once.add_argument("--symbols", default="", help=f"Comma-separated symbols. Default: {DEFAULT_SYMBOLS}")
    once.add_argument("--timeframes", default=DEFAULT_TIMEFRAMES, help=f"Comma-separated timeframes. Default: {DEFAULT_TIMEFRAMES}")
    once.add_argument("--runtime-dir", type=Path, default=None, help="MT5 runtime directory")
    once.add_argument("--latest-file", type=Path, default=None, help="Where to write latest fusion JSON")
    once.add_argument("--deepseek-env-file", type=Path, default=None, help="Local .env.deepseek.local path")
    once.add_argument("--no-deepseek", action="store_true", help="Skip DeepSeek and run validator downgrade/fallback path")
    once.add_argument("--delivery-preview", action="store_true", help="Build dry-run Telegram preview in output")
    once.add_argument("--send", action="store_true", help="Send compact Telegram fusion message")
    once.add_argument("--disable-notification", action="store_true", help="Send Telegram silently when --send is used")
    once.add_argument("--no-record", action="store_true", help="Do not write notification evidence when --send is used")
    once.add_argument("--repo-root", type=Path, default=None, help="Backend repo root for Telegram config")
    once.add_argument("--env-file", type=Path, default=None, help="Local .env.telegram.local path")
    once.set_defaults(func=scan_once)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        emit(result)
        if isinstance(result, dict) and int(result.get("failedDeliveryCount") or 0) > 0:
            return 2
        return 0
    except Exception as exc:  # pragma: no cover - CLI boundary
        emit({"ok": False, "mode": MODE, "error": str(exc), "safety": safety_payload()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
