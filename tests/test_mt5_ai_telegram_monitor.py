from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_mt5_ai_telegram_monitor as monitor
from notify.messages import render


def sample_report(symbol: str = "USDJPYc") -> dict:
    return {
        "ok": True,
        "symbol": symbol,
        "generatedAt": "2026-05-03T00:00:00Z",
        "snapshot": {
            "source": "runtime_files",
            "fallback": False,
            "runtimeFresh": True,
            "runtimeAgeSeconds": 12,
            "current_price": {"bid": 155.12, "ask": 155.14},
            "open_positions": [],
        },
        "technical": {
            "direction": "neutral",
            "trend": {"m15": "neutral", "h1": "neutral", "h4": "neutral", "d1": "neutral"},
            "indicators": {"ma_cross": {"signal": "none"}, "rsi": {"h1": 51.2, "zone": "neutral"}},
            "key_levels": {"support": [154.9], "resistance": [155.8]},
        },
        "risk": {
            "risk_level": "medium",
            "kill_switch_active": False,
            "factors": [{"severity": "low", "detail": "No active local risk blocker found in fallback inputs."}],
        },
        "news": {"risk_level": "low", "reasoning": "No high-impact news evidence."},
        "sentiment": {"bias": "neutral", "reasoning": "Local sentiment is neutral."},
        "bull_case": {"thesis": "Bull case waits for a cleaner breakout.", "conviction": 0.31},
        "bear_case": {"thesis": "Bear case is limited by current range conditions.", "conviction": 0.29},
        "decision": {
            "action": "HOLD",
            "confidence": 0.64,
            "reasoning": "Advisory only.",
            "key_factors": ["Risk level medium", "Technical direction neutral"],
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "risk_reward_ratio": None,
            "position_size_suggestion": "0.01",
            "debate_summary": {
                "bull_conviction": 0.31,
                "bear_conviction": 0.29,
                "bull_thesis": "Bull case waits for a cleaner breakout.",
                "bear_thesis": "Bear case is limited by current range conditions.",
            },
        },
    }


class FakeAnalysisService:
    def __init__(self, runtime_dir=None):
        self.runtime_dir = runtime_dir

    async def run_analysis(self, symbol, timeframes):
        report = sample_report(symbol)
        report["timeframes"] = timeframes
        return report


class Mt5AiTelegramMonitorTests(unittest.TestCase):
    def test_safety_blocks_trading_and_commands(self) -> None:
        safety = monitor.monitor_safety()
        self.assertTrue(safety["advisoryOnly"])
        self.assertFalse(safety["orderSendAllowed"])
        self.assertFalse(safety["telegramCommandExecutionAllowed"])
        self.assertFalse(safety["livePresetMutationAllowed"])

    def test_default_symbol_universe_is_live_usdjpy_only(self) -> None:
        self.assertEqual(monitor.DEFAULT_SYMBOLS, "USDJPYc")

    def test_send_layer_blocks_mock_message_text(self) -> None:
        self.assertEqual(
            monitor.unsafe_advisory_message_reason("失效条件：mock decision"),
            "mock_decision_text",
        )

    def test_advisory_message_hold_returns_none(self) -> None:
        """HOLD decisions must return None (suppressed push)."""
        payload = monitor._build_render_payload(sample_report())
        msg = render("ai_advisory", payload)
        self.assertIsNone(msg)

    def test_advisory_message_buy_produces_chinese_message(self) -> None:
        """BUY decision produces a compact Chinese Shadow observation."""
        report = sample_report()
        report["decision"]["action"] = "BUY"
        report["decision"]["entry_price"] = 155.12
        report["decision"]["stop_loss"] = 154.72
        report["decision"]["take_profit"] = 155.92
        report["decision"]["risk_reward_ratio"] = 2.0
        payload = monitor._build_render_payload(report)
        msg = render("ai_advisory", payload)
        assert msg is not None
        self.assertIn("QuantGod · AI 观察", msg)
        self.assertIn("USDJPYc", msg)
        self.assertIn("偏多", msg)
        for forbidden in ("入场", "止损", "目标", "仓位", "持仓"):
            self.assertNotIn(forbidden, msg)
        self.assertLessEqual(len(msg), 700)

    def test_deepseek_insight_uses_distinct_format(self) -> None:
        """DeepSeek insight uses a compact, distinct Shadow format."""
        report = sample_report()
        report["decision"]["action"] = "BUY"
        report["deepseek_advice"] = {
            "ok": True,
            "status": "ok",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "advice": {
                "headline": "大模型判断证据偏多，可在风控确认后入场。",
                "verdict": "偏多观察",
                "signalGrade": "A 级",
                "confidencePct": "75%",
                "marketSummary": "价格向上突破，点差正常。",
                "technicalSummary": "短线偏多，M15/H1共振。",
                "bullCase": "突破压力位后延续上攻。",
                "bearCase": "上方阻力仍在，假突破风险。",
                "newsRisk": "暂无高影响新闻。",
                "sentimentPositioning": "机构偏多，散户偏空。",
                "planStatus": "等待风控确认",
                "entryZone": "155.00 – 155.20",
                "targets": ["155.60", "155.95", "156.40"],
                "defense": "154.70",
                "riskReward": "1:2.0",
                "positionAdvice": "不超过0.02手",
                "invalidation": "H1收盘跌破154.70",
                "watchPoints": ["等待新鲜证据", "观察支撑压力"],
                "riskNotes": ["不追单", "不绕过风控"],
                "executionBoundary": "仅建议，不执行交易。",
            },
        }
        payload = monitor._build_render_payload(report)
        msg = render("deepseek_insight", payload)
        assert msg is not None
        self.assertIn("QuantGod · DeepSeek 观察", msg)
        self.assertIn("结论：", msg)
        self.assertIn("原因：", msg)
        self.assertIn("下一步：", msg)
        self.assertIn("deepseek-v4-pro", msg)
        # ai_advisory prefix should NOT appear in deepseek message
        self.assertNotIn("AI 实盘建议", msg)
        self.assertLessEqual(len(msg), 700)

    def test_dedupe_waits_for_unchanged_signature(self) -> None:
        report = sample_report()
        sig = monitor.event_signature(report)
        state = {
            "symbols": {
                "USDJPYc": {
                    "signature": sig,
                    "lastNotifiedAt": "2026-05-03T00:00:00Z",
                }
            }
        }
        ok, reason = monitor.should_notify(
            state,
            symbol="USDJPYc",
            signature=sig,
            now_epoch=1777766405,
            min_interval_seconds=60,
            force=False,
        )
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("dedup_wait_"))

    def test_preview_state_never_advances_last_notified_clock(self) -> None:
        report = sample_report()
        state = monitor.update_state(
            {},
            symbol="USDJPYc",
            signature=monitor.event_signature(report),
            status="preview",
            reason="first_seen",
            report=report,
            now_iso="2026-05-03T00:00:00Z",
        )
        self.assertNotIn("lastNotifiedAt", state["symbols"]["USDJPYc"])

    def test_scan_counts_only_confirmed_gateway_delivery(self) -> None:
        def attach_buy(_args, report):
            report = dict(report)
            report["decision"] = dict(report["decision"], action="BUY", confidence=0.82)
            return report

        cases = (
            ({"ok": True, "status": "preview", "sendRequested": False, "sent": False, "deliveryOk": False}, False, 0),
            ({"ok": True, "status": "sent", "sendRequested": True, "sent": True, "deliveryOk": True}, True, 1),
        )
        for delivery, send, expected_count in cases:
            with self.subTest(send=send), tempfile.TemporaryDirectory() as tmp_dir:
                argv = [
                    "scan-once",
                    "--symbols",
                    "USDJPYc",
                    "--runtime-dir",
                    tmp_dir,
                    "--min-interval-seconds",
                    "0",
                    "--disable-journal",
                ]
                if send:
                    argv.append("--send")
                args = monitor.build_parser().parse_args(argv)
                with mock.patch.object(monitor, "AnalysisServiceV2", FakeAnalysisService), mock.patch.object(
                    monitor, "attach_deepseek_advice", side_effect=attach_buy
                ), mock.patch.object(
                    monitor, "advisory_push_gate", return_value=(True, "passed")
                ), mock.patch.object(
                    monitor, "send_or_record", return_value=delivery
                ):
                    payload = asyncio.run(monitor.scan_once(args))
                self.assertEqual(payload["summary"]["notifications"], expected_count)
                self.assertEqual(payload["deliveryAttemptedCount"], 1 if send else 0)
                self.assertEqual(payload["failedDeliveryCount"], 0)
                state = json.loads(Path(payload["statePath"]).read_text(encoding="utf-8"))
                symbol_state = state["symbols"]["USDJPYc"]
                if send:
                    self.assertIn("lastNotifiedAt", symbol_state)
                else:
                    self.assertNotIn("lastNotifiedAt", symbol_state)

    def test_scan_once_hold_skips_push_with_skipped_hold_status(self) -> None:
        """When action=HOLD, scan_once should record skipped_hold, not push."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = monitor.build_parser().parse_args(
                [
                    "scan-once",
                    "--symbols",
                    "USDJPYc",
                    "--runtime-dir",
                    tmp_dir,
                    "--env-file",
                    str(Path(tmp_dir) / ".env.telegram.local"),
                    "--min-interval-seconds",
                    "0",
                    "--no-deepseek",
                ]
            )
            env_file = Path(tmp_dir) / ".env.telegram.local"
            env_file.write_text(
                "QG_TELEGRAM_BOT_TOKEN=123456:ABCDEF\n"
                "QG_TELEGRAM_CHAT_ID=@QuardGod\n"
                "QG_TELEGRAM_PUSH_ALLOWED=0\n"
                "QG_TELEGRAM_COMMANDS_ALLOWED=0\n",
                encoding="utf-8",
            )
            with mock.patch.object(monitor, "AnalysisServiceV2", FakeAnalysisService):
                payload = asyncio.run(monitor.scan_once(args))
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dryRun"])
            # HOLD → no notifications, skipped_hold status
            self.assertEqual(payload["summary"]["notifications"], 0)
            items = payload["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["delivery"]["status"], "skipped_hold")
            latest = Path(tmp_dir) / "QuantGod_MT5AiTelegramMonitorLatest.json"
            state = Path(tmp_dir) / "QuantGod_MT5AiTelegramMonitorState.json"
            self.assertTrue(latest.exists())
            self.assertTrue(state.exists())
            self.assertEqual(
                json.loads(state.read_text())["symbols"]["USDJPYc"]["status"],
                "skipped_hold",
            )

    def test_buy_with_untrusted_evidence_is_not_pushed(self) -> None:
        report = sample_report("EURUSDc")
        report["decision"]["action"] = "BUY"
        report["decision"]["confidence"] = 0.88
        report["snapshot"]["runtimeFresh"] = False
        ok, reason = monitor.advisory_push_gate(report)
        self.assertFalse(ok)
        self.assertEqual(reason, "runtime_not_fresh")

    def test_buy_requires_real_deepseek_validation(self) -> None:
        report = sample_report("EURUSDc")
        report["decision"]["action"] = "BUY"
        report["decision"]["confidence"] = 0.88
        report["deepseek_advice"] = {"ok": False, "status": "missing_api_key"}
        ok, reason = monitor.advisory_push_gate(report)
        self.assertFalse(ok)
        self.assertEqual(reason, "deepseek_not_available")

    def test_confident_validated_report_passes_push_gate(self) -> None:
        report = sample_report("EURUSDc")
        report["decision"]["action"] = "BUY"
        report["decision"]["confidence"] = 0.82
        report["deepseek_advice"] = {
            "ok": True,
            "status": "ok",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "validation": {"status": "pass"},
            "advice": {
                "entryZone": "1.1010 - 1.1020",
                "targets": ["1.1040", "1.1060", "1.1080"],
                "defense": "1.0980",
                "riskReward": "1:2.0",
                "invalidation": "跌破 1.0980 后失效",
            },
        }
        report["advisory_fusion"] = {"finalAction": "WATCH_LONG", "agreement": "local_and_deepseek_compatible"}
        ok, reason = monitor.advisory_push_gate(report, min_confidence_pct=70)
        self.assertTrue(ok, reason)
        payload = monitor._build_render_payload(report)
        self.assertEqual(payload["decision"]["entryZone"], "1.1010 - 1.1020")
        self.assertEqual(payload["decision"]["targets"], ["1.1040", "1.1060", "1.1080"])
        self.assertEqual(payload["decision"]["stopLoss"], "1.0980")
        self.assertEqual(payload["decision"]["riskReward"], "1:2.0")

    def test_validated_hold_can_render_observation_summary(self) -> None:
        report = sample_report("USDJPYc")
        report["decision"]["action"] = "HOLD"
        report["deepseek_advice"] = {
            "ok": True,
            "status": "ok",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "validation": {"status": "pass"},
            "advice": {
                "verdict": "观望，不开新仓",
                "headline": "多空证据未共振，等待更清晰的入场条件。",
                "confidencePct": "62%",
                "watchPoints": ["等待 M15/H1 同向", "确认点差和新闻过滤正常"],
            },
        }
        report["advisory_fusion"] = {"finalAction": "HOLD", "agreement": "local_and_deepseek_hold"}
        ok, reason = monitor.observation_push_gate(report)
        self.assertTrue(ok, reason)
        message = monitor.build_observation_message(report, gate_reason="action_hold")
        self.assertIn("QuantGod · AI 观察", message)
        self.assertIn("本轮只保留观察证据", message)
        self.assertIn("无执行通道", message)
        self.assertLessEqual(len(message), 700)

    def test_deepseek_and_observation_scrub_adversarial_execution_prose(self) -> None:
        report = sample_report("USDJPYc")
        report["decision"]["action"] = "BUY"
        report["deepseek_advice"] = {
            "ok": True,
            "status": "ok",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "validation": {"status": "pass"},
            "advice": {
                "marketSummary": "Buy at 155.10, SL 154.80, TP 155.80, 2 lots, leverage 20x, long now.",
                "bullCase": "立即下单买入，止损 154.80，止盈 155.80。",
                "bearCase": "目标 156.00，仓位 2 手。",
            },
        }
        rendered = render("deepseek_insight", monitor._build_render_payload(report))
        assert rendered is not None

        report["decision"]["action"] = "HOLD"
        report["deepseek_advice"]["advice"].update(
            {
                "verdict": "立即开仓做多",
                "headline": "Buy at 155.10 with SL 154.80 and TP 155.80",
                "watchPoints": ["建议买入 2 lots，leverage 20x"],
            }
        )
        observation = monitor.build_observation_message(report, gate_reason="action_hold")
        for message in (rendered, observation):
            lowered = message.lower()
            for forbidden in (
                "buy at",
                "sl 154",
                "tp 155",
                "lots",
                "leverage",
                "long now",
                "立即下单",
                "开仓",
                "止损",
                "止盈",
                "目标",
                "仓位",
                "买入",
            ):
                self.assertNotIn(forbidden, lowered)
            self.assertIn("交易计划细节", message)
            self.assertIn("隐藏", message)

        self.assertEqual(
            monitor.unsafe_advisory_message_reason("Buy at 155.10; SL 154.80; TP 155.80"),
            "execution_language_blocked",
        )

    def test_build_render_payload_extracts_decision_fields(self) -> None:
        """_build_render_payload correctly maps report fields to renderer payload."""
        report = sample_report()
        report["decision"]["action"] = "BUY"
        report["decision"]["confidence"] = 0.72
        payload = monitor._build_render_payload(report)
        self.assertEqual(payload["symbol"], "USDJPYc")
        self.assertEqual(payload["decision"]["action"], "BUY")
        self.assertEqual(payload["decision"]["confidence"], 0.72)

    def test_build_render_payload_integration_quality(self) -> None:
        """_build_render_payload produces well-formed output for all renderers."""
        report = sample_report()
        report["decision"]["action"] = "BUY"
        report["decision"]["confidence"] = 0.72
        report["decision"]["entry_price"] = 155.12
        report["decision"]["stop_loss"] = 154.72
        report["decision"]["take_profit"] = 155.92
        report["decision"]["risk_reward_ratio"] = 2.0
        report["symbol"] = "USDJPYc"

        payload = monitor._build_render_payload(report)

        # ── Decision fields are present and well-formed ─
        dec = payload["decision"]
        self.assertIn(dec["action"], ("BUY", "SELL", "HOLD"))
        self.assertIsInstance(dec["confidence"], (int, float))
        self.assertIn("级", dec["signalGrade"])  # Chinese label present
        self.assertIsInstance(dec["signalGrade"], str)
        # entryZone is not a fake interval — single entry price or proper zone
        self.assertIsInstance(dec["entryZone"], str)
        self.assertNotEqual(dec["entryZone"], "--")
        # stopLoss formatted with proper precision (not stripped)
        self.assertIsInstance(dec["stopLoss"], str)
        # stopLossPips computed when entry and stop loss are present
        self.assertIsNotNone(dec["stopLossPips"])
        self.assertIsInstance(dec["stopLossPips"], int)
        self.assertGreater(dec["stopLossPips"], 0)
        # targets list
        self.assertIsInstance(dec["targets"], list)
        # targets from report with take_profit
        self.assertGreater(len(dec["targets"]), 0)
        # riskReward
        self.assertEqual(dec["riskReward"], 2.0)

        # ── Payload renders without error for both kinds ─
        from notify.messages import render

        ai_result = render("ai_advisory", payload)
        self.assertIsNotNone(ai_result)
        self.assertIn("QuantGod · AI 观察", str(ai_result))
        self.assertIn("USDJPYc", str(ai_result))
        self.assertIn("偏多", str(ai_result))

        # deepseek_insight kind (even without deepseek_advice — graceful)
        ds_result = render("deepseek_insight", payload)
        self.assertIsNotNone(ds_result)
        self.assertIn("QuantGod · DeepSeek 观察", str(ds_result))

    def test_build_render_payload_with_deepseek_advice_targets(self) -> None:
        """When DeepSeek advice provides targets, they take precedence."""
        report = sample_report("USDJPYc")
        report["decision"]["action"] = "BUY"
        report["decision"]["entry_price"] = 155.12
        report["decision"]["stop_loss"] = 154.72
        report["decision"]["take_profit"] = None  # No single target
        report["deepseek_advice"] = {
            "ok": True,
            "status": "ok",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "advice": {
                "headline": "DeepSeek signal",
                "targets": ["155.60", "155.95", "156.40"],
                "entryZone": "155.00 – 155.20",
                "stopLoss": "154.70",
                "bullCase": "Bullish breakout",
                "bearCase": "Resistance holds",
                "newsRisk": "No news",
                "sentimentPositioning": "Bullish",
            },
        }
        payload = monitor._build_render_payload(report)
        dec = payload["decision"]

        # entryZone from DeepSeek advice takes priority
        self.assertEqual(dec["entryZone"], "155.00 – 155.20")
        # targets from DeepSeek advice (3 targets)
        self.assertEqual(len(dec["targets"]), 3)
        self.assertEqual(dec["targets"], ["155.60", "155.95", "156.40"])

    def test_build_render_payload_with_advisory_fusion(self) -> None:
        """advisory_fusion agreement surfaces in renderer output."""
        report = sample_report("EURUSDc")
        report["decision"]["action"] = "SELL"
        report["decision"]["entry_price"] = 1.0850
        report["decision"]["stop_loss"] = 1.0890
        report["decision"]["take_profit"] = 1.0800
        report["advisory_fusion"] = {
            "agreement": "一致",
            "finalAction": "SELL",
            "ok": True,
        }
        payload = monitor._build_render_payload(report)

        # advisory_fusion passed through
        self.assertEqual(payload["advisory_fusion"]["agreement"], "一致")

        from notify.messages import render

        msg = render("ai_advisory", payload)
        self.assertIsNotNone(msg)
        self.assertIn("共识 一致", str(msg))


if __name__ == "__main__":
    unittest.main()
