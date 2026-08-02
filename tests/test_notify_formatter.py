from __future__ import annotations

import unittest

from tools.notify.event_formatter import format_event


class NotifyFormatterTests(unittest.TestCase):
    def test_ai_analysis_message_is_structured(self) -> None:
        """AI_ANALYSIS with BUY produces a structured message."""
        text = format_event(
            "AI_ANALYSIS",
            {
                "symbol": "EURUSDc",
                "action": "BUY",
                "confidence": 0.72,
                "risk": "medium",
                "note": "Trend continuation expected",
            },
        )
        self.assertIn("EURUSDc", text)
        self.assertIn("QuantGod · AI 观察", text)
        self.assertIn("72%", text)

    def test_ai_analysis_hold_returns_empty(self) -> None:
        """AI_ANALYSIS with HOLD returns empty string (suppressed push)."""
        text = format_event(
            "AI_ANALYSIS",
            {
                "symbol": "EURUSDc",
                "action": "HOLD",
                "confidence": 0.35,
                "risk": "medium_high",
                "note": "Wait for NFP",
            },
        )
        self.assertEqual(text, "")

    def test_trade_messages_plain_text(self) -> None:
        """Messages are plain text — no HTML markup (by design, Telegram plain text)."""
        text = format_event("TEST", {"message": "ping <b>bold</b>"})
        self.assertIn("ping <b>bold</b>", text)
        self.assertIn("\U0001f9ea QuantGod 通道测试", text)

    def test_all_required_phase2_events_have_messages(self) -> None:
        events = [
            "TRADE_OPEN",
            "TRADE_CLOSE",
            "KILL_SWITCH",
            "NEWS_BLOCK",
            "CONSECUTIVE_LOSS",
            "DAILY_DIGEST",
        ]
        for event in events:
            with self.subTest(event=event):
                self.assertGreater(
                    len(format_event(event, {"symbol": "EURUSDc", "message": "ok"})),
                    10,
                )

    def test_governance_event(self) -> None:
        text = format_event(
            "GOVERNANCE",
            {"route": "mt5_rsi_failfast", "action": "暂停", "reason": "连亏"},
        )
        self.assertGreater(len(text), 10)
        self.assertIn("mt5_rsi_failfast", text)


if __name__ == "__main__":
    unittest.main()
