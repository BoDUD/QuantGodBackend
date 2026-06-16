from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from tools.case_memory.taxonomy import (
        CATEGORY_GUIDANCE_ZH,
        REQUIRED_CASE_MEMORY_CATEGORIES,
        case_memory_category_counts,
        case_memory_tokens_from_report,
    )
except ModuleNotFoundError:  # pragma: no cover
    from case_memory.taxonomy import (
        CATEGORY_GUIDANCE_ZH,
        REQUIRED_CASE_MEMORY_CATEGORIES,
        case_memory_category_counts,
        case_memory_tokens_from_report,
    )

from .schema import CORE_ARTIFACTS, REPORT_SCHEMA, SAFETY, SCHEMA_VERSION, manifest_path


LEGACY_ABSOLUTE_PATH_RE = re.compile(r"/Users/[^\n\r\t\"']*/Quard/QuantGod(?:/|\b)")
REQUIRED_HISTORY_TIMEFRAMES = ("M1", "M5", "M15", "H1")
EVIDENCE_RECOVERY_ALLOWED_LANES = ["READ_ONLY_RESEARCH", "SHADOW", "TESTER_ONLY"]
EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS = [
    "ORDER_SEND",
    "POSITION_CLOSE",
    "LIVE_PRESET_MUTATION",
    "MT5_REQUEST_WRITE",
    "WALLET_AUTHORIZATION",
]


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
        "copyRatesExportFreshnessStatus": copyrates_freshness.get("status"),
        "copyRatesExportStale": bool(copyrates_freshness.get("stale")),
        "copyRatesExportGeneratedAtServer": copyrates_freshness.get("generatedAtServer") or "",
        "copyRatesExportGeneratedLagHours": copyrates_freshness.get("generatedLagHours"),
        "copyRatesExportLatestLagHours": lag_by_timeframe.get(timeframe),
        "copyRatesExportStaleTimeframes": list(stale_timeframes),
        "copyRatesExportNextActionZh": copyrates_freshness.get("nextActionZh") or "",
    }


def _history_recovery_queue(
    rows: Dict[str, Dict[str, Any]],
    copyrates_freshness: Dict[str, Any] | None = None,
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

    passed = not blockers
    copyrates_freshness = (
        payload.get("copyRatesExportFreshness")
        if isinstance(payload.get("copyRatesExportFreshness"), dict)
        else {}
    )
    recovery_queue = _history_recovery_queue(rows, copyrates_freshness)
    stale_timeframes = [timeframe for timeframe, row in rows.items() if not row.get("freshnessOk")]
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


def _case_memory_promotion_gate(runtime_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    blockers: List[str] = []
    report_path = _candidate_report_path(runtime_dir, manifest)
    report = _read_json(report_path)
    if not report:
        blockers.append("candidate_report_missing_or_unreadable")
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
        "blockers": blockers,
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
    blockers: List[str] = []
    payload: Dict[str, Any] = {}
    declared_schema = ""
    declared_version: Any = ""
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
            "headers": [],
            "status": _row_status(blockers),
            "blockers": blockers,
        }

    size_bytes = path.stat().st_size
    file_hash = _sha256(path)
    if content_type in {"json", "jsonl"}:
        declared_schema, declared_version, payload = _declared_json_schema(path, content_type)
        if not declared_schema:
            blockers.append("missing_declared_schema")
        elif expected_schemas and declared_schema not in expected_schemas:
            blockers.append("schema_mismatch")
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
                        "copyRatesExportStale": item.get("copyRatesExportStale"),
                        "copyRatesExportGeneratedAtServer": item.get("copyRatesExportGeneratedAtServer"),
                        "copyRatesExportGeneratedLagHours": item.get("copyRatesExportGeneratedLagHours"),
                        "copyRatesExportLatestLagHours": item.get("copyRatesExportLatestLagHours"),
                        "copyRatesExportStaleTimeframes": item.get("copyRatesExportStaleTimeframes"),
                        "copyRatesExportNextActionZh": item.get("copyRatesExportNextActionZh"),
                        "refreshCommand": item.get("refreshCommand"),
                        "verifyCommand": item.get("verifyCommand"),
                        "nextActionZh": item.get("nextActionZh"),
                        "acceptanceZh": item.get("acceptanceZh"),
                        "allowedLanes": list(EVIDENCE_RECOVERY_ALLOWED_LANES),
                        "forbiddenSideEffects": list(EVIDENCE_RECOVERY_FORBIDDEN_SIDE_EFFECTS),
                    }
                )
            continue

        if artifact_id == "caseMemoryArtifactManifest":
            blockers = [str(blocker) for blocker in gate.get("blockers", [])]
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
                        "nextActionZh": guidance.get(
                            "nextActionZh",
                            f"补齐 Case Memory {category_key} 样本；只允许 shadow/tester/read-only 证据。",
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


def build_core_evidence_manifest(runtime_dir: Path, *, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    rows = [_artifact_row(runtime_dir, spec) for spec in CORE_ARTIFACTS]
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
        "blockerCount": len(blockers),
        "blockers": blockers,
        "promotionGatePassed": promotion_gate_passed,
        "promotionGateStatus": "PASS" if promotion_gate_passed else "BLOCKED",
        "promotionBlockerCount": len(promotion_blockers),
        "promotionBlockers": promotion_blockers,
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
