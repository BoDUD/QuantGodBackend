from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"
MAC_LAUNCHER = ROOT / "Start_QuantGod_mac.sh"
WINDOWS_LAUNCHERS = (
    ROOT / "Start_QuantGod_MT5.bat",
    ROOT / "Start_QuantGod_MT5_HFM_Shadow.bat",
    ROOT / "Start_QuantGod_MT5_HFM_LivePilot.bat",
)


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise AssertionError(f"unterminated function: {signature}")


def parse_set_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", ";")) and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


class Mt5ExecutionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA_PATH.read_text(encoding="utf-8-sig")

    def test_tracked_ea_permanently_reports_no_live_mode(self):
        body = function_body(self.source, "bool IsPilotLiveMode()")
        self.assertRegex(body, r"\breturn\s+false\s*;")
        self.assertNotIn("EnablePilotAutoTrading &&", body)

        blocker = function_body(self.source, "string LiveTradePermissionBlocker(string symbol)")
        self.assertIn('return "EXECUTION_LANE_REMOVED";', blocker)
        self.assertNotIn('return "";', blocker)

    def test_all_tracked_mql_sources_contain_no_broker_mutation_primitive(self):
        forbidden = {
            "trade include": r"#include\s*<Trade/Trade\.mqh>",
            "CTrade type": r"\bCTrade\b",
            "CTrade instance": r"\bg_trade\b",
            "order send": r"\bOrderSend(?:Async)?\s*\(",
            "trade method": r"\.(?:Buy|Sell|PositionClose|PositionModify|OrderDelete|OrderModify)\s*\(",
            "raw trade action": r"TRADE_ACTION_(?:DEAL|PENDING|SLTP|MODIFY|REMOVE)",
        }
        sources = sorted((ROOT / "MQL5").rglob("*.mq5")) + sorted((ROOT / "MQL5").rglob("*.mqh"))
        self.assertTrue(sources)
        for source_path in sources:
            source = source_path.read_text(encoding="utf-8-sig")
            for label, pattern in forbidden.items():
                with self.subTest(path=source_path.relative_to(ROOT), label=label):
                    self.assertNotRegex(source, pattern)

    def test_legacy_mutation_entry_points_are_advisory_fail_closed_stubs(self):
        signatures = (
            "bool SendPilotMarketOrder(string symbol, int direction, double slPrice, double tpPrice, string strategyKey)",
            "bool ClosePositionWithExecutionGuard(ulong ticket)",
            "bool ModifyPilotPositionStops(ulong ticket, string symbol, double slPrice, double tpPrice)",
        )
        for signature in signatures:
            with self.subTest(signature=signature):
                body = function_body(self.source, signature)
                self.assertIn("execution lane removed", body.lower())
                self.assertRegex(body, r"\breturn\s+false\s*;")
                self.assertNotRegex(body, r"\bMqlTrade(?:Request|Result)\b")

    def test_every_tracked_mt5_config_disables_terminal_live_trading(self):
        configs = sorted((ROOT / "MQL5" / "Config").glob("*.ini"))
        self.assertTrue(configs)
        for config in configs:
            with self.subTest(config=config.relative_to(ROOT)):
                text = config.read_text(encoding="utf-8-sig")
                self.assertIn("AllowLiveTrading=0", text)
                self.assertNotIn("AllowLiveTrading=1", text)

        for tester_config in sorted((ROOT / "MQL5" / "Config" / "BacktestLab").glob("*.ini")):
            with self.subTest(tester_config=tester_config.relative_to(ROOT)):
                text = tester_config.read_text(encoding="utf-8-sig")
                self.assertIn("[Tester]", text)
                self.assertNotIn("[StartUp]", text)

    def test_non_backtest_presets_are_all_shadow_readonly(self):
        presets = [
            path
            for path in sorted((ROOT / "MQL5" / "Presets").glob("*.set"))
            if "Backtest" not in path.name
        ]
        self.assertTrue(presets)
        for preset in presets:
            values = parse_set_values(preset)
            with self.subTest(preset=preset.name):
                self.assertEqual(values.get("ShadowMode"), "true")
                self.assertEqual(values.get("ReadOnlyMode"), "true")
                self.assertEqual(values.get("EnablePilotAutoTrading"), "false")
                self.assertFalse(
                    any(key.startswith("Enable") and key.endswith("Live") and value == "true" for key, value in values.items())
                )
                self.assertNotEqual(values.get("PilotCloseOnKillSwitch"), "true")

    def test_mac_launcher_only_installs_and_starts_shadow_allowlist(self):
        text = MAC_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('shadow|off)', text)
        self.assertIn('assert_shadow_readonly_ea_source "$EA_SOURCE"', text)
        self.assertIn("QuantGod_MT5_HFM_Shadow_mac.ini", text)
        self.assertIn(
            'cp MQL5/Presets/QuantGod_MT5_HFM_Shadow.set "$MT5_PRESETS/QuantGod_MT5_HFM_Shadow.set"',
            text,
        )
        for forbidden in (
            "QG_MT5_LIVE_LAUNCH_ALLOWED",
            "QG_MT5_SECONDARY_ENABLED",
            "QG_MT5_SECONDARY_ALLOW_LIVE_TRADING",
            "QuantGod_MT5_HFM_LivePilot_mac.ini",
            "rsync -a MQL5/Presets/",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_mac_compile_cannot_reuse_a_stale_binary(self):
        text = MAC_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('EA_BUILD_DIR="$(mktemp -d "$EA_BUILD_ROOT/compile-run.XXXXXX")"', text)
        self.assertIn('EA_COMPILE_RUN_ID="${EA_BUILD_DIR##*/}"', text)
        self.assertIn('EA_BUILD_WIN_DIR="C:\\\\qg\\\\$EA_COMPILE_RUN_ID"', text)
        self.assertIn(
            'EA_EXPECTED_WINDOWS_SOURCE="${EA_BUILD_WIN_DIR}\\\\QuantGod_MultiStrategy.mq5"',
            text,
        )
        self.assertIn(
            'rm -f "$EA_BUILD_OUTPUT" "$EA_COMPILE_LOG" "$EA_COMPILE_MARKER" "$EA_INSTALL_TMP"',
            text,
        )
        self.assertLess(text.index('mv -f "$EA_INSTALLED_OUTPUT" "$EA_DISABLED_OUTPUT"'), text.index('if [[ -x "$WINE64" ]]'))
        self.assertIn('EA_COMPILE_WAIT_SECONDS="${QG_MT5_COMPILE_WAIT_SECONDS:-120}"', text)
        self.assertIn('[[ ! "$EA_COMPILE_WAIT_SECONDS" =~ ^[0-9]+$ ]]', text)
        self.assertIn('EA_COMPILE_WAIT_SECONDS > 600', text)
        self.assertIn('"$EA_BUILD_OUTPUT" -nt "$EA_COMPILE_MARKER"', text)
        self.assertIn('-s "$EA_COMPILE_LOG" && "$EA_COMPILE_LOG" -nt "$EA_COMPILE_MARKER"', text)
        self.assertIn('"$EA_COMPILE_READY" != "1"', text)
        self.assertIn('EA_COMPILE_LOG_SAFE=0', text)
        self.assertIn('tools/validate_metaeditor_compile.py', text)
        self.assertIn('--source "$EA_BUILD_SOURCE"', text)
        self.assertIn('--ex5 "$EA_BUILD_OUTPUT"', text)
        self.assertIn('--log "$EA_COMPILE_LOG"', text)
        self.assertIn('--marker "$EA_COMPILE_MARKER"', text)
        self.assertEqual(
            text.count('--expected-windows-source "$EA_EXPECTED_WINDOWS_SOURCE"'),
            3,
        )
        self.assertIn('"$EA_COMPILE_LOG_SAFE" != "1"', text)
        self.assertIn('if [[ "$COMPILE_CODE" -ne 0 ]]; then', text)
        self.assertIn('EA_CANONICAL_SOURCE="$EA_BUILD_ROOT/QuantGod_MultiStrategy.mq5"', text)
        self.assertIn('EA_CANONICAL_OUTPUT="$EA_BUILD_ROOT/QuantGod_MultiStrategy.ex5"', text)
        self.assertIn('EA_CANONICAL_LOG="$EA_BUILD_ROOT/compile.log"', text)
        self.assertIn('cp -p "$EA_BUILD_SOURCE" "$EA_CANONICAL_SOURCE_TMP"', text)
        self.assertIn('cp -p "$EA_BUILD_OUTPUT" "$EA_CANONICAL_OUTPUT_TMP"', text)
        self.assertIn('cp -p "$EA_COMPILE_LOG" "$EA_CANONICAL_LOG_TMP"', text)
        self.assertLess(
            text.index('mv -f "$EA_CANONICAL_OUTPUT_TMP" "$EA_CANONICAL_OUTPUT"'),
            text.index('mv -f "$EA_CANONICAL_SOURCE_TMP" "$EA_CANONICAL_SOURCE"'),
        )
        self.assertLess(
            text.index('mv -f "$EA_CANONICAL_LOG_TMP" "$EA_CANONICAL_LOG"'),
            text.index('mv -f "$EA_CANONICAL_SOURCE_TMP" "$EA_CANONICAL_SOURCE"'),
        )
        self.assertIn('cp -p "$EA_CANONICAL_OUTPUT" "$EA_INSTALL_TMP"', text)
        self.assertIn('mv -f "$EA_INSTALL_TMP" "$EA_INSTALLED_OUTPUT"', text)
        self.assertIn("previous EA binary remains quarantined", text)
        self.assertNotRegex(
            text,
            r'cp\s+"\$EA_BUILD_OUTPUT"\s+MQL5/Experts/QuantGod_MultiStrategy\.ex5',
        )

    def test_windows_mt5_launchers_are_retired_without_side_effects(self):
        for launcher in WINDOWS_LAUNCHERS:
            text = launcher.read_text(encoding="utf-8")
            with self.subTest(launcher=launcher.name):
                self.assertIn("retired", text.lower())
                self.assertIn("exit /b 2", text.lower())
                self.assertNotRegex(text.lower(), r"(?m)^\s*(?:copy|xcopy|start|taskkill)\b")

    def test_tester_runners_are_pinned_to_canonical_isolated_root(self):
        ps_runner = (ROOT / "tools" / "run_mt5_backtest_lab.ps1").read_text(encoding="utf-8")
        py_runner = (ROOT / "tools" / "run_param_lab.py").read_text(encoding="utf-8")
        self.assertNotIn(r"C:\Program Files\HFM Metatrader 5", ps_runner)
        self.assertIn("HFM_MT5_Tester_Isolated", ps_runner)
        self.assertIn("Resolve-Path -LiteralPath $expectedTesterRoot", ps_runner)
        self.assertNotIn('MQL5\\Experts\\QuantGod_MultiStrategy.ex5', ps_runner)
        self.assertIn('DEFAULT_REPO_ROOT / "runtime" / "HFM_MT5_Tester_Isolated"', py_runner)
        self.assertIn("resolve_isolated_tester_root", py_runner)
        self.assertNotIn('binary_path = repo_root / "MQL5" / "Experts" / "QuantGod_MultiStrategy.ex5"', py_runner)


if __name__ == "__main__":
    unittest.main()
