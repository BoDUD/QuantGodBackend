from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List

try:
    from tools.autonomous_lifecycle.account_registry import mt5_account_registry
    from tools.news_gate.classifier import classify_news_gate
    from tools.news_gate.policy import apply_news_gate_to_live_policy
except ModuleNotFoundError:  # CLI execution from tools/
    from autonomous_lifecycle.account_registry import mt5_account_registry
    from news_gate.classifier import classify_news_gate
    from news_gate.policy import apply_news_gate_to_live_policy

from .data_loader import (
    adaptive_policy,
    dynamic_sltp,
    entry_trigger_plan,
    fastlane_quality,
    first_json,
    focus_runtime_snapshot,
)
from .schema import (
    ENTRY_BLOCKED,
    ENTRY_OPPORTUNITY,
    ENTRY_STANDARD,
    FOCUS_SYMBOL,
    PolicyItem,
    READ_ONLY_SAFETY,
    STATUS_PAUSED,
    STATUS_RUNNABLE,
    STATUS_WATCH_ONLY,
    STRATEGY_CATALOG_VERSION,
    assert_no_secret_or_execution_flags,
    utc_now_iso,
)
from .strategy_signals import build_candidate_signals
from .strategy_scoreboard import build_strategy_scoreboard

FASTLANE_PASS_STATES = {"OK", "PASS", "PASSED", "GOOD", "HEALTHY", "FAST", "EA_DASHBOARD_OK"}
LIVE_ELIGIBLE_STRATEGY = "RSI_Reversal"
LIVE_ELIGIBLE_DIRECTION = "LONG"
RUNTIME_FRESH_SECONDS = 30.0
RUNTIME_HARD_STALE_SECONDS = 90.0
SPREAD_NORMAL_PIPS = 2.2
SPREAD_SOFT_PIPS = 2.7
SPREAD_HARD_PIPS = 3.0
HARD_RSI_DIAGNOSTIC_STATES = {
    "KILL_SWITCH",
    "SYMBOL_POSITION_FULL",
    "MANUAL_POSITION_BLOCK",
    "LOSS_COOLDOWN",
    "NEWS_BLOCK",
    "SESSION_CLOSED",
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _round_lot(value: float, step: float = 0.01, min_lot: float = 0.01, max_lot: float = 2.0) -> float:
    if value <= 0:
        return 0.0
    value = max(min_lot, min(value, max_lot))
    steps = round(value / step)
    return round(max(min_lot, min(max_lot, steps * step)), 2)


def _runtime_thresholds() -> tuple[float, float]:
    fresh = max(5.0, _env_float("QG_USDJPY_RUNTIME_FRESH_SOFT_SECONDS", RUNTIME_FRESH_SECONDS))
    hard = max(fresh, _env_float("QG_USDJPY_RUNTIME_HARD_STALE_SECONDS", RUNTIME_HARD_STALE_SECONDS))
    return fresh, hard


def _spread_thresholds(diagnostics: Dict[str, Any] | None = None) -> tuple[float, float, float]:
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    guards = diagnostics.get("guards") if isinstance(diagnostics.get("guards"), dict) else {}
    inputs = diagnostics.get("inputs") if isinstance(diagnostics.get("inputs"), dict) else {}
    diagnostic_normal = _num(
        guards.get("maxSpreadPips", inputs.get("PilotMaxSpreadPips", SPREAD_NORMAL_PIPS)),
        SPREAD_NORMAL_PIPS,
    )
    normal = max(0.1, _env_float("QG_USDJPY_SPREAD_NORMAL_PIPS", diagnostic_normal or SPREAD_NORMAL_PIPS))
    soft = max(normal, _env_float("QG_USDJPY_SPREAD_SOFT_PIPS", SPREAD_SOFT_PIPS))
    hard = max(soft, _env_float("QG_USDJPY_SPREAD_HARD_PIPS", SPREAD_HARD_PIPS))
    return normal, soft, hard


def _price_payload(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    current_price = snapshot.get("current_price") if isinstance(snapshot.get("current_price"), dict) else {}
    market = snapshot.get("market") if isinstance(snapshot.get("market"), dict) else {}
    return {**market, **current_price}


def _spread_from_price_payload(price: Dict[str, Any]) -> float | None:
    bid = _num(price.get("bid"), 0.0)
    ask = _num(price.get("ask"), 0.0)
    if bid > 0 and ask > 0 and ask >= bid:
        return round(abs(ask - bid) / 0.01, 4)
    for key in ("spreadPips", "spread_pips"):
        value = _num(price.get(key), -1.0)
        if value > 0:
            return round(value, 4)
    spread = _num(price.get("spread"), -1.0)
    if spread > 0:
        return round(spread * 100.0 if spread <= 0.5 else spread, 4)
    return None


def _diagnostic_spread_pips(diagnostics: Dict[str, Any]) -> float | None:
    guards = diagnostics.get("guards") if isinstance(diagnostics.get("guards"), dict) else {}
    for source in (guards, diagnostics):
        if not isinstance(source, dict):
            continue
        for key in ("spreadPips", "currentSpreadPips", "spread_pips"):
            value = _num(source.get(key), -1.0)
            if value > 0:
                return round(value, 4)
        spread = _num(source.get("spread"), -1.0)
        if spread > 0:
            return round(spread * 100.0 if spread <= 0.5 else spread, 4)
    return None


def _build_spread_gate(snapshot: Dict[str, Any], diagnostics: Dict[str, Any] | None = None) -> Dict[str, Any]:
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    normal, soft, hard = _spread_thresholds(diagnostics)
    spread = _diagnostic_spread_pips(diagnostics)
    source = "rsi_diagnostics"
    if spread is None:
        spread = _spread_from_price_payload(_price_payload(snapshot or {}))
        source = "runtime_snapshot" if spread is not None else "missing"
    if spread is None:
        return {
            "schema": "quantgod.usdjpy_spread_gate.v1",
            "spreadPips": None,
            "tier": "UNKNOWN",
            "tierZh": "点差未知",
            "normalLimitPips": normal,
            "softLimitPips": soft,
            "hardLimitPips": hard,
            "hardBlock": True,
            "lotMultiplier": 0.0,
            "maxCentOpportunityLot": 0.0,
            "action": "BLOCK",
            "centAction": "BLOCKED",
            "usdAction": "BLOCKED",
            "centActionZh": "美分账户阻断；没有可靠点差。",
            "usdActionZh": "美元账户阻断；没有可靠点差。",
            "source": source,
            "reasonZh": "缺少可靠点差，不能用未知执行成本入场。",
        }
    soft_lot_multiplier = max(0.01, min(1.0, _env_float("QG_USDJPY_SPREAD_SOFT_LOT_MULTIPLIER", 0.35)))
    soft_high_lot_multiplier = max(0.01, min(1.0, _env_float("QG_USDJPY_SPREAD_SOFT_HIGH_LOT_MULTIPLIER", 0.20)))
    soft_cap = max(0.01, _env_float("QG_USDJPY_SOFT_WIDE_CENT_MAX_LOT", 0.10))
    soft_high_cap = max(0.01, _env_float("QG_USDJPY_SOFT_WIDE_HIGH_CENT_MAX_LOT", 0.05))
    if spread <= normal:
        tier = "NORMAL"
        tier_zh = "正常"
        hard_block = False
        lot_multiplier = 1.0
        cap = None
        action = "ALLOW_NORMAL"
        cent_action = "ALLOW_NORMAL"
        usd_action = "ALLOW_STANDARD_IF_ELIGIBLE"
        reason = "点差处于正常上限内，按 quorum 和账户车道正常处理。"
    elif spread <= soft:
        tier = "SOFT_WIDE"
        tier_zh = "轻微偏宽"
        hard_block = False
        lot_multiplier = soft_lot_multiplier
        cap = soft_cap
        action = "DOWNGRADE_LOT_NOT_BLOCK"
        cent_action = "CENT_OPPORTUNITY_SMALL_LOT"
        usd_action = "USD_PAPER_MIRROR_ONLY"
        reason = "点差轻微偏宽，美分账户降仓机会入场，美元账户仅镜像观察。"
    elif spread <= hard:
        tier = "SOFT_WIDE_HIGH"
        tier_zh = "偏宽较高"
        hard_block = False
        lot_multiplier = soft_high_lot_multiplier
        cap = soft_high_cap
        action = "DOWNGRADE_TO_MIN_LOT_NOT_BLOCK"
        cent_action = "CENT_OPPORTUNITY_MIN_LOT"
        usd_action = "USD_PAPER_MIRROR_ONLY"
        reason = "点差偏宽但未到严重异常，美分账户只允许极小仓机会入场，美元账户仅镜像观察。"
    else:
        tier = "HARD_WIDE"
        tier_zh = "严重偏宽"
        hard_block = True
        lot_multiplier = 0.0
        cap = 0.0
        action = "BLOCK"
        cent_action = "BLOCKED"
        usd_action = "BLOCKED"
        reason = "点差严重偏宽，两个账户都硬阻断。"
    return {
        "schema": "quantgod.usdjpy_spread_gate.v1",
        "spreadPips": round(spread, 4),
        "tier": tier,
        "tierZh": tier_zh,
        "normalLimitPips": normal,
        "softLimitPips": soft,
        "hardLimitPips": hard,
        "hardBlock": hard_block,
        "lotMultiplier": lot_multiplier,
        "maxCentOpportunityLot": cap,
        "action": action,
        "centAction": cent_action,
        "usdAction": usd_action,
        "centActionZh": "美分账户允许小仓机会入场。" if not hard_block and tier != "NORMAL" else ("美分账户正常处理。" if not hard_block else "美分账户阻断。"),
        "usdActionZh": "美元账户仅 paper mirror，不实盘。" if not hard_block and tier != "NORMAL" else ("美元账户只允许合格 STANDARD_ENTRY。" if not hard_block else "美元账户阻断。"),
        "source": source,
        "reasonZh": reason,
    }


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        if path.exists() and path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def _load_execution_quality_report(runtime_dir: Path) -> Dict[str, Any]:
    for path in (
        runtime_dir / "execution" / "QuantGod_LiveExecutionQualityReport.json",
        runtime_dir / "evidence_os" / "QuantGod_LiveExecutionQualityReport.json",
    ):
        payload = _read_json_file(path)
        if payload:
            payload.setdefault("_filePath", str(path))
            return payload
    return {}


def _account_lane(account_registry: Dict[str, Any], mode: str) -> Dict[str, Any]:
    accounts = account_registry.get("accounts") if isinstance(account_registry.get("accounts"), list) else []
    for account in accounts:
        if isinstance(account, dict) and str(account.get("accountMode") or "") == mode:
            return account
    return {}


def _cent_opportunity_lot_cap(
    *,
    account_registry: Dict[str, Any],
    spread_gate: Dict[str, Any],
    min_lot: float,
    max_lot: float,
    step: float,
) -> float:
    cent_lane = _account_lane(account_registry, "cent")
    stage_lot = cent_lane.get("stageLot") if isinstance(cent_lane.get("stageLot"), dict) else {}
    lane_max = _num(cent_lane.get("maxLot"), max_lot)
    configured_cap = _num(stage_lot.get("OPPORTUNITY_ENTRY"), _env_float("QG_CENT_OPPORTUNITY_LOT", 0.10))
    cap = min(max_lot, lane_max, configured_cap)
    spread_cap_value = spread_gate.get("maxCentOpportunityLot")
    if spread_cap_value not in (None, ""):
        cap = min(cap, _num(spread_cap_value, cap))
    if cap < min_lot or spread_gate.get("hardBlock"):
        return 0.0
    return _round_lot(cap, step=step, min_lot=min_lot, max_lot=max_lot)


def _cent_opportunity_sampling_gate(
    *,
    account_registry: Dict[str, Any],
    spread_gate: Dict[str, Any],
    min_lot: float,
    max_lot: float,
    step: float,
) -> Dict[str, Any]:
    cent_lane = _account_lane(account_registry, "cent")
    usd_lane = _account_lane(account_registry, "standard_usd")
    cap = _cent_opportunity_lot_cap(
        account_registry=account_registry,
        spread_gate=spread_gate,
        min_lot=min_lot,
        max_lot=max_lot,
        step=step,
    )
    return {
        "schema": "quantgod.usdjpy_cent_opportunity_sampling_gate.v1",
        "mode": "CENT_SMALL_LOT_SAMPLE_USD_PAPER_MIRROR",
        "accountAlias": cent_lane.get("accountAlias") or "hfm_cent",
        "accountMode": "cent",
        "entryMode": ENTRY_OPPORTUNITY,
        "allowedLiveAccountMode": "cent",
        "usdAccountAlias": usd_lane.get("accountAlias") or "hfm_usd",
        "usdAccountMode": "paper_mirror_only",
        "usdLiveAllowed": False,
        "maxOpportunityLot": cap,
        "spreadTier": spread_gate.get("tier") or "UNKNOWN",
        "spreadAction": spread_gate.get("centAction") or spread_gate.get("action") or "UNKNOWN",
        "requiresRuntimeFreshness": ["FRESH", "SOFT_STALE"],
        "requiresHardGatePass": True,
        "requiresNewsNotHard": True,
        "sampleGoals": cent_lane.get("sampleGoals") if isinstance(cent_lane.get("sampleGoals"), dict) else {},
        "reasonZh": (
            f"机会入场只允许美分账户小仓采样，单笔上限 {cap:.2f} lot；"
            "美元账户只做 paper mirror，不能实盘接探索单。"
        ),
    }


def _apply_cent_sampling_gate_to_live_policy(
    *,
    entry_mode: str,
    allowed: bool,
    recommended_lot: float,
    strictness: str,
    reasons: List[str],
    sampling_gate: Dict[str, Any],
    hard_status: str,
    runtime_tier: str,
    news_gate: Dict[str, Any],
    spread_gate: Dict[str, Any],
    min_lot: float,
    max_lot: float,
    step: float,
) -> tuple[str, bool, float, str, List[str], Dict[str, Any]]:
    gate = dict(sampling_gate)
    gate["active"] = entry_mode == ENTRY_OPPORTUNITY
    gate["passed"] = True
    gate["blockers"] = []
    if entry_mode != ENTRY_OPPORTUNITY:
        return entry_mode, allowed, recommended_lot, strictness, reasons, gate

    blockers: List[Dict[str, Any]] = []

    def block(code: str, reason: str, value: Any = None, limit: Any = None) -> None:
        blockers.append({"code": code, "reasonZh": reason, "value": value, "limit": limit})

    cap = _num(gate.get("maxOpportunityLot"), 0.0)
    if hard_status != "PASS":
        block("CENT_HARD_GATE_REQUIRED", "机会入场也必须先通过硬风控。", hard_status, "PASS")
    if runtime_tier not in {"FRESH", "SOFT_STALE"}:
        block("CENT_RUNTIME_FRESH_OR_SOFT_STALE_REQUIRED", "机会入场需要 FRESH 或 SOFT_STALE runtime。", runtime_tier, "FRESH/SOFT_STALE")
    news_risk = str(news_gate.get("riskLevel") or "UNKNOWN").upper()
    if news_gate.get("hardBlock") or news_risk == "HARD":
        block("CENT_NEWS_NOT_HARD_REQUIRED", "高冲击新闻窗口不允许机会入场。", news_risk, "not HARD")
    if spread_gate.get("hardBlock"):
        block("CENT_SPREAD_NOT_HARD_REQUIRED", "严重偏宽点差不允许机会入场。", spread_gate.get("tier"), "not HARD_WIDE")
    if cap < min_lot:
        block("CENT_OPPORTUNITY_LOT_CAP_TOO_SMALL", "美分账户机会入场仓位上限小于最小下单手数。", cap, min_lot)

    gate["passed"] = not blockers
    gate["blockers"] = blockers
    if blockers:
        return ENTRY_BLOCKED, False, 0.0, "BLOCKED_CENT_SAMPLING_GATE", [
            *reasons,
            "美分账户小仓采样门未通过，机会入场阻断。",
        ], gate

    lot = min(recommended_lot, cap)
    lot = _round_lot(lot, step=step, min_lot=min_lot, max_lot=max_lot) if allowed else 0.0
    gate["recommendedLotBeforeCap"] = round(float(recommended_lot or 0.0), 2)
    gate["recommendedLotAfterCap"] = lot
    return entry_mode, allowed, lot, strictness, [
        *reasons,
        gate.get("reasonZh") or "机会入场已收敛为美分账户小仓采样。",
    ], gate


def _bucket_source_count(bucket: Dict[str, Any], *keys: str) -> int:
    counts = bucket.get("sourceTierCounts") if isinstance(bucket.get("sourceTierCounts"), dict) else {}
    return sum(int(_num(counts.get(key), 0.0)) for key in keys)


def _last_loss_streak(bucket: Dict[str, Any]) -> int | None:
    if "lossStreak" in bucket:
        return int(_num(bucket.get("lossStreak"), 999.0))
    if "currentLossStreak" in bucket:
        return int(_num(bucket.get("currentLossStreak"), 999.0))
    return None


def _usd_deployment_gate(
    *,
    top_policy: Dict[str, Any],
    spread_gate: Dict[str, Any],
    news_gate: Dict[str, Any],
    runtime_tier: str,
    fast_ok: bool,
    account_registry: Dict[str, Any],
    execution_report: Dict[str, Any],
) -> Dict[str, Any]:
    usd_lane = _account_lane(account_registry, "standard_usd")
    cent_lane = _account_lane(account_registry, "cent")
    gate_cfg = usd_lane.get("promotionGate") if isinstance(usd_lane.get("promotionGate"), dict) else {}
    stage_lot = usd_lane.get("stageLot") if isinstance(usd_lane.get("stageLot"), dict) else {}
    blocked: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    def block(code: str, reason: str, value: Any = None, limit: Any = None) -> None:
        blocked.append({"code": code, "reasonZh": reason, "value": value, "limit": limit})

    entry_mode = str(top_policy.get("entryMode") or top_policy.get("entryDecision") or "MISSING")
    if not top_policy:
        block("NO_TOP_POLICY", "没有可评估的 USDJPY RSI live policy。")
    if str(top_policy.get("strategy") or "") != LIVE_ELIGIBLE_STRATEGY:
        block("USD_STRATEGY_LOCK", "美元账户只允许 RSI_Reversal。", top_policy.get("strategy"), LIVE_ELIGIBLE_STRATEGY)
    if str(top_policy.get("direction") or "").upper() != LIVE_ELIGIBLE_DIRECTION:
        block("USD_DIRECTION_LOCK", "美元账户只允许 LONG。", top_policy.get("direction"), LIVE_ELIGIBLE_DIRECTION)
    if entry_mode != ENTRY_STANDARD or not bool(top_policy.get("allowed")):
        block("USD_STANDARD_ENTRY_REQUIRED", "美元账户不接探索单；只有 STANDARD_ENTRY 才能实盘。", entry_mode, ENTRY_STANDARD)
    quorum = int(_num(top_policy.get("signalQuorum"), 0.0))
    if quorum < 3:
        block("USD_QUORUM_3_REQUIRED", "美元账户需要 3/3 signal quorum。", quorum, 3)
    if str(spread_gate.get("tier") or "UNKNOWN").upper() != "NORMAL" or spread_gate.get("hardBlock"):
        block("USD_NORMAL_SPREAD_REQUIRED", "美元账户只在 NORMAL 点差下实盘；SOFT_WIDE 只 mirror。", spread_gate.get("tier"), "NORMAL")
    news_risk = str(news_gate.get("riskLevel") or "UNKNOWN").upper()
    if news_risk != "NONE":
        block("USD_NEWS_NONE_REQUIRED", "美元账户只在无新闻风险时实盘；UNKNOWN/SOFT/HARD 都只 mirror 或阻断。", news_risk, "NONE")
    if runtime_tier != "FRESH":
        block("USD_RUNTIME_FRESH_REQUIRED", "美元账户需要 FRESH runtime；SOFT_STALE 只允许美分账户降级小仓。", runtime_tier, "FRESH")
    if not fast_ok:
        block("USD_FASTLANE_REQUIRED", "美元账户需要 fastlane 或 EA dashboard 新鲜证据通过。")

    metrics = execution_report.get("metrics") if isinstance(execution_report.get("metrics"), dict) else {}
    promotion_gate = execution_report.get("promotionGate") if isinstance(execution_report.get("promotionGate"), dict) else {}
    by_account = metrics.get("byAccount") if isinstance(metrics.get("byAccount"), dict) else {}
    cent_alias = str(cent_lane.get("accountAlias") or "hfm_cent")
    cent_bucket = by_account.get(cent_alias) if isinstance(by_account.get(cent_alias), dict) else {}
    if execution_report and not cent_bucket:
        block("USD_CENT_BUCKET_MISSING", "执行反馈缺少 hfm_cent 美分账户分桶，美元账户继续 mirror。", cent_alias)
    cent_live_events = max(
        int(_num(cent_bucket.get("fillCount"), 0.0)) + int(_num(cent_bucket.get("closeCount"), 0.0)),
        _bucket_source_count(cent_bucket, "cent_live_real"),
    )
    cent_live_trades = int(_num(cent_bucket.get("liveTradeCount") or cent_bucket.get("closedTradeCount"), cent_live_events))
    cent_net_r_raw = cent_bucket.get("netR")
    cent_net_r = _num(cent_net_r_raw, -9999.0)
    cent_pf_raw = cent_bucket.get("profitFactor")
    cent_pf = _num(cent_pf_raw, -1.0)
    loss_streak = _last_loss_streak(cent_bucket)
    no_rollback_days = _num(
        cent_bucket.get("noHardRollbackDays")
        or metrics.get("centNoHardRollbackDays")
        or execution_report.get("noHardRollbackDays"),
        -1.0,
    )
    feedback_coverage = _num(
        cent_bucket.get("feedbackCoveragePct") or metrics.get("fieldCoveragePct"),
        0.0,
    )
    exec_status = str(promotion_gate.get("status") or "WAITING_FEEDBACK").upper()
    min_trades = int(_num(gate_cfg.get("centLiveTradesMin"), 20.0))
    min_pf = _num(gate_cfg.get("centProfitFactorMin"), 1.05)
    min_net_r = _num(gate_cfg.get("centNetRMin"), 0.0)
    max_loss_streak = int(_num(gate_cfg.get("centLossStreakMax"), 1.0))
    min_no_rollback = _num(gate_cfg.get("noHardRollbackDaysMin"), 3.0)
    min_coverage = _num(gate_cfg.get("executionFeedbackCoverageMinPct"), 90.0)

    if not execution_report:
        block("USD_EXECUTION_REPORT_MISSING", "缺少执行反馈质量报告，美元账户只能 mirror。")
    if exec_status != "PASS":
        block("USD_EXECUTION_QUALITY_PASS_REQUIRED", "美元账户需要执行反馈 promotionGate=PASS。", exec_status, "PASS")
    if cent_live_trades < min_trades:
        block("USD_CENT_LIVE_TRADES_LT_MIN", "美分账户真实样本不足，美元账户暂不实盘。", cent_live_trades, min_trades)
    if cent_pf < min_pf:
        block("USD_CENT_PF_LT_MIN", "美分账户 profit factor 未达部署门槛。", cent_pf_raw if cent_pf_raw is not None else None, min_pf)
    if cent_net_r_raw in (None, "") or cent_net_r <= min_net_r:
        block("USD_CENT_NET_R_NOT_POSITIVE", "美分账户净 R 尚未证明为正。", cent_net_r_raw, f">{min_net_r}")
    if loss_streak is None:
        warnings.append({"code": "USD_CENT_LOSS_STREAK_UNKNOWN", "reasonZh": "尚未看到美分账户连亏字段，保持 USD mirror。"})
        block("USD_CENT_LOSS_STREAK_REQUIRED", "缺少美分账户连亏字段，美元账户暂不实盘。")
    elif loss_streak > max_loss_streak:
        block("USD_CENT_LOSS_STREAK_GT_MAX", "美分账户连亏超过美元部署门槛。", loss_streak, max_loss_streak)
    if no_rollback_days < min_no_rollback:
        block("USD_NO_HARD_ROLLBACK_DAYS_LT_MIN", "无硬回滚天数不足，美元账户继续 mirror。", no_rollback_days, min_no_rollback)
    if feedback_coverage < min_coverage:
        block("USD_FEEDBACK_COVERAGE_LT_MIN", "执行反馈字段覆盖率不足，美元账户继续 mirror。", feedback_coverage, min_coverage)

    live_allowed = not blocked
    target_stage = "USD_MICRO_LIVE" if live_allowed else "USD_PAPER_MIRROR"
    recommended_lot = _round_lot(
        _num(stage_lot.get("USD_MICRO_LIVE") or stage_lot.get("STANDARD_ENTRY"), 0.01),
        min_lot=0.01,
        max_lot=_num(usd_lane.get("maxLot"), 0.10),
    ) if live_allowed else 0.0
    return {
        "schema": "quantgod.usdjpy_usd_deployment_gate.v1",
        "stage": str(usd_lane.get("defaultStage") or "USD_PAPER_MIRROR"),
        "targetStage": target_stage,
        "liveAllowed": live_allowed,
        "action": "USD_MICRO_LIVE" if live_allowed else "PAPER_MIRROR",
        "allowedLiveEntryModes": ["STANDARD_ENTRY"],
        "blockedEntryModes": ["OPPORTUNITY_ENTRY"],
        "recommendedLot": recommended_lot,
        "maxLot": _num(usd_lane.get("maxLot"), 0.10),
        "normalSpreadOnly": True,
        "newsNoneOnly": True,
        "centValidation": {
            "accountAlias": cent_alias,
            "centLiveTrades": cent_live_trades,
            "centNetR": cent_net_r_raw if cent_net_r_raw not in (None, "") else None,
            "centProfitFactor": cent_pf_raw,
            "centLossStreak": loss_streak,
            "centNoHardRollbackDays": no_rollback_days if no_rollback_days >= 0 else None,
            "executionFeedbackCoveragePct": feedback_coverage,
            "executionPromotionGateStatus": exec_status,
        },
        "thresholds": {
            "centLiveTradesMin": min_trades,
            "centProfitFactorMin": min_pf,
            "centNetRMin": min_net_r,
            "centLossStreakMax": max_loss_streak,
            "noHardRollbackDaysMin": min_no_rollback,
            "executionFeedbackCoverageMinPct": min_coverage,
        },
        "blockers": blocked,
        "warnings": warnings,
        "reasonZh": (
            "美元账户部署门通过：只允许 STANDARD_ENTRY / NORMAL 点差 / 无新闻风险下极小仓实盘。"
            if live_allowed
            else "美元账户继续 mirror；只有美分账户验证和严格 STANDARD_ENTRY 条件全部通过后才切 USD_MICRO_LIVE。"
        ),
    }


def _credible_price(snapshot: Dict[str, Any]) -> bool:
    price = _price_payload(snapshot)
    bid = _num(price.get("bid"), 0.0)
    ask = _num(price.get("ask"), 0.0)
    last = _num(price.get("last") or price.get("price"), 0.0)
    if bid > 0 and ask > 0 and ask >= bid:
        return True
    return last > 0


def _runtime_freshness(snapshot: Dict[str, Any]) -> tuple[str, bool, List[str]]:
    if not snapshot:
        return "MISSING", False, ["缺少 USDJPY 运行快照"]
    if not _credible_price(snapshot):
        return "NO_CREDIBLE_PRICE", False, ["运行快照缺少可信 bid/ask/current price，禁止自动入场"]
    fresh_limit, hard_limit = _runtime_thresholds()
    reasons: List[str] = []
    age = snapshot.get("runtimeAgeSeconds", snapshot.get("_fileAgeSeconds"))
    age_value = _num(age, -1.0)
    if bool(snapshot.get("fallback")):
        return "FALLBACK_BLOCKED", False, ["运行快照处于回退模式，禁止自动入场"]
    if age_value >= 0:
        if age_value > hard_limit:
            return "HARD_STALE", False, [f"运行快照严重陈旧：{age_value:.0f}s > {hard_limit:.0f}s"]
        if age_value > fresh_limit:
            reasons.append(f"运行快照轻微陈旧：{age_value:.0f}s，降为机会入场/小仓")
            return "SOFT_STALE", True, reasons
    if snapshot.get("runtimeFresh") is False:
        reasons.append("运行快照标记为不新鲜，降级观察")
        return "SOFT_STALE", True, reasons
    return "FRESH", True, ["运行快照通过"]


def _runtime_ok(snapshot: Dict[str, Any]) -> tuple[bool, List[str]]:
    _tier, ok, reasons = _runtime_freshness(snapshot)
    return ok, reasons


def _load_rsi_entry_diagnostics(runtime_dir: Path) -> Dict[str, Any]:
    diagnostics = first_json(runtime_dir, "QuantGod_USDJPYRsiEntryDiagnostics.json") or {}
    dashboard = focus_runtime_snapshot(runtime_dir) or {}
    embedded = dashboard.get("usdJpyRsiEntryDiagnostics")
    if isinstance(embedded, dict) and embedded:
        dashboard_age = _num(dashboard.get("_fileAgeSeconds"), 999999.0)
        diagnostics_age = _num(diagnostics.get("_fileAgeSeconds"), 999999.0)
        if not diagnostics or dashboard_age < diagnostics_age:
            result = dict(embedded)
            result.setdefault("_source", "QuantGod_Dashboard.json.usdJpyRsiEntryDiagnostics")
            result.setdefault("_dashboardFilePath", dashboard.get("_filePath"))
            result.setdefault("_fileAgeSeconds", dashboard.get("_fileAgeSeconds"))
            return result
    if diagnostics:
        return diagnostics
    return {}


def _rsi_diagnostic_ready(diagnostics: Dict[str, Any]) -> bool:
    state = str(diagnostics.get("state") or "").upper()
    if state == "READY_BUY_SIGNAL":
        return True
    rsi = diagnostics.get("rsi") if isinstance(diagnostics.get("rsi"), dict) else {}
    signal_direction = str(rsi.get("signalDirection") or diagnostics.get("direction") or "").upper()
    return bool(rsi.get("signalReady")) and signal_direction in {"BUY", "LONG"}


def _rsi_hard_gate(diagnostics: Dict[str, Any]) -> tuple[bool, List[str]]:
    if not diagnostics:
        return True, []
    state = str(diagnostics.get("state") or "").upper()
    if state not in HARD_RSI_DIAGNOSTIC_STATES:
        return True, []
    summary = diagnostics.get("summary") or diagnostics.get("stateZh") or state
    reasons = [f"EA RSI 诊断硬阻断：{summary}"]
    why = diagnostics.get("whyNoEntry") if isinstance(diagnostics.get("whyNoEntry"), list) else []
    for row in why[:2]:
        if isinstance(row, dict):
            detail = row.get("detail") or row.get("label") or row.get("code")
            if detail:
                reasons.append(str(detail))
    return False, reasons


def _fastlane_ok(quality: Dict[str, Any]) -> tuple[bool, List[str]]:
    if not quality.get("found"):
        return False, ["缺少 USDJPY 快通道质量证据"]
    state = str(quality.get("quality") or "MISSING").upper()
    if state not in FASTLANE_PASS_STATES:
        return False, [f"快通道质量未通过：{state}"]
    if quality.get("focusSymbolFound") is False:
        return False, ["快通道质量文件未包含 USDJPY"]
    if state == "EA_DASHBOARD_OK":
        return True, ["快通道质量降级可用：使用 HFM EA Dashboard 新鲜快照"]
    return True, ["快通道质量通过"]


def _is_live_route(item: PolicyItem) -> bool:
    return item.strategy == LIVE_ELIGIBLE_STRATEGY and str(item.direction).upper() == LIVE_ELIGIBLE_DIRECTION


def _is_live_eligible(item: PolicyItem) -> bool:
    return _is_live_route(item) and item.entryMode in {ENTRY_STANDARD, ENTRY_OPPORTUNITY} and bool(item.allowed)


def _trigger_state(plan: Dict[str, Any], direction: str) -> tuple[str, List[str], float, Dict[str, Any]]:
    items = plan.get("plans") or plan.get("triggers") or plan.get("items") or plan.get("decisions") or []
    if isinstance(items, dict):
        items = list(items.values())
    best = None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("symbol") or "").upper().startswith("USDJPY") and str(item.get("direction") or "").upper() == direction:
            best = item
            break
    if not best:
        return "MISSING", ["缺少 USDJPY 入场触发计划"], 0.0, {
            "status": "MISSING",
            "missingConfirmations": ["trigger_plan"],
            "score": 0.0,
        }
    status = str(best.get("status") or best.get("state") or best.get("entryMode") or "UNKNOWN").upper()
    score = best.get("triggerScore") or best.get("score") or 0.0
    try:
        score = float(score)
        if score <= 1.0:
            score *= 100
    except Exception:
        score = 0.0
    missing = best.get("missingConfirmations") or best.get("missing") or []
    if isinstance(missing, str):
        missing = [missing]
    confirmations = best.get("confirmations") if isinstance(best.get("confirmations"), dict) else {}
    tactical = {
        "status": status,
        "missingConfirmations": [str(item) for item in missing],
        "score": score,
        "confirmations": confirmations,
    }
    if status in {"READY_FOR_CONFIRMATION", "WAIT_TRIGGER_CONFIRMATION", "STANDARD_ENTRY", "PASS", "READY", "OPPORTUNITY_ENTRY"}:
        if not missing:
            return "TACTICAL_OK", ["入场触发允许：核心项全部通过"], score, tactical
        if len(missing) <= 1:
            return "TACTICAL_PARTIAL", ["入场触发部分确认：核心项通过，战术确认缺一项"], score, tactical
    reasons = best.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    blocked_detail = missing or reasons
    return "BLOCKED", ["入场触发阻断" if not blocked_detail else "入场触发阻断：" + "、".join([str(item) for item in blocked_detail[:3]])], score, tactical


def _sltp_available(plan: Dict[str, Any], strategy: str, direction: str) -> tuple[bool, List[str], Dict[str, Any]]:
    plans = plan.get("plans") or plan.get("items") or plan.get("calibrations") or []
    if isinstance(plans, dict):
        plans = list(plans.values())
    for item in plans if isinstance(plans, list) else []:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").upper()
        item_strategy = str(item.get("strategy") or "").strip()
        item_direction = str(item.get("direction") or "").upper()
        status = str(item.get("status") or "").upper()
        if sym.startswith("USDJPY") and item_strategy == strategy and item_direction == direction and status not in {"PAUSED", "BLOCKED", "INSUFFICIENT_DATA"}:
            return True, ["动态止盈止损可用"], item
    direction_plans = plan.get("dynamicSltpPlans") or []
    if isinstance(direction_plans, dict):
        direction_plans = list(direction_plans.values())
    for item in direction_plans if isinstance(direction_plans, list) else []:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").upper()
        item_direction = str(item.get("direction") or "").upper()
        risk_mode = str(item.get("riskMode") or "").upper()
        if sym.startswith("USDJPY") and item_direction == direction and risk_mode != "暂停":
            return True, ["动态止盈止损方向级计划可用"], item
    if plan:
        return False, ["动态止盈止损未匹配当前策略方向"], {}
    return False, ["缺少动态止盈止损计划"], {}


def _soften_live_route_trigger(status: str, strategy: str, direction: str, trigger_status: str, trigger_reasons: List[str]) -> tuple[str, List[str]]:
    if status != STATUS_RUNNABLE:
        return trigger_status, trigger_reasons
    if strategy != LIVE_ELIGIBLE_STRATEGY or str(direction).upper() != LIVE_ELIGIBLE_DIRECTION:
        return trigger_status, trigger_reasons
    if trigger_status != "BLOCKED":
        return trigger_status, trigger_reasons
    text = "；".join(str(item) for item in trigger_reasons)
    if "影子样本" not in text:
        return trigger_status, trigger_reasons
    return "TACTICAL_PARTIAL", [
        "RSI 实盘买入 forward 为正；影子方向池偏弱不阻断现有 EA 路线，仍由 EA 的 RSI、新闻、session、spread 风控二次确认。"
    ]


def _hard_gate(
    *,
    runtime_ok: bool,
    runtime_reasons: List[str],
    fast_ok: bool,
    fast_reasons: List[str],
    sltp_ok: bool,
    sltp_reasons: List[str],
    news_gate: Dict[str, Any],
    diagnostics: Dict[str, Any],
    spread_gate: Dict[str, Any],
) -> tuple[str, List[str]]:
    blockers: List[str] = []
    if not runtime_ok:
        blockers.extend(runtime_reasons)
    if not fast_ok:
        blockers.extend(fast_reasons)
    if not sltp_ok:
        blockers.extend(sltp_reasons)
    rsi_ok, rsi_reasons = _rsi_hard_gate(diagnostics)
    if not rsi_ok:
        blockers.extend(rsi_reasons)
    if spread_gate.get("hardBlock"):
        blockers.append(spread_gate.get("reasonZh") or "点差严重偏宽，硬阻断。")
    if news_gate.get("hardBlock") or str(news_gate.get("riskLevel") or "").upper() == "HARD":
        blockers.append(news_gate.get("reasonZh") or "高冲击新闻窗口，暂停 live。")
    return ("PASS", ["硬风控通过"]) if not blockers else ("BLOCKED", list(dict.fromkeys(blockers)))


def _apply_spread_gate_to_live_policy(
    *,
    entry_mode: str,
    allowed: bool,
    recommended_lot: float,
    strictness: str,
    reasons: List[str],
    spread_gate: Dict[str, Any],
    min_lot: float,
    max_lot: float,
    step: float,
) -> tuple[str, bool, float, str, List[str]]:
    tier = str(spread_gate.get("tier") or "UNKNOWN").upper()
    if spread_gate.get("hardBlock"):
        return ENTRY_BLOCKED, False, 0.0, "BLOCKED_SPREAD_HARD_GATE", [
            *reasons,
            spread_gate.get("reasonZh") or "点差严重偏宽，禁止入场。",
        ]
    if tier == "NORMAL" or entry_mode not in {ENTRY_STANDARD, ENTRY_OPPORTUNITY}:
        return entry_mode, allowed, recommended_lot, strictness, reasons
    adjusted_mode = ENTRY_OPPORTUNITY
    adjusted_strictness = "SPREAD_SOFT_WIDE_STAGE_DOWNGRADED"
    cap_value = spread_gate.get("maxCentOpportunityLot")
    cap = _num(cap_value, max_lot) if cap_value not in (None, "") else max_lot
    multiplier = max(0.0, min(1.0, _num(spread_gate.get("lotMultiplier"), 1.0)))
    lot = min(recommended_lot * multiplier, cap, max_lot)
    lot = _round_lot(lot, step=step, min_lot=min_lot, max_lot=max_lot) if allowed else 0.0
    return adjusted_mode, allowed, lot, adjusted_strictness, [
        *reasons,
        spread_gate.get("reasonZh") or "点差轻微偏宽：不硬阻断，降级/降仓。",
    ]


def _signal_quorum(
    *,
    status: str,
    score: float,
    trigger_status: str,
    runtime_tier: str,
    diagnostics: Dict[str, Any],
    news_gate: Dict[str, Any],
) -> Dict[str, Any]:
    rsi_ready = _rsi_diagnostic_ready(diagnostics)
    direction_signal = status == STATUS_RUNNABLE or score >= 45
    trigger_signal = trigger_status in {"TACTICAL_OK", "TACTICAL_PARTIAL"} or (
        trigger_status == "MISSING" and rsi_ready
    )
    market_context = runtime_tier in {"FRESH", "SOFT_STALE"} and not (
        news_gate.get("hardBlock") or str(news_gate.get("riskLevel") or "").upper() == "HARD"
    )
    components = {
        "directionSignal": bool(direction_signal),
        "triggerSignal": bool(trigger_signal),
        "marketContext": bool(market_context),
    }
    return {
        "signalQuorum": sum(1 for value in components.values() if value),
        "signalQuorumRequired": 2,
        "components": components,
        "rsiDiagnosticReady": rsi_ready,
        "missingTriggerWithoutRsiDiagnostic": trigger_status == "MISSING" and not rsi_ready,
    }


def _recommended_lot(score: float, entry_mode: str, *, max_lot: float, min_lot: float, step: float) -> float:
    risk_pct = _env_float("QG_AUTO_RISK_PER_TRADE_PCT", 0.5)
    opportunity_mult = _env_float("QG_AUTO_OPPORTUNITY_LOT_MULTIPLIER", 0.35)
    standard_mult = _env_float("QG_AUTO_STANDARD_LOT_MULTIPLIER", 1.0)
    equity = _env_float("QG_AUTO_ACCOUNT_EQUITY", 1000.0)
    base = max_lot * max(0.10, min(1.0, score / 100.0)) * max(0.05, min(2.0, risk_pct / 0.5))
    if entry_mode == ENTRY_OPPORTUNITY:
        base *= opportunity_mult
    elif entry_mode == ENTRY_STANDARD:
        base *= standard_mult
    else:
        base = 0.0
    return _round_lot(base, step=step, min_lot=min_lot, max_lot=max_lot)


def build_usdjpy_policy(runtime_dir: Path, *, write: bool = False, min_samples: int = 5) -> Dict[str, Any]:
    max_lot = _env_float("QG_AUTO_MAX_LOT", 2.0)
    min_lot = _env_float("QG_AUTO_MIN_LOT", 0.01)
    step = _env_float("QG_AUTO_LOT_STEP", 0.01)
    scoreboard = build_strategy_scoreboard(runtime_dir, min_samples=min_samples)
    candidate_signals = build_candidate_signals(runtime_dir, limit=20)
    snapshot = focus_runtime_snapshot(runtime_dir)
    quality = fastlane_quality(runtime_dir)
    trigger = entry_trigger_plan(runtime_dir)
    sltp = dynamic_sltp(runtime_dir)
    adaptive = adaptive_policy(runtime_dir)
    news_gate = classify_news_gate(snapshot or {})
    account_registry = mt5_account_registry()
    execution_report = _load_execution_quality_report(runtime_dir)
    runtime_tier, runtime_ok, runtime_reasons = _runtime_freshness(snapshot or {})
    fast_ok, fast_reasons = _fastlane_ok(quality)
    diagnostics = _load_rsi_entry_diagnostics(runtime_dir)
    spread_gate = _build_spread_gate(snapshot or {}, diagnostics)
    cent_sampling_gate = _cent_opportunity_sampling_gate(
        account_registry=account_registry,
        spread_gate=spread_gate,
        min_lot=min_lot,
        max_lot=max_lot,
        step=step,
    )
    policies: List[PolicyItem] = []
    for route in scoreboard.get("routes", []):
        status = route.get("status")
        strategy = route.get("strategy") or "UNKNOWN_STRATEGY"
        direction = route.get("direction") or "UNKNOWN"
        regime = route.get("regime") or "UNKNOWN"
        score = float(route.get("score") or 0.0)
        reasons = list(route.get("reasons") or [])
        reasons.extend(runtime_reasons)
        reasons.extend(fast_reasons)
        trigger_status, trigger_reasons, trigger_score, tactical_confirmations = _trigger_state(trigger, direction)
        trigger_status, trigger_reasons = _soften_live_route_trigger(status, strategy, direction, trigger_status, trigger_reasons)
        sltp_ok, sltp_reasons, sltp_item = _sltp_available(sltp, strategy, direction)
        reasons.extend(trigger_reasons)
        reasons.extend(sltp_reasons)
        hard_status, hard_reasons = _hard_gate(
            runtime_ok=runtime_ok,
            runtime_reasons=runtime_reasons,
            fast_ok=fast_ok,
            fast_reasons=fast_reasons,
            sltp_ok=sltp_ok,
            sltp_reasons=sltp_reasons,
            news_gate=news_gate,
            diagnostics=diagnostics if strategy == LIVE_ELIGIBLE_STRATEGY and str(direction).upper() == LIVE_ELIGIBLE_DIRECTION else {},
            spread_gate=spread_gate if strategy == LIVE_ELIGIBLE_STRATEGY and str(direction).upper() == LIVE_ELIGIBLE_DIRECTION else {"hardBlock": False},
        )
        quorum = _signal_quorum(
            status=str(status or ""),
            score=score,
            trigger_status=trigger_status,
            runtime_tier=runtime_tier,
            diagnostics=diagnostics if strategy == LIVE_ELIGIBLE_STRATEGY and str(direction).upper() == LIVE_ELIGIBLE_DIRECTION else {},
            news_gate=news_gate,
        )
        reasons.extend(hard_reasons if hard_status == "BLOCKED" else [])
        live_route = strategy == LIVE_ELIGIBLE_STRATEGY and str(direction).upper() == LIVE_ELIGIBLE_DIRECTION
        entry_mode = STATUS_WATCH_ONLY
        allowed = False
        strictness = "WATCH_ONLY_QUORUM"
        if status == STATUS_PAUSED:
            entry_mode = ENTRY_BLOCKED
            strictness = "BLOCKED_STRATEGY_PAUSED"
            reasons.append("策略方向近期表现为负，暂停")
        elif not live_route:
            strictness = "SHADOW_ONLY_NON_RSI_LIVE_ROUTE"
            reasons.append("非 RSI_Reversal LONG 不进入 MT5 live；只保留 shadow/replay/GA 研究。")
        elif hard_status != "PASS":
            entry_mode = ENTRY_BLOCKED
            strictness = "BLOCKED_HARD_RISK_GATE"
            reasons.append("硬风控未通过，禁止机会入场")
        elif quorum.get("missingTriggerWithoutRsiDiagnostic"):
            strictness = "WATCH_ONLY_TRIGGER_MISSING_NO_RSI_DIAGNOSTIC"
            reasons.append("缺少 trigger plan 且 EA RSI 诊断未显示 READY_BUY_SIGNAL，只能观察。")
        elif trigger_status == "TACTICAL_OK" and int(quorum["signalQuorum"]) == 3 and score >= 70:
            entry_mode = ENTRY_STANDARD
            allowed = True
            strictness = "STANDARD_HARD_GATE_PASS_QUORUM_3"
        elif int(quorum["signalQuorum"]) >= 2 and score >= 45:
            entry_mode = ENTRY_OPPORTUNITY
            allowed = True
            strictness = "OPPORTUNITY_HARD_GATE_PASS_QUORUM_2_OF_3"
            reasons.append("硬风控通过，2/3 信号 quorum 达标，允许小仓机会观察")
        else:
            reasons.append("硬风控通过但 quorum/分数不足，保持观察不入场")
        if entry_mode == ENTRY_STANDARD and runtime_tier == "SOFT_STALE":
            entry_mode = ENTRY_OPPORTUNITY
            strictness = "RUNTIME_SOFT_STALE_STAGE_DOWNGRADED"
            reasons.append("runtime 轻微陈旧：标准入场降为机会入场并由仓位控制降风险。")
        lot = _recommended_lot(score, entry_mode, max_lot=max_lot, min_lot=min_lot, step=step)
        if live_route:
            entry_mode, allowed, lot, strictness, reasons = _apply_spread_gate_to_live_policy(
                entry_mode=entry_mode,
                allowed=allowed,
                recommended_lot=lot,
                strictness=strictness,
                reasons=reasons,
                spread_gate=spread_gate,
                min_lot=min_lot,
                max_lot=max_lot,
                step=step,
            )
            entry_mode, allowed, lot, strictness, reasons = apply_news_gate_to_live_policy(
                entry_mode=entry_mode,
                allowed=allowed,
                recommended_lot=lot,
                strictness=strictness,
                reasons=reasons,
                news_gate=news_gate,
                min_lot=min_lot,
                max_lot=max_lot,
                step=step,
            )
            entry_mode, allowed, lot, strictness, reasons, policy_cent_sampling_gate = _apply_cent_sampling_gate_to_live_policy(
                entry_mode=entry_mode,
                allowed=allowed,
                recommended_lot=lot,
                strictness=strictness,
                reasons=reasons,
                sampling_gate=cent_sampling_gate,
                hard_status=hard_status,
                runtime_tier=runtime_tier,
                news_gate=news_gate,
                spread_gate=spread_gate,
                min_lot=min_lot,
                max_lot=max_lot,
                step=step,
            )
        else:
            reasons.append("新闻风险只记录到 shadow / replay，不阻断 MT5 模拟策略。")
            policy_cent_sampling_gate = {}
        policies.append(PolicyItem(
            symbol=FOCUS_SYMBOL,
            strategy=strategy,
            direction=direction,
            regime=regime,
            entryMode=entry_mode,
            allowed=allowed,
            recommendedLot=lot,
            maxLot=max_lot,
            score=round(score, 2),
            entryStrictness=strictness,
            exitMode="LET_PROFIT_RUN" if allowed else "NO_POSITION",
            breakevenDelayR=float(sltp_item.get("breakevenDelayR", 0.9)) if sltp_item else 0.9,
            trailStartR=float(sltp_item.get("trailStartR", 1.4)) if sltp_item else 1.4,
            timeStopBars=int(float(sltp_item.get("timeStopBars", 6))) if sltp_item else 6,
            reasons=list(dict.fromkeys([str(r) for r in reasons if r])),
            newsGate=dict(news_gate),
            hardGateStatus=hard_status if live_route else "SHADOW_ONLY",
            hardGateReasons=hard_reasons,
            runtimeFreshnessTier=runtime_tier,
            signalQuorum=int(quorum["signalQuorum"]),
            signalQuorumRequired=int(quorum["signalQuorumRequired"]),
            signalComponents=dict(quorum["components"]),
            tacticalConfirmations={**tactical_confirmations, "policyTriggerStatus": trigger_status, "triggerScore": trigger_score},
            entryDecision=entry_mode,
            spreadGate=dict(spread_gate) if live_route else {},
            centSamplingGate=policy_cent_sampling_gate,
        ))

    policies.sort(key=lambda item: (item.entryMode == ENTRY_BLOCKED, -item.score, -item.recommendedLot, item.strategy))
    top_shadow_policy = policies[0].to_dict() if policies else None
    live_route_candidates = [item for item in policies if _is_live_route(item)]
    live_eligible_candidates = [item for item in policies if _is_live_eligible(item)]
    top_live_policy = live_eligible_candidates[0].to_dict() if live_eligible_candidates else None
    live_recovery_candidate = live_route_candidates[0].to_dict() if live_route_candidates else None
    top_policy = top_live_policy or live_recovery_candidate or top_shadow_policy
    usd_deployment_gate = _usd_deployment_gate(
        top_policy=top_policy or {},
        spread_gate=spread_gate,
        news_gate=news_gate,
        runtime_tier=runtime_tier,
        fast_ok=fast_ok,
        account_registry=account_registry,
        execution_report=execution_report,
    )
    payload = {
        "schema": "quantgod.usdjpy_auto_execution_policy.v1",
        "generatedAt": utc_now_iso(),
        "strategyCatalogVersion": STRATEGY_CATALOG_VERSION,
        "focusOnly": True,
        "symbol": FOCUS_SYMBOL,
        "allowedSymbols": [FOCUS_SYMBOL],
        "ignoredNonFocusSymbols": True,
        "marketRegime": (snapshot or {}).get("regime") or (snapshot or {}).get("marketRegime") or "UNKNOWN",
        "policyConstraints": {
            "focusOnly": True,
            "newStrategiesShadowOnlyUntilEvidencePass": True,
            "requiresBacktestBeforeLive": True,
            "requiresGovernanceBeforeLive": True,
            "requiresAutonomousGovernance": True,
            "operatorApprovalRequired": False,
            "unattendedLiveExpansionAllowed": True,
            "liveScopeExpansionMode": "autonomous_governance_stage_gated",
            "autoApplyAllowed": "stage_gated",
            "patchWritable": True,
            "liveMutationAllowed": False,
            "rsiLiveRoutePreserved": True,
            "newsGateDefaultMode": news_gate.get("mode"),
            "ordinaryNewsHardBlocksLive": False,
            "highImpactNewsHardBlocksLive": True,
        },
        "newsGate": news_gate,
        "spreadGate": spread_gate,
        "accountRegistry": account_registry,
        "usdDeploymentGate": usd_deployment_gate,
        "accountLanePolicy": {
            "centAccountCanUseOpportunityEntry": True,
            "usdAccountOpportunityEntryMode": "PAPER_MIRROR_ONLY",
            "usdAccountLiveEntryModes": ["STANDARD_ENTRY"],
            "softWideSpreadCentMode": "OPPORTUNITY_ENTRY_SMALL_LOT",
            "softWideSpreadUsdMode": "PAPER_MIRROR_ONLY",
            "usdDeploymentLiveMode": "STANDARD_ENTRY_NORMAL_SPREAD_NEWS_NONE_ONLY",
            "usdDeploymentTargetStage": usd_deployment_gate.get("targetStage"),
            "usdDeploymentLiveAllowed": bool(usd_deployment_gate.get("liveAllowed")),
            "centOpportunitySamplingGate": cent_sampling_gate,
            "centOpportunityLotCap": cent_sampling_gate.get("maxOpportunityLot"),
            "centOpportunityLiveAccountOnly": True,
            "externalMarketRemoved": True,
        },
        "maxLot": max_lot,
        "standardEntryCount": sum(1 for item in policies if item.entryMode == ENTRY_STANDARD),
        "opportunityEntryCount": sum(1 for item in policies if item.entryMode == ENTRY_OPPORTUNITY),
        "watchOnlyCount": sum(1 for item in policies if item.entryMode == STATUS_WATCH_ONLY),
        "blockedCount": sum(1 for item in policies if item.entryMode == ENTRY_BLOCKED),
        "topPolicy": top_policy,
        "topShadowPolicy": top_shadow_policy,
        "topLiveEligiblePolicy": top_live_policy,
        "liveRecoveryCandidate": live_recovery_candidate,
        "strategies": [item.to_dict() for item in policies],
        "evidence": {
            "runtimeOk": runtime_ok,
            "runtimeFreshnessTier": runtime_tier,
            "fastlaneOk": fast_ok,
            "triggerPlanFound": bool(trigger),
            "dynamicSltpFound": bool(sltp),
            "adaptivePolicyFound": bool(adaptive),
            "scoreboardRoutes": len(scoreboard.get("routes", [])),
            "candidateSignalCount": candidate_signals.get("count", 0),
            "topLiveEligiblePolicyFound": bool(top_live_policy),
            "topShadowPolicyStrategy": (top_shadow_policy or {}).get("strategy"),
            "newsGateMode": news_gate.get("mode"),
            "newsRiskLevel": news_gate.get("riskLevel"),
            "newsHardBlock": bool(news_gate.get("hardBlock")),
            "spreadGateTier": spread_gate.get("tier"),
            "spreadGateHardBlock": bool(spread_gate.get("hardBlock")),
            "usdDeploymentLiveAllowed": bool(usd_deployment_gate.get("liveAllowed")),
            "usdDeploymentTargetStage": usd_deployment_gate.get("targetStage"),
            "centOpportunityLotCap": cent_sampling_gate.get("maxOpportunityLot"),
            "decisionModel": "HARD_GATES_PLUS_SIGNAL_QUORUM_V1",
            "hardGatePassCount": sum(1 for item in policies if item.hardGateStatus == "PASS"),
            "quorumEligibleCount": sum(1 for item in policies if int(item.signalQuorum) >= int(item.signalQuorumRequired)),
        },
        "candidateSignals": candidate_signals.get("signals", []),
        "scoreboard": scoreboard,
        "safety": dict(READ_ONLY_SAFETY),
    }
    assert_no_secret_or_execution_flags(payload)
    if write:
        adaptive_dir = runtime_dir / "adaptive"
        adaptive_dir.mkdir(parents=True, exist_ok=True)
        policy_path = adaptive_dir / "QuantGod_USDJPYAutoExecutionPolicy.json"
        policy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        ledger_path = adaptive_dir / "QuantGod_USDJPYAutoExecutionPolicyLedger.csv"
        is_new = not ledger_path.exists()
        with ledger_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["generatedAt", "symbol", "standard", "opportunity", "blocked", "topStrategy", "topMode", "topLot"])
            if is_new:
                writer.writeheader()
            top = payload.get("topPolicy") or {}
            writer.writerow({
                "generatedAt": payload["generatedAt"],
                "symbol": FOCUS_SYMBOL,
                "standard": payload["standardEntryCount"],
                "opportunity": payload["opportunityEntryCount"],
                "blocked": payload["blockedCount"],
                "topStrategy": top.get("strategy", ""),
                "topMode": top.get("entryMode", ""),
                "topLot": top.get("recommendedLot", 0),
            })
    return payload
