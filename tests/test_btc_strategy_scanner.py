from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.btc_strategy_scanner import (
    build_btc_strategy_scan_report,
    _next_focused_search_plan,
    _balanced_quality_repair_configs,
    _balanced_sample_density_repair_configs,
    _balanced_yield_repair_configs,
    _focused_scan_configs,
    _middle_window_rescue_repair_configs,
    _near_live_stability_confirmation_configs,
    _near_live_stability_followup_configs,
    _near_live_followup_refinement_configs,
    _near_live_middle_window_followup_configs,
    _near_live_middle_window_cluster_refinement_configs,
    _near_live_signal_refinement_configs,
    _near_live_signal_refinement_followup_configs,
    _near_live_high_yield_neighborhood_configs,
    _near_live_high_yield_neighborhood_followup_configs,
    _near_live_high_yield_neighborhood_followup_micro_configs,
    _near_live_high_yield_neighborhood_followup_micro_followup_configs,
    _near_live_stoploss_ladder_refinement_configs,
    _near_live_stoploss_ladder_followup_configs,
    _near_live_stoploss_ladder_followup_micro_configs,
    _near_live_stoploss_ladder_followup_micro_followup_configs,
    _near_live_middle_window_contender_micro_configs,
    _near_live_exit_refinement_configs,
    _near_live_middle_tradeoff_configs,
    _near_live_tempo_refinement_configs,
    _near_live_middle_density_lift_configs,
    _sample_rich_quality_repair_configs,
    _stable_middle_tradeoff_followup_configs,
    _stable_middle_weak_window_bridge_configs,
    _stable_middle_weak_window_confirmation_configs,
    _stable_middle_third_confirmation_configs,
    _stable_middle_third_followup_configs,
    _stable_middle_followup_refinement_micro_configs,
    _stable_middle_followup_refinement_micro_followup_configs,
    _window_summary_entry,
    _yield_leader_confirmation_configs,
)


class BtcStrategyScannerTests(unittest.TestCase):
    def test_near_live_high_yield_neighborhood_configs_target_converged_leader_kernel(self) -> None:
        configs = _near_live_high_yield_neighborhood_configs(24)

        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_high_yield_") for row in configs)
        )
        self.assertTrue(all(row["parameters"]["bias"] == "short" for row in configs[:12]))
        take_profits = {row["parameters"]["takeProfitPriceMove"] for row in configs}
        self.assertTrue({437.5, 450.0, 462.5, 475.0}.issubset(take_profits))
        self.assertTrue(all(row["parameters"]["cooldownBars"] in (4, 5) for row in configs[:12]))

    def test_near_live_high_yield_neighborhood_followup_configs_target_3125_local_pocket(self) -> None:
        configs = _near_live_high_yield_neighborhood_followup_configs(24)

        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_high_yield_followup_") for row in configs)
        )
        stop_losses = {row["parameters"]["stopLossPriceMove"] for row in configs}
        self.assertTrue({306.25, 309.375, 312.5, 315.625}.issubset(stop_losses))
        take_profits = {row["parameters"]["takeProfitPriceMove"] for row in configs}
        self.assertTrue({443.75, 450.0, 456.25, 462.5}.issubset(take_profits))
        self.assertTrue(all(row["parameters"]["cooldownBars"] in (4, 5) for row in configs[:12]))

    def test_near_live_high_yield_neighborhood_followup_micro_configs_target_ultra_local_pocket(self) -> None:
        configs = _near_live_high_yield_neighborhood_followup_micro_configs(64)

        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_high_yield_followup_micro_") for row in configs)
        )
        stop_losses = {row["parameters"]["stopLossPriceMove"] for row in configs}
        self.assertTrue({307.8125, 309.375, 310.9375, 312.5}.issubset(stop_losses))
        take_profits = {row["parameters"]["takeProfitPriceMove"] for row in configs}
        self.assertTrue({446.875, 450.0, 453.125, 456.25}.issubset(take_profits))
        self.assertTrue(all(row["parameters"]["cooldownBars"] in (4, 5) for row in configs[:12]))

    def test_near_live_high_yield_neighborhood_followup_micro_followup_configs_target_31875_pocket(self) -> None:
        configs = _near_live_high_yield_neighborhood_followup_micro_followup_configs(64)

        self.assertTrue(
            all(
                row["strategyId"].startswith("hfm_crypto_btc_near_live_high_yield_followup_micro_followup_")
                for row in configs
            )
        )
        stop_losses = {row["parameters"]["stopLossPriceMove"] for row in configs}
        self.assertTrue({315.625, 317.1875, 318.75, 320.3125}.issubset(stop_losses))
        take_profits = {row["parameters"]["takeProfitPriceMove"] for row in configs}
        self.assertTrue({446.875, 450.0, 453.125, 456.25}.issubset(take_profits))
        self.assertTrue(all(row["parameters"]["cooldownBars"] in (4, 5) for row in configs[:12]))

    def test_stable_middle_followup_refinement_micro_configs_target_micro_ladder(self) -> None:
        configs = _stable_middle_followup_refinement_micro_configs(24)

        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_stable_middle_followup_refinement_micro_") for row in configs)
        )
        stop_losses = {row["parameters"]["stopLossPriceMove"] for row in configs}
        self.assertTrue({306.25, 312.5, 318.75}.issubset(stop_losses))
        self.assertTrue(all(row["parameters"]["cooldownBars"] in (5, 6) for row in configs[:12]))

    def test_stable_middle_followup_refinement_micro_followup_configs_target_ultra_local_ladder(self) -> None:
        configs = _stable_middle_followup_refinement_micro_followup_configs(24)

        self.assertTrue(
            all(
                row["strategyId"].startswith(
                    "hfm_crypto_btc_stable_middle_followup_refinement_micro_followup_"
                )
                for row in configs
            )
        )
        stop_losses = {row["parameters"]["stopLossPriceMove"] for row in configs}
        self.assertTrue({303.125, 306.25, 309.375}.issubset(stop_losses))
        self.assertTrue(all(row["parameters"]["cooldownBars"] in (5, 6) for row in configs[:12]))

    def test_window_summary_entry_supports_raw_windows_shape(self) -> None:
        candidate = {
            "windows": [
                {
                    "window": "middle_third",
                    "metrics": {
                        "pnlUsd": 8.1466,
                        "sharpe": 0.5409,
                        "tradeCount": 19,
                    },
                    "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                }
            ]
        }
        row = _window_summary_entry(candidate, "middle_third")
        self.assertEqual(row["window"], "middle_third")
        self.assertEqual(row["pnlUsd"], 8.1466)
        self.assertEqual(row["sharpe"], 0.5409)
        self.assertEqual(row["tradeCount"], 19)
        self.assertEqual(row["blockers"], ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"])

    def test_scan_is_bounded_read_only_and_reports_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
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

            report = build_btc_strategy_scan_report(runtime, max_configs=8, top_n=3, write=True)

            self.assertEqual(report["schema"], "quantgod.btc_strategy_scan.report.v1")
            self.assertIn("generatedAtIso", report)
            self.assertEqual(report["generatedAtIso"], report["generatedAt"])
            self.assertEqual(report["scannedConfigCount"], 8)
            self.assertLessEqual(len(report["topCandidates"]), 3)
            self.assertEqual(report["topRecommendation"]["strategyId"], report["topCandidate"]["strategyId"])
            self.assertEqual(report["topCandidateStrategyId"], report["topCandidate"]["strategyId"])
            self.assertIsInstance(report["mostStableTradeoff"], dict)
            self.assertIsInstance(report["currentHighestYieldTradeoff"], dict)
            self.assertEqual(
                report["recommendedFocusedRetestOrder"],
                report["nextFocusedSearchPlan"]["recommendedFocusedRetestOrder"],
            )
            self.assertEqual(
                report["nextFocusedSearchPlan"]["recommendedFocusedRetestOrder"],
                report["recommendedFocusedRetestOrder"],
            )
            self.assertEqual(
                report["nextFocusedSearchPlan"]["stabilityFirstTop3StrategyIds"],
                report["recommendedFocusedRetestOrder"],
            )
            self.assertEqual(
                report["nextFocusedSearchPlan"]["topStrategyId"],
                report["mostStableTradeoff"]["strategyId"],
            )
            self.assertEqual(
                report["nextFocusedSearchPlan"]["nextDistinctStrategyId"],
                report["nextFocusedSearchPlan"]["nearLiveStabilityTradeoff"]["strategyId"],
            )
            self.assertEqual(
                report["nextFocusedSearchPlan"]["repairStrategyId"],
                report["recommendedFocusedRetestOrder"][2],
            )
            self.assertIn("repairDiagnostics", report)
            self.assertIn("nextFocusedSearchPlan", report)
            self.assertFalse(report["nextFocusedSearchPlan"]["safety"]["orderSendAllowed"])
            self.assertFalse(report["nextFocusedSearchPlan"]["safety"]["livePresetMutationAllowed"])
            self.assertFalse(report["safety"]["orderSendAllowed"])
            self.assertFalse(report["safety"]["livePresetMutationAllowed"])
            self.assertTrue((runtime / "agent" / "QuantGod_BtcStrategyScanReport.json").exists())

    def test_stability_configs_are_prioritized_in_small_scan_budget(self) -> None:
        configs = _focused_scan_configs(8)

        self.assertIn(
            "hfm_crypto_btc_stability_short_window_shadow_v1",
            {row["strategyId"] for row in configs},
        )

    def test_near_live_followup_configs_cover_runner_up_neighborhood(self) -> None:
        configs = _near_live_stability_followup_configs(72)

        self.assertTrue(configs)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_followup_") for row in configs)
        )
        self.assertIn(
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 57,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 350.0,
                "maxHoldBars": 8,
                "cooldownBars": 4,
            },
            [row["parameters"] for row in configs],
        )

    def test_near_live_refinement_configs_cover_followup_neighborhood(self) -> None:
        configs = _near_live_followup_refinement_configs(72)

        self.assertTrue(configs)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_refinement_") for row in configs)
        )
        self.assertIn(
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 57,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 325.0,
                "maxHoldBars": 8,
                "cooldownBars": 4,
            },
            [row["parameters"] for row in configs],
        )

    def test_near_live_middle_window_followup_configs_target_followup_weak_window(self) -> None:
        configs = _near_live_middle_window_followup_configs(96)

        self.assertTrue(configs)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_middle_window_") for row in configs)
        )
        self.assertIn(
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 57,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 325.0,
                "maxHoldBars": 8,
                "cooldownBars": 4,
            },
            [row["parameters"] for row in configs],
        )
        self.assertTrue(any(row["maxHoldBars"] == 6 for row in [c["parameters"] for c in configs]))

    def test_near_live_middle_window_cluster_refinement_configs_target_converged_variant_ladder(self) -> None:
        configs = _near_live_middle_window_cluster_refinement_configs(72)

        self.assertEqual(len(configs), 72)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_cluster_refinement_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:12]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue(all(row["slopeLookbackBars"] in (54, 57, 60) for row in top_params))
        self.assertTrue(all(row["slopeThresholdPrice"] in (100.0, 105.0, 110.0) for row in top_params))
        self.assertTrue(all(row["takeProfitPriceMove"] in (425.0, 450.0, 475.0) for row in top_params))
        self.assertTrue(all(row["stopLossPriceMove"] in (300.0, 325.0, 350.0) for row in top_params))
        self.assertIn(300.0, {row["stopLossPriceMove"] for row in top_params})
        self.assertIn(325.0, {row["stopLossPriceMove"] for row in top_params})

    def test_near_live_signal_refinement_configs_target_signal_kernel_neighborhood(self) -> None:
        configs = _near_live_signal_refinement_configs(72)

        self.assertEqual(len(configs), 72)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_signal_refinement_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:16]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue(any(row["emaSpan"] == 18 for row in top_params), top_params)
        self.assertTrue(any(row["slopeLookbackBars"] == 57 for row in top_params), top_params)
        self.assertTrue(any(row["slopeThresholdPrice"] == 105.0 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 325.0 for row in top_params), top_params)

    def test_near_live_signal_refinement_followup_configs_target_micro_kernel_ladder(self) -> None:
        configs = _near_live_signal_refinement_followup_configs(36)

        self.assertEqual(len(configs), 36)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_signal_refinement_followup_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:12]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertIn(425.0, {row["takeProfitPriceMove"] for row in top_params})
        self.assertIn(437.5, {row["takeProfitPriceMove"] for row in top_params})
        self.assertIn(325.0, {row["stopLossPriceMove"] for row in top_params})
        self.assertTrue(any(row["slopeThresholdPrice"] == 105.0 for row in top_params), top_params)

    def test_near_live_middle_tradeoff_configs_target_converged_cluster_weak_window(self) -> None:
        configs = _near_live_middle_tradeoff_configs(72)

        self.assertEqual(len(configs), 72)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_middle_tradeoff_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:16]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))

    def test_near_live_tempo_refinement_configs_target_hold_cooldown_axis(self) -> None:
        configs = _near_live_tempo_refinement_configs(72)

        self.assertEqual(len(configs), 72)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_tempo_refinement_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:16]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue(any(row["maxHoldBars"] == 8 for row in top_params), top_params)
        self.assertTrue(any(row["cooldownBars"] == 4 for row in top_params), top_params)
        self.assertTrue(any(row["maxHoldBars"] == 9 for row in top_params), top_params)
        self.assertTrue(any(row["cooldownBars"] == 5 for row in top_params), top_params)
        self.assertTrue(any(row["slopeLookbackBars"] == 57 for row in top_params), top_params)
        self.assertTrue(any(row["slopeThresholdPrice"] == 105.0 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 300.0 for row in top_params), top_params)
        self.assertTrue(any(row["cooldownBars"] == 5 for row in top_params), top_params)

    def test_near_live_exit_refinement_configs_target_tp_sl_axis(self) -> None:
        configs = _near_live_exit_refinement_configs(72)

        self.assertEqual(len(configs), 72)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_exit_refinement_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:16]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue(all(row["emaSpan"] == 18 for row in top_params), top_params)
        self.assertTrue(any(row["takeProfitPriceMove"] == 450.0 for row in top_params), top_params)
        self.assertTrue(any(row["takeProfitPriceMove"] == 425.0 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 300.0 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 325.0 for row in top_params), top_params)

    def test_near_live_stoploss_ladder_refinement_configs_target_sl_microsteps(self) -> None:
        configs = _near_live_stoploss_ladder_refinement_configs(72)

        self.assertEqual(len(configs), 72)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_stoploss_ladder_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:16]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue(all(row["emaSpan"] == 18 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 312.5 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 300.0 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 325.0 for row in top_params), top_params)
        self.assertTrue(any(row["takeProfitPriceMove"] == 450.0 for row in top_params), top_params)

    def test_near_live_stoploss_ladder_followup_configs_target_substep_sl_microsteps(self) -> None:
        configs = _near_live_stoploss_ladder_followup_configs(48)

        self.assertEqual(len(configs), 48)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_stoploss_ladder_followup_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:16]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue(all(row["emaSpan"] == 18 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 306.25 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 312.5 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 318.75 for row in top_params), top_params)
        self.assertTrue(any(row["takeProfitPriceMove"] == 450.0 for row in top_params), top_params)

    def test_near_live_stoploss_ladder_followup_micro_configs_target_30625_substeps(self) -> None:
        configs = _near_live_stoploss_ladder_followup_micro_configs(24)

        self.assertEqual(len(configs), 24)
        self.assertTrue(
            all(
                row["strategyId"].startswith("hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_")
                for row in configs
            )
        )
        top_params = [row["parameters"] for row in configs[:16]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue(any(row["stopLossPriceMove"] == 303.125 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 306.25 for row in top_params), top_params)
        self.assertTrue(any(row["stopLossPriceMove"] == 309.375 for row in top_params), top_params)
        self.assertTrue(any(row["takeProfitPriceMove"] == 450.0 for row in top_params), top_params)

    def test_near_live_stoploss_ladder_followup_micro_followup_configs_target_31875_substeps(self) -> None:
        configs = _near_live_stoploss_ladder_followup_micro_followup_configs(24)

        self.assertEqual(len(configs), 24)
        self.assertTrue(
            all(
                row["strategyId"].startswith("hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_followup_")
                for row in configs
            )
        )
        top_params = [row["parameters"] for row in configs[:16]]
        stop_losses = {row["parameters"]["stopLossPriceMove"] for row in configs}
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue({317.1875, 318.75, 320.3125}.issubset(stop_losses), stop_losses)
        self.assertTrue(any(row["takeProfitPriceMove"] == 450.0 for row in top_params), top_params)

    def test_near_live_middle_window_contender_micro_configs_target_325_pocket(self) -> None:
        configs = _near_live_middle_window_contender_micro_configs(24)

        self.assertEqual(len(configs), 24)
        self.assertTrue(
            all(
                row["strategyId"].startswith("hfm_crypto_btc_near_live_middle_window_contender_micro_")
                for row in configs
            )
        )
        top_params = [row["parameters"] for row in configs[:16]]
        stop_losses = {row["parameters"]["stopLossPriceMove"] for row in configs}
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue({323.4375, 325.0, 326.5625}.issubset(stop_losses), stop_losses)
        self.assertTrue(any(row["takeProfitPriceMove"] == 450.0 for row in top_params), top_params)

    def test_near_live_middle_density_lift_configs_target_trade_density_axis(self) -> None:
        configs = _near_live_middle_density_lift_configs(72)

        self.assertEqual(len(configs), 72)
        self.assertTrue(
            all(row["strategyId"].startswith("hfm_crypto_btc_near_live_middle_density_") for row in configs)
        )
        top_params = [row["parameters"] for row in configs[:16]]
        self.assertTrue(all(row["bias"] == "short" for row in top_params))
        self.assertTrue(any(row["cooldownBars"] == 2 for row in top_params), top_params)
        self.assertTrue(any(row["maxHoldBars"] == 6 for row in top_params), top_params)
        self.assertTrue(any(row["slopeThresholdPrice"] == 95.0 for row in top_params), top_params)
        self.assertTrue(any(row["slopeLookbackBars"] == 51 for row in top_params), top_params)

    def test_champion_repair_configs_are_near_front_of_scan_budget(self) -> None:
        configs = _focused_scan_configs(16)
        ids = [row["strategyId"] for row in configs]

        self.assertTrue(
            any(strategy_id.startswith("hfm_crypto_btc_champion_repair_") for strategy_id in ids),
            ids,
        )

    def test_balanced_yield_repair_configs_are_prioritized_before_broad_grid(self) -> None:
        configs = _focused_scan_configs(32)
        ids = [row["strategyId"] for row in configs]

        self.assertTrue(
            any(strategy_id.startswith("hfm_crypto_btc_balanced_yield_repair_") for strategy_id in ids),
            ids,
        )
        self.assertFalse(
            any(strategy_id.startswith("hfm_crypto_btc_scan_focused_") for strategy_id in ids),
            ids,
        )

    def test_balanced_yield_repair_includes_high_pnl_candidate_neighborhoods(self) -> None:
        configs = _balanced_yield_repair_configs(12)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "both",
                "emaSpan": 36,
                "slopeLookbackBars": 144,
                "slopeThresholdPrice": 75.0,
                "takeProfitPriceMove": 900.0,
                "stopLossPriceMove": 500.0,
                "maxHoldBars": 16,
                "cooldownBars": 4,
            },
            parameters,
        )
        self.assertIn(
            {
                "bias": "both",
                "emaSpan": 36,
                "slopeLookbackBars": 144,
                "slopeThresholdPrice": 75.0,
                "takeProfitPriceMove": 750.0,
                "stopLossPriceMove": 400.0,
                "maxHoldBars": 36,
                "cooldownBars": 6,
            },
            parameters,
        )

    def test_balanced_sample_density_repair_prioritizes_shorter_trade_cycles(self) -> None:
        configs = _balanced_sample_density_repair_configs(20)
        parameters = [row["parameters"] for row in configs]

        self.assertTrue(all(row["bias"] == "both" for row in parameters))
        self.assertTrue(any(row["maxHoldBars"] <= 8 for row in parameters), parameters)
        self.assertTrue(any(row["cooldownBars"] <= 1 for row in parameters), parameters)
        self.assertTrue(any(row["slopeThresholdPrice"] <= 50.0 for row in parameters), parameters)

    def test_middle_window_rescue_keeps_stable_and_high_pnl_neighborhoods(self) -> None:
        configs = _middle_window_rescue_repair_configs(32)
        parameters = [row["parameters"] for row in configs]

        self.assertTrue(any(row["bias"] == "short" for row in parameters), parameters)
        self.assertTrue(any(row["bias"] == "both" for row in parameters), parameters)
        self.assertTrue(any(row["maxHoldBars"] <= 8 for row in parameters), parameters)
        self.assertTrue(any(row["cooldownBars"] <= 3 for row in parameters), parameters)
        self.assertTrue(any(row["takeProfitPriceMove"] >= 750.0 for row in parameters), parameters)

    def test_balanced_quality_repair_includes_high_pnl_slow_neighborhoods(self) -> None:
        configs = _balanced_quality_repair_configs(24)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "both",
                "emaSpan": 36,
                "slopeLookbackBars": 144,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 750.0,
                "stopLossPriceMove": 400.0,
                "maxHoldBars": 36,
                "cooldownBars": 6,
            },
            parameters,
        )
        self.assertTrue(all(row["maxHoldBars"] >= 24 for row in parameters), parameters)
        self.assertTrue(all(row["cooldownBars"] >= 5 for row in parameters), parameters)
        self.assertTrue(all(row["slopeThresholdPrice"] >= 75.0 for row in parameters), parameters)

    def test_near_live_stability_confirmation_covers_sample_balanced_neighborhood(self) -> None:
        configs = _near_live_stability_confirmation_configs(512)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "both",
                "emaSpan": 36,
                "slopeLookbackBars": 144,
                "slopeThresholdPrice": 75.0,
                "takeProfitPriceMove": 900.0,
                "stopLossPriceMove": 500.0,
                "maxHoldBars": 16,
                "cooldownBars": 4,
            },
            parameters,
        )
        self.assertTrue(any(12 <= row["maxHoldBars"] <= 20 for row in parameters), parameters)
        self.assertTrue(any(row["cooldownBars"] in (4, 5) for row in parameters), parameters)
        self.assertTrue(any(row["takeProfitPriceMove"] in (750.0, 900.0) for row in parameters), parameters)
        self.assertTrue(
            any(
                row["emaSpan"] == 42
                and row["slopeLookbackBars"] == 144
                and row["slopeThresholdPrice"] == 100.0
                and row["takeProfitPriceMove"] in (400.0, 500.0)
                and row["stopLossPriceMove"] == 600.0
                and row["maxHoldBars"] == 16
                and row["cooldownBars"] == 4
                for row in parameters
            ),
            parameters,
        )
        self.assertTrue(any(row["takeProfitPriceMove"] in (400.0, 500.0) for row in parameters), parameters)
        self.assertTrue(
            any(
                row["bias"] == "short"
                and row["emaSpan"] == 18
                and row["slopeLookbackBars"] in (57, 72)
                and row["takeProfitPriceMove"] == 450.0
                and row["stopLossPriceMove"] == 350.0
                and row["maxHoldBars"] in (8, 10)
                and row["cooldownBars"] in (4, 5)
                for row in parameters
            ),
            parameters,
        )

    def test_stable_middle_third_confirmation_stays_close_to_0302_anchor(self) -> None:
        configs = _stable_middle_third_confirmation_configs(64)
        parameters = [row["parameters"] for row in configs]

        self.assertTrue(all(row["bias"] == "short" for row in parameters), parameters)
        self.assertIn(
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 48,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 300.0,
                "maxHoldBars": 8,
                "cooldownBars": 6,
            },
            parameters,
        )
        self.assertTrue(any(row["maxHoldBars"] in (10, 12) for row in parameters), parameters)
        self.assertTrue(any(row["cooldownBars"] in (4, 5) for row in parameters), parameters)
        self.assertTrue(any(row["takeProfitPriceMove"] == 500.0 for row in parameters), parameters)

    def test_yield_leader_confirmation_stays_close_to_current_yield_leader(self) -> None:
        configs = _yield_leader_confirmation_configs(96)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "both",
                "emaSpan": 36,
                "slopeLookbackBars": 144,
                "slopeThresholdPrice": 75.0,
                "takeProfitPriceMove": 750.0,
                "stopLossPriceMove": 400.0,
                "maxHoldBars": 36,
                "cooldownBars": 6,
            },
            parameters,
        )
        self.assertTrue(any(row["takeProfitPriceMove"] == 900.0 for row in parameters), parameters)
        self.assertTrue(any(row["stopLossPriceMove"] == 450.0 for row in parameters), parameters)
        self.assertTrue(any(row["cooldownBars"] == 8 for row in parameters), parameters)

    def test_stable_middle_third_followup_stays_close_to_0067_neighbor(self) -> None:
        configs = _stable_middle_third_followup_configs(64)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 48,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 325.0,
                "maxHoldBars": 8,
                "cooldownBars": 6,
            },
            parameters,
        )
        self.assertTrue(any(row["stopLossPriceMove"] == 350.0 for row in parameters), parameters)
        self.assertTrue(any(row["takeProfitPriceMove"] == 500.0 for row in parameters), parameters)
        self.assertTrue(any(row["cooldownBars"] in (4, 5) for row in parameters), parameters)

    def test_stable_middle_weak_window_confirmation_targets_true_weak_window_neighborhood(self) -> None:
        configs = _stable_middle_weak_window_confirmation_configs(32)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 54,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 325.0,
                "maxHoldBars": 8,
                "cooldownBars": 4,
            },
            parameters,
        )
        self.assertTrue(any(row["cooldownBars"] == 3 for row in parameters), parameters)
        self.assertTrue(any(row["slopeLookbackBars"] == 48 for row in parameters), parameters)
        self.assertTrue(all(row["bias"] == "short" for row in parameters), parameters)

    def test_stable_middle_weak_window_bridge_targets_between_0302_and_weak_window_spike(self) -> None:
        configs = _stable_middle_weak_window_bridge_configs(32)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 48,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 325.0,
                "maxHoldBars": 8,
                "cooldownBars": 5,
            },
            parameters,
        )
        self.assertTrue(any(row["cooldownBars"] == 6 for row in parameters), parameters)
        self.assertTrue(any(row["stopLossPriceMove"] == 350.0 for row in parameters), parameters)
        self.assertTrue(all(row["bias"] == "short" for row in parameters), parameters)

    def test_stable_middle_tradeoff_followup_targets_bridge_followup_neighborhood(self) -> None:
        configs = _stable_middle_tradeoff_followup_configs(48)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "short",
                "emaSpan": 18,
                "slopeLookbackBars": 48,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 450.0,
                "stopLossPriceMove": 350.0,
                "maxHoldBars": 8,
                "cooldownBars": 5,
            },
            parameters,
        )
        self.assertTrue(any(row["slopeLookbackBars"] in (51, 54) for row in parameters), parameters)
        self.assertTrue(any(row["emaSpan"] == 21 for row in parameters), parameters)
        self.assertTrue(any(row["cooldownBars"] == 6 for row in parameters), parameters)

    def test_near_live_stability_configs_are_in_focused_budget_before_density(self) -> None:
        configs = _focused_scan_configs(768)
        ids = [row["strategyId"] for row in configs]
        first_near_live = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_near_live_stability_")
        )
        first_density = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_balanced_sample_density_")
        )

        self.assertLess(first_near_live, first_density)

    def test_balanced_quality_repair_configs_are_prioritized_before_density(self) -> None:
        configs = _focused_scan_configs(768)
        ids = [row["strategyId"] for row in configs]
        first_quality = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_balanced_quality_repair_")
        )
        first_density = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_balanced_sample_density_")
        )

        self.assertLess(first_quality, first_density)

    def test_sample_rich_quality_repair_bridges_optimizer_leaderboard(self) -> None:
        configs = _sample_rich_quality_repair_configs(32)
        parameters = [row["parameters"] for row in configs]

        self.assertIn(
            {
                "bias": "both",
                "emaSpan": 42,
                "slopeLookbackBars": 144,
                "slopeThresholdPrice": 100.0,
                "takeProfitPriceMove": 400.0,
                "stopLossPriceMove": 600.0,
                "maxHoldBars": 16,
                "cooldownBars": 4,
            },
            parameters,
        )
        self.assertTrue(any(12 <= row["maxHoldBars"] <= 24 for row in parameters), parameters)
        self.assertTrue(all(row["cooldownBars"] >= 4 for row in parameters), parameters)

    def test_sample_rich_quality_repair_is_prioritized_before_density(self) -> None:
        configs = _focused_scan_configs(2048)
        ids = [row["strategyId"] for row in configs]
        first_sample_rich = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_sample_rich_quality_")
        )
        first_density = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_balanced_sample_density_")
        )

        self.assertLess(first_sample_rich, first_density)

    def test_middle_window_rescue_configs_are_in_focused_budget(self) -> None:
        configs = _focused_scan_configs(512)
        ids = [row["strategyId"] for row in configs]

        self.assertTrue(
            any(strategy_id.startswith("hfm_crypto_btc_middle_window_rescue_") for strategy_id in ids),
            ids,
        )

    def test_stable_middle_confirmation_configs_are_in_focused_budget_before_density(self) -> None:
        configs = _focused_scan_configs(768)
        ids = [row["strategyId"] for row in configs]
        first_stable_middle = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_stable_middle_third_")
        )
        first_density = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_balanced_sample_density_")
        )

        self.assertLess(first_stable_middle, first_density)

    def test_yield_leader_confirmation_configs_are_in_focused_budget_before_density(self) -> None:
        configs = _focused_scan_configs(768)
        ids = [row["strategyId"] for row in configs]
        first_yield_leader = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_yield_leader_confirmation_")
        )
        first_density = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_balanced_sample_density_")
        )

        self.assertLess(first_yield_leader, first_density)

    def test_stable_middle_third_followup_configs_are_in_focused_budget_before_density(self) -> None:
        configs = _focused_scan_configs(768)
        ids = [row["strategyId"] for row in configs]
        first_followup = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_stable_middle_followup_")
        )
        first_density = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_balanced_sample_density_")
        )

        self.assertLess(first_followup, first_density)

    def test_stable_middle_weak_window_configs_are_in_focused_budget_before_density(self) -> None:
        configs = _focused_scan_configs(768)
        ids = [row["strategyId"] for row in configs]
        first_weak_window = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_stable_middle_weak_window_")
        )
        first_density = next(
            index for index, strategy_id in enumerate(ids)
            if strategy_id.startswith("hfm_crypto_btc_balanced_sample_density_")
        )

        self.assertLess(first_weak_window, first_density)

    def test_sample_density_repair_configs_are_in_focused_budget(self) -> None:
        configs = _focused_scan_configs(768)
        ids = [row["strategyId"] for row in configs]

        self.assertTrue(
            any(strategy_id.startswith("hfm_crypto_btc_balanced_sample_density_") for strategy_id in ids),
            ids,
        )

    def test_repair_diagnostics_are_written_for_default_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
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
                for index in range(600):
                    price += 60.0 if index % 12 < 6 else -45.0
                    writer.writerow({
                        "epoch": 1800000000 + index * 900,
                        "timestamp": f"2026.06.01 {index:04d}",
                        "open": price - 5,
                        "high": price + 25,
                        "low": price - 25,
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

            report = build_btc_strategy_scan_report(runtime, max_configs=2048, top_n=3, write=False)
            diagnostics = report["repairDiagnostics"]

            self.assertIn("shortChampionRepair", diagnostics)
            self.assertIn("balancedYieldRepair", diagnostics)
            self.assertIn("yieldLeaderConfirmation", diagnostics)
            self.assertIn("nearLiveStabilityRepair", diagnostics)
            self.assertIn("nearLiveHighYieldNeighborhood", diagnostics)
            self.assertIn("stableMiddleThirdConfirmation", diagnostics)
            self.assertIn("stableMiddleThirdFollowup", diagnostics)
            self.assertIn("stableMiddleWeakWindowConfirmation", diagnostics)
            self.assertIn("stableMiddleWeakWindowBridge", diagnostics)
            self.assertIn("stableMiddleTradeoffFollowup", diagnostics)
            self.assertIn("middleWindowRescueRepair", diagnostics)
            self.assertIn("balancedQualityRepair", diagnostics)
            self.assertIn("sampleRichQualityRepair", diagnostics)
            self.assertIn("balancedSampleDensityRepair", diagnostics)
            self.assertGreater(diagnostics["middleWindowRescueRepair"]["candidateCount"], 0)
            self.assertGreater(diagnostics["nearLiveStabilityRepair"]["candidateCount"], 0)
            self.assertGreater(diagnostics["nearLiveHighYieldNeighborhood"]["candidateCount"], 0)
            self.assertGreater(diagnostics["stableMiddleThirdConfirmation"]["candidateCount"], 0)
            self.assertGreater(diagnostics["stableMiddleWeakWindowConfirmation"]["candidateCount"], 0)
            self.assertGreater(diagnostics["stableMiddleWeakWindowBridge"]["candidateCount"], 0)
            self.assertGreater(diagnostics["stableMiddleTradeoffFollowup"]["candidateCount"], 0)
            self.assertGreater(diagnostics["balancedQualityRepair"]["candidateCount"], 0)
            self.assertGreater(diagnostics["sampleRichQualityRepair"]["candidateCount"], 0)
            self.assertGreater(diagnostics["balancedSampleDensityRepair"]["candidateCount"], 0)
            self.assertIn("highestTradeCountCandidate", diagnostics["balancedSampleDensityRepair"])
            self.assertIn("conclusionZh", diagnostics)

    def test_next_focused_search_plan_explains_tradeoffs_without_execution_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
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
                for index in range(600):
                    price += 90.0 if index % 18 < 9 else -70.0
                    writer.writerow({
                        "epoch": 1800000000 + index * 900,
                        "timestamp": f"2026.06.01 {index:04d}",
                        "open": price - 10,
                        "high": price + 35,
                        "low": price - 35,
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

            report = build_btc_strategy_scan_report(runtime, max_configs=512, top_n=4, write=False)
            plan = report["nextFocusedSearchPlan"]

            self.assertEqual(plan["status"], "BTC_NEXT_FOCUSED_SEARCH_READY")
            if report["status"] == "BTC_SCAN_IMPROVEMENT_FOUND":
                self.assertEqual(
                    report["nextActionZh"],
                    "将 topCandidate 纳入 ChampionRetest 正式候选池，再刷新 Ace/Promotion。",
                )
            else:
                self.assertEqual(report["nextActionZh"], plan["nextActionZh"])
            self.assertIn("highYieldTradeoff", plan)
            self.assertIn("yieldLeaderConfirmationBestTradeoff", plan)
            self.assertIn("yieldLeaderConfirmationImprovesBaseline", plan)
            self.assertIn("yieldLeaderConfirmationOutcomeZh", plan)
            self.assertEqual(plan["recommendedFocusedRetestOrder"], report["recommendedFocusedRetestOrder"])
            self.assertEqual(plan["stabilityFirstTop3StrategyIds"], report["recommendedFocusedRetestOrder"])
            self.assertEqual(plan["topStrategyId"], plan["mostStableTradeoff"]["strategyId"])
            self.assertEqual(plan["nextDistinctStrategyId"], plan["nearLiveStabilityTradeoff"]["strategyId"])
            self.assertEqual(
                plan["repairStrategyId"],
                plan["recommendedFocusedRetestOrder"][2],
            )
            self.assertIn("mostStableTradeoff", plan)
            self.assertIn("nearLiveStabilityTradeoff", plan)
            self.assertIn("nearLiveStabilityRepairBestTradeoff", plan)
            self.assertIn("nearLiveStabilityRepairImprovesBaseline", plan)
            self.assertIn("nearLiveStabilityRepairOutcomeZh", plan)
            self.assertTrue(
                (
                    "next distinct contender" in plan["nearLiveStabilityRepairOutcomeZh"]
                    or "challenger" in plan["nearLiveStabilityRepairOutcomeZh"]
                ),
                plan["nearLiveStabilityRepairOutcomeZh"],
            )
            self.assertIn("nearLiveStabilityFollowupBestTradeoff", plan)
            self.assertIn("nearLiveStabilityFollowupBestStrategyId", plan)
            self.assertIn("nearLiveStabilityFollowupImprovesRepair", plan)
            self.assertIn("nearLiveStabilityFollowupOutcomeZh", plan)
            self.assertTrue(
                (
                    "next distinct contender" in plan["nearLiveStabilityFollowupOutcomeZh"]
                    or "第二候选" in plan["nearLiveStabilityFollowupOutcomeZh"]
                    or "follow-up" in plan["nearLiveStabilityFollowupOutcomeZh"]
                ),
                plan["nearLiveStabilityFollowupOutcomeZh"],
            )
            self.assertIn("nearLiveStabilityRefinementBestTradeoff", plan)
            self.assertIn("nearLiveStabilityRefinementBestStrategyId", plan)
            self.assertIn("nearLiveStabilityRefinementImprovesFollowup", plan)
            self.assertIn("nearLiveStabilityRefinementOutcomeZh", plan)
            self.assertTrue(
                (
                    "next distinct contender" in plan["nearLiveStabilityRefinementOutcomeZh"]
                    or "refinement" in plan["nearLiveStabilityRefinementOutcomeZh"]
                ),
                plan["nearLiveStabilityRefinementOutcomeZh"],
            )
            self.assertIn("nearLiveMiddleWindowFollowupBestTradeoff", plan)
            self.assertIn("nearLiveMiddleWindowFollowupBestStrategyId", plan)
            self.assertIn("nearLiveMiddleWindowFollowupImprovesFollowup", plan)
            self.assertIn("nearLiveMiddleWindowFollowupOutcomeZh", plan)
            self.assertTrue(
                (
                    "next distinct contender" in plan["nearLiveMiddleWindowFollowupOutcomeZh"]
                    or "middle-window" in plan["nearLiveMiddleWindowFollowupOutcomeZh"]
                ),
                plan["nearLiveMiddleWindowFollowupOutcomeZh"],
            )
            self.assertIn("nearLiveSignalRefinementBestTradeoff", plan)
            self.assertIn("nearLiveSignalRefinementBestStrategyId", plan)
            self.assertIn("nearLiveSignalRefinementImprovesContender", plan)
            self.assertIn("nearLiveSignalRefinementOutcomeZh", plan)
            self.assertIn("nearLiveSignalRefinementFollowupBestTradeoff", plan)
            self.assertIn("nearLiveSignalRefinementFollowupBestStrategyId", plan)
            self.assertIn("nearLiveSignalRefinementFollowupImprovesContender", plan)
            self.assertIn("nearLiveSignalRefinementFollowupOutcomeZh", plan)
            self.assertIn("nearLiveHighYieldNeighborhoodBestTradeoff", plan)
            self.assertIn("nearLiveHighYieldNeighborhoodBestStrategyId", plan)
            self.assertIn("nearLiveHighYieldNeighborhoodImprovesAnchor", plan)
            self.assertIn("nearLiveHighYieldNeighborhoodOutcomeZh", plan)
            self.assertIn("nearLiveTempoRefinementBestTradeoff", plan)
            self.assertIn("nearLiveTempoRefinementBestStrategyId", plan)
            self.assertIn("nearLiveTempoRefinementImprovesContender", plan)
            self.assertIn("nearLiveTempoRefinementOutcomeZh", plan)
            self.assertIn("nearLiveStoplossLadderRefinementBestTradeoff", plan)
            self.assertIn("nearLiveStoplossLadderRefinementBestStrategyId", plan)
            self.assertIn("nearLiveStoplossLadderRefinementImprovesContender", plan)
            self.assertIn("nearLiveStoplossLadderRefinementOutcomeZh", plan)
            self.assertIn("nearLiveStoplossLadderFollowupMicroBestTradeoff", plan)
            self.assertIn("nearLiveStoplossLadderFollowupMicroBestStrategyId", plan)
            self.assertIn("nearLiveStoplossLadderFollowupMicroImprovesRefinement", plan)
            self.assertIn("nearLiveStoplossLadderFollowupMicroImprovesContender", plan)
            self.assertIn("nearLiveStoplossLadderFollowupMicroOutcomeZh", plan)
            self.assertIn("nearLiveExitRefinementBestTradeoff", plan)
            self.assertIn("nearLiveExitRefinementBestStrategyId", plan)
            self.assertIn("nearLiveExitRefinementImprovesContender", plan)
            self.assertIn("nearLiveExitRefinementOutcomeZh", plan)
            self.assertIn("nearLiveClusterRefinementBestTradeoff", plan)
            self.assertIn("nearLiveClusterRefinementBestStrategyId", plan)
            self.assertIn("nearLiveClusterRefinementImprovesContender", plan)
            self.assertIn("nearLiveClusterRefinementOutcomeZh", plan)
            self.assertIn("nearLiveMiddleTradeoffBestTradeoff", plan)
            self.assertIn("nearLiveMiddleTradeoffBestStrategyId", plan)
            self.assertIn("nearLiveMiddleTradeoffImprovesContender", plan)
            self.assertIn("nearLiveMiddleTradeoffOutcomeZh", plan)
            self.assertIn("nearLiveMiddleDensityLiftBestTradeoff", plan)
            self.assertIn("nearLiveMiddleDensityLiftBestStrategyId", plan)
            self.assertIn("nearLiveMiddleDensityLiftImprovesContender", plan)
            self.assertIn("nearLiveMiddleDensityLiftOutcomeZh", plan)
            self.assertIn("stableMiddleThirdRepairBestTradeoff", plan)
            self.assertIn("stableMiddleThirdRepairImprovesBaseline", plan)
            self.assertIn("stableMiddleThirdRepairOutcomeZh", plan)
            self.assertIn("stableMiddleThirdFollowupBestTradeoff", plan)
            self.assertIn("stableMiddleThirdFollowupImprovesAggregate", plan)
            self.assertIn("stableMiddleThirdFollowupImprovesWeakWindow", plan)
            self.assertIn("stableMiddleThirdFollowupImprovesRepair", plan)
            self.assertIn("stableMiddleThirdFollowupOutcomeZh", plan)
            self.assertIn("stableMiddleWeakWindowConfirmationBestTradeoff", plan)
            self.assertIn("stableMiddleWeakWindowConfirmationImprovesBaseline", plan)
            self.assertIn("stableMiddleWeakWindowConfirmationOutcomeZh", plan)
            self.assertIn("stableMiddleWeakWindowBridgeBestTradeoff", plan)
            self.assertIn("stableMiddleWeakWindowBridgeImprovesAggregate", plan)
            self.assertIn("stableMiddleWeakWindowBridgeImprovesWeakWindow", plan)
            self.assertIn("stableMiddleWeakWindowBridgeImprovesBaseline", plan)
            self.assertIn("stableMiddleWeakWindowBridgeOutcomeZh", plan)
            self.assertIn("stableMiddleTradeoffFollowupBestTradeoff", plan)
            self.assertIn("stableMiddleTradeoffFollowupBestStrategyId", plan)
            self.assertIn("stableMiddleTradeoffFollowupImprovesBridge", plan)
            self.assertIn("stableMiddleTradeoffFollowupImprovesWeakWindow", plan)
            self.assertIn("stableMiddleTradeoffFollowupImprovesBaseline", plan)
            self.assertIn("stableMiddleTradeoffFollowupOutcomeZh", plan)
            self.assertIn(
                plan["mostStableTradeoff"]["strategyId"],
                plan["stableMiddleThirdRepairOutcomeZh"],
            )
            self.assertIn("sampleRichQualityTradeoff", plan)
            self.assertIn("windowFailureProfiles", plan)
            self.assertIn("recommendations", plan)
            self.assertTrue(plan["recommendations"])
            expected_near_live_basis = (
                plan["nearLiveMiddleDensityLiftBestTradeoff"]["strategyId"]
                if plan["nearLiveMiddleDensityLiftImprovesContender"]
                else (
                    plan["nearLiveSignalRefinementBestTradeoff"]["strategyId"]
                    if plan["nearLiveSignalRefinementImprovesContender"]
                else (
                    plan["nearLiveMiddleTradeoffBestTradeoff"]["strategyId"]
                    if plan["nearLiveMiddleTradeoffImprovesContender"]
                else (
                    plan["nearLiveStabilityTradeoff"]["strategyId"]
                    if plan["nearLiveChallengerConvergedWithYieldFrontier"]
                else (
                    plan["nearLiveMiddleWindowFollowupBestTradeoff"]["strategyId"]
                    if plan["nearLiveMiddleWindowFollowupImprovesFollowup"]
                    else (
                        plan["nearLiveStabilityRefinementBestTradeoff"]["strategyId"]
                        if plan["nearLiveStabilityRefinementImprovesFollowup"]
                        else (
                            plan["nearLiveStabilityFollowupBestTradeoff"]["strategyId"]
                            if plan["nearLiveStabilityFollowupImprovesRepair"]
                            else (
                                plan["nearLiveStabilityRepairBestTradeoff"]["strategyId"]
                                if plan["nearLiveStabilityRepairImprovesBaseline"]
                                else plan["nearLiveStabilityTradeoff"]["strategyId"]
                            )
                        )
                    )
                    )
                )
                )
                )
            )
            self.assertEqual(
                plan["recommendations"][0]["basisStrategyId"],
                expected_near_live_basis,
            )
            if plan["nearLiveChallengerConvergedWithYieldFrontier"]:
                self.assertEqual(
                    plan["recommendations"][0]["baselineStrategyId"],
                    plan["mostStableTradeoff"]["strategyId"],
                )
            elif plan["nearLiveMiddleWindowFollowupImprovesFollowup"]:
                self.assertEqual(
                    plan["recommendations"][0]["baselineStrategyId"],
                    plan["nearLiveStabilityFollowupBestTradeoff"]["strategyId"],
                )
            elif plan["nearLiveStabilityRefinementImprovesFollowup"]:
                self.assertEqual(
                    plan["recommendations"][0]["baselineStrategyId"],
                    plan["nearLiveStabilityFollowupBestTradeoff"]["strategyId"],
                )
            elif plan["nearLiveStabilityFollowupImprovesRepair"]:
                self.assertEqual(
                    plan["recommendations"][0]["baselineStrategyId"],
                    plan["nearLiveStabilityRepairBestTradeoff"]["strategyId"],
                )
            elif plan["nearLiveStabilityRepairImprovesBaseline"]:
                self.assertEqual(
                    plan["recommendations"][0]["baselineStrategyId"],
                    plan["nearLiveStabilityTradeoff"]["strategyId"],
                )
            self.assertEqual(plan["recommendations"][0]["priority"], 1)
            expected_high_yield_basis = (
                plan["nearLiveHighYieldNeighborhoodBestTradeoff"]["strategyId"]
                if plan["nearLiveHighYieldNeighborhoodImprovesAnchor"]
                else plan["highYieldTradeoff"]["strategyId"]
            )
            self.assertEqual(plan["recommendations"][1]["basisStrategyId"], expected_high_yield_basis)
            self.assertEqual(plan["recommendations"][1]["priority"], 2)
            self.assertEqual(plan["recommendations"][2]["id"], "sample_rich_quality_bridge")
            self.assertEqual(plan["recommendations"][2]["priority"], 3)
            self.assertEqual(plan["recommendations"][3]["id"], "stable_champion_middle_third_rescue")
            self.assertEqual(plan["recommendations"][3]["priority"], 4)
            self.assertTrue(
                any(row["id"] == "sample_rich_quality_bridge" for row in plan["recommendations"]),
                plan["recommendations"],
            )
            self.assertFalse(plan["safety"]["orderSendAllowed"])
            self.assertFalse(plan["safety"]["livePresetMutationAllowed"])
            self.assertTrue(
                "near-live" in plan["nextActionZh"]
                or "next distinct contender" in plan["nextActionZh"]
                or "challenger" in plan["nextActionZh"]
            )
            self.assertIn("sample-rich bridge", plan["nextActionZh"])
            self.assertIn("避免只靠缩短冷却", plan["nextActionZh"])

    def test_tradeoff_repair_moves_ahead_of_sample_rich_when_it_improves_baseline(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.3834,
                        "tradeCount": 15,
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    }
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "validWindowCount": 4,
                "majorWindowFailureCount": 2,
                "fullWindowMetrics": {"pnlUsd": 52.7, "sharpe": 1.3613, "tradeCount": 74},
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.3343,
                        "tradeCount": 21,
                        "blockers": ["HFM_SHARPE_LT_MIN"],
                    }
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                "validWindowCount": 3,
                "majorWindowFailureCount": 3,
                "fullWindowMetrics": {"pnlUsd": 72.4, "sharpe": 1.987, "tradeCount": 47},
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.7501,
                        "tradeCount": 14,
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    }
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[2]},
            "sampleRichQualityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                    "validWindowCount": 3,
                    "fullWindowMetrics": {"pnlUsd": 40.2, "sharpe": 1.77, "tradeCount": 81},
                }
            },
            "balancedSampleDensityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_density_only_0001",
                    "validWindowCount": 2,
                    "fullWindowMetrics": {"pnlUsd": 22.0, "sharpe": 0.9, "tradeCount": 100},
                }
            },
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_bridge_0015",
                    "validWindowCount": 2,
                    "fullWindowMetrics": {"pnlUsd": 29.1, "sharpe": 1.0089, "tradeCount": 70},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.45,
                            "tradeCount": 18,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleTradeoffFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0025",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 48.3, "sharpe": 1.5646, "tradeCount": 80},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.5409,
                            "tradeCount": 19,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["recommendations"][2]["id"], "stable_champion_middle_third_rescue")
        self.assertEqual(plan["recommendations"][2]["priority"], 3)
        self.assertEqual(plan["recommendations"][3]["id"], "sample_rich_quality_bridge")
        self.assertEqual(plan["recommendations"][3]["priority"], 4)
        self.assertEqual(
            plan["stableMiddleTradeoffFollowupBestStrategyId"],
            plan["stableMiddleTradeoffFollowupBestTradeoff"]["strategyId"],
        )
        self.assertIn("tradeoff 版本", plan["recommendations"][2]["reasonZh"])
        self.assertIn("第四顺位", plan["recommendations"][3]["reasonZh"])
        self.assertIn("第三线弱窗口修复路径", plan["nextActionZh"])

    def test_converged_stable_and_yield_frontier_promotes_next_distinct_near_live_contender(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 79},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_followup_0015",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 53.9, "sharpe": 1.74, "tradeCount": 79},
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                }
            },
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["nearLiveStabilityTradeoff"]["strategyId"], "hfm_crypto_btc_near_live_middle_window_0021")
        self.assertEqual(plan["recommendations"][0]["id"], "near_live_stability_challenger")
        self.assertEqual(plan["recommendations"][0]["basisStrategyId"], "hfm_crypto_btc_near_live_middle_window_0021")
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_middle_window_0003")
        self.assertIn("next distinct contender", plan["recommendations"][0]["reasonZh"])

    def test_near_live_cluster_refinement_moves_ahead_of_converged_contender_when_it_improves_it(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveClusterRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_cluster_refinement_0007",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.7, "sharpe": 1.792, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.571, "tradeCount": 20, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["nearLiveClusterRefinementBestStrategyId"], "hfm_crypto_btc_near_live_cluster_refinement_0007")
        self.assertTrue(plan["nearLiveClusterRefinementImprovesContender"])
        self.assertEqual(plan["recommendations"][0]["basisStrategyId"], "hfm_crypto_btc_near_live_cluster_refinement_0007")
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_middle_window_0021")
        self.assertIn("converged-cluster refinement", plan["recommendations"][0]["reasonZh"])
        self.assertIn("converged-cluster refinement", plan["nextActionZh"])

    def test_converged_high_yield_recommendation_uses_near_live_parameter_focus(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5947, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5947, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_balanced_quality_repair_0005",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 41.0, "sharpe": 1.31, "tradeCount": 72},
                    "parameters": {
                        "bias": "both",
                        "takeProfitPriceMove": 600.0,
                        "stopLossPriceMove": 500.0,
                        "maxHoldBars": 24,
                        "cooldownBars": 8,
                    },
                }
            },
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {"bestByStabilityRank": {}},
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["recommendations"][1]["id"], "quality_first_high_yield_neighborhood")
        self.assertEqual(plan["recommendations"][1]["basisStrategyId"], "hfm_crypto_btc_near_live_middle_window_0003")
        self.assertEqual(
            plan["recommendations"][1]["parameterFocus"],
            [
                "preserve_short_bias_signal_kernel",
                "keep_take_profit_425_to_475",
                "keep_stop_loss_300_to_325",
                "nudge_max_hold_8_to_9",
                "nudge_cooldown_4_to_5",
            ],
        )
        self.assertIn("near-live 主锚点", plan["recommendations"][1]["reasonZh"])

    def test_near_live_signal_refinement_moves_ahead_of_converged_contender_when_it_improves_it(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_signal_refinement_0008",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.6, "sharpe": 1.79, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.571, "tradeCount": 20, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["nearLiveSignalRefinementBestStrategyId"], "hfm_crypto_btc_near_live_signal_refinement_0008")
        self.assertTrue(plan["nearLiveSignalRefinementImprovesContender"])
        self.assertEqual(plan["recommendations"][0]["basisStrategyId"], "hfm_crypto_btc_near_live_signal_refinement_0008")
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_middle_window_0021")
        self.assertIn("signal refinement", plan["recommendations"][0]["reasonZh"])
        self.assertIn("signal refinement", plan["nextActionZh"])

    def test_near_live_signal_refinement_followup_moves_ahead_of_converged_contender_when_it_improves_it(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinementFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_signal_refinement_followup_0004",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.8, "sharpe": 1.81, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.581, "tradeCount": 20, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveSignalRefinementFollowupBestStrategyId"],
            "hfm_crypto_btc_near_live_signal_refinement_followup_0004",
        )
        self.assertTrue(plan["nearLiveSignalRefinementFollowupImprovesContender"])
        self.assertEqual(
            plan["recommendations"][0]["basisStrategyId"],
            "hfm_crypto_btc_near_live_signal_refinement_followup_0004",
        )
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_middle_window_0021")
        self.assertIn("signal-kernel", plan["recommendations"][0]["reasonZh"])
        self.assertIn("signal", plan["nextActionZh"])

    def test_near_live_high_yield_neighborhood_promotes_local_leader_when_it_improves_anchor(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinementFollowup": {"bestByStabilityRank": {}},
            "nearLiveHighYieldNeighborhood": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_0003",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 55.1, "sharpe": 1.7861, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.548, "tradeCount": 20, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveHighYieldNeighborhoodBestStrategyId"],
            "hfm_crypto_btc_near_live_high_yield_0003",
        )
        self.assertTrue(plan["nearLiveHighYieldNeighborhoodImprovesAnchor"])
        self.assertEqual(
            plan["recommendations"][1]["basisStrategyId"],
            "hfm_crypto_btc_near_live_high_yield_0003",
        )
        self.assertEqual(
            plan["recommendations"][1]["baselineStrategyId"],
            "hfm_crypto_btc_near_live_middle_window_0003",
        )
        self.assertIn("局部 leader", plan["recommendations"][1]["reasonZh"])

    def test_near_live_high_yield_neighborhood_followup_promotes_tighter_local_leader(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinementFollowup": {"bestByStabilityRank": {}},
            "nearLiveHighYieldNeighborhood": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_0004",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.5947, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveHighYieldNeighborhoodFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_followup_0002",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.5, "sharpe": 1.786, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.601, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveHighYieldNeighborhoodFollowupBestStrategyId"],
            "hfm_crypto_btc_near_live_high_yield_followup_0002",
        )
        self.assertTrue(plan["nearLiveHighYieldNeighborhoodFollowupImprovesNeighborhood"])
        self.assertEqual(
            plan["recommendations"][1]["basisStrategyId"],
            "hfm_crypto_btc_near_live_high_yield_followup_0002",
        )
        self.assertEqual(
            plan["recommendations"][1]["baselineStrategyId"],
            "hfm_crypto_btc_near_live_middle_window_0003",
        )
        self.assertIn("更窄的 near-live 邻域", plan["recommendations"][1]["reasonZh"])

    def test_near_live_high_yield_neighborhood_followup_micro_promotes_ultra_local_leader(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinementFollowup": {"bestByStabilityRank": {}},
            "nearLiveHighYieldNeighborhood": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_0004",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.5947, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveHighYieldNeighborhoodFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_followup_0002",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.5, "sharpe": 1.786, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.601, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveHighYieldNeighborhoodFollowupMicro": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_followup_micro_0003",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.7, "sharpe": 1.787, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.612, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveHighYieldNeighborhoodFollowupMicroBestStrategyId"],
            "hfm_crypto_btc_near_live_high_yield_followup_micro_0003",
        )
        self.assertTrue(plan["nearLiveHighYieldNeighborhoodFollowupMicroImprovesFollowup"])
        self.assertEqual(
            plan["recommendations"][1]["basisStrategyId"],
            "hfm_crypto_btc_near_live_high_yield_followup_micro_0003",
        )
        self.assertIn("ultra-local leader", plan["recommendations"][1]["reasonZh"])

    def test_near_live_high_yield_neighborhood_followup_micro_followup_promotes_31875_pocket(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinementFollowup": {"bestByStabilityRank": {}},
            "nearLiveHighYieldNeighborhood": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_0004",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.5947, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveHighYieldNeighborhoodFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_followup_0002",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.5, "sharpe": 1.786, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.601, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveHighYieldNeighborhoodFollowupMicro": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_followup_micro_0003",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.7, "sharpe": 1.787, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.612, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveHighYieldNeighborhoodFollowupMicroFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_high_yield_followup_micro_followup_0004",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.8, "sharpe": 1.788, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.618, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveHighYieldNeighborhoodFollowupMicroFollowupBestStrategyId"],
            "hfm_crypto_btc_near_live_high_yield_followup_micro_followup_0004",
        )
        self.assertTrue(plan["nearLiveHighYieldNeighborhoodFollowupMicroFollowupImprovesMicro"])
        self.assertEqual(
            plan["recommendations"][1]["basisStrategyId"],
            "hfm_crypto_btc_near_live_high_yield_followup_micro_followup_0004",
        )
        self.assertIn("318.75", plan["recommendations"][1]["reasonZh"])

    def test_near_live_stoploss_ladder_followup_moves_ahead_of_converged_contender_when_it_improves_it(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.3, "sharpe": 1.7862, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.548, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveStoplossLadderFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_followup_0004",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.7, "sharpe": 1.792, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.571, "tradeCount": 20, "blockers": []},
                    ],
                }
            },
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveStoplossLadderFollowupBestStrategyId"],
            "hfm_crypto_btc_near_live_stoploss_ladder_followup_0004",
        )
        self.assertTrue(plan["nearLiveStoplossLadderFollowupImprovesRefinement"])
        self.assertEqual(plan["recommendations"][0]["basisStrategyId"], "hfm_crypto_btc_near_live_stoploss_ladder_followup_0004")
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_middle_window_0021")
        self.assertIn("stop-loss ladder", plan["recommendations"][0]["reasonZh"])
        self.assertIn("stop-loss ladder", plan["nextActionZh"])

    def test_near_live_stoploss_ladder_followup_micro_moves_ahead_of_converged_contender_when_it_improves_it(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinementFollowup": {"bestByStabilityRank": {}},
            "nearLiveHighYieldNeighborhood": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.3, "sharpe": 1.7862, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.548, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveStoplossLadderFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_followup_0002",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.3, "sharpe": 1.7864, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.552, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveStoplossLadderFollowupMicro": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_0003",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.9, "sharpe": 1.793, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.579, "tradeCount": 20, "blockers": []},
                    ],
                }
            },
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinementFollowup": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinementMicro": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveStoplossLadderFollowupMicroBestStrategyId"],
            "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_0003",
        )
        self.assertTrue(plan["nearLiveStoplossLadderFollowupMicroImprovesRefinement"])
        self.assertTrue(plan["nearLiveStoplossLadderFollowupMicroImprovesContender"])
        self.assertEqual(
            plan["recommendations"][0]["basisStrategyId"],
            "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_0003",
        )
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_middle_window_0021")
        self.assertIn("306.25", plan["recommendations"][0]["reasonZh"])

    def test_near_live_stoploss_ladder_followup_micro_followup_becomes_basis_when_it_improves_micro(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinementFollowup": {"bestByStabilityRank": {}},
            "nearLiveHighYieldNeighborhood": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_0001",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.3, "sharpe": 1.7862, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.548, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveStoplossLadderFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_followup_0004",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.3, "sharpe": 1.7864, "tradeCount": 80},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.552, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                    ],
                }
            },
            "nearLiveStoplossLadderFollowupMicro": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_0003",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 55.0, "sharpe": 1.794, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.579, "tradeCount": 20, "blockers": []},
                    ],
                }
            },
            "nearLiveStoplossLadderFollowupMicroFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_followup_0001",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 55.2, "sharpe": 1.796, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.586, "tradeCount": 20, "blockers": []},
                    ],
                }
            },
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinementFollowup": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinementMicro": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId"],
            "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_followup_0001",
        )
        self.assertTrue(plan["nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro"])
        self.assertTrue(plan["nearLiveStoplossLadderFollowupMicroFollowupImprovesContender"])
        self.assertEqual(
            plan["recommendations"][0]["basisStrategyId"],
            "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_followup_0001",
        )
        self.assertEqual(
            plan["recommendations"][0]["baselineStrategyId"],
            "hfm_crypto_btc_near_live_middle_window_0021",
        )
        self.assertIn("318.75", plan["recommendations"][0]["reasonZh"])

    def test_near_live_middle_window_contender_micro_can_reclaim_contender_slot(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_stoploss_ladder_followup_micro_followup_0004",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 55.5, "sharpe": 1.801, "tradeCount": 82},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 318.75,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.579, "tradeCount": 20, "blockers": []},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]},
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[1]},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinementFollowup": {"bestByStabilityRank": {}},
            "nearLiveHighYieldNeighborhood": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderFollowup": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderFollowupMicro": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderFollowupMicroFollowup": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowContenderMicro": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_contender_micro_0004",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 55.0, "sharpe": 1.794, "tradeCount": 81},
                    "windowSummary": [
                        {"window": "middle_third", "sharpe": 0.584, "tradeCount": 20, "blockers": []},
                    ],
                }
            },
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinement": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinementFollowup": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinementMicro": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["nearLiveMiddleWindowContenderMicroBestStrategyId"],
            "hfm_crypto_btc_near_live_middle_window_contender_micro_0004",
        )
        self.assertTrue(plan["nearLiveMiddleWindowContenderMicroImprovesContender"])
        self.assertEqual(
            plan["recommendations"][0]["basisStrategyId"],
            "hfm_crypto_btc_near_live_middle_window_contender_micro_0004",
        )
        self.assertEqual(
            plan["recommendations"][0]["baselineStrategyId"],
            "hfm_crypto_btc_near_live_middle_window_0003",
        )
        self.assertIn("325.0", plan["recommendations"][0]["reasonZh"])

    def test_tradeoff_repair_moves_ahead_of_sample_rich_when_challenger_converges_with_yield(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.3834,
                        "tradeCount": 15,
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    }
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.5409,
                        "tradeCount": 19,
                        "blockers": ["HFM_SHARPE_LT_MIN"],
                    }
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[1]},
            "sampleRichQualityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                    "validWindowCount": 3,
                    "fullWindowMetrics": {"pnlUsd": 40.2, "sharpe": 1.77, "tradeCount": 81},
                }
            },
            "balancedSampleDensityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_density_only_0001",
                    "validWindowCount": 2,
                    "fullWindowMetrics": {"pnlUsd": 22.0, "sharpe": 0.9, "tradeCount": 100},
                }
            },
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_followup_0015",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 53.9, "sharpe": 1.74, "tradeCount": 79},
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.49,
                            "tradeCount": 18,
                            "blockers": ["HFM_SHARPE_LT_MIN"],
                        }
                    ],
                }
            },
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.5409,
                            "tradeCount": 19,
                            "blockers": ["HFM_SHARPE_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_bridge_0015",
                    "validWindowCount": 2,
                    "fullWindowMetrics": {"pnlUsd": 29.1, "sharpe": 1.0089, "tradeCount": 70},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.45,
                            "tradeCount": 18,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleTradeoffFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0046",
                    "validWindowCount": 3,
                    "fullWindowMetrics": {"pnlUsd": 29.0, "sharpe": 1.0329, "tradeCount": 64},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.41,
                            "tradeCount": 17,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertTrue(plan["nearLiveChallengerConvergedWithYieldFrontier"])
        self.assertEqual(plan["recommendations"][2]["id"], "stable_champion_middle_third_rescue")
        self.assertEqual(plan["recommendations"][2]["priority"], 3)
        self.assertEqual(plan["recommendations"][3]["id"], "sample_rich_quality_bridge")
        self.assertEqual(plan["recommendations"][3]["priority"], 4)
        self.assertIn("收敛到同一参数簇", plan["recommendations"][2]["reasonZh"])
        self.assertIn("next distinct near-live contender", plan["nextActionZh"])
        self.assertIn("sample-rich bridge 退到第四线", plan["nextActionZh"])

    def test_tradeoff_repair_stays_ahead_of_sample_rich_in_converged_runtime_even_without_bridge_improvement(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.3834,
                        "tradeCount": 15,
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    }
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 54.2343, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.3834,
                        "tradeCount": 15,
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    }
                ],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                    "validWindowCount": 3,
                    "fullWindowMetrics": {"pnlUsd": 40.2, "sharpe": 1.77, "tradeCount": 81},
                }
            },
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_followup_0015",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 53.9, "sharpe": 1.74, "tradeCount": 79},
                    "parameters": {
                        "bias": "short",
                        "takeProfitPriceMove": 450.0,
                        "stopLossPriceMove": 325.0,
                        "maxHoldBars": 8,
                        "cooldownBars": 4,
                    },
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.49,
                            "tradeCount": 18,
                            "blockers": ["HFM_SHARPE_LT_MIN"],
                        }
                    ],
                }
            },
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {"bestByStabilityRank": {}},
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_bridge_0003",
                    "validWindowCount": 2,
                    "fullWindowMetrics": {"pnlUsd": 29.1, "sharpe": 1.0089, "tradeCount": 70},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.45,
                            "tradeCount": 18,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleTradeoffFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0001",
                    "validWindowCount": 0,
                    "fullWindowMetrics": {"pnlUsd": 5.7539, "sharpe": 0.2026, "tradeCount": 75},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.2026,
                            "tradeCount": 75,
                            "blockers": ["HFM_MIDDLE_THIRD_NOT_FULLY_REPAIRED"],
                        }
                    ],
                }
            },
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertTrue(plan["nearLiveChallengerConvergedWithYieldFrontier"])
        self.assertEqual(plan["recommendations"][2]["id"], "stable_champion_middle_third_rescue")
        self.assertEqual(plan["repairStrategyId"], "hfm_crypto_btc_stable_middle_bridge_0003")
        self.assertEqual(plan["recommendations"][2]["basisStrategyId"], "hfm_crypto_btc_stable_middle_bridge_0003")
        self.assertEqual(plan["recommendations"][2]["priority"], 3)
        self.assertEqual(plan["recommendations"][3]["id"], "sample_rich_quality_bridge")
        self.assertEqual(plan["recommendations"][3]["priority"], 4)
        self.assertIn("bridge 版本", plan["recommendations"][2]["reasonZh"])
        self.assertIn("next distinct near-live contender", plan["nextActionZh"])
        self.assertIn("sample-rich bridge 退到第四线", plan["nextActionZh"])
        self.assertIn("stable middle weak-window bridge", plan["nextActionZh"])
        self.assertNotIn("stable middle tradeoff follow-up", plan["nextActionZh"])
        self.assertNotIn("near-live stability follow-up", plan["nextActionZh"])

    def test_converged_frontier_uses_followup_as_third_line_when_tradeoff_is_weaker(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.5947,
                        "tradeCount": 19,
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    }
                ],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [
                    {
                        "window": "middle_third",
                        "sharpe": 0.5947,
                        "tradeCount": 19,
                        "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                    }
                ],
            },
        ]
        diagnostics = {
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_sample_rich_quality_0001",
                    "validWindowCount": 3,
                    "fullWindowMetrics": {"pnlUsd": 40.2, "sharpe": 1.77, "tradeCount": 81},
                }
            },
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {"bestByStabilityRank": {}},
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_0002",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 38.0, "sharpe": 1.2945, "tradeCount": 69},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.52,
                            "tradeCount": 19,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_bridge_0003",
                    "validWindowCount": 0,
                    "fullWindowMetrics": {"pnlUsd": 18.3, "sharpe": 0.6698, "tradeCount": 75},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.45,
                            "tradeCount": 18,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleTradeoffFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0001",
                    "validWindowCount": 0,
                    "fullWindowMetrics": {"pnlUsd": 5.75, "sharpe": 0.2026, "tradeCount": 75},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.2026,
                            "tradeCount": 75,
                            "blockers": ["HFM_MIDDLE_THIRD_NOT_FULLY_REPAIRED"],
                        }
                    ],
                }
            },
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["repairStrategyId"], "hfm_crypto_btc_stable_middle_followup_0002")
        self.assertEqual(
            plan["recommendedFocusedRetestOrder"],
            [
                "hfm_crypto_btc_near_live_middle_window_0003",
                "hfm_crypto_btc_near_live_middle_window_0021",
                "hfm_crypto_btc_stable_middle_followup_0002",
            ],
        )
        self.assertEqual(plan["repairStrategyLabelZh"], "stable middle-third aggregate-stability fallback")
        self.assertEqual(plan["repairStrategyRoleZh"], "第三条 distinct 稳定 fallback 路径")
        self.assertIn("aggregate-stability candidate", plan["recommendations"][2]["reasonZh"])
        self.assertIn("第三条 distinct 稳定 fallback 路径", plan["nextActionZh"])

    def test_stable_middle_followup_refinement_can_replace_followup_as_third_line(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [],
            },
        ]
        diagnostics = {
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {"bestByStabilityRank": {}},
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_0002",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 38.0, "sharpe": 1.2945, "tradeCount": 69},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.52,
                            "tradeCount": 19,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleThirdFollowupRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_0004",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 41.2, "sharpe": 1.402, "tradeCount": 72},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.58,
                            "tradeCount": 19,
                            "blockers": ["HFM_SHARPE_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_tradeoff_0001",
                    "validWindowCount": 0,
                    "fullWindowMetrics": {"pnlUsd": 5.75, "sharpe": 0.2026, "tradeCount": 75},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.2026,
                            "tradeCount": 75,
                            "blockers": ["HFM_MIDDLE_THIRD_NOT_FULLY_REPAIRED"],
                        }
                    ],
                }
            },
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["stableMiddleThirdFollowupRefinementBestStrategyId"],
            "hfm_crypto_btc_stable_middle_followup_refinement_0004",
        )
        self.assertTrue(plan["stableMiddleThirdFollowupRefinementImprovesFollowup"])
        self.assertEqual(plan["repairStrategyId"], "hfm_crypto_btc_stable_middle_followup_refinement_0004")
        self.assertEqual(plan["repairStrategyLabelZh"], "stable middle-third aggregate-stability refinement")
        self.assertIn("refinement", plan["recommendations"][2]["reasonZh"])

    def test_stable_middle_followup_refinement_followup_can_replace_refinement_as_third_line(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [],
            },
        ]
        diagnostics = {
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {"bestByStabilityRank": {}},
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_0002",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 38.0, "sharpe": 1.2945, "tradeCount": 69},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.52,
                            "tradeCount": 19,
                            "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleThirdFollowupRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_0004",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 41.2, "sharpe": 1.402, "tradeCount": 72},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.58,
                            "tradeCount": 19,
                            "blockers": ["HFM_SHARPE_LT_MIN"],
                        }
                    ],
                }
            },
            "stableMiddleThirdFollowupRefinementFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_followup_0003",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 42.4, "sharpe": 1.448, "tradeCount": 74},
                    "windowSummary": [
                        {
                            "window": "middle_third",
                            "sharpe": 0.61,
                            "tradeCount": 20,
                            "blockers": [],
                        }
                    ],
                }
            },
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["stableMiddleThirdFollowupRefinementFollowupBestStrategyId"],
            "hfm_crypto_btc_stable_middle_followup_refinement_followup_0003",
        )
        self.assertTrue(plan["stableMiddleThirdFollowupRefinementFollowupImprovesRefinement"])
        self.assertEqual(
            plan["repairStrategyId"],
            "hfm_crypto_btc_stable_middle_followup_refinement_followup_0003",
        )
        self.assertEqual(
            plan["repairStrategyLabelZh"],
            "stable middle-third aggregate-stability refinement follow-up",
        )
        self.assertIn("refinement 邻域", plan["recommendations"][2]["reasonZh"])

    def test_stable_middle_followup_refinement_micro_can_replace_refinement_as_third_line(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [],
            },
        ]
        diagnostics = {
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderFollowup": {"bestByStabilityRank": {}},
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_0002",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 38.0, "sharpe": 1.2945, "tradeCount": 69},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.52, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]}],
                }
            },
            "stableMiddleThirdFollowupRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_0003",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 40.4, "sharpe": 1.3906, "tradeCount": 69},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.57, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]}],
                }
            },
            "stableMiddleThirdFollowupRefinementFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_followup_0006",
                    "validWindowCount": 3,
                    "fullWindowMetrics": {"pnlUsd": 33.9, "sharpe": 1.1939, "tradeCount": 58},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.49, "tradeCount": 17, "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"]}],
                }
            },
            "stableMiddleThirdFollowupRefinementMicro": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_micro_0002",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 41.3, "sharpe": 1.431, "tradeCount": 72},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.61, "tradeCount": 20, "blockers": []}],
                }
            },
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["stableMiddleThirdFollowupRefinementMicroBestStrategyId"],
            "hfm_crypto_btc_stable_middle_followup_refinement_micro_0002",
        )
        self.assertTrue(plan["stableMiddleThirdFollowupRefinementMicroImprovesRefinement"])
        self.assertEqual(
            plan["repairStrategyId"],
            "hfm_crypto_btc_stable_middle_followup_refinement_micro_0002",
        )
        self.assertEqual(
            plan["repairStrategyLabelZh"],
            "stable middle-third micro-refinement",
        )
        self.assertIn("micro-refinement", plan["recommendations"][2]["reasonZh"])

    def test_stable_middle_followup_refinement_micro_followup_can_replace_refinement_as_third_line(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0003",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 325.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_near_live_middle_window_0021",
                "validWindowCount": 5,
                "majorWindowFailureCount": 0,
                "fullWindowMetrics": {"pnlUsd": 54.2, "sharpe": 1.7858, "tradeCount": 80},
                "parameters": {
                    "bias": "short",
                    "takeProfitPriceMove": 450.0,
                    "stopLossPriceMove": 300.0,
                    "maxHoldBars": 8,
                    "cooldownBars": 4,
                },
                "windowSummary": [],
            },
        ]
        diagnostics = {
            "nearLiveMiddleWindowFollowup": {"bestByStabilityRank": ranked[0]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {"bestByStabilityRank": {}},
            "nearLiveStabilityFollowup": {"bestByStabilityRank": {}},
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveClusterRefinement": {"bestByStabilityRank": {}},
            "nearLiveSignalRefinement": {"bestByStabilityRank": {}},
            "nearLiveTempoRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderRefinement": {"bestByStabilityRank": {}},
            "nearLiveStoplossLadderFollowup": {"bestByStabilityRank": {}},
            "nearLiveExitRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleTradeoff": {"bestByStabilityRank": {}},
            "nearLiveMiddleDensityLift": {"bestByStabilityRank": {}},
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_0002",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 38.0, "sharpe": 1.2945, "tradeCount": 69},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.52, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]}],
                }
            },
            "stableMiddleThirdFollowupRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_0003",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 40.4, "sharpe": 1.3906, "tradeCount": 69},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.57, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]}],
                }
            },
            "stableMiddleThirdFollowupRefinementFollowup": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowupRefinementMicro": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_micro_0006",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.55, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN"]}],
                }
            },
            "stableMiddleThirdFollowupRefinementMicroFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_stable_middle_followup_refinement_micro_followup_0002",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 41.6, "sharpe": 1.437, "tradeCount": 72},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.6, "tradeCount": 20, "blockers": []}],
                }
            },
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(
            plan["stableMiddleThirdFollowupRefinementMicroFollowupBestStrategyId"],
            "hfm_crypto_btc_stable_middle_followup_refinement_micro_followup_0002",
        )
        self.assertTrue(plan["stableMiddleThirdFollowupRefinementMicroFollowupImprovesMicro"])
        self.assertTrue(plan["stableMiddleThirdFollowupRefinementMicroFollowupImprovesRefinement"])
        self.assertEqual(
            plan["repairStrategyId"],
            "hfm_crypto_btc_stable_middle_followup_refinement_micro_followup_0002",
        )
        self.assertEqual(
            plan["repairStrategyLabelZh"],
            "stable middle-third micro-followup",
        )
        self.assertIn("micro-followup", plan["recommendations"][2]["reasonZh"])

    def test_near_live_followup_moves_ahead_of_repair_when_it_improves_repair(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "validWindowCount": 4,
                "majorWindowFailureCount": 2,
                "fullWindowMetrics": {"pnlUsd": 52.7, "sharpe": 1.3613, "tradeCount": 74},
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                "validWindowCount": 3,
                "majorWindowFailureCount": 3,
                "fullWindowMetrics": {"pnlUsd": 72.4, "sharpe": 1.987, "tradeCount": 47},
                "windowSummary": [],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[2]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stability_0003",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 48.3, "sharpe": 1.5646, "tradeCount": 80},
                }
            },
            "nearLiveStabilityFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_followup_0007",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 50.1, "sharpe": 1.61, "tradeCount": 81},
                }
            },
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["nearLiveStabilityFollowupBestStrategyId"], "hfm_crypto_btc_near_live_followup_0007")
        self.assertTrue(plan["nearLiveStabilityFollowupImprovesRepair"])
        self.assertEqual(plan["recommendations"][0]["basisStrategyId"], "hfm_crypto_btc_near_live_followup_0007")
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_stability_0003")
        self.assertIn("follow-up", plan["recommendations"][0]["reasonZh"])
        self.assertIn("near-live stability follow-up", plan["nextActionZh"])

    def test_near_live_refinement_moves_ahead_of_followup_when_it_improves_followup(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "validWindowCount": 4,
                "majorWindowFailureCount": 2,
                "fullWindowMetrics": {"pnlUsd": 52.7, "sharpe": 1.3613, "tradeCount": 74},
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                "validWindowCount": 3,
                "majorWindowFailureCount": 3,
                "fullWindowMetrics": {"pnlUsd": 72.4, "sharpe": 1.987, "tradeCount": 47},
                "windowSummary": [],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[2]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stability_0003",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 48.3, "sharpe": 1.5646, "tradeCount": 80},
                }
            },
            "nearLiveStabilityFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_followup_0007",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 50.1, "sharpe": 1.61, "tradeCount": 81},
                }
            },
            "nearLiveStabilityRefinement": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_refinement_0005",
                    "validWindowCount": 5,
                    "fullWindowMetrics": {"pnlUsd": 50.4, "sharpe": 1.72, "tradeCount": 82},
                }
            },
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["nearLiveStabilityRefinementBestStrategyId"], "hfm_crypto_btc_near_live_refinement_0005")
        self.assertTrue(plan["nearLiveStabilityRefinementImprovesFollowup"])
        self.assertEqual(plan["recommendations"][0]["basisStrategyId"], "hfm_crypto_btc_near_live_refinement_0005")
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_followup_0007")
        self.assertIn("refinement", plan["recommendations"][0]["reasonZh"])
        self.assertIn("near-live stability refinement", plan["nextActionZh"])

    def test_near_live_middle_window_moves_ahead_of_followup_when_it_improves_weak_window(self) -> None:
        ranked = [
            {
                "strategyId": "hfm_crypto_btc_tpsl_0302",
                "validWindowCount": 5,
                "majorWindowFailureCount": 1,
                "fullWindowMetrics": {"pnlUsd": 38.7, "sharpe": 1.326, "tradeCount": 69},
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_sample_balanced_both_shadow_v1",
                "validWindowCount": 4,
                "majorWindowFailureCount": 2,
                "fullWindowMetrics": {"pnlUsd": 52.7, "sharpe": 1.3613, "tradeCount": 74},
                "windowSummary": [],
            },
            {
                "strategyId": "hfm_crypto_btc_yield_balanced_both_shadow_v1",
                "validWindowCount": 3,
                "majorWindowFailureCount": 3,
                "fullWindowMetrics": {"pnlUsd": 72.4, "sharpe": 1.987, "tradeCount": 47},
                "windowSummary": [],
            },
        ]
        diagnostics = {
            "balancedQualityRepair": {"bestByStabilityRank": ranked[2]},
            "sampleRichQualityRepair": {"bestByStabilityRank": {}},
            "balancedSampleDensityRepair": {"bestByStabilityRank": {}},
            "yieldLeaderConfirmation": {"bestByStabilityRank": {}},
            "nearLiveStabilityRepair": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_stability_0003",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 48.3, "sharpe": 1.5646, "tradeCount": 80},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.5409, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"]}],
                }
            },
            "nearLiveStabilityFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_followup_0007",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 50.1, "sharpe": 1.61, "tradeCount": 81},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.5947, "tradeCount": 19, "blockers": ["HFM_SHARPE_LT_MIN", "HFM_TRADE_COUNT_LT_MIN"]}],
                }
            },
            "nearLiveStabilityRefinement": {"bestByStabilityRank": {}},
            "nearLiveMiddleWindowFollowup": {
                "bestByStabilityRank": {
                    "strategyId": "hfm_crypto_btc_near_live_middle_window_0005",
                    "validWindowCount": 4,
                    "fullWindowMetrics": {"pnlUsd": 49.9, "sharpe": 1.6, "tradeCount": 82},
                    "windowSummary": [{"window": "middle_third", "sharpe": 0.71, "tradeCount": 20, "blockers": ["HFM_SHARPE_LT_MIN"]}],
                }
            },
            "stableMiddleThirdConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleThirdFollowup": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowConfirmation": {"bestByStabilityRank": {}},
            "stableMiddleWeakWindowBridge": {"bestByStabilityRank": {}},
            "stableMiddleTradeoffFollowup": {"bestByStabilityRank": {}},
        }

        plan = _next_focused_search_plan(ranked, diagnostics)

        self.assertEqual(plan["nearLiveMiddleWindowFollowupBestStrategyId"], "hfm_crypto_btc_near_live_middle_window_0005")
        self.assertTrue(plan["nearLiveMiddleWindowFollowupImprovesFollowup"])
        self.assertEqual(plan["recommendations"][0]["basisStrategyId"], "hfm_crypto_btc_near_live_middle_window_0005")
        self.assertEqual(plan["recommendations"][0]["baselineStrategyId"], "hfm_crypto_btc_near_live_followup_0007")
        self.assertIn("middle-window", plan["recommendations"][0]["reasonZh"])
        self.assertIn("near-live middle-window follow-up", plan["nextActionZh"])


if __name__ == "__main__":
    unittest.main()
