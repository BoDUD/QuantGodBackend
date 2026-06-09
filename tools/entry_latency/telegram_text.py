from __future__ import annotations

from typing import Any, Dict, List


def _items(rows: List[str], limit: int = 8) -> str:
    if not rows:
        return "- 暂无"
    shown = rows[:limit]
    if len(rows) > limit:
        shown.append(f"- 其余 {len(rows) - limit} 条已省略")
    return "\n".join(shown)


def build_telegram_text(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    latency = report.get("latency") or {}
    timeline = report.get("timeline") or []
    blockers = report.get("blockers") or []
    lines = []
    for stage in timeline:
        lines.append(
            f"- {stage.get('labelZh', stage.get('stage'))}：{stage.get('statusZh', stage.get('status'))}"
            f"｜年龄 {stage.get('ageSeconds', '—')}s｜{stage.get('reasonZh', '')}"
        )
    blocker_lines = [
        f"- {item.get('labelZh')}：{item.get('reasonZh')}"
        for item in blockers
        if item.get("reasonZh")
    ]
    return "\n".join([
        "【QuantGod USDJPY 入场延迟归因】",
        "",
        f"结论：{summary.get('stateZh', '未知')}｜{summary.get('state', 'UNKNOWN')}",
        f"主因：{summary.get('primaryReasonZh', '暂无')}",
        f"启动保护：{'开启中' if summary.get('startupGuardActive') else '未阻断'}；点差：{summary.get('spreadPips', '未知')}",
        "",
        "时间线：",
        _items(lines, 8),
        "",
        "延迟读数：",
        f"- 快通道到政策：{latency.get('marketDataToPolicyMs', '—')} ms",
        f"- 政策到 EA：{latency.get('policyToEaMs', '—')} ms",
        f"- EA 到订单尝试：{latency.get('eaToOrderAttemptMs', '—')} ms",
        "",
        "阻断/慢点：",
        _items(blocker_lines, 8),
        "",
        "安全边界：本报告只读取本地证据并归因慢点；不会下单、平仓、撤单、改单或修改实盘 preset。",
    ])
