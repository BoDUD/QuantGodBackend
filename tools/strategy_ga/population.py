from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from .crossover import crossover_seed
from .mutation import mutate_seed
from .schema import (
    CANDIDATE_RUNS_FILE,
    DEFAULT_ELITE_COUNT,
    DEFAULT_POPULATION_SIZE,
    EVOLUTION_PATH_FILE,
    GENERATION_LEDGER_FILE,
    ga_dir,
)
from .seed_generator import (
    case_memory_seed_pool,
    exploration_seed_pool,
    initial_seed_pool,
    quality_repair_seed_pool,
)

try:
    from tools.strategy_json.fingerprint import strategy_fingerprint
    from tools.strategy_json.normalizer import normalize_strategy_json
except ModuleNotFoundError:  # pragma: no cover
    from strategy_json.fingerprint import strategy_fingerprint
    from strategy_json.normalizer import normalize_strategy_json

_VOLATILE_SEED_FIELDS = {
    "seedId",
    "strategyId",
    "source",
    "parentSeedId",
    "parentFitness",
    "explorationMode",
    "explorationReasonZh",
    "repairReasonZh",
    "repairTargetBlocker",
    "personalityLockAudit",
}


def population_size() -> int:
    try:
        return max(4, min(64, int(os.environ.get("QG_GA_POPULATION_SIZE", DEFAULT_POPULATION_SIZE))))
    except Exception:
        return DEFAULT_POPULATION_SIZE


def elite_count() -> int:
    try:
        return max(1, min(8, int(os.environ.get("QG_GA_ELITE_COUNT", DEFAULT_ELITE_COUNT))))
    except Exception:
        return DEFAULT_ELITE_COUNT


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _recent_rejected_seeds(runtime_dir: Path | None, limit: int = 4) -> List[Dict[str, Any]]:
    if runtime_dir is None:
        return []
    candidate_file = ga_dir(runtime_dir) / CANDIDATE_RUNS_FILE
    if not candidate_file.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in candidate_file.read_text(encoding="utf-8").splitlines()[-256:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        seed = row.get("strategyJson") if isinstance(row.get("strategyJson"), dict) else {}
        if not seed:
            continue
        blocker = str(row.get("blockerCode") or "")
        if blocker in {"SAFETY_REJECTED", "DUPLICATE_STRATEGY", "HISTORY_PRODUCTION_NOT_READY"}:
            continue
        rows.append(row)
    rows.sort(key=_mutation_parent_sort_key)
    seeds: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        seed = row.get("strategyJson")
        seed_id = str(seed.get("seedId") or "")
        if seed_id in seen:
            continue
        seen.add(seed_id)
        seeds.append(seed)
        if len(seeds) >= limit:
            break
    return seeds


def _recent_promoted_shadow_seeds(runtime_dir: Path | None, limit: int = 4) -> List[Dict[str, Any]]:
    if runtime_dir is None:
        return []
    candidate_file = ga_dir(runtime_dir) / CANDIDATE_RUNS_FILE
    if not candidate_file.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in candidate_file.read_text(encoding="utf-8").splitlines()[-512:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        seed = row.get("strategyJson") if isinstance(row.get("strategyJson"), dict) else {}
        if not seed:
            continue
        status = str(row.get("status") or "").upper()
        stage = str(row.get("promotionStage") or "").upper()
        if status != "PROMOTED_TO_SHADOW" and stage != "FAST_SHADOW":
            continue
        if row.get("blockerCode"):
            continue
        rows.append(row)
    rows.sort(key=lambda row: (-_num(row.get("fitness"), -999.0), int(_num(row.get("rank"), 9999))))
    seeds: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        seed = row.get("strategyJson")
        seed_id = str(seed.get("seedId") or "")
        if seed_id in seen:
            continue
        seen.add(seed_id)
        seeds.append(seed)
        if len(seeds) >= limit:
            break
    return seeds


def _elite_guided_plateau_active(runtime_dir: Path | None, window: int = 4) -> bool:
    return _elite_guided_plateau_streak(runtime_dir, window) >= window


def _elite_guided_plateau_streak(runtime_dir: Path | None, window: int = 4) -> int:
    if runtime_dir is None:
        return 0
    path_file = ga_dir(runtime_dir) / EVOLUTION_PATH_FILE
    if not path_file.exists():
        return 0
    try:
        payload = json.loads(path_file.read_text(encoding="utf-8"))
    except Exception:
        return 0
    generations = payload.get("generations") if isinstance(payload.get("generations"), list) else []
    if not generations:
        return 0
    last_strategy = str(generations[-1].get("bestStrategy") or "")
    last_fitness = round(_num(generations[-1].get("bestFitness"), -999.0), 4)
    if not last_strategy:
        return 0
    streak = 0
    for row in reversed(generations):
        if str(row.get("bestStrategy") or "") != last_strategy:
            break
        if round(_num(row.get("bestFitness"), -999.0), 4) != last_fitness:
            break
        streak += 1
    return streak


def _last_generation_regressed(runtime_dir: Path | None) -> bool:
    if runtime_dir is None:
        return False
    path_file = ga_dir(runtime_dir) / EVOLUTION_PATH_FILE
    if not path_file.exists():
        return False
    try:
        payload = json.loads(path_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    generations = payload.get("generations") if isinstance(payload.get("generations"), list) else []
    if len(generations) < 2:
        return False
    previous = generations[-2]
    latest = generations[-1]
    previous_avg = _num(previous.get("avgFitness"), -999.0)
    latest_avg = _num(latest.get("avgFitness"), -999.0)
    previous_blocked = int(_num(previous.get("blockedCount"), 0))
    latest_blocked = int(_num(latest.get("blockedCount"), 0))
    return (
        latest_avg < previous_avg - 1.0
        or latest_blocked > previous_blocked + 1
        or _last_generation_walk_forward_regressed(runtime_dir)
    )


def _last_generation_walk_forward_regressed(runtime_dir: Path | None) -> bool:
    if runtime_dir is None:
        return False
    ledger_file = ga_dir(runtime_dir) / GENERATION_LEDGER_FILE
    if not ledger_file.exists():
        return False
    rows: List[Dict[str, Any]] = []
    for line in ledger_file.read_text(encoding="utf-8").splitlines()[-8:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict) and isinstance(row.get("walkForward"), dict):
            rows.append(row)
    if len(rows) < 2:
        return False
    previous = rows[-2].get("walkForward") or {}
    latest = rows[-1].get("walkForward") or {}
    previous_stability = _num(previous.get("avgStabilityScore"), 0.0)
    latest_stability = _num(latest.get("avgStabilityScore"), 0.0)
    previous_passed = int(_num(previous.get("passedCount"), 0))
    latest_passed = int(_num(latest.get("passedCount"), 0))
    previous_blocked = int(_num(previous.get("blockedCount"), 0))
    latest_blocked = int(_num(latest.get("blockedCount"), 0))
    return (
        latest_stability < previous_stability - 0.12
        or latest_passed < previous_passed - 2
        or latest_blocked > previous_blocked + 2
    )


def _canonical_seed_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical_seed_value(child)
            for key, child in sorted(value.items())
            if key not in _VOLATILE_SEED_FIELDS
        }
    if isinstance(value, list):
        return [_canonical_seed_value(child) for child in value]
    return value


def _strategy_content_key(seed: Dict[str, Any]) -> str:
    try:
        normalized = normalize_strategy_json(seed)
        return f"normalized:{strategy_fingerprint(normalized)}"
    except Exception:
        return f"raw:{json.dumps(_canonical_seed_value(seed), sort_keys=True, default=str)}"


def _dedupe_strategy_content(seeds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for seed in seeds:
        key = _strategy_content_key(seed)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(seed)
    return deduped


def _append_unique(population: List[Dict[str, Any]], seeds: List[Dict[str, Any]], limit: int) -> None:
    seen = {_strategy_content_key(seed) for seed in population}
    for seed in seeds:
        if len(population) >= limit:
            break
        key = _strategy_content_key(seed)
        if key in seen:
            continue
        seen.add(key)
        population.append(seed)


def _seed_family(seed: Dict[str, Any]) -> str:
    return str(seed.get("strategyFamily") or "")


def _recent_family_outcomes(runtime_dir: Path | None, window_generations: int = 6) -> Dict[str, Dict[str, int]]:
    if runtime_dir is None:
        return {}
    candidate_file = ga_dir(runtime_dir) / CANDIDATE_RUNS_FILE
    if not candidate_file.exists():
        return {}
    rows: List[Dict[str, Any]] = []
    for line in candidate_file.read_text(encoding="utf-8").splitlines()[-1024:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    latest_generation = max((int(_num(row.get("generation"), 0)) for row in rows), default=0)
    min_generation = max(0, latest_generation - window_generations + 1)
    outcomes: Dict[str, Dict[str, int]] = {}
    for row in rows:
        generation = int(_num(row.get("generation"), 0))
        if latest_generation and generation < min_generation:
            continue
        seed = row.get("strategyJson") if isinstance(row.get("strategyJson"), dict) else {}
        family = str(seed.get("strategyFamily") or row.get("strategyFamily") or "")
        if not family:
            continue
        bucket = outcomes.setdefault(family, {"pass": 0, "unstable": 0, "rejected": 0})
        blocker = str(row.get("blockerCode") or "")
        status = str(row.get("status") or "").upper()
        if not blocker and status in {"ELITE_SELECTED", "PROMOTED_TO_SHADOW"}:
            bucket["pass"] += 1
        if blocker == "WALK_FORWARD_UNSTABLE":
            bucket["unstable"] += 1
        if blocker:
            bucket["rejected"] += 1
    return outcomes


def _deep_plateau_suppresses_family(family: str, outcomes: Dict[str, Dict[str, int]]) -> bool:
    if family == "RSI_Reversal":
        return False
    stats = outcomes.get(family) or {}
    return int(stats.get("unstable", 0)) >= 4 and int(stats.get("pass", 0)) == 0


def _filter_deep_plateau_seeds(
    seeds: List[Dict[str, Any]],
    runtime_dir: Path | None,
) -> List[Dict[str, Any]]:
    outcomes = _recent_family_outcomes(runtime_dir)
    if not outcomes:
        return seeds
    filtered: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []
    for seed in seeds:
        family = _seed_family(seed)
        if _deep_plateau_suppresses_family(family, outcomes):
            seed["explorationSuppressedByRecentBlockers"] = True
            seed["explorationSuppressionReasonZh"] = (
                "深平台期最近多代该家族连续 walk-forward 不稳定且没有通过候选，先降低投放优先级。"
            )
            suppressed.append(seed)
            continue
        filtered.append(seed)
    return filtered or suppressed[:1] or seeds


def _mutation_parent_sort_key(row: Dict[str, Any]) -> tuple:
    seed = row.get("strategyJson") if isinstance(row.get("strategyJson"), dict) else {}
    breakdown = row.get("fitnessBreakdown") if isinstance(row.get("fitnessBreakdown"), dict) else {}
    backtest = breakdown.get("strategyBacktest") if isinstance(breakdown.get("strategyBacktest"), dict) else {}
    blocker = str(row.get("blockerCode") or "")
    family = str(seed.get("strategyFamily") or row.get("strategyFamily") or "")
    direction = str(seed.get("direction") or row.get("direction") or "").upper()
    sample_count = int(_num(breakdown.get("sampleCount"), 0))
    trade_count = int(_num(backtest.get("tradeCount"), 0))
    quality_penalty = 0
    if blocker == "STRATEGY_BACKTEST_NO_TRADES" or trade_count == 0:
        quality_penalty += 10
    if blocker == "INSUFFICIENT_SAMPLES" or sample_count < 5 or trade_count < 5:
        quality_penalty += 5
    if family == "BB_Triple" and direction == "SHORT" and quality_penalty:
        quality_penalty += 10
    if family == "RSI_Reversal" and blocker in {"OVERFIT_RISK", "OVERFIT_RISK_HIGH", "RSI_MIN_TRADE_GATE"}:
        if max(sample_count, trade_count) < 20:
            quality_penalty += 18
        elif max(sample_count, trade_count) < 24:
            quality_penalty += 7
    rsi_focus_penalty = 0 if _is_p4_10d_rsi_parent(family, blocker, sample_count, trade_count) else 8
    return (
        rsi_focus_penalty,
        quality_penalty,
        int(_num(row.get("rank"), 9999)),
        -_num(row.get("fitness"), -999.0),
    )


def _is_p4_10d_rsi_parent(family: str, blocker: str, sample_count: int, trade_count: int) -> bool:
    if family != "RSI_Reversal":
        return False
    if blocker not in {
        "OVERFIT_RISK",
        "OVERFIT_RISK_HIGH",
        "RSI_MIN_TRADE_GATE",
        "WALK_FORWARD_UNSTABLE",
        "WALK_FORWARD_INSUFFICIENT",
    }:
        return False
    return max(sample_count, trade_count) >= 20


def build_population(generation_number: int, previous_elites: List[Dict[str, Any]] | None = None, runtime_dir: Path | None = None) -> List[Dict[str, Any]]:
    size = population_size()
    case_seeds = case_memory_seed_pool(runtime_dir) if runtime_dir is not None else []
    if generation_number <= 1 or not previous_elites:
        if generation_number <= 1:
            population: List[Dict[str, Any]] = []
            _append_unique(population, case_seeds + initial_seed_pool(size), size)
            return population[:size]
        population: List[Dict[str, Any]] = []
        _append_unique(population, case_seeds[: max(1, size // 4)], size)
        quality_seeds = (
            quality_repair_seed_pool(runtime_dir, generation_number, limit=max(2, size // 2))
            if runtime_dir is not None
            else []
        )
        _append_unique(population, quality_seeds[: max(0, size - len(population))], size)
        offset = 1
        for parent in _recent_rejected_seeds(runtime_dir, limit=max(2, size // 4)):
            if len(population) >= size:
                break
            seed_id = f"GA-USDJPY-G{generation_number:04d}-RM{offset:04d}"
            mutated = mutate_seed(parent, seed_id, generation_number, offset)
            mutated["source"] = "EXPLORATION_MUTATION"
            mutated["explorationMode"] = "NO_ELITE_EXPAND_SEARCH"
            mutated["explorationReasonZh"] = "上一代没有 elite，基于最佳 rejected seed 做受控参数变异。"
            _append_unique(population, [mutated], size)
            offset += 1
        _append_unique(population, exploration_seed_pool(generation_number, max(0, size - len(population))), size)
        return population[:size]
    population: List[Dict[str, Any]] = []
    elites = _dedupe_strategy_content([row.get("strategyJson") for row in previous_elites if isinstance(row.get("strategyJson"), dict)])
    plateau_streak = _elite_guided_plateau_streak(runtime_dir)
    plateau_active = plateau_streak >= 4
    deep_plateau_active = plateau_streak >= 8
    plateau_recovery_active = deep_plateau_active and _last_generation_regressed(runtime_dir)
    elite_keep = elite_count()
    if deep_plateau_active:
        elite_keep = max(1, elite_count() // 2)
    if plateau_recovery_active:
        elite_keep = max(2, elite_keep)
    _append_unique(population, elites[: elite_keep], size)
    case_limit = 0 if deep_plateau_active else (max(1, size // 8) if plateau_active else max(0, size - len(population)))
    _append_unique(population, case_seeds[: min(case_limit, max(0, size - len(population)))], size)
    if plateau_active:
        if plateau_recovery_active:
            quality_limit = max(2, size // 4)
        else:
            quality_limit = max(3, size // 4) if deep_plateau_active else max(2, size // 4)
        quality_seeds = (
            quality_repair_seed_pool(runtime_dir, generation_number, limit=quality_limit)
            if runtime_dir is not None
            else []
        )
        if deep_plateau_active:
            quality_seeds = _filter_deep_plateau_seeds(quality_seeds, runtime_dir)
        for seed in quality_seeds:
            seed["explorationMode"] = "ELITE_PLATEAU_DIVERSIFY"
            seed["explorationReasonZh"] = (
                "最近一代候选质量回落，深平台期进入恢复模式：减少宽探索，优先修复近期稳定 family。"
                if plateau_recovery_active
                else (
                    "最近多代冠军未变化，深平台期提高质量修复占比，并避开近期反复 walk-forward 不稳定的家族。"
                    if deep_plateau_active
                    else "最近多代冠军未变化，平台期注入质量修复 seed 扩大搜索。"
                )
            )
        _append_unique(population, quality_seeds, size)
        promoted_offset = 1
        promoted_limit = max(3, size // 3) if plateau_recovery_active else (max(2, size // 4) if deep_plateau_active else max(1, size // 8))
        for parent in _recent_promoted_shadow_seeds(runtime_dir, limit=promoted_limit):
            if len(population) >= size:
                break
            seed_id = f"GA-USDJPY-G{generation_number:04d}-PS{promoted_offset:04d}"
            mutated = mutate_seed(parent, seed_id, generation_number, 100 + promoted_offset)
            mutated["source"] = "PLATEAU_SHADOW_MUTATION"
            mutated["explorationMode"] = "ELITE_PLATEAU_DIVERSIFY"
            mutated["explorationReasonZh"] = (
                "最近一代候选质量回落，深平台期优先沿 FAST_SHADOW 做恢复变异。"
                if plateau_recovery_active
                else (
                    "最近多代冠军未变化，深平台期沿更多 FAST_SHADOW 候选做受控变异。"
                    if deep_plateau_active
                    else "最近多代冠军未变化，沿 FAST_SHADOW 候选继续受控变异。"
                )
            )
            _append_unique(population, [mutated], size)
            promoted_offset += 1
        exploration_count = 1 if deep_plateau_active else max(2, size // 4)
        exploration_seeds = exploration_seed_pool(generation_number, exploration_count)
        if deep_plateau_active:
            exploration_seeds = _filter_deep_plateau_seeds(exploration_seeds, runtime_dir)
        for seed in exploration_seeds:
            seed["source"] = "EXPLORATION_PLATEAU"
            seed["explorationMode"] = "ELITE_PLATEAU_DIVERSIFY"
            seed["explorationReasonZh"] = (
                "最近一代候选质量回落，深平台期只保留少量参数网格探针。"
                if plateau_recovery_active
                else (
                    "最近多代冠军未变化，深平台期扩大参数网格 seed，同时避开近期反复 walk-forward 不稳定的家族。"
                    if deep_plateau_active
                    else "最近多代冠军未变化，平台期注入参数网格 seed 避免重复 elite crossover。"
                )
            )
        _append_unique(population, exploration_seeds, size)
    offset = 1
    attempts = 0
    max_attempts = max(size * 8, len(elites) * 4)
    while len(population) < size and elites and attempts < max_attempts:
        attempts += 1
        parent = elites[(offset - 1) % len(elites)]
        seed_id = f"GA-USDJPY-G{generation_number:04d}-M{offset:04d}"
        _append_unique(population, [mutate_seed(parent, seed_id, generation_number, offset)], size)
        offset += 1
        if len(elites) > 1 and len(population) < size:
            left = elites[(offset - 2) % len(elites)]
            right = elites[(offset - 1) % len(elites)]
            crossed = crossover_seed(left, right, f"GA-USDJPY-G{generation_number:04d}-C{offset:04d}", generation_number, offset)
            if crossed:
                _append_unique(population, [crossed], size)
            offset += 1
    if len(population) < size:
        _append_unique(population, initial_seed_pool(size - len(population)), size)
    return population[:size]
