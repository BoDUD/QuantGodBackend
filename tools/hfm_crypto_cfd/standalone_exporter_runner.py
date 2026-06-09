from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import SAFETY, hfm_crypto_dir, utc_now_iso
from .standalone_exporter_bundle import (
    EXPERT_FILE,
    SCRIPT_FILE,
    _default_wine64_path,
    _runtime_experts_dir,
    _runtime_scripts_dir,
    _runtime_wineprefix,
    _startup_command,
    _startup_config_path,
    _terminal_workdir,
    _windows_config_path,
    build_hfm_crypto_standalone_exporter_bundle,
)


RUNNER_FILE = "QuantGod_HFMCryptoStandaloneExporterRunner.json"


def _runner_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / RUNNER_FILE


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def _run_command(command: list[str], *, cwd: Path, wineprefix: Path | None, timeout: int) -> dict[str, Any]:
    env = os.environ.copy()
    if wineprefix:
        env["WINEPREFIX"] = str(wineprefix)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "attempted": True,
            "returnCode": completed.returncode,
            "stdoutTail": (completed.stdout or "")[-4000:],
            "stderrTail": (completed.stderr or "")[-4000:],
            "command": command,
            "cwd": str(cwd),
        }
    except Exception as exc:
        return {
            "attempted": True,
            "returnCode": None,
            "error": str(exc),
            "command": command,
            "cwd": str(cwd),
        }


def _compile_source(runtime_dir: Path, source_path: Path, log_name: str) -> dict[str, Any]:
    workdir = _terminal_workdir(runtime_dir)
    wine64 = _default_wine64_path()
    metaeditor = workdir / "metaeditor64.exe"
    drive_c_qg = workdir.parents[1] / "qg" if workdir.name == "MetaTrader 5" else hfm_crypto_dir(runtime_dir)
    drive_c_qg.mkdir(parents=True, exist_ok=True)
    work_source = drive_c_qg / source_path.name
    work_compiled = work_source.with_suffix(".ex5")
    log_path = drive_c_qg / log_name
    shutil.copy2(source_path, work_source)
    if work_compiled.exists():
        work_compiled.unlink()
    command = [
        str(wine64),
        r"C:\Program Files\MetaTrader 5\metaeditor64.exe",
        "/portable",
        "/compile:" + _windows_config_path(work_source, runtime_dir),
        "/log:" + _windows_config_path(log_path, runtime_dir),
    ]
    result = _run_command(command, cwd=workdir, wineprefix=_runtime_wineprefix(runtime_dir), timeout=180)
    target_compiled = source_path.with_suffix(".ex5")
    copied_compiled_back = False
    if work_compiled.exists() and work_compiled.stat().st_size > 0:
        shutil.copy2(work_compiled, target_compiled)
        copied_compiled_back = True
    compiled_fresh = bool(
        target_compiled.exists()
        and target_compiled.stat().st_size > 0
        and target_compiled.stat().st_mtime >= source_path.stat().st_mtime
    )
    result.update({
        "sourcePath": str(source_path),
        "sourceMtimeIso": _mtime_iso(source_path),
        "compiledPath": str(target_compiled),
        "compiledExists": target_compiled.exists(),
        "compiledMtimeIso": _mtime_iso(target_compiled),
        "compiledFresh": compiled_fresh,
        "copiedCompiledBack": copied_compiled_back,
        "workSourcePath": str(work_source),
        "workCompiledPath": str(work_compiled),
        "workCompiledExists": work_compiled.exists(),
        "logPath": str(log_path),
        "logExists": log_path.exists(),
        "logTail": log_path.read_text(encoding="utf-16le", errors="replace")[-4000:] if log_path.exists() else "",
        "metaeditorPath": str(metaeditor),
        "metaeditorExists": metaeditor.exists(),
    })
    return result


def build_hfm_crypto_standalone_exporter_runner(
    runtime_dir: Path,
    *,
    install: bool = False,
    compile_sources: bool = False,
    run_terminal: bool = False,
    write: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    bundle = build_hfm_crypto_standalone_exporter_bundle(runtime_dir, write=True)
    scripts_dir = _runtime_scripts_dir(runtime_dir)
    experts_dir = _runtime_experts_dir(runtime_dir)
    target_script = scripts_dir / SCRIPT_FILE
    target_expert = experts_dir / EXPERT_FILE
    installed_files: list[str] = []
    if install and bundle.get("standaloneExporterReady"):
        scripts_dir.mkdir(parents=True, exist_ok=True)
        experts_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(bundle["bundle"]["stagedScriptPath"]), target_script)
        shutil.copy2(Path(bundle["bundle"]["stagedExpertPath"]), target_expert)
        installed_files.extend([str(target_script), str(target_expert)])

    compile_results: list[dict[str, Any]] = []
    if compile_sources:
        if target_script.exists():
            compile_results.append(_compile_source(runtime_dir, target_script, "QuantGod_HFMCryptoSpecExporter_compile.log"))
        if target_expert.exists():
            compile_results.append(_compile_source(runtime_dir, target_expert, "QuantGod_HFMCryptoSpecExporterEA_compile.log"))

    startup_config_path = _startup_config_path(runtime_dir, hfm_crypto_dir(runtime_dir) / "standalone_exporter_bundle")
    terminal_result: dict[str, Any] = {"attempted": False}
    if run_terminal:
        workdir = _terminal_workdir(runtime_dir)
        wine64 = _default_wine64_path()
        command = [
            str(wine64),
            "terminal64.exe",
            "/portable",
            "/config:" + _windows_config_path(startup_config_path, runtime_dir),
        ]
        terminal_result = _run_command(command, cwd=workdir, wineprefix=_runtime_wineprefix(runtime_dir), timeout=180)

    refreshed_bundle = build_hfm_crypto_standalone_exporter_bundle(runtime_dir, write=False)
    output = refreshed_bundle.get("output") if isinstance(refreshed_bundle.get("output"), dict) else {}
    payload = {
        "ok": True,
        "schema": "quantgod.hfm_crypto_cfd.standalone_exporter_runner.v1",
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "RUNNER_COMPLETED" if install or compile_sources or run_terminal else "RUNNER_DRY_RUN",
        "installAttempted": install,
        "compileAttempted": compile_sources,
        "scriptRunAttempted": run_terminal,
        "installedFilesMutated": bool(installed_files),
        "installedFiles": installed_files,
        "compileResults": compile_results,
        "terminalRun": terminal_result,
        "startupCommand": _startup_command(runtime_dir, startup_config_path),
        "target": refreshed_bundle.get("target", {}),
        "output": output,
        "nextRequiredActionZh": (
            "rates JSON 已出现；刷新 rates-export、simulation-profile 和 profit target。"
            if output.get("expectedRatesExists")
            else "MetaEditor 未生成最新 exporter .ex5；先修编译日志，再运行只读启动配置。"
            if compile_sources and any(not row.get("compiledFresh") for row in compile_results)
            else "若编译通过但 rates JSON 未出现，重新运行只读启动配置或检查 MT5 Journal。"
        ),
        "safety": {
            **SAFETY,
            "allowLiveTrading": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "livePresetMutationAllowed": False,
        },
    }
    if write:
        out = _runner_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_standalone_exporter_runner(runtime_dir: Path) -> dict[str, Any]:
    path = _runner_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
        except Exception:
            pass
    return build_hfm_crypto_standalone_exporter_runner(Path(runtime_dir), write=False)
