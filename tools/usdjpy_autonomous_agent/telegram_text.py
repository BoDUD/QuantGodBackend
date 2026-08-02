from __future__ import annotations

from typing import Any

try:
    from telegram_digest import build_digest, clean_text
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest, clean_text


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _stage_label(payload: dict[str, Any]) -> str:
    stage = str(payload.get("stage") or "").upper()
    stage_zh = clean_text(payload.get("stageZh"))
    if stage == "TESTER_ONLY" or "测试器" in stage_zh:
        return "测试器验证"
    if "SHADOW" in stage or "影子" in stage_zh:
        return "Shadow 验证"
    if "PAPER" in stage or "模拟" in stage_zh:
        return "模拟验证"
    return stage_zh or "只读验证"


def autonomous_agent_to_chinese_text(payload: dict[str, Any]) -> str:
    decision = _dict(payload.get("promotionDecision"))
    patch = _dict(payload.get("currentPatch"))
    rollback = _dict(patch.get("rollback"))
    candidates = decision.get("candidates") if isinstance(decision.get("candidates"), list) else []
    mt5_summary = _dict(_dict(_dict(payload.get("lanes")).get("mt5Shadow")).get("summary"))
    blockers = rollback.get("hardBlockers") if isinstance(rollback.get("hardBlockers"), list) else []

    if blockers:
        conclusion = "硬风控已触发，Agent 保持只读并停止候选推进。"
        level = "danger"
        reasons = [clean_text(item) for item in blockers[:2]]
        next_action = "等待证据修复后由下一轮 Agent 自动复核。"
    else:
        conclusion = "Agent 运行正常；当前仅做测试器与 Shadow 验证。"
        level = "ok"
        reasons = ["未触发硬回滚；系统没有订单执行通道。"]
        next_action = "继续收集回放样本和策略一致性证据。"

    metrics = [
        f"{clean_text(payload.get('symbol'), 'USDJPYc')} / {_stage_label(payload)}",
        f"模拟路线 {int(mt5_summary.get('routeCount') or 0)}",
        f"候选策略 {len(candidates)}",
        f"暂停路线 {int(mt5_summary.get('paused') or 0)}",
    ]
    return build_digest(
        title="策略 Agent",
        level=level,
        conclusion=conclusion,
        metrics=metrics,
        reasons=reasons,
        next_action=next_action,
        generated_at=payload.get("generatedAtIso"),
    )
