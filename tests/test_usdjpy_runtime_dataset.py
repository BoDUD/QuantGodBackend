from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.usdjpy_runtime_dataset.builder import build_runtime_dataset
from tools.usdjpy_runtime_dataset.config_proposal import build_live_config_proposal
from tools.usdjpy_runtime_dataset.param_tuner import build_param_tuning_report
from tools.usdjpy_runtime_dataset.replay import build_replay_report
from tools.usdjpy_bar_replay.replay_engine import build_entry_comparison


class USDJPYRuntimeDatasetTests(unittest.TestCase):
    def test_builds_usdjpy_only_dataset_and_retune_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            with (runtime / "QuantGod_EntryBlockers.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "symbol",
                    "strategy",
                    "direction",
                    "status",
                    "reason",
                    "riskPips",
                    "posteriorPips60",
                    "maeR",
                ])
                writer.writeheader()
                writer.writerow({
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "direction": "LONG",
                    "status": "READY_BUY_SIGNAL",
                    "reason": "READY_BUY_SIGNAL but no entry",
                    "riskPips": "5",
                    "posteriorPips60": "8",
                    "maeR": "-0.4",
                })
                writer.writerow({
                    "symbol": "EURUSDc",
                    "strategy": "RSI_Reversal",
                    "direction": "LONG",
                    "status": "READY_BUY_SIGNAL",
                    "reason": "must be ignored",
                })
            with (runtime / "QuantGod_CloseHistory.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["symbol", "strategy", "direction", "profitUSC", "profitR", "mfeR", "maeR", "exitReason"])
                writer.writeheader()
                writer.writerow({
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "direction": "LONG",
                    "profitUSC": "0.4",
                    "profitR": "0.35",
                    "mfeR": "1.5",
                    "maeR": "-0.25",
                    "exitReason": "breakeven_or_trailing",
                })
            (runtime / "backtest").mkdir()
            (runtime / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.usdjpy_history_production_status.v1",
                        "status": "PASS",
                        "historyTargetSatisfied": True,
                        "maxLatestLagHours": 96,
                        "timeframes": {
                            timeframe: {
                                "timeframe": timeframe,
                                "passed": True,
                                "freshnessOk": True,
                                "spanOk": True,
                                "densityOk": True,
                            }
                            for timeframe in ("M1", "M5", "M15", "H1")
                        },
                    }
                ),
                encoding="utf-8",
            )

            dataset = build_runtime_dataset(runtime, write=True)
            replay = build_replay_report(runtime, write=True)
            tuning = build_param_tuning_report(runtime, write=True)
            proposal = build_live_config_proposal(runtime, write=True)

            self.assertEqual(dataset["summary"]["sampleCount"], 2)
            self.assertNotIn("EURUSDc", str(dataset["samples"]))
            self.assertEqual(dataset["summary"]["historyFreshnessStatus"], "PASS")
            self.assertTrue(dataset["summary"]["historyFreshnessPass"])
            self.assertEqual(dataset["latest"]["historyFreshnessGate"]["failedTimeframes"], [])
            self.assertEqual(replay["summary"]["missedOpportunityCount"], 1)
            self.assertEqual(replay["summary"]["earlyExitCount"], 1)
            self.assertEqual(replay["unitPolicy"]["primary"], "R")
            relaxed = {item["scenario"]: item for item in replay["scenarioComparisons"]}["relaxed_entry_v1"]
            let_profit = {item["scenario"]: item for item in replay["scenarioComparisons"]}["let_profit_run_v1"]
            self.assertGreater(relaxed["netRDelta"], 0)
            self.assertGreater(let_profit["netRDelta"], 0)
            self.assertGreaterEqual(tuning["summary"]["candidateCount"], 2)
            self.assertTrue(all("expectedImpact" in item for item in tuning["candidates"]))
            self.assertTrue(all("replayVariant" in item for item in tuning["candidates"] if item["param"] != "dataCollection"))
            self.assertEqual(proposal["status"], "PROPOSAL_READY_FOR_OPERATOR_REVIEW")
            self.assertTrue(proposal["expectedImpact"])
            self.assertTrue(all("riskDelta" in item for item in proposal["changes"]))
            self.assertEqual(proposal["autoApplyAllowed"], "shadow_only")
            self.assertNotIn("requiresManualReview", proposal)
            self.assertTrue(proposal["requiresAutonomousGovernance"])
            self.assertTrue(proposal["safety"]["operatorApprovalRequired"])
            self.assertFalse(proposal["safety"]["unattendedLiveExpansionAllowed"])
            self.assertFalse(proposal["safety"]["liveExpansionAllowed"])
            self.assertTrue(proposal["completedByAgent"])
            self.assertFalse(proposal["autoAppliedByAgent"])
            self.assertFalse(proposal["safety"]["orderSendAllowed"])
            self.assertTrue((runtime / "datasets" / "usdjpy" / "QuantGod_USDJPYRuntimeDataset.json").exists())
            self.assertTrue((runtime / "adaptive" / "QuantGod_USDJPYLiveConfigProposal.json").exists())

    def test_early_exit_requires_r_multiple_not_usc_mixed_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            with (runtime / "QuantGod_CloseHistory.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["symbol", "strategy", "direction", "profitUSC", "mfeR", "exitReason"])
                writer.writeheader()
                writer.writerow({
                    "symbol": "USDJPYc",
                    "strategy": "RSI_Reversal",
                    "direction": "LONG",
                    "profitUSC": "0.8",
                    "mfeR": "2.0",
                    "exitReason": "breakeven_or_trailing",
                })

            dataset = build_runtime_dataset(runtime, write=True)
            replay = build_replay_report(runtime, write=False)

            self.assertEqual(dataset["summary"]["sampleCount"], 1)
            self.assertEqual(replay["summary"]["earlyExitCount"], 0)
            self.assertEqual(replay["summary"]["missingExitRCount"], 1)

    def test_history_freshness_gate_blocks_stale_history_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / "backtest").mkdir()
            (runtime / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.usdjpy_history_production_status.v1",
                        "status": "WARN",
                        "historyTargetSatisfied": False,
                        "maxLatestLagHours": 96,
                        "timeframes": {
                            "M1": {"passed": False, "freshnessOk": False, "latestLagHours": 260},
                            "M5": {"passed": False, "freshnessOk": False, "latestLagHours": 260},
                            "M15": {"passed": False, "freshnessOk": False, "latestLagHours": 260},
                            "H1": {"passed": False, "freshnessOk": False, "latestLagHours": 260},
                        },
                    }
                ),
                encoding="utf-8",
            )

            dataset = build_runtime_dataset(runtime, write=False)

            self.assertEqual(dataset["summary"]["historyFreshnessStatus"], "BLOCKED")
            self.assertFalse(dataset["summary"]["historyFreshnessPass"])
            self.assertEqual(dataset["summary"]["historyStaleTimeframes"], ["M1", "M5", "M15", "H1"])
            self.assertIn("history_freshness_lag_exceeded", dataset["latest"]["historyFreshnessGate"]["blockers"])

    def test_derives_replay_r_units_from_hfm_csv_price_and_shadow_pips(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            with (runtime / "QuantGod_CloseHistory.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "ExitTicket",
                        "Type",
                        "Symbol",
                        "OpenTime",
                        "CloseTime",
                        "OpenPrice",
                        "ClosePrice",
                        "NetProfit",
                        "Strategy",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "ExitTicket": "700000001",
                        "Type": "BUY",
                        "Symbol": "USDJPYc",
                        "OpenTime": "2026.06.01 00:00",
                        "CloseTime": "2026.06.01 01:30",
                        "OpenPrice": "159.95",
                        "ClosePrice": "160.12",
                        "NetProfit": "0.15",
                        "Strategy": "RSI_Reversal",
                    }
                )
            with (runtime / "QuantGod_ShadowCandidateOutcomeLedger.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "EventId",
                        "Symbol",
                        "CandidateRoute",
                        "Timeframe",
                        "CandidateDirection",
                        "CandidateScore",
                        "Regime",
                        "DirectionalOutcomePips",
                        "LongMFEPips",
                        "LongMAEPips",
                        "ShortMFEPips",
                        "ShortMAEPips",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "EventId": "SIG-RSI-1",
                        "Symbol": "USDJPYc",
                        "CandidateRoute": "RSI_Reversal",
                        "Timeframe": "M15",
                        "CandidateDirection": "LONG",
                        "CandidateScore": "85",
                        "Regime": "BEAR_STRETCH",
                        "DirectionalOutcomePips": "3.2",
                        "LongMFEPips": "6.4",
                        "LongMAEPips": "1.8",
                        "ShortMFEPips": "0",
                        "ShortMAEPips": "0",
                    }
                )

            dataset = build_runtime_dataset(runtime, write=True)
            entry = build_entry_comparison(runtime, write=False)

            close_sample = next(item for item in dataset["samples"] if item["source"] == "close_history")
            shadow_sample = next(item for item in dataset["samples"] if item["source"] == "shadow_outcomes")

            self.assertEqual(close_sample["riskPips"], 10.0)
            self.assertEqual(close_sample["profitPips"], 17.0)
            self.assertEqual(close_sample["profitR"], 1.7)
            self.assertEqual(shadow_sample["riskPips"], 10.0)
            self.assertTrue(shadow_sample["wouldEnter"])
            self.assertEqual(shadow_sample["posteriorPips"]["60m"], 3.2)
            self.assertEqual(shadow_sample["posteriorR"]["60m"], 0.32)
            self.assertEqual(shadow_sample["mfeR"], 0.64)
            self.assertEqual(shadow_sample["maeR"], -0.18)
            self.assertEqual(entry["inputCoverage"]["actualProfitRReadyCount"], 1)
            self.assertEqual(entry["inputCoverage"]["posteriorReadyCount"], 1)
            self.assertEqual(entry["inputCoverage"]["entryScoreReadyCount"], 2)


if __name__ == "__main__":
    unittest.main()
