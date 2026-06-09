from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ace_strategy_scout import build_ace_strategy_scout, read_ace_strategy_scout


class AceStrategyScoutTests(unittest.TestCase):
    def test_prefers_stable_hfm_crypto_shadow_without_execution_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "hfm_crypto").mkdir(parents=True)
            (runtime / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps(
                    {
                        "simulationQualified": True,
                        "metrics": {
                            "agentId": "hfm_crypto_btc_regime_stability_shadow_v1",
                            "strategyName": "BTC stability",
                            "pnlUsd": 65.2,
                            "roiPct": 6.5,
                            "sharpe": 2.7,
                            "maxDrawdownPct": 0.8,
                            "tradeCount": 29,
                            "liquidationCount": 0,
                        },
                        "blockers": [],
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "ga_factory").mkdir(parents=True)
            (runtime / "ga_factory" / "QuantGod_GAEliteArchive.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": "GA-USDJPY-G0001",
                                "strategyId": "USDJPY_RSI",
                                "strategyFamily": "RSI_Reversal",
                                "direction": "LONG",
                                "fitness": 4.0,
                                "status": "ELITE_SELECTED",
                                "promotionStage": "TESTER_ONLY",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_ace_strategy_scout(runtime, write=True)

            self.assertEqual(report["schema"], "quantgod.ace_strategy_scout.report.v1")
            self.assertEqual(report["status"], "ACE_SCOUT_READY")
            self.assertEqual(report["generatedAtIso"], report["generatedAt"])
            self.assertEqual(report["topLane"], "hfm_crypto_cfd_shadow")
            self.assertEqual(report["topStrategyId"], "hfm_crypto_btc_regime_stability_shadow_v1")
            self.assertEqual(report["topQualifiedCrypto"]["strategyId"], "hfm_crypto_btc_regime_stability_shadow_v1")
            self.assertEqual(report["topResearchCrypto"]["strategyId"], "hfm_crypto_btc_regime_stability_shadow_v1")
            self.assertEqual(report["topResearchCrypto"]["sourceArtifact"], "topQualifiedCrypto")
            self.assertEqual(report["gaIterationHealth"]["recommendedMode"], "ELITE_GUIDED_SEARCH")
            self.assertIn(
                "usd_jpy_top_forex_champion_retest",
                {action["id"] for action in report["nextSafeActions"]},
            )
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["mt5OrderSendAllowed"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])
            self.assertFalse(report["safety"]["livePresetMutationAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_AceStrategyScout.json").exists())

            saved = read_ace_strategy_scout(runtime)
            self.assertEqual(saved["topStrategyId"], report["topStrategyId"])
            self.assertEqual(saved["generatedAtIso"], saved["generatedAt"])

    def test_marks_bad_live12_rsi_as_not_ace_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_ForexLive12RsiCandidatePromotionGate.json").write_text(
                json.dumps(
                    {
                        "candidate": {
                            "afterMetrics": {
                                "netProfitUSC": -0.21,
                                "profitFactor": 0.9067,
                                "tradeCount": 9,
                                "maxConsecutiveLosses": 1,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = build_ace_strategy_scout(runtime, write=False)
            candidate = report["candidates"][0]

            self.assertEqual(candidate["lane"], "live12_rsi_repair_candidate")
            self.assertIn("NET_PROFIT_NOT_POSITIVE", candidate["blockers"])
            self.assertIn("PROFIT_FACTOR_LT_1_05", candidate["blockers"])
            self.assertEqual(candidate["decision"], "REPAIR_OR_DISCARD")
            self.assertFalse(candidate["safety"]["orderSendAllowed"])

    def test_downgrades_crypto_candidate_when_champion_retest_needs_more_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            strategy_id = "hfm_crypto_btc_regime_stability_shadow_v1"
            (runtime / "hfm_crypto").mkdir(parents=True)
            (runtime / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps(
                    {
                        "simulationQualified": True,
                        "metrics": {
                            "agentId": strategy_id,
                            "strategyName": "BTC stability",
                            "pnlUsd": 65.2,
                            "roiPct": 6.5,
                            "sharpe": 2.7,
                            "maxDrawdownPct": 0.8,
                            "tradeCount": 29,
                            "liquidationCount": 0,
                        },
                        "blockers": [],
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "cryptoChampion": {
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "strategyId": strategy_id,
                            "windowCount": 6,
                            "validWindowCount": 1,
                            "blockers": [
                                "BTC_MULTI_WINDOW_VALID_WINDOWS_LT_2",
                                "HFM_SHARPE_LT_MIN",
                                "HFM_TRADE_COUNT_LT_MIN",
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = build_ace_strategy_scout(runtime, write=False)
            candidate = report["candidates"][0]

            self.assertEqual(candidate["strategyId"], strategy_id)
            self.assertFalse(candidate["qualified"])
            self.assertEqual(candidate["decision"], "REPAIR_OR_DISCARD")
            self.assertEqual(candidate["championRetestStatus"], "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS")
            self.assertEqual(candidate["championRetestValidWindowCount"], 1)
            self.assertIn("CHAMPION_RETEST_BTC_MULTI_WINDOW_VALID_WINDOWS_LT_2", candidate["blockers"])
            self.assertIn(
                "CHAMPION_RETEST_STATUS_BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                candidate["blockers"],
            )
            self.assertIsNone(report["topQualifiedCrypto"]["strategyId"])
            self.assertEqual(report["topResearchCrypto"]["strategyId"], strategy_id)
            self.assertEqual(report["topResearchCrypto"]["sourceArtifact"], "topRetestedCrypto")
            self.assertFalse(candidate["safety"]["orderSendAllowed"])

    def test_reads_autogen_crypto_candidate_results_and_retest_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "hfm_crypto").mkdir(parents=True)
            (runtime / "hfm_crypto" / "QuantGod_HFMCryptoSimulationProfileReview.json").write_text(
                json.dumps(
                    {
                        "simulationQualified": True,
                        "metrics": {
                            "agentId": "hfm_crypto_btc_regime_stability_shadow_v1",
                            "strategyName": "BTC stability",
                            "pnlUsd": 65.2,
                            "roiPct": 6.5,
                            "sharpe": 2.7,
                            "maxDrawdownPct": 0.8,
                            "tradeCount": 29,
                            "liquidationCount": 0,
                        },
                        "blockers": [],
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "hfm_crypto" / "hfm_crypto_simulation_profile.autogen.json").write_text(
                json.dumps(
                    {
                        "simulation": {
                            "candidateResults": [
                                {
                                    "strategyId": "hfm_crypto_btc_regime_sample_rich_shadow_v1",
                                    "qualified": True,
                                    "blockerCodes": [],
                                    "metrics": {
                                        "agentId": "hfm_crypto_btc_regime_sample_rich_shadow_v1",
                                        "strategyName": "BTC sample rich",
                                        "pnlUsd": 80.0,
                                        "roiPct": 8.0,
                                        "sharpe": 2.2,
                                        "maxDrawdownPct": 1.0,
                                        "tradeCount": 44,
                                        "liquidationCount": 0,
                                    },
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "cryptoChampion": {
                            "strategyId": "hfm_crypto_btc_regime_sample_rich_shadow_v1",
                            "status": "BTC_CHAMPION_RETEST_PASS",
                            "validWindowCount": 2,
                            "windowCount": 6,
                            "fullWindowMetrics": {
                                "pnlUsd": 80.0,
                                "sharpe": 2.2,
                                "maxDrawdownPct": 1.0,
                                "tradeCount": 44,
                            },
                            "candidateRetests": [
                                {
                                    "strategyId": "hfm_crypto_btc_regime_stability_shadow_v1",
                                    "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                                    "validWindowCount": 1,
                                    "windowCount": 6,
                                    "blockers": ["BTC_MULTI_WINDOW_VALID_WINDOWS_LT_2"],
                                },
                                {
                                    "strategyId": "hfm_crypto_btc_regime_sample_rich_shadow_v1",
                                    "status": "BTC_CHAMPION_RETEST_PASS",
                                    "validWindowCount": 2,
                                    "windowCount": 6,
                                    "blockers": [],
                                },
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = build_ace_strategy_scout(runtime, write=False)

            self.assertEqual(report["topQualifiedCrypto"]["strategyId"], "hfm_crypto_btc_regime_sample_rich_shadow_v1")
            self.assertEqual(report["topResearchCrypto"]["strategyId"], "hfm_crypto_btc_regime_sample_rich_shadow_v1")
            self.assertEqual(report["topResearchCrypto"]["sourceArtifact"], "topQualifiedCrypto")
            self.assertEqual(report["topRetestedCrypto"]["strategyId"], "hfm_crypto_btc_regime_sample_rich_shadow_v1")
            self.assertEqual(report["topRetestedCrypto"]["validWindowCount"], 2)
            self.assertEqual(report["topLane"], "hfm_crypto_cfd_shadow")
            self.assertEqual(report["topStrategyId"], "hfm_crypto_btc_regime_sample_rich_shadow_v1")
            self.assertEqual(report["candidates"][0]["championRetestStatus"], "BTC_CHAMPION_RETEST_PASS")
            self.assertFalse(report["safety"]["orderSendAllowed"])

    def test_crypto_candidate_ranking_prefers_retest_stability_over_raw_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "cryptoChampion": {
                            "strategyId": "btc_stable",
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "validWindowCount": 5,
                            "windowCount": 6,
                            "positiveWindowCount": 6,
                            "negativeWindowCount": 0,
                            "positiveMajorWindowCount": 3,
                            "majorWindowFailureCount": 0,
                            "blockers": ["HFM_SHARPE_LT_MIN"],
                            "fullWindowMetrics": {
                                "agentId": "btc_stable",
                                "pnlUsd": 38.0,
                                "roiPct": 3.8,
                                "sharpe": 1.3,
                                "maxDrawdownPct": 1.5,
                                "tradeCount": 69,
                                "liquidationCount": 0,
                            },
                            "candidateRetests": [
                                {
                                    "strategyId": "btc_high_pnl_low_stability",
                                    "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                                    "validWindowCount": 2,
                                    "windowCount": 6,
                                    "positiveWindowCount": 6,
                                    "negativeWindowCount": 0,
                                    "positiveMajorWindowCount": 3,
                                    "majorWindowFailureCount": 0,
                                    "blockers": ["HFM_SHARPE_LT_MIN"],
                                    "fullWindowMetrics": {
                                        "agentId": "btc_high_pnl_low_stability",
                                        "pnlUsd": 82.0,
                                        "roiPct": 8.2,
                                        "sharpe": 2.2,
                                        "maxDrawdownPct": 1.5,
                                        "tradeCount": 48,
                                        "liquidationCount": 0,
                                    },
                                },
                                {
                                    "strategyId": "btc_stable",
                                    "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                                    "validWindowCount": 5,
                                    "windowCount": 6,
                                    "positiveWindowCount": 6,
                                    "negativeWindowCount": 0,
                                    "positiveMajorWindowCount": 3,
                                    "majorWindowFailureCount": 0,
                                    "blockers": ["HFM_SHARPE_LT_MIN"],
                                    "fullWindowMetrics": {
                                        "agentId": "btc_stable",
                                        "pnlUsd": 38.0,
                                        "roiPct": 3.8,
                                        "sharpe": 1.3,
                                        "maxDrawdownPct": 1.5,
                                        "tradeCount": 69,
                                        "liquidationCount": 0,
                                    },
                                },
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = build_ace_strategy_scout(runtime, write=False)

            self.assertEqual(report["topRetestedCrypto"]["strategyId"], "btc_stable")
            self.assertEqual(report["candidates"][0]["strategyId"], "btc_stable")
            self.assertEqual(report["candidates"][0]["championRetestValidWindowCount"], 5)
            self.assertEqual(report["candidates"][0]["championRetestNegativeWindowCount"], 0)
            self.assertGreater(report["candidates"][0]["score"], report["candidates"][1]["score"])
            self.assertFalse(report["candidates"][0]["safety"]["orderSendAllowed"])

    def test_refreshes_stale_champion_retest_when_btc_scan_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            agent.mkdir(parents=True)
            stale_retest = {
                "generatedAtIso": "2026-06-08T15:00:00Z",
                "cryptoChampion": {
                    "strategyId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                    "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "positiveWindowCount": 6,
                    "negativeWindowCount": 0,
                    "positiveMajorWindowCount": 3,
                    "majorWindowFailureCount": 0,
                    "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    "fullWindowMetrics": {
                        "agentId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                        "pnlUsd": 38.7432,
                        "roiPct": 3.8743,
                        "sharpe": 1.326,
                        "maxDrawdownPct": 1.5619,
                        "tradeCount": 69,
                        "liquidationCount": 0,
                    },
                    "candidateRetests": [
                        {
                            "strategyId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "validWindowCount": 5,
                            "windowCount": 6,
                            "positiveWindowCount": 6,
                            "negativeWindowCount": 0,
                            "positiveMajorWindowCount": 3,
                            "majorWindowFailureCount": 0,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                            "fullWindowMetrics": {
                                "agentId": "hfm_crypto_btc_stability_short_window_shadow_v1",
                                "pnlUsd": 38.7432,
                                "roiPct": 3.8743,
                                "sharpe": 1.326,
                                "maxDrawdownPct": 1.5619,
                                "tradeCount": 69,
                                "liquidationCount": 0,
                            },
                        }
                    ],
                },
            }
            (agent / "QuantGod_ChampionRetestReport.json").write_text(json.dumps(stale_retest), encoding="utf-8")
            scan = {
                "generatedAtIso": "2026-06-08T16:10:12Z",
                "topRecommendation": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "strategyName": "BTCUSD near-live middle-window follow-up scan",
                    "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "positiveWindowCount": 6,
                    "negativeWindowCount": 0,
                    "positiveMajorWindowCount": 3,
                    "majorWindowFailureCount": 0,
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
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                },
                "topCandidates": [
                    {
                        "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                        "strategyName": "BTCUSD near-live middle-window follow-up scan",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "positiveWindowCount": 6,
                        "negativeWindowCount": 0,
                        "positiveMajorWindowCount": 3,
                        "majorWindowFailureCount": 0,
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
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 300.0,
                            "maxHoldBars": 8,
                            "cooldownBars": 4,
                        },
                    },
                    {
                        "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                        "strategyName": "BTCUSD near-live stop-loss ladder refinement scan",
                        "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                        "validWindowCount": 5,
                        "windowCount": 6,
                        "positiveWindowCount": 6,
                        "negativeWindowCount": 0,
                        "positiveMajorWindowCount": 3,
                        "majorWindowFailureCount": 0,
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
                            "takeProfitPriceMove": 450.0,
                            "stopLossPriceMove": 312.5,
                            "maxHoldBars": 8,
                            "cooldownBars": 4,
                        },
                    },
                ],
                "nextFocusedSearchPlan": {
                    "nearLiveStoplossLadderRefinementBestStrategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                },
                "repairDiagnostics": {
                    "stableMiddleTradeoffFollowup": {
                        "bestByStabilityRank": {
                            "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                            "strategyName": "BTCUSD stable middle tradeoff follow-up scan",
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "validWindowCount": 3,
                            "windowCount": 6,
                            "positiveWindowCount": 6,
                            "negativeWindowCount": 0,
                            "positiveMajorWindowCount": 3,
                            "majorWindowFailureCount": 0,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                            "fullWindowMetrics": {
                                "pnlUsd": 29.068,
                                "roiPct": 2.9068,
                                "sharpe": 1.0329,
                                "maxDrawdownPct": 1.7218,
                                "tradeCount": 64,
                                "liquidationCount": 0,
                            },
                        }
                    }
                },
            }
            (agent / "QuantGod_BtcStrategyScanReport.json").write_text(json.dumps(scan), encoding="utf-8")
            (agent / "QuantGod_ChampionTesterRunGate.json").write_text(
                json.dumps(
                    {
                        "generatedAtIso": "2026-06-09T00:00:00Z",
                        "blockers": [
                            "live_dashboard_snapshot_stale",
                            "outside_strategy_tester_window",
                            "mt5_terminal_process_missing",
                        ],
                        "decision": {
                            "nextRequiredActionZh": "先恢复主 MT5 terminal64 进程并恢复 dashboard freshness，再重建 tester gate。"
                        },
                    }
                ),
                encoding="utf-8",
            )
            (agent / "QuantGod_LiveEvidenceIntake.json").write_text(
                json.dumps(
                    {
                        "generatedAtIso": "2026-06-09T00:00:00Z",
                        "dashboardFresh": False,
                        "tradeStatus": "SHADOW",
                        "tradePermissionBlocker": "READ_ONLY_MODE",
                    }
                ),
                encoding="utf-8",
            )

            rebuilt_retest = {
                "generatedAtIso": "2026-06-08T16:10:30Z",
                "cryptoChampion": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                    "validWindowCount": 5,
                    "windowCount": 6,
                    "positiveWindowCount": 6,
                    "negativeWindowCount": 0,
                    "positiveMajorWindowCount": 3,
                    "majorWindowFailureCount": 0,
                    "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    "fullWindowMetrics": {
                        "agentId": "hfm_crypto_btc_near_live_middle_window_0003",
                        "pnlUsd": 54.2343,
                        "roiPct": 5.4234,
                        "sharpe": 1.7858,
                        "maxDrawdownPct": 1.1824,
                        "tradeCount": 80,
                        "liquidationCount": 0,
                    },
                    "candidateRetests": [
                        {
                            "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "validWindowCount": 5,
                            "windowCount": 6,
                            "positiveWindowCount": 6,
                            "negativeWindowCount": 0,
                            "positiveMajorWindowCount": 3,
                            "majorWindowFailureCount": 0,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                            "fullWindowMetrics": {
                                "agentId": "hfm_crypto_btc_near_live_middle_window_0003",
                                "pnlUsd": 54.2343,
                                "roiPct": 5.4234,
                                "sharpe": 1.7858,
                                "maxDrawdownPct": 1.1824,
                                "tradeCount": 80,
                                "liquidationCount": 0,
                            },
                        },
                        {
                            "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "validWindowCount": 5,
                            "windowCount": 6,
                            "positiveWindowCount": 6,
                            "negativeWindowCount": 0,
                            "positiveMajorWindowCount": 3,
                            "majorWindowFailureCount": 0,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                            "fullWindowMetrics": {
                                "agentId": "hfm_crypto_btc_near_live_middle_window_0021",
                                "pnlUsd": 54.2343,
                                "roiPct": 5.4234,
                                "sharpe": 1.7858,
                                "maxDrawdownPct": 1.1824,
                                "tradeCount": 80,
                                "liquidationCount": 0,
                            },
                        },
                    ],
                },
            }

            def _fake_rebuild(runtime_dir: Path, write: bool = False) -> dict:
                self.assertTrue(write)
                target = runtime_dir / "agent" / "QuantGod_ChampionRetestReport.json"
                target.write_text(json.dumps(rebuilt_retest), encoding="utf-8")
                return rebuilt_retest

            with patch("tools.champion_retest.build_champion_retest_report", side_effect=_fake_rebuild) as rebuild:
                report = build_ace_strategy_scout(runtime, write=False)

            self.assertEqual(rebuild.call_count, 1)
            self.assertEqual(report["topRetestedCrypto"]["strategyId"], "hfm_crypto_btc_near_live_middle_window_0003")
            self.assertEqual(report["topResearchCrypto"]["strategyId"], "hfm_crypto_btc_near_live_middle_window_0003")
            self.assertEqual(report["topResearchCrypto"]["sourceArtifact"], "topRetestedCrypto")
            self.assertEqual(report["currentResearchLane"], "btcCryptoCfd")
            self.assertEqual(report["currentOperatorLane"], "btcCryptoCfd")
            self.assertEqual(report["researchNextActionZh"], report["nextActionZh"])
            self.assertIn("hfm_crypto_btc_near_live_middle_window_0003", report["nextActionZh"])
            self.assertIn("hfm_crypto_btc_near_live_middle_window_0021", report["nextActionZh"])
            self.assertIn("hfm_crypto_btc_stable_middle_tradeoff_0046", report["nextActionZh"])
            self.assertNotIn("stable middle tradeoff follow-up", report["nextActionZh"])
            self.assertIn("live16 dashboard", report["operatorNextActionZh"])
            self.assertIn("READ_ONLY_MODE", report["operatorBlockers"])
            self.assertIn("championTesterRunGate", report["operatorSourceArtifacts"])
            self.assertIn("liveEvidenceIntake", report["operatorSourceArtifacts"])
            self.assertEqual(
                report["btcResearchFocus"]["topStrategyId"],
                "hfm_crypto_btc_near_live_middle_window_0003",
            )
            self.assertEqual(
                report["btcResearchFocus"]["nextDistinctStrategyId"],
                "hfm_crypto_btc_near_live_middle_window_0021",
            )
            self.assertEqual(
                report["btcResearchFocus"]["repairStrategyId"],
                "hfm_crypto_btc_stable_middle_tradeoff_0046",
            )
            self.assertEqual(
                report["btcResearchFocus"]["recommendedFocusedRetestOrder"],
                [
                    "hfm_crypto_btc_near_live_middle_window_0003",
                    "hfm_crypto_btc_near_live_middle_window_0021",
                    "hfm_crypto_btc_stable_middle_tradeoff_0046",
                ],
            )
            self.assertEqual(
                report["btcResearchFocus"]["nextDistinctContenderStrategyId"],
                "hfm_crypto_btc_near_live_middle_window_0021",
            )
            self.assertEqual(
                report["btcResearchFocus"]["repairLineStrategyId"],
                "hfm_crypto_btc_stable_middle_tradeoff_0046",
            )
            self.assertEqual(
                report["btcResearchFocus"]["convergedVariantStrategyIds"],
                [
                    "hfm_crypto_btc_near_live_middle_window_0003",
                    "hfm_crypto_btc_near_live_middle_window_0021",
                    "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                ],
            )
            self.assertEqual(
                report["btcResearchFocus"]["convergedVariantStopLossLadder"],
                [325.0, 300.0, 312.5],
            )
            self.assertIn(
                "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                report["btcResearchFocus"]["convergedVariantSummaryZh"],
            )
            crypto_ids = [row["strategyId"] for row in report["candidates"] if row.get("lane") == "hfm_crypto_cfd_shadow"][:2]
            self.assertEqual(
                crypto_ids,
                [
                    "hfm_crypto_btc_near_live_middle_window_0003",
                    "hfm_crypto_btc_near_live_middle_window_0021",
                ],
            )

    def test_surfaces_mt5_operator_lane_when_forex_release_path_is_closer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            agent = runtime / "agent"
            (runtime / "ga_factory").mkdir(parents=True)
            (runtime / "ga").mkdir(parents=True)
            agent.mkdir(parents=True)

            (runtime / "ga_factory" / "QuantGod_GAEliteArchive.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": "GA-USDJPY-G0093-C0004",
                                "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004",
                                "strategyFamily": "RSI_Reversal",
                                "direction": "LONG",
                                "fitness": 7.796,
                                "status": "ELITE_SELECTED",
                                "promotionStage": "TESTER_ONLY",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "ga" / "QuantGod_GAEliteStrategies.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": "GA-USDJPY-G0093-C0004",
                                "fitnessBreakdown": {
                                    "strategyBacktest": {
                                        "netR": 6.5923,
                                        "profitFactor": 2.6998,
                                        "sharpe": 2.0702,
                                        "maxDrawdownR": 1.9486,
                                        "tradeCount": 25,
                                    },
                                    "walkForward": {
                                        "summary": {
                                            "stabilityScore": 0.95,
                                            "trainNetR": 5.0877,
                                            "validationNetR": 1.6828,
                                            "forwardNetR": 2.3428,
                                            "forwardNetRDelta": 0.66,
                                        }
                                    },
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (agent / "QuantGod_BtcStrategyScanReport.json").write_text(
                json.dumps(
                    {
                        "generatedAtIso": "2026-06-09T00:00:00Z",
                        "topRecommendation": {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003"},
                        "mostStableTradeoff": {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003"},
                        "topCandidates": [
                            {"strategyId": "hfm_crypto_btc_near_live_middle_window_0003"},
                            {"strategyId": "hfm_crypto_btc_near_live_middle_window_0021"},
                        ],
                        "nextFocusedSearchPlan": {
                            "nextActionZh": "继续复验 BTC 主线。",
                            "recommendations": [
                                {
                                    "id": "near_live_stability_challenger",
                                    "basisStrategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                                    "reasonZh": "继续复验 near-live challenger。",
                                },
                                {
                                    "id": "stable_champion_middle_third_rescue",
                                    "basisStrategyId": "hfm_crypto_btc_stable_middle_followup_refinement_0003",
                                    "reasonZh": "继续保留第三条稳定 fallback。",
                                },
                            ],
                            "repairStrategyId": "hfm_crypto_btc_stable_middle_followup_refinement_0003",
                            "recommendedFocusedRetestOrder": [
                                "hfm_crypto_btc_near_live_middle_window_0003",
                                "hfm_crypto_btc_near_live_middle_window_0021",
                                "hfm_crypto_btc_stable_middle_followup_refinement_0003",
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (agent / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps({"generatedAtIso": "2026-06-09T00:00:01Z", "cryptoChampion": {}, "forexChampion": {}}),
                encoding="utf-8",
            )
            (agent / "QuantGod_ChampionTesterRunGate.json").write_text(
                json.dumps(
                    {
                        "generatedAtIso": "2026-06-09T00:00:00Z",
                        "blockers": [
                            "live_dashboard_snapshot_stale",
                            "outside_strategy_tester_window",
                            "mt5_terminal_process_missing",
                        ],
                        "decision": {
                            "nextRequiredActionZh": "先恢复主 MT5 terminal64 进程并恢复 dashboard freshness，再重建 tester gate。"
                        },
                    }
                ),
                encoding="utf-8",
            )
            (agent / "QuantGod_LiveEvidenceIntake.json").write_text(
                json.dumps(
                    {
                        "generatedAtIso": "2026-06-09T00:00:00Z",
                        "dashboardFresh": False,
                        "tradeStatus": "SHADOW",
                        "tradePermissionBlocker": "READ_ONLY_MODE",
                    }
                ),
                encoding="utf-8",
            )

            report = build_ace_strategy_scout(runtime, write=False)

            self.assertEqual(report["currentResearchLane"], "btcCryptoCfd")
            self.assertEqual(report["currentOperatorLane"], "forexMt5")
            self.assertIn("terminal64", report["operatorNextActionZh"])
            self.assertIn("mt5_terminal_process_missing", report["operatorBlockers"])

    def test_uses_walk_forward_sample_count_for_ga_low_sample_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "ga_factory").mkdir(parents=True)
            (runtime / "ga").mkdir(parents=True)
            seed_id = "GA-USDJPY-G0093-C0004"
            strategy_id = "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR_092_001_CROSS_093_004"
            (runtime / "ga_factory" / "QuantGod_GAEliteArchive.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": seed_id,
                                "strategyId": strategy_id,
                                "strategyFamily": "RSI_Reversal",
                                "direction": "LONG",
                                "fitness": 7.796,
                                "status": "ELITE_SELECTED",
                                "promotionStage": "TESTER_ONLY",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "ga" / "QuantGod_GAEliteStrategies.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": seed_id,
                                "strategyBacktest": {},
                                "fitnessBreakdown": {
                                    "strategyBacktest": {
                                        "netR": 6.5923,
                                        "profitFactor": 2.6998,
                                        "sharpe": 2.0702,
                                        "maxDrawdownR": 1.9486,
                                        "tradeCount": 18,
                                    },
                                    "walkForward": {
                                        "summary": {
                                            "sampleCount": 25,
                                            "stabilityScore": 0.95,
                                            "promotionAllowed": True,
                                        },
                                        "segments": [
                                            {"segment": "train", "tradeCount": 14},
                                            {"segment": "validation", "tradeCount": 5},
                                            {"segment": "forward", "tradeCount": 6},
                                        ],
                                    },
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_ace_strategy_scout(runtime, write=False)
            candidate = report["candidates"][0]

            self.assertEqual(candidate["seedId"], seed_id)
            self.assertEqual(candidate["tradeCount"], 18)
            self.assertEqual(candidate["effectiveSampleCount"], 25)
            self.assertNotIn("LOW_SAMPLE_LT_20", candidate["blockers"])
            self.assertTrue(candidate["qualified"])
            self.assertEqual(report["topQualifiedForex"]["seedId"], seed_id)

    def test_marks_tied_forex_ace_candidates_for_parallel_tester_forward(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "ga_factory").mkdir(parents=True)
            (runtime / "ga").mkdir(parents=True)
            tied_rows = [
                ("GA-USDJPY-G0093-C0004", "USDJPY_RSI_A"),
                ("GA-USDJPY-G0102-C0004", "USDJPY_RSI_B"),
            ]
            (runtime / "ga_factory" / "QuantGod_GAEliteArchive.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": seed_id,
                                "strategyId": strategy_id,
                                "strategyFamily": "RSI_Reversal",
                                "direction": "LONG",
                                "fitness": 7.796,
                                "status": "ELITE_SELECTED",
                                "promotionStage": "TESTER_ONLY",
                            }
                            for seed_id, strategy_id in tied_rows
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "ga" / "QuantGod_GAEliteStrategies.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": seed_id,
                                "strategyBacktest": {},
                                "fitnessBreakdown": {
                                    "strategyBacktest": {
                                        "netR": 6.5923,
                                        "profitFactor": 2.6998,
                                        "sharpe": 2.0702,
                                        "maxDrawdownR": 1.9486,
                                        "tradeCount": 18,
                                    },
                                    "walkForward": {
                                        "summary": {
                                            "sampleCount": 25,
                                            "trainNetR": 5.0877,
                                            "validationNetR": 1.6828,
                                            "forwardNetR": 2.3428,
                                            "forwardNetRDelta": 0.66,
                                            "stabilityScore": 0.95,
                                            "promotionAllowed": True,
                                        },
                                        "segments": [
                                            {"segment": "train", "tradeCount": 14},
                                            {"segment": "validation", "tradeCount": 5},
                                            {"segment": "forward", "tradeCount": 6},
                                        ],
                                    },
                                },
                            }
                            for seed_id, _strategy_id in tied_rows
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_ace_strategy_scout(runtime, write=False)
            review = report["forexContenderReview"]

            self.assertEqual(review["status"], "PARALLEL_TESTER_FORWARD_TIE_BREAK_REQUIRED")
            self.assertEqual(review["tiedTopCount"], 2)
            self.assertTrue(review["requiresParallelTesterForward"])
            self.assertEqual(
                {row["seedId"] for row in review["contenders"]},
                {"GA-USDJPY-G0093-C0004", "GA-USDJPY-G0102-C0004"},
            )
            self.assertEqual(review["contenders"][0]["forwardNetR"], 2.3428)
            self.assertFalse(review["safety"]["orderSendAllowed"])
            self.assertFalse(report["nextSafeActions"][0]["orderSendAllowed"])
            plan = report["moneyPriorityPlan"]
            self.assertEqual(plan["focusMode"], "FOREX_AB_TESTER_FORWARD_TIE_BREAK")
            self.assertEqual(plan["immediateWorkQueue"][0]["id"], "forex_ab_tie_break")
            self.assertEqual(plan["immediateWorkQueue"][0]["priority"], 1)
            self.assertIn("暂不把 10 仓位作为主目标。", plan["deprioritizedWorkZh"])
            self.assertFalse(plan["executionPolicy"]["orderSendAllowed"])
            self.assertFalse(plan["executionPolicy"]["writesMt5OrderRequest"])


if __name__ == "__main__":
    unittest.main()
