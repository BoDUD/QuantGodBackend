from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    from daily_autopilot_v2.orchestrator import read_latest_run
    from daily_autopilot_v2.report import build_daily_autopilot_v2
    from usdjpy_evidence_os.io_utils import load_json, read_jsonl_tail, utc_now_iso, write_json
    from usdjpy_evidence_os.schema import SAFETY_BOUNDARY, gateway_ledger_path, gateway_queue_path
    from usdjpy_evidence_os.telegram_gateway import gateway_status
except ModuleNotFoundError:  # pragma: no cover - package import path when run from tests
    from tools.daily_autopilot_v2.orchestrator import read_latest_run
    from tools.daily_autopilot_v2.report import build_daily_autopilot_v2
    from tools.usdjpy_evidence_os.io_utils import load_json, read_jsonl_tail, utc_now_iso, write_json
    from tools.usdjpy_evidence_os.schema import SAFETY_BOUNDARY, gateway_ledger_path, gateway_queue_path
    from tools.usdjpy_evidence_os.telegram_gateway import gateway_status


SCHEMA = "quantgod.agent_ops_health.v1"
AGENT_VERSION = "v2.7-agent-ops-health-fail-closed"
OUTPUT_FILE = Path("agent") / "QuantGod_AgentOpsHealth.json"
AGENT_LOOP_STATUS_FILE = Path("agent") / "QuantGod_AgentV25LoopStatus.json"
AGENT_LOOP_SUPERVISOR_FILE = Path("agent") / "QuantGod_AgentV25SupervisorStatus.json"
LIVE_RUNTIME_PREFLIGHT_FILE = Path("agent") / "QuantGod_LiveRuntimePreflightProbe.json"
HISTORY_PRODUCTION_STATUS_FILE = Path("backtest") / "QuantGod_USDJPYHistoryProductionStatus.json"
GA_STABILITY_REPORT_FILE = Path("production_validation") / "QuantGod_GAMultiGenerationStabilityReport.json"
CORE_EVIDENCE_MANIFEST_FILE = Path("integrity") / "QuantGod_CoreRuntimeEvidenceManifest.json"
REQUIRED_HISTORY_TIMEFRAMES = ("M1", "M5", "M15", "H1")


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


def _as_float(value: Any, fallback: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _status_rank(status: str) -> int:
    normalized = str(status or "UNKNOWN").upper()
    if normalized == "PASS":
        return 0
    if normalized == "WARN":
        return 1
    return 2


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
        "UNKNOWN": "状态未知",
        "STALE": "证据过期",
        "NOT_STARTED": "尚未运行",
        "BLOCKED": "自动化阻断",
    }
    return mapping.get(str(status).upper(), "需要观察")


def _check(
    key: str,
    label: str,
    status: str,
    detail: str,
    metric: Any = None,
    category: str = "system",
    reasons: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
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
    if reasons:
        payload["reason"] = reasons[0]
        payload["reasons"] = reasons
    return payload


def _reason(code: str, status: str, reason_zh: str, value: Any = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "status": status,
        "reasonZh": reason_zh,
    }
    if value is not None:
        payload["value"] = value
    return payload


def _evidence_max_age_seconds() -> int:
    return max(300, _as_int(os.environ.get("QG_AGENT_OPS_EVIDENCE_MAX_AGE_SECONDS"), 86400))


def _artifact_age_seconds(payload: Dict[str, Any], path: Path) -> float | None:
    generated_at = payload.get("generatedAtIso") or payload.get("generatedAt") or payload.get("createdAt")
    age_seconds = _age_seconds(generated_at)
    if age_seconds is not None:
        return age_seconds
    try:
        return max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    except OSError:
        return None


def _worst_readiness_status(statuses: List[str]) -> str:
    normalized = {str(status or "UNKNOWN").upper() for status in statuses}
    for status in ("BLOCKED", "STALE", "UNKNOWN", "WARN"):
        if status in normalized:
            return status
    return "PASS"


def _evidence_health(
    *,
    status: str,
    source_status: str,
    source_path: Path,
    payload: Dict[str, Any],
    reasons: List[Dict[str, Any]],
    pass_code: str,
    pass_detail: str,
    **extra: Any,
) -> Dict[str, Any]:
    structured_reason = reasons[0] if reasons else _reason(pass_code, "PASS", pass_detail)
    return {
        "status": status,
        "statusZh": _status_zh(status),
        "sourceStatus": source_status,
        "sourcePath": str(source_path),
        "sourceSchema": payload.get("schema"),
        "generatedAt": payload.get("generatedAtIso") or payload.get("generatedAt") or payload.get("createdAt"),
        "ageSeconds": _artifact_age_seconds(payload, source_path),
        "reason": structured_reason,
        "reasons": reasons,
        "detailZh": structured_reason["reasonZh"],
        **extra,
    }


def _live_runtime_freshness_health(runtime_dir: Path) -> Dict[str, Any]:
    source_path = runtime_dir / LIVE_RUNTIME_PREFLIGHT_FILE
    payload = load_json(source_path)
    if not payload:
        reasons = [_reason("LIVE_RUNTIME_PREFLIGHT_MISSING", "UNKNOWN", "缺少 live runtime preflight 证据，无法确认 MT5 runtime freshness。")]
        return _evidence_health(
            status="UNKNOWN",
            source_status="UNKNOWN",
            source_path=source_path,
            payload=payload,
            reasons=reasons,
            pass_code="LIVE_RUNTIME_FRESH",
            pass_detail="Live runtime 快照新鲜。",
            snapshotFound=False,
            snapshotFresh=False,
            snapshotAgeSeconds=None,
            maxAgeSeconds=None,
        )

    source_status = str(payload.get("status") or "UNKNOWN").upper()
    snapshot = payload.get("dashboardSnapshot") if isinstance(payload.get("dashboardSnapshot"), dict) else {}
    reasons: List[Dict[str, Any]] = []
    statuses: List[str] = []
    if source_status in {"UNKNOWN", "STALE", "BLOCKED"}:
        statuses.append(source_status)
        reasons.append(_reason("LIVE_RUNTIME_SOURCE_STATUS_NOT_READY", source_status, f"Live runtime preflight 状态为 {source_status}。", source_status))

    snapshot_found = snapshot.get("found") is True
    snapshot_fresh = snapshot.get("fresh") is True
    max_age_seconds = _as_float(snapshot.get("maxAgeSeconds"), 300.0)
    report_age_seconds = _artifact_age_seconds(payload, source_path)
    recorded_snapshot_age = _as_float(snapshot.get("ageSeconds"), None)
    age_candidates = [age for age in (report_age_seconds, recorded_snapshot_age) if age is not None]
    if report_age_seconds is not None and recorded_snapshot_age is not None:
        age_candidates.append(report_age_seconds + recorded_snapshot_age)
    snapshot_path = Path(str(snapshot.get("path"))) if snapshot.get("path") else None
    if snapshot_path:
        try:
            age_candidates.append(max(0.0, datetime.now(timezone.utc).timestamp() - snapshot_path.stat().st_mtime))
        except OSError:
            pass
    snapshot_age_seconds = max(age_candidates) if age_candidates else None

    if not snapshot_found:
        statuses.append("UNKNOWN")
        reasons.append(_reason("LIVE_RUNTIME_SNAPSHOT_UNKNOWN", "UNKNOWN", "Preflight 未找到 MT5 dashboard runtime 快照。"))
    elif not snapshot_fresh or snapshot_age_seconds is None or snapshot_age_seconds > float(max_age_seconds or 300.0):
        statuses.append("STALE")
        reasons.append(
            _reason(
                "LIVE_RUNTIME_SNAPSHOT_STALE",
                "STALE",
                "MT5 dashboard runtime 快照已过期，不能继续报告整体健康。",
                {
                    "ageSeconds": round(snapshot_age_seconds, 3) if snapshot_age_seconds is not None else None,
                    "maxAgeSeconds": max_age_seconds,
                },
            )
        )
    else:
        statuses.append("PASS")

    status = _worst_readiness_status(statuses)
    return _evidence_health(
        status=status,
        source_status=source_status,
        source_path=source_path,
        payload=payload,
        reasons=reasons,
        pass_code="LIVE_RUNTIME_FRESH",
        pass_detail="Live runtime preflight 的 MT5 dashboard 快照新鲜。",
        snapshotFound=snapshot_found,
        snapshotFresh=snapshot_fresh,
        snapshotAgeSeconds=round(snapshot_age_seconds, 3) if snapshot_age_seconds is not None else None,
        maxAgeSeconds=max_age_seconds,
    )


def _history_freshness_sync_health(runtime_dir: Path) -> Dict[str, Any]:
    source_path = runtime_dir / HISTORY_PRODUCTION_STATUS_FILE
    payload = load_json(source_path)
    if not payload:
        reasons = [_reason("HISTORY_PRODUCTION_STATUS_MISSING", "UNKNOWN", "缺少 USDJPY history production status，无法确认 freshness 与 continuous sync。")]
        return _evidence_health(
            status="UNKNOWN",
            source_status="UNKNOWN",
            source_path=source_path,
            payload=payload,
            reasons=reasons,
            pass_code="HISTORY_FRESHNESS_SYNC_PASS",
            pass_detail="USDJPY 历史 freshness 与 continuous sync 通过。",
        )

    source_status = str(payload.get("status") or "UNKNOWN").upper()
    reasons: List[Dict[str, Any]] = []
    statuses: List[str] = []
    artifact_age = _artifact_age_seconds(payload, source_path)
    if artifact_age is None:
        statuses.append("UNKNOWN")
        reasons.append(_reason("HISTORY_STATUS_AGE_UNKNOWN", "UNKNOWN", "USDJPY history production status 时间无法确认。"))
    elif artifact_age > _evidence_max_age_seconds():
        statuses.append("STALE")
        reasons.append(_reason("HISTORY_STATUS_ARTIFACT_STALE", "STALE", "USDJPY history production status 文件已过期。", round(artifact_age, 3)))

    if source_status in {"UNKNOWN", "STALE", "BLOCKED"}:
        statuses.append(source_status)
        reasons.append(_reason("HISTORY_SOURCE_STATUS_NOT_READY", source_status, f"History production status 为 {source_status}。", source_status))
    elif source_status != "PASS" or payload.get("ok") is not True or payload.get("historyTargetSatisfied") is not True:
        statuses.append("BLOCKED")
        reasons.append(_reason("HISTORY_PRODUCTION_GATE_BLOCKED", "BLOCKED", str(payload.get("reasonZh") or "USDJPY 历史数据未达到生产验收。"), source_status))

    freshness = payload.get("copyRatesExportFreshness") if isinstance(payload.get("copyRatesExportFreshness"), dict) else {}
    freshness_status = str(freshness.get("status") or "UNKNOWN").upper()
    if freshness.get("stale") is True or freshness_status == "STALE":
        statuses.append("STALE")
        reasons.append(_reason("COPYRATES_EXPORT_STALE", "STALE", str(freshness.get("nextActionZh") or "MQL5 CopyRates export 已过期。"), freshness.get("staleTimeframes") or freshness_status))
    elif freshness_status not in {"PASS", "FRESH"}:
        statuses.append("UNKNOWN")
        reasons.append(_reason("COPYRATES_EXPORT_FRESHNESS_UNKNOWN", "UNKNOWN", "无法确认 MQL5 CopyRates export freshness。", freshness_status))

    continuous_sync = payload.get("continuousSync") if isinstance(payload.get("continuousSync"), dict) else {}
    sync_status = str(continuous_sync.get("status") or "UNKNOWN").upper()
    if continuous_sync.get("running") is not True:
        normalized_sync_status = "UNKNOWN" if sync_status in {"UNKNOWN", "PROBE_BLOCKED"} else "BLOCKED"
        statuses.append(normalized_sync_status)
        reasons.append(_reason("HISTORY_CONTINUOUS_SYNC_NOT_RUNNING", normalized_sync_status, str(continuous_sync.get("reasonZh") or "USDJPY history continuous sync 未运行或无法确认。"), sync_status))
    elif sync_status not in {"PASS", "RUNNING"}:
        statuses.append("UNKNOWN")
        reasons.append(_reason("HISTORY_CONTINUOUS_SYNC_STATUS_UNKNOWN", "UNKNOWN", "History continuous sync 状态无法确认。", sync_status))

    timeframes = payload.get("timeframes") if isinstance(payload.get("timeframes"), dict) else {}
    missing_timeframes = [name for name in REQUIRED_HISTORY_TIMEFRAMES if not isinstance(timeframes.get(name), dict)]
    stale_timeframes = [
        name
        for name in REQUIRED_HISTORY_TIMEFRAMES
        if isinstance(timeframes.get(name), dict) and timeframes[name].get("freshnessOk") is not True
    ]
    if missing_timeframes:
        statuses.append("UNKNOWN")
        reasons.append(_reason("HISTORY_TIMEFRAMES_MISSING", "UNKNOWN", "History production status 缺少必需周期。", missing_timeframes))
    if stale_timeframes:
        statuses.append("STALE")
        reasons.append(_reason("HISTORY_TIMEFRAMES_STALE", "STALE", "History production status 包含 freshness 未通过的周期。", stale_timeframes))

    if not statuses:
        statuses.append("PASS")
    status = _worst_readiness_status(statuses)
    return _evidence_health(
        status=status,
        source_status=source_status,
        source_path=source_path,
        payload=payload,
        reasons=reasons,
        pass_code="HISTORY_FRESHNESS_SYNC_PASS",
        pass_detail="USDJPY history production、CopyRates freshness 与 continuous sync 均通过。",
        historyTargetSatisfied=payload.get("historyTargetSatisfied") is True,
        copyRatesExportFreshnessStatus=freshness_status,
        continuousSyncStatus=sync_status,
        continuousSyncRunning=continuous_sync.get("running") is True,
        missingTimeframes=missing_timeframes,
        staleTimeframes=stale_timeframes,
    )


def _ga_promotion_health(runtime_dir: Path) -> Dict[str, Any]:
    source_path = runtime_dir / GA_STABILITY_REPORT_FILE
    payload = load_json(source_path)
    if not payload:
        reasons = [_reason("GA_STABILITY_REPORT_MISSING", "UNKNOWN", "缺少 GA multi-generation stability report，无法确认 GA promotion gate。")]
        return _evidence_health(
            status="UNKNOWN",
            source_status="UNKNOWN",
            source_path=source_path,
            payload=payload,
            reasons=reasons,
            pass_code="GA_PROMOTION_GATE_PASS",
            pass_detail="GA 多代稳定性与 promotion gate 通过。",
        )

    source_status = str(payload.get("status") or "UNKNOWN").upper()
    reasons: List[Dict[str, Any]] = []
    statuses: List[str] = []
    artifact_age = _artifact_age_seconds(payload, source_path)
    if artifact_age is None:
        statuses.append("UNKNOWN")
        reasons.append(_reason("GA_STABILITY_AGE_UNKNOWN", "UNKNOWN", "GA stability report 时间无法确认。"))
    elif artifact_age > _evidence_max_age_seconds():
        statuses.append("STALE")
        reasons.append(_reason("GA_STABILITY_REPORT_STALE", "STALE", "GA stability report 已过期。", round(artifact_age, 3)))

    if source_status in {"UNKNOWN", "STALE", "BLOCKED"}:
        statuses.append(source_status)
        reasons.append(_reason("GA_STABILITY_STATUS_NOT_READY", source_status, f"GA stability report 状态为 {source_status}。", source_status))
    elif source_status != "PASS":
        statuses.append("BLOCKED")
        reasons.append(_reason("GA_STABILITY_NOT_PASS", "BLOCKED", "GA multi-generation stability 尚未通过。", source_status))
    if payload.get("ok") is not True:
        statuses.append("BLOCKED")
        reasons.append(_reason("GA_STABILITY_REPORT_NOT_OK", "BLOCKED", "GA stability report 未明确确认 ok=true。", payload.get("ok")))
    if payload.get("promotionAllowed") is not True:
        statuses.append("BLOCKED")
        reasons.append(
            _reason(
                "GA_PROMOTION_NOT_ALLOWED",
                "BLOCKED",
                "GA evidence 当前不允许晋级，不能继续报告整体健康。",
                {
                    "stabilityGrade": payload.get("stabilityGrade") or "UNKNOWN",
                    "closureMode": payload.get("closureMode") or "UNKNOWN",
                },
            )
        )
    ga_blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    if ga_blockers:
        statuses.append("BLOCKED")
    for blocker in ga_blockers:
        reasons.append(_reason("GA_STABILITY_BLOCKER", "BLOCKED", "GA stability report 含 blocker。", str(blocker)))

    if not statuses:
        statuses.append("PASS")
    status = _worst_readiness_status(statuses)
    return _evidence_health(
        status=status,
        source_status=source_status,
        source_path=source_path,
        payload=payload,
        reasons=reasons,
        pass_code="GA_PROMOTION_GATE_PASS",
        pass_detail="GA multi-generation stability 与 promotionAllowed 均通过。",
        stabilityGrade=payload.get("stabilityGrade") or "UNKNOWN",
        closureMode=payload.get("closureMode") or "UNKNOWN",
        promotionAllowed=payload.get("promotionAllowed") is True,
    )


def _promotion_gate_health(runtime_dir: Path) -> Dict[str, Any]:
    source_path = runtime_dir / CORE_EVIDENCE_MANIFEST_FILE
    payload = load_json(source_path)
    if not payload:
        reasons = [_reason("CORE_EVIDENCE_PROMOTION_GATE_MISSING", "UNKNOWN", "缺少 core runtime evidence manifest，无法确认 promotion gate。")]
        return _evidence_health(
            status="UNKNOWN",
            source_status="UNKNOWN",
            source_path=source_path,
            payload=payload,
            reasons=reasons,
            pass_code="CORE_EVIDENCE_PROMOTION_GATE_PASS",
            pass_detail="Core runtime evidence promotion gate 通过。",
        )

    source_status = str(payload.get("promotionGateStatus") or "UNKNOWN").upper()
    manifest_status = str(payload.get("status") or "UNKNOWN").upper()
    reasons: List[Dict[str, Any]] = []
    statuses: List[str] = []
    artifact_age = _artifact_age_seconds(payload, source_path)
    if artifact_age is None:
        statuses.append("UNKNOWN")
        reasons.append(_reason("CORE_EVIDENCE_MANIFEST_AGE_UNKNOWN", "UNKNOWN", "Core runtime evidence manifest 时间无法确认。"))
    elif artifact_age > _evidence_max_age_seconds():
        statuses.append("STALE")
        reasons.append(_reason("CORE_EVIDENCE_MANIFEST_STALE", "STALE", "Core runtime evidence manifest 已过期。", round(artifact_age, 3)))

    if manifest_status in {"UNKNOWN", "STALE", "BLOCKED"}:
        statuses.append(manifest_status)
        reasons.append(_reason("CORE_EVIDENCE_MANIFEST_STATUS_NOT_READY", manifest_status, f"Core runtime evidence manifest 状态为 {manifest_status}。", manifest_status))
    elif manifest_status != "PASS" or payload.get("ok") is not True:
        statuses.append("BLOCKED")
        reasons.append(_reason("CORE_EVIDENCE_MANIFEST_NOT_OK", "BLOCKED", "Core runtime evidence manifest 未明确确认 PASS/ok=true。", manifest_status))

    if source_status in {"UNKNOWN", "STALE", "BLOCKED"}:
        statuses.append(source_status)
        reasons.append(_reason("CORE_EVIDENCE_PROMOTION_GATE_NOT_READY", source_status, f"Core runtime evidence promotion gate 为 {source_status}。", source_status))
    elif source_status != "PASS" or payload.get("promotionGatePassed") is not True:
        statuses.append("BLOCKED")
        reasons.append(_reason("CORE_EVIDENCE_PROMOTION_GATE_BLOCKED", "BLOCKED", "Core runtime evidence 尚未通过 promotion gate。", source_status))
    promotion_blockers = payload.get("promotionBlockers") if isinstance(payload.get("promotionBlockers"), list) else []
    if promotion_blockers:
        statuses.append("BLOCKED")
    for blocker in promotion_blockers:
        reasons.append(_reason("CORE_EVIDENCE_PROMOTION_BLOCKER", "BLOCKED", "Promotion gate 含 blocker。", str(blocker)))

    if not statuses:
        statuses.append("PASS")
    status = _worst_readiness_status(statuses)
    return _evidence_health(
        status=status,
        source_status=source_status,
        source_path=source_path,
        payload=payload,
        reasons=reasons,
        pass_code="CORE_EVIDENCE_PROMOTION_GATE_PASS",
        pass_detail="Core runtime evidence promotion gate 通过。",
        manifestStatus=manifest_status,
        promotionGatePassed=payload.get("promotionGatePassed") is True,
        promotionBlockerCount=len(promotion_blockers),
    )


def _readiness_health(runtime_dir: Path) -> Dict[str, Dict[str, Any]]:
    return {
        "liveRuntimeFreshness": _live_runtime_freshness_health(runtime_dir),
        "historyFreshnessSync": _history_freshness_sync_health(runtime_dir),
        "gaPromotionGate": _ga_promotion_health(runtime_dir),
        "promotionGate": _promotion_gate_health(runtime_dir),
    }


def _structured_check_reasons(checks: List[Dict[str, Any]], *, minimum_rank: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for check in checks:
        if _status_rank(str(check.get("status") or "UNKNOWN")) < minimum_rank:
            continue
        reasons = check.get("reasons") if isinstance(check.get("reasons"), list) else []
        if not reasons:
            reasons = [_reason(f"{check.get('key')}_STATUS", str(check.get("status") or "UNKNOWN"), str(check.get("detailZh") or "状态未通过。"))]
        for reason in reasons:
            if isinstance(reason, dict):
                rows.append({"checkKey": check.get("key"), **reason})
    return rows


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


def _daily_autopilot_health(runtime_dir: Path, repo_root: Path) -> Dict[str, Any]:
    report = build_daily_autopilot_v2(
        runtime_dir,
        repo_root=repo_root,
        write=False,
    )
    latest_run = read_latest_run(runtime_dir)
    steps = latest_run.get("steps") if isinstance(latest_run.get("steps"), list) else []
    completed_status = "COMPLETED_BY_AGENT"
    failed_steps = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            failed_steps.append(f"invalid_step_{index + 1}")
            continue
        if str(step.get("status") or "").upper() != completed_status:
            failed_steps.append(str(step.get("name") or step.get("action") or step.get("step") or "unknown"))
    completed_steps = sum(
        1
        for step in steps
        if isinstance(step, dict) and str(step.get("status") or "").upper() == completed_status
    )
    last_run_at = (
        latest_run.get("completedAtIso")
        or latest_run.get("generatedAtIso")
        or latest_run.get("startedAtIso")
    )
    age_seconds = _age_seconds(last_run_at)
    interval = _as_int(os.environ.get("QG_AGENT_V25_INTERVAL_SECONDS"), 300)
    stale_after = max(1800, interval * 3)
    cycle_found = bool(latest_run) and len(steps) > 0
    cycle_status = str(latest_run.get("status") or "NOT_STARTED").upper()
    completed_by_agent = (
        cycle_found
        and not failed_steps
        and cycle_status == completed_status
        and latest_run.get("completedByAgent") is True
    )
    status = "PASS"
    detail = "Daily Autopilot 持久化周期存在、步骤完整且证据新鲜。"
    if not cycle_found:
        status = "NOT_STARTED"
        detail = "尚未找到包含步骤的 Daily Autopilot 持久化周期；本次 GET 不计为运行。"
    elif failed_steps:
        status = "BLOCKED"
        detail = f"Daily Autopilot 有失败步骤：{', '.join(failed_steps[:4])}"
    elif not completed_by_agent:
        status = "BLOCKED"
        detail = "Daily Autopilot 周期未明确标记 completedByAgent=true。"
    elif age_seconds is None:
        status = "UNKNOWN"
        detail = "Daily Autopilot 持久化周期缺少可解析的运行时间。"
    elif age_seconds > stale_after:
        status = "STALE"
        detail = f"Daily Autopilot 最近一次运行已超过 {int(age_seconds)} 秒。"
    return {
        "status": status,
        "statusZh": _status_zh(status),
        "cycleFound": cycle_found,
        "cycleStatus": cycle_status,
        "completedByAgent": completed_by_agent,
        "autoAppliedByAgent": bool(latest_run.get("autoAppliedByAgent")) if cycle_found else False,
        "reportGeneratedAtIso": report.get("generatedAtIso"),
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
) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    agent_loop = _agent_loop_health(runtime_dir)
    daily = _daily_autopilot_health(runtime_dir, repo_root)
    telegram = _telegram_health(runtime_dir)
    readiness = _readiness_health(runtime_dir)
    system_checks = [
        _check("agentV25Loop", "Agent v2.5 后台循环", agent_loop["status"], agent_loop["detailZh"], agent_loop.get("lastHeartbeatAgeSeconds")),
        _check("dailyAutopilot", "Daily Autopilot", daily["status"], daily["detailZh"], daily.get("lastRunAgeSeconds")),
        _check("telegramGateway", "Telegram Gateway", telegram["status"], telegram["detailZh"], telegram.get("pendingCount")),
    ]
    strategy_checks: List[Dict[str, Any]] = []
    readiness_checks = [
        _check(
            "liveRuntimeFreshness",
            "Live runtime freshness",
            readiness["liveRuntimeFreshness"]["status"],
            readiness["liveRuntimeFreshness"]["detailZh"],
            readiness["liveRuntimeFreshness"].get("snapshotAgeSeconds"),
            category="readiness",
            reasons=readiness["liveRuntimeFreshness"].get("reasons"),
        ),
        _check(
            "historyFreshnessSync",
            "USDJPY history freshness / sync",
            readiness["historyFreshnessSync"]["status"],
            readiness["historyFreshnessSync"]["detailZh"],
            readiness["historyFreshnessSync"].get("staleTimeframes"),
            category="readiness",
            reasons=readiness["historyFreshnessSync"].get("reasons"),
        ),
        _check(
            "gaPromotionGate",
            "GA multi-generation promotion gate",
            readiness["gaPromotionGate"]["status"],
            readiness["gaPromotionGate"]["detailZh"],
            readiness["gaPromotionGate"].get("stabilityGrade"),
            category="readiness",
            reasons=readiness["gaPromotionGate"].get("reasons"),
        ),
        _check(
            "promotionGate",
            "Core runtime evidence promotion gate",
            readiness["promotionGate"]["status"],
            readiness["promotionGate"]["detailZh"],
            readiness["promotionGate"].get("promotionBlockerCount"),
            category="readiness",
            reasons=readiness["promotionGate"].get("reasons"),
        ),
    ]
    critical_checks = [*system_checks, *readiness_checks]
    checks = [*critical_checks, *strategy_checks]
    system_status = _overall_status(system_checks)
    readiness_status = _overall_status(readiness_checks)
    overall_status = _overall_status(critical_checks)
    strategy_status = _overall_status(strategy_checks)
    system_blockers = [check["detailZh"] for check in system_checks if _status_rank(check.get("status", "UNKNOWN")) >= 2]
    system_warnings = [check["detailZh"] for check in system_checks if check.get("status") == "WARN"]
    readiness_blockers = [check["detailZh"] for check in readiness_checks if _status_rank(check.get("status", "UNKNOWN")) >= 2]
    readiness_warnings = [check["detailZh"] for check in readiness_checks if check.get("status") == "WARN"]
    blockers = [*system_blockers, *readiness_blockers]
    warnings = [*system_warnings, *readiness_warnings]
    strategy_blockers = [check["detailZh"] for check in strategy_checks if _status_rank(check.get("status", "UNKNOWN")) >= 2]
    strategy_warnings = [check["detailZh"] for check in strategy_checks if check.get("status") == "WARN"]
    blocking_reasons = _structured_check_reasons(critical_checks, minimum_rank=2)
    warning_reasons = _structured_check_reasons(
        [check for check in critical_checks if check.get("status") == "WARN"],
        minimum_rank=1,
    )
    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "agentVersion": AGENT_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "overallStatus": overall_status,
        "overallStatusZh": _status_zh(overall_status),
        "systemStatus": system_status,
        "systemStatusZh": _status_zh(system_status),
        "readinessStatus": readiness_status,
        "readinessStatusZh": _status_zh(readiness_status),
        "strategyStatus": strategy_status,
        "strategyStatusZh": _status_zh(strategy_status),
        "ok": overall_status == "PASS",
        "strategyOk": strategy_status != "BLOCKED",
        "agentV25Loop": agent_loop,
        "dailyAutopilot": daily,
        "telegramGateway": telegram,
        **readiness,
        "systemChecks": system_checks,
        "readinessChecks": readiness_checks,
        "strategyChecks": strategy_checks,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "systemBlockers": system_blockers,
        "systemWarnings": system_warnings,
        "readinessBlockers": readiness_blockers,
        "readinessWarnings": readiness_warnings,
        "blockingReasons": blocking_reasons,
        "warningReasons": warning_reasons,
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
