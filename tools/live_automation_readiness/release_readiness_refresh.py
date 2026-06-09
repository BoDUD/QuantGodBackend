from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .live_pilot_activation import _live_pilot_file_evidence
from .schema import (
    BROKER_ORDER_SEND_REVIEW_SCHEMA_VERSION,
    EA_REQUEST_CONSUMPTION_REVIEW_SCHEMA_VERSION,
    LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_SCHEMA_VERSION,
    LIVE_EXECUTION_ROLLBACK_REVIEW_SCHEMA_VERSION,
    RECEIPT_RECONCILIATION_REVIEW_SCHEMA_VERSION,
    RELEASE_READINESS_REFRESH_SCHEMA_VERSION,
    SAFETY,
    SIM_TO_LIVE_ORCHESTRATOR_SCHEMA_VERSION,
    assert_no_execution_flags,
    broker_order_send_review_path,
    ea_request_consumption_review_path,
    live_execution_adapter_write_review_path,
    live_execution_rollback_review_path,
    receipt_reconciliation_review_path,
    release_readiness_refresh_path,
    sim_to_live_orchestrator_path,
    utc_now_iso,
)

try:  # pragma: no cover - exercised by CLI fallback import mode
    from tools.profit_target_tracker.schema import report_path as profit_target_report_path
except ModuleNotFoundError:  # pragma: no cover
    from profit_target_tracker.schema import report_path as profit_target_report_path


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _primary_file_blocker(blockers: list[Any]) -> dict[str, Any]:
    priority = (
        "DEPLOYED_PRESET_READ_ONLY_TRUE",
        "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF",
        "DEPLOYED_PRESET_RSI_LIVE_OFF",
        "DEPLOYED_PRESET_EA_REQUEST_READER_OFF",
        "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF",
    )
    normalized = [row for row in blockers if isinstance(row, dict)]
    for code in priority:
        for blocker in normalized:
            if str(blocker.get("code") or "") == code:
                return blocker
    return normalized[0] if normalized else {}


def _read_existing_artifact(path: Path, schema: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {
            "ok": False,
            "schema": schema,
            "status": "MISSING",
            "statusZh": "artifact 缺失",
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        assert_no_execution_flags(payload)
        return payload
    return {
        "ok": False,
        "schema": schema,
        "status": "INVALID",
        "statusZh": "artifact 格式无效",
        "path": str(path),
        "safety": dict(SAFETY),
    }


def _artifact_row(step_id: str, label_zh: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "stepId": step_id,
        "labelZh": label_zh,
        "schema": payload.get("schema", ""),
        "status": payload.get("status", ""),
        "statusZh": payload.get("statusZh", ""),
        "dataPlaneReady": bool(
            payload.get("dataPlaneAdapterWriteReady")
            or payload.get("dataPlaneEaRequestConsumptionReady")
            or payload.get("dataPlaneBrokerOrderSendReady")
            or payload.get("dataPlaneReconciliationReady")
            or payload.get("dataPlaneRollbackReady")
        ),
        "executionModeOnlyBlocked": bool(payload.get("executionModeOnlyBlocked")),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "nextRequiredActionZh": payload.get("nextRequiredActionZh", ""),
    }


def _read_profit_target(runtime_dir: Path) -> dict[str, Any]:
    path = profit_target_report_path(runtime_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"exists": False, "path": str(path)}
    except Exception as exc:
        return {"exists": True, "path": str(path), "readError": str(exc)}
    if not isinstance(payload, dict):
        return {"exists": True, "path": str(path), "readError": "json_root_is_not_object"}
    return {"exists": True, "path": str(path), "payload": payload}


def _lane_profit_rows(profit_target: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane_id, lane in _safe_dict(profit_target.get("laneTargets")).items():
        lane = _safe_dict(lane)
        rows.append({
            "laneId": str(lane_id),
            "labelZh": lane.get("labelZh", ""),
            "simulationVerifiedUsdProfit": lane.get("simulationVerifiedUsdProfit"),
            "targetReached": bool(lane.get("targetReached")),
            "lanePositive": bool(lane.get("lanePositive") or (lane.get("simulationVerifiedUsdProfit") or 0) > 0),
            "status": lane.get("status", ""),
            "statusZh": lane.get("statusZh", ""),
        })
    return rows


def _post_target_execution_summary(
    *,
    profit_target_source: dict[str, Any],
    release_packet: dict[str, Any],
    activation_summary: dict[str, Any],
    release_summary: dict[str, Any],
    primary_actionable_blocker: dict[str, Any],
    file_evidence_blockers: list[Any],
    refreshed_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    profit_target = _safe_dict(profit_target_source.get("payload"))
    combined_target = _safe_dict(profit_target.get("combinedTarget"))
    target_reached = bool(
        profit_target.get("targetReached")
        or profit_target.get("dualTargetReached")
        or combined_target.get("targetReached")
    )
    activation_blocked = int(activation_summary.get("blocked") or 0)
    release_blocked = int(release_summary.get("blocked") or release_packet.get("blockedGateCount") or 0)
    data_plane_ready = bool(
        release_packet.get("safeAutomationCanContinue")
        and all(row.get("dataPlaneReady") for row in refreshed_artifacts)
    )
    return {
        "schema": "quantgod.post_target_execution_summary.v1",
        "stage": "TARGET_REACHED_EXECUTION_LOCKED_REVIEW_ONLY" if target_reached else "WAITING_PROFIT_TARGET_EVIDENCE",
        "status": "WAITING_RELEASE_TOKENS_AND_EXECUTION_MODE" if target_reached else "WAITING_PROFIT_TARGET_EVIDENCE",
        "statusZh": (
            f"收益目标已达成，执行仍锁定：{release_blocked} 个 release token 未释放，"
            f"{activation_blocked} 个 MT5 执行模式闸门未通过"
        ) if target_reached else "等待收益目标证据",
        "profitTarget": {
            "found": bool(profit_target_source.get("payload")),
            "path": profit_target_source.get("path", ""),
            "status": profit_target.get("status", ""),
            "statusZh": profit_target.get("statusZh", ""),
            "targetReached": target_reached,
            "combinedVerifiedUsdProfit": combined_target.get("combinedVerifiedUsdProfit"),
            "targetUsd": _safe_dict(profit_target.get("target")).get("targetUsd") or combined_target.get("targetUsd"),
            "aggregationMode": _safe_dict(profit_target.get("target")).get("aggregationMode")
                or combined_target.get("aggregationMode"),
            "qualifyingLaneIds": _safe_list(combined_target.get("qualifyingLaneIds")),
            "laneProfits": _lane_profit_rows(profit_target),
        },
        "dataPlaneReady": data_plane_ready,
        "executionModeOnlyBlocked": bool(target_reached and data_plane_ready and (activation_blocked or release_blocked)),
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
        "livePresetMutationAllowed": False,
        "primaryActionableBlocker": primary_actionable_blocker,
        "executionModeBlockerCodes": [
            row.get("code", "") for row in _safe_list(file_evidence_blockers) if isinstance(row, dict)
        ],
        "activationGateSummary": activation_summary,
        "releaseGateSummary": release_summary,
        "blockedReleaseTokenCodes": _safe_list(
            release_summary.get("blockerCodes") or release_packet.get("blockedReleaseTokenCodes")
        ),
        "safeNextAutomationActions": [
            "refresh_disabled_first_execution_artifacts",
            "run_no_side_effect_contract_tests",
            "surface_review_only_preset_diff",
            "wait_for_separately_reviewed_execution_release_tokens",
        ],
        "forbiddenUntilRelease": [
            "write_mt5_order_request",
            "read_or_consume_mt5_order_request",
            "call_mt5_order_send",
            "write_live_receipt",
            "mutate_live_preset_or_startup_config",
        ],
    }


def _execution_mode_review_row(
    blocker: dict[str, Any],
    execution_mode_file_evidence: dict[str, Any],
) -> dict[str, Any]:
    code = str(blocker.get("code") or "")
    startup = _safe_dict(execution_mode_file_evidence.get("startupConfig"))
    preset = _safe_dict(execution_mode_file_evidence.get("deployedPreset"))
    startup_values = _safe_dict(startup.get("values"))
    preset_values = _safe_dict(preset.get("values"))
    mapping = {
        "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF": {
            "artifact": "startupConfig",
            "path": startup.get("path", ""),
            "section": "Experts",
            "key": "AllowLiveTrading",
            "currentValue": startup_values.get("AllowLiveTrading", blocker.get("value", "")),
            "targetValue": "1",
            "reviewRequirementZh": "单独评审终端级 AllowLiveTrading=1，并确认重启后 dashboard livePilotMode/tradeAllowed 证据。",
        },
        "DEPLOYED_PRESET_READ_ONLY_TRUE": {
            "artifact": "deployedPreset",
            "path": preset.get("path", ""),
            "section": "",
            "key": "ReadOnlyMode",
            "currentValue": preset_values.get("ReadOnlyMode", blocker.get("value", "")),
            "targetValue": "false",
            "reviewRequirementZh": "单独评审 ReadOnlyMode=false 的最小 diff，并先跑 no-side-effect contract tests。",
        },
        "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF": {
            "artifact": "deployedPreset",
            "path": preset.get("path", ""),
            "section": "",
            "key": "EnablePilotAutoTrading",
            "currentValue": preset_values.get("EnablePilotAutoTrading", blocker.get("value", "")),
            "targetValue": "true",
            "reviewRequirementZh": "单独评审 EnablePilotAutoTrading=true，并保留 lot、spread、kill switch 与日亏损探针。",
        },
        "DEPLOYED_PRESET_RSI_LIVE_OFF": {
            "artifact": "deployedPreset",
            "path": preset.get("path", ""),
            "section": "",
            "key": "EnablePilotRsiH1Live",
            "currentValue": preset_values.get("EnablePilotRsiH1Live", blocker.get("value", "")),
            "targetValue": "true",
            "reviewRequirementZh": "单独评审 USDJPY RSI live route；BTC/HFM crypto lane 仍需 request reader 与 broker send release。",
        },
        "DEPLOYED_PRESET_EA_REQUEST_READER_OFF": {
            "artifact": "deployedPreset",
            "path": preset.get("path", ""),
            "section": "",
            "key": "EnableEARequestReaderReviewHarness",
            "currentValue": preset_values.get("EnableEARequestReaderReviewHarness", blocker.get("value", "")),
            "targetValue": "true",
            "reviewRequirementZh": "单独评审 EA request reader review harness；release token 未通过前不能消费 request。",
        },
    }
    detail = mapping.get(code, {})
    return {
        "blockerCode": code,
        "reasonZh": blocker.get("reasonZh", ""),
        "artifact": detail.get("artifact", ""),
        "path": detail.get("path", ""),
        "section": detail.get("section", ""),
        "key": detail.get("key", ""),
        "currentValue": detail.get("currentValue", blocker.get("value", "")),
        "targetValue": detail.get("targetValue", ""),
        "reviewRequirementZh": detail.get("reviewRequirementZh", "单独评审该 execution mode blocker 的最小 diff。"),
        "mutationAllowedNow": False,
        "writesStartupConfig": False,
        "writesMt5Preset": False,
        "requiresSeparateReview": True,
    }


def _release_token_review_rows(release_checklist: list[Any], release_packet: dict[str, Any]) -> list[dict[str, Any]]:
    source_rows = [row for row in release_checklist if isinstance(row, dict)]
    if not source_rows:
        source_rows = [row for row in _safe_list(release_packet.get("gates")) if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    for row in source_rows:
        token_required = bool(row.get("tokenRequired", True))
        token_provided = bool(row.get("tokenProvided"))
        rows.append({
            "gateId": row.get("gateId", ""),
            "labelZh": row.get("labelZh", ""),
            "sourceArtifact": row.get("sourceArtifact", ""),
            "status": row.get("status", ""),
            "tokenName": row.get("tokenName", ""),
            "tokenRequired": token_required,
            "tokenProvided": token_provided,
            "blockerCode": row.get("blockerCode", ""),
            "sideEffectZh": row.get("sideEffectZh", ""),
            "dataPlaneReady": bool(row.get("dataPlaneReady")),
            "releaseTokenCanBeAutoMinted": False,
            "sideEffectAllowedNow": False,
            "requiredEvidenceZh": "需要单独审查的 release token、对应 no-side-effect 测试、以及 rollback/kill-switch 探针证据。",
        })
    return rows


def _release_unblock_plan(
    *,
    post_target_summary: dict[str, Any],
    release_packet: dict[str, Any],
    release_checklist: list[Any],
    execution_mode_file_evidence: dict[str, Any],
    file_evidence_blockers: list[Any],
) -> dict[str, Any]:
    profit_target = _safe_dict(post_target_summary.get("profitTarget"))
    execution_mode_rows = [
        _execution_mode_review_row(row, execution_mode_file_evidence)
        for row in file_evidence_blockers
        if isinstance(row, dict)
    ]
    release_token_rows = _release_token_review_rows(release_checklist, release_packet)
    target_reached = bool(profit_target.get("targetReached"))
    blocked_tokens = [row for row in release_token_rows if row.get("tokenRequired") and not row.get("tokenProvided")]
    blocked_modes = [row for row in execution_mode_rows if row.get("blockerCode")]
    return {
        "schema": "quantgod.release_unblock_plan.v1",
        "status": (
            "TARGET_REACHED_REVIEW_ONLY_UNBLOCK_PLAN"
            if target_reached
            else "WAITING_PROFIT_TARGET_BEFORE_RELEASE_PLAN"
        ),
        "statusZh": (
            f"收益已达标；待审查 {len(blocked_tokens)} 个 release token 和 {len(blocked_modes)} 个 MT5 执行模式最小 diff"
            if target_reached
            else "收益目标未证明前不生成实盘释放计划"
        ),
        "profitTargetReached": target_reached,
        "combinedVerifiedUsdProfit": profit_target.get("combinedVerifiedUsdProfit"),
        "qualifyingLaneIds": _safe_list(profit_target.get("qualifyingLaneIds")),
        "releaseTokenReviewRows": release_token_rows,
        "executionModeReviewRows": execution_mode_rows,
        "reviewOnlyProposedFileChanges": execution_mode_rows,
        "releaseBlockedCount": len(blocked_tokens),
        "executionModeBlockedCount": len(blocked_modes),
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "receiptWritesAllowed": False,
        "livePresetMutationAllowed": False,
        "startupConfigMutationAllowed": False,
        "releaseTokenCanBeAutoMinted": False,
        "nextSafeActionZh": (
            "生成审查用最小 diff 和 release-token 证据清单；未通过单独执行 lane 评审前保持只读。"
        ),
        "forbiddenUntilSeparateReleaseReview": _safe_list(post_target_summary.get("forbiddenUntilRelease")),
    }


def build_release_readiness_refresh(
    runtime_dir: Path,
    *,
    ea_source_path: str = "",
    ea_status_json: str = "",
    receipt_json: str = "",
    request_json: str = "",
    operator_approval_json: str = "",
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
    write: bool = False,
    refresh_sources: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    adapter_write = _read_existing_artifact(
        live_execution_adapter_write_review_path(runtime),
        LIVE_EXECUTION_ADAPTER_WRITE_REVIEW_SCHEMA_VERSION,
    )
    ea_consumption = _read_existing_artifact(
        ea_request_consumption_review_path(runtime),
        EA_REQUEST_CONSUMPTION_REVIEW_SCHEMA_VERSION,
    )
    broker_send = _read_existing_artifact(
        broker_order_send_review_path(runtime),
        BROKER_ORDER_SEND_REVIEW_SCHEMA_VERSION,
    )
    receipt_reconciliation = _read_existing_artifact(
        receipt_reconciliation_review_path(runtime),
        RECEIPT_RECONCILIATION_REVIEW_SCHEMA_VERSION,
    )
    rollback = _read_existing_artifact(
        live_execution_rollback_review_path(runtime),
        LIVE_EXECUTION_ROLLBACK_REVIEW_SCHEMA_VERSION,
    )
    orchestrator = _read_existing_artifact(
        sim_to_live_orchestrator_path(runtime),
        SIM_TO_LIVE_ORCHESTRATOR_SCHEMA_VERSION,
    )
    release_packet = _safe_dict(orchestrator.get("executionReleaseReadinessPacket"))
    execution_mode_file_evidence = _live_pilot_file_evidence(runtime)
    file_evidence_blockers = _safe_list(execution_mode_file_evidence.get("blockingEvidence"))
    primary_actionable_blocker = _primary_file_blocker(file_evidence_blockers)
    file_blocker_hint = primary_actionable_blocker.get("reasonZh") if primary_actionable_blocker else ""
    refreshed_artifacts = [
        _artifact_row("request_writer_release", "Python request writer", adapter_write),
        _artifact_row("ea_reader_release", "EA request reader", ea_consumption),
        _artifact_row("broker_order_send_release", "Broker OrderSend", broker_send),
        _artifact_row("receipt_writer_release", "Receipt writer", receipt_reconciliation),
        _artifact_row("rollback_auto_disable_release", "Rollback auto-disable", rollback),
    ]
    activation_summary = _safe_dict(orchestrator.get("executionActivationGateSummary"))
    release_summary = _safe_dict(orchestrator.get("executionReleaseGateSummary"))
    profit_target_source = _read_profit_target(runtime)
    post_target_summary = _post_target_execution_summary(
        profit_target_source=profit_target_source,
        release_packet=release_packet,
        activation_summary=activation_summary,
        release_summary=release_summary,
        primary_actionable_blocker=primary_actionable_blocker,
        file_evidence_blockers=file_evidence_blockers,
        refreshed_artifacts=refreshed_artifacts,
    )
    release_unblock_plan = _release_unblock_plan(
        post_target_summary=post_target_summary,
        release_packet=release_packet,
        release_checklist=_safe_list(orchestrator.get("executionReleaseGateChecklist")),
        execution_mode_file_evidence=execution_mode_file_evidence,
        file_evidence_blockers=file_evidence_blockers,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "schema": RELEASE_READINESS_REFRESH_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": release_packet.get("status") or orchestrator.get("status") or "WAITING_RELEASE_READINESS_INPUTS",
        "statusZh": release_packet.get("statusZh") or orchestrator.get("statusZh") or "等待 release readiness 输入",
        "refreshMode": "DISABLED_FIRST_REVIEW_ONLY",
        "refreshedArtifactCount": 5,
        "safeAutomationCanContinue": True,
        "executionReleaseReadinessPacket": release_packet,
        "postTargetExecutionSummary": post_target_summary,
        "releaseUnblockPlan": release_unblock_plan,
        "executionActivationGateSummary": activation_summary,
        "executionReleaseGateSummary": release_summary,
        "executionReleaseGateChecklist": orchestrator.get("executionReleaseGateChecklist", []),
        "executionModeFileEvidence": execution_mode_file_evidence,
        "fileEvidenceBlockers": file_evidence_blockers,
        "primaryActionableBlocker": primary_actionable_blocker,
        "refreshedArtifacts": refreshed_artifacts,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "nextRequiredActionZh": (
            f"收益达标后仍未释放真实执行；当前主 blocker：{file_blocker_hint} "
            if file_blocker_hint
            else "已按 release gate 顺序刷新 disabled-first artifacts；"
        )
        + (
            "继续保持不写 request、不读 request、不调用 broker、不写 receipt、不修改 preset。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = release_readiness_refresh_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_release_readiness_refresh(runtime_dir: Path) -> dict[str, Any]:
    path = release_readiness_refresh_path(Path(runtime_dir))
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {
            "ok": False,
            "schema": RELEASE_READINESS_REFRESH_SCHEMA_VERSION,
            "status": "MISSING",
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        if not isinstance(payload.get("releaseUnblockPlan"), dict):
            execution_mode_file_evidence = _safe_dict(payload.get("executionModeFileEvidence"))
            release_packet = _safe_dict(payload.get("executionReleaseReadinessPacket"))
            payload["releaseUnblockPlan"] = _release_unblock_plan(
                post_target_summary=_safe_dict(payload.get("postTargetExecutionSummary")),
                release_packet=release_packet,
                release_checklist=_safe_list(payload.get("executionReleaseGateChecklist")),
                execution_mode_file_evidence=execution_mode_file_evidence,
                file_evidence_blockers=_safe_list(payload.get("fileEvidenceBlockers")),
            )
        assert_no_execution_flags(payload)
        return payload
    return {
        "ok": False,
        "schema": RELEASE_READINESS_REFRESH_SCHEMA_VERSION,
        "status": "INVALID",
        "path": str(path),
        "safety": dict(SAFETY),
    }
