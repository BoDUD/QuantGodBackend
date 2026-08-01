from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import atomic_write_json, build_empty_status, default_safety, latest_path, ledger_path, now_iso, run_path, validate_safe_payload


@dataclass
class ChainStep:
    name: str
    label_zh: str
    command: List[str]
    required: bool = True
    timeout_seconds: int = 120


class AutomationChainRunner:
    def __init__(self, repo_root: str | Path, runtime_dir: str | Path, symbols: List[str], python_bin: str | None = None, max_age_seconds: int = 180):
        self.repo_root = Path(repo_root).resolve()
        self.runtime_dir = Path(runtime_dir)
        focus_symbols = [s.strip() for s in symbols if s.strip() and s.strip().upper().startswith("USDJPY")]
        self.symbols = focus_symbols or ["USDJPYc"]
        self.python_bin = python_bin or sys.executable
        self.max_age_seconds = max_age_seconds

    def _script(self, name: str) -> str:
        return str(self.repo_root / "tools" / name)

    def _symbols_arg(self) -> str:
        return ",".join(self.symbols)

    def build_steps(self, send: bool = False) -> List[ChainStep]:
        runtime = str(self.runtime_dir)
        symbols = self._symbols_arg()
        steps = [
            ChainStep("fastlane_quality", "P3-7 快通道质量", [self.python_bin, self._script("run_mt5_fastlane.py"), "--runtime-dir", runtime, "quality", "--symbols", symbols], required=False),
            ChainStep("execution_feedback_producer", "执行反馈 entryContext 生产", [self.python_bin, self._script("run_execution_feedback_producer.py"), "--runtime-dir", runtime, "build", "--write"], required=False),
            ChainStep("case_memory", "四层交易记忆刷新", [self.python_bin, self._script("run_case_memory.py"), "--runtime-dir", runtime, "build", "--write", "--limit", "8"], required=False),
            ChainStep("adaptive_policy", "P3-6 自适应策略", [self.python_bin, self._script("run_adaptive_policy.py"), "--runtime-dir", runtime, "build", "--symbols", symbols], required=True),
            ChainStep("dynamic_sltp", "P3-8 动态止盈止损", [self.python_bin, self._script("run_dynamic_sltp.py"), "--runtime-dir", runtime, "build", "--symbols", symbols], required=True),
            ChainStep("entry_trigger", "P3-9 入场触发", [self.python_bin, self._script("run_entry_trigger_lab.py"), "--runtime-dir", runtime, "build", "--symbols", symbols], required=True),
            ChainStep("usdjpy_strategy_policy", "USDJPY 策略政策", [self.python_bin, self._script("run_usdjpy_strategy_lab.py"), "--runtime-dir", runtime, "build", "--write"], required=True),
            ChainStep("usdjpy_ea_dry_run", "USDJPY EA 干跑决策", [self.python_bin, self._script("run_usdjpy_strategy_lab.py"), "--runtime-dir", runtime, "dry-run", "--write"], required=True),
            ChainStep("usdjpy_live_loop", "USDJPY 实盘恢复闭环", [self.python_bin, self._script("run_usdjpy_live_loop.py"), "--runtime-dir", runtime, "once"], required=True),
            ChainStep("fastlane_quality_final", "P3-7 快通道质量收尾刷新", [self.python_bin, self._script("run_mt5_fastlane.py"), "--runtime-dir", runtime, "quality", "--symbols", symbols], required=False),
            ChainStep("strategy_parity", "P4-2 Strategy/Replay/EA parity", [self.python_bin, self._script("run_strategy_parity.py"), "--runtime-dir", runtime, "build", "--write"], required=False),
            ChainStep("entry_latency", "USDJPY 入场延迟归因", [self.python_bin, self._script("run_entry_latency.py"), "--runtime-dir", runtime, "build", "--write"], required=False),
        ]
        if send:
            steps.append(ChainStep("usdjpy_live_loop_telegram", "USDJPY 闭环 Telegram 中文推送", [self.python_bin, self._script("run_usdjpy_live_loop.py"), "--runtime-dir", runtime, "telegram-text", "--refresh", "--send"], required=False, timeout_seconds=60))
        return steps

    def _run_step(self, step: ChainStep) -> Dict[str, Any]:
        script_path = Path(step.command[1]) if len(step.command) > 1 else None
        if script_path and not script_path.exists():
            return {
                "name": step.name,
                "labelZh": step.label_zh,
                "ok": not step.required,
                "required": step.required,
                "skipped": True,
                "reason": f"脚本不存在：{script_path.name}",
                "summaryZh": "脚本不存在，已按缺失证据处理" if step.required else "脚本不存在，已跳过",
            }
        try:
            proc = subprocess.run(step.command, cwd=str(self.repo_root), text=True, capture_output=True, timeout=step.timeout_seconds, encoding="utf-8", errors="replace")
            ok = proc.returncode == 0
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            return {
                "name": step.name,
                "labelZh": step.label_zh,
                "ok": ok,
                "required": step.required,
                "exitCode": proc.returncode,
                "summaryZh": "运行完成" if ok else "运行失败",
                "stdoutPreview": stdout[-2000:],
                "stderrPreview": stderr[-2000:],
                "commandPreview": " ".join(Path(x).name if i == 1 and x.endswith('.py') else x for i, x in enumerate(step.command)),
            }
        except subprocess.TimeoutExpired:
            return {
                "name": step.name,
                "labelZh": step.label_zh,
                "ok": False,
                "required": step.required,
                "exitCode": -1,
                "summaryZh": "运行超时",
                "reason": "timeout",
            }
        except Exception as exc:  # pragma: no cover
            return {
                "name": step.name,
                "labelZh": step.label_zh,
                "ok": False,
                "required": step.required,
                "exitCode": -1,
                "summaryZh": f"运行异常：{exc}",
                "reason": str(exc),
            }

    def _read_json(self, *parts: str) -> Optional[Dict[str, Any]]:
        path = self.runtime_dir.joinpath(*parts)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return None

    def _input_fingerprint(self) -> str:
        evidence_paths = [
            self.runtime_dir / "QuantGod_Dashboard.json",
            self.runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json",
            self.runtime_dir / "production_validation" / "QuantGod_ProductionEvidenceValidationReport.json",
            self.runtime_dir / "ga_factory" / "QuantGod_GAFactoryState.json",
        ]
        rows = [f"symbols={self._symbols_arg()}", f"runtime={self.runtime_dir.resolve()}"]
        for evidence_path in evidence_paths:
            try:
                stat = evidence_path.stat()
                rows.append(f"{evidence_path.name}:{stat.st_size}:{stat.st_mtime_ns}")
            except FileNotFoundError:
                rows.append(f"{evidence_path.name}:missing")
        return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()

    def _next_due_at(self, generated_at: str) -> str:
        interval = max(5, int(os.environ.get("QG_AUTOMATION_INTERVAL_SECONDS", "300")))
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        return (generated + timedelta(seconds=interval)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _policy_file(self) -> Optional[Dict[str, Any]]:
        return self._read_json("adaptive", "QuantGod_USDJPYAutoExecutionPolicy.json")

    def _dry_run_file(self) -> Optional[Dict[str, Any]]:
        return self._read_json("adaptive", "QuantGod_USDJPYEADryRunDecision.json")

    def _live_loop_file(self) -> Optional[Dict[str, Any]]:
        return self._read_json("live", "QuantGod_USDJPYLiveLoopStatus.json")

    def _entry_latency_file(self) -> Optional[Dict[str, Any]]:
        return self._read_json("latency", "QuantGod_EntryLatencyReport.json")

    def _ga_factory_summary(self) -> Dict[str, Any]:
        state = self._read_json("ga_factory", "QuantGod_GAFactoryState.json") or {}
        elite_archive = self._read_json("ga_factory", "QuantGod_GAEliteArchive.json") or {}
        elites = elite_archive.get("elites") if isinstance(elite_archive.get("elites"), list) else []
        top_elites = []
        for row in elites[:4]:
            if not isinstance(row, dict):
                continue
            top_elites.append({
                "seedId": row.get("seedId"),
                "strategyId": row.get("strategyId"),
                "fitness": row.get("fitness"),
                "promotionStage": row.get("promotionStage"),
                "directLiveAllowed": bool(row.get("directLiveAllowed")),
                "blockerCode": row.get("blockerCode"),
            })
        safety = state.get("safety") if isinstance(state.get("safety"), dict) else {}
        return {
            "available": bool(state or elites),
            "status": state.get("status"),
            "statusZh": state.get("statusZh"),
            "currentGeneration": state.get("currentGeneration"),
            "candidateCount": state.get("candidateCount"),
            "eliteCount": state.get("eliteCount"),
            "graveyardCount": state.get("graveyardCount"),
            "nextGeneration": state.get("nextGeneration"),
            "topElites": top_elites,
            "bestElite": top_elites[0] if top_elites else None,
            "safety": {
                "orderSendAllowed": bool(safety.get("orderSendAllowed")),
                "writesMt5OrderRequest": bool(safety.get("writesMt5OrderRequest")),
                "gaDirectLiveAllowed": bool(safety.get("gaDirectLiveAllowed")),
                "livePresetMutationAllowed": bool(safety.get("livePresetMutationAllowed")),
            },
        }

    def _history_production_readiness(self) -> Dict[str, Any]:
        path = self.runtime_dir / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json"
        if not path.exists():
            return {
                "ready": False,
                "status": "MISSING",
                "freshness": "MISSING",
                "ageSeconds": None,
                "maxAgeSeconds": 7200,
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            status = str(payload.get("productionStatus") or payload.get("status") or "UNKNOWN").upper()
            max_age_seconds = max(60, int(os.environ.get("QG_HISTORY_STATUS_FRESH_SECONDS", "7200")))
            age_seconds = max(0.0, time.time() - path.stat().st_mtime)
            fresh = age_seconds <= max_age_seconds
            history_target_satisfied = payload.get("historyTargetSatisfied")
            freshness_ok = payload.get("freshnessOk")
            explicit_failure = history_target_satisfied is False or freshness_ok is False
            ready = fresh and status in {"PASS", "READY", "OK", "FRESH"} and not explicit_failure
            return {
                "ready": ready,
                "status": status,
                "freshness": "FRESH" if fresh else "STALE",
                "ageSeconds": age_seconds,
                "maxAgeSeconds": max_age_seconds,
                "historyTargetSatisfied": history_target_satisfied,
                "freshnessOk": freshness_ok,
                "filePath": str(path),
            }
        except Exception as exc:
            return {
                "ready": False,
                "status": "INVALID",
                "freshness": "INVALID",
                "ageSeconds": None,
                "maxAgeSeconds": 7200,
                "error": str(exc),
                "filePath": str(path),
            }

    def _dashboard_snapshot_covers_symbol(self, symbol: str) -> bool:
        path = self.runtime_dir / "QuantGod_Dashboard.json"
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return False
        age_seconds = time.time() - path.stat().st_mtime
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        tick_age = runtime.get("tickAgeSeconds")
        fresh = age_seconds <= self.max_age_seconds
        if isinstance(tick_age, (int, float)):
            fresh = fresh and float(tick_age) <= self.max_age_seconds
        if not fresh:
            return False
        wanted = str(symbol or "").upper()
        candidates = [
            payload.get("watchlist"),
            payload.get("symbol"),
            payload.get("focusSymbol"),
            runtime.get("symbol"),
            runtime.get("focusSymbol"),
        ]
        return any(str(candidate or "").upper() == wanted for candidate in candidates)

    def _collect_missing_evidence(self) -> List[str]:
        checks = [
            (self.runtime_dir / "quality" / "QuantGod_MT5FastLaneQuality.json", "缺少 P3-7 快通道质量证据"),
            (self.runtime_dir / "adaptive" / "QuantGod_AdaptivePolicy.json", "缺少 P3-6 自适应策略输出"),
            (self.runtime_dir / "adaptive" / "QuantGod_DynamicSLTPCalibration.json", "缺少 P3-8 动态止盈止损校准"),
            (self.runtime_dir / "adaptive" / "QuantGod_EntryTriggerPlan.json", "缺少 P3-9 入场触发计划"),
            (self.runtime_dir / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json", "缺少 USDJPY 策略政策"),
            (self.runtime_dir / "adaptive" / "QuantGod_USDJPYEADryRunDecision.json", "缺少 USDJPY EA 干跑决策"),
            (self.runtime_dir / "live" / "QuantGod_USDJPYLiveLoopStatus.json", "缺少 USDJPY 实盘恢复闭环状态"),
        ]
        missing = [label for path, label in checks if not path.exists()]
        for symbol in self.symbols:
            snapshot_path = self.runtime_dir / f"QuantGod_MT5RuntimeSnapshot_{symbol}.json"
            if not snapshot_path.exists() and not self._dashboard_snapshot_covers_symbol(symbol):
                missing.append(f"缺少 {symbol} 运行快照")
        return missing

    def _direction_zh(self, direction: str) -> str:
        return "买入观察" if str(direction).upper() in {"LONG", "BUY"} else "卖出观察"

    def _entry_mode_zh(self, mode: str) -> str:
        return {
            "STANDARD_ENTRY": "标准入场",
            "OPPORTUNITY_ENTRY": "机会入场",
            "BLOCKED": "阻断",
        }.get(str(mode), str(mode))

    def _reason_text(self, row: Dict[str, Any]) -> str:
        if row.get("reason"):
            return str(row.get("reason"))
        reasons = row.get("reasons") or []
        if isinstance(reasons, str):
            return reasons
        if isinstance(reasons, list):
            return "；".join(str(item) for item in reasons[:4] if item)
        return ""

    def _actionable_blockers(self, rows: List[str]) -> List[str]:
        positive_only = {
            "运行快照通过",
            "USDJPY 运行快照可用",
            "快通道质量通过",
            "动态止盈止损可用",
        }
        cleaned: List[str] = []
        for raw in rows:
            text = str(raw or "").strip()
            if not text:
                continue
            parts = [part.strip() for part in text.replace("\n", "；").split("；") if part.strip()]
            actionable_parts = [part for part in parts if part not in positive_only]
            cleaned.extend(actionable_parts)
        return list(dict.fromkeys(cleaned))

    def _summarize_policy(self, policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        summary = {"opportunities": [], "blocked": [], "standardCount": 0, "opportunityCount": 0, "blockedCount": 0}
        if not policy:
            return summary
        for row in policy.get("strategies", []) or policy.get("policies", []) or []:
            item = {
                "symbol": row.get("symbol"),
                "direction": row.get("direction"),
                "directionZh": self._direction_zh(row.get("direction", "")),
                "entryMode": row.get("entryMode"),
                "entryModeZh": self._entry_mode_zh(row.get("entryMode", "")),
                "recommendedLot": row.get("recommendedLot", 0),
                "score": row.get("score", 0),
                "reason": self._reason_text(row),
            }
            if row.get("entryMode") == "STANDARD_ENTRY" and row.get("allowed"):
                summary["standardCount"] += 1
                summary["opportunities"].append(item)
            elif row.get("entryMode") == "OPPORTUNITY_ENTRY" and row.get("allowed"):
                summary["opportunityCount"] += 1
                summary["opportunities"].append(item)
            else:
                summary["blockedCount"] += 1
                summary["blocked"].append(item)
        return summary

    def _status_from_live_loop(self, live_loop: Optional[Dict[str, Any]], policy_summary: Dict[str, Any], failed_required: List[Dict[str, Any]], missing: List[str]) -> tuple[str, str]:
        if failed_required or missing:
            return "BLOCKED_MISSING_EVIDENCE", "阻断：USDJPY 证据不完整"
        live_state = str((live_loop or {}).get("state") or "")
        live_state_zh = str((live_loop or {}).get("stateZh") or "")
        if live_state == "READY_FOR_EXISTING_EA":
            return "READY_FOR_EXISTING_EA", live_state_zh or "RSI 买入路线已恢复，等待 EA 自身信号"
        if live_state == "POLICY_READY_PRESET_BLOCKED":
            return "POLICY_READY_PRESET_BLOCKED", live_state_zh or "政策已就绪，但实盘 preset 尚未完全恢复"
        if live_state == "EVIDENCE_MISSING":
            return "BLOCKED_MISSING_EVIDENCE", live_state_zh or "证据链不完整，EA 不应自动入场"
        if live_state == "POLICY_BLOCKED":
            return "BLOCKED_BY_USDJPY_POLICY", live_state_zh or "政策仍阻断，EA 不应自动入场"
        if policy_summary["standardCount"] or policy_summary["opportunityCount"]:
            return "READY_WITH_USDJPY_OPPORTUNITIES", "发现 USDJPY 可复核机会"
        return "BLOCKED_BY_USDJPY_POLICY", "阻断：USDJPY 策略政策未放行"

    def _top_level_blocked_reasons(self, state: str, blockers: List[str]) -> List[str]:
        if str(state or "").startswith("BLOCKED"):
            return blockers
        return []

    def _command_text(self, command: List[str]) -> str:
        return " ".join(str(part) for part in command)

    def _safe_iteration_script_names(self) -> set[str]:
        return {
            "run_mt5_fastlane.py",
            "run_adaptive_policy.py",
            "run_entry_trigger_lab.py",
            "run_usdjpy_strategy_lab.py",
            "run_usdjpy_live_loop.py",
            "run_entry_latency.py",
            "run_execution_feedback_producer.py",
            "run_case_memory.py",
            "run_strategy_ga.py",
            "run_strategy_ga_factory.py",
            "run_strategy_parity.py",
            "run_automation_chain.py",
        }

    def _safe_iteration_action(
        self,
        action_id: str,
        label_zh: str,
        priority: int,
        reason_zh: str,
        next_required_action_zh: str,
        commands: List[List[str]],
        expected_evidence: List[str],
    ) -> Dict[str, Any]:
        return {
            "actionId": action_id,
            "labelZh": label_zh,
            "priority": priority,
            "mode": "SHADOW_SIMULATION_ONLY",
            "reasonZh": reason_zh,
            "nextRequiredActionZh": next_required_action_zh,
            "commands": [self._command_text(command) for command in commands],
            "commandArgv": commands,
            "expectedEvidence": expected_evidence,
            "safety": {
                "advisoryOnly": True,
                "simulationOrShadowOnly": True,
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerExecutionAllowed": False,
                "livePresetMutationAllowed": False,
            },
        }

    def _safe_iteration_plan(
        self,
        entry_latency: Optional[Dict[str, Any]],
        live_loop: Optional[Dict[str, Any]],
        policy_summary: Dict[str, Any],
        ga_factory_summary: Dict[str, Any],
        state: str,
    ) -> Dict[str, Any]:
        latency = entry_latency or {}
        readiness = latency.get("entryReadiness") if isinstance(latency.get("entryReadiness"), dict) else {}
        failed_gap_ids = [str(item) for item in readiness.get("failedGapIds", []) if item]
        failed_gap_set = set(failed_gap_ids)
        runtime = str(self.runtime_dir)
        symbols = self._symbols_arg()
        actions: List[Dict[str, Any]] = []
        try:
            ga_generation = int(float(ga_factory_summary.get("currentGeneration") or 0))
        except (TypeError, ValueError):
            ga_generation = 0
        ga_elite_count = ga_factory_summary.get("eliteCount")
        ga_no_elite_stop_generation = max(1, int(os.environ.get("QG_GA_NO_ELITE_STOP_GENERATION", "50")))
        history_readiness = self._history_production_readiness()
        ga_progression_paused = (
            ga_factory_summary.get("available")
            and (
                not history_readiness.get("ready")
                or (ga_elite_count == 0 and ga_generation >= ga_no_elite_stop_generation)
            )
        )

        if "market_data_ready" in failed_gap_set:
            actions.append(self._safe_iteration_action(
                "refresh_fastlane_quality",
                "刷新快通道行情证据",
                10,
                "快通道行情缺口仍未通过。",
                "先刷新 MT5 tick、指标和 dashboard heartbeat，再重新生成策略政策。",
                [[self.python_bin, self._script("run_mt5_fastlane.py"), "--runtime-dir", runtime, "quality", "--symbols", symbols]],
                ["QuantGod_MT5FastLaneQuality.json", "heartbeatFresh=true", "tick/indicator age within threshold"],
            ))

        if failed_gap_set.intersection({"policy_entry_mode", "signal_quorum", "shadow_sample_non_negative"}):
            actions.append(self._safe_iteration_action(
                "refresh_execution_feedback_memory",
                "刷新执行反馈与四层记忆",
                18,
                "策略证据不足时，先把 shadow/live 结果整理成 entryContext ledger，再刷新 case memory，避免下游只靠桥接/代理样本判断王牌。",
                "运行 execution feedback producer 和 case memory；只写 runtime 证据，不写订单、不改 preset。",
                [
                    [self.python_bin, self._script("run_execution_feedback_producer.py"), "--runtime-dir", runtime, "build", "--write"],
                    [self.python_bin, self._script("run_case_memory.py"), "--runtime-dir", runtime, "build", "--write", "--limit", "8"],
                ],
                [
                    "execution/QuantGod_LiveExecutionFeedbackProducerReport.json",
                    "case_memory/QuantGod_CaseMemoryStrategyCandidates.json",
                    "fineFactorMemoryHealth.rawCoverageRatio improves when raw fields exist",
                ],
            ))
            actions.append(self._safe_iteration_action(
                "refresh_policy_shadow_evidence",
                "刷新政策与影子样本",
                20,
                "策略仍未给出可复核 entryMode、信号 quorum 或非负影子样本。",
                "继续生成 adaptive policy、entry trigger 和 USDJPY live-loop 影子证据，直到 RSI_Reversal LONG 达到 quorum 且影子样本不为负。",
                [
                    [self.python_bin, self._script("run_adaptive_policy.py"), "--runtime-dir", runtime, "build", "--symbols", symbols],
                    [self.python_bin, self._script("run_entry_trigger_lab.py"), "--runtime-dir", runtime, "build", "--symbols", symbols],
                    [self.python_bin, self._script("run_usdjpy_strategy_lab.py"), "--runtime-dir", runtime, "build", "--write"],
                    [self.python_bin, self._script("run_usdjpy_live_loop.py"), "--runtime-dir", runtime, "once"],
                ],
                ["signalQuorum >= signalQuorumRequired", "entryMode=STANDARD_ENTRY/OPPORTUNITY_ENTRY", "影子样本未显示负期望=true"],
            ))
            if "policy_ea_signal_alignment" in failed_gap_set:
                actions.append(self._safe_iteration_action(
                    "build_signal_direction_shadow_strategy_intent",
                    "生成当前信号方向影子策略种子",
                    28,
                    "EA 实时 RSI 已给出 SELL，但 SELL 侧因 live loss review 被降级，不能直接开闸，需要先为当前信号方向补齐影子/回测证据。",
                    "用 Strategy JSON GA Factory 生成 USDJPY SHORT 影子/回测种子，验证方向一致性、动态止盈止损、样本质量和 live loss review 恢复条件；不改变实盘 preset，不写订单。",
                    [
                        [
                            self.python_bin,
                            self._script("run_strategy_ga_factory.py"),
                            "--runtime-dir",
                            runtime,
                            "intent-plan",
                            "--write",
                            "--prompt",
                            "USDJPY RSI_Reversal SHORT 低风险影子/回测策略；当前 EA RSI 给出 SELL，但 SELL live side 已因 live_loss_review 降级，只在 SHADOW/TESTER_ONLY 内补齐样本、动态止盈止损、方向一致性和恢复评审证据，不改 live preset，不写订单，回撤扩大就停手。",
                        ],
                        [self.python_bin, self._script("run_strategy_ga_factory.py"), "--runtime-dir", runtime, "build", "--write"],
                    ],
                    ["QuantGod_StrategyGAFactoryIntentPlan.json", "direction=SHORT remains SHADOW/TESTER_ONLY", "dynamic SLTP matches SHORT", "orderSendAllowed=false"],
                ))
            if "policy_ea_signal_alignment" not in failed_gap_set:
                actions.append(self._safe_iteration_action(
                    "build_shadow_strategy_intent",
                    "生成影子策略迭代种子",
                    30,
                    "当前策略性格还没把入场信号和影子样本推到可复核状态。",
                    "用 Strategy JSON GA Factory 生成低风险 USDJPY 影子/模拟种子，重点约束回撤和追单频率，不改变实盘执行闸门。",
                    [
                        [
                            self.python_bin,
                            self._script("run_strategy_ga_factory.py"),
                            "--runtime-dir",
                            runtime,
                            "intent-plan",
                            "--write",
                            "--prompt",
                            "USDJPY RSI_Reversal LONG 低风险影子策略，目标先证明本 lane 正收益并保持非负期望；信号 quorum 不足时减少追单，优先等待确认，回撤扩大就停手。",
                        ],
                        [self.python_bin, self._script("run_strategy_ga_factory.py"), "--runtime-dir", runtime, "build", "--write"],
                    ],
                    ["QuantGod_StrategyGAFactoryIntentPlan.json", "QuantGod_GAFactoryReflectionReport.json", "personality lock passed"],
                ))

        if failed_gap_set.intersection({"policy_ea_signal_alignment", "shadow_sample_non_negative", "signal_quorum"}) or (
            ga_factory_summary.get("available") and str(state or "").startswith("BLOCKED")
        ):
            actions.append(self._safe_iteration_action(
                "refresh_strategy_parity_evidence",
                "刷新 Strategy/Replay/EA parity 证据",
                32,
                "GA 候选晋级需要最新 Strategy JSON、Python replay 和 MQL5 EA parity 证据；旧 parity 会把高分候选错误归类到缺证据 blocker。",
                "在推进下一代 GA 前刷新 P4-2 parity，只更新审计证据，不改变实盘 preset，不写订单。",
                [[self.python_bin, self._script("run_strategy_parity.py"), "--runtime-dir", runtime, "build", "--write"]],
                ["parity/QuantGod_StrategyParityReport.json", "evidence_os/QuantGod_StrategyParityReport.json", "promotionGate.status"],
            ))

        if (
            ga_factory_summary.get("available")
            and str(state or "").startswith("BLOCKED")
            and not ga_progression_paused
        ):
            actions.append(self._safe_iteration_action(
                "advance_ga_shadow_generation",
                "推进 GA 影子下一代",
                35,
                "GA Factory 已就绪，可继续在 TESTER_ONLY/FAST_SHADOW 范围做下一代 mutation/crossover 或扩大搜索。",
                "运行一代 Strategy JSON GA，再重新归档 Factory；只允许 SHADOW/TESTER/PAPER_SIM 阶段，不进入实盘。",
                [
                    [self.python_bin, self._script("run_strategy_ga.py"), "--runtime-dir", runtime, "run-generation", "--write"],
                    [self.python_bin, self._script("run_strategy_ga_factory.py"), "--runtime-dir", runtime, "build", "--write"],
                ],
                ["QuantGod_GAFactoryState.json currentGeneration increases", "elite directLiveAllowed=false", "orderSendAllowed=false"],
            ))

        if failed_gap_set.intersection({"ea_startup_guard_clear", "ea_spread_gate", "ea_entry_guard_ready"}):
            actions.append(self._safe_iteration_action(
                "refresh_ea_entry_diagnostics",
                "刷新 EA 入场守门诊断",
                40,
                "EA 守门仍未进入可复核状态。",
                "刷新入场延迟报告和 USDJPY live-loop，只观察启动保护、点差、新闻和 RSI 信号是否解除。",
                [
                    [self.python_bin, self._script("run_usdjpy_live_loop.py"), "--runtime-dir", runtime, "once"],
                    [self.python_bin, self._script("run_mt5_fastlane.py"), "--runtime-dir", runtime, "quality", "--symbols", symbols],
                    [self.python_bin, self._script("run_entry_latency.py"), "--runtime-dir", runtime, "build", "--write"],
                ],
                ["startupGuardActive=false", "spreadAllowed=true", "EA state=READY/READY_SIGNAL/NEWS_BLOCK"],
            ))

        order_status = ""
        for stage in latency.get("timeline", []) or []:
            if isinstance(stage, dict) and stage.get("stage") == "order_attempt":
                order_status = str(stage.get("status") or "")
                break
        if order_status in {"NO_ATTEMPT", "STALE_ATTEMPT"}:
            actions.append(self._safe_iteration_action(
                "inspect_readonly_order_feedback",
                "复核只读订单反馈",
                50,
                "当前没有新鲜订单反馈证据，或只有过期历史事件。",
                "仅检查执行反馈文件的新鲜度；在单独执行 lane 通过前不写 MT5 request。",
                [[self.python_bin, self._script("run_entry_latency.py"), "--runtime-dir", runtime, "build", "--write"]],
                ["fresh send/fill/reject/entry feedback only after reviewed execution lane", "orderSendAllowed=false"],
            ))

        if not actions and str(state or "").startswith("BLOCKED"):
            actions.append(self._safe_iteration_action(
                "rerun_safe_automation_chain",
                "重跑安全自动化链",
                60,
                "阻断仍存在，但没有可定位的入场缺口字段。",
                "重跑 USDJPY 自动化链刷新证据，再按新的 readiness gaps 判断下一步。",
                [[self.python_bin, self._script("run_automation_chain.py"), "--runtime-dir", runtime, "--symbols", symbols, "once"]],
                ["QuantGod_AutomationChainLatest.json", "readinessGaps"],
            ))

        actions.sort(key=lambda item: int(item.get("priority") or 99))
        return {
            "schema": "quantgod.safe_autonomous_iteration_plan.v1",
            "mode": "SHADOW_SIMULATION_ONLY",
            "state": "ITERATION_REQUIRED" if actions else "WAIT_FOR_NEXT_SIGNAL_OR_EXECUTION_REVIEW",
            "stateZh": "需要继续影子/模拟迭代" if actions else "暂未发现新的安全迭代动作",
            "readinessScore": readiness.get("score"),
            "readyForEntryReview": bool(readiness.get("readyForEntryReview")),
            "failedGapIds": failed_gap_ids,
            "actionCount": len(actions),
            "actions": actions,
            "liveLoopState": (live_loop or {}).get("state"),
            "standardCount": policy_summary.get("standardCount", 0),
            "opportunityCount": policy_summary.get("opportunityCount", 0),
            "gaFactorySummary": ga_factory_summary,
            "gaProgression": {
                "paused": bool(ga_progression_paused),
                "reasonCode": (
                    "HISTORY_NOT_READY"
                    if ga_factory_summary.get("available") and not history_readiness.get("ready")
                    else "NO_ELITE_GENERATION_LIMIT"
                    if ga_progression_paused
                    else "ELIGIBLE_FOR_SHADOW_REVIEW"
                ),
                "currentGeneration": ga_generation,
                "eliteCount": ga_elite_count,
                "stopGeneration": ga_no_elite_stop_generation,
                "requiresNewDataOrHypothesis": bool(ga_progression_paused),
            },
            "dataReadiness": {"historyProduction": history_readiness},
            "safety": {
                "advisoryOnly": True,
                "simulationOrShadowOnly": True,
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerExecutionAllowed": False,
                "livePresetMutationAllowed": False,
            },
        }

    def _validate_safe_iteration_command(self, command: List[str]) -> None:
        if not command or len(command) < 2:
            raise ValueError("安全迭代命令缺少脚本。")
        script = Path(str(command[1])).name
        if script not in self._safe_iteration_script_names():
            raise ValueError(f"安全迭代命令不在白名单：{script}")
        lowered = " ".join(str(part).lower() for part in command)
        forbidden_tokens = (
            "ordersend",
            "order-send",
            "quick-trade",
            "privatekey",
            "private_key",
            "wallet",
            "--send",
            "telegram-text",
            "live-preset",
            "preset-mutation",
            "broker-order",
        )
        blocked = [token for token in forbidden_tokens if token in lowered]
        if blocked:
            raise ValueError(f"安全迭代命令包含禁止片段：{', '.join(blocked)}")

    def _safe_iteration_timeout_seconds(self, action: Dict[str, Any], command: List[str]) -> int:
        action_id = str(action.get("actionId") or "")
        script = Path(str(command[1])).name if len(command) > 1 else ""
        if action_id == "advance_ga_shadow_generation" and script == "run_strategy_ga.py":
            return 420
        if action_id == "advance_ga_shadow_generation":
            return 240
        return 180

    def _run_safe_iteration_command(self, action: Dict[str, Any], command: List[str]) -> Dict[str, Any]:
        self._validate_safe_iteration_command(command)
        step = ChainStep(
            str(action.get("actionId") or "safe_iteration"),
            str(action.get("labelZh") or "安全迭代动作"),
            command,
            required=False,
            timeout_seconds=self._safe_iteration_timeout_seconds(action, command),
        )
        result = self._run_step(step)
        result["actionId"] = action.get("actionId")
        result["mode"] = "SHADOW_SIMULATION_ONLY"
        result["safety"] = {
            "advisoryOnly": True,
            "simulationOrShadowOnly": True,
            "orderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "brokerExecutionAllowed": False,
            "livePresetMutationAllowed": False,
        }
        return result

    def run_safe_iteration_cycle(
        self,
        *,
        refresh_before: bool = True,
        refresh_after: bool = True,
        max_actions: Optional[int] = None,
        write: bool = True,
    ) -> Dict[str, Any]:
        before = self.run_once(send=False, write=write) if refresh_before else self.build_status()
        plan = before.get("safeIterationPlan") if isinstance(before.get("safeIterationPlan"), dict) else {}
        actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
        if max_actions is not None:
            actions = actions[: max(0, int(max_actions))]

        command_results: List[Dict[str, Any]] = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            commands = action.get("commandArgv") if isinstance(action.get("commandArgv"), list) else []
            for command in commands:
                if not isinstance(command, list):
                    continue
                command_results.append(self._run_safe_iteration_command(action, [str(part) for part in command]))

        after = self.run_once(send=False, write=write) if refresh_after else self.build_status()
        payload = {
            "schema": "quantgod.safe_iteration_cycle.v1",
            "generatedAt": now_iso(),
            "runtimeDir": str(self.runtime_dir),
            "symbols": self.symbols,
            "mode": "SHADOW_SIMULATION_ONLY",
            "before": {
                "state": before.get("state"),
                "stateZh": before.get("stateZh"),
                "entryReadiness": (before.get("entryLatencyReport") or {}).get("entryReadiness"),
                "gaFactorySummary": before.get("gaFactorySummary"),
                "safeIterationActionCount": plan.get("actionCount"),
            },
            "after": {
                "state": after.get("state"),
                "stateZh": after.get("stateZh"),
                "entryReadiness": (after.get("entryLatencyReport") or {}).get("entryReadiness"),
                "gaFactorySummary": after.get("gaFactorySummary"),
                "safeIterationActionCount": (after.get("safeIterationPlan") or {}).get("actionCount"),
            },
            "executedActionCount": len({str(result.get("actionId") or "") for result in command_results if result.get("actionId")}),
            "executedCommandCount": len(command_results),
            "commandResults": command_results,
            "safety": {
                "advisoryOnly": True,
                "simulationOrShadowOnly": True,
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerExecutionAllowed": False,
                "livePresetMutationAllowed": False,
                "telegramCommandExecutionAllowed": False,
            },
        }
        validate_safe_payload(payload)
        if write:
            target = self.runtime_dir / "automation" / "QuantGod_SafeIterationCycleLatest.json"
            atomic_write_json(target, payload)
        return payload

    def _loop_measure(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        readiness = snapshot.get("entryReadiness") if isinstance(snapshot.get("entryReadiness"), dict) else {}
        ga = snapshot.get("gaFactorySummary") if isinstance(snapshot.get("gaFactorySummary"), dict) else {}
        best = ga.get("bestElite") if isinstance(ga.get("bestElite"), dict) else {}
        return {
            "state": snapshot.get("state"),
            "readinessScore": readiness.get("score"),
            "readyForEntryReview": bool(readiness.get("readyForEntryReview")),
            "failedGapIds": readiness.get("failedGapIds") if isinstance(readiness.get("failedGapIds"), list) else [],
            "gaGeneration": ga.get("currentGeneration"),
            "bestFitness": best.get("fitness"),
            "bestEliteSeedId": best.get("seedId"),
            "bestEliteStage": best.get("promotionStage"),
            "bestEliteDirectLiveAllowed": bool(best.get("directLiveAllowed")),
        }

    def _metric_delta(self, after: Any, before: Any) -> Optional[float]:
        if not isinstance(after, (int, float)) or not isinstance(before, (int, float)):
            return None
        return round(float(after) - float(before), 6)

    def run_safe_iteration_loop(
        self,
        *,
        cycles: int = 2,
        max_actions: Optional[int] = None,
        write: bool = True,
    ) -> Dict[str, Any]:
        cycle_limit = max(0, min(int(cycles), 10))
        cycle_reports: List[Dict[str, Any]] = []
        stop_reason = "CYCLE_LIMIT_REACHED"
        for index in range(cycle_limit):
            cycle = self.run_safe_iteration_cycle(
                refresh_before=True,
                refresh_after=True,
                max_actions=max_actions,
                write=write,
            )
            before_measure = self._loop_measure(cycle.get("before") if isinstance(cycle.get("before"), dict) else {})
            after_measure = self._loop_measure(cycle.get("after") if isinstance(cycle.get("after"), dict) else {})
            cycle_reports.append({
                "cycleIndex": index + 1,
                "executedActionCount": cycle.get("executedActionCount"),
                "executedCommandCount": cycle.get("executedCommandCount"),
                "before": before_measure,
                "after": after_measure,
                "readinessScoreDelta": self._metric_delta(after_measure.get("readinessScore"), before_measure.get("readinessScore")),
                "gaGenerationDelta": self._metric_delta(after_measure.get("gaGeneration"), before_measure.get("gaGeneration")),
                "bestFitnessDelta": self._metric_delta(after_measure.get("bestFitness"), before_measure.get("bestFitness")),
                "commandFailures": [
                    {
                        "actionId": row.get("actionId"),
                        "summaryZh": row.get("summaryZh") or row.get("reason"),
                        "exitCode": row.get("exitCode"),
                    }
                    for row in cycle.get("commandResults", [])
                    if isinstance(row, dict) and not row.get("ok")
                ],
                "safety": cycle.get("safety"),
            })
            if after_measure.get("readyForEntryReview"):
                stop_reason = "READY_FOR_ENTRY_REVIEW"
                break
            if not cycle.get("executedCommandCount"):
                stop_reason = "NO_SAFE_ACTIONS"
                break
            if cycle_reports[-1]["commandFailures"]:
                stop_reason = "COMMAND_FAILURE"
                break

        first_before = cycle_reports[0]["before"] if cycle_reports else {}
        last_after = cycle_reports[-1]["after"] if cycle_reports else {}
        payload = {
            "schema": "quantgod.safe_iteration_loop.v1",
            "generatedAt": now_iso(),
            "runtimeDir": str(self.runtime_dir),
            "symbols": self.symbols,
            "mode": "SHADOW_SIMULATION_ONLY",
            "requestedCycleCount": cycle_limit,
            "executedCycleCount": len(cycle_reports),
            "maxActionsPerCycle": max_actions,
            "stopReason": stop_reason,
            "cycles": cycle_reports,
            "summary": {
                "initial": first_before,
                "final": last_after,
                "readinessScoreDelta": self._metric_delta(last_after.get("readinessScore"), first_before.get("readinessScore")),
                "gaGenerationDelta": self._metric_delta(last_after.get("gaGeneration"), first_before.get("gaGeneration")),
                "bestFitnessDelta": self._metric_delta(last_after.get("bestFitness"), first_before.get("bestFitness")),
            },
            "safety": {
                "advisoryOnly": True,
                "simulationOrShadowOnly": True,
                "orderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "brokerExecutionAllowed": False,
                "livePresetMutationAllowed": False,
                "telegramCommandExecutionAllowed": False,
            },
        }
        validate_safe_payload(payload)
        if write:
            target = self.runtime_dir / "automation" / "QuantGod_SafeIterationLoopLatest.json"
            atomic_write_json(target, payload)
        return payload

    def build_status(self) -> Dict[str, Any]:
        if not latest_path(self.runtime_dir).exists():
            return build_empty_status(self.runtime_dir, self.symbols)
        try:
            return json.loads(latest_path(self.runtime_dir).read_text(encoding="utf-8-sig"))
        except Exception:
            return build_empty_status(self.runtime_dir, self.symbols)

    def run_once(self, send: bool = False, write: bool = True) -> Dict[str, Any]:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        cycle_id = f"cycle-{uuid.uuid4().hex}"
        started_at = now_iso()
        input_fingerprint = self._input_fingerprint()
        steps = [self._run_step(step) for step in self.build_steps(send=send)]
        missing = self._collect_missing_evidence()
        policy = self._policy_file()
        dry_run = self._dry_run_file()
        live_loop = self._live_loop_file()
        entry_latency = self._entry_latency_file()
        ga_factory_summary = self._ga_factory_summary()
        policy_summary = self._summarize_policy(policy)
        failed_required = [s for s in steps if s.get("required") and not s.get("ok")]
        blocked_reasons: List[str] = []
        for step in failed_required:
            blocked_reasons.append(f"{step.get('labelZh')}未通过：{step.get('summaryZh') or step.get('reason')}")
        blocked_reasons.extend(missing)
        blocked_reasons.extend([str(x) for x in (live_loop or {}).get("whyNoEntry", [])[:8] if x])
        blocked_reasons.extend([item.get("reason", "") for item in policy_summary.get("blocked", [])[:6] if item.get("reason")])
        blocked_reasons = self._actionable_blockers(blocked_reasons)
        state, state_zh = self._status_from_live_loop(live_loop, policy_summary, failed_required, missing)
        top_level_blocked_reasons = self._top_level_blocked_reasons(state, blocked_reasons)
        safe_iteration_plan = self._safe_iteration_plan(entry_latency, live_loop, policy_summary, ga_factory_summary, state)
        generated_at = now_iso()
        run_status = "FAILED" if failed_required else "COMPLETED"
        report = {
            "schema": "quantgod.automation_chain.v1",
            "cycleId": cycle_id,
            "runStatus": run_status,
            "startedAt": started_at,
            "completedAt": generated_at,
            "generatedAt": generated_at,
            "heartbeatAt": generated_at,
            "lastSuccessAt": generated_at if run_status == "COMPLETED" else None,
            "nextDueAt": self._next_due_at(generated_at),
            "retryCount": 0,
            "currentStep": "completed" if run_status == "COMPLETED" else "failed",
            "stepCount": len(steps),
            "requiredStepCount": sum(1 for step in steps if step.get("required")),
            "requiredFailedCount": len(failed_required),
            "inputFingerprint": input_fingerprint,
            "runtimeDir": str(self.runtime_dir),
            "symbols": self.symbols,
            "singleSourceOfTruth": "USDJPY_LIVE_LOOP",
            "sourceFiles": {
                "executionFeedbackProducer": str(self.runtime_dir / "execution" / "QuantGod_LiveExecutionFeedbackProducerReport.json"),
                "caseMemory": str(self.runtime_dir / "case_memory" / "QuantGod_CaseMemoryStrategyCandidates.json"),
                "policy": str(self.runtime_dir / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json"),
                "dryRun": str(self.runtime_dir / "adaptive" / "QuantGod_USDJPYEADryRunDecision.json"),
                "liveLoop": str(self.runtime_dir / "live" / "QuantGod_USDJPYLiveLoopStatus.json"),
                "entryLatency": str(self.runtime_dir / "latency" / "QuantGod_EntryLatencyReport.json"),
            },
            "state": state,
            "stateZh": state_zh,
            "steps": steps,
            "missingEvidence": sorted(set(missing)),
            "blockedReasons": [x for x in top_level_blocked_reasons if x],
            "shadowBlockedReasons": [x for x in blocked_reasons if x],
            "policySummary": policy_summary,
            "topLiveEligiblePolicy": (live_loop or {}).get("topLiveEligiblePolicy") or (policy or {}).get("topLiveEligiblePolicy"),
            "topShadowPolicy": (live_loop or {}).get("topShadowPolicy") or (policy or {}).get("topShadowPolicy"),
            "dryRunDecision": dry_run,
            "liveLoopStatus": live_loop,
            "entryLatencyReport": entry_latency,
            "entryLatencySummary": (entry_latency or {}).get("summary"),
            "entryLatencyTimeline": (entry_latency or {}).get("timeline", []),
            "gaFactorySummary": ga_factory_summary,
            "safeIterationPlan": safe_iteration_plan,
            "standardCount": policy_summary["standardCount"],
            "opportunityCount": policy_summary["opportunityCount"],
            "blockedCount": policy_summary["blockedCount"],
            "safety": default_safety(),
        }
        report["outputFingerprint"] = hashlib.sha256(
            json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        validate_safe_payload(report)
        if write:
            self.write_report(report)
        return report

    def write_report(self, report: Dict[str, Any]) -> None:
        target_dir = latest_path(self.runtime_dir).parent
        target_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(latest_path(self.runtime_dir), report)
        atomic_write_json(run_path(self.runtime_dir), report)
        ledger = ledger_path(self.runtime_dir)
        exists = ledger.exists()
        with ledger.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["generatedAt", "state", "stateZh", "standardCount", "opportunityCount", "blockedCount", "missingCount"])
            if not exists:
                writer.writeheader()
            writer.writerow({
                "generatedAt": report.get("generatedAt"),
                "state": report.get("state"),
                "stateZh": report.get("stateZh"),
                "standardCount": report.get("standardCount", 0),
                "opportunityCount": report.get("opportunityCount", 0),
                "blockedCount": report.get("blockedCount", 0),
                "missingCount": len(report.get("missingEvidence", [])),
            })


def loop_forever(runner: AutomationChainRunner, interval_seconds: int, send: bool = False) -> None:
    while True:
        report = runner.run_once(send=send, write=True)
        print(json.dumps({"generatedAt": report.get("generatedAt"), "state": report.get("state"), "stateZh": report.get("stateZh")}, ensure_ascii=False))
        time.sleep(max(5, int(interval_seconds)))
