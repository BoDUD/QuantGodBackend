from __future__ import annotations

import os
from pathlib import Path
from typing import Any


SECONDARY_SCOPE_ALIASES = {"secondary", "live16", "hfm-live16", "hfm_live16", "crypto", "hfm-crypto"}
PRIMARY_SCOPE_ALIASES = {"primary", "live12", "hfm-live12", "hfm_live12", "default"}


def normalize_hfm_crypto_scope(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in SECONDARY_SCOPE_ALIASES:
        return "secondary"
    if text in PRIMARY_SCOPE_ALIASES:
        return "primary"
    return text


def mac_secondary_mt5_files_dir() -> Path:
    return (
        Path.home()
        / "Library/Application Support/net.metaquotes.wine.metatrader5-live16/drive_c/Program Files/MetaTrader 5/MQL5/Files"
    )


def _path_from_root(root: str) -> str:
    return str(Path(root).expanduser() / "MQL5" / "Files") if root else ""


def _path_from_wine_prefix(prefix: str) -> str:
    return (
        str(Path(prefix).expanduser() / "drive_c" / "Program Files" / "MetaTrader 5" / "MQL5" / "Files")
        if prefix
        else ""
    )


def secondary_runtime_candidates() -> list[Path]:
    raw_candidates = [
        os.environ.get("QG_HFM_CRYPTO_RUNTIME_DIR", ""),
        os.environ.get("QG_MT5_SECONDARY_FILES_DIR", ""),
        _path_from_root(os.environ.get("QG_MT5_SECONDARY_ROOT", "")),
        _path_from_wine_prefix(os.environ.get("QG_MT5_SECONDARY_WINE_PREFIX", "")),
        str(mac_secondary_mt5_files_dir()),
    ]
    candidates: list[Path] = []
    for raw in raw_candidates:
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def first_existing_secondary_runtime_dir() -> Path | None:
    for candidate in secondary_runtime_candidates():
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def resolve_hfm_crypto_runtime_dir(
    default_runtime_dir: Path | str,
    configured: str | Path | None = None,
    *,
    scope: str | None = None,
    prefer_secondary: bool = False,
) -> Path:
    default = Path(default_runtime_dir).expanduser()
    if configured:
        return Path(configured).expanduser()
    normalized_scope = normalize_hfm_crypto_scope(scope or os.environ.get("QG_HFM_CRYPTO_SCOPE", ""))
    if normalized_scope == "primary":
        return default
    if normalized_scope == "secondary" or prefer_secondary or os.environ.get("QG_HFM_CRYPTO_RUNTIME_DIR"):
        secondary = first_existing_secondary_runtime_dir()
        if secondary:
            return secondary
    return default


def hfm_crypto_runtime_scope_meta(
    default_runtime_dir: Path | str,
    configured: str | Path | None = None,
    *,
    scope: str | None = None,
    prefer_secondary: bool = False,
) -> dict[str, str]:
    requested_scope = scope or os.environ.get("QG_HFM_CRYPTO_SCOPE", "")
    normalized_scope = normalize_hfm_crypto_scope(requested_scope)
    resolved = resolve_hfm_crypto_runtime_dir(
        default_runtime_dir,
        configured,
        scope=requested_scope,
        prefer_secondary=prefer_secondary,
    )
    secondary = first_existing_secondary_runtime_dir()
    uses_secondary = bool(secondary and resolved == secondary) or normalized_scope == "secondary"
    return {
        "scope": "secondary" if uses_secondary else "primary",
        "requestedScope": requested_scope or ("secondary" if uses_secondary else "primary"),
        "accountLabel": "HFM Live16 crypto CFD" if uses_secondary else "HFM primary MT5",
        "runtimeDir": str(resolved),
    }
