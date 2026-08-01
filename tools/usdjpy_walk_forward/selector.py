from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

try:
    from tools.usdjpy_strategy_lab.data_loader import _write_json, first_json
    from tools.usdjpy_bar_replay.replay_engine import build_bar_replay_report
except ModuleNotFoundError:  # pragma: no cover
    from usdjpy_strategy_lab.data_loader import _write_json, first_json
    from usdjpy_bar_replay.replay_engine import build_bar_replay_report

from .metrics import compare, summarize
from .schema import (
    CONCLUSION_LIVE_CONFIG_ELIGIBLE,
    CONCLUSION_REJECTED,
    CONCLUSION_SHADOW_ONLY,
    CONCLUSION_TESTER_ONLY,
    FOCUS_SYMBOL,
    READ_ONLY_SAFETY,
    SCHEMA_PROPOSAL,
    SCHEMA_SELECTION,
    SCHEMA_WALK_FORWARD,
    SEGMENTS,
    utc_now_iso,
)
from .splitter import split_events


def _load_bar_replay(runtime_dir: Path) -> Dict[str, Any]:
    payload = first_json(runtime_dir, "QuantGod_USDJPYBarReplayReport.json") or {}
    if payload:
        return payload
    return build_bar_replay_report(runtime_dir, write=False)


def _events(group: Dict[str, Any], variant: str) -> List[Dict[str, Any]]:
    payload = group.get("events") if isinstance(group.get("events"), dict) else {}
    values = payload.get(variant) if isinstance(payload.get(variant), list) else []
    return [item for item in values if isinstance(item, dict)]


def _segment_comparison(current_events: List[Dict[str, Any]], candidate_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    current_segments = split_events(current_events)
    candidate_segments = split_events(candidate_events)
    result: Dict[str, Any] = {}
    for segment in SEGMENTS:
        result[segment] = compare(summarize(candidate_segments[segment]), summarize(current_segments[segment]))
    return result


def _is_non_deteriorating(segment: Dict[str, Any]) -> bool:
    if int(segment.get("scoredSampleCount") or 0) <= 0:
        return False
    if float(segment.get("netRDelta") or 0.0) < 0:
        return False
    adverse_delta = segment.get("maxAdverseDeltaR")
    if adverse_delta is not None and float(adverse_delta) < -0.35:
        return False
    return True


def _grade_candidate(segments: Dict[str, Dict[str, Any]]) -> str:
    total_scored = sum(int(item.get("scoredSampleCount") or 0) for item in segments.values())
    total_delta = round(sum(float(item.get("netRDelta") or 0.0) for item in segments.values()), 4)
    if not _is_non_deteriorating(segments.get("validation", {})) or not _is_non_deteriorating(segments.get("forward", {})):
        return CONCLUSION_REJECTED
    if total_scored < 9:
        return CONCLUSION_SHADOW_ONLY
    if total_scored >= 45 and total_delta > 1.0:
        forward = segments.get("forward", {})
        validation = segments.get("validation", {})
        if float(forward.get("netRDelta") or 0.0) > 0 and float(validation.get("netRDelta") or 0.0) > 0:
            return CONCLUSION_LIVE_CONFIG_ELIGIBLE
    return CONCLUSION_TESTER_ONLY


def _candidate_summary(name: str, label: str, group: str, segments: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    total_delta = round(sum(float(item.get("netRDelta") or 0.0) for item in segments.values()), 4)
    total_samples = sum(int(item.get("sampleCount") or 0) for item in segments.values())
    conclusion = _grade_candidate(segments)
    return {
        "variant": name,
        "labelZh": label,
        "group": group,
        "conclusion": conclusion,
        "segments": segments,
        "summary": {
            "sampleCount": total_samples,
            "netRDelta": total_delta,
            "validationNetRDelta": segments.get("validation", {}).get("netRDelta"),
            "forwardNetRDelta": segments.get("forward", {}).get("netRDelta"),
            "stableAcrossValidationAndForward": conclusion != CONCLUSION_REJECTED,
        },
        "reasonZh": _reason_zh(conclusion, total_delta, segments),
        "autoApplyAllowed": "shadow_only",
        "requiresAutonomousGovernance": True,
        "operatorApprovalRequired": True,
        "unattendedLiveExpansionAllowed": False,
        "liveExpansionAllowed": False,
        "completedByAgent": True,
        "autoAppliedByAgent": False,
        "posteriorUsedForScoringOnly": True,
    }


def _reason_zh(conclusion: str, total_delta: float, segments: Dict[str, Dict[str, Any]]) -> str:
    if conclusion == CONCLUSION_REJECTED:
        return "validation 或 forward 段出现净 R 变差 / 风险恶化，拒绝进入下一阶段。"
    if conclusion == CONCLUSION_SHADOW_ONLY:
        return "三段没有明显恶化，但样本太少，只能继续影子观察。"
    if conclusion == CONCLUSION_LIVE_CONFIG_ELIGIBLE:
        return f"三段稳定且总净改善 {total_delta}R，可进入自主治理门；通过硬风控后只写受控 patch。"
    return "三段没有明显恶化，可进入 tester-only / shadow 验证。"


def build_walk_forward_report(runtime_dir: Path, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    replay = _load_bar_replay(runtime_dir)
    entry = replay.get("entryComparison") if isinstance(replay.get("entryComparison"), dict) else {}
    exit_cmp = replay.get("exitComparison") if isinstance(replay.get("exitComparison"), dict) else {}
    entry_candidate = _candidate_summary(
        "relaxed_entry_v1",
        "放宽 RSI 一档",
        "entry",
        _segment_comparison(_events(entry, "current"), _events(entry, "relaxed_entry_v1")),
    )
    exit_candidate = _candidate_summary(
        "let_profit_run_v1",
        "盈利多拿一段",
        "exit",
        _segment_comparison(_events(exit_cmp, "current"), _events(exit_cmp, "let_profit_run_v1")),
    )
    candidates = [entry_candidate, exit_candidate]
    payload = {
        "ok": True,
        "schema": SCHEMA_WALK_FORWARD,
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "status": (
            "WALK_FORWARD_READY"
            if any(item["summary"]["sampleCount"] for item in candidates)
            else "NO_REPLAY_EVENTS"
        ),
        "statusZh": (
            "已生成 USDJPY walk-forward 参数筛选"
            if any(item["summary"]["sampleCount"] for item in candidates)
            else "缺少回放事件，等待 P3-19 回放补样本"
        ),
        "safety": READ_ONLY_SAFETY,
        "splitPolicy": {
            "segments": list(SEGMENTS),
            "ratio": "60/20/20",
            "causalBoundaryZh": "分段评分只用于验证参数稳定性；不会反向改变当时的入场触发。",
        },
        "candidates": candidates,
        "summary": {
            "candidateCount": len(candidates),
            "rejectedCount": sum(1 for item in candidates if item["conclusion"] == CONCLUSION_REJECTED),
            "testerOnlyCount": sum(1 for item in candidates if item["conclusion"] == CONCLUSION_TESTER_ONLY),
            "liveProposalEligibleCount": sum(1 for item in candidates if item["conclusion"] == CONCLUSION_LIVE_CONFIG_ELIGIBLE),
        },
    }
    if write:
        out_dir = runtime_dir / "replay" / "usdjpy"
        _write_json(out_dir / "QuantGod_USDJPYWalkForwardReport.json", payload)
    return payload


def build_parameter_selection(runtime_dir: Path, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    report = first_json(runtime_dir, "QuantGod_USDJPYWalkForwardReport.json") or build_walk_forward_report(runtime_dir, write=False)
    candidates = report.get("candidates") if isinstance(report.get("candidates"), list) else []
    selected = []
    rejected = []
    for item in candidates:
        target = selected if item.get("conclusion") != CONCLUSION_REJECTED else rejected
        target.append({
            "variant": item.get("variant"),
            "labelZh": item.get("labelZh"),
            "group": item.get("group"),
            "conclusion": item.get("conclusion"),
            "reasonZh": item.get("reasonZh"),
            "summary": item.get("summary"),
            "segments": item.get("segments"),
            "autoApplyAllowed": "shadow_only",
            "requiresAutonomousGovernance": True,
            "operatorApprovalRequired": True,
            "unattendedLiveExpansionAllowed": False,
            "liveExpansionAllowed": False,
            "completedByAgent": True,
            "autoAppliedByAgent": False,
        })
    payload = {
        "ok": True,
        "schema": SCHEMA_SELECTION,
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "status": "PARAMETER_SELECTION_READY" if selected else "ALL_CANDIDATES_REJECTED_OR_PENDING",
        "statusZh": "已生成 walk-forward 参数选择" if selected else "候选不稳定，暂不进入 tester-only",
        "selected": selected,
        "rejected": rejected,
        "safety": READ_ONLY_SAFETY,
    }
    if write:
        out_dir = runtime_dir / "replay" / "usdjpy"
        _write_json(out_dir / "QuantGod_USDJPYParameterSelection.json", payload)
    return payload


def build_live_config_proposal(runtime_dir: Path, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    selection = first_json(runtime_dir, "QuantGod_USDJPYParameterSelection.json") or build_parameter_selection(runtime_dir, write=False)
    selected = selection.get("selected") if isinstance(selection.get("selected"), list) else []
    eligible = [item for item in selected if item.get("conclusion") == CONCLUSION_LIVE_CONFIG_ELIGIBLE]
    tester = [item for item in selected if item.get("conclusion") == CONCLUSION_TESTER_ONLY]
    payload = {
        "ok": True,
        "schema": SCHEMA_PROPOSAL,
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "status": (
            "LIVE_CONFIG_PROPOSAL_READY"
            if eligible
            else ("TESTER_ONLY_READY" if tester else "NO_LIVE_CONFIG_CHANGE")
        ),
        "statusZh": (
            "已有候选可进入自主治理门；通过后只写受控 patch"
            if eligible
            else ("已有候选可进入 tester-only，暂不改实盘" if tester else "没有稳定候选，暂不改实盘")
        ),
        "eligibleChanges": eligible,
        "testerOnlyChanges": tester,
        "autoApplyAllowed": "shadow_only",
        "requiresAutonomousGovernance": True,
        "operatorApprovalRequired": True,
        "unattendedLiveExpansionAllowed": False,
        "liveExpansionAllowed": False,
        "liveScopeExpansionMode": "operator_reviewed_future_lane",
        "completedByAgent": True,
        "autoAppliedByAgent": False,
        "requiresTesterOnlyValidation": True,
        "requiresShadowValidation": True,
        "safety": READ_ONLY_SAFETY,
    }
    if write:
        out_dir = runtime_dir / "proposals"
        _write_json(out_dir / "QuantGod_USDJPYLiveConfigProposal.json", payload)
    return payload


def sample_walk_forward_runtime(runtime_dir: Path, overwrite: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    blockers = runtime_dir / "QuantGod_EntryBlockers.csv"
    close = runtime_dir / "QuantGod_CloseHistory.csv"
    if (blockers.exists() or close.exists()) and not overwrite:
        return {"ok": True, "skipped": True, "reason": "sample already exists", "runtimeDir": str(runtime_dir)}
    runtime_dir.mkdir(parents=True, exist_ok=True)
    blocker_rows: List[Dict[str, Any]] = []
    dates = [
        ("2026-05-01T09:10:00Z", "0.28", "-0.24"),
        ("2026-05-01T10:20:00Z", "0.18", "-0.20"),
        ("2026-05-01T11:35:00Z", "0.31", "-0.26"),
        ("2026-05-02T09:45:00Z", "0.22", "-0.22"),
        ("2026-05-02T10:55:00Z", "0.24", "-0.25"),
        ("2026-05-03T09:25:00Z", "0.16", "-0.18"),
        ("2026-05-04T09:15:00Z", "0.20", "-0.21"),
        ("2026-05-04T10:40:00Z", "0.12", "-0.19"),
        ("2026-05-05T09:35:00Z", "0.21", "-0.23"),
        ("2026-05-05T11:00:00Z", "0.19", "-0.22"),
    ]
    for timestamp, posterior, mae in dates:
        blocker_rows.append({
            "timestamp": timestamp,
            "symbol": FOCUS_SYMBOL,
            "strategy": "RSI_Reversal",
            "direction": "LONG",
            "status": "READY_BUY_SIGNAL",
            "reason": "NO_CROSS tactical confirmation missing",
            "riskPips": "5",
            "posteriorR60": posterior,
            "posteriorPips60": str(round(float(posterior) * 5, 3)),
            "maeR": mae,
        })
    with blockers.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(blocker_rows[0].keys()))
        writer.writeheader()
        writer.writerows(blocker_rows)
    close_rows = [
        ("2026-05-01T12:30:00Z", "0.20", "1.05", "-0.24"),
        ("2026-05-02T13:15:00Z", "0.18", "0.94", "-0.30"),
        ("2026-05-03T14:00:00Z", "0.24", "1.20", "-0.22"),
        ("2026-05-04T12:45:00Z", "0.15", "0.88", "-0.25"),
        ("2026-05-05T13:10:00Z", "0.21", "1.12", "-0.27"),
    ]
    with close.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "symbol", "strategy", "direction", "profitUSC", "profitR", "mfeR", "maeR", "exitReason"])
        writer.writeheader()
        for timestamp, profit_r, mfe_r, mae_r in close_rows:
            writer.writerow({
                "timestamp": timestamp,
                "symbol": FOCUS_SYMBOL,
                "strategy": "RSI_Reversal",
                "direction": "LONG",
                "profitUSC": str(round(float(profit_r) * 1.5, 4)),
                "profitR": profit_r,
                "mfeR": mfe_r,
                "maeR": mae_r,
                "exitReason": "breakeven_or_trailing",
            })
    return {"ok": True, "entryBlockers": str(blockers), "closeHistory": str(close)}
