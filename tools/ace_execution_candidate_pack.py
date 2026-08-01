"""Build a read-only USDJPY forex execution-candidate review packet."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "quantgod.ace_execution_candidate_pack.v1"
REPORT_PATH = Path("agent") / "QuantGod_AceExecutionCandidatePack.json"

SAFETY = {
    "readOnly": True,
    "shadowOnly": True,
    "testerOnly": True,
    "advisoryOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "writesMt5OrderReceipt": False,
    "writesLivePreset": False,
    "livePresetMutationAllowed": False,
    "brokerCallsMade": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _metrics(source: dict[str, Any]) -> dict[str, Any]:
    backtest = _dict(source.get("backtest"))
    walk_forward = _dict(source.get("walkForward"))
    return {
        "fitness": source.get("fitness"),
        "netR": backtest.get("netR", source.get("netR")),
        "profitFactor": backtest.get("profitFactor", source.get("profitFactor")),
        "sharpe": backtest.get("sharpe", source.get("sharpe")),
        "maxDrawdownR": backtest.get("maxDrawdownR", source.get("maxDrawdownR")),
        "tradeCount": backtest.get("tradeCount", source.get("tradeCount")),
        "effectiveSampleCount": backtest.get("effectiveSampleCount", source.get("effectiveSampleCount")),
        "walkForwardStability": walk_forward.get("stabilityScore", source.get("walkForwardStability")),
        "forwardNetR": walk_forward.get("forwardNetR", source.get("forwardNetR")),
    }


def _forex_pack(scout: dict[str, Any], retest: dict[str, Any], tpsl: dict[str, Any]) -> dict[str, Any]:
    observed = _dict(scout.get("topQualifiedForex"))
    champion = _dict(retest.get("forexChampion"))
    source = champion if champion.get("seedId") else observed
    optimizer = _dict(tpsl.get("forexMt5"))
    blockers = list(dict.fromkeys([
        *[str(code) for code in _list(source.get("blockers")) if code],
        *[str(code) for code in _list(optimizer.get("blockers")) if code],
    ]))
    return {
        "lane": "forexMt5",
        "role": "primaryForexAce",
        "status": source.get("status") or ("FOREX_ACE_CANDIDATE_READY" if source else "FOREX_ACE_MISSING"),
        "seedId": source.get("seedId"),
        "strategyId": source.get("strategyId"),
        "strategyFamily": source.get("strategyFamily") or "RSI_Reversal",
        "direction": source.get("direction") or "LONG",
        "metrics": _metrics(source),
        "contenderReview": _dict(scout.get("forexContenderReview")) or _dict(retest.get("forexContenderReview")),
        "recommendedTpSl": _dict(optimizer.get("recommended")),
        "testerVariantQueue": _list(optimizer.get("testerVariantQueue")),
        "blockers": blockers,
        "reviewCandidate": bool(source) and not blockers,
        "nextActionZh": "进入隔离 MT5 tester/forward 复验；不直接升级实盘。",
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _strategy_shortlist(forex: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if forex.get("seedId") or forex.get("strategyId"):
        rows.append({
            "lane": "forexMt5",
            "role": "primaryChampion",
            "seedId": forex.get("seedId"),
            "strategyId": forex.get("strategyId"),
            "strategyFamily": forex.get("strategyFamily"),
            "direction": forex.get("direction"),
            "status": forex.get("status"),
            "metrics": _dict(forex.get("metrics")),
            "blockers": _list(forex.get("blockers")),
            "testerOnly": True,
            "orderSendAllowed": False,
        })
    for index, contender in enumerate(_list(_dict(forex.get("contenderReview")).get("contenders"))[:2], start=1):
        row = _dict(contender)
        if row.get("seedId") == forex.get("seedId"):
            continue
        rows.append({
            "lane": "forexMt5",
            "role": f"parallelContender{index}",
            "seedId": row.get("seedId"),
            "strategyId": row.get("strategyId"),
            "strategyFamily": row.get("strategyFamily"),
            "direction": row.get("direction"),
            "status": row.get("status"),
            "metrics": _metrics(row),
            "blockers": _list(row.get("blockers")),
            "testerOnly": True,
            "orderSendAllowed": False,
        })
    return {
        "status": "FOREX_SHORTLIST_READY" if rows else "FOREX_SHORTLIST_MISSING",
        "forexTopStrategies": rows,
        "comparisonRequired": len(rows) > 1,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _rsi_demotion_review(scout: dict[str, Any], forex: dict[str, Any]) -> dict[str, Any]:
    raw = next(
        (_dict(row) for row in _list(scout.get("candidates")) if _dict(row).get("lane") == "live12_raw_rsi"),
        {},
    )
    blockers = _list(raw.get("blockers"))
    demote = bool(not raw or raw.get("decision") == "DISCARD_AS_ACE" or blockers)
    return {
        "status": "RSI_LIVE_LOGIC_DEMOTE_REVIEW" if demote else "RSI_LIVE_LOGIC_KEEP_REVIEW",
        "lane": "live12_raw_rsi",
        "decision": raw.get("decision") or ("MISSING_FROM_ACE_SCOUT" if not raw else None),
        "recommendedAction": "DEMOTE_RAW_RSI_FROM_ACE" if demote else "KEEP_RAW_RSI_SHADOW_REVIEW",
        "recommendedActionZh": "raw RSI 保留 shadow/review；替代候选必须先通过隔离 tester/forward。",
        "currentEvidence": raw,
        "replacementPlan": {
            "primaryForexAce": forex,
            "nextActionZh": "只复验 USDJPY 外汇候选；不写订单、不改 live preset。",
        },
        "safety": dict(SAFETY),
    }


def build_ace_execution_candidate_pack(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    agent = runtime / "agent"
    try:
        from tools.ace_strategy_scout import read_ace_strategy_scout
    except ModuleNotFoundError:  # pragma: no cover
        from ace_strategy_scout import read_ace_strategy_scout
    scout = _dict(read_ace_strategy_scout(runtime))
    retest = _read_json(agent / "QuantGod_ChampionRetestReport.json")
    tpsl = _read_json(agent / "QuantGod_TpSlOptimizerReport.json")
    run_gate = _read_json(agent / "QuantGod_ChampionTesterRunGate.json")
    preflight = _read_json(agent / "QuantGod_LiveRuntimePreflightProbe.json")
    profit_target = _read_json(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json")
    forex = _forex_pack(scout, retest, tpsl)
    shortlist = _strategy_shortlist(forex)
    rsi_review = _rsi_demotion_review(scout, forex)
    selected = {
        "lane": "forexMt5",
        "seedId": forex.get("seedId"),
        "strategyId": forex.get("strategyId"),
        "strategyFamily": forex.get("strategyFamily"),
        "direction": forex.get("direction"),
        "status": forex.get("status"),
        "metrics": _dict(forex.get("metrics")),
        "testerVariantQueue": _list(forex.get("testerVariantQueue")),
    }
    blockers = list(dict.fromkeys([
        *[str(code) for code in _list(forex.get("blockers")) if code],
        *[str(code) for code in _list(_dict(run_gate.get("gate")).get("blockers")) if isinstance(code, str)],
    ]))
    payload = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "status": "ACE_EXECUTION_CANDIDATE_PACK_READY" if forex.get("seedId") else "ACE_EXECUTION_CANDIDATE_PACK_WAITING_EVIDENCE",
        "statusZh": "USDJPY 外汇王牌候选包已生成" if forex.get("seedId") else "等待 USDJPY 外汇王牌证据",
        "forexMt5": forex,
        "strategyShortlist": shortlist,
        "rsiDemotionReview": rsi_review,
        "liveUpgradeSelection": {
            "status": "FOREX_TESTER_REVIEW_READY" if forex.get("reviewCandidate") else "FOREX_TESTER_REVIEW_BLOCKED",
            "statusZh": "外汇候选进入 tester 审查" if forex.get("reviewCandidate") else "外汇候选仍需补证据",
            "selectedLane": "forexMt5",
            "selectedStrategy": selected,
            "excludedAceCandidates": [],
            "upgradePrerequisites": [
                "isolated_tester_forward_report_ready",
                "champion_tester_run_gate_ready",
                "separate_execution_release_lane_ready",
            ],
            "nextActionZh": "先完成隔离 tester/forward，再进入独立 release review。",
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "writesLivePreset": False,
        },
        "executionReadinessBoard": {
            "status": "FOREX_REVIEW_READY" if forex.get("reviewCandidate") else "FOREX_REVIEW_BLOCKED",
            "selectedLaneForSeparateReleaseReview": "forexMt5" if forex.get("reviewCandidate") else None,
            "closestResearchLaneNow": "forexMt5",
            "laneSnapshots": [{
                "lane": "forexMt5",
                "reviewCandidate": bool(forex.get("reviewCandidate")),
                "blockers": _list(forex.get("blockers")),
            }],
            "primaryClosureQueue": blockers,
            "runtimePreflightStatus": preflight.get("status"),
            "testerRunGateStatus": run_gate.get("status"),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "profitTargetSummary": {
            "status": profit_target.get("status"),
            "targetReached": bool(profit_target.get("targetReached")),
            "verifiedForexProfitUsd": _dict(profit_target.get("progress")).get("verifiedForexProfitUsd"),
        },
        "finalVerdict": {
            "selectedLane": "forexMt5",
            "selectedStrategy": selected,
            "blockers": blockers,
            "canPromoteToLiveNow": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "nextActionZh": "继续补 tester/forward 与 release 证据；当前禁止实盘写入。",
        },
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, payload)
    return payload


def read_ace_execution_candidate_pack(runtime_dir: Path) -> dict[str, Any]:
    payload = _read_json(Path(runtime_dir) / REPORT_PATH)
    return payload if payload else build_ace_execution_candidate_pack(Path(runtime_dir), write=False)
