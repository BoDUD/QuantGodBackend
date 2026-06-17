from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from tools.usdjpy_bar_replay.replay_engine import (
    build_bar_replay_report,
    build_entry_comparison,
    build_exit_comparison,
)


class USDJPYBarReplayTests(unittest.TestCase):
    def _write_fixture(self, runtime: Path) -> None:
        with (runtime / "QuantGod_EntryBlockers.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "symbol",
                "strategy",
                "direction",
                "status",
                "reason",
                "riskPips",
                "posteriorR60",
                "posteriorPips60",
                "maeR",
            ])
            writer.writeheader()
            writer.writerow({
                "symbol": "USDJPYc",
                "strategy": "RSI_Reversal",
                "direction": "LONG",
                "status": "READY_BUY_SIGNAL",
                "reason": "NO_CROSS tactical confirmation missing",
                "riskPips": "5",
                "posteriorR60": "0.75",
                "posteriorPips60": "3.75",
                "maeR": "-0.32",
            })
            writer.writerow({
                "symbol": "USDJPYc",
                "strategy": "RSI_Reversal",
                "direction": "LONG",
                "status": "NEWS_BLOCK",
                "reason": "NEWS_BLOCK positive posterior must not trigger",
                "riskPips": "5",
                "posteriorR60": "1.6",
                "posteriorPips60": "8.0",
                "maeR": "-0.2",
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
                "profitUSC": "0.35",
                "profitR": "0.28",
                "mfeR": "1.65",
                "maeR": "-0.31",
                "exitReason": "breakeven_or_trailing",
            })

    def test_causal_replay_does_not_use_posterior_to_bypass_news(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            self._write_fixture(runtime)

            entry = build_entry_comparison(runtime, write=True)
            relaxed_events = entry["events"]["relaxed_entry_v1"]

            self.assertTrue(entry["safety"]["causalReplay"])
            self.assertFalse(entry["safety"]["posteriorMayAffectTrigger"])
            self.assertFalse(entry["causalReplay"]["posteriorMayAffectTrigger"])
            self.assertEqual(entry["inputCoverage"]["sampleCount"], 3)
            self.assertEqual(entry["inputCoverage"]["posteriorReadyCount"], 2)
            self.assertEqual(entry["inputCoverage"]["entryScoreReadyCount"], 3)
            self.assertIn("posteriorR15/30/60/120", " ".join(entry["inputCoverage"]["requiredOutcomeFields"]))
            self.assertEqual(entry["variants"][1]["metrics"]["sampleCount"], 2)
            self.assertNotIn("NEWS_BLOCK positive posterior", str(relaxed_events))
            self.assertNotIn("EURUSDc", str(entry))
            self.assertGreater(entry["variants"][1]["metrics"]["netRDelta"], 0)

    def test_exit_variant_uses_r_capture_ratio_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            self._write_fixture(runtime)

            exit_cmp = build_exit_comparison(runtime, write=True)
            report = build_bar_replay_report(runtime, write=True)

            self.assertEqual(exit_cmp["variants"][0]["metrics"]["sampleCount"], 1)
            self.assertGreater(exit_cmp["variants"][1]["metrics"]["netRDelta"], 0)
            self.assertEqual(report["unitPolicy"]["primary"], "R")
            self.assertEqual(report["summary"]["entryCountDelta"], 1)
            self.assertTrue((runtime / "replay" / "usdjpy" / "QuantGod_USDJPYBarReplayReport.json").exists())
            self.assertTrue((runtime / "replay" / "usdjpy" / "QuantGod_USDJPYEntryVariantComparison.json").exists())
            self.assertTrue((runtime / "replay" / "usdjpy" / "QuantGod_USDJPYExitVariantComparison.json").exists())
            self.assertTrue((runtime / "replay" / "usdjpy" / "QuantGod_USDJPYReplayLedger.csv").exists())
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["livePresetMutationAllowed"])


if __name__ == "__main__":
    unittest.main()
