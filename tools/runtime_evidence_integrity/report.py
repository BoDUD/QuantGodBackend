from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from tools.case_memory.report import status as case_memory_status
    from tools.case_memory.taxonomy import (
        CATEGORY_GUIDANCE_ZH,
        REQUIRED_CASE_MEMORY_CATEGORIES,
        case_memory_category_counts,
        case_memory_tokens_from_report,
    )
except ModuleNotFoundError:  # pragma: no cover
    from case_memory.report import status as case_memory_status
    from case_memory.taxonomy import (
        CATEGORY_GUIDANCE_ZH,
        REQUIRED_CASE_MEMORY_CATEGORIES,
        case_memory_category_counts,
        case_memory_tokens_from_report,
    )

from .schema import CORE_ARTIFACTS, REPORT_SCHEMA, SAFETY, SCHEMA_VERSION, manifest_path


LEGACY_ABSOLUTE_PATH_RE = re.compile(r"/Users/[^\n\r\t\"']*/Quard/QuantGod(?:/|\b)")
REQUIRED_HISTORY_TIMEFRAMES = ("M1", "M5", "M15", "H1")
SUMMARY_SCHEMA = "quantgod.core_runtime_evidence_summary.v1"
SUMMARY_SCHEMA_VERSION = 1
DEFAULT_SUMMARY_QUEUE_LIMIT = 8
DEFAULT_SUMMARY_BLOCKER_LIMIT = 12
EVIDENCE_RECOVERY_ALLOWED_LANES = ["READ_ONLY_RESEARCH", "SHADOW", "TESTER_ONLY"]
EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS = [
    "ORDER_SEND",
    "POSITION_CLOSE",
    "LIVE_PRESET_MUTATION",
    "MT5_REQUEST_WRITE",
    "WALLET_AUTHORIZATION",
]
HISTORY_SYNC_RECOVERY_MODE = "READ_ONLY_HISTORY_SYNC_LOOP"
HISTORY_SYNC_LOOP_COMMAND = "tools/run_mac_usdjpy_history_sync_loop.sh --loop"
HISTORY_SYNC_ONCE_COMMAND = "tools/run_mac_usdjpy_history_sync_loop.sh --once"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read_text(path: Path, limit_bytes: int = 2_000_000) -> str:
    raw = path.read_bytes()[:limit_bytes]
    return raw.decode("utf-8", errors="ignore")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_jsonl_object(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    return {}
                return payload if isinstance(payload, dict) else {}
    except OSError:
        return {}
    return {}


def _csv_headers(path: Path) -> List[str]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
            reader = csv.reader(handle)
            return [str(value) for value in next(reader, [])]
    except OSError:
        return []


def _declared_json_schema(path: Path, content_type: str) -> tuple[str, Any, Dict[str, Any]]:
    if content_type == "jsonl":
        payload = _first_jsonl_object(path)
    elif content_type == "json":
        payload = _read_json(path)
    else:
        return "", "", {}
    schema = str(payload.get("schema") or "")
    version = payload.get("schemaVersion", payload.get("version", payload.get("agentVersion", "")))
    return schema, version, payload


def _declared_version_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value != ""


def _manifest_hash_rows_ok(payload: Dict[str, Any]) -> bool:
    rows = payload.get("artifacts")
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        if row.get("exists") is False:
            continue
        if not str(row.get("sha256") or ""):
            return False
    return True


def _history_timeframe_passed(row: Dict[str, Any]) -> bool:
    return bool(
        row.get("passed")
        or (row.get("spanOk") and row.get("densityOk") and row.get("freshnessOk"))
    )


def _copyrates_queue_context(copyrates_freshness: Dict[str, Any] | None, timeframe: str) -> Dict[str, Any]:
    if not isinstance(copyrates_freshness, dict) or not copyrates_freshness:
        return {}
    lag_by_timeframe = (
        copyrates_freshness.get("latestLagHoursByTimeframe")
        if isinstance(copyrates_freshness.get("latestLagHoursByTimeframe"), dict)
        else {}
    )
    stale_timeframes = (
        copyrates_freshness.get("staleTimeframes")
        if isinstance(copyrates_freshness.get("staleTimeframes"), list)
        else []
    )
    return {
        "copyRatesExportSchemaVersion": copyrates_freshness.get("schemaVersion"),
        "copyRatesExportFreshnessStatus": copyrates_freshness.get("status"),
        "copyRatesExportStale": bool(copyrates_freshness.get("stale")),
        "copyRatesExportGeneratedAtServer": copyrates_freshness.get("generatedAtServer") or "",
        "copyRatesExportGeneratedLagHours": copyrates_freshness.get("generatedLagHours"),
        "copyRatesExportLatestLagHours": lag_by_timeframe.get(timeframe),
        "copyRatesExportStaleTimeframes": list(stale_timeframes),
        "copyRatesExportNextActionZh": copyrates_freshness.get("nextActionZh") or "",
    }


def _continuous_sync_queue_context(continuous_sync: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(continuous_sync, dict) or not continuous_sync:
        return {}
    return {
        "continuousSyncSchemaVersion": continuous_sync.get("schemaVersion"),
        "continuousSyncStatus": continuous_sync.get("status") or "",
        "continuousSyncRunning": bool(continuous_sync.get("running")),
        "continuousSyncMode": continuous_sync.get("mode") or "",
        "continuousSyncScript": continuous_sync.get("script") or "",
        "continuousSyncStartupCommand": continuous_sync.get("startupCommand") or continuous_sync.get("script") or "",
        "continuousSyncOnceCommand": continuous_sync.get("onceCommand") or "",
        "continuousSyncLaunchdService": continuous_sync.get("launchdService") or "",
        "continuousSyncMatchingProcessCount": continuous_sync.get("matchingProcessCount"),
        "continuousSyncProbePermissionDenied": bool(continuous_sync.get("probePermissionDenied")),
        "continuousSyncHostProbeCommand": continuous_sync.get("hostProbeCommand") or "",
        "continuousSyncNextActionZh": continuous_sync.get("nextActionZh") or "",
        "continuousSyncAcceptanceZh": continuous_sync.get("acceptanceZh") or "",
        "continuousSyncAllowedLanes": (
            list(continuous_sync.get("allowedLanes"))
            if isinstance(continuous_sync.get("allowedLanes"), list)
            else []
        ),
        "continuousSyncForbiddenSideEffects": (
            list(continuous_sync.get("forbiddenSideEffects"))
            if isinstance(continuous_sync.get("forbiddenSideEffects"), list)
            else []
        ),
        "continuousSyncRequiresFreshCopyRatesExporter": bool(
            continuous_sync.get("requiresFreshCopyRatesExporter")
        ),
    }


def _history_sync_recovery_contract_blockers(
    continuous_sync: Dict[str, Any],
    stale_timeframes: List[str],
) -> List[str]:
    if not stale_timeframes:
        return []
    blockers: List[str] = []
    if not isinstance(continuous_sync, dict) or not continuous_sync:
        return ["history_sync_recovery_contract_missing"]

    if continuous_sync.get("expected") is not True:
        blockers.append("history_sync_recovery_contract_expected_not_true")
    if continuous_sync.get("mode") != HISTORY_SYNC_RECOVERY_MODE:
        blockers.append("history_sync_recovery_contract_mode_missing")
    if continuous_sync.get("startupCommand") != HISTORY_SYNC_LOOP_COMMAND:
        blockers.append("history_sync_recovery_contract_startup_missing")
    if continuous_sync.get("onceCommand") != HISTORY_SYNC_ONCE_COMMAND:
        blockers.append("history_sync_recovery_contract_once_missing")
    if continuous_sync.get("requiresFreshCopyRatesExporter") is not True:
        blockers.append("history_sync_recovery_contract_copyrates_requirement_missing")
    if not continuous_sync.get("acceptanceZh"):
        blockers.append("history_sync_recovery_contract_acceptance_missing")

    allowed_lanes = set(continuous_sync.get("allowedLanes") or [])
    if not set(EVIDENCE_RECOVERY_ALLOWED_LANES).issubset(allowed_lanes):
        blockers.append("history_sync_recovery_contract_allowed_lanes_missing")
    forbidden_side_effects = set(continuous_sync.get("forbiddenSideEffects") or [])
    if not set(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS).issubset(forbidden_side_effects):
        blockers.append("history_sync_recovery_contract_forbidden_side_effects_missing")

    safety = continuous_sync.get("safety") if isinstance(continuous_sync.get("safety"), dict) else {}
    for key in (
        "orderSendAllowed",
        "closeAllowed",
        "cancelAllowed",
        "livePresetMutationAllowed",
        "telegramCommandExecutionAllowed",
    ):
        if safety.get(key) is not False:
            blockers.append(f"history_sync_recovery_contract_safety_unlock:{key}")
    return blockers


def _history_recovery_queue(
    rows: Dict[str, Dict[str, Any]],
    copyrates_freshness: Dict[str, Any] | None = None,
    continuous_sync: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    refresh_command = (
        "python3 tools/run_usdjpy_strategy_backtest.py --runtime-dir ./runtime "
        "sync-klines --months 12 --timeframes M1,M5,M15,H1"
    )
    verify_command = (
        "python3 tools/run_usdjpy_strategy_backtest.py --runtime-dir ./runtime production-status "
        "--months 12 --max-latest-lag-hours 96"
    )
    queue: List[Dict[str, Any]] = []
    for timeframe in REQUIRED_HISTORY_TIMEFRAMES:
        row = rows.get(timeframe, {})
        latest_lag = row.get("latestLagHours")
        max_lag = row.get("maxLatestLagHours") or 96.0
        excess_lag = None
        if isinstance(latest_lag, (int, float)) and isinstance(max_lag, (int, float)):
            excess_lag = round(max(0.0, float(latest_lag) - float(max_lag)), 3)
        if row.get("passed"):
            status = "PASS"
            priority = "OK"
            next_action = "该周期历史 freshness 已通过；保持后台增量同步。"
        elif row.get("spanOk") and row.get("densityOk") and not row.get("freshnessOk"):
            status = "FRESHNESS_STALE"
            priority = "HIGH"
            next_action = (
                f"{timeframe} 覆盖和密度已满足，但 latestLagHours 超过阈值；恢复 MT5/MQL5 "
                "CopyRates 数据源后运行 sync-klines，再刷新 production-status。"
            )
        else:
            status = "COVERAGE_OR_DENSITY_BLOCKED"
            priority = "MEDIUM"
            next_action = f"{timeframe} 覆盖或密度未通过；运行更长 lookback 的 sync-klines 并复核表内 bar count。"
        queue_row = {
            "timeframe": timeframe,
            "status": status,
            "priority": priority,
            "spanDays": row.get("spanDays"),
            "latestLagHours": latest_lag,
            "maxLatestLagHours": max_lag,
            "excessLagHours": excess_lag,
            "spanOk": bool(row.get("spanOk")),
            "densityOk": bool(row.get("densityOk")),
            "freshnessOk": bool(row.get("freshnessOk")),
            "passed": bool(row.get("passed")),
            "refreshCommand": refresh_command,
            "verifyCommand": verify_command,
            "nextActionZh": next_action,
            "acceptanceZh": (
                f"{timeframe} spanOk=true、densityOk=true、freshnessOk=true、passed=true，且 "
                "historyTargetSatisfied=true。"
            ),
            "allowedLanes": ["READ_ONLY_RESEARCH", "SHADOW", "TESTER_ONLY"],
            "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
        }
        queue_row.update(_copyrates_queue_context(copyrates_freshness, timeframe))
        queue_row.update(_continuous_sync_queue_context(continuous_sync))
        queue.append(queue_row)
    return queue


def _history_promotion_gate(payload: Dict[str, Any]) -> Dict[str, Any]:
    timeframes = payload.get("timeframes")
    blockers: List[str] = []
    rows: Dict[str, Dict[str, Any]] = {}

    if str(payload.get("status") or "").upper() != "PASS":
        blockers.append("history_status_not_pass")
    if payload.get("historyTargetSatisfied") is not True:
        blockers.append("history_target_not_satisfied")
    if not isinstance(timeframes, dict):
        blockers.append("history_timeframes_missing")
        timeframes = {}

    for timeframe in REQUIRED_HISTORY_TIMEFRAMES:
        raw = timeframes.get(timeframe) if isinstance(timeframes.get(timeframe), dict) else {}
        row = {
            "timeframe": timeframe,
            "spanOk": bool(raw.get("spanOk")),
            "densityOk": bool(raw.get("densityOk")),
            "freshnessOk": bool(raw.get("freshnessOk")),
            "passed": _history_timeframe_passed(raw),
            "spanDays": raw.get("spanDays"),
            "latestLagHours": raw.get("latestLagHours"),
            "maxLatestLagHours": raw.get("maxLatestLagHours") or payload.get("maxLatestLagHours"),
        }
        rows[timeframe] = row
        if not row["spanOk"]:
            blockers.append(f"{timeframe}:span_not_ok")
        if not row["densityOk"]:
            blockers.append(f"{timeframe}:density_not_ok")
        if not row["freshnessOk"]:
            blockers.append(f"{timeframe}:freshness_not_ok")
        if not row["passed"]:
            blockers.append(f"{timeframe}:not_passed")

    copyrates_freshness = (
        payload.get("copyRatesExportFreshness")
        if isinstance(payload.get("copyRatesExportFreshness"), dict)
        else {}
    )
    continuous_sync = payload.get("continuousSync") if isinstance(payload.get("continuousSync"), dict) else {}
    stale_timeframes = [timeframe for timeframe, row in rows.items() if not row.get("freshnessOk")]
    blockers.extend(_history_sync_recovery_contract_blockers(continuous_sync, stale_timeframes))
    passed = not blockers
    recovery_queue = _history_recovery_queue(rows, copyrates_freshness, continuous_sync)
    return {
        "gateId": "history_freshness_promotion_gate",
        "requiredFor": ["ga_promotion", "champion_promotion"],
        "requiredTimeframes": list(REQUIRED_HISTORY_TIMEFRAMES),
        "passed": passed,
        "status": "PASS" if passed else "BLOCKED",
        "statusZh": "历史数据可作为晋级前置证据" if passed else "历史数据 freshness/覆盖未通过，禁止晋级",
        "blockers": blockers,
        "timeframes": rows,
        "staleTimeframes": stale_timeframes,
        "copyRatesExportFreshness": copyrates_freshness,
        "continuousSync": continuous_sync,
        "freshnessRecoveryQueue": recovery_queue,
        "nextActionZh": (
            "历史数据 freshness 已通过；保持后台增量同步。"
            if passed
            else "按 freshnessRecoveryQueue 刷新 M1/M5/M15/H1；通过 production-status 前禁止 GA/champion 晋级。"
        ),
    }


def _candidate_report_path(runtime_dir: Path, manifest: Dict[str, Any]) -> Path:
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, list):
        for row in artifacts:
            if not isinstance(row, dict):
                continue
            if row.get("artifactId") == "candidateReport" and row.get("path"):
                return runtime_dir / str(row["path"])
    return runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"


def _candidate_ledger_path(runtime_dir: Path, manifest: Dict[str, Any]) -> Path:
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, list):
        for row in artifacts:
            if not isinstance(row, dict):
                continue
            if row.get("artifactId") == "candidateLedger" and row.get("path"):
                return runtime_dir / str(row["path"])
    return runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidateLedger.jsonl"


def _candidate_ledger_summary(path: Path) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except OSError:
        rows = []
    case_type_counts: Dict[str, int] = {}
    for row in rows:
        case_type = str(row.get("caseType") or row.get("type") or "").strip()
        if not case_type:
            continue
        case_type_counts[case_type] = case_type_counts.get(case_type, 0) + 1
    return {
        "schema": "quantgod.case_memory_candidate_ledger_summary.v1",
        "path": path.name,
        "present": path.exists(),
        "rowCount": len(rows),
        "caseTypeCounts": case_type_counts,
    }


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _case_memory_status_payload(runtime_dir: Path) -> Dict[str, Any]:
    try:
        payload = case_memory_status(runtime_dir)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _case_memory_promotion_gate(runtime_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    blockers: List[str] = []
    report_path = _candidate_report_path(runtime_dir, manifest)
    report = _read_json(report_path)
    hydrated_report = _case_memory_status_payload(runtime_dir)
    if not report:
        blockers.append("candidate_report_missing_or_unreadable")
        report = hydrated_report
    else:
        if hydrated_report.get("schema") == report.get("schema"):
            for key in ("candidateLedgerSummary", "sourceEvidenceGaps", "coveragePlan"):
                if key in hydrated_report:
                    report[key] = hydrated_report[key]
        else:
            report["candidateLedgerSummary"] = _candidate_ledger_summary(
                _candidate_ledger_path(runtime_dir, manifest)
            )

    tokens = case_memory_tokens_from_report(report)
    counts = case_memory_category_counts(tokens)
    missing = [category for category, count in counts.items() if count <= 0]
    for category in missing:
        blockers.append(f"missing_category:{category}")

    candidate_count = _safe_int(report.get("candidateCount"), len(report.get("candidates") or []))
    ga_seed_count = _safe_int(report.get("gaSeedCount"), len(report.get("gaSeeds") or []))
    if candidate_count <= 0:
        blockers.append("candidate_count_zero")
    if ga_seed_count <= 0:
        blockers.append("ga_seed_count_zero")

    passed = not blockers
    return {
        "gateId": "case_memory_taxonomy_promotion_gate",
        "requiredFor": ["ga_promotion", "champion_promotion"],
        "requiredCategories": list(REQUIRED_CASE_MEMORY_CATEGORIES),
        "passed": passed,
        "status": "PASS" if passed else "BLOCKED",
        "statusZh": "Case Memory 样本类型覆盖可用于晋级评审" if passed else "Case Memory 样本类型不足，禁止晋级",
        "candidateReportPath": _relative_path(runtime_dir, report_path),
        "candidateCount": candidate_count,
        "gaSeedCount": ga_seed_count,
        "observedTokenCount": len(tokens),
        "categoryCounts": counts,
        "missingCategories": missing,
        "sourceEvidenceGaps": (
            report.get("sourceEvidenceGaps")
            if isinstance(report.get("sourceEvidenceGaps"), dict)
            else {}
        ),
        "coveragePlan": (
            report.get("coveragePlan") if isinstance(report.get("coveragePlan"), dict) else {}
        ),
        "blockers": blockers,
    }


def _parity_promotion_gate(payload: Dict[str, Any]) -> Dict[str, Any]:
    gate = payload.get("promotionGate") if isinstance(payload.get("promotionGate"), dict) else {}
    blockers: List[str] = []
    blocker_details: List[Dict[str, Any]] = []
    report_status = str(payload.get("status") or "").upper()
    gate_status = str(gate.get("status") or "").upper()

    if report_status != "PARITY_PASS":
        blockers.append(f"parity_status:{report_status or 'missing'}")
    if gate_status != "PASS":
        blockers.append(f"promotion_gate_status:{gate_status or 'missing'}")
    if gate.get("promotionAllowed") is not True:
        blockers.append("promotion_not_allowed")

    for item in gate.get("blockers") if isinstance(gate.get("blockers"), list) else []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("code") or "parity_blocker")
            blockers.append(name)
            blocker_details.append(item)
        else:
            name = str(item)
            blockers.append(name)
            blocker_details.append({"name": name})

    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    for key in (
        "orderSendAllowed",
        "closeAllowed",
        "cancelAllowed",
        "livePresetMutationAllowed",
        "telegramCommandExecutionAllowed",
    ):
        if safety.get(key) is not False:
            blockers.append(f"safety_unlock:{key}")

    seen: set[str] = set()
    deduped_blockers: List[str] = []
    for blocker in blockers:
        if blocker in seen:
            continue
        seen.add(blocker)
        deduped_blockers.append(blocker)

    passed = not deduped_blockers
    return {
        "gateId": "strategy_parity_promotion_gate",
        "requiredFor": ["ga_promotion", "champion_promotion"],
        "requiredEvidence": [
            "Strategy JSON",
            "Python bar replay",
            "MQL5 EA diagnostics",
        ],
        "passed": passed,
        "status": "PASS" if passed else "BLOCKED",
        "statusZh": (
            "Strategy JSON / Python Replay / MQL5 EA parity 可用于晋级评审"
            if passed
            else "Strategy JSON / Python Replay / MQL5 EA parity 未通过，禁止晋级"
        ),
        "reportStatus": payload.get("status") or "",
        "promotionAllowed": bool(gate.get("promotionAllowed")),
        "blockers": deduped_blockers,
        "blockerDetails": blocker_details,
        "reasonZh": gate.get("reasonZh") or payload.get("reasonZh") or "",
        "refreshCommand": "python3 tools/run_strategy_parity.py --runtime-dir ./runtime build --write",
        "verifyCommand": "python3 tools/run_runtime_evidence_integrity.py --runtime-dir ./runtime verify",
        "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
        "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
        "nextActionZh": (
            "parity 已通过；保持 Strategy JSON、Python replay、MQL5 EA diagnostics 同步。"
            if passed
            else "先刷新 Strategy JSON backtest、bar replay 与 MQL5 EA diagnostics，再运行 strategy parity；只允许 shadow/tester/read-only 证据。"
        ),
    }


def _ga_stability_promotion_gate(payload: Dict[str, Any]) -> Dict[str, Any]:
    blockers: List[str] = []
    status = str(payload.get("status") or "").upper()
    grade = str(payload.get("stabilityGrade") or "").upper()
    promotion_allowed = payload.get("promotionAllowed") is True
    generation_count = _safe_int(payload.get("generationCount"))
    candidate_count = _safe_int(payload.get("candidateCount"))
    elite_count = _safe_int(payload.get("eliteCount"))
    closure_mode = str(payload.get("closureMode") or "")

    if status != "PASS":
        blockers.append(f"stability_status:{status or 'missing'}")
    if grade not in {"STABLE", "PRODUCTION_READY"}:
        blockers.append(f"stability_grade:{grade or 'missing'}")
    if not promotion_allowed:
        blockers.append("promotion_not_allowed")

    for item in payload.get("blockers") if isinstance(payload.get("blockers"), list) else []:
        blockers.append(str(item))

    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    for key in (
        "orderSendAllowed",
        "closeAllowed",
        "cancelAllowed",
        "livePresetMutationAllowed",
        "telegramCommandExecutionAllowed",
        "writesMt5OrderRequest",
    ):
        if safety.get(key) is not False:
            blockers.append(f"safety_unlock:{key}")

    deduped_blockers: List[str] = []
    seen: set[str] = set()
    for blocker in blockers:
        if blocker in seen:
            continue
        seen.add(blocker)
        deduped_blockers.append(blocker)

    passed = not deduped_blockers
    if passed:
        next_action = "GA 多代稳定性已可用于晋级评审；继续保持 walk-forward、parity 与 Case Memory 覆盖。"
    elif grade == "NEGATIVE_SELECTION_CLOSED":
        next_action = "GA 已形成负筛选闭环但当前无可晋级 elite；扩大下一轮搜索并把过拟合/淘汰样本写入 Case Memory。"
    else:
        next_action = "先运行 GA multi-generation stability build，补齐多代候选、elite 重复、lineage 和 graveyard 证据。"

    return {
        "gateId": "ga_multi_generation_stability_promotion_gate",
        "requiredFor": ["ga_promotion", "champion_promotion"],
        "requiredEvidence": [
            "GA candidate runs",
            "GA factory ledger",
            "elite repeat evidence",
            "lineage graph",
            "graveyard / blocker samples",
        ],
        "passed": passed,
        "status": "PASS" if passed else "BLOCKED",
        "statusZh": (
            "GA 多代稳定性可用于晋级评审"
            if passed
            else "GA 多代稳定性尚不允许晋级"
        ),
        "reportStatus": status,
        "stabilityGrade": grade,
        "closureMode": closure_mode,
        "promotionAllowed": promotion_allowed,
        "generationCount": generation_count,
        "candidateCount": candidate_count,
        "eliteCount": elite_count,
        "eliteRepeatCount": _safe_int(payload.get("eliteRepeatCount")),
        "lineageDepth": _safe_int(payload.get("lineageDepth")),
        "factoryLedgerRows": _safe_int(payload.get("factoryLedgerRows")),
        "blockers": deduped_blockers,
        "recommendationsZh": (
            payload.get("recommendationsZh")
            if isinstance(payload.get("recommendationsZh"), list)
            else []
        ),
        "refreshCommand": "python3 tools/run_ga_multi_generation_stability.py --runtime-dir ./runtime build --write",
        "verifyCommand": "python3 tools/run_runtime_evidence_integrity.py --runtime-dir ./runtime verify",
        "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
        "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
        "nextActionZh": next_action,
    }


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _row_status(blockers: Iterable[str]) -> str:
    return "PASS" if not list(blockers) else "FAIL"


def _artifact_row(runtime_dir: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    rel_path = str(spec["path"])
    path = runtime_dir / rel_path
    content_type = str(spec.get("contentType") or "json")
    expected_schemas = [str(item) for item in spec.get("expectedSchemas", [])]
    requires_declared_version = bool(spec.get("requiresDeclaredVersion"))
    blockers: List[str] = []
    payload: Dict[str, Any] = {}
    declared_schema = ""
    declared_version: Any = ""
    declared_version_present = False
    version_status = "NOT_APPLICABLE"
    headers: List[str] = []

    if not path.exists():
        if spec.get("required"):
            blockers.append("missing_required_artifact")
        return {
            "artifactId": spec["artifactId"],
            "category": spec.get("category", "runtime"),
            "required": bool(spec.get("required")),
            "path": rel_path,
            "contentType": content_type,
            "exists": False,
            "sizeBytes": 0,
            "sha256": "",
            "hashAlgorithm": "sha256",
            "expectedSchemas": expected_schemas,
            "declaredSchema": "",
            "declaredVersion": "",
            "declaredVersionPresent": False,
            "requiresDeclaredVersion": requires_declared_version,
            "versionStatus": "MISSING_ARTIFACT",
            "headers": [],
            "status": _row_status(blockers),
            "blockers": blockers,
        }

    size_bytes = path.stat().st_size
    file_hash = _sha256(path)
    if content_type in {"json", "jsonl"}:
        declared_schema, declared_version, payload = _declared_json_schema(path, content_type)
        declared_version_present = _declared_version_present(declared_version)
        version_status = (
            "DECLARED_VERSION_PRESENT"
            if declared_version_present
            else "MISSING_REQUIRED_VERSION"
            if requires_declared_version
            else "MISSING_OPTIONAL_VERSION"
        )
        if not declared_schema:
            blockers.append("missing_declared_schema")
        elif expected_schemas and declared_schema not in expected_schemas:
            blockers.append("schema_mismatch")
        if requires_declared_version and not declared_version_present:
            blockers.append("missing_declared_version")
    elif content_type == "csv":
        declared_schema = expected_schemas[0] if expected_schemas else ""
        headers = _csv_headers(path)
        if not headers:
            blockers.append("missing_csv_headers")
    else:
        blockers.append("unsupported_content_type")

    if LEGACY_ABSOLUTE_PATH_RE.search(_read_text(path)):
        blockers.append("legacy_quantgod_absolute_path")

    if spec.get("requiresArtifactHashes") and not _manifest_hash_rows_ok(payload):
        blockers.append("manifest_missing_artifact_hashes")

    promotion_gate = (
        _history_promotion_gate(payload)
        if spec.get("requiresHistoryPromotionGate") and content_type == "json"
        else None
    )
    if spec.get("requiresParityPromotionGate") and content_type == "json":
        promotion_gate = _parity_promotion_gate(payload)
    if spec.get("requiresGaStabilityPromotionGate") and content_type == "json":
        promotion_gate = _ga_stability_promotion_gate(payload)
    if spec.get("requiresCaseMemoryPromotionGate") and content_type == "json":
        promotion_gate = _case_memory_promotion_gate(runtime_dir, payload)

    row = {
        "artifactId": spec["artifactId"],
        "category": spec.get("category", "runtime"),
        "required": bool(spec.get("required")),
        "path": rel_path,
        "contentType": content_type,
        "exists": True,
        "sizeBytes": size_bytes,
        "sha256": file_hash,
        "hashAlgorithm": "sha256",
        "expectedSchemas": expected_schemas,
        "declaredSchema": declared_schema,
        "declaredVersion": declared_version,
        "declaredVersionPresent": declared_version_present,
        "requiresDeclaredVersion": requires_declared_version,
        "versionStatus": version_status,
        "headers": headers,
        "status": _row_status(blockers),
        "blockers": blockers,
    }
    if promotion_gate:
        row["promotionGate"] = promotion_gate
    return row


def _promotion_recovery_queue(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    queue: List[Dict[str, Any]] = []
    for row in rows:
        artifact_id = str(row.get("artifactId") or "")
        gate = row.get("promotionGate")
        if not isinstance(gate, dict) or gate.get("passed") is True:
            continue

        if artifact_id == "historyProductionStatus":
            for item in gate.get("freshnessRecoveryQueue") if isinstance(gate.get("freshnessRecoveryQueue"), list) else []:
                if not isinstance(item, dict):
                    continue
                if item.get("passed") is True and str(item.get("status") or "").upper() == "PASS":
                    continue
                queue.append(
                    {
                        "kind": "history_freshness",
                        "artifactId": artifact_id,
                        "artifactPath": row.get("path"),
                        "gateId": gate.get("gateId"),
                        "timeframe": item.get("timeframe"),
                        "status": item.get("status"),
                        "priority": item.get("priority"),
                        "latestLagHours": item.get("latestLagHours"),
                        "maxLatestLagHours": item.get("maxLatestLagHours"),
                        "excessLagHours": item.get("excessLagHours"),
                        "copyRatesExportFreshnessStatus": item.get("copyRatesExportFreshnessStatus"),
                        "copyRatesExportSchemaVersion": item.get("copyRatesExportSchemaVersion"),
                        "copyRatesExportStale": item.get("copyRatesExportStale"),
                        "copyRatesExportGeneratedAtServer": item.get("copyRatesExportGeneratedAtServer"),
                        "copyRatesExportGeneratedLagHours": item.get("copyRatesExportGeneratedLagHours"),
                        "copyRatesExportLatestLagHours": item.get("copyRatesExportLatestLagHours"),
                        "copyRatesExportStaleTimeframes": item.get("copyRatesExportStaleTimeframes"),
                        "copyRatesExportNextActionZh": item.get("copyRatesExportNextActionZh"),
                        "continuousSyncStatus": item.get("continuousSyncStatus"),
                        "continuousSyncSchemaVersion": item.get("continuousSyncSchemaVersion"),
                        "continuousSyncRunning": item.get("continuousSyncRunning"),
                        "continuousSyncMode": item.get("continuousSyncMode"),
                        "continuousSyncScript": item.get("continuousSyncScript"),
                        "continuousSyncStartupCommand": item.get("continuousSyncStartupCommand"),
                        "continuousSyncOnceCommand": item.get("continuousSyncOnceCommand"),
                        "continuousSyncLaunchdService": item.get("continuousSyncLaunchdService"),
                        "continuousSyncMatchingProcessCount": item.get("continuousSyncMatchingProcessCount"),
                        "continuousSyncProbePermissionDenied": item.get("continuousSyncProbePermissionDenied"),
                        "continuousSyncHostProbeCommand": item.get("continuousSyncHostProbeCommand"),
                        "continuousSyncNextActionZh": item.get("continuousSyncNextActionZh"),
                        "continuousSyncAcceptanceZh": item.get("continuousSyncAcceptanceZh"),
                        "continuousSyncAllowedLanes": item.get("continuousSyncAllowedLanes"),
                        "continuousSyncForbiddenSideEffects": item.get("continuousSyncForbiddenSideEffects"),
                        "continuousSyncRequiresFreshCopyRatesExporter": item.get(
                            "continuousSyncRequiresFreshCopyRatesExporter"
                        ),
                        "refreshCommand": item.get("refreshCommand"),
                        "verifyCommand": item.get("verifyCommand"),
                        "nextActionZh": item.get("nextActionZh"),
                        "acceptanceZh": item.get("acceptanceZh"),
                        "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
                        "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
                    }
                )
            continue

        if artifact_id == "strategyParityReport":
            queue.append(
                {
                    "kind": "strategy_parity",
                    "artifactId": artifact_id,
                    "artifactPath": row.get("path"),
                    "gateId": gate.get("gateId"),
                    "status": gate.get("status"),
                    "priority": "HIGH",
                    "reportStatus": gate.get("reportStatus"),
                    "promotionAllowed": gate.get("promotionAllowed"),
                    "blockers": list(gate.get("blockers", []))
                    if isinstance(gate.get("blockers"), list)
                    else [],
                    "blockerDetails": list(gate.get("blockerDetails", []))
                    if isinstance(gate.get("blockerDetails"), list)
                    else [],
                    "sourceArtifacts": [
                        "backtest/QuantGod_StrategyBacktestReport.json",
                        "replay/usdjpy/QuantGod_USDJPYBarReplayReport.json",
                        "QuantGod_USDJPYRsiEntryDiagnostics.json",
                    ],
                    "refreshCommand": gate.get("refreshCommand"),
                    "verifyCommand": gate.get("verifyCommand"),
                    "nextActionZh": gate.get("nextActionZh"),
                    "acceptanceZh": "promotionGate.status=PASS、promotionAllowed=true、status=PARITY_PASS，且 safety 执行开关保持 false。",
                    "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
                    "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
                }
            )
            continue

        if artifact_id == "gaMultiGenerationStabilityReport":
            queue.append(
                {
                    "kind": "ga_multi_generation_stability",
                    "artifactId": artifact_id,
                    "artifactPath": row.get("path"),
                    "gateId": gate.get("gateId"),
                    "status": gate.get("status"),
                    "priority": "HIGH",
                    "reportStatus": gate.get("reportStatus"),
                    "stabilityGrade": gate.get("stabilityGrade"),
                    "closureMode": gate.get("closureMode"),
                    "promotionAllowed": gate.get("promotionAllowed"),
                    "generationCount": gate.get("generationCount"),
                    "candidateCount": gate.get("candidateCount"),
                    "eliteCount": gate.get("eliteCount"),
                    "eliteRepeatCount": gate.get("eliteRepeatCount"),
                    "lineageDepth": gate.get("lineageDepth"),
                    "factoryLedgerRows": gate.get("factoryLedgerRows"),
                    "blockers": list(gate.get("blockers", []))
                    if isinstance(gate.get("blockers"), list)
                    else [],
                    "recommendationsZh": list(gate.get("recommendationsZh", []))
                    if isinstance(gate.get("recommendationsZh"), list)
                    else [],
                    "sourceArtifacts": [
                        "ga/QuantGod_GACandidateRuns.jsonl",
                        "ga/QuantGod_GAStatus.json",
                        "ga/QuantGod_GABlockerSummary.json",
                        "ga_factory/QuantGod_GAFactoryLedger.csv",
                        "ga_factory/QuantGod_GAStrategyGraveyard.json",
                    ],
                    "refreshCommand": gate.get("refreshCommand"),
                    "verifyCommand": gate.get("verifyCommand"),
                    "nextActionZh": gate.get("nextActionZh"),
                    "acceptanceZh": (
                        "status=PASS、stabilityGrade=STABLE/PRODUCTION_READY、promotionAllowed=true，"
                        "且 safety 执行开关保持 false。"
                    ),
                    "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
                    "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
                }
            )
            continue

        if artifact_id == "caseMemoryArtifactManifest":
            blockers = [str(blocker) for blocker in gate.get("blockers", [])]
            coverage_plan = gate.get("coveragePlan") if isinstance(gate.get("coveragePlan"), dict) else {}
            collection_rows: Dict[str, Dict[str, Any]] = {}
            for item in (
                coverage_plan.get("nextCollectionQueue")
                if isinstance(coverage_plan.get("nextCollectionQueue"), list)
                else []
            ):
                if not isinstance(item, dict):
                    continue
                category = str(item.get("category") or "")
                if category:
                    collection_rows[category] = item
            if "candidate_report_missing_or_unreadable" in blockers:
                queue.append(
                    {
                        "kind": "case_memory_report",
                        "artifactId": artifact_id,
                        "artifactPath": row.get("path"),
                        "gateId": gate.get("gateId"),
                        "status": "MISSING_REPORT",
                        "priority": "HIGH",
                        "candidateReportPath": gate.get("candidateReportPath"),
                        "nextActionZh": (
                            "生成或修复 Case Memory candidate report；只允许读取 shadow/tester/replay 证据，不放开真实执行。"
                        ),
                        "acceptanceZh": "candidateReport 可读，candidateCount>0、gaSeedCount>0，且必需样本类型覆盖晋级门。",
                        "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
                        "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
                    }
                )
            for category in gate.get("missingCategories") if isinstance(gate.get("missingCategories"), list) else []:
                category_key = str(category)
                guidance = CATEGORY_GUIDANCE_ZH.get(category_key, {})
                collection_row = collection_rows.get(category_key, {})
                source_gap = (
                    collection_row.get("sourceGap")
                    if isinstance(collection_row.get("sourceGap"), dict)
                    else {}
                )
                evidence_gap = (
                    collection_row.get("evidenceGapZh")
                    or source_gap.get("evidenceGapZh")
                    or ""
                )
                queue.append(
                    {
                        "kind": "case_memory_category",
                        "artifactId": artifact_id,
                        "artifactPath": row.get("path"),
                        "gateId": gate.get("gateId"),
                        "category": category_key,
                        "status": "MISSING_CATEGORY",
                        "priority": guidance.get("priority", "HIGH"),
                        "observedCount": gate.get("categoryCounts", {}).get(category_key, 0)
                        if isinstance(gate.get("categoryCounts"), dict)
                        else 0,
                        "targetCount": guidance.get("targetCount"),
                        "source": guidance.get("source"),
                        "sourceArtifacts": list(guidance.get("sourceArtifacts", [])),
                        "collectionEndpoint": guidance.get("collectionEndpoint"),
                        "collectionCommand": (
                            collection_row.get("collectionCommand")
                            or guidance.get("collectionCommand")
                        ),
                        "prerequisiteCommand": (
                            collection_row.get("prerequisiteCommand")
                            or source_gap.get("prerequisiteCommand")
                            or ""
                        ),
                        "caseMemoryBuildCommand": (
                            collection_row.get("caseMemoryBuildCommand")
                            or guidance.get("caseMemoryBuildCommand")
                        ),
                        "verifyCommand": (
                            collection_row.get("verifyCommand")
                            or guidance.get("verifyCommand")
                        ),
                        "sourceGap": source_gap,
                        "sourceGapStatus": source_gap.get("status") or "",
                        "sourceGapArtifact": source_gap.get("sourceArtifact") or "",
                        "evidenceGapZh": evidence_gap,
                        "requiredOutcomeFields": (
                            list(source_gap.get("requiredOutcomeFields"))
                            if isinstance(source_gap.get("requiredOutcomeFields"), list)
                            else []
                        ),
                        "nextActionZh": (
                            collection_row.get("nextActionZh")
                            or source_gap.get("nextActionZh")
                            or guidance.get(
                                "nextActionZh",
                                f"补齐 Case Memory {category_key} 样本；只允许 shadow/tester/read-only 证据。",
                            )
                        ),
                        "acceptanceZh": guidance.get(
                            "acceptanceZh",
                            f"{category_key} 至少有 1 条可审计样本，并通过 Case Memory taxonomy gate。",
                        ),
                        "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
                        "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
                    }
                )
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "OK": 3}
    queue.sort(
        key=lambda item: (
            priority_order.get(str(item.get("priority") or "").upper(), 4),
            str(item.get("kind") or ""),
            str(item.get("timeframe") or item.get("category") or ""),
        )
    )
    return queue


def _promotion_blocker_priority(artifact_id: str, gate: Dict[str, Any]) -> str:
    if artifact_id in {
        "historyProductionStatus",
        "gaMultiGenerationStabilityReport",
        "caseMemoryArtifactManifest",
        "strategyParityReport",
    }:
        return "HIGH"
    if str(gate.get("status") or "").upper() == "BLOCKED":
        return "MEDIUM"
    return "LOW"


def _promotion_blocker_summary(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []
    for row in rows:
        artifact_id = str(row.get("artifactId") or "")
        gate = row.get("promotionGate")
        if not isinstance(gate, dict) or gate.get("passed") is True:
            continue
        blockers = [str(blocker) for blocker in gate.get("blockers", [])]
        item: Dict[str, Any] = {
            "artifactId": artifact_id,
            "artifactPath": row.get("path"),
            "category": row.get("category"),
            "gateId": gate.get("gateId"),
            "status": gate.get("status") or "BLOCKED",
            "priority": _promotion_blocker_priority(artifact_id, gate),
            "requiredFor": list(gate.get("requiredFor", []))
            if isinstance(gate.get("requiredFor"), list)
            else [],
            "blockerCount": len(blockers),
            "blockers": blockers,
            "nextActionZh": gate.get("nextActionZh") or "",
            "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
            "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
        }
        if artifact_id == "historyProductionStatus":
            item["staleTimeframes"] = (
                list(gate.get("staleTimeframes", []))
                if isinstance(gate.get("staleTimeframes"), list)
                else []
            )
            item["requiredTimeframes"] = (
                list(gate.get("requiredTimeframes", []))
                if isinstance(gate.get("requiredTimeframes"), list)
                else []
            )
            copyrates = (
                gate.get("copyRatesExportFreshness")
                if isinstance(gate.get("copyRatesExportFreshness"), dict)
                else {}
            )
            continuous_sync = (
                gate.get("continuousSync")
                if isinstance(gate.get("continuousSync"), dict)
                else {}
            )
            item["copyRatesExportFreshnessStatus"] = copyrates.get("status") or ""
            item["continuousSyncStatus"] = continuous_sync.get("status") or ""
            item["continuousSyncRunning"] = bool(continuous_sync.get("running"))
        elif artifact_id == "gaMultiGenerationStabilityReport":
            item["stabilityGrade"] = gate.get("stabilityGrade") or ""
            item["closureMode"] = gate.get("closureMode") or ""
            item["generationCount"] = gate.get("generationCount")
            item["eliteCount"] = gate.get("eliteCount")
        elif artifact_id == "caseMemoryArtifactManifest":
            item["missingCategories"] = (
                list(gate.get("missingCategories", []))
                if isinstance(gate.get("missingCategories"), list)
                else []
            )
            item["candidateCount"] = gate.get("candidateCount")
            item["gaSeedCount"] = gate.get("gaSeedCount")
        elif artifact_id == "strategyParityReport":
            item["reportStatus"] = gate.get("reportStatus") or ""
            item["promotionAllowed"] = bool(gate.get("promotionAllowed"))
        summary.append(item)
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    summary.sort(
        key=lambda item: (
            priority_order.get(str(item.get("priority") or "").upper(), 3),
            str(item.get("artifactId") or ""),
        )
    )
    return summary


def _bounded_list(value: Any, *, limit: int) -> List[Any]:
    if not isinstance(value, list):
        return []
    return value[: max(0, limit)]


def _summarize_recovery_row(row: Dict[str, Any]) -> Dict[str, Any]:
    compact_keys = (
        "kind",
        "artifactId",
        "category",
        "timeframe",
        "status",
        "priority",
        "stabilityGrade",
        "closureMode",
        "sourceGapStatus",
        "sourceGapArtifact",
        "copyRatesExportSchemaVersion",
        "copyRatesExportFreshnessStatus",
        "copyRatesExportGeneratedLagHours",
        "copyRatesExportLatestLagHours",
        "continuousSyncSchemaVersion",
        "continuousSyncStatus",
        "continuousSyncRunning",
        "continuousSyncMode",
        "continuousSyncScript",
        "continuousSyncStartupCommand",
        "continuousSyncOnceCommand",
        "continuousSyncLaunchdService",
        "continuousSyncMatchingProcessCount",
        "continuousSyncProbePermissionDenied",
        "continuousSyncHostProbeCommand",
        "continuousSyncNextActionZh",
        "continuousSyncAcceptanceZh",
        "continuousSyncAllowedLanes",
        "continuousSyncForbiddenSideEffects",
        "continuousSyncRequiresFreshCopyRatesExporter",
        "evidenceGapZh",
        "copyRatesExportNextActionZh",
        "nextActionZh",
        "acceptanceZh",
        "prerequisiteCommand",
        "refreshCommand",
        "collectionCommand",
        "caseMemoryBuildCommand",
        "verifyCommand",
        "allowedLanes",
        "forbiddenSideEffects",
    )
    return {key: row[key] for key in compact_keys if key in row and row[key] is not None}


def build_core_evidence_summary(
    payload: Dict[str, Any],
    *,
    queue_limit: int = DEFAULT_SUMMARY_QUEUE_LIMIT,
    blocker_limit: int = DEFAULT_SUMMARY_BLOCKER_LIMIT,
) -> Dict[str, Any]:
    blockers = _bounded_list(payload.get("blockers"), limit=blocker_limit)
    promotion_blockers = _bounded_list(payload.get("promotionBlockers"), limit=blocker_limit)
    promotion_blocker_summary = _bounded_list(payload.get("promotionBlockerSummary"), limit=blocker_limit)
    recovery_queue = _bounded_list(payload.get("promotionRecoveryQueue"), limit=queue_limit)
    blocker_count = int(payload.get("blockerCount") or 0)
    promotion_blocker_count = int(payload.get("promotionBlockerCount") or 0)
    promotion_blocker_summary_count = int(payload.get("promotionBlockerSummaryCount") or 0)
    recovery_queue_count = int(payload.get("promotionRecoveryQueueCount") or 0)
    return {
        "schema": SUMMARY_SCHEMA,
        "schemaVersion": SUMMARY_SCHEMA_VERSION,
        "generatedAt": payload.get("generatedAt"),
        "status": payload.get("status"),
        "statusZh": payload.get("statusZh"),
        "ok": bool(payload.get("ok")),
        "artifactCount": payload.get("artifactCount"),
        "presentArtifactCount": payload.get("presentArtifactCount"),
        "blockerCount": blocker_count,
        "blockers": blockers,
        "blockerOverflowCount": max(0, blocker_count - len(blockers)),
        "promotionGateStatus": payload.get("promotionGateStatus"),
        "promotionGatePassed": bool(payload.get("promotionGatePassed")),
        "promotionBlockerCount": promotion_blocker_count,
        "promotionBlockers": promotion_blockers,
        "promotionBlockerOverflowCount": max(0, promotion_blocker_count - len(promotion_blockers)),
        "promotionBlockerSummaryCount": promotion_blocker_summary_count,
        "promotionBlockerSummary": promotion_blocker_summary,
        "promotionBlockerSummaryOverflowCount": max(
            0, promotion_blocker_summary_count - len(promotion_blocker_summary)
        ),
        "promotionRecoveryQueueCount": recovery_queue_count,
        "promotionRecoveryQueue": [
            _summarize_recovery_row(row) for row in recovery_queue if isinstance(row, dict)
        ],
        "promotionRecoveryQueueOverflowCount": max(0, recovery_queue_count - len(recovery_queue)),
        "jsonArtifactCount": payload.get("jsonArtifactCount"),
        "jsonDeclaredVersionCount": payload.get("jsonDeclaredVersionCount"),
        "versionCoverageStatus": payload.get("versionCoverageStatus"),
        "versionCoverageRatio": payload.get("versionCoverageRatio"),
        "versionMissingArtifacts": _bounded_list(payload.get("versionMissingArtifacts"), limit=blocker_limit),
        "declaredVersionRequiredCount": payload.get("declaredVersionRequiredCount"),
        "declaredVersionRequiredMissingCount": payload.get("declaredVersionRequiredMissingCount"),
        "declaredVersionRequiredStatus": payload.get("declaredVersionRequiredStatus"),
        "declaredVersionRequiredMissingArtifacts": _bounded_list(
            payload.get("declaredVersionRequiredMissingArtifacts"),
            limit=blocker_limit,
        ),
        "nextActionZh": payload.get("nextActionZh"),
        "safety": dict(payload.get("safety") or {}),
    }


def build_core_evidence_manifest(runtime_dir: Path, *, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    rows = [_artifact_row(runtime_dir, spec) for spec in CORE_ARTIFACTS]
    json_rows = [
        row for row in rows if row.get("exists") and row.get("contentType") in {"json", "jsonl"}
    ]
    json_declared_version_rows = [
        row for row in json_rows if row.get("declaredVersionPresent") is True
    ]
    version_missing_artifacts = [
        str(row.get("artifactId") or "") for row in json_rows if row.get("declaredVersionPresent") is not True
    ]
    required_version_rows = [
        row for row in json_rows if row.get("requiresDeclaredVersion") is True
    ]
    required_version_missing_artifacts = [
        str(row.get("artifactId") or "")
        for row in required_version_rows
        if row.get("declaredVersionPresent") is not True
    ]
    blockers = [
        f"{row['artifactId']}:{blocker}"
        for row in rows
        for blocker in row.get("blockers", [])
    ]
    promotion_blockers = [
        f"{row['artifactId']}:{blocker}"
        for row in rows
        for blocker in row.get("promotionGate", {}).get("blockers", [])
    ]
    status = "PASS" if not blockers else "FAIL"
    promotion_gate_passed = not promotion_blockers
    promotion_blocker_summary = _promotion_blocker_summary(rows)
    promotion_recovery_queue = _promotion_recovery_queue(rows)
    payload: Dict[str, Any] = {
        "ok": status == "PASS",
        "schema": REPORT_SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": status,
        "statusZh": "核心运行证据完整" if status == "PASS" else "核心运行证据完整性失败",
        "hashAlgorithm": "sha256",
        "runtimeRoot": ".",
        "artifactCount": len(rows),
        "presentArtifactCount": sum(1 for row in rows if row.get("exists")),
        "jsonArtifactCount": len(json_rows),
        "jsonDeclaredVersionCount": len(json_declared_version_rows),
        "versionCoverageRatio": (
            round(len(json_declared_version_rows) / len(json_rows), 4)
            if json_rows
            else 1.0
        ),
        "versionCoverageStatus": "PASS" if not version_missing_artifacts else "PARTIAL",
        "versionMissingArtifacts": version_missing_artifacts,
        "declaredVersionRequiredCount": len(required_version_rows),
        "declaredVersionRequiredMissingCount": len(required_version_missing_artifacts),
        "declaredVersionRequiredStatus": (
            "PASS" if not required_version_missing_artifacts else "FAIL"
        ),
        "declaredVersionRequiredMissingArtifacts": required_version_missing_artifacts,
        "blockerCount": len(blockers),
        "blockers": blockers,
        "promotionGatePassed": promotion_gate_passed,
        "promotionGateStatus": "PASS" if promotion_gate_passed else "BLOCKED",
        "promotionBlockerCount": len(promotion_blockers),
        "promotionBlockers": promotion_blockers,
        "promotionBlockerSummaryCount": len(promotion_blocker_summary),
        "promotionBlockerSummary": promotion_blocker_summary,
        "promotionRecoveryQueueCount": len(promotion_recovery_queue),
        "promotionRecoveryQueue": promotion_recovery_queue,
        "promotionScope": ["ga_promotion", "champion_promotion"],
        "artifacts": rows,
        "safety": dict(SAFETY),
        "nextActionZh": (
            "先修复缺失证据、schema 漂移、旧仓绝对路径或 artifact hash 缺口，再允许进入晋级评审。"
            if status != "PASS"
            else (
                "核心证据文件完整，但 history freshness、Case Memory 样本类型或其他 promotion gate 仍阻断 GA/champion 晋级；按 promotionRecoveryQueue 逐项修复。"
                if not promotion_gate_passed
                else "继续把 live-loop、production policy、GA、execution feedback 和 case memory 证据纳入晋级门。"
            )
        ),
    }
    if write:
        _write_json(manifest_path(runtime_dir), payload)
    return payload
