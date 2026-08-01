#!/usr/bin/env python3
"""Retired MT5 mutation bridge kept as a fail-closed compatibility shim.

QuantGod's active product contract is Shadow/ReadOnly and has no execution
lane.  Read-only account, position, order, quote, and health access lives in
``mt5_readonly_bridge.py`` and the dedicated Dashboard routes.  Legacy callers
may still import this module while they are migrated, but every mutating
endpoint is permanently blocked in code and never calls the broker API.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import socket
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import mt5_readonly_bridge
    import mt5_symbol_registry
except ImportError:  # pragma: no cover - defensive path for unusual launchers
    sys.path.append(str(Path(__file__).resolve().parent))
    import mt5_readonly_bridge  # type: ignore
    import mt5_symbol_registry  # type: ignore


DEFAULT_RUNTIME_DIR = Path(r"C:\Program Files\HFM Metatrader 5\MQL5\Files")
DEFAULT_CONFIG_NAME = "QuantGod_MT5TradingConfig.json"
DEFAULT_PROFILES_NAME = "QuantGod_MT5AccountProfiles.json"
AUDIT_LEDGER_NAME = "QuantGod_MT5TradingAuditLedger.csv"
MODE = "MT5_TRADING_BRIDGE_V1"
WORKER_VERSION = "mt5-trading-bridge-retired-v2"
EXECUTION_LANE_EXISTS = False
EXECUTION_LANE_REMOVED_REASON = "execution_lane_removed_shadow_readonly"

ENDPOINTS = {"status", "profiles", "save-profile", "login", "order", "close", "cancel"}
MUTATING_ENDPOINTS = {"save-profile", "login", "order", "close", "cancel"}
ORDER_ENDPOINTS = {"order", "close", "cancel"}
SHADOW_SIMULATION_ENDPOINTS = {"order", "close", "cancel"}
LIVE_OWNER_MODES = {"DASHBOARD_TICKET_OPS", "PY_PENDING_ONLY", "EA_AND_PY_SPLIT"}
PENDING_ONLY_OWNER_MODES = {"PY_PENDING_ONLY", "EA_AND_PY_SPLIT"}
TRUTHY = {"1", "true", "yes", "y", "on"}

DEFAULT_CONFIG: dict[str, Any] = {
    "mode": "MT5_TRADING_CONTROL_V1",
    "tradingEnabled": False,
    "dryRun": True,
    "killSwitch": True,
    "killReason": "default locked until operator enables MT5 trading controls",
    "ownerMode": "EA_ONLY",
    "terminalPath": "",
    "accountLogin": 0,
    "server": "",
    "allowDashboardMarketOrders": False,
    "allowDashboardPendingOrders": False,
    "allowDashboardClose": False,
    "allowDashboardCancel": False,
    "allowLogin": False,
    "allowedActions": ["order", "close", "cancel"],
    "allowedRoutes": ["MA_Cross", "RSI_Reversal"],
    "allowedCanonicalSymbols": ["EURUSD", "USDJPY"],
    "maxLotsPerOrder": 0.01,
    "maxTotalLotsPerCanonical": 0.01,
    "maxPortfolioLots": 0.02,
    "maxOrdersPerDay": 2,
    "maxOrdersPerRouteSymbolDay": 1,
    "maxSpreadPoints": 35,
    "minStopDistancePoints": 30,
    "defaultDeviationPoints": 20,
    "magic": 520090,
    "auditLedgerName": AUDIT_LEDGER_NAME,
    "profilesName": DEFAULT_PROFILES_NAME,
    "authLockPath": str(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "QuantGod" / "mt5_trading_auth_lock.json"),
    "signatureRequired": True,
    "signatureSecretEnvVar": "QG_MT5_AUTH_SECRET",
    "requireEnvEnable": True,
    "envEnableVar": "QG_MT5_TRADING_ENABLED",
}

AUDIT_FIELDS = [
    "LedgerId",
    "EventTimeIso",
    "Endpoint",
    "Action",
    "DryRun",
    "LiveAllowed",
    "Decision",
    "Reason",
    "AccountLogin",
    "Server",
    "Route",
    "CanonicalSymbol",
    "BrokerSymbol",
    "OrderType",
    "Side",
    "Lots",
    "Ticket",
    "Price",
    "StopLoss",
    "TakeProfit",
    "ExpirationTimeIso",
    "AuthLockId",
    "KillSwitchSnapshotJson",
    "RequestJson",
    "BrokerRetCode",
    "BrokerOrderTicket",
    "BrokerComment",
    "WorkerVersion",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(read_text(path).replace("\ufeff", ""))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in TRUTHY


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(str(value).strip())
        return number if math.isfinite(number) else default
    except Exception:
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def clean(value: Any, max_len: int = 160) -> str:
    return " ".join(str(value or "").split())[:max_len]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def runtime_path(runtime_dir: Path, name: str) -> Path:
    base = Path(name).name
    return runtime_dir / base


def load_config(runtime_dir: Path, config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or runtime_path(runtime_dir, DEFAULT_CONFIG_NAME)
    payload = read_json(path)
    config = deep_merge(DEFAULT_CONFIG, payload)
    config["_configPath"] = str(path)
    return config


def public_safety(config: dict[str, Any], *, live_allowed: bool = False, dry_run: bool | None = None) -> dict[str, Any]:
    del live_allowed, dry_run
    return {
        "readOnly": True,
        "dryRun": True,
        "executionLaneExists": EXECUTION_LANE_EXISTS,
        "tradingEnabled": False,
        "legacyTradingConfigured": as_bool(config.get("tradingEnabled")),
        "envEnableVar": config.get("envEnableVar", "QG_MT5_TRADING_ENABLED"),
        "envEnabled": False,
        "legacyEnvRequested": env_enabled(config),
        "killSwitch": True,
        "ownerMode": "SHADOW_READONLY",
        "orderSendAllowed": False,
        "closeAllowed": False,
        "cancelAllowed": False,
        "loginAllowed": False,
        "credentialStorageAllowed": False,
        "livePresetMutationAllowed": False,
        "auditLedgerRequired": False,
        "mutatesMt5": False,
        "reason": EXECUTION_LANE_REMOVED_REASON,
    }


def env_enabled(config: dict[str, Any]) -> bool:
    if not as_bool(config.get("requireEnvEnable"), True):
        return True
    return str(os.environ.get(str(config.get("envEnableVar") or "QG_MT5_TRADING_ENABLED"), "")).strip().lower() in TRUTHY


def canonical_symbol(symbol: str) -> str:
    row = mt5_symbol_registry.normalize_symbol_row({"name": clean(symbol, 80).upper()})
    return clean(row.get("canonicalSymbol") or symbol, 80).upper()


def parse_iso(value: Any) -> datetime | None:
    text = clean(value, 64).replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def lock_signature_payload(lock: dict[str, Any]) -> str:
    parts = [
        clean(lock.get("lockId"), 80),
        str(as_int(lock.get("accountLogin"), 0)),
        clean(lock.get("server"), 120),
        clean(lock.get("expiresAtIso"), 64),
        clean(lock.get("mode"), 64),
    ]
    return "|".join(parts)


def expected_signature(lock: dict[str, Any], secret: str) -> str:
    return hashlib.sha256(f"{lock_signature_payload(lock)}|{secret}".encode("utf-8")).hexdigest()


def load_auth_lock(config: dict[str, Any]) -> dict[str, Any]:
    path = Path(clean(config.get("authLockPath"), 260))
    lock = read_json(path)
    return {"path": str(path), "exists": path.exists(), "payload": lock}


def validate_auth_lock(
    config: dict[str, Any],
    request: dict[str, Any],
    account: dict[str, Any] | None,
) -> dict[str, Any]:
    loaded = load_auth_lock(config)
    lock = loaded["payload"]
    reasons: list[str] = []
    now = datetime.now(timezone.utc)

    if not loaded["exists"]:
        reasons.append("auth_lock_missing")
    if not isinstance(lock, dict) or not lock:
        reasons.append("auth_lock_unreadable")

    expires_at = parse_iso(lock.get("expiresAtIso")) if lock else None
    if not expires_at:
        reasons.append("auth_lock_expiry_missing")
    elif expires_at <= now:
        reasons.append("auth_lock_expired")

    action = clean(request.get("endpoint") or request.get("action"), 40)
    allowed_actions = {clean(item, 40) for item in lock.get("allowedActions", [])} if lock else set()
    if action and allowed_actions and action not in allowed_actions:
        reasons.append("action_not_allowed_by_lock")

    route = clean(request.get("route"), 80)
    allowed_routes = {clean(item, 80) for item in lock.get("allowedRoutes", [])} if lock else set()
    if route and allowed_routes and route not in allowed_routes:
        reasons.append("route_not_allowed_by_lock")

    symbol = canonical_symbol(clean(request.get("symbol") or request.get("brokerSymbol"), 80))
    allowed_symbols = {canonical_symbol(str(item)) for item in lock.get("allowedCanonicalSymbols", [])} if lock else set()
    if symbol and allowed_symbols and symbol not in allowed_symbols:
        reasons.append("symbol_not_allowed_by_lock")

    account_login = as_int((account or {}).get("login"), 0)
    lock_login = as_int(lock.get("accountLogin"), 0) if lock else 0
    if account_login and lock_login and account_login != lock_login:
        reasons.append("account_login_mismatch")

    account_server = clean((account or {}).get("server"), 120)
    lock_server = clean(lock.get("server"), 120) if lock else ""
    if account_server and lock_server and account_server != lock_server:
        reasons.append("server_mismatch")

    if as_bool(config.get("signatureRequired"), True):
        secret_name = clean(config.get("signatureSecretEnvVar") or "QG_MT5_AUTH_SECRET", 80)
        secret = os.environ.get(secret_name, "")
        if not secret:
            reasons.append("signature_secret_missing")
        elif clean(lock.get("signature"), 128).lower() != expected_signature(lock, secret).lower():
            reasons.append("auth_lock_signature_invalid")

    return {
        "ok": not reasons,
        "lockId": clean(lock.get("lockId"), 80) if lock else "",
        "path": loaded["path"],
        "expiresAtIso": clean(lock.get("expiresAtIso"), 64) if lock else "",
        "operator": clean(lock.get("operator"), 80) if lock else "",
        "mode": clean(lock.get("mode"), 64) if lock else "",
        "reasons": reasons,
    }


def active_lot_totals(mt5: Any, symbol: str = "") -> dict[str, float]:
    totals: dict[str, float] = {}
    try:
        positions = mt5.positions_get() or []
    except Exception:
        positions = []
    try:
        orders = mt5.orders_get() or []
    except Exception:
        orders = []

    for item in list(positions) + list(orders):
        row = mt5_readonly_bridge.maybe_asdict(item)
        broker_symbol = clean(row.get("symbol"), 80)
        canonical = canonical_symbol(broker_symbol)
        volume = as_float(row.get("volume") or row.get("volume_current") or row.get("volume_initial"), 0.0)
        totals[canonical] = totals.get(canonical, 0.0) + volume
    if symbol:
        canonical = canonical_symbol(symbol)
        return {canonical: totals.get(canonical, 0.0)}
    return totals


def today_audit_count(runtime_dir: Path, *, route: str = "", canonical: str = "") -> int:
    ledger = runtime_path(runtime_dir, AUDIT_LEDGER_NAME)
    if not ledger.exists():
        return 0
    today = utc_now()[:10]
    count = 0
    try:
        with ledger.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not str(row.get("EventTimeIso", "")).startswith(today):
                    continue
                live_allowed = str(row.get("LiveAllowed", "")).strip().lower() in TRUTHY
                if row.get("Decision") != "ORDER_SEND_ACCEPTED" or not live_allowed:
                    continue
                if route and clean(row.get("Route"), 80) != route:
                    continue
                if canonical and clean(row.get("CanonicalSymbol"), 80) != canonical:
                    continue
                count += 1
    except Exception:
        return 0
    return count


def validate_limits(
    config: dict[str, Any],
    auth: dict[str, Any],
    request: dict[str, Any],
    mt5: Any | None,
    runtime_dir: Path,
) -> list[str]:
    reasons: list[str] = []
    endpoint = clean(request.get("endpoint") or request.get("action"), 40)
    if endpoint not in ORDER_ENDPOINTS:
        return reasons

    route = clean(request.get("route"), 80)
    broker_symbol = clean(request.get("symbol") or request.get("brokerSymbol"), 80)
    canonical = canonical_symbol(broker_symbol)
    lots = as_float(request.get("lots") or request.get("volume"), 0.0)

    allowed_actions = {clean(item, 40) for item in config.get("allowedActions", [])}
    if endpoint in ORDER_ENDPOINTS and allowed_actions and endpoint not in allowed_actions:
        reasons.append("action_not_allowed_by_config")

    allowed_routes = {clean(item, 80) for item in config.get("allowedRoutes", [])}
    if route and allowed_routes and route not in allowed_routes:
        reasons.append("route_not_allowed_by_config")

    allowed_symbols = {canonical_symbol(str(item)) for item in config.get("allowedCanonicalSymbols", [])}
    if broker_symbol and allowed_symbols and canonical not in allowed_symbols:
        reasons.append("symbol_not_allowed_by_config")

    lock_payload = read_json(Path(auth.get("path", ""))) if auth.get("path") else {}
    max_lots = min(
        as_float(config.get("maxLotsPerOrder"), 0.01),
        as_float(lock_payload.get("maxLotsPerOrder"), as_float(config.get("maxLotsPerOrder"), 0.01)) or as_float(config.get("maxLotsPerOrder"), 0.01),
    )
    if endpoint == "order":
        if lots <= 0:
            reasons.append("lots_required")
        if lots > max_lots:
            reasons.append("lots_exceeds_max")

    max_day = min(
        as_int(config.get("maxOrdersPerDay"), 0) or 999999,
        as_int(lock_payload.get("maxOrdersPerDay"), as_int(config.get("maxOrdersPerDay"), 0) or 999999) or 999999,
    )
    if endpoint == "order" and today_audit_count(runtime_dir) >= max_day:
        reasons.append("daily_order_limit_reached")

    max_route_symbol = as_int(config.get("maxOrdersPerRouteSymbolDay"), 0)
    if endpoint == "order" and max_route_symbol and today_audit_count(runtime_dir, route=route, canonical=canonical) >= max_route_symbol:
        reasons.append("route_symbol_daily_order_limit_reached")

    if mt5 is not None and endpoint == "order":
        totals = active_lot_totals(mt5, broker_symbol)
        next_lots = totals.get(canonical, 0.0) + lots
        if next_lots > as_float(config.get("maxTotalLotsPerCanonical"), 0.01):
            reasons.append("canonical_lot_limit_reached")
        portfolio_next = sum(active_lot_totals(mt5).values()) + lots
        if portfolio_next > as_float(config.get("maxPortfolioLots"), 0.02):
            reasons.append("portfolio_lot_limit_reached")

    return reasons


def control_state(
    config: dict[str, Any],
    request: dict[str, Any],
    account: dict[str, Any] | None,
    mt5: Any | None,
    runtime_dir: Path,
) -> dict[str, Any]:
    del account, mt5, runtime_dir
    endpoint = clean(request.get("endpoint") or request.get("action"), 40)
    reasons = [EXECUTION_LANE_REMOVED_REASON] if endpoint in MUTATING_ENDPOINTS else []
    return {
        "endpoint": endpoint,
        "dryRun": True,
        "liveAllowed": False,
        "decision": "BLOCKED" if endpoint in MUTATING_ENDPOINTS else "READ_ONLY",
        "reasons": reasons,
        "authLock": {"ok": False, "reasons": reasons},
        "safety": public_safety(config),
    }


def audit_row(
    runtime_dir: Path,
    *,
    endpoint: str,
    request: dict[str, Any],
    state: dict[str, Any],
    decision: str,
    reason: str,
    account: dict[str, Any] | None = None,
    broker_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    broker_symbol = clean(request.get("symbol") or request.get("brokerSymbol"), 80)
    row = {
        "LedgerId": str(uuid.uuid4()),
        "EventTimeIso": utc_now(),
        "Endpoint": endpoint,
        "Action": clean(request.get("action") or endpoint, 40),
        "DryRun": str(bool(state.get("dryRun"))).lower(),
        "LiveAllowed": str(bool(state.get("liveAllowed"))).lower(),
        "Decision": decision,
        "Reason": reason,
        "AccountLogin": (account or {}).get("login", request.get("accountLogin", "")),
        "Server": (account or {}).get("server", request.get("server", "")),
        "Route": clean(request.get("route"), 80),
        "CanonicalSymbol": canonical_symbol(broker_symbol) if broker_symbol else clean(request.get("canonicalSymbol"), 80),
        "BrokerSymbol": broker_symbol,
        "OrderType": clean(request.get("orderType") or request.get("type"), 40),
        "Side": clean(request.get("side"), 20),
        "Lots": request.get("lots") or request.get("volume") or "",
        "Ticket": request.get("ticket") or request.get("positionTicket") or request.get("orderTicket") or "",
        "Price": request.get("price") or request.get("entryPrice") or "",
        "StopLoss": request.get("sl") or request.get("stopLoss") or "",
        "TakeProfit": request.get("tp") or request.get("takeProfit") or "",
        "ExpirationTimeIso": clean(request.get("expirationTimeIso"), 64),
        "AuthLockId": (state.get("authLock") or {}).get("lockId", ""),
        "KillSwitchSnapshotJson": json.dumps(
            {
                "killSwitch": state.get("safety", {}).get("killSwitch"),
                "ownerMode": state.get("safety", {}).get("ownerMode"),
                "reasons": state.get("reasons", []),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "RequestJson": json.dumps(redact_request(request), ensure_ascii=False, separators=(",", ":")),
        "BrokerRetCode": (broker_response or {}).get("retcode", ""),
        "BrokerOrderTicket": (broker_response or {}).get("order", ""),
        "BrokerComment": clean((broker_response or {}).get("comment"), 240),
        "WorkerVersion": WORKER_VERSION,
    }
    append_audit(runtime_dir, row)
    return row


def append_audit(runtime_dir: Path, row: dict[str, Any]) -> None:
    path = runtime_path(runtime_dir, AUDIT_LEDGER_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in AUDIT_FIELDS})


def redact_request(request: dict[str, Any]) -> dict[str, Any]:
    redacted = deepcopy(request)
    for key in list(redacted):
        if key.lower() in {"password", "token", "secret", "signature"}:
            redacted[key] = "[REDACTED]"
    return redacted


def result_to_dict(result: Any) -> dict[str, Any]:
    row = mt5_readonly_bridge.maybe_asdict(result)
    if row:
        return row
    if result is None:
        return {}
    return {"raw": str(result)}


def get_tick_price(mt5: Any, symbol: str, side: str) -> float:
    tick = mt5_readonly_bridge.maybe_asdict(mt5.symbol_info_tick(symbol))
    if side == "buy":
        return as_float(tick.get("ask"), 0.0)
    return as_float(tick.get("bid"), 0.0)


def mt5_order_type(mt5: Any, order_type: str, side: str) -> int:
    normalized = clean(order_type or side, 40).lower()
    mapping = {
        "buy": getattr(mt5, "ORDER_TYPE_BUY", 0),
        "sell": getattr(mt5, "ORDER_TYPE_SELL", 1),
        "market": getattr(mt5, "ORDER_TYPE_BUY", 0) if side == "buy" else getattr(mt5, "ORDER_TYPE_SELL", 1),
        "buy_limit": getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2),
        "sell_limit": getattr(mt5, "ORDER_TYPE_SELL_LIMIT", 3),
        "buy_stop": getattr(mt5, "ORDER_TYPE_BUY_STOP", 4),
        "sell_stop": getattr(mt5, "ORDER_TYPE_SELL_STOP", 5),
        "buy_stop_limit": getattr(mt5, "ORDER_TYPE_BUY_STOP_LIMIT", 6),
        "sell_stop_limit": getattr(mt5, "ORDER_TYPE_SELL_STOP_LIMIT", 7),
    }
    return mapping.get(normalized, mapping["market"])


def build_order_send_request(mt5: Any, config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    symbol = clean(request.get("symbol") or request.get("brokerSymbol"), 80)
    side = clean(request.get("side"), 20).lower()
    order_type = clean(request.get("orderType") or request.get("type") or side, 40).lower()
    is_pending = "limit" in order_type or "stop" in order_type
    lots = as_float(request.get("lots") or request.get("volume"), 0.0)
    price = as_float(request.get("price") or request.get("entryPrice"), 0.0)
    if not is_pending:
        price = get_tick_price(mt5, symbol, side)
    expiration = parse_iso(request.get("expirationTimeIso"))
    payload = {
        "action": getattr(mt5, "TRADE_ACTION_PENDING", 5) if is_pending else getattr(mt5, "TRADE_ACTION_DEAL", 1),
        "symbol": symbol,
        "volume": lots,
        "type": mt5_order_type(mt5, order_type, side),
        "price": price,
        "sl": as_float(request.get("sl") or request.get("stopLoss"), 0.0),
        "tp": as_float(request.get("tp") or request.get("takeProfit"), 0.0),
        "deviation": as_int(request.get("deviation"), as_int(config.get("defaultDeviationPoints"), 20)),
        "magic": as_int(request.get("magic"), as_int(config.get("magic"), 520090)),
        "comment": clean(request.get("comment") or f"QG_PY_{clean(request.get('route'), 24)}", 31),
        "type_time": getattr(mt5, "ORDER_TIME_SPECIFIED", 2) if expiration else getattr(mt5, "ORDER_TIME_GTC", 0),
        "type_filling": getattr(mt5, "ORDER_FILLING_RETURN", getattr(mt5, "ORDER_FILLING_FOK", 0)),
    }
    if expiration:
        payload["expiration"] = int(expiration.timestamp())
    return payload


def find_position(mt5: Any, ticket: int) -> dict[str, Any] | None:
    for item in mt5.positions_get() or []:
        row = mt5_readonly_bridge.maybe_asdict(item)
        if as_int(row.get("ticket") or row.get("identifier"), 0) == ticket:
            return row
    return None


def build_close_request(mt5: Any, config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    ticket = as_int(request.get("ticket") or request.get("positionTicket"), 0)
    position = find_position(mt5, ticket)
    if not position:
        raise ValueError(f"position not found: {ticket}")
    symbol = clean(position.get("symbol"), 80)
    volume = as_float(request.get("lots") or request.get("volume"), as_float(position.get("volume"), 0.0))
    position_type = position.get("type")
    is_buy = position_type == getattr(mt5, "POSITION_TYPE_BUY", 0)
    side = "sell" if is_buy else "buy"
    return {
        "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
        "position": ticket,
        "symbol": symbol,
        "volume": volume,
        "type": getattr(mt5, "ORDER_TYPE_SELL", 1) if is_buy else getattr(mt5, "ORDER_TYPE_BUY", 0),
        "price": get_tick_price(mt5, symbol, side),
        "deviation": as_int(request.get("deviation"), as_int(config.get("defaultDeviationPoints"), 20)),
        "magic": as_int(request.get("magic"), as_int(config.get("magic"), 520090)),
        "comment": clean(request.get("comment") or "QG_PY_CLOSE", 31),
        "type_filling": getattr(mt5, "ORDER_FILLING_RETURN", getattr(mt5, "ORDER_FILLING_FOK", 0)),
    }


def build_cancel_request(mt5: Any, request: dict[str, Any]) -> dict[str, Any]:
    ticket = as_int(request.get("ticket") or request.get("orderTicket"), 0)
    if ticket <= 0:
        raise ValueError("order ticket is required")
    return {
        "action": getattr(mt5, "TRADE_ACTION_REMOVE", 8),
        "order": ticket,
        "comment": clean(request.get("comment") or "QG_PY_CANCEL", 31),
    }


def profile_path(runtime_dir: Path, config: dict[str, Any]) -> Path:
    return runtime_path(runtime_dir, clean(config.get("profilesName") or DEFAULT_PROFILES_NAME, 120))


def load_profiles(runtime_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    payload = read_json(profile_path(runtime_dir, config))
    if not payload:
        payload = {"mode": "MT5_ACCOUNT_PROFILES_V1", "profiles": [], "updatedAtIso": utc_now()}
    profiles = payload.get("profiles")
    payload["profiles"] = profiles if isinstance(profiles, list) else []
    for profile in payload["profiles"]:
        if isinstance(profile, dict):
            profile.pop("password", None)
            profile.pop("secret", None)
            profile["credentialStorageAllowed"] = False
    return payload


def save_profile(runtime_dir: Path, config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    profiles_payload = load_profiles(runtime_dir, config)
    profile_id = clean(request.get("profileId") or request.get("name") or f"mt5-{request.get('accountLogin')}", 80)
    if not profile_id:
        raise ValueError("profileId is required")
    profile = {
        "profileId": profile_id,
        "accountLogin": as_int(request.get("accountLogin") or request.get("login"), 0),
        "server": clean(request.get("server"), 120),
        "terminalPath": clean(request.get("terminalPath"), 260),
        "passwordEnvVar": clean(request.get("passwordEnvVar"), 80),
        "role": clean(request.get("role") or "operator", 40),
        "updatedAtIso": utc_now(),
        "credentialStorageAllowed": False,
        "passwordPersisted": False,
    }
    profiles_payload["profiles"] = [
        item for item in profiles_payload.get("profiles", [])
        if not (isinstance(item, dict) and item.get("profileId") == profile_id)
    ] + [profile]
    profiles_payload["updatedAtIso"] = utc_now()
    write_json(profile_path(runtime_dir, config), profiles_payload)
    return profile


def password_for_login(request: dict[str, Any], profile: dict[str, Any] | None = None) -> str:
    if request.get("password"):
        return str(request["password"])
    env_name = clean(request.get("passwordEnvVar") or (profile or {}).get("passwordEnvVar"), 80)
    return os.environ.get(env_name, "") if env_name else ""


def find_profile(runtime_dir: Path, config: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    for profile in load_profiles(runtime_dir, config).get("profiles", []):
        if isinstance(profile, dict) and profile.get("profileId") == profile_id:
            return profile
    return None


def load_mt5_for_action(config: dict[str, Any], runtime_dir: Path, request: dict[str, Any], need_live: bool) -> tuple[Any | None, dict[str, Any] | None]:
    mt5, error = mt5_readonly_bridge.load_mt5()
    if error:
        if need_live:
            return None, error
        return None, None
    terminal_path = clean(request.get("terminalPath") or config.get("terminalPath") or os.environ.get("QG_MT5_TERMINAL_PATH", ""), 260)
    initialized, init_error = mt5_readonly_bridge.initialize_mt5(mt5, terminal_path)
    if not initialized:
        return None, mt5_readonly_bridge.public_error("MT5 initialize failed", detail=init_error)
    return mt5, None


def status_payload(runtime_dir: Path, config: dict[str, Any], mt5: Any | None = None) -> dict[str, Any]:
    account = None
    terminal = None
    last_error = None
    initialized = False
    if mt5 is not None:
        account = mt5_readonly_bridge.account_payload(mt5)
        terminal = mt5_readonly_bridge.terminal_payload(mt5)
        last_error = mt5_readonly_bridge.safe_last_error(mt5)
        initialized = True
    payload = {
        "ok": True,
        "mode": MODE,
        "endpoint": "status",
        "generatedAtIso": utc_now(),
        "host": socket.gethostname(),
        "status": "EXECUTION_LANE_REMOVED",
        "config": redact_config(config),
        "safety": public_safety(config),
        "authLock": {"ok": False, "reasons": [EXECUTION_LANE_REMOVED_REASON]},
        "terminalInitialized": initialized,
        "terminal": terminal,
        "account": account,
        "lastError": last_error,
        "profiles": load_profiles(runtime_dir, config),
        "auditLedger": str(runtime_path(runtime_dir, AUDIT_LEDGER_NAME)),
    }
    return payload


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    visible = deepcopy(config)
    for key in list(visible):
        if key.startswith("_"):
            continue
        if key.lower() in {"password", "secret", "signature"}:
            visible[key] = "[REDACTED]"
    visible.update(
        {
            "tradingEnabled": False,
            "dryRun": True,
            "killSwitch": True,
            "ownerMode": "SHADOW_READONLY",
            "allowDashboardMarketOrders": False,
            "allowDashboardPendingOrders": False,
            "allowDashboardClose": False,
            "allowDashboardCancel": False,
            "allowLogin": False,
            "executionLaneExists": False,
            "legacyConfigIgnored": True,
        }
    )
    return visible


def execute_endpoint(
    endpoint: str,
    request: dict[str, Any],
    *,
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    config_path: Path | None = None,
    mt5: Any | None = None,
    audit: bool = True,
) -> dict[str, Any]:
    endpoint = clean(endpoint, 40)
    request = dict(request or {})
    request["endpoint"] = endpoint
    config = load_config(runtime_dir, config_path)

    requested_dry_run = as_bool(request.get("dryRun"), as_bool(config.get("dryRun"), True))
    if endpoint in SHADOW_SIMULATION_ENDPOINTS and requested_dry_run:
        return shadow_simulation_payload(runtime_dir, endpoint, request, config, audit=audit)
    if endpoint in MUTATING_ENDPOINTS:
        return disabled_mutation_payload(endpoint, config)

    if endpoint == "profiles":
        return {
            "ok": True,
            "mode": MODE,
            "endpoint": endpoint,
            "generatedAtIso": utc_now(),
            "safety": public_safety(config),
            "profiles": load_profiles(runtime_dir, config),
        }

    own_mt5 = False
    if mt5 is None:
        mt5, error = load_mt5_for_action(config, runtime_dir, request, need_live=False)
        if error and endpoint in MUTATING_ENDPOINTS and not as_bool(request.get("dryRun"), as_bool(config.get("dryRun"), True)):
            return error
        own_mt5 = mt5 is not None

    try:
        if endpoint == "status":
            return status_payload(runtime_dir, config, mt5)

        return {
            "ok": False,
            "mode": MODE,
            "endpoint": endpoint,
            "generatedAtIso": utc_now(),
            "error": "unsupported_mt5_trading_endpoint",
            "safety": public_safety(config),
        }
    finally:
        if own_mt5 and mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass


def disabled_mutation_payload(endpoint: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "mode": MODE,
        "endpoint": endpoint,
        "generatedAtIso": utc_now(),
        "status": "BLOCKED",
        "decision": "EXECUTION_LANE_REMOVED",
        "reason": EXECUTION_LANE_REMOVED_REASON,
        "safety": public_safety(config),
        "authLock": {"ok": False, "reasons": [EXECUTION_LANE_REMOVED_REASON]},
        "wouldSendRequest": {},
        "audit": {},
    }


def shadow_simulation_payload(
    runtime_dir: Path,
    endpoint: str,
    request: dict[str, Any],
    config: dict[str, Any],
    *,
    audit: bool = True,
) -> dict[str, Any]:
    state = {
        "endpoint": endpoint,
        "dryRun": True,
        "liveAllowed": False,
        "decision": "DRY_RUN_ACCEPTED",
        "reasons": ["shadow_simulation_only", EXECUTION_LANE_REMOVED_REASON],
        "authLock": {"ok": False, "reasons": [EXECUTION_LANE_REMOVED_REASON]},
        "safety": public_safety(config),
    }
    ledger = (
        audit_row(
            runtime_dir,
            endpoint=endpoint,
            request=request,
            state=state,
            decision="DRY_RUN_ACCEPTED",
            reason="shadow_simulation_only",
        )
        if audit
        else {}
    )
    return {
        "ok": True,
        "mode": MODE,
        "endpoint": endpoint,
        "generatedAtIso": utc_now(),
        "status": "SHADOW_ONLY",
        "decision": "DRY_RUN_ACCEPTED",
        "reason": "shadow_simulation_only",
        "safety": state["safety"],
        "authLock": state["authLock"],
        "wouldSendRequest": redact_request(request),
        "audit": {
            "ledgerId": ledger.get("LedgerId"),
            "ledgerPath": str(runtime_path(runtime_dir, AUDIT_LEDGER_NAME)),
        }
        if ledger
        else {},
    }


def blocked_or_dry_run_payload(
    runtime_dir: Path,
    endpoint: str,
    request: dict[str, Any],
    state: dict[str, Any],
    *,
    would_send: dict[str, Any] | None = None,
    audit: bool = True,
    account: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del would_send, account
    if state.get("dryRun") and endpoint in SHADOW_SIMULATION_ENDPOINTS:
        return shadow_simulation_payload(runtime_dir, endpoint, request, DEFAULT_CONFIG, audit=audit)
    return disabled_mutation_payload(endpoint, DEFAULT_CONFIG)


def execute_login(runtime_dir: Path, config: dict[str, Any], request: dict[str, Any], state: dict[str, Any], mt5: Any | None, audit: bool) -> dict[str, Any]:
    del runtime_dir, request, state, mt5, audit
    return disabled_mutation_payload("login", config)


def execute_order(runtime_dir: Path, config: dict[str, Any], request: dict[str, Any], state: dict[str, Any], mt5: Any | None, audit: bool) -> dict[str, Any]:
    del mt5
    if as_bool(request.get("dryRun"), bool(state.get("dryRun"))):
        return shadow_simulation_payload(runtime_dir, "order", request, config, audit=audit)
    return disabled_mutation_payload("order", config)


def execute_close(runtime_dir: Path, config: dict[str, Any], request: dict[str, Any], state: dict[str, Any], mt5: Any | None, audit: bool) -> dict[str, Any]:
    del mt5
    if as_bool(request.get("dryRun"), bool(state.get("dryRun"))):
        return shadow_simulation_payload(runtime_dir, "close", request, config, audit=audit)
    return disabled_mutation_payload("close", config)


def execute_cancel(runtime_dir: Path, config: dict[str, Any], request: dict[str, Any], state: dict[str, Any], mt5: Any | None, audit: bool) -> dict[str, Any]:
    del mt5
    if as_bool(request.get("dryRun"), bool(state.get("dryRun"))):
        return shadow_simulation_payload(runtime_dir, "cancel", request, config, audit=audit)
    return disabled_mutation_payload("cancel", config)


def parse_payload_arg(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_json:
        try:
            value = json.loads(args.payload_json)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid --payload-json: {exc}") from exc
    if args.payload_file:
        return read_json(Path(args.payload_file))
    return {}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QuantGod guarded MT5 trading bridge")
    parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), default="status")
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--config", default="")
    parser.add_argument("--payload-json", default="")
    parser.add_argument("--payload-file", default="")
    parser.add_argument("--dry-run", action="store_true", help="Force request dry-run.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    config_path = Path(args.config) if args.config else None
    try:
        payload = parse_payload_arg(args)
        if args.dry_run:
            payload["dryRun"] = True
        result = execute_endpoint(args.endpoint, payload, runtime_dir=runtime_dir, config_path=config_path)
    except Exception as exc:
        config = load_config(runtime_dir, config_path)
        result = {
            "ok": False,
            "mode": MODE,
            "endpoint": args.endpoint,
            "generatedAtIso": utc_now(),
            "error": str(exc),
            "safety": public_safety(config),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
