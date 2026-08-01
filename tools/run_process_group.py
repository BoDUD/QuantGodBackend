#!/usr/bin/env python3
"""Run one command in an isolated process group and stop the full tree safely."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_exists(process_group: int) -> bool:
    if process_group <= 0:
        return False
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_until_stopped(check, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while check():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _signal_group(process_group: int, sig: signal.Signals) -> None:
    try:
        os.killpg(process_group, sig)
    except ProcessLookupError:
        pass


def _terminate_group(process_group: int, grace_seconds: float) -> None:
    if not _group_exists(process_group):
        return
    _signal_group(process_group, signal.SIGTERM)
    if _wait_until_stopped(lambda: _group_exists(process_group), grace_seconds):
        return
    _signal_group(process_group, signal.SIGKILL)
    _wait_until_stopped(lambda: _group_exists(process_group), min(1.0, grace_seconds))


def _record_still_owned(path: Path, runner_pid: int, child_pid: int) -> bool:
    payload = _read_json(path)
    return payload.get("runnerPid") == runner_pid and payload.get("childPid") == child_pid


def _unlink_owned_record(path: Path, runner_pid: int, child_pid: int) -> None:
    if not _record_still_owned(path, runner_pid, child_pid):
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def run_command(command: Sequence[str], pid_file: Path, grace_seconds: float) -> int:
    if not command:
        raise ValueError("a command is required after --")

    child = subprocess.Popen(list(command), start_new_session=True)
    process_group = child.pid
    runner_pid = os.getpid()
    payload = {
        "schema": "quantgod.process_group.v1",
        "generatedAtIso": _utc_now_iso(),
        "runnerPid": runner_pid,
        "childPid": child.pid,
        "childProcessGroup": process_group,
        "command": list(command),
    }
    _atomic_write_json(pid_file, payload)

    received_signal = 0
    termination_started_at = 0.0

    def handle_signal(signum: int, _frame: Any) -> None:
        nonlocal received_signal, termination_started_at
        received_signal = received_signal or signum
        if not termination_started_at:
            termination_started_at = time.monotonic()
            _signal_group(process_group, signal.SIGTERM)

    handled_signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    previous_handlers = {sig: signal.getsignal(sig) for sig in handled_signals}
    for sig in handled_signals:
        signal.signal(sig, handle_signal)

    try:
        while child.poll() is None:
            try:
                child.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                if termination_started_at and time.monotonic() - termination_started_at >= grace_seconds:
                    _signal_group(process_group, signal.SIGKILL)
        return_code = child.returncode
    finally:
        if child.poll() is None:
            _terminate_group(process_group, grace_seconds)
            try:
                child.wait(timeout=max(1.0, grace_seconds))
            except subprocess.TimeoutExpired:
                pass
        for sig, previous in previous_handlers.items():
            signal.signal(sig, previous)
        _unlink_owned_record(pid_file, runner_pid, child.pid)

    if received_signal:
        return 128 + received_signal
    return return_code


def stop_recorded_group(pid_file: Path, grace_seconds: float) -> int:
    if not pid_file.exists():
        return 0
    payload = _read_json(pid_file)
    runner_pid = payload.get("runnerPid")
    child_pid = payload.get("childPid")
    process_group = payload.get("childProcessGroup")
    if not all(isinstance(value, int) and value > 0 for value in (runner_pid, child_pid, process_group)):
        print(f"Invalid process-group record: {pid_file}", file=sys.stderr)
        return 2

    if _process_exists(child_pid):
        try:
            current_group = os.getpgid(child_pid)
        except ProcessLookupError:
            current_group = -1
        if current_group != process_group:
            print(
                f"Refusing stale process-group record: child pid {child_pid} is now in group {current_group}",
                file=sys.stderr,
            )
            return 2
        _terminate_group(process_group, grace_seconds)

    if _process_exists(runner_pid):
        try:
            os.kill(runner_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if not _wait_until_stopped(lambda: _process_exists(runner_pid), grace_seconds):
            try:
                os.kill(runner_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    current = _read_json(pid_file)
    if current.get("runnerPid") == runner_pid and current.get("childPid") == child_pid:
        try:
            pid_file.unlink()
        except FileNotFoundError:
            pass
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pid-file", type=Path, help="record for a newly launched process group")
    mode.add_argument("--stop-pid-file", type=Path, help="stop a previously recorded process group")
    parser.add_argument("--grace-seconds", type=float, default=5.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.grace_seconds < 0:
        parser.error("--grace-seconds must be non-negative")
    if args.pid_file and not args.command:
        parser.error("a command is required after --")
    if args.stop_pid_file and args.command:
        parser.error("a command cannot be used with --stop-pid-file")
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.stop_pid_file:
        return stop_recorded_group(args.stop_pid_file, args.grace_seconds)
    return run_command(args.command, args.pid_file, args.grace_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
