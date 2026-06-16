from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

from .builder import build_case_memory_candidates
from .io_utils import append_jsonl_unique, load_json, read_jsonl, utc_now_iso, write_json
from .long_term_memory import build_long_term_trade_memory
from .schema import (
    AGENT_VERSION,
    CASE_MEMORY_SOURCES,
    FOCUS_SYMBOL,
    SAFETY,
    SCHEMA_ARTIFACT_MANIFEST,
    SCHEMA_REPORT,
    artifact_manifest_path,
    candidate_ledger_path,
    report_path,
)
from .taxonomy import build_case_memory_coverage_plan


def _relative_artifact_path(runtime_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(runtime_dir).resolve()).as_posix()
    except ValueError:
        return path.name


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_specs(runtime_dir: Path) -> list[tuple[str, Path, str]]:
    return [
        ("candidateReport", report_path(runtime_dir), SCHEMA_REPORT),
        ("candidateLedger", candidate_ledger_path(runtime_dir), "quantgod.case_memory_strategy_candidate_ledger.v1"),
    ]


def _artifact_manifest(runtime_dir: Path, created_at: str) -> Dict[str, Any]:
    rows: list[Dict[str, Any]] = []
    for artifact_id, path, schema in _artifact_specs(runtime_dir):
        exists = path.exists()
        rows.append(
            {
                "artifactId": artifact_id,
                "schema": schema,
                "path": _relative_artifact_path(runtime_dir, path),
                "exists": exists,
                "sizeBytes": path.stat().st_size if exists else 0,
                "sha256": _file_sha256(path) if exists else "",
            }
        )
    return {
        "ok": True,
        "schema": SCHEMA_ARTIFACT_MANIFEST,
        "schemaVersion": 1,
        "createdAt": created_at,
        "artifactCount": len(rows),
        "artifacts": rows,
        "safety": dict(SAFETY),
    }


def _artifact_manifest_summary(
    runtime_dir: Path,
    manifest: Dict[str, Any] | None = None,
    *,
    present: bool | None = None,
) -> Dict[str, Any]:
    path = artifact_manifest_path(runtime_dir)
    artifact_count = int((manifest or {}).get("artifactCount") or len(_artifact_specs(runtime_dir)))
    return {
        "schema": SCHEMA_ARTIFACT_MANIFEST,
        "schemaVersion": 1,
        "path": _relative_artifact_path(runtime_dir, path),
        "present": path.exists() if present is None else present,
        "artifactCount": artifact_count,
        "hashAlgorithm": "sha256",
    }


def _candidate_ledger_summary(runtime_dir: Path) -> Dict[str, Any]:
    rows = read_jsonl(candidate_ledger_path(runtime_dir))
    case_type_counts: Dict[str, int] = {}
    for row in rows:
        case_type = str(row.get("caseType") or row.get("type") or "").strip()
        if not case_type:
            continue
        case_type_counts[case_type] = case_type_counts.get(case_type, 0) + 1
    return {
        "schema": "quantgod.case_memory_candidate_ledger_summary.v1",
        "path": _relative_artifact_path(runtime_dir, candidate_ledger_path(runtime_dir)),
        "present": candidate_ledger_path(runtime_dir).exists(),
        "rowCount": len(rows),
        "caseTypeCounts": case_type_counts,
    }


def build_case_memory_report(
    runtime_dir: Path,
    *,
    write: bool = True,
    limit: int = 8,
) -> Dict[str, Any]:
    payload = build_case_memory_candidates(runtime_dir, write_case_memory=write, limit=limit)
    long_term_memory = build_long_term_trade_memory(runtime_dir)
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    ga_seeds = payload.get("gaSeeds") if isinstance(payload.get("gaSeeds"), list) else []
    created_at = utc_now_iso()
    report: Dict[str, Any] = {
        "ok": payload.get("status") != "BLOCKED_BY_PARITY",
        "schema": SCHEMA_REPORT,
        "agentVersion": AGENT_VERSION,
        "createdAt": created_at,
        "symbol": FOCUS_SYMBOL,
        "status": payload.get("status"),
        "caseSummary": payload.get("caseSummary") or {},
        "candidateCount": len(candidates),
        "gaSeedCount": len(ga_seeds),
        "candidates": candidates,
        "gaSeeds": ga_seeds,
        "candidateLedgerSummary": _candidate_ledger_summary(runtime_dir),
        "longTermTradeMemory": long_term_memory,
        "parityGate": payload.get("parityGate") or {},
        "sources": CASE_MEMORY_SOURCES,
        "artifactManifest": _artifact_manifest_summary(runtime_dir, present=write),
        "reasonZh": payload.get("reasonZh") or "",
        "safety": dict(SAFETY),
    }
    report["coveragePlan"] = build_case_memory_coverage_plan(report)
    report["nextActionZh"] = _next_action(payload, report["coveragePlan"])
    if write:
        write_json(report_path(runtime_dir), report)
        if candidates:
            append_jsonl_unique(candidate_ledger_path(runtime_dir), candidates, "candidateId")
        write_json(artifact_manifest_path(runtime_dir), _artifact_manifest(runtime_dir, created_at))
    return report


def status(runtime_dir: Path) -> Dict[str, Any]:
    payload = load_json(report_path(runtime_dir))
    if payload:
        payload["candidateLedgerSummary"] = _candidate_ledger_summary(runtime_dir)
        payload["coveragePlan"] = build_case_memory_coverage_plan(payload)
        return {"ok": True, **payload}
    return {
        "ok": True,
        "schema": SCHEMA_REPORT,
        "agentVersion": AGENT_VERSION,
        "symbol": FOCUS_SYMBOL,
        "status": "WAITING_FIRST_RUN",
        "candidateCount": 0,
        "gaSeedCount": 0,
        "coveragePlan": build_case_memory_coverage_plan({}),
        "artifactManifest": _artifact_manifest_summary(runtime_dir),
        "reasonZh": "等待 Case Memory 生成 Strategy JSON candidate。",
        "safety": dict(SAFETY),
    }


def _next_action(payload: Dict[str, Any], coverage_plan: Dict[str, Any] | None = None) -> str:
    if payload.get("status") == "BLOCKED_BY_PARITY":
        return "先修复 Strategy / Replay / EA parity，再生成 Strategy JSON candidate。"
    if isinstance(coverage_plan, dict) and coverage_plan.get("status") == "BLOCKED":
        missing = coverage_plan.get("missingCategories") if isinstance(coverage_plan.get("missingCategories"), list) else []
        if missing:
            return f"继续补齐 Case Memory 样本类型：{' / '.join(str(item) for item in missing)}；只允许 shadow/tester 证据。"
    if payload.get("gaSeeds"):
        return "下一轮 GA population 应纳入这些 CASE_MEMORY shadow seeds。"
    return "等待 replay、执行反馈或 GA blocker 产生可转写的 Case Memory。"
