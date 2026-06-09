from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.autonomous_lifecycle.cent_account_rules import cent_account_config
from tools.autonomous_lifecycle.hfm_crypto_shadow_lane import build_hfm_crypto_shadow_lane
from tools.autonomous_lifecycle.lifecycle import build_autonomous_lifecycle
from tools.autonomous_lifecycle.mt5_shadow_lane import build_mt5_shadow_lane
from tools.daily_autopilot_v2.orchestrator import run_daily_autopilot_cycle
from tools.daily_autopilot_v2.report import build_daily_autopilot_v2
from tools.daily_autopilot_v2.telegram_text import daily_autopilot_v2_to_chinese_text
from tools.usdjpy_strategy_lab.schema import DEFAULT_STRATEGIES
from tools.usdjpy_walk_forward.selector import sample_walk_forward_runtime
from tools.hfm_crypto_cfd.schema import filled_contract_spec_path


class AutonomousLifecycleTests(unittest.TestCase):
    def test_builds_three_lane_lifecycle_without_trade_rights(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            sample_walk_forward_runtime(runtime, overwrite=True)

            payload = build_autonomous_lifecycle(runtime, write=True)

            self.assertEqual(payload["symbol"], "USDJPYc")
            self.assertEqual(payload["lanes"]["live"]["strategy"], "RSI_Reversal")
            self.assertEqual(payload["lanes"]["live"]["direction"], "LONG")
            self.assertIn("accountRegistry", payload)
            self.assertEqual(payload["accountRegistry"]["spreadPolicy"]["normalLimitPips"], 2.2)
            self.assertEqual(payload["lanes"]["centLive"]["accountMode"], "cent")
            self.assertEqual(payload["lanes"]["usdDeployment"]["accountMode"], "standard_usd")
            self.assertEqual(payload["lanes"]["usdDeployment"]["defaultStage"], "USD_PAPER_MIRROR")
            self.assertTrue(payload["lanes"]["globalUsdJpyExposureGuard"]["usdAccountPriority"])
            self.assertFalse(payload["safety"]["orderSendAllowed"])
            self.assertFalse(payload["safety"]["operatorApprovalRequired"])
            self.assertTrue(payload["safety"]["unattendedLiveExpansionAllowed"])
            self.assertFalse(payload["safety"]["liveMutationAllowed"])
            self.assertFalse(payload["safety"]["externalMarketRealMoneyAllowed"])
            self.assertFalse(payload["safety"]["hfmCryptoExecutionAllowed"])
            self.assertIn("mt5Shadow", payload["lanes"])
            self.assertIn("hfmCryptoShadow", payload["lanes"])
            self.assertTrue((runtime / "agent" / "QuantGod_AutonomousLifecycle.json").exists())
            self.assertTrue((runtime / "agent" / "QuantGod_MT5ShadowStrategyRanking.json").exists())
            self.assertTrue((runtime / "agent" / "QuantGod_HFMCryptoShadowLane.json").exists())

    def test_lifecycle_can_read_hfm_crypto_from_separate_live16_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            primary = Path(temp) / "primary"
            secondary = Path(temp) / "live16"
            primary.mkdir()
            filled_spec = filled_contract_spec_path(secondary)
            filled_spec.parent.mkdir(parents=True)
            filled_spec.write_text(
                json.dumps(
                    {
                        "symbols": [
                            {
                                "brokerSymbol": "#BTCUSD",
                                "canonicalSymbol": "BTCUSD",
                                "contractSize": 1,
                                "tickSize": 0.01,
                                "tickValue": 0.01,
                                "minLot": 0.01,
                                "lotStep": 0.01,
                                "maxLot": 3,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = build_autonomous_lifecycle(primary, hfm_crypto_runtime_dir=secondary, write=False)

            hfm_lane = payload["lanes"]["hfmCryptoShadow"]
            self.assertEqual(payload["runtimeDir"], str(primary))
            self.assertEqual(payload["hfmCryptoRuntimeDir"], str(secondary))
            self.assertTrue(hfm_lane["summary"]["symbolEvidenceFound"])
            self.assertEqual(hfm_lane["hfmCryptoCfdState"]["targetSymbols"], ["BTCUSD"])
            self.assertFalse(hfm_lane["safety"]["mt5OrderSendAllowed"])

    def test_mt5_shadow_lane_keeps_all_default_strategies_in_simulation_pool(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)

            payload = build_mt5_shadow_lane(runtime)

            self.assertEqual(payload["lane"], "MT5_SHADOW")
            self.assertFalse(payload["safety"]["liveEligible"])
            self.assertTrue(payload["safety"]["liveEligibleAfterStageGates"])
            self.assertFalse(payload["safety"]["operatorApprovalRequired"])
            self.assertEqual(set(payload["strategyPool"]), set(DEFAULT_STRATEGIES))
            route_strategies = {row["strategy"] for row in payload["routes"]}
            self.assertTrue(set(DEFAULT_STRATEGIES).issubset(route_strategies))

    def test_parity_fail_blocks_rsi_long_from_shadow_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            parity_dir = runtime / "parity"
            parity_dir.mkdir(parents=True)
            (parity_dir / "QuantGod_StrategyParityReport.json").write_text(
                json.dumps(
                    {
                        "status": "PARITY_FAIL",
                        "reasonZh": "Strategy JSON 与 MQL5 EA RSI 参数不一致。",
                        "promotionGate": {"status": "BLOCKED", "promotionAllowed": False},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = build_mt5_shadow_lane(runtime)

            rsi_routes = [
                row
                for row in payload["routes"]
                if row.get("strategy") == "RSI_Reversal" and row.get("direction") == "LONG"
            ]
            self.assertTrue(rsi_routes)
            self.assertEqual(rsi_routes[0]["promotionStage"], "REJECTED")
            self.assertTrue(payload["parityGate"]["parityFailBlocksShadow"])

    def test_hfm_crypto_lane_is_never_execution_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)

            payload = build_hfm_crypto_shadow_lane(runtime)

            self.assertEqual(payload["lane"], "HFM_CRYPTO_CFD_SHADOW")
            self.assertFalse(payload["safety"]["walletAuthorizationAllowed"])
            self.assertFalse(payload["safety"]["hfmCryptoExecutionAllowed"])
            self.assertFalse(payload["safety"]["mt5OrderSendAllowed"])

    def test_cent_account_config_caps_max_lot_at_two(self) -> None:
        cfg = cent_account_config()

        self.assertEqual(cfg["accountMode"], "cent")
        self.assertLessEqual(cfg["maxLot"], 2.0)
        self.assertTrue(cfg["centAccountAcceleration"])

    def test_daily_autopilot_v2_summarizes_three_lanes_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            sample_walk_forward_runtime(runtime, overwrite=True)
            backtest_dir = runtime / "backtest"
            backtest_dir.mkdir(parents=True, exist_ok=True)
            (backtest_dir / "QuantGod_USDJPYHistoryProductionStatus.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "historyTargetSatisfied": True,
                        "failedCount": 0,
                        "reasonZh": "USDJPY SQLite 历史数据生产状态通过。",
                        "source": {"mql5ExportDir": "/tmp/exported_klines"},
                        "timeframes": {"H1": {"spanDays": 372.1}, "M1": {"spanDays": 372.2}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            adaptive_dir = runtime / "adaptive"
            adaptive_dir.mkdir(parents=True, exist_ok=True)
            (adaptive_dir / "QuantGod_USDJPYAutoExecutionPolicy.json").write_text(
                json.dumps(
                    {
                        "spreadGate": {
                            "spreadPips": 2.3,
                            "tier": "SOFT_WIDE",
                            "tierZh": "轻微偏宽",
                            "normalLimitPips": 2.2,
                            "softLimitPips": 2.7,
                            "hardLimitPips": 3.0,
                            "reasonZh": "点差轻微偏宽，美分账户降仓机会入场，美元账户仅镜像观察。",
                            "centActionZh": "美分账户允许小仓机会入场。",
                            "usdActionZh": "美元账户仅 paper mirror，不实盘。",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = build_daily_autopilot_v2(runtime, write=True)

            self.assertEqual(payload["symbol"], "USDJPYc")
            self.assertIn("morningPlan", payload)
            self.assertIn("eveningReview", payload)
            self.assertIn("dailyTodo", payload)
            self.assertIn("dailyReview", payload)
            self.assertIn("nextPhaseTodos", payload)
            self.assertTrue(payload["dailyTodo"]["completedByAgent"])
            self.assertTrue(payload["dailyReview"]["completedByAgent"])
            self.assertTrue(payload["dailyTodo"]["requiresAutonomousGovernance"])
            self.assertEqual(payload["agentVersion"], "v2.6")
            self.assertIn("strategyJsonTodo", payload["dailyTodo"])
            self.assertIn("gaEvolutionTodo", payload["dailyTodo"])
            self.assertIn("telegramGatewayTodo", payload["dailyTodo"])
            self.assertEqual(payload["historyProductionStatus"]["statusZh"], "生产级 PASS")
            self.assertEqual(payload["gaReview"]["historyProductionStatus"]["promotionGateStatus"], "PASS")
            self.assertEqual(payload["dailyTodo"]["historyProductionStatus"]["status"], "PASS")
            self.assertEqual(payload["dailyReview"]["historyProductionStatus"]["status"], "PASS")
            self.assertIn("executionConsistencyReview", payload["dailyReview"])
            text = daily_autopilot_v2_to_chinese_text(payload)
            self.assertIn("美分账户", text)
            self.assertIn("美元账户", text)
            self.assertIn("USD_PAPER_MIRROR", text)
            self.assertIn("USDJPY 点差门禁", text)
            self.assertIn("轻微偏宽", text)
            self.assertIn("GA 历史样本", text)
            self.assertIn("生产级 PASS", text)
            self.assertIn("执行一致性复盘", text)
            self.assertTrue(payload["nextPhaseTodos"]["completedByAgent"])
            self.assertEqual(payload["nextPhaseTodos"]["strategyJsonTodo"]["status"], "COMPLETED_BY_AGENT")
            self.assertEqual(payload["nextPhaseTodos"]["gaEvolutionTodo"]["status"], "COMPLETED_BY_AGENT")
            self.assertEqual(payload["nextPhaseTodos"]["telegramGatewayTodo"]["status"], "COMPLETED_BY_AGENT")
            self.assertNotIn("requiresManualReview", payload["dailyTodo"])
            self.assertNotIn("requiresManualReview", payload["dailyReview"])
            self.assertIn("mt5Shadow", payload["lanes"])
            self.assertIn("centLive", payload["lanes"])
            self.assertIn("usdDeployment", payload["lanes"])
            self.assertIn("hfmCryptoShadow", payload["lanes"])
            self.assertIn("accountRegistry", payload)
            self.assertFalse(payload["safety"]["orderSendAllowed"])
            self.assertFalse(payload["safety"]["externalMarketRealMoneyAllowed"])
            self.assertFalse(payload["safety"]["hfmCryptoExecutionAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_DailyAutopilotV2.json").exists())

    def test_daily_autopilot_v2_runs_agent_cycle_and_records_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            repo_root = Path(__file__).resolve().parents[1]

            run = run_daily_autopilot_cycle(
                runtime,
                repo_root=repo_root,
                write=True,
                bootstrap_samples=True,
            )
            payload = build_daily_autopilot_v2(runtime, repo_root=repo_root, write=True)

            self.assertTrue(run["ok"])
            self.assertEqual(run["status"], "COMPLETED_BY_AGENT")
            self.assertGreaterEqual(run["completedStepCount"], 7)
            self.assertEqual(run["failedStepCount"], 0)
            self.assertIn("orchestrationRun", payload)
            self.assertEqual(payload["orchestrationRun"]["status"], "COMPLETED_BY_AGENT")
            self.assertTrue((runtime / "agent" / "QuantGod_DailyAutopilotV2RunLatest.json").exists())
            self.assertTrue((runtime / "agent" / "QuantGod_DailyAutopilotV2RunLedger.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
