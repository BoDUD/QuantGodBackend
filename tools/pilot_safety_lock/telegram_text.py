from __future__ import annotations

from typing import Any

try:
    from telegram_digest import build_digest
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest


def build_telegram_text(report: dict[str, Any]) -> str:
    symbol = str(report.get("symbol") or "UNKNOWN")
    direction = {
        "LONG": "偏多",
        "SHORT": "偏空",
    }.get(str(report.get("direction") or "").upper(), "方向待定")
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    passed = sum(bool(check.get("passed")) for check in checks if isinstance(check, dict))
    failed_checks = [
        check
        for check in checks
        if isinstance(check, dict) and not bool(check.get("passed"))
    ]
    decision = str(report.get("decisionZh") or report.get("decision") or "阻断")
    reasons = [
        f"{check.get('name') or '门禁'}：{_shadow_reason(check.get('detail') or '未通过')}"
        for check in failed_checks[:2]
    ]
    if not reasons:
        reasons = [_shadow_reason(reason) for reason in (report.get("reasons") or [])[:2]]
    if not reasons:
        reasons = ["全部结果仍需操作员在本地面板复核。"]
    return build_digest(
        title="安全门禁观察",
        level="warning" if failed_checks or decision in {"阻断", "BLOCKED"} else "info",
        conclusion=f"{symbol} {direction}｜{decision}；仅记录 Shadow 门禁结果。",
        metrics=[f"检查 {len(checks)}", f"通过 {passed}", f"未通过 {len(failed_checks)}"],
        reasons=reasons,
        next_action="在本地面板处理未通过项并重新检查；Telegram 不触发执行。",
        generated_at=report.get("generatedAt") or report.get("generatedAtIso"),
    )


def _shadow_reason(value: Any) -> str:
    text = str(value or "等待复核")
    blocked_terms = ("入场", "下单", "开仓", "平仓", "止损", "止盈", "仓位", "持仓", "目标", "place order", "execute trade", "position")
    if any(term in text.lower() for term in blocked_terms):
        return "详细策略参数已隐藏，请在本地面板复核。"
    return text
