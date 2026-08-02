#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict

from daily_autopilot_v2.orchestrator import run_daily_autopilot_cycle
from daily_autopilot_v2.report import build_daily_autopilot_v2
from daily_autopilot_v2.telegram_text import daily_autopilot_v2_to_chinese_text
from telegram_cli_truth import explicit_send_exit_code, normalize_delivery
from telegram_digest import build_digest
from telegram_gateway_cli import dispatch_cli_text


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


def emit(payload, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def attach_delivery(result: Dict[str, object], gateway: Dict[str, object]) -> int:
    normalized_gateway = normalize_delivery(gateway, send_requested=True)
    result.update(
        {
            "telegramGateway": normalized_gateway,
            "sendRequested": True,
            "sent": normalized_gateway["sent"],
            "deliveryOk": normalized_gateway["deliveryOk"],
        }
    )
    if not normalized_gateway["deliveryOk"]:
        result["ok"] = False
        result["error"] = "TELEGRAM_DELIVERY_NOT_CONFIRMED"
    return explicit_send_exit_code(True, result)


def todo_text(payload: Dict[str, object]) -> str:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    history = payload.get("historyProductionStatus") if isinstance(payload.get("historyProductionStatus"), dict) else {}
    rows = [item for item in items if isinstance(item, dict)]
    completed = sum(1 for item in rows if str(item.get("status") or "").startswith("COMPLETED"))
    history_passed = str(history.get("promotionGateStatus") or "BLOCKED").upper() == "PASS"
    waiting = next((item for item in rows if not str(item.get("status") or "").startswith("COMPLETED")), None)
    return build_digest(
        title="Agent 待办",
        level="ok" if history_passed and completed == len(rows) else "warning",
        conclusion="Agent 已完成本轮自动检查。" if completed == len(rows) else "仍有只读研究任务等待自动处理。",
        metrics=[f"完成 {completed}/{len(rows)}", f"历史数据 {'通过' if history_passed else '未通过'}"],
        reasons=[] if history_passed else [history.get("reasonZh") or "历史数据尚未通过生产验收。"],
        next_action=(waiting or {}).get("summaryZh") or "等待下一轮自动复核，无需人工回灌。",
        generated_at=payload.get("generatedAtIso"),
    )


def review_text(payload: Dict[str, object]) -> str:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    live = payload.get("liveLane") if isinstance(payload.get("liveLane"), dict) else {}
    mt5 = payload.get("mt5ShadowLane") if isinstance(payload.get("mt5ShadowLane"), dict) else {}
    history = payload.get("historyProductionStatus") if isinstance(payload.get("historyProductionStatus"), dict) else {}
    consistency = payload.get("executionConsistencyReview") if isinstance(payload.get("executionConsistencyReview"), dict) else {}
    history_passed = str(history.get("promotionGateStatus") or "BLOCKED").upper() == "PASS"
    parity_passed = str(consistency.get("parityGateStatus") or "MISSING").upper() == "PASS"
    rollback = bool(payload.get("rollbackTriggered"))
    if rollback:
        conclusion = "本轮触发硬回滚，所有候选保持只读。"
        level = "danger"
    elif history_passed and parity_passed:
        conclusion = "本轮复盘完成，只读证据链正常。"
        level = "ok"
    else:
        conclusion = "本轮复盘完成，但证据仍未达到晋级条件。"
        level = "warning"
    reasons = []
    if not history_passed:
        reasons.append(history.get("reasonZh") or "历史数据尚未通过生产验收。")
    if not parity_passed:
        reasons.append("策略与 EA 一致性证据尚未通过。")
    return build_digest(
        title="每日复盘",
        level=level,
        conclusion=conclusion,
        metrics=[
            f"验证阶段 {live.get('stageZh') or live.get('stage') or 'Shadow'}",
            f"样本净 R {metrics.get('netR', 0)}",
            f"最大不利 R {metrics.get('maxAdverseR', '—')}",
            f"模拟路线 {(mt5.get('summary') or {}).get('routeCount', 0)}",
        ],
        reasons=reasons,
        next_action=consistency.get("agentConclusionZh") or "继续收集一致性和回放证据。",
        generated_at=payload.get("generatedAtIso"),
    )


def send_telegram(runtime_dir: Path, topic: str, text: str) -> Dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    return dispatch_cli_text(
        runtime_dir=runtime_dir,
        source="daily_autopilot_v2",
        topic=topic,
        severity="INFO",
        text=text,
        repo_root=root,
    )


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env.usdjpy.local")
    parser = argparse.ArgumentParser(description="QuantGod Daily Autopilot 2.0 for USDJPY cent-account autonomous agent")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    parser.add_argument("--repo-root", default=str(root))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    run_cycle = sub.add_parser("run-cycle")
    run_cycle.add_argument("--write", action="store_true")
    run_cycle.add_argument("--bootstrap-samples", action="store_true")
    run_cycle.add_argument("--view", choices=["full", "daily-todo", "daily-review"], default="full")
    todo = sub.add_parser("daily-todo")
    todo.add_argument("--write", action="store_true")
    review = sub.add_parser("daily-review")
    review.add_argument("--write", action="store_true")
    text = sub.add_parser("telegram-text")
    text.add_argument("--refresh", action="store_true")
    text.add_argument("--write", action="store_true")
    text.add_argument("--send", action="store_true")
    todo_text_parser = sub.add_parser("daily-todo-telegram-text")
    todo_text_parser.add_argument("--refresh", action="store_true")
    todo_text_parser.add_argument("--write", action="store_true")
    todo_text_parser.add_argument("--send", action="store_true")
    review_text_parser = sub.add_parser("daily-review-telegram-text")
    review_text_parser.add_argument("--refresh", action="store_true")
    review_text_parser.add_argument("--write", action="store_true")
    review_text_parser.add_argument("--send", action="store_true")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    repo_root = Path(args.repo_root)
    if args.command == "status":
        payload = build_daily_autopilot_v2(
            runtime_dir,
            repo_root=repo_root,
            write=False,
        )
        return emit(payload)
    if args.command == "build":
        payload = build_daily_autopilot_v2(
            runtime_dir,
            repo_root=repo_root,
            write=args.write,
        )
        return emit(payload)
    if args.command == "run-cycle":
        run_payload = run_daily_autopilot_cycle(
            runtime_dir,
            repo_root=repo_root,
            write=args.write or True,
            bootstrap_samples=args.bootstrap_samples,
        )
        payload = build_daily_autopilot_v2(
            runtime_dir,
            repo_root=repo_root,
            write=args.write or True,
        )
        payload["orchestrationRun"] = run_payload
        if args.view == "daily-todo":
            daily_todo = payload.get("dailyTodo") if isinstance(payload.get("dailyTodo"), dict) else {}
            daily_todo["orchestrationRun"] = run_payload
            return emit(daily_todo)
        if args.view == "daily-review":
            daily_review = payload.get("dailyReview") if isinstance(payload.get("dailyReview"), dict) else {}
            daily_review["orchestrationRun"] = run_payload
            return emit(daily_review)
        return emit(payload)
    if args.command == "daily-todo":
        payload = build_daily_autopilot_v2(
            runtime_dir,
            repo_root=repo_root,
            write=args.write,
        )
        return emit(payload.get("dailyTodo") or {"ok": False, "error": "daily_todo_missing"})
    if args.command == "daily-review":
        payload = build_daily_autopilot_v2(
            runtime_dir,
            repo_root=repo_root,
            write=args.write,
        )
        return emit(payload.get("dailyReview") or {"ok": False, "error": "daily_review_missing"})
    if args.command == "telegram-text":
        payload = build_daily_autopilot_v2(
            runtime_dir,
            repo_root=repo_root,
            write=args.write or args.refresh,
        )
        content = daily_autopilot_v2_to_chinese_text(payload)
        result = {"ok": True, "text": content, "dailyAutopilotV2": payload}
        if args.send:
            exit_code = attach_delivery(
                result,
                send_telegram(runtime_dir, "DAILY_AUTOPILOT_V2_REPORT", content),
            )
            return emit(result, exit_code)
        return emit(result)
    if args.command == "daily-todo-telegram-text":
        payload = build_daily_autopilot_v2(
            runtime_dir,
            repo_root=repo_root,
            write=args.write or args.refresh,
        )
        daily_todo = payload.get("dailyTodo") if isinstance(payload.get("dailyTodo"), dict) else {}
        content = todo_text(daily_todo)
        result = {"ok": True, "text": content, "dailyTodo": daily_todo}
        if args.send:
            exit_code = attach_delivery(
                result,
                send_telegram(runtime_dir, "DAILY_TODO_AGENT_REPORT", content),
            )
            return emit(result, exit_code)
        return emit(result)
    if args.command == "daily-review-telegram-text":
        payload = build_daily_autopilot_v2(
            runtime_dir,
            repo_root=repo_root,
            write=args.write or args.refresh,
        )
        daily_review = payload.get("dailyReview") if isinstance(payload.get("dailyReview"), dict) else {}
        content = review_text(daily_review)
        result = {"ok": True, "text": content, "dailyReview": daily_review}
        if args.send:
            exit_code = attach_delivery(
                result,
                send_telegram(runtime_dir, "DAILY_REVIEW_AGENT_REPORT", content),
            )
            return emit(result, exit_code)
        return emit(result)
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
