from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


RUN_LATEST_NAME = "QuantGod_DailyAutopilotV2RunLatest.json"
RUN_LEDGER_NAME = "QuantGod_DailyAutopilotV2RunLedger.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_paths(runtime_dir: Path) -> Dict[str, Path]:
    base = Path(runtime_dir) / "agent"
    return {
        "base": base,
        "latest": base / RUN_LATEST_NAME,
        "ledger": base / RUN_LEDGER_NAME,
    }


def run_daily_autopilot_cycle(
    runtime_dir: Path,
    *,
    repo_root: Path,
    write: bool = True,
    bootstrap_samples: bool = False,
) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    repo_root = Path(repo_root)
    started_at = utc_now_iso()
    steps: List[Dict[str, Any]] = []
    for step in _build_steps(
        runtime_dir,
        repo_root,
        bootstrap_samples=bootstrap_samples,
    ):
        steps.append(_run_step(repo_root, step))
    failed = [step for step in steps if step.get("status") != "COMPLETED_BY_AGENT"]
    cycle_started = len(steps) > 0
    cycle_completed = cycle_started and not failed
    payload: Dict[str, Any] = {
        "ok": cycle_completed,
        "schema": "quantgod.daily_autopilot_v2_run.v1",
        "agentVersion": "v2.6",
        "startedAtIso": started_at,
        "completedAtIso": utc_now_iso(),
        "symbol": "USDJPYc",
        "runtimeDir": str(runtime_dir),
        "status": (
            "COMPLETED_BY_AGENT"
            if cycle_completed
            else ("FAILED_RETRYABLE" if cycle_started else "NOT_STARTED")
        ),
        "completedByAgent": cycle_completed,
        "autoAppliedByAgent": cycle_completed,
        "requiresAutonomousGovernance": True,
        "stepCount": len(steps),
        "completedStepCount": len(steps) - len(failed),
        "failedStepCount": len(failed),
        "steps": steps,
        "summaryZh": _summary_zh(steps, failed),
        "safety": {
            "shadowOnly": True,
            "readOnlyMode": True,
            "operatorApprovalRequired": True,
            "unattendedLiveExpansionAllowed": False,
            "liveExpansionAllowed": False,
            "orderSendAllowed": False,
            "closeAllowed": False,
            "cancelAllowed": False,
            "livePresetMutationAllowed": False,
            "externalMarketRealMoneyAllowed": False,
            "telegramCommandExecutionAllowed": False,
        },
    }
    if write:
        _write_run(runtime_dir, payload)
    return payload


def read_latest_run(runtime_dir: Path) -> Dict[str, Any]:
    latest = run_paths(runtime_dir)["latest"]
    try:
        if latest.exists():
            data = json.loads(latest.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _build_steps(
    runtime_dir: Path,
    repo_root: Path,
    *,
    bootstrap_samples: bool,
) -> List[Dict[str, Any]]:
    py = sys.executable
    runtime_arg = ["--runtime-dir", str(runtime_dir)]
    steps: List[Dict[str, Any]] = [
        {
            "id": "automation_chain",
            "lane": "LIVE",
            "action": "RUN_USDJPY_AUTOMATION_CHAIN",
            "summaryZh": "刷新 USDJPY live-loop 真相来源。",
            "command": [py, "tools/run_automation_chain.py", *runtime_arg, "--symbols", "USDJPYc", "once"],
            "timeoutSeconds": 180,
        },
        {
            "id": "strategy_backtest_sync",
            "lane": "MT5_SHADOW",
            "action": "SYNC_USDJPY_KLINES",
            "summaryZh": "同步 USDJPY K 线到 SQLite 回测库。",
            "command": [py, "tools/run_usdjpy_strategy_backtest.py", *runtime_arg, "sync-klines"],
            "timeoutSeconds": 180,
        },
        {
            "id": "strategy_backtest_run",
            "lane": "MT5_SHADOW",
            "action": "RUN_STRATEGY_JSON_BACKTEST",
            "summaryZh": "运行 Strategy JSON USDJPY 回测并写入交易和权益证据。",
            "command": [py, "tools/run_usdjpy_strategy_backtest.py", *runtime_arg, "run", "--write"],
            "timeoutSeconds": 180,
        },
        {
            "id": "strategy_backtest_quality",
            "lane": "MT5_SHADOW",
            "action": "CHECK_STRATEGY_BACKTEST_QUALITY",
            "summaryZh": "检查回测生产化质量：历史深度、动态成本、历史新闻门禁和缓存证据。",
            "command": [py, "tools/run_usdjpy_strategy_backtest.py", *runtime_arg, "quality"],
            "timeoutSeconds": 120,
            "allowWarn": True,
        },
        {
            "id": "bar_replay",
            "lane": "MT5_SHADOW",
            "action": "RUN_CAUSAL_BAR_REPLAY",
            "summaryZh": "运行 USDJPY 因果 bar replay。",
            "command": [py, "tools/run_usdjpy_bar_replay.py", *runtime_arg, "build", "--write"],
            "timeoutSeconds": 180,
        },
        {
            "id": "strategy_parity",
            "lane": "LIVE",
            "action": "RUN_STRATEGY_REPLAY_EA_PARITY",
            "summaryZh": "运行 Strategy JSON / Python Replay / MQL5 EA 一致性校验。",
            "command": [py, "tools/run_strategy_parity.py", *runtime_arg, "build", "--write"],
            "timeoutSeconds": 180,
        },
        {
            "id": "live_execution_feedback",
            "lane": "LIVE",
            "action": "RUN_LIVE_EXECUTION_FEEDBACK_SUMMARY",
            "summaryZh": "汇总 EA shadow/live 执行反馈：滑点、延迟、点差、退出质量和 R 倍数。",
            "command": [py, "tools/run_live_execution_feedback.py", *runtime_arg, "build", "--write"],
            "timeoutSeconds": 180,
        },
        {
            "id": "evidence_os",
            "lane": "LIVE",
            "action": "RUN_PARITY_AND_EXECUTION_FEEDBACK",
            "summaryZh": "运行 parity、执行反馈和 Case Memory 审计；失败证据会阻断晋级。",
            "command": [py, "tools/run_usdjpy_evidence_os.py", *runtime_arg, "once", "--write"],
            "timeoutSeconds": 180,
        },
        {
            "id": "walk_forward",
            "lane": "MT5_SHADOW",
            "action": "RUN_WALK_FORWARD",
            "summaryZh": "运行 walk-forward 参数选择。",
            "command": [py, "tools/run_usdjpy_walk_forward.py", *runtime_arg, "build", "--write"],
            "timeoutSeconds": 180,
        },
        {
            "id": "ga_generation",
            "lane": "MT5_SHADOW",
            "action": "RUN_GA_GENERATION",
            "summaryZh": "运行 Strategy JSON GA generation 并写全过程 trace。",
            "command": [py, "tools/run_strategy_ga.py", *runtime_arg, "run-generation", "--write"],
            "timeoutSeconds": 180,
        },
        {
            "id": "ga_factory",
            "lane": "MT5_SHADOW",
            "action": "BUILD_GA_FACTORY_ARCHIVE",
            "summaryZh": "归档 GA Factory state、lineage 和 graveyard，保持生产证据与最新 generation 对齐。",
            "command": [py, "tools/run_strategy_ga_factory.py", *runtime_arg, "build", "--write"],
            "timeoutSeconds": 120,
        },
        {
            "id": "ga_multi_generation_stability",
            "lane": "MT5_SHADOW",
            "action": "BUILD_GA_MULTI_GENERATION_STABILITY",
            "summaryZh": "刷新 GA 多代稳定性证据，用于 burn-in 和 production evidence。",
            "command": [py, "tools/run_ga_multi_generation_stability.py", *runtime_arg, "build", "--write"],
            "timeoutSeconds": 120,
        },
    ]
    if bootstrap_samples:
        steps.insert(
            0,
            {
                "id": "bootstrap_backtest_sample",
                "lane": "MT5_SHADOW",
                "action": "BOOTSTRAP_TEST_SAMPLE",
                "summaryZh": "测试环境生成 USDJPY 回测样本。",
                "command": [py, "tools/run_usdjpy_strategy_backtest.py", *runtime_arg, "sample", "--overwrite"],
                "timeoutSeconds": 60,
            },
        )
    return steps


def _run_step(repo_root: Path, step: Dict[str, Any]) -> Dict[str, Any]:
    started = utc_now_iso()
    command = [str(item) for item in step["command"]]
    try:
        proc = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=int(step.get("timeoutSeconds") or 180),
        )
        payload = _parse_json(proc.stdout)
        warn_allowed = bool(step.get("allowWarn")) and str(payload.get("status") or "").upper() == "WARN"
        ok = proc.returncode == 0 and (payload.get("ok") is not False or warn_allowed)
        return {
            "id": step["id"],
            "lane": step["lane"],
            "action": step["action"],
            "status": "COMPLETED_BY_AGENT" if ok else "FAILED_RETRYABLE",
            "completedByAgent": ok,
            "autoAppliedByAgent": ok,
            "requiresAutonomousGovernance": True,
            "startedAtIso": started,
            "completedAtIso": utc_now_iso(),
            "exitCode": proc.returncode,
            "summaryZh": step["summaryZh"],
            "resultSchema": payload.get("schema"),
            "resultStatus": payload.get("status"),
            "error": None if ok else _trim(proc.stderr or proc.stdout),
        }
    except subprocess.TimeoutExpired as exc:
        return _failed_step(step, started, f"timeout after {exc.timeout}s")
    except Exception as exc:  # pragma: no cover - defensive for local ops.
        return _failed_step(step, started, str(exc))


def _failed_step(step: Dict[str, Any], started: str, error: str) -> Dict[str, Any]:
    return {
        "id": step["id"],
        "lane": step["lane"],
        "action": step["action"],
        "status": "FAILED_RETRYABLE",
        "completedByAgent": False,
        "autoAppliedByAgent": False,
        "requiresAutonomousGovernance": True,
        "startedAtIso": started,
        "completedAtIso": utc_now_iso(),
        "exitCode": None,
        "summaryZh": step["summaryZh"],
        "error": _trim(error),
    }


def _parse_json(stdout: str) -> Dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"ok": True, "data": data}
    except Exception:
        return {"ok": True, "rawText": _trim(text)}


def _write_run(runtime_dir: Path, payload: Dict[str, Any]) -> None:
    paths = run_paths(runtime_dir)
    paths["base"].mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    paths["latest"].write_text(text, encoding="utf-8")
    with paths["ledger"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _summary_zh(steps: List[Dict[str, Any]], failed: List[Dict[str, Any]]) -> str:
    if not steps:
        return "Agent 调度周期尚未开始；没有步骤证据，不能标记为自动完成。"
    if failed:
        return f"Agent 调度完成 {len(steps) - len(failed)}/{len(steps)} 步；失败步骤会保留为可重试。"
    return (
        f"Agent 已自动完成 {len(steps)} 个调度步骤，并刷新回测、回放、parity、"
        "执行反馈、Case Memory、walk-forward 和 GA 证据。"
    )


def _trim(text: str, limit: int = 900) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[-limit:]
