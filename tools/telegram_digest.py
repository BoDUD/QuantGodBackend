from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

MAX_DIGEST_CHARS = 700
SHADOW_FOOTER = "边界：永久 Shadow｜无执行通道｜Telegram 只推送、不接收命令。"
EXECUTION_DETAIL_REDACTION = "交易计划细节已隐藏，请在本地面板复核。"

_EXECUTION_LANGUAGE_PATTERNS = (
    re.compile(r"(?:立即|马上|现在|自动|建议|直接|准备)?(?:入场|下单|开仓|平仓|加仓|减仓|撤单|改单)"),
    re.compile(r"(?:止损|止盈|目标(?:价|点位)?|仓位|持仓|杠杆)"),
    re.compile(r"(?:建议|立即|马上|现在|自动|直接|准备)?(?:买入|卖出)"),
    re.compile(r"\b(?:buy|sell)\s+(?:at|now|limit|market)\b", re.IGNORECASE),
    re.compile(r"\b(?:go\s+)?(?:long|short)\s+now\b", re.IGNORECASE),
    re.compile(r"\b(?:open|close|add|reduce)\s+(?:an?\s+)?position\b", re.IGNORECASE),
    re.compile(r"\b(?:place|submit|execute|cancel|modify)\s+(?:an?\s+)?(?:order|trade)\b", re.IGNORECASE),
    re.compile(r"\b(?:stop[- ]?loss|take[- ]?profit|position\s*size|entry(?:\s+(?:zone|price))?|target(?:s|\s+price)?)\b", re.IGNORECASE),
    re.compile(r"\b(?:sl|tp)\b", re.IGNORECASE),
    re.compile(r"\b(?:\d+(?:\.\d+)?\s*)?lots?\b", re.IGNORECASE),
    re.compile(r"\bleverage\b", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+)?\s*手"),
)


def clean_text(value: Any, fallback: str = "") -> str:
    if value in (None, ""):
        return fallback
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or fallback


def contains_execution_language(value: Any) -> bool:
    text = clean_text(value)
    return bool(text and any(pattern.search(text) for pattern in _EXECUTION_LANGUAGE_PATTERNS))


def sanitize_execution_language(value: Any, fallback: str = EXECUTION_DETAIL_REDACTION) -> str:
    text = clean_text(value)
    if not text:
        return ""
    return fallback if contains_execution_language(text) else text


def sanitize_telegram_message(value: Any) -> str:
    """Redact actionable lines while preserving the surrounding status digest."""
    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    output: list[str] = []
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        safe_line = sanitize_execution_language(line) if line else ""
        if safe_line == EXECUTION_DETAIL_REDACTION and output and output[-1] == safe_line:
            continue
        output.append(safe_line)
    return "\n".join(output).strip()


def clip_text(value: Any, limit: int, fallback: str = "") -> str:
    text = clean_text(value, fallback)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip("；，,。 ") + "…"


def display_time(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        tokyo = parsed.astimezone(timezone(timedelta(hours=9)))
        return tokyo.strftime("%m-%d %H:%M JST")
    except (TypeError, ValueError):
        return clip_text(text, 32)


def _compact_items(items: Iterable[Any], *, item_limit: int, max_items: int) -> list[str]:
    output: list[str] = []
    for item in items:
        text = clip_text(sanitize_execution_language(item), item_limit)
        if text and text not in output:
            output.append(text)
        if len(output) >= max_items:
            break
    return output


def build_digest(
    *,
    title: str,
    level: str,
    conclusion: Any,
    metrics: Sequence[Any] = (),
    reasons: Sequence[Any] = (),
    next_action: Any = "",
    generated_at: Any = "",
    footer: str = SHADOW_FOOTER,
) -> str:
    icon = {
        "ok": "🟢",
        "info": "🔵",
        "warning": "🟡",
        "danger": "🔴",
    }.get(str(level).lower(), "🔵")
    lines = [
        f"{icon} QuantGod · {clip_text(sanitize_execution_language(title), 28, '状态')}",
        f"结论：{clip_text(sanitize_execution_language(conclusion), 110, '等待下一轮状态')}",
    ]
    metric_items = _compact_items(metrics, item_limit=48, max_items=4)
    if metric_items:
        lines.append("关键：" + "｜".join(metric_items))
    reason_items = _compact_items(reasons, item_limit=88, max_items=2)
    if reason_items:
        lines.append("原因：" + "；".join(reason_items))
    action = clip_text(sanitize_execution_language(next_action), 110)
    if action:
        lines.append(f"下一步：{action}")
    timestamp = display_time(generated_at)
    if timestamp:
        lines.append(f"时间：{timestamp}")
    lines.append(clip_text(footer, 64, SHADOW_FOOTER))
    message = "\n".join(lines)
    if len(message) <= MAX_DIGEST_CHARS:
        return message
    # Field-level limits above should normally keep messages below this cap.
    # Preserve both the conclusion and safety footer if unexpected input grows.
    available = MAX_DIGEST_CHARS - len(footer) - 2
    return message[:available].rstrip() + "…\n" + footer
