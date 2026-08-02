#!/usr/bin/env python3
"""Build the private Live16 observer config without copying credentials.

The source is an existing local, password-free account selector.  The output is
always a distinct Shadow/ReadOnly startup config plus a minimal login reference.
No account identity is accepted on the command line or written to stdout.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import TextIO

EXPECTED_SERVER = "HFMarketsGlobal-" + "Live16"
SOURCE_NAME = "QuantGod_MT5_HFM_LiveSecondary_mac.ini"
TARGET_NAME = "QuantGod_MT5_HFM_SecondaryShadow_mac.ini"
LOGIN_REFERENCE_NAME = "QuantGod_MT5_LoginOnly_mac.ini"
LOGIN_PATTERN = re.compile(r"[0-9]+")


class SecondaryHydrationError(ValueError):
    """Raised when local identity evidence is missing or unsafe."""


def _require_private_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise SecondaryHydrationError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SecondaryHydrationError(f"{label} must be a regular non-symlink file")
    if metadata.st_uid != os.getuid():
        raise SecondaryHydrationError(f"{label} must belong to the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SecondaryHydrationError(f"{label} must not be accessible by group or other users")


def _require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise SecondaryHydrationError(f"{label} is missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SecondaryHydrationError(f"{label} must be a regular non-symlink file")


def _read_unique_ini_identity(path: Path) -> tuple[str, str]:
    _require_private_regular_file(path, "secondary account selector")
    if path.name != SOURCE_NAME:
        raise SecondaryHydrationError("secondary account selector has an unexpected filename")
    try:
        text = path.read_text(encoding="utf-8-sig", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise SecondaryHydrationError("secondary account selector is not valid UTF-8") from exc

    values: dict[str, str] = {}
    common_sections = 0
    in_common = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_common = line[1:-1].strip().casefold() == "common"
            if in_common:
                common_sections += 1
            continue
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip().casefold()
        if normalized_key == "password":
            raise SecondaryHydrationError("secondary account selector must not contain Password")
        if not in_common or normalized_key not in {"login", "server"}:
            continue
        if normalized_key in values:
            raise SecondaryHydrationError(f"secondary account selector has duplicate {normalized_key}")
        values[normalized_key] = value.strip()

    if common_sections != 1 or set(values) != {"login", "server"}:
        raise SecondaryHydrationError("secondary account selector lacks one [Common] Login/Server pair")
    login = values["login"]
    server = values["server"]
    if LOGIN_PATTERN.fullmatch(login) is None or len(login) > 20:
        raise SecondaryHydrationError("secondary login identity is invalid")
    if server != EXPECTED_SERVER:
        raise SecondaryHydrationError("secondary server is outside the locked Live16 contract")
    return login, server


def _verify_private_profile(path: Path, login: str, server: str) -> None:
    _require_private_regular_file(path, "private MT5 account profile")
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SecondaryHydrationError("private MT5 account profile is invalid") from exc
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, list):
        raise SecondaryHydrationError("private MT5 account profile list is missing")
    candidates = [
        item
        for item in profiles
        if isinstance(item, dict) and str(item.get("server") or "").strip() == EXPECTED_SERVER
    ]
    if len(candidates) != 1:
        raise SecondaryHydrationError("private MT5 account profile must contain one Live16 identity")
    profile = candidates[0]
    profile_login = str(profile.get("accountLogin") or "").strip()
    if LOGIN_PATTERN.fullmatch(profile_login) is None or len(profile_login) > 20:
        raise SecondaryHydrationError("private MT5 account profile login is invalid")
    if not hmac.compare_digest(profile_login, login) or not hmac.compare_digest(
        str(profile.get("server") or "").strip(), server
    ):
        raise SecondaryHydrationError("secondary selector does not match the registered private profile")
    if profile.get("passwordPersisted") is not False or profile.get("credentialStorageAllowed") is not False:
        raise SecondaryHydrationError("secondary profile violates the no-credential-storage contract")


def _read_template(path: Path) -> list[str]:
    _require_regular_file(path, "tracked Shadow template")
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise SecondaryHydrationError("tracked Shadow template is not valid UTF-8") from exc
    for line in text.splitlines():
        if "=" in line and line.split("=", 1)[0].strip().casefold() == "password":
            raise SecondaryHydrationError("tracked Shadow template must not contain Password")
    return text.splitlines()


def _patch_unique(lines: list[str], section: str, key: str, value: str) -> list[str]:
    section_name = section.casefold()
    key_name = key.casefold()
    section_count = 0
    key_count = 0
    in_section = False
    output: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1].strip().casefold() == section_name
            section_count += int(in_section)
            output.append(raw_line)
            continue
        if in_section and "=" in line and line.split("=", 1)[0].strip().casefold() == key_name:
            output.append(f"{key}={value}")
            key_count += 1
        else:
            output.append(raw_line)
    if section_count != 1 or key_count != 1:
        raise SecondaryHydrationError(f"tracked Shadow template must contain one [{section}] {key}")
    return output


def _validate_targets(prefix: Path, source: Path, target: Path, login_reference: Path) -> None:
    if not prefix.is_absolute() or prefix.is_symlink() or not prefix.is_dir():
        raise SecondaryHydrationError("secondary Wine prefix must be a real absolute directory")
    qg_dir = prefix / "drive_c/qg"
    if qg_dir.is_symlink() or not qg_dir.is_dir():
        raise SecondaryHydrationError("secondary private qg directory is invalid")
    expected_paths = {
        source: qg_dir / SOURCE_NAME,
        target: qg_dir / TARGET_NAME,
        login_reference: qg_dir / LOGIN_REFERENCE_NAME,
    }
    for actual, expected in expected_paths.items():
        if actual.absolute() != expected.absolute():
            raise SecondaryHydrationError("secondary runtime path is outside the exact reviewed prefix contract")
    if target.exists() and target.is_symlink():
        raise SecondaryHydrationError("secondary Shadow target must not be a symlink")
    if login_reference.exists() and login_reference.is_symlink():
        raise SecondaryHydrationError("secondary login reference must not be a symlink")


def _atomic_private_write(path: Path, text: str) -> None:
    descriptor = -1
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", errors="strict", newline="\n") as stream:
            descriptor = -1
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
        os.chmod(path, 0o600, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def hydrate_secondary_shadow_config(
    *,
    prefix: Path,
    template: Path,
    source: Path,
    profile: Path,
    target: Path,
    login_reference: Path,
    symbol: str,
    max_bars: int,
) -> None:
    if re.fullmatch(r"[A-Za-z0-9._-]+", symbol) is None:
        raise SecondaryHydrationError("secondary Shadow symbol contains unsupported characters")
    if not 1 <= max_bars <= 10_000_000:
        raise SecondaryHydrationError("secondary Shadow MaxBars is outside the supported range")
    _validate_targets(prefix, source, target, login_reference)
    login, server = _read_unique_ini_identity(source)
    _verify_private_profile(profile, login, server)
    lines = _read_template(template)
    for section, key, value in (
        ("Common", "Login", login),
        ("Common", "Server", server),
        ("Charts", "MaxBars", str(max_bars)),
        ("Experts", "AllowLiveTrading", "0"),
        ("StartUp", "Symbol", symbol),
    ):
        lines = _patch_unique(lines, section, key, value)
    _atomic_private_write(login_reference, f"[Common]\nLogin={login}\nServer={server}\n")
    _atomic_private_write(target, "\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hydrate the private Live16 Shadow observer config")
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--login-reference", required=True, type=Path)
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--max-bars", type=int, default=1_000_000)
    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        hydrate_secondary_shadow_config(
            prefix=args.prefix,
            template=args.template,
            source=args.source,
            profile=args.profile,
            target=args.target,
            login_reference=args.login_reference,
            symbol=args.symbol,
            max_bars=args.max_bars,
        )
    except SecondaryHydrationError as exc:
        raise SystemExit(f"MT5 secondary Shadow hydration failed closed: {exc}") from exc
    print(
        "MT5 secondary Shadow identity matched the private Live16 profile; credentials were not logged.",
        file=stdout if stdout is not None else sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
