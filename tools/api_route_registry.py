#!/usr/bin/env python3
"""Export a read-only registry of QuantGod Backend `/api/*` routes."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PATH_RE = re.compile(r"/api/[A-Za-z0-9_./:-]+")

ROUTE_FILE_RELATIVE_PATHS = (
    "Dashboard/phase1_api_routes.js",
    "Dashboard/phase2_api_routes.js",
    "Dashboard/phase3_api_routes.js",
    "Dashboard/state_api_routes.js",
    "Dashboard/dashboard_server.js",
    "Dashboard/automation_chain_api_routes.js",
    "Dashboard/usdjpy_strategy_lab_api_routes.js",
    "Dashboard/case_memory_api_routes.js",
    "Dashboard/strategy_ga_factory_api_routes.js",
    "Dashboard/ga_factory_api_routes.js",
    "Dashboard/telegram_gateway_ops_api_routes.js",
    "Dashboard/hfm_crypto_cfd_api_routes.js",
    "Dashboard/live_automation_readiness_api_routes.js",
    "Dashboard/production_evidence_validation_api_routes.js",
)

PLACEHOLDER_PATHS = frozenset(
    {
        "/api/ai-analysis/history/:id",
        "/api/ai-analysis-v2/history/:id",
        "/api/vibe-coding/strategy/:id",
        "/api/usdjpy-strategy-lab/ga/candidate/:seedId",
        "/api/paramlab/auto-tester/:action",
        "/api/mt5-platform/:endpoint",
        "/api/mt5-trading/:endpoint",
        "/api/mt5/order/:ticket",
        "/api/mt5-readonly/:endpoint",
        "/api/mt5-readonly-secondary/:endpoint",
        "/api/mt5-symbol-registry/:endpoint",
        "/api/mt5/:endpoint",
    }
)

ALIAS_PREFIX_COVERAGE = {
    "/api/ga-factory/": "/api/ga-factory",
}

SAFETY_DEFAULTS = {
    "mode": "READ_ONLY_ROUTE_DISCOVERY",
    "readOnly": True,
    "writesFiles": False,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "credentialStorageAllowed": False,
    "livePresetMutationAllowed": False,
    "canOverrideKillSwitch": False,
}


def normalize_backend_path(path: str) -> str:
    clean = path.rstrip("/") or path

    dynamic_prefixes = (
        ("/api/ai-analysis/history/", "/api/ai-analysis/history/:id"),
        ("/api/ai-analysis-v2/history/", "/api/ai-analysis-v2/history/:id"),
        ("/api/vibe-coding/strategy/", "/api/vibe-coding/strategy/:id"),
        (
            "/api/usdjpy-strategy-lab/ga/candidate/",
            "/api/usdjpy-strategy-lab/ga/candidate/:seedId",
        ),
        ("/api/paramlab/auto-tester/", "/api/paramlab/auto-tester/:action"),
        ("/api/mt5-platform/", "/api/mt5-platform/:endpoint"),
        ("/api/mt5-trading/", "/api/mt5-trading/:endpoint"),
        ("/api/mt5/order/", "/api/mt5/order/:ticket"),
        ("/api/mt5-readonly/", "/api/mt5-readonly/:endpoint"),
        ("/api/mt5-readonly-secondary/", "/api/mt5-readonly-secondary/:endpoint"),
        ("/api/mt5-symbol-registry/", "/api/mt5-symbol-registry/:endpoint"),
        ("/api/mt5/", "/api/mt5/:endpoint"),
    )
    for prefix, normalized in dynamic_prefixes:
        if clean.startswith(prefix):
            return normalized

    return clean


def extract_api_paths(text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for match in PATH_RE.finditer(text):
        raw = match.group(0).rstrip("/") or match.group(0)
        if raw not in seen:
            paths.append(raw)
            seen.add(raw)
    return paths


def _source_file_entry(backend_root: Path, relative_path: str) -> dict:
    path = backend_root / relative_path
    raw_paths: list[str] = []
    normalized_paths: list[str] = []

    if path.exists():
        raw_paths = extract_api_paths(path.read_text(encoding="utf-8", errors="ignore"))
        normalized_paths = sorted({normalize_backend_path(raw) for raw in raw_paths})

    return {
        "relativePath": relative_path,
        "exists": path.exists(),
        "rawPathCount": len(raw_paths),
        "normalizedPathCount": len(normalized_paths),
        "rawPaths": raw_paths,
        "normalizedPaths": normalized_paths,
    }


def build_api_route_registry(
    backend_root: Path,
    route_files: Iterable[str] = ROUTE_FILE_RELATIVE_PATHS,
) -> dict:
    root = backend_root.resolve()
    source_files = [_source_file_entry(root, relative_path) for relative_path in route_files]

    raw_paths = sorted(
        {
            raw_path
            for source_file in source_files
            for raw_path in source_file["rawPaths"]
        }
    )
    normalized_paths = sorted(
        {
            normalized_path
            for source_file in source_files
            for normalized_path in source_file["normalizedPaths"]
        }
    )
    paths = sorted(set(raw_paths) | set(normalized_paths))

    return {
        "schema": "quantgod.backend_api_route_registry.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "backendRoot": str(root),
        "routeFileCount": len(source_files),
        "observedRouteFileCount": sum(1 for source_file in source_files if source_file["exists"]),
        "rawPathCount": len(raw_paths),
        "normalizedPathCount": len(normalized_paths),
        "pathCount": len(paths),
        "rawPaths": raw_paths,
        "normalizedPaths": normalized_paths,
        "paths": paths,
        "placeholderPaths": sorted(PLACEHOLDER_PATHS),
        "aliasPrefixCoverage": ALIAS_PREFIX_COVERAGE,
        "safety": dict(SAFETY_DEFAULTS),
        "sourceFiles": source_files,
    }


def default_backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export QuantGod Backend API route registry")
    parser.add_argument("--backend-root", default=str(default_backend_root()))
    parser.add_argument("--format", choices=("json", "paths"), default="json")
    args = parser.parse_args(argv)

    registry = build_api_route_registry(Path(args.backend_root))
    if args.format == "paths":
        print("\n".join(registry["paths"]))
        return 0

    print(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
