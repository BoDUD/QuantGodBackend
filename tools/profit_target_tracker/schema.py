from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "quantgod.profit_target_tracker.v1"
REPORT_FILE = "QuantGod_ProfitTargetTracker.json"

SAFETY: dict[str, Any] = {
    "localOnly": True,
    "readOnlyDataPlane": True,
    "advisoryOnly": True,
    "profitTargetTrackingOnly": True,
    "orderSendAllowed": False,
    "brokerCallsMade": False,
    "requestWritesAllowed": False,
    "requestFilesWritten": False,
    "receiptWritesAllowed": False,
    "receiptFilesWritten": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "mt5OrderSendAllowed": False,
    "eaOrderSendAllowed": False,
    "hfmCryptoExecutionAllowed": False,
    "copyTradeExecutionAllowed": False,
    "mossExecutionAllowed": False,
    "hyperliquidExecutionAllowed": False,
    "walletAuthorizationAllowed": False,
    "livePresetMutationAllowed": False,
    "telegramCommandExecutionAllowed": False,
    "webhookReceiverAllowed": False,
    "credentialStorageAllowed": False,
    "writesMt5Preset": False,
    "writesMt5OrderRequest": False,
    "externalMarketRemoved": True,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def profit_target_dir(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "profit_target"


def report_path(runtime_dir: Path) -> Path:
    return profit_target_dir(runtime_dir) / REPORT_FILE
