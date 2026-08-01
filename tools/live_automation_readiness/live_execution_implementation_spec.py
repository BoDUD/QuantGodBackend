from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .live_execution_cutover import build_live_execution_cutover_review, read_live_execution_cutover_review
from .schema import (
    LIVE_EXECUTION_IMPLEMENTATION_SPEC_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    broker_order_send_review_path,
    ea_request_consumption_review_path,
    live_execution_adapter_write_review_path,
    live_execution_implementation_spec_path,
    live_pilot_activation_review_path,
    receipt_reconciliation_review_path,
    utc_now_iso,
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


def _review_step(
    step_id: str,
    label_zh: str,
    target_files: list[str],
    implementation_contract: list[str],
    required_tests: list[str],
    *,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "stepId": step_id,
        "labelZh": label_zh,
        "status": "REQUIRES_SEPARATE_PR_REVIEW",
        "dependsOn": depends_on or [],
        "targetFiles": target_files,
        "implementationContract": implementation_contract,
        "requiredTests": required_tests,
        "forbiddenUntilReviewed": [
            "broker order send",
            "MT5 request file writes from this artifact",
            "receipt file writes from this artifact",
            "Telegram/webhook command execution",
            "credential storage",
            "live preset mutation",
        ],
    }


def _implementation_steps(cutover: dict[str, Any]) -> list[dict[str, Any]]:
    handoff = _safe_dict(cutover.get("implementationHandoff"))
    request_dir = handoff.get("requestDirectory") or "runtime/agent/mt5_order_requests"
    receipt_dir = handoff.get("receiptDirectory") or "runtime/agent/mt5_order_receipts"
    review_hash = handoff.get("reviewPacketHash") or ""
    preflight_hash = handoff.get("runtimePreflightHash") or ""
    return [
        _review_step(
            "live_execution_adapter_write_path",
            "Python adapter 写入 MT5 request 的受控路径",
            [
                "tools/live_automation_readiness/live_execution_adapter.py",
                "tools/live_automation_readiness/live_execution_request_writer.py",
                "tests/test_live_execution_adapter.py",
            ],
            [
                "只接受 QuantGod_MT5OrderRequestContract.json 已批准字段。",
                f"requestDirectory 必须固定为 {request_dir}，并使用 .tmp 原子写入后 rename。",
                "requestId/idempotencyKey 必须可重复执行且不会生成重复有效 request。",
                "必须绑定当前 reviewPacketHash 与 runtimePreflightHash。",
                "默认模式必须是 DISABLED_REVIEW_ONLY，除非单独审查开启。",
            ],
            [
                "schema validation rejects missing fuses",
                "idempotency rejects duplicate requestId",
                "atomic temp-file write can be reviewed without broker calls",
                "all execution flags remain false in review mode",
            ],
        ),
        _review_step(
            "ea_request_reader_consumption_path",
            "MT5 EA request reader 消费路径",
            [
                "MQL5/Experts/QuantGod_MultiStrategy.mq5",
            ],
            [
                "EA reader 必须默认关闭，且运行时 status 继续导出 effectiveEnabled=false 直到执行 PR 合并。",
                "执行骨架必须与 review harness 分离，并导出 eaRequestReaderExecution 禁用态状态。",
                "禁用态 status 必须暴露 required fields、true fuses、allowed values 和 rejection receipt matrix。",
                f"requestDirectory 必须与 adapter 一致：{request_dir}。",
                f"receiptDirectory 必须与 adapter 一致：{receipt_dir}。",
                "读取 request 前必须校验 schema、requestId、reviewPacketHash、runtimePreflightHash、kill switch、spread、symbol mapping。",
                "任一校验失败只允许写拒绝 receipt，不能触发 order send。",
            ],
            [
                "EA safety marker guard",
                "runtime status export guard",
                "invalid request produces rejected receipt",
                "request consumption remains disabled before final execution review",
            ],
            depends_on=["live_execution_adapter_write_path"],
        ),
        _review_step(
            "broker_order_send_path",
            "Broker order send 最小封装路径",
            [
                "MQL5/Experts/QuantGod_MultiStrategy.mq5",
                "tests/test_live_execution_order_send_contract.py",
            ],
            [
                "必须只从已验收 request reader 路径进入，不允许 Telegram/webhook 直接触发。",
                "禁用态 wrapper 必须导出 brokerOrderSendWrapper status，并保持 brokerCallsMade=false。",
                "必须校验账户、server、symbol、volume step、max lot、spread、kill switch、daily loss、position cap。",
                "必须把 requestId、reviewPacketHash、runtimePreflightHash、ticket、retcode、fill price 写入 receipt。",
                "失败必须可对账、可自动暂停，不能静默重试放大风险。",
                f"当前 spec 绑定 reviewPacketHash={review_hash} runtimePreflightHash={preflight_hash}。",
            ],
            [
                "blocked when kill switch active",
                "blocked when spread exceeds contract spec",
                "blocked when account/server mismatch",
                "receipt contains retcode and safety snapshot",
            ],
            depends_on=["ea_request_reader_consumption_path"],
        ),
        _review_step(
            "receipt_writer_and_reconciliation_path",
            "Receipt 写入与对账路径",
            [
                "tools/live_automation_readiness/receipt_reconciliation.py",
                "MQL5/Experts/QuantGod_MultiStrategy.mq5",
            ],
            [
                f"receiptDirectory 必须固定为 {receipt_dir}，并使用原子写入。",
                "禁用态 receipt skeleton 必须导出 receiptWriterReconciliation status，并保持 receiptFilesWritten=false。",
                "每个 request 必须最终对应 accepted/rejected/duplicate/expired receipt。",
                "出现孤儿 receipt、缺 receipt、ticket 出现在 review-only 阶段时必须阻断后续切换。",
                "对账摘要必须进入 dashboard/operator artifact。",
            ],
            [
                "missing receipt blocks cutover",
                "orphan receipt blocks cutover",
                "duplicate request produces duplicate receipt",
                "review-only receipt with ticket is rejected",
            ],
            depends_on=["broker_order_send_path"],
        ),
        _review_step(
            "rollback_and_auto_disable_path",
            "Rollback 与自动暂停路径",
            [
                "tools/live_automation_readiness/live_execution_rollback.py",
                "Dashboard/live_automation_readiness_api_routes.js",
            ],
            [
                "自动暂停只允许写本地审查状态，不能直接修改 live preset。",
                "触发条件至少包括 receipt 缺失、retcode 异常、滑点超限、symbol mismatch、daily loss、EA status stale。",
                "恢复必须要求人工审批证据和新的 runtime preflight hash。",
                "所有状态变更必须有审计 JSON 和 dashboard 显示。",
            ],
            [
                "auto-disable trigger matrix",
                "manual re-arm requires approval evidence",
                "stale EA status blocks re-arm",
                "no live preset mutation from dashboard route",
            ],
            depends_on=["receipt_writer_and_reconciliation_path"],
        ),
    ]


def _acceptance_matrix(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in steps:
        rows.append({
            "stepId": step["stepId"],
            "requiredBeforeLive": True,
            "disabledFirstImplementationWorkReady": True,
            "nextCodeWorkAllowedInReviewOnly": True,
            "reviewEvidenceRequired": [
                "code diff reviewed",
                "focused tests passed",
                "node safety guard passed",
                "truthy execution flag scan passed",
                "operator runbook updated",
            ],
            "status": "PENDING_IMPLEMENTATION_PR",
            "statusZh": "可开始 disabled-first 拆分实现；实盘执行仍禁止",
        })
    return rows


def _execution_safety_traceability_matrix(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    step_by_id = {
        str(row.get("stepId") or ""): row
        for row in steps
        if isinstance(row, dict)
    }
    definitions = [
        {
            "stepId": "broker_order_send_path",
            "gateId": "broker_send_wrapper",
            "labelZh": "OrderSend 最小封装只能从已验收 EA request reader 进入",
            "requiredArtifacts": [
                "QuantGod_LiveExecutionImplementationSpec.json",
                "QuantGod_BrokerOrderSendReview.json",
                "QuantGod_LiveRuntimePreflightProbe.json",
            ],
            "mustProve": [
                "account/server/symbol bound",
                "kill switch/spread/daily loss/position cap checked",
                "receipt contains retcode/ticket after future execution",
            ],
            "blockingIfMissing": "BROKER_ORDER_SEND_PATH_NOT_REVIEWED",
        },
        {
            "stepId": "receipt_writer_and_reconciliation_path",
            "gateId": "receipt_reconciliation",
            "labelZh": "每个 request 必须有 accepted/rejected/duplicate/expired receipt 并可对账",
            "requiredArtifacts": [
                "QuantGod_ReceiptReconciliationReview.json",
                "QuantGod_EARequestConsumptionReview.json",
                "QuantGod_BrokerOrderSendReview.json",
            ],
            "mustProve": [
                "missing receipt blocks cutover",
                "orphan receipt blocks cutover",
                "review-only receipt with ticket is rejected",
            ],
            "blockingIfMissing": "RECEIPT_RECONCILIATION_PATH_NOT_REVIEWED",
        },
        {
            "stepId": "rollback_and_auto_disable_path",
            "gateId": "rollback_auto_disable",
            "labelZh": "异常 receipt、滑点、retcode、stale runtime 必须触发暂停/回滚审查",
            "requiredArtifacts": [
                "QuantGod_LiveExecutionImplementationSpec.json",
                "QuantGod_ReceiptReconciliationReview.json",
                "operator runbook",
            ],
            "mustProve": [
                "auto-disable trigger matrix reviewed",
                "manual re-arm requires approval evidence",
                "dashboard route cannot mutate live preset",
            ],
            "blockingIfMissing": "ROLLBACK_AUTO_DISABLE_PATH_NOT_REVIEWED",
        },
    ]
    rows: list[dict[str, Any]] = []
    for definition in definitions:
        step = _safe_dict(step_by_id.get(str(definition["stepId"])))
        rows.append({
            **definition,
            "declaredInImplementationSteps": bool(step),
            "stepStatus": step.get("status", "MISSING"),
            "dependsOn": _safe_list(step.get("dependsOn")),
            "targetFiles": _safe_list(step.get("targetFiles")),
            "requiredTests": _safe_list(step.get("requiredTests")),
            "requiredBeforeLive": True,
            "reviewOnlyStatus": "PENDING_SEPARATE_PR_REVIEW" if step else "MISSING_FROM_IMPLEMENTATION_SPEC",
            "currentArtifactAllowedToApply": False,
            "canPromoteToLiveNow": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "requestFilesWritten": False,
            "receiptFilesWritten": False,
            "brokerCallsMade": False,
            "autoDisableMutationAllowed": False,
        })
    return rows


def _execution_mode_blockers(cutover: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in _safe_list(cutover.get("blockers")):
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "")
        if code not in {
            "EXECUTION_MODE_GATES_NOT_ACTIVE",
            "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
            "MT5_READ_ONLY_MODE_STILL_ACTIVE",
            "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
            "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
            "STARTUP_CONFIG_ALLOW_LIVE_TRADING_OFF",
            "DEPLOYED_PRESET_READ_ONLY_TRUE",
            "DEPLOYED_PRESET_PILOT_AUTO_TRADING_OFF",
            "DEPLOYED_PRESET_RSI_LIVE_OFF",
            "DEPLOYED_PRESET_EA_REQUEST_READER_OFF",
        }:
            continue
        key = (code, str(row.get("reasonZh") or ""))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def _blockers_by_code(cutover: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _safe_list(cutover.get("blockers")):
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "")
        if code and code not in rows:
            rows[code] = row
    return rows


def _gate_current(blockers: dict[str, dict[str, Any]], code: str, fallback: Any) -> Any:
    row = blockers.get(code, {})
    return row.get("value", fallback)


def _live_pilot_gate_transition_plan(
    gates: list[dict[str, Any]],
    file_evidence: dict[str, Any],
    activation_diff_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gate_fields = [str(row.get("field") or "") for row in gates if isinstance(row, dict)]
    gate_blocker_codes = [
        str(row.get("runtimeBlockerCode") or "")
        for row in gates
        if isinstance(row, dict) and row.get("runtimeBlockerCode")
    ]
    startup_config = _safe_dict(file_evidence.get("startupConfig"))
    deployed_preset = _safe_dict(file_evidence.get("deployedPreset"))
    startup_values = _safe_dict(startup_config.get("values"))
    preset_values = _safe_dict(deployed_preset.get("values"))
    activation_diff_package = _safe_dict(activation_diff_package)
    return {
        "status": "WAITING_EXECUTION_MODE_ACTIVATION",
        "statusZh": "等待 MT5/EA live pilot 四闸门切换",
        "canBeAppliedByThisArtifact": False,
        "writesMt5Preset": False,
        "writesMt5OrderRequest": False,
        "brokerCallsMade": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "gateFields": gate_fields,
        "gateBlockerCodes": gate_blocker_codes,
        "actualRuntimeFileEvidence": {
            "startupConfigPath": startup_config.get("path", ""),
            "deployedPresetPath": deployed_preset.get("path", ""),
            "restartWouldKeepExecutionDisabled": bool(file_evidence.get("restartWouldKeepExecutionDisabled")),
            "writesMt5Preset": False,
            "writesStartupConfig": False,
        },
        "reviewedPresetDiffPreview": {
            "mode": "REVIEW_ONLY_DIFF_PREVIEW_NO_FILE_WRITE",
            "sourcePresetPath": deployed_preset.get("path", ""),
            "startupConfigPath": startup_config.get("path", ""),
            "candidateFileWritten": False,
            "writesMt5Preset": False,
            "writesStartupConfig": False,
            "orderSendAllowed": False,
            "changes": [
                {
                    "key": "ReadOnlyMode",
                    "current": str(preset_values.get("ReadOnlyMode") or ""),
                    "candidate": "false",
                    "reasonZh": "解除 EA read-only fuse；必须与 kill switch、spread、daily loss、position cap 一起评审。",
                },
                {
                    "key": "EnablePilotAutoTrading",
                    "current": str(preset_values.get("EnablePilotAutoTrading") or ""),
                    "candidate": "true",
                    "reasonZh": "让 IsPilotLiveMode() 可成立；本 artifact 只给 diff，不写 preset。",
                },
                {
                    "key": "PilotStartupEntryGuardMode",
                    "current": str(preset_values.get("PilotStartupEntryGuardMode") or ""),
                    "candidate": "FAST_WARMUP",
                    "reasonZh": "降低首次入场等待，但仍不能绕过点差、新闻、kill switch、仓位和策略闸门。",
                },
                {
                    "key": "AllowLiveTrading",
                    "current": str(startup_values.get("AllowLiveTrading") or ""),
                    "candidate": "operator-reviewed MT5 terminal/EA attach setting",
                    "reasonZh": "启动 ini 目前会让重启后继续关闭 live trading；只能作为人工切换审查输入。",
                },
            ],
        },
        "reviewOnlyPresetDiffPackage": activation_diff_package,
        "transitionSteps": [
            {
                "stepId": "operator_approval_bound",
                "labelZh": "用户授权绑定到当前 review packet",
                "status": "DONE_IN_REVIEW_EVIDENCE",
                "requiredBeforeLive": True,
                "canBeAppliedByThisArtifact": False,
                "evidenceRequired": [
                    "QuantGod_LiveOperatorApprovalEvidenceReview.json status accepted",
                    "reviewPacketHash matches current review packet",
                ],
                "forbiddenHere": ["unlock orderSendAllowed", "write MT5 preset"],
            },
            {
                "stepId": "reviewed_preset_diff",
                "labelZh": "生成并审查 live pilot preset 差异",
                "status": "PENDING_EXECUTION_LANE_REVIEW",
                "requiredBeforeLive": True,
                "canBeAppliedByThisArtifact": False,
                "evidenceRequired": [
                    "ReadOnlyMode false is reviewed with kill switch still active",
                    "EnablePilotAutoTrading true is reviewed with max loss and spread limits",
                    "target route is scoped to exactly one approved lane",
                ],
                "forbiddenHere": ["mutate existing live preset", "attach EA from this artifact"],
            },
            {
                "stepId": "manual_mt5_attach_and_runtime_proof",
                "labelZh": "MT5 手动挂载后重新证明四个执行闸门",
                "status": "WAITING_RUNTIME_PROOF",
                "requiredBeforeLive": True,
                "canBeAppliedByThisArtifact": False,
                "evidenceRequired": [
                    "livePilotMode=true",
                    "readOnlyMode=false",
                    "executionEnabled=true",
                    "tradeAllowed=true",
                ],
                "forbiddenHere": ["infer runtime proof from account permission only"],
            },
            {
                "stepId": "request_reader_and_broker_send_reviews",
                "labelZh": "完成 request reader、broker send、receipt、rollback 拆分评审",
                "status": "PENDING_IMPLEMENTATION_REVIEW",
                "requiredBeforeLive": True,
                "canBeAppliedByThisArtifact": False,
                "evidenceRequired": [
                    "EA request reader consumption review",
                    "broker order send wrapper review",
                    "receipt reconciliation review",
                    "rollback and auto-disable review",
                ],
                "forbiddenHere": ["consume request files", "call OrderSend", "write live receipt"],
            },
            {
                "stepId": "post_attach_preflight_rerun",
                "labelZh": "切换后重跑 runtime preflight 与 broker-send review",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "requiredBeforeLive": True,
                "canBeAppliedByThisArtifact": False,
                "evidenceRequired": [
                    "QuantGod_LiveRuntimePreflightProbe.json runtimeProbePassed=true",
                    "QuantGod_BrokerOrderSendReview.json still binds account/server/symbol/risk fuses",
                    "all safety flags are reviewed before any live order path exists",
                ],
                "forbiddenHere": ["auto-promote to live from this artifact"],
            },
        ],
        "validationCommands": [
            {
                "id": "refresh_runtime_preflight",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir <Live16 Files> runtime-preflight --write",
                "expectedStatus": "READY_FOR_LIVE_PILOT_RUNTIME_REVIEW",
                "mustProve": ["livePilotMode", "readOnlyMode", "executionEnabled", "tradeAllowed"],
            },
            {
                "id": "refresh_order_contract",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir <Live16 Files> order-request-contract --write",
                "expectedStatus": "READY_FOR_ADAPTER_CODE_REVIEW",
                "mustProve": ["runtimePreflightHash current", "request schema fixed", "no request files written"],
            },
            {
                "id": "refresh_broker_send_review",
                "command": "python3 tools/run_live_automation_readiness.py --runtime-dir <Live16 Files> broker-order-send-review --write",
                "expectedStatus": "READY_FOR_BROKER_ORDER_SEND_REVIEW",
                "mustProve": ["account/server bound", "symbol/risk fuses bound", "no broker calls in review"],
            },
        ],
        "nextRequiredActionZh": (
            "把 live pilot preset diff、MT5 手动挂载证明、request reader、broker send、receipt 和 rollback "
            "作为独立执行 lane 评审输入；本 artifact 仍不能写单。"
        ),
    }


def _execution_activation_gap_audit(cutover: dict[str, Any], activation: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers = _blockers_by_code(cutover)
    activation = _safe_dict(activation)
    activation_package = _safe_dict(activation.get("presetActivationPackage"))
    activation_diff_package = _safe_dict(activation_package.get("reviewOnlyPresetDiffPackage"))
    file_evidence = _safe_dict(cutover.get("executionModeFileEvidence"))
    startup_config = _safe_dict(file_evidence.get("startupConfig"))
    deployed_preset = _safe_dict(file_evidence.get("deployedPreset"))
    startup_values = _safe_dict(startup_config.get("values"))
    preset_values = _safe_dict(deployed_preset.get("values"))
    preset_file = "MQL5/Presets/QuantGod_MT5_HFM_LiveSecondary.set"
    ea_file = "MQL5/Experts/QuantGod_MultiStrategy.mq5"
    gates = [
        {
            "field": "readOnlyMode",
            "current": _gate_current(blockers, "MT5_READ_ONLY_MODE_STILL_ACTIVE", True),
            "expectedForLivePilot": False,
            "runtimeBlockerCode": "MT5_READ_ONLY_MODE_STILL_ACTIVE",
            "currentPresetSetting": f"ReadOnlyMode={preset_values.get('ReadOnlyMode') or 'true'}",
            "eaSourceOfTruth": "ReadOnlyMode input and LiveTradePermissionBlocker() return READ_ONLY_MODE first.",
            "reviewedActivationRequirementZh": "必须在单独 live pilot 激活评审中确认新 preset 把 ReadOnlyMode 关掉，并保留 kill switch、账户、symbol、spread、daily loss 和 position cap 约束。",
        },
        {
            "field": "livePilotMode",
            "current": _gate_current(blockers, "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED", False),
            "expectedForLivePilot": True,
            "runtimeBlockerCode": "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
            "currentPresetSetting": (
                f"EnablePilotAutoTrading={preset_values.get('EnablePilotAutoTrading') or 'false'}, "
                f"ReadOnlyMode={preset_values.get('ReadOnlyMode') or 'true'}"
            ),
            "eaSourceOfTruth": "IsPilotLiveMode() returns EnablePilotAutoTrading && !ReadOnlyMode.",
            "reviewedActivationRequirementZh": "必须在已审查的 live pilot preset 中同时满足 EnablePilotAutoTrading=true 且 ReadOnlyMode=false。",
        },
        {
            "field": "executionEnabled",
            "current": _gate_current(blockers, "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT", False),
            "expectedForLivePilot": True,
            "runtimeBlockerCode": "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
            "currentPresetSetting": f"ReadOnlyMode={preset_values.get('ReadOnlyMode') or 'true'}",
            "eaSourceOfTruth": "Dashboard runtime exports executionEnabled as !ReadOnlyMode.",
            "reviewedActivationRequirementZh": "必须由同一份已审查 live pilot runtime 证明 executionEnabled=true；本 artifact 不能自行改 preset。",
        },
        {
            "field": "tradeAllowed",
            "current": _gate_current(blockers, "MT5_TRADE_ALLOWED_NOT_CONFIRMED", False),
            "expectedForLivePilot": True,
            "runtimeBlockerCode": "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
            "currentPresetSetting": "Composite permission is false while ReadOnlyMode=true.",
            "eaSourceOfTruth": "tradeAllowed requires !ReadOnlyMode plus terminal/account/program/symbol permissions.",
            "reviewedActivationRequirementZh": "必须在 MT5 dashboard 同时证明终端、账户、EA、symbol 和 ReadOnlyMode 全部通过，不能只看账户有交易权限。",
        },
    ]
    request_reader_gap = {
        "field": "eaRequestReader",
        "current": False,
        "expectedForLivePilot": "reviewed staged enablement only",
        "currentPresetSetting": "EnableEARequestReaderReviewHarness=false by default",
        "eaSourceOfTruth": "EA request reader review harness defaults to disabled and does not consume request files in this lane.",
        "reviewedActivationRequirementZh": "必须先完成 adapter write、EA request consumption、broker order send 和 receipt reconciliation 的单独评审，才能允许 EA 读取 request 并写 receipt。",
    }
    return {
        "status": "PROFIT_TARGET_REACHED_EXECUTION_GATES_OFF",
        "statusZh": "合计盈利目标已过，实盘执行闸门仍关闭",
        "profitGateConclusionZh": "不再要求每条 lane 都达到 50 USD；当前只要求必需 lane 为正收益且合计达到 50 USD。",
        "goLiveAllowedNow": False,
        "directReasonZh": "MT5 Live16 数据面已通过，但当前 preset 和 EA runtime 仍显式处于 read-only/shadow 执行模式。",
        "sourceOfTruth": {
            "runtimeArtifact": "QuantGod_LiveRuntimePreflightProbe.json",
            "orchestratorArtifact": "QuantGod_SimToLiveOrchestrator.json",
            "presetFile": preset_file,
            "eaFile": ea_file,
            "actualStartupConfigPath": startup_config.get("path", ""),
            "actualDeployedPresetPath": deployed_preset.get("path", ""),
        },
        "actualRuntimeFileEvidence": file_evidence,
        "fileEvidenceBlockers": _safe_list(file_evidence.get("blockingEvidence")),
        "gates": gates,
        "requestReaderGap": request_reader_gap,
        "requiredReviewedActivationChangeSet": [
            {
                "id": "create_reviewed_live_pilot_preset",
                "descriptionZh": "生成单独 live pilot preset/activation package，把 ReadOnlyMode、EnablePilotAutoTrading 和目标策略 live toggle 作为一个整体审查。",
                "mustRemainDisabledHere": True,
            },
            {
                "id": "prove_runtime_gates_after_manual_mt5_attach",
                "descriptionZh": "让 MT5 dashboard 重新导出 livePilotMode=true、readOnlyMode=false、executionEnabled=true、tradeAllowed=true。",
                "mustRemainDisabledHere": True,
            },
            {
                "id": "review_request_reader_and_broker_send_path",
                "descriptionZh": "完成 request 写入、EA 消费、OrderSend、receipt、回滚/暂停的拆分实现评审。",
                "mustRemainDisabledHere": True,
            },
        ],
        "livePilotGateTransitionPlan": _live_pilot_gate_transition_plan(
            gates,
            file_evidence,
            activation_diff_package=activation_diff_package,
        ),
    }


def _first_dict(rows: Any) -> dict[str, Any]:
    for row in _safe_list(rows):
        if isinstance(row, dict):
            return row
    return {}


def _canonical_execution_lane_id(value: Any) -> str:
    text = str(value or "").strip()
    mapping = {
        "forexMt5": "FOREX_MT5",
        "FOREX_MT5": "FOREX_MT5",
        "USDJPY_MT5": "USDJPY_MT5",
    }
    return mapping.get(text, text)


def _implementation_blueprint(runtime_dir: Path, cutover: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    handoff = _safe_dict(cutover.get("implementationHandoff"))
    adapter_write = _read_existing_json(live_execution_adapter_write_review_path(runtime_dir))
    ea_consumption = _read_existing_json(ea_request_consumption_review_path(runtime_dir))
    broker_send = _read_existing_json(broker_order_send_review_path(runtime_dir))
    receipt_reconciliation = _read_existing_json(receipt_reconciliation_review_path(runtime_dir))
    write_plan = _first_dict(adapter_write.get("writePlans"))
    consumption_plan = _first_dict(ea_consumption.get("consumptionPlans"))
    broker_plan = _first_dict(broker_send.get("brokerSendPlans"))
    rejection_plan = _safe_dict(consumption_plan.get("rejectionReceiptPlan"))
    rejection_receipt_plan_complete = bool(
        rejection_plan.get("complete") is True
        or handoff.get("rejectionReceiptPlanComplete") is True
    )
    target_lane = (
        str(broker_plan.get("lane") or "")
        or str(handoff.get("selectedLane") or "")
        or str((_safe_list(handoff.get("approvedLanes")) or [""])[0] or "")
    )
    target_lane = _canonical_execution_lane_id(target_lane)
    target_request_id = (
        str(broker_plan.get("requestId") or "")
        or str(consumption_plan.get("requestId") or "")
        or str(write_plan.get("requestId") or "")
    )
    packages = [
        {
            "packageId": "python_request_writer",
            "stepId": "live_execution_adapter_write_path",
            "status": "READY_TO_CODE_DISABLED_FIRST",
            "definitionOfDone": [
                "serialize exactly the reviewed request contract",
                "write to temp file then atomic rename only after a future reviewed execution switch",
                "refuse duplicate requestId/final path before any file write",
                "never call broker from Python writer",
            ],
            "currentReviewEvidence": {
                "adapterWriteStatus": adapter_write.get("status", ""),
                "writerRuntimePreflight": _safe_dict(adapter_write.get("writerRuntimePreflight")).get("status", ""),
                "writePlanCount": adapter_write.get("writePlanCount", len(_safe_list(adapter_write.get("writePlans")))),
                "disabledFirstWriterModule": "tools/live_automation_readiness/live_execution_request_writer.py",
            },
        },
        {
            "packageId": "mql5_request_reader",
            "stepId": "ea_request_reader_consumption_path",
            "status": "READY_TO_CODE_DISABLED_FIRST",
            "definitionOfDone": [
                "poll request directory only when reviewed EA reader switch is enabled",
                "validate schema/hash/idempotency/kill switch before broker path",
                "produce rejected receipts for schema, duplicate, expired and kill-switch cases",
                "leave request unread in review-only mode",
            ],
            "currentReviewEvidence": {
                "eaConsumptionStatus": ea_consumption.get("status", ""),
                "rejectionReceiptPlanComplete": rejection_plan.get("complete") is True,
                "duplicateRequestIds": ea_consumption.get("duplicateRequestIds", []),
                "disabledExecutionStatusFunction": "BuildEARequestReaderExecutionStatusJson",
                "disabledExecutionStatusFile": "QuantGod_EARequestReaderExecutionStatus.json",
                "dashboardField": "eaRequestReaderExecution",
                "validationMatrixFunction": "BuildEARequestReaderExecutionRequiredFieldsJson",
                "rejectionMatrixFunction": "BuildEARequestReaderExecutionRejectionMatrixJson",
            },
        },
        {
            "packageId": "mql5_broker_order_send_wrapper",
            "stepId": "broker_order_send_path",
            "status": "READY_TO_CODE_DISABLED_FIRST",
            "definitionOfDone": [
                "enter broker send only from validated request reader",
                "bind account/server/symbol/volume step/spread/daily loss/position cap",
                "write retcode, fill price and ticket into receipt after future execution",
                "fail closed without retry amplification",
            ],
            "currentReviewEvidence": {
                "brokerOrderSendStatus": broker_send.get("status", ""),
                "brokerSendPlanCount": broker_send.get("brokerSendPlanCount", len(_safe_list(broker_send.get("brokerSendPlans")))),
                "targetBrokerSymbol": broker_plan.get("brokerSymbol", ""),
                "disabledWrapperStatusFunction": "BuildBrokerOrderSendWrapperStatusJson",
                "disabledWrapperStatusFile": "QuantGod_BrokerOrderSendWrapperStatus.json",
                "dashboardField": "brokerOrderSendWrapper",
            },
        },
        {
            "packageId": "receipt_writer_and_reconciliation",
            "stepId": "receipt_writer_and_reconciliation_path",
            "status": "READY_TO_CODE_DISABLED_FIRST",
            "definitionOfDone": [
                "one receipt per request: accepted, rejected, duplicate or expired",
                "reject review-only receipts containing a ticket",
                "block cutover on missing or orphan receipts",
                "surface receipt failures to dashboard/operator artifacts",
            ],
            "currentReviewEvidence": {
                "receiptReconciliationStatus": receipt_reconciliation.get("status", ""),
                "reviewOnlyReceiptsReconciled": receipt_reconciliation.get("reviewOnlyReceiptsReconciled", False),
                "receiptCount": receipt_reconciliation.get("receiptCount", 0),
                "disabledReceiptStatusFunction": "BuildReceiptWriterReconciliationStatusJson",
                "disabledReceiptStatusFile": "QuantGod_ReceiptWriterReconciliationStatus.json",
                "dashboardField": "receiptWriterReconciliation",
            },
        },
        {
            "packageId": "rollback_auto_disable",
            "stepId": "rollback_and_auto_disable_path",
            "status": "READY_TO_CODE_DISABLED_FIRST",
            "definitionOfDone": [
                "pause on missing/failed/orphan receipt",
                "pause on broker send wrapper not ready",
                "pause if EA reader is unexpectedly enabled before reviewed activation",
                "require fresh approval and preflight before manual re-arm",
            ],
            "currentReviewEvidence": {
                "rollbackRuleCount": handoff.get("rollbackRuleCount", 0),
                "requiredFuturePrs": handoff.get("requiredFuturePrs", []),
                "disabledRollbackStatusFunction": "BuildRollbackAutoDisableStatusJson",
                "disabledRollbackStatusFile": "QuantGod_RollbackAutoDisableStatus.json",
                "dashboardField": "rollbackAutoDisable",
                "triggerMatrixFunction": "BuildRollbackAutoDisableTriggerMatrixJson",
                "manualRearmRequirementsFunction": "BuildRollbackManualRearmRequirementsJson",
            },
        },
    ]
    required_step_ids = {str(row.get("stepId") or "") for row in steps if isinstance(row, dict)}
    package_step_ids = {str(row.get("stepId") or "") for row in packages}
    hard_blocks = [
        {
            "code": "EXECUTION_CODE_NOT_DEPLOYED",
            "reasonZh": "Python request writer、EA reader 状态/校验/拒绝矩阵、broker wrapper 状态/风控合同、receipt writer/reconciliation 状态/阻断矩阵、rollback auto-disable 状态/触发矩阵已有 disabled-first 实现；EA request 实际文件消费、broker call、receipt 实际写入、auto-disable 状态写入和 re-arm 执行段仍未部署到可执行闭环。",
        },
        {
            "code": "ORDER_SEND_FLAG_REMAINS_FALSE",
            "reasonZh": "当前 artifact 不允许把 orderSendAllowed 或 mt5OrderSendAllowed 置为 true。",
        },
    ]
    return {
        "mode": "MICRO_LIVE_EXECUTION_IMPLEMENTATION_BLUEPRINT_REVIEW_ONLY",
        "status": "READY_TO_IMPLEMENT_DISABLED_FIRST",
        "statusZh": "可开始拆分实现真实执行 lane，但本 artifact 仍不启用下单",
        "disabledFirstImplementationWorkReady": True,
        "nextCodeWorkAllowedInReviewOnly": True,
        "liveExecutionStillForbidden": True,
        "selectedLane": target_lane,
        "requestId": target_request_id,
        "brokerSymbol": broker_plan.get("brokerSymbol") or handoff.get("brokerSymbol", ""),
        "canonicalSymbol": broker_plan.get("canonicalSymbol") or handoff.get("canonicalSymbol", ""),
        "accountNumber": broker_plan.get("accountNumber") or handoff.get("accountNumber"),
        "brokerServer": broker_plan.get("brokerServer") or handoff.get("brokerServer", ""),
        "requestDirectory": handoff.get("requestDirectory", ""),
        "receiptDirectory": handoff.get("receiptDirectory", ""),
        "reviewPacketHash": handoff.get("reviewPacketHash", ""),
        "runtimePreflightHash": handoff.get("runtimePreflightHash", ""),
        "reviewPlanVolumeLots": broker_plan.get("volumeLots") or handoff.get("volumeLots", 0),
        "initialLiveVolumeLotsCandidate": 0.01,
        "initialLiveVolumeRequiresSeparateRiskReview": True,
        "packageCount": len(packages),
        "implementationPackages": packages,
        "allRequiredStepsMapped": bool(required_step_ids and required_step_ids.issubset(package_step_ids)),
        "rejectionReceiptPlanComplete": rejection_receipt_plan_complete,
        "duplicateRequestIds": ea_consumption.get("duplicateRequestIds", handoff.get("duplicateRequestIds", [])),
        "hardBlocksBeforeAnyLiveOrder": hard_blocks,
        "wouldWriteRequestFile": False,
        "wouldWriteReceiptFile": False,
        "wouldCallBroker": False,
        "requestWritesAllowed": False,
        "requestFilesWritten": False,
        "receiptWritesAllowed": False,
        "receiptFilesWritten": False,
        "brokerCallsMade": False,
        "adapterExecutionAllowed": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "brokerExecutionAllowed": False,
        "eaRequestReaderAllowed": False,
        "eaRequestReaderEnabled": False,
        "eaRequestFilesRead": False,
        "eaRequestFilesConsumed": False,
        "eaOrderSendAllowed": False,
    }


def build_live_execution_implementation_spec_cutover_proxy(runtime_dir: Path) -> dict[str, Any]:
    """Return a non-recursive review-only spec while cutover is assembling dependencies."""
    runtime_dir = Path(runtime_dir)
    cutover_proxy = {
        "status": "WAITING_EXECUTION_MODE_ACTIVATION",
        "readyForSeparateLiveExecutionCutoverImplementationReview": False,
        "dataPlaneCutoverReady": True,
        "executionModeOnlyBlocked": True,
        "implementationHandoff": {
            "handoffMode": "CUTOVER_REVIEW_IN_PROGRESS_NON_RECURSIVE_PROXY",
            "implementationMustStaySeparate": True,
            "requestDirectory": "runtime/agent/mt5_order_requests",
            "receiptDirectory": "runtime/agent/mt5_order_receipts",
            "requiredFuturePrs": [
                "live_execution_adapter_write_path",
                "ea_request_reader_consumption_path",
                "broker_order_send_path",
                "receipt_writer_and_reconciliation_path",
                "rollback_and_auto_disable_path",
            ],
        },
        "blockers": [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "cutover 正在生成 broker send 证据；implementation spec 使用非递归代理，真实执行仍关闭。",
            )
        ],
    }
    steps = _implementation_steps(cutover_proxy)
    payload = {
        "ok": True,
        "schema": LIVE_EXECUTION_IMPLEMENTATION_SPEC_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": "WAITING_EXECUTION_MODE_ACTIVATION",
        "statusZh": "live execution implementation spec 数据面代理已生成，等待执行模式闸门",
        "specMode": "IMPLEMENTATION_SPEC_REVIEW_ONLY_NO_EXECUTION_NON_RECURSIVE_PROXY",
        "readyForLiveExecutionImplementationSpecReview": False,
        "dataPlaneImplementationSpecReady": True,
        "executionModeOnlyBlocked": True,
        "implementationCanStart": False,
        "disabledFirstImplementationWorkReady": True,
        "nextCodeWorkAllowedInReviewOnly": True,
        "liveExecutionStillForbidden": True,
        "implementationSteps": steps,
        "implementationStepCount": len(steps),
        "implementationAcceptanceMatrix": _acceptance_matrix(steps),
        "executionSafetyTraceabilityMatrix": _execution_safety_traceability_matrix(steps),
        "implementationHandoff": _safe_dict(cutover_proxy.get("implementationHandoff")),
        "blockers": _safe_list(cutover_proxy.get("blockers")),
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "liveExecutionCutoverAllowed": False,
        "livePilotActivationAllowed": False,
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
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    return payload


def build_live_execution_implementation_spec(
    runtime_dir: Path,
    *,
    ea_source_path: str = "",
    ea_status_json: str = "",
    receipt_json: str = "",
    request_json: str = "",
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    should_rebuild = bool(
        refresh_sources
        or ea_source_path
        or ea_status_json
        or receipt_json
        or request_json
        or operator_approval_json
        or extra_bases_roots
    )
    cutover = (
        build_live_execution_cutover_review(
            runtime_dir,
            ea_source_path=ea_source_path,
            ea_status_json=ea_status_json,
            receipt_json=receipt_json,
            request_json=request_json,
            operator_approval_json=operator_approval_json,
            write=write,
            refresh_sources=refresh_sources,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_live_execution_cutover_review(runtime_dir)
    )
    cutover_ready = bool(cutover.get("readyForSeparateLiveExecutionCutoverImplementationReview"))
    activation = _read_existing_json(live_pilot_activation_review_path(runtime_dir))
    steps = _implementation_steps(cutover)
    implementation_blueprint = _implementation_blueprint(runtime_dir, cutover, steps)
    disabled_first_work_ready = bool(
        data_plane_implementation_spec_ready := bool(cutover.get("dataPlaneCutoverReady") and steps)
    )
    blockers = []
    if not cutover_ready:
        blockers.append(_blocker(
            "LIVE_EXECUTION_CUTOVER_REVIEW_NOT_READY",
            "必须先让最终 cutover review 全链路通过，才能进入实盘实现规格评审。",
            cutover.get("status", ""),
        ))
    execution_mode_only_blocked = bool(cutover.get("executionModeOnlyBlocked"))
    activation_gap_audit = _execution_activation_gap_audit(cutover, activation)
    execution_mode_blocker_rows = _execution_mode_blockers(cutover)
    execution_mode_blocker_codes = list(dict.fromkeys(
        str(row.get("code") or "")
        for row in execution_mode_blocker_rows
        if isinstance(row, dict) and row.get("code")
    ))
    if data_plane_implementation_spec_ready and execution_mode_only_blocked and not cutover_ready:
        blockers = [
            _blocker(
                "EXECUTION_MODE_GATES_NOT_ACTIVE",
                "live execution implementation spec 数据面和拆分 PR 合同已具备；仅等待执行模式闸门。",
                cutover.get("status", ""),
            )
        ]
        blockers.extend(execution_mode_blocker_rows)
    payload = {
        "ok": True,
        "schema": LIVE_EXECUTION_IMPLEMENTATION_SPEC_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": (
            "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW"
            if cutover_ready
            else "WAITING_EXECUTION_MODE_ACTIVATION"
            if data_plane_implementation_spec_ready and execution_mode_only_blocked
            else "WAITING_LIVE_EXECUTION_IMPLEMENTATION_SPEC_INPUTS"
        ),
        "statusZh": (
            "可评审 live execution implementation spec"
            if cutover_ready
            else "live execution implementation spec 数据面已通过，等待执行模式闸门"
            if data_plane_implementation_spec_ready and execution_mode_only_blocked
            else "等待 live execution implementation spec 输入"
        ),
        "specMode": "IMPLEMENTATION_SPEC_REVIEW_ONLY_NO_EXECUTION",
        "readyForLiveExecutionImplementationSpecReview": cutover_ready,
        "dataPlaneImplementationSpecReady": data_plane_implementation_spec_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "implementationCanStart": cutover_ready,
        "disabledFirstImplementationWorkReady": disabled_first_work_ready,
        "nextCodeWorkAllowedInReviewOnly": disabled_first_work_ready,
        "liveExecutionStillForbidden": True,
        "implementationReadinessSummary": {
            "status": (
                "READY_TO_IMPLEMENT_DISABLED_FIRST"
                if disabled_first_work_ready
                else "WAITING_IMPLEMENTATION_INPUTS"
            ),
            "statusZh": (
                "可继续拆分实现 execution lane 的 disabled-first 代码；真实订单仍禁止。"
                if disabled_first_work_ready
                else "等待 cutover 数据面和 implementation steps。"
            ),
            "allowedWorkType": "CODE_AND_REVIEW_ARTIFACTS_ONLY",
            "forbiddenWorkType": "LIVE_ORDER_EXECUTION",
            "packageCount": implementation_blueprint.get("packageCount", 0),
            "allRequiredStepsMapped": implementation_blueprint.get("allRequiredStepsMapped", False),
            "blockedExecutionGateFields": [
                row.get("field", "")
                for row in _safe_list(activation_gap_audit.get("gates"))
                if isinstance(row, dict)
            ],
            "primaryExecutionBlockerCodes": [
                code
                for code in execution_mode_blocker_codes
            ],
            "nextRequiredActionZh": (
                "按 microLiveExecutionBlueprint.implementationPackages 逐个实现 disabled-first 代码和测试；"
                "任何实盘订单、preset 变更、request/receipt 写入仍必须保持关闭。"
            ),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "requestFilesWritten": False,
            "receiptFilesWritten": False,
            "brokerCallsMade": False,
        },
        "implementationMustStaySeparate": True,
        "executionReady": False,
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "liveExecutionCutoverAllowed": False,
        "livePilotActivationAllowed": False,
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
        "cutoverReview": {
            "schema": cutover.get("schema", ""),
            "status": cutover.get("status", ""),
            "readyForSeparateLiveExecutionCutoverImplementationReview": cutover_ready,
            "dataPlaneCutoverReady": cutover.get("dataPlaneCutoverReady", False),
            "executionModeOnlyBlocked": cutover.get("executionModeOnlyBlocked", False),
            "blockerCount": len(_safe_list(cutover.get("blockers"))),
            "implementationHandoff": _safe_dict(cutover.get("implementationHandoff")),
            "executionModeFileEvidence": _safe_dict(cutover.get("executionModeFileEvidence")),
            "reviewOnlyPresetDiffPackage": _safe_dict(
                _safe_dict(_safe_dict(activation.get("presetActivationPackage")).get("reviewOnlyPresetDiffPackage"))
            ),
        },
        "executionActivationGapAudit": activation_gap_audit,
        "microLiveExecutionBlueprint": implementation_blueprint,
        "implementationSteps": steps,
        "acceptanceMatrix": _acceptance_matrix(steps),
        "executionSafetyTraceabilityMatrix": _execution_safety_traceability_matrix(steps),
        "requiredFuturePrs": [row["stepId"] for row in steps],
        "blockers": blockers,
        "nextRequiredActionZh": (
            "按 implementationSteps 拆分单独 PR，并为每个 PR 先补测试和 operator runbook；本 artifact 仍不会写 request/receipt 或调用 broker。"
            if cutover_ready
            else "implementation spec 拆分 PR 合同已生成；仅剩执行模式闸门，当前仍不会写 request/receipt 或调用 broker。"
            if data_plane_implementation_spec_ready and execution_mode_only_blocked
            else "先补齐 cutover review 的 HFM 证据、审批、preflight、EA runtime status、receipt 对账和 disabled harness。"
        ),
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = live_execution_implementation_spec_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_execution_implementation_spec(runtime_dir: Path) -> dict[str, Any]:
    path = live_execution_implementation_spec_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return build_live_execution_implementation_spec(Path(runtime_dir), write=False)


def read_existing_live_execution_implementation_spec(runtime_dir: Path) -> dict[str, Any]:
    return _read_existing_json(live_execution_implementation_spec_path(Path(runtime_dir)))
