from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from .forex_live12_micro_expansion_review import (
    _primary_close_history_path,
    build_forex_live12_micro_expansion_review,
)
from .lane_selector import _derived_primary_dashboard_path
from .forex_live12_rsi_shadow_candidate import build_forex_live12_rsi_shadow_candidate
from .forex_live12_rsi_tester_request import build_forex_live12_rsi_tester_request
from .forex_live12_rsi_tester_run_gate import build_forex_live12_rsi_tester_run_gate
from .schema import (
    FOREX_LIVE12_RSI_CANDIDATE_PROMOTION_GATE_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_rsi_candidate_promotion_gate_path,
    utc_now_iso,
)


def _numeric(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _path_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _path_mtime_iso(path: Path) -> str:
    mtime = _path_mtime(path)
    if mtime is None:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))


def _source_paths(runtime: Path, primary_dashboard_json: str = "") -> dict[str, Path]:
    dashboard_path = Path(primary_dashboard_json) if primary_dashboard_json else _derived_primary_dashboard_path(runtime)
    return {
        "dashboard": dashboard_path,
        "closeHistory": _primary_close_history_path(runtime, primary_dashboard_json),
    }


def _source_newer_than_artifact(runtime: Path, artifact_path: Path) -> bool:
    sources = _source_paths(runtime)
    artifact_mtime = _path_mtime(artifact_path)
    if artifact_mtime is None:
        return True
    for source in sources.values():
        source_mtime = _path_mtime(source)
        if source_mtime is not None and source_mtime > artifact_mtime + 0.5:
            return True
    return False


def _candidate_validation_stage(candidate: dict[str, Any]) -> str:
    replay = candidate.get("proxyReplay") if isinstance(candidate.get("proxyReplay"), dict) else {}
    after = replay.get("afterMetrics") if isinstance(replay.get("afterMetrics"), dict) else {}
    kept = _int_value(replay.get("keptTradeCount"))
    after_pf = _numeric(after.get("profitFactor"))
    after_net = _numeric(after.get("netProfitUSC"))
    after_losses = _int_value(after.get("maxConsecutiveLosses"))
    if candidate.get("status") == "RSI_SHADOW_CANDIDATE_READY" and kept > 0 and after_pf >= 1.05 and after_net >= 0 and after_losses <= 2:
        return "READY_FOR_TESTER_VALIDATION"
    return "WAITING_SHADOW_EVIDENCE"


def build_forex_live12_rsi_candidate_promotion_gate(
    runtime_dir: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    micro = build_forex_live12_micro_expansion_review(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    candidate = build_forex_live12_rsi_shadow_candidate(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    tester_request = build_forex_live12_rsi_tester_request(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    tester_gate = build_forex_live12_rsi_tester_run_gate(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    raw_blockers = micro.get("blockers") if isinstance(micro.get("blockers"), list) else []
    validation_stage = _candidate_validation_stage(candidate)
    tester_request_ready = tester_request.get("status") == "RSI_TESTER_REQUEST_READY"
    tester_queue_ready = tester_gate.get("gate", {}).get("queue", {}).get("ok") is True
    stage_ready = validation_stage == "READY_FOR_TESTER_VALIDATION" and tester_request_ready and tester_queue_ready
    after = candidate.get("proxyReplay", {}).get("afterMetrics", {})
    before = candidate.get("proxyReplay", {}).get("beforeMetrics", {})
    sources = _source_paths(runtime, primary_dashboard_json)
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_RSI_CANDIDATE_PROMOTION_GATE_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "artifactFreshness": {
            "mode": "SOURCE_DASHBOARD_AND_CLOSE_HISTORY_MTIME_WATCH",
            "primaryDashboardPath": str(sources["dashboard"]),
            "primaryDashboardMtimeIso": _path_mtime_iso(sources["dashboard"]),
            "closeHistoryPath": str(sources["closeHistory"]),
            "closeHistoryMtimeIso": _path_mtime_iso(sources["closeHistory"]),
            "generatedFromCurrentSource": True,
            "autoRebuiltForRead": False,
        },
        "status": "RSI_REPAIRED_CANDIDATE_READY_FOR_TESTER" if stage_ready else "RSI_REPAIRED_CANDIDATE_WAITING_EVIDENCE",
        "statusZh": "RSI 修复候选可进入 tester 验证" if stage_ready else "RSI 修复候选仍需补证据",
        "target": {
            "requestedMaxTotalTrades": requested_max_total_trades,
            "finalTargetMaxTotalTrades": requested_max_total_trades,
            "currentStage": "2_TO_3_REPAIR",
            "nextStageMaxTotalTrades": micro.get("phase", {}).get("toMaxTotalTrades"),
            "directJumpToTargetStatus": "BLOCKED_BY_STAGED_RISK_RULES",
            "reasonZh": "目标 10 已记录，但当前扩仓只能先完成 2→3 的修复候选 tester 验证。",
        },
        "rawExpansionEvidence": {
            "status": micro.get("status"),
            "statusZh": micro.get("statusZh"),
            "metrics": micro.get("evidence", {}).get("metrics", {}),
            "blockers": raw_blockers,
            "rawExpansionStage": "BLOCKED" if raw_blockers else "READY_FOR_REVIEW",
        },
        "repairedCandidateEvidence": {
            "candidateId": candidate.get("candidate", {}).get("id"),
            "validationStage": validation_stage,
            "beforeMetrics": before,
            "afterMetrics": after,
            "blockedTradeCount": candidate.get("proxyReplay", {}).get("blockedTradeCount"),
            "blockedTrades": candidate.get("proxyReplay", {}).get("blockedTrades", []),
            "parameters": candidate.get("candidate", {}).get("parameters", {}),
        },
        "testerValidation": {
            "requestStatus": tester_request.get("status"),
            "requestStatusZh": tester_request.get("statusZh"),
            "queueReady": tester_queue_ready,
            "runGateStatus": tester_gate.get("status"),
            "runGateStatusZh": tester_gate.get("statusZh"),
            "runGateBlockers": tester_gate.get("gate", {}).get("blockers", []),
            "nextActionZh": "等待 tester 启动闸门窗口与 lock 条件满足后，只跑隔离 tester；不改实盘 preset。",
        },
        "decision": {
            "candidateReadyForTesterValidation": stage_ready,
            "candidateValidationStage": validation_stage,
            "nextRecommendedMaxTotalTrades": micro.get("decision", {}).get("nextRecommendedMaxTotalTrades"),
            "targetMaxTotalTradesAfterValidation": requested_max_total_trades,
            "canApplyHere": False,
            "canWritePresetHere": False,
            "canPromoteToLiveHere": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
        },
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = forex_live12_rsi_candidate_promotion_gate_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_rsi_candidate_promotion_gate(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_rsi_candidate_promotion_gate_path(runtime)
    try:
        if _source_newer_than_artifact(runtime, path):
            payload = build_forex_live12_rsi_candidate_promotion_gate(runtime, write=False)
            payload["artifactFreshness"]["autoRebuiltForRead"] = True
            return payload
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_rsi_candidate_promotion_gate(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_RSI_CANDIDATE_PROMOTION_GATE_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 RSI candidate promotion gate artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_rsi_candidate_promotion_gate(runtime, write=False)
