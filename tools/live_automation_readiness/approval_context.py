from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .schema import approval_evidence_review_path


def _read_existing_artifact(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_existing_path(runtime_dir: Path, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = Path(runtime_dir) / candidate
    if candidate.exists() and candidate.is_file():
        return str(candidate)
    return ""


def _default_operator_approval_json(runtime_dir: Path) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        os.environ.get("QG_LIVE_OPERATOR_APPROVAL_JSON", ""),
        os.environ.get("QG_OPERATOR_APPROVAL_JSON", ""),
        os.environ.get("QG_LIVE16_OPERATOR_APPROVAL_JSON", ""),
        str(repo_root / "runtime" / "agent" / "QuantGod_UserChatOperatorApproval_Live16.json"),
        str(repo_root / "runtime" / "agent" / "QuantGod_UserChatOperatorApproval.json"),
        str(Path.cwd() / "runtime" / "agent" / "QuantGod_UserChatOperatorApproval_Live16.json"),
        str(Path.cwd() / "runtime" / "agent" / "QuantGod_UserChatOperatorApproval.json"),
        str(Path(runtime_dir) / "agent" / "QuantGod_UserChatOperatorApproval_Live16.json"),
        str(Path(runtime_dir) / "agent" / "QuantGod_UserChatOperatorApproval.json"),
    ]
    for candidate in candidates:
        resolved = _resolve_existing_path(runtime_dir, candidate)
        if resolved:
            return resolved
    return ""


def operator_approval_json_for_refresh(
    runtime_dir: Path,
    operator_approval_json: str,
    *,
    refresh_sources: bool,
) -> tuple[str, dict[str, Any]]:
    explicit_path = str(operator_approval_json or "")
    if explicit_path:
        return explicit_path, {
            "mode": "explicit",
            "reused": False,
            "sourceArtifact": "",
            "operatorApprovalJsonPath": explicit_path,
        }

    evidence_path = approval_evidence_review_path(Path(runtime_dir))
    meta: dict[str, Any] = {
        "mode": "not_requested",
        "reused": False,
        "sourceArtifact": str(evidence_path),
        "operatorApprovalJsonPath": "",
    }
    if not refresh_sources:
        default_path = _default_operator_approval_json(Path(runtime_dir))
        if default_path:
            return default_path, {
                "mode": "auto_discovered_local_default",
                "reused": True,
                "sourceArtifact": "",
                "operatorApprovalJsonPath": default_path,
            }
        return "", meta

    prior = _read_existing_artifact(evidence_path)
    if not prior:
        default_path = _default_operator_approval_json(Path(runtime_dir))
        if default_path:
            return default_path, {
                "mode": "auto_discovered_local_default",
                "reused": True,
                "sourceArtifact": "",
                "operatorApprovalJsonPath": default_path,
            }
        meta["mode"] = "prior_evidence_missing"
        return "", meta
    if not bool(prior.get("operatorApprovalProvided")):
        default_path = _default_operator_approval_json(Path(runtime_dir))
        if default_path:
            return default_path, {
                "mode": "auto_discovered_local_default",
                "reused": True,
                "sourceArtifact": "",
                "operatorApprovalJsonPath": default_path,
            }
        meta["mode"] = "prior_evidence_not_accepted"
        return "", meta

    candidate = str(prior.get("operatorApprovalJsonPath") or "").strip()
    if not candidate:
        default_path = _default_operator_approval_json(Path(runtime_dir))
        if default_path:
            return default_path, {
                "mode": "auto_discovered_local_default",
                "reused": True,
                "sourceArtifact": "",
                "operatorApprovalJsonPath": default_path,
            }
        meta["mode"] = "prior_evidence_path_missing"
        return "", meta

    candidate_path = Path(candidate).expanduser()
    if not candidate_path.is_absolute():
        candidate_path = Path(runtime_dir) / candidate_path
    meta["operatorApprovalJsonPath"] = str(candidate_path)
    if not candidate_path.exists() or not candidate_path.is_file():
        default_path = _default_operator_approval_json(Path(runtime_dir))
        if default_path:
            return default_path, {
                "mode": "auto_discovered_local_default",
                "reused": True,
                "sourceArtifact": "",
                "operatorApprovalJsonPath": default_path,
            }
        meta["mode"] = "prior_evidence_path_not_found"
        return "", meta

    meta["mode"] = "reused_prior_accepted_evidence"
    meta["reused"] = True
    return str(candidate_path), meta
