from __future__ import annotations

from pathlib import Path
from typing import Any


PRESET_RELATIVE_PATH = Path("MQL5/Presets/QuantGod_MT5_HFM_LivePilot.set")


def read_set_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def set_bool(values: dict[str, str], key: str, default: bool = False) -> bool:
    raw = str(values.get(key, "")).strip().lower()
    if raw in {"true", "1", "yes", "on"}:
        return True
    if raw in {"false", "0", "no", "off"}:
        return False
    return default


def set_float(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(str(values.get(key, default)).strip())
    except Exception:
        return default


def load_live_preset(repo_root: Path) -> dict[str, Any]:
    path = repo_root / PRESET_RELATIVE_PATH
    values = read_set_file(path)
    if not values:
        return {
            "found": False,
            "path": str(path),
            "ready": False,
            "reasons": ["未找到 legacy preset，无法确认 Shadow/ReadOnly 兼容状态"],
        }
    checks = {
        "watchlistUsdJpy": values.get("Watchlist") in {"USDJPY", "USDJPYc"},
        "shadowOn": set_bool(values, "ShadowMode", False),
        "readOnlyOn": set_bool(values, "ReadOnlyMode", False),
        "autoTradingOff": not set_bool(values, "EnablePilotAutoTrading", True),
        "rsiLiveOff": not set_bool(values, "EnablePilotRsiH1Live", True),
        "maLiveOff": not set_bool(values, "EnablePilotMA", False),
        "bbLiveOff": not set_bool(values, "EnablePilotBBH1Live", False),
        "macdLiveOff": not set_bool(values, "EnablePilotMacdH1Live", False),
        "srLiveOff": not set_bool(values, "EnablePilotSRM15Live", False),
        "nonRsiAuthOff": not set_bool(values, "EnableNonRsiLegacyLiveAuthorization", False),
    }
    failed = [key for key, ok in checks.items() if not ok]
    return {
        "found": True,
        "path": str(path),
        "ready": not failed,
        "checks": checks,
        "failedChecks": failed,
        "watchlist": values.get("Watchlist", ""),
        "maxEaPositions": int(set_float(values, "PilotMaxTotalPositions", 1.0)),
        "pilotLotSize": set_float(values, "PilotLotSize", 0.01),
        "maxFloatingLossUSC": set_float(values, "PilotMaxFloatingLossUSC", 30.0),
        "rsiBuyRoutePreserved": False,
        "shadowRoutes": ["RSI_Reversal", "MA_Cross", "BB_Triple", "MACD_Divergence", "SR_Breakout"],
        "reasons": ["legacy preset 已锁定 Shadow/ReadOnly，所有 live 开关关闭"] if not failed else [f"preset 检查未通过：{', '.join(failed)}"],
    }
