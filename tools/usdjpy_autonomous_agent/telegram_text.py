from __future__ import annotations

from typing import Any, Dict


def _fmt(value: Any, fallback: str = "—") -> str:
    return fallback if value in (None, "") else str(value)


def autonomous_agent_to_chinese_text(payload: Dict[str, Any]) -> str:
    decision = payload.get("promotionDecision") if isinstance(payload.get("promotionDecision"), dict) else {}
    patch = payload.get("currentPatch") if isinstance(payload.get("currentPatch"), dict) else {}
    limits = patch.get("limits") if isinstance(patch.get("limits"), dict) else {}
    rollback = patch.get("rollback") if isinstance(patch.get("rollback"), dict) else {}
    candidates = decision.get("candidates") if isinstance(decision.get("candidates"), list) else []
    cent = payload.get("centAccount") if isinstance(payload.get("centAccount"), dict) else {}
    lanes = payload.get("lanes") if isinstance(payload.get("lanes"), dict) else {}
    mt5_shadow = lanes.get("mt5Shadow") if isinstance(lanes.get("mt5Shadow"), dict) else {}
    mt5_summary = mt5_shadow.get("summary") if isinstance(mt5_shadow.get("summary"), dict) else {}
    patch_writable = bool(payload.get("patchWritable"))
    lines = [
        "【QuantGod USDJPY 美分账户自主 Agent】",
        "",
        f"当前阶段：{_fmt(payload.get('stageZh') or payload.get('stage'))}",
        f"受控 patch：{'允许写入' if patch_writable else '未放行'}；实盘 preset 修改：禁止。",
        (
            f"账户模式：{_fmt(cent.get('accountMode'), 'cent')} / "
            f"{_fmt(cent.get('accountCurrencyUnit'), 'USC')}；"
            f"美分加速：{'开启' if cent.get('centAccountAcceleration') else '关闭'}。"
        ),
        (
            f"阶段仓位上限：{_fmt(limits.get('stageMaxLot'), '0')} / "
            f"系统上限 {_fmt(limits.get('maxLot'), '2.0')}；2.0 只是上限，不是固定仓位。"
        ),
        "审批模式：当前仅 Shadow/ReadOnly；任何未来实盘范围都必须另行人工审核。",
        "",
        "三车道：",
        "- Live：禁用；USDJPYc 仅生成 Shadow/Paper 证据。",
        (
            f"- MT5 模拟：{_fmt(mt5_summary.get('routeCount'), '0')} 条路线；"
            f"快速模拟 {_fmt(mt5_summary.get('fastShadow'), '0')}；"
            f"测试器 {_fmt(mt5_summary.get('testerOnly'), '0')}。"
        ),
        "",
        "候选参数：",
    ]
    if candidates:
        for item in candidates[:4]:
            summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
            lines.append(
                f"- {_fmt(item.get('labelZh') or item.get('variant'))}：{_fmt(item.get('autonomousStageZh'))}，"
                f"净变化 {_fmt(summary.get('netRDelta'), '0')}R"
            )
    else:
        lines.append("- 暂无候选，等待回放样本。")
    blockers = rollback.get("hardBlockers") if isinstance(rollback.get("hardBlockers"), list) else []
    lines.extend(["", "硬风控："])
    if blockers:
        lines.extend(f"- {item}" for item in blockers[:5])
    else:
        lines.append("- 当前未触发硬回滚。")
    lines.extend([
        "",
        (
            "底线：USDJPY-only；DeepSeek 只解释；"
            "Telegram 不接交易命令；Agent 只写 EA 白名单运行时 patch。"
        ),
    ])
    return "\n".join(lines)
