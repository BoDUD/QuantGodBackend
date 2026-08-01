from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.run_local_shadow_backup import create_backup, verify_backup


class LocalShadowBackupTests(unittest.TestCase):
    def test_online_backup_is_atomic_private_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            backup_root = root / "backups"
            database = runtime / "backtest" / "usdjpy.sqlite"
            database.parent.mkdir(parents=True)
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE bars(timestamp TEXT PRIMARY KEY, close REAL)")
                connection.execute("INSERT INTO bars VALUES('2026-08-01T00:00:00Z', 157.0)")
                connection.commit()
                connection.execute("PRAGMA journal_mode=WAL")
            finally:
                connection.close()
            (runtime / "QuantGod_Dashboard.json").write_text(
                json.dumps({"runtime": {"shadowMode": True, "readOnlyMode": True}}),
                encoding="utf-8",
            )

            manifest = create_backup(runtime, backup_root)
            backup_dir = Path(manifest["backupPath"])

            self.assertEqual(manifest["mode"], "SHADOW_READONLY")
            self.assertFalse(manifest["safety"]["orderSendAllowed"])
            self.assertFalse(manifest["safety"]["credentialFilesIncluded"])
            self.assertTrue((backup_dir / "manifest.json").exists())
            self.assertEqual(list(backup_root.glob(".partial-*")), [])

            verification = verify_backup(backup_dir)
            self.assertTrue(verification["ok"], verification)
            sqlite_check = next(row for row in verification["checks"] if row["relativePath"].endswith("usdjpy.sqlite"))
            self.assertEqual(sqlite_check["quickCheck"], "ok")

            backup_connection = sqlite3.connect(backup_dir / "backtest" / "usdjpy.sqlite")
            try:
                self.assertEqual(backup_connection.execute("SELECT COUNT(*) FROM bars").fetchone()[0], 1)
            finally:
                backup_connection.close()


if __name__ == "__main__":
    unittest.main()
