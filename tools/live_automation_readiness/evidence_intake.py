from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapter_contract_validator import build_adapter_contract_validator, read_adapter_contract_validator
from .execution_adapter_review import build_execution_adapter_review, read_execution_adapter_review
from .pipeline import build_sim_to_live_automation_pipeline, read_sim_to_live_automation_pipeline
from .preflight import build_live_runtime_preflight_probe, read_live_runtime_preflight_probe
from .schema import (
    LIVE_EVIDENCE_INTAKE_SCHEMA_VERSION,
    SAFETY,
    adapter_contract_validator_path,
    assert_no_execution_flags,
    live_evidence_intake_path,
    utc_now_iso,
)

try:
    from tools.hfm_crypto_cfd.builder import build_hfm_crypto_cfd_state, read_hfm_crypto_cfd_state
    from tools.hfm_crypto_cfd.contract_spec_export import (
        build_hfm_crypto_contract_spec_export,
        read_hfm_crypto_contract_spec_export,
    )
    from tools.hfm_crypto_cfd.evidence_kit import build_hfm_crypto_evidence_kit, read_hfm_crypto_evidence_kit
    from tools.hfm_crypto_cfd.execution_spec import (
        build_hfm_crypto_execution_spec_review,
        read_hfm_crypto_execution_spec_review,
    )
    from tools.hfm_crypto_cfd.filled_input_validator import (
        build_hfm_crypto_filled_input_validator,
        read_hfm_crypto_filled_input_validator,
    )
    from tools.hfm_crypto_cfd.mt5_exporter_review import (
        build_hfm_crypto_mt5_exporter_review,
        read_hfm_crypto_mt5_exporter_review,
    )
    from tools.hfm_crypto_cfd.mt5_upgrade_bundle import (
        build_hfm_crypto_mt5_upgrade_bundle,
        read_hfm_crypto_mt5_upgrade_bundle,
    )
    from tools.hfm_crypto_cfd.mt5_post_upgrade_verify import (
        build_hfm_crypto_mt5_post_upgrade_verify,
        read_hfm_crypto_mt5_post_upgrade_verify,
    )
    from tools.hfm_crypto_cfd.post_upgrade_controller import (
        build_hfm_crypto_post_upgrade_controller,
        read_hfm_crypto_post_upgrade_controller,
    )
    from tools.hfm_crypto_cfd.schema import (
        EA_SYMBOL_SPECS_FILE,
        FILLED_CONTRACT_SPEC_FILE,
        FILLED_SIMULATION_PROFILE_FILE,
        contract_spec_export_path,
        evidence_kit_path,
        execution_spec_review_path,
        filled_input_validator_path,
        filled_contract_spec_path,
        filled_simulation_profile_path,
        hfm_crypto_dir,
        mt5_exporter_review_path,
        mt5_exporter_upgrade_bundle_path,
        mt5_post_upgrade_verify_path,
        post_upgrade_controller_path,
        simulation_profile_review_path,
    )
    from tools.hfm_crypto_cfd.simulation_profile import (
        build_hfm_crypto_simulation_profile_review,
        read_hfm_crypto_simulation_profile_review,
    )
except ModuleNotFoundError:  # pragma: no cover
    from hfm_crypto_cfd.builder import build_hfm_crypto_cfd_state, read_hfm_crypto_cfd_state
    from hfm_crypto_cfd.contract_spec_export import (
        build_hfm_crypto_contract_spec_export,
        read_hfm_crypto_contract_spec_export,
    )
    from hfm_crypto_cfd.evidence_kit import build_hfm_crypto_evidence_kit, read_hfm_crypto_evidence_kit
    from hfm_crypto_cfd.execution_spec import (
        build_hfm_crypto_execution_spec_review,
        read_hfm_crypto_execution_spec_review,
    )
    from hfm_crypto_cfd.filled_input_validator import (
        build_hfm_crypto_filled_input_validator,
        read_hfm_crypto_filled_input_validator,
    )
    from hfm_crypto_cfd.mt5_exporter_review import (
        build_hfm_crypto_mt5_exporter_review,
        read_hfm_crypto_mt5_exporter_review,
    )
    from hfm_crypto_cfd.mt5_upgrade_bundle import (
        build_hfm_crypto_mt5_upgrade_bundle,
        read_hfm_crypto_mt5_upgrade_bundle,
    )
    from hfm_crypto_cfd.mt5_post_upgrade_verify import (
        build_hfm_crypto_mt5_post_upgrade_verify,
        read_hfm_crypto_mt5_post_upgrade_verify,
    )
    from hfm_crypto_cfd.post_upgrade_controller import (
        build_hfm_crypto_post_upgrade_controller,
        read_hfm_crypto_post_upgrade_controller,
    )
    from hfm_crypto_cfd.schema import (
        EA_SYMBOL_SPECS_FILE,
        FILLED_CONTRACT_SPEC_FILE,
        FILLED_SIMULATION_PROFILE_FILE,
        contract_spec_export_path,
        evidence_kit_path,
        execution_spec_review_path,
        filled_input_validator_path,
        filled_contract_spec_path,
        filled_simulation_profile_path,
        hfm_crypto_dir,
        mt5_exporter_review_path,
        mt5_exporter_upgrade_bundle_path,
        mt5_post_upgrade_verify_path,
        post_upgrade_controller_path,
        simulation_profile_review_path,
    )
    from hfm_crypto_cfd.simulation_profile import (
        build_hfm_crypto_simulation_profile_review,
        read_hfm_crypto_simulation_profile_review,
    )

MT5_SYMBOL_REGISTRY_CRYPTO_FILE = "mt5_symbol_registry_crypto.json"


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def _path_status(path: Path | str, *, input_id: str, label_zh: str, required: bool, reason_zh: str) -> dict[str, Any]:
    candidate = Path(path).expanduser()
    exists = candidate.exists() and candidate.is_file()
    size = None
    mtime = None
    if exists:
        try:
            stat = candidate.stat()
            size = stat.st_size
            mtime = int(stat.st_mtime)
        except OSError:
            pass
    return {
        "id": input_id,
        "labelZh": label_zh,
        "path": str(candidate),
        "required": required,
        "exists": exists,
        "status": "PRESENT" if exists else ("MISSING" if required else "OPTIONAL"),
        "sizeBytes": size,
        "mtimeEpochSeconds": mtime,
        "reasonZh": reason_zh,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _first_failed(checklist: list[dict[str, Any]], fallback: str) -> str:
    for item in checklist:
        if not bool(item.get("passed")):
            return str(item.get("reasonZh") or fallback)
    return fallback


def _check(check_id: str, label_zh: str, passed: bool, reason_zh: str, evidence: Any = None) -> dict[str, Any]:
    row = {
        "id": check_id,
        "labelZh": label_zh,
        "passed": bool(passed),
        "status": "PASS" if passed else "MISSING",
        "reasonZh": reason_zh,
    }
    if evidence not in (None, "", []):
        row["evidence"] = evidence
    return row


def _check_blocker_code(item: dict[str, Any]) -> str:
    check_id = str(item.get("id") or "evidence")
    reason = str(item.get("reasonZh") or "")
    if check_id in {"runtime_preflight", "order_request_contract"} and (
        "执行模式闸门" in reason or "数据面已通过" in reason
    ):
        return "EXECUTION_MODE_GATES_NOT_ACTIVE"
    return f"{check_id.upper()}_MISSING"


def _pipeline_check_map(pipeline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in _safe_list(pipeline.get("evidenceChecklist")):
        if isinstance(item, dict) and item.get("id"):
            rows[str(item["id"])] = item
    return rows


def _expected_input_files(runtime_dir: Path, operator_approval_json: str) -> list[dict[str, Any]]:
    base = hfm_crypto_dir(runtime_dir)
    rows = [
        _path_status(
            evidence_kit_path(runtime_dir),
            input_id="hfm_evidence_kit",
            label_zh="HFM evidence kit",
            required=False,
            reason_zh="本地采集模板和只读命令包。",
        ),
        _path_status(
            base / EA_SYMBOL_SPECS_FILE,
            input_id="ea_symbol_specs",
            label_zh="EA 导出的 HFM crypto symbol specs",
            required=False,
            reason_zh="macOS/Python MT5 bridge 不可用时，EA 用只读 SymbolInfo 字段导出 broker 规格；也可由 dashboard.hfmCryptoSymbolSpecs 提供。",
        ),
        _path_status(
            mt5_exporter_review_path(runtime_dir),
            input_id="mt5_exporter_review",
            label_zh="MT5 EA crypto exporter review",
            required=False,
            reason_zh="确认当前 MT5 安装目录 EA 是否能导出 HFM crypto symbol specs。",
        ),
        _path_status(
            mt5_exporter_upgrade_bundle_path(runtime_dir),
            input_id="mt5_upgrade_bundle",
            label_zh="MT5 EA exporter upgrade bundle",
            required=False,
            reason_zh="把新版 EA exporter 暂存到 runtime，供人工复制/编译；不会自动修改 MT5。",
        ),
        _path_status(
            mt5_post_upgrade_verify_path(runtime_dir),
            input_id="mt5_post_upgrade_verify",
            label_zh="MT5 EA post-upgrade verify",
            required=False,
            reason_zh="人工升级后复核 installed EA、compiled ex5、dashboard specs，并推进 contract-spec 审查。",
        ),
        _path_status(
            post_upgrade_controller_path(runtime_dir),
            input_id="post_upgrade_controller",
            label_zh="HFM post-upgrade controller",
            required=False,
            reason_zh="把 EA 升级包、升级后复核、contract-spec export 和 execution-spec review 串成一键只读控制器。",
        ),
        _path_status(
            base / MT5_SYMBOL_REGISTRY_CRYPTO_FILE,
            input_id="mt5_symbol_registry_crypto",
            label_zh="MT5 symbol registry crypto export",
            required=False,
            reason_zh="Python MT5 bridge 可用时的只读 symbol registry 导出。",
        ),
        _path_status(
            base / FILLED_CONTRACT_SPEC_FILE,
            input_id="filled_contract_spec",
            label_zh="人工补齐的 HFM contract spec",
            required=False,
            reason_zh="至少包含 contractSize、tickSize、tickValue、minLot、lotStep、maxLot。",
        ),
        _path_status(
            contract_spec_export_path(runtime_dir),
            input_id="contract_spec_export",
            label_zh="HFM contract spec export",
            required=False,
            reason_zh="由 EA specs 或 MT5 registry 转成的审查输入。",
        ),
        _path_status(
            execution_spec_review_path(runtime_dir),
            input_id="execution_spec_review",
            label_zh="HFM execution spec review",
            required=False,
            reason_zh="合约规格审查 artifact。",
        ),
        _path_status(
            base / FILLED_SIMULATION_PROFILE_FILE,
            input_id="filled_simulation_profile",
            label_zh="HFM/Moss simulation profile",
            required=False,
            reason_zh="包含 ROI、Sharpe、最大回撤、交易笔数和爆仓次数。",
        ),
        _path_status(
            filled_input_validator_path(runtime_dir),
            input_id="filled_input_validator",
            label_zh="HFM filled input validator",
            required=False,
            reason_zh="独立校验人工 filled contract spec/profile 是否可进入实盘评审链。",
        ),
        _path_status(
            simulation_profile_review_path(runtime_dir),
            input_id="simulation_profile_review",
            label_zh="HFM simulation profile review",
            required=False,
            reason_zh="模拟表现审查 artifact。",
        ),
        _path_status(
            adapter_contract_validator_path(runtime_dir),
            input_id="adapter_contract_validator",
            label_zh="Adapter contract validator",
            required=False,
            reason_zh="验证未来 MT5 adapter request JSON 与 request/receipt contract，仍只生成 review-only receipt。",
        ),
    ]
    if operator_approval_json:
        rows.append(_path_status(
            operator_approval_json,
            input_id="operator_approval_json",
            label_zh="Operator approval JSON",
            required=False,
            reason_zh="人工审批证据；即使验收也不会自动解锁执行。",
        ))
    return rows


def _artifact_summary(payload: dict[str, Any], extra_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    keys = (
        "schema",
        "status",
        "statusZh",
        "generatedAt",
        "generatedAtIso",
        "nextRequiredActionZh",
        *extra_keys,
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _input_paths(
    runtime_dir: Path,
    *,
    moss_backtest_json: str,
    hfm_simulation_profile_json: str,
    hfm_contract_spec_json: str,
) -> dict[str, str]:
    base = hfm_crypto_dir(runtime_dir)
    filled_contract = filled_contract_spec_path(runtime_dir)
    filled_sim = filled_simulation_profile_path(runtime_dir)
    export_path = contract_spec_export_path(runtime_dir)
    effective_sim = hfm_simulation_profile_json or moss_backtest_json or (str(filled_sim) if filled_sim.exists() else "")
    effective_sim_source = (
        "explicit_hfm_simulation_profile_json"
        if hfm_simulation_profile_json
        else "explicit_moss_backtest_json"
        if moss_backtest_json
        else "filled_simulation_profile"
        if filled_sim.exists()
        else ""
    )
    effective_contract = hfm_contract_spec_json or (str(filled_contract) if filled_contract.exists() else "") or (str(export_path) if export_path.exists() else "")
    effective_contract_source = (
        "explicit_hfm_contract_spec_json"
        if hfm_contract_spec_json
        else "filled_contract_spec"
        if filled_contract.exists()
        else "contract_spec_export"
        if export_path.exists()
        else ""
    )
    return {
        "effectiveSimulationProfileJson": effective_sim,
        "effectiveSimulationProfileSource": effective_sim_source,
        "effectiveContractSpecJson": effective_contract,
        "effectiveContractSpecSource": effective_contract_source,
        "expectedFilledContractSpecJson": str(filled_contract),
        "expectedFilledSimulationProfileJson": str(filled_sim),
        "expectedEaSymbolSpecsJson": str(base / EA_SYMBOL_SPECS_FILE),
        "expectedMt5RegistryCryptoJson": str(base / MT5_SYMBOL_REGISTRY_CRYPTO_FILE),
    }


def _review_commands(paths: dict[str, str]) -> list[dict[str, Any]]:
    contract_path = paths["effectiveContractSpecJson"] or "runtime/hfm_crypto/QuantGod_HFMCryptoContractSpecExport.json"
    simulation_path = paths["effectiveSimulationProfileJson"] or "runtime/hfm_crypto/hfm_crypto_simulation_profile.filled.json"
    return [
        {
            "id": "build_hfm_evidence_kit",
            "whenZh": "先生成模板和采集说明。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime evidence-kit --write",
        },
        {
            "id": "export_hfm_contract_specs",
            "whenZh": "EA specs 或 MT5 registry 文件出现后，转换成合约规格审查输入。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime contract-spec-export --write",
        },
        {
            "id": "review_mt5_ea_exporter",
            "whenZh": "如果 dashboard 没有 hfmCryptoSymbolSpecs，先确认 MT5 安装目录 EA 是否需要升级。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime mt5-exporter-review --write",
        },
        {
            "id": "build_mt5_ea_upgrade_bundle",
            "whenZh": "如果安装目录 EA 版本偏旧，生成人工升级包。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime mt5-upgrade-bundle --write",
        },
        {
            "id": "verify_mt5_ea_post_upgrade",
            "whenZh": "人工升级/编译/重载 EA 后，确认 specs 是否已输出，并自动推进 contract-spec 审查。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime mt5-post-upgrade-verify --write",
        },
        {
            "id": "run_hfm_post_upgrade_controller",
            "whenZh": "人工升级后反复跑这一条，它会自动刷新 exporter、bundle、post-upgrade verify、contract-spec 和 execution-spec。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime post-upgrade-controller --write",
        },
        {
            "id": "validate_filled_hfm_inputs",
            "whenZh": "如果使用人工 filled JSON，先独立确认 specs/profile 字段和模拟门槛都通过。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime filled-input-validator --write",
        },
        {
            "id": "review_hfm_contract_specs",
            "whenZh": "合约规格 JSON/CSV 已存在后，审查 tick/lot/contractSize。",
            "command": f"python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime execution-spec --write --contract-spec-json {contract_path}",
        },
        {
            "id": "review_hfm_simulation_profile",
            "whenZh": "Moss/HFM 模拟 profile 已存在后，审查 ROI/Sharpe/回撤/交易数/爆仓数。",
            "command": f"python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime simulation-profile --write --simulation-profile-json {simulation_path}",
        },
        {
            "id": "refresh_sim_to_live_pipeline",
            "whenZh": "HFM symbol、合约规格、模拟 profile 都补齐后，刷新完整 sim-to-live 审查链。",
            "command": (
                "python3 tools/run_live_automation_readiness.py --runtime-dir runtime pipeline --write --refresh-sources "
                f"--hfm-contract-spec-json {contract_path} --hfm-simulation-profile-json {simulation_path}"
            ),
        },
        {
            "id": "refresh_evidence_intake",
            "whenZh": "每次补证据后刷新本面板。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
        },
        {
            "id": "validate_adapter_contract",
            "whenZh": "request contract 和 adapter sandbox 通过后，离线验证 future adapter request/receipt 合同。",
            "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime adapter-contract-validator --write --refresh-sources",
        },
    ]


def build_live_evidence_intake(
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
    paths = _input_paths(
        runtime_dir,
        moss_backtest_json=moss_backtest_json,
        hfm_simulation_profile_json=hfm_simulation_profile_json,
        hfm_contract_spec_json=hfm_contract_spec_json,
    )
    profile_path = paths["effectiveSimulationProfileJson"]
    contract_path = paths["effectiveContractSpecJson"]
    evidence_kit = (
        build_hfm_crypto_evidence_kit(runtime_dir, write=write)
        if write or refresh_sources
        else read_hfm_crypto_evidence_kit(runtime_dir)
    )
    contract_export = (
        build_hfm_crypto_contract_spec_export(runtime_dir, write=write)
        if write or refresh_sources
        else read_hfm_crypto_contract_spec_export(runtime_dir)
    )
    mt5_exporter_review = (
        build_hfm_crypto_mt5_exporter_review(runtime_dir, write=write)
        if write or refresh_sources
        else read_hfm_crypto_mt5_exporter_review(runtime_dir)
    )
    mt5_upgrade_bundle = (
        build_hfm_crypto_mt5_upgrade_bundle(runtime_dir, write=write)
        if write or refresh_sources
        else read_hfm_crypto_mt5_upgrade_bundle(runtime_dir)
    )
    mt5_post_upgrade_verify = (
        build_hfm_crypto_mt5_post_upgrade_verify(runtime_dir, write=write)
        if write or refresh_sources
        else read_hfm_crypto_mt5_post_upgrade_verify(runtime_dir)
    )
    post_upgrade_controller = (
        build_hfm_crypto_post_upgrade_controller(runtime_dir, write=write)
        if write or refresh_sources
        else read_hfm_crypto_post_upgrade_controller(runtime_dir)
    )
    filled_input_validator = (
        build_hfm_crypto_filled_input_validator(runtime_dir, write=write)
        if write or refresh_sources
        else read_hfm_crypto_filled_input_validator(runtime_dir)
    )
    if (not contract_path or paths.get("effectiveContractSpecSource") == "contract_spec_export") and contract_export.get("readyForContractSpecReviewInput"):
        contract_path = str(contract_spec_export_path(runtime_dir))
        paths["effectiveContractSpecJson"] = contract_path
        paths["effectiveContractSpecSource"] = "contract_spec_export"
    execution_spec = (
        build_hfm_crypto_execution_spec_review(runtime_dir, contract_spec_json=contract_path, write=write)
        if contract_path or write or refresh_sources
        else read_hfm_crypto_execution_spec_review(runtime_dir)
    )
    simulation_profile = (
        build_hfm_crypto_simulation_profile_review(runtime_dir, simulation_profile_json=profile_path, write=write)
        if profile_path or write or refresh_sources
        else read_hfm_crypto_simulation_profile_review(runtime_dir)
    )
    hfm_state = (
        build_hfm_crypto_cfd_state(
            runtime_dir,
            moss_backtest_json=moss_backtest_json,
            simulation_profile_json=hfm_simulation_profile_json,
            contract_spec_json=contract_path,
            extra_bases_roots=extra_roots,
            write=write,
        )
        if write or refresh_sources or profile_path or contract_path or extra_roots
        else read_hfm_crypto_cfd_state(runtime_dir)
    )
    pipeline_kwargs = {
        "operator_approval_json": operator_approval_json,
        "write": write,
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": profile_path,
        "hfm_contract_spec_json": contract_path,
        "extra_bases_roots": extra_roots,
    }
    should_rebuild_pipeline = bool(write or refresh_sources or operator_approval_json or profile_path or contract_path or extra_roots)
    pipeline = (
        build_sim_to_live_automation_pipeline(runtime_dir, **pipeline_kwargs)
        if should_rebuild_pipeline
        else read_sim_to_live_automation_pipeline(runtime_dir)
    )
    preflight = (
        build_live_runtime_preflight_probe(runtime_dir, **pipeline_kwargs)
        if should_rebuild_pipeline
        else read_live_runtime_preflight_probe(runtime_dir)
    )
    adapter_review = (
        build_execution_adapter_review(runtime_dir, **pipeline_kwargs)
        if should_rebuild_pipeline
        else read_execution_adapter_review(runtime_dir)
    )
    adapter_validator = (
        build_adapter_contract_validator(runtime_dir, **pipeline_kwargs)
        if should_rebuild_pipeline
        else read_adapter_contract_validator(runtime_dir)
    )
    file_inputs = _expected_input_files(runtime_dir, operator_approval_json)
    file_by_id = {row["id"]: row for row in file_inputs}
    pipeline_checks = _pipeline_check_map(pipeline)
    hfm_local = _safe_dict(hfm_state.get("localEvidence"))
    hfm_symbol_evidence = _safe_dict(hfm_state.get("symbolEvidence"))
    filled_validator_artifacts = _safe_dict(filled_input_validator.get("artifacts"))
    filled_validator_execution_spec = _safe_dict(filled_validator_artifacts.get("executionSpec"))
    filled_validator_simulation_profile = _safe_dict(filled_validator_artifacts.get("simulationProfile"))
    symbol_evidence_passed = bool(
        hfm_symbol_evidence.get("found")
        or hfm_local.get("found")
        or execution_spec.get("readyForExecutionSpecReview")
        or filled_validator_execution_spec.get("readyForExecutionSpecReview")
        or contract_export.get("readyForContractSpecReviewInput")
        or mt5_exporter_review.get("exporterReadyForEvidenceIntake")
        or mt5_post_upgrade_verify.get("postUpgradeVerified")
        or post_upgrade_controller.get("postUpgradeReviewAutomated")
        or file_by_id.get("ea_symbol_specs", {}).get("exists")
        or file_by_id.get("mt5_symbol_registry_crypto", {}).get("exists")
    )
    contract_evidence_passed = bool(
        execution_spec.get("readyForExecutionSpecReview")
        or filled_validator_execution_spec.get("readyForExecutionSpecReview")
        or mt5_post_upgrade_verify.get("executionSpecReviewReady")
        or post_upgrade_controller.get("executionSpecReviewReady")
        or contract_export.get("readyForContractSpecReviewInput")
    )
    simulation_evidence_passed = bool(
        simulation_profile.get("simulationQualified")
        or filled_validator_simulation_profile.get("simulationQualified")
    )
    checklist = [
        _check(
            "hfm_crypto_symbol_evidence",
            "HFM crypto broker symbol 证据",
            symbol_evidence_passed,
            "需要 HFM MT5 Bases 里的 crypto history/tick，或 EA/MT5 registry 只读导出的 broker symbol specs。",
            hfm_symbol_evidence.get("brokerSymbols") or hfm_local.get("brokerSymbols") or contract_export.get("coveredBrokerSymbols"),
        ),
        _check(
            "hfm_crypto_contract_spec",
            "HFM crypto 合约规格",
            contract_evidence_passed,
            "需要 contractSize、tickSize、tickValue、minLot、lotStep、maxLot 等 broker 规格。",
            execution_spec.get("coveredBrokerSymbols") or contract_export.get("coveredBrokerSymbols"),
        ),
        _check(
            "hfm_crypto_simulation_profile",
            "HFM/Moss 模拟表现",
            simulation_evidence_passed,
            "需要 ROI、Sharpe、最大回撤、交易笔数和爆仓次数字段。",
            _safe_dict(simulation_profile.get("metrics")).get("agentId"),
        ),
    ]
    for check_id in (
        "review_candidate_lane",
        "operator_approval_evidence",
        "dry_run_replay",
        "runtime_preflight",
        "order_request_contract",
    ):
        item = pipeline_checks.get(check_id)
        if item:
            checklist.append(dict(item))
    blockers = []
    for item in checklist:
        if not bool(item.get("passed")):
            blockers.append(_blocker(_check_blocker_code(item), item.get("reasonZh", "缺少证据。")))
    present_count = sum(1 for row in file_inputs if row.get("exists"))
    missing_required_count = sum(1 for row in file_inputs if row.get("required") and not row.get("exists"))
    missing_check_count = sum(1 for row in checklist if not row.get("passed"))
    hfm_inputs_present = symbol_evidence_passed and contract_evidence_passed and simulation_evidence_passed
    status = "HFM_REVIEW_INPUTS_PRESENT" if hfm_inputs_present else "WAITING_HFM_LIVE_EVIDENCE_INPUTS"
    dashboard_snapshot = _safe_dict(preflight.get("dashboardSnapshot"))
    probe_results = _safe_dict(preflight.get("probeResults"))
    lane_runtime_checks = _safe_list(preflight.get("laneRuntimeChecks"))
    permission_layers = _safe_dict(dashboard_snapshot.get("permissionLayers"))
    trade_permission_blocker = str(
        permission_layers.get("tradePermissionBlocker")
        or dashboard_snapshot.get("tradePermissionBlocker")
        or ""
    )
    target_symbols = [
        str(row.get("brokerSymbol") or row.get("canonicalSymbol"))
        for row in lane_runtime_checks
        if isinstance(row, dict) and (row.get("brokerSymbol") or row.get("canonicalSymbol"))
    ]
    summary_zh = (
        f"dashboardFresh={dashboard_snapshot.get('fresh')} ageSeconds={dashboard_snapshot.get('ageSeconds')} "
        f"tradeStatus={dashboard_snapshot.get('tradeStatus')} livePilotMode={dashboard_snapshot.get('livePilotMode')} "
        f"readOnlyMode={dashboard_snapshot.get('readOnlyMode')} executionEnabled={dashboard_snapshot.get('executionEnabled')} "
        f"tradeAllowed={dashboard_snapshot.get('tradeAllowed')} "
        f"tradePermissionBlocker={trade_permission_blocker or 'NONE'} "
        f"targetSymbols={','.join(target_symbols) if target_symbols else 'NONE'}。"
    )
    payload = {
        "ok": True,
        "schema": LIVE_EVIDENCE_INTAKE_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": "HFM crypto 主要审查输入已出现" if hfm_inputs_present else "等待 HFM crypto 实盘前证据输入",
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
        "externalMarketRemoved": True,
        "dashboardSnapshot": dashboard_snapshot,
        "probeResults": probe_results,
        "laneRuntimeChecks": lane_runtime_checks,
        "dashboardFresh": dashboard_snapshot.get("fresh"),
        "dashboardAgeSeconds": dashboard_snapshot.get("ageSeconds"),
        "tradeStatus": dashboard_snapshot.get("tradeStatus"),
        "livePilotMode": dashboard_snapshot.get("livePilotMode"),
        "readOnlyMode": dashboard_snapshot.get("readOnlyMode"),
        "executionEnabled": dashboard_snapshot.get("executionEnabled"),
        "tradeAllowed": dashboard_snapshot.get("tradeAllowed"),
        "tradePermissionBlocker": trade_permission_blocker,
        "targetSymbols": target_symbols,
        "summaryZh": summary_zh,
        "inputs": {
            "mossBacktestJson": moss_backtest_json,
            "hfmSimulationProfileJson": hfm_simulation_profile_json,
            "hfmContractSpecJson": hfm_contract_spec_json,
            "effectiveSimulationProfileJson": profile_path,
            "effectiveSimulationProfileSource": paths.get("effectiveSimulationProfileSource", ""),
            "effectiveContractSpecJson": contract_path,
            "effectiveContractSpecSource": paths.get("effectiveContractSpecSource", ""),
            "operatorApprovalJsonProvided": bool(operator_approval_json),
            "extraBasesRootCount": len(extra_roots),
        },
        "fileInputs": file_inputs,
        "fileInputSummary": {
            "presentInputCount": present_count,
            "missingRequiredInputCount": missing_required_count,
            "missingChecklistCount": missing_check_count,
        },
        "intakeChecklist": checklist,
        "artifacts": {
            "hfmState": _artifact_summary(hfm_state),
            "evidenceKit": _artifact_summary(evidence_kit),
            "mt5ExporterReview": _artifact_summary(mt5_exporter_review, ("exporterReadyForEvidenceIntake", "mt5EaUpgradeRequired")),
            "mt5UpgradeBundle": _artifact_summary(mt5_upgrade_bundle, ("bundleReadyForManualUpgrade", "bundleWritten")),
            "mt5PostUpgradeVerify": _artifact_summary(mt5_post_upgrade_verify, ("postUpgradeVerified", "readyForContractSpecReview", "executionSpecReviewReady")),
            "postUpgradeController": _artifact_summary(post_upgrade_controller, ("postUpgradeReviewAutomated", "readyForHfmContractSpecReview", "executionSpecReviewReady")),
            "filledInputValidator": _artifact_summary(filled_input_validator, ("filledInputsValid", "readyForEvidenceIntakeRefresh")),
            "contractSpecExport": _artifact_summary(contract_export, ("readyForContractSpecReviewInput", "validRowCount")),
            "executionSpec": _artifact_summary(execution_spec, ("readyForExecutionSpecReview", "validRowCount")),
            "simulationProfile": _artifact_summary(simulation_profile, ("simulationQualified",)),
            "pipeline": _artifact_summary(pipeline, ("autoStage", "readyForSeparateExecutionAdapterReview")),
            "runtimePreflight": _artifact_summary(preflight, ("runtimeProbePassed",)),
            "adapterReview": _artifact_summary(adapter_review, ("readyForExecutionAdapterCodeReview",)),
            "adapterContractValidator": _artifact_summary(adapter_validator, ("validationPassed", "requestCount", "receiptCount")),
        },
        "mt5DashboardSummary": dashboard_snapshot,
        "readOnlyReviewCommands": _review_commands(paths),
        "blockers": blockers,
        "nextRequiredActionZh": _first_failed(
            checklist,
            "证据齐了以后刷新 sim-to-live pipeline，然后再进入单独 execution adapter 代码评审。",
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
        payload = _read_json(path)
        if payload:
            return payload
    return build_live_evidence_intake(Path(runtime_dir), write=False)
