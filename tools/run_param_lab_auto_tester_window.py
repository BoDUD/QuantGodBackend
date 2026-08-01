#!/usr/bin/env python3
"""Guarded AUTO_TESTER_WINDOW entrypoint for ParamLab Strategy Tester runs.

Default mode is evaluation-only: it writes guard status for Dashboard/Governance
without launching MT5. With --run-terminal, this script refuses to run unless
the shared guard proves the window, lock, queue, profile root, and tester-only
constraints are all satisfied. The underlying runner performs the same lock and
config checks again before terminal launch.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from auto_tester_window_guard import (
    AUTO_TESTER_WINDOW_LEDGER_NAME,
    AUTO_TESTER_WINDOW_NAME,
    LOCK_NAME,
    evaluate_execution_gate,
    parse_now,
    read_json,
)


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HFM_ROOT = Path(r"C:\Program Files\HFM Metatrader 5")
DEFAULT_RUNTIME_DIR = DEFAULT_HFM_ROOT / "MQL5" / "Files"
DEFAULT_TESTER_ROOT = DEFAULT_REPO_ROOT / "runtime" / "HFM_MT5_Tester_Isolated"
SCHEDULER_NAME = "QuantGod_ParamLabAutoScheduler.json"
STATUS_NAME = "QuantGod_ParamLabStatus.json"
RUN_RECOVERY_NAME = "QuantGod_ParamLabRunRecovery.json"
WATCHER_NAME = "QuantGod_ParamLabReportWatcher.json"
BACKTEST_BUDGET_NAME = "QuantGod_ParamLabBacktestBudget.json"
EXECUTOR_PLAN_NAME = "QuantGod_AutoTesterWindowExecutorPlan.json"

DEFAULT_ROUTE_BUDGET = {
    "MA_Cross": 2,
    "RSI_Reversal": 2,
    "BB_Triple": 1,
    "MACD_Divergence": 1,
    "SR_Breakout": 1,
}
DEFAULT_BACKTEST_BUDGET = {
    "schemaVersion": 1,
    "source": "QuantGod AUTO_TESTER_WINDOW default budget policy",
    "defaultRouteBudget": 1,
    "routeBudget": DEFAULT_ROUTE_BUDGET,
    "defaultParameterFamilyBudget": 2,
    "defaultFailureFamilyBudget": 1,
    "hardGuards": [
        "Budget policy is enforced before runner launch.",
        "Red retry drilldown candidates are excluded before budget accounting.",
        "Budget limits only tester-only ParamLab work and never mutate live presets.",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate or run the QuantGod AUTO_TESTER_WINDOW guard.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--hfm-root", default=str(DEFAULT_HFM_ROOT))
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--scheduler", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--ledger", default="")
    parser.add_argument("--lock", default="")
    parser.add_argument("--run-recovery", default="")
    parser.add_argument("--budget-policy", default="")
    parser.add_argument("--executor-plan", default="")
    parser.add_argument(
        "--tester-root",
        default=str(DEFAULT_TESTER_ROOT),
        help="Isolated tester terminal root. Defaults to repo runtime/HFM_MT5_Tester_Isolated.",
    )
    parser.add_argument(
        "--require-isolated-tester",
        dest="require_isolated_tester",
        action="store_true",
        default=True,
        help="Block run-terminal execution unless --tester-root differs from --hfm-root. Enabled by default.",
    )
    parser.add_argument(
        "--allow-shared-tester",
        dest="require_isolated_tester",
        action="store_false",
        help="Explicitly allow shared HFM root for evaluation or manual diagnostics.",
    )
    parser.add_argument("--max-tasks", type=int, default=4)
    parser.add_argument("--route", action="append", default=[])
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--rank-mode", choices=("route-balanced", "score"), default="route-balanced")
    parser.add_argument("--from-date", default="")
    parser.add_argument("--to-date", default="")
    parser.add_argument(
        "--terminal-timeout-seconds",
        type=int,
        default=0,
        help="Forwarded to run_param_lab.py; 0 keeps the runner's manual/full-run default.",
    )
    parser.add_argument("--login", default="90000001")
    parser.add_argument("--server", default="SyntheticBroker-Demo")
    parser.add_argument("--now-iso", default="", help="Testing hook for guard evaluation.")
    parser.add_argument("--run-terminal", action="store_true", help="Attempt a guarded Strategy Tester run.")
    parser.add_argument(
        "--authorized-strategy-tester",
        action="store_true",
        help="Required with --run-terminal; the lock and time window are still required.",
    )
    parser.add_argument(
        "--allow-outside-window",
        action="store_true",
        help="Only honored when the authorization lock also has allowOutsideWindow=true.",
    )
    parser.add_argument(
        "--disable-retry-drilldown",
        action="store_true",
        help="Do not enforce Run Recovery red/yellow/green drilldown before runner launch.",
    )
    parser.add_argument(
        "--disable-budget-control",
        action="store_true",
        help="Do not enforce per-route/parameter-family/failure-family tester budget before runner launch.",
    )
    parser.add_argument(
        "--continuous-watch",
        action="store_true",
        help="After a guarded tester run, poll Report Watcher until reports parse or timeout.",
    )
    parser.add_argument("--watch-interval-seconds", type=int, default=30)
    parser.add_argument("--watch-timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--max-live-snapshot-age-minutes",
        type=int,
        default=30,
        help="Maximum age for QuantGod_Dashboard.json before run-terminal is blocked by the live-session guard.",
    )
    return parser.parse_args()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def path_same(left: Path, right: Path) -> bool:
    try:
        return str(left.resolve()).lower() == str(right.resolve()).lower()
    except Exception:
        return str(left).lower() == str(right).lower()


def command_for_runner(
    args: argparse.Namespace,
    *,
    run_terminal: bool,
    lock_path: Path,
    plan_path: Path,
    hfm_root: Path,
) -> list[str]:
    repo_root = Path(args.repo_root)
    runtime_dir = Path(args.runtime_dir)
    command = [
        sys.executable or "python3",
        str(repo_root / "tools" / "run_param_lab.py"),
        "--repo-root",
        str(repo_root),
        "--hfm-root",
        str(hfm_root),
        "--runtime-dir",
        str(runtime_dir),
        "--plan",
        str(plan_path),
        "--max-tasks",
        str(args.max_tasks),
        "--rank-mode",
        args.rank_mode,
        "--login",
        args.login,
        "--server",
        args.server,
        "--auto-tester-lock",
        str(lock_path),
        "--max-live-snapshot-age-minutes",
        str(args.max_live_snapshot_age_minutes),
    ]
    if args.from_date:
        command.extend(["--from-date", args.from_date])
    if args.to_date:
        command.extend(["--to-date", args.to_date])
    if int(args.terminal_timeout_seconds or 0) > 0:
        command.extend(["--terminal-timeout-seconds", str(args.terminal_timeout_seconds)])
    for route in args.route:
        command.extend(["--route", route])
    for candidate_id in args.candidate_id:
        command.extend(["--candidate-id", candidate_id])
    if run_terminal:
        command.extend(["--run-terminal", "--authorized-strategy-tester"])
        if args.allow_outside_window:
            command.append("--allow-outside-window")
    return command


def command_for_watcher(args: argparse.Namespace) -> list[str]:
    repo_root = Path(args.repo_root)
    runtime_dir = Path(args.runtime_dir)
    scheduler_path = Path(args.executor_plan) if args.executor_plan else runtime_dir / EXECUTOR_PLAN_NAME
    return [
        sys.executable or "python3",
        str(repo_root / "tools" / "watch_param_lab_reports.py"),
        "--repo-root",
        str(repo_root),
        "--runtime-dir",
        str(runtime_dir),
        "--scheduler",
        str(scheduler_path),
    ]


def command_to_text(command: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def summarize_selected_tasks(scheduler: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = scheduler.get("selectedTasks") if isinstance(scheduler.get("selectedTasks"), list) else []
    rows = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        rows.append({
            "rank": task.get("rank", ""),
            "candidateId": task.get("candidateId", ""),
            "routeKey": task.get("routeKey", ""),
            "symbol": task.get("symbol", ""),
            "timeframe": task.get("timeframe", ""),
            "scheduleAction": task.get("scheduleAction", ""),
            "sourceDecision": task.get("sourceDecision", ""),
            "testerOnly": task.get("testerOnly") is True,
            "livePresetMutation": bool(task.get("livePresetMutation")),
            "runTerminalDefault": bool(task.get("runTerminalDefault")),
            "executorDecision": task.get("executorDecision", ""),
            "retryRiskLevel": task.get("retryRiskLevel", ""),
            "retryRiskReason": task.get("retryRiskReason", ""),
            "retryUsed": task.get("retryUsed", ""),
            "retryRemaining": task.get("retryRemaining", ""),
            "budgetFamily": task.get("budgetFamily", ""),
            "budgetDecision": task.get("budgetDecision", ""),
        })
    return rows


def load_budget_policy(path: Path) -> dict[str, Any]:
    policy = read_json(path)
    if not policy:
        return dict(DEFAULT_BACKTEST_BUDGET)
    merged = dict(DEFAULT_BACKTEST_BUDGET)
    merged.update(policy)
    route_budget = dict(DEFAULT_ROUTE_BUDGET)
    route_budget.update(safe_dict(policy.get("routeBudget")))
    merged["routeBudget"] = route_budget
    return merged


def drilldown_index(recovery: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = recovery.get("candidateDrilldown") if isinstance(recovery.get("candidateDrilldown"), list) else []
    return {
        str(row.get("candidateId") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("candidateId") or "")
    }


def tester_section_has_login(config_path: Path) -> bool:
    if not config_path.exists():
        return False
    section = ""
    try:
        lines = config_path.read_text(encoding="ascii", errors="ignore").splitlines()
    except Exception:
        return False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if section == "tester" and stripped.lower().startswith("login=") and stripped.split("=", 1)[1].strip():
            return True
    return False


def previous_tester_config_missing_login(candidate_id: str, drilldown: dict[str, Any]) -> bool:
    status_path_text = str(drilldown.get("latestStatusPath") or "")
    if not status_path_text:
        return False
    status = read_json(Path(status_path_text))
    for row in safe_list(status.get("taskStatus")) + safe_list(status.get("tasks")):
        task = safe_dict(row)
        if str(task.get("candidateId") or "") != candidate_id:
            continue
        config_path_text = str(task.get("configPath") or "")
        if not config_path_text:
            return False
        return not tester_section_has_login(Path(config_path_text))
    return False


def runner_changed_since_failure(drilldown: dict[str, Any]) -> bool:
    generated_text = str(drilldown.get("latestGeneratedAtIso") or "")
    if not generated_text:
        return False
    try:
        generated = datetime.fromisoformat(generated_text.replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    runner_mtime = datetime.fromtimestamp((Path(__file__).parent / "run_param_lab.py").stat().st_mtime, timezone.utc)
    return runner_mtime > generated


def parameter_family(task: dict[str, Any]) -> str:
    route_key = str(task.get("routeKey") or task.get("strategy") or "UNKNOWN")
    variant = str(task.get("variant") or "").strip()
    if variant:
        return f"{route_key}:{variant}"
    candidate_id = str(task.get("candidateId") or "")
    for symbol in ("EURUSDc", "USDJPYc", "XAUUSDc"):
        candidate_id = candidate_id.replace(f"_{symbol}_", "_")
    prefix = f"{route_key}_"
    if candidate_id.startswith(prefix):
        candidate_id = candidate_id[len(prefix):]
    parts = [part for part in candidate_id.split("_") if part]
    return f"{route_key}:{'_'.join(parts[:4]) or 'unknown'}"


def failure_family(task: dict[str, Any], drilldown: dict[str, Any]) -> str:
    route_key = str(task.get("routeKey") or task.get("strategy") or "UNKNOWN")
    reason = str(drilldown.get("riskReason") or "within_retry_budget")
    if reason == "within_retry_budget":
        blockers = [str(item) for item in safe_list(task.get("blockers"))]
        for marker in ("report_missing", "malformed", "terminal", "win_lt", "pf_lt", "drawdown"):
            if any(marker in blocker.lower() for blocker in blockers):
                reason = marker
                break
    return f"{route_key}:{reason}"


def budget_limit(policy: dict[str, Any], key: str, default_key: str, fallback: int) -> int:
    try:
        return max(0, int(policy.get(key, policy.get(default_key, fallback))))
    except Exception:
        return fallback


def route_budget_for(policy: dict[str, Any], route_key: str) -> int:
    route_budget = safe_dict(policy.get("routeBudget"))
    try:
        return max(0, int(route_budget.get(route_key, policy.get("defaultRouteBudget", 1))))
    except Exception:
        return 1


def apply_executor_controls(
    *,
    scheduler: dict[str, Any],
    recovery: dict[str, Any],
    budget_policy: dict[str, Any],
    max_tasks: int,
    enforce_retry_drilldown: bool,
    enforce_budget: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tasks = [safe_dict(task) for task in safe_list(scheduler.get("selectedTasks"))]
    task_by_id = {str(task.get("candidateId") or ""): task for task in tasks}
    drilldowns = drilldown_index(recovery)
    allowed_ids: list[str] = []
    excluded: list[dict[str, Any]] = []
    route_used: dict[str, int] = defaultdict(int)
    family_used: dict[str, int] = defaultdict(int)
    failure_used: dict[str, int] = defaultdict(int)
    route_blocked = family_blocked = failure_blocked = red_blocked = 0
    max_allowed = max(1, int(max_tasks or 1))
    family_limit = budget_limit(budget_policy, "parameterFamilyBudget", "defaultParameterFamilyBudget", 2)
    failure_limit = budget_limit(budget_policy, "failureFamilyBudget", "defaultFailureFamilyBudget", 1)

    for task in tasks:
        candidate_id = str(task.get("candidateId") or "")
        route_key = str(task.get("routeKey") or task.get("strategy") or "UNKNOWN")
        drilldown = drilldowns.get(candidate_id, {})
        risk_level = str(drilldown.get("riskLevel") or "green").lower()
        risk_reason = str(drilldown.get("riskReason") or "within_retry_budget")
        family = parameter_family(task)
        fail_family = failure_family(task, drilldown)
        enriched = dict(task)
        enriched.update({
            "retryRiskLevel": risk_level,
            "retryRiskReason": risk_reason,
            "retryUsed": drilldown.get("retryUsed", 0),
            "retryRemaining": drilldown.get("retryRemaining", ""),
            "budgetFamily": family,
            "failureFamily": fail_family,
        })

        retry_override = ""
        if enforce_retry_drilldown and risk_level == "red" and risk_reason == "terminal_nonzero":
            if previous_tester_config_missing_login(candidate_id, drilldown):
                retry_override = "PREVIOUS_TESTER_CONFIG_MISSING_TESTER_LOGIN_FIXED"
            elif runner_changed_since_failure(drilldown):
                retry_override = "RUNNER_CHANGED_AFTER_TERMINAL_NONZERO"
        if retry_override:
            risk_level = "yellow"
            risk_reason = "tester_login_config_fixed"
            enriched["retryRiskLevel"] = risk_level
            enriched["retryRiskReason"] = risk_reason
            enriched["retryOverride"] = retry_override

        if enforce_retry_drilldown and risk_level == "red":
            enriched["executorDecision"] = "SKIP_RED_DRILLDOWN_NO_RETRY"
            enriched["budgetDecision"] = "retry_protected"
            excluded.append(enriched)
            red_blocked += 1
            continue

        if enforce_budget:
            route_limit = route_budget_for(budget_policy, route_key)
            if route_used[route_key] >= route_limit:
                enriched["executorDecision"] = "SKIP_ROUTE_BUDGET"
                enriched["budgetDecision"] = f"route_budget_{route_used[route_key]}/{route_limit}"
                excluded.append(enriched)
                route_blocked += 1
                continue
            if family_used[family] >= family_limit:
                enriched["executorDecision"] = "SKIP_PARAMETER_FAMILY_BUDGET"
                enriched["budgetDecision"] = f"family_budget_{family_used[family]}/{family_limit}"
                excluded.append(enriched)
                family_blocked += 1
                continue
            if risk_reason != "within_retry_budget" and failure_used[fail_family] >= failure_limit:
                enriched["executorDecision"] = "SKIP_FAILURE_FAMILY_BUDGET"
                enriched["budgetDecision"] = f"failure_budget_{failure_used[fail_family]}/{failure_limit}"
                excluded.append(enriched)
                failure_blocked += 1
                continue

        enriched["executorDecision"] = "ALLOW_EXECUTOR_QUEUE"
        enriched["budgetDecision"] = "within_budget"
        route_used[route_key] += 1
        family_used[family] += 1
        if risk_reason != "within_retry_budget":
            failure_used[fail_family] += 1
        allowed_ids.append(candidate_id)
        task_by_id[candidate_id] = enriched
        if len(allowed_ids) >= max_allowed:
            break

    allowed_set = set(allowed_ids)
    effective = json.loads(json.dumps(scheduler))
    effective["selectedTasks"] = [task_by_id[cid] for cid in allowed_ids if cid in task_by_id]
    effective["backtestTasks"] = []
    for raw_task in safe_list(scheduler.get("backtestTasks")):
        task = safe_dict(raw_task)
        candidate_id = str(task.get("candidateId") or "")
        if candidate_id in allowed_set:
            effective["backtestTasks"].append(task_by_id.get(candidate_id, task))
    for route_plan in safe_list(effective.get("routePlans")):
        if not isinstance(route_plan, dict):
            continue
        route_plan["candidates"] = [
            candidate for candidate in safe_list(route_plan.get("candidates"))
            if str(safe_dict(candidate).get("candidateId") or "") in allowed_set
        ]
        route_plan["scheduledTaskCount"] = len(route_plan["candidates"])
    effective["executorControls"] = {
        "generatedAtIso": datetime.now(timezone.utc).isoformat(),
        "retryDrilldownEnforced": enforce_retry_drilldown,
        "budgetControlEnforced": enforce_budget,
        "allowedCount": len(allowed_ids),
        "excludedCount": len(excluded),
        "redSkippedCount": red_blocked,
        "routeBudgetSkippedCount": route_blocked,
        "parameterFamilyBudgetSkippedCount": family_blocked,
        "failureFamilyBudgetSkippedCount": failure_blocked,
        "routeUsed": dict(route_used),
        "parameterFamilyUsed": dict(family_used),
        "failureFamilyUsed": dict(failure_used),
        "budgetPolicy": budget_policy,
    }
    effective_summary = safe_dict(effective.get("summary"))
    effective_summary["queueCount"] = len(effective["selectedTasks"])
    effective_summary["executorFilteredQueueCount"] = len(effective["selectedTasks"])
    effective_summary["executorExcludedCount"] = len(excluded)
    effective_summary["runTerminal"] = False
    effective_summary["livePresetMutation"] = False
    effective["summary"] = effective_summary
    return effective, {
        **effective["executorControls"],
        "excludedTasks": excluded,
    }


def build_isolation_status(*, hfm_root: Path, tester_root: Path, require_isolated: bool) -> dict[str, Any]:
    shared = path_same(hfm_root, tester_root)
    terminal_path = tester_root / "terminal64.exe"
    profile_root = tester_root / "MQL5" / "Profiles" / "Tester"
    blockers: list[str] = []
    warnings: list[str] = []
    if require_isolated and shared:
        blockers.append("isolated_tester_required_but_shared_with_live_hfm_root")
    if not terminal_path.exists():
        blockers.append("tester_terminal64_missing")
    if not profile_root.exists():
        blockers.append("tester_profile_root_missing")
    if shared:
        warnings.append("tester_root_shared_with_live_hfm_root")
    return {
        "mode": "SHARED_TERMINAL" if shared else "ISOLATED_TERMINAL",
        "status": "ready" if not blockers else "blocked",
        "ok": not blockers,
        "requireIsolatedTester": bool(require_isolated),
        "hfmRoot": str(hfm_root),
        "testerRoot": str(tester_root),
        "terminalPath": str(terminal_path),
        "testerProfileRoot": str(profile_root),
        "blockers": blockers,
        "warnings": warnings,
    }


def run_continuous_watcher(args: argparse.Namespace, *, enabled: bool) -> dict[str, Any]:
    watcher_command = command_for_watcher(args)
    watcher_status: dict[str, Any] = {
        "enabled": bool(args.continuous_watch),
        "attempted": False,
        "iterations": 0,
        "exitCodes": [],
        "lastStdoutTail": "",
        "lastStderrTail": "",
        "startedAtIso": "",
        "endedAtIso": "",
        "stopReason": "not_enabled" if not args.continuous_watch else "not_attempted",
        "watcherCommand": command_to_text(watcher_command),
    }
    if not (args.continuous_watch and enabled):
        return watcher_status
    timeout_seconds = max(0, int(args.watch_timeout_seconds or 0))
    interval_seconds = max(1, int(args.watch_interval_seconds or 1))
    deadline = time.monotonic() + timeout_seconds
    runtime_dir = Path(args.runtime_dir)
    watcher_path = runtime_dir / WATCHER_NAME
    watcher_status["attempted"] = True
    watcher_status["startedAtIso"] = datetime.now(timezone.utc).isoformat()
    if timeout_seconds <= 0:
        watcher_status["stopReason"] = "watch_timeout_zero"
        watcher_status["endedAtIso"] = datetime.now(timezone.utc).isoformat()
        return watcher_status

    while time.monotonic() <= deadline:
        process = subprocess.run(watcher_command, text=True, capture_output=True, check=False)
        watcher_status["iterations"] += 1
        watcher_status["exitCodes"].append(process.returncode)
        watcher_status["lastStdoutTail"] = "\n".join(process.stdout.splitlines()[-20:])
        watcher_status["lastStderrTail"] = "\n".join(process.stderr.splitlines()[-20:])
        watcher_doc = read_json(watcher_path)
        summary = safe_dict(watcher_doc.get("summary"))
        pending = int(summary.get("pendingReportCount") or 0)
        malformed = int(summary.get("malformedReportCount") or 0)
        parsed = int(summary.get("parsedReportCount") or 0)
        if process.returncode != 0:
            watcher_status["stopReason"] = "watcher_exit_nonzero"
            break
        if parsed and pending <= 0 and malformed <= 0:
            watcher_status["stopReason"] = "reports_parsed"
            break
        watcher_status["stopReason"] = "watch_timeout"
        time.sleep(interval_seconds)
    watcher_status["endedAtIso"] = datetime.now(timezone.utc).isoformat()
    return watcher_status


def build_status(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    repo_root = Path(args.repo_root)
    hfm_root = Path(args.hfm_root)
    tester_root = Path(args.tester_root) if args.tester_root else DEFAULT_TESTER_ROOT
    runtime_dir = Path(args.runtime_dir)
    scheduler_path = Path(args.scheduler) if args.scheduler else runtime_dir / SCHEDULER_NAME
    output_path = Path(args.output) if args.output else runtime_dir / AUTO_TESTER_WINDOW_NAME
    ledger_path = Path(args.ledger) if args.ledger else runtime_dir / AUTO_TESTER_WINDOW_LEDGER_NAME
    lock_path = Path(args.lock) if args.lock else runtime_dir / LOCK_NAME
    run_recovery_path = Path(args.run_recovery) if args.run_recovery else runtime_dir / RUN_RECOVERY_NAME
    budget_policy_path = Path(args.budget_policy) if args.budget_policy else runtime_dir / BACKTEST_BUDGET_NAME
    executor_plan_path = Path(args.executor_plan) if args.executor_plan else runtime_dir / EXECUTOR_PLAN_NAME
    now = parse_now(args.now_iso)
    scheduler = read_json(scheduler_path)
    run_recovery = read_json(run_recovery_path)
    budget_policy = load_budget_policy(budget_policy_path)
    effective_scheduler, executor_controls = apply_executor_controls(
        scheduler=scheduler,
        recovery=run_recovery,
        budget_policy=budget_policy,
        max_tasks=args.max_tasks,
        enforce_retry_drilldown=not args.disable_retry_drilldown,
        enforce_budget=not args.disable_budget_control,
    )
    write_json(executor_plan_path, effective_scheduler)
    selected_tasks = summarize_selected_tasks(effective_scheduler)
    effective_max_tasks = max(1, min(args.max_tasks, len(selected_tasks) or args.max_tasks))
    isolation = build_isolation_status(
        hfm_root=hfm_root,
        tester_root=tester_root,
        require_isolated=args.require_isolated_tester,
    )

    gate = evaluate_execution_gate(
        scheduler=effective_scheduler,
        runtime_dir=runtime_dir,
        hfm_root=tester_root,
        repo_root=repo_root,
        lock_path=lock_path,
        now_utc=now,
        max_tasks=effective_max_tasks,
        allow_outside_window=args.allow_outside_window,
        expected_login=args.login,
        expected_server=args.server,
        max_live_snapshot_age_minutes=args.max_live_snapshot_age_minutes,
    )
    if not isolation.get("ok"):
        gate["blockers"].extend(isolation.get("blockers") or [])
        gate["canRunTerminal"] = False
        gate["status"] = "blocked"
    gate["testerIsolation"] = isolation
    config_only_command = command_for_runner(
        args,
        run_terminal=False,
        lock_path=lock_path,
        plan_path=executor_plan_path,
        hfm_root=tester_root,
    )
    run_command = command_for_runner(
        args,
        run_terminal=True,
        lock_path=lock_path,
        plan_path=executor_plan_path,
        hfm_root=tester_root,
    )
    child_status: dict[str, Any] = {
        "attempted": False,
        "exitCode": None,
        "stdoutTail": "",
        "stderrTail": "",
    }
    mode = "EVALUATE_ONLY"
    exit_code = 0

    if args.run_terminal:
        mode = "EXECUTE_STRATEGY_TESTER"
        if not args.authorized_strategy_tester:
            gate["blockers"].append("missing_authorized_strategy_tester_flag")
            gate["canRunTerminal"] = False
            gate["status"] = "blocked"
        if not gate["canRunTerminal"]:
            exit_code = 2
        else:
            process = subprocess.run(run_command, text=True, capture_output=True, check=False)
            child_status = {
                "attempted": True,
                "exitCode": process.returncode,
                "stdoutTail": "\n".join(process.stdout.splitlines()[-20:]),
                "stderrTail": "\n".join(process.stderr.splitlines()[-20:]),
            }
            exit_code = process.returncode

    watcher_status = run_continuous_watcher(
        args,
        enabled=bool(args.run_terminal and child_status["attempted"]),
    )
    latest_runner_status = read_json(runtime_dir / STATUS_NAME)
    summary = {
        "mode": mode,
        "canRunTerminal": bool(gate.get("canRunTerminal")),
        "runTerminalRequested": bool(args.run_terminal),
        "runAttempted": bool(child_status["attempted"]),
        "selectedTaskCount": len(selected_tasks),
        "queueCount": gate.get("queue", {}).get("queueCount", 0),
        "sourceQueueCount": len(summarize_selected_tasks(scheduler)),
        "executorExcludedCount": executor_controls.get("excludedCount", 0),
        "redSkippedCount": executor_controls.get("redSkippedCount", 0),
        "routeBudgetSkippedCount": executor_controls.get("routeBudgetSkippedCount", 0),
        "parameterFamilyBudgetSkippedCount": executor_controls.get("parameterFamilyBudgetSkippedCount", 0),
        "failureFamilyBudgetSkippedCount": executor_controls.get("failureFamilyBudgetSkippedCount", 0),
        "windowOk": bool(gate.get("window", {}).get("ok")),
        "lockOk": bool(gate.get("authorizationLock", {}).get("ok")),
        "queueOk": bool(gate.get("queue", {}).get("ok")),
        "liveSessionOk": bool(gate.get("liveSession", {}).get("ok")),
        "openLivePositions": int(gate.get("liveSession", {}).get("openTradeCount") or 0),
        "liveSnapshotAgeMinutes": gate.get("liveSession", {}).get("snapshotAgeMinutes"),
        "environmentOk": gate.get("environment", {}).get("status") == "ready",
        "isolationOk": bool(isolation.get("ok")),
        "isolationMode": isolation.get("mode", ""),
        "blockerCount": len(gate.get("blockers") or []),
        "childExitCode": child_status["exitCode"],
        "terminalTimeoutSeconds": int(args.terminal_timeout_seconds or 0),
        "continuousWatcherEnabled": bool(args.continuous_watch),
        "continuousWatcherAttempted": bool(watcher_status.get("attempted")),
        "continuousWatcherIterations": int(watcher_status.get("iterations") or 0),
        "continuousWatcherStopReason": watcher_status.get("stopReason", ""),
        "runTerminal": bool(child_status["attempted"]),
        "livePresetMutation": False,
    }
    status = {
        "schemaVersion": 2,
        "source": "QuantGod AUTO_TESTER_WINDOW Guard",
        "generatedAtIso": datetime.now(timezone.utc).isoformat(),
        "evaluatedAtIso": now.isoformat(),
        "mode": mode,
        "runtimeDir": str(runtime_dir),
        "repoRoot": str(repo_root),
        "hfmRoot": str(hfm_root),
        "testerRoot": str(tester_root),
        "schedulerPath": str(scheduler_path),
        "executorPlanPath": str(executor_plan_path),
        "runRecoveryPath": str(run_recovery_path),
        "budgetPolicyPath": str(budget_policy_path),
        "lockPath": str(lock_path),
        "summary": summary,
        "gate": gate,
        "testerIsolation": isolation,
        "executorControls": executor_controls,
        "selectedTasks": selected_tasks,
        "excludedTasks": executor_controls.get("excludedTasks", []),
        "configOnlyCommand": command_to_text(config_only_command),
        "guardedRunCommand": command_to_text(run_command),
        "continuousWatcher": watcher_status,
        "childProcess": child_status,
        "latestParamLabStatus": {
            "runId": latest_runner_status.get("runId", ""),
            "mode": latest_runner_status.get("mode", ""),
            "generatedAtIso": latest_runner_status.get("generatedAtIso", ""),
            "summary": latest_runner_status.get("summary", {}),
        },
        "hardGuards": gate.get("hardGuards", []),
        "nextOperatorSteps": [
            "Keep this in EVALUATE_ONLY mode on weekdays.",
            "Create the authorization lock only for a controlled Strategy Tester session.",
            "Use guardedRunCommand only when canRunTerminal=true and executorControls.allowedCount is positive.",
            "Red Run Recovery drilldown candidates are excluded before runner launch and do not consume automatic retries.",
            "Continuous watcher can poll reports during an authorized tester window after a guarded run.",
            "Default tester root is repo/runtime/HFM_MT5_Tester_Isolated and shared live HFM root is blocked unless --allow-shared-tester is explicit.",
            "Run-terminal stays blocked while QuantGod_Dashboard.json reports any live open position, margin in use, stale dashboard state, or account/server/session mismatch.",
        ],
    }
    write_json(output_path, status)
    rows = []
    for task in selected_tasks:
        rows.append({
            "GeneratedAtIso": status["generatedAtIso"],
            "Mode": mode,
            "CanRunTerminal": str(summary["canRunTerminal"]).lower(),
            "WindowOk": str(summary["windowOk"]).lower(),
            "LockOk": str(summary["lockOk"]).lower(),
            "QueueOk": str(summary["queueOk"]).lower(),
            "IsolationOk": str(summary["isolationOk"]).lower(),
            "CandidateId": task.get("candidateId", ""),
            "RouteKey": task.get("routeKey", ""),
            "ScheduleAction": task.get("scheduleAction", ""),
            "ExecutorDecision": task.get("executorDecision", ""),
            "RetryRiskLevel": task.get("retryRiskLevel", ""),
            "RetryRiskReason": task.get("retryRiskReason", ""),
            "BudgetDecision": task.get("budgetDecision", ""),
            "Blockers": "/".join(gate.get("blockers") or []),
        })
    for task in executor_controls.get("excludedTasks", []):
        rows.append({
            "GeneratedAtIso": status["generatedAtIso"],
            "Mode": mode,
            "CanRunTerminal": str(summary["canRunTerminal"]).lower(),
            "WindowOk": str(summary["windowOk"]).lower(),
            "LockOk": str(summary["lockOk"]).lower(),
            "QueueOk": str(summary["queueOk"]).lower(),
            "IsolationOk": str(summary["isolationOk"]).lower(),
            "CandidateId": task.get("candidateId", ""),
            "RouteKey": task.get("routeKey", ""),
            "ScheduleAction": task.get("scheduleAction", ""),
            "ExecutorDecision": task.get("executorDecision", ""),
            "RetryRiskLevel": task.get("retryRiskLevel", ""),
            "RetryRiskReason": task.get("retryRiskReason", ""),
            "BudgetDecision": task.get("budgetDecision", ""),
            "Blockers": "/".join(gate.get("blockers") or []),
        })
    write_csv(
        ledger_path,
        rows,
        [
            "GeneratedAtIso",
            "Mode",
            "CanRunTerminal",
            "WindowOk",
            "LockOk",
            "QueueOk",
            "IsolationOk",
            "CandidateId",
            "RouteKey",
            "ScheduleAction",
            "ExecutorDecision",
            "RetryRiskLevel",
            "RetryRiskReason",
            "BudgetDecision",
            "Blockers",
        ],
    )
    print(f"Wrote {output_path}")
    print(f"Wrote {ledger_path}")
    print(f"Wrote {executor_plan_path}")
    print(
        "AUTO_TESTER_WINDOW: "
        f"mode={mode} canRunTerminal={summary['canRunTerminal']} "
        f"windowOk={summary['windowOk']} lockOk={summary['lockOk']} "
        f"queue={summary['queueCount']} excluded={summary['executorExcludedCount']} "
        f"redSkipped={summary['redSkippedCount']} blockers={summary['blockerCount']}"
    )
    return status, exit_code


def main() -> int:
    args = parse_args()
    try:
        _, exit_code = build_status(args)
        return exit_code
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
