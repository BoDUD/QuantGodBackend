from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .mt5_exporter_review import SOURCE_FILE, build_hfm_crypto_mt5_exporter_review, read_hfm_crypto_mt5_exporter_review
from .schema import (
    MT5_EXPORTER_UPGRADE_BUNDLE_SCHEMA_VERSION,
    SAFETY,
    mt5_exporter_upgrade_bundle_dir,
    mt5_exporter_upgrade_bundle_path,
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


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def _script_text(target_path: str, source_file_name: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            'echo "Manual MT5 EA upgrade helper"',
            'echo "1. Close or detach the running QuantGod EA in MT5."',
            f'echo "2. Copy {source_file_name} to: {target_path}"',
            'echo "3. Compile it in MetaEditor and reload the EA on the chart."',
            'echo "4. Confirm EnableHfmCryptoSpecExporter=true, then refresh mt5-exporter-review."',
            'echo "This helper is intentionally print-only. It does not copy, compile, change presets, or trade."',
            "",
        ]
    )


def build_hfm_crypto_mt5_upgrade_bundle(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    review = (
        build_hfm_crypto_mt5_exporter_review(runtime_dir, write=write)
        if write
        else read_hfm_crypto_mt5_exporter_review(runtime_dir)
    )
    repo_source = _safe_path(review.get("repoEaSource", {}).get("path"))
    installed_source = _safe_path(review.get("installedMt5Ea", {}).get("sourcePath"))
    upgrade_required = bool(review.get("mt5EaUpgradeRequired"))
    repo_ready = bool(review.get("repoEaSource", {}).get("hasExporter")) and repo_source is not None
    bundle_dir = mt5_exporter_upgrade_bundle_dir(runtime_dir)
    staged_source = bundle_dir / SOURCE_FILE
    helper_script = bundle_dir / "manual_upgrade_instructions.sh"
    manifest_path = mt5_exporter_upgrade_bundle_path(runtime_dir)
    blockers: list[dict[str, Any]] = []
    if not repo_ready:
        blockers.append(_blocker("REPO_EA_EXPORTER_NOT_READY", "仓库 EA 尚未包含可打包的 HFM crypto exporter。", review.get("repoEaSource", {}).get("path")))
    if not installed_source:
        blockers.append(_blocker("INSTALLED_MT5_EA_SOURCE_MISSING", "没有找到当前 MT5 安装目录里的 EA 源码，无法生成明确的目标路径。"))
    if review.get("exporterReadyForEvidenceIntake"):
        blockers.append(_blocker("MT5_EXPORTER_ALREADY_AVAILABLE", "当前 MT5 已经能提供 HFM crypto specs，通常不需要升级包。"))

    bundle_ready = bool(repo_ready and installed_source and not review.get("exporterReadyForEvidenceIntake"))
    status = "READY_FOR_MANUAL_MT5_EA_UPGRADE" if bundle_ready else "WAITING_MT5_UPGRADE_BUNDLE_INPUTS"
    if review.get("exporterReadyForEvidenceIntake"):
        status = "MT5_EXPORTER_ALREADY_AVAILABLE"

    repo_hash = _sha256(repo_source) if repo_source else ""
    installed_hash = _sha256(installed_source) if installed_source else ""
    if write and bundle_ready and repo_source:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_source, staged_source)
        helper_script.write_text(
            _script_text(str(installed_source), SOURCE_FILE),
            encoding="utf-8",
        )
        try:
            helper_script.chmod(0o755)
        except OSError:
            pass

    payload = {
        "ok": True,
        "schema": MT5_EXPORTER_UPGRADE_BUNDLE_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": "可人工升级 MT5 EA exporter" if bundle_ready else "等待 MT5 EA exporter 升级包输入",
        "bundleReadyForManualUpgrade": bundle_ready,
        "bundleWritten": bool(write and bundle_ready),
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "installedFilesMutated": False,
        "compileAttempted": False,
        "copyIntoMt5Allowed": False,
        "source": {
            "repoEaSourcePath": str(repo_source) if repo_source else str(review.get("repoEaSource", {}).get("path") or ""),
            "repoEaSha256": repo_hash,
            "repoHasExporter": bool(review.get("repoEaSource", {}).get("hasExporter")),
        },
        "target": {
            "installedEaSourcePath": str(installed_source) if installed_source else str(review.get("installedMt5Ea", {}).get("sourcePath") or ""),
            "installedEaSha256Before": installed_hash,
            "installedSourceHasExporter": bool(review.get("installedMt5Ea", {}).get("sourceHasExporter")),
        },
        "bundle": {
            "directory": str(bundle_dir),
            "stagedSourcePath": str(staged_source),
            "helperScriptPath": str(helper_script),
            "manifestPath": str(manifest_path),
            "stagedSourceExists": staged_source.exists(),
            "helperScriptExists": helper_script.exists(),
            "stagedSourceSha256": _sha256(staged_source) if staged_source.exists() else "",
        },
        "reviewStatus": {
            "mt5ExporterReviewStatus": review.get("status", ""),
            "mt5EaUpgradeRequired": upgrade_required,
            "exporterReadyForEvidenceIntake": bool(review.get("exporterReadyForEvidenceIntake")),
        },
        "manualSteps": [
            "Open MT5/MetaEditor manually.",
            f"Copy the staged {SOURCE_FILE} from the bundle directory into the MT5 Experts target path.",
            "Compile the EA in MetaEditor and reload it on the chart.",
            "Confirm EnableHfmCryptoSpecExporter=true in the preset/input panel.",
            "Refresh mt5-exporter-review, contract-spec-export, execution-spec, and live evidence intake.",
        ],
        "blockers": blockers,
        "nextRequiredActionZh": (
            "人工复制 bundle 中的 EA 源码到 MT5 Experts 目录，MetaEditor 编译后重新加载 EA。"
            if bundle_ready
            else "先让仓库 EA 和安装目录路径可识别，并确认是否真的需要升级。"
        ),
        "safety": {
            **SAFETY,
            "mutatesMt5": False,
            "installedFilesMutated": False,
            "compileAttempted": False,
            "copyIntoMt5Allowed": False,
            "symbolSelectAllowed": False,
        },
    }
    if write:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_mt5_upgrade_bundle(runtime_dir: Path) -> dict[str, Any]:
    path = mt5_exporter_upgrade_bundle_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        payload = _read_json(path)
        if payload:
            return payload
    return build_hfm_crypto_mt5_upgrade_bundle(Path(runtime_dir), write=False)
