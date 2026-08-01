from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FOCUS_SYMBOL = "USDJPYc"
SCHEMA_DATASET = "quantgod.usdjpy_runtime_dataset.v1"
SCHEMA_REPLAY = "quantgod.usdjpy_replay_report.v1"
SCHEMA_TUNING = "quantgod.usdjpy_param_tuning.v1"
SCHEMA_PROPOSAL = "quantgod.usdjpy_live_config_proposal.v1"

READ_ONLY_SAFETY = {
    "localOnly": True,
    "focusOnly": True,
    "focusSymbol": FOCUS_SYMBOL,
    "readOnlyDataPlane": True,
    "advisoryOnly": True,
    "autoApplyAllowed": "shadow_only",
    "requiresAutonomousGovernance": True,
    "operatorApprovalRequired": True,
    "unattendedLiveExpansionAllowed": False,
    "liveExpansionAllowed": False,
    "liveScopeExpansionMode": "operator_reviewed_future_lane",
    "completedByAgent": True,
    "autoAppliedByAgent": False,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "livePresetMutationAllowed": False,
    "writesMt5Preset": False,
    "writesMt5OrderRequest": False,
    "telegramCommandExecutionAllowed": False,
    "webhookReceiverAllowed": False,
    "credentialStorageAllowed": False,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "pass", "passed", "ok", "ready"}
