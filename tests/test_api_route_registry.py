from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.api_route_registry import (
    build_api_route_registry,
    discover_route_files,
    extract_api_paths,
    normalize_backend_path,
)


class ApiRouteRegistryTests(unittest.TestCase):
    def test_extract_api_paths_deduplicates_in_order(self) -> None:
        text = "fetch('/api/a'); fetch('/api/a'); fetch('/api/b/status')"

        self.assertEqual(extract_api_paths(text), ["/api/a", "/api/b/status"])

    def test_registry_discovers_normalized_paths_and_safety_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard = root / "Dashboard"
            dashboard.mkdir()
            (dashboard / "dashboard_server.js").write_text(
                """
                app.get('/api/mt5-readonly/account', handler)
                app.get('/api/usdjpy-strategy-lab/ga/candidate/g0093', handler)
                """,
                encoding="utf-8",
            )
            (dashboard / "production_evidence_validation_api_routes.js").write_text(
                """
                router.get('/api/production-evidence-validation/status', handler)
                router.post('/api/production-evidence-validation/run', handler)
                """,
                encoding="utf-8",
            )

            registry = build_api_route_registry(root)
            paths = set(registry["paths"])

            self.assertIn("/api/mt5-readonly/account", paths)
            self.assertIn("/api/mt5-readonly/:endpoint", paths)
            self.assertIn("/api/usdjpy-strategy-lab/ga/candidate/:seedId", paths)
            self.assertIn("/api/production-evidence-validation/status", paths)
            self.assertIn("/api/production-evidence-validation/run", paths)
            self.assertTrue(registry["safety"]["readOnly"])
            self.assertFalse(registry["safety"]["orderSendAllowed"])
            self.assertFalse(registry["safety"]["livePresetMutationAllowed"])

    def test_registry_auto_discovers_dashboard_api_route_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard = root / "Dashboard"
            dashboard.mkdir()
            (dashboard / "new_feature_api_routes.js").write_text(
                "router.get('/api/new-feature/status', handler)",
                encoding="utf-8",
            )

            registry = build_api_route_registry(root)

            self.assertIn("/api/new-feature/status", registry["paths"])
            self.assertIn("Dashboard/new_feature_api_routes.js", discover_route_files(root))
            source_paths = {
                source_file["relativePath"]
                for source_file in registry["sourceFiles"]
                if "/api/new-feature/status" in source_file["rawPaths"]
            }
            self.assertEqual(source_paths, {"Dashboard/new_feature_api_routes.js"})

    def test_registry_can_use_explicit_route_files_for_focused_scans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard = root / "Dashboard"
            dashboard.mkdir()
            (dashboard / "new_feature_api_routes.js").write_text(
                "router.get('/api/new-feature/status', handler)",
                encoding="utf-8",
            )
            (dashboard / "focused_api_routes.js").write_text(
                "router.get('/api/focused/status', handler)",
                encoding="utf-8",
            )

            registry = build_api_route_registry(
                root,
                route_files=("Dashboard/focused_api_routes.js",),
            )

            self.assertIn("/api/focused/status", registry["paths"])
            self.assertNotIn("/api/new-feature/status", registry["paths"])

    def test_normalize_backend_path_preserves_static_paths(self) -> None:
        self.assertEqual(
            normalize_backend_path("/api/production-evidence-validation/status"),
            "/api/production-evidence-validation/status",
        )

    def test_cli_paths_format_outputs_registry_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard = root / "Dashboard"
            dashboard.mkdir()
            (dashboard / "hfm_crypto_cfd_api_routes.js").write_text(
                "router.get('/api/hfm-crypto/status', handler)",
                encoding="utf-8",
            )

            script = Path(__file__).resolve().parents[1] / "tools" / "api_route_registry.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--backend-root",
                    str(root),
                    "--format",
                    "paths",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("/api/hfm-crypto/status", result.stdout.splitlines())

    def test_cli_json_format_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Dashboard").mkdir()
            script = Path(__file__).resolve().parents[1] / "tools" / "api_route_registry.py"
            result = subprocess.run(
                [sys.executable, str(script), "--backend-root", str(root), "--format", "json"],
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "quantgod.backend_api_route_registry.v1")
            self.assertIn("paths", payload)


if __name__ == "__main__":
    unittest.main()
