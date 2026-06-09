from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .schema import (
    EXECUTION_SPEC_REVIEW_SCHEMA_VERSION,
    HFM_CRYPTO_USD_CANONICALS,
    SAFETY,
    execution_spec_review_path,
    utc_now_iso,
)

try:
    from tools.mt5_symbol_registry import normalize_symbol_row
except ModuleNotFoundError:  # pragma: no cover
    from mt5_symbol_registry import normalize_symbol_row


CRYPTO_CANONICAL_RE = re.compile(
    "(" + "|".join(re.escape(symbol) for symbol in sorted(HFM_CRYPTO_USD_CANONICALS, key=len, reverse=True)) + ")"
)

REQUIRED_NUMERIC_FIELDS = (
    "contractSize",
    "tickSize",
    "tickValue",
    "minLot",
    "lotStep",
    "maxLot",
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _compact_symbol(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _clean_text(value).upper())


def _canonical_from_symbol(symbol: Any) -> str:
    compact = _compact_symbol(symbol)
    match = CRYPTO_CANONICAL_RE.search(compact)
    return match.group(1) if match else ""


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
    if text in {"true", "1", "yes", "y", "enabled", "on"}:
        return True
    if text in {"false", "0", "no", "n", "disabled", "off"}:
        return False
    return None


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("symbols", "rows", "items", "contracts", "specs", "mappings"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    if any(key in payload for key in ("symbol", "name", "brokerSymbol", "contractSize", "tradeContractSize")):
        return [payload]
    return []


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_rows(path: str) -> tuple[list[dict[str, Any]], str, str]:
    raw_path = _clean_text(path)
    if not raw_path:
        return [], "", "NO_PATH"
    source_path = Path(raw_path).expanduser()
    if not source_path.exists() or not source_path.is_file():
        return [], str(source_path), "MISSING"
    suffix = source_path.suffix.lower()
    try:
        if suffix == ".csv":
            return _read_csv_rows(source_path), str(source_path), "CSV"
        return _read_json_rows(source_path), str(source_path), "JSON"
    except Exception:
        return [], str(source_path), "UNREADABLE"


def _normalize_spec_row(row: dict[str, Any]) -> dict[str, Any]:
    broker_symbol = _first_value(row, ("brokerSymbol", "symbol", "name", "Symbol", "Name"))
    normalized = normalize_symbol_row({
        "name": broker_symbol,
        "description": _first_value(row, ("description", "Description")),
        "path": _first_value(row, ("path", "Path", "category", "assetClass")) or "Crypto CFD",
    })
    canonical = _first_value(row, ("canonicalSymbol", "canonical", "CanonicalSymbol")) or _canonical_from_symbol(broker_symbol)
    if not canonical:
        canonical = normalized.get("canonicalSymbol") or ""
    return {
        "brokerSymbol": _clean_text(broker_symbol),
        "canonicalSymbol": _clean_text(canonical),
        "description": _clean_text(_first_value(row, ("description", "Description"))),
        "path": _clean_text(_first_value(row, ("path", "Path", "category", "assetClass"))),
        "tradeMode": _clean_text(_first_value(row, ("tradeMode", "TradeMode", "trade_mode", "mode"))),
        "calcMode": _clean_text(_first_value(row, ("calcMode", "CalcMode", "tradeCalcMode", "trade_calc_mode"))),
        "contractSize": _safe_float(_first_value(row, ("contractSize", "ContractSize", "tradeContractSize", "trade_contract_size", "lotSize"))),
        "tickSize": _safe_float(_first_value(row, ("tickSize", "TickSize", "point", "Point"))),
        "tickValue": _safe_float(_first_value(row, ("tickValue", "TickValue", "tradeTickValue", "trade_tick_value"))),
        "minLot": _safe_float(_first_value(row, ("minLot", "MinLot", "volumeMin", "volume_min", "volume_min_lots"))),
        "lotStep": _safe_float(_first_value(row, ("lotStep", "LotStep", "volumeStep", "volume_step", "volume_step_lots"))),
        "maxLot": _safe_float(_first_value(row, ("maxLot", "MaxLot", "volumeMax", "volume_max", "volume_max_lots"))),
        "spreadMaxPips": _safe_float(_first_value(row, ("spreadMaxPips", "maxSpreadPips", "spreadPips", "spread"))),
        "maxSlippagePips": _safe_float(_first_value(row, ("maxSlippagePips", "slippagePips"))),
        "marginInitial": _safe_float(_first_value(row, ("marginInitial", "initialMargin", "margin_initial"))),
        "swapLong": _safe_float(_first_value(row, ("swapLong", "SwapLong", "longSwap"))),
        "swapShort": _safe_float(_first_value(row, ("swapShort", "SwapShort", "shortSwap"))),
        "tradeEnabled": _safe_bool(_first_value(row, ("tradeEnabled", "enabled", "visible"))),
        "normalizedMarketType": normalized.get("marketType"),
    }


def _row_blockers(row: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not row.get("brokerSymbol") or not row.get("canonicalSymbol"):
        blockers.append({
            "code": "HFM_CRYPTO_SPEC_SYMBOL_MISSING",
            "reasonZh": "合约规格缺少 broker symbol 或 canonical symbol。",
        })
    if _clean_text(row.get("canonicalSymbol")) and not _canonical_from_symbol(row.get("canonicalSymbol")):
        blockers.append({
            "code": "HFM_CRYPTO_SPEC_NOT_CRYPTO_USD",
            "reasonZh": "合约规格不是当前支持的 crypto USD CFD。",
            "value": row.get("canonicalSymbol"),
        })
    for field in REQUIRED_NUMERIC_FIELDS:
        value = row.get(field)
        if value is None or value <= 0:
            blockers.append({
                "code": "HFM_CRYPTO_SPEC_FIELD_MISSING",
                "reasonZh": f"HFM crypto 合约规格缺少有效 {field}。",
                "field": field,
                "value": value,
            })
    if row.get("maxLot") is not None and row.get("minLot") is not None and row["maxLot"] < row["minLot"]:
        blockers.append({
            "code": "HFM_CRYPTO_SPEC_LOT_RANGE_INVALID",
            "reasonZh": "最大手数小于最小手数。",
            "value": {"minLot": row.get("minLot"), "maxLot": row.get("maxLot")},
        })
    return blockers


def build_hfm_crypto_execution_spec_review(
    runtime_dir: Path,
    *,
    contract_spec_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    raw_rows, resolved_path, source_format = _load_rows(contract_spec_json)
    normalized_rows = [_normalize_spec_row(row) for row in raw_rows]
    crypto_rows = [
        row for row in normalized_rows
        if _canonical_from_symbol(row.get("canonicalSymbol")) or _canonical_from_symbol(row.get("brokerSymbol"))
    ]
    reviewed_rows = []
    blockers: list[dict[str, Any]] = []
    if not contract_spec_json:
        blockers.append({
            "code": "HFM_CRYPTO_CONTRACT_SPEC_FILE_MISSING",
            "reasonZh": "尚未导入 HFM/MT5 crypto CFD 合约规格 JSON/CSV。",
        })
    elif source_format == "MISSING":
        blockers.append({
            "code": "HFM_CRYPTO_CONTRACT_SPEC_FILE_NOT_FOUND",
            "reasonZh": "指定的 HFM crypto 合约规格文件不存在。",
            "value": resolved_path,
        })
    elif source_format == "UNREADABLE":
        blockers.append({
            "code": "HFM_CRYPTO_CONTRACT_SPEC_FILE_UNREADABLE",
            "reasonZh": "指定的 HFM crypto 合约规格文件无法解析。",
            "value": resolved_path,
        })
    elif not raw_rows:
        blockers.append({
            "code": "HFM_CRYPTO_CONTRACT_SPEC_EMPTY",
            "reasonZh": "指定的 HFM crypto 合约规格文件没有可用 rows。",
            "value": resolved_path,
        })
    elif not crypto_rows:
        blockers.append({
            "code": "HFM_CRYPTO_CONTRACT_SPEC_NO_CRYPTO_ROWS",
            "reasonZh": "合约规格文件里没有 BTC/ETH/SOL/XRP/DOGE/LTC 等 crypto USD CFD。",
            "value": resolved_path,
        })
    for row in crypto_rows:
        row_blockers = _row_blockers(row)
        reviewed_rows.append({**row, "validForDryRunContract": not row_blockers, "blockers": row_blockers})
        blockers.extend({**item, "brokerSymbol": row.get("brokerSymbol"), "canonicalSymbol": row.get("canonicalSymbol")} for item in row_blockers)
    valid_rows = [row for row in reviewed_rows if row.get("validForDryRunContract")]
    ready = bool(valid_rows) and not [
        row for row in blockers
        if row.get("code") in {
            "HFM_CRYPTO_CONTRACT_SPEC_FILE_MISSING",
            "HFM_CRYPTO_CONTRACT_SPEC_FILE_NOT_FOUND",
            "HFM_CRYPTO_CONTRACT_SPEC_FILE_UNREADABLE",
            "HFM_CRYPTO_CONTRACT_SPEC_EMPTY",
            "HFM_CRYPTO_CONTRACT_SPEC_NO_CRYPTO_ROWS",
        }
    ]
    payload = {
        "ok": True,
        "schema": EXECUTION_SPEC_REVIEW_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": "READY_FOR_EXECUTION_CONTRACT_REVIEW" if ready else "WAITING_HFM_CRYPTO_CONTRACT_SPEC",
        "statusZh": "HFM crypto 合约规格可进入执行合约审查" if ready else "等待 HFM crypto 合约规格证据",
        "readyForExecutionSpecReview": ready,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "contractSpecJsonPath": resolved_path,
        "sourceFormat": source_format,
        "rawRowCount": len(raw_rows),
        "cryptoRowCount": len(crypto_rows),
        "validRowCount": len(valid_rows),
        "coveredCanonicalSymbols": sorted({row["canonicalSymbol"] for row in valid_rows if row.get("canonicalSymbol")}),
        "coveredBrokerSymbols": sorted({row["brokerSymbol"] for row in valid_rows if row.get("brokerSymbol")}),
        "requiredFields": list(REQUIRED_NUMERIC_FIELDS),
        "reviewedRows": reviewed_rows,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "把这些合约规格并入 review packet，继续审查 kill switch、最大亏损、点差滑点和 operator approval。"
            if ready
            else "从 HFM/MT5 导出 crypto symbol 规格，至少包含 contractSize、tickSize、tickValue、minLot、lotStep、maxLot。"
        ),
        "safety": dict(SAFETY),
    }
    if write:
        out = execution_spec_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_execution_spec_review(runtime_dir: Path) -> dict[str, Any]:
    path = execution_spec_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
        except Exception:
            pass
    return {
        "ok": True,
        "schema": EXECUTION_SPEC_REVIEW_SCHEMA_VERSION,
        "status": "WAITING_HFM_CRYPTO_CONTRACT_SPEC",
        "statusZh": "等待 HFM crypto 合约规格证据",
        "readyForExecutionSpecReview": False,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "blockers": [{
            "code": "HFM_CRYPTO_CONTRACT_SPEC_REVIEW_NOT_BUILT",
            "reasonZh": "尚未构建 HFM crypto 合约规格审查。",
        }],
        "safety": dict(SAFETY),
    }
