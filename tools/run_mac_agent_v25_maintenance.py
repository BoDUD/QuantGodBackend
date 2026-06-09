#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_ops_health import build_agent_ops_health
from hfm_crypto_cfd.runtime_scope import hfm_crypto_runtime_scope_meta, resolve_hfm_crypto_runtime_dir
from production_evidence_validation.burn_in import build_burn_in_report, load_latest_burn_in


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, fallback: int) -> int:
    try:
        return int(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        return fallback


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _burn_in_due(runtime_dir: Path, min_interval_seconds: int, force: bool) -> tuple[bool, float | None]:
    if force:
        return True, None
    latest = load_latest_burn_in(runtime_dir) or {}
    age = _age_seconds(latest.get("generatedAt") or latest.get("generatedAtIso"))
    if age is None:
        return True, None
    return age >= max(1, min_interval_seconds), age


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod Agent v2.5 scheduled maintenance")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    parser.add_argument("--hfm-crypto-runtime-dir", default=os.environ.get("QG_HFM_CRYPTO_RUNTIME_DIR", ""))
    parser.add_argument("--repo-root", default=str(root))
    parser.add_argument(
        "--burn-in-window-hours",
        type=int,
        default=_env_int("QG_PRODUCTION_BURN_IN_WINDOW_HOURS", 72),
    )
    parser.add_argument(
        "--burn-in-sample-interval-minutes",
        type=int,
        default=_env_int("QG_PRODUCTION_BURN_IN_SAMPLE_INTERVAL_MINUTES", 5),
    )
    parser.add_argument(
        "--burn-in-max-stale-minutes",
        type=int,
        default=_env_int("QG_PRODUCTION_BURN_IN_MAX_STALE_MINUTES", 15),
    )
    parser.add_argument(
        "--burn-in-min-interval-seconds",
        type=int,
        default=_env_int("QG_PRODUCTION_BURN_IN_INTERVAL_SECONDS", 300),
    )
    parser.add_argument("--force-burn-in", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    for name in [".env", ".env.local", ".env.usdjpy.local", ".env.auto.local", ".env.telegram.local", ".env.deepseek.local"]:
        _load_env_file(root / name)
    args = build_parser().parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    hfm_crypto_runtime_dir = resolve_hfm_crypto_runtime_dir(runtime_dir, args.hfm_crypto_runtime_dir)
    hfm_crypto_runtime_scope = hfm_crypto_runtime_scope_meta(runtime_dir, args.hfm_crypto_runtime_dir)
    repo_root = Path(args.repo_root)

    agent_health: dict[str, Any] | None = None
    if _truthy(os.environ.get("QG_AGENT_OPS_HEALTH_ENABLED"), default=True):
        agent_health = build_agent_ops_health(
            runtime_dir,
            repo_root=repo_root,
            write=True,
            hfm_crypto_runtime_dir=hfm_crypto_runtime_dir,
        )

    burn_in_report: dict[str, Any] | None = None
    burn_in_skipped_reason = ""
    latest_burn_in_age_seconds: float | None = None
    if _truthy(os.environ.get("QG_PRODUCTION_BURN_IN_ENABLED"), default=True):
        due, latest_burn_in_age_seconds = _burn_in_due(
            runtime_dir,
            args.burn_in_min_interval_seconds,
            args.force_burn_in,
        )
        if due:
            burn_in_report = build_burn_in_report(
                runtime_dir,
                write=True,
                window_hours=args.burn_in_window_hours,
                sample_interval_minutes=args.burn_in_sample_interval_minutes,
                max_stale_minutes=args.burn_in_max_stale_minutes,
            )
        else:
            burn_in_skipped_reason = "not_due"
    else:
        burn_in_skipped_reason = "disabled"

    payload = {
        "ok": True,
        "runtimeDir": str(runtime_dir),
        "hfmCryptoRuntimeScope": hfm_crypto_runtime_scope,
        "repoRoot": str(repo_root),
        "agentOpsHealth": {
            "written": agent_health is not None,
            "overallStatus": agent_health.get("overallStatus") if agent_health else None,
            "generatedAtIso": agent_health.get("generatedAtIso") if agent_health else None,
        },
        "burnIn": {
            "written": burn_in_report is not None,
            "status": burn_in_report.get("status") if burn_in_report else None,
            "generatedAt": burn_in_report.get("generatedAt") if burn_in_report else None,
            "skippedReason": burn_in_skipped_reason,
            "latestAgeSeconds": latest_burn_in_age_seconds,
            "minIntervalSeconds": args.burn_in_min_interval_seconds,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
