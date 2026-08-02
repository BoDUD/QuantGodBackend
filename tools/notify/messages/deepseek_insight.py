"""Renderer for the ``deepseek_insight`` message kind.

Triggered by the Phase 1 "自动分析并推送 Telegram" button
(``POST /api/ai-analysis/deepseek-telegram/run``).

Returns **None** when the decision action is HOLD — the caller must
skip the push, not the renderer.

Distinct from ``ai_advisory``:
- 🤖 prefix instead of 🎯
- Extra "模型推理摘要" / "新闻与情绪" paragraphs
- Model attribution line at the bottom
"""

from __future__ import annotations

from typing import Any

from ._shared import (
    chinese_risk,
    fmt_pct,
    safe_truncate,
)

try:
    from telegram_digest import build_digest, sanitize_execution_language
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest, sanitize_execution_language


def render_deepseek_insight(payload: dict[str, Any]) -> str | None:
    """Render a DeepSeek-powered insight message.

    Returns:
        ``str`` for BUY/SELL; ``None`` for HOLD (meaning "do not push").
    """
    decision = payload.get("decision") or {}
    action = str(decision.get("action") or "HOLD").upper()

    # HOLD → suppress push
    if action == "HOLD":
        return None

    # ── fusion audit ────────────────────────────────────────────────
    fusion = payload.get("advisory_fusion") or payload.get("fusion") or {}
    fusion_agreement = (fusion.get("agreement") or fusion.get("finalAction") or "").strip()

    # ── resolve fields ──────────────────────────────────────────────
    symbol = str(payload.get("symbol") or "UNKNOWN")
    timeframe = str(
        payload.get("timeframe")
        or (_primary_tf(payload))
        or "M15"
    )
    confidence = decision.get("confidence") or 0
    grade = safe_truncate(
        decision.get("signalGrade") or _infer_grade(decision), 20, "B 级"
    )
    risk_raw = payload.get("risk")
    risk_val = (
        risk_raw.get("risk_level")
        if isinstance(risk_raw, dict)
        else risk_raw
    )
    risk = chinese_risk(decision.get("risk") or risk_val)

    # DeepSeek-specific enriched sections
    ds_advice = payload.get("deepseek_advice") or {}
    advice = ds_advice.get("advice") if isinstance(ds_advice.get("advice"), dict) else {}
    model = str(ds_advice.get("model") or advice.get("model") or "deepseek-v4-flash")

    market_summary = safe_truncate(
        advice.get("marketSummary")
        or advice.get("headline")
        or "技术面与基本面综合分析",
        150,
    )
    bull_case = safe_truncate(
        advice.get("bullCase") or "多方证据待确认", 160
    )
    bear_case = safe_truncate(
        advice.get("bearCase") or "空方证据待确认", 160
    )

    direction = "偏多" if action == "BUY" else "偏空"
    agreement = safe_truncate(fusion_agreement, 36, "待复核")
    market_reason = _shadow_excerpt(market_summary)
    debate_reason = _shadow_excerpt(f"多方 {bull_case}；空方 {bear_case}")
    return build_digest(
        title="DeepSeek 观察",
        level="warning",
        conclusion=f"{symbol} {timeframe} 当前{direction}；仅记录方向性 Shadow 观察。",
        metrics=[f"置信度 {fmt_pct(confidence)}", f"风险 {risk}", grade, f"模型 {model}"],
        reasons=[market_reason, f"共识 {agreement}；{debate_reason}"],
        next_action="在本地面板复核证据来源、风险门禁与多周期一致性。",
        generated_at=payload.get("generatedAt") or payload.get("generatedAtIso"),
    )


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------


def _primary_tf(payload: dict[str, Any]) -> str | None:
    tfs = payload.get("timeframes") or []
    return tfs[0] if tfs else None


def _infer_grade(decision: dict[str, Any]) -> str:
    conf = decision.get("confidence")
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


def _shadow_excerpt(value: Any) -> str:
    text = safe_truncate(value, 88, "模型未给出可用摘要")
    return sanitize_execution_language(
        text,
        "模型给出方向性信号；交易计划细节已从 Telegram 摘要中隐藏。",
    )
