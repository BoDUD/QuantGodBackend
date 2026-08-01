from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .schema import SAFETY, SCHEMA_VERSION, report_path, utc_now_iso


DEFAULT_TARGET_USD = 50.0
TARGET_AGGREGATION_MODE = "FOREX_VERIFIED_USD_NET_PROFIT"

USD_EXPLICIT_KEYS = (
    "profitUsd",
    "profitUSD",
    "pnlUsd",
    "pnlUSD",
    "netUsd",
    "netUSD",
    "netProfitUsd",
    "netProfitUSD",
    "realizedPnlUsd",
    "realizedPnLUsd",
    "realizedProfitUsd",
)
CENT_EXPLICIT_KEYS = (
    "profitUSC",
    "pnlUSC",
    "netUSC",
    "netProfitUSC",
    "realizedPnlUSC",
    "realizedPnLUSC",
)
GENERIC_PROFIT_KEYS = ("profit", "pnl", "netProfit", "realizedPnl", "realizedPnL", "realizedProfit")
OUTCOME_EVENT_TOKENS = ("CLOSE", "OUTCOME", "EXIT", "HISTORY", "TRADE_JOURNAL")
ISO_CURRENCIES = {
    "AUD", "CAD", "CHF", "CNH", "EUR", "GBP", "HKD", "JPY", "MXN", "NOK", "NZD",
    "PLN", "SEK", "SGD", "TRY", "USD", "ZAR",
}


def _target_label(target_usd: float) -> str:
    value = float(target_usd)
    return f"{int(value)} USD" if value.is_integer() else f"{value:.2f} USD"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _first_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if source.get(key) not in (None, ""):
            return source.get(key)
    return None


def _runtime_roots(runtime_dir: Path, secondary_runtime_dir: Path | None) -> list[Path]:
    return _unique_paths([runtime_dir, *([secondary_runtime_dir] if secondary_runtime_dir else [])])


def _profit_source_paths(runtime_dir: Path, secondary_runtime_dir: Path | None) -> list[Path]:
    paths: list[Path] = []
    for root in _runtime_roots(runtime_dir, secondary_runtime_dir):
        paths.extend([
            root / "evidence_os" / "QuantGod_LiveExecutionFeedback.jsonl",
            root / "evidence_os" / "QuantGod_LiveExecutionFeedbackHistory.jsonl",
            root / "execution" / "QuantGod_LiveExecutionFeedback.jsonl",
            root / "execution" / "QuantGod_LiveExecutionFeedbackHistory.jsonl",
            root / "QuantGod_LiveExecutionFeedback.jsonl",
            root / "QuantGod_LiveExecutionFeedbackHistory.jsonl",
            root / "QuantGod_RuntimeTradeEvents.jsonl",
            root / "QuantGod_TradeJournal.csv",
            root / "live" / "QuantGod_USDJPYLiveLoopLedger.csv",
            root / "adaptive" / "QuantGod_USDJPYEADryRunDecisionLedger.csv",
        ])
        try:
            paths.extend(sorted(root.glob("QuantGod_CloseHistory*.csv")))
        except OSError:
            pass
    return _unique_paths(paths)


def _unique_paths(paths: Iterable[Path | None]) -> list[Path]:
    rows: list[Path] = []
    seen: set[str] = set()
    for candidate in paths:
        if candidate is None:
            continue
        path = Path(candidate)
        key = str(path)
        if key not in seen:
            seen.add(key)
            rows.append(path)
    return rows


def _load_profit_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() == ".jsonl":
            rows.extend(_read_jsonl(path))
        elif path.suffix.lower() == ".csv":
            rows.extend(_read_csv(path))
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    offset = max(1, len(lines) - 4999)
    for line_number, raw in enumerate(lines[-5000:], start=offset):
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            rows.append({**payload, "_sourceFile": str(path), "_lineNumber": line_number})
    return rows


def _read_csv(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
            return [
                {**dict(row), "_sourceFile": str(path), "_lineNumber": index}
                for index, row in enumerate(csv.DictReader(handle), start=2)
            ]
    except OSError:
        return []


def _is_forex_symbol(symbol: str) -> bool:
    normalized = re.sub(r"[^A-Z]", "", symbol.upper().lstrip("#"))
    if len(normalized) < 6:
        return False
    return normalized[:3] in ISO_CURRENCIES and normalized[3:6] in ISO_CURRENCIES


def _is_forex_row(row: dict[str, Any]) -> bool:
    market_type = str(_first_value(row, ("marketType", "assetClass", "market", "lane")) or "").upper()
    if market_type:
        if "FOREX" in market_type or "FX" == market_type:
            return True
        if any(token in market_type for token in ("DIGITAL", "TOKEN", "PREDICTION")):
            return False
    symbol = str(row.get("symbol") or row.get("Symbol") or "").strip()
    if symbol:
        return _is_forex_symbol(symbol)
    context = " ".join(
        str(row.get(key) or "")
        for key in ("strategyId", "policyId", "strategy", "_sourceFile")
    ).upper()
    if any(token in context for token in ("DIGITAL", "TOKEN", "PREDICTION")):
        return False
    return True


def _is_outcome_like(event_type: str, row: dict[str, Any]) -> bool:
    if not event_type:
        return any(key in row for key in USD_EXPLICIT_KEYS + CENT_EXPLICIT_KEYS)
    return any(token in event_type for token in OUTCOME_EVENT_TOKENS)


def _explicit_amount(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[float | None, str | None]:
    for key in keys:
        amount = _num(row.get(key))
        if amount is not None:
            return amount, key
    return None, None


def _dedupe_key(row: dict[str, Any], currency: str, amount: float) -> str:
    stable_keys = ("feedbackId", "eventId", "ticket", "dealId", "positionId", "orderId", "intentId", "policyId")
    parts = [str(row[key]) for key in stable_keys if row.get(key) not in (None, "")]
    event_type = str(row.get("eventType") or row.get("event") or row.get("type") or "")
    if parts:
        return "|".join([currency, event_type, *parts])
    clean = {key: value for key, value in row.items() if key not in {"_sourceFile", "_lineNumber"}}
    return f"{currency}|{amount}|{json.dumps(clean, ensure_ascii=False, sort_keys=True, default=str)}"


def _evidence_row(row: dict[str, Any], amount: float, currency: str, field: str) -> dict[str, Any]:
    return {
        "amount": round(float(amount), 4),
        "currency": currency,
        "field": field,
        "eventType": row.get("eventType") or row.get("event") or row.get("type"),
        "symbol": row.get("symbol") or row.get("Symbol"),
        "accountAlias": row.get("accountAlias") or row.get("account") or row.get("accountName"),
        "strategyId": row.get("strategyId") or row.get("policyId") or row.get("strategy"),
        "ticket": row.get("ticket") or row.get("dealId") or row.get("positionId") or row.get("orderId"),
        "sourceFile": row.get("_sourceFile"),
        "lineNumber": row.get("_lineNumber"),
    }


def _profit_progress(
    rows: list[dict[str, Any]],
    target_usd: float,
    profile_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    verified: list[dict[str, Any]] = list(profile_evidence or [])
    cent: list[dict[str, Any]] = []
    shadow: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in verified:
        seen.add(f"PROFILE|{row.get('sourceFile')}|{row.get('amount')}")
    for row in rows:
        if not _is_forex_row(row):
            continue
        event_type = str(row.get("eventType") or row.get("event") or row.get("type") or "").upper()
        outcome_like = _is_outcome_like(event_type, row)
        usd_amount, usd_key = _explicit_amount(row, USD_EXPLICIT_KEYS)
        cent_amount, cent_key = _explicit_amount(row, CENT_EXPLICIT_KEYS)
        currency = str(_first_value(row, ("currency", "accountCurrency", "profitCurrency")) or "").upper()
        if usd_amount is None and currency == "USD" and outcome_like:
            usd_amount, usd_key = _explicit_amount(row, GENERIC_PROFIT_KEYS)
        if cent_amount is None and currency == "USC" and outcome_like:
            cent_amount, cent_key = _explicit_amount(row, GENERIC_PROFIT_KEYS)
        if usd_amount is not None and outcome_like:
            key = _dedupe_key(row, "USD", usd_amount)
            if key not in seen:
                seen.add(key)
                verified.append(_evidence_row(row, usd_amount, "USD", usd_key or "profit"))
            continue
        if cent_amount is not None and outcome_like:
            key = _dedupe_key(row, "USC", cent_amount)
            if key not in seen:
                seen.add(key)
                cent.append(_evidence_row(row, cent_amount, "USC", cent_key or "profit"))
            continue
        profit_r = _num(_first_value(row, ("profitR", "netR", "rMultiple")))
        if profit_r is not None and outcome_like:
            shadow.append(_evidence_row(row, profit_r, "R", "profitR"))
    verified_total = round(sum(row["amount"] for row in verified), 2)
    cent_total = round(sum(row["amount"] for row in cent), 2)
    return {
        "verifiedUsdProfit": verified_total,
        "estimatedUsdFromCentAccount": round(cent_total / 100.0, 2),
        "centAccountProfitUSC": cent_total,
        "remainingUsd": round(max(0.0, float(target_usd) - verified_total), 2),
        "profitEvidenceCount": len(verified),
        "centEvidenceCount": len(cent),
        "shadowRCount": len(shadow),
        "verifiedUsdEvidence": verified[-20:],
        "centOnlyEvidence": cent[-20:],
        "shadowOnlyREvidence": shadow[-20:],
        "countingRuleZh": "仅外汇已出场事件中的明确 USD 收益计入目标；USC 与 R 只作旁证。",
    }


def _forex_profile_evidence(runtime_dir: Path, secondary_runtime_dir: Path | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in _runtime_roots(runtime_dir, secondary_runtime_dir):
        path = root / "forex" / "QuantGod_ForexMt5SimulationProfileReview.json"
        payload = _read_json(path)
        if not payload or not bool(payload.get("simulationQualified") or payload.get("qualified")):
            continue
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else payload
        metrics = profile.get("metrics") if isinstance(profile.get("metrics"), dict) else {}
        direct_metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        metrics = {**metrics, **direct_metrics}
        amount = _num(_first_value(metrics, USD_EXPLICIT_KEYS + GENERIC_PROFIT_KEYS))
        if amount is None:
            amount = _num(_first_value(profile, USD_EXPLICIT_KEYS + GENERIC_PROFIT_KEYS))
        if amount is None:
            continue
        rows.append({
            "amount": round(amount, 4),
            "currency": "USD",
            "field": "forexSimulationProfilePnlUsd",
            "eventType": "SIMULATION_PROFILE",
            "symbol": metrics.get("symbol") or profile.get("symbol") or "USDJPYc",
            "accountAlias": "forex_mt5_simulation",
            "strategyId": metrics.get("agentId") or profile.get("agentId") or profile.get("id"),
            "ticket": None,
            "sourceFile": str(path),
            "lineNumber": None,
        })
    return rows


def _forex_lane(progress: dict[str, Any], target_usd: float) -> dict[str, Any]:
    verified = float(progress.get("verifiedUsdProfit") or 0.0)
    reached = verified >= float(target_usd)
    return {
        "laneId": "forexMt5",
        "labelZh": "外汇 MT5 模拟/纸盘",
        "marketType": "forex_cfd",
        "targetUsd": round(float(target_usd), 2),
        "verifiedUsdProfit": round(verified, 2),
        "remainingUsd": round(max(0.0, float(target_usd) - verified), 2),
        "evidenceCount": int(progress.get("profitEvidenceCount") or 0),
        "targetReached": reached,
        "status": "TARGET_REACHED" if reached else "TRACKING_NOT_REACHED",
        "statusZh": "外汇收益目标已达成" if reached else "外汇收益目标尚未达成",
    }


def _normalize_blocker(blocker: Any, scope: str, source: str) -> dict[str, Any]:
    if isinstance(blocker, dict):
        return {**blocker, "scope": blocker.get("scope") or scope, "source": blocker.get("source") or source}
    return {"code": str(blocker), "reasonZh": str(blocker), "scope": scope, "source": source}


def _collect_blockers(runtime_dir: Path, secondary_runtime_dir: Path | None) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, root in enumerate(_runtime_roots(runtime_dir, secondary_runtime_dir)):
        scope = "primary" if index == 0 else "secondary"
        readiness = _read_json(root / "agent" / "QuantGod_LiveAutomationReadiness.json")
        for row in readiness.get("globalBlockers", []) if isinstance(readiness.get("globalBlockers"), list) else []:
            blockers.append(_normalize_blocker(row, scope, "live_readiness"))
        lane = readiness.get("lanes", {}).get("usdjpyMt5", {}) if isinstance(readiness.get("lanes"), dict) else {}
        for row in lane.get("reviewBlockers", []) if isinstance(lane.get("reviewBlockers"), list) else []:
            blockers.append(_normalize_blocker(row, scope, "live_readiness.usdjpyMt5"))
    unique: list[dict[str, Any]] = []
    for row in blockers:
        key = (str(row.get("scope")), str(row.get("code")))
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique[:48]


def _research_progress(runtime_dir: Path, secondary_runtime_dir: Path | None) -> dict[str, Any]:
    ga_state = _read_json(runtime_dir / "ga_factory" / "QuantGod_GAFactoryState.json")
    best = _ga_best_candidate(ga_state)
    best_overall = _ga_best_candidate(ga_state, current_only=False)
    readiness_rows = []
    for index, root in enumerate(_runtime_roots(runtime_dir, secondary_runtime_dir)):
        readiness = _read_json(root / "agent" / "QuantGod_LiveAutomationReadiness.json")
        readiness_rows.append({
            "scope": "primary" if index == 0 else "secondary",
            "runtimeDir": str(root),
            "status": readiness.get("status"),
            "statusZh": readiness.get("statusZh"),
            "reviewCandidateCount": readiness.get("reviewCandidateCount"),
            "simulationQualifiedCount": readiness.get("simulationQualifiedCount"),
        })
    return {
        "gaFactory": {
            "status": ga_state.get("status"),
            "currentGeneration": ga_state.get("currentGeneration"),
            "candidateCount": ga_state.get("candidateCount"),
            "eliteCount": ga_state.get("eliteCount"),
            "bestSeedId": best.get("seedId") or ga_state.get("bestSeedId"),
            "bestStrategyId": best.get("strategyId"),
            "bestFitness": best.get("fitness") if best else ga_state.get("bestFitness"),
            "bestGeneration": best.get("generation"),
            "bestStatus": best.get("status"),
            "bestBlockerCode": best.get("blockerCode"),
            "bestPromotionStage": best.get("promotionStage"),
            "bestOverallSeedId": best_overall.get("seedId"),
            "bestOverallStrategyId": best_overall.get("strategyId"),
            "bestOverallFitness": best_overall.get("fitness"),
            "bestOverallGeneration": best_overall.get("generation"),
        },
        "forexReadiness": readiness_rows,
    }


def _ga_best_candidate(ga_state: dict[str, Any], *, current_only: bool = True) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for key in ("eliteArchive", "lineageTree", "graveyard"):
        section = ga_state.get(key)
        if not isinstance(section, dict):
            continue
        for list_key in ("elites", "nodes", "strategies"):
            values = section.get(list_key)
            if isinstance(values, list):
                candidates.extend(row for row in values if isinstance(row, dict))
    direct = ga_state.get("bestCandidate")
    if isinstance(direct, dict):
        candidates.append(direct)
    current_generation = _num(ga_state.get("currentGeneration"))
    current = [row for row in candidates if _num(row.get("generation")) == current_generation]
    pool = (current or candidates) if current_only else candidates
    ranked = [row for row in pool if _num(row.get("fitness")) is not None]
    if not ranked:
        return {}
    best = max(ranked, key=lambda row: float(_num(row.get("fitness")) or 0.0))
    return {
        "seedId": best.get("seedId"),
        "strategyId": best.get("strategyId") or best.get("strategy"),
        "generation": _num(best.get("generation")),
        "fitness": _num(best.get("fitness")),
        "status": best.get("status"),
        "blockerCode": best.get("blockerCode"),
        "promotionStage": best.get("promotionStage"),
    }


def _live_execution_review(runtime_dir: Path) -> dict[str, Any]:
    agent = runtime_dir / "agent"
    orchestrator = _read_json(agent / "QuantGod_SimToLiveOrchestrator.json")
    cutover = _read_json(agent / "QuantGod_LiveExecutionCutoverReview.json")
    rollback = _read_json(agent / "QuantGod_LiveExecutionRollbackReview.json")
    release = _read_json(agent / "QuantGod_ReleaseReadinessRefresh.json")
    blockers: list[dict[str, Any]] = []
    for source_name, payload in (("orchestrator", orchestrator), ("cutover", cutover), ("rollback", rollback), ("release", release)):
        for row in payload.get("blockers", []) if isinstance(payload.get("blockers"), list) else []:
            blockers.append(_normalize_blocker(row, "forex", source_name))
    data_plane_ready = bool(
        orchestrator.get("dataPlaneOrchestratorReady")
        or cutover.get("dataPlaneCutoverReady")
    )
    return {
        "status": orchestrator.get("status") or cutover.get("status") or "WAITING_FOREX_EXECUTION_REVIEW",
        "statusZh": orchestrator.get("statusZh") or cutover.get("statusZh") or "等待外汇执行审查证据",
        "dataPlaneReady": data_plane_ready,
        "executionModeOnlyBlocked": bool(
            orchestrator.get("executionModeOnlyBlocked") or cutover.get("executionModeOnlyBlocked")
        ),
        "readyForLiveExecutionCutoverReview": bool(cutover.get("readyForLiveExecutionCutoverReview")),
        "readyForLiveExecutionRollbackReview": bool(rollback.get("readyForLiveExecutionRollbackReview")),
        "separateExecutionImplementationReviewReady": False,
        "releaseReady": bool(release.get("releaseReady")),
        "blockers": blockers[:24],
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
    }


def _source_manifest(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        exists = path.exists() and path.is_file()
        row: dict[str, Any] = {"path": str(path), "exists": exists}
        if exists:
            try:
                row["sizeBytes"] = path.stat().st_size
            except OSError:
                pass
        rows.append(row)
    return rows


def build_profit_target_tracker(
    runtime_dir: Path,
    *,
    secondary_runtime_dir: Path | None = None,
    report_runtime_dir: Path | None = None,
    target_usd: float = DEFAULT_TARGET_USD,
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    secondary = Path(secondary_runtime_dir) if secondary_runtime_dir else None
    report_runtime = Path(report_runtime_dir) if report_runtime_dir else runtime
    sources = _profit_source_paths(runtime, secondary)
    progress = _profit_progress(
        _load_profit_rows(sources),
        target_usd,
        _forex_profile_evidence(runtime, secondary),
    )
    lane = _forex_lane(progress, target_usd)
    lane_targets = {"forexMt5": lane}
    target_reached = bool(lane["targetReached"])
    blockers = _collect_blockers(runtime, secondary)
    live_review = _live_execution_review(secondary or runtime)
    if target_reached:
        status = "TARGET_REACHED"
    elif blockers:
        status = "TRACKING_BLOCKED_NOT_REACHED"
    elif progress["profitEvidenceCount"]:
        status = "TRACKING_NOT_REACHED"
    else:
        status = "WAITING_FOR_PROFIT_EVIDENCE"
    combined_target = {
        "targetUsd": round(float(target_usd), 2),
        "combinedVerifiedUsdProfit": lane["verifiedUsdProfit"],
        "remainingUsd": lane["remainingUsd"],
        "targetReached": target_reached,
        "status": lane["status"],
        "statusZh": lane["statusZh"],
        "countingRuleZh": "仅汇总外汇 lane 的可验证 USD 净收益。",
    }
    payload: dict[str, Any] = {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "secondaryMt5RuntimeDir": str(secondary) if secondary else None,
        "reportRuntimeDir": str(report_runtime),
        "reportPath": str(report_path(report_runtime)),
        "status": status,
        "statusZh": {
            "TARGET_REACHED": f"外汇已达到 {_target_label(target_usd)} 目标",
            "TRACKING_BLOCKED_NOT_REACHED": "外汇收益未达标，且存在 readiness 阻断",
            "TRACKING_NOT_REACHED": "正在追踪外汇收益，尚未达标",
            "WAITING_FOR_PROFIT_EVIDENCE": "等待可验证外汇收益证据",
        }[status],
        "target": {
            "targetUsd": round(float(target_usd), 2),
            "baseCurrency": "USD",
            "reasonZh": "追踪外汇策略的可验证美元净收益，达标后仅进入独立 execution review。",
            "aggregationMode": TARGET_AGGREGATION_MODE,
            "requiredLaneIds": ["forexMt5"],
        },
        "progress": progress,
        "laneTargets": lane_targets,
        "combinedTarget": combined_target,
        "targetReached": target_reached,
        "executionTargetReached": target_reached,
        "liveCutoverGate": {
            "status": "READY_FOR_EXECUTION_REVIEW" if target_reached else "WAITING_FOR_FOREX_SIM_TARGET",
            "statusZh": "外汇收益目标已达成，可进入独立执行评审" if target_reached else f"等待外汇达到模拟 {_target_label(target_usd)}",
            "combinedTargetReached": target_reached,
            "cutoverReady": bool(live_review.get("readyForLiveExecutionCutoverReview")),
            "rollbackReady": bool(live_review.get("readyForLiveExecutionRollbackReview")),
            "orderSendAllowed": False,
            "reasonZh": "收益达标不授权实盘；本追踪器不写订单、不改预设。",
        },
        "blockers": blockers,
        "researchProgress": _research_progress(runtime, secondary),
        "liveExecutionReview": live_review,
        "simToLiveDecision": {
            "targetReached": target_reached,
            "dataPlaneReady": bool(live_review.get("dataPlaneReady")),
            "executionModeOnlyBlocked": bool(live_review.get("executionModeOnlyBlocked")),
            "canPromoteToLiveNow": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "nextRequiredActionZh": "继续补齐外汇 tester/forward、runtime 与 release 证据；真实执行保持关闭。",
        },
        "sourceFiles": _source_manifest(sources),
        "nextRequiredActionZh": (
            "外汇收益已达标；进入独立 execution review，仍禁止订单与 preset 变更。"
            if target_reached
            else "继续收集外汇已出场 USD 收益，并修复 readiness blocker。"
        ),
        "safety": dict(SAFETY),
    }
    if write:
        out = report_path(report_runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_profit_target_tracker(runtime_dir: Path) -> dict[str, Any]:
    path = report_path(Path(runtime_dir))
    payload = _read_json(path)
    if payload:
        return payload
    return {
        "ok": False,
        "schema": SCHEMA_VERSION,
        "reportExists": False,
        "reportPath": str(path),
        "safety": dict(SAFETY),
    }
