from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.champion_retest import build_champion_retest_report, _ranked_btc_retests


class ChampionRetestTests(unittest.TestCase):
    def test_btc_retest_prefers_positive_major_windows_over_single_window_pnl(self) -> None:
        unstable_high_pnl = {
            "strategyId": "unstable_high_pnl",
            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
            "validWindowCount": 2,
            "positiveWindowCount": 5,
            "negativeWindowCount": 1,
            "positiveMajorWindowCount": 2,
            "majorWindowFailureCount": 1,
            "fullWindowMetrics": {
                "pnlUsd": 90.0,
                "sharpe": 2.4,
                "maxDrawdownPct": 1.5,
            },
            "score": 20.0,
        }
        stable_lower_pnl = {
            "strategyId": "stable_lower_pnl",
            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
            "validWindowCount": 1,
            "positiveWindowCount": 6,
            "negativeWindowCount": 0,
            "positiveMajorWindowCount": 3,
            "majorWindowFailureCount": 0,
            "fullWindowMetrics": {
                "pnlUsd": 60.0,
                "sharpe": 1.8,
                "maxDrawdownPct": 1.0,
            },
            "score": 12.0,
        }

        ranked = _ranked_btc_retests([unstable_high_pnl, stable_lower_pnl])

        self.assertEqual(ranked[0]["strategyId"], "stable_lower_pnl")

    def test_btc_retest_prefers_no_negative_windows_over_more_valid_windows(self) -> None:
        higher_valid_with_negative_third = {
            "strategyId": "higher_valid_with_negative_third",
            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
            "validWindowCount": 3,
            "positiveWindowCount": 5,
            "negativeWindowCount": 1,
            "positiveMajorWindowCount": 3,
            "majorWindowFailureCount": 0,
            "fullWindowMetrics": {
                "pnlUsd": 60.0,
                "sharpe": 1.5,
                "maxDrawdownPct": 2.0,
            },
            "score": 14.0,
        }
        all_windows_positive = {
            "strategyId": "all_windows_positive",
            "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
            "validWindowCount": 2,
            "positiveWindowCount": 6,
            "negativeWindowCount": 0,
            "positiveMajorWindowCount": 3,
            "majorWindowFailureCount": 0,
            "fullWindowMetrics": {
                "pnlUsd": 55.0,
                "sharpe": 1.4,
                "maxDrawdownPct": 1.8,
            },
            "score": 12.0,
        }

        ranked = _ranked_btc_retests([higher_valid_with_negative_third, all_windows_positive])

        self.assertEqual(ranked[0]["strategyId"], "all_windows_positive")

    def test_forex_champion_passes_and_safety_stays_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "ga").mkdir(parents=True)
            (runtime / "ga" / "QuantGod_GAEliteStrategies.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": "GA-USDJPY-G0077-C0002",
                                "strategyId": "USDJPY_RSI_CHAMPION",
                                "fitness": 7.4,
                                "fitnessBreakdown": {
                                    "strategyBacktest": {
                                        "netR": 5.9,
                                        "profitFactor": 3.0,
                                        "sharpe": 2.4,
                                        "maxDrawdownR": 1.9,
                                        "tradeCount": 20,
                                        "evidenceQuality": "MEDIUM",
                                    },
                                    "walkForward": {
                                        "summary": {
                                            "sampleCount": 26,
                                            "stabilityScore": 0.95,
                                            "trainNetR": 4.8,
                                            "validationNetR": 2.3,
                                            "forwardNetR": 1.9,
                                            "maxDrawdownR": 1.9,
                                            "promotionAllowed": True,
                                            "evidenceQuality": "HIGH",
                                        },
                                        "segments": [
                                            {"segment": "train", "netR": 4.8, "profitFactor": 3.5, "sharpe": 2.3, "maxDrawdownR": 1.9, "tradeCount": 14, "lossStreak": 2},
                                            {"segment": "validation", "netR": 2.3, "profitFactor": 2.3, "sharpe": 9.6, "maxDrawdownR": 0, "tradeCount": 5, "lossStreak": 0},
                                            {"segment": "forward", "netR": 1.9, "profitFactor": 2.9, "sharpe": 1.3, "maxDrawdownR": 0.9, "tradeCount": 7, "lossStreak": 1},
                                        ],
                                    },
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_retest_report(runtime, write=False)

            self.assertEqual(report["forexChampion"]["status"], "FOREX_CHAMPION_RETEST_PASS")
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["writesMt5OrderRequest"])

    def test_forex_champion_follows_ace_scout_top_effective_sample_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "agent").mkdir(parents=True)
            (runtime / "agent" / "QuantGod_AceStrategyScout.json").write_text(
                json.dumps(
                    {
                        "topQualifiedForex": {
                            "seedId": "GA-USDJPY-G0093-C0004",
                            "effectiveSampleCount": 25,
                        },
                        "forexContenderReview": {
                            "status": "PARALLEL_TESTER_FORWARD_TIE_BREAK_REQUIRED",
                            "requiresParallelTesterForward": True,
                            "tiedTopCount": 2,
                            "contenders": [
                                {"seedId": "GA-USDJPY-G0093-C0004"},
                                {"seedId": "GA-USDJPY-G0102-C0004"},
                            ],
                            "safety": {"orderSendAllowed": False},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "ga").mkdir(parents=True)
            (runtime / "ga" / "QuantGod_GAEliteStrategies.json").write_text(
                json.dumps(
                    {
                        "elites": [
                            {
                                "seedId": "GA-USDJPY-G0093-C0004",
                                "strategyId": "USDJPY_RSI_G0093",
                                "fitness": 7.796,
                                "fitnessBreakdown": {
                                    "strategyBacktest": {
                                        "netR": 6.5923,
                                        "profitFactor": 2.6998,
                                        "sharpe": 2.0702,
                                        "maxDrawdownR": 1.9486,
                                        "tradeCount": 18,
                                        "evidenceQuality": "MEDIUM",
                                    },
                                    "walkForward": {
                                        "summary": {
                                            "sampleCount": 25,
                                            "stabilityScore": 0.95,
                                            "trainNetR": 5.0877,
                                            "validationNetR": 1.6828,
                                            "forwardNetR": 2.3428,
                                            "maxDrawdownR": 1.9296,
                                            "promotionAllowed": True,
                                            "evidenceQuality": "HIGH",
                                        },
                                        "segments": [
                                            {"segment": "train", "netR": 5.0877, "profitFactor": 2.7578, "sharpe": 1.8189, "maxDrawdownR": 1.9296, "tradeCount": 14, "lossStreak": 2},
                                            {"segment": "validation", "netR": 1.6828, "profitFactor": 2.7272, "sharpe": 1.1182, "maxDrawdownR": 0.9743, "tradeCount": 5, "lossStreak": 1},
                                            {"segment": "forward", "netR": 2.3428, "profitFactor": 3.4046, "sharpe": 1.516, "maxDrawdownR": 0.9743, "tradeCount": 6, "lossStreak": 1},
                                        ],
                                    },
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_retest_report(runtime, write=False)

            self.assertEqual(report["forexChampion"]["seedId"], "GA-USDJPY-G0093-C0004")
            self.assertEqual(report["forexChampion"]["status"], "FOREX_CHAMPION_RETEST_PASS")
            self.assertEqual(report["forexChampion"]["backtest"]["tradeCount"], 18)
            self.assertEqual(report["forexChampion"]["backtest"]["effectiveSampleCount"], 25)
            self.assertNotIn("FOREX_TRADE_COUNT_LT_20", report["forexChampion"]["blockers"])
            self.assertTrue(report["forexContenderReview"]["requiresParallelTesterForward"])
            self.assertIn("GA-USDJPY-G0093-C0004 / GA-USDJPY-G0102-C0004", report["nextSafeActionZh"])
            self.assertFalse(report["safety"]["orderSendAllowed"])

    def test_btc_windows_are_retested_without_order_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            rates = runtime / "hfm_crypto" / "rates"
            rates.mkdir(parents=True)
            csv_path = rates / "BTCUSD___BTCUSD__M15.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["epoch", "timestamp", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
                writer.writeheader()
                price = 100000.0
                for index in range(600):
                    price -= 35.0
                    writer.writerow({
                        "epoch": 1800000000 + index * 900,
                        "timestamp": f"2026.06.01 {index:04d}",
                        "open": price + 10,
                        "high": price + 20,
                        "low": price - 20,
                        "close": price,
                        "tick_volume": 1,
                        "spread": 10,
                        "real_volume": 0,
                    })
            (runtime / "hfm_crypto").mkdir(exist_ok=True)
            (runtime / "hfm_crypto" / "QuantGod_HFMCryptoContractSpecExport.json").write_text(
                json.dumps(
                    {
                        "symbols": [
                            {
                                "brokerSymbol": "#BTCUSD",
                                "canonicalSymbol": "BTCUSD",
                                "contractSize": 1,
                                "tickSize": 0.001,
                                "tickValue": 0.001,
                                "minLot": 0.01,
                                "lotStep": 0.01,
                                "maxLot": 50,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_retest_report(runtime, write=False)

            self.assertGreaterEqual(report["cryptoChampion"]["windowCount"], 3)
            self.assertGreaterEqual(len(report["cryptoChampion"]["candidateRetests"]), 6)
            self.assertEqual(
                report["cryptoChampion"]["strategyId"],
                report["cryptoChampion"]["candidateRetests"][0]["strategyId"],
            )
            self.assertIn(
                "hfm_crypto_btc_regime_bidirectional_shadow_v1",
                {row["strategyId"] for row in report["cryptoChampion"]["candidateRetests"]},
            )
            self.assertIn(
                "hfm_crypto_btc_regime_balanced_window_shadow_v1",
                {row["strategyId"] for row in report["cryptoChampion"]["candidateRetests"]},
            )
            self.assertFalse(report["cryptoChampion"]["safety"]["orderSendAllowed"])
            self.assertFalse(report["cryptoChampion"]["safety"]["livePresetMutationAllowed"])

    def test_btc_retest_imports_scanner_top_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            rates = runtime / "hfm_crypto" / "rates"
            rates.mkdir(parents=True)
            csv_path = rates / "BTCUSD___BTCUSD__M15.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["epoch", "timestamp", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
                writer.writeheader()
                price = 100000.0
                for index in range(600):
                    price -= 35.0
                    writer.writerow({
                        "epoch": 1800000000 + index * 900,
                        "timestamp": f"2026.06.01 {index:04d}",
                        "open": price + 10,
                        "high": price + 20,
                        "low": price - 20,
                        "close": price,
                        "tick_volume": 1,
                        "spread": 10,
                        "real_volume": 0,
                    })
            (runtime / "hfm_crypto" / "QuantGod_HFMCryptoContractSpecExport.json").write_text(
                json.dumps(
                    {
                        "symbols": [
                            {
                                "brokerSymbol": "#BTCUSD",
                                "canonicalSymbol": "BTCUSD",
                                "contractSize": 1,
                                "tickSize": 0.001,
                                "tickValue": 0.001,
                                "minLot": 0.01,
                                "lotStep": 0.01,
                                "maxLot": 50,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "agent").mkdir()
            (runtime / "agent" / "QuantGod_BtcStrategyScanReport.json").write_text(
                json.dumps(
                    {
                        "topCandidates": [
                            {
                                "strategyId": "hfm_crypto_btc_scan_promoted_candidate",
                                "strategyName": "BTC scanner promoted candidate",
                                "strategyFamily": "ema_slope_regime",
                                "parameters": {
                                    "bias": "short",
                                    "emaSpan": 36,
                                    "slopeLookbackBars": 96,
                                    "slopeThresholdPrice": 75.0,
                                    "takeProfitPriceMove": 450.0,
                                    "stopLossPriceMove": 300.0,
                                    "maxHoldBars": 18,
                                    "cooldownBars": 2,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_champion_retest_report(runtime, write=False)

            self.assertIn(
                "hfm_crypto_btc_scan_promoted_candidate",
                {row["strategyId"] for row in report["cryptoChampion"]["candidateRetests"]},
            )
            self.assertFalse(report["cryptoChampion"]["safety"]["orderSendAllowed"])


if __name__ == "__main__":
    unittest.main()
