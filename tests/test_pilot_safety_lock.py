import os
import json
import tempfile
import unittest
from pathlib import Path

from tools.pilot_safety_lock.checks import evaluate_pilot_safety_lock
from tools.run_pilot_safety_lock import main as cli_main
from tools.pilot_safety_lock.schema import DEFAULT_CONFIRMATION_PHRASE
from tools.pilot_safety_lock.telegram_text import build_telegram_text


class PilotSafetyLockTests(unittest.TestCase):
    def setUp(self):
        self.old_env = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("QG_PILOT_"):
                os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear(); os.environ.update(self.old_env)

    def test_default_blocks_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = evaluate_pilot_safety_lock(Path(tmp), "USDJPYc", "LONG", Path(tmp))
            self.assertEqual(report["decision"], "BLOCKED")
            self.assertFalse(any(c["passed"] for c in report["checks"] if c["name"] == "人工打开试点开关"))

    def test_sample_still_blocks_without_env_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli_main(["--runtime-dir", tmp, "sample", "--overwrite"])
            report = evaluate_pilot_safety_lock(Path(tmp), "USDJPYc", "LONG", Path(tmp))
            self.assertEqual(report["decision"], "BLOCKED")
            self.assertIn("缺少精确人工确认短语", "；".join(report["reasons"]))

    def test_can_be_armable_only_with_all_manual_and_runtime_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli_main(["--runtime-dir", tmp, "sample", "--overwrite"])
            os.environ["QG_PILOT_EXECUTION_ALLOWED"] = "1"
            os.environ["QG_PILOT_CONFIRMATION_PHRASE"] = DEFAULT_CONFIRMATION_PHRASE
            os.environ["QG_PILOT_MAX_LOT"] = "0.01"
            os.environ["QG_PILOT_MAX_DAILY_TRADES"] = "1"
            os.environ["QG_PILOT_MAX_DAILY_LOSS_R"] = "0.5"
            os.environ["QG_PILOT_ALLOWED_SYMBOLS"] = "USDJPYc"
            os.environ["QG_PILOT_ALLOWED_STRATEGIES"] = "RSI_Reversal"
            report = evaluate_pilot_safety_lock(Path(tmp), "USDJPYc", "LONG", Path(tmp))
            self.assertEqual(report["decision"], "ARMABLE_FOR_MANUAL_PILOT")
            self.assertFalse(report["safety"]["orderSendAllowedByThisTool"])

    def test_blocked_entry_trigger_cannot_arm_pilot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli_main(["--runtime-dir", tmp, "sample", "--overwrite"])
            os.environ["QG_PILOT_EXECUTION_ALLOWED"] = "1"
            os.environ["QG_PILOT_CONFIRMATION_PHRASE"] = DEFAULT_CONFIRMATION_PHRASE
            os.environ["QG_PILOT_ALLOWED_SYMBOLS"] = "USDJPYc"
            os.environ["QG_PILOT_ALLOWED_STRATEGIES"] = "RSI_Reversal"
            trigger = Path(tmp) / "adaptive" / "QuantGod_EntryTriggerPlan.json"
            payload = json.loads(trigger.read_text(encoding="utf-8"))
            payload["decisions"][0]["state"] = "BLOCKED"
            trigger.write_text(json.dumps(payload), encoding="utf-8")
            report = evaluate_pilot_safety_lock(Path(tmp), "USDJPYc", "LONG", Path(tmp))
            self.assertEqual(report["decision"], "BLOCKED")
            self.assertFalse(next(c for c in report["checks"] if c["name"] == "入场触发处于复核态")["passed"])

    def test_stale_runtime_snapshot_blocks_pilot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli_main(["--runtime-dir", tmp, "sample", "--overwrite"])
            os.environ["QG_PILOT_EXECUTION_ALLOWED"] = "1"
            os.environ["QG_PILOT_CONFIRMATION_PHRASE"] = DEFAULT_CONFIRMATION_PHRASE
            os.environ["QG_PILOT_ALLOWED_SYMBOLS"] = "USDJPYc"
            os.environ["QG_PILOT_ALLOWED_STRATEGIES"] = "RSI_Reversal"
            snapshot = Path(tmp) / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json"
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            payload.pop("runtimeFresh", None)
            payload["generatedAt"] = "2026-01-01T00:00:00Z"
            snapshot.write_text(json.dumps(payload), encoding="utf-8")
            report = evaluate_pilot_safety_lock(Path(tmp), "USDJPYc", "LONG", Path(tmp))
            self.assertEqual(report["decision"], "BLOCKED")
            self.assertFalse(next(c for c in report["checks"] if c["name"] == "运行快照新鲜")["passed"])

    def test_chinese_telegram_text_and_no_execution_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = evaluate_pilot_safety_lock(Path(tmp), "USDJPYc", "LONG", Path(tmp))
            text = build_telegram_text(report)
            self.assertIn("安全门禁观察", text)
            self.assertIn("永久 Shadow", text)
            for forbidden in ("实盘试点", "建议仓位", "入场", "止损", "目标"):
                self.assertNotIn(forbidden, text)
            self.assertNotIn("OrderSend", text)


if __name__ == "__main__":
    unittest.main()
