from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from .personality_lock import personality_lock_report


def crossover_seed(left: Dict[str, Any], right: Dict[str, Any], seed_id: str, generation: int, offset: int) -> Dict[str, Any] | None:
    """Cross over only seeds from the same strategy family."""
    if left.get("strategyFamily") != right.get("strategyFamily"):
        return None
    seed = deepcopy(left)
    seed["seedId"] = seed_id
    seed["source"] = "CROSSOVER"
    seed["parentSeedIds"] = [left.get("seedId"), right.get("seedId")]
    seed["strategyId"] = f"{left.get('strategyId', 'USDJPY_STRATEGY')}_CROSS_{generation:03d}_{offset:03d}"
    seed["exit"] = deepcopy(right.get("exit") or left.get("exit") or {})
    left_rsi = ((left.get("indicators") or {}).get("rsi") or {})
    right_rsi = ((right.get("indicators") or {}).get("rsi") or {})
    seed.setdefault("indicators", {})["rsi"] = {
        **left_rsi,
        "crossbackThreshold": right_rsi.get("crossbackThreshold", left_rsi.get("crossbackThreshold", 0.8)),
    }
    seed.setdefault("risk", {})["stage"] = "SHADOW"
    seed["risk"]["maxLot"] = min(2.0, float(seed["risk"].get("maxLot", 2.0)))
    seed["personalityLockAudit"] = personality_lock_report(left, seed)
    return seed
