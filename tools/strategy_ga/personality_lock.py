from __future__ import annotations

from typing import Any, Dict, List


SCHEMA_VERSION = "quantgod.strategy_ga.personality_lock.v1"

LOCKED_PERSONALITY_PATHS = [
    "symbol",
    "strategyFamily",
    "direction",
    "lane",
    "risk.stage",
    "risk.maxLot",
    "risk.opportunityLotMultiplier",
    "safety.orderSendAllowed",
    "safety.closeAllowed",
    "safety.cancelAllowed",
    "safety.livePresetMutationAllowed",
    "safety.gaDirectLiveAllowed",
]

TACTICAL_MUTATION_BOUNDS_PCT = 30.0


def _get_path(payload: Dict[str, Any], path: str) -> Any:
    node: Any = payload
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def build_personality_lock(seed: Dict[str, Any]) -> Dict[str, Any]:
    values = {path: _get_path(seed, path) for path in LOCKED_PERSONALITY_PATHS}
    return {
        "schema": SCHEMA_VERSION,
        "locked": True,
        "lockedPaths": list(LOCKED_PERSONALITY_PATHS),
        "lockedValues": values,
        "tacticalMutationBoundsPct": TACTICAL_MUTATION_BOUNDS_PCT,
        "mutableFamilies": [
            "indicators",
            "entry.conditions",
            "entry.eventFilter",
            "exit",
        ],
        "reasonZh": "锁死方向、策略族、车道和风险内核；进化只能微调战术参数，避免为历史收益改性格。",
    }


def personality_lock_report(parent: Dict[str, Any], child: Dict[str, Any]) -> Dict[str, Any]:
    violations: List[Dict[str, Any]] = []
    for path in LOCKED_PERSONALITY_PATHS:
        before = _get_path(parent, path)
        after = _get_path(child, path)
        if before != after:
            violations.append({
                "path": path,
                "parent": before,
                "child": after,
                "reasonZh": "性格锁字段发生变化。",
            })
    return {
        "schema": SCHEMA_VERSION,
        "locked": True,
        "passed": not violations,
        "violationCount": len(violations),
        "violations": violations,
        "tacticalMutationBoundsPct": TACTICAL_MUTATION_BOUNDS_PCT,
        "reasonZh": (
            "性格锁通过：本轮只允许战术参数微调。"
            if not violations
            else "性格锁未通过：候选改变了方向、策略族、车道或风险内核。"
        ),
    }
