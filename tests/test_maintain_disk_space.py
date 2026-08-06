from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "maintain_disk_space.py"
SPEC = importlib.util.spec_from_file_location("maintain_disk_space", MODULE_PATH)
disk = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = disk
SPEC.loader.exec_module(disk)

DiskUsage = namedtuple("DiskUsage", "total used free")
UTC = timezone.utc  # noqa: UP017 -- production installs still run Python 3.10.
NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


class DiskSpaceMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.backend = self.root / "QuantGodBackend"
        self.runtime = self.backend / "runtime"
        self.dashboard = self.backend / "Dashboard"
        self.mt5 = self.root / "MetaTrader 5"
        self.mt5_files = self.mt5 / "MQL5" / "Files"
        self.private = self.root / ".quantgod"
        self.status_root = self.private / "status"
        self.lock_root = self.private / "locks"
        for path in (
            self.runtime / "ai_analysis" / "history",
            self.runtime / "log_archive",
            self.runtime / "jsonl_archive",
            self.mt5_files / "ai_analysis" / "history",
            self.mt5_files / "log_archive",
            self.mt5_files / "jsonl_archive",
            self.dashboard,
            self.mt5_files,
            self.mt5 / "logs",
            self.mt5 / "MQL5" / "Logs",
            self.status_root,
            self.lock_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _usage(self, free_percent: float = 50.0):
        total = 10_000_000
        free = int(total * free_percent / 100.0)
        return lambda _path: DiskUsage(total, total - free, free)

    def _sequential_usage(self, *free_percentages: float):
        total = 10_000_000
        usages = iter(
            DiskUsage(
                total,
                total - int(total * free_percent / 100.0),
                int(total * free_percent / 100.0),
            )
            for free_percent in free_percentages
        )
        return lambda _path: next(usages)

    def _run(self, **overrides):
        values = {
            "backend_runtime_root": self.runtime,
            "mt5_runtime_root": self.mt5_files,
            "status_root": self.status_root,
            "lock_root": self.lock_root,
            "backend_root": self.backend,
            "mt5_terminal_root": self.mt5,
            "private_root": self.private,
            "history_retention_days": 0,
            "pressure_retention_days": 0,
            "history_keep": 0,
            "pressure_history_keep": 0,
            "stale_temp_hours": 0,
            "now": NOW,
            "disk_usage_fn": self._usage(),
        }
        values.update(overrides)
        return disk.maintain_disk_space(**values)

    def _history(
        self,
        stamp: str,
        size: int = 32,
        age_days: int = 30,
        runtime: Path | None = None,
    ) -> Path:
        path = (runtime or self.runtime) / "ai_analysis" / "history" / f"{stamp}_USDJPYc_v2.json"
        path.write_bytes(b"x" * size)
        old = NOW.timestamp() - age_days * 86400
        os.utime(path, (old, old))
        return path

    def test_default_dry_run_reports_reclaimable_without_deleting(self) -> None:
        candidate = self._history("20260501T010101Z")
        report = self._run()

        self.assertTrue(candidate.exists())
        self.assertEqual(report["mode"], "DRY_RUN")
        self.assertEqual(report["appliedPressureLevel"], "NORMAL")
        self.assertEqual(report["deleted"], [])
        self.assertEqual(len(report["reclaimable"]), 1)
        self.assertFalse(report["safety"]["orderSendAllowed"])
        self.assertFalse(report["safety"]["mt5MutationAllowed"])

    def test_execute_deletes_only_allowlisted_candidates(self) -> None:
        history = self._history("20260501T010101Z")
        archive = self.runtime / "log_archive" / "agent.20260501T010101JST.log.gz"
        archive.write_bytes(b"archive")
        old = NOW.timestamp() - 30 * 86400
        os.utime(archive, (old, old))
        mt5_history = self._history("20260501T010102Z", runtime=self.mt5_files)
        mt5_archive = self.mt5_files / "jsonl_archive" / "agent.20260501T010101JST.jsonl.gz"
        mt5_archive.write_bytes(b"mt5 archive")
        os.utime(mt5_archive, (old, old))
        mt5_log = self.mt5 / "MQL5" / "Logs" / "20260501.log"
        mt5_log.write_bytes(b"log")
        os.utime(mt5_log, (old, old))
        previous = self.dashboard / "vue-dist.previous-abc123"
        previous.mkdir()
        (previous / "index.html").write_text("old", encoding="utf-8")
        os.utime(previous, (old, old))

        report = self._run(execute=True)

        for path in (history, mt5_history):
            self.assertFalse(path.exists())
        self.assertTrue(archive.exists())
        self.assertTrue(mt5_archive.exists())
        self.assertTrue(mt5_log.exists())
        self.assertTrue(previous.exists())
        self.assertEqual(report["summary"]["deletedCount"], 2)
        self.assertEqual(report["status"], "SUCCESS")
        allowed = {Path(path) for path in report["allowedRoots"]}
        self.assertEqual(
            allowed,
            {self.runtime, self.mt5_files, self.status_root, self.lock_root},
        )

    def test_backend_and_mt5_history_keep_counts_are_independent(self) -> None:
        backend_old = self._history("20260501T010101Z", age_days=40)
        backend_new = self._history("20260502T010101Z", age_days=39)
        mt5_old = self._history("20260501T010101Z", age_days=40, runtime=self.mt5_files)
        mt5_new = self._history("20260502T010101Z", age_days=39, runtime=self.mt5_files)

        report = self._run(execute=True, history_keep=1)

        self.assertFalse(backend_old.exists())
        self.assertFalse(mt5_old.exists())
        self.assertTrue(backend_new.exists())
        self.assertTrue(mt5_new.exists())
        self.assertEqual(report["summary"]["deletedCount"], 2)

    def test_keep_newest_and_age_retention_are_both_enforced(self) -> None:
        oldest = self._history("20260501T010101Z", age_days=40)
        middle = self._history("20260502T010101Z", age_days=20)
        newest = self._history("20260503T010101Z", age_days=10)

        report = self._run(
            execute=True,
            history_keep=1,
            history_retention_days=30,
        )

        self.assertFalse(oldest.exists())
        self.assertTrue(middle.exists())
        self.assertTrue(newest.exists())
        reasons = {item["path"]: item["reason"] for item in report["skipped"]}
        self.assertEqual(reasons[str(newest.resolve())], "keep_newest")
        self.assertEqual(reasons[str(middle.resolve())], "retention_not_elapsed")

    def test_byte_budget_caps_a_single_run(self) -> None:
        first = self._history("20260501T010101Z", size=16, age_days=40)
        second = self._history("20260502T010101Z", size=16, age_days=39)

        report = self._run(execute=True, max_delete_bytes_per_run=16)

        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(report["summary"]["deletedBytes"], 16)
        self.assertTrue(any(item["reason"] == "byte_budget_exhausted" for item in report["skipped"]))

    def test_atomic_candidate_replacement_is_rejected_before_unlink(self) -> None:
        candidate = self._history("20260501T010101Z", size=16, age_days=40)
        original_classify = disk._classify_candidates

        def replace_after_scan(*args, **kwargs):
            result = original_classify(*args, **kwargs)
            replacement = candidate.with_name("replacement.tmp")
            replacement.write_bytes(b"y" * 128)
            os.replace(replacement, candidate)
            return result

        with mock.patch.object(disk, "_classify_candidates", side_effect=replace_after_scan):
            report = self._run(execute=True, max_delete_bytes_per_run=16)

        self.assertTrue(candidate.exists())
        self.assertEqual(candidate.stat().st_size, 128)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["summary"]["deletedCount"], 0)
        self.assertEqual(report["summary"]["errorCount"], 1)
        self.assertIn("identity changed", report["errors"][0]["detail"])

    def test_same_size_in_place_rewrite_after_scan_is_rejected(self) -> None:
        candidate = self._history("20260501T010101Z", size=16, age_days=40)
        original_classify = disk._classify_candidates

        def rewrite_after_scan(*args, **kwargs):
            result = original_classify(*args, **kwargs)
            candidate.write_bytes(b"z" * 16)
            return result

        with mock.patch.object(disk, "_classify_candidates", side_effect=rewrite_after_scan):
            report = self._run(execute=True, max_delete_bytes_per_run=16)

        self.assertTrue(candidate.exists())
        self.assertEqual(candidate.read_bytes(), b"z" * 16)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["summary"]["deletedCount"], 0)
        self.assertEqual(report["summary"]["errorCount"], 1)
        self.assertIn("timestamps changed", report["errors"][0]["detail"])

    def test_candidate_unlink_is_relative_to_verified_parent_descriptor(self) -> None:
        candidate = self._history("20260501T010101Z", age_days=40)

        with mock.patch.object(disk.os, "unlink", wraps=os.unlink) as unlink:
            report = self._run(execute=True)

        self.assertEqual(report["summary"]["deletedCount"], 1)
        self.assertTrue(
            any(
                call.args == (candidate.name,) and call.kwargs.get("dir_fd") is not None
                for call in unlink.call_args_list
            )
        )

    def test_symlink_root_and_out_of_bounds_status_are_rejected(self) -> None:
        linked_runtime = self.root / "linked-runtime"
        linked_runtime.symlink_to(self.runtime, target_is_directory=True)
        with self.assertRaisesRegex(disk.MaintenanceError, "symlink"):
            self._run(backend_runtime_root=linked_runtime)

        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(self.backend, target_is_directory=True)
        with self.assertRaisesRegex(disk.MaintenanceError, "symlink component"):
            self._run(backend_runtime_root=linked_parent / "runtime")

        status_subdir = self.status_root / "real-subdir"
        status_subdir.mkdir()
        status_alias = self.status_root / "status-alias"
        status_alias.symlink_to(status_subdir, target_is_directory=True)
        with self.assertRaisesRegex(disk.MaintenanceError, "symlink component"):
            self._run(status_file=status_alias / "status.json")

        outside = self.root / "outside.json"
        with self.assertRaisesRegex(disk.MaintenanceError, "escapes"):
            self._run(status_file=outside)

    def test_allowed_roots_must_be_distinct_and_non_overlapping(self) -> None:
        nested_lock_root = self.status_root / "nested-lock"
        nested_lock_root.mkdir()

        with self.assertRaisesRegex(disk.MaintenanceError, "must not overlap"):
            self._run(lock_root=nested_lock_root)

    def test_symlink_candidate_is_skipped_and_target_is_untouched(self) -> None:
        outside = self.root / "outside-history.json"
        outside.write_bytes(b"keep")
        link = self.runtime / "ai_analysis" / "history" / "20260501T010101Z_USDJPYc_v2.json"
        link.symlink_to(outside)

        report = self._run(execute=True)

        self.assertTrue(link.is_symlink())
        self.assertEqual(outside.read_bytes(), b"keep")
        self.assertTrue(any(item["reason"] == "symlink_rejected" for item in report["skipped"]))

    def test_symlinked_candidate_subdirectory_is_rejected_before_scan(self) -> None:
        outside = self.root / "outside-history"
        outside.mkdir()
        outside_file = outside / "20260501T010101Z_USDJPYc_v2.json"
        outside_file.write_bytes(b"keep")
        history = self.runtime / "ai_analysis" / "history"
        history.rmdir()
        history.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(disk.MaintenanceError, "symlink component"):
            self._run(execute=True)

        self.assertEqual(outside_file.read_bytes(), b"keep")

    def test_hard_linked_candidate_is_skipped(self) -> None:
        outside = self.root / "outside-hardlink.json"
        outside.write_bytes(b"keep")
        candidate = self.runtime / "ai_analysis" / "history" / "20260501T010101Z_USDJPYc_v2.json"
        os.link(outside, candidate)

        report = self._run(execute=True)

        self.assertTrue(candidate.exists())
        self.assertTrue(outside.exists())
        self.assertTrue(
            any(item["reason"] == "unsafe_candidate" and "hard-linked" in item["detail"] for item in report["skipped"])
        )

    def test_hard_linked_existing_status_or_lock_file_is_rejected(self) -> None:
        status = self.status_root / disk.STATUS_FILE_NAME
        status.write_text("{}", encoding="utf-8")
        os.link(status, self.root / "status-hardlink.json")
        with self.assertRaisesRegex(disk.MaintenanceError, "hard-linked"):
            self._run()

        status.unlink()
        lock = self.lock_root / disk.LOCK_FILE_NAME
        lock.write_text("", encoding="utf-8")
        os.link(lock, self.root / "lock-hardlink")
        with self.assertRaisesRegex(disk.MaintenanceError, "hard-linked"):
            self._run()

    def test_only_exact_old_status_temps_with_inactive_pid_are_deleted(self) -> None:
        exact = self.status_root / ".history-sync.tmp-99999999"
        active = self.status_root / f".endpoint-health.tmp-{os.getpid()}"
        recent = self.status_root / ".sqlite-backup.tmp-99999998"
        unknown = self.status_root / ".anything.tmp-99999997"
        atomic_temp = self.status_root / f".{disk.STATUS_FILE_NAME}.tmp-99999996"
        for path in (exact, active, recent, unknown, atomic_temp):
            path.write_text("temporary", encoding="utf-8")
        old = NOW.timestamp() - 48 * 3600
        for path in (exact, active, unknown, atomic_temp):
            os.utime(path, (old, old))

        with mock.patch.object(
            disk,
            "_pid_is_active",
            side_effect=lambda pid: pid == os.getpid(),
        ):
            report = self._run(execute=True, stale_temp_hours=24)

        self.assertFalse(exact.exists())
        self.assertTrue(active.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unknown.exists())
        self.assertTrue(atomic_temp.exists())
        reasons = {item["path"]: item["reason"] for item in report["skipped"]}
        self.assertEqual(reasons[str(active)], "owner_pid_active")
        self.assertEqual(reasons[str(recent.resolve())], "retention_not_elapsed")

    def test_databases_latest_evidence_source_config_and_ex5_are_protected(self) -> None:
        directory = self.runtime / "ai_analysis" / "history"
        protected = [
            directory / "latest.json",
            directory / "state.sqlite",
            directory / "state.sqlite-wal",
            directory / "QuantGod.mq5",
            directory / "QuantGod.ex5",
            directory / "current.json",
        ]
        for path in protected:
            path.write_bytes(b"protected")

        report = self._run(execute=True)

        self.assertTrue(all(path.exists() for path in protected))
        self.assertEqual(report["deleted"], [])
        self.assertFalse(report["safety"]["databaseFilesTouched"])
        self.assertFalse(report["safety"]["sourceConfigOrEx5Touched"])

    def test_pressure_hysteresis_stays_active_until_target_percent(self) -> None:
        status = self.status_root / disk.STATUS_FILE_NAME
        status.write_text(json.dumps({"pressureActive": True}), encoding="utf-8")
        status.chmod(0o600)

        report = self._run(disk_usage_fn=self._usage(11.0))
        self.assertTrue(report["pressureActive"])
        self.assertEqual(report["pressureReason"], "hysteresis_below_recovery_target")
        self.assertEqual(report["status"], "PRESSURE_REMAINS")
        self.assertEqual(report["pressureRemainingBytes"], 100_000)

        status.write_text(json.dumps({"pressureActive": True}), encoding="utf-8")
        recovered = self._run(disk_usage_fn=self._usage(12.0))
        self.assertFalse(recovered["pressureActive"])
        self.assertEqual(recovered["pressureLevel"], "WARNING")
        self.assertEqual(recovered["pressureRemainingBytes"], 0)

    def test_warning_uses_normal_retention_and_keep_policy(self) -> None:
        report = self._run(
            disk_usage_fn=self._usage(15.0),
            history_retention_days=14,
            pressure_retention_days=3,
            history_keep=500,
            pressure_history_keep=100,
        )

        self.assertEqual(report["pressureLevel"], "WARNING")
        self.assertEqual(report["policy"]["retentionDays"], 14)
        self.assertEqual(report["policy"]["historyKeep"], 500)
        self.assertNotIn("archiveKeep", report["policy"])

    def test_pressure_threshold_boundaries_match_health_contract(self) -> None:
        at_critical_boundary = self._run(disk_usage_fn=self._usage(10.0))
        self.assertEqual(at_critical_boundary["pressureLevel"], "WARNING")
        self.assertFalse(at_critical_boundary["pressureActive"])
        self.assertEqual(at_critical_boundary["pressureReason"], "warning_threshold")

        at_warning_boundary = self._run(disk_usage_fn=self._usage(20.0))
        self.assertEqual(at_warning_boundary["pressureLevel"], "NORMAL")
        self.assertFalse(at_warning_boundary["pressureActive"])
        self.assertEqual(at_warning_boundary["pressureReason"], "normal_free_space")

    def test_execute_reports_the_pressure_level_that_selected_policy(self) -> None:
        for recovered_percent in (12.0, 15.0):
            with self.subTest(recovered_percent=recovered_percent):
                report = self._run(
                    execute=True,
                    disk_usage_fn=self._sequential_usage(9.0, recovered_percent),
                    history_retention_days=14,
                    pressure_retention_days=3,
                    history_keep=500,
                    pressure_history_keep=100,
                )

                self.assertEqual(report["appliedPressureLevel"], "CRITICAL")
                self.assertEqual(report["pressureLevel"], "WARNING")
                self.assertFalse(report["pressureActive"])
                self.assertEqual(report["policy"]["retentionDays"], 3)
                self.assertEqual(report["policy"]["historyKeep"], 100)
                self.assertEqual(report["pressureRemainingBytes"], 0)

    def test_inactive_warning_has_no_pressure_remaining_bytes(self) -> None:
        report = self._run(disk_usage_fn=self._usage(11.0))

        self.assertEqual(report["pressureLevel"], "WARNING")
        self.assertFalse(report["pressureActive"])
        self.assertEqual(report["pressureRemainingBytes"], 0)

    def test_defaults_match_infra_contract(self) -> None:
        self.assertEqual(disk.DEFAULT_HISTORY_RETENTION_DAYS, 14)
        self.assertEqual(disk.DEFAULT_PRESSURE_RETENTION_DAYS, 3)
        self.assertEqual(disk.DEFAULT_HISTORY_KEEP, 500)
        self.assertEqual(disk.DEFAULT_PRESSURE_HISTORY_KEEP, 100)

    def test_status_report_is_atomic_private_and_has_no_temp_residue(self) -> None:
        with mock.patch.object(disk.os, "replace", wraps=os.replace) as replace:
            report = self._run()
        status = self.status_root / disk.STATUS_FILE_NAME

        replace.assert_called_once()
        self.assertEqual(stat.S_IMODE(status.stat().st_mode), 0o600)
        self.assertEqual(json.loads(status.read_text(encoding="utf-8"))["schema"], disk.SCHEMA)
        self.assertEqual(report["schema"], disk.SCHEMA)
        self.assertEqual(list(self.status_root.glob(f".{status.name}.*")), [])

    def test_nonblocking_lock_rejects_concurrent_run(self) -> None:
        lock = self.lock_root / disk.LOCK_FILE_NAME
        with lock.open("w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(disk.MaintenanceError, "already running"):
                self._run()

    def test_cli_returns_zero_when_successful_report_remains_critical(self) -> None:
        fake = {
            "schema": disk.SCHEMA,
            "status": "PRESSURE_REMAINS",
            "mode": "EXECUTE",
            "pressureLevel": "CRITICAL",
            "pressureActive": True,
            "errors": [],
            "summary": {
                "candidateCount": 0,
                "reclaimableCount": 0,
                "reclaimableBytes": 0,
                "deletedCount": 0,
                "deletedBytes": 0,
                "errorCount": 0,
            },
        }
        argv = [
            "--backend-runtime-root",
            str(self.runtime),
            "--mt5-runtime-root",
            str(self.mt5_files),
            "--status-root",
            str(self.status_root),
            "--lock-root",
            str(self.lock_root),
            "--execute",
        ]
        with mock.patch.object(disk, "maintain_disk_space", return_value=fake):
            self.assertEqual(disk.main(argv), 0)


if __name__ == "__main__":
    unittest.main()
