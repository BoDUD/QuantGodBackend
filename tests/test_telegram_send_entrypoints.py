from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import run_ai_advisory_fusion, run_telegram_notifier, telegram_gateway_cli

ROOT = Path(__file__).resolve().parents[1]
RUNNERS = (
    "tools/run_adaptive_policy.py",
    "tools/run_auto_execution_policy.py",
    "tools/run_automation_chain.py",
    "tools/run_entry_trigger_lab.py",
    "tools/run_pilot_safety_lock.py",
    "tools/run_ai_advisory_fusion.py",
    "tools/run_mt5_ai_telegram_monitor.py",
    "tools/notify/notify_service.py",
    "tools/notify/telegram_bot.py",
)
CANONICAL_TRANSPORT = "tools/usdjpy_evidence_os/telegram_gateway.py"
QUERY_CLIENT_ALLOWLIST = {
    "tools/telegram_notifier/client.py",
    "tools/run_telegram_notifier.py",
}


class TelegramSendEntrypointTests(unittest.TestCase):
    def test_legacy_cli_senders_use_the_canonical_gateway(self) -> None:
        for relative_path in RUNNERS:
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(runner=relative_path):
                self.assertIn("dispatch_cli_text", source)
                self.assertNotIn("TelegramClient(", source)
                self.assertNotIn("load_telegram_config", source)
                self.assertNotIn("/sendMessage", source)

    def test_only_gateway_owns_real_telegram_message_transport(self) -> None:
        for path in sorted((ROOT / "tools").rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=relative):
                if "/sendMessage" in source or "api.telegram.org/bot" in source:
                    self.assertEqual(relative, CANONICAL_TRANSPORT)
                if "TelegramClient(" in source:
                    self.assertIn(relative, QUERY_CLIENT_ALLOWLIST)
                if relative in QUERY_CLIENT_ALLOWLIST:
                    self.assertNotIn('.request("sendMessage"', source)

    def test_configuration_query_client_allowlist_is_narrow_and_non_sending(self) -> None:
        client_source = (ROOT / "tools/telegram_notifier/client.py").read_text(encoding="utf-8")
        runner_source = (ROOT / "tools/run_telegram_notifier.py").read_text(encoding="utf-8")
        self.assertIn("get_me", client_source)
        self.assertIn("get_webhook_info", client_source)
        self.assertIn("get_updates", client_source)
        self.assertNotIn("def send_message", client_source)
        self.assertNotIn(".send_message(", runner_source)
        self.assertIn("dispatch_cli_text", runner_source)

    def test_local_env_loader_filters_keys_and_preserves_process_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env.telegram.local").write_text(
                "QG_TELEGRAM_BOT_TOKEN=file-token\n"
                "QG_TELEGRAM_CHAT_ID=file-chat\n"
                "QG_TELEGRAM_API_ID=must-not-load\n"
                "QG_TELEGRAM_API_HASH=must-not-load\n",
                encoding="utf-8",
            )
            keys = (
                "QG_TELEGRAM_BOT_TOKEN",
                "QG_TELEGRAM_CHAT_ID",
                "QG_TELEGRAM_API_ID",
                "QG_TELEGRAM_API_HASH",
            )
            previous = {key: os.environ.get(key) for key in keys}
            try:
                os.environ["QG_TELEGRAM_BOT_TOKEN"] = "process-token"
                for key in keys[1:]:
                    os.environ.pop(key, None)
                telegram_gateway_cli.load_local_telegram_env(root)
                self.assertEqual(os.environ["QG_TELEGRAM_BOT_TOKEN"], "process-token")
                self.assertEqual(os.environ["QG_TELEGRAM_CHAT_ID"], "file-chat")
                self.assertNotIn("QG_TELEGRAM_API_ID", os.environ)
                self.assertNotIn("QG_TELEGRAM_API_HASH", os.environ)
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_explicit_cli_send_routes_once_through_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            with mock.patch.object(telegram_gateway_cli, "load_local_telegram_env") as load_env:
                with mock.patch.object(
                    telegram_gateway_cli,
                    "dispatch_text",
                    return_value={"ok": True, "delivery": {"ok": False, "skipped": True}},
                ) as dispatch:
                    result = telegram_gateway_cli.dispatch_cli_text(
                        runtime_dir=runtime_dir,
                        source="test_runner",
                        topic="TEST_REPORT",
                        severity="INFO",
                        text="preview",
                        repo_root=ROOT,
                    )

            load_env.assert_called_once_with(ROOT)
            dispatch.assert_called_once_with(
                runtime_dir,
                "test_runner",
                "TEST_REPORT",
                "INFO",
                "preview",
                send=True,
            )
            self.assertFalse(result["delivery"]["ok"])
            self.assertTrue(result["sendRequested"])
            self.assertFalse(result["sent"])
            self.assertFalse(result["deliveryOk"])

    def test_cli_normalization_requires_a_message_receipt(self) -> None:
        cases = (
            ({"ok": True, "delivery": {"ok": True}}, False),
            ({"ok": True, "delivery": {"ok": True, "messageId": 42}}, True),
        )
        for gateway_result, expected in cases:
            with self.subTest(gateway_result=gateway_result), mock.patch.object(
                telegram_gateway_cli,
                "load_local_telegram_env",
            ), mock.patch.object(
                telegram_gateway_cli,
                "dispatch_text",
                return_value=gateway_result,
            ):
                result = telegram_gateway_cli.dispatch_cli_text(
                    runtime_dir="runtime",
                    source="test_runner",
                    topic="TEST_REPORT",
                    severity="INFO",
                    text="preview",
                )

            self.assertEqual(result["deliveryOk"], expected)
            self.assertEqual(result["sent"], expected)

    def test_fusion_preview_is_compact_shadow_only_and_never_dispatches(self) -> None:
        report = {
            "symbol": "USDJPYc",
            "generatedAt": "2026-08-02T00:00:00Z",
            "advisory_fusion": {
                "finalAction": "WATCH_LONG",
                "notifySeverity": "SIGNAL_REVIEW",
                "agreement": "compatible",
            },
            "deepseek_advice": {
                "validation": {
                    "status": "pass",
                    "evidenceQuality": {
                        "source": "runtime_files",
                        "fallback": False,
                        "runtimeFresh": True,
                    },
                },
                "advice": {
                    "entryZone": "155.00-155.10",
                    "targets": ["155.50"],
                    "positionAdvice": "0.02 lot",
                },
            },
        }
        args = run_ai_advisory_fusion.build_parser().parse_args(["scan-once", "--delivery-preview"])
        with mock.patch.object(run_ai_advisory_fusion, "dispatch_cli_text") as dispatch:
            result = run_ai_advisory_fusion.maybe_send(args, report)
        dispatch.assert_not_called()
        self.assertTrue(result["dryRun"])
        self.assertFalse(result["sent"])
        message = result["messagePreview"]
        self.assertLessEqual(len(message), 700)
        for forbidden in ("entry", "stop", "target", "position", "入场", "止损", "目标", "仓位"):
            self.assertNotIn(forbidden, message.lower())
        self.assertIn("永久 Shadow", message)

    def test_notifier_test_and_notify_default_to_preview(self) -> None:
        for command in (["test"], ["notify", "--title", "状态"]):
            with self.subTest(command=command):
                args = run_telegram_notifier.build_parser().parse_args(command)
                self.assertFalse(args.send)


if __name__ == "__main__":
    unittest.main()
