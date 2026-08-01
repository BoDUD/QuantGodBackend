from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .builder import build_live_automation_readiness, read_live_automation_readiness
from .evidence_intake import build_live_evidence_intake, read_live_evidence_intake
from .pipeline import build_sim_to_live_automation_pipeline, read_sim_to_live_automation_pipeline
from .review_packet import build_live_execution_review_packet, read_live_execution_review_packet
from .schema import (
    LIVE_PROMOTION_CANDIDATES_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    live_promotion_candidates_path,
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


def _evidence_map(intake: dict[str, Any]) -> dict[str, bool]:
    return {
        str(row["id"]): bool(row.get("passed"))
        for row in _safe_list(intake.get("intakeChecklist"))
        if isinstance(row, dict) and row.get("id")
    }


def _lane_row(lane: dict[str, Any], evidence: dict[str, bool]) -> dict[str, Any]:
    blockers = [item for item in _safe_list(lane.get("reviewBlockers")) if isinstance(item, dict)]
    score = 0
    score += 35 if lane.get("simulationQualified") else 0
    score += 35 if lane.get("reviewCandidate") else 0
    score += 10 if evidence.get("usdjpy_deployment_gate") else 0
    score += 10 if evidence.get("forex_runtime_handoff") else 0
    score += 10 if evidence.get("usdjpy_strategy_evidence") else 0
    return {
        "laneKey": "usdjpyMt5",
        "lane": lane.get("lane") or "USDJPY_MT5",
        "laneZh": lane.get("laneZh") or "USDJPY MT5 外汇候选",
        "simulationQualified": bool(lane.get("simulationQualified")),
        "reviewCandidate": bool(lane.get("reviewCandidate")),
        "canEnterLiveReviewNow": bool(lane.get("reviewCandidate")),
        "canPromoteToLiveNow": False,
        "executionReady": False,
        "evidenceScore": min(score, 100),
        "primaryBlockerCode": blockers[0].get("code") if blockers else "",
        "nextRequiredActionZh": lane.get("nextRequiredActionZh", ""),
        "blockerCount": len(blockers),
        "blockers": blockers[:12],
    }


def _artifact_summary(payload: dict[str, Any], extra_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    keys = ("schema", "status", "statusZh", "generatedAtIso", "nextRequiredActionZh", *extra_keys)
    return {key: payload.get(key) for key in keys if key in payload}


def _review_commands(candidate_count: int) -> list[dict[str, Any]]:
    if candidate_count <= 0:
        return [{
            "id": "refresh_forex_evidence_intake",
            "whenZh": "外汇策略或 runtime 证据缺失时刷新证据接入。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
        }]
    return [
        {
            "id": "build_review_packet",
            "whenZh": "外汇候选就绪后生成执行审查包。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime review-packet --write --refresh-sources",
        },
        {
            "id": "build_dry_run_plan",
            "whenZh": "生成 blocked dry-run intent 供人工检查。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime dry-run-plan --write --refresh-sources",
        },
    ]


def build_live_promotion_candidates(
    runtime_dir: Path,
    *,
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    extra_bases_roots: list[str] | None = None,
    **_retired_inputs: Any,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    should_rebuild = bool(write or refresh_sources or operator_approval_json or extra_bases_roots)
    readiness = (
        build_live_automation_readiness(runtime_dir, write=write, refresh_sources=refresh_sources)
        if should_rebuild
        else read_live_automation_readiness(runtime_dir)
    )
    intake = (
        build_live_evidence_intake(
            runtime_dir,
            operator_approval_json=operator_approval_json,
            write=write,
            refresh_sources=refresh_sources,
            extra_bases_roots=extra_bases_roots,
        )
        if should_rebuild
        else read_live_evidence_intake(runtime_dir)
    )
    review_packet = (
        build_live_execution_review_packet(runtime_dir, write=write, refresh_sources=refresh_sources)
        if should_rebuild
        else read_live_execution_review_packet(runtime_dir)
    )
    pipeline = (
        build_sim_to_live_automation_pipeline(
            runtime_dir,
            operator_approval_json=operator_approval_json,
            write=write,
            refresh_sources=refresh_sources,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_sim_to_live_automation_pipeline(runtime_dir)
    )
    lane = _safe_dict(_safe_dict(readiness.get("lanes")).get("usdjpyMt5"))
    candidate = _lane_row(lane, _evidence_map(intake))
    review_candidate_count = int(candidate["canEnterLiveReviewNow"])
    simulation_qualified_count = int(candidate["simulationQualified"])
    blockers: list[dict[str, Any]] = []
    if not review_candidate_count:
        blockers.append(_blocker("NO_FOREX_LANE_READY_FOR_LIVE_REVIEW", "USDJPY 外汇 lane 尚未达到实盘评审候选条件。"))
    if not bool(pipeline.get("readyForSeparateExecutionAdapterReview")):
        blockers.append(_blocker("SIM_TO_LIVE_PIPELINE_NOT_READY", "外汇 sim-to-live pipeline 尚未到达 adapter 评审边界。", pipeline.get("autoStage")))
    ready_for_operator_review = bool(review_candidate_count)
    payload = {
        "ok": True,
        "schema": LIVE_PROMOTION_CANDIDATES_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "READY_FOR_OPERATOR_REVIEW_PACKET" if ready_for_operator_review else "WAITING_FOREX_PROMOTION_CANDIDATE",
        "statusZh": "USDJPY 外汇候选可生成评审包" if ready_for_operator_review else "等待 USDJPY 外汇候选",
        "reviewCandidateCount": review_candidate_count,
        "simulationQualifiedCount": simulation_qualified_count,
        "readyForOperatorReviewPacket": ready_for_operator_review,
        "readyForSeparateExecutionAdapterReview": bool(pipeline.get("readyForSeparateExecutionAdapterReview")),
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
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "candidateLanes": [candidate],
        "artifacts": {
            "readiness": _artifact_summary(readiness, ("reviewCandidateCount", "simulationQualifiedCount")),
            "evidenceIntake": _artifact_summary(intake, ("fileInputSummary",)),
            "reviewPacket": _artifact_summary(review_packet, ("reviewCandidateCount",)),
            "pipeline": _artifact_summary(pipeline, ("autoStage", "readyForSeparateExecutionAdapterReview")),
        },
        "readOnlyReviewCommands": _review_commands(review_candidate_count),
        "blockers": blockers,
        "nextRequiredActionZh": (
            "生成外汇 review packet 与 dry-run plan；真实执行仍需独立 release 审批。"
            if ready_for_operator_review
            else "补齐 USDJPY tester/forward、deployment gate 与 runtime freshness 证据。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_promotion_candidates_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_promotion_candidates(runtime_dir: Path) -> dict[str, Any]:
    path = live_promotion_candidates_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_live_promotion_candidates(Path(runtime_dir), write=False)
