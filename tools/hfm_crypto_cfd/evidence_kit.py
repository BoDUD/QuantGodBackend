from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .schema import (
    CONTRACT_SPEC_TEMPLATE_CSV_FILE,
    CONTRACT_SPEC_TEMPLATE_FILE,
    EA_SYMBOL_SPECS_FILE,
    EVIDENCE_KIT_SCHEMA_VERSION,
    HFM_CRYPTO_CFD_CANDIDATES,
    SAFETY,
    contract_spec_export_path,
    contract_spec_template_csv_path,
    contract_spec_template_path,
    ea_symbol_specs_path,
    evidence_kit_path,
    filled_contract_spec_path,
    filled_simulation_profile_path,
    simulation_profile_template_path,
    utc_now_iso,
)

try:
    from tools.mt5_symbol_registry import normalize_symbol_row
except ModuleNotFoundError:  # pragma: no cover
    from mt5_symbol_registry import normalize_symbol_row


REQUIRED_CONTRACT_SPEC_FIELDS = [
    "brokerSymbol",
    "canonicalSymbol",
    "contractSize",
    "tickSize",
    "tickValue",
    "minLot",
    "lotStep",
    "maxLot",
]

OPTIONAL_CONTRACT_SPEC_FIELDS = [
    "description",
    "path",
    "tradeMode",
    "calcMode",
    "spreadMaxPips",
    "maxSlippagePips",
    "marginInitial",
    "swapLong",
    "swapShort",
    "tradeEnabled",
]


def _template_row(symbol: str) -> dict[str, Any]:
    row = normalize_symbol_row({"name": symbol, "path": "Crypto CFD"})
    return {
        "brokerSymbol": row.get("brokerSymbol") or symbol,
        "canonicalSymbol": row.get("canonicalSymbol") or "",
        "contractSize": None,
        "tickSize": None,
        "tickValue": None,
        "minLot": None,
        "lotStep": None,
        "maxLot": None,
        "description": row.get("description") or "",
        "path": row.get("path") or "Crypto CFD",
        "tradeMode": "",
        "calcMode": "",
        "spreadMaxPips": None,
        "maxSlippagePips": None,
        "marginInitial": None,
        "swapLong": None,
        "swapShort": None,
        "tradeEnabled": None,
    }


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("canonicalSymbol") or ""), str(row.get("brokerSymbol") or ""))
        unique[key] = row
    return list(unique.values())


def _contract_spec_template() -> dict[str, Any]:
    rows = _dedupe_rows([_template_row(symbol) for symbol in HFM_CRYPTO_CFD_CANDIDATES])
    return {
        "symbols": rows,
        "requiredFields": REQUIRED_CONTRACT_SPEC_FIELDS,
        "optionalFields": OPTIONAL_CONTRACT_SPEC_FIELDS,
    }


def _write_csv_template(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [*REQUIRED_CONTRACT_SPEC_FIELDS, *OPTIONAL_CONTRACT_SPEC_FIELDS]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _simulation_profile_template() -> dict[str, Any]:
    return {
        "agentId": "agt_hfm_crypto_candidate",
        "agentUrl": "https://moss.site/agent/agt...",
        "strategyName": "HFM Crypto CFD candidate",
        "metrics": {
            "pnlUsd": None,
            "roiPct": None,
            "sharpe": None,
            "maxDrawdownPct": None,
            "tradeCount": None,
            "liquidationCount": 0,
        },
        "backtest": {
            "dateRange": "YYYY-MM-DD..YYYY-MM-DD",
        },
    }


def build_hfm_crypto_evidence_kit(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    template = _contract_spec_template()
    simulation_template = _simulation_profile_template()
    template_json_path = contract_spec_template_path(runtime_dir)
    template_csv_path = contract_spec_template_csv_path(runtime_dir)
    simulation_template_json_path = simulation_profile_template_path(runtime_dir)
    payload = {
        "ok": True,
        "schema": EVIDENCE_KIT_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": "READY_FOR_OPERATOR_EXPORT",
        "statusZh": "HFM crypto 证据采集包已生成",
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "requiredContractSpecFields": REQUIRED_CONTRACT_SPEC_FIELDS,
        "optionalContractSpecFields": OPTIONAL_CONTRACT_SPEC_FIELDS,
        "contractSpecTemplate": template,
        "simulationProfileTemplate": simulation_template,
        "outputFiles": {
            "evidenceKit": str(evidence_kit_path(runtime_dir)),
            "contractSpecTemplateJson": str(template_json_path),
            "contractSpecTemplateCsv": str(template_csv_path),
            "contractSpecExportJson": str(contract_spec_export_path(runtime_dir)),
            "eaSymbolSpecsJson": str(ea_symbol_specs_path(runtime_dir)),
            "simulationProfileTemplateJson": str(simulation_template_json_path),
            "expectedFilledContractSpecJson": str(filled_contract_spec_path(runtime_dir)),
            "expectedFilledSimulationProfileJson": str(filled_simulation_profile_path(runtime_dir)),
        },
        "collectionChecklist": [
            {
                "id": "download_or_enable_hfm_crypto_history",
                "labelZh": "在 HFM MT5 中下载或显示 crypto CFD symbol 历史",
                "reasonZh": "readiness 需要在本机 Bases 目录看到 HFM 官方 crypto USD CFD 的 history 或 tick 目录。",
            },
            {
                "id": "export_mt5_symbol_registry",
                "labelZh": "导出只读 MT5 symbol registry",
                "reasonZh": "如果本机 Python MT5 bridge 可用，可以直接从 Market Watch/服务器读取 symbol 规格字段。",
            },
            {
                "id": "collect_ea_hfm_crypto_symbol_specs",
                "labelZh": f"让 MT5 EA 写出 {EA_SYMBOL_SPECS_FILE}",
                "reasonZh": "macOS 上 Python MetaTrader5 bridge 不可用时，EA 会用 SymbolInfo* 只读导出 HFM 官方 crypto CFD 合约规格；后端也能从 QuantGod_Dashboard.json 内嵌的 hfmCryptoSymbolSpecs 自动抽取。",
            },
            {
                "id": "fill_contract_spec_template",
                "labelZh": "补齐 HFM crypto 合约规格模板",
                "reasonZh": "至少需要 contractSize、tickSize、tickValue、minLot、lotStep、maxLot。",
            },
            {
                "id": "import_moss_or_sim_profile",
                "labelZh": "导入 Moss/模拟回测 profile",
                "reasonZh": "必须有 USD pnl、ROI、Sharpe、最大回撤、交易笔数和爆仓次数字段；pnlUsd 会进入 BTC/crypto 合计收益目标追踪。",
            },
        ],
        "readOnlyCommands": [
            "python3 tools/mt5_symbol_registry.py --endpoint registry --group \"*Crypto*\" --limit 500 > runtime/hfm_crypto/mt5_symbol_registry_crypto.json",
            "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime contract-spec-export --write --symbol-registry-json runtime/hfm_crypto/mt5_symbol_registry_crypto.json",
            f"# macOS fallback: copy MT5 Files/{EA_SYMBOL_SPECS_FILE} to runtime/hfm_crypto/{EA_SYMBOL_SPECS_FILE}, then auto-discover it",
            "# macOS fallback 2: sync MT5 Files/QuantGod_Dashboard.json; the embedded hfmCryptoSymbolSpecs object is auto-discovered",
            "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime contract-spec-export --write",
            "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime execution-spec --write --contract-spec-json runtime/hfm_crypto/QuantGod_HFMCryptoContractSpecExport.json",
            "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime simulation-profile --write --simulation-profile-json runtime/hfm_crypto/hfm_crypto_simulation_profile.filled.json",
            "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime build --write --contract-spec-json runtime/hfm_crypto/QuantGod_HFMCryptoContractSpecExport.json",
            "python3 tools/run_live_automation_readiness.py --runtime-dir runtime build --write --refresh-sources --hfm-contract-spec-json runtime/hfm_crypto/QuantGod_HFMCryptoContractSpecExport.json",
        ],
        "nextRequiredActionZh": f"在 HFM MT5 运行 EA 生成 {EA_SYMBOL_SPECS_FILE} 或 QuantGod_Dashboard.json 内嵌 hfmCryptoSymbolSpecs，或把 HFM MT5 读到的 crypto 合约规格填入模板，再导入 execution-spec 审查器。",
        "safety": dict(SAFETY),
    }
    if write:
        out = evidence_kit_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        template_json_path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        simulation_template_json_path.write_text(json.dumps(simulation_template, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_csv_template(template_csv_path, template["symbols"])
    return payload


def read_hfm_crypto_evidence_kit(runtime_dir: Path) -> dict[str, Any]:
    path = evidence_kit_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
        except Exception:
            pass
    return build_hfm_crypto_evidence_kit(Path(runtime_dir), write=False)
