#!/usr/bin/env python3
"""Run QuantGod's daily safe automation loop.

This orchestrator turns Dashboard "today" items into file-based work:
refresh evidence, maintain ParamLab queues, evaluate the tester guard, run
tester-only tasks only when explicitly enabled and guarded, and write the DailyReview artifact. It never applies live promotion
or sends financial orders.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTOPILOT_NAME = "QuantGod_DailyAutopilot.json"
DEFAULT_AUTOPILOT_LEDGER = "QuantGod_DailyAutopilotLedger.csv"
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run QuantGod daily safe autopilot.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR") or os.environ.get("QG_MT5_FILES_DIR") or "")
    parser.add_argument("--dashboard-dir", default=os.environ.get("QG_DASHBOARD_FILES_DIR") or "")
    parser.add_argument("--tester-root", default=os.environ.get("QG_PARAMLAB_TESTER_ROOT") or os.environ.get("QG_MT5_TESTER_ROOT") or "")
    parser.add_argument("--hfm-root", default=os.environ.get("QG_PARAMLAB_HFM_ROOT") or "")
    parser.add_argument("--python-bin", default=os.environ.get("QG_PYTHON_BIN", "python3"))
    parser.add_argument("--interval-minutes", type=float, default=float(os.environ.get("QG_DAILY_AUTOPILOT_INTERVAL_MINUTES", "60")))
    parser.add_argument("--max-tasks", type=int, default=int(os.environ.get("QG_DAILY_AUTOPILOT_MAX_TASKS", "5")))
    parser.add_argument(
        "--tester-lookback-days",
        type=int,
        default=int(os.environ.get("QG_DAILY_AUTOPILOT_TESTER_LOOKBACK_DAYS", "2")),
        help="Short bounded date range for daily todo Strategy Tester runs. Full historical runs should use run_param_lab.py directly.",
    )
    parser.add_argument(
        "--tester-terminal-timeout-seconds",
        type=int,
        default=int(os.environ.get("QG_DAILY_AUTOPILOT_TESTER_TIMEOUT_SECONDS", "900")),
        help="Maximum seconds allowed for each guarded daily tester child process.",
    )
    parser.add_argument("--allow-tester-run", action="store_true", default=os.environ.get("QG_DAILY_AUTOPILOT_ALLOW_TESTER_RUN", "0") == "1")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    return parser.parse_args()


def mac_mt5_files_dir() -> Path:
    return Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Files"


def mac_mt5_root() -> Path:
    return mac_mt5_files_dir().parent.parent


def resolve_runtime_dir(repo_root: Path, configured: str) -> Path:
    candidate = Path(configured).expanduser() if configured else repo_root / "Dashboard"
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    source_mode = os.environ.get("QG_MAC_RUNTIME_SOURCE", "auto").strip().lower()
    mac_files = mac_mt5_files_dir()
    if mac_files.exists():
        normalized = str(candidate).replace("\\", "/")
        dashboard_missing = not (candidate / "QuantGod_Dashboard.json").exists()
        mac_dashboard_exists = (mac_files / "QuantGod_Dashboard.json").exists()
        if (
            source_mode == "mt5"
            or (source_mode == "auto" and "/runtime/mac_import/mt5_files_snapshot" in normalized)
            or (source_mode == "auto" and dashboard_missing and mac_dashboard_exists)
        ):
            return mac_files
    return candidate


def resolve_hfm_root(repo_root: Path, runtime_dir: Path, configured: str) -> Path:
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        return candidate
    if runtime_dir.name == "Files" and runtime_dir.parent.name == "MQL5":
        candidate = runtime_dir.parent.parent
        if candidate.exists():
            return candidate
    if os.uname().sysname == "Darwin":
        mac_root = mac_mt5_root()
        if mac_root.exists():
            return mac_root
    return repo_root / "runtime/ParamLab_Tester_Sandbox/live_hfm_placeholder"


def resolve_dashboard_dir(repo_root: Path, configured: str) -> Path:
    candidate = Path(configured).expanduser() if configured else repo_root / "Dashboard"
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    if "/runtime/mac_import/dashboard_runtime_snapshot" in str(candidate).replace("\\", "/"):
        return repo_root / "Dashboard"
    return candidate


def append_csv(path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    if exists:
        with path.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        existing_header = rows[0] if rows else []
        if existing_header != fieldnames:
            migrated_rows: list[dict[str, Any]] = []
            for values in rows[1:]:
                # Always map old values by the old header.  A same-width schema
                # change can otherwise shift values into unrelated new columns.
                migrated_rows.append(dict(zip(existing_header, values)))
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for existing_row in migrated_rows:
                    writer.writerow({key: existing_row.get(key, "") for key in fieldnames})
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_step(
    name: str,
    command: list[str],
    cwd: Path,
    timeout: int = 900,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if env_overrides:
        env.update(env_overrides)
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        status = "OK" if result.returncode == 0 else "ERROR"
        return {
            "name": name,
            "status": status,
            "exitCode": result.returncode,
            "startedAtIso": started.isoformat(),
            "finishedAtIso": datetime.now(timezone.utc).isoformat(),
            "stdoutTail": result.stdout.strip()[-1600:],
            "stderrTail": result.stderr.strip()[-1600:],
        }
    except subprocess.TimeoutExpired as error:
        return {
            "name": name,
            "status": "TIMEOUT",
            "exitCode": -1,
            "startedAtIso": started.isoformat(),
            "finishedAtIso": datetime.now(timezone.utc).isoformat(),
            "stdoutTail": (error.stdout or "")[-1600:] if isinstance(error.stdout, str) else "",
            "stderrTail": (error.stderr or "")[-1600:] if isinstance(error.stderr, str) else "",
        }


def tool(python_bin: str, script: str, *args: str) -> list[str]:
    return [python_bin, str(DEFAULT_REPO_ROOT / "tools" / script), *args]


def daily_tester_date_range(now: datetime | None = None, lookback_days: int = 2) -> tuple[str, str]:
    local_now = (now or datetime.now(timezone.utc)).astimezone(JST)
    safe_lookback = max(1, min(int(lookback_days or 1), 14))
    from_date = local_now.date() - timedelta(days=safe_lookback)
    to_date = local_now.date()
    return from_date.strftime("%Y.%m.%d"), to_date.strftime("%Y.%m.%d")


def daily_tester_timeout_seconds(value: int) -> int:
    return max(300, min(int(value or 900), 3600))


def run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).expanduser().resolve()
    runtime_dir = resolve_runtime_dir(repo_root, args.runtime_dir)
    dashboard_dir = resolve_dashboard_dir(repo_root, args.dashboard_dir)
    tester_root = Path(args.tester_root).expanduser() if args.tester_root else repo_root / "runtime/HFM_MT5_Tester_Isolated"
    hfm_root = resolve_hfm_root(repo_root, runtime_dir, args.hfm_root)
    if not tester_root.is_absolute():
        tester_root = repo_root / tester_root
    runtime_dir.mkdir(parents=True, exist_ok=True)
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    tester_from_date, tester_to_date = daily_tester_date_range(started, args.tester_lookback_days)
    tester_timeout = daily_tester_timeout_seconds(args.tester_terminal_timeout_seconds)
    steps: list[dict[str, Any]] = []
    common = ["--runtime-dir", str(runtime_dir)]
    repo_common = ["--repo-root", str(repo_root), "--runtime-dir", str(runtime_dir)]

    pipeline = [
        ("mt5_research_stats", tool(args.python_bin, "build_mt5_research_stats.py", *common)),
        ("mt5_entry_blockers", tool(args.python_bin, "build_mt5_entry_blockers.py", *common)),
        ("collect_paramlab_results", tool(args.python_bin, "collect_param_lab_results.py", *repo_common)),
        ("watch_paramlab_reports", tool(args.python_bin, "watch_param_lab_reports.py", *repo_common)),
        ("paramlab_run_recovery", tool(args.python_bin, "build_param_lab_run_recovery.py", *repo_common)),
        ("governance_advisor_first_pass", tool(args.python_bin, "build_governance_advisor.py", *common)),
        ("optimizer_v2_plan", tool(args.python_bin, "build_optimizer_v2_plan.py", *repo_common)),
        ("param_optimization_plan", tool(args.python_bin, "build_param_optimization_plan.py", *repo_common, "--max-tasks", str(max(args.max_tasks, 8)))),
        ("strategy_version_registry", tool(args.python_bin, "build_strategy_version_registry.py", *repo_common)),
        ("version_promotion_gate", tool(args.python_bin, "build_version_promotion_gate.py", *common)),
        ("paramlab_auto_scheduler", tool(args.python_bin, "build_param_lab_auto_scheduler.py", *repo_common, "--max-tasks", str(max(args.max_tasks, 1)))),
    ]
    for name, command in pipeline:
        steps.append(run_step(name, command, repo_root))

    if args.allow_tester_run:
        steps.append(run_step(
            "create_auto_tester_lock",
            tool(
                args.python_bin,
                "create_paramlab_auto_tester_lock.py",
                "--runtime-dir",
                str(runtime_dir),
                "--hfm-root",
                str(tester_root),
                "--ttl-minutes",
                "90",
                "--max-tasks",
                str(args.max_tasks),
                "--source",
                "daily_autopilot",
            ),
            repo_root,
        ))

    eval_command = tool(
        args.python_bin,
        "run_param_lab_auto_tester_window.py",
        "--repo-root",
        str(repo_root),
        "--runtime-dir",
        str(runtime_dir),
        "--hfm-root",
        str(hfm_root),
        "--tester-root",
        str(tester_root),
        "--max-tasks",
        str(args.max_tasks),
        "--from-date",
        tester_from_date,
        "--to-date",
        tester_to_date,
        "--terminal-timeout-seconds",
        str(tester_timeout),
    )
    steps.append(run_step("auto_tester_evaluate", eval_command, repo_root))
    auto_tester = read_json(runtime_dir / "QuantGod_AutoTesterWindow.json")
    can_run = bool(auto_tester.get("summary", {}).get("canRunTerminal"))
    run_attempted = False
    if args.allow_tester_run and can_run:
        run_attempted = True
        run_command = [
            *eval_command,
            "--run-terminal",
            "--authorized-strategy-tester",
            "--continuous-watch",
        ]
        steps.append(run_step("auto_tester_guarded_run", run_command, repo_root, timeout=tester_timeout + 180))
        steps.append(run_step("watch_paramlab_reports_after_run", tool(args.python_bin, "watch_param_lab_reports.py", *repo_common), repo_root))
        steps.append(run_step("version_promotion_gate_after_run", tool(args.python_bin, "build_version_promotion_gate.py", *common), repo_root))
        steps.append(run_step("governance_advisor_after_run", tool(args.python_bin, "build_governance_advisor.py", *common), repo_root))

    steps.append(run_step(
        "usd_jpy_automation_chain",
        tool(args.python_bin, "run_automation_chain.py", "--runtime-dir", str(runtime_dir), "--symbols", "USDJPYc", "once"),
        repo_root,
        timeout=1200,
        env_overrides={"QG_AUTOMATION_SYMBOLS": "USDJPYc"},
    ))
    steps.append(run_step("usd_jpy_strategy_policy", tool(args.python_bin, "run_usdjpy_strategy_lab.py", "--runtime-dir", str(runtime_dir), "build", "--write"), repo_root))
    steps.append(run_step("usd_jpy_ea_dry_run", tool(args.python_bin, "run_usdjpy_strategy_lab.py", "--runtime-dir", str(runtime_dir), "dry-run", "--write"), repo_root))
    steps.append(run_step("usd_jpy_live_loop", tool(args.python_bin, "run_usdjpy_live_loop.py", "--repo-root", str(repo_root), "--runtime-dir", str(runtime_dir), "once", "--write"), repo_root))
    steps.append(run_step("usd_jpy_runtime_dataset", tool(args.python_bin, "run_usdjpy_runtime_dataset.py", "--runtime-dir", str(runtime_dir), "build", "--write"), repo_root))
    steps.append(run_step("usd_jpy_replay_report", tool(args.python_bin, "run_usdjpy_runtime_dataset.py", "--runtime-dir", str(runtime_dir), "replay", "--write"), repo_root))
    steps.append(run_step("usd_jpy_param_tuning", tool(args.python_bin, "run_usdjpy_runtime_dataset.py", "--runtime-dir", str(runtime_dir), "tune", "--write"), repo_root))
    steps.append(run_step("usd_jpy_config_proposal", tool(args.python_bin, "run_usdjpy_runtime_dataset.py", "--runtime-dir", str(runtime_dir), "proposal", "--write"), repo_root))

    steps.append(run_step("daily_review", tool(args.python_bin, "build_daily_review.py", *common, "--max-actions", str(max(args.max_tasks, 1))), repo_root))
    daily_review = read_json(runtime_dir / "QuantGod_DailyReview.json")
    usdjpy_live_loop = read_json(runtime_dir / "live" / "QuantGod_USDJPYLiveLoopStatus.json")
    usdjpy_dataset = read_json(runtime_dir / "datasets" / "usdjpy" / "QuantGod_USDJPYRuntimeDataset.json")
    usdjpy_replay = read_json(runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYReplayReport.json")
    usdjpy_tuning = read_json(runtime_dir / "adaptive" / "QuantGod_USDJPYParamTuningReport.json")
    usdjpy_proposal = read_json(runtime_dir / "adaptive" / "QuantGod_USDJPYLiveConfigProposal.json")

    status = "OK" if all(step["status"] == "OK" for step in steps) else "PARTIAL"
    payload = {
        "schemaVersion": 1,
        "mode": "QUANTGOD_DAILY_AUTOPILOT_SAFE_LOOP",
        "generatedAtIso": datetime.now(timezone.utc).isoformat(),
        "startedAtIso": started.isoformat(),
        "runtimeDir": str(runtime_dir),
        "dashboardDir": str(dashboard_dir),
        "allowTesterRun": bool(args.allow_tester_run),
        "testerRunAttempted": run_attempted,
        "testerTodoMode": {
            "mode": "DAILY_TODO_SHORT_WINDOW",
            "fromDate": tester_from_date,
            "toDate": tester_to_date,
            "lookbackDays": max(1, min(int(args.tester_lookback_days or 1), 14)),
            "terminalTimeoutSeconds": tester_timeout,
            "fullHistoricalRuns": "Use tools/run_param_lab.py or an explicit weekend/full-run automation, not the daily autopilot.",
        },
        "status": status,
        "safety": {
            "mutatesMt5": False,
            "orderSendAllowed": False,
            "walletWriteAllowed": False,
            "livePresetMutationAllowed": False,
            "autoApplyLivePromotion": False,
        },
        "steps": steps,
        "dailyReviewSummary": daily_review.get("summary", {}),
        "usdJpyLiveLoopSummary": {
            "state": usdjpy_live_loop.get("state", ""),
            "stateZh": usdjpy_live_loop.get("stateZh", ""),
            "policyReady": usdjpy_live_loop.get("policyReady", False),
            "presetReady": usdjpy_live_loop.get("presetReady", False),
            "runtimeReady": usdjpy_live_loop.get("runtimeReady", False),
            "advisoryRoute": usdjpy_live_loop.get("advisoryRouteZh", "所有策略仅做 Shadow/ReadOnly 复核"),
            "whyNoEntry": usdjpy_live_loop.get("whyNoEntry", []),
            "nextActions": usdjpy_live_loop.get("nextActions", []),
        },
        "usdJpyEvolutionSummary": {
            "datasetSamples": usdjpy_dataset.get("summary", {}).get("sampleCount", 0),
            "readySignalCount": usdjpy_dataset.get("summary", {}).get("readySignalCount", 0),
            "actualEntryCount": usdjpy_dataset.get("summary", {}).get("actualEntryCount", 0),
            "missedOpportunityCount": usdjpy_replay.get("summary", {}).get("missedOpportunityCount", 0),
            "earlyExitCount": usdjpy_replay.get("summary", {}).get("earlyExitCount", 0),
            "paramCandidateCount": usdjpy_tuning.get("summary", {}).get("candidateCount", 0),
            "proposalStatus": usdjpy_proposal.get("status", ""),
            "proposalStatusZh": usdjpy_proposal.get("statusZh", ""),
            "autoApplyAllowed": usdjpy_proposal.get("autoApplyAllowed", False),
            "requiresAutonomousGovernance": bool(usdjpy_proposal.get("requiresAutonomousGovernance", False)),
            "completedByAgent": True,
            "autoAppliedByAgent": bool(usdjpy_proposal.get("autoAppliedByAgent", False)),
        },
        "codexReview": daily_review.get("codexReview", {}),
        "promotionRecommendations": daily_review.get("promotionRecommendations", []),
        "nextActions": daily_review.get("nextActions", []),
    }
    output = runtime_dir / DEFAULT_AUTOPILOT_NAME
    ledger = runtime_dir / DEFAULT_AUTOPILOT_LEDGER
    write_json(output, payload)
    append_csv(
        ledger,
        {
            "GeneratedAtIso": payload["generatedAtIso"],
            "Status": status,
            "StepCount": len(steps),
            "ErrorCount": sum(1 for step in steps if step["status"] != "OK"),
            "AllowTesterRun": str(bool(args.allow_tester_run)).lower(),
            "TesterRunAttempted": str(run_attempted).lower(),
            "DailyReviewDateJst": daily_review.get("summary", {}).get("dailyReviewDateJst", ""),
            "DailyParamActions": daily_review.get("summary", {}).get("paramActionCount", ""),
            "DailyParamWaitWindow": daily_review.get("summary", {}).get("paramWaitWindowCount", ""),
            "TodayTodoStatus": daily_review.get("summary", {}).get("todayTodoStatus", ""),
            "TesterFromDate": tester_from_date,
            "TesterToDate": tester_to_date,
            "TesterTimeoutSeconds": tester_timeout,
            "NextTesterWindowLabel": daily_review.get("summary", {}).get("nextTesterWindowLabel", ""),
            "PromotionReviewCount": daily_review.get("summary", {}).get("promotionReviewCount", ""),
            "CodexReviewRequired": str(bool(daily_review.get("codexReview", {}).get("required"))).lower(),
            "UsdJpyLiveLoopState": usdjpy_live_loop.get("state", ""),
            "UsdJpyPolicyReady": str(bool(usdjpy_live_loop.get("policyReady"))).lower(),
            "UsdJpyPresetReady": str(bool(usdjpy_live_loop.get("presetReady"))).lower(),
            "UsdJpyRuntimeReady": str(bool(usdjpy_live_loop.get("runtimeReady"))).lower(),
            "UsdJpyDatasetSamples": usdjpy_dataset.get("summary", {}).get("sampleCount", ""),
            "UsdJpyMissedOpportunities": usdjpy_replay.get("summary", {}).get("missedOpportunityCount", ""),
            "UsdJpyParamCandidateCount": usdjpy_tuning.get("summary", {}).get("candidateCount", ""),
            "UsdJpyConfigProposalStatus": usdjpy_proposal.get("status", ""),
        },
        [
            "GeneratedAtIso",
            "Status",
            "StepCount",
            "ErrorCount",
            "AllowTesterRun",
            "TesterRunAttempted",
            "DailyReviewDateJst",
            "DailyParamActions",
            "DailyParamWaitWindow",
            "TodayTodoStatus",
            "TesterFromDate",
            "TesterToDate",
            "TesterTimeoutSeconds",
            "NextTesterWindowLabel",
            "PromotionReviewCount",
            "CodexReviewRequired",
            "UsdJpyLiveLoopState",
            "UsdJpyPolicyReady",
            "UsdJpyPresetReady",
            "UsdJpyRuntimeReady",
            "UsdJpyDatasetSamples",
            "UsdJpyMissedOpportunities",
            "UsdJpyParamCandidateCount",
            "UsdJpyConfigProposalStatus",
        ],
    )
    print(
        "DAILY_AUTOPILOT "
        f"status={status} steps={len(steps)} errors={sum(1 for step in steps if step['status'] != 'OK')} "
        f"testerRunAttempted={run_attempted} output={output}"
    )
    return payload


def main() -> int:
    args = parse_args()
    if not args.loop:
        args.once = True
    while True:
        run_cycle(args)
        if args.once:
            return 0
        time.sleep(max(60.0, float(args.interval_minutes) * 60.0))


if __name__ == "__main__":
    raise SystemExit(main())
