from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from tools.strategy_json.schema import base_strategy_seed
except ModuleNotFoundError:  # pragma: no cover
    from strategy_json.schema import base_strategy_seed

from .historical_news import load_historical_news_events
from .schema import AGENT_VERSION, FOCUS_SYMBOL, SAFETY_BOUNDARY, atomic_write_json
from .sqlite_store import (
    BAR_TABLES,
    Bar,
    connect,
    count_bars,
    load_bars_range,
    write_sample_bars,
)
from .strategy_runner import run_strategy

SEGMENTS: Tuple[Tuple[str, float], ...] = (
    ("train", 0.60),
    ("validation", 0.20),
    ("forward", 0.20),
)

SEGMENT_LABEL_ZH = {
    "train": "训练段",
    "validation": "验证段",
    "forward": "前推段",
}

MIN_REFERENCE_BARS = 60
MIN_SEGMENT_BARS = 12


def build_seed_walk_forward(
    runtime_dir: Path,
    strategy_json: Dict[str, Any] | None = None,
    write: bool = False,
) -> Dict[str, Any]:
    """Run causal train/validation/forward backtests for one Strategy JSON seed.

    The split is based only on historical bar timestamps. Posterior outcomes
    never affect entry decisions; they are produced by the same Strategy JSON
    runner used by full backtest scoring.
    """

    seed = strategy_json or base_strategy_seed("WALK-FORWARD-USDJPY-RSI-LONG")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    historical_news = load_historical_news_events(runtime_dir)
    parity_status = _parity_status(runtime_dir)
    execution_penalty = _execution_feedback_penalty(runtime_dir)

    with connect(runtime_dir) as conn:
        if count_bars(conn, "H1") < 40:
            write_sample_bars(runtime_dir, overwrite=False)
        primary_timeframe = _select_reference_timeframe(conn, seed)
        reference_bars = load_bars_range(conn, primary_timeframe, limit=200000)
        history_counts = {timeframe: count_bars(conn, timeframe) for timeframe in BAR_TABLES}
        segment_ranges = _segment_ranges(reference_bars)
        segment_payloads: List[Dict[str, Any]] = []
        for name, start_index, end_index in segment_ranges:
            start_bar = reference_bars[start_index]
            end_bar = reference_bars[end_index - 1]
            bars_by_timeframe = {
                timeframe: load_bars_range(
                    conn,
                    timeframe,
                    start=start_bar.timestamp,
                    end=end_bar.timestamp,
                    limit=200000,
                )
                for timeframe in BAR_TABLES
            }
            segment_payloads.append(
                _run_segment(
                    name,
                    start_bar.timestamp,
                    end_bar.timestamp,
                    primary_timeframe,
                    bars_by_timeframe,
                    seed,
                    historical_news,
                    parity_status,
                    execution_penalty,
                )
            )

    summary = _summary(segment_payloads, parity_status, execution_penalty, primary_timeframe, history_counts)
    report = {
        "ok": summary["promotionGateStatus"] != "BLOCKED",
        "schema": "quantgod.usdjpy_seed_walk_forward.v1",
        "agentVersion": AGENT_VERSION,
        "createdAt": now,
        "symbol": FOCUS_SYMBOL,
        "seedId": seed.get("seedId"),
        "strategyId": seed.get("strategyId"),
        "strategyFamily": seed.get("strategyFamily"),
        "direction": seed.get("direction"),
        "primaryTimeframe": primary_timeframe,
        "splitPolicy": {
            "schema": "quantgod.walk_forward_split.v1",
            "trainPct": 60,
            "validationPct": 20,
            "forwardPct": 20,
            "causalReplay": True,
            "posteriorMayAffectTrigger": False,
            "reasonZh": "每个 GA seed 独立切 train / validation / forward；后验结果只用于评分，不能决定当时入场。",
        },
        "segments": segment_payloads,
        "summary": summary,
        "safety": dict(SAFETY_BOUNDARY),
    }
    if write:
        path = runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYSeedWalkForwardReport.json"
        atomic_write_json(path, report)
    return report


def _select_reference_timeframe(conn: Any, seed: Dict[str, Any]) -> str:
    indicators = seed.get("indicators") if isinstance(seed.get("indicators"), dict) else {}
    family = str(seed.get("strategyFamily") or "")
    cfg_key = {
        "RSI_Reversal": "rsi",
        "MA_Cross": "ma",
        "BB_Triple": "bollinger",
        "MACD_Divergence": "macd",
        "SR_Breakout": "supportResistance",
        "USDJPY_TOKYO_RANGE_BREAKOUT": "tokyoRange",
        "USDJPY_NIGHT_REVERSION_SAFE": "nightReversion",
        "USDJPY_H4_TREND_PULLBACK": "h4Pullback",
    }.get(family, "rsi")
    family_cfg = indicators.get(cfg_key) if isinstance(indicators.get(cfg_key), dict) else {}
    rsi = indicators.get("rsi") if isinstance(indicators.get("rsi"), dict) else {}
    preferred = str(family_cfg.get("timeframe") or rsi.get("timeframe") or "H1").upper()
    candidates = [preferred, "H1", "M15", "M5", "M1", "H4", "D1"]
    seen = set()
    for timeframe in candidates:
        if timeframe in seen or timeframe not in BAR_TABLES:
            continue
        seen.add(timeframe)
        if count_bars(conn, timeframe) >= MIN_REFERENCE_BARS:
            return timeframe
    return "H1"


def _segment_ranges(reference_bars: List[Bar]) -> List[Tuple[str, int, int]]:
    count = len(reference_bars)
    if count < MIN_REFERENCE_BARS:
        return []
    train_end = max(MIN_SEGMENT_BARS, int(count * 0.60))
    validation_end = max(train_end + MIN_SEGMENT_BARS, int(count * 0.80))
    validation_end = min(validation_end, count - MIN_SEGMENT_BARS)
    if validation_end <= train_end:
        return []
    return [
        ("train", 0, train_end),
        ("validation", train_end, validation_end),
        ("forward", validation_end, count),
    ]


def _run_segment(
    name: str,
    start: str,
    end: str,
    primary_timeframe: str,
    bars_by_timeframe: Dict[str, List[Bar]],
    seed: Dict[str, Any],
    historical_news: Dict[str, Any],
    parity_status: str,
    execution_penalty: float,
) -> Dict[str, Any]:
    primary_bars = bars_by_timeframe.get(primary_timeframe, [])
    if len(primary_bars) < MIN_SEGMENT_BARS:
        return _empty_segment(
            name,
            start,
            end,
            primary_timeframe,
            parity_status,
            execution_penalty,
            "SEGMENT_INSUFFICIENT_BARS",
            f"{SEGMENT_LABEL_ZH.get(name, name)} K线不足，不能做稳定评分。",
        )
    result = run_strategy(seed, bars_by_timeframe, historical_news=historical_news)
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    ok = bool(result.get("ok"))
    blocker = "" if ok else "SEGMENT_BACKTEST_FAILED"
    return {
        "segment": name,
        "labelZh": SEGMENT_LABEL_ZH.get(name, name),
        "start": start,
        "end": end,
        "ok": ok,
        "blockerCode": blocker,
        "reasonZh": result.get("reasonZh") or ("分段回测完成。" if ok else "分段回测失败。"),
        "primaryTimeframe": primary_timeframe,
        "barCount": len(primary_bars),
        "parityStatus": parity_status,
        "executionFeedbackPenalty": execution_penalty,
        "metrics": _segment_metrics(metrics),
        **_segment_metrics(metrics),
    }


def _empty_segment(
    name: str,
    start: str,
    end: str,
    primary_timeframe: str,
    parity_status: str,
    execution_penalty: float,
    blocker: str,
    reason: str,
) -> Dict[str, Any]:
    metrics = _segment_metrics({})
    return {
        "segment": name,
        "labelZh": SEGMENT_LABEL_ZH.get(name, name),
        "start": start,
        "end": end,
        "ok": False,
        "blockerCode": blocker,
        "reasonZh": reason,
        "primaryTimeframe": primary_timeframe,
        "barCount": 0,
        "parityStatus": parity_status,
        "executionFeedbackPenalty": execution_penalty,
        "metrics": metrics,
        **metrics,
    }


def _segment_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "netR": round(_num(metrics.get("netR")), 4),
        "profitFactor": round(_num(metrics.get("profitFactor")), 4),
        "winRate": round(_num(metrics.get("winRate")), 4),
        "maxDrawdownR": round(_num(metrics.get("maxDrawdownR")), 4),
        "sharpe": round(_num(metrics.get("sharpe")), 4),
        "sortino": round(_num(metrics.get("sortino")), 4),
        "tradeCount": int(_num(metrics.get("tradeCount"))),
        "avgR": round(_num(metrics.get("avgR")), 4),
        "medianR": round(_num(metrics.get("medianR")), 4),
        "lossStreak": int(_num(metrics.get("lossStreak"))),
        "profitCaptureRatio": round(_num(metrics.get("profitCaptureRatio")), 4),
        "maxAdverseR": round(_num(metrics.get("maxAdverseR")), 4),
    }


def _summary(
    segments: List[Dict[str, Any]],
    parity_status: str,
    execution_penalty: float,
    primary_timeframe: str,
    history_counts: Dict[str, int],
) -> Dict[str, Any]:
    by_name = {str(item.get("segment")): item for item in segments}
    train = by_name.get("train", {})
    validation = by_name.get("validation", {})
    forward = by_name.get("forward", {})
    valid_segments = [item for item in segments if item.get("ok")]
    total_trades = sum(int(_num(item.get("tradeCount"))) for item in segments)
    validation_net = _num(validation.get("netR"))
    forward_net = _num(forward.get("netR"))
    train_net = _num(train.get("netR"))
    max_drawdown = max((_num(item.get("maxDrawdownR")) for item in segments), default=0.0)
    max_adverse = min((_num(item.get("maxAdverseR")) for item in segments), default=0.0)
    overfit_penalty = _overfit_penalty(train_net, validation_net, forward_net, max_drawdown, total_trades)
    stability_score = _stability_score(segments, overfit_penalty, execution_penalty)
    blocker = _blocker(segments, total_trades, validation_net, forward_net, overfit_penalty)
    status = "BLOCKED" if blocker else ("PASS" if stability_score >= 0.70 else "WARN")
    return {
        "schema": "quantgod.usdjpy_seed_walk_forward_summary.v1",
        "primaryTimeframe": primary_timeframe,
        "historyBarCounts": history_counts,
        "segmentCount": len(segments),
        "validSegmentCount": len(valid_segments),
        "sampleCount": total_trades,
        "trainNetR": round(train_net, 4),
        "validationNetR": round(validation_net, 4),
        "forwardNetR": round(forward_net, 4),
        "validationNetRDelta": round(validation_net - train_net, 4),
        "forwardNetRDelta": round(forward_net - validation_net, 4),
        "maxDrawdownR": round(max_drawdown, 4),
        "maxAdverseR": round(max_adverse, 4),
        "parityStatus": parity_status,
        "executionFeedbackPenalty": execution_penalty,
        "overfitPenalty": round(overfit_penalty, 4),
        "stabilityScore": round(stability_score, 4),
        "promotionGateStatus": status,
        "promotionAllowed": status == "PASS",
        "blockerCode": blocker,
        "evidenceQuality": _evidence_quality(total_trades, len(valid_segments), stability_score),
        "reasonZh": _summary_reason(status, blocker, stability_score),
    }


def _overfit_penalty(
    train_net: float,
    validation_net: float,
    forward_net: float,
    max_drawdown: float,
    total_trades: int,
) -> float:
    penalty = 0.0
    if validation_net < 0:
        penalty += 0.35
    if forward_net < 0:
        penalty += 0.45
    if train_net > 0 and (validation_net <= 0 or forward_net <= 0):
        penalty += 0.25
    if max_drawdown > 2.0:
        penalty += min(0.35, (max_drawdown - 2.0) * 0.08)
    if total_trades < 5:
        penalty += 0.35
    elif total_trades < 12:
        penalty += 0.15
    return round(min(1.25, penalty), 4)


def _stability_score(segments: List[Dict[str, Any]], overfit_penalty: float, execution_penalty: float) -> float:
    if not segments:
        return 0.0
    score = 1.0
    score -= overfit_penalty * 0.45
    score -= min(0.25, execution_penalty * 0.15)
    for item in segments:
        if not item.get("ok"):
            score -= 0.18
        if _num(item.get("profitFactor")) < 1.0 and int(_num(item.get("tradeCount"))) > 0:
            score -= 0.08
        if _num(item.get("maxDrawdownR")) > 1.5:
            score -= 0.05
    return max(0.0, min(1.0, score))


def _blocker(
    segments: List[Dict[str, Any]],
    total_trades: int,
    validation_net: float,
    forward_net: float,
    overfit_penalty: float,
) -> str | None:
    if len(segments) != 3:
        return "WALK_FORWARD_INSUFFICIENT"
    if any(not item.get("ok") for item in segments):
        return "WALK_FORWARD_FAILED"
    if total_trades < 5:
        return "WALK_FORWARD_INSUFFICIENT"
    if validation_net < 0 or forward_net < 0 or overfit_penalty >= 0.65:
        return "WALK_FORWARD_UNSTABLE"
    return None


def _evidence_quality(total_trades: int, valid_segments: int, stability_score: float) -> str:
    if valid_segments < 3 or total_trades < 5:
        return "LOW"
    if stability_score >= 0.82 and total_trades >= 20:
        return "HIGH"
    if stability_score >= 0.60:
        return "MEDIUM"
    return "LOW"


def _summary_reason(status: str, blocker: str | None, stability_score: float) -> str:
    if status == "PASS":
        return "该 Strategy JSON seed 在 train / validation / forward 三段均保持稳定，可进入下一层 GA 评估。"
    if blocker == "WALK_FORWARD_INSUFFICIENT":
        return "该 Strategy JSON seed 的三段交易样本不足，不能证明样本外稳定。"
    if blocker == "WALK_FORWARD_UNSTABLE":
        return "该 Strategy JSON seed 在 validation 或 forward 段不稳定，疑似过拟合。"
    if blocker == "WALK_FORWARD_FAILED":
        return "该 Strategy JSON seed 的分段回测未全部通过。"
    return f"该 Strategy JSON seed 三段稳定分 {stability_score:.2f}，仅可作为 shadow/tester 证据。"


def _parity_status(runtime_dir: Path) -> str:
    payload = _load_json(runtime_dir / "evidence_os" / "QuantGod_StrategyParityReport.json")
    if not payload:
        return "MISSING"
    gate = payload.get("promotionGate") if isinstance(payload.get("promotionGate"), dict) else {}
    if gate.get("status") == "BLOCKED":
        return "PARITY_BLOCKED"
    return str(payload.get("status") or gate.get("status") or "UNKNOWN")


def _execution_feedback_penalty(runtime_dir: Path) -> float:
    payload = _load_json(runtime_dir / "evidence_os" / "QuantGod_LiveExecutionQualityReport.json")
    if not payload:
        return 0.35
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    gate = payload.get("promotionGate") if isinstance(payload.get("promotionGate"), dict) else {}
    penalty = 0.0
    if gate.get("status") == "BLOCKED":
        penalty += 0.45
    penalty += min(0.25, _num(metrics.get("rejectCount")) * 0.05)
    penalty += min(0.25, _num(metrics.get("policyMismatchCount")) * 0.10)
    penalty += max(0.0, _num(metrics.get("avgAbsSlippagePips")) - 0.8) * 0.15
    penalty += max(0.0, _num(metrics.get("avgLatencyMs")) - 1500.0) / 6000.0
    penalty += min(0.35, _num(metrics.get("coreMissingFieldCount")) * 0.12)
    return round(min(1.0, penalty), 4)


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default
