from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

try:
    from tools.auto_tester_window_guard import LOCK_NAME, LOCK_PURPOSE
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from auto_tester_window_guard import LOCK_NAME, LOCK_PURPOSE

from .forex_live12_rsi_tester_run_gate import (
    _next_tester_window,
    build_forex_live12_rsi_tester_run_gate,
)
from .schema import (
    FOREX_LIVE12_RSI_TESTER_LOCK_DRAFT_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_rsi_tester_lock_draft_path,
    utc_now_iso,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _draft_times(next_window: dict[str, Any], *, ttl_minutes: int = 90) -> dict[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = _parse_iso(next_window.get("startJstIso")) or now
    end = _parse_iso(next_window.get("endJstIso")) or (now + timedelta(minutes=ttl_minutes))
    created = max(now, start.astimezone(timezone.utc) - timedelta(minutes=5))
    expires = min(created + timedelta(minutes=max(15, min(ttl_minutes, 180))), end.astimezone(timezone.utc))
    if expires <= created:
        expires = created + timedelta(minutes=15)
    return {
        "createdAtIso": _utc_iso(created),
        "expiresAtIso": _utc_iso(expires),
    }


def build_forex_live12_rsi_tester_lock_draft(
    runtime_dir: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    repo_root = _repo_root()
    tester_gate = build_forex_live12_rsi_tester_run_gate(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    gate_payload = _safe_dict(tester_gate.get("gate"))
    lock_payload = _safe_dict(gate_payload.get("authorizationLock"))
    environment = _safe_dict(gate_payload.get("environment"))
    next_window = _safe_dict(tester_gate.get("nextTesterWindow")) or _next_tester_window()
    isolated_runtime_dir = repo_root / "runtime" / "HFM_MT5_Tester_Isolated" / "MQL5" / "Files"
    hfm_root = repo_root / "runtime" / "HFM_MT5_Tester_Isolated"
    lock_path = Path(str(lock_payload.get("path") or isolated_runtime_dir / LOCK_NAME))
    live_runtime_dir = Path(str(environment.get("runtimeDir") or ""))
    times = _draft_times(next_window)
    max_tasks = int(_safe_dict(gate_payload.get("queue")).get("queueCount") or 1)
    draft_payload = {
        "schemaVersion": 1,
        "purpose": LOCK_PURPOSE,
        "authorized": True,
        "testerOnly": True,
        "allowRunTerminal": True,
        "livePresetMutation": False,
        "allowOutsideWindow": False,
        "createdAtIso": times["createdAtIso"],
        "expiresAtIso": times["expiresAtIso"],
        "runtimeDir": str(live_runtime_dir),
        "hfmRoot": str(hfm_root),
        "maxTasks": max(1, max_tasks),
        "source": "quantgod.forex_live12_rsi_tester_lock_draft",
    }
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_RSI_TESTER_LOCK_DRAFT_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": "RSI_TESTER_LOCK_DRAFT_READY",
        "statusZh": "RSI tester lock 草案已生成",
        "requestedMaxTotalTrades": requested_max_total_trades,
        "targetLockPath": str(lock_path),
        "lockFileWritten": False,
        "lockFileExistsNow": lock_path.exists(),
        "nextTesterWindow": next_window,
        "sourceTesterGate": {
            "status": tester_gate.get("status"),
            "statusZh": tester_gate.get("statusZh"),
            "blockers": gate_payload.get("blockers", []),
            "liveSession": gate_payload.get("liveSession", {}),
            "queue": gate_payload.get("queue", {}),
        },
        "draftPayload": draft_payload,
        "decision": {
            "draftReadyForSeparateLockWriter": True,
            "lockFileWritten": False,
            "canRunTerminalHere": False,
            "canRunIsolatedTesterHere": False,
            "canApplyHere": False,
            "canWritePresetHere": False,
            "canPromoteToLiveHere": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
            "nextRequiredActionZh": "到 tester 窗口时，单独的受控 lock writer 可按 draftPayload 写入短期 lock；本 artifact 不写 lock、不启动 terminal。",
        },
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = forex_live12_rsi_tester_lock_draft_path(runtime)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _dashboard_path_from_payload(payload: dict[str, Any]) -> str:
    source_gate = _safe_dict(payload.get("sourceTesterGate"))
    live_session = _safe_dict(source_gate.get("liveSession"))
    path = str(live_session.get("path") or "")
    if path:
        return path
    runtime_dir = str(_safe_dict(payload.get("draftPayload")).get("runtimeDir") or "")
    return str(Path(runtime_dir) / "QuantGod_Dashboard.json") if runtime_dir else ""


def read_forex_live12_rsi_tester_lock_draft(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_rsi_tester_lock_draft_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_rsi_tester_lock_draft(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_RSI_TESTER_LOCK_DRAFT_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 RSI tester lock draft artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        primary_dashboard_json = _dashboard_path_from_payload(payload)
        rebuilt = build_forex_live12_rsi_tester_lock_draft(
            runtime,
            primary_dashboard_json=primary_dashboard_json,
            write=False,
        )
        rebuilt["artifactFreshness"] = {
            "mode": "LOCK_DRAFT_STATUS_REBUILD_FROM_SOURCE_ARTIFACT",
            "sourceArtifactPath": str(path),
            "primaryDashboardPath": primary_dashboard_json,
            "autoRebuiltForRead": True,
        }
        return rebuilt
    return build_forex_live12_rsi_tester_lock_draft(runtime, write=False)
