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


def _replay_variant_metrics(path: Path) -> list[Dict[str, Any]]:
    payload = load_json(path)
    variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
    rows: list[Dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        metrics = variant.get("metrics") if isinstance(variant.get("metrics"), dict) else variant
        rows.append(
            {
                "name": variant.get("name") or variant.get("variant") or "",
                "sampleCount": metrics.get("sampleCount"),
                "scoredSampleCount": metrics.get("scoredSampleCount"),
                "unresolvedSampleCount": metrics.get("unresolvedSampleCount"),
                "entryCountDelta": metrics.get("entryCountDelta"),
                "netRDelta": metrics.get("netRDelta"),
                "profitCaptureRatio": metrics.get("profitCaptureRatio"),
                "evidenceQuality": metrics.get("evidenceQuality"),
                "recommendation": metrics.get("recommendation"),
                "softNewsOpportunityR": metrics.get("softNewsOpportunityR"),
                "hardNewsAvoidedLossR": metrics.get("hardNewsAvoidedLossR"),
                "maxAdverseRDelta": metrics.get("maxAdverseRDelta"),
            }
        )
    return rows


def _num(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _case_memory_source_gaps(runtime_dir: Path) -> Dict[str, Any]:
    entry_path = runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYEntryVariantComparison.json"
    exit_path = runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYExitVariantComparison.json"
    news_path = runtime_dir / "replay" / "usdjpy" / "QuantGod_USDJPYNewsGateReplayReport.json"
    entry_variants = _replay_variant_metrics(entry_path)
    exit_variants = _replay_variant_metrics(exit_path)
    news_variants = _replay_variant_metrics(news_path)

    entry_sample_count = max((_num(row.get("sampleCount")) for row in entry_variants), default=0.0)
    entry_scored_count = max((_num(row.get("scoredSampleCount")) for row in entry_variants), default=0.0)
    entry_unresolved_count = max((_num(row.get("unresolvedSampleCount")) for row in entry_variants), default=0.0)
    entry_delta = max((_num(row.get("entryCountDelta")) for row in entry_variants), default=0.0)
    entry_net_delta = max((_num(row.get("netRDelta")) for row in entry_variants), default=0.0)

    exit_sample_count = max((_num(row.get("sampleCount")) for row in exit_variants), default=0.0)
    exit_scored_count = max((_num(row.get("scoredSampleCount")) for row in exit_variants), default=0.0)
    exit_capture = max((_num(row.get("profitCaptureRatio")) for row in exit_variants), default=0.0)
    exit_net_delta = max((_num(row.get("netRDelta")) for row in exit_variants), default=0.0)

    news_entry_delta = max((_num(row.get("entryCountDelta")) for row in news_variants), default=0.0)
    news_net_delta = max((_num(row.get("netRDelta")) for row in news_variants), default=0.0)
    news_soft_r = max((_num(row.get("softNewsOpportunityR")) for row in news_variants), default=0.0)
    news_adverse = min((_num(row.get("maxAdverseRDelta")) for row in news_variants), default=0.0)

    entry_gap = (
        "entry replay 有样本但缺少 scored posterior R，不能证明错失机会。"
        if entry_sample_count > 0 and entry_scored_count <= 0 and entry_unresolved_count > 0
        else "entry replay 暂无新增机会 delta。"
    )
    if entry_delta > 0 or entry_net_delta > 0:
        entry_gap = "entry replay 已出现机会 delta，可转写 missed-opportunity 样本。"

    exit_gap = (
        "exit replay 0 样本，不能证明早出场或盈利捕获不足。"
        if exit_sample_count <= 0
        else "exit replay 尚未显示 let-profit-run 改善。"
    )
    if exit_capture > 0.35 or exit_net_delta > 0:
        exit_gap = "exit replay 已出现盈利捕获改善，可转写 early-exit 样本。"

    news_gap = "news gate replay 未发现普通新闻导致的损伤或错失机会。"
    if news_entry_delta > 0 or news_net_delta > 0 or news_soft_r > 0 or news_adverse < 0:
        news_gap = "news replay 已出现新闻门禁损伤/机会 delta，可转写 news-damage 样本。"

    return {
        "schema": "quantgod.case_memory_source_evidence_gaps.v1",
        "MISSED_OPPORTUNITY": {
            "sourceArtifact": _relative_artifact_path(runtime_dir, entry_path),
            "sampleCount": int(entry_sample_count),
            "scoredSampleCount": int(entry_scored_count),
            "unresolvedSampleCount": int(entry_unresolved_count),
            "entryCountDelta": entry_delta,
            "netRDelta": entry_net_delta,
            "status": "BLOCKED_BY_REPLAY_SCORING_GAP" if entry_scored_count <= 0 and entry_sample_count > 0 else "WAITING_SIGNAL_DELTA",
            "evidenceGapZh": entry_gap,
        },
        "EARLY_EXIT": {
            "sourceArtifact": _relative_artifact_path(runtime_dir, exit_path),
            "sampleCount": int(exit_sample_count),
            "scoredSampleCount": int(exit_scored_count),
            "profitCaptureRatio": exit_capture,
            "netRDelta": exit_net_delta,
            "status": "WAITING_EXIT_REPLAY_SAMPLES" if exit_sample_count <= 0 else "WAITING_EXIT_IMPROVEMENT",
            "evidenceGapZh": exit_gap,
        },
        "NEWS_DAMAGE": {
            "sourceArtifact": _relative_artifact_path(runtime_dir, news_path),
            "variantCount": len(news_variants),
            "entryCountDelta": news_entry_delta,
            "netRDelta": news_net_delta,
            "softNewsOpportunityR": news_soft_r,
            "maxAdverseRDelta": news_adverse,
            "status": "WAITING_NEWS_DAMAGE_DELTA",
            "evidenceGapZh": news_gap,
        },
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
        "sourceEvidenceGaps": _case_memory_source_gaps(runtime_dir),
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
        payload["sourceEvidenceGaps"] = _case_memory_source_gaps(runtime_dir)
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
