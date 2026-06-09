from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .schema import (
    CONTRACT_SPEC_EXPORT_SCHEMA_VERSION,
    EA_SYMBOL_SPECS_FILE,
    HFM_CRYPTO_USD_CANONICALS,
    SAFETY,
    contract_spec_export_path,
    utc_now_iso,
)

try:
    from tools.mt5_symbol_registry import normalize_symbol_row
except ModuleNotFoundError:  # pragma: no cover
    from mt5_symbol_registry import normalize_symbol_row

try:
    from tools.mt5_readonly_bridge import runtime_dir_candidates
except ModuleNotFoundError:  # pragma: no cover
    from mt5_readonly_bridge import runtime_dir_candidates


REQUIRED_CONTRACT_SPEC_FIELDS = (
    "contractSize",
    "tickSize",
    "tickValue",
    "minLot",
    "lotStep",
    "maxLot",
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _clean_text(value).lower()
    if text in {"true", "1", "yes", "y", "enabled", "on", "selected", "visible"}:
        return True
    if text in {"false", "0", "no", "n", "disabled", "off"}:
        return False
    return None


def _safe_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _read_json(path: Path) -> dict[str, Any] | list[Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("mappings", "symbols", "rows", "items", "contracts", "specs"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            return [dict(row) for row in value["items"] if isinstance(row, dict)]
    if any(key in payload for key in ("brokerSymbol", "symbol", "name", "contractSize", "tradeContractSize")):
        return [dict(payload)]
    return []


def _load_registry_rows(path: str) -> tuple[list[dict[str, Any]], str, str, dict[str, Any] | None]:
    raw_path = _clean_text(path)
    if not raw_path:
        return [], "", "NO_PATH", None
    source_path = Path(raw_path).expanduser()
    if not source_path.exists() or not source_path.is_file():
        return [], str(source_path), "MISSING", None
    try:
        payload = _read_json(source_path)
    except Exception as exc:
        return [], str(source_path), "UNREADABLE", {"error": str(exc)}
    rows = _extract_rows(payload)
    metadata = payload if isinstance(payload, dict) else {}
    return rows, str(source_path), "JSON", metadata


def _broker_symbol_diagnostics(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {
            "brokerSymbolTotalAll": 0,
            "brokerSymbolTotalMarketWatch": 0,
            "brokerCryptoLikeCountAll": 0,
            "brokerCryptoLikeCountMarketWatch": 0,
            "brokerSymbolSampleCount": 0,
            "brokerSymbolSamples": [],
        }
    samples = metadata.get("brokerSymbolSamples")
    if not isinstance(samples, list):
        samples = []
    return {
        "brokerSymbolTotalAll": _safe_int(metadata.get("brokerSymbolTotalAll")),
        "brokerSymbolTotalMarketWatch": _safe_int(metadata.get("brokerSymbolTotalMarketWatch")),
        "brokerCryptoLikeCountAll": _safe_int(metadata.get("brokerCryptoLikeCountAll")),
        "brokerCryptoLikeCountMarketWatch": _safe_int(metadata.get("brokerCryptoLikeCountMarketWatch")),
        "brokerSymbolSampleCount": _safe_int(metadata.get("brokerSymbolSampleCount")),
        "brokerSymbolSamples": [dict(item) for item in samples if isinstance(item, dict)][:160],
    }


def _load_dashboard_hfm_crypto_specs(path: Path) -> tuple[list[dict[str, Any]], str, str, dict[str, Any] | None]:
    try:
        payload = _read_json(path)
    except Exception as exc:
        return [], str(path), "EA_DASHBOARD_UNREADABLE", {"error": str(exc)}
    if not isinstance(payload, dict):
        return [], str(path), "EA_DASHBOARD_EMPTY", {"error": "dashboard payload is not an object"}
    specs = payload.get("hfmCryptoSymbolSpecs")
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except Exception as exc:
            return [], str(path), "EA_DASHBOARD_UNREADABLE", {"error": str(exc)}
    if not isinstance(specs, dict):
        return [], str(path), "EA_DASHBOARD_EMPTY", {
            "schema": payload.get("schema", ""),
            "status": payload.get("status", ""),
            "summary": {},
        }
    rows = _extract_rows(specs)
    metadata = {
        **specs,
        "dashboardPath": str(path),
        "dashboardBuild": payload.get("build", ""),
        "dashboardTimestamp": payload.get("timestamp", ""),
    }
    return rows, str(path), "EA_DASHBOARD_HFM_CRYPTO_SYMBOL_SPECS", metadata


def _find_latest_ea_symbol_specs(runtime_dir: Path) -> Path | None:
    candidates = [
        Path(runtime_dir) / "hfm_crypto" / EA_SYMBOL_SPECS_FILE,
        Path(runtime_dir) / EA_SYMBOL_SPECS_FILE,
        Path(runtime_dir) / "mac_import" / "mt5_files_snapshot" / EA_SYMBOL_SPECS_FILE,
    ]
    candidates.extend(directory / EA_SYMBOL_SPECS_FILE for directory in runtime_dir_candidates())

    seen: set[str] = set()
    existing: list[tuple[float, Path]] = []
    for candidate in candidates:
        key = str(candidate.expanduser())
        if key in seen:
            continue
        seen.add(key)
        path = candidate.expanduser()
        if path.exists() and path.is_file():
            try:
                existing.append((path.stat().st_mtime, path))
            except OSError:
                continue
    if not existing:
        return None
    return sorted(existing, key=lambda item: item[0], reverse=True)[0][1]


def _find_latest_ea_dashboard(runtime_dir: Path) -> Path | None:
    candidates = [
        Path(runtime_dir) / "QuantGod_Dashboard.json",
        Path(runtime_dir) / "mac_import" / "mt5_files_snapshot" / "QuantGod_Dashboard.json",
    ]
    candidates.extend(directory / "QuantGod_Dashboard.json" for directory in runtime_dir_candidates())

    seen: set[str] = set()
    existing: list[tuple[float, Path]] = []
    for candidate in candidates:
        key = str(candidate.expanduser())
        if key in seen:
            continue
        seen.add(key)
        path = candidate.expanduser()
        if path.exists() and path.is_file():
            try:
                existing.append((path.stat().st_mtime, path))
            except OSError:
                continue
    if not existing:
        return None
    return sorted(existing, key=lambda item: item[0], reverse=True)[0][1]


def _run_live_mt5_registry(*, terminal_path: str = "", group: str = "*Crypto*", limit: int = 500) -> tuple[list[dict[str, Any]], str, str, dict[str, Any] | None]:
    script = Path(__file__).resolve().parents[1] / "mt5_symbol_registry.py"
    command = [
        sys.executable,
        str(script),
        "--endpoint",
        "registry",
        "--group",
        group,
        "--limit",
        str(limit),
    ]
    if terminal_path:
        command.extend(["--terminal-path", terminal_path])
    try:
        completed = subprocess.run(
            command,
            cwd=str(script.parents[1]),
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except Exception as exc:
        return [], "live_mt5_symbol_registry", "LIVE_MT5_UNAVAILABLE", {"error": str(exc), "command": command}
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception as exc:
        return [], "live_mt5_symbol_registry", "LIVE_MT5_UNREADABLE", {
            "error": str(exc),
            "exitCode": completed.returncode,
            "stderr": completed.stderr,
        }
    if not isinstance(payload, dict) or payload.get("ok") is False:
        return [], "live_mt5_symbol_registry", "LIVE_MT5_UNAVAILABLE", {
            "payload": payload,
            "exitCode": completed.returncode,
            "stderr": completed.stderr,
        }
    return _extract_rows(payload), "live_mt5_symbol_registry", "LIVE_MT5", payload


def _normalize_contract_row(row: dict[str, Any]) -> dict[str, Any]:
    broker_symbol = _first_value(row, ("brokerSymbol", "symbol", "name", "Symbol", "Name"))
    normalized = normalize_symbol_row({
        **row,
        "name": broker_symbol,
        "description": _first_value(row, ("description", "Description")),
        "path": _first_value(row, ("path", "Path", "category", "assetClass")) or "Crypto CFD",
    })
    canonical = _first_value(row, ("canonicalSymbol", "canonical", "CanonicalSymbol")) or normalized.get("canonicalSymbol")
    return {
        "brokerSymbol": _clean_text(broker_symbol),
        "canonicalSymbol": _clean_text(canonical),
        "description": _clean_text(_first_value(row, ("description", "Description")) or normalized.get("description")),
        "path": _clean_text(_first_value(row, ("path", "Path", "category", "assetClass")) or normalized.get("path")),
        "tradeMode": _clean_text(_first_value(row, ("tradeMode", "TradeMode", "trade_mode", "mode"))),
        "calcMode": _clean_text(_first_value(row, ("calcMode", "CalcMode", "tradeCalcMode", "trade_calc_mode"))),
        "contractSize": _safe_float(_first_value(row, ("contractSize", "ContractSize", "tradeContractSize", "trade_contract_size"))),
        "tickSize": _safe_float(_first_value(row, ("tickSize", "TickSize", "tradeTickSize", "trade_tick_size", "point", "Point"))),
        "tickValue": _safe_float(_first_value(row, ("tickValue", "TickValue", "tradeTickValue", "trade_tick_value"))),
        "minLot": _safe_float(_first_value(row, ("minLot", "MinLot", "volumeMin", "volume_min", "volume_min_lots"))),
        "lotStep": _safe_float(_first_value(row, ("lotStep", "LotStep", "volumeStep", "volume_step", "volume_step_lots"))),
        "maxLot": _safe_float(_first_value(row, ("maxLot", "MaxLot", "volumeMax", "volume_max", "volume_max_lots"))),
        "spreadMaxPips": _safe_float(_first_value(row, ("spreadMaxPips", "maxSpreadPips", "spreadPips", "spread"))),
        "maxSlippagePips": _safe_float(_first_value(row, ("maxSlippagePips", "slippagePips"))),
        "marginInitial": _safe_float(_first_value(row, ("marginInitial", "initialMargin", "margin_initial"))),
        "swapLong": _safe_float(_first_value(row, ("swapLong", "SwapLong", "longSwap", "swap_long"))),
        "swapShort": _safe_float(_first_value(row, ("swapShort", "SwapShort", "shortSwap", "swap_short"))),
        "tradeEnabled": _safe_bool(_first_value(row, ("tradeEnabled", "enabled", "visible", "selected"))),
        "sourceMarketType": normalized.get("marketType"),
        "sourceMappingReason": normalized.get("mappingReason"),
    }


def _is_crypto_row(row: dict[str, Any]) -> bool:
    return row.get("sourceMarketType") == "crypto_cfd" or str(row.get("canonicalSymbol") or "").upper() in set(HFM_CRYPTO_USD_CANONICALS)


def _row_blockers(row: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not row.get("brokerSymbol") or not row.get("canonicalSymbol"):
        blockers.append({
            "code": "HFM_CONTRACT_SPEC_EXPORT_SYMBOL_MISSING",
            "reasonZh": "MT5 symbol registry 行缺少 brokerSymbol 或 canonicalSymbol。",
        })
    for field in REQUIRED_CONTRACT_SPEC_FIELDS:
        value = row.get(field)
        if value is None or value <= 0:
            blockers.append({
                "code": "HFM_CONTRACT_SPEC_EXPORT_FIELD_MISSING",
                "reasonZh": f"MT5 symbol registry 行缺少有效 {field}，不能进入合约规格审查。",
                "field": field,
                "value": value,
            })
    return blockers


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_clean_text(row.get("canonicalSymbol")), _clean_text(row.get("brokerSymbol")))
        unique[key] = row
    return list(unique.values())


def build_hfm_crypto_contract_spec_export(
    runtime_dir: Path,
    *,
    symbol_registry_json: str = "",
    live_mt5: bool = False,
    terminal_path: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    auto_discovered_ea_export = False
    auto_discovered_ea_dashboard = False
    ea_symbol_specs_json_path = ""
    ea_dashboard_json_path = ""
    if symbol_registry_json:
        raw_rows, resolved_path, source_format, metadata = _load_registry_rows(symbol_registry_json)
    elif live_mt5:
        raw_rows, resolved_path, source_format, metadata = _run_live_mt5_registry(terminal_path=terminal_path)
    else:
        ea_export_path = _find_latest_ea_symbol_specs(runtime_dir)
        if ea_export_path:
            raw_rows, resolved_path, source_format, metadata = _load_registry_rows(str(ea_export_path))
            auto_discovered_ea_export = True
            ea_symbol_specs_json_path = resolved_path
            if source_format == "JSON":
                source_format = "EA_SYMBOL_SPECS_JSON"
        else:
            ea_dashboard_path = _find_latest_ea_dashboard(runtime_dir)
            if ea_dashboard_path:
                raw_rows, resolved_path, source_format, metadata = _load_dashboard_hfm_crypto_specs(ea_dashboard_path)
                auto_discovered_ea_dashboard = True
                ea_dashboard_json_path = resolved_path
            else:
                raw_rows, resolved_path, source_format, metadata = [], "", "NO_PATH", None

    broker_symbol_diagnostics = _broker_symbol_diagnostics(metadata if isinstance(metadata, dict) else None)
    account_symbols_without_crypto = (
        broker_symbol_diagnostics.get("brokerSymbolTotalAll", 0) > 0
        and broker_symbol_diagnostics.get("brokerCryptoLikeCountAll", 0) == 0
    )
    normalized_rows = [_normalize_contract_row(row) for row in raw_rows]
    crypto_rows = _dedupe_rows([row for row in normalized_rows if _is_crypto_row(row)])
    reviewed_rows = []
    blockers: list[dict[str, Any]] = []
    if source_format == "NO_PATH":
        blockers.append({
            "code": "HFM_MT5_SYMBOL_REGISTRY_EXPORT_MISSING",
            "reasonZh": f"尚未提供 MT5 symbol registry JSON，也没有找到 EA 只读导出的 {EA_SYMBOL_SPECS_FILE} 或内嵌 hfmCryptoSymbolSpecs 的 QuantGod_Dashboard.json。",
        })
    elif source_format == "MISSING":
        blockers.append({
            "code": "HFM_MT5_SYMBOL_REGISTRY_EXPORT_NOT_FOUND",
            "reasonZh": "指定的 MT5 symbol registry JSON 不存在。",
            "value": resolved_path,
        })
    elif source_format in {"UNREADABLE", "LIVE_MT5_UNREADABLE"}:
        blockers.append({
            "code": "HFM_MT5_SYMBOL_REGISTRY_EXPORT_UNREADABLE",
            "reasonZh": "MT5 symbol registry JSON 无法解析。",
            "value": resolved_path,
        })
    elif source_format in {"EA_DASHBOARD_UNREADABLE", "EA_DASHBOARD_EMPTY"}:
        blockers.append({
            "code": "HFM_MT5_EA_DASHBOARD_EXPORT_UNREADABLE",
            "reasonZh": "EA dashboard 中的 hfmCryptoSymbolSpecs 不存在或无法解析。",
            "value": resolved_path,
        })
    elif source_format == "LIVE_MT5_UNAVAILABLE":
        blockers.append({
            "code": "HFM_MT5_SYMBOL_REGISTRY_LIVE_UNAVAILABLE",
            "reasonZh": "当前环境无法通过 Python MetaTrader5 只读读取 symbol registry。",
            "value": resolved_path,
        })
    elif not raw_rows and account_symbols_without_crypto:
        blockers.append({
            "code": "HFM_MT5_ACCOUNT_NO_CRYPTO_CFD_SYMBOLS",
            "reasonZh": (
                "MT5 已下发账号 symbol 清单，但没有任何 crypto CFD symbol；"
                "当前 HFM 账号/服务器可能未开放 crypto CFD。"
            ),
            "value": resolved_path,
            "brokerSymbolTotalAll": broker_symbol_diagnostics.get("brokerSymbolTotalAll", 0),
            "brokerSymbolTotalMarketWatch": broker_symbol_diagnostics.get("brokerSymbolTotalMarketWatch", 0),
            "brokerCryptoLikeCountAll": broker_symbol_diagnostics.get("brokerCryptoLikeCountAll", 0),
        })
    elif not raw_rows:
        blockers.append({
            "code": "HFM_MT5_SYMBOL_REGISTRY_EMPTY",
            "reasonZh": "MT5 symbol registry 没有返回 symbol 行。",
            "value": resolved_path,
        })
    elif not crypto_rows and account_symbols_without_crypto:
        blockers.append({
            "code": "HFM_MT5_ACCOUNT_NO_CRYPTO_CFD_SYMBOLS",
            "reasonZh": (
                "MT5 已下发账号 symbol 清单，但没有任何 crypto CFD symbol；"
                "当前 HFM 账号/服务器可能未开放 crypto CFD。"
            ),
            "value": resolved_path,
            "brokerSymbolTotalAll": broker_symbol_diagnostics.get("brokerSymbolTotalAll", 0),
            "brokerSymbolTotalMarketWatch": broker_symbol_diagnostics.get("brokerSymbolTotalMarketWatch", 0),
            "brokerCryptoLikeCountAll": broker_symbol_diagnostics.get("brokerCryptoLikeCountAll", 0),
        })
    elif not crypto_rows:
        blockers.append({
            "code": "HFM_MT5_SYMBOL_REGISTRY_NO_CRYPTO",
            "reasonZh": "MT5 symbol registry 中没有识别到 HFM crypto CFD symbol。",
            "value": resolved_path,
        })
    for row in crypto_rows:
        row_blockers = _row_blockers(row)
        reviewed_rows.append({**row, "validForContractSpecReview": not row_blockers, "blockers": row_blockers})
        blockers.extend({**item, "brokerSymbol": row.get("brokerSymbol"), "canonicalSymbol": row.get("canonicalSymbol")} for item in row_blockers)

    valid_rows = [row for row in reviewed_rows if row.get("validForContractSpecReview")]
    export_path = contract_spec_export_path(runtime_dir)
    ready = bool(valid_rows)
    payload = {
        "ok": True,
        "schema": CONTRACT_SPEC_EXPORT_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": "READY_FOR_CONTRACT_SPEC_REVIEW_INPUT" if ready else "WAITING_HFM_CRYPTO_CONTRACT_SPEC_EXPORT",
        "statusZh": (
            "HFM crypto MT5 合约规格导出可进入审查"
            if ready
            else "当前 HFM 账号未下发 crypto CFD symbol"
            if account_symbols_without_crypto
            else "等待 HFM crypto MT5 合约规格导出"
        ),
        "readyForContractSpecReviewInput": ready,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "symbolRegistryJsonPath": resolved_path,
        "eaSymbolSpecsJsonPath": ea_symbol_specs_json_path,
        "eaDashboardJsonPath": ea_dashboard_json_path,
        "autoDiscoveredEaExport": auto_discovered_ea_export,
        "autoDiscoveredEaDashboardExport": auto_discovered_ea_dashboard,
        "sourceFormat": source_format,
        "contractSpecJsonPath": str(export_path),
        "rawRowCount": len(raw_rows),
        "cryptoRowCount": len(crypto_rows),
        "validRowCount": len(valid_rows),
        "coveredCanonicalSymbols": sorted({row["canonicalSymbol"] for row in valid_rows if row.get("canonicalSymbol")}),
        "coveredBrokerSymbols": sorted({row["brokerSymbol"] for row in valid_rows if row.get("brokerSymbol")}),
        "requiredFields": list(REQUIRED_CONTRACT_SPEC_FIELDS),
        "symbols": reviewed_rows,
        "blockers": blockers,
        "brokerSymbolDiagnostics": broker_symbol_diagnostics,
        "sourceMetadata": {
            "mode": metadata.get("mode") if isinstance(metadata, dict) else "",
            "source": metadata.get("source") if isinstance(metadata, dict) else "",
            "status": metadata.get("status") if isinstance(metadata, dict) else "",
            "summary": metadata.get("summary") if isinstance(metadata, dict) else {},
            "schema": metadata.get("schema") if isinstance(metadata, dict) else "",
            "brokerSymbolTotalAll": broker_symbol_diagnostics.get("brokerSymbolTotalAll", 0),
            "brokerSymbolTotalMarketWatch": broker_symbol_diagnostics.get("brokerSymbolTotalMarketWatch", 0),
            "brokerCryptoLikeCountAll": broker_symbol_diagnostics.get("brokerCryptoLikeCountAll", 0),
            "brokerCryptoLikeCountMarketWatch": broker_symbol_diagnostics.get("brokerCryptoLikeCountMarketWatch", 0),
            "error": metadata.get("error") if isinstance(metadata, dict) else "",
            "detail": metadata.get("detail") if isinstance(metadata, dict) else "",
            "dashboardPath": metadata.get("dashboardPath") if isinstance(metadata, dict) else "",
            "dashboardBuild": metadata.get("dashboardBuild") if isinstance(metadata, dict) else "",
            "dashboardTimestamp": metadata.get("dashboardTimestamp") if isinstance(metadata, dict) else "",
        },
        "nextRequiredActionZh": (
            "用 contractSpecJsonPath 运行 execution-spec 审查，然后刷新 live automation readiness。"
            if ready
            else "当前账号没有下发 crypto CFD；需要换用开通 HFM crypto CFD 的账号/服务器，或提供该账号真实 MT5 symbol specs。"
            if account_symbols_without_crypto
            else f"先在 HFM MT5 EA 导出 {EA_SYMBOL_SPECS_FILE}，同步包含 hfmCryptoSymbolSpecs 的 QuantGod_Dashboard.json，或提供只读 symbol registry JSON。"
        ),
        "safety": {
            **SAFETY,
            "mutatesMt5": False,
            "symbolSelectAllowed": False,
        },
    }
    if write:
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_contract_spec_export(runtime_dir: Path) -> dict[str, Any]:
    path = contract_spec_export_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                if not payload.get("readyForContractSpecReviewInput"):
                    return build_hfm_crypto_contract_spec_export(Path(runtime_dir), write=False)
                return {"ok": True, **payload}
        except Exception:
            pass
    return build_hfm_crypto_contract_spec_export(Path(runtime_dir), write=False)
