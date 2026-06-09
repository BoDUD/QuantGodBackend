from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from .schema import SAFETY, SCHEMA_VERSION, report_path, utc_now_iso


AGENT_RE = re.compile(r"(agt[0-9A-Za-z_-]+)")


def _agent_id_from_url(url: str) -> str:
    match = AGENT_RE.search(url)
    return match.group(1) if match else ""


def _is_moss_agent_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    return host.endswith("moss.site") and "/agent/" in parsed.path


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _first_value(source: Dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return None


def _load_profile_json(path: str) -> Dict[str, Any]:
    profile_path = Path(str(path or "").strip()).expanduser()
    if not profile_path:
        return {}
    try:
        if profile_path.exists() and profile_path.is_file():
            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def _extract_profile_metrics(profile: Dict[str, Any]) -> Dict[str, Any]:
    if not profile:
        return {}
    nested = profile.get("agent") if isinstance(profile.get("agent"), dict) else {}
    metrics = profile.get("metrics") if isinstance(profile.get("metrics"), dict) else {}
    source: Dict[str, Any] = {**profile, **nested, **metrics}
    return {
        "strategyName": _first_value(source, ["strategyName", "name", "title"]),
        "style": _first_value(source, ["style", "strategyStyle", "description"]),
        "roiPct": _safe_float(_first_value(source, ["roiPct", "roi", "returnPct", "profitPct"])),
        "maxDrawdownPct": _safe_float(_first_value(source, ["maxDrawdownPct", "maxDrawdown", "drawdownPct"])),
        "runtimeHours": _safe_float(_first_value(source, ["runtimeHours", "runningHours", "ageHours"])),
        "liquidationCount": _safe_int(_first_value(source, ["liquidationCount", "liquidations", "liqCount"])),
        "tradeCount": _safe_int(_first_value(source, ["tradeCount", "trades", "totalTrades"])),
    }


def build_hyperliquid_shadow_lane(
    runtime_dir: Path,
    *,
    target_agent_url: str = "",
    target_agent_profile_json: str = "",
    write: bool = True,
) -> Dict[str, Any]:
    url = str(target_agent_url or "").strip()
    agent_id = _agent_id_from_url(url)
    valid_url = bool(url) and _is_moss_agent_url(url)
    profile = _load_profile_json(target_agent_profile_json)
    profile_metrics = _extract_profile_metrics(profile)
    status = "READY_FOR_READONLY_SIGNAL_MAPPING" if valid_url else "WAITING_MOSS_AGENT_URL"
    blockers = [] if valid_url else [{
        "code": "MOSS_AGENT_URL_REQUIRED",
        "reasonZh": "需要 moss.site/agent/agt... 页面链接后，才能建立只读影子映射。",
    }]
    payload: Dict[str, Any] = {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": status,
        "statusZh": "Hyperliquid 影子车道就绪" if valid_url else "等待 Moss agent 链接",
        "targetAgent": {
            "url": url,
            "agentId": agent_id,
            "source": "moss_agent_page",
            "valid": valid_url,
            "profileJsonPath": str(target_agent_profile_json or ""),
            "profileFound": bool(profile),
            "metrics": profile_metrics,
        },
        "shadowPlan": {
            "mode": "READONLY_SIGNAL_MIRROR",
            "pollIntervalSeconds": 60,
            "priceDiffProtectionPct": 3.0,
            "positionSizing": "not_applicable_until_execution_lane_is_separately_approved",
            "recordsOnly": True,
            "writesOrders": False,
            "reasonZh": "先把目标 agent 的开平仓信号映射为本地只读事件；不授权钱包、不下单。",
        },
        "riskBoundary": {
            "followRatio": 0.0,
            "maxNotionalUsd": 0.0,
            "stopLossPct": None,
            "autoFlattenAllowed": False,
            "operatorApprovalRequiredForExecutionLane": True,
            "reasonZh": "当前只建立观察车道；真钱跟单必须另走隔离授权和资金门禁。",
        },
        "blockers": blockers,
        "sourceFiles": {
            "report": str(report_path(runtime_dir)),
        },
        "safety": dict(SAFETY),
    }
    if write:
        path = report_path(runtime_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hyperliquid_shadow_lane(runtime_dir: Path) -> Dict[str, Any]:
    path = report_path(runtime_dir)
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
    except Exception:
        pass
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "status": "WAITING_HYPERLIQUID_SHADOW_BUILD",
        "statusZh": "等待构建 Hyperliquid 影子车道",
        "safety": dict(SAFETY),
    }
