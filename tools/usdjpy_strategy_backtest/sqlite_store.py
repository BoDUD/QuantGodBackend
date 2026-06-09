from __future__ import annotations

import math
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .schema import FOCUS_SYMBOL, db_path, ingest_report_path


@dataclass(frozen=True)
class Bar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread: float = 0.0
    real_volume: float = 0.0


BAR_TABLES = {
    "M1": "bars_m1",
    "M5": "bars_m5",
    "M15": "bars_m15",
    "H1": "bars_h1",
    "H4": "bars_h4",
    "D1": "bars_d1",
}

SNAPSHOT_KLINE_KEYS = {
    "M1": "kline_m1",
    "M5": "kline_m5",
    "M15": "kline_m15",
    "H1": "kline_h1",
    "H4": "kline_h4",
    "D1": "kline_d1",
}


def connect(runtime_dir: Path) -> sqlite3.Connection:
    path = db_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = 4
    last_error: sqlite3.OperationalError | None = None
    for attempt in range(attempts):
        conn = sqlite3.connect(path, timeout=60.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 60000")
        try:
            init_schema(conn)
            return conn
        except sqlite3.OperationalError as exc:
            conn.close()
            if "database is locked" not in str(exc).lower():
                raise
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(min(8.0, 1.5 * (attempt + 1)))
    if last_error:
        raise last_error
    raise sqlite3.OperationalError("database connection failed")


def init_schema(conn: sqlite3.Connection) -> None:
    for table in BAR_TABLES.values():
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                spread REAL NOT NULL DEFAULT 0,
                real_volume REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (symbol, timestamp)
            )
            """
        )
        _ensure_column(conn, table, "spread", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, table, "real_volume", "REAL NOT NULL DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_runs (
            run_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            net_r REAL NOT NULL,
            trade_count INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_trades (
            run_id TEXT NOT NULL,
            trade_id TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            exit_time TEXT NOT NULL,
            profit_r REAL NOT NULL,
            profit_pips REAL NOT NULL,
            PRIMARY KEY (run_id, trade_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS equity_curves (
            run_id TEXT NOT NULL,
            index_no INTEGER NOT NULL,
            equity_r REAL NOT NULL,
            PRIMARY KEY (run_id, index_no)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fitness_cache (
            strategy_fingerprint TEXT PRIMARY KEY,
            report_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upsert_bars(conn: sqlite3.Connection, timeframe: str, bars: Iterable[Bar]) -> None:
    table = BAR_TABLES[timeframe]
    conn.executemany(
        f"""
        INSERT OR REPLACE INTO {table}
        (symbol, timestamp, open, high, low, close, volume, spread, real_volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                FOCUS_SYMBOL,
                item.timestamp,
                item.open,
                item.high,
                item.low,
                item.close,
                item.volume,
                item.spread,
                item.real_volume,
            )
            for item in bars
        ],
    )
    conn.commit()


def load_bars(conn: sqlite3.Connection, timeframe: str, limit: int = 1000) -> List[Bar]:
    table = BAR_TABLES[timeframe]
    rows = conn.execute(
        f"""
        SELECT timestamp, open, high, low, close, volume, spread, real_volume
        FROM (
            SELECT timestamp, open, high, low, close, volume, spread, real_volume
            FROM {table}
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
        )
        ORDER BY timestamp ASC
        """,
        (FOCUS_SYMBOL, int(limit)),
    ).fetchall()
    return [
        Bar(
            timestamp=str(row["timestamp"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            spread=float(row["spread"] or 0),
            real_volume=float(row["real_volume"] or 0),
        )
        for row in rows
    ]


def load_bars_range(
    conn: sqlite3.Connection,
    timeframe: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50000,
) -> List[Bar]:
    table = BAR_TABLES[timeframe]
    where = ["symbol = ?"]
    params: List[Any] = [FOCUS_SYMBOL]
    if start:
        where.append("timestamp >= ?")
        params.append(start)
    if end:
        where.append("timestamp <= ?")
        params.append(end)
    params.append(int(limit))
    rows = conn.execute(
        f"""
        SELECT timestamp, open, high, low, close, volume, spread, real_volume
        FROM {table}
        WHERE {' AND '.join(where)}
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        Bar(
            timestamp=str(row["timestamp"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            spread=float(row["spread"] or 0),
            real_volume=float(row["real_volume"] or 0),
        )
        for row in rows
    ]


def count_bars(conn: sqlite3.Connection, timeframe: str) -> int:
    table = BAR_TABLES[timeframe]
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE symbol = ?", (FOCUS_SYMBOL,)).fetchone()
    return int(row["count"] if row else 0)


def latest_bar_time(conn: sqlite3.Connection, timeframe: str) -> str | None:
    table = BAR_TABLES[timeframe]
    row = conn.execute(
        f"SELECT MAX(timestamp) AS latest FROM {table} WHERE symbol = ?",
        (FOCUS_SYMBOL,),
    ).fetchone()
    return str(row["latest"]) if row and row["latest"] else None


def earliest_bar_time(conn: sqlite3.Connection, timeframe: str) -> str | None:
    table = BAR_TABLES[timeframe]
    row = conn.execute(
        f"SELECT MIN(timestamp) AS earliest FROM {table} WHERE symbol = ?",
        (FOCUS_SYMBOL,),
    ).fetchone()
    return str(row["earliest"]) if row and row["earliest"] else None


def bar_coverage_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    timeframes: Dict[str, Any] = {}
    primary_days = 0.0
    primary_count = 0
    for timeframe in BAR_TABLES:
        count = count_bars(conn, timeframe)
        earliest = earliest_bar_time(conn, timeframe)
        latest = latest_bar_time(conn, timeframe)
        span_days = _span_days(earliest, latest)
        timeframes[timeframe] = {
            "barCount": count,
            "earliestBar": earliest,
            "latestBar": latest,
            "spanDays": span_days,
        }
        if timeframe == "H1":
            primary_days = span_days
            primary_count = count
    return {
        "schema": "quantgod.usdjpy_sqlite_history_coverage.v1",
        "symbol": FOCUS_SYMBOL,
        "primaryTimeframe": "H1",
        "primaryBarCount": primary_count,
        "primarySpanDays": primary_days,
        "timeframes": timeframes,
        "evidenceQuality": _history_evidence_quality(primary_days, primary_count),
        "reasonZh": _history_reason(primary_days, primary_count),
    }


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _span_days(earliest: str | None, latest: str | None) -> float:
    start = _parse_time(earliest)
    end = _parse_time(latest)
    if not start or not end or end < start:
        return 0.0
    return round((end - start).total_seconds() / 86400.0, 3)


def _history_evidence_quality(span_days: float, bar_count: int) -> str:
    if span_days >= 365 and bar_count >= 4000:
        return "HIGH"
    if span_days >= 90 and bar_count >= 1000:
        return "MEDIUM_HIGH"
    if span_days >= 30 and bar_count >= 300:
        return "MEDIUM"
    if span_days >= 7 and bar_count >= 120:
        return "LOW_MEDIUM"
    return "LOW"


def _history_reason(span_days: float, bar_count: int) -> str:
    if span_days >= 365 and bar_count >= 4000:
        return "USDJPY SQLite 历史窗口已覆盖一年级别，可用于 GA 样本外筛选。"
    if span_days >= 90 and bar_count >= 1000:
        return "USDJPY SQLite 历史窗口已覆盖季度级别，可用于更可信的多策略比较。"
    if span_days >= 30 and bar_count >= 300:
        return "USDJPY SQLite 历史窗口已覆盖月度级别，可用于初步策略比较。"
    return "USDJPY SQLite 历史窗口仍偏短，GA 结论只能视为 shadow/tester 证据。"


def write_strategy_run(conn: sqlite3.Connection, report: Dict[str, Any]) -> str:
    """Persist the latest Strategy JSON backtest report into audit tables."""
    run_id = str(report.get("runId") or f"{report.get('strategyId')}-{report.get('createdAt')}")
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    conn.execute(
        """
        INSERT OR REPLACE INTO strategy_runs
        (run_id, strategy_id, created_at, net_r, trade_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_id,
            str(report.get("strategyId") or ""),
            str(report.get("createdAt") or datetime.now(timezone.utc).isoformat()),
            float(metrics.get("netR") or 0.0),
            int(metrics.get("tradeCount") or report.get("tradeCount") or 0),
        ),
    )
    conn.execute("DELETE FROM strategy_trades WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM equity_curves WHERE run_id = ?", (run_id,))
    conn.executemany(
        """
        INSERT OR REPLACE INTO strategy_trades
        (run_id, trade_id, entry_time, exit_time, profit_r, profit_pips)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                str(trade.get("tradeId") or f"T{index:04d}"),
                str(trade.get("entryTime") or ""),
                str(trade.get("exitTime") or ""),
                float(trade.get("profitR") or 0.0),
                float(trade.get("profitPips") or 0.0),
            )
            for index, trade in enumerate(report.get("trades") or [], start=1)
            if isinstance(trade, dict)
        ],
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO equity_curves
        (run_id, index_no, equity_r)
        VALUES (?, ?, ?)
        """,
        [
            (run_id, index, float(value or 0.0))
            for index, value in enumerate(report.get("equityCurve") or [], start=1)
        ],
    )
    conn.commit()
    return run_id


def ingest_runtime_snapshot(runtime_dir: Path, snapshot_path: Path | None = None) -> Dict[str, Any]:
    """Incrementally ingest real USDJPY K-lines exported by the MT5 runtime snapshot."""
    source = snapshot_path or runtime_dir / "QuantGod_MT5RuntimeSnapshot_USDJPYc.json"
    report: Dict[str, Any] = {
        "ok": True,
        "schema": "quantgod.usdjpy_kline_ingest_report.v1",
        "symbol": FOCUS_SYMBOL,
        "source": str(source),
        "sourceFound": source.exists(),
        "insertedOrUpdated": {},
        "barCounts": {},
        "latestBars": {},
        "safety": {
            "readOnlyDataPlane": True,
            "orderSendAllowed": False,
            "livePresetMutationAllowed": False,
        },
    }
    if not source.exists():
        ingest_report_path(runtime_dir).parent.mkdir(parents=True, exist_ok=True)
        ingest_report_path(runtime_dir).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    try:
        payload = json.loads(source.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        report.update({"ok": False, "error": f"snapshot_parse_failed: {exc}"})
        ingest_report_path(runtime_dir).parent.mkdir(parents=True, exist_ok=True)
        ingest_report_path(runtime_dir).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    with connect(runtime_dir) as conn:
        for timeframe, key in SNAPSHOT_KLINE_KEYS.items():
            bars = bars_from_snapshot_rows(payload.get(key))
            if bars:
                upsert_bars(conn, timeframe, bars)
            report["insertedOrUpdated"][timeframe] = len(bars)
            report["barCounts"][timeframe] = count_bars(conn, timeframe)
            report["latestBars"][timeframe] = latest_bar_time(conn, timeframe)

    ingest_report_path(runtime_dir).parent.mkdir(parents=True, exist_ok=True)
    ingest_report_path(runtime_dir).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def bars_from_snapshot_rows(rows: Any) -> List[Bar]:
    if not isinstance(rows, list):
        return []
    bars: List[Bar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = str(row.get("timeIso") or row.get("timestamp") or "").strip()
        if not timestamp:
            continue
        try:
            bars.append(
                Bar(
                    timestamp=timestamp,
                    open=float(row.get("open")),
                    high=float(row.get("high")),
                    low=float(row.get("low")),
                    close=float(row.get("close")),
                    volume=float(row.get("volume") or 0),
                    spread=float(row.get("spread") or row.get("spreadPoints") or 0),
                    real_volume=float(row.get("real_volume") or row.get("realVolume") or 0),
                )
            )
        except Exception:
            continue
    return sorted(bars, key=lambda item: item.timestamp)


def write_sample_bars(runtime_dir: Path, overwrite: bool = False) -> dict:
    with connect(runtime_dir) as conn:
        if overwrite:
            for table in BAR_TABLES.values():
                conn.execute(f"DELETE FROM {table} WHERE symbol = ?", (FOCUS_SYMBOL,))
            conn.commit()
        bars = sample_h1_bars()
        upsert_bars(conn, "H1", bars)
        return {"symbol": FOCUS_SYMBOL, "timeframe": "H1", "barCount": count_bars(conn, "H1")}


def sample_h1_bars(count: int = 180) -> List[Bar]:
    """Create deterministic USDJPY H1 bars with RSI oversold/recovery phases."""
    start = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
    price = 156.20
    bars: List[Bar] = []
    for index in range(count):
        wave = math.sin(index / 5.0) * 0.035
        drift = -0.018 if index % 45 < 18 else 0.024
        pulse = 0.075 if index in {24, 25, 70, 71, 116, 117, 162, 163} else 0.0
        shock = -0.055 if index in {18, 64, 110, 156} else 0.0
        previous = price
        close = max(150.0, previous + wave + drift + pulse + shock)
        high = max(previous, close) + 0.035 + abs(wave) * 0.35
        low = min(previous, close) - 0.035 - abs(wave) * 0.35
        timestamp = (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z")
        bars.append(
            Bar(
                timestamp=timestamp,
                open=round(previous, 5),
                high=round(high, 5),
                low=round(low, 5),
                close=round(close, 5),
                volume=1000 + (index % 12) * 37,
                spread=10,
                real_volume=0,
            )
        )
        price = close
    return bars
