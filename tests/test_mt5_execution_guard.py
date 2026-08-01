from collections import Counter
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise AssertionError(f"unterminated function: {signature}")


class Mt5ExecutionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA_PATH.read_text(encoding="utf-8-sig")

    def test_live_mode_requires_auto_trading_and_disables_shadow_and_readonly(self):
        body = function_body(self.source, "bool IsPilotLiveMode()")
        compact = re.sub(r"\s+", "", body)
        self.assertIn(
            "return(EnablePilotAutoTrading&&!ShadowMode&&!ReadOnlyMode);",
            compact,
        )

        blocker = function_body(self.source, "string LiveTradePermissionBlocker(string symbol)")
        self.assertIn('if(ShadowMode)\n      return "SHADOW_MODE";', blocker)
        self.assertIn('if(ReadOnlyMode)\n      return "READ_ONLY_MODE";', blocker)
        self.assertIn(
            'if(!EnablePilotAutoTrading)\n      return "PILOT_AUTO_TRADING_DISABLED";',
            blocker,
        )

    def test_dashboard_trade_flags_use_the_hard_live_mode_gate(self):
        self.assertIn(
            "bool tradePermissionsAllowed = (IsPilotLiveMode() && connected && terminalTradeAllowed && programTradeAllowed && accountTradeAllowed && accountExpertTradeAllowed && focusSymbolTradeAllowed);",
            self.source,
        )
        self.assertIn(
            "bool tradeAllowed = tradePermissionsAllowed && !g_pilotKillSwitch && !newsTradingBlocked && !startupGuardActive;",
            self.source,
        )
        self.assertIn('JsonBool(tradeAllowed) + ",\\r\\n";', self.source)
        self.assertNotIn('JsonBool(!ReadOnlyMode) + ",\\r\\n";', self.source)

    def test_every_mutating_entry_point_has_a_fail_closed_guard(self):
        signatures = (
            "bool SendPilotMarketOrder(string symbol, int direction, double slPrice, double tpPrice, string strategyKey)",
            "bool ClosePositionWithExecutionGuard(ulong ticket)",
            "void ClosePilotPositions(const string reason)",
            "bool ModifyPilotPositionStops(ulong ticket, string symbol, double slPrice, double tpPrice)",
            "void ManageDemotedPilotRouteExits()",
            "void ManagePilotRsiTimeStops()",
            "void ManagePilotRsiFailFastStops()",
            "void ManagePilotBreakevenStops()",
            "void ManageManualSafetyGuard()",
            "void RunPilotExecutionLoop()",
        )
        for signature in signatures:
            with self.subTest(signature=signature):
                body = function_body(self.source, signature)
                self.assertIn("if(!IsPilotLiveMode())", body)

    def test_broker_mutations_are_confined_to_guarded_choke_points(self):
        methods = Counter(
            re.findall(r"\bg_trade\.(Buy|Sell|PositionClose)\s*\(", self.source)
        )
        self.assertEqual(methods, Counter({"Buy": 1, "Sell": 1, "PositionClose": 1}))
        self.assertEqual(len(re.findall(r"\bOrderSend\s*\(", self.source)), 1)
        self.assertNotRegex(
            self.source,
            r"\b(OrderSendAsync|OrderDelete|OrderModify)\s*\(|TRADE_ACTION_(DEAL|PENDING|MODIFY|REMOVE)",
        )

        send_body = function_body(
            self.source,
            "bool SendPilotMarketOrder(string symbol, int direction, double slPrice, double tpPrice, string strategyKey)",
        )
        self.assertIn("g_trade.Buy(", send_body)
        self.assertIn("g_trade.Sell(", send_body)

        close_body = function_body(self.source, "bool ClosePositionWithExecutionGuard(ulong ticket)")
        self.assertIn("g_trade.PositionClose(ticket)", close_body)

        modify_body = function_body(
            self.source,
            "bool ModifyPilotPositionStops(ulong ticket, string symbol, double slPrice, double tpPrice)",
        )
        self.assertIn("request.action = TRADE_ACTION_SLTP;", modify_body)
        self.assertIn("OrderSend(request, result)", modify_body)

    def test_on_tick_does_not_enter_position_management_outside_live_mode(self):
        body = function_body(self.source, "void OnTick()")
        self.assertRegex(
            body,
            re.compile(
                r"if\(IsPilotLiveMode\(\)\)\s*\{\s*"
                r"ManagePilotBreakevenStops\(\);\s*"
                r"ManagePilotRsiFailFastStops\(\);\s*"
                r"if\(g_pilotKillSwitch && PilotCloseOnKillSwitch\)\s*"
                r"ClosePilotPositions\(g_pilotKillReason\);\s*\}",
                re.MULTILINE,
            ),
        )


if __name__ == "__main__":
    unittest.main()
