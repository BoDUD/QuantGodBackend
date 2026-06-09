from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "quantgod.mt5_reviewed_order_request.v1"
REQUEST_DIRECTORY = "runtime/agent/mt5_order_requests"
RECEIPT_DIRECTORY = "runtime/agent/mt5_order_receipts"
REVIEWED_REQUEST_WRITE_RELEASE_TOKEN = "QG_REVIEWED_MT5_REQUEST_WRITE_RELEASE_V1"


REQUIRED_FIELDS = (
    "requestId",
    "schema",
    "createdAtIso",
    "reviewPacketHash",
    "runtimePreflightHash",
    "operatorApprovalId",
    "lane",
    "brokerSymbol",
    "canonicalSymbol",
    "side",
    "orderType",
    "volumeLots",
    "killSwitchOk",
    "runtimeFresh",
    "spreadProbeOk",
    "symbolMappingOk",
    "dryRunReplayPassed",
)

REQUIRED_TRUE_FUSES = (
    "killSwitchOk",
    "runtimeFresh",
    "spreadProbeOk",
    "symbolMappingOk",
    "dryRunReplayPassed",
)


@dataclass(frozen=True)
class RequestWriterDecision:
    ok: bool
    status: str
    reason: str
    request_id: str
    final_request_path: str
    temp_request_path: str
    planned_receipt_path: str
    serialized_payload_hash: str
    idempotency_hash: str
    canonical_json: str
    blocker_codes: tuple[str, ...]
    wrote_request_file: bool = False
    wrote_receipt_file: bool = False
    called_broker: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "requestId": self.request_id,
            "finalRequestPath": self.final_request_path,
            "tempRequestPath": self.temp_request_path,
            "plannedReceiptPath": self.planned_receipt_path,
            "serializedPayloadHash": self.serialized_payload_hash,
            "idempotencyHash": self.idempotency_hash,
            "canonicalJson": self.canonical_json,
            "blockerCodes": list(self.blocker_codes),
            "wroteRequestFile": self.wrote_request_file,
            "wroteReceiptFile": self.wrote_receipt_file,
            "calledBroker": self.called_broker,
        }


def canonical_request_json(request: dict[str, Any]) -> str:
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def payload_hash(request: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_request_json(request).encode("utf-8")).hexdigest()


def idempotency_hash(request: dict[str, Any]) -> str:
    payload = {
        "requestId": request.get("requestId", ""),
        "reviewPacketHash": request.get("reviewPacketHash", ""),
        "runtimePreflightHash": request.get("runtimePreflightHash", ""),
        "payloadHash": payload_hash(request),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise_relative_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _path_blockers(relative_path: str, *, expected_prefix: str) -> list[str]:
    blockers: list[str] = []
    if not relative_path:
        return ["PATH_EMPTY"]
    if relative_path.startswith("/") or re.match(r"^[A-Za-z]:/", relative_path):
        blockers.append("PATH_ABSOLUTE_FORBIDDEN")
    parts = [part for part in relative_path.split("/") if part]
    if any(part == ".." for part in parts):
        blockers.append("PATH_TRAVERSAL_FORBIDDEN")
    if not relative_path.startswith(expected_prefix.rstrip("/") + "/"):
        blockers.append("PATH_PREFIX_MISMATCH")
    return blockers


def _validate_request(request: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    missing = [field for field in REQUIRED_FIELDS if field not in request]
    if missing:
        blockers.append("REQUEST_REQUIRED_FIELDS_MISSING")
    if request.get("schema") != REQUEST_SCHEMA:
        blockers.append("REQUEST_SCHEMA_MISMATCH")
    request_id = str(request.get("requestId") or "")
    if not request_id or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$", request_id):
        blockers.append("REQUEST_ID_INVALID")
    if str(request.get("side") or "") not in {"BUY", "SELL"}:
        blockers.append("REQUEST_SIDE_INVALID")
    if str(request.get("orderType") or "") not in {"MARKET", "LIMIT", "STOP"}:
        blockers.append("REQUEST_ORDER_TYPE_INVALID")
    try:
        volume = float(request.get("volumeLots"))
    except (TypeError, ValueError):
        blockers.append("REQUEST_VOLUME_INVALID")
    else:
        if volume < 0:
            blockers.append("REQUEST_VOLUME_NEGATIVE")
    for field in REQUIRED_TRUE_FUSES:
        if request.get(field) is not True:
            blockers.append(f"REQUEST_FUSE_{field}_NOT_TRUE")
    return blockers


def _validate_plan(request: dict[str, Any], plan: dict[str, Any]) -> tuple[str, str, list[str]]:
    request_id = str(request.get("requestId") or "")
    final_path = _normalise_relative_path(
        plan.get("finalRequestPath")
        or plan.get("plannedRequestPath")
        or f"{REQUEST_DIRECTORY}/{request_id}.json"
    )
    receipt_path = _normalise_relative_path(
        plan.get("plannedReceiptPath")
        or f"{RECEIPT_DIRECTORY}/{request_id}.receipt.json"
    )
    blockers = [
        *_path_blockers(final_path, expected_prefix=REQUEST_DIRECTORY),
        *_path_blockers(receipt_path, expected_prefix=RECEIPT_DIRECTORY),
    ]
    if final_path and Path(final_path).name != f"{request_id}.json":
        blockers.append("REQUEST_FILENAME_MUST_MATCH_REQUEST_ID")
    if receipt_path and Path(receipt_path).name != f"{request_id}.receipt.json":
        blockers.append("RECEIPT_FILENAME_MUST_MATCH_REQUEST_ID")
    if plan.get("atomicWriteRequired") is not True:
        blockers.append("ATOMIC_WRITE_REQUIRED")
    idempotency_key = str(plan.get("idempotencyKey") or request_id)
    if idempotency_key != request_id:
        blockers.append("IDEMPOTENCY_KEY_MISMATCH")
    return final_path, receipt_path, blockers


def _make_decision(
    *,
    ok: bool,
    status: str,
    reason: str,
    request: dict[str, Any],
    final_request_path: str,
    temp_request_path: str,
    planned_receipt_path: str,
    blocker_codes: list[str],
    wrote_request_file: bool = False,
) -> RequestWriterDecision:
    return RequestWriterDecision(
        ok=ok,
        status=status,
        reason=reason,
        request_id=str(request.get("requestId") or ""),
        final_request_path=final_request_path,
        temp_request_path=temp_request_path,
        planned_receipt_path=planned_receipt_path,
        serialized_payload_hash=payload_hash(request) if isinstance(request, dict) else "",
        idempotency_hash=idempotency_hash(request) if isinstance(request, dict) else "",
        canonical_json=canonical_request_json(request) if isinstance(request, dict) else "",
        blocker_codes=tuple(blocker_codes),
        wrote_request_file=wrote_request_file,
        wrote_receipt_file=False,
        called_broker=False,
    )


def prepare_request_writer_decision(
    runtime_dir: Path,
    request: dict[str, Any],
    plan: dict[str, Any],
    *,
    execution_enabled: bool = False,
    allow_request_write: bool = False,
    review_release_token: str = "",
) -> RequestWriterDecision:
    final_path, receipt_path, blockers = _validate_plan(request, plan)
    blockers.extend(_validate_request(request))
    final_target = Path(runtime_dir) / final_path if final_path else Path(runtime_dir)
    temp_target = final_target.with_name(f"{final_target.name}.tmp.{os.getpid()}")
    if final_path and final_target.exists():
        blockers.append("FINAL_REQUEST_FILE_ALREADY_EXISTS")
    if not execution_enabled:
        blockers.append("WRITER_EXECUTION_DISABLED")
    if not allow_request_write:
        blockers.append("REQUEST_WRITE_NOT_RELEASED")
    if review_release_token != REVIEWED_REQUEST_WRITE_RELEASE_TOKEN:
        blockers.append("REQUEST_WRITE_RELEASE_TOKEN_MISSING")
    if blockers:
        return _make_decision(
            ok=False,
            status="BLOCKED",
            reason="request writer blocked before any file write",
            request=request,
            final_request_path=final_path,
            temp_request_path=str(temp_target),
            planned_receipt_path=receipt_path,
            blocker_codes=sorted(set(blockers)),
        )
    return _make_decision(
        ok=True,
        status="READY_TO_COMMIT_REQUEST_FILE",
        reason="request passed schema, path, idempotency and disabled-first release checks",
        request=request,
        final_request_path=final_path,
        temp_request_path=str(temp_target),
        planned_receipt_path=receipt_path,
        blocker_codes=[],
    )


def commit_request_file(
    runtime_dir: Path,
    request: dict[str, Any],
    plan: dict[str, Any],
    *,
    execution_enabled: bool = False,
    allow_request_write: bool = False,
    review_release_token: str = "",
) -> RequestWriterDecision:
    decision = prepare_request_writer_decision(
        runtime_dir,
        request,
        plan,
        execution_enabled=execution_enabled,
        allow_request_write=allow_request_write,
        review_release_token=review_release_token,
    )
    if not decision.ok:
        return decision

    final_target = Path(runtime_dir) / decision.final_request_path
    temp_target = Path(decision.temp_request_path)
    final_target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temp_target, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(decision.canonical_json)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_target, final_target)
        except FileExistsError:
            return _make_decision(
                ok=False,
                status="BLOCKED",
                reason="final request file already exists at atomic commit",
                request=request,
                final_request_path=decision.final_request_path,
                temp_request_path=decision.temp_request_path,
                planned_receipt_path=decision.planned_receipt_path,
                blocker_codes=["FINAL_REQUEST_FILE_ALREADY_EXISTS"],
            )
        try:
            dir_fd = os.open(final_target.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        try:
            temp_target.unlink()
        except FileNotFoundError:
            pass

    return _make_decision(
        ok=True,
        status="REQUEST_FILE_COMMITTED",
        reason="request file committed atomically; broker and receipt paths untouched",
        request=request,
        final_request_path=decision.final_request_path,
        temp_request_path=decision.temp_request_path,
        planned_receipt_path=decision.planned_receipt_path,
        blocker_codes=[],
        wrote_request_file=True,
    )
