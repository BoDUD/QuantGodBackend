import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load_module(name):
    path = TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker = load_module("mt5_pending_order_worker")
platform = load_module("mt5_platform_store")


class Mt5PendingWorkerAndPlatformTests(unittest.TestCase):
    def test_platform_database_uses_wal_busy_timeout_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / platform.DB_NAME
            connection = platform.connect_db(database)
            try:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertGreaterEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 1)
            finally:
                connection.close()

    def write_intents(self, runtime: Path):
        payload = {
            "mode": "TEST_INTENTS",
            "intents": [
                {
                    "sourceCandidateId": "candidate-1",
                    "route": "MA_Cross",
                    "symbol": "EURUSDc",
                    "side": "buy",
                    "orderType": "buy_limit",
                    "lots": 0.01,
                    "entryPrice": 1.099,
                    "stopLoss": 1.094,
                    "takeProfit": 1.109,
                    "dryRun": True,
                }
            ],
        }
        path = runtime / worker.INTENTS_NAME
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_pending_worker_dry_run_writes_ledgers_and_skips_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self.write_intents(runtime)

            first = worker.run_worker(runtime, force_dry_run=True)
            self.assertTrue(first["ok"])
            self.assertEqual(first["summary"]["accepted"], 1)
            self.assertTrue((runtime / worker.LEDGER_NAME).exists())

            second = worker.run_worker(runtime, force_dry_run=True)
            self.assertTrue(second["ok"])
            self.assertEqual(second["summary"]["skipped"], 1)

    def test_platform_store_syncs_trading_and_pending_audit_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self.write_intents(runtime)
            worker.run_worker(runtime, force_dry_run=True)

            state = platform.run(
                runtime,
                operator={"operatorId": "owner", "displayName": "Owner", "role": "admin", "status": "active"},
            )
            self.assertTrue(state["ok"])
            self.assertEqual(state["summary"]["operators"], 1)
            self.assertGreaterEqual(state["summary"]["auditEvents"], 1)
            self.assertTrue((runtime / platform.DB_NAME).exists())
            self.assertTrue((runtime / platform.OUTPUT_NAME).exists())
            self.assertFalse(state["safety"]["orderSendAllowed"])

    def test_platform_store_profile_strategy_queue_contract_is_dry_run_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)

            credential_state = platform.run(
                runtime,
                endpoint="credential",
                payload={
                    "credentialId": "hfm-live",
                    "displayName": "HFM Live",
                    "accountLogin": 90000001,
                    "server": "SyntheticBroker-Demo",
                    "terminalPath": r"C:\Program Files\HFM Metatrader 5\terminal64.exe",
                    "password": "do-not-store-me",
                    "passwordEnvVar": "QG_MT5_HFM_PASSWORD",
                },
            )
            self.assertTrue(credential_state["ok"])
            self.assertFalse(credential_state["safety"]["orderSendAllowed"])
            self.assertFalse(credential_state["safety"]["rawPasswordStorageAllowed"])
            self.assertTrue(credential_state["action"]["credential"]["rawSecretRejected"])
            self.assertFalse(credential_state["action"]["credential"]["rawSecretStored"])

            strategy_state = platform.run(
                runtime,
                endpoint="strategy",
                payload={
                    "strategyId": "MA_EURUSD_M15",
                    "route": "MA_Cross",
                    "symbol": "EURUSDc",
                    "timeframe": "M15",
                    "executionMode": "live",
                    "credentialId": "hfm-live",
                },
            )
            self.assertEqual(strategy_state["action"]["strategy"]["executionMode"], "dry_run")
            self.assertEqual(strategy_state["action"]["strategy"]["canonicalSymbol"], "EURUSD")

            queued = platform.run(
                runtime,
                endpoint="enqueue",
                payload={
                    "strategyId": "MA_EURUSD_M15",
                    "route": "MA_Cross",
                    "symbol": "EURUSDc",
                    "side": "buy",
                    "orderType": "buy_limit",
                    "lots": 0.01,
                    "price": 1.099,
                },
            )
            self.assertEqual(queued["summary"]["pendingOrders"], 1)
            self.assertEqual(queued["summary"]["queuedOrders"], 1)
            self.assertTrue(queued["action"]["pendingOrder"]["dryRunRequired"])

            dispatched = platform.run(runtime, endpoint="dispatch", payload={"maxOrders": 1})
            self.assertEqual(dispatched["action"]["dispatch"]["processed"], 1)
            self.assertEqual(dispatched["action"]["dispatch"]["accepted"], 1)
            self.assertFalse(dispatched["safety"]["dispatchLiveAllowed"])
            self.assertEqual(dispatched["pendingOrders"][0]["status"], "dry_run_accepted")

            db = sqlite3.connect(runtime / platform.DB_NAME)
            try:
                raw_config = db.execute("SELECT encrypted_config FROM qd_exchange_credentials WHERE id='hfm-live'").fetchone()[0]
                self.assertNotIn("do-not-store-me", raw_config)
                self.assertIn("[REDACTED]", raw_config)
                dry_run_required = db.execute("SELECT dry_run_required FROM pending_orders").fetchone()[0]
                self.assertEqual(dry_run_required, 1)
            finally:
                db.close()

    def test_platform_store_env_var_reference_is_not_raw_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = platform.run(
                runtime,
                endpoint="credential",
                payload={
                    "credentialId": "hfm-env-only",
                    "accountLogin": 123,
                    "server": "HFMarkets",
                    "passwordEnvVar": "QG_MT5_HFM_PASSWORD",
                },
            )
            self.assertFalse(state["action"]["credential"]["rawSecretRejected"])
            self.assertEqual(state["credentials"][0]["passwordEnvVar"], "QG_MT5_HFM_PASSWORD")

    def test_platform_dispatch_preserves_route_from_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            platform.run(
                runtime,
                endpoint="enqueue",
                payload={
                    "strategyId": "MA_EURUSD_M15",
                    "route": "MA_Cross",
                    "symbol": "EURUSDc",
                    "side": "buy",
                    "orderType": "buy_limit",
                    "lots": 0.01,
                    "price": 1.099,
                },
            )
            dispatched = platform.run(runtime, endpoint="dispatch", payload={"maxOrders": 1})
            self.assertEqual(dispatched["action"]["dispatch"]["rows"][0]["status"], "dry_run_accepted")

            db = sqlite3.connect(runtime / platform.DB_NAME)
            try:
                route = db.execute(
                    "SELECT route FROM audit_events WHERE source='mt5_platform_store' AND action='dispatch' ORDER BY event_time_iso DESC LIMIT 1"
                ).fetchone()[0]
                self.assertEqual(route, "MA_Cross")
            finally:
                db.close()

    def test_platform_store_reconcile_and_symbol_catalog_use_canonical_pooling(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            state = platform.run(
                runtime,
                endpoint="reconcile",
                payload={
                    "positions": [
                        {
                            "ticket": 1001,
                            "symbol": "EURUSDc",
                            "type": "buy",
                            "volume": 0.01,
                            "price_open": 1.1,
                            "price_current": 1.102,
                            "profit": 2.0,
                        }
                    ],
                    "orders": [
                        {
                            "ticket": 2001,
                            "symbol": "USDJPY.raw",
                            "type": "sell_limit",
                            "volume_current": 0.01,
                            "price_open": 151.5,
                        }
                    ],
                },
            )
            self.assertEqual(state["action"]["reconcile"]["positionsSynced"], 1)
            self.assertEqual(state["action"]["reconcile"]["ordersSynced"], 1)
            self.assertEqual(state["positions"][0]["canonicalSymbol"], "EURUSD")
            self.assertIn("highestPrice", state["positions"][0])
            self.assertIn("pnlPercent", state["positions"][0])
            self.assertEqual(state["pendingOrders"][0]["canonicalSymbol"], "USDJPY")
            self.assertFalse(state["safety"]["symbolSelectAllowed"])

            symbols_state = platform.run(
                runtime,
                endpoint="symbols",
                payload={
                    "mappings": [
                        {"brokerSymbol": "EURUSDc", "canonicalSymbol": "EURUSD", "assetClass": "Forex", "marketCategory": "Forex", "brokerSuffix": "c"},
                        {"brokerSymbol": "EURUSD.raw", "canonicalSymbol": "EURUSD", "assetClass": "Forex", "marketCategory": "Forex", "brokerSuffix": ".raw"},
                        {"brokerSymbol": "XAUUSD.synthetic", "canonicalSymbol": "XAUUSD", "assetClass": "Forex", "marketCategory": "Forex", "brokerSuffix": ".synthetic"},
                        {"brokerSymbol": "US30.synthetic", "canonicalSymbol": "US30", "assetClass": "Indices", "marketCategory": "index_cfd", "brokerSuffix": ".synthetic"},
                    ]
                },
            )
            self.assertEqual(symbols_state["action"]["symbols"]["synced"], 2)
            self.assertGreaterEqual(symbols_state["summary"]["symbolCatalog"], 2)
            self.assertIn("EURUSD", {row["canonicalSymbol"] for row in symbols_state["symbolCatalog"]})
            self.assertIn("standardLot", symbols_state["symbolCatalog"][0])
            self.assertTrue(symbols_state["symbolCatalog"])
            self.assertTrue(all(row["marketCategory"].lower() == "forex" for row in symbols_state["symbolCatalog"]))
            self.assertNotIn(
                "XAUUSD.synthetic",
                {row["brokerSymbol"] for row in symbols_state["symbolCatalog"]},
            )
            self.assertNotIn(
                "US30.synthetic",
                {row["brokerSymbol"] for row in symbols_state["symbolCatalog"]},
            )

            db = sqlite3.connect(runtime / platform.DB_NAME)
            try:
                non_forex_count = db.execute(
                    "SELECT COUNT(*) FROM qd_market_symbols WHERE lower(COALESCE(market_category, '')) <> 'forex'"
                ).fetchone()[0]
                self.assertEqual(non_forex_count, 0)
            finally:
                db.close()

    def test_platform_db_worker_processes_pending_orders_and_records_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            platform.run(
                runtime,
                endpoint="enqueue",
                payload={
                    "strategyId": "MA_EURUSD_M15",
                    "route": "MA_Cross",
                    "symbol": "EURUSDc",
                    "side": "buy",
                    "orderType": "buy_limit",
                    "lots": 0.01,
                    "price": 1.099,
                },
            )

            worked = platform.run(runtime, endpoint="worker-run", payload={"maxOrders": 1, "dryRun": True})
            self.assertEqual(worked["action"]["worker"]["processed"], 1)
            self.assertEqual(worked["action"]["worker"]["dryRunAccepted"], 1)
            self.assertEqual(worked["pendingOrders"][0]["status"], "dry_run_accepted")
            self.assertGreaterEqual(worked["summary"]["taskRuns"], 1)
            self.assertGreaterEqual(len(worked["taskRuns"]), 1)
            self.assertFalse(worked["safety"]["dispatchLiveAllowed"])


if __name__ == "__main__":
    unittest.main()
