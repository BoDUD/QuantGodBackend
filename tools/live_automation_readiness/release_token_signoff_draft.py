from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .release_token_evidence_review import build_release_token_evidence_review, read_release_token_evidence_review
from .schema import (
    RELEASE_TOKEN_SIGNOFF_DRAFT_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    release_token_evidence_review_path,
    release_token_signoff_draft_path,
    utc_now_iso,
)


REQUIRED_SIGNOFF_FIELDS = [
    "operatorId",
    "reviewedAtIso",
    "acknowledgeNoSideEffectEvidence",
    "acknowledgeKillSwitch",
    "acknowledgeRollback",
    "acknowledgeRiskLimits",
    "acknowledgeExecutionModeSeparatelyReviewed",
    "finalSignoffText",
]


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _draft_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "gateId": row.get("gateId", ""),
        "labelZh": row.get("labelZh", ""),
        "tokenName": row.get("tokenName", ""),
        "blockerCode": row.get("blockerCode", ""),
        "contractArtifact": row.get("contractArtifact", ""),
        "sourceArtifactPath": row.get("sourceArtifactPath", ""),
        "sideEffectZh": row.get("sideEffectZh", ""),
        "readyForSeparateSignoffReview": bool(row.get("readyForSeparateSignoffReview")),
        "signoffQuestionZh": row.get("signoffQuestionZh", ""),
        "requiredIndependentReviewZh": row.get("requiredIndependentReviewZh", ""),
        "acknowledgeNoSideEffectEvidence": False,
        "acknowledgeKillSwitch": False,
        "acknowledgeRollback": False,
        "acknowledgeRiskLimits": False,
        "acknowledgeExecutionModeSeparatelyReviewed": False,
        "finalSignoffText": "",
        "canSignOffHere": False,
        "canMintTokenHere": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def build_release_token_signoff_draft(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    evidence = read_release_token_evidence_review(runtime)
    if not _safe_list(evidence.get("manualReleaseReviewRows")):
        evidence = build_release_token_evidence_review(runtime, write=False)
    manual_rows = [row for row in _safe_list(evidence.get("manualReleaseReviewRows")) if isinstance(row, dict)]
    ready_count = sum(1 for row in manual_rows if row.get("readyForSeparateSignoffReview"))
    release_token_count = int(evidence.get("releaseTokenCount") or len(manual_rows))
    all_ready = bool(manual_rows) and ready_count == len(manual_rows)
    signoff_rows = [_draft_row(row) for row in manual_rows]
    payload = {
        "ok": True,
        "schema": RELEASE_TOKEN_SIGNOFF_DRAFT_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "sourceReleaseTokenEvidencePath": str(release_token_evidence_review_path(runtime)),
        "sourceReleaseTokenEvidenceStatus": evidence.get("status", ""),
        "sourceReleaseTokenEvidenceStatusZh": evidence.get("statusZh", ""),
        "status": "READY_FOR_SEPARATE_SIGNOFF_INPUT" if all_ready else "WAITING_RELEASE_TOKEN_EVIDENCE",
        "statusZh": (
            f"{ready_count}/{len(manual_rows)} 个 release token 已生成签收输入草案；当前 artifact 不签收、不铸造 token"
            if manual_rows
            else "等待 release token evidence review 生成手动签收行"
        ),
        "releaseTokenCount": release_token_count,
        "readyForSeparateSignoffCount": ready_count,
        "signoffDraftTemplate": {
            "schema": "quantgod.release_token_signoff_input.v1",
            "operatorId": "",
            "reviewedAtIso": "",
            "releaseTokenSignoffs": signoff_rows,
        },
        "requiredSignoffFields": list(REQUIRED_SIGNOFF_FIELDS),
        "cannotBeUsedAsReleaseToken": True,
        "canAcceptSignoffHere": False,
        "canSignOffHere": False,
        "canMintTokenHere": False,
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
        "nextRequiredActionZh": "把本草案作为单独 execution release lane 的输入模板复核；本地当前 artifact 不能签收、不能铸造 release token、不能写订单请求。",
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = release_token_signoff_draft_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_release_token_signoff_draft(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = release_token_signoff_draft_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_release_token_signoff_draft(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": RELEASE_TOKEN_SIGNOFF_DRAFT_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "release token signoff draft artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_release_token_signoff_draft(runtime, write=False)
