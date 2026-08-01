from __future__ import annotations

from datetime import datetime, timezone


FOCUS_SYMBOL = "USDJPYc"
SCHEMA_WALK_FORWARD = "quantgod.usdjpy_walk_forward_report.v1"
SCHEMA_SELECTION = "quantgod.usdjpy_parameter_selection.v1"
SCHEMA_PROPOSAL = "quantgod.usdjpy_walk_forward_live_config_proposal.v1"

CONCLUSION_REJECTED = "REJECTED"
CONCLUSION_SHADOW_ONLY = "SHADOW_ONLY"
CONCLUSION_TESTER_ONLY = "TESTER_ONLY"
CONCLUSION_LIVE_CONFIG_ELIGIBLE = "LIVE_CONFIG_PROPOSAL_ELIGIBLE"

SEGMENTS = ("train", "validation", "forward")

READ_ONLY_SAFETY = {
    "localOnly": True,
    "focusOnly": True,
    "focusSymbol": FOCUS_SYMBOL,
    "walkForward": True,
    "trainValidationForward": True,
    "causalReplayInputRequired": True,
    "posteriorMayAffectTrigger": False,
    "posteriorUsedForScoringOnly": True,
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
    "requiresTesterOnlyValidation": True,
    "requiresShadowValidation": True,
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
