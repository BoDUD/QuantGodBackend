from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from .lane_selector import _derived_primary_dashboard_path, _forex_no_entry_diagnostics, _read_json, _safe_dict, _safe_list
from .schema import (
    FOREX_LIVE12_RUNTIME_HANDOFF_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_runtime_handoff_path,
    utc_now_iso,
)

try:  # pragma: no cover - import style differs when called as a standalone script.
    from tools.mt5_readonly_bridge import runtime_dir_candidates
except Exception:  # pragma: no cover
    try:
        from mt5_readonly_bridge import runtime_dir_candidates
    except Exception:  # pragma: no cover
        runtime_dir_candidates = None


MAX_RUNTIME_DASHBOARD_AGE_SECONDS = 1800.0


def _bool(value: Any) -> bool:
    return value is True or value == "true" or value == "1" or value == 1


def _money(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(numeric if numeric == numeric else 0.0, 2)


def _float_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric


def _pip_size(symbol: str) -> float:
    normalized = str(symbol or "").upper()
    if "JPY" in normalized:
        return 0.01
    if normalized.startswith("XAU") or "GOLD" in normalized:
        return 0.1
    return 0.0001


def _round_pips(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _path_mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def _path_age_seconds(path: Path) -> float | None:
    try:
        return round(max(0.0, time.time() - path.stat().st_mtime), 1)
    except OSError:
        return None


def _process_evidence() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ps", "ax"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout or ""
    except Exception as exc:
        return {
            "mode": "READ_ONLY_PROCESS_SCAN",
            "mainMt5TerminalRunning": False,
            "isolatedTesterTerminalRunning": False,
            "dashboardServerRunning": False,
            "scanError": str(exc),
            "blockers": ["process_scan_failed"],
        }

    main_mt5_running = "terminal64" in output and "HFM_MT5_Tester_Isolated" not in output
    isolated_tester_running = "HFM_MT5_Tester_Isolated" in output and "terminal64" in output
    dashboard_server_running = "dashboard_server.js" in output or "backend-api" in output
    blockers: list[str] = []
    if not main_mt5_running:
        blockers.append("mt5_terminal_process_missing")

    return {
        "mode": "READ_ONLY_PROCESS_SCAN",
        "mainMt5TerminalRunning": main_mt5_running,
        "isolatedTesterTerminalRunning": isolated_tester_running,
        "dashboardServerRunning": dashboard_server_running,
        "blockers": blockers,
    }


def _is_source_newer(source: Path, artifact: Path) -> bool:
    try:
        return source.exists() and artifact.exists() and source.stat().st_mtime > artifact.stat().st_mtime + 0.5
    except OSError:
        return False


def _repo_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime"


def _dashboard_candidates(runtime_dir: Path, explicit_path: str = "") -> list[Path]:
    runtime = Path(runtime_dir)
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    candidates.extend([
        _derived_primary_dashboard_path(runtime),
        runtime / "mac_import" / "mt5_files_snapshot" / "QuantGod_Dashboard.json",
        runtime.parent / "Dashboard" / "QuantGod_Dashboard.json",
    ])
    include_global = runtime.resolve() == _repo_runtime_dir().resolve()
    include_global = include_global or str(os.environ.get("QG_LIVE_PREFLIGHT_INCLUDE_GLOBAL_MT5", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if include_global and callable(runtime_dir_candidates):
        candidates.extend(Path(item) / "QuantGod_Dashboard.json" for item in runtime_dir_candidates())
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        path = candidate.expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _select_dashboard_path(runtime_dir: Path, explicit_path: str = "") -> tuple[Path, list[str]]:
    candidates = _dashboard_candidates(runtime_dir, explicit_path)
    existing = [path for path in candidates if path.exists() and path.is_file()]
    if not existing:
        return (candidates[0] if candidates else _derived_primary_dashboard_path(runtime_dir), [str(path) for path in candidates])
    return max(existing, key=lambda path: path.stat().st_mtime), [str(path) for path in candidates]


def _positions(open_trades: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _safe_list(open_trades):
        if not isinstance(row, dict):
            continue
        rows.append({
            "ticket": row.get("ticket") or row.get("positionId") or "",
            "positionId": row.get("positionId") or row.get("ticket") or "",
            "symbol": row.get("symbol") or "",
            "type": row.get("type") or row.get("side") or "",
            "lots": row.get("lots") or row.get("volume") or 0,
            "openPrice": row.get("openPrice") or row.get("priceOpen") or 0,
            "sl": row.get("sl") or 0,
            "tp": row.get("tp") or 0,
            "profit": _money(row.get("profit") if row.get("profit") is not None else row.get("actualProfit")),
            "strategy": row.get("strategy") or "",
            "source": row.get("source") or "",
            "comment": row.get("comment") or "",
            "durationMinutes": row.get("durationMinutes") or 0,
        })
    return rows


def _position_distance_watch(
    positions: list[dict[str, Any]],
    *,
    bid: Any,
    ask: Any,
) -> dict[str, Any]:
    market_bid = _float_or_none(bid)
    market_ask = _float_or_none(ask)
    watched: list[dict[str, Any]] = []
    tp_distances: list[float] = []
    sl_distances: list[float] = []

    for row in positions:
        symbol = str(row.get("symbol") or "")
        side = str(row.get("type") or row.get("side") or "").upper()
        pip = _pip_size(symbol)
        current = market_bid if side == "BUY" else market_ask
        tp = _float_or_none(row.get("tp"))
        sl = _float_or_none(row.get("sl"))
        distance_to_tp: float | None = None
        distance_to_sl: float | None = None
        if current is not None and pip > 0:
            if tp is not None and tp > 0:
                raw_tp = (tp - current) if side == "BUY" else (current - tp)
                distance_to_tp = max(0.0, raw_tp / pip)
                tp_distances.append(distance_to_tp)
            if sl is not None and sl > 0:
                raw_sl = (current - sl) if side == "BUY" else (sl - current)
                distance_to_sl = max(0.0, raw_sl / pip)
                sl_distances.append(distance_to_sl)
        watched.append({
            "ticket": row.get("ticket") or row.get("positionId") or "",
            "symbol": symbol,
            "type": side,
            "lots": row.get("lots") or 0,
            "profit": _money(row.get("profit")),
            "currentClosePrice": current,
            "tp": tp,
            "sl": sl,
            "distanceToTpPips": _round_pips(distance_to_tp),
            "distanceToSlPips": _round_pips(distance_to_sl),
        })

    return {
        "mode": "READ_ONLY_CAPACITY_RELEASE_WATCH",
        "positionCount": len(positions),
        "watchedPositions": watched,
        "nearestTpPips": _round_pips(min(tp_distances)) if tp_distances else None,
        "nearestSlPips": _round_pips(min(sl_distances)) if sl_distances else None,
        "releaseTriggerZh": "等待现有 EA 持仓按 TP/SL/风控自然释放容量；此监控不平仓、不改仓、不加仓。",
        "nextPollSeconds": 60,
        "orderSendAllowed": False,
        "closeAllowed": False,
        "modifyAllowed": False,
        "writesMt5OrderRequest": False,
    }


def build_forex_live12_runtime_handoff(
    runtime_dir: Path,
    *,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    dashboard_path, checked_dashboard_paths = _select_dashboard_path(runtime, primary_dashboard_json)
    dashboard = _read_json(dashboard_path)
    runtime_payload = _safe_dict(dashboard.get("runtime"))
    account = _safe_dict(dashboard.get("account"))
    symbols = _safe_list(dashboard.get("symbols"))
    focus_symbol = symbols[0] if symbols and isinstance(symbols[0], dict) else {}
    diagnostics = _forex_no_entry_diagnostics(dashboard)
    guards = _safe_dict(diagnostics.get("guards"))
    rsi = _safe_dict(diagnostics.get("rsi"))
    positions = _positions(dashboard.get("openTrades"))
    market_payload = _safe_dict(dashboard.get("market"))
    market_symbol = market_payload.get("symbol") or focus_symbol.get("symbol") or ""
    market_bid = market_payload.get("bid") or focus_symbol.get("bid")
    market_ask = market_payload.get("ask") or focus_symbol.get("ask")
    source_dashboard_age_seconds = _path_age_seconds(dashboard_path)
    dashboard_fresh = (
        source_dashboard_age_seconds is not None
        and source_dashboard_age_seconds <= MAX_RUNTIME_DASHBOARD_AGE_SECONDS
    )
    process_evidence = _process_evidence()
    runtime_freshness_blockers: list[str] = []
    if not dashboard_fresh:
        runtime_freshness_blockers.append("live_dashboard_snapshot_stale")
    runtime_freshness_blockers.extend(str(item) for item in _safe_list(process_evidence.get("blockers")))
    runtime_fresh = dashboard_fresh and bool(process_evidence.get("mainMt5TerminalRunning"))
    capacity_release_watch = _position_distance_watch(positions, bid=market_bid, ask=market_ask)
    max_total_trades = int(account.get("maxTotalTrades") or guards.get("maxTotalPositions") or 0)
    open_position_count = len(positions)
    portfolio_full = bool(
        (max_total_trades and open_position_count >= max_total_trades)
        or str(diagnostics.get("state") or "").upper() == "PORTFOLIO_FULL"
    )
    hard_switches_active = bool(
        _bool(runtime_payload.get("livePilotMode"))
        and not _bool(runtime_payload.get("readOnlyMode"))
        and _bool(runtime_payload.get("executionEnabled"))
        and _bool(runtime_payload.get("tradeAllowed"))
    )
    status = "FOREX_LIVE12_RUNTIME_REFRESH_BLOCKED" if not runtime_fresh else (
        "FOREX_LIVE12_ACTIVE_PORTFOLIO_FULL" if hard_switches_active and portfolio_full else (
            "FOREX_LIVE12_ACTIVE_WAITING_EA_GUARDS" if hard_switches_active else "FOREX_LIVE12_WAITING_RUNTIME_SWITCHES"
        )
    )
    source_dashboard_mtime = _safe_dict(dashboard.get("_file")).get("mtimeIso") or _path_mtime_iso(dashboard_path)
    next_action = (
        "Live12 dashboard 已过期或主 MT5 进程缺失；先恢复 MT5/EA 持续刷新，再评估仓位、信号和王牌升级。"
        if status == "FOREX_LIVE12_RUNTIME_REFRESH_BLOCKED"
        else (
        "外币 Live12 EA 已在真实 pilot 运行且仓位 2/2 已满；等待 EA 自己按 TP/SL/风控释放容量，不能手动加仓或平仓。"
        if portfolio_full
        else "外币 Live12 EA 硬开关已开；等待新闻、点差、策略信号和仓位容量自然通过。"
        if hard_switches_active
        else "补齐 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 运行证据；当前 artifact 不改 preset。"
        )
    )
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_RUNTIME_HANDOFF_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "sourceDashboardPath": str(dashboard_path),
        "sourceDashboardMtimeIso": source_dashboard_mtime,
        "artifactFreshness": {
            "mode": "SOURCE_DASHBOARD_MTIME_WATCH",
            "sourceDashboardMtimeIso": source_dashboard_mtime,
            "sourceDashboardAgeSeconds": source_dashboard_age_seconds,
            "maxRuntimeDashboardAgeSeconds": MAX_RUNTIME_DASHBOARD_AGE_SECONDS,
            "checkedDashboardPaths": checked_dashboard_paths,
            "handoffGeneratedFromCurrentDashboard": True,
            "staleSourceDetected": False,
            "autoRebuiltForRead": False,
        },
        "runtimeFreshness": {
            "mode": "LIVE12_DASHBOARD_AND_PROCESS_WATCH",
            "fresh": runtime_fresh,
            "dashboardFresh": dashboard_fresh,
            "sourceDashboardAgeSeconds": source_dashboard_age_seconds,
            "maxDashboardAgeSeconds": MAX_RUNTIME_DASHBOARD_AGE_SECONDS,
            "processEvidence": process_evidence,
            "blockers": runtime_freshness_blockers,
            "nextActionZh": (
                "恢复主 MT5/EA 进程并刷新 dashboard；本 artifact 只做只读诊断。"
                if runtime_freshness_blockers
                else "运行时证据新鲜，可继续读取 EA guard、仓位和策略信号。"
            ),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
            "livePresetMutationAllowed": False,
        },
        "status": status,
        "statusZh": (
            "外币 Live12 运行时刷新阻塞，dashboard 或 MT5 进程证据不可用"
            if status == "FOREX_LIVE12_RUNTIME_REFRESH_BLOCKED"
            else "外币 Live12 已连通真实 EA pilot，但当前 EA 仓位容量已满"
            if status == "FOREX_LIVE12_ACTIVE_PORTFOLIO_FULL"
            else "外币 Live12 已连通真实 EA pilot，等待 EA 守门自然通过"
            if status == "FOREX_LIVE12_ACTIVE_WAITING_EA_GUARDS"
            else "外币 Live12 仍等待运行开关证据"
        ),
        "account": {
            "number": account.get("number"),
            "server": account.get("server"),
            "currency": account.get("currency"),
            "balance": _money(account.get("balance")),
            "equity": _money(account.get("equity")),
            "profit": _money(account.get("profit")),
            "maxTotalTrades": max_total_trades,
        },
        "runtimeSwitches": {
            "tradeStatus": runtime_payload.get("tradeStatus") or "",
            "livePilotMode": _bool(runtime_payload.get("livePilotMode")),
            "readOnlyMode": _bool(runtime_payload.get("readOnlyMode")),
            "executionEnabled": _bool(runtime_payload.get("executionEnabled")),
            "tradeAllowed": _bool(runtime_payload.get("tradeAllowed")),
            "pilotKillSwitch": _bool(runtime_payload.get("pilotKillSwitch")),
            "pilotKillReason": runtime_payload.get("pilotKillReason") or "",
            "pilotStartupEntryGuardActive": _bool(runtime_payload.get("pilotStartupEntryGuardActive")),
            "tradePermissionBlocker": runtime_payload.get("tradePermissionBlocker") or "",
            "hardSwitchesActive": hard_switches_active,
        },
        "positionSummary": {
            "openPositionCount": open_position_count,
            "maxTotalTrades": max_total_trades,
            "portfolioFull": portfolio_full,
            "floatingProfit": _money(sum(_money(row.get("profit")) for row in positions)),
            "positions": positions,
        },
        "capacityReleaseWatch": {
            **capacity_release_watch,
            "portfolioFull": portfolio_full,
            "capacityUsed": open_position_count,
            "capacityLimit": max_total_trades,
            "capacityLineZh": (
                f"{open_position_count}/{max_total_trades} 已占用，"
                f"最近 TP 约 {capacity_release_watch['nearestTpPips']} pips，"
                f"最近 SL 约 {capacity_release_watch['nearestSlPips']} pips"
                if portfolio_full and max_total_trades
                else f"{open_position_count}/{max_total_trades or '未知'} 已占用，等待 EA 守门自然通过"
            ),
        },
        "noEntryDiagnostics": {
            "state": diagnostics.get("state") or "",
            "stateZh": diagnostics.get("stateZh") or "",
            "summary": diagnostics.get("summary") or "",
            "whyNoEntry": _safe_list(diagnostics.get("whyNoEntry")),
            "guards": guards,
            "rsi": rsi,
        },
        "market": {
            "symbol": market_symbol,
            "bid": market_bid,
            "ask": market_ask,
            "spread": market_payload.get("spread") or focus_symbol.get("spread"),
        },
        "nextRequiredActionZh": next_action,
        "automationCanContinueWithoutUser": True,
        "operatorPromptRequired": False,
        "canAddPositionHere": False,
        "canClosePositionHere": False,
        "canModifyPositionHere": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "closeAllowed": False,
        "cancelAllowed": False,
        "modifyAllowed": False,
        "requestFilesWritten": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
        "livePresetMutationAllowed": False,
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = forex_live12_runtime_handoff_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_runtime_handoff(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_runtime_handoff_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_runtime_handoff(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_RUNTIME_HANDOFF_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 runtime handoff artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        source_path, _ = _select_dashboard_path(runtime, str(payload.get("sourceDashboardPath") or ""))
        source_age_seconds = _path_age_seconds(source_path)
        runtime_freshness = _safe_dict(payload.get("runtimeFreshness"))
        should_rebuild_for_read = (
            _is_source_newer(source_path, path)
            or not runtime_freshness
            or (
                source_age_seconds is not None
                and source_age_seconds > MAX_RUNTIME_DASHBOARD_AGE_SECONDS
                and runtime_freshness.get("dashboardFresh") is not False
            )
        )
        if should_rebuild_for_read:
            rebuilt = build_forex_live12_runtime_handoff(runtime, primary_dashboard_json=str(source_path), write=False)
            rebuilt["artifactFreshness"] = {
                **_safe_dict(rebuilt.get("artifactFreshness")),
                "staleSourceDetected": _is_source_newer(source_path, path),
                "autoRebuiltForRead": True,
                "previousArtifactMtimeIso": _path_mtime_iso(path),
            }
            assert_no_execution_flags(rebuilt)
            return rebuilt
        payload["artifactFreshness"] = {
            **_safe_dict(payload.get("artifactFreshness")),
            "artifactFileMtimeIso": _path_mtime_iso(path),
            "artifactAgeSeconds": _path_age_seconds(path),
            "staleSourceDetected": False,
            "autoRebuiltForRead": False,
        }
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_runtime_handoff(runtime, write=False)
