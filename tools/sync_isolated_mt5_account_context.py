#!/usr/bin/env python3
"""Sync local MT5 account context into the isolated Strategy Tester root.

This copies the minimum local terminal account context needed for MT5's
Strategy Tester to recognize an account in portable isolated mode. It writes
only under the tester root, never launches MT5, and never edits live presets.
The target runtime directory is gitignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5"
DEFAULT_TESTER_ROOT = DEFAULT_REPO_ROOT / "runtime" / "HFM_MT5_Tester_Isolated"
DEFAULT_LOGIN = "90000001"
DEFAULT_SERVER = "SyntheticBroker-Demo"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync HFM MT5 account context into isolated tester root.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--tester-root", default=str(DEFAULT_TESTER_ROOT))
    parser.add_argument("--login", default=DEFAULT_LOGIN)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--status", default="")
    parser.add_argument(
        "--allow-sensitive-account-context",
        action="store_true",
        help="Required: confirms copying local account context into gitignored isolated tester runtime.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Inspect account-context readiness and write status without copying sensitive account files.",
    )
    return parser.parse_args()


def sha256_prefix(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def copy_file(src: Path, dst: Path, *, required: bool = False) -> dict[str, Any] | None:
    if not src.exists():
        if required:
            raise FileNotFoundError(src)
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {
        "path": str(dst),
        "bytes": dst.stat().st_size,
        "sha256Prefix": sha256_prefix(dst),
    }


def copy_tree(src: Path, dst: Path) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    if not src.exists():
        return copied
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        copied_file = copy_file(item, dst / rel)
        if copied_file:
            copied_file["relativePath"] = str(rel).replace("\\", "/")
            copied.append(copied_file)
    return copied


def path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def file_probe(path: Path, *, include_hash: bool = False) -> dict[str, Any]:
    exists = path.exists()
    probe: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
    }
    if exists:
        stat = path.stat()
        probe["bytes"] = stat.st_size
        probe["mtimeIso"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        if include_hash:
            probe["sha256Prefix"] = sha256_prefix(path)
    return probe


def build_status(
    *,
    mode: str,
    source_root: Path,
    tester_root: Path,
    login: str,
    server: str,
    copied_files: list[dict[str, Any]] | None = None,
    copied_trees: list[dict[str, Any]] | None = None,
    sensitive_copy_allowed: bool = False,
) -> dict[str, Any]:
    copied_files = copied_files or []
    copied_trees = copied_trees or []
    account_trade_root = tester_root / "Bases" / server / "trades" / login
    selected_symbols = tester_root / "Bases" / server / "symbols" / f"selected-{login}.dat"
    required_target_checks = {
        "Config/accounts.dat": file_probe(tester_root / "Config" / "accounts.dat", include_hash=sensitive_copy_allowed),
        "Config/servers.dat": file_probe(tester_root / "Config" / "servers.dat", include_hash=sensitive_copy_allowed),
        f"Bases/{server}": {
            "path": str(tester_root / "Bases" / server),
            "exists": (tester_root / "Bases" / server).exists(),
        },
        f"Bases/{server}/trades/{login}": {
            "path": str(account_trade_root),
            "exists": account_trade_root.exists(),
        },
        f"Bases/{server}/symbols/selected-{login}.dat": file_probe(selected_symbols, include_hash=sensitive_copy_allowed),
    }
    source_checks = {
        "terminal64.exe": file_probe(source_root / "terminal64.exe"),
        "Config/accounts.dat": file_probe(source_root / "Config" / "accounts.dat"),
        "Config/servers.dat": file_probe(source_root / "Config" / "servers.dat"),
        f"Bases/{server}": {
            "path": str(source_root / "Bases" / server),
            "exists": (source_root / "Bases" / server).exists(),
        },
    }
    missing_target = [
        key
        for key, value in required_target_checks.items()
        if not bool(value.get("exists"))
    ]
    missing_source = [
        key
        for key, value in source_checks.items()
        if not bool(value.get("exists"))
    ]
    ready = (
        required_target_checks["Config/accounts.dat"]["exists"]
        and required_target_checks["Config/servers.dat"]["exists"]
        and required_target_checks[f"Bases/{server}"]["exists"]
        and (
            required_target_checks[f"Bases/{server}/trades/{login}"]["exists"]
            or required_target_checks[f"Bases/{server}/symbols/selected-{login}.dat"]["exists"]
        )
    )
    blockers: list[str] = []
    if missing_source:
        blockers.append("source_mt5_account_context_not_found")
    if missing_target:
        blockers.append("isolated_tester_account_context_not_ready")
    if missing_target and not sensitive_copy_allowed:
        blockers.append("sensitive_account_context_sync_required")
    separate_sync_required = bool(missing_target and not missing_source and not sensitive_copy_allowed)
    command_preview = [
        "python3",
        "tools/sync_isolated_mt5_account_context.py",
        "--allow-sensitive-account-context",
    ]
    return {
        "schemaVersion": 1,
        "generatedAtIso": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "sourceRoot": str(source_root),
        "testerRoot": str(tester_root),
        "source": {
            "root": str(source_root),
            "terminalExists": source_checks["terminal64.exe"]["exists"],
            "accountContextExists": source_checks["Config/accounts.dat"]["exists"],
            "serverContextExists": source_checks["Config/servers.dat"]["exists"],
            "brokerBaseExists": source_checks[f"Bases/{server}"]["exists"],
            "missing": missing_source,
        },
        "target": {
            "root": str(tester_root),
            "accountContextExists": required_target_checks["Config/accounts.dat"]["exists"],
            "serverContextExists": required_target_checks["Config/servers.dat"]["exists"],
            "brokerBaseExists": required_target_checks[f"Bases/{server}"]["exists"],
            "tradeContextExists": required_target_checks[f"Bases/{server}/trades/{login}"]["exists"],
            "selectedSymbolsExists": required_target_checks[f"Bases/{server}/symbols/selected-{login}.dat"]["exists"],
            "missing": missing_target,
        },
        "login": login,
        "server": server,
        "ready": ready,
        "sensitiveCopyAllowed": sensitive_copy_allowed,
        "strategyBlocked": False,
        "environmentBlocked": not ready,
        "sensitiveAccountContextSyncRequired": bool(missing_target and not sensitive_copy_allowed),
        "sourceChecks": source_checks,
        "requiredTargetChecks": required_target_checks,
        "missingTarget": missing_target,
        "missingSource": missing_source,
        "blockers": blockers,
        "copiedFileCount": len(copied_files),
        "copiedTreeCount": len(copied_trees),
        "copiedFiles": [
            {
                "relativePath": item["relativePath"],
                "bytes": item["bytes"],
                "sha256Prefix": item["sha256Prefix"],
            }
            for item in copied_files
        ],
        "copiedTrees": copied_trees,
        "separateSyncReview": {
            "status": "SEPARATE_SENSITIVE_ACCOUNT_CONTEXT_SYNC_REQUIRED" if separate_sync_required else (
                "ACCOUNT_CONTEXT_SYNCED" if ready else "ACCOUNT_CONTEXT_PREFLIGHT_BLOCKED"
            ),
            "statusZh": (
                "源账户上下文存在，隔离 tester 目标缺文件；需要单独受控同步，本 preflight 不复制。"
                if separate_sync_required
                else (
                    "隔离 tester 账户上下文已就绪。"
                    if ready
                    else "账户上下文 preflight 仍被源或目标缺失挡住。"
                )
            ),
            "sourceAccountContextExists": bool(source_checks["Config/accounts.dat"]["exists"]),
            "targetAccountContextExists": bool(required_target_checks["Config/accounts.dat"]["exists"]),
            "missingTarget": missing_target,
            "missingSource": missing_source,
            "requiresSeparateControlledSync": separate_sync_required,
            "sensitiveCopyAllowedHere": sensitive_copy_allowed,
            "commandPreview": command_preview if separate_sync_required else [],
            "writesOnlyUnderTesterRoot": True,
            "launchesTerminal": False,
            "writesLivePreset": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
        },
        "nextActionZh": (
            "隔离 tester 账户上下文已就绪，可在 tester-only lock/window 内重试。"
            if ready
            else "隔离 tester 账户上下文不完整；需要单独受控同步账户上下文后再重试 Strategy Tester。"
        ),
        "hardGuards": [
            "Local filesystem operation only; no network transfer.",
            "Writes only under repo runtime/HFM_MT5_Tester_Isolated when sensitive sync is explicitly allowed.",
            "Does not launch terminal64.exe or Strategy Tester.",
            "Does not mutate live HFM presets or live-pilot Files.",
            "Generated ParamLab tester configs still set AllowLiveTrading=0.",
        ],
    }


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root)
    source_root = Path(args.source_root)
    tester_root = Path(args.tester_root)
    status_path = Path(args.status) if args.status else repo_root / "runtime" / "QuantGod_IsolatedTesterAccountContextStatus.json"
    login = str(args.login).strip()
    server = str(args.server).strip()

    if not path_under(tester_root, repo_root / "runtime"):
        raise SystemExit(f"tester root must stay under repo runtime/: {tester_root}")
    if args.preflight_only:
        status = build_status(
            mode="PREFLIGHT_ONLY_NO_SENSITIVE_COPY",
            source_root=source_root,
            tester_root=tester_root,
            login=login,
            server=server,
            sensitive_copy_allowed=False,
        )
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Preflight isolated tester account context: ready={status['ready']}")
        print(f"Wrote {status_path}")
        return 0 if status["ready"] else 2
    if not args.allow_sensitive_account_context:
        raise SystemExit("Refusing to copy account context without --allow-sensitive-account-context")
    if not (source_root / "terminal64.exe").exists():
        raise FileNotFoundError(f"source MT5 terminal missing: {source_root / 'terminal64.exe'}")
    if not (tester_root / "terminal64.exe").exists():
        raise FileNotFoundError(f"isolated tester terminal missing: {tester_root / 'terminal64.exe'}")

    copied_files: list[dict[str, Any]] = []
    copied_trees: list[dict[str, Any]] = []

    for name in ("accounts.dat", "servers.dat", "dnsperf.dat"):
        copied = copy_file(source_root / "Config" / name, tester_root / "Config" / name, required=(name == "accounts.dat"))
        if copied:
            copied["relativePath"] = f"Config/{name}"
            copied_files.append(copied)

    terminal_license = copy_file(source_root / "Config" / "terminal.lic", tester_root / "Config" / "terminal.lic")
    if terminal_license:
        terminal_license["relativePath"] = "Config/terminal.lic"
        copied_files.append(terminal_license)

    for rel in (
        Path("Bases") / "dns.dat",
        Path("Bases") / "symbols.raw",
    ):
        copied = copy_file(source_root / rel, tester_root / rel)
        if copied:
            copied["relativePath"] = str(rel).replace("\\", "/")
            copied_files.append(copied)

    server_tree = copy_tree(source_root / "Bases" / server, tester_root / "Bases" / server)
    if server_tree:
        copied_trees.append({
            "relativeRoot": f"Bases/{server}",
            "fileCount": len(server_tree),
            "sample": [
                {
                    "relativePath": item["relativePath"],
                    "bytes": item["bytes"],
                    "sha256Prefix": item["sha256Prefix"],
                }
                for item in server_tree[:12]
            ],
        })

    status = build_status(
        mode="LOCAL_ONLY_SYNC_TO_ISOLATED_TESTER",
        source_root=source_root,
        tester_root=tester_root,
        login=login,
        server=server,
        copied_files=copied_files,
        copied_trees=copied_trees,
        sensitive_copy_allowed=True,
    )
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Synced isolated tester account context: ready={status['ready']}")
    print(f"Wrote {status_path}")
    return 0 if status["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
