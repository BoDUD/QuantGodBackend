from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .approval_context import operator_approval_json_for_refresh
from .live_pilot_activation import build_live_pilot_activation_review, read_live_pilot_activation_review
from .order_request_contract import build_mt5_order_request_contract, read_mt5_order_request_contract
from .receipt_reconciliation import build_receipt_reconciliation_review, read_receipt_reconciliation_review
from .schema import (
    EA_REQUEST_READER_REVIEW_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    ea_request_reader_review_path,
    live_pilot_activation_review_path,
    order_request_contract_path,
    receipt_reconciliation_review_path,
    utc_now_iso,
)

try:  # pragma: no cover - import style differs when called as a standalone script.
    from tools.mt5_readonly_bridge import runtime_dir_candidates
except Exception:  # pragma: no cover
    try:
        from mt5_readonly_bridge import runtime_dir_candidates
    except Exception:  # pragma: no cover
        runtime_dir_candidates = None


REQUIRED_EA_MARKERS: tuple[dict[str, str], ...] = (
    {
        "id": "disabled_by_default",
        "marker": "QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT",
        "reasonZh": "EA request reader 必须默认关闭，不能因 artifact 生成而自动启用。",
    },
    {
        "id": "schema_validation",
        "marker": "QG_EA_REQUEST_SCHEMA_VALIDATION_REQUIRED",
        "reasonZh": "EA 必须校验 request schema、字段类型、枚举值和安全 fuse。",
    },
    {
        "id": "idempotency_request_id",
        "marker": "QG_EA_IDEMPOTENCY_REQUEST_ID_REQUIRED",
        "reasonZh": "EA 必须按 requestId 幂等处理，重复 request 只能生成拒绝/重复 receipt。",
    },
    {
        "id": "kill_switch",
        "marker": "QG_EA_KILL_SWITCH_REQUIRED",
        "reasonZh": "EA 读取 request 前必须检查 kill switch、日内亏损和交易权限。",
    },
    {
        "id": "receipt_writer",
        "marker": "QG_EA_RECEIPT_WRITER_REQUIRED",
        "reasonZh": "EA 必须为每个 request 写 receipt，包含拒绝原因和安全快照 hash。",
    },
    {
        "id": "separate_order_send_review",
        "marker": "QG_EA_ORDER_SEND_REQUIRES_SEPARATE_REVIEW",
        "reasonZh": "任何真实下单调用必须另走独立代码评审，不能由本审查 artifact 解锁。",
    },
)

EA_REQUEST_READER_RUNTIME_STATUS_SCHEMA = "quantgod.mql5.ea_request_reader_review_status.v1"

REQUIRED_RUNTIME_MARKERS: tuple[tuple[str, str], ...] = (
    ("disabledByDefault", "QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT"),
    ("schemaValidationRequired", "QG_EA_REQUEST_SCHEMA_VALIDATION_REQUIRED"),
    ("idempotencyRequestIdRequired", "QG_EA_IDEMPOTENCY_REQUEST_ID_REQUIRED"),
    ("killSwitchRequired", "QG_EA_KILL_SWITCH_REQUIRED"),
    ("receiptWriterRequired", "QG_EA_RECEIPT_WRITER_REQUIRED"),
    ("orderSendRequiresSeparateReview", "QG_EA_ORDER_SEND_REQUIRES_SEPARATE_REVIEW"),
)

REQUIRED_RUNTIME_SAFETY_FALSE_KEYS: tuple[str, ...] = (
    "requestFilesRead",
    "requestFilesConsumed",
    "receiptFilesWritten",
    "orderSendAllowed",
    "mt5OrderSendAllowed",
    "brokerCallsMade",
    "livePresetMutationAllowed",
    "credentialStorageAllowed",
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, "", []):
        row["value"] = value
    return row


def _read_existing_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dependency_source(payload: dict[str, Any], *, prefer_existing: bool) -> str:
    if payload:
        return "existing_artifact"
    return "rebuilt_after_explicit_input" if not prefer_existing else "rebuilt_missing_artifact"


def _repo_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime"


def _include_global_runtime_candidates(runtime_dir: Path) -> bool:
    include_global = str(os.environ.get("QG_EA_REQUEST_READER_INCLUDE_GLOBAL_MT5", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    include_global = include_global or str(os.environ.get("QG_LIVE_PREFLIGHT_INCLUDE_GLOBAL_MT5", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        include_global = include_global or Path(runtime_dir).resolve() == _repo_runtime_dir().resolve()
    except Exception:
        pass
    return include_global


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for item in paths:
        path = item.expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _path_from_root(raw: str) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return Path(value).expanduser() / "MQL5" / "Files"


def _path_from_wine_prefix(raw: str) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return Path(value).expanduser() / "drive_c" / "Program Files" / "MetaTrader 5" / "MQL5" / "Files"


def _secondary_runtime_roots(runtime_dir: Path) -> list[Path]:
    roots: list[Path] = []
    for env_name in ("QG_HFM_CRYPTO_RUNTIME_DIR", "QG_MT5_SECONDARY_FILES_DIR"):
        value = str(os.environ.get(env_name, "") or "").strip()
        if value:
            roots.append(Path(value).expanduser())
    for path in (
        _path_from_root(os.environ.get("QG_MT5_SECONDARY_ROOT", "")),
        _path_from_wine_prefix(os.environ.get("QG_MT5_SECONDARY_WINE_PREFIX", "")),
    ):
        if path is not None:
            roots.append(path)
    include_default_live16 = False
    try:
        include_default_live16 = Path(runtime_dir).resolve() == _repo_runtime_dir().resolve()
    except Exception:
        include_default_live16 = False
    include_default_live16 = include_default_live16 or str(
        os.environ.get("QG_EA_REQUEST_READER_INCLUDE_GLOBAL_MT5", "") or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if include_default_live16:
        roots.append(
            Path.home()
            / "Library"
            / "Application Support"
            / "net.metaquotes.wine.metatrader5-live16"
            / "drive_c"
            / "Program Files"
            / "MetaTrader 5"
            / "MQL5"
            / "Files"
        )
    return _unique_paths(roots)


def _runtime_status_candidate_paths(runtime_dir: Path, ea_status_json: str = "") -> list[Path]:
    if ea_status_json:
        return _unique_paths([Path(ea_status_json)])
    runtime_dir = Path(runtime_dir)
    roots = [
        runtime_dir / "agent",
        runtime_dir,
        runtime_dir / "hfm_crypto",
        runtime_dir / "mac_import" / "mt5_files_snapshot",
        runtime_dir.parent / "Dashboard",
    ]
    if _include_global_runtime_candidates(runtime_dir) and callable(runtime_dir_candidates):
        try:
            roots.extend(Path(item) for item in runtime_dir_candidates())
        except Exception:
            pass
    roots.extend(_secondary_runtime_roots(runtime_dir))
    paths: list[Path] = []
    for root in roots:
        paths.append(root / "QuantGod_EARequestReaderReviewStatus.json")
        paths.append(root / "QuantGod_Dashboard.json")
    return _unique_paths(paths)


def _runtime_status_from_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if payload.get("schema") == EA_REQUEST_READER_RUNTIME_STATUS_SCHEMA:
        return payload, "status_file"
    embedded = _safe_dict(payload.get("eaRequestReaderReview"))
    if embedded:
        return embedded, "dashboard_embedded_eaRequestReaderReview"
    return {}, ""


def _read_runtime_status(runtime_dir: Path, ea_status_json: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    found: list[tuple[float, Path, dict[str, Any], str]] = []
    checked: list[str] = []
    parse_errors: list[dict[str, str]] = []
    source_kind = "operator_supplied" if ea_status_json else "autodiscovered"
    for candidate in _runtime_status_candidate_paths(runtime_dir, ea_status_json):
        checked.append(str(candidate))
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            root_payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            parse_errors.append({"path": str(candidate), "error": str(exc)})
            continue
        if not isinstance(root_payload, dict):
            parse_errors.append({"path": str(candidate), "error": "json_root_is_not_object"})
            continue
        payload, payload_kind = _runtime_status_from_payload(root_payload)
        if not payload:
            parse_errors.append({"path": str(candidate), "error": "ea_request_reader_status_not_found"})
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            mtime = 0.0
        found.append((mtime, candidate, payload, payload_kind))
    if not found:
        return {}, {
            "found": False,
            "path": "",
            "source": source_kind,
            "payloadKind": "",
            "checked": checked,
            "parseErrors": parse_errors,
        }
    _, path, payload, payload_kind = sorted(found, key=lambda item: item[0], reverse=True)[0]
    return payload, {
        "found": True,
        "path": str(path),
        "source": source_kind,
        "payloadKind": payload_kind,
        "checked": checked,
        "parseErrors": parse_errors,
    }


def _check_row(id_: str, label_zh: str, passed: bool, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {
        "id": id_,
        "labelZh": label_zh,
        "passed": bool(passed),
        "status": "PASS" if passed else "BLOCKED",
        "reasonZh": reason_zh,
    }
    if value not in (None, "", []):
        row["value"] = value
    return row


def _runtime_status_checks(payload: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        _check_row(
            "runtime_status_found",
            "运行时 EA request reader status 已导出",
            bool(source.get("found")),
            "需要新版 EA 导出 QuantGod_EARequestReaderReviewStatus.json，或在 QuantGod_Dashboard.json 中内嵌 eaRequestReaderReview。",
            source.get("path") or source.get("checked"),
        )
    ]
    if not source.get("found"):
        return checks
    checks.append(_check_row(
        "runtime_status_schema",
        "运行时 status schema 正确",
        payload.get("schema") == EA_REQUEST_READER_RUNTIME_STATUS_SCHEMA,
        "运行时 status 必须使用 EA request reader review status v1 schema。",
        payload.get("schema", ""),
    ))
    checks.append(_check_row(
        "runtime_effective_disabled",
        "运行时 reader 仍有效关闭",
        payload.get("effectiveEnabled") is False,
        "即便 operatorRequested 为 true，effectiveEnabled 也必须保持 false，直到单独执行代码评审完成。",
        payload.get("effectiveEnabled"),
    ))
    markers = _safe_dict(payload.get("markerChecks"))
    for key, marker in REQUIRED_RUNTIME_MARKERS:
        checks.append(_check_row(
            f"marker_{key}",
            f"运行时标记 {marker}",
            markers.get(key) is True,
            "EA 运行时 status 必须确认源码安全标记仍然存在。",
            markers.get(key),
        ))
    safety = _safe_dict(payload.get("safety"))
    checks.append(_check_row(
        "safety_reviewOnly",
        "运行时 status 仍为 review-only",
        safety.get("reviewOnly") is True,
        "EA request reader runtime status 必须声明 reviewOnly=true。",
        safety.get("reviewOnly"),
    ))
    for key in REQUIRED_RUNTIME_SAFETY_FALSE_KEYS:
        checks.append(_check_row(
            f"safety_{key}",
            f"运行时 safety.{key}=false",
            safety.get(key) is False,
            "EA runtime status 必须证明没有读取 request、没有写 receipt、没有调用 broker、没有打开下单权限。",
            safety.get(key),
        ))
    return checks


def _runtime_status_summary(payload: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source,
        "schema": payload.get("schema", ""),
        "status": payload.get("status", ""),
        "operatorRequested": payload.get("operatorRequested") if source.get("found") else None,
        "effectiveEnabled": payload.get("effectiveEnabled") if source.get("found") else None,
        "configuredMode": payload.get("configuredMode", ""),
        "requestDirectory": payload.get("requestDirectory", ""),
        "receiptDirectory": payload.get("receiptDirectory", ""),
    }


def _runtime_status_blockers(
    *,
    source: dict[str, Any],
    checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not source.get("found"):
        return [_blocker(
            "EA_REQUEST_READER_RUNTIME_STATUS_MISSING",
            "没有找到 EA request reader 运行时 status 导出。",
            source.get("checked"),
        )]
    failed_ids = [str(row.get("id") or "") for row in checks if not row.get("passed")]
    if "runtime_status_schema" in failed_ids:
        return [_blocker(
            "EA_REQUEST_READER_RUNTIME_STATUS_SCHEMA_INVALID",
            "EA request reader 运行时 status schema 不匹配。",
            source.get("path"),
        )]
    if "runtime_effective_disabled" in failed_ids:
        return [_blocker(
            "EA_REQUEST_READER_RUNTIME_STATUS_NOT_DISABLED",
            "EA request reader 运行时 status 没有证明 effectiveEnabled=false。",
            source.get("path"),
        )]
    if failed_ids:
        return [_blocker(
            "EA_REQUEST_READER_RUNTIME_STATUS_SAFETY_FAILED",
            "EA request reader 运行时 safety/marker 检查未全部通过。",
            failed_ids,
        )]
    return []


def _default_ea_source_path() -> Path:
    return Path(__file__).resolve().parents[2] / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"


def _source_summary(ea_source_path: str) -> tuple[dict[str, Any], str]:
    path = Path(ea_source_path).expanduser() if ea_source_path else _default_ea_source_path()
    if not path.exists() or not path.is_file():
        return {
            "path": str(path),
            "source": "operator_supplied" if ea_source_path else "repo_default",
            "exists": False,
            "readable": False,
            "sizeBytes": 0,
            "sha256": "",
        }, ""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        return {
            "path": str(path),
            "source": "operator_supplied" if ea_source_path else "repo_default",
            "exists": True,
            "readable": False,
            "sizeBytes": path.stat().st_size,
            "sha256": "",
            "error": str(exc),
        }, ""
    return {
        "path": str(path),
        "source": "operator_supplied" if ea_source_path else "repo_default",
        "exists": True,
        "readable": True,
        "sizeBytes": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }, text


def _marker_checks(source_text: str, source_exists: bool) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for row in REQUIRED_EA_MARKERS:
        present = bool(source_exists and row["marker"] in source_text)
        checks.append({
            "id": row["id"],
            "marker": row["marker"],
            "present": present,
            "status": "PASS" if present else "MISSING",
            "reasonZh": row["reasonZh"],
        })
    return checks


def _artifact_summary(payload: dict[str, Any], extra_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    keys = (
        "schema",
        "status",
        "statusZh",
        "generatedAtIso",
        "nextRequiredActionZh",
        *extra_keys,
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _reader_contract(
    *,
    order_contract: dict[str, Any],
    activation: dict[str, Any],
    receipt_review: dict[str, Any],
    marker_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    request_contract = _safe_dict(order_contract.get("requestContract"))
    receipt_results = _safe_list(receipt_review.get("reconciliationResults"))
    return {
        "contractMode": "EA_REQUEST_READER_IMPLEMENTATION_REVIEW_ONLY",
        "requestSchema": request_contract.get("inputSchema", "quantgod.mt5_reviewed_order_request.v1"),
        "receiptSchema": request_contract.get("receiptSchema", "quantgod.mt5_execution_receipt.v1"),
        "requestDirectory": request_contract.get("requestDirectory", "runtime/agent/mt5_order_requests"),
        "receiptDirectory": request_contract.get("receiptDirectory", "runtime/agent/mt5_order_receipts"),
        "requestFilePattern": "*.request.json",
        "receiptFilePattern": "*.receipt.json",
        "requiredMarkers": [row["marker"] for row in marker_checks],
        "reviewedRequestCount": int(receipt_review.get("plannedRequestCount") or 0),
        "reviewedReceiptCount": int(receipt_review.get("receiptCount") or 0),
        "validatedRequestIds": [
            str(row.get("requestId") or "")
            for row in receipt_results
            if isinstance(row, dict) and row.get("requestId")
        ],
        "operatorApprovalId": _safe_dict(activation.get("pilotEnvelope")).get("operatorApprovalId", ""),
        "requiredRuntimeFuses": [
            "request_reader_disabled_by_default",
            "schema_validation_before_any_side_effect",
            "request_id_idempotency",
            "kill_switch_inactive",
            "runtime_fresh",
            "spread_probe_ok",
            "symbol_mapping_ok",
            "receipt_written_for_every_request",
            "separate_order_send_code_review",
        ],
        "forbiddenInThisArtifact": [
            "MT5 Files request consumption",
            "receipt file writes",
            "preset mutation",
            "credential storage",
            "broker-side execution",
            "automatic live pilot activation",
        ],
    }


def _review_checklist(
    *,
    activation: dict[str, Any],
    order_contract: dict[str, Any],
    receipt_review: dict[str, Any],
    source: dict[str, Any],
    marker_checks: list[dict[str, Any]],
    runtime_status_ready: bool,
    runtime_status_source: dict[str, Any],
) -> list[dict[str, Any]]:
    markers_passed = bool(marker_checks and all(row.get("present") for row in marker_checks))
    checks = [
        {
            "id": "live_pilot_activation_ready",
            "labelZh": "live pilot 激活评审已到边界",
            "passed": bool(activation.get("readyForLivePilotActivationReview")),
            "status": "PASS" if activation.get("readyForLivePilotActivationReview") else "BLOCKED",
            "reasonZh": "需要 activation review 汇总总控、preflight、审批、validator 和 disabled harness。",
            "value": activation.get("status", ""),
        },
        {
            "id": "order_request_contract_ready",
            "labelZh": "MT5 request contract 可评审",
            "passed": bool(order_contract.get("readyForAdapterCodeReview")),
            "status": "PASS" if order_contract.get("readyForAdapterCodeReview") else "BLOCKED",
            "reasonZh": "EA request reader 必须绑定已通过的 request/receipt contract。",
            "value": order_contract.get("status", ""),
        },
        {
            "id": "receipt_reconciliation_ready",
            "labelZh": "receipt 对账规则可评审",
            "passed": bool(receipt_review.get("readyForReceiptReconciliationReview")),
            "status": "PASS" if receipt_review.get("readyForReceiptReconciliationReview") else "BLOCKED",
            "reasonZh": "EA request reader 上线前必须先有 planned request 与 review-only receipt 对账。",
            "value": receipt_review.get("status", ""),
        },
        {
            "id": "ea_source_readable",
            "labelZh": "EA 源码可读取",
            "passed": bool(source.get("exists") and source.get("readable")),
            "status": "PASS" if source.get("exists") and source.get("readable") else "BLOCKED",
            "reasonZh": "需要仓库或操作者提供的 QuantGod_MultiStrategy.mq5 源码用于审查。",
            "value": source.get("path", ""),
        },
        {
            "id": "ea_request_reader_markers_present",
            "labelZh": "EA request reader 安全标记齐全",
            "passed": markers_passed,
            "status": "PASS" if markers_passed else "BLOCKED",
            "reasonZh": "EA 源码需要显式标记默认关闭、schema 校验、幂等、kill switch、receipt writer 和单独下单评审。",
            "value": [row["marker"] for row in marker_checks if not row.get("present")],
        },
        {
            "id": "ea_runtime_status_disabled",
            "labelZh": "EA 运行时 request reader 仍默认关闭",
            "passed": bool(runtime_status_ready),
            "status": "PASS" if runtime_status_ready else "BLOCKED",
            "reasonZh": "需要新版 EA 或 Dashboard 导出 request reader runtime status，并证明它没有读取 request、没有写 receipt、没有下单权限。",
            "value": runtime_status_source.get("path") or runtime_status_source.get("checked"),
        },
        {
            "id": "review_only_no_side_effects",
            "labelZh": "本 artifact 无执行副作用",
            "passed": True,
            "status": "PASS",
            "reasonZh": "当前工具只读取源码和 review artifacts，不读取/消费 MT5 request，不写 receipt，不调用 broker。",
        },
    ]
    return checks


def _blockers_from_review(
    *,
    checklist: list[dict[str, Any]],
    marker_checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for row in checklist:
        if row.get("passed"):
            continue
        code = "EA_REQUEST_READER_CHECK_NOT_PASSED"
        if row.get("id") == "ea_request_reader_markers_present":
            code = "EA_REQUEST_READER_MARKERS_MISSING"
        elif row.get("id") == "ea_source_readable":
            code = "EA_SOURCE_NOT_READABLE"
        elif row.get("id") == "ea_runtime_status_disabled":
            code = "EA_REQUEST_READER_RUNTIME_STATUS_NOT_READY"
        blockers.append(_blocker(code, str(row.get("reasonZh") or "EA request reader review check 未通过。"), row.get("value") or row.get("id")))
    missing = [row for row in marker_checks if not row.get("present")]
    if missing:
        blockers.append(_blocker(
            "EA_REQUEST_READER_REQUIRED_MARKERS_MISSING",
            "EA 源码缺少 request reader 安全标记。",
            [row["marker"] for row in missing],
        ))
    return blockers


def _execution_mode_blockers(*payloads: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for payload in payloads:
        for row in _safe_list(payload.get("blockers")):
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "")
            if code not in {
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
                "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
                "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
            }:
                continue
            key = (code, str(row.get("reasonZh") or ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def build_ea_request_reader_review(
    runtime_dir: Path,
    *,
    ea_source_path: str = "",
    ea_status_json: str = "",
    receipt_json: str = "",
    request_json: str = "",
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    upstream_inputs_provided = bool(
        request_json
        or moss_backtest_json
        or hfm_simulation_profile_json
        or hfm_contract_spec_json
        or extra_bases_roots
    )
    receipt_inputs_provided = bool(receipt_json or upstream_inputs_provided)
    prefer_existing_activation = not upstream_inputs_provided
    prefer_existing_order_contract = not upstream_inputs_provided
    prefer_existing_receipt_review = not receipt_inputs_provided
    common = {
        "operator_approval_json": operator_approval_json,
        "write": bool(refresh_sources),
        "refresh_sources": refresh_sources,
        "moss_backtest_json": moss_backtest_json,
        "hfm_simulation_profile_json": hfm_simulation_profile_json,
        "hfm_contract_spec_json": hfm_contract_spec_json,
        "extra_bases_roots": extra_bases_roots or [],
    }
    activation = _read_existing_json(live_pilot_activation_review_path(runtime_dir)) if prefer_existing_activation else {}
    order_contract = _read_existing_json(order_request_contract_path(runtime_dir)) if prefer_existing_order_contract else {}
    receipt_review = _read_existing_json(receipt_reconciliation_review_path(runtime_dir)) if prefer_existing_receipt_review else {}
    activation_source = _dependency_source(activation, prefer_existing=prefer_existing_activation)
    order_contract_source = _dependency_source(order_contract, prefer_existing=prefer_existing_order_contract)
    receipt_review_source = _dependency_source(receipt_review, prefer_existing=prefer_existing_receipt_review)
    if not activation:
        activation = (
            build_live_pilot_activation_review(runtime_dir, request_json=request_json, **common)
            if refresh_sources or operator_approval_json or upstream_inputs_provided
            else read_live_pilot_activation_review(runtime_dir)
        )
    if not order_contract:
        order_contract = (
            build_mt5_order_request_contract(runtime_dir, **common)
            if refresh_sources or operator_approval_json or upstream_inputs_provided
            else read_mt5_order_request_contract(runtime_dir)
        )
    if not receipt_review:
        receipt_review = (
            build_receipt_reconciliation_review(
                runtime_dir,
                receipt_json=receipt_json,
                request_json=request_json,
                **common,
            )
            if refresh_sources or operator_approval_json or receipt_inputs_provided
            else read_receipt_reconciliation_review(runtime_dir)
        )
    source, source_text = _source_summary(ea_source_path)
    marker_checks = _marker_checks(source_text, bool(source.get("exists") and source.get("readable")))
    runtime_status, runtime_status_source = _read_runtime_status(runtime_dir, ea_status_json)
    runtime_status_safety_checks = _runtime_status_checks(runtime_status, runtime_status_source)
    runtime_status_found = bool(runtime_status_source.get("found"))
    runtime_status_schema_ok = runtime_status.get("schema") == EA_REQUEST_READER_RUNTIME_STATUS_SCHEMA
    runtime_status_disabled = runtime_status.get("effectiveEnabled") is False
    runtime_status_safety_passed = bool(runtime_status_safety_checks and all(row.get("passed") for row in runtime_status_safety_checks))
    runtime_status_ready = bool(
        runtime_status_found
        and runtime_status_schema_ok
        and runtime_status_disabled
        and runtime_status_safety_passed
    )
    checklist = _review_checklist(
        activation=activation,
        order_contract=order_contract,
        receipt_review=receipt_review,
        source=source,
        marker_checks=marker_checks,
        runtime_status_ready=runtime_status_ready,
        runtime_status_source=runtime_status_source,
    )
    review_ready = bool(checklist and all(row.get("passed") for row in checklist))
    blockers = _blockers_from_review(checklist=checklist, marker_checks=marker_checks)
    blockers.extend(_runtime_status_blockers(source=runtime_status_source, checks=runtime_status_safety_checks))
    missing_marker_count = sum(1 for row in marker_checks if not row.get("present"))
    execution_mode_only_blocked = bool(
        activation.get("executionModeOnlyBlocked")
        or order_contract.get("runtimePreflightExecutionModeOnlyBlocked")
        or receipt_review.get("executionModeOnlyBlocked")
    )
    data_plane_reader_ready = bool(
        activation.get("dataPlaneActivationReady")
        and order_contract.get("runtimePreflightDataPlaneReadyForReview")
        and (
            receipt_review.get("dataPlaneReconciliationReady")
            or receipt_review.get("readyForReceiptReconciliationReview")
        )
        and source.get("exists")
        and source.get("readable")
        and missing_marker_count == 0
        and runtime_status_ready
    )
    if data_plane_reader_ready and execution_mode_only_blocked:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "EA request reader 数据面、源码标记、运行时禁用状态和 receipt 对账已具备；仅等待执行模式闸门。",
                activation.get("status") or order_contract.get("status") or receipt_review.get("status"),
            )
        ]
        blockers.extend(_execution_mode_blockers(activation, order_contract, receipt_review))
    if review_ready:
        next_required_action_zh = "进入单独 EA request reader 实现 PR/代码评审；本 artifact 仍不会读取 request 文件或调用 broker。"
    elif data_plane_reader_ready and execution_mode_only_blocked:
        next_required_action_zh = "EA request reader 数据面已具备；仅剩执行模式闸门，当前仍不会读取 request、写 receipt 或调用 broker。"
    elif missing_marker_count:
        next_required_action_zh = "先在 EA 源码中加入 request reader 安全标记与实现评审入口，再补齐前置 activation/receipt/order-contract 审查。"
    elif not runtime_status_ready:
        next_required_action_zh = "EA 源码安全标记已存在；把新版 EA 部署/编译/加载到 MT5，并同步 dashboard 或 QuantGod_EARequestReaderReviewStatus.json。"
    else:
        next_required_action_zh = "EA request reader 安全标记已存在；继续补齐 activation、order contract、receipt reconciliation 等前置审查。"
    payload = {
        "ok": True,
        "schema": EA_REQUEST_READER_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_EA_REQUEST_READER_IMPLEMENTATION_REVIEW"
            if review_ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_reader_ready and execution_mode_only_blocked
            else "WAITING_EA_REQUEST_READER_INPUTS"
        ),
        "statusZh": (
            "可进入 EA request reader 实现评审"
            if review_ready
            else "EA request reader 数据面已通过，等待执行模式闸门"
            if data_plane_reader_ready and execution_mode_only_blocked
            else "等待 EA request reader 评审输入"
        ),
        "reviewMode": "EA_REQUEST_READER_REVIEW_ONLY_NO_SIDE_EFFECTS",
        "readyForEaRequestReaderImplementationReview": review_ready,
        "dataPlaneEaRequestReaderReady": data_plane_reader_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "livePilotActivationAllowed": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "dependencyRefreshMode": {
            "refreshSources": bool(refresh_sources),
            "upstreamInputsProvided": upstream_inputs_provided,
            "receiptInputsProvided": receipt_inputs_provided,
            "activationReview": activation_source,
            "orderRequestContract": order_contract_source,
            "receiptReconciliationReview": receipt_review_source,
        },
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "brokerExecutionAllowed": False,
        "autoDisableMutationAllowed": False,
        "eaRequestReaderAllowed": False,
        "eaRequestReaderEnabled": False,
        "eaRequestFilesRead": False,
        "eaRequestFilesConsumed": False,
        "eaOrderSendAllowed": False,
        "eaSource": source,
        "markerChecks": marker_checks,
        "missingMarkerCount": missing_marker_count,
        "runtimeStatusSource": runtime_status_source,
        "runtimeStatusFound": runtime_status_found,
        "runtimeStatusSchemaOk": runtime_status_schema_ok,
        "runtimeStatusDisabled": runtime_status_disabled,
        "runtimeStatusSafetyPassed": runtime_status_safety_passed,
        "readyForRuntimeEaRequestReaderStatusReview": runtime_status_ready,
        "runtimeStatusReview": _runtime_status_summary(runtime_status, runtime_status_source),
        "runtimeStatusSafetyChecks": runtime_status_safety_checks,
        "reviewChecklist": checklist,
        "readerImplementationContract": _reader_contract(
            order_contract=order_contract,
            activation=activation,
            receipt_review=receipt_review,
            marker_checks=marker_checks,
        ),
        "artifacts": {
            "livePilotActivationReview": _artifact_summary(activation, ("readyForLivePilotActivationReview",)),
            "orderRequestContract": _artifact_summary(order_contract, ("readyForAdapterCodeReview", "reviewPacketHash", "runtimePreflightHash")),
            "receiptReconciliationReview": _artifact_summary(receipt_review, ("readyForReceiptReconciliationReview", "reconciliationPassed", "plannedRequestCount", "receiptCount")),
        },
        "blockers": blockers[:32],
        "nextRequiredActionZh": next_required_action_zh,
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = ea_request_reader_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_ea_request_reader_review(runtime_dir: Path) -> dict[str, Any]:
    path = ea_request_reader_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_ea_request_reader_review(Path(runtime_dir), write=False)
