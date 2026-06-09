from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools.build_param_lab_run_recovery import report_state_for_run_task
from tools.run_param_lab import build_runner_status, classify_terminal_blockers
from tools.sync_isolated_mt5_account_context import build_status


class ParamLabRunnerTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_config_only_run_does_not_require_terminal_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            tester = root / "tester"
            runtime = tester / "MQL5" / "Files"
            output = runtime / "agent" / "QuantGod_ChampionTesterForwardParamLabStatus.json"
            plan_path = runtime / "agent" / "QuantGod_ChampionTesterForwardRequest.json"
            base_preset = repo / "MQL5" / "Presets" / "QuantGod_MT5_HFM_Backtest_USDJPYc.set"
            base_preset.parent.mkdir(parents=True, exist_ok=True)
            base_preset.write_text(
                "\n".join([
                    "PilotLotSize=0.01",
                    "PilotMaxTotalPositions=1",
                    "PilotMaxPositionsPerSymbol=1",
                ]),
                encoding="ascii",
            )
            (repo / "MQL5" / "Experts").mkdir(parents=True, exist_ok=True)
            (repo / "MQL5" / "Experts" / "QuantGod_MultiStrategy.ex5").write_text("stub", encoding="ascii")

            task = {
                "rank": 1,
                "candidateId": "g0077-usdjpy-rsi-champion-tester-forward-v1",
                "routeKey": "RSI_Reversal",
                "symbol": "USDJPYc",
                "timeframe": "H1",
                "basePreset": str(base_preset),
                "presetName": "QuantGod_MT5_ParamLab_g0077-usdjpy-rsi-champion-tester-forward-v1.set",
                "presetOverrides": {
                    "PilotLotSize": "0.01",
                    "PilotMaxTotalPositions": "1",
                    "PilotMaxPositionsPerSymbol": "1",
                },
            }
            self._write_json(plan_path, {
                "summary": {"runTerminal": False, "livePresetMutation": False},
                "routePlans": [{"routeKey": "RSI_Reversal", "candidates": [task]}],
                "selectedTasks": [{**task, "testerOnly": True, "livePresetMutation": False, "runTerminalDefault": False}],
                "backtestTasks": [task],
            })

            args = argparse.Namespace(
                repo_root=str(repo),
                hfm_root=str(tester),
                runtime_dir=str(runtime),
                plan=str(plan_path),
                output=str(output),
                max_tasks=1,
                route=[],
                candidate_id=["g0077-usdjpy-rsi-champion-tester-forward-v1"],
                rank_mode="route-balanced",
                from_date="2026.03.05",
                to_date="2026.06.03",
                terminal_timeout_seconds=5,
                login="186054398",
                server="HFMarketsGlobal-Live12",
                run_terminal=False,
                authorized_strategy_tester=False,
                allow_outside_window=False,
                auto_tester_lock="",
                max_live_snapshot_age_minutes=30,
                wineprefix="",
            )

            status = build_runner_status(args)

            self.assertEqual(status["mode"], "CONFIG_ONLY")
            self.assertEqual(status["summary"]["configReadyCount"], 1)
            self.assertEqual(status["summary"]["runAttemptedCount"], 0)
            self.assertEqual(status["tasks"][0]["status"], "CONFIG_READY")
            self.assertEqual(status["tasks"][0]["winePrefix"], "")
            self.assertFalse(status["tasks"][0]["livePresetMutation"])

    def test_nonzero_terminal_without_html_report_is_not_report_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            live_runtime = root / "live" / "MQL5" / "Files"
            tester = root / "tester"
            output = tester / "MQL5" / "Files" / "agent" / "QuantGod_ForexLive12RsiTesterParamLabStatus.json"
            plan_path = tester / "MQL5" / "Files" / "agent" / "QuantGod_ForexLive12RsiTesterRequest.json"
            lock_path = tester / "MQL5" / "Files" / "QuantGod_AutoTesterWindow.lock.json"
            base_preset = repo / "MQL5" / "Presets" / "QuantGod_MT5_HFM_Backtest_USDJPYc.set"
            terminal = tester / "terminal64.exe"

            base_preset.parent.mkdir(parents=True, exist_ok=True)
            base_preset.write_text(
                "\n".join([
                    "PilotLotSize=0.01",
                    "PilotMaxTotalPositions=2",
                    "PilotMaxPositionsPerSymbol=1",
                ]),
                encoding="ascii",
            )
            (repo / "MQL5" / "Experts").mkdir(parents=True, exist_ok=True)
            (repo / "MQL5" / "Experts" / "QuantGod_MultiStrategy.ex5").write_text("stub", encoding="ascii")
            terminal.parent.mkdir(parents=True, exist_ok=True)
            terminal.write_text("stub", encoding="ascii")
            (tester / "MQL5" / "Profiles" / "Tester").mkdir(parents=True, exist_ok=True)

            now = datetime.now(timezone.utc)
            self._write_json(lock_path, {
                "schemaVersion": 1,
                "purpose": "PARAM_LAB_STRATEGY_TESTER_ONLY",
                "authorized": True,
                "testerOnly": True,
                "allowRunTerminal": True,
                "livePresetMutation": False,
                "allowOutsideWindow": True,
                "createdAtIso": (now - timedelta(minutes=5)).isoformat(),
                "expiresAtIso": (now + timedelta(hours=1)).isoformat(),
                "runtimeDir": str(live_runtime),
                "hfmRoot": str(tester),
                "maxTasks": 1,
            })
            self._write_json(live_runtime / "QuantGod_Dashboard.json", {
                "timestamp": now.isoformat(),
                "runtime": {
                    "connected": True,
                    "terminalConnected": True,
                    "accountAuthorized": True,
                    "pilotKillSwitch": False,
                    "tradeStatus": "READY",
                    "livePilotMode": True,
                },
                "account": {
                    "number": 186054398,
                    "server": "HFMarketsGlobal-Live12",
                    "margin": 0,
                },
                "symbols": [],
                "openTrades": [],
                "strategies": {},
            })
            task = {
                "rank": 1,
                "candidateId": "forex-live12-rsi-loss-cooldown-v1",
                "routeKey": "RSI_Reversal",
                "symbol": "USDJPYc",
                "timeframe": "H1",
                "presetName": "QuantGod_MT5_ParamLab_forex-live12-rsi-loss-cooldown-v1.set",
                "presetOverrides": {
                    "PilotLotSize": "0.01",
                    "PilotMaxTotalPositions": "2",
                    "PilotMaxPositionsPerSymbol": "1",
                },
            }
            self._write_json(plan_path, {
                "summary": {"runTerminal": False, "livePresetMutation": False},
                "routePlans": [{"routeKey": "RSI_Reversal", "candidates": [task]}],
                "selectedTasks": [{**task, "testerOnly": True, "livePresetMutation": False, "runTerminalDefault": False}],
                "backtestTasks": [task],
            })

            args = argparse.Namespace(
                repo_root=str(repo),
                hfm_root=str(tester),
                runtime_dir=str(live_runtime),
                plan=str(plan_path),
                output=str(output),
                max_tasks=1,
                route=[],
                candidate_id=["forex-live12-rsi-loss-cooldown-v1"],
                rank_mode="route-balanced",
                from_date="2026.03.05",
                to_date="2026.06.03",
                terminal_timeout_seconds=5,
                login="186054398",
                server="HFMarketsGlobal-Live12",
                run_terminal=True,
                authorized_strategy_tester=True,
                allow_outside_window=True,
                auto_tester_lock=str(lock_path),
                max_live_snapshot_age_minutes=30,
                wineprefix=str(root / "tester-wineprefix"),
            )

            stderr = "wineserver: Can't check in server_mach_port\nwine: for some mysterious reason, the wine server failed to run.\n"
            with patch("tools.run_param_lab.mt5_terminal_command", return_value=(["terminal64.exe"], tester, {})), \
                 patch("tools.run_param_lab.run_terminal_process", return_value=(1, False, {"stderrTail": stderr})):
                status = build_runner_status(args)

            self.assertEqual(status["summary"]["runAttemptedCount"], 1)
            self.assertEqual(status["summary"]["reportParsedCount"], 0)
            self.assertEqual(status["summary"]["htmlReportParsedCount"], 0)
            self.assertEqual(status["summary"]["terminalNonzeroCount"], 1)
            self.assertEqual(status["summary"]["terminalBlockerCodes"], ["WINE_SERVER_MACH_PORT_UNAVAILABLE"])
            task_status = status["tasks"][0]
            self.assertEqual(task_status["status"], "TERMINAL_EXIT_NONZERO_REPORT_MISSING")
            self.assertEqual(task_status["terminalProcess"]["stderrTail"], stderr)
            self.assertEqual(task_status["terminalBlockers"][0]["code"], "WINE_SERVER_MACH_PORT_UNAVAILABLE")
            self.assertFalse(task_status["metrics"].get("htmlReportExists", False))

    def test_terminal_exit_191_without_html_is_classified(self) -> None:
        blockers = classify_terminal_blockers(
            {"stderrTail": "0024:err:toolbar:ToolbarWindowProc unknown msg 0465"},
            terminal_exit_code=191,
            html_report_exists=False,
        )

        self.assertEqual([item["code"] for item in blockers], ["MT5_TERMINAL_EXIT_191_REPORT_MISSING"])

    def test_recovery_does_not_treat_agent_artifacts_as_html_report(self) -> None:
        task = {
            "status": "TERMINAL_EXIT_NONZERO_REPORT_MISSING",
            "terminalExitCode": 191,
            "metrics": {
                "reportExists": True,
                "htmlReportExists": False,
                "testerEvidenceExists": True,
                "parseStatus": "PARSED_AGENT_ARTIFACTS",
                "evidenceSource": "agent_artifacts",
            },
        }

        self.assertEqual(report_state_for_run_task(task, {}, True), "missing")

    def test_account_context_preflight_reports_missing_target_without_hashing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            tester = root / "tester"
            (source / "Config").mkdir(parents=True)
            (source / "Bases" / "HFMarketsGlobal-Live12").mkdir(parents=True)
            (tester / "Config").mkdir(parents=True)
            (tester / "Bases" / "HFMarketsGlobal-Live12" / "symbols").mkdir(parents=True)
            (source / "terminal64.exe").write_text("terminal", encoding="ascii")
            (source / "Config" / "accounts.dat").write_bytes(b"account-context")
            (source / "Config" / "servers.dat").write_bytes(b"servers")
            (tester / "Config" / "servers.dat").write_bytes(b"servers")
            (tester / "Bases" / "HFMarketsGlobal-Live12" / "symbols" / "selected-186054398.dat").write_bytes(b"selected")

            status = build_status(
                mode="PREFLIGHT_ONLY_NO_SENSITIVE_COPY",
                source_root=source,
                tester_root=tester,
                login="186054398",
                server="HFMarketsGlobal-Live12",
                sensitive_copy_allowed=False,
            )

        self.assertFalse(status["ready"])
        self.assertFalse(status["sensitiveCopyAllowed"])
        self.assertFalse(status["strategyBlocked"])
        self.assertTrue(status["environmentBlocked"])
        self.assertTrue(status["sensitiveAccountContextSyncRequired"])
        self.assertIn("Config/accounts.dat", status["missingTarget"])
        self.assertEqual(
            status["blockers"],
            [
                "isolated_tester_account_context_not_ready",
                "sensitive_account_context_sync_required",
            ],
        )
        self.assertEqual(status["source"]["missing"], [])
        self.assertIn("Config/accounts.dat", status["target"]["missing"])
        self.assertTrue(status["sourceChecks"]["Config/accounts.dat"]["exists"])
        self.assertNotIn("sha256Prefix", status["sourceChecks"]["Config/accounts.dat"])
        sync_review = status["separateSyncReview"]
        self.assertEqual(sync_review["status"], "SEPARATE_SENSITIVE_ACCOUNT_CONTEXT_SYNC_REQUIRED")
        self.assertTrue(sync_review["sourceAccountContextExists"])
        self.assertFalse(sync_review["targetAccountContextExists"])
        self.assertTrue(sync_review["requiresSeparateControlledSync"])
        self.assertFalse(sync_review["sensitiveCopyAllowedHere"])
        self.assertIn("--allow-sensitive-account-context", sync_review["commandPreview"])
        self.assertFalse(sync_review["launchesTerminal"])
        self.assertFalse(sync_review["writesLivePreset"])
        self.assertFalse(sync_review["writesMt5OrderRequest"])


if __name__ == "__main__":
    unittest.main()
