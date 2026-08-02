from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/hydrate_mt5_secondary_shadow_config.py"
SPEC = importlib.util.spec_from_file_location("secondary_hydrator", TOOL)
assert SPEC and SPEC.loader
hydrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hydrator)
SYNTHETIC_SECONDARY_LOGIN = "90000002"


def _fixture(tmp_path: Path) -> dict[str, Path]:
    prefix = tmp_path / "net.metaquotes.wine.metatrader5-live16"
    qg = prefix / "drive_c/qg"
    qg.mkdir(parents=True)
    source = qg / hydrator.SOURCE_NAME
    source.write_text(
        f"[Common]\nLogin={SYNTHETIC_SECONDARY_LOGIN}\nServer={hydrator.EXPECTED_SERVER}\n\n"
        "[Experts]\nAllowLiveTrading=0\n",
        encoding="utf-8",
    )
    source.chmod(0o600)
    profile = tmp_path / "QuantGod_MT5AccountProfiles.json"
    profile.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "accountLogin": SYNTHETIC_SECONDARY_LOGIN,
                        "server": hydrator.EXPECTED_SERVER,
                        "passwordPersisted": False,
                        "credentialStorageAllowed": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    profile.chmod(0o600)
    template = tmp_path / "QuantGod_MT5_HFM_Shadow.ini"
    template.write_text(
        "[Common]\nLogin=90000001\nServer=SyntheticBroker-Demo\n\n"
        "[Charts]\nMaxBars=1000\n\n"
        "[Experts]\nAllowLiveTrading=0\nAllowDllImport=0\n\n"
        "[StartUp]\nSymbol=USDJPYc\nExpertParameters=QuantGod_MT5_HFM_Shadow.set\n",
        encoding="utf-8",
    )
    return {
        "prefix": prefix,
        "source": source,
        "profile": profile,
        "template": template,
        "target": qg / hydrator.TARGET_NAME,
        "login_reference": qg / hydrator.LOGIN_REFERENCE_NAME,
    }


def _hydrate(paths: dict[str, Path]) -> None:
    hydrator.hydrate_secondary_shadow_config(
        **paths,
        symbol="USDJPY",
        max_bars=300_000,
    )


def test_hydrates_distinct_live16_shadow_and_minimal_login_reference(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _hydrate(paths)

    runtime = paths["target"].read_text(encoding="utf-8")
    reference = paths["login_reference"].read_text(encoding="utf-8")
    assert f"Login={SYNTHETIC_SECONDARY_LOGIN}" in runtime
    assert f"Server={hydrator.EXPECTED_SERVER}" in runtime
    assert "AllowLiveTrading=0" in runtime
    assert "Symbol=USDJPY" in runtime
    assert "Password=" not in runtime
    assert reference == (
        f"[Common]\nLogin={SYNTHETIC_SECONDARY_LOGIN}\nServer={hydrator.EXPECTED_SERVER}\n"
    )
    assert stat.S_IMODE(paths["target"].stat().st_mode) == 0o600
    assert stat.S_IMODE(paths["login_reference"].stat().st_mode) == 0o600


@pytest.mark.parametrize("unsafe", ["password", "profile-mismatch", "wide-mode"])
def test_unsafe_identity_evidence_fails_before_runtime_write(tmp_path: Path, unsafe: str) -> None:
    paths = _fixture(tmp_path)
    if unsafe == "password":
        paths["source"].write_text(
            paths["source"].read_text(encoding="utf-8") + "Password=must-not-exist\n",
            encoding="utf-8",
        )
        paths["source"].chmod(0o600)
    elif unsafe == "profile-mismatch":
        payload = json.loads(paths["profile"].read_text(encoding="utf-8"))
        payload["profiles"][0]["accountLogin"] = "90000003"
        paths["profile"].write_text(json.dumps(payload), encoding="utf-8")
        paths["profile"].chmod(0o600)
    else:
        paths["source"].chmod(0o644)

    with pytest.raises(hydrator.SecondaryHydrationError):
        _hydrate(paths)

    assert not paths["target"].exists()
    assert not paths["login_reference"].exists()


def test_runtime_paths_are_locked_to_the_secondary_prefix(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["target"] = tmp_path / hydrator.TARGET_NAME

    with pytest.raises(hydrator.SecondaryHydrationError, match="exact reviewed prefix"):
        _hydrate(paths)
