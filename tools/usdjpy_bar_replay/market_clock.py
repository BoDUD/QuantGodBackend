from __future__ import annotations

from typing import Any, Dict, List


HARD_BLOCK_TOKENS = (
    "SPREAD",
    "SESSION",
    "COOLDOWN",
    "STARTUP",
    "KILL",
    "FALLBACK",
    "RUNTIME",
    "FASTLANE",
    "CAPACITY",
    "MARGIN",
)

HIGH_IMPACT_NEWS_TOKENS = (
    "BOJ",
    "FOMC",
    "CPI",
    "NFP",
    "NONFARM",
    "PAYROLL",
    "RATE DECISION",
    "INTEREST RATE",
    "POWELL",
    "UEDA",
)

TACTICAL_TOKENS = (
    "NO_CROSS",
    "WAIT",
    "BAR",
    "TACTICAL",
    "RSI",
    "CONFIRM",
    "PULLBACK",
)


def classify_gates(sample: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join(str(item or "") for item in (
        sample.get("blockReason"),
        sample.get("status"),
        sample.get("exitReason"),
    )).upper()
    raw = sample.get("raw") if isinstance(sample.get("raw"), dict) else {}
    hard: List[str] = []
    tactical: List[str] = []
    for token in HARD_BLOCK_TOKENS:
        if token in text:
            hard.append(token)
    for token in TACTICAL_TOKENS:
        if token in text:
            tactical.append(token)
    for key, token in (
        ("sessionAllowed", "SESSION"),
        ("spreadAllowed", "SPREAD"),
        ("cooldownAllowed", "COOLDOWN"),
        ("startupGuardAllowed", "STARTUP"),
        ("positionCapacityAllowed", "CAPACITY"),
    ):
        if raw.get(key) is False and token not in hard:
            hard.append(token)
    news_text = " ".join(str(item or "") for item in (
        text,
        raw.get("newsReason"),
        raw.get("newsImpact"),
        raw.get("newsEvent"),
        raw.get("eventName"),
        raw.get("impact"),
    )).upper()
    high_impact_news = any(token in news_text for token in HIGH_IMPACT_NEWS_TOKENS)
    high_impact_news = high_impact_news or str(raw.get("impact") or raw.get("newsImpact") or "").upper() in {"HIGH", "CRITICAL", "RED", "3"}
    if (raw.get("newsAllowed") is False or "NEWS" in text) and high_impact_news:
        hard.append("HIGH_IMPACT_NEWS")
    return {
        "hardBlockers": sorted(set(hard)),
        "tacticalBlockers": sorted(set(tactical)),
        "hardGatePass": not hard,
        "tacticalGatePass": not tactical,
        "newsRiskLevel": (
            "HARD"
            if "HIGH_IMPACT_NEWS" in hard
            else ("SOFT" if "NEWS" in text or raw.get("newsAllowed") is False else "NONE")
        ),
        "note": (
            "runtime、fastlane、spread、session、cooldown、startup、capacity 与高冲击新闻"
            "不会在 relaxed_entry_v1 中放宽；普通新闻只降仓/降级。"
        ),
    }
