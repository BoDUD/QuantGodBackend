from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_strategy_contract_adapter
import run_strategy_ga
import run_usdjpy_autonomous_agent
import run_usdjpy_bar_replay
import run_usdjpy_evidence_os
import run_usdjpy_live_loop
import run_usdjpy_runtime_dataset
import run_usdjpy_strategy_backtest
import run_usdjpy_strategy_lab
import run_usdjpy_walk_forward


CONFIRMED = {
    "ok": True,
    "delivery": {"ok": True, "messageId": 73},
}
UNCONFIRMED = {
    "ok": True,
    "delivery": {"ok": False, "skipped": True, "reason": "push_disabled"},
}


class LegacyTelegramCliTruthTests(unittest.TestCase):
    def _cases(self, runtime_dir: str):
        base = ["--runtime-dir", runtime_dir, "telegram-text"]
        return (
            (run_strategy_contract_adapter, base, {"read_strategy_contract_status": {}, "contract_to_chinese_text": "preview"}, "send_telegram"),
            (run_strategy_ga, base, {"build_ga_status": {}, "ga_to_chinese_text": "preview"}, "send_telegram"),
            (run_usdjpy_autonomous_agent, base, {"build_agent_state": {}, "autonomous_agent_to_chinese_text": "preview"}, "send_telegram"),
            (run_usdjpy_bar_replay, base, {"build_bar_replay_report": {}, "bar_replay_to_chinese_text": "preview"}, "send_telegram"),
            (run_usdjpy_live_loop, base, {"build_live_loop": {}, "live_loop_to_chinese_text": "preview"}, "send_telegram"),
            (run_usdjpy_runtime_dataset, base, {"build_all": {}, "evolution_to_chinese_text": "preview"}, "send_telegram"),
            (run_usdjpy_strategy_backtest, base, {"status": {"latestReport": {}}, "backtest_to_chinese_text": "preview"}, "send_telegram"),
            (run_usdjpy_strategy_lab, base, {"build_usdjpy_policy": {}, "policy_to_chinese_text": "preview"}, "send_telegram"),
            (run_usdjpy_walk_forward, base, {"build_walk_forward_report": {}, "walk_forward_to_chinese_text": "preview"}, "send_telegram"),
            (run_usdjpy_evidence_os, base, {"status": {}, "evidence_os_to_chinese_text": "preview"}, "dispatch_event"),
        )

    def _run_case(self, module, argv, replacements, sender_name, delivery, *, send: bool):
        output = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(module, "load_env", return_value=None))
            for name, result in replacements.items():
                stack.enter_context(mock.patch.object(module, name, return_value=result))
            sender = stack.enter_context(mock.patch.object(module, sender_name, return_value=delivery))
            stack.enter_context(redirect_stdout(output))
            code = module.main([*argv, *(('--send',) if send else ())])
        return code, json.loads(output.getvalue()), sender

    def test_all_legacy_wrappers_fail_closed_without_message_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for module, argv, replacements, sender_name in self._cases(temp_dir):
                with self.subTest(module=module.__name__):
                    code, payload, sender = self._run_case(
                        module, argv, replacements, sender_name, UNCONFIRMED, send=True
                    )
                    self.assertEqual(code, 2)
                    self.assertTrue(payload["sendRequested"])
                    self.assertFalse(payload["sent"])
                    self.assertFalse(payload["deliveryOk"])
                    self.assertFalse(payload["ok"])
                    self.assertEqual(payload["error"], "TELEGRAM_DELIVERY_NOT_CONFIRMED")
                    sender.assert_called_once()

    def test_all_legacy_previews_succeed_without_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for module, argv, replacements, sender_name in self._cases(temp_dir):
                with self.subTest(module=module.__name__):
                    code, payload, sender = self._run_case(
                        module, argv, replacements, sender_name, UNCONFIRMED, send=False
                    )
                    self.assertEqual(code, 0)
                    self.assertFalse(payload["sendRequested"])
                    self.assertFalse(payload["sent"])
                    self.assertFalse(payload["deliveryOk"])
                    self.assertTrue(payload["ok"])
                    sender.assert_not_called()

    def test_confirmed_receipt_is_the_only_successful_send(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            module, argv, replacements, sender_name = self._cases(temp_dir)[0]
            code, payload, _sender = self._run_case(
                module, argv, replacements, sender_name, CONFIRMED, send=True
            )
        self.assertEqual(code, 0)
        self.assertTrue(payload["sendRequested"])
        self.assertTrue(payload["sent"])
        self.assertTrue(payload["deliveryOk"])
        self.assertTrue(payload["ok"])

    def test_send_loop_stops_before_sleep_when_delivery_is_unconfirmed(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            run_usdjpy_live_loop, "load_env", return_value=None
        ), mock.patch.object(
            run_usdjpy_live_loop, "build_live_loop", return_value={}
        ), mock.patch.object(
            run_usdjpy_live_loop, "live_loop_to_chinese_text", return_value="preview"
        ), mock.patch.object(
            run_usdjpy_live_loop, "send_telegram", return_value=UNCONFIRMED
        ), mock.patch.object(
            run_usdjpy_live_loop.time, "sleep"
        ) as sleep, redirect_stdout(output):
            code = run_usdjpy_live_loop.main(
                ["--runtime-dir", temp_dir, "loop", "--interval-seconds", "30", "--send"]
            )
        self.assertEqual(code, 2)
        sleep.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["deliveryOk"])


if __name__ == "__main__":
    unittest.main()
