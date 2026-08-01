from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .promotion_gate import build_promotion_decision
from .schema import (
    FOCUS_SYMBOL,
    HARD_SAFETY,
    ROLLBACK_PAUSED,
    SCHEMA_PATCH,
    STAGE_LIVE_LIMITED,
    STAGE_MICRO_LIVE,
    STAGE_PAPER_LIVE_SIM,
    STAGE_REJECTED,
    STAGE_SHADOW_ONLY,
    STAGE_TESTER_ONLY,
    utc_now_iso,
)

try:
    from tools.autonomous_lifecycle.cent_account_rules import cent_account_config, stage_max_lot
except ModuleNotFoundError:  # pragma: no cover
    from autonomous_lifecycle.cent_account_rules import cent_account_config, stage_max_lot


def _changes_for_variant(variant: str) -> Dict[str, Any]:
    if variant == "relaxed_entry_v1":
        return {"rsiBuyBand": 34, "rsiCrossbackThreshold": 0.0}
    if variant == "let_profit_run_v1":
        return {"breakevenDelayR": 1.0, "trailStartR": 1.5, "mfeGivebackPct": 0.6}
    return {}


def _patch_id(stage: str, generated_at_iso: str) -> str:
    safe_timestamp = generated_at_iso.replace(":", "").replace("-", "").replace("Z", "")
    return f"agent-{FOCUS_SYMBOL}-RSI-LONG-{stage}-{safe_timestamp}"


def _format_ea_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _build_ea_runtime_patch_text(payload: Dict[str, Any]) -> str:
    changes = payload.get("changes") or {}
    limits = payload.get("limits") or {}
    safety = payload.get("safety") or {}
    rows = {
        "schema": "quantgod.autonomous_config_patch_ea.v1",
        "patchId": payload.get("patchId", ""),
        "generatedAtIso": payload.get("generatedAtIso", ""),
        "symbol": payload.get("symbol", FOCUS_SYMBOL),
        "strategy": payload.get("strategy", "RSI_Reversal"),
        "direction": payload.get("direction", "LONG"),
        "executionStage": payload.get("executionStage", ""),
        "stage": payload.get("stage", ""),
        "patchWritable": bool(payload.get("patchWritable")),
        "autoAppliedByAgent": bool(payload.get("autoAppliedByAgent")),
        "requiresAutonomousGovernance": bool(payload.get("requiresAutonomousGovernance")),
        "operatorApprovalRequired": bool(payload.get("operatorApprovalRequired", True)),
        "unattendedLiveExpansionAllowed": bool(payload.get("unattendedLiveExpansionAllowed")),
        "liveExpansionAllowed": bool(payload.get("liveExpansionAllowed")),
        "liveMutationAllowed": bool(payload.get("liveMutationAllowed")),
        "orderSendAllowed": bool(safety.get("orderSendAllowed")),
        "livePresetMutationAllowed": bool(safety.get("livePresetMutationAllowed")),
        "newsHardBypassAllowed": False,
        "runtimeFreshnessBypassAllowed": False,
        "fastlaneBypassAllowed": False,
        "maxLot": limits.get("maxLot", 2.0),
        "stageMaxLot": limits.get("stageMaxLot", 0.0),
        "rsiBuyBand": changes.get("rsiBuyBand", ""),
        "rsiCrossbackThreshold": changes.get("rsiCrossbackThreshold", ""),
        "breakevenDelayR": changes.get("breakevenDelayR", ""),
        "trailStartR": changes.get("trailStartR", ""),
        "mfeGivebackPct": changes.get("mfeGivebackPct", ""),
    }
    return "\n".join(f"{key}={_format_ea_value(value)}" for key, value in rows.items()) + "\n"


def build_config_patch(runtime_dir: Path, *, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    decision = build_promotion_decision(runtime_dir, write=write)
    stage = decision.get("stage", STAGE_REJECTED)
    cent = cent_account_config()
    allowed = stage in {STAGE_SHADOW_ONLY, STAGE_TESTER_ONLY, STAGE_PAPER_LIVE_SIM}
    changes: Dict[str, Any] = {}
    for item in decision.get("candidates") or []:
        if item.get("autonomousStage") in {STAGE_TESTER_ONLY, STAGE_PAPER_LIVE_SIM, STAGE_MICRO_LIVE, STAGE_LIVE_LIMITED}:
            changes.update(_changes_for_variant(str(item.get("variant") or "")))
    patch_writable = bool(allowed and changes and stage != ROLLBACK_PAUSED)
    auto_applied = False
    generated_at_iso = utc_now_iso()
    payload = {
        "ok": True,
        "schema": SCHEMA_PATCH,
        "generatedAtIso": generated_at_iso,
        "patchId": _patch_id(str(stage), generated_at_iso),
        "symbol": FOCUS_SYMBOL,
        "strategy": "RSI_Reversal",
        "direction": "LONG",
        "stage": stage,
        "executionStage": stage,
        "stageZh": decision.get("stageZh"),
        "patchWritable": patch_writable,
        "operatorApprovalRequired": True,
        "unattendedLiveExpansionAllowed": False,
        "liveExpansionAllowed": False,
        "liveScopeExpansionMode": "operator_reviewed_future_lane",
        "liveMutationAllowed": False,
        "requiresAutonomousGovernance": True,
        "completedByAgent": True,
        "autoAppliedByAgent": auto_applied,
        "autoApplyAllowed": "shadow_only",
        "centAccount": cent,
        "changes": changes if allowed else {},
        "limits": {
            "maxLot": cent.get("maxLot", 2.0),
            "stageMaxLot": stage_max_lot(str(stage), cent),
            "microLiveLot": cent.get("microLiveLot", 0.05),
            "opportunityLot": cent.get("opportunityLot", 0.10),
            "standardLot": cent.get("standardLot", 0.35),
            "maxDailyTrades": 2,
            "maxDailyLossR": cent.get("maxDailyLossR", 1.0),
            "maxConsecutiveLosses": cent.get("maxConsecutiveLosses", 2),
        },
        "rollback": {
            "enabled": True,
            "trigger": "lossStreak>=2 OR dailyLossR<=-1.0 OR fastlane not in FAST/EA_DASHBOARD_OK OR runtime stale OR spread abnormal OR highImpactNews",
            "hardBlockers": (decision.get("hardRollback") or {}).get("hardBlockers", []),
        },
        "sourceDecision": decision,
        "safety": HARD_SAFETY,
    }
    if write:
        out = runtime_dir / "agent"
        out.mkdir(parents=True, exist_ok=True)
        (out / "QuantGod_AutonomousConfigPatch.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (runtime_dir / "QuantGod_AutonomousConfigPatch_EA.txt").write_text(_build_ea_runtime_patch_text(payload), encoding="utf-8")
    return payload
