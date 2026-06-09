"""Build GA Factory state from Strategy JSON GA outputs."""

from __future__ import annotations

from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
)

try:
    from tools.strategy_ga.schema import (
        CANDIDATE_RUNS_FILE,
        ELITE_FILE,
        LINEAGE_FILE,
        STATUS_FILE,
        ga_dir,
        utc_now_iso,
    )
except ModuleNotFoundError:  # pragma: no cover
    from strategy_ga.schema import (
        CANDIDATE_RUNS_FILE,
        ELITE_FILE,
        LINEAGE_FILE,
        STATUS_FILE,
        ga_dir,
        utc_now_iso,
    )

from .archive import (
    append_ledger_row,
    latest_by_key,
    load_json,
    read_jsonl,
    write_json,
)
from .schema import (
    AGENT_VERSION,
    ALLOWED_PROMOTION_STAGES,
    SAFETY,
    SCHEMA_ELITE_ARCHIVE,
    SCHEMA_FACTORY_STATE,
    SCHEMA_GRAVEYARD,
    SCHEMA_LINEAGE_TREE,
    SCHEMA_REFLECTION_REPORT,
    elite_archive_path,
    graveyard_path,
    intent_plan_path,
    ledger_path,
    lineage_tree_path,
    reflection_report_path,
    state_path,
)


def build_factory_state(runtime_dir: Path, *, write: bool = True) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    status = load_json(ga_dir(runtime_dir) / STATUS_FILE)
    candidates = latest_by_key(read_jsonl(ga_dir(runtime_dir) / CANDIDATE_RUNS_FILE), "seedId")
    elite_archive = _elite_archive(runtime_dir, candidates)
    graveyard = _graveyard(candidates)
    lineage_tree = _lineage_tree(runtime_dir, candidates)
    reflection_report = _reflection_report(status, candidates, elite_archive, graveyard)
    generated_at = utc_now_iso()
    factory_status = _factory_status(status, candidates)
    state: Dict[str, Any] = {
        "ok": True,
        "schema": SCHEMA_FACTORY_STATE,
        "agentVersion": AGENT_VERSION,
        "generatedAt": generated_at,
        "status": factory_status,
        "statusZh": _status_zh(factory_status),
        "currentGeneration": status.get("currentGeneration", 0),
        "candidateCount": len(candidates),
        "eliteCount": elite_archive["eliteCount"],
        "graveyardCount": graveyard["graveyardCount"],
        "lineageNodeCount": lineage_tree["nodeCount"],
        "lineageEdgeCount": lineage_tree["edgeCount"],
        "allowedPromotionStages": ALLOWED_PROMOTION_STAGES,
        "nextGeneration": _next_generation(status, elite_archive, graveyard),
        "evolutionLockPolicy": _evolution_lock_policy(),
        "reflectionReport": reflection_report,
        "archiveFiles": {
            "state": str(state_path(runtime_dir)),
            "eliteArchive": str(elite_archive_path(runtime_dir)),
            "graveyard": str(graveyard_path(runtime_dir)),
            "lineageTree": str(lineage_tree_path(runtime_dir)),
            "ledger": str(ledger_path(runtime_dir)),
            "intentPlan": str(intent_plan_path(runtime_dir)),
            "reflectionReport": str(reflection_report_path(runtime_dir)),
        },
        "eliteArchive": elite_archive,
        "graveyard": graveyard,
        "lineageTree": lineage_tree,
        "safety": dict(SAFETY),
    }
    if write:
        write_json(state_path(runtime_dir), state)
        write_json(elite_archive_path(runtime_dir), elite_archive)
        write_json(graveyard_path(runtime_dir), graveyard)
        write_json(lineage_tree_path(runtime_dir), lineage_tree)
        write_json(reflection_report_path(runtime_dir), reflection_report)
        append_ledger_row(
            ledger_path(runtime_dir),
            {
                "generatedAt": generated_at,
                "status": factory_status,
                "currentGeneration": state["currentGeneration"],
                "candidateCount": state["candidateCount"],
                "eliteCount": state["eliteCount"],
                "graveyardCount": state["graveyardCount"],
                "lineageNodeCount": state["lineageNodeCount"],
                "nextGenerationStatus": state["nextGeneration"]["status"],
            },
            [
                "generatedAt",
                "status",
                "currentGeneration",
                "candidateCount",
                "eliteCount",
                "graveyardCount",
                "lineageNodeCount",
                "nextGenerationStatus",
            ],
        )
    return state


def read_factory_state(runtime_dir: Path) -> Dict[str, Any]:
    payload = load_json(state_path(Path(runtime_dir)))
    if payload:
        return {"ok": True, **payload}
    return {
        "ok": True,
        "schema": SCHEMA_FACTORY_STATE,
        "agentVersion": AGENT_VERSION,
        "status": "WAITING_GA_FACTORY_BUILD",
        "statusZh": "等待 GA Factory 归档",
        "candidateCount": 0,
        "eliteCount": 0,
        "graveyardCount": 0,
        "lineageNodeCount": 0,
        "nextGeneration": {
            "status": "WAITING_GA_TRACE",
            "reasonZh": "先运行 Strategy JSON GA generation，再构建 GA Factory。",
        },
        "evolutionLockPolicy": _evolution_lock_policy(),
        "reflectionReport": _reflection_report({}, [], {"eliteCount": 0}, {"graveyardCount": 0}),
        "safety": dict(SAFETY),
    }


def _evolution_lock_policy() -> Dict[str, Any]:
    return {
        "schema": "quantgod.strategy_ga_factory.evolution_lock_policy.v1",
        "personalityLocked": True,
        "lockedFields": [
            "symbol",
            "strategyFamily",
            "direction",
            "lane",
            "risk.stage",
            "risk.maxLot",
            "risk.opportunityLotMultiplier",
        ],
        "tacticalMutationBoundsPct": 30.0,
        "riskKernelMutationAllowed": False,
        "directLivePromotionAllowed": False,
        "reasonZh": "GA Factory 归档和下一代生成必须保留策略性格；只允许战术参数小步变异。",
    }


def _elite_archive(runtime_dir: Path, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    elite_file = load_json(ga_dir(runtime_dir) / ELITE_FILE)
    raw_elites = elite_file.get("elites") if isinstance(elite_file.get("elites"), list) else []
    elites = [row for row in candidates if str(row.get("status") or "") == "ELITE_SELECTED"]
    if not elites:
        elites = [row for row in raw_elites if isinstance(row, dict)]
    rows = sorted((_candidate_summary(row) for row in elites), key=_elite_sort_key)
    return {
        "ok": True,
        "schema": SCHEMA_ELITE_ARCHIVE,
        "agentVersion": AGENT_VERSION,
        "generatedAt": utc_now_iso(),
        "eliteCount": len(rows),
        "elites": rows[:32],
        "reasonZh": (
            f"已归档 {len(rows)} 个 elite Strategy JSON。"
            if rows
            else "暂无 elite；下一代应扩大搜索并继续吸收 Case Memory seed。"
        ),
        "safety": dict(SAFETY),
    }


def _graveyard(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    blocked = [
        row
        for row in candidates
        if str(row.get("status") or "") in {"REJECTED", "SAFETY_REJECTED"}
        or bool(row.get("blockerCode"))
    ]
    rows = sorted((_candidate_summary(row) for row in blocked), key=_graveyard_sort_key)
    return {
        "ok": True,
        "schema": SCHEMA_GRAVEYARD,
        "agentVersion": AGENT_VERSION,
        "generatedAt": utc_now_iso(),
        "graveyardCount": len(rows),
        "strategies": rows[:256],
        "reasonZh": (
            f"{len(rows)} 个候选进入 Strategy Graveyard，防止下一代重复踩同一类 blocker。"
            if rows
            else "暂无硬阻断候选进入墓园。"
        ),
        "safety": dict(SAFETY),
    }


def _lineage_tree(runtime_dir: Path, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    lineage = load_json(ga_dir(runtime_dir) / LINEAGE_FILE)
    nodes = lineage.get("nodes") if isinstance(lineage.get("nodes"), list) else []
    edges = lineage.get("edges") if isinstance(lineage.get("edges"), list) else []
    if not nodes:
        nodes = [_lineage_node_from_candidate(row) for row in candidates if row.get("seedId")]
    visible_nodes = [node for node in nodes if isinstance(node, dict)]
    visible_edges = [edge for edge in edges if isinstance(edge, dict)]
    return {
        "ok": True,
        "schema": SCHEMA_LINEAGE_TREE,
        "agentVersion": AGENT_VERSION,
        "generatedAt": utc_now_iso(),
        "nodeCount": len(visible_nodes),
        "edgeCount": len(visible_edges),
        "nodes": visible_nodes[-512:],
        "edges": visible_edges[-768:],
        "reasonZh": _lineage_reason(visible_nodes, visible_edges),
        "safety": dict(SAFETY),
    }


def _reflection_report(
    status: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    elite_archive: Dict[str, Any],
    graveyard: Dict[str, Any],
) -> Dict[str, Any]:
    elites = [row for row in candidates if str(row.get("status") or "") == "ELITE_SELECTED"]
    rejected = [
        row
        for row in candidates
        if str(row.get("status") or "") in {"REJECTED", "SAFETY_REJECTED"}
        or bool(row.get("blockerCode"))
    ]
    generation = int(status.get("currentGeneration") or 0) if status else 0
    segments = [
        {
            "segment": "overview",
            "status": "READY" if candidates else "WAITING_GA_TRACE",
            "summaryZh": _reflection_overview_summary(generation, candidates),
            "evidence": {
                "currentGeneration": generation,
                "candidateCount": len(candidates),
                "eliteCount": int(elite_archive.get("eliteCount") or 0),
                "graveyardCount": int(graveyard.get("graveyardCount") or 0),
            },
            "allowedMutationScope": "observe_only",
        },
        {
            "segment": "winners",
            "status": "HAS_ELITES" if elites else "NO_ELITE_YET",
            "summaryZh": _winner_summary(elites),
            "evidence": {
                "topCandidates": [_candidate_summary(row) for row in _top_by_fitness(elites, 5)],
            },
            "allowedMutationScope": "preserve_personality_and_tune_entry_exit_thresholds",
        },
        {
            "segment": "losers",
            "status": "HAS_BLOCKERS" if rejected else "NO_BLOCKERS_YET",
            "summaryZh": _loser_summary(rejected),
            "evidence": {
                "topBlockers": [_candidate_summary(row) for row in rejected[:8]],
            },
            "allowedMutationScope": "avoid_repeated_blockers_without_changing_risk_kernel",
        },
        {
            "segment": "next_generation",
            "status": "READY" if candidates else "WAITING",
            "summaryZh": _next_reflection_summary(elites, rejected, candidates),
            "evidence": {
                "tacticalMutationBoundsPct": 30.0,
                "personalityLocked": True,
                "riskKernelMutationAllowed": False,
            },
            "allowedMutationScope": "indicators_thresholds_exit_session_windows_only",
        },
    ]
    return {
        "ok": True,
        "schema": SCHEMA_REFLECTION_REPORT,
        "agentVersion": AGENT_VERSION,
        "generatedAt": utc_now_iso(),
        "segmentCount": len(segments),
        "segments": segments,
        "rulesZh": [
            "先看整体候选分布，再看赢家和输家的细节。",
            "赢家只提炼可复用战术，不改变方向和风险内核。",
            "输家只记录 blocker 与失败类型，下一代避免重复踩坑。",
            "每轮战术参数最多按 30% 边界微调。",
        ],
        "safety": dict(SAFETY),
    }


def _reflection_overview_summary(generation: int, candidates: List[Dict[str, Any]]) -> str:
    if not candidates:
        return "还没有 GA 候选轨迹，先跑一代 Strategy JSON GA，再进入分段复盘。"
    return f"第 {generation} 代共归档 {len(candidates)} 个候选，先从整体分布判断下一代是否该扩大搜索或沿 elite 微调。"


def _winner_summary(elites: List[Dict[str, Any]]) -> str:
    if not elites:
        return "本轮还没有 elite，下一代应扩大搜索范围，同时保留性格锁和风险边界。"
    best = _top_by_fitness(elites, 1)[0]
    return (
        f"本轮 {len(elites)} 个 elite 值得复用；最佳候选 "
        f"{best.get('strategyId') or best.get('seedId')} fitness={best.get('fitness')}，"
        "只提炼入场确认、止盈止损和交易时段节奏。"
    )


def _loser_summary(rejected: List[Dict[str, Any]]) -> str:
    if not rejected:
        return "暂无硬阻断候选；下一代仍需监控回撤、陈旧行情和风控 blocker。"
    blocker_counts: Dict[str, int] = {}
    for row in rejected:
        code = str(row.get("blockerCode") or row.get("status") or "UNKNOWN")
        blocker_counts[code] = blocker_counts.get(code, 0) + 1
    dominant = sorted(blocker_counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return f"{len(rejected)} 个候选失败或被阻断，最高频 blocker 是 {dominant[0]} ({dominant[1]} 次)，下一代避免重复。"


def _next_reflection_summary(
    elites: List[Dict[str, Any]],
    rejected: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
) -> str:
    if not candidates:
        return "等待候选数据后再生成下一代复盘建议。"
    if elites:
        return "下一代可以基于 elite 做 mutation/crossover，但只能在指标、阈值、出场、时段窗口内微调。"
    if rejected:
        return "下一代先扩大搜索并避开墓园 blocker，不能为了过拟合历史而放松风险内核。"
    return "下一代继续补足候选样本，保持 personality lock 和 shadow-only 晋级路径。"


def _top_by_fitness(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: _safe_float(row.get("fitness"), -9999.0), reverse=True)[:limit]


def _candidate_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    stage = str(row.get("promotionStage") or "SHADOW")
    return {
        "seedId": row.get("seedId"),
        "strategyId": row.get("strategyId"),
        "strategyFamily": row.get("strategyFamily"),
        "direction": row.get("direction"),
        "source": row.get("source"),
        "generation": row.get("generation"),
        "generationId": row.get("generationId"),
        "fitness": row.get("fitness"),
        "rank": row.get("rank"),
        "status": row.get("status"),
        "promotionStage": stage,
        "allowedPromotionStage": stage in ALLOWED_PROMOTION_STAGES,
        "blockerCode": row.get("blockerCode"),
        "blockerZh": row.get("blockerZh"),
        "fingerprint": row.get("fingerprint"),
        "directLiveAllowed": False,
    }


def _lineage_node_from_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "seedId": row.get("seedId"),
        "strategyId": row.get("strategyId"),
        "strategyFamily": row.get("strategyFamily"),
        "source": row.get("source"),
        "generation": row.get("generation"),
        "fitness": row.get("fitness"),
        "rank": row.get("rank"),
        "status": row.get("status"),
        "promotionStage": row.get("promotionStage"),
    }


def _factory_status(status: Dict[str, Any], candidates: List[Dict[str, Any]]) -> str:
    if not status and not candidates:
        return "WAITING_GA_TRACE"
    if candidates:
        return "FACTORY_READY"
    return "WAITING_CANDIDATE_RUNS"


def _status_zh(status: str) -> str:
    if status == "FACTORY_READY":
        return "GA Factory 已归档"
    if status == "WAITING_CANDIDATE_RUNS":
        return "等待 GA candidate runs"
    return "等待 GA trace"


def _next_generation(
    status: Dict[str, Any],
    elite_archive: Dict[str, Any],
    graveyard: Dict[str, Any],
) -> Dict[str, Any]:
    elite_count = int(elite_archive.get("eliteCount") or 0)
    if elite_count > 0:
        return {
            "status": "READY_FOR_ELITE_GUIDED_NEXT_GENERATION",
            "targetGeneration": int(status.get("currentGeneration") or 0) + 1,
            "reasonZh": f"基于 {elite_count} 个 elite 继续 mutation / crossover。",
        }
    if status:
        return {
            "status": "NO_ELITE_EXPAND_SEARCH",
            "targetGeneration": int(status.get("currentGeneration") or 0) + 1,
            "reasonZh": "暂无 elite；下一代扩大参数网格并吸收 Case Memory seed，墓园 blocker 不重复尝试。",
            "graveyardCount": graveyard.get("graveyardCount", 0),
        }
    return {
        "status": "WAITING_GA_TRACE",
        "targetGeneration": 1,
        "reasonZh": "先运行第一代 Strategy JSON GA，再由工厂归档。",
    }


def _elite_sort_key(row: Dict[str, Any]) -> tuple[Any, ...]:
    rank = row.get("rank") if isinstance(row.get("rank"), int) else 9999
    fitness = _safe_float(row.get("fitness"), -9999.0)
    return (rank, -fitness, str(row.get("seedId") or ""))


def _graveyard_sort_key(row: Dict[str, Any]) -> tuple[Any, ...]:
    generation = row.get("generation") if isinstance(row.get("generation"), int) else -1
    fitness = _safe_float(row.get("fitness"), -9999.0)
    return (-generation, fitness, str(row.get("seedId") or ""))


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _lineage_reason(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> str:
    if not nodes:
        return "等待 GA lineage 生成。"
    return f"已归档 {len(nodes)} 个 lineage 节点和 {len(edges)} 条父子边。"
