from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"CI_GUARD_FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_text(path: Path) -> str:
    """Read repository text files with a few safe fallbacks.

    MQL5 preset files are usually UTF-8, but MT5 can occasionally write files
    with a BOM or a local encoding. The guard should fail on missing files, not
    on harmless encoding differences.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        fail(f"missing required file: {path.relative_to(ROOT)}")

    for encoding in ("utf-8", "utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def require_contains(path: Path, needle: str, label: str | None = None) -> None:
    text = read_text(path)
    if needle not in text:
        detail = label or needle
        fail(f"{path.relative_to(ROOT)} must contain {detail!r}")


def require_any_contains(path: Path, needles: tuple[str, ...], label: str) -> None:
    text = read_text(path)
    if not any(needle in text for needle in needles):
        fail(f"{path.relative_to(ROOT)} must contain one of {label}")


def parse_set_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def check_expected_set_values(path: Path, expected: dict[str, str]) -> None:
    values = parse_set_file(path)
    for key, expected_value in expected.items():
        actual = values.get(key)
        if actual != expected_value:
            fail(
                f"{path.relative_to(ROOT)} drift: {key} expected "
                f"{expected_value!r}, got {actual!r}"
            )


def tracked_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        fail(f"unable to list tracked files: {exc}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def check_secret_file_hygiene() -> None:
    """Reject tracked secrets and credential-like files.

    Allow documented `.env*.example` files because they describe required
    variables without storing real credentials. Real local env files remain
    ignored and must never be tracked.
    """
    allowed_env_files = {
        ".env.ai.local.example",
        ".env.auto.local.example",
        ".env.example",
        ".env.pilot.local.example",
        ".env.telegram.local.example",
        ".env.usdjpy.local.example",
    }
    for rel in tracked_files():
        name = Path(rel).name.lower()
        if name.startswith(".env") and name not in allowed_env_files:
            fail(f"tracked env file is not allowed: {rel}")
        if any(token in name for token in ("credential", "login_config", "password")):
            fail(f"tracked credential-like file name is not allowed: {rel}")
        if "secret" in name and not name.endswith(".example"):
            fail(f"tracked secret-like file name is not allowed: {rel}")


def check_backend_split_boundaries() -> None:
    """Backend repo must not depend on checked-in frontend/infra source trees."""
    forbidden_dirs = ("frontend",)
    for dirname in forbidden_dirs:
        if (ROOT / dirname).exists():
            fail(f"backend split violation: {dirname}/ must not exist in QuantGodBackend")

    for rel in tracked_files():
        normalized = rel.replace("\\", "/")
        if normalized.startswith(("frontend/",)):
            fail(f"backend split violation: tracked split-out source file {rel}")
        if normalized.startswith("Dashboard/vue-dist/"):
            fail(f"backend split violation: tracked frontend build artifact {rel}")
        if normalized.startswith("Dashboard/QuantGod_") and normalized.endswith((".json", ".csv")):
            fail(f"backend split violation: tracked runtime evidence artifact {rel}")
        if normalized in {
            "tools/responsive_check.mjs",
            "tools/install_phase1_frontend.py",
            "tools/apply_phase1_full.py",
            "tools/apply_phase2_full.py",
            "tools/apply_phase3_full.py",
        }:
            fail(f"backend split violation: split-out helper must not be tracked here: {rel}")


def check_required_backend_files() -> None:
    required = (
        "Dashboard/dashboard_server.js",
        "MQL5/Experts/QuantGod_MultiStrategy.mq5",
        "MQL5/Presets/QuantGod_MT5_HFM_LivePilot.set",
        "tools/ci_guard.py",
    )
    for rel in required:
        path = ROOT / rel
        if not path.exists():
            fail(f"missing required backend artifact: {rel}")

def check_mql5_safety_guards() -> None:
    ea = ROOT / "MQL5/Experts/QuantGod_MultiStrategy.mq5"
    required_markers = {
        "startup entry guard status": 'tradeStatus = "STARTUP_GUARD";',
        "RSI H1 uptrend sell blocker": "PilotRsiBlockSellInUptrend && IsUptrendRegimeLabel(regime.label)",
        "RSI H1 range-tight buy-only blocker": "PilotRsiRangeTightBuyOnly && IsRangeTightRegimeLabel(regime.label)",
        "RSI H1 blocked-trade audit text": "RSI H1 SELL blocked in",
    }
    for label, marker in required_markers.items():
        require_contains(ea, marker, label)


def check_live_preset_defaults() -> None:
    live_preset = ROOT / "MQL5/Presets/QuantGod_MT5_HFM_LivePilot.set"
    check_expected_set_values(
        live_preset,
        {
            "DashboardBuild": "QuantGod-v3.17-mt5-startup-entry-guard",
            "Watchlist": "USDJPY",
            "ShadowMode": "false",
            "ReadOnlyMode": "false",
            "EnablePilotMA": "false",
            "EnablePilotRsiH1Candidate": "true",
            "EnablePilotRsiH1Live": "true",
            "PilotRsiBlockSellInUptrend": "true",
            "PilotRsiRangeTightBuyOnly": "true",
            "EnablePilotBBH1Live": "false",
            "EnablePilotMacdH1Live": "false",
            "EnablePilotSRM15Live": "false",
            "EnableNonRsiLegacyLiveAuthorization": "false",
            "NonRsiLegacyLiveAuthorizationTag": "",
            "PilotLotSize": "0.01",
            "PilotMaxTotalPositions": "2",
            "PilotMaxPositionsPerSymbol": "2",
            "PilotRequireStrategyCommentForManagedPosition": "true",
            "PilotNewsCurrencies": "USD,JPY",
            "EnableUsdJpyTokyoBreakoutShadowResearch": "true",
            "EnableUsdJpyNightReversionShadowResearch": "true",
            "EnableUsdJpyH4PullbackShadowResearch": "true",
        },
    )


def main() -> None:
    check_required_backend_files()
    check_backend_split_boundaries()
    check_mql5_safety_guards()
    check_live_preset_defaults()
    check_secret_file_hygiene()
    print("CI_GUARD_OK")


if __name__ == "__main__":
    main()
