#!/usr/bin/env python3
"""Build ParamLab guarded-run history and recovery advice.

This is a read-only recovery ledger for the AUTO_TESTER_WINDOW chain. It
summarizes ParamLab run archives, terminal exit codes, report parse state,
retry counts, and next recovery action for the dashboard. It never launches
MT5, never edits presets, and never touches broker/order paths.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DIR = Path(r"C:\Program Files\HFM Metatrader 5\MQL5\Files")
STATUS_NAME = "QuantGod_ParamLabStatus.json"
RESULTS_NAME = "QuantGod_ParamLabResults.json"
WATCHER_NAME = "QuantGod_ParamLabReportWatcher.json"
AUTO_TESTER_WINDOW_NAME = "QuantGod_AutoTesterWindow.json"
ACCOUNT_CONTEXT_STATUS_NAME = "QuantGod_IsolatedTesterAccountContextStatus.json"
OUTPUT_NAME = "QuantGod_ParamLabRunRecovery.json"
LEDGER_NAME = "QuantGod_ParamLabRunRecoveryLedger.csv"
DRILLDOWN_LEDGER_NAME = "QuantGod_ParamLabRunRecoveryDrilldown.csv"
DEFAULT_RETRY_BUDGET = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build QuantGod ParamLab run recovery ledger.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--archive-root", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--ledger", default="")
    parser.add_argument("--drilldown-ledger", default="")
    parser.add_argument("--retry-budget", type=int, default=DEFAULT_RETRY_BUDGET)
    return parser.parse_args()


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(read_text(path))
    except Exception:
        return {}


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


def parse_iso(value: Any) -> datetime | None:
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


def load_status_documents(runtime_status_path: Path, archive_root: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if archive_root.exists():
        for status_path in sorted(archive_root.glob(f"*/{STATUS_NAME}")):
            status = read_json(status_path)
            if status:
                status["_statusPath"] = str(status_path)
                status["_statusSource"] = "archive_status"
                docs.append(status)
    runtime_status = read_json(runtime_status_path)
    if runtime_status:
        runtime_status["_statusPath"] = str(runtime_status_path)
        runtime_status["_statusSource"] = "runtime_status"
        docs.append(runtime_status)

    deduped: dict[str, dict[str, Any]] = {}
    for status in docs:
        run_id = str(status.get("runId") or status.get("generatedAtIso") or status.get("_statusPath") or "")
        existing = deduped.get(run_id)
        if not existing:
            deduped[run_id] = status
            continue
        if existing.get("_statusSource") == "runtime_status" and status.get("_statusSource") == "archive_status":
            deduped[run_id] = status
    return sorted(deduped.values(), key=lambda item: str(item.get("runId") or item.get("generatedAtIso") or ""))


def result_key(result: dict[str, Any]) -> tuple[str, str]:
    return str(result.get("runId") or ""), str(result.get("candidateId") or "")


def build_result_index(results_doc: dict[str, Any], watcher_doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rows = []
    rows.extend(safe_list(results_doc.get("results")))
    rows.extend(safe_list(watcher_doc.get("watchedResults")))
    rows.extend(safe_list(watcher_doc.get("results")))
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        row = safe_dict(raw)
        key = result_key(row)
        if not any(key):
            continue
        previous = index.get(key)
        previous_has_report = safe_dict(previous.get("metrics") if previous else {}).get("reportExists") if previous else False
        has_report = safe_dict(row.get("metrics")).get("reportExists")
        if previous is None or (has_report and not previous_has_report):
            index[key] = row
    return index


def report_state_from_task(task: dict[str, Any], result: dict[str, Any]) -> str:
    status = str(result.get("status") or task.get("status") or "").upper()
    metrics = safe_dict(result.get("metrics")) or safe_dict(task.get("metrics"))
    parse_status = str(metrics.get("parseStatus") or "").upper()
    html_report_exists = bool(metrics.get("htmlReportExists"))
    report_exists = bool(metrics.get("reportExists")) and str(metrics.get("evidenceSource") or "") != "agent_artifacts"
    if status in {"TERMINAL_EXIT_NONZERO_REPORT_MISSING", "REPORT_MISSING_AFTER_RUN", "REPORT_MISSING", "PENDING_REPORT"}:
        return "missing"
    if status == "REPORT_FOUND_UNPARSED" or parse_status == "REPORT_FOUND_UNPARSED":
        return "malformed"
    if (status.startswith("PARSED") or parse_status.startswith("PARSED")) and html_report_exists:
        return "parsed"
    if report_exists and not parse_status:
        return "parsed"
    if parse_status in {"PENDING_REPORT", "REPORT_MISSING"}:
        return "missing"
    if str(task.get("terminalExitCode") or "") not in {"", "None"}:
        return "missing"
    return "pending"


def stop_reason_for(
    *,
    mode: str,
    run_terminal: bool,
    terminal_codes: list[Any],
    missing: int,
    parsed: int,
    malformed: int,
    task_count: int,
    current_blockers: list[str],
) -> str:
    nonzero_codes = [code for code in terminal_codes if code not in (None, "", 0, "0")]
    if not task_count:
        return "no_paramlab_tasks"
    if malformed:
        return "report_malformed"
    if nonzero_codes:
        return "terminal_exit_nonzero"
    if run_terminal and missing:
        return "report_missing_after_run"
    if parsed and parsed >= task_count:
        return "reports_parsed"
    if mode == "CONFIG_ONLY" and not run_terminal:
        if current_blockers:
            return "waiting_guard_clearance"
        return "config_only_waiting_tester_window"
    if missing:
        return "waiting_report"
    return "pending_recovery_review"


def action_for_stop_reason(stop_reason: str) -> str:
    mapping = {
        "no_paramlab_tasks": "BUILD_SCHEDULER_QUEUE",
        "report_malformed": "OPEN_REPORT_AND_REPARSE",
        "terminal_exit_nonzero": "CHECK_TERMINAL_LOG_THEN_RETRY",
        "report_missing_after_run": "CHECK_REPORT_PATH_THEN_RETRY_WATCHER",
        "reports_parsed": "SCORE_AND_VERSION_GATE",
        "waiting_guard_clearance": "WAIT_AUTO_TESTER_WINDOW",
        "config_only_waiting_tester_window": "WAIT_AUTHORIZED_TESTER_WINDOW",
        "waiting_report": "WAIT_OR_RUN_REPORT_WATCHER",
    }
    return mapping.get(stop_reason, "REVIEW_RUN_STATE")


def build_run_rows(
    statuses: list[dict[str, Any]],
    result_index: dict[tuple[str, str], dict[str, Any]],
    current_blockers: list[str],
) -> list[dict[str, Any]]:
    attempt_counter: dict[str, int] = defaultdict(int)
    rows: list[dict[str, Any]] = []
    sorted_statuses = sorted(statuses, key=lambda item: str(item.get("runId") or item.get("generatedAtIso") or ""))
    for status in sorted_statuses:
        run_id = str(status.get("runId") or status.get("generatedAtIso") or "unknown_run")
        tasks = [safe_dict(task) for task in safe_list(status.get("tasks"))]
        task_count = len(tasks)
        mode = str(status.get("mode") or "")
        run_terminal = bool(status.get("runTerminal"))
        terminal_codes = [task.get("terminalExitCode") for task in tasks if task.get("terminalExitCode") not in (None, "")]
        parsed = missing = malformed = pending = 0
        routes: set[str] = set()
        candidates: list[str] = []
        retry_values: list[int] = []

        for task in tasks:
            candidate_id = str(task.get("candidateId") or "")
            route_key = str(task.get("routeKey") or task.get("strategy") or "")
            if route_key:
                routes.add(route_key)
            if candidate_id:
                candidates.append(candidate_id)
                attempt_counter[candidate_id] += 1
                retry_values.append(max(0, attempt_counter[candidate_id] - 1))
            result = result_index.get((run_id, candidate_id), {})
            if not run_terminal and str(task.get("status") or "").upper() == "CONFIG_READY":
                state = "pending"
            else:
                state = report_state_from_task(task, result)
            if state == "parsed":
                parsed += 1
            elif state == "missing":
                missing += 1
            elif state == "malformed":
                malformed += 1
            else:
                pending += 1

        summary = safe_dict(status.get("summary"))
        if not tasks:
            parsed = int(summary.get("reportParsedCount") or 0)
            missing = int(summary.get("runAttemptedCount") or 0) - parsed
            pending = int(summary.get("configReadyCount") or 0)
        stop_reason = stop_reason_for(
            mode=mode,
            run_terminal=run_terminal,
            terminal_codes=terminal_codes,
            missing=max(0, missing),
            parsed=parsed,
            malformed=malformed,
            task_count=task_count or int(summary.get("selectedTaskCount") or 0),
            current_blockers=current_blockers,
        )
        rows.append({
            "runId": run_id,
            "generatedAtIso": status.get("generatedAtIso", ""),
            "mode": mode,
            "runTerminal": run_terminal,
            "terminalExitCodes": terminal_codes,
            "terminalExitCodeLabel": ",".join(str(code) for code in terminal_codes) if terminal_codes else "--",
            "reportParsedCount": parsed,
            "reportMissingCount": max(0, missing),
            "reportMalformedCount": malformed,
            "reportPendingCount": max(0, pending),
            "retryCount": max(retry_values) if retry_values else 0,
            "taskCount": task_count or int(summary.get("selectedTaskCount") or 0),
            "routeKeys": sorted(routes),
            "candidateIds": candidates,
            "stopReason": stop_reason,
            "recoveryAction": action_for_stop_reason(stop_reason),
            "statusPath": status.get("_statusPath", ""),
            "archiveDir": status.get("archiveDir", ""),
            "source": status.get("_statusSource", ""),
        })
    return sorted(rows, key=lambda item: str(item.get("runId")), reverse=True)


def report_state_for_run_task(task: dict[str, Any], result: dict[str, Any], run_terminal: bool) -> str:
    if not run_terminal and str(task.get("status") or "").upper() == "CONFIG_READY":
        return "waiting_report"
    state = report_state_from_task(task, result)
    if state == "pending":
        return "waiting_report"
    return state


def failure_reason_counts(row: dict[str, Any]) -> dict[str, int]:
    return {
        "waiting_report": int(row.get("waitingReportCount") or 0),
        "report_missing_after_run": int(row.get("reportMissingCount") or 0),
        "report_malformed": int(row.get("reportMalformedCount") or 0),
        "terminal_exit_nonzero": int(row.get("terminalNonzeroCount") or 0),
        "parsed": int(row.get("reportParsedCount") or 0),
    }


def risk_for_candidate(row: dict[str, Any], retry_budget: int) -> tuple[str, str, int, str]:
    retry_used = int(row.get("retryUsed") or 0)
    waiting = int(row.get("waitingReportCount") or 0)
    missing = int(row.get("reportMissingCount") or 0)
    malformed = int(row.get("reportMalformedCount") or 0)
    nonzero = int(row.get("terminalNonzeroCount") or 0)
    parsed = int(row.get("reportParsedCount") or 0)
    if str(row.get("latestState") or "") == "parsed":
        return "green", "status-live", 10 + parsed, "parsed_latest"
    budget_exhausted = retry_used >= retry_budget and parsed == 0
    if malformed or nonzero or missing or budget_exhausted:
        reason = "malformed" if malformed else "terminal_nonzero" if nonzero else "missing_after_run" if missing else "retry_budget_exhausted"
        score = 100 + malformed * 20 + nonzero * 15 + missing * 12 + max(0, retry_used - retry_budget + 1) * 10
        return "red", "status-danger", score, reason
    if waiting >= 2 or retry_used > 0:
        score = 50 + waiting * 5 + retry_used * 4
        return "yellow", "status-warn", score, "repeated_waiting_report"
    return "green", "status-live", 10 + parsed, "within_retry_budget"


def recovery_advice_for_candidate(row: dict[str, Any], risk_reason: str) -> str:
    mapping = {
        "malformed": "Open report, fix parser mapping, then rerun watcher before another tester run.",
        "terminal_nonzero": "Inspect terminal/tester logs and profile sync before consuming another retry.",
        "tester_account_context_missing": "Sync or recreate isolated tester account context; MT5 tester reports account is not specified.",
        "account_context_synced_retry_ready": "Account context was synced after the failure; allow one guarded isolated tester retry.",
        "parsed_latest": "Latest guarded tester run has parsed evidence; old failures are retained as history only.",
        "missing_after_run": "Verify reportPath and Strategy Tester output folder, then rerun watcher once.",
        "retry_budget_exhausted": "Pause automatic reruns; inspect config/report paths and candidate parameters first.",
        "repeated_waiting_report": "Keep queued, but prioritize only after authorized tester window and lock are green.",
        "within_retry_budget": "Low recovery risk; keep in queue or score if parsed.",
    }
    if int(row.get("reportParsedCount") or 0) and risk_reason == "within_retry_budget":
        return "Parsed report exists; hand to Score and Version Gate."
    return mapping.get(risk_reason, "Review candidate recovery state before rerun.")


def tester_log_contains(repo_root: Path, phrase: str) -> bool:
    log_root = repo_root / "runtime" / "HFM_MT5_Tester_Isolated" / "Tester" / "logs"
    if not log_root.exists():
        return False
    lowered = phrase.lower()
    for path in sorted(log_root.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)[:3]:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        for encoding in ("utf-16", "utf-16-le", "utf-8"):
            text = raw.decode(encoding, errors="ignore")
            if lowered in text.lower():
                return True
    return False


def parse_iso(text: str) -> datetime | None:
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def account_context_synced_after_failure(repo_root: Path, latest_generated_at: str) -> bool:
    status = read_json(repo_root / "runtime" / ACCOUNT_CONTEXT_STATUS_NAME)
    if not status.get("ready"):
        return False
    synced_at = parse_iso(str(status.get("generatedAtIso") or ""))
    failed_at = parse_iso(latest_generated_at)
    return bool(synced_at and failed_at and synced_at > failed_at)


def build_candidate_drilldown(
    statuses: list[dict[str, Any]],
    result_index: dict[tuple[str, str], dict[str, Any]],
    retry_budget: int,
    repo_root: Path,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    sorted_statuses = sorted(statuses, key=lambda item: str(item.get("runId") or item.get("generatedAtIso") or ""))
    for status in sorted_statuses:
        run_id = str(status.get("runId") or status.get("generatedAtIso") or "unknown_run")
        run_terminal = bool(status.get("runTerminal"))
        status_path = str(status.get("_statusPath") or "")
        generated_at = str(status.get("generatedAtIso") or "")
        for raw_task in safe_list(status.get("tasks")):
            task = safe_dict(raw_task)
            candidate_id = str(task.get("candidateId") or "")
            if not candidate_id:
                continue
            result = result_index.get((run_id, candidate_id), {})
            route_key = str(task.get("routeKey") or result.get("routeKey") or task.get("strategy") or "")
            row = candidates.setdefault(candidate_id, {
                "candidateId": candidate_id,
                "routeKey": route_key,
                "symbol": str(task.get("symbol") or result.get("symbol") or ""),
                "timeframe": str(task.get("timeframe") or result.get("timeframe") or ""),
                "variant": str(task.get("variant") or result.get("variant") or ""),
                "attemptCount": 0,
                "runIds": [],
                "reportParsedCount": 0,
                "waitingReportCount": 0,
                "reportMissingCount": 0,
                "reportMalformedCount": 0,
                "terminalNonzeroCount": 0,
                "terminalExitCodes": [],
                "latestRunId": "",
                "latestGeneratedAtIso": "",
                "latestStatusPath": "",
                "latestReportPath": "",
                "latestState": "",
                "latestStopReason": "",
                "latestRecoveryAction": "",
            })
            if route_key:
                row["routeKey"] = route_key
            row["attemptCount"] += 1
            row["runIds"].append(run_id)
            row["latestRunId"] = run_id
            row["latestGeneratedAtIso"] = generated_at
            row["latestStatusPath"] = status_path
            row["latestReportPath"] = str(task.get("reportPath") or result.get("reportPath") or row.get("latestReportPath") or "")

            terminal_code = task.get("terminalExitCode")
            if terminal_code not in (None, ""):
                row["terminalExitCodes"].append(terminal_code)
                if terminal_code not in (0, "0"):
                    row["terminalNonzeroCount"] += 1

            state = report_state_for_run_task(task, result, run_terminal)
            row["latestState"] = state
            if state == "parsed":
                row["reportParsedCount"] += 1
            elif state == "missing":
                row["reportMissingCount"] += 1
            elif state == "malformed":
                row["reportMalformedCount"] += 1
            else:
                row["waitingReportCount"] += 1

    normalized: list[dict[str, Any]] = []
    for row in candidates.values():
        row["retryBudget"] = retry_budget
        row["retryUsed"] = max(0, int(row.get("attemptCount") or 0) - 1)
        row["retryRemaining"] = max(0, retry_budget - int(row["retryUsed"]))
        risk_level, risk_tone, risk_score, risk_reason = risk_for_candidate(row, retry_budget)
        if risk_reason == "terminal_nonzero" and tester_log_contains(repo_root, "account is not specified"):
            risk_reason = "tester_account_context_missing"
            risk_score += 20
        if (
            risk_reason == "tester_account_context_missing"
            and account_context_synced_after_failure(repo_root, str(row.get("latestGeneratedAtIso") or ""))
        ):
            risk_level = "yellow"
            risk_tone = "status-warn"
            risk_reason = "account_context_synced_retry_ready"
            risk_score = max(75, risk_score - 35)
        row["riskLevel"] = risk_level
        row["riskTone"] = risk_tone
        row["riskScore"] = risk_score
        row["riskReason"] = risk_reason
        row["failureReasons"] = failure_reason_counts(row)
        row["latestStopReason"] = risk_reason
        row["latestRecoveryAction"] = recovery_advice_for_candidate(row, risk_reason)
        normalized.append(row)
    return sorted(normalized, key=lambda item: (-int(item.get("riskScore") or 0), str(item.get("candidateId") or "")))


def build_recovery(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root)
    runtime_dir = Path(args.runtime_dir)
    archive_root = Path(args.archive_root) if args.archive_root else repo_root / "archive" / "param-lab" / "runs"
    output_path = Path(args.output) if args.output else runtime_dir / OUTPUT_NAME
    ledger_path = Path(args.ledger) if args.ledger else runtime_dir / LEDGER_NAME
    drilldown_ledger_path = Path(args.drilldown_ledger) if args.drilldown_ledger else runtime_dir / DRILLDOWN_LEDGER_NAME
    retry_budget = max(1, int(args.retry_budget or DEFAULT_RETRY_BUDGET))

    auto_tester_window = read_json(runtime_dir / AUTO_TESTER_WINDOW_NAME)
    current_summary = safe_dict(auto_tester_window.get("summary"))
    gate = safe_dict(auto_tester_window.get("gate"))
    current_blockers = safe_list(gate.get("blockers"))
    statuses = load_status_documents(runtime_dir / STATUS_NAME, archive_root)
    result_index = build_result_index(read_json(runtime_dir / RESULTS_NAME), read_json(runtime_dir / WATCHER_NAME))
    runs = build_run_rows(statuses, result_index, [str(item) for item in current_blockers])
    candidate_drilldown = build_candidate_drilldown(statuses, result_index, retry_budget, repo_root)
    recovery_queue = [
        row for row in runs
        if row.get("recoveryAction") not in {"SCORE_AND_VERSION_GATE"} or row.get("reportMalformedCount") or row.get("reportMissingCount")
    ]
    generated_at = datetime.now(timezone.utc).isoformat()

    summary = {
        "runCount": len(runs),
        "guardedRunCount": sum(1 for row in runs if row.get("runTerminal")),
        "configOnlyCount": sum(1 for row in runs if row.get("mode") == "CONFIG_ONLY"),
        "runAttemptedCount": sum(1 for row in runs if row.get("runTerminal")),
        "reportParsedCount": sum(int(row.get("reportParsedCount") or 0) for row in runs),
        "reportMissingCount": sum(int(row.get("reportMissingCount") or 0) for row in runs),
        "reportMalformedCount": sum(int(row.get("reportMalformedCount") or 0) for row in runs),
        "retryCount": sum(int(row.get("retryCount") or 0) for row in runs),
        "recoveryQueueCount": len(recovery_queue),
        "candidateDrilldownCount": len(candidate_drilldown),
        "riskRedCount": sum(1 for row in candidate_drilldown if row.get("riskLevel") == "red"),
        "riskYellowCount": sum(1 for row in candidate_drilldown if row.get("riskLevel") == "yellow"),
        "riskGreenCount": sum(1 for row in candidate_drilldown if row.get("riskLevel") == "green"),
        "retryBudget": retry_budget,
        "retryBudgetExhaustedCount": sum(1 for row in candidate_drilldown if int(row.get("retryRemaining") or 0) <= 0 and int(row.get("reportParsedCount") or 0) == 0),
        "latestRunId": runs[0]["runId"] if runs else "",
        "latestStopReason": runs[0]["stopReason"] if runs else "no_runs",
        "canRunTerminalNow": bool(current_summary.get("canRunTerminal")),
        "currentBlockerCount": len(current_blockers),
        "runTerminal": False,
        "livePresetMutation": False,
    }
    output = {
        "schemaVersion": 1,
        "source": "QuantGod ParamLab Run History Recovery",
        "generatedAtIso": generated_at,
        "runtimeDir": str(runtime_dir),
        "repoRoot": str(repo_root),
        "archiveRoot": str(archive_root),
        "mode": "FILE_ONLY_RUN_HISTORY_RECOVERY",
        "summary": summary,
        "currentGuard": {
            "generatedAtIso": auto_tester_window.get("generatedAtIso", ""),
            "mode": auto_tester_window.get("mode", current_summary.get("mode", "")),
            "canRunTerminal": bool(current_summary.get("canRunTerminal")),
            "windowOk": bool(current_summary.get("windowOk")),
            "lockOk": bool(current_summary.get("lockOk")),
            "queueOk": bool(current_summary.get("queueOk")),
            "environmentOk": bool(current_summary.get("environmentOk")),
            "blockers": current_blockers,
        },
        "runs": runs,
        "candidateDrilldown": candidate_drilldown[:50],
        "recoveryQueue": recovery_queue[:25],
        "hardGuards": [
            "Run Recovery is read-only and never launches MT5.",
            "Run Recovery never mutates HFM live presets.",
            "Run Recovery never connects to broker APIs or OrderSend paths.",
            "Retry advice is advisory; run-terminal execution still requires AUTO_TESTER_WINDOW lock/window/profile/config validation.",
        ],
        "nextOperatorSteps": [
            "Use candidateDrilldown red/yellow/green risk before consuming more tester retries.",
            "Clear AUTO_TESTER_WINDOW blockers before any guarded run-terminal attempt.",
            "If terminal exit is non-zero, inspect HFM terminal/tester logs before retry.",
            "If reports are missing, verify reportPath under archive/param-lab/runs and rerun the watcher.",
            "If reports are malformed, open the report and improve parser mapping before using it as evidence.",
        ],
    }

    write_json(output_path, output)
    write_csv(
        ledger_path,
        [
            {
                "GeneratedAtIso": generated_at,
                "RunId": row.get("runId", ""),
                "RunMode": row.get("mode", ""),
                "RunTerminal": str(bool(row.get("runTerminal"))).lower(),
                "TerminalExitCodes": row.get("terminalExitCodeLabel", ""),
                "Parsed": row.get("reportParsedCount", 0),
                "Missing": row.get("reportMissingCount", 0),
                "Malformed": row.get("reportMalformedCount", 0),
                "Pending": row.get("reportPendingCount", 0),
                "RetryCount": row.get("retryCount", 0),
                "TaskCount": row.get("taskCount", 0),
                "StopReason": row.get("stopReason", ""),
                "RecoveryAction": row.get("recoveryAction", ""),
                "Routes": "/".join(row.get("routeKeys") or []),
                "StatusPath": row.get("statusPath", ""),
            }
            for row in runs
        ],
        [
            "GeneratedAtIso",
            "RunId",
            "RunMode",
            "RunTerminal",
            "TerminalExitCodes",
            "Parsed",
            "Missing",
            "Malformed",
            "Pending",
            "RetryCount",
            "TaskCount",
            "StopReason",
            "RecoveryAction",
            "Routes",
            "StatusPath",
        ],
    )
    write_csv(
        drilldown_ledger_path,
        [
            {
                "GeneratedAtIso": generated_at,
                "CandidateId": row.get("candidateId", ""),
                "Route": row.get("routeKey", ""),
                "Symbol": row.get("symbol", ""),
                "Timeframe": row.get("timeframe", ""),
                "RiskLevel": row.get("riskLevel", ""),
                "RiskReason": row.get("riskReason", ""),
                "RiskScore": row.get("riskScore", 0),
                "AttemptCount": row.get("attemptCount", 0),
                "RetryBudget": row.get("retryBudget", 0),
                "RetryUsed": row.get("retryUsed", 0),
                "RetryRemaining": row.get("retryRemaining", 0),
                "WaitingReport": row.get("waitingReportCount", 0),
                "MissingAfterRun": row.get("reportMissingCount", 0),
                "Malformed": row.get("reportMalformedCount", 0),
                "TerminalNonzero": row.get("terminalNonzeroCount", 0),
                "Parsed": row.get("reportParsedCount", 0),
                "LatestRunId": row.get("latestRunId", ""),
                "LatestState": row.get("latestState", ""),
                "LatestReportPath": row.get("latestReportPath", ""),
                "RecoveryAction": row.get("latestRecoveryAction", ""),
            }
            for row in candidate_drilldown
        ],
        [
            "GeneratedAtIso",
            "CandidateId",
            "Route",
            "Symbol",
            "Timeframe",
            "RiskLevel",
            "RiskReason",
            "RiskScore",
            "AttemptCount",
            "RetryBudget",
            "RetryUsed",
            "RetryRemaining",
            "WaitingReport",
            "MissingAfterRun",
            "Malformed",
            "TerminalNonzero",
            "Parsed",
            "LatestRunId",
            "LatestState",
            "LatestReportPath",
            "RecoveryAction",
        ],
    )
    print(f"Wrote {output_path}")
    print(f"Wrote {ledger_path}")
    print(f"Wrote {drilldown_ledger_path}")
    print(
        "Run Recovery: "
        f"runs={summary['runCount']} attempted={summary['runAttemptedCount']} "
        f"missing={summary['reportMissingCount']} parsed={summary['reportParsedCount']} "
        f"malformed={summary['reportMalformedCount']} "
        f"risk(red/yellow/green)={summary['riskRedCount']}/{summary['riskYellowCount']}/{summary['riskGreenCount']} "
        f"latest={summary['latestStopReason']}"
    )
    return output


def main() -> int:
    args = parse_args()
    try:
        build_recovery(args)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
