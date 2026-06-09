from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .schema import assert_safe_payload, runtime_dir, safety_payload

try:  # pragma: no cover - import fallback is for direct script contexts.
    from tools.mt5_readonly_bridge import runtime_dir_candidates as mt5_runtime_dir_candidates
except Exception:  # pragma: no cover
    try:
        from mt5_readonly_bridge import runtime_dir_candidates as mt5_runtime_dir_candidates
    except Exception:
        mt5_runtime_dir_candidates = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def age_seconds(value: Any) -> int | None:
    dt = parse_time(value)
    if not dt:
        return None
    return max(0, int((utc_now() - dt).total_seconds()))


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            assert_safe_payload(payload)
            return payload
    except Exception:
        return None
    return None


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "y", "on", "是"}


def _repo_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime"


def _include_global_mt5_candidates(root: Path) -> bool:
    if _truthy_env("QG_FASTLANE_INCLUDE_GLOBAL_MT5") or _truthy_env("QG_USDJPY_INCLUDE_GLOBAL_MT5"):
        return True
    try:
        return root.resolve() == _repo_runtime_dir().resolve()
    except Exception:
        return False


def _candidate_roots(root: Path) -> list[Path]:
    candidates = [root]
    if _include_global_mt5_candidates(root) and mt5_runtime_dir_candidates:
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


def _latest_json_file(candidates: list[Path], filename: str) -> tuple[dict[str, Any] | None, Path | None]:
    found: list[tuple[float, Path, dict[str, Any]]] = []
    for directory in candidates:
        path = directory / filename
        payload = read_json(path)
        if not payload:
            continue
        try:
            found.append((path.stat().st_mtime, path, payload))
        except Exception:
            continue
    if not found:
        return None, None
    _, path, payload = sorted(found, key=lambda item: item[0], reverse=True)[0]
    return payload, path


def _payload_is_newer(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if not current:
        return True
    candidate_dt = parse_time(candidate.get("generatedAt") or candidate.get("timeIso") or candidate.get("timestamp"))
    current_dt = parse_time(current.get("generatedAt") or current.get("timeIso") or current.get("timestamp"))
    if candidate_dt and current_dt:
        return candidate_dt >= current_dt
    return bool(candidate_dt and not current_dt)


def _file_mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except Exception:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _read_kv_text(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        rows: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            rows[key.strip()] = value.strip()
        return rows
    except Exception:
        return {}


def _symbol_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.endswith("C") and len(text) > 6:
        text = text[:-1]
    return text


def _symbol_matches(left: Any, right: Any) -> bool:
    return _symbol_key(left) == _symbol_key(right)


def _dashboard_symbol(dashboard: dict[str, Any] | None) -> str | None:
    if not dashboard:
        return None
    market = dashboard.get("market") if isinstance(dashboard.get("market"), dict) else {}
    for value in (market.get("symbol"), dashboard.get("symbol"), dashboard.get("watchlist")):
        text = str(value or "").strip()
        if text:
            return text.split(",")[0].strip()
    return None


def _requested_or_dashboard_symbols(symbols: list[str] | None, dashboard: dict[str, Any] | None) -> list[str]:
    requested = [str(item).strip() for item in symbols or [] if str(item).strip()]
    if requested:
        return requested
    symbol = _dashboard_symbol(dashboard)
    return [symbol] if symbol else []


def _timer_heartbeat(root: Path) -> dict[str, Any] | None:
    path = root / "QuantGod_MT5_TimerHeartbeat.txt"
    fields = _read_kv_text(path)
    generated_at = _file_mtime_iso(path)
    if not fields and not generated_at:
        return None
    payload = {
        "schema": "quantgod.mt5.fast_lane.heartbeat.timer_fallback.v1",
        "generatedAt": generated_at,
        "source": "QuantGod_MT5_TimerHeartbeat.txt",
        "fallbackSource": "timer_heartbeat",
        "timerHeartbeatFallback": True,
        "localTime": fields.get("localTime", ""),
        "serverTime": fields.get("serverTime", ""),
        "refreshIntervalSeconds": _safe_int(fields.get("refreshIntervalSeconds"), 0),
        "safety": safety_payload(),
    }
    assert_safe_payload(payload)
    return payload


def _dashboard_heartbeat(root: Path, dashboard: dict[str, Any] | None) -> dict[str, Any] | None:
    path = root / "QuantGod_Dashboard.json"
    generated_at = _file_mtime_iso(path)
    if not dashboard or not generated_at:
        return None
    runtime = dashboard.get("runtime") if isinstance(dashboard.get("runtime"), dict) else {}
    payload = {
        "schema": "quantgod.mt5.fast_lane.heartbeat.dashboard_fallback.v1",
        "generatedAt": generated_at,
        "source": "QuantGod_Dashboard.json",
        "fallbackSource": "dashboard",
        "dashboardFallback": True,
        "dashboardTimestamp": dashboard.get("timestamp"),
        "tradeStatus": runtime.get("tradeStatus"),
        "connected": runtime.get("connected"),
        "terminalConnected": runtime.get("terminalConnected"),
        "localTime": runtime.get("localTime"),
        "serverTime": runtime.get("serverTime"),
        "gmtTime": runtime.get("gmtTime"),
        "safety": safety_payload(),
    }
    assert_safe_payload(payload)
    return payload


def _fallback_tick_rows(root: Path, dashboard: dict[str, Any] | None, symbol: str) -> list[dict[str, Any]]:
    if not dashboard:
        return []
    market = dashboard.get("market") if isinstance(dashboard.get("market"), dict) else {}
    source_symbol = market.get("symbol") or _dashboard_symbol(dashboard) or symbol
    if source_symbol and not _symbol_matches(source_symbol, symbol):
        return []
    generated_at = _file_mtime_iso(root / "QuantGod_Dashboard.json")
    generated_dt = parse_time(generated_at)
    if not generated_dt:
        return []
    runtime = dashboard.get("runtime") if isinstance(dashboard.get("runtime"), dict) else {}
    tick_age = _safe_int(runtime.get("tickAgeSeconds"), 0)
    latest_tick_dt = generated_dt - timedelta(seconds=max(0, tick_age))
    bid = _safe_float(market.get("bid"), 0.0)
    ask = _safe_float(market.get("ask"), 0.0)
    spread_pips = _safe_float(market.get("spread"), 0.0)
    point = 0.001 if _symbol_key(symbol).startswith("USDJPY") else 0.00001
    spread_points = abs(ask - bid) / point if ask > 0 and bid > 0 and point > 0 else spread_pips
    rows: list[dict[str, Any]] = []
    for idx in range(3):
        tick_dt = latest_tick_dt - timedelta(seconds=2 - idx)
        rows.append({
            "schema": "quantgod.mt5.fast_lane.tick.dashboard_fallback.v1",
            "generatedAt": generated_at,
            "timeIso": tick_dt.isoformat(),
            "symbol": symbol,
            "sourceSymbol": source_symbol,
            "bid": bid,
            "ask": ask,
            "point": point,
            "spreadPips": spread_pips,
            "spreadPoints": spread_points,
            "marketTickAgeSeconds": tick_age,
            "source": "QuantGod_Dashboard.json",
            "fallbackSource": "dashboard",
            "dashboardFallback": True,
            "syntheticRows": True,
            "safety": safety_payload(),
        })
    for row in rows:
        assert_safe_payload(row)
    return rows


def _rsi_indicator_payload(
    root: Path,
    dashboard: dict[str, Any] | None,
    symbol: str,
    *,
    dashboard_path: Path | None = None,
    candidate_roots: list[Path] | None = None,
) -> dict[str, Any] | None:
    candidates = candidate_roots or [root]
    standalone, standalone_path = _latest_json_file(candidates, "QuantGod_USDJPYRsiEntryDiagnostics.json")
    embedded = dashboard.get("usdJpyRsiEntryDiagnostics") if dashboard and isinstance(dashboard.get("usdJpyRsiEntryDiagnostics"), dict) else None
    embedded_path = dashboard_path or (root / "QuantGod_Dashboard.json")
    payload = standalone
    payload_path = standalone_path
    if embedded:
        standalone_mtime = 0.0
        embedded_mtime = 0.0
        try:
            standalone_mtime = standalone_path.stat().st_mtime if standalone_path else 0.0
        except Exception:
            standalone_mtime = 0.0
        try:
            embedded_mtime = embedded_path.stat().st_mtime
        except Exception:
            embedded_mtime = 0.0
        if not payload or embedded_mtime >= standalone_mtime:
            payload = embedded
            payload_path = embedded_path
    if not payload:
        return None
    source_symbol = payload.get("symbol") or _dashboard_symbol(dashboard) or symbol
    if source_symbol and not _symbol_matches(source_symbol, symbol):
        return None
    source = payload_path.name if payload_path else "QuantGod_Dashboard.json"
    generated_at = _file_mtime_iso(payload_path) if payload_path else None
    rsi = payload.get("rsi") if isinstance(payload.get("rsi"), dict) else {}
    guards = payload.get("guards") if isinstance(payload.get("guards"), dict) else {}
    indicator = {
        "schema": "quantgod.mt5.fast_lane.indicators.rsi_diagnostic_fallback.v1",
        "generatedAt": generated_at,
        "symbol": symbol,
        "sourceSymbol": source_symbol,
        "strategy": payload.get("strategy", "RSI_Reversal"),
        "state": payload.get("state"),
        "rsiClosed1": rsi.get("rsiClosed1"),
        "rsiClosed2": rsi.get("rsiClosed2"),
        "atr": rsi.get("atrClosed1"),
        "lowerBand": rsi.get("lowerBand"),
        "upperBand": rsi.get("upperBand"),
        "closeClosed1": rsi.get("closeClosed1"),
        "spreadPips": guards.get("spreadPips"),
        "source": source,
        "sourcePath": str(payload_path) if payload_path else "",
        "fallbackSource": "rsi_entry_diagnostics",
        "dashboardFallback": True,
        "safety": safety_payload(),
    }
    assert_safe_payload(indicator)
    return indicator


def read_jsonl_tail(path: Path, limit: int = 50) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    assert_safe_payload(item)
                    rows.append(item)
            except Exception:
                continue
    except Exception:
        return []
    return rows


@dataclass
class FastLaneEvidence:
    runtime_dir: Path
    heartbeat: dict[str, Any] | None
    ticks: dict[str, list[dict[str, Any]]]
    indicators: dict[str, dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    trade_events: list[dict[str, Any]]
    fallback_sources: list[str]


def _symbol_from_name(name: str, prefix: str, suffix: str) -> str:
    return name[len(prefix) : -len(suffix)]


def load_fastlane_evidence(path: str | Path = "runtime", symbols: list[str] | None = None) -> FastLaneEvidence:
    root = runtime_dir(path)
    heartbeat = read_json(root / "QuantGod_RuntimeHeartbeat.json")
    allowed = {s.upper() for s in symbols or []}
    candidates = _candidate_roots(root)
    dashboard, dashboard_path = _latest_json_file(candidates, "QuantGod_Dashboard.json")
    dashboard_root = dashboard_path.parent if dashboard_path else root
    fallback_sources: set[str] = set()
    if not heartbeat:
        heartbeat = _timer_heartbeat(dashboard_root) or _dashboard_heartbeat(dashboard_root, dashboard)
        if heartbeat:
            fallback_sources.add(str(heartbeat.get("source") or heartbeat.get("fallbackSource") or "fallback_heartbeat"))
    ticks: dict[str, list[dict[str, Any]]] = {}
    indicators: dict[str, dict[str, Any]] = {}
    if root.exists():
        for file in root.glob("QuantGod_RuntimeTicks_*.jsonl"):
            sym = _symbol_from_name(file.name, "QuantGod_RuntimeTicks_", ".jsonl")
            if allowed and sym.upper() not in allowed:
                continue
            ticks[sym] = read_jsonl_tail(file, 120)
        for file in root.glob("QuantGod_RuntimeIndicators_*.json"):
            sym = _symbol_from_name(file.name, "QuantGod_RuntimeIndicators_", ".json")
            if allowed and sym.upper() not in allowed:
                continue
            payload = read_json(file)
            if payload:
                indicators[sym] = payload
    for symbol in _requested_or_dashboard_symbols(symbols, dashboard):
        if symbol not in ticks:
            rows = _fallback_tick_rows(dashboard_root, dashboard, symbol)
            if rows:
                ticks[symbol] = rows
                fallback_sources.add(str(dashboard_path.name if dashboard_path else "QuantGod_Dashboard.json"))
        indicator = _rsi_indicator_payload(
            root,
            dashboard,
            symbol,
            dashboard_path=dashboard_path,
            candidate_roots=candidates,
        )
        if indicator and _payload_is_newer(indicator, indicators.get(symbol)):
            indicators[symbol] = indicator
            fallback_sources.add(str(indicator.get("source") or "rsi_entry_diagnostics"))
    diagnostics = read_jsonl_tail(root / "QuantGod_RuntimeStrategyDiagnostics.jsonl", 120)
    trade_events = read_jsonl_tail(root / "QuantGod_RuntimeTradeEvents.jsonl", 120)
    return FastLaneEvidence(root, heartbeat, ticks, indicators, diagnostics, trade_events, sorted(fallback_sources))


def latest_tick_age(rows: list[dict[str, Any]]) -> int | None:
    if not rows:
        return None
    latest = rows[-1]
    if latest.get("marketTickAgeSeconds") not in (None, ""):
        return _safe_int(latest.get("marketTickAgeSeconds"), 0)
    return age_seconds(latest.get("timeIso") or latest.get("generatedAt") or latest.get("time"))


def latest_indicator_age(payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    return age_seconds(payload.get("generatedAt") or payload.get("timeIso") or payload.get("timestamp"))
