from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approval import build_dry_run_live_execution_plan, build_live_operator_approval_draft
from .evidence_intake import build_live_evidence_intake, read_live_evidence_intake
from .pipeline import build_sim_to_live_automation_pipeline
from .promotion_candidates import build_live_promotion_candidates, read_live_promotion_candidates
from .review_packet import build_live_execution_review_packet
from .schema import (
    LIVE_PROMOTION_CONTROLLER_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    live_promotion_controller_path,
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


def _artifact_summary(payload: dict[str, Any], extra_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    keys = (
        "schema",
        "status",
        "statusZh",
        "generatedAtIso",
        "nextRequiredActionZh",
        *extra_keys,
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _eligible_lanes(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in _safe_list(candidates.get("candidateLanes"))
        if isinstance(row, dict) and row.get("canEnterLiveReviewNow")
    ]


def _review_artifact_rows(artifacts: dict[str, dict[str, Any]], requested: bool, write: bool) -> list[dict[str, Any]]:
    rows = []
    for artifact_id, payload in artifacts.items():
        rows.append({
            "artifactId": artifact_id,
            "schema": payload.get("schema", ""),
            "status": payload.get("status", ""),
            "statusZh": payload.get("statusZh", ""),
            "requestedByController": requested,
            "writtenByController": bool(requested and write),
            "executionReady": False,
            "requestWritesAllowed": False,
            "brokerCallsMade": False,
        })
    return rows


def build_live_promotion_controller(
    runtime_dir: Path,
    *,
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    extra_roots = extra_bases_roots or []
    common_kwargs = {
        "write": write,
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_roots,
    }
    approval_kwargs = {**common_kwargs, "operator_approval_json": operator_approval_json}
    should_rebuild = bool(write or refresh_sources or operator_approval_json or moss_backtest_json or hfm_simulation_profile_json or hfm_contract_spec_json or extra_roots)
    intake = build_live_evidence_intake(runtime_dir, **approval_kwargs) if should_rebuild else read_live_evidence_intake(runtime_dir)
    candidates = build_live_promotion_candidates(runtime_dir, **approval_kwargs) if should_rebuild else read_live_promotion_candidates(runtime_dir)
    eligible = _eligible_lanes(candidates)
    requested = bool(eligible)
    artifacts: dict[str, dict[str, Any]] = {}
    if requested:
        artifacts["reviewPacket"] = build_live_execution_review_packet(runtime_dir, **common_kwargs)
        artifacts["approvalDraft"] = build_live_operator_approval_draft(runtime_dir, **common_kwargs)
        artifacts["dryRunPlan"] = build_dry_run_live_execution_plan(runtime_dir, **common_kwargs)
        artifacts["pipeline"] = build_sim_to_live_automation_pipeline(runtime_dir, **approval_kwargs)
    blockers: list[dict[str, Any]] = []
    if not requested:
        blockers.append(_blocker(
            "NO_PROMOTION_CANDIDATE_TO_AUTOMATE",
            "还没有模拟达标 lane，controller 不会生成实盘审查包。",
            candidates.get("status"),
        ))
        blockers.extend(item for item in _safe_list(candidates.get("blockers")) if isinstance(item, dict))
    else:
        pipeline = _safe_dict(artifacts.get("pipeline"))
        if not bool(pipeline.get("readyForSeparateExecutionAdapterReview")):
            blockers.append(_blocker(
                "PIPELINE_AUTOMATED_BUT_WAITING_INPUTS",
                "审查包已自动生成，但完整 pipeline 仍等待审批、dry-run、runtime preflight 或 request contract。",
                pipeline.get("autoStage"),
            ))
    status = "OPERATOR_REVIEW_PACKET_AUTOMATED" if requested else "WAITING_PROMOTION_CANDIDATE"
    payload = {
        "ok": True,
        "schema": LIVE_PROMOTION_CONTROLLER_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": "已自动生成实盘评审包" if requested else "等待可自动晋级的模拟候选",
        "controllerMode": "SIM_TO_LIVE_REVIEW_AUTOMATION_ONLY",
        "reviewAutomationRequested": requested,
        "reviewArtifactsWrittenByThisRun": bool(requested and write),
        "eligibleLaneCount": len(eligible),
        "eligibleLanes": [{
            "laneKey": row.get("laneKey", ""),
            "lane": row.get("lane", ""),
            "laneZh": row.get("laneZh", ""),
            "evidenceScore": row.get("evidenceScore", 0),
        } for row in eligible],
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerExecutionAllowed": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "artifacts": {
            "evidenceIntake": _artifact_summary(intake, ("fileInputSummary",)),
            "promotionCandidates": _artifact_summary(candidates, ("reviewCandidateCount", "readyForOperatorReviewPacket")),
            **{key: _artifact_summary(value, ("reviewCandidateCount", "reviewPacketHash", "autoStage")) for key, value in artifacts.items()},
        },
        "reviewArtifactRuns": _review_artifact_rows(artifacts, requested, write),
        "blockers": blockers,
        "nextRequiredActionZh": (
            "等待人工审批 JSON，然后继续 dry-run replay、runtime preflight、request contract 和单独 adapter 代码评审。"
            if requested
            else "继续补齐 HFM crypto symbol/spec/profile，或让 USDJPY deployment gate 先过线。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_promotion_controller_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_promotion_controller(runtime_dir: Path) -> dict[str, Any]:
    path = live_promotion_controller_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_live_promotion_controller(Path(runtime_dir), write=False)
