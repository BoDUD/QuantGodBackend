from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.production_evidence_validation.report import build_report, write_reports
from tools.production_evidence_validation.schema import REQUIRED_STRATEGY_FAMILIES


class ProductionEvidenceValidationTests(unittest.TestCase):
    def test_builds_warn_report_without_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_report(Path(tmp))
            self.assertEqual(report["schema"], "quantgod.production_evidence_validation.v1")
            self.assertIn(report["status"], {"WARN", "FAIL"})
            self.assertFalse(report["safety"]["orderSendAllowed"])

    def test_writes_reports_with_sqlite_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "backtest" / "usdjpy.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db))
            conn.execute("CREATE TABLE bars_m1 (time TEXT, close REAL)")
            conn.execute("CREATE TABLE bars_m5 (time TEXT, close REAL)")
            conn.execute("INSERT INTO bars_m1 VALUES ('2026-05-12T00:00:00Z', 155.0)")
            conn.execute("INSERT INTO bars_m5 VALUES ('2026-05-12T00:00:00Z', 155.0)")
            conn.commit()
            conn.close()
            report = build_report(root)
            paths = write_reports(root, report)
            self.assertTrue(Path(paths["latest"]).exists())
            saved = json.loads(Path(paths["latest"]).read_text(encoding="utf-8"))
            self.assertIn("historyProduction", saved)
            self.assertEqual(saved["historyProduction"]["status"], "WARN")
            self.assertIn("M15 历史覆盖不足", saved["historyProduction"]["blockersZh"])

    def test_history_audit_requires_all_core_timeframes_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "backtest" / "usdjpy.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db))
            for table in ("bars_m1", "bars_m5", "bars_m15", "bars_h1"):
                conn.execute(f"CREATE TABLE {table} (time TEXT, close REAL)")
                conn.execute(f"INSERT INTO {table} VALUES ('2026-06-01T00:00:00Z', 155.0)")
            conn.commit()
            conn.close()
            (root / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.usdjpy_history_production_status.v1",
                        "status": "PASS",
                        "historyTargetSatisfied": True,
                        "requiredSpanDays": 316.2,
                        "maxLatestLagHours": 96.0,
                        "timeframes": {
                            timeframe: {
                                "timeframe": timeframe,
                                "barCount": 1000,
                                "earliestBar": "2025-06-01T00:00:00Z",
                                "latestBar": "2026-06-01T00:00:00Z",
                                "spanDays": 365.0,
                                "requiredSpanDays": 316.2,
                                "latestLagHours": 12.0,
                                "maxLatestLagHours": 96.0,
                                "spanOk": True,
                                "densityOk": True,
                                "freshnessOk": True,
                                "passed": True,
                            }
                            for timeframe in ("M1", "M5", "M15", "H1")
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(root)

            history = report["historyProduction"]
            self.assertEqual(history["status"], "PASS")
            self.assertTrue(history["coverageGatePassed"])
            self.assertTrue(history["freshnessGatePassed"])
            self.assertEqual(history["passedTimeframes"], 4)
            self.assertEqual(history["databasePath"], "backtest/usdjpy.sqlite")

    def test_history_audit_blocks_when_production_freshness_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "backtest" / "usdjpy.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db))
            for table in ("bars_m1", "bars_m5", "bars_m15", "bars_h1"):
                conn.execute(f"CREATE TABLE {table} (time TEXT, close REAL)")
                conn.execute(f"INSERT INTO {table} VALUES ('2026-06-01T00:00:00Z', 155.0)")
            conn.commit()
            conn.close()
            (root / "backtest" / "QuantGod_USDJPYHistoryProductionStatus.json").write_text(
                json.dumps(
                    {
                        "schema": "quantgod.usdjpy_history_production_status.v1",
                        "status": "WARN",
                        "historyTargetSatisfied": False,
                        "requiredSpanDays": 316.2,
                        "maxLatestLagHours": 96.0,
                        "timeframes": {
                            timeframe: {
                                "timeframe": timeframe,
                                "barCount": 1000,
                                "earliestBar": "2025-06-01T00:00:00Z",
                                "latestBar": "2026-06-01T00:00:00Z",
                                "spanDays": 365.0,
                                "requiredSpanDays": 316.2,
                                "latestLagHours": 240.0,
                                "maxLatestLagHours": 96.0,
                                "spanOk": True,
                                "densityOk": True,
                                "freshnessOk": False,
                                "passed": False,
                            }
                            for timeframe in ("M1", "M5", "M15", "H1")
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(root)

            history = report["historyProduction"]
            self.assertEqual(history["status"], "WARN")
            self.assertFalse(history["freshnessGatePassed"])
            self.assertIn("M1 最新 K 线延迟超阈值", history["blockersZh"])
            self.assertIn("USDJPY 历史数据覆盖或 freshness 未通过", report["blockersZh"])

    def test_strategy_family_parity_uses_backtest_coverage_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for family in REQUIRED_STRATEGY_FAMILIES:
                for direction in ("LONG", "SHORT"):
                    rows.append(
                        {
                            "strategyFamily": family,
                            "direction": direction,
                            "ok": True,
                            "status": "PASS",
                            "tradeCount": 0,
                            "parityVectorPresent": True,
                        }
                    )

            report_path = root / "backtest" / "QuantGod_StrategyBacktestReport.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "strategyCoverageMatrix": {
                            "schema": "quantgod.strategy_backtest_coverage_matrix.v1",
                            "status": "PASS",
                            "rows": rows,
                            "summary": {
                                "familyCount": len(REQUIRED_STRATEGY_FAMILIES),
                                "routeCount": len(rows),
                                "coveredFamilyCount": len(REQUIRED_STRATEGY_FAMILIES),
                                "okRouteCount": len(rows),
                                "parityVectorRouteCount": len(rows),
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            parity_dir = root / "parity"
            parity_dir.mkdir(parents=True, exist_ok=True)
            (parity_dir / "QuantGod_StrategyParityReport.json").write_text(
                json.dumps(
                    {
                        "families": [
                            {
                                "strategyFamily": "RSI_Reversal",
                                "status": "PARITY_PASS",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(root)
            parity = report["strategyFamilyParity"]
            statuses = {row["strategyFamily"]: row["parityStatus"] for row in parity["matrix"]}
            self.assertEqual(parity["missingCount"], 0)
            self.assertEqual(parity["status"], "PASS")
            self.assertEqual(statuses["RSI_Reversal"], "PASS")
            self.assertIn("SHADOW_RESEARCH_ONLY", set(statuses.values()))


if __name__ == "__main__":
    unittest.main()
