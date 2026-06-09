from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .release_token_signoff_draft import (
    REQUIRED_SIGNOFF_FIELDS,
    build_release_token_signoff_draft,
    read_release_token_signoff_draft,
)
from .schema import (
    RELEASE_TOKEN_SIGNOFF_INPUT_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    release_token_signoff_draft_path,
    release_token_signoff_input_review_path,
    utc_now_iso,
)


ACK_FIELDS = [
    "acknowledgeNoSideEffectEvidence",
    "acknowledgeKillSwitch",
    "acknowledgeRollback",
    "acknowledgeRiskLimits",
    "acknowledgeExecutionModeSeparatelyReviewed",
]

FORBIDDEN_SECRET_FIELDS = {
    "apiKey",
    "apiSecret",
    "authToken",
    "password",
    "privateKey",
    "secret",
    "token",
    "tokenValue",
}


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _truthy_secret_field_paths(value: Any, path: str = "root") -> list[str]:
    if isinstance(value, dict):
        hits: list[str] = []
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_SECRET_FIELDS and child not in (None, "", False):
                hits.append(child_path)
            hits.extend(_truthy_secret_field_paths(child, child_path))
        return hits
    if isinstance(value, list):
        hits = []
        for idx, child in enumerate(value):
            hits.extend(_truthy_secret_field_paths(child, f"{path}[{idx}]"))
        return hits
    return []


def _load_signoff_input(signoff_json: str) -> tuple[dict[str, Any], str, str]:
    text = str(signoff_json or "").strip()
    if not text:
        return {}, "not_provided", ""
    path = Path(text).expanduser()
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8-sig")), "file", str(path)
    except OSError:
        pass
    try:
        parsed = json.loads(text)
    except Exception as exc:
        return {"ok": False, "parseError": str(exc)}, "invalid_json", ""
    return parsed if isinstance(parsed, dict) else {"ok": False, "parseError": "signoff input must be an object"}, "inline_json", ""


def _signoff_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _safe_list(payload.get("releaseTokenSignoffs")) if isinstance(row, dict)]


def _review_row(draft_row: dict[str, Any], input_by_gate: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gate_id = str(draft_row.get("gateId") or "")
    row = input_by_gate.get(gate_id, {})
    missing_acks = [field for field in ACK_FIELDS if row.get(field) is not True]
    final_text = str(row.get("finalSignoffText") or "")
    token_name = str(draft_row.get("tokenName") or "")
    blocker_code = str(draft_row.get("blockerCode") or "")
    final_text_ok = bool(final_text and token_name in final_text and blocker_code in final_text)
    complete = bool(row) and not missing_acks and final_text_ok
    return {
        "gateId": gate_id,
        "labelZh": draft_row.get("labelZh", ""),
        "tokenName": token_name,
        "blockerCode": blocker_code,
        "sideEffectZh": draft_row.get("sideEffectZh", ""),
        "inputProvided": bool(row),
        "acknowledgementComplete": bool(row) and not missing_acks,
        "missingAcknowledgements": missing_acks,
        "finalSignoffTextOk": final_text_ok,
        "completeForSeparateReleaseReview": complete,
        "status": "SIGNOFF_INPUT_COMPLETE" if complete else "SIGNOFF_INPUT_INCOMPLETE",
        "statusZh": (
            "签收输入完整，可交给独立 execution release lane 复核"
            if complete
            else "签收输入不完整或签收文本未包含 tokenName 与 blockerCode"
        ),
        "canAcceptSignoffHere": False,
        "canMintTokenHere": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def build_release_token_signoff_input_review(
    runtime_dir: Path,
    *,
    signoff_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    draft = read_release_token_signoff_draft(runtime)
    if not _safe_list(_safe_dict(draft.get("signoffDraftTemplate")).get("releaseTokenSignoffs")):
        draft = build_release_token_signoff_draft(runtime, write=False)
    signoff_input, input_source, input_path = _load_signoff_input(signoff_json)
    secret_paths = _truthy_secret_field_paths(signoff_input)
    draft_rows = [
        row for row in _safe_list(_safe_dict(draft.get("signoffDraftTemplate")).get("releaseTokenSignoffs"))
        if isinstance(row, dict)
    ]
    input_rows = _signoff_rows(signoff_input)
    input_by_gate = {str(row.get("gateId") or ""): row for row in input_rows}
    review_rows = [_review_row(row, input_by_gate) for row in draft_rows]
    complete_count = sum(1 for row in review_rows if row["completeForSeparateReleaseReview"])
    all_complete = bool(review_rows) and complete_count == len(review_rows) and not secret_paths
    payload = {
        "ok": True,
        "schema": RELEASE_TOKEN_SIGNOFF_INPUT_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "sourceReleaseTokenSignoffDraftPath": str(release_token_signoff_draft_path(runtime)),
        "signoffInputSource": input_source,
        "signoffInputPath": input_path,
        "status": "SIGNOFF_INPUT_READY_FOR_SEPARATE_RELEASE_REVIEW" if all_complete else "WAITING_SIGNOFF_INPUT",
        "statusZh": (
            f"{complete_count}/{len(review_rows)} 个 release token 签收输入完整；可交给独立 execution release lane 复核，当前 artifact 仍不放行"
            if all_complete
            else f"{complete_count}/{len(review_rows)} 个 release token 签收输入完整；仍等待完整签收输入"
        ),
        "releaseTokenCount": len(review_rows),
        "completeSignoffCount": complete_count,
        "requiredSignoffFields": list(REQUIRED_SIGNOFF_FIELDS),
        "forbiddenSecretFieldPaths": secret_paths,
        "reviewRows": review_rows,
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
        "nextRequiredActionZh": "把完整签收输入交给独立 execution release lane 复核；本 artifact 只验证输入完整性，不签收、不铸 token、不写订单。",
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = release_token_signoff_input_review_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_release_token_signoff_input_review(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = release_token_signoff_input_review_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_release_token_signoff_input_review(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": RELEASE_TOKEN_SIGNOFF_INPUT_REVIEW_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "release token signoff input review artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_release_token_signoff_input_review(runtime, write=False)
