from __future__ import annotations

from typing import Any

from .schema import bool_zh, direction_zh, entry_mode_zh


def live_loop_to_chinese_text(payload: dict[str, Any]) -> str:
    top = payload.get("topShadowPolicy") or payload.get("topPolicy") or {}
    shadow = payload.get("topShadowPolicy") or {}
    preset = payload.get("preset") or {}
    runtime = payload.get("runtime") or {}
    lines = [
        "【QuantGod USDJPY Shadow Advisory 闭环】",
        "",
        f"结论：{payload.get('stateZh', '未知')}",
        f"观察范围：{payload.get('advisoryRouteZh', '所有策略仅做 Shadow/ReadOnly 复核')}",
        "",
        "当前优先策略：",
        f"- 策略：{top.get('strategy', 'UNKNOWN')}",
        f"- 方向：{direction_zh(top.get('direction'))}",
        f"- 状态：{entry_mode_zh(top.get('entryMode'))}",
        f"- 研究仓位参数：{float(top.get('recommendedLot') or 0):.2f}（不用于 broker execution）",
        "",
        "现场证据：",
        f"- 运行快照：{bool_zh(runtime.get('ready'))}",
        f"- Shadow/ReadOnly preset：{bool_zh(preset.get('ready'))}",
        "- executionLaneExists=false；现有 EA 不拥有执行权限",
    ]
    if shadow and shadow != top:
        lines.extend([
            "",
            "影子研究第一名：",
            f"- {shadow.get('strategy', 'UNKNOWN')}｜{direction_zh(shadow.get('direction'))}｜{entry_mode_zh(shadow.get('entryMode'))}",
            "- 影子第一名只用于研究与证据复核。",
        ])
    why = payload.get("whyNoEntry") or []
    if why:
        lines.extend(["", "为什么没有入场："])
        lines.extend(f"- {item}" for item in why[:6])
    actions = payload.get("nextActions") or []
    if actions:
        lines.extend(["", "下一步自动动作："])
        lines.extend(f"- {item}" for item in actions[:5])
    lines.extend([
        "",
        "安全边界：",
        "- 本消息只说明 Shadow/ReadOnly 研究证据是否完整。",
        "- 系统不存在执行通道，不会下单、平仓、撤单或修改 broker 状态。",
    ])
    return "\n".join(lines)
