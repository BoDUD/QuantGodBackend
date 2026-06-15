from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .schema import CORE_ARTIFACTS, REPORT_SCHEMA, SAFETY, SCHEMA_VERSION, manifest_path


LEGACY_ABSOLUTE_PATH_RE = re.compile(r"/Users/[^\n\r\t\"']*/Quard/QuantGod(?:/|\b)")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read_text(path: Path, limit_bytes: int = 2_000_000) -> str:
    raw = path.read_bytes()[:limit_bytes]
    return raw.decode("utf-8", errors="ignore")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_jsonl_object(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    return {}
                return payload if isinstance(payload, dict) else {}
    except OSError:
        return {}
    return {}


def _csv_headers(path: Path) -> List[str]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
            reader = csv.reader(handle)
            return [str(value) for value in next(reader, [])]
    except OSError:
        return []


def _declared_json_schema(path: Path, content_type: str) -> tuple[str, Any, Dict[str, Any]]:
    if content_type == "jsonl":
        payload = _first_jsonl_object(path)
    elif content_type == "json":
        payload = _read_json(path)
    else:
        return "", "", {}
    schema = str(payload.get("schema") or "")
    version = payload.get("schemaVersion", payload.get("version", payload.get("agentVersion", "")))
    return schema, version, payload


def _manifest_hash_rows_ok(payload: Dict[str, Any]) -> bool:
    rows = payload.get("artifacts")
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        if row.get("exists") is False:
            continue
        if not str(row.get("sha256") or ""):
            return False
    return True


def _row_status(blockers: Iterable[str]) -> str:
    return "PASS" if not list(blockers) else "FAIL"


def _artifact_row(runtime_dir: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    rel_path = str(spec["path"])
    path = runtime_dir / rel_path
    content_type = str(spec.get("contentType") or "json")
    expected_schemas = [str(item) for item in spec.get("expectedSchemas", [])]
    blockers: List[str] = []
    payload: Dict[str, Any] = {}
    declared_schema = ""
    declared_version: Any = ""
    headers: List[str] = []

    if not path.exists():
        if spec.get("required"):
            blockers.append("missing_required_artifact")
        return {
            "artifactId": spec["artifactId"],
            "category": spec.get("category", "runtime"),
            "required": bool(spec.get("required")),
            "path": rel_path,
            "contentType": content_type,
            "exists": False,
            "sizeBytes": 0,
            "sha256": "",
            "hashAlgorithm": "sha256",
            "expectedSchemas": expected_schemas,
            "declaredSchema": "",
            "declaredVersion": "",
            "headers": [],
            "status": _row_status(blockers),
            "blockers": blockers,
        }

    size_bytes = path.stat().st_size
    file_hash = _sha256(path)
    if content_type in {"json", "jsonl"}:
        declared_schema, declared_version, payload = _declared_json_schema(path, content_type)
        if not declared_schema:
            blockers.append("missing_declared_schema")
        elif expected_schemas and declared_schema not in expected_schemas:
            blockers.append("schema_mismatch")
    elif content_type == "csv":
        declared_schema = expected_schemas[0] if expected_schemas else ""
        headers = _csv_headers(path)
        if not headers:
            blockers.append("missing_csv_headers")
    else:
        blockers.append("unsupported_content_type")

    if LEGACY_ABSOLUTE_PATH_RE.search(_read_text(path)):
        blockers.append("legacy_quantgod_absolute_path")

    if spec.get("requiresArtifactHashes") and not _manifest_hash_rows_ok(payload):
        blockers.append("manifest_missing_artifact_hashes")

    return {
        "artifactId": spec["artifactId"],
        "category": spec.get("category", "runtime"),
        "required": bool(spec.get("required")),
        "path": rel_path,
        "contentType": content_type,
        "exists": True,
        "sizeBytes": size_bytes,
        "sha256": file_hash,
        "hashAlgorithm": "sha256",
        "expectedSchemas": expected_schemas,
        "declaredSchema": declared_schema,
        "declaredVersion": declared_version,
        "headers": headers,
        "status": _row_status(blockers),
        "blockers": blockers,
    }


def build_core_evidence_manifest(runtime_dir: Path, *, write: bool = False) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    rows = [_artifact_row(runtime_dir, spec) for spec in CORE_ARTIFACTS]
    blockers = [
        f"{row['artifactId']}:{blocker}"
        for row in rows
        for blocker in row.get("blockers", [])
    ]
    status = "PASS" if not blockers else "FAIL"
    payload: Dict[str, Any] = {
        "ok": status == "PASS",
        "schema": REPORT_SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": status,
        "statusZh": "核心运行证据完整" if status == "PASS" else "核心运行证据完整性失败",
        "hashAlgorithm": "sha256",
        "runtimeRoot": ".",
        "artifactCount": len(rows),
        "presentArtifactCount": sum(1 for row in rows if row.get("exists")),
        "blockerCount": len(blockers),
        "blockers": blockers,
        "artifacts": rows,
        "safety": dict(SAFETY),
        "nextActionZh": (
            "继续把 live-loop、production policy、GA、execution feedback 和 case memory 证据纳入晋级门。"
            if status == "PASS"
            else "先修复缺失证据、schema 漂移、旧仓绝对路径或 artifact hash 缺口，再允许进入晋级评审。"
        ),
    }
    if write:
        _write_json(manifest_path(runtime_dir), payload)
    return payload
