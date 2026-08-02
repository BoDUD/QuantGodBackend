from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_adaptive_policy
import run_auto_execution_policy
import run_automation_chain
import run_daily_autopilot_v2
import run_entry_trigger_lab
import run_notify
import run_pilot_safety_lock
from telegram_cli_truth import explicit_send_exit_code, normalize_delivery


CONFIRMED = {
    "ok": True,
    "sent": True,
    "deliveryOk": True,
    "delivery": {"ok": True, "messageId": 42},
}
UNCONFIRMED = {
    "ok": True,
    "sent": False,
    "deliveryOk": False,
    "delivery": {"ok": False, "skipped": True, "reason": "push_disabled"},
}


class TelegramCliExitTruthTests(unittest.TestCase):
    def test_truth_helper_requires_confirmed_message_receipt(self) -> None:
        self.assertEqual(explicit_send_exit_code(True, CONFIRMED), 0)
        self.assertEqual(explicit_send_exit_code(True, {"ok": True, "sent": True, "deliveryOk": True}), 2)
        self.assertEqual(explicit_send_exit_code(True, UNCONFIRMED), 2)
        self.assertEqual(explicit_send_exit_code(False, UNCONFIRMED), 0)
        preview = normalize_delivery({"ok": True}, send_requested=False)
        self.assertFalse(preview["sendRequested"])
        self.assertFalse(preview["sent"])
        self.assertFalse(preview["deliveryOk"])

    def test_policy_wrappers_return_two_on_unconfirmed_explicit_send(self) -> None:
        cases = (CONFIRMED, UNCONFIRMED)
        for gateway_result in cases:
            expected = 0 if gateway_result is CONFIRMED else 2
            with self.subTest(wrapper="adaptive", expected=expected), mock.patch.object(
                run_adaptive_policy, "build_adaptive_policy", return_value={}
            ), mock.patch.object(
                run_adaptive_policy, "build_policy_telegram_text", return_value="preview"
            ), mock.patch.object(
                run_adaptive_policy, "dispatch_cli_text", return_value=gateway_result
            ), redirect_stdout(io.StringIO()):
                code = run_adaptive_policy.cmd_telegram_text(
                    SimpleNamespace(runtime_dir="runtime", symbols=None, no_write=True, symbol=None, send=True)
                )
                self.assertEqual(code, expected)

            engine = mock.Mock()
            engine.build.return_value = {"policies": [], "summary": {}}
            with self.subTest(wrapper="auto_policy", expected=expected), mock.patch.object(
                run_auto_execution_policy, "AutoExecutionPolicyEngine", return_value=engine
            ), mock.patch.object(
                run_auto_execution_policy, "build_telegram_text", return_value="preview"
            ), mock.patch.object(
                run_auto_execution_policy, "dispatch_cli_text", return_value=gateway_result
            ), redirect_stdout(io.StringIO()):
                code = run_auto_execution_policy.cmd_telegram_text(
                    SimpleNamespace(
                        runtime_dir="runtime",
                        max_age_seconds=180,
                        symbols="USDJPYc",
                        directions="LONG,SHORT",
                        write=False,
                        symbol="",
                        send=True,
                    )
                )
                self.assertEqual(code, expected)

    def test_chain_entry_and_pilot_wrappers_propagate_delivery_failure(self) -> None:
        for gateway_result, expected in ((CONFIRMED, 0), (UNCONFIRMED, 2)):
            runner = mock.Mock()
            runner.build_status.return_value = {}
            with self.subTest(wrapper="automation_text", expected=expected), mock.patch.object(
                run_automation_chain, "build_runner", return_value=runner
            ), mock.patch.object(
                run_automation_chain, "build_automation_telegram_text", return_value="preview"
            ), mock.patch.object(
                run_automation_chain, "dispatch_cli_text", return_value=gateway_result
            ), redirect_stdout(io.StringIO()):
                code = run_automation_chain.cmd_telegram_text(
                    SimpleNamespace(refresh=False, no_write=True, send=True, runtime_dir="runtime")
                )
                self.assertEqual(code, expected)

            with tempfile.TemporaryDirectory() as temp_dir, self.subTest(wrapper="entry", expected=expected), mock.patch.object(
                run_entry_trigger_lab, "_load_plan", return_value={}
            ), mock.patch.object(
                run_entry_trigger_lab, "build_telegram_text", return_value="preview"
            ), mock.patch.object(
                run_entry_trigger_lab, "dispatch_cli_text", return_value=gateway_result
            ), redirect_stdout(io.StringIO()):
                code = run_entry_trigger_lab.cmd_telegram_text(
                    SimpleNamespace(runtime_dir=temp_dir, symbol=None, send=True)
                )
                self.assertEqual(code, expected)

            with self.subTest(wrapper="pilot", expected=expected), mock.patch.object(
                run_pilot_safety_lock, "read_report", return_value={"decision": "BLOCKED"}
            ), mock.patch.object(
                run_pilot_safety_lock, "build_telegram_text", return_value="preview"
            ), mock.patch.object(
                run_pilot_safety_lock, "dispatch_cli_text", return_value=gateway_result
            ), redirect_stdout(io.StringIO()):
                code = run_pilot_safety_lock.cmd_telegram_text(
                    SimpleNamespace(
                        runtime_dir="runtime",
                        refresh=False,
                        write=False,
                        symbol="USDJPYc",
                        direction="LONG",
                        send=True,
                    )
                )
                self.assertEqual(code, expected)

    def test_daily_and_notify_main_return_two_without_receipt(self) -> None:
        for gateway_result, expected in ((CONFIRMED, 0), (UNCONFIRMED, 2)):
            raw_gateway = gateway_result
            with self.subTest(wrapper="daily", expected=expected), tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
                run_daily_autopilot_v2, "build_daily_autopilot_v2", return_value={}
            ), mock.patch.object(
                run_daily_autopilot_v2, "daily_autopilot_v2_to_chinese_text", return_value="preview"
            ), mock.patch.object(
                run_daily_autopilot_v2, "send_telegram", return_value=raw_gateway
            ), redirect_stdout(io.StringIO()):
                code = run_daily_autopilot_v2.main(
                    ["--runtime-dir", temp_dir, "telegram-text", "--send"]
                )
                self.assertEqual(code, expected)

            notify_result = {
                "ok": expected == 0,
                "sent": expected == 0,
                "deliveryOk": expected == 0,
                "gateway": gateway_result,
            }
            with self.subTest(wrapper="notify", expected=expected), mock.patch.object(
                run_notify.NotifyConfig, "from_env", return_value=mock.Mock()
            ), mock.patch.object(
                run_notify, "send_event", new=mock.Mock(return_value=object())
            ), mock.patch.object(
                run_notify, "run_async", return_value=notify_result
            ), redirect_stdout(io.StringIO()):
                code = run_notify.main(["test", "--send"])
                self.assertEqual(code, expected)

    def test_automation_once_requires_receipt_in_child_stdout(self) -> None:
        for child_delivery, expected in ((CONFIRMED, 0), (UNCONFIRMED, 2)):
            runner = mock.Mock()
            runner.run_once.return_value = {
                "runStatus": "COMPLETED",
                "steps": [
                    {
                        "name": "usdjpy_live_loop_telegram",
                        "stdoutPreview": json.dumps(child_delivery),
                    }
                ],
            }
            with self.subTest(expected=expected), mock.patch.object(
                run_automation_chain, "build_runner", return_value=runner
            ), redirect_stdout(io.StringIO()):
                code = run_automation_chain.cmd_once(SimpleNamespace(send=True, no_write=True))
                self.assertEqual(code, expected)

    def test_automation_send_loop_stops_with_two_on_first_unconfirmed_cycle(self) -> None:
        runner = mock.Mock()
        runner.run_once.return_value = {
            "runStatus": "COMPLETED",
            "steps": [
                {
                    "name": "usdjpy_live_loop_telegram",
                    "stdoutPreview": json.dumps(UNCONFIRMED),
                }
            ],
        }
        with mock.patch.object(
            run_automation_chain, "build_runner", return_value=runner
        ), mock.patch.object(
            run_automation_chain.time, "sleep"
        ) as sleep, redirect_stdout(io.StringIO()):
            code = run_automation_chain.cmd_loop(SimpleNamespace(send=True, interval_seconds=300))
        self.assertEqual(code, 2)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
