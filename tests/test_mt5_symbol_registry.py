import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "mt5_symbol_registry.py"
SPEC = importlib.util.spec_from_file_location("mt5_symbol_registry", MODULE_PATH)
registry = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(registry)


class Mt5SymbolRegistryTests(unittest.TestCase):
    def test_forex_suffix_maps_to_canonical_symbol(self):
        row = registry.normalize_symbol_row(
            {
                "name": "EURUSDc",
                "description": "Euro vs US Dollar (Cent)",
                "path": "ForexCent\\EURUSDc",
                "currencyBase": "EUR",
                "currencyProfit": "USD",
                "digits": 5,
                "point": 0.00001,
                "volumeMin": 0.01,
                "volumeStep": 0.01,
            }
        )
        self.assertEqual(row["canonicalSymbol"], "EURUSD")
        self.assertEqual(row["brokerSuffix"], "c")
        self.assertEqual(row["assetClass"], "Forex")
        self.assertEqual(row["baseCurrency"], "EUR")
        self.assertEqual(row["quoteCurrency"], "USD")

    def test_raw_suffix_and_jpy_pair(self):
        row = registry.normalize_symbol_row(
            {
                "name": "USDJPY.raw",
                "description": "US Dollar vs Japanese Yen",
                "path": "Forex\\USDJPY.raw",
                "currency_base": "USD",
                "currency_profit": "JPY",
            }
        )
        self.assertEqual(row["canonicalSymbol"], "USDJPY")
        self.assertEqual(row["brokerSuffix"], ".raw")
        self.assertEqual(row["assetClass"], "Forex")

    def test_metal_prefix_maps_to_metals(self):
        row = registry.normalize_symbol_row(
            {
                "name": "XAUUSDc",
                "description": "Gold vs US Dollar",
                "path": "Metals\\XAUUSDc",
            }
        )
        self.assertEqual(row["canonicalSymbol"], "XAUUSD")
        self.assertEqual(row["assetClass"], "Metals")
        self.assertEqual(row["baseCurrency"], "XAU")
        self.assertEqual(row["quoteCurrency"], "USD")

    def test_metal_cross_keeps_quote_currency(self):
        row = registry.normalize_symbol_row(
            {
                "name": "XAUEURc",
                "description": "Gold vs Euro / Spot",
                "path": "Metals & Energies\\Spot\\Gold & Silver Cent\\XAUEURc",
            }
        )
        self.assertEqual(row["canonicalSymbol"], "XAUEUR")
        self.assertEqual(row["assetClass"], "Metals")
        self.assertEqual(row["baseCurrency"], "XAU")
        self.assertEqual(row["quoteCurrency"], "EUR")

    def test_build_registry_summary_and_resolve(self):
        payload = registry.build_registry_from_symbols(
            [
                {"name": "EURUSDc", "description": "Euro vs US Dollar", "path": "ForexCent\\EURUSDc"},
                {"name": "USDJPYc", "description": "US Dollar vs Japanese Yen", "path": "ForexCent\\USDJPYc"},
                {"name": "XAUUSDc", "description": "Gold vs US Dollar", "path": "Metals\\XAUUSDc"},
            ],
            generated_at="2026-04-28T00:00:00Z",
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["totalSymbols"], 2)
        self.assertEqual(payload["summary"]["assetClassCounts"]["Forex"], 2)
        self.assertNotIn("Metals", payload["summary"]["assetClassCounts"])

        resolved = registry.add_resolve_payload(payload, "EURUSD")
        self.assertEqual(resolved["matchCount"], 1)
        self.assertEqual(resolved["resolved"]["brokerSymbol"], "EURUSDc")

        filtered = registry.add_resolve_payload(payload, "XAUUSD")
        self.assertEqual(filtered["matchCount"], 0)

    def test_registry_contract_fields_are_stable(self):
        payload = registry.build_registry_from_symbols(
            [
                {
                    "name": "EURUSDc",
                    "description": "Euro vs US Dollar",
                    "path": "ForexCent\\EURUSDc",
                    "visible": True,
                    "selected": True,
                    "digits": 5,
                    "point": 0.00001,
                    "spread": 17,
                    "tradeMode": 4,
                    "volumeMin": 0.01,
                    "volumeMax": 200.0,
                    "volumeStep": 0.01,
                }
            ],
            generated_at="2026-04-28T00:00:00Z",
        )
        self.assertEqual(payload["mode"], "MT5_SYMBOL_REGISTRY_V1")
        self.assertEqual(payload["endpoint"], "registry")
        self.assertEqual(payload["safety"], registry.SAFETY)
        self.assertIn("summary", payload)
        self.assertIn("mappings", payload)
        self.assertIn("assetClassCounts", payload["summary"])
        self.assertIn("brokerSuffixCounts", payload["summary"])

        row = payload["mappings"][0]
        required_fields = {
            "canonicalSymbol",
            "brokerSymbol",
            "brokerSuffix",
            "assetClass",
            "marketCategory",
            "marketType",
            "baseCurrency",
            "quoteCurrency",
            "description",
            "path",
            "visible",
            "selected",
            "digits",
            "point",
            "spread",
            "tradeMode",
            "volumeMin",
            "volumeMax",
            "volumeStep",
            "lotSize",
            "standardLot",
            "minLot",
            "lotStep",
            "maxLot",
            "contractUnit",
            "mappingReason",
            "confidence",
            "aliases",
        }
        self.assertTrue(required_fields.issubset(row.keys()))
        self.assertFalse(payload["safety"]["symbolSelectAllowed"])
        self.assertFalse(payload["safety"]["orderSendAllowed"])

    def test_resolve_contract_fields_are_stable(self):
        payload = registry.build_registry_from_symbols(
            [{"name": "USDJPYc", "description": "US Dollar vs Japanese Yen", "path": "ForexCent\\USDJPYc"}],
            generated_at="2026-04-28T00:00:00Z",
        )
        resolved = registry.add_resolve_payload(payload, "USDJPYc")
        self.assertEqual(resolved["endpoint"], "resolve")
        self.assertEqual(resolved["querySymbol"], "USDJPYc")
        self.assertEqual(resolved["matchCount"], 1)
        self.assertEqual(resolved["resolved"]["canonicalSymbol"], "USDJPY")
        self.assertEqual(resolved["matches"][0]["brokerSymbol"], "USDJPYc")

    def test_safety_metadata_is_read_only(self):
        self.assertTrue(registry.SAFETY["readOnly"])
        self.assertFalse(registry.SAFETY["orderSendAllowed"])
        self.assertFalse(registry.SAFETY["closeAllowed"])
        self.assertFalse(registry.SAFETY["cancelAllowed"])
        self.assertFalse(registry.SAFETY["symbolSelectAllowed"])
        self.assertFalse(registry.SAFETY["mutatesMt5"])

    def test_static_catalog_is_forex_only(self):
        catalog = registry.static_symbol_catalog()
        canonical = {row["canonicalSymbol"] for row in catalog}
        self.assertIn("EURUSD", canonical)
        self.assertIn("USDJPY", canonical)
        self.assertNotIn("XAUUSD", canonical)
        self.assertNotIn("US500", canonical)
        self.assertTrue(all(row["marketCategory"] == "forex" for row in catalog))
        self.assertEqual(registry.get_lot_size_info("EURUSD")["standardLot"], 100000)


if __name__ == "__main__":
    unittest.main()
