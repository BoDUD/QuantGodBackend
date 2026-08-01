from __future__ import annotations

from copy import deepcopy
from typing import Any

from .freshness import utc_now_iso

RUNTIME_SNAPSHOT_SCHEMA = "quantgod.mt5.runtime_snapshot.v1"
ALLOWED_TIMEFRAMES = ("M15", "H1", "H4", "D1")
FORBIDDEN_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "token",
    "apikey",
    "api_key",
    "secret",
    "authorization",
    "bearer",
)
FORBIDDEN_TRUE_SAFETY_FLAGS = (
    "canExecuteTrade",
    "orderSendAllowed",
    "closeAllowed",
    "cancelAllowed",
    "credentialStorageAllowed",
    "livePresetMutationAllowed",
    "canOverrideKillSwitch",
    "telegramCommandExecutionAllowed",
    "telegramWebhookReceiverAllowed",
    "webhookReceiverAllowed",
    "emailDeliveryAllowed",
)


def bridge_safety_payload() -> dict[str, Any]:
    return {
        "mode": "QUANTGOD_P3_2_1_MT5_RUNTIME_EVIDENCE_BRIDGE_V1",
        "phase": "P3-2.1",
        "localOnly": True,
        "readOnlyDataPlane": True,
        "advisoryOnly": True,
        "runtimeEvidenceOnly": True,
        "notificationPushOnly": True,
        "canExecuteTrade": False,
        "orderSendAllowed": False,
        "closeAllowed": False,
        "cancelAllowed": False,
        "credentialStorageAllowed": False,
        "livePresetMutationAllowed": False,
        "canOverrideKillSwitch": False,
        "telegramCommandExecutionAllowed": False,
        "telegramWebhookReceiverAllowed": False,
        "webhookReceiverAllowed": False,
        "emailDeliveryAllowed": False,
        "writesMt5Preset": False,
        "writesMt5OrderRequest": False,
    }


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip()


def safe_symbol_filename(symbol: str) -> str:
    cleaned = normalize_symbol(symbol)
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in cleaned) or "UNKNOWN"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _walk_forbidden_keys(value: Any, *, path: str = "$", out: list[str] | None = None) -> list[str]:
    out = out if out is not None else []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).replace("-", "_").replace(" ", "_").lower()
            compact = normalized.replace("_", "")
            if any(fragment.replace("_", "") in compact for fragment in FORBIDDEN_KEY_FRAGMENTS):
                out.append(f"{path}.{key}")
            _walk_forbidden_keys(child, path=f"{path}.{key}", out=out)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden_keys(child, path=f"{path}[{index}]", out=out)
    return out


def _numeric_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_runtime_snapshot(snapshot: dict[str, Any], *, expected_symbol: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(snapshot, dict):
        return {"ok": False, "errors": ["snapshot_must_be_object"], "warnings": [], "safety": bridge_safety_payload()}

    schema = str(snapshot.get("schema") or "").strip()
    if schema and schema != RUNTIME_SNAPSHOT_SCHEMA:
        warnings.append(f"unexpected_schema:{schema}")
    if not schema:
        warnings.append("missing_schema")

    symbol = normalize_symbol(snapshot.get("symbol") or snapshot.get("brokerSymbol") or snapshot.get("canonicalSymbol"))
    if not symbol:
        errors.append("missing_symbol")
    if expected_symbol and symbol and symbol.upper() != normalize_symbol(expected_symbol).upper():
        errors.append(f"symbol_mismatch:{symbol}!={expected_symbol}")

    current_price = snapshot.get("current_price") or snapshot.get("currentPrice")
    if not isinstance(current_price, dict):
        errors.append("missing_current_price")
    else:
        bid = _numeric_or_none(current_price.get("bid"))
        ask = _numeric_or_none(current_price.get("ask"))
        last = _numeric_or_none(current_price.get("last") or current_price.get("price"))
        if bid is None and ask is None and last is None:
            errors.append("current_price_requires_bid_ask_or_last")

    generated_at = snapshot.get("generatedAt") or snapshot.get("generatedAtIso")
    if not generated_at:
        warnings.append("missing_generatedAt")

    safety = snapshot.get("safety") if isinstance(snapshot.get("safety"), dict) else {}
    for flag in FORBIDDEN_TRUE_SAFETY_FLAGS:
        if _truthy(safety.get(flag)) or _truthy(snapshot.get(flag)):
            errors.append(f"unsafe_truthy_flag:{flag}")
    if safety and safety.get("readOnly") is False:
        errors.append("unsafe_readOnly_false")

    forbidden_keys = _walk_forbidden_keys(snapshot)
    if forbidden_keys:
        errors.append("forbidden_credential_like_keys:" + ",".join(forbidden_keys[:8]))

    for timeframe in ALLOWED_TIMEFRAMES:
        key = f"kline_{timeframe.lower()}"
        value = snapshot.get(key)
        if value is not None and not isinstance(value, list):
            errors.append(f"{key}_must_be_list")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "symbol": symbol,
        "schema": schema or RUNTIME_SNAPSHOT_SCHEMA,
        "safety": bridge_safety_payload(),
    }


def build_sample_snapshot(symbol: str = "USDJPYc", *, generated_at: str | None = None) -> dict[str, Any]:
    clean_symbol = normalize_symbol(symbol) or "USDJPYc"
    now = generated_at or utc_now_iso()
    base = 155.12 if "JPY" in clean_symbol.upper() else 1.0912
    if "XAU" in clean_symbol.upper() or "GOLD" in clean_symbol.upper():
        base = 2310.5
    def bars(step: float) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index in range(8):
            close = base + (index - 4) * step
            rows.append(
                {
                    "timeIso": now,
                    "open": round(close - step, 5),
                    "high": round(close + step * 2, 5),
                    "low": round(close - step * 2, 5),
                    "close": round(close, 5),
                    "volume": 1000 + index,
                    "source": "sample_hfm_ea_runtime",
                }
            )
        return rows

    snapshot = {
        "schema": RUNTIME_SNAPSHOT_SCHEMA,
        "source": "hfm_ea_runtime",
        "generatedAt": now,
        "account": {
            "broker": "HFM",
            "loginRedacted": "***",
            "serverRedacted": "***",
            "balance": 10000.0,
            "equity": 10020.5,
            "margin": 0.0,
            "freeMargin": 10020.5,
        },
        "symbol": clean_symbol,
        "current_price": {
            "symbol": clean_symbol,
            "bid": round(base, 5),
            "ask": round(base + (0.02 if "JPY" in clean_symbol.upper() or "XAU" in clean_symbol.upper() else 0.00017), 5),
            "last": round(base + (0.01 if "JPY" in clean_symbol.upper() or "XAU" in clean_symbol.upper() else 0.00008), 5),
            "spread": 0.02 if "JPY" in clean_symbol.upper() or "XAU" in clean_symbol.upper() else 0.00017,
            "timeIso": now,
        },
        "symbol_info": {"name": clean_symbol, "broker": "HFM", "runtimeSource": "EA read-only file"},
        "open_positions": [],
        "kline_m15": bars(0.01 if "JPY" in clean_symbol.upper() or "XAU" in clean_symbol.upper() else 0.0001),
        "kline_h1": bars(0.02 if "JPY" in clean_symbol.upper() or "XAU" in clean_symbol.upper() else 0.0002),
        "kline_h4": bars(0.04 if "JPY" in clean_symbol.upper() or "XAU" in clean_symbol.upper() else 0.0004),
        "kline_d1": bars(0.08 if "JPY" in clean_symbol.upper() or "XAU" in clean_symbol.upper() else 0.0008),
        "kill_switch_status": {"locked": True, "canOverride": False},
        "news_filter_status": {"active": False},
        "consecutive_loss_state": {"count": 0},
        "daily_pnl": 0.0,
        "safety": deepcopy(bridge_safety_payload()) | {"readOnly": True},
    }
    return snapshot
