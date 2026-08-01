#!/usr/bin/env python3
"""Local MT5 platform store for QuantGod.

This is the QuantDinger-style product layer for QuantGod's MT5 port.  It keeps
account profile metadata, strategy configs, pending-order intent queues,
symbol catalogs, platform positions/trades, connection events, and audit
ledger mirrors in one local SQLite database.

The store is intentionally a control-plane component.  It may write local
SQLite/JSON artifacts and dry-run audit rows, but it never stores raw passwords,
places trades, closes positions, cancels orders, changes presets, or relaxes
the EA-owned live path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import mt5_readonly_bridge
    import mt5_symbol_registry
    import mt5_trading_client
except ImportError:  # pragma: no cover - direct import in unit tests.
    sys.path.append(str(Path(__file__).resolve().parent))
    import mt5_readonly_bridge  # type: ignore
    import mt5_symbol_registry  # type: ignore
    import mt5_trading_client  # type: ignore


DEFAULT_RUNTIME_DIR = Path(r"C:\Program Files\HFM Metatrader 5\MQL5\Files")
DB_NAME = "QuantGod_MT5Platform.db"
OUTPUT_NAME = "QuantGod_MT5PlatformState.json"
TRADING_LEDGER_NAME = "QuantGod_MT5TradingAuditLedger.csv"
PENDING_LEDGER_NAME = "QuantGod_MT5PendingOrderLedger.csv"
MODE = "MT5_PLATFORM_STORE_V3"

ENDPOINTS = {
    "status",
    "operator",
    "credentials",
    "credential",
    "connect",
    "disconnect",
    "strategies",
    "strategy",
    "queue",
    "enqueue",
    "quick-trade",
    "dispatch",
    "queue-retry",
    "queue-cancel",
    "queue-archive",
    "worker-run",
    "ledger",
    "quick-trades",
    "task-runs",
    "positions",
    "trades",
    "symbols",
    "reconcile",
}

SAFETY = {
    "readOnly": False,
    "controlPlaneOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "credentialStorageAllowed": False,
    "credentialMetadataStorageAllowed": True,
    "rawPasswordStorageAllowed": False,
    "pendingOrderQueueAllowed": True,
    "quickTradeAllowed": True,
    "dbPendingWorkerAllowed": True,
    "dispatchLiveAllowed": False,
    "dryRunRequired": True,
    "authLockRequiredForLive": True,
    "auditLedgerRequired": True,
    "exchangeOrderIdLedgerAllowed": True,
    "positionLifecycleMirrorAllowed": True,
    "staticSymbolCatalogAllowed": True,
    "livePresetMutationAllowed": False,
    "symbolSelectAllowed": False,
    "mutatesMt5": False,
}

SECRET_KEYS = {
    "password",
    "mt5_password",
    "account_password",
    "secret",
    "token",
    "private_key",
    "signature",
    "api_secret",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clean(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def clean_status(value: Any, default: str = "active") -> str:
    normalized = clean(value or default, 40).lower().replace(" ", "_")
    return normalized or default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(str(value)))
    except Exception:
        return default


def bool_int(value: Any) -> int:
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "y", "on"} else 0


def first_value(*values: Any, default: Any = "") -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def stable_id(prefix: str, *parts: Any) -> str:
    text = "|".join(clean(part, 500) for part in parts if part not in (None, ""))
    if not text:
        text = str(uuid.uuid4())
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def redact_secret_fields(payload: Any) -> Any:
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            normalized = clean(key, 80).lower()
            if normalized in SECRET_KEYS or "password" in normalized or normalized.endswith("_key"):
                result[key] = "[REDACTED]" if value not in (None, "") else ""
            else:
                result[key] = redact_secret_fields(value)
        return result
    if isinstance(payload, list):
        return [redact_secret_fields(item) for item in payload]
    return payload


def is_raw_secret_key(key: Any) -> bool:
    normalized = clean(key, 80).lower()
    reference_keys = {
        "passwordenvvar",
        "password_env_var",
        "secretref",
        "secret_ref",
        "api_key_hint",
    }
    compact = normalized.replace("_", "")
    if normalized in reference_keys or compact in reference_keys:
        return False
    return normalized in SECRET_KEYS or "password" in normalized


def has_raw_secret(payload: dict[str, Any]) -> bool:
    for key, value in payload.items():
        if value not in (None, "") and is_raw_secret_key(key):
            return True
    return False


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.DatabaseError:
        return set()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in existing_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_schema_columns(conn: sqlite3.Connection) -> None:
    pending_columns = {
        "dispatch_note": "TEXT NOT NULL DEFAULT ''",
        "filled": "REAL NOT NULL DEFAULT 0",
        "avg_price": "REAL NOT NULL DEFAULT 0",
        "executed_at": "TEXT",
        "owner_mode": "TEXT NOT NULL DEFAULT 'EA_ONLY'",
    }
    for column, definition in pending_columns.items():
        ensure_column(conn, "pending_orders", column, definition)

    position_columns = {
        "highest_price": "REAL NOT NULL DEFAULT 0",
        "lowest_price": "REAL NOT NULL DEFAULT 0",
        "pnl_percent": "REAL NOT NULL DEFAULT 0",
        "equity": "REAL NOT NULL DEFAULT 0",
    }
    for column, definition in position_columns.items():
        ensure_column(conn, "qd_strategy_positions", column, definition)

    trade_columns = {
        "commission": "REAL NOT NULL DEFAULT 0",
        "commission_ccy": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in trade_columns.items():
        ensure_column(conn, "qd_strategy_trades", column, definition)

    symbol_columns = {
        "market_type": "TEXT NOT NULL DEFAULT ''",
        "standard_lot": "REAL NOT NULL DEFAULT 0",
        "min_lot": "REAL NOT NULL DEFAULT 0",
        "lot_step": "REAL NOT NULL DEFAULT 0",
        "max_lot": "REAL NOT NULL DEFAULT 0",
        "contract_unit": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in symbol_columns.items():
        ensure_column(conn, "qd_market_symbols", column, definition)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS operators (
            operator_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at_iso TEXT NOT NULL,
            updated_at_iso TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS role_permissions (
            role TEXT NOT NULL,
            permission TEXT NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 0,
            updated_at_iso TEXT NOT NULL,
            PRIMARY KEY (role, permission)
        );
        CREATE TABLE IF NOT EXISTS product_features (
            feature_key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            description TEXT NOT NULL,
            updated_at_iso TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_runs (
            task_id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at_iso TEXT NOT NULL,
            finished_at_iso TEXT,
            summary_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            event_time_iso TEXT NOT NULL,
            decision TEXT NOT NULL,
            actor TEXT NOT NULL,
            route TEXT,
            canonical_symbol TEXT,
            broker_symbol TEXT,
            action TEXT,
            dry_run INTEGER NOT NULL DEFAULT 1,
            live_allowed INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS qd_exchange_credentials (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL DEFAULT '',
            exchange_id TEXT NOT NULL DEFAULT 'mt5',
            api_key_hint TEXT NOT NULL DEFAULT '',
            encrypted_config TEXT NOT NULL DEFAULT '{}',
            credential_type TEXT NOT NULL DEFAULT 'mt5_profile_ref',
            broker TEXT NOT NULL DEFAULT 'MT5',
            mt5_server TEXT NOT NULL DEFAULT '',
            mt5_login TEXT NOT NULL DEFAULT '',
            terminal_path TEXT NOT NULL DEFAULT '',
            password_env_var TEXT NOT NULL DEFAULT '',
            secret_ref TEXT NOT NULL DEFAULT '',
            raw_secret_present INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS qd_strategies_trading (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL DEFAULT '',
            route TEXT NOT NULL DEFAULT '',
            symbol TEXT NOT NULL DEFAULT '',
            canonical_symbol TEXT NOT NULL DEFAULT '',
            broker_symbol TEXT NOT NULL DEFAULT '',
            market_category TEXT NOT NULL DEFAULT 'Forex',
            market_type TEXT NOT NULL DEFAULT 'forex',
            timeframe TEXT NOT NULL DEFAULT 'M15',
            execution_mode TEXT NOT NULL DEFAULT 'dry_run',
            credential_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'staged',
            trading_config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pending_orders (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            strategy_id TEXT,
            symbol TEXT NOT NULL,
            canonical_symbol TEXT NOT NULL DEFAULT '',
            broker_symbol TEXT NOT NULL DEFAULT '',
            signal_type TEXT NOT NULL DEFAULT '',
            signal_ts INTEGER,
            market_type TEXT NOT NULL DEFAULT 'forex',
            order_type TEXT NOT NULL DEFAULT 'buy_limit',
            side TEXT NOT NULL DEFAULT 'buy',
            amount REAL NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            sl REAL NOT NULL DEFAULT 0,
            tp REAL NOT NULL DEFAULT 0,
            execution_mode TEXT NOT NULL DEFAULT 'dry_run',
            status TEXT NOT NULL DEFAULT 'queued',
            priority INTEGER NOT NULL DEFAULT 5,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            last_error TEXT NOT NULL DEFAULT '',
            dispatch_note TEXT NOT NULL DEFAULT '',
            exchange_id TEXT NOT NULL DEFAULT 'mt5',
            exchange_order_id TEXT NOT NULL DEFAULT '',
            exchange_response_json TEXT NOT NULL DEFAULT '{}',
            filled REAL NOT NULL DEFAULT 0,
            avg_price REAL NOT NULL DEFAULT 0,
            executed_at TEXT,
            owner_mode TEXT NOT NULL DEFAULT 'EA_ONLY',
            dry_run_required INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            processed_at TEXT,
            sent_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders(status);
        CREATE INDEX IF NOT EXISTS idx_pending_orders_strategy_id ON pending_orders(strategy_id);
        CREATE INDEX IF NOT EXISTS idx_pending_orders_symbol ON pending_orders(canonical_symbol, broker_symbol);
        CREATE TABLE IF NOT EXISTS qd_strategy_positions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            strategy_id TEXT,
            symbol TEXT NOT NULL DEFAULT '',
            canonical_symbol TEXT NOT NULL DEFAULT '',
            broker_symbol TEXT NOT NULL DEFAULT '',
            side TEXT NOT NULL DEFAULT '',
            size REAL NOT NULL DEFAULT 0,
            entry_price REAL NOT NULL DEFAULT 0,
            current_price REAL NOT NULL DEFAULT 0,
            highest_price REAL NOT NULL DEFAULT 0,
            lowest_price REAL NOT NULL DEFAULT 0,
            unrealized_pnl REAL NOT NULL DEFAULT 0,
            pnl_percent REAL NOT NULL DEFAULT 0,
            equity REAL NOT NULL DEFAULT 0,
            ticket TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'mt5_readonly_reconcile',
            observed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_positions_strategy_id ON qd_strategy_positions(strategy_id);
        CREATE INDEX IF NOT EXISTS idx_positions_symbol ON qd_strategy_positions(canonical_symbol, broker_symbol);
        CREATE TABLE IF NOT EXISTS qd_strategy_trades (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            strategy_id TEXT,
            symbol TEXT NOT NULL DEFAULT '',
            canonical_symbol TEXT NOT NULL DEFAULT '',
            broker_symbol TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT '',
            side TEXT NOT NULL DEFAULT '',
            price REAL NOT NULL DEFAULT 0,
            amount REAL NOT NULL DEFAULT 0,
            value REAL NOT NULL DEFAULT 0,
            profit REAL NOT NULL DEFAULT 0,
            fee REAL NOT NULL DEFAULT 0,
            commission REAL NOT NULL DEFAULT 0,
            commission_ccy TEXT NOT NULL DEFAULT '',
            exchange_order_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            opened_at TEXT,
            closed_at TEXT,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_trades_strategy_id ON qd_strategy_trades(strategy_id);
        CREATE INDEX IF NOT EXISTS idx_trades_symbol ON qd_strategy_trades(canonical_symbol, broker_symbol);
        CREATE TABLE IF NOT EXISTS qd_market_symbols (
            id TEXT PRIMARY KEY,
            market TEXT NOT NULL DEFAULT 'Forex',
            symbol TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            exchange TEXT NOT NULL DEFAULT 'mt5',
            currency TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            is_hot INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            canonical_symbol TEXT NOT NULL DEFAULT '',
            broker_symbol TEXT NOT NULL DEFAULT '',
            broker_suffix TEXT NOT NULL DEFAULT '',
            asset_class TEXT NOT NULL DEFAULT '',
            market_category TEXT NOT NULL DEFAULT '',
            market_type TEXT NOT NULL DEFAULT '',
            digits INTEGER NOT NULL DEFAULT 0,
            point REAL NOT NULL DEFAULT 0,
            volume_min REAL NOT NULL DEFAULT 0,
            volume_max REAL NOT NULL DEFAULT 0,
            volume_step REAL NOT NULL DEFAULT 0,
            standard_lot REAL NOT NULL DEFAULT 0,
            min_lot REAL NOT NULL DEFAULT 0,
            lot_step REAL NOT NULL DEFAULT 0,
            max_lot REAL NOT NULL DEFAULT 0,
            contract_unit TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(market, symbol, exchange)
        );
        CREATE INDEX IF NOT EXISTS idx_market_symbols_market ON qd_market_symbols(market);
        CREATE INDEX IF NOT EXISTS idx_market_symbols_canonical ON qd_market_symbols(canonical_symbol);
        CREATE TABLE IF NOT EXISTS qd_quick_trades (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            pending_order_id TEXT NOT NULL DEFAULT '',
            route TEXT NOT NULL DEFAULT '',
            canonical_symbol TEXT NOT NULL DEFAULT '',
            broker_symbol TEXT NOT NULL DEFAULT '',
            side TEXT NOT NULL DEFAULT '',
            order_type TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            sl REAL NOT NULL DEFAULT 0,
            tp REAL NOT NULL DEFAULT 0,
            execution_mode TEXT NOT NULL DEFAULT 'dry_run',
            status TEXT NOT NULL DEFAULT 'queued',
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_quick_trades_pending_order ON qd_quick_trades(pending_order_id);
        CREATE TABLE IF NOT EXISTS mt5_connection_sessions (
            session_id TEXT PRIMARY KEY,
            credential_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            event TEXT NOT NULL,
            account_login TEXT NOT NULL DEFAULT '',
            server TEXT NOT NULL DEFAULT '',
            dry_run_required INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    ensure_schema_columns(conn)
    seed_defaults(conn)
    seed_static_symbol_catalog(conn)
    conn.commit()


def seed_defaults(conn: sqlite3.Connection) -> None:
    now = utc_now()
    permissions = [
        ("admin", "mt5:view", 1),
        ("admin", "mt5:dry_run", 1),
        ("admin", "mt5:queue", 1),
        ("admin", "mt5:dispatch_dry_run", 1),
        ("admin", "mt5:request_auth_lock", 1),
        ("admin", "mt5:live_trade", 0),
        ("operator", "mt5:view", 1),
        ("operator", "mt5:dry_run", 1),
        ("operator", "mt5:queue", 1),
        ("operator", "mt5:dispatch_dry_run", 1),
        ("operator", "mt5:request_auth_lock", 0),
        ("operator", "mt5:live_trade", 0),
        ("viewer", "mt5:view", 1),
        ("viewer", "mt5:dry_run", 0),
        ("viewer", "mt5:queue", 0),
        ("viewer", "mt5:dispatch_dry_run", 0),
        ("viewer", "mt5:request_auth_lock", 0),
        ("viewer", "mt5:live_trade", 0),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO role_permissions(role, permission, allowed, updated_at_iso)
        VALUES (?, ?, ?, ?)
        """,
        [(role, perm, allowed, now) for role, perm, allowed in permissions],
    )
    features = [
        ("mt5_readonly_bridge", "enabled", "status/account/positions/orders/symbols/quote"),
        ("mt5_symbol_registry", "enabled", "broker symbol to canonical symbol mapping"),
        ("mt5_profile_registry", "enabled", "MT5 broker profile metadata without raw passwords"),
        ("mt5_strategy_configs", "enabled", "route/symbol/timeframe execution metadata"),
        ("mt5_pending_orders_sqlite", "dry_run", "local pending_orders queue, dry-run dispatch only"),
        ("mt5_position_trade_reconcile", "enabled", "read-only reconcile into local positions/trades"),
        ("mt5_quick_trade_ticket", "dry_run", "quick-ticket intent capture without live sends"),
        ("mt5_trading_bridge", "locked", "guarded order/close/cancel/login path"),
        ("mt5_pending_order_worker", "dry_run", "guarded pending-order queue worker"),
        ("mt5_platform_store", "enabled", "local SQLite control-plane store"),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO product_features(feature_key, status, description, updated_at_iso)
        VALUES (?, ?, ?, ?)
        """,
        [(key, status, desc, now) for key, status, desc in features],
    )


def seed_static_symbol_catalog(conn: sqlite3.Connection) -> None:
    conn.execute(
        "DELETE FROM qd_market_symbols WHERE lower(COALESCE(market_category, '')) <> 'forex'"
    )
    for row in mt5_symbol_registry.static_symbol_catalog():
        upsert_symbol_mapping(conn, row, source="quantdinger_static_catalog")


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def canonical_map(symbol: Any) -> dict[str, Any]:
    broker_symbol = clean(symbol, 80)
    if not broker_symbol:
        return {
            "canonicalSymbol": "",
            "brokerSymbol": "",
            "brokerSuffix": "",
            "assetClass": "",
            "marketCategory": "",
            "marketType": "forex",
        }
    row = mt5_symbol_registry.normalize_symbol_row({"name": broker_symbol})
    return {
        "canonicalSymbol": clean(row.get("canonicalSymbol"), 80).upper(),
        "brokerSymbol": clean(row.get("brokerSymbol") or broker_symbol, 80),
        "brokerSuffix": clean(row.get("brokerSuffix"), 40),
        "assetClass": clean(row.get("assetClass"), 80),
        "marketCategory": clean(row.get("marketCategory") or row.get("assetClass") or "Forex", 80),
        "marketType": clean(row.get("marketType") or row.get("marketCategory") or row.get("assetClass") or "forex", 80).lower(),
        "mapping": row,
    }


def position_side(value: Any) -> str:
    text = clean(value, 40).lower()
    if text in {"0", "buy", "long", "position_type_buy"}:
        return "long"
    if text in {"1", "sell", "short", "position_type_sell"}:
        return "short"
    return text or "unknown"


def order_side(value: Any, order_type: Any = "") -> str:
    text = clean(value or order_type, 40).lower()
    if text.startswith("sell"):
        return "sell"
    return "buy"


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


def fetch_rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def audit_platform_event(
    conn: sqlite3.Connection,
    *,
    decision: str,
    action: str,
    payload: dict[str, Any] | None = None,
    actor: str = "dashboard_or_platform_store",
    route: str = "",
    canonical_symbol: str = "",
    broker_symbol: str = "",
    dry_run: bool = True,
    live_allowed: bool = False,
) -> dict[str, Any]:
    event_time = utc_now()
    safe_payload = redact_secret_fields(payload or {})
    event_id = stable_id("platform_evt", decision, action, route, canonical_symbol, broker_symbol, event_time, uuid.uuid4())
    conn.execute(
        """
        INSERT OR IGNORE INTO audit_events(
            event_id, source, event_time_iso, decision, actor, route,
            canonical_symbol, broker_symbol, action, dry_run, live_allowed, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            "mt5_platform_store",
            event_time,
            clean(decision, 120),
            clean(actor, 120),
            clean(route, 80),
            clean(canonical_symbol, 80),
            clean(broker_symbol, 80),
            clean(action, 80),
            1 if dry_run else 0,
            1 if live_allowed else 0,
            json_dumps(safe_payload),
        ),
    )
    return {"eventId": event_id, "eventTimeIso": event_time, "decision": decision, "action": action}


def sync_trading_ledger(conn: sqlite3.Connection, path: Path) -> int:
    rows = read_csv_rows(path)
    inserted = 0
    for row in rows:
        event_id = clean(row.get("LedgerId"), 120)
        if not event_id:
            continue
        payload = json_dumps(row)
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO audit_events(
                event_id, source, event_time_iso, decision, actor, route,
                canonical_symbol, broker_symbol, action, dry_run, live_allowed, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                "mt5_trading_ledger",
                clean(row.get("EventTimeIso"), 80),
                clean(row.get("Decision"), 80),
                "dashboard_or_bridge",
                clean(row.get("Route"), 80),
                clean(row.get("CanonicalSymbol"), 80),
                clean(row.get("BrokerSymbol"), 80),
                clean(row.get("Action"), 80),
                bool_int(row.get("DryRun", "true")),
                bool_int(row.get("LiveAllowed", "false")),
                payload,
            ),
        )
        inserted += int(cur.rowcount > 0)
    conn.commit()
    return inserted


def sync_pending_ledger(conn: sqlite3.Connection, path: Path) -> int:
    rows = read_csv_rows(path)
    inserted = 0
    for row in rows:
        event_id = clean(row.get("LedgerId"), 120)
        if not event_id:
            continue
        payload = json_dumps(row)
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO audit_events(
                event_id, source, event_time_iso, decision, actor, route,
                canonical_symbol, broker_symbol, action, dry_run, live_allowed, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                "mt5_pending_worker_ledger",
                clean(row.get("EventTimeIso"), 80),
                clean(row.get("Decision"), 80),
                "pending_worker",
                clean(row.get("Route"), 80),
                clean(row.get("CanonicalSymbol"), 80),
                clean(row.get("BrokerSymbol"), 80),
                "pending_order",
                bool_int(row.get("DryRun", "true")),
                bool_int(row.get("LiveAllowed", "false")),
                payload,
            ),
        )
        inserted += int(cur.rowcount > 0)
    conn.commit()
    return inserted


def sync_audit_trades(conn: sqlite3.Connection) -> int:
    events = fetch_rows(
        conn,
        """
        SELECT event_id, event_time_iso, decision, route, canonical_symbol, broker_symbol,
               action, payload_json
        FROM audit_events
        WHERE action IN ('order', 'close', 'cancel', 'pending_order')
        ORDER BY event_time_iso DESC
        LIMIT 500
        """,
    )
    inserted = 0
    for event in events:
        trade_id = f"audit_{event['event_id']}"
        try:
            raw_payload = json.loads(event.get("payload_json") or "{}")
        except Exception:
            raw_payload = {}
        broker_symbol = clean(event.get("broker_symbol") or raw_payload.get("BrokerSymbol") or raw_payload.get("symbol"), 80)
        mapping = canonical_map(broker_symbol or event.get("canonical_symbol"))
        side = clean(raw_payload.get("Side") or raw_payload.get("side"), 20).lower()
        amount = as_float(first_value(raw_payload.get("Lots"), raw_payload.get("lots"), raw_payload.get("volume"), default=0), 0.0)
        price = as_float(first_value(raw_payload.get("Price"), raw_payload.get("price"), raw_payload.get("entryPrice"), default=0), 0.0)
        status = clean(event.get("decision"), 80).lower()
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO qd_strategy_trades(
                id, user_id, strategy_id, symbol, canonical_symbol, broker_symbol,
                type, side, price, amount, value, profit, fee, exchange_order_id,
                status, opened_at, closed_at, created_at, payload_json
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                clean(event.get("route"), 80),
                mapping["brokerSymbol"] or broker_symbol,
                mapping["canonicalSymbol"],
                mapping["brokerSymbol"] or broker_symbol,
                clean(event.get("action"), 40),
                side,
                price,
                amount,
                price * amount,
                clean(raw_payload.get("ExchangeOrderId") or raw_payload.get("BrokerOrder") or raw_payload.get("order"), 120),
                status,
                clean(event.get("event_time_iso"), 80),
                clean(event.get("event_time_iso"), 80) if event.get("action") in {"close", "cancel"} else None,
                clean(event.get("event_time_iso"), 80),
                json_dumps(raw_payload),
            ),
        )
        inserted += int(cur.rowcount > 0)
    conn.commit()
    return inserted


def upsert_operator(conn: sqlite3.Connection, operator_id: str, display_name: str, role: str, status: str) -> dict[str, Any]:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO operators(operator_id, display_name, role, status, created_at_iso, updated_at_iso)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(operator_id) DO UPDATE SET
            display_name=excluded.display_name,
            role=excluded.role,
            status=excluded.status,
            updated_at_iso=excluded.updated_at_iso
        """,
        (operator_id, display_name, role, status, now, now),
    )
    audit_platform_event(conn, decision="OPERATOR_UPSERTED", action="operator", payload={"operatorId": operator_id, "role": role}, actor=operator_id)
    conn.commit()
    return {"operatorId": operator_id, "displayName": display_name, "role": role, "status": status}


def upsert_credential(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    safe = redact_secret_fields(deepcopy(payload))
    login = clean(first_value(payload.get("mt5_login"), payload.get("accountLogin"), payload.get("login")), 80)
    server = clean(first_value(payload.get("mt5_server"), payload.get("server")), 160)
    terminal_path = clean(first_value(payload.get("mt5_terminal_path"), payload.get("terminalPath")), 320)
    password_env_var = clean(first_value(payload.get("passwordEnvVar"), payload.get("password_env_var")), 120)
    secret_ref = clean(first_value(payload.get("secretRef"), payload.get("secret_ref")), 160)
    display_name = clean(first_value(payload.get("displayName"), payload.get("name"), payload.get("profileId"), default="MT5 Profile"), 120)
    credential_id = clean(first_value(payload.get("credentialId"), payload.get("profileId"), default=stable_id("cred", server, login, display_name)), 120)
    broker = clean(first_value(payload.get("broker"), payload.get("exchange"), default="MT5"), 80)
    status = clean_status(payload.get("status"), "active")
    raw_secret_present = 1 if has_raw_secret(payload) else 0
    api_key_hint = clean(f"{server}:{login}".strip(":"), 120)
    now = utc_now()
    encrypted_config = {
        "broker": broker,
        "server": server,
        "login": login,
        "terminalPath": terminal_path,
        "passwordEnvVar": password_env_var,
        "secretRef": secret_ref,
        "rawSecretStored": False,
        "rawSecretRejected": bool(raw_secret_present),
        "source": clean(payload.get("source"), 80),
        "metadata": safe,
    }
    conn.execute(
        """
        INSERT INTO qd_exchange_credentials(
            id, user_id, name, exchange_id, api_key_hint, encrypted_config,
            credential_type, broker, mt5_server, mt5_login, terminal_path,
            password_env_var, secret_ref, raw_secret_present, status, created_at, updated_at
        ) VALUES (?, 1, ?, 'mt5', ?, ?, 'mt5_profile_ref', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            api_key_hint=excluded.api_key_hint,
            encrypted_config=excluded.encrypted_config,
            broker=excluded.broker,
            mt5_server=excluded.mt5_server,
            mt5_login=excluded.mt5_login,
            terminal_path=excluded.terminal_path,
            password_env_var=excluded.password_env_var,
            secret_ref=excluded.secret_ref,
            raw_secret_present=excluded.raw_secret_present,
            status=excluded.status,
            updated_at=excluded.updated_at
        """,
        (
            credential_id,
            display_name,
            api_key_hint,
            json_dumps(encrypted_config),
            broker,
            server,
            login,
            terminal_path,
            password_env_var,
            secret_ref,
            raw_secret_present,
            status,
            now,
            now,
        ),
    )
    audit = audit_platform_event(conn, decision="CREDENTIAL_METADATA_UPSERTED", action="credential", payload=encrypted_config, actor=clean(payload.get("actor") or payload.get("source"), 80))
    conn.commit()
    return {
        "credentialId": credential_id,
        "displayName": display_name,
        "broker": broker,
        "server": server,
        "login": login,
        "terminalPath": terminal_path,
        "passwordEnvVar": password_env_var,
        "secretRef": secret_ref,
        "status": status,
        "rawSecretStored": False,
        "rawSecretRejected": bool(raw_secret_present),
        "audit": audit,
    }


def upsert_strategy(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    broker_symbol = clean(first_value(payload.get("brokerSymbol"), payload.get("symbol")), 80)
    mapping = canonical_map(broker_symbol)
    canonical = clean(first_value(payload.get("canonicalSymbol"), mapping["canonicalSymbol"]), 80).upper()
    route = clean(first_value(payload.get("route"), payload.get("strategy"), default="MT5_Strategy"), 80)
    timeframe = clean(first_value(payload.get("timeframe"), payload.get("interval"), default="M15"), 40)
    strategy_id = clean(first_value(payload.get("strategyId"), payload.get("id"), default=stable_id("strat", route, canonical, timeframe)), 120)
    execution_mode = clean(first_value(payload.get("executionMode"), payload.get("execution_mode"), default="dry_run"), 40).lower()
    if execution_mode in {"live", "paper"}:
        execution_mode = "dry_run"
    status = clean_status(payload.get("status"), "staged")
    credential_id = clean(first_value(payload.get("credentialId"), payload.get("profileId")), 120)
    market_category = clean(first_value(payload.get("marketCategory"), mapping["marketCategory"], default="Forex"), 80)
    market_type = clean(first_value(payload.get("marketType"), mapping["marketType"], default="forex"), 80).lower()
    name = clean(first_value(payload.get("displayName"), payload.get("name"), default=f"{route} {canonical}"), 160)
    config = redact_secret_fields({**payload, "executionMode": execution_mode, "canonicalSymbol": canonical, "brokerSymbol": broker_symbol})
    now = utc_now()
    conn.execute(
        """
        INSERT INTO qd_strategies_trading(
            id, user_id, name, route, symbol, canonical_symbol, broker_symbol,
            market_category, market_type, timeframe, execution_mode, credential_id,
            status, trading_config_json, created_at, updated_at
        ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            route=excluded.route,
            symbol=excluded.symbol,
            canonical_symbol=excluded.canonical_symbol,
            broker_symbol=excluded.broker_symbol,
            market_category=excluded.market_category,
            market_type=excluded.market_type,
            timeframe=excluded.timeframe,
            execution_mode=excluded.execution_mode,
            credential_id=excluded.credential_id,
            status=excluded.status,
            trading_config_json=excluded.trading_config_json,
            updated_at=excluded.updated_at
        """,
        (
            strategy_id,
            name,
            route,
            broker_symbol,
            canonical,
            broker_symbol,
            market_category,
            market_type,
            timeframe,
            execution_mode,
            credential_id,
            status,
            json_dumps(config),
            now,
            now,
        ),
    )
    audit = audit_platform_event(conn, decision="STRATEGY_CONFIG_UPSERTED", action="strategy", payload=config, route=route, canonical_symbol=canonical, broker_symbol=broker_symbol)
    conn.commit()
    return {
        "strategyId": strategy_id,
        "displayName": name,
        "route": route,
        "canonicalSymbol": canonical,
        "brokerSymbol": broker_symbol,
        "timeframe": timeframe,
        "executionMode": execution_mode,
        "credentialId": credential_id,
        "status": status,
        "audit": audit,
    }


def enqueue_order(conn: sqlite3.Connection, payload: dict[str, Any], *, quick_trade: bool = False) -> dict[str, Any]:
    broker_symbol = clean(first_value(payload.get("brokerSymbol"), payload.get("symbol")), 80)
    mapping = canonical_map(broker_symbol)
    canonical = clean(first_value(payload.get("canonicalSymbol"), mapping["canonicalSymbol"]), 80).upper()
    route = clean(first_value(payload.get("route"), payload.get("strategy"), payload.get("strategyId"), default="QuickTrade" if quick_trade else "MT5_Strategy"), 80)
    strategy_id = clean(first_value(payload.get("strategyId"), route), 120)
    credential_id = clean(first_value(payload.get("credentialId"), payload.get("profileId")), 120)
    order_type = clean(first_value(payload.get("orderType"), payload.get("order_type"), default="buy_limit"), 40).lower()
    side = order_side(payload.get("side"), order_type)
    lots = as_float(first_value(payload.get("lots"), payload.get("amount"), payload.get("volume"), default=0.0), 0.0)
    price = as_float(first_value(payload.get("price"), payload.get("entryPrice"), default=0.0), 0.0)
    sl = as_float(first_value(payload.get("sl"), payload.get("stopLoss"), default=0.0), 0.0)
    tp = as_float(first_value(payload.get("tp"), payload.get("takeProfit"), default=0.0), 0.0)
    signal_type = clean(first_value(payload.get("signalType"), payload.get("signal_type"), default=side), 40).lower()
    priority = as_int(payload.get("priority"), 5)
    max_attempts = max(1, as_int(payload.get("maxAttempts"), 1))
    now = utc_now()
    order_id = clean(first_value(payload.get("orderId"), payload.get("id"), default=stable_id("po", route, canonical, side, order_type, lots, price, now, uuid.uuid4())), 120)
    safe_payload = redact_secret_fields(
        {
            **payload,
            "source": "dashboard_quick_trade" if quick_trade else clean(payload.get("source") or "dashboard_platform_queue", 80),
            "dryRun": True,
            "dryRunRequired": True,
            "orderSendAllowed": False,
        }
    )
    conn.execute(
        """
        INSERT INTO pending_orders(
            id, user_id, strategy_id, symbol, canonical_symbol, broker_symbol,
            signal_type, signal_ts, market_type, order_type, side, amount,
            price, sl, tp, execution_mode, status, priority, attempts,
            max_attempts, last_error, exchange_id, exchange_order_id,
            exchange_response_json, dry_run_required, payload_json,
            created_at, updated_at, processed_at, sent_at
        ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'dry_run', 'queued', ?, 0, ?, '', 'mt5', '', '{}', 1, ?, ?, ?, NULL, NULL)
        """,
        (
            order_id,
            strategy_id,
            broker_symbol,
            canonical,
            broker_symbol,
            signal_type,
            as_int(payload.get("signalTs"), 0) or None,
            mapping["marketType"],
            order_type,
            side,
            lots,
            price,
            sl,
            tp,
            priority,
            max_attempts,
            json_dumps(safe_payload),
            now,
            now,
        ),
    )
    if quick_trade:
        conn.execute(
            """
            INSERT OR REPLACE INTO qd_quick_trades(
                id, user_id, pending_order_id, route, canonical_symbol, broker_symbol,
                side, order_type, amount, price, sl, tp, execution_mode, status,
                created_at, payload_json
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'dry_run', 'queued', ?, ?)
            """,
            (
                stable_id("qt", order_id, route, canonical, broker_symbol),
                order_id,
                route,
                canonical,
                broker_symbol,
                side,
                order_type,
                lots,
                price,
                sl,
                tp,
                now,
                json_dumps(safe_payload),
            ),
        )
    audit = audit_platform_event(conn, decision="PENDING_ORDER_QUEUED_DRY_RUN_ONLY", action="enqueue", payload=safe_payload, route=route, canonical_symbol=canonical, broker_symbol=broker_symbol)
    conn.commit()
    return {
        "orderId": order_id,
        "strategyId": strategy_id,
        "credentialId": credential_id,
        "route": route,
        "canonicalSymbol": canonical,
        "brokerSymbol": broker_symbol,
        "side": side,
        "orderType": order_type,
        "lots": lots,
        "price": price,
        "sl": sl,
        "tp": tp,
        "status": "queued",
        "dryRunRequired": True,
        "audit": audit,
    }


def update_queue_status(conn: sqlite3.Connection, payload: dict[str, Any], status: str) -> dict[str, Any]:
    order_id = clean(first_value(payload.get("orderId"), payload.get("id")), 120)
    if not order_id:
        return {"ok": False, "error": "orderId_required"}
    now = utc_now()
    if status == "queued":
        conn.execute(
            """
            UPDATE pending_orders
            SET status='queued', attempts=0, last_error='', updated_at=?, processed_at=NULL
            WHERE id=?
            """,
            (now, order_id),
        )
        decision = "PENDING_ORDER_REQUEUED_DRY_RUN_ONLY"
    else:
        conn.execute(
            "UPDATE pending_orders SET status=?, updated_at=?, processed_at=? WHERE id=?",
            (status, now, now, order_id),
        )
        decision = f"PENDING_ORDER_{status.upper()}"
    row = fetch_rows(conn, "SELECT * FROM pending_orders WHERE id=?", (order_id,))
    audit = audit_platform_event(conn, decision=decision, action="queue_status", payload={"orderId": order_id, "status": status}, route=(row[0].get("strategy_id") if row else ""), canonical_symbol=(row[0].get("canonical_symbol") if row else ""), broker_symbol=(row[0].get("broker_symbol") if row else ""))
    conn.commit()
    return {"orderId": order_id, "status": status, "updated": bool(row), "audit": audit}


def platform_order_request(row: dict[str, Any]) -> dict[str, Any]:
    try:
        extra = json.loads(row.get("payload_json") or "{}")
    except Exception:
        extra = {}
    return {
        **extra,
        "endpoint": "order",
        "action": "order",
        "platformOrderId": row.get("id"),
        "strategyId": row.get("strategy_id"),
        "route": extra.get("route") or row.get("strategy_id") or "platform_db_queue",
        "symbol": row.get("broker_symbol") or row.get("symbol"),
        "brokerSymbol": row.get("broker_symbol") or row.get("symbol"),
        "canonicalSymbol": row.get("canonical_symbol"),
        "side": row.get("side"),
        "orderType": row.get("order_type"),
        "lots": as_float(row.get("amount"), 0.0),
        "price": as_float(row.get("price"), 0.0),
        "sl": as_float(row.get("sl"), 0.0),
        "tp": as_float(row.get("tp"), 0.0),
        "dryRun": True,
        "dryRunRequired": True,
        "source": "mt5_platform_db_dispatch",
    }


def broker_execution_fields(result: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    decision = clean(result.get("decision"), 80)
    live_allowed = bool((result.get("safety") or {}).get("orderSendAllowed"))
    order_ticket = clean(first_value(response.get("order"), response.get("order_id"), response.get("deal"), response.get("deal_id")), 120)
    lots = as_float(first_value(response.get("filled"), request.get("lots"), default=0.0), 0.0) if live_allowed else 0.0
    price = as_float(first_value(response.get("price"), request.get("price"), default=0.0), 0.0) if live_allowed else 0.0
    return {
        "decision": decision,
        "exchangeOrderId": order_ticket if live_allowed else "",
        "filled": lots,
        "avgPrice": price,
        "dispatchNote": clean(result.get("reason") or response.get("comment") or decision, 500),
        "liveAllowed": live_allowed,
    }


def dispatch_queued_orders(conn: sqlite3.Connection, runtime_dir: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    max_orders = max(1, min(as_int(first_value(payload.get("maxOrders"), payload.get("limit"), default=10), 10), 50))
    orders = fetch_rows(
        conn,
        """
        SELECT * FROM pending_orders
        WHERE status='queued' AND dry_run_required=1
        ORDER BY priority ASC, created_at ASC
        LIMIT ?
        """,
        (max_orders,),
    )
    rows: list[dict[str, Any]] = []
    accepted = 0
    blocked = 0
    now = utc_now()
    for order in orders:
        request = platform_order_request(order)
        conn.execute(
            "UPDATE pending_orders SET status='processing', attempts=attempts+1, updated_at=? WHERE id=?",
            (now, order["id"]),
        )
        result = mt5_trading_client.execute_endpoint("order", request, runtime_dir=runtime_dir)
        decision = clean(result.get("decision"), 80) or "UNKNOWN"
        status = "dry_run_accepted" if decision == "DRY_RUN_ACCEPTED" else "blocked"
        if status == "dry_run_accepted":
            accepted += 1
        else:
            blocked += 1
        response_json = json_dumps(redact_secret_fields(result))
        exec_fields = broker_execution_fields(result, request)
        processed_at = utc_now()
        conn.execute(
            """
            UPDATE pending_orders
            SET status=?, last_error=?, dispatch_note=?, exchange_order_id=?,
                exchange_response_json=?, filled=?, avg_price=?, executed_at=?,
                updated_at=?, processed_at=?, sent_at=NULL
            WHERE id=?
            """,
            (
                status,
                clean(result.get("reason") or result.get("error"), 500),
                exec_fields["dispatchNote"],
                exec_fields["exchangeOrderId"],
                response_json,
                exec_fields["filled"],
                exec_fields["avgPrice"],
                processed_at if exec_fields["liveAllowed"] else None,
                processed_at,
                processed_at,
                order["id"],
            ),
        )
        audit = audit_platform_event(
            conn,
            decision=f"PLATFORM_DISPATCH_{decision}",
            action="dispatch",
            payload={"order": order, "result": result},
            route=clean(request.get("route"), 80),
            canonical_symbol=clean(order.get("canonical_symbol"), 80),
            broker_symbol=clean(order.get("broker_symbol"), 80),
        )
        rows.append({"orderId": order["id"], "status": status, "decision": decision, "result": result, "audit": audit})
    conn.commit()
    return {
        "processed": len(rows),
        "accepted": accepted,
        "blocked": blocked,
        "rows": rows,
        "dryRunRequired": True,
        "orderSendAllowed": False,
    }


def record_task_run(conn: sqlite3.Connection, task_type: str, status: str, summary: dict[str, Any], *, task_id: str = "") -> dict[str, Any]:
    started = clean(summary.get("startedAtIso") or utc_now(), 80)
    finished = utc_now()
    task_id = clean(task_id or stable_id("task", task_type, started, uuid.uuid4()), 120)
    conn.execute(
        """
        INSERT OR REPLACE INTO task_runs(task_id, task_type, status, started_at_iso, finished_at_iso, summary_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, clean(task_type, 80), clean(status, 80), started, finished, json_dumps(redact_secret_fields(summary))),
    )
    return {"taskId": task_id, "taskType": task_type, "status": status, "startedAtIso": started, "finishedAtIso": finished}


def run_db_pending_worker(conn: sqlite3.Connection, runtime_dir: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    started = utc_now()
    max_orders = max(1, min(as_int(first_value(payload.get("maxOrders"), payload.get("limit"), default=10), 10), 100))
    force_dry_run = str(payload.get("dryRun", "true")).strip().lower() not in {"0", "false", "no", "off"}
    orders = fetch_rows(
        conn,
        """
        SELECT * FROM pending_orders
        WHERE status IN ('queued', 'pending', 'deferred', 'failed') AND attempts < max_attempts
        ORDER BY priority ASC, created_at ASC
        LIMIT ?
        """,
        (max_orders,),
    )
    rows: list[dict[str, Any]] = []
    accepted = 0
    sent = 0
    failed = 0
    deferred = 0
    dry_run = 0

    for order in orders:
        now = utc_now()
        conn.execute(
            "UPDATE pending_orders SET status='processing', attempts=attempts+1, processed_at=?, updated_at=? WHERE id=?",
            (now, now, order["id"]),
        )
        request = platform_order_request(order)
        request["dryRun"] = True if force_dry_run or bool_int(order.get("dry_run_required")) else False
        request["source"] = "mt5_platform_db_worker"
        result = mt5_trading_client.execute_endpoint("order", request, runtime_dir=runtime_dir)
        decision = clean(result.get("decision"), 80) or "UNKNOWN"
        exec_fields = broker_execution_fields(result, request)
        response_json = json_dumps(redact_secret_fields(result))
        finished = utc_now()
        if decision == "ORDER_SEND_ACCEPTED" and exec_fields["exchangeOrderId"]:
            status = "sent"
            accepted += 1
            sent += 1
            sent_at = finished
            executed_at = finished
        elif decision == "DRY_RUN_ACCEPTED":
            status = "dry_run_accepted"
            accepted += 1
            dry_run += 1
            sent_at = None
            executed_at = None
        elif "kill_switch_on" in str(result.get("reason", "")) or "auth_lock" in str(result.get("reason", "")):
            status = "deferred"
            deferred += 1
            sent_at = None
            executed_at = None
        else:
            status = "failed"
            failed += 1
            sent_at = None
            executed_at = None
        conn.execute(
            """
            UPDATE pending_orders
            SET status=?, last_error=?, dispatch_note=?, exchange_order_id=?,
                exchange_response_json=?, filled=?, avg_price=?, executed_at=?,
                updated_at=?, processed_at=?, sent_at=?
            WHERE id=?
            """,
            (
                status,
                clean(result.get("reason") or result.get("error"), 500),
                exec_fields["dispatchNote"],
                exec_fields["exchangeOrderId"],
                response_json,
                exec_fields["filled"],
                exec_fields["avgPrice"],
                executed_at,
                finished,
                finished,
                sent_at,
                order["id"],
            ),
        )
        audit = audit_platform_event(
            conn,
            decision=f"DB_WORKER_{decision}",
            action="db_worker",
            payload={"order": order, "result": result},
            route=clean(request.get("route"), 80),
            canonical_symbol=clean(order.get("canonical_symbol"), 80),
            broker_symbol=clean(order.get("broker_symbol"), 80),
            dry_run=status != "sent",
            live_allowed=status == "sent",
        )
        rows.append(
            {
                "orderId": order["id"],
                "status": status,
                "decision": decision,
                "exchangeOrderId": exec_fields["exchangeOrderId"],
                "filled": exec_fields["filled"],
                "avgPrice": exec_fields["avgPrice"],
                "audit": audit,
            }
        )

    summary = {
        "startedAtIso": started,
        "processed": len(rows),
        "accepted": accepted,
        "sent": sent,
        "dryRunAccepted": dry_run,
        "failed": failed,
        "deferred": deferred,
        "forceDryRun": force_dry_run,
        "orderSendAllowed": sent > 0,
    }
    task = record_task_run(conn, "mt5_db_pending_order_worker", "completed", summary)
    conn.commit()
    return {**summary, "task": task, "rows": rows, "safety": {**SAFETY, "mutatesMt5": sent > 0, "orderSendAllowed": sent > 0}}


def upsert_symbol_mapping(conn: sqlite3.Connection, row: dict[str, Any], *, source: str = "registry") -> bool:
    broker_symbol = clean(first_value(row.get("brokerSymbol"), row.get("name"), row.get("symbol")), 80)
    if not broker_symbol:
        return False
    normalized_input = dict(row)
    normalized_input["name"] = broker_symbol
    normalized = mt5_symbol_registry.normalize_symbol_row(normalized_input)
    market_category = clean(normalized.get("marketCategory"), 80).lower()
    if market_category != "forex":
        return False
    canonical = clean(normalized.get("canonicalSymbol"), 80).upper()
    market = "forex"
    symbol_id = stable_id("sym", market, broker_symbol, "mt5")
    conn.execute(
        """
        INSERT INTO qd_market_symbols(
            id, market, symbol, name, exchange, currency, is_active, is_hot, sort_order,
            canonical_symbol, broker_symbol, broker_suffix, asset_class, market_category,
            market_type, digits, point, volume_min, volume_max, volume_step,
            standard_lot, min_lot, lot_step, max_lot, contract_unit, source, updated_at
        ) VALUES (?, ?, ?, ?, 'mt5', ?, 1, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market, symbol, exchange) DO UPDATE SET
            name=excluded.name,
            currency=excluded.currency,
            canonical_symbol=excluded.canonical_symbol,
            broker_symbol=excluded.broker_symbol,
            broker_suffix=excluded.broker_suffix,
            asset_class=excluded.asset_class,
            market_category=excluded.market_category,
            market_type=excluded.market_type,
            digits=excluded.digits,
            point=excluded.point,
            volume_min=excluded.volume_min,
            volume_max=excluded.volume_max,
            volume_step=excluded.volume_step,
            standard_lot=excluded.standard_lot,
            min_lot=excluded.min_lot,
            lot_step=excluded.lot_step,
            max_lot=excluded.max_lot,
            contract_unit=excluded.contract_unit,
            source=excluded.source,
            updated_at=excluded.updated_at
        """,
        (
            symbol_id,
            market,
            broker_symbol,
            clean(normalized.get("description") or broker_symbol, 255),
            clean(normalized.get("quoteCurrency") or normalized.get("baseCurrency"), 20),
            canonical,
            broker_symbol,
            clean(normalized.get("brokerSuffix"), 40),
            clean(normalized.get("assetClass"), 80),
            clean(normalized.get("marketCategory"), 80),
            clean(normalized.get("marketType"), 80),
            as_int(normalized.get("digits"), 0),
            as_float(normalized.get("point"), 0.0),
            as_float(normalized.get("volumeMin"), 0.0),
            as_float(normalized.get("volumeMax"), 0.0),
            as_float(normalized.get("volumeStep"), 0.0),
            as_float(normalized.get("standardLot"), 0.0),
            as_float(normalized.get("minLot"), 0.0),
            as_float(normalized.get("lotStep"), 0.0),
            as_float(normalized.get("maxLot"), 0.0),
            clean(normalized.get("contractUnit"), 80),
            source,
            utc_now(),
        ),
    )
    return True


def sync_symbol_catalog(conn: sqlite3.Connection, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    source = "payload"
    mappings: list[dict[str, Any]] = []
    if isinstance(payload.get("mappings"), list):
        mappings = [dict(row) for row in payload.get("mappings") or [] if isinstance(row, dict)]
    elif isinstance(payload.get("symbols"), list):
        registry = mt5_symbol_registry.build_registry_from_symbols([dict(row) for row in payload.get("symbols") or [] if isinstance(row, dict)], source="payload")
        mappings = registry.get("mappings", [])
    elif isinstance(payload.get("symbols"), dict) and isinstance(payload["symbols"].get("items"), list):
        registry = mt5_symbol_registry.build_registry_from_symbols([dict(row) for row in payload["symbols"].get("items") or [] if isinstance(row, dict)], source="payload")
        mappings = registry.get("mappings", [])
    else:
        args = argparse.Namespace(endpoint="registry", group=clean(payload.get("group") or "*", 80), query=clean(payload.get("query"), 80), limit=max(1, min(as_int(payload.get("limit"), 2000), 5000)), terminal_path=clean(payload.get("terminalPath"), 320))
        live_payload, error = mt5_symbol_registry.load_live_symbols(args)
        if error:
            return {"ok": False, "error": error.get("error", "mt5_symbol_registry_unavailable"), "detail": error}
        symbols_block = live_payload.get("symbols") if live_payload else {}
        symbols = symbols_block.get("items", []) if isinstance(symbols_block, dict) else []
        registry = mt5_symbol_registry.build_registry_from_symbols(symbols, source="live_mt5", group=args.group, query=args.query)
        mappings = registry.get("mappings", [])
        source = "live_mt5"

    synced = sum(1 for row in mappings if upsert_symbol_mapping(conn, row, source=source))
    audit = audit_platform_event(conn, decision="SYMBOL_CATALOG_SYNCED", action="symbols", payload={"source": source, "count": synced})
    conn.commit()
    return {"ok": True, "source": source, "synced": synced, "audit": audit}


def extract_position_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("positions"), list):
        return [dict(row) for row in payload["positions"] if isinstance(row, dict)]
    positions = payload.get("positions")
    if isinstance(positions, dict) and isinstance(positions.get("items"), list):
        return [dict(row) for row in positions.get("items") or [] if isinstance(row, dict)]
    snapshot = payload.get("snapshot")
    if isinstance(snapshot, dict):
        return extract_position_rows(snapshot)
    mt5, error = mt5_readonly_bridge.load_mt5()
    if error:
        return []
    initialized, _ = mt5_readonly_bridge.initialize_mt5(mt5, clean(payload.get("terminalPath"), 320))
    if not initialized:
        return []
    try:
        block = mt5_readonly_bridge.get_positions(mt5, clean(payload.get("symbol"), 80))
        return [dict(row) for row in block.get("items", []) if isinstance(row, dict)]
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


def extract_order_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("orders"), list):
        return [dict(row) for row in payload["orders"] if isinstance(row, dict)]
    orders = payload.get("orders")
    if isinstance(orders, dict) and isinstance(orders.get("items"), list):
        return [dict(row) for row in orders.get("items") or [] if isinstance(row, dict)]
    snapshot = payload.get("snapshot")
    if isinstance(snapshot, dict):
        return extract_order_rows(snapshot)
    return []


def reconcile_snapshot(conn: sqlite3.Connection, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    positions = extract_position_rows(payload)
    orders = extract_order_rows(payload)
    synced_positions = 0
    synced_orders = 0
    observed = utc_now()
    for row in positions:
        broker_symbol = clean(first_value(row.get("brokerSymbol"), row.get("symbol")), 80)
        mapping = canonical_map(broker_symbol)
        ticket = clean(first_value(row.get("ticket"), row.get("identifier")), 120)
        side = position_side(first_value(row.get("side"), row.get("type")))
        position_id = clean(first_value(row.get("positionId"), row.get("id"), default=stable_id("pos", ticket, mapping["canonicalSymbol"], side)), 120)
        strategy_id = clean(first_value(row.get("strategyId"), row.get("route"), payload.get("strategyId")), 120)
        size = as_float(first_value(row.get("lots"), row.get("volume"), row.get("size"), default=0.0), 0.0)
        entry = as_float(first_value(row.get("entryPrice"), row.get("priceOpen"), row.get("price_open"), default=0.0), 0.0)
        current = as_float(first_value(row.get("currentPrice"), row.get("priceCurrent"), row.get("price_current"), default=0.0), 0.0)
        profit = as_float(first_value(row.get("profit"), row.get("unrealizedPnl"), default=0.0), 0.0)
        highest = as_float(first_value(row.get("highestPrice"), row.get("highest_price"), default=max(entry, current)), max(entry, current))
        lowest_default = min(value for value in [entry, current] if value > 0) if (entry > 0 or current > 0) else 0.0
        lowest = as_float(first_value(row.get("lowestPrice"), row.get("lowest_price"), default=lowest_default), lowest_default)
        notional = abs(entry * size)
        pnl_percent = as_float(first_value(row.get("pnlPercent"), row.get("pnl_percent"), default=(profit / notional * 100.0 if notional > 0 else 0.0)), 0.0)
        equity = as_float(row.get("equity"), 0.0)
        conn.execute(
            """
            INSERT INTO qd_strategy_positions(
                id, user_id, strategy_id, symbol, canonical_symbol, broker_symbol,
                side, size, entry_price, current_price, highest_price, lowest_price,
                unrealized_pnl, pnl_percent, equity, ticket,
                source, observed_at, updated_at, payload_json
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'mt5_readonly_reconcile', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                strategy_id=excluded.strategy_id,
                symbol=excluded.symbol,
                canonical_symbol=excluded.canonical_symbol,
                broker_symbol=excluded.broker_symbol,
                side=excluded.side,
                size=excluded.size,
                entry_price=excluded.entry_price,
                current_price=excluded.current_price,
                highest_price=CASE
                    WHEN qd_strategy_positions.highest_price > excluded.highest_price THEN qd_strategy_positions.highest_price
                    ELSE excluded.highest_price
                END,
                lowest_price=CASE
                    WHEN qd_strategy_positions.lowest_price = 0 THEN excluded.lowest_price
                    WHEN excluded.lowest_price = 0 THEN qd_strategy_positions.lowest_price
                    WHEN excluded.lowest_price < qd_strategy_positions.lowest_price THEN excluded.lowest_price
                    ELSE qd_strategy_positions.lowest_price
                END,
                unrealized_pnl=excluded.unrealized_pnl,
                pnl_percent=excluded.pnl_percent,
                equity=excluded.equity,
                ticket=excluded.ticket,
                source=excluded.source,
                observed_at=excluded.observed_at,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                position_id,
                strategy_id,
                broker_symbol,
                mapping["canonicalSymbol"],
                broker_symbol,
                side,
                size,
                entry,
                current,
                highest,
                lowest,
                profit,
                pnl_percent,
                equity,
                ticket,
                observed,
                observed,
                json_dumps(redact_secret_fields(row)),
            ),
        )
        synced_positions += 1

    for row in orders:
        broker_symbol = clean(first_value(row.get("brokerSymbol"), row.get("symbol")), 80)
        mapping = canonical_map(broker_symbol)
        ticket = clean(first_value(row.get("ticket"), row.get("orderTicket")), 120)
        order_type = clean(first_value(row.get("orderType"), row.get("type"), default="pending"), 40).lower()
        side = order_side(row.get("side"), order_type)
        order_id = clean(first_value(row.get("orderId"), default=stable_id("broker_po", ticket, mapping["canonicalSymbol"], order_type)), 120)
        amount = as_float(first_value(row.get("lots"), row.get("volumeCurrent"), row.get("volume_current"), row.get("volume"), default=0.0), 0.0)
        price = as_float(first_value(row.get("priceOpen"), row.get("price_open"), row.get("price"), default=0.0), 0.0)
        conn.execute(
            """
            INSERT INTO pending_orders(
                id, user_id, strategy_id, symbol, canonical_symbol, broker_symbol,
                signal_type, signal_ts, market_type, order_type, side, amount,
                price, sl, tp, execution_mode, status, priority, attempts,
                max_attempts, last_error, exchange_id, exchange_order_id,
                exchange_response_json, dry_run_required, payload_json,
                created_at, updated_at, processed_at, sent_at
            ) VALUES (?, 1, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 'observed', 'broker_pending_observed', 9, 0, 1, '', 'mt5', ?, ?, 1, ?, ?, ?, NULL, NULL)
            ON CONFLICT(id) DO UPDATE SET
                symbol=excluded.symbol,
                canonical_symbol=excluded.canonical_symbol,
                broker_symbol=excluded.broker_symbol,
                order_type=excluded.order_type,
                side=excluded.side,
                amount=excluded.amount,
                price=excluded.price,
                sl=excluded.sl,
                tp=excluded.tp,
                status=excluded.status,
                exchange_order_id=excluded.exchange_order_id,
                exchange_response_json=excluded.exchange_response_json,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                order_id,
                clean(first_value(row.get("strategyId"), payload.get("strategyId")), 120),
                broker_symbol,
                mapping["canonicalSymbol"],
                broker_symbol,
                side,
                mapping["marketType"],
                order_type,
                side,
                amount,
                price,
                as_float(first_value(row.get("sl"), row.get("stopLoss"), default=0.0), 0.0),
                as_float(first_value(row.get("tp"), row.get("takeProfit"), default=0.0), 0.0),
                ticket,
                json_dumps(redact_secret_fields(row)),
                json_dumps(redact_secret_fields(row)),
                observed,
                observed,
            ),
        )
        synced_orders += 1

    audit = audit_platform_event(conn, decision="READONLY_RECONCILE_SYNCED", action="reconcile", payload={"positions": synced_positions, "orders": synced_orders})
    conn.commit()
    return {"positionsSynced": synced_positions, "ordersSynced": synced_orders, "audit": audit}


def record_connection_event(conn: sqlite3.Connection, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    credential_id = clean(first_value(payload.get("credentialId"), payload.get("profileId")), 120)
    if event == "connect" and (payload.get("mt5_login") or payload.get("accountLogin") or payload.get("login") or payload.get("server")):
        credential = upsert_credential(conn, payload)
        credential_id = credential["credentialId"]
    session_id = stable_id("session", event, credential_id, utc_now(), uuid.uuid4())
    login = clean(first_value(payload.get("mt5_login"), payload.get("accountLogin"), payload.get("login")), 80)
    server = clean(first_value(payload.get("mt5_server"), payload.get("server")), 160)
    status = "dry_run_recorded" if event == "connect" else "disconnected_recorded"
    safe_payload = redact_secret_fields({**payload, "event": event, "dryRunRequired": True, "rawSecretStored": False})
    conn.execute(
        """
        INSERT INTO mt5_connection_sessions(
            session_id, credential_id, status, event, account_login, server,
            dry_run_required, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (session_id, credential_id, status, event, login, server, utc_now(), json_dumps(safe_payload)),
    )
    audit = audit_platform_event(conn, decision=f"CONNECTION_{event.upper()}_RECORDED_DRY_RUN_ONLY", action=event, payload=safe_payload)
    conn.commit()
    return {
        "sessionId": session_id,
        "credentialId": credential_id,
        "event": event,
        "status": status,
        "dryRunRequired": True,
        "rawSecretStored": False,
        "audit": audit,
    }


def parse_json_field(row: dict[str, Any], field: str) -> dict[str, Any]:
    try:
        value = json.loads(row.get(field) or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def build_state(conn: sqlite3.Connection, runtime_dir: Path, db_path: Path, sync: bool, *, action: dict[str, Any] | None = None) -> dict[str, Any]:
    inserted = {"trading": 0, "pending": 0, "trades": 0}
    if sync:
        inserted["trading"] = sync_trading_ledger(conn, runtime_dir / TRADING_LEDGER_NAME)
        inserted["pending"] = sync_pending_ledger(conn, runtime_dir / PENDING_LEDGER_NAME)
        inserted["trades"] = sync_audit_trades(conn)

    credentials = fetch_rows(
        conn,
        """
        SELECT id AS credentialId, name AS displayName, broker, mt5_server AS server,
               mt5_login AS login, terminal_path AS terminalPath, password_env_var AS passwordEnvVar,
               secret_ref AS secretRef, raw_secret_present AS rawSecretRejected,
               status, updated_at AS updatedAt
        FROM qd_exchange_credentials
        ORDER BY updated_at DESC
        LIMIT 25
        """,
    )
    strategies = fetch_rows(
        conn,
        """
        SELECT id AS strategyId, name AS displayName, route, canonical_symbol AS canonicalSymbol,
               broker_symbol AS brokerSymbol, market_category AS marketCategory, market_type AS marketType,
               timeframe, execution_mode AS executionMode, credential_id AS credentialId,
               status, updated_at AS updatedAt
        FROM qd_strategies_trading
        ORDER BY updated_at DESC
        LIMIT 50
        """,
    )
    pending_orders = fetch_rows(
        conn,
        """
        SELECT id AS orderId, strategy_id AS strategyId, symbol, canonical_symbol AS canonicalSymbol,
               broker_symbol AS brokerSymbol, signal_type AS signalType, order_type AS orderType,
               side, amount AS lots, price, sl, tp, execution_mode AS executionMode, status,
               priority, attempts, max_attempts AS maxAttempts, last_error AS lastError,
               dispatch_note AS dispatchNote, exchange_order_id AS exchangeOrderId,
               filled, avg_price AS avgPrice, executed_at AS executedAt,
               owner_mode AS ownerMode, dry_run_required AS dryRunRequired,
               created_at AS createdAt, updated_at AS updatedAt, processed_at AS processedAt,
               sent_at AS sentAt
        FROM pending_orders
        ORDER BY updated_at DESC
        LIMIT 100
        """,
    )
    positions = fetch_rows(
        conn,
        """
        SELECT id AS positionId, strategy_id AS strategyId, symbol, canonical_symbol AS canonicalSymbol,
               broker_symbol AS brokerSymbol, side, size AS lots, entry_price AS entryPrice,
               current_price AS currentPrice, highest_price AS highestPrice,
               lowest_price AS lowestPrice, unrealized_pnl AS unrealizedPnl,
               pnl_percent AS pnlPercent, equity, ticket, source,
               observed_at AS observedAt, updated_at AS updatedAt
        FROM qd_strategy_positions
        ORDER BY updated_at DESC
        LIMIT 100
        """,
    )
    trades = fetch_rows(
        conn,
        """
        SELECT id AS tradeId, strategy_id AS strategyId, symbol, canonical_symbol AS canonicalSymbol,
               broker_symbol AS brokerSymbol, type, side, price, amount AS lots, value,
               profit, fee, commission, commission_ccy AS commissionCcy,
               exchange_order_id AS exchangeOrderId, status,
               opened_at AS openedAt, closed_at AS closedAt, created_at AS createdAt
        FROM qd_strategy_trades
        ORDER BY created_at DESC
        LIMIT 100
        """,
    )
    quick_trades = fetch_rows(
        conn,
        """
        SELECT id AS quickTradeId, pending_order_id AS pendingOrderId, route,
               canonical_symbol AS canonicalSymbol, broker_symbol AS brokerSymbol,
               side, order_type AS orderType, amount AS lots, price, sl, tp,
               execution_mode AS executionMode, status, created_at AS createdAt
        FROM qd_quick_trades
        ORDER BY created_at DESC
        LIMIT 100
        """,
    )
    symbol_catalog = fetch_rows(
        conn,
        """
        SELECT market, symbol, name, exchange, currency, canonical_symbol AS canonicalSymbol,
               broker_symbol AS brokerSymbol, broker_suffix AS brokerSuffix, asset_class AS assetClass,
               market_category AS marketCategory, market_type AS marketType, digits, point,
               volume_min AS volumeMin, volume_max AS volumeMax, volume_step AS volumeStep,
               standard_lot AS standardLot, min_lot AS minLot, lot_step AS lotStep,
               max_lot AS maxLot, contract_unit AS contractUnit,
               source, updated_at AS updatedAt
        FROM qd_market_symbols
        WHERE lower(COALESCE(market_category, '')) = 'forex'
        ORDER BY market, canonical_symbol, broker_symbol
        LIMIT 200
        """,
    )
    recent_events = fetch_rows(
        conn,
        """
        SELECT event_id AS eventId, source, event_time_iso AS eventTimeIso, decision,
               route, canonical_symbol AS canonicalSymbol, broker_symbol AS brokerSymbol,
               action, dry_run AS dryRun, live_allowed AS liveAllowed
        FROM audit_events
        ORDER BY event_time_iso DESC
        LIMIT 50
        """,
    )
    connection_sessions = fetch_rows(
        conn,
        """
        SELECT session_id AS sessionId, credential_id AS credentialId, status, event,
               account_login AS login, server, dry_run_required AS dryRunRequired,
               created_at AS createdAt
        FROM mt5_connection_sessions
        ORDER BY created_at DESC
        LIMIT 20
        """,
    )
    task_runs = fetch_rows(
        conn,
        """
        SELECT task_id AS taskId, task_type AS taskType, status,
               started_at_iso AS startedAtIso, finished_at_iso AS finishedAtIso,
               summary_json AS summaryJson
        FROM task_runs
        ORDER BY started_at_iso DESC
        LIMIT 50
        """,
    )
    summary = {
        "operators": table_count(conn, "operators"),
        "rolePermissions": table_count(conn, "role_permissions"),
        "productFeatures": table_count(conn, "product_features"),
        "taskRuns": table_count(conn, "task_runs"),
        "auditEvents": table_count(conn, "audit_events"),
        "liveAllowedEvents": int(conn.execute("SELECT COUNT(*) AS c FROM audit_events WHERE live_allowed=1").fetchone()["c"]),
        "credentials": table_count(conn, "qd_exchange_credentials"),
        "strategies": table_count(conn, "qd_strategies_trading"),
        "pendingOrders": table_count(conn, "pending_orders"),
        "queuedOrders": int(conn.execute("SELECT COUNT(*) AS c FROM pending_orders WHERE status='queued'").fetchone()["c"]),
        "platformPositions": table_count(conn, "qd_strategy_positions"),
        "platformTrades": table_count(conn, "qd_strategy_trades"),
        "quickTrades": table_count(conn, "qd_quick_trades"),
        "symbolCatalog": int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM qd_market_symbols WHERE lower(COALESCE(market_category, ''))='forex'"
            ).fetchone()["c"]
        ),
        "connectionSessions": table_count(conn, "mt5_connection_sessions"),
    }
    ledger_summary = {
        "pendingSent": int(conn.execute("SELECT COUNT(*) AS c FROM pending_orders WHERE status='sent'").fetchone()["c"]),
        "pendingFailed": int(conn.execute("SELECT COUNT(*) AS c FROM pending_orders WHERE status='failed' OR status='blocked'").fetchone()["c"]),
        "pendingDryRunAccepted": int(conn.execute("SELECT COUNT(*) AS c FROM pending_orders WHERE status='dry_run_accepted'").fetchone()["c"]),
        "exchangeOrderIds": int(conn.execute("SELECT COUNT(*) AS c FROM pending_orders WHERE exchange_order_id<>''").fetchone()["c"]),
        "filledRows": int(conn.execute("SELECT COUNT(*) AS c FROM pending_orders WHERE filled>0").fetchone()["c"]),
    }
    payload = {
        "ok": True,
        "mode": MODE,
        "generatedAtIso": utc_now(),
        "runtimeDir": str(runtime_dir),
        "databasePath": str(db_path),
        "safety": SAFETY,
        "sync": {"enabled": sync, "inserted": inserted},
        "summary": summary,
        "features": fetch_rows(conn, "SELECT feature_key AS featureKey, status, description, updated_at_iso AS updatedAtIso FROM product_features ORDER BY feature_key"),
        "operators": fetch_rows(conn, "SELECT operator_id AS operatorId, display_name AS displayName, role, status, updated_at_iso AS updatedAtIso FROM operators ORDER BY operator_id"),
        "credentials": credentials,
        "strategies": strategies,
        "pendingOrders": pending_orders,
        "positions": positions,
        "trades": trades,
        "quickTrades": quick_trades,
        "symbolCatalog": symbol_catalog,
        "connectionSessions": connection_sessions,
        "taskRuns": task_runs,
        "ledgerSummary": ledger_summary,
        "recentAuditEvents": recent_events,
    }
    if action:
        payload["action"] = action
    write_path = runtime_dir / OUTPUT_NAME
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run(
    runtime_dir: Path,
    *,
    db_path: Path | None = None,
    sync: bool = True,
    operator: dict[str, Any] | None = None,
    endpoint: str = "status",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint = clean(endpoint or "status", 40)
    if endpoint not in ENDPOINTS:
        return {"ok": False, "mode": MODE, "endpoint": endpoint, "error": "unsupported_mt5_platform_endpoint", "supportedEndpoints": sorted(ENDPOINTS), "safety": SAFETY}

    database = db_path or (runtime_dir / DB_NAME)
    conn = connect_db(database)
    action: dict[str, Any] | None = None
    try:
        init_db(conn)
        payload = payload or {}
        if operator:
            action = {
                "operator": upsert_operator(
                    conn,
                    clean(operator.get("operatorId") or operator.get("id") or "local-operator", 80),
                    clean(operator.get("displayName") or operator.get("name") or "Local Operator", 120),
                    clean(operator.get("role") or "operator", 40),
                    clean(operator.get("status") or "active", 40),
                )
            }

        if endpoint == "operator" and payload:
            action = {
                "operator": upsert_operator(
                    conn,
                    clean(payload.get("operatorId") or payload.get("id") or "local-operator", 80),
                    clean(payload.get("displayName") or payload.get("name") or "Local Operator", 120),
                    clean(payload.get("role") or "operator", 40),
                    clean(payload.get("status") or "active", 40),
                )
            }
        elif endpoint == "credential":
            action = {"credential": upsert_credential(conn, payload)}
        elif endpoint == "connect":
            action = {"connection": record_connection_event(conn, "connect", payload)}
        elif endpoint == "disconnect":
            action = {"connection": record_connection_event(conn, "disconnect", payload)}
        elif endpoint == "strategy":
            action = {"strategy": upsert_strategy(conn, payload)}
        elif endpoint == "enqueue":
            action = {"pendingOrder": enqueue_order(conn, payload)}
        elif endpoint == "quick-trade":
            action = {"pendingOrder": enqueue_order(conn, payload, quick_trade=True)}
        elif endpoint == "dispatch":
            action = {"dispatch": dispatch_queued_orders(conn, runtime_dir, payload)}
        elif endpoint == "worker-run":
            action = {"worker": run_db_pending_worker(conn, runtime_dir, payload)}
        elif endpoint == "queue-retry":
            action = {"queue": update_queue_status(conn, payload, "queued")}
        elif endpoint == "queue-cancel":
            action = {"queue": update_queue_status(conn, payload, "canceled")}
        elif endpoint == "queue-archive":
            action = {"queue": update_queue_status(conn, payload, "archived")}
        elif endpoint == "symbols":
            action = {"symbols": sync_symbol_catalog(conn, payload)}
        elif endpoint == "reconcile":
            action = {"reconcile": reconcile_snapshot(conn, payload)}

        return build_state(conn, runtime_dir, database, sync, action=action)
    finally:
        conn.close()


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def parse_payload_arg(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_json:
        try:
            value = json.loads(args.payload_json)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid --payload-json: {exc}") from exc
    if args.payload_file:
        return read_json_file(Path(args.payload_file))
    return {}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QuantGod MT5 local platform store")
    parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), default="status")
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR))
    parser.add_argument("--db", default="")
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--operator-json", default="")
    parser.add_argument("--payload-json", default="")
    parser.add_argument("--payload-file", default="")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    operator = json.loads(args.operator_json) if args.operator_json else None
    payload = parse_payload_arg(args)
    result = run(
        Path(args.runtime_dir),
        db_path=Path(args.db) if args.db else None,
        sync=not args.no_sync,
        operator=operator,
        endpoint=args.endpoint,
        payload=payload,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
