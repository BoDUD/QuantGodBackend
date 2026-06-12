from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approval import build_dry_run_live_execution_plan, read_dry_run_live_execution_plan
from .approval_context import operator_approval_json_for_refresh
from .execution_lane import build_live_execution_lane_spec, read_live_execution_lane_spec
from .schema import (
    DRY_RUN_INTENT_REPLAY_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    dry_run_intent_replay_path,
    utc_now_iso,
)


REQUIRED_INTENT_FIELDS = (
    "intentId",
    "lane",
    "dryRunOnly",
    "canonicalSymbol",
    "brokerSymbol",
    "side",
    "orderType",
    "volumeLots",
    "riskLimits",
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


def _replay_intent(intent: dict[str, Any], lane_spec: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    for field in REQUIRED_INTENT_FIELDS:
        if field not in intent or intent.get(field) in (None, "", {}, []):
            if field == "volumeLots" and intent.get(field) == 0.0:
                continue
            blockers.append(_blocker("DRY_RUN_INTENT_FIELD_MISSING", f"dry-run intent 缺少必填字段 {field}。", field))
    if not bool(intent.get("dryRunOnly")):
        blockers.append(_blocker("DRY_RUN_INTENT_NOT_DRY_RUN_ONLY", "dry-run intent 必须明确 dryRunOnly=true。"))
    for flag in ("writesMt5OrderRequest", "mt5PendingOrderIntentsWritten", "orderSendAllowed", "brokerExecutionAllowed"):
        if bool(intent.get(flag)):
            blockers.append(_blocker("DRY_RUN_INTENT_EXECUTION_FLAG_FORBIDDEN", f"dry-run intent 出现执行开关 {flag}=true。", flag))

    lane = str(intent.get("lane") or "")
    lane_contracts = _safe_list(lane_spec.get("laneContracts"))
    matching_contract = next(
        (
            item for item in lane_contracts
            if isinstance(item, dict)
            and str(item.get("lane") or "") == lane
            and str(item.get("dryRunIntentId") or "") == str(intent.get("intentId") or "")
        ),
        {},
    )
    if not matching_contract:
        blockers.append(_blocker("DRY_RUN_INTENT_NOT_IN_EXECUTION_LANE_SPEC", "execution lane spec 中没有匹配的 dry-run intent 合约。", intent.get("intentId")))

    passed = not blockers
    return {
        "intentId": intent.get("intentId", ""),
        "lane": lane,
        "canonicalSymbol": intent.get("canonicalSymbol", ""),
        "brokerSymbol": intent.get("brokerSymbol", ""),
        "side": intent.get("side", ""),
        "orderType": intent.get("orderType", ""),
        "volumeLots": intent.get("volumeLots", 0.0),
        "passed": passed,
        "status": "PASS" if passed else "BLOCKED",
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "orderSendAllowed": False,
        "brokerExecutionAllowed": False,
        "blockers": blockers,
    }


def build_dry_run_intent_replay(
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
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    should_rebuild = bool(
        refresh_sources
        or operator_approval_json
        or moss_backtest_json
        or hfm_simulation_profile_json
        or hfm_contract_spec_json
        or extra_bases_roots
    )
    lane_spec = (
        build_live_execution_lane_spec(
            runtime_dir,
            write=bool(write and refresh_sources),
            refresh_sources=refresh_sources,
            operator_approval_json=operator_approval_json,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_live_execution_lane_spec(runtime_dir)
    )
    dry_run_plan = (
        build_dry_run_live_execution_plan(
            runtime_dir,
            write=bool(write and refresh_sources),
            refresh_sources=refresh_sources,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_dry_run_live_execution_plan(runtime_dir)
    )
    intents = [
        item for item in _safe_list(dry_run_plan.get("dryRunIntents"))
        if isinstance(item, dict)
    ]
    replay_rows = [_replay_intent(intent, lane_spec) for intent in intents]
    blockers: list[dict[str, Any]] = []
    if not bool(lane_spec.get("readyForImplementationReview")):
        blockers.append(_blocker("EXECUTION_LANE_SPEC_NOT_READY", "execution lane spec 尚未进入实现评审。", lane_spec.get("status")))
    if not intents:
        blockers.append(_blocker("DRY_RUN_INTENTS_MISSING", "没有可回放的 dry-run intents。"))
    for row in replay_rows:
        blockers.extend({**item, "intentId": row.get("intentId"), "lane": row.get("lane")} for item in _safe_list(row.get("blockers")) if isinstance(item, dict))

    replay_passed = bool(replay_rows and not blockers)
    payload = {
        "ok": True,
        "schema": DRY_RUN_INTENT_REPLAY_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "DRY_RUN_INTENT_REPLAY_ACCEPTED_EXECUTION_STILL_DISABLED" if replay_passed else "WAITING_DRY_RUN_INTENT_REPLAY_INPUTS",
        "statusZh": "dry-run intent 回放通过，但真实执行仍关闭" if replay_passed else "等待可回放的 dry-run intent",
        "replayPassed": replay_passed,
        "readyForImplementationReview": bool(lane_spec.get("readyForImplementationReview")),
        "executionReady": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "reviewPacketHash": lane_spec.get("reviewPacketHash", ""),
        "approvedLanes": _safe_list(lane_spec.get("approvedLanes")),
        "intentCount": len(intents),
        "passedIntentCount": len([row for row in replay_rows if row.get("passed")]),
        "replayedIntents": replay_rows,
        "blockers": blockers,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "orderSendAllowed": False,
        "brokerExecutionAllowed": False,
        "nextRequiredActionZh": (
            "dry-run replay 证据可进入单独 execution adapter 代码评审；当前仍不会写订单。"
            if replay_passed
            else "先让 execution lane spec、operator approval evidence 和 dry-run intents 全部就绪。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = dry_run_intent_replay_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_dry_run_intent_replay(runtime_dir: Path) -> dict[str, Any]:
    path = dry_run_intent_replay_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_dry_run_intent_replay(Path(runtime_dir), write=False)
