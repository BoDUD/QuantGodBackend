import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "mt5_trading_client.py"
SPEC = importlib.util.spec_from_file_location("mt5_trading_client", MODULE_PATH)
client = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(client)


TerminalInfo = namedtuple(
    "TerminalInfo",
    "connected trade_allowed dlls_allowed name company path data_path commondata_path codepage maxbars",
)
AccountInfo = namedtuple(
    "AccountInfo",
    "login server name currency company balance equity profit margin margin_free margin_level leverage trade_allowed trade_expert",
)
PositionInfo = namedtuple(
    "PositionInfo",
    "ticket identifier symbol type volume price_open price_current sl tp profit swap magic comment time",
)
TickInfo = namedtuple("TickInfo", "bid ask last volume time")
OrderSendResult = namedtuple("OrderSendResult", "retcode order comment")


class FakeMt5:
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    ORDER_TIME_GTC = 0
    ORDER_TIME_SPECIFIED = 2
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008

    def __init__(self):
        self.order_send_calls = []
        self.login_calls = []

    def terminal_info(self):
        return TerminalInfo(True, True, False, "Fake HFM MT5", "Fake Broker", "C:\\MT5", "C:\\MT5", "C:\\Common", 65001, 100000)

    def account_info(self):
        return AccountInfo(123456, "Fake-Live", "Trader", "USC", "Fake Broker", 10000, 10000, 0, 0, 10000, 0, 1000, True, True)

    def positions_get(self):
        return [
            PositionInfo(777, 777, "EURUSDc", self.POSITION_TYPE_BUY, 0.01, 1.1, 1.101, 1.09, 1.12, 1.0, 0.0, 520001, "QG", 1777389974)
        ]

    def orders_get(self):
        return []

    def symbol_info_tick(self, symbol):
        return TickInfo(1.1001, 1.1003, 1.1002, 100, 1777389999)

    def order_send(self, request):
        self.order_send_calls.append(request)
        retcode = self.TRADE_RETCODE_PLACED if request.get("action") == self.TRADE_ACTION_PENDING else self.TRADE_RETCODE_DONE
        return OrderSendResult(retcode, 987654, "accepted")

    def login(self, **request):
        self.login_calls.append(request)
        return True

    def last_error(self):
        return (1, "Success")


class Mt5TradingClientTests(unittest.TestCase):
    def write_config(self, runtime: Path, **overrides):
        config = {**client.DEFAULT_CONFIG, **overrides}
        path = runtime / client.DEFAULT_CONFIG_NAME
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def write_lock(self, runtime: Path, **overrides):
        lock = {
            "lockId": "lock-test",
            "expiresAtIso": "2099-01-01T00:00:00Z",
            "accountLogin": 123456,
            "server": "Fake-Live",
            "mode": "DASHBOARD_TICKET_OPS",
            "allowedActions": ["order", "close", "cancel", "login"],
            "allowedRoutes": ["MA_Cross"],
            "allowedCanonicalSymbols": ["EURUSD"],
            "maxOrdersPerDay": 5,
            "maxLotsPerOrder": 0.01,
            "operator": "unit-test",
            **overrides,
        }
        path = runtime / "auth_lock.json"
        path.write_text(json.dumps(lock), encoding="utf-8")
        return path

    def test_every_mutating_endpoint_is_blocked_without_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            fake = FakeMt5()
            request = {
                "profileId": "legacy-live",
                "accountLogin": 123456,
                "server": "Fake-Live",
                "password": "must-not-be-read",
                "route": "MA_Cross",
                "symbol": "EURUSDc",
                "side": "buy",
                "orderType": "buy",
                "lots": 0.01,
                "ticket": 777,
                "dryRun": False,
            }

            for endpoint in sorted(client.MUTATING_ENDPOINTS):
                with self.subTest(endpoint=endpoint):
                    result = client.execute_endpoint(
                        endpoint,
                        request,
                        runtime_dir=runtime,
                        mt5=fake,
                    )
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["status"], "BLOCKED")
                    self.assertEqual(result["decision"], "EXECUTION_LANE_REMOVED")
                    self.assertEqual(result["reason"], client.EXECUTION_LANE_REMOVED_REASON)
                    self.assertTrue(result["safety"]["readOnly"])
                    self.assertFalse(result["safety"]["executionLaneExists"])
                    self.assertFalse(result["safety"]["orderSendAllowed"])
                    self.assertFalse(result["safety"]["closeAllowed"])
                    self.assertFalse(result["safety"]["cancelAllowed"])
                    self.assertFalse(result["safety"]["loginAllowed"])
                    self.assertFalse(result["safety"]["mutatesMt5"])

            self.assertEqual(fake.order_send_calls, [])
            self.assertEqual(fake.login_calls, [])
            self.assertFalse((runtime / client.AUDIT_LEDGER_NAME).exists())
            self.assertFalse((runtime / client.DEFAULT_PROFILES_NAME).exists())

    def test_all_legacy_gates_open_still_blocks_dispatch_and_direct_function_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            lock_path = self.write_lock(runtime)
            config_path = self.write_config(
                runtime,
                tradingEnabled=True,
                dryRun=False,
                killSwitch=False,
                ownerMode="DASHBOARD_TICKET_OPS",
                requireEnvEnable=False,
                signatureRequired=False,
                allowDashboardMarketOrders=True,
                allowDashboardPendingOrders=True,
                allowDashboardClose=True,
                allowDashboardCancel=True,
                allowLogin=True,
                authLockPath=str(lock_path),
                maxPortfolioLots=0.03,
                maxTotalLotsPerCanonical=0.03,
                maxOrdersPerRouteSymbolDay=5,
            )
            config = client.load_config(runtime, config_path)
            fake = FakeMt5()
            request = {
                "endpoint": "order",
                "route": "MA_Cross",
                "symbol": "EURUSDc",
                "side": "buy",
                "orderType": "buy",
                "lots": 0.01,
                "ticket": 777,
                "accountLogin": 123456,
                "server": "Fake-Live",
                "password": "must-not-be-read",
                "dryRun": False,
            }
            forged_live_state = {
                "dryRun": False,
                "liveAllowed": True,
                "decision": "LIVE_ALLOWED",
                "reasons": [],
                "authLock": {"ok": True},
                "safety": {"orderSendAllowed": True},
            }

            dispatch = client.execute_endpoint(
                "order",
                request,
                runtime_dir=runtime,
                config_path=config_path,
                mt5=fake,
            )
            self.assertEqual(dispatch["decision"], "EXECUTION_LANE_REMOVED")

            direct_calls = {
                "login": client.execute_login,
                "order": client.execute_order,
                "close": client.execute_close,
                "cancel": client.execute_cancel,
            }
            for endpoint, function in direct_calls.items():
                with self.subTest(endpoint=endpoint):
                    result = function(
                        runtime,
                        config,
                        request,
                        forged_live_state,
                        fake,
                        True,
                    )
                    self.assertEqual(result["decision"], "EXECUTION_LANE_REMOVED")
                    self.assertFalse(result["safety"]["executionLaneExists"])
                    self.assertFalse(result["safety"]["orderSendAllowed"])

            state = client.control_state(config, request, fake.account_info()._asdict(), fake, runtime)
            self.assertFalse(state["liveAllowed"])
            self.assertEqual(state["decision"], "BLOCKED")
            self.assertIn(client.EXECUTION_LANE_REMOVED_REASON, state["reasons"])
            self.assertEqual(fake.order_send_calls, [])
            self.assertEqual(fake.login_calls, [])
            self.assertFalse((runtime / client.AUDIT_LEDGER_NAME).exists())

    def test_cli_mutation_returns_nonzero_even_when_legacy_environment_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            config_path = self.write_config(
                runtime,
                tradingEnabled=True,
                dryRun=False,
                killSwitch=False,
                ownerMode="DASHBOARD_TICKET_OPS",
                requireEnvEnable=False,
                signatureRequired=False,
                allowDashboardMarketOrders=True,
            )
            env = {**os.environ, "QG_MT5_TRADING_ENABLED": "1"}
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--endpoint",
                    "order",
                    "--runtime-dir",
                    str(runtime),
                    "--config",
                    str(config_path),
                    "--payload-json",
                    json.dumps({"symbol": "EURUSDc", "side": "buy", "lots": 0.01, "dryRun": False}),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 2, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["decision"], "EXECUTION_LANE_REMOVED")
            self.assertFalse(result["safety"]["orderSendAllowed"])
            self.assertFalse((runtime / client.AUDIT_LEDGER_NAME).exists())

    def test_read_only_status_and_profile_reads_remain_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            fake = FakeMt5()

            status = client.execute_endpoint("status", {}, runtime_dir=runtime, mt5=fake)
            profiles = client.execute_endpoint("profiles", {}, runtime_dir=runtime)

            self.assertTrue(status["ok"])
            self.assertEqual(status["status"], "EXECUTION_LANE_REMOVED")
            self.assertEqual(status["account"]["login"], 123456)
            self.assertFalse(status["safety"]["executionLaneExists"])
            self.assertTrue(profiles["ok"])
            self.assertEqual(profiles["profiles"]["profiles"], [])
            self.assertFalse((runtime / client.DEFAULT_PROFILES_NAME).exists())

    def test_retired_client_source_contains_no_broker_mutation_call(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(".order_send(", source)
        self.assertNotRegex(source, r"\.login\s*\(")


if __name__ == "__main__":
    unittest.main()
