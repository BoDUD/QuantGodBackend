"""Read-only run gate for the current champion tester/forward task."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from tools.auto_tester_window_guard import LOCK_NAME, evaluate_execution_gate
    from tools.champion_tester_forward_request import read_champion_tester_forward_request
    from tools.live_automation_readiness.forex_live12_rsi_tester_run_gate import _next_tester_window
except ModuleNotFoundError:  # pragma: no cover
    from auto_tester_window_guard import LOCK_NAME, evaluate_execution_gate
    from champion_tester_forward_request import read_champion_tester_forward_request
    from live_automation_readiness.forex_live12_rsi_tester_run_gate import _next_tester_window


REPORT_SCHEMA = "quantgod.champion_tester_run_gate.v1"
REPORT_PATH = Path("agent") / "QuantGod_ChampionTesterRunGate.json"

SAFETY = {
    "readOnly": True,
    "testerOnly": True,
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe_strs(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _terminal_recovery_action_zh(preferred_terminal_path: str = "") -> str:
    if preferred_terminal_path:
        return (
            f"未发现主 MT5 terminal64 进程；先恢复 {preferred_terminal_path} 并恢复 "
            "live dashboard 刷新，否则不能确认 live session freshness。"
        )
    return "未发现主 MT5 terminal64 进程；live dashboard 很可能不会继续刷新。"


def _terminal_recovery_required_action_zh(preferred_terminal_path: str = "") -> str:
    if preferred_terminal_path:
        return (
            f"先恢复主 MT5 terminal64 进程（优先: {preferred_terminal_path}）并恢复 "
            "dashboard freshness，再重建 tester gate。"
        )
    return "先恢复主 MT5 terminal64 进程并恢复 dashboard freshness，再重建 tester gate。"


def _drive_c_root(runtime_dir: Path) -> Path | None:
    runtime_dir = Path(runtime_dir)
    for item in (runtime_dir, *runtime_dir.parents):
        if item.name == "drive_c":
            return item
    candidate = runtime_dir / "drive_c"
    if candidate.exists():
        return candidate
    return None


def _startup_config_path(runtime_dir: Path) -> Path:
    drive_c = _drive_c_root(runtime_dir)
    if drive_c:
        return drive_c / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"
    return Path(runtime_dir) / "drive_c" / "qg" / "QuantGod_MT5_HFM_LiveSecondary_mac.ini"


def _primary_dashboard_path(runtime_dir: Path, explicit_dashboard_json: str = "") -> Path:
    if explicit_dashboard_json:
        return Path(explicit_dashboard_json)
    runtime_dashboard = Path(runtime_dir) / "QuantGod_Dashboard.json"
    if runtime_dashboard.exists():
        return runtime_dashboard
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
        / "QuantGod_Dashboard.json"
    )


def _account_from_dashboard(path: Path) -> dict[str, str]:
    dashboard = _read_json(path)
    account = _safe_dict(dashboard.get("account"))
    return {
        "number": str(account.get("number") or ""),
        "server": str(account.get("server") or ""),
    }


def _account_context(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "runtime" / "QuantGod_IsolatedTesterAccountContextStatus.json"
    status = _read_json(path)
    ready = bool(status.get("ready"))
    status_blockers = status.get("blockers") if isinstance(status.get("blockers"), list) else []
    blockers = [] if ready else (status_blockers or ["isolated_tester_account_context_not_ready"])
    return {
        "path": str(path),
        "exists": path.exists(),
        "ready": ready,
        "mode": status.get("mode", ""),
        "login": str(status.get("login") or ""),
        "server": str(status.get("server") or ""),
        "generatedAtIso": status.get("generatedAtIso", ""),
        "missingTarget": status.get("missingTarget") if isinstance(status.get("missingTarget"), list) else [],
        "blockers": blockers,
        "sensitiveAccountContextSyncRequired": bool(status.get("sensitiveAccountContextSyncRequired")),
        "strategyBlocked": bool(status.get("strategyBlocked")),
        "environmentBlocked": bool(status.get("environmentBlocked")),
        "nextActionZh": status.get("nextActionZh", ""),
    }


def _candidate_terminal_paths(preferred_terminal_path: Path | None = None) -> tuple[str, list[str]]:
    candidates: list[str] = []
    if preferred_terminal_path:
        candidates.append(str(preferred_terminal_path))
    root = (
        Path.home()
        / "Library"
        / "Application Support"
    )
    for path in sorted(
        root.glob("net.metaquotes.wine.metatrader5*/drive_c/Program Files/MetaTrader 5/terminal64.exe")
    ):
        text = str(path)
        if text not in candidates:
            candidates.append(text)
    preferred = candidates[0] if candidates else ""
    return preferred, candidates[:8]


def _supporting_process_evidence(
    preferred_terminal_path: Path | None = None,
    runtime_dir: Path | None = None,
    dashboard_path: Path | None = None,
) -> dict[str, Any]:
    preferred_terminal_path_text, candidate_terminal_paths = _candidate_terminal_paths(preferred_terminal_path)
    startup_config_path = _startup_config_path(runtime_dir or Path("."))
    dashboard_path_text = str(dashboard_path or "")
    read_only_verification_commands = [
        "ps ax | rg -i 'terminal64|dashboard_server.js|backend-api'",
    ]
    if preferred_terminal_path_text:
        read_only_verification_commands.append(f'ls "{preferred_terminal_path_text}"')
    if dashboard_path_text:
        read_only_verification_commands.append(f'ls "{dashboard_path_text}"')
    read_only_verification_commands.append(f'ls "{startup_config_path}"')
    try:
        proc = subprocess.run(
            ["ps", "ax"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "PROCESS_SCAN_UNAVAILABLE",
            "scanSupported": False,
            "error": str(exc),
            "mainMt5TerminalRunning": None,
            "isolatedTesterTerminalRunning": None,
            "dashboardServerRunning": None,
            "preferredTerminalPath": preferred_terminal_path_text,
            "candidateTerminalPaths": candidate_terminal_paths,
            "dashboardPath": dashboard_path_text,
            "startupConfigPath": str(startup_config_path),
            "startupConfigExists": startup_config_path.exists(),
            "readOnlyVerificationCommands": read_only_verification_commands,
            "blockers": [],
            "nextActionZh": "当前无法读取本机 MT5 进程证据；先按 dashboard freshness 继续诊断。",
        }
    text = proc.stdout or ""
    lowered = text.lower()
    main_terminal_running = "terminal64" in lowered and "hfm_mt5_tester_isolated" not in lowered
    isolated_tester_terminal_running = "terminal64" in lowered and "hfm_mt5_tester_isolated" in lowered
    dashboard_server_running = "dashboard_server.js" in lowered or "backend-api" in lowered
    blockers: list[str] = []
    if not main_terminal_running:
        blockers.append("mt5_terminal_process_missing")
    return {
        "status": "PROCESS_SCAN_READY",
        "scanSupported": True,
        "mode": "READ_ONLY_PROCESS_SCAN",
        "mainMt5TerminalRunning": main_terminal_running,
        "isolatedTesterTerminalRunning": isolated_tester_terminal_running,
        "dashboardServerRunning": dashboard_server_running,
        "preferredTerminalPath": preferred_terminal_path_text,
        "candidateTerminalPaths": candidate_terminal_paths,
        "preferredTerminalExists": bool(preferred_terminal_path_text and Path(preferred_terminal_path_text).exists()),
        "dashboardPath": dashboard_path_text,
        "startupConfigPath": str(startup_config_path),
        "startupConfigExists": startup_config_path.exists(),
        "readOnlyVerificationCommands": read_only_verification_commands,
        "blockers": blockers,
        "nextActionZh": (
            _terminal_recovery_action_zh(preferred_terminal_path_text)
            if blockers
            else "主 MT5 terminal64 进程存在，可继续按 dashboard freshness 判断 live session。"
        ),
    }


def _scheduler_from_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": {
            **_safe_dict(request.get("summary")),
            "runTerminal": False,
            "livePresetMutation": False,
        },
        "selectedTasks": _safe_list(request.get("selectedTasks")),
    }


def _top_level_readiness(gate: dict[str, Any], account_context: dict[str, Any]) -> dict[str, Any]:
    live_session = _safe_dict(gate.get("liveSession"))
    authorization_lock = _safe_dict(gate.get("authorizationLock"))
    window = _safe_dict(gate.get("window"))

    checks = [
        {
            "id": "authorization_lock_ready",
            "ok": bool(authorization_lock.get("ok")),
            "summaryZh": "隔离 tester lock 已授权。",
        },
        {
            "id": "dashboard_fresh",
            "ok": "live_dashboard_snapshot_stale" not in _safe_list(gate.get("blockers")),
            "summaryZh": "主 MT5 live dashboard 仍在 freshness 阈值内。",
        },
        {
            "id": "live_session_fresh",
            "ok": bool(live_session.get("ok")),
            "summaryZh": "live session 新鲜且无 live 持仓/保证金占用阻塞。",
        },
        {
            "id": "isolated_account_context_ready",
            "ok": bool(account_context.get("ready")),
            "summaryZh": "隔离 tester account context 已就绪。",
        },
        {
            "id": "sensitive_sync_cleared",
            "ok": not bool(account_context.get("sensitiveAccountContextSyncRequired")),
            "summaryZh": "敏感账户上下文同步阻塞已清空。",
        },
        {
            "id": "tester_window_open",
            "ok": bool(window.get("ok")),
            "summaryZh": "当前已进入允许的 Strategy Tester 时间窗口。",
        },
        {
            "id": "tester_can_run_now",
            "ok": bool(gate.get("canRunTerminal")),
            "summaryZh": "隔离 Strategy Tester 当前可启动。",
        },
    ]
    ok_count = sum(1 for item in checks if item["ok"])
    total_count = len(checks)
    blockers = _dedupe_strs(gate.get("blockers") if isinstance(gate.get("blockers"), list) else [])
    unmet_ids = [item["id"] for item in checks if not item["ok"]]
    summary_zh = (
        f"已满足 {ok_count}/{total_count} 项；未满足: {', '.join(unmet_ids)}。"
        if unmet_ids
        else f"已满足 {ok_count}/{total_count} 项；可进入隔离 tester 启动。"
    )
    return {
        "okCount": ok_count,
        "totalCount": total_count,
        "ratio": f"{ok_count}/{total_count}",
        "ok": ok_count == total_count,
        "checks": checks,
        "unmetCheckIds": unmet_ids,
        "blockers": blockers,
        "summaryZh": summary_zh,
    }


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _authorization_lock_refresh_guidance(next_window: dict[str, Any], now_utc: datetime | None = None) -> dict[str, Any]:
    max_ttl_minutes = 180
    now = now_utc or datetime.now(timezone.utc)
    start_at = _parse_iso(next_window.get("startJstIso"))
    if not start_at:
        return {
            "maxTtlMinutes": max_ttl_minutes,
            "refreshDueNow": False,
            "recommendedEarliestRefreshJstIso": "",
            "recommendedWindowStartJstIso": str(next_window.get("startJstIso") or ""),
            "minutesUntilRecommendedRefresh": None,
            "summaryZh": "tester-only lock 最长只覆盖 180 分钟；当前先恢复 terminal/dashboard，临近 tester window 再刷新 lock。",
            "nextRequiredActionZh": "临近 tester window 时再刷新 tester-only lock，避免短锁在开窗前再次过期。",
        }
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    earliest_refresh_at = start_at - timedelta(minutes=max_ttl_minutes)
    refresh_due_now = now >= earliest_refresh_at
    minutes_until_refresh = round((earliest_refresh_at - now).total_seconds() / 60.0, 1)
    if refresh_due_now:
        summary_zh = (
            f"已进入 tester-only lock 建议刷新时段；现在刷新可覆盖 {next_window.get('startJstIso')} "
            "附近的 tester window。"
        )
        next_required_action_zh = "现在可刷新 tester-only lock 草案和授权状态，覆盖当前窗口。"
    else:
        summary_zh = (
            f"tester-only lock 最长只覆盖 180 分钟；建议不早于 {earliest_refresh_at.isoformat()} 再刷新，"
            f"避免在 {next_window.get('startJstIso')} 开窗前再次过期。"
        )
        next_required_action_zh = (
            f"等待到不早于 {earliest_refresh_at.isoformat()} 再刷新 tester-only lock，避免短锁在开窗前再次过期。"
        )
    return {
        "maxTtlMinutes": max_ttl_minutes,
        "refreshDueNow": refresh_due_now,
        "recommendedEarliestRefreshJstIso": earliest_refresh_at.isoformat(),
        "recommendedWindowStartJstIso": str(next_window.get("startJstIso") or ""),
        "minutesUntilRecommendedRefresh": 0.0 if refresh_due_now else max(0.0, minutes_until_refresh),
        "summaryZh": summary_zh,
        "nextRequiredActionZh": next_required_action_zh,
    }


def _window_briefing(next_window: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    status = str(next_window.get("status") or "")
    residual_after_open = [item for item in blockers if item != "outside_strategy_tester_window"]
    summary_zh = "tester window 信息缺失。"
    if status == "open_now":
        summary_zh = (
            "tester window 已打开；开窗后仍需继续清理："
            f"{', '.join(residual_after_open)}。"
            if residual_after_open
            else "tester window 已打开。"
        )
    elif status == "waiting":
        minutes_until_start = next_window.get("minutesUntilStart")
        if isinstance(minutes_until_start, (int, float)):
            summary_zh = (
                f"距离下一次 tester window 还有 {minutes_until_start:.1f} 分钟；"
                f"开窗后仍需继续清理：{', '.join(residual_after_open)}。"
                if residual_after_open
                else f"距离下一次 tester window 还有 {minutes_until_start:.1f} 分钟。"
            )
        else:
            summary_zh = "当前不在 tester window 内。"
    elif status == "closed":
        summary_zh = (
            f"当前不在 tester window 内；开窗后仍需继续清理：{', '.join(residual_after_open)}。"
            if residual_after_open
            else "当前不在 tester window 内。"
        )
    return {
        "status": status or "unknown",
        "label": next_window.get("label"),
        "startJstIso": next_window.get("startJstIso"),
        "endJstIso": next_window.get("endJstIso"),
        "minutesUntilStart": next_window.get("minutesUntilStart"),
        "minutesUntilEnd": next_window.get("minutesUntilEnd"),
        "residualAfterWindowOpenCheckIds": residual_after_open,
        "summaryZh": summary_zh,
    }


def build_champion_tester_run_gate(
    runtime_dir: Path,
    *,
    primary_dashboard_json: str = "",
    allow_outside_window: bool = False,
    now_utc: datetime | None = None,
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    repo_root = _repo_root()
    request = read_champion_tester_forward_request(runtime)
    isolation = _safe_dict(request.get("testerIsolation"))
    isolated_tester_root = Path(str(isolation.get("isolatedTesterRoot") or repo_root / "runtime" / "HFM_MT5_Tester_Isolated"))
    isolated_runtime_dir = Path(str(isolation.get("isolatedRuntimeDir") or isolated_tester_root / "MQL5" / "Files"))
    live_dashboard_path = _primary_dashboard_path(runtime, primary_dashboard_json)
    live_runtime_dir = live_dashboard_path.parent
    preferred_terminal_path = live_dashboard_path.parents[2] / "terminal64.exe"
    account = _account_from_dashboard(live_dashboard_path)
    scheduler = _scheduler_from_request(request)
    queue_count = max(1, len(_safe_list(scheduler.get("selectedTasks"))))
    allowed_run_max_tasks = 1
    process_evidence = _supporting_process_evidence(
        preferred_terminal_path,
        runtime_dir=live_runtime_dir,
        dashboard_path=live_dashboard_path,
    )

    gate = evaluate_execution_gate(
        scheduler=scheduler,
        runtime_dir=live_runtime_dir,
        hfm_root=isolated_tester_root,
        repo_root=repo_root,
        lock_path=isolated_runtime_dir / LOCK_NAME,
        max_tasks=allowed_run_max_tasks,
        allow_outside_window=allow_outside_window,
        now_utc=now_utc,
        expected_login=account["number"],
        expected_server=account["server"],
        max_live_snapshot_age_minutes=30,
    )
    account_context = _account_context(repo_root)
    blockers = list(gate.get("blockers") if isinstance(gate.get("blockers"), list) else [])
    blockers.extend(account_context["blockers"])
    blockers.extend(_safe_list(process_evidence.get("blockers")))
    blockers = _dedupe_strs(blockers)
    gate = dict(gate)
    gate["blockers"] = blockers
    gate["canRunTerminal"] = bool(
        gate.get("canRunTerminal")
        and account_context["ready"]
        and not _safe_list(process_evidence.get("blockers"))
    )
    gate["status"] = "ready" if gate["canRunTerminal"] else "blocked"

    can_run = bool(gate.get("canRunTerminal"))
    status = "CHAMPION_TESTER_RUN_GATE_READY" if can_run else "CHAMPION_TESTER_RUN_GATE_BLOCKED"
    materialization = _safe_dict(request.get("materializationStatus"))
    selected_champion = _safe_dict(request.get("selectedChampion"))
    seed_id = str(selected_champion.get("seedId") or "UNKNOWN_CHAMPION")
    next_tester_window = _next_tester_window(now_utc)
    lock_refresh_guidance = _authorization_lock_refresh_guidance(next_tester_window, now_utc)
    readiness = _top_level_readiness(gate, account_context)
    window_briefing = _window_briefing(next_tester_window, blockers)
    summary_zh = (
        f"{seed_id} 隔离 tester 已就绪。"
        if can_run
        else f"{seed_id} 隔离 tester 仍被 blocker 卡住：{', '.join(blockers[:8]) or 'unknown'}。"
    )
    process_blockers = _safe_list(process_evidence.get("blockers"))
    if process_blockers:
        next_required_action_zh = _terminal_recovery_required_action_zh(
            str(process_evidence.get("preferredTerminalPath") or "")
        )
    elif "live_dashboard_snapshot_stale" in blockers:
        next_required_action_zh = "先恢复主 MT5 dashboard freshness，再重建 tester gate。"
    elif "authorization_lock_expired" in blockers:
        next_required_action_zh = str(lock_refresh_guidance.get("nextRequiredActionZh") or "")
    else:
        next_required_action_zh = f"先清空 tester gate blocker：{', '.join(str(item) for item in blockers[:8]) or 'unknown'}。"
    gate.setdefault("authorizationLock", {})
    if isinstance(gate["authorizationLock"], dict):
        gate["authorizationLock"]["refreshGuidance"] = dict(lock_refresh_guidance)
    payload = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "status": status,
        "statusZh": f"{seed_id} 隔离 Strategy Tester 启动条件已满足" if can_run else f"{seed_id} 隔离 Strategy Tester 启动条件未满足",
        "blockers": blockers,
        "summaryZh": summary_zh,
        "readiness": readiness,
        "windowBriefing": window_briefing,
        "authorizationLockRefreshGuidance": lock_refresh_guidance,
        "supportingProcessEvidence": process_evidence,
        "selectedChampion": selected_champion,
        "sourceTesterRequest": {
            "status": request.get("status"),
            "topCandidateId": _safe_dict(request.get("summary")).get("topCandidateId"),
            "candidateIds": _safe_dict(request.get("summary")).get("candidateIds", []),
            "queueCount": _safe_dict(request.get("summary")).get("queueCount"),
            "allowedRunMaxTasks": allowed_run_max_tasks,
            "materializationStatus": materialization,
            "isolatedPlanPath": request.get("isolatedPlanPath"),
        },
        "liveSessionSource": {
            "dashboardPath": str(live_dashboard_path),
            "dashboardExists": live_dashboard_path.exists(),
            "dashboardRuntimeDir": str(live_runtime_dir),
            "expectedLogin": account["number"],
            "expectedServer": account["server"],
        },
        "gate": gate,
        "testerAccountContext": account_context,
        "nextTesterWindow": next_tester_window,
        "decision": {
            "canRunTerminalHere": False,
            "canRunIsolatedTester": can_run,
            "canPromoteToLiveHere": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
            "nextRequiredActionZh": (
                "条件已满足时，仍需单独的受控 runner 才能启动 Strategy Tester；本 gate 不启动 terminal。"
                if can_run
                else next_required_action_zh
            ),
        },
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, payload)
    return payload


def read_champion_tester_run_gate(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = runtime / REPORT_PATH
    payload = _read_json(path)
    if payload:
        return build_champion_tester_run_gate(runtime, write=False)
    return build_champion_tester_run_gate(runtime, write=False)
