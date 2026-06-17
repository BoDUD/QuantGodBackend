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
    "BAD_ENTRY": (
        "BAD_ENTRY",
        "POOR_ENTRY",
        "ENTRY_QUALITY",
        "ADVERSE_ENTRY",
        "CHASE_PULLBACK",
        "FAKE_BREAKOUT",
        "FAST_LOSS",
        "ULTRA_FAST_LOSS",
    ),
    "MISSED_OPPORTUNITY": ("MISSED_OPPORTUNITY", "MISSEDOPPORTUNITY", "MISSED_BIG_MOVE"),
    "EARLY_EXIT": ("EARLY_EXIT", "EARLYEXIT", "PROFIT_GIVEBACK", "LOW_MFE_CAPTURE", "RECOVERED_TO_SMALL_WIN"),
    "SPREAD_DAMAGE": ("SPREAD_DAMAGE", "WIDE_SPREAD", "SPREAD", "SLIPPAGE", "EXECUTION_SLIPPAGE"),
    "NEWS_DAMAGE": ("NEWS_DAMAGE", "NEWS_BLOCK", "NEWS_ADVERSE", "HIGH_IMPACT_NEWS"),
    "GA_OVERFIT": ("GA_OVERFIT", "OVERFIT", "OVERFIT_RISK", "WALK_FORWARD_OVERFIT", "WALK_FORWARD_UNSTABLE"),
}

CATEGORY_GUIDANCE_ZH = {
    "BAD_ENTRY": {
        "priority": "HIGH",
        "targetCount": 3,
        "source": "entry-context feedback / bar replay adverse-entry audit",
        "sourceArtifacts": [
            "replay/usdjpy/QuantGod_USDJPYBarReplayReport.json",
            "execution/QuantGod_LiveExecutionFeedback.jsonl",
            "evidence_os/QuantGod_LiveExecutionFeedback.jsonl",
        ],
        "collectionEndpoint": "/api/usdjpy-strategy-lab/evidence-os/execution-feedback",
        "collectionCommand": "python3 tools/run_live_execution_feedback.py --runtime-dir ./runtime build --write",
        "caseMemoryBuildCommand": "python3 tools/run_case_memory.py --runtime-dir ./runtime build --write --limit 8",
        "verifyCommand": "python3 tools/run_runtime_evidence_integrity.py --runtime-dir ./runtime verify",
        "nextActionZh": "收集入场后快速进入 MAE、低 MFE 或反向信号确认的影子/执行反馈样本。",
        "acceptanceZh": "至少 3 条含 entryContext、MAE/MFE、入场原因和后续走势的 shadow/tester 样本。",
    },
    "MISSED_OPPORTUNITY": {
        "priority": "HIGH",
        "targetCount": 3,
        "source": "shadow signal ledger / no-entry diagnostics / bar replay",
        "sourceArtifacts": [
            "replay/usdjpy/QuantGod_USDJPYBarReplayReport.json",
            "QuantGod_USDJPYRsiEntryDiagnostics.json",
            "QuantGod_ShadowSignalLedger.csv",
        ],
        "collectionEndpoint": "/api/usdjpy-strategy-lab/bar-replay/entry",
        "collectionCommand": "python3 tools/run_usdjpy_bar_replay.py --runtime-dir ./runtime entry --write",
        "caseMemoryBuildCommand": "python3 tools/run_case_memory.py --runtime-dir ./runtime build --write --limit 8",
        "verifyCommand": "python3 tools/run_runtime_evidence_integrity.py --runtime-dir ./runtime verify",
        "nextActionZh": "收集高分影子机会被点差、session、新闻或冷却门挡住后继续走盈利方向的样本。",
        "acceptanceZh": "至少 3 条有 shadow signal、阻断原因和后续盈利方向 replay 的 missed-entry 样本。",
    },
    "EARLY_EXIT": {
        "priority": "MEDIUM",
        "targetCount": 3,
        "source": "close-history + MFE/MAE replay / exit feedback",
        "sourceArtifacts": [
            "replay/usdjpy/QuantGod_USDJPYBarReplayReport.json",
            "QuantGod_CloseHistory.csv",
            "execution/QuantGod_LiveExecutionFeedback.jsonl",
        ],
        "collectionEndpoint": "/api/usdjpy-strategy-lab/bar-replay/exit",
        "collectionCommand": "python3 tools/run_usdjpy_bar_replay.py --runtime-dir ./runtime exit --write",
        "caseMemoryBuildCommand": "python3 tools/run_case_memory.py --runtime-dir ./runtime build --write --limit 8",
        "verifyCommand": "python3 tools/run_runtime_evidence_integrity.py --runtime-dir ./runtime verify",
        "nextActionZh": "收集平仓后仍显著顺向延续、profit-capture 偏低或 trailing 过紧的样本。",
        "acceptanceZh": "至少 3 条含 exit reason、MFE giveback、profit-capture ratio 的早出场 replay 样本。",
    },
    "SPREAD_DAMAGE": {
        "priority": "MEDIUM",
        "targetCount": 3,
        "source": "live execution feedback / spread gate audit",
        "sourceArtifacts": [
            "execution/QuantGod_LiveExecutionFeedback.jsonl",
            "evidence_os/QuantGod_LiveExecutionQualityReport.json",
            "QuantGod_USDJPYRsiEntryDiagnostics.json",
        ],
        "collectionEndpoint": "/api/usdjpy-strategy-lab/evidence-os/execution-feedback",
        "collectionCommand": "python3 tools/run_live_execution_feedback.py --runtime-dir ./runtime build --write",
        "caseMemoryBuildCommand": "python3 tools/run_case_memory.py --runtime-dir ./runtime build --write --limit 8",
        "verifyCommand": "python3 tools/run_runtime_evidence_integrity.py --runtime-dir ./runtime verify",
        "nextActionZh": "继续保留滑点、宽点差和成交质量样本，用于收紧执行过滤。",
        "acceptanceZh": "至少 3 条含 spread/slippage、成交质量和结果影响的执行反馈样本。",
    },
    "NEWS_DAMAGE": {
        "priority": "MEDIUM",
        "targetCount": 2,
        "source": "news gate replay / event impact audit",
        "sourceArtifacts": [
            "replay/usdjpy/QuantGod_USDJPYNewsGateReplayReport.json",
            "replay/usdjpy/QuantGod_USDJPYBarReplayReport.json",
        ],
        "collectionEndpoint": "/api/usdjpy-strategy-lab/bar-replay/status",
        "collectionCommand": "python3 tools/run_usdjpy_bar_replay.py --runtime-dir ./runtime build --write",
        "caseMemoryBuildCommand": "python3 tools/run_case_memory.py --runtime-dir ./runtime build --write --limit 8",
        "verifyCommand": "python3 tools/run_runtime_evidence_integrity.py --runtime-dir ./runtime verify",
        "nextActionZh": "收集新闻窗口内亏损、软挡失效或错过机会的回放样本。",
        "acceptanceZh": "至少 2 条带 news window、gate decision、后续影响的新闻损伤 replay 样本。",
    },
    "GA_OVERFIT": {
        "priority": "HIGH",
        "targetCount": 2,
        "source": "GA walk-forward / champion retest / generation stability",
        "sourceArtifacts": [
            "ga/QuantGod_GABlockerSummary.json",
            "ga/QuantGod_GAStatus.json",
            "ga_factory/QuantGod_GAFactoryArtifactManifest.json",
        ],
        "collectionEndpoint": "/api/usdjpy-strategy-lab/ga/blockers",
        "collectionCommand": "python3 tools/run_ga_multi_generation_stability.py --runtime-dir ./runtime build --write",
        "caseMemoryBuildCommand": "python3 tools/run_case_memory.py --runtime-dir ./runtime build --write --limit 8",
        "verifyCommand": "python3 tools/run_runtime_evidence_integrity.py --runtime-dir ./runtime verify",
        "nextActionZh": "收集训练段优秀但 forward、walk-forward 或 champion retest 失效的候选样本。",
        "acceptanceZh": "至少 2 条带 generation、seed、train/forward 差异和 blockerCode 的过拟合样本。",
    },
}


def case_memory_tokens_from_report(report: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text:
            tokens.append(text.upper())

    def add_list(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                add(item)
        elif isinstance(value, str):
            for separator in ("|", ";", "；", ","):
                value = value.replace(separator, "\n")
            for item in value.splitlines():
                add(item)

    def add_counted_row(row: Dict[str, Any], key: str) -> None:
        try:
            count = int(row.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        for _ in range(max(1, min(count, 50))):
            add(row.get(key))

    summary = report.get("caseSummary") if isinstance(report.get("caseSummary"), dict) else {}
    counts = summary.get("caseTypeCounts")
    if isinstance(counts, dict):
        for key, value in counts.items():
            try:
                count = int(value or 0)
            except (TypeError, ValueError):
                count = 0
            for _ in range(max(0, min(count, 50))):
                add(key)

    ledger_summary = (
        report.get("candidateLedgerSummary") if isinstance(report.get("candidateLedgerSummary"), dict) else {}
    )
    ledger_counts = ledger_summary.get("caseTypeCounts")
    if isinstance(ledger_counts, dict):
        for key, value in ledger_counts.items():
            try:
                count = int(value or 0)
            except (TypeError, ValueError):
                count = 0
            for _ in range(max(0, min(count, 50))):
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
        for key in ("entryMemory", "exitMemory", "reviewExitMemory", "caseMemory", "lossLessons"):
            for row in long_term.get(key) if isinstance(long_term.get(key), list) else []:
                if isinstance(row, dict):
                    add(row.get("caseType") or row.get("memoryType") or row.get("lossTag"))
                    add(row.get("exitType"))
                    add(row.get("exitReason"))
                    add(row.get("factorAttributionSummary"))
                    add_list(row.get("lossTags"))
                    add_list(row.get("exitQualityTags"))
                    add_list(row.get("entryReasons"))
        rolling = long_term.get("rollingReview") if isinstance(long_term.get("rollingReview"), dict) else {}
        for key in ("commonLossPatterns", "commonDataGaps", "failureExitTypes"):
            for row in rolling.get(key) if isinstance(rolling.get(key), list) else []:
                if isinstance(row, dict):
                    add_counted_row(row, "name")
        for key in ("suggestions", "tpSlOptimizationHints"):
            for row in rolling.get(key) if isinstance(rolling.get(key), list) else []:
                if isinstance(row, dict):
                    add(row.get("trigger"))
        exit_efficiency = rolling.get("exitEfficiency") if isinstance(rolling.get("exitEfficiency"), dict) else {}
        for row in exit_efficiency.get("qualityTags") if isinstance(exit_efficiency.get("qualityTags"), list) else []:
            if isinstance(row, dict):
                add_counted_row(row, "name")

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
    source_gaps = report.get("sourceEvidenceGaps") if isinstance(report.get("sourceEvidenceGaps"), dict) else {}
    missing = [category for category, count in counts.items() if count <= 0]
    rows = []
    for category in REQUIRED_CASE_MEMORY_CATEGORIES:
        count = counts.get(category, 0)
        guidance = CATEGORY_GUIDANCE_ZH[category]
        source_gap = source_gaps.get(category) if isinstance(source_gaps.get(category), dict) else {}
        rows.append(
            {
                "category": category,
                "status": "COVERED" if count > 0 else "MISSING",
                "observedCount": count,
                "targetCount": guidance["targetCount"],
                "remainingCount": max(0, int(guidance["targetCount"]) - count),
                "priority": guidance["priority"],
                "source": guidance["source"],
                "sourceArtifacts": list(guidance["sourceArtifacts"]),
                "collectionEndpoint": guidance["collectionEndpoint"],
                "collectionCommand": guidance["collectionCommand"],
                "caseMemoryBuildCommand": guidance["caseMemoryBuildCommand"],
                "verifyCommand": guidance["verifyCommand"],
                "sourceGap": source_gap,
                "evidenceGapZh": source_gap.get("evidenceGapZh") or "",
                "nextActionZh": guidance["nextActionZh"],
                "acceptanceZh": guidance["acceptanceZh"],
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
    missing_rows = [row for row in rows if row["status"] == "MISSING"]
    missing_rows.sort(key=lambda row: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(row["priority"]).upper(), 3), row["category"]))
    return {
        "schema": "quantgod.case_memory_coverage_plan.v1",
        "requiredCategories": list(REQUIRED_CASE_MEMORY_CATEGORIES),
        "categoryCounts": counts,
        "missingCategories": missing,
        "missingRows": missing_rows,
        "nextCollectionQueue": [
            {
                "category": row["category"],
                "priority": row["priority"],
                "remainingCount": row["remainingCount"],
                "source": row["source"],
                "sourceArtifacts": row["sourceArtifacts"],
                "collectionEndpoint": row["collectionEndpoint"],
                "collectionCommand": row["collectionCommand"],
                "caseMemoryBuildCommand": row["caseMemoryBuildCommand"],
                "verifyCommand": row["verifyCommand"],
                "sourceGap": row["sourceGap"],
                "evidenceGapZh": row["evidenceGapZh"],
                "nextActionZh": row["nextActionZh"],
                "acceptanceZh": row["acceptanceZh"],
            }
            for row in missing_rows
        ],
        "coveredCategoryCount": len(REQUIRED_CASE_MEMORY_CATEGORIES) - len(missing),
        "requiredCategoryCount": len(REQUIRED_CASE_MEMORY_CATEGORIES),
        "coverageRatio": round((len(REQUIRED_CASE_MEMORY_CATEGORIES) - len(missing)) / len(REQUIRED_CASE_MEMORY_CATEGORIES), 4),
        "targetSampleCount": sum(int(CATEGORY_GUIDANCE_ZH[category]["targetCount"]) for category in REQUIRED_CASE_MEMORY_CATEGORIES),
        "observedSampleCount": sum(counts.values()),
        "remainingTargetSampleCount": sum(max(0, int(CATEGORY_GUIDANCE_ZH[row["category"]]["targetCount"]) - row["observedCount"]) for row in rows),
        "status": "PASS" if passed else "BLOCKED",
        "statusZh": "Case Memory 样本类型已覆盖晋级门" if passed else "Case Memory 样本类型不足，继续只读补证",
        "promotionAllowed": passed,
        "rows": rows,
        "nextActionZh": "样本类型覆盖后再进入 GA/champion 晋级评审。" if passed else "按缺失分类补充 shadow/tester 证据，不放开真实执行。",
    }
