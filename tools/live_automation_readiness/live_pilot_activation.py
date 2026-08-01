from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import re

from .adapter_contract_validator import build_adapter_contract_validator, read_adapter_contract_validator
from .approval import build_live_operator_approval_evidence_review, read_live_operator_approval_evidence_review
from .approval_context import operator_approval_json_for_refresh
from .execution_adapter_harness import build_execution_adapter_harness, read_execution_adapter_harness
from .orchestrator import build_sim_to_live_orchestrator, read_sim_to_live_orchestrator
from .pipeline import build_sim_to_live_automation_pipeline, read_sim_to_live_automation_pipeline
from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
from .schema import (
    LIVE_PILOT_ACTIVATION_REVIEW_SCHEMA_VERSION,
    SAFETY,
    adapter_contract_validator_path,
    approval_evidence_review_path,
    assert_no_execution_flags,
    execution_adapter_harness_path,
    live_pilot_activation_review_path,
    runtime_preflight_path,
    sim_to_live_pipeline_path,
    sim_to_live_orchestrator_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    return row


def _read_existing_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ready_existing_json(path: Path, ready_key: str) -> dict[str, Any]:
    payload = _read_existing_json(path)
    return payload if payload.get(ready_key) is True else {}


def _reviewable_existing_json(
    path: Path,
    *,
    ready_key: str,
    data_plane_keys: tuple[str, ...],
) -> dict[str, Any]:
    payload = _read_existing_json(path)
    if payload.get(ready_key) is True:
        return payload
    if payload.get("status") == "WAITING_EXECUTION_MODE_ACTIVATION" and any(
        payload.get(key) is True for key in data_plane_keys
    ):
        return payload
    return {}


def _dependency_source(payload: dict[str, Any], *, rebuilt_after_explicit_input: bool) -> str:
    if payload:
        return "existing_artifact"
    return "rebuilt_after_explicit_input" if rebuilt_after_explicit_input else "rebuilt_missing_artifact"


def _read_key_values(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"path": str(path), "exists": False, "values": {}}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except Exception as exc:
        return {"path": str(path), "exists": True, "readError": str(exc), "values": {}}
    for line in lines:
        text = line.strip()
        if not text or text.startswith(("#", ";", "//")) or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip()
    return {"path": str(path), "exists": True, "values": values}


def _read_ini_sections(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"path": str(path), "exists": False, "sections": {}}
    sections: dict[str, dict[str, str]] = {}
    current = ""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except Exception as exc:
        return {"path": str(path), "exists": True, "readError": str(exc), "sections": sections}
    for line in lines:
        text = line.strip()
        if not text or text.startswith(("#", ";", "//")):
            continue
        if text.startswith("[") and text.endswith("]"):
            current = text[1:-1].strip()
            sections.setdefault(current, {})
            continue
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        sections.setdefault(current, {})[key.strip()] = value.strip()
    return {"path": str(path), "exists": True, "sections": sections}


def _drive_c_root(runtime_dir: Path) -> Path | None:
    runtime_dir = Path(runtime_dir)
    for item in (runtime_dir, *runtime_dir.parents):
        if item.name == "drive_c":
            return item
    candidate = runtime_dir / "drive_c"
    if candidate.exists():
        return candidate
    return None


def _mt5_root(runtime_dir: Path) -> Path | None:
    runtime_dir = Path(runtime_dir)
    if runtime_dir.name == "Files" and runtime_dir.parent.name == "MQL5":
        return runtime_dir.parent.parent
    for item in (runtime_dir, *runtime_dir.parents):
        if item.name == "MetaTrader 5":
            return item
    return None


def _startup_config_path(runtime_dir: Path) -> Path:
    drive_c = _drive_c_root(runtime_dir)
    if drive_c:
        return drive_c / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"
    return Path(runtime_dir) / "drive_c" / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"


def _deployed_preset_path(runtime_dir: Path, expert_parameters: str = "") -> Path:
    preset_name = expert_parameters or "QuantGod_MT5_HFM_LiveSecondary.set"
    mt5_root = _mt5_root(runtime_dir)
    if mt5_root:
        return mt5_root / "MQL5" / "Presets" / preset_name
    return Path(runtime_dir) / "MQL5" / "Presets" / preset_name


def _gate_value(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    return "" if value is None else str(value)


def _live_pilot_file_evidence(runtime_dir: Path) -> dict[str, Any]:
    config = _read_ini_sections(_startup_config_path(runtime_dir))
    sections = _safe_dict(config.get("sections"))
    experts = _safe_dict(sections.get("Experts"))
    startup = _safe_dict(sections.get("StartUp"))
    expert_parameters = str(startup.get("ExpertParameters") or "QuantGod_MT5_HFM_LiveSecondary.set")
    preset = _read_key_values(_deployed_preset_path(runtime_dir, expert_parameters))
    preset_values = _safe_dict(preset.get("values"))
    selected_keys = (
        "Watchlist",
        "ReadOnlyMode",
        "EnablePilotAutoTrading",
        "EnablePilotRsiH1Live",
        "EnableEARequestReaderReviewHarness",
        "PilotStartupEntryGuardMode",
        "PilotStartupEntryMinWaitMinutes",
        "PilotStartupEntryWaitNextH1Bar",
        "PilotLotSize",
    )
    deployed_values = {key: _gate_value(preset_values, key) for key in selected_keys if key in preset_values}
    startup_values = {
        "AllowLiveTrading": _gate_value(experts, "AllowLiveTrading"),
        "Enabled": _gate_value(experts, "Enabled"),
        "Expert": _gate_value(startup, "Expert"),
        "ExpertParameters": expert_parameters,
        "Symbol": _gate_value(startup, "Symbol"),
        "Period": _gate_value(startup, "Period"),
    }
    blockers: list[dict[str, Any]] = []
    if startup_values["AllowLiveTrading"] == "0":
        blockers.append(_blocker(
            "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF",
            "Live16 启动 ini 的 [Experts] AllowLiveTrading=0；重新启动时仍会保持终端级 live trading 关闭。",
            startup_values["AllowLiveTrading"],
        ))
    if deployed_values.get("ReadOnlyMode") == "true":
        blockers.append(_blocker("DEPLOYED_PRESET_READ_ONLY_TRUE", "当前部署 preset 仍为 ReadOnlyMode=true。", "true"))
    if deployed_values.get("EnablePilotAutoTrading") == "false":
        blockers.append(_blocker("DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF", "当前部署 preset 仍为 EnablePilotAutoTrading=false。", "false"))
    if deployed_values.get("EnablePilotRsiH1Live") == "false":
        blockers.append(_blocker("DEPLOYED_PRESET_RSI_LIVE_OFF", "当前部署 preset 未开启 USDJPY RSI live route。", "false"))
    if deployed_values.get("EnableEARequestReaderReviewHarness") == "false":
        blockers.append(_blocker(
            "DEPLOYED_PRESET_EA_REQUEST_READER_OFF",
            "当前部署 preset 未开启 EA request reader review harness，外汇 request review 路径保持关闭。",
            "false",
        ))
    return {
        "startupConfig": {
            "path": config.get("path", ""),
            "exists": bool(config.get("exists")),
            "values": startup_values,
        },
        "deployedPreset": {
            "path": preset.get("path", ""),
            "exists": bool(preset.get("exists")),
            "values": deployed_values,
        },
        "restartWouldKeepExecutionDisabled": bool(blockers),
        "blockingEvidence": blockers,
        "writesMt5Preset": False,
        "writesStartupConfig": False,
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


def _check(check_id: str, label_zh: str, passed: bool, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {
        "id": check_id,
        "labelZh": label_zh,
        "passed": bool(passed),
        "status": "PASS" if passed else "BLOCKED",
        "reasonZh": reason_zh,
    }
    if value not in (None, "", []):
        row["value"] = value
    return row


def _operator_approval_id(approval: dict[str, Any]) -> str:
    for key in ("operatorApprovalId", "operatorId", "approvalId"):
        value = approval.get(key)
        if value:
            return str(value)
    return ""


def _pilot_envelope(
    *,
    approval: dict[str, Any],
    preflight: dict[str, Any],
    validator: dict[str, Any],
    harness: dict[str, Any],
) -> dict[str, Any]:
    approved_lanes = _safe_list(approval.get("approvedLanes") or preflight.get("approvedLanes"))
    lane_rows = _safe_list(validator.get("validationResults"))
    request_count = int(harness.get("plannedWriteCount") or validator.get("requestCount") or 0)
    return {
        "pilotMode": "REVIEW_ONLY_ACTIVATION_PACKET",
        "approvedLanes": approved_lanes,
        "requestCount": request_count,
        "reviewOnlyReceiptCount": int(harness.get("reviewOnlyReceiptCount") or 0),
        "operatorApprovalId": _operator_approval_id(approval),
        "dashboardSnapshot": _safe_dict(preflight.get("dashboardSnapshot")),
        "validatedRequestIds": [
            str(row.get("requestId") or "")
            for row in lane_rows
            if isinstance(row, dict) and row.get("requestId")
        ],
        "targetRequestDirectory": harness.get("requestDirectoryTarget") or "runtime/agent/mt5_order_requests",
        "targetReceiptDirectory": harness.get("receiptDirectoryTarget") or "runtime/agent/mt5_order_receipts",
        "maxInitialNotionalPolicyZh": "未来实盘 pilot 必须另行设置极小 notional/lot，上线前不得由本 artifact 自动放大。",
        "rollbackPolicyZh": "未来实盘 adapter 必须支持 kill switch、receipt reconciliation、自动暂停和人工回滚；当前 artifact 不执行。",
    }


def _review_checklist(
    *,
    orchestrator: dict[str, Any],
    harness: dict[str, Any],
    validator: dict[str, Any],
    pipeline: dict[str, Any],
    preflight: dict[str, Any],
    approval: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _check(
            "sim_to_live_orchestrator_ready",
            "sim-to-live 总控到达 adapter 实现评审边界",
            bool(orchestrator.get("readyForExecutionAdapterImplementationReview")),
            "需要证据、审批、dry-run、preflight、request contract、adapter review 全链路通过。",
            orchestrator.get("status"),
        ),
        _check(
            "pipeline_ready",
            "sim-to-live pipeline 到达单独 adapter 评审边界",
            bool(pipeline.get("readyForSeparateExecutionAdapterReview")),
            "需要 order request contract 先进入 adapter 代码评审状态。",
            pipeline.get("status"),
        ),
        _check(
            "runtime_preflight_passed",
            "MT5 运行时预检通过",
            bool(preflight.get("runtimeProbePassed")),
            "需要新鲜 dashboard、kill switch、账户、symbol 映射和价差探针。",
            preflight.get("status"),
        ),
        _check(
            "operator_approval_accepted",
            "人工审批证据已验收",
            bool(approval.get("operatorApprovalProvided")),
            "需要 operator approval JSON 绑定当前 reviewPacketHash 并确认所有必需项。",
            approval.get("status"),
        ),
        _check(
            "adapter_contract_validation_passed",
            "adapter request/receipt 合同离线验证通过",
            bool(validator.get("validationPassed")),
            "需要 request JSON 或 sandbox sample request 完整通过合同验证。",
            validator.get("status"),
        ),
        _check(
            "disabled_adapter_harness_ready",
            "禁用态 adapter harness 可评审",
            bool(harness.get("readyForDisabledAdapterImplementationReview")),
            "需要禁用态 request/receipt 写入计划、幂等、原子写和 review-only receipt 校验通过。",
            harness.get("status"),
        ),
        _check(
            "no_request_side_effects",
            "当前链路没有 request 文件写入",
            harness.get("requestWritesAllowed") is False and harness.get("requestFilesWritten") is False,
            "本阶段只允许审查，不允许写入 MT5 request/receipt 文件。",
        ),
        _check(
            "no_broker_calls",
            "当前链路没有 broker 调用",
            harness.get("brokerCallsMade") is False and harness.get("adapterExecutionAllowed") is False,
            "本阶段不允许 MT5 或 broker 真实执行调用。",
        ),
    ]


def _deployment_runbook() -> list[dict[str, Any]]:
    return [
        {
            "phase": "evidence_lock",
            "labelZh": "锁定证据版本",
            "requiredBeforeLivePilot": True,
            "actionZh": "把 MT5 symbol specs、simulation profile、operator approval、dashboard preflight hash 固定到同一个 review packet。",
        },
        {
            "phase": "adapter_code_review",
            "labelZh": "单独评审真实 adapter 实现",
            "requiredBeforeLivePilot": True,
            "actionZh": "未来 PR 必须只读取已验收 request contract，并提供 request reader、receipt writer、幂等和回滚测试。",
        },
        {
            "phase": "ea_request_reader_review",
            "labelZh": "MT5 EA request reader 评审",
            "requiredBeforeLivePilot": True,
            "actionZh": "EA 侧必须先审查 Files 目录读取、schema 校验、kill switch、只处理一笔 request 的幂等逻辑。",
        },
        {
            "phase": "pilot_limits",
            "labelZh": "实盘 pilot 额度限制",
            "requiredBeforeLivePilot": True,
            "actionZh": "首次 pilot 必须由操作者单独设置极小 lot/notional、单日损失、连续亏损、价差和滑点上限。",
        },
        {
            "phase": "receipt_reconciliation",
            "labelZh": "回执与风控对账",
            "requiredBeforeLivePilot": True,
            "actionZh": "任何未来实盘执行都必须有 receipt reconciliation、异常自动暂停、人工 kill switch 和审计日志。",
        },
    ]


def _candidate_setting(key: str, current: str, candidate: str, reason_zh: str) -> dict[str, Any]:
    return {
        "key": key,
        "currentValue": current,
        "candidateValue": candidate,
        "reasonZh": reason_zh,
    }


def _runtime_proof(field: str, current: Any, expected: Any, reason_zh: str) -> dict[str, Any]:
    return {
        "field": field,
        "current": current,
        "expected": expected,
        "reasonZh": reason_zh,
    }



def _review_only_preset_candidates(
    *,
    file_evidence: dict[str, Any],
    preflight: dict[str, Any],
    validator: dict[str, Any],
    harness: dict[str, Any],
) -> list[dict[str, Any]]:
    dashboard = _safe_dict(preflight.get("dashboardSnapshot"))
    return [{
        "candidateId": "usdjpy_forex_live_pilot_review_only",
        "lane": "forexMt5",
        "route": "USDJPY_RSI_H1_LIVE_PILOT",
        "status": "WAITING_OPERATOR_AND_RUNTIME_REVIEW",
        "statusZh": "USDJPY 外汇候选配置已定义，仍需人工与 runtime 评审",
        "sourcePresetFile": "MQL5/Presets/QuantGod_MT5_HFM_LiveSecondary.set",
        "candidatePresetName": "QuantGod_MT5_HFM_LivePilot_USDJPY_REVIEW_ONLY.set",
        "candidateFileWritten": False,
        "writesMt5Preset": False,
        "writesMt5OrderRequest": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "canAttachNow": False,
        "candidateSettings": [
            _candidate_setting("Watchlist", _current_preset_value(file_evidence, "Watchlist", "USDJPY"), "USDJPY", "只保留 USDJPY 外汇 watchlist。"),
            _candidate_setting("ReadOnlyMode", _current_preset_value(file_evidence, "ReadOnlyMode", "true"), "operator-reviewed false", "只有全部安全证据通过后才可人工审查解除。"),
            _candidate_setting("EnablePilotAutoTrading", _current_preset_value(file_evidence, "EnablePilotAutoTrading", "false"), "operator-reviewed true", "由 live pilot 总闸统一控制。"),
            _candidate_setting("EnablePilotRsiH1Live", _current_preset_value(file_evidence, "EnablePilotRsiH1Live", "false"), "operator-reviewed true", "只审查 USDJPY RSI H1 route。"),
            _candidate_setting("EnableEARequestReaderReviewHarness", _current_preset_value(file_evidence, "EnableEARequestReaderReviewHarness", "false"), "false", "外汇 pilot 不启用 request reader。"),
        ],
        "implementationPrerequisites": [
            "operator_approval_bound_to_review_packet",
            "runtime_preflight_passed",
            "kill_switch_and_permission_layers_passed",
            "isolated_tester_forward_passed",
        ],
        "expectedRuntimeProof": [
            _runtime_proof("symbolNames", dashboard.get("symbolNames", []), "USDJPY broker symbol", "dashboard 必须输出 USDJPY 实时 tick。"),
            _runtime_proof("adapterContractValidation", validator.get("status", ""), "reviewed", "合同验证保持只读。"),
            _runtime_proof("disabledHarness", harness.get("status", ""), "reviewed disabled harness", "harness 必须证明无 request 写入和无 broker 调用。"),
        ],
    }]


def _candidate_safety_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [
        {
            "id": "no_candidate_file_written",
            "passed": all(candidate.get("candidateFileWritten") is False for candidate in candidates),
            "status": "PASS",
            "reasonZh": "候选配置只存在于 JSON 审查产物，不写入 MT5 Presets 目录。",
        },
        {
            "id": "no_preset_mutation",
            "passed": all(candidate.get("writesMt5Preset") is False for candidate in candidates),
            "status": "PASS",
            "reasonZh": "本产物不会改 LiveSecondary 或任何 MT5 preset。",
        },
        {
            "id": "no_order_request_write",
            "passed": all(candidate.get("writesMt5OrderRequest") is False for candidate in candidates),
            "status": "PASS",
            "reasonZh": "本产物不会写 MT5 order request。",
        },
        {
            "id": "no_order_send",
            "passed": all(candidate.get("orderSendAllowed") is False for candidate in candidates),
            "status": "PASS",
            "reasonZh": "候选配置不允许 broker order send。",
        },
        {
            "id": "no_unreviewed_attach",
            "passed": all(candidate.get("canAttachNow") is False for candidate in candidates),
            "status": "PASS",
            "reasonZh": "候选配置必须先做人审、MT5 attach proof 和 runtime preflight。",
        },
    ]
    return {
        "status": "PASS_REVIEW_ONLY_NO_SIDE_EFFECTS" if all(row["passed"] for row in checks) else "BLOCKED",
        "statusZh": "候选 preset 只用于审查，无 MT5 preset 写入、无 request 写入、无 broker 调用。",
        "passed": all(row["passed"] for row in checks),
        "checks": checks,
    }


def _safe_candidate_file_stem(candidate: dict[str, Any]) -> str:
    raw = str(candidate.get("candidateId") or candidate.get("lane") or "candidate")
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return stem or "candidate"


def _render_review_only_candidate_text(candidate: dict[str, Any]) -> str:
    lines = [
        "; QuantGod review-only live pilot activation candidate",
        "; This file is NOT written to MQL5/Presets and must not be auto-attached.",
        "; Safety: writesMt5Preset=false, writesMt5OrderRequest=false, orderSendAllowed=false, canAttachNow=false.",
        f"; candidateId={candidate.get('candidateId', '')}",
        f"; lane={candidate.get('lane', '')}",
        f"; route={candidate.get('route', '')}",
        f"; status={candidate.get('status', '')}",
        "",
    ]
    for setting in _safe_list(candidate.get("candidateSettings")):
        if not isinstance(setting, dict):
            continue
        key = str(setting.get("key") or "")
        value = str(setting.get("candidateValue") or "")
        reason = str(setting.get("reasonZh") or "")
        if not key:
            continue
        review_required = any(
            marker in value.lower()
            for marker in ("operator", "review", "after broker-send")
        )
        prefix = "; REVIEW_REQUIRED " if review_required else ""
        lines.append(f"{prefix}{key}={value}")
        if reason:
            lines.append(f"; reasonZh={reason}")
    lines.extend([
        "",
        "; Required runtime proof after any separate manual attach:",
    ])
    for proof in _safe_list(candidate.get("expectedRuntimeProof")):
        if not isinstance(proof, dict):
            continue
        lines.append(
            f"; - {proof.get('field', '')}: current={proof.get('current', '')} expected={proof.get('expected', '')}"
        )
    return "\n".join(lines) + "\n"


def _review_only_candidate_file_package(
    runtime_dir: Path,
    package: dict[str, Any],
    *,
    write: bool,
) -> dict[str, Any]:
    candidate_dir = Path(runtime_dir) / "agent" / "review_only_activation_candidates"
    candidates = [row for row in _safe_list(package.get("reviewOnlyPresetCandidates")) if isinstance(row, dict)]
    manifest_path = candidate_dir / "QuantGod_LivePilotActivationCandidateManifest.json"
    file_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        stem = _safe_candidate_file_stem(candidate)
        preview_path = candidate_dir / f"{stem}.review-only.txt"
        row = {
            "candidateId": candidate.get("candidateId", ""),
            "lane": candidate.get("lane", ""),
            "route": candidate.get("route", ""),
            "previewPath": str(preview_path),
            "reviewArtifactFileWritten": bool(write),
            "candidateFileWritten": False,
            "writesMt5Preset": False,
            "writesStartupConfig": False,
            "writesMt5OrderRequest": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "canAttachNow": False,
        }
        file_rows.append(row)
        if write:
            candidate_dir.mkdir(parents=True, exist_ok=True)
            preview_path.write_text(_render_review_only_candidate_text(candidate), encoding="utf-8")
    manifest = {
        "schema": "quantgod.review_only_live_pilot_activation_candidate_files.v1",
        "packageMode": "REVIEW_ONLY_ACTIVATION_CANDIDATE_FILES_NO_MT5_MUTATION",
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "candidateDirectory": str(candidate_dir),
        "manifestPath": str(manifest_path),
        "reviewArtifactFilesWritten": bool(write),
        "candidateCount": len(candidates),
        "files": file_rows,
        "safety": {
            "reviewOnly": True,
            "writesMt5Preset": False,
            "writesStartupConfig": False,
            "writesMt5OrderRequest": False,
            "requestFilesWritten": False,
            "receiptFilesWritten": False,
            "brokerCallsMade": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "livePilotActivationAllowed": False,
        },
        "nextRequiredActionZh": "这些文件只是 review-only 候选包；不能自动复制到 MT5 Presets，也不能触发订单。后续必须另行完成执行 lane 评审和 runtime proof。",
    }
    if write:
        candidate_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _current_preset_value(file_evidence: dict[str, Any], key: str, default: str = "") -> str:
    values = _safe_dict(_safe_dict(file_evidence.get("deployedPreset")).get("values"))
    value = values.get(key)
    if value in (None, ""):
        return default
    return str(value)


def _current_startup_value(file_evidence: dict[str, Any], key: str, default: str = "") -> str:
    values = _safe_dict(_safe_dict(file_evidence.get("startupConfig")).get("values"))
    value = values.get(key)
    if value in (None, ""):
        return default
    return str(value)


def _diff_change(
    key: str,
    current: str,
    candidate: str,
    reason_zh: str,
    *,
    risk_guard_retained: bool = True,
    requires_runtime_proof: bool = True,
) -> dict[str, Any]:
    return {
        "key": key,
        "current": current,
        "candidate": candidate,
        "reasonZh": reason_zh,
        "riskGuardRetained": bool(risk_guard_retained),
        "requiresRuntimeProof": bool(requires_runtime_proof),
    }




def _review_only_preset_diff_package(
    *,
    file_evidence: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate = candidates[0] if candidates else {}
    changes = [
        _diff_change("Watchlist", _current_preset_value(file_evidence, "Watchlist", "USDJPY"), "USDJPY", "只保留 USDJPY 外汇 symbol。"),
        _diff_change("ReadOnlyMode", _current_preset_value(file_evidence, "ReadOnlyMode", "true"), "operator-reviewed false", "必须保留人工复核与全部安全闸。"),
        _diff_change("EnablePilotAutoTrading", _current_preset_value(file_evidence, "EnablePilotAutoTrading", "false"), "operator-reviewed true", "仅在独立激活评审后人工启用。"),
        _diff_change("EnablePilotRsiH1Live", _current_preset_value(file_evidence, "EnablePilotRsiH1Live", "false"), "operator-reviewed true", "仅审查 USDJPY RSI H1 route。"),
        _diff_change("EnableEARequestReaderReviewHarness", _current_preset_value(file_evidence, "EnableEARequestReaderReviewHarness", "false"), "false", "外汇 pilot 保持 request reader 关闭。"),
    ]
    return {
        "mode": "REVIEW_ONLY_PRESET_DIFF_PACKAGE_NO_FILE_WRITE",
        "lane": "forexMt5",
        "candidatePresetName": candidate.get("candidatePresetName"),
        "changes": changes,
        "writesMt5Preset": False,
        "writesStartupConfig": False,
        "writesMt5OrderRequest": False,
        "orderSendAllowed": False,
        "canAttachNow": False,
    }


def _preset_activation_package(
    *,
    runtime_dir: Path,
    approval: dict[str, Any],
    preflight: dict[str, Any],
    validator: dict[str, Any],
    harness: dict[str, Any],
) -> dict[str, Any]:
    file_evidence = _live_pilot_file_evidence(runtime_dir)
    candidates = _review_only_preset_candidates(
        file_evidence=file_evidence,
        preflight=preflight,
        validator=validator,
        harness=harness,
    )
    return {
        "mode": "REVIEW_ONLY_ACTIVATION_PACKAGE_NO_FILE_WRITE",
        "approvedLanes": _safe_list(approval.get("approvedLanes") or preflight.get("approvedLanes")),
        "liveRuntimeFileEvidence": file_evidence,
        "reviewOnlyPresetCandidates": candidates,
        "candidateSafetyValidation": _candidate_safety_validation(candidates),
        "reviewOnlyPresetDiffPackage": _review_only_preset_diff_package(
            file_evidence=file_evidence,
            candidates=candidates,
        ),
        "candidateFileWritten": False,
        "writesMt5Preset": False,
        "writesStartupConfig": False,
        "writesMt5OrderRequest": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "canAttachNow": False,
    }


def _blockers_from_checklist(checklist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in checklist:
        if item.get("passed"):
            continue
        rows.append(_blocker("LIVE_PILOT_ACTIVATION_CHECK_NOT_PASSED", str(item.get("reasonZh") or "live pilot activation review check 未通过。"), item.get("id")))
    return rows


def build_live_pilot_activation_review(
    runtime_dir: Path,
    *,
    request_json: str = "",
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    extra_bases_roots: list[str] | None = None,
    **_retired_inputs: Any,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    should_rebuild = bool(refresh_sources or request_json)
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    common = {
        "operator_approval_json": operator_approval_json,
        "write": bool(write and refresh_sources),
        "refresh_sources": refresh_sources,
        "extra_bases_roots": extra_bases_roots or [],
    }
    adapter = {**common, "request_json": request_json}
    explicit_dependency_inputs = bool(
        should_rebuild
        or operator_approval_json
        or extra_bases_roots
    )
    orchestrator = (
        _reviewable_existing_json(
            sim_to_live_orchestrator_path(runtime_dir),
            ready_key="readyForExecutionAdapterImplementationReview",
            data_plane_keys=("dataPlaneOrchestratorReady",),
        )
        if explicit_dependency_inputs
        else _read_existing_json(sim_to_live_orchestrator_path(runtime_dir))
    )
    harness = (
        _reviewable_existing_json(
            execution_adapter_harness_path(runtime_dir),
            ready_key="readyForDisabledAdapterImplementationReview",
            data_plane_keys=("dataPlaneHarnessReady",),
        )
        if explicit_dependency_inputs
        else _read_existing_json(execution_adapter_harness_path(runtime_dir))
    )
    validator = (
        _reviewable_existing_json(
            adapter_contract_validator_path(runtime_dir),
            ready_key="validationPassed",
            data_plane_keys=("dataPlaneValidationReady", "sampleValidationPassed"),
        )
        if explicit_dependency_inputs
        else _read_existing_json(adapter_contract_validator_path(runtime_dir))
    )
    orchestrator_source = _dependency_source(orchestrator, rebuilt_after_explicit_input=explicit_dependency_inputs)
    harness_source = _dependency_source(harness, rebuilt_after_explicit_input=explicit_dependency_inputs)
    validator_source = _dependency_source(validator, rebuilt_after_explicit_input=explicit_dependency_inputs)
    if not orchestrator:
        orchestrator = build_sim_to_live_orchestrator(runtime_dir, **adapter) if explicit_dependency_inputs else read_sim_to_live_orchestrator(runtime_dir)
    if not validator:
        validator = build_adapter_contract_validator(runtime_dir, **adapter) if explicit_dependency_inputs else read_adapter_contract_validator(runtime_dir)
    if not harness:
        harness = build_execution_adapter_harness(runtime_dir, **adapter) if explicit_dependency_inputs else read_execution_adapter_harness(runtime_dir)
    pipeline_path = sim_to_live_pipeline_path(runtime_dir)
    preflight_path = runtime_preflight_path(runtime_dir)
    approval_path = approval_evidence_review_path(runtime_dir)
    pipeline = _read_existing_json(pipeline_path) if not explicit_dependency_inputs else {}
    preflight = _read_existing_json(preflight_path) if not explicit_dependency_inputs else {}
    approval = _read_existing_json(approval_path) if not explicit_dependency_inputs else {}
    if explicit_dependency_inputs:
        pipeline = _reviewable_existing_json(
            pipeline_path,
            ready_key="readyForSeparateExecutionAdapterReview",
            data_plane_keys=("dataPlanePipelineReady",),
        )
        preflight = _reviewable_existing_json(
            preflight_path,
            ready_key="runtimeProbePassed",
            data_plane_keys=("dataPlaneReadyForLivePilotReview",),
        )
        approval = _ready_existing_json(approval_path, "operatorApprovalProvided")
    pipeline_source = _dependency_source(pipeline, rebuilt_after_explicit_input=explicit_dependency_inputs)
    preflight_source = _dependency_source(preflight, rebuilt_after_explicit_input=explicit_dependency_inputs)
    approval_source = _dependency_source(approval, rebuilt_after_explicit_input=explicit_dependency_inputs)
    if not pipeline:
        pipeline = build_sim_to_live_automation_pipeline(runtime_dir, **common) if explicit_dependency_inputs else read_sim_to_live_automation_pipeline(runtime_dir)
    if not preflight:
        preflight = build_live_runtime_preflight_probe(runtime_dir, **common) if explicit_dependency_inputs else read_live_runtime_preflight_probe(runtime_dir)
    if not approval:
        approval = build_live_operator_approval_evidence_review(runtime_dir, **common) if explicit_dependency_inputs else read_live_operator_approval_evidence_review(runtime_dir)
    checklist = _review_checklist(
        orchestrator=orchestrator,
        harness=harness,
        validator=validator,
        pipeline=pipeline,
        preflight=preflight,
        approval=approval,
    )
    review_ready = bool(
        checklist
        and all(row.get("passed") for row in checklist)
        and harness.get("readyForDisabledAdapterImplementationReview")
    )
    execution_mode_only_blocked = bool(
        preflight.get("executionModeOnlyBlocked")
        or validator.get("contractExecutionModeOnlyBlocked")
        or harness.get("executionModeOnlyBlocked")
    )
    preflight_data_plane_ready = bool(
        preflight.get("dataPlaneReadyForLivePilotReview")
        or validator.get("contractDataPlaneReadyForReview")
        or harness.get("dataPlaneHarnessReady")
    )
    validator_data_plane_ready = bool(
        validator.get("dataPlaneValidationReady")
        or (
            validator.get("sampleValidationPassed")
            and validator.get("contractExecutionModeOnlyBlocked")
        )
    )
    data_plane_activation_ready = bool(
        approval.get("operatorApprovalProvided")
        and preflight_data_plane_ready
        and validator_data_plane_ready
        and harness.get("dataPlaneHarnessReady")
        and harness.get("requestWritesAllowed") is False
        and harness.get("requestFilesWritten") is False
        and harness.get("brokerCallsMade") is False
        and harness.get("adapterExecutionAllowed") is False
    )
    live_runtime_file_evidence = _live_pilot_file_evidence(runtime_dir)
    blockers = _blockers_from_checklist(checklist)
    if data_plane_activation_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "live pilot 激活包数据面已具备；仅等待 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 执行模式闸门。",
                preflight.get("status"),
            )
        ]
        blockers.extend(
            item
            for item in _safe_list(preflight.get("executionModeBlockers"))
            if isinstance(item, dict)
        )
    blockers.extend(
        item
        for item in _safe_list(live_runtime_file_evidence.get("blockingEvidence"))
        if isinstance(item, dict)
    )
    activation_package = _preset_activation_package(
        runtime_dir=runtime_dir,
        approval=approval,
        preflight=preflight,
        validator=validator,
        harness=harness,
    )
    activation_package["reviewOnlyCandidateFilePackage"] = _review_only_candidate_file_package(
        runtime_dir,
        activation_package,
        write=write,
    )
    payload = {
        "ok": True,
        "schema": LIVE_PILOT_ACTIVATION_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_LIVE_PILOT_ACTIVATION_REVIEW"
            if review_ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_activation_ready and execution_mode_only_blocked
            else "WAITING_LIVE_PILOT_ACTIVATION_INPUTS"
        ),
        "statusZh": (
            "可进入 live pilot 激活评审"
            if review_ready
            else "live pilot 激活包数据面已通过，等待执行模式闸门"
            if data_plane_activation_ready and execution_mode_only_blocked
            else "等待 live pilot 激活评审输入"
        ),
        "activationMode": "LIVE_PILOT_ACTIVATION_REVIEW_ONLY_NO_EXECUTION",
        "readyForLivePilotActivationReview": review_ready,
        "dataPlaneActivationReady": data_plane_activation_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "livePilotActivationAllowed": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "brokerExecutionAllowed": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "dependencyRefreshMode": {
            "refreshSources": bool(refresh_sources),
            "explicitDependencyInputs": explicit_dependency_inputs,
            "orchestrator": orchestrator_source,
            "pipeline": pipeline_source,
            "runtimePreflight": preflight_source,
            "approvalEvidence": approval_source,
            "adapterContractValidator": validator_source,
            "adapterHarness": harness_source,
        },
        "preflightDataPlaneReadyForActivation": preflight_data_plane_ready,
        "validatorDataPlaneReadyForActivation": validator_data_plane_ready,
        "requestJsonProvided": bool(request_json),
        "reviewChecklist": checklist,
        "pilotEnvelope": _pilot_envelope(
            approval=approval,
            preflight=preflight,
            validator=validator,
            harness=harness,
        ),
        "presetActivationPackage": activation_package,
        "deploymentRunbook": _deployment_runbook(),
        "artifacts": {
            "orchestrator": _artifact_summary(orchestrator, ("readyForExecutionAdapterImplementationReview", "currentStage")),
            "pipeline": _artifact_summary(pipeline, ("readyForSeparateExecutionAdapterReview", "autoStage")),
            "runtimePreflight": _artifact_summary(preflight, ("runtimeProbePassed", "reviewPacketHash")),
            "approvalEvidence": _artifact_summary(approval, ("operatorApprovalProvided", "reviewPacketHash")),
            "adapterContractValidator": _artifact_summary(
                validator,
                (
                    "validationPassed",
                    "sampleValidationPassed",
                    "dataPlaneValidationReady",
                    "contractExecutionModeOnlyBlocked",
                    "requestCount",
                    "receiptCount",
                ),
            ),
            "adapterHarness": _artifact_summary(
                harness,
                (
                    "readyForDisabledAdapterImplementationReview",
                    "dataPlaneHarnessReady",
                    "executionModeOnlyBlocked",
                    "plannedWriteCount",
                    "reviewOnlyReceiptCount",
                ),
            ),
        },
        "forbiddenUntilFutureReviewedExecutionLane": [
            "writing MT5 request files",
            "calling MT5 OrderSend or OrderSendAsync",
            "mutating MT5 presets",
            "storing credentials",
            "enabling Telegram or webhook execution",
            "increasing pilot notional without fresh operator approval",
        ],
        "blockers": blockers[:24],
        "nextRequiredActionZh": (
            "进入单独 live adapter implementation/EA request reader/rollback 评审；本 artifact 仍不会写订单或调用 broker。"
            if review_ready
            else "live pilot 激活包数据面、审批、样本、harness 和无副作用证据已具备；仅剩执行模式闸门，当前仍不会写订单或调用 broker。"
            if data_plane_activation_ready and execution_mode_only_blocked
            else "先让 orchestrator、adapter contract validator、disabled harness、preflight 和审批证据全部通过。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_pilot_activation_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_pilot_activation_review(runtime_dir: Path) -> dict[str, Any]:
    path = live_pilot_activation_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_live_pilot_activation_review(Path(runtime_dir), write=False)
