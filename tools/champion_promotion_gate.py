"""Read-only promotion gate for the current QuantGod ace champion.

The gate turns scattered ace/retest/live-readiness evidence into one promotion
decision. It is intentionally advisory: it never writes live presets, MT5 order
request files, receipts, or broker commands.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.champion_tester_run_gate import build_champion_tester_run_gate
except ModuleNotFoundError:  # pragma: no cover
    from champion_tester_run_gate import build_champion_tester_run_gate


REPORT_SCHEMA = "quantgod.champion_promotion_gate.v1"
REPORT_PATH = Path("agent") / "QuantGod_ChampionPromotionGate.json"
TESTER_REQUEST_SCHEMA = "quantgod.champion_tester_forward_request.v1"
TESTER_REQUEST_PATH = Path("agent") / "QuantGod_ChampionTesterForwardRequest.json"
TESTER_RUN_GATE_PATH = Path("agent") / "QuantGod_ChampionTesterRunGate.json"
TESTER_LOCK_DRAFT_PATH = Path("agent") / "QuantGod_ChampionTesterLockDraft.json"
HISTORY_PRODUCTION_STATUS_PATH = Path("backtest") / "QuantGod_USDJPYHistoryProductionStatus.json"
HISTORY_TIMEFRAMES = ("M1", "M5", "M15", "H1")


SAFETY = {
    "readOnly": True,
    "shadowOnly": True,
    "testerOnlyNext": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "writesMt5OrderReceipt": False,
    "livePresetMutationAllowed": False,
    "walletAuthorizationAllowed": False,
    "hyperliquidExecutionAllowed": False,
    "mossExecutionAllowed": False,
    "hfmCryptoExecutionAllowed": False,
    "autoPromotionToLiveAllowed": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _bool(value: Any) -> bool:
    return bool(value)


def _order_side_effect_paths(runtime_dir: Path) -> list[str]:
    names = {"mt5_order_requests", "mt5_order_receipts"}
    hits: list[str] = []
    if not runtime_dir.exists():
        return hits
    for path in runtime_dir.rglob("*"):
        if path.is_dir() and path.name in names:
            hits.append(str(path))
    return sorted(hits)


def _check(item_id: str, label_zh: str, passed: bool, reason_zh: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": item_id,
        "labelZh": label_zh,
        "passed": bool(passed),
        "status": "PASS" if passed else "BLOCKED",
        "reasonZh": reason_zh,
        **{key: value for key, value in extra.items() if value is not None},
    }


def _candidate_from_ace(ace: dict[str, Any]) -> dict[str, Any]:
    forex = ace.get("topQualifiedForex") if isinstance(ace.get("topQualifiedForex"), dict) else {}
    if forex.get("seedId"):
        return {
            "lane": "usdjpy_ga_elite",
            "laneZh": "USDJPY GA elite 外汇冠军",
            "seedId": forex.get("seedId"),
            "strategyId": forex.get("strategyId"),
            "symbol": forex.get("symbol") or "USDJPYc",
            "strategyFamily": forex.get("strategyFamily") or "RSI_Reversal",
            "direction": forex.get("direction") or "LONG",
            "profitFactor": forex.get("profitFactor"),
            "sharpe": forex.get("sharpe"),
            "tradeCount": forex.get("tradeCount"),
            "walkForwardStability": forex.get("walkForwardStability"),
        }
    crypto = ace.get("topQualifiedCrypto") if isinstance(ace.get("topQualifiedCrypto"), dict) else {}
    if crypto.get("strategyId"):
        return {
            "lane": "hfm_crypto_cfd_shadow",
            "laneZh": "HFM BTC crypto CFD shadow 冠军",
            "strategyId": crypto.get("strategyId"),
            "pnlUsd": crypto.get("pnlUsd"),
            "sharpe": crypto.get("sharpe"),
            "tradeCount": crypto.get("tradeCount"),
            "maxDrawdownPct": crypto.get("maxDrawdownPct"),
            "liquidationCount": crypto.get("liquidationCount"),
        }
    return {}


def _observed_crypto_candidate_from_evidence(ace: dict[str, Any], retest: dict[str, Any]) -> dict[str, Any]:
    ace_crypto = ace.get("topRetestedCrypto") if isinstance(ace.get("topRetestedCrypto"), dict) else {}
    retest_crypto = retest.get("cryptoChampion") if isinstance(retest.get("cryptoChampion"), dict) else {}
    crypto = retest_crypto if retest_crypto.get("strategyId") else ace_crypto
    if not crypto.get("strategyId"):
        return {}
    full_metrics = crypto.get("fullWindowMetrics") if isinstance(crypto.get("fullWindowMetrics"), dict) else {}
    ace_matches = ace_crypto.get("strategyId") == crypto.get("strategyId")
    metric_source = ace_crypto if ace_matches else full_metrics
    return {
        "lane": "hfm_crypto_cfd_shadow",
        "laneZh": "HFM BTC crypto CFD 观察中王牌",
        "strategyId": crypto.get("strategyId"),
        "status": crypto.get("status"),
        "validWindowCount": crypto.get("validWindowCount"),
        "windowCount": crypto.get("windowCount"),
        "positiveMajorWindowCount": crypto.get("positiveMajorWindowCount"),
        "majorWindowFailureCount": crypto.get("majorWindowFailureCount"),
        "negativeMajorWindows": crypto.get("negativeMajorWindows", []),
        "pnlUsd": metric_source.get("pnlUsd"),
        "sharpe": metric_source.get("sharpe"),
        "tradeCount": metric_source.get("tradeCount"),
        "maxDrawdownPct": metric_source.get("maxDrawdownPct"),
        "blockers": crypto.get("blockers", []),
        "qualifiedForPromotion": False,
        "nextRequiredActionZh": "这是当前 BTC 最强观察候选；多窗口仍未完全达标前不进入实盘晋级。",
    }


def _champion_label(candidate: dict[str, Any]) -> str:
    return str(candidate.get("seedId") or candidate.get("strategyId") or "当前冠军")


def _candidate_slug(candidate: dict[str, Any]) -> str:
    label = _champion_label(candidate).lower()
    slug = "".join(char if char.isalnum() else "_" for char in label).strip("_")
    return slug or "current_champion"


def _tester_forward_request_ready(request: dict[str, Any]) -> bool:
    tasks = request.get("selectedTasks") if isinstance(request.get("selectedTasks"), list) else []
    safety = request.get("safety") if isinstance(request.get("safety"), dict) else {}
    if request.get("schema") != TESTER_REQUEST_SCHEMA or not tasks:
        return False
    if safety.get("orderSendAllowed") or safety.get("writesMt5OrderRequest") or safety.get("livePresetMutationAllowed"):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            return False
        if not task.get("testerOnly") or task.get("livePresetMutation") or task.get("runTerminalDefault"):
            return False
    return True


def _tester_forward_report_ready(request: dict[str, Any]) -> bool:
    materialization = request.get("materializationStatus") if isinstance(request.get("materializationStatus"), dict) else {}
    return int(materialization.get("htmlReportParsedCount") or 0) > 0


def _refresh_tester_request_materialization(request: dict[str, Any]) -> dict[str, Any]:
    if not request:
        return {}
    refreshed = dict(request)
    isolation = request.get("testerIsolation") if isinstance(request.get("testerIsolation"), dict) else {}
    status_path_text = str(isolation.get("statusPath") or "")
    status_path = Path(status_path_text) if status_path_text else Path()
    status = _read_json(status_path) if status_path_text else {}
    if not status:
        return refreshed
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    refreshed["materializationStatus"] = {
        "exists": True,
        "statusPath": str(status_path),
        "status": status.get("status") or status.get("mode") or "STATUS_PRESENT",
        "configReadyCount": summary.get("configReadyCount", 0),
        "runAttemptedCount": summary.get("runAttemptedCount", 0),
        "htmlReportParsedCount": summary.get("htmlReportParsedCount", 0),
        "terminalNonzeroCount": summary.get("terminalNonzeroCount", 0),
        "terminalBlockerCodes": summary.get("terminalBlockerCodes", []),
        "runTerminal": bool(status.get("runTerminal")),
        "orderSendAllowed": False,
        "writesMt5OrderRequest": False,
    }
    return refreshed


def _tester_run_gate_ready(run_gate: dict[str, Any]) -> bool:
    decision = run_gate.get("decision") if isinstance(run_gate.get("decision"), dict) else {}
    gate = run_gate.get("gate") if isinstance(run_gate.get("gate"), dict) else {}
    return bool(decision.get("canRunIsolatedTester") or gate.get("canRunTerminal"))


def _tester_lock_draft_ready(lock_draft: dict[str, Any]) -> bool:
    decision = lock_draft.get("decision") if isinstance(lock_draft.get("decision"), dict) else {}
    draft = lock_draft.get("draftPayload") if isinstance(lock_draft.get("draftPayload"), dict) else {}
    safety = lock_draft.get("safety") if isinstance(lock_draft.get("safety"), dict) else {}
    if lock_draft.get("schema") != "quantgod.champion_tester_lock_draft.v1":
        return False
    if not draft or draft.get("livePresetMutation") or draft.get("testerOnly") is not True:
        return False
    if safety.get("orderSendAllowed") or safety.get("writesMt5OrderRequest") or safety.get("livePresetMutationAllowed"):
        return False
    return bool(decision.get("draftReadyForSeparateLockWriter"))


def _repo_runtime_fallback() -> Path:
    return Path(__file__).resolve().parents[1] / "runtime"


def _evidence_runtime_dir(runtime_dir: Path) -> Path:
    if (runtime_dir / "agent" / "QuantGod_AceStrategyScout.json").exists():
        return runtime_dir
    fallback = _repo_runtime_fallback()
    if fallback != runtime_dir and (fallback / "agent" / "QuantGod_AceStrategyScout.json").exists():
        return fallback
    return runtime_dir


def _readiness_diagnosis(
    *,
    ace_candidate_selected: bool,
    champion_retest_pass: bool,
    tester_request_ready: bool,
    tester_report_ready: bool,
    tester_lock_draft_ready: bool,
    tester_run_blockers: list[Any],
    tester_account_context: dict[str, Any],
) -> dict[str, Any]:
    blocker_texts = [str(item) for item in tester_run_blockers]
    environment_blockers = [
        item
        for item in blocker_texts
        if item.startswith("authorization_lock_")
        or item.startswith("isolated_tester_")
        or item.startswith("sensitive_account_context_")
        or item.startswith("live_session_")
        or item.startswith("live_dashboard_")
        or item.startswith("tester_window_")
        or item in {"outside_tester_window", "outside_strategy_tester_window", "runtime_environment_not_ready"}
    ]
    strategy_blockers: list[str] = []
    if not ace_candidate_selected:
        strategy_blockers.append("ace_candidate_selected")
    if not champion_retest_pass:
        strategy_blockers.append("champion_retest_pass")
    if not tester_request_ready:
        strategy_blockers.append("isolated_tester_forward_required")
    evidence_blockers = [] if tester_report_ready else ["isolated_tester_forward_report_ready"]
    strategy_ready_for_tester = bool(
        ace_candidate_selected
        and champion_retest_pass
        and tester_request_ready
        and tester_lock_draft_ready
    )
    environment_blocked = bool(environment_blockers or tester_account_context.get("environmentBlocked"))
    return {
        "strategyReadyForTester": strategy_ready_for_tester,
        "strategyBlocked": bool(strategy_blockers),
        "strategyBlockers": strategy_blockers,
        "environmentBlocked": environment_blocked,
        "environmentBlockers": environment_blockers,
        "evidenceBlocked": bool(evidence_blockers),
        "evidenceBlockers": evidence_blockers,
        "sensitiveAccountContextSyncRequired": bool(tester_account_context.get("sensitiveAccountContextSyncRequired")),
        "canRunTesterAfterEnvironmentCleared": bool(strategy_ready_for_tester and not tester_report_ready),
        "summaryZh": (
            "策略候选、复验和 tester 请求已就绪；当前主要卡点是隔离 tester 环境。"
            if strategy_ready_for_tester and environment_blocked
            else "策略证据仍需补齐。"
            if strategy_blockers
            else "等待 tester/forward 报告解析。"
        ),
    }


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _memory_promotion_review(runtime_dir: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    case_memory = _read_json(runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json")
    adaptive = _read_json(runtime_dir / "adaptive" / "QuantGod_AdaptivePolicy.json")
    long_memory = case_memory.get("longTermTradeMemory") if isinstance(case_memory.get("longTermTradeMemory"), dict) else {}
    feedback = long_memory.get("entryFeedbackPolicy") if isinstance(long_memory.get("entryFeedbackPolicy"), dict) else {}
    rolling = long_memory.get("rollingReview") if isinstance(long_memory.get("rollingReview"), dict) else {}
    entry_completeness = rolling.get("entryMemoryCompleteness") if isinstance(rolling.get("entryMemoryCompleteness"), dict) else {}
    quality_gate = entry_completeness.get("qualityGate") if isinstance(entry_completeness.get("qualityGate"), dict) else {}
    route = _matching_adaptive_route(adaptive, candidate)
    memory_feedback = route.get("memoryFeedback") if isinstance(route.get("memoryFeedback"), dict) else {}
    quality_profile = route.get("memoryQualityProfile") if isinstance(route.get("memoryQualityProfile"), dict) else {}
    applied_rules = memory_feedback.get("appliedRules") if isinstance(memory_feedback.get("appliedRules"), list) else []
    memory_penalty = _num(route.get("memoryPenalty"), 0.0)
    route_state = str(route.get("state") or "")
    route_before = str(route.get("stateBeforeMemory") or "")
    raw_coverage_pass = bool(quality_gate.get("rawCoveragePass", True))
    proxy_ratio_pass = bool(quality_gate.get("proxySampleRatioPass", True))
    context_missing_pass = bool(quality_gate.get("contextMissingRatioPass", True))
    quality_blocks_live = bool(not raw_coverage_pass or not proxy_ratio_pass or not context_missing_pass)
    blocks_live = bool(
        route_state == "PAUSED"
        or memory_penalty >= 0.15
        or feedback.get("status") == "DEFENSE_MODE"
        or quality_blocks_live
    )
    status = "MEMORY_PROMOTION_BLOCKED" if blocks_live else "MEMORY_PROMOTION_OBSERVE"
    if not long_memory:
        status = "MEMORY_MISSING_OBSERVE"
    return {
        "schema": "quantgod.champion_long_term_memory_promotion_review.v1",
        "status": status,
        "memoryFound": bool(long_memory),
        "routeMatched": bool(route),
        "blocksLivePromotion": blocks_live,
        "requiresTesterForwardBeforePromotion": blocks_live,
        "sampleCount": rolling.get("sampleCount") or feedback.get("sampleCount") or 0,
        "rollingReviewStatus": rolling.get("status"),
        "winRate": rolling.get("winRate"),
        "totalProfitR": rolling.get("totalProfitR"),
        "entryFeedbackStatus": feedback.get("status"),
        "entryMemoryCompleteness": {
            "status": entry_completeness.get("status"),
            "overallCoverageRatio": entry_completeness.get("overallCoverageRatio"),
            "rawCoverageRatio": entry_completeness.get("rawCoverageRatio"),
            "proxyCoverageRatio": entry_completeness.get("proxyCoverageRatio"),
            "contextMissingSampleCount": entry_completeness.get("contextMissingSampleCount"),
            "contextMissingSampleRatio": entry_completeness.get("contextMissingSampleRatio"),
            "usableRawSampleCount": entry_completeness.get("usableRawSampleCount"),
            "proxySampleCount": entry_completeness.get("proxySampleCount"),
            "proxySampleRatio": entry_completeness.get("proxySampleRatio"),
            "qualityGate": quality_gate,
            "blocksLivePromotion": quality_blocks_live,
        },
        "candidate": {
            "lane": candidate.get("lane"),
            "seedId": candidate.get("seedId"),
            "strategyId": candidate.get("strategyId"),
            "symbol": candidate.get("symbol"),
            "strategyFamily": candidate.get("strategyFamily"),
            "direction": candidate.get("direction"),
        },
        "matchedRoute": {
            "symbol": route.get("symbol"),
            "strategy": route.get("strategy"),
            "direction": route.get("direction"),
            "matchQuality": route.get("matchQuality"),
            "state": route_state,
            "stateBeforeMemory": route_before,
            "rawAvgScoreR": route.get("rawAvgScoreR"),
            "avgScoreR": route.get("avgScoreR"),
            "memoryPenalty": memory_penalty,
            "riskMultiplier": route.get("riskMultiplier"),
        },
        "qualityProfile": quality_profile,
        "appliedRules": applied_rules,
        "reasonZh": (
            "长期记忆显示真实采集覆盖不足或代理上下文占比过高；只能继续 tester/forward，不能进入实盘晋级。"
            if quality_blocks_live
            else "长期记忆显示当前冠军 route 已暂停或扣分偏高；只能继续 tester/forward，不能进入实盘晋级。"
            if blocks_live
            else "长期记忆未触发实盘晋级阻断；仍需通过 tester/forward 和执行通道评审。"
        ),
        "sourceArtifacts": {
            "caseMemory": str(runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"),
            "adaptivePolicy": str(runtime_dir / "adaptive" / "QuantGod_AdaptivePolicy.json"),
        },
        "safety": SAFETY,
    }


def _history_freshness_review(runtime_dir: Path) -> dict[str, Any]:
    history = _read_json(runtime_dir / HISTORY_PRODUCTION_STATUS_PATH)
    if not history:
        return {
            "schema": "quantgod.champion_history_freshness_review.v1",
            "status": "HISTORY_PRODUCTION_STATUS_MISSING",
            "historyTargetSatisfied": False,
            "blocksLivePromotion": True,
            "failedTimeframes": list(HISTORY_TIMEFRAMES),
            "staleTimeframes": list(HISTORY_TIMEFRAMES),
            "blockers": ["history_production_status_missing"],
            "reasonZh": "缺少 USDJPY 历史生产状态；M1/M5/M15/H1 未被证明新鲜前，不能把冠军包装成实盘晋级。",
            "sourceArtifact": str(runtime_dir / HISTORY_PRODUCTION_STATUS_PATH),
            "safety": SAFETY,
        }

    timeframes = history.get("timeframes") if isinstance(history.get("timeframes"), dict) else {}
    failed: list[str] = []
    stale: list[str] = []
    max_lag_by_timeframe: dict[str, Any] = {}
    for timeframe in HISTORY_TIMEFRAMES:
        row = timeframes.get(timeframe) if isinstance(timeframes.get(timeframe), dict) else {}
        max_lag_by_timeframe[timeframe] = row.get("latestLagHours")
        if row.get("passed") is not True:
            failed.append(timeframe)
        if row.get("freshnessOk") is not True:
            stale.append(timeframe)
    passed = bool(history.get("historyTargetSatisfied") is True and not failed)
    blockers: list[str] = []
    if failed:
        blockers.append("history_timeframes_not_production_ready")
    if stale:
        blockers.append("history_freshness_lag_exceeded")
    if not bool(history.get("historyTargetSatisfied")):
        blockers.append("history_target_not_satisfied")
    return {
        "schema": "quantgod.champion_history_freshness_review.v1",
        "status": "HISTORY_FRESHNESS_PASS" if passed else "HISTORY_FRESHNESS_BLOCKED",
        "historyTargetSatisfied": bool(history.get("historyTargetSatisfied")),
        "blocksLivePromotion": not passed,
        "failedTimeframes": failed,
        "staleTimeframes": stale,
        "latestLagHoursByTimeframe": max_lag_by_timeframe,
        "maxLatestLagHours": history.get("maxLatestLagHours"),
        "generatedAt": history.get("generatedAt"),
        "blockers": blockers,
        "reasonZh": (
            "USDJPY M1/M5/M15/H1 历史覆盖、密度和 freshness 均通过，可作为冠军晋级前置证据。"
            if passed
            else "USDJPY 历史生产状态未通过；覆盖/密度/最新延迟未全部达标前，只允许 tester-only/forward 或 shadow 观察。"
        ),
        "sourceArtifact": str(runtime_dir / HISTORY_PRODUCTION_STATUS_PATH),
        "safety": SAFETY,
    }


def _matching_adaptive_route(adaptive: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    routes = adaptive.get("routes") if isinstance(adaptive.get("routes"), list) else []
    symbol = str(candidate.get("symbol") or ("USDJPYc" if candidate.get("lane") == "usdjpy_ga_elite" else "")).upper()
    direction = str(candidate.get("direction") or "").upper()
    family = str(candidate.get("strategyFamily") or "").upper()
    strategy_id = str(candidate.get("strategyId") or "").upper()
    exact_matches: list[dict[str, Any]] = []
    direction_matches: list[dict[str, Any]] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        if symbol and str(route.get("symbol") or "").upper() != symbol:
            continue
        if direction and str(route.get("direction") or "").upper() != direction:
            continue
        route_strategy = str(route.get("strategy") or "").upper()
        if family and family in route_strategy:
            exact = dict(route)
            exact["matchQuality"] = "strategy_family"
            exact_matches.append(exact)
            continue
        if strategy_id and route_strategy in strategy_id:
            exact = dict(route)
            exact["matchQuality"] = "strategy_id"
            exact_matches.append(exact)
            continue
        if not family and not strategy_id:
            exact = dict(route)
            exact["matchQuality"] = "symbol_direction"
            exact_matches.append(exact)
            continue
        fallback = dict(route)
        fallback["matchQuality"] = "symbol_direction_fallback"
        direction_matches.append(fallback)
    matches = exact_matches or direction_matches
    return sorted(matches, key=lambda row: (_num(row.get("memoryPenalty"), 0.0), _num(row.get("avgScoreR"), 0.0)))[-1] if matches else {}


def build_champion_promotion_gate(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    evidence_runtime_dir = _evidence_runtime_dir(runtime_dir)
    ace = _read_json(evidence_runtime_dir / "agent" / "QuantGod_AceStrategyScout.json")
    retest = _read_json(evidence_runtime_dir / "agent" / "QuantGod_ChampionRetestReport.json")
    pipeline = _read_json(evidence_runtime_dir / "agent" / "QuantGod_SimToLiveAutomationPipeline.json")
    live_candidates = _read_json(evidence_runtime_dir / "agent" / "QuantGod_LivePromotionCandidates.json")
    tester_request = _refresh_tester_request_materialization(_read_json(evidence_runtime_dir / TESTER_REQUEST_PATH))
    tester_run_gate = build_champion_tester_run_gate(evidence_runtime_dir, write=True)
    tester_lock_draft = _read_json(evidence_runtime_dir / TESTER_LOCK_DRAFT_PATH)
    side_effect_paths = _order_side_effect_paths(runtime_dir)
    candidate = _candidate_from_ace(ace)
    memory_promotion_review = _memory_promotion_review(evidence_runtime_dir, candidate)
    history_freshness_review = _history_freshness_review(evidence_runtime_dir)
    observed_crypto_candidate = _observed_crypto_candidate_from_evidence(ace, retest)
    forex_contender_review = (
        retest.get("forexContenderReview")
        if isinstance(retest.get("forexContenderReview"), dict)
        else ace.get("forexContenderReview")
        if isinstance(ace.get("forexContenderReview"), dict)
        else {}
    )
    contender_ids = [
        str(row.get("seedId"))
        for row in forex_contender_review.get("contenders", [])
        if isinstance(row, dict) and row.get("seedId")
    ]
    parallel_tester_required = bool(forex_contender_review.get("requiresParallelTesterForward") and contender_ids)
    champion_label = _champion_label(candidate)
    tester_target_label = " / ".join(contender_ids) if parallel_tester_required else champion_label
    champion_slug = _candidate_slug(candidate)

    forex_retest = retest.get("forexChampion") if isinstance(retest.get("forexChampion"), dict) else {}
    crypto_retest = retest.get("cryptoChampion") if isinstance(retest.get("cryptoChampion"), dict) else {}
    ace_candidate_selected = bool(candidate)
    selected_forex = candidate.get("lane") == "usdjpy_ga_elite"
    selected_crypto = candidate.get("lane") == "hfm_crypto_cfd_shadow"
    champion_retest_pass = (
        selected_forex and forex_retest.get("seedId") == candidate.get("seedId") and forex_retest.get("status") == "FOREX_CHAMPION_RETEST_PASS"
    ) or (
        selected_crypto and crypto_retest.get("strategyId") == candidate.get("strategyId") and crypto_retest.get("status") == "BTC_CHAMPION_RETEST_PASS"
    )
    pipeline_ready_for_review = _bool(pipeline.get("readyForSeparateExecutionAdapterReview"))
    execution_ready = _bool(pipeline.get("executionReady")) or _bool(live_candidates.get("executionReady"))
    auto_live_allowed = _bool(pipeline.get("autoPromotionToLiveAllowed")) or _bool(live_candidates.get("autoPromotionToLiveAllowed"))
    tester_request_ready = _tester_forward_request_ready(tester_request)
    tester_report_ready = _tester_forward_report_ready(tester_request)
    tester_run_gate_ready = _tester_run_gate_ready(tester_run_gate)
    tester_lock_draft_ready = _tester_lock_draft_ready(tester_lock_draft)
    tester_run_blockers = []
    if isinstance(tester_run_gate.get("gate"), dict):
        tester_run_blockers = tester_run_gate.get("gate", {}).get("blockers") if isinstance(tester_run_gate.get("gate", {}).get("blockers"), list) else []
    tester_account_context = tester_run_gate.get("testerAccountContext") if isinstance(tester_run_gate.get("testerAccountContext"), dict) else {}

    checklist = [
        _check(
            "ace_candidate_selected",
            "王牌候选已选出",
            ace_candidate_selected,
            "Ace scout 必须先选出无 blocker 的 topQualifiedForex 或 topQualifiedCrypto。",
            value=candidate.get("seedId") or candidate.get("strategyId"),
        ),
        _check(
            "champion_retest_pass",
            "冠军复验通过",
            champion_retest_pass,
            "冠军必须通过 champion retest；BTC 还必须通过多窗口复验。",
            value=(forex_retest.get("status") if selected_forex else crypto_retest.get("status")),
        ),
        _check(
            "isolated_tester_forward_required",
            "隔离 tester / forward 证据",
            tester_request_ready,
            "当前冠军必须先生成隔离 Strategy Tester / forward 请求；该请求只允许 config-only/tester-only。",
            value=tester_request.get("status"),
        ),
        _check(
            "isolated_tester_forward_report_ready",
            "隔离 tester / forward 报告已解析",
            tester_report_ready,
            "tester 请求准备好以后，还需要隔离 Strategy Tester HTML 报告解析结果，才能评估是否晋级。",
            value=(tester_request.get("materializationStatus") or {}).get("status") if isinstance(tester_request.get("materializationStatus"), dict) else None,
        ),
        _check(
            "champion_tester_run_gate_ready",
            "冠军 tester 启动条件",
            bool(tester_report_ready or tester_run_gate_ready),
            f"如果报告尚未解析，必须先清空 {champion_label} tester run gate：窗口、lock、账户上下文、live session、queue 都要 ready。",
            value=tester_run_gate.get("status"),
            blockers=tester_run_blockers or None,
        ),
        _check(
            "champion_tester_lock_draft_ready",
            "冠军 tester lock 草案",
            bool(tester_report_ready or tester_lock_draft_ready),
            f"{champion_label} tester 需要短期 tester-only lock 草案；草案本身不得写 lock、不得启动 terminal。",
            value=tester_lock_draft.get("status"),
        ),
        _check(
            "champion_tester_forward_request_safety",
            "冠军 tester 请求安全闸",
            not tester_request or tester_request_ready,
            f"{champion_label} tester 请求必须保持 testerOnly/configOnly，禁止 runTerminal 默认启动、live preset 变更和订单文件写入。",
            value=tester_request.get("summary", {}).get("topCandidateId") if isinstance(tester_request.get("summary"), dict) else None,
        ),
        _check(
            "long_term_memory_promotion_guard",
            "长期记忆晋级闸",
            not memory_promotion_review.get("blocksLivePromotion"),
            "长期交易记忆若显示方向弱、低覆盖亏损或 route 已暂停，则禁止包装成实盘晋级。",
            value=memory_promotion_review.get("status"),
            memoryPenalty=(memory_promotion_review.get("matchedRoute") or {}).get("memoryPenalty"),
        ),
        _check(
            "history_freshness_promotion_guard",
            "历史数据 freshness 晋级闸",
            not history_freshness_review.get("blocksLivePromotion"),
            "USDJPY M1/M5/M15/H1 历史生产状态必须通过覆盖、密度和最新延迟检查，才能包装成晋级证据。",
            value=history_freshness_review.get("status"),
            failedTimeframes=history_freshness_review.get("failedTimeframes"),
            staleTimeframes=history_freshness_review.get("staleTimeframes"),
        ),
        _check(
            "separate_execution_lane_review",
            "单独执行通道评审",
            pipeline_ready_for_review,
            "Sim-to-live 数据平面可进入执行通道评审，但评审通过不等于允许下单。",
            value=pipeline.get("status"),
        ),
        _check(
            "execution_not_enabled",
            "真实执行仍关闭",
            not execution_ready and not auto_live_allowed,
            "实盘执行开关必须保持关闭，直到单独执行 lane 和外部风控全部通过。",
            executionReady=execution_ready,
            autoPromotionToLiveAllowed=auto_live_allowed,
        ),
        _check(
            "no_order_side_effect_paths",
            "未发现 MT5 订单请求/回执目录",
            not side_effect_paths,
            "只读报告不应创建 mt5_order_requests 或 mt5_order_receipts。",
            paths=side_effect_paths or None,
        ),
    ]
    blockers = [item["id"] for item in checklist if not item["passed"]]
    if not ace_candidate_selected:
        status = "NO_ACE_CHAMPION_SELECTED"
        status_zh = "尚未选出王牌冠军"
        next_action = "继续刷新 ace scout 和 champion retest，直到出现无 blocker 冠军。"
    elif not champion_retest_pass:
        status = "CHAMPION_RETEST_BLOCKED"
        status_zh = "冠军复验未通过"
        next_action = "修复或补样本后重新复验；BTC 必须补更多多窗口证据。"
    elif not tester_request_ready:
        status = "READY_FOR_ISOLATED_TESTER_FORWARD"
        status_zh = "冠军可进入隔离 tester / forward"
        next_action = f"围绕 {tester_target_label} 生成 tester-only 复验任务，先跑隔离 Strategy Tester/forward，不进入真钱执行。"
    elif not tester_report_ready:
        status = "WAITING_ISOLATED_TESTER_FORWARD_REPORT"
        status_zh = f"{tester_target_label} tester 请求已准备，等待前向报告"
        next_action = "在受控 Strategy Tester window 内运行隔离 tester，然后解析 HTML 报告。"
    else:
        status = "ISOLATED_TESTER_FORWARD_REPORT_READY"
        status_zh = f"{tester_target_label} 前向报告已解析"
        next_action = "审查 tester/forward 指标；若仍稳定，再进入单独 execution lane 评审。"
    readiness_diagnosis = _readiness_diagnosis(
        ace_candidate_selected=ace_candidate_selected,
        champion_retest_pass=champion_retest_pass,
        tester_request_ready=tester_request_ready,
        tester_report_ready=tester_report_ready,
        tester_lock_draft_ready=tester_lock_draft_ready,
        tester_run_blockers=tester_run_blockers,
        tester_account_context=tester_account_context,
    )

    report = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime_dir),
        "evidenceRuntimeDir": str(evidence_runtime_dir),
        "evidenceRuntimeFallbackUsed": evidence_runtime_dir != runtime_dir,
        "status": status,
        "statusZh": status_zh,
        "selectedChampion": candidate,
        "longTermMemoryPromotionReview": memory_promotion_review,
        "historyFreshnessPromotionReview": history_freshness_review,
        "forexContenderReview": forex_contender_review,
        "observedCryptoChampion": observed_crypto_candidate,
        "championRetest": {
            "forexStatus": forex_retest.get("status"),
            "cryptoStatus": crypto_retest.get("status"),
            "cryptoValidWindowCount": crypto_retest.get("validWindowCount"),
            "cryptoWindowCount": crypto_retest.get("windowCount"),
            "cryptoBlockers": crypto_retest.get("blockers") or [],
        },
        "championTesterForwardRequest": {
            "status": tester_request.get("status"),
            "ready": tester_request_ready,
            "reportReady": tester_report_ready,
            "topCandidateId": (tester_request.get("summary") or {}).get("topCandidateId") if isinstance(tester_request.get("summary"), dict) else None,
            "materializationStatus": tester_request.get("materializationStatus") if isinstance(tester_request.get("materializationStatus"), dict) else {},
        },
        "championTesterRunGate": {
            "status": tester_run_gate.get("status"),
            "ready": tester_run_gate_ready,
            "blockers": tester_run_blockers,
            "nextTesterWindow": tester_run_gate.get("nextTesterWindow") if isinstance(tester_run_gate.get("nextTesterWindow"), dict) else {},
            "liveSession": tester_run_gate.get("gate", {}).get("liveSession") if isinstance(tester_run_gate.get("gate"), dict) else {},
            "testerAccountContext": tester_account_context,
        },
        "championTesterLockDraft": {
            "status": tester_lock_draft.get("status"),
            "ready": tester_lock_draft_ready,
            "lockFileWritten": bool(tester_lock_draft.get("lockFileWritten")),
            "targetLockPath": tester_lock_draft.get("targetLockPath"),
            "draftPayload": tester_lock_draft.get("draftPayload") if isinstance(tester_lock_draft.get("draftPayload"), dict) else {},
        },
        "promotionDecision": {
            "canRunIsolatedTesterForwardNext": bool(ace_candidate_selected and champion_retest_pass and tester_request_ready and not tester_report_ready),
            "canGenerateTesterForwardRequestNext": bool(ace_candidate_selected and champion_retest_pass and not tester_request_ready),
            "canRunIsolatedTesterNow": bool(tester_run_gate_ready),
            "testerLockDraftReady": bool(tester_lock_draft_ready),
            "canPromoteToLiveNow": False,
            "memoryBlocksLivePromotion": bool(memory_promotion_review.get("blocksLivePromotion")),
            "historyFreshnessBlocksPromotion": bool(history_freshness_review.get("blocksLivePromotion")),
            "executionReady": False,
            "autoPromotionToLiveAllowed": False,
            "strategyReadyButEnvironmentBlocked": bool(readiness_diagnosis["strategyReadyForTester"] and readiness_diagnosis["environmentBlocked"]),
            "reasonZh": f"目标是赚钱，但当前最稳路径是先把 {tester_target_label} 补成 tester/forward 级冠军；本闸门不允许直接真钱执行。",
        },
        "readinessDiagnosis": readiness_diagnosis,
        "checklist": checklist,
        "blockers": blockers,
        "nextSafeActions": [
            {
                "id": f"{champion_slug}_tester_forward_task",
                "actionZh": f"为 {tester_target_label} 生成 tester-only/forward 复验任务，锁定 seed 和风险核，不改 live preset。",
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
            },
            {
                "id": "btc_multi_window_retest",
                "actionZh": "BTC 继续补更长 CopyRates，多窗口达标前不进入实盘候选。",
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
            },
            {
                "id": "live_lane_review_after_tester_pass",
                "actionZh": "只有 tester/forward 证据通过后，才进入单独 execution lane 评审。",
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
            },
        ],
        "sourceArtifacts": {
            "aceStrategyScout": str(evidence_runtime_dir / "agent" / "QuantGod_AceStrategyScout.json"),
            "championRetest": str(evidence_runtime_dir / "agent" / "QuantGod_ChampionRetestReport.json"),
            "simToLivePipeline": str(evidence_runtime_dir / "agent" / "QuantGod_SimToLiveAutomationPipeline.json"),
            "livePromotionCandidates": str(evidence_runtime_dir / "agent" / "QuantGod_LivePromotionCandidates.json"),
            "championTesterForwardRequest": str(evidence_runtime_dir / TESTER_REQUEST_PATH),
            "championTesterRunGate": str(evidence_runtime_dir / TESTER_RUN_GATE_PATH),
            "championTesterLockDraft": str(evidence_runtime_dir / TESTER_LOCK_DRAFT_PATH),
            "historyProductionStatus": str(evidence_runtime_dir / HISTORY_PRODUCTION_STATUS_PATH),
        },
        "safety": SAFETY,
        "reportPath": str(runtime_dir / REPORT_PATH),
    }
    if write:
        _write_json(runtime_dir / REPORT_PATH, report)
    return report


def read_champion_promotion_gate(runtime_dir: Path) -> dict[str, Any]:
    report = _read_json(runtime_dir / REPORT_PATH)
    if report:
        selected = report.get("selectedChampion") if isinstance(report.get("selectedChampion"), dict) else {}
        fallback = _evidence_runtime_dir(runtime_dir)
        if not selected and fallback != runtime_dir:
            return build_champion_promotion_gate(runtime_dir, write=True)
        if "historyFreshnessPromotionReview" not in report:
            return build_champion_promotion_gate(runtime_dir, write=True)
        return report
    return build_champion_promotion_gate(runtime_dir, write=False)
