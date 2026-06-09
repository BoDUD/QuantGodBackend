from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tools.ace_execution_candidate_pack import (
    _alias_strategy_ids_without_self,
    _btc_scan_plan_repair_candidate,
    _current_near_live_cluster_aliases,
    _btc_focused_retest_queue,
    _btc_lineup_board,
    _resolve_current_btc_canonical_strategy_id,
    _btc_shortlist,
    _lane_verdicts,
    _artifact_summary,
    _mt5_window_briefing,
    _mt5_tester_snapshot,
    _strategy_shortlist_item,
    build_ace_execution_candidate_pack,
    read_ace_execution_candidate_pack,
)


class AceExecutionCandidatePackTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_resolve_current_btc_canonical_strategy_id_maps_optimizer_alias_to_current_contender(self) -> None:
        strategy_shortlist = {
            "btcTopStrategies": [
                {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "params": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                },
                {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                    "params": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 300.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                },
                {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_0003",
                    "params": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 312.5,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                },
            ],
            "btcCryptoCfd": {
                "focusedRetestQueue": [
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "params": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 325.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 4,
                        },
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "params": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 4,
                        },
                    },
                ],
            },
            "selectionConsensus": {
                "btc": {
                    "mostStableNowStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "strongestYieldNowStrategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                },
            },
        }

        canonical = _resolve_current_btc_canonical_strategy_id(
            {
                "strategyId": "hfm_crypto_btc_tpsl_0341",
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
            },
            strategy_shortlist,
        )

        self.assertEqual(canonical, "hfm_crypto_btc_near_live_middle_window_0021")

    def test_btc_focused_queue_tracks_recommended_order_when_tradeoff_is_promoted(self) -> None:
        queue = _btc_focused_retest_queue(
            btc={
                "focusedRetestQueue": [
                    {"strategyId": "hfm_crypto_btc_tpsl_0302"},
                    {"strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1"},
                    {"strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1"},
                ],
                "windowHealth": {"selectedDefault": {}},
            },
            strategy_shortlist={
                "btcTopStrategies": [
                    {
                        "role": "stableAnchor",
                        "strategyId": "hfm_crypto_btc_tpsl_0302",
                        "strategyName": "hfm_crypto_btc_tpsl_0302",
                        "strategyFamily": "stable_anchor",
                        "status": "READY",
                        "metrics": {"validWindowCount": 5},
                        "params": {},
                        "blockers": [],
                        "selectionBasis": {"sourceArtifact": "scan.stable"},
                    },
                    {
                        "role": "stabilityAlternative",
                        "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                        "strategyName": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                        "strategyFamily": "near_live",
                        "status": "READY",
                        "metrics": {"validWindowCount": 4},
                        "params": {},
                        "blockers": [],
                        "selectionBasis": {"sourceArtifact": "scan.near_live"},
                    },
                    {
                        "role": "highYieldTradeoff",
                        "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                        "strategyName": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                        "strategyFamily": "yield_frontier",
                        "status": "READY",
                        "metrics": {"validWindowCount": 3},
                        "params": {},
                        "blockers": [],
                        "selectionBasis": {"sourceArtifact": "scan.yield"},
                    },
                ],
                "btcLineupBoard": {
                    "recommendedFocusedRetestOrder": [
                        "hfm_crypto_btc_tpsl_0302",
                        "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                        "hfm_crypto_btc_stable_middle_tradeoff_0025",
                        "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                    ],
                    "stableMiddleTradeoffFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0025",
                        "pnlUsd": 48.3,
                        "sharpe": 1.5646,
                        "tradeCount": 80,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "stableMiddleTradeoffFollowupImprovesBridge": True,
                    "stableMiddleTradeoffFollowupImprovesWeakWindow": True,
                    "stableMiddleTradeoffFollowupImprovesBaseline": True,
                    "stableMiddleTradeoffFollowupOutcomeZh": "tradeoff 已改善 weak-window baseline。",
                },
            },
        )

        self.assertEqual(
            [row["strategyId"] for row in queue],
            [
                "hfm_crypto_btc_tpsl_0302",
                "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "hfm_crypto_btc_stable_middle_tradeoff_0025",
                "hfm_crypto_btc_yield_balanced_both_shadow_v1",
            ],
        )
        self.assertEqual([row["priority"] for row in queue], [1, 2, 3, 4])
        self.assertEqual(queue[2]["role"], "repairObservation")
        self.assertEqual(queue[2]["summaryType"], "stableMiddleTradeoffFollowup")

    def test_btc_scan_plan_repair_candidate_uses_followup_metadata_when_followup_is_selected(self) -> None:
        candidate = _btc_scan_plan_repair_candidate({
            "repairStrategyId": "hfm_crypto_btc_stable_middle_followup_0002",
            "repairStrategyLabelZh": "stable middle-third aggregate-stability fallback",
            "repairStrategyRoleZh": "第三条 distinct 稳定 fallback 路径",
            "stableMiddleThirdFollowupBestTradeoff": {
                "strategyId": "hfm_crypto_btc_stable_middle_followup_0002",
                "pnlUsd": 38.0,
                "sharpe": 1.29,
                "tradeCount": 69,
                "validWindowCount": 4,
                "windowCount": 6,
                "bias": "short",
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 325.0,
                "maxHoldBars": 8,
                "cooldownBars": 6,
            },
            "stableMiddleThirdFollowupImprovesAggregate": True,
            "stableMiddleThirdFollowupImprovesWeakWindow": False,
            "stableMiddleThirdFollowupImprovesRepair": False,
            "stableMiddleThirdFollowupOutcomeZh": "stable middle-third follow-up 局部搜索提升了整体稳定性。",
            "stableMiddleTradeoffFollowupBestTradeoff": {
                "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0001",
            },
            "stableMiddleTradeoffFollowupOutcomeZh": "tradeoff 仍未优于 bridge。",
        })

        self.assertEqual(candidate["strategyId"], "hfm_crypto_btc_stable_middle_followup_0002")
        self.assertEqual(candidate["summaryType"], "stableMiddleThirdFollowup")
        self.assertEqual(candidate["strategyFamily"], "stable_middle_third_followup")
        self.assertEqual(
            candidate["sourceArtifact"],
            "btcStrategyScan.nextFocusedSearchPlan.stableMiddleThirdFollowupBestTradeoff",
        )
        self.assertEqual(candidate["labelZh"], "stable middle-third aggregate-stability fallback")
        self.assertEqual(candidate["roleZh"], "第三条 distinct 稳定 fallback 路径")
        self.assertTrue(candidate["improvementFlags"]["stableMiddleThirdFollowupImprovesAggregate"])
        self.assertFalse(candidate["improvementFlags"]["stableMiddleThirdFollowupImprovesWeakWindow"])

    def test_btc_focused_queue_uses_followup_repair_metadata_when_followup_is_selected(self) -> None:
        queue = _btc_focused_retest_queue(
            btc={
                "focusedRetestQueue": [
                    {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003"},
                    {"strategyId": "hfm_crypto_btc_near_live_middle_window_0021"},
                ],
                "windowHealth": {"selectedDefault": {}},
            },
            strategy_shortlist={
                "btcTopStrategies": [
                    {
                        "role": "stableAnchor",
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "strategyName": "hfm_crypto_btc_near_live_middle_window_0003",
                        "strategyFamily": "near_live_middle_window",
                        "status": "READY",
                        "metrics": {"validWindowCount": 5},
                        "params": {},
                        "blockers": [],
                        "selectionBasis": {"sourceArtifact": "scan.stable"},
                    },
                    {
                        "role": "stabilityAlternative",
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "strategyName": "hfm_crypto_btc_near_live_middle_window_0021",
                        "strategyFamily": "near_live_middle_window",
                        "status": "READY",
                        "metrics": {"validWindowCount": 5},
                        "params": {},
                        "blockers": [],
                        "selectionBasis": {"sourceArtifact": "scan.challenger"},
                    },
                    {
                        "role": "highYieldTradeoff",
                        "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                        "strategyName": "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                        "strategyFamily": "near_live_stoploss_ladder",
                        "status": "READY",
                        "metrics": {"validWindowCount": 5},
                        "params": {},
                        "blockers": [],
                        "selectionBasis": {"sourceArtifact": "scan.yield"},
                    },
                ],
                "btcLineupBoard": {
                    "recommendedFocusedRetestOrder": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_middle_window_0021",
                        "hfm_crypto_btc_stable_middle_followup_0002",
                    ],
                    "repairStrategyId": "hfm_crypto_btc_stable_middle_followup_0002",
                    "repairStrategyLabelZh": "stable middle-third aggregate-stability fallback",
                    "stableMiddleThirdFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_followup_0002",
                        "pnlUsd": 38.0,
                        "sharpe": 1.29,
                        "tradeCount": 69,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                    "stableMiddleThirdFollowupImprovesAggregate": True,
                    "stableMiddleThirdFollowupImprovesWeakWindow": False,
                    "stableMiddleThirdFollowupImprovesRepair": False,
                    "stableMiddleThirdFollowupOutcomeZh": "stable middle-third follow-up 局部搜索提升了整体稳定性。",
                    "stableMiddleTradeoffFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0001",
                        "pnlUsd": 5.7,
                    },
                    "stableMiddleTradeoffFollowupImprovesBridge": False,
                    "stableMiddleTradeoffFollowupImprovesWeakWindow": False,
                    "stableMiddleTradeoffFollowupImprovesBaseline": False,
                    "stableMiddleTradeoffFollowupOutcomeZh": "tradeoff 仍未优于 bridge。",
                },
            },
        )

        repair_row = next(row for row in queue if row["role"] == "repairObservation")
        self.assertEqual(repair_row["strategyId"], "hfm_crypto_btc_stable_middle_followup_0002")
        self.assertEqual(repair_row["summaryType"], "stableMiddleThirdFollowup")
        self.assertEqual(repair_row["strategyFamily"], "stable_middle_third_followup")
        self.assertEqual(
            repair_row["selectionBasis"]["sourceArtifact"],
            "btcStrategyScan.nextFocusedSearchPlan.stableMiddleThirdFollowupBestTradeoff",
        )
        self.assertTrue(repair_row["selectionBasis"]["stableMiddleThirdFollowupImprovesAggregate"])
        self.assertIn("整体稳定性", repair_row["nextActionZh"])

    def test_operator_aliases_prefer_current_near_live_cluster_over_legacy_lineage(self) -> None:
        aliases = _alias_strategy_ids_without_self(
            {
                "sameParameterSetAs": [
                    "hfm_crypto_btc_near_live_followup_0015",
                    "hfm_crypto_btc_near_live_middle_window_0021",
                    "hfm_crypto_btc_near_live_refinement_0002",
                    "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                    "hfm_crypto_btc_near_live_stability_0003",
                ]
            },
            "hfm_crypto_btc_near_live_middle_window_0003",
        )

        self.assertEqual(
            aliases,
            [
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_stoploss_ladder_0001",
            ],
        )

    def test_current_near_live_cluster_aliases_fall_back_to_converged_runtime_triplet(self) -> None:
        aliases = _current_near_live_cluster_aliases(
            {
                "nearLiveChallengerConvergedWithYieldFrontier": True,
                "mostStableTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                },
                "highYieldTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                },
                "nearLiveStabilityTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                },
                "nearLiveStoplossLadderRefinementBestTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                },
                "nearLiveClusterRefinementBestTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_cluster_refinement_0012",
                },
            },
            "hfm_crypto_btc_near_live_middle_window_0021",
        )

        self.assertEqual(
            aliases,
            [
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_near_live_stoploss_ladder_0001",
            ],
        )

    def test_btc_shortlist_promotes_near_live_repair_when_it_improves_baseline(self) -> None:
        shortlist = _btc_shortlist(
            final_pick={
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "strategyName": "hfm_crypto_btc_tpsl_0302",
                "strategyFamily": "ema_slope_regime",
                "status": "BTC_STABLE_READY",
                "metrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "tpSlSummary": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 6,
                },
                "blockers": [],
                "validWindowCount": 5,
                "windowCount": 6,
            },
            btc={
                "recommendedStable": {
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 300.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                    "validWindowCount": 5,
                    "windowCount": 6,
                },
                "status": "BTC_TPSL_READY",
            },
            scan={
                "status": "BTC_NEXT_FOCUSED_SEARCH_READY",
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                        "strategyFamily": "ema_slope_regime",
                        "status": "READY",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                        "parameters": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "blockers": [],
                    }
                ],
                "nextFocusedSearchPlan": {
                    "nearLiveStabilityTradeoff": {
                        "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                        "pnlUsd": 52.7,
                        "sharpe": 1.3613,
                        "tradeCount": 74,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 400.0,
                        "stopLossPriceMove": 600.0,
                        "maxHoldBars": 16,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityRepairBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_stability_0003",
                        "pnlUsd": 48.3852,
                        "sharpe": 1.5646,
                        "tradeCount": 80,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityRepairImprovesBaseline": True,
                    "nearLiveStabilityRepairOutcomeZh": "near-live stability 局部搜索已找到比当前 sample-balanced challenger 更强的第二候选；下一轮优先围绕修复版做复验。",
                    "highYieldTradeoff": {
                        "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                        "pnlUsd": 72.4,
                        "sharpe": 1.987,
                        "tradeCount": 47,
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 750.0,
                        "stopLossPriceMove": 400.0,
                        "maxHoldBars": 36,
                        "cooldownBars": 6,
                    },
                },
            },
        )

        self.assertEqual(shortlist[1]["strategyId"], "hfm_crypto_btc_near_live_stability_0003")
        self.assertEqual(shortlist[1]["role"], "stabilityAlternative")
        self.assertEqual(
            shortlist[1]["selectionBasis"]["nearLiveBaselineStrategyId"],
            "hfm_crypto_btc_sample_balanced_both_shadow_v1",
        )
        self.assertTrue(shortlist[1]["selectionBasis"]["nearLiveRepairImprovesBaseline"])

    def test_btc_shortlist_promotes_near_live_followup_when_it_improves_repair(self) -> None:
        shortlist = _btc_shortlist(
            final_pick={
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "strategyName": "hfm_crypto_btc_tpsl_0302",
                "strategyFamily": "ema_slope_regime",
                "status": "BTC_STABLE_READY",
                "metrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "tpSlSummary": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 6,
                },
                "blockers": [],
                "validWindowCount": 5,
                "windowCount": 6,
            },
            btc={
                "recommendedStable": {
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 300.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                    "validWindowCount": 5,
                    "windowCount": 6,
                },
                "status": "BTC_TPSL_READY",
            },
            scan={
                "status": "BTC_NEXT_FOCUSED_SEARCH_READY",
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                        "strategyFamily": "ema_slope_regime",
                        "status": "READY",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                        "parameters": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "blockers": [],
                    }
                ],
                "nextFocusedSearchPlan": {
                    "nearLiveStabilityTradeoff": {
                        "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                        "pnlUsd": 52.7,
                        "sharpe": 1.3613,
                        "tradeCount": 74,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 400.0,
                        "stopLossPriceMove": 600.0,
                        "maxHoldBars": 16,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityRepairBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_stability_0003",
                        "pnlUsd": 48.3852,
                        "sharpe": 1.5646,
                        "tradeCount": 80,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityRepairImprovesBaseline": True,
                    "nearLiveStabilityRepairOutcomeZh": "near-live stability 局部搜索已找到比当前 sample-balanced challenger 更强的第二候选；下一轮优先围绕修复版做复验。",
                    "nearLiveStabilityFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_followup_0007",
                        "pnlUsd": 50.1,
                        "sharpe": 1.61,
                        "tradeCount": 81,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityFollowupImprovesRepair": True,
                    "nearLiveStabilityFollowupOutcomeZh": "near-live stability follow-up 已找到比当前修复版更强的第二候选；下一轮优先围绕 follow-up 版本继续复验。",
                    "highYieldTradeoff": {
                        "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                        "pnlUsd": 72.4,
                        "sharpe": 1.987,
                        "tradeCount": 47,
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 750.0,
                        "stopLossPriceMove": 400.0,
                        "maxHoldBars": 36,
                        "cooldownBars": 6,
                    },
                },
            },
        )

        self.assertEqual(shortlist[1]["strategyId"], "hfm_crypto_btc_near_live_followup_0007")
        self.assertEqual(shortlist[1]["selectionBasis"]["nearLiveBaselineStrategyId"], "hfm_crypto_btc_sample_balanced_both_shadow_v1")
        self.assertEqual(shortlist[1]["selectionBasis"]["nearLiveRepairBestStrategyId"], "hfm_crypto_btc_near_live_stability_0003")
        self.assertTrue(shortlist[1]["selectionBasis"]["nearLiveFollowupImprovesRepair"])

    def test_btc_shortlist_adds_repair_observation_when_challenger_converges_with_yield(self) -> None:
        shortlist = _btc_shortlist(
            final_pick={
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "strategyName": "hfm_crypto_btc_tpsl_0302",
                "strategyFamily": "ema_slope_regime",
                "status": "BTC_STABLE_READY",
                "metrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "tpSlSummary": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 6,
                },
                "blockers": [],
                "validWindowCount": 5,
                "windowCount": 6,
            },
            btc={
                "recommendedStable": {
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 300.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                    "validWindowCount": 5,
                    "windowCount": 6,
                },
                "status": "BTC_TPSL_READY",
            },
            scan={
                "status": "BTC_NEXT_FOCUSED_SEARCH_READY",
                "topCandidates": [],
                "nextFocusedSearchPlan": {
                    "nearLiveStabilityTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2,
                        "sharpe": 1.78,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_followup_0015",
                        "pnlUsd": 49.0,
                        "sharpe": 1.59,
                        "tradeCount": 80,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityFollowupBestStrategyId": "hfm_crypto_btc_near_live_followup_0015",
                    "nearLiveStabilityFollowupImprovesRepair": True,
                    "nearLiveStabilityFollowupOutcomeZh": "followup 赢过 repair。",
                    "nearLiveMiddleWindowFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2,
                        "sharpe": 1.78,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveMiddleWindowFollowupBestStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "nearLiveMiddleWindowFollowupImprovesFollowup": False,
                    "nearLiveMiddleWindowFollowupOutcomeZh": "middle-window winner 仍未推翻 followup。",
                    "highYieldTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2,
                        "sharpe": 1.78,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "stableMiddleTradeoffFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                        "pnlUsd": 29.1,
                        "sharpe": 1.03,
                        "tradeCount": 64,
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                    "stableMiddleTradeoffFollowupBestStrategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    "stableMiddleTradeoffFollowupImprovesBridge": True,
                    "stableMiddleTradeoffFollowupImprovesWeakWindow": False,
                    "stableMiddleTradeoffFollowupImprovesBaseline": False,
                    "stableMiddleTradeoffFollowupOutcomeZh": "tradeoff 作为下一条观察线。",
                },
            },
        )

        self.assertEqual(
            [row["strategyId"] for row in shortlist],
            [
                "hfm_crypto_btc_tpsl_0302",
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_stable_middle_tradeoff_0046",
            ],
        )
        self.assertEqual(shortlist[2]["role"], "repairObservation")

    def test_btc_shortlist_promotes_near_live_refinement_when_it_improves_followup(self) -> None:
        shortlist = _btc_shortlist(
            final_pick={
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "strategyName": "hfm_crypto_btc_tpsl_0302",
                "strategyFamily": "ema_slope_regime",
                "status": "BTC_STABLE_READY",
                "metrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "tpSlSummary": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 6,
                },
                "blockers": [],
                "validWindowCount": 5,
                "windowCount": 6,
            },
            btc={
                "recommendedStable": {
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 300.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                    "validWindowCount": 5,
                    "windowCount": 6,
                },
                "status": "BTC_TPSL_READY",
            },
            scan={
                "status": "BTC_NEXT_FOCUSED_SEARCH_READY",
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                        "strategyFamily": "ema_slope_regime",
                        "status": "READY",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                        "parameters": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "blockers": [],
                    }
                ],
                "nextFocusedSearchPlan": {
                    "nearLiveStabilityTradeoff": {
                        "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                        "pnlUsd": 52.7,
                        "sharpe": 1.3613,
                        "tradeCount": 74,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 400.0,
                        "stopLossPriceMove": 600.0,
                        "maxHoldBars": 16,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityRepairBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_stability_0003",
                        "pnlUsd": 48.3852,
                        "sharpe": 1.5646,
                        "tradeCount": 80,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityRepairImprovesBaseline": True,
                    "nearLiveStabilityFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_followup_0007",
                        "pnlUsd": 50.1,
                        "sharpe": 1.61,
                        "tradeCount": 81,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityFollowupImprovesRepair": True,
                    "nearLiveStabilityRefinementBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_refinement_0005",
                        "pnlUsd": 50.4,
                        "sharpe": 1.72,
                        "tradeCount": 82,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityRefinementImprovesFollowup": True,
                    "nearLiveStabilityRefinementOutcomeZh": "near-live stability refinement 已找到比当前 follow-up 更强的第二候选；下一轮优先围绕 refinement 版本继续复验。",
                    "highYieldTradeoff": {
                        "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                        "pnlUsd": 72.4,
                        "sharpe": 1.987,
                        "tradeCount": 47,
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 750.0,
                        "stopLossPriceMove": 400.0,
                        "maxHoldBars": 36,
                        "cooldownBars": 6,
                    },
                },
            },
        )

        self.assertEqual(shortlist[1]["strategyId"], "hfm_crypto_btc_near_live_refinement_0005")
        self.assertEqual(shortlist[1]["selectionBasis"]["nearLiveBaselineStrategyId"], "hfm_crypto_btc_sample_balanced_both_shadow_v1")
        self.assertEqual(shortlist[1]["selectionBasis"]["nearLiveRepairBestStrategyId"], "hfm_crypto_btc_near_live_stability_0003")
        self.assertEqual(shortlist[1]["selectionBasis"]["nearLiveFollowupBestStrategyId"], "hfm_crypto_btc_near_live_followup_0007")
        self.assertTrue(shortlist[1]["selectionBasis"]["nearLiveRefinementImprovesFollowup"])

    def test_btc_shortlist_promotes_near_live_middle_window_when_it_improves_followup(self) -> None:
        shortlist = _btc_shortlist(
            final_pick={
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "strategyName": "hfm_crypto_btc_tpsl_0302",
                "strategyFamily": "ema_slope_regime",
                "status": "BTC_STABLE_READY",
                "metrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "tpSlSummary": {"bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 300.0, "maxHoldBars": 8, "cooldownBars": 6},
                "blockers": [],
                "validWindowCount": 5,
                "windowCount": 6,
            },
            btc={
                "recommendedStable": {"parameters": {"bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 300.0, "maxHoldBars": 8, "cooldownBars": 6}, "validWindowCount": 5, "windowCount": 6},
                "status": "BTC_TPSL_READY",
            },
            scan={
                "status": "BTC_NEXT_FOCUSED_SEARCH_READY",
                "topCandidates": [{
                    "strategyId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                    "strategyFamily": "ema_slope_regime",
                    "status": "READY",
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                    "parameters": {"bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 300.0, "maxHoldBars": 8, "cooldownBars": 6},
                    "blockers": [],
                }],
                "nextFocusedSearchPlan": {
                    "nearLiveStabilityTradeoff": {"strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1", "pnlUsd": 52.7, "sharpe": 1.3613, "tradeCount": 74, "validWindowCount": 4, "windowCount": 6, "bias": "both", "takeProfitPriceMove": 400.0, "stopLossPriceMove": 600.0, "maxHoldBars": 16, "cooldownBars": 4},
                    "nearLiveStabilityRepairBestTradeoff": {"strategyId": "hfm_crypto_btc_near_live_stability_0003", "pnlUsd": 48.3852, "sharpe": 1.5646, "tradeCount": 80, "validWindowCount": 4, "windowCount": 6, "bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 350.0, "maxHoldBars": 8, "cooldownBars": 4},
                    "nearLiveStabilityRepairImprovesBaseline": True,
                    "nearLiveStabilityFollowupBestTradeoff": {"strategyId": "hfm_crypto_btc_near_live_followup_0007", "pnlUsd": 50.1, "sharpe": 1.61, "tradeCount": 81, "validWindowCount": 4, "windowCount": 6, "bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 350.0, "maxHoldBars": 8, "cooldownBars": 4},
                    "nearLiveStabilityFollowupImprovesRepair": True,
                    "nearLiveMiddleWindowFollowupBestTradeoff": {"strategyId": "hfm_crypto_btc_near_live_middle_window_0005", "pnlUsd": 49.9, "sharpe": 1.6, "tradeCount": 82, "validWindowCount": 4, "windowCount": 6, "bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 325.0, "maxHoldBars": 6, "cooldownBars": 4},
                    "nearLiveMiddleWindowFollowupImprovesFollowup": True,
                    "nearLiveMiddleWindowFollowupOutcomeZh": "near-live middle-window follow-up 已在保住当前有效窗口数的前提下改善 middle_third；下一轮优先围绕 middle-window 版本复验。",
                    "highYieldTradeoff": {"strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1", "pnlUsd": 72.4, "sharpe": 1.987, "tradeCount": 47, "validWindowCount": 3, "windowCount": 6, "bias": "both", "takeProfitPriceMove": 750.0, "stopLossPriceMove": 400.0, "maxHoldBars": 36, "cooldownBars": 6},
                },
            },
        )

        self.assertEqual(shortlist[1]["strategyId"], "hfm_crypto_btc_near_live_middle_window_0005")
        self.assertEqual(shortlist[1]["selectionBasis"]["nearLiveFollowupBestStrategyId"], "hfm_crypto_btc_near_live_followup_0007")
        self.assertTrue(shortlist[1]["selectionBasis"]["nearLiveMiddleWindowFollowupImprovesFollowup"])

    def test_btc_shortlist_promotes_scan_most_stable_when_scan_converges(self) -> None:
        shortlist = _btc_shortlist(
            final_pick={
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "strategyName": "hfm_crypto_btc_tpsl_0302",
                "strategyFamily": "ema_slope_regime",
                "status": "BTC_STABLE_READY",
                "metrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "tpSlSummary": {"bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 300.0, "maxHoldBars": 8, "cooldownBars": 6},
                "blockers": [],
                "validWindowCount": 5,
                "windowCount": 6,
            },
            btc={
                "recommendedStable": {"parameters": {"bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 300.0, "maxHoldBars": 8, "cooldownBars": 6}, "validWindowCount": 5, "windowCount": 6},
                "status": "BTC_TPSL_READY",
            },
            scan={
                "status": "BTC_NEXT_FOCUSED_SEARCH_READY",
                "topRecommendation": {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003"},
                "mostStableTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "strategyFamily": "near_live_middle_window",
                    "status": "READY",
                    "pnlUsd": 54.2343,
                    "sharpe": 1.7858,
                    "tradeCount": 80,
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "currentHighestYieldTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "strategyFamily": "near_live_middle_window",
                        "status": "READY",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                        "parameters": {"bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 325.0, "maxHoldBars": 8, "cooldownBars": 4},
                        "blockers": [],
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "strategyFamily": "near_live_middle_window",
                        "status": "READY",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                        "parameters": {"bias": "short", "takeProfitPriceMove": 450.0, "stopLossPriceMove": 300.0, "maxHoldBars": 8, "cooldownBars": 4},
                        "blockers": [],
                    },
                ],
                "nextFocusedSearchPlan": {
                    "mostStableTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2343,
                        "sharpe": 1.7858,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "highYieldTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2343,
                        "sharpe": 1.7858,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveMiddleWindowFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2343,
                        "sharpe": 1.7858,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveMiddleWindowFollowupImprovesFollowup": True,
                    "nearLiveChallengerConvergedWithYieldFrontier": True,
                    "stableMiddleTradeoffFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                        "pnlUsd": 29.068,
                        "sharpe": 1.0329,
                        "tradeCount": 64,
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                    "stableMiddleTradeoffFollowupImprovesBaseline": True,
                },
            },
        )

        self.assertEqual(shortlist[0]["strategyId"], "hfm_crypto_btc_near_live_middle_window_0003")
        self.assertEqual(shortlist[0]["role"], "stableAnchor")
        self.assertEqual(shortlist[1]["strategyId"], "hfm_crypto_btc_near_live_middle_window_0021")
        self.assertEqual(shortlist[1]["role"], "stabilityAlternative")
        self.assertIn("next distinct near-live contender", shortlist[1]["nextActionZh"])
        self.assertIn("next distinct near-live contender", shortlist[1]["selectionBasis"]["selectionReasonZh"])
        self.assertEqual(shortlist[2]["strategyId"], "hfm_crypto_btc_stable_middle_tradeoff_0046")
        self.assertEqual(shortlist[2]["role"], "repairObservation")

    def test_btc_lineup_board_exposes_stability_first_top3_separately_from_yield_inclusive_top3(self) -> None:
        board = _btc_lineup_board(
            [
                {
                    "role": "stableAnchor",
                    "strategyId": "hfm_crypto_btc_tpsl_0302",
                    "metrics": {"validWindowCount": 5, "tradeCount": 69, "sharpe": 1.326, "pnlUsd": 38.7},
                    "selectionBasis": {
                        "sameParameterSetAs": ["hfm_crypto_btc_stability_short_window_shadow_v1"],
                        "stableMiddleTradeoffFollowupBestTradeoff": {
                            "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0025",
                            "pnlUsd": 48.3852,
                            "sharpe": 1.5646,
                            "tradeCount": 80,
                            "validWindowCount": 4,
                            "windowCount": 6,
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 350.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 4,
                        },
                        "stableMiddleTradeoffFollowupBestStrategyId": "hfm_crypto_btc_stable_middle_tradeoff_0025",
                        "stableMiddleTradeoffFollowupImprovesBridge": True,
                        "stableMiddleTradeoffFollowupImprovesWeakWindow": True,
                        "stableMiddleTradeoffFollowupImprovesBaseline": True,
                        "stableMiddleTradeoffFollowupOutcomeZh": "tradeoff 已兼顾 2+ valid windows 与 middle_third 改善。",
                    },
                },
                {
                    "role": "stabilityAlternative",
                    "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                    "metrics": {"validWindowCount": 4, "tradeCount": 74, "sharpe": 1.3613, "pnlUsd": 52.7},
                    "selectionBasis": {"nearLiveRepairBestStrategyId": "hfm_crypto_btc_near_live_stability_0099"},
                },
                {
                    "role": "highYieldTradeoff",
                    "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                    "metrics": {"validWindowCount": 3, "tradeCount": 47, "sharpe": 1.987, "pnlUsd": 72.4},
                    "selectionBasis": {
                        "sameParameterSetAs": ["hfm_crypto_btc_tpsl_4138"],
                        "yieldLeaderConfirmationBestStrategyId": "hfm_crypto_btc_yield_leader_confirmation_0018",
                        "yieldLeaderConfirmationImprovesBaseline": False,
                        "yieldLeaderConfirmationOutcomeZh": "yield leader 未翻盘。",
                    },
                },
            ],
            {
                "btc": {
                    "strongestYieldFrontierDriftDetected": False,
                    "strongestYieldOptimizerBaselineStrategyId": None,
                }
            },
        )

        self.assertEqual(
            board["stabilityFirstTop3StrategyIds"],
            [
                "hfm_crypto_btc_tpsl_0302",
                "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "hfm_crypto_btc_stable_middle_tradeoff_0025",
            ],
        )
        self.assertEqual(
            board["yieldInclusiveTop3StrategyIds"],
            [
                "hfm_crypto_btc_tpsl_0302",
                "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "hfm_crypto_btc_yield_balanced_both_shadow_v1",
            ],
        )
        self.assertIn("stable_middle_tradeoff_0025", board["stabilityFirstSummaryZh"])
        self.assertIn("yield_balanced_both_shadow_v1", board["yieldInclusiveSummaryZh"])

    def test_btc_lineup_board_uses_current_challenger_basis_when_yield_converges(self) -> None:
        board = _btc_lineup_board(
            [
                {
                    "role": "stableAnchor",
                    "strategyId": "hfm_crypto_btc_tpsl_0302",
                    "metrics": {"validWindowCount": 5, "tradeCount": 69, "sharpe": 1.326, "pnlUsd": 38.7},
                    "selectionBasis": {},
                },
                {
                    "role": "highYieldTradeoff",
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "metrics": {"validWindowCount": 5, "tradeCount": 80, "sharpe": 1.7858, "pnlUsd": 54.2343},
                    "selectionBasis": {
                        "nearLiveFollowupBestStrategyId": "hfm_crypto_btc_near_live_followup_0015",
                        "nearLiveFollowupImprovesRepair": True,
                        "nearLiveFollowupOutcomeZh": "followup 仍是现任第二候选。",
                        "nearLiveMiddleWindowFollowupBestStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "nearLiveMiddleWindowFollowupImprovesFollowup": False,
                        "nearLiveMiddleWindowFollowupOutcomeZh": "middle-window family 尚未推翻 followup。",
                        "yieldLeaderConfirmationBestStrategyId": "hfm_crypto_btc_yield_leader_confirmation_0018",
                        "yieldLeaderConfirmationImprovesBaseline": False,
                        "yieldLeaderConfirmationOutcomeZh": "yield leader 未翻盘。",
                    },
                },
                {
                    "role": "repairObservation",
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    "metrics": {"validWindowCount": 3, "tradeCount": 64, "sharpe": 1.0329, "pnlUsd": 29.068},
                    "selectionBasis": {
                        "stableMiddleTradeoffFollowupBestStrategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                        "stableMiddleTradeoffFollowupImprovesBridge": True,
                        "stableMiddleTradeoffFollowupImprovesWeakWindow": False,
                        "stableMiddleTradeoffFollowupImprovesBaseline": False,
                        "stableMiddleTradeoffFollowupOutcomeZh": "tradeoff 仍是下一条观察线。",
                    },
                },
            ],
            {"btc": {"strongestYieldFrontierDriftDetected": False, "strongestYieldOptimizerBaselineStrategyId": None}},
            scan={
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "parameters": {"stopLossPriceMove": 325.0, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "parameters": {"stopLossPriceMove": 300.0, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0013",
                        "parameters": {"stopLossPriceMove": 312.5, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                ]
            },
        )

        self.assertTrue(board["challengerConvergedWithYieldFrontier"])
        self.assertEqual(board["nearLiveChallengerStrategyId"], "hfm_crypto_btc_near_live_middle_window_0003")
        self.assertEqual(board["nearLiveFollowupBestStrategyId"], "hfm_crypto_btc_near_live_followup_0015")
        self.assertFalse(board["nearLiveMiddleWindowFollowupImprovesFollowup"])
        self.assertEqual(
            board["yieldInclusiveTop3StrategyIds"],
            [
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_stoploss_ladder_0013",
            ],
        )

    def test_btc_lineup_board_surfaces_near_live_middle_window_variant_ladder(self) -> None:
        board = _btc_lineup_board(
            [
                {
                    "role": "stableAnchor",
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "metrics": {"validWindowCount": 5, "tradeCount": 80, "sharpe": 1.7858, "pnlUsd": 54.2343},
                    "selectionBasis": {
                        "nearLiveSignalRefinementBestStrategyId": "hfm_crypto_btc_near_live_signal_refinement_0008",
                        "nearLiveSignalRefinementImprovesContender": True,
                        "nearLiveSignalRefinementOutcomeZh": "near-live signal refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 signal-kernel 版本做 near-live 复验。",
                        "nearLiveTempoRefinementBestStrategyId": "hfm_crypto_btc_near_live_tempo_refinement_0009",
                        "nearLiveTempoRefinementImprovesContender": True,
                        "nearLiveTempoRefinementOutcomeZh": "near-live tempo refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 hold/cooldown 节奏版本做 near-live 复验。",
                        "nearLiveStoplossLadderRefinementBestStrategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0013",
                        "nearLiveStoplossLadderRefinementImprovesContender": True,
                        "nearLiveStoplossLadderRefinementOutcomeZh": "near-live stop-loss ladder refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 stop-loss ladder 版本做 near-live 复验。",
                        "nearLiveExitRefinementBestStrategyId": "hfm_crypto_btc_near_live_exit_refinement_0011",
                        "nearLiveExitRefinementImprovesContender": True,
                        "nearLiveExitRefinementOutcomeZh": "near-live exit refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 TP/SL exit 版本做 near-live 复验。",
                        "nearLiveClusterRefinementBestStrategyId": "hfm_crypto_btc_near_live_cluster_refinement_0007",
                        "nearLiveClusterRefinementImprovesContender": True,
                        "nearLiveClusterRefinementOutcomeZh": "near-live converged-cluster refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕该变体继续 near-live 复验。",
                        "nearLiveMiddleTradeoffBestStrategyId": "hfm_crypto_btc_near_live_middle_tradeoff_0004",
                        "nearLiveMiddleTradeoffImprovesContender": True,
                        "nearLiveMiddleTradeoffOutcomeZh": "near-live middle tradeoff 已在保住收敛簇有效窗口数的前提下改善 middle_third；下一轮优先围绕该 next distinct contender 继续 near-live 复验。",
                        "nearLiveMiddleDensityLiftBestStrategyId": "hfm_crypto_btc_near_live_middle_density_0006",
                        "nearLiveMiddleDensityLiftImprovesContender": True,
                        "nearLiveMiddleDensityLiftOutcomeZh": "near-live middle-density lift 已在保住收敛簇有效窗口数的前提下改善 middle_third 样本密度；下一轮优先围绕该 next distinct contender 继续 near-live 复验。",
                    },
                },
                {
                    "role": "stabilityAlternative",
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                    "metrics": {"validWindowCount": 5, "tradeCount": 80, "sharpe": 1.7858, "pnlUsd": 54.2343},
                    "selectionBasis": {
                        "nearLiveSignalRefinementBestStrategyId": "hfm_crypto_btc_near_live_signal_refinement_0008",
                        "nearLiveSignalRefinementImprovesContender": True,
                        "nearLiveSignalRefinementOutcomeZh": "near-live signal refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 signal-kernel 版本做 near-live 复验。",
                        "nearLiveTempoRefinementBestStrategyId": "hfm_crypto_btc_near_live_tempo_refinement_0009",
                        "nearLiveTempoRefinementImprovesContender": True,
                        "nearLiveTempoRefinementOutcomeZh": "near-live tempo refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 hold/cooldown 节奏版本做 near-live 复验。",
                        "nearLiveStoplossLadderRefinementBestStrategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0013",
                        "nearLiveStoplossLadderRefinementImprovesContender": True,
                        "nearLiveStoplossLadderRefinementOutcomeZh": "near-live stop-loss ladder refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 stop-loss ladder 版本做 near-live 复验。",
                        "nearLiveExitRefinementBestStrategyId": "hfm_crypto_btc_near_live_exit_refinement_0011",
                        "nearLiveExitRefinementImprovesContender": True,
                        "nearLiveExitRefinementOutcomeZh": "near-live exit refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕 TP/SL exit 版本做 near-live 复验。",
                        "nearLiveClusterRefinementBestStrategyId": "hfm_crypto_btc_near_live_cluster_refinement_0007",
                        "nearLiveClusterRefinementImprovesContender": True,
                        "nearLiveClusterRefinementOutcomeZh": "near-live converged-cluster refinement 已在不替换主锚点的前提下找到更强的 next distinct contender；下一轮优先围绕该变体继续 near-live 复验。",
                        "nearLiveMiddleTradeoffBestStrategyId": "hfm_crypto_btc_near_live_middle_tradeoff_0004",
                        "nearLiveMiddleTradeoffImprovesContender": True,
                        "nearLiveMiddleTradeoffOutcomeZh": "near-live middle tradeoff 已在保住收敛簇有效窗口数的前提下改善 middle_third；下一轮优先围绕该 next distinct contender 继续 near-live 复验。",
                        "nearLiveMiddleDensityLiftBestStrategyId": "hfm_crypto_btc_near_live_middle_density_0006",
                        "nearLiveMiddleDensityLiftImprovesContender": True,
                        "nearLiveMiddleDensityLiftOutcomeZh": "near-live middle-density lift 已在保住收敛簇有效窗口数的前提下改善 middle_third 样本密度；下一轮优先围绕该 next distinct contender 继续 near-live 复验。",
                    },
                },
                {
                    "role": "repairObservation",
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    "metrics": {"validWindowCount": 3, "tradeCount": 64, "sharpe": 1.0329, "pnlUsd": 29.068},
                    "selectionBasis": {},
                },
            ],
            {"btc": {"strongestYieldFrontierDriftDetected": True, "strongestYieldOptimizerBaselineStrategyId": "hfm_crypto_btc_tpsl_4138"}},
            scan={
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "parameters": {"stopLossPriceMove": 325.0, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "parameters": {"stopLossPriceMove": 300.0, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0013",
                        "parameters": {"stopLossPriceMove": 312.5, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0040",
                        "parameters": {"stopLossPriceMove": 350.0, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 53.1707, "sharpe": 1.7384, "tradeCount": 80},
                    },
                ]
            },
        )

        self.assertEqual(
            board["nearLiveMiddleWindowVariantStrategyIds"],
            [
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_middle_window_0040",
            ],
        )
        self.assertEqual(board["nearLiveMiddleWindowVariantStopLossLadder"], [325.0, 300.0, 350.0])
        self.assertIn("0040", board["nearLiveMiddleWindowVariantSummaryZh"])
        self.assertIn("SL=300.0", board["nearLiveMiddleWindowVariantSummaryZh"])
        self.assertEqual(
            board["nearLiveConvergedVariantStrategyIds"],
            [
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_stoploss_ladder_0013",
            ],
        )
        self.assertEqual(board["nearLiveConvergedVariantStopLossLadder"], [325.0, 300.0, 312.5])
        self.assertIn("收敛簇前排变体", board["nearLiveConvergedVariantSummaryZh"])
        self.assertIn("stoploss_ladder_0013", board["nearLiveConvergedVariantSummaryZh"])
        self.assertEqual(board["nearLiveClusterRefinementBestStrategyId"], "hfm_crypto_btc_near_live_cluster_refinement_0007")
        self.assertTrue(board["nearLiveClusterRefinementImprovesContender"])
        self.assertEqual(board["nearLiveSignalRefinementBestStrategyId"], "hfm_crypto_btc_near_live_signal_refinement_0008")
        self.assertTrue(board["nearLiveSignalRefinementImprovesContender"])
        self.assertIn("signal-kernel", board["nearLiveSignalRefinementOutcomeZh"])
        self.assertEqual(board["nearLiveTempoRefinementBestStrategyId"], "hfm_crypto_btc_near_live_tempo_refinement_0009")
        self.assertTrue(board["nearLiveTempoRefinementImprovesContender"])
        self.assertIn("hold/cooldown", board["nearLiveTempoRefinementOutcomeZh"])
        self.assertEqual(board["nearLiveStoplossLadderRefinementBestStrategyId"], "hfm_crypto_btc_near_live_stoploss_ladder_0013")
        self.assertTrue(board["nearLiveStoplossLadderRefinementImprovesContender"])
        self.assertIn("stop-loss ladder", board["nearLiveStoplossLadderRefinementOutcomeZh"])
        self.assertEqual(board["nearLiveExitRefinementBestStrategyId"], "hfm_crypto_btc_near_live_exit_refinement_0011")
        self.assertTrue(board["nearLiveExitRefinementImprovesContender"])
        self.assertIn("TP/SL exit", board["nearLiveExitRefinementOutcomeZh"])
        self.assertEqual(board["nearLiveMiddleTradeoffBestStrategyId"], "hfm_crypto_btc_near_live_middle_tradeoff_0004")
        self.assertTrue(board["nearLiveMiddleTradeoffImprovesContender"])
        self.assertIn("middle tradeoff", board["nearLiveMiddleTradeoffOutcomeZh"])
        self.assertEqual(board["nearLiveMiddleDensityLiftBestStrategyId"], "hfm_crypto_btc_near_live_middle_density_0006")
        self.assertTrue(board["nearLiveMiddleDensityLiftImprovesContender"])
        self.assertIn("middle-density", board["nearLiveMiddleDensityLiftOutcomeZh"])

    def test_btc_lineup_board_surfaces_converged_variant_ladder_with_cluster_refinement(self) -> None:
        board = _btc_lineup_board(
            [
                {
                    "role": "stableAnchor",
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "metrics": {"validWindowCount": 5, "tradeCount": 80, "sharpe": 1.7858, "pnlUsd": 54.2343},
                    "selectionBasis": {},
                },
                {
                    "role": "stabilityAlternative",
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                    "metrics": {"validWindowCount": 5, "tradeCount": 80, "sharpe": 1.7858, "pnlUsd": 54.2343},
                    "selectionBasis": {},
                },
                {
                    "role": "repairObservation",
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    "metrics": {"validWindowCount": 3, "tradeCount": 64, "sharpe": 1.0329, "pnlUsd": 29.068},
                    "selectionBasis": {},
                },
            ],
            {"btc": {"strongestYieldFrontierDriftDetected": False, "strongestYieldOptimizerBaselineStrategyId": None}},
            scan={
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "parameters": {"stopLossPriceMove": 325.0, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "parameters": {"stopLossPriceMove": 300.0, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0013",
                        "parameters": {"stopLossPriceMove": 312.5, "takeProfitPriceMove": 450.0, "cooldownBars": 4, "maxHoldBars": 8},
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                ]
            },
        )

        self.assertEqual(
            board["nearLiveConvergedVariantStrategyIds"],
            [
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_stoploss_ladder_0013",
            ],
        )
        self.assertEqual(board["nearLiveConvergedVariantStopLossLadder"], [325.0, 300.0, 312.5])
        self.assertIn("near_live_stoploss_ladder_0013", board["nearLiveConvergedVariantSummaryZh"])

    def test_btc_top_level_default_stable_tracks_converged_shortlist_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            profit = runtime / "profit_target"
            agent.mkdir(parents=True)
            profit.mkdir(parents=True)

            self._write_json(agent / "QuantGod_AceStrategyScout.json", {
                "topQualifiedForex": {},
                "topQualifiedCrypto": {},
            })
            self._write_json(agent / "QuantGod_ChampionRetestReport.json", {
                "cryptoChampion": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "fullWindowMetrics": {
                        "agentId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2343,
                        "roiPct": 5.4234,
                        "sharpe": 1.7858,
                        "maxDrawdownPct": 1.1824,
                        "tradeCount": 80,
                        "liquidationCount": 0,
                    },
                    "candidateRetests": [],
                },
                "forexChampion": {},
            })
            self._write_json(agent / "QuantGod_TpSlOptimizerReport.json", {
                "btcCryptoCfd": {
                    "status": "BTC_TPSL_SCAN_READY",
                    "finalAdvisoryPickPolicy": "STABLE_OVER_TARGET_SEEKING",
                    "finalAdvisoryPickReasonZh": "旧 optimizer 仍建议 0302。",
                    "recommendedStable": {
                        "strategyId": "hfm_crypto_btc_tpsl_0302",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "parameters": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "fullWindowMetrics": {
                            "pnlUsd": 38.7432,
                            "roiPct": 3.8743,
                            "sharpe": 1.326,
                            "maxDrawdownPct": 1.5619,
                            "tradeCount": 69,
                            "liquidationCount": 0,
                        },
                    },
                    "recommendedTargetSeeking": {},
                    "bestHighPnl": {},
                    "finalAdvisoryPick": {
                        "strategyId": "hfm_crypto_btc_tpsl_0302",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "parameters": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "fullWindowMetrics": {
                            "pnlUsd": 38.7432,
                            "roiPct": 3.8743,
                            "sharpe": 1.326,
                            "maxDrawdownPct": 1.5619,
                            "tradeCount": 69,
                            "liquidationCount": 0,
                        },
                    },
                },
                "forexMt5": {},
            })
            self._write_json(agent / "QuantGod_BtcStrategyScanReport.json", {
                "topRecommendation": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "strategyName": "BTCUSD near-live middle-window follow-up scan",
                    "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    "fullWindowMetrics": {
                        "pnlUsd": 54.2343,
                        "roiPct": 5.4234,
                        "sharpe": 1.7858,
                        "maxDrawdownPct": 1.1824,
                        "tradeCount": 80,
                        "liquidationCount": 0,
                    },
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "windowSummary": [],
                },
                "mostStableTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "pnlUsd": 54.2343,
                    "sharpe": 1.7858,
                    "maxDrawdownPct": 1.1824,
                    "tradeCount": 80,
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "currentHighestYieldTradeoff": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "pnlUsd": 54.2343,
                    "sharpe": 1.7858,
                    "maxDrawdownPct": 1.1824,
                    "tradeCount": 80,
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "parameters": {
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 325.0,
                            "cooldownBars": 4,
                            "maxHoldBars": 8,
                        },
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "parameters": {
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "cooldownBars": 4,
                            "maxHoldBars": 8,
                        },
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    },
                ],
                "nextFocusedSearchPlan": {
                    "highYieldTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2343,
                        "sharpe": 1.7858,
                        "maxDrawdownPct": 1.1824,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "mostStableTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2343,
                        "sharpe": 1.7858,
                        "maxDrawdownPct": 1.1824,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "nearLiveStabilityTradeoff": {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "pnlUsd": 54.2343,
                        "sharpe": 1.7858,
                        "maxDrawdownPct": 1.1824,
                        "tradeCount": 80,
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 300.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "stableMiddleTradeoffFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                        "pnlUsd": 29.068,
                        "sharpe": 1.0329,
                        "maxDrawdownPct": 1.7218,
                        "tradeCount": 64,
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 6,
                    },
                    "nearLiveConvergedVariantStrategyIds": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_middle_window_0021",
                        "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                    ],
                    "nearLiveMiddleWindowVariantStrategyIds": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_middle_window_0021",
                    ],
                },
            })
            self._write_json(agent / "QuantGod_ChampionTesterRunGate.json", {"nextTesterWindow": {"status": "closed"}, "gate": {"blockers": []}, "decision": {}})
            self._write_json(agent / "QuantGod_LiveRuntimePreflightProbe.json", {})
            self._write_json(agent / "QuantGod_SimTargetExecutionReviewSummary.json", {})
            self._write_json(agent / "QuantGod_ReleaseTokenSignoffEvidenceMatrix.json", {})
            self._write_json(profit / "QuantGod_ProfitTargetTracker.json", {})

            report = build_ace_execution_candidate_pack(runtime, write=False)

            self.assertEqual(report["decision"]["defaultBtcStrategyId"], "hfm_crypto_btc_near_live_middle_window_0003")
            self.assertEqual(report["btcCryptoCfd"]["defaultStable"]["strategyId"], "hfm_crypto_btc_near_live_middle_window_0003")
            self.assertEqual(report["btcCryptoCfd"]["optimizerStableLegacy"]["strategyId"], "hfm_crypto_btc_tpsl_0302")
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["mostStableSameParameterSetAs"],
                [
                    "hfm_crypto_btc_near_live_middle_window_0021",
                    "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                ],
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldSameParameterSetAs"],
                [
                    "hfm_crypto_btc_near_live_middle_window_0021",
                    "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                ],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][1]["selectionBasis"]["sameParameterSetAs"],
                [
                    "hfm_crypto_btc_near_live_middle_window_0003",
                    "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                ],
            )
            self.assertEqual(
                report["btcCryptoCfd"]["finalAdvisoryPickReasonZh"],
                report["decision"]["btcDefaultReasonZh"],
            )

    def test_strategy_shortlist_item_backfills_selection_reason_alias(self) -> None:
        item = _strategy_shortlist_item(
            lane="btcCryptoCfd",
            role="repairObservation",
            summary_type="stableMiddleTradeoffFollowup",
            strategy_id="hfm_crypto_btc_stable_middle_tradeoff_0046",
            selection_basis={"reasonZh": "作为第三条 distinct 修复线继续观察。"},
        )

        self.assertEqual(
            item["selectionBasis"]["selectionReasonZh"],
            "作为第三条 distinct 修复线继续观察。",
        )

    def test_lane_verdicts_fallback_to_repair_observation_when_no_stability_alternative(self) -> None:
        verdicts = _lane_verdicts(
            [],
            [
                {
                    "role": "stableAnchor",
                    "strategyId": "hfm_crypto_btc_tpsl_0302",
                    "selectionBasis": {"sameParameterSetAs": ["hfm_crypto_btc_stability_short_window_shadow_v1"]},
                },
                {
                    "role": "highYieldTradeoff",
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "selectionBasis": {"sameParameterSetAs": ["hfm_crypto_btc_near_live_followup_0015"]},
                },
                {
                    "role": "repairObservation",
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    "selectionBasis": {"reasonZh": "repair observation fallback"},
                },
            ],
        )

        self.assertEqual(
            verdicts["btc"]["bestAlternative"]["strategyId"],
            "hfm_crypto_btc_stable_middle_tradeoff_0046",
        )
        self.assertIn(
            "repair observation",
            verdicts["btc"]["bestAlternative"]["reasonZh"],
        )

    def test_mt5_countdown_is_recomputed_from_window_start(self) -> None:
        next_window = {
            "label": "daily_night",
            "startJstIso": "2026-06-08T20:10:00+09:00",
            "endJstIso": "2026-06-08T23:30:00+09:00",
            "minutesUntilStart": 302.4,
        }
        with patch(
            "tools.ace_execution_candidate_pack._utc_now",
            return_value=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc),
        ):
            summary = _artifact_summary(Path("unused.json"), {"nextTesterWindow": next_window}, kind="championTesterRunGate")
            snapshot = _mt5_tester_snapshot({"nextTesterWindow": next_window, "gate": {}})
        self.assertEqual(summary["nextTesterWindowMinutesUntilStart"], 70.0)
        self.assertEqual(snapshot["minutesUntilStart"], 70.0)

    def test_mt5_window_briefing_enters_final_hour_mode(self) -> None:
        briefing = _mt5_window_briefing({
            "gateDiagnostics": {
                "minutesUntilStart": 38.1,
            },
            "testerSnapshot": {
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1-usdjpy_tpsl_14r_1_2",
                ],
            },
            "readinessChecklist": {
                "readyCount": 0,
                "totalCount": 7,
                "rows": [
                    {"id": "tester_window_open", "ok": False, "dependencyCheckIds": []},
                    {"id": "dashboard_fresh", "ok": False, "dependencyCheckIds": []},
                    {"id": "authorization_lock_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "isolated_account_context_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "sensitive_sync_cleared", "ok": False, "dependencyCheckIds": ["isolated_account_context_ready"]},
                    {"id": "tester_can_run_now", "ok": False, "dependencyCheckIds": ["dashboard_fresh", "authorization_lock_ready", "isolated_account_context_ready", "sensitive_sync_cleared", "tester_window_open"]},
                ],
            },
        })
        self.assertEqual(briefing["phase"], "PRE_WINDOW_FINAL_HOUR")
        self.assertEqual(
            briefing["preWindowCheckIds"],
            [
                "dashboard_fresh",
                "authorization_lock_ready",
                "isolated_account_context_ready",
                "sensitive_sync_cleared",
            ],
        )
        self.assertEqual(briefing["autoClearCheckIds"], ["tester_window_open"])
        self.assertEqual(
            briefing["residualAfterWindowOpenCheckIds"],
            [
                "dashboard_fresh",
                "authorization_lock_ready",
                "isolated_account_context_ready",
                "sensitive_sync_cleared",
                "tester_can_run_now",
            ],
        )
        self.assertEqual(briefing["readinessNow"]["ratio"], "0/7")
        self.assertEqual(briefing["expectedReadinessAfterWindowOpen"]["ratio"], "1/7")
        self.assertEqual(briefing["windowOpenGainCount"], 1)
        self.assertTrue(briefing["postWindowStillBlocked"])
        self.assertEqual(
            briefing["highestLeveragePreWindowCheckIds"],
            ["isolated_account_context_ready"],
        )
        self.assertIn("38.1", briefing["summaryZh"])
        self.assertIn("g0093-usdjpy-rsi-champion-tester-forward-v1", briefing["summaryZh"])

    def test_mt5_window_briefing_enters_final_30_min_mode(self) -> None:
        briefing = _mt5_window_briefing({
            "gateDiagnostics": {
                "minutesUntilStart": 24.6,
            },
            "testerSnapshot": {
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [],
            },
            "readinessChecklist": {
                "readyCount": 0,
                "totalCount": 7,
                "rows": [
                    {"id": "tester_window_open", "ok": False, "dependencyCheckIds": []},
                    {"id": "dashboard_fresh", "ok": False, "dependencyCheckIds": []},
                    {"id": "live_session_fresh", "ok": False, "dependencyCheckIds": ["dashboard_fresh"]},
                    {"id": "authorization_lock_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "isolated_account_context_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "sensitive_sync_cleared", "ok": False, "dependencyCheckIds": ["isolated_account_context_ready"]},
                    {"id": "tester_can_run_now", "ok": False, "dependencyCheckIds": ["live_session_fresh", "tester_window_open", "authorization_lock_ready", "dashboard_fresh", "isolated_account_context_ready", "sensitive_sync_cleared"]},
                ],
            },
        })
        self.assertEqual(briefing["phase"], "PRE_WINDOW_FINAL_30_MIN")
        self.assertEqual(briefing["windowOpenGainCount"], 1)
        self.assertEqual(briefing["residualAfterWindowOpenCount"], 6)
        self.assertEqual(
            briefing["highestLeveragePreWindowCheckIds"],
            ["dashboard_fresh", "isolated_account_context_ready"],
        )
        self.assertIn("仍剩 6 项未闭环", briefing["windowOpenEffectZh"])
        self.assertTrue(briefing["postWindowStillBlocked"])

    def test_mt5_window_briefing_enters_final_15_min_mode(self) -> None:
        briefing = _mt5_window_briefing({
            "gateDiagnostics": {
                "minutesUntilStart": 12.1,
            },
            "testerSnapshot": {
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [],
            },
            "readinessChecklist": {
                "readyCount": 0,
                "totalCount": 7,
                "rows": [
                    {"id": "tester_window_open", "ok": False, "dependencyCheckIds": []},
                    {"id": "dashboard_fresh", "ok": False, "dependencyCheckIds": []},
                    {"id": "live_session_fresh", "ok": False, "dependencyCheckIds": ["dashboard_fresh"]},
                    {"id": "authorization_lock_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "isolated_account_context_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "sensitive_sync_cleared", "ok": False, "dependencyCheckIds": ["isolated_account_context_ready"]},
                    {"id": "tester_can_run_now", "ok": False, "dependencyCheckIds": ["live_session_fresh", "tester_window_open", "authorization_lock_ready", "dashboard_fresh", "isolated_account_context_ready", "sensitive_sync_cleared"]},
                ],
            },
        })
        self.assertEqual(briefing["phase"], "PRE_WINDOW_FINAL_15_MIN")
        self.assertEqual(
            briefing["finalSprintCheckIds"],
            ["dashboard_fresh", "isolated_account_context_ready"],
        )
        self.assertEqual(
            briefing["highestLeveragePostWindowCheckIds"],
            ["dashboard_fresh", "isolated_account_context_ready"],
        )
        self.assertIn("开窗后第一优先仍是", briefing["postWindowPrimarySummaryZh"])
        self.assertIn("最后冲刺只盯", briefing["summaryZh"])

    def test_mt5_window_briefing_enters_final_5_min_mode(self) -> None:
        briefing = _mt5_window_briefing({
            "gateDiagnostics": {
                "minutesUntilStart": 4.8,
            },
            "testerSnapshot": {
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [],
            },
            "readinessChecklist": {
                "readyCount": 0,
                "totalCount": 7,
                "rows": [
                    {"id": "tester_window_open", "ok": False, "dependencyCheckIds": []},
                    {"id": "dashboard_fresh", "ok": False, "dependencyCheckIds": []},
                    {"id": "live_session_fresh", "ok": False, "dependencyCheckIds": ["dashboard_fresh"]},
                    {"id": "authorization_lock_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "isolated_account_context_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "sensitive_sync_cleared", "ok": False, "dependencyCheckIds": ["isolated_account_context_ready"]},
                    {"id": "tester_can_run_now", "ok": False, "dependencyCheckIds": ["live_session_fresh", "tester_window_open", "authorization_lock_ready", "dashboard_fresh", "isolated_account_context_ready", "sensitive_sync_cleared"]},
                ],
            },
        })
        self.assertEqual(briefing["phase"], "PRE_WINDOW_FINAL_5_MIN")
        self.assertEqual(briefing["finalSprintCheckIds"], ["dashboard_fresh"])
        self.assertIn("最后 5 分钟只盯", briefing["summaryZh"])

    def test_mt5_window_briefing_in_window_reports_realized_gain(self) -> None:
        briefing = _mt5_window_briefing({
            "gateDiagnostics": {
                "minutesUntilStart": 0.0,
            },
            "testerSnapshot": {
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [],
            },
            "readinessChecklist": {
                "readyCount": 1,
                "totalCount": 7,
                "rows": [
                    {"id": "tester_window_open", "ok": True, "dependencyCheckIds": []},
                    {"id": "dashboard_fresh", "ok": False, "dependencyCheckIds": []},
                    {"id": "live_session_fresh", "ok": False, "dependencyCheckIds": ["dashboard_fresh"]},
                    {"id": "authorization_lock_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "isolated_account_context_ready", "ok": False, "dependencyCheckIds": []},
                    {"id": "sensitive_sync_cleared", "ok": False, "dependencyCheckIds": ["isolated_account_context_ready"]},
                    {"id": "tester_can_run_now", "ok": False, "dependencyCheckIds": ["live_session_fresh", "tester_window_open", "authorization_lock_ready", "dashboard_fresh", "isolated_account_context_ready", "sensitive_sync_cleared"]},
                ],
            },
        })
        self.assertEqual(briefing["phase"], "IN_WINDOW")
        self.assertEqual(briefing["windowOpenGainCount"], 1)
        self.assertEqual(briefing["windowOpenRealizedCheckIds"], ["tester_window_open"])
        self.assertIn("窗口已打开，已实得 1 项通过", briefing["windowOpenEffectZh"])

    def test_build_pack_refreshes_stale_scout_before_embedding_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            self._write_json(agent / "QuantGod_AceStrategyScout.json", {
                "generatedAtIso": "2026-06-08T17:00:00Z",
                "topResearchCrypto": {"strategyId": "stale_btc"},
            })
            self._write_json(agent / "QuantGod_ChampionRetestReport.json", {})
            self._write_json(agent / "QuantGod_TpSlOptimizerReport.json", {"btcCryptoCfd": {}})
            self._write_json(agent / "QuantGod_BtcStrategyScanReport.json", {
                "generatedAtIso": "2026-06-08T17:25:10Z",
                "topCandidateStrategyId": "fresh_scan_btc",
                "nextFocusedSearchPlan": {},
                "topCandidates": [],
            })
            self._write_json(agent / "QuantGod_ChampionTesterRunGate.json", {})
            self._write_json(agent / "QuantGod_LiveRuntimePreflightProbe.json", {})
            self._write_json(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json", {})
            self._write_json(agent / "QuantGod_ReleaseTokenSignoffEvidenceMatrix.json", {})
            self._write_json(agent / "QuantGod_SimTargetExecutionReviewSummary.json", {})

            with patch(
                "tools.ace_execution_candidate_pack._resolve_ace_strategy_scout",
                return_value={"generatedAtIso": "2026-06-08T17:30:00Z", "topResearchCrypto": {"strategyId": "fresh_scout_btc"}},
            ):
                report = build_ace_execution_candidate_pack(runtime, write=False)

            self.assertEqual(
                report["sourceArtifactSummaries"]["aceStrategyScout"]["topResearchCryptoStrategyId"],
                "fresh_scout_btc",
            )

    def test_pack_prefers_stable_btc_tpsl_and_keeps_execution_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            self._write_json(agent / "QuantGod_AceStrategyScout.json", {
                "candidates": [
                    {
                        "lane": "live12_raw_rsi",
                        "strategyId": "LIVE12_RAW_RSI",
                        "decision": "DISCARD_AS_ACE",
                        "netProfitUSC": 0.0,
                        "profitFactor": 0.0,
                        "tradeCount": 0,
                        "blockers": ["NET_PROFIT_NOT_POSITIVE", "PROFIT_FACTOR_LT_1_05"],
                        "liveUnsafeReason": "RSI_TESTER_RUN_GATE_BLOCKED",
                    }
                ],
                "topQualifiedForex": {
                    "seedId": "GA-USDJPY-G0093-C0004",
                    "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    "profitFactor": 2.6998,
                    "sharpe": 2.0702,
                    "tradeCount": 18,
                    "effectiveSampleCount": 25,
                    "walkForwardStability": 0.95,
                },
                "forexContenderReview": {
                    "requiresParallelTesterForward": True,
                    "contenders": [{"seedId": "GA-USDJPY-G0093-C0004"}, {"seedId": "GA-USDJPY-G0102-C0004"}],
                },
            })
            self._write_json(agent / "QuantGod_ChampionRetestReport.json", {
                "forexChampion": {
                    "status": "FOREX_CHAMPION_RETEST_PASS",
                    "seedId": "GA-USDJPY-G0093-C0004",
                    "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    "backtest": {"profitFactor": 2.6998, "sharpe": 2.0702, "tradeCount": 18},
                    "walkForward": {"forwardNetR": 2.3428, "stabilityScore": 0.95},
                    "blockers": [],
                }
            })
            self._write_json(agent / "QuantGod_TpSlOptimizerReport.json", {
                "forexMt5": {
                    "status": "FOREX_TPSL_NO_PASSING_COARSE_COMBO",
                    "testerVariantQueue": [
                        {
                            "variantId": "usdjpy_tpsl_14r_1_2",
                            "riskPips": 14.0,
                            "tpPips": 16.8,
                            "rewardRatio": 1.2,
                            "coarseScreenScore": -416.8893,
                            "coarseScreenBlockers": [
                                "FOREX_TPSL_NET_PIPS_NOT_POSITIVE",
                                "FOREX_TPSL_PF_LT_1_25",
                                "FOREX_TPSL_SHARPE_LT_1",
                            ],
                            "testerOverrides": {
                                "ChampionRiskPips": "14",
                                "PilotRewardRatio": "1.2",
                                "PilotRsiATRMultiplierSL": "1.5",
                            },
                        }
                    ],
                },
                "btcCryptoCfd": {
                    "status": "BTC_TPSL_SCAN_READY",
                    "finalAdvisoryPickPolicy": "STABLE_OVER_TARGET_SEEKING",
                    "finalAdvisoryPickReasonZh": "冲目标候选窗口更弱，默认稳健。",
                    "recommendedStable": {
                        "strategyId": "hfm_crypto_btc_tpsl_0016",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "parameters": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "fullWindowMetrics": {
                            "pnlUsd": 38.7432,
                            "sharpe": 1.326,
                            "maxDrawdownPct": 1.5619,
                            "tradeCount": 69,
                            "liquidationCount": 0,
                        },
                    },
                    "recommendedTargetSeeking": {
                        "strategyId": "hfm_crypto_btc_tpsl_0095",
                        "validWindowCount": 2,
                        "windowCount": 6,
                        "parameters": {
                            "bias": "both",
                            "takeProfitPriceMove": 750.0,
                            "stopLossPriceMove": 400.0,
                        },
                        "fullWindowMetrics": {"pnlUsd": 83.0437, "sharpe": 2.2224},
                    },
                    "finalAdvisoryPick": {
                        "strategyId": "hfm_crypto_btc_tpsl_0016",
                        "params": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "tpSlSummary": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "fullWindowMetrics": {"pnlUsd": 38.7432, "sharpe": 1.326},
                    },
                    "windowHealth": {
                        "selectedDefault": {
                            "middleThirdWeak": True,
                            "repairFocus": ["raise_window_sharpe", "increase_window_sample_density", "middle_third_rescue"],
                        }
                    },
                    "middleWindowLeaders": {
                        "status": "BTC_MIDDLE_WINDOW_LEADERS_READY",
                        "bestTargetMiddleQuality": {
                            "strategyId": "hfm_crypto_btc_tpsl_target_middle",
                            "testerOnly": True,
                            "orderSendAllowed": False,
                        },
                        "bestMiddleQuality": {
                            "strategyId": "hfm_crypto_btc_tpsl_best_middle",
                            "testerOnly": True,
                            "orderSendAllowed": False,
                        },
                    },
                    "focusedRetestQueue": [
                        {
                            "priority": 1,
                            "role": "selectedDefault",
                            "strategyId": "hfm_crypto_btc_tpsl_0016",
                            "testerOnly": True,
                            "livePresetMutation": False,
                            "orderSendAllowed": False,
                            "windowHealth": {"middleThirdWeak": True},
                        }
                    ],
                }
            })
            self._write_json(agent / "QuantGod_BtcStrategyScanReport.json", {
                "status": "BTC_SCAN_COMPLETE_NO_CLEAR_UPGRADE",
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                        "strategyName": "BTCUSD short-window stability shadow simulation",
                        "strategyFamily": "ema_slope_regime",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "fullWindowMetrics": {
                            "pnlUsd": 38.7432,
                            "roiPct": 3.8743,
                            "sharpe": 1.326,
                            "maxDrawdownPct": 1.5619,
                            "tradeCount": 69,
                        },
                        "parameters": {
                            "bias": "short",
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 6,
                        },
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    },
                    {
                        "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                        "strategyName": "BTCUSD sample-balanced bidirectional shadow simulation",
                        "strategyFamily": "ema_slope_regime",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "fullWindowMetrics": {
                            "pnlUsd": 52.7069,
                            "roiPct": 5.2707,
                            "sharpe": 1.3613,
                            "maxDrawdownPct": 2.5771,
                            "tradeCount": 74,
                        },
                        "parameters": {
                            "bias": "both",
                            "takeProfitPriceMove": 900.0,
                            "stopLossPriceMove": 500.0,
                            "maxHoldBars": 16,
                            "cooldownBars": 4,
                        },
                        "blockers": ["HFM_SHARPE_LT_MIN"],
                    },
                    {
                        "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                        "strategyName": "BTCUSD yield-balanced bidirectional shadow simulation",
                        "strategyFamily": "ema_slope_regime",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "fullWindowMetrics": {
                            "pnlUsd": 72.4065,
                            "roiPct": 7.2406,
                            "sharpe": 1.987,
                            "maxDrawdownPct": 1.5181,
                            "tradeCount": 47,
                        },
                        "parameters": {
                            "bias": "both",
                            "takeProfitPriceMove": 750.0,
                            "stopLossPriceMove": 400.0,
                            "maxHoldBars": 36,
                            "cooldownBars": 6,
                        },
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    },
                    {
                        "strategyId": "hfm_crypto_btc_sample_rich_quality_0009",
                        "strategyName": "BTCUSD sample-rich quality shadow simulation",
                        "strategyFamily": "ema_slope_regime",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "fullWindowMetrics": {
                            "pnlUsd": 53.7733,
                            "roiPct": 5.3773,
                            "sharpe": 1.7125,
                            "maxDrawdownPct": 1.745,
                            "tradeCount": 76,
                        },
                        "parameters": {
                            "bias": "both",
                            "takeProfitPriceMove": 400.0,
                            "stopLossPriceMove": 600.0,
                            "maxHoldBars": 16,
                            "cooldownBars": 4,
                        },
                        "blockers": ["HFM_SHARPE_LT_MIN"],
                    }
                ],
                "nextFocusedSearchPlan": {
                    "highYieldTradeoff": {
                        "strategyId": "hfm_crypto_btc_balanced_quality_repair_0028",
                        "pnlUsd": 83.0437,
                        "roiPct": 8.3044,
                        "sharpe": 2.2224,
                        "maxDrawdownPct": 1.5156,
                        "tradeCount": 48,
                        "validWindowCount": 2,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 750.0,
                        "stopLossPriceMove": 400.0,
                        "maxHoldBars": 36,
                        "cooldownBars": 6,
                    },
                    "yieldLeaderConfirmationBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_yield_leader_confirmation_0018",
                        "pnlUsd": 83.0437,
                        "roiPct": 8.3044,
                        "sharpe": 2.2224,
                        "maxDrawdownPct": 1.5156,
                        "tradeCount": 48,
                        "validWindowCount": 2,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 750.0,
                        "stopLossPriceMove": 400.0,
                        "maxHoldBars": 36,
                        "cooldownBars": 6,
                    },
                    "yieldLeaderConfirmationImprovesBaseline": False,
                    "yieldLeaderConfirmationOutcomeZh": "yield leader 局部确认暂未推翻当前高收益 leader；继续把它作为高收益参考。",
                    "stableMiddleThirdFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_followup_0008",
                        "pnlUsd": 39.2211,
                        "roiPct": 3.9221,
                        "sharpe": 1.361,
                        "maxDrawdownPct": 1.544,
                        "tradeCount": 70,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 500.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 10,
                        "cooldownBars": 5,
                    },
                    "stableMiddleThirdFollowupImprovesRepair": False,
                    "stableMiddleThirdFollowupOutcomeZh": "stable middle-third follow-up 局部搜索暂未推翻当前 repair 候选；继续把 0302 和现有 repair 版本作为主锚点。",
                    "stableMiddleWeakWindowBridgeBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_bridge_0004",
                        "pnlUsd": 34.1123,
                        "roiPct": 3.4112,
                        "sharpe": 1.1188,
                        "maxDrawdownPct": 1.622,
                        "tradeCount": 71,
                        "validWindowCount": 2,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 350.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 5,
                    },
                    "stableMiddleWeakWindowBridgeImprovesAggregate": True,
                    "stableMiddleWeakWindowBridgeImprovesWeakWindow": False,
                    "stableMiddleWeakWindowBridgeImprovesBaseline": False,
                    "stableMiddleWeakWindowBridgeOutcomeZh": "stable middle weak-window bridge 提高了整体有效窗口数，但 middle_third 弱窗口本身没有改善；把它当作折中观察线，不当作真实 weak-window 修复。",
                    "stableMiddleTradeoffFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0005",
                        "pnlUsd": 33.1123,
                        "roiPct": 3.3112,
                        "sharpe": 1.1428,
                        "maxDrawdownPct": 1.5888,
                        "tradeCount": 72,
                        "validWindowCount": 2,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 5,
                    },
                    "stableMiddleTradeoffFollowupImprovesBridge": True,
                    "stableMiddleTradeoffFollowupImprovesWeakWindow": False,
                    "stableMiddleTradeoffFollowupImprovesBaseline": False,
                    "stableMiddleTradeoffFollowupOutcomeZh": "stable middle tradeoff follow-up 改善了 bridge 线，但 middle_third 仍未真正修复；把它当作下一条折中观察线。",
                    "qualityRepairTradeoff": {
                        "strategyId": "hfm_crypto_btc_balanced_quality_repair_0028",
                        "pnlUsd": 83.0437,
                        "roiPct": 8.3044,
                        "sharpe": 2.2224,
                        "maxDrawdownPct": 1.5156,
                        "tradeCount": 48,
                        "validWindowCount": 2,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 750.0,
                        "stopLossPriceMove": 400.0,
                        "maxHoldBars": 36,
                        "cooldownBars": 6,
                    },
                    "sampleRichQualityTradeoff": {
                        "strategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                        "pnlUsd": 60.2265,
                        "roiPct": 6.0227,
                        "sharpe": 1.774,
                        "maxDrawdownPct": 1.801,
                        "tradeCount": 81,
                        "validWindowCount": 3,
                        "windowCount": 6,
                        "bias": "both",
                        "takeProfitPriceMove": 400.0,
                        "stopLossPriceMove": 600.0,
                        "maxHoldBars": 16,
                        "cooldownBars": 4,
                    },
                    "recommendations": [
                        {
                            "id": "quality_first_high_yield_neighborhood",
                            "priority": 1,
                            "basisStrategyId": "hfm_crypto_btc_balanced_quality_repair_0028",
                            "reasonZh": "高收益慢频候选优先补窗口样本。",
                        },
                        {
                            "id": "sample_rich_quality_bridge",
                            "priority": 2,
                            "basisStrategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                            "reasonZh": "样本丰富候选作为桥接修复方向。",
                        },
                        {
                            "id": "stable_champion_middle_third_rescue",
                            "priority": 3,
                            "basisStrategyId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                            "reasonZh": "现任稳健候选继续修 middle_third。",
                        },
                    ],
                },
            })
            self._write_json(agent / "QuantGod_ChampionTesterRunGate.json", {
                "status": "CHAMPION_TESTER_RUN_GATE_BLOCKED",
                "gate": {
                    "blockers": [
                        "authorization_lock_expired",
                        "live_dashboard_snapshot_stale",
                        "outside_strategy_tester_window",
                        "isolated_tester_account_context_not_ready",
                        "sensitive_account_context_sync_required",
                    ],
                    "queue": {
                        "queueCount": 2,
                        "tasks": [
                            {
                                "candidateId": "g0093-usdjpy-rsi-champion-tester-forward-v1",
                                "status": "ready",
                            },
                            {
                                "candidateId": "g0102-usdjpy-rsi-champion-tester-forward-v1",
                                "status": "ready",
                            },
                        ],
                    },
                    "liveSession": {
                        "ok": False,
                        "status": "blocked",
                        "openTradeCount": 0,
                        "marginInUse": 0,
                        "accountNumber": "186054398",
                        "server": "HFMarketsGlobal-Live12",
                    },
                },
                "testerAccountContext": {
                    "sensitiveAccountContextSyncRequired": True,
                },
                "nextTesterWindow": {
                    "label": "daily_night",
                    "startJstIso": "2026-06-08T20:10:00+09:00",
                    "endJstIso": "2026-06-08T23:30:00+09:00",
                    "minutesUntilStart": 302.4,
                },
                "decision": {
                    "canRunIsolatedTester": False,
                    "nextRequiredActionZh": "先清空 tester gate blocker。",
                },
            })
            self._write_json(agent / "QuantGod_LiveRuntimePreflightProbe.json", {
                "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                "runtimeProbePassed": False,
                "dataPlaneReadyForLivePilotReview": False,
                "approvedLanes": ["hfmCryptoCfd"],
                "dashboardSnapshot": {
                    "fresh": False,
                    "ageSeconds": 246750.956,
                    "maxAgeSeconds": 300,
                    "symbolCount": 1,
                    "symbolNames": ["USDJPYc"],
                    "permissionLayers": {
                        "terminalConnected": True,
                        "accountAuthorized": True,
                        "terminalTradeAllowed": True,
                        "programTradeAllowed": True,
                        "accountTradeAllowed": True,
                        "accountExpertTradeAllowed": True,
                        "focusSymbolTradeAllowed": True,
                        "tradePermissionBlocker": "READ_ONLY_MODE",
                    },
                    "executionGateDiagnostics": {
                        "tradeAllowed": {
                            "detailZh": "MT5 terminal/account/program/symbol 交易权限均已通过；当前 composite tradeAllowed=false 的直接阻塞为 READ_ONLY_MODE。",
                        }
                    },
                },
                "probeResults": {
                    "symbolSelectedInDashboardOk": False,
                    "symbolRuntimeProbeOk": False,
                    "sidecarLiveTickOk": False,
                    "spreadProbeOk": False,
                },
                "blockers": [
                    {"code": "MT5_DASHBOARD_SNAPSHOT_STALE"},
                    {"code": "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING"},
                ],
                "laneRuntimeChecks": [
                    {
                        "brokerSymbol": "#BTCUSD",
                        "runtimeProbeFresh": False,
                        "runtimeProbeAgeSeconds": 246742.515,
                        "symbolPresentInSnapshot": False,
                        "symbolPresentInNames": False,
                        "spreadFieldPresent": False,
                    }
                ],
                "nextRequiredActionZh": "先补齐 dashboard、symbol 和 spread 证据。",
            })
            self._write_json(agent / "QuantGod_LiveEvidenceIntake.json", {
                "schema": "quantgod.live_automation_readiness.evidence_intake.v1",
                "generatedAtIso": "2026-06-08T05:29:00Z",
                "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                "dashboardFresh": False,
                "tradeStatus": "SHADOW",
                "livePilotMode": False,
                "readOnlyMode": True,
                "executionEnabled": False,
                "tradeAllowed": False,
                "tradePermissionBlocker": "READ_ONLY_MODE",
                "targetSymbols": ["#BTCUSD"],
                "fileInputSummary": {
                    "presentInputCount": 4,
                    "missingChecklistCount": 3,
                },
                "summaryZh": "当前仍为 SHADOW/READ_ONLY_MODE，且 live16 dashboard stale。",
            })
            self._write_json(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json", {
                "status": "TARGET_REACHED",
                "targetReached": True,
                "target": {"targetUsd": 50.0},
                "combinedTarget": {
                    "targetReached": True,
                    "combinedVerifiedUsdProfit": 72.0,
                    "qualifyingLaneIds": ["forexMt5"],
                },
                "liveExecutionReview": {
                    "executionReleaseGateSummary": {
                        "blockerCodes": [
                            "REQUEST_WRITE_RELEASE_TOKEN_MISSING",
                            "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                        ]
                    }
                },
            })
            self._write_json(agent / "QuantGod_ReleaseTokenSignoffEvidenceMatrix.json", {
                "status": "SIGNOFF_EVIDENCE_AND_INPUT_READY_FOR_SEPARATE_RELEASE_LANE",
                "completeSignoffCount": 5,
                "releaseTokenCount": 5,
            })

            with patch(
                "tools.ace_execution_candidate_pack._resolve_ace_strategy_scout",
                return_value={
                    "candidates": [
                        {
                            "lane": "live12_raw_rsi",
                            "strategyId": "LIVE12_RAW_RSI",
                            "decision": "DISCARD_AS_ACE",
                            "netProfitUSC": 0.0,
                            "profitFactor": 0.0,
                            "tradeCount": 0,
                            "blockers": ["NET_PROFIT_NOT_POSITIVE", "PROFIT_FACTOR_LT_1_05"],
                            "liveUnsafeReason": "RSI_TESTER_RUN_GATE_BLOCKED",
                        }
                    ],
                    "topQualifiedForex": {
                        "seedId": "GA-USDJPY-G0093-C0004",
                        "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                        "profitFactor": 2.6998,
                        "sharpe": 2.0702,
                        "tradeCount": 18,
                        "effectiveSampleCount": 25,
                        "walkForwardStability": 0.95,
                    },
                    "forexContenderReview": {
                        "requiresParallelTesterForward": True,
                        "contenders": [{"seedId": "GA-USDJPY-G0093-C0004"}, {"seedId": "GA-USDJPY-G0102-C0004"}],
                    },
                },
            ):
                report = build_ace_execution_candidate_pack(runtime, write=True)

            self.assertEqual(report["schema"], "quantgod.ace_execution_candidate_pack.v1")
            self.assertTrue(report["decision"]["profitTargetReached"])
            self.assertEqual(report["decision"]["defaultBtcStrategyId"], "hfm_crypto_btc_tpsl_0016")
            self.assertEqual(report["decision"]["btcDefaultPolicy"], "STABLE_OVER_TARGET_SEEKING")
            self.assertEqual(
                report["btcCryptoCfd"]["selectedDefault"]["tpSlSummary"]["takeProfitPriceMove"],
                450.0,
            )
            self.assertEqual(
                report["btcCryptoCfd"]["targetSeeking"]["tpSlSummary"]["stopLossPriceMove"],
                400.0,
            )
            self.assertTrue(report["btcCryptoCfd"]["windowHealth"]["selectedDefault"]["middleThirdWeak"])
            self.assertEqual(
                report["btcCryptoCfd"]["middleWindowLeaders"]["bestTargetMiddleQuality"]["strategyId"],
                "hfm_crypto_btc_tpsl_target_middle",
            )
            self.assertEqual(report["btcCryptoCfd"]["focusedRetestQueue"][0]["role"], "selectedDefault")
            self.assertFalse(report["btcCryptoCfd"]["focusedRetestQueue"][0]["orderSendAllowed"])
            self.assertEqual(
                report["btcCryptoCfd"]["focusedRetestQueue"][1]["strategyId"],
                report["strategyShortlist"]["btcDuelBoard"]["nearLiveChallengerStrategyId"],
            )
            self.assertEqual(
                report["btcCryptoCfd"]["focusedRetestQueue"][1]["role"],
                "stabilityAlternative",
            )
            self.assertEqual(
                report["btcCryptoCfd"]["focusedRetestQueue"][2]["strategyId"],
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldNowStrategyId"],
            )
            self.assertEqual(
                report["btcCryptoCfd"]["focusedRetestQueue"][2]["role"],
                "yieldFrontierChallenger",
            )
            self.assertEqual(
                report["btcCryptoCfd"]["focusedRetestQueue"][2]["optimizerBaselineStrategyId"],
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldOptimizerBaselineStrategyId"],
            )
            self.assertEqual(
                report["btcCryptoCfd"]["focusedRetestQueue"][3]["strategyId"],
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleTradeoffFollowupBestStrategyId"],
            )
            self.assertEqual(
                report["btcCryptoCfd"]["focusedRetestQueue"][3]["role"],
                "repairObservation",
            )
            self.assertEqual(
                report["btcCryptoCfd"]["focusedRetestQueue"][3]["selectionBasis"]["sourceArtifact"],
                "btcStrategyScan.nextFocusedSearchPlan.stableMiddleTradeoffFollowupBestTradeoff",
            )
            self.assertTrue(report["forexMt5"]["contenderTieBreakRequired"])
            self.assertEqual(report["strategyShortlist"]["status"], "STRATEGY_SHORTLIST_READY")
            self.assertEqual(report["strategyShortlist"]["counts"]["mt5TopStrategies"], 3)
            self.assertEqual(report["strategyShortlist"]["counts"]["btcTopStrategies"], 3)
            self.assertEqual(
                report["strategyShortlist"]["finalistComparison"]["mt5"]["status"],
                "FINALIST_COMPARISON_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["finalistComparison"]["btc"]["status"],
                "FINALIST_COMPARISON_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["laneVerdicts"]["status"],
                "LANE_VERDICTS_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5AbBoard"]["status"],
                "MT5_AB_BOARD_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5AbBoard"]["championSeedId"],
                report["strategyShortlist"]["laneVerdicts"]["mt5"]["strongestNow"]["seedId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5AbBoard"]["contenderSeedId"],
                report["strategyShortlist"]["laneVerdicts"]["mt5"]["strongestNow"]["tieWithSeedIds"][0],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["status"],
                "BTC_LINEUP_BOARD_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["stableAnchorStrategyId"],
                report["strategyShortlist"]["laneVerdicts"]["btc"]["mostStableNow"]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["yieldFrontierStrategyId"],
                report["strategyShortlist"]["laneVerdicts"]["btc"]["strongestNow"]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["nearLiveChallengerStrategyId"],
                "hfm_crypto_btc_sample_balanced_both_shadow_v1",
            )
            self.assertIn(
                "nearLiveRepairBestStrategyId",
                report["strategyShortlist"]["btcLineupBoard"],
            )
            self.assertIn(
                "stableMiddleThirdRepairBestStrategyId",
                report["strategyShortlist"]["btcLineupBoard"],
            )
            self.assertIn(
                "nearLiveRepairImprovesBaseline",
                report["strategyShortlist"]["btcLineupBoard"],
            )
            self.assertIn(
                "stableMiddleThirdRepairImprovesBaseline",
                report["strategyShortlist"]["btcLineupBoard"],
            )
            self.assertIn(
                "nearLiveRepairOutcomeZh",
                report["strategyShortlist"]["btcLineupBoard"],
            )
            self.assertIn(
                "stableMiddleThirdRepairOutcomeZh",
                report["strategyShortlist"]["btcLineupBoard"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleThirdFollowupBestStrategyId"],
                "hfm_crypto_btc_stable_middle_followup_0008",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleWeakWindowBridgeBestStrategyId"],
                "hfm_crypto_btc_stable_middle_bridge_0004",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleTradeoffFollowupBestStrategyId"],
                "hfm_crypto_btc_stable_middle_tradeoff_0005",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleTradeoffFollowupBestTradeoff"]["strategyId"],
                "hfm_crypto_btc_stable_middle_tradeoff_0005",
            )
            self.assertFalse(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleThirdFollowupImprovesRepair"]
            )
            self.assertTrue(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleWeakWindowBridgeImprovesAggregate"]
            )
            self.assertFalse(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleWeakWindowBridgeImprovesWeakWindow"]
            )
            self.assertFalse(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleWeakWindowBridgeImprovesBaseline"]
            )
            self.assertTrue(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleTradeoffFollowupImprovesBridge"]
            )
            self.assertFalse(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleTradeoffFollowupImprovesWeakWindow"]
            )
            self.assertFalse(
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleTradeoffFollowupImprovesBaseline"]
            )
            self.assertIn(
                "follow-up 局部搜索暂未推翻",
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleThirdFollowupOutcomeZh"],
            )
            self.assertIn(
                "提高了整体有效窗口数",
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleWeakWindowBridgeOutcomeZh"],
            )
            self.assertIn(
                "改善了 bridge 线",
                report["strategyShortlist"]["btcLineupBoard"]["stableMiddleTradeoffFollowupOutcomeZh"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["recommendedFocusedRetestOrder"][0],
                report["btcCryptoCfd"]["focusedRetestQueue"][0]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["focusedRetestQueue"][0]["strategyId"],
                report["btcCryptoCfd"]["focusedRetestQueue"][0]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["recommendedFocusedRetestOrder"][1],
                report["btcCryptoCfd"]["focusedRetestQueue"][1]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["focusedRetestQueue"][1]["strategyId"],
                report["btcCryptoCfd"]["focusedRetestQueue"][1]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["recommendedFocusedRetestOrder"][3],
                report["btcCryptoCfd"]["focusedRetestQueue"][3]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["focusedRetestQueue"][3]["strategyId"],
                report["btcCryptoCfd"]["focusedRetestQueue"][3]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcDuelBoard"]["nearLiveChallengerStrategyId"],
                report["strategyShortlist"]["btcLineupBoard"]["nearLiveChallengerStrategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLineupBoard"]["yieldLeaderConfirmationBestStrategyId"],
                "hfm_crypto_btc_yield_leader_confirmation_0018",
            )
            self.assertFalse(
                report["strategyShortlist"]["btcLineupBoard"]["yieldLeaderConfirmationImprovesBaseline"]
            )
            self.assertIn(
                "yield leader 局部确认暂未推翻",
                report["strategyShortlist"]["btcLineupBoard"]["yieldLeaderConfirmationOutcomeZh"],
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["status"],
                "SELECTION_CONSENSUS_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionRefreshAudit"]["status"],
                "SELECTION_REFRESH_AUDIT_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["status"],
                "GO_LIVE_GAP_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5TopStrategies"][0]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5TopStrategies"][1]["seedId"],
                "GA-USDJPY-G0102-C0004",
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5TopStrategies"][0]["selectionBasis"]["sourceArtifact"],
                "championRetest.forexChampion",
            )
            self.assertIn(
                "walkForwardStability",
                report["strategyShortlist"]["mt5TopStrategies"][0]["selectionBasis"]["comparisonFocus"],
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5TopStrategies"][2]["summaryType"],
                "tester_forward_variant",
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5TopStrategies"][1]["selectionBasis"]["sourceArtifact"],
                "aceStrategyScout.forexContenderReview",
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5TopStrategies"][2]["selectionBasis"]["sourceArtifact"],
                "tpSlOptimizer.forexMt5.testerVariantQueue",
            )
            self.assertIn(
                "ChampionRiskPips",
                report["strategyShortlist"]["mt5TopStrategies"][2]["params"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][0]["strategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectedDefault"]["strategyId"],
                report["liveUpgradeSelection"]["selectedDefault"]["strategyId"],
            )
            self.assertEqual(
                report["strategyShortlist"]["selectedDefaultSource"],
                report["liveUpgradeSelection"]["selectedDefaultSource"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][1]["strategyId"],
                "hfm_crypto_btc_sample_balanced_both_shadow_v1",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][1]["role"],
                "stabilityAlternative",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][1]["selectionBasis"]["sourceArtifact"],
                "btcStrategyScan",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][2]["strategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][0]["selectionBasis"]["sourceArtifact"],
                "tpSlOptimizer.finalAdvisoryPick",
            )
            self.assertIn(
                "validWindowCount",
                report["strategyShortlist"]["btcTopStrategies"][0]["selectionBasis"]["comparisonFocus"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][0]["selectionBasis"]["scanAliasStrategyId"],
                "hfm_crypto_btc_stability_short_window_shadow_v1",
            )
            self.assertIn(
                "stableMiddleThirdRepairBestStrategyId",
                report["strategyShortlist"]["btcTopStrategies"][0]["selectionBasis"],
            )
            self.assertIn(
                "stableMiddleThirdRepairImprovesBaseline",
                report["strategyShortlist"]["btcTopStrategies"][0]["selectionBasis"],
            )
            self.assertIn(
                "stableMiddleThirdRepairOutcomeZh",
                report["strategyShortlist"]["btcTopStrategies"][0]["selectionBasis"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][0]["selectionBasis"]["sameParameterSetAs"],
                ["hfm_crypto_btc_stability_short_window_shadow_v1"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][2]["selectionBasis"]["optimizerAliasStrategyId"],
                None,
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][2]["selectionBasis"]["optimizerBaselineStrategyId"],
                "hfm_crypto_btc_tpsl_0095",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][2]["selectionBasis"]["scanTopAliasStrategyId"],
                "hfm_crypto_btc_yield_balanced_both_shadow_v1",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][2]["selectionBasis"]["sameParameterSetAs"],
                ["hfm_crypto_btc_yield_balanced_both_shadow_v1"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcTopStrategies"][2]["role"],
                "highYieldTradeoff",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcParameterClusters"]["status"],
                "BTC_PARAMETER_CLUSTERS_READY",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcParameterClusters"]["rows"][0]["canonicalStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertIn(
                "hfm_crypto_btc_stability_short_window_shadow_v1",
                report["strategyShortlist"]["btcParameterClusters"]["rows"][0]["aliasStrategyIds"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcParameterClusters"]["rows"][1]["canonicalStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcParameterClusters"]["rows"][1]["recommendedResearchPriority"],
                1,
            )
            self.assertIn(
                "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                report["strategyShortlist"]["btcParameterClusters"]["rows"][1]["aliasStrategyIds"],
            )
            self.assertNotIn(
                "hfm_crypto_btc_tpsl_0095",
                report["strategyShortlist"]["btcParameterClusters"]["rows"][1]["aliasStrategyIds"],
            )
            self.assertEqual(
                report["strategyShortlist"]["finalistComparison"]["mt5"]["rows"][0]["headlineZh"],
                "主冠军",
            )
            self.assertIn(
                "walkForwardStability",
                report["strategyShortlist"]["finalistComparison"]["mt5"]["rows"][0]["strongestMetricZh"],
            )
            self.assertEqual(
                report["strategyShortlist"]["finalistComparison"]["btc"]["rows"][1]["headlineZh"],
                "稳定替补",
            )
            self.assertIn(
                "validWindowCount",
                report["strategyShortlist"]["finalistComparison"]["btc"]["rows"][1]["strongestMetricZh"],
            )
            self.assertEqual(
                report["strategyShortlist"]["finalistComparison"]["btc"]["rows"][0]["sameParameterSetAs"],
                ["hfm_crypto_btc_stability_short_window_shadow_v1"],
            )
            self.assertIn(
                "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                report["strategyShortlist"]["finalistComparison"]["btc"]["rows"][2]["aliasSummaryZh"],
            )
            self.assertEqual(
                report["strategyShortlist"]["laneVerdicts"]["mt5"]["strongestNow"]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["strategyShortlist"]["laneVerdicts"]["mt5"]["strongestNow"]["tieWithSeedIds"][0],
                "GA-USDJPY-G0102-C0004",
            )
            self.assertEqual(
                report["strategyShortlist"]["laneVerdicts"]["btc"]["strongestNow"]["strategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertEqual(
                report["strategyShortlist"]["laneVerdicts"]["btc"]["strongestNow"]["sameParameterSetAs"],
                ["hfm_crypto_btc_yield_balanced_both_shadow_v1"],
            )
            self.assertEqual(
                report["strategyShortlist"]["laneVerdicts"]["btc"]["mostStableNow"]["strategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertEqual(
                report["strategyShortlist"]["laneVerdicts"]["btc"]["mostStableNow"]["sameParameterSetAs"],
                ["hfm_crypto_btc_stability_short_window_shadow_v1"],
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["mt5"]["strongestNowSeedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["mt5"]["agreementCount"],
                2,
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["mt5"]["consensusLevel"],
                "MODERATE",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["mt5"]["supportingSources"],
                ["aceStrategyScout.topQualifiedForex", "championRetest.forexChampion"],
            )
            self.assertTrue(
                report["strategyShortlist"]["selectionConsensus"]["mt5"]["tieBreakStillRequired"],
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["mostStableNowStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["mostStableSupportingSources"],
                [
                    "tpSlOptimizer.recommendedStable",
                    "tpSlOptimizer.finalAdvisoryPick",
                    "btcStrategyScan.topCandidates",
                ],
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["mostStableAgreementCount"],
                3,
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldNowStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldSupportingSources"],
                [
                    "btcStrategyScan.topCandidates",
                    "btcStrategyScan.nextFocusedSearchPlan.highYieldTradeoff",
                    "btcStrategyScan.nextFocusedSearchPlan.qualityRepairTradeoff",
                ],
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldOptimizerBaselineStrategyId"],
                "hfm_crypto_btc_tpsl_0095",
            )
            self.assertFalse(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldConvergedWithStable"],
            )
            self.assertTrue(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldFrontierDriftDetected"],
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionConsensus"]["btc"]["strongestYieldConsensusLevel"],
                "HIGH",
            )
            self.assertTrue(
                report["strategyShortlist"]["selectionRefreshAudit"]["mt5StrongestAlignmentOk"]
            )
            self.assertTrue(
                report["strategyShortlist"]["selectionRefreshAudit"]["btcStableAlignmentOk"]
            )
            self.assertTrue(
                report["strategyShortlist"]["selectionRefreshAudit"]["btcHighYieldAlignmentOk"]
            )
            self.assertFalse(
                report["strategyShortlist"]["selectionRefreshAudit"]["btcStableYieldConverged"]
            )
            self.assertTrue(
                report["strategyShortlist"]["selectionRefreshAudit"]["btcHighYieldFrontierDriftDetected"]
            )
            self.assertTrue(
                report["strategyShortlist"]["selectionRefreshAudit"]["btcHighYieldScanAligned"]
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionRefreshAudit"]["scanTopStrategyId"],
                "hfm_crypto_btc_stability_short_window_shadow_v1",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionRefreshAudit"]["optimizerStableStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionRefreshAudit"]["optimizerFinalAdvisoryPickStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionRefreshAudit"]["currentDefaultStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionRefreshAudit"]["finalAdvisoryPickStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionRefreshAudit"]["optimizerTargetStrategyId"],
                "hfm_crypto_btc_tpsl_0095",
            )
            self.assertEqual(
                report["strategyShortlist"]["selectionRefreshAudit"]["scanHighYieldTradeoffStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            sample_rich_cluster = next(
                row
                for row in report["strategyShortlist"]["btcParameterClusters"]["rows"]
                if row["canonicalStrategyId"] == "hfm_crypto_btc_sample_rich_quality_0001"
            )
            self.assertEqual(sample_rich_cluster["recommendedResearchPriority"], 2)
            self.assertIn("hfm_crypto_btc_sample_rich_quality_0009", sample_rich_cluster["aliasStrategyIds"])
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["mt5"]["focusStrategyId"],
                "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["mt5"]["queueCount"],
                2,
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["mt5"]["gateDiagnostics"]["autoClearAtWindowBlockers"],
                ["outside_strategy_tester_window"],
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["mt5"]["gateDiagnostics"]["manualRefreshBlockers"],
                ["authorization_lock_expired", "live_dashboard_snapshot_stale"],
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["mt5"]["gateDiagnostics"]["manualSensitiveBlockers"],
                [
                    "isolated_tester_account_context_not_ready",
                    "sensitive_account_context_sync_required",
                ],
            )
            self.assertIn(
                "authorization_lock_expired",
                report["strategyShortlist"]["goLiveGap"]["mt5"]["topBlockers"],
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["btc"]["focusStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertIn(
                "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING",
                report["strategyShortlist"]["goLiveGap"]["btc"]["topBlockers"],
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["btc"]["gateDiagnostics"]["externalRefreshBlockers"],
                ["MT5_DASHBOARD_SNAPSHOT_STALE"],
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["btc"]["gateDiagnostics"]["dataPlaneBlockers"],
                ["MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING"],
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["btc"]["gateDiagnostics"]["executionModeBlockers"],
                [],
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["status"],
                "CHAMPION_TESTER_RUN_GATE_BLOCKED",
            )
            self.assertIn(
                "authorization_lock_expired",
                report["strategyShortlist"]["mt5LaneReadiness"]["blockers"],
            )
            self.assertFalse(report["strategyShortlist"]["mt5LaneReadiness"]["canRunTester"])
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["testerSnapshot"]["nextTesterWindowLabel"],
                "daily_night",
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["queueCount"],
                2,
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["readinessChecklist"]["readyCount"],
                0,
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["readinessChecklist"]["rows"][1],
                {
                    "id": "tester_window_open",
                    "ok": False,
                    "labelZh": "tester window open",
                    "dependencyCheckIds": [],
                    "sourceArtifact": "championTesterRunGate.nextTesterWindow",
                    "evidenceKeyZh": "nextTesterWindow.status/minutesUntilStart",
                    "nextActionZh": "等待 nightly tester window 打开后自动清除此项。",
                },
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["gateDiagnostics"]["autoClearAtWindowBlockers"],
                ["outside_strategy_tester_window"],
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["gateDiagnostics"]["manualRefreshBlockers"],
                ["authorization_lock_expired", "live_dashboard_snapshot_stale"],
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["gateDiagnostics"]["manualSensitiveBlockers"],
                [
                    "isolated_tester_account_context_not_ready",
                    "sensitive_account_context_sync_required",
                ],
            )
            self.assertEqual(
                report["strategyShortlist"]["mt5LaneReadiness"]["abCandidateIds"],
                ["g0093-usdjpy-rsi-champion-tester-forward-v1", "g0102-usdjpy-rsi-champion-tester-forward-v1"],
            )
            self.assertIn(
                f"minutesUntilStart={report['strategyShortlist']['mt5LaneReadiness']['testerSnapshot']['minutesUntilStart']}",
                report["strategyShortlist"]["mt5LaneReadiness"]["testerSummaryZh"],
            )
            self.assertIn(
                "queueCount=2",
                report["strategyShortlist"]["mt5LaneReadiness"]["testerSummaryZh"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLaneReadiness"]["status"],
                "WAITING_RUNTIME_PREFLIGHT_INPUTS",
            )
            self.assertIn(
                "MT5_DASHBOARD_SNAPSHOT_STALE",
                report["strategyShortlist"]["btcLaneReadiness"]["blockers"],
            )
            self.assertIn(
                "tradePermissionBlocker=READ_ONLY_MODE",
                report["strategyShortlist"]["btcLaneReadiness"]["runtimeSummaryZh"],
            )
            self.assertIn(
                "permissionChainHealthy=True",
                report["strategyShortlist"]["btcLaneReadiness"]["runtimeSummaryZh"],
            )
            self.assertTrue(
                report["strategyShortlist"]["btcLaneReadiness"]["runtimeSnapshot"]["permissionChainHealthy"]
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLaneReadiness"]["readinessChecklist"]["readyCount"],
                1,
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLaneReadiness"]["readinessChecklist"]["rows"][4],
                {
                    "id": "permission_chain_healthy",
                    "ok": True,
                    "labelZh": "permission chain healthy",
                    "dependencyCheckIds": ["dashboard_fresh"],
                    "sourceArtifact": "liveRuntimePreflightProbe.dashboardSnapshot.permissionLayers",
                    "evidenceKeyZh": "terminal/account/program/symbol permission layers",
                    "nextActionZh": "保持权限链为绿；当前不是主要 blocker。",
                },
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLaneReadiness"]["gateDiagnostics"]["externalRefreshBlockers"],
                ["MT5_DASHBOARD_SNAPSHOT_STALE"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLaneReadiness"]["gateDiagnostics"]["dataPlaneBlockers"],
                ["MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING"],
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLaneReadiness"]["gateDiagnostics"]["executionModeBlockers"],
                [],
            )
            self.assertEqual(
                report["strategyShortlist"]["goLiveGap"]["btc"]["directExecutionBlockerCode"],
                "READ_ONLY_MODE",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLaneReadiness"]["focusSymbol"],
                "#BTCUSD",
            )
            self.assertEqual(
                report["strategyShortlist"]["btcLaneReadiness"]["runtimeSnapshot"]["dashboardSymbolNames"],
                ["USDJPYc"],
            )
            self.assertFalse(
                report["strategyShortlist"]["btcLaneReadiness"]["runtimeSnapshot"]["spreadProbeOk"]
            )
            self.assertIn(
                "dashboardFresh=False",
                report["strategyShortlist"]["btcLaneReadiness"]["runtimeSummaryZh"],
            )
            self.assertFalse(report["strategyShortlist"]["liveActivationReady"])
            self.assertIn(
                "BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING",
                report["strategyShortlist"]["liveActivationBlockers"],
            )
            self.assertEqual(report["promotionQueue"]["status"], "PROMOTION_QUEUE_READY")
            self.assertEqual(report["promotionQueue"]["counts"]["total"], 6)
            self.assertEqual(report["promotionQueue"]["counts"]["actionableNow"], 3)
            self.assertEqual(report["promotionQueue"]["counts"]["blockedNow"], 3)
            self.assertEqual(
                report["executionReadinessBoard"]["status"],
                "EXECUTION_READINESS_BOARD_READY",
            )
            self.assertEqual(
                report["launchBoard"]["status"],
                "LAUNCH_BOARD_READY",
            )
            self.assertFalse(report["executionReadinessBoard"]["canProceedToSeparateReleaseLane"])
            self.assertEqual(
                report["executionReadinessBoard"]["readyStrategyCountForSeparateReleaseLane"],
                0,
            )
            self.assertEqual(
                report["executionReadinessBoard"]["closestResearchLaneNow"],
                "btcCryptoCfd",
            )
            self.assertEqual(
                report["launchBoard"]["currentClosestLaneNow"],
                "btcCryptoCfd",
            )
            self.assertEqual(
                report["launchBoard"]["selectedReleaseCandidateLane"],
                "forexMt5",
            )
            self.assertTrue(report["launchBoard"]["laneConflictDetected"])
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["btc"]["focusStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["btc"]["yieldFrontierStrategyId"],
                report["strategyShortlist"]["btcDuelBoard"]["yieldFrontierStrategyId"],
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["btc"]["nearLiveChallengerStrategyId"],
                report["strategyShortlist"]["btcLineupBoard"]["nearLiveChallengerStrategyId"],
            )
            self.assertEqual(
                report["launchBoard"]["criticalPath"][0]["checkId"],
                "runtime_probe_fresh",
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["btc"]["readiness"]["ratio"],
                "1/9",
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["btc"]["blockerFamilies"],
                ["external_refresh", "data_plane"],
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["mt5"]["focusSeedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["mt5"]["abContenderSeedId"],
                "GA-USDJPY-G0102-C0004",
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["mt5"]["readiness"]["ratio"],
                "0/7",
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["mt5"]["blockerFamilies"],
                ["window", "manual_refresh", "sensitive_sync"],
            )
            self.assertTrue(
                report["launchBoard"]["laneBoards"]["mt5"]["isSelectedReleaseCandidate"]
            )
            self.assertEqual(
                report["launchBoard"]["laneBoards"]["mt5"]["activeAbSummaryZh"],
                report["strategyShortlist"]["mt5AbBoard"]["recommendationZh"],
            )
            self.assertEqual(
                report["executionReadinessBoard"]["nextActionsOverall"][0]["id"],
                "btc_runtime_preflight_refresh",
            )
            self.assertEqual(
                report["executionReadinessBoard"]["nextActionsOverall"][1]["id"],
                "btc_stable_anchor_retest",
            )
            self.assertEqual(
                report["executionReadinessBoard"]["nextActionsOverall"][2]["id"],
                "restore_live_mt5_dashboard_refresh",
            )
            self.assertIn(
                "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING",
                report["executionReadinessBoard"]["nextActionsOverall"][0]["topBlockers"],
            )
            self.assertEqual(
                report["executionReadinessBoard"]["nextActionsOverall"][0]["evidenceSnapshot"]["dashboardSymbolNames"],
                ["USDJPYc"],
            )
            self.assertFalse(
                report["executionReadinessBoard"]["nextActionsOverall"][0]["evidenceSnapshot"]["symbolSelectedInDashboardOk"]
            )
            self.assertFalse(
                report["executionReadinessBoard"]["nextActionsOverall"][0]["evidenceSnapshot"]["symbolSelectionEffectiveOk"]
            )
            self.assertIn(
                "#BTCUSD selectedRaw=False selectedEffective=False",
                report["executionReadinessBoard"]["nextActionsOverall"][0]["evidenceSummaryZh"],
            )
            self.assertEqual(
                report["executionReadinessBoard"]["laneSnapshots"][0]["evidenceSnapshot"]["nextTesterWindowLabel"],
                "daily_night",
            )
            self.assertEqual(
                report["executionReadinessBoard"]["laneSnapshots"][1]["evidenceSnapshot"]["targetSymbol"],
                "#BTCUSD",
            )
            self.assertEqual(
                report["executionReadinessBoard"]["closureQueue"][0]["lane"],
                "btcCryptoCfd",
            )
            self.assertEqual(
                report["executionReadinessBoard"]["closureQueue"][0]["checkId"],
                "runtime_probe_fresh",
            )
            self.assertEqual(
                report["executionReadinessBoard"]["closureQueue"][0]["sourceArtifact"],
                "liveRuntimePreflightProbe.laneRuntimeChecks",
            )
            self.assertTrue(
                report["executionReadinessBoard"]["closureQueue"][0]["isPrimaryActionable"]
            )
            self.assertEqual(
                report["executionReadinessBoard"]["closureQueue"][2]["blockingDependencyCheckIds"],
                ["runtime_probe_fresh"],
            )
            self.assertEqual(
                report["executionReadinessBoard"]["primaryClosureQueue"][0]["checkId"],
                "runtime_probe_fresh",
            )
            self.assertIn(
                "主闭环项",
                report["executionReadinessBoard"]["closureSummaryZh"],
            )
            self.assertIn(
                "首项=runtime_probe_fresh",
                report["executionReadinessBoard"]["closureSummaryZh"],
            )
            self.assertEqual(
                report["promotionQueue"]["queue"][0]["promotionStage"],
                "wait_tester_gate",
            )
            self.assertEqual(
                report["promotionQueue"]["queue"][0]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertFalse(report["promotionQueue"]["queue"][0]["canAdvanceNow"])
            self.assertIn(
                "authorization_lock_expired",
                report["promotionQueue"]["queue"][0]["blockingReasons"],
            )
            btc_queue_by_role = {
                row["role"]: row
                for row in report["promotionQueue"]["queue"]
                if row.get("lane") == "btcCryptoCfd"
            }
            self.assertEqual(
                btc_queue_by_role["stableAnchor"]["promotionStage"],
                "focused_retest_next",
            )
            self.assertTrue(btc_queue_by_role["stableAnchor"]["canAdvanceNow"])
            self.assertIn(
                "MT5_DASHBOARD_SNAPSHOT_STALE",
                btc_queue_by_role["stableAnchor"]["blockingReasons"],
            )
            self.assertFalse(btc_queue_by_role["stableAnchor"]["readyForSeparateReleaseLane"])
            self.assertEqual(
                btc_queue_by_role["stabilityAlternative"]["promotionStage"],
                "stability_compare",
            )
            self.assertEqual(report["rsiDemotionReview"]["status"], "RSI_LIVE_LOGIC_DEMOTE_REVIEW")
            self.assertEqual(
                report["rsiDemotionReview"]["recommendedAction"],
                "DEMOTE_RAW_RSI_FROM_ACE",
            )
            self.assertEqual(report["liveUpgradeSelection"]["status"], "RSI_DEMOTED_FOREX_AB_READY")
            self.assertEqual(report["liveUpgradeSelection"]["selectedLane"], "forexMt5")
            self.assertEqual(
                report["liveUpgradeSelection"]["selectedStrategy"]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["liveUpgradeSelection"]["laneSelections"]["forexMt5"]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["liveUpgradeSelection"]["laneSelections"]["btcCryptoCfd"]["strategyId"],
                report["btcCryptoCfd"]["selectedDefault"]["strategyId"],
            )
            self.assertTrue(
                report["liveUpgradeSelection"]["selectedDefault"]["selectionReasonZh"],
            )
            self.assertEqual(
                report["liveUpgradeSelection"]["excludedAceCandidates"][0]["reason"],
                "DEMOTE_RAW_RSI_FROM_ACE",
            )
            self.assertIn(
                "champion_tester_run_gate_ready",
                report["liveUpgradeSelection"]["upgradePrerequisites"],
            )
            self.assertFalse(report["liveUpgradeSelection"]["orderSendAllowed"])

            self._write_json(agent / "QuantGod_LiveRuntimePreflightProbe.json", {
                "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                "runtimeProbePassed": False,
                "dataPlaneReadyForLivePilotReview": False,
                "approvedLanes": ["hfmCryptoCfd"],
                "dashboardSnapshot": {
                    "fresh": False,
                    "ageSeconds": 248472.018,
                    "maxAgeSeconds": 300,
                    "symbolCount": 1,
                    "symbolNames": ["USDJPY"],
                },
                "probeResults": {
                    "symbolSelectedInDashboardOk": False,
                    "symbolRuntimeProbeOk": True,
                    "sidecarLiveTickOk": True,
                    "spreadProbeOk": True,
                    "livePilotModeOk": False,
                    "readOnlyModeOff": False,
                    "executionEnabledOk": False,
                    "tradeAllowedOk": False,
                },
                "blockers": [
                    {"code": "MT5_DASHBOARD_SNAPSHOT_STALE"},
                    {"code": "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED"},
                    {"code": "MT5_READ_ONLY_MODE_STILL_ACTIVE"},
                    {"code": "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT"},
                    {"code": "MT5_TRADE_ALLOWED_NOT_CONFIRMED"},
                ],
                "laneRuntimeChecks": [
                    {
                        "brokerSymbol": "#BTCUSD",
                        "runtimeProbeFresh": True,
                        "runtimeProbeAgeSeconds": 0.0,
                        "symbolPresentInSnapshot": False,
                        "symbolPresentInNames": False,
                        "spreadFieldPresent": False,
                    }
                ],
                "nextRequiredActionZh": "先补齐 dry-run replay、MT5 dashboard 新鲜快照、kill switch、账户、symbol 和价差证据。",
            })

            refreshed_report = build_ace_execution_candidate_pack(runtime, write=False)
            expected_focus_order = " -> ".join(
                refreshed_report["strategyShortlist"]["btcLineupBoard"]["recommendedFocusedRetestOrder"][:3]
            )
            self.assertEqual(
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["nextActionZh"],
                "先刷新 live16 dashboard，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。",
            )
            self.assertEqual(
                refreshed_report["strategyShortlist"]["nextActionZh"],
                "先刷新 live16 dashboard，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。 "
                f"随后继续按 BTC {expected_focus_order} 做 focused retest。",
            )
            self.assertEqual(
                refreshed_report["liveUpgradeSelection"]["nextActionZh"],
                "先刷新 live16 dashboard，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。",
            )
            self.assertEqual(
                refreshed_report["btcCryptoCfd"]["nextActionZh"],
                "先刷新 live16 dashboard，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。 "
                f"随后继续按 BTC {expected_focus_order} 这条稳定优先主线做 focused retest。",
            )
            run_gate_mt5_first = json.loads(
                (agent / "QuantGod_ChampionTesterRunGate.json").read_text(encoding="utf-8")
            )
            run_gate_mt5_first["blockers"] = [
                "live_dashboard_snapshot_stale",
                "outside_strategy_tester_window",
                "mt5_terminal_process_missing",
            ]
            run_gate_mt5_first["gate"] = {
                **dict(run_gate_mt5_first.get("gate") or {}),
                "blockers": [
                    "live_dashboard_snapshot_stale",
                    "outside_strategy_tester_window",
                    "mt5_terminal_process_missing",
                ],
                "authorizationLock": {"ok": True, "status": "ready"},
            }
            run_gate_mt5_first["decision"] = {
                **dict(run_gate_mt5_first.get("decision") or {}),
                "nextRequiredActionZh": "先恢复主 MT5 terminal64 进程并恢复 dashboard freshness，再重建 tester gate。",
                "canRunIsolatedTester": False,
            }
            run_gate_mt5_first["supportingProcessEvidence"] = {
                **dict(run_gate_mt5_first.get("supportingProcessEvidence") or {}),
                "blockers": ["mt5_terminal_process_missing"],
                "preferredTerminalPath": "/Applications/MetaTrader 5/terminal64.exe",
                "startupConfigPath": "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
                "dashboardPath": "/tmp/MetaTrader 5/MQL5/Files/QuantGod_Dashboard.json",
                "dashboardServerRunning": False,
                "readOnlyVerificationCommands": ["ps ax | rg -i 'terminal64|dashboard_server.js|backend-api'"],
            }
            self._write_json(agent / "QuantGod_ChampionTesterRunGate.json", run_gate_mt5_first)

            mt5_first_report = build_ace_execution_candidate_pack(runtime, write=False)
            self.assertEqual(
                mt5_first_report["executionReadinessBoard"]["closestResearchLaneNow"],
                "forexMt5",
            )
            self.assertEqual(
                [row["id"] for row in mt5_first_report["executionReadinessBoard"]["nextActionsOverall"][:3]],
                [
                    "restore_live_mt5_dashboard_refresh",
                    "wait_for_tester_window",
                    "run_forex_ab_tester_forward",
                ],
            )
            self.assertEqual(
                mt5_first_report["executionReadinessBoard"]["nextActionsOverall"][0]["id"],
                "restore_live_mt5_dashboard_refresh",
            )
            self.assertIn(
                "/Applications/MetaTrader 5/terminal64.exe",
                mt5_first_report["executionReadinessBoard"]["nextActionsOverall"][0]["actionZh"],
            )
            self.assertEqual(
                mt5_first_report["executionReadinessBoard"]["nextActionsOverall"][1]["lane"],
                "forexMt5",
            )
            self.assertEqual(
                mt5_first_report["executionReadinessBoard"]["nextActionsOverall"][2]["lane"],
                "forexMt5",
            )
            self.assertEqual(
                mt5_first_report["strategyShortlist"]["nextActionZh"],
                mt5_first_report["executionReadinessBoard"]["nextActionsOverall"][0]["actionZh"],
            )
            self.assertEqual(
                mt5_first_report["strategyShortlist"]["mt5LaneReadiness"]["nextActionZh"],
                "先恢复主 MT5 terminal64 进程（优先: /Applications/MetaTrader 5/terminal64.exe）并恢复 dashboard freshness，再重建 tester gate。",
            )
            self.assertEqual(
                mt5_first_report["executionReadinessBoard"]["nextActionsOverall"][0]["evidenceSnapshot"]["startupConfigPath"],
                "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
            )
            self.assertFalse(
                mt5_first_report["executionReadinessBoard"]["nextActionsOverall"][0]["evidenceSnapshot"]["dashboardServerRunning"]
            )
            self.assertIn(
                "需恢复进程=mt5_terminal_process_missing",
                mt5_first_report["strategyShortlist"]["mt5LaneReadiness"]["gateDiagnostics"]["summaryZh"],
            )
            self.assertEqual(
                refreshed_report["launchBoard"]["laneBoards"]["btc"]["readiness"]["ratio"],
                "3/9",
            )
            self.assertEqual(
                refreshed_report["launchBoard"]["laneBoards"]["btc"]["blockerFamilies"],
                ["external_refresh", "execution_mode"],
            )
            self.assertEqual(
                refreshed_report["launchBoard"]["laneBoards"]["btc"]["directExecutionBlockerCode"],
                None,
            )
            self.assertEqual(
                refreshed_report["launchBoard"]["laneBoards"]["btc"]["activeDuelSummaryZh"],
                refreshed_report["strategyShortlist"]["btcDuelBoard"]["recommendationZh"],
            )
            self.assertEqual(
                refreshed_report["launchBoard"]["criticalPath"][0]["checkId"],
                "dashboard_fresh",
            )
            self.assertEqual(
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["gateDiagnostics"]["externalRefreshBlockers"],
                ["MT5_DASHBOARD_SNAPSHOT_STALE"],
            )
            self.assertEqual(
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["gateDiagnostics"]["dataPlaneBlockers"],
                [],
            )
            self.assertEqual(
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["gateDiagnostics"]["executionModeBlockers"],
                [
                    "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
                    "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                    "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
                    "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
                ],
            )
            self.assertEqual(
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["gateDiagnostics"]["directExecutionBlockerCode"],
                None,
            )
            self.assertEqual(
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["readinessChecklist"]["rows"][2],
                {
                    "id": "tick_spread_ready",
                    "ok": True,
                    "labelZh": "tick/spread ready",
                    "dependencyCheckIds": ["runtime_probe_fresh"],
                    "sourceArtifact": "liveRuntimePreflightProbe.probeResults",
                    "evidenceKeyZh": "sidecarLiveTickOk/spreadProbeOk",
                    "nextActionZh": "保持 sidecar tick/spread 输出连续，不需要改执行模式。",
                },
            )
            self.assertTrue(
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["runtimeSnapshot"]["symbolSelectionEffectiveOk"]
            )
            self.assertEqual(
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["readinessChecklist"]["readyCount"],
                3,
            )
            self.assertEqual(
                refreshed_report["executionReadinessBoard"]["nextActionsOverall"][0]["actionZh"],
                "先刷新 live16 dashboard，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。",
            )
            self.assertIn(
                "当前主要卡在 dashboard freshness 和执行模式字段",
                refreshed_report["executionReadinessBoard"]["nextActionsOverall"][0]["whyNowZh"],
            )
            self.assertIn(
                "而不是 symbol 取证",
                refreshed_report["executionReadinessBoard"]["nextActionsOverall"][0]["whyNowZh"],
            )
            self.assertEqual(
                refreshed_report["executionReadinessBoard"]["laneSnapshots"][1]["currentModeZh"],
                "先刷新 dashboard freshness 与 execution-mode 证据",
            )
            self.assertIn(
                "selectedRaw=False selectedEffective=True",
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["runtimeSummaryZh"],
            )
            self.assertIn(
                "tick=True spread=True",
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["runtimeSummaryZh"],
            )
            self.assertIn(
                "livePilotMode=False",
                refreshed_report["strategyShortlist"]["btcLaneReadiness"]["runtimeSummaryZh"],
            )
            self.assertEqual(
                report["rsiDemotionReview"]["replacementPlan"]["primaryForexAce"]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["rsiDemotionReview"]["replacementPlan"]["btcTargetMiddleQuality"]["strategyId"],
                "hfm_crypto_btc_tpsl_target_middle",
            )
            expected_retest_order = " -> ".join(
                report["strategyShortlist"]["btcLineupBoard"]["recommendedFocusedRetestOrder"]
            )
            self.assertIn(
                expected_retest_order,
                report["rsiDemotionReview"]["replacementPlan"]["nextActionZh"],
            )
            self.assertNotIn(
                "hfm_crypto_btc_tpsl_0302 -> hfm_crypto_btc_tpsl_4138 -> hfm_crypto_btc_tpsl_4060",
                report["rsiDemotionReview"]["replacementPlan"]["nextActionZh"],
            )
            self.assertFalse(report["rsiDemotionReview"]["safety"]["orderSendAllowed"])
            self.assertIn("raw RSI 已降级", report["decision"]["nextActionZh"])
            self.assertIn("当前第一动作是", report["decision"]["nextActionZh"])
            expected_decision_focus_order = " -> ".join(
                report["strategyShortlist"]["btcLineupBoard"]["recommendedFocusedRetestOrder"][:3]
            )
            self.assertIn(
                expected_decision_focus_order,
                report["decision"]["nextActionZh"],
            )
            self.assertFalse(report["decision"]["canProceedToSeparateReleaseLane"])
            self.assertEqual(report["decision"]["readyStrategyCountForSeparateReleaseLane"], 0)
            self.assertEqual(report["decision"]["closestResearchLaneNow"], "btcCryptoCfd")
            self.assertFalse(report["decision"]["canReleaseExecutionNow"])
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])
            self.assertIn("BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING", report["releaseBlockers"])
            self.assertEqual(
                report["sourceArtifactSummaries"]["championTesterRunGate"]["nextTesterWindowStartJstIso"],
                "2026-06-08T20:10:00+09:00",
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["championTesterRunGate"]["nextTesterWindowMinutesUntilStart"],
                report["strategyShortlist"]["mt5LaneReadiness"]["testerSnapshot"]["minutesUntilStart"],
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["liveRuntimePreflightProbe"]["dashboardSymbolNames"],
                ["USDJPYc"],
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["liveEvidenceIntake"]["tradePermissionBlocker"],
                "READ_ONLY_MODE",
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["finalAdvisoryPickStrategyId"],
                report["strategyShortlist"]["selectionRefreshAudit"]["currentDefaultStrategyId"],
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["recommendedStableStrategyId"],
                report["strategyShortlist"]["selectionRefreshAudit"]["currentDefaultStrategyId"],
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["currentConsensusDefaultStrategyId"],
                report["strategyShortlist"]["selectionRefreshAudit"]["currentDefaultStrategyId"],
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["currentConsensusDefaultSource"],
                "strategyShortlist.selectedDefault",
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["currentConsensusDiffersFromOptimizerLegacy"],
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["currentConsensusDefaultStrategyId"]
                not in {
                    report["sourceArtifactSummaries"]["tpSlOptimizer"]["optimizerLegacyStableStrategyId"],
                    report["sourceArtifactSummaries"]["tpSlOptimizer"]["optimizerLegacyFinalAdvisoryPickStrategyId"],
                },
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["optimizerLegacyFinalAdvisoryPickStrategyId"],
                "hfm_crypto_btc_tpsl_0016",
            )
            self.assertIn(
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["currentConsensusDefaultStrategyId"],
                report["sourceArtifactSummaries"]["tpSlOptimizer"]["operatorSummaryZh"],
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["btcStrategyScan"]["topCandidateStrategyId"],
                "hfm_crypto_btc_stability_short_window_shadow_v1",
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["aceStrategyScout"]["topResearchCryptoStrategyId"],
                "hfm_crypto_btc_stability_short_window_shadow_v1",
            )
            self.assertIn(
                "scout@",
                report["sourceArtifactSummaryZh"],
            )
            self.assertIn(
                "windowStart=2026-06-08T20:10:00+09:00",
                report["sourceArtifactSummaryZh"],
            )
            self.assertIn(
                f"currentDefault={report['sourceArtifactSummaries']['tpSlOptimizer']['currentConsensusDefaultStrategyId']}",
                report["sourceArtifactSummaryZh"],
            )
            self.assertIn(
                "optimizerLegacy=hfm_crypto_btc_tpsl_0016",
                report["sourceArtifactSummaryZh"],
            )
            self.assertIn(
                "tradeBlocker=READ_ONLY_MODE",
                report["sourceArtifactSummaryZh"],
            )
            self.assertTrue((agent / "QuantGod_AceExecutionCandidatePack.json").exists())

            saved = read_ace_execution_candidate_pack(runtime)
            self.assertEqual(saved["decision"]["defaultBtcStrategyId"], "hfm_crypto_btc_tpsl_0016")

            stale_payload = json.loads((agent / "QuantGod_AceExecutionCandidatePack.json").read_text(encoding="utf-8"))
            stale_payload["sourceArtifactSummaries"]["btcStrategyScan"]["generatedAtIso"] = "2026-06-08T05:00:00Z"
            (agent / "QuantGod_AceExecutionCandidatePack.json").write_text(
                json.dumps(stale_payload),
                encoding="utf-8",
            )
            refreshed_saved = read_ace_execution_candidate_pack(runtime)
            self.assertNotEqual(
                refreshed_saved["sourceArtifactSummaries"]["btcStrategyScan"]["generatedAtIso"],
                "2026-06-08T05:00:00Z",
            )

            stale_payload = json.loads((agent / "QuantGod_AceExecutionCandidatePack.json").read_text(encoding="utf-8"))
            stale_payload["sourceArtifactSummaries"]["aceStrategyScout"]["generatedAtIso"] = "2026-06-08T05:00:00Z"
            (agent / "QuantGod_AceExecutionCandidatePack.json").write_text(
                json.dumps(stale_payload),
                encoding="utf-8",
            )
            refreshed_saved = read_ace_execution_candidate_pack(runtime)
            self.assertNotEqual(
                refreshed_saved["sourceArtifactSummaries"]["aceStrategyScout"]["generatedAtIso"],
                "2026-06-08T05:00:00Z",
            )

            stale_payload = json.loads((agent / "QuantGod_AceExecutionCandidatePack.json").read_text(encoding="utf-8"))
            stale_payload["sourceArtifactSummaries"]["liveEvidenceIntake"]["generatedAtIso"] = "2026-06-08T05:00:00Z"
            (agent / "QuantGod_AceExecutionCandidatePack.json").write_text(
                json.dumps(stale_payload),
                encoding="utf-8",
            )
            refreshed_saved = read_ace_execution_candidate_pack(runtime)
            self.assertNotEqual(
                refreshed_saved["sourceArtifactSummaries"]["liveEvidenceIntake"]["generatedAtIso"],
                "2026-06-08T05:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
