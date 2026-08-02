"""QuantGod Telegram message renderer registry.

All Telegram text generation is centralised here.  Callers import
``render(kind, payload)`` and never construct message strings by hand.

``kind`` is one of:

===============  ====================================================
ai_advisory      Local AI advisor (Phase 2 "AI 分析并推送")
deepseek_insight  DeepSeek model insight (Phase 1 "DeepSeek 推送")
daily_digest     Daily recap (Phase 2 "推送每日摘要")
runtime_event    Runtime scan event (Phase 2 "普通扫描演练")
test             Channel connectivity test
===============  ====================================================

Returns:
    - ``str``: the Telegram-ready message text (always ≤ 4096 chars).
    - ``None``: the renderer decided this payload should NOT be pushed
      (e.g. action=HOLD for advisory kinds).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .ai_advisory import render_ai_advisory
from .daily_digest import render_daily_digest
from .deepseek_insight import render_deepseek_insight
from .runtime_event import render_runtime_event
from .test import render_test

RENDERERS: dict[str, Callable[[dict[str, Any]], Optional[str]]] = {
    "ai_advisory": render_ai_advisory,
    "deepseek_insight": render_deepseek_insight,
    "daily_digest": render_daily_digest,
    "runtime_event": render_runtime_event,
    "test": render_test,
}

# Used by golden-file tests to assert prefix uniqueness across kinds.
KIND_TITLE_PREFIX: dict[str, str] = {
    "ai_advisory": "🟡 QuantGod · AI 观察",
    "deepseek_insight": "🟡 QuantGod · DeepSeek 观察",
    "daily_digest": "\U0001f4ca 今日复盘",
    "runtime_event:KILL_SWITCH": "⛔ Kill Switch",
    "runtime_event:NEWS_BLOCK": "\U0001f4f0 高影响新闻",
    "runtime_event:CONSECUTIVE_LOSS": "⚠️ 连亏暂停",
    "runtime_event:RISK_THRESHOLD": "\U0001f7e1 风险阈值",
    "test": "\U0001f9ea QuantGod 通道测试",
}

TELEGRAM_MAX_CHARS = 4096


def render(kind: str, payload: dict[str, Any]) -> Optional[str]:
    """Generate a Telegram text message for the given *kind* and *payload*.

    Guarantees:
        - Never raises — any downstream renderer exception is caught and
          converted into a short fallback message.
        - Output never exceeds ``TELEGRAM_MAX_CHARS`` (4096).
    """
    renderer = RENDERERS.get(kind)
    if renderer is None:
        return f"ℹ️ QuantGod 未知通知类型：{kind}"

    try:
        text = renderer(dict(payload or {}))
    except Exception as exc:
        # Fail-safe: a message module crash must not kill the monitor.
        return (
            f"ℹ️ QuantGod 通知渲染失败（{kind}）："
            f"{type(exc).__name__}"
        )

    if text is None:
        return None

    if len(text) > TELEGRAM_MAX_CHARS:
        text = text[: TELEGRAM_MAX_CHARS - 6] + "\n…"

    return text
