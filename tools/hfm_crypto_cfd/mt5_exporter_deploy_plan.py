from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .mt5_exporter_review import SOURCE_FILE
from .mt5_post_upgrade_verify import read_hfm_crypto_mt5_post_upgrade_verify
from .mt5_upgrade_bundle import build_hfm_crypto_mt5_upgrade_bundle, read_hfm_crypto_mt5_upgrade_bundle
from .schema import (
    MT5_EXPORTER_DEPLOY_PLAN_SCHEMA_VERSION,
    SAFETY,
    mt5_exporter_deploy_plan_path,
    mt5_exporter_upgrade_bundle_dir,
    utc_now_iso,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _path_from_text(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text).expanduser()


def _shell_quote(path: str) -> str:
    return "'" + str(path).replace("'", "'\"'\"'") + "'"


def _backup_timestamp(value: str) -> str:
    return value.replace("-", "").replace(":", "").replace("+00:00", "Z")


def _command(label_zh: str, command: str, *, manual_only: bool = True) -> dict[str, Any]:
    return {
        "labelZh": label_zh,
        "command": command,
        "manualOnly": manual_only,
        "executedByCodex": False,
    }


def build_hfm_crypto_mt5_exporter_deploy_plan(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    generated_at = utc_now_iso()
    bundle = (
        build_hfm_crypto_mt5_upgrade_bundle(runtime_dir, write=True)
        if write
        else read_hfm_crypto_mt5_upgrade_bundle(runtime_dir)
    )
    verify = read_hfm_crypto_mt5_post_upgrade_verify(runtime_dir)

    staged_source = _path_from_text(bundle.get("bundle", {}).get("stagedSourcePath"))
    installed_source = _path_from_text(bundle.get("target", {}).get("installedEaSourcePath"))
    bundle_dir = mt5_exporter_upgrade_bundle_dir(runtime_dir)
    backups_dir = bundle_dir / "backups"
    backup_path = backups_dir / f"{SOURCE_FILE}.{_backup_timestamp(generated_at)}.before"

    staged_exists = bool(staged_source and staged_source.exists() and staged_source.is_file())
    installed_exists = bool(installed_source and installed_source.exists() and installed_source.is_file())
    staged_hash = _sha256(staged_source) if staged_exists and staged_source else ""
    installed_hash = _sha256(installed_source) if installed_exists and installed_source else ""
    source_hash_matches_bundle = bool(
        staged_hash and bundle.get("source", {}).get("repoEaSha256") and staged_hash == bundle["source"]["repoEaSha256"]
    )
    hashes_differ = bool(staged_hash and installed_hash and staged_hash != installed_hash)

    blockers: list[dict[str, Any]] = []
    if not bundle.get("bundleReadyForManualUpgrade"):
        blockers.append(_blocker("MT5_EXPORTER_UPGRADE_BUNDLE_NOT_READY", "EA exporter 升级包还没有准备好。", bundle.get("status")))
    if not staged_exists:
        blockers.append(_blocker("STAGED_EA_SOURCE_MISSING", "升级包中的 staged EA 源码不存在。", str(staged_source or "")))
    if not installed_exists:
        blockers.append(_blocker("INSTALLED_EA_SOURCE_MISSING", "当前 MT5 Experts 目录里的 EA 源码不存在。", str(installed_source or "")))
    if staged_exists and bundle.get("source", {}).get("repoEaSha256") and not source_hash_matches_bundle:
        blockers.append(_blocker("STAGED_EA_HASH_MISMATCH", "staged EA 源码 hash 与 bundle 记录的仓库 hash 不一致。"))
    if staged_hash and installed_hash and not hashes_differ:
        blockers.append(_blocker("INSTALLED_EA_ALREADY_MATCHES_STAGED", "安装目录 EA 与 staged EA hash 相同，通常无需部署。"))

    deploy_plan_ready = not blockers
    rollback_plan_ready = installed_exists
    status = "READY_FOR_OPERATOR_MT5_EA_DEPLOY_REVIEW" if deploy_plan_ready else "WAITING_OPERATOR_MT5_EA_DEPLOY_REVIEW_INPUTS"
    status_zh = "等待人工复核 MT5 EA exporter 部署" if deploy_plan_ready else "等待 EA exporter 部署计划输入"

    staged_text = str(staged_source or "")
    installed_text = str(installed_source or "")
    backup_text = str(backup_path)
    commands = [
        _command("创建备份目录", f"mkdir -p {_shell_quote(str(backups_dir))}"),
        _command("备份当前 MT5 EA 源码", f"cp -p {_shell_quote(installed_text)} {_shell_quote(backup_text)}"),
        _command("部署 staged EA 源码到 MT5 Experts", f"cp -p {_shell_quote(staged_text)} {_shell_quote(installed_text)}"),
        _command("回滚到部署前备份", f"cp -p {_shell_quote(backup_text)} {_shell_quote(installed_text)}"),
    ]

    payload = {
        "ok": True,
        "schema": MT5_EXPORTER_DEPLOY_PLAN_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "deployPlanReady": deploy_plan_ready,
        "rollbackPlanReady": rollback_plan_ready,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "installedFilesMutated": False,
        "compileAttempted": False,
        "copyIntoMt5Allowed": False,
        "deployCommandExecuted": False,
        "rollbackCommandExecuted": False,
        "brokerCallsMade": False,
        "source": {
            "stagedSourcePath": staged_text,
            "stagedSourceExists": staged_exists,
            "stagedSourceSha256": staged_hash,
            "repoEaSha256": bundle.get("source", {}).get("repoEaSha256", ""),
            "sourceHashMatchesBundle": source_hash_matches_bundle,
        },
        "target": {
            "installedEaSourcePath": installed_text,
            "installedEaSourceExists": installed_exists,
            "installedEaSha256Before": installed_hash,
            "installedSourceHasExporter": bool(bundle.get("target", {}).get("installedSourceHasExporter")),
            "stagedDiffersFromInstalled": hashes_differ,
        },
        "backupPlan": {
            "backupDirectory": str(backups_dir),
            "backupPath": backup_text,
            "backupRequiredBeforeDeploy": True,
            "backupCreatedByThisTool": False,
        },
        "rollbackPlan": {
            "rollbackSourcePath": backup_text,
            "rollbackTargetPath": installed_text,
            "manualOnly": True,
            "rollbackCommandExecuted": False,
        },
        "operatorChecklist": [
            {
                "id": "pause_or_detach_ea",
                "labelZh": "在 MT5 图表上暂停/移除当前 EA，避免替换源码时仍在运行",
                "required": True,
                "automated": False,
            },
            {
                "id": "verify_staged_hash",
                "labelZh": "确认 staged EA hash 与 bundle/repo hash 一致",
                "required": True,
                "automated": False,
                "passedByPlan": source_hash_matches_bundle,
            },
            {
                "id": "backup_installed_source",
                "labelZh": "先备份安装目录当前 EA 源码",
                "required": True,
                "automated": False,
            },
            {
                "id": "copy_staged_source",
                "labelZh": "人工复制 staged EA 源码到 MT5 Experts 目录",
                "required": True,
                "automated": False,
            },
            {
                "id": "compile_metaeditor",
                "labelZh": "在 MetaEditor 编译 QuantGod_MultiStrategy.mq5",
                "required": True,
                "automated": False,
            },
            {
                "id": "reload_ea",
                "labelZh": "重新加载 EA，并确认 EnableHfmCryptoSpecExporter=true",
                "required": True,
                "automated": False,
            },
            {
                "id": "run_post_upgrade_controller",
                "labelZh": "运行 post-upgrade-controller --write 刷新 exporter/specs 审查",
                "required": True,
                "automated": False,
            },
        ],
        "commandsForHumanReview": commands,
        "reviewStatus": {
            "upgradeBundleStatus": bundle.get("status", ""),
            "postUpgradeVerifyStatus": verify.get("status", ""),
            "postUpgradeVerified": bool(verify.get("postUpgradeVerified")),
        },
        "blockers": blockers,
        "nextRequiredActionZh": (
            "人工复核 hash、备份安装目录 EA、复制 staged EA、MetaEditor 编译并重载，然后运行 post-upgrade-controller。"
            if deploy_plan_ready
            else "先重新生成 mt5-upgrade-bundle，确认 staged EA 和安装目录 EA 路径都存在且 hash 可对账。"
        ),
        "safety": {
            **SAFETY,
            "mutatesMt5": False,
            "installedFilesMutated": False,
            "compileAttempted": False,
            "copyIntoMt5Allowed": False,
            "deployCommandExecuted": False,
            "rollbackCommandExecuted": False,
            "brokerCallsMade": False,
            "symbolSelectAllowed": False,
        },
    }
    if write:
        plan_path = mt5_exporter_deploy_plan_path(runtime_dir)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_mt5_exporter_deploy_plan(runtime_dir: Path) -> dict[str, Any]:
    path = mt5_exporter_deploy_plan_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        payload = _read_json(path)
        if payload:
            return payload
    return build_hfm_crypto_mt5_exporter_deploy_plan(Path(runtime_dir), write=False)
