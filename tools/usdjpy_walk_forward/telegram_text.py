from __future__ import annotations

from typing import Any, Dict


def _line_for_candidate(item: Dict[str, Any]) -> str:
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    return (
        f"- {item.get('labelZh') or item.get('variant')}：结论 {item.get('conclusion')}，"
        f"总净变化 {summary.get('netRDelta', 0)}R，"
        f"validation {summary.get('validationNetRDelta')}R，forward {summary.get('forwardNetRDelta')}R\n"
        f"  原因：{item.get('reasonZh')}"
    )


def walk_forward_to_chinese_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    lines = [
        "【USDJPY Walk-forward 参数筛选】",
        "",
        f"状态：{payload.get('statusZh') or payload.get('status')}",
        "分段：train / validation / forward",
        "主口径：R；pips 只辅助展示；USC 不参与评分。",
        "",
        "候选稳定性：",
    ]
    if candidates:
        lines.extend(_line_for_candidate(item) for item in candidates[:6])
    else:
        lines.append("- 暂无候选，等待 P3-19 回放补样本。")
    lines.extend([
        "",
        "安全边界：",
        "- 当前仅 Shadow/ReadOnly；任何未来 live scope 都必须另行人工审核。",
        "- 不会下单、不会平仓、不会撤单、不会修改实盘 preset。",
        "- 后验结果只用于评分，不能反向决定当时是否入场。",
    ])
    return "\n".join(lines)
