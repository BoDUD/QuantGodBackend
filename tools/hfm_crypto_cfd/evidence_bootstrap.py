from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence_kit import build_hfm_crypto_evidence_kit, read_hfm_crypto_evidence_kit
from .filled_input_validator import build_hfm_crypto_filled_input_validator, read_hfm_crypto_filled_input_validator
from .schema import (
    EVIDENCE_BOOTSTRAP_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    contract_spec_draft_path,
    evidence_bootstrap_path,
    filled_contract_spec_path,
    filled_simulation_profile_path,
    operator_approval_draft_path,
    simulation_profile_draft_path,
    state_path,
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


def _write_json_if_missing(path: Path, payload: dict[str, Any], *, overwrite: bool) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    wrote = bool(overwrite or not existed)
    if wrote:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "path": str(path),
        "existsBefore": existed,
        "writtenByThisRun": wrote,
        "overwriteAllowed": bool(overwrite),
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _contract_spec_draft(kit: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "quantgod.hfm_crypto_cfd.contract_spec_filled_draft.v1",
        "generatedAtIso": utc_now_iso(),
        "sourceTemplate": kit.get("outputFiles", {}).get("contractSpecTemplateJson", ""),
        "operatorInstructionZh": "把真实 HFM/MT5 SymbolInfo* 或 broker 合约规格填入 null 字段；确认后另存为 hfm_crypto_contract_specs.filled.json。",
        "symbols": _safe_dict(kit.get("contractSpecTemplate")).get("symbols", []),
        "requiredFields": kit.get("requiredContractSpecFields", []),
        "optionalFields": kit.get("optionalContractSpecFields", []),
    }


def _simulation_profile_draft(kit: dict[str, Any]) -> dict[str, Any]:
    template = _safe_dict(kit.get("simulationProfileTemplate"))
    return {
        "schema": "quantgod.hfm_crypto_cfd.simulation_profile_filled_draft.v1",
        "generatedAtIso": utc_now_iso(),
        "sourceTemplate": kit.get("outputFiles", {}).get("simulationProfileTemplateJson", ""),
        "operatorInstructionZh": "把 Moss/模拟回测的 USD pnl、ROI、Sharpe、最大回撤、交易笔数和爆仓次数填入；确认后另存为 hfm_crypto_simulation_profile.filled.json。",
        **template,
    }


def _approval_draft(runtime_dir: Path) -> dict[str, Any]:
    try:
        from tools.live_automation_readiness.approval import build_live_operator_approval_draft
    except ModuleNotFoundError:  # pragma: no cover
        from live_automation_readiness.approval import build_live_operator_approval_draft

    draft = build_live_operator_approval_draft(Path(runtime_dir), write=False)
    template = _safe_dict(draft.get("manualApprovalTemplate"))
    return {
        "schema": "quantgod.live_operator_approval_filled_draft.v1",
        "generatedAtIso": utc_now_iso(),
        "sourceApprovalDraftStatus": draft.get("status", ""),
        "operatorInstructionZh": "只有 reviewCandidateLanes 非空且人工逐项确认后，才把本文件另存为 operator_approval.filled.json 并交给 approval-evidence。",
        **template,
    }


def _live_summaries(runtime_dir: Path) -> dict[str, Any]:
    try:
        from tools.live_automation_readiness.schema import (
            execution_adapter_harness_path,
            live_evidence_intake_path,
            sim_to_live_orchestrator_path,
        )
    except ModuleNotFoundError:  # pragma: no cover
        from live_automation_readiness.schema import (
            execution_adapter_harness_path,
            live_evidence_intake_path,
            sim_to_live_orchestrator_path,
        )

    evidence = _read_json_file(live_evidence_intake_path(runtime_dir))
    orchestrator = _read_json_file(sim_to_live_orchestrator_path(runtime_dir))
    harness = _read_json_file(execution_adapter_harness_path(runtime_dir))
    return {
        "evidenceIntake": {
            "schema": evidence.get("schema", ""),
            "status": evidence.get("status", ""),
            "statusZh": evidence.get("statusZh", ""),
            "missingChecklistCount": _safe_dict(evidence.get("fileInputSummary")).get("missingChecklistCount", 0),
        },
        "orchestrator": {
            "schema": orchestrator.get("schema", ""),
            "status": orchestrator.get("status", ""),
            "statusZh": orchestrator.get("statusZh", ""),
            "currentStage": orchestrator.get("currentStage", ""),
            "currentStageZh": orchestrator.get("currentStageZh", ""),
            "passedStageCount": orchestrator.get("passedStageCount", 0),
            "stageCount": orchestrator.get("stageCount", 0),
        },
        "adapterHarness": {
            "schema": harness.get("schema", ""),
            "status": harness.get("status", ""),
            "statusZh": harness.get("statusZh", ""),
            "plannedWriteCount": harness.get("plannedWriteCount", 0),
        },
    }


def _draft_rows(runtime_dir: Path, writes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row_id, label, path, target in (
        ("contract_spec_draft", "合约规格草稿", contract_spec_draft_path(runtime_dir), filled_contract_spec_path(runtime_dir)),
        ("simulation_profile_draft", "模拟表现草稿", simulation_profile_draft_path(runtime_dir), filled_simulation_profile_path(runtime_dir)),
        ("operator_approval_draft", "人工审批草稿", operator_approval_draft_path(runtime_dir), Path(runtime_dir) / "hfm_crypto" / "operator_approval.filled.json"),
    ):
        write_info = _safe_dict(writes.get(row_id))
        rows.append({
            "id": row_id,
            "labelZh": label,
            "draftPath": str(path),
            "targetFilledPath": str(target),
            "draftExists": path.exists(),
            "targetFilledExists": target.exists(),
            "writtenByThisRun": bool(write_info.get("writtenByThisRun")),
            "mustFillManually": True,
        })
    return rows


def build_hfm_crypto_evidence_bootstrap(
    runtime_dir: Path,
    *,
    write: bool = False,
    overwrite_drafts: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    kit = build_hfm_crypto_evidence_kit(runtime_dir, write=write)
    state = _read_json_file(state_path(runtime_dir))
    filled_validator = build_hfm_crypto_filled_input_validator(runtime_dir, write=write) if write else read_hfm_crypto_filled_input_validator(runtime_dir)
    live = _live_summaries(runtime_dir)
    writes: dict[str, dict[str, Any]] = {}
    if write:
        writes["contract_spec_draft"] = _write_json_if_missing(
            contract_spec_draft_path(runtime_dir),
            _contract_spec_draft(kit),
            overwrite=overwrite_drafts,
        )
        writes["simulation_profile_draft"] = _write_json_if_missing(
            simulation_profile_draft_path(runtime_dir),
            _simulation_profile_draft(kit),
            overwrite=overwrite_drafts,
        )
        writes["operator_approval_draft"] = _write_json_if_missing(
            operator_approval_draft_path(runtime_dir),
            _approval_draft(runtime_dir),
            overwrite=overwrite_drafts,
        )
    draft_rows = _draft_rows(runtime_dir, writes)
    blockers: list[dict[str, Any]] = []
    if not bool(filled_validator.get("filledInputsValid")):
        blockers.append(_blocker("FILLED_INPUTS_NOT_VALID", "filled specs/profile 尚未通过校验。", filled_validator.get("status")))
        blockers.extend(item for item in _safe_list(filled_validator.get("blockers"))[:8] if isinstance(item, dict))
    if _safe_dict(live.get("evidenceIntake")).get("status") != "HFM_REVIEW_INPUTS_PRESENT":
        blockers.append(_blocker("LIVE_EVIDENCE_INTAKE_NOT_READY", "live evidence intake 尚未看到完整 HFM review 输入。", _safe_dict(live.get("evidenceIntake")).get("status")))
    ready = bool(filled_validator.get("filledInputsValid") and _safe_dict(live.get("evidenceIntake")).get("status") == "HFM_REVIEW_INPUTS_PRESENT")
    payload = {
        "ok": True,
        "schema": EVIDENCE_BOOTSTRAP_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "HFM_EVIDENCE_BOOTSTRAP_READY_FOR_REVIEW_REFRESH" if ready else "WAITING_HFM_EVIDENCE_BOOTSTRAP_INPUTS",
        "statusZh": "HFM 证据 bootstrap 已可刷新实盘评审链" if ready else "等待 HFM 证据 bootstrap 输入",
        "bootstrapMode": "DRAFTS_AND_REVIEW_ARTIFACTS_ONLY",
        "filledInputsValid": bool(filled_validator.get("filledInputsValid")),
        "readyForEvidenceIntakeRefresh": bool(filled_validator.get("readyForEvidenceIntakeRefresh")),
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "draftFiles": draft_rows,
        "artifactSummary": {
            "evidenceKit": {"status": kit.get("status", ""), "statusZh": kit.get("statusZh", "")},
            "hfmState": {"status": state.get("status", ""), "statusZh": state.get("statusZh", "")},
            "filledInputValidator": {
                "status": filled_validator.get("status", ""),
                "statusZh": filled_validator.get("statusZh", ""),
                "filledInputsValid": bool(filled_validator.get("filledInputsValid")),
            },
            **live,
        },
        "commands": [
            {
                "id": "write_bootstrap",
                "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime evidence-bootstrap --write",
                "whenZh": "重新生成草稿和 bootstrap 状态。",
            },
            {
                "id": "validate_filled_inputs",
                "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime filled-input-validator --write",
                "whenZh": "把 draft 人工补齐并另存为 filled JSON 后先跑。",
            },
            {
                "id": "refresh_live_intake",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
                "whenZh": "filled 输入通过后刷新 live evidence intake。",
            },
            {
                "id": "run_sim_to_live_orchestrator",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime orchestrator --write --refresh-sources",
                "whenZh": "证据、审批、预检逐步补齐后跑完整总控。",
            },
            {
                "id": "run_adapter_harness",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime adapter-harness --write --refresh-sources",
                "whenZh": "总控和合同验证通过后生成禁用态 adapter harness。",
            },
        ],
        "blockers": blockers,
        "nextRequiredActionZh": (
            "filled 输入已可进入 live evidence intake；刷新 evidence-intake 和 orchestrator。"
            if ready
            else "先把 draft 中的 HFM 合约规格和模拟表现补成真实 filled JSON，再运行 filled-input-validator。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = evidence_bootstrap_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_evidence_bootstrap(runtime_dir: Path) -> dict[str, Any]:
    path = evidence_bootstrap_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_hfm_crypto_evidence_bootstrap(Path(runtime_dir), write=False)
