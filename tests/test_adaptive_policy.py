from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.adaptive_policy.policy_engine import build_adaptive_policy
from tools.adaptive_policy.telegram_text import build_policy_telegram_text


def _write_long_term_memory_feedback(runtime: Path, *, include_exits: bool = False) -> None:
    out = runtime / "case_memory"
    out.mkdir(parents=True, exist_ok=True)
    exit_memory = []
    if include_exits:
        for index in range(12):
            profit_r = -0.2 if index < 7 else 0.35
            exit_memory.append(
                {
                    "schema": "quantgod.trade_exit_memory.v1",
                    "tradeId": f"M-{index + 1:03d}",
                    "exitTime": f"2099-01-01T01:{index:02d}:00Z",
                    "symbol": "USDJPYc",
                    "side": "LONG",
                    "strategyVersion": "MEMORY_ROUTE_V1",
                    "profitR": profit_r,
                    "pnlPercent": profit_r * 100,
                    "mfeR": 1.1 if profit_r > 0 else 0.25,
                    "maeR": 0.3 if profit_r > 0 else 1.0,
                    "givebackR": 0.15 if profit_r > 0 else 0.0,
                    "capturedMfeRatio": 0.6 if profit_r > 0 else 0.0,
                    "exitType": "LOSS_EXIT" if profit_r < 0 else "PROFIT_EXIT",
                    "lossTags": ["LOW_COVERAGE_LOSS"] if profit_r < 0 else [],
                    "exitQualityTags": ["HELD_WINNER_WELL"] if profit_r > 0 else [],
                }
            )
    (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
        json.dumps(
            {
                "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                "longTermTradeMemory": {
                    "schema": "quantgod.long_term_trade_memory.v1",
                    "generatedAt": "2099-01-01T00:00:00Z",
                    "status": "READY_TO_ADJUST",
                    "exitMemory": exit_memory,
                    "rollingReview": {
                        "status": "READY_TO_ADJUST",
                        "sampleCount": 12,
                        "winRate": 0.35,
                        "totalProfitR": -1.2,
                    },
                    "entryFeedbackPolicy": {
                        "schema": "quantgod.entry_feedback_policy.v1",
                        "status": "DEFENSE_MODE",
                        "sampleCount": 12,
                        "candidatePenaltyRules": [
                            {
                                "match": {"symbol": "USDJPYc"},
                                "penalty": 0.08,
                                "reasonZh": "USDJPYc 近期拖累，下一轮候选扣分。",
                            },
                            {
                                "match": {"side": "LONG"},
                                "penalty": 0.12,
                                "reasonZh": "LONG 近期弱，降低这一侧进攻欲望。",
                            },
                            {
                                "match": {"dataGap": "dataCoverage"},
                                "penalty": 0.15,
                                "reasonZh": "低覆盖亏损偏多，提高覆盖门槛。",
                            },
                        ],
                        "defenseMode": {
                            "enabled": True,
                            "riskMultiplierCap": 0.25,
                            "entryScoreBufferAdd": 0.05,
                            "reasonZh": "测试防守模式。",
                        },
                        "aggressionControl": {"manualAggressiveTierPreserved": True},
                        "tpSlGuidance": {"mode": "DEFENSIVE_TP_SL_REVIEW"},
                    },
                    "nextActionZh": "长期记忆测试扣分。",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class AdaptivePolicyTests(unittest.TestCase):
    def _runtime(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="qg_adaptive_policy_"))
        (root / "journal").mkdir(parents=True, exist_ok=True)
        snapshot = {
            "schema": "quantgod.mt5.runtime_snapshot.v1",
            "source": "hfm_ea_runtime",
            "generatedAt": "2099-01-01T00:00:00Z",
            "symbol": "USDJPYc",
            "fallback": False,
            "runtimeAgeSeconds": 1,
            "current_price": {"bid": 155.10, "ask": 155.12, "spread": 0.02, "timeIso": "2099-01-01T00:00:00Z"},
            "safety": {"readOnly": True, "orderSendAllowed": False}
        }
        (root / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json").write_text(json.dumps(snapshot), encoding="utf-8")
        with (root / "ShadowCandidateOutcomeLedger.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["symbol", "strategy", "direction", "regime", "scoreR", "mfe", "mae", "spread"])
            writer.writeheader()
            for _ in range(7):
                writer.writerow({"symbol": "USDJPYc", "strategy": "RSI_Reversal", "direction": "BUY", "regime": "TREND_EXP_DOWN", "scoreR": "0.35", "mfe": "1.2", "mae": "0.4", "spread": "0.02"})
            for _ in range(7):
                writer.writerow({"symbol": "USDJPYc", "strategy": "RSI_Reversal", "direction": "SELL", "regime": "RANGE", "scoreR": "-0.40", "mfe": "0.2", "mae": "1.1", "spread": "0.02"})
        with (root / "QuantGod_StrategyEvaluationReport.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["symbol", "ATR", "ADX", "BBWidth"])
            writer.writeheader()
            writer.writerow({"symbol": "USDJPYc", "ATR": "1.0", "ADX": "20", "BBWidth": "0.01"})
        return root

    def test_scores_buy_active_and_sell_paused(self):
        runtime = self._runtime()
        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=True)
        routes = policy["routes"]
        buy = [r for r in routes if r["direction"] == "LONG"][0]
        sell = [r for r in routes if r["direction"] == "SHORT"][0]
        self.assertEqual(buy["state"], "ACTIVE_SHADOW_OK")
        self.assertEqual(sell["state"], "PAUSED")
        self.assertGreater(buy["winRate"], 0.9)

    def test_long_term_memory_feedback_demotes_and_caps_active_route(self):
        runtime = self._runtime()
        _write_long_term_memory_feedback(runtime)

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)

        self.assertTrue(policy["longTermMemoryFeedback"]["memoryFound"])
        buy = [r for r in policy["routes"] if r["direction"] == "LONG"][0]
        self.assertEqual(buy["stateBeforeMemory"], "ACTIVE_SHADOW_OK")
        self.assertEqual(buy["state"], "WATCH_ONLY")
        self.assertGreater(buy["rawAvgScoreR"], buy["avgScoreR"])
        self.assertAlmostEqual(buy["memoryPenalty"], 0.2)
        self.assertLessEqual(buy["riskMultiplier"], 0.25)
        self.assertTrue(buy["memoryFeedback"]["defenseModeEnabled"])
        self.assertEqual(len(buy["memoryFeedback"]["appliedRules"]), 2)
        gate = policy["entryGates"][0]
        history_check = [item for item in gate["checks"] if item["name"] == "历史方向"][0]
        self.assertTrue(history_check["passed"])
        self.assertIn("长期记忆扣分", history_check["reason"])
        self.assertFalse(policy["safety"]["orderSendAllowed"])

    def test_long_term_memory_exit_memory_can_seed_routes_when_outcome_ledger_missing(self):
        runtime = self._runtime()
        (runtime / "ShadowCandidateOutcomeLedger.csv").unlink()
        _write_long_term_memory_feedback(runtime, include_exits=True)

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)

        self.assertEqual(policy["longTermMemoryFeedback"]["memoryObservationCount"], 12)
        self.assertEqual(policy["longTermMemoryFeedback"]["memoryObservationSource"], "exitMemory")
        routes = policy["routes"]
        self.assertTrue(routes)
        route = routes[0]
        self.assertEqual(route["symbol"], "USDJPYc")
        self.assertEqual(route["direction"], "LONG")
        self.assertTrue(route["memoryFeedback"]["applied"])
        applied_matches = [item["match"] for item in route["memoryFeedback"]["appliedRules"]]
        self.assertIn({"dataGap": "dataCoverage"}, applied_matches)
        self.assertTrue(route["memoryQualityProfile"]["dataGaps"])
        self.assertLess(route["avgScoreR"], route["rawAvgScoreR"])
        plan = policy["dynamicSltpPlans"][0]
        self.assertGreater(plan["sampleCount"], 0)
        self.assertGreater(plan["targets"][0]["value"], 0)
        self.assertGreater(plan["initialStop"]["value"], 0)
        self.assertFalse(policy["safety"]["writesMt5OrderRequest"])

    def test_dynamic_sltp_uses_close_move_bridge_when_mfe_mae_missing(self):
        runtime = self._runtime()
        (runtime / "ShadowCandidateOutcomeLedger.csv").unlink()
        out = runtime / "case_memory"
        out.mkdir(parents=True, exist_ok=True)
        review_exits = []
        for index in range(12):
            win = index >= 6
            close_move_r = 0.018 if win else -0.004
            review_exits.append(
                {
                    "schema": "quantgod.trade_exit_memory.v1",
                    "tradeId": f"CLOSEMOVE-{index:03d}",
                    "exitTime": f"2099-01-01T02:{index:02d}:00Z",
                    "symbol": "USDJPYc",
                    "side": "LONG",
                    "strategyVersion": "CLOSE_MOVE_ROUTE_V1",
                    "profitR": 0.18 if win else -0.12,
                    "pnlPercent": 18 if win else -12,
                    "mfeR": 0.0,
                    "maeR": 0.0,
                    "mfeMaeAvailable": False,
                    "movementQuality": "BRIDGED_CLOSE_MOVE_ONLY",
                    "closeMove": {
                        "available": True,
                        "closeMoveR": close_move_r,
                        "favorablePriceMovePips": close_move_r * 8,
                        "plannedStopPips": 8,
                        "plannedTakeProfitPips": 12,
                    },
                    "exitType": "PROFIT_EXIT" if win else "LOSS_EXIT",
                    "lossTags": ["LOW_COVERAGE_LOSS"] if not win else [],
                    "exitQualityTags": [],
                }
            )
        (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps(
                {
                    "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                    "longTermTradeMemory": {
                        "schema": "quantgod.long_term_trade_memory.v1",
                        "status": "READY_TO_ADJUST",
                        "reviewExitMemory": review_exits,
                        "rollingReview": {
                            "status": "READY_TO_ADJUST",
                            "sampleCount": 12,
                            "winRate": 0.5,
                            "totalProfitR": 0.36,
                        },
                        "entryFeedbackPolicy": {
                            "status": "MEMORY_ACTIVE_OBSERVE",
                            "sampleCount": 12,
                            "candidatePenaltyRules": [],
                            "defenseMode": {"enabled": False},
                            "tpSlGuidance": {
                                "mode": "DEFENSIVE_TP_SL_REVIEW",
                                "exitEfficiency": {
                                    "closeMoveAvailableCount": 12,
                                    "closeMoveBridgeOnlyCount": 12,
                                    "mfeMaeAvailableCount": 0,
                                },
                            },
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)

        self.assertEqual(policy["longTermMemoryFeedback"]["memoryObservationSource"], "reviewExitMemory")
        plan = policy["dynamicSltpPlans"][0]
        self.assertTrue(plan["movementEvidence"]["closeMoveFallbackUsed"])
        self.assertEqual(plan["movementEvidence"]["closeMoveSampleCount"], 12)
        self.assertTrue(plan["movementEvidence"]["fallbackFloorApplied"])
        self.assertEqual(plan["movementEvidence"]["fallbackQuality"], "CLOSE_MOVE_BRIDGE_ONLY")
        self.assertLess(plan["movementEvidence"]["fallbackPreFloor"]["stop"], 0.55)
        self.assertGreaterEqual(plan["initialStop"]["value"], 0.55)
        self.assertGreaterEqual(plan["targets"][0]["value"], 0.35)
        self.assertGreaterEqual(plan["targets"][1]["value"], 0.70)
        self.assertGreaterEqual(plan["targets"][2]["value"], 1.00)
        self.assertIn("close-move", plan["basis"])
        self.assertIn("安全地板", plan["basis"])
        self.assertEqual(plan["memoryTpSlOverlay"]["exitEfficiencyCounts"]["closeMoveBridgeOnlyCount"], 12)

    def test_long_term_memory_review_exit_memory_feeds_routes_before_raw_recent_noise(self):
        runtime = self._runtime()
        (runtime / "ShadowCandidateOutcomeLedger.csv").unlink()
        out = runtime / "case_memory"
        out.mkdir(parents=True, exist_ok=True)
        raw_noise = [
            {
                "schema": "quantgod.trade_exit_memory.v1",
                "tradeId": f"RAW-{index:03d}",
                "exitTime": f"2099-01-01T00:{index:02d}:00Z",
                "symbol": "USDJPYc",
                "side": "UNKNOWN",
                "strategyVersion": "RAW_SHADOW_NOISE",
                "profitR": 0,
                "mfeR": 1.0,
                "maeR": 1.0,
                "exitType": "FLAT_EXIT",
                "lossTags": [],
                "exitQualityTags": [],
            }
            for index in range(20)
        ]
        review_exits = [
            {
                "schema": "quantgod.trade_exit_memory.v1",
                "tradeId": f"REV-{index:03d}",
                "exitTime": f"2099-01-01T01:{index:02d}:00Z",
                "symbol": "USDJPYc",
                "side": "SHORT",
                "strategyVersion": "REVIEW_ROUTE_V1",
                "profitR": 0.28,
                "pnlPercent": 28,
                "mfeR": 0.9,
                "maeR": 0.25,
                "exitType": "PROFIT_EXIT",
                "lossTags": [],
                "exitQualityTags": ["HELD_WINNER_WELL"],
            }
            for index in range(12)
        ]
        (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps(
                {
                    "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                    "longTermTradeMemory": {
                        "schema": "quantgod.long_term_trade_memory.v1",
                        "status": "READY_TO_ADJUST",
                        "exitMemory": raw_noise,
                        "reviewExitMemory": review_exits,
                        "rollingReview": {
                            "status": "READY_TO_ADJUST",
                            "sampleCount": 12,
                            "winRate": 1.0,
                            "totalProfitR": 3.36,
                        },
                        "entryFeedbackPolicy": {
                            "status": "MEMORY_ACTIVE_OBSERVE",
                            "sampleCount": 12,
                            "candidatePenaltyRules": [],
                            "defenseMode": {"enabled": False},
                            "tpSlGuidance": {"mode": "OBSERVE"},
                        },
                        "nextActionZh": "reviewExitMemory 应优先反哺开仓。",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)

        self.assertEqual(policy["longTermMemoryFeedback"]["memoryObservationSource"], "reviewExitMemory")
        self.assertEqual(policy["longTermMemoryFeedback"]["memoryObservationCount"], 12)
        short_routes = [route for route in policy["routes"] if route["direction"] == "SHORT"]
        self.assertTrue(short_routes)
        self.assertGreater(short_routes[0]["memoryQualityProfile"]["sampleCount"], 0)
        plan = policy["dynamicSltpPlans"][0]
        self.assertEqual(plan["direction"], "SHORT")
        self.assertGreaterEqual(plan["sampleCount"], 12)

    def test_long_term_memory_exit_quality_tightens_dynamic_sltp_overlay(self):
        runtime = self._runtime()
        (runtime / "ShadowCandidateOutcomeLedger.csv").unlink()
        out = runtime / "case_memory"
        out.mkdir(parents=True, exist_ok=True)
        review_exits = [
            {
                "schema": "quantgod.trade_exit_memory.v1",
                "tradeId": f"REV-{index:03d}",
                "exitTime": f"2099-01-01T01:{index:02d}:00Z",
                "symbol": "USDJPYc",
                "side": "LONG",
                "strategyVersion": "MEMORY_TPSL_ROUTE_V1",
                "profitR": 0.12,
                "pnlPercent": 12,
                "mfeR": 1.2,
                "maeR": 0.3,
                "givebackR": 1.08,
                "capturedMfeRatio": 0.1,
                "exitType": "TRAILING_TAKE_PROFIT",
                "lossTags": [],
                "exitQualityTags": ["PROFIT_GIVEBACK", "LOW_MFE_CAPTURE", "RECOVERED_TO_SMALL_WIN"],
            }
            for index in range(12)
        ]
        (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps(
                {
                    "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                    "longTermTradeMemory": {
                        "schema": "quantgod.long_term_trade_memory.v1",
                        "status": "READY_TO_ADJUST",
                        "reviewExitMemory": review_exits,
                        "rollingReview": {
                            "status": "READY_TO_ADJUST",
                            "sampleCount": 12,
                            "winRate": 1.0,
                            "totalProfitR": 1.44,
                        },
                        "entryFeedbackPolicy": {
                            "status": "DEFENSE_MODE",
                            "sampleCount": 12,
                            "candidatePenaltyRules": [],
                            "adverseFactorPenalties": [
                                {"factor": "executionRisk", "lossTag": "HIGH_EXECUTION_RISK", "lossCount": 3}
                            ],
                            "defenseMode": {"enabled": True, "riskMultiplierCap": 0.3, "entryScoreBufferAdd": 0.08},
                            "tpSlGuidance": {
                                "mode": "DEFENSIVE_TP_SL_REVIEW",
                                "actionsZh": ["MFE 捕获率偏低，TP1 应更早落袋。"],
                                "exitEfficiency": {
                                    "profitGivebackCount": 12,
                                    "lowMfeCaptureCount": 12,
                                    "recoveredSmallWinCount": 12,
                                    "heldWinnerWellCount": 0,
                                },
                            },
                        },
                        "nextActionZh": "长期记忆要求收紧动态止盈止损。",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        route = [r for r in policy["routes"] if r["direction"] == "LONG"][0]
        plan = policy["dynamicSltpPlans"][0]

        self.assertEqual(route["memoryQualityProfile"]["exitQualityPatterns"][0]["tag"], "PROFIT_GIVEBACK")
        overlay = plan["memoryTpSlOverlay"]
        self.assertTrue(overlay["applied"])
        self.assertTrue(overlay["earlyProfitTaking"])
        self.assertTrue(overlay["tightenTrailing"])
        self.assertTrue(overlay["tightenStop"])
        self.assertEqual(plan["riskMode"], "记忆防守")
        self.assertLess(plan["targets"][0]["value"], 1.2)
        self.assertEqual(plan["trailing"]["breakevenAtR"], 0.55)
        self.assertEqual(plan["trailing"]["givebackPct"], 0.32)
        self.assertFalse(policy["safety"]["orderSendAllowed"])

    def test_long_term_memory_data_gap_rule_penalizes_low_coverage_route(self):
        runtime = self._runtime()
        with (runtime / "ShadowCandidateOutcomeLedger.csv").open("w", encoding="utf-8", newline="") as handle:
            fields = [
                "symbol",
                "strategy",
                "direction",
                "regime",
                "scoreR",
                "mfe",
                "mae",
                "spread",
                "dataCoverageScore",
                "professionalScore",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for _ in range(7):
                writer.writerow({
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "direction": "BUY",
                    "regime": "TREND_EXP_DOWN",
                    "scoreR": "0.35",
                    "mfe": "1.2",
                    "mae": "0.4",
                    "spread": "0.02",
                    "dataCoverageScore": "0.42",
                    "professionalScore": "0.91",
                })
        out = runtime / "case_memory"
        out.mkdir(parents=True, exist_ok=True)
        (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps({
                "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                "longTermTradeMemory": {
                    "schema": "quantgod.long_term_trade_memory.v1",
                    "status": "READY_TO_ADJUST",
                    "rollingReview": {"status": "READY_TO_ADJUST", "sampleCount": 12},
                    "entryFeedbackPolicy": {
                        "status": "MEMORY_ACTIVE_OBSERVE",
                        "sampleCount": 12,
                        "candidatePenaltyRules": [{
                            "match": {"dataGap": "dataCoverage"},
                            "penalty": 0.15,
                            "reasonZh": "低覆盖亏损偏多，提高覆盖门槛。",
                        }],
                        "defenseMode": {"enabled": False},
                    },
                    "nextActionZh": "长期记忆测试低覆盖扣分。",
                },
            }),
            encoding="utf-8",
        )

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        buy = [r for r in policy["routes"] if r["direction"] == "LONG"][0]

        self.assertEqual(buy["stateBeforeMemory"], "ACTIVE_SHADOW_OK")
        self.assertEqual(buy["memoryPenalty"], 0.15)
        self.assertEqual(buy["memoryQualityProfile"]["dataGaps"][0]["gap"], "dataCoverage")
        self.assertEqual(buy["memoryFeedback"]["appliedRules"][0]["observedCount"], 7)
        self.assertLess(buy["avgScoreR"], buy["rawAvgScoreR"])

    def test_long_term_memory_adverse_factor_rule_penalizes_matching_route(self):
        runtime = self._runtime()
        with (runtime / "ShadowCandidateOutcomeLedger.csv").open("w", encoding="utf-8", newline="") as handle:
            fields = ["symbol", "strategy", "direction", "regime", "scoreR", "mfe", "mae", "spread", "newsScore"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for _ in range(7):
                writer.writerow({
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "direction": "SELL",
                    "regime": "RANGE",
                    "scoreR": "0.32",
                    "mfe": "0.8",
                    "mae": "0.2",
                    "spread": "0.02",
                    "newsScore": "-0.4",
                })
        out = runtime / "case_memory"
        out.mkdir(parents=True, exist_ok=True)
        (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps({
                "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                "longTermTradeMemory": {
                    "schema": "quantgod.long_term_trade_memory.v1",
                    "status": "READY_TO_ADJUST",
                    "rollingReview": {"status": "READY_TO_ADJUST", "sampleCount": 12},
                    "entryFeedbackPolicy": {
                        "status": "MEMORY_ACTIVE_OBSERVE",
                        "sampleCount": 12,
                        "candidatePenaltyRules": [{
                            "match": {"adverseFactor": "news"},
                            "penalty": 0.11,
                            "reasonZh": "新闻逆风亏损重复，新闻分低时降权。",
                        }],
                        "defenseMode": {"enabled": False},
                    },
                    "nextActionZh": "长期记忆测试新闻逆风扣分。",
                },
            }),
            encoding="utf-8",
        )

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        sell = [r for r in policy["routes"] if r["direction"] == "SHORT"][0]

        self.assertEqual(sell["memoryPenalty"], 0.11)
        self.assertEqual(sell["memoryQualityProfile"]["adverseFactors"][0]["factor"], "news")
        self.assertEqual(sell["memoryFeedback"]["appliedRules"][0]["observedCount"], 7)

    def test_long_term_memory_missing_fine_factor_rule_penalizes_matching_route(self):
        runtime = self._runtime()
        with (runtime / "ShadowCandidateOutcomeLedger.csv").open("w", encoding="utf-8", newline="") as handle:
            fields = ["symbol", "strategy", "direction", "regime", "scoreR", "mfe", "mae", "spread", "newsScore"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for _ in range(7):
                writer.writerow({
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "direction": "SELL",
                    "regime": "RANGE",
                    "scoreR": "0.32",
                    "mfe": "0.8",
                    "mae": "0.2",
                    "spread": "0.02",
                    "newsScore": "0.2",
                })
        out = runtime / "case_memory"
        out.mkdir(parents=True, exist_ok=True)
        (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps({
                "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                "longTermTradeMemory": {
                    "schema": "quantgod.long_term_trade_memory.v1",
                    "status": "READY_TO_ADJUST",
                    "rollingReview": {"status": "READY_TO_ADJUST", "sampleCount": 12},
                    "entryFeedbackPolicy": {
                        "status": "MEMORY_ACTIVE_OBSERVE",
                        "sampleCount": 12,
                        "candidatePenaltyRules": [{
                            "match": {"dataGap": "missingFactor:predictionMarket"},
                            "penalty": 0.09,
                            "reasonZh": "predictionMarket 细因子缺失亏损重复，信息不完整信号降权。",
                        }],
                        "defenseMode": {"enabled": False},
                    },
                    "nextActionZh": "长期记忆测试细因子缺失扣分。",
                },
            }),
            encoding="utf-8",
        )

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        sell = [r for r in policy["routes"] if r["direction"] == "SHORT"][0]

        self.assertEqual(sell["memoryPenalty"], 0.09)
        self.assertTrue(
            any(item["gap"] == "missingFactor:predictionMarket" for item in sell["memoryQualityProfile"]["dataGaps"])
        )
        self.assertEqual(sell["memoryFeedback"]["appliedRules"][0]["observedCount"], 7)

    def test_auto_generated_raw_missing_fine_factor_rule_penalizes_route(self):
        runtime = self._runtime()
        with (runtime / "ShadowCandidateOutcomeLedger.csv").open("w", encoding="utf-8", newline="") as handle:
            fields = ["symbol", "strategy", "direction", "regime", "scoreR", "mfe", "mae", "spread", "newsScore"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for _ in range(7):
                writer.writerow({
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "direction": "SELL",
                    "regime": "RANGE",
                    "scoreR": "0.32",
                    "mfe": "0.8",
                    "mae": "0.2",
                    "spread": "0.02",
                    "newsScore": "0.2",
                })
        out = runtime / "case_memory"
        out.mkdir(parents=True, exist_ok=True)
        (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps({
                "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                "longTermTradeMemory": {
                    "schema": "quantgod.long_term_trade_memory.v1",
                    "status": "READY_TO_ADJUST",
                    "rollingReview": {"status": "READY_TO_ADJUST", "sampleCount": 12},
                    "entryFeedbackPolicy": {
                        "status": "MEMORY_ACTIVE_OBSERVE",
                        "sampleCount": 12,
                        "fineFactorPenalties": [{
                            "factor": "kronos",
                            "dataGap": "missingFactor:kronos",
                            "lossTag": "FINE_FACTOR_kronos_RAW_MISSING",
                            "lossCount": 6,
                            "penalty": 0.08,
                            "reasonZh": "kronos 细因子缺少原始开仓快照。",
                        }],
                        "candidatePenaltyRules": [{
                            "match": {"dataGap": "missingFactor:kronos"},
                            "penalty": 0.08,
                            "reasonZh": "kronos 细因子缺少原始开仓快照。",
                        }],
                        "defenseMode": {"enabled": False},
                    },
                    "nextActionZh": "长期记忆测试自动生成 raw missing 细因子扣分。",
                },
            }),
            encoding="utf-8",
        )

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        sell = [r for r in policy["routes"] if r["direction"] == "SHORT"][0]

        self.assertEqual(sell["memoryPenalty"], 0.08)
        self.assertTrue(any(item["gap"] == "missingFactor:kronos" for item in sell["memoryQualityProfile"]["dataGaps"]))
        self.assertEqual(sell["memoryFeedback"]["appliedRules"][0]["match"], {"dataGap": "missingFactor:kronos"})

    def test_missing_fine_factor_penalties_are_group_capped(self):
        runtime = self._runtime()
        with (runtime / "ShadowCandidateOutcomeLedger.csv").open("w", encoding="utf-8", newline="") as handle:
            fields = ["symbol", "strategy", "direction", "regime", "scoreR", "mfe", "mae", "spread"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for _ in range(7):
                writer.writerow({
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "direction": "SELL",
                    "regime": "RANGE",
                    "scoreR": "0.50",
                    "mfe": "0.8",
                    "mae": "0.2",
                    "spread": "0.02",
                })
        out = runtime / "case_memory"
        out.mkdir(parents=True, exist_ok=True)
        rules = [
            {
                "match": {"dataGap": f"missingFactor:{factor}"},
                "penalty": 0.079,
                "reasonZh": f"{factor} 缺少原始开仓快照。",
            }
            for factor in ["atr", "entryTiming", "executionRisk", "fundFlow", "kronos", "news"]
        ]
        (out / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps({
                "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                "longTermTradeMemory": {
                    "schema": "quantgod.long_term_trade_memory.v1",
                    "status": "READY_TO_ADJUST",
                    "rollingReview": {"status": "READY_TO_ADJUST", "sampleCount": 12},
                    "entryFeedbackPolicy": {
                        "status": "MEMORY_ACTIVE_OBSERVE",
                        "sampleCount": 12,
                        "candidatePenaltyRules": rules,
                        "defenseMode": {"enabled": False},
                    },
                    "nextActionZh": "长期记忆测试 missing fine factor cap。",
                },
            }),
            encoding="utf-8",
        )

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        sell = [r for r in policy["routes"] if r["direction"] == "SHORT"][0]
        breakdown = sell["memoryFeedback"]["penaltyBreakdown"]

        self.assertEqual(breakdown["missingFineFactorRuleCount"], 6)
        self.assertGreater(breakdown["missingFineFactorRawPenalty"], breakdown["missingFineFactorAppliedPenalty"])
        self.assertEqual(breakdown["missingFineFactorAppliedPenalty"], 0.24)
        self.assertEqual(sell["memoryPenalty"], 0.24)

    def test_entry_gate_and_sltp_plan_are_written(self):
        runtime = self._runtime()
        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=True)
        self.assertTrue((runtime / "adaptive" / "QuantGod_AdaptivePolicy.json").exists())
        self.assertTrue((runtime / "adaptive" / "QuantGod_DynamicEntryGate.json").exists())
        self.assertTrue((runtime / "adaptive" / "QuantGod_DynamicSLTPPlan.json").exists())
        self.assertTrue(policy["entryGates"][0]["runtimeFresh"])
        self.assertFalse(policy["entryGates"][0]["fallback"])

    def test_entry_gate_blocks_abnormally_wide_spread_against_history(self):
        runtime = self._runtime()
        snapshot_path = runtime / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["current_price"]["spread"] = 0.20
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        spread_check = [item for item in policy["entryGates"][0]["checks"] if item["name"] == "点差"][0]

        self.assertFalse(spread_check["passed"])
        self.assertIn("历史中位点差", spread_check["reason"])

    def test_entry_gate_blocks_degraded_fastlane_quality(self):
        runtime = self._runtime()
        quality_dir = runtime / "quality"
        quality_dir.mkdir(parents=True, exist_ok=True)
        (quality_dir / "QuantGod_MT5FastLaneQuality.json").write_text(json.dumps({
            "schema": "quantgod.mt5.fast_lane_quality.v1",
            "heartbeatFresh": True,
            "heartbeatAgeSeconds": 1,
            "symbols": [{
                "symbol": "USDJPYc",
                "quality": "DEGRADED",
                "tickAgeSeconds": 20,
                "indicatorAgeSeconds": 30,
                "spreadPoints": 2.0,
            }],
            "safety": {"readOnlyDataPlane": True, "orderSendAllowed": False},
        }), encoding="utf-8")

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        fastlane_check = [item for item in policy["entryGates"][0]["checks"] if item["name"] == "快通道"][0]

        self.assertFalse(fastlane_check["passed"])
        self.assertFalse(policy["entryGates"][0]["passed"])
        self.assertIn("快通道降级", fastlane_check["reason"])

    def test_empty_fastlane_uses_fresh_hfm_dashboard_fallback(self):
        runtime = self._runtime()
        (runtime / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json").unlink()
        (runtime / "QuantGod_StrategyEvaluationReport.csv").write_text(
            "ReportTimeLocal,Symbol,Strategy,ATRPips,ADX,BBWidthPips,TickAgeSeconds,SpreadPips\n"
            "2026.05.06 14:00:00,USDJPYc,RSI_Reversal,0,0,0,0,2.6\n",
            encoding="utf-8",
        )
        (runtime / "QuantGod_Dashboard.json").write_text(json.dumps({
            "watchlist": "USDJPYc",
            "runtime": {"tradeStatus": "READY", "executionEnabled": True, "readOnlyMode": False, "tickAgeSeconds": 0},
            "market": {"symbol": "USDJPYc", "bid": 155.71, "ask": 155.74, "spread": 0.02},
        }), encoding="utf-8")
        quality_dir = runtime / "quality"
        quality_dir.mkdir(parents=True, exist_ok=True)
        (quality_dir / "QuantGod_MT5FastLaneQuality.json").write_text(json.dumps({
            "schema": "quantgod.mt5.fastlane.quality.v1",
            "heartbeatFound": False,
            "heartbeatFresh": False,
            "symbols": [{"symbol": "USDJPYc", "quality": "DEGRADED", "tickRows": 0, "tickAgeSeconds": None, "indicatorAgeSeconds": None}],
        }), encoding="utf-8")

        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        gate = policy["entryGates"][0]
        checks = {item["name"]: item for item in gate["checks"]}

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["snapshotSource"], "hfm_ea_dashboard")
        self.assertIn("Dashboard", checks["快通道"]["reason"])
        self.assertIn("降级", checks["指标"]["reason"])

    def test_telegram_text_is_chinese_and_read_only(self):
        runtime = self._runtime()
        policy = build_adaptive_policy(runtime, symbols=["USDJPYc"], write=False)
        text = build_policy_telegram_text(policy)
        self.assertIn("自适应策略审查", text)
        self.assertIn("买入观察", text)
        self.assertIn("暂停", text)
        self.assertIn("不会下单", text)
        self.assertNotIn("orderSendAllowed=true", text)

if __name__ == "__main__":
    unittest.main()
