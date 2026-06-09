from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools.champion_tester_run_gate import build_champion_tester_run_gate
from tools.champion_tester_lock_draft import build_champion_tester_lock_draft


class ChampionTesterRunGateTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _setup_repo(self, root: Path, *, account_context_ready: bool, parallel_queue: bool = False) -> tuple[Path, Path]:
        repo = root / "repo"
        runtime = repo / "runtime"
        tester_root = runtime / "HFM_MT5_Tester_Isolated"
        isolated_runtime = tester_root / "MQL5" / "Files"
        live_runtime = root / "live" / "MQL5" / "Files"
        now = datetime.now(timezone.utc).replace(microsecond=0)

        (tester_root / "MQL5" / "Profiles" / "Tester").mkdir(parents=True)
        (tester_root / "terminal64.exe").write_text("stub", encoding="ascii")
        self._write_json(
            live_runtime / "QuantGod_Dashboard.json",
            {
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
                "symbols": [{"openPositions": 0}],
                "strategies": {"RSI_Reversal": {"positions": 0}},
                "openTrades": [],
            },
        )
        self._write_json(
            isolated_runtime / "QuantGod_AutoTesterWindow.lock.json",
            {
                "schemaVersion": 1,
                "purpose": "PARAM_LAB_STRATEGY_TESTER_ONLY",
                "authorized": True,
                "testerOnly": True,
                "allowRunTerminal": True,
                "livePresetMutation": False,
                "allowOutsideWindow": True,
                "createdAtIso": (now - timedelta(minutes=5)).isoformat(),
                "expiresAtIso": (now + timedelta(minutes=30)).isoformat(),
                "runtimeDir": str(live_runtime),
                "hfmRoot": str(tester_root),
                "maxTasks": 1,
            },
        )
        self._write_json(
            runtime / "QuantGod_IsolatedTesterAccountContextStatus.json",
            {
                "ready": account_context_ready,
                "mode": "TEST",
                "login": "186054398",
                "server": "HFMarketsGlobal-Live12",
                "missingTarget": [] if account_context_ready else ["Config/accounts.dat"],
                "blockers": [] if account_context_ready else [
                    "isolated_tester_account_context_not_ready",
                    "sensitive_account_context_sync_required",
                ],
                "sensitiveAccountContextSyncRequired": not account_context_ready,
                "strategyBlocked": False,
                "environmentBlocked": not account_context_ready,
            },
        )
        task = {
            "candidateId": "g0077-usdjpy-rsi-champion-tester-forward-v1",
            "routeKey": "RSI_Reversal",
            "symbol": "USDJPYc",
            "timeframe": "H1",
            "testerOnly": True,
            "livePresetMutation": False,
            "runTerminalDefault": False,
            "configOnlyCommand": "python tools/run_param_lab.py --candidate-id g0077-usdjpy-rsi-champion-tester-forward-v1",
        }
        selected_tasks = [task]
        candidate_ids = [task["candidateId"]]
        if parallel_queue:
            second = {
                **task,
                "candidateId": "g0093-usdjpy-rsi-champion-tester-forward-v1",
                "configOnlyCommand": "python tools/run_param_lab.py --candidate-id g0093-usdjpy-rsi-champion-tester-forward-v1",
            }
            selected_tasks.append(second)
            candidate_ids.append(second["candidateId"])
        self._write_json(
            runtime / "agent" / "QuantGod_ChampionTesterForwardRequest.json",
            {
                "schema": "quantgod.champion_tester_forward_request.v1",
                "status": "CHAMPION_TESTER_FORWARD_REQUEST_READY",
                "selectedChampion": {"seedId": "GA-USDJPY-G0077-C0002"},
                "summary": {
                    "queueCount": len(selected_tasks),
                    "runTerminal": False,
                    "livePresetMutation": False,
                    "topCandidateId": task["candidateId"],
                    "candidateIds": candidate_ids,
                },
                "selectedTasks": selected_tasks,
                "testerIsolation": {
                    "isolatedTesterRoot": str(tester_root),
                    "isolatedRuntimeDir": str(isolated_runtime),
                    "statusPath": str(isolated_runtime / "agent" / "QuantGod_ChampionTesterForwardParamLabStatus.json"),
                },
                "materializationStatus": {"status": "CONFIG_ONLY", "configReadyCount": 1},
            },
        )
        return runtime, live_runtime / "QuantGod_Dashboard.json"

    def test_ready_when_queue_live_session_lock_and_account_context_are_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime, dashboard = self._setup_repo(Path(tmp), account_context_ready=True)
            repo = runtime.parent

            with patch("tools.champion_tester_run_gate._repo_root", return_value=repo), \
                 patch("tools.champion_tester_forward_request._repo_root", return_value=repo), \
                 patch("tools.champion_tester_run_gate._supporting_process_evidence", return_value={
                     "status": "PROCESS_SCAN_READY",
                     "scanSupported": True,
                     "mode": "READ_ONLY_PROCESS_SCAN",
                     "mainMt5TerminalRunning": True,
                     "isolatedTesterTerminalRunning": False,
                     "blockers": [],
                     "nextActionZh": "主 MT5 terminal64 进程存在，可继续按 dashboard freshness 判断 live session。",
                 }):
                gate = build_champion_tester_run_gate(
                    runtime,
                    primary_dashboard_json=str(dashboard),
                    allow_outside_window=True,
                    write=False,
                )

            self.assertEqual(gate["status"], "CHAMPION_TESTER_RUN_GATE_READY")
            self.assertTrue(gate["decision"]["canRunIsolatedTester"])
            self.assertFalse(gate["decision"]["canRunTerminalHere"])
            self.assertFalse(gate["safety"]["orderSendAllowed"])
            self.assertEqual(gate["gate"]["queue"]["queueCount"], 1)
            self.assertEqual(gate["blockers"], [])
            self.assertEqual(gate["readiness"]["ratio"], "6/7")
            self.assertEqual(gate["readiness"]["unmetCheckIds"], ["tester_window_open"])
            self.assertIn(gate["windowBriefing"]["status"], {"open_now", "waiting"})

    def test_parallel_queue_keeps_single_task_lock_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime, dashboard = self._setup_repo(Path(tmp), account_context_ready=True, parallel_queue=True)
            repo = runtime.parent

            with patch("tools.champion_tester_run_gate._repo_root", return_value=repo), \
                 patch("tools.champion_tester_forward_request._repo_root", return_value=repo), \
                 patch("tools.champion_tester_run_gate._supporting_process_evidence", return_value={
                     "status": "PROCESS_SCAN_READY",
                     "scanSupported": True,
                     "mode": "READ_ONLY_PROCESS_SCAN",
                     "mainMt5TerminalRunning": True,
                     "isolatedTesterTerminalRunning": False,
                     "blockers": [],
                     "nextActionZh": "主 MT5 terminal64 进程存在，可继续按 dashboard freshness 判断 live session。",
                 }):
                gate = build_champion_tester_run_gate(
                    runtime,
                    primary_dashboard_json=str(dashboard),
                    allow_outside_window=True,
                    write=False,
                )
                draft = build_champion_tester_lock_draft(
                    runtime,
                    primary_dashboard_json=str(dashboard),
                    write=False,
                )

            self.assertEqual(gate["status"], "CHAMPION_TESTER_RUN_GATE_READY")
            self.assertEqual(gate["gate"]["queue"]["queueCount"], 2)
            self.assertEqual(gate["sourceTesterRequest"]["allowedRunMaxTasks"], 1)
            self.assertNotIn("authorization_lock_max_tasks_too_low", gate["gate"]["blockers"])
            self.assertEqual(draft["draftPayload"]["maxTasks"], 1)
            self.assertEqual(
                draft["draftPayload"]["candidateIds"],
                [
                    "g0077-usdjpy-rsi-champion-tester-forward-v1",
                    "g0093-usdjpy-rsi-champion-tester-forward-v1",
                ],
            )

    def test_blocks_when_account_context_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime, dashboard = self._setup_repo(Path(tmp), account_context_ready=False)
            repo = runtime.parent

            with patch("tools.champion_tester_run_gate._repo_root", return_value=repo), \
                 patch("tools.champion_tester_forward_request._repo_root", return_value=repo), \
                 patch("tools.champion_tester_run_gate._supporting_process_evidence", return_value={
                     "status": "PROCESS_SCAN_READY",
                     "scanSupported": True,
                     "mode": "READ_ONLY_PROCESS_SCAN",
                     "mainMt5TerminalRunning": True,
                     "isolatedTesterTerminalRunning": False,
                     "blockers": [],
                     "nextActionZh": "主 MT5 terminal64 进程存在，可继续按 dashboard freshness 判断 live session。",
                 }):
                gate = build_champion_tester_run_gate(
                    runtime,
                    primary_dashboard_json=str(dashboard),
                    allow_outside_window=True,
                    write=False,
                )

            self.assertEqual(gate["status"], "CHAMPION_TESTER_RUN_GATE_BLOCKED")
            self.assertFalse(gate["decision"]["canRunIsolatedTester"])
            self.assertIn("isolated_tester_account_context_not_ready", gate["gate"]["blockers"])
            self.assertIn("sensitive_account_context_sync_required", gate["gate"]["blockers"])
            self.assertIn("isolated_tester_account_context_not_ready", gate["blockers"])
            self.assertIn("sensitive_account_context_sync_required", gate["blockers"])
            self.assertIn("未满足", gate["readiness"]["summaryZh"])
            self.assertTrue(gate["testerAccountContext"]["sensitiveAccountContextSyncRequired"])
            self.assertFalse(gate["testerAccountContext"]["strategyBlocked"])
            self.assertTrue(gate["testerAccountContext"]["environmentBlocked"])

    def test_promotes_top_level_blockers_readiness_and_window_briefing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime, dashboard = self._setup_repo(Path(tmp), account_context_ready=True)
            repo = runtime.parent

            with patch("tools.champion_tester_run_gate._repo_root", return_value=repo), \
                 patch("tools.champion_tester_forward_request._repo_root", return_value=repo), \
                 patch("tools.champion_tester_run_gate._supporting_process_evidence", return_value={
                     "status": "PROCESS_SCAN_READY",
                     "scanSupported": True,
                     "mode": "READ_ONLY_PROCESS_SCAN",
                     "mainMt5TerminalRunning": True,
                     "isolatedTesterTerminalRunning": False,
                     "blockers": [],
                     "nextActionZh": "主 MT5 terminal64 进程存在，可继续按 dashboard freshness 判断 live session。",
                 }):
                gate = build_champion_tester_run_gate(
                    runtime,
                    primary_dashboard_json=str(dashboard),
                    allow_outside_window=False,
                    write=False,
                )

            self.assertEqual(gate["status"], "CHAMPION_TESTER_RUN_GATE_BLOCKED")
            self.assertEqual(
                gate["blockers"],
                ["outside_strategy_tester_window"],
            )
            self.assertEqual(gate["readiness"]["ratio"], "5/7")
            self.assertEqual(
                gate["readiness"]["unmetCheckIds"],
                ["tester_window_open", "tester_can_run_now"],
            )
            self.assertEqual(gate["windowBriefing"]["status"], "waiting")
            self.assertIn("tester window", gate["windowBriefing"]["summaryZh"])
            self.assertEqual(gate["windowBriefing"]["residualAfterWindowOpenCheckIds"], [])

    def test_promotes_process_blocker_into_top_level_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime, dashboard = self._setup_repo(Path(tmp), account_context_ready=True)
            repo = runtime.parent

            with patch("tools.champion_tester_run_gate._repo_root", return_value=repo), \
                 patch("tools.champion_tester_forward_request._repo_root", return_value=repo), \
                 patch("tools.champion_tester_run_gate._supporting_process_evidence", return_value={
                     "status": "PROCESS_SCAN_READY",
                     "scanSupported": True,
                     "mode": "READ_ONLY_PROCESS_SCAN",
                     "mainMt5TerminalRunning": False,
                     "isolatedTesterTerminalRunning": False,
                     "dashboardServerRunning": False,
                     "preferredTerminalPath": "/Applications/MetaTrader 5/terminal64.exe",
                     "dashboardPath": "/tmp/MetaTrader 5/MQL5/Files/QuantGod_Dashboard.json",
                     "startupConfigPath": "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
                     "readOnlyVerificationCommands": ["ps ax | rg -i 'terminal64|dashboard_server.js|backend-api'"],
                     "blockers": ["mt5_terminal_process_missing"],
                     "nextActionZh": "未发现主 MT5 terminal64 进程；live dashboard 很可能不会继续刷新。",
                 }):
                gate = build_champion_tester_run_gate(
                    runtime,
                    primary_dashboard_json=str(dashboard),
                    allow_outside_window=True,
                    write=False,
                )

            self.assertIn("mt5_terminal_process_missing", gate["blockers"])
            self.assertEqual(gate["supportingProcessEvidence"]["blockers"], ["mt5_terminal_process_missing"])
            self.assertEqual(
                gate["supportingProcessEvidence"]["startupConfigPath"],
                "/tmp/drive_c/qg/QuantGod_MT5_HFM_LiveSecondary_mac.ini",
            )
            self.assertFalse(gate["supportingProcessEvidence"]["dashboardServerRunning"])
            self.assertEqual(gate["status"], "CHAMPION_TESTER_RUN_GATE_BLOCKED")
            self.assertFalse(gate["decision"]["canRunIsolatedTester"])
            self.assertIn("mt5_terminal_process_missing", gate["summaryZh"])
            self.assertEqual(
                gate["decision"]["nextRequiredActionZh"],
                "先恢复主 MT5 terminal64 进程（优先: /Applications/MetaTrader 5/terminal64.exe）并恢复 dashboard freshness，再重建 tester gate。",
            )
            self.assertIn(
                "开窗后仍需继续清理：mt5_terminal_process_missing",
                gate["windowBriefing"]["summaryZh"],
            )

    def test_lock_draft_never_writes_lock_or_runs_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime, dashboard = self._setup_repo(Path(tmp), account_context_ready=False)
            repo = runtime.parent

            with patch("tools.champion_tester_run_gate._repo_root", return_value=repo), \
                 patch("tools.champion_tester_forward_request._repo_root", return_value=repo):
                draft = build_champion_tester_lock_draft(
                    runtime,
                    primary_dashboard_json=str(dashboard),
                    write=True,
                )

            self.assertEqual(draft["schema"], "quantgod.champion_tester_lock_draft.v1")
            self.assertFalse(draft["lockFileWritten"])
            self.assertFalse(draft["decision"]["canRunTerminalHere"])
            self.assertFalse(draft["decision"]["canRunIsolatedTesterHere"])
            self.assertFalse(draft["safety"]["orderSendAllowed"])
            self.assertEqual(draft["draftPayload"]["candidateId"], "g0077-usdjpy-rsi-champion-tester-forward-v1")
            self.assertEqual(draft["draftPayload"]["purpose"], "PARAM_LAB_STRATEGY_TESTER_ONLY")
            self.assertTrue((runtime / "agent" / "QuantGod_ChampionTesterLockDraft.json").exists())


if __name__ == "__main__":
    unittest.main()
