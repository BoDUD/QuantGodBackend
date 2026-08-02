from __future__ import annotations

from typing import Any

try:
    from telegram_digest import build_digest, clean_text
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest, clean_text


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def build_automation_telegram_text(report: dict[str, Any]) -> str:
    state = clean_text(report.get("stateZh") or report.get("state"), "尚未运行")
    steps = report.get("steps") if isinstance(report.get("steps"), list) else []
    passed_steps = sum(1 for step in steps if isinstance(step, dict) and step.get("ok"))
    missing = [clean_text(item) for item in (report.get("missingEvidence") or []) if clean_text(item)]
    blockers = [clean_text(item) for item in (report.get("blockedReasons") or []) if clean_text(item)]
    iteration = _dict(report.get("safeIterationPlan"))
    ga_summary = _dict(iteration.get("gaFactorySummary"))
    best_elite = _dict(ga_summary.get("bestElite"))
    actions = iteration.get("actions") if isinstance(iteration.get("actions"), list) else []

    has_blocker = bool(missing or blockers or "阻断" in state or "失败" in state)
    if has_blocker:
        conclusion = "巡检发现证据缺口，自动链路保持只读。"
        level = "warning"
    elif not steps:
        conclusion = "尚无完整巡检结果，等待下一轮只读闭环。"
        level = "info"
    else:
        conclusion = "自动巡检通过，继续积累 Shadow 证据。"
        level = "ok"

    reasons = (blockers + missing)[:2]
    if not reasons and not steps:
        reasons = ["当前尚未生成完整巡检证据。"]
    next_action = "运行下一轮自动巡检并刷新证据。"
    if actions and isinstance(actions[0], dict):
        next_action = clean_text(
            actions[0].get("nextRequiredActionZh") or actions[0].get("reasonZh"),
            next_action,
        )
    symbols = ", ".join(str(item) for item in (report.get("symbols") or [])) or "USDJPYc"
    readiness = iteration.get("readinessScore")
    metrics = [
        symbols,
        f"步骤 {passed_steps}/{len(steps)} 通过",
        f"就绪分 {readiness if readiness not in (None, '') else '—'}",
        f"GA 合格策略 {'有' if best_elite else '无'}",
    ]
    return build_digest(
        title="自动巡检",
        level=level,
        conclusion=conclusion,
        metrics=metrics,
        reasons=reasons,
        next_action=next_action,
        generated_at=report.get("generatedAt"),
    )
