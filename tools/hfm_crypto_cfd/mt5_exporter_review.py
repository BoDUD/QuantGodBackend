from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .schema import (
    EA_RUNTIME_PROBE_FILE,
    EA_SYMBOL_SPECS_FILE,
    MT5_EXPORTER_REVIEW_SCHEMA_VERSION,
    SAFETY,
    mt5_exporter_review_path,
    utc_now_iso,
)

try:
    from tools.mt5_readonly_bridge import read_ea_dashboard_snapshot, runtime_dir_candidates
except ModuleNotFoundError:  # pragma: no cover
    from mt5_readonly_bridge import read_ea_dashboard_snapshot, runtime_dir_candidates


SOURCE_FILE = "QuantGod_MultiStrategy.mq5"
BINARY_FILE = "QuantGod_MultiStrategy.ex5"
EXPORTER_MARKERS = (
    "EnableHfmCryptoSpecExporter",
    "HFM Crypto Symbol Spec Export BEGIN",
    "BuildHfmCryptoSymbolSpecsJson",
    "BuildHfmCryptoRuntimeProbeJson",
    "hfmCryptoSymbolSpecs",
    "hfmCryptoRuntimeProbe",
    EA_SYMBOL_SPECS_FILE,
    EA_RUNTIME_PROBE_FILE,
)
FORBIDDEN_EXPORT_MARKERS = (
    "Order" + "Send(",
    "Order" + "SendAsync(",
    "TRADE_ACTION_" + "DEAL",
    "Position" + "Close(",
    "Symbol" + "Select(",
)


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_expert_dirs(runtime_dir: Path | None) -> list[Path]:
    if not runtime_dir:
        return []
    runtime = Path(runtime_dir).expanduser()
    candidates: list[Path] = []
    if runtime.name.lower() == "files":
        candidates.append(runtime.parent / "Experts")
    candidates.append(runtime / "Experts")
    return candidates


def _candidate_expert_dirs(runtime_dir: Path | None = None) -> list[Path]:
    raw_values = [
        os.environ.get("QG_MT5_EXPERTS_DIR", ""),
        os.environ.get("QG_HFM_EXPERTS_DIR", ""),
    ]
    candidates: list[Path] = _runtime_expert_dirs(runtime_dir)
    for raw in raw_values:
        value = str(raw or "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    for files_dir in runtime_dir_candidates():
        files_path = Path(files_dir).expanduser()
        if files_path.name.lower() == "files":
            candidates.append(files_path.parent / "Experts")
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _latest_existing(paths: list[Path]) -> Path | None:
    found: list[tuple[float, Path]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if not found:
        return None
    return sorted(found, key=lambda item: item[0], reverse=True)[0][1]


def _preferred_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def _installed_source_path(runtime_dir: Path) -> Path | None:
    return _preferred_existing([directory / SOURCE_FILE for directory in _candidate_expert_dirs(runtime_dir)])


def _installed_binary_path(runtime_dir: Path) -> Path | None:
    return _preferred_existing([directory / BINARY_FILE for directory in _candidate_expert_dirs(runtime_dir)])


def _marker_rows(source: str) -> list[dict[str, Any]]:
    return [{"marker": marker, "present": marker in source} for marker in EXPORTER_MARKERS]


def _has_exporter(source: str) -> bool:
    return bool(source) and all(row["present"] for row in _marker_rows(source))


def _export_block(source: str) -> str:
    begin = "// HFM Crypto Symbol Spec Export BEGIN"
    end = "// HFM Crypto Symbol Spec Export END"
    if begin not in source or end not in source:
        return ""
    return source.split(begin, 1)[1].split(end, 1)[0]


def _forbidden_rows(source: str) -> list[dict[str, Any]]:
    block = _export_block(source)
    return [{"marker": marker, "present": marker in block} for marker in FORBIDDEN_EXPORT_MARKERS]


def _read_dashboard_from_runtime(runtime_dir: Path) -> tuple[dict[str, Any] | None, Path | None, dict[str, Any] | None]:
    candidates = [Path(runtime_dir) / "QuantGod_Dashboard.json"]
    candidates.extend(directory / "QuantGod_Dashboard.json" for directory in runtime_dir_candidates())
    for file_path in candidates:
        if not file_path.exists() or not file_path.is_file():
            continue
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload, file_path, None
        except Exception as exc:
            return None, file_path, {"path": str(file_path), "error": str(exc)}
    return read_ea_dashboard_snapshot()


def _dashboard_specs_summary(runtime_dir: Path) -> dict[str, Any]:
    payload, path, error = _read_dashboard_from_runtime(runtime_dir)
    specs = payload.get("hfmCryptoSymbolSpecs") if isinstance(payload, dict) else None
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except Exception:
            specs = None
    symbols = specs.get("symbols") if isinstance(specs, dict) else []
    if not isinstance(symbols, list):
        symbols = []
    symbol_count = specs.get("symbolCount") if isinstance(specs, dict) else None
    if not isinstance(symbol_count, int):
        symbol_count = len(symbols)
    return {
        "found": bool(payload),
        "path": str(path) if path else "",
        "error": error or {},
        "dashboardBuild": payload.get("build", "") if isinstance(payload, dict) else "",
        "dashboardTimestamp": payload.get("timestamp", "") if isinstance(payload, dict) else "",
        "hasHfmCryptoSymbolSpecs": isinstance(specs, dict),
        "hfmCryptoSymbolCount": symbol_count,
        "hfmCryptoSymbols": [
            str(row.get("brokerSymbol") or row.get("symbol") or row.get("name") or "")
            for row in symbols
            if isinstance(row, dict)
        ],
    }


def _ea_symbol_specs_file(runtime_dir: Path) -> Path | None:
    scoped_candidates = [
        Path(runtime_dir) / "hfm_crypto" / EA_SYMBOL_SPECS_FILE,
        Path(runtime_dir) / EA_SYMBOL_SPECS_FILE,
        Path(runtime_dir) / "mac_import" / "mt5_files_snapshot" / EA_SYMBOL_SPECS_FILE,
    ]
    scoped = _preferred_existing(scoped_candidates)
    if scoped:
        return scoped
    candidates = [directory / EA_SYMBOL_SPECS_FILE for directory in runtime_dir_candidates()]
    return _latest_existing(candidates)


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def build_hfm_crypto_mt5_exporter_review(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    repo_source_path = _repo_root() / "MQL5" / "Experts" / SOURCE_FILE
    repo_source = _safe_read_text(repo_source_path)
    installed_source_path = _installed_source_path(runtime_dir)
    installed_binary_path = _installed_binary_path(runtime_dir)
    installed_source = _safe_read_text(installed_source_path) if installed_source_path else ""
    repo_has_exporter = _has_exporter(repo_source)
    installed_has_exporter = _has_exporter(installed_source)
    installed_forbidden = _forbidden_rows(installed_source)
    dashboard = _dashboard_specs_summary(runtime_dir)
    ea_specs_path = _ea_symbol_specs_file(runtime_dir)
    ea_specs_present = bool(ea_specs_path)
    export_available = bool(
        ea_specs_present
        or (dashboard["hasHfmCryptoSymbolSpecs"] and int(dashboard.get("hfmCryptoSymbolCount") or 0) > 0)
    )
    upgrade_required = bool(repo_has_exporter and not installed_has_exporter)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not repo_has_exporter:
        blockers.append(_blocker("REPO_EA_EXPORTER_MISSING", "仓库里的 EA 源码缺少 HFM crypto spec exporter。", str(repo_source_path)))
    if not installed_source_path:
        row = _blocker("INSTALLED_MT5_EA_SOURCE_MISSING", "MT5 Experts 目录里没有找到 QuantGod_MultiStrategy.mq5。")
        (warnings if export_available else blockers).append(row)
    elif not installed_has_exporter:
        row = _blocker(
            "INSTALLED_MT5_EA_EXPORTER_MISSING",
            "当前 MT5 安装目录里的 EA 源码还没有 hfmCryptoSymbolSpecs exporter；已由独立只读 exporter/specs 输出接管证据。",
            str(installed_source_path),
        )
        (warnings if export_available else blockers).append(row)
    if installed_has_exporter and any(row["present"] for row in installed_forbidden):
        blockers.append(_blocker("INSTALLED_MT5_EXPORTER_NOT_READ_ONLY", "安装目录里的 exporter block 出现了不允许的交易/选择 symbol 调用。"))
    if installed_has_exporter and not export_available:
        blockers.append(_blocker("HFM_CRYPTO_SPECS_NOT_EXPORTED_YET", f"EA 尚未写出 {EA_SYMBOL_SPECS_FILE}，dashboard 也没有有效 hfmCryptoSymbolSpecs。"))

    if export_available:
        status = "HFM_CRYPTO_MT5_EXPORT_AVAILABLE"
        status_zh = "HFM crypto MT5 规格导出已可用"
    elif upgrade_required:
        status = "WAITING_MT5_EA_EXPORTER_UPGRADE"
        status_zh = "等待 MT5 EA 升级到包含 crypto exporter 的版本"
    else:
        status = "WAITING_HFM_CRYPTO_SPEC_EXPORT"
        status_zh = "等待 HFM crypto 规格导出"

    payload = {
        "ok": True,
        "schema": MT5_EXPORTER_REVIEW_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "exporterReadyForEvidenceIntake": export_available,
        "mt5EaUpgradeRequired": upgrade_required,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "installedFilesMutated": False,
        "repoEaSource": {
            "path": str(repo_source_path),
            "exists": repo_source_path.exists(),
            "hasExporter": repo_has_exporter,
            "markerChecks": _marker_rows(repo_source),
            "forbiddenMarkerChecks": _forbidden_rows(repo_source),
        },
        "installedMt5Ea": {
            "sourcePath": str(installed_source_path) if installed_source_path else "",
            "sourceExists": bool(installed_source_path),
            "sourceHasExporter": installed_has_exporter,
            "binaryPath": str(installed_binary_path) if installed_binary_path else "",
            "binaryExists": bool(installed_binary_path),
            "markerChecks": _marker_rows(installed_source),
            "forbiddenMarkerChecks": installed_forbidden,
        },
        "dashboard": dashboard,
        "eaSymbolSpecsFile": {
            "path": str(ea_specs_path) if ea_specs_path else "",
            "exists": ea_specs_present,
        },
        "manualUpgradePlan": [
            {
                "step": "copy_source",
                "labelZh": "把仓库里的 QuantGod_MultiStrategy.mq5 复制到 MT5 Experts 目录",
                "source": str(repo_source_path),
                "target": str(installed_source_path) if installed_source_path else "MT5/MQL5/Experts/QuantGod_MultiStrategy.mq5",
                "automatic": False,
            },
            {
                "step": "compile_in_metaeditor",
                "labelZh": "在 MetaEditor 编译 QuantGod_MultiStrategy.mq5，生成新的 .ex5",
                "automatic": False,
            },
            {
                "step": "reload_ea",
                "labelZh": "在 MT5 图表上重新加载 EA，并确认 preset 中 EnableHfmCryptoSpecExporter=true",
                "automatic": False,
            },
            {
                "step": "refresh_specs",
                "labelZh": f"等待 EA 写出 {EA_SYMBOL_SPECS_FILE} 或 dashboard.hfmCryptoSymbolSpecs，然后运行 contract-spec-export",
                "automatic": False,
            },
        ],
        "blockers": blockers,
        "warnings": warnings,
        "nextRequiredActionZh": (
            "HFM crypto 规格已可进入 contract-spec-export。"
            if export_available
            else "先升级并重新加载 MT5 EA，让 dashboard 带出 hfmCryptoSymbolSpecs 或写出 QuantGod_HFMCryptoSymbolSpecs.json。"
        ),
        "safety": {
            **SAFETY,
            "mutatesMt5": False,
            "installedFilesMutated": False,
            "symbolSelectAllowed": False,
        },
    }
    if write:
        out = mt5_exporter_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_mt5_exporter_review(runtime_dir: Path) -> dict[str, Any]:
    path = mt5_exporter_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
        except Exception:
            pass
    return build_hfm_crypto_mt5_exporter_review(Path(runtime_dir), write=False)
