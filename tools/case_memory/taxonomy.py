from __future__ import annotations

from typing import Any, Dict, List


REQUIRED_CASE_MEMORY_CATEGORIES = (
    "BAD_ENTRY",
    "MISSED_OPPORTUNITY",
    "EARLY_EXIT",
    "SPREAD_DAMAGE",
    "NEWS_DAMAGE",
    "GA_OVERFIT",
)

CASE_MEMORY_CATEGORY_ALIASES = {
    "BAD_ENTRY": ("BAD_ENTRY", "POOR_ENTRY", "ENTRY_QUALITY", "ADVERSE_ENTRY"),
    "MISSED_OPPORTUNITY": ("MISSED_OPPORTUNITY", "MISSEDOPPORTUNITY"),
    "EARLY_EXIT": ("EARLY_EXIT", "EARLYEXIT"),
    "SPREAD_DAMAGE": ("SPREAD_DAMAGE", "WIDE_SPREAD", "SPREAD", "SLIPPAGE", "EXECUTION_SLIPPAGE"),
    "NEWS_DAMAGE": ("NEWS_DAMAGE", "NEWS_BLOCK", "NEWS"),
    "GA_OVERFIT": ("GA_OVERFIT", "OVERFIT", "WALK_FORWARD_OVERFIT"),
}

CATEGORY_GUIDANCE_ZH = {
    "BAD_ENTRY": {
        "source": "entry-context feedback / bar replay adverse-entry audit",
        "nextActionZh": "收集入场后快速进入 MAE、低 MFE 或反向信号确认的影子/执行反馈样本。",
    },
    "MISSED_OPPORTUNITY": {
        "source": "shadow signal ledger / no-entry diagnostics / bar replay",
        "nextActionZh": "收集高分影子机会被点差、session、新闻或冷却门挡住后继续走盈利方向的样本。",
    },
    "EARLY_EXIT": {
        "source": "close-history + MFE/MAE replay / exit feedback",
        "nextActionZh": "收集平仓后仍显著顺向延续、profit-capture 偏低或 trailing 过紧的样本。",
    },
    "SPREAD_DAMAGE": {
        "source": "live execution feedback / spread gate audit",
        "nextActionZh": "继续保留滑点、宽点差和成交质量样本，用于收紧执行过滤。",
    },
    "NEWS_DAMAGE": {
        "source": "news gate replay / event impact audit",
        "nextActionZh": "收集新闻窗口内亏损、软挡失效或错过机会的回放样本。",
    },
    "GA_OVERFIT": {
        "source": "GA walk-forward / champion retest / generation stability",
        "nextActionZh": "收集训练段优秀但 forward、walk-forward 或 champion retest 失效的候选样本。",
    },
}


def case_memory_tokens_from_report(report: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text:
            tokens.append(text.upper())

    summary = report.get("caseSummary") if isinstance(report.get("caseSummary"), dict) else {}
    counts = summary.get("caseTypeCounts")
    if isinstance(counts, dict):
        for key, value in counts.items():
            try:
                count = int(value or 0)
            except (TypeError, ValueError):
                count = 0
            if count > 0:
                add(key)

    for row in summary.get("cases") if isinstance(summary.get("cases"), list) else []:
        if isinstance(row, dict):
            add(row.get("type") or row.get("caseType"))
            add(row.get("rootCause"))
            add(row.get("reasonZh"))

    for row in report.get("candidates") if isinstance(report.get("candidates"), list) else []:
        if isinstance(row, dict):
            add(row.get("caseType"))
            add(row.get("rootCause"))
            add(row.get("proposedMutation"))

    for row in report.get("gaSeeds") if isinstance(report.get("gaSeeds"), list) else []:
        if isinstance(row, dict):
            add(row.get("caseType"))
            add(row.get("mutationHint"))

    long_term = report.get("longTermTradeMemory")
    if isinstance(long_term, dict):
        for key in ("entryMemory", "exitMemory", "caseMemory", "lossLessons"):
            for row in long_term.get(key) if isinstance(long_term.get(key), list) else []:
                if isinstance(row, dict):
                    add(row.get("caseType") or row.get("memoryType") or row.get("lossTag"))
                    add(row.get("factorAttributionSummary"))

    return tokens


def case_memory_category_counts(tokens: List[str]) -> Dict[str, int]:
    counts = {category: 0 for category in REQUIRED_CASE_MEMORY_CATEGORIES}
    for token in tokens:
        normalized = str(token or "").replace("-", "_").replace(" ", "_").upper()
        for category, aliases in CASE_MEMORY_CATEGORY_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                counts[category] += 1
    return counts


def build_case_memory_coverage_plan(report: Dict[str, Any]) -> Dict[str, Any]:
    tokens = case_memory_tokens_from_report(report)
    counts = case_memory_category_counts(tokens)
    missing = [category for category, count in counts.items() if count <= 0]
    rows = []
    for category in REQUIRED_CASE_MEMORY_CATEGORIES:
        count = counts.get(category, 0)
        guidance = CATEGORY_GUIDANCE_ZH[category]
        rows.append(
            {
                "category": category,
                "status": "COVERED" if count > 0 else "MISSING",
                "observedCount": count,
                "source": guidance["source"],
                "nextActionZh": guidance["nextActionZh"],
                "allowedLanes": ["SHADOW", "TESTER_ONLY", "PAPER_LIVE_SIM"],
                "forbiddenSideEffects": [
                    "ORDER_SEND",
                    "CLOSE_POSITION",
                    "CANCEL_ORDER",
                    "LIVE_PRESET_MUTATION",
                    "WALLET_AUTHORIZATION",
                ],
            }
        )
    passed = not missing
    return {
        "schema": "quantgod.case_memory_coverage_plan.v1",
        "requiredCategories": list(REQUIRED_CASE_MEMORY_CATEGORIES),
        "categoryCounts": counts,
        "missingCategories": missing,
        "coveredCategoryCount": len(REQUIRED_CASE_MEMORY_CATEGORIES) - len(missing),
        "requiredCategoryCount": len(REQUIRED_CASE_MEMORY_CATEGORIES),
        "coverageRatio": round((len(REQUIRED_CASE_MEMORY_CATEGORIES) - len(missing)) / len(REQUIRED_CASE_MEMORY_CATEGORIES), 4),
        "status": "PASS" if passed else "BLOCKED",
        "statusZh": "Case Memory 样本类型已覆盖晋级门" if passed else "Case Memory 样本类型不足，继续只读补证",
        "promotionAllowed": passed,
        "rows": rows,
        "nextActionZh": "样本类型覆盖后再进入 GA/champion 晋级评审。" if passed else "按缺失分类补充 shadow/tester 证据，不放开真实执行。",
    }
