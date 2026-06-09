"""Read-only MT5 symbol registry for QuantGod.

This tool normalizes broker-specific MT5 symbols such as EURUSDc or
USDJPY.raw into stable canonical symbols for dashboard and research use. It
reads MT5 symbol metadata only and never selects symbols, writes files, stores
credentials, or sends trade requests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import mt5_readonly_bridge  # noqa: E402

try:  # noqa: E402
    from tools.hfm_crypto_cfd.schema import HFM_CRYPTO_USD_CANONICALS
except Exception:  # pragma: no cover - support direct script execution from tools/
    try:
        from hfm_crypto_cfd.schema import HFM_CRYPTO_USD_CANONICALS
    except Exception:  # pragma: no cover - keep this standalone when copied outside repo
        HFM_CRYPTO_USD_CANONICALS = (
            "BTCUSD",
            "ETHUSD",
            "LTCUSD",
            "XRPUSD",
            "BCHUSD",
            "ADAUSD",
            "DOTUSD",
            "SOLUSD",
            "DOGEUSD",
        )


SAFETY = {
    "readOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "symbolSelectAllowed": False,
    "credentialStorageAllowed": False,
    "livePresetMutationAllowed": False,
    "mutatesMt5": False,
}

ENDPOINTS = {"registry", "resolve"}
DEFAULT_LIMIT = 2000
MAX_LIMIT = 5000

STATIC_SYMBOLS: tuple[dict[str, Any], ...] = (
    # Forex majors
    {"name": "EURUSD", "description": "Euro vs US Dollar", "path": "Forex\\Majors"},
    {"name": "GBPUSD", "description": "British Pound vs US Dollar", "path": "Forex\\Majors"},
    {"name": "USDJPY", "description": "US Dollar vs Japanese Yen", "path": "Forex\\Majors"},
    {"name": "USDCHF", "description": "US Dollar vs Swiss Franc", "path": "Forex\\Majors"},
    {"name": "AUDUSD", "description": "Australian Dollar vs US Dollar", "path": "Forex\\Majors"},
    {"name": "USDCAD", "description": "US Dollar vs Canadian Dollar", "path": "Forex\\Majors"},
    {"name": "NZDUSD", "description": "New Zealand Dollar vs US Dollar", "path": "Forex\\Majors"},
    # Crosses and exotics mirrored from QuantDinger's MT5 catalog shape.
    {"name": "EURGBP", "description": "Euro vs British Pound", "path": "Forex\\Crosses"},
    {"name": "EURJPY", "description": "Euro vs Japanese Yen", "path": "Forex\\Crosses"},
    {"name": "EURCHF", "description": "Euro vs Swiss Franc", "path": "Forex\\Crosses"},
    {"name": "EURAUD", "description": "Euro vs Australian Dollar", "path": "Forex\\Crosses"},
    {"name": "EURCAD", "description": "Euro vs Canadian Dollar", "path": "Forex\\Crosses"},
    {"name": "EURNZD", "description": "Euro vs New Zealand Dollar", "path": "Forex\\Crosses"},
    {"name": "GBPJPY", "description": "British Pound vs Japanese Yen", "path": "Forex\\Crosses"},
    {"name": "GBPCHF", "description": "British Pound vs Swiss Franc", "path": "Forex\\Crosses"},
    {"name": "GBPAUD", "description": "British Pound vs Australian Dollar", "path": "Forex\\Crosses"},
    {"name": "GBPCAD", "description": "British Pound vs Canadian Dollar", "path": "Forex\\Crosses"},
    {"name": "GBPNZD", "description": "British Pound vs New Zealand Dollar", "path": "Forex\\Crosses"},
    {"name": "AUDJPY", "description": "Australian Dollar vs Japanese Yen", "path": "Forex\\Crosses"},
    {"name": "AUDCHF", "description": "Australian Dollar vs Swiss Franc", "path": "Forex\\Crosses"},
    {"name": "AUDCAD", "description": "Australian Dollar vs Canadian Dollar", "path": "Forex\\Crosses"},
    {"name": "AUDNZD", "description": "Australian Dollar vs New Zealand Dollar", "path": "Forex\\Crosses"},
    {"name": "NZDJPY", "description": "New Zealand Dollar vs Japanese Yen", "path": "Forex\\Crosses"},
    {"name": "NZDCHF", "description": "New Zealand Dollar vs Swiss Franc", "path": "Forex\\Crosses"},
    {"name": "NZDCAD", "description": "New Zealand Dollar vs Canadian Dollar", "path": "Forex\\Crosses"},
    {"name": "CADJPY", "description": "Canadian Dollar vs Japanese Yen", "path": "Forex\\Crosses"},
    {"name": "CADCHF", "description": "Canadian Dollar vs Swiss Franc", "path": "Forex\\Crosses"},
    {"name": "CHFJPY", "description": "Swiss Franc vs Japanese Yen", "path": "Forex\\Crosses"},
    {"name": "USDMXN", "description": "US Dollar vs Mexican Peso", "path": "Forex\\Exotics"},
    {"name": "USDZAR", "description": "US Dollar vs South African Rand", "path": "Forex\\Exotics"},
    {"name": "USDTRY", "description": "US Dollar vs Turkish Lira", "path": "Forex\\Exotics"},
    {"name": "USDHKD", "description": "US Dollar vs Hong Kong Dollar", "path": "Forex\\Exotics"},
    {"name": "USDSGD", "description": "US Dollar vs Singapore Dollar", "path": "Forex\\Exotics"},
    {"name": "USDNOK", "description": "US Dollar vs Norwegian Krone", "path": "Forex\\Exotics"},
    {"name": "USDSEK", "description": "US Dollar vs Swedish Krona", "path": "Forex\\Exotics"},
    {"name": "USDDKK", "description": "US Dollar vs Danish Krone", "path": "Forex\\Exotics"},
    {"name": "EURTRY", "description": "Euro vs Turkish Lira", "path": "Forex\\Exotics"},
    {"name": "EURMXN", "description": "Euro vs Mexican Peso", "path": "Forex\\Exotics"},
    {"name": "EURNOK", "description": "Euro vs Norwegian Krone", "path": "Forex\\Exotics"},
    {"name": "EURSEK", "description": "Euro vs Swedish Krona", "path": "Forex\\Exotics"},
    {"name": "EURDKK", "description": "Euro vs Danish Krone", "path": "Forex\\Exotics"},
    {"name": "EURPLN", "description": "Euro vs Polish Zloty", "path": "Forex\\Exotics"},
    {"name": "EURHUF", "description": "Euro vs Hungarian Forint", "path": "Forex\\Exotics"},
    {"name": "EURCZK", "description": "Euro vs Czech Koruna", "path": "Forex\\Exotics"},
    # CFD classes QuantDinger exposes through the same MT5 symbol layer.
    {"name": "XAUUSD", "description": "Gold vs US Dollar", "path": "Metals"},
    {"name": "XAGUSD", "description": "Silver vs US Dollar", "path": "Metals"},
    {"name": "XAUEUR", "description": "Gold vs Euro", "path": "Metals"},
    {"name": "US30", "description": "Dow Jones 30 CFD", "path": "Indices"},
    {"name": "US500", "description": "S&P 500 CFD", "path": "Indices"},
    {"name": "USTEC", "description": "Nasdaq 100 CFD", "path": "Indices"},
    {"name": "UK100", "description": "FTSE 100 CFD", "path": "Indices"},
    {"name": "DE40", "description": "DAX 40 CFD", "path": "Indices"},
    {"name": "JP225", "description": "Nikkei 225 CFD", "path": "Indices"},
    {"name": "AU200", "description": "Australia 200 CFD", "path": "Indices"},
    {"name": "BTCUSD", "description": "Bitcoin vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "ETHUSD", "description": "Ethereum vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "LTCUSD", "description": "Litecoin vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "XRPUSD", "description": "Ripple vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "ADAUSD", "description": "Cardano vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "BNBUSD", "description": "BNB vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "BCHUSD", "description": "Bitcoin Cash vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "SOLUSD", "description": "Solana vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "DOTUSD", "description": "Polkadot vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "LINKUSD", "description": "Chainlink vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "AAVEUSD", "description": "Aave vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "AVAXUSD", "description": "Avalanche vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "TRXUSD", "description": "Tron vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "FETUSD", "description": "Fetch vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "ICPUSD", "description": "Internet Computer vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "XLMUSD", "description": "Stellar Lumens vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "NEARUSD", "description": "NEAR Protocol vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "UNIUSD", "description": "Uniswap vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "ALGOUSD", "description": "Algo vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "APTUSD", "description": "Aptos vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "ATOMUSD", "description": "Cosmos vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "CRVUSD", "description": "Curve vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "FILUSD", "description": "Filecoin vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "FLOWUSD", "description": "Flow vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "THETAUSD", "description": "Theta Network vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "HBARUSD", "description": "Hedera vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "XTZUSD", "description": "Tezos vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "DOGEUSD", "description": "Dogecoin vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "GALAUSD", "description": "Gala vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "GRTUSD", "description": "The Graph vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "ETCUSD", "description": "Ethereum Classic vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "IMXUSD", "description": "Immutable vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "IOTAUSD", "description": "IOTA vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "SANDUSD", "description": "The Sandbox vs US Dollar CFD", "path": "Crypto CFD"},
    {"name": "SHIBUSD", "description": "Shiba Inu vs US Dollar CFD", "path": "Crypto CFD"},
)

CURRENCY_CODES = (
    "AUD",
    "CAD",
    "CHF",
    "CNH",
    "CZK",
    "DKK",
    "EUR",
    "GBP",
    "HKD",
    "HUF",
    "JPY",
    "MXN",
    "NOK",
    "NZD",
    "PLN",
    "RUB",
    "SEK",
    "SGD",
    "THB",
    "TRY",
    "USD",
    "USC",
    "ZAR",
)

METAL_PREFIXES = {
    "XAUUSD": ("XAU", "USD"),
    "XAGUSD": ("XAG", "USD"),
    "XPTUSD": ("XPT", "USD"),
    "XPDUSD": ("XPD", "USD"),
}

METAL_ALIASES = {
    "GOLD": ("XAUUSD", "XAU", "USD"),
    "SILVER": ("XAGUSD", "XAG", "USD"),
}

CRYPTO_PREFIXES = {
    *HFM_CRYPTO_USD_CANONICALS,
}

INDEX_PREFIXES = (
    "US500",
    "SPX500",
    "NAS100",
    "US100",
    "USTEC",
    "US30",
    "DJ30",
    "DE40",
    "GER40",
    "DAX40",
    "UK100",
    "JP225",
    "HK50",
    "AUS200",
    "FRA40",
    "EU50",
)

ENERGY_PREFIXES = (
    "XTIUSD",
    "XBRUSD",
    "USOIL",
    "UKOIL",
    "BRENT",
    "WTI",
    "NATGAS",
)

LOT_SIZE_PROFILES = {
    "forex": {"standardLot": 100000, "minLot": 0.01, "lotStep": 0.01, "maxLot": 100.0, "contractUnit": "base_currency_units"},
    "metal_cfd": {"standardLot": 100, "minLot": 0.01, "lotStep": 0.01, "maxLot": 50.0, "contractUnit": "troy_ounces"},
    "index_cfd": {"standardLot": 1, "minLot": 0.1, "lotStep": 0.1, "maxLot": 100.0, "contractUnit": "index_contract"},
    "crypto_cfd": {"standardLot": 1, "minLot": 0.01, "lotStep": 0.01, "maxLot": 100.0, "contractUnit": "coin_contract"},
    "energy_cfd": {"standardLot": 1000, "minLot": 0.01, "lotStep": 0.01, "maxLot": 100.0, "contractUnit": "barrel_or_contract"},
    "unknown": {"standardLot": 1, "minLot": 0.01, "lotStep": 0.01, "maxLot": 100.0, "contractUnit": "contract"},
}

KNOWN_SUFFIXES = (
    ".RAW",
    "_RAW",
    "-RAW",
    ".ECN",
    "_ECN",
    "-ECN",
    ".PRO",
    "_PRO",
    "-PRO",
    ".CASH",
    "_CASH",
    "-CASH",
    ".CFD",
    "_CFD",
    "-CFD",
    ".CENT",
    "_CENT",
    "-CENT",
    ".MICRO",
    "_MICRO",
    "-MICRO",
    "RAW",
    "ECN",
    "PRO",
    "CASH",
    "CFD",
    "CENT",
    "MICRO",
    "MINI",
    "C",
    "M",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def compact_symbol(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", clean_text(value).upper())


def first_value(row: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def clamp_limit(value: Any, fallback: int = DEFAULT_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, min(parsed, MAX_LIMIT))


def detect_forex_pair(compact: str) -> tuple[str, str, str] | None:
    for base in CURRENCY_CODES:
        for quote in CURRENCY_CODES:
            if base == quote:
                continue
            pair = f"{base}{quote}"
            if compact.startswith(pair):
                return pair, base, quote
    return None


def detect_metal_pair(compact: str) -> tuple[str, str, str] | None:
    for base in ("XAU", "XAG", "XPT", "XPD"):
        for quote in CURRENCY_CODES:
            pair = f"{base}{quote}"
            if compact.startswith(pair):
                return pair, base, quote
    return None


def strip_known_suffix(symbol: str) -> tuple[str, str]:
    upper = clean_text(symbol).upper()
    for suffix in sorted(KNOWN_SUFFIXES, key=len, reverse=True):
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return symbol[: -len(suffix)], symbol[-len(suffix) :]
    return symbol, ""


def suffix_from_prefix(symbol: str, canonical: str) -> str:
    if clean_text(symbol).upper().startswith(canonical.upper()):
        return symbol[len(canonical) :]
    return ""


def market_type_from_category(category: Any) -> str:
    text = clean_text(category).lower()
    if "forex" in text:
        return "forex"
    if "metal" in text:
        return "metal_cfd"
    if "index" in text:
        return "index_cfd"
    if "crypto" in text:
        return "crypto_cfd"
    if "energy" in text:
        return "energy_cfd"
    return text or "unknown"


def parse_symbol(symbol: str) -> tuple[str, str]:
    row = normalize_symbol_row({"name": symbol})
    return clean_text(row.get("canonicalSymbol")).upper(), market_type_from_category(row.get("marketCategory"))


def get_lot_size_info(symbol: str) -> dict[str, Any]:
    _canonical, market_type = parse_symbol(symbol)
    return dict(LOT_SIZE_PROFILES.get(market_type) or LOT_SIZE_PROFILES["unknown"])


def static_symbol_catalog() -> list[dict[str, Any]]:
    return [normalize_symbol_row(dict(row)) for row in STATIC_SYMBOLS]


def infer_symbol_identity(row: dict[str, Any]) -> dict[str, Any]:
    broker_symbol = clean_text(row.get("name"))
    compact = compact_symbol(broker_symbol)
    haystack = " ".join(
        [
            broker_symbol,
            clean_text(row.get("description")),
            clean_text(row.get("path")),
            clean_text(row.get("currency_base", row.get("currencyBase"))),
            clean_text(row.get("currency_profit", row.get("currencyProfit"))),
        ]
    ).lower()

    forex = detect_forex_pair(compact)
    if forex:
        canonical, base, quote = forex
        return {
            "canonicalSymbol": canonical,
            "baseCurrency": base,
            "quoteCurrency": quote,
            "assetClass": "Forex",
            "marketCategory": "forex",
            "brokerSuffix": suffix_from_prefix(broker_symbol, canonical),
            "confidence": 1.0,
            "mappingReason": "currency_pair_prefix",
        }

    metal_pair = detect_metal_pair(compact)
    if metal_pair:
        canonical, base, quote = metal_pair
        return {
            "canonicalSymbol": canonical,
            "baseCurrency": base,
            "quoteCurrency": quote,
            "assetClass": "Metals",
            "marketCategory": "metal_cfd",
            "brokerSuffix": suffix_from_prefix(broker_symbol, canonical),
            "confidence": 0.96,
            "mappingReason": "metal_pair_prefix",
        }

    for alias, identity in METAL_ALIASES.items():
        if compact.startswith(alias) or alias.lower() in haystack:
            canonical, base, quote = identity
            return {
                "canonicalSymbol": canonical,
                "baseCurrency": base,
                "quoteCurrency": quote,
                "assetClass": "Metals",
                "marketCategory": "metal_cfd",
                "brokerSuffix": suffix_from_prefix(broker_symbol, alias),
                "confidence": 0.88,
                "mappingReason": "metal_alias",
            }

    for prefix in CRYPTO_PREFIXES:
        if compact.startswith(prefix):
            return {
                "canonicalSymbol": prefix,
                "baseCurrency": prefix[:-3],
                "quoteCurrency": prefix[-3:],
                "assetClass": "Crypto CFD",
                "marketCategory": "crypto_cfd",
                "brokerSuffix": suffix_from_prefix(broker_symbol, prefix),
                "confidence": 0.9,
                "mappingReason": "crypto_prefix",
            }

    for prefix in INDEX_PREFIXES:
        if compact.startswith(prefix):
            return {
                "canonicalSymbol": prefix,
                "baseCurrency": "",
                "quoteCurrency": clean_text(row.get("currency_profit", row.get("currencyProfit"))) or "USD",
                "assetClass": "Indices",
                "marketCategory": "index_cfd",
                "brokerSuffix": suffix_from_prefix(broker_symbol, prefix),
                "confidence": 0.84,
                "mappingReason": "index_prefix",
            }

    for prefix in ENERGY_PREFIXES:
        if compact.startswith(prefix) or prefix.lower() in haystack:
            return {
                "canonicalSymbol": prefix,
                "baseCurrency": "",
                "quoteCurrency": clean_text(row.get("currency_profit", row.get("currencyProfit"))) or "USD",
                "assetClass": "Energy",
                "marketCategory": "energy_cfd",
                "brokerSuffix": suffix_from_prefix(broker_symbol, prefix),
                "confidence": 0.82,
                "mappingReason": "energy_prefix",
            }

    stripped, suffix = strip_known_suffix(broker_symbol)
    fallback = compact_symbol(stripped) or compact or broker_symbol.upper()
    asset_class = "Other CFD"
    market_category = "other_cfd"
    if "stock" in haystack or "shares" in haystack:
        asset_class = "Stocks"
        market_category = "stock_cfd"
    elif "commodity" in haystack:
        asset_class = "Commodities"
        market_category = "commodity_cfd"
    elif "index" in haystack or "indices" in haystack:
        asset_class = "Indices"
        market_category = "index_cfd"
    elif "crypto" in haystack:
        asset_class = "Crypto CFD"
        market_category = "crypto_cfd"

    return {
        "canonicalSymbol": fallback,
        "baseCurrency": clean_text(row.get("currency_base", row.get("currencyBase"))),
        "quoteCurrency": clean_text(row.get("currency_profit", row.get("currencyProfit"))),
        "assetClass": asset_class,
        "marketCategory": market_category,
        "brokerSuffix": suffix,
        "confidence": 0.55,
        "mappingReason": "fallback_suffix_strip",
    }


def normalize_symbol_row(row: dict[str, Any]) -> dict[str, Any]:
    identity = infer_symbol_identity(row)
    broker_symbol = clean_text(row.get("name"))
    canonical = identity["canonicalSymbol"]
    market_type = market_type_from_category(identity["marketCategory"])
    lot_info = dict(LOT_SIZE_PROFILES.get(market_type) or LOT_SIZE_PROFILES["unknown"])
    volume_min = first_value(row, ("volumeMin", "volume_min"), 0.0)
    volume_max = first_value(row, ("volumeMax", "volume_max"), 0.0)
    volume_step = first_value(row, ("volumeStep", "volume_step"), 0.0)
    contract_size = first_value(
        row,
        ("contractSize", "tradeContractSize", "trade_contract_size"),
        lot_info["standardLot"],
    )
    tick_size = first_value(
        row,
        ("tickSize", "tradeTickSize", "trade_tick_size", "point"),
        0.0,
    )
    tick_value = first_value(
        row,
        ("tickValue", "tradeTickValue", "trade_tick_value"),
        0.0,
    )
    aliases = []
    for candidate in [canonical, broker_symbol, compact_symbol(broker_symbol)]:
        if candidate and candidate not in aliases:
            aliases.append(candidate)
    return {
        "canonicalSymbol": canonical,
        "brokerSymbol": broker_symbol,
        "brokerSuffix": identity["brokerSuffix"],
        "assetClass": identity["assetClass"],
        "marketCategory": identity["marketCategory"],
        "marketType": market_type,
        "baseCurrency": identity["baseCurrency"],
        "quoteCurrency": identity["quoteCurrency"],
        "description": clean_text(row.get("description")),
        "path": clean_text(row.get("path")),
        "visible": bool(row.get("visible")),
        "selected": bool(row.get("selected", row.get("select"))),
        "digits": row.get("digits", 0),
        "point": row.get("point", 0.0),
        "spread": row.get("spread", 0),
        "tradeMode": row.get("tradeMode", row.get("trade_mode", 0)),
        "tradeCalcMode": first_value(row, ("tradeCalcMode", "trade_calc_mode", "calcMode"), 0),
        "tradeContractSize": contract_size,
        "tradeTickSize": tick_size,
        "tradeTickValue": tick_value,
        "volumeMin": volume_min,
        "volumeMax": volume_max,
        "volumeStep": volume_step,
        "lotSize": lot_info,
        "standardLot": lot_info["standardLot"],
        "contractSize": contract_size,
        "tickSize": tick_size,
        "tickValue": tick_value,
        "minLot": volume_min or lot_info["minLot"],
        "lotStep": volume_step or lot_info["lotStep"],
        "maxLot": volume_max or lot_info["maxLot"],
        "swapLong": first_value(row, ("swapLong", "swap_long"), 0.0),
        "swapShort": first_value(row, ("swapShort", "swap_short"), 0.0),
        "marginInitial": first_value(row, ("marginInitial", "margin_initial"), 0.0),
        "contractUnit": lot_info["contractUnit"],
        "mappingReason": identity["mappingReason"],
        "confidence": identity["confidence"],
        "aliases": aliases,
    }


def registry_summary(mappings: list[dict[str, Any]]) -> dict[str, Any]:
    asset_counts = Counter(row["assetClass"] for row in mappings)
    suffix_counts = Counter(row["brokerSuffix"] or "(none)" for row in mappings)
    by_canonical: dict[str, list[str]] = defaultdict(list)
    for row in mappings:
        by_canonical[row["canonicalSymbol"]].append(row["brokerSymbol"])
    conflicts = [
        {"canonicalSymbol": key, "brokerSymbols": values}
        for key, values in sorted(by_canonical.items())
        if len(values) > 1
    ]
    return {
        "totalSymbols": len(mappings),
        "mappedSymbols": sum(1 for row in mappings if row.get("canonicalSymbol")),
        "visibleSymbols": sum(1 for row in mappings if row.get("visible")),
        "selectedSymbols": sum(1 for row in mappings if row.get("selected")),
        "assetClassCounts": dict(sorted(asset_counts.items())),
        "staticCatalogSymbols": len(STATIC_SYMBOLS),
        "brokerSuffixCounts": dict(sorted(suffix_counts.items())),
        "canonicalConflicts": conflicts,
        "canonicalConflictCount": len(conflicts),
    }


def build_registry_from_symbols(
    symbols: list[dict[str, Any]],
    *,
    endpoint: str = "registry",
    source: str = "input",
    group: str = "*",
    query: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    mappings = [normalize_symbol_row(dict(row)) for row in symbols if clean_text(row.get("name"))]
    mappings.sort(key=lambda row: (row["assetClass"], row["canonicalSymbol"], row["brokerSymbol"]))
    return {
        "ok": True,
        "mode": "MT5_SYMBOL_REGISTRY_V1",
        "endpoint": endpoint,
        "source": source,
        "group": group,
        "query": query,
        "generatedAtIso": generated_at or utc_now(),
        "safety": SAFETY,
        "summary": registry_summary(mappings),
        "mappings": mappings,
    }


def matches_symbol(row: dict[str, Any], symbol: str) -> bool:
    needle = compact_symbol(symbol)
    if not needle:
        return False
    candidates = [
        row.get("canonicalSymbol"),
        row.get("brokerSymbol"),
        *(row.get("aliases") or []),
    ]
    return any(compact_symbol(candidate) == needle for candidate in candidates)


def add_resolve_payload(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    matches = [row for row in payload.get("mappings", []) if matches_symbol(row, symbol)]
    exact_canonical = [row for row in matches if compact_symbol(row.get("canonicalSymbol")) == compact_symbol(symbol)]
    primary = exact_canonical[0] if exact_canonical else (matches[0] if matches else None)
    payload.update(
        {
            "endpoint": "resolve",
            "querySymbol": clean_text(symbol),
            "resolved": primary,
            "matches": matches,
            "matchCount": len(matches),
        }
    )
    return payload


def public_error(message: str, *, endpoint: str = "registry", detail: Any = None) -> dict[str, Any]:
    payload = {
        "ok": False,
        "status": "UNAVAILABLE",
        "mode": "MT5_SYMBOL_REGISTRY_V1",
        "endpoint": endpoint,
        "generatedAtIso": utc_now(),
        "error": str(message),
        "safety": SAFETY,
    }
    if detail not in (None, ""):
        payload["detail"] = detail
    return payload


def extract_symbols_from_payload(payload: Any) -> tuple[list[dict[str, Any]], str, str]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)], "*", ""
    if not isinstance(payload, dict):
        return [], "*", ""
    symbols_block = payload.get("symbols") if isinstance(payload.get("symbols"), dict) else payload
    items = symbols_block.get("items") if isinstance(symbols_block, dict) else []
    group = clean_text(symbols_block.get("group", "*")) if isinstance(symbols_block, dict) else "*"
    query = clean_text(symbols_block.get("query", "")) if isinstance(symbols_block, dict) else ""
    return [dict(row) for row in items if isinstance(row, dict)], group, query


def load_input_symbols(path: str) -> tuple[list[dict[str, Any]], str, str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return extract_symbols_from_payload(payload)


def load_live_symbols(args: argparse.Namespace) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    mt5, error = mt5_readonly_bridge.load_mt5()
    if error:
        return None, public_error(error.get("error", "MetaTrader5 package unavailable"), endpoint=args.endpoint, detail=error.get("detail"))
    initialized, init_error = mt5_readonly_bridge.initialize_mt5(mt5, args.terminal_path)
    if not initialized:
        return None, public_error("MT5 initialize failed", endpoint=args.endpoint, detail=init_error)
    try:
        status = mt5_readonly_bridge.status_payload(mt5, endpoint="symbol-registry")
        symbols = mt5_readonly_bridge.get_symbols(mt5, args.group, args.query, args.limit)
        return {"status": status, "symbols": symbols}, None
    except Exception as exc:
        return None, public_error(f"MT5 symbol registry query failed: {exc}", endpoint=args.endpoint)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QuantGod read-only MT5 symbol registry")
    parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), default="registry")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--group", default="*")
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--input-json", default="")
    parser.add_argument("--terminal-path", default=os.environ.get("QG_MT5_TERMINAL_PATH", ""))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    args.limit = clamp_limit(args.limit)
    source = "live_mt5"
    status = None

    if args.input_json:
        try:
            symbols, group, query = load_input_symbols(args.input_json)
            source = "input_json"
            args.group = args.group or group
            args.query = args.query or query
        except Exception as exc:
            print(json.dumps(public_error(f"input json load failed: {exc}", endpoint=args.endpoint), ensure_ascii=False, indent=2))
            return 0
    else:
        live_payload, error = load_live_symbols(args)
        if error:
            print(json.dumps(error, ensure_ascii=False, indent=2))
            return 0
        status = live_payload.get("status") if live_payload else None
        symbols_block = live_payload.get("symbols") if live_payload else {}
        symbols = symbols_block.get("items", []) if isinstance(symbols_block, dict) else []
        args.group = symbols_block.get("group", args.group) if isinstance(symbols_block, dict) else args.group
        args.query = symbols_block.get("query", args.query) if isinstance(symbols_block, dict) else args.query

    payload = build_registry_from_symbols(
        symbols,
        endpoint=args.endpoint,
        source=source,
        group=args.group,
        query=args.query,
    )
    if status:
        payload["terminal"] = status.get("terminal")
        payload["account"] = status.get("account")
        payload["status"] = status.get("status")
        payload["lastError"] = status.get("lastError")
    if args.endpoint == "resolve":
        payload = add_resolve_payload(payload, args.symbol)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
