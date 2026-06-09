from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contract_spec_export import build_hfm_crypto_contract_spec_export, read_hfm_crypto_contract_spec_export
from .execution_spec import build_hfm_crypto_execution_spec_review, read_hfm_crypto_execution_spec_review
from .mt5_exporter_review import build_hfm_crypto_mt5_exporter_review, read_hfm_crypto_mt5_exporter_review
from .mt5_upgrade_bundle import read_hfm_crypto_mt5_upgrade_bundle
from .schema import (
    MT5_POST_UPGRADE_VERIFY_SCHEMA_VERSION,
    SAFETY,
    contract_spec_export_path,
    mt5_post_upgrade_verify_path,
    utc_now_iso,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    return path if path.exists() and path.is_file() else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _mtime(path: Path | None) -> float | None:
    if not path:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def build_hfm_crypto_mt5_post_upgrade_verify(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    review = (
        build_hfm_crypto_mt5_exporter_review(runtime_dir, write=write)
        if write
        else read_hfm_crypto_mt5_exporter_review(runtime_dir)
    )
    bundle = read_hfm_crypto_mt5_upgrade_bundle(runtime_dir)
    installed_source = _safe_path(review.get("installedMt5Ea", {}).get("sourcePath"))
    installed_binary = _safe_path(review.get("installedMt5Ea", {}).get("binaryPath"))
    staged_source = _safe_path(bundle.get("bundle", {}).get("stagedSourcePath"))
    installed_hash = _sha256(installed_source) if installed_source else ""
    staged_hash = _sha256(staged_source) if staged_source else str(bundle.get("bundle", {}).get("stagedSourceSha256") or "")
    source_hash_matches_bundle = bool(installed_hash and staged_hash and installed_hash == staged_hash)
    source_has_exporter = bool(review.get("installedMt5Ea", {}).get("sourceHasExporter"))
    binary_mtime = _mtime(installed_binary)
    source_mtime = _mtime(installed_source)
    binary_present = bool(installed_binary)
    binary_not_older_than_source = bool(
        binary_present
        and binary_mtime is not None
        and source_mtime is not None
        and binary_mtime >= source_mtime
    )
    specs_available = bool(review.get("exporterReadyForEvidenceIntake"))
    contract_export = (
        build_hfm_crypto_contract_spec_export(runtime_dir, write=write)
        if specs_available or write
        else read_hfm_crypto_contract_spec_export(runtime_dir)
    )
    contract_path = str(contract_spec_export_path(runtime_dir)) if contract_export.get("readyForContractSpecReviewInput") else ""
    execution_spec = (
        build_hfm_crypto_execution_spec_review(runtime_dir, contract_spec_json=contract_path, write=write)
        if contract_path
        else read_hfm_crypto_execution_spec_review(runtime_dir)
    )

    blockers: list[dict[str, Any]] = []
    if not source_has_exporter:
        blockers.append(_blocker("INSTALLED_SOURCE_NOT_UPGRADED", "安装目录 EA 源码仍未包含 HFM crypto exporter。", review.get("installedMt5Ea", {}).get("sourcePath")))
    if staged_hash and not source_hash_matches_bundle:
        blockers.append(_blocker("INSTALLED_SOURCE_HASH_DIFFERS_FROM_BUNDLE", "安装目录 EA 源码 hash 还没有匹配 runtime 升级包。"))
    if not binary_present:
        blockers.append(_blocker("INSTALLED_BINARY_MISSING", "安装目录没有找到 QuantGod_MultiStrategy.ex5，尚不能确认已编译。"))
    elif source_has_exporter and not binary_not_older_than_source:
        blockers.append(_blocker("INSTALLED_BINARY_OLDER_THAN_SOURCE", "EA .ex5 早于源码，可能还没用 MetaEditor 重新编译。"))
    if source_has_exporter and binary_not_older_than_source and not specs_available:
        blockers.append(_blocker("HFM_CRYPTO_SPECS_NOT_EXPORTED_AFTER_UPGRADE", "EA 可能已升级/编译，但 dashboard 或 specs 文件尚未出现 HFM crypto symbol specs。"))
    if specs_available and not contract_export.get("readyForContractSpecReviewInput"):
        blockers.append(_blocker("CONTRACT_SPEC_EXPORT_NOT_READY", "已发现 specs 入口，但 contract-spec export 还没有有效 crypto 行。", contract_export.get("status")))

    if contract_export.get("readyForContractSpecReviewInput") and execution_spec.get("readyForExecutionSpecReview"):
        status = "HFM_CRYPTO_MT5_POST_UPGRADE_VERIFIED"
        status_zh = "HFM crypto MT5 升级后证据已通过"
    elif specs_available:
        status = "WAITING_CONTRACT_SPEC_REVIEW_AFTER_UPGRADE"
        status_zh = "等待升级后的合约规格审查"
    elif source_has_exporter and binary_not_older_than_source:
        status = "WAITING_HFM_CRYPTO_SPECS_AFTER_UPGRADE"
        status_zh = "等待升级后的 HFM crypto specs 输出"
    else:
        status = "WAITING_MANUAL_MT5_EA_UPGRADE"
        status_zh = "等待人工升级并编译 MT5 EA"

    payload = {
        "ok": True,
        "schema": MT5_POST_UPGRADE_VERIFY_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "postUpgradeVerified": status == "HFM_CRYPTO_MT5_POST_UPGRADE_VERIFIED",
        "readyForContractSpecReview": bool(contract_export.get("readyForContractSpecReviewInput")),
        "executionSpecReviewReady": bool(execution_spec.get("readyForExecutionSpecReview")),
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "installedFilesMutated": False,
        "compileAttempted": False,
        "brokerCallsMade": False,
        "checks": {
            "installedSourceHasExporter": source_has_exporter,
            "sourceHashMatchesBundle": source_hash_matches_bundle,
            "installedBinaryPresent": binary_present,
            "installedBinaryNotOlderThanSource": binary_not_older_than_source,
            "hfmCryptoSpecsAvailable": specs_available,
            "contractSpecExportReady": bool(contract_export.get("readyForContractSpecReviewInput")),
            "executionSpecReviewReady": bool(execution_spec.get("readyForExecutionSpecReview")),
        },
        "source": {
            "installedEaSourcePath": str(installed_source) if installed_source else str(review.get("installedMt5Ea", {}).get("sourcePath") or ""),
            "installedEaSha256": installed_hash,
            "stagedSourcePath": str(staged_source) if staged_source else str(bundle.get("bundle", {}).get("stagedSourcePath") or ""),
            "stagedSourceSha256": staged_hash,
        },
        "binary": {
            "installedBinaryPath": str(installed_binary) if installed_binary else str(review.get("installedMt5Ea", {}).get("binaryPath") or ""),
            "installedBinaryMtime": binary_mtime,
            "installedSourceMtime": source_mtime,
        },
        "dashboard": review.get("dashboard", {}),
        "contractSpecExport": {
            "status": contract_export.get("status", ""),
            "readyForContractSpecReviewInput": bool(contract_export.get("readyForContractSpecReviewInput")),
            "validRowCount": contract_export.get("validRowCount", 0),
            "contractSpecJsonPath": contract_export.get("contractSpecJsonPath", ""),
            "coveredBrokerSymbols": contract_export.get("coveredBrokerSymbols", []),
        },
        "executionSpec": {
            "status": execution_spec.get("status", ""),
            "readyForExecutionSpecReview": bool(execution_spec.get("readyForExecutionSpecReview")),
            "validRowCount": execution_spec.get("validRowCount", 0),
            "coveredBrokerSymbols": execution_spec.get("coveredBrokerSymbols", []),
        },
        "blockers": blockers,
        "nextRequiredActionZh": (
            "HFM crypto specs 已完成升级后验证；继续导入模拟 profile 并刷新 sim-to-live pipeline。"
            if status == "HFM_CRYPTO_MT5_POST_UPGRADE_VERIFIED"
            else "先完成 EA 源码替换、MetaEditor 编译、EA 重新加载，并等待 hfmCryptoSymbolSpecs 出现。"
        ),
        "safety": {
            **SAFETY,
            "mutatesMt5": False,
            "installedFilesMutated": False,
            "compileAttempted": False,
            "brokerCallsMade": False,
            "symbolSelectAllowed": False,
        },
    }
    if write:
        out = mt5_post_upgrade_verify_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_mt5_post_upgrade_verify(runtime_dir: Path) -> dict[str, Any]:
    path = mt5_post_upgrade_verify_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        payload = _read_json(path)
        if payload:
            return payload
    return build_hfm_crypto_mt5_post_upgrade_verify(Path(runtime_dir), write=False)
