from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict

try:
    from tools.usdjpy_strategy_lab.data_loader import _write_json
except ModuleNotFoundError:  # pragma: no cover
    from usdjpy_strategy_lab.data_loader import _write_json

from .dataset_loader import load_replay_samples, summarize_input_coverage
from .entry_variants import build_entry_events
from .exit_variants import build_exit_events
from .metrics import summarize_events
from .schema import (
    FOCUS_SYMBOL,
    READ_ONLY_SAFETY,
    SCHEMA_ENTRY,
    SCHEMA_EXIT,
    SCHEMA_REPORT,
    VARIANT_CURRENT,
    VARIANT_LET_PROFIT_RUN,
    VARIANT_RELAXED_ENTRY,
    utc_now_iso,
)
try:
    from tools.news_gate.replay import build_news_gate_replay_report
except ModuleNotFoundError:  # CLI execution from tools/
    from news_gate.replay import build_news_gate_replay_report


def _out_dir(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "replay" / "usdjpy"


def build_entry_comparison(runtime_dir: Path, write: bool = False) -> Dict[str, Any]:
    samples = load_replay_samples(runtime_dir)
    input_coverage = summarize_input_coverage(samples)
    current_events = build_entry_events(samples, VARIANT_CURRENT)
    relaxed_events = build_entry_events(samples, VARIANT_RELAXED_ENTRY)
    current_metrics = summarize_events(current_events)
    relaxed_metrics = summarize_events(relaxed_events, baseline=current_metrics)
    payload = {
        "ok": True,
        "schema": SCHEMA_ENTRY,
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "safety": READ_ONLY_SAFETY,
        "causalReplay": {
            "posteriorMayAffectTrigger": False,
            "posteriorUse": "15/30/60/120 分钟后验窗口只用于评分，不参与当时入场触发。",
            "hardGatesNeverRelaxed": ["runtime", "fastlane", "highImpactNews", "spread", "session", "cooldown", "startup", "capacity"],
            "ordinaryNewsBlocksLive": False,
        },
        "inputCoverage": input_coverage,
        "variants": [
            {"name": VARIANT_CURRENT, "labelZh": "当前规则", "metrics": current_metrics},
            {"name": VARIANT_RELAXED_ENTRY, "labelZh": "放宽 RSI 一档", "metrics": relaxed_metrics},
        ],
        "events": {
            VARIANT_CURRENT: current_events[:80],
            VARIANT_RELAXED_ENTRY: relaxed_events[:80],
        },
    }
    if write:
        _write_json(_out_dir(runtime_dir) / "QuantGod_USDJPYEntryVariantComparison.json", payload)
    return payload


def build_exit_comparison(runtime_dir: Path, write: bool = False) -> Dict[str, Any]:
    samples = load_replay_samples(runtime_dir)
    current_events = build_exit_events(samples, VARIANT_CURRENT)
    let_run_events = build_exit_events(samples, VARIANT_LET_PROFIT_RUN)
    current_metrics = summarize_events(current_events)
    let_run_metrics = summarize_events(let_run_events, baseline=current_metrics)
    payload = {
        "ok": True,
        "schema": SCHEMA_EXIT,
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "safety": READ_ONLY_SAFETY,
        "causalReplay": {
            "posteriorMayAffectTrigger": False,
            "posteriorUse": "出场候选只重估已发生入场的出场持有，不新增未来触发。",
        },
        "variants": [
            {"name": VARIANT_CURRENT, "labelZh": "当前出场", "metrics": current_metrics},
            {"name": VARIANT_LET_PROFIT_RUN, "labelZh": "延后保本/放宽回吐", "metrics": let_run_metrics},
        ],
        "events": {
            VARIANT_CURRENT: current_events[:80],
            VARIANT_LET_PROFIT_RUN: let_run_events[:80],
        },
    }
    if write:
        _write_json(_out_dir(runtime_dir) / "QuantGod_USDJPYExitVariantComparison.json", payload)
    return payload


def build_bar_replay_report(runtime_dir: Path, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    samples = load_replay_samples(runtime_dir)
    entry = build_entry_comparison(runtime_dir, write=write)
    exit_cmp = build_exit_comparison(runtime_dir, write=write)
    entry_current = entry["variants"][0]["metrics"]
    entry_relaxed = entry["variants"][1]["metrics"]
    exit_current = exit_cmp["variants"][0]["metrics"]
    exit_let_run = exit_cmp["variants"][1]["metrics"]
    news_gate_replay = build_news_gate_replay_report(runtime_dir, entry, write=write)
    payload = {
        "ok": True,
        "schema": SCHEMA_REPORT,
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "status": "BAR_REPLAY_READY" if samples else "NO_USDJPY_SAMPLES",
        "statusZh": "已生成 USDJPY 因果回放" if samples else "缺少 USDJPY 样本，等待 EA/运行数据写入",
        "safety": READ_ONLY_SAFETY,
        "unitPolicy": {
            "primary": "R",
            "secondary": "pips",
            "bookReference": "USC",
            "note": "入场和出场评分只使用 R；pips 辅助展示，USC 仅保留为账面参考。",
        },
        "causalReplay": {
            "posteriorMayAffectTrigger": False,
            "posteriorUsedForScoringOnly": True,
            "explanationZh": (
                "每一步只使用当时样本已存在的 RSI、session、spread、news、cooldown 和守门状态；"
                "未来后验窗口只用于事后评分。"
            ),
        },
        "summary": {
            "sampleCount": len(samples),
            "inputCoverage": entry.get("inputCoverage") or {},
            "currentEntryCount": entry_current.get("sampleCount", 0),
            "relaxedEntryCount": entry_relaxed.get("sampleCount", 0),
            "entryCountDelta": entry_relaxed.get("entryCountDelta", 0),
            "relaxedNetRDelta": entry_relaxed.get("netRDelta", 0),
            "currentProfitCapture": exit_current.get("profitCaptureRatio"),
            "letProfitRunCapture": exit_let_run.get("profitCaptureRatio"),
            "letProfitRunNetRDelta": exit_let_run.get("netRDelta", 0),
            "entryConclusion": entry_relaxed.get("conclusion"),
            "exitConclusion": exit_let_run.get("conclusion"),
            "newsGateRecommendation": news_gate_replay.get("recommendationZh"),
        },
        "entryComparison": entry,
        "exitComparison": exit_cmp,
        "newsGateReplay": news_gate_replay,
        "nextStepZh": _next_step(entry_relaxed, exit_let_run),
    }
    if write:
        out_dir = _out_dir(runtime_dir)
        _write_json(out_dir / "QuantGod_USDJPYBarReplayReport.json", payload)
        _write_ledger(out_dir / "QuantGod_USDJPYReplayLedger.csv", payload)
    return payload


def _next_step(entry_metrics: Dict[str, Any], exit_metrics: Dict[str, Any]) -> str:
    conclusions = {entry_metrics.get("conclusion"), exit_metrics.get("conclusion")}
    if "LIVE_CONFIG_PROPOSAL_ELIGIBLE" in conclusions:
        return "可进入 live config proposal 审查，但仍禁止自动应用。"
    if "TESTER_ONLY" in conclusions:
        return "进入 tester-only / shadow 验证，不自动改实盘。"
    if "SHADOW_ONLY" in conclusions:
        return "样本或后验证据不足，继续 shadow-only 采集。"
    return "候选没有改善或风险扩大，暂不调整。"


def _write_ledger(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for group_name in ("entryComparison", "exitComparison"):
        group = payload.get(group_name) if isinstance(payload.get(group_name), dict) else {}
        for variant in group.get("variants", []):
            metrics = variant.get("metrics", {}) if isinstance(variant, dict) else {}
            rows.append({
                "generatedAtIso": payload.get("generatedAtIso"),
                "group": group_name,
                "variant": variant.get("name"),
                "conclusion": metrics.get("conclusion"),
                "sampleCount": metrics.get("sampleCount"),
                "netR": metrics.get("netR"),
                "netRDelta": metrics.get("netRDelta"),
                "maxAdverseR": metrics.get("maxAdverseR"),
                "winRate": metrics.get("winRate"),
            })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["generatedAtIso"])
        writer.writeheader()
        writer.writerows(rows)
