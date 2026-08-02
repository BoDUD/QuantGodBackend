from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools import run_telegram_gateway
from tools.notify.config import FORBIDDEN_NOTIFY_TRUTHY_ENV
from tools.usdjpy_evidence_os import telegram_gateway as telegram_gateway_module
from tools.usdjpy_evidence_os.io_utils import read_jsonl_tail
from tools.usdjpy_evidence_os.schema import gateway_ledger_path
from tools.usdjpy_evidence_os.telegram_gateway import (
    FORBIDDEN_TELEGRAM_GATEWAY_TRUTHY_ENV,
    TELEGRAM_SAFETY_FOOTER,
    TELEGRAM_TEXT_MAX_CHARS,
    _send_telegram,
    build_notification_event,
    dispatch_event,
    dispatch_pending,
    enqueue_event,
    gateway_status,
    prepare_telegram_text,
)


class TelegramGatewaySafetyTests(unittest.TestCase):
    def test_gateway_forbidden_environment_keys_match_notify_config(self) -> None:
        self.assertEqual(FORBIDDEN_TELEGRAM_GATEWAY_TRUTHY_ENV, FORBIDDEN_NOTIFY_TRUTHY_ENV)

    def test_every_forbidden_truthy_environment_flag_blocks_before_network(self) -> None:
        safe_environment = {key: "0" for key in FORBIDDEN_TELEGRAM_GATEWAY_TRUTHY_ENV}
        safe_environment.update(
            {
                "QG_TELEGRAM_PUSH_ALLOWED": "1",
                "QG_TELEGRAM_BOT_TOKEN": "123456:TEST_ONLY_NOT_A_REAL_TOKEN",
                "QG_TELEGRAM_CHAT_ID": "999",
            }
        )
        for key in FORBIDDEN_TELEGRAM_GATEWAY_TRUTHY_ENV:
            environment = {**safe_environment, key: "allowed"}
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ,
                environment,
                clear=False,
            ), patch("tools.usdjpy_evidence_os.telegram_gateway.urllib.request.urlopen") as urlopen:
                delivery = _send_telegram("危险环境必须在网络前阻断")
                status = gateway_status(Path(tmp))

            self.assertFalse(delivery["ok"])
            self.assertTrue(delivery["skipped"])
            self.assertTrue(delivery["blocked"])
            self.assertIn(key, delivery["blockedUnsafeEnvironmentKeys"])
            self.assertFalse(status["environmentSafe"])
            self.assertIn(key, status["blockedUnsafeEnvironmentKeys"])
            urlopen.assert_not_called()

    def test_gateway_blocks_unsafe_local_telegram_env_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            env_file = runtime_dir / ".env.telegram.local"
            env_file.write_text("QG_WITHDRAWAL_ALLOWED=on\n", encoding="utf-8")
            environment = {
                "QG_TELEGRAM_ENV_FILE": str(env_file),
                "QG_TELEGRAM_PUSH_ALLOWED": "1",
                "QG_TELEGRAM_COMMANDS_ALLOWED": "0",
                "QG_TELEGRAM_BOT_TOKEN": "123456:TEST_ONLY_NOT_A_REAL_TOKEN",
                "QG_TELEGRAM_CHAT_ID": "999",
            }
            with patch.dict(os.environ, environment, clear=True), patch(
                "tools.usdjpy_evidence_os.telegram_gateway.urllib.request.urlopen"
            ) as urlopen:
                delivery = _send_telegram("本地环境文件也必须阻断")
                status = gateway_status(runtime_dir)

        self.assertFalse(delivery["ok"])
        self.assertTrue(delivery["blocked"])
        self.assertEqual(delivery["blockedUnsafeEnvironmentKeys"], ["QG_WITHDRAWAL_ALLOWED"])
        self.assertFalse(status["environmentSafe"])
        self.assertEqual(status["blockedUnsafeEnvironmentKeys"], ["QG_WITHDRAWAL_ALLOWED"])
        urlopen.assert_not_called()

    def test_gateway_status_reports_safe_environment_when_all_flags_are_false(self) -> None:
        environment = {key: "0" for key in FORBIDDEN_TELEGRAM_GATEWAY_TRUTHY_ENV}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, environment, clear=False):
            status = gateway_status(Path(tmp))

        self.assertTrue(status["environmentSafe"])
        self.assertEqual(status["blockedUnsafeEnvironmentKeys"], [])

    def test_gateway_status_confirms_push_only_boundary_without_enabling_push(self) -> None:
        environment = {key: "0" for key in FORBIDDEN_TELEGRAM_GATEWAY_TRUTHY_ENV}
        environment["QG_TELEGRAM_PUSH_ALLOWED"] = "0"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, environment, clear=False):
            status = gateway_status(Path(tmp))

        self.assertFalse(status["pushAllowed"])
        self.assertTrue(status["pushOnly"])
        self.assertTrue(status["notificationPushOnly"])
        self.assertFalse(status["commandsAllowed"])
        self.assertFalse(status["executionLaneExists"])
        safety = status["safety"]
        self.assertTrue(safety["pushOnly"])
        self.assertTrue(safety["notificationPushOnly"])
        self.assertFalse(safety["commandsAllowed"])
        self.assertFalse(safety["telegramCommandExecutionAllowed"])
        self.assertFalse(safety["gatewayReceivesCommands"])
        self.assertFalse(safety["executionLaneExists"])
        for key in (
            "orderSendAllowed",
            "closeAllowed",
            "cancelAllowed",
            "livePresetMutationAllowed",
            "writesMt5OrderRequest",
        ):
            self.assertFalse(safety[key], key)

    def test_all_supported_truthy_command_values_fail_closed_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for value in ("1", " true ", "TRUE", "yes", "YES", "y", "on", "ON", "allow", "allowed"):
                with self.subTest(value=value), patch.dict(
                    os.environ,
                    {
                        "QG_TELEGRAM_PUSH_ALLOWED": "1",
                        "QG_TELEGRAM_COMMANDS_ALLOWED": value,
                        "QG_TELEGRAM_BOT_TOKEN": "123456:TEST_ONLY_NOT_A_REAL_TOKEN",
                        "QG_TELEGRAM_CHAT_ID": "999",
                    },
                    clear=False,
                ), patch("tools.usdjpy_evidence_os.telegram_gateway.urllib.request.urlopen") as urlopen:
                    delivery = _send_telegram("不得进入网络层")
                    status = gateway_status(Path(tmp))

                self.assertFalse(delivery["ok"])
                self.assertTrue(delivery["skipped"])
                self.assertEqual(delivery["reason"], "Telegram command execution must stay disabled")
                self.assertTrue(status["commandsEnvRequested"])
                self.assertFalse(status["commandsAllowed"])
                self.assertEqual(status["commandsBlockedReason"], "telegram_command_execution_disabled")
                urlopen.assert_not_called()

    def test_false_command_values_are_not_reported_as_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for value in ("", "0", "false", "no", "off", "disabled"):
                with self.subTest(value=value), patch.dict(
                    os.environ,
                    {"QG_TELEGRAM_COMMANDS_ALLOWED": value},
                    clear=False,
                ):
                    status = gateway_status(Path(tmp))
                self.assertFalse(status["commandsEnvRequested"])
                self.assertIsNone(status["commandsBlockedReason"])

    def test_safe_text_clipping_always_preserves_one_bottom_boundary(self) -> None:
        short = prepare_telegram_text(f"标题\n{TELEGRAM_SAFETY_FOOTER}\n关键信息")
        self.assertEqual(short.count(TELEGRAM_SAFETY_FOOTER), 1)
        self.assertTrue(short.endswith(TELEGRAM_SAFETY_FOOTER))

        long_text = "首行\n" + ("业务详情" * 1600) + "\n不应保留的原始尾部"
        clipped = prepare_telegram_text(long_text)
        self.assertLessEqual(len(clipped), TELEGRAM_TEXT_MAX_CHARS)
        self.assertEqual(clipped.count(TELEGRAM_SAFETY_FOOTER), 1)
        self.assertTrue(clipped.endswith(TELEGRAM_SAFETY_FOOTER))
        self.assertIn("永久 Shadow", clipped)
        self.assertIn("无执行通道", clipped)
        self.assertIn("只推送、不接收命令", clipped)
        self.assertIn("内容已安全裁剪", clipped)
        self.assertNotIn("不应保留的原始尾部", clipped)

    def test_sender_uses_prepared_text_and_returns_no_telegram_echo(self) -> None:
        token = "123456:TEST_ONLY_NOT_A_REAL_TOKEN"
        telegram_response = {
            "ok": True,
            "result": {
                "message_id": 2468,
                "chat": {"id": 999, "username": "private-chat"},
                "text": "SERVER_MESSAGE_TEXT_ECHO",
            },
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(telegram_response).encode("utf-8")
        with patch.dict(
            os.environ,
            {
                "QG_TELEGRAM_PUSH_ALLOWED": "1",
                "QG_TELEGRAM_COMMANDS_ALLOWED": "0",
                "QG_TELEGRAM_BOT_TOKEN": token,
                "QG_TELEGRAM_CHAT_ID": "999",
            },
            clear=False,
        ), patch(
            "tools.usdjpy_evidence_os.telegram_gateway.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            delivery = _send_telegram("X" * 6000)

        sent_body = urlopen.call_args.kwargs["data"].decode("utf-8")
        sent_text = urllib.parse.parse_qs(sent_body)["text"][0]
        self.assertLessEqual(len(sent_text), TELEGRAM_TEXT_MAX_CHARS)
        self.assertTrue(sent_text.endswith(TELEGRAM_SAFETY_FOOTER))
        self.assertEqual(delivery, {"ok": True, "messageId": 2468, "transport": "urllib"})
        self.assertNotIn("telegram", delivery)
        self.assertNotIn("SERVER_MESSAGE_TEXT_ECHO", json.dumps(delivery))
        self.assertNotIn("private-chat", json.dumps(delivery))

    def test_sender_requires_message_receipt_even_when_telegram_says_ok(self) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": True, "result": {"chat": {"id": 999}}}
        ).encode("utf-8")
        with patch.dict(
            os.environ,
            {
                "QG_TELEGRAM_PUSH_ALLOWED": "1",
                "QG_TELEGRAM_COMMANDS_ALLOWED": "0",
                "QG_TELEGRAM_BOT_TOKEN": "123456:TEST_ONLY_NOT_A_REAL_TOKEN",
                "QG_TELEGRAM_CHAT_ID": "999",
            },
            clear=False,
        ), patch(
            "tools.usdjpy_evidence_os.telegram_gateway.urllib.request.urlopen",
            return_value=response,
        ):
            delivery = _send_telegram("只验证响应，不会进入真实网络")

        self.assertFalse(delivery["ok"])
        self.assertEqual(delivery["reason"], "telegram_delivery_unconfirmed_missing_message_id")
        self.assertNotIn("messageId", delivery)

    def test_urllib_failure_has_no_curl_fallback_and_redacts_token(self) -> None:
        token = "123456:TEST_ONLY_NOT_A_REAL_TOKEN"
        with patch.dict(
            os.environ,
            {
                "QG_TELEGRAM_PUSH_ALLOWED": "1",
                "QG_TELEGRAM_COMMANDS_ALLOWED": "0",
                "QG_TELEGRAM_BOT_TOKEN": token,
                "QG_TELEGRAM_CHAT_ID": "999",
            },
            clear=False,
        ), patch(
            "tools.usdjpy_evidence_os.telegram_gateway.urllib.request.urlopen",
            side_effect=RuntimeError(f"request failed at https://api.telegram.org/bot{token}/sendMessage"),
        ), patch.object(subprocess, "run") as subprocess_run:
            delivery = _send_telegram("不会真实发送")

        subprocess_run.assert_not_called()
        self.assertFalse(delivery["ok"])
        self.assertEqual(delivery["transport"], "urllib")
        self.assertNotIn(token, json.dumps(delivery))
        self.assertNotIn("curl", json.dumps(delivery).lower())

    def test_ledger_writes_only_minimal_redacted_delivery_record(self) -> None:
        bot_token = "123456:TEST_ONLY_NOT_A_REAL_TOKEN"
        business_text = f"token={bot_token} " + ("业务详情" * 100) + " PRIVATE_BUSINESS_TAIL"
        event = build_notification_event(
            "private-source",
            "GA_EVOLUTION_REPORT",
            "WARN",
            business_text,
            payload={"account": "PRIVATE_ACCOUNT", "nested": {"secret": "PRIVATE_PAYLOAD_SECRET"}},
            dedupe_key="PRIVATE_DEDUPE_KEY",
        )
        raw_delivery = {
            "ok": True,
            "transport": "urllib",
            "telegram": {
                "ok": True,
                "result": {
                    "message_id": 777,
                    "chat": {"id": 999, "username": "PRIVATE_CHAT"},
                    "text": "PRIVATE_SERVER_TEXT_ECHO",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "tools.usdjpy_evidence_os.telegram_gateway._send_telegram",
            return_value=raw_delivery,
        ):
            runtime_dir = Path(tmp)
            result = dispatch_event(runtime_dir, event, send=True)
            rows = read_jsonl_tail(gateway_ledger_path(runtime_dir), 10)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            set(row),
            {"schema", "eventId", "topic", "severity", "messageLength", "messagePreview", "createdAt", "delivery"},
        )
        self.assertEqual(row["schema"], "quantgod.telegram_gateway_ledger.v2")
        self.assertEqual(row["messageLength"], len(event["text"]))
        self.assertLessEqual(len(row["messagePreview"]), 160)
        self.assertEqual(row["delivery"]["status"], "SENT")
        self.assertEqual(row["delivery"]["messageId"], 777)
        self.assertNotIn("telegram", row["delivery"])
        serialized = json.dumps(row, ensure_ascii=False)
        for forbidden in (
            bot_token,
            "PRIVATE_ACCOUNT",
            "PRIVATE_PAYLOAD_SECRET",
            "PRIVATE_DEDUPE_KEY",
            "PRIVATE_CHAT",
            "PRIVATE_SERVER_TEXT_ECHO",
            "PRIVATE_BUSINESS_TAIL",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("payload", row)
        self.assertNotIn("text", row)
        self.assertNotIn("telegram", result["delivery"])

    def test_shared_scan_reads_repo_env_and_pilot_env_without_leaking_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "123456:LOCAL_SECRET_MUST_NOT_LEAK"
            (root / ".env").write_text(
                f"QG_MT5_ADAPTIVE_APPLY_ENABLED=1\nQG_TELEGRAM_BOT_TOKEN={secret}\n",
                encoding="utf-8",
            )
            (root / ".env.pilot.local").write_text(
                "QG_PILOT_SAFETY_LOCK_DISABLED=enabled\n",
                encoding="utf-8",
            )
            environment = {"QG_TELEGRAM_PUSH_ALLOWED": "0"}
            scanner_module = sys.modules[
                telegram_gateway_module.unsafe_telegram_environment_keys.__module__
            ]
            with patch.dict(os.environ, environment, clear=True), patch.object(
                scanner_module,
                "_default_repo_root",
                return_value=root,
            ):
                status = gateway_status(root / "runtime")

        self.assertFalse(status["environmentSafe"])
        self.assertEqual(
            status["blockedUnsafeEnvironmentKeys"],
            ["QG_MT5_ADAPTIVE_APPLY_ENABLED", "QG_PILOT_SAFETY_LOCK_DISABLED"],
        )
        self.assertNotIn(secret, json.dumps(status, ensure_ascii=False))

    def test_gateway_scrubs_actionable_trade_language_before_delivery(self) -> None:
        text = prepare_telegram_text(
            "Buy at 155.10; SL 154.80; TP 155.80; 2 lots; leverage 20x; long now.\n"
            "立即下单买入，止损 154.80，止盈 155.80，目标 156.00，仓位 2 手。"
        )
        for forbidden in (
            "buy at",
            "sl 154",
            "tp 155",
            "2 lots",
            "leverage",
            "long now",
            "立即下单",
            "买入",
            "止损",
            "止盈",
            "目标",
            "仓位",
            "2 手",
        ):
            self.assertNotIn(forbidden, text.lower())
        self.assertIn("交易计划细节已隐藏", text)
        self.assertTrue(text.endswith(TELEGRAM_SAFETY_FOOTER))

    def test_minimal_ledger_keeps_dry_run_pending_then_marks_success_processed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            event = build_notification_event("unit", "GA_EVOLUTION_REPORT", "INFO", "待投递")
            enqueue_event(runtime_dir, event)

            dry_run = dispatch_pending(runtime_dir, send=False)
            self.assertEqual(dry_run["pendingCount"], 1)
            self.assertEqual(gateway_status(runtime_dir)["pendingCount"], 1)

            with patch(
                "tools.usdjpy_evidence_os.telegram_gateway._send_telegram",
                return_value={"ok": True, "messageId": 55, "transport": "urllib"},
            ):
                sent = dispatch_pending(runtime_dir, send=True)

            self.assertEqual(sent["pendingCount"], 0)
            self.assertEqual(gateway_status(runtime_dir)["pendingCount"], 0)
            rows = read_jsonl_tail(gateway_ledger_path(runtime_dir), 10)
            self.assertEqual([row["delivery"]["status"] for row in rows], ["SUPPRESSED", "SENT"])
            self.assertTrue(all("payload" not in row and "text" not in row for row in rows))

    def test_missing_message_receipt_stays_failed_and_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            event = build_notification_event("unit", "GA_EVOLUTION_REPORT", "WARN", "缺少回执")
            enqueue_event(runtime_dir, event)

            with patch(
                "tools.usdjpy_evidence_os.telegram_gateway._send_telegram",
                return_value={"ok": True, "transport": "urllib"},
            ):
                result = dispatch_pending(runtime_dir, send=True)

            delivery = result["dispatchResults"][0]["delivery"]
            self.assertFalse(delivery["ok"])
            self.assertEqual(delivery["status"], "FAILED")
            self.assertEqual(delivery["reason"], "telegram_delivery_unconfirmed_missing_message_id")
            status = gateway_status(runtime_dir)
            self.assertEqual(status["deliveredCount"], 0)
            self.assertEqual(status["pendingCount"], 1)
            self.assertEqual(status["deliveryObservability"]["failedCount"], 1)

    def test_gateway_cli_returns_nonzero_only_for_explicit_unconfirmed_send(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "tools" / "run_telegram_gateway.py"
        environment = dict(os.environ)
        environment.update(
            {
                "QG_TELEGRAM_PUSH_ALLOWED": "0",
                "QG_TELEGRAM_COMMANDS_ALLOWED": "0",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = [sys.executable, str(script), "--runtime-dir", tmp]
            enqueue = subprocess.run(
                [*base, "enqueue", "--text", "本地退出码验证"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            preview = subprocess.run(
                [*base, "dispatch"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            explicit_send = subprocess.run(
                [*base, "dispatch", "--send"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            status = subprocess.run(
                [*base, "status"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(enqueue.returncode, 0, enqueue.stderr)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(explicit_send.returncode, 2, explicit_send.stderr)
        payload = json.loads(explicit_send.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["deliveryOk"])
        self.assertFalse(payload["sent"])
        self.assertEqual(payload["failedDeliveryCount"], 1)
        self.assertEqual(payload["error"], "TELEGRAM_DELIVERY_NOT_CONFIRMED")

    def test_gateway_runner_does_not_trust_nested_ok_without_receipt(self) -> None:
        payload = {
            "ok": True,
            "dispatchResults": [{"delivery": {"ok": True, "status": "SENT"}}],
        }
        with patch("builtins.print"):
            exit_code = run_telegram_gateway.emit_explicit_send(payload)

        self.assertEqual(exit_code, 2)

    def test_legacy_full_ledger_rows_remain_readable_without_being_rewritten_or_reexposed(self) -> None:
        legacy_row = {
            "eventId": "legacy-event",
            "createdAt": "2026-08-01T00:00:00Z",
            "topic": "DAILY_AUTOPILOT_V2_REPORT",
            "severity": "INFO",
            "text": "LEGACY_FULL_TEXT",
            "payload": {"private": "LEGACY_PRIVATE_PAYLOAD"},
            "delivery": {
                "ok": True,
                "sentAtIso": "2026-08-01T00:00:01Z",
                "telegram": {
                    "ok": True,
                    "result": {
                        "message_id": 808,
                        "chat": {"username": "LEGACY_PRIVATE_CHAT"},
                        "text": "LEGACY_TELEGRAM_ECHO",
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            enqueue_event(
                runtime_dir,
                {
                    "eventId": "legacy-event",
                    "topic": "DAILY_AUTOPILOT_V2_REPORT",
                    "severity": "INFO",
                    "text": "queue copy",
                },
            )
            ledger_path = gateway_ledger_path(runtime_dir)
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            original = json.dumps(legacy_row, ensure_ascii=False) + "\n"
            ledger_path.write_text(original, encoding="utf-8")

            status = gateway_status(runtime_dir)

            self.assertEqual(status["deliveredCount"], 1)
            self.assertEqual(status["pendingCount"], 0)
            self.assertEqual(status["lastDelivery"]["messageId"], 808)
            public_delivery = json.dumps(status["lastDelivery"], ensure_ascii=False)
            self.assertNotIn("telegram", status["lastDelivery"])
            self.assertNotIn("LEGACY_PRIVATE_CHAT", public_delivery)
            self.assertNotIn("LEGACY_TELEGRAM_ECHO", public_delivery)
            self.assertEqual(ledger_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
