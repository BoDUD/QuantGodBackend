from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

try:
    from tools.usdjpy_strategy_lab.data_loader import _write_json, first_json
except ModuleNotFoundError:  # pragma: no cover - CLI entrypoint runs from tools/
    from usdjpy_strategy_lab.data_loader import _write_json, first_json

from .replay import build_replay_report
from .schema import FOCUS_SYMBOL, READ_ONLY_SAFETY, SCHEMA_TUNING, utc_now_iso


def _candidate(
    param: str,
    current: str,
    proposed: str,
    reason: str,
    evidence: Dict[str, Any],
    expected_impact: str = "需要 replay/shadow 继续确认",
    risk_delta: str = "未知，禁止直接改 live preset",
    replay_variant: str = "",
    evidence_quality: str = "RULE_BASED_REPLAY_SUMMARY",
) -> Dict[str, Any]:
    return {
        "param": param,
        "current": current,
        "proposed": proposed,
        "reason": reason,
        "evidence": evidence,
        "expectedImpact": expected_impact,
        "riskDelta": risk_delta,
        "replayVariant": replay_variant,
        "evidenceQuality": evidence_quality,
        "scope": "autonomous governance / tester / shadow validation",
        "autoApplyAllowed": "shadow_only",
        "requiresAutonomousGovernance": True,
        "completedByAgent": True,
        "autoAppliedByAgent": False,
    }


def build_param_tuning_report(runtime_dir: Path, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    replay = first_json(runtime_dir, "QuantGod_USDJPYReplayReport.json") or build_replay_report(runtime_dir, write=False)
    summary = replay.get("summary") if isinstance(replay.get("summary"), dict) else {}
    missed = int(summary.get("missedOpportunityCount") or 0)
    early = int(summary.get("earlyExitCount") or 0)
    samples = int(summary.get("sampleCount") or 0)
    posterior_ready = int(summary.get("posteriorReadyCount") or 0)
    missing_exit_r = int(summary.get("missingExitRCount") or 0)
    scenarios = replay.get("scenarioComparisons") if isinstance(replay.get("scenarioComparisons"), list) else []
    scenario_map = {str(item.get("scenario")): item for item in scenarios if isinstance(item, dict)}
    relaxed = scenario_map.get("relaxed_entry_v1", {})
    let_profit = scenario_map.get("let_profit_run_v1", {})
    candidates: List[Dict[str, Any]] = []
    if missed > 0:
        relaxed_delta = relaxed.get("netRDelta")
        relaxed_text = f"后验样本显示放宽入场约 {relaxed_delta}R" if relaxed_delta is not None else "已有错失样本，但缺少后验 bar/tick 路径"
        risk_text = f"最大不利波动约 {relaxed.get('maxAdverseR')}R" if relaxed.get("maxAdverseR") is not None else "需要 bar/tick replay 补 MAE"
        candidates.append(_candidate(
            "rsiBuyCrossbackThreshold",
            "当前 EA preset",
            "放宽 1 档后仅在 replay/shadow 验证",
            "回放发现 READY/准入信号未成交，需要评估 RSI crossback 是否过紧。",
            {"missedOpportunityCount": missed, "posteriorReadyCount": posterior_ready, "sampleCount": samples, "scenario": relaxed},
            relaxed_text,
            risk_text,
            "relaxed_entry_v1",
            "POSTERIOR_PATH_READY" if posterior_ready else "NEEDS_BAR_REPLAY",
        ))
        candidates.append(_candidate(
            "sessionWindow",
            "当前交易时段",
            "东京/伦敦交接段扩大 15-30 分钟后回放",
            "错失机会需要拆分 session 阻断与合理阻断，不直接修改实盘。",
            {"missedOpportunityCount": missed, "posteriorReadyCount": posterior_ready, "scenario": relaxed},
            relaxed_text,
            "扩大 session 可能增加点差/假突破暴露，必须 shadow-only",
            "relaxed_entry_v1",
            "POSTERIOR_PATH_READY" if posterior_ready else "NEEDS_BAR_REPLAY",
        ))
    if early > 0:
        hold_delta = let_profit.get("netRDelta")
        candidates.append(_candidate(
            "breakevenDelayR",
            "0.7R 或当前 preset",
            "1.0R",
            "回放发现盈利单可能过早保护，先延后保本做 tester-only 验证。",
            {"earlyExitCount": early, "missingExitRCount": missing_exit_r, "scenario": let_profit},
            f"按 MFE 捕获率估算，延后保本最多可多捕获 {hold_delta}R" if hold_delta is not None else "需要 profitR/MFER 完整样本确认",
            "延后保本可能增加回吐，必须先做 shadow 出场复盘",
            "let_profit_run_v1",
            "R_MULTIPLE_READY" if hold_delta is not None else "NEEDS_PROFIT_R",
        ))
        candidates.append(_candidate(
            "mfeGivebackPct",
            "45%",
            "60%",
            "提高 MFE 回吐容忍，减少刚盈利就抛的情况。",
            {"earlyExitCount": early, "missingExitRCount": missing_exit_r, "scenario": let_profit},
            f"按 MFE 捕获率估算，let_profit_run_v1 净增 {hold_delta}R" if hold_delta is not None else "需要 profitR/MFER 完整样本确认",
            "回吐容忍提高会扩大单笔浮盈回撤",
            "let_profit_run_v1",
            "R_MULTIPLE_READY" if hold_delta is not None else "NEEDS_PROFIT_R",
        ))
    if not candidates and samples < 20:
        candidates.append(_candidate(
            "dataCollection",
            "样本不足",
            "继续采集 USDJPY runtime dataset",
            "当前样本不足以判断参数优劣，先补齐运行数据。",
            {"sampleCount": samples},
        ))
    status = "PARAM_CANDIDATES_READY" if any(c["param"] != "dataCollection" for c in candidates) else "COLLECT_MORE_DATA"
    payload = {
        "ok": True,
        "schema": SCHEMA_TUNING,
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "status": status,
        "statusZh": "已生成 USDJPY 参数候选" if status == "PARAM_CANDIDATES_READY" else "继续采集数据，暂不调实盘参数",
        "summary": {
            "candidateCount": len(candidates),
            "sampleCount": samples,
            "missedOpportunityCount": missed,
            "earlyExitCount": early,
            "autoApplyAllowed": "shadow_only",
            "requiresAutonomousGovernance": True,
        },
        "candidates": candidates,
        "safety": READ_ONLY_SAFETY,
    }
    if write:
        out_dir = runtime_dir / "adaptive"
        _write_json(out_dir / "QuantGod_USDJPYParamCandidates.json", {"generatedAtIso": payload["generatedAtIso"], "symbol": FOCUS_SYMBOL, "candidates": candidates, "safety": READ_ONLY_SAFETY})
        _write_json(out_dir / "QuantGod_USDJPYParamTuningReport.json", payload)
    return payload
