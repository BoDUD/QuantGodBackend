from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "hydrate_mt5_shadow_config.py"
LAUNCHER = ROOT / "Start_QuantGod_mac.sh"
EXPECTED_SERVER = "HFMarketsGlobal-" + "Live12"
SYNTHETIC_SERVER = "SyntheticBroker-Demo"
RUNTIME_NAME = "QuantGod_MT5_HFM_Shadow_mac.ini"


def _template_text(*, password: bool = False) -> str:
    password_line = "Password=must-not-copy\n" if password else ""
    return (
        "[Common]\n"
        "Login=90000001\n"
        f"Server={SYNTHETIC_SERVER}\n"
        f"{password_line}"
        "KeepPrivate=1\n\n"
        "[Charts]\n"
        "MaxBars=1000000\n\n"
        "[Experts]\n"
        "AllowLiveTrading=0\n"
        "AllowDllImport=0\n\n"
        "[StartUp]\n"
        "Symbol=USDJPYc\n"
    )


def _write_common(path: Path, *, login: str, server: str) -> None:
    text = (
        "[Common]\r\n"
        "Environment=community-account\r\n"
        f"Login={login}\r\n"
        f"Server={server}\r\n"
        "Password=ignored-even-if-present\r\n"
        "[Charts]\r\n"
        "MaxBars=50000\r\n"
    )
    path.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    template = tmp_path / "QuantGod_MT5_HFM_Shadow.ini"
    template.write_text(_template_text(), encoding="utf-8")
    common = tmp_path / "common.ini"
    _write_common(common, login="123456789", server=EXPECTED_SERVER)
    runtime_dir = tmp_path / "private-runtime"
    runtime_dir.mkdir()
    return template, common, runtime_dir / RUNTIME_NAME


def _run(
    template: Path,
    common: Path,
    target: Path,
    *,
    env_updates: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in (
        "QG_MT5_SHADOW_LOGIN",
        "QG_MT5_SHADOW_SERVER",
        "QG_MT5_EXPECTED_SERVER",
    ):
        env.pop(name, None)
    env.update(env_updates or {})
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--template",
            str(template),
            "--target",
            str(target),
            "--common-ini",
            str(common),
            "--symbol",
            "USDJPYc",
            "--max-bars",
            "300000",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hydrates_from_selected_utf16le_common_ini_without_password(
    tmp_path: Path,
) -> None:
    template, common, target = _paths(tmp_path)

    result = _run(template, common, target)

    assert result.returncode == 0, result.stderr
    runtime = target.read_text(encoding="utf-8")
    assert "Login=123456789" in runtime
    assert f"Server={EXPECTED_SERVER}" in runtime
    assert "Password=" not in runtime
    assert "MaxBars=300000" in runtime
    assert "AllowLiveTrading=0" in runtime
    assert "Symbol=USDJPYc" in runtime
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert "123456789" not in result.stdout
    assert EXPECTED_SERVER not in result.stdout
    assert SYNTHETIC_SERVER in template.read_text(encoding="utf-8")


def test_paired_local_env_takes_precedence_without_reading_common(
    tmp_path: Path,
) -> None:
    template, common, target = _paths(tmp_path)
    common.unlink()

    result = _run(
        template,
        common,
        target,
        env_updates={
            "QG_MT5_SHADOW_LOGIN": "987654321",
            "QG_MT5_SHADOW_SERVER": EXPECTED_SERVER,
            "QG_MT5_EXPECTED_SERVER": EXPECTED_SERVER,
        },
    )

    assert result.returncode == 0, result.stderr
    runtime = target.read_text(encoding="utf-8")
    assert "Login=987654321" in runtime
    assert f"Server={EXPECTED_SERVER}" in runtime
    assert "987654321" not in result.stdout


@pytest.mark.parametrize(
    "env_updates",
    [
        {"QG_MT5_SHADOW_LOGIN": "123456789"},
        {"QG_MT5_SHADOW_SERVER": EXPECTED_SERVER},
        {
            "QG_MT5_SHADOW_LOGIN": "12345x789",
            "QG_MT5_SHADOW_SERVER": EXPECTED_SERVER,
        },
        {
            "QG_MT5_SHADOW_LOGIN": "123456789",
            "QG_MT5_SHADOW_SERVER": SYNTHETIC_SERVER,
        },
        {"QG_MT5_EXPECTED_SERVER": SYNTHETIC_SERVER},
    ],
)
def test_invalid_or_partial_env_fails_without_overwriting_runtime(
    tmp_path: Path, env_updates: dict[str, str]
) -> None:
    template, common, target = _paths(tmp_path)
    target.write_text("previous-private-runtime\n", encoding="utf-8")
    target.chmod(0o600)

    result = _run(template, common, target, env_updates=env_updates)

    assert result.returncode != 0
    assert "failed closed" in result.stderr
    assert target.read_text(encoding="utf-8") == "previous-private-runtime\n"


@pytest.mark.parametrize(
    ("login", "server"),
    [
        ("not-numeric", EXPECTED_SERVER),
        ("123456789", SYNTHETIC_SERVER),
    ],
)
def test_invalid_common_identity_fails_closed(
    tmp_path: Path, login: str, server: str
) -> None:
    template, common, target = _paths(tmp_path)
    _write_common(common, login=login, server=server)

    result = _run(template, common, target)

    assert result.returncode != 0
    assert not target.exists()


def test_non_utf16le_common_ini_is_rejected(tmp_path: Path) -> None:
    template, common, target = _paths(tmp_path)
    common.write_text(
        f"[Common]\nLogin=123456789\nServer={EXPECTED_SERVER}\n",
        encoding="utf-8",
    )

    result = _run(template, common, target)

    assert result.returncode != 0
    assert "UTF-16LE" in result.stderr
    assert not target.exists()


def test_password_in_template_is_rejected_without_writing_target(
    tmp_path: Path,
) -> None:
    template, common, target = _paths(tmp_path)
    template.write_text(_template_text(password=True), encoding="utf-8")

    result = _run(template, common, target)

    assert result.returncode != 0
    assert "Password" in result.stderr
    assert not target.exists()


def test_launcher_uses_private_hydrator_before_shadow_launch() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")
    hydrate_position = launcher.index("tools/hydrate_mt5_shadow_config.py")
    shadow_launch_position = launcher.index(
        "terminal64.exe /portable '/config:C:\\\\qg\\\\QuantGod_MT5_HFM_Shadow_mac.ini'"
    )

    assert hydrate_position < shadow_launch_position
    assert '--common-ini "$MT5_ROOT/config/common.ini"' in launcher
    assert 'cp MQL5/Config/QuantGod_MT5_HFM_Shadow.ini "$MT5_SHADOW_CONFIG"' not in launcher
    assert "QG_MT5_HFM_PASSWORD" not in launcher
    subprocess.run(["bash", "-n", str(LAUNCHER)], cwd=ROOT, check=True)
