from __future__ import annotations

import asyncio
import csv
import json
import math
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .agents.base_agent import utc_now_iso
from .config import AIAnalysisConfig, load_config

TIMEFRAME_BARS = {
    "M15": 200,
    "H1": 200,
    "H4": 100,
    "D1": 60,
}

TIMEFRAME_SECONDS = {
    "M15": 15 * 60,
    "H1": 60 * 60,
    "H4": 4 * 60 * 60,
    "D1": 24 * 60 * 60,
}

READ_ONLY_SAFETY = {
    "readOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "credentialStorageAllowed": False,
    "livePresetMutationAllowed": False,
    "mutatesMt5": False,
    "symbolSelectAllowed": False,
}


class MarketDataCollector:
    """Collect read-only market/runtime context for the 3-Agent pipeline."""

    def __init__(self, config: AIAnalysisConfig | None = None, runtime_dir: str | Path | None = None) -> None:
        base_config = config or load_config()
        if runtime_dir is not None:
            base_config = replace(base_config, runtime_dir=Path(runtime_dir).expanduser())
        self.config = base_config

    async def collect(self, symbol: str, timeframes: list[str] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self.collect_sync, symbol, timeframes)

    def collect_sync(self, symbol: str, timeframes: list[str] | None = None) -> dict[str, Any]:
        clean_symbol = (symbol or "").strip()
        if not clean_symbol:
            raise ValueError("symbol is required")

        requested = _normalize_timeframes(timeframes)
        mt5_payload = self._collect_from_mt5(clean_symbol, requested)
        runtime_payload = self._collect_from_runtime_files(clean_symbol, requested)
        source = _choose_snapshot_source(mt5_payload, runtime_payload)

        snapshot: dict[str, Any] = {
            "mode": "QUANTGOD_MARKET_SNAPSHOT_V1",
            "symbol": clean_symbol,
            "generatedAtIso": utc_now_iso(),
            "source": source,
            "safety": READ_ONLY_SAFETY,
            "timeframes": requested,
            "current_price": mt5_payload.get("current_price") or runtime_payload.get("current_price") or _mock_quote(clean_symbol),
            "symbol_info": mt5_payload.get("symbol_info") or runtime_payload.get("symbol_info") or {"name": clean_symbol},
            "open_positions": mt5_payload.get("open_positions") or runtime_payload.get("open_positions") or [],
            "kill_switch_status": runtime_payload.get("kill_switch_status", {}),
            "news_filter_status": runtime_payload.get("news_filter_status", {}),
            "shadow_signal_recent": runtime_payload.get("shadow_signal_recent", []),
            "consecutive_loss_state": runtime_payload.get("consecutive_loss_state", {}),
            "daily_pnl": runtime_payload.get("daily_pnl", 0.0),
            "runtimeFresh": bool(runtime_payload.get("runtimeFresh", False)),
            "runtimeAgeSeconds": runtime_payload.get("runtimeAgeSeconds"),
            "runtimePath": runtime_payload.get("runtimePath", ""),
            "runtime": runtime_payload.get("runtime", {}),
            "fallbackReason": runtime_payload.get("fallbackReason") or mt5_payload.get("source", ""),
        }

        for timeframe in requested:
            key = f"kline_{timeframe.lower()}"
            snapshot[key] = mt5_payload.get(key) or runtime_payload.get(key) or _mock_kline(
                clean_symbol, timeframe, TIMEFRAME_BARS[timeframe]
            )

        snapshot["fallback"] = bool(mt5_payload.get("fallback", True) and runtime_payload.get("fallback", True))
        return snapshot

    def _collect_from_mt5(self, symbol: str, timeframes: list[str]) -> dict[str, Any]:
        if self.config.mock_mode:
            return {"fallback": True, "source": "mock_mode"}

        try:
            import MetaTrader5 as mt5  # type: ignore[import-not-found]
        except Exception:
            return {"fallback": True, "source": "mt5_python_unavailable"}

        initialized = False
        try:
            terminal_path = os.getenv("QG_MT5_TERMINAL_PATH", "").strip()
            initialized = bool(mt5.initialize(path=terminal_path) if terminal_path else mt5.initialize())
            if not initialized:
                return {"fallback": True, "source": "mt5_initialize_failed", "lastError": _safe_last_error(mt5)}

            payload: dict[str, Any] = {"fallback": False, "source": "live_mt5_readonly", "lastError": _safe_last_error(mt5)}
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                payload["current_price"] = {
                    "symbol": symbol,
                    "bid": _attr(tick, "bid"),
                    "ask": _attr(tick, "ask"),
                    "last": _attr(tick, "last"),
                    "volume": _attr(tick, "volume"),
                    "timeIso": _timestamp_iso(_attr(tick, "time")),
                }
                bid = payload["current_price"].get("bid")
                ask = payload["current_price"].get("ask")
                if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
                    payload["current_price"]["spread"] = round(ask - bid, 8)

            info = mt5.symbol_info(symbol)
            if info is not None:
                payload["symbol_info"] = _symbol_info_dict(info)

            positions = mt5.positions_get(symbol=symbol)
            if positions is not None:
                payload["open_positions"] = [_position_dict(item) for item in positions]

            for timeframe in timeframes:
                mt5_tf = _mt5_timeframe(mt5, timeframe)
                if mt5_tf is None:
                    continue
                rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, TIMEFRAME_BARS[timeframe])
                if rates is None:
                    continue
                payload[f"kline_{timeframe.lower()}"] = [_rate_dict(row) for row in list(rates)]
            return payload
        except Exception as error:
            return {"fallback": True, "source": "mt5_collect_error", "error": str(error)}
        finally:
            if initialized:
                try:
                    mt5.shutdown()
                except Exception:
                    pass

    def _collect_from_runtime_files(self, symbol: str, timeframes: list[str]) -> dict[str, Any]:
        runtime_dir = self.config.safe_runtime_dir
        bridge_payload = _read_runtime_bridge_payload(runtime_dir, symbol, timeframes)
        if not bridge_payload.get("fallback", True):
            return bridge_payload

        dashboard_path = runtime_dir / "QuantGod_Dashboard.json"
        payload: dict[str, Any] = dict(bridge_payload) if isinstance(bridge_payload, dict) else {"fallback": True, "source": "runtime_files"}
        payload.setdefault("fallback", True)
        payload.setdefault("source", "runtime_files")

        dashboard = _read_json(dashboard_path)
        if isinstance(dashboard, dict):
            extracted = _extract_dashboard_state(dashboard, symbol)
            payload.update(extracted)
            if extracted:
                payload["fallback"] = False
                payload["source"] = payload.get("source") or "dashboard_runtime"

        shadow_rows = _read_recent_shadow_rows(runtime_dir, symbol, hours=24)
        if shadow_rows:
            payload["shadow_signal_recent"] = shadow_rows
        return payload


def _choose_snapshot_source(mt5_payload: dict[str, Any], runtime_payload: dict[str, Any]) -> str:
    if not mt5_payload.get("fallback", True):
        return str(mt5_payload.get("source") or "live_mt5_readonly")
    if not runtime_payload.get("fallback", True):
        return str(runtime_payload.get("source") or "runtime_files")
    return str(mt5_payload.get("source") or runtime_payload.get("source") or "mock_fallback")


def _read_runtime_bridge_payload(runtime_dir: Path, symbol: str, timeframes: list[str]) -> dict[str, Any]:
    try:
        from mt5_runtime_bridge.reader import RuntimeBridgeReader

        max_age = _env_int("QG_MT5_RUNTIME_MAX_AGE_SECONDS", 1800)
        allow_stale = _env_bool("QG_MT5_RUNTIME_ALLOW_STALE", False)
        return RuntimeBridgeReader(runtime_dir, max_age_seconds=max_age, allow_stale=allow_stale).collect_for_ai_snapshot(
            symbol, timeframes
        )
    except Exception as error:
        return {
            "fallback": True,
            "source": "runtime_bridge_error",
            "fallbackReason": str(error),
            "runtimeFresh": False,
            "runtimeAgeSeconds": None,
            "runtimePath": "",
        }


def _normalize_timeframes(timeframes: list[str] | None) -> list[str]:
    if not timeframes:
        return ["M15", "H1", "H4", "D1"]
    out = []
    for item in timeframes:
        tf = str(item).strip().upper()
        if tf in TIMEFRAME_BARS and tf not in out:
            out.append(tf)
    return out or ["M15", "H1", "H4", "D1"]


def _read_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _extract_dashboard_state(dashboard: dict[str, Any], symbol: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    payload["kill_switch_status"] = dashboard.get("killSwitch") or dashboard.get("kill_switch") or dashboard.get("risk") or {}
    payload["news_filter_status"] = dashboard.get("news") or dashboard.get("newsFilter") or {}
    payload["consecutive_loss_state"] = dashboard.get("consecutiveLoss") or dashboard.get("consecutive_loss") or {}
    payload["daily_pnl"] = dashboard.get("dailyPnl") or dashboard.get("daily_pnl") or 0.0

    symbols = dashboard.get("symbols")
    if isinstance(symbols, list):
        for item in symbols:
            if not isinstance(item, dict):
                continue
            names = {str(item.get(key, "")).upper() for key in ("symbol", "brokerSymbol", "canonicalSymbol", "name")}
            if symbol.upper() in names:
                payload.setdefault("symbol_info", item.get("symbolInfo") or item)
                if "bid" in item or "ask" in item:
                    payload["current_price"] = {
                        "symbol": symbol,
                        "bid": item.get("bid"),
                        "ask": item.get("ask"),
                        "last": item.get("last") or item.get("price"),
                        "spread": item.get("spread") or item.get("spreadPoints"),
                    }
                if isinstance(item.get("positions"), list):
                    payload["open_positions"] = item["positions"]
                break

    if "open_positions" not in payload:
        positions = dashboard.get("positions") or dashboard.get("openPositions") or []
        if isinstance(positions, list):
            payload["open_positions"] = [
                row for row in positions if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol.upper()
            ]
    return payload


def _read_recent_shadow_rows(runtime_dir: Path, symbol: str, hours: int = 24) -> list[dict[str, Any]]:
    names = ["QuantGod_ShadowSignalLedger.csv", "QuantGod_ShadowCandidateLedger.csv"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows: list[dict[str, Any]] = []
    for name in names:
        path = runtime_dir / name
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    row_symbol = str(row.get("Symbol") or row.get("symbol") or row.get("BrokerSymbol") or "")
                    if row_symbol and row_symbol.upper() != symbol.upper():
                        continue
                    event_time = _parse_any_time(row.get("TimeIso") or row.get("EventTimeIso") or row.get("Timestamp") or row.get("Time"))
                    if event_time and event_time < cutoff:
                        continue
                    row["_sourceFile"] = name
                    rows.append(dict(row))
        except Exception:
            continue
    return rows[-50:]


def _parse_any_time(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for normalized in (text.replace("Z", "+00:00"), text.replace(".", "-", 2)):
        try:
            dt = datetime.fromisoformat(normalized)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _mock_quote(symbol: str) -> dict[str, Any]:
    base = _mock_base_price(symbol)
    return {
        "symbol": symbol,
        "bid": round(base, 5),
        "ask": round(base + 0.00017, 5),
        "last": round(base + 0.00008, 5),
        "spread": 0.00017,
        "timeIso": utc_now_iso(),
        "source": "mock_fallback",
    }


def _mock_kline(symbol: str, timeframe: str, bars: int) -> list[dict[str, Any]]:
    base = _mock_base_price(symbol)
    seconds = TIMEFRAME_SECONDS[timeframe]
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(seconds=seconds * bars)
    rows: list[dict[str, Any]] = []
    for idx in range(bars):
        angle = idx / 10.0
        drift = (idx - bars / 2) * 0.000005
        center = base + math.sin(angle) * 0.0008 + drift
        open_price = center - 0.00012
        close = center + math.cos(angle / 2) * 0.00012
        high = max(open_price, close) + 0.00022
        low = min(open_price, close) - 0.00022
        ts = start + timedelta(seconds=seconds * idx)
        rows.append(
            {
                "timestamp": int(ts.timestamp() * 1000),
                "timeIso": ts.isoformat().replace("+00:00", "Z"),
                "open": round(open_price, 5),
                "high": round(high, 5),
                "low": round(low, 5),
                "close": round(close, 5),
                "volume": 1000 + idx,
                "source": "mock_fallback",
            }
        )
    return rows


def _mock_base_price(symbol: str) -> float:
    upper = symbol.upper()
    if "JPY" in upper:
        return 156.25
    if "XAU" in upper or "GOLD" in upper:
        return 2310.0
    return 1.10 + (sum(ord(ch) for ch in upper) % 200) / 100000.0


def _attr(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        value = item.get(name, default)
    else:
        value = getattr(item, name, default)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return default
    return value


def _safe_last_error(mt5: Any) -> Any:
    try:
        return mt5.last_error()
    except Exception:
        return None


def _timestamp_iso(timestamp: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(timestamp), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None


def _symbol_info_dict(info: Any) -> dict[str, Any]:
    fields = [
        "name",
        "description",
        "path",
        "visible",
        "select",
        "currency_base",
        "currency_profit",
        "digits",
        "point",
        "spread",
        "trade_mode",
        "volume_min",
        "volume_max",
        "volume_step",
    ]
    return {field: _attr(info, field) for field in fields}


def _position_dict(item: Any) -> dict[str, Any]:
    return {
        "ticket": _attr(item, "ticket"),
        "identifier": _attr(item, "identifier"),
        "symbol": _attr(item, "symbol"),
        "type": _attr(item, "type"),
        "volume": _attr(item, "volume"),
        "priceOpen": _attr(item, "price_open"),
        "priceCurrent": _attr(item, "price_current"),
        "sl": _attr(item, "sl"),
        "tp": _attr(item, "tp"),
        "profit": _attr(item, "profit"),
        "magic": _attr(item, "magic"),
        "comment": _attr(item, "comment"),
        "timeIso": _timestamp_iso(_attr(item, "time")),
    }


def _mt5_timeframe(mt5: Any, timeframe: str) -> Any:
    return {
        "M15": getattr(mt5, "TIMEFRAME_M15", None),
        "H1": getattr(mt5, "TIMEFRAME_H1", None),
        "H4": getattr(mt5, "TIMEFRAME_H4", None),
        "D1": getattr(mt5, "TIMEFRAME_D1", None),
    }.get(timeframe)


def _rate_dict(row: Any) -> dict[str, Any]:
    get = row.get if isinstance(row, dict) else lambda key, default=None: _attr(row, key, default)
    timestamp = get("time")
    return {
        "timestamp": int(float(timestamp) * 1000) if timestamp is not None else None,
        "timeIso": _timestamp_iso(timestamp),
        "open": float(get("open", 0.0)),
        "high": float(get("high", 0.0)),
        "low": float(get("low", 0.0)),
        "close": float(get("close", 0.0)),
        "volume": int(get("tick_volume", get("real_volume", 0)) or 0),
    }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default
