import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from tools.usdjpy_live_loop.runner import build_live_loop
from tools.usdjpy_live_loop.schema import STATE_EVIDENCE_MISSING, STATE_READY
from tools.usdjpy_strategy_lab.data_loader import sample_runtime


def write_ready_preset(repo: Path) -> None:
    preset = repo / "MQL5" / "Presets" / "QuantGod_MT5_HFM_LivePilot.set"
    preset.parent.mkdir(parents=True, exist_ok=True)
    preset.write_text(
        "\n".join([
            "Watchlist=USDJPY",
            "ShadowMode=true",
            "ReadOnlyMode=true",
            "EnablePilotAutoTrading=false",
            "EnablePilotRsiH1Live=false",
            "EnablePilotMA=false",
            "EnablePilotBBH1Live=false",
            "EnablePilotMacdH1Live=false",
            "EnablePilotSRM15Live=false",
            "EnableNonRsiLegacyLiveAuthorization=false",
            "PilotMaxTotalPositions=2",
            "PilotLotSize=0.01",
            "PilotBlockManualPerSymbol=false",
        ]),
        encoding="utf-8",
    )


class USDJPYLiveLoopTests(unittest.TestCase):
    def test_ready_sample_reports_shadow_advisory_without_execution_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            runtime = Path(tmp) / "runtime"
            write_ready_preset(root)
            sample_runtime(runtime, overwrite=True)
            payload = build_live_loop(root, runtime, write=True)
            self.assertEqual(payload["schemaVersion"], 1)
            self.assertEqual(payload["state"], STATE_READY)
            self.assertTrue(payload["presetReady"])
            self.assertTrue(payload["policyReady"])
            self.assertFalse(payload["safety"]["orderSendAllowedByTool"])
            self.assertFalse(payload["safety"]["existingEaOwnsExecution"])
            self.assertFalse(payload["safety"]["executionLaneExists"])
            self.assertFalse(payload["intent"]["executionLaneExists"])
            self.assertNotIn("allowedLiveRoute", payload["intent"])
            self.assertNotIn("allowed", payload["intent"]["topPolicy"])
            self.assertTrue(payload["intent"]["topPolicy"]["researchOnly"])
            self.assertFalse(payload["intent"]["topPolicy"]["executionAllowed"])
            self.assertFalse(payload["intent"]["topPolicy"]["executionLaneExists"])
            self.assertTrue(payload["policy"]["compatibility"]["researchOnly"])
            self.assertFalse(payload["policy"]["compatibility"]["executionAllowed"])
            self.assertFalse(payload["dryRun"]["compatibility"]["executionLaneExists"])
            self.assertEqual(payload["intent"]["schemaVersion"], 1)
            self.assertTrue((runtime / "live" / "QuantGod_USDJPYLiveLoopStatus.json").exists())
            self.assertTrue((runtime / "live" / "QuantGod_USDJPYLiveIntent.json").exists())

    def test_missing_runtime_fails_closed_even_if_preset_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            runtime = Path(tmp) / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            write_ready_preset(root)
            payload = build_live_loop(root, runtime, write=True)
            self.assertEqual(payload["state"], STATE_EVIDENCE_MISSING)
            self.assertFalse(payload["runtimeReady"])
            self.assertIn("缺少 USDJPY 运行快照", "；".join(payload["whyNoEntry"]))

    def test_dashboard_snapshot_within_mt5_bridge_window_stays_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            runtime = Path(tmp) / "runtime"
            write_ready_preset(root)
            sample_runtime(runtime, overwrite=True)
            (runtime / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json").unlink()
            dashboard = runtime / "QuantGod_Dashboard.json"
            dashboard.write_text(
                json.dumps({
                    "timestamp": "2026.05.06 01:40:21",
                    "watchlist": "USDJPYc",
                    "runtime": {
                        "tradeStatus": "SHADOW",
                        "executionEnabled": False,
                        "readOnlyMode": True,
                        "tickAgeSeconds": 2,
                    },
                    "market": {"bid": 157.762, "ask": 157.788, "spread": 2.6},
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            old_time = time.time() - 60
            os.utime(dashboard, (old_time, old_time))
            payload = build_live_loop(root, runtime, write=True)
            self.assertEqual(payload["state"], STATE_READY)
            self.assertTrue(payload["runtimeReady"])
            self.assertEqual(payload["runtime"]["freshnessTier"], "SOFT_STALE")
            self.assertNotIn("运行快照过旧", "；".join(payload["whyNoEntry"]))

    def test_hard_stale_dashboard_snapshot_blocks_live_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            runtime = Path(tmp) / "runtime"
            write_ready_preset(root)
            sample_runtime(runtime, overwrite=True)
            snapshot_path = runtime / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["runtimeAgeSeconds"] = 120
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

            payload = build_live_loop(root, runtime, write=True)

            self.assertEqual(payload["state"], STATE_EVIDENCE_MISSING)
            self.assertFalse(payload["runtimeReady"])
            self.assertEqual(payload["runtime"]["freshnessTier"], "HARD_STALE")

    def test_stale_runtime_snapshot_mtime_blocks_even_with_embedded_fresh_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            runtime = Path(tmp) / "runtime"
            write_ready_preset(root)
            sample_runtime(runtime, overwrite=True)
            snapshot_path = runtime / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["runtimeFresh"] = True
            snapshot["runtimeAgeSeconds"] = 2
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            old_time = time.time() - 3600
            os.utime(snapshot_path, (old_time, old_time))

            payload = build_live_loop(root, runtime, write=True)

            self.assertEqual(payload["state"], STATE_EVIDENCE_MISSING)
            self.assertFalse(payload["runtimeReady"])
            self.assertEqual(payload["runtime"]["freshnessTier"], "HARD_STALE")
            self.assertGreater(payload["runtime"]["ageSeconds"], 3500)

    def test_hard_spread_blocker_is_prioritized_in_why_no_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            runtime = Path(tmp) / "runtime"
            write_ready_preset(root)
            sample_runtime(runtime, overwrite=True)
            (runtime / "QuantGod_USDJPYRsiEntryDiagnostics.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.mt5.usdjpy_rsi_entry_diagnostics.v1",
                        "symbol": "USDJPYc",
                        "strategy": "RSI_Reversal",
                        "direction": "LONG",
                        "state": "SPREAD_BLOCK",
                        "guards": {"sessionOpen": True, "spreadAllowed": False, "spreadPips": 3.1, "maxSpreadPips": 2.2},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = build_live_loop(root, runtime, write=True)

            self.assertEqual(payload["state"], "POLICY_BLOCKED")
            self.assertEqual(payload["spreadGate"]["tier"], "HARD_WIDE")
            self.assertIn("点差严重偏宽", "；".join(payload["whyNoEntry"]))

    def test_written_daily_autopilot_is_chinese_operator_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            runtime = Path(tmp) / "runtime"
            write_ready_preset(root)
            sample_runtime(runtime, overwrite=True)
            build_live_loop(root, runtime, write=True)
            daily = json.loads((runtime / "live" / "QuantGod_USDJPYDailyAutopilot.json").read_text(encoding="utf-8"))
            self.assertIn("Shadow/ReadOnly", daily["advisoryRoute"])
            self.assertIn("买入", daily["topDirectionZh"])
            self.assertFalse(daily["safety"]["orderSendAllowedByTool"])
            self.assertFalse(daily["safety"]["executionLaneExists"])

    def test_shadow_top_strategy_becomes_advisory_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            runtime = Path(tmp) / "runtime"
            write_ready_preset(root)
            sample_runtime(runtime, overwrite=True)
            ledger = runtime / "ShadowCandidateOutcomeLedger.csv"
            with ledger.open("a", encoding="utf-8") as handle:
                for idx in range(8):
                    handle.write(f"USDJPYc,MA_Cross,LONG,TREND_EXP_UP,M15,{8 + idx * 0.1:.1f},10.0,1.0\n")
            sltp_path = runtime / "adaptive" / "QuantGod_DynamicSLTPCalibration.json"
            sltp = json.loads(sltp_path.read_text(encoding="utf-8"))
            sltp["plans"].append({
                "symbol": "USDJPYc",
                "strategy": "MA_Cross",
                "direction": "LONG",
                "status": "CALIBRATED",
                "initialStopPips": 3.0,
                "target1Pips": 5.0,
            })
            sltp_path.write_text(json.dumps(sltp, ensure_ascii=False), encoding="utf-8")
            payload = build_live_loop(root, runtime, write=True)
            self.assertEqual(payload["state"], STATE_READY)
            self.assertEqual(payload["topShadowPolicy"]["strategy"], "MA_Cross")
            self.assertNotIn("topLiveEligiblePolicy", payload)
            self.assertEqual(payload["intent"]["strategy"], "MA_Cross")
            self.assertFalse(payload["intent"]["existingEaOwnsExecution"])


if __name__ == "__main__":
    unittest.main()
