#!/usr/bin/env python3
"""Create a private MT5 Shadow runtime config from local account context.

The repository template intentionally contains a synthetic identity.  This tool
hydrates only a separate runtime file and never accepts or copies a password.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, TextIO


EXPECTED_SERVER = "HFMarketsGlobal-" + "Live12"
LOGIN_ENV = "QG_MT5_SHADOW_LOGIN"
SERVER_ENV = "QG_MT5_SHADOW_SERVER"
EXPECTED_SERVER_ENV = "QG_MT5_EXPECTED_SERVER"
RUNTIME_CONFIG_NAME = "QuantGod_MT5_HFM_Shadow_mac.ini"
LOGIN_PATTERN = re.compile(r"[0-9]+")


class HydrationError(ValueError):
    """Raised when local MT5 identity evidence is missing or unsafe."""


@dataclass(frozen=True)
class ShadowIdentity:
    login: str
    server: str
    source: str


def _clean_env_value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name, "")).strip()


def _validate_identity(login: str, server: str, *, source: str) -> ShadowIdentity:
    if not login or LOGIN_PATTERN.fullmatch(login) is None:
        raise HydrationError(f"{source} login must contain ASCII digits only")
    if len(login) > 20:
        raise HydrationError(f"{source} login is outside the supported length")
    if server != EXPECTED_SERVER:
        raise HydrationError(f"{source} server does not match the locked HFM endpoint")
    return ShadowIdentity(login=login, server=server, source=source)


def _identity_from_env(env: Mapping[str, str]) -> ShadowIdentity | None:
    login = _clean_env_value(env, LOGIN_ENV)
    server = _clean_env_value(env, SERVER_ENV)
    if not login and not server:
        return None
    if not login or not server:
        raise HydrationError(
            f"{LOGIN_ENV} and {SERVER_ENV} must be configured together"
        )
    return _validate_identity(login, server, source="local environment")


def _read_common_identity(path: Path) -> ShadowIdentity:
    try:
        file_mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise HydrationError("portable MT5 config/common.ini is missing") from exc
    if stat.S_ISLNK(file_mode) or not stat.S_ISREG(file_mode):
        raise HydrationError("portable MT5 config/common.ini must be a regular file")

    values: dict[str, str] = {}
    common_sections = 0
    in_common = False
    try:
        with path.open("rb") as binary_stream:
            if binary_stream.read(2) != b"\xff\xfe":
                raise HydrationError(
                    "portable MT5 config/common.ini must be UTF-16LE with a BOM"
                )
            with io.TextIOWrapper(
                binary_stream, encoding="utf-16-le", errors="strict", newline=None
            ) as text_stream:
                for raw_line in text_stream:
                    stripped = raw_line.strip()
                    if stripped.startswith("[") and stripped.endswith("]"):
                        in_common = stripped[1:-1].strip().casefold() == "common"
                        if in_common:
                            common_sections += 1
                        continue
                    if not in_common or "=" not in stripped:
                        continue
                    key, value = stripped.split("=", 1)
                    normalized_key = key.strip().casefold()
                    if normalized_key not in {"login", "server"}:
                        # In particular, password material is never retained.
                        continue
                    if normalized_key in values:
                        raise HydrationError(
                            f"portable MT5 common.ini has duplicate {normalized_key}"
                        )
                    values[normalized_key] = value.strip()
    except UnicodeError as exc:
        raise HydrationError("portable MT5 common.ini is not valid UTF-16LE") from exc
    except OSError as exc:
        raise HydrationError("portable MT5 common.ini could not be read") from exc

    if common_sections != 1:
        raise HydrationError("portable MT5 common.ini must contain one [Common] section")
    if set(values) != {"login", "server"}:
        raise HydrationError(
            "portable MT5 common.ini lacks a selected Login/Server pair"
        )
    return _validate_identity(
        values["login"], values["server"], source="portable MT5 common.ini"
    )


def resolve_shadow_identity(
    common_ini: Path, env: Mapping[str, str] | None = None
) -> ShadowIdentity:
    effective_env = os.environ if env is None else env
    declared_expected = _clean_env_value(effective_env, EXPECTED_SERVER_ENV)
    if declared_expected and declared_expected != EXPECTED_SERVER:
        raise HydrationError(
            f"{EXPECTED_SERVER_ENV} conflicts with the locked HFM endpoint"
        )
    explicit_identity = _identity_from_env(effective_env)
    if explicit_identity is not None:
        return explicit_identity
    return _read_common_identity(common_ini)


def _config_lines(template: Path) -> list[str]:
    try:
        mode = template.lstat().st_mode
    except FileNotFoundError as exc:
        raise HydrationError("tracked Shadow config template is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise HydrationError("tracked Shadow config template must be a regular file")
    try:
        text = template.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise HydrationError("tracked Shadow config template is not valid UTF-8") from exc
    for line in text.splitlines():
        stripped = line.strip()
        if "=" in stripped and stripped.split("=", 1)[0].strip().casefold() == "password":
            raise HydrationError("tracked Shadow config template must not contain Password")
    return text.splitlines()


def _patch_unique_section_key(
    lines: list[str], section: str, key: str, value: str
) -> list[str]:
    target_section = section.casefold()
    target_key = key.casefold()
    section_count = 0
    key_count = 0
    in_target = False
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_target = stripped[1:-1].strip().casefold() == target_section
            if in_target:
                section_count += 1
            output.append(line)
            continue
        if in_target and "=" in stripped:
            current_key = stripped.split("=", 1)[0].strip().casefold()
            if current_key == target_key:
                output.append(f"{key}={value}")
                key_count += 1
                continue
        output.append(line)
    if section_count != 1 or key_count != 1:
        raise HydrationError(
            f"tracked Shadow config must contain one [{section}] {key} key"
        )
    return output


def _validate_runtime_target(template: Path, common_ini: Path, target: Path) -> None:
    if target.name != RUNTIME_CONFIG_NAME:
        raise HydrationError("runtime Shadow config has an unexpected filename")
    target_parent = target.parent
    try:
        parent_mode = target_parent.lstat().st_mode
    except FileNotFoundError as exc:
        raise HydrationError("runtime Shadow config directory is missing") from exc
    if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
        raise HydrationError("runtime Shadow config directory must be a real directory")

    target_location = target_parent.resolve(strict=True) / target.name
    for protected_path, label in (
        (template.resolve(strict=True), "tracked template"),
        (common_ini.resolve(strict=False), "portable common.ini"),
    ):
        if target_location == protected_path:
            raise HydrationError(f"runtime Shadow config must not replace {label}")


def _atomic_private_write(target: Path, text: str) -> None:
    file_descriptor = -1
    temporary_name = ""
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", dir=target.parent
        )
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(
            file_descriptor, "w", encoding="utf-8", errors="strict", newline="\n"
        ) as stream:
            file_descriptor = -1
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
        temporary_name = ""
        os.chmod(target, 0o600, follow_symlinks=False)
        directory_descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def hydrate_shadow_config(
    *,
    template: Path,
    target: Path,
    common_ini: Path,
    symbol: str,
    max_bars: int,
    env: Mapping[str, str] | None = None,
) -> ShadowIdentity:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", symbol):
        raise HydrationError("Shadow symbol contains unsupported characters")
    if not 1 <= max_bars <= 10_000_000:
        raise HydrationError("Shadow MaxBars is outside the supported range")

    identity = resolve_shadow_identity(common_ini, env)
    lines = _config_lines(template)
    for section, key, value in (
        ("Common", "Login", identity.login),
        ("Common", "Server", identity.server),
        ("Charts", "MaxBars", str(max_bars)),
        ("Experts", "AllowLiveTrading", "0"),
        ("StartUp", "Symbol", symbol),
    ):
        lines = _patch_unique_section_key(lines, section, key, value)

    _validate_runtime_target(template, common_ini, target)
    _atomic_private_write(target, "\n".join(lines) + "\n")
    return identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hydrate a private, read-only MT5 Shadow runtime config"
    )
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--common-ini", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--max-bars", required=True, type=int)
    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    output = stdout if stdout is not None else sys.stdout
    args = build_parser().parse_args(argv)
    try:
        identity = hydrate_shadow_config(
            template=args.template,
            target=args.target,
            common_ini=args.common_ini,
            symbol=args.symbol,
            max_bars=args.max_bars,
        )
    except HydrationError as exc:
        raise SystemExit(f"MT5 Shadow config hydration failed closed: {exc}") from exc
    print(
        f"MT5 Shadow runtime identity hydrated from {identity.source}; "
        "credentials were not logged.",
        file=output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
