from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

try:
    from tools.usdjpy_strategy_lab.data_loader import focus_runtime_snapshot
    from tools.usdjpy_strategy_lab.dry_run_bridge import build_dry_run_decision
    from tools.usdjpy_strategy_lab.entry_context_feedback import append_entry_context_feedback
    from tools.usdjpy_strategy_lab.policy_builder import _runtime_freshness, build_usdjpy_policy
except ModuleNotFoundError:  # CLI execution from tools/
    from usdjpy_strategy_lab.data_loader import focus_runtime_snapshot
    from usdjpy_strategy_lab.dry_run_bridge import build_dry_run_decision
    from usdjpy_strategy_lab.entry_context_feedback import append_entry_context_feedback
    from usdjpy_strategy_lab.policy_builder import _runtime_freshness, build_usdjpy_policy

from .preset import load_live_preset
from .schema import (
    FOCUS_SYMBOL,
    SAFE_EVIDENCE_BOUNDARY,
    SCHEMA_DAILY,
    SCHEMA_INTENT,
    SCHEMA_STATUS,
    STATE_EVIDENCE_MISSING,
    STATE_POLICY_BLOCKED,
    STATE_POLICY_READY_PRESET_BLOCKED,
    STATE_READY,
    STATE_ZH,
    direction_zh,
    entry_mode_zh,
    utc_now_iso,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    top = payload.get("topShadowPolicy") or payload.get("topPolicy") or {}
    row = {
        "generatedAt": payload.get("generatedAt", ""),
        "state": payload.get("state", ""),
        "stateZh": payload.get("stateZh", ""),
        "topStrategy": top.get("strategy", ""),
        "topDirection": top.get("direction", ""),
        "entryMode": top.get("entryMode", ""),
        "recommendedLot": top.get("recommendedLot", ""),
        "presetReady": str(bool((payload.get("preset") or {}).get("ready"))).lower(),
        "runtimeReady": str(bool((payload.get("runtime") or {}).get("ready"))).lower(),
        "whyNoEntry": "；".join(payload.get("whyNoEntry") or [])[:500],
    }
    fields = list(row)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def _research_candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict) or not candidate:
        return {}
    result = dict(candidate)
    result.pop("allowed", None)
    result["researchOnly"] = True
    result["executionAllowed"] = False
    result["executionLaneExists"] = False
    return result


def _legacy_research_view(payload: dict[str, Any], schema_name: str) -> dict[str, Any]:
    result = dict(payload)
    result["compatibility"] = {
        "legacySchema": schema_name,
        "researchOnly": True,
        "executionAllowed": False,
        "executionLaneExists": False,
        "existingEaOwnsExecution": False,
    }
    return result


def _runtime_status(runtime_dir: Path) -> dict[str, Any]:
    snapshot = focus_runtime_snapshot(runtime_dir)
    if not snapshot:
        return {
            "found": False,
            "ready": False,
            "reasons": ["缺少 USDJPY 运行快照，无法确认 Shadow/ReadOnly 运行状态"],
        }
    runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}
    age = snapshot.get("runtimeAgeSeconds", snapshot.get("_fileAgeSeconds"))
    runtime_tier, ready, tier_reasons = _runtime_freshness(snapshot)
    reasons: list[str] = [str(item) for item in tier_reasons if item]
    if not reasons:
        reasons.append("USDJPY 运行快照可用")
    return {
        "found": True,
        "ready": ready,
        "freshnessTier": runtime_tier,
        "ageSeconds": age,
        "tradeStatus": runtime.get("tradeStatus") or snapshot.get("tradeStatus"),
        "executionEnabled": runtime.get("executionEnabled", snapshot.get("executionEnabled")),
        "readOnlyMode": runtime.get("readOnlyMode", snapshot.get("readOnlyMode")),
        "openPositions": runtime.get("positions", snapshot.get("openPositions")),
        "tickAgeSeconds": runtime.get("tickAgeSeconds"),
        "reasons": reasons,
        "source": snapshot.get("_filePath"),
    }


def _policy_ready(policy: dict[str, Any]) -> tuple[bool, list[str]]:
    top = policy.get("topShadowPolicy") or policy.get("topPolicy") or {}
    fallback = policy.get("liveRecoveryCandidate") or {}
    spread_gates = [
        policy.get("spreadGate"),
        top.get("spreadGate") if isinstance(top, dict) else None,
        fallback.get("spreadGate") if isinstance(fallback, dict) else None,
    ]
    hard_block_reasons: list[str] = []
    for spread_gate in spread_gates:
        if isinstance(spread_gate, dict) and spread_gate.get("hardBlock"):
            hard_block_reasons.append(str(spread_gate.get("reasonZh") or "点差硬阻断"))
    if hard_block_reasons:
        return False, list(dict.fromkeys(hard_block_reasons))[:6]
    if not top:
        priority_reasons: list[str] = []
        priority_reasons.extend(str(item) for item in (fallback.get("hardGateReasons") or []) if item)
        priority_reasons.extend(str(item) for item in (fallback.get("reasons") or []) if item)
        return False, [
            "没有可进入 Shadow advisory 复核的策略政策",
            *list(dict.fromkeys(priority_reasons))[:6],
        ]
    reasons = list(top.get("reasons") or [])
    return True, ["USDJPY Shadow advisory 策略政策已就绪", *reasons[:3]]


def _build_next_actions(state: str, policy: dict[str, Any], preset: dict[str, Any], runtime: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if not runtime.get("ready"):
        actions.append("先恢复 USDJPY 运行快照和快通道证据，避免基于旧数据判断。")
    if not preset.get("ready"):
        actions.append("检查 legacy preset：必须保持 Shadow=true、ReadOnly=true 且自动交易关闭。")
    if state == STATE_POLICY_BLOCKED:
        actions.append("继续自动 retune/backtest：重点分析阻断原因是否来自样本不足、触发缺失或动态止盈止损缺失。")
    if state == STATE_READY:
        actions.append("继续积累 Shadow 样本与只读证据，不触发 broker mutation。")
    if not actions:
        actions.append("保持 USDJPY-only 自动链路每小时刷新，并在 Telegram 推送中文复盘。")
    return actions


def build_live_loop(repo_root: Path, runtime_dir: Path, *, write: bool = False, min_samples: int = 5) -> dict[str, Any]:
    policy = build_usdjpy_policy(runtime_dir, write=write, min_samples=min_samples)
    dry_run = build_dry_run_decision(runtime_dir, write=write)
    preset = load_live_preset(repo_root)
    runtime = _runtime_status(runtime_dir)
    policy_ok, policy_reasons = _policy_ready(policy)
    why_no_entry: list[str] = []
    if not runtime.get("ready"):
        why_no_entry.extend(runtime.get("reasons") or [])
    if not policy_ok:
        why_no_entry.extend(policy_reasons)
    if not preset.get("ready"):
        why_no_entry.extend(preset.get("reasons") or [])
    if not runtime.get("ready"):
        state = STATE_EVIDENCE_MISSING
    elif not policy_ok:
        state = STATE_POLICY_BLOCKED
    elif not preset.get("ready"):
        state = STATE_POLICY_READY_PRESET_BLOCKED
    else:
        state = STATE_READY
    raw_top = policy.get("topShadowPolicy") or policy.get("topPolicy") or policy.get("liveRecoveryCandidate") or {}
    top = _research_candidate(raw_top)
    top_shadow = _research_candidate(policy.get("topShadowPolicy"))
    policy_view = _legacy_research_view(policy, "quantgod.usdjpy_auto_execution_policy.v1")
    dry_run_view = _legacy_research_view(dry_run, "quantgod.usdjpy_ea_dry_run_decision.v1")
    intent = {
        "schema": SCHEMA_INTENT,
        "schemaVersion": 1,
        "generatedAt": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "state": state,
        "stateZh": STATE_ZH.get(state, state),
        "existingEaOwnsExecution": False,
        "executionLaneExists": False,
        "toolDoesNotTrade": True,
        "manualPositionsIgnoredByPolicy": True,
        "maxEaPositions": preset.get("maxEaPositions", 2),
        "topPolicy": top,
        "topShadowPolicy": top_shadow,
        "recommendedLot": top.get("recommendedLot", 0.0),
        "entryMode": top.get("entryMode", "BLOCKED"),
        "strategy": top.get("strategy", "UNKNOWN"),
        "direction": top.get("direction", "UNKNOWN"),
        "spreadGate": policy.get("spreadGate") or top.get("spreadGate") or {},
        "whyNoEntry": list(dict.fromkeys(str(item) for item in why_no_entry if item)),
        "nextActions": _build_next_actions(state, policy, preset, runtime),
        "safety": dict(SAFE_EVIDENCE_BOUNDARY),
    }
    payload = {
        "schema": SCHEMA_STATUS,
        "schemaVersion": 1,
        "generatedAt": intent["generatedAt"],
        "symbol": FOCUS_SYMBOL,
        "state": state,
        "stateZh": intent["stateZh"],
        "advisoryRouteZh": "所有策略仅用于 Shadow/ReadOnly 观察与研究复核。",
        "policyReady": policy_ok,
        "presetReady": bool(preset.get("ready")),
        "runtimeReady": bool(runtime.get("ready")),
        "manualPositionsIgnoredByPolicy": True,
        "maxEaPositions": preset.get("maxEaPositions", 2),
        "topPolicy": top,
        "topShadowPolicy": top_shadow,
        "policy": policy_view,
        "spreadGate": policy.get("spreadGate") or top.get("spreadGate") or {},
        "dryRun": dry_run_view,
        "preset": preset,
        "runtime": runtime,
        "intent": intent,
        "whyNoEntry": intent["whyNoEntry"],
        "nextActions": intent["nextActions"],
        "safety": dict(SAFE_EVIDENCE_BOUNDARY),
    }
    if write:
        live_dir = runtime_dir / "live"
        payload["entryContextFeedback"] = append_entry_context_feedback(
            runtime_dir,
            policy=policy,
            top_policy=raw_top,
            generated_at=payload["generatedAt"],
            event_type="SHADOW_ADVISORY_CONTEXT",
            source_name="QuantGod_USDJPYLiveLoopStatus.json",
        )
        _write_json(live_dir / "QuantGod_USDJPYLiveLoopStatus.json", payload)
        _write_json(live_dir / "QuantGod_USDJPYLiveIntent.json", intent)
        daily = {
            "schema": SCHEMA_DAILY,
            "schemaVersion": 1,
            "generatedAt": payload["generatedAt"],
            "summaryZh": payload["stateZh"],
            "state": state,
            "advisoryRoute": payload["advisoryRouteZh"],
            "topStrategy": top.get("strategy"),
            "topDirectionZh": direction_zh(top.get("direction")),
            "entryModeZh": entry_mode_zh(top.get("entryMode")),
            "whyNoEntry": intent["whyNoEntry"],
            "nextActions": intent["nextActions"],
            "safety": dict(SAFE_EVIDENCE_BOUNDARY),
        }
        _write_json(live_dir / "QuantGod_USDJPYDailyAutopilot.json", daily)
        _append_ledger(live_dir / "QuantGod_USDJPYLiveLoopLedger.csv", payload)
    return payload
