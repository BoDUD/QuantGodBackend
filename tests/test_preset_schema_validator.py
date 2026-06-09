"""Validate MQL5 preset files have required keys and sensible value ranges."""
from __future__ import annotations
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRESET = REPO_ROOT / "MQL5" / "Presets" / "QuantGod_MT5_HFM_LivePilot.set"

REQUIRED_KEYS = [
    "Watchlist", "DashboardBuild",
    "EnablePilotAutoTrading", "EnablePilotStartupEntryGuard",
    "PilotStartupEntryGuardMode",
    "PilotStartupEntryFastWarmupMinutes",
    "PilotStartupEntryFastWarmupM1Bars",
    "EnablePilotRsiH1Live", "EnablePilotRsiH1Candidate",
    "EnablePilotBBH1Live", "EnablePilotBBH1Candidate",
    "EnablePilotMacdH1Live", "EnablePilotMacdH1Candidate",
    "EnablePilotSRM15Live", "EnablePilotSRM15Candidate",
    "EnableNonRsiLegacyLiveAuthorization",
    "EnableUsdJpyTokyoBreakoutShadowResearch",
    "EnableUsdJpyNightReversionShadowResearch",
    "EnableUsdJpyH4PullbackShadowResearch",
    "EnableHfmCryptoSpecExporter",
    "HfmCryptoSpecExportSymbols",
    "HfmCryptoSpecExportMaxSymbols",
    "PilotLotSize", "PilotMaxTotalPositions",
    "PilotMaxFloatingLossUSC", "PilotMaxRealizedLossDayUSC",
    "ReadOnlyMode", "ShadowMode",
]

NUMERIC_RANGES = {
    "PilotLotSize": (0.001, 10.0),
    "PilotMaxTotalPositions": (0.0, 100.0),
    "PilotMaxFloatingLossUSC": (0.0, 1000.0),
    "PilotMaxRealizedLossDayUSC": (0.0, 1000.0),
    "PilotRsiPeriod": (1, 100),
    "PilotRsiOverbought": (50, 100),
    "PilotRsiOversold": (0, 50),
    "PilotRsiCrossbackThreshold": (0, 5),
    "PilotStartupEntryMinWaitMinutes": (0, 60),
    "PilotStartupEntryFastWarmupMinutes": (0, 30),
    "PilotStartupEntryFastWarmupM1Bars": (0, 10),
    "PilotNewsHighImpactPreBlockMinutes": (0, 180),
    "HfmCryptoSpecExportMaxSymbols": (1, 500),
}


class PresetSchemaValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DEFAULT_PRESET.exists():
            raise unittest.SkipTest(f"Preset not found: {DEFAULT_PRESET}")
        cls.values = {}
        for raw in DEFAULT_PRESET.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cls.values[k.strip()] = v.strip()

    def test_all_required_keys_present(self):
        for key in REQUIRED_KEYS:
            self.assertIn(key, self.values, f"Missing required key: {key}")

    def test_numeric_values_in_range(self):
        for key, (lo, hi) in NUMERIC_RANGES.items():
            if key not in self.values:
                continue
            try:
                val = float(self.values[key])
            except ValueError:
                self.fail(f"{key} value is not numeric: {self.values[key]}")
            self.assertTrue(lo <= val <= hi, f"{key}={val} outside [{lo}, {hi}]")

    def test_safety_keys_are_off(self):
        safety_off = ["EnableNonRsiLegacyLiveAuthorization"]
        for key in safety_off:
            if key in self.values:
                self.assertIn(self.values[key].lower(), {"false", "0"},
                    f"Safety key {key} must be false/0, got {self.values[key]}")

    def test_watchlist_contains_usdjpy(self):
        watchlist = self.values.get("Watchlist", "").upper()
        self.assertIn("USDJPY", watchlist, "Live preset should include USDJPY")

    def test_startup_guard_mode_is_known(self):
        self.assertIn(self.values.get("PilotStartupEntryGuardMode"), {"H1_STRICT", "FAST_WARMUP", "BACKTEST_OFF"})


if __name__ == "__main__":
    unittest.main()
