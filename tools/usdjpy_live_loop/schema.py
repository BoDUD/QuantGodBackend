from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FOCUS_SYMBOL = "USDJPYc"
SCHEMA_STATUS = "quantgod.usdjpy_live_loop_status.v1"
SCHEMA_INTENT = "quantgod.usdjpy_live_intent.v1"
SCHEMA_DAILY = "quantgod.usdjpy_daily_autopilot.v1"

STATE_READY = "SHADOW_ADVISORY_READY"
STATE_POLICY_READY_PRESET_BLOCKED = "POLICY_READY_PRESET_BLOCKED"
STATE_POLICY_BLOCKED = "POLICY_BLOCKED"
STATE_EVIDENCE_MISSING = "EVIDENCE_MISSING"

STATE_ZH = {
    STATE_READY: "Shadow advisory 已就绪，可继续观察与复核",
    STATE_POLICY_READY_PRESET_BLOCKED: "政策已就绪，但 Shadow/ReadOnly preset 未通过",
    STATE_POLICY_BLOCKED: "政策仍阻断，只保留 Shadow 观察",
    STATE_EVIDENCE_MISSING: "证据链不完整，只保留 Shadow 观察",
}

SAFE_EVIDENCE_BOUNDARY = {
    "localOnly": True,
    "focusOnly": True,
    "focusSymbol": FOCUS_SYMBOL,
    "advisoryOnly": True,
    "orderSendAllowedByTool": False,
    "closeAllowedByTool": False,
    "cancelAllowedByTool": False,
    "modifyAllowedByTool": False,
    "writesMt5OrderRequest": False,
    "livePresetMutationAllowed": False,
    "telegramCommandExecutionAllowed": False,
    "executionLaneExists": False,
    "existingEaOwnsExecution": False,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bool_zh(value: Any) -> str:
    return "通过" if bool(value) else "未通过"


def entry_mode_zh(value: Any) -> str:
    mapping = {
        "STANDARD_ENTRY": "标准入场候选",
        "OPPORTUNITY_ENTRY": "机会入场候选",
        "BLOCKED": "阻断",
    }
    return mapping.get(str(value or ""), "未知")


def direction_zh(value: Any) -> str:
    text = str(value or "").upper()
    if text in {"LONG", "BUY"}:
        return "买入观察"
    if text in {"SHORT", "SELL"}:
        return "卖出观察"
    return "方向待确认"
