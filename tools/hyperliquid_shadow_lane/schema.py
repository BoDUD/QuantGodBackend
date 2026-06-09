from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


SCHEMA_VERSION = "quantgod.hyperliquid_shadow_lane.v1"
REPORT_FILE = "QuantGod_HyperliquidShadowLane.json"

SAFETY: Dict[str, Any] = {
    "readOnly": True,
    "shadowOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "walletAuthorizationAllowed": False,
    "credentialStorageAllowed": False,
    "apiTradingAllowed": False,
    "copyTradeExecutionAllowed": False,
    "hyperliquidOrderSendAllowed": False,
    "mossFollowExecutionAllowed": False,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def shadow_dir(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "hyperliquid_shadow"


def report_path(runtime_dir: Path) -> Path:
    return shadow_dir(runtime_dir) / REPORT_FILE
