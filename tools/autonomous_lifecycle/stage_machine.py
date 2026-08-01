from __future__ import annotations

from typing import Any, Dict


STAGE_REJECTED = "REJECTED"
STAGE_SHADOW = "SHADOW"
STAGE_FAST_SHADOW = "FAST_SHADOW"
STAGE_TESTER_ONLY = "TESTER_ONLY"
STAGE_PAPER_LIVE_SIM = "PAPER_LIVE_SIM"
STAGE_MICRO_LIVE = "MICRO_LIVE"
STAGE_LIVE_LIMITED = "LIVE_LIMITED"
STAGE_PAUSED = "PAUSED"
STAGE_ROLLBACK = "ROLLBACK"
STAGE_PAPER_CONTEXT = "PAPER_CONTEXT"
STAGE_QUARANTINED = "QUARANTINED"

LIVE_STAGES = {
    STAGE_SHADOW,
    STAGE_TESTER_ONLY,
    STAGE_PAPER_LIVE_SIM,
    STAGE_PAUSED,
    STAGE_ROLLBACK,
}

MT5_SHADOW_STAGES = {
    STAGE_REJECTED,
    STAGE_SHADOW,
    STAGE_FAST_SHADOW,
    STAGE_TESTER_ONLY,
    STAGE_PAPER_LIVE_SIM,
    STAGE_PAUSED,
}

STAGE_ZH: Dict[str, str] = {
    STAGE_REJECTED: "淘汰",
    STAGE_SHADOW: "模拟观察",
    STAGE_FAST_SHADOW: "快速模拟强化",
    STAGE_TESTER_ONLY: "测试器验证",
    STAGE_PAPER_LIVE_SIM: "实盘行情干跑",
    STAGE_MICRO_LIVE: "美分账户极小仓实盘",
    STAGE_LIVE_LIMITED: "限制实盘",
    STAGE_PAUSED: "暂停",
    STAGE_ROLLBACK: "自动回滚",
    STAGE_PAPER_CONTEXT: "事件风险参考",
    STAGE_QUARANTINED: "隔离",
}

STAGE_ORDER = [
    STAGE_REJECTED,
    STAGE_QUARANTINED,
    STAGE_PAUSED,
    STAGE_SHADOW,
    STAGE_FAST_SHADOW,
    STAGE_TESTER_ONLY,
    STAGE_PAPER_LIVE_SIM,
]


def stage_rank(stage: str) -> int:
    try:
        return STAGE_ORDER.index(str(stage))
    except ValueError:
        return 0


def stage_label(stage: str) -> str:
    return STAGE_ZH.get(str(stage), str(stage))


def stage_payload(stage: str, *, reason: str = "", extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = {
        "stage": stage,
        "stageZh": stage_label(stage),
        "reasonZh": reason,
    }
    if extra:
        payload.update(extra)
    return payload


def normalize_legacy_stage(stage: str) -> str:
    text = str(stage or "").upper()
    if text in {"SHADOW_ONLY", "WATCH_ONLY", "ACTIVE_SHADOW_OK"}:
        return STAGE_SHADOW
    if text in {"ROLLBACK_PAUSED", "HARD_ROLLBACK", "AUTO_ROLLBACK"}:
        return STAGE_ROLLBACK
    return text if text in STAGE_ZH else STAGE_REJECTED
