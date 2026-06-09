from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .forex_live12_rsi_shadow_candidate import build_forex_live12_rsi_shadow_candidate
from .schema import (
    FOREX_LIVE12_RSI_TESTER_REQUEST_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    forex_live12_rsi_tester_request_path,
    utc_now_iso,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _materialization_status(repo_root: Path) -> dict[str, Any]:
    isolated_runtime_dir = repo_root / "runtime" / "HFM_MT5_Tester_Isolated" / "MQL5" / "Files"
    status_path = isolated_runtime_dir / "agent" / "QuantGod_ForexLive12RsiTesterParamLabStatus.json"
    status = _read_json(status_path)
    if not status:
        return {
            "exists": False,
            "statusPath": str(status_path),
            "statusZh": "等待隔离 ParamLab config-only materialize",
            "runTerminal": False,
            "livePresetMutation": False,
            "orderSendAllowed": False,
            "writesMt5OrderRequest": False,
        }
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    tasks = status.get("tasks") if isinstance(status.get("tasks"), list) else []
    first_task = tasks[0] if tasks and isinstance(tasks[0], dict) else {}
    metrics = first_task.get("metrics") if isinstance(first_task.get("metrics"), dict) else {}
    task_status = str(first_task.get("status") or "")
    terminal_process = first_task.get("terminalProcess") if isinstance(first_task.get("terminalProcess"), dict) else {}
    terminal_blockers = first_task.get("terminalBlockers") if isinstance(first_task.get("terminalBlockers"), list) else []
    terminal_blocker_codes = [
        str(item.get("code"))
        for item in terminal_blockers
        if isinstance(item, dict) and item.get("code")
    ]
    if summary.get("htmlReportParsedCount") or metrics.get("htmlReportExists"):
        status_zh = "隔离 ParamLab HTML tester 报告已解析"
    elif "WINE_SERVER_MACH_PORT_UNAVAILABLE" in terminal_blocker_codes:
        status_zh = "隔离 ParamLab terminal 失败：Wine Mach port 不可用，HTML tester 报告缺失"
    elif "WINE_SERVER_BIND_BLOCKED_BY_SANDBOX" in terminal_blocker_codes:
        status_zh = "隔离 ParamLab terminal 失败：Wine bind 被沙盒/权限拦截，HTML tester 报告缺失"
    elif summary.get("runAttemptedCount") and first_task.get("terminalExitCode") not in (None, 0):
        status_zh = "隔离 ParamLab terminal 运行失败，HTML tester 报告缺失"
    elif summary.get("runAttemptedCount"):
        status_zh = "隔离 ParamLab 已运行，等待 HTML tester 报告"
    elif summary.get("configReadyCount"):
        status_zh = "隔离 ParamLab config 已就绪"
    else:
        status_zh = "隔离 ParamLab config 等待生成"
    return {
        "exists": True,
        "statusPath": str(status_path),
        "runId": status.get("runId", ""),
        "mode": status.get("mode", ""),
        "statusZh": status_zh,
        "configReadyCount": summary.get("configReadyCount", 0),
        "runAttemptedCount": summary.get("runAttemptedCount", 0),
        "reportParsedCount": summary.get("reportParsedCount", 0),
        "htmlReportParsedCount": summary.get("htmlReportParsedCount", 0),
        "agentEvidenceParsedCount": summary.get("agentEvidenceParsedCount", 0),
        "terminalNonzeroCount": summary.get("terminalNonzeroCount", 0),
        "terminalBlockerCodes": summary.get("terminalBlockerCodes", terminal_blocker_codes),
        "terminalBlockers": terminal_blockers,
        "selectedTaskCount": status.get("selectedTaskCount", 0),
        "candidateId": first_task.get("candidateId", ""),
        "taskStatus": task_status,
        "terminalExitCode": first_task.get("terminalExitCode"),
        "terminalTimedOut": bool(first_task.get("terminalTimedOut")),
        "terminalStderrTail": terminal_process.get("stderrTail", ""),
        "htmlReportExists": bool(metrics.get("htmlReportExists")),
        "testerEvidenceExists": bool(metrics.get("testerEvidenceExists")),
        "sampleStatus": metrics.get("sampleStatus", ""),
        "configPath": first_task.get("configPath", ""),
        "presetPath": first_task.get("presetPath", ""),
        "hfmPresetPath": first_task.get("hfmPresetPath", ""),
        "reportPath": first_task.get("reportPath", ""),
        "materializedGuardOk": first_task.get("materializedGuard", {}).get("ok") is True,
        "runTerminal": bool(status.get("runTerminal")),
        "livePresetMutation": bool(first_task.get("livePresetMutation")),
        "orderSendAllowed": False,
        "writesMt5OrderRequest": False,
    }


def _task_from_candidate(
    candidate_payload: dict[str, Any],
    repo_root: Path,
    request_path: Path,
    isolated_runtime_dir: Path,
    live_runtime_dir: Path,
) -> dict[str, Any]:
    candidate = candidate_payload.get("candidate") if isinstance(candidate_payload.get("candidate"), dict) else {}
    candidate_id = str(candidate.get("id") or "forex-live12-rsi-loss-cooldown-v1")
    params = candidate.get("parameters") if isinstance(candidate.get("parameters"), dict) else {}
    base_preset = repo_root / "MQL5" / "Presets" / "QuantGod_MT5_HFM_Backtest_USDJPYc.set"
    preset_overrides = {
        "DashboardBuild": "QuantGod-v3.18-rsi-loss-cooldown-tester-request",
        "Watchlist": "USDJPYc",
        "PreferredSymbolSuffix": "AUTO",
        "ShadowMode": "false",
        "ReadOnlyMode": "false",
        "EnablePilotAutoTrading": "true",
        "PilotLotSize": "0.01",
        "PilotMaxTotalPositions": str(candidate.get("stageMaxTotalTrades") or 2),
        "PilotMaxPositionsPerSymbol": "1",
        "PilotBlockManualPerSymbol": "false",
        "EnableManualSafetyGuard": "false",
        "PilotCloseOnKillSwitch": "true",
        "EnablePilotMA": "false",
        "EnablePilotRsiH1Candidate": "true",
        "EnablePilotRsiH1Live": "false",
        "EnablePilotBBH1Candidate": "false",
        "EnablePilotBBH1Live": "false",
        "EnablePilotMacdH1Candidate": "false",
        "EnablePilotMacdH1Live": "false",
        "EnablePilotSRM15Candidate": "false",
        "EnablePilotSRM15Live": "false",
        "PilotRsiLossCooldownAfterLosses": str(params.get("cooldownAfterConsecutiveLosses") or 2),
        "PilotRsiLossCooldownBarsH1": str(params.get("cooldownBarsH1") or 1),
        "PilotRsiRequireSignalScoreAfterCooldown": str(params.get("requireSignalScoreAfterCooldown") or 100),
        "PilotRsiMinProfitFactorForExpansion": str(params.get("minProfitFactorForExpansion") or 1.05),
        "PilotRsiMaxConsecutiveLossesForExpansion": str(params.get("maxConsecutiveLossesForExpansion") or 2),
        "PilotRsiRequireFloatingProfitNonNegative": "true",
        "PilotRsiPenalizeTrendDownBuy": "true",
    }
    config_command = (
        f'python "{repo_root / "tools" / "run_param_lab.py"}" '
        f'--hfm-root "{repo_root / "runtime" / "HFM_MT5_Tester_Isolated"}" '
        f'--runtime-dir "{isolated_runtime_dir}" '
        f'--plan "{request_path}" '
        f'--output "{isolated_runtime_dir / "agent" / "QuantGod_ForexLive12RsiTesterParamLabStatus.json"}" '
        f'--candidate-id "{candidate_id}"'
    )
    guarded_run_command = (
        f'python "{repo_root / "tools" / "run_param_lab.py"}" '
        f'--hfm-root "{repo_root / "runtime" / "HFM_MT5_Tester_Isolated"}" '
        f'--runtime-dir "{live_runtime_dir}" '
        f'--plan "{request_path}" '
        f'--output "{isolated_runtime_dir / "agent" / "QuantGod_ForexLive12RsiTesterParamLabStatus.json"}" '
        f'--candidate-id "{candidate_id}" '
        f'--max-tasks 1 '
        f'--run-terminal '
        f'--authorized-strategy-tester '
        f'--terminal-timeout-seconds 420 '
        f'--auto-tester-lock "{isolated_runtime_dir / "QuantGod_AutoTesterWindow.lock.json"}" '
        f'--wineprefix "{repo_root / "runtime" / "HFM_MT5_Tester_Isolated" / "WinePrefix"}"'
    )
    return {
        "rank": 1,
        "candidateId": candidate_id,
        "routeKey": "RSI_Reversal",
        "strategy": "RSI_Reversal",
        "label": "USDJPY RSI_Reversal H1 loss-cooldown candidate",
        "symbol": "USDJPYc",
        "timeframe": "H1",
        "candidateRoute": "RSI_LOSS_COOLDOWN",
        "variant": "loss_cooldown_trend_down_filter_v1",
        "intent": "Materialize tester-only config for isolated Strategy Tester validation; do not run terminal here.",
        "score": candidate_payload.get("proxyReplay", {}).get("afterMetrics", {}).get("profitFactor"),
        "basePreset": str(base_preset),
        "basePresetFound": base_preset.exists(),
        "presetName": f"QuantGod_MT5_ParamLab_{candidate_id}.set",
        "presetOverrides": preset_overrides,
        "parameterSummary": (
            "2-loss H1 cooldown, require score 100 after cooldown, trend-down BUY penalty, "
            "PF>=1.05 and max consecutive losses<=2 before expansion"
        ),
        "testerOnly": True,
        "livePresetMutation": False,
        "testerOnlyCommand": config_command,
        "configOnlyCommand": config_command,
        "guardedRunTerminalCommand": guarded_run_command,
        "runTerminalDefault": False,
    }


def build_forex_live12_rsi_tester_request(
    runtime_dir: Path,
    *,
    requested_max_total_trades: int = 10,
    primary_dashboard_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    repo_root = _repo_root()
    isolated_tester_root = repo_root / "runtime" / "HFM_MT5_Tester_Isolated"
    isolated_runtime_dir = isolated_tester_root / "MQL5" / "Files"
    isolated_wineprefix = isolated_tester_root / "WinePrefix"
    request_path = isolated_runtime_dir / "agent" / "QuantGod_ForexLive12RsiTesterRequest.json"
    live_runtime_request_path = forex_live12_rsi_tester_request_path(runtime)
    live_runtime_dir = Path(primary_dashboard_json).parent if primary_dashboard_json else runtime
    shadow_candidate = build_forex_live12_rsi_shadow_candidate(
        runtime,
        requested_max_total_trades=requested_max_total_trades,
        primary_dashboard_json=primary_dashboard_json,
        write=False,
    )
    task = _task_from_candidate(shadow_candidate, repo_root, request_path, isolated_runtime_dir, live_runtime_dir)
    payload = {
        "ok": True,
        "schema": FOREX_LIVE12_RSI_TESTER_REQUEST_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "repoRoot": str(repo_root),
        "liveRuntimeRequestPath": str(live_runtime_request_path),
        "isolatedPlanPath": str(request_path),
        "status": "RSI_TESTER_REQUEST_READY",
        "statusZh": "RSI 修复候选已进入 Tester-only 请求包",
        "mode": "PARAM_LAB_COMPATIBLE_CONFIG_ONLY_REQUEST",
        "summary": {
            "queueCount": 1,
            "configOnly": True,
            "runTerminal": False,
            "testerOnly": True,
            "livePresetMutation": False,
            "topCandidateId": task["candidateId"],
            "proxyAfterProfitFactor": shadow_candidate.get("proxyReplay", {}).get("afterMetrics", {}).get("profitFactor"),
            "proxyAfterMaxConsecutiveLosses": shadow_candidate.get("proxyReplay", {}).get("afterMetrics", {}).get("maxConsecutiveLosses"),
        },
        "sourceShadowCandidate": {
            "status": shadow_candidate.get("status"),
            "statusZh": shadow_candidate.get("statusZh"),
            "candidate": shadow_candidate.get("candidate", {}),
            "proxyReplaySummary": {
                "beforeMetrics": shadow_candidate.get("proxyReplay", {}).get("beforeMetrics", {}),
                "afterMetrics": shadow_candidate.get("proxyReplay", {}).get("afterMetrics", {}),
                "blockedTradeCount": shadow_candidate.get("proxyReplay", {}).get("blockedTradeCount"),
            },
        },
        "materializationStatus": _materialization_status(repo_root),
        "routePlans": [
            {
                "routeKey": "RSI_Reversal",
                "label": "USDJPY RSI_Reversal H1",
                "currentDecision": "TESTER_ONLY_REQUESTED",
                "queueMode": "CONFIG_ONLY_QUEUE",
                "scheduledTaskCount": 1,
                "candidates": [task],
            }
        ],
        "selectedTasks": [task],
        "backtestTasks": [task],
        "batchCommand": task["configOnlyCommand"],
        "testerIsolation": {
            "requireIsolatedTester": True,
            "isolatedTesterRoot": str(isolated_tester_root),
            "isolatedRuntimeDir": str(isolated_runtime_dir),
            "liveRuntimeDir": str(live_runtime_dir),
            "isolatedWinePrefix": str(isolated_wineprefix),
            "isolatedPlanPath": str(request_path),
            "sharedLiveRootAllowed": False,
            "runTerminalRequiresSeparateAuthorization": True,
        },
        "decision": {
            "canApplyHere": False,
            "canWritePresetHere": False,
            "canRunTerminalHere": False,
            "canPromoteToLiveHere": False,
            "paramLabCompatible": True,
            "nextRequiredActionZh": "下一步只允许在隔离 Tester root 中 materialize config；Strategy Tester 启动仍需单独受控窗口。",
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5Preset": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerCallsMade": False,
        },
        "hardGuards": [
            "This request is config-only and never adds --run-terminal.",
            "No HFM live preset is mutated.",
            "No MT5 order request or receipt is written.",
            "Use only an isolated tester root when materializing configs.",
            "Strategy Tester launch requires a separate authorized tester window and a live dashboard runtime for guards.",
        ],
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        live_runtime_request_path.parent.mkdir(parents=True, exist_ok=True)
        live_runtime_request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_forex_live12_rsi_tester_request(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = forex_live12_rsi_tester_request_path(runtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return build_forex_live12_rsi_tester_request(runtime, write=False)
    except Exception as exc:
        return {
            "ok": False,
            "schema": FOREX_LIVE12_RSI_TESTER_REQUEST_SCHEMA_VERSION,
            "status": "INVALID",
            "statusZh": "forex Live12 RSI tester request artifact 无法读取",
            "readError": str(exc),
            "path": str(path),
            "safety": dict(SAFETY),
        }
    if isinstance(payload, dict):
        payload["materializationStatus"] = _materialization_status(_repo_root())
        assert_no_execution_flags(payload)
        return payload
    return build_forex_live12_rsi_tester_request(runtime, write=False)
