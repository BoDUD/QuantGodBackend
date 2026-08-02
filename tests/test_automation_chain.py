from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.automation_chain.runner import AutomationChainRunner
from tools.automation_chain.telegram_text import build_automation_telegram_text


class AutomationChainTest(unittest.TestCase):
    def test_status_fail_closed_when_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = AutomationChainRunner(Path.cwd(), tmp, ["USDJPYc"], python_bin="python")
            status = runner.build_status()
            self.assertEqual(status["state"], "NOT_RUN")
            self.assertEqual(status["runStatus"], "NOT_STARTED")
            self.assertEqual(status["stepCount"], 0)
            self.assertIn("尚未运行", status["stateZh"])
            self.assertFalse(status["safety"]["orderSendAllowed"])
            self.assertFalse(status["safety"]["executionLaneExists"])
            self.assertFalse(status["safety"]["unattendedLiveExpansionAllowed"])
            self.assertTrue(status["safety"]["operatorApprovalRequired"])

    def test_report_write_is_atomic_and_preserves_cycle_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runner = AutomationChainRunner(Path.cwd(), runtime, ["USDJPYc"], python_bin="python")
            report = {
                "cycleId": "cycle-test",
                "runStatus": "COMPLETED",
                "generatedAt": "2026-08-01T00:00:00Z",
                "state": "BLOCKED_BY_USDJPY_POLICY",
                "stateZh": "策略证据不足",
                "standardCount": 0,
                "opportunityCount": 0,
                "blockedCount": 1,
                "missingEvidence": [],
            }
            runner.write_report(report)
            latest = json.loads((runtime / "automation" / "QuantGod_AutomationChainLatest.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["cycleId"], "cycle-test")
            self.assertEqual(latest["runStatus"], "COMPLETED")
            self.assertEqual(list((runtime / "automation").glob("*.tmp")), [])

    def test_policy_summary_detects_opportunity_and_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "adaptive").mkdir(parents=True)
            (runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json").write_text(json.dumps({
                "strategies": [
                    {"symbol": "USDJPYc", "direction": "LONG", "entryMode": "OPPORTUNITY_ENTRY", "allowed": True, "recommendedLot": 0.7, "reason": "核心安全通过"},
                    {"symbol": "USDJPYc", "direction": "SHORT", "entryMode": "BLOCKED", "allowed": False, "recommendedLot": 0, "reasons": ["方向负期望", "运行快照通过"]},
                ]
            }, ensure_ascii=False), encoding="utf-8")
            runner = AutomationChainRunner(Path.cwd(), runtime, ["USDJPYc"], python_bin="python")
            summary = runner._summarize_policy(runner._policy_file())
            self.assertEqual(summary["opportunityCount"], 1)
            self.assertEqual(summary["blockedCount"], 1)
            self.assertEqual(summary["opportunities"][0]["entryModeZh"], "机会入场")
            self.assertIn("方向负期望", summary["blocked"][0]["reason"])

    def test_blocked_reasons_filter_positive_evidence(self):
        runner = AutomationChainRunner(Path.cwd(), "runtime", ["USDJPYc"], python_bin="python")
        reasons = runner._actionable_blockers(["USDJPY 运行快照可用", "运行快照通过", "快通道质量未通过：DEGRADED"])
        self.assertEqual(reasons, ["快通道质量未通过：DEGRADED"])

    def test_ready_state_keeps_shadow_blockers_out_of_main_blockers(self):
        runner = AutomationChainRunner(Path.cwd(), "runtime", ["USDJPYc"], python_bin="python")
        blockers = ["影子路线样本不足", "MA_Cross 仍在模拟观察"]
        self.assertEqual(runner._top_level_blocked_reasons("SHADOW_ADVISORY_READY", blockers), [])
        self.assertEqual(runner._top_level_blocked_reasons("BLOCKED_BY_USDJPY_POLICY", blockers), blockers)

    def test_chain_steps_use_usdjpy_live_loop_as_source_of_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = AutomationChainRunner(Path.cwd(), tmp, ["USDJPYc"], python_bin="python")
            commands = "\n".join(" ".join(step.command) for step in runner.build_steps(send=True))
            self.assertIn("run_execution_feedback_producer.py", commands)
            self.assertIn("run_case_memory.py", commands)
            self.assertIn("run_usdjpy_strategy_lab.py", commands)
            self.assertIn("run_usdjpy_live_loop.py", commands)
            self.assertIn("run_entry_latency.py", commands)
            self.assertIn("run_strategy_parity.py", commands)
            producer_index = commands.index("run_execution_feedback_producer.py")
            case_memory_index = commands.index("run_case_memory.py")
            adaptive_index = commands.index("run_adaptive_policy.py")
            live_loop_index = commands.index("run_usdjpy_live_loop.py")
            final_fastlane_index = commands.rindex("run_mt5_fastlane.py")
            strategy_parity_index = commands.index("run_strategy_parity.py")
            entry_latency_index = commands.index("run_entry_latency.py")
            self.assertLess(producer_index, case_memory_index)
            self.assertLess(case_memory_index, adaptive_index)
            self.assertLess(live_loop_index, final_fastlane_index)
            self.assertLess(final_fastlane_index, strategy_parity_index)
            self.assertLess(strategy_parity_index, entry_latency_index)
            self.assertIn("dry-run", commands)
            self.assertNotIn("run_auto_execution_policy.py", commands)

    def test_safe_iteration_plan_turns_readiness_gaps_into_shadow_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = AutomationChainRunner(Path.cwd(), tmp, ["USDJPYc"], python_bin="python")
            runner._history_production_readiness = lambda: {"ready": True, "status": "PASS", "freshness": "FRESH"}  # type: ignore[method-assign]
            plan = runner._safe_iteration_plan(
                {
                    "entryReadiness": {
                        "score": 42.9,
                        "readyForEntryReview": False,
                        "failedGapIds": [
                            "policy_entry_mode",
                            "policy_ea_signal_alignment",
                            "signal_quorum",
                            "shadow_sample_non_negative",
                            "ea_entry_guard_ready",
                        ],
                    },
                    "timeline": [{"stage": "order_attempt", "status": "STALE_ATTEMPT"}],
                },
                {"state": "POLICY_BLOCKED"},
                {"standardCount": 0, "opportunityCount": 0},
                {
                    "available": True,
                    "currentGeneration": 372,
                    "bestElite": {"seedId": "GA-USDJPY-G0372-M0007", "fitness": 6.4823, "promotionStage": "TESTER_ONLY", "directLiveAllowed": False},
                    "safety": {"orderSendAllowed": False, "writesMt5OrderRequest": False, "gaDirectLiveAllowed": False},
                },
                "BLOCKED_BY_USDJPY_POLICY",
            )

            self.assertEqual(plan["mode"], "SHADOW_SIMULATION_ONLY")
            self.assertFalse(plan["safety"]["orderSendAllowed"])
            self.assertFalse(plan["safety"]["writesMt5OrderRequest"])
            self.assertEqual(plan["readinessScore"], 42.9)
            self.assertEqual(plan["gaFactorySummary"]["currentGeneration"], 372)
            self.assertEqual(plan["gaFactorySummary"]["bestElite"]["promotionStage"], "TESTER_ONLY")
            self.assertFalse(plan["gaFactorySummary"]["bestElite"]["directLiveAllowed"])
            action_ids = [item["actionId"] for item in plan["actions"]]
            self.assertIn("refresh_execution_feedback_memory", action_ids)
            self.assertIn("refresh_policy_shadow_evidence", action_ids)
            self.assertIn("build_signal_direction_shadow_strategy_intent", action_ids)
            self.assertNotIn("build_shadow_strategy_intent", action_ids)
            self.assertIn("refresh_strategy_parity_evidence", action_ids)
            self.assertIn("advance_ga_shadow_generation", action_ids)
            self.assertIn("refresh_ea_entry_diagnostics", action_ids)
            self.assertIn("inspect_readonly_order_feedback", action_ids)
            signal_direction_action = next(item for item in plan["actions"] if item["actionId"] == "build_signal_direction_shadow_strategy_intent")
            self.assertLess(signal_direction_action["priority"], 30)
            self.assertIn("SHORT", "\n".join(signal_direction_action["commands"]))
            self.assertIn("SHADOW/TESTER_ONLY", "\n".join(signal_direction_action["commands"]))
            self.assertFalse(signal_direction_action["safety"]["orderSendAllowed"])
            ea_refresh_action = next(item for item in plan["actions"] if item["actionId"] == "refresh_ea_entry_diagnostics")
            ea_refresh_scripts = [Path(command[1]).name for command in ea_refresh_action["commandArgv"]]
            self.assertEqual(ea_refresh_scripts, ["run_usdjpy_live_loop.py", "run_mt5_fastlane.py", "run_entry_latency.py"])
            parity_action = next(item for item in plan["actions"] if item["actionId"] == "refresh_strategy_parity_evidence")
            ga_action = next(item for item in plan["actions"] if item["actionId"] == "advance_ga_shadow_generation")
            self.assertLess(parity_action["priority"], ga_action["priority"])
            self.assertEqual([Path(command[1]).name for command in parity_action["commandArgv"]], ["run_strategy_parity.py"])
            all_commands = "\n".join("\n".join(item["commands"]) for item in plan["actions"])
            self.assertIn("run_execution_feedback_producer.py", all_commands)
            self.assertIn("run_case_memory.py", all_commands)
            self.assertIn("run_strategy_ga_factory.py", all_commands)
            self.assertIn("run_strategy_ga.py", all_commands)
            self.assertIn("run_strategy_parity.py", all_commands)
            self.assertIn("run_entry_latency.py", all_commands)
            self.assertNotIn("OrderSend", all_commands)
            self.assertTrue(all(item.get("commandArgv") for item in plan["actions"]))

    def test_safe_iteration_command_allowlist_blocks_execution_surfaces(self):
        runner = AutomationChainRunner(Path.cwd(), "runtime", ["USDJPYc"], python_bin="python")
        runner._validate_safe_iteration_command(["python", str(Path.cwd() / "tools" / "run_strategy_ga.py"), "--runtime-dir", "runtime", "run-generation", "--write"])
        runner._validate_safe_iteration_command(["python", str(Path.cwd() / "tools" / "run_strategy_parity.py"), "--runtime-dir", "runtime", "build", "--write"])
        with self.assertRaises(ValueError):
            runner._validate_safe_iteration_command(["python", str(Path.cwd() / "tools" / "run_usdjpy_live_loop.py"), "telegram-text", "--send"])
        with self.assertRaises(ValueError):
            runner._validate_safe_iteration_command(["python", str(Path.cwd() / "tools" / "run_live_automation_readiness.py"), "broker-order"])

    def test_ga_safe_iteration_gets_longer_timeout_without_opening_execution(self):
        runner = AutomationChainRunner(Path.cwd(), "runtime", ["USDJPYc"], python_bin="python")
        action = {"actionId": "advance_ga_shadow_generation"}
        ga_command = ["python", str(Path.cwd() / "tools" / "run_strategy_ga.py"), "--runtime-dir", "runtime", "run-generation", "--write"]
        factory_command = ["python", str(Path.cwd() / "tools" / "run_strategy_ga_factory.py"), "--runtime-dir", "runtime", "build", "--write"]
        latency_command = ["python", str(Path.cwd() / "tools" / "run_entry_latency.py"), "--runtime-dir", "runtime", "build", "--write"]
        producer_command = ["python", str(Path.cwd() / "tools" / "run_execution_feedback_producer.py"), "--runtime-dir", "runtime", "build", "--write"]
        case_memory_command = ["python", str(Path.cwd() / "tools" / "run_case_memory.py"), "--runtime-dir", "runtime", "build", "--write", "--limit", "8"]

        self.assertEqual(runner._safe_iteration_timeout_seconds(action, ga_command), 420)
        self.assertEqual(runner._safe_iteration_timeout_seconds(action, factory_command), 240)
        self.assertEqual(runner._safe_iteration_timeout_seconds({"actionId": "refresh_ea_entry_diagnostics"}, latency_command), 180)
        runner._validate_safe_iteration_command(ga_command)
        runner._validate_safe_iteration_command(producer_command)
        runner._validate_safe_iteration_command(case_memory_command)
        with self.assertRaises(ValueError):
            runner._validate_safe_iteration_command(["python", str(Path.cwd() / "tools" / "run_strategy_ga.py"), "--send"])

    def test_no_elite_generation_limit_pauses_more_ga_churn(self):
        runner = AutomationChainRunner(Path.cwd(), "runtime", ["USDJPYc"], python_bin="python")
        runner._history_production_readiness = lambda: {"ready": True, "status": "PASS", "freshness": "FRESH"}  # type: ignore[method-assign]
        plan = runner._safe_iteration_plan(
            {"entryReadiness": {"failedGapIds": ["shadow_sample_non_negative"]}},
            {"state": "POLICY_BLOCKED"},
            {"standardCount": 0, "opportunityCount": 0},
            {
                "available": True,
                "currentGeneration": 985,
                "eliteCount": 0,
                "graveyardCount": 96,
                "nextGeneration": {"action": "NO_ELITE_EXPAND_SEARCH"},
            },
            "BLOCKED_BY_USDJPY_POLICY",
        )

        action_ids = [item["actionId"] for item in plan["actions"]]
        self.assertNotIn("advance_ga_shadow_generation", action_ids)
        self.assertTrue(plan["gaProgression"]["paused"])
        self.assertEqual(plan["gaProgression"]["reasonCode"], "NO_ELITE_GENERATION_LIMIT")
        self.assertTrue(plan["gaProgression"]["requiresNewDataOrHypothesis"])

    def test_stale_history_pauses_ga_even_when_elites_exist(self):
        runner = AutomationChainRunner(Path.cwd(), "runtime", ["USDJPYc"], python_bin="python")
        runner._history_production_readiness = lambda: {"ready": False, "status": "PASS", "freshness": "STALE"}  # type: ignore[method-assign]
        plan = runner._safe_iteration_plan(
            {"entryReadiness": {"failedGapIds": ["shadow_sample_non_negative"]}},
            {"state": "POLICY_BLOCKED"},
            {"standardCount": 0, "opportunityCount": 0},
            {"available": True, "currentGeneration": 10, "eliteCount": 2},
            "BLOCKED_BY_USDJPY_POLICY",
        )

        self.assertTrue(plan["gaProgression"]["paused"])
        self.assertEqual(plan["gaProgression"]["reasonCode"], "HISTORY_NOT_READY")
        self.assertNotIn("advance_ga_shadow_generation", [item["actionId"] for item in plan["actions"]])

    def test_ga_factory_summary_is_shadow_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "ga_factory").mkdir(parents=True)
            (runtime / "ga_factory" / "QuantGod_GAFactoryState.json").write_text(json.dumps({
                "status": "FACTORY_READY",
                "currentGeneration": 372,
                "candidateCount": 91,
                "eliteCount": 4,
                "graveyardCount": 59,
                "nextGeneration": {"targetGeneration": 373},
                "safety": {
                    "orderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                    "gaDirectLiveAllowed": False,
                    "livePresetMutationAllowed": False,
                },
            }), encoding="utf-8")
            (runtime / "ga_factory" / "QuantGod_GAEliteArchive.json").write_text(json.dumps({
                "elites": [
                    {
                        "seedId": "GA-USDJPY-G0372-M0007",
                        "strategyId": "elite",
                        "fitness": 6.4823,
                        "promotionStage": "TESTER_ONLY",
                        "directLiveAllowed": False,
                    }
                ]
            }), encoding="utf-8")
            runner = AutomationChainRunner(Path.cwd(), runtime, ["USDJPYc"], python_bin="python")
            summary = runner._ga_factory_summary()
            self.assertTrue(summary["available"])
            self.assertEqual(summary["currentGeneration"], 372)
            self.assertEqual(summary["bestElite"]["seedId"], "GA-USDJPY-G0372-M0007")
            self.assertFalse(summary["safety"]["orderSendAllowed"])

    def test_safe_iteration_loop_tracks_bounded_progress(self):
        runner = AutomationChainRunner(Path.cwd(), "runtime", ["USDJPYc"], python_bin="python")
        cycle_payloads = [
            {
                "before": {
                    "state": "BLOCKED_BY_USDJPY_POLICY",
                    "entryReadiness": {"score": 42.9, "readyForEntryReview": False, "failedGapIds": ["signal_quorum"]},
                    "gaFactorySummary": {"currentGeneration": 374, "bestElite": {"seedId": "a", "fitness": 6.4, "promotionStage": "TESTER_ONLY", "directLiveAllowed": False}},
                },
                "after": {
                    "state": "BLOCKED_BY_USDJPY_POLICY",
                    "entryReadiness": {"score": 57.1, "readyForEntryReview": False, "failedGapIds": ["signal_quorum"]},
                    "gaFactorySummary": {"currentGeneration": 375, "bestElite": {"seedId": "b", "fitness": 6.8, "promotionStage": "TESTER_ONLY", "directLiveAllowed": False}},
                },
                "executedActionCount": 3,
                "executedCommandCount": 8,
                "commandResults": [{"actionId": "advance_ga_shadow_generation", "ok": True}],
                "safety": {"orderSendAllowed": False, "writesMt5OrderRequest": False},
            },
            {
                "before": {
                    "state": "BLOCKED_BY_USDJPY_POLICY",
                    "entryReadiness": {"score": 57.1, "readyForEntryReview": False, "failedGapIds": ["signal_quorum"]},
                    "gaFactorySummary": {"currentGeneration": 375, "bestElite": {"seedId": "b", "fitness": 6.8, "promotionStage": "TESTER_ONLY", "directLiveAllowed": False}},
                },
                "after": {
                    "state": "BLOCKED_BY_USDJPY_POLICY",
                    "entryReadiness": {"score": 57.1, "readyForEntryReview": False, "failedGapIds": ["signal_quorum"]},
                    "gaFactorySummary": {"currentGeneration": 376, "bestElite": {"seedId": "c", "fitness": 6.9, "promotionStage": "TESTER_ONLY", "directLiveAllowed": False}},
                },
                "executedActionCount": 3,
                "executedCommandCount": 8,
                "commandResults": [{"actionId": "advance_ga_shadow_generation", "ok": True}],
                "safety": {"orderSendAllowed": False, "writesMt5OrderRequest": False},
            },
        ]

        def fake_cycle(**_kwargs):
            return cycle_payloads.pop(0)

        runner.run_safe_iteration_cycle = fake_cycle  # type: ignore[method-assign]
        payload = runner.run_safe_iteration_loop(cycles=2, max_actions=3, write=False)

        self.assertEqual(payload["mode"], "SHADOW_SIMULATION_ONLY")
        self.assertEqual(payload["executedCycleCount"], 2)
        self.assertEqual(payload["stopReason"], "CYCLE_LIMIT_REACHED")
        self.assertEqual(payload["summary"]["readinessScoreDelta"], 14.2)
        self.assertEqual(payload["summary"]["gaGenerationDelta"], 2.0)
        self.assertEqual(payload["summary"]["bestFitnessDelta"], 0.5)
        self.assertFalse(payload["safety"]["orderSendAllowed"])
        self.assertFalse(payload["cycles"][0]["after"]["bestEliteDirectLiveAllowed"])

    def test_fresh_hfm_dashboard_replaces_runtime_snapshot_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            for folder in ("quality", "adaptive", "live"):
                (runtime / folder).mkdir(parents=True, exist_ok=True)
            required_files = [
                runtime / "quality" / "QuantGod_MT5FastLaneQuality.json",
                runtime / "adaptive" / "QuantGod_AdaptivePolicy.json",
                runtime / "adaptive" / "QuantGod_DynamicSLTPCalibration.json",
                runtime / "adaptive" / "QuantGod_EntryTriggerPlan.json",
                runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json",
                runtime / "adaptive" / "QuantGod_USDJPYEADryRunDecision.json",
                runtime / "live" / "QuantGod_USDJPYLiveLoopStatus.json",
            ]
            for path in required_files:
                path.write_text("{}", encoding="utf-8")
            (runtime / "QuantGod_Dashboard.json").write_text(json.dumps({
                "watchlist": "USDJPYc",
                "runtime": {
                    "tickAgeSeconds": 1,
                    "tradeStatus": "READY",
                    "executionEnabled": True,
                    "readOnlyMode": False,
                    "localTime": datetime.now(timezone.utc).isoformat(),
                },
            }), encoding="utf-8")
            runner = AutomationChainRunner(Path.cwd(), runtime, ["USDJPYc"], python_bin="python")
            self.assertEqual(runner._collect_missing_evidence(), [])

    def test_telegram_text_is_chinese_and_safe(self):
        report = {
            "stateZh": "阻断：证据不完整",
            "symbols": ["USDJPYc"],
            "singleSourceOfTruth": "USDJPY_LIVE_LOOP",
            "generatedAt": "2099-01-01T00:00:00Z",
            "steps": [{"labelZh": "P3-7 快通道质量", "ok": False, "summaryZh": "缺少质量文件"}],
            "missingEvidence": ["缺少 P3-7 快通道质量证据"],
            "blockedReasons": ["缺少运行快照"],
            "policySummary": {"opportunities": [], "blocked": []},
            "topAdvisoryPolicy": {"strategy": "RSI_Reversal", "direction": "LONG", "entryMode": "OPPORTUNITY_ENTRY", "recommendedLot": 0.12},
            "dryRunDecision": {"decision": "本应机会入场", "strategy": "RSI_Reversal", "direction": "LONG"},
            "entryLatencyReport": {
                "summary": {"stateZh": "策略政策", "primaryReasonZh": "政策阻断"},
                "timeline": [{"labelZh": "策略政策", "statusZh": "政策阻断", "reasonZh": "样本不足"}],
            },
            "safeIterationPlan": {
                "mode": "SHADOW_SIMULATION_ONLY",
                "readinessScore": 42.9,
                "gaFactorySummary": {
                    "currentGeneration": 372,
                    "bestElite": {"seedId": "GA-USDJPY-G0372-M0007", "fitness": 6.4823, "promotionStage": "TESTER_ONLY"},
                },
                "actions": [{"actionId": "refresh_policy_shadow_evidence", "labelZh": "刷新政策与影子样本", "nextRequiredActionZh": "继续刷新影子证据"}],
            },
        }
        text = build_automation_telegram_text(report)
        self.assertIn("QuantGod · 自动巡检", text)
        self.assertIn("结论：", text)
        self.assertIn("关键：", text)
        self.assertIn("原因：", text)
        self.assertIn("下一步：", text)
        self.assertIn("继续刷新影子证据", text)
        self.assertIn("无执行通道", text)
        self.assertLessEqual(len(text), 700)
        self.assertNotIn("OrderSend", text)


if __name__ == "__main__":
    unittest.main()
