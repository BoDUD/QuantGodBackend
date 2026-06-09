from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.champion_tester_forward_request import (
    build_champion_tester_forward_request,
    read_champion_tester_forward_request,
)


def champion_fixture() -> dict:
    return {
        "seedId": "GA-USDJPY-G0077-C0002",
        "strategyId": "USDJPY_G0077_RSI",
        "strategyFamily": "RSI_Reversal",
        "direction": "LONG",
        "fingerprint": "g0077-fp",
        "fitness": 12.34,
        "fitnessBreakdown": {
            "strategyBacktest": {
                "netR": 5.9337,
                "profitFactor": 3.0434,
                "sharpe": 2.4035,
                "maxDrawdownR": 1.9296,
                "tradeCount": 20,
            },
            "walkForward": {
                "summary": {
                    "sampleCount": 26,
                    "trainNetR": 2.1,
                    "validationNetR": 1.8,
                    "forwardNetR": 1.2,
                    "stabilityScore": 0.95,
                    "promotionAllowed": True,
                    "evidenceQuality": "GOOD",
                }
            },
        },
        "strategyJson": {
            "seedId": "GA-USDJPY-G0077-C0002",
            "strategyId": "USDJPY_G0077_RSI",
            "indicators": {
                "rsi": {
                    "period": 19,
                    "buyBand": 29,
                    "crossbackThreshold": 0.4,
                }
            },
            "exit": {"timeStopBars": {"H1": 5}},
            "risk": {"riskPips": 21, "opportunityLotMultiplier": 0.22},
        },
    }


class ChampionTesterForwardRequestTests(unittest.TestCase):
    def test_builds_config_only_param_lab_request_for_g0077(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            with patch("tools.champion_tester_forward_request._champion_rows", return_value=[champion_fixture()]):
                report = build_champion_tester_forward_request(runtime, write=False)

            self.assertEqual(report["schema"], "quantgod.champion_tester_forward_request.v1")
            self.assertEqual(report["status"], "CHAMPION_TESTER_FORWARD_REQUEST_READY")
            self.assertEqual(report["summary"]["queueCount"], 1)
            self.assertEqual(report["summary"]["topCandidateId"], "g0077-usdjpy-rsi-champion-tester-forward-v1")
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])
            self.assertFalse(report["safety"]["livePresetMutationAllowed"])
            self.assertFalse(report["decision"]["canRunTerminalHere"])

            task = report["selectedTasks"][0]
            self.assertTrue(task["testerOnly"])
            self.assertFalse(task["livePresetMutation"])
            self.assertFalse(task["runTerminalDefault"])
            self.assertIn("run_param_lab.py", task["configOnlyCommand"])
            self.assertEqual(task["presetOverrides"]["ChampionSeedId"], "GA-USDJPY-G0077-C0002")
            self.assertEqual(task["strategyJsonSnapshot"]["seedId"], "GA-USDJPY-G0077-C0002")

    def test_status_falls_back_to_build_without_writing_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            with patch("tools.champion_tester_forward_request._champion_rows", return_value=[champion_fixture()]):
                report = read_champion_tester_forward_request(runtime)

            self.assertEqual(report["status"], "CHAMPION_TESTER_FORWARD_REQUEST_READY")
            self.assertFalse((runtime / "agent" / "QuantGod_ChampionTesterForwardRequest.json").exists())

    def test_builds_parallel_config_only_request_for_tied_contenders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            g0077 = champion_fixture()
            g0093 = {
                **champion_fixture(),
                "seedId": "GA-USDJPY-G0093-C0004",
                "strategyId": "USDJPY_G0093_RSI",
                "fingerprint": "g0093-fp",
                "strategyJson": {
                    **champion_fixture()["strategyJson"],
                    "seedId": "GA-USDJPY-G0093-C0004",
                    "strategyId": "USDJPY_G0093_RSI",
                },
            }

            with patch("tools.champion_tester_forward_request._champion_rows", return_value=[g0077, g0093]):
                report = build_champion_tester_forward_request(runtime, write=False)

            self.assertEqual(report["status"], "CHAMPION_TESTER_FORWARD_REQUEST_READY")
            self.assertEqual(report["summary"]["queueCount"], 2)
            self.assertEqual(
                report["summary"]["candidateIds"],
                [
                    "g0077-usdjpy-rsi-champion-tester-forward-v1",
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                ],
            )
            self.assertNotIn("--candidate-id", report["batchCommand"])
            self.assertEqual(len(report["selectedTasks"]), 2)
            self.assertEqual(report["selectedTasks"][0]["rank"], 1)
            self.assertEqual(report["selectedTasks"][1]["rank"], 2)
            self.assertFalse(report["selectedTasks"][1]["runTerminalDefault"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])

    def test_attaches_tpsl_optimizer_variants_as_tester_only_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            report_path = runtime / "agent" / "QuantGod_TpSlOptimizerReport.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                """
                {
                  "schema": "quantgod.tp_sl_optimizer.report.v1",
                  "forexMt5": {
                    "status": "FOREX_TPSL_NO_PASSING_COARSE_COMBO",
                    "testerVariantQueue": [
                      {
                        "variantId": "usdjpy_tpsl_18r_1_35",
                        "riskPips": 18,
                        "rewardRatio": 1.35,
                        "tpPips": 24.3,
                        "testerOnly": true,
                        "livePresetMutation": false,
                        "testerOverrides": {
                          "ChampionRiskPips": "18",
                          "PilotRewardRatio": "1.35",
                          "PilotRsiATRMultiplierSL": "1.5"
                        }
                      },
                      {
                        "variantId": "unsafe_live_mutation",
                        "riskPips": 99,
                        "rewardRatio": 9,
                        "testerOnly": true,
                        "livePresetMutation": true,
                        "testerOverrides": {"ChampionRiskPips": "99"}
                      }
                    ]
                  }
                }
                """,
                encoding="utf-8",
            )

            with patch("tools.champion_tester_forward_request._champion_rows", return_value=[champion_fixture()]):
                report = build_champion_tester_forward_request(runtime, write=False)

            self.assertEqual(report["summary"]["queueCount"], 2)
            self.assertEqual(report["summary"]["championQueueCount"], 1)
            self.assertEqual(report["summary"]["tpSlVariantQueueCount"], 1)
            self.assertEqual(report["tpSlOptimization"]["variantQueueCount"], 1)
            variant_task = report["selectedTasks"][1]
            self.assertEqual(
                variant_task["candidateId"],
                "g0077-usdjpy-rsi-champion-tester-forward-v1-usdjpy_tpsl_18r_1_35",
            )
            self.assertEqual(variant_task["routeKey"], "RSI_Reversal_TPSL")
            self.assertEqual(variant_task["presetOverrides"]["ChampionRiskPips"], "18")
            self.assertEqual(variant_task["presetOverrides"]["PilotRewardRatio"], "1.35")
            self.assertTrue(variant_task["testerOnly"])
            self.assertFalse(variant_task["livePresetMutation"])
            self.assertFalse(variant_task["runTerminalDefault"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])


if __name__ == "__main__":
    unittest.main()
