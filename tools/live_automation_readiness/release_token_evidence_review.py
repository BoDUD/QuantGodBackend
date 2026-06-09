from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .release_minimal_diff_review import build_release_minimal_diff_review, read_release_minimal_diff_review
from .release_readiness_refresh import build_release_readiness_refresh, read_release_readiness_refresh
from .orchestrator import read_sim_to_live_orchestrator
from .schema import (
    EXECUTION_FLAG_KEYS,
    RELEASE_TOKEN_EVIDENCE_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    broker_order_send_review_path,
    ea_request_consumption_review_path,
    live_execution_adapter_write_review_path,
    live_execution_rollback_review_path,
    receipt_reconciliation_review_path,
    release_minimal_diff_review_path,
    release_token_evidence_review_path,
    utc_now_iso,
)


TOKEN_EVIDENCE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "request_writer_release": {
        "contractArtifact": "liveExecutionAdapterWriteReview",
        "requiredChecks": [
            "adapter request schema hash stable",
            "atomic write path reviewed",
            "request directory stays empty during review-only run",
            "kill-switch fuse blocks writes when release token missing",
        ],
        "testCommands": [
            "python3 -m unittest discover -s tests -p test_live_automation_readiness.py -k live_execution_adapter_write -v",
            "node --test tests/node/test_live_automation_readiness_guard.mjs",
        ],
    },
    "ea_reader_release": {
        "contractArtifact": "eaRequestConsumptionReview",
        "requiredChecks": [
            "EA request reader markers present",
            "request consumption defaults to HOLD when token missing",
            "receipt directory remains untouched during review-only run",
            "reader fuse blocks request file consumption",
        ],
        "testCommands": [
            "python3 -m unittest discover -s tests -p test_live_automation_readiness.py -k ea_request_consumption -v",
            "node --test tests/node/test_live_automation_readiness_guard.mjs",
        ],
    },
    "broker_order_send_release": {
        "contractArtifact": "brokerOrderSendReview",
        "requiredChecks": [
            "OrderSend plan is schema-validated",
            "broker call marker remains review-only before release",
            "lot, spread, slippage, max-loss and symbol mapping probes pass",
            "OrderSend fuse blocks broker calls when token missing",
        ],
        "testCommands": [
            "python3 -m unittest discover -s tests -p test_live_automation_readiness.py -k broker_order_send -v",
            "node --test tests/node/test_live_automation_readiness_guard.mjs",
        ],
    },
    "receipt_writer_release": {
        "contractArtifact": "receiptReconciliationReview",
        "requiredChecks": [
            "receipt schema and idempotency reviewed",
            "receipt matching rejects stale or unrelated fills",
            "reconciliation rollback handoff is present",
            "receipt writer fuse blocks writes when token missing",
        ],
        "testCommands": [
            "python3 -m unittest discover -s tests -p test_live_automation_readiness.py -k receipt_reconciliation -v",
            "node --test tests/node/test_live_automation_readiness_guard.mjs",
        ],
    },
    "rollback_auto_disable_release": {
        "contractArtifact": "liveExecutionRollbackReview",
        "requiredChecks": [
            "daily loss, kill-switch and hard rollback thresholds reviewed",
            "auto-disable action is idempotent",
            "rollback cannot increase risk or lot size",
            "mutation fuse blocks preset/status changes when token missing",
        ],
        "testCommands": [
            "python3 -m unittest discover -s tests -p test_live_automation_readiness.py -k live_execution_rollback -v",
            "node --test tests/node/test_live_automation_readiness_guard.mjs",
        ],
    },
}

ARTIFACT_CONFIG: dict[str, dict[str, Any]] = {
    "liveExecutionAdapterWriteReview": {
        "pathFn": live_execution_adapter_write_review_path,
        "dataPlaneKeys": ["dataPlaneAdapterWriteReady"],
        "releaseGateKeys": ["disabledWriterImplementationContract.releaseGate"],
    },
    "eaRequestConsumptionReview": {
        "pathFn": ea_request_consumption_review_path,
        "dataPlaneKeys": ["dataPlaneEaRequestConsumptionReady"],
        "releaseGateKeys": ["readerReleaseGate"],
    },
    "brokerOrderSendReview": {
        "pathFn": broker_order_send_review_path,
        "dataPlaneKeys": ["dataPlaneBrokerOrderSendReady"],
        "releaseGateKeys": ["brokerReleaseGate"],
    },
    "receiptReconciliationReview": {
        "pathFn": receipt_reconciliation_review_path,
        "dataPlaneKeys": ["dataPlaneReconciliationReady"],
        "releaseGateKeys": ["receiptReleaseGate"],
    },
    "liveExecutionRollbackReview": {
        "pathFn": live_execution_rollback_review_path,
        "dataPlaneKeys": ["dataPlaneRollbackReady"],
        "releaseGateKeys": ["rollbackReleaseGate"],
    },
}


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _nested_get(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"ok": False, "status": "MISSING", "path": str(path)}
    except Exception as exc:
        return {"ok": False, "status": "INVALID", "path": str(path), "readError": str(exc)}
    return payload if isinstance(payload, dict) else {"ok": False, "status": "INVALID", "path": str(path)}


def _truthy_execution_flag_paths(value: Any, path: str = "root") -> list[str]:
    if isinstance(value, dict):
        hits: list[str] = []
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in EXECUTION_FLAG_KEYS and bool(child):
                hits.append(child_path)
            hits.extend(_truthy_execution_flag_paths(child, child_path))
        return hits
    if isinstance(value, list):
        hits = []
        for idx, child in enumerate(value):
            hits.extend(_truthy_execution_flag_paths(child, f"{path}[{idx}]"))
        return hits
    return []


def _directory_empty_or_absent(path: Path) -> bool:
    if not path.exists():
        return True
    if not path.is_dir():
        return False
    return not any(path.iterdir())


def _side_effect_directory_checks(runtime: Path) -> list[dict[str, Any]]:
    request_dir = runtime / "agent" / "mt5_order_requests"
    receipt_dir = runtime / "agent" / "mt5_order_receipts"
    return [
        {
            "id": "mt5_order_requests_empty",
            "labelZh": "MT5 request 目录为空或不存在",
            "passed": _directory_empty_or_absent(request_dir),
            "path": str(request_dir),
        },
        {
            "id": "mt5_order_receipts_empty",
            "labelZh": "MT5 receipt 目录为空或不存在",
            "passed": _directory_empty_or_absent(receipt_dir),
            "path": str(receipt_dir),
        },
    ]


def _artifact_evidence(runtime: Path, contract_artifact: str, token: dict[str, Any]) -> dict[str, Any]:
    config = ARTIFACT_CONFIG.get(contract_artifact, {})
    path_fn = config.get("pathFn")
    path = path_fn(runtime) if callable(path_fn) else runtime / "agent" / f"{contract_artifact}.json"
    payload = _read_json_file(path)
    artifact_present = payload.get("ok") is not False and payload.get("status") not in {"MISSING", "INVALID"}
    data_plane_ready = bool(token.get("dataPlaneReady")) or any(
        bool(_nested_get(payload, key)) for key in _safe_list(config.get("dataPlaneKeys"))
    )
    release_gate_payloads = [
        _safe_dict(_nested_get(payload, key)) for key in _safe_list(config.get("releaseGateKeys"))
    ]
    expected_blocker = str(token.get("blockerCode") or "")
    release_gate_blocked = any(
        gate.get("tokenRequired", True)
        and not bool(gate.get("tokenProvided") or gate.get("tokenProvidedInThisArtifact"))
        and (not expected_blocker or str(gate.get("blockerCode") or "") == expected_blocker)
        for gate in release_gate_payloads
    )
    release_gate_blocked = release_gate_blocked or bool(
        token.get("tokenRequired", True)
        and not token.get("tokenProvided")
        and (not expected_blocker or token.get("blockerCode") == expected_blocker)
    )
    truthy_flags = _truthy_execution_flag_paths(payload)
    return {
        "artifactPath": str(path),
        "artifactPresent": artifact_present,
        "artifactStatus": payload.get("statusZh") or payload.get("status") or ("PRESENT" if artifact_present else "MISSING"),
        "dataPlaneReady": data_plane_ready,
        "releaseGateBlocked": release_gate_blocked,
        "truthyExecutionFlagPaths": truthy_flags,
        "noExecutionFlagsTruthy": not truthy_flags,
    }


def _check_row(check_id: str, label: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {
        "id": check_id,
        "labelZh": label,
        "passed": bool(passed),
        "detailZh": detail,
    }


def _token_evidence_row(runtime: Path, token: dict[str, Any]) -> dict[str, Any]:
    gate_id = str(token.get("gateId") or "")
    requirement = TOKEN_EVIDENCE_REQUIREMENTS.get(gate_id, {})
    token_provided = bool(token.get("tokenProvided"))
    contract_artifact = str(requirement.get("contractArtifact") or token.get("sourceArtifact") or "")
    artifact_evidence = _artifact_evidence(runtime, contract_artifact, token)
    dir_checks = _side_effect_directory_checks(runtime)
    evidence_checks = [
        _check_row(
            "source_artifact_present",
            "上游审查 artifact 存在",
            bool(artifact_evidence["artifactPresent"]),
            str(artifact_evidence["artifactStatus"]),
        ),
        _check_row(
            "source_artifact_data_plane_ready",
            "上游数据面就绪",
            bool(artifact_evidence["dataPlaneReady"]),
            artifact_evidence["artifactPath"],
        ),
        _check_row(
            "source_artifact_no_execution_flags",
            "上游 artifact 没有开启执行标志",
            bool(artifact_evidence["noExecutionFlagsTruthy"]),
            " / ".join(artifact_evidence["truthyExecutionFlagPaths"]),
        ),
        _check_row(
            "release_gate_still_blocked",
            "release gate 仍保持阻断",
            bool(artifact_evidence["releaseGateBlocked"]),
            str(token.get("blockerCode") or ""),
        ),
        *dir_checks,
    ]
    no_side_effect_evidence_complete = all(bool(row.get("passed")) for row in evidence_checks)
    return {
        "gateId": gate_id,
        "labelZh": token.get("labelZh", ""),
        "tokenName": token.get("tokenName", ""),
        "blockerCode": token.get("blockerCode", ""),
        "sourceArtifact": token.get("sourceArtifact", ""),
        "contractArtifact": contract_artifact,
        "sideEffectZh": token.get("sideEffectZh", ""),
        "dataPlaneReady": bool(artifact_evidence["dataPlaneReady"]),
        "tokenProvided": token_provided,
        "canMintNow": False,
        "evidenceComplete": no_side_effect_evidence_complete,
        "noSideEffectEvidenceComplete": no_side_effect_evidence_complete,
        "releaseAllowedNow": False,
        "evidencePassedCount": sum(1 for row in evidence_checks if row.get("passed")),
        "evidenceCheckCount": len(evidence_checks),
        "evidenceChecks": evidence_checks,
        "sourceArtifactEvidence": artifact_evidence,
        "requiredChecks": list(requirement.get("requiredChecks") or []),
        "testCommands": list(requirement.get("testCommands") or []),
        "currentBlockerZh": (
            "release token 已提供但仍需单独执行 lane 审查复核"
            if token_provided
            else "release token 未提供；当前 artifact 只能生成证据清单，不能自动铸造或释放"
        ),
    }


def _manual_release_review_row(row: dict[str, Any]) -> dict[str, Any]:
    evidence_complete = bool(row.get("evidenceComplete"))
    token_provided = bool(row.get("tokenProvided"))
    ready_for_separate_review = evidence_complete and not token_provided
    return {
        "gateId": row.get("gateId", ""),
        "labelZh": row.get("labelZh", ""),
        "tokenName": row.get("tokenName", ""),
        "blockerCode": row.get("blockerCode", ""),
        "contractArtifact": row.get("contractArtifact", ""),
        "sourceArtifactPath": _safe_dict(row.get("sourceArtifactEvidence")).get("artifactPath", ""),
        "sideEffectZh": row.get("sideEffectZh", ""),
        "status": (
            "READY_FOR_SEPARATE_SIGNOFF_REVIEW"
            if ready_for_separate_review
            else "TOKEN_ALREADY_PROVIDED_RECHECK_REQUIRED"
            if token_provided
            else "EVIDENCE_INCOMPLETE"
        ),
        "statusZh": (
            "无副作用证据已齐，可进入单独 release token 签收评审"
            if ready_for_separate_review
            else "release token 已提供，仍需复核执行 lane 审查"
            if token_provided
            else "证据未齐，不能进入 release token 签收"
        ),
        "readyForSeparateSignoffReview": ready_for_separate_review,
        "canSignOffHere": False,
        "canMintTokenHere": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "requiredIndependentReviewZh": (
            f"单独评审 {row.get('labelZh') or row.get('gateId')} 对应副作用：{row.get('sideEffectZh') or '执行副作用'}；"
            "确认上游 artifact、kill switch、no-side-effect 测试、回滚和操作员最终签收后，才可在独立 execution release lane 提供 token。"
        ),
        "signoffQuestionZh": (
            f"是否允许释放 {row.get('tokenName') or row.get('gateId')}，从而解除 {row.get('blockerCode') or 'release blocker'}？"
        ),
        "mustRemainFalseHere": [
            "orderSendAllowed",
            "mt5OrderSendAllowed",
            "writesMt5OrderRequest",
            "brokerCallsMade",
            "receiptWritesAllowed",
            "livePresetMutationAllowed",
        ],
        "testCommands": list(row.get("testCommands") or []),
    }


def _release_tokens_from_readiness(runtime: Path) -> list[dict[str, Any]]:
    readiness = read_release_readiness_refresh(runtime)
    plan = _safe_dict(readiness.get("releaseUnblockPlan"))
    rows = [row for row in _safe_list(plan.get("releaseTokenReviewRows")) if isinstance(row, dict)]
    if rows:
        return rows
    readiness = build_release_readiness_refresh(runtime, write=False)
    plan = _safe_dict(readiness.get("releaseUnblockPlan"))
    rows = [row for row in _safe_list(plan.get("releaseTokenReviewRows")) if isinstance(row, dict)]
    if rows:
        return rows
    orchestrator = read_sim_to_live_orchestrator(runtime)
    rows = [
        row for row in _safe_list(orchestrator.get("executionReleaseGateChecklist")) if isinstance(row, dict)
    ]
    if rows:
        return rows
    packet = _safe_dict(orchestrator.get("executionReleaseReadinessPacket"))
    return [row for row in _safe_list(packet.get("gates")) if isinstance(row, dict)]


def _review_package_release_tokens(runtime: Path, diff_review: dict[str, Any]) -> list[dict[str, Any]]:
    review_package = _safe_dict(diff_review.get("reviewPackage"))
    tokens = [row for row in _safe_list(review_package.get("releaseTokens")) if isinstance(row, dict)]
    if tokens:
        return tokens
    rebuilt = build_release_minimal_diff_review(runtime, write=False)
    rebuilt_package = _safe_dict(rebuilt.get("reviewPackage"))
    tokens = [row for row in _safe_list(rebuilt_package.get("releaseTokens")) if isinstance(row, dict)]
    if tokens:
        return tokens
    return _release_tokens_from_readiness(runtime)


def build_release_token_evidence_review(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    diff_review = read_release_minimal_diff_review(runtime)
    if not _safe_dict(diff_review.get("reviewPackage")):
        diff_review = build_release_minimal_diff_review(runtime, write=False)
    tokens = _review_package_release_tokens(runtime, diff_review)
    evidence_rows = [_token_evidence_row(runtime, row) for row in tokens]
    missing_rows = [row for row in evidence_rows if not row["tokenProvided"] or not row["evidenceComplete"]]
    evidence_complete_count = sum(1 for row in evidence_rows if row["evidenceComplete"])
    incomplete_evidence_count = len(evidence_rows) - evidence_complete_count
    no_side_effect_evidence_complete_count = sum(
        1 for row in evidence_rows if row["noSideEffectEvidenceComplete"]
    )
    token_provided_count = sum(1 for row in evidence_rows if row["tokenProvided"])
    token_missing_count = len(evidence_rows) - token_provided_count
    token_missing_only = (
        bool(evidence_rows)
        and evidence_complete_count == len(evidence_rows)
        and no_side_effect_evidence_complete_count == len(evidence_rows)
        and token_missing_count > 0
    )
    manual_release_review_rows = [_manual_release_review_row(row) for row in evidence_rows]
    manual_release_review_ready_count = sum(
        1 for row in manual_release_review_rows if row["readyForSeparateSignoffReview"]
    )
    payload = {
        "ok": True,
        "schema": RELEASE_TOKEN_EVIDENCE_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": (
            "WAITING_RELEASE_TOKEN_EVIDENCE_AND_SEPARATE_REVIEW"
            if missing_rows
            else "RELEASE_TOKEN_EVIDENCE_PRESENT_REVIEW_STILL_REQUIRED"
        ),
        "statusZh": (
            (
                f"无副作用证据已完成 {no_side_effect_evidence_complete_count}/{len(evidence_rows)}；"
                f"release token 已提供 {token_provided_count}/{len(evidence_rows)}，保持 review-only"
            )
            if token_missing_only
            else f"{len(missing_rows)} 个 release token 仍缺证据或未释放；保持 review-only"
            if missing_rows
            else "release token 证据已存在；仍需单独执行 lane 审查"
        ),
        "sourceReleaseMinimalDiffReviewPath": str(
            diff_review.get("path") or release_minimal_diff_review_path(runtime)
        ),
        "profitTargetReached": bool(diff_review.get("profitTargetReached")),
        "combinedVerifiedUsdProfit": diff_review.get("combinedVerifiedUsdProfit"),
        "qualifyingLaneIds": _safe_list(diff_review.get("qualifyingLaneIds")),
        "releaseTokenCount": len(evidence_rows),
        "tokenOrEvidenceMissingCount": len(missing_rows),
        "incompleteEvidenceCount": incomplete_evidence_count,
        "missingEvidenceCount": len(missing_rows),
        "evidenceCompleteCount": evidence_complete_count,
        "noSideEffectEvidenceCompleteCount": no_side_effect_evidence_complete_count,
        "tokenProvidedCount": token_provided_count,
        "tokenMissingCount": token_missing_count,
        "tokenMissingOnly": token_missing_only,
        "releaseTokenMissingOnlyAfterEvidenceComplete": token_missing_only,
        "releaseBlockerClass": (
            "TOKEN_MISSING_ONLY_AFTER_NO_SIDE_EFFECT_EVIDENCE"
            if token_missing_only
            else "EVIDENCE_OR_TOKEN_MISSING"
        ),
        "manualReleaseReviewReadyCount": manual_release_review_ready_count,
        "manualReleaseReviewRows": manual_release_review_rows,
        "manualReleaseReviewStatus": (
            "READY_FOR_SEPARATE_SIGNOFF_REVIEW"
            if manual_release_review_ready_count == len(evidence_rows) and evidence_rows
            else "WAITING_EVIDENCE_OR_TOKEN_RECHECK"
        ),
        "manualReleaseReviewStatusZh": (
            f"{manual_release_review_ready_count}/{len(evidence_rows)} 个 release token 可进入单独签收评审；本 artifact 不签收、不铸造 token"
            if evidence_rows
            else "等待 release token 清单"
        ),
        "blockedReleaseTokenCodes": [row["blockerCode"] for row in missing_rows if row.get("blockerCode")],
        "evidenceRows": evidence_rows,
        "canReleaseExecutionNow": False,
        "releaseTokenCanBeAutoMinted": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "receiptWritesAllowed": False,
        "livePresetMutationAllowed": False,
        "startupConfigMutationAllowed": False,
        "nextRequiredActionZh": "按 evidenceRows 逐项补单独 release token 审查证据；通过前不得写 request、消费 request、调用 broker、写 receipt 或自动改 preset。",
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = release_token_evidence_review_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_release_token_evidence_review(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = release_token_evidence_review_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_release_token_evidence_review(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": RELEASE_TOKEN_EVIDENCE_REVIEW_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "release token evidence review artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_release_token_evidence_review(runtime, write=False)
