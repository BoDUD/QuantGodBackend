from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from .schema import SCHEMA_VERSION, SAFETY, assert_no_execution_flags, readiness_path, utc_now_iso

try:
    from tools.usdjpy_autonomous_agent.promotion_gate import build_promotion_decision
    from tools.usdjpy_strategy_lab.policy_builder import build_usdjpy_policy
except ModuleNotFoundError:  # pragma: no cover
    from usdjpy_autonomous_agent.promotion_gate import build_promotion_decision
    from usdjpy_strategy_lab.policy_builder import build_usdjpy_policy


USDJPY_SIM_STAGES = {"PAPER_LIVE_SIM", "MICRO_LIVE", "LIVE_LIMITED"}
_READINESS_BUILD_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int | None = None) -> int | None:
    numeric = _num(value, None)
    if numeric is None:
        return default
    return int(numeric)


def _capture_source(name: str, loader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        payload = loader()
        return {"ok": True, "name": name, "payload": _safe_dict(payload)}
    except Exception as exc:  # pragma: no cover - defensive against partial runtime folders
        return {"ok": False, "name": name, "error": str(exc), "payload": {}}


def _path_fingerprint(value: str) -> tuple[Any, ...]:
    if not value:
        return ("", None, None)
    path = Path(value)
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_size, stat.st_mtime_ns)


def _dir_fingerprint(path: Path) -> tuple[Any, ...]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns)


def _readiness_cache_key(
    runtime_dir: Path,
    *,
    refresh_sources: bool,
) -> tuple[Any, ...]:
    return (
        str(runtime_dir.resolve()),
        bool(refresh_sources),
        _dir_fingerprint(runtime_dir / "Bases"),
        _path_fingerprint(str(runtime_dir / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json")),
        _path_fingerprint(str(runtime_dir / "agent" / "QuantGod_AutonomousPromotionDecision.json")),
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_usdjpy_policy(runtime_dir: Path) -> dict[str, Any]:
    payload = _read_json(Path(runtime_dir) / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json")
    if payload:
        return payload
    return {
        "ok": False,
        "symbol": "USDJPYc",
        "status": "USDJPY_POLICY_ARTIFACT_MISSING",
        "usdDeploymentGate": {
            "liveAllowed": False,
            "targetStage": "UNKNOWN",
            "blockers": [
                _blocker(
                    "USD_RUNTIME_FRESH_REQUIRED",
                    "美元账户需要 FRESH runtime；当前 status build 未重建 USDJPY policy。",
                    "MISSING_USDJPY_POLICY_ARTIFACT",
                    "FRESH",
                )
            ],
        },
        "topPolicy": {},
        "safety": dict(SAFETY),
    }


def _read_usdjpy_promotion_decision(runtime_dir: Path) -> dict[str, Any]:
    payload = _read_json(Path(runtime_dir) / "agent" / "QuantGod_AutonomousPromotionDecision.json")
    if payload:
        return payload
    return {
        "ok": False,
        "schema": "quantgod.autonomous_promotion_decision.v1",
        "status": "AUTONOMOUS_PROMOTION_ARTIFACT_MISSING",
        "stage": "UNKNOWN",
        "executionStage": "UNKNOWN",
        "candidates": [],
        "safety": dict(SAFETY),
    }


def _build_forex_live12_runtime_handoff(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    try:
        from tools.live_automation_readiness.forex_live12_runtime_handoff import build_forex_live12_runtime_handoff
    except ModuleNotFoundError:  # pragma: no cover
        from live_automation_readiness.forex_live12_runtime_handoff import build_forex_live12_runtime_handoff
    return build_forex_live12_runtime_handoff(runtime_dir, write=write)


def _blocker(code: str, reason_zh: str, value: Any = None, limit: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value is not None:
        row["value"] = value
    if limit is not None:
        row["limit"] = limit
    return row


def _blocker_codes(rows: list[Any]) -> set[str]:
    return {str(row.get("code")) for row in rows if isinstance(row, dict) and row.get("code")}


def _first_metric(metrics: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in metrics and metrics.get(key) not in (None, ""):
            return metrics.get(key)
    return None


def _append_blocker_once(rows: list[dict[str, Any]], blocker: dict[str, Any]) -> None:
    code = blocker.get("code")
    if code and code in _blocker_codes(rows):
        return
    rows.append(blocker)


def _usd_blockers_from_policy(policy: dict[str, Any]) -> list[dict[str, Any]]:
    gate = _safe_dict(policy.get("usdDeploymentGate"))
    rows: list[dict[str, Any]] = []
    for item in _safe_list(gate.get("blockers")):
        if isinstance(item, dict):
            rows.append(item)
    if not policy:
        rows.append(_blocker("USDJPY_POLICY_MISSING", "缺少 USDJPY 自动执行 policy。"))
    if not _safe_dict(policy.get("topLiveEligiblePolicy")):
        rows.append(_blocker("USDJPY_TOP_LIVE_POLICY_MISSING", "缺少符合 live route 的 USDJPY RSI_Reversal LONG policy。"))
    return rows


def _rollback_blockers(promotion: dict[str, Any]) -> list[dict[str, Any]]:
    rollback = _safe_dict(promotion.get("hardRollback"))
    return [
        _blocker("USDJPY_HARD_ROLLBACK", str(reason))
        for reason in _safe_list(rollback.get("hardBlockers"))
        if reason
    ]


def _policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: policy.get(key)
        for key in (
            "symbol",
            "strategy",
            "direction",
            "entryMode",
            "allowed",
            "recommendedLot",
            "score",
            "entryStrictness",
            "hardGateStatus",
            "runtimeFreshnessTier",
            "signalQuorum",
            "signalQuorumRequired",
            "reasons",
        )
        if key in policy
    }


def _live12_handoff_summary(handoff_source: dict[str, Any]) -> dict[str, Any]:
    handoff = _safe_dict(handoff_source.get("payload"))
    runtime_freshness = _safe_dict(handoff.get("runtimeFreshness"))
    return {
        "ok": bool(handoff_source.get("ok")),
        "error": handoff_source.get("error"),
        "status": handoff.get("status"),
        "statusZh": handoff.get("statusZh"),
        "sourceDashboardPath": handoff.get("sourceDashboardPath"),
        "sourceDashboardAgeSeconds": _safe_dict(handoff.get("artifactFreshness")).get("sourceDashboardAgeSeconds"),
        "runtimeFreshness": runtime_freshness,
        "runtimeFresh": bool(runtime_freshness.get("fresh")),
        "runtimeFreshnessBlockers": _safe_list(runtime_freshness.get("blockers")),
        "account": _safe_dict(handoff.get("account")),
        "runtimeSwitches": _safe_dict(handoff.get("runtimeSwitches")),
        "positionSummary": _safe_dict(handoff.get("positionSummary")),
        "capacityReleaseWatch": _safe_dict(handoff.get("capacityReleaseWatch")),
        "noEntryState": _safe_dict(handoff.get("noEntryDiagnostics")).get("state"),
        "noEntryStateZh": _safe_dict(handoff.get("noEntryDiagnostics")).get("stateZh"),
        "market": _safe_dict(handoff.get("market")),
        "orderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
    }


def _build_usdjpy_lane(
    policy_source: dict[str, Any],
    promotion_source: dict[str, Any],
    handoff_source: dict[str, Any],
) -> dict[str, Any]:
    policy = _safe_dict(policy_source.get("payload"))
    promotion = _safe_dict(promotion_source.get("payload"))
    handoff = _safe_dict(handoff_source.get("payload"))
    handoff_status = str(handoff.get("status") or "")
    handoff_runtime_freshness = _safe_dict(handoff.get("runtimeFreshness"))
    handoff_runtime_fresh = bool(handoff_source.get("ok") and handoff_runtime_freshness.get("fresh"))
    gate = _safe_dict(policy.get("usdDeploymentGate"))
    promotion_stage = str(promotion.get("stage") or "UNKNOWN")
    target_stage = str(gate.get("targetStage") or "UNKNOWN")
    source_gate_live_allowed = bool(gate.get("liveAllowed"))
    simulation_qualified = promotion_stage in USDJPY_SIM_STAGES or target_stage == "USD_MICRO_LIVE"
    source_blocks = _usd_blockers_from_policy(policy)
    rollback_blocks = _rollback_blockers(promotion)
    source_candidate = bool(source_gate_live_allowed and simulation_qualified and not source_blocks and not rollback_blocks)
    review_blockers = [*source_blocks, *rollback_blocks]
    if bool(handoff_source.get("ok")) and not handoff_runtime_fresh:
        _append_blocker_once(review_blockers, _blocker(
            "LIVE12_RUNTIME_REFRESH_BLOCKED",
            "Live12 runtime handoff 可读，但 dashboard 或 MT5 进程证据不新鲜，不能作为当前实盘状态。",
            handoff_status or "UNKNOWN",
            "FRESH",
        ))
    if source_candidate:
        review_blockers.append(_blocker(
            "MT5_EXECUTION_LANE_REVIEW_REQUIRED",
            "USDJPY 已可进入实盘执行审查，但当前 readiness lane 不写 MT5 订单请求。",
        ))
    else:
        review_blockers.append(_blocker(
            "USDJPY_SIM_TO_LIVE_EVIDENCE_INCOMPLETE",
            "模拟、美分账户执行反馈、点差、新闻、runtime 或 rollback 条件仍未全部通过。",
        ))
    review_candidate = bool(source_candidate)
    return {
        "lane": "USDJPY_MT5",
        "laneZh": "USDJPY MT5 实盘候选",
        "sourceStatus": {
            "policyOk": bool(policy_source.get("ok")),
            "promotionOk": bool(promotion_source.get("ok")),
            "live12RuntimeHandoffReadable": bool(handoff_source.get("ok")),
            "live12RuntimeHandoffOk": handoff_runtime_fresh,
            "live12RuntimeHandoffFresh": handoff_runtime_fresh,
            "live12RuntimeHandoffStatus": handoff_status or None,
            "live12RuntimeHandoffBlockers": _safe_list(handoff_runtime_freshness.get("blockers")),
            "policyError": policy_source.get("error"),
            "promotionError": promotion_source.get("error"),
            "live12RuntimeHandoffError": handoff_source.get("error"),
        },
        "simulationQualified": simulation_qualified,
        "reviewCandidate": review_candidate,
        "executionReady": False,
        "sourceGateLiveAllowed": source_gate_live_allowed,
        "promotionStage": promotion_stage,
        "usdDeploymentTargetStage": target_stage,
        "topPolicy": _policy_summary(_safe_dict(policy.get("topPolicy"))),
        "usdDeploymentGate": gate,
        "live12RuntimeHandoff": _live12_handoff_summary(handoff_source),
        "reviewBlockers": review_blockers,
        "nextRequiredActionZh": (
            "准备 MT5 执行通道设计评审包，单独审查 broker、账户、kill switch 与订单写入合约。"
            if review_candidate
            else "继续跑模拟/美分账户验证，直到 USD deployment gate 和 autonomous promotion gate 全部通过。"
        ),
        "safety": dict(SAFETY),
    }



def _global_blockers(usdjpy_lane: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        _blocker("EXECUTION_LANE_NOT_ENABLED", "当前系统只生成实盘自动化准入档案，不启用真实订单写入。"),
        _blocker("SEPARATE_REVIEW_REQUIRED", "需要单独评审 execution lane 才能从 readiness 进入真实 broker 执行。"),
    ]
    if not usdjpy_lane.get("reviewCandidate"):
        rows.append(_blocker("NO_LANE_READY_FOR_REVIEW", "USDJPY MT5 当前未达到实盘执行审查候选条件。"))
    return rows


def _lane_blocker_codes(lane: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for row in _safe_list(lane.get("reviewBlockers")):
        if isinstance(row, dict) and row.get("code"):
            codes.append(str(row.get("code")))
    return codes


def _execution_review_summary(usdjpy_lane: dict[str, Any]) -> dict[str, Any]:
    review_lanes = [
        key
        for key, lane in (("usdjpyMt5", usdjpy_lane),)
        if lane.get("reviewCandidate")
    ]
    simulation_lanes = [
        key
        for key, lane in (("usdjpyMt5", usdjpy_lane),)
        if lane.get("simulationQualified")
    ]
    usdjpy_source = _safe_dict(usdjpy_lane.get("sourceStatus"))
    live12_fresh = bool(usdjpy_source.get("live12RuntimeHandoffFresh"))
    usdjpy_blockers = _lane_blocker_codes(usdjpy_lane)
    blocker_codes_by_lane = {
        "usdjpyMt5": usdjpy_blockers,
        "global": ["EXECUTION_LANE_NOT_ENABLED", "SEPARATE_REVIEW_REQUIRED"],
    }
    blocker_codes = [
        *usdjpy_blockers[:6],
        *blocker_codes_by_lane["global"],
    ]
    if not live12_fresh:
        blocker_codes_by_lane["global"].append("LIVE12_RUNTIME_NOT_FRESH")
        blocker_codes.append("LIVE12_RUNTIME_NOT_FRESH")
    if simulation_lanes:
        status = "SIMULATION_READY_EXECUTION_BLOCKED"
        status_zh = "模拟证据已达标，执行链路仍阻塞"
        next_action = "继续补 execution lane 合同、runtime freshness、tester/forward 证据和 release token；当前不写订单。"
    else:
        status = "WAITING_STRATEGY_EVIDENCE"
        status_zh = "等待可审查策略证据"
        next_action = "继续补外汇 tester/forward 复验，直到 USDJPY lane 达到执行评审候选。"
    return {
        "status": status,
        "statusZh": status_zh,
        "reviewReadyLaneIds": review_lanes,
        "simulationQualifiedLaneIds": simulation_lanes,
        "liveExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "live12RuntimeFresh": live12_fresh,
        "blockerCodesByLane": blocker_codes_by_lane,
        "primaryBlockerCodes": list(dict.fromkeys(blocker_codes))[:12],
        "nextRequiredActionZh": next_action,
    }


def build_live_automation_readiness(
    runtime_dir: Path,
    *,
    write: bool = False,
    refresh_sources: bool = False,
    **_retired_inputs: Any,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    cache_key = _readiness_cache_key(
        runtime_dir,
        refresh_sources=refresh_sources,
    )
    if not write and cache_key in _READINESS_BUILD_CACHE:
        return copy.deepcopy(_READINESS_BUILD_CACHE[cache_key])
    rebuild_usdjpy_research = bool(write or refresh_sources)
    usdjpy_policy_source = _capture_source(
        "usdjpy_policy",
        lambda: (
            build_usdjpy_policy(runtime_dir, write=bool(write and refresh_sources))
            if rebuild_usdjpy_research
            else _read_usdjpy_policy(runtime_dir)
        ),
    )
    promotion_source = _capture_source(
        "usdjpy_autonomous_promotion",
        lambda: (
            build_promotion_decision(runtime_dir, write=bool(write and refresh_sources))
            if rebuild_usdjpy_research
            else _read_usdjpy_promotion_decision(runtime_dir)
        ),
    )
    usdjpy_handoff_source = _capture_source(
        "forex_live12_runtime_handoff",
        lambda: _build_forex_live12_runtime_handoff(runtime_dir, write=bool(write and refresh_sources)),
    )
    usdjpy_lane = _build_usdjpy_lane(usdjpy_policy_source, promotion_source, usdjpy_handoff_source)
    execution_summary = _execution_review_summary(usdjpy_lane)
    any_review_candidate = bool(usdjpy_lane.get("reviewCandidate"))
    any_simulation_qualified = bool(usdjpy_lane.get("simulationQualified"))
    if any_review_candidate:
        status = "READY_FOR_EXECUTION_REVIEW"
        status_zh = "可进入实盘执行审查"
    elif any_simulation_qualified:
        status = "SIMULATION_QUALIFIED_EXECUTION_BLOCKED"
        status_zh = "模拟合格但执行通道未审查"
    else:
        status = "WAITING_FOR_EVIDENCE"
        status_zh = "等待模拟/执行反馈证据"
    payload = {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "liveExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "reviewCandidateCount": int(usdjpy_lane.get("reviewCandidate")),
        "simulationQualifiedCount": int(usdjpy_lane.get("simulationQualified")),
        "executionReviewSummary": execution_summary,
        "nextRequiredActionZh": execution_summary.get("nextRequiredActionZh"),
        "lanes": {
            "usdjpyMt5": usdjpy_lane,
        },
        "approvalPacket": {
            "requiredBeforeLiveExecution": [
                "execution_lane_contract_review",
                "broker_account_and_symbol_mapping_review",
                "max_daily_loss_and_kill_switch_review",
                "spread_slippage_funding_fee_review",
                "paper_to_live_parity_review",
                "operator_final_approval",
            ],
            "writesOrders": False,
            "writesPresets": False,
            "storesCredentials": False,
        },
        "globalBlockers": _global_blockers(usdjpy_lane),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = readiness_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        _READINESS_BUILD_CACHE[cache_key] = copy.deepcopy(payload)
    return payload


def read_live_automation_readiness(runtime_dir: Path) -> dict[str, Any]:
    path = readiness_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {
        "ok": False,
        "schema": SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(Path(runtime_dir)),
        "status": "READINESS_ARTIFACT_MISSING",
        "statusZh": "live automation readiness artifact 尚未生成",
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "nextRequiredActionZh": "使用显式 build/refresh 生成 readiness；普通 status 读取不会重建或覆盖 runtime 证据。",
        "safety": dict(SAFETY),
    }
