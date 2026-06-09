import tempfile
import unittest
import os
import json
from pathlib import Path

from tools.strategy_ga.cache import evidence_signature
from tools.strategy_ga.fitness import _execution_blocks_strategy_ranking, evidence_metrics, score_seed
from tools.strategy_ga.generation_runner import read_candidate, read_candidates, run_generation
from tools.strategy_ga.population import build_population, _strategy_content_key
from tools.strategy_ga.telegram_text import ga_to_chinese_text
from tools.strategy_json.schema import base_strategy_seed
from tools.strategy_json.validator import validate_strategy_json


class StrategyJsonGATests(unittest.TestCase):
    def _write_case_memory_feedback(self, runtime_dir: Path, *, penalty: float = 0.2) -> None:
        case_dir = runtime_dir / "case_memory"
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "QuantGod_CaseMemoryStrategyCandidates.json").write_text(
            json.dumps(
                {
                    "schema": "quantgod.case_memory_strategy_candidate_report.v1",
                    "longTermTradeMemory": {
                        "schema": "quantgod.long_term_trade_memory.v1",
                        "generatedAt": "2099-01-01T00:00:00Z",
                        "status": "READY_TO_ADJUST",
                        "rollingReview": {
                            "status": "READY_TO_ADJUST",
                            "sampleCount": 18,
                            "winRate": 0.38,
                            "totalProfitR": -1.4,
                        },
                        "entryFeedbackPolicy": {
                            "status": "DEFENSE_MODE",
                            "sampleCount": 18,
                            "candidatePenaltyRules": [
                                {
                                    "match": {"symbol": "USDJPYc"},
                                    "penalty": penalty,
                                    "reasonZh": "USDJPYc 近期拖累，下一轮候选扣分。",
                                },
                                {
                                    "match": {"side": "LONG"},
                                    "penalty": penalty,
                                    "reasonZh": "LONG 近期弱，降低这一侧进攻欲望。",
                                },
                                {
                                    "match": {"dataGap": "dataCoverage"},
                                    "penalty": 0.1,
                                    "reasonZh": "低覆盖亏损偏多，提高覆盖门槛。",
                                },
                            ],
                            "defenseMode": {"enabled": True, "riskMultiplierCap": 0.35},
                        },
                        "nextActionZh": "长期记忆测试扣分。",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_ga_fitness_consumes_long_term_memory_penalties(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            self._write_case_memory_feedback(runtime_dir, penalty=0.2)
            seed = base_strategy_seed("GA-USDJPY-MEMORY-LONG", direction="LONG")

            score = score_seed(seed, runtime_dir)

            feedback = score["longTermMemoryFeedback"]
            self.assertTrue(feedback["present"])
            self.assertEqual(feedback["appliedRuleCount"], 3)
            self.assertAlmostEqual(feedback["directPenalty"], 0.4)
            self.assertAlmostEqual(feedback["globalContextPenalty"], 0.035)
            self.assertAlmostEqual(feedback["defensePenalty"], 0.15)
            self.assertAlmostEqual(feedback["penalty"], 0.585)
            self.assertGreaterEqual(score["evidencePenalty"], feedback["penalty"])

    def test_ga_fitness_cache_signature_tracks_long_term_memory_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            before = evidence_signature(runtime_dir)
            self._write_case_memory_feedback(runtime_dir, penalty=0.1)
            after = evidence_signature(runtime_dir)

            self.assertNotEqual(before, after)

    def test_live_lane_governance_block_does_not_stop_shadow_strategy_ranking(self):
        self.assertFalse(
            _execution_blocks_strategy_ranking(
                {
                    "promotionGateStatus": "BLOCKED",
                    "blockerCodes": ["LIVE_LANE_STRATEGY_LOCK_MISMATCH"],
                }
            )
        )
        self.assertTrue(
            _execution_blocks_strategy_ranking(
                {
                    "promotionGateStatus": "BLOCKED",
                    "blockerCodes": ["LIVE_EXECUTION_FEEDBACK_FIELD_GAP"],
                }
            )
        )

    def test_fitness_reads_standard_parity_directory_when_evidence_os_copy_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            parity_dir = runtime_dir / "parity"
            parity_dir.mkdir(parents=True)
            (parity_dir / "QuantGod_StrategyParityReport.json").write_text(
                json.dumps(
                    {
                        "status": "PARITY_PASS",
                        "promotionGate": {
                            "status": "PASS",
                            "promotionAllowed": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            metrics = evidence_metrics(runtime_dir)

            self.assertTrue(metrics["parity"]["present"])
            self.assertEqual(metrics["parity"]["status"], "PARITY_PASS")
            self.assertEqual(metrics["parity"]["promotionGateStatus"], "PASS")
            self.assertTrue(metrics["parity"]["promotionAllowed"])

    def test_demoted_parity_warn_blocks_live_but_not_shadow_strategy_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            evidence_dir = runtime_dir / "evidence_os"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "QuantGod_StrategyParityReport.json").write_text(
                json.dumps(
                    {
                        "status": "PARITY_WARN",
                        "promotionGate": {
                            "status": "BLOCKED",
                            "promotionAllowed": False,
                            "blockerCount": 2,
                        },
                        "deepParity": {
                            "status": "WARN",
                            "hardMismatches": [],
                            "softMismatches": ["mql5.rsi.signalDirection"],
                            "demotedOutOfScopeSignal": {
                                "demoted": True,
                                "expectedDirection": "LONG",
                                "signalDirection": "SHORT",
                                "promotionImpact": "BLOCK_PROMOTION_KEEP_LIVE_ROUTE_LOCK",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            metrics = evidence_metrics(runtime_dir)

            self.assertEqual(metrics["parity"]["promotionGateStatus"], "BLOCKED")
            self.assertFalse(metrics["parity"]["promotionAllowed"])
            self.assertTrue(metrics["parity"]["shadowOnlyReviewAllowed"])
            self.assertFalse(metrics["parity"]["blocksStrategyRanking"])
            self.assertEqual(metrics["parity"]["penalty"], 0.2)

    def test_validator_rejects_execution_primitives_and_live_privileges(self):
        seed = base_strategy_seed("GA-USDJPY-TEST")
        seed["entry"]["conditions"].append("OrderSend()")
        self.assertFalse(validate_strategy_json(seed)["valid"])

        seed = base_strategy_seed("GA-USDJPY-TEST")
        seed["risk"]["maxLot"] = 2.1
        self.assertEqual(validate_strategy_json(seed)["blockerCode"], "MAX_LOT_TOO_HIGH")

        seed = base_strategy_seed("GA-USDJPY-TEST")
        seed["risk"]["stage"] = "MICRO_LIVE"
        self.assertEqual(validate_strategy_json(seed)["blockerCode"], "LIVE_STAGE_REJECTED")

        seed = base_strategy_seed("GA-USDJPY-TEST")
        seed["symbol"] = "EURUSDc"
        self.assertEqual(validate_strategy_json(seed)["blockerCode"], "NON_USDJPY_REJECTED")

    def test_validator_allows_explicit_false_safety_boundary_fields(self):
        seed = base_strategy_seed("GA-USDJPY-SAFE")
        result = validate_strategy_json(seed)
        self.assertTrue(result["valid"], result)
        self.assertFalse(result["normalized"]["safety"]["orderSendAllowed"])
        self.assertFalse(result["normalized"]["safety"]["telegramCommandExecutionAllowed"])

    def test_generation_writes_trace_files_and_never_promotes_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            result = run_generation(runtime_dir, write=True)
            ga_dir = runtime_dir / "ga"

            for name in [
                "QuantGod_GAStatus.json",
                "QuantGod_GAGenerationLatest.json",
                "QuantGod_GACandidateRuns.jsonl",
                "QuantGod_GAEliteStrategies.json",
                "QuantGod_GABlockerSummary.json",
                "QuantGod_GAEvolutionPath.json",
                "QuantGod_GAFitnessCache.json",
                "QuantGod_GALineage.json",
                "QuantGod_GARunLimiter.json",
            ]:
                self.assertTrue((ga_dir / name).exists(), name)

            self.assertTrue(result["candidates"])
            self.assertTrue(result["generation"]["strategyBacktest"]["required"])
            self.assertTrue(result["generation"]["walkForward"]["required"])
            self.assertIn("qualityRepairCount", result["generation"])
            self.assertEqual(result["generation"]["searchExpansion"]["schema"], "quantgod.ga.search_expansion.v1")
            self.assertEqual(
                result["generation"]["strategyBacktest"]["scoredCount"],
                len(result["candidates"]),
            )
            self.assertEqual(
                result["generation"]["walkForward"]["scoredCount"],
                len(result["candidates"]),
            )
            for row in result["candidates"]:
                self.assertEqual(row["strategyJson"]["symbol"], "USDJPYc")
                self.assertIn("generationId", row)
                self.assertIn("seedId", row)
                self.assertIn("fitness", row)
                self.assertIn("blockerCode", row)
                backtest = row["fitnessBreakdown"]["strategyBacktest"]
                walk_forward = row["fitnessBreakdown"]["walkForward"]
                for field in [
                    "required",
                    "present",
                    "ok",
                    "netR",
                    "profitFactor",
                    "winRate",
                    "maxDrawdownR",
                    "sharpe",
                    "sortino",
                    "tradeCount",
                ]:
                    self.assertIn(field, backtest)
                self.assertTrue(backtest["required"])
                self.assertTrue(backtest["present"])
                self.assertEqual(walk_forward["schema"], "quantgod.usdjpy_seed_walk_forward.v1")
                self.assertEqual([item["segment"] for item in walk_forward["segments"]], ["train", "validation", "forward"])
                self.assertIn("stabilityScore", walk_forward["summary"])
                self.assertIn("walkForwardPenalty", row["fitnessBreakdown"])
                self.assertIn("walkForwardStabilityBonus", row["fitnessBreakdown"])
                self.assertNotIn(row["promotionStage"], {"MICRO_LIVE", "LIVE_LIMITED"})
                self.assertFalse(row["safety"]["orderSendAllowed"])
                self.assertFalse(row["safety"]["livePresetMutationAllowed"])

            latest = read_candidates(runtime_dir)
            self.assertEqual(len(latest["candidates"]), len(result["candidates"]))

            detail = read_candidate(runtime_dir, result["candidates"][0]["seedId"])
            self.assertTrue(detail["ok"], detail)
            audit = detail["candidate"]["audit"]
            self.assertEqual(audit["schema"], "quantgod.ga.candidate_audit.v1")
            self.assertIn("lineage", audit)
            self.assertIn("lineageTree", audit)
            self.assertIn("sourceTrace", audit)
            self.assertIn("backtest", audit)
            self.assertIn("walkForward", audit)
            self.assertIn("evidenceChain", audit)
            self.assertTrue(audit["backtest"]["present"])
            self.assertTrue(audit["walkForward"]["present"])
            self.assertEqual(
                [item["segment"] for item in audit["walkForward"]["segments"]],
                ["train", "validation", "forward"],
            )
            self.assertIn("equityCurve", audit["backtest"])
            self.assertEqual(audit["lineageTree"]["schema"], "quantgod.ga.lineage_tree.v1")
            self.assertGreaterEqual(audit["lineageTree"]["nodeCount"], 1)
            self.assertIsInstance(audit["lineageTree"]["nodes"], list)
            self.assertIsInstance(audit["lineageTree"]["edges"], list)
            self.assertIn("elitePathSeedIds", audit["lineageTree"])
            self.assertIn("fold", audit["lineageTree"])
            self.assertIn("canExpand", audit["lineageTree"]["fold"])
            self.assertTrue(any(node.get("selected") for node in audit["lineageTree"]["nodes"]))
            self.assertIn("lineagePath", audit)
            self.assertEqual(audit["lineagePath"]["schema"], "quantgod.ga.lineage_path.v1")
            self.assertIsInstance(audit["lineagePath"]["nodes"], list)
            self.assertIn("bestFitnessEnd", audit["lineagePath"])
            self.assertIn("fitnessDelta", audit["lineagePath"])
            self.assertIsInstance(audit["evidenceChain"], list)
            self.assertTrue(any(item["step"] == "USDJPY SQLite 回测" for item in audit["evidenceChain"]))
            self.assertTrue(any(item["step"] == "Per-seed Walk-forward" for item in audit["evidenceChain"]))

    def test_case_memory_seeds_cache_and_lineage_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            evidence_dir = runtime_dir / "evidence_os"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "QuantGod_CaseMemorySummary.json").write_text(
                """
                {
                  "schema": "quantgod.case_memory_summary.v1",
                  "cases": [
                    {
                      "caseId": "USDJPY-MISSED-001",
                      "status": "QUEUED_FOR_GA",
                      "proposedAction": {"mutationHint": "relax_rsi_crossback"}
                    },
                    {
                      "caseId": "USDJPY-EARLY-001",
                      "status": "QUEUED_FOR_GA",
                      "proposedAction": {"mutationHint": "let_profit_run"}
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            first = run_generation(runtime_dir, write=True, force=True)
            self.assertTrue(any(row["source"] == "CASE_MEMORY" for row in first["candidates"]))
            self.assertGreater(first["generation"]["caseMemorySeedCount"], 0)
            self.assertEqual(first["generation"]["cache"]["hits"], 0)
            self.assertIn("lineage", first)
            self.assertTrue(any(edge["type"] == "CASE_MEMORY" for edge in first["lineage"]["edges"]))

            second = run_generation(runtime_dir, write=True, force=True)
            self.assertTrue(any(row.get("cacheHit") for row in second["candidates"]), second["candidates"])
            self.assertGreaterEqual(second["generation"]["cache"]["hits"], 1)

    def test_generation_frequency_limiter_can_skip_without_losing_status(self):
        old = os.environ.get("QG_GA_MIN_RUN_INTERVAL_SECONDS")
        os.environ["QG_GA_MIN_RUN_INTERVAL_SECONDS"] = "3600"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runtime_dir = Path(tmp)
                first = run_generation(runtime_dir, write=True, force=True)
                self.assertTrue(first["ok"])
                skipped = run_generation(runtime_dir, write=True, force=False)
                self.assertFalse(skipped["ok"])
                self.assertTrue(skipped["skipped"])
                self.assertFalse(skipped["runLimiter"]["allowed"])
        finally:
            if old is None:
                os.environ.pop("QG_GA_MIN_RUN_INTERVAL_SECONDS", None)
            else:
                os.environ["QG_GA_MIN_RUN_INTERVAL_SECONDS"] = old

    def test_elite_plateau_injects_exploration_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            ga_dir = runtime_dir / "ga"
            ga_dir.mkdir(parents=True)
            (ga_dir / "QuantGod_GAEvolutionPath.json").write_text(
                json.dumps(
                    {
                        "generations": [
                            {"generation": 1, "bestFitness": 5.0, "bestStrategy": "USDJPY_TEST_PLATEAU"},
                            {"generation": 2, "bestFitness": 5.0, "bestStrategy": "USDJPY_TEST_PLATEAU"},
                            {"generation": 3, "bestFitness": 5.0, "bestStrategy": "USDJPY_TEST_PLATEAU"},
                            {"generation": 4, "bestFitness": 5.0, "bestStrategy": "USDJPY_TEST_PLATEAU"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            elite_seed = base_strategy_seed("GA-USDJPY-PLATEAU-ELITE")
            elite_seed["strategyId"] = "USDJPY_TEST_PLATEAU"
            population = build_population(
                5,
                previous_elites=[{"strategyJson": elite_seed}],
                runtime_dir=runtime_dir,
            )

            self.assertTrue(any(row.get("source") == "EXPLORATION_PLATEAU" for row in population))
            self.assertTrue(any(row.get("explorationMode") == "ELITE_PLATEAU_DIVERSIFY" for row in population))

    def test_elite_plateau_mutates_recent_fast_shadow_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            ga_dir = runtime_dir / "ga"
            ga_dir.mkdir(parents=True)
            (ga_dir / "QuantGod_GAEvolutionPath.json").write_text(
                json.dumps(
                    {
                        "generations": [
                            {"generation": 1, "bestFitness": 5.0, "bestStrategy": "USDJPY_TEST_PLATEAU"},
                            {"generation": 2, "bestFitness": 5.0, "bestStrategy": "USDJPY_TEST_PLATEAU"},
                            {"generation": 3, "bestFitness": 5.0, "bestStrategy": "USDJPY_TEST_PLATEAU"},
                            {"generation": 4, "bestFitness": 5.0, "bestStrategy": "USDJPY_TEST_PLATEAU"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            promoted_seed = base_strategy_seed("GA-USDJPY-FAST-SHADOW")
            promoted_seed["strategyId"] = "USDJPY_FAST_SHADOW_PARENT"
            (ga_dir / "QuantGod_GACandidateRuns.jsonl").write_text(
                json.dumps(
                    {
                        "seedId": promoted_seed["seedId"],
                        "strategyId": promoted_seed["strategyId"],
                        "status": "PROMOTED_TO_SHADOW",
                        "promotionStage": "FAST_SHADOW",
                        "fitness": 2.5,
                        "rank": 5,
                        "blockerCode": None,
                        "strategyJson": promoted_seed,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            elite_seed = base_strategy_seed("GA-USDJPY-PLATEAU-ELITE")
            elite_seed["strategyId"] = "USDJPY_TEST_PLATEAU"
            population = build_population(
                5,
                previous_elites=[{"strategyJson": elite_seed}],
                runtime_dir=runtime_dir,
            )

            self.assertTrue(any(row.get("source") == "PLATEAU_SHADOW_MUTATION" for row in population))
            self.assertTrue(any(row.get("parentSeedId") == "GA-USDJPY-FAST-SHADOW" for row in population))

    def test_deep_elite_plateau_reduces_elite_copies_and_expands_diversification(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            ga_dir = runtime_dir / "ga"
            ga_dir.mkdir(parents=True)
            (ga_dir / "QuantGod_GAEvolutionPath.json").write_text(
                json.dumps(
                    {
                        "generations": [
                            {
                                "generation": generation,
                                "bestFitness": 5.0,
                                "bestStrategy": "USDJPY_TEST_DEEP_PLATEAU",
                            }
                            for generation in range(1, 9)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            elites = []
            for index in range(4):
                elite_seed = base_strategy_seed(f"GA-USDJPY-DEEP-PLATEAU-ELITE-{index}")
                elite_seed["strategyId"] = "USDJPY_TEST_DEEP_PLATEAU"
                elites.append({"strategyJson": elite_seed})

            population = build_population(9, previous_elites=elites, runtime_dir=runtime_dir)
            copied_elites = [
                row
                for row in population
                if str(row.get("seedId") or "").startswith("GA-USDJPY-DEEP-PLATEAU-ELITE-")
            ]

            self.assertLess(len(copied_elites), len(elites))
            self.assertTrue(any(row.get("source") == "EXPLORATION_PLATEAU" for row in population))
            self.assertTrue(
                any("深平台期" in str(row.get("explorationReasonZh") or "") for row in population)
            )

    def test_deep_plateau_suppresses_case_memory_and_limits_grid_exploration(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            ga_dir = runtime_dir / "ga"
            ga_dir.mkdir(parents=True)
            (ga_dir / "QuantGod_GAEvolutionPath.json").write_text(
                json.dumps(
                    {
                        "generations": [
                            {
                                "generation": generation,
                                "bestFitness": 5.0,
                                "bestStrategy": "USDJPY_TEST_DEEP_PLATEAU",
                            }
                            for generation in range(1, 9)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            case_dir = runtime_dir / "evidence_os"
            case_dir.mkdir(parents=True)
            (case_dir / "QuantGod_CaseMemorySummary.json").write_text(
                """
                {
                  "schema": "quantgod.case_memory_summary.v1",
                  "cases": [
                    {
                      "caseId": "USDJPY-GA-DEEP-CASE-001",
                      "status": "QUEUED_FOR_GA",
                      "proposedAction": {"mutationHint": "reduce_mutation_rate"}
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            elites = []
            for index in range(4):
                elite_seed = base_strategy_seed(f"GA-USDJPY-DEEP-CASE-ELITE-{index}")
                elite_seed["strategyId"] = "USDJPY_TEST_DEEP_PLATEAU"
                elites.append({"strategyJson": elite_seed})

            population = build_population(9, previous_elites=elites, runtime_dir=runtime_dir)
            source_counts = {}
            for row in population:
                source_counts[row.get("source")] = source_counts.get(row.get("source"), 0) + 1

            self.assertEqual(source_counts.get("CASE_MEMORY", 0), 0)
            self.assertLessEqual(source_counts.get("EXPLORATION_PLATEAU", 0), 1)

    def test_deep_plateau_suppresses_recent_unstable_non_rsi_exploration_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            ga_dir = runtime_dir / "ga"
            ga_dir.mkdir(parents=True)
            (ga_dir / "QuantGod_GAEvolutionPath.json").write_text(
                json.dumps(
                    {
                        "generations": [
                            {
                                "generation": generation,
                                "bestFitness": 5.0,
                                "bestStrategy": "USDJPY_TEST_DEEP_PLATEAU",
                            }
                            for generation in range(1, 9)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rejected_rows = []
            for generation in range(5, 9):
                seed = base_strategy_seed(f"GA-USDJPY-BB-UNSTABLE-{generation}", family="BB_Triple")
                seed["strategyId"] = f"USDJPY_BB_TRIPLE_LONG_UNSTABLE_{generation}"
                rejected_rows.append(
                    {
                        "generation": generation,
                        "seedId": seed["seedId"],
                        "strategyId": seed["strategyId"],
                        "strategyFamily": "BB_Triple",
                        "status": "REJECTED",
                        "blockerCode": "WALK_FORWARD_UNSTABLE",
                        "strategyJson": seed,
                    }
                )
            (ga_dir / "QuantGod_GACandidateRuns.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rejected_rows) + "\n",
                encoding="utf-8",
            )
            elites = []
            for index in range(4):
                elite_seed = base_strategy_seed(f"GA-USDJPY-DEEP-PLATEAU-ELITE-{index}")
                elite_seed["strategyId"] = "USDJPY_TEST_DEEP_PLATEAU"
                elites.append({"strategyJson": elite_seed})

            population = build_population(9, previous_elites=elites, runtime_dir=runtime_dir)
            suppressed_families = {
                row.get("strategyFamily")
                for row in population
                if row.get("explorationSuppressedByRecentBlockers")
            }
            active_families = {
                row.get("strategyFamily")
                for row in population
                if row.get("source") in {"EXPLORATION_PLATEAU", "QUALITY_REPAIR"}
                and not row.get("explorationSuppressedByRecentBlockers")
            }

            self.assertNotIn("BB_Triple", active_families)
            self.assertIn("BB_Triple", suppressed_families)

    def test_deep_plateau_regression_uses_recovery_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            ga_dir = runtime_dir / "ga"
            ga_dir.mkdir(parents=True)
            (ga_dir / "QuantGod_GAEvolutionPath.json").write_text(
                json.dumps(
                    {
                        "generations": [
                            {
                                "generation": generation,
                                "bestFitness": 5.0,
                                "bestStrategy": "USDJPY_TEST_DEEP_PLATEAU",
                                "avgFitness": -8.0,
                                "blockedCount": 8,
                            }
                            for generation in range(1, 8)
                        ]
                        + [
                            {
                                "generation": 8,
                                "bestFitness": 5.0,
                                "bestStrategy": "USDJPY_TEST_DEEP_PLATEAU",
                                "avgFitness": -15.0,
                                "blockedCount": 12,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            promoted_seed = base_strategy_seed("GA-USDJPY-FAST-SHADOW-RECOVERY")
            promoted_seed["strategyId"] = "USDJPY_FAST_SHADOW_RECOVERY_PARENT"
            (ga_dir / "QuantGod_GACandidateRuns.jsonl").write_text(
                json.dumps(
                    {
                        "generation": 8,
                        "seedId": promoted_seed["seedId"],
                        "strategyId": promoted_seed["strategyId"],
                        "status": "PROMOTED_TO_SHADOW",
                        "promotionStage": "FAST_SHADOW",
                        "fitness": 3.0,
                        "rank": 5,
                        "blockerCode": None,
                        "strategyJson": promoted_seed,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            case_dir = runtime_dir / "evidence_os"
            case_dir.mkdir(parents=True)
            (case_dir / "QuantGod_CaseMemorySummary.json").write_text(
                """
                {
                  "schema": "quantgod.case_memory_summary.v1",
                  "cases": [
                    {
                      "caseId": "USDJPY-GA-REGRESSION-001",
                      "status": "QUEUED_FOR_GA",
                      "proposedAction": {"mutationHint": "reduce_mutation_rate"}
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            elites = []
            for index in range(4):
                elite_seed = base_strategy_seed(f"GA-USDJPY-DEEP-PLATEAU-ELITE-{index}")
                elite_seed["strategyId"] = "USDJPY_TEST_DEEP_PLATEAU"
                elites.append({"strategyJson": elite_seed})

            population = build_population(9, previous_elites=elites, runtime_dir=runtime_dir)
            source_counts = {}
            for row in population:
                source_counts[row.get("source")] = source_counts.get(row.get("source"), 0) + 1

            self.assertEqual(source_counts.get("CASE_MEMORY", 0), 0)
            self.assertLessEqual(source_counts.get("EXPLORATION_PLATEAU", 0), 1)
            self.assertGreaterEqual(source_counts.get("PLATEAU_SHADOW_MUTATION", 0), 1)
            self.assertTrue(any("恢复模式" in str(row.get("explorationReasonZh") or "") for row in population))

    def test_deep_plateau_walk_forward_regression_uses_recovery_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            ga_dir = runtime_dir / "ga"
            ga_dir.mkdir(parents=True)
            (ga_dir / "QuantGod_GAEvolutionPath.json").write_text(
                json.dumps(
                    {
                        "generations": [
                            {
                                "generation": generation,
                                "bestFitness": 5.0,
                                "bestStrategy": "USDJPY_TEST_DEEP_PLATEAU",
                                "avgFitness": -20.0 + generation,
                                "blockedCount": 8,
                            }
                            for generation in range(1, 9)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (ga_dir / "QuantGod_GAGenerationLedger.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "generation": 7,
                                "walkForward": {
                                    "avgStabilityScore": 0.76,
                                    "passedCount": 10,
                                    "blockedCount": 4,
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "generation": 8,
                                "walkForward": {
                                    "avgStabilityScore": 0.50,
                                    "passedCount": 6,
                                    "blockedCount": 9,
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            promoted_seed = base_strategy_seed("GA-USDJPY-FAST-SHADOW-WF-RECOVERY")
            promoted_seed["strategyId"] = "USDJPY_FAST_SHADOW_WF_RECOVERY_PARENT"
            (ga_dir / "QuantGod_GACandidateRuns.jsonl").write_text(
                json.dumps(
                    {
                        "generation": 8,
                        "seedId": promoted_seed["seedId"],
                        "strategyId": promoted_seed["strategyId"],
                        "status": "PROMOTED_TO_SHADOW",
                        "promotionStage": "FAST_SHADOW",
                        "fitness": 3.0,
                        "rank": 5,
                        "blockerCode": None,
                        "strategyJson": promoted_seed,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            elites = []
            for index in range(4):
                elite_seed = base_strategy_seed(f"GA-USDJPY-DEEP-WF-PLATEAU-ELITE-{index}")
                elite_seed["strategyId"] = "USDJPY_TEST_DEEP_PLATEAU"
                elites.append({"strategyJson": elite_seed})

            population = build_population(9, previous_elites=elites, runtime_dir=runtime_dir)
            source_counts = {}
            for row in population:
                source_counts[row.get("source")] = source_counts.get(row.get("source"), 0) + 1

            self.assertEqual(source_counts.get("CASE_MEMORY", 0), 0)
            self.assertLessEqual(source_counts.get("EXPLORATION_PLATEAU", 0), 1)
            self.assertGreaterEqual(source_counts.get("PLATEAU_SHADOW_MUTATION", 0), 1)
            self.assertTrue(any("恢复模式" in str(row.get("explorationReasonZh") or "") for row in population))

    def test_population_dedupes_strategy_content_ignoring_lineage_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            elite_seed = base_strategy_seed("GA-USDJPY-DUPE-ELITE-001")
            elite_seed["strategyId"] = "USDJPY_DUPE_ELITE_001"
            duplicate_elite = json.loads(json.dumps(elite_seed))
            duplicate_elite["seedId"] = "GA-USDJPY-DUPE-ELITE-002"
            duplicate_elite["strategyId"] = "USDJPY_DUPE_ELITE_002"
            duplicate_elite["parentSeedId"] = "GA-USDJPY-SOME-PARENT"
            duplicate_elite["source"] = "CROSSOVER"

            population = build_population(
                2,
                previous_elites=[
                    {"strategyJson": elite_seed},
                    {"strategyJson": duplicate_elite},
                ],
                runtime_dir=runtime_dir,
            )
            keys = [_strategy_content_key(row) for row in population]

            self.assertEqual(len(keys), len(set(keys)))
            self.assertEqual(
                sum(str(row.get("seedId") or "").startswith("GA-USDJPY-DUPE-ELITE") for row in population),
                1,
            )

    def test_population_dedupes_strategy_content_after_strategy_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            elite_seed = base_strategy_seed("GA-USDJPY-NORMALIZED-DUPE-001")
            elite_seed["strategyId"] = "USDJPY_NORMALIZED_DUPE_001"
            raw_variant = json.loads(json.dumps(elite_seed))
            raw_variant["seedId"] = "GA-USDJPY-NORMALIZED-DUPE-002"
            raw_variant["strategyId"] = "USDJPY_NORMALIZED_DUPE_002"
            raw_variant["source"] = "CROSSOVER"
            del raw_variant["indicators"]["macd"]

            population = build_population(
                2,
                previous_elites=[
                    {"strategyJson": elite_seed},
                    {"strategyJson": raw_variant},
                ],
                runtime_dir=runtime_dir,
            )
            keys = [_strategy_content_key(row) for row in population]

            self.assertEqual(len(keys), len(set(keys)))
            self.assertEqual(
                sum(str(row.get("seedId") or "").startswith("GA-USDJPY-NORMALIZED-DUPE") for row in population),
                1,
            )

    def test_generation_rejects_only_dangerous_seed_fields_not_safe_field_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_generation(Path(tmp), write=False)
            self.assertNotIn("SAFETY_REJECTED", {row["blockerCode"] for row in result["candidates"]})

    def test_telegram_text_is_chinese_push_only_and_no_execution_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_generation(Path(tmp), write=True)
            text = ga_to_chinese_text(result)
            self.assertIn("GA 进化报告", text)
            self.assertIn("安全边界", text)
            self.assertIn("不直接实盘", text)
            self.assertNotIn("OrderSend", text)


if __name__ == "__main__":
    unittest.main()
