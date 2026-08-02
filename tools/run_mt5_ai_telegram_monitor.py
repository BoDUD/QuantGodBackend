#!/usr/bin/env python3
"""Read-only MT5 AI monitor with Telegram push-only advisory delivery.

The monitor follows the Web3-style loop of source monitoring -> AI summary ->
push notification, but keeps QuantGod trading safety intact: no orders, no
position changes, no preset mutation, no Telegram commands, and no kill-switch
override.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
for candidate in (str(REPO_ROOT), str(TOOLS_DIR)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from ai_analysis.analysis_service_v2 import AnalysisServiceV2, phase3_ai_safety  # noqa: E402
from ai_analysis.deepseek_mt5_advisor import (  # noqa: E402
    DeepSeekAdvisorError,
    DeepSeekMt5Advisor,
    load_deepseek_config,
)
from notify.messages import render  # noqa: E402
from telegram_digest import build_digest, contains_execution_language  # noqa: E402
from telegram_gateway_cli import dispatch_cli_text  # noqa: E402
from telegram_notifier.config import load_config  # noqa: E402
from telegram_notifier.records import record_notification  # noqa: E402
from telegram_notifier.safety import (  # noqa: E402
    assert_telegram_safety,
)
from telegram_notifier.safety import (  # noqa: E402
    safety_payload as telegram_safety_payload,
)

MODE = "QUANTGOD_MT5_AI_TELEGRAM_MONITOR_V1"
DEFAULT_SYMBOLS = "USDJPYc"
DEFAULT_TIMEFRAMES = "M15,H1,H4,D1"
DEFAULT_MIN_INTERVAL_SECONDS = 15 * 60
DEFAULT_MIN_CONFIDENCE_PCT = float(os.environ.get("QG_MT5_AI_MONITOR_MIN_CONFIDENCE_PCT", "60"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def format_report_time(value: Any) -> str:
    text = str(value or utc_now_iso()).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        tokyo = parsed.astimezone(timezone(timedelta(hours=9)))
        return tokyo.strftime("%Y-%m-%d %H:%M:%S 东京时间")
    except Exception:
        return text


def monitor_safety() -> dict[str, Any]:
    payload = {
        "mode": MODE,
        "localOnly": True,
        "readOnlyDataPlane": True,
        "advisoryOnly": True,
        "notificationPushOnly": True,
        "telegramCommandExecutionAllowed": False,
        "telegramWebhookReceiverAllowed": False,
        "orderSendAllowed": False,
        "closeAllowed": False,
        "cancelAllowed": False,
        "credentialStorageAllowed": False,
        "livePresetMutationAllowed": False,
        "canOverrideKillSwitch": False,
        "canMutateGovernanceDecision": False,
        "canPromoteOrDemoteRoute": False,
        "automatedTradingAllowed": False,
    }
    payload["ai"] = phase3_ai_safety()
    return payload


def parse_csv_list(value: str | None, fallback: str) -> list[str]:
    raw = value if value not in (None, "") else fallback
    items: list[str] = []
    for part in str(raw).split(","):
        item = part.strip()
        if item and item not in items:
            items.append(item)
    return items


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def runtime_dir_from_args(args: argparse.Namespace) -> Path:
    value = args.runtime_dir or os.environ.get("QG_RUNTIME_DIR") or os.environ.get("QG_MT5_FILES_DIR")
    return Path(value or (REPO_ROOT / "runtime")).expanduser().resolve()


def monitor_state_path(args: argparse.Namespace) -> Path:
    if args.state_file:
        return Path(args.state_file).expanduser().resolve()
    return runtime_dir_from_args(args) / "QuantGod_MT5AiTelegramMonitorState.json"


def latest_report_path(args: argparse.Namespace) -> Path:
    return runtime_dir_from_args(args) / "QuantGod_MT5AiTelegramMonitorLatest.json"


def summarize_source(report: dict[str, Any]) -> dict[str, Any]:
    snapshot = report.get("snapshot") if isinstance(report.get("snapshot"), dict) else {}
    current_price = snapshot.get("current_price") if isinstance(snapshot.get("current_price"), dict) else {}
    positions = snapshot.get("open_positions") if isinstance(snapshot.get("open_positions"), list) else []
    risk = report.get("risk") if isinstance(report.get("risk"), dict) else {}
    technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
    return {
        "snapshotSource": snapshot.get("source", ""),
        "fallback": bool(snapshot.get("fallback", False)),
        "runtimeFresh": bool(snapshot.get("runtimeFresh", False)),
        "runtimeAgeSeconds": snapshot.get("runtimeAgeSeconds"),
        "price": current_price,
        "openPositions": len(positions),
        "riskLevel": risk.get("risk_level", "unknown"),
        "killSwitchActive": bool(risk.get("kill_switch_active", False)),
        "technicalDirection": technical.get("direction") or ((technical.get("trend") or {}).get("consensus") if isinstance(technical.get("trend"), dict) else ""),
    }


def decision_summary(report: dict[str, Any]) -> dict[str, Any]:
    decision = report.get("decision") if isinstance(report.get("decision"), dict) else {}
    return {
        "action": str(decision.get("action") or "HOLD"),
        "confidence": decision.get("confidence"),
        "reasoning": str(decision.get("reasoning") or ""),
        "keyFactors": decision.get("key_factors") if isinstance(decision.get("key_factors"), list) else [],
        "entryPrice": decision.get("entry_price"),
        "stopLoss": decision.get("stop_loss"),
        "takeProfit": decision.get("take_profit"),
        "riskRewardRatio": decision.get("risk_reward_ratio"),
        "positionSizeSuggestion": decision.get("position_size_suggestion"),
        "debateSummary": decision.get("debate_summary") if isinstance(decision.get("debate_summary"), dict) else {},
    }


def event_signature(report: dict[str, Any]) -> str:
    advice = report.get("deepseek_advice") if isinstance(report.get("deepseek_advice"), dict) else {}
    seed = {
        "symbol": report.get("symbol"),
        "decision": decision_summary(report),
        "source": summarize_source(report),
        "deepseek": {
            "ok": bool(advice.get("ok")),
            "status": advice.get("status"),
            "model": advice.get("model"),
            "headline": ((advice.get("advice") or {}).get("headline") if isinstance(advice.get("advice"), dict) else ""),
            "verdict": ((advice.get("advice") or {}).get("verdict") if isinstance(advice.get("advice"), dict) else ""),
        },
    }
    raw = json.dumps(seed, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _confidence_to_pct(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric * 100.0 if numeric <= 1.0 else numeric


def unsafe_advisory_message_reason(message: str) -> str | None:
    """Last-resort block for fake/stale text before Telegram delivery."""
    text = str(message or "").lower()
    blocked_patterns = (
        ("mock decision", "mock_decision_text"),
        ("mock_fallback", "mock_fallback_text"),
        ("fallback evidence", "fallback_evidence_text"),
        ("runtime_files_missing_or_stale", "stale_runtime_text"),
        ("运行快照不新鲜", "stale_runtime_text"),
        ("回退模式", "fallback_evidence_text"),
    )
    for needle, reason in blocked_patterns:
        if needle in text:
            return reason
    if contains_execution_language(message):
        return "execution_language_blocked"
    return None


def fmt_value(value: Any, fallback: str = "--") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return str(value)


def fmt_price(value: Any, digits: int = 2, fallback: str = "--") -> str:
    """Format a price with fixed decimal places (keeps trailing zeros)."""
    if value is None or value == "":
        return fallback
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def first_text(*values: Any, fallback: str = "暂无") -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            if parts:
                return "；".join(parts[:3])
            continue
        text = str(value).strip()
        if text:
            return text
    return fallback


def truncate_text(value: Any, limit: int = 150, fallback: str = "暂无") -> str:
    text = translate_common_text(first_text(value, fallback=fallback)).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def translate_common_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    exact = {
        "Advisory only.": "仅生成建议，不执行任何交易。",
        "DecisionAgent V2 combines Technical/Risk/News/Sentiment evidence plus Bull/Bear debate. It remains advisory only.": "智能决策综合技术面、风险、新闻、情绪与多空辩论证据；结果仅作为建议，不自动执行。",
        "Bull case is weak; wait for clearer upside evidence.": "多头证据偏弱，等待更清晰的上行确认。",
        "Bear case is weak; no strong downside evidence.": "空头证据偏弱，暂无明显下行确认。",
        "No high-impact news evidence found in local snapshot": "本地快照未发现高影响新闻风险。",
        "No high-impact news evidence.": "未发现高影响新闻风险。",
        "Sentiment is derived from local snapshot fields; missing fields default to neutral.": "情绪来自本地快照字段；缺失字段按中性处理。",
        "Local sentiment is neutral.": "本地情绪为中性。",
        "No active local risk blocker found in fallback inputs.": "本地输入未发现正在生效的风险阻断。",
        "Fallback technical summary from local OHLC bars; LLM output unavailable or invalid.": "基于本地价格序列生成技术摘要；智能模型输出不可用或格式无效。",
        "Fallback risk summary from local dashboard/runtime state; LLM output unavailable or invalid.": "基于本地仪表盘与运行状态生成风险摘要；智能模型输出不可用或格式无效。",
        "none": "无",
        "golden_cross": "金叉",
        "death_cross": "死叉",
        "overbought": "超买",
        "oversold": "超卖",
        "not_evaluated_fallback": "回退模式未评估",
        "action_hold": "本地与模型结论为观望，不生成入场建议。",
        "fusion_hold": "融合门禁保持观望，不生成入场建议。",
    }
    if text in exact:
        return exact[text]
    replacements = {
        "Bull conviction": "多头强度",
        "Bear conviction": "空头强度",
        "Risk level": "风险等级",
        "Technical direction": "技术方向",
        "bullish": "偏多",
        "bearish": "偏空",
        "neutral": "中性",
        "medium": "中",
        "critical": "极高",
        "high": "高",
        "low": "低",
        "unknown": "未知",
        "fallback": "回退",
        "runtime": "运行时",
        "news": "新闻",
        "sentiment": "情绪",
    }
    out = text
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out


def chinese_action(action: Any) -> str:
    normalized = str(action or "HOLD").upper()
    labels = {
        "BUY": "偏多观察，等待程序风控确认",
        "SELL": "偏空观察，等待程序风控确认",
        "HOLD": "观望，不开新仓",
    }
    return labels.get(normalized, normalized)


def chinese_trigger(reason: Any) -> str:
    text = str(reason or "").strip()
    if text == "force":
        return "手动强制复核"
    if text == "changed":
        return "信号或证据变化"
    if text == "first_seen":
        return "首次发现"
    if text == "interval_elapsed":
        return "定时复核"
    if text.startswith("dedup_wait_"):
        return "重复信号等待中"
    return translate_common_text(text) or "未知"


def chinese_source(value: Any) -> str:
    normalized = str(value or "unknown").strip()
    labels = {
        "hfm_ea_runtime": "HFM 程序运行快照",
        "dashboard_runtime": "仪表盘运行快照",
        "runtime_files": "本地运行文件",
        "phase3_v2_fallback_snapshot": "智能分析回退快照",
        "mt5_python_unavailable": "行情接口不可用，使用安全回退",
        "unknown": "未知来源",
    }
    return labels.get(normalized, translate_common_text(normalized))


def chinese_timeframes(items: list[Any]) -> str:
    labels = {
        "M1": "1分钟",
        "M5": "5分钟",
        "M15": "15分钟",
        "M30": "30分钟",
        "H1": "1小时",
        "H4": "4小时",
        "D1": "日线",
    }
    values = items or [part.strip() for part in DEFAULT_TIMEFRAMES.split(",")]
    return "、".join(labels.get(str(item), str(item)) for item in values)


def chinese_risk(value: Any) -> str:
    normalized = str(value or "unknown").lower()
    labels = {
        "low": "低",
        "medium": "中",
        "medium_high": "中高",
        "high": "高",
        "critical": "极高",
        "unknown": "未知",
    }
    return labels.get(normalized, str(value or "未知"))


def chinese_direction(value: Any) -> str:
    normalized = str(value or "unknown").lower()
    labels = {
        "bullish": "偏多",
        "bearish": "偏空",
        "neutral": "中性",
        "mixed_neutral": "混合中性",
        "mixed_bullish": "混合偏多",
        "mixed_bearish": "混合偏空",
        "neutral_bullish": "中性偏多",
        "neutral_bearish": "中性偏空",
        "up": "上行",
        "down": "下行",
        "range": "震荡",
        "unknown": "未知",
    }
    return labels.get(normalized, str(value or "未知"))


def confidence_pct(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "--"
    if numeric <= 1:
        numeric *= 100
    return f"{numeric:.0f}%"


def numeric_value(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def signal_grade(decision: dict[str, Any], source: dict[str, Any]) -> str:
    if evidence_blocks_trade(source):
        return "数据复核级"
    action = str(decision.get("action") or "HOLD").upper()
    if action == "HOLD":
        return "观察级"
    confidence = numeric_value(decision.get("confidence")) or 0.0
    if confidence <= 1:
        confidence *= 100
    risk = str(source.get("riskLevel") or "unknown").lower()
    if confidence >= 75 and risk in {"low", "medium"}:
        return "A 级"
    if confidence >= 55 and risk in {"low", "medium"}:
        return "B 级"
    return "C 级"


def evidence_blocks_trade(source: dict[str, Any]) -> bool:
    return bool(source.get("fallback")) or not bool(source.get("runtimeFresh"))


def evidence_quality_line(source: dict[str, Any]) -> str:
    if source.get("fallback"):
        return "回退证据：行情或账户快照不可直接作为入场依据。"
    if not source.get("runtimeFresh"):
        return "证据过期：需要等待新的程序运行快照。"
    return "运行证据有效：可进入观察复核，但仍不代表自动入场。"


def target_plan(decision: dict[str, Any]) -> tuple[str, str, str]:
    action = str(decision.get("action") or "HOLD").upper()
    entry = numeric_value(decision.get("entryPrice"))
    take_profit = numeric_value(decision.get("takeProfit"))
    if action not in {"BUY", "SELL"} or entry is None or take_profit is None:
        return ("未生成", "未生成", "未生成")
    distance = take_profit - entry
    first = entry + distance * 0.33
    second = entry + distance * 0.66
    return (fmt_value(first), fmt_value(second), fmt_value(take_profit))


def advisory_plan_lines(decision: dict[str, Any], source: dict[str, Any]) -> list[str]:
    action = str(decision.get("action") or "HOLD").upper()
    price = source.get("price") if isinstance(source.get("price"), dict) else {}
    reference_price = decision.get("entryPrice") or price.get("ask") or price.get("bid")
    lot = decision.get("positionSizeSuggestion")
    target_one, target_two, target_three = target_plan(decision)
    if evidence_blocks_trade(source):
        return [
            "计划状态：暂停，仅允许观察复核。",
            f"暂停原因：{evidence_quality_line(source)}",
            "入场区间：不生成，等待新鲜运行快照后重算。",
            "目标一：不生成",
            "目标二：不生成",
            "目标三：不生成",
            "防守位置：不生成",
            f"仓位上限：{fmt_value(lot, '0.01')} 手，仅作为系统默认上限展示，不构成下单建议。",
            "复查条件：程序快照恢复新鲜、新闻过滤正常、点差正常、熔断未触发、治理状态允许观察。",
        ]
    if action == "BUY":
        entry = f"等待程序风控门禁确认后才考虑做多；参考价 {fmt_value(reference_price)}"
        invalidation = "跌破防守价、新闻隔离开启、熔断开启、点差异常或程序风控拒绝。"
    elif action == "SELL":
        entry = f"等待程序风控门禁确认后才考虑做空；参考价 {fmt_value(reference_price)}"
        invalidation = "突破防守价、新闻隔离开启、熔断开启、点差异常或程序风控拒绝。"
    else:
        entry = "暂不建议主动入场；等待交易时段、新闻过滤、点差、治理状态和信号方向同时改善。"
        invalidation = "如果证据继续不足或风险升高，保持观望；不追单、不手动补单。"
    return [
        f"建议方向：{chinese_action(action)}",
        f"入场区间：{entry}",
        f"目标一：{target_one}",
        f"目标二：{target_two}",
        f"目标三：{target_three}",
        f"防守位置：{fmt_value(decision.get('stopLoss'), '未生成；无交易信号时不设置')}",
        f"盈亏比：{fmt_value(decision.get('riskRewardRatio'), '未评估')}",
        f"仓位上限：{fmt_value(lot, '0.01')} 手，仅作为程序风控参考",
        f"失效条件：{invalidation}",
    ]


def extract_ai_context(report: dict[str, Any]) -> dict[str, str]:
    bull = report.get("bull_case") if isinstance(report.get("bull_case"), dict) else {}
    bear = report.get("bear_case") if isinstance(report.get("bear_case"), dict) else {}
    news = report.get("news") if isinstance(report.get("news"), dict) else {}
    sentiment = report.get("sentiment") if isinstance(report.get("sentiment"), dict) else {}
    decision = report.get("decision") if isinstance(report.get("decision"), dict) else {}
    debate = decision.get("debate_summary") if isinstance(decision.get("debate_summary"), dict) else {}
    return {
        "bull": truncate_text(bull.get("thesis") or debate.get("bull_thesis") or bull.get("reasoning"), 150),
        "bear": truncate_text(bear.get("thesis") or debate.get("bear_thesis") or bear.get("reasoning"), 150),
        "news": truncate_text(news.get("reasoning") or news.get("risk_level") or news.get("macro_bias"), 130),
        "sentiment": truncate_text(sentiment.get("reasoning") or sentiment.get("bias") or sentiment.get("score"), 130),
    }


def factor_lines(factors: list[Any]) -> list[str]:
    if not factors:
        return ["1. 暂无关键因子"]
    return [f"{index}. {translate_common_text(item)}" for index, item in enumerate(factors[:5], start=1)]


def technical_structure_lines(report: dict[str, Any]) -> list[str]:
    technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
    trend = technical.get("trend") if isinstance(technical.get("trend"), dict) else {}
    indicators = technical.get("indicators") if isinstance(technical.get("indicators"), dict) else {}
    levels = technical.get("key_levels") if isinstance(technical.get("key_levels"), dict) else {}
    ma = indicators.get("ma_cross") if isinstance(indicators.get("ma_cross"), dict) else {}
    rsi = indicators.get("rsi") if isinstance(indicators.get("rsi"), dict) else {}
    support = levels.get("support") if isinstance(levels.get("support"), list) else []
    resistance = levels.get("resistance") if isinstance(levels.get("resistance"), list) else []
    return [
        f"15分钟趋势：{chinese_direction(trend.get('m15'))}",
        f"1小时趋势：{chinese_direction(trend.get('h1'))}",
        f"4小时趋势：{chinese_direction(trend.get('h4'))}",
        f"日线趋势：{chinese_direction(trend.get('d1'))}",
        f"均线信号：{translate_common_text(ma.get('signal') or '无明显交叉')}",
        f"相对强弱：{fmt_value(rsi.get('h1'))}；区域：{translate_common_text(rsi.get('zone') or '未知')}",
        f"关键压力：{', '.join(fmt_value(item) for item in resistance[:3]) or '暂无'}",
        f"关键支撑：{', '.join(fmt_value(item) for item in support[:3]) or '暂无'}",
    ]


def risk_lines(report: dict[str, Any]) -> list[str]:
    risk = report.get("risk") if isinstance(report.get("risk"), dict) else {}
    factors = risk.get("factors") if isinstance(risk.get("factors"), list) else []
    if not factors:
        return ["1. 暂无本地风险阻断证据"]
    lines: list[str] = []
    for index, item in enumerate(factors[:5], start=1):
        if isinstance(item, dict):
            severity = chinese_risk(item.get("severity"))
            detail = translate_common_text(item.get("detail") or item.get("factor") or "风险因子")
            lines.append(f"{index}. {severity}：{detail}")
        else:
            lines.append(f"{index}. {translate_common_text(item)}")
    return lines


def parse_iso_seconds(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def should_notify(state: dict[str, Any], *, symbol: str, signature: str, now_epoch: float, min_interval_seconds: int, force: bool) -> tuple[bool, str]:
    if force:
        return True, "force"
    symbols = state.get("symbols") if isinstance(state.get("symbols"), dict) else {}
    previous = symbols.get(symbol) if isinstance(symbols.get(symbol), dict) else {}
    if previous.get("signature") != signature:
        return True, "changed"
    last_epoch = parse_iso_seconds(previous.get("lastNotifiedAt"))
    if last_epoch is None:
        return True, "first_seen"
    remaining = min_interval_seconds - int(now_epoch - last_epoch)
    if remaining <= 0:
        return True, "interval_elapsed"
    return False, f"dedup_wait_{remaining}s"


def advisory_push_gate(report: dict[str, Any], *, min_confidence_pct: float = DEFAULT_MIN_CONFIDENCE_PCT) -> tuple[bool, str]:
    """Return whether a report is allowed to become a Telegram advisory push.

    This gate is intentionally stricter than the renderer. It prevents fallback,
    mock, stale, or non-validated AI output from being formatted as a live-looking
    advisory. The notification remains advisory-only even when this passes.
    """
    source = summarize_source(report)
    if bool(source.get("fallback")):
        return False, "fallback_evidence"
    if not bool(source.get("runtimeFresh")):
        return False, "runtime_not_fresh"
    if bool(source.get("killSwitchActive")):
        return False, "kill_switch_active"
    if str(source.get("riskLevel") or "unknown").lower() in {"high", "critical"}:
        return False, "risk_too_high"

    decision = decision_summary(report)
    action = str(decision.get("action") or "HOLD").upper()
    if action not in {"BUY", "SELL"}:
        return False, "action_hold"

    confidence = _confidence_to_pct(decision.get("confidence"))
    if confidence < float(min_confidence_pct):
        return False, f"confidence_below_{float(min_confidence_pct):.0f}"

    deepseek = report.get("deepseek_advice") if isinstance(report.get("deepseek_advice"), dict) else {}
    validation = deepseek.get("validation") if isinstance(deepseek.get("validation"), dict) else {}
    if not deepseek.get("ok"):
        return False, "deepseek_not_available"
    if validation.get("status") != "pass":
        return False, f"deepseek_validation_{validation.get('status') or 'unknown'}"

    fusion = report.get("advisory_fusion") if isinstance(report.get("advisory_fusion"), dict) else {}
    final_action = str(fusion.get("finalAction") or "HOLD").upper()
    expected = "WATCH_LONG" if action == "BUY" else "WATCH_SHORT"
    if final_action != expected:
        return False, f"fusion_{final_action.lower()}"
    return True, "passed"


def observation_push_gate(report: dict[str, Any]) -> tuple[bool, str]:
    """Return whether a non-trade AI observation summary can be pushed.

    This is intentionally weaker than ``advisory_push_gate`` but still blocks
    fake, stale, unsafe, or non-validated evidence. It is used when the final
    answer is HOLD so the operator still receives a Chinese analysis summary
    without making it look like a live entry signal.
    """
    source = summarize_source(report)
    if bool(source.get("fallback")):
        return False, "fallback_evidence"
    if not bool(source.get("runtimeFresh")):
        return False, "runtime_not_fresh"

    deepseek = report.get("deepseek_advice") if isinstance(report.get("deepseek_advice"), dict) else {}
    validation = deepseek.get("validation") if isinstance(deepseek.get("validation"), dict) else {}
    if not deepseek.get("ok"):
        return False, "deepseek_not_available"
    if validation.get("status") != "pass":
        return False, f"deepseek_validation_{validation.get('status') or 'unknown'}"
    return True, "observation_passed"


def build_observation_message(report: dict[str, Any], *, gate_reason: str) -> str:
    """Render a Chinese HOLD/blocked observation summary for Telegram."""
    decision = decision_summary(report)
    source = summarize_source(report)
    symbol = str(report.get("symbol") or "UNKNOWN")
    timeframes = report.get("timeframes") if isinstance(report.get("timeframes"), list) else []
    advice, deepseek_payload = deepseek_advice(report)
    advice = advice or {}
    fusion = report.get("advisory_fusion") if isinstance(report.get("advisory_fusion"), dict) else {}
    confidence = advice.get("confidencePct") or f"{_confidence_to_pct(decision.get('confidence')):.0f}%"
    verdict = advice.get("verdict") or chinese_action(decision.get("action"))
    headline = advice.get("headline") or decision.get("reasoning") or "AI 已完成只读观察。"
    watch_points = advice.get("watchPoints") if isinstance(advice.get("watchPoints"), list) else []
    risk_notes = advice.get("riskNotes") if isinstance(advice.get("riskNotes"), list) else []
    fusion_label = fusion.get("finalAction") or fusion.get("agreement") or "HOLD"
    points = [str(item) for item in watch_points[:4] if str(item).strip()]
    if not points:
        points = [str(item) for item in risk_notes[:4] if str(item).strip()]
    if not points:
        points = ["继续等待新鲜快照、风控门禁和多周期信号一致。"]
    next_action = translate_common_text(points[0])
    return build_digest(
        title="AI 观察",
        level="warning",
        conclusion=f"{symbol} {verdict}；本轮只保留观察证据。",
        metrics=[
            f"周期 {', '.join(timeframes) or 'M15,H1,H4,D1'}",
            f"置信度 {confidence}",
            f"风险 {chinese_risk(source.get('riskLevel'))}",
            f"共识 {fusion_label}",
        ],
        reasons=[translate_common_text(gate_reason), str(headline)],
        next_action=next_action,
        generated_at=report.get("generatedAt"),
    )


def update_state(state: dict[str, Any], *, symbol: str, signature: str, status: str, reason: str, report: dict[str, Any], now_iso: str) -> dict[str, Any]:
    out = dict(state)
    out["mode"] = MODE
    out["updatedAt"] = now_iso
    symbols = dict(out.get("symbols") or {})
    previous = dict(symbols.get(symbol) or {})
    previous.update(
        {
            "symbol": symbol,
            "signature": signature,
            "status": status,
            "reason": reason,
            "lastDecision": decision_summary(report),
            "lastSource": summarize_source(report),
            "lastAnalyzedAt": report.get("generatedAt") or now_iso,
        }
    )
    if status == "sent":
        previous["lastNotifiedAt"] = now_iso
    symbols[symbol] = previous
    out["symbols"] = symbols
    out["safety"] = monitor_safety()
    return out


def attach_deepseek_advice(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(report)
    if getattr(args, "no_deepseek", False):
        enriched["deepseek_advice"] = {"ok": False, "status": "disabled_by_cli", "provider": "deepseek"}
    else:
        try:
            config = load_deepseek_config(repo_root=REPO_ROOT, env_file=getattr(args, "deepseek_env_file", None))
            advice = DeepSeekMt5Advisor(config).analyze(enriched)
        except (DeepSeekAdvisorError, ValueError, OSError) as error:
            advice = {
                "ok": False,
                "status": "error",
                "provider": "deepseek",
                "error": str(error)[:240],
            }
        enriched["deepseek_advice"] = advice

    try:
        from ai_analysis.advisory_fusion import fuse_advisory_report

        enriched = fuse_advisory_report(enriched)
    except Exception as fusion_error:  # pragma: no cover - monitor boundary
        enriched["advisory_fusion"] = {
            "ok": False,
            "schema": "quantgod.ai_advisory_fusion.v1",
            "status": "fusion_error",
            "error": str(fusion_error)[:240],
            "finalAction": "HOLD",
            "safety": monitor_safety(),
        }
    return enriched


def deepseek_advice(report: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    payload = report.get("deepseek_advice") if isinstance(report.get("deepseek_advice"), dict) else {}
    if payload.get("ok") and isinstance(payload.get("advice"), dict):
        return payload["advice"], payload
    return None, payload


def _compute_pip_size(symbol: str) -> float:
    """Return the pip/tick size for a given symbol string."""
    sym = str(symbol).upper()
    if "JPY" in sym:
        return 0.01
    if "XAU" in sym or "XAG" in sym or "GOLD" in sym:
        return 0.10
    if any(idx in sym for idx in ("US30", "NAS", "SPX", "US100", "UK100", "GER30", "US500", "USTEC")):
        return 1.0
    return 0.0001  # standard forex (EURUSD, GBPUSD, etc.)


def _build_render_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Extract the fields needed by the message renderers from a raw report.

    This replaces the old ``build_advisory_message`` which mixed extraction
    and formatting into one 200-line function.
    """
    decision = decision_summary(report)
    source = summarize_source(report)
    symbol = str(report.get("symbol") or "UNKNOWN")

    # ── entryZone: prefer DeepSeek's validated opinion, fall back to entry price ─
    ds_advice_raw = report.get("deepseek_advice") if isinstance(report.get("deepseek_advice"), dict) else {}
    ds_advice = (ds_advice_raw.get("advice") or {}) if ds_advice_raw.get("ok") else {}
    entry_zone = ds_advice.get("entryZone") or fmt_price(decision.get("entryPrice"))
    entry_price = decision.get("entryPrice")

    # ── stopLossPips: compute if not explicitly provided ─
    stop_loss_pips = decision.get("stopLossPips")
    stop_loss = decision.get("stopLoss") or decision.get("stop_loss") or ds_advice.get("defense") or ds_advice.get("stopLoss")
    if stop_loss_pips is None:
        if entry_price is not None and stop_loss is not None:
            try:
                pip_size = _compute_pip_size(symbol)
                pips = abs(float(entry_price) - float(stop_loss)) / pip_size
                stop_loss_pips = int(round(pips))
            except (TypeError, ValueError):
                stop_loss_pips = None

    # ── targets: try multi-target fields, then DeepSeek, then single ──
    targets = _extract_targets(decision, ds_advice)

    # ── stopLoss: keep AI-provided string precision, e.g. 1.0980 ─
    stop_loss_str = _format_target(stop_loss) if stop_loss is not None else "--"

    # Core fields used by ai_advisory / deepseek_insight
    payload: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": (report.get("timeframes") or ["M15"])[0] if isinstance(report.get("timeframes"), list) and report.get("timeframes") else "M15",
        "timeframes": report.get("timeframes") if isinstance(report.get("timeframes"), list) else [],
        "decision": {
            "action": decision.get("action", "HOLD"),
            "confidence": decision.get("confidence", 0),
            "signalGrade": ds_advice.get("signalGrade") or signal_grade(decision, source),
            "entryZone": entry_zone,
            "stopLoss": stop_loss_str,
            "stopLossPips": stop_loss_pips,
            "targets": targets,
            "riskReward": ds_advice.get("riskReward") or decision.get("riskRewardRatio") or "--",
            "invalidation": str(ds_advice.get("invalidation") or decision.get("reasoning") or "等待确认")[:80],
            "risk": source.get("riskLevel", "unknown"),
        },
    }

    # DeepSeek advice (for deepseek_insight kind)
    if ds_advice_raw.get("ok") and isinstance(ds_advice_raw.get("advice"), dict):
        payload["deepseek_advice"] = ds_advice_raw

    # advisory_fusion for audit line (AI 共识)
    fusion = report.get("advisory_fusion") if isinstance(report.get("advisory_fusion"), dict) else {}
    if fusion:
        payload["advisory_fusion"] = fusion

    return payload


def _extract_targets(decision: dict[str, Any], ds_advice: dict[str, Any] | None = None) -> list[str]:
    """Extract up to 3 target prices from decision and DeepSeek advice."""
    # 1) Multi-target fields from decision
    for key in ("takeProfitTargets", "targets", "tp_levels"):
        vals = decision.get(key)
        if isinstance(vals, list) and vals:
            return [_format_target(v) for v in vals[:3]]
    # 2) DeepSeek advice targets
    if ds_advice:
        ds_targets = ds_advice.get("targets")
        if isinstance(ds_targets, list) and ds_targets:
            return [_format_target(t) for t in ds_targets[:3]]
    # 3) Single target fallback
    tp = decision.get("takeProfit") or decision.get("take_profit")
    if tp is not None:
        return [_format_target(tp)]
    return []


def _format_target(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return fmt_price(value)


def _delivery_confirmed(delivery: dict[str, Any]) -> bool:
    return delivery.get("sent") is True and delivery.get("deliveryOk") is True


def send_or_record(args: argparse.Namespace, *, message: str, event_type: str, dry_run: bool) -> dict[str, Any]:
    try:
        from ai_journal.telegram_text import ensure_chinese_telegram_text
        message = ensure_chinese_telegram_text(message)
    except Exception:
        pass
    unsafe_reason = unsafe_advisory_message_reason(message)
    if unsafe_reason:
        return {
            "ok": bool(dry_run),
            "status": "blocked_unsafe_message",
            "reason": unsafe_reason,
            "sendRequested": not dry_run,
            "sent": False,
            "deliveryOk": False,
            "safety": monitor_safety(),
        }
    config = load_config(repo_root=args.repo_root, env_file=args.env_file)
    assert_telegram_safety(config)
    if dry_run:
        record = {"ok": True, "recorded": False}
        if not args.no_record:
            record = record_notification(config, event_type=event_type, status="dry_run", payload={"messagePreview": message[:160]})
        return {
            "ok": True,
            "status": "preview",
            "dryRun": True,
            "sendRequested": False,
            "sent": False,
            "deliveryOk": False,
            "record": record,
            "safety": telegram_safety_payload(config),
        }

    gateway = dispatch_cli_text(
        runtime_dir=runtime_dir_from_args(args),
        source="mt5_ai_telegram_monitor",
        topic=event_type,
        severity="INFO",
        text=message,
        repo_root=args.repo_root or REPO_ROOT,
    )
    nested_delivery = gateway.get("delivery") if isinstance(gateway.get("delivery"), dict) else {}
    confirmed = _delivery_confirmed(gateway)
    if confirmed:
        status = "sent"
    elif nested_delivery.get("skipped") is True:
        status = "send_suppressed"
    else:
        status = "send_failed"
    record = {"ok": True, "recorded": False}
    if not args.no_record:
        record = record_notification(
            config,
            event_type=event_type,
            status="sent" if confirmed else status,
            payload={
                "telegramMessageId": nested_delivery.get("messageId") if confirmed else None,
                "messagePreview": message[:160],
                "reason": nested_delivery.get("reason"),
            },
        )
    gateway.update(
        {
            "ok": confirmed,
            "status": status,
            "sent": confirmed,
            "deliveryOk": confirmed,
            "telegramMessageId": nested_delivery.get("messageId") if confirmed else None,
            "record": record,
            "safety": telegram_safety_payload(config),
        }
    )
    return gateway


async def scan_once(args: argparse.Namespace) -> dict[str, Any]:
    runtime_dir = runtime_dir_from_args(args)
    symbols = parse_csv_list(args.symbols or os.environ.get("QG_MT5_AI_MONITOR_SYMBOLS"), DEFAULT_SYMBOLS)
    timeframes = parse_csv_list(args.timeframes, DEFAULT_TIMEFRAMES)
    state_path = monitor_state_path(args)
    state = read_json(state_path)
    now_epoch = time.time()
    now_iso = utc_now_iso()
    service = AnalysisServiceV2(runtime_dir=runtime_dir)
    items: list[dict[str, Any]] = []
    notifications = 0

    for symbol in symbols:
        report = await service.run_analysis(symbol, timeframes)
        report = attach_deepseek_advice(args, report)
        try:
            from ai_journal.kill_switch import apply_signal_kill_switch
            report = apply_signal_kill_switch(report, runtime_dir=runtime_dir, now_iso=now_iso)
        except Exception as journal_gate_error:
            report.setdefault("ai_journal_gate", {"ok": False, "status": "error", "error": str(journal_gate_error)[:240]})
        signature = event_signature(report)
        should_send, reason = should_notify(
            state,
            symbol=symbol,
            signature=signature,
            now_epoch=now_epoch,
            min_interval_seconds=max(0, int(args.min_interval_seconds)),
            force=bool(args.force),
        )
        delivery: dict[str, Any] = {"ok": True, "status": "skipped", "reason": reason}
        status = "skipped"
        if should_send:
            gate_ok, gate_reason = advisory_push_gate(report, min_confidence_pct=float(args.min_confidence_pct))
            if not gate_ok:
                status = "skipped_hold" if gate_reason == "action_hold" else "skipped_gate"
                delivery = {"ok": True, "status": status, "reason": gate_reason}
                if bool(getattr(args, "push_hold_summary", False)) and bool(args.send):
                    observation_ok, observation_reason = observation_push_gate(report)
                    if observation_ok:
                        message = build_observation_message(report, gate_reason=gate_reason)
                        delivery = send_or_record(
                            args,
                            message=message,
                            event_type="MT5_AI_OBSERVATION",
                            dry_run=False,
                        )
                        status = str(delivery.get("status") or "sent_observation")
                        delivery["observation"] = True
                        delivery["gateReason"] = gate_reason
                        if _delivery_confirmed(delivery):
                            notifications += 1
                    else:
                        delivery["observationReason"] = observation_reason
                items.append(
                    {
                        "symbol": symbol,
                        "signature": signature,
                        "shouldNotify": should_send,
                        "reason": reason,
                        "delivery": delivery,
                        "decision": decision_summary(report),
                        "source": summarize_source(report),
                        "deepseek": report.get("deepseek_advice") if isinstance(report.get("deepseek_advice"), dict) else {},
                        "fusion": report.get("advisory_fusion") if isinstance(report.get("advisory_fusion"), dict) else {},
                    }
                )
                state = update_state(state, symbol=symbol, signature=signature, status=status, reason=gate_reason, report=report, now_iso=now_iso)
                continue
            kind = getattr(args, "kind", "ai_advisory") or "ai_advisory"
            payload = _build_render_payload(report)
            message = render(kind, payload)
            if message is None:
                # HOLD → skip push, record as skipped_hold
                delivery = {"ok": True, "status": "skipped_hold", "reason": "action=HOLD"}
                status = "skipped_hold"
                items.append(
                    {
                        "symbol": symbol,
                        "signature": signature,
                        "shouldNotify": should_send,
                        "reason": reason,
                        "delivery": delivery,
                        "decision": decision_summary(report),
                        "source": summarize_source(report),
                        "deepseek": report.get("deepseek_advice") if isinstance(report.get("deepseek_advice"), dict) else {},
                        "fusion": report.get("advisory_fusion") if isinstance(report.get("advisory_fusion"), dict) else {},
                    }
                )
                state = update_state(state, symbol=symbol, signature=signature, status=status, reason=reason, report=report, now_iso=now_iso)
                continue
            delivery = send_or_record(args, message=message, event_type="MT5_AI_ADVISORY", dry_run=not args.send)
            if not getattr(args, "disable_journal", False):
                try:
                    from ai_journal.writer import record_telegram_advisory
                    delivery["journal"] = record_telegram_advisory(
                        runtime_dir=runtime_dir,
                        report=report,
                        delivery=delivery,
                        message=message,
                        reason=reason,
                        dry_run=not args.send,
                        now_iso=now_iso,
                    )
                except Exception as journal_error:
                    delivery["journal"] = {"ok": False, "status": "journal_error", "error": str(journal_error)[:240]}
            status = str(delivery.get("status") or "sent")
            if _delivery_confirmed(delivery):
                notifications += 1
        state = update_state(state, symbol=symbol, signature=signature, status=status, reason=reason, report=report, now_iso=now_iso)
        items.append(
            {
                "symbol": symbol,
                "signature": signature,
                "shouldNotify": should_send,
                "reason": reason,
                "delivery": delivery,
                "decision": decision_summary(report),
                "source": summarize_source(report),
                "deepseek": report.get("deepseek_advice") if isinstance(report.get("deepseek_advice"), dict) else {},
                "fusion": report.get("advisory_fusion") if isinstance(report.get("advisory_fusion"), dict) else {},
            }
        )

    attempted_deliveries = [
        item.get("delivery")
        for item in items
        if isinstance(item.get("delivery"), dict)
        and item["delivery"].get("sendRequested") is True
    ]
    confirmed_deliveries = [delivery for delivery in attempted_deliveries if _delivery_confirmed(delivery)]
    failed_delivery_count = len(attempted_deliveries) - len(confirmed_deliveries)
    payload = {
        "ok": failed_delivery_count == 0,
        "mode": MODE,
        "generatedAt": now_iso,
        "runtimeDir": str(runtime_dir),
        "dryRun": not args.send,
        "sendRequested": bool(args.send),
        "deliveryAttemptedCount": len(attempted_deliveries),
        "sent": bool(confirmed_deliveries),
        "sentCount": len(confirmed_deliveries),
        "deliveryOk": (
            failed_delivery_count == 0 and bool(attempted_deliveries)
            if args.send
            else False
        ),
        "failedDeliveryCount": failed_delivery_count,
        "items": items,
        "summary": {"symbols": len(symbols), "notifications": notifications},
        "statePath": str(state_path),
        "latestPath": str(latest_report_path(args)),
        "safety": monitor_safety(),
    }
    write_json(state_path, state)
    write_json(latest_report_path(args), payload)
    return payload


async def run_loop(args: argparse.Namespace) -> dict[str, Any]:
    cycles = int(args.cycles)
    interval = max(1, int(args.interval_seconds))
    runs: list[dict[str, Any]] = []
    index = 0
    while cycles <= 0 or index < cycles:
        run = await scan_once(args)
        runs.append(run)
        index += 1
        if bool(args.send) and int(run.get("failedDeliveryCount") or 0) > 0:
            break
        if cycles <= 0 or index < cycles:
            await asyncio.sleep(interval)
    attempted_count = sum(int(run.get("deliveryAttemptedCount") or 0) for run in runs)
    sent_count = sum(int(run.get("sentCount") or 0) for run in runs)
    failed_count = sum(int(run.get("failedDeliveryCount") or 0) for run in runs)
    return {
        "ok": failed_count == 0,
        "mode": MODE,
        "cycles": cycles,
        "completedCycles": len(runs),
        "runs": runs,
        "sendRequested": bool(args.send),
        "deliveryAttemptedCount": attempted_count,
        "sent": sent_count > 0,
        "sentCount": sent_count,
        "deliveryOk": bool(args.send) and attempted_count > 0 and failed_count == 0,
        "failedDeliveryCount": failed_count,
        "safety": monitor_safety(),
    }


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def add_common_scan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbols", default="", help=f"Comma-separated symbols. Default: {DEFAULT_SYMBOLS}")
    parser.add_argument("--timeframes", default=DEFAULT_TIMEFRAMES, help=f"Comma-separated timeframes. Default: {DEFAULT_TIMEFRAMES}")
    parser.add_argument("--runtime-dir", default="", help="MT5/QuantGod runtime evidence directory")
    parser.add_argument("--state-file", default="", help="Optional monitor state JSON path")
    parser.add_argument("--min-interval-seconds", type=int, default=DEFAULT_MIN_INTERVAL_SECONDS, help="Minimum interval before repeating unchanged advisory")
    parser.add_argument("--force", action="store_true", help="Bypass dedupe for this run")
    parser.add_argument("--min-confidence-pct", type=float, default=DEFAULT_MIN_CONFIDENCE_PCT, help="Minimum local AI confidence required before Telegram push")
    parser.add_argument("--send", action="store_true", help="Actually send Telegram push. Default records dry-run evidence only.")
    parser.add_argument("--disable-notification", action="store_true", help="Send silently when --send is used")
    parser.add_argument("--no-record", action="store_true", help="Do not write notification evidence to SQLite")
    parser.add_argument("--disable-journal", action="store_true", help="Do not write AI advisory outcome journal records")
    parser.add_argument("--push-hold-summary", action="store_true", help="When --send is used, push a non-trade Chinese observation summary for validated HOLD reports")
    parser.add_argument("--repo-root", type=Path, default=None, help="Backend repo root for Telegram config")
    parser.add_argument("--env-file", type=Path, default=None, help="Local .env.telegram.local path")
    parser.add_argument("--deepseek-env-file", type=Path, default=None, help="Local .env.deepseek.local path")
    parser.add_argument("--no-deepseek", action="store_true", help="Skip DeepSeek advisory call and use local fallback text")
    parser.add_argument("--kind", default="deepseek_insight", choices=["ai_advisory", "deepseek_insight"], help="Message renderer kind. deepseek_insight is the default for DeepSeek-powered Chinese reports.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuantGod read-only MT5 AI Telegram monitor")
    sub = parser.add_subparsers(dest="command", required=True)
    config = sub.add_parser("config", help="Show monitor safety/config defaults")
    config.set_defaults(func=lambda args: {"ok": True, "mode": MODE, "defaultSymbols": DEFAULT_SYMBOLS, "defaultTimeframes": DEFAULT_TIMEFRAMES, "safety": monitor_safety()})
    once = sub.add_parser("scan-once", help="Run one read-only AI analysis and Telegram advisory pass")
    add_common_scan_args(once)
    once.set_defaults(func=scan_once)
    loop = sub.add_parser("loop", help="Run a bounded polling loop")
    add_common_scan_args(loop)
    loop.add_argument("--cycles", type=int, default=3, help="Number of cycles to run; use 0 for a continuous event-driven monitor")
    loop.add_argument("--interval-seconds", type=int, default=60, help="Delay between cycles")
    loop.set_defaults(func=run_loop)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        emit(result)
        if isinstance(result, dict) and int(result.get("failedDeliveryCount") or 0) > 0:
            return 2
        return 0
    except Exception as exc:
        emit({"ok": False, "error": str(exc), "safety": monitor_safety()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
