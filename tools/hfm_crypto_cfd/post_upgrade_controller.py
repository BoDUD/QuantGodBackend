from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .builder import build_hfm_crypto_cfd_state, read_hfm_crypto_cfd_state
from .contract_spec_export import build_hfm_crypto_contract_spec_export, read_hfm_crypto_contract_spec_export
from .execution_spec import build_hfm_crypto_execution_spec_review, read_hfm_crypto_execution_spec_review
from .mt5_exporter_review import build_hfm_crypto_mt5_exporter_review, read_hfm_crypto_mt5_exporter_review
from .mt5_post_upgrade_verify import (
    build_hfm_crypto_mt5_post_upgrade_verify,
    read_hfm_crypto_mt5_post_upgrade_verify,
)
from .mt5_upgrade_bundle import build_hfm_crypto_mt5_upgrade_bundle, read_hfm_crypto_mt5_upgrade_bundle
from .schema import (
    POST_UPGRADE_CONTROLLER_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    contract_spec_export_path,
    post_upgrade_controller_path,
    utc_now_iso,
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


def _artifact_summary(payload: dict[str, Any], extra_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    keys = (
        "schema",
        "status",
        "statusZh",
        "generatedAt",
        "nextRequiredActionZh",
        *extra_keys,
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _review_artifact_rows(artifacts: dict[str, dict[str, Any]], write: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact_id, payload in artifacts.items():
        rows.append({
            "artifactId": artifact_id,
            "schema": payload.get("schema", ""),
            "status": payload.get("status", ""),
            "statusZh": payload.get("statusZh", ""),
            "writtenByController": bool(write),
            "executionReady": False,
            "requestWritesAllowed": False,
            "requestFilesWritten": False,
            "brokerCallsMade": False,
            "adapterExecutionAllowed": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
        })
    return rows


def _read_only_review_commands(contract_path: str, specs_available: bool) -> list[dict[str, Any]]:
    contract = contract_path or "runtime/hfm_crypto/QuantGod_HFMCryptoContractSpecExport.json"
    commands = [
        {
            "id": "review_mt5_ea_exporter",
            "whenZh": "确认当前 MT5 安装目录 EA 是否包含 HFM crypto specs exporter。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime mt5-exporter-review --write",
        },
        {
            "id": "stage_manual_mt5_ea_upgrade_bundle",
            "whenZh": "如果安装目录 EA 偏旧，生成人工复制/编译用的 runtime 升级包。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime mt5-upgrade-bundle --write",
        },
        {
            "id": "run_post_upgrade_controller",
            "whenZh": "人工复制、MetaEditor 编译、EA 重新加载后，一键复核并刷新审查证据。",
            "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime post-upgrade-controller --write",
        },
    ]
    if specs_available:
        commands.extend([
            {
                "id": "refresh_contract_spec_export",
                "whenZh": "EA specs 或 dashboard.hfmCryptoSymbolSpecs 出现后，刷新合约规格导出。",
                "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime contract-spec-export --write",
            },
            {
                "id": "refresh_execution_spec_review",
                "whenZh": "合约规格导出可用后，刷新 tick/lot/contractSize 审查。",
                "command": (
                    "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime execution-spec --write "
                    f"--contract-spec-json {contract}"
                ),
            },
            {
                "id": "refresh_live_evidence_intake",
                "whenZh": "HFM 证据刷新后，更新 sim-to-live evidence intake。",
                "command": (
                    "python3 tools/run_live_automation_readiness.py --runtime-dir runtime "
                    "evidence-intake --write --refresh-sources"
                ),
            },
            {
                "id": "refresh_live_promotion_candidates",
                "whenZh": "模拟 profile 也补齐后，重新挑选可进入实盘评审的 lane。",
                "command": (
                    "python3 tools/run_live_automation_readiness.py --runtime-dir runtime "
                    "promotion-candidates --write --refresh-sources"
                ),
            },
            {
                "id": "refresh_live_promotion_controller",
                "whenZh": "存在候选 lane 时，仅自动生成本地 review artifact。",
                "command": (
                    "python3 tools/run_live_automation_readiness.py --runtime-dir runtime "
                    "promotion-controller --write --refresh-sources"
                ),
            },
        ])
    return commands


def _controller_status(
    post_verify: dict[str, Any],
    contract_export: dict[str, Any],
    execution_spec: dict[str, Any],
) -> tuple[str, str]:
    checks = _safe_dict(post_verify.get("checks"))
    if bool(post_verify.get("postUpgradeVerified")) and bool(execution_spec.get("readyForExecutionSpecReview")):
        return "HFM_CRYPTO_POST_UPGRADE_REVIEW_AUTOMATED", "HFM crypto 升级后审查已自动推进"
    if bool(contract_export.get("readyForContractSpecReviewInput")) or bool(post_verify.get("readyForContractSpecReview")):
        return "READY_FOR_HFM_CONTRACT_SPEC_REVIEW", "HFM crypto specs 已可进入合约规格审查"
    if bool(checks.get("installedSourceHasExporter")) and bool(checks.get("installedBinaryNotOlderThanSource")):
        return "WAITING_HFM_CRYPTO_SPECS_AFTER_UPGRADE", "等待升级后的 HFM crypto specs 输出"
    return "WAITING_MANUAL_MT5_EA_UPGRADE", "等待人工升级并编译 MT5 EA"


def build_hfm_crypto_post_upgrade_controller(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    exporter_review = (
        build_hfm_crypto_mt5_exporter_review(runtime_dir, write=write)
        if write
        else read_hfm_crypto_mt5_exporter_review(runtime_dir)
    )
    upgrade_bundle = (
        build_hfm_crypto_mt5_upgrade_bundle(runtime_dir, write=write)
        if write
        else read_hfm_crypto_mt5_upgrade_bundle(runtime_dir)
    )
    post_verify = (
        build_hfm_crypto_mt5_post_upgrade_verify(runtime_dir, write=write)
        if write
        else read_hfm_crypto_mt5_post_upgrade_verify(runtime_dir)
    )
    specs_available = bool(
        exporter_review.get("exporterReadyForEvidenceIntake")
        or _safe_dict(post_verify.get("checks")).get("hfmCryptoSpecsAvailable")
    )
    contract_export = (
        build_hfm_crypto_contract_spec_export(runtime_dir, write=write)
        if specs_available or write
        else read_hfm_crypto_contract_spec_export(runtime_dir)
    )
    contract_path = (
        str(contract_spec_export_path(runtime_dir))
        if contract_export.get("readyForContractSpecReviewInput")
        else ""
    )
    execution_spec = (
        build_hfm_crypto_execution_spec_review(runtime_dir, contract_spec_json=contract_path, write=write)
        if contract_path
        else read_hfm_crypto_execution_spec_review(runtime_dir)
    )
    hfm_state = (
        build_hfm_crypto_cfd_state(runtime_dir, contract_spec_json=contract_path, write=write)
        if write or contract_path
        else read_hfm_crypto_cfd_state(runtime_dir)
    )
    status, status_zh = _controller_status(post_verify, contract_export, execution_spec)
    blockers = [
        item
        for source in (
            _safe_list(exporter_review.get("blockers")),
            _safe_list(upgrade_bundle.get("blockers")),
            _safe_list(post_verify.get("blockers")),
            _safe_list(contract_export.get("blockers")),
            _safe_list(execution_spec.get("blockers")),
        )
        for item in source
        if isinstance(item, dict)
    ]
    if status == "HFM_CRYPTO_POST_UPGRADE_REVIEW_AUTOMATED":
        blockers = [
            item for item in blockers
            if item.get("code") not in {
                "HFM_CRYPTO_SPECS_NOT_EXPORTED_YET",
                "HFM_CRYPTO_SPECS_NOT_EXPORTED_AFTER_UPGRADE",
                "HFM_MT5_SYMBOL_REGISTRY_EXPORT_MISSING",
                "HFM_CRYPTO_CONTRACT_SPEC_FILE_MISSING",
            }
        ]
    elif status == "WAITING_MANUAL_MT5_EA_UPGRADE" and not blockers:
        blockers.append(_blocker(
            "MANUAL_MT5_EA_UPGRADE_REQUIRED",
            "需要人工复制 runtime 升级包中的 EA 源码、用 MetaEditor 编译，并重新加载 EA。",
        ))
    artifacts = {
        "mt5ExporterReview": exporter_review,
        "mt5UpgradeBundle": upgrade_bundle,
        "mt5PostUpgradeVerify": post_verify,
        "contractSpecExport": contract_export,
        "executionSpec": execution_spec,
        "hfmCryptoState": hfm_state,
    }
    payload = {
        "ok": True,
        "schema": POST_UPGRADE_CONTROLLER_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "controllerMode": "MT5_EA_POST_UPGRADE_REVIEW_AUTOMATION_ONLY",
        "postUpgradeReviewAutomated": status == "HFM_CRYPTO_POST_UPGRADE_REVIEW_AUTOMATED",
        "readyForHfmContractSpecReview": bool(contract_export.get("readyForContractSpecReviewInput")),
        "executionSpecReviewReady": bool(execution_spec.get("readyForExecutionSpecReview")),
        "specsAvailable": specs_available,
        "reviewArtifactsWrittenByThisRun": bool(write),
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "brokerExecutionAllowed": False,
        "adapterExecutionAllowed": False,
        "hfmCryptoExecutionAllowed": False,
        "livePresetMutationAllowed": False,
        "installedFilesMutated": False,
        "compileAttempted": False,
        "copyIntoMt5Allowed": False,
        "controllerChecks": {
            "installedSourceHasExporter": bool(_safe_dict(post_verify.get("checks")).get("installedSourceHasExporter")),
            "sourceHashMatchesBundle": bool(_safe_dict(post_verify.get("checks")).get("sourceHashMatchesBundle")),
            "installedBinaryPresent": bool(_safe_dict(post_verify.get("checks")).get("installedBinaryPresent")),
            "installedBinaryNotOlderThanSource": bool(_safe_dict(post_verify.get("checks")).get("installedBinaryNotOlderThanSource")),
            "hfmCryptoSpecsAvailable": specs_available,
            "contractSpecExportReady": bool(contract_export.get("readyForContractSpecReviewInput")),
            "executionSpecReviewReady": bool(execution_spec.get("readyForExecutionSpecReview")),
        },
        "artifacts": {
            "mt5ExporterReview": _artifact_summary(exporter_review, ("exporterReadyForEvidenceIntake", "mt5EaUpgradeRequired")),
            "mt5UpgradeBundle": _artifact_summary(upgrade_bundle, ("bundleReadyForManualUpgrade", "bundleWritten")),
            "mt5PostUpgradeVerify": _artifact_summary(post_verify, ("postUpgradeVerified", "readyForContractSpecReview", "executionSpecReviewReady")),
            "contractSpecExport": _artifact_summary(contract_export, ("readyForContractSpecReviewInput", "validRowCount")),
            "executionSpec": _artifact_summary(execution_spec, ("readyForExecutionSpecReview", "validRowCount")),
            "hfmCryptoState": _artifact_summary(hfm_state),
        },
        "reviewArtifactRuns": _review_artifact_rows(artifacts, write),
        "paths": {
            "controllerJsonPath": str(post_upgrade_controller_path(runtime_dir)),
            "contractSpecJsonPath": contract_export.get("contractSpecJsonPath", ""),
            "stagedSourcePath": _safe_dict(upgrade_bundle.get("bundle")).get("stagedSourcePath", ""),
            "installedEaSourcePath": _safe_dict(post_verify.get("source")).get("installedEaSourcePath", ""),
            "installedBinaryPath": _safe_dict(post_verify.get("binary")).get("installedBinaryPath", ""),
        },
        "readOnlyReviewCommands": _read_only_review_commands(contract_path, specs_available),
        "blockers": blockers[:24],
        "nextRequiredActionZh": (
            "HFM crypto specs 和合约审查已自动刷新；继续补模拟 profile，然后运行 live evidence intake / promotion controller。"
            if status == "HFM_CRYPTO_POST_UPGRADE_REVIEW_AUTOMATED"
            else "人工升级/编译/重载 EA 后重新运行本 controller；它会在 specs 出现时自动刷新后续审查 artifact。"
            if status == "WAITING_MANUAL_MT5_EA_UPGRADE"
            else "保持 EA 运行并刷新 dashboard/specs；specs 出现后本 controller 会推进 contract-spec 审查。"
        ),
        "safety": {
            **SAFETY,
            "mutatesMt5": False,
            "installedFilesMutated": False,
            "compileAttempted": False,
            "copyIntoMt5Allowed": False,
            "brokerCallsMade": False,
            "symbolSelectAllowed": False,
            "requestWritesAllowed": False,
            "requestFilesWritten": False,
            "brokerExecutionAllowed": False,
            "hfmCryptoExecutionAllowed": False,
        },
    }
    assert_no_execution_flags(payload)
    if write:
        out = post_upgrade_controller_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_post_upgrade_controller(runtime_dir: Path) -> dict[str, Any]:
    path = post_upgrade_controller_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_hfm_crypto_post_upgrade_controller(Path(runtime_dir), write=False)
