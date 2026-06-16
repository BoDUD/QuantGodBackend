from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution_feedback_audit import audit_execution_feedback
from .ga_audit import audit_ga
from .history_audit import audit_history
from .io_utils import ensure_dir, write_json
from .parity_audit import audit_parity
from .rsi_lineage_closure import build_rsi_lineage_closure, write_rsi_lineage_closure
from .schema import (
    EXECUTION_FEEDBACK_COVERAGE,
    GA_STABILITY_REPORT,
    LATEST_REPORT,
    OUTPUT_DIR,
    REPORT_SCHEMA,
    RSI_LINEAGE_CLOSURE_REPORT,
    SAFETY,
    STRATEGY_FAMILY_PARITY,
)

try:
    from case_memory.report import status as case_memory_status
except ImportError:  # pragma: no cover - used when imported as tools.* in tests
    from tools.case_memory.report import status as case_memory_status

try:
    from runtime_evidence_integrity.report import build_core_evidence_manifest
    from runtime_evidence_integrity.schema import manifest_path as core_evidence_manifest_path
except ImportError:  # pragma: no cover - used when imported as tools.* in tests
    from tools.runtime_evidence_integrity.report import build_core_evidence_manifest
    from tools.runtime_evidence_integrity.schema import manifest_path as core_evidence_manifest_path


def _overall_status(sections: list[dict[str, Any]]) -> str:
    states = {str(section.get("status") or "UNKNOWN").upper() for section in sections}
    if "FAIL" in states:
        return "FAIL"
    if "BLOCKED" in states:
        return "WARN"
    if "WARN" in states or "UNKNOWN" in states:
        return "WARN"
    return "PASS"


def _next_actions(
    history: dict[str, Any],
    parity: dict[str, Any],
    execution_feedback: dict[str, Any],
    ga: dict[str, Any],
    rsi_lineage: dict[str, Any],
    runtime_integrity: dict[str, Any],
    case_memory: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if runtime_integrity.get("status") != "PASS":
        actions.append("先修复核心 runtime evidence integrity：缺失文件、schema/hash 漂移或旧仓路径都会阻断晋级")
    if parity.get("failCount"):
        actions.append("优先修复 PARITY_FAIL，相关策略不得晋级")
    elif parity.get("missingCount"):
        actions.append("补齐缺失 strategy family parity 覆盖")
    elif parity.get("shadowResearchOnlyCount"):
        actions.append("持续观察 shadow-only 策略族的 EA 影子评估证据")
    thresholds = execution_feedback.get("thresholds") or {}
    if execution_feedback.get("sampleCount", 0) < thresholds.get("minProductionSamples", 20):
        actions.append("继续收集 live/shadow execution feedback，直到样本达到生产观察阈值")
    if execution_feedback.get("fieldCoverage", 0) < thresholds.get("minFieldCoverage", 0.8):
        actions.append("补齐 execution feedback 缺失字段，避免 Case Memory / GA fitness 误判")
    if ga.get("status") != "PASS":
        actions.append("连续观察 GA 多代 elite / graveyard / lineage 稳定性")
    if rsi_lineage.get("status") != "PASS":
        actions.append("冻结并复核 guarded RSI elite lineage，再判断 tester-only shadow promotion")
    if history.get("status") != "PASS":
        actions.append("确认 USDJPY 历史数据同步长期 PASS")
    if case_memory.get("status") != "PASS":
        actions.append(case_memory.get("nextActionZh") or "继续补齐 Case Memory 样本类型覆盖，只允许 shadow/tester 证据")
    if not actions:
        actions.append("生产证据可进入持续观察")
    return actions


def _case_memory_coverage(runtime_dir: Path) -> dict[str, Any]:
    payload = case_memory_status(runtime_dir)
    coverage = payload.get("coveragePlan") if isinstance(payload.get("coveragePlan"), dict) else {}
    missing = coverage.get("missingCategories") if isinstance(coverage.get("missingCategories"), list) else []
    rows = coverage.get("rows") if isinstance(coverage.get("rows"), list) else []
    coverage_status = str(coverage.get("status") or "UNKNOWN").upper()
    status = "PASS" if coverage_status == "PASS" else "BLOCKED"
    return {
        "schema": "quantgod.production_evidence_case_memory_coverage.v1",
        "status": status,
        "statusZh": coverage.get("statusZh")
        or ("Case Memory 样本类型已覆盖晋级门" if status == "PASS" else "Case Memory 样本类型不足，禁止晋级"),
        "candidateStatus": payload.get("status") or "",
        "candidateCount": payload.get("candidateCount") or 0,
        "gaSeedCount": payload.get("gaSeedCount") or 0,
        "coveragePlan": coverage,
        "requiredCategories": coverage.get("requiredCategories") or [],
        "categoryCounts": coverage.get("categoryCounts") or {},
        "missingCategories": missing,
        "coveredCategoryCount": coverage.get("coveredCategoryCount") or 0,
        "requiredCategoryCount": coverage.get("requiredCategoryCount") or len(coverage.get("requiredCategories") or []),
        "coverageRatio": coverage.get("coverageRatio") or 0,
        "blockersZh": [f"Case Memory 缺少 {category} 样本" for category in missing],
        "rows": rows,
        "nextActionZh": payload.get("nextActionZh")
        or coverage.get("nextActionZh")
        or "按缺失分类补充 shadow/tester 证据，不放开真实执行。",
        "safety": payload.get("safety") or SAFETY,
    }


def build_report(runtime_dir: Path) -> dict[str, Any]:
    runtime_integrity = build_core_evidence_manifest(runtime_dir, write=False)
    history = audit_history(runtime_dir)
    parity = audit_parity(runtime_dir)
    execution_feedback = audit_execution_feedback(runtime_dir)
    ga = audit_ga(runtime_dir)
    case_memory = _case_memory_coverage(runtime_dir)
    rsi_lineage = build_rsi_lineage_closure(
        runtime_dir,
        production_sections={
            "overall": {"status": "PASS"},
            "history": history,
            "parity": parity,
            "executionFeedback": execution_feedback,
            "ga": ga,
            "caseMemory": case_memory,
            "runtimeIntegrity": runtime_integrity,
        },
        write=False,
    )
    sections = [runtime_integrity, history, parity, execution_feedback, ga, case_memory, rsi_lineage]
    status = _overall_status(sections)
    blockers = []
    if runtime_integrity.get("status") != "PASS":
        blockers.append("核心运行证据 integrity 未通过")
    if parity.get("failCount"):
        blockers.append("存在 PARITY_FAIL，相关策略不得晋级")
    thresholds = execution_feedback.get("thresholds") or {}
    if execution_feedback.get("sampleCount", 0) < thresholds.get("minUsableSamples", 5):
        blockers.append("真实/影子执行反馈样本不足")
    if execution_feedback.get("coreCoverage", 0) < thresholds.get("minCoreCoverage", 0.95):
        blockers.append("执行反馈核心字段覆盖率不足")
    if history.get("status") != "PASS":
        blockers.append("USDJPY 历史数据覆盖或 freshness 未通过")
    if ga.get("status") != "PASS":
        blockers.append("GA 多代稳定性证据不足")
    if case_memory.get("status") != "PASS":
        blockers.append("Case Memory 样本类型覆盖不足")
    if rsi_lineage.get("status") != "PASS":
        blockers.append("RSI guarded elite lineage 尚未完成冻结/复核")
    return {
        "schema": REPORT_SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summaryZh": "生产证据可用" if status == "PASS" else "生产证据仍需补强",
        "blockersZh": blockers,
        "historyProduction": history,
        "coreRuntimeEvidenceIntegrity": runtime_integrity,
        "strategyFamilyParity": parity,
        "liveExecutionFeedbackCoverage": execution_feedback,
        "gaMultiGenerationStability": ga,
        "caseMemoryCoverage": case_memory,
        "rsiStabilityLineageClosure": rsi_lineage,
        "safety": SAFETY,
        "nextActionsZh": _next_actions(
            history,
            parity,
            execution_feedback,
            ga,
            rsi_lineage,
            runtime_integrity,
            case_memory,
        ),
    }


def write_reports(runtime_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    out_dir = ensure_dir(runtime_dir / OUTPUT_DIR)
    paths = {
        "latest": str(out_dir / LATEST_REPORT),
        "parityMatrix": str(out_dir / STRATEGY_FAMILY_PARITY),
        "executionFeedbackCoverage": str(out_dir / EXECUTION_FEEDBACK_COVERAGE),
        "gaStability": str(out_dir / GA_STABILITY_REPORT),
        "rsiLineageClosure": str(out_dir / RSI_LINEAGE_CLOSURE_REPORT),
        "coreRuntimeEvidenceManifest": str(core_evidence_manifest_path(runtime_dir)),
    }
    write_json(Path(paths["latest"]), report)
    write_json(Path(paths["coreRuntimeEvidenceManifest"]), report.get("coreRuntimeEvidenceIntegrity") or {})
    write_json(Path(paths["parityMatrix"]), report.get("strategyFamilyParity") or {})
    write_json(Path(paths["executionFeedbackCoverage"]), report.get("liveExecutionFeedbackCoverage") or {})
    write_json(Path(paths["gaStability"]), report.get("gaMultiGenerationStability") or {})
    paths.update(write_rsi_lineage_closure(runtime_dir, report.get("rsiStabilityLineageClosure") or {}))
    return paths


def load_latest(runtime_dir: Path) -> dict[str, Any] | None:
    from .io_utils import read_json
    return read_json(runtime_dir / OUTPUT_DIR / LATEST_REPORT, None)
