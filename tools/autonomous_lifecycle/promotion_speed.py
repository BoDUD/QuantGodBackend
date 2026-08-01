from __future__ import annotations

from typing import Any, Dict

from .cent_account_rules import cent_account_config
from .stage_machine import STAGE_PAPER_LIVE_SIM, STAGE_TESTER_ONLY


def cent_accelerated_stage(base_stage: str, *, sample_count: int, net_r_delta: float) -> Dict[str, Any]:
    cfg = cent_account_config()
    if not cfg.get("centFastPromotion"):
        return {"stage": base_stage, "accelerated": False, "reasonZh": "未启用美分账户快速晋级。"}
    if base_stage == STAGE_TESTER_ONLY and sample_count >= int(cfg.get("testerOnlyMinSamples") or 20) and net_r_delta > 0:
        return {
            "stage": STAGE_PAPER_LIVE_SIM,
            "accelerated": True,
            "reasonZh": "稳定 tester-only 候选可推进到 PAPER_LIVE_SIM，仍不具备下单权限。",
        }
    return {"stage": base_stage, "accelerated": False, "reasonZh": "未达到美分账户快速晋级门槛。"}
