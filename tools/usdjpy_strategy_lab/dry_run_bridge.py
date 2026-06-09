from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict

from .entry_context_feedback import append_entry_context_feedback
from .policy_builder import build_usdjpy_policy
from .schema import ENTRY_BLOCKED, ENTRY_OPPORTUNITY, ENTRY_STANDARD, FOCUS_SYMBOL, READ_ONLY_SAFETY, assert_no_secret_or_execution_flags, utc_now_iso


def build_dry_run_decision(runtime_dir: Path, *, write: bool = False) -> Dict[str, Any]:
    policy = build_usdjpy_policy(runtime_dir, write=write)
    top = policy.get("topLiveEligiblePolicy") or policy.get("liveRecoveryCandidate") or {}
    mode = top.get("entryMode") or ENTRY_BLOCKED
    decision = "阻断"
    if mode == ENTRY_STANDARD:
        decision = "本应标准入场"
    elif mode == ENTRY_OPPORTUNITY:
        decision = "本应机会入场"
    payload = {
        "schema": "quantgod.usdjpy_ea_dry_run_decision.v1",
        "generatedAt": utc_now_iso(),
        "focusOnly": True,
        "symbol": FOCUS_SYMBOL,
        "decision": decision,
        "entryMode": mode,
        "strategy": top.get("strategy", "UNKNOWN"),
        "direction": top.get("direction", "UNKNOWN"),
        "recommendedLot": top.get("recommendedLot", 0.0),
        "maxLot": top.get("maxLot", policy.get("maxLot", 2.0)),
        "reasons": top.get("reasons", []) or ["没有可用 USDJPY 策略政策"],
        "policy": top,
        "topShadowPolicy": policy.get("topShadowPolicy"),
        "topLiveEligiblePolicy": policy.get("topLiveEligiblePolicy"),
        "safety": dict(READ_ONLY_SAFETY),
    }
    if write:
        payload["entryContextFeedback"] = append_entry_context_feedback(
            runtime_dir,
            policy=policy,
            top_policy=top,
            generated_at=payload["generatedAt"],
            event_type="DRY_RUN_ENTRY_CONTEXT",
            source_name="QuantGod_USDJPYEADryRunDecision.json",
        )
    assert_no_secret_or_execution_flags(payload)
    if write:
        adaptive_dir = runtime_dir / "adaptive"
        adaptive_dir.mkdir(parents=True, exist_ok=True)
        (adaptive_dir / "QuantGod_USDJPYEADryRunDecision.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        ledger = adaptive_dir / "QuantGod_USDJPYEADryRunDecisionLedger.csv"
        is_new = not ledger.exists()
        with ledger.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["generatedAt", "symbol", "decision", "entryMode", "strategy", "direction", "recommendedLot", "reason"])
            if is_new:
                writer.writeheader()
            writer.writerow({
                "generatedAt": payload["generatedAt"],
                "symbol": FOCUS_SYMBOL,
                "decision": decision,
                "entryMode": mode,
                "strategy": payload["strategy"],
                "direction": payload["direction"],
                "recommendedLot": payload["recommendedLot"],
                "reason": "；".join(payload.get("reasons", [])[:3]),
            })
    return payload
