from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    from daily_autopilot_v2.orchestrator import read_latest_run
    from daily_autopilot_v2.report import build_daily_autopilot_v2
    from autonomous_lifecycle.hfm_crypto_shadow_lane import build_hfm_crypto_shadow_lane
    from usdjpy_evidence_os.io_utils import load_json, read_jsonl_tail, utc_now_iso, write_json
    from usdjpy_evidence_os.schema import SAFETY_BOUNDARY, gateway_ledger_path, gateway_queue_path
    from usdjpy_evidence_os.telegram_gateway import gateway_status
except ModuleNotFoundError:  # pragma: no cover - package import path when run from tests
    from tools.daily_autopilot_v2.orchestrator import read_latest_run
    from tools.daily_autopilot_v2.report import build_daily_autopilot_v2
    from tools.autonomous_lifecycle.hfm_crypto_shadow_lane import build_hfm_crypto_shadow_lane
    from tools.usdjpy_evidence_os.io_utils import load_json, read_jsonl_tail, utc_now_iso, write_json
    from tools.usdjpy_evidence_os.schema import SAFETY_BOUNDARY, gateway_ledger_path, gateway_queue_path
    from tools.usdjpy_evidence_os.telegram_gateway import gateway_status


SCHEMA = "quantgod.agent_ops_health.v1"
AGENT_VERSION = "v2.6-agent-ops-health"
OUTPUT_FILE = Path("agent") / "QuantGod_AgentOpsHealth.json"
AGENT_LOOP_STATUS_FILE = Path("agent") / "QuantGod_AgentV25LoopStatus.json"
AGENT_LOOP_SUPERVISOR_FILE = Path("agent") / "QuantGod_AgentV25SupervisorStatus.json"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _age_seconds(value: Any) -> float | None:
    parsed = _parse_time(value)
    if not parsed:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _status_rank(status: str) -> int:
    return {"PASS": 0, "WARN": 1, "BLOCKED": 2}.get(str(status).upper(), 1)


def _overall_status(checks: List[Dict[str, Any]]) -> str:
    if any(_status_rank(check.get("status", "WARN")) >= 2 for check in checks):
        return "BLOCKED"
    if any(_status_rank(check.get("status", "WARN")) >= 1 for check in checks):
        return "WARN"
    return "PASS"


def _status_zh(status: str) -> str:
    mapping = {
        "PASS": "自动化健康",
        "WARN": "需要观察",
        "BLOCKED": "自动化阻断",
    }
    return mapping.get(str(status).upper(), "需要观察")


def _check(key: str, label: str, status: str, detail: str, metric: Any = None, category: str = "system") -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "key": key,
        "label": label,
        "category": category,
        "status": status,
        "statusZh": _status_zh(status),
        "detailZh": detail,
    }
    if metric is not None:
        payload["metric"] = metric
    return payload


def _latest_delivery(runtime_dir: Path) -> Dict[str, Any]:
    rows = read_jsonl_tail(gateway_ledger_path(runtime_dir), limit=50)
    if not rows:
        return {}
    row = rows[-1]
    delivery = row.get("delivery") if isinstance(row.get("delivery"), dict) else {}
    return {
        "eventId": row.get("eventId"),
        "topic": row.get("topic"),
        "source": row.get("source"),
        "createdAtIso": row.get("createdAtIso"),
        "deliveryOk": bool(delivery.get("ok")),
        "deliveryReason": delivery.get("reason") or delivery.get("error") or "",
        "sentAtIso": delivery.get("sentAtIso") or delivery.get("queuedAtIso") or row.get("createdAtIso"),
    }


def _daily_autopilot_health(runtime_dir: Path, repo_root: Path, hfm_crypto_runtime_dir: Path | None = None) -> Dict[str, Any]:
    report = build_daily_autopilot_v2(
        runtime_dir,
        repo_root=repo_root,
        write=False,
        hfm_crypto_runtime_dir=hfm_crypto_runtime_dir,
    )
    latest_run = read_latest_run(runtime_dir)
    steps = latest_run.get("steps") if isinstance(latest_run.get("steps"), list) else []
    failed_steps = [
        str(step.get("name") or step.get("action") or step.get("step") or "unknown")
        for step in steps
        if str(step.get("status") or "").upper() not in {"OK", "PASS", "COMPLETED", "COMPLETED_BY_AGENT", "SKIPPED"}
    ]
    completed_steps = len(steps) - len(failed_steps)
    last_run_at = (
        latest_run.get("completedAtIso")
        or latest_run.get("generatedAtIso")
        or latest_run.get("startedAtIso")
        or report.get("generatedAtIso")
    )
    age_seconds = _age_seconds(last_run_at)
    interval = _as_int(os.environ.get("QG_AGENT_V25_INTERVAL_SECONDS"), 300)
    stale_after = max(1800, interval * 3)
    completed_by_agent = bool(report.get("completedByAgent", True))
    status = "PASS"
    detail = "Daily Autopilot 已由 Agent 生成今日待办和每日复盘。"
    if failed_steps:
        status = "BLOCKED"
        detail = f"Daily Autopilot 有失败步骤：{', '.join(failed_steps[:4])}"
    elif age_seconds is not None and age_seconds > stale_after:
        status = "WARN"
        detail = f"Daily Autopilot 最近一次运行已超过 {int(age_seconds)} 秒。"
    elif not completed_by_agent:
        status = "WARN"
        detail = "日报仍未标记为 Agent 自动完成。"
    return {
        "status": status,
        "statusZh": _status_zh(status),
        "completedByAgent": completed_by_agent,
        "autoAppliedByAgent": bool(report.get("autoAppliedByAgent", True)),
        "lastRunAtIso": last_run_at,
        "lastRunAgeSeconds": age_seconds,
        "stepCount": len(steps),
        "completedStepCount": completed_steps,
        "failedStepCount": len(failed_steps),
        "failedSteps": failed_steps,
        "detailZh": detail,
        "summary": report.get("summary", {}),
    }


def _agent_loop_health(runtime_dir: Path) -> Dict[str, Any]:
    loop_status = load_json(runtime_dir / AGENT_LOOP_STATUS_FILE)
    supervisor_status = load_json(runtime_dir / AGENT_LOOP_SUPERVISOR_FILE)
    interval = _as_int(loop_status.get("intervalSeconds") or os.environ.get("QG_AGENT_V25_INTERVAL_SECONDS"), 300)
    stale_after = _as_int(os.environ.get("QG_AGENT_V25_STALE_SECONDS"), max(900, interval * 4))
    last_heartbeat = loop_status.get("lastHeartbeatAtIso") or loop_status.get("generatedAtIso")
    age_seconds = _age_seconds(last_heartbeat)
    screen_name = loop_status.get("screenName") or supervisor_status.get("screenName") or "quantgod-agent-v25"
    status = "PASS"
    detail = "Agent v2.5 后台循环在线，Telegram Gateway 会按调度收集并投递。"
    if not loop_status:
        status = "WARN"
        detail = "尚未看到 Agent v2.5 后台循环心跳；请运行 ensure_mac_agent_v25_loop。"
    elif age_seconds is None:
        status = "WARN"
        detail = "Agent v2.5 后台循环心跳时间无法解析。"
    elif age_seconds > stale_after:
        status = "BLOCKED"
        detail = f"Agent v2.5 后台循环心跳已超过 {int(age_seconds)} 秒，自动推送可能中断。"
    elif str(loop_status.get("status") or "").upper() not in {"RUNNING", "COMPLETED"}:
        status = "WARN"
        detail = f"Agent v2.5 后台循环状态：{loop_status.get('status') or 'UNKNOWN'}"
    return {
        "status": status,
        "statusZh": _status_zh(status),
        "screenName": screen_name,
        "mode": loop_status.get("mode") or "loop",
        "pid": loop_status.get("pid"),
        "runtimeDir": loop_status.get("runtimeDir") or str(runtime_dir),
        "lastHeartbeatAtIso": last_heartbeat,
        "lastHeartbeatAgeSeconds": age_seconds,
        "staleAfterSeconds": stale_after,
        "intervalSeconds": interval,
        "sendTelegram": bool(loop_status.get("sendTelegram")),
        "supervisorAction": supervisor_status.get("action"),
        "supervisorReasonZh": supervisor_status.get("reasonZh"),
        "supervisorGeneratedAtIso": supervisor_status.get("generatedAtIso"),
        "detailZh": detail,
    }


def _hfm_crypto_health(runtime_dir: Path, hfm_crypto_runtime_dir: Path | None = None) -> Dict[str, Any]:
    effective_runtime_dir = hfm_crypto_runtime_dir or runtime_dir
    lane = build_hfm_crypto_shadow_lane(effective_runtime_dir, write=False)
    summary = lane.get("summary") if isinstance(lane.get("summary"), dict) else {}
    evidence_found = bool(summary.get("symbolEvidenceFound"))
    status = "PASS" if evidence_found else "WARN"
    detail = "HFM Crypto CFD 影子资料已就绪，执行权限仍关闭。"
    if not evidence_found:
        status = "WARN"
        detail = "等待本机 HFM/MT5 Bases 里出现 BTC/ETH/SOL 等 crypto CFD history 或 tick 证据。"
    return {
        "status": status,
        "statusZh": _status_zh(status),
        "stage": lane.get("stage"),
        "stageZh": lane.get("stageZh"),
        "symbolEvidenceFound": evidence_found,
        "detectedSymbolCount": _as_int(summary.get("detectedSymbolCount"), 0),
        "runtimeDir": str(effective_runtime_dir),
        "mossProfileFound": bool(summary.get("mossProfileFound")),
        "detailZh": detail,
        "walletAuthorizationAllowed": False,
        "hfmCryptoExecutionAllowed": False,
    }


def _telegram_health(runtime_dir: Path) -> Dict[str, Any]:
    status_payload = gateway_status(runtime_dir)
    latest = _latest_delivery(runtime_dir)
    observability = status_payload.get("deliveryObservability") if isinstance(status_payload.get("deliveryObservability"), dict) else {}
    queue_rows = read_jsonl_tail(gateway_queue_path(runtime_dir), limit=500)
    pending_count = _as_int(status_payload.get("pendingCount"), len(queue_rows))
    delivered_count = _as_int(status_payload.get("deliveredCount"), 0)
    push_allowed = bool(status_payload.get("pushAllowed"))
    commands_allowed = bool(status_payload.get("commandsAllowed"))
    latest_reason = str(latest.get("deliveryReason") or "")
    latest_ok = bool(latest.get("deliveryOk")) or latest_reason == "duplicate_suppressed"
    status = "PASS"
    detail = "Telegram Gateway 已启用 push-only 投递。"
    if commands_allowed:
        status = "BLOCKED"
        detail = "Telegram 命令接收被打开，违反 push-only 边界。"
    elif not push_allowed:
        status = "WARN"
        detail = "Telegram 推送未启用，Agent 会生成消息但不会发送。"
    elif pending_count > 0 and delivered_count == 0:
        status = "WARN"
        detail = "Telegram 队列有待投递消息，尚未看到成功投递。"
    elif latest and not latest_ok:
        status = "WARN"
        detail = f"最近 Telegram 投递未成功：{latest_reason or '等待下一轮'}"
    elif latest_reason == "duplicate_suppressed":
        detail = "Telegram Gateway 已启用 push-only 投递；重复报告已自动去重。"
    return {
        "status": status,
        "statusZh": _status_zh(status),
        "queuedCount": _as_int(status_payload.get("queuedCount"), len(queue_rows)),
        "pendingCount": pending_count,
        "deliveredCount": delivered_count,
        "ledgerCount": _as_int(status_payload.get("ledgerCount"), 0),
        "pushAllowed": push_allowed,
        "commandsAllowed": commands_allowed,
        "lastTopic": latest.get("topic") or status_payload.get("lastTopic"),
        "lastEventId": latest.get("eventId") or status_payload.get("lastEventId"),
        "lastDeliveryOk": latest_ok if latest else None,
        "lastDeliveryReason": latest_reason or None,
        "lastDeliveryAtIso": latest.get("sentAtIso"),
        "deliveryObservability": observability,
        "lastActualSentAtIso": status_payload.get("lastActualSentAtIso") or observability.get("lastActualSentAtIso"),
        "lastSuppressedAtIso": status_payload.get("lastSuppressedAtIso") or observability.get("lastSuppressedAtIso"),
        "lastSuppressedReason": status_payload.get("lastSuppressedReason") or observability.get("lastSuppressedReason"),
        "suppressedCount": _as_int(status_payload.get("suppressedCount") or observability.get("suppressedCount"), 0),
        "sentCountByTopic": status_payload.get("sentCountByTopic") or observability.get("sentCountByTopic") or {},
        "pendingByTopic": status_payload.get("pendingByTopic") or observability.get("pendingByTopic") or {},
        "nextEligibleSendAtIso": status_payload.get("nextEligibleSendAtIso") or observability.get("nextEligibleSendAtIso"),
        "detailZh": detail,
    }


def build_agent_ops_health(
    runtime_dir: Path,
    repo_root: Path | None = None,
    write: bool = False,
    hfm_crypto_runtime_dir: Path | str | None = None,
) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    hfm_crypto_runtime = Path(hfm_crypto_runtime_dir) if hfm_crypto_runtime_dir else runtime_dir
    agent_loop = _agent_loop_health(runtime_dir)
    daily = _daily_autopilot_health(runtime_dir, repo_root, hfm_crypto_runtime)
    hfm_crypto = _hfm_crypto_health(runtime_dir, hfm_crypto_runtime)
    telegram = _telegram_health(runtime_dir)
    system_checks = [
        _check("agentV25Loop", "Agent v2.5 后台循环", agent_loop["status"], agent_loop["detailZh"], agent_loop.get("lastHeartbeatAgeSeconds")),
        _check("dailyAutopilot", "Daily Autopilot", daily["status"], daily["detailZh"], daily.get("lastRunAgeSeconds")),
        _check("telegramGateway", "Telegram Gateway", telegram["status"], telegram["detailZh"], telegram.get("pendingCount")),
    ]
    strategy_checks = [
        _check(
            "hfmCryptoShadow",
            "HFM Crypto CFD 影子车道",
            hfm_crypto["status"],
            hfm_crypto["detailZh"],
            hfm_crypto.get("detectedSymbolCount"),
            category="strategy",
        ),
    ]
    checks = [*system_checks, *strategy_checks]
    system_status = _overall_status(system_checks)
    strategy_status = _overall_status(strategy_checks)
    blockers = [check["detailZh"] for check in system_checks if check.get("status") == "BLOCKED"]
    warnings = [check["detailZh"] for check in system_checks if check.get("status") == "WARN"]
    strategy_blockers = [check["detailZh"] for check in strategy_checks if check.get("status") == "BLOCKED"]
    strategy_warnings = [check["detailZh"] for check in strategy_checks if check.get("status") == "WARN"]
    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "agentVersion": AGENT_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "hfmCryptoRuntimeDir": str(hfm_crypto_runtime),
        "overallStatus": system_status,
        "overallStatusZh": _status_zh(system_status),
        "systemStatus": system_status,
        "systemStatusZh": _status_zh(system_status),
        "strategyStatus": strategy_status,
        "strategyStatusZh": _status_zh(strategy_status),
        "ok": system_status != "BLOCKED",
        "strategyOk": strategy_status != "BLOCKED",
        "agentV25Loop": agent_loop,
        "dailyAutopilot": daily,
        "hfmCryptoShadow": hfm_crypto,
        "telegramGateway": telegram,
        "systemChecks": system_checks,
        "strategyChecks": strategy_checks,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "strategyBlockers": strategy_blockers,
        "strategyWarnings": strategy_warnings,
        "allBlockers": [*blockers, *strategy_blockers],
        "allWarnings": [*warnings, *strategy_warnings],
        "safety": {
            **SAFETY_BOUNDARY,
            "agentOpsHealthOnly": True,
            "orderSendAllowed": False,
            "livePresetMutationAllowed": False,
            "telegramCommandsAllowed": False,
        },
    }
    if write:
        write_json(runtime_dir / OUTPUT_FILE, payload)
    return payload
