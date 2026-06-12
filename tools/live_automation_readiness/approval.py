from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .review_packet import build_live_execution_review_packet, read_live_execution_review_packet
from .schema import (
    APPROVAL_EVIDENCE_REVIEW_SCHEMA_VERSION,
    APPROVAL_DRAFT_SCHEMA_VERSION,
    DRY_RUN_PLAN_SCHEMA_VERSION,
    SAFETY,
    approval_evidence_review_path,
    approval_draft_path,
    assert_no_execution_flags,
    dry_run_plan_path,
    utc_now_iso,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _stable_digest_payload(payload: Any, *, _depth: int = 0, _seen: set[int] | None = None) -> Any:
    volatile_keys = {"generatedAt", "generatedAtIso"}
    if _seen is None:
        _seen = set()
    if _depth > 8:
        return {"__truncated__": "max_depth", "type": type(payload).__name__}
    if isinstance(payload, dict):
        ident = id(payload)
        if ident in _seen:
            return {"__truncated__": "cycle", "type": "dict"}
        _seen.add(ident)
        keys = sorted(key for key in payload.keys() if key not in volatile_keys)
        head = keys[:80]
        rows = {
            key: _stable_digest_payload(payload[key], _depth=_depth + 1, _seen=_seen)
            for key in head
        }
        if len(keys) > len(head):
            rows["__truncatedKeyCount__"] = len(keys) - len(head)
            rows["__totalKeyCount__"] = len(keys)
        _seen.remove(ident)
        return rows
    if isinstance(payload, list):
        ident = id(payload)
        if ident in _seen:
            return {"__truncated__": "cycle", "type": "list"}
        _seen.add(ident)
        head = payload[:80]
        rows = [_stable_digest_payload(item, _depth=_depth + 1, _seen=_seen) for item in head]
        if len(payload) > len(head):
            rows.append({"__truncatedItemCount__": len(payload) - len(head), "__totalItemCount__": len(payload)})
        _seen.remove(ident)
        return rows
    if isinstance(payload, str) and len(payload) > 2000:
        return {
            "__truncated__": "long_string",
            "length": len(payload),
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }
    return payload


def _stable_digest(payload: Any) -> str:
    raw = json.dumps(_stable_digest_payload(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _approval_packet_hash(packet: dict[str, Any]) -> str:
    """Bind operator approval to the reviewable contract, not volatile runtime ages."""
    return _stable_digest({
        "schema": packet.get("schema", ""),
        "contracts": _candidate_contracts(packet),
        "forbiddenOutputs": _safe_list(packet.get("forbiddenOutputs")),
    })


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _read_json_with_error(path: Path) -> tuple[dict[str, Any], str, str]:
    if not path.exists() or not path.is_file():
        return {}, "MISSING", "operator approval JSON not found"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {}, "UNREADABLE", str(exc)
    if not isinstance(payload, dict):
        return {}, "UNREADABLE", "operator approval JSON must be an object"
    return payload, "JSON", ""


def _lane_contracts(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contracts = _safe_dict(packet.get("contracts"))
    return {
        key: value
        for key, value in contracts.items()
        if isinstance(value, dict)
    }


def _candidate_contracts(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: value
        for key, value in _lane_contracts(packet).items()
        if bool(value.get("reviewCandidate"))
    }


def _approval_requirements(packet: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = _candidate_contracts(packet)
    requirements = [
        {
            "id": "review_packet_hash_ack",
            "labelZh": "确认审查包 hash",
            "required": True,
            "reasonZh": "最终审批必须绑定当前审查包，避免审批和执行计划错配。",
        },
        {
            "id": "risk_limits_ack",
            "labelZh": "确认每条车道风险限制",
            "required": True,
            "reasonZh": "需要逐项确认 max daily loss、max notional、spread/slippage 和连续亏损限制。",
        },
        {
            "id": "kill_switch_ack",
            "labelZh": "确认 kill switch 可用",
            "required": True,
            "reasonZh": "任何实盘 lane 都必须能被本地 kill switch 立即阻断。",
        },
        {
            "id": "credentials_external_ack",
            "labelZh": "确认凭据仅外部引用",
            "required": True,
            "reasonZh": "系统不得存储 MT5 密码、钱包私钥、API secret 或授权 token。",
        },
        {
            "id": "dry_run_first_ack",
            "labelZh": "确认先跑 dry-run plan",
            "required": True,
            "reasonZh": "即使候选通过，也必须先观察 dry-run 计划和执行反馈，不直接开真钱。",
        },
    ]
    if "hfmCryptoCfd" in candidates:
        requirements.append({
            "id": "hfm_contract_spec_ack",
            "labelZh": "确认 HFM crypto 合约规格",
            "required": True,
            "reasonZh": "必须确认 broker symbol、contract size、tick value、lot step、spread、swap/funding 和周末跳空规则。",
        })
    return requirements


def _approval_bool(payload: dict[str, Any], key: str, requirement_id: str = "") -> bool:
    if bool(payload.get(key)):
        return True
    requirement_acks = _safe_dict(payload.get("requirementAcks"))
    if requirement_id and bool(requirement_acks.get(requirement_id)):
        return True
    acknowledged = {str(item) for item in _safe_list(payload.get("acknowledgedRequirementIds"))}
    return bool(requirement_id and requirement_id in acknowledged)


def _approval_blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


def _operator_approval_id(payload: dict[str, Any], packet_hash: str) -> str:
    for key in ("operatorApprovalId", "approvalId", "operatorId"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    if packet_hash:
        return f"approval-{packet_hash[:16]}"
    return ""


def _authorization_boundary(*, approval_path: Path | None, accepted: bool) -> dict[str, Any]:
    return {
        "schema": "quantgod.authorization_boundary.v1",
        "chatAuthorizationAcknowledged": True,
        "chatAuthorizationSource": "current_codex_thread_user_messages",
        "chatAuthorizationCanUnlockLiveExecution": False,
        "operatorApprovalJsonProvided": bool(approval_path),
        "operatorApprovalEvidenceAccepted": bool(accepted),
        "operatorApprovalJsonCanUnlockLiveExecution": False,
        "releaseTokensStillRequired": True,
        "executionModeProofStillRequired": True,
        "canReleaseExecutionNow": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
        "reasonZh": (
            "用户在对话中表达了自动推进和实盘意图，但聊天授权不能等价为 execution release token；"
            "机器可读审批证据即使通过，也只能进入下一层审查，不能单独打开真实下单。"
        ),
    }


def build_live_operator_approval_draft(
    runtime_dir: Path,
    *,
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    packet = (
        build_live_execution_review_packet(
            runtime_dir,
            write=write,
            refresh_sources=refresh_sources,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if refresh_sources or moss_backtest_json or hfm_simulation_profile_json or hfm_contract_spec_json or extra_bases_roots
        else read_live_execution_review_packet(runtime_dir)
    )
    packet_hash = _approval_packet_hash(packet)
    candidates = _candidate_contracts(packet)
    payload = {
        "ok": True,
        "schema": APPROVAL_DRAFT_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "WAITING_OPERATOR_APPROVAL" if candidates else "WAITING_REVIEW_CANDIDATE",
        "statusZh": "等待操作者最终确认" if candidates else "等待可审批候选",
        "reviewPacketHash": packet_hash,
        "reviewCandidateLanes": sorted(candidates.keys()),
        "operatorApprovalProvided": False,
        "operatorApprovalId": "",
        "approvalCanUnlockLiveExecution": False,
        "autoPromotionToLiveAllowed": False,
        "canPromoteToLiveNow": False,
        "orderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "requiredApprovalFields": [
            "operatorId",
            "approvedAtIso",
            "reviewPacketHash",
            "approvedLanes",
            "maxDailyLossAck",
            "killSwitchAck",
            "credentialsExternalAck",
            "dryRunFirstAck",
            "finalHumanApprovalText",
        ],
        "approvalRequirements": _approval_requirements(packet),
        "manualApprovalTemplate": {
            "operatorId": "",
            "approvedAtIso": "",
            "reviewPacketHash": packet_hash,
            "approvedLanes": sorted(candidates.keys()),
            "maxDailyLossAck": False,
            "killSwitchAck": False,
            "credentialsExternalAck": False,
            "dryRunFirstAck": False,
            "finalHumanApprovalText": "",
        },
        "nextRequiredActionZh": (
            "由操作者逐项审查风险限制、kill switch、凭据模式和 dry-run plan 后，另行提交人工审批证据。"
            if candidates
            else "先等 readiness/review packet 出现可审批候选。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = approval_draft_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_operator_approval_draft(runtime_dir: Path) -> dict[str, Any]:
    path = approval_draft_path(Path(runtime_dir))
    payload = _read_json(path)
    if payload:
        return payload
    return build_live_operator_approval_draft(Path(runtime_dir), write=False)


def build_live_operator_approval_evidence_review(
    runtime_dir: Path,
    *,
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    draft = build_live_operator_approval_draft(
        runtime_dir,
        write=bool(write and refresh_sources),
        refresh_sources=refresh_sources,
        moss_backtest_json=moss_backtest_json,
        hfm_simulation_profile_json=hfm_simulation_profile_json,
        hfm_contract_spec_json=hfm_contract_spec_json,
        extra_bases_roots=extra_bases_roots or [],
    )
    packet_hash = str(draft.get("reviewPacketHash") or "")
    candidate_lanes = {str(item) for item in _safe_list(draft.get("reviewCandidateLanes"))}
    approval_path = Path(str(operator_approval_json or "")).expanduser() if operator_approval_json else None
    approval_payload: dict[str, Any] = {}
    source_format = "NO_PATH"
    source_error = ""
    if approval_path:
        approval_payload, source_format, source_error = _read_json_with_error(approval_path)

    blockers: list[dict[str, Any]] = []
    if not approval_path:
        blockers.append(_approval_blocker("OPERATOR_APPROVAL_JSON_MISSING", "尚未提供人工审批 JSON 文件。"))
    elif source_format != "JSON":
        blockers.append(_approval_blocker("OPERATOR_APPROVAL_JSON_UNREADABLE", "人工审批 JSON 无法读取或解析。", source_error))
    if not candidate_lanes:
        blockers.append(_approval_blocker("NO_REVIEW_CANDIDATE_LANES", "当前 review packet 没有可审批候选 lane。"))

    provided_hash = str(approval_payload.get("reviewPacketHash") or "")
    if approval_payload and provided_hash != packet_hash:
        blockers.append(_approval_blocker(
            "REVIEW_PACKET_HASH_MISMATCH",
            "人工审批绑定的 reviewPacketHash 与当前审查包不一致。",
            {"expected": packet_hash, "actual": provided_hash},
        ))
    approved_lanes = {str(item) for item in _safe_list(approval_payload.get("approvedLanes"))}
    if approval_payload and not approved_lanes:
        blockers.append(_approval_blocker("APPROVED_LANES_EMPTY", "人工审批没有列出 approvedLanes。"))
    invalid_lanes = sorted(approved_lanes - candidate_lanes)
    if invalid_lanes:
        blockers.append(_approval_blocker("APPROVED_LANES_NOT_CANDIDATES", "人工审批包含当前审查包之外的 lane。", invalid_lanes))

    required_fields = [
        "operatorId",
        "approvedAtIso",
        "reviewPacketHash",
        "approvedLanes",
        "maxDailyLossAck",
        "killSwitchAck",
        "credentialsExternalAck",
        "dryRunFirstAck",
        "finalHumanApprovalText",
    ]
    for field in required_fields:
        if approval_payload and approval_payload.get(field) in (None, "", [], {}):
            blockers.append(_approval_blocker("OPERATOR_APPROVAL_FIELD_MISSING", f"人工审批缺少必填字段 {field}。", field))

    requirement_results = []
    for requirement in _safe_list(draft.get("approvalRequirements")):
        if not isinstance(requirement, dict):
            continue
        requirement_id = str(requirement.get("id") or "")
        if not requirement_id:
            continue
        field = {
            "review_packet_hash_ack": "reviewPacketHash",
            "risk_limits_ack": "maxDailyLossAck",
            "kill_switch_ack": "killSwitchAck",
            "credentials_external_ack": "credentialsExternalAck",
            "dry_run_first_ack": "dryRunFirstAck",
            "hfm_contract_spec_ack": "hfmContractSpecAck",
        }.get(requirement_id, requirement_id)
        passed = bool(
            approval_payload
            and (
                (requirement_id == "review_packet_hash_ack" and provided_hash == packet_hash)
                or _approval_bool(approval_payload, field, requirement_id)
            )
        )
        requirement_results.append({
            "id": requirement_id,
            "labelZh": requirement.get("labelZh") or requirement_id,
            "passed": passed,
            "status": "PASS" if passed else "BLOCKED",
        })
        if approval_payload and requirement.get("required", True) and not passed:
            blockers.append(_approval_blocker("OPERATOR_APPROVAL_REQUIREMENT_NOT_ACKED", "人工审批未确认必需项。", requirement_id))

    text = str(approval_payload.get("finalHumanApprovalText") or "").strip()
    if approval_payload and len(text) < 10:
        blockers.append(_approval_blocker("FINAL_APPROVAL_TEXT_TOO_SHORT", "最终人工审批文本过短，不能作为可审计确认。"))

    accepted = bool(approval_payload and not blockers)
    operator_approval_id = _operator_approval_id(approval_payload, packet_hash) if approval_payload else ""
    payload = {
        "ok": True,
        "schema": APPROVAL_EVIDENCE_REVIEW_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED" if accepted else "WAITING_OPERATOR_APPROVAL_EVIDENCE",
        "statusZh": "人工审批证据已验收，但真实执行仍关闭" if accepted else "等待有效人工审批证据",
        "operatorApprovalJsonPath": str(approval_path) if approval_path else "",
        "sourceFormat": source_format,
        "reviewPacketHash": packet_hash,
        "providedReviewPacketHash": provided_hash,
        "operatorApprovalId": operator_approval_id,
        "operatorId": str(approval_payload.get("operatorId") or ""),
        "approvedAtIso": str(approval_payload.get("approvedAtIso") or ""),
        "approvalBoundToReviewPacket": bool(accepted and provided_hash == packet_hash),
        "reviewCandidateLanes": sorted(candidate_lanes),
        "approvedLanes": sorted(approved_lanes),
        "requirementResults": requirement_results,
        "authorizationBoundary": _authorization_boundary(approval_path=approval_path, accepted=accepted),
        "operatorApprovalProvided": accepted,
        "approvalCanUnlockLiveExecution": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "orderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "审批证据可审计；下一步仍必须单独实现并评审真实 MT5 execution lane，当前不会写订单。"
            if accepted
            else "按 approval draft 填写本地 JSON，并确保 reviewPacketHash 与当前审查包一致。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = approval_evidence_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_operator_approval_evidence_review(runtime_dir: Path) -> dict[str, Any]:
    path = approval_evidence_review_path(Path(runtime_dir))
    payload = _read_json(path)
    if payload:
        if not isinstance(payload.get("authorizationBoundary"), dict):
            approval_path_text = str(payload.get("operatorApprovalJsonPath") or "").strip()
            approval_path = Path(approval_path_text).expanduser() if approval_path_text else None
            payload["authorizationBoundary"] = _authorization_boundary(
                approval_path=approval_path,
                accepted=bool(payload.get("operatorApprovalProvided")),
            )
        assert_no_execution_flags(payload)
        return payload
    return build_live_operator_approval_evidence_review(Path(runtime_dir), write=False)


def _dry_run_intent_for_contract(key: str, contract: dict[str, Any], packet_hash: str) -> dict[str, Any]:
    spec = _safe_dict(contract.get("dryRunOrderIntentSpec"))
    example = _safe_dict(spec.get("example"))
    risk_limits = _safe_dict(contract.get("riskLimits"))
    intent_key = _stable_digest({"key": key, "example": example, "packetHash": packet_hash})[:20]
    return {
        "intentId": f"qg-dry-live-{intent_key}",
        "status": "BLOCKED_PENDING_OPERATOR_APPROVAL",
        "lane": contract.get("lane") or key,
        "dryRunOnly": True,
        "writesMt5OrderRequest": False,
        "mt5PendingOrderIntentsWritten": False,
        "orderSendAllowed": False,
        "brokerExecutionAllowed": False,
        "canonicalSymbol": example.get("canonicalSymbol", ""),
        "brokerSymbol": example.get("brokerSymbol", ""),
        "side": example.get("side", ""),
        "orderType": example.get("orderType", ""),
        "volumeLots": example.get("volumeLots", 0.0),
        "riskLimits": risk_limits,
        "blockers": [
            *_safe_list(contract.get("blockers")),
            {"code": "OPERATOR_APPROVAL_MISSING", "reasonZh": "缺少最终人工审批证据。"},
            {"code": "LIVE_EXECUTION_LANE_DISABLED", "reasonZh": "当前没有启用真实 broker 执行 lane。"},
        ],
    }


def build_dry_run_live_execution_plan(
    runtime_dir: Path,
    *,
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    packet = (
        build_live_execution_review_packet(
            runtime_dir,
            write=write,
            refresh_sources=refresh_sources,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if refresh_sources or moss_backtest_json or hfm_simulation_profile_json or hfm_contract_spec_json or extra_bases_roots
        else read_live_execution_review_packet(runtime_dir)
    )
    approval = build_live_operator_approval_draft(
        runtime_dir,
        write=write,
        refresh_sources=refresh_sources,
        moss_backtest_json=moss_backtest_json,
        hfm_simulation_profile_json=hfm_simulation_profile_json,
        hfm_contract_spec_json=hfm_contract_spec_json,
        extra_bases_roots=extra_bases_roots or [],
    )
    packet_hash = _safe_dict(approval).get("reviewPacketHash") or _approval_packet_hash(packet)
    candidates = _candidate_contracts(packet)
    intents = [
        _dry_run_intent_for_contract(key, contract, str(packet_hash))
        for key, contract in candidates.items()
    ]
    payload = {
        "ok": True,
        "schema": DRY_RUN_PLAN_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "READY_FOR_DRY_RUN_REVIEW" if intents else "WAITING_REVIEW_CANDIDATE",
        "statusZh": "等待 dry-run 计划复核" if intents else "等待可生成计划的候选",
        "reviewPacketHash": packet_hash,
        "operatorApprovalProvided": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "mt5PendingOrderIntentsWritten": False,
        "writesMt5OrderRequest": False,
        "dryRunIntents": intents,
        "summary": {
            "candidateLanes": sorted(candidates.keys()),
            "intentCount": len(intents),
            "allIntentsBlocked": True,
            "blockedReasonZh": "缺少 operator approval，且真实执行 lane 未启用。",
        },
        "nextRequiredActionZh": (
            "复核 dry-run intents，确认风险字段、symbol、volume 和保护条件，再进入单独执行 lane 评审。"
            if intents
            else "先等 review packet 出现候选，当前没有可生成的 dry-run live intent。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = dry_run_plan_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_dry_run_live_execution_plan(runtime_dir: Path) -> dict[str, Any]:
    path = dry_run_plan_path(Path(runtime_dir))
    payload = _read_json(path)
    if payload:
        return payload
    return build_dry_run_live_execution_plan(Path(runtime_dir), write=False)
