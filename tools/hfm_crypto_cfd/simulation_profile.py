from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import (
    SAFETY,
    SIMULATION_PROFILE_REVIEW_SCHEMA_VERSION,
    filled_simulation_profile_path,
    hfm_crypto_dir,
    moss_backtest_path,
    rates_autogen_profile_path,
    simulation_profile_review_path,
    utc_now_iso,
)


ROI_MIN_PCT = 0.0
PNL_USD_MIN = 0.0
SHARPE_MIN = 1.0
MAX_DRAWDOWN_MAX_PCT = 15.0
TRADE_COUNT_MIN = 20
LIQUIDATION_MAX = 0

REQUIRED_PROFILE_FIELDS = [
    "agentId",
    "pnlUsd",
    "roiPct",
    "sharpe",
    "maxDrawdownPct",
    "tradeCount",
    "liquidationCount",
]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _first_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _read_json(path: str) -> tuple[dict[str, Any], str, str]:
    raw_path = _clean_text(path)
    if not raw_path:
        return {}, "", "NO_PATH"
    source_path = Path(raw_path).expanduser()
    if not source_path.exists() or not source_path.is_file():
        return {}, str(source_path), "MISSING"
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}, str(source_path), "UNREADABLE"
    return (payload if isinstance(payload, dict) else {}), str(source_path), "JSON"


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in paths:
        path = candidate.expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _auto_profile_candidates(runtime_dir: Path) -> list[Path]:
    base = hfm_crypto_dir(runtime_dir)
    return _unique_paths([
        filled_simulation_profile_path(runtime_dir),
        rates_autogen_profile_path(runtime_dir),
        moss_backtest_path(runtime_dir),
        base / "moss_backtest.json",
        base / "moss_profile.json",
        base / "hfm_crypto_simulation_profile.json",
        Path(runtime_dir) / "moss_backtest.json",
        Path(runtime_dir) / "moss_profile.json",
        Path(runtime_dir) / "hfm_crypto_simulation_profile.json",
    ])


def _profile_candidate_summary(path: Path) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    row = {
        "path": str(path),
        "exists": exists,
        "sourceFormat": "MISSING",
        "profileFound": False,
        "qualified": False,
        "agentId": "",
        "blockerCodes": [],
    }
    if not exists:
        return row
    profile = parse_simulation_profile(str(path))
    metrics = profile.get("metrics") if isinstance(profile.get("metrics"), dict) else {}
    blockers = simulation_metric_blockers(metrics, bool(profile.get("profileFound")))
    row.update({
        "sourceFormat": profile.get("sourceFormat", ""),
        "profileFound": bool(profile.get("profileFound")),
        "qualified": bool(profile.get("profileFound")) and not blockers,
        "agentId": str(metrics.get("agentId") or ""),
        "blockerCodes": [item.get("code") for item in blockers if isinstance(item, dict)],
    })
    return row


def _auto_profile(runtime_dir: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    summaries = [_profile_candidate_summary(path) for path in _auto_profile_candidates(runtime_dir)]
    found = [row for row in summaries if row.get("profileFound")]
    if not found:
        return parse_simulation_profile(""), {"source": "", "path": "", "autoDiscovered": False}, summaries
    selected = next((row for row in found if row.get("qualified")), found[0])
    return (
        parse_simulation_profile(str(selected.get("path") or "")),
        {
            "source": "auto_discovered_simulation_profile",
            "path": selected.get("path", ""),
            "autoDiscovered": True,
            "qualified": bool(selected.get("qualified")),
        },
        summaries,
    )


def parse_simulation_profile(path: str = "", raw_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile, resolved_path, source_format = _read_json(path)
    if raw_profile:
        profile = {**profile, **raw_profile}
        source_format = "RAW_PROFILE"
    if not profile:
        return {
            "source": "moss_or_simulation_profile_json",
            "profileJsonPath": resolved_path,
            "sourceFormat": source_format,
            "profileFound": False,
            "metrics": {},
        }
    nested = profile.get("agent") if isinstance(profile.get("agent"), dict) else {}
    metrics = profile.get("metrics") if isinstance(profile.get("metrics"), dict) else {}
    backtest = profile.get("backtest") if isinstance(profile.get("backtest"), dict) else {}
    source = {**profile, **nested, **metrics, **backtest}
    parsed = {
        "agentId": _first_value(source, ("agentId", "id", "targetAgentId")),
        "url": _first_value(source, ("url", "agentUrl", "targetAgentUrl")),
        "strategyName": _first_value(source, ("strategyName", "name", "title")),
        "pnl": _safe_float(_first_value(source, ("pnl", "profit", "profitUsd", "pnlUsd"))),
        "roiPct": _safe_float(_first_value(source, ("roiPct", "roi", "returnPct", "profitPct"))),
        "sharpe": _safe_float(_first_value(source, ("sharpe", "sharpeRatio"))),
        "maxDrawdownPct": _safe_float(_first_value(source, ("maxDrawdownPct", "maxDrawdown", "drawdownPct"))),
        "liquidationCount": _safe_int(_first_value(source, ("liquidationCount", "liquidations", "liqCount"))),
        "tradeCount": _safe_int(_first_value(source, ("tradeCount", "trades", "totalTrades"))),
        "backtestDateRange": _first_value(source, ("backtestDateRange", "dateRange", "range")),
    }
    return {
        "source": "moss_or_simulation_profile_json",
        "profileJsonPath": resolved_path,
        "sourceFormat": source_format,
        "profileFound": True,
        "metrics": parsed,
        "rawKeys": sorted(profile.keys()),
    }


def _blocker(code: str, reason_zh: str, value: Any = None, limit: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value is not None:
        row["value"] = value
    if limit is not None:
        row["limit"] = limit
    return row


def simulation_metric_blockers(metrics: dict[str, Any], profile_found: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not profile_found:
        rows.append(_blocker("HFM_SIMULATION_PROFILE_MISSING", "缺少 Moss/HFM crypto 模拟或回测 profile。"))
        return rows
    roi = _safe_float(metrics.get("roiPct"))
    sharpe = _safe_float(metrics.get("sharpe"))
    max_drawdown = _safe_float(metrics.get("maxDrawdownPct"))
    trade_count = _safe_int(metrics.get("tradeCount"))
    liquidation_count = _safe_int(metrics.get("liquidationCount"))
    agent_id = _clean_text(metrics.get("agentId"))
    if not agent_id:
        rows.append(_blocker("HFM_SIM_AGENT_ID_MISSING", "模拟 profile 缺少 agentId，无法绑定策略身份。"))
    pnl = _safe_float(metrics.get("pnl"))
    if pnl is None or pnl <= PNL_USD_MIN:
        rows.append(_blocker("HFM_PNL_USD_NOT_POSITIVE", "HFM crypto 模拟 USD pnl 未证明为正，不能计入 BTC/crypto 合计收益目标追踪。", pnl, f">{PNL_USD_MIN}"))
    if roi is None or roi <= ROI_MIN_PCT:
        rows.append(_blocker("HFM_ROI_NOT_POSITIVE", "HFM crypto 模拟 ROI 未证明为正。", roi, f">{ROI_MIN_PCT}"))
    if sharpe is None or sharpe < SHARPE_MIN:
        rows.append(_blocker("HFM_SHARPE_LT_MIN", "HFM crypto 模拟 Sharpe 未达准入线。", sharpe, SHARPE_MIN))
    if max_drawdown is None or max_drawdown > MAX_DRAWDOWN_MAX_PCT:
        rows.append(_blocker("HFM_MAX_DRAWDOWN_GT_MAX", "HFM crypto 模拟最大回撤超过准入线。", max_drawdown, MAX_DRAWDOWN_MAX_PCT))
    if trade_count is None or trade_count < TRADE_COUNT_MIN:
        rows.append(_blocker("HFM_TRADE_COUNT_LT_MIN", "HFM crypto 模拟交易样本不足。", trade_count, TRADE_COUNT_MIN))
    if liquidation_count is None or liquidation_count > LIQUIDATION_MAX:
        rows.append(_blocker("HFM_LIQUIDATION_COUNT_GT_MAX", "HFM crypto 模拟出现爆仓或缺少爆仓字段。", liquidation_count, LIQUIDATION_MAX))
    return rows


def build_hfm_crypto_simulation_profile_review(
    runtime_dir: Path,
    *,
    simulation_profile_json: str = "",
    write: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    if simulation_profile_json:
        profile = parse_simulation_profile(simulation_profile_json)
        source_selection = {
            "source": "explicit_simulation_profile_json",
            "path": profile.get("profileJsonPath", str(Path(simulation_profile_json).expanduser())),
            "autoDiscovered": False,
        }
        auto_candidates: list[dict[str, Any]] = []
    else:
        profile, source_selection, auto_candidates = _auto_profile(runtime_dir)
    metrics = profile.get("metrics") if isinstance(profile.get("metrics"), dict) else {}
    blockers = simulation_metric_blockers(metrics, bool(profile.get("profileFound")))
    qualified = bool(profile.get("profileFound")) and not blockers
    payload = {
        "ok": True,
        "schema": SIMULATION_PROFILE_REVIEW_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "status": "SIMULATION_PROFILE_QUALIFIED" if qualified else "WAITING_HFM_CRYPTO_SIMULATION_PROFILE",
        "statusZh": "HFM crypto 模拟表现达标" if qualified else "等待 HFM crypto 模拟表现证据",
        "simulationQualified": qualified,
        "executionReady": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "sourceSelection": source_selection,
        "autoProfileCandidates": auto_candidates,
        "profile": profile,
        "metrics": metrics,
        "thresholds": {
            "pnlUsdMinExclusive": PNL_USD_MIN,
            "roiPctMinExclusive": ROI_MIN_PCT,
            "sharpeMin": SHARPE_MIN,
            "maxDrawdownPctMax": MAX_DRAWDOWN_MAX_PCT,
            "tradeCountMin": TRADE_COUNT_MIN,
            "liquidationCountMax": LIQUIDATION_MAX,
        },
        "requiredFields": REQUIRED_PROFILE_FIELDS,
        "blockers": blockers,
        "nextRequiredActionZh": (
            "模拟表现已达标；继续确认 HFM symbol、合约规格、执行 lane 评审和 operator approval。"
            if qualified
            else "导入包含 USD pnl、ROI、Sharpe、最大回撤、交易笔数和爆仓次数的 Moss/模拟 profile JSON。"
        ),
        "safety": dict(SAFETY),
    }
    if write:
        out = simulation_profile_review_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_hfm_crypto_simulation_profile_review(runtime_dir: Path) -> dict[str, Any]:
    path = simulation_profile_review_path(Path(runtime_dir))
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return {"ok": True, **payload}
        except Exception:
            pass
    return build_hfm_crypto_simulation_profile_review(Path(runtime_dir), write=False)
