from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESS_GROUP_RUNNER = REPO_ROOT / "tools" / "run_process_group.py"


def _wait_for(predicate, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    state = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")


def test_agent_telegram_dispatch_requires_dedicated_explicit_opt_in() -> None:
    launcher = (REPO_ROOT / "Start_QuantGod_mac.sh").read_text(encoding="utf-8")
    supervisor = (REPO_ROOT / "tools" / "ensure_mac_agent_v25_loop.sh").read_text(encoding="utf-8")
    loop = (REPO_ROOT / "tools" / "run_mac_agent_v25_loop.sh").read_text(encoding="utf-8")

    safe_default = 'QG_AGENT_V25_SEND_TELEGRAM:-0}'
    inherited_default = 'QG_AGENT_V25_SEND_TELEGRAM:-${QG_TELEGRAM_PUSH_ALLOWED:-0}'
    assert safe_default in launcher
    assert safe_default in supervisor
    assert safe_default in loop
    assert inherited_default not in launcher
    assert inherited_default not in supervisor
    assert inherited_default not in loop
    assert loop.count('"$SEND_TELEGRAM" == "1"') >= 2
    assert 'QG_TELEGRAM_COMMANDS_ALLOWED:-0' in launcher
    assert 'QG_TELEGRAM_COMMANDS_ALLOWED:-0' in supervisor


def test_agent_screen_uses_process_group_runner() -> None:
    supervisor = (REPO_ROOT / "tools" / "ensure_mac_agent_v25_loop.sh").read_text(encoding="utf-8")
    loop = (REPO_ROOT / "tools" / "run_mac_agent_v25_loop.sh").read_text(encoding="utf-8")

    assert "tools/run_process_group.py" in supervisor
    assert '--pid-file "$PROCESS_GROUP_FILE"' in supervisor or "--pid-file '$PROCESS_GROUP_FILE'" in supervisor
    assert '--stop-pid-file "$PROCESS_GROUP_FILE"' in supervisor
    assert "trap cleanup_loop_children EXIT" in loop
    assert "trap exit_on_term TERM HUP" in loop


def test_runner_termination_stops_child_and_grandchild(tmp_path: Path) -> None:
    pid_file = tmp_path / "process-group.json"
    descendants_file = tmp_path / "descendants.json"
    grandchild_code = "import time; time.sleep(60)"
    child_code = "\n".join(
        [
            "import json, os, subprocess, sys, time",
            f"grandchild = subprocess.Popen([sys.executable, '-c', {grandchild_code!r}])",
            "with open(sys.argv[1], 'w', encoding='utf-8') as handle:",
            "    json.dump({'childPid': os.getpid(), 'grandchildPid': grandchild.pid}, handle)",
            "while True:",
            "    time.sleep(1)",
        ]
    )
    runner = subprocess.Popen(
        [
            sys.executable,
            str(PROCESS_GROUP_RUNNER),
            "--pid-file",
            str(pid_file),
            "--grace-seconds",
            "0.5",
            "--",
            sys.executable,
            "-c",
            child_code,
            str(descendants_file),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert _wait_for(lambda: pid_file.exists() and descendants_file.exists())
        descendants = json.loads(descendants_file.read_text(encoding="utf-8"))
        child_pid = int(descendants["childPid"])
        grandchild_pid = int(descendants["grandchildPid"])
        assert _process_is_running(child_pid)
        assert _process_is_running(grandchild_pid)

        runner.send_signal(signal.SIGTERM)
        runner.wait(timeout=5)

        assert runner.returncode == 128 + signal.SIGTERM
        assert _wait_for(lambda: not _process_is_running(child_pid))
        assert _wait_for(lambda: not _process_is_running(grandchild_pid))
        assert not pid_file.exists()
    finally:
        if runner.poll() is None:
            runner.kill()
            runner.wait(timeout=2)
