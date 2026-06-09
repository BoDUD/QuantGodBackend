from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from .schema import SAFETY, SCHEMA_VERSION, report_path, utc_now_iso

try:  # pragma: no cover - direct script fallback only.
    from tools.mt5_readonly_bridge import runtime_dir_candidates as mt5_runtime_dir_candidates
except Exception:  # pragma: no cover
    try:
        from mt5_readonly_bridge import runtime_dir_candidates as mt5_runtime_dir_candidates
    except Exception:
        mt5_runtime_dir_candidates = None


DEFAULT_TARGET_USD = 50.0
TARGET_AGGREGATION_MODE = "ANY_LANE_OR_COMBINED_NET_PROFIT"


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
GENERIC_PROFIT_KEYS = (
    "profit",
    "pnl",
    "netProfit",
    "realizedPnl",
    "realizedPnL",
    "realizedProfit",
)
OUTCOME_EVENT_TOKENS = (
    "CLOSE",
    "OUTCOME",
    "EXIT",
    "HISTORY",
    "TRADE_JOURNAL",
)


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "y", "on", "是"}


def _repo_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime"


def _include_global_mt5_candidates(runtime_dir: Path) -> bool:
    if _truthy_env("QG_PROFIT_TRACKER_INCLUDE_GLOBAL_MT5") or _truthy_env("QG_USDJPY_INCLUDE_GLOBAL_MT5"):
        return True
    try:
        return runtime_dir.resolve() == _repo_runtime_dir().resolve()
    except Exception:
        return False


def _candidate_roots(runtime_dir: Path) -> list[Path]:
    candidates = [runtime_dir]
    if _include_global_mt5_candidates(runtime_dir) and mt5_runtime_dir_candidates:
        candidates.extend(mt5_runtime_dir_candidates())
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        try:
            key = str(candidate.expanduser().resolve())
        except Exception:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique
CRYPTO_BASES = {
    "AAVE",
    "ADA",
    "ALGO",
    "APT",
    "ATOM",
    "AVAX",
    "BCH",
    "BNB",
    "BTC",
    "CRV",
    "DOGE",
    "DOT",
    "ETC",
    "ETH",
    "FET",
    "FIL",
    "FLOW",
    "GALA",
    "GRT",
    "HBAR",
    "ICP",
    "IMX",
    "IOTA",
    "LINK",
    "LTC",
    "NEAR",
    "NEO",
    "SAND",
    "SHIB",
    "SOL",
    "THETA",
    "TON",
    "TRX",
    "UNI",
    "VET",
    "XLM",
    "XMR",
    "XRP",
    "XTZ",
}
LANE_DEFINITIONS = {
    "forexMt5": {
        "labelZh": "外币 MT5 模拟/纸盘",
        "marketType": "forex_cfd",
        "reasonZh": "外币系统可单独达到 {targetLabel}，也可与其他 lane 净合计达到目标。",
    },
    "btcCryptoCfd": {
        "labelZh": "BTC / HFM crypto CFD 模拟",
        "marketType": "crypto_cfd",
        "reasonZh": "BTC/crypto CFD 系统可单独达到 {targetLabel}，也可与其他 lane 净合计达到目标。",
    },
}


def _target_label(target_usd: float) -> str:
    value = float(target_usd)
    if value.is_integer():
        return f"{int(value)} USD"
    return f"{value:.2f} USD"


def build_profit_target_tracker(
    runtime_dir: Path,
    *,
    hfm_runtime_dir: Path | None = None,
    report_runtime_dir: Path | None = None,
    target_usd: float = DEFAULT_TARGET_USD,
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    hfm_runtime = Path(hfm_runtime_dir) if hfm_runtime_dir else None
    report_runtime = Path(report_runtime_dir) if report_runtime_dir else runtime
    sources = _profit_source_paths(runtime, hfm_runtime)
    rows = _load_profit_rows(sources)
    progress = _profit_progress(rows, target_usd)
    lane_targets = _lane_target_progress(runtime, rows, target_usd, hfm_runtime)
    blockers = _collect_blockers(runtime, hfm_runtime)
    research = _research_progress(runtime, hfm_runtime)
    live_review = _live_execution_review(hfm_runtime or runtime)
    combined_target = _combined_target_progress(lane_targets, target_usd)
    target_reached = bool(combined_target["targetReached"])
    status = _status(target_reached, progress["profitEvidenceCount"], blockers)
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "hfmRuntimeDir": str(hfm_runtime) if hfm_runtime else None,
        "reportRuntimeDir": str(report_runtime),
        "reportPath": str(report_path(report_runtime)),
        "status": status,
        "statusZh": _status_zh(status, target_usd),
        "target": {
            "targetUsd": round(float(target_usd), 2),
            "baseCurrency": "USD",
            "reasonZh": "追踪“外币或 BTC/crypto 任一合格 lane 可单独达标，也可用多 lane 可验证美元净收益合计达标，再进入下一阶段”的收益目标。",
            "aggregationMode": TARGET_AGGREGATION_MODE,
            "combinedTargetUsd": round(float(target_usd), 2),
            "requiredLaneIds": list(lane_targets.keys()),
            "allRequiredLanesMustReachTarget": False,
            "allRequiredLanesMustBePositive": False,
            "anySingleLaneCanReachTarget": True,
            "combinedNetCanReachTarget": True,
        },
        "progress": progress,
        "laneTargets": lane_targets,
        "combinedTarget": combined_target,
        "targetReached": target_reached,
        "dualTargetReached": target_reached and "btcCryptoCfd" in lane_targets,
        "executionTargetReached": target_reached,
        "liveCutoverGate": {
            "status": (
                "READY_FOR_CUTOVER_IMPLEMENTATION_REVIEW"
                if target_reached and live_review.get("separateExecutionImplementationReviewReady")
                else "READY_FOR_EXECUTION_REVIEW"
                if target_reached
                else "WAITING_FOR_ALL_SIM_TARGETS"
            ),
            "statusZh": (
                "收益目标已达成，cutover/rollback 审查链已就绪，可进入单独实现评审"
                if target_reached and live_review.get("separateExecutionImplementationReviewReady")
                else "任一 lane 或多 lane 净合计收益目标已达成，可进入单独 execution lane 评审"
                if target_reached
                else f"等待任一 lane 或多 lane 净合计达到模拟 {_target_label(target_usd)}"
            ),
            "allLaneTargetsReached": target_reached,
            "combinedTargetReached": target_reached,
            "cutoverReady": bool(live_review.get("readyForLiveExecutionCutoverReview")),
            "rollbackReady": bool(live_review.get("readyForLiveExecutionRollbackReview")),
            "separateExecutionImplementationReviewReady": bool(live_review.get("separateExecutionImplementationReviewReady")),
            "orderSendAllowed": False,
            "reasonZh": "达到模拟收益目标只代表可进入实盘执行评审；本追踪器不写订单、不改预设。",
        },
        "blockers": blockers,
        "researchProgress": research,
        "liveExecutionReview": live_review,
        "simToLiveDecision": _sim_to_live_decision(
            target_reached=target_reached,
            lane_targets=lane_targets,
            live_review=live_review,
            target_usd=target_usd,
        ),
        "sourceFiles": _source_manifest(sources),
        "nextRequiredActionZh": _next_required_action(target_reached, blockers, research, lane_targets, live_review),
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
        "schema": SCHEMA_VERSION,
        "ok": False,
        "reportExists": False,
        "reportPath": str(path),
        "safety": dict(SAFETY),
    }


def _status(target_reached: bool, evidence_count: int, blockers: list[dict[str, Any]]) -> str:
    if target_reached:
        return "TARGET_REACHED"
    if blockers:
        return "TRACKING_BLOCKED_NOT_REACHED"
    if evidence_count:
        return "TRACKING_NOT_REACHED"
    return "WAITING_FOR_PROFIT_EVIDENCE"


def _status_zh(status: str, target_usd: float) -> str:
    return {
        "TARGET_REACHED": f"已达到合计 {_target_label(target_usd)} 目标",
        "TRACKING_BLOCKED_NOT_REACHED": "未达到目标，且当前存在实盘/模拟阻断",
        "TRACKING_NOT_REACHED": "正在追踪，尚未达到目标",
        "WAITING_FOR_PROFIT_EVIDENCE": "等待可验证收益证据",
    }.get(status, status)


def _profit_source_paths(runtime_dir: Path, hfm_runtime_dir: Path | None) -> list[Path]:
    roots = [runtime_dir]
    if hfm_runtime_dir and hfm_runtime_dir != runtime_dir:
        roots.append(hfm_runtime_dir)
    paths: list[Path] = []
    for root in roots:
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


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    rows: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            rows.append(path)
    return rows


def _load_profit_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        suffix = path.suffix.lower()
        if suffix == ".jsonl":
            rows.extend(_read_jsonl(path))
        elif suffix == ".csv":
            rows.extend(_read_csv(path))
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    except OSError:
        return rows
    for line_number, raw in enumerate(lines[-5000:], start=max(1, len(lines) - 4999)):
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
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


def _profit_progress(rows: list[dict[str, Any]], target_usd: float) -> dict[str, Any]:
    verified: list[dict[str, Any]] = []
    cent: list[dict[str, Any]] = []
    shadow: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
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
    estimated_from_cent = round(cent_total / 100.0, 2)
    remaining = round(max(0.0, float(target_usd) - verified_total), 2)
    return {
        "verifiedUsdProfit": verified_total,
        "estimatedUsdFromCentAccount": estimated_from_cent,
        "centAccountProfitUSC": cent_total,
        "remainingUsd": remaining,
        "profitEvidenceCount": len(verified),
        "centEvidenceCount": len(cent),
        "shadowRCount": len(shadow),
        "verifiedUsdEvidence": verified[-20:],
        "centOnlyEvidence": cent[-20:],
        "shadowOnlyREvidence": shadow[-20:],
        "countingRuleZh": "只有明确 USD 字段或 currency=USD 的已出场/结果事件计入 verifiedUsdProfit；USC 美分账户只做估算，不当作目标已达成。",
    }


def _lane_target_progress(
    runtime_dir: Path,
    rows: list[dict[str, Any]],
    target_usd: float,
    hfm_runtime_dir: Path | None,
) -> dict[str, Any]:
    required_lane_ids = ["forexMt5"]
    if hfm_runtime_dir:
        required_lane_ids.append("btcCryptoCfd")
    buckets: dict[str, list[dict[str, Any]]] = {lane_id: [] for lane_id in required_lane_ids}
    seen: set[str] = set()
    for row in rows:
        lane_id = _row_lane_id(row)
        if lane_id not in buckets:
            continue
        amount, field = _verified_usd_outcome(row)
        if amount is None:
            continue
        key = _dedupe_key(row, f"USD:{lane_id}", amount)
        if key in seen:
            continue
        seen.add(key)
        evidence = _evidence_row(row, amount, "USD", field or "profit")
        evidence["laneId"] = lane_id
        evidence["evidenceType"] = "trade_outcome"
        buckets[lane_id].append(evidence)
    profile_evidence = _hfm_crypto_profile_profit_evidence(hfm_runtime_dir)
    if profile_evidence and "btcCryptoCfd" in buckets:
        buckets["btcCryptoCfd"].append(profile_evidence)
    forex_profile_evidence = _forex_profile_profit_evidence(runtime_dir, rows)
    if forex_profile_evidence and "forexMt5" in buckets:
        buckets["forexMt5"].append(forex_profile_evidence)
    lane_targets: dict[str, Any] = {}
    for lane_id in required_lane_ids:
        evidence = buckets.get(lane_id, [])
        verified_total = round(sum(float(row.get("amount") or 0.0) for row in evidence), 2)
        reached = verified_total > 0.0
        lane_definition = dict(LANE_DEFINITIONS[lane_id])
        lane_definition["reasonZh"] = lane_definition["reasonZh"].format(targetLabel=_target_label(target_usd))
        lane_targets[lane_id] = {
            "laneId": lane_id,
            **lane_definition,
            "targetUsd": round(float(target_usd), 2),
            "combinedTargetUsd": round(float(target_usd), 2),
            "laneMinimumUsd": 0.0,
            "lanePositive": reached,
            "simulationVerifiedUsdProfit": verified_total,
            "remainingUsd": 0.0 if reached else 0.01,
            "remainingToPositiveUsd": 0.0 if reached else 0.01,
            "targetReached": reached,
            "status": "LANE_POSITIVE" if reached else ("TRACKING_NOT_POSITIVE" if evidence else "WAITING_FOR_SIMULATION_EVIDENCE"),
            "statusZh": "该 lane 已证明正收益" if reached else ("正在追踪，该 lane 尚未证明正收益" if evidence else "等待模拟/回测收益证据"),
            "evidenceCount": len(evidence),
            "evidence": evidence[-20:],
            "countingRuleZh": "只统计该车道明确 USD 的已出场、回测或模拟 profile pnl；任一 lane 可单独达标，多 lane 也可净合计达到总目标。",
        }
    return lane_targets


def _combined_target_progress(lane_targets: dict[str, Any], target_usd: float) -> dict[str, Any]:
    lanes = [row for row in lane_targets.values() if isinstance(row, dict)]
    combined_profit = round(sum(float(row.get("simulationVerifiedUsdProfit") or 0.0) for row in lanes), 2)
    positive_lane_ids = [str(row.get("laneId")) for row in lanes if float(row.get("simulationVerifiedUsdProfit") or 0.0) > 0.0]
    missing_positive_lane_ids = [str(row.get("laneId")) for row in lanes if float(row.get("simulationVerifiedUsdProfit") or 0.0) <= 0.0]
    all_required_lanes_positive = bool(lanes) and not missing_positive_lane_ids
    qualifying_lane_ids = [
        str(row.get("laneId"))
        for row in lanes
        if float(row.get("simulationVerifiedUsdProfit") or 0.0) >= float(target_usd)
    ]
    single_lane_target_reached = bool(qualifying_lane_ids)
    combined_profit_reached = combined_profit >= float(target_usd)
    target_reached = single_lane_target_reached or combined_profit_reached
    return {
        "targetUsd": round(float(target_usd), 2),
        "combinedVerifiedUsdProfit": combined_profit,
        "remainingUsd": round(max(0.0, float(target_usd) - combined_profit), 2),
        "aggregationMode": TARGET_AGGREGATION_MODE,
        "requiredLaneCount": len(lanes),
        "positiveLaneCount": len(positive_lane_ids),
        "positiveLaneIds": positive_lane_ids,
        "missingPositiveLaneIds": missing_positive_lane_ids,
        "allRequiredLanesPositive": all_required_lanes_positive,
        "allRequiredLanesMustBePositive": False,
        "qualifyingLaneIds": qualifying_lane_ids,
        "singleLaneTargetReached": single_lane_target_reached,
        "combinedProfitReached": combined_profit_reached,
        "targetReached": target_reached,
        "status": "TARGET_REACHED" if target_reached else "WAITING_FOR_COMBINED_POSITIVE_PROFIT",
        "statusZh": (
            f"任一 lane 或多 lane 净合计已达到 {_target_label(target_usd)}"
            if target_reached
            else f"等待任一 lane 或多 lane 净合计达到 {_target_label(target_usd)}"
        ),
        "countingRuleZh": "外币与 BTC/crypto CFD 收益可以净合计计算总目标；任一 lane 单独达到目标也可进入实盘执行审查。",
    }


def _verified_usd_outcome(row: dict[str, Any]) -> tuple[float | None, str | None]:
    event_type = str(row.get("eventType") or row.get("event") or row.get("type") or "").upper()
    outcome_like = _is_outcome_like(event_type, row)
    usd_amount, usd_key = _explicit_amount(row, USD_EXPLICIT_KEYS)
    currency = str(_first_value(row, ("currency", "accountCurrency", "profitCurrency")) or "").upper()
    if usd_amount is None and currency == "USD" and outcome_like:
        usd_amount, usd_key = _explicit_amount(row, GENERIC_PROFIT_KEYS)
    if usd_amount is None or not outcome_like:
        return None, None
    return usd_amount, usd_key


def _row_lane_id(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or row.get("Symbol") or row.get("brokerSymbol") or row.get("canonicalSymbol") or "")
    source_file = str(row.get("_sourceFile") or "")
    if _looks_like_crypto_symbol(symbol) or "/hfm_crypto/" in source_file.replace("\\", "/"):
        return "btcCryptoCfd"
    return "forexMt5"


def _looks_like_crypto_symbol(symbol: str) -> bool:
    clean = re.sub(r"[^A-Za-z]", "", symbol).upper()
    if not clean:
        return False
    for quote in ("USD", "USDT", "USDC"):
        if clean.endswith(quote):
            base = clean[: -len(quote)]
            if base in CRYPTO_BASES:
                return True
    return clean in CRYPTO_BASES


def _hfm_crypto_profile_profit_evidence(hfm_runtime_dir: Path | None) -> dict[str, Any] | None:
    if not hfm_runtime_dir:
        return None
    candidates = [
        hfm_runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json",
        hfm_runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoMossBacktestProfile.json",
        hfm_runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoFilledSimulationProfile.json",
    ]
    for path in candidates:
        payload = _read_json(path)
        if not payload:
            continue
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else payload
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        if isinstance(profile.get("metrics"), dict):
            metrics = {**profile["metrics"], **metrics}
        amount = _num(_first_value(metrics, ("pnl", "profitUsd", "pnlUsd", "netUsd", "netProfitUsd", "realizedPnlUsd")))
        if amount is None:
            amount = _num(_first_value(profile, ("pnl", "profitUsd", "pnlUsd", "netUsd", "netProfitUsd", "realizedPnlUsd")))
        if amount is None:
            continue
        return {
            "amount": round(float(amount), 4),
            "currency": "USD",
            "field": "simulationProfilePnlUsd",
            "eventType": "SIMULATION_PROFILE",
            "symbol": metrics.get("symbol") or profile.get("symbol") or "BTC/HFM_CRYPTO_CFD",
            "accountAlias": "hfm_crypto_simulation",
            "strategyId": metrics.get("agentId") or profile.get("agentId") or profile.get("id"),
            "ticket": None,
            "sourceFile": str(path),
            "lineNumber": None,
            "laneId": "btcCryptoCfd",
            "evidenceType": "simulation_profile",
            "simulationQualified": bool(payload.get("simulationQualified") or payload.get("qualified")),
        }
    return None


def _forex_profile_profit_evidence(runtime_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    runtime_roots = {
        Path(str(row.get("_sourceFile") or "")).parents[0]
        for row in rows
        if row.get("_sourceFile")
    }
    candidates: list[Path] = []
    for source_dir in runtime_roots:
        for parent in [source_dir, *source_dir.parents]:
            if parent.name in {"runtime", "primary"}:
                candidates.append(parent / "forex" / "QuantGod_ForexMt5SimulationProfileReview.json")
                break
    candidates.append(Path(runtime_dir) / "forex" / "QuantGod_ForexMt5SimulationProfileReview.json")
    for path in _unique_paths(candidates):
        payload = _read_json(path)
        if not payload or not bool(payload.get("simulationQualified") or payload.get("qualified")):
            continue
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else payload
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        if isinstance(profile.get("metrics"), dict):
            metrics = {**profile["metrics"], **metrics}
        amount = _num(_first_value(metrics, ("pnl", "profitUsd", "pnlUsd", "netUsd", "netProfitUsd", "realizedPnlUsd")))
        if amount is None:
            amount = _num(_first_value(profile, ("pnl", "profitUsd", "pnlUsd", "netUsd", "netProfitUsd", "realizedPnlUsd")))
        if amount is None:
            continue
        return {
            "amount": round(float(amount), 4),
            "currency": "USD",
            "field": "forexSimulationProfilePnlUsd",
            "eventType": "SIMULATION_PROFILE",
            "symbol": metrics.get("symbol") or profile.get("symbol") or "USDJPYc",
            "accountAlias": "forex_mt5_simulation",
            "strategyId": metrics.get("agentId") or profile.get("agentId") or profile.get("id"),
            "ticket": None,
            "sourceFile": str(path),
            "lineNumber": None,
            "laneId": "forexMt5",
            "evidenceType": "simulation_profile",
            "simulationQualified": True,
        }
    return None


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


def _evidence_row(row: dict[str, Any], amount: float, currency: str, key: str) -> dict[str, Any]:
    return {
        "amount": round(float(amount), 4),
        "currency": currency,
        "field": key,
        "eventType": row.get("eventType") or row.get("event") or row.get("type"),
        "symbol": row.get("symbol") or row.get("Symbol"),
        "accountAlias": row.get("accountAlias") or row.get("account") or row.get("accountName"),
        "strategyId": row.get("strategyId") or row.get("policyId") or row.get("strategy"),
        "ticket": row.get("ticket") or row.get("dealId") or row.get("positionId") or row.get("orderId"),
        "sourceFile": row.get("_sourceFile"),
        "lineNumber": row.get("_lineNumber"),
    }


def _dedupe_key(row: dict[str, Any], currency: str, amount: float) -> str:
    stable_keys = (
        "feedbackId",
        "eventId",
        "ticket",
        "dealId",
        "positionId",
        "orderId",
        "intentId",
        "policyId",
    )
    parts = [str(row.get(key) or "") for key in stable_keys if row.get(key) not in (None, "")]
    event_type = str(row.get("eventType") or row.get("event") or row.get("type") or "")
    if parts:
        return "|".join([currency, event_type, *parts])
    clean = {
        key: value
        for key, value in row.items()
        if key not in {"_sourceFile", "_lineNumber"}
    }
    return f"{currency}|{amount}|{json.dumps(clean, ensure_ascii=False, sort_keys=True, default=str)}"


def _collect_blockers(runtime_dir: Path, hfm_runtime_dir: Path | None) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    primary_readiness = _read_json(runtime_dir / "agent" / "QuantGod_LiveAutomationReadiness.json")
    hfm_readiness = _read_json(hfm_runtime_dir / "agent" / "QuantGod_LiveAutomationReadiness.json") if hfm_runtime_dir else {}
    if hfm_readiness:
        blockers.extend(_blockers_from_readiness(
            primary_readiness,
            "primary",
            include_lanes={"usdjpyMt5"},
            exclude_codes={"NO_LANE_READY_FOR_REVIEW"},
        ))
        blockers.extend(_blockers_from_readiness(hfm_readiness, "hfm", include_lanes={"hfmCryptoCfd"}))
    else:
        blockers.extend(_blockers_from_readiness(primary_readiness, "primary"))
    blockers.extend(_spread_blockers(runtime_dir))
    if hfm_runtime_dir:
        blockers.extend(_hfm_blockers(hfm_runtime_dir))
    return _dedupe_blockers(blockers)


def _blockers_from_readiness(
    payload: dict[str, Any],
    scope: str,
    *,
    include_lanes: set[str] | None = None,
    exclude_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    excluded = exclude_codes or set()
    if not payload:
        return rows
    for blocker in payload.get("globalBlockers", []):
        normalized = _normalize_blocker(blocker, scope, "live_readiness")
        if normalized.get("code") not in excluded:
            rows.append(normalized)
    lanes = payload.get("lanes")
    if isinstance(lanes, dict):
        for lane_name, lane in lanes.items():
            if not isinstance(lane, dict):
                continue
            if include_lanes is not None and lane_name not in include_lanes:
                continue
            for blocker in lane.get("reviewBlockers", []):
                normalized = _normalize_blocker(blocker, scope, f"live_readiness.{lane_name}")
                if normalized.get("code") not in excluded:
                    rows.append(normalized)
    return rows


def _spread_blockers(runtime_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sources: list[tuple[Path, dict[str, Any]]] = []
    for path in (runtime_dir / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json",):
        payload = _read_json(path)
        if payload:
            sources.append((path, payload))
    diagnostics, diagnostics_path = _latest_usdjpy_rsi_entry_diagnostics(runtime_dir)
    if diagnostics and diagnostics_path:
        sources.append((diagnostics_path, diagnostics))
    for path, payload in sources:
        if _spread_gate_active(payload):
            spread_pips = _first_recursive(payload, ("spreadPips", "currentSpreadPips"))
            rows.append({
                "code": "USDJPY_SPREAD_GATE_ACTIVE",
                "reasonZh": "USDJPY 当前点差或 EA 入场守门仍在阻断。",
                "value": spread_pips,
                "source": str(path),
                "scope": "primary",
            })
    return rows


def _latest_usdjpy_rsi_entry_diagnostics(runtime_dir: Path) -> tuple[dict[str, Any] | None, Path | None]:
    found: list[tuple[float, Path, dict[str, Any]]] = []
    for directory in _candidate_roots(runtime_dir):
        path = directory / "QuantGod_USDJPYRsiEntryDiagnostics.json"
        payload = _read_json(path)
        if payload:
            try:
                found.append((path.stat().st_mtime, path, payload))
            except OSError:
                pass
        dashboard_path = directory / "QuantGod_Dashboard.json"
        dashboard = _read_json(dashboard_path)
        embedded = dashboard.get("usdJpyRsiEntryDiagnostics") if dashboard and isinstance(dashboard.get("usdJpyRsiEntryDiagnostics"), dict) else None
        if embedded:
            try:
                found.append((dashboard_path.stat().st_mtime, dashboard_path, embedded))
            except OSError:
                pass
    if not found:
        return None, None
    _, path, payload = sorted(found, key=lambda item: item[0], reverse=True)[0]
    return payload, path


def _spread_gate_active(payload: dict[str, Any]) -> bool:
    text = json.dumps(payload, ensure_ascii=False).upper()
    if "SPREAD_BLOCK" in text:
        return True
    blocked_states = {
        "BLOCKED",
        "HARD_BLOCK",
        "SPREAD_BLOCK",
        "SPREAD_BLOCKED",
        "HARD_WIDE",
    }
    for key in ("status", "state", "tier", "evalCode"):
        for value in _recursive_values(payload, key):
            if str(value or "").strip().upper() in blocked_states:
                return True
    guards = _first_recursive(payload, ("guards",))
    if isinstance(guards, dict) and guards.get("spreadAllowed") is False:
        return True
    return False


def _recursive_values(value: Any, key: str) -> list[Any]:
    rows: list[Any] = []
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            if str(item_key) == key:
                rows.append(item_value)
            rows.extend(_recursive_values(item_value, key))
    elif isinstance(value, list):
        for item in value:
            rows.extend(_recursive_values(item, key))
    return rows


def _hfm_blockers(hfm_runtime_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    state_path = hfm_runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json"
    state = _read_json(state_path)
    if state:
        for blocker in state.get("blockers", []) + state.get("reviewBlockers", []):
            rows.append(_normalize_blocker(blocker, "hfm", "hfm_crypto_state"))
        runtime_probe_blocker = _hfm_runtime_probe_blocker_from_state(state, state_path)
        if runtime_probe_blocker:
            rows.append(runtime_probe_blocker)
        summary = state.get("summary") if isinstance(state.get("summary"), dict) else {}
        if summary.get("simulationProfileQualified") is False:
            rows.append({
                "code": "HFM_SIMULATION_PROFILE_NOT_QUALIFIED",
                "reasonZh": "HFM crypto CFD 缺少合格模拟/回测 profile，不能进入执行候选。",
                "value": summary.get("simulationProfileStatus"),
                "scope": "hfm",
                "source": str(hfm_runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json"),
            })
    review = _read_json(hfm_runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json")
    if review and not bool(review.get("qualified") or review.get("simulationQualified")):
        rows.append({
            "code": review.get("status") or "HFM_SIMULATION_PROFILE_MISSING",
            "reasonZh": review.get("reasonZh") or "缺少 HFM crypto CFD 模拟/回测 profile。",
            "scope": "hfm",
            "source": str(hfm_runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json"),
        })
    return rows


def _hfm_runtime_probe_blocker(hfm_runtime_dir: Path) -> dict[str, Any]:
    state_path = hfm_runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json"
    return _hfm_runtime_probe_blocker_from_state(_read_json(state_path), state_path)


def _hfm_runtime_probe_blocker_from_state(state: dict[str, Any], state_path: Path) -> dict[str, Any]:
    bundle = state.get("standaloneExporterBundle") if isinstance(state.get("standaloneExporterBundle"), dict) else {}
    if not bundle:
        return {}
    if bool(bundle.get("runtimeProbeTickDetected")):
        return {}
    missing_after_specs = bool(bundle.get("runtimeProbeMissingAfterSpecs"))
    status = str(bundle.get("status") or "")
    if not missing_after_specs and status not in {
        "WAITING_STANDALONE_MT5_RUNTIME_PROBE_INSTALL",
        "READY_TO_RUN_STANDALONE_MT5_RUNTIME_PROBE",
    }:
        return {}
    symbol = str(bundle.get("startupSymbol") or "#BTCUSD")
    target = bundle.get("target") if isinstance(bundle.get("target"), dict) else {}
    output = bundle.get("output") if isinstance(bundle.get("output"), dict) else {}
    installed_matches_bundle = bundle.get("targetExpertInstalledMatchesBundle")
    if installed_matches_bundle is None:
        installed_matches_bundle = target.get("targetExpertInstalledMatchesBundle")
    if installed_matches_bundle is False:
        code = "HFM_CRYPTO_RUNTIME_PROBE_EXPORTER_NOT_CURRENT"
        reason = (
            f"{symbol} runtime probe 缺失：当前 MT5 Experts 里的 exporter EA 不是最新版，"
            "需要安装/编译带 runtime probe 的只读 HFM crypto exporter EA。"
        )
    else:
        code = "HFM_CRYPTO_RUNTIME_PROBE_MISSING_AFTER_SPECS"
        reason = (
            f"{symbol} runtime probe 缺失：HFM specs 已存在，但尚未运行带 runtime probe 的只读 "
            "HFM crypto exporter EA。"
        )
    return {
        "code": code,
        "reasonZh": reason,
        "value": symbol,
        "scope": "hfm",
        "source": "hfm_crypto_standalone_exporter_bundle",
        "sourceFile": str(state_path),
        "status": status or None,
        "nextRequiredActionZh": bundle.get("nextRequiredActionZh"),
        "targetExpertPath": bundle.get("targetExpertPath") or target.get("targetExpertPath"),
        "expectedRuntimeProbePath": bundle.get("expectedRuntimeProbePath") or output.get("expectedRuntimeProbePath"),
    }


def _normalize_blocker(blocker: Any, scope: str, source: str) -> dict[str, Any]:
    if isinstance(blocker, dict):
        return {
            "code": blocker.get("code") or "BLOCKER",
            "reasonZh": blocker.get("reasonZh") or blocker.get("reason") or blocker.get("label") or "",
            "value": blocker.get("value"),
            "limit": blocker.get("limit"),
            "scope": scope,
            "source": source,
        }
    return {
        "code": "BLOCKER",
        "reasonZh": str(blocker),
        "scope": scope,
        "source": source,
    }


def _dedupe_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blocker in blockers:
        key = "|".join([
            str(blocker.get("scope") or ""),
            str(blocker.get("code") or ""),
            str(blocker.get("source") or ""),
            str(blocker.get("reasonZh") or ""),
        ])
        if key not in seen:
            seen.add(key)
            rows.append(blocker)
    return rows[:40]


def _research_progress(runtime_dir: Path, hfm_runtime_dir: Path | None) -> dict[str, Any]:
    ga_state = _read_json(runtime_dir / "ga_factory" / "QuantGod_GAFactoryState.json")
    ga_current_generation = _num(ga_state.get("currentGeneration"))
    ga_best = _ga_best_candidate(ga_state, generation=ga_current_generation)
    ga_best_overall = _ga_best_candidate(ga_state)
    primary_readiness = _read_json(runtime_dir / "agent" / "QuantGod_LiveAutomationReadiness.json")
    hfm_readiness = _read_json(hfm_runtime_dir / "agent" / "QuantGod_LiveAutomationReadiness.json") if hfm_runtime_dir else {}
    readiness = hfm_readiness or primary_readiness
    hfm_state = _read_json((hfm_runtime_dir or runtime_dir) / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json")
    hfm_sim = _read_json((hfm_runtime_dir or runtime_dir) / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json")
    hfm_simulation_qualified = None
    if hfm_sim:
        hfm_simulation_qualified = hfm_sim.get("qualified") if "qualified" in hfm_sim else hfm_sim.get("simulationQualified")
    return {
        "gaFactory": {
            "status": ga_state.get("status"),
            "currentGeneration": ga_state.get("currentGeneration"),
            "candidateCount": ga_state.get("candidateCount"),
            "eliteCount": ga_state.get("eliteCount"),
            "bestSeedId": ga_best.get("seedId"),
            "bestStrategyId": ga_best.get("strategyId"),
            "bestFitness": ga_best.get("fitness"),
            "bestGeneration": ga_best.get("generation"),
            "bestStatus": ga_best.get("status"),
            "bestBlockerCode": ga_best.get("blockerCode"),
            "bestPromotionStage": ga_best.get("promotionStage"),
            "bestOverallSeedId": ga_best_overall.get("seedId"),
            "bestOverallStrategyId": ga_best_overall.get("strategyId"),
            "bestOverallFitness": ga_best_overall.get("fitness"),
            "bestOverallGeneration": ga_best_overall.get("generation"),
            "bestOverallBlockerCode": ga_best_overall.get("blockerCode"),
            "nextGeneration": ga_state.get("nextGeneration"),
            "allowedPromotionStages": ga_state.get("safety", {}).get("allowedPromotionStages") if isinstance(ga_state.get("safety"), dict) else None,
        },
        "liveReadiness": {
            "status": readiness.get("status"),
            "statusZh": readiness.get("statusZh"),
            "canPromoteToLiveNow": readiness.get("canPromoteToLiveNow"),
            "autoPromotionToLiveAllowed": readiness.get("autoPromotionToLiveAllowed"),
            "orderSendAllowed": readiness.get("safety", {}).get("orderSendAllowed") if isinstance(readiness.get("safety"), dict) else None,
        },
        "hfmCryptoCfd": {
            "status": hfm_state.get("status"),
            "statusZh": hfm_state.get("statusZh"),
            "detectedSymbolCount": (
                hfm_state.get("detectedSymbolCount")
                or _first_recursive(hfm_state, ("detectedSymbolCount", "targetSymbolCount"))
                or len(_first_recursive(hfm_state, ("canonicalSymbols",)) or [])
                or len(hfm_state.get("targetSymbols") or [])
            ),
            "simulationProfileStatus": hfm_sim.get("status") or _first_recursive(hfm_state, ("simulationProfileStatus",)),
            "simulationProfileQualified": hfm_simulation_qualified if hfm_sim else _first_recursive(hfm_state, ("simulationProfileQualified",)),
            "executionSpecReady": _first_recursive(hfm_state, ("executionSpecReady",)),
        },
    }


def _ga_best_candidate(ga_state: dict[str, Any], *, generation: float | None = None) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for key in ("eliteArchive", "lineageTree", "graveyard"):
        section = ga_state.get(key)
        if not isinstance(section, dict):
            continue
        for list_key in ("elites", "nodes", "strategies"):
            rows = section.get(list_key)
            if isinstance(rows, list):
                candidates.extend(row for row in rows if isinstance(row, dict))
    direct = ga_state.get("bestCandidate")
    if isinstance(direct, dict):
        candidates.append(direct)
    if generation is not None:
        current_generation_candidates = [
            candidate for candidate in candidates
            if _num(candidate.get("generation")) == generation
        ]
        if current_generation_candidates:
            candidates = current_generation_candidates
    best: dict[str, Any] = {}
    best_fitness: float | None = None
    for candidate in candidates:
        fitness = _num(candidate.get("fitness") if "fitness" in candidate else candidate.get("bestFitness"))
        if fitness is None:
            continue
        if best_fitness is None or fitness > best_fitness:
            best_fitness = fitness
            best = candidate
    if not best:
        seed_id = ga_state.get("bestSeedId")
        fitness = _num(ga_state.get("bestFitness"))
        if seed_id not in (None, "") or fitness is not None:
            best = {"seedId": seed_id, "fitness": fitness}
    if not best:
        return {}
    return {
        "seedId": best.get("seedId") or best.get("bestSeedId"),
        "strategyId": best.get("strategyId") or best.get("strategy"),
        "generation": _num(best.get("generation")),
        "fitness": round(float(best_fitness), 4) if best_fitness is not None else _num(best.get("fitness")),
        "status": best.get("status"),
        "blockerCode": best.get("blockerCode"),
        "promotionStage": best.get("promotionStage"),
    }


def _first_hfm_intent(plan: dict[str, Any]) -> dict[str, Any]:
    for intent in plan.get("dryRunIntents", []):
        if isinstance(intent, dict) and str(intent.get("lane") or "") == "HFM_CRYPTO_CFD":
            return intent
    return {}


def _first_hfm_runtime_check(preflight: dict[str, Any]) -> dict[str, Any]:
    for check in preflight.get("laneRuntimeChecks", []):
        if isinstance(check, dict) and str(check.get("lane") or "") == "HFM_CRYPTO_CFD":
            return check
    return {}


def _live_blockers(*payloads: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        for blocker in payload.get("blockers", []):
            normalized = _normalize_blocker(blocker, "hfm", "live_execution_review")
            rows.append(normalized)
    return _dedupe_blockers(rows)[:12]


def _primary_actionable_live_blocker(blockers: list[dict[str, Any]]) -> dict[str, Any]:
    if not blockers:
        return {}
    symbol_codes = {
        "MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD",
        "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING",
        "MT5_SYMBOL_NOT_IN_RUNTIME_SNAPSHOT",
        "MT5_SYMBOL_SNAPSHOT_EMPTY",
    }
    for blocker in blockers:
        if str(blocker.get("code") or "") in symbol_codes:
            return blocker
    file_evidence_codes = (
        "DEPLOYED_PRESET_READ_ONLY_TRUE",
        "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF",
        "DEPLOYED_PRESET_RSI_LIVE_OFF",
        "DEPLOYED_PRESET_EA_REQUEST_READER_OFF",
        "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF",
    )
    for code in file_evidence_codes:
        for blocker in blockers:
            if str(blocker.get("code") or "") == code:
                return blocker
    generic_codes = {
        "RUNTIME_PREFLIGHT_NOT_PASSED",
        "WAITING_RUNTIME_PREFLIGHT_INPUTS",
        "EXECUTION_MODE_GATES_NOT_ACTIVE",
        "EXECUTION_LANE_NOT_ENABLED",
        "SEPARATE_REVIEW_REQUIRED",
    }
    for blocker in blockers:
        if str(blocker.get("code") or "") not in generic_codes:
            return blocker
    return blockers[0]


def _live_execution_review(hfm_runtime_dir: Path | None) -> dict[str, Any]:
    if not hfm_runtime_dir:
        return {}
    agent = hfm_runtime_dir / "agent"
    review_packet = _read_json(agent / "QuantGod_LiveExecutionReviewPacket.json")
    approval = _read_json(agent / "QuantGod_LiveOperatorApprovalEvidenceReview.json")
    dry_run = _read_json(agent / "QuantGod_DryRunLiveExecutionPlan.json")
    execution_spec = _read_json(agent / "QuantGod_LiveExecutionLaneSpec.json")
    replay = _read_json(agent / "QuantGod_LiveDryRunIntentReplay.json")
    preflight = _read_json(agent / "QuantGod_LiveRuntimePreflightProbe.json")
    order_contract = _read_json(agent / "QuantGod_MT5OrderRequestContract.json")
    activation = _read_json(agent / "QuantGod_LivePilotActivationReview.json")
    cutover = _read_json(agent / "QuantGod_LiveExecutionCutoverReview.json")
    rollback = _read_json(agent / "QuantGod_LiveExecutionRollbackReview.json")
    implementation_spec = _read_json(agent / "QuantGod_LiveExecutionImplementationSpec.json")
    orchestrator = _read_json(agent / "QuantGod_SimToLiveOrchestrator.json")
    intent = _first_hfm_intent(dry_run)
    runtime_check = _first_hfm_runtime_check(preflight)
    dashboard = preflight.get("dashboardSnapshot") if isinstance(preflight.get("dashboardSnapshot"), dict) else {}
    blockers = _live_blockers(cutover, rollback, activation, order_contract, preflight, execution_spec, replay, approval)
    runtime_probe_blocker = _hfm_runtime_probe_blocker(hfm_runtime_dir)
    if runtime_probe_blocker:
        blockers = _dedupe_blockers([runtime_probe_blocker, *blockers])[:12]
    primary_blocker = runtime_probe_blocker or _primary_actionable_live_blocker(blockers)
    activation_package = activation.get("presetActivationPackage") if isinstance(activation.get("presetActivationPackage"), dict) else {}
    execution_mode_file_evidence = (
        cutover.get("executionModeFileEvidence")
        if isinstance(cutover.get("executionModeFileEvidence"), dict)
        else activation_package.get("liveRuntimeFileEvidence")
        if isinstance(activation_package.get("liveRuntimeFileEvidence"), dict)
        else {}
    )
    file_evidence_blockers = (
        execution_mode_file_evidence.get("blockingEvidence")
        if isinstance(execution_mode_file_evidence.get("blockingEvidence"), list)
        else []
    )
    order_send_allowed = bool(
        order_contract.get("orderSendAllowed")
        or preflight.get("orderSendAllowed")
        or execution_spec.get("orderSendAllowed")
    )
    cutover_handoff = cutover.get("implementationHandoff") if isinstance(cutover.get("implementationHandoff"), dict) else {}
    micro_blueprint = (
        implementation_spec.get("microLiveExecutionBlueprint")
        if isinstance(implementation_spec.get("microLiveExecutionBlueprint"), dict)
        else {}
    )
    implementation_readiness_summary = (
        implementation_spec.get("implementationReadinessSummary")
        if isinstance(implementation_spec.get("implementationReadinessSummary"), dict)
        else {}
    )
    rollback_matrix = rollback.get("rollbackMatrix") if isinstance(rollback.get("rollbackMatrix"), list) else []
    live_execution_status = (
        cutover.get("status")
        or order_contract.get("status")
        or preflight.get("status")
        or execution_spec.get("status")
        or review_packet.get("status")
    )
    live_execution_status_zh = (
        cutover.get("statusZh")
        or order_contract.get("statusZh")
        or preflight.get("statusZh")
        or execution_spec.get("statusZh")
        or review_packet.get("statusZh")
    )
    cutover_ready = bool(cutover.get("readyForSeparateLiveExecutionCutoverImplementationReview"))
    rollback_ready = bool(rollback.get("readyForLiveExecutionRollbackReview"))
    orchestrator_stages = orchestrator.get("stages") if isinstance(orchestrator.get("stages"), list) else []
    approval_wait_resolved_stages = [
        str(row.get("stageId") or "")
        for row in orchestrator_stages
        if isinstance(row, dict) and row.get("approvalWaitResolved") and row.get("stageId")
    ]
    release_gate_summary = (
        orchestrator.get("executionReleaseGateSummary")
        if isinstance(orchestrator.get("executionReleaseGateSummary"), dict)
        else {}
    )
    release_gate_checklist = (
        orchestrator.get("executionReleaseGateChecklist")
        if isinstance(orchestrator.get("executionReleaseGateChecklist"), list)
        else []
    )
    release_readiness_packet = (
        orchestrator.get("executionReleaseReadinessPacket")
        if isinstance(orchestrator.get("executionReleaseReadinessPacket"), dict)
        else {}
    )
    return {
        "status": live_execution_status,
        "statusZh": live_execution_status_zh,
        "summaryZh": (
            primary_blocker.get("reasonZh")
            if primary_blocker
            else "收益目标、审批、broker/receipt/EA reader、rollback 与 cutover 数据面均已就绪；真实订单写入仍关闭，等待单独 execution implementation。"
            if cutover_ready and rollback_ready
            else "BTCUSD dry-run、审批证据和执行 lane spec 已可审查；真实订单写入仍关闭。"
        ),
        "primaryActionableBlocker": primary_blocker,
        "reviewPacketHash": (
            order_contract.get("reviewPacketHash")
            or preflight.get("reviewPacketHash")
            or execution_spec.get("reviewPacketHash")
            or dry_run.get("reviewPacketHash")
        ),
        "orderSendAllowed": order_send_allowed,
        "mt5OrderSendAllowed": bool(order_contract.get("mt5OrderSendAllowed") or preflight.get("mt5OrderSendAllowed")),
        "writesMt5OrderRequest": bool(order_contract.get("writesMt5OrderRequest") or execution_spec.get("writesMt5OrderRequest")),
        "approvalEvidenceAccepted": bool(approval.get("operatorApprovalProvided") or execution_spec.get("approvalEvidenceAccepted")),
        "approvalWaitResolved": bool(approval_wait_resolved_stages),
        "approvalWaitResolvedStages": approval_wait_resolved_stages,
        "readyForImplementationReview": bool(execution_spec.get("readyForImplementationReview")),
        "replayPassed": bool(replay.get("replayPassed")),
        "runtimeProbePassed": bool(preflight.get("runtimeProbePassed")),
        "runtimePreflightDataPlaneReadyForReview": bool(preflight.get("dataPlaneReadyForLivePilotReview")),
        "runtimePreflightExecutionModeReady": bool(preflight.get("executionModeReady")),
        "runtimePreflightExecutionModeOnlyBlocked": bool(preflight.get("executionModeOnlyBlocked")),
        "runtimePreflightNonExecutionBlockers": preflight.get("nonExecutionBlockers") if isinstance(preflight.get("nonExecutionBlockers"), list) else [],
        "runtimePreflightExecutionModeBlockers": preflight.get("executionModeBlockers") if isinstance(preflight.get("executionModeBlockers"), list) else [],
        "executionModeFileEvidence": execution_mode_file_evidence,
        "fileEvidenceBlockers": file_evidence_blockers,
        "orderContractDataPlaneReadyForReview": bool(order_contract.get("runtimePreflightDataPlaneReadyForReview")),
        "orderContractExecutionModeOnlyBlocked": bool(order_contract.get("runtimePreflightExecutionModeOnlyBlocked")),
        "readyForAdapterCodeReview": bool(order_contract.get("readyForAdapterCodeReview")),
        "cutoverStatus": cutover.get("status", ""),
        "readyForLiveExecutionCutoverReview": cutover_ready,
        "dataPlaneCutoverReady": bool(cutover.get("dataPlaneCutoverReady")),
        "cutoverExecutionModeOnlyBlocked": bool(cutover.get("executionModeOnlyBlocked")),
        "rollbackStatus": rollback.get("status", ""),
        "readyForLiveExecutionRollbackReview": rollback_ready,
        "dataPlaneRollbackReady": bool(rollback.get("dataPlaneRollbackReady")),
        "rollbackExecutionModeOnlyBlocked": bool(rollback.get("executionModeOnlyBlocked")),
        "separateExecutionImplementationReviewReady": bool(cutover_ready and rollback_ready),
        "orchestratorStatus": orchestrator.get("status", ""),
        "orchestratorDataPlaneReady": bool(orchestrator.get("dataPlaneOrchestratorReady")),
        "allExecutionReleaseTokensProvided": bool(
            orchestrator.get("allExecutionReleaseTokensProvided")
            or release_gate_summary.get("allReleased")
        ),
        "executionReleaseGateSummary": release_gate_summary,
        "executionReleaseGateChecklist": release_gate_checklist,
        "executionReleaseReadinessPacket": release_readiness_packet,
        "implementationSpecStatus": implementation_spec.get("status", ""),
        "readyForLiveExecutionImplementationSpecReview": bool(
            implementation_spec.get("readyForLiveExecutionImplementationSpecReview")
        ),
        "disabledFirstImplementationWorkReady": bool(implementation_spec.get("disabledFirstImplementationWorkReady")),
        "nextCodeWorkAllowedInReviewOnly": bool(implementation_spec.get("nextCodeWorkAllowedInReviewOnly")),
        "liveExecutionStillForbidden": bool(implementation_spec.get("liveExecutionStillForbidden")),
        "implementationReadinessSummary": implementation_readiness_summary,
        "microLiveExecutionBlueprint": {
            "mode": micro_blueprint.get("mode", ""),
            "status": micro_blueprint.get("status", ""),
            "statusZh": micro_blueprint.get("statusZh", ""),
            "selectedLane": micro_blueprint.get("selectedLane", ""),
            "requestId": micro_blueprint.get("requestId", ""),
            "brokerSymbol": micro_blueprint.get("brokerSymbol", ""),
            "canonicalSymbol": micro_blueprint.get("canonicalSymbol", ""),
            "accountNumber": micro_blueprint.get("accountNumber"),
            "brokerServer": micro_blueprint.get("brokerServer", ""),
            "initialLiveVolumeLotsCandidate": micro_blueprint.get("initialLiveVolumeLotsCandidate"),
            "initialLiveVolumeRequiresSeparateRiskReview": bool(
                micro_blueprint.get("initialLiveVolumeRequiresSeparateRiskReview")
            ),
            "packageCount": micro_blueprint.get("packageCount", 0),
            "allRequiredStepsMapped": bool(micro_blueprint.get("allRequiredStepsMapped")),
            "rejectionReceiptPlanComplete": bool(micro_blueprint.get("rejectionReceiptPlanComplete")),
            "disabledFirstImplementationWorkReady": bool(
                micro_blueprint.get("disabledFirstImplementationWorkReady")
            ),
            "nextCodeWorkAllowedInReviewOnly": bool(micro_blueprint.get("nextCodeWorkAllowedInReviewOnly")),
            "liveExecutionStillForbidden": bool(micro_blueprint.get("liveExecutionStillForbidden")),
            "duplicateRequestIds": micro_blueprint.get("duplicateRequestIds", [])
            if isinstance(micro_blueprint.get("duplicateRequestIds"), list)
            else [],
            "hardBlocksBeforeAnyLiveOrder": micro_blueprint.get("hardBlocksBeforeAnyLiveOrder", [])
            if isinstance(micro_blueprint.get("hardBlocksBeforeAnyLiveOrder"), list)
            else [],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "requestFilesWritten": False,
            "receiptFilesWritten": False,
            "brokerCallsMade": False,
        } if micro_blueprint else {},
        "cutoverHandoff": {
            "approvedLanes": cutover_handoff.get("approvedLanes", []),
            "plannedWriteCount": cutover_handoff.get("plannedWriteCount", 0),
            "brokerSendPlanCount": cutover_handoff.get("brokerSendPlanCount", 0),
            "rollbackRuleCount": cutover_handoff.get("rollbackRuleCount", len(rollback_matrix)),
            "reviewOnlyReceiptCount": cutover_handoff.get("reviewOnlyReceiptCount", 0),
            "implementationMustStaySeparate": bool(cutover_handoff.get("implementationMustStaySeparate")),
            "requiredFuturePrs": cutover_handoff.get("requiredFuturePrs", []),
        },
        "rollbackSummary": {
            "rollbackRuleCount": len(rollback_matrix),
            "allRollbackRulesPassed": bool(rollback_matrix and all(row.get("passed") for row in rollback_matrix if isinstance(row, dict))),
            "manualRearmRequirements": rollback.get("manualRearmRequirements", []) if isinstance(rollback.get("manualRearmRequirements"), list) else [],
        },
        "dryRunIntent": {
            "intentId": intent.get("intentId"),
            "lane": intent.get("lane"),
            "canonicalSymbol": intent.get("canonicalSymbol"),
            "brokerSymbol": intent.get("brokerSymbol"),
            "volumeLots": intent.get("volumeLots"),
            "orderType": intent.get("orderType"),
            "dryRunOnly": intent.get("dryRunOnly"),
            "orderSendAllowed": intent.get("orderSendAllowed"),
        } if intent else {},
        "runtimeCheck": {
            "canonicalSymbol": runtime_check.get("canonicalSymbol"),
            "brokerSymbol": runtime_check.get("brokerSymbol"),
            "symbolPresentInSnapshot": runtime_check.get("symbolPresentInSnapshot"),
            "symbolPresentInSidecarSpecs": runtime_check.get("symbolPresentInSidecarSpecs"),
            "symbolPresentInRuntimeProbe": runtime_check.get("symbolPresentInRuntimeProbe"),
            "symbolMappingOk": runtime_check.get("symbolMappingOk"),
            "spreadFieldPresent": runtime_check.get("spreadFieldPresent"),
            "spreadValue": runtime_check.get("spreadValue"),
            "sidecarLiveTickPresent": runtime_check.get("sidecarLiveTickPresent"),
            "sidecarSpreadValue": runtime_check.get("sidecarSpreadValue"),
            "runtimeProbeSource": runtime_check.get("runtimeProbeSource"),
            "runtimeProbeFresh": runtime_check.get("runtimeProbeFresh"),
            "runtimeProbeAgeSeconds": runtime_check.get("runtimeProbeAgeSeconds"),
            "riskLimitsPresent": runtime_check.get("riskLimitsPresent"),
            "passed": runtime_check.get("passed"),
        } if runtime_check else {},
        "dashboardSnapshot": {
            "found": dashboard.get("found"),
            "fresh": dashboard.get("fresh"),
            "account": dashboard.get("account"),
            "tradeStatus": dashboard.get("tradeStatus"),
            "livePilotMode": dashboard.get("livePilotMode"),
            "readOnlyMode": dashboard.get("readOnlyMode"),
            "executionEnabled": dashboard.get("executionEnabled"),
            "tradeAllowed": dashboard.get("tradeAllowed"),
            "permissionLayers": dashboard.get("permissionLayers", {}),
            "executionGateDiagnostics": dashboard.get("executionGateDiagnostics", {}),
            "symbolNames": dashboard.get("symbolNames"),
        } if dashboard else {},
        "blockers": blockers,
        "nextRequiredActionZh": (
            "cutover/rollback 均 READY；下一步只能进入单独 live execution implementation，实现 request 写入与 broker 调用前仍需独立审查。"
            if cutover_ready and rollback_ready
            else cutover.get("nextRequiredActionZh")
            if cutover.get("nextRequiredActionZh")
            else rollback.get("nextRequiredActionZh")
            if rollback.get("nextRequiredActionZh")
            else
            order_contract.get("nextRequiredActionZh")
            or preflight.get("nextRequiredActionZh")
            or "先让 runtime preflight 通过，再进入 MT5 请求文件与回执合同审查。"
        ),
        "sourceFiles": {
            "reviewPacket": str(agent / "QuantGod_LiveExecutionReviewPacket.json"),
            "dryRunPlan": str(agent / "QuantGod_DryRunLiveExecutionPlan.json"),
            "executionLaneSpec": str(agent / "QuantGod_LiveExecutionLaneSpec.json"),
            "dryRunReplay": str(agent / "QuantGod_LiveDryRunIntentReplay.json"),
            "runtimePreflight": str(agent / "QuantGod_LiveRuntimePreflightProbe.json"),
            "orderRequestContract": str(agent / "QuantGod_MT5OrderRequestContract.json"),
            "livePilotActivationReview": str(agent / "QuantGod_LivePilotActivationReview.json"),
            "liveExecutionCutoverReview": str(agent / "QuantGod_LiveExecutionCutoverReview.json"),
            "liveExecutionRollbackReview": str(agent / "QuantGod_LiveExecutionRollbackReview.json"),
            "liveExecutionImplementationSpec": str(agent / "QuantGod_LiveExecutionImplementationSpec.json"),
        },
    }


def _lane_decision_summary(lane_targets: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "laneId": lane_id,
            "status": row.get("status"),
            "targetReached": bool(row.get("targetReached")),
            "lanePositive": bool(row.get("lanePositive")),
            "simulationVerifiedUsdProfit": row.get("simulationVerifiedUsdProfit"),
            "targetUsd": row.get("targetUsd"),
            "combinedTargetUsd": row.get("combinedTargetUsd"),
            "evidenceCount": row.get("evidenceCount"),
        }
        for lane_id, row in lane_targets.items()
        if isinstance(row, dict)
    ]


def _activation_gate_checklist(live_review: dict[str, Any]) -> list[dict[str, Any]]:
    dashboard = live_review.get("dashboardSnapshot") if isinstance(live_review.get("dashboardSnapshot"), dict) else {}
    definitions = [
        (
            "livePilotMode",
            True,
            "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
            "MT5 dashboard 必须证明 livePilotMode=true。",
        ),
        (
            "readOnlyMode",
            False,
            "MT5_READ_ONLY_MODE_STILL_ACTIVE",
            "MT5 dashboard 必须证明 readOnlyMode=false。",
        ),
        (
            "executionEnabled",
            True,
            "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
            "MT5 dashboard 必须证明 executionEnabled=true。",
        ),
        (
            "tradeAllowed",
            True,
            "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
            "MT5 dashboard 必须证明账户、终端、EA 和 symbol tradeAllowed=true。",
        ),
    ]
    rows: list[dict[str, Any]] = []
    blockers = {
        str(row.get("code") or ""): row
        for row in live_review.get("runtimePreflightExecutionModeBlockers", [])
        if isinstance(row, dict)
    }
    for field, expected, blocker_code, reason_zh in definitions:
        current = dashboard.get(field)
        diagnostics = (
            dashboard.get("executionGateDiagnostics", {}).get(field, {})
            if isinstance(dashboard.get("executionGateDiagnostics"), dict)
            else {}
        )
        passed = current is expected
        blocker = blockers.get(blocker_code, {})
        rows.append({
            "field": field,
            "expected": expected,
            "current": current,
            "passed": passed,
            "blockerCode": "" if passed else blocker_code,
            "reasonZh": "" if passed else str(blocker.get("reasonZh") or reason_zh),
            "layer": diagnostics.get("layer", ""),
            "detailZh": diagnostics.get("detailZh", ""),
            "rawValue": diagnostics.get("rawValue"),
            "permissionLayers": diagnostics.get("permissionLayers", {}),
            "source": "liveExecutionReview.dashboardSnapshot",
        })
    return rows


def _activation_gate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in rows if not row.get("passed")]
    return {
        "total": len(rows),
        "passed": len(rows) - len(failed),
        "blocked": len(failed),
        "allPassed": bool(rows and not failed),
        "failedGateFields": [row.get("field") for row in failed if row.get("field")],
        "blockerCodes": [row.get("blockerCode") for row in failed if row.get("blockerCode")],
        "source": "liveExecutionReview.dashboardSnapshot",
    }


def _authorization_vs_execution_summary(
    *,
    target_reached: bool,
    live_review: dict[str, Any],
    execution_mode_only_blocked: bool,
    all_activation_gates_passed: bool,
    activation_gate_summary: dict[str, Any],
    file_evidence_blockers: list[Any],
    approval_wait_resolved: bool,
    release_gate_summary: dict[str, Any],
) -> dict[str, Any]:
    approval_accepted = bool(live_review.get("approvalEvidenceAccepted"))
    blocker_codes = [
        str(row.get("code") or "")
        for row in file_evidence_blockers
        if isinstance(row, dict) and row.get("code")
    ]
    gate_blocker_codes = [
        str(code)
        for code in activation_gate_summary.get("blockerCodes", [])
        if code
    ]
    release_blocker_codes = [
        str(code)
        for code in release_gate_summary.get("blockerCodes", [])
        if code
    ]
    release_blocked = int(release_gate_summary.get("blocked") or 0) > 0
    if approval_accepted and approval_wait_resolved and (execution_mode_only_blocked or release_blocked):
        blocker_parts: list[str] = []
        if execution_mode_only_blocked:
            blocker_parts.append("MT5 执行模式闸门")
        if release_blocked:
            blocker_parts.append(f"{int(release_gate_summary.get('blocked') or 0)} 个 execution release token")
        why_not_live = (
            "聊天/操作员授权证据已接受且不再等待用户确认；当前卡在"
            f"{' 和 '.join(blocker_parts)}，本追踪器不会写订单。"
        )
    elif approval_accepted and execution_mode_only_blocked:
        why_not_live = (
            "聊天/操作员授权证据已接受，但 MT5 执行模式闸门仍关闭；需要 livePilotMode=true、"
            "readOnlyMode=false、executionEnabled=true、tradeAllowed=true 的 runtime 证据，本追踪器不会写订单。"
        )
    elif approval_accepted and target_reached and live_review.get("separateExecutionImplementationReviewReady"):
        why_not_live = "聊天/操作员授权证据已接受，cutover/rollback 审查链已就绪；真实执行仍必须单独实现 live execution lane，本追踪器不会写订单。"
    elif approval_accepted and target_reached:
        why_not_live = "聊天/操作员授权证据已接受；真实执行仍必须进入单独 execution lane 合约评审，本追踪器不会写订单。"
    elif target_reached:
        why_not_live = "模拟收益目标已达到，但尚未看到可接受的操作员授权证据；本追踪器不会写订单。"
    else:
        why_not_live = "模拟收益目标尚未达到；继续保持 shadow/review-only，本追踪器不会写订单。"
    return {
        "schema": "quantgod.authorization_vs_execution.v1",
        "chatAuthorizationAcknowledged": approval_accepted,
        "operatorApprovalEvidenceAccepted": approval_accepted,
        "approvalWaitResolved": bool(approval_wait_resolved),
        "simulationTargetReached": bool(target_reached),
        "executionModeOnlyBlocked": bool(execution_mode_only_blocked),
        "allActivationGatesPassed": bool(all_activation_gates_passed),
        "allExecutionReleaseTokensProvided": bool(
            release_gate_summary.get("allReleased") or live_review.get("allExecutionReleaseTokensProvided")
        ),
        "releaseTokensBlocked": release_blocked,
        "executionCanStartNow": False,
        "whyNotLiveNowZh": why_not_live,
        "remainingGateFields": [
            str(field)
            for field in activation_gate_summary.get("failedGateFields", [])
            if field
        ],
        "remainingBlockerCodes": gate_blocker_codes,
        "releaseTokenBlockerCodes": release_blocker_codes,
        "fileBlockerCodes": blocker_codes,
        "primaryActionableBlocker": (
            live_review.get("primaryActionableBlocker")
            if isinstance(live_review.get("primaryActionableBlocker"), dict)
            else {}
        ),
    }


def _sim_to_live_decision(
    *,
    target_reached: bool,
    lane_targets: dict[str, Any],
    live_review: dict[str, Any],
    target_usd: float,
) -> dict[str, Any]:
    target_label = _target_label(target_usd)
    execution_mode_only_blocked = bool(
        live_review.get("runtimePreflightExecutionModeOnlyBlocked")
        or live_review.get("orderContractExecutionModeOnlyBlocked")
        or live_review.get("cutoverExecutionModeOnlyBlocked")
        or live_review.get("rollbackExecutionModeOnlyBlocked")
        or live_review.get("status") == "WAITING_EXECUTION_MODE_ACTIVATION"
    )
    activation_gate_checklist = _activation_gate_checklist(live_review)
    activation_gate_summary = _activation_gate_summary(activation_gate_checklist)
    release_gate_summary = (
        live_review.get("executionReleaseGateSummary")
        if isinstance(live_review.get("executionReleaseGateSummary"), dict)
        else {}
    )
    release_gate_checklist = (
        live_review.get("executionReleaseGateChecklist")
        if isinstance(live_review.get("executionReleaseGateChecklist"), list)
        else []
    )
    release_readiness_packet = (
        live_review.get("executionReleaseReadinessPacket")
        if isinstance(live_review.get("executionReleaseReadinessPacket"), dict)
        else {}
    )
    approval_wait_resolved = bool(live_review.get("approvalWaitResolved"))
    all_release_tokens_provided = bool(
        live_review.get("allExecutionReleaseTokensProvided")
        or release_gate_summary.get("allReleased")
    )
    file_evidence = live_review.get("executionModeFileEvidence") if isinstance(live_review.get("executionModeFileEvidence"), dict) else {}
    file_evidence_blockers = live_review.get("fileEvidenceBlockers") if isinstance(live_review.get("fileEvidenceBlockers"), list) else []
    all_activation_gates_passed = bool(activation_gate_checklist and all(row.get("passed") for row in activation_gate_checklist))
    data_plane_ready = bool(
        live_review.get("dataPlaneCutoverReady")
        or live_review.get("dataPlaneRollbackReady")
        or live_review.get("runtimePreflightDataPlaneReadyForReview")
        or live_review.get("orderContractDataPlaneReadyForReview")
        or execution_mode_only_blocked
    )
    implementation_readiness_summary = (
        live_review.get("implementationReadinessSummary")
        if isinstance(live_review.get("implementationReadinessSummary"), dict)
        else {}
    )
    disabled_first_implementation_work_ready = bool(
        live_review.get("disabledFirstImplementationWorkReady")
        or implementation_readiness_summary.get("status") == "READY_TO_IMPLEMENT_DISABLED_FIRST"
    )
    if target_reached and execution_mode_only_blocked:
        status = "TARGET_REACHED_WAITING_EXECUTION_MODE_ACTIVATION"
        status_zh = f"模拟收益目标 {target_label} 已由任一 lane 或净合计达成，等待执行模式闸门"
        next_action = (
            "模拟收益目标和 HFM/BTC 数据面已达成；审批证据已验收，不再等待用户确认；"
            "当前仅剩 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 执行模式闸门"
            "以及 execution release token；已读取 Live16 启动 ini 与 deployed preset 作为文件级阻塞证据。"
            "当前仍保持 shadow/review-only，不写订单。"
            if approval_wait_resolved
            else "模拟收益目标和 HFM/BTC 数据面已达成；仅剩 livePilotMode/readOnlyMode/"
            "executionEnabled/tradeAllowed 执行模式闸门；已读取 Live16 启动 ini 与 deployed preset 作为文件级阻塞证据。当前仍保持 shadow/review-only，不写订单。"
        )
    elif target_reached and live_review.get("separateExecutionImplementationReviewReady"):
        status = "TARGET_REACHED_READY_FOR_CUTOVER_IMPLEMENTATION_REVIEW"
        status_zh = f"模拟收益目标 {target_label} 已达成，cutover/rollback 审查链已就绪"
        next_action = "目标已达成，cutover/rollback 均 READY；下一步只能进入单独 live execution implementation，实现 request 写入与 broker 调用前仍需独立审查。"
    elif target_reached:
        status = "TARGET_REACHED_READY_FOR_SEPARATE_EXECUTION_REVIEW"
        status_zh = f"模拟收益目标 {target_label} 已由任一 lane 或净合计达成，可进入单独执行评审"
        next_action = "目标已达成；下一步只应进入单独 execution lane 合约评审，本追踪器不自动下单。"
    else:
        status = "WAITING_FOR_SIMULATION_TARGETS"
        status_zh = f"等待任一 lane 或多 lane 净合计达到模拟 {target_label}"
        next_action = "继续收集 forexMt5 与 btcCryptoCfd 的可验证 USD 模拟/纸盘收益证据，直到任一 lane 或净合计达标。"
    return {
        "status": status,
        "statusZh": status_zh,
        "targetReached": bool(target_reached),
        "dataPlaneReady": data_plane_ready,
        "cutoverReady": bool(live_review.get("readyForLiveExecutionCutoverReview")),
        "rollbackReady": bool(live_review.get("readyForLiveExecutionRollbackReview")),
        "separateExecutionImplementationReviewReady": bool(live_review.get("separateExecutionImplementationReviewReady")),
        "disabledFirstImplementationWorkReady": disabled_first_implementation_work_ready,
        "nextCodeWorkAllowedInReviewOnly": bool(live_review.get("nextCodeWorkAllowedInReviewOnly")),
        "liveExecutionStillForbidden": bool(live_review.get("liveExecutionStillForbidden", True)),
        "implementationReadinessSummary": implementation_readiness_summary,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "allActivationGatesPassed": all_activation_gates_passed,
        "authorizationVsExecution": _authorization_vs_execution_summary(
            target_reached=target_reached,
            live_review=live_review,
            execution_mode_only_blocked=execution_mode_only_blocked,
            all_activation_gates_passed=all_activation_gates_passed,
            activation_gate_summary=activation_gate_summary,
            file_evidence_blockers=file_evidence_blockers,
            approval_wait_resolved=approval_wait_resolved,
            release_gate_summary=release_gate_summary,
        ),
        "activationGateChecklist": activation_gate_checklist,
        "activationGateSummary": activation_gate_summary,
        "executionActivationGateChecklist": activation_gate_checklist,
        "executionActivationGateSummary": activation_gate_summary,
        "approvalWaitResolved": approval_wait_resolved,
        "approvalWaitResolvedStages": live_review.get("approvalWaitResolvedStages")
        if isinstance(live_review.get("approvalWaitResolvedStages"), list)
        else [],
        "allExecutionReleaseTokensProvided": all_release_tokens_provided,
        "executionReleaseGateChecklist": release_gate_checklist,
        "executionReleaseGateSummary": release_gate_summary,
        "executionReleaseReadinessPacket": release_readiness_packet,
        "executionModeBlockers": (
            live_review.get("runtimePreflightExecutionModeBlockers")
            if isinstance(live_review.get("runtimePreflightExecutionModeBlockers"), list)
            else []
        ),
        "executionModeFileEvidence": file_evidence,
        "fileEvidenceBlockers": file_evidence_blockers,
        "requiredLaneSummaries": _lane_decision_summary(lane_targets),
        "liveExecutionReviewStatus": live_review.get("status"),
        "cutoverHandoff": live_review.get("cutoverHandoff") if isinstance(live_review.get("cutoverHandoff"), dict) else {},
        "rollbackSummary": live_review.get("rollbackSummary") if isinstance(live_review.get("rollbackSummary"), dict) else {},
        "primaryActionableBlocker": live_review.get("primaryActionableBlocker") if isinstance(live_review.get("primaryActionableBlocker"), dict) else {},
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "nextRequiredActionZh": next_action,
    }


def _next_required_action(
    target_reached: bool,
    blockers: list[dict[str, Any]],
    research: dict[str, Any],
    lane_targets: dict[str, Any],
    live_review: dict[str, Any],
) -> str:
    if target_reached:
        if bool(
            live_review.get("runtimePreflightExecutionModeOnlyBlocked")
            or live_review.get("orderContractExecutionModeOnlyBlocked")
            or live_review.get("cutoverExecutionModeOnlyBlocked")
            or live_review.get("rollbackExecutionModeOnlyBlocked")
            or live_review.get("status") == "WAITING_EXECUTION_MODE_ACTIVATION"
        ):
            return (
                "收益目标已由任一 lane 或多 lane 净合计达到；HFM/BTC 数据面也已通过，仅剩 livePilotMode/readOnlyMode/"
                "executionEnabled/tradeAllowed 执行模式闸门，当前仍不会写订单。"
            )
        if live_review.get("separateExecutionImplementationReviewReady"):
            return "目标已达到，cutover/rollback 均 READY；下一步只能进入单独 live execution implementation，实现 request 写入与 broker 调用前仍需独立审查。"
        return "目标已达到；下一步只应进入单独 execution lane 合约评审，不自动下单。"
    btc = lane_targets.get("btcCryptoCfd", {})
    forex = lane_targets.get("forexMt5", {})
    if btc and not btc.get("targetReached") and not btc.get("evidenceCount"):
        return "优先补齐 BTC/HFM crypto CFD 模拟或回测 USD pnl profile；外币系统继续 GA 与纸盘反馈迭代。"
    if forex and not forex.get("targetReached") and not forex.get("evidenceCount"):
        return "优先补齐外币 MT5 模拟/纸盘 USD 收益证据，同时继续 GA 下一代 shadow/tester-only 迭代。"
    codes = {str(row.get("code") or "") for row in blockers}
    if any("HFM_SIMULATION_PROFILE" in code for code in codes):
        return "优先补齐 HFM crypto CFD 合格模拟/回测 profile，再继续 paper/live 准入评估。"
    if "USDJPY_SPREAD_GATE_ACTIVE" in codes:
        return "等待 USDJPY 点差恢复并继续收集标准化执行反馈；同时继续 GA 下一代 shadow/tester-only 迭代。"
    if research.get("liveReadiness", {}).get("orderSendAllowed") is False:
        return "继续跑模拟、纸盘和执行反馈证据；当前 orderSendAllowed=false。"
    return "继续收集可验证 USD 收益证据，直到 verifiedUsdProfit 达到目标。"


def _source_manifest(paths: list[Path]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in paths:
        exists = path.exists()
        item: dict[str, Any] = {
            "path": str(path),
            "exists": exists,
        }
        if exists:
            try:
                item["bytes"] = path.stat().st_size
            except OSError:
                pass
        manifest.append(item)
    return manifest


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def _first_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            cleaned = re.sub(r"[,$%]", "", value.strip())
            if not cleaned:
                return None
            return float(cleaned)
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_recursive(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            found = value.get(key)
            if found not in (None, ""):
                return found
        for child in value.values():
            found = _first_recursive(child, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_recursive(child, keys)
            if found not in (None, ""):
                return found
    return None
