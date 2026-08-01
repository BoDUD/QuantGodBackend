from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approval import (
    build_dry_run_live_execution_plan,
    build_live_operator_approval_evidence_review,
    read_dry_run_live_execution_plan,
    read_live_operator_approval_evidence_review,
)
from .approval_context import operator_approval_json_for_refresh
from .schema import (
    EXECUTION_LANE_SPEC_SCHEMA_VERSION,
    RELEASE_READINESS_REFRESH_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    execution_lane_spec_path,
    release_readiness_refresh_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def _approved_intents(plan: dict[str, Any], approved_lanes: set[str]) -> list[dict[str, Any]]:
    lane_aliases = {
        "usdjpyMt5": "USDJPY_MT5",
    }
    approved_lane_codes = {lane_aliases.get(lane, lane) for lane in approved_lanes}
    intents = []
    for intent in _safe_list(plan.get("dryRunIntents")):
        if not isinstance(intent, dict):
            continue
        lane = str(intent.get("lane") or "")
        if lane in approved_lane_codes:
            intents.append(intent)
    return intents


def _lane_symbol_contract(intent: dict[str, Any]) -> dict[str, Any]:
    risk_limits = _safe_dict(intent.get("riskLimits"))
    return {
        "lane": intent.get("lane") or "",
        "canonicalSymbol": intent.get("canonicalSymbol") or "",
        "brokerSymbol": intent.get("brokerSymbol") or "",
        "sideMode": intent.get("side") or "",
        "orderTypeMode": intent.get("orderType") or "",
        "volumeLots": intent.get("volumeLots", 0.0),
        "riskLimits": {
            "maxNotionalUsd": risk_limits.get("maxNotionalUsd", 0.0),
            "maxDailyLossPct": risk_limits.get("maxDailyLossPct", 1.0),
            "maxDailyLossR": risk_limits.get("maxDailyLossR", 1.0),
            "maxConsecutiveLosses": risk_limits.get("maxConsecutiveLosses", 2),
            "priceDiffProtectionPct": risk_limits.get("priceDiffProtectionPct"),
            "normalSpreadOnly": risk_limits.get("normalSpreadOnly", True),
            "newsNoneOnly": risk_limits.get("newsNoneOnly", True),
        },
        "dryRunIntentId": intent.get("intentId") or "",
    }


def _read_release_readiness_artifact(runtime_dir: Path) -> dict[str, Any]:
    path = release_readiness_refresh_path(Path(runtime_dir))
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {
            "ok": False,
            "schema": RELEASE_READINESS_REFRESH_SCHEMA_VERSION,
            "status": "MISSING",
            "path": str(path),
            "safety": dict(SAFETY),
        }
    except Exception as exc:
        return {
            "ok": False,
            "schema": RELEASE_READINESS_REFRESH_SCHEMA_VERSION,
            "status": "INVALID",
            "path": str(path),
            "readError": str(exc),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return {
        "ok": False,
        "schema": RELEASE_READINESS_REFRESH_SCHEMA_VERSION,
        "status": "INVALID",
        "path": str(path),
        "safety": dict(SAFETY),
    }


def _post_target_release_audit(release_readiness: dict[str, Any]) -> dict[str, Any]:
    post_target = _safe_dict(release_readiness.get("postTargetExecutionSummary"))
    profit_target = _safe_dict(post_target.get("profitTarget"))
    release_summary = _safe_dict(
        post_target.get("releaseGateSummary") or release_readiness.get("executionReleaseGateSummary")
    )
    activation_summary = _safe_dict(
        post_target.get("activationGateSummary") or release_readiness.get("executionActivationGateSummary")
    )
    file_blockers = _safe_list(release_readiness.get("fileEvidenceBlockers"))
    blocked_release_codes = _safe_list(
        post_target.get("blockedReleaseTokenCodes")
        or release_summary.get("blockerCodes")
        or _safe_dict(release_readiness.get("executionReleaseReadinessPacket")).get("blockedReleaseTokenCodes")
    )
    execution_mode_codes = _safe_list(post_target.get("executionModeBlockerCodes")) or [
        str(row.get("code") or "") for row in file_blockers if isinstance(row, dict)
    ]
    target_reached = bool(profit_target.get("targetReached"))
    release_blocked = int(release_summary.get("blocked") or len(blocked_release_codes) or 0)
    activation_blocked = int(activation_summary.get("blocked") or len(execution_mode_codes) or 0)
    primary_blocker = (
        _safe_dict(post_target.get("primaryActionableBlocker"))
        or _safe_dict(release_readiness.get("primaryActionableBlocker"))
        or (file_blockers[0] if file_blockers and isinstance(file_blockers[0], dict) else {})
    )
    release_artifact_present = bool(release_readiness.get("schema") == RELEASE_READINESS_REFRESH_SCHEMA_VERSION)
    if target_reached and (release_blocked or activation_blocked):
        status = "TARGET_REACHED_EXECUTION_RELEASE_BLOCKED"
        status_zh = f"收益已达标，但 {release_blocked} 个 release token 和 {activation_blocked} 个 MT5 执行模式闸门仍未释放"
    elif target_reached:
        status = "TARGET_REACHED_WAITING_RELEASE_REVIEW"
        status_zh = "收益已达标，等待 execution release 评审证据"
    elif release_artifact_present:
        status = "WAITING_PROFIT_TARGET_EVIDENCE"
        status_zh = "等待收益目标证据"
    else:
        status = "WAITING_RELEASE_READINESS_REFRESH"
        status_zh = "等待 release-readiness refresh artifact"
    return {
        "schema": "quantgod.execution_lane_post_target_release_audit.v1",
        "status": status,
        "statusZh": status_zh,
        "releaseReadinessArtifactPresent": release_artifact_present,
        "profitTargetReached": target_reached,
        "combinedVerifiedUsdProfit": profit_target.get("combinedVerifiedUsdProfit"),
        "qualifyingLaneIds": _safe_list(profit_target.get("qualifyingLaneIds")),
        "releaseBlockedCount": release_blocked,
        "activationBlockedCount": activation_blocked,
        "blockedReleaseTokenCodes": blocked_release_codes,
        "executionModeBlockerCodes": execution_mode_codes,
        "primaryActionableBlocker": primary_blocker,
        "dataPlaneReady": bool(post_target.get("dataPlaneReady")),
        "executionModeOnlyBlocked": bool(post_target.get("executionModeOnlyBlocked")),
        "releaseReady": False,
        "executionReady": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
        "livePresetMutationAllowed": False,
        "nextSafeActions": [
            "refresh_release_readiness_artifact",
            "review_release_token_gaps",
            "surface_review_only_preset_diff",
            "rerun_no_side_effect_contract_tests",
        ],
        "forbiddenUntilRelease": _safe_list(post_target.get("forbiddenUntilRelease")) or [
            "write_mt5_order_request",
            "read_or_consume_mt5_order_request",
            "call_mt5_order_send",
            "write_live_receipt",
            "mutate_live_preset_or_startup_config",
        ],
    }


def _authorization_boundary_from_approval(approval_review: dict[str, Any]) -> dict[str, Any]:
    boundary = _safe_dict(approval_review.get("authorizationBoundary"))
    if boundary:
        return boundary
    accepted = bool(approval_review.get("operatorApprovalProvided"))
    return {
        "schema": "quantgod.authorization_boundary.v1",
        "chatAuthorizationAcknowledged": True,
        "chatAuthorizationSource": "current_codex_thread_user_messages",
        "chatAuthorizationCanUnlockLiveExecution": False,
        "operatorApprovalJsonProvided": bool(approval_review.get("operatorApprovalJsonPath")),
        "operatorApprovalEvidenceAccepted": accepted,
        "operatorApprovalJsonCanUnlockLiveExecution": False,
        "releaseTokensStillRequired": True,
        "executionModeProofStillRequired": True,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
        "reasonZh": "聊天授权和机器可读审批证据都不能单独打开真实下单；仍需 release token 与 MT5 执行模式证据。",
    }


def build_live_execution_lane_spec(
    runtime_dir: Path,
    *,
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    should_rebuild = bool(
        refresh_sources
        or operator_approval_json
        or extra_bases_roots
    )
    approval_review = (
        build_live_operator_approval_evidence_review(
            runtime_dir,
            write=bool(write and refresh_sources),
            refresh_sources=refresh_sources,
            operator_approval_json=operator_approval_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_live_operator_approval_evidence_review(runtime_dir)
    )
    dry_run_plan = (
        build_dry_run_live_execution_plan(
            runtime_dir,
            write=bool(write and refresh_sources),
            refresh_sources=refresh_sources,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_dry_run_live_execution_plan(runtime_dir)
    )
    release_readiness = _read_release_readiness_artifact(runtime_dir)
    post_target_release_audit = _post_target_release_audit(release_readiness)
    authorization_boundary = _authorization_boundary_from_approval(approval_review)
    approved_lanes = {str(item) for item in _safe_list(approval_review.get("approvedLanes"))}
    approval_accepted = bool(approval_review.get("operatorApprovalProvided"))
    dry_run_intents = _approved_intents(dry_run_plan, approved_lanes)
    blockers: list[dict[str, Any]] = []
    if not approval_accepted:
        approval_blockers = [
            item for item in _safe_list(approval_review.get("blockers"))
            if isinstance(item, dict)
        ]
        blockers.extend(approval_blockers or [_blocker("OPERATOR_APPROVAL_EVIDENCE_REQUIRED", "缺少已验收的 operator approval evidence。")])
    if not dry_run_intents:
        blockers.append(_blocker("DRY_RUN_INTENTS_REQUIRED", "缺少与已审批 lane 匹配的 dry-run intent。", sorted(approved_lanes)))

    ready_for_implementation_review = bool(approval_accepted and dry_run_intents and not blockers)
    payload = {
        "ok": True,
        "schema": EXECUTION_LANE_SPEC_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "READY_FOR_EXECUTION_LANE_IMPLEMENTATION_REVIEW" if ready_for_implementation_review else "WAITING_EXECUTION_LANE_SPEC_INPUTS",
        "statusZh": "可进入真实执行 lane 实现评审" if ready_for_implementation_review else "等待审批证据和 dry-run intents",
        "readyForImplementationReview": ready_for_implementation_review,
        "executionReady": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "approvalEvidenceAccepted": approval_accepted,
        "authorizationBoundary": authorization_boundary,
        "postTargetReleaseAudit": post_target_release_audit,
        "reviewPacketHash": approval_review.get("reviewPacketHash", ""),
        "approvedLanes": sorted(approved_lanes),
        "approvedDryRunIntentCount": len(dry_run_intents),
        "laneContracts": [_lane_symbol_contract(intent) for intent in dry_run_intents],
        "implementationContract": {
            "adapterName": "MT5_LIVE_EXECUTION_LANE_FUTURE_REVIEW_REQUIRED",
            "inputSchema": "quantgod.mt5_reviewed_order_intent.v1",
            "outputSchema": "quantgod.mt5_execution_receipt.v1",
            "credentialMode": "external_env_reference_only",
            "storesCredentials": False,
            "writesMt5OrderRequest": False,
            "mt5PendingOrderIntentsWritten": False,
            "orderSendAllowed": False,
            "brokerExecutionAllowed": False,
            "requiredBeforeCodeCanWriteOrders": [
                "separate_execution_lane_code_review",
                "mt5_ea_order_request_contract_review",
                "operator_approval_evidence_review",
                "dry_run_intent_replay_success",
                "kill_switch_runtime_probe",
                "daily_loss_runtime_probe",
                "spread_slippage_runtime_probe",
                "broker_account_and_symbol_mapping_probe",
            "rollback_and_auto_disable_probe",
            "post_target_release_audit_clear",
        ],
            "forbiddenInThisSpec": [
                "direct MT5 order API calls",
                "async MT5 order API calls",
                "MQL trade helper classes",
                "position close calls",
                "MT5 order request file writes",
                "wallet authorization",
                "credential storage",
                "live preset mutation",
            ],
        },
        "runtimeProbesRequired": {
            "killSwitchOk": False,
            "dailyLossOk": False,
            "spreadSlippageOk": False,
            "symbolMappingOk": False,
            "accountModeOk": False,
            "operatorApprovalStillCurrent": approval_accepted,
        },
        "blockers": blockers,
        "nextRequiredActionZh": (
            "进入单独 execution lane 代码评审；只有评审通过后才能考虑 MT5 写单实现。"
            if ready_for_implementation_review
            else "先让 review candidate、operator approval evidence 和 dry-run intents 全部就绪。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = execution_lane_spec_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_execution_lane_spec(runtime_dir: Path) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    path = execution_lane_spec_path(runtime_dir)
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                if not isinstance(payload.get("postTargetReleaseAudit"), dict):
                    payload["postTargetReleaseAudit"] = _post_target_release_audit(
                        _read_release_readiness_artifact(runtime_dir)
                    )
                if not isinstance(payload.get("authorizationBoundary"), dict):
                    payload["authorizationBoundary"] = _authorization_boundary_from_approval(
                        read_live_operator_approval_evidence_review(runtime_dir)
                    )
                assert_no_execution_flags(payload)
                return payload
        except Exception:
            pass
    return build_live_execution_lane_spec(runtime_dir, write=False)
