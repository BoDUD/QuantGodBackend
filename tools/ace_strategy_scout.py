"""Read-only scout report for stable QuantGod strategy candidates.

This module compares existing shadow/research evidence across lanes and writes a
compact ranking report. It never writes MT5 order requests or live presets.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "quantgod.ace_strategy_scout.report.v1"
REPORT_PATH = Path("agent") / "QuantGod_AceStrategyScout.json"
BTC_SCAN_REPORT_PATH = Path("agent") / "QuantGod_BtcStrategyScanReport.json"
CHAMPION_RETEST_REPORT_PATH = Path("agent") / "QuantGod_ChampionRetestReport.json"
CHAMPION_TESTER_RUN_GATE_PATH = Path("agent") / "QuantGod_ChampionTesterRunGate.json"
LIVE_EVIDENCE_INTAKE_PATH = Path("agent") / "QuantGod_LiveEvidenceIntake.json"


SAFETY = {
    "readOnly": True,
    "shadowOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "livePresetMutationAllowed": False,
    "walletAuthorizationAllowed": False,
    "hyperliquidExecutionAllowed": False,
    "mossExecutionAllowed": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _artifact_generated_at(path: Path, payload: dict[str, Any]) -> datetime | None:
    parsed = _parse_iso(payload.get("generatedAtIso")) or _parse_iso(payload.get("generatedAt"))
    if parsed is not None:
        return parsed.astimezone(timezone.utc)
    if path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return None


def _ensure_fresh_champion_retest(runtime_dir: Path) -> dict[str, Any]:
    scan_path = runtime_dir / BTC_SCAN_REPORT_PATH
    retest_path = runtime_dir / CHAMPION_RETEST_REPORT_PATH
    scan = _read_json(scan_path)
    retest = _read_json(retest_path)
    scan_time = _artifact_generated_at(scan_path, scan)
    retest_time = _artifact_generated_at(retest_path, retest)
    if scan_time and (not retest or retest_time is None or retest_time < scan_time):
        try:
            from tools.champion_retest import build_champion_retest_report
        except ModuleNotFoundError:  # pragma: no cover
            from champion_retest import build_champion_retest_report
        build_champion_retest_report(runtime_dir, write=True)
        retest = _read_json(retest_path)
    return retest


def _saved_scout_stale(runtime_dir: Path, payload: dict[str, Any]) -> bool:
    report_path = runtime_dir / REPORT_PATH
    report_time = _artifact_generated_at(report_path, payload)
    if report_time is None:
        return True
    dependency_paths = [
        runtime_dir / BTC_SCAN_REPORT_PATH,
        runtime_dir / CHAMPION_RETEST_REPORT_PATH,
        runtime_dir / "ga_factory" / "QuantGod_GAEliteArchive.json",
        runtime_dir / "ga" / "QuantGod_GAEliteStrategies.json",
        runtime_dir / "agent" / "QuantGod_ForexLive12RsiCandidatePromotionGate.json",
    ]
    for dependency_path in dependency_paths:
        dependency_payload = _read_json(dependency_path)
        dependency_time = _artifact_generated_at(dependency_path, dependency_payload)
        if dependency_time and dependency_time > report_time:
            return True
    return False


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace("%", "")
        try:
            return float(stripped)
        except ValueError:
            return default
    return default


def _stable_score(*, pnl: float, roi: float, sharpe: float, drawdown: float, trades: float, stability: float = 0.0) -> float:
    sample_bonus = math.log10(max(trades, 1.0)) * 1.2
    return round(
        (max(pnl, 0.0) / 20.0)
        + (max(roi, 0.0) / 3.0)
        + (max(sharpe, 0.0) * 2.0)
        + sample_bonus
        + (max(stability, 0.0) * 3.0)
        - (max(drawdown, 0.0) / 2.0),
        4,
    )


def _crypto_retest_stability_bonus(candidate_retest: dict[str, Any]) -> float:
    if not candidate_retest:
        return 0.0
    valid_windows = _num(candidate_retest.get("validWindowCount"))
    positive_windows = _num(candidate_retest.get("positiveWindowCount"))
    positive_major_windows = _num(candidate_retest.get("positiveMajorWindowCount"))
    negative_windows = _num(candidate_retest.get("negativeWindowCount"))
    major_failures = _num(candidate_retest.get("majorWindowFailureCount"))
    pass_bonus = 8.0 if candidate_retest.get("status") == "BTC_CHAMPION_RETEST_PASS" else 0.0
    return round(
        pass_bonus
        + valid_windows * 2.4
        + positive_windows * 0.8
        + positive_major_windows * 1.2
        - negative_windows * 6.0
        - major_failures * 9.0,
        4,
    )


def _effective_ga_sample_count(backtest: dict[str, Any], wf_summary: dict[str, Any], walk_forward: dict[str, Any]) -> int:
    backtest_trades = int(_num(backtest.get("tradeCount")))
    wf_samples = int(_num(wf_summary.get("sampleCount")))
    segment_trades = sum(
        int(_num(segment.get("tradeCount")))
        for segment in walk_forward.get("segments", [])
        if isinstance(segment, dict)
    )
    return max(backtest_trades, wf_samples, segment_trades)


def _decision_for_candidate(candidate: dict[str, Any]) -> str:
    if candidate.get("lane") == "live12_raw_rsi":
        return "DISCARD_AS_ACE"
    if candidate.get("blockers"):
        return "REPAIR_OR_DISCARD"
    if candidate.get("lane") == "usdjpy_ga_elite":
        return "PRIORITIZE_FOR_TESTER_FORWARD"
    if candidate.get("lane") == "hfm_crypto_cfd_shadow":
        return "PRIORITIZE_FOR_MULTI_WINDOW_SHADOW"
    if candidate.get("liveUnsafeReason"):
        return "KEEP_SHADOW_RESEARCH"
    return "PRIORITIZE_FOR_FORWARD_VALIDATION"


def _crypto_candidates(runtime_dir: Path) -> list[dict[str, Any]]:
    state = _read_json(runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoCfdState.json")
    review = _read_json(runtime_dir / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json")
    autogen_profile = _read_json(runtime_dir / "hfm_crypto" / "hfm_crypto_simulation_profile.autogen.json")
    retest = _ensure_fresh_champion_retest(runtime_dir)
    crypto_retest = retest.get("cryptoChampion", {}) if isinstance(retest.get("cryptoChampion"), dict) else {}
    retests_by_strategy = {
        str(row.get("strategyId")): row
        for row in crypto_retest.get("candidateRetests", [])
        if isinstance(row, dict) and row.get("strategyId")
    }
    if crypto_retest.get("strategyId"):
        retests_by_strategy[str(crypto_retest.get("strategyId"))] = crypto_retest
    candidates: list[dict[str, Any]] = []
    seen_strategy_ids: set[str] = set()

    def add_metrics(source: str, metrics: dict[str, Any], qualified: bool = False, blockers: list[str] | None = None) -> None:
        if not metrics:
            return
        pnl = _num(metrics.get("pnlUsd", metrics.get("pnl", 0.0)))
        roi = _num(metrics.get("roiPct", metrics.get("roi", 0.0)))
        sharpe = _num(metrics.get("sharpe"))
        drawdown = _num(metrics.get("maxDrawdownPct", metrics.get("maxDrawdown", 0.0)))
        trades = _num(metrics.get("tradeCount"))
        liq = int(_num(metrics.get("liquidationCount")))
        blocker_codes = list(blockers or [])
        if liq > 0 and "LIQUIDATION_GT_0" not in blocker_codes:
            blocker_codes.append("LIQUIDATION_GT_0")
        if trades < 20 and "LOW_SAMPLE_LT_20" not in blocker_codes:
            blocker_codes.append("LOW_SAMPLE_LT_20")
        if sharpe < 1 and "SHARPE_LT_1" not in blocker_codes:
            blocker_codes.append("SHARPE_LT_1")
        strategy_id = metrics.get("agentId") or metrics.get("strategyId") or "hfm_crypto_shadow_candidate"
        if strategy_id in seen_strategy_ids:
            return
        seen_strategy_ids.add(str(strategy_id))
        candidate_retest = retests_by_strategy.get(str(strategy_id), {})
        retest_status = candidate_retest.get("status")
        retest_blockers: list[str] = []
        if candidate_retest:
            retest_blockers = [
                f"CHAMPION_RETEST_{item}"
                for item in candidate_retest.get("blockers", [])
                if item
            ]
            if retest_status and retest_status != "BTC_CHAMPION_RETEST_PASS":
                retest_blockers.append(f"CHAMPION_RETEST_STATUS_{retest_status}")
            for item in retest_blockers:
                if item not in blocker_codes:
                    blocker_codes.append(item)
        candidates.append(
            {
                "lane": "hfm_crypto_cfd_shadow",
                "source": source,
                "strategyId": strategy_id,
                "strategyName": metrics.get("strategyName", ""),
                "symbol": metrics.get("symbol", "BTCUSD"),
                "pnlUsd": round(pnl, 4),
                "roiPct": round(roi, 4),
                "sharpe": round(sharpe, 4),
                "maxDrawdownPct": round(drawdown, 4),
                "tradeCount": int(trades),
                "liquidationCount": liq,
                "championRetestStatus": retest_status if candidate_retest else None,
                "championRetestValidWindowCount": (
                    int(_num(candidate_retest.get("validWindowCount"))) if candidate_retest else None
                ),
                "championRetestWindowCount": (
                    int(_num(candidate_retest.get("windowCount"))) if candidate_retest else None
                ),
                "championRetestPositiveWindowCount": (
                    int(_num(candidate_retest.get("positiveWindowCount"))) if candidate_retest else None
                ),
                "championRetestNegativeWindowCount": (
                    int(_num(candidate_retest.get("negativeWindowCount"))) if candidate_retest else None
                ),
                "championRetestPositiveMajorWindowCount": (
                    int(_num(candidate_retest.get("positiveMajorWindowCount"))) if candidate_retest else None
                ),
                "championRetestMajorWindowFailureCount": (
                    int(_num(candidate_retest.get("majorWindowFailureCount"))) if candidate_retest else None
                ),
                "qualified": bool(qualified and not blocker_codes),
                "blockers": blocker_codes,
                "score": _stable_score(pnl=pnl, roi=roi, sharpe=sharpe, drawdown=drawdown, trades=trades)
                + _crypto_retest_stability_bonus(candidate_retest),
                "promotionStage": "SHADOW",
                "liveUnsafeReason": "read_only_crypto_cfd_shadow_lane",
                "safety": SAFETY,
            }
        )

    metrics = review.get("metrics") or review.get("profile", {}).get("metrics", {})
    add_metrics("simulation_profile_review", metrics, bool(review.get("simulationQualified")), review.get("blockers") or [])

    for row in state.get("ratesExportReview", {}).get("autoProfile", {}).get("autoProfileCandidates", []):
        add_metrics("rates_export_auto_profile", row.get("metrics", {}), bool(row.get("qualified")), row.get("blockerCodes") or [])

    for row in autogen_profile.get("simulation", {}).get("candidateResults", []):
        add_metrics("autogen_profile_candidate_result", row.get("metrics", {}), bool(row.get("qualified")), row.get("blockerCodes") or [])

    for row in crypto_retest.get("candidateRetests", []):
        if not isinstance(row, dict):
            continue
        metrics = row.get("fullWindowMetrics", {})
        if isinstance(metrics, dict):
            add_metrics("champion_retest_candidate_matrix", metrics, row.get("status") == "BTC_CHAMPION_RETEST_PASS", row.get("blockers") or [])

    return candidates


def _ga_candidates(runtime_dir: Path) -> list[dict[str, Any]]:
    elite_archive = _read_json(runtime_dir / "ga_factory" / "QuantGod_GAEliteArchive.json")
    elite_strategies = _read_json(runtime_dir / "ga" / "QuantGod_GAEliteStrategies.json")
    retest = _read_json(runtime_dir / "agent" / "QuantGod_ChampionRetestReport.json")
    forex_retest = retest.get("forexChampion", {}) if isinstance(retest.get("forexChampion"), dict) else {}
    generation_elites = {
        row.get("seedId"): row
        for row in elite_strategies.get("elites", [])
        if isinstance(row, dict) and row.get("seedId")
    }
    candidates: list[dict[str, Any]] = []
    for row in elite_archive.get("elites", [])[:12]:
        seed_id = row.get("seedId", "")
        detail = generation_elites.get(seed_id, {})
        fitness_breakdown = detail.get("fitnessBreakdown", {}) if isinstance(detail, dict) else {}
        backtest = fitness_breakdown.get("strategyBacktest", {}) or detail.get("strategyBacktest", {})
        wf = (fitness_breakdown.get("walkForward", {}) or detail.get("walkForward", {})).get("summary", {})
        pnl_r = _num(backtest.get("netR"))
        pf = _num(backtest.get("profitFactor"))
        sharpe = _num(backtest.get("sharpe"))
        drawdown_r = _num(backtest.get("maxDrawdownR"))
        trades = _num(backtest.get("tradeCount"))
        effective_samples = _effective_ga_sample_count(backtest, wf, fitness_breakdown.get("walkForward", {}) or detail.get("walkForward", {}))
        stability = _num(wf.get("stabilityScore"))
        blockers = []
        if not detail or not backtest:
            blockers.append("MISSING_ELITE_METRICS")
        if row.get("blockerCode"):
            blockers.append(row["blockerCode"])
        if wf.get("promotionAllowed") is False and wf.get("blockerCode"):
            blockers.append(wf["blockerCode"])
        if (trades or effective_samples) and effective_samples < 20:
            blockers.append("LOW_SAMPLE_LT_20")
        if drawdown_r > 5:
            blockers.append("DRAWDOWN_R_GT_5")
        retest_status = forex_retest.get("status")
        if forex_retest.get("seedId") == seed_id:
            for item in forex_retest.get("blockers", []):
                if item:
                    blockers.append(f"CHAMPION_RETEST_{item}")
            if retest_status and retest_status != "FOREX_CHAMPION_RETEST_PASS":
                blockers.append(f"CHAMPION_RETEST_STATUS_{retest_status}")
        candidates.append(
            {
                "lane": "usdjpy_ga_elite",
                "source": "ga_factory_elite_archive",
                "seedId": seed_id,
                "strategyId": row.get("strategyId", ""),
                "strategyFamily": row.get("strategyFamily", ""),
                "direction": row.get("direction", ""),
                "fitness": round(_num(row.get("fitness")), 4),
                "netR": round(pnl_r, 4),
                "profitFactor": round(pf, 4),
                "sharpe": round(sharpe, 4),
                "maxDrawdownR": round(drawdown_r, 4),
                "tradeCount": int(trades),
                "effectiveSampleCount": effective_samples,
                "walkForwardStability": round(stability, 4),
                "trainNetR": round(_num(wf.get("trainNetR")), 4),
                "validationNetR": round(_num(wf.get("validationNetR")), 4),
                "forwardNetR": round(_num(wf.get("forwardNetR")), 4),
                "forwardNetRDelta": round(_num(wf.get("forwardNetRDelta")), 4),
                "championRetestStatus": retest_status if forex_retest.get("seedId") == seed_id else None,
                "promotionStage": row.get("promotionStage", "TESTER_ONLY"),
                "qualified": not blockers and row.get("status") == "ELITE_SELECTED",
                "blockers": sorted(set(blockers)),
                "score": _stable_score(
                    pnl=max(pnl_r, 0.0) * 10.0,
                    roi=max(pnl_r, 0.0) * 2.0,
                    sharpe=sharpe,
                    drawdown=drawdown_r,
                    trades=trades,
                    stability=stability,
                )
                + max(_num(row.get("fitness")), 0.0),
                "liveUnsafeReason": "ga_elite_requires_tester_and_forward_evidence",
                "safety": SAFETY,
            }
        )
    return candidates


def _forex_contender_review(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    forex = [
        row
        for row in candidates
        if row.get("lane") == "usdjpy_ga_elite"
        and row.get("qualified")
        and not row.get("blockers")
    ]
    forex = sorted(
        forex,
        key=lambda row: (
            _num(row.get("fitness")),
            _num(row.get("forwardNetR")),
            _num(row.get("validationNetR")),
            _num(row.get("profitFactor")),
            _num(row.get("sharpe")),
            -_num(row.get("maxDrawdownR")),
            _num(row.get("effectiveSampleCount")),
        ),
        reverse=True,
    )
    if not forex:
        return {
            "schema": "quantgod.ace_strategy_scout.forex_contender_review.v1",
            "status": "WAITING_QUALIFIED_FOREX_CONTENDERS",
            "statusZh": "等待合格外汇王牌候选",
            "contenderCount": 0,
            "tiedTopCount": 0,
            "requiresParallelTesterForward": False,
            "contenders": [],
            "safety": SAFETY,
        }

    top_fitness = _num(forex[0].get("fitness"))
    tied = [row for row in forex if abs(_num(row.get("fitness")) - top_fitness) <= 0.0001]
    contenders = []
    for row in tied[:5]:
        contenders.append(
            {
                "seedId": row.get("seedId"),
                "strategyId": row.get("strategyId"),
                "fitness": row.get("fitness"),
                "netR": row.get("netR"),
                "profitFactor": row.get("profitFactor"),
                "sharpe": row.get("sharpe"),
                "maxDrawdownR": row.get("maxDrawdownR"),
                "tradeCount": row.get("tradeCount"),
                "effectiveSampleCount": row.get("effectiveSampleCount"),
                "trainNetR": row.get("trainNetR"),
                "validationNetR": row.get("validationNetR"),
                "forwardNetR": row.get("forwardNetR"),
                "forwardNetRDelta": row.get("forwardNetRDelta"),
                "walkForwardStability": row.get("walkForwardStability"),
                "promotionStage": row.get("promotionStage"),
                "orderSendAllowed": False,
            }
        )

    tied_top_count = len(tied)
    return {
        "schema": "quantgod.ace_strategy_scout.forex_contender_review.v1",
        "status": "PARALLEL_TESTER_FORWARD_TIE_BREAK_REQUIRED"
        if tied_top_count > 1
        else "SINGLE_FOREX_ACE_CANDIDATE_READY",
        "statusZh": (
            "发现多个同分外汇王牌候选，需要隔离 tester/forward 并排复验"
            if tied_top_count > 1
            else "已找到单一外汇王牌候选，可进入隔离 tester/forward 复验"
        ),
        "topFitness": round(top_fitness, 4),
        "contenderCount": len(forex),
        "tiedTopCount": tied_top_count,
        "requiresParallelTesterForward": tied_top_count > 1,
        "tieBreakMetrics": [
            "forwardNetR",
            "validationNetR",
            "profitFactor",
            "sharpe",
            "maxDrawdownR",
            "effectiveSampleCount",
        ],
        "contenders": contenders,
        "recommendedActionZh": (
            "不要继续围绕仓位扩容优化；先把同分候选逐个送入隔离 Strategy Tester/forward A/B 复验，谁在样本外更稳再升级为唯一冠军。"
            if tied_top_count > 1
            else "围绕当前唯一候选补隔离 Strategy Tester/forward 证据，确认可重复稳定性。"
        ),
        "safety": SAFETY,
    }


def _live12_rsi_candidate(runtime_dir: Path) -> list[dict[str, Any]]:
    promotion = _read_json(runtime_dir / "agent" / "QuantGod_ForexLive12RsiCandidatePromotionGate.json")
    micro = _read_json(runtime_dir / "agent" / "QuantGod_ForexLive12MicroExpansionReview.json")
    repair = _read_json(runtime_dir / "agent" / "QuantGod_ForexLive12RsiTesterRunGate.json")
    metrics = (
        promotion.get("repairedCandidateEvidence", {}).get("metrics")
        or promotion.get("candidate", {}).get("afterMetrics")
        or promotion.get("afterMetrics")
        or {}
    )
    raw = (
        promotion.get("rawExpansionEvidence", {}).get("metrics")
        or promotion.get("current", {}).get("metrics")
        or micro.get("evidence", {}).get("metrics")
        or micro.get("metrics")
        or {}
    )
    rows = []
    for label, source_metrics in [("live12_raw_rsi", raw), ("live12_rsi_repair_candidate", metrics)]:
        if not source_metrics:
            continue
        pnl = _num(source_metrics.get("netProfitUSC", source_metrics.get("netProfit", 0.0)))
        pf = _num(source_metrics.get("profitFactor"))
        trades = _num(
            source_metrics.get(
                "closedTrades",
                source_metrics.get("naturalClosedTrades", source_metrics.get("tradeCount", 0.0)),
            )
        )
        loss_streak = int(_num(source_metrics.get("maxConsecutiveLosses", source_metrics.get("lossStreak", 0.0))))
        blockers = []
        if pnl <= 0:
            blockers.append("NET_PROFIT_NOT_POSITIVE")
        if pf < 1.05:
            blockers.append("PROFIT_FACTOR_LT_1_05")
        if loss_streak > 1:
            blockers.append("LOSS_STREAK_GT_1")
        rows.append(
            {
                "lane": label,
                "source": "live12_rsi_forward_or_tester_gate",
                "strategyId": label,
                "netProfitUSC": round(pnl, 4),
                "profitFactor": round(pf, 4),
                "tradeCount": int(trades),
                "maxConsecutiveLosses": loss_streak,
                "promotionStage": "TESTER_ONLY",
                "qualified": False,
                "blockers": blockers,
                "score": _stable_score(pnl=max(pnl, 0.0) / 10.0, roi=max(pnl, 0.0) / 10.0, sharpe=pf - 1.0, drawdown=loss_streak, trades=trades),
                "liveUnsafeReason": repair.get("status", "live12_rsi_not_ace_ready"),
                "safety": SAFETY,
            }
        )
    return rows


def _ga_iteration_health(runtime_dir: Path) -> dict[str, Any]:
    generation = _read_json(runtime_dir / "ga" / "QuantGod_GAGenerationLatest.json")
    status = _read_json(runtime_dir / "ga" / "QuantGod_GAStatus.json")
    walk_forward = generation.get("walkForward") or {}
    candidate_count = int(_num(walk_forward.get("candidateCount")))
    passed_count = int(_num(walk_forward.get("passedCount")))
    avg_fitness = _num(generation.get("avgFitness"))
    blocked_count = int(_num(generation.get("blockedCount")))
    current_generation = int(_num(status.get("currentGeneration", generation.get("generation"))))
    pass_rate = round((passed_count / candidate_count) if candidate_count else 0.0, 4)
    plateau = current_generation >= 90 and status.get("bestSeedId") in {
        "GA-USDJPY-G0093-C0004",
        "GA-USDJPY-G0077-C0002",
    }
    degraded = avg_fitness < -10 or pass_rate < 0.5
    return {
        "schema": "quantgod.ace_strategy_scout.ga_iteration_health.v1",
        "currentGeneration": current_generation,
        "bestSeedId": status.get("bestSeedId") or generation.get("bestSeedId"),
        "bestFitness": _num(status.get("bestFitness", generation.get("bestFitness"))),
        "avgFitness": round(avg_fitness, 4),
        "blockedCount": blocked_count,
        "walkForwardPassRate": pass_rate,
        "walkForwardPassedCount": passed_count,
        "walkForwardCandidateCount": candidate_count,
        "plateauDetected": plateau,
        "qualityDegraded": degraded,
        "recommendedMode": "CHAMPION_RETEST" if plateau and degraded else "ELITE_GUIDED_SEARCH",
        "reasonZh": (
            "GA 已进入平台期且本代质量退化；优先复验冠军候选，不继续盲目堆代数。"
            if plateau and degraded
            else "GA 仍可继续 elite-guided 搜索。"
        ),
        "safety": SAFETY,
    }


def _money_priority_plan(
    *,
    candidates: list[dict[str, Any]],
    forex_contender_review: dict[str, Any],
    ga_health: dict[str, Any],
    crypto_champion: dict[str, Any],
) -> dict[str, Any]:
    top = candidates[0] if candidates else {}
    qualified_forex = [
        row
        for row in candidates
        if row.get("lane") == "usdjpy_ga_elite"
        and row.get("qualified")
        and not row.get("blockers")
    ]
    crypto_blockers = list(crypto_champion.get("blockers", [])) if isinstance(crypto_champion, dict) else []
    crypto_valid_windows = int(_num(crypto_champion.get("validWindowCount"))) if isinstance(crypto_champion, dict) else 0
    crypto_window_count = int(_num(crypto_champion.get("windowCount"))) if isinstance(crypto_champion, dict) else 0
    crypto_negative_major_windows = (
        list(crypto_champion.get("negativeMajorWindows", []))
        if isinstance(crypto_champion.get("negativeMajorWindows"), list)
        else []
    )
    tied_forex_count = int(_num(forex_contender_review.get("tiedTopCount")))
    requires_tie_break = bool(forex_contender_review.get("requiresParallelTesterForward"))

    if qualified_forex and requires_tie_break:
        focus_mode = "FOREX_AB_TESTER_FORWARD_TIE_BREAK"
        primary_action = "并排复验 G0093/G0102，先确定唯一王牌，再考虑任何放大。"
    elif qualified_forex:
        focus_mode = "FOREX_SINGLE_CHAMPION_TESTER_FORWARD"
        primary_action = "把唯一外汇冠军推进隔离 tester/forward，补齐样本外证据。"
    elif crypto_valid_windows >= 2:
        focus_mode = "BTC_MULTI_WINDOW_REPAIR"
        primary_action = "BTC 已有局部强证据，但必须继续修复低 Sharpe / 低样本窗口。"
    else:
        focus_mode = "EVIDENCE_REPAIR_BEFORE_SIZE"
        primary_action = "先补样本和修 blocker，不把仓位数当成优化目标。"
    btc_action = (
        f"BTC 只做 shadow 多窗口修复，优先处理负主窗口 {crypto_negative_major_windows} 和低 Sharpe/低样本窗口。"
        if crypto_negative_major_windows
        else "BTC 只做 shadow 多窗口修复；当前主窗口均为正，下一步重点提高子窗口 Sharpe 和交易数。"
    )
    btc_success_criteria = [
        "至少 3 个主要窗口无 pnl blocker",
        "有效窗口数继续提高",
        "tradeCount 不靠单窗口堆高",
        "maxDrawdownPct 保持低于 3%",
    ]
    if crypto_negative_major_windows:
        btc_success_criteria.insert(0, "负主窗口 pnlUsd 转正")

    plan = {
        "schema": "quantgod.ace_strategy_scout.money_priority_plan.v1",
        "objectiveZh": "赚钱优先不是先扩仓，而是先找可重复、低回撤、样本外仍为正的王牌策略。",
        "focusMode": focus_mode,
        "primaryLane": top.get("lane"),
        "primaryStrategyId": top.get("strategyId") or top.get("seedId"),
        "primaryActionZh": primary_action,
        "whyNotPositionFirstZh": "仓位只放大既有边际；如果策略跨窗口不稳，扩仓会同步放大回撤和过拟合风险。",
        "stableAceDefinition": {
            "mustHavePositiveForwardEvidence": True,
            "mustAvoidNegativeMajorWindow": True,
            "mustPassTesterOrForward": True,
            "mustKeepDrawdownControlled": True,
            "minEffectiveSampleCount": 20,
            "minSharpe": 1.0,
            "orderSendAllowed": False,
        },
        "immediateWorkQueue": [
            {
                "id": "forex_ab_tie_break",
                "priority": 1,
                "lane": "usdjpy_ga_elite",
                "actionZh": "把并列最高分 G0093/G0102 作为第一算力对象，做隔离 tester/forward A/B 复验。",
                "reasonZh": f"当前合格外汇候选 {len(qualified_forex)} 个，并列最高 {tied_forex_count} 个；二者 PF/Sharpe/forwardNetR 相同，需要样本外打破平局。",
                "successCriteria": [
                    "forwardNetR 保持正值",
                    "profitFactor 仍大于 1.5",
                    "maxDrawdownR 不扩大",
                    "有效样本数继续增加",
                ],
                "writesOrders": False,
            },
            {
                "id": "btc_window_repair",
                "priority": 2,
                "lane": "hfm_crypto_cfd_shadow",
                "actionZh": btc_action,
                "reasonZh": f"BTC 当前有效窗口 {crypto_valid_windows}/{crypto_window_count}，blocker={crypto_blockers[:5]}。",
                "successCriteria": btc_success_criteria,
                "writesOrders": False,
            },
            {
                "id": "ga_blocker_suppression",
                "priority": 3,
                "lane": "usdjpy_ga",
                "actionZh": "减少盲目新代数，把 mutation 权重压向减少 WALK_FORWARD_UNSTABLE、OVERFIT_RISK、MAX_ADVERSE_TOO_HIGH。",
                "reasonZh": f"GA 模式={ga_health.get('recommendedMode')}，当前 best={ga_health.get('bestSeedId')}，平台期信号={ga_health.get('plateauDetected')}。",
                "successCriteria": [
                    "新候选不能牺牲风险内核",
                    "新候选必须比 G0093/G0102 在样本外更稳",
                    "不因高 pnl 接受更大不利波动",
                ],
                "writesOrders": False,
            },
        ],
        "deprioritizedWorkZh": [
            "暂不把 10 仓位作为主目标。",
            "暂不把 BTC 单段高 pnl 当作实盘王牌。",
            "暂不把 raw Live12 RSI 当王牌，除非 tester 证据重新达标。",
        ],
        "executionPolicy": {
            "liveExecutionAllowed": False,
            "orderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "livePresetMutationAllowed": False,
            "reasonZh": "本计划只负责把策略研究导向赚钱概率最高的路线；不触发真实订单。"
        },
        "safety": SAFETY,
    }
    return plan


def _top_research_crypto_candidate(
    *,
    top_crypto: dict[str, Any],
    crypto_champion: dict[str, Any],
    crypto_champion_metrics: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    def blockers_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return []

    if top_crypto:
        return {
            "strategyId": top_crypto.get("strategyId"),
            "status": top_crypto.get("championRetestStatus") or top_crypto.get("status"),
            "pnlUsd": top_crypto.get("pnlUsd"),
            "sharpe": top_crypto.get("sharpe"),
            "maxDrawdownPct": top_crypto.get("maxDrawdownPct"),
            "tradeCount": top_crypto.get("tradeCount"),
            "validWindowCount": top_crypto.get("championRetestValidWindowCount"),
            "windowCount": top_crypto.get("championRetestWindowCount"),
            "blockers": blockers_list(top_crypto.get("blockers")),
            "qualified": True,
            "sourceArtifact": "topQualifiedCrypto",
            "reasonZh": "当前存在无 blocker 的 BTC 合格候选，优先把它作为研究级冠军显示。",
        }

    if crypto_champion.get("strategyId"):
        return {
            "strategyId": crypto_champion.get("strategyId"),
            "status": crypto_champion.get("status"),
            "pnlUsd": crypto_champion_metrics.get("pnlUsd"),
            "sharpe": crypto_champion_metrics.get("sharpe"),
            "maxDrawdownPct": crypto_champion_metrics.get("maxDrawdownPct"),
            "tradeCount": crypto_champion_metrics.get("tradeCount"),
            "validWindowCount": crypto_champion.get("validWindowCount"),
            "windowCount": crypto_champion.get("windowCount"),
            "blockers": blockers_list(crypto_champion.get("blockers")),
            "qualified": False,
            "sourceArtifact": "topRetestedCrypto",
            "reasonZh": "当前没有无 blocker 的 BTC 合格候选；回退到 multi-window champion retest 第一名作为研究级冠军。",
        }

    top_shadow_candidate = next(
        (row for row in candidates if row.get("lane") == "hfm_crypto_cfd_shadow"),
        {},
    )
    return {
        "strategyId": top_shadow_candidate.get("strategyId"),
        "status": top_shadow_candidate.get("championRetestStatus") or top_shadow_candidate.get("status"),
        "pnlUsd": top_shadow_candidate.get("pnlUsd"),
        "sharpe": top_shadow_candidate.get("sharpe"),
        "maxDrawdownPct": top_shadow_candidate.get("maxDrawdownPct"),
        "tradeCount": top_shadow_candidate.get("tradeCount"),
        "validWindowCount": top_shadow_candidate.get("championRetestValidWindowCount"),
        "windowCount": top_shadow_candidate.get("championRetestWindowCount"),
        "blockers": blockers_list(top_shadow_candidate.get("blockers")),
        "qualified": bool(top_shadow_candidate.get("qualified")),
        "sourceArtifact": "candidates",
        "reasonZh": "当前没有可用的 BTC retest 冠军时，回退到侦察报告里的最高分 BTC shadow 候选。",
    }


def _btc_shadow_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in candidates
        if row.get("lane") == "hfm_crypto_cfd_shadow"
    ]


def _find_candidate_by_strategy_id(candidates: list[dict[str, Any]], strategy_id: Any) -> dict[str, Any]:
    strategy_id_str = str(strategy_id or "")
    if not strategy_id_str:
        return {}
    return next(
        (row for row in candidates if str(row.get("strategyId") or "") == strategy_id_str),
        {},
    )


def _btc_converged_variant_rows(scan: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_rows: list[dict[str, Any]] = []
    top_recommendation = scan.get("topRecommendation")
    if isinstance(top_recommendation, dict):
        source_rows.append(top_recommendation)
    source_rows.extend(
        row for row in scan.get("topCandidates", [])
        if isinstance(row, dict)
    )
    for rank, row in enumerate(source_rows, start=1):
        strategy_id = str(row.get("strategyId") or "")
        if not strategy_id or strategy_id in seen:
            continue
        if not (
            strategy_id.startswith("hfm_crypto_btc_near_live_middle_window_")
            or strategy_id.startswith("hfm_crypto_btc_near_live_stoploss_ladder_")
            or strategy_id.startswith("hfm_crypto_btc_near_live_cluster_refinement_")
        ):
            continue
        seen.add(strategy_id)
        params = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}
        metrics = row.get("fullWindowMetrics") if isinstance(row.get("fullWindowMetrics"), dict) else {}
        rows.append({
            "rank": rank,
            "strategyId": strategy_id,
            "stopLossPriceMove": params.get("stopLossPriceMove"),
            "takeProfitPriceMove": params.get("takeProfitPriceMove"),
            "cooldownBars": params.get("cooldownBars"),
            "maxHoldBars": params.get("maxHoldBars"),
            "validWindowCount": row.get("validWindowCount"),
            "windowCount": row.get("windowCount"),
            "pnlUsd": metrics.get("pnlUsd"),
            "sharpe": metrics.get("sharpe"),
            "tradeCount": metrics.get("tradeCount"),
        })
        if len(rows) >= limit:
            break
    return rows


def _btc_converged_variant_summary(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    parts: list[str] = []
    for row in rows:
        strategy_id = row.get("strategyId")
        stop_loss = row.get("stopLossPriceMove")
        if isinstance(strategy_id, str) and strategy_id:
            if stop_loss is not None:
                parts.append(f"{strategy_id}(SL={stop_loss})")
            else:
                parts.append(strategy_id)
    if not parts:
        return None
    return f"当前 near-live 收敛簇前排变体: {' -> '.join(parts)}。"


def _btc_research_focus(
    *,
    scan: dict[str, Any],
    top_research_crypto: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    scan_plan = scan.get("nextFocusedSearchPlan", {}) if isinstance(scan.get("nextFocusedSearchPlan"), dict) else {}
    recommendations = [
        row for row in scan_plan.get("recommendations", [])
        if isinstance(row, dict)
    ]
    top_recommendation = scan.get("topRecommendation", {}) if isinstance(scan.get("topRecommendation"), dict) else {}
    most_stable = scan.get("mostStableTradeoff", {}) if isinstance(scan.get("mostStableTradeoff"), dict) else {}
    top_candidates = [
        row for row in scan.get("topCandidates", [])
        if isinstance(row, dict)
    ]
    repair_diagnostics = scan.get("repairDiagnostics", {}) if isinstance(scan.get("repairDiagnostics"), dict) else {}
    stable_middle_tradeoff = scan_plan.get("stableMiddleTradeoffFollowupBestTradeoff", {})
    if not isinstance(stable_middle_tradeoff, dict):
        stable_middle_tradeoff = {}
    if not stable_middle_tradeoff:
        stable_middle_tradeoff = (
            repair_diagnostics.get("stableMiddleTradeoffFollowup", {}).get("bestByStabilityRank", {})
            if isinstance(repair_diagnostics.get("stableMiddleTradeoffFollowup"), dict)
            else {}
        )
    near_live_cluster_refinement = scan_plan.get("nearLiveClusterRefinementBestTradeoff", {})
    if not isinstance(near_live_cluster_refinement, dict):
        near_live_cluster_refinement = {}
    near_live_stoploss_ladder_strategy_id = str(
        (
            scan_plan.get("nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId")
            if (
                scan_plan.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro")
                or scan_plan.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesContender")
            )
            else (
            scan_plan.get("nearLiveStoplossLadderFollowupMicroBestStrategyId")
            if (
                scan_plan.get("nearLiveStoplossLadderFollowupMicroImprovesRefinement")
                or scan_plan.get("nearLiveStoplossLadderFollowupMicroImprovesContender")
            )
            else (
                scan_plan.get("nearLiveStoplossLadderFollowupBestStrategyId")
                if scan_plan.get("nearLiveStoplossLadderFollowupImprovesRefinement")
                else scan_plan.get("nearLiveStoplossLadderRefinementBestStrategyId")
            )
            )
        )
        or ""
    )

    anchor_id = (
        top_recommendation.get("strategyId")
        or most_stable.get("strategyId")
        or top_research_crypto.get("strategyId")
    )

    contender_id = ""
    contender_reason_zh = None
    contender_source_artifact = None
    for recommendation in recommendations:
        basis_strategy_id = str(recommendation.get("basisStrategyId") or "")
        if basis_strategy_id and basis_strategy_id != anchor_id:
            contender_id = basis_strategy_id
            contender_reason_zh = recommendation.get("reasonZh")
            contender_source_artifact = (
                f"btcStrategyScan.nextFocusedSearchPlan.recommendations.{recommendation.get('id')}"
                if recommendation.get("id") else "btcStrategyScan.nextFocusedSearchPlan.recommendations"
            )
            break
    if not contender_id:
        for row in top_candidates:
            basis_strategy_id = str(row.get("strategyId") or "")
            if basis_strategy_id and basis_strategy_id != anchor_id:
                contender_id = basis_strategy_id
                contender_reason_zh = "当前 fresh scan 的 next distinct BTC contender。"
                contender_source_artifact = "btcStrategyScan.topCandidates"
                break
    if not contender_id:
        for row in _btc_shadow_candidates(candidates):
            basis_strategy_id = str(row.get("strategyId") or "")
            if basis_strategy_id and basis_strategy_id != anchor_id:
                contender_id = basis_strategy_id
                contender_reason_zh = "当前 scout 里的 next distinct BTC shadow contender。"
                contender_source_artifact = "aceStrategyScout.candidates"
                break

    repair_id = str(scan_plan.get("repairStrategyId") or "")
    repair_reason_zh = None
    repair_source_artifact = (
        "btcStrategyScan.nextFocusedSearchPlan.repairStrategyId"
        if repair_id else None
    )
    for recommendation in recommendations:
        if recommendation.get("id") == "stable_champion_middle_third_rescue":
            repair_reason_zh = recommendation.get("reasonZh")
            if repair_id:
                break
    if not repair_reason_zh:
        for outcome_key in (
            "stableMiddleThirdFollowupOutcomeZh",
            "stableMiddleTradeoffFollowupOutcomeZh",
            "stableMiddleWeakWindowBridgeOutcomeZh",
            "stableMiddleWeakWindowConfirmationOutcomeZh",
            "stableMiddleThirdRepairOutcomeZh",
        ):
            outcome = scan_plan.get(outcome_key)
            if isinstance(outcome, str) and outcome:
                repair_reason_zh = outcome
                break
    if not repair_id:
        repair_id = str(stable_middle_tradeoff.get("strategyId") or "")
        repair_source_artifact = (
            "btcStrategyScan.nextFocusedSearchPlan.stableMiddleTradeoffFollowupBestTradeoff"
            if repair_id else None
        )
    if not repair_id:
        for recommendation in recommendations:
            if recommendation.get("id") == "stable_champion_middle_third_rescue":
                basis_strategy_id = str(recommendation.get("basisStrategyId") or "")
                if basis_strategy_id:
                    repair_id = basis_strategy_id
                    repair_reason_zh = recommendation.get("reasonZh")
                    repair_source_artifact = "btcStrategyScan.nextFocusedSearchPlan.recommendations.stable_champion_middle_third_rescue"
                    break
    if not repair_id:
        for row in _btc_shadow_candidates(candidates):
            candidate_id = str(row.get("strategyId") or "")
            if candidate_id and candidate_id not in {anchor_id, contender_id}:
                repair_id = candidate_id
                repair_reason_zh = "当前 scout 里的第三条 BTC repair 观察线。"
                repair_source_artifact = "aceStrategyScout.candidates"
                break

    recommended_order = [
        str(strategy_id)
        for strategy_id in (
            scan_plan.get("recommendedFocusedRetestOrder")
            if isinstance(scan_plan.get("recommendedFocusedRetestOrder"), list)
            else []
        )
        if isinstance(strategy_id, str) and strategy_id
    ]
    if not recommended_order:
        recommended_order = []
    for strategy_id in (anchor_id, contender_id, repair_id):
        strategy_id_str = str(strategy_id or "")
        if strategy_id_str and strategy_id_str not in recommended_order:
            recommended_order.append(strategy_id_str)

    converged_variant_ids: list[str] = []
    for strategy_id in (
        anchor_id,
        contender_id,
        near_live_stoploss_ladder_strategy_id or near_live_cluster_refinement.get("strategyId"),
    ):
        strategy_id_str = str(strategy_id or "")
        if strategy_id_str and strategy_id_str not in converged_variant_ids:
            converged_variant_ids.append(strategy_id_str)
    converged_variant_rows = _btc_converged_variant_rows(scan)
    converged_variant_stop_loss_ladder = [
        row.get("stopLossPriceMove")
        for row in converged_variant_rows
        if row.get("stopLossPriceMove") is not None
    ]
    converged_variant_summary_zh = _btc_converged_variant_summary(converged_variant_rows)

    return {
        "status": "BTC_RESEARCH_FOCUS_READY" if recommended_order else "WAITING_BTC_RESEARCH_FOCUS",
        "topStrategyId": anchor_id,
        "stableAnchorStrategyId": anchor_id,
        "nextDistinctStrategyId": contender_id or None,
        "nextDistinctContenderStrategyId": contender_id or None,
        "repairStrategyId": repair_id or None,
        "repairLineStrategyId": repair_id or None,
        "recommendedFocusedRetestOrder": recommended_order,
        "convergedVariantStrategyIds": converged_variant_ids,
        "convergedVariantRows": converged_variant_rows,
        "convergedVariantStopLossLadder": converged_variant_stop_loss_ladder,
        "convergedVariantSummaryZh": converged_variant_summary_zh,
        "stableAnchorSourceArtifact": (
            "btcStrategyScan.topRecommendation"
            if top_recommendation.get("strategyId")
            else (
                "btcStrategyScan.mostStableTradeoff"
                if most_stable.get("strategyId")
                else top_research_crypto.get("sourceArtifact")
            )
        ),
        "nextDistinctContenderSourceArtifact": contender_source_artifact,
        "repairLineSourceArtifact": repair_source_artifact,
        "nextDistinctContenderReasonZh": contender_reason_zh,
        "repairLineReasonZh": repair_reason_zh,
        "summaryZh": (
            f"BTC 当前研究主线: {anchor_id or 'unknown'}"
            + (f" -> {contender_id}" if contender_id else "")
            + (f" -> {repair_id}" if repair_id else "")
            + "。"
        ),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _operator_focus(
    *,
    runtime_dir: Path,
    top_forex: dict[str, Any],
    btc_research_focus: dict[str, Any],
    btc_next_action_zh: str | None,
) -> dict[str, Any]:
    run_gate = _read_json(runtime_dir / CHAMPION_TESTER_RUN_GATE_PATH)
    live_evidence = _read_json(runtime_dir / LIVE_EVIDENCE_INTAKE_PATH)

    mt5_blockers = _string_list(run_gate.get("blockers"))
    btc_blockers: list[str] = []
    if live_evidence:
        if not bool(live_evidence.get("dashboardFresh")):
            btc_blockers.append("live_dashboard_snapshot_stale")
        trade_permission_blocker = str(live_evidence.get("tradePermissionBlocker") or "")
        if trade_permission_blocker:
            btc_blockers.append(trade_permission_blocker)
        if str(live_evidence.get("tradeStatus") or "").upper() == "SHADOW":
            btc_blockers.append("trade_status_shadow")

    mt5_next_action_zh = ""
    decision = run_gate.get("decision")
    if isinstance(decision, dict):
        mt5_next_action_zh = str(decision.get("nextRequiredActionZh") or "")
    if not mt5_next_action_zh and mt5_blockers:
        mt5_next_action_zh = "先恢复主 MT5 terminal64 进程并恢复 dashboard freshness，再重建 tester gate。"

    btc_operator_action_zh = ""
    if live_evidence:
        btc_operator_action_zh = (
            "先刷新 live16 dashboard 并确认 livePilotMode/readOnlyMode/"
            "executionEnabled/tradeAllowed，再继续当前 BTC 稳定优先复验。"
        )
    if not btc_operator_action_zh:
        btc_operator_action_zh = btc_next_action_zh or ""

    has_forex_release_candidate = bool(top_forex.get("seedId") or top_forex.get("strategyId"))
    has_btc_research_candidate = bool(btc_research_focus.get("topStrategyId"))

    operator_lane = None
    operator_next_action_zh = None
    operator_focus_summary_zh = None
    operator_blockers: list[str] = []

    if mt5_blockers and has_forex_release_candidate and (
        not btc_blockers or len(mt5_blockers) <= len(btc_blockers)
    ):
        operator_lane = "forexMt5"
        operator_next_action_zh = mt5_next_action_zh or None
        operator_blockers = mt5_blockers
        operator_focus_summary_zh = (
            "当前最接近 guarded tester-forward 的仍是 MT5 lane；"
            f"先清外部门槛 {', '.join(mt5_blockers)}。"
        )
    elif btc_blockers and has_btc_research_candidate:
        operator_lane = "btcCryptoCfd"
        operator_next_action_zh = btc_operator_action_zh or None
        operator_blockers = btc_blockers
        operator_focus_summary_zh = (
            "当前需要先补 BTC live evidence；"
            f"直接 blocker={', '.join(btc_blockers)}。"
        )
    elif has_btc_research_candidate:
        operator_lane = "btcCryptoCfd"
        operator_next_action_zh = btc_next_action_zh or None
        operator_focus_summary_zh = "当前没有 fresh 外部 gate 证据时，继续沿 BTC 研究主线推进。"
    elif has_forex_release_candidate:
        operator_lane = "forexMt5"
        operator_next_action_zh = mt5_next_action_zh or None
        operator_blockers = mt5_blockers
        operator_focus_summary_zh = "当前优先继续推进 MT5 tester-forward 准备。"

    return {
        "currentOperatorLane": operator_lane,
        "operatorNextActionZh": operator_next_action_zh,
        "operatorFocusSummaryZh": operator_focus_summary_zh,
        "operatorBlockers": operator_blockers,
        "operatorSourceArtifacts": [
            artifact
            for artifact, payload in (
                ("championTesterRunGate", run_gate),
                ("liveEvidenceIntake", live_evidence),
            )
            if isinstance(payload, dict) and payload
        ],
    }


def build_ace_strategy_scout(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    scan = _read_json(runtime_dir / BTC_SCAN_REPORT_PATH)
    candidates = _crypto_candidates(runtime_dir) + _ga_candidates(runtime_dir) + _live12_rsi_candidate(runtime_dir)
    candidates = sorted(
        candidates,
        key=lambda row: (
            not bool(row.get("blockers")),
            bool(row.get("qualified")),
            row.get("score", 0.0),
        ),
        reverse=True,
    )
    for index, row in enumerate(candidates, start=1):
        row["rank"] = index
        row["decision"] = _decision_for_candidate(row)

    blocker_counts = Counter(
        blocker
        for row in candidates
        for blocker in row.get("blockers", [])
        if blocker
    )
    ga_health = _ga_iteration_health(runtime_dir)
    forex_contender_review = _forex_contender_review(candidates)
    top = candidates[0] if candidates else {}
    qualified = [row for row in candidates if not row.get("blockers") and row.get("qualified")]
    top_forex = next((row for row in qualified if row.get("lane") == "usdjpy_ga_elite"), {})
    top_crypto = next((row for row in qualified if row.get("lane") == "hfm_crypto_cfd_shadow"), {})
    champion_retest = _ensure_fresh_champion_retest(runtime_dir)
    crypto_champion = champion_retest.get("cryptoChampion", {}) if isinstance(champion_retest.get("cryptoChampion"), dict) else {}
    crypto_champion_metrics = crypto_champion.get("fullWindowMetrics", {}) if isinstance(crypto_champion.get("fullWindowMetrics"), dict) else {}
    top_research_crypto = _top_research_crypto_candidate(
        top_crypto=top_crypto,
        crypto_champion=crypto_champion,
        crypto_champion_metrics=crypto_champion_metrics,
        candidates=candidates,
    )
    btc_research_focus = _btc_research_focus(
        scan=scan,
        top_research_crypto=top_research_crypto,
        candidates=candidates,
    )
    scan_plan = scan.get("nextFocusedSearchPlan", {}) if isinstance(scan.get("nextFocusedSearchPlan"), dict) else {}
    btc_next_action_zh = (
        scan_plan.get("nextActionZh")
        if isinstance(scan_plan.get("nextActionZh"), str) and scan_plan.get("nextActionZh")
        else btc_research_focus.get("summaryZh")
    )
    operator_focus = _operator_focus(
        runtime_dir=runtime_dir,
        top_forex=top_forex,
        btc_research_focus=btc_research_focus,
        btc_next_action_zh=btc_next_action_zh,
    )
    money_priority_plan = _money_priority_plan(
        candidates=candidates,
        forex_contender_review=forex_contender_review,
        ga_health=ga_health,
        crypto_champion=crypto_champion,
    )
    generated_at_iso = _now_iso()
    report = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAt": generated_at_iso,
        "generatedAtIso": generated_at_iso,
        "status": "ACE_SCOUT_READY" if candidates else "WAITING_STRATEGY_EVIDENCE",
        "statusZh": "王牌策略侦察报告已生成" if candidates else "等待策略证据",
        "candidateCount": len(candidates),
        "topLane": top.get("lane"),
        "topStrategyId": top.get("strategyId") or top.get("seedId"),
        "topDecision": top.get("decision"),
        "topQualifiedForex": {
            "seedId": top_forex.get("seedId"),
            "strategyId": top_forex.get("strategyId"),
            "profitFactor": top_forex.get("profitFactor"),
            "sharpe": top_forex.get("sharpe"),
            "tradeCount": top_forex.get("tradeCount"),
            "effectiveSampleCount": top_forex.get("effectiveSampleCount"),
            "walkForwardStability": top_forex.get("walkForwardStability"),
        },
        "topQualifiedCrypto": {
            "strategyId": top_crypto.get("strategyId"),
            "pnlUsd": top_crypto.get("pnlUsd"),
            "sharpe": top_crypto.get("sharpe"),
            "maxDrawdownPct": top_crypto.get("maxDrawdownPct"),
            "tradeCount": top_crypto.get("tradeCount"),
            "liquidationCount": top_crypto.get("liquidationCount"),
        },
        "topResearchCrypto": top_research_crypto,
        "btcResearchFocus": btc_research_focus,
        "currentResearchLane": "btcCryptoCfd" if btc_research_focus.get("topStrategyId") else None,
        "researchNextActionZh": btc_next_action_zh,
        "nextActionZh": btc_next_action_zh,
        "currentOperatorLane": operator_focus.get("currentOperatorLane"),
        "operatorNextActionZh": operator_focus.get("operatorNextActionZh"),
        "operatorFocusSummaryZh": operator_focus.get("operatorFocusSummaryZh"),
        "operatorBlockers": operator_focus.get("operatorBlockers"),
        "operatorSourceArtifacts": operator_focus.get("operatorSourceArtifacts"),
        "topRetestedCrypto": {
            "strategyId": crypto_champion.get("strategyId"),
            "status": crypto_champion.get("status"),
            "validWindowCount": crypto_champion.get("validWindowCount"),
            "windowCount": crypto_champion.get("windowCount"),
            "pnlUsd": crypto_champion_metrics.get("pnlUsd"),
            "sharpe": crypto_champion_metrics.get("sharpe"),
            "maxDrawdownPct": crypto_champion_metrics.get("maxDrawdownPct"),
            "tradeCount": crypto_champion_metrics.get("tradeCount"),
            "blockers": crypto_champion.get("blockers", []),
        },
        "forexContenderReview": forex_contender_review,
        "candidates": candidates,
        "blockerCounts": dict(blocker_counts.most_common()),
        "gaIterationHealth": ga_health,
        "moneyPriorityPlan": money_priority_plan,
        "nextSafeActions": [
            {
                "id": "usd_jpy_tied_forex_contender_ab_tester_forward",
                "lane": "usdjpy_ga_elite",
                "actionZh": "若 forexContenderReview 显示同分候选，先做隔离 tester/forward A/B 复验，不把扩仓当作优化目标。",
                "writesOrders": False,
                "orderSendAllowed": False,
            },
            {
                "id": "usd_jpy_top_forex_champion_retest",
                "lane": "usdjpy_ga_elite",
                "actionZh": f"把 {top_forex.get('seedId') or '当前最高分 USDJPY 候选'} 作为外汇冠军候选进入隔离 tester / forward 复验。",
                "writesOrders": False,
                "orderSendAllowed": False,
            },
            {
                "id": "btc_crypto_shadow_multi_window_retest",
                "lane": "hfm_crypto_cfd_shadow",
                "actionZh": "对 BTC crypto candidateRetests 第一名补更长 CopyRates 多窗口复验，确认不是 2026-05 单窗口偶然性。",
                "writesOrders": False,
                "orderSendAllowed": False,
            },
            {
                "id": "ga_plateau_reduce_blind_iterations",
                "lane": "usdjpy_ga",
                "actionZh": "GA 若继续退化，减少盲目 generation，改为围绕 G0077/G0093 做低样本补齐和 blocker 定向修复。",
                "writesOrders": False,
                "orderSendAllowed": False,
            },
        ],
        "recommendationsZh": [
            "停止把扩仓当作主要优化目标；先提高候选策略的样本外稳定性和回撤质量。",
            "优先推进排名最高且无 blocker 的候选进入更多 forward / tester 样本；低样本高分候选先补样本，不直接当王牌。",
            "HFM BTC crypto CFD shadow 保持 crypto 第一研究线，继续做多窗口复验和样本扩展。",
            "USDJPY GA elite 只进入隔离 Strategy Tester/forward 验证；未经 tester 和 forward 证据不进入真钱执行。",
            "Live12 原始 RSI 不作为王牌候选，除非修复版重新证明净利、PF 和连续亏损都达标。",
            "下一轮 GA 应降低造成 WALK_FORWARD_UNSTABLE、OVERFIT_RISK、MAX_ADVERSE_TOO_HIGH 的变异方向权重。",
        ],
        "aceCriteria": {
            "minTradeCount": 20,
            "minSharpe": 1.0,
            "maxDrawdownPctPreferred": 3.0,
            "maxLiquidationCount": 0,
            "mustPassForwardOrTester": True,
            "orderSendAllowed": False,
        },
        "safety": SAFETY,
        "reportPath": str(runtime_dir / REPORT_PATH),
    }
    if write:
        _write_json(runtime_dir / REPORT_PATH, report)
    return report


def read_ace_strategy_scout(runtime_dir: Path) -> dict[str, Any]:
    report = _read_json(runtime_dir / REPORT_PATH)
    if report and not _saved_scout_stale(runtime_dir, report):
        return report
    return build_ace_strategy_scout(runtime_dir, write=False)
