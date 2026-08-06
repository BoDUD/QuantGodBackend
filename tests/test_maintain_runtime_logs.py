import gzip
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "maintain_runtime_logs.py"
SPEC = importlib.util.spec_from_file_location("maintain_runtime_logs", MODULE_PATH)
runtime_logs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = runtime_logs
SPEC.loader.exec_module(runtime_logs)


class RuntimeLogMaintenanceTests(unittest.TestCase):
    def test_collision_fallback_archives_are_numbered_and_recognized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp).resolve() / "archive"
            archive_dir.mkdir()
            stamp = "20260802T021500JST"

            first_log = archive_dir / f"agent_v25_screen.{stamp}.log.gz"
            first_log.touch()
            numbered_log = runtime_logs._unique_archive_path(archive_dir, "agent_v25_screen", stamp)
            self.assertEqual(numbered_log.name, f"agent_v25_screen.{stamp}.1.log.gz")
            self.assertTrue(runtime_logs._is_archived_log(numbered_log))

            first_jsonl = archive_dir / f"execution__feedback.{stamp}.jsonl.gz"
            first_jsonl.touch()
            numbered_jsonl = runtime_logs._unique_jsonl_archive_path(
                archive_dir,
                "execution__feedback",
                stamp,
            )
            self.assertEqual(numbered_jsonl.name, f"execution__feedback.{stamp}.1.jsonl.gz")
            self.assertTrue(runtime_logs._is_archived_jsonl(numbered_jsonl))

    def test_rotates_large_active_log_and_truncates_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp).resolve() / "runtime"
            runtime_root.mkdir(parents=True)
            active_log = runtime_root / "agent_v25_screen.log"
            active_log.write_text("line\n" * 64, encoding="utf-8")

            status = runtime_logs.maintain_logs(
                runtime_root,
                max_active_bytes=32,
                retention_days=7,
            )

            self.assertEqual(active_log.stat().st_size, 0)
            self.assertEqual(len(status["rotated"]), 1)
            archive_path = Path(status["rotated"][0]["archive"])
            self.assertTrue(archive_path.exists())
            with gzip.open(archive_path, "rt", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "line\n" * 64)

    def test_compresses_legacy_archives_and_prunes_expired_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp).resolve() / "runtime"
            archive_dir = runtime_root / "log_archive"
            runtime_root.mkdir(parents=True)
            legacy = runtime_root / "agent_v25_screen.20260512T1459JST.log"
            legacy.write_text("legacy\n" * 8, encoding="utf-8")
            old_archive = archive_dir / "agent_v25_screen.20260510T1459JST.1.log.gz"
            archive_dir.mkdir(parents=True)
            with gzip.open(old_archive, "wt", encoding="utf-8") as handle:
                handle.write("expired\n")

            old_time = (datetime.now().timestamp() - timedelta(days=5).total_seconds(),) * 2
            os.utime(old_archive, old_time)

            status = runtime_logs.maintain_logs(
                runtime_root,
                archive_dir=archive_dir,
                max_active_bytes=1024 * 1024,
                retention_days=2,
            )

            self.assertFalse(legacy.exists())
            self.assertTrue(any(item["action"] == "compressed_legacy_archive" for item in status["compressedLegacy"]))
            self.assertFalse(old_archive.exists())
            self.assertTrue(any(item["reason"] == "expired_archive" for item in status["deleted"]))

    def test_prunes_log_archives_over_size_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp).resolve() / "runtime"
            archive_dir = runtime_root / "log_archive"
            archive_dir.mkdir(parents=True)
            old_archive = archive_dir / "agent_v25_screen.20260510T1459JST.log.gz"
            new_archive = archive_dir / "agent_v25_screen.20260511T1459JST.log.gz"
            for archive in (old_archive, new_archive):
                with gzip.open(archive, "wt", encoding="utf-8") as handle:
                    handle.write("x" * 128)
            now = time.time()
            os.utime(old_archive, (now - 2, now - 2))
            os.utime(new_archive, (now - 1, now - 1))

            status = runtime_logs.maintain_logs(
                runtime_root,
                archive_dir=archive_dir,
                max_active_bytes=1024 * 1024,
                archive_max_bytes=1,
                retention_days=30,
                maintain_jsonl=False,
            )

            self.assertTrue(any(item["reason"] == "archive_size_cap" for item in status["deleted"]))
            self.assertFalse(old_archive.exists())

    def test_compacts_large_jsonl_and_archives_full_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp).resolve() / "runtime"
            ledger = runtime_root / "execution" / "QuantGod_LiveExecutionFeedback.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("".join(f'{{"i":{i},"text":"{"x" * 20}"}}\n' for i in range(10)), encoding="utf-8")

            status = runtime_logs.maintain_logs(
                runtime_root,
                max_active_bytes=1024 * 1024,
                jsonl_max_active_bytes=90,
                jsonl_keep_lines=3,
                jsonl_min_age_seconds=0,
                maintain_jsonl=True,
            )

            self.assertEqual(len(status["jsonl"]["compacted"]), 1)
            self.assertLessEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 3)
            archive_path = Path(status["jsonl"]["compacted"][0]["archive"])
            self.assertTrue(archive_path.exists())
            with gzip.open(archive_path, "rt", encoding="utf-8") as handle:
                self.assertIn('"i":0', handle.read())

    def test_jsonl_tail_respects_byte_cap_when_keep_lines_are_large(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp).resolve() / "runtime"
            ledger = runtime_root / "notifications" / "QuantGod_TelegramGatewayLedger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                "".join(f'{{"i":{i},"text":"{"x" * 20}"}}\n' for i in range(20)),
                encoding="utf-8",
            )

            status = runtime_logs.maintain_logs(
                runtime_root,
                max_active_bytes=1024 * 1024,
                jsonl_max_active_bytes=160,
                jsonl_keep_lines=20,
                jsonl_min_age_seconds=0,
                maintain_jsonl=True,
            )

            self.assertEqual(len(status["jsonl"]["compacted"]), 1)
            retained = ledger.read_bytes()
            self.assertLessEqual(len(retained), 160)
            retained_text = retained.decode("utf-8")
            self.assertIn('"i":19', retained_text)
            self.assertNotIn('"i":0', retained_text)

    def test_prunes_jsonl_archives_over_size_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp).resolve() / "runtime"
            archive_dir = runtime_root / "jsonl_archive"
            archive_dir.mkdir(parents=True)
            old_archive = archive_dir / "execution__QuantGod_LiveExecutionFeedback.20260510T1459JST.1.jsonl.gz"
            new_archive = archive_dir / "evidence_os__QuantGod_LiveExecutionFeedback.20260511T1459JST.jsonl.gz"
            for archive in (old_archive, new_archive):
                with gzip.open(archive, "wt", encoding="utf-8") as handle:
                    handle.write("x" * 256)
            now = time.time()
            os.utime(old_archive, (now - 2, now - 2))
            os.utime(new_archive, (now - 1, now - 1))

            status = runtime_logs.maintain_logs(
                runtime_root,
                max_active_bytes=1024 * 1024,
                retention_days=30,
                jsonl_archive_dir=archive_dir,
                jsonl_archive_max_bytes=1,
                maintain_jsonl=True,
            )

            self.assertTrue(any(item["reason"] == "jsonl_archive_size_cap" for item in status["jsonl"]["deleted"]))
            self.assertFalse(old_archive.exists())

    def test_rejects_symlinked_active_log_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            outside = root / "outside.log"
            outside.write_text("outside evidence\n", encoding="utf-8")
            (runtime_root / "agent_v25_screen.log").symlink_to(outside)

            with self.assertRaises(runtime_logs.MaintenanceError):
                runtime_logs.maintain_logs(
                    runtime_root,
                    max_active_bytes=1,
                    maintain_jsonl=False,
                )

            self.assertEqual(outside.read_text(encoding="utf-8"), "outside evidence\n")

    def test_rejects_hardlinked_active_log_without_truncating_peer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            outside = root / "outside.log"
            original = b"outside evidence\n" * 32
            outside.write_bytes(original)
            os.link(outside, runtime_root / "agent_v25_screen.log")

            with self.assertRaises(runtime_logs.MaintenanceError):
                runtime_logs.maintain_logs(
                    runtime_root,
                    max_active_bytes=1,
                    maintain_jsonl=False,
                )

            self.assertEqual(outside.read_bytes(), original)

    def test_rejects_symlinked_jsonl_without_rewriting_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            runtime_root = root / "runtime"
            ledger_dir = runtime_root / "execution"
            ledger_dir.mkdir(parents=True)
            outside = root / "outside.jsonl"
            original = b'{"outside":true}\n' * 32
            outside.write_bytes(original)
            (ledger_dir / "QuantGod_LiveExecutionFeedback.jsonl").symlink_to(outside)

            with self.assertRaises(runtime_logs.MaintenanceError):
                runtime_logs.maintain_logs(
                    runtime_root,
                    max_active_bytes=1024 * 1024,
                    jsonl_max_active_bytes=1,
                    maintain_jsonl=True,
                )

            self.assertEqual(outside.read_bytes(), original)

    def test_rejects_hardlinked_jsonl_without_rewriting_peer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            runtime_root = root / "runtime"
            ledger_dir = runtime_root / "execution"
            ledger_dir.mkdir(parents=True)
            outside = root / "outside.jsonl"
            original = b'{"outside":true}\n' * 32
            outside.write_bytes(original)
            os.link(outside, ledger_dir / "QuantGod_LiveExecutionFeedback.jsonl")

            with self.assertRaises(runtime_logs.MaintenanceError):
                runtime_logs.maintain_logs(
                    runtime_root,
                    max_active_bytes=1024 * 1024,
                    jsonl_max_active_bytes=1,
                    maintain_jsonl=True,
                )

            self.assertEqual(outside.read_bytes(), original)

    def test_rejects_hardlinked_archive_before_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            runtime_root = root / "runtime"
            archive_dir = runtime_root / "log_archive"
            archive_dir.mkdir(parents=True)
            outside = root / "outside.log.gz"
            outside.write_bytes(b"archive evidence")
            os.link(outside, archive_dir / "agent_v25_screen.20260510T1459JST.log.gz")

            with self.assertRaises(runtime_logs.MaintenanceError):
                runtime_logs.maintain_logs(
                    runtime_root,
                    archive_dir=archive_dir,
                    archive_max_bytes=1,
                    retention_days=30,
                    maintain_jsonl=False,
                )

            self.assertEqual(outside.read_bytes(), b"archive evidence")

    def test_rejects_symlinked_archive_before_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            runtime_root = root / "runtime"
            archive_dir = runtime_root / "log_archive"
            archive_dir.mkdir(parents=True)
            outside = root / "outside.log.gz"
            outside.write_bytes(b"archive evidence")
            (archive_dir / "agent_v25_screen.20260510T1459JST.log.gz").symlink_to(outside)

            with self.assertRaises(runtime_logs.MaintenanceError):
                runtime_logs.maintain_logs(
                    runtime_root,
                    archive_dir=archive_dir,
                    archive_max_bytes=1,
                    retention_days=30,
                    maintain_jsonl=False,
                )

            self.assertEqual(outside.read_bytes(), b"archive evidence")

    def test_rejects_symlink_component_in_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real_runtime = root / "real-runtime"
            real_runtime.mkdir()
            linked_runtime = root / "runtime-link"
            linked_runtime.symlink_to(real_runtime, target_is_directory=True)

            with self.assertRaises(runtime_logs.MaintenanceError):
                runtime_logs.maintain_logs(linked_runtime, maintain_jsonl=False)

    def test_safe_unlink_refuses_path_swap_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp).resolve() / "runtime"
            runtime_root.mkdir()
            candidate = runtime_root / "agent_v25_screen.20260510T1459JST.log.gz"
            candidate.write_bytes(b"original archive")
            snapshot = runtime_logs._snapshot_managed_file(
                candidate,
                root=runtime_root,
                label="test archive",
            )
            moved_original = runtime_root / "moved-original.log.gz"
            candidate.rename(moved_original)
            candidate.write_bytes(b"replacement archive")

            with self.assertRaises(runtime_logs.ManagedFileChangedError):
                runtime_logs._safe_unlink(snapshot)

            self.assertEqual(candidate.read_bytes(), b"replacement archive")
            self.assertEqual(moved_original.read_bytes(), b"original archive")

    def test_rejects_file_when_current_uid_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp).resolve() / "runtime"
            runtime_root.mkdir()
            active_log = runtime_root / "agent_v25_screen.log"
            active_log.write_text("log\n", encoding="utf-8")
            mismatched_uid = (os.getuid() if hasattr(os, "getuid") else 0) + 1

            with (
                mock.patch.object(runtime_logs, "_current_uid", return_value=mismatched_uid),
                self.assertRaises(runtime_logs.MaintenanceError),
            ):
                runtime_logs.maintain_logs(runtime_root, maintain_jsonl=False)


if __name__ == "__main__":
    unittest.main()
