from __future__ import annotations

from typing import Any, Dict


def _fmt(value: Any, default: str = "—") -> str:
    if value in (None, ""):
        return default
    return str(value)


def ga_to_chinese_text(payload: Dict[str, Any]) -> str:
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    generation = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), dict) else {}
    blocker_rows = blockers.get("summary") if isinstance(blockers.get("summary"), list) else []
    lines = [
        "【QuantGod GA 进化报告】",
        "",
        f"当前代数：第 {_fmt(status.get('currentGeneration'), '0')} 代",
        f"种群数量：{_fmt(status.get('populationSize'), '0')}",
        f"最佳策略：{_fmt(status.get('bestSeedId'))}",
        f"最佳分数：{_fmt(status.get('bestFitness'), '0')}",
        f"Elite：{_fmt(status.get('eliteCount'), '0')}",
        f"淘汰/阻断：{_fmt(status.get('blockedCandidates'), '0')}",
        f"状态：{_fmt(generation.get('status') or status.get('status'))}",
        "",
        "主要阻断：",
    ]
    for row in blocker_rows[:6]:
        if isinstance(row, dict) and row.get("blockerCode") != "PASSED":
            lines.append(f"- {_fmt(row.get('reasonZh') or row.get('blockerCode'))}：{_fmt(row.get('count'), '0')}")
    if len(lines) <= 10:
        lines.append("- 暂无主要阻断")
    lines.extend([
        "",
        f"下一步：{_fmt(status.get('nextAction'), '继续下一代 Strategy JSON 评分')}",
        "",
        "安全边界：GA 只生成 Strategy JSON、进入 shadow/tester/paper-live-sim。",
        "不直接实盘，不改 live preset，不接 crypto 执行授权，不接 Telegram 交易命令。",
    ])
    return "\n".join(lines)
