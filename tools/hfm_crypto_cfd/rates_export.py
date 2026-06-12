from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contract_spec_export import _extract_rows as _extract_contract_rows
from .contract_spec_export import _normalize_contract_row
from .simulation_profile import simulation_metric_blockers
from .schema import (
    EA_RATES_EXPORT_FILE,
    HFM_CRYPTO_USD_CANONICALS,
    RATES_EXPORT_REVIEW_SCHEMA_VERSION,
    SAFETY,
    contract_spec_export_path,
    ea_rates_export_path,
    rates_autogen_profile_path,
    rates_export_review_path,
    utc_now_iso,
)

try:
    from tools.mt5_readonly_bridge import runtime_dir_candidates
except ModuleNotFoundError:  # pragma: no cover
    from mt5_readonly_bridge import runtime_dir_candidates


MIN_BTC_BARS = 180
SIM_INITIAL_EQUITY_USD = 1000.0
SIM_TARGET_NOTIONAL_USD = 1000.0


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    numeric = _safe_float(value)
    return int(numeric) if numeric is not None else 0


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def _find_latest_rates_manifest(runtime_dir: Path) -> Path | None:
    candidates = [
        ea_rates_export_path(runtime_dir),
        Path(runtime_dir) / EA_RATES_EXPORT_FILE,
        Path(runtime_dir) / "mac_import" / "mt5_files_snapshot" / "hfm_crypto" / EA_RATES_EXPORT_FILE,
        Path(runtime_dir) / "mac_import" / "mt5_files_snapshot" / EA_RATES_EXPORT_FILE,
    ]
    candidates.extend(directory / "hfm_crypto" / EA_RATES_EXPORT_FILE for directory in runtime_dir_candidates())
    candidates.extend(directory / EA_RATES_EXPORT_FILE for directory in runtime_dir_candidates())
    seen: set[str] = set()
    existing: list[tuple[float, Path]] = []
    for candidate in candidates:
        path = candidate.expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists() and path.is_file():
            try:
                existing.append((path.stat().st_mtime, path))
            except OSError:
                continue
    if not existing:
        return None
    return sorted(existing, key=lambda item: item[0], reverse=True)[0][1]


def _rate_csv_candidates(runtime_dir: Path) -> list[Path]:
    roots = [
        Path(runtime_dir) / "hfm_crypto" / "rates",
        Path(runtime_dir) / "rates",
        Path(runtime_dir) / "mac_import" / "mt5_files_snapshot" / "hfm_crypto" / "rates",
    ]
    seen: set[str] = set()
    candidates: list[Path] = []
    for root in roots:
        expanded = root.expanduser()
        if not expanded.exists() or not expanded.is_dir():
            continue
        for path in expanded.glob("*.csv"):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(path)
    candidates.sort(key=lambda path: (path.stat().st_mtime if path.exists() else 0.0), reverse=True)
    return candidates


def _series_from_csv_path(path: Path) -> dict[str, Any]:
    metadata = _series_metadata_from_csv_path(path)
    rows = _read_rate_rows(path, limit=20_000)
    return {
        **metadata,
        "copiedBars": len(rows),
        "ok": bool(rows),
        "mtimeIso": _mtime_iso(path),
    }


def _series_metadata_from_csv_path(path: Path) -> dict[str, Any]:
    stem = path.stem
    canonical = stem.split("___", 1)[0].split("__", 1)[0].upper().replace("#", "")
    broker = canonical
    if "___" in stem:
        broker = stem.split("___", 1)[1].split("__", 1)[0].upper().replace("#", "")
    timeframe = "M15"
    if "__" in stem:
        maybe_timeframe = stem.rsplit("__", 1)[-1].upper()
        if maybe_timeframe:
            timeframe = maybe_timeframe
    return {
        "brokerSymbol": broker,
        "canonicalSymbol": canonical,
        "timeframe": timeframe,
        "file": str(path),
        "csvPath": str(path),
    }


def _partial_csv_manifest(runtime_dir: Path) -> tuple[dict[str, Any], Path | None]:
    candidates = [
        path for path in _rate_csv_candidates(runtime_dir)
        if _series_metadata_from_csv_path(path).get("canonicalSymbol") in HFM_CRYPTO_USD_CANONICALS
    ]
    if not candidates:
        return {}, None
    items = [_series_from_csv_path(path) for path in candidates]
    manifest_path = ea_rates_export_path(runtime_dir)
    return {
        "schema": "quantgod.mql5.hfm_crypto_rates_export.v1",
        "source": "AUTOGEN_FROM_PARTIAL_COPYRATES_CSV",
        "sourceReason": "MT5 exporter produced rate CSV files before the manifest was written; backend reconstructed a read-only manifest from those CSVs.",
        "timeframe": "M15",
        "symbols": items,
        "symbolCount": len(items),
        "generatedAt": utc_now_iso(),
        "safety": dict(SAFETY),
    }, manifest_path


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def _resolve_rate_csv_path(runtime_dir: Path, manifest_path: Path, raw: Any) -> Path:
    text = _clean_text(raw).replace("\\", "/")
    if not text:
        return manifest_path.parent / ""
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    if text.startswith("hfm_crypto/"):
        return Path(runtime_dir) / text
    if text.startswith("rates/"):
        return Path(runtime_dir) / "hfm_crypto" / text
    return manifest_path.parent / text


def _read_rate_rows(path: Path, limit: int = 10000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                close = _safe_float(row.get("close"))
                epoch = _safe_int(row.get("epoch"))
                if close is None or close <= 0 or epoch <= 0:
                    continue
                rows.append({
                    "epoch": epoch,
                    "timestamp": _clean_text(row.get("timestamp")),
                    "open": _safe_float(row.get("open")) or close,
                    "high": _safe_float(row.get("high")) or close,
                    "low": _safe_float(row.get("low")) or close,
                    "close": close,
                    "spread": _safe_float(row.get("spread")) or 0.0,
                })
                if len(rows) >= limit:
                    break
    except Exception:
        return []
    rows.sort(key=lambda item: item["epoch"])
    return rows


def _manifest_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("symbols", "items", "series", "rates"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _missing_rates_export_review(runtime_dir: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    blocker = {
        "code": "HFM_CRYPTO_RATES_EXPORT_MISSING",
        "reasonZh": f"尚未发现 MT5 只读 CopyRates 导出的 {EA_RATES_EXPORT_FILE}。",
    }
    return {
        "ok": True,
        "schema": RATES_EXPORT_REVIEW_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "WAITING_HFM_CRYPTO_RATES_EXPORT",
        "statusZh": "等待 HFM crypto CopyRates 行情导出",
        "ratesExportFound": False,
        "ratesReadyForSimulation": False,
        "autogenProfileReady": False,
        "manifestPath": str(manifest_path or ""),
        "manifestFromPartialCsvs": False,
        "series": [],
        "blockers": [blocker],
        "nextRequiredActionZh": "运行只读 MT5 HFM crypto CopyRates exporter，生成 BTCUSD K 线后再自动生成 pnlUsd profile。",
        "safety": dict(SAFETY),
    }


def _canonical_from_row(row: dict[str, Any]) -> str:
    canonical = _clean_text(row.get("canonicalSymbol")).upper()
    if canonical:
        return canonical
    symbol = _clean_text(row.get("brokerSymbol") or row.get("symbol")).upper().replace("#", "")
    for suffix in ("R", "X", "C"):
        if symbol.endswith(suffix) and symbol[:-1].endswith("USD"):
            symbol = symbol[:-1]
    return symbol


def _contract_specs(runtime_dir: Path) -> dict[str, dict[str, Any]]:
    export_path = contract_spec_export_path(runtime_dir)
    payload = _read_json(export_path)
    rows = _extract_contract_rows(payload)
    specs: dict[str, dict[str, Any]] = {}
    for row in rows:
        normalized = _normalize_contract_row(row)
        canonical = _clean_text(normalized.get("canonicalSymbol")).upper()
        broker = _clean_text(normalized.get("brokerSymbol")).upper()
        if canonical:
            specs[canonical] = normalized
        if broker:
            specs[broker] = normalized
    return specs


def _align_lot(raw_lot: float, min_lot: float, lot_step: float, max_lot: float) -> float:
    if lot_step <= 0:
        lot_step = min_lot if min_lot > 0 else 0.01
    lot = max(min_lot, min(raw_lot, max_lot if max_lot > 0 else raw_lot))
    steps = math.floor((lot - min_lot) / lot_step)
    aligned = min_lot + max(0, steps) * lot_step
    return round(max(min_lot, min(aligned, max_lot if max_lot > 0 else aligned)), 8)


def _ema(previous: float | None, value: float, span: int) -> float:
    alpha = 2.0 / (span + 1.0)
    return value if previous is None else previous + alpha * (value - previous)


def _simulate_profile(series: dict[str, Any], specs: dict[str, dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    rows = series.get("rows") if isinstance(series.get("rows"), list) else []
    canonical = _clean_text(series.get("canonicalSymbol")).upper()
    broker = _clean_text(series.get("brokerSymbol")).upper()
    spec = specs.get(canonical) or specs.get(broker)
    blockers: list[dict[str, Any]] = []
    if canonical != "BTCUSD":
        blockers.append({"code": "HFM_BTC_RATES_MISSING", "reasonZh": "BTC/HFM crypto 目标需要 BTCUSD CopyRates 行情。", "value": canonical})
        return None, blockers
    if len(rows) < MIN_BTC_BARS:
        blockers.append({"code": "HFM_BTC_RATES_BARS_LT_MIN", "reasonZh": "BTCUSD CopyRates K 线样本不足，不能生成可审查模拟 profile。", "value": len(rows), "limit": MIN_BTC_BARS})
        return None, blockers
    if not spec:
        blockers.append({"code": "HFM_BTC_CONTRACT_SPEC_MISSING", "reasonZh": "缺少 BTCUSD HFM 合约规格，不能把价格变化换算为 USD pnl。"})
        return None, blockers

    contract_size = _safe_float(spec.get("contractSize")) or 1.0
    point = _safe_float(spec.get("tickSize")) or 0.01
    min_lot = _safe_float(spec.get("minLot")) or 0.01
    lot_step = _safe_float(spec.get("lotStep")) or min_lot
    max_lot = _safe_float(spec.get("maxLot")) or min_lot
    first_price = float(rows[0]["close"])
    lot = _align_lot(SIM_TARGET_NOTIONAL_USD / max(first_price * contract_size, 1e-9), min_lot, lot_step, max_lot)

    def close_pnl(position: int, entry_price: float, price: float, spread_points: float) -> float:
        spread_price = max(spread_points, 0.0) * point
        gross = (price - entry_price) * position * contract_size * lot
        cost = spread_price * contract_size * lot
        return gross - cost

    def summarize_trades(trade_pnls: list[float], strategy_id: str) -> dict[str, Any]:
        pnl_usd = round(sum(trade_pnls), 4)
        trade_count = len(trade_pnls)
        equity = SIM_INITIAL_EQUITY_USD
        peak = equity
        max_drawdown_pct = 0.0
        for item in trade_pnls:
            equity += item
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100.0)
        if trade_count >= 2:
            mean = sum(trade_pnls) / trade_count
            variance = sum((item - mean) ** 2 for item in trade_pnls) / (trade_count - 1)
            stdev = math.sqrt(variance)
            sharpe = (mean / stdev) * math.sqrt(trade_count) if stdev > 0 else (9.99 if mean > 0 else 0.0)
        else:
            sharpe = 0.0
        return {
            "agentId": strategy_id,
            "symbol": "BTCUSD",
            "pnlUsd": pnl_usd,
            "pnl": pnl_usd,
            "roiPct": round((pnl_usd / SIM_INITIAL_EQUITY_USD) * 100.0, 4),
            "sharpe": round(sharpe, 4),
            "maxDrawdownPct": round(max_drawdown_pct, 4),
            "tradeCount": trade_count,
            "liquidationCount": 0,
        }

    def run_ema_cross(strategy_id: str, fast_span: int, slow_span: int) -> dict[str, Any]:
        fast: float | None = None
        slow: float | None = None
        position = 0
        entry_price = 0.0
        trade_pnls: list[float] = []
        warmup = max(48, slow_span)
        for index, row in enumerate(rows):
            price = float(row["close"])
            fast = _ema(fast, price, fast_span)
            slow = _ema(slow, price, slow_span)
            if index < warmup:
                continue
            desired = 1 if fast > slow else -1 if fast < slow else 0
            if desired != position:
                if position != 0:
                    trade_pnls.append(close_pnl(position, entry_price, price, float(row.get("spread") or 0.0)))
                position = desired
                entry_price = price if desired != 0 else 0.0
        if position != 0:
            trade_pnls.append(close_pnl(position, entry_price, float(rows[-1]["close"]), float(rows[-1].get("spread") or 0.0)))
        return {
            "strategyId": strategy_id,
            "strategyName": f"BTCUSD EMA {fast_span}/{slow_span} crossover shadow simulation",
            "strategyFamily": "ema_crossover",
            "parameters": {"fastSpan": fast_span, "slowSpan": slow_span},
            "tradePnls": trade_pnls,
            "metrics": summarize_trades(trade_pnls, strategy_id),
        }

    def run_regime_slope(
        *,
        strategy_id: str,
        strategy_name: str,
        bias: str,
        ema_span: int,
        slope_lookback: int,
        slope_threshold: float,
        take_profit_move: float,
        stop_loss_move: float,
        max_hold_bars: int,
        cooldown_bars: int,
    ) -> dict[str, Any]:
        ema_values: list[float] = []
        ema_value: float | None = None
        for row in rows:
            ema_value = _ema(ema_value, float(row["close"]), ema_span)
            ema_values.append(ema_value)
        position = 0
        entry_price = 0.0
        entry_index = 0
        last_change_index = -10**9
        trade_pnls: list[float] = []
        warmup = max(ema_span, slope_lookback)
        for index, row in enumerate(rows):
            if index < warmup:
                continue
            price = float(row["close"])
            slope = ema_values[index] - ema_values[index - slope_lookback]
            regime = 1 if slope > slope_threshold else -1 if slope < -slope_threshold else 0
            if bias == "short":
                regime = -1 if regime < 0 else 0
            elif bias == "long":
                regime = 1 if regime > 0 else 0

            desired = position
            if position != 0:
                move = (price - entry_price) * position
                if (
                    move >= take_profit_move
                    or move <= -stop_loss_move
                    or index - entry_index >= max_hold_bars
                    or regime != position
                ):
                    desired = 0
            elif regime != 0 and index - last_change_index >= cooldown_bars:
                desired = regime

            if desired != position:
                if position != 0:
                    trade_pnls.append(close_pnl(position, entry_price, price, float(row.get("spread") or 0.0)))
                position = desired
                entry_price = price if desired != 0 else 0.0
                entry_index = index
                last_change_index = index
        if position != 0:
            trade_pnls.append(close_pnl(position, entry_price, float(rows[-1]["close"]), float(rows[-1].get("spread") or 0.0)))
        return {
            "strategyId": strategy_id,
            "strategyName": strategy_name,
            "strategyFamily": "ema_slope_regime",
            "parameters": {
                "bias": bias,
                "emaSpan": ema_span,
                "slopeLookbackBars": slope_lookback,
                "slopeThresholdPrice": slope_threshold,
                "takeProfitPriceMove": take_profit_move,
                "stopLossPriceMove": stop_loss_move,
                "maxHoldBars": max_hold_bars,
                "cooldownBars": cooldown_bars,
            },
            "tradePnls": trade_pnls,
            "metrics": summarize_trades(trade_pnls, strategy_id),
        }

    strategy_candidates = [
        run_ema_cross("hfm_crypto_btc_copyrates_ema_shadow_v1", 12, 36),
        run_regime_slope(
            strategy_id="hfm_crypto_btc_regime_stability_shadow_v1",
            strategy_name="BTCUSD EMA-slope short regime stability shadow simulation",
            bias="short",
            ema_span=48,
            slope_lookback=144,
            slope_threshold=200.0,
            take_profit_move=1500.0,
            stop_loss_move=500.0,
            max_hold_bars=24,
            cooldown_bars=8,
        ),
        run_regime_slope(
            strategy_id="hfm_crypto_btc_regime_bidirectional_shadow_v1",
            strategy_name="BTCUSD EMA-slope bidirectional regime shadow simulation",
            bias="both",
            ema_span=48,
            slope_lookback=144,
            slope_threshold=50.0,
            take_profit_move=600.0,
            stop_loss_move=1200.0,
            max_hold_bars=72,
            cooldown_bars=8,
        ),
        run_regime_slope(
            strategy_id="hfm_crypto_btc_regime_short_yield_shadow_v1",
            strategy_name="BTCUSD EMA-slope short yield shadow simulation",
            bias="short",
            ema_span=48,
            slope_lookback=144,
            slope_threshold=300.0,
            take_profit_move=600.0,
            stop_loss_move=1200.0,
            max_hold_bars=96,
            cooldown_bars=8,
        ),
        run_regime_slope(
            strategy_id="hfm_crypto_btc_regime_sample_rich_shadow_v1",
            strategy_name="BTCUSD EMA-slope sample-rich regime shadow simulation",
            bias="both",
            ema_span=48,
            slope_lookback=144,
            slope_threshold=150.0,
            take_profit_move=1500.0,
            stop_loss_move=800.0,
            max_hold_bars=24,
            cooldown_bars=8,
        ),
    ]
    for candidate in strategy_candidates:
        candidate["blockers"] = simulation_metric_blockers(candidate["metrics"], True)
    qualified_candidates = [candidate for candidate in strategy_candidates if not candidate["blockers"]]
    if qualified_candidates:
        selected = sorted(
            qualified_candidates,
            key=lambda item: (
                _safe_float(item["metrics"].get("sharpe")) or -999.0,
                _safe_float(item["metrics"].get("pnlUsd")) or -999999.0,
                -(_safe_float(item["metrics"].get("maxDrawdownPct")) or 999.0),
                _safe_int(item["metrics"].get("tradeCount")),
            ),
            reverse=True,
        )[0]
    else:
        selected = sorted(
            strategy_candidates,
            key=lambda item: (
                _safe_float(item["metrics"].get("pnlUsd")) or -999999.0,
                _safe_float(item["metrics"].get("sharpe")) or -999.0,
                -(_safe_float(item["metrics"].get("maxDrawdownPct")) or 999.0),
            ),
            reverse=True,
        )[0]
    metrics = selected["metrics"]
    trade_pnls = selected["tradePnls"]
    profile = {
        "schema": "quantgod.hfm_crypto_cfd.autogen_simulation_profile.v1",
        "source": "HFM_MT5_COPYRATES_SHADOW_SIM",
        "agentId": selected["strategyId"],
        "strategyName": selected["strategyName"],
        "symbol": "BTCUSD",
        "brokerSymbol": broker or canonical,
        "pnlUsd": metrics["pnlUsd"],
        "roiPct": metrics["roiPct"],
        "sharpe": metrics["sharpe"],
        "maxDrawdownPct": metrics["maxDrawdownPct"],
        "tradeCount": metrics["tradeCount"],
        "liquidationCount": metrics["liquidationCount"],
        "backtestDateRange": f"{rows[0].get('timestamp') or rows[0]['epoch']}..{rows[-1].get('timestamp') or rows[-1]['epoch']}",
        "metrics": dict(metrics),
        "simulation": {
            "initialEquityUsd": SIM_INITIAL_EQUITY_USD,
            "targetNotionalUsd": SIM_TARGET_NOTIONAL_USD,
            "contractSize": contract_size,
            "lot": lot,
            "barCount": len(rows),
            "selectedStrategy": {
                "strategyId": selected["strategyId"],
                "strategyName": selected["strategyName"],
                "strategyFamily": selected["strategyFamily"],
                "parameters": selected["parameters"],
            },
            "selectionPolicy": "qualified_highest_sharpe_then_pnl_shadow_only",
            "candidateCount": len(strategy_candidates),
            "candidateResults": [
                {
                    "strategyId": candidate["strategyId"],
                    "strategyName": candidate["strategyName"],
                    "strategyFamily": candidate["strategyFamily"],
                    "parameters": candidate["parameters"],
                    "metrics": candidate["metrics"],
                    "qualified": not candidate["blockers"],
                    "blockerCodes": [item.get("code") for item in candidate["blockers"]],
                }
                for candidate in sorted(
                    strategy_candidates,
                    key=lambda item: (
                        _safe_float(item["metrics"].get("sharpe")) or -999.0,
                        _safe_float(item["metrics"].get("pnlUsd")) or -999999.0,
                    ),
                    reverse=True,
                )
            ],
            "tradePnlPreview": [round(item, 4) for item in trade_pnls[:20]],
            "readOnly": True,
        },
        "safety": dict(SAFETY),
    }
    metric_blockers = simulation_metric_blockers(profile["metrics"], True)
    return profile, metric_blockers


def build_hfm_crypto_rates_export_review(
    runtime_dir: Path,
    *,
    rates_manifest_json: str = "",
    write: bool = False,
    write_profile: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    manifest_path = Path(rates_manifest_json).expanduser() if rates_manifest_json else _find_latest_rates_manifest(runtime_dir)
    manifest_from_partial_csvs = False
    blockers: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    local_partial_manifest: dict[str, Any] = {}
    local_partial_path: Path | None = None
    if not rates_manifest_json:
        local_partial_manifest, local_partial_path = _partial_csv_manifest(runtime_dir)
        if local_partial_manifest and (not manifest_path or not _path_is_under(manifest_path, runtime_dir)):
            manifest_path = local_partial_path
            manifest = local_partial_manifest
            manifest_from_partial_csvs = True
            if write and manifest_path:
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if manifest_path and manifest_path.exists():
        if not manifest:
            manifest = _read_json(manifest_path)
    else:
        manifest, partial_manifest_path = (local_partial_manifest, local_partial_path) if local_partial_manifest else _partial_csv_manifest(runtime_dir)
        if manifest:
            manifest_from_partial_csvs = True
            manifest_path = partial_manifest_path
            if write and manifest_path:
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            manifest_path = manifest_path or partial_manifest_path

    if not manifest_path or not manifest:
        payload = _missing_rates_export_review(runtime_dir, manifest_path)
        if blockers:
            payload["blockers"] = blockers
        if write:
            out = rates_export_review_path(runtime_dir)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    items = _manifest_items(manifest)
    series: list[dict[str, Any]] = []
    for item in items:
        canonical = _canonical_from_row(item)
        if canonical not in HFM_CRYPTO_USD_CANONICALS:
            continue
        csv_path = _resolve_rate_csv_path(runtime_dir, manifest_path, item.get("file") or item.get("csvPath"))
        rows = _read_rate_rows(csv_path)
        series.append({
            "canonicalSymbol": canonical,
            "brokerSymbol": _clean_text(item.get("brokerSymbol") or item.get("symbol")),
            "timeframe": _clean_text(item.get("timeframe") or manifest.get("timeframe") or "M15"),
            "csvPath": str(csv_path),
            "csvExists": csv_path.exists(),
            "csvMtimeIso": _mtime_iso(csv_path) if csv_path.exists() else "",
            "barCount": len(rows),
            "manifestCopiedBars": _safe_int(item.get("copiedBars") or item.get("bars")),
            "manifestOk": bool(item.get("ok", False)),
            "oldest": rows[0].get("timestamp", "") if rows else "",
            "latest": rows[-1].get("timestamp", "") if rows else "",
            "rows": rows,
        })
    series.sort(key=lambda row: (row["canonicalSymbol"] != "BTCUSD", -int(row["barCount"])))
    btc_series = next((row for row in series if row.get("canonicalSymbol") == "BTCUSD" and row.get("barCount", 0) > 0), None)
    specs = _contract_specs(runtime_dir)
    profile, profile_blockers = _simulate_profile(btc_series or {}, specs) if btc_series else (None, [{
        "code": "HFM_BTC_RATES_MISSING",
        "reasonZh": "没有可读取的 BTCUSD CopyRates CSV，不能证明 BTC/crypto 线模拟收益。",
    }])
    blockers.extend(profile_blockers)
    rates_ready = bool(btc_series and btc_series.get("barCount", 0) >= MIN_BTC_BARS)
    profile_ready = bool(profile and not profile_blockers)
    profile_path = rates_autogen_profile_path(runtime_dir)
    profile_written = False
    if write_profile and profile:
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        profile_written = True

    public_series = [{key: value for key, value in row.items() if key != "rows"} for row in series]
    payload = {
        "ok": True,
        "schema": RATES_EXPORT_REVIEW_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": "HFM_CRYPTO_RATES_PROFILE_READY" if profile_ready else "WAITING_HFM_CRYPTO_RATES_EXPORT",
        "statusZh": "HFM crypto CopyRates profile 已生成" if profile_ready else "等待可生成 profile 的 HFM crypto CopyRates 行情",
        "ratesExportFound": True,
        "ratesReadyForSimulation": rates_ready,
        "autogenProfileReady": profile_ready,
        "manifestPath": str(manifest_path),
        "manifestSchema": manifest.get("schema", ""),
        "manifestSource": manifest.get("source", ""),
        "manifestFromPartialCsvs": manifest_from_partial_csvs,
        "manifestMtimeIso": _mtime_iso(manifest_path),
        "seriesCount": len(series),
        "btcBarCount": int(btc_series.get("barCount", 0)) if btc_series else 0,
        "selectedSeries": {key: value for key, value in (btc_series or {}).items() if key != "rows"},
        "series": public_series,
        "profileCandidate": profile or {},
        "autogenProfilePath": str(profile_path),
        "autogenProfileWritten": profile_written,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "已生成 HFM crypto pnlUsd profile；刷新 simulation-profile 和 profit-target tracker。"
            if profile_ready
            else "继续运行只读 CopyRates exporter，确保 BTCUSD K 线、合约规格和交易样本足够。"
        ),
        "safety": dict(SAFETY),
    }
    if write:
        out = rates_export_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_rates_export_review(runtime_dir: Path) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    path = rates_export_review_path(runtime_dir)
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
        except Exception:
            pass
    return _missing_rates_export_review(runtime_dir)
