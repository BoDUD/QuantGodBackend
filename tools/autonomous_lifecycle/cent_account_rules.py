from __future__ import annotations

import os
from typing import Any, Dict


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, default)).strip())
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(str(os.environ.get(name, default)).strip()))
    except Exception:
        return default


def cent_account_config() -> Dict[str, Any]:
    account_mode = str(os.environ.get("QG_ACCOUNT_MODE", "cent")).strip().lower() or "cent"
    is_cent = account_mode == "cent"
    acceleration = is_cent and _env_bool("QG_CENT_ACCOUNT_ACCELERATION", True)
    fast_promotion = acceleration and _env_bool("QG_CENT_FAST_PROMOTION", True)
    max_lot = min(max(_env_float("QG_AUTO_MAX_LOT", 2.0), 0.0), 2.0)
    return {
        "accountMode": account_mode,
        "accountCurrencyUnit": os.environ.get("QG_ACCOUNT_CURRENCY_UNIT", "USC").strip() or "USC",
        "centAccount": is_cent,
        "centAccountAcceleration": acceleration,
        "centFastPromotion": fast_promotion,
        "maxLot": max_lot,
        "microLiveLot": min(_env_float("QG_CENT_MICRO_LIVE_LOT", 0.05), max_lot),
        "opportunityLot": min(_env_float("QG_CENT_OPPORTUNITY_LOT", 0.10), max_lot),
        "standardLot": min(_env_float("QG_CENT_STANDARD_LOT", 0.35), max_lot),
        "microLiveMinSamples": max(_env_int("QG_CENT_MICRO_LIVE_MIN_SAMPLES", 10), 1),
        "paperLiveMinSamples": max(_env_int("QG_CENT_PAPER_LIVE_MIN_SAMPLES", 10), 1),
        "testerOnlyMinSamples": max(_env_int("QG_CENT_TESTER_ONLY_MIN_SAMPLES", 20), 1),
        "maxConsecutiveLosses": max(_env_int("QG_CENT_MAX_CONSECUTIVE_LOSSES", 2), 1),
        "maxDailyLossR": abs(_env_float("QG_CENT_MAX_DAILY_LOSS_R", 1.0)),
        "safetyNoteZh": (
            "美分账户允许更快收集小仓真实样本，但不能绕过 runtime、"
            "快通道、新闻、点差、连续亏损和日亏损硬门禁。"
        ),
    }


def stage_max_lot(stage: str, config: Dict[str, Any] | None = None) -> float:
    cfg = config or cent_account_config()
    stage = str(stage or "").upper()
    if stage == "MICRO_LIVE":
        return round(float(cfg.get("microLiveLot") or 0.0), 2)
    if stage == "LIVE_LIMITED":
        return round(float(cfg.get("maxLot") or 0.0), 2)
    return 0.0
