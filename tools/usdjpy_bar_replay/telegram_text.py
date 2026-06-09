from __future__ import annotations

from typing import Any, Dict


def _metric(group: Dict[str, Any], index: int, key: str, fallback: str = "—") -> Any:
    variants = group.get("variants") if isinstance(group.get("variants"), list) else []
    if len(variants) <= index:
        return fallback
    metrics = variants[index].get("metrics") if isinstance(variants[index].get("metrics"), dict) else {}
    value = metrics.get(key)
    return fallback if value in (None, "") else value


def bar_replay_to_chinese_text(payload: Dict[str, Any]) -> str:
    entry = payload.get("entryComparison") if isinstance(payload.get("entryComparison"), dict) else {}
    exit_cmp = payload.get("exitComparison") if isinstance(payload.get("exitComparison"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return "\n".join([
        "【USDJPY 回放模拟报告】",
        "",
        f"状态：{payload.get('statusZh') or payload.get('status') or '未知'}",
        "回放范围：本地 USDJPY 运行样本",
        "主口径：R；辅助口径：pips；USC 只作账面参考",
        "实盘修改：无",
        "",
        "入场候选对比：",
        (
            f"- 当前规则：入场 {_metric(entry, 0, 'sampleCount', 0)} 次，"
            f"净值 {_metric(entry, 0, 'netR', 0)}R，"
            f"最大不利 {_metric(entry, 0, 'maxAdverseR')}R"
        ),
        (
            f"- 放宽 RSI 一档：入场 {_metric(entry, 1, 'sampleCount', 0)} 次，"
            f"净变化 {_metric(entry, 1, 'netRDelta', 0)}R，"
            f"最大不利 {_metric(entry, 1, 'maxAdverseR')}R"
        ),
        f"结论：{summary.get('entryConclusion') or '待补样本'}",
        "",
        "出场候选对比：",
        f"- 当前出场：利润捕获率 {_metric(exit_cmp, 0, 'profitCaptureRatio')}",
        f"- 延后保本/放宽回吐：利润捕获率 {_metric(exit_cmp, 1, 'profitCaptureRatio')}，净变化 {_metric(exit_cmp, 1, 'netRDelta', 0)}R",
        f"结论：{summary.get('exitConclusion') or '待补样本'}",
        "",
        f"下一步：{payload.get('nextStepZh') or '继续采集，不自动修改实盘。'}",
        "",
        "因果边界：后验窗口只用于评分，不能决定当时是否入场。",
        "安全边界：不会下单、不会平仓、不会撤单、不会修改实盘 preset。",
    ])
