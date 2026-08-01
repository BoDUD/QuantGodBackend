#!/usr/bin/env python3
"""Prepare and optionally run QuantGod ParamLab Strategy Tester tasks.

ParamLab is the offline runner for QuantGod_ParamOptimizationPlan.json. It
materializes tester-only presets and MT5 tester configs for ranked RSI/BB/MACD/SR
parameter candidates, records the run status, and can parse tester reports. It
does not mutate the HFM live preset and does not send orders.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from tools.auto_tester_window_guard import (
        LOCK_NAME,
        evaluate_execution_gate,
        read_json as read_guard_json,
        validate_materialized_task,
        validate_tester_profile_matches,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from auto_tester_window_guard import (
        LOCK_NAME,
        evaluate_execution_gate,
        read_json as read_guard_json,
        validate_materialized_task,
        validate_tester_profile_matches,
    )


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HFM_ROOT = Path(r"C:\Program Files\HFM Metatrader 5")
DEFAULT_RUNTIME_DIR = DEFAULT_HFM_ROOT / "MQL5" / "Files"
PLAN_NAME = "QuantGod_ParamOptimizationPlan.json"
STATUS_NAME = "QuantGod_ParamLabStatus.json"
AGENT_ARTIFACT_NAMES = {
    "QuantGod_Dashboard.json",
    "QuantGod_MT5_ShadowStatus.txt",
    "QuantGod_TradeJournal.csv",
    "QuantGod_CloseHistory.csv",
    "QuantGod_TradeOutcomeLabels.csv",
    "QuantGod_TradeEventLinks.csv",
    "QuantGod_ShadowOutcomeLedger.csv",
    "QuantGod_ShadowCandidateOutcomeLedger.csv",
    "QuantGod_StrategyEvaluationReport.csv",
    "QuantGod_RegimeEvaluationReport.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare QuantGod ParamLab tester tasks.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--hfm-root", default=str(DEFAULT_HFM_ROOT))
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--plan", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--max-tasks", type=int, default=4)
    parser.add_argument("--route", action="append", default=[], help="Route key to include. Can be repeated.")
    parser.add_argument("--candidate-id", action="append", default=[], help="Exact candidate id to include.")
    parser.add_argument(
        "--rank-mode",
        choices=("route-balanced", "score"),
        default="route-balanced",
        help="Default picks the top task per route before filling by score.",
    )
    parser.add_argument("--from-date", default=(datetime.now() - timedelta(days=90)).strftime("%Y.%m.%d"))
    parser.add_argument("--to-date", default=datetime.now().strftime("%Y.%m.%d"))
    parser.add_argument(
        "--terminal-timeout-seconds",
        type=int,
        default=0,
        help="Kill the Strategy Tester terminal child after this many seconds. 0 means no runner-level timeout.",
    )
    parser.add_argument("--login", default="90000001")
    parser.add_argument("--server", default="SyntheticBroker-Demo")
    parser.add_argument("--run-terminal", action="store_true", help="Launch MT5 Strategy Tester for selected tasks.")
    parser.add_argument(
        "--authorized-strategy-tester",
        action="store_true",
        help="Required with --run-terminal to confirm this is a controlled Strategy Tester run.",
    )
    parser.add_argument(
        "--allow-outside-window",
        action="store_true",
        help="Allow --run-terminal outside the regular weekend tester window only when the authorization lock allows it.",
    )
    parser.add_argument(
        "--auto-tester-lock",
        default="",
        help="Authorization lock JSON required for --run-terminal. Defaults to <runtime-dir>/QuantGod_AutoTesterWindow.lock.json.",
    )
    parser.add_argument(
        "--max-live-snapshot-age-minutes",
        type=int,
        default=30,
        help="Maximum age for QuantGod_Dashboard.json before --run-terminal is blocked.",
    )
    parser.add_argument(
        "--wineprefix",
        default="",
        help="Optional Wine prefix for Strategy Tester launch. On macOS, defaults to QG_PARAMLAB_WINEPREFIX, then QG_WINEPREFIX, then the standard MT5 prefix.",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
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


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


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


def normalize_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def load_preset_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return read_text(path).splitlines()


def merge_preset_lines(base_lines: list[str], overrides: dict[str, Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for line in base_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, tail = line.split("=", 1)
        if key in overrides:
            value = normalize_value(overrides[key])
            if "||" in tail:
                _, suffix = tail.split("||", 1)
                output.append(f"{key}={value}||{suffix}")
            else:
                output.append(f"{key}={value}")
            seen.add(key)
        else:
            output.append(line)
    for key in sorted(overrides):
        if key not in seen:
            output.append(f"{key}={normalize_value(overrides[key])}")
    return output


def write_ascii_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii", errors="ignore")


def timeframe_to_period(timeframe: str) -> str:
    value = str(timeframe or "").upper()
    if value in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
        return value
    return "M15"


def wine_windows_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    return "Z:" + str(resolved).replace("/", "\\")


def mt5_terminal_command(
    terminal: Path,
    config_path: Path,
    login: str,
    wineprefix_override: str = "",
) -> tuple[list[str], Path | None, dict[str, str] | None]:
    login_arg = f"/login:{login}" if str(login or "").strip() else ""
    if sys.platform != "darwin":
        command = [str(terminal)]
        if login_arg:
            command.append(login_arg)
        command.append(f"/config:{config_path}")
        return command, None, None
    wine64 = Path(os.environ.get("QG_WINE64") or (Path.home() / "Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine64"))
    wineprefix = Path(
        wineprefix_override
        or os.environ.get("QG_PARAMLAB_WINEPREFIX")
        or os.environ.get("QG_WINEPREFIX")
        or (Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5")
    )
    command = [str(wine64), "terminal64.exe", "/portable"]
    if login_arg:
        command.append(login_arg)
    command.append(f"/config:{wine_windows_path(config_path)}")
    env = {**os.environ, "WINEPREFIX": str(wineprefix)}
    return command, terminal.parent, env


def _tail_text(value: str, max_chars: int = 4000) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def run_terminal_process(
    command: list[str],
    cwd: Path | None,
    env: dict[str, str] | None,
    timeout_seconds: int,
) -> tuple[int, bool, dict[str, str]]:
    timeout = int(timeout_seconds or 0)
    popen_kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "env": env,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **popen_kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout if timeout > 0 else None)
        return process.returncode, False, {
            "stdoutTail": _tail_text(stdout or ""),
            "stderrTail": _tail_text(stderr or ""),
        }
    except subprocess.TimeoutExpired:
        if sys.platform != "win32":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if sys.platform != "win32":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=10)
        stdout = ""
        stderr = ""
        try:
            stdout, stderr = process.communicate(timeout=1)
        except Exception:
            pass
        return -9, True, {
            "stdoutTail": _tail_text(stdout or ""),
            "stderrTail": _tail_text(stderr or ""),
        }


def classify_terminal_blockers(
    terminal_process: dict[str, str],
    *,
    terminal_exit_code: int | None = None,
    html_report_exists: bool = False,
) -> list[dict[str, str]]:
    stdout = str(terminal_process.get("stdoutTail") or "")
    stderr = str(terminal_process.get("stderrTail") or "")
    combined = f"{stdout}\n{stderr}".lower()
    blockers: list[dict[str, str]] = []
    if "can't check in server_mach_port" in combined or "wine server failed to run" in combined:
        blockers.append({
            "code": "WINE_SERVER_MACH_PORT_UNAVAILABLE",
            "severity": "terminal_environment",
            "reasonZh": "Wine server Mach port 无法接入，隔离 MT5 Strategy Tester 没有真正启动。",
            "nextActionZh": "需要在可用的 macOS 用户图形会话/Wine 会话中重试 tester，或先重启 Wine/MT5 tester 环境。",
        })
    if "wineserver: bind: operation not permitted" in combined:
        blockers.append({
            "code": "WINE_SERVER_BIND_BLOCKED_BY_SANDBOX",
            "severity": "terminal_environment",
            "reasonZh": "Wine server bind 被当前沙盒/权限环境拦截，隔离 MT5 Strategy Tester 没有真正启动。",
            "nextActionZh": "需要在已授权的非沙盒 Wine/MT5 tester 环境中重试。",
        })
    if terminal_exit_code == 191 and not html_report_exists:
        blockers.append({
            "code": "MT5_TERMINAL_EXIT_191_REPORT_MISSING",
            "severity": "strategy_tester_runtime",
            "reasonZh": "MT5 terminal 返回 191 且没有生成 HTML tester 报告，Strategy Tester 未完成可验证回测。",
            "nextActionZh": "检查隔离 tester 配置、报告路径、历史数据与 MT5 tester profile；修复后在同一 tester-only lock/window 中重试。",
        })
    return blockers


def tester_config_text(
    *,
    login: str,
    server: str,
    symbol: str,
    period: str,
    preset_name: str,
    from_date: str,
    to_date: str,
    report_path: Path | str,
) -> str:
    return f"""[Common]
Login={login}
Server={server}
KeepPrivate=1

[Experts]
AllowLiveTrading=0
AllowDllImport=0
Enabled=1
Account=0
Profile=0

[Tester]
Login={login}
Expert=QuantGod_MultiStrategy.ex5
ExpertParameters={preset_name}
Symbol={symbol}
Period={period}
Model=1
ExecutionMode=0
Optimization=0
FromDate={from_date}
ToDate={to_date}
ForwardMode=0
Deposit=10000
Currency=USC
Leverage=1000
Report={report_path}
ReplaceReport=1
ShutdownTerminal=1
"""


def metric_from_report(text: str, labels: list[str]) -> float | None:
    for label in labels:
        escaped = re.escape(label)
        patterns = [
            rf"{escaped}\s*</[^>]+>\s*<[^>]+>\s*([-+]?[0-9][0-9\s,]*(?:\.[0-9]+)?)",
            rf"{escaped}[^-+0-9]*([-+]?[0-9][0-9\s,]*(?:\.[0-9]+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                raw = match.group(1).replace(" ", "").replace(",", "")
                try:
                    number = float(raw)
                    if math.isfinite(number):
                        return number
                except Exception:
                    pass
    return None


def parse_report(report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        return {
            "reportExists": False,
            "parseStatus": "REPORT_MISSING",
            "closedTrades": None,
            "netProfit": None,
            "profitFactor": None,
            "winRate": None,
        }
    text = read_text(report_path)
    net_profit = metric_from_report(text, ["Total Net Profit", "Net Profit", "Total profit"])
    profit_factor = metric_from_report(text, ["Profit Factor"])
    total_trades = metric_from_report(text, ["Total Trades", "Trades"])
    win_rate = metric_from_report(text, ["Profit Trades (% of total)", "Win rate", "Winning trades"])
    return {
        "reportExists": True,
        "parseStatus": "PARSED_PARTIAL" if net_profit is not None or total_trades is not None else "REPORT_FOUND_UNPARSED",
        "closedTrades": total_trades,
        "netProfit": net_profit,
        "profitFactor": profit_factor,
        "winRate": win_rate,
    }


def latest_agent_files_dir(hfm_root: Path) -> Path | None:
    tester_root = hfm_root / "Tester"
    if not tester_root.exists():
        return None
    candidates = [path / "MQL5" / "Files" for path in tester_root.glob("Agent-*") if (path / "MQL5" / "Files").exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def copy_agent_artifacts(hfm_root: Path, destination_dir: Path) -> bool:
    source_dir = latest_agent_files_dir(hfm_root)
    if source_dir is None:
        return False
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied = False
    for source in source_dir.iterdir():
        if source.is_file() and source.name in AGENT_ARTIFACT_NAMES:
            shutil.copy2(source, destination_dir / source.name)
            copied = True
    return copied


def parse_agent_artifacts(artifact_dir: Path, report_metrics: dict[str, Any]) -> dict[str, Any]:
    if not artifact_dir.exists():
        return report_metrics

    trade_rows = csv_rows(artifact_dir / "QuantGod_TradeJournal.csv")
    close_rows = csv_rows(artifact_dir / "QuantGod_CloseHistory.csv")
    exit_rows = [row for row in trade_rows if str(row.get("EventType") or "").upper() == "EXIT"]
    closed_rows = close_rows or exit_rows
    closed_trades = len(closed_rows)
    net_profit = 0.0
    for row in closed_rows:
        try:
            net_profit += float(str(row.get("NetProfit") or "0").strip())
        except Exception:
            pass

    dashboard = read_json(artifact_dir / "QuantGod_Dashboard.json")
    runtime = dashboard.get("runtime") if isinstance(dashboard.get("runtime"), dict) else {}
    account = dashboard.get("account") if isinstance(dashboard.get("account"), dict) else {}
    strategy_rows = csv_rows(artifact_dir / "QuantGod_StrategyEvaluationReport.csv")
    regime_rows = csv_rows(artifact_dir / "QuantGod_RegimeEvaluationReport.csv")

    metrics = dict(report_metrics)
    metrics.update(
        {
            "reportExists": True,
            "htmlReportExists": bool(report_metrics.get("reportExists")),
            "testerEvidenceExists": True,
            "parseStatus": "PARSED_AGENT_ARTIFACTS",
            "evidenceSource": "agent_artifacts",
            "artifactDir": str(artifact_dir),
            "closedTrades": report_metrics.get("closedTrades") if report_metrics.get("closedTrades") is not None else closed_trades,
            "netProfit": report_metrics.get("netProfit") if report_metrics.get("netProfit") is not None else round(net_profit, 6),
            "profitFactor": report_metrics.get("profitFactor"),
            "winRate": report_metrics.get("winRate"),
            "finalBalance": account.get("balance"),
            "tradeStatus": runtime.get("tradeStatus"),
            "executionEnabled": runtime.get("executionEnabled"),
            "readOnlyMode": runtime.get("readOnlyMode"),
            "strategyEvaluationRows": len(strategy_rows),
            "regimeEvaluationRows": len(regime_rows),
        }
    )
    if closed_trades == 0 and not strategy_rows and not regime_rows:
        metrics["sampleStatus"] = "NO_TRADES_IN_TEST_WINDOW"
    return metrics


def sync_tester_profile(preset_path: Path, profile_path: Path) -> bool:
    if not preset_path.exists():
        return False
    values: dict[str, str] = {}
    for line in read_text(preset_path).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith((";", "#")) and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key] = value.split("||", 1)[0]
    if not values:
        return False

    profile_lines = load_preset_lines(profile_path) or [
        "; generated by QuantGod ParamLab",
        "; this file contains input parameters for testing QuantGod_MultiStrategy expert advisor",
    ]
    output: list[str] = []
    seen: set[str] = set()
    for line in profile_lines:
        if "=" not in line or line.lstrip().startswith((";", "#")):
            output.append(line)
            continue
        key, tail = line.split("=", 1)
        if key in values:
            if "||" in tail:
                _, suffix = tail.split("||", 1)
                output.append(f"{key}={values[key]}||{suffix}")
            else:
                output.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key in sorted(values):
        if key not in seen:
            output.append(f"{key}={values[key]}")
    write_ascii_lines(profile_path, output)
    return True


def in_regular_tester_window(now_jst: datetime | None = None) -> bool:
    now = now_jst or datetime.now(timezone(timedelta(hours=9)))
    weekday = now.weekday()  # Monday=0
    minutes = now.hour * 60 + now.minute
    weekday_night_window = weekday <= 4 and (20 * 60 + 10) <= minutes <= (23 * 60 + 30)
    saturday_window = weekday == 5 and (7 * 60 + 10) <= minutes <= (9 * 60 + 30)
    sunday_window = weekday == 6 and (8 * 60) <= minutes <= (9 * 60 + 30)
    return weekday_night_window or saturday_window or sunday_window


def select_tasks(
    plan: dict[str, Any],
    max_tasks: int,
    routes: list[str],
    candidate_ids: list[str],
    rank_mode: str,
) -> list[dict[str, Any]]:
    tasks = plan.get("backtestTasks") if isinstance(plan.get("backtestTasks"), list) else []
    route_filter = {item.strip() for item in routes if item.strip()}
    id_filter = {item.strip() for item in candidate_ids if item.strip()}
    selected = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if route_filter and str(task.get("routeKey", "")) not in route_filter:
            continue
        if id_filter and str(task.get("candidateId", "")) not in id_filter:
            continue
        selected.append(task)
    selected.sort(key=lambda item: int(item.get("rank") or 9999))
    limit = max(1, max_tasks)
    if rank_mode == "score" or id_filter or route_filter:
        return selected[:limit]

    by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in selected:
        by_route[str(task.get("routeKey") or "UNKNOWN")].append(task)

    route_balanced: list[dict[str, Any]] = []
    for route_key in sorted(by_route):
        by_route[route_key].sort(key=lambda item: int(item.get("rank") or 9999))
        route_balanced.append(by_route[route_key][0])
    used = {id(item) for item in route_balanced}
    for task in selected:
        if len(route_balanced) >= limit:
            break
        if id(task) not in used:
            route_balanced.append(task)
            used.add(id(task))
    route_balanced.sort(key=lambda item: int(item.get("rank") or 9999))
    return route_balanced[:limit]


def candidate_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for route_plan in plan.get("routePlans", []) if isinstance(plan.get("routePlans"), list) else []:
        if not isinstance(route_plan, dict):
            continue
        for candidate in route_plan.get("candidates", []) if isinstance(route_plan.get("candidates"), list) else []:
            if isinstance(candidate, dict) and candidate.get("candidateId"):
                result[str(candidate["candidateId"])] = candidate
    return result


def update_plan_with_run(plan: dict[str, Any], status: dict[str, Any], plan_path: Path) -> None:
    task_status = {str(task.get("candidateId")): task for task in status.get("tasks", []) if isinstance(task, dict)}
    for task in plan.get("backtestTasks", []) if isinstance(plan.get("backtestTasks"), list) else []:
        candidate_id = str(task.get("candidateId", ""))
        if candidate_id in task_status:
            result = task_status[candidate_id]
            task["status"] = result.get("status", task.get("status", ""))
            task["paramLabRunId"] = status.get("runId", "")
            task["configPath"] = result.get("configPath", "")
            task["reportPath"] = result.get("reportPath", "")
            task["presetPath"] = result.get("presetPath", "")
            task["hfmPresetPath"] = result.get("hfmPresetPath", "")
            task["metrics"] = result.get("metrics", {})
    plan["paramLabLatestRun"] = {
        "runId": status.get("runId", ""),
        "generatedAtIso": status.get("generatedAtIso", ""),
        "mode": status.get("mode", ""),
        "runTerminal": status.get("runTerminal", False),
        "selectedTaskCount": status.get("selectedTaskCount", 0),
        "summary": status.get("summary", {}),
    }
    write_json(plan_path, plan)


def build_runner_status(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root)
    hfm_root = Path(args.hfm_root)
    runtime_dir = Path(args.runtime_dir)
    plan_path = Path(args.plan) if args.plan else runtime_dir / PLAN_NAME
    output_path = Path(args.output) if args.output else runtime_dir / STATUS_NAME
    plan = read_json(plan_path)
    if not plan:
        raise FileNotFoundError(f"Param optimization plan not found or unreadable: {plan_path}")

    run_terminal_gate: dict[str, Any] = {}
    if args.run_terminal:
        if not args.authorized_strategy_tester:
            raise RuntimeError("--run-terminal requires --authorized-strategy-tester.")
        lock_path = Path(args.auto_tester_lock) if args.auto_tester_lock else runtime_dir / LOCK_NAME
        scheduler_doc = read_guard_json(plan_path)
        run_terminal_gate = evaluate_execution_gate(
            scheduler=scheduler_doc,
            runtime_dir=runtime_dir,
            hfm_root=hfm_root,
            repo_root=repo_root,
            lock_path=lock_path,
            max_tasks=args.max_tasks,
            allow_outside_window=args.allow_outside_window,
            expected_login=args.login,
            expected_server=args.server,
            max_live_snapshot_age_minutes=args.max_live_snapshot_age_minutes,
        )
        if not run_terminal_gate.get("canRunTerminal"):
            blockers = ", ".join(run_terminal_gate.get("blockers") or ["unknown_guard_blocker"])
            raise RuntimeError(f"--run-terminal blocked by AUTO_TESTER_WINDOW guard: {blockers}")

    terminal = hfm_root / "terminal64.exe"
    hfm_presets = hfm_root / "MQL5" / "Presets"
    hfm_tester_profiles = hfm_root / "MQL5" / "Profiles" / "Tester"
    hfm_experts = hfm_root / "MQL5" / "Experts"

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = repo_root / "archive" / "param-lab" / "runs" / run_id
    preset_dir = run_dir / "presets"
    config_dir = run_dir / "configs"
    report_dir = run_dir / "reports"
    agent_artifact_root = run_dir / "agent-files"
    for directory in (preset_dir, config_dir, report_dir, agent_artifact_root, hfm_presets, hfm_tester_profiles):
        directory.mkdir(parents=True, exist_ok=True)

    source_synced = False
    binary_synced = False
    source_path = repo_root / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"
    binary_path = repo_root / "MQL5" / "Experts" / "QuantGod_MultiStrategy.ex5"
    if source_path.exists():
        hfm_experts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, hfm_experts / source_path.name)
        source_synced = True
    if binary_path.exists():
        hfm_experts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary_path, hfm_experts / binary_path.name)
        binary_synced = True

    candidates = candidate_by_id(plan)
    selected = select_tasks(plan, args.max_tasks, args.route, args.candidate_id, args.rank_mode)
    task_results: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []

    for task in selected:
        candidate_id = str(task.get("candidateId", ""))
        candidate = candidates.get(candidate_id, {})
        symbol = str(task.get("symbol") or candidate.get("symbol") or "")
        route_key = str(task.get("routeKey") or candidate.get("routeKey") or "")
        timeframe = str(task.get("timeframe") or candidate.get("timeframe") or "M15")
        preset_name = str(task.get("presetName") or candidate.get("presetName") or f"QuantGod_MT5_ParamLab_{candidate_id}.set")
        base_preset = Path(str(candidate.get("basePreset") or repo_root / "MQL5" / "Presets" / f"QuantGod_MT5_HFM_Backtest_{symbol}.set"))
        overrides = task.get("presetOverrides") if isinstance(task.get("presetOverrides"), dict) else candidate.get("presetOverrides", {})
        if not isinstance(overrides, dict):
            overrides = {}

        local_preset = preset_dir / preset_name
        hfm_preset = hfm_presets / preset_name
        config_path = config_dir / f"{candidate_id}.ini"
        symbol_report_dir = report_dir / symbol
        symbol_report_dir.mkdir(parents=True, exist_ok=True)
        report_path = symbol_report_dir / f"{candidate_id}.html"

        merged_lines = merge_preset_lines(load_preset_lines(base_preset), overrides)
        write_ascii_lines(local_preset, merged_lines)
        shutil.copy2(local_preset, hfm_preset)
        report_path_for_config: Path | str = report_path
        if sys.platform == "darwin":
            report_path_for_config = wine_windows_path(report_path)
        config_path.write_text(
            tester_config_text(
                login=args.login,
                server=args.server,
                symbol=symbol,
                period=timeframe_to_period(timeframe),
                preset_name=preset_name,
                from_date=args.from_date,
                to_date=args.to_date,
                report_path=report_path_for_config,
            ),
            encoding="ascii",
        )

        materialized_guard = validate_materialized_task(
            {
                "candidateId": candidate_id,
                "routeKey": route_key,
                "symbol": symbol,
                "timeframe": timeframe,
                "configPath": str(config_path),
                "presetPath": str(local_preset),
                "hfmPresetPath": str(hfm_preset),
            },
            repo_root=repo_root,
            hfm_root=hfm_root,
        )
        if not materialized_guard.get("ok"):
            blockers = ", ".join(materialized_guard.get("blockers") or ["unknown_materialized_guard_blocker"])
            raise RuntimeError(f"Materialized tester task failed AUTO_TESTER_WINDOW guard for {candidate_id}: {blockers}")

        profile_synced = False
        terminal_exit_code: int | None = None
        terminal_timed_out = False
        terminal_process: dict[str, str] = {}
        terminal_blockers: list[dict[str, str]] = []
        agent_files_copied = False
        artifact_dir = agent_artifact_root / candidate_id
        runner_status = "CONFIG_READY"
        env: dict[str, str] | None = None
        if args.run_terminal:
            if not terminal.exists():
                raise FileNotFoundError(f"HFM terminal not found: {terminal}")
            tester_profile = hfm_tester_profiles / "QuantGod_MultiStrategy.set"
            profile_synced = sync_tester_profile(hfm_preset, tester_profile)
            profile_guard = validate_tester_profile_matches(tester_profile, hfm_preset)
            if not profile_guard.get("ok"):
                blockers = ", ".join(profile_guard.get("blockers") or ["unknown_profile_guard_blocker"])
                raise RuntimeError(f"Tester profile failed AUTO_TESTER_WINDOW guard for {candidate_id}: {blockers}")
            if profile_synced:
                shutil.copy2(tester_profile, hfm_tester_profiles / preset_name)
            command, cwd, env = mt5_terminal_command(terminal, config_path, args.login, args.wineprefix)
            terminal_exit_code, terminal_timed_out, terminal_process = run_terminal_process(
                command,
                cwd,
                env,
                args.terminal_timeout_seconds,
            )
            agent_files_copied = copy_agent_artifacts(hfm_root, artifact_dir)
            runner_status = "RUN_ATTEMPTED"

        metrics = parse_report(report_path)
        if agent_files_copied:
            metrics = parse_agent_artifacts(artifact_dir, metrics)
        html_report_exists = bool(metrics.get("htmlReportExists", metrics.get("reportExists")))
        if args.run_terminal:
            terminal_blockers = classify_terminal_blockers(
                terminal_process,
                terminal_exit_code=terminal_exit_code,
                html_report_exists=html_report_exists,
            )
        if html_report_exists and metrics["parseStatus"].startswith("PARSED"):
            runner_status = metrics["parseStatus"]
        elif args.run_terminal and terminal_exit_code not in (None, 0) and not html_report_exists:
            runner_status = "TERMINAL_EXIT_NONZERO_REPORT_MISSING"
        elif terminal_timed_out:
            runner_status = "TERMINAL_TIMEOUT"
        elif args.run_terminal and not html_report_exists:
            runner_status = "REPORT_MISSING_AFTER_RUN"

        result = {
            "rank": task.get("rank"),
            "candidateId": candidate_id,
            "routeKey": route_key,
            "symbol": symbol,
            "timeframe": timeframe,
            "variant": candidate.get("variant", ""),
            "score": candidate.get("score", task.get("score")),
            "status": runner_status,
            "configPath": str(config_path),
            "reportPath": str(report_path),
            "artifactDir": str(artifact_dir),
            "agentFilesCopied": agent_files_copied,
            "presetPath": str(local_preset),
            "hfmPresetPath": str(hfm_preset),
            "testerProfileSynced": profile_synced,
            "terminalExitCode": terminal_exit_code,
            "terminalTimedOut": terminal_timed_out,
            "terminalTimeoutSeconds": int(args.terminal_timeout_seconds or 0),
            "winePrefix": str((env or {}).get("WINEPREFIX", "")),
            "terminalProcess": terminal_process,
            "terminalBlockers": terminal_blockers,
            "metrics": metrics,
            "materializedGuard": materialized_guard,
            "livePresetMutation": False,
        }
        task_results.append(result)
        ledger_rows.append({
            "RunId": run_id,
            "GeneratedAtIso": datetime.now(timezone.utc).isoformat(),
            "CandidateId": candidate_id,
            "RouteKey": route_key,
            "Symbol": symbol,
            "Timeframe": timeframe,
            "Variant": candidate.get("variant", ""),
            "Status": runner_status,
            "ClosedTrades": metrics.get("closedTrades"),
            "NetProfit": metrics.get("netProfit"),
            "ProfitFactor": metrics.get("profitFactor"),
            "WinRate": metrics.get("winRate"),
            "TerminalTimedOut": str(terminal_timed_out).lower(),
            "ConfigPath": str(config_path),
            "ReportPath": str(report_path),
            "ArtifactDir": str(artifact_dir),
        })

    by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in task_results:
        by_route[str(task.get("routeKey", ""))].append(task)
    top_by_route = {}
    for route_key, rows in by_route.items():
        rows.sort(key=lambda item: int(item.get("rank") or 9999))
        top_by_route[route_key] = rows[0]

    summary = {
        "configReadyCount": sum(1 for item in task_results if item["status"] == "CONFIG_READY"),
        "runAttemptedCount": sum(1 for item in task_results if item["terminalExitCode"] is not None),
        "terminalTimeoutCount": sum(1 for item in task_results if item.get("terminalTimedOut")),
        "htmlReportParsedCount": sum(1 for item in task_results if item["metrics"].get("htmlReportExists")),
        "reportParsedCount": sum(1 for item in task_results if item["metrics"].get("htmlReportExists")),
        "agentEvidenceParsedCount": sum(1 for item in task_results if item["metrics"].get("testerEvidenceExists")),
        "terminalNonzeroCount": sum(1 for item in task_results if item.get("terminalExitCode") not in (None, 0)),
        "terminalBlockerCodes": sorted({
            str(blocker.get("code"))
            for item in task_results
            for blocker in item.get("terminalBlockers", [])
            if blocker.get("code")
        }),
        "selectedTaskCount": len(task_results),
        "sourceSynced": source_synced,
        "binarySynced": binary_synced,
    }
    status = {
        "schemaVersion": 1,
        "source": "QuantGod ParamLab controlled runner",
        "generatedAtIso": datetime.now(timezone.utc).isoformat(),
        "runId": run_id,
        "mode": "STRATEGY_TESTER_RUN" if args.run_terminal else "CONFIG_ONLY",
        "runTerminal": bool(args.run_terminal),
        "runtimeDir": str(runtime_dir),
        "planPath": str(plan_path),
        "archiveDir": str(run_dir),
        "selectedTaskCount": len(task_results),
        "rankMode": args.rank_mode,
        "testerDateRange": {
            "fromDate": args.from_date,
            "toDate": args.to_date,
            "terminalTimeoutSeconds": int(args.terminal_timeout_seconds or 0),
        },
        "summary": summary,
        "autoTesterWindowGate": run_terminal_gate,
        "topByRoute": top_by_route,
        "tasks": task_results,
        "hardGuards": [
            "No HFM live preset was modified.",
            "No broker live order path is used by this runner.",
            "Generated presets are ParamLab tester-only files.",
            "Strategy Tester launch requires --run-terminal and --authorized-strategy-tester.",
            "Regular unattended tester runs are blocked outside the weekend tester window.",
            "Run-terminal is blocked unless the live dashboard confirms zero open live positions, no margin in use, and compatible live account/server/session state.",
        ],
        "nextOperatorSteps": [
            "Review CONFIG_READY tasks in Governance Advisor before any Strategy Tester launch.",
            "Run with --run-terminal only in the authorized tester window or explicitly authorized session.",
            "Use parsed ParamLab results as evidence only; do not write them into the live preset automatically.",
        ],
    }
    write_json(output_path, status)
    write_json(run_dir / STATUS_NAME, status)
    write_csv(
        run_dir / "QuantGod_ParamLabLedger.csv",
        ledger_rows,
        [
            "RunId",
            "GeneratedAtIso",
            "CandidateId",
            "RouteKey",
            "Symbol",
            "Timeframe",
            "Variant",
            "Status",
            "ClosedTrades",
            "NetProfit",
            "ProfitFactor",
            "WinRate",
            "TerminalTimedOut",
            "ConfigPath",
            "ReportPath",
        ],
    )
    update_plan_with_run(plan, status, plan_path)
    return status


def main() -> int:
    args = parse_args()
    try:
        status = build_runner_status(args)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"Wrote {status['runtimeDir']}\\{STATUS_NAME}")
    print(f"ParamLab {status['mode']}: {status['selectedTaskCount']} task(s), archive {status['archiveDir']}")
    print(
        "Summary: "
        f"configReady={status['summary']['configReadyCount']} "
        f"runAttempted={status['summary']['runAttemptedCount']} "
        f"reportParsed={status['summary']['reportParsedCount']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
