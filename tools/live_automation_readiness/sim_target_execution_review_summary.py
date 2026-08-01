from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from tools.profit_target_tracker.builder import build_profit_target_tracker, read_profit_target_tracker
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from profit_target_tracker.builder import build_profit_target_tracker, read_profit_target_tracker

from .forex_live12_rsi_candidate_promotion_gate import (
    build_forex_live12_rsi_candidate_promotion_gate,
    read_forex_live12_rsi_candidate_promotion_gate,
)
from .live_execution_cutover import build_live_execution_cutover_review, read_live_execution_cutover_review
from .release_minimal_diff_review import build_release_minimal_diff_review
from .release_readiness_refresh import build_release_readiness_refresh, read_release_readiness_refresh
from .release_token_evidence_review import build_release_token_evidence_review
from .release_token_signoff_evidence_matrix import build_release_token_signoff_evidence_matrix
from .release_token_signoff_handoff import build_release_token_signoff_handoff
from .schema import (
    SAFETY,
    SIM_TARGET_EXECUTION_REVIEW_SUMMARY_SCHEMA_VERSION,
    assert_no_execution_flags,
    sim_target_execution_review_summary_path,
    utc_now_iso,
)


TOP_BLOCKER_CODES = (
    "EXECUTION_MODE_GATES_NOT_ACTIVE",
    "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
    "MT5_READ_ONLY_MODE_STILL_ACTIVE",
    "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
    "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
    "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF",
    "DEPLOYED_PRESET_READ_ONLY_TRUE",
    "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF",
    "DEPLOYED_PRESET_RSI_LIVE_OFF",
    "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
    "REQUEST_READER_RELEASE_TOKEN_MISSING",
    "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
    "RECEIPT_WRITER_RELEASE_TOKEN_MISSING",
    "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
)


def _secondary_mt5_runtime_dir() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "net.metaquotes.wine.metatrader5-live16"
        / "drive_c"
        / "Program Files"
        / "MetaTrader 5"
        / "MQL5"
        / "Files"
    )


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_or_build_profit_tracker(runtime: Path, target_usd: float) -> dict[str, Any]:
    report = read_profit_target_tracker(runtime)
    if report.get("targetReached") or report.get("status") == "TARGET_REACHED":
        return report
    secondary_runtime = _secondary_mt5_runtime_dir()
    return build_profit_target_tracker(
        runtime,
        secondary_runtime_dir=secondary_runtime if secondary_runtime.exists() else None,
        report_runtime_dir=runtime,
        target_usd=target_usd,
        write=False,
    )


def _lane_summaries(profit_tracker: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lane_targets = _safe_dict(profit_tracker.get("laneTargets"))
    for lane_id in ("forexMt5",):
        lane = _safe_dict(lane_targets.get(lane_id))
        if not lane:
            continue
        rows.append({
            "laneId": lane_id,
            "labelZh": lane.get("labelZh"),
            "marketType": lane.get("marketType"),
            "status": lane.get("status"),
            "targetReached": bool(lane.get("targetReached")),
            "lanePositive": bool(lane.get("lanePositive")),
            "simulationVerifiedUsdProfit": lane.get("simulationVerifiedUsdProfit"),
            "targetUsd": lane.get("targetUsd"),
            "evidenceCount": lane.get("evidenceCount"),
        })
    return rows


def _ranked_blockers(
    profit_tracker: dict[str, Any],
    release_packet: dict[str, Any] | None = None,
    cutover_review: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    live_review = _safe_dict(profit_tracker.get("liveExecutionReview"))
    release_packet = _safe_dict(release_packet) or _safe_dict(live_review.get("executionReleaseReadinessPacket"))
    release_summary = _safe_dict(release_packet.get("releaseGateSummary"))
    release_codes = release_summary.get("blockerCodes") or []
    raw_blockers = (
        _safe_list(live_review.get("blockers"))
        + _safe_list(_safe_dict(cutover_review).get("blockers"))
        + [
        {"code": code, "source": "execution_release_gate", "reasonZh": "执行 release token 尚未释放。"}
        for code in release_codes
        ]
    )
    by_code: dict[str, dict[str, Any]] = {}
    for blocker in raw_blockers:
        if not isinstance(blocker, dict):
            continue
        code = str(blocker.get("code") or "").strip()
        if not code:
            continue
        by_code.setdefault(code, {
            "code": code,
            "scope": blocker.get("scope"),
            "source": blocker.get("source"),
            "value": blocker.get("value"),
            "reasonZh": blocker.get("reasonZh"),
        })
    ranked = [by_code[code] for code in TOP_BLOCKER_CODES if code in by_code]
    extras = [
        blocker
        for code, blocker in by_code.items()
        if code not in TOP_BLOCKER_CODES
    ]
    return ranked + extras[:10]



def _ace_strategy_upgrade_summary(runtime: Path) -> dict[str, Any]:
    pack = _read_json(runtime / "agent" / "QuantGod_AceExecutionCandidatePack.json")
    champion_gate = _read_json(runtime / "agent" / "QuantGod_ChampionPromotionGate.json")
    tester_request = _read_json(runtime / "agent" / "QuantGod_ChampionTesterForwardRequest.json")
    tester_run_gate = _read_json(runtime / "agent" / "QuantGod_ChampionTesterRunGate.json")
    tester_lock_draft = _read_json(runtime / "agent" / "QuantGod_ChampionTesterLockDraft.json")
    account_context = _read_json(runtime / "QuantGod_IsolatedTesterAccountContextStatus.json")
    rsi = _safe_dict(pack.get("rsiDemotionReview"))
    live_upgrade_selection = _safe_dict(pack.get("liveUpgradeSelection"))
    replacement = _safe_dict(rsi.get("replacementPlan"))
    forex = _safe_dict(replacement.get("primaryForexAce")) or _safe_dict(pack.get("forexMt5"))
    if not pack:
        return {
            "status": "ACE_EXECUTION_CANDIDATE_PACK_MISSING",
            "statusZh": "王牌执行候选包尚未生成；无法判断 RSI 降级替代。",
            "rsiDemoted": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "writesLivePreset": False,
        }
    rsi_demoted = rsi.get("status") == "RSI_LIVE_LOGIC_DEMOTE_REVIEW"
    return {
        "status": "ACE_RSI_DEMOTION_REPLACEMENT_READY" if rsi_demoted else "ACE_RSI_DEMOTION_REVIEW_PENDING",
        "statusZh": (
            "raw RSI 已降级，替代王牌候选已进入复验摘要。"
            if rsi_demoted
            else "raw RSI 降级状态未确认，继续保留 review。"
        ),
        "rsiDemoted": bool(rsi_demoted),
        "rsiRecommendedAction": rsi.get("recommendedAction"),
        "rsiDecision": rsi.get("decision"),
        "rsiCurrentEvidence": _safe_dict(rsi.get("currentEvidence")),
        "liveUpgradeSelection": {
            "status": live_upgrade_selection.get("status"),
            "statusZh": live_upgrade_selection.get("statusZh"),
            "selectedLane": live_upgrade_selection.get("selectedLane"),
            "selectedStrategy": _safe_dict(live_upgrade_selection.get("selectedStrategy")),
            "excludedAceCandidates": _safe_list(live_upgrade_selection.get("excludedAceCandidates")),
            "upgradePrerequisites": _safe_list(live_upgrade_selection.get("upgradePrerequisites")),
            "nextActionZh": live_upgrade_selection.get("nextActionZh"),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "writesLivePreset": False,
        },
        "primaryReplacementLane": "forexMt5" if forex else None,
        "primaryForexReplacement": {
            "seedId": forex.get("seedId"),
            "strategyId": forex.get("strategyId"),
            "status": forex.get("status"),
            "contenderTieBreakRequired": bool(forex.get("contenderTieBreakRequired")),
            "metrics": _safe_dict(forex.get("metrics")),
        },
        "championForwardReview": {
            "status": champion_gate.get("status"),
            "statusZh": champion_gate.get("statusZh"),
            "blockers": champion_gate.get("blockers") or [],
            "promotionDecision": {
                "canRunIsolatedTesterForwardNext": bool(
                    _safe_dict(champion_gate.get("promotionDecision")).get("canRunIsolatedTesterForwardNext")
                ),
                "canRunIsolatedTesterNow": bool(
                    _safe_dict(champion_gate.get("promotionDecision")).get("canRunIsolatedTesterNow")
                ),
                "testerLockDraftReady": bool(
                    _safe_dict(champion_gate.get("promotionDecision")).get("testerLockDraftReady")
                ),
                "canPromoteToLiveNow": False,
                "autoPromotionToLiveAllowed": False,
                "reasonZh": _safe_dict(champion_gate.get("promotionDecision")).get("reasonZh"),
            },
            "testerRequest": {
                "status": tester_request.get("status"),
                "statusZh": tester_request.get("statusZh"),
                "candidateIds": _safe_dict(tester_request.get("summary")).get("candidateIds") or [],
                "queueCount": _safe_dict(tester_request.get("summary")).get("queueCount"),
                "canMaterializeConfigHere": bool(
                    _safe_dict(tester_request.get("decision")).get("canMaterializeConfigHere")
                ),
                "canRunTerminalHere": False,
                "canPromoteToLiveHere": False,
            },
            "testerRunGate": {
                "status": tester_run_gate.get("status"),
                "statusZh": tester_run_gate.get("statusZh"),
                "blockers": _safe_dict(tester_run_gate.get("gate")).get("blockers") or [],
                "accountContextBlockers": _safe_dict(tester_run_gate.get("testerAccountContext")).get("blockers") or [],
                "nextTesterWindow": _safe_dict(tester_run_gate.get("nextTesterWindow")),
                "liveSession": {
                    "status": _safe_dict(_safe_dict(tester_run_gate.get("gate")).get("liveSession")).get("status"),
                    "ok": bool(_safe_dict(_safe_dict(tester_run_gate.get("gate")).get("liveSession")).get("ok")),
                    "openTradeCount": _safe_dict(_safe_dict(tester_run_gate.get("gate")).get("liveSession")).get("openTradeCount"),
                    "marginInUse": _safe_dict(_safe_dict(tester_run_gate.get("gate")).get("liveSession")).get("marginInUse"),
                    "tradeStatus": _safe_dict(_safe_dict(tester_run_gate.get("gate")).get("liveSession")).get("tradeStatus"),
                    "accountNumber": _safe_dict(_safe_dict(tester_run_gate.get("gate")).get("liveSession")).get("accountNumber"),
                    "server": _safe_dict(_safe_dict(tester_run_gate.get("gate")).get("liveSession")).get("server"),
                },
                "canRunIsolatedTester": bool(
                    _safe_dict(tester_run_gate.get("decision")).get("canRunIsolatedTester")
                ),
                "canRunTerminalHere": False,
            },
            "accountContextSyncPlan": {
                "status": "ACCOUNT_CONTEXT_READY" if account_context.get("ready") else "ACCOUNT_CONTEXT_SYNC_REQUIRED",
                "statusZh": (
                    "隔离 tester 账户上下文已就绪。"
                    if account_context.get("ready")
                    else "隔离 tester 账户上下文仍缺目标文件；只允许单独受控同步，不在 summary 中复制。"
                ),
                "sourceAccountContextExists": bool(_safe_dict(account_context.get("source")).get("accountContextExists")),
                "sourceServerContextExists": bool(_safe_dict(account_context.get("source")).get("serverContextExists")),
                "targetAccountContextExists": bool(_safe_dict(account_context.get("target")).get("accountContextExists")),
                "targetServerContextExists": bool(_safe_dict(account_context.get("target")).get("serverContextExists")),
                "missingTarget": account_context.get("missingTarget") or [],
                "missingSource": account_context.get("missingSource") or [],
                "sensitiveAccountContextSyncRequired": bool(account_context.get("sensitiveAccountContextSyncRequired")),
                "sensitiveCopyAllowedHere": False,
                "copiedFileCount": 0,
                "copiedTreeCount": 0,
                "separateSyncReview": _safe_dict(account_context.get("separateSyncReview")),
                "nextActionZh": account_context.get("nextActionZh")
                or "等待账户上下文预检；当前不复制敏感文件。",
            },
            "testerLockDraft": {
                "status": tester_lock_draft.get("status"),
                "statusZh": tester_lock_draft.get("statusZh"),
                "draftReadyForSeparateLockWriter": bool(
                    _safe_dict(tester_lock_draft.get("decision")).get("draftReadyForSeparateLockWriter")
                ),
                "lockFileWritten": False,
                "canRunTerminalHere": False,
            },
            "nextRequiredActionZh": (
                _safe_dict(champion_gate.get("promotionDecision")).get("reasonZh")
                or "等待隔离 Strategy Tester/forward 复验；当前不升级实盘。"
            ),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "writesLivePreset": False,
            "livePresetMutationAllowed": False,
        },
        "nextActionZh": replacement.get("nextActionZh")
        or "继续复验替代王牌候选；当前不写订单、不改 live preset。",
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "writesLivePreset": False,
        "livePresetMutationAllowed": False,
    }


def _capacity_summary(
    runtime: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
) -> dict[str, Any]:
    if primary_dashboard_json:
        gate = build_forex_live12_rsi_candidate_promotion_gate(
            runtime,
            requested_max_total_trades=requested_max_total_trades,
            primary_dashboard_json=primary_dashboard_json,
            write=True,
        )
    else:
        gate = read_forex_live12_rsi_candidate_promotion_gate(runtime)
    target = _safe_dict(gate.get("target"))
    raw = _safe_dict(gate.get("rawExpansionEvidence"))
    raw_metrics = _safe_dict(raw.get("metrics"))
    repaired = _safe_dict(gate.get("repairedCandidateEvidence"))
    repaired_metrics = _safe_dict(repaired.get("afterMetrics"))
    freshness = _safe_dict(gate.get("artifactFreshness"))
    decision = _safe_dict(gate.get("decision"))
    return {
        "requestedMaxTotalTrades": target.get("requestedMaxTotalTrades", 10),
        "sourceDashboardPath": freshness.get("primaryDashboardPath"),
        "sourceDashboardMtimeIso": freshness.get("primaryDashboardMtimeIso"),
        "sourceCloseHistoryPath": freshness.get("closeHistoryPath"),
        "sourceCloseHistoryMtimeIso": freshness.get("closeHistoryMtimeIso"),
        "currentStage": target.get("currentStage"),
        "directJumpToTargetStatus": target.get("directJumpToTargetStatus"),
        "rawExpansionStage": raw.get("rawExpansionStage"),
        "rawBlockerCodes": raw.get("blockerCodes") or [],
        "rawNaturalClosedTrades": raw_metrics.get("naturalClosedTrades"),
        "rawProfitFactor": raw_metrics.get("profitFactor"),
        "rawMaxConsecutiveLosses": raw_metrics.get("maxConsecutiveLosses"),
        "repairedCandidateStage": repaired.get("validationStage"),
        "repairedNaturalClosedTrades": repaired_metrics.get("naturalClosedTrades"),
        "repairedProfitFactor": repaired_metrics.get("profitFactor"),
        "repairedMaxConsecutiveLosses": repaired_metrics.get("maxConsecutiveLosses"),
        "candidateId": repaired.get("candidateId"),
        "candidateReadyForTesterValidation": bool(decision.get("candidateReadyForTesterValidation")),
        "nextRecommendedMaxTotalTrades": decision.get("nextRecommendedMaxTotalTrades"),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5Preset": False,
    }


def _minimal_diff_summary(runtime: Path) -> dict[str, Any]:
    diff = build_release_minimal_diff_review(runtime, write=False)
    package = _safe_dict(diff.get("reviewPackage"))
    proposed_changes = [
        row for row in _safe_list(package.get("proposedChanges")) if isinstance(row, dict)
    ]
    release_tokens = [
        row for row in _safe_list(package.get("releaseTokens")) if isinstance(row, dict)
    ]
    return {
        "status": diff.get("status"),
        "statusZh": diff.get("statusZh"),
        "profitTargetReached": bool(diff.get("profitTargetReached")),
        "releaseBlockedCount": diff.get("releaseBlockedCount"),
        "executionModeBlockedCount": diff.get("executionModeBlockedCount"),
        "changeCount": package.get("changeCount", len(proposed_changes)),
        "releaseTokenCount": package.get("releaseTokenCount", len(release_tokens)),
        "proposedChanges": proposed_changes,
        "releaseTokens": release_tokens,
        "canApplyDiffNow": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesStartupConfig": False,
        "writesMt5Preset": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
    }


def _signoff_handoff_summary(runtime: Path) -> dict[str, Any]:
    handoff = build_release_token_signoff_handoff(runtime, write=False)
    return {
        "status": handoff.get("status"),
        "statusZh": handoff.get("statusZh"),
        "releaseTokenCount": handoff.get("releaseTokenCount"),
        "readyForInputCount": handoff.get("readyForInputCount"),
        "completeSignoffCount": handoff.get("completeSignoffCount"),
        "missingSignoffCount": handoff.get("missingSignoffCount"),
        "missingSignoffRows": handoff.get("missingSignoffRows") or [],
        "handoffInstructions": handoff.get("handoffInstructions") or [],
        "canProceedToLiveExecutionHere": False,
        "canAcceptSignoffHere": False,
        "canMintTokenHere": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "livePresetMutationAllowed": False,
    }


def _signoff_evidence_matrix_summary(runtime: Path) -> dict[str, Any]:
    try:
        matrix = build_release_token_signoff_evidence_matrix(runtime, write=False)
    except Exception as exc:
        return {
            "status": "SIGNOFF_EVIDENCE_MATRIX_UNAVAILABLE_REVIEW_ONLY",
            "statusZh": "release signoff evidence matrix 暂不可生成；summary 保持 review-only",
            "readError": str(exc),
            "releaseTokenCount": None,
            "completeSignoffCount": None,
            "acknowledgementReadyCount": None,
            "acknowledgementCount": None,
            "gatesWithCompleteEvidence": None,
            "acknowledgementRows": [],
            "gateRows": [],
            "canAcceptSignoffHere": False,
            "canMintTokenHere": False,
            "canReleaseExecutionNow": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "requestFilesWritten": False,
            "brokerCallsMade": False,
            "livePresetMutationAllowed": False,
        }
    return {
        "status": matrix.get("status"),
        "statusZh": matrix.get("statusZh"),
        "releaseTokenCount": matrix.get("releaseTokenCount"),
        "completeSignoffCount": matrix.get("completeSignoffCount"),
        "acknowledgementReadyCount": matrix.get("acknowledgementReadyCount"),
        "acknowledgementCount": matrix.get("acknowledgementCount"),
        "gatesWithCompleteEvidence": matrix.get("gatesWithCompleteEvidence"),
        "acknowledgementRows": matrix.get("acknowledgementRows") or [],
        "gateRows": matrix.get("gateRows") or [],
        "canAcceptSignoffHere": False,
        "canMintTokenHere": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "livePresetMutationAllowed": False,
    }


def _release_token_evidence_summary(runtime: Path) -> dict[str, Any]:
    evidence = build_release_token_evidence_review(runtime, write=False)
    return {
        "status": evidence.get("status"),
        "statusZh": evidence.get("statusZh"),
        "sourceReleaseMinimalDiffReviewPath": evidence.get("sourceReleaseMinimalDiffReviewPath"),
        "releaseTokenCount": evidence.get("releaseTokenCount"),
        "tokenOrEvidenceMissingCount": evidence.get("tokenOrEvidenceMissingCount"),
        "incompleteEvidenceCount": evidence.get("incompleteEvidenceCount"),
        "evidenceCompleteCount": evidence.get("evidenceCompleteCount"),
        "noSideEffectEvidenceCompleteCount": evidence.get("noSideEffectEvidenceCompleteCount"),
        "tokenProvidedCount": evidence.get("tokenProvidedCount"),
        "tokenMissingCount": evidence.get("tokenMissingCount"),
        "tokenMissingOnly": bool(evidence.get("tokenMissingOnly")),
        "releaseTokenMissingOnlyAfterEvidenceComplete": bool(
            evidence.get("releaseTokenMissingOnlyAfterEvidenceComplete")
            or evidence.get("tokenMissingOnly")
        ),
        "releaseBlockerClass": evidence.get("releaseBlockerClass"),
        "manualReleaseReviewReadyCount": evidence.get("manualReleaseReviewReadyCount"),
        "manualReleaseReviewStatus": evidence.get("manualReleaseReviewStatus"),
        "blockedReleaseTokenCodes": evidence.get("blockedReleaseTokenCodes") or [],
        "canReleaseExecutionNow": False,
        "releaseTokenCanBeAutoMinted": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
    }


def build_sim_target_execution_review_summary(
    runtime_dir: Path,
    *,
    target_usd: float = 50.0,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    profit_tracker = _read_or_build_profit_tracker(runtime, target_usd)
    live_review = _safe_dict(profit_tracker.get("liveExecutionReview"))
    cutover_review = read_live_execution_cutover_review(runtime)
    if cutover_review.get("schema") != "quantgod.live_execution_cutover_review.v1":
        cutover_review = build_live_execution_cutover_review(runtime, write=False)
    release_readiness = read_release_readiness_refresh(runtime)
    if not _safe_dict(release_readiness.get("executionReleaseReadinessPacket")):
        release_readiness = build_release_readiness_refresh(runtime, write=False)
    release_packet = _safe_dict(live_review.get("executionReleaseReadinessPacket")) or _safe_dict(
        release_readiness.get("executionReleaseReadinessPacket")
    )
    post_target_execution = _safe_dict(release_readiness.get("postTargetExecutionSummary"))
    minimal_diff = _minimal_diff_summary(runtime)
    release_token_evidence = _release_token_evidence_summary(runtime)
    signoff_handoff = _signoff_handoff_summary(runtime)
    signoff_evidence_matrix = _signoff_evidence_matrix_summary(runtime)
    capacity = _capacity_summary(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
    )
    capacity["requestedMaxTotalTrades"] = requested_max_total_trades
    payload = {
        "ok": True,
        "schema": SIM_TARGET_EXECUTION_REVIEW_SUMMARY_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": "TARGET_REACHED_WAITING_EXECUTION_MODE"
        if profit_tracker.get("targetReached")
        else "WAITING_FOR_SIM_TARGET",
        "statusZh": "模拟收益目标已达成，但实盘执行模式仍未打开"
        if profit_tracker.get("targetReached")
        else "仍在等待模拟收益目标达成",
        "request": {
            "targetUsd": round(float(target_usd), 2),
            "requestedMaxTotalTrades": int(requested_max_total_trades),
            "requestedPositionExpansionRecorded": True,
        },
        "targetEvidence": {
            "targetReached": bool(profit_tracker.get("targetReached")),
            "combinedVerifiedUsdProfit": _safe_dict(profit_tracker.get("combinedTarget")).get("combinedVerifiedUsdProfit"),
            "combinedTargetStatus": _safe_dict(profit_tracker.get("combinedTarget")).get("status"),
            "combinedTargetStatusZh": _safe_dict(profit_tracker.get("combinedTarget")).get("statusZh"),
            "laneSummaries": _lane_summaries(profit_tracker),
        },
        "aceStrategyUpgradeReview": _ace_strategy_upgrade_summary(runtime),
        "capacityExpansionEvidence": capacity,
        "executionReview": {
            "status": live_review.get("status") or cutover_review.get("status") or post_target_execution.get("status"),
            "statusZh": live_review.get("statusZh") or cutover_review.get("statusZh") or post_target_execution.get("statusZh"),
            "cutoverStatus": live_review.get("cutoverStatus") or cutover_review.get("status"),
            "dataPlaneReady": bool(
                live_review.get("dataPlaneCutoverReady")
                or cutover_review.get("dataPlaneCutoverReady")
                or post_target_execution.get("dataPlaneReady")
            ),
            "disabledFirstImplementationWorkReady": bool(live_review.get("disabledFirstImplementationWorkReady")),
            "executionModeOnlyBlocked": bool(
                live_review.get("executionModeOnlyBlocked")
                or live_review.get("cutoverExecutionModeOnlyBlocked")
                or cutover_review.get("executionModeOnlyBlocked")
                or post_target_execution.get("executionModeOnlyBlocked")
            ),
            "releaseReady": bool(release_packet.get("releaseReady")),
            "blockedReleaseGateCount": _safe_dict(release_packet.get("releaseGateSummary")).get("blocked"),
            "topBlockers": _ranked_blockers(
                profit_tracker,
                release_packet=release_packet,
                cutover_review=cutover_review,
            ),
            "minimalDiffReview": minimal_diff,
            "releaseTokenEvidenceReview": release_token_evidence,
            "signoffHandoff": signoff_handoff,
            "signoffEvidenceMatrix": signoff_evidence_matrix,
            "primaryActionableBlocker": live_review.get("primaryActionableBlocker"),
        },
        "decision": {
            "summaryReadyForDashboard": True,
            "safeAutomationCanContinue": True,
            "targetReachedButLiveStillForbidden": bool(profit_tracker.get("targetReached")),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "writesMt5OrderRequest": False,
            "livePresetMutationAllowed": False,
            "requestFilesWritten": False,
            "receiptFilesWritten": False,
            "brokerCallsMade": False,
            "nextRequiredActionZh": "收益目标和仓位目标已记录；继续自动刷新 execution-mode、release-token、tester 与 no-side-effect 证据。这里不写订单、不改实盘 preset。",
        },
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = sim_target_execution_review_summary_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_sim_target_execution_review_summary(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = sim_target_execution_review_summary_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_sim_target_execution_review_summary(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": SIM_TARGET_EXECUTION_REVIEW_SUMMARY_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "sim target execution review summary artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_sim_target_execution_review_summary(runtime, write=False)
