from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .mt5_exporter_review import SOURCE_FILE, build_hfm_crypto_mt5_exporter_review
from .schema import SAFETY, hfm_crypto_dir, utc_now_iso
from .standalone_exporter_bundle import (
    _default_wine64_path,
    _runtime_wineprefix,
    _terminal_workdir,
    _windows_config_path,
)
from .standalone_exporter_runner import _compile_source


RUNNER_FILE = "QuantGod_HFMCryptoMt5UpgradeRunner.json"


def _runner_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / RUNNER_FILE


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def _fallback_installed_source_path(runtime_dir: Path) -> Path:
    runtime = Path(runtime_dir).expanduser()
    if runtime.name.lower() == "files":
        return runtime.parent / "Experts" / SOURCE_FILE
    return runtime / "Experts" / SOURCE_FILE


def _path_from_review(value: Any, runtime_dir: Path) -> Path:
    text = str(value or "").strip()
    if text:
        return Path(text).expanduser()
    return _fallback_installed_source_path(runtime_dir)


def _copy_source_with_backup(repo_source: Path, installed_source: Path) -> dict[str, Any]:
    installed_source.parent.mkdir(parents=True, exist_ok=True)
    before_hash = _sha256(installed_source) if installed_source.exists() else ""
    repo_hash = _sha256(repo_source)
    backup_path = ""
    backup_hash = ""
    if installed_source.exists() and before_hash != repo_hash:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = installed_source.with_name(f"{installed_source.name}.qg_backup_{stamp}")
        shutil.copy2(installed_source, backup)
        backup_path = str(backup)
        backup_hash = _sha256(backup)
    shutil.copy2(repo_source, installed_source)
    return {
        "installedSourcePath": str(installed_source),
        "installedSourceExists": installed_source.exists(),
        "installedSourceSha256Before": before_hash,
        "repoSourceSha256": repo_hash,
        "installedSourceSha256After": _sha256(installed_source),
        "backupPath": backup_path,
        "backupSha256": backup_hash,
        "sourceMtimeIso": _mtime_iso(installed_source),
        "copied": True,
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_startup_config(runtime_dir: Path) -> Path:
    wineprefix = _runtime_wineprefix(runtime_dir)
    if wineprefix:
        return wineprefix / "drive_c" / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"
    return hfm_crypto_dir(runtime_dir) / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"


def _screen_sessions(screen_name: str) -> list[str]:
    try:
        completed = subprocess.run(["screen", "-ls"], check=False, capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    sessions: list[str] = []
    for line in (completed.stdout or "").splitlines():
        token = line.strip().split("\t", 1)[0].strip()
        if token.endswith("." + screen_name):
            sessions.append(token)
    return sessions


def _matching_terminal_processes(*, wineprefix: Path | None, windows_config: str) -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(["ps", "ax"], check=False, capture_output=True, text=True, timeout=10)
    except Exception:
        return []

    wineprefix_text = str(wineprefix or "")
    rows: list[dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("PID "):
            continue
        parts = stripped.split(None, 4)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        command = parts[-1] if len(parts) >= 5 else stripped
        if "terminal64.exe" not in command:
            continue
        config_match = bool(windows_config and windows_config in command)
        wineprefix_match = bool(wineprefix_text and wineprefix_text in command)
        if not (config_match or wineprefix_match):
            continue
        rows.append({
            "pid": pid,
            "commandTail": command[-1000:],
            "matchedWindowsConfig": config_match,
            "matchedWineprefix": wineprefix_match,
        })
    return rows


def _terminate_processes(processes: list[dict[str, Any]], *, signal_name: str = "-TERM") -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    for process in processes:
        pid = int(process.get("pid") or 0)
        if pid <= 0 or pid in seen or pid == os.getpid():
            continue
        seen.add(pid)
        completed = subprocess.run(["kill", signal_name, str(pid)], check=False, capture_output=True, text=True, timeout=10)
        results.append({
            "pid": pid,
            "signal": signal_name,
            "returnCode": completed.returncode,
            "stdoutTail": (completed.stdout or "")[-1000:],
            "stderrTail": (completed.stderr or "")[-1000:],
        })
    return results


def _restart_terminal_screen(runtime_dir: Path, *, screen_name: str = "quantgod-mt5-live16", startup_config: str = "") -> dict[str, Any]:
    workdir = _terminal_workdir(runtime_dir)
    wineprefix = _runtime_wineprefix(runtime_dir)
    wine64 = _default_wine64_path()
    config_path = Path(startup_config).expanduser() if startup_config else _default_startup_config(runtime_dir)
    log_path = _repo_root() / "runtime" / "mt5_hfm_secondary_live_screen.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    blockers: list[dict[str, Any]] = []
    if not workdir.exists():
        blockers.append({"code": "MT5_WORKDIR_MISSING", "reasonZh": "MT5 terminal 目录不存在。", "value": str(workdir)})
    if wineprefix is None or not wineprefix.exists():
        blockers.append({"code": "MT5_WINEPREFIX_MISSING", "reasonZh": "Live16 Wine prefix 不存在。", "value": str(wineprefix or "")})
    if not wine64.exists():
        blockers.append({"code": "WINE64_MISSING", "reasonZh": "wine64 不存在，无法启动 MT5。", "value": str(wine64)})
    if not config_path.exists():
        blockers.append({"code": "MT5_STARTUP_CONFIG_MISSING", "reasonZh": "Live16 启动配置不存在。", "value": str(config_path)})
    if blockers:
        return {
            "attempted": True,
            "started": False,
            "screenName": screen_name,
            "blockers": blockers,
            "startupConfigPath": str(config_path),
            "workdir": str(workdir),
            "wineprefix": str(wineprefix or ""),
            "wine64Path": str(wine64),
        }

    windows_config = _windows_config_path(config_path, runtime_dir)
    before_sessions = _screen_sessions(screen_name)
    before_processes = _matching_terminal_processes(wineprefix=wineprefix, windows_config=windows_config)
    quit_results: list[dict[str, Any]] = []
    for session in before_sessions or [screen_name]:
        completed = subprocess.run(["screen", "-S", session, "-X", "quit"], check=False, capture_output=True, text=True, timeout=10)
        quit_results.append({
            "session": session,
            "returnCode": completed.returncode,
            "stdoutTail": (completed.stdout or "")[-1000:],
            "stderrTail": (completed.stderr or "")[-1000:],
        })
    time.sleep(3)
    orphan_processes_after_screen_quit = _matching_terminal_processes(wineprefix=wineprefix, windows_config=windows_config)
    orphan_terminate_results = _terminate_processes(orphan_processes_after_screen_quit)
    if orphan_terminate_results:
        time.sleep(3)
    processes_after_terminate = _matching_terminal_processes(wineprefix=wineprefix, windows_config=windows_config)
    shell_command = (
        "cd " + shlex.quote(str(workdir)) +
        " && exec env WINEPREFIX=" + shlex.quote(str(wineprefix)) +
        " " + shlex.quote(str(wine64)) +
        " terminal64.exe /portable " + shlex.quote("/config:" + windows_config) +
        " >> " + shlex.quote(str(log_path)) + " 2>&1"
    )
    start_command = ["screen", "-dmS", screen_name, "/bin/zsh", "-lc", shell_command]
    start = subprocess.run(start_command, check=False, capture_output=True, text=True, timeout=10)
    time.sleep(2)
    after_sessions = _screen_sessions(screen_name)
    after_processes = _matching_terminal_processes(wineprefix=wineprefix, windows_config=windows_config)
    return {
        "attempted": True,
        "started": bool(after_sessions),
        "screenName": screen_name,
        "screenSessionsBefore": before_sessions,
        "screenSessionsAfter": after_sessions,
        "terminalProcessesBefore": before_processes,
        "orphanProcessesAfterScreenQuit": orphan_processes_after_screen_quit,
        "orphanTerminateResults": orphan_terminate_results,
        "terminalProcessesAfterTerminate": processes_after_terminate,
        "terminalProcessesAfterStart": after_processes,
        "quitResults": quit_results,
        "startReturnCode": start.returncode,
        "startStdoutTail": (start.stdout or "")[-1000:],
        "startStderrTail": (start.stderr or "")[-1000:],
        "startupConfigPath": str(config_path),
        "startupConfigWindowsPath": windows_config,
        "workdir": str(workdir),
        "wineprefix": str(wineprefix),
        "wine64Path": str(wine64),
        "logPath": str(log_path),
        "command": start_command,
    }


def build_hfm_crypto_mt5_upgrade_runner(
    runtime_dir: Path,
    *,
    install: bool = False,
    compile_source: bool = False,
    restart_terminal: bool = False,
    screen_name: str = "quantgod-mt5-live16",
    startup_config: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    before_review = build_hfm_crypto_mt5_exporter_review(runtime_dir, write=write)
    repo_source = Path(str(before_review.get("repoEaSource", {}).get("path") or "")).expanduser()
    installed_source = _path_from_review(before_review.get("installedMt5Ea", {}).get("sourcePath"), runtime_dir)
    repo_ready = bool(repo_source.exists() and before_review.get("repoEaSource", {}).get("hasExporter"))
    installed_result: dict[str, Any] = {"attempted": False}
    compile_result: dict[str, Any] = {"attempted": False}
    terminal_restart_result: dict[str, Any] = {"attempted": False}
    blockers: list[dict[str, Any]] = []

    if install:
        if not repo_ready:
            blockers.append({
                "code": "REPO_EA_EXPORTER_NOT_READY",
                "reasonZh": "仓库 EA 尚未包含可安装的只读 HFM crypto exporter/runtime probe。",
                "value": str(repo_source),
            })
        else:
            installed_result = _copy_source_with_backup(repo_source, installed_source)
            installed_result["attempted"] = True

    if compile_source:
        if not installed_source.exists():
            blockers.append({
                "code": "INSTALLED_EA_SOURCE_MISSING",
                "reasonZh": "安装目录缺少 QuantGod_MultiStrategy.mq5，无法编译。",
                "value": str(installed_source),
            })
        else:
            compile_result = _compile_source(runtime_dir, installed_source, "QuantGod_MultiStrategy_compile.log")

    if restart_terminal:
        terminal_restart_result = _restart_terminal_screen(
            runtime_dir,
            screen_name=screen_name,
            startup_config=startup_config,
        )
        blockers.extend(terminal_restart_result.get("blockers") or [])

    after_review = build_hfm_crypto_mt5_exporter_review(runtime_dir, write=write)
    compiled_fresh = bool(compile_result.get("compiledFresh"))
    copied = bool(installed_result.get("copied"))
    restarted = bool(terminal_restart_result.get("started"))
    status = "MT5_UPGRADE_RUNNER_DRY_RUN"
    status_zh = "MT5 EA 升级 runner 未执行安装或编译"
    if blockers:
        status = "MT5_UPGRADE_RUNNER_BLOCKED"
        status_zh = "MT5 EA 升级 runner 输入不足"
    elif copied and compile_source and compiled_fresh:
        status = "MT5_UPGRADE_RUNNER_INSTALLED_AND_COMPILED"
        status_zh = "MT5 EA 已安装并编译，等待 MT5 图表重载新版 EA"
    elif copied:
        status = "MT5_UPGRADE_RUNNER_INSTALLED"
        status_zh = "MT5 EA 源码已安装，等待编译或图表重载"
    elif compile_source and compiled_fresh:
        status = "MT5_UPGRADE_RUNNER_COMPILED"
        status_zh = "MT5 EA 已编译，等待 MT5 图表重载新版 EA"
    elif compile_source:
        status = "MT5_UPGRADE_RUNNER_COMPILE_NEEDS_REVIEW"
        status_zh = "MetaEditor 未生成最新 QuantGod_MultiStrategy.ex5，需要查看编译日志"
    if restarted and status in {"MT5_UPGRADE_RUNNER_INSTALLED_AND_COMPILED", "MT5_UPGRADE_RUNNER_COMPILED", "MT5_UPGRADE_RUNNER_DRY_RUN"}:
        status = "MT5_UPGRADE_RUNNER_RESTARTED"
        status_zh = "Live16 MT5 已重启，等待新版 EA 写出 runtime probe"

    payload = {
        "ok": True,
        "schema": "quantgod.hfm_crypto_cfd.mt5_upgrade_runner.v1",
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "installAttempted": install,
        "compileAttempted": compile_source,
        "terminalRestartAttempted": restart_terminal,
        "installedFilesMutated": copied,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "repoSource": {
            "path": str(repo_source),
            "exists": repo_source.exists(),
            "hasExporter": bool(before_review.get("repoEaSource", {}).get("hasExporter")),
            "sha256": _sha256(repo_source) if repo_source.exists() else "",
        },
        "target": {
            "installedSourcePath": str(installed_source),
            "installedSourceExists": installed_source.exists(),
            "installedSourceSha256": _sha256(installed_source) if installed_source.exists() else "",
            "compiledPath": str(installed_source.with_suffix(".ex5")),
            "compiledExists": installed_source.with_suffix(".ex5").exists(),
            "compiledMtimeIso": _mtime_iso(installed_source.with_suffix(".ex5")),
        },
        "installResult": installed_result,
        "compileResult": compile_result,
        "terminalRestart": terminal_restart_result,
        "beforeReview": {
            "status": before_review.get("status", ""),
            "mt5EaUpgradeRequired": bool(before_review.get("mt5EaUpgradeRequired")),
            "installedSourceHasExporter": bool(before_review.get("installedMt5Ea", {}).get("sourceHasExporter")),
        },
        "afterReview": {
            "status": after_review.get("status", ""),
            "mt5EaUpgradeRequired": bool(after_review.get("mt5EaUpgradeRequired")),
            "installedSourceHasExporter": bool(after_review.get("installedMt5Ea", {}).get("sourceHasExporter")),
            "dashboardBuild": after_review.get("dashboard", {}).get("dashboardBuild", ""),
            "dashboardHasHfmCryptoSymbolSpecs": bool(after_review.get("dashboard", {}).get("hasHfmCryptoSymbolSpecs")),
        },
        "blockers": blockers,
        "nextRequiredActionZh": (
            "等待新版 Live16 EA 刷新 dashboard.hfmCryptoRuntimeProbe 或 hfm_crypto/QuantGod_HFMCryptoRuntimeProbe.json，然后重跑 readiness/profit tracker。"
            if restarted
            else
            "让 MT5 图表重新加载 QuantGod_MultiStrategy.ex5，等待 dashboard.hfmCryptoRuntimeProbe 或 hfm_crypto/QuantGod_HFMCryptoRuntimeProbe.json 出现。"
            if status in {"MT5_UPGRADE_RUNNER_INSTALLED_AND_COMPILED", "MT5_UPGRADE_RUNNER_COMPILED"}
            else "先修复 MetaEditor 编译日志，确认安装目录 QuantGod_MultiStrategy.ex5 更新。"
            if compile_source and not compiled_fresh
            else "运行 --install --compile，把仓库只读 EA 安装到 Live16 并编译。"
        ),
        "safety": {
            **SAFETY,
            "mutatesMt5": copied,
            "installedFilesMutated": copied,
            "compileAttempted": compile_source,
            "terminalRestartAttempted": restart_terminal,
            "allowLiveTrading": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "livePresetMutationAllowed": False,
            "symbolSelectAllowed": False,
        },
    }
    if write:
        out = _runner_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_mt5_upgrade_runner(runtime_dir: Path) -> dict[str, Any]:
    path = _runner_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
        except Exception:
            pass
    return build_hfm_crypto_mt5_upgrade_runner(Path(runtime_dir), write=False)
