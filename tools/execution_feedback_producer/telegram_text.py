from __future__ import annotations

from typing import Any


def build_telegram_text(report: dict[str, Any]) -> str:
    lines = ["【QuantGod 执行反馈样本生产器】"]
    lines.append(f"状态：{report.get('status', 'UNKNOWN')}")
    lines.append(f"总结：{report.get('summaryZh', '')}")
    lines.append(f"样本数：{report.get('sampleCount', 0)}")
    lines.append(f"完整样本：{report.get('completeSampleCount', 0)}")
    lines.append(f"本轮新增：{report.get('generatedCount', 0)}")
    coverage = report.get("entryContextCoverage") if isinstance(report.get("entryContextCoverage"), dict) else {}
    source_audit = report.get("entryContextSourceAudit") if isinstance(report.get("entryContextSourceAudit"), dict) else {}
    if coverage:
        lines.append(
            "entryContext："
            f"nested={coverage.get('overallNestedCoverageRatio', 0)} "
            f"proxy={coverage.get('proxyContextRatio', 0)} "
            f"status={coverage.get('status', 'UNKNOWN')}"
        )
    if source_audit:
        lines.append(
            "raw审计："
            f"raw={source_audit.get('rawContextRatio', 0)} "
            f"limited={source_audit.get('contextLimitedRatio', 0)} "
            f"status={source_audit.get('status', 'UNKNOWN')}"
        )
    source_counts = report.get("sourceCounts") or {}
    if source_counts:
        lines.append("来源：")
        for source, count in source_counts.items():
            lines.append(f"- {source}: {count}")
    lines.append("")
    lines.append("安全边界：只写执行反馈证据，不会下单、平仓、撤单或修改实盘 preset。")
    return "\n".join(lines)
