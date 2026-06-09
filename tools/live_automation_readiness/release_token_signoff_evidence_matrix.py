from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .broker_order_send import build_broker_order_send_review, read_broker_order_send_review
from .live_execution_rollback import build_live_execution_rollback_review, read_live_execution_rollback_review
from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
from .release_minimal_diff_review import build_release_minimal_diff_review, read_release_minimal_diff_review
from .release_token_evidence_review import build_release_token_evidence_review, read_release_token_evidence_review
from .release_token_signoff_handoff import build_release_token_signoff_handoff
from .schema import (
    RELEASE_TOKEN_SIGNOFF_EVIDENCE_MATRIX_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    broker_order_send_review_path,
    live_execution_rollback_review_path,
    release_minimal_diff_review_path,
    release_token_evidence_review_path,
    release_token_signoff_evidence_matrix_path,
    runtime_preflight_path,
    utc_now_iso,
)


ACKNOWLEDGEMENTS = [
    "acknowledgeNoSideEffectEvidence",
    "acknowledgeKillSwitch",
    "acknowledgeRollback",
    "acknowledgeRiskLimits",
    "acknowledgeExecutionModeSeparatelyReviewed",
]


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status_row(
    key: str,
    *,
    status: str,
    status_zh: str,
    evidence_ready: bool,
    source_artifact: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "acknowledgement": key,
        "status": status,
        "statusZh": status_zh,
        "evidenceReadyForSignoff": bool(evidence_ready),
        "sourceArtifact": source_artifact,
        "details": details or {},
        "canAcceptSignoffHere": False,
        "canMintTokenHere": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _check_passed(rows: list[Any], check_id: str) -> bool:
    for row in rows:
        if isinstance(row, dict) and row.get("id") == check_id:
            return bool(row.get("passed"))
    return False


def _no_side_effect_row(evidence: dict[str, Any]) -> dict[str, Any]:
    total = int(evidence.get("releaseTokenCount") or 0)
    no_side_effect_count = int(evidence.get("noSideEffectEvidenceCompleteCount") or 0)
    token_missing_count = int(evidence.get("tokenMissingCount") or 0)
    ready = total > 0 and no_side_effect_count == total
    token_missing_only = bool(evidence.get("tokenMissingOnly")) or (
        ready
        and token_missing_count == total
        and int(evidence.get("tokenProvidedCount") or 0) == 0
    )
    missing_only_after_evidence = bool(
        evidence.get("releaseTokenMissingOnlyAfterEvidenceComplete")
        or token_missing_only
    )
    return _status_row(
        "acknowledgeNoSideEffectEvidence",
        status="READY" if ready else "WAITING_NO_SIDE_EFFECT_EVIDENCE",
        status_zh=(
            f"无副作用证据已完成 {no_side_effect_count}/{total}；release token 仍缺 {token_missing_count}"
            if ready
            else f"无副作用证据不足：{no_side_effect_count}/{total}"
        ),
        evidence_ready=ready,
        source_artifact="releaseTokenEvidenceReview",
        details={
            "releaseTokenCount": total,
            "tokenOrEvidenceMissingCount": evidence.get("tokenOrEvidenceMissingCount"),
            "incompleteEvidenceCount": evidence.get("incompleteEvidenceCount"),
            "noSideEffectEvidenceCompleteCount": no_side_effect_count,
            "tokenProvidedCount": evidence.get("tokenProvidedCount"),
            "tokenMissingCount": token_missing_count,
            "tokenMissingOnly": token_missing_only,
            "releaseTokenMissingOnlyAfterEvidenceComplete": missing_only_after_evidence,
            "releaseBlockerClass": evidence.get("releaseBlockerClass"),
            "manualReleaseReviewReadyCount": evidence.get("manualReleaseReviewReadyCount"),
        },
    )


def _kill_switch_row(preflight: dict[str, Any], broker: dict[str, Any]) -> dict[str, Any]:
    probe = _safe_dict(preflight.get("probeResults"))
    broker_plans = [row for row in _safe_list(broker.get("brokerSendPlans")) if isinstance(row, dict)]
    broker_requires_kill_switch = bool(broker_plans) and all(
        bool(row.get("killSwitchRequired")) for row in broker_plans
    )
    preflight_ok = bool(probe.get("killSwitchOk"))
    ready = preflight_ok and (broker_requires_kill_switch or not broker_plans)
    return _status_row(
        "acknowledgeKillSwitch",
        status="READY" if ready else "WAITING_KILL_SWITCH_EVIDENCE",
        status_zh=(
            "kill switch 运行时探针与 broker wrapper 强制项已就绪"
            if ready
            else "kill switch 证据不足或 broker wrapper 未证明强制检查"
        ),
        evidence_ready=ready,
        source_artifact="runtimePreflight+brokerOrderSendReview",
        details={
            "preflightStatus": preflight.get("status"),
            "killSwitchOk": preflight_ok,
            "brokerOrderSendStatus": broker.get("status"),
            "brokerPlanCount": len(broker_plans),
            "brokerRequiresKillSwitch": broker_requires_kill_switch,
        },
    )


def _rollback_row(rollback: dict[str, Any]) -> dict[str, Any]:
    checklist = _safe_list(rollback.get("rollbackChecklist"))
    matrix = _safe_list(rollback.get("rollbackMatrix"))
    checklist_passed = bool(checklist) and all(bool(row.get("passed")) for row in checklist if isinstance(row, dict))
    matrix_passed = bool(matrix) and all(bool(row.get("passed")) for row in matrix if isinstance(row, dict))
    data_plane_ready = bool(rollback.get("dataPlaneRollbackReady"))
    blocker_codes = [
        str(row.get("code") or "")
        for row in _safe_list(rollback.get("blockers"))
        if isinstance(row, dict)
    ]
    allowed_wait_codes = {
        "EXECUTION_MODE_GATES_NOT_ACTIVE",
        "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
        "MT5_READ_ONLY_MODE_STILL_ACTIVE",
        "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
        "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
        "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF",
        "DEPLOYED_PRESET_READ_ONLY_TRUE",
        "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF",
        "DEPLOYED_PRESET_EA_REQUEST_READER_OFF",
        "ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING",
    }
    execution_wait_only = (
        data_plane_ready
        and bool(rollback.get("executionModeOnlyBlocked"))
        and bool(checklist)
        and bool(matrix)
        and _check_passed(checklist, "no_execution_side_effects_in_rollback_review")
        and all(code in allowed_wait_codes for code in blocker_codes if code)
    )
    ready = (data_plane_ready and checklist_passed and matrix_passed) or execution_wait_only
    return _status_row(
        "acknowledgeRollback",
        status="READY" if ready else "PARTIAL_ROLLBACK_EVIDENCE",
        status_zh=(
            "rollback/auto-disable 数据面已就绪；仍等待执行闸门或 release token"
            if ready
            else "rollback/auto-disable 证据仍不完整"
        ),
        evidence_ready=ready,
        source_artifact="liveExecutionRollbackReview",
        details={
            "rollbackStatus": rollback.get("status"),
            "dataPlaneRollbackReady": data_plane_ready,
            "executionModeOnlyBlocked": bool(rollback.get("executionModeOnlyBlocked")),
            "releaseTokenProvided": bool(rollback.get("releaseTokenProvided")),
            "checklistCount": len(checklist),
            "matrixCount": len(matrix),
            "checklistPassed": checklist_passed,
            "matrixPassed": matrix_passed,
            "executionWaitOnly": execution_wait_only,
            "blockerCodes": blocker_codes,
        },
    )


def _risk_limits_row(preflight: dict[str, Any], broker: dict[str, Any]) -> dict[str, Any]:
    probe = _safe_dict(preflight.get("probeResults"))
    checklist = _safe_list(broker.get("brokerOrderSendChecklist")) or _safe_list(broker.get("checklist"))
    risk_controls_ok = _check_passed(checklist, "risk_controls_required")
    request_fuses_ok = _check_passed(checklist, "request_fuses_bound")
    ready = bool(probe.get("riskLimitsOk")) and risk_controls_ok and request_fuses_ok
    return _status_row(
        "acknowledgeRiskLimits",
        status="READY" if ready else "WAITING_RISK_LIMIT_EVIDENCE",
        status_zh=(
            "risk limits、request fuses、lot/position/daily loss/spread/slippage/receipt 控制已就绪"
            if ready
            else "risk limits 或 broker wrapper 风控证据未齐"
        ),
        evidence_ready=ready,
        source_artifact="runtimePreflight+brokerOrderSendReview",
        details={
            "preflightStatus": preflight.get("status"),
            "riskLimitsOk": bool(probe.get("riskLimitsOk")),
            "brokerOrderSendStatus": broker.get("status"),
            "riskControlsRequiredPassed": risk_controls_ok,
            "requestFusesBoundPassed": request_fuses_ok,
        },
    )


def _execution_mode_row(diff: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    package = _safe_dict(diff.get("reviewPackage"))
    proposed_changes = [row for row in _safe_list(package.get("proposedChanges")) if isinstance(row, dict)]
    review_ready = diff.get("status") == "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW"
    release_blocked = int(diff.get("releaseBlockedCount") or 0)
    execution_blocked = int(diff.get("executionModeBlockedCount") or 0)
    complete_signoff_count = int(handoff.get("completeSignoffCount") or 0)
    release_token_count = int(handoff.get("releaseTokenCount") or 0)
    handoff_ready = (
        handoff.get("status") == "SIGNOFF_HANDOFF_READY_FOR_SEPARATE_RELEASE_LANE"
        and release_token_count > 0
        and complete_signoff_count == release_token_count
        and not _safe_list(handoff.get("forbiddenSecretFieldPaths"))
    )
    evidence_ready = bool(review_ready and handoff_ready)
    status = (
        "SEPARATE_SIGNOFF_INPUT_READY_FOR_RELEASE_LANE"
        if evidence_ready
        else "REVIEW_PACKAGE_READY_WAITING_SEPARATE_SIGNOFF"
        if review_ready
        else "WAITING_EXECUTION_MODE_REVIEW_PACKAGE"
    )
    return _status_row(
        "acknowledgeExecutionModeSeparatelyReviewed",
        status=status,
        status_zh=(
            f"执行模式最小 diff 与 {complete_signoff_count}/{release_token_count} 个签收输入已完整；仍只可交给独立 release lane"
            if evidence_ready
            else
            f"最小 diff 审查包已生成，仍待单独复核：{len(proposed_changes)} 项变更、{release_blocked} 个 token、{execution_blocked} 个执行闸门"
            if review_ready
            else "执行模式最小 diff 审查包尚未就绪"
        ),
        evidence_ready=evidence_ready,
        source_artifact="releaseMinimalDiffReview",
        details={
            "minimalDiffStatus": diff.get("status"),
            "profitTargetReached": bool(diff.get("profitTargetReached")),
            "proposedChangeCount": len(proposed_changes),
            "releaseBlockedCount": release_blocked,
            "executionModeBlockedCount": execution_blocked,
            "proposedChangeKeys": [row.get("key") for row in proposed_changes],
            "signoffHandoffStatus": handoff.get("status", ""),
            "completeSignoffCount": complete_signoff_count,
            "releaseTokenCount": release_token_count,
            "forbiddenSecretFieldCount": len(_safe_list(handoff.get("forbiddenSecretFieldPaths"))),
        },
    )


def _gate_matrix_rows(
    evidence: dict[str, Any],
    acknowledgement_rows: list[dict[str, Any]],
    *,
    all_input_complete: bool = False,
) -> list[dict[str, Any]]:
    ack_by_key = {row["acknowledgement"]: row for row in acknowledgement_rows}
    manual_rows = [row for row in _safe_list(evidence.get("manualReleaseReviewRows")) if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    for row in manual_rows:
        missing = [
            key
            for key in ACKNOWLEDGEMENTS
            if not _safe_dict(ack_by_key.get(key)).get("evidenceReadyForSignoff")
        ]
        status = (
            "EVIDENCE_AND_INPUT_READY_FOR_SEPARATE_RELEASE_LANE"
            if not missing and all_input_complete
            else "EVIDENCE_READY_WAITING_SIGNOFF_INPUT"
            if not missing
            else "WAITING_SIGNOFF_EVIDENCE"
        )
        rows.append({
            "gateId": row.get("gateId", ""),
            "labelZh": row.get("labelZh", ""),
            "tokenName": row.get("tokenName", ""),
            "blockerCode": row.get("blockerCode", ""),
            "sourceArtifactPath": row.get("sourceArtifactPath", ""),
            "sideEffectZh": row.get("sideEffectZh", ""),
            "readyForSeparateSignoffReview": bool(row.get("readyForSeparateSignoffReview")),
            "evidenceAcknowledgements": {
                key: bool(_safe_dict(ack_by_key.get(key)).get("evidenceReadyForSignoff"))
                for key in ACKNOWLEDGEMENTS
            },
            "missingEvidenceAcknowledgements": missing,
            "status": status,
            "canAcceptSignoffHere": False,
            "canMintTokenHere": False,
            "canReleaseExecutionNow": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })
    return rows


def build_release_token_signoff_evidence_matrix(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    evidence = read_release_token_evidence_review(runtime)
    if not _safe_list(evidence.get("manualReleaseReviewRows")):
        evidence = build_release_token_evidence_review(runtime, write=False)
    preflight = read_live_runtime_preflight_probe(runtime)
    if preflight.get("schema") != "quantgod.live_runtime_preflight_probe.v1":
        preflight = build_live_runtime_preflight_probe(runtime, write=False)
    broker = read_broker_order_send_review(runtime)
    if broker.get("schema") != "quantgod.broker_order_send_review.v1":
        broker = build_broker_order_send_review(runtime, write=False)
    rollback = read_live_execution_rollback_review(runtime)
    if rollback.get("schema") != "quantgod.live_execution_rollback_review.v1":
        rollback = build_live_execution_rollback_review(runtime, write=False)
    diff = read_release_minimal_diff_review(runtime)
    if not _safe_dict(diff.get("reviewPackage")):
        diff = build_release_minimal_diff_review(runtime, write=False)
    handoff = build_release_token_signoff_handoff(runtime, write=False)

    acknowledgement_rows = [
        _no_side_effect_row(evidence),
        _kill_switch_row(preflight, broker),
        _rollback_row(rollback),
        _risk_limits_row(preflight, broker),
        _execution_mode_row(diff, handoff),
    ]
    ready_count = sum(1 for row in acknowledgement_rows if row.get("evidenceReadyForSignoff"))
    release_token_count = int(evidence.get("releaseTokenCount") or len(_safe_list(evidence.get("manualReleaseReviewRows"))))
    complete_signoff_count = int(handoff.get("completeSignoffCount") or 0)
    all_input_complete = bool(release_token_count and complete_signoff_count == release_token_count)
    gate_rows = _gate_matrix_rows(
        evidence,
        acknowledgement_rows,
        all_input_complete=all_input_complete,
    )
    gates_with_complete_evidence = sum(1 for row in gate_rows if not row.get("missingEvidenceAcknowledgements"))
    status = (
        "SIGNOFF_EVIDENCE_AND_INPUT_READY_FOR_SEPARATE_RELEASE_LANE"
        if (
            release_token_count
            and gates_with_complete_evidence == release_token_count
            and complete_signoff_count == release_token_count
        )
        else "SIGNOFF_EVIDENCE_READY_WAITING_SIGNOFF_INPUT"
        if release_token_count and gates_with_complete_evidence == release_token_count
        else "SIGNOFF_EVIDENCE_PARTIAL_REVIEW_ONLY"
    )
    payload = {
        "ok": True,
        "schema": RELEASE_TOKEN_SIGNOFF_EVIDENCE_MATRIX_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": status,
        "statusZh": (
            f"{gates_with_complete_evidence}/{release_token_count} 个 release gate 的证据确认项与签收输入已齐；等待独立 execution release lane"
            if status == "SIGNOFF_EVIDENCE_AND_INPUT_READY_FOR_SEPARATE_RELEASE_LANE"
            else
            f"{gates_with_complete_evidence}/{release_token_count} 个 release gate 的证据确认项已齐；仍需签收输入"
            if status == "SIGNOFF_EVIDENCE_READY_WAITING_SIGNOFF_INPUT"
            else f"签收证据矩阵仍不完整：{ready_count}/{len(ACKNOWLEDGEMENTS)} 个确认项已具备证据"
        ),
        "releaseTokenCount": release_token_count,
        "completeSignoffCount": complete_signoff_count,
        "acknowledgementReadyCount": ready_count,
        "acknowledgementCount": len(ACKNOWLEDGEMENTS),
        "gatesWithCompleteEvidence": gates_with_complete_evidence,
        "acknowledgementRows": acknowledgement_rows,
        "gateRows": gate_rows,
        "sourceArtifacts": {
            "releaseTokenEvidenceReview": str(release_token_evidence_review_path(runtime)),
            "runtimePreflight": str(runtime_preflight_path(runtime)),
            "brokerOrderSendReview": str(broker_order_send_review_path(runtime)),
            "liveExecutionRollbackReview": str(live_execution_rollback_review_path(runtime)),
            "releaseMinimalDiffReview": str(release_minimal_diff_review_path(runtime)),
        },
        "decision": {
            "canAcceptSignoffHere": False,
            "canMintTokenHere": False,
            "canReleaseExecutionNow": False,
            "releaseTokenCanBeAutoMinted": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "writesMt5OrderRequest": False,
            "requestFilesWritten": False,
            "receiptFilesWritten": False,
            "brokerCallsMade": False,
            "livePresetMutationAllowed": False,
            "nextRequiredActionZh": "按 acknowledgementRows 补齐证据后，仍只能交给独立 execution release lane；本矩阵不签收、不铸 token、不执行交易。",
        },
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = release_token_signoff_evidence_matrix_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_release_token_signoff_evidence_matrix(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = release_token_signoff_evidence_matrix_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_release_token_signoff_evidence_matrix(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": RELEASE_TOKEN_SIGNOFF_EVIDENCE_MATRIX_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "release token signoff evidence matrix artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_release_token_signoff_evidence_matrix(runtime, write=False)
