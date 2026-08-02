from __future__ import annotations

from typing import Any

try:
    from telegram_digest import build_digest, clean_text
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest, clean_text


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any, digits: int = 2, fallback: str = "—") -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return fallback


def _stage_label(live: dict[str, Any]) -> str:
    stage = str(live.get("stage") or "").upper()
    stage_zh = clean_text(live.get("stageZh"))
    if stage == "TESTER_ONLY" or "测试器" in stage_zh:
        return "测试器验证"
    if "SHADOW" in stage or "影子" in stage_zh:
        return "Shadow 验证"
    if "PAPER" in stage or "模拟" in stage_zh:
        return "模拟验证"
    return stage_zh or "只读验证"


def daily_autopilot_v2_to_chinese_text(payload: dict[str, Any]) -> str:
    morning = _dict(payload.get("morningPlan"))
    evening = _dict(payload.get("eveningReview"))
    live = _dict(morning.get("liveLane"))
    mt5_summary = _dict(_dict(morning.get("mt5ShadowLane")).get("summary"))
    spread_gate = _dict(morning.get("spreadGate"))
    consistency = _dict(payload.get("executionConsistencyReview"))
    ga_review = _dict(payload.get("gaReview"))
    history = _dict(payload.get("historyProductionStatus")) or _dict(ga_review.get("historyProductionStatus"))

    history_gate = str(history.get("promotionGateStatus") or "BLOCKED").upper()
    parity_gate = str(consistency.get("parityGateStatus") or "MISSING").upper()
    elite_count = int(ga_review.get("eliteCount") or 0)
    blocked_count = int(ga_review.get("blockedCandidates") or 0)

    reasons: list[str] = []
    if history_gate != "PASS":
        timeframes = _dict(history.get("timeframes"))
        failed_timeframes = [
            str(name)
            for name, row in timeframes.items()
            if isinstance(row, dict) and not bool(row.get("passed"))
        ]
        if failed_timeframes:
            reasons.append(f"{'/'.join(failed_timeframes[:4])} 最新 K 线已过期或不完整。")
        else:
            reasons.append("USDJPY 历史数据未通过新鲜度和完整性验收。")
    if parity_gate != "PASS":
        reasons.append("策略与 EA 一致性证据尚未通过。")
    if blocked_count:
        reasons.append(f"本代 {blocked_count} 个 GA 候选被质量门禁阻断。")

    if history_gate != "PASS":
        conclusion = "继续 Shadow 观察；历史数据尚未通过生产验收。"
        next_action = "刷新 M1/M5/M15/H1 历史数据，再重新运行 GA 验证。"
        level = "warning"
    elif elite_count <= 0:
        conclusion = "继续 Shadow 观察；GA 尚未产生合格策略。"
        next_action = "继续下一代参数搜索，并复核主要阻断原因。"
        level = "warning"
    elif parity_gate != "PASS":
        conclusion = "继续 Shadow 观察；策略一致性证据尚未达标。"
        next_action = "刷新 Strategy JSON 与 EA 一致性证据。"
        level = "warning"
    else:
        conclusion = "只读自动链路运行正常，继续积累验证证据。"
        next_action = clean_text(ga_review.get("nextAction"), "等待下一轮自动复核。")
        level = "ok"

    symbol = clean_text(payload.get("symbol") or live.get("symbol"), "USDJPYc")
    spread = _number(spread_gate.get("spreadPips"), 2)
    generation = int(ga_review.get("currentGeneration") or 0)
    metrics = [
        f"{symbol} / {_stage_label(live)}",
        f"点差 {spread} pips",
        f"模拟路线 {int(mt5_summary.get('routeCount') or 0)}",
        f"GA 第 {generation} 代 / 合格策略 {elite_count}",
    ]
    generated_at = payload.get("generatedAtIso") or payload.get("timestamp") or evening.get("generatedAtIso")
    return build_digest(
        title="每日状态",
        level=level,
        conclusion=conclusion,
        metrics=metrics,
        reasons=reasons,
        next_action=next_action,
        generated_at=generated_at,
    )
