from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .builder import build_live_automation_readiness, read_live_automation_readiness
from .schema import (
    REVIEW_PACKET_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    review_packet_path,
    utc_now_iso,
)

_REVIEW_PACKET_BUILD_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str) -> dict[str, Any]:
    return {"code": code, "reasonZh": reason_zh}


def _path_fingerprint(value: str) -> tuple[Any, ...]:
    if not value:
        return ("", None, None)
    path = Path(value)
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_size, stat.st_mtime_ns)


def _dir_fingerprint(path: Path) -> tuple[Any, ...]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns)


def _review_packet_cache_key(
    runtime_dir: Path,
    *,
    refresh_sources: bool,
    moss_backtest_json: str,
    hfm_simulation_profile_json: str,
    hfm_contract_spec_json: str,
    extra_bases_roots: list[str],
) -> tuple[Any, ...]:
    return (
        str(runtime_dir.resolve()),
        bool(refresh_sources),
        _path_fingerprint(moss_backtest_json),
        _path_fingerprint(hfm_simulation_profile_json),
        _path_fingerprint(hfm_contract_spec_json),
        tuple(_dir_fingerprint(Path(root)) for root in extra_bases_roots),
        _dir_fingerprint(runtime_dir / "Bases"),
        _path_fingerprint(str(review_packet_path(runtime_dir))),
    )


def _check_item(item_id: str, label_zh: str, passed: bool, reason_zh: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "labelZh": label_zh,
        "status": "PASS" if passed else "BLOCKED",
        "passed": passed,
        "reasonZh": reason_zh,
    }


def _ordered_unique(values: list[Any]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def _canonical_from_broker_symbol(value: str) -> str:
    text = str(value or "").upper()
    text = text.lstrip("#")
    return "".join(ch for ch in text if ch.isalnum())


def _hfm_profile_text(lane: dict[str, Any]) -> str:
    shadow = _safe_dict(lane.get("shadowLane"))
    state = _safe_dict(shadow.get("hfmCryptoCfdState"))
    simulation_review = _safe_dict(lane.get("simulationProfileReview") or state.get("simulationProfileReview"))
    profile = _safe_dict(simulation_review.get("profile"))
    metrics = _safe_dict(profile.get("metrics") or simulation_review.get("metrics"))
    return json.dumps({**profile, **metrics}, ensure_ascii=False).upper()


def _preferred_hfm_canonical_symbol(lane: dict[str, Any], symbols: list[str]) -> str:
    symbol_set = {str(item).upper() for item in symbols}
    profile_text = _hfm_profile_text(lane)
    if "BTCUSD" in profile_text and "BTCUSD" in symbol_set:
        return "BTCUSD"
    if "BTCUSD" in symbol_set:
        return "BTCUSD"
    return symbols[0] if symbols else ""


def _order_hfm_symbols(lane: dict[str, Any], symbols: list[str]) -> list[str]:
    ordered = _ordered_unique(symbols)
    preferred = _preferred_hfm_canonical_symbol(lane, ordered)
    if not preferred:
        return ordered
    return [preferred, *[item for item in ordered if item != preferred]]


def _hfm_broker_symbols(lane: dict[str, Any], canonical_symbols: list[str]) -> list[str]:
    shadow = _safe_dict(lane.get("shadowLane"))
    state = _safe_dict(shadow.get("hfmCryptoCfdState"))
    local = _safe_dict(state.get("localEvidence"))
    contract_spec_export = _safe_dict(lane.get("contractSpecExport") or state.get("contractSpecExport"))
    execution_spec = _safe_dict(lane.get("executionSpecReview") or state.get("executionSpecReview"))
    all_symbols = _ordered_unique([
        *_safe_list(local.get("brokerSymbols")),
        *_safe_list(execution_spec.get("coveredBrokerSymbols")),
        *_safe_list(contract_spec_export.get("coveredBrokerSymbols")),
    ])
    candidates = _safe_list(state.get("brokerSymbolCandidates"))
    for row in candidates:
        if isinstance(row, dict) and row.get("brokerSymbol"):
            all_symbols.append(str(row.get("brokerSymbol")))
    all_symbols = _ordered_unique(all_symbols)
    preferred_canonical = _preferred_hfm_canonical_symbol(lane, canonical_symbols)
    if not preferred_canonical:
        return all_symbols
    exact = [item for item in all_symbols if _canonical_from_broker_symbol(item) == preferred_canonical]
    rest = [item for item in all_symbols if item not in set(exact)]
    return [*exact, *rest]


def _hfm_canonical_symbols(lane: dict[str, Any]) -> list[str]:
    shadow = _safe_dict(lane.get("shadowLane"))
    state = _safe_dict(shadow.get("hfmCryptoCfdState"))
    local = _safe_dict(state.get("localEvidence"))
    found = [str(item) for item in _safe_list(local.get("canonicalSymbols")) if item]
    if found:
        return _order_hfm_symbols(lane, found)
    return _order_hfm_symbols(lane, [str(item) for item in _safe_list(state.get("targetSymbols")) if item])


def _usd_jpy_contract(lane: dict[str, Any]) -> dict[str, Any]:
    top = _safe_dict(lane.get("topPolicy"))
    gate = _safe_dict(lane.get("usdDeploymentGate"))
    review_candidate = bool(lane.get("reviewCandidate"))
    return {
        "lane": "USDJPY_MT5",
        "status": "READY_FOR_REVIEW" if review_candidate else "WAITING_EVIDENCE",
        "reviewCandidate": review_candidate,
        "broker": {
            "platform": "MT5",
            "brokerFamily": "HFM",
            "accountLane": "standard_usd_after_cent_validation",
            "credentialMode": "external_env_reference_only",
            "storesCredentials": False,
        },
        "scope": {
            "canonicalSymbols": ["USDJPY"],
            "brokerSymbols": ["USDJPYc"],
            "strategyLock": "RSI_Reversal",
            "directionLock": "LONG",
            "allowedEntryModes": ["STANDARD_ENTRY"],
        },
        "dryRunOrderIntentSpec": {
            "schema": "quantgod.mt5_dry_order_intent_spec.v1",
            "writesMt5OrderRequest": False,
            "dryRunOnly": True,
            "source": "usdDeploymentGate.topPolicy",
            "requiredFields": [
                "intentId",
                "lane",
                "canonicalSymbol",
                "brokerSymbol",
                "side",
                "orderType",
                "volumeLots",
                "entryMode",
                "stopLoss",
                "takeProfit",
                "maxSpreadPips",
                "maxSlippagePips",
                "killSwitchOk",
                "dailyLossOk",
                "runtimeFresh",
                "newsGateNone",
                "operatorApprovalId",
            ],
            "example": {
                "lane": "USDJPY_MT5",
                "canonicalSymbol": "USDJPY",
                "brokerSymbol": "USDJPYc",
                "side": "buy" if str(top.get("direction") or "LONG").upper() == "LONG" else "sell",
                "orderType": "market_or_ea_owned_entry",
                "volumeLots": gate.get("recommendedLot", 0.0),
                "entryMode": top.get("entryMode", "BLOCKED"),
                "maxSpreadPips": 2.2,
                "maxSlippagePips": 1.0,
            },
        },
        "riskLimits": {
            "recommendedLot": gate.get("recommendedLot", 0.0),
            "maxLot": gate.get("maxLot", 0.0),
            "maxDailyLossR": 1.0,
            "maxConsecutiveLosses": 2,
            "normalSpreadOnly": True,
            "newsNoneOnly": True,
            "centValidation": _safe_dict(gate.get("centValidation")),
        },
        "blockers": _safe_list(lane.get("reviewBlockers")),
        "safety": dict(SAFETY),
    }


def _hfm_crypto_contract(lane: dict[str, Any]) -> dict[str, Any]:
    shadow = _safe_dict(lane.get("shadowLane"))
    state = _safe_dict(shadow.get("hfmCryptoCfdState"))
    contract_spec_export = _safe_dict(lane.get("contractSpecExport") or state.get("contractSpecExport"))
    execution_spec = _safe_dict(lane.get("executionSpecReview") or state.get("executionSpecReview"))
    simulation_review = _safe_dict(lane.get("simulationProfileReview") or state.get("simulationProfileReview"))
    shadow_plan = _safe_dict(state.get("shadowPlan"))
    risk_boundary = _safe_dict(state.get("riskBoundary"))
    canonical_symbols = _hfm_canonical_symbols(lane)
    broker_symbols = _hfm_broker_symbols(lane, canonical_symbols)
    broker_symbol = broker_symbols[0] if broker_symbols else ""
    review_candidate = bool(lane.get("reviewCandidate"))
    return {
        "lane": "HFM_CRYPTO_CFD",
        "status": "READY_FOR_REVIEW" if review_candidate else "WAITING_EVIDENCE",
        "reviewCandidate": review_candidate,
        "broker": {
            "platform": "MT5",
            "brokerFamily": "HFM",
            "marketType": "crypto_cfd",
            "credentialMode": "external_env_reference_only",
            "storesCredentials": False,
        },
        "scope": {
            "canonicalSymbols": canonical_symbols,
            "brokerSymbols": broker_symbols,
            "copyOrSignalSource": "Moss profile metadata only",
            "allowedDirectionModes": ["long", "short", "flat"],
        },
        "dryRunOrderIntentSpec": {
            "schema": "quantgod.hfm_crypto_dry_order_intent_spec.v1",
            "writesMt5OrderRequest": False,
            "dryRunOnly": True,
            "requiredFields": [
                "intentId",
                "lane",
                "canonicalSymbol",
                "brokerSymbol",
                "side",
                "orderType",
                "volumeLots",
                "referencePrice",
                "stopLoss",
                "takeProfit",
                "priceDiffProtectionPct",
                "maxNotionalUsd",
                "contractSpecReviewed",
                "fundingFeePolicyReviewed",
                "operatorApprovalId",
            ],
            "example": {
                "lane": "HFM_CRYPTO_CFD",
                "canonicalSymbol": canonical_symbols[0] if canonical_symbols else "",
                "brokerSymbol": broker_symbol,
                "side": "mirror_signal_only",
                "orderType": "dry_run_market_or_limit",
                "volumeLots": 0.0,
                "priceDiffProtectionPct": shadow_plan.get("priceDiffProtectionPct", 3.0),
                "maxNotionalUsd": 0.0,
            },
        },
        "riskLimits": {
            "followRatio": risk_boundary.get("followRatio", 0.0),
            "maxNotionalUsd": risk_boundary.get("maxNotionalUsd", 0.0),
            "priceDiffProtectionPct": shadow_plan.get("priceDiffProtectionPct", 3.0),
            "autoFlattenAllowed": False,
            "maxDailyLossPct": 1.0,
            "maxConsecutiveLosses": 2,
        },
        "contractSpecReview": {
            "requiredBeforeAnyLiveOrder": [
                "broker_symbol_resolution",
                "contract_size_and_tick_value",
                "min_lot_lot_step_max_lot",
                "spread_and_slippage_limits",
                "swap_or_funding_fee_policy",
                "session_and_weekend_gap_policy",
                "per_symbol_notional_cap",
            ],
            "currentEvidence": {
                "symbolEvidenceFound": bool(lane.get("symbolEvidenceFound")),
                "detectedSymbolCount": lane.get("detectedSymbolCount", 0),
                "mossProfileFound": bool(lane.get("mossProfileFound")),
                "mossMetrics": _safe_dict(lane.get("mossMetrics")),
                "simulationProfileQualified": bool(lane.get("simulationProfileQualified")),
                "simulationProfileStatus": simulation_review.get("status"),
                "simulationProfileBlockerCount": len(_safe_list(simulation_review.get("blockers"))),
                "contractSpecExportReady": bool(contract_spec_export.get("readyForContractSpecReviewInput")),
                "contractSpecExportStatus": contract_spec_export.get("status"),
                "contractSpecExportValidRowCount": contract_spec_export.get("validRowCount", 0),
                "executionSpecReady": bool(lane.get("executionSpecReady")),
                "executionSpecStatus": execution_spec.get("status"),
                "executionSpecValidRowCount": execution_spec.get("validRowCount", 0),
                "executionSpecCoveredBrokerSymbols": _safe_list(execution_spec.get("coveredBrokerSymbols")),
                "executionSpecBlockerCount": len(_safe_list(execution_spec.get("blockers"))),
            },
        },
        "blockers": _safe_list(lane.get("reviewBlockers")),
        "safety": dict(SAFETY),
    }


def _review_checklist(readiness: dict[str, Any]) -> list[dict[str, Any]]:
    lanes = _safe_dict(readiness.get("lanes"))
    usd = _safe_dict(lanes.get("usdjpyMt5"))
    hfm = _safe_dict(lanes.get("hfmCryptoCfd"))
    return [
        _check_item(
            "readiness_dossier_available",
            "准入档案可生成",
            bool(readiness.get("ok")),
            "已生成 readiness dossier。" if readiness.get("ok") else "缺少 readiness dossier。",
        ),
        _check_item(
            "usd_jpy_review_candidate",
            "USDJPY MT5 可进入执行审查",
            bool(usd.get("reviewCandidate")),
            usd.get("nextRequiredActionZh") or "USDJPY 证据仍不足。",
        ),
        _check_item(
            "hfm_crypto_review_candidate",
            "HFM Crypto CFD 可进入执行审查",
            bool(hfm.get("reviewCandidate")),
            hfm.get("nextRequiredActionZh") or "HFM crypto 证据仍不足。",
        ),
        _check_item(
            "no_direct_execution",
            "当前包不产生订单",
            not bool(readiness.get("canPromoteToLiveNow")),
            "审查包只描述未来执行合约，不写订单请求。",
        ),
    ]


def build_live_execution_review_packet(
    runtime_dir: Path,
    *,
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    cache_key = _review_packet_cache_key(
        runtime_dir,
        refresh_sources=refresh_sources,
        moss_backtest_json=moss_backtest_json,
        hfm_simulation_profile_json=hfm_simulation_profile_json,
        hfm_contract_spec_json=hfm_contract_spec_json,
        extra_bases_roots=extra_bases_roots or [],
    )
    if not write and cache_key in _REVIEW_PACKET_BUILD_CACHE:
        return copy.deepcopy(_REVIEW_PACKET_BUILD_CACHE[cache_key])
    readiness = (
        build_live_automation_readiness(
            runtime_dir,
            write=write,
            refresh_sources=refresh_sources,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if refresh_sources or moss_backtest_json or hfm_simulation_profile_json or hfm_contract_spec_json or extra_bases_roots
        else read_live_automation_readiness(runtime_dir)
    )
    lanes = _safe_dict(readiness.get("lanes"))
    usd_contract = _usd_jpy_contract(_safe_dict(lanes.get("usdjpyMt5")))
    hfm_contract = _hfm_crypto_contract(_safe_dict(lanes.get("hfmCryptoCfd")))
    candidate_count = int(bool(usd_contract.get("reviewCandidate"))) + int(bool(hfm_contract.get("reviewCandidate")))
    payload = {
        "ok": True,
        "schema": REVIEW_PACKET_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "READY_FOR_OPERATOR_REVIEW" if candidate_count else "WAITING_FOR_REVIEW_CANDIDATE",
        "statusZh": "等待操作者审查" if candidate_count else "等待审查候选",
        "reviewCandidateCount": candidate_count,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "readinessStatus": readiness.get("status"),
        "readinessStatusZh": readiness.get("statusZh"),
        "contracts": {
            "usdjpyMt5": usd_contract,
            "hfmCryptoCfd": hfm_contract,
        },
        "reviewChecklist": _review_checklist(readiness),
        "forbiddenOutputs": [
            "MT5 order request files",
            "MT5 preset mutation",
            "wallet authorization links",
            "private keys or mnemonics",
            "Telegram command receiver",
            "webhook trade receiver",
        ],
        "nextRequiredActionZh": (
            "审查 dryRunOrderIntentSpec、broker symbol、合约规格、风控限制和最终 operator approval。"
            if candidate_count
            else "继续收集模拟、symbol、Moss profile、runtime、点差和执行反馈证据。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = review_packet_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        _REVIEW_PACKET_BUILD_CACHE[cache_key] = copy.deepcopy(payload)
    return payload


def read_live_execution_review_packet(runtime_dir: Path) -> dict[str, Any]:
    path = review_packet_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_live_execution_review_packet(Path(runtime_dir), write=False)
