from __future__ import annotations

from typing import Any, Dict, List

from .schema import ENTRY_BLOCKED, ENTRY_OPPORTUNITY, ENTRY_STANDARD, FOCUS_SYMBOL, direction_cn, status_cn


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "0.0%"


def _num(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "0.00"


def policy_to_chinese_text(policy: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("【QuantGod USDJPY 单品种多策略审查】")
    lines.append("")
    lines.append("研究范围：仅 USDJPYc")
    lines.append("其他品种：已忽略，不参与 Shadow 研究或 Telegram 主报告。")
    lines.append("")
    lines.append("总体结论：")
    lines.append(f"- 标准入场候选：{policy.get('standardEntryCount', 0)}")
    lines.append(f"- 机会入场候选：{policy.get('opportunityEntryCount', 0)}")
    lines.append(f"- 阻断策略方向：{policy.get('blockedCount', 0)}")
    lines.append(f"- 最高允许仓位：{_num(policy.get('maxLot', 2.0))}")
    lines.append("")
    top = policy.get("topShadowPolicy") or policy.get("topPolicy") or policy.get("liveRecoveryCandidate") or {}
    if top:
        lines.append("当前 Shadow advisory 路线：")
        lines.append(f"- 策略：{top.get('strategy', 'UNKNOWN')}")
        lines.append(f"- 方向：{direction_cn(top.get('direction'))}")
        lines.append(f"- 状态：{status_cn(top.get('entryMode'))}")
        lines.append(f"- 研究仓位参数：{_num(top.get('recommendedLot', 0.0))}（不用于 broker execution）")
        lines.append(f"- 评分：{_num(top.get('score', 0.0), 1)}")
        reasons = top.get("reasons") or []
        if reasons:
            lines.append("- 原因：" + "；".join(str(r) for r in reasons[:4]))
        lines.append("")
    shadow = policy.get("topShadowPolicy") or {}
    if shadow and shadow != top:
        lines.append("影子研究第一名：")
        lines.append(f"- {shadow.get('strategy', 'UNKNOWN')}｜{direction_cn(shadow.get('direction'))}｜{status_cn(shadow.get('entryMode'))}｜评分 {_num(shadow.get('score', 0.0), 1)}")
        lines.append("- 说明：影子第一名仅用于研究与证据复核。")
        lines.append("")
    lines.append("策略排名：")
    strategies = policy.get("strategies") or []
    for idx, item in enumerate(strategies[:8], start=1):
        lines.append(
            f"{idx}. {item.get('strategy', 'UNKNOWN')}｜{direction_cn(item.get('direction'))}｜"
            f"{status_cn(item.get('entryMode'))}｜建议仓位 {_num(item.get('recommendedLot', 0.0))}｜评分 {_num(item.get('score', 0.0), 1)}"
        )
        reasons = item.get("reasons") or []
        if reasons:
            lines.append(f"   原因：{'；'.join(str(r) for r in reasons[:2])}")
    if not strategies:
        lines.append("- 暂无 USDJPY 策略政策，请先生成样本和运行快照。")
    lines.append("")
    evidence = policy.get("evidence") or {}
    lines.append("证据链：")
    lines.append(f"- 运行快照：{'通过' if evidence.get('runtimeOk') else '缺失或未通过'}")
    lines.append(f"- 快通道质量：{'通过' if evidence.get('fastlaneOk') else '缺失或未通过'}")
    lines.append(f"- 入场触发计划：{'已找到' if evidence.get('triggerPlanFound') else '缺失'}")
    lines.append(f"- 动态止盈止损：{'已找到' if evidence.get('dynamicSltpFound') else '缺失'}")
    lines.append("")
    lines.append("安全边界：")
    lines.append("- executionLaneExists=false；现有 EA 不拥有执行权限。")
    lines.append("- 本工具只生成 USDJPY 策略政策和 EA 干跑证据。")
    lines.append("- 不会下单、不会平仓、不会撤单、不会修改订单。")
    lines.append("- 不会修改 tracked preset，不会写 MT5 OrderRequest。")
    return "\n".join(lines)


def dry_run_to_chinese_text(decision: Dict[str, Any]) -> str:
    lines = [
        "【QuantGod USDJPY EA 干跑决策】",
        "",
        "说明：本消息只记录 EA 如果读取政策时会如何判断，不会真实下单。",
        "",
        f"品种：{decision.get('symbol', FOCUS_SYMBOL)}",
        f"决策：{decision.get('decision', '阻断')}",
        f"策略：{decision.get('strategy', 'UNKNOWN')}",
        f"方向：{direction_cn(decision.get('direction'))}",
        f"建议仓位：{_num(decision.get('recommendedLot', 0.0))} / 上限 {_num(decision.get('maxLot', 2.0))}",
    ]
    reasons = decision.get("reasons") or []
    if reasons:
        lines.append("原因：" + "；".join(str(r) for r in reasons[:5]))
    lines.extend([
        "",
        "安全边界：",
        "- 干跑不会触发 OrderSend。",
        "- 干跑不会修改 SL/TP 或 live preset。",
    ])
    return "\n".join(lines)
