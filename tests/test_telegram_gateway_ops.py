"""Tests for Telegram Gateway observability helpers."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.telegram_gateway_ops.status import (
    build_gateway_ops_status,
    collect_gateway_ops,
)
from tools.telegram_gateway_ops.telegram_text import gateway_ops_to_chinese_text
from tools.usdjpy_evidence_os.telegram_gateway import (
    build_notification_event,
    dispatch_event,
    enqueue_event,
)
from tools.usdjpy_evidence_os.schema import gateway_ledger_path


class TelegramGatewayOpsTests(unittest.TestCase):
    def test_status_summarizes_queue_ledger_and_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            sent = build_notification_event("unit", "DAILY_AUTOPILOT_V2_REPORT", "INFO", "已发送")
            pending = build_notification_event("unit", "GA_EVOLUTION_REPORT", "INFO", "待投递")
            dispatch_event(runtime_dir, sent, send=False)
            enqueue_event(runtime_dir, pending)

            status = build_gateway_ops_status(runtime_dir)
            self.assertEqual(status["schema"], "quantgod.telegram_gateway_ops.status.v1")
            self.assertEqual(status["ledgerCount"], 1)
            self.assertEqual(status["pendingCount"], 1)
            self.assertEqual(status["pendingByTopic"]["GA_EVOLUTION_REPORT"], 1)
            self.assertFalse(status["safety"]["telegramCommandExecutionAllowed"])
            self.assertFalse(status["safety"]["orderSendAllowed"])

            text = gateway_ops_to_chinese_text(status)
            self.assertIn("QuantGod · Telegram 网关", text)
            self.assertIn("结论：", text)
            self.assertIn("下一步：", text)
            self.assertIn("无执行通道", text)
            self.assertLessEqual(len(text), 700)

    def test_collect_gateway_ops_only_queues_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            status = collect_gateway_ops(
                runtime_dir,
                repo_root=Path(__file__).resolve().parents[1],
                refresh=True,
            )
            self.assertTrue(status["ok"])
            self.assertGreaterEqual(status["collectedCount"], 3)
            self.assertGreaterEqual(status["pendingCount"], 3)
            self.assertFalse(status["safety"]["gatewayReceivesCommands"])
            self.assertFalse(status["commandsAllowed"])

    def test_ops_status_keeps_commands_blocked_when_env_is_misset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"QG_TELEGRAM_COMMANDS_ALLOWED": "1"},
            clear=False,
        ):
            status = build_gateway_ops_status(Path(tmp))
            self.assertEqual(status["status"], "COMMAND_ENV_BLOCKED_WARN")
            self.assertIn("已硬阻断", status["statusZh"])
            self.assertFalse(status["commandsAllowed"])
            self.assertTrue(status["commandsEnvRequested"])
            self.assertEqual(status["commandsBlockedReason"], "telegram_command_execution_disabled")
            self.assertFalse(status["safety"]["telegramCommandExecutionAllowed"])

    def test_sent_topic_requires_receipt_and_exposes_message_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "tools.usdjpy_evidence_os.telegram_gateway._send_telegram",
            return_value={"ok": True, "messageId": 321, "transport": "urllib"},
        ):
            runtime_dir = Path(tmp)
            event = build_notification_event("unit", "GA_EVOLUTION_REPORT", "INFO", "确认送达")
            dispatch_event(runtime_dir, event, send=True)

            status = build_gateway_ops_status(runtime_dir)

        self.assertEqual(status["actualSentCount"], 1)
        row = next(item for item in status["latestTopicRows"] if item["topic"] == "GA_EVOLUTION_REPORT")
        self.assertTrue(row["deliveryOk"])
        self.assertEqual(row["messageId"], 321)
        self.assertTrue(row["sentAtIso"])

    def test_legacy_ok_without_receipt_is_failed_not_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            ledger = gateway_ledger_path(runtime_dir)
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(
                json.dumps(
                    {
                        "eventId": "legacy-unconfirmed",
                        "topic": "DAILY_AUTOPILOT_V2_REPORT",
                        "createdAt": "2026-08-02T00:00:00Z",
                        "delivery": {"ok": True, "processedAtIso": "2026-08-02T00:00:01Z"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            status = build_gateway_ops_status(runtime_dir)

        self.assertEqual(status["actualSentCount"], 0)
        self.assertEqual(status["failedCount"], 1)
        row = status["latestTopicRows"][0]
        self.assertFalse(row["deliveryOk"])
        self.assertIsNone(row["messageId"])
        self.assertIsNone(row["sentAtIso"])


if __name__ == "__main__":
    unittest.main()
