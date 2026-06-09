from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

try:
    from tools.usdjpy_strategy_backtest.sqlite_store import Bar, connect, load_bars
except ModuleNotFoundError:  # pragma: no cover
    from usdjpy_strategy_backtest.sqlite_store import Bar, connect, load_bars

from .schema import SAFETY, SCHEMA_VERSION, simulation_profile_review_path, simulation_trades_path, utc_now_iso


PNL_USD_MIN = 0.0
ROI_MIN_PCT = 0.0
SHARPE_MIN = 1.0
MAX_DRAWDOWN_MAX_PCT = 15.0
TRADE_COUNT_MIN = 20
MAX_LOT = 0.01
INITIAL_EQUITY_USD = 1000.0


def build_forex_simulation_profile_review(
    runtime_dir: Path,
    *,
    write: bool = False,
    initial_equity_usd: float = INITIAL_EQUITY_USD,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    bars = _load_h1_bars(runtime_dir)
    candidates = [_score_candidate(bars, candidate, initial_equity_usd) for candidate in _candidate_definitions()]
    selected = _select_candidate(candidates)
    blockers = _simulation_metric_blockers(
        selected.get("metrics", {}) if selected else {},
        bool(selected),
    )
    qualified = bool(selected) and not blockers
    payload: dict[str, Any] = {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": "FOREX_SIMULATION_PROFILE_QUALIFIED" if qualified else "WAITING_FOREX_SIMULATION_PROFILE",
        "statusZh": "外币 MT5 模拟 profile 已证明正收益" if qualified else "等待外币 MT5 合格模拟 profile",
        "simulationQualified": qualified,
        "qualified": qualified,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "profile": selected.get("profile", {}) if selected else {},
        "metrics": selected.get("metrics", {}) if selected else {},
        "selectedCandidate": selected.get("candidate", {}) if selected else {},
        "candidateResults": [_candidate_result_summary(row) for row in candidates],
        "selectionPolicy": "qualified_highest_sharpe_then_pnl_shadow_only",
        "thresholds": {
            "pnlUsdMin": PNL_USD_MIN,
            "roiPctMinExclusive": ROI_MIN_PCT,
            "sharpeMin": SHARPE_MIN,
            "maxDrawdownPctMax": MAX_DRAWDOWN_MAX_PCT,
            "tradeCountMin": TRADE_COUNT_MIN,
            "maxLot": MAX_LOT,
            "allTimeSegmentsMustBePositive": True,
        },
        "dataCoverage": _data_coverage(bars),
        "blockers": blockers,
        "nextRequiredActionZh": (
            "外币模拟已证明正收益；下一步只能进入单独 execution lane 评审，不自动下单。"
            if qualified
            else "继续生成 USDJPY/HFM 外币模拟候选，直到 PnL、Sharpe、回撤和分段稳定性全部达标。"
        ),
        "safety": dict(SAFETY),
    }
    if write:
        out = simulation_profile_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        _write_trades(runtime_dir, selected.get("trades", []) if selected else [])
    return payload


def read_forex_simulation_profile_review(runtime_dir: Path) -> dict[str, Any]:
    path = simulation_profile_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
        except Exception:
            pass
    return build_forex_simulation_profile_review(Path(runtime_dir), write=False)


def _candidate_definitions() -> list[dict[str, Any]]:
    return [
        {
            "agentId": "qg_usdjpy_h1_ema_trend_long_tp60_sl32_hold8_v1",
            "strategyFamily": "EMA_H1_TREND_CONTINUATION",
            "descriptionZh": "H1 EMA 斜率顺势，只做 USDJPYc 多头，低手数纸盘模拟。",
            "timeframe": "H1",
            "emaSpan": 24,
            "slopeLookbackBars": 24,
            "slopeThresholdPips": 2.0,
            "direction": "long",
            "takeProfitPips": 60.0,
            "stopLossPips": 32.0,
            "maxHoldBars": 8,
            "cooldownBars": 4,
            "lot": 0.01,
        },
        {
            "agentId": "qg_usdjpy_h1_ema_trend_long_tp60_sl32_hold4_v1",
            "strategyFamily": "EMA_H1_TREND_CONTINUATION",
            "descriptionZh": "H1 EMA 斜率顺势，较短持仓版本，用来对照持仓风险。",
            "timeframe": "H1",
            "emaSpan": 24,
            "slopeLookbackBars": 24,
            "slopeThresholdPips": 2.0,
            "direction": "long",
            "takeProfitPips": 60.0,
            "stopLossPips": 32.0,
            "maxHoldBars": 4,
            "cooldownBars": 4,
            "lot": 0.01,
        },
        {
            "agentId": "qg_usdjpy_h1_ema_conservative_long_tp60_sl32_hold8_v1",
            "strategyFamily": "EMA_H1_TREND_CONTINUATION",
            "descriptionZh": "更强斜率过滤的 H1 顺势候选，交易频率更低。",
            "timeframe": "H1",
            "emaSpan": 48,
            "slopeLookbackBars": 6,
            "slopeThresholdPips": 16.0,
            "direction": "long",
            "takeProfitPips": 60.0,
            "stopLossPips": 32.0,
            "maxHoldBars": 8,
            "cooldownBars": 4,
            "lot": 0.01,
        },
        {
            "agentId": "qg_usdjpy_h1_ema_balanced_both_tp40_sl24_hold8_v1",
            "strategyFamily": "EMA_H1_TREND_CONTINUATION",
            "descriptionZh": "多空双向 H1 EMA 斜率候选，用来避免只看单边行情。",
            "timeframe": "H1",
            "emaSpan": 144,
            "slopeLookbackBars": 6,
            "slopeThresholdPips": 16.0,
            "direction": "both",
            "takeProfitPips": 40.0,
            "stopLossPips": 24.0,
            "maxHoldBars": 8,
            "cooldownBars": 4,
            "lot": 0.01,
        },
    ]


def _load_h1_bars(runtime_dir: Path) -> list[Bar]:
    try:
        with connect(runtime_dir) as conn:
            return load_bars(conn, "H1", limit=10000)
    except Exception:
        return []


def _score_candidate(bars: list[Bar], candidate: dict[str, Any], initial_equity_usd: float) -> dict[str, Any]:
    trades = _run_ema_candidate(bars, candidate)
    metrics = _summarize_trades(trades, bars, candidate, initial_equity_usd)
    blockers = _simulation_metric_blockers(metrics, bool(trades))
    profile = {
        "agentId": candidate["agentId"],
        "symbol": "USDJPYc",
        "marketType": "forex_cfd",
        "timeframe": candidate.get("timeframe", "H1"),
        "initialEquityUsd": round(float(initial_equity_usd), 2),
        "lot": round(float(candidate.get("lot") or 0.0), 3),
        "parameters": {key: value for key, value in candidate.items() if key not in {"descriptionZh"}},
        "metrics": metrics,
        "backtestDateRange": metrics.get("backtestDateRange"),
        "executionMode": "PAPER_LIVE_SIM",
        "qualified": not blockers,
    }
    return {
        "candidate": candidate,
        "profile": profile,
        "metrics": metrics,
        "trades": trades,
        "blockers": blockers,
        "qualified": not blockers,
    }


def _run_ema_candidate(bars: list[Bar], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    if len(bars) < 200:
        return []
    closes = [float(item.close) for item in bars]
    ema_span = int(candidate["emaSpan"])
    lookback = int(candidate["slopeLookbackBars"])
    ema = _ema_values(closes, ema_span)
    trades: list[dict[str, Any]] = []
    next_available_index = 0
    pip_size = 0.01
    for index in range(ema_span + lookback, len(bars) - 2):
        if index < next_available_index:
            continue
        if ema[index] is None or ema[index - lookback] is None:
            continue
        slope_pips = (float(ema[index]) - float(ema[index - lookback])) / pip_size
        close = closes[index]
        direction = _signal_direction(
            candidate_direction=str(candidate.get("direction") or "long"),
            slope_pips=slope_pips,
            threshold=float(candidate["slopeThresholdPips"]),
            close=close,
            ema_value=float(ema[index]),
        )
        if not direction:
            continue
        trade, exit_index = _simulate_exit(
            bars,
            entry_index=index + 1,
            direction=direction,
            take_profit_pips=float(candidate["takeProfitPips"]),
            stop_loss_pips=float(candidate["stopLossPips"]),
            max_hold_bars=int(candidate["maxHoldBars"]),
            lot=float(candidate["lot"]),
            trade_no=len(trades) + 1,
        )
        trade["signal"] = {
            "reason": "EMA_H1_SLOPE_CONTINUATION",
            "sourceBarTime": bars[index].timestamp,
            "emaSpan": ema_span,
            "slopeLookbackBars": lookback,
            "slopePips": round(slope_pips, 4),
            "closeAboveEma": close >= float(ema[index]),
        }
        trades.append(trade)
        next_available_index = exit_index + int(candidate["cooldownBars"])
    return trades


def _signal_direction(
    *,
    candidate_direction: str,
    slope_pips: float,
    threshold: float,
    close: float,
    ema_value: float,
) -> str | None:
    mode = candidate_direction.lower()
    if mode in {"long", "both"} and slope_pips >= threshold and close >= ema_value:
        return "LONG"
    if mode in {"short", "both"} and slope_pips <= -threshold and close <= ema_value:
        return "SHORT"
    return None


def _simulate_exit(
    bars: list[Bar],
    *,
    entry_index: int,
    direction: str,
    take_profit_pips: float,
    stop_loss_pips: float,
    max_hold_bars: int,
    lot: float,
    trade_no: int,
) -> tuple[dict[str, Any], int]:
    entry = bars[entry_index]
    entry_price = float(entry.open)
    signed = 1.0 if direction == "LONG" else -1.0
    pip_size = 0.01
    take_profit_price = entry_price + signed * take_profit_pips * pip_size
    stop_loss_price = entry_price - signed * stop_loss_pips * pip_size
    exit_price = float(entry.close)
    exit_bar = entry
    exit_index = entry_index
    exit_reason = "TIME_STOP"
    for index in range(entry_index, min(len(bars), entry_index + max_hold_bars + 1)):
        bar = bars[index]
        high = float(bar.high)
        low = float(bar.low)
        if direction == "LONG":
            if low <= stop_loss_price:
                exit_price = stop_loss_price
                exit_bar = bar
                exit_index = index
                exit_reason = "STOP_LOSS"
                break
            if high >= take_profit_price:
                exit_price = take_profit_price
                exit_bar = bar
                exit_index = index
                exit_reason = "TAKE_PROFIT"
                break
        else:
            if high >= stop_loss_price:
                exit_price = stop_loss_price
                exit_bar = bar
                exit_index = index
                exit_reason = "STOP_LOSS"
                break
            if low <= take_profit_price:
                exit_price = take_profit_price
                exit_bar = bar
                exit_index = index
                exit_reason = "TAKE_PROFIT"
                break
        exit_price = float(bar.close)
        exit_bar = bar
        exit_index = index
    gross_profit_pips = signed * (exit_price - entry_price) / pip_size
    cost_pips = _round_turn_cost_pips(entry)
    profit_pips = gross_profit_pips - cost_pips
    profit_usd = profit_pips * _pip_value_usd(entry_price, lot)
    return {
        "tradeId": f"FXSIM-{trade_no:04d}",
        "symbol": "USDJPYc",
        "direction": direction,
        "entryIndex": entry_index,
        "entryTime": entry.timestamp,
        "exitTime": exit_bar.timestamp,
        "entryPrice": round(entry_price, 5),
        "exitPrice": round(exit_price, 5),
        "exitReason": exit_reason,
        "grossProfitPips": round(gross_profit_pips, 4),
        "costPips": round(cost_pips, 4),
        "profitPips": round(profit_pips, 4),
        "profitUsd": round(profit_usd, 4),
        "lot": round(lot, 3),
        "spreadPoints": round(float(getattr(entry, "spread", 0.0) or 0.0), 3),
        "spreadPips": round(_spread_pips(entry), 4),
    }, exit_index


def _summarize_trades(
    trades: list[dict[str, Any]],
    bars: list[Bar],
    candidate: dict[str, Any],
    initial_equity_usd: float,
) -> dict[str, Any]:
    if not trades:
        return {
            "agentId": candidate.get("agentId"),
            "symbol": "USDJPYc",
            "pnl": 0.0,
            "pnlUsd": 0.0,
            "roiPct": 0.0,
            "sharpe": 0.0,
            "maxDrawdownPct": 0.0,
            "tradeCount": 0,
            "liquidationCount": 0,
        }
    pnls = [float(row.get("profitUsd") or 0.0) for row in trades]
    total = sum(pnls)
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    profit_factor = sum(wins) / abs(sum(losses)) if losses else 99.0
    mean = sum(pnls) / len(pnls)
    stdev = statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
    sharpe = mean / stdev * math.sqrt(len(pnls)) if stdev > 0 else 0.0
    max_drawdown_usd = _max_drawdown(pnls)
    time_segments = _time_segment_pnls(trades, len(bars))
    return {
        "agentId": candidate.get("agentId"),
        "symbol": "USDJPYc",
        "marketType": "forex_cfd",
        "pnl": round(total, 4),
        "pnlUsd": round(total, 4),
        "profitUsd": round(total, 4),
        "roiPct": round((total / max(1.0, initial_equity_usd)) * 100.0, 4),
        "sharpe": round(sharpe, 4),
        "profitFactor": round(profit_factor, 4),
        "maxDrawdownUsd": round(max_drawdown_usd, 4),
        "maxDrawdownPct": round((max_drawdown_usd / max(1.0, initial_equity_usd)) * 100.0, 4),
        "tradeCount": len(trades),
        "winRatePct": round((len(wins) / len(pnls)) * 100.0, 2),
        "liquidationCount": 0,
        "lot": round(float(candidate.get("lot") or 0.0), 3),
        "initialEquityUsd": round(float(initial_equity_usd), 2),
        "timeSegmentPnls": [round(value, 4) for value in time_segments],
        "allTimeSegmentsPositive": all(value > 0 for value in time_segments),
        "backtestDateRange": f"{bars[0].timestamp}..{bars[-1].timestamp}" if bars else "",
        "costModel": {
            "spreadFromBars": True,
            "maxSpreadPips": 8.0,
            "slippagePips": 0.2,
            "commissionPips": 0.0,
            "reasonZh": "按 MT5 H1 bar spread 估算点差，封顶 8 pips，并叠加 0.2 pips 滑点。",
        },
    }


def _simulation_metric_blockers(metrics: dict[str, Any], profile_found: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not profile_found:
        return [_blocker("FOREX_SIMULATION_PROFILE_MISSING", "缺少外币 MT5 模拟 profile。")]
    pnl = _safe_float(metrics.get("pnlUsd"))
    roi = _safe_float(metrics.get("roiPct"))
    sharpe = _safe_float(metrics.get("sharpe"))
    max_drawdown = _safe_float(metrics.get("maxDrawdownPct"))
    trade_count = _safe_int(metrics.get("tradeCount"))
    lot = _safe_float(metrics.get("lot"))
    if pnl is None or pnl <= PNL_USD_MIN:
        rows.append(_blocker("FOREX_PNL_USD_NOT_POSITIVE", "外币模拟 USD pnl 未证明为正。", pnl, f">{PNL_USD_MIN}"))
    if roi is None or roi <= ROI_MIN_PCT:
        rows.append(_blocker("FOREX_ROI_NOT_POSITIVE", "外币模拟 ROI 未证明为正。", roi, f">{ROI_MIN_PCT}"))
    if sharpe is None or sharpe < SHARPE_MIN:
        rows.append(_blocker("FOREX_SHARPE_LT_MIN", "外币模拟 Sharpe 未达准入线。", sharpe, SHARPE_MIN))
    if max_drawdown is None or max_drawdown > MAX_DRAWDOWN_MAX_PCT:
        rows.append(_blocker("FOREX_MAX_DRAWDOWN_GT_MAX", "外币模拟最大回撤超过准入线。", max_drawdown, MAX_DRAWDOWN_MAX_PCT))
    if trade_count is None or trade_count < TRADE_COUNT_MIN:
        rows.append(_blocker("FOREX_TRADE_COUNT_LT_MIN", "外币模拟交易样本不足。", trade_count, TRADE_COUNT_MIN))
    if lot is None or lot > MAX_LOT:
        rows.append(_blocker("FOREX_LOT_GT_MAX", "外币模拟手数超过低风险上限。", lot, MAX_LOT))
    if not bool(metrics.get("allTimeSegmentsPositive")):
        rows.append(_blocker("FOREX_TIME_SEGMENTS_NOT_ALL_POSITIVE", "外币模拟三段时间切片未全部盈利。", metrics.get("timeSegmentPnls")))
    return rows


def _select_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    qualified = [row for row in candidates if row.get("qualified")]
    if not qualified:
        return None
    return sorted(
        qualified,
        key=lambda row: (
            _safe_float(row.get("metrics", {}).get("sharpe")) or -999.0,
            _safe_float(row.get("metrics", {}).get("pnlUsd")) or -999.0,
            -(_safe_float(row.get("metrics", {}).get("maxDrawdownPct")) or 999.0),
        ),
        reverse=True,
    )[0]


def _candidate_result_summary(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
    return {
        "agentId": candidate.get("agentId"),
        "qualified": bool(row.get("qualified")),
        "blockerCodes": [item.get("code") for item in row.get("blockers", []) if isinstance(item, dict)],
        "metrics": {
            "pnlUsd": metrics.get("pnlUsd"),
            "roiPct": metrics.get("roiPct"),
            "sharpe": metrics.get("sharpe"),
            "maxDrawdownPct": metrics.get("maxDrawdownPct"),
            "tradeCount": metrics.get("tradeCount"),
            "timeSegmentPnls": metrics.get("timeSegmentPnls"),
        },
        "parameters": {
            key: candidate.get(key)
            for key in (
                "timeframe",
                "emaSpan",
                "slopeLookbackBars",
                "slopeThresholdPips",
                "direction",
                "takeProfitPips",
                "stopLossPips",
                "maxHoldBars",
                "cooldownBars",
                "lot",
            )
        },
    }


def _ema_values(values: list[float], span: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    alpha = 2.0 / (span + 1.0)
    ema: float | None = None
    for index, value in enumerate(values):
        ema = value if ema is None else alpha * value + (1.0 - alpha) * ema
        if index >= span - 1:
            output[index] = ema
    return output


def _spread_pips(bar: Bar) -> float:
    try:
        points = float(getattr(bar, "spread", 0.0) or 0.0)
    except Exception:
        points = 0.0
    if points <= 0:
        return 0.8
    return max(0.0, min(8.0, points * 0.1))


def _round_turn_cost_pips(bar: Bar) -> float:
    return _spread_pips(bar) + 0.2


def _pip_value_usd(price: float, lot: float) -> float:
    return lot * 100000.0 * 0.01 / max(0.0001, price)


def _max_drawdown(pnls: list[float]) -> float:
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        running += pnl
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
    return max_drawdown


def _time_segment_pnls(trades: list[dict[str, Any]], bar_count: int) -> list[float]:
    if not trades or bar_count <= 0:
        return [0.0, 0.0, 0.0]
    boundaries = [bar_count // 3, (bar_count * 2) // 3, bar_count + 1]
    start = 0
    rows: list[float] = []
    for boundary in boundaries:
        rows.append(sum(float(row.get("profitUsd") or 0.0) for row in trades if start <= int(row.get("entryIndex") or 0) < boundary))
        start = boundary
    return rows


def _data_coverage(bars: list[Bar]) -> dict[str, Any]:
    return {
        "symbol": "USDJPYc",
        "timeframe": "H1",
        "barCount": len(bars),
        "startTime": bars[0].timestamp if bars else None,
        "endTime": bars[-1].timestamp if bars else None,
        "source": "runtime/backtest/usdjpy.sqlite",
    }


def _write_trades(runtime_dir: Path, trades: list[dict[str, Any]]) -> None:
    path = simulation_trades_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "tradeId",
        "symbol",
        "direction",
        "entryTime",
        "exitTime",
        "entryPrice",
        "exitPrice",
        "exitReason",
        "grossProfitPips",
        "costPips",
        "profitPips",
        "profitUsd",
        "lot",
        "spreadPoints",
        "spreadPips",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in trades:
            writer.writerow({field: row.get(field, "") for field in fields})


def _blocker(code: str, reason_zh: str, value: Any = None, limit: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value is not None:
        row["value"] = value
    if limit is not None:
        row["limit"] = limit
    return row


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    number = _safe_float(value)
    if number is None:
        return None
    return int(number)
