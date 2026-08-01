from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .builder import build_live_automation_readiness, read_live_automation_readiness
from .schema import REVIEW_PACKET_SCHEMA_VERSION, SAFETY, assert_no_execution_flags, review_packet_path, utc_now_iso


_REVIEW_PACKET_BUILD_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _check_item(item_id: str, label_zh: str, passed: bool, reason_zh: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "labelZh": label_zh,
        "status": "PASS" if passed else "BLOCKED",
        "passed": bool(passed),
        "reasonZh": reason_zh,
    }


def _cache_key(runtime_dir: Path, refresh_sources: bool) -> tuple[Any, ...]:
    readiness = runtime_dir / "agent" / "QuantGod_LiveAutomationReadiness.json"
    try:
        stat = readiness.stat()
        fingerprint: tuple[Any, ...] = (stat.st_size, stat.st_mtime_ns)
    except OSError:
        fingerprint = (None, None)
    return (str(runtime_dir.resolve()), bool(refresh_sources), *fingerprint)


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


def _review_checklist(readiness: dict[str, Any]) -> list[dict[str, Any]]:
    lane = _safe_dict(_safe_dict(readiness.get("lanes")).get("usdjpyMt5"))
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
            bool(lane.get("reviewCandidate")),
            lane.get("nextRequiredActionZh") or "USDJPY 外汇证据仍不足。",
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
    **_retired_inputs: Any,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    cache_key = _cache_key(runtime, refresh_sources)
    if not write and cache_key in _REVIEW_PACKET_BUILD_CACHE:
        return copy.deepcopy(_REVIEW_PACKET_BUILD_CACHE[cache_key])
    readiness = (
        build_live_automation_readiness(runtime, write=write, refresh_sources=refresh_sources)
        if refresh_sources
        else read_live_automation_readiness(runtime)
    )
    lane = _safe_dict(_safe_dict(readiness.get("lanes")).get("usdjpyMt5"))
    contract = _usd_jpy_contract(lane)
    candidate_count = int(bool(contract.get("reviewCandidate")))
    payload = {
        "ok": True,
        "schema": REVIEW_PACKET_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": "READY_FOR_OPERATOR_REVIEW" if candidate_count else "WAITING_FOR_REVIEW_CANDIDATE",
        "statusZh": "等待操作者审查" if candidate_count else "等待 USDJPY 外汇审查候选",
        "reviewCandidateCount": candidate_count,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "readinessStatus": readiness.get("status"),
        "readinessStatusZh": readiness.get("statusZh"),
        "contracts": {"usdjpyMt5": contract},
        "reviewChecklist": _review_checklist(readiness),
        "forbiddenOutputs": [
            "MT5 order request files",
            "MT5 preset mutation",
            "credentials",
            "Telegram command receiver",
            "webhook trade receiver",
        ],
        "nextRequiredActionZh": (
            "审查外汇 dryRunOrderIntentSpec、broker symbol、风控限制和最终 operator approval。"
            if candidate_count
            else "继续收集 USDJPY tester/forward、runtime、点差和执行反馈证据。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = review_packet_path(runtime)
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
