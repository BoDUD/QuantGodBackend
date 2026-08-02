from __future__ import annotations

import unittest

from tools.automation_chain.telegram_text import build_automation_telegram_text
from tools.daily_autopilot_v2.telegram_text import daily_autopilot_v2_to_chinese_text
from tools.strategy_ga.telegram_text import ga_to_chinese_text
from tools.telegram_digest import (
    EXECUTION_DETAIL_REDACTION,
    MAX_DIGEST_CHARS,
    SHADOW_FOOTER,
    build_digest,
    contains_execution_language,
    sanitize_execution_language,
)
from tools.telegram_gateway_ops.telegram_text import gateway_ops_to_chinese_text
from tools.usdjpy_autonomous_agent.telegram_text import autonomous_agent_to_chinese_text

FORBIDDEN_OPERATOR_WORDS = (
    "AI 实盘建议",
    "实盘车道",
    "建议阶段仓位",
    "Live 阶段",
    "实盘执行质量",
    "MICRO_LIVE",
    "LIVE_LIMITED",
    "OrderSend",
)


class TelegramDigestTests(unittest.TestCase):
    def assert_digest(self, text: str) -> None:
        self.assertLessEqual(len(text), MAX_DIGEST_CHARS)
        self.assertIn("结论：", text)
        self.assertIn("下一步：", text)
        self.assertTrue(text.endswith(SHADOW_FOOTER))
        for marker in FORBIDDEN_OPERATOR_WORDS:
            self.assertNotIn(marker, text)

    def test_template_keeps_footer_when_inputs_are_very_long(self) -> None:
        text = build_digest(
            title="状态" * 100,
            level="warning",
            conclusion="结论" * 500,
            metrics=["指标" * 500] * 8,
            reasons=["原因" * 500] * 8,
            next_action="下一步" * 500,
            generated_at="2026-08-02T00:00:00Z",
        )
        self.assert_digest(text)

    def test_daily_digest_is_short_and_shadow_only(self) -> None:
        text = daily_autopilot_v2_to_chinese_text(
            {
                "symbol": "USDJPYc",
                "generatedAtIso": "2026-08-02T00:00:00Z",
                "morningPlan": {
                    "liveLane": {"stage": "TESTER_ONLY", "stageZh": "只进测试器验证"},
                    "mt5ShadowLane": {"summary": {"routeCount": 18}},
                    "spreadGate": {"spreadPips": 2.7},
                },
                "historyProductionStatus": {
                    "promotionGateStatus": "BLOCKED",
                    "reasonZh": "历史 K 线已经过期，需要刷新。",
                },
                "executionConsistencyReview": {"parityGateStatus": "PASS"},
                "gaReview": {"currentGeneration": 533, "eliteCount": 0, "blockedCandidates": 16},
            }
        )
        self.assert_digest(text)
        self.assertIn("历史数据", text)
        self.assertIn("GA 第 533 代", text)
        self.assertIn("合格策略 0", text)

    def test_all_managed_formatters_follow_the_same_contract(self) -> None:
        messages = [
            ga_to_chinese_text(
                {
                    "status": {"currentGeneration": 3, "populationSize": 16, "eliteCount": 0, "blockedCandidates": 16},
                    "generation": {"createdAt": "2026-08-02T00:00:00Z"},
                    "blockers": {"summary": [{"blockerCode": "DATA", "reasonZh": "历史数据过期", "count": 16}]},
                }
            ),
            autonomous_agent_to_chinese_text(
                {
                    "symbol": "USDJPYc",
                    "stage": "TESTER_ONLY",
                    "generatedAtIso": "2026-08-02T00:00:00Z",
                    "promotionDecision": {"candidates": []},
                    "currentPatch": {"rollback": {"hardBlockers": []}},
                    "lanes": {"mt5Shadow": {"summary": {"routeCount": 2}}},
                }
            ),
            build_automation_telegram_text({"symbols": ["USDJPYc"]}),
            gateway_ops_to_chinese_text(
                {
                    "pushAllowed": False,
                    "pendingCount": 0,
                    "deliveryObservability": {"stateZh": "等待新报告"},
                }
            ),
        ]
        for message in messages:
            with self.subTest(message=message.splitlines()[0]):
                self.assert_digest(message)

    def test_adversarial_execution_language_is_redacted(self) -> None:
        samples = (
            "Buy at 155.10",
            "SL 154.80",
            "TP 155.80",
            "2 lots",
            "leverage 20x",
            "long now",
            "立即下单",
            "开仓做多",
            "止损 154.80",
            "止盈 155.80",
            "目标 156.00",
            "仓位 0.02 手",
            "建议买入",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(contains_execution_language(sample))
                self.assertEqual(sanitize_execution_language(sample), EXECUTION_DETAIL_REDACTION)


if __name__ == "__main__":
    unittest.main()
