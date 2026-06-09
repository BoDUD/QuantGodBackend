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
try:
    from tools.hfm_crypto_cfd.schema import filled_contract_spec_path, filled_simulation_profile_path
except ModuleNotFoundError:  # pragma: no cover
    from hfm_crypto_cfd.schema import filled_contract_spec_path, filled_simulation_profile_path


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def _lane_score(lane: dict[str, Any], evidence: dict[str, Any]) -> int:
    score = 0
    if lane.get("simulationQualified"):
        score += 35
    if lane.get("reviewCandidate"):
        score += 35
    if lane.get("executionSpecReady") or lane.get("sourceGateLiveAllowed"):
        score += 15
    if evidence.get("hfm_crypto_symbol_evidence") or lane.get("lane") == "USDJPY_MT5":
        score += 5
    if evidence.get("hfm_crypto_contract_spec") or lane.get("lane") == "USDJPY_MT5":
        score += 5
    if evidence.get("hfm_crypto_simulation_profile") or lane.get("simulationQualified"):
        score += 5
    return min(score, 100)


def _evidence_map(intake: dict[str, Any]) -> dict[str, bool]:
    rows: dict[str, bool] = {}
    for item in _safe_list(intake.get("intakeChecklist")):
        if isinstance(item, dict) and item.get("id"):
            rows[str(item["id"])] = bool(item.get("passed"))
    return rows


def _lane_row(lane_key: str, lane: dict[str, Any], evidence: dict[str, bool]) -> dict[str, Any]:
    review_candidate = bool(lane.get("reviewCandidate"))
    simulation_qualified = bool(lane.get("simulationQualified"))
    blockers = [item for item in _safe_list(lane.get("reviewBlockers")) if isinstance(item, dict)]
    return {
        "laneKey": lane_key,
        "lane": lane.get("lane") or lane_key,
        "laneZh": lane.get("laneZh") or lane_key,
        "simulationQualified": simulation_qualified,
        "reviewCandidate": review_candidate,
        "canEnterLiveReviewNow": review_candidate,
        "canPromoteToLiveNow": False,
        "executionReady": False,
        "evidenceScore": _lane_score(lane, evidence),
        "primaryBlockerCode": blockers[0].get("code") if blockers else "",
        "nextRequiredActionZh": lane.get("nextRequiredActionZh", ""),
        "blockerCount": len(blockers),
        "blockers": blockers[:12],
    }


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


def _review_commands(candidate_count: int) -> list[dict[str, Any]]:
    if candidate_count <= 0:
        return [{
            "id": "refresh_evidence_intake",
            "whenZh": "模拟或 HFM 证据缺失时，先刷新证据接入。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
        }]
    return [
        {
            "id": "build_review_packet",
            "whenZh": "有 review candidate 后，生成执行审查包。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime review-packet --write --refresh-sources",
        },
        {
            "id": "build_approval_draft",
            "whenZh": "生成人工审批草案，等待 operator 明确确认。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime approval-draft --write --refresh-sources",
        },
        {
            "id": "build_dry_run_plan",
            "whenZh": "把候选 lane 转成 blocked dry-run intent 供人工检查。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime dry-run-plan --write --refresh-sources",
        },
        {
            "id": "build_pipeline",
            "whenZh": "串联完整 sim-to-live 审查链。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime pipeline --write --refresh-sources",
        },
    ]


def build_live_promotion_candidates(
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
    kwargs = {
        "write": write,
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_roots,
    }
    approval_kwargs = {**kwargs, "operator_approval_json": operator_approval_json}
    filled_inputs_available = (
        filled_contract_spec_path(runtime_dir).exists()
        or filled_simulation_profile_path(runtime_dir).exists()
    )
    should_rebuild = bool(
        write
        or refresh_sources
        or operator_approval_json
        or moss_backtest_json
        or hfm_simulation_profile_json
        or hfm_contract_spec_json
        or extra_roots
        or filled_inputs_available
    )
    readiness = build_live_automation_readiness(runtime_dir, **kwargs) if should_rebuild else read_live_automation_readiness(runtime_dir)
    intake = build_live_evidence_intake(runtime_dir, **approval_kwargs) if should_rebuild else read_live_evidence_intake(runtime_dir)
    review_packet = build_live_execution_review_packet(runtime_dir, **kwargs) if should_rebuild else read_live_execution_review_packet(runtime_dir)
    pipeline = build_sim_to_live_automation_pipeline(runtime_dir, **approval_kwargs) if should_rebuild else read_sim_to_live_automation_pipeline(runtime_dir)
    lanes = _safe_dict(readiness.get("lanes"))
    evidence = _evidence_map(intake)
    candidate_rows = [
        _lane_row("usdjpyMt5", _safe_dict(lanes.get("usdjpyMt5")), evidence),
        _lane_row("hfmCryptoCfd", _safe_dict(lanes.get("hfmCryptoCfd")), evidence),
    ]
    candidate_rows.sort(key=lambda row: (not row["canEnterLiveReviewNow"], -int(row["evidenceScore"]), row["laneKey"]))
    review_candidate_count = sum(1 for row in candidate_rows if row.get("canEnterLiveReviewNow"))
    simulation_qualified_count = sum(1 for row in candidate_rows if row.get("simulationQualified"))
    blockers: list[dict[str, Any]] = []
    if not review_candidate_count:
        blockers.append(_blocker("NO_SIMULATION_LANE_READY_FOR_LIVE_REVIEW", "还没有 lane 达到模拟转实盘评审候选条件。"))
    if not bool(pipeline.get("readyForSeparateExecutionAdapterReview")):
        blockers.append(_blocker("SIM_TO_LIVE_PIPELINE_NOT_READY", "完整 sim-to-live pipeline 尚未到达 adapter 评审边界。", pipeline.get("autoStage")))
    if not bool(intake.get("status") == "HFM_REVIEW_INPUTS_PRESENT") and not bool(_safe_dict(lanes.get("usdjpyMt5")).get("reviewCandidate")):
        blockers.append(_blocker("HFM_OR_USDJPY_EVIDENCE_INCOMPLETE", "HFM crypto 证据或 USDJPY deployment gate 至少需要一个先过线。"))
    ready_for_operator_review = bool(review_candidate_count)
    status = "READY_FOR_OPERATOR_REVIEW_PACKET" if ready_for_operator_review else "WAITING_LIVE_PROMOTION_CANDIDATES"
    payload = {
        "ok": True,
        "schema": LIVE_PROMOTION_CANDIDATES_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": "有模拟达标 lane，可自动生成实盘评审包" if ready_for_operator_review else "等待模拟达标 lane",
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
        "brokerExecutionAllowed": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "candidateLanes": candidate_rows,
        "artifacts": {
            "readiness": _artifact_summary(readiness, ("reviewCandidateCount", "simulationQualifiedCount")),
            "evidenceIntake": _artifact_summary(intake, ("fileInputSummary",)),
            "reviewPacket": _artifact_summary(review_packet, ("reviewCandidateCount",)),
            "pipeline": _artifact_summary(pipeline, ("autoStage", "readyForSeparateExecutionAdapterReview")),
        },
        "readOnlyReviewCommands": _review_commands(review_candidate_count),
        "blockers": blockers,
        "nextRequiredActionZh": (
            "自动生成 review packet、approval draft 和 dry-run plan；真实执行仍需单独 adapter 代码评审。"
            if ready_for_operator_review
            else "继续补齐 HFM crypto symbol/spec/profile，或让 USDJPY deployment gate 先过线。"
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
