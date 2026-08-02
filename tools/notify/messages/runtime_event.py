"""Renderer for the ``runtime_event`` message kind.

Dispatches on ``_event_type`` (or ``event_type``) inside the payload to
the appropriate sub-renderer: KILL_SWITCH, NEWS_BLOCK, CONSECUTIVE_LOSS,
RISK_THRESHOLD, GOVERNANCE, TRADE_OPEN, TRADE_CLOSE, or a generic fallback.

Triggered by ``POST /api/notify/runtime-scan`` (Phase 2 "普通扫描演练" button).
"""

from __future__ import annotations

from typing import Any

from ._shared import chinese_risk, fmt_money, fmt_time_tokyo, safe_truncate


def render_runtime_event(payload: dict[str, Any]) -> str:
    """Dispatch to the correct sub-renderer based on ``_event_type``."""
    event_type = str(
        payload.get("_event_type") or payload.get("event_type") or "GENERIC"
    ).upper()
    handler = _HANDLERS.get(event_type, _render_generic)
    return handler(payload)


# ---------------------------------------------------------------------------
# Sub-renderers
# ---------------------------------------------------------------------------


def _render_kill_switch(p: dict[str, Any]) -> str:
    return "\n".join(
        [
            "⛔ Kill Switch 触发",
            f"原因：{safe_truncate(p.get('reason'), 60, '未知')}",
            f"当日盈亏：{fmt_money(p.get('pnl') or p.get('dailyPnl') or 0)}",
            f"恢复条件：{safe_truncate(p.get('recovery'), 80, '手动复核 + 第二日 09:00 重置')}",
        ]
    )


def _render_news_block(p: dict[str, Any]) -> str:
    phase = p.get("phase") or ""
    phase_display = f"｜阶段：{phase}" if phase else ""
    actual = p.get("actual")
    forecast = p.get("forecast")
    previous = p.get("previous")
    data_line_parts = []
    if actual is not None:
        data_line_parts.append(f"实际 {actual}")
    if forecast is not None:
        data_line_parts.append(f"预期 {forecast}")
    if previous is not None:
        data_line_parts.append(f"前值 {previous}")
    data_line = "｜" + " / ".join(data_line_parts) if data_line_parts else ""
    lines = [
        "\U0001f4f0 高影响新闻预警",
        f"事件：{safe_truncate(p.get('label') or p.get('event'), 50, '跟踪事件')}{phase_display}",
        f"距离：{p.get('eta') or '--'} 分钟",
        f"本地风控已标记为阻断{data_line}",
    ]
    reason = p.get("reason")
    if reason:
        lines.append(f"原因：{safe_truncate(reason, 80)}")
    return "\n".join(lines)


def _render_consecutive_loss(p: dict[str, Any]) -> str:
    return "\n".join(
        [
            "⚠️ 连亏暂停",
            f"连续：{p.get('losses') or '--'} 次｜今日累计 {fmt_money(p.get('todayPnl') or 0)}",
            f"冷却期：{p.get('cooldown') or '--'} 分钟（恢复时刻 {p.get('resumeAt') or '--'}）",
        ]
    )


def _render_risk_threshold(p: dict[str, Any]) -> str:
    return "\n".join(
        [
            "\U0001f7e1 风险阈值预警",
            f"指标：{safe_truncate(p.get('metric'), 40, '未指定')}",
            f"当前值：{p.get('value') or '--'}｜阈值：{p.get('threshold') or '--'}",
            f"风险等级：{chinese_risk(p.get('risk_level'))}",
        ]
    )


def _render_governance(p: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"\U0001f6e1️ 治理动作 — {safe_truncate(p.get('route'), 30, '全局')}",
            f"动作：{safe_truncate(p.get('action'), 40, '复核')}",
            f"原因：{safe_truncate(p.get('reason'), 80, '治理证据更新')}",
        ]
    )


def _render_trade_open(p: dict[str, Any]) -> str:
    side_raw = str(p.get("side") or "").upper()
    side_zh = "做多" if side_raw in ("BUY", "LONG") else "做空"
    return "\n".join(
        [
            f"🟡 观察到持仓新增 — {p.get('symbol') or '?'} {side_zh}",
            f"数量 {p.get('lots') or '—'}｜成交价 {p.get('price') or '--'}",
            f"止损 {p.get('sl') or '--'}｜止盈 {p.get('tp') or '--'}",
            f"路由：{p.get('route') or '--'}｜东京时间 {fmt_time_tokyo()}",
            "只读观察｜QuantGod 未发送此订单",
        ]
    )


def _render_trade_close(p: dict[str, Any]) -> str:
    pnl_str = fmt_money(p.get("pnl") or p.get("profit") or 0)
    return "\n".join(
        [
            f"🟡 观察到持仓结束 — {p.get('symbol') or '?'}",
            f"盈亏 {pnl_str}｜持仓时长 {p.get('duration') or '--'}",
            f"结束于 {fmt_time_tokyo()}",
            "只读观察｜QuantGod 未执行此平仓",
        ]
    )


def _render_generic(p: dict[str, Any]) -> str:
    summary = safe_truncate(
        p.get("summary") or p.get("message"), 100, "事件已记录"
    )
    return f"ℹ️ QuantGod 事件\n{summary}"


_HANDLERS: dict[str, Any] = {
    "KILL_SWITCH": _render_kill_switch,
    "NEWS_BLOCK": _render_news_block,
    "CONSECUTIVE_LOSS": _render_consecutive_loss,
    "RISK_THRESHOLD": _render_risk_threshold,
    "GOVERNANCE": _render_governance,
    "TRADE_OPEN": _render_trade_open,
    "TRADE_CLOSE": _render_trade_close,
}
