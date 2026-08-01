from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_ACCOUNT_ID = "90000001"
SYNTHETIC_SERVER = "SyntheticBroker-Demo"
ACCOUNT_LITERAL = re.compile(
    r"(?i)(?:account(?:login|number)?|login)\s*[\"']?\s*[:=]\s*[\"']?(\d{6,})"
)
PRODUCTION_SERVER_LITERAL = re.compile(r"\bHFMarketsGlobal-Live\d+\b")
ACTIVE_ACCOUNT_SURFACES = (
    "Dashboard/dashboard_server.js",
    "MQL5/Config/QuantGod_MT5_HFM_LivePilot.ini",
    "MQL5/Config/QuantGod_MT5_HFM_Shadow.ini",
    "tools/run_mt5_backtest_lab.ps1",
    "tools/run_param_lab.py",
    "tools/run_param_lab_auto_tester_window.py",
    "tools/sync_isolated_mt5_account_context.py",
)


def _tracked_files() -> list[Path]:
    names = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
    ).decode("utf-8").split("\0")
    return [REPO_ROOT / name for name in names if name and (REPO_ROOT / name).is_file()]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_tracked_repository_has_no_production_broker_server_literal() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _tracked_files()
        if PRODUCTION_SERVER_LITERAL.search(_text(path))
    ]
    assert offenders == []


def test_active_account_surfaces_use_only_synthetic_fixture_identity() -> None:
    for relative_path in ACTIVE_ACCOUNT_SURFACES:
        path = REPO_ROOT / relative_path
        text = _text(path)
        account_ids = ACCOUNT_LITERAL.findall(text)
        assert set(account_ids).issubset({SYNTHETIC_ACCOUNT_ID}), relative_path
        assert "HFMarketsGlobal-Live" not in text, relative_path

    combined_config = "\n".join(
        _text(REPO_ROOT / relative_path)
        for relative_path in ACTIVE_ACCOUNT_SURFACES
        if relative_path.startswith("MQL5/Config/")
    )
    assert SYNTHETIC_ACCOUNT_ID in combined_config
    assert SYNTHETIC_SERVER in combined_config
