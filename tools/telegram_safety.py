from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "y", "on", "allow", "allowed", "enabled"})

# Any truthy flag below is incompatible with the permanent Shadow/read-only
# statement appended to QuantGod Telegram notifications.  Keep this list in one
# module so Notify and the canonical Gateway cannot drift apart.
FORBIDDEN_TELEGRAM_TRUTHY_ENV = (
    "QG_TELEGRAM_COMMANDS_ALLOWED",
    "QG_TELEGRAM_WEBHOOK_RECEIVER_ALLOWED",
    "QG_WEBHOOK_RECEIVER_ALLOWED",
    "QG_ORDER_SEND_ALLOWED",
    "QG_MT5_ORDER_SEND_ALLOWED",
    "QG_MT5_TRADING_ENABLED",
    "QG_CLOSE_ALLOWED",
    "QG_CANCEL_ALLOWED",
    "QG_MODIFY_ALLOWED",
    "QG_CREDENTIAL_STORAGE_ALLOWED",
    "QG_LIVE_PRESET_MUTATION_ALLOWED",
    "QG_MT5_ADAPTIVE_APPLY_ENABLED",
    "QG_CAN_OVERRIDE_KILL_SWITCH",
    "QG_KILL_SWITCH_OVERRIDE_ALLOWED",
    "QG_PILOT_EXECUTION_ALLOWED",
    "QG_PILOT_SAFETY_LOCK_DISABLED",
    "QG_EXECUTION_ALLOWED",
    "QG_AUTO_EXECUTION_ALLOWED",
    "QG_REVIEWED_MT5_REQUEST_WRITE_RELEASE_V1",
    "QG_REVIEWED_EA_REQUEST_READER_RELEASE_V1",
    "QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1",
    "QG_REVIEWED_RECEIPT_WRITER_RELEASE_V1",
    "QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1",
    "QG_EMAIL_DELIVERY_ALLOWED",
    "QG_EXTERNAL_MARKET_ORDER_ALLOWED",
    "QG_WALLET_INTEGRATION_ALLOWED",
    "QG_FUND_TRANSFER_ALLOWED",
    "QG_WITHDRAWAL_ALLOWED",
)

LOCAL_SAFETY_ENV_FILES = (
    ".env",
    ".env.local",
    ".env.auto.local",
    ".env.usdjpy.local",
    ".env.pilot.local",
    ".env.telegram.local",
    ".env.ai.local",
    ".env.deepseek.local",
)


def truthy_env_value(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUTHY_ENV_VALUES


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def local_safety_env_paths(
    *,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    source_environ = os.environ if environ is None else environ
    root = Path(repo_root).expanduser().resolve() if repo_root else _default_repo_root()
    paths: list[Path] = []
    custom = str(source_environ.get("QG_TELEGRAM_ENV_FILE") or "").strip()
    if custom:
        custom_path = Path(custom).expanduser()
        if not custom_path.is_absolute():
            custom_path = root / custom_path
        paths.append(custom_path)
    paths.extend(root / name for name in LOCAL_SAFETY_ENV_FILES)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def _forbidden_values_from_file(path: Path) -> dict[str, str]:
    """Read only forbidden safety keys; never retain Telegram credentials."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    allowed = set(FORBIDDEN_TELEGRAM_TRUTHY_ENV)
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def unsafe_telegram_environment_keys(
    *,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    env_paths: Sequence[Path | str] | None = None,
) -> list[str]:
    """Return truthy unsafe keys with process values taking precedence.

    When a key is absent from the process environment, all relevant local env
    files are checked and any truthy occurrence fails closed.  Only the named
    safety keys are retained; bot tokens, chat ids and other secrets are never
    returned or logged.
    """
    source_environ = os.environ if environ is None else environ
    paths = (
        tuple(Path(path).expanduser().resolve() for path in env_paths)
        if env_paths is not None
        else local_safety_env_paths(repo_root=repo_root, environ=source_environ)
    )
    file_values = [_forbidden_values_from_file(path) for path in paths]
    blocked: list[str] = []
    for key in FORBIDDEN_TELEGRAM_TRUTHY_ENV:
        process_value = source_environ.get(key)
        if process_value is not None and str(process_value).strip() != "":
            if truthy_env_value(process_value):
                blocked.append(key)
            continue
        if any(truthy_env_value(values.get(key)) for values in file_values):
            blocked.append(key)
    return blocked
