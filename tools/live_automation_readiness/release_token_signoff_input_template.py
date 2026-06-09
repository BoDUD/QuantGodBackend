from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .release_token_signoff_draft import build_release_token_signoff_draft, read_release_token_signoff_draft
from .schema import (
    RELEASE_TOKEN_SIGNOFF_INPUT_TEMPLATE_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    release_token_signoff_draft_path,
    release_token_signoff_input_template_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blank_signoff_row(row: dict[str, Any]) -> dict[str, Any]:
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
        "canAcceptSignoffHere": False,
        "canSignOffHere": False,
        "canMintTokenHere": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def build_release_token_signoff_input_template(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    draft = read_release_token_signoff_draft(runtime)
    draft_template = _safe_dict(draft.get("signoffDraftTemplate"))
    draft_rows = [row for row in _safe_list(draft_template.get("releaseTokenSignoffs")) if isinstance(row, dict)]
    if not draft_rows:
        draft = build_release_token_signoff_draft(runtime, write=False)
        draft_template = _safe_dict(draft.get("signoffDraftTemplate"))
        draft_rows = [row for row in _safe_list(draft_template.get("releaseTokenSignoffs")) if isinstance(row, dict)]
    input_rows = [_blank_signoff_row(row) for row in draft_rows]
    ready_count = sum(1 for row in input_rows if row.get("readyForSeparateSignoffReview"))
    payload = {
        "ok": True,
        "schema": RELEASE_TOKEN_SIGNOFF_INPUT_TEMPLATE_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "sourceReleaseTokenSignoffDraftPath": str(release_token_signoff_draft_path(runtime)),
        "sourceReleaseTokenSignoffDraftStatus": draft.get("status", ""),
        "sourceReleaseTokenSignoffDraftStatusZh": draft.get("statusZh", ""),
        "templatePath": str(release_token_signoff_input_template_path(runtime)),
        "status": "READY_FOR_SIGNOFF_INPUT_FILL" if input_rows else "WAITING_RELEASE_TOKEN_SIGNOFF_DRAFT",
        "statusZh": (
            f"{ready_count}/{len(input_rows)} 个 release token 签收输入模板已生成；等待外部独立填写"
            if input_rows
            else "等待 release token signoff draft 生成输入模板"
        ),
        "releaseTokenCount": len(input_rows),
        "readyForInputCount": ready_count,
        "signoffInputTemplate": {
            "schema": "quantgod.release_token_signoff_input.v1",
            "operatorId": "",
            "reviewedAtIso": "",
            "releaseTokenSignoffs": input_rows,
        },
        "forbiddenSecretFieldsZh": "不要填写 apiKey/apiSecret/authToken/password/privateKey/secret/token/tokenValue 等秘密字段。",
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
        "nextRequiredActionZh": "在独立 execution release lane 外部填写 operatorId、reviewedAtIso、5 个 acknowledgement 与 finalSignoffText；不要填任何密钥或 token value，然后提交给签收输入校验。",
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = release_token_signoff_input_template_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_release_token_signoff_input_template(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = release_token_signoff_input_template_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_release_token_signoff_input_template(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": RELEASE_TOKEN_SIGNOFF_INPUT_TEMPLATE_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "release token signoff input template artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_release_token_signoff_input_template(runtime, write=False)
