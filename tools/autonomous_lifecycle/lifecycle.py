from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

try:
    from tools.usdjpy_strategy_lab.schema import FOCUS_SYMBOL, utc_now_iso
except ModuleNotFoundError:  # pragma: no cover
    from usdjpy_strategy_lab.schema import FOCUS_SYMBOL, utc_now_iso

from .account_registry import mt5_account_registry
from .cent_account_rules import cent_account_config
from .ea_reproducibility import build_ea_reproducibility
from .mt5_shadow_lane import build_mt5_shadow_lane


def build_autonomous_lifecycle(
    runtime_dir: Path,
    *,
    repo_root: Path | None = None,
    write: bool = False,
) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    cent = cent_account_config()
    account_registry = mt5_account_registry()
    accounts = account_registry.get("accounts") if isinstance(account_registry.get("accounts"), list) else []
    cent_lane = accounts[0] if len(accounts) > 0 and isinstance(accounts[0], dict) else {}
    usd_lane = accounts[1] if len(accounts) > 1 and isinstance(accounts[1], dict) else {}
    mt5_shadow = build_mt5_shadow_lane(runtime_dir, write=write)
    ea_repro = build_ea_reproducibility(runtime_dir, repo_root=repo_root, write=write)
    payload: Dict[str, Any] = {
        "ok": True,
        "schema": "quantgod.autonomous_lifecycle.v2_3",
        "generatedAtIso": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "runtimeDir": str(runtime_dir),
        "sloganZh": "实盘要窄，模拟要宽，升降级要快，回滚要硬。",
        "singleSourceOfTruth": "USDJPY_LIVE_LOOP_WITH_AUTONOMOUS_LIFECYCLE",
        "centAccount": cent,
        "accountRegistry": account_registry,
        "lanes": {
            "live": {
                "lane": "LIVE",
                "laneZh": "实盘车道",
                "accountAlias": cent_lane.get("accountAlias", "hfm_cent"),
                "accountMode": cent_lane.get("accountMode", "cent"),
                "symbol": FOCUS_SYMBOL,
                "strategy": "RSI_Reversal",
                "direction": "LONG",
                "enabled": False,
                "mode": "SHADOW_READONLY",
                "allowedLiveStages": [],
                "operatorApprovalRequired": True,
                "unattendedLiveExpansionAllowed": False,
                "liveExpansionAllowed": False,
                "liveScopeExpansionMode": "operator_reviewed_future_lane",
                "forbiddenZh": ["未过 autonomous governance 的实盘扩展", "非 USDJPY 实盘"],
                "maxLotIsCapNotFixed": True,
            },
            "centLive": {
                **cent_lane,
                "symbol": FOCUS_SYMBOL,
                "strategy": "RSI_Reversal",
                "direction": "LONG",
                "entryPolicyZh": "硬风控通过后，OPPORTUNITY_ENTRY 可在美分账户小仓收集真实执行样本。",
            },
            "usdDeployment": {
                **usd_lane,
                "symbol": FOCUS_SYMBOL,
                "strategy": "RSI_Reversal",
                "direction": "LONG",
                "entryPolicyZh": (
                    "美元账户是严格部署车道：默认 USD_PAPER_MIRROR；"
                    "美分账户验证达标后，只允许 STANDARD_ENTRY / NORMAL 点差极小仓实盘。"
                ),
            },
            "globalUsdJpyExposureGuard": account_registry.get("globalExposureGuard", {}),
            "mt5Shadow": mt5_shadow,
        },
        "eaReproducibility": ea_repro,
        "safety": {
            "requiresAutonomousGovernance": True,
            "autoApplyAllowed": "shadow_only",
            "operatorApprovalRequired": True,
            "unattendedLiveExpansionAllowed": False,
            "liveExpansionAllowed": False,
            "liveScopeExpansionMode": "operator_reviewed_future_lane",
            "patchWritable": False,
            "liveMutationAllowed": False,
            "orderSendAllowed": False,
            "externalMarketRealMoneyAllowed": False,
            "deepSeekCanApproveLive": False,
            "telegramCommandExecutionAllowed": False,
        },
    }
    if write:
        out = runtime_dir / "agent"
        out.mkdir(parents=True, exist_ok=True)
        (out / "QuantGod_AutonomousLifecycle.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
