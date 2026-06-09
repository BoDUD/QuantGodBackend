from __future__ import annotations

from datetime import datetime, timezone


FOCUS_SYMBOL = "USDJPYc"

SCHEMA_STATE = "quantgod.autonomous_agent_state.v1"
SCHEMA_DECISION = "quantgod.autonomous_promotion_decision.v1"
SCHEMA_PATCH = "quantgod.autonomous_config_patch.v1"

STAGE_REJECTED = "REJECTED"
STAGE_SHADOW = "SHADOW"
STAGE_FAST_SHADOW = "FAST_SHADOW"
STAGE_SHADOW_ONLY = "SHADOW_ONLY"
STAGE_TESTER_ONLY = "TESTER_ONLY"
STAGE_PAPER_LIVE_SIM = "PAPER_LIVE_SIM"
STAGE_MICRO_LIVE = "MICRO_LIVE"
STAGE_LIVE_LIMITED = "LIVE_LIMITED"
STAGE_PAUSED = "PAUSED"
STAGE_ROLLBACK = "ROLLBACK"
STAGE_PAPER_CONTEXT = "PAPER_CONTEXT"
STAGE_QUARANTINED = "QUARANTINED"

ROLLBACK_PAUSED = "ROLLBACK_PAUSED"

STAGE_ZH = {
    STAGE_REJECTED: "拒绝",
    STAGE_SHADOW: "模拟观察",
    STAGE_FAST_SHADOW: "快速模拟强化",
    STAGE_SHADOW_ONLY: "只进影子观察",
    STAGE_TESTER_ONLY: "只进测试器验证",
    STAGE_PAPER_LIVE_SIM: "实盘行情干跑",
    STAGE_MICRO_LIVE: "极小仓实盘试点",
    STAGE_LIVE_LIMITED: "受限实盘",
    STAGE_PAUSED: "暂停",
    STAGE_ROLLBACK: "自动回滚",
    STAGE_PAPER_CONTEXT: "事件风险参考",
    STAGE_QUARANTINED: "隔离",
    ROLLBACK_PAUSED: "已自动回滚并暂停",
}

HARD_SAFETY = {
    "localOnly": True,
    "focusOnly": True,
    "focusSymbol": FOCUS_SYMBOL,
    "requiresAutonomousGovernance": True,
    "autoApplyAllowed": "stage_gated",
    "operatorApprovalRequired": False,
    "unattendedLiveExpansionAllowed": True,
    "liveScopeExpansionMode": "autonomous_governance_stage_gated",
    "agentMayExpandLiveScope": True,
    "agentMayWriteConfigPatch": True,
    "patchWritable": True,
    # Keep direct broker and preset mutation disabled. The agent may only write
    # the narrow runtime patch that the EA validates before applying.
    "liveMutationAllowed": False,
    "agentMayMutateSource": False,
    "agentMayMutateLivePreset": False,
    "agentMaySendOrder": False,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "livePresetMutationAllowed": False,
    "writesMt5Preset": False,
    "writesMt5OrderRequest": False,
    "telegramCommandExecutionAllowed": False,
    "webhookReceiverAllowed": False,
    "deepSeekCanApproveLive": False,
    "deepSeekCanOverrideReplayScore": False,
    "posteriorMayAffectTrigger": False,
    "posteriorUsedForScoringOnly": True,
    "externalMarketRealMoneyAllowed": False,
    "hfmCryptoExecutionAllowed": False,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
