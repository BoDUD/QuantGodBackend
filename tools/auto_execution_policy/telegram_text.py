from __future__ import annotations

from typing import Any

try:
    from telegram_digest import build_digest
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_telegram_text(document: dict[str, Any], symbol_filter: str | None = None, limit: int = 8) -> str:
    rows: list[dict[str, Any]] = list(document.get("policies", []))
    if symbol_filter:
        rows = [row for row in rows if row.get("symbol") == symbol_filter]
    summary = document.get("summary") if isinstance(document.get("summary"), dict) else {}
    blocked = int(summary.get("blocked") or sum(row.get("entryMode") == "BLOCKED" for row in rows))
    candidates = max(0, len(rows) - blocked)
    conclusion = (
        "当前策略全部保持阻断；等待数据与风险门禁恢复。"
        if rows and candidates == 0
        else f"发现 {candidates} 条候选观察；仅供本地 Shadow 复核。"
        if rows
        else "暂无策略证据；系统保持阻断。"
    )
    reasons: list[str] = []
    for row in rows[: max(1, min(limit, 3))]:
        symbol = row.get("symbol") or "未知品种"
        direction = {
            "LONG": "偏多",
            "BUY": "偏多",
            "SHORT": "偏空",
            "SELL": "偏空",
        }.get(str(row.get("direction") or "").upper(), "方向待定")
        state = "阻断" if row.get("entryMode") == "BLOCKED" else "候选观察"
        reason = _shadow_reason(row.get("reason") or (row.get("blockers") or ["等待复核"])[0])
        reasons.append(f"{symbol} {direction}｜{state}｜评分 {_fmt(row.get('score', 0))}｜{reason}")
    return build_digest(
        title="策略观察",
        level="warning" if blocked else "info",
        conclusion=conclusion,
        metrics=[f"策略 {len(rows)}", f"候选 {candidates}", f"阻断 {blocked}"],
        reasons=reasons or ["未生成可用策略行。"],
        next_action="在本地面板复核数据新鲜度、评分与风险门禁；不触发交易。",
        generated_at=document.get("generatedAt") or document.get("generatedAtIso"),
    )


def _shadow_reason(value: Any) -> str:
    text = str(value or "等待复核")
    blocked_terms = ("入场", "下单", "开仓", "平仓", "止损", "止盈", "仓位", "持仓", "目标", "place order", "execute trade", "position")
    if any(term in text.lower() for term in blocked_terms):
        return "详细策略参数已隐藏，请在本地面板复核。"
    return text
