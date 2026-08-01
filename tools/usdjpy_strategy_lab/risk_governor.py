from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .data_loader import fastlane_quality, focus_runtime_snapshot, runtime_fresh_limit_seconds
from .schema import FOCUS_SYMBOL, READ_ONLY_SAFETY, assert_no_secret_or_execution_flags, utc_now_iso

try:
    from tools.news_gate.classifier import classify_news_gate
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from news_gate.classifier import classify_news_gate


def build_risk_check(runtime_dir: Path) -> Dict[str, Any]:
    snapshot = focus_runtime_snapshot(runtime_dir) or {}
    quality = fastlane_quality(runtime_dir)
    news_gate = classify_news_gate(snapshot)
    blockers: List[str] = []
    runtime_ok = True
    if not snapshot:
        runtime_ok = False
        blockers.append("缺少 USDJPY 运行快照")
    elif snapshot.get("fallback"):
        runtime_ok = False
        blockers.append("运行快照处于 fallback")
    try:
        age = float(snapshot.get("runtimeAgeSeconds", 9999))
        if age > runtime_fresh_limit_seconds():
            runtime_ok = False
            blockers.append(f"运行快照过旧：{age:.0f}s")
    except Exception:
        runtime_ok = False
        blockers.append("运行快照年龄不可解析")
    fastlane_ok = True
    if not quality.get("found"):
        fastlane_ok = False
        blockers.append("缺少快通道质量")
    elif str(quality.get("quality") or "").upper() not in {"OK", "PASS", "PASSED", "GOOD", "HEALTHY", "FAST", "EA_DASHBOARD_OK"}:
        fastlane_ok = False
        blockers.append(f"快通道质量未通过：{quality.get('quality')}")
    news_ok = news_gate.get("hardBlock") is False
    shadow_only = READ_ONLY_SAFETY.get("shadowTradingOnly") is True
    risk_ok = all(value is True for value in (runtime_ok, fastlane_ok, news_ok, shadow_only))
    payload = {
        "ok": True,
        "schema": "quantgod.usdjpy_strategy_risk_check.v1",
        "generatedAt": utc_now_iso(),
        "symbol": FOCUS_SYMBOL,
        "status": "PASS" if risk_ok else "BLOCKED",
        "riskOk": risk_ok,
        "runtimeOk": runtime_ok,
        "fastlaneOk": fastlane_ok,
        "newsOk": news_ok,
        "shadowOnly": shadow_only,
        "newsGate": news_gate,
        "blockers": blockers,
        "notes": [
            "风险检查只决定是否允许进入影子/干跑政策评估。",
            "不会下单、平仓、撤单或修改 live preset。",
        ],
        "safety": dict(READ_ONLY_SAFETY),
    }
    assert_no_secret_or_execution_flags(payload)
    return payload
