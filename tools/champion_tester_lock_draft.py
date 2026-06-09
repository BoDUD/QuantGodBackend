"""Lock draft for the current champion tester/forward run."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from tools.auto_tester_window_guard import LOCK_NAME, LOCK_PURPOSE
    from tools.champion_tester_run_gate import build_champion_tester_run_gate
except ModuleNotFoundError:  # pragma: no cover
    from auto_tester_window_guard import LOCK_NAME, LOCK_PURPOSE
    from champion_tester_run_gate import build_champion_tester_run_gate


REPORT_SCHEMA = "quantgod.champion_tester_lock_draft.v1"
REPORT_PATH = Path("agent") / "QuantGod_ChampionTesterLockDraft.json"

SAFETY = {
    "readOnly": True,
    "testerOnly": True,
    "lockFileWritten": False,
    "runTerminalHere": False,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "writesMt5OrderReceipt": False,
    "writesLivePreset": False,
    "livePresetMutationAllowed": False,
    "brokerCallsMade": False,
    "walletAuthorizationAllowed": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    return {"createdAtIso": _utc_iso(created), "expiresAtIso": _utc_iso(expires)}


def build_champion_tester_lock_draft(
    runtime_dir: Path,
    *,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    run_gate = build_champion_tester_run_gate(
        runtime,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    gate = _safe_dict(run_gate.get("gate"))
    environment = _safe_dict(gate.get("environment"))
    lock = _safe_dict(gate.get("authorizationLock"))
    queue = _safe_dict(gate.get("queue"))
    next_window = _safe_dict(run_gate.get("nextTesterWindow"))
    selected_champion = _safe_dict(run_gate.get("selectedChampion"))
    source_request = _safe_dict(run_gate.get("sourceTesterRequest"))
    seed_id = str(selected_champion.get("seedId") or "UNKNOWN_CHAMPION")
    candidate_id = str(source_request.get("topCandidateId") or "")
    candidate_ids = source_request.get("candidateIds") if isinstance(source_request.get("candidateIds"), list) else []
    times = _draft_times(next_window)
    lock_path = Path(str(lock.get("path") or Path(environment.get("runtimeDir", "")) / LOCK_NAME))
    terminal_path = Path(str(environment.get("terminalPath") or ""))
    hfm_root = str(terminal_path.parent) if str(terminal_path) else ""
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
        "runtimeDir": str(environment.get("runtimeDir") or ""),
        "hfmRoot": hfm_root,
        "maxTasks": 1,
        "source": "quantgod.champion_tester_lock_draft",
        "candidateId": candidate_id,
        "candidateIds": candidate_ids or ([candidate_id] if candidate_id else []),
        "seedId": seed_id,
    }
    payload = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "status": "CHAMPION_TESTER_LOCK_DRAFT_READY",
        "statusZh": f"{seed_id} tester lock 草案已生成",
        "targetLockPath": str(lock_path),
        "lockFileWritten": False,
        "lockFileExistsNow": lock_path.exists(),
        "nextTesterWindow": next_window,
        "sourceTesterGate": {
            "status": run_gate.get("status"),
            "statusZh": run_gate.get("statusZh"),
            "blockers": gate.get("blockers", []),
            "liveSession": gate.get("liveSession", {}),
            "queue": queue,
            "testerAccountContext": run_gate.get("testerAccountContext", {}),
        },
        "draftPayload": draft_payload,
        "decision": {
            "draftReadyForSeparateLockWriter": True,
            "lockFileWritten": False,
            "canRunTerminalHere": False,
            "canRunIsolatedTesterHere": False,
            "canPromoteToLiveHere": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
            "nextRequiredActionZh": "到 tester 窗口且账户上下文就绪后，单独受控 lock writer 可按 draftPayload 写短期 lock；本 artifact 不写 lock、不启动 terminal。",
        },
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, payload)
    return payload


def read_champion_tester_lock_draft(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    return build_champion_tester_lock_draft(runtime, write=False)
