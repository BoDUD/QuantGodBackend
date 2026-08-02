"""Unit tests for the notify messages module.

Covers every renderer for the happy path, edge cases (empty
payloads, missing fields), and the critical HOLD → None contract.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from notify.messages import RENDERERS, render


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "notify"
GOLDEN = Path(__file__).resolve().parent / "golden" / "notify"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _load_golden(name: str) -> str:
    return (GOLDEN / f"{name}.txt").read_text(encoding="utf-8").rstrip()


def _strip_time(line: str) -> str:
    """Remove the variable Tokyo time suffix so golden tests are stable."""
    # "时间：14:30 JST" → "时间：**:** JST"
    import re
    line = re.sub(r"时间：\d{2}:\d{2} JST", "时间：**:** JST", line)
    return re.sub(r"东京时间 \d{2}:\d{2}", "东京时间 **:**", line)


class AiAdvisoryTests(unittest.TestCase):
    """ai_advisory renderer."""

    def test_hold_returns_none(self) -> None:
        self.assertIsNone(render("ai_advisory", {"decision": {"action": "HOLD"}}))

    def test_hold_returns_none_even_with_full_payload(self) -> None:
        fixture = _load_fixture("ai_advisory_buy")
        fixture["decision"]["action"] = "HOLD"
        self.assertIsNone(render("ai_advisory", fixture))

    def test_buy_contains_required_fields(self) -> None:
        msg = render("ai_advisory", _load_fixture("ai_advisory_buy"))
        assert msg is not None
        self.assertIn("QuantGod · AI 观察", msg)
        self.assertIn("USDJPYc", msg)
        self.assertIn("偏多", msg)
        self.assertIn("72%", msg)
        for forbidden in ("入场", "止损", "目标", "仓位", "持仓", "153.60", "1H 收盘跌破"):
            self.assertNotIn(forbidden, msg)
        self.assertIn("永久 Shadow", msg)
        self.assertLessEqual(len(msg), 700)

    def test_sell_message(self) -> None:
        msg = render("ai_advisory", _load_fixture("ai_advisory_sell"))
        assert msg is not None
        self.assertIn("偏空", msg)
        self.assertIn("EURUSDc", msg)

    def test_empty_payload(self) -> None:
        """Empty payload should not crash — should return None for HOLD."""
        self.assertIsNone(render("ai_advisory", {}))

    def test_minimal_payload_buy(self) -> None:
        msg = render("ai_advisory", {"decision": {"action": "BUY"}})
        assert msg is not None
        self.assertIn("偏多", msg)

    def test_golden_buy(self) -> None:
        fixture = _load_fixture("ai_advisory_buy")
        expected = _load_golden("ai_advisory_buy")
        actual = (render("ai_advisory", fixture) or "").rstrip()
        # Strip time-dependent fields
        actual_stable = _strip_time(actual)
        expected_stable = _strip_time(expected)
        self.assertEqual(
            actual_stable,
            expected_stable,
            "ai_advisory BUY golden file mismatch — review diff and update golden file",
        )

    def test_golden_sell(self) -> None:
        fixture = _load_fixture("ai_advisory_sell")
        expected = _load_golden("ai_advisory_sell")
        actual = (render("ai_advisory", fixture) or "").rstrip()
        actual_stable = _strip_time(actual)
        expected_stable = _strip_time(expected)
        self.assertEqual(actual_stable, expected_stable)


class DeepSeekInsightTests(unittest.TestCase):
    """deepseek_insight renderer."""

    def test_hold_returns_none(self) -> None:
        self.assertIsNone(
            render("deepseek_insight", {"decision": {"action": "HOLD"}})
        )

    def test_buy_contains_deepseek_sections(self) -> None:
        msg = render("deepseek_insight", _load_fixture("deepseek_insight_buy"))
        assert msg is not None
        self.assertIn("QuantGod · DeepSeek 观察", msg)
        self.assertIn("结论：", msg)
        self.assertIn("关键：", msg)
        self.assertIn("原因：", msg)
        self.assertIn("下一步：", msg)
        self.assertIn("deepseek-v4-flash", msg)
        self.assertIn("偏多", msg)
        for forbidden in ("入场", "止损", "目标", "仓位", "持仓"):
            self.assertNotIn(forbidden, msg)
        self.assertIn("永久 Shadow", msg)
        self.assertLessEqual(len(msg), 700)

    def test_golden_buy(self) -> None:
        fixture = _load_fixture("deepseek_insight_buy")
        expected = _load_golden("deepseek_insight_buy")
        actual = (render("deepseek_insight", fixture) or "").rstrip()
        actual_stable = _strip_time(actual)
        expected_stable = _strip_time(expected)
        self.assertEqual(actual_stable, expected_stable)


class DailyDigestTests(unittest.TestCase):
    """daily_digest renderer."""

    def test_produces_compact_output(self) -> None:
        msg = render("daily_digest", _load_fixture("daily_digest"))
        assert msg is not None
        lines = msg.split("\n")
        self.assertIn("\U0001f4ca 今日复盘", msg)
        self.assertIn("+$245.60", msg)
        self.assertIn("8 胜", msg)
        self.assertIn("3 负", msg)
        # Must be compact (≤ 6 meaningful lines)
        self.assertLessEqual(len([l for l in lines if l.strip()]), 8)

    def test_minimal_payload(self) -> None:
        msg = render("daily_digest", {})
        assert msg is not None
        self.assertIn("$0.00", msg)

    def test_golden(self) -> None:
        fixture = _load_fixture("daily_digest")
        expected = _load_golden("daily_digest")
        actual = (render("daily_digest", fixture) or "").rstrip()
        # The date in the golden file header may differ; strip it
        import re
        actual_stable = re.sub(r"今日复盘 — \d{4}-\d{2}-\d{2}", "今日复盘 — YYYY-MM-DD", actual)
        expected_stable = re.sub(r"今日复盘 — \d{4}-\d{2}-\d{2}", "今日复盘 — YYYY-MM-DD", expected)
        self.assertEqual(actual_stable, expected_stable)


class RuntimeEventTests(unittest.TestCase):
    """runtime_event renderer (dispatches on _event_type)."""

    def test_kill_switch(self) -> None:
        msg = render("runtime_event", _load_fixture("runtime_event_kill_switch"))
        assert msg is not None
        self.assertIn("⛔ Kill Switch 触发", msg)
        self.assertIn("daily_drawdown_exceeded", msg)
        self.assertIn("$-420.50", msg)

    def test_news_block(self) -> None:
        msg = render("runtime_event", _load_fixture("runtime_event_news_block"))
        assert msg is not None
        self.assertIn("\U0001f4f0 高影响新闻预警", msg)
        self.assertIn("Non-Farm", msg)
        self.assertIn("12 分钟", msg)
        self.assertIn("阶段：PRE_EVENT", msg)
        self.assertIn("本地风控已标记为阻断", msg)
        self.assertIn("实际 180", msg)
        self.assertIn("预期 175", msg)
        self.assertIn("前值 165", msg)
        self.assertIn("NFP release window", msg)

    def test_consecutive_loss(self) -> None:
        msg = render(
            "runtime_event", _load_fixture("runtime_event_consecutive_loss")
        )
        assert msg is not None
        self.assertIn("⚠️ 连亏暂停", msg)
        self.assertIn("$-78.20", msg)

    def test_risk_threshold(self) -> None:
        msg = render(
            "runtime_event",
            {
                "_event_type": "RISK_THRESHOLD",
                "metric": "max_drawdown_pct",
                "value": "12.5%",
                "threshold": "10%",
                "risk_level": "high",
            },
        )
        assert msg is not None
        self.assertIn("风险阈值预警", msg)
        self.assertIn("12.5%", msg)

    def test_governance(self) -> None:
        msg = render(
            "runtime_event",
            {
                "_event_type": "GOVERNANCE",
                "route": "mt5_rsi_failfast",
                "action": "暂停该路由",
                "reason": "连亏 3 次触发治理规则",
            },
        )
        assert msg is not None
        self.assertIn("\U0001f6e1", msg)
        self.assertIn("mt5_rsi_failfast", msg)

    def test_trade_open(self) -> None:
        msg = render(
            "runtime_event",
            {
                "_event_type": "TRADE_OPEN",
                "symbol": "EURUSDc",
                "side": "BUY",
                "lots": 0.02,
                "price": 1.0850,
                "sl": 1.0820,
                "tp": 1.0920,
                "route": "rsi_reversal",
            },
        )
        assert msg is not None
        self.assertIn("观察到持仓新增", msg)
        self.assertIn("做多", msg)
        self.assertIn("未发送此订单", msg)

    def test_trade_close(self) -> None:
        msg = render(
            "runtime_event",
            {
                "_event_type": "TRADE_CLOSE",
                "symbol": "USDJPYc",
                "pnl": 35.50,
                "duration": "2h 15m",
            },
        )
        assert msg is not None
        self.assertIn("观察到持仓结束", msg)
        self.assertIn("未执行此平仓", msg)

    def test_generic_fallback(self) -> None:
        msg = render("runtime_event", {"_event_type": "UNKNOWN_TYPE", "summary": "test"})
        assert msg is not None
        self.assertIn("ℹ️ QuantGod 事件", msg)

    def test_golden_kill_switch(self) -> None:
        fixture = _load_fixture("runtime_event_kill_switch")
        expected = _load_golden("runtime_event_kill_switch")
        actual = (render("runtime_event", fixture) or "").rstrip()
        self.assertEqual(actual, expected)

    def test_golden_news_block(self) -> None:
        fixture = _load_fixture("runtime_event_news_block")
        expected = _load_golden("runtime_event_news_block")
        actual = (render("runtime_event", fixture) or "").rstrip()
        self.assertEqual(actual, expected)

    def test_golden_consecutive_loss(self) -> None:
        fixture = _load_fixture("runtime_event_consecutive_loss")
        expected = _load_golden("runtime_event_consecutive_loss")
        actual = (render("runtime_event", fixture) or "").rstrip()
        self.assertEqual(actual, expected)


class TestRendererTests(unittest.TestCase):
    """test renderer."""

    def test_output(self) -> None:
        msg = render("test", _load_fixture("test"))
        assert msg is not None
        self.assertIn("\U0001f9ea QuantGod 通道测试", msg)
        self.assertIn("ping from CI", msg)

    def test_golden(self) -> None:
        fixture = _load_fixture("test")
        expected = _load_golden("test")
        actual = (render("test", fixture) or "").rstrip()
        actual_stable = _strip_time(actual)
        expected_stable = _strip_time(expected)
        self.assertEqual(actual_stable, expected_stable)


class RenderRegistryTests(unittest.TestCase):
    """render() main entry-point behaviours."""

    def test_unknown_kind_returns_info_message(self) -> None:
        msg = render("nonexistent_kind", {})
        assert msg is not None
        self.assertIn("未知通知类型", msg)

    def test_all_registered_kinds_are_callable(self) -> None:
        for kind in RENDERERS:
            with self.subTest(kind=kind):
                self.assertTrue(callable(RENDERERS[kind]))

    def test_render_never_raises(self) -> None:
        """Malformed payloads must not crash the render() entry point."""
        # Pass something that makes string ops choke
        result = render("test", None)  # type: ignore[arg-type]
        # Should return a fallback string, not raise
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_message_length_limited_to_4096(self) -> None:
        """render() must enforce the Telegram 4096-char limit."""
        huge = {"message": "x" * 5000}
        msg = render("test", huge)
        assert msg is not None
        self.assertLessEqual(len(msg), 4096)


if __name__ == "__main__":
    unittest.main()
