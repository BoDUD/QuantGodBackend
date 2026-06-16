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
        REQUIRED_CASE_MEMORY_CATEGORIES,
        case_memory_category_counts,
        case_memory_tokens_from_report,
    )
except ModuleNotFoundError:  # pragma: no cover
    from case_memory.taxonomy import (
        REQUIRED_CASE_MEMORY_CATEGORIES,
        case_memory_category_counts,
        case_memory_tokens_from_report,
    )

from .schema import CORE_ARTIFACTS, REPORT_SCHEMA, SAFETY, SCHEMA_VERSION, manifest_path


LEGACY_ABSOLUTE_PATH_RE = re.compile(r"/Users/[^\n\r\t\"']*/Quard/QuantGod(?:/|\b)")
REQUIRED_HISTORY_TIMEFRAMES = ("M1", "M5", "M15", "H1")


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
    return {
        "gateId": "history_freshness_promotion_gate",
        "requiredFor": ["ga_promotion", "champion_promotion"],
        "requiredTimeframes": list(REQUIRED_HISTORY_TIMEFRAMES),
        "passed": passed,
        "status": "PASS" if passed else "BLOCKED",
        "statusZh": "历史数据可作为晋级前置证据" if passed else "历史数据 freshness/覆盖未通过，禁止晋级",
        "blockers": blockers,
        "timeframes": rows,
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
        "promotionScope": ["ga_promotion", "champion_promotion"],
        "artifacts": rows,
        "safety": dict(SAFETY),
        "nextActionZh": (
            "先修复缺失证据、schema 漂移、旧仓绝对路径或 artifact hash 缺口，再允许进入晋级评审。"
            if status != "PASS"
            else (
                "核心证据文件完整，但 history freshness、Case Memory 样本类型或其他 promotion gate 仍阻断 GA/champion 晋级。"
                if not promotion_gate_passed
                else "继续把 live-loop、production policy、GA、execution feedback 和 case memory 证据纳入晋级门。"
            )
        ),
    }
    if write:
        _write_json(manifest_path(runtime_dir), payload)
    return payload
