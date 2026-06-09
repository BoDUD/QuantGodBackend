from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tools.ace_upgrade_action_plan import (
    _artifact_summary,
    _build_action_queue,
    _decision_next_action_why,
    _mt5_gate_diagnostics,
    _next_hour_action_board,
    _mt5_window_briefing,
    _priority_summary,
    _resolve_candidate_pack,
    _workstream_status,
    build_ace_upgrade_action_plan,
    read_ace_upgrade_action_plan,
)


class AceUpgradeActionPlanTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_mt5_countdown_is_zero_once_window_is_open(self) -> None:
        next_window = {
            "label": "daily_night",
            "startJstIso": "2026-06-08T20:10:00+09:00",
            "endJstIso": "2026-06-08T23:30:00+09:00",
            "minutesUntilStart": 302.4,
        }
        with patch(
            "tools.ace_upgrade_action_plan._utc_now",
            return_value=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
        ):
            summary = _artifact_summary(Path("unused.json"), {"nextTesterWindow": next_window}, kind="championTesterRunGate")
            diagnostics = _mt5_gate_diagnostics({"nextTesterWindow": next_window, "gate": {}})
        self.assertEqual(summary["nextTesterWindowMinutesUntilStart"], 0.0)
        self.assertEqual(diagnostics["minutesUntilStart"], 0.0)

    def test_mt5_window_briefing_enters_final_hour_mode(self) -> None:
        briefing = _mt5_window_briefing(
            {
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
                }
            },
            {
                "gateDiagnostics": {"minutesUntilStart": 38.1},
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1-usdjpy_tpsl_14r_1_2",
                ],
            },
        )
        self.assertEqual(briefing["phase"], "PRE_WINDOW_FINAL_HOUR")
        self.assertEqual(briefing["autoClearCheckIds"], ["tester_window_open"])
        self.assertIn("dashboard_fresh", briefing["preWindowCheckIds"])
        self.assertIn("tester_can_run_now", briefing["residualAfterWindowOpenCheckIds"])
        self.assertEqual(briefing["readinessNow"]["ratio"], "0/7")
        self.assertEqual(briefing["expectedReadinessAfterWindowOpen"]["ratio"], "1/7")
        self.assertEqual(briefing["windowOpenGainCount"], 1)
        self.assertTrue(briefing["postWindowStillBlocked"])
        self.assertEqual(
            briefing["highestLeveragePreWindowCheckIds"],
            ["isolated_account_context_ready"],
        )

    def test_priority_summary_prefers_current_action_queue_over_stale_pack_next_actions(self) -> None:
        summary = _priority_summary(
            strategy_shortlist={
                "btcTopStrategies": [
                    {"strategyId": "hfm_crypto_btc_tpsl_0302", "role": "stableAnchor"},
                    {"strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1", "role": "stableAlternative"},
                    {"strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1", "role": "highYieldTradeoff"},
                ],
                "btcLineupBoard": {
                    "stableAnchorStrategyId": "hfm_crypto_btc_tpsl_0302",
                    "nearLiveChallengerStrategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                    "nearLiveMiddleWindowVariantStrategyIds": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_middle_window_0021",
                        "hfm_crypto_btc_near_live_middle_window_0040",
                    ],
                    "nearLiveMiddleWindowVariantRows": [
                        {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003", "stopLossPriceMove": 325.0},
                        {"strategyId": "hfm_crypto_btc_near_live_middle_window_0021", "stopLossPriceMove": 300.0},
                        {"strategyId": "hfm_crypto_btc_near_live_middle_window_0040", "stopLossPriceMove": 350.0},
                    ],
                    "nearLiveMiddleWindowVariantStopLossLadder": [325.0, 300.0, 350.0],
                    "nearLiveMiddleWindowVariantSummaryZh": "当前 near-live middle-window 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_middle_window_0040(SL=350.0)。",
                    "nearLiveConvergedVariantStrategyIds": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_middle_window_0021",
                        "hfm_crypto_btc_near_live_stoploss_ladder_0013",
                    ],
                    "nearLiveConvergedVariantRows": [
                        {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003", "stopLossPriceMove": 325.0},
                        {"strategyId": "hfm_crypto_btc_near_live_middle_window_0021", "stopLossPriceMove": 300.0},
                        {"strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0013", "stopLossPriceMove": 312.5},
                    ],
                    "nearLiveConvergedVariantStopLossLadder": [325.0, 300.0, 312.5],
                    "nearLiveConvergedVariantSummaryZh": "当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0013(SL=312.5)。",
                    "nearLiveFollowupBestStrategyId": "hfm_crypto_btc_near_live_followup_0007",
                    "nearLiveFollowupImprovesRepair": True,
                    "nearLiveFollowupOutcomeZh": "near-live stability follow-up 已找到比当前修复版更强的第二候选；下一轮优先围绕 follow-up 版本继续复验。",
                    "nearLiveRefinementBestStrategyId": "hfm_crypto_btc_near_live_refinement_0005",
                    "nearLiveRefinementImprovesFollowup": True,
                    "nearLiveRefinementOutcomeZh": "near-live stability refinement 已找到比当前 follow-up 更强的第二候选；下一轮优先围绕 refinement 版本继续复验。",
                    "nearLiveMiddleWindowFollowupBestStrategyId": "hfm_crypto_btc_near_live_middle_window_0009",
                    "nearLiveMiddleWindowFollowupImprovesFollowup": True,
                    "nearLiveMiddleWindowFollowupOutcomeZh": "near-live middle-window follow-up 已在保住当前有效窗口数的前提下改善 middle_third；下一轮优先围绕 middle-window 版本复验。",
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
                    "yieldFrontierStrategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                    "yieldLeaderConfirmationBestStrategyId": "hfm_crypto_btc_yield_leader_confirmation_0018",
                    "yieldLeaderConfirmationImprovesBaseline": False,
                    "yieldLeaderConfirmationOutcomeZh": "yield leader 局部确认暂未推翻当前高收益 leader；继续把它作为高收益参考。",
                    "stableMiddleThirdFollowupBestStrategyId": "hfm_crypto_btc_stable_middle_followup_0008",
                    "stableMiddleThirdFollowupImprovesRepair": False,
                    "stableMiddleThirdFollowupOutcomeZh": "stable middle-third follow-up 局部搜索暂未推翻当前 repair 候选；继续把 0302 和现有 repair 版本作为主锚点。",
                    "stableMiddleWeakWindowBridgeBestStrategyId": "hfm_crypto_btc_stable_middle_bridge_0004",
                    "stableMiddleWeakWindowBridgeImprovesAggregate": True,
                    "stableMiddleWeakWindowBridgeImprovesWeakWindow": False,
                    "stableMiddleWeakWindowBridgeImprovesBaseline": False,
                    "stableMiddleWeakWindowBridgeOutcomeZh": "stable middle weak-window bridge 提高了整体有效窗口数，但 middle_third 弱窗口本身没有改善；把它当作折中观察线，不当作真实 weak-window 修复。",
                    "stableMiddleTradeoffFollowupBestStrategyId": "hfm_crypto_btc_stable_middle_tradeoff_0005",
                    "stableMiddleTradeoffFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0005",
                        "pnlUsd": 42.0,
                        "sharpe": 1.5,
                        "tradeCount": 72,
                        "validWindowCount": 4,
                        "windowCount": 6,
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 350.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "stableMiddleTradeoffFollowupImprovesBridge": True,
                    "stableMiddleTradeoffFollowupImprovesWeakWindow": False,
                    "stableMiddleTradeoffFollowupImprovesBaseline": False,
                    "stableMiddleTradeoffFollowupOutcomeZh": "stable middle tradeoff follow-up 改善了 bridge 线，但 middle_third 仍未真正修复；把它当作下一条折中观察线。",
                    "recommendedFocusedRetestOrder": [
                        "hfm_crypto_btc_tpsl_0302",
                        "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                        "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                        "hfm_crypto_btc_stable_middle_tradeoff_0005",
                    ],
                    "recommendationZh": "默认继续拿稳健锚点做主研究对象，先复验稳定 challenger，再把当前高收益 leader 作为第三顺位收益对照，并把 stable middle tradeoff follow-up 作为第四顺位修复观察线。",
                },
            },
            execution_readiness_board={
                "closestResearchLaneNow": "forexMt5",
                "selectedLaneForSeparateReleaseReview": "forexMt5",
                "laneSnapshots": [
                    {
                        "lane": "forexMt5",
                        "focusStrategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    },
                ],
                "nextActionsOverall": [
                    {
                        "id": "btc_runtime_preflight_refresh",
                        "lane": "btcCryptoCfd",
                        "actionZh": "旧 BTC 摘要",
                    },
                ],
            },
            live_selection={
                "selectedStrategy": {
                    "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    "seedId": "GA-USDJPY-G0093-C0004",
                },
            },
            action_queue=[
                {
                    "id": "restore_live_mt5_dashboard_refresh",
                    "lane": "forexMt5",
                    "actionZh": "先恢复 MT5 live dashboard 刷新。",
                    "whyNowZh": "开窗后第一优先 residual 仍是 dashboard freshness。",
                    "evidenceSummaryZh": "dashboardFresh=false",
                    "blockers": ["live_dashboard_snapshot_stale"],
                    "recommendedOrder": 1,
                },
                {
                    "id": "separate_account_context_sync_review",
                    "lane": "forexMt5",
                    "actionZh": "单独复核隔离账户上下文。",
                    "whyNowZh": "开窗后第二优先 residual 是 isolated account context。",
                    "evidenceSummaryZh": "isolatedAccountContextReady=false",
                    "blockers": ["isolated_tester_account_context_not_ready"],
                    "recommendedOrder": 2,
                },
            ],
        )
        self.assertEqual(
            [row["id"] for row in summary["nextActionsOverall"]],
            [
                "restore_live_mt5_dashboard_refresh",
                "separate_account_context_sync_review",
            ],
        )
        self.assertEqual(summary["nextActionsOverall"][0]["lane"], "forexMt5")
        self.assertEqual(
            summary["nextActionsOverall"][0]["whyNowZh"],
            "开窗后第一优先 residual 仍是 dashboard freshness。",
        )
        self.assertEqual(summary["btcContextSnapshot"]["lane"], "btcCryptoCfd")
        self.assertEqual(
            summary["btcContextSnapshot"]["stableAnchorStrategyId"],
            "hfm_crypto_btc_tpsl_0302",
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveChallengerStrategyId"],
            "hfm_crypto_btc_sample_balanced_both_shadow_v1",
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveClusterRefinementBestStrategyId"],
            "hfm_crypto_btc_near_live_cluster_refinement_0007",
        )

        self.assertTrue(summary["btcContextSnapshot"]["nearLiveClusterRefinementImprovesContender"])
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveSignalRefinementBestStrategyId"],
            "hfm_crypto_btc_near_live_signal_refinement_0008",
        )
        self.assertTrue(summary["btcContextSnapshot"]["nearLiveSignalRefinementImprovesContender"])
        self.assertIn(
            "signal-kernel",
            summary["btcContextSnapshot"]["nearLiveSignalRefinementOutcomeZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveTempoRefinementBestStrategyId"],
            "hfm_crypto_btc_near_live_tempo_refinement_0009",
        )
        self.assertTrue(summary["btcContextSnapshot"]["nearLiveTempoRefinementImprovesContender"])
        self.assertIn(
            "hold/cooldown",
            summary["btcContextSnapshot"]["nearLiveTempoRefinementOutcomeZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveStoplossLadderRefinementBestStrategyId"],
            "hfm_crypto_btc_near_live_stoploss_ladder_0013",
        )
        self.assertTrue(summary["btcContextSnapshot"]["nearLiveStoplossLadderRefinementImprovesContender"])
        self.assertIn(
            "stop-loss ladder",
            summary["btcContextSnapshot"]["nearLiveStoplossLadderRefinementOutcomeZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveExitRefinementBestStrategyId"],
            "hfm_crypto_btc_near_live_exit_refinement_0011",
        )
        self.assertTrue(summary["btcContextSnapshot"]["nearLiveExitRefinementImprovesContender"])
        self.assertIn(
            "TP/SL exit",
            summary["btcContextSnapshot"]["nearLiveExitRefinementOutcomeZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveMiddleTradeoffBestStrategyId"],
            "hfm_crypto_btc_near_live_middle_tradeoff_0004",
        )
        self.assertTrue(summary["btcContextSnapshot"]["nearLiveMiddleTradeoffImprovesContender"])
        self.assertIn(
            "middle tradeoff",
            summary["btcContextSnapshot"]["nearLiveMiddleTradeoffOutcomeZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["yieldFrontierStrategyId"],
            "hfm_crypto_btc_yield_balanced_both_shadow_v1",
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveRefinementBestStrategyId"],
            "hfm_crypto_btc_near_live_refinement_0005",
        )
        self.assertTrue(summary["btcContextSnapshot"]["nearLiveRefinementImprovesFollowup"])
        self.assertIn(
            "refinement",
            summary["btcContextSnapshot"]["nearLiveRefinementOutcomeZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveMiddleWindowFollowupBestStrategyId"],
            "hfm_crypto_btc_near_live_middle_window_0009",
        )
        self.assertTrue(summary["btcContextSnapshot"]["nearLiveMiddleWindowFollowupImprovesFollowup"])
        self.assertIn(
            "middle-window",
            summary["btcContextSnapshot"]["nearLiveMiddleWindowFollowupOutcomeZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["recommendedFocusedRetestOrder"],
            [
                "hfm_crypto_btc_tpsl_0302",
                "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                "hfm_crypto_btc_stable_middle_tradeoff_0005",
            ],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["stabilityFirstTop3StrategyIds"],
            [
                "hfm_crypto_btc_tpsl_0302",
                "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "hfm_crypto_btc_stable_middle_tradeoff_0005",
            ],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["yieldInclusiveTop3StrategyIds"],
            [
                "hfm_crypto_btc_tpsl_0302",
                "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "hfm_crypto_btc_yield_balanced_both_shadow_v1",
            ],
        )
        self.assertIn(
            "stable_middle_tradeoff_0005",
            summary["btcContextSnapshot"]["stabilityFirstSummaryZh"],
        )
        self.assertIn(
            "yield_balanced_both_shadow_v1",
            summary["btcContextSnapshot"]["yieldInclusiveSummaryZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveMiddleWindowVariantStrategyIds"],
            [
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_middle_window_0040",
            ],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveMiddleWindowVariantStopLossLadder"],
            [325.0, 300.0, 350.0],
        )
        self.assertIn(
            "0040",
            summary["btcContextSnapshot"]["nearLiveMiddleWindowVariantSummaryZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveConvergedVariantStrategyIds"],
            [
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_stoploss_ladder_0013",
            ],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["nearLiveConvergedVariantStopLossLadder"],
            [325.0, 300.0, 312.5],
        )
        self.assertIn(
            "near_live_stoploss_ladder_0013",
            summary["btcContextSnapshot"]["nearLiveConvergedVariantSummaryZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["yieldLeaderConfirmationBestStrategyId"],
            "hfm_crypto_btc_yield_leader_confirmation_0018",
        )
        self.assertFalse(summary["btcContextSnapshot"]["yieldLeaderConfirmationImprovesBaseline"])
        self.assertIn(
            "yield leader 局部确认暂未推翻",
            summary["btcContextSnapshot"]["yieldLeaderConfirmationOutcomeZh"],
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["stableMiddleThirdFollowupBestStrategyId"],
            "hfm_crypto_btc_stable_middle_followup_0008",
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["stableMiddleWeakWindowBridgeBestStrategyId"],
            "hfm_crypto_btc_stable_middle_bridge_0004",
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["stableMiddleTradeoffFollowupBestStrategyId"],
            "hfm_crypto_btc_stable_middle_tradeoff_0005",
        )
        self.assertEqual(
            summary["btcContextSnapshot"]["stableMiddleTradeoffFollowupBestTradeoff"]["strategyId"],
            "hfm_crypto_btc_stable_middle_tradeoff_0005",
        )
        self.assertFalse(summary["btcContextSnapshot"]["stableMiddleThirdFollowupImprovesRepair"])
        self.assertTrue(summary["btcContextSnapshot"]["stableMiddleWeakWindowBridgeImprovesAggregate"])
        self.assertFalse(summary["btcContextSnapshot"]["stableMiddleWeakWindowBridgeImprovesWeakWindow"])
        self.assertFalse(summary["btcContextSnapshot"]["stableMiddleWeakWindowBridgeImprovesBaseline"])
        self.assertTrue(summary["btcContextSnapshot"]["stableMiddleTradeoffFollowupImprovesBridge"])
        self.assertFalse(summary["btcContextSnapshot"]["stableMiddleTradeoffFollowupImprovesWeakWindow"])
        self.assertFalse(summary["btcContextSnapshot"]["stableMiddleTradeoffFollowupImprovesBaseline"])
        self.assertIn(
            "follow-up 局部搜索暂未推翻",
            summary["btcContextSnapshot"]["stableMiddleThirdFollowupOutcomeZh"],
        )
        self.assertIn(
            "提高了整体有效窗口数",
            summary["btcContextSnapshot"]["stableMiddleWeakWindowBridgeOutcomeZh"],
        )
        self.assertIn(
            "改善了 bridge 线",
            summary["btcContextSnapshot"]["stableMiddleTradeoffFollowupOutcomeZh"],
        )

    def test_priority_summary_prefers_current_focus_lane_even_when_raw_queue_starts_with_mt5(self) -> None:
        summary = _priority_summary(
            strategy_shortlist={
                "btcTopStrategies": [
                    {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003", "role": "stableAnchor"},
                    {"strategyId": "hfm_crypto_btc_near_live_middle_window_0021", "role": "stableAlternative"},
                    {"strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0001", "role": "repairObservation"},
                ],
                "btcLineupBoard": {
                    "stableAnchorStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "nearLiveChallengerStrategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                    "stableMiddleTradeoffFollowupBestStrategyId": "hfm_crypto_btc_stable_middle_tradeoff_0001",
                    "recommendedFocusedRetestOrder": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_middle_window_0021",
                        "hfm_crypto_btc_stable_middle_tradeoff_0001",
                    ],
                    "recommendationZh": "默认继续拿当前已收敛的稳健锚点做主研究对象。",
                },
            },
            execution_readiness_board={
                "closestResearchLaneNow": "btcCryptoCfd",
                "selectedLaneForSeparateReleaseReview": "forexMt5",
                "laneSnapshots": [
                    {"lane": "btcCryptoCfd", "focusStrategyId": "hfm_crypto_btc_near_live_middle_window_0003"},
                    {"lane": "forexMt5", "focusStrategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004"},
                ],
                "nextActionsOverall": [],
            },
            live_selection={
                "selectedStrategy": {
                    "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    "seedId": "GA-USDJPY-G0093-C0004",
                },
            },
            action_queue=[
                {
                    "id": "restore_live_mt5_dashboard_refresh",
                    "lane": "forexMt5",
                    "actionZh": "先恢复 MT5 live dashboard 刷新。",
                    "whyNowZh": "MT5 当前主要卡在 dashboard freshness。",
                    "blockers": ["live_dashboard_snapshot_stale"],
                },
                {
                    "id": "refresh_btc_runtime_preflight_inputs",
                    "lane": "btcCryptoCfd",
                    "actionZh": "先刷新 BTC runtime preflight。",
                    "whyNowZh": "BTC 当前还能继续推进研究，但缺 runtime freshness/execution mode 证据。",
                    "blockers": ["MT5_DASHBOARD_SNAPSHOT_STALE", "MT5_READ_ONLY_MODE_STILL_ACTIVE"],
                    "focusClusterSummaryZh": "当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。",
                    "yieldFrontierClusterSummaryZh": "当前高收益 leader 已收敛在同一 near-live 参数簇；当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。",
                },
                {
                    "id": "rerun_btc_tp_sl_optimizer",
                    "lane": "btcCryptoCfd",
                    "actionZh": "继续做 BTC focused retest。",
                    "whyNowZh": "先围绕 next distinct contender 做 near-live 复验。",
                    "blockers": ["HFM_SHARPE_LT_MIN"],
                    "focusClusterCanonicalStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "focusClusterAliasStrategyIds": [
                        "hfm_crypto_btc_near_live_middle_window_0021",
                        "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                    ],
                    "focusClusterSummaryZh": "当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。",
                    "comparisonClusterCanonicalStrategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                    "comparisonClusterAliasStrategyIds": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                    ],
                    "comparisonClusterSummaryZh": "当前 next distinct contender=hfm_crypto_btc_near_live_middle_window_0021；当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。",
                    "yieldFrontierClusterSummaryZh": "当前高收益 leader 已收敛在同一 near-live 参数簇；当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。",
                },
                {
                    "id": "rerun_btc_strategy_scanner",
                    "lane": "btcCryptoCfd",
                    "actionZh": "继续复扫 BTC 候选。",
                    "whyNowZh": "继续验证当前收敛簇是否出现更稳替代。",
                    "blockers": [],
                },
            ],
        )
        self.assertEqual(
            [row["id"] for row in summary["nextActionsOverall"]],
            [
                "refresh_btc_runtime_preflight_inputs",
                "rerun_btc_tp_sl_optimizer",
                "rerun_btc_strategy_scanner",
            ],
        )
        self.assertEqual(summary["nextActionsOverall"][0]["lane"], "btcCryptoCfd")
        self.assertIn("near_live_stoploss_ladder_0001", summary["currentResearchFocusClusterSummaryZh"])
        self.assertIn("当前高收益 leader 已收敛", summary["currentResearchYieldFrontierClusterSummaryZh"])

    def test_priority_summary_prefers_mt5_actionable_refresh_before_passive_window_wait(self) -> None:
        summary = _priority_summary(
            strategy_shortlist={
                "laneVerdicts": {
                    "mt5": {
                        "strongestNow": {
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                        }
                    }
                },
                "mt5TopStrategies": [
                    {
                        "seedId": "GA-USDJPY-G0093-C0004",
                        "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    }
                ],
            },
            execution_readiness_board={
                "closestResearchLaneNow": "forexMt5",
                "selectedLaneForSeparateReleaseReview": "forexMt5",
                "laneSnapshots": [
                    {
                        "lane": "forexMt5",
                        "focusStrategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    }
                ],
                "nextActionsOverall": [],
            },
            live_selection={
                "selectedStrategy": {
                    "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    "seedId": "GA-USDJPY-G0093-C0004",
                },
            },
            action_queue=[
                {
                    "id": "wait_for_tester_window",
                    "lane": "forexMt5",
                    "stage": "tester_window",
                    "actionZh": "等待 tester 窗口。",
                    "whyNowZh": "窗口尚未打开。",
                    "blockers": ["outside_strategy_tester_window"],
                },
                {
                    "id": "restore_live_mt5_dashboard_refresh",
                    "lane": "forexMt5",
                    "stage": "runtime_freshness",
                    "actionZh": "先恢复 MT5 live dashboard 刷新。",
                    "whyNowZh": "开窗前最值钱的是先清 dashboard freshness。",
                    "blockers": ["live_dashboard_snapshot_stale"],
                },
                {
                    "id": "run_forex_ab_tester_forward",
                    "lane": "forexMt5",
                    "stage": "tester_forward",
                    "actionZh": "启动 A/B tester-forward。",
                    "whyNowZh": "窗口打开且 dashboard fresh 后进入 guarded run。",
                    "blockers": ["live_dashboard_snapshot_stale", "outside_strategy_tester_window"],
                },
            ],
        )

        self.assertEqual(
            [row["id"] for row in summary["nextActionsOverall"]],
            [
                "restore_live_mt5_dashboard_refresh",
                "wait_for_tester_window",
                "run_forex_ab_tester_forward",
            ],
        )
        self.assertEqual(
            summary["currentLaneActionQueueIds"],
            [
                "restore_live_mt5_dashboard_refresh",
                "wait_for_tester_window",
                "run_forex_ab_tester_forward",
            ],
        )

    def test_workstream_status_surfaces_focus_and_yield_cluster_summaries(self) -> None:
        workstream = _workstream_status(
            priority_summary={
                "currentResearchFocusLane": "btcCryptoCfd",
                "currentResearchFocusStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "currentResearchFocusClusterCanonicalStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "currentResearchFocusClusterAliasStrategyIds": [
                    "hfm_crypto_btc_near_live_middle_window_0021",
                    "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                ],
                "currentResearchFocusClusterSummaryZh": "当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。",
                "currentResearchDuelSummaryZh": "默认继续拿当前已收敛的稳健锚点做主研究对象。",
                "currentResearchNearLiveChallengerStrategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "currentResearchYieldFrontierStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "currentResearchYieldFrontierClusterSummaryZh": "当前高收益 leader 已收敛在同一 near-live 参数簇；当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。",
                "currentResearchComparisonClusterCanonicalStrategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "currentResearchComparisonClusterAliasStrategyIds": [
                    "hfm_crypto_btc_near_live_middle_window_0003",
                    "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                ],
                "currentResearchComparisonClusterSummaryZh": "当前 next distinct contender=hfm_crypto_btc_near_live_middle_window_0021；当前 near-live 收敛簇前排变体: hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。",
                "selectedLaneForSeparateReleaseReview": "forexMt5",
                "selectedReleaseAbSummaryZh": "默认继续把 G0093 视为暂时主冠军，但任何 release 判断都必须等 G0093/G0102 的隔离 tester-forward A/B 结果。",
                "selectedReleaseAbContenderSeedId": "GA-USDJPY-G0102-C0004",
                "canProceedToSeparateReleaseLane": False,
            },
            live_selection={
                "selectedStrategy": {
                    "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                    "seedId": "GA-USDJPY-G0093-C0004",
                }
            },
            tester_environment={
                "runGateBlockers": ["outside_strategy_tester_window"],
                "canRunIsolatedTester": False,
            },
            action_queue=[
                {
                    "id": "refresh_btc_runtime_preflight_inputs",
                    "lane": "btcCryptoCfd",
                    "priorityBucket": "current_research_focus",
                    "actionZh": "先刷新 BTC runtime preflight。",
                    "gateDiagnostics": {},
                }
            ],
            execution_readiness_board={
                "laneSnapshots": [
                    {"lane": "btcCryptoCfd", "focusStrategyId": "hfm_crypto_btc_near_live_middle_window_0003", "readinessChecklist": {}},
                    {"lane": "forexMt5", "focusStrategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004", "readinessChecklist": {}},
                ],
                "closureQueue": [],
                "primaryClosureQueue": [],
                "deferredClosureQueue": [],
            },
        )
        research = workstream["researchWorkstream"]
        self.assertIn("near_live_stoploss_ladder_0001", research["focusClusterSummaryZh"])
        self.assertIn("当前高收益 leader 已收敛", research["yieldFrontierClusterSummaryZh"])

    def test_build_action_queue_attaches_mt5_in_window_evidence_to_residual_actions(self) -> None:
        queue = _build_action_queue(
            selected_lane="forexMt5",
            selected_seed="GA-USDJPY-G0093-C0004",
            selected_strategy="USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
            prerequisites=["isolated_tester_forward_report_ready", "champion_tester_run_gate_ready"],
            run_gate_blockers=[
                "authorization_lock_expired",
                "live_dashboard_snapshot_stale",
                "isolated_tester_account_context_not_ready",
                "sensitive_account_context_sync_required",
            ],
            process_blockers=["mt5_terminal_process_missing"],
            can_run_tester=False,
            lock_ready=False,
            target_reached=True,
            forward_request={
                "selectedTasks": [
                    {
                        "candidateId": "g0093-usdjpy-rsi-champion-tester-forward-v1",
                        "label": "G0093",
                        "configOnlyCommand": "echo config",
                        "guardedRunTerminalCommand": "echo guarded",
                    }
                ]
            },
            next_tester_window={
                "status": "open_now",
                "label": "daily_night",
                "startJstIso": "2026-06-08T20:10:00+09:00",
                "endJstIso": "2026-06-08T23:30:00+09:00",
                "minutesUntilStart": 0.0,
            },
            strategy_shortlist={
                "mt5LaneReadiness": {
                    "testerSummaryZh": "liveSessionOk=False window=daily_night start=2026-06-08T20:10:00+09:00 minutesUntilStart=0.0 queueCount=8。",
                    "readinessChecklist": {
                        "summaryZh": "已满足 1/7 项；未满足: live_session_fresh, authorization_lock_ready, dashboard_fresh, isolated_account_context_ready, sensitive_sync_cleared, tester_can_run_now。",
                    },
                    "windowBriefing": {
                        "phase": "IN_WINDOW",
                        "summaryZh": "tester window 已打开。",
                        "postWindowPrimarySummaryZh": "开窗后第一优先仍是 dashboard_fresh, isolated_account_context_ready；已自动解除 tester_window_open。",
                        "readinessNow": {"ratio": "1/7"},
                        "highestLeveragePostWindowCheckIds": ["dashboard_fresh", "isolated_account_context_ready"],
                    },
                }
            },
            preflight={},
            live_evidence_intake={},
            hfm_review={},
            run_gate={
                "gate": {
                    "liveSession": {
                        "ok": False,
                        "snapshotTimestamp": "2026-06-05T18:47:17+09:00",
                        "snapshotAgeMinutes": 4415.7,
                        "maxSnapshotAgeMinutes": 30,
                    },
                    "authorizationLock": {
                        "status": "blocked",
                        "expiresAtIso": "2026-06-03T13:49:59+00:00",
                        "createdAtIso": "2026-06-03T12:19:59+00:00",
                        "allowOutsideWindow": False,
                    },
                },
                "decision": {"canRunIsolatedTester": False},
                "supportingProcessEvidence": {
                    "preferredTerminalPath": "/Applications/MetaTrader 5/terminal64.exe",
                    "startupConfigPath": "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
                    "dashboardPath": "/tmp/MetaTrader 5/MQL5/Files/QuantGod_Dashboard.json",
                    "dashboardServerRunning": False,
                    "readOnlyVerificationCommands": ["ps ax | rg -i 'terminal64|dashboard_server.js|backend-api'"],
                },
            },
            account_context={
                "ready": False,
                "mode": "PREFLIGHT_ONLY_NO_SENSITIVE_COPY",
                "missingTarget": ["Config/accounts.dat"],
                "sensitiveAccountContextSyncRequired": True,
                "nextActionZh": "隔离 tester 账户上下文不完整；需要单独受控同步账户上下文后再重试 Strategy Tester。",
            },
        )
        self.assertEqual(queue[0]["id"], "restore_live_mt5_dashboard_refresh")
        self.assertEqual(
            queue[0]["blockers"],
            ["live_dashboard_snapshot_stale", "mt5_terminal_process_missing"],
        )
        self.assertEqual(queue[0]["supportingProcessBlockers"], ["mt5_terminal_process_missing"])
        self.assertIn("主 MT5 terminal64 进程", queue[0]["actionZh"])
        self.assertIn("主 MT5 terminal64 进程", queue[0]["whyNowZh"])
        self.assertIn("liveSessionOk=False", queue[0]["evidenceSummaryZh"])
        self.assertEqual(
            queue[0]["evidenceSnapshot"]["processEvidenceBlockers"],
            ["mt5_terminal_process_missing"],
        )
        self.assertEqual(
            queue[0]["nextRequiredActionZh"],
            "先恢复主 MT5 terminal64 进程（优先: /Applications/MetaTrader 5/terminal64.exe）并恢复 dashboard freshness，再重建 tester gate。",
        )
        self.assertEqual(
            queue[0]["evidenceSnapshot"]["startupConfigPath"],
            "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
        )
        self.assertFalse(queue[0]["evidenceSnapshot"]["dashboardServerRunning"])
        self.assertEqual(queue[1]["id"], "separate_account_context_sync_review")
        self.assertIn("Config/accounts.dat", queue[1]["evidenceSummaryZh"])
        self.assertEqual(queue[2]["id"], "tester_lock_refresh")
        self.assertIn("authorization lock", queue[2]["whyNowZh"])
        self.assertIn("expiresAtIso=2026-06-03T13:49:59+00:00", queue[2]["evidenceSummaryZh"])
        self.assertEqual(queue[3]["id"], "run_forex_ab_tester_forward")
        self.assertNotIn("mt5_terminal_process_missing", queue[3]["blockers"])
        self.assertEqual(queue[3]["supportingProcessBlockers"], ["mt5_terminal_process_missing"])
        self.assertIn("A/B 主对照", queue[3]["whyNowZh"])
        self.assertIn("queueCount=1", queue[3]["evidenceSummaryZh"])
        self.assertEqual(
            queue[3]["nextRequiredActionZh"],
            "先恢复主 MT5 terminal64 进程（优先: /Applications/MetaTrader 5/terminal64.exe）并恢复 dashboard freshness，再重建 tester gate。",
        )
        self.assertEqual(
            queue[3]["evidenceSnapshot"]["startupConfigPath"],
            "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
        )
        self.assertIn("需恢复进程=mt5_terminal_process_missing", queue[3]["gateDiagnostics"]["summaryZh"])
        self.assertEqual(queue[3]["evidenceSnapshot"]["windowPhase"], "IN_WINDOW")
        self.assertEqual(queue[3]["evidenceSnapshot"]["queueCount"], 1)
        self.assertEqual(
            queue[3]["evidenceSnapshot"]["processEvidenceBlockers"],
            ["mt5_terminal_process_missing"],
        )
        self.assertNotIn("isolated_tester_forward_report_ready", queue[3]["blockers"])
        self.assertNotIn("champion_tester_run_gate_ready", queue[3]["blockers"])
        self.assertEqual(
            queue[3]["downstreamReleaseRequirementIds"],
            ["isolated_tester_forward_report_ready", "champion_tester_run_gate_ready"],
        )

    def test_build_action_queue_prefers_converged_near_live_variant_ladder_over_legacy_aliases(self) -> None:
        queue = _build_action_queue(
            selected_lane="btcCryptoCfd",
            selected_seed=None,
            selected_strategy="hfm_crypto_btc_near_live_middle_window_0003",
            prerequisites=[],
            run_gate_blockers=[],
            process_blockers=[],
            can_run_tester=False,
            lock_ready=False,
            target_reached=True,
            forward_request={},
            next_tester_window={},
            strategy_shortlist={
                "btcLaneReadiness": {"blockers": []},
                "btcTopStrategies": [
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "role": "stableAnchor",
                        "blockers": ["HFM_SHARPE_LT_MIN"],
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "role": "stabilityAlternative",
                        "blockers": ["HFM_TRADE_COUNT_LT_MIN"],
                    },
                    {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                        "role": "repairObservation",
                        "blockers": [],
                    },
                ],
                "btcLineupBoard": {
                    "stableAnchorStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "nearLiveChallengerStrategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                    "yieldFrontierStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "recommendedFocusedRetestOrder": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_middle_window_0021",
                        "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    ],
                    "nearLiveConvergedVariantStrategyIds": [
                        "hfm_crypto_btc_near_live_middle_window_0003",
                        "hfm_crypto_btc_near_live_middle_window_0021",
                        "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                    ],
                    "nearLiveConvergedVariantRows": [
                        {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003", "stopLossPriceMove": 325.0},
                        {"strategyId": "hfm_crypto_btc_near_live_middle_window_0021", "stopLossPriceMove": 300.0},
                        {"strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0001", "stopLossPriceMove": 312.5},
                    ],
                    "nearLiveConvergedVariantStopLossLadder": [325.0, 300.0, 312.5],
                    "nearLiveConvergedVariantSummaryZh": (
                        "当前 near-live 收敛簇前排变体: "
                        "hfm_crypto_btc_near_live_middle_window_0003(SL=325.0) -> "
                        "hfm_crypto_btc_near_live_middle_window_0021(SL=300.0) -> "
                        "hfm_crypto_btc_near_live_stoploss_ladder_0001(SL=312.5)。"
                    ),
                    "stableMiddleTradeoffFollowupBestTradeoff": {
                        "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    },
                    "stableMiddleTradeoffFollowupBestStrategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    "stableMiddleTradeoffFollowupOutcomeZh": "stable middle tradeoff repair line 改善了 bridge 线，但 middle_third 仍未真正修复；把它当作下一条折中观察线。",
                },
                "btcParameterClusters": {
                    "rows": [
                        {
                            "canonicalStrategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                            "aliasStrategyIds": ["hfm_crypto_btc_near_live_followup_0015"],
                            "memberStrategyIds": [
                                "hfm_crypto_btc_near_live_middle_window_0003",
                                "hfm_crypto_btc_near_live_middle_window_0021",
                                "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                            ],
                        },
                        {
                            "canonicalStrategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                            "aliasStrategyIds": ["hfm_crypto_btc_near_live_refinement_0002"],
                            "memberStrategyIds": [
                                "hfm_crypto_btc_near_live_middle_window_0021",
                                "hfm_crypto_btc_near_live_middle_window_0003",
                                "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                            ],
                            "recommendedResearchPriority": 1,
                            "recommendedResearchReasonZh": "稳定锚点与收益 frontier 已收敛到同一参数簇；下一轮优先围绕当前 next distinct contender 做 near-live 复验，避免继续重复已收敛的主锚点。",
                        },
                    ],
                },
            },
            preflight={},
            live_evidence_intake={},
            hfm_review={},
            run_gate={},
            account_context={},
        )
        optimizer_action = [row for row in queue if row["id"] == "rerun_btc_tp_sl_optimizer"][0]
        scanner_action = [row for row in queue if row["id"] == "rerun_btc_strategy_scanner"][0]
        self.assertEqual(
            optimizer_action["focusClusterAliasStrategyIds"],
            [
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_stoploss_ladder_0001",
            ],
        )
        self.assertIn("near_live_stoploss_ladder_0001", optimizer_action["focusClusterSummaryZh"])
        self.assertNotIn("near_live_followup_0015", optimizer_action["focusClusterSummaryZh"])
        self.assertEqual(
            optimizer_action["comparisonClusterCanonicalStrategyId"],
            "hfm_crypto_btc_near_live_middle_window_0021",
        )
        self.assertIn("当前 next distinct contender=hfm_crypto_btc_near_live_middle_window_0021", optimizer_action["comparisonClusterSummaryZh"])
        self.assertIn("near_live_stoploss_ladder_0001", optimizer_action["comparisonClusterSummaryZh"])
        self.assertNotIn("near_live_refinement_0002", optimizer_action["comparisonClusterSummaryZh"])
        self.assertEqual(
            scanner_action["focusClusterAliasStrategyIds"],
            [
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_near_live_stoploss_ladder_0001",
            ],
        )
        self.assertIn("当前 near-live 收敛簇前排变体", scanner_action["focusClusterSummaryZh"])

    def test_mt5_window_briefing_enters_final_30_min_mode(self) -> None:
        briefing = _mt5_window_briefing(
            {
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
                }
            },
            {
                "gateDiagnostics": {"minutesUntilStart": 24.6},
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [],
            },
        )
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
        briefing = _mt5_window_briefing(
            {
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
                }
            },
            {
                "gateDiagnostics": {"minutesUntilStart": 12.1},
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [],
            },
        )
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
        briefing = _mt5_window_briefing(
            {
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
                }
            },
            {
                "gateDiagnostics": {"minutesUntilStart": 4.8},
                "abCandidateIds": [
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                    "g0102-usdjpy-rsi-champion-tester-forward-v1",
                ],
                "variantCandidateIds": [],
            },
        )
        self.assertEqual(briefing["phase"], "PRE_WINDOW_FINAL_5_MIN")
        self.assertEqual(briefing["finalSprintCheckIds"], ["dashboard_fresh"])
        self.assertIn("最后 5 分钟只盯", briefing["summaryZh"])

    def test_next_hour_action_board_keeps_mt5_residual_clearance_visible_in_window(self) -> None:
        board = _next_hour_action_board(
            workstream_status={
                "researchWorkstream": {
                    "lane": "forexMt5",
                    "readinessChecklist": {
                        "rows": [
                            {"id": "dashboard_fresh", "ok": False, "dependencyCheckIds": []},
                            {"id": "live_pilot_mode", "ok": False, "dependencyCheckIds": ["dashboard_fresh"]},
                        ]
                    },
                },
                "releaseWorkstream": {
                    "lane": "forexMt5",
                    "gateDiagnostics": {
                        "nextWindowStartJstIso": "2026-06-08T20:10:00+09:00",
                    },
                    "windowBriefing": {
                        "phase": "IN_WINDOW",
                        "minutesUntilStart": 0.0,
                        "readinessNow": {"ratio": "1/7", "readyCount": 1, "totalCount": 7},
                        "expectedReadinessAfterWindowOpen": {"ratio": "1/7", "readyCount": 1, "totalCount": 7},
                        "windowOpenGainCount": 1,
                        "windowOpenGainRatio": 0.1429,
                        "windowOpenRealizedCheckIds": ["tester_window_open"],
                        "postWindowStillBlocked": True,
                        "residualAfterWindowOpenCheckIds": [
                            "dashboard_fresh",
                            "isolated_account_context_ready",
                            "tester_can_run_now",
                        ],
                        "residualAfterWindowOpenCount": 3,
                        "highestLeveragePostWindowCheckIds": [
                            "dashboard_fresh",
                            "isolated_account_context_ready",
                        ],
                        "postWindowPrimarySummaryZh": "开窗后第一优先仍是 dashboard_fresh, isolated_account_context_ready；已自动解除 tester_window_open。",
                        "windowOpenEffectZh": "窗口已打开，已实得 1 项通过，当前仍剩 3 项未闭环。",
                        "abCandidateIds": [
                            "g0093-usdjpy-rsi-champion-tester-forward-v1",
                            "g0102-usdjpy-rsi-champion-tester-forward-v1",
                        ],
                        "inWindowCheckIds": ["tester_can_run_now"],
                    },
                },
            },
            action_queue=[
                {
                    "lane": "forexMt5",
                    "id": "restore_live_mt5_dashboard_refresh",
                    "actionZh": "restore mt5",
                    "whyNowZh": "mt5 first",
                    "commands": [],
                }
            ],
        )
        self.assertEqual(board["releasePhase"], "IN_WINDOW")
        self.assertEqual(board["mt5PriorityCheckIds"], ["dashboard_fresh", "isolated_account_context_ready"])
        self.assertEqual(
            [step["actionId"] for step in board["steps"]],
            [
                "restore_live_mt5_dashboard_refresh",
                "mt5_in_window_residual_clearance",
                "mt5_in_window_ab_first",
            ],
        )
        self.assertEqual(board["actions"], board["steps"])
        self.assertIn("MT5 窗口已开", board["summaryZh"])
        self.assertEqual(board["steps"][0]["checkIds"], ["dashboard_fresh", "isolated_account_context_ready"])

    def test_resolve_candidate_pack_prefers_fresh_pack_when_selected_strategy_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            self._write_json(agent / "QuantGod_AceExecutionCandidatePack.json", {
                "liveUpgradeSelection": {
                    "selectedStrategy": {"seedId": "OLD"}
                }
            })
            with patch(
                "tools.ace_execution_candidate_pack.read_ace_execution_candidate_pack",
                return_value={
                    "liveUpgradeSelection": {
                        "selectedStrategy": {"seedId": "NEW", "strategyId": "fresh"}
                    }
                },
            ):
                resolved = _resolve_candidate_pack(runtime, write=False)
            self.assertEqual(resolved["liveUpgradeSelection"]["selectedStrategy"]["seedId"], "NEW")

    def test_resolve_candidate_pack_falls_back_to_saved_pack_when_refresh_lacks_selected_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            self._write_json(agent / "QuantGod_AceExecutionCandidatePack.json", {
                "liveUpgradeSelection": {
                    "selectedStrategy": {"seedId": "SAVED", "strategyId": "saved"}
                }
            })
            with patch(
                "tools.ace_execution_candidate_pack.read_ace_execution_candidate_pack",
                return_value={
                    "liveUpgradeSelection": {
                        "selectedStrategy": {}
                    }
                },
            ):
                resolved = _resolve_candidate_pack(runtime, write=False)
            self.assertEqual(resolved["liveUpgradeSelection"]["selectedStrategy"]["seedId"], "SAVED")

    def test_decision_next_action_why_appends_near_live_repair_outcome_for_btc_lane(self) -> None:
        why = _decision_next_action_why(
            action_queue=[{
                "lane": "btcCryptoCfd",
                "whyNowZh": "当前主要卡在 dashboard freshness 和执行模式字段。",
            }],
            priority_summary={
                "currentResearchNearLiveRepairOutcomeZh": "near-live stability 局部搜索（含 sample-balanced / sample-rich bridge 邻域）暂未推翻当前 sample-balanced challenger；继续把它作为第二候选。"
            },
        )
        self.assertIn("当前主要卡在 dashboard freshness 和执行模式字段。", why)
        self.assertIn("sample-balanced challenger", why)

    def test_action_plan_routes_demoted_rsi_to_forex_ab_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            self._write_json(agent / "QuantGod_AceExecutionCandidatePack.json", {
                "schema": "quantgod.ace_execution_candidate_pack.v1",
                "sourceArtifactSummaries": {
                    "btcStrategyScan": {"generatedAtIso": "2026-06-08T06:00:00Z"},
                    "tpSlOptimizer": {"generatedAtIso": "2026-06-08T06:00:00Z"},
                    "liveRuntimePreflightProbe": {"generatedAtIso": "2026-06-08T06:37:56Z"},
                },
                "liveUpgradeSelection": {
                    "status": "RSI_DEMOTED_FOREX_AB_READY",
                    "selectedLane": "forexMt5",
                    "selectedStrategy": {
                        "lane": "forexMt5",
                        "seedId": "GA-USDJPY-G0093-C0004",
                        "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                        "strategyFamily": "RSI_Reversal",
                        "contenderTieBreakRequired": True,
                    },
                    "excludedAceCandidates": [
                        {"lane": "live12_raw_rsi", "reason": "DEMOTE_RAW_RSI_FROM_ACE"}
                    ],
                    "upgradePrerequisites": [
                        "isolated_tester_forward_report_ready",
                        "champion_tester_run_gate_ready",
                        "separate_execution_release_lane_ready",
                    ],
                },
                "strategyShortlist": {
                    "btcLaneReadiness": {
                        "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                        "focusSymbol": "#BTCUSD",
                        "blockers": [
                            "MT5_DASHBOARD_SNAPSHOT_STALE",
                            "MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD",
                            "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING",
                        ],
                    },
                    "btcTopStrategies": [
                        {
                            "strategyId": "hfm_crypto_btc_tpsl_0302",
                            "role": "stableAnchor",
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        },
                        {
                            "strategyId": "hfm_crypto_btc_balanced_quality_repair_0028",
                            "role": "highYieldTradeoff",
                            "blockers": [],
                        },
                        {
                            "strategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                            "role": "sampleRichBridge",
                            "blockers": [],
                        },
                    ],
                    "btcParameterClusters": {
                        "status": "BTC_PARAMETER_CLUSTERS_READY",
                        "rows": [
                            {
                                "canonicalStrategyId": "hfm_crypto_btc_tpsl_0302",
                                "aliasStrategyIds": ["hfm_crypto_btc_stability_short_window_shadow_v1"],
                                "memberStrategyIds": [
                                    "hfm_crypto_btc_tpsl_0302",
                                    "hfm_crypto_btc_stability_short_window_shadow_v1",
                                ],
                                "recommendedResearchPriority": 3,
                                "recommendedResearchReasonZh": "现任稳健候选继续修 middle_third。",
                            },
                            {
                                "canonicalStrategyId": "hfm_crypto_btc_balanced_quality_repair_0028",
                                "aliasStrategyIds": [
                                    "hfm_crypto_btc_tpsl_4138",
                                    "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                                ],
                                "memberStrategyIds": [
                                    "hfm_crypto_btc_balanced_quality_repair_0028",
                                    "hfm_crypto_btc_tpsl_4138",
                                    "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                                ],
                                "recommendedResearchPriority": 1,
                                "recommendedResearchReasonZh": "高收益慢频候选优先补窗口样本。",
                            },
                            {
                                "canonicalStrategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                                "aliasStrategyIds": [],
                                "memberStrategyIds": ["hfm_crypto_btc_sample_rich_quality_0001"],
                                "recommendedResearchPriority": 2,
                                "recommendedResearchReasonZh": "样本丰富候选作为桥接修复方向。",
                            },
                        ],
                    },
                },
                "executionReadinessBoard": {
                    "status": "EXECUTION_READINESS_BOARD_READY",
                    "canProceedToSeparateReleaseLane": False,
                    "readyStrategyCountForSeparateReleaseLane": 0,
                    "closestResearchLaneNow": "btcCryptoCfd",
                    "selectedLaneForSeparateReleaseReview": "forexMt5",
                    "laneSnapshots": [
                        {
                            "lane": "forexMt5",
                            "focusStrategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                            "readinessChecklist": {
                                "status": "MT5_READINESS_CHECKLIST_READY",
                                "readyCount": 0,
                                "totalCount": 7,
                                "rows": [
                                    {"id": "live_session_fresh", "ok": False, "labelZh": "live session fresh"},
                                    {"id": "tester_window_open", "ok": False, "labelZh": "tester window open"},
                                ],
                            },
                        },
                        {
                            "lane": "btcCryptoCfd",
                            "focusStrategyId": "hfm_crypto_btc_tpsl_0302",
                            "readinessChecklist": {
                                "status": "BTC_READINESS_CHECKLIST_READY",
                                "readyCount": 1,
                                "totalCount": 9,
                                "rows": [
                                    {"id": "runtime_probe_fresh", "ok": False, "labelZh": "runtime probe fresh"},
                                    {"id": "permission_chain_healthy", "ok": True, "labelZh": "permission chain healthy"},
                                ],
                            },
                        },
                    ],
                    "nextActionsOverall": [
                        {
                            "id": "btc_runtime_preflight_refresh",
                            "lane": "btcCryptoCfd",
                            "actionZh": "先补 BTC runtime/data-plane 证据。",
                            "whyNowZh": "BTC 是当前唯一还能继续推进研究的 lane，但缺实时 dashboard/tick/spread 证据。",
                            "evidenceSummaryZh": "dashboardFresh=False ageSeconds=246750.956；当前 dashboard symbols=USDJPYc；#BTCUSD selectedRaw=False selectedEffective=False tick=False spread=False runtimeProbeAgeSeconds=246742.515。",
                            "evidenceSnapshot": {
                                "dashboardSymbolNames": ["USDJPYc"],
                                "symbolSelectedInDashboardOk": False,
                                "symbolSelectionEffectiveOk": False,
                                "targetSymbol": "#BTCUSD",
                            },
                        },
                        {
                            "id": "btc_stable_anchor_retest",
                            "lane": "btcCryptoCfd",
                            "actionZh": "围绕稳健默认继续修 middle_third。",
                            "whyNowZh": "稳健默认仍是离实盘评审最近的 BTC 候选，继续补分段质量比换冠军更值钱。",
                            "evidenceSummaryZh": "dashboardFresh=False ageSeconds=246750.956；当前 dashboard symbols=USDJPYc；#BTCUSD selectedRaw=False selectedEffective=False tick=False spread=False runtimeProbeAgeSeconds=246742.515。",
                            "evidenceSnapshot": {
                                "dashboardSymbolNames": ["USDJPYc"],
                                "symbolSelectedInDashboardOk": False,
                                "symbolSelectionEffectiveOk": False,
                                "targetSymbol": "#BTCUSD",
                            },
                        },
                        {
                            "id": "mt5_clear_tester_gate",
                            "lane": "forexMt5",
                            "actionZh": "清 MT5 tester gate。",
                            "whyNowZh": "MT5 候选本身已相对稳定，当前主要卡在 lock、dashboard freshness 和 tester window。",
                            "evidenceSummaryZh": "liveSessionOk=False window=daily_night start=2026-06-08T20:10:00+09:00 minutesUntilStart=302.4。",
                            "evidenceSnapshot": {
                                "nextTesterWindowLabel": "daily_night",
                                "minutesUntilStart": 302.4,
                            },
                        },
                    ],
                },
            })
            self._write_json(agent / "QuantGod_SimTargetExecutionReviewSummary.json", {
                "targetEvidence": {
                    "targetReached": True,
                    "combinedVerifiedUsdProfit": 72.0,
                    "combinedTargetStatus": "TARGET_REACHED",
                }
            })
            self._write_json(agent / "QuantGod_ChampionPromotionGate.json", {
                "status": "WAITING_ISOLATED_TESTER_FORWARD_REPORT"
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
                    "liveSession": {
                        "status": "ready",
                        "ok": True,
                        "openTradeCount": 0,
                        "marginInUse": 0,
                        "accountNumber": "186054398",
                        "server": "HFMarketsGlobal-Live12",
                    },
                },
                "nextTesterWindow": {
                    "startJstIso": "2026-06-05T20:10:00+09:00",
                    "endJstIso": "2026-06-05T23:30:00+09:00",
                },
                "decision": {"canRunIsolatedTester": False},
            })
            self._write_json(agent / "QuantGod_ChampionTesterForwardRequest.json", {
                "status": "CHAMPION_TESTER_FORWARD_REQUEST_READY",
                "selectedTasks": [
                    {
                        "candidateId": "g0093-usdjpy-rsi-champion-tester-forward-v1",
                        "label": "USDJPY G0093 RSI_Reversal champion tester/forward",
                        "configOnlyCommand": "python tools/run_param_lab.py --candidate-id g0093-usdjpy-rsi-champion-tester-forward-v1",
                        "guardedRunTerminalCommand": "python tools/run_param_lab.py --candidate-id g0093-usdjpy-rsi-champion-tester-forward-v1 --run-terminal",
                    },
                    {
                        "candidateId": "g0102-usdjpy-rsi-champion-tester-forward-v1",
                        "label": "USDJPY G0102 RSI_Reversal contender tester/forward",
                        "configOnlyCommand": "python tools/run_param_lab.py --candidate-id g0102-usdjpy-rsi-champion-tester-forward-v1",
                        "guardedRunTerminalCommand": "python tools/run_param_lab.py --candidate-id g0102-usdjpy-rsi-champion-tester-forward-v1 --run-terminal",
                    },
                ],
            })
            self._write_json(agent / "QuantGod_ChampionTesterLockDraft.json", {
                "status": "CHAMPION_TESTER_LOCK_DRAFT_READY",
                "decision": {"draftReadyForSeparateLockWriter": True},
            })
            self._write_json(agent / "QuantGod_BtcStrategyScanReport.json", {
                "generatedAtIso": "2026-06-08T06:50:00Z",
                "status": "BTC_SCAN_COMPLETE_NO_CLEAR_UPGRADE",
            })
            self._write_json(agent / "QuantGod_TpSlOptimizerReport.json", {
                "generatedAtIso": "2026-06-08T06:49:00Z",
                "status": "TPSL_OPTIMIZER_READY",
            })
            self._write_json(agent / "QuantGod_LiveRuntimePreflightProbe.json", {
                "generatedAtIso": "2026-06-08T06:37:56Z",
                "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                "approvedLanes": ["hfmCryptoCfd"],
                "dashboardSnapshot": {
                    "path": "/Users/bowen/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Files/QuantGod_Dashboard.json",
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
                },
                "probeResults": {
                    "symbolSelectedInDashboardOk": False,
                    "symbolRuntimeProbeOk": False,
                    "sidecarLiveTickOk": False,
                    "spreadProbeOk": False,
                },
                "laneRuntimeChecks": [
                    {
                        "lane": "HFM_CRYPTO_CFD",
                        "brokerSymbol": "#BTCUSD",
                        "symbolPresentInRuntimeProbe": True,
                        "runtimeProbeSource": "/Users/bowen/Library/Application Support/net.metaquotes.wine.metatrader5-live16/drive_c/Program Files/MetaTrader 5/MQL5/Files/QuantGod_HFMCryptoRuntimeProbe.json",
                        "runtimeProbeFresh": False,
                        "runtimeProbeAgeSeconds": 246742.515,
                        "symbolPresentInSnapshot": False,
                        "symbolPresentInNames": False,
                        "spreadFieldPresent": False,
                    }
                ],
                "blockers": [
                    {"code": "MT5_DASHBOARD_SNAPSHOT_STALE"},
                    {
                        "code": "MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD",
                        "reasonZh": "HFM specs 已证明 broker symbol 存在，但当前 MT5 dashboard/watchlist 尚未选中该 symbol 并输出实时 tick。",
                        "value": "#BTCUSD",
                    },
                    {
                        "code": "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING",
                        "reasonZh": "当前 MT5 dashboard/runtime probe 尚未输出该 symbol 的实时 bid/ask 或 spread，无法做价差预检。",
                        "value": "#BTCUSD",
                    },
                ],
                "nextRequiredActionZh": "先补 BTC runtime preflight 证据。",
            })
            self._write_json(agent / "QuantGod_LiveEvidenceIntake.json", {
                "generatedAtIso": "2026-06-08T06:38:15Z",
                "status": "HFM_REVIEW_INPUTS_PRESENT",
                "dashboardFresh": False,
                "tradeStatus": "SHADOW",
                "readOnlyMode": True,
                "executionEnabled": False,
                "tradeAllowed": False,
                "tradePermissionBlocker": "READ_ONLY_MODE",
                "fileInputSummary": {
                    "presentInputCount": 2,
                    "missingChecklistCount": 1,
                },
                "readOnlyReviewCommands": [
                    {
                        "id": "refresh_evidence_intake",
                        "whenZh": "每次补证据后刷新本面板。",
                        "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
                    },
                    {
                        "id": "run_hfm_post_upgrade_controller",
                        "whenZh": "人工升级后反复跑这一条。",
                        "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime post-upgrade-controller --write",
                    },
                    {
                        "id": "verify_mt5_ea_post_upgrade",
                        "whenZh": "人工升级后确认 specs 已输出。",
                        "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime mt5-post-upgrade-verify --write",
                    },
                    {
                        "id": "build_mt5_ea_upgrade_bundle",
                        "whenZh": "如果安装目录 EA 版本偏旧，生成人工升级包。",
                        "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime mt5-upgrade-bundle --write",
                    },
                ],
            })
            hfm = runtime / "hfm_crypto"
            self._write_json(hfm / "QuantGod_HFMCryptoPostUpgradeController.json", {
                "status": "HFM_CRYPTO_POST_UPGRADE_REVIEW_AUTOMATED",
                "readyForHfmContractSpecReview": True,
                "executionSpecReviewReady": True,
            })
            self._write_json(hfm / "QuantGod_HFMCryptoMt5PostUpgradeVerify.json", {
                "status": "HFM_CRYPTO_MT5_POST_UPGRADE_VERIFIED",
            })
            self._write_json(hfm / "QuantGod_HFMCryptoMt5ExporterUpgradeBundle.json", {
                "status": "MT5_EXPORTER_ALREADY_AVAILABLE",
            })
            self._write_json(runtime / "QuantGod_IsolatedTesterAccountContextStatus.json", {
                "ready": False,
                "mode": "PREFLIGHT_ONLY_NO_SENSITIVE_COPY",
                "missingTarget": ["Config/accounts.dat"],
                "sensitiveAccountContextSyncRequired": True,
                "separateSyncReview": {
                    "status": "SEPARATE_SENSITIVE_ACCOUNT_CONTEXT_SYNC_REQUIRED",
                    "requiresSeparateControlledSync": True,
                    "writesMt5OrderRequest": False,
                },
            })

            with patch("tools.ace_upgrade_action_plan._process_evidence", return_value={
                "status": "PROCESS_SCAN_READY",
                "scanSupported": True,
                "mainMt5TerminalRunning": False,
                "isolatedTesterTerminalRunning": False,
                "dashboardServerRunning": True,
                "dailyAutopilotRunning": False,
                "liveExecutionFeedbackRunning": False,
                "blockers": ["mt5_terminal_process_missing"],
                "nextActionZh": "未发现主 MT5 terminal64 进程；live dashboard 可能不会继续刷新。",
                "launchesTerminal": False,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            }), patch(
                "tools.ace_upgrade_action_plan._utc_now",
                return_value=datetime(2026, 6, 5, 10, 35, tzinfo=timezone.utc),
            ):
                report = build_ace_upgrade_action_plan(runtime, write=True)

            self.assertEqual(report["schema"], "quantgod.ace_upgrade_action_plan.v1")
            self.assertEqual(report["status"], "ACE_UPGRADE_WAITING_TESTER_ENVIRONMENT")
            self.assertTrue(report["targetEvidence"]["targetReached"])
            self.assertEqual(report["selectedUpgrade"]["seedId"], "GA-USDJPY-G0093-C0004")
            self.assertEqual(report["selectedUpgrade"]["selectedLane"], "forexMt5")
            self.assertEqual(
                report["selectedUpgrade"]["laneSelections"]["forexMt5"]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["selectedUpgrade"]["laneSelections"]["btcCryptoCfd"]["strategyId"],
                "hfm_crypto_btc_tpsl_0302",
            )
            self.assertEqual(
                report["selectedUpgrade"]["excludedAceCandidates"][0]["reason"],
                "DEMOTE_RAW_RSI_FROM_ACE",
            )
            self.assertIn("outside_strategy_tester_window", report["testerEnvironment"]["runGateBlockers"])
            action_ids = [row["id"] for row in report["actionQueue"]]
            self.assertIn("wait_for_tester_window", action_ids)
            self.assertIn("restore_live_mt5_dashboard_refresh", action_ids)
            self.assertIn("separate_account_context_sync_review", action_ids)
            self.assertIn("run_forex_ab_tester_forward", action_ids)
            self.assertIn("refresh_btc_runtime_preflight_inputs", action_ids)
            self.assertIn("rerun_btc_tp_sl_optimizer", action_ids)
            self.assertIn("rerun_btc_strategy_scanner", action_ids)
            self.assertEqual(report["prioritySummary"]["status"], "PRIORITY_SUMMARY_READY")
            self.assertEqual(report["workstreamStatus"]["status"], "WORKSTREAM_STATUS_READY")
            self.assertEqual(report["operatorCommandDeck"]["status"], "OPERATOR_COMMAND_DECK_READY")
            self.assertEqual(report["packSourceFreshnessDiagnostics"]["status"], "PACK_SOURCE_FRESHNESS_READY")
            self.assertFalse(report["packSourceFreshnessDiagnostics"]["packSnapshotUpToDate"])
            self.assertEqual(report["packSourceFreshnessDiagnostics"]["staleCount"], 2)
            comparisons_by_id = {
                row["id"]: row
                for row in report["packSourceFreshnessDiagnostics"]["comparisons"]
            }
            self.assertIn("btcStrategyScan", comparisons_by_id)
            self.assertTrue(comparisons_by_id["btcStrategyScan"]["packSnapshotStale"])
            self.assertFalse(report["decision"]["packSnapshotUpToDate"])
            self.assertEqual(report["operatorCommandDeck"]["currentWorkstreamLane"], "btcCryptoCfd")
            self.assertEqual(report["operatorCommandDeck"]["stepCount"], 3)
            self.assertGreaterEqual(report["operatorCommandDeck"]["flatCommandCount"], 6)
            self.assertEqual(
                report["operatorCommandDeck"]["steps"][0]["actionId"],
                "refresh_btc_runtime_preflight_inputs",
            )
            self.assertEqual(
                report["operatorCommandDeck"]["steps"][0]["whyNowZh"],
                "BTC 是当前唯一还能继续推进研究的 lane，但缺实时 dashboard/tick/spread 证据。",
            )
            self.assertEqual(
                report["operatorCommandDeck"]["steps"][0]["evidenceSnapshot"]["dashboardSymbolNames"],
                ["USDJPYc"],
            )
            self.assertEqual(
                report["operatorCommandDeck"]["steps"][0]["nextRequiredActionZh"],
                "先补 BTC runtime preflight 证据。",
            )
            self.assertEqual(
                report["operatorCommandDeck"]["steps"][0]["refreshOutcome"]["status"],
                "REFRESH_ATTEMPTED_RUNTIME_STILL_STALE",
            )
            self.assertTrue(
                report["operatorCommandDeck"]["steps"][0]["refreshOutcome"]["externalRuntimeInterventionRequired"]
            )
            self.assertEqual(
                report["operatorCommandDeck"]["steps"][0]["refreshOutcome"]["sourceAlignmentStatus"],
                "MISMATCHED_MT5_INSTANCE",
            )
            self.assertEqual(
                report["operatorCommandDeck"]["steps"][0]["commands"][0]["conditionStatus"],
                "REQUIRED_NOW",
            )
            self.assertTrue(report["operatorCommandDeck"]["steps"][0]["commands"][0]["neededNow"])
            self.assertEqual(
                report["operatorCommandDeck"]["steps"][0]["commands"][3]["conditionStatus"],
                "SKIP_UNLESS_EXPORTER_MISSING",
            )
            self.assertFalse(report["operatorCommandDeck"]["steps"][0]["commands"][3]["neededNow"])
            self.assertEqual(
                report["operatorCommandDeck"]["flatCommandQueue"][0]["id"],
                "refresh_evidence_intake",
            )
            self.assertEqual(
                report["operatorCommandDeck"]["flatCommandQueue"][0]["command"],
                "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
            )
            self.assertEqual(
                report["operatorCommandDeck"]["flatCommandQueue"][0]["stepActionZh"],
                "先补 BTC runtime/data-plane 证据，确认 #BTCUSD 已在 dashboard/watchlist 输出实时 tick/spread。",
            )
            self.assertIn(
                "#BTCUSD selectedRaw=False selectedEffective=False",
                report["operatorCommandDeck"]["flatCommandQueue"][0]["stepEvidenceSummaryZh"],
            )
            self.assertEqual(
                report["operatorCommandDeck"]["flatCommandQueue"][0]["conditionStatus"],
                "REQUIRED_NOW",
            )
            self.assertTrue(report["operatorCommandDeck"]["flatCommandQueue"][0]["neededNow"])
            self.assertEqual(
                report["operatorCommandDeck"]["flatCommandQueue"][3]["conditionStatus"],
                "SKIP_UNLESS_EXPORTER_MISSING",
            )
            self.assertFalse(report["operatorCommandDeck"]["flatCommandQueue"][3]["neededNow"])
            self.assertEqual(
                report["operatorCommandDeck"]["requiredNowCommandIds"],
                ["refresh_evidence_intake"],
            )
            self.assertEqual(report["operatorCommandDeck"]["requiredNowFlatCommandCount"], 1)
            self.assertGreaterEqual(report["operatorCommandDeck"]["conditionalFlatCommandCount"], 5)
            self.assertEqual(
                report["operatorCommandDeck"]["requiredNowFlatCommandQueue"][0]["id"],
                "refresh_evidence_intake",
            )
            self.assertEqual(
                report["operatorCommandDeck"]["conditionalFlatCommandQueue"][0]["id"],
                "run_hfm_post_upgrade_controller",
            )
            self.assertEqual(
                report["workstreamStatus"]["overallMode"],
                "DUAL_TRACK_RESEARCH_ACTIVE_RELEASE_WAITING",
            )
            self.assertEqual(
                report["workstreamStatus"]["closureQueue"][0]["lane"],
                "btcCryptoCfd",
            )
            self.assertEqual(
                report["workstreamStatus"]["closureQueue"][0]["checkId"],
                "runtime_probe_fresh",
            )
            self.assertEqual(
                report["workstreamStatus"]["primaryClosureQueue"][0]["checkId"],
                "runtime_probe_fresh",
            )
            self.assertIn(
                "优先 lane=btcCryptoCfd",
                report["workstreamStatus"]["closureSummaryZh"],
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["lane"],
                "btcCryptoCfd",
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["recommendedActionIds"],
                [
                    "refresh_btc_runtime_preflight_inputs",
                    "rerun_btc_tp_sl_optimizer",
                    "rerun_btc_strategy_scanner",
                ],
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["readinessChecklist"]["readyCount"],
                1,
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["gateDiagnostics"]["externalRefreshBlockers"],
                ["MT5_DASHBOARD_SNAPSHOT_STALE"],
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["gateDiagnostics"]["dataPlaneBlockers"],
                ["MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD", "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING"],
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["gateDiagnostics"]["executionModeBlockers"],
                [],
            )
            self.assertEqual(
                report["workstreamStatus"]["releaseWorkstream"]["lane"],
                "forexMt5",
            )
            self.assertEqual(
                report["workstreamStatus"]["releaseWorkstream"]["status"],
                "RELEASE_WAITING_GATE",
            )
            self.assertEqual(
                report["workstreamStatus"]["releaseWorkstream"]["queueCount"],
                2,
            )
            self.assertEqual(
                report["workstreamStatus"]["releaseWorkstream"]["readinessChecklist"]["readyCount"],
                0,
            )
            self.assertEqual(
                report["workstreamStatus"]["releaseWorkstream"]["gateDiagnostics"]["autoClearAtWindowBlockers"],
                ["outside_strategy_tester_window"],
            )
            self.assertEqual(
                report["workstreamStatus"]["releaseWorkstream"]["gateDiagnostics"]["manualRefreshBlockers"],
                ["authorization_lock_expired", "live_dashboard_snapshot_stale"],
            )
            self.assertEqual(
                report["workstreamStatus"]["releaseWorkstream"]["gateDiagnostics"]["manualSensitiveBlockers"],
                [
                    "isolated_tester_account_context_not_ready",
                    "sensitive_account_context_sync_required",
                ],
            )
            self.assertIn(
                "A/B 主对照=g0093-usdjpy-rsi-champion-tester-forward-v1, g0102-usdjpy-rsi-champion-tester-forward-v1",
                report["workstreamStatus"]["releaseWorkstream"]["queueSummaryZh"],
            )
            self.assertEqual(report["nextHourActionBoard"]["status"], "NEXT_HOUR_ACTION_BOARD_READY")
            self.assertEqual(report["nextHourActionBoard"]["releasePhase"], "PRE_WINDOW_FINAL_HOUR")
            self.assertEqual(
                report["nextHourActionBoard"]["minutesUntilWindow"],
                report["workstreamStatus"]["releaseWorkstream"]["windowBriefing"]["minutesUntilStart"],
            )
            self.assertEqual(
                report["nextHourActionBoard"]["nextWindowStartJstIso"],
                report["workstreamStatus"]["releaseWorkstream"]["gateDiagnostics"]["nextWindowStartJstIso"],
            )
            self.assertEqual(report["nextHourActionBoard"]["readinessNow"]["ratio"], "0/7")
            self.assertEqual(
                report["nextHourActionBoard"]["expectedReadinessAfterWindowOpen"]["ratio"],
                "1/7",
            )
            self.assertEqual(report["nextHourActionBoard"]["windowOpenGainCount"], 1)
            self.assertTrue(report["nextHourActionBoard"]["postWindowStillBlocked"])
            self.assertEqual(
                report["nextHourActionBoard"]["btcPriorityCheckIds"],
                ["runtime_probe_fresh"],
            )
            self.assertEqual(
                report["nextHourActionBoard"]["mt5PriorityCheckIds"],
                ["live_session_fresh"],
            )
            self.assertEqual(
                report["nextHourActionBoard"]["residualAfterWindowOpenCheckIds"],
                report["workstreamStatus"]["releaseWorkstream"]["windowBriefing"]["residualAfterWindowOpenCheckIds"],
            )
            self.assertEqual(
                report["nextHourActionBoard"]["residualAfterWindowOpenCount"],
                len(report["nextHourActionBoard"]["residualAfterWindowOpenCheckIds"]),
            )
            self.assertIn("仍剩", report["nextHourActionBoard"]["windowOpenEffectZh"])
            self.assertEqual(
                [step["actionId"] for step in report["nextHourActionBoard"]["steps"]],
                [
                    "refresh_btc_runtime_preflight_inputs",
                    "mt5_pre_window_clearance",
                    "mt5_in_window_ab_first",
                ],
            )
            self.assertIn("G0093/G0102 A/B", report["decision"]["nextHourSummaryZh"])
            self.assertEqual(report["prioritySummary"]["closestResearchLaneNow"], "btcCryptoCfd")
            self.assertEqual(report["prioritySummary"]["currentResearchFocusLane"], "btcCryptoCfd")
            self.assertEqual(
                report["prioritySummary"]["currentResearchFocusStrategyId"],
                "hfm_crypto_btc_tpsl_0302",
            )
            self.assertEqual(
                report["prioritySummary"]["currentResearchFocusClusterCanonicalStrategyId"],
                "hfm_crypto_btc_tpsl_0302",
            )
            self.assertEqual(
                report["prioritySummary"]["currentResearchFocusClusterAliasStrategyIds"],
                ["hfm_crypto_btc_stability_short_window_shadow_v1"],
            )
            self.assertEqual(
                report["prioritySummary"]["currentResearchYieldFrontierStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertEqual(
                report["prioritySummary"]["selectedLaneForSeparateReleaseReview"],
                "forexMt5",
            )
            self.assertEqual(
                report["prioritySummary"]["selectedReleaseAbContenderSeedId"],
                "GA-USDJPY-G0102-C0004",
            )
            self.assertTrue(report["prioritySummary"]["laneConflictDetected"])
            self.assertEqual(
                report["prioritySummary"]["currentLaneActionQueueIds"][0],
                "refresh_btc_runtime_preflight_inputs",
            )
            self.assertEqual(
                report["prioritySummary"]["recommendedActionQueueIds"][:3],
                [
                    "refresh_btc_runtime_preflight_inputs",
                    "rerun_btc_tp_sl_optimizer",
                    "rerun_btc_strategy_scanner",
                ],
            )
            tester_action = [row for row in report["actionQueue"] if row["id"] == "run_forex_ab_tester_forward"][0]
            self.assertEqual(tester_action["status"], "GATED")
            self.assertEqual(tester_action["lane"], "forexMt5")
            self.assertNotIn("mt5_terminal_process_missing", tester_action["blockers"])
            self.assertEqual(
                tester_action["supportingProcessBlockers"],
                ["mt5_terminal_process_missing"],
            )
            self.assertIn("sensitive_account_context_sync_required", tester_action["blockers"])
            self.assertEqual(tester_action["queueCount"], 2)
            self.assertEqual(
                tester_action["gateDiagnostics"]["autoClearAtWindowBlockers"],
                ["outside_strategy_tester_window"],
            )
            self.assertEqual(
                tester_action["gateDiagnostics"]["manualRefreshBlockers"],
                ["authorization_lock_expired", "live_dashboard_snapshot_stale"],
            )
            self.assertEqual(
                tester_action["gateDiagnostics"]["manualSensitiveBlockers"],
                [
                    "isolated_tester_account_context_not_ready",
                    "sensitive_account_context_sync_required",
                ],
            )
            self.assertEqual(
                tester_action["abCandidateIds"],
                ["g0093-usdjpy-rsi-champion-tester-forward-v1", "g0102-usdjpy-rsi-champion-tester-forward-v1"],
            )
            self.assertEqual(
                tester_action["evidenceSnapshot"]["processEvidenceBlockers"],
                ["mt5_terminal_process_missing"],
            )
            self.assertGreaterEqual(len(tester_action["commands"]), 2)
            self.assertEqual(
                tester_action["commands"][0]["id"],
                "g0093-usdjpy-rsi-champion-tester-forward-v1_config_only",
            )
            self.assertEqual(report["actionQueue"][0]["id"], "refresh_btc_runtime_preflight_inputs")
            self.assertEqual(report["actionQueue"][0]["recommendedOrder"], 1)
            self.assertEqual(report["actionQueue"][0]["priorityBucket"], "current_research_focus")
            self.assertTrue(report["actionQueue"][0]["recommendedNow"])
            self.assertEqual(
                report["actionQueue"][0]["focusClusterCanonicalStrategyId"],
                "hfm_crypto_btc_tpsl_0302",
            )
            self.assertEqual(report["actionQueue"][1]["id"], "rerun_btc_tp_sl_optimizer")
            self.assertEqual(
                report["actionQueue"][1]["comparisonClusterCanonicalStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertEqual(report["actionQueue"][2]["id"], "rerun_btc_strategy_scanner")
            self.assertEqual(
                report["actionQueue"][2]["focusClusterCanonicalStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertEqual(
                report["actionQueue"][2]["comparisonClusterCanonicalStrategyId"],
                "hfm_crypto_btc_sample_rich_quality_0001",
            )
            btc_preflight_action = [row for row in report["actionQueue"] if row["id"] == "refresh_btc_runtime_preflight_inputs"][0]
            self.assertEqual(btc_preflight_action["status"], "READY")
            self.assertEqual(btc_preflight_action["lane"], "btcCryptoCfd")
            self.assertIn("MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING", btc_preflight_action["blockers"])
            self.assertGreaterEqual(len(btc_preflight_action["commands"]), 3)
            self.assertEqual(
                btc_preflight_action["blockerDetails"][0]["code"],
                "MT5_DASHBOARD_SNAPSHOT_STALE",
            )
            self.assertEqual(
                btc_preflight_action["blockerDetails"][1]["reasonZh"],
                "HFM specs 已证明 broker symbol 存在，但当前 MT5 dashboard/watchlist 尚未选中该 symbol 并输出实时 tick。",
            )
            self.assertEqual(
                btc_preflight_action["evidenceSnapshot"]["targetSymbol"],
                "#BTCUSD",
            )
            self.assertTrue(btc_preflight_action["evidenceSnapshot"]["permissionChainHealthy"])
            self.assertEqual(
                btc_preflight_action["directExecutionBlockerCode"],
                "READ_ONLY_MODE",
            )
            self.assertEqual(
                btc_preflight_action["gateDiagnostics"]["externalRefreshBlockers"],
                ["MT5_DASHBOARD_SNAPSHOT_STALE"],
            )
            self.assertEqual(
                btc_preflight_action["gateDiagnostics"]["dataPlaneBlockers"],
                ["MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD", "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING"],
            )
            self.assertEqual(
                btc_preflight_action["gateDiagnostics"]["executionModeBlockers"],
                [],
            )
            self.assertEqual(
                btc_preflight_action["evidenceSnapshot"]["dashboardInstance"],
                "main",
            )
            self.assertEqual(
                btc_preflight_action["evidenceSnapshot"]["runtimeProbeInstance"],
                "live16",
            )
            self.assertEqual(
                btc_preflight_action["evidenceSnapshot"]["sourceAlignmentStatus"],
                "MISMATCHED_MT5_INSTANCE",
            )
            self.assertFalse(btc_preflight_action["evidenceSnapshot"]["dashboardFresh"])
            self.assertEqual(
                btc_preflight_action["evidenceSnapshot"]["dashboardSymbolNames"],
                ["USDJPYc"],
            )
            self.assertFalse(
                btc_preflight_action["evidenceSnapshot"]["symbolSelectedInDashboardOk"]
            )
            self.assertFalse(
                btc_preflight_action["evidenceSnapshot"]["symbolSelectionEffectiveOk"]
            )
            self.assertFalse(btc_preflight_action["evidenceSnapshot"]["spreadProbeOk"])
            self.assertEqual(
                btc_preflight_action["nextRequiredActionZh"],
                "先补 BTC runtime preflight 证据。",
            )
            btc_optimizer_action = [row for row in report["actionQueue"] if row["id"] == "rerun_btc_tp_sl_optimizer"][0]
            self.assertIn("hfm_crypto_btc_tpsl_0302", btc_optimizer_action["actionZh"])
            self.assertIn("参数簇主 ID=hfm_crypto_btc_tpsl_0302", btc_optimizer_action["actionZh"])
            self.assertIn("高收益慢频候选优先补窗口样本", btc_optimizer_action["whyNowZh"])
            self.assertIn(
                "稳定主线=hfm_crypto_btc_tpsl_0302；对照 challenger=hfm_crypto_btc_balanced_quality_repair_0028",
                btc_optimizer_action["evidenceSummaryZh"],
            )
            self.assertEqual(
                btc_optimizer_action["evidenceSnapshot"]["stableAnchorStrategyId"],
                "hfm_crypto_btc_tpsl_0302",
            )
            self.assertEqual(
                btc_optimizer_action["evidenceSnapshot"]["challengerStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertNotIn("dashboard_fresh", btc_optimizer_action["whyNowZh"])
            self.assertEqual(
                btc_optimizer_action["comparisonClusterAliasStrategyIds"],
                ["hfm_crypto_btc_tpsl_4138", "hfm_crypto_btc_yield_balanced_both_shadow_v1"],
            )
            self.assertEqual(
                btc_optimizer_action["commands"][0]["command"],
                "python3 tools/run_tp_sl_optimizer.py --runtime-dir runtime build",
            )
            process_evidence = report["testerEnvironment"]["processEvidence"]
            self.assertIn(process_evidence["status"], ("PROCESS_SCAN_READY", "PROCESS_SCAN_UNAVAILABLE"))
            self.assertFalse(process_evidence["launchesTerminal"])
            self.assertFalse(process_evidence["brokerCallsMade"])
            self.assertFalse(process_evidence.get("orderSendAllowed", False))
            self.assertEqual(report["decision"]["currentResearchFocusLane"], "btcCryptoCfd")
            self.assertEqual(
                report["decision"]["currentResearchFocusStrategyId"],
                "hfm_crypto_btc_tpsl_0302",
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["focusClusterCanonicalStrategyId"],
                "hfm_crypto_btc_tpsl_0302",
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["focusClusterAliasStrategyIds"],
                ["hfm_crypto_btc_stability_short_window_shadow_v1"],
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["comparisonClusterCanonicalStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["comparisonClusterAliasStrategyIds"],
                ["hfm_crypto_btc_tpsl_4138", "hfm_crypto_btc_yield_balanced_both_shadow_v1"],
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["yieldFrontierStrategyId"],
                "hfm_crypto_btc_balanced_quality_repair_0028",
            )
            self.assertIn(
                "nearLiveRepairBestStrategyId",
                report["workstreamStatus"]["researchWorkstream"],
            )
            self.assertIn(
                "nearLiveRepairImprovesBaseline",
                report["workstreamStatus"]["researchWorkstream"],
            )
            self.assertIn(
                "nearLiveRepairOutcomeZh",
                report["workstreamStatus"]["researchWorkstream"],
            )
            self.assertIn(
                "nearLiveFollowupBestStrategyId",
                report["workstreamStatus"]["researchWorkstream"],
            )
            self.assertIn(
                "nearLiveFollowupImprovesRepair",
                report["workstreamStatus"]["researchWorkstream"],
            )
            self.assertIn(
                "nearLiveFollowupOutcomeZh",
                report["workstreamStatus"]["researchWorkstream"],
            )
            self.assertIn(
                "稳健锚点",
                report["workstreamStatus"]["researchWorkstream"]["duelSummaryZh"],
            )
            self.assertEqual(
                report["workstreamStatus"]["releaseWorkstream"]["abContenderSeedId"],
                "GA-USDJPY-G0102-C0004",
            )
            self.assertIn(
                "G0093/G0102",
                report["workstreamStatus"]["releaseWorkstream"]["abSummaryZh"],
            )
            self.assertEqual(report["decision"]["selectedLaneForSeparateReleaseReview"], "forexMt5")
            self.assertFalse(report["decision"]["canProceedToSeparateReleaseLane"])
            self.assertEqual(
                report["decision"]["overallMode"],
                "DUAL_TRACK_RESEARCH_ACTIVE_RELEASE_WAITING",
            )
            self.assertEqual(
                report["decision"]["recommendedCommandIds"][:3],
                [
                    "refresh_evidence_intake",
                    "run_hfm_post_upgrade_controller",
                    "verify_mt5_ea_post_upgrade",
                ],
            )
            self.assertEqual(
                report["decision"]["nextActionZh"],
                "先补 BTC runtime/data-plane 证据，确认 #BTCUSD 已在 dashboard/watchlist 输出实时 tick/spread。",
            )
            self.assertEqual(
                report["decision"]["nextActionWhyZh"],
                "BTC 是当前唯一还能继续推进研究的 lane，但缺实时 dashboard/tick/spread 证据。",
            )
            self.assertIn(
                "dashboard symbols=USDJPYc",
                report["decision"]["nextActionEvidenceSummaryZh"],
            )
            self.assertIn(
                "tradePermissionBlocker=READ_ONLY_MODE",
                report["decision"]["nextActionEvidenceSummaryZh"],
            )
            self.assertTrue(report["decision"]["nextActionPermissionChainHealthy"])
            self.assertEqual(
                report["decision"]["nextActionDirectExecutionBlockerCode"],
                "READ_ONLY_MODE",
            )
            self.assertIn(
                "livePilotMode=False",
                report["decision"]["nextActionEvidenceSummaryZh"],
            )
            self.assertEqual(
                report["decision"]["nextActionRefreshOutcome"]["status"],
                "REFRESH_ATTEMPTED_RUNTIME_STILL_STALE",
            )
            self.assertTrue(
                report["decision"]["nextActionRefreshOutcome"]["externalRuntimeInterventionRequired"]
            )
            self.assertEqual(
                report["decision"]["nextActionRefreshOutcome"]["sourceAlignmentStatus"],
                "MISMATCHED_MT5_INSTANCE",
            )
            self.assertEqual(
                report["decision"]["requiredNowCommandIds"],
                ["refresh_evidence_intake"],
            )
            self.assertFalse(report["decision"]["canRunTesterHere"])
            self.assertFalse(report["decision"]["copiesAccountContext"])
            self.assertFalse(report["decision"]["writesTesterLock"])
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])
            self.assertFalse(report["safety"]["writesLivePreset"])
            self.assertEqual(
                report["sourceArtifactSummaries"]["aceExecutionCandidatePack"]["closestResearchLaneNow"],
                "btcCryptoCfd",
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["championTesterRunGate"]["nextTesterWindowStartJstIso"],
                "2026-06-05T20:10:00+09:00",
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["liveRuntimePreflightProbe"]["dashboardSymbolNames"],
                ["USDJPYc"],
            )
            self.assertEqual(
                report["sourceArtifactSummaries"]["liveEvidenceIntake"]["presentInputCount"],
                2,
            )
            self.assertIn(
                "runGate@",
                report["sourceArtifactSummaryZh"],
            )
            self.assertIn(
                "preflight@2026-06-08T06:37:56Z",
                report["sourceArtifactSummaryZh"],
            )
            self.assertIn(
                "tradeBlocker=READ_ONLY_MODE",
                report["sourceArtifactSummaryZh"],
            )
            saved = read_ace_upgrade_action_plan(runtime)
            self.assertEqual(saved["selectedUpgrade"]["seedId"], "GA-USDJPY-G0093-C0004")

            stale_plan = json.loads((agent / "QuantGod_AceUpgradeActionPlan.json").read_text(encoding="utf-8"))
            stale_plan["sourceArtifactSummaries"]["aceExecutionCandidatePack"]["generatedAtIso"] = "2026-06-08T05:00:00Z"
            (agent / "QuantGod_AceUpgradeActionPlan.json").write_text(
                json.dumps(stale_plan),
                encoding="utf-8",
            )
            refreshed_saved = read_ace_upgrade_action_plan(runtime)
            self.assertNotEqual(
                refreshed_saved["sourceArtifactSummaries"]["aceExecutionCandidatePack"]["generatedAtIso"],
                "2026-06-08T05:00:00Z",
            )

    def test_action_plan_switches_btc_focus_once_tick_spread_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            self._write_json(agent / "QuantGod_AceExecutionCandidatePack.json", {
                "schema": "quantgod.ace_execution_candidate_pack.v1",
                "liveUpgradeSelection": {
                    "status": "RSI_DEMOTED_FOREX_AB_READY",
                    "selectedLane": "forexMt5",
                    "selectedStrategy": {
                        "lane": "forexMt5",
                        "seedId": "GA-USDJPY-G0093-C0004",
                        "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                        "strategyFamily": "RSI_Reversal",
                        "contenderTieBreakRequired": True,
                    },
                    "upgradePrerequisites": [
                        "isolated_tester_forward_report_ready",
                        "champion_tester_run_gate_ready",
                        "separate_execution_release_lane_ready",
                    ],
                },
                "strategyShortlist": {
                    "btcLaneReadiness": {
                        "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                        "focusSymbol": "#BTCUSD",
                        "blockers": [
                            "MT5_DASHBOARD_SNAPSHOT_STALE",
                            "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
                            "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                            "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
                            "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
                        ],
                    },
                    "btcTopStrategies": [
                        {
                            "strategyId": "hfm_crypto_btc_tpsl_0302",
                            "role": "stableAnchor",
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        },
                        {
                            "strategyId": "hfm_crypto_btc_balanced_quality_repair_0028",
                            "role": "highYieldTradeoff",
                            "blockers": [],
                        },
                        {
                            "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                            "role": "stableAlternative",
                            "blockers": [],
                        },
                    ],
                    "btcParameterClusters": {
                        "status": "BTC_PARAMETER_CLUSTERS_READY",
                        "rows": [
                            {
                                "canonicalStrategyId": "hfm_crypto_btc_tpsl_0302",
                                "aliasStrategyIds": ["hfm_crypto_btc_stability_short_window_shadow_v1"],
                                "memberStrategyIds": [
                                    "hfm_crypto_btc_tpsl_0302",
                                    "hfm_crypto_btc_stability_short_window_shadow_v1",
                                ],
                                "recommendedResearchPriority": 3,
                                "recommendedResearchReasonZh": "现任稳健候选继续修 middle_third。",
                            },
                            {
                                "canonicalStrategyId": "hfm_crypto_btc_balanced_quality_repair_0028",
                                "aliasStrategyIds": [
                                    "hfm_crypto_btc_tpsl_4138",
                                    "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                                ],
                                "memberStrategyIds": [
                                    "hfm_crypto_btc_balanced_quality_repair_0028",
                                    "hfm_crypto_btc_tpsl_4138",
                                    "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                                ],
                                "recommendedResearchPriority": 1,
                                "recommendedResearchReasonZh": "高收益慢频候选优先补窗口样本。",
                            },
                            {
                                "canonicalStrategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                                "aliasStrategyIds": [
                                    "hfm_crypto_btc_sample_rich_quality_0009",
                                    "hfm_crypto_btc_sample_rich_quality_0007",
                                ],
                                "memberStrategyIds": [
                                    "hfm_crypto_btc_sample_rich_quality_0001",
                                    "hfm_crypto_btc_sample_rich_quality_0009",
                                    "hfm_crypto_btc_sample_rich_quality_0007",
                                ],
                                "recommendedResearchPriority": 2,
                                "recommendedResearchReasonZh": "样本丰富候选作为桥接修复方向。",
                            },
                            {
                                "canonicalStrategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                                "aliasStrategyIds": [],
                                "memberStrategyIds": ["hfm_crypto_btc_sample_balanced_both_shadow_v1"],
                            },
                        ],
                    },
                },
                "executionReadinessBoard": {
                    "status": "EXECUTION_READINESS_BOARD_READY",
                    "canProceedToSeparateReleaseLane": False,
                    "readyStrategyCountForSeparateReleaseLane": 0,
                    "closestResearchLaneNow": "btcCryptoCfd",
                    "selectedLaneForSeparateReleaseReview": "forexMt5",
                    "laneSnapshots": [
                        {
                            "lane": "forexMt5",
                            "focusStrategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                        },
                        {
                            "lane": "btcCryptoCfd",
                            "focusStrategyId": "hfm_crypto_btc_tpsl_0302",
                        },
                    ],
                    "nextActionsOverall": [
                        {
                            "id": "btc_runtime_preflight_refresh",
                            "lane": "btcCryptoCfd",
                            "actionZh": "先补 BTC runtime/data-plane 证据。",
                            "whyNowZh": "BTC 是当前唯一还能继续推进研究的 lane，但缺实时 dashboard/tick/spread 证据。",
                            "evidenceSummaryZh": "旧摘要，不应继续出现在 action plan 顶层。",
                            "evidenceSnapshot": {
                                "dashboardSymbolNames": ["USDJPY"],
                                "symbolSelectedInDashboardOk": False,
                                "symbolSelectionEffectiveOk": False,
                                "targetSymbol": "#BTCUSD",
                            },
                        },
                    ],
                },
            })
            self._write_json(agent / "QuantGod_SimTargetExecutionReviewSummary.json", {
                "targetEvidence": {
                    "targetReached": True,
                    "combinedVerifiedUsdProfit": 72.0,
                    "combinedTargetStatus": "TARGET_REACHED",
                }
            })
            self._write_json(agent / "QuantGod_ChampionPromotionGate.json", {
                "status": "WAITING_ISOLATED_TESTER_FORWARD_REPORT"
            })
            self._write_json(agent / "QuantGod_ChampionTesterRunGate.json", {
                "status": "CHAMPION_TESTER_RUN_GATE_BLOCKED",
                "gate": {
                    "blockers": [
                        "authorization_lock_expired",
                        "outside_strategy_tester_window",
                        "isolated_tester_account_context_not_ready",
                        "sensitive_account_context_sync_required",
                    ],
                    "liveSession": {
                        "status": "ready",
                        "ok": True,
                        "openTradeCount": 0,
                        "marginInUse": 0,
                        "accountNumber": "186054398",
                        "server": "HFMarketsGlobal-Live12",
                    },
                },
                "nextTesterWindow": {
                    "startJstIso": "2026-06-08T20:10:00+09:00",
                    "endJstIso": "2026-06-08T23:30:00+09:00",
                },
                "decision": {"canRunIsolatedTester": False},
            })
            self._write_json(agent / "QuantGod_ChampionTesterForwardRequest.json", {
                "status": "CHAMPION_TESTER_FORWARD_REQUEST_READY",
                "selectedTasks": [],
            })
            self._write_json(agent / "QuantGod_ChampionTesterLockDraft.json", {
                "status": "CHAMPION_TESTER_LOCK_DRAFT_READY",
                "decision": {"draftReadyForSeparateLockWriter": True},
            })
            self._write_json(agent / "QuantGod_LiveRuntimePreflightProbe.json", {
                "generatedAtIso": "2026-06-08T06:48:38Z",
                "status": "WAITING_RUNTIME_PREFLIGHT_INPUTS",
                "approvedLanes": ["hfmCryptoCfd"],
                "dashboardSnapshot": {
                    "path": "/Users/bowen/Library/Application Support/net.metaquotes.wine.metatrader5-live16/drive_c/Program Files/MetaTrader 5/MQL5/Files/QuantGod_Dashboard.json",
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
                "laneRuntimeChecks": [
                    {
                        "lane": "HFM_CRYPTO_CFD",
                        "brokerSymbol": "#BTCUSD",
                        "symbolPresentInRuntimeProbe": True,
                        "runtimeProbeSource": "dashboard",
                        "runtimeProbeFresh": True,
                        "runtimeProbeAgeSeconds": 0.0,
                        "symbolPresentInSnapshot": False,
                        "symbolPresentInNames": False,
                        "spreadFieldPresent": False,
                    }
                ],
                "blockers": [
                    {"code": "MT5_DASHBOARD_SNAPSHOT_STALE"},
                    {"code": "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED"},
                    {"code": "MT5_READ_ONLY_MODE_STILL_ACTIVE"},
                    {"code": "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT"},
                    {"code": "MT5_TRADE_ALLOWED_NOT_CONFIRMED"},
                ],
                "nextRequiredActionZh": "先补齐 dry-run replay、MT5 dashboard 新鲜快照、kill switch、账户、symbol 和价差证据。",
            })
            self._write_json(agent / "QuantGod_LiveEvidenceIntake.json", {
                "generatedAtIso": "2026-06-08T06:48:38Z",
                "status": "HFM_REVIEW_INPUTS_PRESENT",
                "readOnlyReviewCommands": [
                    {
                        "id": "refresh_evidence_intake",
                        "whenZh": "每次补证据后刷新本面板。",
                        "command": "python3 tools/run_live_automation_readiness.py --runtime-dir runtime evidence-intake --write --refresh-sources",
                    },
                    {
                        "id": "run_hfm_post_upgrade_controller",
                        "whenZh": "人工升级后反复跑这一条。",
                        "command": "python3 tools/run_hfm_crypto_cfd.py --runtime-dir runtime post-upgrade-controller --write",
                    },
                ],
            })
            hfm = runtime / "hfm_crypto"
            self._write_json(hfm / "QuantGod_HFMCryptoPostUpgradeController.json", {
                "status": "HFM_CRYPTO_POST_UPGRADE_REVIEW_AUTOMATED",
                "readyForHfmContractSpecReview": True,
                "executionSpecReviewReady": True,
            })
            self._write_json(hfm / "QuantGod_HFMCryptoMt5PostUpgradeVerify.json", {
                "status": "HFM_CRYPTO_MT5_POST_UPGRADE_VERIFIED",
            })
            self._write_json(hfm / "QuantGod_HFMCryptoMt5ExporterUpgradeBundle.json", {
                "status": "MT5_EXPORTER_ALREADY_AVAILABLE",
            })
            self._write_json(runtime / "QuantGod_IsolatedTesterAccountContextStatus.json", {
                "ready": False,
                "mode": "PREFLIGHT_ONLY_NO_SENSITIVE_COPY",
                "missingTarget": ["Config/accounts.dat"],
                "sensitiveAccountContextSyncRequired": True,
                "separateSyncReview": {
                    "status": "SEPARATE_SENSITIVE_ACCOUNT_CONTEXT_SYNC_REQUIRED",
                    "requiresSeparateControlledSync": True,
                    "writesMt5OrderRequest": False,
                },
            })

            with patch("tools.ace_upgrade_action_plan._process_evidence", return_value={
                "status": "PROCESS_SCAN_READY",
                "scanSupported": True,
                "mainMt5TerminalRunning": False,
                "isolatedTesterTerminalRunning": False,
                "dashboardServerRunning": True,
                "dailyAutopilotRunning": False,
                "liveExecutionFeedbackRunning": False,
                "blockers": ["mt5_terminal_process_missing"],
                "nextActionZh": "未发现主 MT5 terminal64 进程；live dashboard 可能不会继续刷新。",
                "launchesTerminal": False,
                "brokerCallsMade": False,
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            }):
                report = build_ace_upgrade_action_plan(runtime, write=False)

            step = report["operatorCommandDeck"]["steps"][0]
            self.assertEqual(
                step["actionZh"],
                "先刷新 live16 dashboard，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。",
            )
            self.assertIn("当前主要卡在 dashboard freshness 和执行模式字段", step["whyNowZh"])
            self.assertIn("而不是 symbol 取证", step["whyNowZh"])
            self.assertIn("selectedRaw=False selectedEffective=True", step["evidenceSummaryZh"])
            self.assertIn("tick=True spread=True", step["evidenceSummaryZh"])
            self.assertIn("livePilotMode=False", step["evidenceSummaryZh"])
            self.assertIn("readOnlyOff=False", step["evidenceSummaryZh"])
            self.assertEqual(
                step["gateDiagnostics"]["externalRefreshBlockers"],
                ["MT5_DASHBOARD_SNAPSHOT_STALE"],
            )
            self.assertEqual(
                step["gateDiagnostics"]["dataPlaneBlockers"],
                [],
            )
            self.assertTrue(step["evidenceSnapshot"]["symbolSelectionEffectiveOk"])
            self.assertEqual(
                step["gateDiagnostics"]["executionModeBlockers"],
                [
                    "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
                    "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                    "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
                    "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
                ],
            )
            self.assertEqual(
                step["gateDiagnostics"]["directExecutionBlockerCode"],
                None,
            )
            self.assertEqual(
                step["refreshOutcome"]["status"],
                "REFRESH_ATTEMPTED_EXECUTION_MODE_OR_FRESHNESS_BLOCKED",
            )
            self.assertIn(
                "#BTCUSD tick/spread",
                step["refreshOutcome"]["outcomeZh"],
            )
            self.assertEqual(
                step["refreshOutcome"]["sourceAlignmentStatus"],
                "ALIGNED_OR_UNKNOWN",
            )
            self.assertEqual(
                report["decision"]["nextActionZh"],
                "先刷新 live16 dashboard，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。",
            )
            self.assertIn(
                "当前主要卡在 dashboard freshness 和执行模式字段",
                report["decision"]["nextActionWhyZh"],
            )
            self.assertIn(
                "selectedRaw=False selectedEffective=True",
                report["decision"]["nextActionEvidenceSummaryZh"],
            )
            self.assertIn(
                "而不是 symbol 取证",
                report["decision"]["nextActionWhyZh"],
            )
            self.assertIn("tick=True spread=True", report["decision"]["nextActionEvidenceSummaryZh"])
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["gateDiagnostics"]["executionModeBlockers"],
                [
                    "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
                    "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                    "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
                    "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
                ],
            )
            self.assertEqual(
                report["decision"]["nextActionRefreshOutcome"]["status"],
                "REFRESH_ATTEMPTED_EXECUTION_MODE_OR_FRESHNESS_BLOCKED",
            )
            scanner_action = [row for row in report["actionQueue"] if row["id"] == "rerun_btc_strategy_scanner"][0]
            self.assertEqual(
                scanner_action["comparisonClusterCanonicalStrategyId"],
                "hfm_crypto_btc_sample_rich_quality_0001",
            )
            self.assertEqual(
                scanner_action["comparisonClusterRecommendedResearchPriority"],
                2,
            )
            self.assertIn("样本丰富候选作为桥接修复方向", scanner_action["whyNowZh"])
            self.assertIn(
                "对照簇=hfm_crypto_btc_sample_rich_quality_0001",
                scanner_action["evidenceSummaryZh"],
            )
            self.assertEqual(
                scanner_action["evidenceSnapshot"]["comparisonClusterCanonicalStrategyId"],
                "hfm_crypto_btc_sample_rich_quality_0001",
            )
            self.assertNotIn("dashboard_fresh", scanner_action["whyNowZh"])
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["secondaryLaneContext"]["lane"],
                "forexMt5",
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["secondaryLaneContext"]["seedId"],
                "GA-USDJPY-G0093-C0004",
            )
            self.assertEqual(
                report["workstreamStatus"]["researchWorkstream"]["secondaryLaneContext"]["nextActionZh"],
                "未发现主 MT5 terminal64 进程；先恢复主 terminal 并恢复 live dashboard 刷新，否则不能确认 live session freshness。",
            )
            self.assertIn(
                "outside_strategy_tester_window",
                report["workstreamStatus"]["researchWorkstream"]["secondaryLaneContext"]["blockers"],
            )


if __name__ == "__main__":
    unittest.main()
