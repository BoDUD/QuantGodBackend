from __future__ import annotations

import os
from typing import Any, Dict, List


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, default)).strip())
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(str(os.environ.get(name, default)).strip()))
    except Exception:
        return default


def _env_text(name: str, default: str) -> str:
    return str(os.environ.get(name, default)).strip() or default


def _env_enabled(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _cent_lane() -> Dict[str, Any]:
    max_lot = min(max(_env_float("QG_CENT_MAX_LOT", _env_float("QG_AUTO_MAX_LOT", 2.0)), 0.0), 2.0)
    return {
        "accountAlias": _env_text("QG_CENT_ACCOUNT_ALIAS", "hfm_cent"),
        "accountMode": "cent",
        "accountCurrency": _env_text("QG_CENT_ACCOUNT_CURRENCY", "USC"),
        "lane": "CENT_EXPLORATION",
        "laneZh": "美分账户学习车道",
        "role": "exploration",
        "purposeZh": "收集 USDJPY RSI_Reversal LONG 的 Shadow/Paper 执行证据。",
        "allowedEntryModes": ["OPPORTUNITY_ENTRY", "STANDARD_ENTRY"],
        "allowedStages": ["CENT_PAPER", "ROLLBACK"],
        "defaultStage": "CENT_PAPER",
        "liveStages": [],
        "maxLot": max_lot,
        "riskPerTradeR": _env_float("QG_CENT_RISK_PER_TRADE_R", 0.25),
        "stageLotMode": "PAPER_NOTIONAL_ONLY",
        "stageLot": {
            "CENT_PAPER": 0.0,
            "CENT_MICRO_LIVE": 0.0,
            "OPPORTUNITY_ENTRY": min(_env_float("QG_CENT_OPPORTUNITY_LOT", 0.10), max_lot),
            "STANDARD_ENTRY": min(_env_float("QG_CENT_STANDARD_LOT", 0.35), max_lot),
            "CENT_LIMITED": 0.0,
        },
        "sampleGoals": {
            "minCentLiveTradesForUsdMirror": _env_int("QG_USD_PROMOTION_MIN_CENT_TRADES", 20),
            "minCentNoHardRollbackDays": _env_int("QG_USD_PROMOTION_MIN_NO_ROLLBACK_DAYS", 3),
        },
    }


def _usd_lane() -> Dict[str, Any]:
    max_lot = min(max(_env_float("QG_USD_MAX_LOT", 0.10), 0.0), 1.0)
    return {
        "accountAlias": _env_text("QG_USD_ACCOUNT_ALIAS", "hfm_usd"),
        "accountMode": "standard_usd",
        "accountCurrency": _env_text("QG_USD_ACCOUNT_CURRENCY", "USD"),
        "lane": "USD_DEPLOYMENT",
        "laneZh": "美元账户部署车道",
        "role": "capital_deployment",
        "purposeZh": "严格部署已被美分账户真实样本验证过的高质量结构；不参与探索。",
        "allowedEntryModes": ["STANDARD_ENTRY"],
        "paperMirrorEntryModes": ["OPPORTUNITY_ENTRY", "STANDARD_ENTRY"],
        "allowedStages": ["USD_PAPER_MIRROR", "PAUSED", "ROLLBACK"],
        "defaultStage": "USD_PAPER_MIRROR",
        "liveStages": [],
        "maxLot": max_lot,
        "riskPerTradeR": _env_float("QG_USD_RISK_PER_TRADE_R", 0.10),
        "stageLot": {
            "USD_PAPER_MIRROR": 0.0,
            "USD_MICRO_LIVE": 0.0,
            "STANDARD_ENTRY": 0.0,
            "USD_LIMITED": 0.0,
        },
        "deploymentRules": {
            "standardEntryOnly": True,
            "normalSpreadOnly": True,
            "opportunityEntryLiveAllowed": False,
            "softWideLiveAllowed": False,
            "unknownNewsLiveAllowed": False,
            "softNewsLiveAllowed": False,
            "symbol": "USDJPYc",
            "strategy": "RSI_Reversal",
            "direction": "LONG",
            "reasonZh": "美元账户当前只做 PAPER_MIRROR；证据达标也不产生实盘执行许可。",
        },
        "promotionGate": {
            "centLiveTradesMin": _env_int("QG_USD_PROMOTION_MIN_CENT_TRADES", 20),
            "centProfitFactorMin": _env_float("QG_USD_PROMOTION_MIN_CENT_PF", 1.05),
            "centNetRMin": _env_float("QG_USD_PROMOTION_MIN_CENT_NET_R", 0.0),
            "centLossStreakMax": _env_int("QG_USD_PROMOTION_MAX_CENT_LOSS_STREAK", 1),
            "noHardRollbackDaysMin": _env_int("QG_USD_PROMOTION_MIN_NO_ROLLBACK_DAYS", 3),
            "executionFeedbackCoverageMinPct": _env_float("QG_USD_PROMOTION_MIN_FEEDBACK_COVERAGE_PCT", 90.0),
        },
    }


def mt5_account_registry() -> Dict[str, Any]:
    primary = _cent_lane()
    secondary_shadow_enabled = _env_enabled("QG_MT5_SECONDARY_SHADOW_ENABLED", True)
    accounts: List[Dict[str, Any]] = [primary]
    if secondary_shadow_enabled:
        accounts.append(_usd_lane())

    if not secondary_shadow_enabled:
        primary.pop("sampleGoals", None)
        return {
            "schema": "quantgod.mt5_account_registry.v1",
            "mode": "MT5_USDJPY_SINGLE_PRIMARY_LANE",
            "secondaryShadowEnabled": False,
            "primaryAccount": primary["accountAlias"],
            "accounts": accounts,
            "spreadPolicy": {
                "schema": "quantgod.usdjpy_spread_lane_policy.v1",
                "normalLimitPips": _env_float("QG_USDJPY_SPREAD_NORMAL_PIPS", 2.2),
                "softLimitPips": _env_float("QG_USDJPY_SPREAD_SOFT_PIPS", 2.7),
                "hardLimitPips": _env_float("QG_USDJPY_SPREAD_HARD_PIPS", 3.0),
                "primarySoftWideAction": "OPPORTUNITY_ENTRY_SMALL_LOT_ADVISORY",
                "reasonZh": "当前仅主账号参与 USDJPY Shadow/Paper 评估；严重偏宽点差仍为硬阻断。",
            },
            "globalExposureGuard": {
                "schema": "quantgod.global_usdjpy_exposure_guard.v1",
                "symbol": "USDJPYc",
                "direction": "LONG",
                "singleAccountOnly": True,
                "rulesZh": [
                    "当前仅主账号参与 Shadow/ReadOnly 监控与建议生成。",
                    "所有反馈、净 R、连亏和 Case Memory 仅按当前主账号分桶。",
                ],
            },
            "safety": {
                "mt5Only": True,
                "shadowOnly": True,
                "readOnlyMode": True,
                "operatorApprovalRequired": True,
                "unattendedLiveExpansionAllowed": False,
                "liveExpansionAllowed": False,
                "orderSendAllowed": False,
                "livePresetMutationAllowed": False,
            },
        }

    spread_policy = {
        "schema": "quantgod.usdjpy_spread_lane_policy.v1",
        "normalLimitPips": _env_float("QG_USDJPY_SPREAD_NORMAL_PIPS", 2.2),
        "softLimitPips": _env_float("QG_USDJPY_SPREAD_SOFT_PIPS", 2.7),
        "hardLimitPips": _env_float("QG_USDJPY_SPREAD_HARD_PIPS", 3.0),
        "centSoftWideAction": "OPPORTUNITY_ENTRY_SMALL_LOT",
        "usdSoftWideAction": "PAPER_MIRROR_ONLY",
        "reasonZh": "2.2 pips 是正常/轻微偏宽分界；只有严重偏宽才作为硬阻断。",
    }
    return {
        "schema": "quantgod.mt5_multi_account_registry.v1",
        "mode": "MT5_USDJPY_MULTI_ACCOUNT_LANE_SPLIT",
        "primaryLearningAccount": accounts[0]["accountAlias"],
        "capitalDeploymentAccount": accounts[1]["accountAlias"],
        "accounts": accounts,
        "spreadPolicy": spread_policy,
        "globalExposureGuard": {
            "schema": "quantgod.global_usdjpy_exposure_guard.v1",
            "symbol": "USDJPYc",
            "direction": "LONG",
            "usdAccountPriority": True,
            "sameDirectionMultiAccountRiskBudget": _env_float("QG_GLOBAL_USDJPY_MAX_DIRECTIONAL_RISK_R", 0.35),
            "rulesZh": [
                "美元账户已有 USDJPY LONG 时，美分账户不得追加同向探索仓。",
                "美分账户已有 USDJPY LONG 时，美元账户只允许 STANDARD_ENTRY 且更小仓。",
                "两个账户反馈、净 R、连亏和 Case Memory 必须按 accountAlias 分桶。",
            ],
        },
        "safety": {
            "mt5Only": True,
            "shadowOnly": True,
            "readOnlyMode": True,
            "operatorApprovalRequired": True,
            "unattendedLiveExpansionAllowed": False,
            "liveExpansionAllowed": False,
            "orderSendAllowed": False,
            "livePresetMutationAllowed": False,
        },
    }
