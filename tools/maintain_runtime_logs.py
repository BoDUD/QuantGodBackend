#!/usr/bin/env python3
"""Rotate repo-local runtime logs and compact cold JSONL ledgers."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import stat
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "runtime"
DEFAULT_ARCHIVE_DIR_NAME = "log_archive"
DEFAULT_MAX_ACTIVE_MB = 128
DEFAULT_ARCHIVE_MAX_MB = 512
DEFAULT_RETENTION_DAYS = 2
DEFAULT_GZIP_LEVEL = 3
DEFAULT_JSONL_ARCHIVE_DIR_NAME = "jsonl_archive"
DEFAULT_MAX_JSONL_MB = 2
DEFAULT_JSONL_ARCHIVE_MAX_MB = 512
DEFAULT_JSONL_KEEP_LINES = 2000
DEFAULT_JSONL_MIN_AGE_SECONDS = 0
STATUS_FILE_NAME = "QuantGod_RuntimeLogMaintenanceStatus.json"
ARCHIVED_LOG_RE = re.compile(r"^.+\.\d{8}T\d{4}(?:\d{2})?[A-Z]{0,5}(?:\.\d+)?\.log(?:\.gz)?$")
ARCHIVED_JSONL_RE = re.compile(r"^.+\.\d{8}T\d{4}(?:\d{2})?[A-Z]{0,5}(?:\.\d+)?\.jsonl\.gz$")


class MaintenanceError(RuntimeError):
    """Fail-closed managed-path or file-identity error."""


class ManagedFileChangedError(MaintenanceError):
    """A managed file changed after it was admitted for maintenance."""


@dataclass(frozen=True)
class ManagedFile:
    path: Path
    root: Path
    device: int
    inode: int
    size_bytes: int
    mode: int
    link_count: int
    uid: int | None
    mtime_ns: int
    ctime_ns: int

    @property
    def mtime(self) -> float:
        return self.mtime_ns / 1_000_000_000


def _tokyo_now() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Tokyo"))
    return datetime.now().astimezone()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")  # noqa: UP017


def _timestamp_stamp(now: datetime | None = None) -> str:
    current = now or _tokyo_now()
    return current.strftime("%Y%m%dT%H%M%S%Z")


def _is_archived_log(path: Path) -> bool:
    return bool(ARCHIVED_LOG_RE.match(path.name))


def _is_archived_jsonl(path: Path) -> bool:
    return bool(ARCHIVED_JSONL_RE.match(path.name))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _current_uid() -> int | None:
    return os.getuid() if hasattr(os, "getuid") else None


def _absolute_lexical_path(raw: Path | str, *, label: str) -> Path:
    path = Path(raw).expanduser()
    if ".." in path.parts:
        raise MaintenanceError(f"{label} must not contain parent traversal: {path}")
    if not path.is_absolute():
        path = Path.cwd() / path
    return Path(os.path.abspath(path))


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _file_open_flags(*, writable: bool) -> int:
    flags = os.O_RDWR if writable else os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _validate_directory_info(info: os.stat_result, *, path: Path, require_owner: bool) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise MaintenanceError(f"managed directory is not a directory: {path}")
    expected_uid = _current_uid()
    if require_owner and expected_uid is not None and getattr(info, "st_uid", expected_uid) != expected_uid:
        raise MaintenanceError(f"managed directory is not owned by the current user: {path}")


def _open_absolute_directory(path: Path, *, create: bool = False) -> int:
    """Open every path component with O_NOFOLLOW and return the final directory fd."""

    if not path.is_absolute() or path == Path(path.anchor):
        raise MaintenanceError(f"managed directory must be an absolute non-root path: {path}")
    flags = _directory_open_flags()
    current_path = Path(path.anchor)
    try:
        current_fd = os.open(path.anchor, flags)
    except OSError as exc:
        raise MaintenanceError(f"could not open filesystem anchor for {path}") from exc
    try:
        for part in path.parts[1:]:
            current_path = current_path / part
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise MaintenanceError(f"managed directory does not exist: {current_path}") from None
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise MaintenanceError(f"could not safely create managed directory: {current_path}") from exc
            except OSError as exc:
                raise MaintenanceError(
                    f"managed directory contains a link or unsafe component: {current_path}"
                ) from exc
            os.close(current_fd)
            current_fd = next_fd
        descriptor_info = os.fstat(current_fd)
        _validate_directory_info(descriptor_info, path=path, require_owner=True)
        try:
            lexical_info = path.lstat()
        except OSError as exc:
            raise MaintenanceError(f"managed directory changed while opening: {path}") from exc
        if not stat.S_ISDIR(lexical_info.st_mode) or (
            lexical_info.st_dev,
            lexical_info.st_ino,
        ) != (descriptor_info.st_dev, descriptor_info.st_ino):
            raise MaintenanceError(f"managed directory changed while opening: {path}")
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _validated_directory(raw: Path | str, *, label: str, create: bool = False) -> Path:
    path = _absolute_lexical_path(raw, label=label)
    fd = _open_absolute_directory(path, create=create)
    os.close(fd)
    return path


def _relative_file_parts(path: Path, root: Path, *, label: str) -> tuple[str, ...]:
    if not path.is_absolute() or not root.is_absolute():
        raise MaintenanceError(f"{label} path and root must be absolute")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise MaintenanceError(f"{label} escapes its managed root: {path}") from exc
    if not relative.parts or relative == Path(".") or any(part in {"", ".", ".."} for part in relative.parts):
        raise MaintenanceError(f"{label} is not a managed file path: {path}")
    return relative.parts


def _open_managed_parent(path: Path, root: Path, *, label: str) -> int:
    parts = _relative_file_parts(path, root, label=label)
    current_fd = _open_absolute_directory(root)
    current_path = root
    flags = _directory_open_flags()
    try:
        for part in parts[:-1]:
            current_path = current_path / part
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except OSError as exc:
                raise MaintenanceError(f"{label} contains a link or unsafe directory: {current_path}") from exc
            try:
                _validate_directory_info(os.fstat(next_fd), path=current_path, require_owner=True)
            except BaseException:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _validate_regular_file_info(info: os.stat_result, *, path: Path, label: str) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise MaintenanceError(f"{label} is not a regular file: {path}")
    if info.st_nlink != 1:
        raise MaintenanceError(f"{label} must have exactly one hard link: {path}")
    expected_uid = _current_uid()
    actual_uid = getattr(info, "st_uid", None)
    if expected_uid is not None and actual_uid != expected_uid:
        raise MaintenanceError(f"{label} is not owned by the current user: {path}")


def _managed_file_from_info(path: Path, root: Path, info: os.stat_result) -> ManagedFile:
    return ManagedFile(
        path=path,
        root=root,
        device=info.st_dev,
        inode=info.st_ino,
        size_bytes=info.st_size,
        mode=info.st_mode,
        link_count=info.st_nlink,
        uid=getattr(info, "st_uid", None),
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def _verify_file_identity(snapshot: ManagedFile, info: os.stat_result, *, stage: str) -> None:
    _validate_regular_file_info(info, path=snapshot.path, label=f"managed file at {stage}")
    actual = (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mode,
        info.st_nlink,
        getattr(info, "st_uid", None),
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
    expected = (
        snapshot.device,
        snapshot.inode,
        snapshot.size_bytes,
        snapshot.mode,
        snapshot.link_count,
        snapshot.uid,
        snapshot.mtime_ns,
        snapshot.ctime_ns,
    )
    if actual != expected:
        raise ManagedFileChangedError(f"managed file identity changed at {stage}: {snapshot.path}")


def _verify_open_file(snapshot: ManagedFile, fd: int, parent_fd: int, *, stage: str) -> None:
    _verify_file_identity(snapshot, os.fstat(fd), stage=f"{stage} descriptor")
    try:
        entry_info = os.stat(snapshot.path.name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise ManagedFileChangedError(f"managed file entry changed at {stage}: {snapshot.path}") from exc
    _verify_file_identity(snapshot, entry_info, stage=f"{stage} directory entry")


@contextmanager
def _open_verified_file(snapshot: ManagedFile, *, writable: bool) -> Iterator[tuple[int, int]]:
    parent_fd = _open_managed_parent(snapshot.path, snapshot.root, label="managed file")
    try:
        try:
            fd = os.open(
                snapshot.path.name,
                _file_open_flags(writable=writable),
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise ManagedFileChangedError(f"managed file could not be safely opened: {snapshot.path}") from exc
        try:
            _verify_open_file(snapshot, fd, parent_fd, stage="open")
            yield fd, parent_fd
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _snapshot_managed_file(path: Path, *, root: Path, label: str) -> ManagedFile:
    path = _absolute_lexical_path(path, label=label)
    parent_fd = _open_managed_parent(path, root, label=label)
    try:
        try:
            fd = os.open(path.name, _file_open_flags(writable=False), dir_fd=parent_fd)
        except OSError as exc:
            raise MaintenanceError(f"{label} could not be safely opened: {path}") from exc
        try:
            info = os.fstat(fd)
            _validate_regular_file_info(info, path=path, label=label)
            try:
                entry_info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as exc:
                raise MaintenanceError(f"{label} changed while opening: {path}") from exc
            _validate_regular_file_info(entry_info, path=path, label=label)
            if (entry_info.st_dev, entry_info.st_ino) != (info.st_dev, info.st_ino):
                raise MaintenanceError(f"{label} changed while opening: {path}")
            return _managed_file_from_info(path, root, info)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _entry_exists(path: Path, *, root: Path, label: str) -> bool:
    parent_fd = _open_managed_parent(path, root, label=label)
    try:
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise MaintenanceError(f"could not inspect {label}: {path}") from exc
        return True
    finally:
        os.close(parent_fd)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("managed file write made no progress")
        view = view[written:]


def _copy_fd(source_fd: int, target: BinaryIO, *, gzip_output: bool, target_name: str) -> None:
    os.lseek(source_fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(source_fd), "rb") as source:
        if gzip_output:
            with gzip.GzipFile(
                filename=target_name,
                mode="wb",
                fileobj=target,
                compresslevel=DEFAULT_GZIP_LEVEL,
            ) as compressed:
                shutil.copyfileobj(source, compressed, length=1024 * 1024)
        else:
            shutil.copyfileobj(source, target, length=1024 * 1024)


def _create_archive_from_fd(
    source_fd: int,
    target: Path,
    *,
    target_root: Path,
    gzip_output: bool,
) -> ManagedFile:
    target = _absolute_lexical_path(target, label="archive target")
    parent_fd = _open_managed_parent(target, target_root, label="archive target")
    target_fd: int | None = None
    created_identity: tuple[int, int] | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            target_fd = os.open(target.name, flags, 0o600, dir_fd=parent_fd)
        except OSError as exc:
            raise MaintenanceError(f"archive target could not be safely created: {target}") from exc
        initial_info = os.fstat(target_fd)
        _validate_regular_file_info(initial_info, path=target, label="archive target")
        created_identity = (initial_info.st_dev, initial_info.st_ino)
        with os.fdopen(os.dup(target_fd), "wb") as target_handle:
            _copy_fd(
                source_fd,
                target_handle,
                gzip_output=gzip_output,
                target_name=target.name,
            )
            target_handle.flush()
        os.fsync(target_fd)
        final_info = os.fstat(target_fd)
        _validate_regular_file_info(final_info, path=target, label="archive target")
        entry_info = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        _validate_regular_file_info(entry_info, path=target, label="archive target")
        if (final_info.st_dev, final_info.st_ino) != created_identity or (
            entry_info.st_dev,
            entry_info.st_ino,
        ) != created_identity:
            raise MaintenanceError(f"archive target changed while writing: {target}")
        return _managed_file_from_info(target, target_root, final_info)
    except BaseException:
        if created_identity is not None:
            try:
                entry_info = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
                if (entry_info.st_dev, entry_info.st_ino) == created_identity:
                    os.unlink(target.name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(parent_fd)


def _safe_unlink(snapshot: ManagedFile) -> None:
    with _open_verified_file(snapshot, writable=False) as (fd, parent_fd):
        _verify_open_file(snapshot, fd, parent_fd, stage="unlink")
        os.unlink(snapshot.path.name, dir_fd=parent_fd)


def _cleanup_created_archive(snapshot: ManagedFile) -> None:
    try:
        _safe_unlink(snapshot)
    except MaintenanceError as exc:
        raise MaintenanceError(f"could not safely clean up incomplete archive: {snapshot.path}") from exc


def _rotate_active_log(source: ManagedFile, target: Path, *, target_root: Path) -> ManagedFile:
    with _open_verified_file(source, writable=True) as (source_fd, source_parent_fd):
        archive = _create_archive_from_fd(
            source_fd,
            target,
            target_root=target_root,
            gzip_output=True,
        )
        try:
            _verify_open_file(source, source_fd, source_parent_fd, stage="pre-truncate")
            os.ftruncate(source_fd, 0)
            os.fsync(source_fd)
        except BaseException:
            _cleanup_created_archive(archive)
            raise
        return archive


def _read_jsonl_tail_from_fd(fd: int, *, max_bytes: int, keep_lines: int) -> bytes:
    if max_bytes <= 0 or keep_lines <= 0:
        return b""
    lines: deque[bytes] = deque()
    total_bytes = 0
    os.lseek(fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(fd), "rb") as handle:
        for line in handle:
            lines.append(line)
            total_bytes += len(line)
            while lines and (len(lines) > keep_lines or (total_bytes > max_bytes and len(lines) > 1)):
                total_bytes -= len(lines.popleft())
    return b"".join(lines)


def _compact_jsonl_file(
    source: ManagedFile,
    target: Path,
    *,
    target_root: Path,
    max_bytes: int,
    keep_lines: int,
) -> tuple[ManagedFile, bytes]:
    with _open_verified_file(source, writable=True) as (source_fd, source_parent_fd):
        archive = _create_archive_from_fd(
            source_fd,
            target,
            target_root=target_root,
            gzip_output=True,
        )
        try:
            tail = _read_jsonl_tail_from_fd(source_fd, max_bytes=max_bytes, keep_lines=keep_lines)
            _verify_open_file(source, source_fd, source_parent_fd, stage="pre-jsonl-rewrite")
            os.lseek(source_fd, 0, os.SEEK_SET)
            os.ftruncate(source_fd, 0)
            _write_all(source_fd, tail)
            os.fsync(source_fd)
        except BaseException:
            _cleanup_created_archive(archive)
            raise
        return archive, tail


def _archive_and_unlink_source(
    source: ManagedFile,
    target: Path,
    *,
    target_root: Path,
    gzip_output: bool,
) -> ManagedFile:
    with _open_verified_file(source, writable=False) as (source_fd, source_parent_fd):
        archive = _create_archive_from_fd(
            source_fd,
            target,
            target_root=target_root,
            gzip_output=gzip_output,
        )
        try:
            _verify_open_file(source, source_fd, source_parent_fd, stage="pre-source-unlink")
            os.unlink(source.path.name, dir_fd=source_parent_fd)
        except BaseException:
            _cleanup_created_archive(archive)
            raise
        return archive


def _unique_archive_path(archive_dir: Path, stem: str, stamp: str) -> Path:
    candidate = archive_dir / f"{stem}.{stamp}.log.gz"
    if not _entry_exists(candidate, root=archive_dir, label="archive collision candidate"):
        return candidate
    _snapshot_managed_file(candidate, root=archive_dir, label="archive collision candidate")
    for index in range(1, 1000):
        fallback = archive_dir / f"{stem}.{stamp}.{index}.log.gz"
        if not _entry_exists(fallback, root=archive_dir, label="archive collision candidate"):
            return fallback
        _snapshot_managed_file(fallback, root=archive_dir, label="archive collision candidate")
    raise MaintenanceError(f"could not find unique archive path for {stem}")


def _unique_jsonl_archive_path(archive_dir: Path, stem: str, stamp: str) -> Path:
    candidate = archive_dir / f"{stem}.{stamp}.jsonl.gz"
    if not _entry_exists(candidate, root=archive_dir, label="JSONL archive collision candidate"):
        return candidate
    _snapshot_managed_file(candidate, root=archive_dir, label="JSONL archive collision candidate")
    for index in range(1, 1000):
        fallback = archive_dir / f"{stem}.{stamp}.{index}.jsonl.gz"
        if not _entry_exists(fallback, root=archive_dir, label="JSONL archive collision candidate"):
            return fallback
        _snapshot_managed_file(fallback, root=archive_dir, label="JSONL archive collision candidate")
    raise MaintenanceError(f"could not find unique jsonl archive path for {stem}")


def _expired(candidate: ManagedFile, *, now: datetime, retention_days: int) -> bool:
    cutoff = now - timedelta(days=max(0, retention_days))
    return datetime.fromtimestamp(candidate.mtime, tz=now.tzinfo) < cutoff


def _older_than(candidate: ManagedFile, *, now: datetime, min_age_seconds: int) -> bool:
    if min_age_seconds <= 0:
        return True
    age_seconds = max(0.0, now.timestamp() - candidate.mtime)
    return age_seconds >= float(min_age_seconds)


def _safe_stem_for_runtime_path(path: Path, runtime_root: Path) -> str:
    try:
        relative = path.relative_to(runtime_root)
    except ValueError:
        relative = Path(path.name)
    without_suffix = relative.with_suffix("")
    raw = "__".join(without_suffix.parts)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._") or path.stem


def _direct_managed_files(
    root: Path,
    *,
    matcher: Callable[[Path], bool],
    label: str,
) -> list[ManagedFile]:
    candidates: list[ManagedFile] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if matcher(path):
            candidates.append(_snapshot_managed_file(path, root=root, label=label))
    return candidates


def _recursive_jsonl_files(runtime_root: Path, *, archive_dir: Path) -> list[ManagedFile]:
    candidates: list[ManagedFile] = []

    def fail_walk(error: OSError) -> None:
        raise MaintenanceError(f"could not safely scan JSONL runtime tree: {error.filename}") from error

    for directory_raw, directory_names, file_names in os.walk(
        runtime_root,
        topdown=True,
        onerror=fail_walk,
        followlinks=False,
    ):
        directory = Path(directory_raw)
        if _is_relative_to(directory, archive_dir):
            directory_names[:] = []
            continue
        safe_directory_names: list[str] = []
        for name in sorted(directory_names):
            child = directory / name
            if _is_relative_to(child, archive_dir):
                continue
            try:
                child_info = child.lstat()
            except OSError as exc:
                raise MaintenanceError(f"could not inspect JSONL directory: {child}") from exc
            if stat.S_ISLNK(child_info.st_mode):
                continue
            if stat.S_ISDIR(child_info.st_mode):
                safe_directory_names.append(name)
        directory_names[:] = safe_directory_names
        for name in sorted(file_names):
            if not name.endswith(".jsonl"):
                continue
            path = directory / name
            candidates.append(
                _snapshot_managed_file(
                    path,
                    root=runtime_root,
                    label="active JSONL ledger",
                )
            )
    return sorted(candidates, key=lambda item: str(item.path))


def _prune_archive_size(
    archive_dir: Path,
    *,
    archived_matcher: Callable[[Path], bool],
    max_bytes: int,
    reason: str,
) -> list[dict[str, Any]]:
    if max_bytes <= 0:
        return []
    candidates = sorted(
        _direct_managed_files(
            archive_dir,
            matcher=archived_matcher,
            label="archive size-cap candidate",
        ),
        key=lambda item: (item.mtime_ns, item.path.name),
    )
    total = sum(candidate.size_bytes for candidate in candidates)
    deleted: list[dict[str, Any]] = []
    for candidate in candidates:
        if total <= max_bytes:
            break
        _safe_unlink(candidate)
        total -= candidate.size_bytes
        deleted.append(
            {
                "path": str(candidate.path),
                "sizeBytes": candidate.size_bytes,
                "reason": reason,
            }
        )
    return deleted


def _write_status(path: Path, payload: dict[str, Any], *, runtime_root: Path) -> None:
    path = _absolute_lexical_path(path, label="maintenance status")
    existing = (
        _snapshot_managed_file(path, root=runtime_root, label="maintenance status")
        if _entry_exists(path, root=runtime_root, label="maintenance status")
        else None
    )
    parent_fd = _open_managed_parent(path, runtime_root, label="maintenance status")
    temporary_name = f".{path.name}.tmp-{os.getpid()}-{os.urandom(8).hex()}"
    temporary_fd: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        temporary_fd = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        temporary_info = os.fstat(temporary_fd)
        _validate_regular_file_info(
            temporary_info,
            path=path.parent / temporary_name,
            label="maintenance status temporary",
        )
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _write_all(temporary_fd, encoded)
        os.fsync(temporary_fd)
        if existing is not None:
            entry_info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            _verify_file_identity(existing, entry_info, stage="status replacement")
        else:
            try:
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise MaintenanceError(f"maintenance status appeared before replacement: {path}")
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
        temporary_name = ""
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if temporary_name:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_fd)
        os.close(parent_fd)


def maintain_jsonl_ledgers(
    runtime_root: Path,
    *,
    archive_dir: Path | None = None,
    max_active_bytes: int = DEFAULT_MAX_JSONL_MB * 1024 * 1024,
    archive_max_bytes: int = DEFAULT_JSONL_ARCHIVE_MAX_MB * 1024 * 1024,
    keep_lines: int = DEFAULT_JSONL_KEEP_LINES,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    min_age_seconds: int = DEFAULT_JSONL_MIN_AGE_SECONDS,
) -> dict[str, Any]:
    runtime_root = _validated_directory(runtime_root, label="runtime root")
    archive_dir = _validated_directory(
        archive_dir or (runtime_root / DEFAULT_JSONL_ARCHIVE_DIR_NAME),
        label="JSONL archive root",
        create=True,
    )
    if archive_dir == runtime_root or _is_relative_to(runtime_root, archive_dir):
        raise MaintenanceError("JSONL archive root must not contain the runtime root")

    now = _tokyo_now()
    stamp = _timestamp_stamp(now)
    compacted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []

    jsonl_files = _recursive_jsonl_files(runtime_root, archive_dir=archive_dir)
    for candidate in jsonl_files:
        if candidate.size_bytes <= max_active_bytes:
            continue
        if not _older_than(candidate, now=now, min_age_seconds=min_age_seconds):
            skipped.append(
                {
                    "path": str(candidate.path),
                    "sizeBytes": candidate.size_bytes,
                    "reason": "recently_modified",
                }
            )
            continue
        stem = _safe_stem_for_runtime_path(candidate.path, runtime_root)
        archive_path = _unique_jsonl_archive_path(archive_dir, stem, stamp)
        try:
            archive, tail = _compact_jsonl_file(
                candidate,
                archive_path,
                target_root=archive_dir,
                max_bytes=max_active_bytes,
                keep_lines=keep_lines,
            )
        except ManagedFileChangedError:
            skipped.append(
                {
                    "path": str(candidate.path),
                    "sizeBytes": candidate.size_bytes,
                    "reason": "identity_changed",
                }
            )
            continue
        compacted.append(
            {
                "source": str(candidate.path),
                "archive": str(archive.path),
                "sizeBytes": candidate.size_bytes,
                "retainedBytes": len(tail),
                "keepLines": int(keep_lines),
            }
        )

    archive_candidates = _direct_managed_files(
        archive_dir,
        matcher=_is_archived_jsonl,
        label="JSONL archive",
    )
    for candidate in archive_candidates:
        if not _expired(candidate, now=now, retention_days=retention_days):
            continue
        _safe_unlink(candidate)
        deleted.append(
            {
                "path": str(candidate.path),
                "sizeBytes": candidate.size_bytes,
                "reason": "expired_jsonl_archive",
            }
        )

    deleted.extend(
        _prune_archive_size(
            archive_dir,
            archived_matcher=_is_archived_jsonl,
            max_bytes=max(0, int(archive_max_bytes)),
            reason="jsonl_archive_size_cap",
        )
    )

    archive_files = _direct_managed_files(
        archive_dir,
        matcher=_is_archived_jsonl,
        label="JSONL archive",
    )
    return {
        "archiveDir": str(archive_dir),
        "maxActiveBytes": int(max_active_bytes),
        "archiveMaxBytes": int(archive_max_bytes),
        "keepLines": int(keep_lines),
        "minAgeSeconds": int(min_age_seconds),
        "retentionDays": int(retention_days),
        "activeJsonlCount": len(jsonl_files),
        "archiveCount": len(archive_files),
        "compacted": compacted,
        "skipped": skipped,
        "deleted": deleted,
    }


def maintain_logs(
    runtime_root: Path,
    *,
    archive_dir: Path | None = None,
    max_active_bytes: int = DEFAULT_MAX_ACTIVE_MB * 1024 * 1024,
    archive_max_bytes: int = DEFAULT_ARCHIVE_MAX_MB * 1024 * 1024,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    jsonl_archive_dir: Path | None = None,
    jsonl_max_active_bytes: int = DEFAULT_MAX_JSONL_MB * 1024 * 1024,
    jsonl_archive_max_bytes: int = DEFAULT_JSONL_ARCHIVE_MAX_MB * 1024 * 1024,
    jsonl_keep_lines: int = DEFAULT_JSONL_KEEP_LINES,
    jsonl_min_age_seconds: int = DEFAULT_JSONL_MIN_AGE_SECONDS,
    maintain_jsonl: bool = True,
) -> dict[str, Any]:
    runtime_root = _validated_directory(runtime_root, label="runtime root")
    archive_dir = _validated_directory(
        archive_dir or (runtime_root / DEFAULT_ARCHIVE_DIR_NAME),
        label="log archive root",
        create=True,
    )
    if archive_dir == runtime_root or _is_relative_to(runtime_root, archive_dir):
        raise MaintenanceError("log archive root must not contain the runtime root")

    now = _tokyo_now()
    stamp = _timestamp_stamp(now)
    rotated: list[dict[str, Any]] = []
    compressed_legacy: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    active_logs = _direct_managed_files(
        runtime_root,
        matcher=lambda path: path.name.endswith(".log") and not _is_archived_log(path),
        label="active log",
    )
    for candidate in active_logs:
        if candidate.size_bytes <= max_active_bytes:
            continue
        archive_path = _unique_archive_path(archive_dir, candidate.path.stem, stamp)
        try:
            archive = _rotate_active_log(candidate, archive_path, target_root=archive_dir)
        except ManagedFileChangedError:
            skipped.append(
                {
                    "path": str(candidate.path),
                    "sizeBytes": candidate.size_bytes,
                    "reason": "identity_changed",
                }
            )
            continue
        rotated.append(
            {
                "source": str(candidate.path),
                "archive": str(archive.path),
                "sizeBytes": candidate.size_bytes,
            }
        )

    legacy_archives = _direct_managed_files(
        runtime_root,
        matcher=_is_archived_log,
        label="legacy log archive",
    )
    for candidate in legacy_archives:
        if _expired(candidate, now=now, retention_days=retention_days):
            _safe_unlink(candidate)
            deleted.append(
                {
                    "path": str(candidate.path),
                    "sizeBytes": candidate.size_bytes,
                    "reason": "expired_legacy_archive",
                }
            )
            continue
        gzip_output = candidate.path.suffix != ".gz"
        target = archive_dir / (f"{candidate.path.name}.gz" if gzip_output else candidate.path.name)
        if _entry_exists(target, root=archive_dir, label="legacy archive target"):
            existing_target = _snapshot_managed_file(
                target,
                root=archive_dir,
                label="legacy archive target",
            )
            _safe_unlink(existing_target)
        archive = _archive_and_unlink_source(
            candidate,
            target,
            target_root=archive_dir,
            gzip_output=gzip_output,
        )
        compressed_legacy.append(
            {
                "source": str(candidate.path),
                "archive": str(archive.path),
                "sizeBytes": candidate.size_bytes,
                "action": "compressed_legacy_archive" if gzip_output else "moved_gzip_archive",
            }
        )

    archive_candidates = _direct_managed_files(
        archive_dir,
        matcher=_is_archived_log,
        label="log archive",
    )
    for candidate in archive_candidates:
        if not _expired(candidate, now=now, retention_days=retention_days):
            continue
        _safe_unlink(candidate)
        deleted.append(
            {
                "path": str(candidate.path),
                "sizeBytes": candidate.size_bytes,
                "reason": "expired_archive",
            }
        )

    deleted.extend(
        _prune_archive_size(
            archive_dir,
            archived_matcher=_is_archived_log,
            max_bytes=max(0, int(archive_max_bytes)),
            reason="archive_size_cap",
        )
    )

    archive_files = _direct_managed_files(
        archive_dir,
        matcher=_is_archived_log,
        label="log archive",
    )
    jsonl_status = (
        maintain_jsonl_ledgers(
            runtime_root,
            archive_dir=jsonl_archive_dir,
            max_active_bytes=max(1, int(jsonl_max_active_bytes)),
            archive_max_bytes=max(0, int(jsonl_archive_max_bytes)),
            keep_lines=max(0, int(jsonl_keep_lines)),
            retention_days=max(0, int(retention_days)),
            min_age_seconds=max(0, int(jsonl_min_age_seconds)),
        )
        if maintain_jsonl
        else {"enabled": False}
    )
    status = {
        "schema": "quantgod.runtime_log_maintenance_status.v1",
        "generatedAtIso": _utc_now_iso(),
        "runtimeRoot": str(runtime_root),
        "archiveDir": str(archive_dir),
        "maxActiveBytes": int(max_active_bytes),
        "archiveMaxBytes": int(archive_max_bytes),
        "retentionDays": int(retention_days),
        "activeLogCount": len(active_logs),
        "archiveCount": len(archive_files),
        "rotated": rotated,
        "compressedLegacy": compressed_legacy,
        "deleted": deleted,
        "skipped": skipped,
        "jsonl": jsonl_status,
    }
    _write_status(runtime_root / STATUS_FILE_NAME, status, runtime_root=runtime_root)
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rotate/compress repo runtime logs and compact cold JSONL ledgers.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--archive-dir", default="")
    parser.add_argument(
        "--max-active-mb",
        type=int,
        default=int(os.environ.get("QG_RUNTIME_LOG_MAX_MB", DEFAULT_MAX_ACTIVE_MB)),
    )
    parser.add_argument(
        "--archive-max-mb",
        type=int,
        default=int(os.environ.get("QG_RUNTIME_LOG_ARCHIVE_MAX_MB", DEFAULT_ARCHIVE_MAX_MB)),
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=int(os.environ.get("QG_RUNTIME_LOG_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)),
    )
    parser.add_argument("--jsonl-archive-dir", default="")
    parser.add_argument(
        "--max-jsonl-mb",
        type=int,
        default=int(os.environ.get("QG_RUNTIME_JSONL_MAX_MB", DEFAULT_MAX_JSONL_MB)),
    )
    parser.add_argument(
        "--jsonl-archive-max-mb",
        type=int,
        default=int(os.environ.get("QG_RUNTIME_JSONL_ARCHIVE_MAX_MB", DEFAULT_JSONL_ARCHIVE_MAX_MB)),
    )
    parser.add_argument(
        "--jsonl-keep-lines",
        type=int,
        default=int(os.environ.get("QG_RUNTIME_JSONL_KEEP_LINES", DEFAULT_JSONL_KEEP_LINES)),
    )
    parser.add_argument(
        "--jsonl-min-age-seconds",
        type=int,
        default=int(os.environ.get("QG_RUNTIME_JSONL_MIN_AGE_SECONDS", DEFAULT_JSONL_MIN_AGE_SECONDS)),
    )
    parser.add_argument("--no-jsonl-maintenance", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_root = Path(args.runtime_root)
    archive_dir = Path(args.archive_dir) if args.archive_dir else runtime_root / DEFAULT_ARCHIVE_DIR_NAME
    jsonl_archive_dir = (
        Path(args.jsonl_archive_dir) if args.jsonl_archive_dir else runtime_root / DEFAULT_JSONL_ARCHIVE_DIR_NAME
    )
    status = maintain_logs(
        runtime_root,
        archive_dir=archive_dir,
        max_active_bytes=max(1, int(args.max_active_mb)) * 1024 * 1024,
        archive_max_bytes=max(0, int(args.archive_max_mb)) * 1024 * 1024,
        retention_days=max(0, int(args.retention_days)),
        jsonl_archive_dir=jsonl_archive_dir,
        jsonl_max_active_bytes=max(1, int(args.max_jsonl_mb)) * 1024 * 1024,
        jsonl_archive_max_bytes=max(0, int(args.jsonl_archive_max_mb)) * 1024 * 1024,
        jsonl_keep_lines=max(0, int(args.jsonl_keep_lines)),
        jsonl_min_age_seconds=max(0, int(args.jsonl_min_age_seconds)),
        maintain_jsonl=not args.no_jsonl_maintenance,
    )
    jsonl_status = status.get("jsonl") if isinstance(status.get("jsonl"), dict) else {}
    print(
        json.dumps(
            {
                "runtimeRoot": status["runtimeRoot"],
                "archiveDir": status["archiveDir"],
                "rotatedCount": len(status["rotated"]),
                "compressedLegacyCount": len(status["compressedLegacy"]),
                "deletedCount": len(status["deleted"]),
                "archiveCount": status["archiveCount"],
                "jsonlCompactedCount": len(jsonl_status.get("compacted", [])),
                "jsonlDeletedCount": len(jsonl_status.get("deleted", [])),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
