from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from typing import Any

try:
    from tools.auto_tester_window_guard import LOCK_NAME, evaluate_execution_gate
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from auto_tester_window_guard import LOCK_NAME, evaluate_execution_gate

from .forex_live12_runtime_handoff import build_forex_live12_runtime_handoff
from .forex_live12_rsi_tester_request import build_forex_live12_rsi_tester_request
from .lane_selector import _derived_primary_dashboard_path
from .schema import (
    FOREX_LIVE12_RSI_TESTER_RUN_GATE_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_rsi_tester_run_gate_path,
    utc_now_iso,
)

JST = timezone(timedelta(hours=9))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_value(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _live_dashboard_runtime_dir(runtime: Path, explicit_dashboard_json: str = "") -> Path:
    dashboard_path = Path(explicit_dashboard_json) if explicit_dashboard_json else _derived_primary_dashboard_path(runtime)
    return dashboard_path.parent


def _path_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _path_mtime_iso(path: Path) -> str:
    mtime = _path_mtime(path)
    if mtime is None:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))


def _source_paths(runtime: Path, primary_dashboard_json: str = "") -> dict[str, Path]:
    dashboard_path = Path(primary_dashboard_json) if primary_dashboard_json else _derived_primary_dashboard_path(runtime)
    repo_root = _repo_root()
    isolated_request = repo_root / "runtime" / "HFM_MT5_Tester_Isolated" / "MQL5" / "Files" / "agent" / "QuantGod_ForexLive12RsiTesterRequest.json"
    isolated_status = repo_root / "runtime" / "HFM_MT5_Tester_Isolated" / "MQL5" / "Files" / "agent" / "QuantGod_ForexLive12RsiTesterParamLabStatus.json"
    account_context_status = repo_root / "runtime" / "QuantGod_IsolatedTesterAccountContextStatus.json"
    return {
        "primaryDashboard": dashboard_path,
        "testerRequest": isolated_request,
        "testerMaterializationStatus": isolated_status,
        "accountContextStatus": account_context_status,
    }


def _extract_dashboard_path_from_payload(payload: dict[str, Any]) -> str:
    gate = _safe_dict(payload.get("gate"))
    live_session = _safe_dict(gate.get("liveSession"))
    path = str(live_session.get("path") or "")
    if path:
        return path
    source = _safe_dict(payload.get("liveSessionSource"))
    runtime_dir = str(source.get("dashboardRuntimeDir") or "")
    return str(Path(runtime_dir) / "QuantGod_Dashboard.json") if runtime_dir else ""


def _needs_rebuild(runtime: Path, artifact_path: Path, payload: dict[str, Any]) -> bool:
    artifact_mtime = _path_mtime(artifact_path)
    if artifact_mtime is None:
        return True
    generated_at = str(payload.get("generatedAtIso") or "")
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - generated > timedelta(seconds=75):
            return True
    except Exception:
        return True
    sources = _source_paths(runtime, _extract_dashboard_path_from_payload(payload))
    for source in sources.values():
        source_mtime = _path_mtime(source)
        if source_mtime is not None and source_mtime > artifact_mtime + 0.5:
            return True
    return False


def _jst_window_on(day: datetime, start_hour: int, start_minute: int, end_hour: int, end_minute: int) -> tuple[datetime, datetime]:
    start = day.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end = day.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return start, end


def _next_tester_window(now_utc: datetime | None = None) -> dict[str, Any]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(JST)
    windows: list[tuple[datetime, datetime, str]] = []
    for offset in range(0, 8):
        day = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        windows.append((*_jst_window_on(day, 0, 0, 2, 30), "daily_closeout"))
        windows.append((*_jst_window_on(day, 20, 10, 23, 30), "daily_night"))
        weekday = day.weekday()
        if weekday == 5:
            windows.append((*_jst_window_on(day, 7, 10, 9, 30), "saturday_morning"))
        if weekday == 6:
            windows.append((*_jst_window_on(day, 8, 0, 9, 30), "sunday_morning"))
    future = [(start, end, label) for start, end, label in windows if end >= now]
    future.sort(key=lambda row: row[0])
    for start, end, label in future:
        if start <= now <= end:
            return {
                "status": "open_now",
                "label": label,
                "startJstIso": start.isoformat(),
                "endJstIso": end.isoformat(),
                "minutesUntilStart": 0,
                "minutesUntilEnd": round((end - now).total_seconds() / 60, 1),
            }
        if start > now:
            return {
                "status": "waiting",
                "label": label,
                "startJstIso": start.isoformat(),
                "endJstIso": end.isoformat(),
                "minutesUntilStart": round((start - now).total_seconds() / 60, 1),
                "minutesUntilEnd": round((end - now).total_seconds() / 60, 1),
            }
    return {"status": "unknown", "label": "", "startJstIso": "", "endJstIso": "", "minutesUntilStart": None, "minutesUntilEnd": None}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _account_context_status(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "runtime" / "QuantGod_IsolatedTesterAccountContextStatus.json"
    status = _read_json(path)
    ready = bool(status.get("ready"))
    missing = status.get("missingTarget") if isinstance(status.get("missingTarget"), list) else []
    blockers = [] if ready else ["isolated_tester_account_context_not_ready"]
    return {
        "path": str(path),
        "exists": path.exists(),
        "ready": ready,
        "mode": status.get("mode", ""),
        "generatedAtIso": status.get("generatedAtIso", ""),
        "missingTarget": missing,
        "nextActionZh": status.get("nextActionZh", ""),
        "blockers": blockers,
    }


def build_forex_live12_rsi_tester_run_gate(
    runtime_dir: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    repo_root = _repo_root()
    tester_request = build_forex_live12_rsi_tester_request(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    live_handoff = build_forex_live12_runtime_handoff(
        runtime,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    isolation = _safe_dict(tester_request.get("testerIsolation"))
    isolated_tester_root = Path(str(isolation.get("isolatedTesterRoot") or repo_root / "runtime" / "HFM_MT5_Tester_Isolated"))
    isolated_runtime_dir = Path(str(isolation.get("isolatedRuntimeDir") or isolated_tester_root / "MQL5" / "Files"))
    live_runtime_dir = _live_dashboard_runtime_dir(runtime, primary_dashboard_json)
    scheduler = {
        "summary": dict(_safe_dict(tester_request.get("summary")), runTerminal=False, livePresetMutation=False),
        "selectedTasks": tester_request.get("selectedTasks") if isinstance(tester_request.get("selectedTasks"), list) else [],
    }
    account = _safe_dict(live_handoff.get("account"))
    gate = evaluate_execution_gate(
        scheduler=scheduler,
        runtime_dir=live_runtime_dir,
        hfm_root=isolated_tester_root,
        repo_root=repo_root,
        lock_path=isolated_runtime_dir / LOCK_NAME,
        max_tasks=max(1, _int_value(tester_request.get("summary", {}).get("queueCount"), 1)),
        expected_login=str(account.get("number") or ""),
        expected_server=str(account.get("server") or ""),
        max_live_snapshot_age_minutes=30,
    )
    account_context = _account_context_status(repo_root)
    gate = dict(gate)
    blockers = list(gate.get("blockers") if isinstance(gate.get("blockers"), list) else [])
    blockers.extend(str(item) for item in account_context.get("blockers", []))
    gate["blockers"] = blockers
    gate["canRunTerminal"] = bool(gate.get("canRunTerminal") and account_context.get("ready"))
    gate["status"] = "ready" if gate["canRunTerminal"] else "blocked"
    gate["accountContext"] = account_context
    status = "RSI_TESTER_RUN_GATE_READY" if gate.get("canRunTerminal") is True else "RSI_TESTER_RUN_GATE_BLOCKED"
    source_paths = _source_paths(runtime, primary_dashboard_json)
    next_window = _next_tester_window()
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_RSI_TESTER_RUN_GATE_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "artifactFreshness": {
            "mode": "TIME_SENSITIVE_TESTER_GATE_READ_REBUILD",
            "primaryDashboardPath": str(source_paths["primaryDashboard"]),
            "primaryDashboardMtimeIso": _path_mtime_iso(source_paths["primaryDashboard"]),
            "testerRequestPath": str(source_paths["testerRequest"]),
            "testerRequestMtimeIso": _path_mtime_iso(source_paths["testerRequest"]),
            "testerMaterializationStatusPath": str(source_paths["testerMaterializationStatus"]),
            "testerMaterializationStatusMtimeIso": _path_mtime_iso(source_paths["testerMaterializationStatus"]),
            "accountContextStatusPath": str(source_paths["accountContextStatus"]),
            "accountContextStatusMtimeIso": _path_mtime_iso(source_paths["accountContextStatus"]),
            "generatedFromCurrentSource": True,
            "autoRebuiltForRead": False,
        },
        "status": status,
        "statusZh": "隔离 RSI Tester 可进入受控启动窗口" if status.endswith("READY") else "隔离 RSI Tester 启动条件未满足",
        "requestedMaxTotalTrades": requested_max_total_trades,
        "sourceTesterRequest": {
            "schema": tester_request.get("schema"),
            "status": tester_request.get("status"),
            "statusZh": tester_request.get("statusZh"),
            "isolatedPlanPath": tester_request.get("isolatedPlanPath"),
            "materializationStatus": tester_request.get("materializationStatus", {}),
            "queueCount": tester_request.get("summary", {}).get("queueCount"),
            "runTerminal": False,
            "livePresetMutation": False,
        },
        "liveSessionSource": {
            "dashboardRuntimeDir": str(live_runtime_dir),
            "handoffStatus": live_handoff.get("status"),
            "handoffStatusZh": live_handoff.get("statusZh"),
            "openPositionCount": live_handoff.get("positionSummary", {}).get("openPositionCount"),
            "floatingProfit": live_handoff.get("positionSummary", {}).get("floatingProfit"),
            "maxTotalTrades": live_handoff.get("positionSummary", {}).get("maxTotalTrades"),
        },
        "gate": gate,
        "testerAccountContext": account_context,
        "nextTesterWindow": next_window,
        "decision": {
            "canRunTerminalHere": False,
            "canRunIsolatedTester": bool(gate.get("canRunTerminal")),
            "canApplyHere": False,
            "canWritePresetHere": False,
            "canPromoteToLiveHere": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
            "nextRequiredActionZh": (
                "隔离 tester 条件已满足；仍需另一个受控启动动作才能运行 Strategy Tester。"
                if gate.get("canRunTerminal")
                else (
                    f"等待 tester gate 清空 blocker：{', '.join(str(item) for item in blockers[:6]) or '未知 blocker'}。"
                    f" 下一次 tester 窗口：{next_window.get('startJstIso') or '未知'}。"
                )
            ),
        },
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = forex_live12_rsi_tester_run_gate_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_rsi_tester_run_gate(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_rsi_tester_run_gate_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_rsi_tester_run_gate(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_RSI_TESTER_RUN_GATE_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 RSI tester run gate artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        if _needs_rebuild(runtime, path, payload):
            primary_dashboard_json = _extract_dashboard_path_from_payload(payload)
            rebuilt = build_forex_live12_rsi_tester_run_gate(runtime, primary_dashboard_json=primary_dashboard_json, write=False)
            rebuilt["artifactFreshness"]["autoRebuiltForRead"] = True
            return rebuilt
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_rsi_tester_run_gate(runtime, write=False)
