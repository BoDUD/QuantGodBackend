from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

AGENT_VERSION = "perfect-v1.0"
SCHEMA_VERSION = 1
FOCUS_SYMBOL = "USDJPYc"
DB_FILE = "usdjpy.sqlite"
REPORT_FILE = "QuantGod_StrategyBacktestReport.json"
TRADES_FILE = "QuantGod_StrategyTrades.csv"
EQUITY_FILE = "QuantGod_StrategyEquityCurve.csv"
INGEST_REPORT_FILE = "QuantGod_USDJPYKlineIngestReport.json"
HISTORY_SYNC_REPORT_FILE = "QuantGod_USDJPYHistoricalKlineSyncReport.json"
BACKTEST_CACHE_FILE = "QuantGod_StrategyBacktestCache.json"
QUALITY_REPORT_FILE = "QuantGod_StrategyBacktestQualityReport.json"
PRODUCTION_STATUS_FILE = "QuantGod_USDJPYHistoryProductionStatus.json"

SAFETY_BOUNDARY: Dict[str, Any] = {
    "usdJpyOnly": True,
    "strategyJsonContract": True,
    "readOnlyResearchPlane": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "livePresetMutationAllowed": False,
    "externalMarketRealMoneyAllowed": False,
    "telegramCommandExecutionAllowed": False,
    "telegramCommandEnv": "QG_TELEGRAM_COMMANDS_ALLOWED=0",
    "backtestDirectLiveAllowed": False,
}


def backtest_dir(runtime_dir: Path) -> Path:
    return runtime_dir / "backtest"


def db_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / DB_FILE


def report_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / REPORT_FILE


def trades_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / TRADES_FILE


def equity_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / EQUITY_FILE


def ingest_report_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / INGEST_REPORT_FILE


def history_sync_report_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / HISTORY_SYNC_REPORT_FILE


def backtest_cache_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / BACKTEST_CACHE_FILE


def quality_report_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / QUALITY_REPORT_FILE


def production_status_path(runtime_dir: Path) -> Path:
    return backtest_dir(runtime_dir) / PRODUCTION_STATUS_FILE


def atomic_write_json(target: Path, payload: Any) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
