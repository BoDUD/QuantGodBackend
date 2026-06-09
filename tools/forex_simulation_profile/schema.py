from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "quantgod.forex_mt5_simulation_profile_review.v1"
PROFILE_FILE = "QuantGod_ForexMt5SimulationProfileReview.json"
TRADES_FILE = "QuantGod_ForexMt5SimulationTrades.csv"

SAFETY: dict[str, Any] = {
    "localOnly": True,
    "readOnlyResearchPlane": True,
    "advisoryOnly": True,
    "usdJpyOnly": True,
    "paperSimulationOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "mt5OrderSendAllowed": False,
    "eaOrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "writesMt5Preset": False,
    "livePresetMutationAllowed": False,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def forex_dir(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "forex"


def simulation_profile_review_path(runtime_dir: Path) -> Path:
    return forex_dir(runtime_dir) / PROFILE_FILE


def simulation_trades_path(runtime_dir: Path) -> Path:
    return forex_dir(runtime_dir) / TRADES_FILE
