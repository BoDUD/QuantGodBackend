from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .execution_spec import build_hfm_crypto_execution_spec_review
from .schema import (
    FILLED_INPUT_VALIDATOR_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    contract_spec_export_path,
    execution_spec_review_path,
    filled_contract_spec_path,
    filled_input_validator_path,
    filled_simulation_profile_path,
    simulation_profile_review_path,
    utc_now_iso,
)
from .simulation_profile import build_hfm_crypto_simulation_profile_review, read_hfm_crypto_simulation_profile_review


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _path_status(path: Path, *, input_id: str, label_zh: str, reason_zh: str) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    size = None
    mtime = None
    if exists:
        try:
            stat = path.stat()
            size = stat.st_size
            mtime = int(stat.st_mtime)
        except OSError:
            pass
    return {
        "id": input_id,
        "labelZh": label_zh,
        "path": str(path),
        "required": True,
        "exists": exists,
        "status": "PRESENT" if exists else "MISSING",
        "sizeBytes": size,
        "mtimeEpochSeconds": mtime,
        "reasonZh": reason_zh,
    }


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    return row


def _check(check_id: str, label_zh: str, passed: bool, reason_zh: str, evidence: Any = None) -> dict[str, Any]:
    row = {
        "id": check_id,
        "labelZh": label_zh,
        "passed": bool(passed),
        "status": "PASS" if passed else "BLOCKED",
        "reasonZh": reason_zh,
    }
    if evidence not in (None, "", []):
        row["evidence"] = evidence
    return row


def _artifact_summary(payload: dict[str, Any], extra_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    keys = (
        "schema",
        "status",
        "statusZh",
        "generatedAt",
        "readyForExecutionSpecReview",
        "validRowCount",
        "simulationQualified",
        *extra_keys,
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _prefixed_blockers(prefix: str, rows: Any) -> list[dict[str, Any]]:
    result = []
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "BLOCKER")
        result.append({
            **row,
            "code": f"{prefix}_{code}",
            "source": prefix.lower(),
        })
    return result


def _reviewed_execution_spec_fallback(runtime_dir: Path) -> dict[str, Any]:
    path = execution_spec_review_path(runtime_dir)
    if not path.exists() or not path.is_file():
        return {}
    payload = _read_json(path)
    return payload if payload.get("readyForExecutionSpecReview") else {}


def _execution_spec_review(runtime_dir: Path, spec_exists: bool, spec_path: Path) -> tuple[dict[str, Any], str, str]:
    if spec_exists:
        return (
            build_hfm_crypto_execution_spec_review(runtime_dir, contract_spec_json=str(spec_path), write=False),
            "filled_contract_spec",
            str(spec_path),
        )
    export_path = contract_spec_export_path(runtime_dir)
    if export_path.exists() and export_path.is_file():
        return (
            build_hfm_crypto_execution_spec_review(runtime_dir, contract_spec_json=str(export_path), write=False),
            "contract_spec_export",
            str(export_path),
        )
    reviewed = _reviewed_execution_spec_fallback(runtime_dir)
    if reviewed:
        return reviewed, "execution_spec_review_artifact", str(execution_spec_review_path(runtime_dir))
    return build_hfm_crypto_execution_spec_review(runtime_dir, contract_spec_json="", write=False), "", ""


def _simulation_profile_review(runtime_dir: Path, profile_exists: bool, profile_path: Path) -> tuple[dict[str, Any], str, str]:
    if profile_exists:
        return (
            build_hfm_crypto_simulation_profile_review(runtime_dir, simulation_profile_json=str(profile_path), write=False),
            "filled_simulation_profile",
            str(profile_path),
        )
    reviewed = read_hfm_crypto_simulation_profile_review(runtime_dir)
    if reviewed.get("simulationQualified"):
        return reviewed, "simulation_profile_review_artifact", str(simulation_profile_review_path(runtime_dir))
    return build_hfm_crypto_simulation_profile_review(runtime_dir, simulation_profile_json="", write=False), "", ""


def build_hfm_crypto_filled_input_validator(
    runtime_dir: Path,
    *,
    write: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    spec_path = filled_contract_spec_path(runtime_dir)
    profile_path = filled_simulation_profile_path(runtime_dir)
    spec_exists = spec_path.exists() and spec_path.is_file()
    profile_exists = profile_path.exists() and profile_path.is_file()
    execution_spec, contract_source, contract_source_path = _execution_spec_review(runtime_dir, spec_exists, spec_path)
    simulation_profile, simulation_source, simulation_source_path = _simulation_profile_review(runtime_dir, profile_exists, profile_path)
    spec_ready = bool(execution_spec.get("readyForExecutionSpecReview"))
    profile_ready = bool(simulation_profile.get("simulationQualified"))
    checklist = [
        _check(
            "contract_spec_input_source",
            "HFM contract spec 输入源",
            bool(contract_source),
            "需要 runtime/hfm_crypto/hfm_crypto_contract_specs.filled.json，或通过的 contract-spec export / execution-spec review artifact。",
            contract_source_path or str(spec_path),
        ),
        _check(
            "filled_contract_spec_fields",
            "人工 HFM contract spec 字段",
            spec_ready,
            "至少一个 crypto USD CFD 行必须包含 contractSize、tickSize、tickValue、minLot、lotStep、maxLot；可来自人工 filled specs 或 EA/MT5 自动导出的 HFM 官方 specs。",
            execution_spec.get("coveredBrokerSymbols"),
        ),
        _check(
            "simulation_profile_input_source",
            "HFM/Moss simulation profile 输入源",
            bool(simulation_source),
            "需要 runtime/hfm_crypto/hfm_crypto_simulation_profile.filled.json，或通过的 simulation profile review artifact。",
            simulation_source_path or str(profile_path),
        ),
        _check(
            "filled_simulation_profile_thresholds",
            "人工 HFM/Moss simulation profile 门槛",
            profile_ready,
            "ROI 必须为正，Sharpe >= 1.0，最大回撤 <= 15%，交易数 >= 20，爆仓次数为 0。",
            simulation_profile.get("metrics"),
        ),
    ]
    blockers: list[dict[str, Any]] = []
    if not contract_source:
        blockers.append(_blocker("HFM_CONTRACT_SPEC_REVIEW_INPUT_MISSING", "缺少人工 filled spec、EA/MT5 contract-spec export 或已通过的 execution-spec review artifact。", str(spec_path)))
    if not simulation_source:
        blockers.append(_blocker("HFM_SIMULATION_PROFILE_REVIEW_INPUT_MISSING", "缺少人工 filled simulation profile 或已通过的 simulation-profile review artifact。", str(profile_path)))
    if contract_source and not spec_ready:
        blockers.extend(_prefixed_blockers("FILLED_CONTRACT_SPEC", execution_spec.get("blockers")))
    if simulation_source and not profile_ready:
        blockers.extend(_prefixed_blockers("FILLED_SIMULATION_PROFILE", simulation_profile.get("blockers")))
    ready = spec_ready and profile_ready
    payload = {
        "ok": True,
        "schema": FILLED_INPUT_VALIDATOR_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": "FILLED_HFM_INPUTS_READY_FOR_REVIEW_CHAIN" if ready else "WAITING_FILLED_HFM_INPUTS",
        "statusZh": "人工 HFM 输入已可进入模拟转实盘审查链" if ready else "等待人工 HFM 输入补齐或修正",
        "filledInputsValid": ready,
        "reviewInputsValid": ready,
        "readyForEvidenceIntakeRefresh": ready,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "brokerExecutionAllowed": False,
        "adapterExecutionAllowed": False,
        "inputSources": {
            "contractSpecSource": contract_source,
            "contractSpecSourcePath": contract_source_path,
            "simulationProfileSource": simulation_source,
            "simulationProfileSourcePath": simulation_source_path,
            "manualFilledContractSpecPath": str(spec_path),
            "manualFilledSimulationProfilePath": str(profile_path),
            "contractSpecExportPath": str(contract_spec_export_path(runtime_dir)),
            "simulationProfileReviewPath": str(simulation_profile_review_path(runtime_dir)),
        },
        "inputFiles": [
            _path_status(
                spec_path,
                input_id="filled_contract_spec",
                label_zh="人工 HFM contract spec",
                reason_zh="人工从 HFM/MT5 或官方规格补齐的 crypto CFD 合约参数。",
            ),
            _path_status(
                profile_path,
                input_id="filled_simulation_profile",
                label_zh="人工 HFM/Moss simulation profile",
                reason_zh="模拟或回测表现证据，供 promotion candidate 和 review packet 使用。",
            ),
        ],
        "checklist": checklist,
        "artifacts": {
            "executionSpec": _artifact_summary(execution_spec),
            "simulationProfile": _artifact_summary(simulation_profile),
        },
        "coveredBrokerSymbols": execution_spec.get("coveredBrokerSymbols", []),
        "coveredCanonicalSymbols": execution_spec.get("coveredCanonicalSymbols", []),
        "simulationMetrics": simulation_profile.get("metrics", {}),
        "thresholds": simulation_profile.get("thresholds", {}),
        "refreshCommands": [
            {
                "id": "validate_filled_inputs",
                "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime filled-input-validator --write",
                "whenZh": "每次人工修改 filled spec/profile 后先跑这一条。",
            },
            {
                "id": "refresh_evidence_intake",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
                "whenZh": "filled inputs 验证通过后刷新证据接入。",
            },
            {
                "id": "refresh_promotion_candidates",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime promotion-candidates --write --refresh-sources",
                "whenZh": "证据接入通过后重新挑选实盘评审候选。",
            },
            {
                "id": "run_promotion_controller",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime promotion-controller --write --refresh-sources",
                "whenZh": "候选出现后自动生成 review packet、approval draft、dry-run plan 和 pipeline。",
            },
        ],
        "blockers": blockers,
        "nextRequiredActionZh": (
            "刷新 evidence-intake 和 promotion-candidates；系统会进入 review packet，而不是直接下单。"
            if ready
            else "先按 blockers 补齐人工 filled JSON，或生成通过的 contract-spec export / simulation-profile review artifact，再重新运行 filled-input-validator。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = filled_input_validator_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_filled_input_validator(runtime_dir: Path) -> dict[str, Any]:
    path = filled_input_validator_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        payload = _read_json(path)
        if payload:
            return {"ok": True, **payload}
    return build_hfm_crypto_filled_input_validator(Path(runtime_dir), write=False)
