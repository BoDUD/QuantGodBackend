from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .release_readiness_refresh import build_release_readiness_refresh, read_release_readiness_refresh
from .schema import (
    RELEASE_MINIMAL_DIFF_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    release_minimal_diff_review_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _review_package_from_unblock_plan(unblock_plan: dict[str, Any]) -> dict[str, Any]:
    proposed_changes = [
        row for row in _safe_list(unblock_plan.get("reviewOnlyProposedFileChanges")) if isinstance(row, dict)
    ]
    release_tokens = [
        row for row in _safe_list(unblock_plan.get("releaseTokenReviewRows")) if isinstance(row, dict)
    ]
    return {
        "schema": "quantgod.release_minimal_diff_package.v1",
        "mode": "REVIEW_ONLY_MINIMAL_DIFF_NO_FILE_WRITE",
        "candidateFileWritten": False,
        "writesStartupConfig": False,
        "writesMt5Preset": False,
        "writesMt5OrderRequest": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerCallsMade": False,
        "receiptWritesAllowed": False,
        "releaseTokenCanBeAutoMinted": False,
        "changeCount": len(proposed_changes),
        "releaseTokenCount": len(release_tokens),
        "proposedChanges": [
            {
                "artifact": row.get("artifact", ""),
                "path": row.get("path", ""),
                "section": row.get("section", ""),
                "key": row.get("key", ""),
                "from": row.get("currentValue", ""),
                "to": row.get("targetValue", ""),
                "blockerCode": row.get("blockerCode", ""),
                "reasonZh": row.get("reasonZh", ""),
                "reviewRequirementZh": row.get("reviewRequirementZh", ""),
                "requiresSeparateReview": True,
                "canApplyNow": False,
            }
            for row in proposed_changes
        ],
        "releaseTokens": [
            {
                "gateId": row.get("gateId", ""),
                "labelZh": row.get("labelZh", ""),
                "tokenName": row.get("tokenName", ""),
                "blockerCode": row.get("blockerCode", ""),
                "sideEffectZh": row.get("sideEffectZh", ""),
                "sourceArtifact": row.get("sourceArtifact", ""),
                "dataPlaneReady": bool(row.get("dataPlaneReady")),
                "tokenProvided": bool(row.get("tokenProvided")),
                "canMintNow": False,
                "requiredEvidenceZh": row.get("requiredEvidenceZh", ""),
            }
            for row in release_tokens
        ],
    }


def build_release_minimal_diff_review(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    readiness = read_release_readiness_refresh(runtime)
    if not _safe_dict(readiness.get("releaseUnblockPlan")):
        readiness = build_release_readiness_refresh(runtime, write=False)
    unblock_plan = _safe_dict(readiness.get("releaseUnblockPlan"))
    review_package = _review_package_from_unblock_plan(unblock_plan)
    release_blocked = int(unblock_plan.get("releaseBlockedCount") or 0)
    execution_blocked = int(unblock_plan.get("executionModeBlockedCount") or 0)
    profit_target_reached = bool(unblock_plan.get("profitTargetReached"))
    payload = {
        "ok": True,
        "schema": RELEASE_MINIMAL_DIFF_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": (
            "TARGET_REACHED_MINIMAL_DIFF_READY_FOR_SEPARATE_REVIEW"
            if profit_target_reached
            else "WAITING_PROFIT_TARGET_BEFORE_MINIMAL_DIFF_REVIEW"
        ),
        "statusZh": (
            f"收益已达标；最小 diff 审查包已生成，仍待 {release_blocked} 个 release token 和 {execution_blocked} 个执行模式闸门"
            if profit_target_reached
            else "收益目标未证明，暂不进入 release diff 审查"
        ),
        "profitTargetReached": profit_target_reached,
        "combinedVerifiedUsdProfit": unblock_plan.get("combinedVerifiedUsdProfit"),
        "qualifyingLaneIds": _safe_list(unblock_plan.get("qualifyingLaneIds")),
        "releaseBlockedCount": release_blocked,
        "executionModeBlockedCount": execution_blocked,
        "reviewPackage": review_package,
        "canApplyDiffNow": False,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesStartupConfig": False,
        "writesMt5Preset": False,
        "writesMt5OrderRequest": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "receiptWritesAllowed": False,
        "livePresetMutationAllowed": False,
        "startupConfigMutationAllowed": False,
        "releaseTokenCanBeAutoMinted": False,
        "nextRequiredActionZh": "把本审查包作为单独 execution release 评审输入；通过前不得改 ini/preset、写 request 或调用 broker。",
        "sourceReleaseReadinessPath": str(readiness.get("path") or ""),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = release_minimal_diff_review_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_release_minimal_diff_review(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = release_minimal_diff_review_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_release_minimal_diff_review(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": RELEASE_MINIMAL_DIFF_REVIEW_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "release minimal diff review artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_release_minimal_diff_review(runtime, write=False)
