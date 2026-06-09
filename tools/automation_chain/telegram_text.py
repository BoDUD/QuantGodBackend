from __future__ import annotations

from typing import Any, Dict, List


def _items(rows: List[str], max_items: int = 8) -> str:
    if not rows:
        return "- 暂无"
    shown = rows[:max_items]
    suffix = [] if len(rows) <= max_items else [f"- 其余 {len(rows) - max_items} 条已省略"]
    return "\n".join(shown + suffix)


def build_automation_telegram_text(report: Dict[str, Any]) -> str:
    status = report.get("stateZh") or report.get("state") or "未知"
    symbols = ", ".join(report.get("symbols") or []) or "未指定"
    source = report.get("singleSourceOfTruth") or "USDJPY_LIVE_LOOP"
    top_live = report.get("topLiveEligiblePolicy") or {}
    top_shadow = report.get("topShadowPolicy") or {}
    dry_run = report.get("dryRunDecision") or {}
    latency = report.get("entryLatencyReport") or {}
    latency_summary = latency.get("summary") or {}
    iteration_plan = report.get("safeIterationPlan") or {}
    ga_summary = report.get("gaFactorySummary") or iteration_plan.get("gaFactorySummary") or {}
    best_elite = ga_summary.get("bestElite") or {}
    latency_timeline = []
    for stage in latency.get("timeline", []) or []:
        latency_timeline.append(
            f"- {stage.get('labelZh', stage.get('stage'))}：{stage.get('statusZh', stage.get('status'))}"
            f"｜{stage.get('reasonZh', '')}"
        )
    iteration_actions = []
    for action in iteration_plan.get("actions", []) or []:
        iteration_actions.append(
            f"- {action.get('labelZh', action.get('actionId'))}：{action.get('nextRequiredActionZh', action.get('reasonZh', ''))}"
        )
    steps = []
    for step in report.get("steps", []):
        mark = "通过" if step.get("ok") else "未通过"
        label = step.get("labelZh") or step.get("name")
        detail = step.get("summaryZh") or step.get("reason") or ""
        steps.append(f"- {label}：{mark}" + (f"｜{detail}" if detail else ""))

    missing = [f"- {x}" for x in report.get("missingEvidence", [])]
    blockers = [f"- {x}" for x in report.get("blockedReasons", [])]
    opportunities = []
    for item in report.get("policySummary", {}).get("opportunities", []):
        opportunities.append(
            f"- {item.get('symbol')}｜{item.get('directionZh', item.get('direction'))}｜{item.get('entryModeZh', item.get('entryMode'))}｜建议仓位 {item.get('recommendedLot', 0)}｜{item.get('reason', '')}"
        )
    blocked = []
    for item in report.get("policySummary", {}).get("blocked", []):
        blocked.append(
            f"- {item.get('symbol')}｜{item.get('directionZh', item.get('direction'))}｜阻断｜{item.get('reason', '')}"
        )

    return "\n".join([
        "【QuantGod USDJPY 自动化闭环巡检】",
        "",
        f"结论：{status}",
        f"品种：{symbols}",
        f"主状态来源：{source}（USDJPY Strategy Lab + Live Loop）",
        f"生成时间：{report.get('generatedAt', '')}",
        "",
        "实盘恢复路线：",
        f"- 实盘候选：{top_live.get('strategy', '暂无')}｜{top_live.get('direction', 'UNKNOWN')}｜{top_live.get('entryMode', 'UNKNOWN')}｜建议仓位 {top_live.get('recommendedLot', 0)}",
        f"- 影子第一名：{top_shadow.get('strategy', '暂无')}｜{top_shadow.get('direction', 'UNKNOWN')}｜{top_shadow.get('entryMode', 'UNKNOWN')}",
        f"- EA 干跑：{dry_run.get('decision', '暂无')}｜{dry_run.get('strategy', 'UNKNOWN')}｜{dry_run.get('direction', 'UNKNOWN')}",
        f"- 入场慢点：{latency_summary.get('stateZh', '暂无')}｜{latency_summary.get('primaryReasonZh', '')}",
        "",
        "链路步骤：",
        _items(steps, 10),
        "",
        "入场延迟时间线：",
        _items(latency_timeline, 8),
        "",
        "下一轮安全迭代：",
        f"- 就绪分：{iteration_plan.get('readinessScore', '暂无')}｜模式：{iteration_plan.get('mode', 'SHADOW_SIMULATION_ONLY')}",
        f"- GA 精英：第 {ga_summary.get('currentGeneration', '暂无')} 代｜{best_elite.get('seedId', '暂无')}｜fitness {best_elite.get('fitness', '暂无')}｜{best_elite.get('promotionStage', 'SHADOW')}",
        _items(iteration_actions, 6),
        "",
        "缺失证据：",
        _items(missing, 8),
        "",
        "阻断原因：",
        _items(blockers, 8),
        "",
        "机会入场 / 标准入场：",
        _items(opportunities, 8),
        "",
        "当前阻断项：",
        _items(blocked, 8),
        "",
        "安全边界：本链路只生成运行证据、中文复核文本和 USDJPY 实盘恢复状态；不会下单、不会平仓、不会撤单、不会修改订单、不会修改实盘 preset。",
    ])
