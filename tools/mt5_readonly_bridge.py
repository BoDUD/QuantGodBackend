"""Read-only MetaTrader 5 bridge for the local QuantGod dashboard.

The bridge intentionally exposes status, account, positions, orders, symbols,
and quote data only. It never sends orders, closes positions, cancels orders,
stores credentials, writes MT5 files, or changes the live preset.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAFETY = {
    "readOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "credentialStorageAllowed": False,
    "livePresetMutationAllowed": False,
    "mutatesMt5": False,
}

ENDPOINTS = {"status", "account", "positions", "orders", "symbols", "quote", "snapshot"}
DEFAULT_SYMBOL_LIMIT = 120
MAX_SYMBOL_LIMIT = 2000
DEFAULT_EA_SNAPSHOT_MAX_AGE_SECONDS = 180


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_from_timestamp(value: Any) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return ""


def public_error(message: str, *, detail: Any = None) -> dict[str, Any]:
    payload = {
        "ok": False,
        "status": "UNAVAILABLE",
        "generatedAtIso": utc_now(),
        "error": str(message),
        "safety": SAFETY,
    }
    if detail not in (None, ""):
        payload["detail"] = detail
    return payload


def base_payload(endpoint: str) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "MT5_READONLY_BRIDGE_V1",
        "endpoint": endpoint,
        "generatedAtIso": utc_now(),
        "safety": SAFETY,
    }


def load_mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        return None, public_error(
            "MetaTrader5 Python package is unavailable in this Python environment. On macOS, use the EA dashboard snapshot; the Python bridge is Windows-only/optional.",
            detail=str(exc),
        )
    return mt5, None


def is_windows_absolute_path(value: Any) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", str(value or "").strip()))


def mac_mt5_files_dir() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "net.metaquotes.wine.metatrader5"
        / "drive_c"
        / "Program Files"
        / "MetaTrader 5"
        / "MQL5"
        / "Files"
    )


def runtime_dir_candidates() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    raw_values = [
        os.environ.get("QG_RUNTIME_DIR", ""),
        os.environ.get("QG_MT5_FILES_DIR", ""),
        os.environ.get("QG_HFM_FILES_DIR", ""),
    ]
    explicit_only = str(os.environ.get("QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    candidates: list[Path] = []
    for raw in raw_values:
        value = str(raw or "").strip()
        if not value:
            continue
        if os.name != "nt" and is_windows_absolute_path(value):
            continue
        candidates.append(Path(value).expanduser())
    if explicit_only:
        seen: set[str] = set()
        unique: list[Path] = []
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique
    candidates.extend(
        [
            mac_mt5_files_dir(),
            repo_root / "runtime" / "mac_import" / "mt5_files_snapshot",
            repo_root / "runtime",
            repo_root / "Dashboard",
        ]
    )
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def read_ea_dashboard_snapshot() -> tuple[dict[str, Any] | None, Path | None, dict[str, Any] | None]:
    found: list[tuple[float, Path, dict[str, Any]]] = []
    parse_errors: list[dict[str, str]] = []
    for directory in runtime_dir_candidates():
        file_path = directory / "QuantGod_Dashboard.json"
        if not file_path.exists():
            continue
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8").lstrip("\ufeff"))
            stat = file_path.stat()
            found.append((stat.st_mtime, file_path, payload))
        except Exception as exc:
            parse_errors.append({"path": str(file_path), "error": str(exc)})
    if found:
        _, file_path, payload = sorted(found, key=lambda item: item[0], reverse=True)[0]
        return payload, file_path, None
    if parse_errors:
        return None, None, {"parseErrors": parse_errors}
    return None, None, None


def ea_snapshot_max_age_seconds() -> int:
    raw = os.environ.get("QG_MT5_EA_SNAPSHOT_MAX_AGE_SECONDS", "")
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = DEFAULT_EA_SNAPSHOT_MAX_AGE_SECONDS
    return max(15, value)


def ea_snapshot_age_seconds(stat: os.stat_result | None) -> float | None:
    if not stat:
        return None
    return max(0.0, time.time() - float(stat.st_mtime))


def parse_local_evidence_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def ea_snapshot_evidence(
    file_path: Path | None,
    dashboard: dict[str, Any],
    stat: os.stat_result | None,
) -> dict[str, Any]:
    """Use writer-owned timestamps so copying an old JSON cannot make it fresh."""
    now = time.time()
    candidates: list[tuple[str, float]] = []
    if stat is not None:
        candidates.append(("file_mtime", float(stat.st_mtime)))

    dashboard_timestamp = parse_local_evidence_timestamp(dashboard.get("timestamp"))
    if dashboard_timestamp is not None:
        candidates.append(("dashboard_timestamp", dashboard_timestamp))

    heartbeat_path = file_path.with_name("QuantGod_MT5_TimerHeartbeat.txt") if file_path else None
    heartbeat_stat: os.stat_result | None = None
    heartbeat_timestamp: float | None = None
    heartbeat_local_time = ""
    if heartbeat_path and heartbeat_path.exists():
        try:
            heartbeat_stat = heartbeat_path.stat()
            heartbeat_text = heartbeat_path.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"(?m)^localTime=(.+?)\s*$", heartbeat_text)
            heartbeat_local_time = match.group(1).strip() if match else ""
            heartbeat_timestamp = parse_local_evidence_timestamp(heartbeat_local_time)
        except OSError:
            heartbeat_stat = None
        if heartbeat_stat is not None:
            candidates.append(("heartbeat_mtime", float(heartbeat_stat.st_mtime)))
        if heartbeat_timestamp is not None:
            candidates.append(("heartbeat_local_time", heartbeat_timestamp))

    effective_timestamp = min((value for _, value in candidates), default=None)
    age_seconds = max(0.0, now - effective_timestamp) if effective_timestamp is not None else None
    oldest_source = ""
    if effective_timestamp is not None:
        oldest_source = next((name for name, value in candidates if value == effective_timestamp), "")
    return {
        "ageSeconds": age_seconds,
        "oldestSource": oldest_source,
        "evidenceSources": [name for name, _ in candidates],
        "dashboardTimestamp": str(dashboard.get("timestamp") or ""),
        "dashboardTimestampIso": (
            datetime.fromtimestamp(dashboard_timestamp, timezone.utc).isoformat().replace("+00:00", "Z")
            if dashboard_timestamp is not None
            else ""
        ),
        "heartbeatFile": str(heartbeat_path) if heartbeat_path and heartbeat_path.exists() else "",
        "heartbeatLocalTime": heartbeat_local_time,
        "heartbeatMtimeIso": (
            datetime.fromtimestamp(heartbeat_stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
            if heartbeat_stat is not None
            else ""
        ),
    }


def ea_snapshot_fresh(stat: os.stat_result | None, evidence: dict[str, Any] | None = None) -> bool:
    age = evidence.get("ageSeconds") if isinstance(evidence, dict) else ea_snapshot_age_seconds(stat)
    if age is None:
        return False
    return age <= ea_snapshot_max_age_seconds()


def ea_snapshot_freshness(
    file_path: Path | None,
    stat: os.stat_result | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    age = evidence.get("ageSeconds") if isinstance(evidence, dict) else ea_snapshot_age_seconds(stat)
    max_age = ea_snapshot_max_age_seconds()
    fresh = age is not None and age <= max_age
    source_file = str(file_path) if file_path else ""
    status_zh = "MT5 dashboard 快照新鲜" if fresh else "MT5 dashboard 快照已过期"
    next_action_zh = (
        "继续读取最新 EA dashboard 快照。"
        if fresh
        else "恢复 MT5 终端和 EA dashboard writer，让 QuantGod_Dashboard.json 重新写入；恢复前不要把账户、持仓或执行状态当成当前实盘。"
    )
    return {
        "mode": "MT5_READONLY_EA_SNAPSHOT_MTIME_WATCH",
        "status": "FRESH_EA_SNAPSHOT" if fresh else "STALE_EA_SNAPSHOT",
        "statusLabel": "EA snapshot fresh" if fresh else "EA snapshot stale",
        "statusZh": status_zh,
        "fresh": fresh,
        "stale": not fresh,
        "ageSeconds": round(age, 3) if age is not None else None,
        "maxAgeSeconds": max_age,
        "sourceFile": source_file,
        "freshnessBasis": "oldest_writer_evidence" if evidence else "file_mtime",
        "oldestEvidenceSource": evidence.get("oldestSource", "") if evidence else "file_mtime",
        "evidenceSources": list(evidence.get("evidenceSources") or []) if evidence else ["file_mtime"],
        "blockers": [] if fresh else ["live_dashboard_snapshot_stale"],
        "nextAction": (
            "Continue reading the latest EA dashboard snapshot."
            if fresh
            else "Restore the MT5/EA dashboard writer so QuantGod_Dashboard.json is refreshed before using live account state."
        ),
        "nextActionZh": next_action_zh,
        "recoveryStepsZh": (
            []
            if fresh
            else [
                "确认对应 HFM/MT5 终端正在运行。",
                "确认 EA 已加载并持续写出 QuantGod_Dashboard.json。",
                "刷新 /api/mt5-readonly/snapshot，直到 freshness 重新变为 fresh。",
            ]
        ),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerCallsMade": False,
        "mutatesMt5": False,
    }


def ea_snapshot_missing_freshness(host_process: dict[str, Any] | None = None) -> dict[str, Any]:
    host_process = host_process or {}
    blockers = ["missing_ea_dashboard_snapshot"]
    if host_process.get("terminalProcessDetected") is False:
        blockers.append("mt5_terminal_process_missing")
    return {
        "mode": "MT5_READONLY_EA_SNAPSHOT_MTIME_WATCH",
        "status": "MISSING_EA_SNAPSHOT",
        "statusLabel": "EA snapshot missing",
        "statusZh": "MT5 dashboard 快照缺失",
        "fresh": False,
        "stale": True,
        "ageSeconds": None,
        "maxAgeSeconds": ea_snapshot_max_age_seconds(),
        "sourceFile": "",
        "blockers": blockers,
        "nextAction": "Restore the MT5 terminal/EA dashboard writer so QuantGod_Dashboard.json is created before using live account state.",
        "nextActionZh": "未找到 QuantGod_Dashboard.json；先恢复 MT5 终端和 EA dashboard writer，让快照文件重新生成，恢复前不要把账号数据当成当前实盘。",
        "recoveryStepsZh": [
            "确认对应 HFM/MT5 终端正在运行。",
            "确认 QuantGod EA 已加载并允许写入 dashboard 只读快照。",
            "确认 QG_RUNTIME_DIR / QG_MT5_FILES_DIR 指向当前 MT5 MQL5/Files 目录。",
            "刷新 /api/mt5-readonly/snapshot，直到找到 QuantGod_Dashboard.json 且 freshness 为 fresh。",
        ],
        "hostProcessStatus": host_process.get("status"),
        "terminalProcessDetected": host_process.get("terminalProcessDetected"),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerCallsMade": False,
        "mutatesMt5": False,
    }


def detect_mt5_host_process(file_path: Path | None) -> dict[str, Any]:
    hints: list[str] = []
    if file_path:
        parts = [str(file_path)]
        try:
            parts.extend(str(parent) for parent in file_path.parents[:5])
        except Exception:
            pass
        hints = [value for value in parts if value]
    if str(os.environ.get("QG_MT5_READONLY_PROCESS_SCAN_DISABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return {
            "status": "PROCESS_SCAN_DISABLED",
            "terminalProcessDetected": False,
            "targetProcessDetected": False,
            "matchingProcessCount": 0,
            "targetHint": hints[0] if hints else "",
        }
    if os.name == "nt":
        command = ["tasklist", "/FO", "CSV", "/NH"]
    else:
        command = ["ps", "-axo", "pid=,comm=,args="]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=2)
    except Exception as exc:
        return {
            "status": "PROCESS_SCAN_FAILED",
            "terminalProcessDetected": False,
            "targetProcessDetected": False,
            "matchingProcessCount": 0,
            "targetHint": hints[0] if hints else "",
            "error": str(exc),
        }
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    terminal_rows = [row for row in rows if is_mt5_host_process_row(row)]
    terminal_pids = [pid for row in terminal_rows if (pid := mt5_host_process_pid(row)) is not None]
    process_cwds = mt5_host_process_cwds(terminal_pids)
    hint_matches = []
    for row in terminal_rows:
        normalized_row = row.replace("\\", "/")
        pid = mt5_host_process_pid(row)
        cwd = process_cwds.get(pid, "") if pid is not None else ""
        if cwd and mt5_process_cwd_matches_snapshot(cwd, file_path):
            hint_matches.append(row)
            continue
        for hint in hints:
            if hint and hint.replace("\\", "/") in normalized_row:
                hint_matches.append(row)
                break
    target_detected = bool(hint_matches)
    terminal_detected = bool(terminal_rows)
    return {
        "status": "RUNNING" if terminal_detected else "MISSING",
        "terminalProcessDetected": terminal_detected,
        "targetProcessDetected": target_detected,
        "matchingProcessCount": len(terminal_rows),
        "targetHint": hints[0] if hints else "",
        "matchedTargetProcessCount": len(hint_matches),
        "scanner": "tasklist" if os.name == "nt" else "ps",
    }


def mt5_host_process_pid(row: str) -> int | None:
    match = re.match(r"\s*(?P<pid>\d+)\s+", str(row or ""))
    if not match:
        return None
    try:
        return int(match.group("pid"))
    except (TypeError, ValueError):
        return None


def mt5_host_process_cwds(pids: list[int]) -> dict[int, str]:
    """Return cwd evidence for candidate terminal processes without reading env."""
    unique_pids = sorted({int(pid) for pid in pids if int(pid) > 0})
    lsof = Path("/usr/sbin/lsof")
    if os.name == "nt" or not unique_pids or not lsof.exists():
        return {}
    try:
        result = subprocess.run(
            [str(lsof), "-a", "-d", "cwd", "-p", ",".join(str(pid) for pid in unique_pids), "-Fn"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return {}
    current_pid: int | None = None
    found: dict[int, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("p") and line[1:].isdigit():
            current_pid = int(line[1:])
        elif line.startswith("n") and current_pid is not None:
            found[current_pid] = line[1:]
    return found


def mt5_process_cwd_matches_snapshot(cwd: str, file_path: Path | None) -> bool:
    if not cwd or file_path is None:
        return False
    normalized_cwd = str(Path(cwd)).replace("\\", "/").rstrip("/")
    normalized_file = str(file_path).replace("\\", "/")
    return bool(normalized_cwd and (normalized_file == normalized_cwd or normalized_file.startswith(f"{normalized_cwd}/")))


def is_mt5_host_process_row(row: str) -> bool:
    """Return true only for actual MT5/Wine terminal processes, not path mentions.

    Background maintenance commands can contain paths such as
    ``.../Program Files/MetaTrader 5/MQL5/Files`` in their arguments. Matching the
    whole ps row for "metatrader" makes those Python helpers look like running MT5
    terminals, which hides the real stale-dashboard root cause.
    """
    text = str(row or "").strip()
    if not text:
        return False
    if os.name == "nt":
        return bool(re.search(r"\bterminal64\.exe\b", text, re.I))

    match = re.match(r"\s*(?P<pid>\d+)\s+(?P<comm>\S+)\s+(?P<args>.*)$", text)
    if not match:
        return False
    comm = Path(match.group("comm")).name.lower()
    args = match.group("args")
    if comm in {"screen", "login", "env", "zsh", "bash", "sh", "python", "python3", "rg", "grep", "perl"}:
        return False
    if re.search(r"\bterminal64(?:\.exe)?\b", comm, re.I):
        return True

    # macOS `ps -axo pid=,comm=,args=` truncates `comm` at the first space in
    # application paths.  MetaQuotes Wine therefore appears as `/Users/.../App`
    # even though `args` contains the real wine64-preloader executable followed
    # by `C:\\Program Files\\MetaTrader 5\\terminal64.exe`.  Require both the
    # Wine host and a bounded terminal executable argument so helper processes,
    # maintenance scripts, and plain dashboard-path mentions cannot become
    # false-positive MT5 terminals.
    normalized_args = args.replace("\\", "/")
    wine_host = bool(
        re.search(
            r"(?:^|[\s/])(wine64(?:-preloader)?|wine-preloader)(?=\s|$)",
            normalized_args,
            re.I,
        )
    )
    terminal_argument = bool(
        re.search(
            r"(?:^|[\s/])terminal64\.exe(?=\s|$)",
            normalized_args,
            re.I,
        )
    )
    return wine_host and terminal_argument


def attach_host_process_freshness(freshness: dict[str, Any], host_process: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(freshness)
    if (
        freshness.get("stale") is True
        and host_process.get("terminalProcessDetected") is False
        and host_process.get("status") in {"MISSING", "PROCESS_SCAN_DISABLED", "PROCESS_SCAN_FAILED"}
    ):
        blockers = list(enriched.get("blockers") or [])
        if "mt5_terminal_process_missing" not in blockers:
            blockers.append("mt5_terminal_process_missing")
        enriched["blockers"] = blockers
        if host_process.get("status") == "MISSING":
            enriched["nextAction"] = (
                "Restore the MT5 terminal/EA dashboard writer process and refresh QuantGod_Dashboard.json before using live account state."
            )
        enriched["hostProcessStatus"] = host_process.get("status")
        enriched["terminalProcessDetected"] = False
    return enriched


def stale_collection_payload(
    kind: str,
    symbol: str,
    stat: os.stat_result | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    age = evidence.get("ageSeconds") if isinstance(evidence, dict) else ea_snapshot_age_seconds(stat)
    max_age = ea_snapshot_max_age_seconds()
    return {
        "count": 0,
        "symbol": normalize_symbol_filter(symbol),
        "items": [],
        "stale": True,
        "staleSuppressed": True,
        "kind": kind,
        "ageSeconds": round(age, 3) if age is not None else None,
        "maxAgeSeconds": max_age,
        "reason": "EA snapshot is stale; suppressing openTrades/pendingOrders so old positions are not shown as live.",
    }


def missing_collection_payload(kind: str, symbol: str) -> dict[str, Any]:
    return {
        "count": 0,
        "symbol": normalize_symbol_filter(symbol),
        "items": [],
        "stale": True,
        "missing": True,
        "staleSuppressed": True,
        "kind": kind,
        "ageSeconds": None,
        "maxAgeSeconds": ea_snapshot_max_age_seconds(),
        "reason": "EA dashboard snapshot is missing; suppressing openTrades/pendingOrders so absent evidence is not shown as live.",
    }


def read_usdjpy_rsi_entry_diagnostics() -> tuple[dict[str, Any] | None, Path | None, dict[str, Any] | None]:
    found: list[tuple[float, Path, dict[str, Any]]] = []
    parse_errors: list[dict[str, str]] = []
    for directory in runtime_dir_candidates():
        file_path = directory / "QuantGod_USDJPYRsiEntryDiagnostics.json"
        if not file_path.exists():
            continue
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8").lstrip("\ufeff"))
            stat = file_path.stat()
            found.append((stat.st_mtime, file_path, payload))
        except Exception as exc:
            parse_errors.append({"path": str(file_path), "error": str(exc)})
    if found:
        _, file_path, payload = sorted(found, key=lambda item: item[0], reverse=True)[0]
        return payload, file_path, None
    if parse_errors:
        return None, None, {"parseErrors": parse_errors}
    return None, None, None


def merge_usdjpy_rsi_entry_diagnostics(
    payload: dict[str, Any],
    dashboard: dict[str, Any] | None = None,
) -> None:
    diagnostics, file_path, read_error = read_usdjpy_rsi_entry_diagnostics()
    source_type = "standalone_file"
    if not diagnostics and isinstance(dashboard, dict):
        embedded = dashboard.get("usdJpyRsiEntryDiagnostics")
        if isinstance(embedded, dict) and embedded:
            diagnostics = embedded
            file_path = None
            source_type = "dashboard_embedded"
    if diagnostics:
        payload["usdJpyRsiEntryDiagnostics"] = diagnostics
        source: dict[str, Any] = {"type": source_type}
        if file_path:
            stat = file_path.stat()
            source.update(
                {
                    "file": str(file_path),
                    "mtimeIso": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
        payload["usdJpyRsiEntryDiagnosticsSource"] = source
    elif read_error:
        payload["usdJpyRsiEntryDiagnosticsSource"] = {"type": "read_error", "readError": read_error}


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def first_present(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return default


def find_ea_symbol_row(dashboard: dict[str, Any], symbol: str = "") -> dict[str, Any]:
    symbol = normalize_symbol_filter(symbol) or normalize_symbol_filter(dashboard.get("watchlist", ""))
    rows = dashboard.get("symbols") if isinstance(dashboard.get("symbols"), list) else []
    if symbol:
        for row in rows:
            if isinstance(row, dict) and str(row.get("symbol", "")).lower() == symbol.lower():
                return row
    market = dashboard.get("market") if isinstance(dashboard.get("market"), dict) else {}
    if market and (not symbol or str(market.get("symbol", "")).lower() == symbol.lower()):
        return dict(market)
    if symbol:
        return {}
    return rows[0] if rows and isinstance(rows[0], dict) else {}


def build_connection_state(
    *,
    runtime: dict[str, Any],
    terminal: dict[str, Any],
    account: dict[str, Any] | None,
    snapshot_fresh: bool,
    process_running: bool | None = None,
) -> dict[str, Any]:
    """Build connection truth without treating stored identity as authorization.

    ``accountIdentityPresent`` only says that a login/server identity is visible
    in the snapshot.  Current authorization additionally requires a confirmed
    broker session.  The legacy fields remain in the response, while the new
    names make writer/process/session evidence explicit for API consumers.
    """

    terminal_value = runtime.get("terminalConnected")
    terminal_connected = terminal_value if isinstance(terminal_value, bool) else terminal.get("connected") is True
    broker_value = runtime.get("brokerSessionConnected")
    if not isinstance(broker_value, bool):
        broker_value = runtime.get("brokerConnected")
    broker_session_connected = broker_value if isinstance(broker_value, bool) else terminal_connected

    identity_value = runtime.get("accountIdentityPresent")
    if isinstance(identity_value, bool):
        account_identity_present = identity_value
    else:
        account_identity_present = bool(
            account
            and to_int(first_present(account, "login", "number", default=0)) > 0
            and str(first_present(account, "server", default="")).strip()
        )

    account_value = runtime.get("accountAuthorized")
    if isinstance(account_value, bool):
        authorization_evidence = account_value
    else:
        # Compatibility for older EA snapshots: identity alone is never enough.
        # A current broker session is the additional authorization evidence.
        authorization_evidence = broker_session_connected and account_identity_present
    account_authorized = bool(
        authorization_evidence
        and broker_session_connected
        and account_identity_present
    )

    if process_running is None:
        process_value = runtime.get("processRunning")
        process_running = process_value if isinstance(process_value, bool) else terminal_connected

    operational_connected = terminal_connected and broker_session_connected and account_authorized
    return {
        # Compatibility fields retained for existing clients.
        "terminalConnected": terminal_connected,
        "brokerConnected": broker_session_connected,
        "accountAuthorized": account_authorized,
        "operationalConnected": operational_connected,
        "snapshotFresh": snapshot_fresh,
        # Explicit v2 semantics.
        "writerFresh": snapshot_fresh,
        "processRunning": bool(process_running),
        "brokerSessionConnected": broker_session_connected,
        "accountIdentityPresent": account_identity_present,
        "readReady": operational_connected and snapshot_fresh,
        "semantics": "EXPLICIT_CONNECTION_EVIDENCE_V2",
    }


def ea_terminal_payload(dashboard: dict[str, Any], file_path: Path | None) -> dict[str, Any]:
    runtime = dashboard.get("runtime") if isinstance(dashboard.get("runtime"), dict) else {}
    return {
        # Never reuse the legacy aggregate `connected` flag as terminal proof;
        # older snapshots must provide terminalConnected explicitly.
        "connected": runtime.get("terminalConnected") is True,
        "tradeAllowed": bool(runtime.get("terminalTradeAllowed", runtime.get("tradeAllowed", False))),
        "dllsAllowed": bool(runtime.get("dllAllowed", False)),
        "name": "HFM MetaTrader 5 EA Snapshot",
        "company": "HF Markets",
        "path": str(file_path.parents[2]) if file_path and len(file_path.parents) >= 3 else "",
        "dataPath": str(file_path.parents[1]) if file_path and len(file_path.parents) >= 2 else "",
        "commonDataPath": "",
        "codepage": 0,
        "maxBars": 0,
    }


def ea_account_payload(dashboard: dict[str, Any]) -> dict[str, Any] | None:
    account = dashboard.get("account") if isinstance(dashboard.get("account"), dict) else {}
    if not account:
        return None
    runtime = dashboard.get("runtime") if isinstance(dashboard.get("runtime"), dict) else {}
    return {
        "login": to_int(first_present(account, "number", "login", default=0)),
        "server": first_present(account, "server", default=""),
        "name": first_present(account, "name", default=""),
        "currency": first_present(account, "currency", default=""),
        "company": "HF Markets",
        "balance": to_float(first_present(account, "balance", "startingBalance", default=0.0)),
        "equity": to_float(first_present(account, "equity", "balance", default=0.0)),
        "profit": to_float(first_present(account, "profit", default=0.0)),
        "margin": to_float(first_present(account, "margin", default=0.0)),
        "marginFree": to_float(first_present(account, "freeMargin", "marginFree", default=0.0)),
        "marginLevel": to_float(first_present(account, "marginLevel", default=0.0)),
        "leverage": to_int(first_present(account, "leverage", default=0)),
        "tradeAllowed": bool(runtime.get("accountTradeAllowed", runtime.get("tradeAllowed", False))),
        "tradeExpert": bool(runtime.get("accountExpertTradeAllowed", runtime.get("programTradeAllowed", False))),
    }


def ea_position_price_current(dashboard: dict[str, Any], symbol: str, trade_type: str) -> float:
    row = find_ea_symbol_row(dashboard, symbol)
    if trade_type.lower() == "sell":
        return to_float(row.get("ask", 0.0))
    return to_float(row.get("bid", 0.0))


def ea_positions_payload(dashboard: dict[str, Any], symbol: str = "") -> dict[str, Any]:
    symbol = normalize_symbol_filter(symbol)
    rows = dashboard.get("openTrades") if isinstance(dashboard.get("openTrades"), list) else []
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_symbol = str(row.get("symbol", ""))
        if symbol and row_symbol.lower() != symbol.lower():
            continue
        trade_type = str(row.get("type", "")).lower() or str(row.get("direction", "")).lower()
        price_current = first_present(row, "priceCurrent", "currentPrice", default=None)
        items.append(
            {
                "ticket": to_int(first_present(row, "ticket", "order", default=0)),
                "identifier": to_int(first_present(row, "positionId", "identifier", "ticket", default=0)),
                "symbol": row_symbol,
                "type": trade_type,
                "volume": to_float(first_present(row, "actualLots", "lots", "volume", default=0.0)),
                "priceOpen": to_float(first_present(row, "openPrice", "priceOpen", default=0.0)),
                "priceCurrent": to_float(price_current)
                if price_current is not None
                else ea_position_price_current(dashboard, row_symbol, trade_type),
                "sl": to_float(first_present(row, "sl", "stopLoss", default=0.0)),
                "tp": to_float(first_present(row, "tp", "takeProfit", default=0.0)),
                "profit": to_float(first_present(row, "actualProfit", "profit", default=0.0)),
                "swap": to_float(first_present(row, "swap", default=0.0)),
                "magic": to_int(first_present(row, "magic", default=520001)),
                "comment": first_present(row, "comment", default=""),
                "strategy": first_present(row, "strategy", default=""),
                "source": first_present(row, "source", default=""),
                "entryRegime": first_present(row, "entryRegime", "regime", default=""),
                "regimeTimeframe": first_present(row, "regimeTimeframe", default=""),
                "time": 0,
                "timeIso": "",
            }
        )
    return {"count": len(items), "symbol": symbol, "items": items}


def ea_orders_payload(dashboard: dict[str, Any], symbol: str = "") -> dict[str, Any]:
    symbol = normalize_symbol_filter(symbol)
    rows = dashboard.get("pendingOrders") if isinstance(dashboard.get("pendingOrders"), list) else []
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_symbol = str(row.get("symbol", ""))
        if symbol and row_symbol.lower() != symbol.lower():
            continue
        items.append(
            {
                "ticket": to_int(first_present(row, "ticket", "order", default=0)),
                "symbol": row_symbol,
                "type": str(first_present(row, "type", default="")).lower(),
                "volumeInitial": to_float(first_present(row, "volumeInitial", "lots", "volume", default=0.0)),
                "volumeCurrent": to_float(first_present(row, "volumeCurrent", "lots", "volume", default=0.0)),
                "priceOpen": to_float(first_present(row, "priceOpen", "openPrice", default=0.0)),
                "priceCurrent": to_float(first_present(row, "priceCurrent", default=0.0)),
                "sl": to_float(first_present(row, "sl", "stopLoss", default=0.0)),
                "tp": to_float(first_present(row, "tp", "takeProfit", default=0.0)),
                "magic": to_int(first_present(row, "magic", default=520001)),
                "comment": first_present(row, "comment", default=""),
                "timeSetup": 0,
                "timeSetupIso": "",
            }
        )
    return {"count": len(items), "symbol": symbol, "items": items}


def ea_symbols_payload(
    dashboard: dict[str, Any],
    group: str = "*",
    query: str = "",
    limit: int = DEFAULT_SYMBOL_LIMIT,
) -> dict[str, Any]:
    query_lower = str(query or "").strip().lower()
    rows = dashboard.get("symbols") if isinstance(dashboard.get("symbols"), list) else []
    if not rows and isinstance(dashboard.get("market"), dict):
        rows = [dashboard["market"]]
    limit = max(0, min(int(limit or DEFAULT_SYMBOL_LIMIT), MAX_SYMBOL_LIMIT))
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(first_present(row, "symbol", "name", default=""))
        text = " ".join(str(row.get(key, "")) for key in ("symbol", "role", "status", "tradeMode")).lower()
        if query_lower and query_lower not in text:
            continue
        spread = to_float(first_present(row, "spread", default=0.0))
        items.append(
            {
                "name": name,
                "description": f"{name} HFM EA snapshot".strip(),
                "path": "EA_SNAPSHOT",
                "visible": True,
                "selected": True,
                "currencyBase": name[:3] if len(name) >= 6 else "",
                "currencyProfit": name[3:6] if len(name) >= 6 else "",
                "digits": 3 if "JPY" in name.upper() else 5,
                "point": 0.001 if "JPY" in name.upper() else 0.00001,
                "spread": spread,
                "tradeMode": first_present(row, "tradeMode", default=""),
                "volumeMin": 0.01,
                "volumeMax": 200.0,
                "volumeStep": 0.01,
                "status": first_present(row, "status", default=""),
                "entryTradeAllowed": bool(row.get("entryTradeAllowed", False)),
            }
        )
    returned = items[:limit] if limit else []
    return {
        "group": group,
        "query": query_lower,
        "count": len(items),
        "returned": len(returned),
        "truncated": bool(limit and len(items) > len(returned)),
        "items": returned,
    }


def ea_quote_payload(dashboard: dict[str, Any], symbol: str) -> dict[str, Any]:
    symbol = normalize_symbol_filter(symbol) or normalize_symbol_filter(dashboard.get("watchlist", ""))
    row = find_ea_symbol_row(dashboard, symbol)
    row_symbol = str(first_present(row, "symbol", default=symbol))
    if not row or (symbol and row_symbol.lower() != symbol.lower()):
        return {"ok": False, "error": f"symbol not found in EA snapshot: {symbol}", "symbol": symbol}
    bid = to_float(row.get("bid", 0.0))
    ask = to_float(row.get("ask", 0.0))
    point = 0.001 if "JPY" in row_symbol.upper() else 0.00001
    spread = to_float(first_present(row, "spread", default=((ask - bid) / point if point and ask and bid else 0.0)))
    return {
        "ok": True,
        "symbol": row_symbol,
        "visible": True,
        "digits": 3 if "JPY" in row_symbol.upper() else 5,
        "point": point,
        "bid": bid,
        "ask": ask,
        "last": 0.0,
        "volume": 0,
        "spreadPoints": round(spread, 2),
        "time": 0,
        "timeIso": "",
        "tickAgeSeconds": to_int(row.get("tickAgeSeconds", 0)),
        "tradeMode": first_present(row, "tradeMode", default=""),
    }


def build_ea_snapshot_fallback(args: argparse.Namespace) -> dict[str, Any] | None:
    dashboard, file_path, read_error = read_ea_dashboard_snapshot()
    if not dashboard:
        return None
    endpoint = args.endpoint
    payload = base_payload(endpoint)
    stat = file_path.stat() if file_path else None
    snapshot_evidence = ea_snapshot_evidence(file_path, dashboard, stat)
    snapshot_age = snapshot_evidence.get("ageSeconds")
    snapshot_max_age = ea_snapshot_max_age_seconds()
    snapshot_fresh = ea_snapshot_fresh(stat, snapshot_evidence)
    host_process = detect_mt5_host_process(file_path)
    freshness = attach_host_process_freshness(
        ea_snapshot_freshness(file_path, stat, snapshot_evidence),
        host_process,
    )
    runtime = dict(dashboard.get("runtime")) if isinstance(dashboard.get("runtime"), dict) else {}
    terminal = ea_terminal_payload(dashboard, file_path)
    account = ea_account_payload(dashboard)
    connection = build_connection_state(
        runtime=runtime,
        terminal=terminal,
        account=account,
        snapshot_fresh=snapshot_fresh,
        process_running=host_process.get("targetProcessDetected") is True,
    )
    terminal["connected"] = connection["terminalConnected"]
    runtime.update(
        {
            "connected": connection["operationalConnected"],
            "terminalConnected": connection["terminalConnected"],
            "brokerConnected": connection["brokerConnected"],
            "brokerSessionConnected": connection["brokerSessionConnected"],
            "accountAuthorized": connection["accountAuthorized"],
            "accountIdentityPresent": connection["accountIdentityPresent"],
            "writerFresh": connection["writerFresh"],
            "processRunning": connection["processRunning"],
            "connectionState": connection,
        }
    )
    terminal.update(
        {
            "hostProcessStatus": host_process.get("status"),
            "hostProcessDetected": bool(host_process.get("terminalProcessDetected")),
            "targetHostProcessDetected": bool(host_process.get("targetProcessDetected")),
        }
    )
    payload.update(
        {
            "mode": "MT5_READONLY_BRIDGE_V1_EA_SNAPSHOT_FALLBACK",
            "status": "EA_SNAPSHOT" if snapshot_fresh else "STALE_EA_SNAPSHOT",
            "bridgeStatus": "MT5_PYTHON_UNAVAILABLE_EA_SNAPSHOT_FALLBACK",
            "terminal": terminal,
            "hostProcess": host_process,
            "account": account,
            "runtime": runtime,
            "connection": connection,
            "watchlist": dashboard.get("watchlist", ""),
            "market": dashboard.get("market", {}),
            "snapshotFresh": snapshot_fresh,
            "source": {
                "type": "hfm_ea_dashboard_snapshot",
                "file": str(file_path) if file_path else "",
                "mtimeIso": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
                if stat
                else "",
                "ageSeconds": round(snapshot_age, 3) if snapshot_age is not None else None,
                "maxAgeSeconds": snapshot_max_age,
                "fresh": snapshot_fresh,
                "readError": read_error,
                "freshnessBasis": "oldest_writer_evidence",
                "oldestEvidenceSource": snapshot_evidence.get("oldestSource", ""),
                "evidenceSources": snapshot_evidence.get("evidenceSources", []),
                "dashboardTimestamp": snapshot_evidence.get("dashboardTimestamp", ""),
                "dashboardTimestampIso": snapshot_evidence.get("dashboardTimestampIso", ""),
                "heartbeatMtimeIso": snapshot_evidence.get("heartbeatMtimeIso", ""),
            },
            "_freshness": freshness,
        }
    )
    if not snapshot_fresh:
        payload["warning"] = "ea_snapshot_stale_positions_and_orders_suppressed"

    if endpoint == "status":
        return payload
    if endpoint == "account":
        if not payload.get("account"):
            payload["status"] = "NO_ACCOUNT"
        elif connection["readReady"]:
            payload["status"] = "CONNECTED"
        elif not snapshot_fresh:
            payload["status"] = "STALE_EA_SNAPSHOT"
        else:
            payload["status"] = "ACCOUNT_AVAILABLE_NOT_CONNECTED"
        return payload
    if endpoint == "positions":
        payload["positions"] = (
            ea_positions_payload(dashboard, args.symbol)
            if snapshot_fresh
            else stale_collection_payload("positions", args.symbol, stat, snapshot_evidence)
        )
        return payload
    if endpoint == "orders":
        payload["orders"] = (
            ea_orders_payload(dashboard, args.symbol)
            if snapshot_fresh
            else stale_collection_payload("orders", args.symbol, stat, snapshot_evidence)
        )
        return payload
    if endpoint == "symbols":
        payload["symbols"] = ea_symbols_payload(dashboard, args.group, args.query, args.limit)
        return payload
    if endpoint == "quote":
        quote = ea_quote_payload(dashboard, args.symbol)
        payload["quote"] = quote
        payload["ok"] = bool(quote.get("ok"))
        if not payload["ok"]:
            payload["error"] = quote.get("error", "quote unavailable")
        return payload
    if endpoint == "snapshot":
        payload["positions"] = (
            ea_positions_payload(dashboard, args.symbol)
            if snapshot_fresh
            else stale_collection_payload("positions", args.symbol, stat, snapshot_evidence)
        )
        payload["orders"] = (
            ea_orders_payload(dashboard, args.symbol)
            if snapshot_fresh
            else stale_collection_payload("orders", args.symbol, stat, snapshot_evidence)
        )
        payload["symbols"] = ea_symbols_payload(dashboard, args.group, args.query, args.symbols_limit)
        payload["quote"] = ea_quote_payload(dashboard, args.symbol) if args.symbol else None
        merge_usdjpy_rsi_entry_diagnostics(payload, dashboard)
        return payload
    return payload


def build_missing_ea_snapshot_payload(
    args: argparse.Namespace,
    *,
    python_bridge_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint = args.endpoint
    host_process = detect_mt5_host_process(None)
    freshness = ea_snapshot_missing_freshness(host_process)
    payload = base_payload(endpoint)
    payload.update(
        {
            "ok": False,
            "mode": "MT5_READONLY_BRIDGE_V1_EA_SNAPSHOT_MISSING",
            "status": "MISSING_EA_SNAPSHOT",
            "statusZh": "MT5 dashboard 快照缺失",
            "bridgeStatus": "MT5_PYTHON_UNAVAILABLE_EA_SNAPSHOT_MISSING",
            "error": "EA dashboard snapshot is missing",
            "terminal": {
                "connected": False,
                "tradeAllowed": False,
                "dllsAllowed": False,
                "name": "HFM MetaTrader 5 EA Snapshot",
                "company": "HF Markets",
                "path": "",
                "dataPath": "",
                "commonDataPath": "",
                "codepage": 0,
                "maxBars": 0,
                "hostProcessStatus": host_process.get("status"),
                "hostProcessDetected": bool(host_process.get("terminalProcessDetected")),
                "targetHostProcessDetected": bool(host_process.get("targetProcessDetected")),
            },
            "hostProcess": host_process,
            "account": None,
            "runtime": {
                "connected": False,
                "terminalConnected": False,
                "brokerConnected": False,
                "brokerSessionConnected": False,
                "accountAuthorized": False,
                "accountIdentityPresent": False,
                "writerFresh": False,
                "processRunning": False,
            },
            "connection": {
                "terminalConnected": False,
                "brokerConnected": False,
                "brokerSessionConnected": False,
                "accountAuthorized": False,
                "accountIdentityPresent": False,
                "operationalConnected": False,
                "snapshotFresh": False,
                "writerFresh": False,
                "processRunning": False,
                "readReady": False,
                "semantics": "EXPLICIT_CONNECTION_EVIDENCE_V2",
            },
            "watchlist": "",
            "market": {},
            "snapshotFresh": False,
            "source": {
                "type": "hfm_ea_dashboard_snapshot",
                "file": "",
                "mtimeIso": "",
                "ageSeconds": None,
                "maxAgeSeconds": ea_snapshot_max_age_seconds(),
                "fresh": False,
                "missing": True,
                "searchedDirs": [str(path) for path in runtime_dir_candidates()],
            },
            "_freshness": freshness,
            "warning": "ea_snapshot_missing_positions_and_orders_suppressed",
        }
    )
    if python_bridge_error:
        payload["pythonBridgeError"] = python_bridge_error.get("error", "")
        payload["pythonBridgeDetail"] = python_bridge_error.get("detail", "")

    if endpoint == "positions":
        payload["positions"] = missing_collection_payload("positions", args.symbol)
    elif endpoint == "orders":
        payload["orders"] = missing_collection_payload("orders", args.symbol)
    elif endpoint == "symbols":
        payload["symbols"] = {
            "group": args.group,
            "query": args.query,
            "count": 0,
            "returned": 0,
            "truncated": False,
            "items": [],
            "missing": True,
        }
    elif endpoint == "quote":
        payload["quote"] = {
            "ok": False,
            "symbol": normalize_symbol_filter(args.symbol),
            "error": "EA dashboard snapshot is missing",
            "missing": True,
        }
    elif endpoint == "snapshot":
        payload["positions"] = missing_collection_payload("positions", args.symbol)
        payload["orders"] = missing_collection_payload("orders", args.symbol)
        payload["symbols"] = {
            "group": args.group,
            "query": args.query,
            "count": 0,
            "returned": 0,
            "truncated": False,
            "items": [],
            "missing": True,
        }
        payload["quote"] = None
    return payload


def maybe_asdict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    if isinstance(value, dict):
        return dict(value)
    return {}


def safe_last_error(mt5: Any) -> Any:
    try:
        return mt5.last_error()
    except Exception:
        return None


def initialize_mt5(mt5: Any, terminal_path: str = "") -> tuple[bool, Any]:
    try:
        if terminal_path:
            return bool(mt5.initialize(path=terminal_path)), safe_last_error(mt5)
        return bool(mt5.initialize()), safe_last_error(mt5)
    except Exception as exc:
        return False, str(exc)


def terminal_payload(mt5: Any) -> dict[str, Any]:
    info = maybe_asdict(mt5.terminal_info())
    if not info:
        return {"connected": False}
    return {
        "connected": bool(info.get("connected")),
        "tradeAllowed": bool(info.get("trade_allowed")),
        "dllsAllowed": bool(info.get("dlls_allowed")),
        "name": info.get("name", ""),
        "company": info.get("company", ""),
        "path": info.get("path", ""),
        "dataPath": info.get("data_path", ""),
        "commonDataPath": info.get("commondata_path", ""),
        "codepage": info.get("codepage", 0),
        "maxBars": info.get("maxbars", 0),
    }


def account_payload(mt5: Any) -> dict[str, Any] | None:
    info = maybe_asdict(mt5.account_info())
    if not info:
        return None
    return {
        "login": info.get("login", 0),
        "server": info.get("server", ""),
        "name": info.get("name", ""),
        "currency": info.get("currency", ""),
        "company": info.get("company", ""),
        "balance": info.get("balance", 0.0),
        "equity": info.get("equity", 0.0),
        "profit": info.get("profit", 0.0),
        "margin": info.get("margin", 0.0),
        "marginFree": info.get("margin_free", 0.0),
        "marginLevel": info.get("margin_level", 0.0),
        "leverage": info.get("leverage", 0),
        "tradeAllowed": bool(info.get("trade_allowed")),
        "tradeExpert": bool(info.get("trade_expert")),
    }


def status_payload(mt5: Any, endpoint: str = "status") -> dict[str, Any]:
    payload = base_payload(endpoint)
    account = account_payload(mt5)
    terminal = terminal_payload(mt5)
    connection = build_connection_state(
        runtime={},
        terminal=terminal,
        account=account,
        snapshot_fresh=True,
        process_running=True,
    )
    payload.update(
        {
            "status": "CONNECTED" if connection["operationalConnected"] else "INITIALIZED",
            "terminal": terminal,
            "account": account,
            "runtime": {
                "connected": connection["operationalConnected"],
                "terminalConnected": connection["terminalConnected"],
                "brokerConnected": connection["brokerConnected"],
                "brokerSessionConnected": connection["brokerSessionConnected"],
                "accountAuthorized": connection["accountAuthorized"],
                "accountIdentityPresent": connection["accountIdentityPresent"],
                "writerFresh": connection["writerFresh"],
                "processRunning": connection["processRunning"],
                "connectionState": connection,
            },
            "connection": connection,
            "snapshotFresh": True,
            "lastError": safe_last_error(mt5),
        }
    )
    return payload


def position_type_label(mt5: Any, value: Any) -> str:
    if value == getattr(mt5, "POSITION_TYPE_BUY", 0):
        return "buy"
    if value == getattr(mt5, "POSITION_TYPE_SELL", 1):
        return "sell"
    return str(value)


def order_type_label(mt5: Any, value: Any) -> str:
    mapping = {
        getattr(mt5, "ORDER_TYPE_BUY", -100): "buy",
        getattr(mt5, "ORDER_TYPE_SELL", -101): "sell",
        getattr(mt5, "ORDER_TYPE_BUY_LIMIT", -102): "buy_limit",
        getattr(mt5, "ORDER_TYPE_SELL_LIMIT", -103): "sell_limit",
        getattr(mt5, "ORDER_TYPE_BUY_STOP", -104): "buy_stop",
        getattr(mt5, "ORDER_TYPE_SELL_STOP", -105): "sell_stop",
        getattr(mt5, "ORDER_TYPE_BUY_STOP_LIMIT", -106): "buy_stop_limit",
        getattr(mt5, "ORDER_TYPE_SELL_STOP_LIMIT", -107): "sell_stop_limit",
    }
    return mapping.get(value, str(value))


def normalize_symbol_filter(symbol: str) -> str:
    return str(symbol or "").strip()


def get_positions(mt5: Any, symbol: str = "") -> dict[str, Any]:
    symbol = normalize_symbol_filter(symbol)
    raw_items = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if raw_items is None:
        raw_items = []
    items = []
    for item in raw_items:
        row = maybe_asdict(item)
        items.append(
            {
                "ticket": row.get("ticket", 0),
                "identifier": row.get("identifier", 0),
                "symbol": row.get("symbol", ""),
                "type": position_type_label(mt5, row.get("type")),
                "volume": row.get("volume", 0.0),
                "priceOpen": row.get("price_open", 0.0),
                "priceCurrent": row.get("price_current", 0.0),
                "sl": row.get("sl", 0.0),
                "tp": row.get("tp", 0.0),
                "profit": row.get("profit", 0.0),
                "swap": row.get("swap", 0.0),
                "magic": row.get("magic", 0),
                "comment": row.get("comment", ""),
                "time": row.get("time", 0),
                "timeIso": iso_from_timestamp(row.get("time")),
            }
        )
    return {"count": len(items), "symbol": symbol, "items": items}


def get_orders(mt5: Any, symbol: str = "") -> dict[str, Any]:
    symbol = normalize_symbol_filter(symbol)
    raw_items = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
    if raw_items is None:
        raw_items = []
    items = []
    for item in raw_items:
        row = maybe_asdict(item)
        items.append(
            {
                "ticket": row.get("ticket", 0),
                "symbol": row.get("symbol", ""),
                "type": order_type_label(mt5, row.get("type")),
                "volumeInitial": row.get("volume_initial", 0.0),
                "volumeCurrent": row.get("volume_current", 0.0),
                "priceOpen": row.get("price_open", 0.0),
                "priceCurrent": row.get("price_current", 0.0),
                "sl": row.get("sl", 0.0),
                "tp": row.get("tp", 0.0),
                "magic": row.get("magic", 0),
                "comment": row.get("comment", ""),
                "timeSetup": row.get("time_setup", 0),
                "timeSetupIso": iso_from_timestamp(row.get("time_setup")),
            }
        )
    return {"count": len(items), "symbol": symbol, "items": items}


def get_symbols(mt5: Any, group: str = "*", query: str = "", limit: int = DEFAULT_SYMBOL_LIMIT) -> dict[str, Any]:
    group = str(group or "*").strip() or "*"
    query = str(query or "").strip().lower()
    limit = max(0, min(int(limit or DEFAULT_SYMBOL_LIMIT), MAX_SYMBOL_LIMIT))
    raw_items = mt5.symbols_get(group=group)
    if raw_items is None:
        raw_items = []
    items = []
    for item in raw_items:
        row = maybe_asdict(item)
        text = " ".join(str(row.get(key, "")) for key in ("name", "description", "path")).lower()
        if query and query not in text:
            continue
        items.append(
            {
                "name": row.get("name", ""),
                "description": row.get("description", ""),
                "path": row.get("path", ""),
                "visible": bool(row.get("visible")),
                "selected": bool(row.get("select")),
                "currencyBase": row.get("currency_base", ""),
                "currencyProfit": row.get("currency_profit", ""),
                "digits": row.get("digits", 0),
                "point": row.get("point", 0.0),
                "spread": row.get("spread", 0),
                "tradeMode": row.get("trade_mode", 0),
                "tradeCalcMode": row.get("trade_calc_mode", 0),
                "tradeContractSize": row.get("trade_contract_size", 0.0),
                "tradeTickSize": row.get("trade_tick_size", row.get("point", 0.0)),
                "tradeTickValue": row.get("trade_tick_value", 0.0),
                "volumeMin": row.get("volume_min", 0.0),
                "volumeMax": row.get("volume_max", 0.0),
                "volumeStep": row.get("volume_step", 0.0),
                "swapLong": row.get("swap_long", 0.0),
                "swapShort": row.get("swap_short", 0.0),
                "marginInitial": row.get("margin_initial", 0.0),
            }
        )
    returned = items[:limit] if limit else []
    return {
        "group": group,
        "query": query,
        "count": len(items),
        "returned": len(returned),
        "truncated": bool(limit and len(items) > len(returned)),
        "items": returned,
    }


def get_quote(mt5: Any, symbol: str) -> dict[str, Any]:
    symbol = normalize_symbol_filter(symbol)
    if not symbol:
        return {"ok": False, "error": "symbol is required", "symbol": ""}
    info = maybe_asdict(mt5.symbol_info(symbol))
    if not info:
        return {"ok": False, "error": f"symbol not found: {symbol}", "symbol": symbol}
    tick = maybe_asdict(mt5.symbol_info_tick(symbol))
    if not tick:
        return {
            "ok": False,
            "error": f"tick unavailable for {symbol}; add it to Market Watch in MT5 if needed",
            "symbol": symbol,
            "visible": bool(info.get("visible")),
        }
    point = float(info.get("point") or 0.0)
    bid = float(tick.get("bid") or 0.0)
    ask = float(tick.get("ask") or 0.0)
    spread_points = ((ask - bid) / point) if point and ask and bid else 0.0
    return {
        "ok": True,
        "symbol": symbol,
        "visible": bool(info.get("visible")),
        "digits": info.get("digits", 0),
        "point": point,
        "bid": bid,
        "ask": ask,
        "last": tick.get("last", 0.0),
        "volume": tick.get("volume", 0),
        "spreadPoints": round(spread_points, 2),
        "time": tick.get("time", 0),
        "timeIso": iso_from_timestamp(tick.get("time")),
    }


def build_endpoint_payload(mt5: Any, args: argparse.Namespace) -> dict[str, Any]:
    endpoint = args.endpoint
    payload = status_payload(mt5, endpoint=endpoint)

    if endpoint == "status":
        return payload
    if endpoint == "account":
        payload["account"] = account_payload(mt5)
        if not payload["account"]:
            payload["status"] = "NO_ACCOUNT"
        elif payload["connection"]["readReady"]:
            payload["status"] = "CONNECTED"
        else:
            payload["status"] = "ACCOUNT_AVAILABLE_NOT_CONNECTED"
        return payload
    if endpoint == "positions":
        payload["positions"] = get_positions(mt5, args.symbol)
        return payload
    if endpoint == "orders":
        payload["orders"] = get_orders(mt5, args.symbol)
        return payload
    if endpoint == "symbols":
        payload["symbols"] = get_symbols(mt5, args.group, args.query, args.limit)
        return payload
    if endpoint == "quote":
        quote = get_quote(mt5, args.symbol)
        payload["quote"] = quote
        payload["ok"] = bool(quote.get("ok"))
        if not payload["ok"]:
            payload["error"] = quote.get("error", "quote unavailable")
        return payload
    if endpoint == "snapshot":
        payload["positions"] = get_positions(mt5, args.symbol)
        payload["orders"] = get_orders(mt5, args.symbol)
        payload["symbols"] = get_symbols(mt5, args.group, args.query, args.symbols_limit)
        payload["quote"] = get_quote(mt5, args.symbol) if args.symbol else None
        merge_usdjpy_rsi_entry_diagnostics(payload)
        payload["status"] = "CONNECTED" if payload["connection"]["readReady"] else "INITIALIZED"
        return payload
    raise ValueError(f"unsupported endpoint: {endpoint}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QuantGod read-only MT5 bridge")
    parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), default="snapshot")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--group", default="*")
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=DEFAULT_SYMBOL_LIMIT)
    parser.add_argument("--symbols-limit", type=int, default=DEFAULT_SYMBOL_LIMIT)
    parser.add_argument("--terminal-path", default=os.environ.get("QG_MT5_TERMINAL_PATH", ""))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    mt5, error = load_mt5()
    if error:
        fallback = build_ea_snapshot_fallback(args)
        if fallback:
            fallback["pythonBridgeError"] = error.get("error", "")
            fallback["pythonBridgeDetail"] = error.get("detail", "")
            print(json.dumps(fallback, ensure_ascii=False, indent=2))
            return 0
        missing = build_missing_ea_snapshot_payload(args, python_bridge_error=error)
        print(json.dumps(missing, ensure_ascii=False, indent=2))
        return 0

    initialized, init_error = initialize_mt5(mt5, args.terminal_path)
    if not initialized:
        fallback = build_ea_snapshot_fallback(args)
        if fallback:
            fallback["pythonBridgeError"] = "MT5 initialize failed"
            fallback["pythonBridgeDetail"] = init_error
            print(json.dumps(fallback, ensure_ascii=False, indent=2))
            return 0
        payload = build_missing_ea_snapshot_payload(
            args,
            python_bridge_error=public_error("MT5 initialize failed", detail=init_error),
        )
        payload["bridgeStatus"] = "MT5_INITIALIZE_FAILED_EA_SNAPSHOT_MISSING"
        payload["terminalPath"] = args.terminal_path
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        payload = build_endpoint_payload(mt5, args)
    except Exception as exc:
        payload = public_error(f"MT5 read-only query failed: {exc}")
        payload["endpoint"] = args.endpoint
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
