from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from tools.usdjpy_strategy_lab.data_loader import (
        _write_json,
        fastlane_quality,
        focus_runtime_snapshot,
        first_json,
        is_focus_symbol,
        read_all_csv,
        to_direction,
        to_float,
    )
    from tools.usdjpy_strategy_lab.schema import normalize_strategy_name
except ModuleNotFoundError:  # pragma: no cover - CLI entrypoint runs from tools/
    from usdjpy_strategy_lab.data_loader import (
        _write_json,
        fastlane_quality,
        focus_runtime_snapshot,
        first_json,
        is_focus_symbol,
        read_all_csv,
        to_direction,
        to_float,
    )
    from usdjpy_strategy_lab.schema import normalize_strategy_name

from .schema import FOCUS_SYMBOL, READ_ONLY_SAFETY, SCHEMA_DATASET, utc_now_iso

HISTORY_PRODUCTION_STATUS_FILE = "QuantGod_USDJPYHistoryProductionStatus.json"
HISTORY_TIMEFRAMES = ("M1", "M5", "M15", "H1")
DEFAULT_REPLAY_RISK_PIPS = 10.0


def _pick(row: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return default


def _symbol(row: Dict[str, Any]) -> str:
    return str(_pick(row, "symbol", "Symbol", "品种", default=FOCUS_SYMBOL) or FOCUS_SYMBOL)


def _is_usdjpy_row(row: Dict[str, Any]) -> bool:
    return is_focus_symbol(_symbol(row)) or "USDJPY" in json.dumps(row, ensure_ascii=False).upper()


def _pip_size(symbol: str) -> float:
    normalized = str(symbol or "").upper()
    return 0.01 if "JPY" in normalized else 0.0001


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


def _price_move_pips(row: Dict[str, Any], direction: str, symbol: str) -> float | None:
    open_price = to_float(_pick(row, "OpenPrice", "openPrice", "entryPrice", "EntryPrice"), None)
    close_price = to_float(_pick(row, "ClosePrice", "closePrice", "exitPrice", "ExitPrice", "FutureClose"), None)
    if open_price is None or close_price is None:
        return None
    move = (close_price - open_price) / _pip_size(symbol)
    if direction == "SHORT":
        move = -move
    return _round(move, 4)


def _directional_pips(row: Dict[str, Any], direction: str, symbol: str) -> float | None:
    generic = to_float(
        _pick(
            row,
            "pips",
            "profitPips",
            "pnlPips",
            "outcomePips",
            "DirectionalOutcomePips",
            "DirectionalOutcome",
            default="",
        ),
        None,
    )
    if generic is not None:
        return generic
    if direction == "SHORT":
        value = to_float(_pick(row, "ShortClosePips", "shortClosePips", default=""), None)
        if value is not None:
            return value
    else:
        value = to_float(_pick(row, "LongClosePips", "longClosePips", default=""), None)
        if value is not None:
            return value
    return _price_move_pips(row, direction, symbol)


def _directional_excursion_pips(row: Dict[str, Any], direction: str, kind: str) -> float | None:
    if kind == "mfe":
        generic_keys = ("mfePips", "maxFavorablePips", "MfePips")
        direction_keys = ("ShortMFEPips", "shortMFEPips") if direction == "SHORT" else ("LongMFEPips", "longMFEPips")
    else:
        generic_keys = ("maePips", "maxAdversePips", "MaePips")
        direction_keys = ("ShortMAEPips", "shortMAEPips") if direction == "SHORT" else ("LongMAEPips", "longMAEPips")
    value = to_float(_pick(row, *generic_keys, default=""), None)
    if value is not None:
        return abs(value)
    value = to_float(_pick(row, *direction_keys, default=""), None)
    return abs(value) if value is not None else None


def _risk_pips(row: Dict[str, Any], mae_pips: float | None) -> float | None:
    risk = to_float(_pick(row, "riskPips", "initialRiskPips", "slPips", "RiskPips"), None)
    if risk is not None and risk > 0:
        return risk
    if mae_pips is not None and mae_pips > 0:
        return max(DEFAULT_REPLAY_RISK_PIPS, abs(mae_pips))
    return DEFAULT_REPLAY_RISK_PIPS


def _r_from_pips(pips: float | None, risk_pips: float | None) -> float | None:
    if pips is None or risk_pips is None or risk_pips <= 0:
        return None
    return _round(pips / risk_pips, 4)


def _posterior_window(row: Dict[str, Any]) -> str:
    minutes = to_float(_pick(row, "HorizonMinutes", "horizonMinutes", "horizonMins", default=""), None)
    if minutes is None:
        bars = to_float(_pick(row, "HorizonBars", "horizonBars", default=""), None)
        timeframe = str(_pick(row, "Timeframe", "timeframe", default="")).upper()
        if bars is not None and timeframe.startswith("M"):
            minutes = bars * to_float(timeframe[1:], 1.0)
    if minutes is None:
        return "60m"
    if minutes <= 15:
        return "15m"
    if minutes <= 30:
        return "30m"
    if minutes <= 60:
        return "60m"
    return "120m"


def _posterior_maps(row: Dict[str, Any], source: str, profit_pips: float | None, risk_pips: float | None) -> tuple[Dict[str, Any], Dict[str, Any]]:
    posterior_pips = {
        "15m": to_float(_pick(row, "pipsAfter15", "futurePips15", "posteriorPips15", "post15Pips"), None),
        "30m": to_float(_pick(row, "pipsAfter30", "futurePips30", "posteriorPips30", "post30Pips"), None),
        "60m": to_float(_pick(row, "pipsAfter60", "futurePips60", "posteriorPips60", "post60Pips"), None),
        "120m": to_float(_pick(row, "pipsAfter120", "futurePips120", "posteriorPips120", "post120Pips"), None),
    }
    posterior_r = {
        "15m": to_float(_pick(row, "rAfter15", "futureR15", "posteriorR15", "post15R"), None),
        "30m": to_float(_pick(row, "rAfter30", "futureR30", "posteriorR30", "post30R"), None),
        "60m": to_float(_pick(row, "rAfter60", "futureR60", "posteriorR60", "post60R"), None),
        "120m": to_float(_pick(row, "rAfter120", "futureR120", "posteriorR120", "post120R"), None),
    }
    if source == "shadow_outcomes" and profit_pips is not None:
        window = _posterior_window(row)
        if posterior_pips.get(window) is None:
            posterior_pips[window] = profit_pips
        if posterior_r.get(window) is None:
            posterior_r[window] = _r_from_pips(profit_pips, risk_pips)
    return posterior_pips, posterior_r


def _sample_from_csv(row: Dict[str, Any], source: str) -> Dict[str, Any]:
    symbol = _symbol(row)
    direction = to_direction(_pick(row, "direction", "side", "type", "orderType", "CandidateDirection", "方向"))
    profit = to_float(_pick(row, "profit", "netUSC", "pnl", "profitUSC", "NetUSC", "NetProfit", "净值"), 0.0)
    profit_pips = _directional_pips(row, direction, symbol)
    mfe_pips = _directional_excursion_pips(row, direction, "mfe")
    mae_pips = _directional_excursion_pips(row, direction, "mae")
    risk_pips = _risk_pips(row, mae_pips)
    profit_r = to_float(_pick(row, "profitR", "rMultiple", "r", "signedR", "ProfitR"), None)
    if profit_r is None and source != "shadow_outcomes":
        profit_r = _r_from_pips(profit_pips, risk_pips)
    mfe_r = to_float(_pick(row, "mfeR", "MFER", "mfe", "maxFavorableR"), None)
    if mfe_r is None:
        mfe_r = _r_from_pips(mfe_pips, risk_pips)
    mae_r = to_float(_pick(row, "maeR", "MAER", "mae", "maxAdverseR"), None)
    if mae_r is None and mae_pips is not None:
        mae_r = -abs(_r_from_pips(mae_pips, risk_pips) or 0.0)
    blocker = str(_pick(row, "blocker", "blockReason", "reason", "status", "event", "label", "说明", default="")).strip()
    entered = str(_pick(row, "didEnter", "entered", "event", "type", default="")).upper() in {"1", "TRUE", "ENTRY", "OPEN"}
    if source == "close_history":
        entered = True
    ready = (
        "READY" in blocker.upper()
        or str(_pick(row, "readyBuySignal", "rsiBuySignal", default="")).lower() == "true"
        or source == "shadow_outcomes"
    )
    posterior_pips, posterior_r = _posterior_maps(row, source, profit_pips, risk_pips)
    return {
        "source": source,
        "timestamp": _pick(
            row,
            "timestamp",
            "time",
            "Time",
            "closeTime",
            "openTime",
            "generatedAtIso",
            "OutcomeLabelTimeServer",
            "EventBarTime",
        ),
        "symbol": FOCUS_SYMBOL,
        "strategy": normalize_strategy_name(_pick(row, "strategy", "route", "routeKey", "strategyName", "CandidateRoute", default="UNKNOWN")),
        "direction": direction,
        "status": _pick(row, "status", "state", "event", "label", "OutcomeReason", default="SHADOW_CANDIDATE_SIGNAL" if source == "shadow_outcomes" else ""),
        "blockReason": blocker,
        "didEnter": bool(entered),
        "wouldEnter": bool(ready or "WOULD" in blocker.upper()),
        "profitUSC": profit,
        "profitPips": profit_pips,
        "profitR": profit_r,
        "riskPips": risk_pips,
        "mfeR": mfe_r,
        "maeR": mae_r,
        "mfePips": mfe_pips,
        "maePips": mae_pips,
        "posteriorPips": posterior_pips,
        "posteriorR": posterior_r,
        "exitReason": _pick(row, "exitReason", "closeReason", "reason"),
        "raw": row,
    }


def _diagnostic_sample(runtime_dir: Path) -> Dict[str, Any] | None:
    diag = first_json(runtime_dir, "QuantGod_USDJPYRsiEntryDiagnostics.json") or {}
    if not diag:
        dashboard = focus_runtime_snapshot(runtime_dir) or {}
        diag = dashboard.get("usdJpyRsiEntryDiagnostics") if isinstance(dashboard.get("usdJpyRsiEntryDiagnostics"), dict) else {}
    if not diag:
        return None
    status = str(diag.get("status") or diag.get("conclusion") or "").upper()
    blockers = diag.get("mainBlockers") if isinstance(diag.get("mainBlockers"), list) else []
    return {
        "source": "rsi_entry_diagnostics",
        "timestamp": diag.get("generatedAtIso") or diag.get("timestamp"),
        "symbol": FOCUS_SYMBOL,
        "strategy": "RSI_Reversal",
        "direction": "LONG",
        "status": status or "UNKNOWN",
        "blockReason": "; ".join(str(item) for item in blockers) or diag.get("message") or "",
        "didEnter": False,
        "wouldEnter": status == "READY_BUY_SIGNAL" or bool(diag.get("rsiBuySignal")),
        "profitUSC": 0.0,
        "mfeR": 0.0,
        "maeR": 0.0,
        "exitReason": "",
        "raw": diag,
    }


def _collect_samples(runtime_dir: Path) -> List[Dict[str, Any]]:
    sources = [
        ("close_history", ("QuantGod_CloseHistory.csv", "QuantGod_CloseHistoryLedger.csv", "QuantGod_MT5CloseHistory.csv")),
        ("trade_journal", ("QuantGod_TradeJournal.csv", "QuantGod_MT5TradeJournal.csv", "QuantGod_TradeJournalLedger.csv")),
        ("entry_blockers", ("QuantGod_EntryBlockers.csv", "QuantGod_MT5EntryBlockers.csv", "QuantGod_EntryBlockerLedger.csv")),
        ("shadow_outcomes", ("ShadowCandidateOutcomeLedger.csv", "QuantGod_ShadowCandidateOutcomeLedger.csv")),
        ("strategy_report", ("QuantGod_StrategyEvaluationReport.csv",)),
    ]
    samples: List[Dict[str, Any]] = []
    for source, names in sources:
        for row in read_all_csv(runtime_dir, *names):
            if _is_usdjpy_row(row):
                samples.append(_sample_from_csv(row, source))
    diag = _diagnostic_sample(runtime_dir)
    if diag:
        samples.insert(0, diag)
    return samples


def _blocker_counter(samples: Iterable[Dict[str, Any]]) -> Counter:
    counter: Counter = Counter()
    for sample in samples:
        text = str(sample.get("blockReason") or sample.get("status") or "").upper()
        if not text:
            continue
        for token in ("SESSION", "SPREAD", "NEWS", "COOLDOWN", "STARTUP", "WAIT", "ROUTE_DISABLED", "NO_CROSS", "KILL"):
            if token in text:
                counter[token] += 1
    return counter


def _read_history_production_status(runtime_dir: Path) -> Dict[str, Any]:
    candidates = [
        runtime_dir / "backtest" / HISTORY_PRODUCTION_STATUS_FILE,
        runtime_dir / "quality" / HISTORY_PRODUCTION_STATUS_FILE,
        runtime_dir / HISTORY_PRODUCTION_STATUS_FILE,
    ]
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("_filePath", str(path))
                return payload
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return {}


def _history_freshness_gate(history_status: Dict[str, Any]) -> Dict[str, Any]:
    if not history_status:
        return {
            "status": "MISSING",
            "passed": False,
            "blockers": ["history_production_status_missing"],
            "failedTimeframes": list(HISTORY_TIMEFRAMES),
            "reasonZh": "缺少 USDJPY M1/M5/M15/H1 历史生产状态，不能把研究结果包装成晋级证据。",
        }

    timeframes = history_status.get("timeframes") if isinstance(history_status.get("timeframes"), dict) else {}
    failed: list[str] = []
    stale: list[str] = []
    for timeframe in HISTORY_TIMEFRAMES:
        row = timeframes.get(timeframe) if isinstance(timeframes.get(timeframe), dict) else {}
        if row.get("passed") is not True:
            failed.append(timeframe)
        if row.get("freshnessOk") is not True:
            stale.append(timeframe)
    passed = bool(history_status.get("historyTargetSatisfied") is True and not failed)
    blockers: list[str] = []
    if failed:
        blockers.append("history_timeframes_not_production_ready")
    if stale:
        blockers.append("history_freshness_lag_exceeded")
    if not bool(history_status.get("historyTargetSatisfied")):
        blockers.append("history_target_not_satisfied")
    return {
        "status": "PASS" if passed else "BLOCKED",
        "passed": passed,
        "blockers": blockers,
        "failedTimeframes": failed,
        "staleTimeframes": stale,
        "generatedAt": history_status.get("generatedAt"),
        "maxLatestLagHours": history_status.get("maxLatestLagHours"),
        "reasonZh": (
            "USDJPY M1/M5/M15/H1 历史覆盖、密度和 freshness 均通过，可作为晋级前置证据。"
            if passed
            else "USDJPY 历史生产状态未通过；覆盖/密度/最新延迟未全部达标前，只允许研究、shadow 或 tester-only。"
        ),
    }


def build_runtime_dataset(runtime_dir: Path, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    samples = _collect_samples(runtime_dir)
    blockers = _blocker_counter(samples)
    close_trades = [sample for sample in samples if sample.get("source") == "close_history"]
    decision_samples = [sample for sample in samples if sample.get("source") != "close_history"]
    ready = [sample for sample in samples if sample.get("wouldEnter")]
    entered = [sample for sample in samples if sample.get("didEnter")]
    net_usc = round(sum(to_float(sample.get("profitUSC"), 0.0) for sample in close_trades), 4)
    live_loop = first_json(runtime_dir, "QuantGod_USDJPYLiveLoopStatus.json") or {}
    policy = first_json(runtime_dir, "QuantGod_USDJPYAutoExecutionPolicy.json") or {}
    fastlane = fastlane_quality(runtime_dir)
    history_status = _read_history_production_status(runtime_dir)
    history_gate = _history_freshness_gate(history_status)
    dataset_dir = runtime_dir / "datasets" / "usdjpy"
    payload = {
        "ok": True,
        "schema": SCHEMA_DATASET,
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "runtimeDir": str(runtime_dir),
        "datasetDir": str(dataset_dir),
        "safety": READ_ONLY_SAFETY,
        "summary": {
            "sampleCount": len(samples),
            "decisionSampleCount": len(decision_samples),
            "readySignalCount": len(ready),
            "actualEntryCount": len(entered),
            "blockedCount": sum(blockers.values()),
            "closeTradeCount": len(close_trades),
            "netUSC": net_usc,
            "blockerCounts": dict(blockers.most_common()),
            "fastlaneQuality": fastlane.get("quality"),
            "historyFreshnessStatus": history_gate.get("status"),
            "historyFreshnessPass": history_gate.get("passed"),
            "historyFailedTimeframes": history_gate.get("failedTimeframes", []),
            "historyStaleTimeframes": history_gate.get("staleTimeframes", []),
            "liveLoopState": live_loop.get("state"),
            "topLiveEligiblePolicy": (policy.get("topLiveEligiblePolicy") or {}).get("strategy"),
            "topShadowPolicy": (policy.get("topShadowPolicy") or {}).get("strategy"),
        },
        "latest": {
            "runtime": focus_runtime_snapshot(runtime_dir) or {},
            "fastlane": fastlane,
            "liveLoop": live_loop,
            "policy": policy,
            "historyProductionStatus": history_status,
            "historyFreshnessGate": history_gate,
        },
        "samples": samples[:500],
    }
    if write:
        _write_json(dataset_dir / "QuantGod_USDJPYRuntimeDataset.json", payload)
        jsonl = dataset_dir / "QuantGod_USDJPYDecisionSamples.jsonl"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        jsonl.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in samples) + ("\n" if samples else ""), encoding="utf-8")
    return payload
