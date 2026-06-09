from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .schema import (
    HFM_CRYPTO_CFD_CANDIDATES,
    HFM_CRYPTO_USD_CANONICALS,
    MOSS_BACKTEST_FILE,
    SAFETY,
    SCHEMA_VERSION,
    contract_spec_export_path,
    execution_spec_review_path,
    filled_contract_spec_path,
    filled_simulation_profile_path,
    moss_backtest_path,
    simulation_profile_review_path,
    state_path,
    utc_now_iso,
)

from .execution_spec import build_hfm_crypto_execution_spec_review, read_hfm_crypto_execution_spec_review
from .contract_spec_export import build_hfm_crypto_contract_spec_export, read_hfm_crypto_contract_spec_export
from .simulation_profile import (
    build_hfm_crypto_simulation_profile_review,
    parse_simulation_profile,
    read_hfm_crypto_simulation_profile_review,
)
from .rates_export import read_hfm_crypto_rates_export_review
from .standalone_exporter_bundle import build_hfm_crypto_standalone_exporter_bundle

try:
    from tools.mt5_symbol_registry import normalize_symbol_row, static_symbol_catalog
except ModuleNotFoundError:  # pragma: no cover
    from mt5_symbol_registry import normalize_symbol_row, static_symbol_catalog


CRYPTO_CANONICAL_RE = re.compile(
    "(" + "|".join(re.escape(symbol) for symbol in sorted(HFM_CRYPTO_USD_CANONICALS, key=len, reverse=True)) + ")"
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _compact_symbol(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _clean_text(value).upper())


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _first_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _crypto_row(symbol: str, *, source: str = "candidate") -> dict[str, Any]:
    row = normalize_symbol_row({"name": symbol, "path": "Crypto CFD"})
    canonical = _canonical_from_symbol(symbol) or _clean_text(row.get("canonicalSymbol"))
    if canonical.endswith("USD") and len(canonical) > 3:
        row["canonicalSymbol"] = canonical
        row["baseCurrency"] = canonical[:-3]
        row["quoteCurrency"] = "USD"
    row["source"] = source
    return row


def _candidate_rows() -> list[dict[str, Any]]:
    rows = [
        _crypto_row(symbol, source="hfm_official_candidate")
        for symbol in HFM_CRYPTO_CFD_CANDIDATES
    ]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_clean_text(row.get("canonicalSymbol")), _clean_text(row.get("brokerSymbol")))
        by_key[key] = row
    return list(by_key.values())


def _static_crypto_rows() -> list[dict[str, Any]]:
    return [
        {**row, "source": "mt5_static_symbol_catalog"}
        for row in static_symbol_catalog()
        if row.get("marketType") == "crypto_cfd"
    ]


def _artifact_symbols(payload: dict[str, Any]) -> dict[str, list[str]]:
    canonical = {
        _clean_text(value)
        for value in payload.get("coveredCanonicalSymbols", [])
        if _clean_text(value)
    }
    broker = {
        _clean_text(value)
        for value in payload.get("coveredBrokerSymbols", [])
        if _clean_text(value)
    }
    return {
        "canonicalSymbols": sorted(canonical),
        "brokerSymbols": sorted(broker),
    }


def _symbol_evidence_sources(
    local_evidence: dict[str, Any],
    contract_spec_export: dict[str, Any],
    execution_spec_review: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    local_canonical = [
        _clean_text(value)
        for value in local_evidence.get("canonicalSymbols", [])
        if _clean_text(value)
    ]
    local_broker = [
        _clean_text(value)
        for value in local_evidence.get("brokerSymbols", [])
        if _clean_text(value)
    ]
    if local_evidence.get("found"):
        rows.append({
            "sourceId": "local_mt5_bases",
            "sourceZh": "HFM MT5 Bases history/tick",
            "passed": True,
            "canonicalSymbols": local_canonical,
            "brokerSymbols": local_broker,
        })
    contract_symbols = _artifact_symbols(contract_spec_export)
    if contract_spec_export.get("readyForContractSpecReviewInput") or contract_symbols["brokerSymbols"]:
        rows.append({
            "sourceId": "contract_spec_export",
            "sourceZh": "HFM contract spec export",
            "passed": bool(contract_spec_export.get("readyForContractSpecReviewInput")),
            **contract_symbols,
        })
    execution_symbols = _artifact_symbols(execution_spec_review)
    if execution_spec_review.get("readyForExecutionSpecReview") or execution_symbols["brokerSymbols"]:
        rows.append({
            "sourceId": "execution_spec_review",
            "sourceZh": "HFM execution spec review",
            "passed": bool(execution_spec_review.get("readyForExecutionSpecReview")),
            **execution_symbols,
        })
    return rows


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _default_bases_roots(runtime_dir: Path) -> list[Path]:
    home = Path.home()
    runtime_path = Path(runtime_dir).expanduser()
    primary_mt5_root = (
        home
        / "Library"
        / "Application Support"
        / "net.metaquotes.wine.metatrader5"
        / "drive_c"
        / "Program Files"
        / "MetaTrader 5"
    )
    secondary_mt5_root = (
        home
        / "Library"
        / "Application Support"
        / "net.metaquotes.wine.metatrader5-live16"
        / "drive_c"
        / "Program Files"
        / "MetaTrader 5"
    )
    roots = [
        runtime_path / "HFM_MT5_Tester_Isolated" / "Bases",
        runtime_path / "Bases",
    ]
    allow_global_bases = os.environ.get("QG_HFM_CRYPTO_ALLOW_GLOBAL_BASES", "").strip() == "1"
    for mt5_root in (primary_mt5_root, secondary_mt5_root):
        if allow_global_bases or _path_is_relative_to(runtime_path, mt5_root):
            roots.append(mt5_root / "Bases")
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def _is_crypto_symbol(symbol: str) -> bool:
    compact = _compact_symbol(symbol)
    return bool(CRYPTO_CANONICAL_RE.search(compact))


def _canonical_from_symbol(symbol: str) -> str:
    compact = _compact_symbol(symbol)
    match = CRYPTO_CANONICAL_RE.search(compact)
    return match.group(1) if match else ""


def _safe_count_files(symbol_dir: Path, limit: int = 25) -> int:
    count = 0
    try:
        for child in symbol_dir.iterdir():
            if child.is_file():
                count += 1
                if count >= limit:
                    return count
    except OSError:
        return 0
    return count


def _scan_symbol_dirs(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not root.exists() or not root.is_dir():
        return findings
    try:
        server_dirs = [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        return findings
    for server_dir in server_dirs:
        for kind in ("history", "ticks"):
            base = server_dir / kind
            if not base.exists() or not base.is_dir():
                continue
            try:
                symbol_dirs = [child for child in base.iterdir() if child.is_dir()]
            except OSError:
                continue
            for symbol_dir in symbol_dirs:
                symbol = symbol_dir.name
                if not _is_crypto_symbol(symbol):
                    continue
                canonical = _canonical_from_symbol(symbol)
                normalized = _crypto_row(symbol, source="local_mt5_bases")
                findings.append({
                    "root": str(root),
                    "server": server_dir.name,
                    "kind": kind,
                    "symbol": symbol,
                    "canonicalSymbol": canonical or normalized.get("canonicalSymbol"),
                    "path": str(symbol_dir),
                    "fileCountCapped": _safe_count_files(symbol_dir),
                    "normalized": normalized,
                })
    findings.sort(key=lambda row: (row["canonicalSymbol"], row["server"], row["kind"], row["symbol"]))
    return findings


def scan_local_crypto_evidence(runtime_dir: Path, extra_bases_roots: list[str] | None = None) -> dict[str, Any]:
    roots = _default_bases_roots(runtime_dir)
    for raw in extra_bases_roots or []:
        root = Path(str(raw)).expanduser()
        if root not in roots:
            roots.append(root)
    findings: list[dict[str, Any]] = []
    inspected_roots: list[dict[str, Any]] = []
    for root in roots:
        exists = root.exists() and root.is_dir()
        inspected_roots.append({"path": str(root), "exists": exists})
        findings.extend(_scan_symbol_dirs(root))
    canonical_symbols = sorted({
        _clean_text(item.get("canonicalSymbol"))
        for item in findings
        if _clean_text(item.get("canonicalSymbol"))
    })
    broker_symbols = sorted({_clean_text(item.get("symbol")) for item in findings if _clean_text(item.get("symbol"))})
    return {
        "inspectedRoots": inspected_roots,
        "found": bool(findings),
        "canonicalSymbols": canonical_symbols,
        "brokerSymbols": broker_symbols,
        "findings": findings,
    }


def _load_json(path: str) -> tuple[dict[str, Any], str]:
    raw_path = str(path or "").strip()
    if not raw_path:
        return {}, ""
    source_path = Path(raw_path).expanduser()
    try:
        if source_path.exists() and source_path.is_file():
            payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
            return (payload if isinstance(payload, dict) else {}), str(source_path)
    except Exception:
        return {}, str(source_path)
    return {}, str(source_path)


def parse_moss_backtest_profile(path: str = "", raw_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = parse_simulation_profile(path, raw_profile=raw_profile)
    return {**profile, "source": "moss_backtest_export_json"}


def _moss_profile_from_simulation_review(review: dict[str, Any]) -> dict[str, Any]:
    profile = review.get("profile") if isinstance(review.get("profile"), dict) else {}
    metrics = profile.get("metrics") if isinstance(profile.get("metrics"), dict) else {}
    if not metrics and isinstance(review.get("metrics"), dict):
        metrics = review["metrics"]
    if not bool(profile.get("profileFound")) and not metrics:
        return {}
    source_selection = review.get("sourceSelection") if isinstance(review.get("sourceSelection"), dict) else {}
    return {
        **profile,
        "source": "simulation_profile_review_artifact",
        "profileJsonPath": source_selection.get("path") or profile.get("profileJsonPath", ""),
        "sourceFormat": profile.get("sourceFormat", ""),
        "profileFound": bool(profile.get("profileFound") or metrics),
        "metrics": metrics,
        "simulationProfileReviewStatus": review.get("status", ""),
        "simulationQualified": bool(review.get("simulationQualified")),
        "sourceSelection": source_selection,
    }


def _build_operator_checklist(
    *,
    symbol_evidence_found: bool,
    broker_symbol_diagnostics: dict[str, Any],
    moss_profile: dict[str, Any],
    contract_spec_export: dict[str, Any],
    execution_spec_review: dict[str, Any],
    simulation_profile_review: dict[str, Any],
    rates_export_review: dict[str, Any],
) -> list[dict[str, Any]]:
    broker_total = _safe_int(broker_symbol_diagnostics.get("brokerSymbolTotalAll"))
    broker_market_watch_total = _safe_int(broker_symbol_diagnostics.get("brokerSymbolTotalMarketWatch"))
    crypto_total = _safe_int(broker_symbol_diagnostics.get("brokerCryptoLikeCountAll"))
    crypto_market_watch_total = _safe_int(broker_symbol_diagnostics.get("brokerCryptoLikeCountMarketWatch"))
    broker_inventory_known = broker_total is not None or broker_market_watch_total is not None
    crypto_symbols_available = symbol_evidence_found or (crypto_total or 0) > 0 or (crypto_market_watch_total or 0) > 0
    account_symbol_blocked = broker_inventory_known and not crypto_symbols_available
    contract_spec_ready = bool(contract_spec_export.get("readyForContractSpecReviewInput"))
    execution_spec_ready = bool(execution_spec_review.get("readyForExecutionSpecReview"))
    rates_ready = bool(rates_export_review.get("ratesReadyForSimulation"))
    moss_profile_found = bool(moss_profile.get("profileFound"))
    simulation_qualified = bool(simulation_profile_review.get("simulationQualified"))
    simulation_profile_ready = moss_profile_found or simulation_qualified
    live_review_unlocked = crypto_symbols_available and execution_spec_ready and simulation_profile_ready

    symbol_reason = (
        f"当前账号下发 broker symbols {broker_total if broker_total is not None else '未知'} 个，"
        f"Market Watch {broker_market_watch_total if broker_market_watch_total is not None else '未知'} 个，"
        f"crypto-like {crypto_total if crypto_total is not None else '未知'} 个。"
    )

    return [
        {
            "id": "mt5_account_symbol_inventory",
            "labelZh": "确认 MT5 账号已授权并下发 broker symbol 清单",
            "status": "PASS" if broker_inventory_known and (broker_total or 0) > 0 else "WAITING",
            "statusZh": "已读到账号 symbol 清单" if broker_inventory_known else "等待账号 symbol 清单",
            "passed": bool(broker_inventory_known and (broker_total or 0) > 0),
            "blocking": not broker_inventory_known,
            "required": True,
            "automated": True,
            "readOnly": True,
            "reasonZh": symbol_reason if broker_inventory_known else "等待只读 MT5 specs exporter 写出 broker symbol 诊断。",
            "nextActionZh": "账号链路已通，继续检查是否包含 crypto CFD。" if broker_inventory_known else "先刷新只读 MT5 specs exporter。",
        },
        {
            "id": "hfm_account_crypto_cfd_symbols",
            "labelZh": "HFM 账号/服务器下发 crypto CFD symbols",
            "status": "PASS" if crypto_symbols_available else "BLOCKED" if account_symbol_blocked else "WAITING",
            "statusZh": (
                "已发现 HFM crypto CFD symbols"
                if crypto_symbols_available
                else "当前账号/服务器没有 crypto CFD symbols"
                if account_symbol_blocked
                else "等待 HFM crypto CFD symbol 证据"
            ),
            "passed": bool(crypto_symbols_available),
            "blocking": not crypto_symbols_available,
            "required": True,
            "automated": False,
            "readOnly": True,
            "reasonZh": symbol_reason if broker_inventory_known else "还没有 broker symbol 诊断，不能判断账号是否开放 crypto CFD。",
            "nextActionZh": (
                "换用开通 HFM crypto CFD 的 HFM MT5 账号/服务器，或提供该账号真实 MT5 crypto symbol specs。"
                if account_symbol_blocked
                else "运行只读 specs exporter 并刷新 QuantGod_HFMCryptoSymbolSpecs.json。"
            ),
        },
        {
            "id": "hfm_crypto_contract_specs",
            "labelZh": "导入真实 HFM crypto 合约规格",
            "status": "PASS" if contract_spec_ready or execution_spec_ready else "LOCKED" if account_symbol_blocked else "PENDING",
            "statusZh": (
                "合约规格已可审查"
                if contract_spec_ready or execution_spec_ready
                else "被账号 crypto CFD 缺失锁住"
                if account_symbol_blocked
                else "等待 contract specs"
            ),
            "passed": bool(contract_spec_ready or execution_spec_ready),
            "blocking": not (contract_spec_ready or execution_spec_ready),
            "required": True,
            "automated": False,
            "readOnly": True,
            "reasonZh": contract_spec_export.get("statusZh") or "需要真实 broker symbol、contractSize、tickSize、tickValue、lot 限制。",
            "nextActionZh": "拿到 crypto CFD symbols 后重新生成 contract spec export 和 execution spec review。",
        },
        {
            "id": "hfm_crypto_copyrates_history",
            "labelZh": "导出 BTCUSD/HFM crypto CopyRates K 线",
            "status": "PASS" if rates_ready else "LOCKED" if not (crypto_symbols_available and execution_spec_ready) else "PENDING",
            "statusZh": (
                "BTCUSD CopyRates K 线已可用于模拟"
                if rates_ready
                else "等待 symbols/specs 后导出行情"
                if not (crypto_symbols_available and execution_spec_ready)
                else "等待 BTCUSD CopyRates K 线"
            ),
            "passed": rates_ready,
            "blocking": not rates_ready,
            "required": True,
            "automated": True,
            "readOnly": True,
            "reasonZh": rates_export_review.get("statusZh") or "需要 MT5 只读 CopyRates 导出的 BTCUSD K 线，才能生成不造假的 pnlUsd profile。",
            "nextActionZh": (
                "行情已可模拟；继续刷新 simulation-profile 和 profit-target tracker。"
                if rates_ready
                else "运行只读 HFM crypto CopyRates exporter，生成 QuantGod_HFMCryptoRatesExport.json。"
            ),
        },
        {
            "id": "moss_or_simulation_profile",
            "labelZh": "导入 Moss/backtest 模拟表现 profile",
            "status": "PASS" if moss_profile_found or simulation_qualified else "PENDING",
            "statusZh": "已导入模拟表现" if moss_profile_found or simulation_qualified else "等待 Moss/backtest profile",
            "passed": bool(moss_profile_found or simulation_qualified),
            "blocking": not (moss_profile_found or simulation_qualified),
            "required": True,
            "automated": False,
            "readOnly": True,
            "reasonZh": "实盘/跟单前需要 USD pnl、ROI、Sharpe、最大回撤、交易笔数和爆仓次数；pnlUsd 会进入 BTC/crypto 合计收益目标追踪。",
            "nextActionZh": (
                "先导出 BTCUSD CopyRates K 线，再自动生成包含 pnlUsd 的 HFM crypto 模拟 profile。"
                if not rates_ready
                else "刷新 simulation-profile，让 CopyRates 自动 profile 进入 pnlUsd 目标追踪。"
            ),
        },
        {
            "id": "review_only_execution_boundary",
            "labelZh": "保持 review-only，禁止 MT5/钱包/Moss/Hyperliquid 实盘执行",
            "status": "PASS",
            "statusZh": "只读安全边界已锁定",
            "passed": True,
            "blocking": False,
            "required": True,
            "automated": True,
            "readOnly": True,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "mossExecutionAllowed": False,
            "hyperliquidExecutionAllowed": False,
            "reasonZh": "当前车道只做证据、模拟和审查，不写订单、不授权钱包、不改实盘预设。",
            "nextActionZh": "任何真钱执行必须另开隔离 execution lane 代码评审。",
        },
        {
            "id": "separate_sim_to_live_review",
            "labelZh": "进入单独 sim-to-live / live execution 评审",
            "status": "PENDING" if live_review_unlocked else "LOCKED",
            "statusZh": "可准备单独评审" if live_review_unlocked else "前置证据未齐，不能进入执行实现",
            "passed": False,
            "blocking": not live_review_unlocked,
            "required": True,
            "automated": False,
            "readOnly": True,
            "reasonZh": "需要 crypto symbols、真实合约规格、模拟表现 profile 全部齐后才讨论执行实现。",
            "nextActionZh": (
                "先解除账号 crypto CFD symbol 阻断，再补 specs/profile。"
                if not crypto_symbols_available
                else "crypto symbol 已通；继续刷新并审查真实 HFM 合约规格。"
                if not execution_spec_ready
                else "合约规格已可审查；先补 BTCUSD CopyRates 行情，再生成包含 pnlUsd 的模拟 profile。"
                if not rates_ready
                else "CopyRates 行情已可模拟；继续补包含 pnlUsd 的模拟 profile。"
                if not simulation_profile_ready
                else "前置证据已齐，可准备单独 sim-to-live 执行评审包。"
            ),
        },
    ]


def build_hfm_crypto_cfd_state(
    runtime_dir: Path,
    *,
    moss_backtest_json: str = "",
    simulation_profile_json: str = "",
    contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    local_evidence = scan_local_crypto_evidence(runtime_dir, extra_bases_roots)
    profile_json = simulation_profile_json or moss_backtest_json
    if not profile_json:
        filled_sim = filled_simulation_profile_path(runtime_dir)
        if filled_sim.exists():
            profile_json = str(filled_sim)
    moss_profile = parse_moss_backtest_profile(profile_json)
    simulation_profile_review = (
        build_hfm_crypto_simulation_profile_review(runtime_dir, simulation_profile_json=profile_json, write=write)
        if profile_json
        else read_hfm_crypto_simulation_profile_review(runtime_dir)
    )
    if not moss_profile.get("profileFound"):
        moss_profile = _moss_profile_from_simulation_review(simulation_profile_review) or moss_profile
    resolved_contract_spec_json = contract_spec_json
    if not resolved_contract_spec_json:
        filled_contract = filled_contract_spec_path(runtime_dir)
        if filled_contract.exists():
            resolved_contract_spec_json = str(filled_contract)
    standalone_exporter_bundle = build_hfm_crypto_standalone_exporter_bundle(runtime_dir, write=False)
    rates_export_review = read_hfm_crypto_rates_export_review(runtime_dir)
    contract_spec_export = (
        read_hfm_crypto_contract_spec_export(runtime_dir)
        if resolved_contract_spec_json
        else build_hfm_crypto_contract_spec_export(runtime_dir, write=write)
    )
    if not resolved_contract_spec_json and contract_spec_export.get("readyForContractSpecReviewInput"):
        resolved_contract_spec_json = str(contract_spec_export.get("contractSpecJsonPath") or "")
    if not resolved_contract_spec_json:
        existing_export_path = contract_spec_export_path(runtime_dir)
        if existing_export_path.exists():
            resolved_contract_spec_json = str(existing_export_path)
    execution_spec_review = (
        build_hfm_crypto_execution_spec_review(runtime_dir, contract_spec_json=resolved_contract_spec_json, write=write)
        if resolved_contract_spec_json
        else read_hfm_crypto_execution_spec_review(runtime_dir)
    )
    static_rows = _static_crypto_rows()
    candidate_rows = _candidate_rows()
    detected_rows = [item["normalized"] for item in local_evidence.get("findings", [])]
    symbol_evidence_sources = _symbol_evidence_sources(local_evidence, contract_spec_export, execution_spec_review)
    symbol_evidence_found = any(bool(row.get("passed")) for row in symbol_evidence_sources)
    artifact_canonical_symbols = sorted({
        symbol
        for row in symbol_evidence_sources
        for symbol in row.get("canonicalSymbols", [])
        if symbol
    })
    artifact_broker_symbols = sorted({
        symbol
        for row in symbol_evidence_sources
        for symbol in row.get("brokerSymbols", [])
        if symbol
    })
    status = "READY_FOR_SHADOW_RESEARCH" if symbol_evidence_found else "WAITING_HFM_CRYPTO_SYMBOLS"
    broker_symbol_diagnostics = contract_spec_export.get("brokerSymbolDiagnostics") if isinstance(contract_spec_export, dict) else {}
    if not isinstance(broker_symbol_diagnostics, dict):
        broker_symbol_diagnostics = {}
    account_symbols_without_crypto = (
        not symbol_evidence_found
        and broker_symbol_diagnostics.get("brokerSymbolTotalAll", 0) > 0
        and broker_symbol_diagnostics.get("brokerCryptoLikeCountAll", 0) == 0
    )
    if account_symbols_without_crypto:
        status = "WAITING_HFM_ACCOUNT_CRYPTO_CFD_SYMBOLS"
    blockers = []
    if not symbol_evidence_found:
        if account_symbols_without_crypto:
            blockers.append({
                "code": "HFM_MT5_ACCOUNT_NO_CRYPTO_CFD_SYMBOLS",
                "reasonZh": (
                    "账号已成功授权并下发 symbol 清单，但当前 HFM 账号/服务器没有 crypto CFD symbol；"
                    "无法在这套账号上接入 HFM crypto CFD 实盘/跟单。"
                ),
                "brokerSymbolTotalAll": broker_symbol_diagnostics.get("brokerSymbolTotalAll", 0),
                "brokerSymbolTotalMarketWatch": broker_symbol_diagnostics.get("brokerSymbolTotalMarketWatch", 0),
                "brokerCryptoLikeCountAll": broker_symbol_diagnostics.get("brokerCryptoLikeCountAll", 0),
                "value": contract_spec_export.get("symbolRegistryJsonPath", ""),
            })
        elif standalone_exporter_bundle.get("targetExpertInstalledAndCompiled"):
            blockers.append({
                "code": "HFM_CRYPTO_STANDALONE_EXPORTER_READY_TO_RUN",
                "reasonZh": "独立只读 MT5 specs 导出 EA 已安装并编译；需要用 Expert 启动一次以写出 QuantGod_HFMCryptoSymbolSpecs.json。",
                "value": standalone_exporter_bundle.get("target", {}).get("targetExpertCompiledPath", ""),
            })
        elif standalone_exporter_bundle.get("targetInstalledAndCompiled"):
            blockers.append({
                "code": "HFM_CRYPTO_STANDALONE_EXPORTER_READY_TO_RUN",
                "reasonZh": "独立只读 MT5 specs 导出脚本已安装并编译；需要在 MT5 Scripts 中运行一次以写出 QuantGod_HFMCryptoSymbolSpecs.json。",
                "value": standalone_exporter_bundle.get("target", {}).get("targetCompiledPath", ""),
            })
        elif standalone_exporter_bundle.get("standaloneExporterReady"):
            blockers.append({
                "code": "HFM_CRYPTO_STANDALONE_EXPORTER_READY_FOR_INSTALL",
                "reasonZh": "独立只读 MT5 specs 导出脚本已生成；需要复制到 MT5 Scripts、编译并运行一次。",
                "value": standalone_exporter_bundle.get("bundle", {}).get("stagedScriptPath", ""),
            })
        blockers.append({
            "code": "NO_HFM_CRYPTO_SYMBOL_EVIDENCE",
            "reasonZh": "还没有 HFM 官方 crypto USD CFD 的 Bases、EA specs、registry 或 contract spec 证据。",
        })
    else:
        simulation_profile_ready = bool(moss_profile.get("profileFound")) or bool(simulation_profile_review.get("simulationQualified"))
        if not simulation_profile_ready and not rates_export_review.get("ratesReadyForSimulation"):
            for blocker in rates_export_review.get("blockers", []):
                if isinstance(blocker, dict):
                    blockers.append({**blocker, "source": "hfm_crypto_rates_export"})
        if not simulation_profile_ready:
            for blocker in simulation_profile_review.get("blockers", []):
                if isinstance(blocker, dict):
                    blockers.append({**blocker, "source": "hfm_crypto_simulation_profile"})
    status_zh = "HFM Crypto CFD 影子研究就绪"
    next_required_action_zh = "继续补 Moss/模拟 profile，并进入只读 shadow/live-readiness 审查。"
    if not symbol_evidence_found:
        status_zh = "等待 HFM Crypto CFD symbol 证据"
        next_required_action_zh = "先从 HFM MT5 导出 crypto CFD specs，或提供只读 symbol registry/contract spec JSON。"
        if account_symbols_without_crypto:
            status_zh = "当前 HFM 账号未下发 Crypto CFD symbols"
            next_required_action_zh = "需要换用开通 HFM crypto CFD 的 HFM 账号/服务器，或提供该账号真实 MT5 crypto symbol specs。"
        elif standalone_exporter_bundle.get("targetExpertInstalledAndCompiled"):
            status_zh = "等待运行独立只读 Specs 导出 EA"
            next_required_action_zh = "用 Expert 启动 QuantGod_HFMCryptoSpecExporterEA，生成 QuantGod_HFMCryptoSymbolSpecs.json 后刷新。"
        elif standalone_exporter_bundle.get("targetInstalledAndCompiled"):
            status_zh = "等待运行独立只读 Specs 导出脚本"
            next_required_action_zh = "在 MT5 Navigator/Scripts 中运行一次 QuantGod_HFMCryptoSpecExporter，生成 QuantGod_HFMCryptoSymbolSpecs.json 后刷新。"
        elif standalone_exporter_bundle.get("standaloneExporterReady"):
            status_zh = "等待安装独立只读 Specs 导出脚本/EA"
            next_required_action_zh = "把 staged 脚本/EA 复制到 MT5 Scripts/Experts、编译并运行一次，生成 QuantGod_HFMCryptoSymbolSpecs.json。"
    operator_checklist = _build_operator_checklist(
        symbol_evidence_found=symbol_evidence_found,
        broker_symbol_diagnostics=broker_symbol_diagnostics,
        moss_profile=moss_profile,
        contract_spec_export=contract_spec_export,
        execution_spec_review=execution_spec_review,
        simulation_profile_review=simulation_profile_review,
        rates_export_review=rates_export_review,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": status,
        "statusZh": status_zh,
        "nextRequiredActionZh": next_required_action_zh,
        "operatorChecklist": operator_checklist,
        "targetSymbols": local_evidence["canonicalSymbols"] or artifact_canonical_symbols or list(HFM_CRYPTO_USD_CANONICALS),
        "symbolEvidence": {
            "found": symbol_evidence_found,
            "localBasesFound": bool(local_evidence.get("found")),
            "contractSpecExportReady": bool(contract_spec_export.get("readyForContractSpecReviewInput")),
            "executionSpecReady": bool(execution_spec_review.get("readyForExecutionSpecReview")),
            "canonicalSymbols": local_evidence["canonicalSymbols"] or artifact_canonical_symbols,
            "brokerSymbols": local_evidence["brokerSymbols"] or artifact_broker_symbols,
            "sources": symbol_evidence_sources,
            "brokerSymbolDiagnostics": broker_symbol_diagnostics,
        },
        "brokerSymbolCandidates": candidate_rows,
        "staticCatalogCrypto": static_rows,
        "localEvidence": local_evidence,
        "mossBacktestProfile": moss_profile,
        "contractSpecExport": contract_spec_export,
        "standaloneExporterBundle": standalone_exporter_bundle,
        "ratesExportReview": rates_export_review,
        "simulationProfileReview": simulation_profile_review,
        "executionSpecReview": execution_spec_review,
        "shadowPlan": {
            "mode": "HFM_CRYPTO_CFD_SHADOW_ONLY",
            "source": "HFM_MT5_CRYPTO_CFD_PLUS_MOSS_BACKTEST_PROFILE",
            "pollIntervalSeconds": 60,
            "priceDiffProtectionPct": 3.0,
            "recordsOnly": True,
            "writesOrders": False,
            "reasonZh": "先把 HFM crypto CFD symbol、Moss 回测指标、策略跟随意图映射成只读资料。",
        },
        "riskBoundary": {
            "followRatio": 0.0,
            "maxNotionalUsd": 0.0,
            "stopLossPct": None,
            "autoFlattenAllowed": False,
            "operatorApprovalRequiredForExecutionLane": True,
            "reasonZh": "当前车道不触发 MT5 或 Moss 实盘执行；真钱执行必须另做隔离评审。",
        },
        "detectedRows": detected_rows,
        "blockers": blockers,
        "sourceFiles": {
            "state": str(state_path(runtime_dir)),
            "mossBacktestProfile": str(moss_backtest_path(runtime_dir)),
            "mossBacktestFileName": MOSS_BACKTEST_FILE,
            "contractSpecExport": str(contract_spec_export_path(runtime_dir)),
            "simulationProfileReview": str(simulation_profile_review_path(runtime_dir)),
            "ratesExportReview": str(rates_export_review.get("manifestPath") or ""),
            "executionSpecReview": str(execution_spec_review_path(runtime_dir)),
        },
        "safety": dict(SAFETY),
    }
    if write:
        path = state_path(runtime_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if moss_profile.get("profileFound"):
            moss_backtest_path(runtime_dir).write_text(
                json.dumps(moss_profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return payload


def read_hfm_crypto_cfd_state(runtime_dir: Path) -> dict[str, Any]:
    path = state_path(runtime_dir)
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                symbol_evidence = payload.get("symbolEvidence") if isinstance(payload.get("symbolEvidence"), dict) else {}
                if not isinstance(payload.get("operatorChecklist"), list):
                    payload["operatorChecklist"] = _build_operator_checklist(
                        symbol_evidence_found=bool(symbol_evidence.get("found")),
                        broker_symbol_diagnostics=symbol_evidence.get("brokerSymbolDiagnostics")
                        if isinstance(symbol_evidence.get("brokerSymbolDiagnostics"), dict)
                        else {},
                        moss_profile=payload.get("mossBacktestProfile")
                        if isinstance(payload.get("mossBacktestProfile"), dict)
                        else {},
                        contract_spec_export=payload.get("contractSpecExport")
                        if isinstance(payload.get("contractSpecExport"), dict)
                        else {},
                        execution_spec_review=payload.get("executionSpecReview")
                        if isinstance(payload.get("executionSpecReview"), dict)
                        else {},
                        simulation_profile_review=payload.get("simulationProfileReview")
                        if isinstance(payload.get("simulationProfileReview"), dict)
                        else {},
                        rates_export_review=payload.get("ratesExportReview")
                        if isinstance(payload.get("ratesExportReview"), dict)
                        else {},
                    )
                return {"ok": True, **payload}
    except Exception:
        pass
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "status": "WAITING_HFM_CRYPTO_BUILD",
        "statusZh": "等待构建 HFM Crypto CFD 影子车道",
        "safety": dict(SAFETY),
    }
