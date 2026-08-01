from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .builder import build_live_automation_readiness, read_live_automation_readiness
from .schema import (
    LIVE_EVIDENCE_INTAKE_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    live_evidence_intake_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _check(
    check_id: str,
    label_zh: str,
    passed: bool,
    reason_zh: str,
    value: Any = None,
) -> dict[str, Any]:
    row = {
        "id": check_id,
        "labelZh": label_zh,
        "passed": bool(passed),
        "reasonZh": reason_zh,
    }
    if value not in (None, "", [], {}):
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


def build_live_evidence_intake(
    runtime_dir: Path,
    *,
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    extra_bases_roots: list[str] | None = None,
    **_retired_inputs: Any,
) -> dict[str, Any]:
    """Build the forex-only evidence intake without touching broker execution."""

    runtime_dir = Path(runtime_dir)
    readiness = (
        build_live_automation_readiness(runtime_dir, write=write, refresh_sources=refresh_sources)
        if write or refresh_sources
        else read_live_automation_readiness(runtime_dir)
    )
    lanes = _safe_dict(readiness.get("lanes"))
    lane = _safe_dict(lanes.get("usdjpyMt5"))
    source_status = _safe_dict(lane.get("sourceStatus"))
    policy_gate = _safe_dict(lane.get("usdDeploymentGate"))
    review_blockers = [row for row in _safe_list(lane.get("reviewBlockers")) if isinstance(row, dict)]

    checklist = [
        _check(
            "usdjpy_strategy_evidence",
            "USDJPY 外汇策略证据",
            bool(lane.get("simulationQualified")),
            "需要可复验的外汇 tester/forward 与模拟证据。",
            lane.get("promotionStage"),
        ),
        _check(
            "usdjpy_deployment_gate",
            "USDJPY deployment gate",
            bool(policy_gate.get("liveAllowed")),
            "USDJPY policy 的 deployment gate 必须显式通过。",
            policy_gate.get("targetStage"),
        ),
        _check(
            "forex_runtime_handoff",
            "外汇 MT5 runtime handoff",
            bool(source_status.get("live12RuntimeHandoffFresh")),
            "dashboard 与 MT5 runtime 证据必须新鲜且可审计。",
            source_status.get("live12RuntimeHandoffStatus"),
        ),
        _check(
            "usdjpy_live_review_candidate",
            "USDJPY 实盘评审候选",
            bool(lane.get("reviewCandidate")),
            "策略证据、runtime、rollback 与 deployment gate 必须全部通过。",
            [row.get("code") for row in review_blockers[:12]],
        ),
    ]
    passed_count = sum(1 for row in checklist if row["passed"])
    review_inputs_present = bool(lane.get("reviewCandidate"))
    status = "USDJPY_REVIEW_INPUTS_PRESENT" if review_inputs_present else "WAITING_USDJPY_FOREX_EVIDENCE_INPUTS"
    payload = {
        "ok": True,
        "schema": LIVE_EVIDENCE_INTAKE_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": "USDJPY 外汇评审输入已齐备" if review_inputs_present else "等待 USDJPY 外汇评审证据",
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "extraForexEvidenceRoots": list(extra_bases_roots or []),
        "fileInputSummary": {
            "requiredCount": len(checklist),
            "passedCount": passed_count,
            "missingCount": len(checklist) - passed_count,
        },
        "intakeChecklist": checklist,
        "artifacts": {
            "readiness": _artifact_summary(
                readiness,
                ("reviewCandidateCount", "simulationQualifiedCount"),
            ),
        },
        "readOnlyReviewCommands": [
            {
                "id": "refresh_forex_readiness",
                "whenZh": "USDJPY 外汇证据或 runtime handoff 更新后刷新。",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
            }
        ],
        "blockers": review_blockers[:16],
        "nextRequiredActionZh": (
            "生成外汇 execution review packet；真实执行仍由独立 release gate 阻断。"
            if review_inputs_present
            else "补齐 USDJPY tester/forward、deployment gate 与新鲜 runtime handoff 证据。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_evidence_intake_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_evidence_intake(runtime_dir: Path) -> dict[str, Any]:
    path = live_evidence_intake_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_live_evidence_intake(Path(runtime_dir), write=False)
