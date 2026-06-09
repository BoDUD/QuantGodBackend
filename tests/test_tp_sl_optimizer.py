from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.tp_sl_optimizer import (
    _btc_base_configs,
    _btc_final_advisory_pick,
    _btc_middle_window_leaders,
    _btc_window_health,
    build_tp_sl_optimizer_report,
)


class TpSlOptimizerTests(unittest.TestCase):
    def _write_forex_trades(self, runtime: Path) -> None:
        path = runtime / "backtest" / "QuantGod_StrategyTrades.csv"
        path.parent.mkdir(parents=True)
        fields = [
            "tradeId",
            "symbol",
            "riskPips",
            "grossProfitPips",
            "costPips",
            "profitPips",
            "mfeR",
            "maeR",
            "exitReason",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for index in range(24):
                winner = index % 3 != 0
                writer.writerow({
                    "tradeId": f"BT-{index:04d}",
                    "symbol": "USDJPYc",
                    "riskPips": "20",
                    "grossProfitPips": "30" if winner else "-20",
                    "costPips": "2.2",
                    "profitPips": "27.8" if winner else "-22.2",
                    "mfeR": "1.8" if winner else "0.4",
                    "maeR": "0.35" if winner else "-1.4",
                    "exitReason": "TAKE_PROFIT" if winner else "STOP_LOSS",
                })

    def _write_btc_rates(self, runtime: Path) -> None:
        rates = runtime / "hfm_crypto" / "rates"
        rates.mkdir(parents=True)
        csv_path = rates / "BTCUSD___BTCUSD__M15.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "epoch",
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "tick_volume",
                    "spread",
                    "real_volume",
                ],
            )
            writer.writeheader()
            price = 100000.0
            for index in range(720):
                price += 95.0 if index % 18 < 9 else -70.0
                writer.writerow({
                    "epoch": 1800000000 + index * 900,
                    "timestamp": f"2026.06.01 {index:04d}",
                    "open": price - 10,
                    "high": price + 30,
                    "low": price - 30,
                    "close": price,
                    "tick_volume": 1,
                    "spread": 10,
                    "real_volume": 0,
                })
        (runtime / "hfm_crypto" / "QuantGod_HFMCryptoContractSpecExport.json").write_text(
            json.dumps({
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
            }),
            encoding="utf-8",
        )
        (runtime / "agent").mkdir(exist_ok=True)
        (runtime / "agent" / "QuantGod_BtcStrategyScanReport.json").write_text(
            json.dumps({
                "topCandidate": {
                    "strategyId": "btc_control",
                    "strategyFamily": "ema_slope_regime",
                    "parameters": {
                        "bias": "both",
                        "emaSpan": 36,
                        "slopeLookbackBars": 96,
                        "slopeThresholdPrice": 75.0,
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 300.0,
                        "maxHoldBars": 12,
                        "cooldownBars": 4,
                    },
                },
                "repairDiagnostics": {},
            }),
            encoding="utf-8",
        )

    def test_builds_read_only_tpsl_report_with_forex_and_btc_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._write_forex_trades(runtime)
            self._write_btc_rates(runtime)

            report = build_tp_sl_optimizer_report(runtime, top_n=4, write=True)

            self.assertEqual(report["schema"], "quantgod.tp_sl_optimizer.report.v1")
            self.assertEqual(report["forexMt5"]["status"], "FOREX_TPSL_SCREEN_READY")
            self.assertGreater(report["forexMt5"]["recommended"]["sampleCount"], 0)
            self.assertIn("testerOverrides", report["forexMt5"]["recommended"])
            self.assertEqual(report["btcCryptoCfd"]["status"], "BTC_TPSL_SCAN_READY")
            self.assertGreater(report["btcCryptoCfd"]["scannedConfigCount"], 0)
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["livePresetMutationAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_TpSlOptimizerReport.json").exists())

    def test_forex_screen_does_not_recommend_blocked_negative_combo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            path = runtime / "backtest" / "QuantGod_StrategyTrades.csv"
            path.parent.mkdir(parents=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "tradeId",
                        "symbol",
                        "riskPips",
                        "grossProfitPips",
                        "costPips",
                        "profitPips",
                        "mfeR",
                        "maeR",
                        "exitReason",
                    ],
                )
                writer.writeheader()
                for index in range(24):
                    writer.writerow({
                        "tradeId": f"BT-{index:04d}",
                        "symbol": "USDJPYc",
                        "riskPips": "20",
                        "grossProfitPips": "-20",
                        "costPips": "2.2",
                        "profitPips": "-22.2",
                        "mfeR": "0.1",
                        "maeR": "-2.0",
                        "exitReason": "STOP_LOSS",
                    })

            report = build_tp_sl_optimizer_report(runtime, top_n=3, write=False)

            self.assertEqual(report["forexMt5"]["status"], "FOREX_TPSL_NO_PASSING_COARSE_COMBO")
            self.assertEqual(report["forexMt5"]["recommended"], {})
            self.assertIn("bestBlockedCandidate", report["forexMt5"])
            self.assertGreater(len(report["forexMt5"]["testerVariantQueue"]), 0)

    def test_btc_final_pick_keeps_stable_default_when_target_has_weaker_windows(self) -> None:
        stable = {
            "strategyId": "stable",
            "validWindowCount": 5,
            "positiveMajorWindowCount": 3,
            "negativeWindowCount": 0,
            "fullWindowMetrics": {"pnlUsd": 38.7, "maxDrawdownPct": 1.56},
            "parameters": {
                "bias": "short",
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 300.0,
                "maxHoldBars": 8,
                "cooldownBars": 6,
            },
        }
        target = {
            "strategyId": "target",
            "validWindowCount": 2,
            "positiveMajorWindowCount": 3,
            "negativeWindowCount": 0,
            "fullWindowMetrics": {"pnlUsd": 83.0, "maxDrawdownPct": 1.52},
        }

        pick, policy, reason = _btc_final_advisory_pick(stable, target)

        self.assertEqual(pick["strategyId"], "stable")
        self.assertEqual(pick["params"]["takeProfitPriceMove"], 450.0)
        self.assertEqual(pick["tpSlSummary"]["stopLossPriceMove"], 300.0)
        self.assertEqual(policy, "STABLE_OVER_TARGET_SEEKING")
        self.assertIn("窗口", reason)

    def test_btc_final_pick_allows_target_when_stability_not_worse(self) -> None:
        stable = {
            "strategyId": "stable",
            "validWindowCount": 4,
            "positiveMajorWindowCount": 3,
            "negativeWindowCount": 0,
            "fullWindowMetrics": {"pnlUsd": 38.7, "maxDrawdownPct": 1.56},
        }
        target = {
            "strategyId": "target",
            "validWindowCount": 5,
            "positiveMajorWindowCount": 3,
            "negativeWindowCount": 0,
            "fullWindowMetrics": {"pnlUsd": 83.0, "maxDrawdownPct": 1.6},
        }

        pick, policy, _ = _btc_final_advisory_pick(stable, target)

        self.assertEqual(pick["strategyId"], "target")
        self.assertEqual(policy, "TARGET_SEEKING_STABILITY_NOT_WORSE")

    def test_btc_window_health_exposes_middle_third_weakness(self) -> None:
        candidate = {
            "strategyId": "btc_middle_weak",
            "validWindowCount": 5,
            "windowCount": 6,
            "windowSummary": [
                {"window": "full", "pnlUsd": 38.7, "sharpe": 1.32, "tradeCount": 69, "blockers": []},
                {"window": "first_half", "pnlUsd": 21.6, "sharpe": 1.05, "tradeCount": 32, "blockers": []},
                {"window": "second_half", "pnlUsd": 21.7, "sharpe": 1.03, "tradeCount": 36, "blockers": []},
                {"window": "first_third", "pnlUsd": 27.5, "sharpe": 1.47, "tradeCount": 24, "blockers": []},
                {
                    "window": "middle_third",
                    "pnlUsd": 5.2,
                    "sharpe": 0.38,
                    "tradeCount": 15,
                    "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                },
                {"window": "last_third", "pnlUsd": 17.1, "sharpe": 1.04, "tradeCount": 23, "blockers": []},
            ],
        }

        health = _btc_window_health(candidate)

        self.assertTrue(health["allWindowsPositive"])
        self.assertTrue(health["middleThirdWeak"])
        self.assertEqual(health["middleThirdWeakness"]["window"], "middle_third")
        self.assertEqual(health["blockerHistogram"]["HFM_SHARPE_LT_MIN"], 1)
        self.assertIn("middle_third_rescue", health["repairFocus"])
        self.assertIn("middle_third", health["diagnosisZh"])

    def test_btc_middle_window_leaders_rank_target_middle_quality(self) -> None:
        def candidate(strategy_id: str, pnl: float, middle_sharpe: float, middle_trades: int, valid: int) -> dict:
            return {
                "strategyId": strategy_id,
                "strategyName": strategy_id,
                "strategyFamily": "ema_slope_regime",
                "status": "BTC_CHAMPION_RETEST_NEEDS_MORE_WINDOWS",
                "validWindowCount": valid,
                "windowCount": 6,
                "positiveWindowCount": 6,
                "negativeWindowCount": 0,
                "positiveMajorWindowCount": 3,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {
                    "pnlUsd": pnl,
                    "sharpe": 1.5,
                    "maxDrawdownPct": 1.4,
                    "tradeCount": 60,
                    "liquidationCount": 0,
                },
                "parameters": {
                    "bias": "both",
                    "takeProfitPriceMove": 700.0,
                    "stopLossPriceMove": 400.0,
                    "maxHoldBars": 24,
                    "cooldownBars": 4,
                },
                "windows": [
                    {"window": "full", "metrics": {"pnlUsd": pnl, "sharpe": 1.5, "tradeCount": 60}, "blockers": []},
                    {"window": "first_half", "metrics": {"pnlUsd": 20.0, "sharpe": 1.1, "tradeCount": 30}, "blockers": []},
                    {"window": "second_half", "metrics": {"pnlUsd": 18.0, "sharpe": 1.05, "tradeCount": 30}, "blockers": []},
                    {"window": "first_third", "metrics": {"pnlUsd": 12.0, "sharpe": 1.2, "tradeCount": 20}, "blockers": []},
                    {
                        "window": "middle_third",
                        "metrics": {"pnlUsd": 10.0, "sharpe": middle_sharpe, "tradeCount": middle_trades},
                        "blockers": [] if middle_sharpe >= 1.0 and middle_trades >= 20 else ["HFM_SHARPE_LT_MIN"],
                    },
                    {"window": "last_third", "metrics": {"pnlUsd": 14.0, "sharpe": 1.1, "tradeCount": 20}, "blockers": []},
                ],
                "blockers": [],
            }

        leaders = _btc_middle_window_leaders([
            candidate("high_pnl_weak_middle", 90.0, 0.4, 15, 4),
            candidate("target_good_middle", 62.0, 1.2, 24, 5),
            candidate("stable_low_pnl", 39.0, 1.4, 25, 6),
        ])

        self.assertEqual(leaders["status"], "BTC_MIDDLE_WINDOW_LEADERS_READY")
        self.assertEqual(leaders["bestTargetMiddleQuality"]["strategyId"], "target_good_middle")
        self.assertEqual(leaders["bestTargetMiddleQuality"]["middleThirdMetrics"]["sharpe"], 1.2)
        self.assertFalse(leaders["bestTargetMiddleQuality"]["orderSendAllowed"])
        self.assertTrue(leaders["bestTargetMiddleQuality"]["testerOnly"])

    def test_btc_base_configs_reuses_prior_middle_window_leader_as_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            report_path = runtime / "agent" / "QuantGod_TpSlOptimizerReport.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(
                json.dumps({
                    "btcCryptoCfd": {
                        "middleWindowLeaders": {
                            "bestTargetMiddleQuality": {
                                "strategyId": "hfm_crypto_btc_tpsl_3018",
                                "strategyFamily": "ema_slope_regime",
                                "parameters": {
                                    "bias": "both",
                                    "emaSpan": 36,
                                    "slopeLookbackBars": 144,
                                    "slopeThresholdPrice": 100.0,
                                    "takeProfitPriceMove": 750.0,
                                    "stopLossPriceMove": 400.0,
                                    "maxHoldBars": 36,
                                    "cooldownBars": 6,
                                },
                            }
                        }
                    }
                }),
                encoding="utf-8",
            )

            configs = _btc_base_configs(runtime)

            self.assertTrue(configs)
            leader_configs = [
                row
                for row in configs
                if row.get("sourceStrategyId") == "hfm_crypto_btc_tpsl_3018"
                and row.get("sourceRepairRole") == "priorOptimizerMiddleWindow:bestTargetMiddleQuality"
            ]
            self.assertTrue(leader_configs)
            values = {(
                row["parameters"]["takeProfitPriceMove"],
                row["parameters"]["stopLossPriceMove"],
                row["parameters"]["maxHoldBars"],
                row["parameters"]["cooldownBars"],
                row["parameters"]["slopeThresholdPrice"],
            ) for row in leader_configs}
            self.assertIn((650.0, 350.0, 48, 8, 125.0), values)
            self.assertIn((850.0, 450.0, 24, 4, 75.0), values)


if __name__ == "__main__":
    unittest.main()
