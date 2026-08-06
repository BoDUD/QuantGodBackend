#!/usr/bin/env python3
"""Conservative local disk-pressure maintenance for QuantGod artifacts.

The tool is dry-run by default.  It never scans outside the explicit roots and
only deletes allow-listed historical analysis and stale status temp files when ``--execute`` is
present.  Trading evidence, databases, source/configuration files, EX5 files,
and current/latest JSON evidence are outside the deletion surface.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc  # noqa: UP017 -- the installed local maintenance runtime is Python 3.10.
SCHEMA = "quantgod.disk_space_maintenance.v1"
STATUS_FILE_NAME = "QuantGod_DiskSpaceMaintenanceStatus.json"
LOCK_FILE_NAME = "disk-space-maintenance.lock"
DEFAULT_WARN_FREE_PERCENT = 20.0
DEFAULT_CRITICAL_FREE_PERCENT = 10.0
DEFAULT_TARGET_FREE_PERCENT = 12.0
DEFAULT_HISTORY_RETENTION_DAYS = 14
DEFAULT_PRESSURE_RETENTION_DAYS = 3
DEFAULT_HISTORY_KEEP = 500
DEFAULT_PRESSURE_HISTORY_KEEP = 100
DEFAULT_STALE_TEMP_HOURS = 24
DEFAULT_MAX_DELETE_MB_PER_RUN = 2048
DEFAULT_MAX_DELETE_FILES_PER_RUN = 500

AI_HISTORY_RE = re.compile(r"^\d{8}T\d{6}Z_[A-Za-z0-9_.-]+\.json$")
STATUS_STALE_TEMP_RE = re.compile(
    r"^\.(?:history-sync|history-quality|automation-chain-report|agent-ops-health|"
    r"endpoint-health|sqlite-backup|sqlite-backup-verify)\.tmp-(?P<pid>[1-9]\d*)$"
)
PROTECTED_SUFFIXES = {
    ".sqlite",
    ".sqlite3",
    ".db",
    ".wal",
    ".shm",
    ".mq5",
    ".mqh",
    ".ex5",
    ".ini",
    ".set",
    ".conf",
    ".yaml",
    ".yml",
    ".toml",
}


class MaintenanceError(RuntimeError):
    """Fail-closed path, lock, or deletion error."""


@dataclass(frozen=True)
class Candidate:
    path: Path
    category: str
    root: Path
    size_bytes: int
    mtime: float
    device: int
    inode: int
    mode: int
    link_count: int
    mtime_ns: int
    ctime_ns: int

    def payload(self, *, now_ts: float, reason: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path": str(self.path),
            "category": self.category,
            "sizeBytes": int(self.size_bytes),
            "mtimeIso": datetime.fromtimestamp(self.mtime, UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "ageDays": round(max(0.0, now_ts - self.mtime) / 86400.0, 3),
            "isDirectory": False,
        }
        if reason:
            result["reason"] = reason
        return result


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _assert_no_symlink_chain(path: Path, *, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise MaintenanceError(f"{label} contains a symlink component: {current}")


def _validated_root(raw: Path | str, *, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise MaintenanceError(f"{label} must be absolute: {path}")
    if ".." in path.parts:
        raise MaintenanceError(f"{label} must not contain parent traversal: {path}")
    # Inspect the lexical input before resolve(); otherwise an ancestor symlink
    # disappears from the resolved path and would evade this boundary check.
    _assert_no_symlink_chain(path, label=label)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise MaintenanceError(f"{label} does not exist: {path}") from exc
    if resolved == Path(resolved.anchor):
        raise MaintenanceError(f"{label} must not be a filesystem root: {resolved}")
    if not resolved.is_dir():
        raise MaintenanceError(f"{label} must be a directory: {resolved}")
    return resolved


def _validated_managed_file(raw: Path | str, *, root: Path, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise MaintenanceError(f"{label} must be absolute: {path}")
    if ".." in path.parts:
        raise MaintenanceError(f"{label} must not contain parent traversal: {path}")
    _assert_no_symlink_chain(path, label=label)
    parent = path.parent.resolve(strict=True)
    resolved = parent / path.name
    if not _is_relative_to(resolved, root):
        raise MaintenanceError(f"{label} escapes its managed root: {resolved}")
    if resolved.exists():
        info = resolved.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise MaintenanceError(f"{label} must be a regular file: {resolved}")
        if info.st_nlink != 1:
            raise MaintenanceError(f"{label} must not be hard-linked: {resolved}")
    return resolved


def _derive_backend_root(runtime_root: Path, explicit: Path | str | None) -> Path:
    if explicit:
        return _validated_root(explicit, label="backend-root")
    if runtime_root.name != "runtime":
        raise MaintenanceError("--backend-root is required when backend runtime is not named runtime")
    return _validated_root(runtime_root.parent, label="derived backend-root")


def _derive_mt5_terminal_root(mt5_runtime_root: Path, explicit: Path | str | None) -> Path:
    if explicit:
        return _validated_root(explicit, label="mt5-terminal-root")
    if mt5_runtime_root.name != "Files" or mt5_runtime_root.parent.name != "MQL5":
        raise MaintenanceError("--mt5-terminal-root is required unless --mt5-runtime-root is MQL5/Files")
    return _validated_root(mt5_runtime_root.parent.parent, label="derived mt5-terminal-root")


def _derive_private_root(
    status_root: Path,
    lock_root: Path,
    explicit: Path | str | None,
) -> Path:
    if explicit:
        return _validated_root(explicit, label="private-root")
    common = Path(os.path.commonpath((str(status_root), str(lock_root))))
    return _validated_root(common, label="derived private-root")


def _validate_roots(
    *,
    backend_runtime_root: Path | str,
    mt5_runtime_root: Path | str,
    status_root: Path | str,
    lock_root: Path | str,
    backend_root: Path | str | None,
    mt5_terminal_root: Path | str | None,
    private_root: Path | str | None,
    status_file: Path | str | None,
    lock_file: Path | str | None,
) -> dict[str, Path]:
    runtime = _validated_root(backend_runtime_root, label="backend-runtime-root")
    mt5_files = _validated_root(mt5_runtime_root, label="mt5-runtime-root")
    statuses = _validated_root(status_root, label="status-root")
    locks = _validated_root(lock_root, label="lock-root")
    backend = _derive_backend_root(runtime, backend_root)
    terminal = _derive_mt5_terminal_root(mt5_files, mt5_terminal_root)
    private = _derive_private_root(statuses, locks, private_root)
    if not _is_relative_to(runtime, backend):
        raise MaintenanceError("backend runtime escapes backend root")
    if not _is_relative_to(mt5_files, terminal):
        raise MaintenanceError("MT5 runtime escapes MT5 terminal root")
    if not _is_relative_to(statuses, private) or not _is_relative_to(locks, private):
        raise MaintenanceError("status/lock roots must remain inside private root")
    top_level = (backend, terminal, private)
    if len(set(top_level)) != len(top_level):
        raise MaintenanceError("backend, MT5 terminal, and private roots must be distinct")
    allowed_roots = (runtime, mt5_files, statuses, locks)
    if len(set(allowed_roots)) != len(allowed_roots):
        raise MaintenanceError("managed roots must be distinct")
    for index, left in enumerate(allowed_roots):
        for right in allowed_roots[index + 1 :]:
            if _is_relative_to(left, right) or _is_relative_to(right, left):
                raise MaintenanceError(f"managed roots must not overlap: {left} and {right}")
    status_path = _validated_managed_file(
        status_file or (statuses / STATUS_FILE_NAME),
        root=statuses,
        label="status-file",
    )
    lock_path = _validated_managed_file(
        lock_file or (locks / LOCK_FILE_NAME),
        root=locks,
        label="lock-file",
    )
    if status_path == lock_path:
        raise MaintenanceError("status-file and lock-file must be distinct")
    return {
        "backendRoot": backend,
        "backendRuntimeRoot": runtime,
        "mt5TerminalRoot": terminal,
        "mt5RuntimeRoot": mt5_files,
        "privateRoot": private,
        "statusRoot": statuses,
        "lockRoot": locks,
        "statusFile": status_path,
        "lockFile": lock_path,
    }


def _protected_reason(path: Path) -> str | None:
    lower = path.name.lower()
    if lower.startswith("latest") and lower.endswith(".json"):
        return "protected_latest_evidence"
    if lower.endswith(("-wal", "-shm", ".wal", ".shm")):
        return "protected_database_config_source_or_binary"
    suffixes = {suffix.lower() for suffix in path.suffixes}
    if suffixes & PROTECTED_SUFFIXES:
        return "protected_database_config_source_or_binary"
    return None


def _candidate_file(
    path: Path,
    *,
    root: Path,
    category: str,
) -> Candidate:
    _assert_no_symlink_chain(path, label=f"{category} candidate")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise MaintenanceError(f"candidate disappeared: {path}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise MaintenanceError(f"unsafe file candidate: {path}")
    canonical = path.parent.resolve(strict=True) / path.name
    if not _is_relative_to(canonical, root):
        raise MaintenanceError(f"candidate escapes {category} root: {canonical}")
    if info.st_nlink != 1:
        raise MaintenanceError(f"hard-linked candidate rejected: {canonical}")
    return Candidate(
        canonical,
        category,
        root,
        info.st_size,
        info.st_mtime,
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _pid_is_active(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Fail closed for an unexpected platform/process-state response.
        return True
    return True


def _scan_candidates(roots: dict[str, Path]) -> tuple[list[Candidate], list[dict[str, Any]]]:
    candidates: list[Candidate] = []
    skipped: list[dict[str, Any]] = []

    def scan_files(
        directory: Path,
        matcher: re.Pattern[str],
        category: str,
        managed_root: Path,
    ) -> None:
        _assert_no_symlink_chain(directory, label=f"{category} directory")
        if not directory.exists():
            return
        if directory.is_symlink() or not directory.is_dir():
            raise MaintenanceError(f"unsafe candidate directory: {directory}")
        resolved_directory = directory.resolve(strict=True)
        if not _is_relative_to(resolved_directory, managed_root):
            raise MaintenanceError(f"candidate directory escapes {category} root: {directory}")
        for path in sorted(directory.iterdir()):
            protected = _protected_reason(path)
            if protected:
                skipped.append({"path": str(path), "category": category, "reason": protected})
                continue
            if path.is_symlink():
                skipped.append({"path": str(path), "category": category, "reason": "symlink_rejected"})
                continue
            if not path.is_file() or not matcher.fullmatch(path.name):
                skipped.append({"path": str(path), "category": category, "reason": "not_allowlisted"})
                continue
            try:
                candidates.append(_candidate_file(path, root=managed_root, category=category))
            except MaintenanceError as exc:
                skipped.append(
                    {"path": str(path), "category": category, "reason": "unsafe_candidate", "detail": str(exc)}
                )

    for root_key, prefix in (
        ("backendRuntimeRoot", "backend"),
        ("mt5RuntimeRoot", "mt5"),
    ):
        runtime = roots[root_key]
        scan_files(
            runtime / "ai_analysis" / "history",
            AI_HISTORY_RE,
            f"{prefix}_ai_analysis_history",
            runtime,
        )

    status_root = roots["statusRoot"]
    for path in sorted(status_root.iterdir()):
        match = STATUS_STALE_TEMP_RE.fullmatch(path.name)
        if not match:
            continue
        if path.is_symlink() or not path.is_file():
            skipped.append(
                {"path": str(path), "category": "status_stale_temp", "reason": "symlink_or_non_file_rejected"}
            )
            continue
        pid = int(match.group("pid"))
        if _pid_is_active(pid):
            skipped.append(
                {"path": str(path), "category": "status_stale_temp", "reason": "owner_pid_active", "pid": pid}
            )
            continue
        try:
            candidates.append(_candidate_file(path, root=status_root, category="status_stale_temp"))
        except MaintenanceError as exc:
            skipped.append(
                {
                    "path": str(path),
                    "category": "status_stale_temp",
                    "reason": "unsafe_candidate",
                    "detail": str(exc),
                }
            )
    return candidates, skipped


def _read_previous_pressure(status_file: Path) -> tuple[bool, str]:
    if not status_file.exists():
        return False, "MISSING"
    if status_file.is_symlink() or not status_file.is_file():
        raise MaintenanceError(f"unsafe previous status file: {status_file}")
    try:
        payload = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "INVALID"
    return payload.get("pressureActive") is True, "LOADED"


def _disk_payload(usage: Any) -> dict[str, Any]:
    total = int(getattr(usage, "total", usage[0]))
    used = int(getattr(usage, "used", usage[1]))
    free = int(getattr(usage, "free", usage[2]))
    free_percent = (free * 100.0 / total) if total > 0 else 0.0
    return {
        "totalBytes": total,
        "usedBytes": used,
        "freeBytes": free,
        "freePercent": round(free_percent, 4),
    }


def _pressure_level(
    free_percent: float,
    *,
    previous_active: bool,
    warning: float,
    critical: float,
    target: float,
) -> tuple[str, bool, str]:
    if free_percent < critical:
        return "CRITICAL", True, "critical_threshold"
    if previous_active and free_percent < target:
        return "CRITICAL", True, "hysteresis_below_recovery_target"
    if free_percent < warning:
        return "WARNING", False, "warning_threshold"
    return "NORMAL", False, "normal_free_space"


def _policy(
    level: str,
    *,
    history_retention_days: int,
    pressure_retention_days: int,
    history_keep: int,
    pressure_history_keep: int,
) -> dict[str, int]:
    if level == "CRITICAL":
        return {
            "retentionDays": max(0, pressure_retention_days),
            "historyKeep": max(0, pressure_history_keep),
        }
    return {
        "retentionDays": max(0, history_retention_days),
        "historyKeep": max(0, history_keep),
    }


def _keep_for(category: str, policy: dict[str, int]) -> int:
    if category == "status_stale_temp":
        return 0
    return policy["historyKeep"]


def _classify_candidates(
    candidates: Sequence[Candidate],
    *,
    now: datetime,
    policy: dict[str, int],
    stale_temp_hours: int,
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    eligible: list[Candidate] = []
    skipped: list[dict[str, Any]] = []
    now_ts = now.timestamp()
    by_category: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        by_category.setdefault(candidate.category, []).append(candidate)
    for category, rows in sorted(by_category.items()):
        newest_first = sorted(rows, key=lambda item: (item.mtime, str(item.path)), reverse=True)
        keep = _keep_for(category, policy)
        for index, candidate in enumerate(newest_first):
            if index < keep:
                skipped.append(candidate.payload(now_ts=now_ts, reason="keep_newest"))
                continue
            retention_seconds = policy["retentionDays"] * 86400
            if category == "status_stale_temp":
                retention_seconds = max(0, stale_temp_hours) * 3600
            if max(0.0, now_ts - candidate.mtime) < retention_seconds:
                skipped.append(candidate.payload(now_ts=now_ts, reason="retention_not_elapsed"))
                continue
            eligible.append(candidate)
    return sorted(eligible, key=lambda item: (item.mtime, str(item.path))), skipped


def _verify_candidate_identity(
    candidate: Candidate,
    info: os.stat_result,
    *,
    stage: str,
) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise MaintenanceError(f"candidate is no longer a regular file at {stage}: {candidate.path}")
    if info.st_nlink != 1 or info.st_nlink != candidate.link_count:
        raise MaintenanceError(f"candidate link count changed at {stage}: {candidate.path}")
    if (info.st_dev, info.st_ino) != (candidate.device, candidate.inode):
        raise MaintenanceError(f"candidate identity changed at {stage}: {candidate.path}")
    if info.st_size != candidate.size_bytes:
        raise MaintenanceError(f"candidate size changed at {stage}: {candidate.path}")
    if info.st_mode != candidate.mode:
        raise MaintenanceError(f"candidate mode changed at {stage}: {candidate.path}")
    if (info.st_mtime_ns, info.st_ctime_ns) != (candidate.mtime_ns, candidate.ctime_ns):
        raise MaintenanceError(f"candidate timestamps changed at {stage}: {candidate.path}")


def _revalidate_candidate(candidate: Candidate) -> None:
    path = candidate.path
    if not _is_relative_to(path, candidate.root):
        raise MaintenanceError(f"candidate changed or escaped before deletion: {path}")
    _assert_no_symlink_chain(path, label=f"{candidate.category} deletion")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise MaintenanceError(f"candidate disappeared before deletion: {path}") from exc
    _verify_candidate_identity(candidate, info, stage="path revalidation")
    protected = _protected_reason(path)
    if protected:
        raise MaintenanceError(f"candidate became protected ({protected}): {path}")


def _delete_candidate(candidate: Candidate) -> None:
    _revalidate_candidate(candidate)
    parent_flags = os.O_RDONLY
    file_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        parent_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        parent_flags |= os.O_CLOEXEC
        file_flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        file_flags |= os.O_NONBLOCK
    try:
        parent_fd = os.open(candidate.path.parent, parent_flags)
    except OSError as exc:
        raise MaintenanceError(f"could not securely open candidate parent: {candidate.path}") from exc
    try:
        try:
            candidate_fd = os.open(candidate.path.name, file_flags, dir_fd=parent_fd)
        except OSError as exc:
            raise MaintenanceError(f"could not securely open candidate: {candidate.path}") from exc
        try:
            _verify_candidate_identity(
                candidate,
                os.fstat(candidate_fd),
                stage="descriptor verification",
            )
            entry_info = os.stat(
                candidate.path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            _verify_candidate_identity(candidate, entry_info, stage="directory entry verification")
            os.unlink(candidate.path.name, dir_fd=parent_fd)
        finally:
            os.close(candidate_fd)
    finally:
        os.close(parent_fd)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.is_symlink():
        raise MaintenanceError(f"refusing symlinked status file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise MaintenanceError(f"could not safely open maintenance lock: {path}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise MaintenanceError(f"maintenance lock must be a single-link regular file: {path}")
        lexical_info = path.lstat()
        if (lexical_info.st_dev, lexical_info.st_ino) != (info.st_dev, info.st_ino):
            raise MaintenanceError(f"maintenance lock changed while opening: {path}")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MaintenanceError("disk maintenance is already running") from exc
        os.ftruncate(fd, 0)
        os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(fd)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def maintain_disk_space(
    *,
    backend_runtime_root: Path | str,
    mt5_runtime_root: Path | str,
    status_root: Path | str,
    lock_root: Path | str,
    backend_root: Path | str | None = None,
    mt5_terminal_root: Path | str | None = None,
    private_root: Path | str | None = None,
    status_file: Path | str | None = None,
    lock_file: Path | str | None = None,
    warning_free_percent: float = DEFAULT_WARN_FREE_PERCENT,
    critical_free_percent: float = DEFAULT_CRITICAL_FREE_PERCENT,
    target_free_percent: float = DEFAULT_TARGET_FREE_PERCENT,
    history_retention_days: int = DEFAULT_HISTORY_RETENTION_DAYS,
    pressure_retention_days: int = DEFAULT_PRESSURE_RETENTION_DAYS,
    history_keep: int = DEFAULT_HISTORY_KEEP,
    pressure_history_keep: int = DEFAULT_PRESSURE_HISTORY_KEEP,
    stale_temp_hours: int = DEFAULT_STALE_TEMP_HOURS,
    max_delete_bytes_per_run: int = DEFAULT_MAX_DELETE_MB_PER_RUN * 1024 * 1024,
    max_delete_files_per_run: int = DEFAULT_MAX_DELETE_FILES_PER_RUN,
    execute: bool = False,
    now: datetime | None = None,
    disk_usage_fn: Callable[[Path], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    if not (0 < critical_free_percent < target_free_percent <= warning_free_percent < 100):
        raise MaintenanceError("thresholds must satisfy 0 < critical < target <= warning < 100")
    roots = _validate_roots(
        backend_runtime_root=backend_runtime_root,
        mt5_runtime_root=mt5_runtime_root,
        status_root=status_root,
        lock_root=lock_root,
        backend_root=backend_root,
        mt5_terminal_root=mt5_terminal_root,
        private_root=private_root,
        status_file=status_file,
        lock_file=lock_file,
    )
    current = (now or _utc_now()).astimezone(UTC)
    status_path = roots["statusFile"]
    lock_path = roots["lockFile"]

    with _exclusive_lock(lock_path):
        previous_active, previous_status = _read_previous_pressure(status_path)
        before = _disk_payload(disk_usage_fn(roots["privateRoot"]))
        level, pressure_active, pressure_reason = _pressure_level(
            float(before["freePercent"]),
            previous_active=previous_active,
            warning=float(warning_free_percent),
            critical=float(critical_free_percent),
            target=float(target_free_percent),
        )
        policy = _policy(
            level,
            history_retention_days=max(0, int(history_retention_days)),
            pressure_retention_days=max(0, int(pressure_retention_days)),
            history_keep=max(0, int(history_keep)),
            pressure_history_keep=max(0, int(pressure_history_keep)),
        )
        candidates, scan_skipped = _scan_candidates(roots)
        eligible, retention_skipped = _classify_candidates(
            candidates,
            now=current,
            policy=policy,
            stale_temp_hours=max(0, int(stale_temp_hours)),
        )
        reclaimable = [candidate.payload(now_ts=current.timestamp()) for candidate in eligible]
        deleted: list[dict[str, Any]] = []
        skipped = [*scan_skipped, *retention_skipped]
        errors: list[dict[str, Any]] = []
        deleted_bytes = 0
        max_bytes = max(0, int(max_delete_bytes_per_run))
        max_files = max(0, int(max_delete_files_per_run))
        estimated_free = int(before["freeBytes"])
        total_bytes = max(1, int(before["totalBytes"]))

        if execute:
            for candidate in eligible:
                if pressure_active and estimated_free * 100.0 / total_bytes >= target_free_percent:
                    skipped.append(candidate.payload(now_ts=current.timestamp(), reason="recovery_target_reached"))
                    continue
                if len(deleted) >= max_files:
                    skipped.append(candidate.payload(now_ts=current.timestamp(), reason="file_budget_exhausted"))
                    continue
                if candidate.size_bytes > max_bytes - deleted_bytes:
                    skipped.append(candidate.payload(now_ts=current.timestamp(), reason="byte_budget_exhausted"))
                    continue
                try:
                    _delete_candidate(candidate)
                except (MaintenanceError, OSError) as exc:
                    error = candidate.payload(now_ts=current.timestamp(), reason="delete_failed")
                    error["detail"] = str(exc)
                    errors.append(error)
                    skipped.append(error)
                    continue
                deleted_bytes += candidate.size_bytes
                estimated_free += candidate.size_bytes
                deleted.append(candidate.payload(now_ts=current.timestamp(), reason="retention_policy"))

        after = _disk_payload(disk_usage_fn(roots["privateRoot"])) if execute else dict(before)
        after_level, after_active, after_reason = _pressure_level(
            float(after["freePercent"]),
            previous_active=pressure_active,
            warning=float(warning_free_percent),
            critical=float(critical_free_percent),
            target=float(target_free_percent),
        )
        effective_pressure_active = after_active if execute else pressure_active
        if errors:
            report_status = "PARTIAL"
        elif effective_pressure_active:
            report_status = "PRESSURE_REMAINS"
        else:
            report_status = "SUCCESS"
        pressure_remaining_bytes = (
            max(
                0,
                math.ceil(int(after["totalBytes"]) * float(target_free_percent) / 100.0 - int(after["freeBytes"])),
            )
            if effective_pressure_active
            else 0
        )
        report = {
            "schema": SCHEMA,
            "generatedAtIso": current.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "status": report_status,
            "mode": "EXECUTE" if execute else "DRY_RUN",
            "dryRun": not execute,
            "appliedPressureLevel": level,
            "pressureLevel": after_level if execute else level,
            "pressureActive": after_active if execute else pressure_active,
            "pressureReason": after_reason if execute else pressure_reason,
            "pressureRemainingBytes": pressure_remaining_bytes,
            "previousPressureActive": previous_active,
            "previousStatus": previous_status,
            "thresholds": {
                "warningFreePercent": float(warning_free_percent),
                "criticalFreePercent": float(critical_free_percent),
                "targetFreePercent": float(target_free_percent),
            },
            "policy": {
                **policy,
                "staleTempHours": max(0, int(stale_temp_hours)),
                "maxDeleteBytesPerRun": max_bytes,
                "maxDeleteFilesPerRun": max_files,
            },
            "disk": {"before": before, "after": after},
            "allowedRoots": [
                str(roots["backendRuntimeRoot"]),
                str(roots["mt5RuntimeRoot"]),
                str(roots["statusRoot"]),
                str(roots["lockRoot"]),
            ],
            "validatedRoots": {key: str(value) for key, value in roots.items()},
            "reclaimable": reclaimable,
            "deleted": deleted,
            "skipped": skipped,
            "errors": errors,
            "summary": {
                "candidateCount": len(candidates),
                "reclaimableCount": len(reclaimable),
                "reclaimableBytes": sum(item.size_bytes for item in eligible),
                "deletedCount": len(deleted),
                "deletedBytes": deleted_bytes,
                "errorCount": len(errors),
            },
            "safety": {
                "localOnly": True,
                "userDataDeletionAllowed": False,
                "managedArtifactDeletionAllowed": bool(execute),
                "mt5MutationAllowed": False,
                "orderSendAllowed": False,
                "closeAllowed": False,
                "cancelAllowed": False,
                "livePresetMutationAllowed": False,
                "mt5OrderFilesTouched": False,
                "databaseFilesTouched": False,
                "sourceConfigOrEx5Touched": False,
            },
        }
        _atomic_write_json(status_path, report)
        return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run-first QuantGod disk maintenance")
    parser.add_argument("--backend-runtime-root", "--backend-runtime", required=True)
    parser.add_argument("--mt5-runtime-root", "--mt5-files-root", required=True)
    parser.add_argument("--status-root", required=True)
    parser.add_argument("--lock-root", required=True)
    parser.add_argument("--backend-root", default="")
    parser.add_argument("--mt5-terminal-root", default="")
    parser.add_argument("--private-root", default="")
    parser.add_argument("--status-file", default="")
    parser.add_argument("--lock-file", default="")
    parser.add_argument("--warn-free-percent", type=float, default=DEFAULT_WARN_FREE_PERCENT)
    parser.add_argument("--critical-free-percent", type=float, default=DEFAULT_CRITICAL_FREE_PERCENT)
    parser.add_argument("--target-free-percent", type=float, default=DEFAULT_TARGET_FREE_PERCENT)
    parser.add_argument("--history-retention-days", type=int, default=DEFAULT_HISTORY_RETENTION_DAYS)
    parser.add_argument("--pressure-retention-days", type=int, default=DEFAULT_PRESSURE_RETENTION_DAYS)
    parser.add_argument("--history-keep", type=int, default=DEFAULT_HISTORY_KEEP)
    parser.add_argument("--pressure-history-keep", type=int, default=DEFAULT_PRESSURE_HISTORY_KEEP)
    parser.add_argument("--stale-temp-hours", type=int, default=DEFAULT_STALE_TEMP_HOURS)
    parser.add_argument("--max-delete-mb-per-run", type=int, default=DEFAULT_MAX_DELETE_MB_PER_RUN)
    parser.add_argument("--max-delete-files-per-run", type=int, default=DEFAULT_MAX_DELETE_FILES_PER_RUN)
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = maintain_disk_space(
            backend_runtime_root=args.backend_runtime_root,
            mt5_runtime_root=args.mt5_runtime_root,
            status_root=args.status_root,
            lock_root=args.lock_root,
            backend_root=args.backend_root or None,
            mt5_terminal_root=args.mt5_terminal_root or None,
            private_root=args.private_root or None,
            status_file=args.status_file or None,
            lock_file=args.lock_file or None,
            warning_free_percent=args.warn_free_percent,
            critical_free_percent=args.critical_free_percent,
            target_free_percent=args.target_free_percent,
            history_retention_days=args.history_retention_days,
            pressure_retention_days=args.pressure_retention_days,
            history_keep=args.history_keep,
            pressure_history_keep=args.pressure_history_keep,
            stale_temp_hours=args.stale_temp_hours,
            max_delete_bytes_per_run=max(0, args.max_delete_mb_per_run) * 1024 * 1024,
            max_delete_files_per_run=max(0, args.max_delete_files_per_run),
            execute=args.execute,
        )
    except (MaintenanceError, OSError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "ERROR", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "status": report["status"],
                "mode": report["mode"],
                "pressureLevel": report["pressureLevel"],
                "pressureActive": report["pressureActive"],
                **report["summary"],
            },
            ensure_ascii=False,
        )
    )
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
