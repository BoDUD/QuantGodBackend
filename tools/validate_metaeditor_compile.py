#!/usr/bin/env python3
"""Fail-closed validation for one MetaEditor compile attempt.

The launcher may accept a non-zero Wine exit code only when this validator can
prove that both the EX5 and compile log were created after the per-run marker,
and the log contains exactly one final zero-error, zero-warning result.
"""

from __future__ import annotations

import argparse
import codecs
import ntpath
import re
import sys
from pathlib import Path


MAX_COMPILE_LOG_BYTES = 8 * 1024 * 1024
ZERO_RESULT_RE = re.compile(r"^Result:\s*0 errors,\s*0 warnings(?:\s*,.*)?$")
COMPILE_SOURCE_RE = re.compile(
    r"^(?P<source>.+?)\s+:\s+information:\s+compiling\s+(?P<compiled>.+?)$",
    re.IGNORECASE,
)


class CompileAcceptanceError(ValueError):
    """Raised when compile evidence is missing, stale, or ambiguous."""


def _regular_file(path: Path, label: str, *, require_nonempty: bool = True) -> None:
    if path.is_symlink():
        raise CompileAcceptanceError(f"{label} must not be a symlink")
    if not path.is_file():
        raise CompileAcceptanceError(f"{label} is missing")
    if require_nonempty and path.stat().st_size <= 0:
        raise CompileAcceptanceError(f"{label} is empty")


def _decode_utf16_without_bom(raw: bytes) -> str:
    if len(raw) % 2 != 0:
        raise CompileAcceptanceError("compile log has odd-length UTF-16 data")
    code_units = max(1, len(raw) // 2)
    even_null_ratio = raw[0::2].count(0) / code_units
    odd_null_ratio = raw[1::2].count(0) / code_units
    if odd_null_ratio >= 0.25 and odd_null_ratio >= even_null_ratio + 0.10:
        encoding = "utf-16-le"
    elif even_null_ratio >= 0.25 and even_null_ratio >= odd_null_ratio + 0.10:
        encoding = "utf-16-be"
    else:
        raise CompileAcceptanceError("compile log encoding is ambiguous")
    try:
        return raw.decode(encoding, errors="strict")
    except UnicodeDecodeError as exc:
        raise CompileAcceptanceError("compile log is invalid UTF-16") from exc


def decode_compile_log(raw: bytes) -> str:
    if not raw:
        raise CompileAcceptanceError("compile log is empty")
    try:
        if raw.startswith(codecs.BOM_UTF8):
            text = raw.decode("utf-8-sig", errors="strict")
        elif raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
            # A declared UTF-16 encoding must decode as UTF-16. Never fall back
            # to UTF-8 after a malformed BOM, which could expose a stale ASCII
            # success line hidden behind corrupt bytes.
            text = raw.decode("utf-16", errors="strict")
        elif b"\x00" in raw:
            text = _decode_utf16_without_bom(raw)
        else:
            text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CompileAcceptanceError("compile log encoding is invalid") from exc

    if "\x00" in text:
        raise CompileAcceptanceError("compile log contains undecoded NUL bytes")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise CompileAcceptanceError("compile log contains unsupported control bytes")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_windows_source_path(value: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
        normalized = normalized[1:-1].strip()
    normalized = ntpath.normpath(normalized.replace("/", "\\"))
    if re.fullmatch(r"[A-Za-z]:\\.+", normalized) is None:
        raise CompileAcceptanceError("expected compile source must be an absolute Windows path")
    return normalized.casefold()


def validate_compile_log_text(text: str, *, expected_windows_source: str) -> None:
    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    compiling_lines = [line for line in nonempty_lines if re.search(r"\bcompiling\b", line, re.IGNORECASE)]
    if len(compiling_lines) != 1:
        raise CompileAcceptanceError("compile log must contain exactly one compiling source record")
    compile_match = COMPILE_SOURCE_RE.fullmatch(compiling_lines[0])
    if compile_match is None:
        raise CompileAcceptanceError("compile source record has an unexpected format")
    expected_source = normalize_windows_source_path(expected_windows_source)
    logged_source = normalize_windows_source_path(compile_match.group("source"))
    logged_compiled = normalize_windows_source_path(compile_match.group("compiled"))
    if logged_source != expected_source or logged_compiled != expected_source:
        raise CompileAcceptanceError("compile log source does not match the expected per-run source")

    result_lines = [line for line in nonempty_lines if re.match(r"^Result\s*:", line)]
    if len(result_lines) != 1:
        raise CompileAcceptanceError("compile log must contain exactly one Result summary")
    result_line = result_lines[0]
    if ZERO_RESULT_RE.fullmatch(result_line) is None:
        raise CompileAcceptanceError("compile result is not exactly 0 errors and 0 warnings")
    if nonempty_lines[-1] != result_line:
        raise CompileAcceptanceError("compile Result summary must be the final non-empty log line")


def validate_compile_acceptance(
    *,
    source_path: Path,
    ex5_path: Path,
    log_path: Path,
    marker_path: Path,
    expected_windows_source: str,
) -> None:
    _regular_file(marker_path, "compile marker", require_nonempty=False)
    _regular_file(source_path, "MQL5 source")
    _regular_file(ex5_path, "EX5 artifact")
    _regular_file(log_path, "compile log")

    marker_mtime_ns = marker_path.stat().st_mtime_ns
    source_mtime_ns = source_path.stat().st_mtime_ns
    ex5_mtime_ns = ex5_path.stat().st_mtime_ns
    if ex5_mtime_ns <= marker_mtime_ns:
        raise CompileAcceptanceError("EX5 artifact is not newer than this compile marker")
    log_stat = log_path.stat()
    if log_stat.st_mtime_ns <= marker_mtime_ns:
        raise CompileAcceptanceError("compile log is not newer than this compile marker")
    if source_mtime_ns > ex5_mtime_ns or source_mtime_ns > log_stat.st_mtime_ns:
        raise CompileAcceptanceError("MQL5 source is newer than its EX5 or compile log")
    if log_stat.st_size > MAX_COMPILE_LOG_BYTES:
        raise CompileAcceptanceError("compile log exceeds the validation size limit")

    validate_compile_log_text(
        decode_compile_log(log_path.read_bytes()),
        expected_windows_source=expected_windows_source,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--ex5", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--marker", required=True, type=Path)
    parser.add_argument("--expected-windows-source", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_compile_acceptance(
            source_path=args.source,
            ex5_path=args.ex5,
            log_path=args.log,
            marker_path=args.marker,
            expected_windows_source=args.expected_windows_source,
        )
    except (CompileAcceptanceError, OSError) as exc:
        print(f"MetaEditor compile evidence rejected: {exc}", file=sys.stderr)
        return 1
    print("MetaEditor compile evidence accepted: fresh EX5 and exact 0 errors, 0 warnings log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
