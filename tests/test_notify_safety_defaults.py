from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tools.notify.config import FORBIDDEN_NOTIFY_TRUTHY_ENV, NotifyConfig
from tools.notify.notify_service import send_event
from tools.notify.telegram_bot import (
    TELEGRAM_MAX_CHARS,
    TELEGRAM_SAFETY_FOOTER,
    TelegramBot,
    TelegramSendResult,
    prepare_telegram_message,
)


class NotifySafetyDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.tmp.name)
        self.old_env = os.environ.copy()
        os.environ["QG_RUNTIME_DIR"] = str(self.runtime)
        os.environ["QG_NOTIFY_HISTORY_PATH"] = str(self.runtime / "QuantGod_NotifyHistory.json")
        os.environ["QG_TELEGRAM_ENV_FILE"] = str(self.runtime / ".env.telegram.local")
        os.environ["QG_NOTIFY_ENABLED"] = "1"
        for key in (
            *FORBIDDEN_NOTIFY_TRUTHY_ENV,
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "QG_TELEGRAM_BOT_TOKEN",
            "QG_TELEGRAM_CHAT_ID",
            "QG_TELEGRAM_PUSH_ALLOWED",
        ):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    def run_cli(self, argv: list[str]) -> dict:
        repo_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(repo_root / "tools" / "run_notify.py"), *argv],
            cwd=repo_root,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_credentials_do_not_enable_push_by_default(self) -> None:
        (self.runtime / ".env.telegram.local").write_text(
            "QG_TELEGRAM_BOT_TOKEN=test-token\nQG_TELEGRAM_CHAT_ID=test-chat\n",
            encoding="utf-8",
        )
        config = NotifyConfig.from_env()
        self.assertTrue(config.telegram_configured)
        self.assertFalse(config.telegram_push_allowed)
        self.assertTrue(config.telegram_environment_safe)

        public = config.public_dict()
        self.assertFalse(public["commandsEnvRequested"])
        self.assertEqual(public["blockedUnsafeEnvironmentKeys"], [])
        self.assertEqual(
            public["safety"],
            {
                "pushOnly": True,
                "notificationPushOnly": True,
                "commandsAllowed": False,
                "telegramCommandsAccepted": False,
                "commandsEnvRequested": False,
                "gatewayReceivesCommands": False,
                "telegramCommandExecutionAllowed": False,
                "unsafeEnvironmentBlocked": False,
                "orderSendAllowed": False,
                "closeAllowed": False,
                "cancelAllowed": False,
                "livePresetMutationAllowed": False,
                "writesMt5OrderRequest": False,
                "externalMarketRealMoneyAllowed": False,
            },
        )

    def test_config_exposes_actual_command_env_request_without_enabling_commands(self) -> None:
        os.environ["QG_TELEGRAM_COMMANDS_ALLOWED"] = "allowed"
        public = NotifyConfig.from_env().public_dict()

        self.assertTrue(public["commandsEnvRequested"])
        self.assertIn("QG_TELEGRAM_COMMANDS_ALLOWED", public["blockedUnsafeEnvironmentKeys"])
        self.assertTrue(public["safety"]["commandsEnvRequested"])
        self.assertTrue(public["safety"]["unsafeEnvironmentBlocked"])
        self.assertFalse(public["safety"]["commandsAllowed"])
        self.assertFalse(public["safety"]["telegramCommandsAccepted"])
        self.assertFalse(public["safety"]["gatewayReceivesCommands"])
        self.assertFalse(public["safety"]["telegramCommandExecutionAllowed"])

    def test_test_daily_digest_and_runtime_scan_cli_default_to_dry_run(self) -> None:
        test_result = self.run_cli(["test", "--message", "preview only"])
        self.assertTrue(test_result["dryRun"])
        self.assertFalse(test_result["sent"])

        digest_result = self.run_cli(["daily-digest"])
        self.assertTrue(digest_result["dryRun"])
        self.assertFalse(digest_result["sent"])

        (self.runtime / "QuantGod_Dashboard.json").write_text(
            json.dumps({"killSwitchActive": True, "killSwitchReason": "test"}),
            encoding="utf-8",
        )
        scan_result = self.run_cli(["scan-once"])
        self.assertEqual(scan_result["count"], 1)
        self.assertTrue(scan_result["results"][0]["dryRun"])
        self.assertFalse(scan_result["results"][0]["sent"])

    def test_forbidden_truthy_flags_block_direct_notify_before_network(self) -> None:
        os.environ["QG_TELEGRAM_BOT_TOKEN"] = "test-token"
        os.environ["QG_TELEGRAM_CHAT_ID"] = "test-chat"
        os.environ["QG_TELEGRAM_PUSH_ALLOWED"] = "1"
        for key in FORBIDDEN_NOTIFY_TRUTHY_ENV:
            with self.subTest(key=key):
                os.environ[key] = "allowed"
                config = NotifyConfig.from_env()
                self.assertIn(key, config.safety_violations)
                with patch.object(TelegramBot, "send_message_result", new=AsyncMock()) as send_mock:
                    result = asyncio.run(send_event("TEST", {"message": "blocked"}, config=config, dry_run=False))
                self.assertFalse(result["ok"])
                self.assertFalse(result["sent"])
                self.assertEqual(result["status"], "blocked_unsafe_environment")
                self.assertIn(key, result["error"])
                send_mock.assert_not_awaited()
                os.environ.pop(key, None)

    def test_direct_bot_also_rejects_unsafe_process_environment(self) -> None:
        os.environ["QG_TELEGRAM_COMMANDS_ALLOWED"] = "yes"
        bot = TelegramBot("test-token", "test-chat")
        with patch.object(bot, "_post_with_retries") as post_mock:
            result = asyncio.run(bot.send_message_result("must not send"))
        self.assertFalse(result.ok)
        self.assertIn("QG_TELEGRAM_COMMANDS_ALLOWED", result.error)
        post_mock.assert_not_called()

    def test_direct_bot_rejects_unsafe_local_telegram_environment(self) -> None:
        (self.runtime / ".env.telegram.local").write_text(
            "QG_ORDER_SEND_ALLOWED=on\n",
            encoding="utf-8",
        )
        bot = TelegramBot("test-token", "test-chat")
        with patch.object(bot, "_post_with_retries") as post_mock:
            result = asyncio.run(bot.send_message_result("must not send"))
        self.assertFalse(result.ok)
        self.assertIn("QG_ORDER_SEND_ALLOWED", result.error)
        post_mock.assert_not_called()

    def test_long_message_truncation_keeps_one_canonical_shadow_footer(self) -> None:
        prepared = prepare_telegram_message(
            f"{'x' * 5000}\n{TELEGRAM_SAFETY_FOOTER}\n{TELEGRAM_SAFETY_FOOTER}"
        )
        self.assertLessEqual(len(prepared), TELEGRAM_MAX_CHARS)
        self.assertTrue(prepared.endswith(TELEGRAM_SAFETY_FOOTER))
        self.assertEqual(prepared.count(TELEGRAM_SAFETY_FOOTER), 1)

        bot = TelegramBot("test-token", "test-chat")
        with patch.object(
            bot,
            "_post_with_retries",
            return_value=TelegramSendResult(ok=True),
        ) as post_mock:
            result = asyncio.run(bot.send_message_result("y" * 5000))
        self.assertTrue(result.ok)
        sent_payload = post_mock.call_args.args[0]
        self.assertLessEqual(len(sent_payload["text"]), TELEGRAM_MAX_CHARS)
        self.assertTrue(sent_payload["text"].endswith(TELEGRAM_SAFETY_FOOTER))


if __name__ == "__main__":
    unittest.main()
