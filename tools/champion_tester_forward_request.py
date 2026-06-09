"""Tester-only request for the current QuantGod ace champion.

This request materializes the selected GA champion as a ParamLab-compatible
config-only queue item. It does not launch MT5, mutate live presets, or write
order request/receipt files.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "quantgod.champion_tester_forward_request.v1"
REPORT_PATH = Path("agent") / "QuantGod_ChampionTesterForwardRequest.json"
TPSL_REPORT_PATH = Path("agent") / "QuantGod_TpSlOptimizerReport.json"
STATUS_FILE = "QuantGod_ChampionTesterForwardParamLabStatus.json"
DEFAULT_CHAMPION_SEED_ID = "GA-USDJPY-G0077-C0002"


SAFETY = {
    "readOnly": True,
    "testerOnly": True,
    "configOnly": True,
    "runTerminal": False,
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


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").replace(",", "").strip())
        except ValueError:
            return default
    return default


def _selected_champion_seed_id(runtime_dir: Path) -> str:
    retest = _read_json(runtime_dir / "agent" / "QuantGod_ChampionRetestReport.json")
    forex = retest.get("forexChampion") if isinstance(retest.get("forexChampion"), dict) else {}
    seed_id = str(forex.get("seedId") or "").strip()
    if seed_id:
        return seed_id
    scout = _read_json(runtime_dir / "agent" / "QuantGod_AceStrategyScout.json")
    top_forex = scout.get("topQualifiedForex") if isinstance(scout.get("topQualifiedForex"), dict) else {}
    seed_id = str(top_forex.get("seedId") or "").strip()
    return seed_id or DEFAULT_CHAMPION_SEED_ID


def _selected_forex_seed_ids(runtime_dir: Path) -> list[str]:
    retest = _read_json(runtime_dir / "agent" / "QuantGod_ChampionRetestReport.json")
    review = retest.get("forexContenderReview") if isinstance(retest.get("forexContenderReview"), dict) else {}
    seeds = [
        str(row.get("seedId")).strip()
        for row in review.get("contenders", [])
        if isinstance(row, dict) and row.get("seedId")
    ]
    if review.get("requiresParallelTesterForward") and seeds:
        return list(dict.fromkeys(seeds))
    return [_selected_champion_seed_id(runtime_dir)]


def _champion_rows(runtime_dir: Path) -> list[dict[str, Any]]:
    payload = _read_json(runtime_dir / "ga" / "QuantGod_GAEliteStrategies.json")
    rows = payload.get("elites") if isinstance(payload.get("elites"), list) else []
    selected_seed_ids = _selected_forex_seed_ids(runtime_dir)
    by_seed = {str(row.get("seedId")): row for row in rows if isinstance(row, dict) and row.get("seedId")}
    return [by_seed[seed_id] for seed_id in selected_seed_ids if seed_id in by_seed]


def _champion_row(runtime_dir: Path) -> dict[str, Any]:
    rows = _champion_rows(runtime_dir)
    return rows[0] if rows else {}


def _promotion_gate(runtime_dir: Path) -> dict[str, Any]:
    return _read_json(runtime_dir / "agent" / "QuantGod_ChampionPromotionGate.json")


def _task_paths(repo_root: Path) -> dict[str, Path]:
    tester_root = repo_root / "runtime" / "HFM_MT5_Tester_Isolated"
    isolated_runtime_dir = tester_root / "MQL5" / "Files"
    request_path = isolated_runtime_dir / "agent" / "QuantGod_ChampionTesterForwardRequest.json"
    status_path = isolated_runtime_dir / "agent" / STATUS_FILE
    return {
        "testerRoot": tester_root,
        "isolatedRuntimeDir": isolated_runtime_dir,
        "requestPath": request_path,
        "statusPath": status_path,
        "lockPath": isolated_runtime_dir / "QuantGod_AutoTesterWindow.lock.json",
        "winePrefix": tester_root / "WinePrefix",
        "basePreset": repo_root / "MQL5" / "Presets" / "QuantGod_MT5_HFM_Backtest_USDJPYc.set",
    }


def _strategy_metrics(champion: dict[str, Any]) -> dict[str, Any]:
    breakdown = champion.get("fitnessBreakdown") if isinstance(champion.get("fitnessBreakdown"), dict) else {}
    backtest = breakdown.get("strategyBacktest") if isinstance(breakdown.get("strategyBacktest"), dict) else {}
    walk_forward = breakdown.get("walkForward") if isinstance(breakdown.get("walkForward"), dict) else {}
    summary = walk_forward.get("summary") if isinstance(walk_forward.get("summary"), dict) else {}
    return {
        "fitness": round(_num(champion.get("fitness")), 4),
        "netR": round(_num(backtest.get("netR", breakdown.get("netR"))), 4),
        "profitFactor": round(_num(backtest.get("profitFactor")), 4),
        "sharpe": round(_num(backtest.get("sharpe")), 4),
        "maxDrawdownR": round(_num(backtest.get("maxDrawdownR")), 4),
        "tradeCount": int(_num(backtest.get("tradeCount", breakdown.get("sampleCount")))),
        "walkForward": {
            "sampleCount": int(_num(summary.get("sampleCount"))),
            "trainNetR": round(_num(summary.get("trainNetR")), 4),
            "validationNetR": round(_num(summary.get("validationNetR")), 4),
            "forwardNetR": round(_num(summary.get("forwardNetR")), 4),
            "stabilityScore": round(_num(summary.get("stabilityScore")), 4),
            "promotionAllowed": bool(summary.get("promotionAllowed")),
            "evidenceQuality": summary.get("evidenceQuality"),
        },
    }


def _preset_overrides(strategy_json: dict[str, Any]) -> dict[str, str]:
    indicators = strategy_json.get("indicators") if isinstance(strategy_json.get("indicators"), dict) else {}
    rsi = indicators.get("rsi") if isinstance(indicators.get("rsi"), dict) else {}
    exit_cfg = strategy_json.get("exit") if isinstance(strategy_json.get("exit"), dict) else {}
    time_stop_bars = exit_cfg.get("timeStopBars") if isinstance(exit_cfg.get("timeStopBars"), dict) else {}
    risk = strategy_json.get("risk") if isinstance(strategy_json.get("risk"), dict) else {}
    return {
        "DashboardBuild": f"QuantGod-v3.19-{str(strategy_json.get('seedId') or DEFAULT_CHAMPION_SEED_ID).lower()}-champion-tester-forward",
        "Watchlist": "USDJPYc",
        "PreferredSymbolSuffix": "AUTO",
        "ShadowMode": "false",
        "ReadOnlyMode": "false",
        "EnablePilotAutoTrading": "true",
        "EnablePilotStartupEntryGuard": "false",
        "PilotStartupEntryGuardMode": "BACKTEST_OFF",
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
        "PilotRsiTimeframe": "16385",
        "PilotRsiPeriod": str(int(_num(rsi.get("period"), 19))),
        "PilotRsiOversold": str(int(_num(rsi.get("buyBand"), 29))),
        "PilotRsiOverbought": "85",
        "PilotRsiCrossbackThreshold": str(_num(rsi.get("crossbackThreshold"), 0.4)),
        "PilotRsiMaxHoldMinutes": str(int(_num(time_stop_bars.get("H1"), 5)) * 60),
        "PilotRsiATRMultiplierSL": "1.5",
        "PilotLotSize": "0.01",
        "PilotMaxTotalPositions": "1",
        "PilotMaxPositionsPerSymbol": "1",
        "PilotMaxConsecutiveLosses": "2",
        "PilotMaxSpreadPips": "2.0",
        "PilotSoftMaxSpreadPips": "2.7",
        "PilotHardMaxSpreadPips": "3.0",
        "PilotRewardRatio": "1.5",
        "PilotRsiRequireFloatingProfitNonNegative": "true",
        "PilotRsiPenalizeTrendDownBuy": "true",
        "ChampionSeedId": str(strategy_json.get("seedId") or DEFAULT_CHAMPION_SEED_ID),
        "ChampionStrategyId": str(strategy_json.get("strategyId") or ""),
        "ChampionRiskPips": str(int(_num(risk.get("riskPips"), 21))),
        "ChampionOpportunityLotMultiplier": str(_num(risk.get("opportunityLotMultiplier"), 0.22)),
    }


def _config_only_command(repo_root: Path, paths: dict[str, Path], *, candidate_id: str = "", max_tasks: int = 1) -> str:
    command = (
        f'python "{repo_root / "tools" / "run_param_lab.py"}" '
        f'--hfm-root "{paths["testerRoot"]}" '
        f'--runtime-dir "{paths["isolatedRuntimeDir"]}" '
        f'--plan "{paths["requestPath"]}" '
        f'--output "{paths["statusPath"]}" '
        f'--max-tasks {max(1, int(max_tasks))}'
    )
    if candidate_id:
        command += f' --candidate-id "{candidate_id}"'
    return command


def _guarded_run_terminal_command(repo_root: Path, paths: dict[str, Path], runtime_dir: Path, candidate_id: str) -> str:
    return (
        f'python "{repo_root / "tools" / "run_param_lab.py"}" '
        f'--hfm-root "{paths["testerRoot"]}" '
        f'--runtime-dir "{runtime_dir}" '
        f'--plan "{paths["requestPath"]}" '
        f'--output "{paths["statusPath"]}" '
        f'--candidate-id "{candidate_id}" '
        f'--max-tasks 1 --run-terminal --authorized-strategy-tester '
        f'--terminal-timeout-seconds 420 '
        f'--auto-tester-lock "{paths["lockPath"]}" '
        f'--wineprefix "{paths["winePrefix"]}"'
    )


def _task(champion: dict[str, Any], repo_root: Path, paths: dict[str, Path], runtime_dir: Path, *, rank: int = 1) -> dict[str, Any]:
    strategy_json = champion.get("strategyJson") if isinstance(champion.get("strategyJson"), dict) else {}
    seed_id = str(champion.get("seedId") or DEFAULT_CHAMPION_SEED_ID)
    match = re.search(r"(G\d{4})", seed_id, re.IGNORECASE)
    seed_slug = match.group(1).lower() if match else seed_id.lower().replace("ga-usdjpy-", "").replace("_", "-")
    candidate_id = f"{seed_slug}-usdjpy-rsi-champion-tester-forward-v1"
    config_command = _config_only_command(repo_root, paths, candidate_id=candidate_id)
    guarded_run_command = _guarded_run_terminal_command(repo_root, paths, runtime_dir, candidate_id)
    return {
        "rank": rank,
        "candidateId": candidate_id,
        "routeKey": "RSI_Reversal",
        "strategy": "RSI_Reversal",
        "label": f"USDJPY {seed_slug.upper()} RSI_Reversal champion tester/forward",
        "symbol": "USDJPYc",
        "timeframe": "H1",
        "candidateRoute": f"{seed_slug.upper()}_CHAMPION_STRATEGY_JSON_LOCK",
        "variant": f"{seed_slug}_strategy_json_locked_v1",
        "intent": "Materialize the current ace champion for isolated tester/forward validation; do not run terminal here.",
        "score": _num(champion.get("fitness")),
        "seedId": champion.get("seedId"),
        "strategyId": champion.get("strategyId"),
        "fingerprint": champion.get("fingerprint"),
        "basePreset": str(paths["basePreset"]),
        "basePresetFound": paths["basePreset"].exists(),
        "presetName": f"QuantGod_MT5_ParamLab_{candidate_id}.set",
        "presetOverrides": _preset_overrides(strategy_json),
        "parameterSummary": f"{seed_id} locked RSI_Reversal LONG, H1 bearish-stretch regime, guarded adverse-excursion filter.",
        "testerOnly": True,
        "livePresetMutation": False,
        "runTerminalDefault": False,
        "testerOnlyCommand": config_command,
        "configOnlyCommand": config_command,
        "guardedRunTerminalCommand": guarded_run_command,
        "strategyJsonSnapshot": strategy_json,
    }


def _tp_sl_optimizer_report(runtime_dir: Path) -> dict[str, Any]:
    payload = _read_json(runtime_dir / TPSL_REPORT_PATH)
    if payload.get("schema") != "quantgod.tp_sl_optimizer.report.v1":
        return {}
    return payload


def _tp_sl_variant_tasks(
    runtime_dir: Path,
    repo_root: Path,
    paths: dict[str, Path],
    base_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach advisory TP/SL variants to the top champion for isolated tester only."""

    if not base_tasks:
        return []
    report = _tp_sl_optimizer_report(runtime_dir)
    forex = report.get("forexMt5") if isinstance(report.get("forexMt5"), dict) else {}
    if not forex:
        forex = report.get("forex") if isinstance(report.get("forex"), dict) else {}
    variants = forex.get("testerVariantQueue") if isinstance(forex.get("testerVariantQueue"), list) else []
    base = base_tasks[0]
    seed_id = str(base.get("seedId") or "")
    tasks: list[dict[str, Any]] = []
    next_rank = len(base_tasks) + 1
    for index, variant in enumerate(variants, start=1):
        if not isinstance(variant, dict):
            continue
        if not variant.get("testerOnly") or variant.get("livePresetMutation"):
            continue
        variant_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(variant.get("variantId") or f"tpsl_{index}")).strip("_")
        if not variant_id:
            continue
        overrides = variant.get("testerOverrides") if isinstance(variant.get("testerOverrides"), dict) else {}
        merged_overrides = dict(base.get("presetOverrides") if isinstance(base.get("presetOverrides"), dict) else {})
        merged_overrides.update({str(key): str(value) for key, value in overrides.items()})
        merged_overrides["DashboardBuild"] = (
            f"{merged_overrides.get('DashboardBuild', 'QuantGod-champion-tester')}-{variant_id}"
        )
        candidate_id = f"{base.get('candidateId')}-{variant_id}"
        config_command = _config_only_command(repo_root, paths, candidate_id=candidate_id)
        task = dict(base)
        task.update(
            {
                "rank": next_rank,
                "candidateId": candidate_id,
                "routeKey": "RSI_Reversal_TPSL",
                "label": f"{base.get('label', 'USDJPY champion')} TP/SL {variant_id}",
                "candidateRoute": f"{base.get('candidateRoute', 'CHAMPION')}_TPSL",
                "variant": variant_id,
                "intent": "Validate TP/SL candidate in isolated Strategy Tester config only; do not run terminal here.",
                "presetName": f"QuantGod_MT5_ParamLab_{candidate_id}.set",
                "presetOverrides": merged_overrides,
                "parameterSummary": (
                    f"{seed_id} TP/SL tester-only variant: riskPips={variant.get('riskPips')}, "
                    f"rewardRatio={variant.get('rewardRatio')}, tpPips={variant.get('tpPips')}"
                ),
                "testerOnly": True,
                "livePresetMutation": False,
                "runTerminalDefault": False,
                "testerOnlyCommand": config_command,
                "configOnlyCommand": config_command,
                "guardedRunTerminalCommand": _guarded_run_terminal_command(repo_root, paths, runtime_dir, candidate_id),
                "tpSlVariant": {
                    "source": "QuantGod_TpSlOptimizerReport",
                    "variantId": variant_id,
                    "riskPips": variant.get("riskPips"),
                    "rewardRatio": variant.get("rewardRatio"),
                    "tpPips": variant.get("tpPips"),
                    "testerOnly": True,
                    "livePresetMutation": False,
                },
            }
        )
        tasks.append(task)
        next_rank += 1
    return tasks


def _materialization_status(paths: dict[str, Path], expected_candidate_ids: str | list[str] = "") -> dict[str, Any]:
    status = _read_json(paths["statusPath"])
    expected_ids = [expected_candidate_ids] if isinstance(expected_candidate_ids, str) else list(expected_candidate_ids)
    expected_ids = [str(item) for item in expected_ids if str(item)]
    if not status:
        label = " / ".join(expected_ids) if expected_ids else "current champion"
        return {
            "exists": False,
            "statusPath": str(paths["statusPath"]),
            "status": "WAITING_CONFIG_MATERIALIZATION",
            "statusZh": f"等待生成 {label} 隔离 tester config",
            "runTerminal": False,
            "orderSendAllowed": False,
            "writesMt5OrderRequest": False,
        }
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    top_by_route = status.get("topByRoute") if isinstance(status.get("topByRoute"), dict) else {}
    materialized_ids = [
        str(item.get("candidateId"))
        for item in top_by_route.values()
        if isinstance(item, dict) and item.get("candidateId")
    ]
    for item in status.get("tasks", []) if isinstance(status.get("tasks"), list) else []:
        if isinstance(item, dict) and item.get("candidateId"):
            materialized_ids.append(str(item.get("candidateId")))
    materialized_ids = sorted(set(materialized_ids))
    missing_ids = sorted(set(expected_ids) - set(materialized_ids))
    if missing_ids:
        return {
            "exists": True,
            "statusPath": str(paths["statusPath"]),
            "status": "CANDIDATE_MISMATCH_NEEDS_CONFIG_REBUILD",
            "expectedCandidateIds": expected_ids,
            "missingCandidateIds": missing_ids,
            "materializedCandidateIds": materialized_ids,
            "configReadyCount": 0,
            "runAttemptedCount": summary.get("runAttemptedCount", 0),
            "htmlReportParsedCount": summary.get("htmlReportParsedCount", 0),
            "terminalNonzeroCount": summary.get("terminalNonzeroCount", 0),
            "terminalBlockerCodes": summary.get("terminalBlockerCodes", []),
            "runTerminal": bool(status.get("runTerminal")),
            "orderSendAllowed": False,
            "writesMt5OrderRequest": False,
        }
    return {
        "exists": True,
        "statusPath": str(paths["statusPath"]),
        "status": status.get("status") or status.get("mode") or "STATUS_PRESENT",
        "configReadyCount": summary.get("configReadyCount", 0),
        "runAttemptedCount": summary.get("runAttemptedCount", 0),
        "htmlReportParsedCount": summary.get("htmlReportParsedCount", 0),
        "terminalNonzeroCount": summary.get("terminalNonzeroCount", 0),
        "terminalBlockerCodes": summary.get("terminalBlockerCodes", []),
        "runTerminal": bool(status.get("runTerminal")),
        "orderSendAllowed": False,
        "writesMt5OrderRequest": False,
    }


def build_champion_tester_forward_request(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    repo_root = _repo_root()
    paths = _task_paths(repo_root)
    champions = _champion_rows(runtime)
    champion = champions[0] if champions else {}
    gate = _promotion_gate(runtime)
    tasks = [
        _task(row, repo_root, paths, runtime, rank=index)
        for index, row in enumerate(champions, start=1)
    ]
    tp_sl_tasks = _tp_sl_variant_tasks(runtime, repo_root, paths, tasks)
    all_tasks = tasks + tp_sl_tasks
    task = all_tasks[0] if all_tasks else {}
    queue_label = " / ".join(str(row.get("seedId")) for row in champions if row.get("seedId"))
    status = "CHAMPION_TESTER_FORWARD_REQUEST_READY" if all_tasks else "CHAMPION_ROW_MISSING"
    status_zh = f"{queue_label} 冠军 tester/forward 请求已生成" if all_tasks else "找不到当前 GA elite 证据"
    batch_command = _config_only_command(repo_root, paths, max_tasks=len(all_tasks)) if all_tasks else ""
    candidate_ids = [str(item.get("candidateId")) for item in all_tasks if item.get("candidateId")]
    payload = {
        "ok": bool(tasks),
        "schema": REPORT_SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "repoRoot": str(repo_root),
        "status": status,
        "statusZh": status_zh,
        "mode": "PARAM_LAB_COMPATIBLE_CONFIG_ONLY_REQUEST",
        "selectedChampion": {
            "seedId": champion.get("seedId"),
            "strategyId": champion.get("strategyId"),
            "strategyFamily": champion.get("strategyFamily"),
            "direction": champion.get("direction"),
            "fingerprint": champion.get("fingerprint"),
        } if champion else {},
        "selectedContenders": [
            {
                "seedId": row.get("seedId"),
                "strategyId": row.get("strategyId"),
                "strategyFamily": row.get("strategyFamily"),
                "direction": row.get("direction"),
                "fingerprint": row.get("fingerprint"),
            }
            for row in champions
        ],
        "championMetrics": _strategy_metrics(champion) if champion else {},
        "promotionGateSnapshot": {
            "status": gate.get("status"),
            "canRunIsolatedTesterForwardNext": gate.get("promotionDecision", {}).get("canRunIsolatedTesterForwardNext"),
            "canPromoteToLiveNow": False,
            "blockers": gate.get("blockers", []),
        },
        "summary": {
            "queueCount": len(all_tasks),
            "championQueueCount": len(tasks),
            "tpSlVariantQueueCount": len(tp_sl_tasks),
            "configOnly": True,
            "runTerminal": False,
            "testerOnly": True,
            "livePresetMutation": False,
            "topCandidateId": task.get("candidateId", ""),
            "candidateIds": candidate_ids,
        },
        "routePlans": [
            {
                "routeKey": "RSI_Reversal",
                "label": f"USDJPY {queue_label or 'current'} RSI_Reversal champion A/B",
                "currentDecision": "TESTER_ONLY_REQUESTED",
                "queueMode": "CONFIG_ONLY_QUEUE",
                "scheduledTaskCount": len(tasks),
                "candidates": tasks,
            }
        ] + ([
            {
                "routeKey": "RSI_Reversal_TPSL",
                "label": "USDJPY top champion TP/SL tester-only variants",
                "currentDecision": "TESTER_ONLY_REQUESTED",
                "queueMode": "CONFIG_ONLY_QUEUE",
                "scheduledTaskCount": len(tp_sl_tasks),
                "candidates": tp_sl_tasks,
            }
        ] if tp_sl_tasks else []),
        "selectedTasks": all_tasks,
        "backtestTasks": all_tasks,
        "tpSlOptimization": {
            "sourcePath": str(runtime / TPSL_REPORT_PATH),
            "sourcePresent": bool(_tp_sl_optimizer_report(runtime)),
            "variantQueueCount": len(tp_sl_tasks),
            "appliedToSeedId": tasks[0].get("seedId") if tasks else "",
            "scope": "top_champion_only",
            "testerOnly": True,
            "livePresetMutation": False,
            "reasonZh": "外汇粗筛没有可直接晋级的 TP/SL 组合；这些候选只进入隔离 Strategy Tester 前向复验。",
        },
        "batchCommand": batch_command,
        "testerIsolation": {
            "requireIsolatedTester": True,
            "isolatedTesterRoot": str(paths["testerRoot"]),
            "isolatedRuntimeDir": str(paths["isolatedRuntimeDir"]),
            "isolatedPlanPath": str(paths["requestPath"]),
            "isolatedWinePrefix": str(paths["winePrefix"]),
            "statusPath": str(paths["statusPath"]),
            "runTerminalRequiresSeparateAuthorization": True,
            "sharedLiveRootAllowed": False,
        },
        "materializationStatus": _materialization_status(paths, candidate_ids),
        "decision": {
            "canMaterializeConfigHere": bool(tasks),
            "canRunTerminalHere": False,
            "canPromoteToLiveHere": False,
            "nextRequiredActionZh": "只允许先生成隔离 tester config；Strategy Tester 启动需要单独 lock/window，实盘仍关闭。",
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
            "Only isolated tester root may materialize the ParamLab config.",
            "Live promotion remains blocked until tester/forward evidence exists.",
        ],
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
        "isolatedPlanPath": str(paths["requestPath"]),
    }
    if write:
        _write_json(runtime / REPORT_PATH, payload)
        _write_json(paths["requestPath"], payload)
    return payload


def read_champion_tester_forward_request(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    payload = _read_json(runtime / REPORT_PATH)
    if payload:
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        expected = summary.get("candidateIds") or summary.get("topCandidateId", "")
        payload["materializationStatus"] = _materialization_status(_task_paths(_repo_root()), expected)
        return payload
    return build_champion_tester_forward_request(runtime, write=False)
