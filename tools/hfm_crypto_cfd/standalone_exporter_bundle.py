from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import (
    EA_RATES_EXPORT_FILE,
    EA_RUNTIME_PROBE_FILE,
    EA_SYMBOL_SPECS_FILE,
    SAFETY,
    STANDALONE_EXPORTER_BUNDLE_SCHEMA_VERSION,
    standalone_exporter_bundle_dir,
    standalone_exporter_bundle_path,
    utc_now_iso,
)


SCRIPT_FILE = "QuantGod_HFMCryptoSpecExporter.mq5"
EXPERT_FILE = "QuantGod_HFMCryptoSpecExporterEA.mq5"
EXPORTER_MARKERS = (
    "Standalone HFM Crypto Spec Exporter BEGIN",
    "BuildStandaloneHfmCryptoSymbolSpecsJson",
    "MQL5_SYMBOLINFO_READONLY_STANDALONE",
    EA_SYMBOL_SPECS_FILE,
    EA_RATES_EXPORT_FILE,
    "quantgod.mql5.hfm_crypto_rates_export.v1",
    "CopyRates",
    "orderSendAllowed",
    "mt5OrderSendAllowed",
    "writesMt5OrderRequest",
)
EXPERT_EXPORTER_MARKERS = (
    "Standalone HFM Crypto Spec Exporter EA BEGIN",
    "BuildStandaloneHfmCryptoSymbolSpecsJson",
    "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA",
    "ExpertRemove",
    EA_SYMBOL_SPECS_FILE,
    EA_RATES_EXPORT_FILE,
    EA_RUNTIME_PROBE_FILE,
    "quantgod.mql5.hfm_crypto_runtime_probe.v1",
    "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA_RUNTIME_PROBE",
    "quantgod.mql5.hfm_crypto_rates_export.v1",
    "CopyRates",
    "orderSendAllowed",
    "mt5OrderSendAllowed",
    "writesMt5OrderRequest",
)
FORBIDDEN_MARKERS = (
    "Order" + "Send(",
    "Order" + "SendAsync(",
    "TRADE_ACTION_" + "DEAL",
    "Position" + "Close(",
    "Symbol" + "Select(",
    "C" + "Trade",
    "FileRead",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("symbols", "rows", "items", "mappings", "contracts", "specs"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            return [dict(row) for row in value["items"] if isinstance(row, dict)]
    return []


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def _output_summary(path: Path) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    summary: dict[str, Any] = {
        "expectedSpecsExists": exists,
        "expectedSpecsSizeBytes": 0,
        "expectedSpecsMtimeIso": "",
        "expectedSpecsReadable": False,
        "expectedSpecsRowCount": 0,
    }
    if not exists:
        return summary
    try:
        summary["expectedSpecsSizeBytes"] = path.stat().st_size
        summary["expectedSpecsMtimeIso"] = _mtime_iso(path)
        payload = _read_json(path)
        rows = _extract_rows(payload)
        summary["expectedSpecsReadable"] = bool(payload)
        summary["expectedSpecsRowCount"] = len(rows)
    except OSError:
        pass
    return summary


def _rates_output_summary(path: Path) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    summary: dict[str, Any] = {
        "expectedRatesExists": exists,
        "expectedRatesSizeBytes": 0,
        "expectedRatesMtimeIso": "",
        "expectedRatesReadable": False,
        "expectedRatesSeriesCount": 0,
    }
    if not exists:
        return summary
    try:
        summary["expectedRatesSizeBytes"] = path.stat().st_size
        summary["expectedRatesMtimeIso"] = _mtime_iso(path)
        payload = _read_json(path)
        rows = _extract_rows(payload)
        summary["expectedRatesReadable"] = bool(payload)
        summary["expectedRatesSeriesCount"] = len(rows)
    except OSError:
        pass
    return summary


def _runtime_probe_output_summary(path: Path) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    summary: dict[str, Any] = {
        "expectedRuntimeProbeExists": exists,
        "expectedRuntimeProbeSizeBytes": 0,
        "expectedRuntimeProbeMtimeIso": "",
        "expectedRuntimeProbeReadable": False,
        "expectedRuntimeProbeSymbolCount": 0,
        "expectedRuntimeProbeLiveTickCount": 0,
    }
    if not exists:
        return summary
    try:
        summary["expectedRuntimeProbeSizeBytes"] = path.stat().st_size
        summary["expectedRuntimeProbeMtimeIso"] = _mtime_iso(path)
        payload = _read_json(path)
        rows = _extract_rows(payload)
        summary["expectedRuntimeProbeReadable"] = bool(payload)
        summary["expectedRuntimeProbeSymbolCount"] = len(rows)
        summary["expectedRuntimeProbeLiveTickCount"] = sum(
            1
            for row in rows
            if bool(row.get("tickOk")) and _number(row.get("ask")) is not None and _number(row.get("bid")) is not None
        )
    except OSError:
        pass
    return summary


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def _runtime_scripts_dir(runtime_dir: Path) -> Path:
    runtime_dir = Path(runtime_dir)
    raw = str(os.environ.get("QG_MT5_SCRIPTS_DIR", "") or os.environ.get("QG_HFM_SCRIPTS_DIR", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    if runtime_dir.name.lower() == "files":
        return runtime_dir.parent / "Scripts"
    return runtime_dir / "Scripts"


def _runtime_experts_dir(runtime_dir: Path) -> Path:
    runtime_dir = Path(runtime_dir)
    raw = str(os.environ.get("QG_MT5_EXPERTS_DIR", "") or os.environ.get("QG_HFM_EXPERTS_DIR", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    if runtime_dir.name.lower() == "files":
        return runtime_dir.parent / "Experts"
    return runtime_dir / "Experts"


def _shell_quote(path: str) -> str:
    return "'" + str(path).replace("'", "'\"'\"'") + "'"


def _drive_c_root(runtime_dir: Path) -> Path | None:
    resolved = Path(runtime_dir).expanduser()
    parts = resolved.parts
    if "drive_c" not in parts:
        return None
    index = parts.index("drive_c")
    return Path(*parts[: index + 1])


def _runtime_wineprefix(runtime_dir: Path) -> Path | None:
    drive_c = _drive_c_root(runtime_dir)
    return drive_c.parent if drive_c else None


def _terminal_workdir(runtime_dir: Path) -> Path:
    if Path(runtime_dir).name.lower() == "files":
        return Path(runtime_dir).parents[1]
    drive_c = _drive_c_root(runtime_dir)
    if drive_c:
        return drive_c / "Program Files" / "MetaTrader 5"
    return Path(runtime_dir)


def _default_wine64_path() -> Path:
    return Path.home() / "Applications" / "MetaTrader 5.app" / "Contents" / "SharedSupport" / "wine" / "bin" / "wine64"


def _windows_config_path(path: Path, runtime_dir: Path) -> str:
    drive_c = _drive_c_root(runtime_dir)
    try:
        if drive_c and path.is_relative_to(drive_c):
            rel = path.relative_to(drive_c)
            return "C:\\" + "\\".join(rel.parts)
    except ValueError:
        pass
    return "Z:" + str(path).replace("/", "\\")


def _parse_ini_field(path: Path, field: str) -> str:
    source = _safe_read_text(path)
    prefix = field.lower() + "="
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix):
            return stripped.split("=", 1)[1].strip()
    return ""


def _looks_like_hfm_crypto_symbol(symbol: str) -> bool:
    value = str(symbol or "").strip().upper()
    if value.startswith("#"):
        value = value[1:]
    if len(value) > 6 and value.endswith(("R", "X", "C")) and value[-4:-1] == "USD":
        value = value[:-1]
    return value in {
        "AAVEUSD", "ADAUSD", "ALGOUSD", "APTUSD", "ATOMUSD", "AVAXUSD", "BCHUSD", "BNBUSD", "BTCUSD",
        "CRVUSD", "DOGEUSD", "DOTUSD", "ETCUSD", "ETHUSD", "FETUSD", "FILUSD", "FLOWUSD", "GALAUSD",
        "GRTUSD", "HBARUSD", "ICPUSD", "IMXUSD", "IOTAUSD", "LINKUSD", "LTCUSD", "NEARUSD", "SANDUSD",
        "SHIBUSD", "SOLUSD", "THETAUSD", "TRXUSD", "UNIUSD", "XLMUSD", "XRPUSD", "XTZUSD",
    }


def _account_seed_config(runtime_dir: Path) -> Path | None:
    drive_c = _drive_c_root(runtime_dir)
    candidates: list[Path] = []
    if drive_c:
        candidates.extend([
            drive_c / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini",
            drive_c / "qg" / "QuantGod_MT5_HFM_LivePilot_mac.ini",
            drive_c / "qg" / "QuantGod_MT5_HFM_Shadow_mac.ini",
        ])
    default_drive_c = Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c"
    candidates.extend([
        default_drive_c / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini",
        default_drive_c / "qg" / "QuantGod_MT5_HFM_LivePilot_mac.ini",
        default_drive_c / "qg" / "QuantGod_MT5_HFM_Shadow_mac.ini",
    ])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _startup_config_path(runtime_dir: Path, bundle_dir: Path) -> Path:
    drive_c = _drive_c_root(runtime_dir)
    if drive_c:
        return drive_c / "qg" / "QuantGod_HFMCryptoSpecExporter_startup.ini"
    return bundle_dir / "QuantGod_HFMCryptoSpecExporter_startup.ini"


def _startup_config_text(runtime_dir: Path) -> tuple[str, dict[str, Any]]:
    seed = _account_seed_config(runtime_dir)
    login = _parse_ini_field(seed, "Login") if seed else ""
    server = _parse_ini_field(seed, "Server") if seed else ""
    symbol = _parse_ini_field(seed, "Symbol") if seed else ""
    symbol = symbol if _looks_like_hfm_crypto_symbol(symbol) else "#BTCUSD"
    text = f"""[Common]
Login={login}
Server={server}
KeepPrivate=1

[Charts]
MaxBars=1000000

[Experts]
AllowLiveTrading=0
AllowDllImport=0
Enabled=1
Account=0
Profile=0

[StartUp]
Expert=QuantGod_HFMCryptoSpecExporterEA
Symbol={symbol}
Period=M1
ShutdownTerminal=1
"""
    return text, {
        "seedConfigPath": str(seed or ""),
        "loginPresent": bool(login),
        "serverPresent": bool(server),
        "startupSymbol": symbol,
    }


def _startup_command(runtime_dir: Path, config_path: Path) -> str:
    workdir = _terminal_workdir(runtime_dir)
    wineprefix = _runtime_wineprefix(runtime_dir)
    wine64 = _default_wine64_path()
    windows_config = _windows_config_path(config_path, runtime_dir)
    prefix = f"env WINEPREFIX={_shell_quote(str(wineprefix))} " if wineprefix else ""
    return (
        f"cd {_shell_quote(str(workdir))} && "
        f"{prefix}{_shell_quote(str(wine64))} terminal64.exe /portable "
        f"{_shell_quote('/config:' + windows_config)}"
    )


def _repo_python_command(runtime_dir: Path, args: str) -> str:
    repo_root = _repo_root()
    return f"cd {_shell_quote(str(repo_root))} && python3 {args} --runtime-dir {_shell_quote(str(runtime_dir))}"


def _post_run_refresh_commands(runtime_dir: Path) -> list[dict[str, Any]]:
    return [
        _command(
            "刷新 HFM crypto contract-spec-export",
            _repo_python_command(runtime_dir, "tools/run_hfm_crypto_cfd.py") + " contract-spec-export --write",
        ),
        _command(
            "刷新 HFM crypto execution-spec",
            _repo_python_command(runtime_dir, "tools/run_hfm_crypto_cfd.py") + " execution-spec --write",
        ),
        _command(
            "刷新 HFM crypto CopyRates profile",
            _repo_python_command(runtime_dir, "tools/run_hfm_crypto_cfd.py") + " rates-export --write --write-profile",
        ),
        _command(
            "刷新 HFM crypto simulation-profile",
            _repo_python_command(runtime_dir, "tools/run_hfm_crypto_cfd.py") + " simulation-profile --write",
        ),
        _command(
            "刷新 HFM crypto state",
            _repo_python_command(runtime_dir, "tools/run_hfm_crypto_cfd.py") + " build --write",
        ),
        _command(
            "刷新 live automation readiness",
            _repo_python_command(runtime_dir, "tools/run_live_automation_readiness.py") + " build --write --refresh-sources",
        ),
    ]


def _marker_rows(source: str) -> list[dict[str, Any]]:
    return [{"marker": marker, "present": marker in source} for marker in EXPORTER_MARKERS]


def _expert_marker_rows(source: str) -> list[dict[str, Any]]:
    return [{"marker": marker, "present": marker in source} for marker in EXPERT_EXPORTER_MARKERS]


def _forbidden_rows(source: str) -> list[dict[str, Any]]:
    return [{"marker": marker, "present": marker in source} for marker in FORBIDDEN_MARKERS]


def _command(label_zh: str, command: str) -> dict[str, Any]:
    return {
        "labelZh": label_zh,
        "command": command,
        "manualOnly": True,
        "executedByCodex": False,
    }


def build_hfm_crypto_standalone_exporter_bundle(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    generated_at = utc_now_iso()
    repo_script = _repo_root() / "MQL5" / "Scripts" / SCRIPT_FILE
    repo_expert = _repo_root() / "MQL5" / "Experts" / EXPERT_FILE
    source = _safe_read_text(repo_script)
    expert_source = _safe_read_text(repo_expert)
    marker_rows = _marker_rows(source)
    expert_marker_rows = _expert_marker_rows(expert_source)
    forbidden_rows = _forbidden_rows(source)
    expert_forbidden_rows = _forbidden_rows(expert_source)
    source_ready = bool(repo_script.exists() and source and all(row["present"] for row in marker_rows))
    expert_source_ready = bool(repo_expert.exists() and expert_source and all(row["present"] for row in expert_marker_rows))
    read_only = not any(row["present"] for row in forbidden_rows)
    expert_read_only = not any(row["present"] for row in expert_forbidden_rows)
    bundle_dir = standalone_exporter_bundle_dir(runtime_dir)
    staged_script = bundle_dir / SCRIPT_FILE
    staged_expert = bundle_dir / EXPERT_FILE
    manifest_path = standalone_exporter_bundle_path(runtime_dir)
    startup_config_path = _startup_config_path(runtime_dir, bundle_dir)
    startup_config_text, startup_config_source = _startup_config_text(runtime_dir)
    scripts_dir = _runtime_scripts_dir(runtime_dir)
    experts_dir = _runtime_experts_dir(runtime_dir)
    target_script = scripts_dir / SCRIPT_FILE
    target_compiled = scripts_dir / SCRIPT_FILE.replace(".mq5", ".ex5")
    target_expert = experts_dir / EXPERT_FILE
    target_expert_compiled = experts_dir / EXPERT_FILE.replace(".mq5", ".ex5")
    expected_specs_path = Path(runtime_dir) / "hfm_crypto" / EA_SYMBOL_SPECS_FILE
    expected_rates_path = Path(runtime_dir) / "hfm_crypto" / EA_RATES_EXPORT_FILE
    expected_runtime_probe_path = Path(runtime_dir) / "hfm_crypto" / EA_RUNTIME_PROBE_FILE
    output_summary = _output_summary(expected_specs_path)
    rates_output_summary = _rates_output_summary(expected_rates_path)
    runtime_probe_output_summary = _runtime_probe_output_summary(expected_runtime_probe_path)
    post_run_refresh_commands = _post_run_refresh_commands(runtime_dir)

    blockers: list[dict[str, Any]] = []
    if not repo_script.exists():
        blockers.append(_blocker("STANDALONE_EXPORTER_SCRIPT_MISSING", "仓库里没有独立 HFM crypto specs 导出脚本。", str(repo_script)))
    if not repo_expert.exists():
        blockers.append(_blocker("STANDALONE_EXPORTER_EXPERT_MISSING", "仓库里没有独立 HFM crypto specs 导出 EA。", str(repo_expert)))
    if repo_script.exists() and not source_ready:
        blockers.append(_blocker("STANDALONE_EXPORTER_MARKERS_MISSING", "独立导出脚本缺少 schema/安全/输出 marker。"))
    if repo_expert.exists() and not expert_source_ready:
        blockers.append(_blocker("STANDALONE_EXPORTER_EXPERT_MARKERS_MISSING", "独立导出 EA 缺少 schema/安全/输出 marker。"))
    if source and not read_only:
        blockers.append(_blocker("STANDALONE_EXPORTER_NOT_READ_ONLY", "独立导出脚本包含交易、选择 symbol 或读取请求文件的禁用调用。"))
    if expert_source and not expert_read_only:
        blockers.append(_blocker("STANDALONE_EXPORTER_EXPERT_NOT_READ_ONLY", "独立导出 EA 包含交易、选择 symbol 或读取请求文件的禁用调用。"))

    ready = source_ready and expert_source_ready and read_only and expert_read_only and not blockers
    if write and ready:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_script, staged_script)
        shutil.copy2(repo_expert, staged_expert)
        startup_config_path.parent.mkdir(parents=True, exist_ok=True)
        startup_config_path.write_text(startup_config_text, encoding="utf-8")

    staged_exists = staged_script.exists() and staged_script.is_file()
    staged_expert_exists = staged_expert.exists() and staged_expert.is_file()
    startup_config_exists = startup_config_path.exists() and startup_config_path.is_file()
    target_exists = target_script.exists() and target_script.is_file()
    target_compiled_exists = target_compiled.exists() and target_compiled.is_file()
    target_expert_exists = target_expert.exists() and target_expert.is_file()
    target_expert_compiled_exists = target_expert_compiled.exists() and target_expert_compiled.is_file()
    repo_hash = _sha256(repo_script) if repo_script.exists() and repo_script.is_file() else ""
    repo_expert_hash = _sha256(repo_expert) if repo_expert.exists() and repo_expert.is_file() else ""
    staged_hash = _sha256(staged_script) if staged_exists else ""
    staged_expert_hash = _sha256(staged_expert) if staged_expert_exists else ""
    target_hash = _sha256(target_script) if target_exists else ""
    target_expert_hash = _sha256(target_expert) if target_expert_exists else ""
    target_installed_matches_bundle = bool(staged_hash and target_hash and staged_hash == target_hash)
    target_expert_installed_matches_bundle = bool(staged_expert_hash and target_expert_hash and staged_expert_hash == target_expert_hash)
    script_installed_and_compiled = bool(target_installed_matches_bundle and target_compiled_exists)
    expert_installed_and_compiled = bool(target_expert_installed_matches_bundle and target_expert_compiled_exists)
    installed_and_compiled = bool(script_installed_and_compiled or expert_installed_and_compiled)
    specs_output_detected = output_summary["expectedSpecsRowCount"] > 0
    runtime_probe_detected = bool(
        runtime_probe_output_summary["expectedRuntimeProbeReadable"]
        and runtime_probe_output_summary["expectedRuntimeProbeSymbolCount"] > 0
    )
    runtime_probe_tick_detected = runtime_probe_output_summary["expectedRuntimeProbeLiveTickCount"] > 0
    runtime_probe_missing_after_specs = bool(specs_output_detected and not runtime_probe_detected)
    status = "READY_FOR_MANUAL_STANDALONE_MT5_SPEC_EXPORT"
    status_zh = "可人工安装/运行独立只读 crypto specs 导出脚本/EA"
    if expert_installed_and_compiled:
        status = "READY_TO_RUN_STANDALONE_MT5_SPEC_EXPORT"
        status_zh = "独立只读 crypto specs 导出 EA 已安装并编译，等待用 Expert 启动"
    elif installed_and_compiled:
        status = "READY_TO_RUN_STANDALONE_MT5_SPEC_EXPORT"
        status_zh = "独立只读 crypto specs 导出脚本已安装并编译，等待在 MT5 运行"
    if runtime_probe_missing_after_specs and not expert_installed_and_compiled:
        status = "WAITING_STANDALONE_MT5_RUNTIME_PROBE_INSTALL"
        status_zh = "等待安装/编译带 runtime probe 的只读 HFM crypto exporter EA"
    elif runtime_probe_missing_after_specs:
        status = "READY_TO_RUN_STANDALONE_MT5_RUNTIME_PROBE"
        status_zh = "specs 已检测到，等待用新版只读 EA 生成 #BTCUSD runtime probe"
    elif specs_output_detected:
        status = "STANDALONE_MT5_SPEC_EXPORT_OUTPUT_DETECTED"
        status_zh = "已检测到独立只读 crypto specs 输出，等待刷新规格审查"
    elif not ready:
        status = "WAITING_STANDALONE_MT5_SPEC_EXPORTER_INPUTS"
        status_zh = "等待独立只读 crypto specs 导出脚本输入"

    payload = {
        "ok": True,
        "schema": STANDALONE_EXPORTER_BUNDLE_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "standaloneExporterReady": ready,
        "bundleReadyForManualScriptInstall": ready,
        "targetInstalledAndCompiled": installed_and_compiled,
        "targetExpertInstalledAndCompiled": expert_installed_and_compiled,
        "targetScriptInstalledAndCompiled": script_installed_and_compiled,
        "runtimeProbeDetected": runtime_probe_detected,
        "runtimeProbeMissingAfterSpecs": runtime_probe_missing_after_specs,
        "runtimeProbeTickDetected": runtime_probe_tick_detected,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "installedFilesMutated": False,
        "copyIntoMt5Allowed": False,
        "compileAttempted": False,
        "scriptRunAttempted": False,
        "brokerCallsMade": False,
        "source": {
            "repoScriptPath": str(repo_script),
            "repoScriptExists": repo_script.exists(),
            "repoScriptSha256": repo_hash,
            "markerChecks": marker_rows,
            "forbiddenMarkerChecks": forbidden_rows,
            "sourceReady": source_ready,
            "readOnly": read_only,
            "repoExpertPath": str(repo_expert),
            "repoExpertExists": repo_expert.exists(),
            "repoExpertSha256": repo_expert_hash,
            "expertMarkerChecks": expert_marker_rows,
            "expertForbiddenMarkerChecks": expert_forbidden_rows,
            "expertSourceReady": expert_source_ready,
            "expertReadOnly": expert_read_only,
        },
        "bundle": {
            "directory": str(bundle_dir),
            "manifestPath": str(manifest_path),
            "stagedScriptPath": str(staged_script),
            "stagedScriptExists": staged_exists,
            "stagedScriptSha256": staged_hash,
            "sourceHashMatchesBundle": bool(repo_hash and staged_hash and repo_hash == staged_hash),
            "stagedExpertPath": str(staged_expert),
            "stagedExpertExists": staged_expert_exists,
            "stagedExpertSha256": staged_expert_hash,
            "expertSourceHashMatchesBundle": bool(repo_expert_hash and staged_expert_hash and repo_expert_hash == staged_expert_hash),
            "bundleWritten": bool(write and ready),
        },
        "startupConfig": {
            "configPath": str(startup_config_path),
            "configExists": startup_config_exists,
            "configWritten": bool(write and ready),
            "configSource": startup_config_source,
            "terminalWorkingDirectory": str(_terminal_workdir(runtime_dir)),
            "winePrefix": str(_runtime_wineprefix(runtime_dir) or ""),
            "wine64Path": str(_default_wine64_path()),
            "windowsConfigPath": _windows_config_path(startup_config_path, runtime_dir),
            "command": _startup_command(runtime_dir, startup_config_path),
            "manualOnly": True,
            "executedByCodex": False,
            "scriptRunAttempted": False,
            "allowLiveTrading": False,
            "shutdownTerminal": True,
            "preferredStartupMode": "Expert",
            "expertName": "QuantGod_HFMCryptoSpecExporterEA",
            "scriptFallbackName": "QuantGod_HFMCryptoSpecExporter",
            "reasonZh": "用独立 MT5 启动配置运行只读导出 EA；不会替换当前实盘 EA，不允许 live trading，运行后请求自动关闭终端。",
        },
        "postRunRefreshPlan": {
            "manualOnly": True,
            "executedByCodex": False,
            "scriptRunAttempted": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "expectedSpecsPath": str(expected_specs_path),
            "expectedRatesPath": str(expected_rates_path),
            "expectedRuntimeProbePath": str(expected_runtime_probe_path),
            "refreshCommands": post_run_refresh_commands,
            "reasonZh": "只在 specs/rates/runtime-probe JSON 出现后刷新只读审查产物；不会触发 MT5 下单或 live preset mutation。",
        },
        "target": {
            "mt5ScriptsDir": str(scripts_dir),
            "mt5ScriptsDirExists": scripts_dir.exists(),
            "targetScriptPath": str(target_script),
            "targetScriptExists": target_exists,
            "targetScriptSha256": target_hash,
            "targetInstalledMatchesBundle": target_installed_matches_bundle,
            "targetCompiledPath": str(target_compiled),
            "targetCompiledExists": target_compiled_exists,
            "mt5ExpertsDir": str(experts_dir),
            "mt5ExpertsDirExists": experts_dir.exists(),
            "targetExpertPath": str(target_expert),
            "targetExpertExists": target_expert_exists,
            "targetExpertSha256": target_expert_hash,
            "targetExpertInstalledMatchesBundle": target_expert_installed_matches_bundle,
            "targetExpertCompiledPath": str(target_expert_compiled),
            "targetExpertCompiledExists": target_expert_compiled_exists,
        },
        "output": {
            "expectedSpecsPath": str(expected_specs_path),
            "expectedSpecsFile": EA_SYMBOL_SPECS_FILE,
            "sourceFormat": "EA_SYMBOL_SPECS_JSON",
            **output_summary,
            "expectedRatesPath": str(expected_rates_path),
            "expectedRatesFile": EA_RATES_EXPORT_FILE,
            **rates_output_summary,
            "expectedRuntimeProbePath": str(expected_runtime_probe_path),
            "expectedRuntimeProbeFile": EA_RUNTIME_PROBE_FILE,
            "sourceRuntimeProbeFormat": "EA_RUNTIME_PROBE_JSON",
            **runtime_probe_output_summary,
        },
        "operatorChecklist": [
            {
                "id": "copy_script",
                "labelZh": "人工复制 staged 脚本到 MT5 MQL5/Scripts 目录",
                "required": True,
                "automated": False,
            },
            {
                "id": "copy_expert",
                "labelZh": "人工复制 staged 只读导出 EA 到 MT5 MQL5/Experts 目录",
                "required": True,
                "automated": False,
            },
            {
                "id": "compile_script",
                "labelZh": "在 MetaEditor 编译 QuantGod_HFMCryptoSpecExporter.mq5",
                "required": True,
                "automated": False,
            },
            {
                "id": "compile_expert",
                "labelZh": "在 MetaEditor 编译 QuantGod_HFMCryptoSpecExporterEA.mq5",
                "required": True,
                "automated": False,
            },
            {
                "id": "run_script_once",
                "labelZh": "用 Expert 启动只读导出 EA，或在 MT5 Navigator/Scripts 中运行一次脚本，生成 specs、CopyRates 与 runtime probe JSON",
                "required": True,
                "automated": False,
            },
            {
                "id": "refresh_review",
                "labelZh": "刷新 contract-spec-export、execution-spec 和 HFM Crypto 状态",
                "required": True,
                "automated": False,
            },
        ],
        "commandsForHumanReview": [
            _command("创建 MT5 Scripts 目录", f"mkdir -p {_shell_quote(str(scripts_dir))}"),
            _command("创建 MT5 Experts 目录", f"mkdir -p {_shell_quote(str(experts_dir))}"),
            _command("复制独立 specs 导出脚本", f"cp -p {_shell_quote(str(staged_script))} {_shell_quote(str(target_script))}"),
            _command("复制独立 specs 导出 EA", f"cp -p {_shell_quote(str(staged_expert))} {_shell_quote(str(target_expert))}"),
            _command("运行独立只读 specs Expert 启动配置", _startup_command(runtime_dir, startup_config_path)),
            *post_run_refresh_commands,
        ],
        "blockers": blockers,
        "nextRequiredActionZh": (
            "staged EA 已包含 runtime probe；当前 MT5 Experts 里的 EA 不是最新版或尚未编译。请人工复制/编译/运行 QuantGod_HFMCryptoSpecExporterEA，生成 QuantGod_HFMCryptoRuntimeProbe.json。"
            if runtime_probe_missing_after_specs and not expert_installed_and_compiled
            else
            "用 Expert 启动新版 QuantGod_HFMCryptoSpecExporterEA，生成 QuantGod_HFMCryptoRuntimeProbe.json 后再刷新 HFM Crypto 状态。"
            if runtime_probe_missing_after_specs
            else
            "刷新 contract-spec-export、execution-spec 和 HFM Crypto 状态，把 specs 输出转成可审查合约规格输入。"
            if specs_output_detected
            else
            "用 Expert 启动 QuantGod_HFMCryptoSpecExporterEA；它只写 specs/rates JSON，不替换当前实盘 EA。"
            if expert_installed_and_compiled
            else "在 MT5 Navigator/Scripts 中运行一次 QuantGod_HFMCryptoSpecExporter；它只写 specs/rates JSON，不替换当前实盘 EA。"
            if script_installed_and_compiled
            else "人工复制并编译独立脚本/EA，然后运行一次；它只写 specs/rates JSON，不替换当前实盘 EA。"
            if ready
            else "先补齐独立导出脚本及其只读安全 marker。"
        ),
        "safety": {
            **SAFETY,
            "mutatesMt5": False,
            "installedFilesMutated": False,
            "copyIntoMt5Allowed": False,
            "compileAttempted": False,
            "scriptRunAttempted": False,
            "brokerCallsMade": False,
            "symbolSelectAllowed": False,
        },
    }
    if write:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_standalone_exporter_bundle(runtime_dir: Path) -> dict[str, Any]:
    return build_hfm_crypto_standalone_exporter_bundle(Path(runtime_dir), write=False)
