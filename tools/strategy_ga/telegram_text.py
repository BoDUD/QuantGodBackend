from __future__ import annotations

from typing import Any

try:
    from telegram_digest import build_digest, clean_text
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest, clean_text


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def ga_to_chinese_text(payload: dict[str, Any]) -> str:
    status = _dict(payload.get("status"))
    generation = _dict(payload.get("generation"))
    blockers = _dict(payload.get("blockers"))
    blocker_rows = blockers.get("summary") if isinstance(blockers.get("summary"), list) else []
    population = int(status.get("populationSize") or 0)
    elite_count = int(status.get("eliteCount") or 0)
    blocked_count = int(status.get("blockedCandidates") or 0)

    reasons: list[str] = []
    for row in blocker_rows:
        if not isinstance(row, dict) or row.get("blockerCode") == "PASSED":
            continue
        reason = clean_text(row.get("reasonZh") or row.get("blockerCode"))
        reason = reason.replace("生产级 PASS", "生产验收")
        if reason:
            reasons.append(f"{reason}（{int(row.get('count') or 0)}）")
        if len(reasons) >= 2:
            break

    if elite_count <= 0:
        conclusion = "本代评估完成，但没有合格策略；不会晋级。"
        level = "warning"
        next_action = "继续下一代参数搜索，并优先修复历史数据与稳定性。"
    elif blocked_count:
        conclusion = "本代已有合格策略，但仍有候选被质量门禁阻断。"
        level = "warning"
        next_action = clean_text(status.get("nextAction"), "继续下一代验证。")
    else:
        conclusion = "本代评估完成，合格策略已进入只读验证。"
        level = "ok"
        next_action = clean_text(status.get("nextAction"), "继续积累 Shadow 证据。")

    best_fitness = status.get("bestFitness")
    try:
        fitness_text = f"{float(best_fitness):.4f}"
    except (TypeError, ValueError):
        fitness_text = "—"
    metrics = [
        f"第 {int(status.get('currentGeneration') or generation.get('generation') or 0)} 代",
        f"合格 {elite_count}/{population}",
        f"阻断 {blocked_count}",
        f"最佳评分 {fitness_text}",
    ]
    return build_digest(
        title="GA 进化",
        level=level,
        conclusion=conclusion,
        metrics=metrics,
        reasons=reasons,
        next_action=next_action,
        generated_at=generation.get("createdAt"),
    )
