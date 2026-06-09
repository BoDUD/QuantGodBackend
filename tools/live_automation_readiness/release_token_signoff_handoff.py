from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .release_token_evidence_review import build_release_token_evidence_review, read_release_token_evidence_review
from .release_token_signoff_input_review import (
    build_release_token_signoff_input_review,
    read_release_token_signoff_input_review,
)
from .release_token_signoff_input_template import (
    build_release_token_signoff_input_template,
    read_release_token_signoff_input_template,
)
from .schema import (
    RELEASE_TOKEN_SIGNOFF_HANDOFF_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    release_token_evidence_review_path,
    release_token_signoff_handoff_path,
    release_token_signoff_input_review_path,
    release_token_signoff_input_template_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _review_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _safe_list(payload.get("reviewRows")) if isinstance(row, dict)]


def _template_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    template = _safe_dict(payload.get("signoffInputTemplate"))
    return [row for row in _safe_list(template.get("releaseTokenSignoffs")) if isinstance(row, dict)]


def _missing_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "gateId": row.get("gateId", ""),
        "labelZh": row.get("labelZh", ""),
        "tokenName": row.get("tokenName", ""),
        "blockerCode": row.get("blockerCode", ""),
        "inputProvided": bool(row.get("inputProvided")),
        "missingAcknowledgements": _safe_list(row.get("missingAcknowledgements")),
        "finalSignoffTextOk": bool(row.get("finalSignoffTextOk")),
        "status": row.get("status", "SIGNOFF_INPUT_INCOMPLETE"),
        "statusZh": row.get("statusZh", "签收输入不完整"),
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def build_release_token_signoff_handoff(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    evidence = read_release_token_evidence_review(runtime)
    if not _safe_list(evidence.get("manualReleaseReviewRows")):
        evidence = build_release_token_evidence_review(runtime, write=False)
    template = read_release_token_signoff_input_template(runtime)
    if not _template_rows(template):
        template = build_release_token_signoff_input_template(runtime, write=False)
    review = read_release_token_signoff_input_review(runtime)
    if not _review_rows(review):
        review = build_release_token_signoff_input_review(runtime, write=False)

    template_rows = _template_rows(template)
    review_rows = _review_rows(review)
    release_token_count = int(
        review.get("releaseTokenCount")
        or template.get("releaseTokenCount")
        or evidence.get("releaseTokenCount")
        or max(len(review_rows), len(template_rows))
    )
    ready_for_input_count = int(template.get("readyForInputCount") or len(template_rows))
    complete_signoff_count = int(review.get("completeSignoffCount") or 0)
    missing_signoff_count = max(release_token_count - complete_signoff_count, 0)
    missing_rows = [_missing_row(row) for row in review_rows if not row.get("completeForSeparateReleaseReview")]
    all_complete = release_token_count > 0 and complete_signoff_count == release_token_count and not review.get("forbiddenSecretFieldPaths")

    status = "SIGNOFF_HANDOFF_READY_FOR_SEPARATE_RELEASE_LANE" if all_complete else "WAITING_SIGNOFF_INPUT_HANDOFF"
    payload = {
        "ok": True,
        "schema": RELEASE_TOKEN_SIGNOFF_HANDOFF_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "sourceReleaseTokenEvidencePath": str(release_token_evidence_review_path(runtime)),
        "sourceReleaseTokenSignoffInputTemplatePath": str(release_token_signoff_input_template_path(runtime)),
        "sourceReleaseTokenSignoffInputReviewPath": str(release_token_signoff_input_review_path(runtime)),
        "handoffPath": str(release_token_signoff_handoff_path(runtime)),
        "status": status,
        "statusZh": (
            f"{complete_signoff_count}/{release_token_count} 个 release token 签收输入完整；可交给独立 execution release lane 复核，当前交接包仍不放行"
            if all_complete
            else f"{complete_signoff_count}/{release_token_count} 个 release token 签收输入完整；还缺 {missing_signoff_count} 个签收输入"
        ),
        "releaseTokenCount": release_token_count,
        "readyForInputCount": ready_for_input_count,
        "completeSignoffCount": complete_signoff_count,
        "missingSignoffCount": missing_signoff_count,
        "forbiddenSecretFieldPaths": _safe_list(review.get("forbiddenSecretFieldPaths")),
        "missingSignoffRows": missing_rows,
        "handoffArtifacts": {
            "releaseTokenEvidenceReview": {
                "schema": evidence.get("schema", ""),
                "status": evidence.get("status", ""),
                "statusZh": evidence.get("statusZh", ""),
                "path": str(release_token_evidence_review_path(runtime)),
            },
            "releaseTokenSignoffInputTemplate": {
                "schema": template.get("schema", ""),
                "status": template.get("status", ""),
                "statusZh": template.get("statusZh", ""),
                "path": str(release_token_signoff_input_template_path(runtime)),
            },
            "releaseTokenSignoffInputReview": {
                "schema": review.get("schema", ""),
                "status": review.get("status", ""),
                "statusZh": review.get("statusZh", ""),
                "path": str(release_token_signoff_input_review_path(runtime)),
            },
        },
        "handoffInstructions": [
            "用 Release Token 签收模板填写 operatorId、reviewedAtIso、5 个 acknowledgement 与 finalSignoffText。",
            "不要提交 apiKey/apiSecret/authToken/password/privateKey/secret/token/tokenValue 等秘密字段。",
            "提交给 /api/live-automation/release-token-signoff-input-review/build 的 JSON body 校验完整性。",
            "完整后只能交给独立 execution release lane 复核；本交接包不签收、不铸 token、不写订单。",
        ],
        "nextRequiredActionZh": (
            "签收输入已完整，等待独立 execution release lane 单独复核；当前 artifact 仍保持 orderSendAllowed=false。"
            if all_complete
            else "继续补齐缺失 release token 的签收输入；当前 artifact 只做交接，不允许实盘执行。"
        ),
        "canAcceptSignoffHere": False,
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
        "canProceedToLiveExecutionHere": False,
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = release_token_signoff_handoff_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_release_token_signoff_handoff(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = release_token_signoff_handoff_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_release_token_signoff_handoff(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": RELEASE_TOKEN_SIGNOFF_HANDOFF_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "release token signoff handoff artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_release_token_signoff_handoff(runtime, write=False)
