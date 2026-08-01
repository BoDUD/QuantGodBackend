#!/usr/bin/env python3
"""Create and verify recoverable local Shadow/ReadOnly runtime backups.

The backup lane uses SQLite's online backup API and copies a small allowlist of
operational evidence. It never reads credentials, changes MT5, or touches order
state. A backup on the same disk is not a second failure domain, but it provides
an atomic local recovery point that can also be copied to an encrypted volume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SQLITE_RELATIVE_PATHS = (
    Path("backtest/usdjpy.sqlite"),
    Path("QuantGod_MT5Platform.db"),
)

EVIDENCE_RELATIVE_PATHS = (
    Path("QuantGod_Dashboard.json"),
    Path("backtest/QuantGod_USDJPYHistoricalKlineSyncReport.json"),
    Path("backtest/QuantGod_USDJPYHistoryProductionStatus.json"),
    Path("backtest/QuantGod_StrategyBacktestQualityReport.json"),
    Path("automation/QuantGod_AutomationChainLatest.json"),
    Path("production_validation/QuantGod_ProductionEvidenceValidationReport.json"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_runtime_dir() -> Path:
    configured = os.environ.get("QG_RUNTIME_DIR") or os.environ.get("QG_MT5_FILES_DIR")
    if configured:
        return Path(configured).expanduser()
    mac_files = (
        Path.home()
        / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Files"
    )
    return mac_files if mac_files.exists() else Path(__file__).resolve().parents[1] / "runtime"


def default_backup_root() -> Path:
    configured = os.environ.get("QG_LOCAL_BACKUP_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / ".quantgod" / "backups"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_root_id(runtime_dir: Path) -> str:
    resolved = runtime_dir.resolve()
    return hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]


def secure_tree(root: Path) -> None:
    os.chmod(root, stat.S_IRWXU)
    for path in root.rglob("*"):
        if path.is_dir():
            os.chmod(path, stat.S_IRWXU)
        elif path.is_file():
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def sqlite_online_backup(source: Path, target: Path) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30.0)
    target_connection = sqlite3.connect(target, timeout=30.0)
    try:
        source_connection.execute("PRAGMA busy_timeout=30000")
        source_connection.backup(target_connection)
        target_connection.commit()
        quick_check = str(target_connection.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check.lower() != "ok":
            raise RuntimeError(f"SQLite quick_check failed for {source.name}: {quick_check}")
    finally:
        target_connection.close()
        source_connection.close()
    return {"quickCheck": "ok", "sizeBytes": target.stat().st_size, "sha256": sha256_file(target)}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_backup(runtime_dir: Path, backup_root: Path) -> dict[str, Any]:
    runtime_dir = runtime_dir.expanduser().resolve()
    backup_root = backup_root.expanduser().resolve()
    if not runtime_dir.exists() or not runtime_dir.is_dir():
        raise FileNotFoundError(f"runtime directory does not exist: {runtime_dir}")
    backup_root.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_root, stat.S_IRWXU)

    backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{uuid.uuid4().hex[:8]}"
    partial = backup_root / f".partial-{backup_id}"
    final = backup_root / backup_id
    partial.mkdir(mode=0o700)
    files: list[dict[str, Any]] = []
    try:
        for relative in SQLITE_RELATIVE_PATHS:
            source = runtime_dir / relative
            if not source.exists():
                continue
            target = partial / relative
            details = sqlite_online_backup(source, target)
            files.append({"kind": "sqlite", "relativePath": relative.as_posix(), **details})

        for relative in EVIDENCE_RELATIVE_PATHS:
            source = runtime_dir / relative
            if not source.exists() or not source.is_file():
                continue
            target = partial / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files.append({
                "kind": "evidence",
                "relativePath": relative.as_posix(),
                "sizeBytes": target.stat().st_size,
                "sha256": sha256_file(target),
            })

        manifest = {
            "schema": "quantgod.local_shadow_backup.v1",
            "backupId": backup_id,
            "createdAt": utc_now(),
            "mode": "SHADOW_READONLY",
            "canonicalRuntimeId": canonical_root_id(runtime_dir),
            "fileCount": len(files),
            "files": files,
            "secondFailureDomain": False,
            "secondFailureDomainRequiredForDisasterRecovery": True,
            "safety": {
                "executionLaneExists": False,
                "orderSendAllowed": False,
                "livePresetMutationAllowed": False,
                "credentialFilesIncluded": False,
                "mutatesMt5": False,
            },
        }
        if not files:
            raise RuntimeError("no allowlisted runtime files were available to back up")
        atomic_json(partial / "manifest.json", manifest)
        secure_tree(partial)
        os.replace(partial, final)
        manifest["backupPath"] = str(final)
        return manifest
    except Exception:
        if partial.exists() and partial.parent == backup_root and partial.name.startswith(".partial-"):
            shutil.rmtree(partial)
        raise


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    for row in manifest.get("files", []):
        relative = Path(str(row.get("relativePath") or ""))
        target = (backup_dir / relative).resolve()
        if backup_dir not in target.parents:
            raise ValueError(f"backup manifest path escapes backup root: {relative}")
        exists = target.exists() and target.is_file()
        digest_ok = exists and sha256_file(target) == row.get("sha256")
        quick_check = None
        if exists and row.get("kind") == "sqlite":
            connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=30.0)
            try:
                quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            finally:
                connection.close()
        checks.append({
            "relativePath": relative.as_posix(),
            "exists": exists,
            "sha256Ok": digest_ok,
            "quickCheck": quick_check,
            "ok": exists and digest_ok and (quick_check in (None, "ok")),
        })
    ok = bool(checks) and all(row["ok"] for row in checks)
    return {
        "schema": "quantgod.local_shadow_backup_verification.v1",
        "verifiedAt": utc_now(),
        "backupId": manifest.get("backupId"),
        "backupPath": str(backup_dir),
        "ok": ok,
        "checks": checks,
        "safety": {"orderSendAllowed": False, "mutatesMt5": False},
    }


def latest_backup(backup_root: Path) -> Path:
    candidates = sorted(
        path for path in backup_root.expanduser().resolve().iterdir()
        if path.is_dir() and not path.name.startswith(".") and (path / "manifest.json").exists()
    )
    if not candidates:
        raise FileNotFoundError(f"no completed backups under {backup_root}")
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantGod local Shadow runtime backup")
    parser.add_argument("--runtime-dir", default=str(default_runtime_dir()))
    parser.add_argument("--backup-root", default=str(default_backup_root()))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup-dir", default="")
    args = parser.parse_args()

    if args.command == "backup":
        payload = create_backup(Path(args.runtime_dir), Path(args.backup_root))
    else:
        target = Path(args.backup_dir) if args.backup_dir else latest_backup(Path(args.backup_root))
        payload = verify_backup(target)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
