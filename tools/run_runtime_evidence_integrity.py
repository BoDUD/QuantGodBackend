#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from runtime_evidence_integrity.report import build_core_evidence_manifest

SUMMARY_SCHEMA = "quantgod.core_runtime_evidence_summary.v1"
SUMMARY_SCHEMA_VERSION = 1
DEFAULT_SUMMARY_QUEUE_LIMIT = 8
DEFAULT_SUMMARY_BLOCKER_LIMIT = 12


def _bounded_list(value: Any, *, limit: int) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value[: max(0, limit)]


def _summarize_recovery_row(row: dict[str, Any]) -> dict[str, Any]:
    compact_keys = (
        "kind",
        "artifactId",
        "category",
        "timeframe",
        "status",
        "priority",
        "stabilityGrade",
        "closureMode",
        "sourceGapStatus",
        "sourceGapArtifact",
        "copyRatesExportFreshnessStatus",
        "copyRatesExportGeneratedLagHours",
        "copyRatesExportLatestLagHours",
        "evidenceGapZh",
        "copyRatesExportNextActionZh",
        "nextActionZh",
        "acceptanceZh",
        "prerequisiteCommand",
        "refreshCommand",
        "collectionCommand",
        "caseMemoryBuildCommand",
        "verifyCommand",
        "allowedLanes",
        "forbiddenSideEffects",
    )
    return {key: row[key] for key in compact_keys if key in row and row[key] is not None}


def build_summary(
    payload: dict[str, Any],
    *,
    queue_limit: int = DEFAULT_SUMMARY_QUEUE_LIMIT,
    blocker_limit: int = DEFAULT_SUMMARY_BLOCKER_LIMIT,
) -> dict[str, Any]:
    blockers = _bounded_list(payload.get("blockers"), limit=blocker_limit)
    promotion_blockers = _bounded_list(payload.get("promotionBlockers"), limit=blocker_limit)
    recovery_queue = _bounded_list(payload.get("promotionRecoveryQueue"), limit=queue_limit)
    blocker_count = int(payload.get("blockerCount") or 0)
    promotion_blocker_count = int(payload.get("promotionBlockerCount") or 0)
    recovery_queue_count = int(payload.get("promotionRecoveryQueueCount") or 0)
    return {
        "schema": SUMMARY_SCHEMA,
        "schemaVersion": SUMMARY_SCHEMA_VERSION,
        "generatedAt": payload.get("generatedAt"),
        "status": payload.get("status"),
        "statusZh": payload.get("statusZh"),
        "ok": bool(payload.get("ok")),
        "artifactCount": payload.get("artifactCount"),
        "presentArtifactCount": payload.get("presentArtifactCount"),
        "blockerCount": blocker_count,
        "blockers": blockers,
        "blockerOverflowCount": max(0, blocker_count - len(blockers)),
        "promotionGateStatus": payload.get("promotionGateStatus"),
        "promotionGatePassed": bool(payload.get("promotionGatePassed")),
        "promotionBlockerCount": promotion_blocker_count,
        "promotionBlockers": promotion_blockers,
        "promotionBlockerOverflowCount": max(0, promotion_blocker_count - len(promotion_blockers)),
        "promotionRecoveryQueueCount": recovery_queue_count,
        "promotionRecoveryQueue": [
            _summarize_recovery_row(row) for row in recovery_queue if isinstance(row, dict)
        ],
        "promotionRecoveryQueueOverflowCount": max(0, recovery_queue_count - len(recovery_queue)),
        "nextActionZh": payload.get("nextActionZh"),
        "safety": dict(payload.get("safety") or {}),
    }


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod core runtime evidence integrity guard")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(repo_root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "build", "verify"):
        item = sub.add_parser(command)
        item.add_argument("--write", action="store_true")
    summary = sub.add_parser("summary")
    summary.add_argument("--queue-limit", type=int, default=DEFAULT_SUMMARY_QUEUE_LIMIT)
    summary.add_argument("--blocker-limit", type=int, default=DEFAULT_SUMMARY_BLOCKER_LIMIT)
    args = parser.parse_args(argv)

    runtime_dir = Path(args.runtime_dir).expanduser()
    if not runtime_dir.is_absolute():
        runtime_dir = repo_root / runtime_dir
    payload = build_core_evidence_manifest(
        runtime_dir,
        write=getattr(args, "write", False) or args.command == "build",
    )
    if args.command == "summary":
        emit(
            build_summary(
                payload,
                queue_limit=args.queue_limit,
                blocker_limit=args.blocker_limit,
            )
        )
        return 0
    emit(payload)
    if args.command == "verify" and payload.get("status") != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
