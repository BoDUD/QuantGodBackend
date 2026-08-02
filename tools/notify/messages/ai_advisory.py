"""Renderer for the ``ai_advisory`` message kind.

Triggered by the Phase 2 "AI 分析并推送" button
(``POST /api/notify/mt5-ai-monitor/run``).

Returns **None** when the decision action is HOLD — the caller must
skip the push, not the renderer.
"""

from __future__ import annotations

from typing import Any

from ._shared import (
    chinese_risk,
    fmt_pct,
    safe_truncate,
)

try:
    from telegram_digest import build_digest
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest


def render_ai_advisory(payload: dict[str, Any]) -> str | None:
    """Render a local AI advisory message.

    Returns:
        ``str`` for BUY/SELL; ``None`` for HOLD (meaning "do not push").
    """
    decision = payload.get("decision") or {}
    # Backward-compat: accept root-level action/confidence/risk as fallback
    # (used by _event_payload_from_analysis in notify_service.py)
    action = str(
        decision.get("action")
        or payload.get("action")
        or "HOLD"
    ).upper()

    # HOLD → suppress push
    if action == "HOLD":
        return None

    # ── fusion audit ────────────────────────────────────────────────
    fusion = payload.get("advisory_fusion") or payload.get("fusion") or {}
    fusion_agreement = (fusion.get("agreement") or fusion.get("finalAction") or "").strip()

    # ── resolve fields (decision.* first, then root-level fallback) ──
    symbol = str(payload.get("symbol") or "UNKNOWN")
    timeframe = str(
        payload.get("timeframe")
        or _primary_tf(payload)
        or "M15"
    )
    confidence = (
        decision.get("confidence")
        or payload.get("confidence")
        or 0
    )
    grade = safe_truncate(
        decision.get("signalGrade") or _infer_grade(decision, payload), 20, "B 级"
    )
    risk_raw = payload.get("risk")
    risk_val = (
        risk_raw.get("risk_level")
        if isinstance(risk_raw, dict)
        else risk_raw
    )
    risk = chinese_risk(decision.get("risk") or risk_val)

    direction = "偏多" if action == "BUY" else "偏空"
    agreement = safe_truncate(fusion_agreement, 36, "待复核")
    return build_digest(
        title="AI 观察",
        level="warning",
        conclusion=f"{symbol} {timeframe} 当前{direction}；仅记录方向性 Shadow 观察。",
        metrics=[f"置信度 {fmt_pct(confidence)}", f"风险 {risk}", grade, f"共识 {agreement}"],
        reasons=["本地模型与风险证据完成只读汇总；交易计划字段不进入 Telegram。"],
        next_action="在本地面板复核快照新鲜度、风险门禁与多周期一致性。",
        generated_at=payload.get("generatedAt") or payload.get("generatedAtIso"),
    )


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------


def _primary_tf(payload: dict[str, Any]) -> str | None:
    tfs = payload.get("timeframes") or []
    return tfs[0] if tfs else None


def _infer_grade(decision: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    conf = decision.get("confidence") or (payload or {}).get("confidence")
    try:
        c = float(conf)  # type: ignore[arg-type]
        if c <= 1:
            c *= 100
        if c >= 75:
            return "A 级"
        if c >= 60:
            return "B 级"
        return "C 级"
    except (TypeError, ValueError):
        return "B 级"
