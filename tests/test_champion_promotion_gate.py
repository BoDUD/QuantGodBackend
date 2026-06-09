from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.champion_promotion_gate import build_champion_promotion_gate, read_champion_promotion_gate


class ChampionPromotionGateTests(unittest.TestCase):
    def test_g0077_champion_moves_only_to_isolated_tester_forward(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_AceStrategyScout.json").write_text(
                json.dumps(
                    {
                        "topQualifiedForex": {
                            "seedId": "GA-USDJPY-G0077-C0002",
                            "strategyId": "USDJPY_RSI_REVERSAL",
                            "profitFactor": 3.0434,
                            "sharpe": 2.4035,
                            "tradeCount": 20,
                            "walkForwardStability": 0.95,
                        },
                        "topQualifiedCrypto": {"strategyId": None},
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "forexChampion": {
                            "status": "FOREX_CHAMPION_RETEST_PASS",
                            "seedId": "GA-USDJPY-G0077-C0002",
                            "blockers": [],
                        },
                        "forexContenderReview": {
                            "status": "PARALLEL_TESTER_FORWARD_TIE_BREAK_REQUIRED",
                            "requiresParallelTesterForward": True,
                            "contenders": [
                                {"seedId": "GA-USDJPY-G0077-C0002"},
                                {"seedId": "GA-USDJPY-G0093-C0004"},
                            ],
                            "safety": {"orderSendAllowed": False},
                        },
                        "cryptoChampion": {
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "strategyId": "hfm_crypto_btc_regime_stability_shadow_v1",
                            "validWindowCount": 1,
                            "windowCount": 6,
                            "blockers": ["BTC_MULTI_WINDOW_VALID_WINDOWS_LT_2"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_SimToLiveAutomationPipeline.json").write_text(
                json.dumps(
                    {
                        "status": "READY_FOR_SEPARATE_EXECUTION_ADAPTER_REVIEW",
                        "readyForSeparateExecutionAdapterReview": True,
                        "executionReady": False,
                        "autoPromotionToLiveAllowed": False,
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionTesterForwardRequest.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.champion_tester_forward_request.v1",
                        "status": "CHAMPION_TESTER_FORWARD_REQUEST_READY",
                        "summary": {"topCandidateId": "g0077-usdjpy-rsi-champion-tester-forward-v1"},
                        "selectedTasks": [
                            {
                                "candidateId": "g0077-usdjpy-rsi-champion-tester-forward-v1",
                                "testerOnly": True,
                                "livePresetMutation": False,
                                "runTerminalDefault": False,
                            }
                        ],
                        "materializationStatus": {
                            "status": "WAITING_CONFIG_MATERIALIZATION",
                            "htmlReportParsedCount": 0,
                        },
                        "safety": {
                            "orderSendAllowed": False,
                            "writesMt5OrderRequest": False,
                            "livePresetMutationAllowed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionTesterRunGate.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.champion_tester_run_gate.v1",
                        "status": "CHAMPION_TESTER_RUN_GATE_BLOCKED",
                        "gate": {
                            "canRunTerminal": False,
                            "blockers": [
                                "authorization_lock_expired",
                                "isolated_tester_account_context_not_ready",
                            ],
                            "liveSession": {"status": "ready", "openTradeCount": 0, "marginInUse": 0},
                        },
                        "testerAccountContext": {
                            "ready": False,
                            "missingTarget": ["Config/accounts.dat"],
                        },
                        "nextTesterWindow": {"startJstIso": "2026-06-04T20:10:00+09:00"},
                        "decision": {"canRunIsolatedTester": False},
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionTesterLockDraft.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.champion_tester_lock_draft.v1",
                        "status": "CHAMPION_TESTER_LOCK_DRAFT_READY",
                        "lockFileWritten": False,
                        "targetLockPath": "/tmp/QuantGod_AutoTesterWindow.lock.json",
                        "draftPayload": {
                            "testerOnly": True,
                            "livePresetMutation": False,
                            "candidateId": "g0077-usdjpy-rsi-champion-tester-forward-v1",
                        },
                        "decision": {"draftReadyForSeparateLockWriter": True},
                        "safety": {
                            "orderSendAllowed": False,
                            "writesMt5OrderRequest": False,
                            "livePresetMutationAllowed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_promotion_gate(runtime, write=True)

            self.assertEqual(report["schema"], "quantgod.champion_promotion_gate.v1")
            self.assertEqual(report["status"], "WAITING_ISOLATED_TESTER_FORWARD_REPORT")
            self.assertEqual(report["selectedChampion"]["seedId"], "GA-USDJPY-G0077-C0002")
            self.assertTrue(report["promotionDecision"]["canRunIsolatedTesterForwardNext"])
            self.assertFalse(report["promotionDecision"]["canGenerateTesterForwardRequestNext"])
            self.assertFalse(report["promotionDecision"]["canPromoteToLiveNow"])
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])
            self.assertNotIn("isolated_tester_forward_required", report["blockers"])
            self.assertIn("isolated_tester_forward_report_ready", report["blockers"])
            self.assertIn("champion_tester_run_gate_ready", report["blockers"])
            self.assertNotIn("champion_tester_lock_draft_ready", report["blockers"])
            self.assertTrue(report["championTesterForwardRequest"]["ready"])
            self.assertFalse(report["championTesterRunGate"]["ready"])
            self.assertTrue(report["championTesterRunGate"]["blockers"])
            self.assertTrue(report["championTesterLockDraft"]["ready"])
            self.assertTrue(report["forexContenderReview"]["requiresParallelTesterForward"])
            self.assertIn("GA-USDJPY-G0077-C0002 / GA-USDJPY-G0093-C0004", report["promotionDecision"]["reasonZh"])
            self.assertIn("GA-USDJPY-G0077-C0002 / GA-USDJPY-G0093-C0004", report["nextSafeActions"][0]["actionZh"])
            saved = read_champion_promotion_gate(runtime)
            self.assertEqual(saved["selectedChampion"]["seedId"], "GA-USDJPY-G0077-C0002")

    def test_refreshes_tester_run_gate_instead_of_using_stale_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_AceStrategyScout.json").write_text(
                json.dumps(
                    {
                        "topQualifiedForex": {
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR",
                            "profitFactor": 2.6998,
                            "sharpe": 2.0702,
                            "tradeCount": 18,
                            "walkForwardStability": 0.95,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "forexChampion": {
                            "status": "FOREX_CHAMPION_RETEST_PASS",
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "blockers": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_SimToLiveAutomationPipeline.json").write_text(
                json.dumps(
                    {
                        "status": "READY_FOR_SEPARATE_EXECUTION_ADAPTER_REVIEW",
                        "readyForSeparateExecutionAdapterReview": True,
                        "executionReady": False,
                        "autoPromotionToLiveAllowed": False,
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionTesterForwardRequest.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.champion_tester_forward_request.v1",
                        "status": "CHAMPION_TESTER_FORWARD_REQUEST_READY",
                        "summary": {"topCandidateId": "g0093-usdjpy-rsi-champion-tester-forward-v1"},
                        "selectedTasks": [
                            {
                                "candidateId": "g0093-usdjpy-rsi-champion-tester-forward-v1",
                                "testerOnly": True,
                                "livePresetMutation": False,
                                "runTerminalDefault": False,
                            }
                        ],
                        "materializationStatus": {
                            "status": "WAITING_CONFIG_MATERIALIZATION",
                            "htmlReportParsedCount": 0,
                        },
                        "safety": {
                            "orderSendAllowed": False,
                            "writesMt5OrderRequest": False,
                            "livePresetMutationAllowed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionTesterRunGate.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.champion_tester_run_gate.v1",
                        "status": "CHAMPION_TESTER_RUN_GATE_BLOCKED",
                        "gate": {
                            "canRunTerminal": False,
                            "blockers": ["live_session_has_open_positions"],
                            "liveSession": {
                                "status": "blocked",
                                "openTradeCount": 2,
                                "marginInUse": 75.0,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionTesterLockDraft.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.champion_tester_lock_draft.v1",
                        "status": "CHAMPION_TESTER_LOCK_DRAFT_READY",
                        "lockFileWritten": False,
                        "draftPayload": {
                            "testerOnly": True,
                            "livePresetMutation": False,
                            "candidateId": "g0093-usdjpy-rsi-champion-tester-forward-v1",
                        },
                        "decision": {"draftReadyForSeparateLockWriter": True},
                        "safety": {
                            "orderSendAllowed": False,
                            "writesMt5OrderRequest": False,
                            "livePresetMutationAllowed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            fresh_run_gate = {
                "schema": "quantgod.champion_tester_run_gate.v1",
                "status": "CHAMPION_TESTER_RUN_GATE_BLOCKED",
                "gate": {
                    "canRunTerminal": False,
                    "blockers": [
                        "live_dashboard_snapshot_stale",
                        "outside_strategy_tester_window",
                        "isolated_tester_account_context_not_ready",
                        "sensitive_account_context_sync_required",
                    ],
                    "liveSession": {
                        "status": "ready",
                        "openTradeCount": 0,
                        "marginInUse": 0.0,
                    },
                },
                "decision": {"canRunIsolatedTester": False},
                "testerAccountContext": {
                    "ready": False,
                    "missingTarget": ["Config/accounts.dat"],
                    "environmentBlocked": True,
                    "strategyBlocked": False,
                    "sensitiveAccountContextSyncRequired": True,
                },
            }

            with patch("tools.champion_promotion_gate.build_champion_tester_run_gate", return_value=fresh_run_gate) as refresh:
                report = build_champion_promotion_gate(runtime, write=False)

            refresh.assert_called_once_with(runtime, write=True)
            self.assertEqual(report["championTesterRunGate"]["liveSession"]["openTradeCount"], 0)
            self.assertEqual(report["championTesterRunGate"]["liveSession"]["marginInUse"], 0.0)
            self.assertEqual(
                report["championTesterRunGate"]["blockers"],
                [
                    "live_dashboard_snapshot_stale",
                    "outside_strategy_tester_window",
                    "isolated_tester_account_context_not_ready",
                    "sensitive_account_context_sync_required",
                ],
            )
            self.assertNotIn("live_session_has_open_positions", report["championTesterRunGate"]["blockers"])
            diagnosis = report["readinessDiagnosis"]
            self.assertTrue(diagnosis["strategyReadyForTester"])
            self.assertFalse(diagnosis["strategyBlocked"])
            self.assertTrue(diagnosis["environmentBlocked"])
            self.assertTrue(diagnosis["sensitiveAccountContextSyncRequired"])
            self.assertIn("live_dashboard_snapshot_stale", diagnosis["environmentBlockers"])
            self.assertIn("outside_strategy_tester_window", diagnosis["environmentBlockers"])
            self.assertIn("isolated_tester_account_context_not_ready", diagnosis["environmentBlockers"])
            self.assertIn("sensitive_account_context_sync_required", diagnosis["environmentBlockers"])
            self.assertTrue(report["promotionDecision"]["strategyReadyButEnvironmentBlocked"])

    def test_no_crypto_promotion_when_ace_scout_has_no_qualified_crypto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_AceStrategyScout.json").write_text(
                json.dumps(
                    {
                        "topQualifiedForex": {"seedId": None},
                        "topQualifiedCrypto": {"strategyId": None},
                        "topRetestedCrypto": {
                            "strategyId": "hfm_crypto_btc_regime_sample_rich_shadow_v1",
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "validWindowCount": 2,
                            "windowCount": 6,
                            "pnlUsd": 69.2107,
                            "sharpe": 2.2174,
                            "maxDrawdownPct": 1.9924,
                            "tradeCount": 44,
                            "blockers": ["WINDOW_PNL_NOT_POSITIVE"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "cryptoChampion": {
                            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                            "strategyId": "hfm_crypto_btc_regime_stability_shadow_v1",
                            "validWindowCount": 1,
                            "windowCount": 6,
                            "positiveMajorWindowCount": 3,
                            "majorWindowFailureCount": 0,
                            "negativeMajorWindows": [],
                            "fullWindowMetrics": {
                                "pnlUsd": 65.2172,
                                "sharpe": 2.7529,
                                "maxDrawdownPct": 0.7974,
                                "tradeCount": 29,
                            },
                            "blockers": ["BTC_MULTI_WINDOW_VALID_WINDOWS_LT_2"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_promotion_gate(runtime, write=False)

            self.assertEqual(report["status"], "NO_ACE_CHAMPION_SELECTED")
            self.assertEqual(report["observedCryptoChampion"]["strategyId"], "hfm_crypto_btc_regime_stability_shadow_v1")
            self.assertEqual(report["observedCryptoChampion"]["positiveMajorWindowCount"], 3)
            self.assertEqual(report["observedCryptoChampion"]["majorWindowFailureCount"], 0)
            self.assertEqual(report["observedCryptoChampion"]["pnlUsd"], 65.2172)
            self.assertFalse(report["observedCryptoChampion"]["qualifiedForPromotion"])
            self.assertFalse(report["promotionDecision"]["canRunIsolatedTesterForwardNext"])
            self.assertFalse(report["promotionDecision"]["canPromoteToLiveNow"])
            self.assertIn("ace_candidate_selected", report["blockers"])
            self.assertFalse(report["safety"]["hfmCryptoExecutionAllowed"])

    def test_long_term_memory_blocks_live_promotion_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "case_memory").mkdir(parents=True)
            (runtime / "adaptive").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_AceStrategyScout.json").write_text(
                json.dumps(
                    {
                        "topQualifiedForex": {
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR",
                            "strategyFamily": "RSI_Reversal",
                            "direction": "LONG",
                            "profitFactor": 2.6998,
                            "sharpe": 2.0702,
                            "tradeCount": 18,
                            "walkForwardStability": 0.95,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "forexChampion": {
                            "status": "FOREX_CHAMPION_RETEST_PASS",
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "blockers": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
                json.dumps(
                    {
                        "longTermTradeMemory": {
                            "schema": "quantgod.long_term_trade_memory.v1",
                            "rollingReview": {
                                "status": "COOLDOWN_ACTIVE",
                                "sampleCount": 23,
                                "winRate": 0.6087,
                                "totalProfitR": 0.1032,
                            },
                            "entryFeedbackPolicy": {
                                "status": "MEMORY_ACTIVE_OBSERVE",
                                "candidatePenaltyRules": [
                                    {"match": {"side": "LONG"}, "penalty": 0.05},
                                    {"match": {"dataGap": "dataCoverage"}, "penalty": 0.12},
                                ],
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "adaptive" / "QuantGod_AdaptivePolicy.json").write_text(
                json.dumps(
                    {
                        "routes": [
                            {
                                "symbol": "USDJPYc",
                                "strategy": "RSI_Reversal",
                                "direction": "LONG",
                                "state": "PAUSED",
                                "stateBeforeMemory": "PAUSED",
                                "rawAvgScoreR": -0.0168,
                                "avgScoreR": -0.1868,
                                "memoryPenalty": 0.17,
                                "riskMultiplier": 0,
                                "memoryQualityProfile": {
                                    "dataGaps": [{"gap": "dataCoverage", "count": 5, "ratio": 0.7143}],
                                    "adverseFactors": [],
                                },
                                "memoryFeedback": {
                                    "appliedRules": [
                                        {"match": {"side": "LONG"}, "penalty": 0.05},
                                        {
                                            "match": {"dataGap": "dataCoverage"},
                                            "penalty": 0.12,
                                            "observedCount": 5,
                                            "observedRatio": 0.7143,
                                        },
                                    ]
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_promotion_gate(runtime, write=False)

            review = report["longTermMemoryPromotionReview"]
            self.assertEqual(review["status"], "MEMORY_PROMOTION_BLOCKED")
            self.assertTrue(review["blocksLivePromotion"])
            self.assertEqual(review["matchedRoute"]["state"], "PAUSED")
            self.assertEqual(review["matchedRoute"]["memoryPenalty"], 0.17)
            self.assertEqual(review["qualityProfile"]["dataGaps"][0]["gap"], "dataCoverage")
            self.assertIn("long_term_memory_promotion_guard", report["blockers"])
            self.assertTrue(report["promotionDecision"]["memoryBlocksLivePromotion"])
            self.assertFalse(report["promotionDecision"]["canPromoteToLiveNow"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])

    def test_proxy_entry_memory_quality_blocks_live_promotion_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "case_memory").mkdir(parents=True)
            (runtime / "adaptive").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_AceStrategyScout.json").write_text(
                json.dumps(
                    {
                        "topQualifiedForex": {
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR",
                            "strategyFamily": "RSI_Reversal",
                            "direction": "LONG",
                            "profitFactor": 2.6998,
                            "sharpe": 2.0702,
                            "tradeCount": 18,
                            "walkForwardStability": 0.95,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "forexChampion": {
                            "status": "FOREX_CHAMPION_RETEST_PASS",
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "blockers": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
                json.dumps(
                    {
                        "longTermTradeMemory": {
                            "schema": "quantgod.long_term_trade_memory.v1",
                            "rollingReview": {
                                "status": "READY_TO_ADJUST",
                                "sampleCount": 36,
                                "winRate": 0.61,
                                "totalProfitR": 3.2,
                                "entryMemoryCompleteness": {
                                    "status": "LOW_RAW_COVERAGE",
                                    "overallCoverageRatio": 1.0,
                                    "rawCoverageRatio": 0.0,
                                    "proxyCoverageRatio": 1.0,
                                    "proxySampleCount": 36,
                                    "proxySampleRatio": 1.0,
                                    "qualityGate": {
                                        "rawCoveragePass": False,
                                        "proxySampleRatioPass": False,
                                        "reasonZh": "代理样本可用于研究，但不能作为升实盘/升王牌的完整证据。",
                                    },
                                },
                            },
                            "entryFeedbackPolicy": {
                                "status": "MEMORY_ACTIVE_OBSERVE",
                                "candidatePenaltyRules": [],
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "adaptive" / "QuantGod_AdaptivePolicy.json").write_text(
                json.dumps(
                    {
                        "routes": [
                            {
                                "symbol": "USDJPYc",
                                "strategy": "RSI_Reversal",
                                "direction": "LONG",
                                "state": "ACTIVE",
                                "stateBeforeMemory": "ACTIVE",
                                "rawAvgScoreR": 0.16,
                                "avgScoreR": 0.16,
                                "memoryPenalty": 0,
                                "riskMultiplier": 1,
                                "memoryFeedback": {"appliedRules": []},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_promotion_gate(runtime, write=False)

            review = report["longTermMemoryPromotionReview"]
            self.assertEqual(review["status"], "MEMORY_PROMOTION_BLOCKED")
            self.assertTrue(review["blocksLivePromotion"])
            self.assertTrue(review["entryMemoryCompleteness"]["blocksLivePromotion"])
            self.assertEqual(review["entryMemoryCompleteness"]["rawCoverageRatio"], 0.0)
            self.assertEqual(review["entryMemoryCompleteness"]["proxySampleRatio"], 1.0)
            self.assertIn("long_term_memory_promotion_guard", report["blockers"])
            self.assertTrue(report["promotionDecision"]["memoryBlocksLivePromotion"])
            self.assertFalse(report["promotionDecision"]["canPromoteToLiveNow"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])

    def test_long_term_memory_falls_back_to_symbol_direction_when_family_route_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "case_memory").mkdir(parents=True)
            (runtime / "adaptive").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_AceStrategyScout.json").write_text(
                json.dumps(
                    {
                        "topQualifiedForex": {
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "strategyId": "USDJPY_RSI_REVERSAL_LONG_QUALITY_REPAIR",
                            "strategyFamily": "RSI_Reversal",
                            "direction": "LONG",
                            "profitFactor": 2.6998,
                            "sharpe": 2.0702,
                            "tradeCount": 18,
                            "walkForwardStability": 0.95,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent" / "QuantGod_ChampionRetestReport.json").write_text(
                json.dumps(
                    {
                        "forexChampion": {
                            "status": "FOREX_CHAMPION_RETEST_PASS",
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "blockers": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
                json.dumps(
                    {
                        "longTermTradeMemory": {
                            "schema": "quantgod.long_term_trade_memory.v1",
                            "rollingReview": {
                                "status": "COOLDOWN_ACTIVE",
                                "sampleCount": 36,
                                "winRate": 0.3611,
                                "totalProfitR": -0.2769,
                            },
                            "entryFeedbackPolicy": {
                                "status": "DEFENSE_MODE",
                                "candidatePenaltyRules": [
                                    {"match": {"symbol": "USDJPYc"}, "penalty": 0.05},
                                    {"match": {"side": "LONG"}, "penalty": 0.05},
                                    {"match": {"dataGap": "dataCoverage"}, "penalty": 0.12},
                                ],
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "adaptive" / "QuantGod_AdaptivePolicy.json").write_text(
                json.dumps(
                    {
                        "routes": [
                            {
                                "symbol": "USDJPYc",
                                "strategy": "Manual/Other",
                                "direction": "LONG",
                                "state": "PAUSED",
                                "stateBeforeMemory": "INSUFFICIENT_DATA",
                                "rawAvgScoreR": -0.0081,
                                "avgScoreR": -0.3481,
                                "memoryPenalty": 0.22,
                                "riskMultiplier": 0,
                                "memoryQualityProfile": {
                                    "sampleCount": 16,
                                    "dataGaps": [{"gap": "dataCoverage", "count": 11, "ratio": 0.6875}],
                                },
                                "memoryFeedback": {
                                    "appliedRules": [
                                        {"match": {"symbol": "USDJPYc"}, "penalty": 0.05},
                                        {"match": {"side": "LONG"}, "penalty": 0.05},
                                        {
                                            "match": {"dataGap": "dataCoverage"},
                                            "penalty": 0.12,
                                            "observedCount": 11,
                                            "observedRatio": 0.6875,
                                        },
                                    ]
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_promotion_gate(runtime, write=False)

            review = report["longTermMemoryPromotionReview"]
            self.assertTrue(review["routeMatched"])
            self.assertEqual(review["matchedRoute"]["matchQuality"], "symbol_direction_fallback")
            self.assertEqual(review["matchedRoute"]["strategy"], "Manual/Other")
            self.assertEqual(review["matchedRoute"]["memoryPenalty"], 0.22)
            self.assertEqual(review["status"], "MEMORY_PROMOTION_BLOCKED")
            self.assertIn("long_term_memory_promotion_guard", report["blockers"])

    def test_falls_back_to_repo_runtime_evidence_when_mt5_scope_has_no_ace_scout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mt5_runtime = Path(tmp)
            repo_runtime = Path(__file__).resolve().parents[1] / "runtime"
            repo_ace = json.loads((repo_runtime / "agent" / "QuantGod_AceStrategyScout.json").read_text(encoding="utf-8"))
            expected_seed = repo_ace["topQualifiedForex"]["seedId"]

            report = build_champion_promotion_gate(mt5_runtime, write=False)

            self.assertTrue(report["evidenceRuntimeFallbackUsed"])
            self.assertEqual(report["selectedChampion"]["seedId"], expected_seed)
            self.assertIn(report["status"], {"READY_FOR_ISOLATED_TESTER_FORWARD", "WAITING_ISOLATED_TESTER_FORWARD_REPORT"})
            self.assertFalse(report["promotionDecision"]["canPromoteToLiveNow"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])


if __name__ == "__main__":
    unittest.main()
