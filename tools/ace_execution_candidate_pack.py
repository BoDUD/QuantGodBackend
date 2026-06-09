"""Read-only ace execution candidate pack.

This artifact collapses the strategy scout, champion retest, TP/SL optimizer,
profit target tracker, and release-token evidence into one operator-facing
decision packet. It never writes order requests, receipts, live presets, or
credentials.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "quantgod.ace_execution_candidate_pack.v1"
REPORT_PATH = Path("agent") / "QuantGod_AceExecutionCandidatePack.json"

SAFETY = {
    "readOnly": True,
    "shadowOnly": True,
    "testerOnly": True,
    "advisoryOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "writesMt5OrderReceipt": False,
    "writesLivePreset": False,
    "livePresetMutationAllowed": False,
    "brokerCallsMade": False,
    "walletAuthorizationAllowed": False,
    "hyperliquidExecutionAllowed": False,
    "mossExecutionAllowed": False,
}

BTC_RUNTIME_DATA_PLANE_BLOCKERS = {
    "MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD",
    "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING",
    "MT5_SYMBOL_NOT_IN_RUNTIME_SNAPSHOT",
}

BTC_EXECUTION_MODE_BLOCKERS = {
    "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
    "MT5_READ_ONLY_MODE_STILL_ACTIVE",
    "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
    "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
}


def _now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _btc_identity_key_from_params(strategy_id: Any, params: dict[str, Any]) -> str:
    if params:
        return "|".join([
            str(params.get("bias") or ""),
            str(params.get("takeProfitPriceMove") or ""),
            str(params.get("stopLossPriceMove") or ""),
            str(params.get("maxHoldBars") or ""),
            str(params.get("cooldownBars") or ""),
        ])
    return str(strategy_id or "")


def _resolve_current_btc_canonical_strategy_id(
    source_row: dict[str, Any],
    strategy_shortlist: dict[str, Any],
) -> str | None:
    source_identity = _btc_identity_key_from_params(
        source_row.get("strategyId"),
        _btc_source_params(source_row),
    )
    if not source_identity:
        return None
    candidate_rows: list[dict[str, Any]] = []
    candidate_rows.extend(_dict(row) for row in _list(strategy_shortlist.get("btcTopStrategies")))
    candidate_rows.extend(_dict(row) for row in _list(_dict(strategy_shortlist.get("btcCryptoCfd")).get("focusedRetestQueue")))
    candidate_rows.extend([
        _dict(_dict(strategy_shortlist.get("selectedDefault")).get("selectionBasis")),
        _dict(_dict(strategy_shortlist.get("selectionConsensus")).get("btc")),
    ])
    seen: set[str] = set()
    for row in candidate_rows:
        strategy_id = str(
            row.get("strategyId")
            or row.get("mostStableNowStrategyId")
            or row.get("strongestYieldNowStrategyId")
            or ""
        )
        if not strategy_id or strategy_id in seen:
            continue
        seen.add(strategy_id)
        candidate_identity = _btc_identity_key_from_params(strategy_id, _btc_source_params(row))
        if candidate_identity == source_identity:
            return strategy_id
    return None


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").replace(",", "").strip())
        except ValueError:
            return default
    return default


def _artifact_summary(path: Path, payload: dict[str, Any], *, kind: str) -> dict[str, Any]:
    generated_at_iso = _artifact_generated_at_from_path(path, payload)
    summary = {
        "path": str(path),
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "generatedAtIso": generated_at_iso,
    }
    if kind == "championTesterRunGate":
        gate = _dict(payload.get("gate"))
        live_session = _dict(gate.get("liveSession"))
        next_window = _resolved_next_tester_window(_dict(payload.get("nextTesterWindow")))
        summary.update({
            "blockerCount": len(_blocker_codes(gate.get("blockers"))),
            "liveSessionOk": bool(live_session.get("ok")),
            "liveSessionStatus": live_session.get("status"),
            "nextTesterWindowLabel": next_window.get("label"),
            "nextTesterWindowStartJstIso": next_window.get("startJstIso"),
            "nextTesterWindowEndJstIso": next_window.get("endJstIso"),
            "nextTesterWindowMinutesUntilStart": next_window.get("minutesUntilStart"),
        })
    elif kind == "liveRuntimePreflightProbe":
        dashboard = _dict(payload.get("dashboardSnapshot"))
        lane_checks = [
            _dict(row)
            for row in _list(payload.get("laneRuntimeChecks"))
            if _dict(row).get("lane") == "HFM_CRYPTO_CFD"
        ]
        lane_check = lane_checks[0] if lane_checks else {}
        summary.update({
            "dashboardFresh": bool(dashboard.get("fresh")),
            "dashboardAgeSeconds": dashboard.get("ageSeconds"),
            "dashboardSymbolNames": _list(dashboard.get("symbolNames"))[:3],
            "runtimeProbeFresh": lane_check.get("runtimeProbeFresh"),
            "runtimeProbeAgeSeconds": lane_check.get("runtimeProbeAgeSeconds"),
        })
    elif kind == "liveEvidenceIntake":
        summary.update({
            "presentInputCount": _dict(payload.get("fileInputSummary")).get("presentInputCount"),
            "missingChecklistCount": _dict(payload.get("fileInputSummary")).get("missingChecklistCount"),
            "dashboardFresh": payload.get("dashboardFresh"),
            "tradeStatus": payload.get("tradeStatus"),
            "tradePermissionBlocker": payload.get("tradePermissionBlocker"),
            "targetSymbols": _list(payload.get("targetSymbols"))[:3],
        })
    elif kind == "tpSlOptimizer":
        btc = _dict(payload.get("btcCryptoCfd"))
        summary.update({
            "recommendedStableStrategyId": _dict(btc.get("recommendedStable")).get("strategyId"),
            "recommendedTargetSeekingStrategyId": _dict(btc.get("recommendedTargetSeeking")).get("strategyId"),
            "finalAdvisoryPickStrategyId": _dict(btc.get("finalAdvisoryPick")).get("strategyId"),
            "optimizerLegacyStableStrategyId": _dict(btc.get("recommendedStable")).get("strategyId"),
            "optimizerLegacyTargetSeekingStrategyId": _dict(btc.get("recommendedTargetSeeking")).get("strategyId"),
            "optimizerLegacyFinalAdvisoryPickStrategyId": _dict(btc.get("finalAdvisoryPick")).get("strategyId"),
        })
    elif kind == "btcStrategyScan":
        top = _dict(_list(payload.get("topCandidates"))[0]) if _list(payload.get("topCandidates")) else {}
        summary.update({
            "topCandidateStrategyId": top.get("strategyId"),
            "topCandidateValidWindowCount": top.get("validWindowCount"),
        })
    elif kind == "aceStrategyScout":
        summary.update({
            "topQualifiedForexSeedId": _dict(payload.get("topQualifiedForex")).get("seedId"),
            "topResearchCryptoStrategyId": (
                _dict(payload.get("topResearchCrypto")).get("strategyId")
                or _dict(payload.get("topQualifiedCrypto")).get("strategyId")
                or _dict(payload.get("topRetestedCrypto")).get("strategyId")
                or payload.get("topStrategyId")
            ),
        })
    elif kind == "championRetest":
        summary.update({
            "forexChampionSeedId": _dict(payload.get("forexChampion")).get("seedId"),
        })
    return summary


def _artifact_generated_at(payload: dict[str, Any]) -> str | None:
    value = payload.get("generatedAtIso") or payload.get("generatedAt")
    return value if isinstance(value, str) and value else None


def _artifact_generated_at_from_path(path: Path, payload: dict[str, Any]) -> str | None:
    generated = _artifact_generated_at(payload)
    if generated:
        return generated
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None
    return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _resolved_next_tester_window(next_window: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(next_window)
    start_at = _parse_iso(next_window.get("startJstIso"))
    if not start_at:
        return resolved
    end_at = _parse_iso(next_window.get("endJstIso"))
    now = _utc_now()
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    if end_at and end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    if end_at and start_at <= now <= end_at:
        resolved["minutesUntilStart"] = 0.0
        return resolved
    resolved["minutesUntilStart"] = round((start_at - now).total_seconds() / 60.0, 1)
    return resolved


def _mt5_lock_refresh_guidance(run_gate: dict[str, Any]) -> dict[str, Any]:
    guidance = _dict(run_gate.get("authorizationLockRefreshGuidance"))
    if guidance:
        return guidance
    return _dict(_dict(_dict(run_gate.get("gate")).get("authorizationLock")).get("refreshGuidance"))


def _source_artifact_summaries(
    *,
    agent_dir: Path,
    ace: dict[str, Any],
    retest: dict[str, Any],
    tpsl: dict[str, Any],
    scan: dict[str, Any],
    run_gate: dict[str, Any],
    preflight: dict[str, Any],
    live_evidence_intake: dict[str, Any],
    profit_target: dict[str, Any],
    matrix: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    scout_summary = _artifact_summary(agent_dir / "QuantGod_AceStrategyScout.json", ace, kind="aceStrategyScout")
    scan_summary = _artifact_summary(agent_dir / "QuantGod_BtcStrategyScanReport.json", scan, kind="btcStrategyScan")
    if not scout_summary.get("topResearchCryptoStrategyId"):
        scout_summary["topResearchCryptoStrategyId"] = scan_summary.get("topCandidateStrategyId")
    return {
        "aceStrategyScout": scout_summary,
        "championRetest": _artifact_summary(agent_dir / "QuantGod_ChampionRetestReport.json", retest, kind="championRetest"),
        "btcStrategyScan": scan_summary,
        "championTesterRunGate": _artifact_summary(agent_dir / "QuantGod_ChampionTesterRunGate.json", run_gate, kind="championTesterRunGate"),
        "liveRuntimePreflightProbe": _artifact_summary(agent_dir / "QuantGod_LiveRuntimePreflightProbe.json", preflight, kind="liveRuntimePreflightProbe"),
        "liveEvidenceIntake": _artifact_summary(agent_dir / "QuantGod_LiveEvidenceIntake.json", live_evidence_intake, kind="liveEvidenceIntake"),
        "tpSlOptimizer": _artifact_summary(agent_dir / "QuantGod_TpSlOptimizerReport.json", tpsl, kind="tpSlOptimizer"),
        "profitTargetTracker": _artifact_summary(agent_dir.parent / "profit_target" / "QuantGod_ProfitTargetTracker.json", profit_target, kind="generic"),
        "simTargetExecutionReviewSummary": _artifact_summary(agent_dir / "QuantGod_SimTargetExecutionReviewSummary.json", summary, kind="generic"),
        "releaseTokenSignoffEvidenceMatrix": _artifact_summary(agent_dir / "QuantGod_ReleaseTokenSignoffEvidenceMatrix.json", matrix, kind="generic"),
    }


def _source_artifact_summary_zh(source_summaries: dict[str, Any]) -> str:
    scout = _dict(source_summaries.get("aceStrategyScout"))
    run_gate = _dict(source_summaries.get("championTesterRunGate"))
    preflight = _dict(source_summaries.get("liveRuntimePreflightProbe"))
    intake = _dict(source_summaries.get("liveEvidenceIntake"))
    tpsl = _dict(source_summaries.get("tpSlOptimizer"))
    scan = _dict(source_summaries.get("btcStrategyScan"))
    return (
        f"scout@{scout.get('generatedAtIso') or 'unknown'} "
        f"btcTop={scout.get('topResearchCryptoStrategyId') or 'unknown'}；"
        f"runGate@{run_gate.get('generatedAtIso') or 'unknown'} "
        f"windowStart={run_gate.get('nextTesterWindowStartJstIso') or 'unknown'} "
        f"minutesUntilStart={run_gate.get('nextTesterWindowMinutesUntilStart')}；"
        f"preflight@{preflight.get('generatedAtIso') or 'unknown'} "
        f"dashboardFresh={preflight.get('dashboardFresh')} ageSeconds={preflight.get('dashboardAgeSeconds')}；"
        f"evidenceIntake@{intake.get('generatedAtIso') or 'unknown'} "
        f"presentInputs={intake.get('presentInputCount')} "
        f"tradeBlocker={intake.get('tradePermissionBlocker') or 'unknown'}；"
        f"tpsl@{tpsl.get('generatedAtIso') or 'unknown'} "
        f"optimizerLegacy={tpsl.get('optimizerLegacyFinalAdvisoryPickStrategyId') or tpsl.get('optimizerLegacyStableStrategyId') or tpsl.get('finalAdvisoryPickStrategyId') or tpsl.get('recommendedStableStrategyId') or 'unknown'} "
        f"optimizerLegacyCanonical={tpsl.get('optimizerLegacyCanonicalStrategyId') or 'unknown'} "
        f"currentDefault={tpsl.get('currentConsensusDefaultStrategyId') or 'unknown'}；"
        f"scan@{scan.get('generatedAtIso') or 'unknown'} top={scan.get('topCandidateStrategyId') or 'unknown'}。"
    )


def _saved_pack_stale(runtime_dir: Path, payload: dict[str, Any]) -> bool:
    embedded = _dict(payload.get("sourceArtifactSummaries"))
    if not embedded:
        return False
    agent_dir = Path(runtime_dir) / "agent"
    current_sources = {
        "aceStrategyScout": _read_json(agent_dir / "QuantGod_AceStrategyScout.json"),
        "btcStrategyScan": _read_json(agent_dir / "QuantGod_BtcStrategyScanReport.json"),
        "tpSlOptimizer": _read_json(agent_dir / "QuantGod_TpSlOptimizerReport.json"),
        "championTesterRunGate": _read_json(agent_dir / "QuantGod_ChampionTesterRunGate.json"),
        "liveRuntimePreflightProbe": _read_json(agent_dir / "QuantGod_LiveRuntimePreflightProbe.json"),
        "liveEvidenceIntake": _read_json(agent_dir / "QuantGod_LiveEvidenceIntake.json"),
    }
    for key, current_payload in current_sources.items():
        source_path = {
            "aceStrategyScout": agent_dir / "QuantGod_AceStrategyScout.json",
            "btcStrategyScan": agent_dir / "QuantGod_BtcStrategyScanReport.json",
            "tpSlOptimizer": agent_dir / "QuantGod_TpSlOptimizerReport.json",
            "championTesterRunGate": agent_dir / "QuantGod_ChampionTesterRunGate.json",
            "liveRuntimePreflightProbe": agent_dir / "QuantGod_LiveRuntimePreflightProbe.json",
            "liveEvidenceIntake": agent_dir / "QuantGod_LiveEvidenceIntake.json",
        }[key]
        embedded_generated = _parse_iso(_dict(embedded.get(key)).get("generatedAtIso"))
        current_generated = _parse_iso(_artifact_generated_at_from_path(source_path, current_payload))
        if embedded_generated and current_generated and current_generated > embedded_generated:
            return True
    return False


def _metrics(source: dict[str, Any]) -> dict[str, Any]:
    if not source:
        return {}
    keys = (
        "fitness",
        "netR",
        "profitFactor",
        "sharpe",
        "maxDrawdownR",
        "maxDrawdownPct",
        "tradeCount",
        "effectiveSampleCount",
        "walkForwardStability",
        "trainNetR",
        "validationNetR",
        "forwardNetR",
        "pnlUsd",
        "roiPct",
        "liquidationCount",
    )
    return {key: source[key] for key in keys if key in source}


def _btc_candidate(candidate: dict[str, Any], *, role: str) -> dict[str, Any]:
    if not candidate:
        return {
            "role": role,
            "status": "BTC_CANDIDATE_MISSING",
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        }
    metrics = _dict(candidate.get("fullWindowMetrics"))
    params = _dict(candidate.get("params")) or _dict(candidate.get("parameters"))
    return {
        "role": role,
        "status": candidate.get("status"),
        "strategyId": candidate.get("strategyId"),
        "strategyName": candidate.get("strategyName"),
        "strategyFamily": candidate.get("strategyFamily"),
        "params": params,
        "tpSlSummary": _dict(candidate.get("tpSlSummary")) or {
            "bias": params.get("bias"),
            "takeProfitPriceMove": params.get("takeProfitPriceMove"),
            "stopLossPriceMove": params.get("stopLossPriceMove"),
            "maxHoldBars": params.get("maxHoldBars"),
            "cooldownBars": params.get("cooldownBars"),
        },
        "metrics": {
            "pnlUsd": metrics.get("pnlUsd"),
            "roiPct": metrics.get("roiPct"),
            "sharpe": metrics.get("sharpe"),
            "maxDrawdownPct": metrics.get("maxDrawdownPct"),
            "tradeCount": metrics.get("tradeCount"),
            "liquidationCount": metrics.get("liquidationCount"),
        },
        "validWindowCount": candidate.get("validWindowCount"),
        "windowCount": candidate.get("windowCount"),
        "positiveWindowCount": candidate.get("positiveWindowCount"),
        "negativeWindowCount": candidate.get("negativeWindowCount"),
        "positiveMajorWindowCount": candidate.get("positiveMajorWindowCount"),
        "majorWindowFailureCount": candidate.get("majorWindowFailureCount"),
        "blockers": _list(candidate.get("blockers")),
        "windowSummary": _list(candidate.get("windowSummary")),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _btc_candidate_from_shortlist_item(item: dict[str, Any], *, role: str) -> dict[str, Any]:
    if not item:
        return _btc_candidate({}, role=role)
    metrics = _dict(item.get("metrics"))
    params = _dict(item.get("params"))
    selection_basis = _dict(item.get("selectionBasis"))
    return {
        "role": role,
        "status": item.get("status"),
        "strategyId": item.get("strategyId"),
        "strategyName": item.get("strategyName"),
        "strategyFamily": item.get("strategyFamily"),
        "params": params,
        "tpSlSummary": dict(params),
        "metrics": {
            "pnlUsd": metrics.get("pnlUsd"),
            "roiPct": metrics.get("roiPct"),
            "sharpe": metrics.get("sharpe"),
            "maxDrawdownPct": metrics.get("maxDrawdownPct"),
            "tradeCount": metrics.get("tradeCount"),
            "liquidationCount": metrics.get("liquidationCount"),
            "validWindowCount": metrics.get("validWindowCount"),
            "windowCount": metrics.get("windowCount"),
        },
        "validWindowCount": metrics.get("validWindowCount"),
        "windowCount": metrics.get("windowCount"),
        "majorWindowFailureCount": metrics.get("majorWindowFailureCount"),
        "selectionReasonZh": selection_basis.get("selectionReasonZh") or selection_basis.get("reasonZh"),
        "blockers": _list(item.get("blockers")),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _strategy_shortlist_item(
    *,
    lane: str,
    role: str,
    summary_type: str,
    strategy_id: str | None = None,
    seed_id: str | None = None,
    strategy_name: str | None = None,
    strategy_family: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    metrics: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    blockers: list[Any] | None = None,
    next_action_zh: str | None = None,
    contender_tie_break_required: bool = False,
    tester_only: bool = True,
    selection_basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_selection_basis = dict(selection_basis or {})
    if (
        isinstance(normalized_selection_basis.get("reasonZh"), str)
        and normalized_selection_basis.get("reasonZh")
        and not normalized_selection_basis.get("selectionReasonZh")
    ):
        normalized_selection_basis["selectionReasonZh"] = normalized_selection_basis.get("reasonZh")
    if (
        isinstance(normalized_selection_basis.get("selectionReasonZh"), str)
        and normalized_selection_basis.get("selectionReasonZh")
        and not normalized_selection_basis.get("reasonZh")
    ):
        normalized_selection_basis["reasonZh"] = normalized_selection_basis.get("selectionReasonZh")
    return {
        "lane": lane,
        "role": role,
        "summaryType": summary_type,
        "strategyId": strategy_id,
        "seedId": seed_id,
        "strategyName": strategy_name,
        "strategyFamily": strategy_family,
        "direction": direction,
        "status": status,
        "metrics": metrics or {},
        "params": params or {},
        "blockers": [item for item in (blockers or []) if item],
        "contenderTieBreakRequired": bool(contender_tie_break_required),
        "testerOnly": bool(tester_only),
        "selectionBasis": normalized_selection_basis,
        "nextActionZh": next_action_zh,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _alias_strategy_ids(selection_basis: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in (
        "scanAliasStrategyId",
        "optimizerAliasStrategyId",
        "scanTopAliasStrategyId",
    ):
        value = selection_basis.get(key)
        if isinstance(value, str) and value and value not in aliases:
            aliases.append(value)
    for value in _list(selection_basis.get("sameParameterSetAs")):
        if isinstance(value, str) and value and value not in aliases:
            aliases.append(value)
    current_cluster_prefixes = (
        "hfm_crypto_btc_near_live_middle_window_",
        "hfm_crypto_btc_near_live_stoploss_ladder_",
        "hfm_crypto_btc_stable_middle_tradeoff_",
    )
    legacy_lineage_prefixes = (
        "hfm_crypto_btc_near_live_followup_",
        "hfm_crypto_btc_near_live_refinement_",
        "hfm_crypto_btc_near_live_stability_",
    )
    if any(alias.startswith(current_cluster_prefixes) for alias in aliases):
        filtered = [
            alias
            for alias in aliases
            if not alias.startswith(legacy_lineage_prefixes)
        ]
        if filtered:
            return filtered
    return aliases


def _alias_strategy_ids_without_self(selection_basis: dict[str, Any], strategy_id: Any) -> list[str]:
    strategy_id_str = str(strategy_id or "")
    return [
        alias
        for alias in _alias_strategy_ids(selection_basis)
        if alias != strategy_id_str
    ]


def _current_near_live_cluster_aliases(source: dict[str, Any], strategy_id: Any) -> list[str]:
    strategy_id_str = str(strategy_id or "")
    candidate_ids: list[str] = []
    for key in ("nearLiveConvergedVariantStrategyIds", "nearLiveMiddleWindowVariantStrategyIds"):
        for alias in _list(source.get(key)):
            if isinstance(alias, str) and alias and alias not in candidate_ids:
                candidate_ids.append(alias)
    if not candidate_ids and bool(source.get("nearLiveChallengerConvergedWithYieldFrontier")):
        inferred_rows = [
            _dict(source.get("mostStableTradeoff")),
            _dict(source.get("highYieldTradeoff")),
            _dict(source.get("nearLiveMiddleWindowFollowupBestTradeoff")),
            _dict(source.get("nearLiveStabilityTradeoff")),
            _dict(source.get("nearLiveStoplossLadderRefinementBestTradeoff")),
        ]
        tertiary_row = (
            _dict(source.get("nearLiveClusterRefinementBestTradeoff"))
            if not _dict(source.get("nearLiveStoplossLadderRefinementBestTradeoff")).get("strategyId")
            else {}
        )
        if tertiary_row:
            inferred_rows.append(tertiary_row)
        for row in inferred_rows:
            alias = row.get("strategyId")
            if isinstance(alias, str) and alias and alias not in candidate_ids:
                candidate_ids.append(alias)
    if strategy_id_str and strategy_id_str in candidate_ids:
        return [alias for alias in candidate_ids if alias != strategy_id_str]
    return []


def _blocker_codes(value: Any) -> list[str]:
    codes: list[str] = []
    for row in _list(value):
        code = row.get("code") if isinstance(row, dict) else row
        if isinstance(code, str) and code and code not in codes:
            codes.append(code)
    return codes


def _merge_unique_codes(*groups: Any) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for code in _blocker_codes(group):
            if code not in merged:
                merged.append(code)
    return merged


def _btc_scan_plan_repair_candidate(plan: dict[str, Any]) -> dict[str, Any]:
    plan_dict = _dict(plan)
    repair_strategy_id = str(plan_dict.get("repairStrategyId") or "")
    candidate_specs = [
        (
            "stableMiddleThirdFollowupBestTradeoff",
            "stableMiddleThirdFollowupOutcomeZh",
            "btcStrategyScan.nextFocusedSearchPlan.stableMiddleThirdFollowupBestTradeoff",
            "stableMiddleThirdFollowup",
            "stable_middle_third_followup",
            (
                "stableMiddleThirdFollowupImprovesAggregate",
                "stableMiddleThirdFollowupImprovesWeakWindow",
                "stableMiddleThirdFollowupImprovesRepair",
            ),
        ),
        (
            "stableMiddleTradeoffFollowupBestTradeoff",
            "stableMiddleTradeoffFollowupOutcomeZh",
            "btcStrategyScan.nextFocusedSearchPlan.stableMiddleTradeoffFollowupBestTradeoff",
            "stableMiddleTradeoffFollowup",
            "stable_middle_tradeoff_followup",
            (
                "stableMiddleTradeoffFollowupImprovesBridge",
                "stableMiddleTradeoffFollowupImprovesWeakWindow",
                "stableMiddleTradeoffFollowupImprovesBaseline",
            ),
        ),
        (
            "stableMiddleWeakWindowBridgeBestTradeoff",
            "stableMiddleWeakWindowBridgeOutcomeZh",
            "btcStrategyScan.nextFocusedSearchPlan.stableMiddleWeakWindowBridgeBestTradeoff",
            "stableMiddleWeakWindowBridge",
            "stable_middle_weak_window_bridge",
            (
                "stableMiddleWeakWindowBridgeImprovesAggregate",
                "stableMiddleWeakWindowBridgeImprovesWeakWindow",
                "stableMiddleWeakWindowBridgeImprovesBaseline",
            ),
        ),
        (
            "stableMiddleWeakWindowConfirmationBestTradeoff",
            "stableMiddleWeakWindowConfirmationOutcomeZh",
            "btcStrategyScan.nextFocusedSearchPlan.stableMiddleWeakWindowConfirmationBestTradeoff",
            "stableMiddleWeakWindowConfirmation",
            "stable_middle_weak_window_confirmation",
            (
                "stableMiddleWeakWindowConfirmationImprovesBaseline",
            ),
        ),
        (
            "stableMiddleThirdRepairBestTradeoff",
            "stableMiddleThirdRepairOutcomeZh",
            "btcStrategyScan.nextFocusedSearchPlan.stableMiddleThirdRepairBestTradeoff",
            "stableMiddleThirdRepair",
            "stable_middle_third_repair",
            (
                "stableMiddleThirdRepairImprovesBaseline",
            ),
        ),
    ]
    fallback: dict[str, Any] | None = None
    selected: dict[str, Any] | None = None
    for (
        tradeoff_key,
        outcome_key,
        source_artifact,
        summary_type,
        strategy_family,
        improvement_keys,
    ) in candidate_specs:
        tradeoff = _dict(plan_dict.get(tradeoff_key))
        strategy_id = str(tradeoff.get("strategyId") or "")
        if not strategy_id:
            continue
        improvement_flags = {
            key: plan_dict.get(key)
            for key in improvement_keys
            if key in plan_dict
        }
        label_zh = (
            plan_dict.get("repairStrategyLabelZh")
            if repair_strategy_id and strategy_id == repair_strategy_id
            else None
        )
        role_zh = (
            plan_dict.get("repairStrategyRoleZh")
            if repair_strategy_id and strategy_id == repair_strategy_id
            else None
        )
        payload = {
            "tradeoff": tradeoff,
            "strategyId": strategy_id,
            "outcomeZh": plan_dict.get(outcome_key),
            "sourceArtifact": source_artifact,
            "summaryType": summary_type,
            "strategyFamily": strategy_family,
            "improvementFlags": improvement_flags,
            "labelZh": label_zh,
            "roleZh": role_zh,
        }
        if fallback is None:
            fallback = payload
        if repair_strategy_id and strategy_id == repair_strategy_id:
            selected = payload
            break
    return selected or fallback or {}


def _mt5_gate_diagnostics(run_gate: dict[str, Any]) -> dict[str, Any]:
    blockers = _blocker_codes(_dict(run_gate.get("gate")).get("blockers"))
    process_evidence_blockers = _blocker_codes(_dict(run_gate.get("supportingProcessEvidence")).get("blockers"))
    blockers = _blocker_codes(blockers + process_evidence_blockers)
    auto_clear_blockers = [code for code in blockers if code == "outside_strategy_tester_window"]
    refresh_blockers = [code for code in blockers if code in ("authorization_lock_expired", "live_dashboard_snapshot_stale")]
    sensitive_blockers = [code for code in blockers if code in (
        "isolated_tester_account_context_not_ready",
        "sensitive_account_context_sync_required",
    )]
    process_blockers = [code for code in blockers if code == "mt5_terminal_process_missing"]
    other_blockers = [
        code for code in blockers
        if code not in auto_clear_blockers + refresh_blockers + sensitive_blockers + process_blockers
    ]
    next_window = _resolved_next_tester_window(_dict(run_gate.get("nextTesterWindow")))
    return {
        "autoClearAtWindowBlockers": auto_clear_blockers,
        "manualRefreshBlockers": refresh_blockers,
        "manualSensitiveBlockers": sensitive_blockers,
        "processRecoveryBlockers": process_blockers,
        "otherBlockers": other_blockers,
        "nextWindowLabel": next_window.get("label"),
        "nextWindowStartJstIso": next_window.get("startJstIso"),
        "minutesUntilStart": next_window.get("minutesUntilStart"),
        "summaryZh": (
            f"自动到点解除={','.join(auto_clear_blockers) if auto_clear_blockers else '无'}；"
            f"需刷新/外部状态={','.join(refresh_blockers) if refresh_blockers else '无'}；"
            f"需恢复进程={','.join(process_blockers) if process_blockers else '无'}；"
            f"需受控人工同步={','.join(sensitive_blockers) if sensitive_blockers else '无'}。"
        ),
    }


def _mt5_preferred_terminal_path(source: dict[str, Any]) -> str:
    direct = str(source.get("preferredTerminalPath") or "")
    if direct:
        return direct
    return str(_dict(source.get("supportingProcessEvidence")).get("preferredTerminalPath") or "")


def _mt5_terminal_restore_action_zh(source: dict[str, Any]) -> str:
    preferred_terminal_path = _mt5_preferred_terminal_path(source)
    if preferred_terminal_path:
        return (
            f"未发现主 MT5 terminal64 进程；先恢复 {preferred_terminal_path} 并恢复 "
            "live dashboard 刷新，否则不能确认 live session freshness。"
        )
    return "未发现主 MT5 terminal64 进程；先恢复主 terminal 并恢复 live dashboard 刷新，否则不能确认 live session freshness。"


def _mt5_terminal_restore_required_action_zh(source: dict[str, Any]) -> str:
    preferred_terminal_path = _mt5_preferred_terminal_path(source)
    if preferred_terminal_path:
        return (
            f"先恢复主 MT5 terminal64 进程（优先: {preferred_terminal_path}）并恢复 "
            "dashboard freshness，再重建 tester gate。"
        )
    return "先恢复主 MT5 terminal64 进程并恢复 dashboard freshness，再重建 tester gate。"


def _permission_chain_healthy(permission_layers: dict[str, Any]) -> bool:
    required_flags = (
        "terminalConnected",
        "accountAuthorized",
        "terminalTradeAllowed",
        "programTradeAllowed",
        "accountTradeAllowed",
        "accountExpertTradeAllowed",
        "focusSymbolTradeAllowed",
    )
    return all(bool(permission_layers.get(flag)) for flag in required_flags)


def _effective_symbol_selection_ok(
    *,
    raw_dashboard_selected: bool,
    runtime_probe_symbol_ok: bool,
    symbol_present_in_runtime_probe: Any,
    runtime_probe_fresh: Any,
) -> bool:
    return bool(
        raw_dashboard_selected
        or (
            bool(runtime_probe_fresh)
            and (
                bool(symbol_present_in_runtime_probe)
                or bool(runtime_probe_symbol_ok)
            )
        )
    )


def _btc_runtime_snapshot(preflight: dict[str, Any]) -> dict[str, Any]:
    dashboard = _dict(preflight.get("dashboardSnapshot"))
    permission_layers = _dict(dashboard.get("permissionLayers"))
    execution_gate_diagnostics = _dict(dashboard.get("executionGateDiagnostics"))
    trade_allowed_diagnostics = _dict(execution_gate_diagnostics.get("tradeAllowed"))
    probe_results = _dict(preflight.get("probeResults"))
    lane_checks = [_dict(row) for row in _list(preflight.get("laneRuntimeChecks"))]
    lane_check = lane_checks[0] if lane_checks else {}
    raw_dashboard_selected = bool(probe_results.get("symbolSelectedInDashboardOk"))
    runtime_probe_symbol_ok = bool(probe_results.get("symbolRuntimeProbeOk"))
    runtime_probe_fresh = lane_check.get("runtimeProbeFresh")
    symbol_present_in_runtime_probe = lane_check.get("symbolPresentInRuntimeProbe")
    permission_chain_healthy = _permission_chain_healthy(permission_layers)
    trade_permission_blocker = permission_layers.get("tradePermissionBlocker")
    symbol_selection_effective_ok = _effective_symbol_selection_ok(
        raw_dashboard_selected=raw_dashboard_selected,
        runtime_probe_symbol_ok=runtime_probe_symbol_ok,
        symbol_present_in_runtime_probe=symbol_present_in_runtime_probe,
        runtime_probe_fresh=runtime_probe_fresh,
    )
    return {
        "targetSymbol": lane_check.get("brokerSymbol"),
        "dashboardFresh": bool(dashboard.get("fresh")),
        "dashboardAgeSeconds": dashboard.get("ageSeconds"),
        "dashboardMaxAgeSeconds": dashboard.get("maxAgeSeconds"),
        "dashboardSymbolCount": dashboard.get("symbolCount"),
        "dashboardSymbolNames": _list(dashboard.get("symbolNames")),
        "symbolSelectedInDashboardOk": raw_dashboard_selected,
        "symbolSelectionEffectiveOk": symbol_selection_effective_ok,
        "symbolRuntimeProbeOk": runtime_probe_symbol_ok,
        "sidecarLiveTickOk": bool(probe_results.get("sidecarLiveTickOk")),
        "spreadProbeOk": bool(probe_results.get("spreadProbeOk")),
        "livePilotModeOk": bool(probe_results.get("livePilotModeOk")),
        "readOnlyModeOff": bool(probe_results.get("readOnlyModeOff")),
        "executionEnabledOk": bool(probe_results.get("executionEnabledOk")),
        "tradeAllowedOk": bool(probe_results.get("tradeAllowedOk")),
        "tradePermissionBlocker": trade_permission_blocker,
        "permissionChainHealthy": permission_chain_healthy,
        "directExecutionBlockerCode": trade_permission_blocker,
        "directExecutionBlockerDetailZh": trade_allowed_diagnostics.get("detailZh"),
        "runtimeProbeFresh": runtime_probe_fresh,
        "runtimeProbeAgeSeconds": lane_check.get("runtimeProbeAgeSeconds"),
        "symbolPresentInSnapshot": lane_check.get("symbolPresentInSnapshot"),
        "symbolPresentInNames": lane_check.get("symbolPresentInNames"),
        "spreadFieldPresent": lane_check.get("spreadFieldPresent"),
        "symbolSelectionEvidenceZh": (
            "dashboard symbol 列未显示目标，但 fresh runtime probe 已证明该 symbol 已被选中并输出只读 tick。"
            if symbol_selection_effective_ok and not raw_dashboard_selected
            else (
                "dashboard symbol 列已直接显示目标 symbol。"
                if raw_dashboard_selected
                else "当前仍缺目标 symbol 的 dashboard/watchlist 选中证据。"
            )
        ),
    }


def _btc_runtime_summary_zh(runtime_snapshot: dict[str, Any]) -> str:
    target_symbol = runtime_snapshot.get("targetSymbol") or "#BTCUSD"
    symbol_names = _list(runtime_snapshot.get("dashboardSymbolNames"))
    symbol_label = ",".join(str(item) for item in symbol_names[:3]) if symbol_names else "无"
    dashboard_age = runtime_snapshot.get("dashboardAgeSeconds")
    runtime_probe_age = runtime_snapshot.get("runtimeProbeAgeSeconds")
    permission_blocker = runtime_snapshot.get("tradePermissionBlocker")
    permission_chain_healthy = runtime_snapshot.get("permissionChainHealthy")
    return (
        f"dashboardFresh={runtime_snapshot.get('dashboardFresh')} ageSeconds={dashboard_age}；"
        f"当前 dashboard symbols={symbol_label}；"
        f"{target_symbol} selectedRaw={runtime_snapshot.get('symbolSelectedInDashboardOk')} "
        f"selectedEffective={runtime_snapshot.get('symbolSelectionEffectiveOk')} "
        f"tick={runtime_snapshot.get('sidecarLiveTickOk')} spread={runtime_snapshot.get('spreadProbeOk')} "
        f"livePilotMode={runtime_snapshot.get('livePilotModeOk')} "
        f"readOnlyOff={runtime_snapshot.get('readOnlyModeOff')} "
        f"executionEnabled={runtime_snapshot.get('executionEnabledOk')} "
        f"tradeAllowed={runtime_snapshot.get('tradeAllowedOk')} "
        f"permissionChainHealthy={permission_chain_healthy} "
        f"tradePermissionBlocker={permission_blocker} "
        f"runtimeProbeAgeSeconds={runtime_probe_age}。"
    )


def _btc_runtime_focus(runtime_snapshot: dict[str, Any], blocker_codes: list[str]) -> tuple[str, str, str]:
    blocker_set = {code for code in blocker_codes if isinstance(code, str)}
    target_symbol = runtime_snapshot.get("targetSymbol") or "#BTCUSD"
    if blocker_set & BTC_RUNTIME_DATA_PLANE_BLOCKERS:
        return (
            f"先补 BTC runtime/data-plane 证据，确认 dashboard/watchlist 已持续输出 {target_symbol} 实时 tick/spread。",
            "BTC 是当前唯一还能继续推进研究的 lane，但缺实时 dashboard/tick/spread 证据。",
            "先补 runtime/data-plane 证据",
        )
    if blocker_set & BTC_EXECUTION_MODE_BLOCKERS or "MT5_DASHBOARD_SNAPSHOT_STALE" in blocker_set:
        permission_blocker = runtime_snapshot.get("tradePermissionBlocker")
        permission_chain_healthy = runtime_snapshot.get("permissionChainHealthy")
        return (
            "先刷新 live16 dashboard，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。",
            (
                "BTC 的 runtime probe 已经有 #BTCUSD 实时 tick/spread；当前主要卡在 dashboard freshness 和执行模式字段，"
                f"permission chain healthy={permission_chain_healthy}，直接交易阻塞为 {permission_blocker or 'UNKNOWN'}，而不是 symbol 取证。"
            ),
            "先刷新 dashboard freshness 与 execution-mode 证据",
        )
    return (
        "继续刷新 BTC runtime 证据并核对 execution lane 审查前置条件。",
        "BTC 仍是当前最接近实盘评审的研究线，先把 runtime 证据和执行闸门核对清楚。",
        "继续核对 runtime 与 execution gate",
    )


def _btc_gate_diagnostics(runtime_snapshot: dict[str, Any], blocker_codes: list[str]) -> dict[str, Any]:
    blockers = [code for code in blocker_codes if isinstance(code, str)]
    data_plane_blockers = [code for code in blockers if code in BTC_RUNTIME_DATA_PLANE_BLOCKERS]
    execution_mode_blockers = [code for code in blockers if code in BTC_EXECUTION_MODE_BLOCKERS]
    external_refresh_blockers = [code for code in blockers if code == "MT5_DASHBOARD_SNAPSHOT_STALE"]
    other_blockers = [
        code for code in blockers
        if code not in data_plane_blockers + execution_mode_blockers + external_refresh_blockers
    ]
    direct_execution_blocker = runtime_snapshot.get("directExecutionBlockerCode")
    permission_chain_healthy = bool(runtime_snapshot.get("permissionChainHealthy"))
    return {
        "externalRefreshBlockers": external_refresh_blockers,
        "dataPlaneBlockers": data_plane_blockers,
        "executionModeBlockers": execution_mode_blockers,
        "otherBlockers": other_blockers,
        "permissionChainHealthy": permission_chain_healthy,
        "directExecutionBlockerCode": direct_execution_blocker,
        "targetSymbol": runtime_snapshot.get("targetSymbol"),
        "summaryZh": (
            f"需外部刷新/新快照={','.join(external_refresh_blockers) if external_refresh_blockers else '无'}；"
            f"需补 data-plane={','.join(data_plane_blockers) if data_plane_blockers else '无'}；"
            f"需切换 execution mode={','.join(execution_mode_blockers) if execution_mode_blockers else '无'}；"
            f"permissionChainHealthy={permission_chain_healthy}；"
            f"directExecutionBlocker={direct_execution_blocker or '无'}。"
        ),
    }


def _btc_readiness_checklist(runtime_snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {
            "id": "runtime_probe_fresh",
            "ok": bool(runtime_snapshot.get("runtimeProbeFresh")),
            "labelZh": "runtime probe fresh",
            "dependencyCheckIds": [],
            "sourceArtifact": "liveRuntimePreflightProbe.laneRuntimeChecks",
            "evidenceKeyZh": "runtimeProbeFresh/runtimeProbeAgeSeconds",
            "nextActionZh": "继续用 evidence-intake 刷新 runtime probe 新鲜度。",
        },
        {
            "id": "dashboard_fresh",
            "ok": bool(runtime_snapshot.get("dashboardFresh")),
            "labelZh": "dashboard fresh",
            "dependencyCheckIds": [],
            "sourceArtifact": "liveRuntimePreflightProbe.dashboardSnapshot",
            "evidenceKeyZh": "dashboardSnapshot.fresh/ageSeconds",
            "nextActionZh": "刷新 live16 dashboard，直到 freshness 回到可评审窗口内。",
        },
        {
            "id": "tick_spread_ready",
            "ok": bool(runtime_snapshot.get("sidecarLiveTickOk")) and bool(runtime_snapshot.get("spreadProbeOk")),
            "labelZh": "tick/spread ready",
            "dependencyCheckIds": ["runtime_probe_fresh"],
            "sourceArtifact": "liveRuntimePreflightProbe.probeResults",
            "evidenceKeyZh": "sidecarLiveTickOk/spreadProbeOk",
            "nextActionZh": "保持 sidecar tick/spread 输出连续，不需要改执行模式。",
        },
        {
            "id": "symbol_selected_in_dashboard",
            "ok": bool(runtime_snapshot.get("symbolSelectionEffectiveOk")),
            "labelZh": "dashboard/runtime symbol selected",
            "dependencyCheckIds": ["dashboard_fresh"],
            "sourceArtifact": "liveRuntimePreflightProbe.probeResults",
            "evidenceKeyZh": "symbolSelectedInDashboardOk/symbolRuntimeProbeOk",
            "nextActionZh": "确认 dashboard symbol 列或 fresh runtime probe 至少一侧已持续证明 #BTCUSD 处于选中输出路径。",
        },
        {
            "id": "permission_chain_healthy",
            "ok": bool(runtime_snapshot.get("permissionChainHealthy")),
            "labelZh": "permission chain healthy",
            "dependencyCheckIds": ["dashboard_fresh"],
            "sourceArtifact": "liveRuntimePreflightProbe.dashboardSnapshot.permissionLayers",
            "evidenceKeyZh": "terminal/account/program/symbol permission layers",
            "nextActionZh": "保持权限链为绿；当前不是主要 blocker。",
        },
        {
            "id": "live_pilot_mode",
            "ok": bool(runtime_snapshot.get("livePilotModeOk")),
            "labelZh": "live pilot mode",
            "dependencyCheckIds": ["dashboard_fresh"],
            "sourceArtifact": "liveRuntimePreflightProbe.dashboardSnapshot.executionGateDiagnostics",
            "evidenceKeyZh": "executionGateDiagnostics.livePilotMode",
            "nextActionZh": "等待外部 runtime 把 EA 模式切到 livePilotMode=true 后再复核。",
        },
        {
            "id": "read_only_mode_off",
            "ok": bool(runtime_snapshot.get("readOnlyModeOff")),
            "labelZh": "read-only mode off",
            "dependencyCheckIds": ["dashboard_fresh"],
            "sourceArtifact": "liveRuntimePreflightProbe.dashboardSnapshot.executionGateDiagnostics",
            "evidenceKeyZh": "executionGateDiagnostics.readOnlyMode",
            "nextActionZh": "解除 shadow/read-only 熔断后再刷新 evidence-intake。",
        },
        {
            "id": "execution_enabled",
            "ok": bool(runtime_snapshot.get("executionEnabledOk")),
            "labelZh": "execution enabled",
            "dependencyCheckIds": ["dashboard_fresh", "live_pilot_mode", "read_only_mode_off"],
            "sourceArtifact": "liveRuntimePreflightProbe.dashboardSnapshot.executionGateDiagnostics",
            "evidenceKeyZh": "executionGateDiagnostics.executionEnabled",
            "nextActionZh": "等待 executionEnabled=true 的 runtime 证据出现。",
        },
        {
            "id": "trade_allowed",
            "ok": bool(runtime_snapshot.get("tradeAllowedOk")),
            "labelZh": "trade allowed",
            "dependencyCheckIds": ["dashboard_fresh", "live_pilot_mode", "read_only_mode_off", "execution_enabled"],
            "sourceArtifact": "liveRuntimePreflightProbe.dashboardSnapshot.executionGateDiagnostics",
            "evidenceKeyZh": "executionGateDiagnostics.tradeAllowed",
            "nextActionZh": "在 livePilot/readOnly/executionEnabled 条件满足后再复核 tradeAllowed。",
        },
    ]
    ready_count = sum(1 for row in rows if row["ok"])
    return {
        "status": "BTC_READINESS_CHECKLIST_READY",
        "readyCount": ready_count,
        "totalCount": len(rows),
        "rows": rows,
        "summaryZh": (
            f"已满足 {ready_count}/{len(rows)} 项；"
            f"未满足: {', '.join(row['id'] for row in rows if not row['ok']) or '无'}。"
        ),
    }


def _mt5_readiness_checklist(mt5_lane_readiness: dict[str, Any], run_gate: dict[str, Any]) -> dict[str, Any]:
    gate_blockers = set(_list(mt5_lane_readiness.get("blockers")))
    tester_context = _dict(run_gate.get("testerAccountContext"))
    auth_lock_ready = "authorization_lock_expired" not in gate_blockers
    lock_refresh_guidance = _mt5_lock_refresh_guidance(run_gate)
    rows = [
        {
            "id": "live_session_fresh",
            "ok": bool(mt5_lane_readiness.get("liveSessionFresh")),
            "labelZh": "live session fresh",
            "dependencyCheckIds": ["dashboard_fresh"],
            "sourceArtifact": "championTesterRunGate.gate.liveSession",
            "evidenceKeyZh": "liveSession.ok/status",
            "nextActionZh": "恢复主 MT5 dashboard/session 刷新后再复核 liveSession。",
        },
        {
            "id": "tester_window_open",
            "ok": "outside_strategy_tester_window" not in gate_blockers,
            "labelZh": "tester window open",
            "dependencyCheckIds": [],
            "sourceArtifact": "championTesterRunGate.nextTesterWindow",
            "evidenceKeyZh": "nextTesterWindow.status/minutesUntilStart",
            "nextActionZh": "等待 nightly tester window 打开后自动清除此项。",
        },
        {
            "id": "authorization_lock_ready",
            "ok": auth_lock_ready,
            "labelZh": "authorization lock ready",
            "dependencyCheckIds": [],
            "sourceArtifact": "championTesterRunGate.gate.authorizationLock",
            "evidenceKeyZh": "authorizationLock.ok/status",
            "nextActionZh": (
                "tester-only authorization lock 已就绪；仅在过期或缺失后再刷新。"
                if auth_lock_ready
                else (
                    str(lock_refresh_guidance.get("nextRequiredActionZh") or "")
                    or "刷新 tester-only lock 草案和授权状态。"
                )
            ),
        },
        {
            "id": "dashboard_fresh",
            "ok": "live_dashboard_snapshot_stale" not in gate_blockers,
            "labelZh": "dashboard fresh",
            "dependencyCheckIds": [],
            "sourceArtifact": "championTesterRunGate.gate.blockers",
            "evidenceKeyZh": "live_dashboard_snapshot_stale",
            "nextActionZh": "恢复主 MT5 dashboard 新鲜快照，再重建 tester gate。",
        },
        {
            "id": "isolated_account_context_ready",
            "ok": "isolated_tester_account_context_not_ready" not in gate_blockers,
            "labelZh": "isolated account context ready",
            "dependencyCheckIds": [],
            "sourceArtifact": "isolatedTesterAccountContextStatus",
            "evidenceKeyZh": "ready/missingTarget",
            "nextActionZh": "完成隔离 tester account context 的受控补齐后再复核。",
        },
        {
            "id": "sensitive_sync_cleared",
            "ok": not bool(tester_context.get("sensitiveAccountContextSyncRequired")),
            "labelZh": "sensitive sync cleared",
            "dependencyCheckIds": ["isolated_account_context_ready"],
            "sourceArtifact": "isolatedTesterAccountContextStatus.separateSyncReview",
            "evidenceKeyZh": "sensitiveAccountContextSyncRequired",
            "nextActionZh": "等待单独受控 sensitive sync 审查完成。",
        },
        {
            "id": "tester_can_run_now",
            "ok": bool(mt5_lane_readiness.get("canRunTester")),
            "labelZh": "tester can run now",
            "dependencyCheckIds": [
                "live_session_fresh",
                "tester_window_open",
                "authorization_lock_ready",
                "dashboard_fresh",
                "isolated_account_context_ready",
                "sensitive_sync_cleared",
            ],
            "sourceArtifact": "championTesterRunGate.decision",
            "evidenceKeyZh": "decision.canRunIsolatedTester",
            "nextActionZh": "只有前置 gate 全部转绿后，此项才会自动变为 true。",
        },
    ]
    ready_count = sum(1 for row in rows if row["ok"])
    return {
        "status": "MT5_READINESS_CHECKLIST_READY",
        "readyCount": ready_count,
        "totalCount": len(rows),
        "rows": rows,
        "summaryZh": (
            f"已满足 {ready_count}/{len(rows)} 项；"
            f"未满足: {', '.join(row['id'] for row in rows if not row['ok']) or '无'}。"
        ),
    }


def _readiness_priority_rows(
    readiness: dict[str, Any],
    *,
    allowed_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows = [_dict(row) for row in _list(readiness.get("rows"))]
    failed_rows = {
        str(row.get("id")): row
        for row in rows
        if isinstance(row.get("id"), str) and not bool(row.get("ok"))
    }
    reverse_deps: dict[str, list[str]] = {}
    for row_id, row in failed_rows.items():
        for dep_id in _list(row.get("dependencyCheckIds")):
            dep_str = str(dep_id)
            if dep_str in failed_rows:
                reverse_deps.setdefault(dep_str, []).append(row_id)

    def descendants(root_id: str) -> list[str]:
        seen: set[str] = set()
        stack = list(reverse_deps.get(root_id, []))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(reverse_deps.get(current, []))
        return sorted(seen)

    allowed = {item for item in allowed_ids if isinstance(item, str)} if allowed_ids else None
    priority_rows: list[dict[str, Any]] = []
    for row_id, row in failed_rows.items():
        if allowed is not None and row_id not in allowed:
            continue
        direct_blocked_ids = sorted(reverse_deps.get(row_id, []))
        transitive_blocked_ids = descendants(row_id)
        priority_rows.append({
            "id": row_id,
            "labelZh": row.get("labelZh"),
            "priorityScore": 1 + len(transitive_blocked_ids),
            "directBlockedIds": direct_blocked_ids,
            "directBlockedCount": len(direct_blocked_ids),
            "transitiveBlockedIds": transitive_blocked_ids,
            "transitiveBlockedCount": len(transitive_blocked_ids),
            "nextActionZh": row.get("nextActionZh"),
        })
    priority_rows.sort(
        key=lambda row: (
            -int(_num(row.get("priorityScore"))),
            -int(_num(row.get("transitiveBlockedCount"))),
            str(row.get("id") or ""),
        )
    )
    return priority_rows


def _mt5_tester_snapshot(run_gate: dict[str, Any]) -> dict[str, Any]:
    gate = _dict(run_gate.get("gate"))
    live_session = _dict(gate.get("liveSession"))
    next_window = _resolved_next_tester_window(_dict(run_gate.get("nextTesterWindow")))
    queue = _dict(gate.get("queue"))
    tasks = [_dict(row) for row in _list(queue.get("tasks"))]
    ready_candidate_ids = [
        row.get("candidateId")
        for row in tasks
        if row.get("status") == "ready" and isinstance(row.get("candidateId"), str)
    ]
    ab_candidate_ids = [candidate_id for candidate_id in ready_candidate_ids if "tpsl" not in candidate_id][:2]
    variant_candidate_ids = [candidate_id for candidate_id in ready_candidate_ids if "tpsl" in candidate_id][:4]
    return {
        "liveSessionOk": bool(live_session.get("ok")),
        "liveSessionStatus": live_session.get("status"),
        "openTradeCount": live_session.get("openTradeCount"),
        "marginInUse": live_session.get("marginInUse"),
        "accountNumber": live_session.get("accountNumber"),
        "server": live_session.get("server"),
        "nextTesterWindowLabel": next_window.get("label"),
        "nextTesterWindowStartJstIso": next_window.get("startJstIso"),
        "nextTesterWindowEndJstIso": next_window.get("endJstIso"),
        "minutesUntilStart": next_window.get("minutesUntilStart"),
        "queueCount": queue.get("queueCount"),
        "readyCandidateIds": ready_candidate_ids,
        "abCandidateIds": ab_candidate_ids,
        "variantCandidateIds": variant_candidate_ids,
    }


def _mt5_tester_summary_zh(tester_snapshot: dict[str, Any]) -> str:
    return (
        f"liveSessionOk={tester_snapshot.get('liveSessionOk')} "
        f"window={tester_snapshot.get('nextTesterWindowLabel') or 'unknown'} "
        f"start={tester_snapshot.get('nextTesterWindowStartJstIso') or 'unknown'} "
        f"minutesUntilStart={tester_snapshot.get('minutesUntilStart')} "
        f"queueCount={tester_snapshot.get('queueCount')}。"
    )


def _mt5_window_briefing(mt5_lane_readiness: dict[str, Any]) -> dict[str, Any]:
    gate = _dict(mt5_lane_readiness.get("gateDiagnostics"))
    readiness = _dict(mt5_lane_readiness.get("readinessChecklist"))
    tester_snapshot = _dict(mt5_lane_readiness.get("testerSnapshot"))
    readiness_rows = [_dict(row) for row in _list(readiness.get("rows"))]
    readiness_ready_count = int(_num(readiness.get("readyCount")))
    readiness_total_count = int(_num(readiness.get("totalCount")))
    minutes_until_start = gate.get("minutesUntilStart")
    if minutes_until_start is None:
        phase = "WINDOW_UNKNOWN"
    elif _num(minutes_until_start) <= 0:
        phase = "IN_WINDOW"
    elif _num(minutes_until_start) <= 5:
        phase = "PRE_WINDOW_FINAL_5_MIN"
    elif _num(minutes_until_start) <= 15:
        phase = "PRE_WINDOW_FINAL_15_MIN"
    elif _num(minutes_until_start) <= 30:
        phase = "PRE_WINDOW_FINAL_30_MIN"
    elif _num(minutes_until_start) <= 60:
        phase = "PRE_WINDOW_FINAL_HOUR"
    elif _num(minutes_until_start) <= 180:
        phase = "PRE_WINDOW_SAME_DAY"
    else:
        phase = "WAITING_WINDOW"

    failed_rows = [
        _dict(row)
        for row in _list(readiness.get("rows"))
        if not bool(_dict(row).get("ok"))
    ]
    failed_ids = [str(row.get("id")) for row in failed_rows if isinstance(row.get("id"), str)]
    pre_window_check_ids = [
        check_id for check_id in (
            "dashboard_fresh",
            "live_session_fresh",
            "authorization_lock_ready",
            "isolated_account_context_ready",
            "sensitive_sync_cleared",
        )
        if check_id in failed_ids
    ]
    auto_clear_check_ids = [
        check_id for check_id in ("tester_window_open",)
        if check_id in failed_ids
    ]
    window_open_realized_check_ids = [
        check_id for check_id in ("tester_window_open",)
        if check_id in {
            str(row.get("id"))
            for row in readiness_rows
            if bool(row.get("ok"))
        }
    ] if phase == "IN_WINDOW" else []
    in_window_check_ids = [
        check_id for check_id in ("tester_can_run_now",)
        if check_id in failed_ids
    ]
    residual_after_window_open_check_ids = pre_window_check_ids + in_window_check_ids
    expected_ready_count_after_window_open = readiness_ready_count + (1 if "tester_window_open" in auto_clear_check_ids else 0)
    if phase == "IN_WINDOW":
        window_open_gain_count = len(window_open_realized_check_ids)
        expected_ready_count_after_window_open = readiness_ready_count
    else:
        window_open_gain_count = max(expected_ready_count_after_window_open - readiness_ready_count, 0)
    remaining_after_window_open_count = len(residual_after_window_open_check_ids)
    window_open_gain_ratio = (
        round(window_open_gain_count / readiness_total_count, 4)
        if readiness_total_count else 0.0
    )
    pre_window_priority_rows = _readiness_priority_rows(readiness, allowed_ids=pre_window_check_ids)
    highest_leverage_pre_window_score = int(_num(_dict(pre_window_priority_rows[0]).get("priorityScore"))) if pre_window_priority_rows else 0
    highest_leverage_pre_window_check_ids = [
        str(row.get("id"))
        for row in pre_window_priority_rows
        if int(_num(_dict(row).get("priorityScore"))) == highest_leverage_pre_window_score
    ]
    post_window_priority_rows = _readiness_priority_rows(readiness, allowed_ids=residual_after_window_open_check_ids)
    highest_leverage_post_window_score = int(_num(_dict(post_window_priority_rows[0]).get("priorityScore"))) if post_window_priority_rows else 0
    highest_leverage_post_window_check_ids = [
        str(row.get("id"))
        for row in post_window_priority_rows
        if int(_num(_dict(row).get("priorityScore"))) == highest_leverage_post_window_score
    ]
    if phase == "PRE_WINDOW_FINAL_5_MIN":
        final_sprint_check_ids = highest_leverage_pre_window_check_ids[:1]
    elif phase == "PRE_WINDOW_FINAL_15_MIN":
        final_sprint_check_ids = highest_leverage_pre_window_check_ids[:2]
    else:
        final_sprint_check_ids = []
    post_window_primary_summary_zh = (
        f"开窗后第一优先仍是 {', '.join(highest_leverage_post_window_check_ids)}；"
        f"{'已自动解除' if phase == 'IN_WINDOW' else '自动解除仅包括'} "
        f"{', '.join(window_open_realized_check_ids if phase == 'IN_WINDOW' else auto_clear_check_ids) if (window_open_realized_check_ids if phase == 'IN_WINDOW' else auto_clear_check_ids) else '无'}。"
        if highest_leverage_post_window_check_ids
        else "开窗后暂无额外主优先 residual。"
    )
    ab_candidate_ids = _list(tester_snapshot.get("abCandidateIds"))
    variant_candidate_ids = _list(tester_snapshot.get("variantCandidateIds"))

    if phase == "IN_WINDOW":
        summary_zh = (
            "tester window 已打开；如果前置 refresh/sensitive gate 已转绿，"
            f"优先跑 A/B 主对照 {', '.join(ab_candidate_ids) if ab_candidate_ids else '无'}，"
            f"否则先清 {', '.join(highest_leverage_post_window_check_ids) if highest_leverage_post_window_check_ids else '无'}，再看 TP/SL 变体。"
        )
    elif phase == "PRE_WINDOW_FINAL_5_MIN":
        summary_zh = (
            f"距离 tester window 约 {minutes_until_start} 分钟；"
            f"最后 5 分钟只盯 {', '.join(final_sprint_check_ids) if final_sprint_check_ids else '无'}，"
            f"到点后自动解除 {', '.join(auto_clear_check_ids) if auto_clear_check_ids else '无'}，"
            f"开窗后第一优先仍是 {', '.join(highest_leverage_post_window_check_ids) if highest_leverage_post_window_check_ids else '无'}；"
            f"若 residual 未清，窗口内仍会先被 {', '.join(highest_leverage_post_window_check_ids) if highest_leverage_post_window_check_ids else '无'} 卡住。"
        )
    elif phase == "PRE_WINDOW_FINAL_15_MIN":
        summary_zh = (
            f"距离 tester window 约 {minutes_until_start} 分钟；"
            f"最后冲刺只盯 {', '.join(final_sprint_check_ids) if final_sprint_check_ids else '无'}，"
            f"到点后自动解除 {', '.join(auto_clear_check_ids) if auto_clear_check_ids else '无'}，"
            f"其余 residual 仍包括 {', '.join(residual_after_window_open_check_ids) if residual_after_window_open_check_ids else '无'}；"
            f"开窗后第一优先仍是 {', '.join(highest_leverage_post_window_check_ids) if highest_leverage_post_window_check_ids else '无'}；"
            f"窗口内先跑 {', '.join(ab_candidate_ids) if ab_candidate_ids else 'A/B 主对照'}。"
        )
    elif phase in {"PRE_WINDOW_FINAL_30_MIN", "PRE_WINDOW_FINAL_HOUR"}:
        summary_zh = (
            f"距离 tester window 约 {minutes_until_start} 分钟；"
            f"窗口前优先清 {', '.join(pre_window_check_ids) if pre_window_check_ids else '无'}，"
            f"到点后自动解除 {', '.join(auto_clear_check_ids) if auto_clear_check_ids else '无'}，"
            f"若其余 gate 未清，窗口打开后仍会剩 {', '.join(residual_after_window_open_check_ids) if residual_after_window_open_check_ids else '无'}；"
            f"窗口内先跑 {', '.join(ab_candidate_ids) if ab_candidate_ids else 'A/B 主对照'}。"
        )
    elif phase == "PRE_WINDOW_SAME_DAY":
        summary_zh = (
            f"今天稍后进入 tester window；先处理 {', '.join(pre_window_check_ids) if pre_window_check_ids else '无'}，"
            "避免到点后仍被 refresh/sensitive gate 卡住。"
        )
    else:
        summary_zh = (
            "仍在等待下一次 tester window；"
            f"当前主要先清 {', '.join(pre_window_check_ids) if pre_window_check_ids else '无'}。"
        )

    return {
        "phase": phase,
        "minutesUntilStart": minutes_until_start,
        "readinessNow": {
            "readyCount": readiness_ready_count,
            "totalCount": readiness_total_count,
            "ratio": f"{readiness_ready_count}/{readiness_total_count}" if readiness_total_count else "0/0",
        },
        "expectedReadinessAfterWindowOpen": {
            "readyCount": expected_ready_count_after_window_open,
            "totalCount": readiness_total_count,
            "ratio": (
                f"{expected_ready_count_after_window_open}/{readiness_total_count}"
                if readiness_total_count else "0/0"
            ),
        },
        "windowOpenGainCount": window_open_gain_count,
        "windowOpenGainRatio": window_open_gain_ratio,
        "preWindowCheckIds": pre_window_check_ids,
        "preWindowPriorityRows": pre_window_priority_rows,
        "highestLeveragePreWindowCheckIds": highest_leverage_pre_window_check_ids,
        "postWindowPriorityRows": post_window_priority_rows,
        "highestLeveragePostWindowCheckIds": highest_leverage_post_window_check_ids,
        "postWindowPrimarySummaryZh": post_window_primary_summary_zh,
        "finalSprintCheckIds": final_sprint_check_ids,
        "autoClearCheckIds": auto_clear_check_ids,
        "residualAfterWindowOpenCheckIds": residual_after_window_open_check_ids,
        "residualAfterWindowOpenCount": remaining_after_window_open_count,
        "inWindowCheckIds": in_window_check_ids,
        "postWindowStillBlocked": bool(residual_after_window_open_check_ids),
        "windowOpenRealizedCheckIds": window_open_realized_check_ids,
        "windowOpenEffectZh": (
            (
                f"窗口已打开，已实得 {window_open_gain_count} 项通过，"
                f"当前仍剩 {remaining_after_window_open_count} 项未闭环。"
            )
            if phase == "IN_WINDOW"
            else (
                f"窗口打开预计只新增 {window_open_gain_count} 项通过，"
                f"仍剩 {remaining_after_window_open_count} 项未闭环。"
            )
        ),
        "abCandidateIds": ab_candidate_ids,
        "variantCandidateIds": variant_candidate_ids,
        "summaryZh": summary_zh,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _forex_pack(ace: dict[str, Any], retest: dict[str, Any], tpsl: dict[str, Any]) -> dict[str, Any]:
    ace_forex = _dict(ace.get("topQualifiedForex"))
    retest_forex = _dict(retest.get("forexChampion"))
    contender_review = _dict(ace.get("forexContenderReview")) or _dict(retest.get("forexContenderReview"))
    tpsl_forex = _dict(tpsl.get("forexMt5"))
    source = retest_forex or ace_forex
    backtest = _dict(retest_forex.get("backtest"))
    walk_forward = _dict(retest_forex.get("walkForward"))
    return {
        "role": "primaryForexAce",
        "status": retest_forex.get("status") or ("FOREX_ACE_CANDIDATE_READY" if ace_forex else "FOREX_ACE_MISSING"),
        "seedId": source.get("seedId"),
        "strategyId": source.get("strategyId"),
        "strategyFamily": source.get("strategyFamily") or "RSI_Reversal",
        "direction": source.get("direction") or "LONG",
        "metrics": _metrics({**ace_forex, **backtest, **walk_forward}),
        "contenderTieBreakRequired": bool(contender_review.get("requiresParallelTesterForward")),
        "contenders": _list(contender_review.get("contenders")),
        "tpSlStatus": tpsl_forex.get("status"),
        "recommendedTpSl": _dict(tpsl_forex.get("recommended")),
        "bestBlockedTpSl": _dict(tpsl_forex.get("bestBlockedCandidate")),
        "testerVariantQueue": _list(tpsl_forex.get("testerVariantQueue")),
        "blockers": _list(retest_forex.get("blockers")) + _list(tpsl_forex.get("blockers")),
        "nextActionZh": (
            "并列冠军先做隔离 tester/forward A/B 复验；粗筛 TP/SL 不直接改 live preset。"
            if contender_review.get("requiresParallelTesterForward")
            else "外币冠军进入隔离 tester/forward 复验；不直接升级实盘。"
        ),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _forex_shortlist(forex_pack: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    contender_tie_break_required = bool(forex_pack.get("contenderTieBreakRequired"))
    seen: set[str] = set()

    def add_item(item: dict[str, Any]) -> None:
        if item.get("summaryType") == "tester_forward_variant":
            logical_id = str(item.get("strategyId") or "")
        else:
            logical_id = str(item.get("seedId") or item.get("strategyId") or "")
        if logical_id in seen:
            return
        seen.add(logical_id)
        items.append(item)

    primary = _strategy_shortlist_item(
        lane="forexMt5",
        role="primaryChampion",
        summary_type="stable_forex_champion",
        strategy_id=forex_pack.get("strategyId"),
        seed_id=forex_pack.get("seedId"),
        strategy_family=forex_pack.get("strategyFamily"),
        direction=forex_pack.get("direction"),
        status=forex_pack.get("status"),
        metrics=_dict(forex_pack.get("metrics")),
        blockers=_list(forex_pack.get("blockers")),
        selection_basis={
            "sourceArtifact": "championRetest.forexChampion",
            "reasonZh": "当前 MT5 主冠军，因 walk-forward 稳定性和回测/前向质量同时达标而入围。",
            "comparisonFocus": [
                "walkForwardStability",
                "profitFactor",
                "sharpe",
                "forwardNetR",
            ],
        },
        next_action_zh=(
            "并列冠军必须先做隔离 tester/forward A/B。"
            if contender_tie_break_required
            else forex_pack.get("nextActionZh")
        ),
        contender_tie_break_required=contender_tie_break_required,
    )
    add_item(primary)
    for index, contender in enumerate(_list(forex_pack.get("contenders"))[:2], start=1):
        row = _dict(contender)
        add_item(
            _strategy_shortlist_item(
                lane="forexMt5",
                role=f"parallelContender{index}",
                summary_type="parallel_tie_break_contender",
                strategy_id=row.get("strategyId"),
                seed_id=row.get("seedId"),
                strategy_family=forex_pack.get("strategyFamily"),
                direction=forex_pack.get("direction"),
                status=forex_pack.get("status"),
                metrics=_metrics(row),
                selection_basis={
                    "sourceArtifact": "aceStrategyScout.forexContenderReview",
                    "reasonZh": "并列 contender，当前与主冠军接近，需要样本外 tester-forward A/B 决胜。",
                    "comparisonFocus": [
                        "fitness",
                        "walkForwardStability",
                        "profitFactor",
                        "sharpe",
                    ],
                },
                next_action_zh="保留并列 contender，等待隔离 tester/forward 样本外胜出。",
                contender_tie_break_required=contender_tie_break_required,
            )
        )
    if len(items) < 3:
        for index, variant in enumerate(_list(forex_pack.get("testerVariantQueue")), start=1):
            row = _dict(variant)
            add_item(
                _strategy_shortlist_item(
                    lane="forexMt5",
                    role=f"testerVariant{index}",
                    summary_type="tester_forward_variant",
                    strategy_id=f"{forex_pack.get('strategyId') or forex_pack.get('seedId') or 'forex'}::{row.get('variantId') or index}",
                    seed_id=forex_pack.get("seedId"),
                    strategy_family=forex_pack.get("strategyFamily"),
                    direction=forex_pack.get("direction"),
                    status=forex_pack.get("tpSlStatus") or forex_pack.get("status"),
                    metrics={
                        "riskPips": row.get("riskPips"),
                        "tpPips": row.get("tpPips"),
                        "rewardRatio": row.get("rewardRatio"),
                        "coarseScreenScore": row.get("coarseScreenScore"),
                    },
                    params=_dict(row.get("testerOverrides")),
                    blockers=_list(row.get("coarseScreenBlockers")),
                    selection_basis={
                        "sourceArtifact": "tpSlOptimizer.forexMt5.testerVariantQueue",
                        "reasonZh": "TP/SL 粗筛未直接通过，但保留该 tester-only 变体做并排前向复验。",
                        "comparisonFocus": [
                            "coarseScreenScore",
                            "riskPips",
                            "rewardRatio",
                            "tpPips",
                        ],
                    },
                    next_action_zh="保留为 tester-only TP/SL 变体，和主冠军并排复验。",
                    contender_tie_break_required=contender_tie_break_required,
                )
            )
            if len(items) >= 3:
                break
    return items


def _btc_shortlist(final_pick: dict[str, Any], btc: dict[str, Any], scan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    stable_source = _dict(btc.get("recommendedStable"))
    plan = _dict(scan.get("nextFocusedSearchPlan"))
    distinct_scan_candidates = _btc_distinct_scan_top_candidates(scan)
    scan_most_stable = (
        _dict(plan.get("mostStableTradeoff"))
        or _dict(scan.get("mostStableTradeoff"))
        or _dict(scan.get("topRecommendation"))
    )
    scan_high_yield = (
        _dict(plan.get("highYieldTradeoff"))
        or _dict(scan.get("currentHighestYieldTradeoff"))
    )

    def add_item(item: dict[str, Any]) -> None:
        strategy_id = str(item.get("strategyId") or "")
        identity_key = _btc_identity_key_from_params(strategy_id, _dict(item.get("params")))
        if not strategy_id or not identity_key or identity_key in seen:
            return
        seen.add(identity_key)
        items.append(item)

    def add_scan_candidate(
        row: dict[str, Any],
        *,
        role: str,
        summary_type: str,
        next_action: str,
        selection_basis_extra: dict[str, Any] | None = None,
    ) -> None:
        add_item(
            _strategy_shortlist_item(
                lane="btcCryptoCfd",
                role=role,
                summary_type=summary_type,
                strategy_id=row.get("strategyId"),
                strategy_name=row.get("strategyName"),
                strategy_family=row.get("strategyFamily") or "ema_slope_regime",
                status=row.get("status") or scan.get("status"),
                metrics={
                    "pnlUsd": _dict(row.get("fullWindowMetrics")).get("pnlUsd") or row.get("pnlUsd"),
                    "roiPct": _dict(row.get("fullWindowMetrics")).get("roiPct") or row.get("roiPct"),
                    "sharpe": _dict(row.get("fullWindowMetrics")).get("sharpe") or row.get("sharpe"),
                    "maxDrawdownPct": _dict(row.get("fullWindowMetrics")).get("maxDrawdownPct") or row.get("maxDrawdownPct"),
                    "tradeCount": _dict(row.get("fullWindowMetrics")).get("tradeCount") or row.get("tradeCount"),
                    "validWindowCount": row.get("validWindowCount"),
                    "windowCount": row.get("windowCount"),
                },
                params={
                    "bias": _dict(row.get("parameters")).get("bias") or row.get("bias"),
                    "takeProfitPriceMove": _dict(row.get("parameters")).get("takeProfitPriceMove") or row.get("takeProfitPriceMove"),
                    "stopLossPriceMove": _dict(row.get("parameters")).get("stopLossPriceMove") or row.get("stopLossPriceMove"),
                    "maxHoldBars": _dict(row.get("parameters")).get("maxHoldBars") or row.get("maxHoldBars"),
                    "cooldownBars": _dict(row.get("parameters")).get("cooldownBars") or row.get("cooldownBars"),
                },
                blockers=_list(row.get("blockers")),
                selection_basis={
                    "sourceArtifact": "btcStrategyScan",
                    "reasonZh": next_action,
                    "comparisonFocus": [
                        "validWindowCount",
                        "tradeCount",
                        "sharpe",
                        "pnlUsd",
                    ],
                    **(selection_basis_extra or {}),
                },
                next_action_zh=next_action,
            )
        )

    def stability_rank(row: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        metrics = _dict(row.get("fullWindowMetrics"))
        blocker_count = float(len(_list(row.get("blockers"))))
        return (
            _num(row.get("validWindowCount")),
            -_num(row.get("majorWindowFailureCount")),
            -blocker_count,
            _num(metrics.get("tradeCount")),
            _num(metrics.get("sharpe")),
            _num(metrics.get("pnlUsd")),
        )

    stable_anchor_source = scan_most_stable if scan_most_stable.get("strategyId") else final_pick
    stable_anchor_params = (
        _btc_source_params(stable_anchor_source)
        or _dict(final_pick.get("tpSlSummary"))
        or _dict(final_pick.get("params"))
        or _dict(stable_source.get("parameters"))
    )
    stable_identity = _btc_identity_key_from_params(
        stable_anchor_source.get("strategyId"),
        stable_anchor_params,
    )
    stable_scan_alias = next((
        row
        for row in distinct_scan_candidates
        if _btc_identity_key_from_params(
            row.get("strategyId"),
            _btc_source_params(row),
        ) == stable_identity
    ), {})

    final_pick_compact = _btc_candidate(final_pick, role="selectedDefault")
    add_item(
        _strategy_shortlist_item(
            lane="btcCryptoCfd",
            role="stableAnchor",
            summary_type="most_stable_btc_candidate",
            strategy_id=stable_anchor_source.get("strategyId") or final_pick_compact.get("strategyId"),
            strategy_name=stable_anchor_source.get("strategyName") or final_pick_compact.get("strategyName"),
            strategy_family=stable_anchor_source.get("strategyFamily") or final_pick_compact.get("strategyFamily"),
            status=stable_anchor_source.get("status") or final_pick_compact.get("status") or btc.get("status"),
            metrics={
                **_dict(final_pick_compact.get("metrics")),
                "pnlUsd": _dict(stable_anchor_source.get("fullWindowMetrics")).get("pnlUsd") or stable_anchor_source.get("pnlUsd") or _dict(final_pick_compact.get("metrics")).get("pnlUsd"),
                "roiPct": _dict(stable_anchor_source.get("fullWindowMetrics")).get("roiPct") or stable_anchor_source.get("roiPct") or _dict(final_pick_compact.get("metrics")).get("roiPct"),
                "sharpe": _dict(stable_anchor_source.get("fullWindowMetrics")).get("sharpe") or stable_anchor_source.get("sharpe") or _dict(final_pick_compact.get("metrics")).get("sharpe"),
                "maxDrawdownPct": _dict(stable_anchor_source.get("fullWindowMetrics")).get("maxDrawdownPct") or stable_anchor_source.get("maxDrawdownPct") or _dict(final_pick_compact.get("metrics")).get("maxDrawdownPct"),
                "tradeCount": _dict(stable_anchor_source.get("fullWindowMetrics")).get("tradeCount") or stable_anchor_source.get("tradeCount") or _dict(final_pick_compact.get("metrics")).get("tradeCount"),
                "validWindowCount": stable_anchor_source.get("validWindowCount") or final_pick.get("validWindowCount") or stable_source.get("validWindowCount"),
                "windowCount": stable_anchor_source.get("windowCount") or final_pick.get("windowCount") or stable_source.get("windowCount"),
            },
            params=stable_anchor_params,
            blockers=_list(stable_anchor_source.get("blockers")) or _list(final_pick_compact.get("blockers")),
            selection_basis={
                "sourceArtifact": (
                    "btcStrategyScan.nextFocusedSearchPlan.mostStableTradeoff"
                    if scan_most_stable.get("strategyId")
                    else "tpSlOptimizer.finalAdvisoryPick"
                ),
                "reasonZh": (
                    "当前 fresh scan 的 mostStableTradeoff 已收敛到该候选；优先把它提升为默认稳定锚点继续复验。"
                    if scan_most_stable.get("strategyId")
                    else "当前默认稳健候选，优先因为 validWindowCount 更高且没有负收益窗口。"
                ),
                "comparisonFocus": [
                    "validWindowCount",
                    "negativeWindowCount",
                    "middleThirdWeakness",
                ],
                "stableMiddleThirdRepairBestStrategyId": _dict(plan.get("stableMiddleThirdRepairBestTradeoff")).get("strategyId"),
                "stableMiddleThirdRepairImprovesBaseline": plan.get("stableMiddleThirdRepairImprovesBaseline"),
                "stableMiddleThirdRepairOutcomeZh": plan.get("stableMiddleThirdRepairOutcomeZh"),
                "stableMiddleThirdFollowupBestStrategyId": _dict(plan.get("stableMiddleThirdFollowupBestTradeoff")).get("strategyId"),
                "stableMiddleThirdFollowupImprovesAggregate": plan.get("stableMiddleThirdFollowupImprovesAggregate"),
                "stableMiddleThirdFollowupImprovesWeakWindow": plan.get("stableMiddleThirdFollowupImprovesWeakWindow"),
                "stableMiddleThirdFollowupImprovesRepair": plan.get("stableMiddleThirdFollowupImprovesRepair"),
                "stableMiddleThirdFollowupOutcomeZh": plan.get("stableMiddleThirdFollowupOutcomeZh"),
                "stableMiddleWeakWindowConfirmationBestStrategyId": _dict(plan.get("stableMiddleWeakWindowConfirmationBestTradeoff")).get("strategyId"),
                "stableMiddleWeakWindowConfirmationImprovesBaseline": plan.get("stableMiddleWeakWindowConfirmationImprovesBaseline"),
                "stableMiddleWeakWindowConfirmationOutcomeZh": plan.get("stableMiddleWeakWindowConfirmationOutcomeZh"),
                "stableMiddleWeakWindowBridgeBestStrategyId": _dict(plan.get("stableMiddleWeakWindowBridgeBestTradeoff")).get("strategyId"),
                "stableMiddleWeakWindowBridgeImprovesAggregate": plan.get("stableMiddleWeakWindowBridgeImprovesAggregate"),
                "stableMiddleWeakWindowBridgeImprovesWeakWindow": plan.get("stableMiddleWeakWindowBridgeImprovesWeakWindow"),
                "stableMiddleWeakWindowBridgeImprovesBaseline": plan.get("stableMiddleWeakWindowBridgeImprovesBaseline"),
                "stableMiddleWeakWindowBridgeOutcomeZh": plan.get("stableMiddleWeakWindowBridgeOutcomeZh"),
                "stableMiddleTradeoffFollowupBestTradeoff": _dict(plan.get("stableMiddleTradeoffFollowupBestTradeoff")),
                "stableMiddleTradeoffFollowupBestStrategyId": _dict(plan.get("stableMiddleTradeoffFollowupBestTradeoff")).get("strategyId"),
                "stableMiddleTradeoffFollowupImprovesBridge": plan.get("stableMiddleTradeoffFollowupImprovesBridge"),
                "stableMiddleTradeoffFollowupImprovesWeakWindow": plan.get("stableMiddleTradeoffFollowupImprovesWeakWindow"),
                "stableMiddleTradeoffFollowupImprovesBaseline": plan.get("stableMiddleTradeoffFollowupImprovesBaseline"),
                "stableMiddleTradeoffFollowupOutcomeZh": plan.get("stableMiddleTradeoffFollowupOutcomeZh"),
                "repairStrategyId": plan.get("repairStrategyId"),
                "repairStrategyLabelZh": plan.get("repairStrategyLabelZh"),
                "repairStrategyRoleZh": plan.get("repairStrategyRoleZh"),
                "recommendedFocusedRetestOrder": [
                    item for item in _list(plan.get("recommendedFocusedRetestOrder"))
                    if isinstance(item, str) and item
                ],
                "scanAliasStrategyId": stable_scan_alias.get("strategyId"),
                "scanAliasStrategyName": stable_scan_alias.get("strategyName"),
                "scanAliasSourceArtifact": "btcStrategyScan" if stable_scan_alias else None,
                "sameParameterSetAs": _btc_aliases_for_identity(stable_identity, scan, exclude_strategy_id=stable_anchor_source.get("strategyId")),
            },
            next_action_zh=(
                "继续把当前 scan most-stable 锚点做多窗口稳定性复验，不进入实盘。"
                if scan_most_stable.get("strategyId")
                else "继续补 middle_third 和多窗口稳定性，不进入实盘。"
            ),
        )
    )

    target_seeking_source = _dict(btc.get("recommendedTargetSeeking"))
    high_yield_plan = scan_high_yield
    high_yield_identity = _btc_identity_key_from_params(
        high_yield_plan.get("strategyId"),
        {
            "bias": high_yield_plan.get("bias"),
            "takeProfitPriceMove": high_yield_plan.get("takeProfitPriceMove"),
            "stopLossPriceMove": high_yield_plan.get("stopLossPriceMove"),
            "maxHoldBars": high_yield_plan.get("maxHoldBars"),
            "cooldownBars": high_yield_plan.get("cooldownBars"),
        },
    )
    high_yield_scan_alias = next((
        _dict(row)
        for row in _list(scan.get("topCandidates"))
        if _btc_identity_key_from_params(
            _dict(row).get("strategyId"),
            {
                "bias": _dict(_dict(row).get("parameters")).get("bias") or _dict(row).get("bias"),
                "takeProfitPriceMove": _dict(_dict(row).get("parameters")).get("takeProfitPriceMove") or _dict(row).get("takeProfitPriceMove"),
                "stopLossPriceMove": _dict(_dict(row).get("parameters")).get("stopLossPriceMove") or _dict(row).get("stopLossPriceMove"),
                "maxHoldBars": _dict(_dict(row).get("parameters")).get("maxHoldBars") or _dict(row).get("maxHoldBars"),
                "cooldownBars": _dict(_dict(row).get("parameters")).get("cooldownBars") or _dict(row).get("cooldownBars"),
            },
        ) == high_yield_identity
    ), {})
    optimizer_target_identity = _btc_identity_key_from_params(
        target_seeking_source.get("strategyId"),
        _btc_source_params(target_seeking_source),
    )
    high_yield_matches_optimizer_target = bool(
        high_yield_identity
        and optimizer_target_identity
        and high_yield_identity == optimizer_target_identity
    )
    strongest_converged_with_stable = bool(
        high_yield_identity
        and stable_identity
        and high_yield_identity == stable_identity
    )
    high_yield_aliases = [
        alias
        for alias in (
            target_seeking_source.get("strategyId") if high_yield_matches_optimizer_target else None,
            high_yield_scan_alias.get("strategyId"),
        )
        if isinstance(alias, str) and alias and alias != str(high_yield_plan.get("strategyId") or "")
    ]
    if high_yield_plan and not strongest_converged_with_stable:
        add_scan_candidate(
            high_yield_plan,
            role="highYieldTradeoff",
            summary_type="highYieldTradeoff",
            next_action="高收益候选继续补窗口，不直接替代稳健默认。",
            selection_basis_extra={
                "optimizerAliasStrategyId": (
                    target_seeking_source.get("strategyId")
                    if high_yield_matches_optimizer_target
                    else None
                ),
                "optimizerAliasSourceArtifact": (
                    "tpSlOptimizer.recommendedTargetSeeking"
                    if high_yield_matches_optimizer_target
                    else None
                ),
                "optimizerBaselineStrategyId": (
                    target_seeking_source.get("strategyId")
                    if target_seeking_source and not high_yield_matches_optimizer_target
                    else None
                ),
                "optimizerBaselineSourceArtifact": (
                    "tpSlOptimizer.recommendedTargetSeeking"
                    if target_seeking_source and not high_yield_matches_optimizer_target
                    else None
                ),
                "frontierChallengeZh": (
                    "fresh scan 已找到比当前 optimizer target 更激进的高收益 frontier，先作为 challenger 跟踪，不直接当成同参簇。"
                    if target_seeking_source and not high_yield_matches_optimizer_target
                    else None
                ),
                "scanTopAliasStrategyId": (
                    high_yield_scan_alias.get("strategyId")
                    if high_yield_scan_alias.get("strategyId") != high_yield_plan.get("strategyId")
                    else None
                ),
                "scanTopAliasStrategyName": high_yield_scan_alias.get("strategyName"),
                "scanTopAliasSourceArtifact": (
                    "btcStrategyScan.topCandidates"
                    if high_yield_scan_alias and high_yield_scan_alias.get("strategyId") != high_yield_plan.get("strategyId")
                    else None
                ),
                "yieldLeaderConfirmationBestStrategyId": _dict(plan.get("yieldLeaderConfirmationBestTradeoff")).get("strategyId"),
                "yieldLeaderConfirmationImprovesBaseline": plan.get("yieldLeaderConfirmationImprovesBaseline"),
                "yieldLeaderConfirmationOutcomeZh": plan.get("yieldLeaderConfirmationOutcomeZh"),
                "sameParameterSetAs": high_yield_aliases,
            },
        )

    near_live_plan = _dict(plan.get("nearLiveStabilityTradeoff"))
    near_live_repair_plan = _dict(plan.get("nearLiveStabilityRepairBestTradeoff"))
    near_live_repair_improves_baseline = bool(plan.get("nearLiveStabilityRepairImprovesBaseline"))
    near_live_followup_plan = _dict(plan.get("nearLiveStabilityFollowupBestTradeoff"))
    near_live_followup_improves_repair = bool(plan.get("nearLiveStabilityFollowupImprovesRepair"))
    near_live_refinement_plan = _dict(plan.get("nearLiveStabilityRefinementBestTradeoff"))
    near_live_refinement_improves_followup = bool(plan.get("nearLiveStabilityRefinementImprovesFollowup"))
    near_live_middle_window_plan = _dict(plan.get("nearLiveMiddleWindowFollowupBestTradeoff"))
    near_live_middle_window_improves_followup = bool(plan.get("nearLiveMiddleWindowFollowupImprovesFollowup"))
    near_live_cluster_refinement_plan = _dict(plan.get("nearLiveClusterRefinementBestTradeoff"))
    near_live_cluster_refinement_improves_contender = bool(plan.get("nearLiveClusterRefinementImprovesContender"))
    near_live_challenger_converged_with_yield = bool(plan.get("nearLiveChallengerConvergedWithYieldFrontier"))
    stable_candidates: list[dict[str, Any]] = []
    if not near_live_plan:
        for row in _list(scan.get("topCandidates")):
            candidate = _dict(row)
            strategy_id = candidate.get("strategyId")
            params = _dict(candidate.get("parameters"))
            identity_key = _btc_identity_key_from_params(strategy_id, {
                "bias": params.get("bias"),
                "takeProfitPriceMove": params.get("takeProfitPriceMove"),
                "stopLossPriceMove": params.get("stopLossPriceMove"),
                "maxHoldBars": params.get("maxHoldBars"),
                "cooldownBars": params.get("cooldownBars"),
            })
            if not strategy_id or identity_key in seen:
                continue
            stable_candidates.append(candidate)
    stable_alternative = (
        near_live_cluster_refinement_plan
        if near_live_cluster_refinement_improves_contender and near_live_cluster_refinement_plan.get("strategyId")
        else (
        near_live_middle_window_plan
        if near_live_middle_window_improves_followup and near_live_middle_window_plan.get("strategyId")
        else (
        near_live_refinement_plan
        if near_live_refinement_improves_followup and near_live_refinement_plan.get("strategyId")
        else (
        near_live_followup_plan
        if near_live_followup_improves_repair and near_live_followup_plan.get("strategyId")
        else (
        near_live_repair_plan
        if near_live_repair_improves_baseline and near_live_repair_plan.get("strategyId")
        else near_live_plan
        )
        )
        )
        )
    ) or (max(stable_candidates, key=stability_rank) if stable_candidates else {})
    if stable_alternative:
        alternative_identity = _btc_identity_key_from_params(
            stable_alternative.get("strategyId"),
            _btc_source_params(stable_alternative),
        )
        if alternative_identity and alternative_identity == stable_identity:
            stable_alternative = next(
                (
                    row for row in distinct_scan_candidates
                    if _btc_identity_key_from_params(row.get("strategyId"), _btc_source_params(row)) != stable_identity
                ),
                {},
            )
    if stable_alternative:
        add_scan_candidate(
            stable_alternative,
            role="stabilityAlternative",
            summary_type="scanStableAlternative",
            next_action=(
                "当前稳健锚点与收益 frontier 已收敛到同一参数簇；把 next distinct near-live contender 提升为新的稳定性替补，继续对比默认锚点的分段质量。"
                if near_live_challenger_converged_with_yield
                else (
                "near-live middle-window follow-up 已在保住当前有效窗口数的前提下改善 weak window；把它提升为新的稳定性替补，继续对比现任稳健默认的分段质量。"
                if near_live_middle_window_improves_followup and near_live_middle_window_plan.get("strategyId")
                else (
                "near-live refinement 已推翻当前 follow-up winner；把它提升为新的稳定性替补，继续对比现任稳健默认的分段质量。"
                if near_live_refinement_improves_followup and near_live_refinement_plan.get("strategyId")
                else (
                "near-live follow-up 已推翻当前 repair winner；把它提升为新的稳定性替补，继续对比现任稳健默认的分段质量。"
                if near_live_followup_improves_repair and near_live_followup_plan.get("strategyId")
                else (
                "near-live 修复版已推翻旧 sample-balanced challenger；把它提升为新的稳定性替补，继续对比现任稳健默认的分段质量。"
                if near_live_repair_improves_baseline and near_live_repair_plan.get("strategyId")
                else "稳定性替补候选保留在 focused retest，对比现任稳健默认的分段质量。"
                )
                )
                )
                )
            ),
            selection_basis_extra={
                "nearLiveBaselineStrategyId": near_live_plan.get("strategyId"),
                "nearLiveRepairBestStrategyId": _dict(plan.get("nearLiveStabilityRepairBestTradeoff")).get("strategyId"),
                "nearLiveRepairImprovesBaseline": plan.get("nearLiveStabilityRepairImprovesBaseline"),
                "nearLiveRepairOutcomeZh": plan.get("nearLiveStabilityRepairOutcomeZh"),
                "nearLiveFollowupBestStrategyId": near_live_followup_plan.get("strategyId"),
                "nearLiveFollowupImprovesRepair": plan.get("nearLiveStabilityFollowupImprovesRepair"),
                "nearLiveFollowupOutcomeZh": plan.get("nearLiveStabilityFollowupOutcomeZh"),
                "nearLiveRefinementBestStrategyId": near_live_refinement_plan.get("strategyId"),
                "nearLiveRefinementImprovesFollowup": plan.get("nearLiveStabilityRefinementImprovesFollowup"),
                "nearLiveRefinementOutcomeZh": plan.get("nearLiveStabilityRefinementOutcomeZh"),
                "nearLiveMiddleWindowFollowupBestStrategyId": near_live_middle_window_plan.get("strategyId"),
                "nearLiveMiddleWindowFollowupImprovesFollowup": plan.get("nearLiveMiddleWindowFollowupImprovesFollowup"),
                "nearLiveMiddleWindowFollowupOutcomeZh": plan.get("nearLiveMiddleWindowFollowupOutcomeZh"),
                "nearLiveClusterRefinementBestStrategyId": near_live_cluster_refinement_plan.get("strategyId"),
                "nearLiveClusterRefinementImprovesContender": plan.get("nearLiveClusterRefinementImprovesContender"),
                "nearLiveClusterRefinementOutcomeZh": plan.get("nearLiveClusterRefinementOutcomeZh"),
                "nearLiveTempoRefinementBestStrategyId": _dict(plan.get("nearLiveTempoRefinementBestTradeoff")).get("strategyId"),
                "nearLiveTempoRefinementImprovesContender": plan.get("nearLiveTempoRefinementImprovesContender"),
                "nearLiveTempoRefinementOutcomeZh": plan.get("nearLiveTempoRefinementOutcomeZh"),
                "nearLiveStoplossLadderRefinementBestStrategyId": _dict(plan.get("nearLiveStoplossLadderRefinementBestTradeoff")).get("strategyId"),
                "nearLiveStoplossLadderRefinementImprovesContender": plan.get("nearLiveStoplossLadderRefinementImprovesContender"),
                "nearLiveStoplossLadderRefinementOutcomeZh": plan.get("nearLiveStoplossLadderRefinementOutcomeZh"),
                "nearLiveStoplossLadderFollowupMicroBestStrategyId": _dict(plan.get("nearLiveStoplossLadderFollowupMicroBestTradeoff")).get("strategyId"),
                "nearLiveStoplossLadderFollowupMicroImprovesRefinement": plan.get("nearLiveStoplossLadderFollowupMicroImprovesRefinement"),
                "nearLiveStoplossLadderFollowupMicroImprovesContender": plan.get("nearLiveStoplossLadderFollowupMicroImprovesContender"),
                "nearLiveStoplossLadderFollowupMicroOutcomeZh": plan.get("nearLiveStoplossLadderFollowupMicroOutcomeZh"),
                "nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId": _dict(
                    plan.get("nearLiveStoplossLadderFollowupMicroFollowupBestTradeoff")
                ).get("strategyId"),
                "nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro": plan.get(
                    "nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro"
                ),
                "nearLiveStoplossLadderFollowupMicroFollowupImprovesContender": plan.get(
                    "nearLiveStoplossLadderFollowupMicroFollowupImprovesContender"
                ),
                "nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh": plan.get(
                    "nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh"
                ),
                "nearLiveExitRefinementBestStrategyId": _dict(plan.get("nearLiveExitRefinementBestTradeoff")).get("strategyId"),
                "nearLiveExitRefinementImprovesContender": plan.get("nearLiveExitRefinementImprovesContender"),
                "nearLiveExitRefinementOutcomeZh": plan.get("nearLiveExitRefinementOutcomeZh"),
                "nearLiveChallengerConvergedWithYieldFrontier": plan.get("nearLiveChallengerConvergedWithYieldFrontier"),
                "sameParameterSetAs": _current_near_live_cluster_aliases(plan, stable_alternative.get("strategyId")),
            },
        )
    else:
        fallback = _dict(plan.get("sampleRichQualityTradeoff")) or _dict(plan.get("qualityRepairTradeoff"))
        add_scan_candidate(
            fallback,
            role="sampleRichBridge",
            summary_type="sampleRichQualityTradeoff",
            next_action="样本丰富候选只作为桥接修复方向。",
        )
    high_yield_item = next((row for row in items if _dict(row).get("role") == "highYieldTradeoff"), None)
    if high_yield_item:
        high_yield_selection_basis = _dict(_dict(high_yield_item).get("selectionBasis"))
        high_yield_selection_basis.update({
            "nearLiveBaselineStrategyId": near_live_plan.get("strategyId"),
            "nearLiveRepairBestStrategyId": _dict(plan.get("nearLiveStabilityRepairBestTradeoff")).get("strategyId"),
            "nearLiveRepairImprovesBaseline": plan.get("nearLiveStabilityRepairImprovesBaseline"),
            "nearLiveRepairOutcomeZh": plan.get("nearLiveStabilityRepairOutcomeZh"),
            "nearLiveFollowupBestStrategyId": near_live_followup_plan.get("strategyId"),
            "nearLiveFollowupImprovesRepair": plan.get("nearLiveStabilityFollowupImprovesRepair"),
            "nearLiveFollowupOutcomeZh": plan.get("nearLiveStabilityFollowupOutcomeZh"),
            "nearLiveRefinementBestStrategyId": near_live_refinement_plan.get("strategyId"),
            "nearLiveRefinementImprovesFollowup": plan.get("nearLiveStabilityRefinementImprovesFollowup"),
            "nearLiveRefinementOutcomeZh": plan.get("nearLiveStabilityRefinementOutcomeZh"),
            "nearLiveMiddleWindowFollowupBestStrategyId": near_live_middle_window_plan.get("strategyId"),
            "nearLiveMiddleWindowFollowupImprovesFollowup": plan.get("nearLiveMiddleWindowFollowupImprovesFollowup"),
            "nearLiveMiddleWindowFollowupOutcomeZh": plan.get("nearLiveMiddleWindowFollowupOutcomeZh"),
            "nearLiveClusterRefinementBestStrategyId": near_live_cluster_refinement_plan.get("strategyId"),
            "nearLiveClusterRefinementImprovesContender": plan.get("nearLiveClusterRefinementImprovesContender"),
            "nearLiveClusterRefinementOutcomeZh": plan.get("nearLiveClusterRefinementOutcomeZh"),
            "nearLiveTempoRefinementBestStrategyId": _dict(plan.get("nearLiveTempoRefinementBestTradeoff")).get("strategyId"),
            "nearLiveTempoRefinementImprovesContender": plan.get("nearLiveTempoRefinementImprovesContender"),
            "nearLiveTempoRefinementOutcomeZh": plan.get("nearLiveTempoRefinementOutcomeZh"),
            "nearLiveStoplossLadderRefinementBestStrategyId": _dict(plan.get("nearLiveStoplossLadderRefinementBestTradeoff")).get("strategyId"),
            "nearLiveStoplossLadderRefinementImprovesContender": plan.get("nearLiveStoplossLadderRefinementImprovesContender"),
            "nearLiveStoplossLadderRefinementOutcomeZh": plan.get("nearLiveStoplossLadderRefinementOutcomeZh"),
            "nearLiveStoplossLadderFollowupMicroBestStrategyId": _dict(plan.get("nearLiveStoplossLadderFollowupMicroBestTradeoff")).get("strategyId"),
            "nearLiveStoplossLadderFollowupMicroImprovesRefinement": plan.get("nearLiveStoplossLadderFollowupMicroImprovesRefinement"),
            "nearLiveStoplossLadderFollowupMicroImprovesContender": plan.get("nearLiveStoplossLadderFollowupMicroImprovesContender"),
            "nearLiveStoplossLadderFollowupMicroOutcomeZh": plan.get("nearLiveStoplossLadderFollowupMicroOutcomeZh"),
            "nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId": _dict(
                plan.get("nearLiveStoplossLadderFollowupMicroFollowupBestTradeoff")
            ).get("strategyId"),
            "nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro": plan.get(
                "nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro"
            ),
            "nearLiveStoplossLadderFollowupMicroFollowupImprovesContender": plan.get(
                "nearLiveStoplossLadderFollowupMicroFollowupImprovesContender"
            ),
            "nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh": plan.get(
                "nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh"
            ),
            "nearLiveExitRefinementBestStrategyId": _dict(plan.get("nearLiveExitRefinementBestTradeoff")).get("strategyId"),
            "nearLiveExitRefinementImprovesContender": plan.get("nearLiveExitRefinementImprovesContender"),
            "nearLiveExitRefinementOutcomeZh": plan.get("nearLiveExitRefinementOutcomeZh"),
        })
        high_yield_item["selectionBasis"] = high_yield_selection_basis
    repair_candidate = _btc_scan_plan_repair_candidate(plan)
    repair_tradeoff_plan = _dict(repair_candidate.get("tradeoff"))
    repair_tradeoff_strategy_id = repair_candidate.get("strategyId")
    repair_tradeoff_outcome_zh = (
        repair_candidate.get("outcomeZh")
        if isinstance(repair_candidate.get("outcomeZh"), str)
        else None
    )
    repair_tradeoff_summary_type = (
        repair_candidate.get("summaryType")
        if isinstance(repair_candidate.get("summaryType"), str)
        else "stableMiddleTradeoffFollowup"
    )
    repair_tradeoff_strategy_family = (
        repair_candidate.get("strategyFamily")
        if isinstance(repair_candidate.get("strategyFamily"), str)
        else "stable_middle_tradeoff_followup"
    )
    repair_tradeoff_source_artifact = (
        repair_candidate.get("sourceArtifact")
        if isinstance(repair_candidate.get("sourceArtifact"), str)
        else "btcStrategyScan.nextFocusedSearchPlan.stableMiddleTradeoffFollowupBestTradeoff"
    )
    repair_tradeoff_selection_basis = _dict(repair_candidate.get("improvementFlags"))
    repair_tradeoff_default_reason_zh = (
        repair_tradeoff_outcome_zh
        or (
            f"{repair_candidate.get('labelZh')} 作为当前第三条观察候选继续复验。"
            if isinstance(repair_candidate.get("labelZh"), str) and repair_candidate.get("labelZh")
            else "当前 repair 观察候选继续保留在 focused retest。"
        )
    )
    if repair_tradeoff_strategy_id and len(items) < 3:
        add_item(
            _strategy_shortlist_item(
                lane="btcCryptoCfd",
                role="repairObservation",
                summary_type=repair_tradeoff_summary_type,
                strategy_id=repair_tradeoff_plan.get("strategyId"),
                strategy_name=repair_tradeoff_plan.get("strategyName") or repair_tradeoff_plan.get("strategyId"),
                strategy_family=repair_tradeoff_plan.get("strategyFamily") or repair_tradeoff_strategy_family,
                status="BTC_REPAIR_OBSERVATION_READY",
                metrics={
                    "pnlUsd": repair_tradeoff_plan.get("pnlUsd"),
                    "sharpe": repair_tradeoff_plan.get("sharpe"),
                    "maxDrawdownPct": repair_tradeoff_plan.get("maxDrawdownPct"),
                    "tradeCount": repair_tradeoff_plan.get("tradeCount"),
                    "validWindowCount": repair_tradeoff_plan.get("validWindowCount"),
                    "windowCount": repair_tradeoff_plan.get("windowCount"),
                },
                params={
                    "bias": repair_tradeoff_plan.get("bias"),
                    "takeProfitPriceMove": repair_tradeoff_plan.get("takeProfitPriceMove"),
                    "stopLossPriceMove": repair_tradeoff_plan.get("stopLossPriceMove"),
                    "maxHoldBars": repair_tradeoff_plan.get("maxHoldBars"),
                    "cooldownBars": repair_tradeoff_plan.get("cooldownBars"),
                },
                blockers=["HFM_MIDDLE_THIRD_NOT_FULLY_REPAIRED"],
                selection_basis={
                    "sourceArtifact": repair_tradeoff_source_artifact,
                    "reasonZh": repair_tradeoff_default_reason_zh,
                    "comparisonFocus": [
                        "validWindowCount",
                        "tradeCount",
                        "sharpe",
                        "pnlUsd",
                        "middleThirdWeakness",
                    ],
                    **repair_tradeoff_selection_basis,
                    f"{repair_tradeoff_summary_type}OutcomeZh": repair_tradeoff_outcome_zh,
                },
                next_action_zh=repair_tradeoff_default_reason_zh,
            )
        )
    role_priority = {
        "stableAnchor": 0,
        "stabilityAlternative": 1,
        "highYieldTradeoff": 2,
        "repairObservation": 3,
        "sampleRichBridge": 4,
    }
    items.sort(key=lambda row: (role_priority.get(str(_dict(row).get("role") or ""), 99), str(_dict(row).get("strategyId") or "")))
    return items


def _btc_parameter_clusters(btc_items: list[dict[str, Any]], btc: dict[str, Any], scan: dict[str, Any]) -> dict[str, Any]:
    clusters: dict[str, dict[str, Any]] = {}

    def add_member(
        *,
        strategy_id: Any,
        params: dict[str, Any],
        metrics: dict[str, Any],
        valid_window_count: Any,
        blockers: list[Any],
        source_artifact: str,
        preferred_role: str | None = None,
    ) -> None:
        cluster_key = _btc_identity_key_from_params(strategy_id, params)
        strategy_id_str = str(strategy_id or "")
        if not cluster_key or not strategy_id_str:
            return
        cluster = clusters.setdefault(cluster_key, {
            "clusterId": cluster_key,
            "representativeParams": params,
            "memberStrategyIds": [],
            "sourceArtifacts": [],
            "bestValidWindowCount": None,
            "bestPnlUsd": None,
            "bestSharpe": None,
            "preferredRole": None,
            "canonicalStrategyId": None,
            "canonicalLocked": False,
            "blockerUnion": [],
            "recommendedResearchPriority": None,
            "recommendedResearchReasonZh": None,
        })
        if strategy_id_str not in cluster["memberStrategyIds"]:
            cluster["memberStrategyIds"].append(strategy_id_str)
        if source_artifact not in cluster["sourceArtifacts"]:
            cluster["sourceArtifacts"].append(source_artifact)
        for blocker in blockers:
            if isinstance(blocker, str) and blocker and blocker not in cluster["blockerUnion"]:
                cluster["blockerUnion"].append(blocker)
        current_valid = cluster.get("bestValidWindowCount")
        valid_count = _num(valid_window_count, default=-1)
        current_best_valid = _num(current_valid, default=-1)
        pnl_usd = _num(metrics.get("pnlUsd"), default=-1)
        current_best_pnl = _num(cluster.get("bestPnlUsd"), default=-1)
        sharpe = _num(metrics.get("sharpe"), default=-1)
        current_best_sharpe = _num(cluster.get("bestSharpe"), default=-1)
        if preferred_role and not cluster.get("canonicalLocked"):
            cluster["canonicalStrategyId"] = strategy_id_str
            cluster["bestValidWindowCount"] = valid_window_count
            cluster["bestPnlUsd"] = metrics.get("pnlUsd")
            cluster["bestSharpe"] = metrics.get("sharpe")
            cluster["canonicalLocked"] = True
        elif (
            not cluster.get("canonicalLocked")
            and (
            cluster.get("canonicalStrategyId") is None
            or valid_count > current_best_valid
            or (valid_count == current_best_valid and pnl_usd > current_best_pnl)
            or (valid_count == current_best_valid and pnl_usd == current_best_pnl and sharpe > current_best_sharpe)
            )
        ):
            cluster["canonicalStrategyId"] = strategy_id_str
            cluster["bestValidWindowCount"] = valid_window_count
            cluster["bestPnlUsd"] = metrics.get("pnlUsd")
            cluster["bestSharpe"] = metrics.get("sharpe")
        if preferred_role and not cluster.get("preferredRole"):
            cluster["preferredRole"] = preferred_role

    for item in btc_items:
        selection_basis = _dict(item.get("selectionBasis"))
        params = _dict(item.get("params"))
        metrics = _dict(item.get("metrics"))
        valid_window_count = metrics.get("validWindowCount") or item.get("validWindowCount")
        add_member(
            strategy_id=item.get("strategyId"),
            params=params,
            metrics=metrics,
            valid_window_count=valid_window_count,
            blockers=_list(item.get("blockers")),
            source_artifact=str(selection_basis.get("sourceArtifact") or "btcShortlist"),
            preferred_role=str(item.get("role") or "") or None,
        )
        for alias_id in _alias_strategy_ids(selection_basis):
            add_member(
                strategy_id=alias_id,
                params=params,
                metrics=metrics,
                valid_window_count=valid_window_count,
                blockers=_list(item.get("blockers")),
                source_artifact="btcShortlist.alias",
                preferred_role=str(item.get("role") or "") or None,
            )

    for row in _list(scan.get("topCandidates")):
        candidate = _dict(row)
        params = _dict(candidate.get("parameters"))
        metrics = _dict(candidate.get("fullWindowMetrics"))
        add_member(
            strategy_id=candidate.get("strategyId"),
            params=params,
            metrics=metrics,
            valid_window_count=candidate.get("validWindowCount"),
            blockers=_list(candidate.get("blockers")),
            source_artifact="btcStrategyScan.topCandidates",
        )

    for name in ("highYieldTradeoff", "nearLiveStabilityTradeoff", "qualityRepairTradeoff", "sampleRichQualityTradeoff"):
        row = _dict(_dict(scan.get("nextFocusedSearchPlan")).get(name))
        params = {
            "bias": row.get("bias"),
            "takeProfitPriceMove": row.get("takeProfitPriceMove"),
            "stopLossPriceMove": row.get("stopLossPriceMove"),
            "maxHoldBars": row.get("maxHoldBars"),
            "cooldownBars": row.get("cooldownBars"),
        }
        metrics = {
            "pnlUsd": row.get("pnlUsd"),
            "sharpe": row.get("sharpe"),
            "tradeCount": row.get("tradeCount"),
        }
        add_member(
            strategy_id=row.get("strategyId"),
            params=params,
            metrics=metrics,
            valid_window_count=row.get("validWindowCount"),
            blockers=[],
            source_artifact=f"btcStrategyScan.nextFocusedSearchPlan.{name}",
        )

    for name in ("recommendedStable", "recommendedTargetSeeking", "finalAdvisoryPick"):
        row = _dict(btc.get(name))
        params = _dict(row.get("parameters")) or _dict(row.get("params")) or _dict(row.get("tpSlSummary"))
        metrics = _dict(row.get("fullWindowMetrics"))
        add_member(
            strategy_id=row.get("strategyId"),
            params=params,
            metrics=metrics,
            valid_window_count=row.get("validWindowCount"),
            blockers=_list(row.get("blockers")),
            source_artifact=f"tpSlOptimizer.{name}",
        )

    for recommendation in _list(_dict(scan.get("nextFocusedSearchPlan")).get("recommendations")):
        row = _dict(recommendation)
        basis_strategy_id = str(row.get("basisStrategyId") or "")
        if not basis_strategy_id:
            continue
        for cluster in clusters.values():
            member_ids = [item for item in _list(cluster.get("memberStrategyIds")) if isinstance(item, str)]
            canonical_id = str(cluster.get("canonicalStrategyId") or "")
            if basis_strategy_id == canonical_id or basis_strategy_id in member_ids:
                priority = row.get("priority")
                current_priority = cluster.get("recommendedResearchPriority")
                if current_priority is None or (_num(priority, default=999) < _num(current_priority, default=999)):
                    cluster["recommendedResearchPriority"] = priority
                    cluster["recommendedResearchReasonZh"] = row.get("reasonZh")
                break

    role_rank = {
        "stableAnchor": 0,
        "highYieldTradeoff": 1,
        "stabilityAlternative": 2,
        "sampleRichBridge": 3,
    }

    def cluster_sort_key(cluster: dict[str, Any]) -> tuple[float, float, float, float]:
        return (
            _num(cluster.get("bestValidWindowCount")),
            _num(cluster.get("bestPnlUsd")),
            _num(cluster.get("bestSharpe")),
            -float(len(_list(cluster.get("blockerUnion")))),
        )

    def selection_status_zh(preferred_role: str | None) -> str:
        return {
            "stableAnchor": "当前稳健默认簇",
            "highYieldTradeoff": "当前高收益候选簇",
            "stabilityAlternative": "当前稳定替补簇",
            "sampleRichBridge": "样本桥接候选簇",
        }.get(preferred_role or "", "观察中参数簇")

    rows: list[dict[str, Any]] = []
    for cluster in sorted(
        clusters.values(),
        key=lambda row: (
            role_rank.get(str(row.get("preferredRole") or ""), 99),
            _num(row.get("recommendedResearchPriority"), default=999),
            cluster_sort_key(row),
        ),
        reverse=False,
    ):
        member_ids = _list(cluster.get("memberStrategyIds"))
        canonical_strategy_id = cluster.get("canonicalStrategyId")
        aliases = [item for item in member_ids if item != canonical_strategy_id]
        rows.append({
            "clusterId": cluster.get("clusterId"),
            "canonicalStrategyId": canonical_strategy_id,
            "preferredRole": cluster.get("preferredRole"),
            "selectionStatusZh": selection_status_zh(cluster.get("preferredRole")),
            "representativeParams": cluster.get("representativeParams"),
            "memberStrategyIds": member_ids,
            "aliasStrategyIds": aliases,
            "memberCount": len(member_ids),
            "bestValidWindowCount": cluster.get("bestValidWindowCount"),
            "bestPnlUsd": cluster.get("bestPnlUsd"),
            "bestSharpe": cluster.get("bestSharpe"),
            "recommendedResearchPriority": cluster.get("recommendedResearchPriority"),
            "recommendedResearchReasonZh": cluster.get("recommendedResearchReasonZh"),
            "sourceArtifacts": cluster.get("sourceArtifacts"),
            "topBlockers": _list(cluster.get("blockerUnion"))[:3],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })

    return {
        "status": "BTC_PARAMETER_CLUSTERS_READY",
        "rowCount": len(rows),
        "rows": rows,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _enrich_btc_items_with_cluster_aliases(
    btc_items: list[dict[str, Any]],
    btc_parameter_clusters: dict[str, Any],
) -> list[dict[str, Any]]:
    alias_map = {
        str(_dict(row).get("canonicalStrategyId") or ""): [
            alias
            for alias in _list(_dict(row).get("aliasStrategyIds"))
            if isinstance(alias, str) and alias
        ]
        for row in _list(btc_parameter_clusters.get("rows"))
        if str(_dict(row).get("canonicalStrategyId") or "")
    }

    enriched: list[dict[str, Any]] = []
    for item in btc_items:
        row = dict(item)
        selection_basis = dict(_dict(row.get("selectionBasis")))
        strategy_id = str(row.get("strategyId") or "")
        aliases = alias_map.get(strategy_id, [])
        merged_aliases: list[str] = []
        for alias in _alias_strategy_ids(selection_basis) + aliases:
            if isinstance(alias, str) and alias and alias != strategy_id and alias not in merged_aliases:
                merged_aliases.append(alias)
        merged_aliases = _alias_strategy_ids({"sameParameterSetAs": merged_aliases})
        if merged_aliases:
            selection_basis["sameParameterSetAs"] = merged_aliases
        elif "sameParameterSetAs" in selection_basis:
            selection_basis["sameParameterSetAs"] = [
                alias
                for alias in _list(selection_basis.get("sameParameterSetAs"))
                if isinstance(alias, str) and alias and alias != strategy_id
            ]
        row["selectionBasis"] = selection_basis
        enriched.append(row)
    return enriched


def _btc_source_params(row: dict[str, Any]) -> dict[str, Any]:
    nested = _dict(row.get("parameters")) or _dict(row.get("params")) or _dict(row.get("tpSlSummary"))
    return {
        "bias": nested.get("bias") or row.get("bias"),
        "takeProfitPriceMove": nested.get("takeProfitPriceMove") or row.get("takeProfitPriceMove"),
        "stopLossPriceMove": nested.get("stopLossPriceMove") or row.get("stopLossPriceMove"),
        "maxHoldBars": nested.get("maxHoldBars") or row.get("maxHoldBars"),
        "cooldownBars": nested.get("cooldownBars") or row.get("cooldownBars"),
    }


def _btc_distinct_scan_top_candidates(scan: dict[str, Any]) -> list[dict[str, Any]]:
    distinct: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _list(scan.get("topCandidates")):
        row = _dict(raw)
        identity = _btc_identity_key_from_params(row.get("strategyId"), _btc_source_params(row))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        distinct.append(row)
    return distinct


def _btc_aliases_for_identity(identity_key: str, scan: dict[str, Any], *, exclude_strategy_id: Any = None) -> list[str]:
    current_cluster_aliases = _current_near_live_cluster_aliases(
        _dict(scan.get("nextFocusedSearchPlan")),
        exclude_strategy_id,
    )
    if current_cluster_aliases:
        return current_cluster_aliases
    aliases: list[str] = []
    exclude = str(exclude_strategy_id or "")
    for raw in _list(scan.get("topCandidates")):
        row = _dict(raw)
        strategy_id = str(row.get("strategyId") or "")
        if not strategy_id or strategy_id == exclude:
            continue
        if _btc_identity_key_from_params(strategy_id, _btc_source_params(row)) != identity_key:
            continue
        if strategy_id not in aliases:
            aliases.append(strategy_id)
    return aliases


def _consensus_level(agreement_count: int, *, tie_break_required: bool = False) -> str:
    if tie_break_required:
        return "MODERATE"
    if agreement_count >= 3:
        return "HIGH"
    if agreement_count >= 2:
        return "MODERATE"
    return "LOW"


def _btc_item_by_role(btc_items: list[dict[str, Any]], role: str) -> dict[str, Any]:
    return next(
        (_dict(row) for row in btc_items if _dict(row).get("role") == role),
        {},
    )


def _btc_supporting_sources(identity_key: str, btc: dict[str, Any], scan: dict[str, Any]) -> list[str]:
    if not identity_key:
        return []

    sources: list[str] = []

    def add_source_if_match(source_artifact: str, row: dict[str, Any]) -> None:
        if not row:
            return
        if _btc_identity_key_from_params(row.get("strategyId"), _btc_source_params(row)) == identity_key:
            if source_artifact not in sources:
                sources.append(source_artifact)

    for name in ("recommendedStable", "recommendedTargetSeeking", "finalAdvisoryPick"):
        add_source_if_match(f"tpSlOptimizer.{name}", _dict(btc.get(name)))

    if any(
        _btc_identity_key_from_params(_dict(row).get("strategyId"), _btc_source_params(_dict(row))) == identity_key
        for row in _list(scan.get("topCandidates"))
    ):
        sources.append("btcStrategyScan.topCandidates")

    focused_plan = _dict(scan.get("nextFocusedSearchPlan"))
    for name in ("highYieldTradeoff", "nearLiveStabilityTradeoff", "qualityRepairTradeoff", "sampleRichQualityTradeoff"):
        add_source_if_match(f"btcStrategyScan.nextFocusedSearchPlan.{name}", _dict(focused_plan.get(name)))

    return sources


def _selection_consensus(
    ace: dict[str, Any],
    retest: dict[str, Any],
    btc: dict[str, Any],
    scan: dict[str, Any],
    mt5_items: list[dict[str, Any]],
    btc_items: list[dict[str, Any]],
) -> dict[str, Any]:
    mt5_primary = _dict(mt5_items[0]) if mt5_items else {}
    mt5_seed_id = str(mt5_primary.get("seedId") or "")
    scout_top = _dict(ace.get("topQualifiedForex"))
    retest_top = _dict(retest.get("forexChampion"))
    contender_review = _dict(ace.get("forexContenderReview")) or _dict(retest.get("forexContenderReview"))
    contender_seed_ids = [
        str(_dict(row).get("seedId") or "")
        for row in _list(contender_review.get("contenders"))
        if str(_dict(row).get("seedId") or "")
    ]
    mt5_sources: list[str] = []
    if mt5_seed_id and str(scout_top.get("seedId") or "") == mt5_seed_id:
        mt5_sources.append("aceStrategyScout.topQualifiedForex")
    if mt5_seed_id and str(retest_top.get("seedId") or "") == mt5_seed_id:
        mt5_sources.append("championRetest.forexChampion")

    btc_stable = _btc_item_by_role(btc_items, "stableAnchor")
    btc_strongest = _btc_item_by_role(btc_items, "highYieldTradeoff")
    focused_plan = _dict(scan.get("nextFocusedSearchPlan"))
    scan_stable = (
        _dict(focused_plan.get("mostStableTradeoff"))
        or _dict(scan.get("mostStableTradeoff"))
        or _dict(scan.get("topRecommendation"))
    )
    scan_strongest = (
        _dict(focused_plan.get("highYieldTradeoff"))
        or _dict(scan.get("currentHighestYieldTradeoff"))
        or scan_stable
    )
    stable_source = scan_stable if scan_stable.get("strategyId") else btc_stable
    strongest_source = scan_strongest if scan_strongest.get("strategyId") else (btc_strongest or stable_source)
    btc_stable_strategy_id = stable_source.get("strategyId") or btc_stable.get("strategyId")
    btc_strongest_strategy_id = (
        strongest_source.get("strategyId")
        or btc_strongest.get("strategyId")
        or btc_stable_strategy_id
    )
    btc_stable_identity = _btc_identity_key_from_params(
        btc_stable_strategy_id,
        _btc_source_params(stable_source) or _dict(btc_stable.get("params")),
    )
    btc_strongest_identity = _btc_identity_key_from_params(
        btc_strongest_strategy_id,
        _btc_source_params(strongest_source) or _dict(btc_strongest.get("params")) or _btc_source_params(stable_source),
    )
    btc_stable_sources = _btc_supporting_sources(btc_stable_identity, btc, scan)
    btc_strongest_sources = _btc_supporting_sources(btc_strongest_identity, btc, scan)
    btc_stable_aliases = (
        _btc_aliases_for_identity(btc_stable_identity, scan, exclude_strategy_id=btc_stable_strategy_id)
        if btc_stable_strategy_id and btc_stable_strategy_id != btc_stable.get("strategyId")
        else _alias_strategy_ids_without_self(
            _dict(btc_stable.get("selectionBasis")),
            btc_stable.get("strategyId"),
        )
    )
    btc_strongest_selection_basis = _dict(btc_strongest.get("selectionBasis"))
    btc_strongest_aliases = (
        _btc_aliases_for_identity(btc_strongest_identity, scan, exclude_strategy_id=btc_strongest_strategy_id)
        if btc_strongest_strategy_id and btc_strongest_strategy_id != btc_strongest.get("strategyId")
        else _alias_strategy_ids_without_self(
            btc_strongest_selection_basis,
            btc_strongest.get("strategyId"),
        )
    )
    optimizer_alias_source = btc_strongest_selection_basis.get("optimizerAliasSourceArtifact")
    optimizer_alias_strategy_id = btc_strongest_selection_basis.get("optimizerAliasStrategyId")
    if (
        isinstance(optimizer_alias_source, str)
        and optimizer_alias_source
        and isinstance(optimizer_alias_strategy_id, str)
        and optimizer_alias_strategy_id
        and optimizer_alias_strategy_id in btc_strongest_aliases
        and optimizer_alias_source not in btc_strongest_sources
    ):
        btc_strongest_sources.insert(0, optimizer_alias_source)
    optimizer_baseline_strategy_id = (
        btc_strongest_selection_basis.get("optimizerBaselineStrategyId")
        or _dict(btc.get("recommendedTargetSeeking")).get("strategyId")
    )
    stable_and_yield_converged = bool(
        btc_stable_strategy_id
        and btc_strongest_strategy_id
        and btc_stable_strategy_id == btc_strongest_strategy_id
    )
    frontier_drift_detected = bool(
        btc_strongest_identity
        and _btc_identity_key_from_params(
            optimizer_baseline_strategy_id,
            _btc_source_params(_dict(btc.get("recommendedTargetSeeking"))),
        )
        and btc_strongest_identity != _btc_identity_key_from_params(
            optimizer_baseline_strategy_id,
            _btc_source_params(_dict(btc.get("recommendedTargetSeeking"))),
        )
    )

    tie_break_required = bool(mt5_primary.get("contenderTieBreakRequired"))
    mt5_summary = (
        "MT5 strongest/stable 结论同时得到 scout 与 champion retest 支持，但 G0093/G0102 仍需 tester-forward A/B 决胜。"
        if tie_break_required
        else "MT5 strongest/stable 结论同时得到 scout 与 champion retest 支持。"
    )
    if frontier_drift_detected:
        btc_summary = (
            "BTC 当前稳健锚点与收益前沿已收敛到同一参数簇；"
            "相对旧 optimizer target 仍存在 frontier 漂移，需要把旧 baseline 与当前 scan 锚点分开跟踪。"
            if stable_and_yield_converged
            else "BTC 稳健簇已得到 TP/SL default/stable 与 scan 同参候选共同支持；高收益前沿已漂移到新的 scan challenger，仍需与旧 optimizer target 分开跟踪。"
        )
    else:
        btc_summary = (
            "BTC 当前稳健锚点与收益前沿已收敛到同一参数簇，scan/consensus 结论一致。"
            if stable_and_yield_converged
            else "BTC 稳健簇已得到 TP/SL default/stable 与 scan 同参候选共同支持；高收益簇也得到 optimizer 与 scan 双源支持。"
        )

    return {
        "status": "SELECTION_CONSENSUS_READY",
        "mt5": {
            "strongestNowSeedId": mt5_primary.get("seedId"),
            "strongestNowStrategyId": mt5_primary.get("strategyId"),
            "mostStableNowSeedId": mt5_primary.get("seedId"),
            "mostStableNowStrategyId": mt5_primary.get("strategyId"),
            "supportingSources": mt5_sources,
            "agreementCount": len(mt5_sources),
            "contenderSeedIds": contender_seed_ids[:2],
            "tieBreakStillRequired": tie_break_required,
            "consensusLevel": _consensus_level(len(mt5_sources), tie_break_required=tie_break_required),
            "summaryZh": mt5_summary,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "btc": {
            "mostStableNowStrategyId": btc_stable_strategy_id,
            "mostStableSameParameterSetAs": btc_stable_aliases,
            "mostStableSupportingSources": btc_stable_sources,
            "mostStableAgreementCount": len(btc_stable_sources),
            "mostStableConsensusLevel": _consensus_level(len(btc_stable_sources)),
            "strongestYieldNowStrategyId": btc_strongest_strategy_id,
            "strongestYieldSameParameterSetAs": btc_strongest_aliases,
            "strongestYieldSupportingSources": btc_strongest_sources,
            "strongestYieldAgreementCount": len(btc_strongest_sources),
            "strongestYieldConsensusLevel": _consensus_level(len(btc_strongest_sources)),
            "strongestYieldOptimizerBaselineStrategyId": optimizer_baseline_strategy_id,
            "strongestYieldConvergedWithStable": stable_and_yield_converged,
            "strongestYieldFrontierDriftDetected": frontier_drift_detected,
            "summaryZh": btc_summary,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _selection_refresh_audit(
    ace: dict[str, Any],
    retest: dict[str, Any],
    btc: dict[str, Any],
    scan: dict[str, Any],
    selection_consensus: dict[str, Any],
    btc_items: list[dict[str, Any]],
) -> dict[str, Any]:
    mt5_consensus = _dict(selection_consensus.get("mt5"))
    btc_consensus = _dict(selection_consensus.get("btc"))
    scout_top = _dict(ace.get("topQualifiedForex"))
    retest_top = _dict(retest.get("forexChampion"))
    scan_top = _dict(_list(scan.get("topCandidates"))[0]) if _list(scan.get("topCandidates")) else {}
    optimizer_stable = _dict(btc.get("recommendedStable"))
    optimizer_target = _dict(btc.get("recommendedTargetSeeking"))
    final_pick = _dict(btc.get("finalAdvisoryPick"))
    current_default = _btc_item_by_role(btc_items, "stableAnchor")
    focused_plan = _dict(scan.get("nextFocusedSearchPlan"))
    scan_stable = (
        _dict(focused_plan.get("mostStableTradeoff"))
        or _dict(scan.get("mostStableTradeoff"))
        or _dict(scan.get("topRecommendation"))
    )
    scan_high_yield = _dict(focused_plan.get("highYieldTradeoff"))
    btc_strongest = _btc_item_by_role(btc_items, "highYieldTradeoff")

    scan_top_identity = _btc_identity_key_from_params(scan_top.get("strategyId"), _btc_source_params(scan_top))
    stable_consensus_identity = _btc_identity_key_from_params(
        btc_consensus.get("mostStableNowStrategyId"),
        _btc_source_params(scan_stable or final_pick or optimizer_stable),
    )
    target_consensus_identity = _btc_identity_key_from_params(
        btc_consensus.get("strongestYieldNowStrategyId"),
        _btc_source_params(scan_high_yield or btc_strongest or scan_stable),
    )
    optimizer_target_identity = _btc_identity_key_from_params(
        optimizer_target.get("strategyId"),
        _btc_source_params(optimizer_target),
    )
    scan_high_yield_identity = _btc_identity_key_from_params(
        scan_high_yield.get("strategyId"),
        _btc_source_params(scan_high_yield),
    )

    mt5_alignment_ok = bool(
        mt5_consensus.get("strongestNowSeedId")
        and mt5_consensus.get("strongestNowSeedId") == scout_top.get("seedId") == retest_top.get("seedId")
    )
    btc_stable_alignment_ok = bool(
        stable_consensus_identity
        and stable_consensus_identity == scan_top_identity
    )
    btc_high_yield_alignment_ok = bool(
        target_consensus_identity
        and target_consensus_identity == scan_high_yield_identity
    )
    btc_stable_yield_converged = bool(
        stable_consensus_identity
        and target_consensus_identity
        and stable_consensus_identity == target_consensus_identity
    )
    btc_high_yield_frontier_drift_detected = bool(
        target_consensus_identity
        and optimizer_target_identity
        and target_consensus_identity != optimizer_target_identity
    )
    btc_high_yield_scan_aligned = bool(
        target_consensus_identity
        and target_consensus_identity == scan_high_yield_identity
    )

    return {
        "status": "SELECTION_REFRESH_AUDIT_READY",
        "mt5StrongestAlignmentOk": mt5_alignment_ok,
        "mt5StrongestSeedId": mt5_consensus.get("strongestNowSeedId"),
        "scoutTopSeedId": scout_top.get("seedId"),
        "retestTopSeedId": retest_top.get("seedId"),
        "btcStableAlignmentOk": btc_stable_alignment_ok,
        "btcStableStrategyId": btc_consensus.get("mostStableNowStrategyId"),
        "scanTopStrategyId": scan_top.get("strategyId"),
        "optimizerStableStrategyId": optimizer_stable.get("strategyId"),
        "optimizerFinalAdvisoryPickStrategyId": final_pick.get("strategyId"),
        "currentDefaultStrategyId": current_default.get("strategyId") or final_pick.get("strategyId"),
        "finalAdvisoryPickStrategyId": current_default.get("strategyId") or final_pick.get("strategyId"),
        "btcHighYieldAlignmentOk": btc_high_yield_alignment_ok,
        "btcStableYieldConverged": btc_stable_yield_converged,
        "btcHighYieldFrontierDriftDetected": btc_high_yield_frontier_drift_detected,
        "btcHighYieldScanAligned": btc_high_yield_scan_aligned,
        "btcHighYieldStrategyId": btc_consensus.get("strongestYieldNowStrategyId"),
        "optimizerTargetStrategyId": optimizer_target.get("strategyId"),
        "scanHighYieldTradeoffStrategyId": scan_high_yield.get("strategyId"),
        "summaryZh": (
            f"MT5对齐={mt5_alignment_ok}；"
            f"BTC稳健对齐={btc_stable_alignment_ok}；"
            f"BTC稳健/高收益收敛={btc_stable_yield_converged}；"
            f"BTC高收益簇对齐={btc_high_yield_alignment_ok}；"
            f"高收益frontier漂移={btc_high_yield_frontier_drift_detected}。"
        ),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _btc_focused_retest_queue(
    *,
    btc: dict[str, Any],
    strategy_shortlist: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_queue = [_dict(row) for row in _list(btc.get("focusedRetestQueue"))]
    raw_by_strategy_id = {
        row.get("strategyId"): row
        for row in raw_queue
        if isinstance(row.get("strategyId"), str)
    }
    raw_window_health = _dict(_dict(btc.get("windowHealth")).get("selectedDefault"))
    top_items = _btc_research_priority_items([_dict(row) for row in _list(strategy_shortlist.get("btcTopStrategies"))])
    queue: list[dict[str, Any]] = []
    role_map = {
        "stableAnchor": "selectedDefault",
        "highYieldTradeoff": "yieldFrontierChallenger",
        "stabilityAlternative": "stabilityAlternative",
        "sampleRichBridge": "sampleRichBridge",
    }
    next_action_map = {
        "stableAnchor": "作为默认稳健候选继续补 middle_third 复验。",
        "highYieldTradeoff": "作为当前高收益 frontier challenger 与稳健默认做 focused retest，不直接替代默认。",
        "stabilityAlternative": "作为稳定替补观察更高样本密度下的分段质量。",
        "sampleRichBridge": "作为样本桥接候选补齐 tradeCount 与窗口质量证据。",
    }

    for priority, item in enumerate(top_items[:3], start=1):
        strategy_id = item.get("strategyId")
        if not isinstance(strategy_id, str) or not strategy_id:
            continue
        selection_basis = _dict(item.get("selectionBasis"))
        raw = dict(raw_by_strategy_id.get(strategy_id, {}))
        params = _dict(item.get("params"))
        metrics = _dict(item.get("metrics"))
        next_action_zh = next_action_map.get(item.get("role")) or item.get("nextActionZh")
        if (
            item.get("role") == "stabilityAlternative"
            and selection_basis.get("nearLiveChallengerConvergedWithYieldFrontier")
        ):
            next_action_zh = (
                "当前稳健锚点与收益 frontier 已收敛到同一参数簇；"
                "把 next distinct near-live contender 作为第二顺位稳定替补继续复验。"
            )
        queue_item = {
            "priority": priority,
            "role": role_map.get(item.get("role"), item.get("role")),
            "strategyId": strategy_id,
            "strategyName": item.get("strategyName"),
            "strategyFamily": item.get("strategyFamily"),
            "status": item.get("status"),
            "metrics": metrics,
            "params": params,
            "tpSlSummary": _dict(raw.get("tpSlSummary")) or params,
            "validWindowCount": metrics.get("validWindowCount"),
            "windowCount": metrics.get("windowCount"),
            "blockers": _list(item.get("blockers")),
            "testerOnly": True,
            "livePresetMutation": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "nextActionZh": next_action_zh,
            "sameParameterSetAs": _alias_strategy_ids_without_self(selection_basis, strategy_id),
            "sourceArtifact": selection_basis.get("sourceArtifact"),
            "selectionBasis": selection_basis,
        }
        summary_type = item.get("summaryType")
        if isinstance(summary_type, str) and summary_type:
            queue_item["summaryType"] = summary_type
        if item.get("role") == "stableAnchor":
            queue_item["windowHealth"] = _dict(raw.get("windowHealth")) or raw_window_health
        if item.get("role") == "highYieldTradeoff":
            queue_item["optimizerBaselineStrategyId"] = selection_basis.get("optimizerBaselineStrategyId")
            queue_item["frontierChallengeZh"] = selection_basis.get("frontierChallengeZh")
        queue.append(queue_item)
    btc_lineup_board = _dict(strategy_shortlist.get("btcLineupBoard"))
    repair_candidate = _btc_scan_plan_repair_candidate(btc_lineup_board)
    repair_tradeoff = _dict(repair_candidate.get("tradeoff"))
    repair_strategy_id = repair_candidate.get("strategyId")
    repair_tradeoff_outcome_zh = (
        repair_candidate.get("outcomeZh")
        if isinstance(repair_candidate.get("outcomeZh"), str)
        else None
    )
    repair_tradeoff_summary_type = (
        repair_candidate.get("summaryType")
        if isinstance(repair_candidate.get("summaryType"), str)
        else "stableMiddleTradeoffFollowup"
    )
    repair_tradeoff_strategy_family = (
        repair_candidate.get("strategyFamily")
        if isinstance(repair_candidate.get("strategyFamily"), str)
        else "stable_middle_tradeoff_followup"
    )
    repair_tradeoff_source_artifact = (
        repair_candidate.get("sourceArtifact")
        if isinstance(repair_candidate.get("sourceArtifact"), str)
        else "btcStrategyScan.nextFocusedSearchPlan.stableMiddleTradeoffFollowupBestTradeoff"
    )
    repair_tradeoff_selection_basis = _dict(repair_candidate.get("improvementFlags"))
    repair_tradeoff_default_reason_zh = (
        repair_tradeoff_outcome_zh
        or (
            f"{repair_candidate.get('labelZh')} 作为当前第三条观察候选继续复验。"
            if isinstance(repair_candidate.get("labelZh"), str) and repair_candidate.get("labelZh")
            else "当前 repair 观察候选继续保留在 focused retest。"
        )
    )
    if isinstance(repair_strategy_id, str) and repair_strategy_id and all(
        _dict(row).get("strategyId") != repair_strategy_id for row in queue
    ):
        queue.append({
            "priority": len(queue) + 1,
            "role": "repairObservation",
            "summaryType": repair_tradeoff_summary_type,
            "strategyId": repair_strategy_id,
            "strategyName": repair_strategy_id,
            "strategyFamily": repair_tradeoff_strategy_family,
            "status": "BTC_REPAIR_OBSERVATION_READY",
            "metrics": {
                "pnlUsd": repair_tradeoff.get("pnlUsd"),
                "sharpe": repair_tradeoff.get("sharpe"),
                "maxDrawdownPct": repair_tradeoff.get("maxDrawdownPct"),
                "tradeCount": repair_tradeoff.get("tradeCount"),
                "validWindowCount": repair_tradeoff.get("validWindowCount"),
                "windowCount": repair_tradeoff.get("windowCount"),
            },
            "params": {
                "bias": repair_tradeoff.get("bias"),
                "takeProfitPriceMove": repair_tradeoff.get("takeProfitPriceMove"),
                "stopLossPriceMove": repair_tradeoff.get("stopLossPriceMove"),
                "maxHoldBars": repair_tradeoff.get("maxHoldBars"),
                "cooldownBars": repair_tradeoff.get("cooldownBars"),
            },
            "tpSlSummary": {
                "bias": repair_tradeoff.get("bias"),
                "takeProfitPriceMove": repair_tradeoff.get("takeProfitPriceMove"),
                "stopLossPriceMove": repair_tradeoff.get("stopLossPriceMove"),
                "maxHoldBars": repair_tradeoff.get("maxHoldBars"),
                "cooldownBars": repair_tradeoff.get("cooldownBars"),
            },
            "validWindowCount": repair_tradeoff.get("validWindowCount"),
            "windowCount": repair_tradeoff.get("windowCount"),
            "blockers": ["HFM_MIDDLE_THIRD_NOT_FULLY_REPAIRED"],
            "testerOnly": True,
            "livePresetMutation": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "nextActionZh": repair_tradeoff_default_reason_zh,
            "sameParameterSetAs": [],
            "sourceArtifact": repair_tradeoff_source_artifact,
            "selectionBasis": {
                "sourceArtifact": repair_tradeoff_source_artifact,
                "reasonZh": repair_tradeoff_default_reason_zh,
                "comparisonFocus": [
                    "validWindowCount",
                    "tradeCount",
                    "sharpe",
                    "pnlUsd",
                    "middleThirdWeakness",
                ],
                **repair_tradeoff_selection_basis,
                f"{repair_tradeoff_summary_type}OutcomeZh": repair_tradeoff_outcome_zh,
            },
        })
    recommended_order = [
        str(item)
        for item in _list(btc_lineup_board.get("recommendedFocusedRetestOrder"))
        if isinstance(item, str) and item
    ]
    if recommended_order and queue:
        queue_by_strategy_id = {
            str(_dict(row).get("strategyId") or ""): row
            for row in queue
            if isinstance(_dict(row).get("strategyId"), str) and _dict(row).get("strategyId")
        }
        reordered: list[dict[str, Any]] = []
        for strategy_id in recommended_order:
            row = queue_by_strategy_id.pop(strategy_id, None)
            if row:
                reordered.append(row)
        reordered.extend(queue_by_strategy_id.values())
        queue = reordered
    for priority, row in enumerate(queue, start=1):
        row["priority"] = priority
    if queue:
        return queue
    return raw_queue


def _strategy_shortlist(
    ace: dict[str, Any],
    retest: dict[str, Any],
    forex_pack: dict[str, Any],
    final_pick: dict[str, Any],
    btc: dict[str, Any],
    scan: dict[str, Any],
    run_gate: dict[str, Any],
    preflight: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    forex_items = _forex_shortlist(forex_pack)
    btc_items = _btc_shortlist(final_pick, btc, scan)
    btc_parameter_clusters = _btc_parameter_clusters(btc_items, btc, scan)
    btc_items = _enrich_btc_items_with_cluster_aliases(btc_items, btc_parameter_clusters)
    selection_consensus = _selection_consensus(ace, retest, btc, scan, forex_items, btc_items)
    selection_refresh_audit = _selection_refresh_audit(ace, retest, btc, scan, selection_consensus, btc_items)
    finalist_comparison = {
        "mt5": _finalist_comparison(forex_items, lane="forexMt5"),
        "btc": _finalist_comparison(btc_items, lane="btcCryptoCfd"),
    }
    mt5_tester_snapshot = _mt5_tester_snapshot(run_gate)
    mt5_gate_diagnostics = _mt5_gate_diagnostics(run_gate)
    btc_runtime_snapshot = _btc_runtime_snapshot(preflight)
    btc_blockers = _blocker_codes(preflight.get("blockers"))
    btc_gate_diagnostics = _btc_gate_diagnostics(btc_runtime_snapshot, btc_blockers)
    btc_next_action_zh, _btc_why_now_zh, btc_current_mode_zh = _btc_runtime_focus(
        btc_runtime_snapshot,
        btc_blockers,
    )
    mt5_lane_readiness = {
        "status": run_gate.get("status") or "CHAMPION_TESTER_RUN_GATE_MISSING",
        "canRunTester": bool(_dict(run_gate.get("decision")).get("canRunIsolatedTester")),
        "blockers": _blocker_codes(run_gate.get("blockers") or _dict(run_gate.get("gate")).get("blockers")),
        "nextTesterWindow": _resolved_next_tester_window(_dict(run_gate.get("nextTesterWindow"))),
        "nextActionZh": (
            _mt5_terminal_restore_required_action_zh(run_gate)
            if "mt5_terminal_process_missing" in _blocker_codes(_dict(run_gate.get("supportingProcessEvidence")).get("blockers"))
            else _dict(run_gate.get("decision")).get("nextRequiredActionZh")
        ),
        "sensitiveAccountContextSyncRequired": bool(_dict(run_gate.get("testerAccountContext")).get("sensitiveAccountContextSyncRequired")),
        "liveSessionFresh": bool(_dict(_dict(run_gate.get("gate")).get("liveSession")).get("ok")),
        "supportingProcessBlockers": _blocker_codes(_dict(run_gate.get("supportingProcessEvidence")).get("blockers")),
        "processEvidence": _dict(run_gate.get("supportingProcessEvidence")),
        "preferredTerminalPath": _mt5_preferred_terminal_path(run_gate),
        "testerSnapshot": mt5_tester_snapshot,
        "queueCount": mt5_tester_snapshot.get("queueCount"),
        "abCandidateIds": _list(mt5_tester_snapshot.get("abCandidateIds")),
        "variantCandidateIds": _list(mt5_tester_snapshot.get("variantCandidateIds")),
        "gateDiagnostics": mt5_gate_diagnostics,
        "testerSummaryZh": _mt5_tester_summary_zh(mt5_tester_snapshot),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }
    mt5_lane_readiness["readinessChecklist"] = _mt5_readiness_checklist(mt5_lane_readiness, run_gate)
    mt5_lane_readiness["clearancePriorityRows"] = _readiness_priority_rows(_dict(mt5_lane_readiness.get("readinessChecklist")))
    mt5_lane_readiness["windowBriefing"] = _mt5_window_briefing(mt5_lane_readiness)
    btc_lane_readiness = {
        "status": preflight.get("status") or "LIVE_RUNTIME_PREFLIGHT_MISSING",
        "runtimeProbePassed": bool(preflight.get("runtimeProbePassed")),
        "dataPlaneReadyForLivePilotReview": bool(preflight.get("dataPlaneReadyForLivePilotReview")),
        "approvedLanes": _list(preflight.get("approvedLanes")),
        "blockers": btc_blockers,
        "focusSymbol": (_dict(_list(preflight.get("laneRuntimeChecks"))[0]).get("brokerSymbol") if _list(preflight.get("laneRuntimeChecks")) else None),
        "nextActionZh": btc_next_action_zh,
        "currentModeZh": btc_current_mode_zh,
        "gateDiagnostics": btc_gate_diagnostics,
        "runtimeSnapshot": btc_runtime_snapshot,
        "runtimeSummaryZh": _btc_runtime_summary_zh(btc_runtime_snapshot),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }
    btc_lane_readiness["readinessChecklist"] = _btc_readiness_checklist(btc_runtime_snapshot)
    btc_lane_readiness["clearancePriorityRows"] = _readiness_priority_rows(_dict(btc_lane_readiness.get("readinessChecklist")))
    lane_verdicts = _lane_verdicts(forex_items, btc_items, selection_consensus)
    mt5_ab_board = _mt5_ab_board(forex_items)
    btc_lineup_board = _btc_lineup_board(btc_items, selection_consensus, scan=scan)
    return {
        "status": "STRATEGY_SHORTLIST_READY",
        "statusZh": "MT5/BTC 强弱候选清单已生成；仅供 tester/shadow 复验。",
        "mt5TopStrategies": forex_items,
        "btcTopStrategies": btc_items,
        "btcParameterClusters": btc_parameter_clusters,
        "selectionConsensus": selection_consensus,
        "selectionRefreshAudit": selection_refresh_audit,
        "finalistComparison": finalist_comparison,
        "laneVerdicts": lane_verdicts,
        "mt5AbBoard": mt5_ab_board,
        "btcLineupBoard": btc_lineup_board,
        "btcDuelBoard": dict(btc_lineup_board),
        "goLiveGap": _go_live_gap(
            lane_verdicts=lane_verdicts,
            mt5_lane_readiness=mt5_lane_readiness,
            btc_lane_readiness=btc_lane_readiness,
            live_activation_blockers=blockers,
        ),
        "counts": {
            "mt5TopStrategies": len(forex_items),
            "btcTopStrategies": len(btc_items),
        },
        "mt5LaneReadiness": mt5_lane_readiness,
        "btcLaneReadiness": btc_lane_readiness,
        "liveActivationReady": False,
        "liveActivationBlockers": list(blockers),
        "nextActionZh": (
            "MT5 先对 G0093/G0102 做隔离 tester/forward A/B；"
            f"{_btc_focus_retest_order_zh(btc_lineup_board)}"
        ),
        "safety": {
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "writesLivePreset": False,
            "livePresetMutationAllowed": False,
        },
    }


def _finalist_comparison(items: list[dict[str, Any]], *, lane: str) -> dict[str, Any]:
    def compare_row(rank: int, item: dict[str, Any]) -> dict[str, Any]:
        metrics = _dict(item.get("metrics"))
        blockers = _list(item.get("blockers"))
        selection_basis = _dict(item.get("selectionBasis"))
        alias_strategy_ids = _alias_strategy_ids(selection_basis)
        if lane == "forexMt5":
            strongest_metric = (
                f"walkForwardStability={metrics.get('walkForwardStability')}"
                if "walkForwardStability" in metrics
                else f"coarseScreenScore={metrics.get('coarseScreenScore')}"
            )
            weakness = (
                ",".join(blockers[:2])
                if blockers
                else ("需要 A/B 决胜" if item.get("contenderTieBreakRequired") else "等待 tester-forward 复验")
            )
            headline = {
                "primaryChampion": "主冠军",
                "parallelContender2": "并列 contender",
            }.get(str(item.get("role") or ""), "tester-only 变体")
            summary_metrics = {
                "profitFactor": metrics.get("profitFactor"),
                "sharpe": metrics.get("sharpe"),
                "walkForwardStability": metrics.get("walkForwardStability"),
                "forwardNetR": metrics.get("forwardNetR"),
                "coarseScreenScore": metrics.get("coarseScreenScore"),
            }
        else:
            valid_window_count = metrics.get("validWindowCount")
            if valid_window_count is None:
                valid_window_count = item.get("validWindowCount")
            strongest_metric = (
                f"validWindowCount={valid_window_count}"
                if valid_window_count is not None
                else f"tradeCount={metrics.get('tradeCount')}"
            )
            weakness = ",".join(blockers[:2]) if blockers else "仍需 focused retest"
            headline = {
                "stableAnchor": "稳健默认",
                "highYieldTradeoff": "高收益候选",
                "stabilityAlternative": "稳定替补",
            }.get(str(item.get("role") or ""), "桥接候选")
            summary_metrics = {
                "pnlUsd": metrics.get("pnlUsd"),
                "sharpe": metrics.get("sharpe"),
                "tradeCount": metrics.get("tradeCount"),
                "validWindowCount": valid_window_count,
                "maxDrawdownPct": metrics.get("maxDrawdownPct"),
            }
        return {
            "rank": rank,
            "role": item.get("role"),
            "strategyId": item.get("strategyId"),
            "seedId": item.get("seedId"),
            "headlineZh": headline,
            "strongestMetricZh": strongest_metric,
            "weaknessZh": weakness,
            "summaryMetrics": summary_metrics,
            "selectionBasis": selection_basis,
            "sameParameterSetAs": alias_strategy_ids,
            "aliasSummaryZh": (
                f"同参异名候选: {', '.join(alias_strategy_ids)}"
                if alias_strategy_ids
                else None
            ),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        }

    rows = [compare_row(rank, _dict(item)) for rank, item in enumerate(items, start=1)]
    return {
        "status": "FINALIST_COMPARISON_READY",
        "lane": lane,
        "rows": rows,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _lane_verdicts(
    mt5_items: list[dict[str, Any]],
    btc_items: list[dict[str, Any]],
    selection_consensus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mt5_primary = _dict(mt5_items[0]) if mt5_items else {}
    mt5_contender = _dict(mt5_items[1]) if len(mt5_items) > 1 else {}
    mt5_variant = _dict(mt5_items[2]) if len(mt5_items) > 2 else {}
    btc_stable = _btc_item_by_role(btc_items, "stableAnchor")
    btc_strongest = _btc_item_by_role(btc_items, "highYieldTradeoff")
    btc_alternative = _btc_item_by_role(btc_items, "stabilityAlternative") or _btc_item_by_role(btc_items, "repairObservation")
    consensus_btc = _dict(_dict(selection_consensus).get("btc"))
    btc_stable_strategy_id = consensus_btc.get("mostStableNowStrategyId") or btc_stable.get("strategyId")
    btc_strongest_strategy_id = consensus_btc.get("strongestYieldNowStrategyId") or btc_strongest.get("strategyId") or btc_stable_strategy_id
    btc_converged = bool(
        isinstance(btc_stable_strategy_id, str)
        and btc_stable_strategy_id
        and btc_stable_strategy_id == btc_strongest_strategy_id
    )
    btc_stable_aliases = _alias_strategy_ids(_dict(btc_stable.get("selectionBasis")))
    btc_strongest_aliases = _alias_strategy_ids(_dict(btc_strongest.get("selectionBasis")))
    if btc_converged:
        btc_strongest_reason_zh = (
            "当前最稳与最高收益已收敛到同一策略簇；继续把它作为 strongestNow 跟踪。"
            if not btc_strongest_aliases
            else "当前最稳与最高收益已收敛到同一策略簇；scan 中同参异名候选不应视为新冠军。"
        )
    else:
        btc_strongest_reason_zh = (
            "当前高收益候选以 pnlUsd/sharpe 占优，但窗口通过数仍不足。"
            if not btc_strongest_aliases
            else "当前高收益候选以 pnlUsd/sharpe 占优，但窗口通过数仍不足；同参簇仍需统一按一个策略族看待。"
        )
    return {
        "status": "LANE_VERDICTS_READY",
        "mt5": {
            "strongestNow": {
                "seedId": mt5_primary.get("seedId"),
                "strategyId": mt5_primary.get("strategyId"),
                "tieWithSeedIds": [mt5_contender.get("seedId")] if mt5_primary.get("contenderTieBreakRequired") and mt5_contender.get("seedId") else [],
                "reasonZh": "当前主冠军与并列 contender 仍需 A/B 决胜，但主冠军暂列 strongestNow。",
            },
            "mostStableNow": {
                "seedId": mt5_primary.get("seedId"),
                "strategyId": mt5_primary.get("strategyId"),
                "reasonZh": "walk-forward 稳定性和前向质量当前最完整，因此暂列 mostStableNow。",
            },
            "bestAlternative": {
                "seedId": mt5_variant.get("seedId"),
                "strategyId": mt5_variant.get("strategyId"),
                "reasonZh": "tester-only TP/SL 变体只作为并排前向复验替补。",
            },
            "requiresTieBreak": bool(mt5_primary.get("contenderTieBreakRequired")),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "btc": {
            "strongestNow": {
                "strategyId": btc_strongest_strategy_id,
                "sameParameterSetAs": btc_strongest_aliases,
                "reasonZh": btc_strongest_reason_zh,
            },
            "mostStableNow": {
                "strategyId": btc_stable_strategy_id,
                "sameParameterSetAs": btc_stable_aliases,
                "reasonZh": (
                    "当前稳健默认以 validWindowCount 和无负收益窗口占优。"
                    if not btc_stable_aliases
                    else "当前稳健默认以 validWindowCount 和无负收益窗口占优；scan 中同参异名候选不应视为新冠军。"
                ),
            },
            "bestAlternative": {
                "strategyId": btc_alternative.get("strategyId"),
                "reasonZh": (
                    "稳定替补候选用于观察更高样本密度下的分段质量。"
                    if btc_alternative.get("role") == "stabilityAlternative"
                    else "收敛场景下当前没有独立稳定替补，先用 repair observation 保留第三条 distinct 修复线。"
                ),
            },
            "requiresTieBreak": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _mt5_ab_board(mt5_items: list[dict[str, Any]]) -> dict[str, Any]:
    champion = _dict(mt5_items[0]) if mt5_items else {}
    contender = _dict(mt5_items[1]) if len(mt5_items) > 1 else {}
    variant = _dict(mt5_items[2]) if len(mt5_items) > 2 else {}
    champion_metrics = _dict(champion.get("metrics"))
    contender_metrics = _dict(contender.get("metrics"))
    return {
        "status": "MT5_AB_BOARD_READY",
        "championSeedId": champion.get("seedId"),
        "championStrategyId": champion.get("strategyId"),
        "contenderSeedId": contender.get("seedId"),
        "contenderStrategyId": contender.get("strategyId"),
        "testerVariantStrategyId": variant.get("strategyId"),
        "tieBreakRequired": bool(champion.get("contenderTieBreakRequired")),
        "sharedCoreMetrics": {
            "profitFactor": champion_metrics.get("profitFactor"),
            "sharpe": champion_metrics.get("sharpe"),
            "walkForwardStability": champion_metrics.get("walkForwardStability"),
            "forwardNetR": champion_metrics.get("forwardNetR"),
            "tradeCount": champion_metrics.get("tradeCount"),
        },
        "championLeadZh": (
            "主冠军暂时保留 seed 领先位，但核心 walk-forward / profitFactor / sharpe / forwardNetR 目前与 contender 基本持平。"
            if champion.get("contenderTieBreakRequired")
            else "主冠军当前在 walk-forward 与前向质量上领先。"
        ),
        "contenderAngleZh": (
            f"并列 contender 当前 seed={contender.get('seedId')}；需要用样本外 tester-forward A/B 决胜。"
            if contender.get("seedId")
            else "当前没有并列 contender。"
        ),
        "recommendationZh": (
            "默认继续把 G0093 视为暂时主冠军，但任何 release 判断都必须等 G0093/G0102 的隔离 tester-forward A/B 结果。"
            if champion.get("contenderTieBreakRequired")
            else "当前可继续沿主冠军推进 tester-forward。"
        ),
        "recommendedAbSeeds": [
            seed_id
            for seed_id in (champion.get("seedId"), contender.get("seedId"))
            if isinstance(seed_id, str) and seed_id
        ],
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _btc_prefer_stability_challenger(frontier: dict[str, Any], alternative: dict[str, Any]) -> bool:
    if not alternative.get("strategyId"):
        return False
    if not frontier.get("strategyId"):
        return True
    frontier_metrics = _dict(frontier.get("metrics"))
    alternative_metrics = _dict(alternative.get("metrics"))
    frontier_valid = _num(frontier_metrics.get("validWindowCount"), default=-1)
    alternative_valid = _num(alternative_metrics.get("validWindowCount"), default=-1)
    if alternative_valid != frontier_valid:
        return alternative_valid > frontier_valid
    frontier_trade_count = _num(frontier_metrics.get("tradeCount"), default=-1)
    alternative_trade_count = _num(alternative_metrics.get("tradeCount"), default=-1)
    if alternative_trade_count != frontier_trade_count:
        return alternative_trade_count > frontier_trade_count
    frontier_blocker_count = len(_list(frontier.get("blockers")))
    alternative_blocker_count = len(_list(alternative.get("blockers")))
    if alternative_blocker_count != frontier_blocker_count:
        return alternative_blocker_count < frontier_blocker_count
    frontier_sharpe = _num(frontier_metrics.get("sharpe"), default=-999)
    alternative_sharpe = _num(alternative_metrics.get("sharpe"), default=-999)
    return alternative_sharpe > frontier_sharpe


def _btc_research_priority_items(btc_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stable = next((_dict(row) for row in btc_items if _dict(row).get("role") == "stableAnchor"), {})
    frontier = next((_dict(row) for row in btc_items if _dict(row).get("role") == "highYieldTradeoff"), {})
    alternative = next((_dict(row) for row in btc_items if _dict(row).get("role") == "stabilityAlternative"), {})
    bridge = next((_dict(row) for row in btc_items if _dict(row).get("role") == "sampleRichBridge"), {})

    ordered: list[dict[str, Any]] = []
    if stable.get("strategyId"):
        ordered.append(stable)

    if _btc_prefer_stability_challenger(frontier, alternative):
        for item in (alternative, frontier, bridge):
            if item.get("strategyId") and item not in ordered:
                ordered.append(item)
    else:
        for item in (frontier, alternative, bridge):
            if item.get("strategyId") and item not in ordered:
                ordered.append(item)

    for item in btc_items:
        row = _dict(item)
        if row.get("strategyId") and row not in ordered:
            ordered.append(row)
    return ordered


def _btc_near_live_middle_window_variants(scan: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(_list(_dict(scan).get("topCandidates")), start=1):
        row = _dict(candidate)
        strategy_id = row.get("strategyId")
        if not isinstance(strategy_id, str) or not strategy_id.startswith("hfm_crypto_btc_near_live_middle_window_"):
            continue
        params = _dict(row.get("parameters"))
        metrics = _dict(row.get("fullWindowMetrics"))
        rows.append({
            "rank": rank,
            "strategyId": strategy_id,
            "stopLossPriceMove": params.get("stopLossPriceMove"),
            "takeProfitPriceMove": params.get("takeProfitPriceMove"),
            "cooldownBars": params.get("cooldownBars"),
            "maxHoldBars": params.get("maxHoldBars"),
            "validWindowCount": row.get("validWindowCount"),
            "windowCount": row.get("windowCount"),
            "pnlUsd": metrics.get("pnlUsd"),
            "sharpe": metrics.get("sharpe"),
            "tradeCount": metrics.get("tradeCount"),
        })
        if len(rows) >= limit:
            break
    return rows


def _btc_near_live_converged_variants(scan: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(_list(_dict(scan).get("topCandidates")), start=1):
        row = _dict(candidate)
        strategy_id = row.get("strategyId")
        if not isinstance(strategy_id, str) or not (
            strategy_id.startswith("hfm_crypto_btc_near_live_middle_window_")
            or strategy_id.startswith("hfm_crypto_btc_near_live_stoploss_ladder_")
            or strategy_id.startswith("hfm_crypto_btc_near_live_cluster_refinement_")
        ):
            continue
        params = _dict(row.get("parameters"))
        metrics = _dict(row.get("fullWindowMetrics"))
        rows.append({
            "rank": rank,
            "strategyId": strategy_id,
            "stopLossPriceMove": params.get("stopLossPriceMove"),
            "takeProfitPriceMove": params.get("takeProfitPriceMove"),
            "cooldownBars": params.get("cooldownBars"),
            "maxHoldBars": params.get("maxHoldBars"),
            "validWindowCount": row.get("validWindowCount"),
            "windowCount": row.get("windowCount"),
            "pnlUsd": metrics.get("pnlUsd"),
            "sharpe": metrics.get("sharpe"),
            "tradeCount": metrics.get("tradeCount"),
        })
        if len(rows) >= limit:
            break
    return rows


def _btc_near_live_middle_window_variant_summary(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    parts: list[str] = []
    for row in rows:
        strategy_id = row.get("strategyId")
        stop_loss = row.get("stopLossPriceMove")
        if isinstance(strategy_id, str) and strategy_id:
            if stop_loss is not None:
                parts.append(f"{strategy_id}(SL={stop_loss})")
            else:
                parts.append(strategy_id)
    if not parts:
        return None
    return f"当前 near-live middle-window 收敛簇前排变体: {' -> '.join(parts)}。"


def _btc_near_live_converged_variant_summary(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    parts: list[str] = []
    for row in rows:
        strategy_id = row.get("strategyId")
        stop_loss = row.get("stopLossPriceMove")
        if isinstance(strategy_id, str) and strategy_id:
            if stop_loss is not None:
                parts.append(f"{strategy_id}(SL={stop_loss})")
            else:
                parts.append(strategy_id)
    if not parts:
        return None
    return f"当前 near-live 收敛簇前排变体: {' -> '.join(parts)}。"


def _btc_lineup_board(
    btc_items: list[dict[str, Any]],
    selection_consensus: dict[str, Any],
    scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stable = _btc_item_by_role(btc_items, "stableAnchor")
    frontier = _btc_item_by_role(btc_items, "highYieldTradeoff")
    alternative = _btc_item_by_role(btc_items, "stabilityAlternative")
    repair_observation = _btc_item_by_role(btc_items, "repairObservation")
    stable_metrics = _dict(stable.get("metrics"))
    frontier_metrics = _dict(frontier.get("metrics"))
    alternative_metrics = _dict(alternative.get("metrics"))
    consensus_btc = _dict(_dict(selection_consensus).get("btc"))
    stable_aliases = _alias_strategy_ids(_dict(stable.get("selectionBasis")))
    frontier_aliases = _alias_strategy_ids(_dict(frontier.get("selectionBasis")))
    alternative_aliases = _alias_strategy_ids(_dict(alternative.get("selectionBasis")))
    alternative_selection_basis = _dict(alternative.get("selectionBasis"))
    stable_selection_basis = _dict(stable.get("selectionBasis"))
    frontier_drift_detected = bool(consensus_btc.get("strongestYieldFrontierDriftDetected"))
    strongest_yield_now_strategy_id = consensus_btc.get("strongestYieldNowStrategyId") or frontier.get("strategyId")
    stable_and_yield_converged = bool(
        isinstance(strongest_yield_now_strategy_id, str)
        and strongest_yield_now_strategy_id
        and strongest_yield_now_strategy_id == stable.get("strategyId")
    )
    stable_valid_window_count = stable_metrics.get("validWindowCount")
    prefer_stability_challenger = _btc_prefer_stability_challenger(frontier, alternative)
    near_live_challenger = alternative if prefer_stability_challenger else frontier
    near_live_challenger_aliases = alternative_aliases if prefer_stability_challenger else frontier_aliases
    near_live_selection_basis = _dict(near_live_challenger.get("selectionBasis"))
    near_live_scan_plan = _dict(_dict(scan).get("nextFocusedSearchPlan"))
    yield_frontier_third = frontier if prefer_stability_challenger else alternative
    near_live_repair_best_strategy_id = near_live_selection_basis.get("nearLiveRepairBestStrategyId")
    near_live_repair_improves_baseline = near_live_selection_basis.get("nearLiveRepairImprovesBaseline")
    near_live_repair_outcome_zh = near_live_selection_basis.get("nearLiveRepairOutcomeZh")
    near_live_followup_best_strategy_id = near_live_selection_basis.get("nearLiveFollowupBestStrategyId")
    near_live_followup_improves_repair = near_live_selection_basis.get("nearLiveFollowupImprovesRepair")
    near_live_followup_outcome_zh = near_live_selection_basis.get("nearLiveFollowupOutcomeZh")
    near_live_refinement_best_strategy_id = near_live_selection_basis.get("nearLiveRefinementBestStrategyId")
    near_live_refinement_improves_followup = near_live_selection_basis.get("nearLiveRefinementImprovesFollowup")
    near_live_refinement_outcome_zh = near_live_selection_basis.get("nearLiveRefinementOutcomeZh")
    near_live_middle_window_best_strategy_id = near_live_selection_basis.get("nearLiveMiddleWindowFollowupBestStrategyId")
    near_live_middle_window_improves_followup = near_live_selection_basis.get("nearLiveMiddleWindowFollowupImprovesFollowup")
    near_live_middle_window_outcome_zh = near_live_selection_basis.get("nearLiveMiddleWindowFollowupOutcomeZh")
    near_live_signal_refinement_best_strategy_id = (
        near_live_selection_basis.get("nearLiveSignalRefinementBestStrategyId")
        or near_live_scan_plan.get("nearLiveSignalRefinementBestStrategyId")
    )
    near_live_signal_refinement_improves_contender = (
        near_live_selection_basis.get("nearLiveSignalRefinementImprovesContender")
        if near_live_selection_basis.get("nearLiveSignalRefinementImprovesContender") is not None
        else near_live_scan_plan.get("nearLiveSignalRefinementImprovesContender")
    )
    near_live_signal_refinement_outcome_zh = (
        near_live_selection_basis.get("nearLiveSignalRefinementOutcomeZh")
        or near_live_scan_plan.get("nearLiveSignalRefinementOutcomeZh")
    )
    near_live_cluster_refinement_best_strategy_id = near_live_selection_basis.get("nearLiveClusterRefinementBestStrategyId")
    near_live_cluster_refinement_improves_contender = near_live_selection_basis.get("nearLiveClusterRefinementImprovesContender")
    near_live_cluster_refinement_outcome_zh = near_live_selection_basis.get("nearLiveClusterRefinementOutcomeZh")
    near_live_tempo_refinement_best_strategy_id = (
        near_live_selection_basis.get("nearLiveTempoRefinementBestStrategyId")
        or near_live_scan_plan.get("nearLiveTempoRefinementBestStrategyId")
    )
    near_live_tempo_refinement_improves_contender = (
        near_live_selection_basis.get("nearLiveTempoRefinementImprovesContender")
        if near_live_selection_basis.get("nearLiveTempoRefinementImprovesContender") is not None
        else near_live_scan_plan.get("nearLiveTempoRefinementImprovesContender")
    )
    near_live_tempo_refinement_outcome_zh = (
        near_live_selection_basis.get("nearLiveTempoRefinementOutcomeZh")
        or near_live_scan_plan.get("nearLiveTempoRefinementOutcomeZh")
    )
    near_live_stoploss_ladder_best_strategy_id = (
        near_live_selection_basis.get("nearLiveStoplossLadderRefinementBestStrategyId")
        or near_live_scan_plan.get("nearLiveStoplossLadderRefinementBestStrategyId")
    )
    near_live_stoploss_ladder_improves_contender = (
        near_live_selection_basis.get("nearLiveStoplossLadderRefinementImprovesContender")
        if near_live_selection_basis.get("nearLiveStoplossLadderRefinementImprovesContender") is not None
        else near_live_scan_plan.get("nearLiveStoplossLadderRefinementImprovesContender")
    )
    near_live_stoploss_ladder_outcome_zh = (
        near_live_selection_basis.get("nearLiveStoplossLadderRefinementOutcomeZh")
        or near_live_scan_plan.get("nearLiveStoplossLadderRefinementOutcomeZh")
    )
    near_live_stoploss_ladder_followup_micro_best_strategy_id = (
        near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroBestStrategyId")
        or near_live_scan_plan.get("nearLiveStoplossLadderFollowupMicroBestStrategyId")
    )
    near_live_stoploss_ladder_followup_micro_improves_refinement = (
        near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroImprovesRefinement")
        if near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroImprovesRefinement") is not None
        else near_live_scan_plan.get("nearLiveStoplossLadderFollowupMicroImprovesRefinement")
    )
    near_live_stoploss_ladder_followup_micro_improves_contender = (
        near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroImprovesContender")
        if near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroImprovesContender") is not None
        else near_live_scan_plan.get("nearLiveStoplossLadderFollowupMicroImprovesContender")
    )
    near_live_stoploss_ladder_followup_micro_outcome_zh = (
        near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroOutcomeZh")
        or near_live_scan_plan.get("nearLiveStoplossLadderFollowupMicroOutcomeZh")
    )
    near_live_stoploss_ladder_followup_micro_followup_best_strategy_id = (
        near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId")
        or near_live_scan_plan.get("nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId")
    )
    near_live_stoploss_ladder_followup_micro_followup_improves_micro = (
        near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro")
        if near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro") is not None
        else near_live_scan_plan.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro")
    )
    near_live_stoploss_ladder_followup_micro_followup_improves_contender = (
        near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesContender")
        if near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesContender") is not None
        else near_live_scan_plan.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesContender")
    )
    near_live_stoploss_ladder_followup_micro_followup_outcome_zh = (
        near_live_selection_basis.get("nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh")
        or near_live_scan_plan.get("nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh")
    )
    near_live_exit_refinement_best_strategy_id = (
        near_live_selection_basis.get("nearLiveExitRefinementBestStrategyId")
        or near_live_scan_plan.get("nearLiveExitRefinementBestStrategyId")
    )
    near_live_exit_refinement_improves_contender = (
        near_live_selection_basis.get("nearLiveExitRefinementImprovesContender")
        if near_live_selection_basis.get("nearLiveExitRefinementImprovesContender") is not None
        else near_live_scan_plan.get("nearLiveExitRefinementImprovesContender")
    )
    near_live_exit_refinement_outcome_zh = (
        near_live_selection_basis.get("nearLiveExitRefinementOutcomeZh")
        or near_live_scan_plan.get("nearLiveExitRefinementOutcomeZh")
    )
    near_live_middle_tradeoff_best_strategy_id = (
        near_live_selection_basis.get("nearLiveMiddleTradeoffBestStrategyId")
        or near_live_scan_plan.get("nearLiveMiddleTradeoffBestStrategyId")
    )
    near_live_middle_tradeoff_improves_contender = (
        near_live_selection_basis.get("nearLiveMiddleTradeoffImprovesContender")
        if near_live_selection_basis.get("nearLiveMiddleTradeoffImprovesContender") is not None
        else near_live_scan_plan.get("nearLiveMiddleTradeoffImprovesContender")
    )
    near_live_middle_tradeoff_outcome_zh = (
        near_live_selection_basis.get("nearLiveMiddleTradeoffOutcomeZh")
        or near_live_scan_plan.get("nearLiveMiddleTradeoffOutcomeZh")
    )
    near_live_middle_density_best_strategy_id = (
        near_live_selection_basis.get("nearLiveMiddleDensityLiftBestStrategyId")
        or near_live_scan_plan.get("nearLiveMiddleDensityLiftBestStrategyId")
    )
    near_live_middle_density_improves_contender = (
        near_live_selection_basis.get("nearLiveMiddleDensityLiftImprovesContender")
        if near_live_selection_basis.get("nearLiveMiddleDensityLiftImprovesContender") is not None
        else near_live_scan_plan.get("nearLiveMiddleDensityLiftImprovesContender")
    )
    near_live_middle_density_outcome_zh = (
        near_live_selection_basis.get("nearLiveMiddleDensityLiftOutcomeZh")
        or near_live_scan_plan.get("nearLiveMiddleDensityLiftOutcomeZh")
    )
    stable_middle_repair_best_strategy_id = stable_selection_basis.get("stableMiddleThirdRepairBestStrategyId")
    stable_middle_repair_improves_baseline = stable_selection_basis.get("stableMiddleThirdRepairImprovesBaseline")
    stable_middle_repair_outcome_zh = stable_selection_basis.get("stableMiddleThirdRepairOutcomeZh")
    stable_middle_followup_best_strategy_id = stable_selection_basis.get("stableMiddleThirdFollowupBestStrategyId")
    stable_middle_followup_improves_aggregate = stable_selection_basis.get("stableMiddleThirdFollowupImprovesAggregate")
    stable_middle_followup_improves_weak_window = stable_selection_basis.get("stableMiddleThirdFollowupImprovesWeakWindow")
    stable_middle_followup_improves_repair = stable_selection_basis.get("stableMiddleThirdFollowupImprovesRepair")
    stable_middle_followup_outcome_zh = stable_selection_basis.get("stableMiddleThirdFollowupOutcomeZh")
    stable_middle_weak_window_best_strategy_id = stable_selection_basis.get("stableMiddleWeakWindowConfirmationBestStrategyId")
    stable_middle_weak_window_improves_baseline = stable_selection_basis.get("stableMiddleWeakWindowConfirmationImprovesBaseline")
    stable_middle_weak_window_outcome_zh = stable_selection_basis.get("stableMiddleWeakWindowConfirmationOutcomeZh")
    stable_middle_weak_window_bridge_best_strategy_id = stable_selection_basis.get("stableMiddleWeakWindowBridgeBestStrategyId")
    stable_middle_weak_window_bridge_improves_aggregate = stable_selection_basis.get("stableMiddleWeakWindowBridgeImprovesAggregate")
    stable_middle_weak_window_bridge_improves_weak_window = stable_selection_basis.get("stableMiddleWeakWindowBridgeImprovesWeakWindow")
    stable_middle_weak_window_bridge_improves_baseline = stable_selection_basis.get("stableMiddleWeakWindowBridgeImprovesBaseline")
    stable_middle_weak_window_bridge_outcome_zh = stable_selection_basis.get("stableMiddleWeakWindowBridgeOutcomeZh")
    repair_candidate = _btc_scan_plan_repair_candidate(stable_selection_basis)
    stable_middle_tradeoff_followup_best_tradeoff = _dict(stable_selection_basis.get("stableMiddleTradeoffFollowupBestTradeoff"))
    stable_middle_tradeoff_followup_best_strategy_id = stable_selection_basis.get("stableMiddleTradeoffFollowupBestStrategyId")
    stable_middle_tradeoff_followup_improves_bridge = stable_selection_basis.get("stableMiddleTradeoffFollowupImprovesBridge")
    stable_middle_tradeoff_followup_improves_weak_window = stable_selection_basis.get("stableMiddleTradeoffFollowupImprovesWeakWindow")
    stable_middle_tradeoff_followup_improves_baseline = stable_selection_basis.get("stableMiddleTradeoffFollowupImprovesBaseline")
    stable_middle_tradeoff_followup_outcome_zh = stable_selection_basis.get("stableMiddleTradeoffFollowupOutcomeZh")
    repair_tradeoff = _dict(repair_candidate.get("tradeoff")) or stable_middle_tradeoff_followup_best_tradeoff or repair_observation
    repair_strategy_id = str(repair_candidate.get("strategyId") or repair_tradeoff.get("strategyId") or "")
    repair_strategy_label_zh = str(stable_selection_basis.get("repairStrategyLabelZh") or "stable middle tradeoff repair line")
    repair_strategy_role_zh = str(stable_selection_basis.get("repairStrategyRoleZh") or "第三条 distinct 弱窗口修复路径")
    repair_strategy_action_role_zh = (
        "第三顺位稳定 fallback 线"
        if repair_strategy_role_zh == "第三条 distinct 稳定 fallback 路径"
        else "第三顺位弱窗口修复线"
    )
    frontier_selection_basis = _dict(frontier.get("selectionBasis"))
    yield_leader_confirmation_best_strategy_id = frontier_selection_basis.get("yieldLeaderConfirmationBestStrategyId")
    yield_leader_confirmation_improves_baseline = frontier_selection_basis.get("yieldLeaderConfirmationImprovesBaseline")
    yield_leader_confirmation_outcome_zh = frontier_selection_basis.get("yieldLeaderConfirmationOutcomeZh")
    recommended_focused_retest_order = [
        item
        for item in _list(stable_selection_basis.get("recommendedFocusedRetestOrder"))
        if isinstance(item, str) and item
    ]
    if not recommended_focused_retest_order:
        recommended_focused_retest_order = [
            item.get("strategyId")
            for item in (
                stable,
                near_live_challenger,
                repair_tradeoff if stable_middle_tradeoff_followup_improves_baseline else yield_frontier_third,
                yield_frontier_third if stable_middle_tradeoff_followup_improves_baseline else repair_tradeoff,
            )
            if isinstance(item.get("strategyId"), str)
            and item.get("strategyId")
        ]
    stability_first_top3_strategy_ids = recommended_focused_retest_order[:3]
    near_live_challenger_strategy_id = near_live_challenger.get("strategyId")
    if stable_and_yield_converged:
        preferred_converged_challenger_strategy_id = next(
            (
                item
                for item in stability_first_top3_strategy_ids[1:]
                if isinstance(item, str) and item and item != stable.get("strategyId")
            ),
            "",
        )
        if preferred_converged_challenger_strategy_id:
            near_live_challenger_strategy_id = preferred_converged_challenger_strategy_id
            if near_live_challenger_strategy_id != near_live_challenger.get("strategyId"):
                near_live_challenger_aliases = []
    challenger_converged_with_yield_frontier = stable_and_yield_converged or (
        bool(near_live_challenger.get("strategyId"))
        and near_live_challenger.get("strategyId") == frontier.get("strategyId")
    )
    near_live_middle_window_variant_rows = _btc_near_live_middle_window_variants(scan or {})
    near_live_middle_window_variant_strategy_ids = [
        row.get("strategyId")
        for row in near_live_middle_window_variant_rows
        if isinstance(row.get("strategyId"), str) and row.get("strategyId")
    ]
    near_live_middle_window_variant_stop_loss_ladder = [
        row.get("stopLossPriceMove")
        for row in near_live_middle_window_variant_rows
        if row.get("stopLossPriceMove") is not None
    ]
    near_live_middle_window_variant_summary_zh = _btc_near_live_middle_window_variant_summary(
        near_live_middle_window_variant_rows
    )
    near_live_converged_variant_rows = _btc_near_live_converged_variants(scan or {})
    near_live_converged_variant_strategy_ids = [
        row.get("strategyId")
        for row in near_live_converged_variant_rows
        if isinstance(row.get("strategyId"), str) and row.get("strategyId")
    ]
    near_live_converged_variant_stop_loss_ladder = [
        row.get("stopLossPriceMove")
        for row in near_live_converged_variant_rows
        if row.get("stopLossPriceMove") is not None
    ]
    near_live_converged_variant_summary_zh = _btc_near_live_converged_variant_summary(
        near_live_converged_variant_rows
    )
    if challenger_converged_with_yield_frontier and near_live_converged_variant_strategy_ids:
        yield_inclusive_top3_strategy_ids = near_live_converged_variant_strategy_ids[:3]
    else:
        yield_inclusive_top3_strategy_ids = [
            item.get("strategyId")
            for item in (stable, near_live_challenger, yield_frontier_third)
            if isinstance(item.get("strategyId"), str) and item.get("strategyId")
        ]
        repair_tradeoff_strategy_id = repair_tradeoff.get("strategyId")
        if len(yield_inclusive_top3_strategy_ids) < 3 and repair_tradeoff_strategy_id:
            yield_inclusive_top3_strategy_ids.append(repair_tradeoff_strategy_id)
        yield_inclusive_top3_strategy_ids = yield_inclusive_top3_strategy_ids[:3]
    yield_metrics = stable_metrics if stable_and_yield_converged else frontier_metrics
    stability_first_summary_zh = (
        f"更接近落地的稳定前三: {' -> '.join(stability_first_top3_strategy_ids)}。"
        if stability_first_top3_strategy_ids
        else "更接近落地的稳定前三: 当前仍未形成。"
    )
    yield_inclusive_summary_zh = (
        (
            f"稳定 challenger 与收益 frontier 已收敛到同一参数簇，当前 distinct 主 shortlist: {' -> '.join(yield_inclusive_top3_strategy_ids)}。"
            if challenger_converged_with_yield_frontier and yield_inclusive_top3_strategy_ids
            else f"收益纳入后的主 shortlist: {' -> '.join(yield_inclusive_top3_strategy_ids)}。"
        )
        if yield_inclusive_top3_strategy_ids
        else "收益纳入后的主 shortlist: 当前仍未形成。"
    )
    if stable_and_yield_converged and near_live_signal_refinement_improves_contender:
        tradeoff_repair_label = "stable middle tradeoff repair line"
        recommendation_zh = (
            "默认继续拿当前已收敛的稳健/收益锚点做主研究对象，"
            "先复验 signal refinement 找到的 next distinct near-live contender，"
            f"再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}。"
        )
    elif stable_and_yield_converged and near_live_tempo_refinement_improves_contender:
        tradeoff_repair_label = "stable middle tradeoff repair line"
        recommendation_zh = (
            "默认继续拿当前已收敛的稳健/收益锚点做主研究对象，"
            "先复验 tempo refinement 找到的 next distinct near-live contender，"
            f"再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}。"
        )
    elif stable_and_yield_converged and near_live_stoploss_ladder_improves_contender:
        tradeoff_repair_label = "stable middle tradeoff repair line"
        recommendation_zh = (
            "默认继续拿当前已收敛的稳健/收益锚点做主研究对象，"
            "先复验 stop-loss ladder refinement 找到的 next distinct near-live contender，"
            f"再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}。"
        )
    elif stable_and_yield_converged and near_live_exit_refinement_improves_contender:
        tradeoff_repair_label = "stable middle tradeoff repair line"
        recommendation_zh = (
            "默认继续拿当前已收敛的稳健/收益锚点做主研究对象，"
            "先复验 exit refinement 找到的 next distinct near-live contender，"
            f"再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}。"
        )
    elif prefer_stability_challenger and near_live_signal_refinement_improves_contender:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，先复验 near-live signal refinement 提升出的 next distinct challenger，再把 stable middle tradeoff repair line 作为第三顺位弱窗口修复线，最后保留当前高收益 frontier 做收益对照。"
    elif prefer_stability_challenger and near_live_tempo_refinement_improves_contender:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，先复验 near-live tempo refinement 提升出的 next distinct challenger，再把 stable middle tradeoff repair line 作为第三顺位弱窗口修复线，最后保留当前高收益 frontier 做收益对照。"
    elif prefer_stability_challenger and near_live_stoploss_ladder_improves_contender:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，先复验 near-live stop-loss ladder refinement 提升出的 next distinct challenger，再把 stable middle tradeoff repair line 作为第三顺位弱窗口修复线，最后保留当前高收益 frontier 做收益对照。"
    elif prefer_stability_challenger and near_live_exit_refinement_improves_contender:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，先复验 near-live exit refinement 提升出的 next distinct challenger，再把 stable middle tradeoff repair line 作为第三顺位弱窗口修复线，最后保留当前高收益 frontier 做收益对照。"
    elif stable_and_yield_converged and near_live_challenger.get("strategyId"):
        recommendation_zh = (
            "默认继续拿当前已收敛的稳健/收益锚点做主研究对象，"
            "先复验 converged-cluster 下的 next distinct near-live challenger，"
            f"再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}。"
        )
    elif prefer_stability_challenger and near_live_middle_density_improves_contender:
        recommendation_zh = f"默认继续拿稳健锚点做主研究对象，先复验 near-live middle-density lift 提升出的 next distinct challenger，再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}，最后保留当前高收益 frontier 做收益对照。"
    elif prefer_stability_challenger and near_live_middle_tradeoff_improves_contender:
        recommendation_zh = f"默认继续拿稳健锚点做主研究对象，先复验 near-live middle tradeoff 提升出的 next distinct challenger，再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}，最后保留当前高收益 frontier 做收益对照。"
    elif prefer_stability_challenger and near_live_middle_window_improves_followup:
        recommendation_zh = f"默认继续拿稳健锚点做主研究对象，先复验 middle-window 后的稳定 challenger，再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}，最后保留当前高收益 frontier 做收益对照。"
    elif prefer_stability_challenger and near_live_refinement_improves_followup:
        recommendation_zh = f"默认继续拿稳健锚点做主研究对象，先复验 refinement 后的稳定 challenger，再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}，最后保留当前高收益 frontier 做收益对照。"
    elif prefer_stability_challenger and stable_middle_followup_improves_weak_window:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，先复验稳定 challenger，再围绕 stable middle-third follow-up 修当前稳健锚点的 middle_third，最后把当前高收益 frontier 作为收益对照。"
    elif prefer_stability_challenger and stable_middle_tradeoff_followup_improves_baseline:
        recommendation_zh = f"默认继续拿稳健锚点做主研究对象，先复验稳定 challenger，再把 {repair_strategy_label_zh} 作为{repair_strategy_action_role_zh}，最后保留当前高收益 frontier 做收益对照。"
    elif prefer_stability_challenger and stable_middle_tradeoff_followup_best_strategy_id:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，先复验稳定 challenger，再把当前高收益 frontier 作为第三顺位收益对照，并把 stable middle tradeoff repair line 作为第四顺位修复观察线。"
    elif prefer_stability_challenger:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，先复验稳定 challenger，再把当前高收益 frontier 作为第三顺位收益对照。"
    elif frontier_drift_detected:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，同时用当前高收益 frontier 做第二对照。"
    else:
        recommendation_zh = "默认继续拿稳健锚点做主研究对象，同时保留高收益候选做收益对照。"
    return {
        "status": "BTC_LINEUP_BOARD_READY",
        "stableAnchorStrategyId": stable.get("strategyId"),
        "stableAnchorSameParameterSetAs": stable_aliases,
        "stableMiddleThirdRepairBestStrategyId": stable_middle_repair_best_strategy_id,
        "stableMiddleThirdRepairImprovesBaseline": stable_middle_repair_improves_baseline,
        "stableMiddleThirdRepairOutcomeZh": stable_middle_repair_outcome_zh,
        "stableMiddleThirdFollowupBestStrategyId": stable_middle_followup_best_strategy_id,
        "stableMiddleThirdFollowupImprovesAggregate": stable_middle_followup_improves_aggregate,
        "stableMiddleThirdFollowupImprovesWeakWindow": stable_middle_followup_improves_weak_window,
        "stableMiddleThirdFollowupImprovesRepair": stable_middle_followup_improves_repair,
        "stableMiddleThirdFollowupOutcomeZh": stable_middle_followup_outcome_zh,
        "stableMiddleWeakWindowConfirmationBestStrategyId": stable_middle_weak_window_best_strategy_id,
        "stableMiddleWeakWindowConfirmationImprovesBaseline": stable_middle_weak_window_improves_baseline,
        "stableMiddleWeakWindowConfirmationOutcomeZh": stable_middle_weak_window_outcome_zh,
        "stableMiddleWeakWindowBridgeBestStrategyId": stable_middle_weak_window_bridge_best_strategy_id,
        "stableMiddleWeakWindowBridgeImprovesAggregate": stable_middle_weak_window_bridge_improves_aggregate,
        "stableMiddleWeakWindowBridgeImprovesWeakWindow": stable_middle_weak_window_bridge_improves_weak_window,
        "stableMiddleWeakWindowBridgeImprovesBaseline": stable_middle_weak_window_bridge_improves_baseline,
        "stableMiddleWeakWindowBridgeOutcomeZh": stable_middle_weak_window_bridge_outcome_zh,
        "stableMiddleTradeoffFollowupBestTradeoff": stable_middle_tradeoff_followup_best_tradeoff,
        "stableMiddleTradeoffFollowupBestStrategyId": stable_middle_tradeoff_followup_best_strategy_id,
        "stableMiddleTradeoffFollowupImprovesBridge": stable_middle_tradeoff_followup_improves_bridge,
        "stableMiddleTradeoffFollowupImprovesWeakWindow": stable_middle_tradeoff_followup_improves_weak_window,
        "stableMiddleTradeoffFollowupImprovesBaseline": stable_middle_tradeoff_followup_improves_baseline,
        "stableMiddleTradeoffFollowupOutcomeZh": stable_middle_tradeoff_followup_outcome_zh,
        "yieldFrontierStrategyId": strongest_yield_now_strategy_id,
        "yieldFrontierSameParameterSetAs": frontier_aliases,
        "yieldLeaderConfirmationBestStrategyId": yield_leader_confirmation_best_strategy_id,
        "yieldLeaderConfirmationImprovesBaseline": yield_leader_confirmation_improves_baseline,
        "yieldLeaderConfirmationOutcomeZh": yield_leader_confirmation_outcome_zh,
        "stabilityAlternativeStrategyId": alternative.get("strategyId"),
        "stabilityAlternativeSameParameterSetAs": alternative_aliases,
        "nearLiveChallengerStrategyId": near_live_challenger_strategy_id,
        "nearLiveChallengerSameParameterSetAs": near_live_challenger_aliases,
        "nearLiveRepairBestStrategyId": near_live_repair_best_strategy_id,
        "nearLiveRepairImprovesBaseline": near_live_repair_improves_baseline,
        "nearLiveRepairOutcomeZh": near_live_repair_outcome_zh,
        "nearLiveFollowupBestStrategyId": near_live_followup_best_strategy_id,
        "nearLiveFollowupImprovesRepair": near_live_followup_improves_repair,
        "nearLiveFollowupOutcomeZh": near_live_followup_outcome_zh,
        "nearLiveRefinementBestStrategyId": near_live_refinement_best_strategy_id,
        "nearLiveRefinementImprovesFollowup": near_live_refinement_improves_followup,
        "nearLiveRefinementOutcomeZh": near_live_refinement_outcome_zh,
        "nearLiveMiddleWindowFollowupBestStrategyId": near_live_middle_window_best_strategy_id,
        "nearLiveMiddleWindowFollowupImprovesFollowup": near_live_middle_window_improves_followup,
        "nearLiveMiddleWindowFollowupOutcomeZh": near_live_middle_window_outcome_zh,
        "nearLiveSignalRefinementBestStrategyId": near_live_signal_refinement_best_strategy_id,
        "nearLiveSignalRefinementImprovesContender": near_live_signal_refinement_improves_contender,
        "nearLiveSignalRefinementOutcomeZh": near_live_signal_refinement_outcome_zh,
        "nearLiveClusterRefinementBestStrategyId": near_live_cluster_refinement_best_strategy_id,
        "nearLiveClusterRefinementImprovesContender": near_live_cluster_refinement_improves_contender,
        "nearLiveClusterRefinementOutcomeZh": near_live_cluster_refinement_outcome_zh,
        "nearLiveTempoRefinementBestStrategyId": near_live_tempo_refinement_best_strategy_id,
        "nearLiveTempoRefinementImprovesContender": near_live_tempo_refinement_improves_contender,
        "nearLiveTempoRefinementOutcomeZh": near_live_tempo_refinement_outcome_zh,
        "nearLiveStoplossLadderRefinementBestStrategyId": near_live_stoploss_ladder_best_strategy_id,
        "nearLiveStoplossLadderRefinementImprovesContender": near_live_stoploss_ladder_improves_contender,
        "nearLiveStoplossLadderRefinementOutcomeZh": near_live_stoploss_ladder_outcome_zh,
        "nearLiveStoplossLadderFollowupMicroBestStrategyId": near_live_stoploss_ladder_followup_micro_best_strategy_id,
        "nearLiveStoplossLadderFollowupMicroImprovesRefinement": near_live_stoploss_ladder_followup_micro_improves_refinement,
        "nearLiveStoplossLadderFollowupMicroImprovesContender": near_live_stoploss_ladder_followup_micro_improves_contender,
        "nearLiveStoplossLadderFollowupMicroOutcomeZh": near_live_stoploss_ladder_followup_micro_outcome_zh,
        "nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId": (
            near_live_stoploss_ladder_followup_micro_followup_best_strategy_id
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro": (
            near_live_stoploss_ladder_followup_micro_followup_improves_micro
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupImprovesContender": (
            near_live_stoploss_ladder_followup_micro_followup_improves_contender
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh": (
            near_live_stoploss_ladder_followup_micro_followup_outcome_zh
        ),
        "nearLiveExitRefinementBestStrategyId": near_live_exit_refinement_best_strategy_id,
        "nearLiveExitRefinementImprovesContender": near_live_exit_refinement_improves_contender,
        "nearLiveExitRefinementOutcomeZh": near_live_exit_refinement_outcome_zh,
        "nearLiveMiddleTradeoffBestStrategyId": near_live_middle_tradeoff_best_strategy_id,
        "nearLiveMiddleTradeoffImprovesContender": near_live_middle_tradeoff_improves_contender,
        "nearLiveMiddleTradeoffOutcomeZh": near_live_middle_tradeoff_outcome_zh,
        "nearLiveMiddleDensityLiftBestStrategyId": near_live_middle_density_best_strategy_id,
        "nearLiveMiddleDensityLiftImprovesContender": near_live_middle_density_improves_contender,
        "nearLiveMiddleDensityLiftOutcomeZh": near_live_middle_density_outcome_zh,
        "optimizerBaselineStrategyId": consensus_btc.get("strongestYieldOptimizerBaselineStrategyId"),
        "frontierDriftDetected": frontier_drift_detected,
        "stableLeadZh": (
            f"稳定性领先: validWindowCount={stable_valid_window_count}，且当前没有负收益窗口。"
            if stable_valid_window_count is not None
            else "稳定性领先: 当前稳健默认的窗口健康度更完整。"
        ),
        "nearLiveLeadZh": (
            f"近实时盘 challenger: validWindowCount={alternative_metrics.get('validWindowCount')}、tradeCount={alternative_metrics.get('tradeCount')}，比当前收益 frontier 更接近稳定复验。"
            if prefer_stability_challenger and alternative.get("strategyId")
            else (
                f"近实时盘 challenger: 当前仍由收益 frontier 担任，pnlUsd={frontier_metrics.get('pnlUsd')}、sharpe={frontier_metrics.get('sharpe')}。"
                if frontier.get("strategyId")
                else "近实时盘 challenger: 当前还没有明确第二候选。"
            )
        ),
        "yieldLeadZh": (
            f"收益领先已与稳健锚点收敛: pnlUsd={yield_metrics.get('pnlUsd')}、sharpe={yield_metrics.get('sharpe')}。"
            if stable_and_yield_converged
            else (
                f"收益领先: pnlUsd={yield_metrics.get('pnlUsd')}、sharpe={yield_metrics.get('sharpe')}。"
                if frontier.get("strategyId")
                else "收益领先: 当前还没有明确的收益 challenger。"
            )
        ),
        "stabilityFirstTop3StrategyIds": stability_first_top3_strategy_ids,
        "yieldInclusiveTop3StrategyIds": yield_inclusive_top3_strategy_ids,
        "stabilityFirstSummaryZh": stability_first_summary_zh,
        "yieldInclusiveSummaryZh": yield_inclusive_summary_zh,
        "nearLiveMiddleWindowVariantRows": near_live_middle_window_variant_rows,
        "nearLiveMiddleWindowVariantStrategyIds": near_live_middle_window_variant_strategy_ids,
        "nearLiveMiddleWindowVariantStopLossLadder": near_live_middle_window_variant_stop_loss_ladder,
        "nearLiveMiddleWindowVariantSummaryZh": near_live_middle_window_variant_summary_zh,
        "nearLiveConvergedVariantRows": near_live_converged_variant_rows,
        "nearLiveConvergedVariantStrategyIds": near_live_converged_variant_strategy_ids,
        "nearLiveConvergedVariantStopLossLadder": near_live_converged_variant_stop_loss_ladder,
        "nearLiveConvergedVariantSummaryZh": near_live_converged_variant_summary_zh,
        "challengerConvergedWithYieldFrontier": challenger_converged_with_yield_frontier,
        "recommendationZh": recommendation_zh,
        "recommendedFocusedRetestOrder": recommended_focused_retest_order,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _btc_focus_retest_order_zh(
    btc_lineup_board: dict[str, Any],
    *,
    prefix: str = "BTC 先按 ",
    suffix: str = " 做 focused retest。",
) -> str:
    order = [
        str(item)
        for item in _list(_dict(btc_lineup_board).get("recommendedFocusedRetestOrder"))
        if isinstance(item, str) and item
    ]
    if not order:
        order = [
            str(_dict(item).get("strategyId"))
            for item in _list(_dict(btc_lineup_board).get("focusedRetestQueue"))
            if isinstance(_dict(item).get("strategyId"), str) and _dict(item).get("strategyId")
        ]
    if not order:
        return "BTC 继续按当前 shortlist 做 focused retest。"
    return f"{prefix}{' -> '.join(order)}{suffix}"


def _go_live_gap(
    *,
    lane_verdicts: dict[str, Any],
    mt5_lane_readiness: dict[str, Any],
    btc_lane_readiness: dict[str, Any],
    live_activation_blockers: list[str],
) -> dict[str, Any]:
    mt5_blockers = _list(mt5_lane_readiness.get("blockers"))
    btc_blockers = _list(btc_lane_readiness.get("blockers"))
    shared_blockers = [code for code in live_activation_blockers if isinstance(code, str)]
    return {
        "status": "GO_LIVE_GAP_READY",
        "mt5": {
            "focusStrategyId": _dict(_dict(lane_verdicts.get("mt5")).get("strongestNow")).get("strategyId"),
            "topBlockers": mt5_blockers[:3],
            "blockerCount": len(mt5_blockers),
            "nextActionZh": mt5_lane_readiness.get("nextActionZh"),
            "readinessChecklist": _dict(mt5_lane_readiness.get("readinessChecklist")),
            "queueCount": _dict(mt5_lane_readiness.get("testerSnapshot")).get("queueCount"),
            "abCandidateIds": _list(_dict(mt5_lane_readiness.get("testerSnapshot")).get("abCandidateIds")),
            "variantCandidateIds": _list(_dict(mt5_lane_readiness.get("testerSnapshot")).get("variantCandidateIds")),
            "gateDiagnostics": _dict(mt5_lane_readiness.get("gateDiagnostics")),
            "sharedReleaseBlockers": shared_blockers[:3],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "btc": {
            "focusStrategyId": _dict(_dict(lane_verdicts.get("btc")).get("mostStableNow")).get("strategyId"),
            "topBlockers": btc_blockers[:3],
            "blockerCount": len(btc_blockers),
            "nextActionZh": btc_lane_readiness.get("nextActionZh"),
            "readinessChecklist": _dict(btc_lane_readiness.get("readinessChecklist")),
            "gateDiagnostics": _dict(btc_lane_readiness.get("gateDiagnostics")),
            "directExecutionBlockerCode": _dict(btc_lane_readiness.get("runtimeSnapshot")).get("directExecutionBlockerCode"),
            "directExecutionBlockerDetailZh": _dict(btc_lane_readiness.get("runtimeSnapshot")).get("directExecutionBlockerDetailZh"),
            "permissionChainHealthy": _dict(btc_lane_readiness.get("runtimeSnapshot")).get("permissionChainHealthy"),
            "sharedReleaseBlockers": shared_blockers[:3],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _execution_readiness_board(
    *,
    strategy_shortlist: dict[str, Any],
    promotion_queue: dict[str, Any],
    live_upgrade_selection: dict[str, Any],
    target_reached: bool,
    release_ready: bool,
    blockers: list[str],
) -> dict[str, Any]:
    lane_verdicts = _dict(strategy_shortlist.get("laneVerdicts"))
    mt5_readiness = _dict(strategy_shortlist.get("mt5LaneReadiness"))
    btc_readiness = _dict(strategy_shortlist.get("btcLaneReadiness"))
    go_live_gap = _dict(strategy_shortlist.get("goLiveGap"))
    promotion_counts = _dict(promotion_queue.get("counts"))
    mt5_focus = _dict(_dict(lane_verdicts.get("mt5")).get("strongestNow"))
    btc_focus = _dict(_dict(lane_verdicts.get("btc")).get("mostStableNow"))
    mt5_tester_snapshot = _dict(mt5_readiness.get("testerSnapshot"))
    btc_runtime_snapshot = _dict(btc_readiness.get("runtimeSnapshot"))
    btc_next_action_zh, btc_why_now_zh, btc_current_mode_zh = _btc_runtime_focus(
        btc_runtime_snapshot,
        _list(btc_readiness.get("blockers")),
    )
    ready_for_release = int(_num(promotion_counts.get("readyForSeparateReleaseLane")))
    can_proceed_to_separate_release_lane = bool(
        target_reached
        and release_ready
        and not blockers
        and ready_for_release > 0
    )

    mt5_blockers = _list(mt5_readiness.get("blockers"))
    mt5_process_blockers = _list(mt5_readiness.get("supportingProcessBlockers"))
    btc_blockers = _list(btc_readiness.get("blockers"))
    mt5_can_run_tester = bool(mt5_readiness.get("canRunTester")) and not mt5_blockers
    btc_runtime_ready = bool(
        btc_readiness.get("runtimeProbePassed")
        and btc_readiness.get("dataPlaneReadyForLivePilotReview")
        and not btc_blockers
    )

    def action_row(
        *,
        priority: int,
        action_id: str,
        urgency: str,
        lane: str,
        focus_strategy_id: str | None,
        action_zh: str,
        blocker_codes: list[str],
        why_now_zh: str,
        evidence_summary_zh: str | None = None,
        evidence_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "priority": priority,
            "id": action_id,
            "urgency": urgency,
            "lane": lane,
            "focusStrategyId": focus_strategy_id,
            "actionZh": action_zh,
            "whyNowZh": why_now_zh,
            "blockerCount": len(blocker_codes),
            "topBlockers": blocker_codes[:3],
            "evidenceSummaryZh": evidence_summary_zh,
            "evidenceSnapshot": evidence_snapshot or {},
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        }

    next_actions: list[dict[str, Any]] = []
    if not btc_runtime_ready:
        next_actions.append(action_row(
            priority=len(next_actions) + 1,
            action_id="btc_runtime_preflight_refresh",
            urgency="now",
            lane="btcCryptoCfd",
            focus_strategy_id=btc_focus.get("strategyId"),
            action_zh=btc_next_action_zh,
            blocker_codes=btc_blockers,
            why_now_zh=btc_why_now_zh,
            evidence_summary_zh=btc_readiness.get("runtimeSummaryZh"),
            evidence_snapshot=btc_runtime_snapshot,
        ))
    if btc_focus.get("strategyId"):
        next_actions.append(action_row(
            priority=len(next_actions) + 1,
            action_id="btc_stable_anchor_retest",
            urgency="now",
            lane="btcCryptoCfd",
            focus_strategy_id=btc_focus.get("strategyId"),
            action_zh="围绕当前稳健默认继续修 middle_third，并保留高收益候选做收益对照。",
            blocker_codes=_list(_dict(go_live_gap.get("btc")).get("topBlockers")),
            why_now_zh="稳健默认仍是离实盘评审最近的 BTC 候选，继续补分段质量比换冠军更值钱。",
            evidence_summary_zh=btc_readiness.get("runtimeSummaryZh"),
            evidence_snapshot=btc_runtime_snapshot,
        ))
    if mt5_can_run_tester:
        next_actions.append(action_row(
            priority=len(next_actions) + 1,
            action_id="mt5_ab_tester_forward",
            urgency="now",
            lane="forexMt5",
            focus_strategy_id=mt5_focus.get("strategyId"),
            action_zh="对 G0093/G0102 执行隔离 tester-forward A/B，并把 TP/SL tester-only 变体并排复验。",
            blocker_codes=[],
            why_now_zh="MT5 当前 strongestNow 与 mostStableNow 仍需 A/B 决胜，tester-forward 是唯一有效证据。",
            evidence_summary_zh=mt5_readiness.get("testerSummaryZh"),
            evidence_snapshot=mt5_tester_snapshot,
        ))
    else:
        mt5_runtime_gate_blockers = [
            code for code in mt5_blockers
            if code in {"live_dashboard_snapshot_stale", "mt5_terminal_process_missing"}
        ]
        mt5_runtime_gate_why_now = (
            "MT5 候选本身已相对稳定，当前主要卡在主 terminal 进程缺失和 dashboard freshness；不先恢复这两项，今晚窗口打开也不能进入 tester-forward。"
            if "mt5_terminal_process_missing" in mt5_runtime_gate_blockers
            else "MT5 候选本身已相对稳定，当前主要卡在 dashboard freshness；不先恢复主 MT5/EA 刷新，今晚窗口打开也不能进入 tester-forward。"
            if "live_dashboard_snapshot_stale" in mt5_runtime_gate_blockers
            else "MT5 候选本身已相对稳定，当前主要卡在 tester gate 未清空。"
        )
        mt5_runtime_gate_snapshot = dict(mt5_tester_snapshot)
        if mt5_process_blockers:
            mt5_runtime_gate_snapshot["processEvidenceBlockers"] = mt5_process_blockers
        process_evidence = _dict(mt5_readiness.get("processEvidence"))
        for key in (
            "preferredTerminalPath",
            "candidateTerminalPaths",
            "dashboardPath",
            "startupConfigPath",
            "dashboardServerRunning",
            "readOnlyVerificationCommands",
        ):
            value = process_evidence.get(key)
            if value not in (None, "", []):
                mt5_runtime_gate_snapshot[key] = value
        next_actions.append(action_row(
            priority=len(next_actions) + 1,
            action_id="restore_live_mt5_dashboard_refresh" if mt5_runtime_gate_blockers else "mt5_clear_tester_gate",
            urgency="next_window",
            lane="forexMt5",
            focus_strategy_id=mt5_focus.get("strategyId"),
            action_zh=(
                _mt5_terminal_restore_action_zh(mt5_readiness)
                if "mt5_terminal_process_missing" in mt5_runtime_gate_blockers
                else "主 MT5/EA 未持续刷新 live dashboard；恢复前不能确认 live session freshness。"
                if mt5_runtime_gate_blockers
                else "先清空 MT5 tester gate，再在窗口内启动 G0093/G0102 的 A/B tester-forward。"
            ),
            blocker_codes=mt5_blockers,
            why_now_zh=mt5_runtime_gate_why_now,
            evidence_summary_zh=mt5_readiness.get("testerSummaryZh"),
            evidence_snapshot=mt5_runtime_gate_snapshot,
        ))
        if "outside_strategy_tester_window" in mt5_blockers:
            next_actions.append(action_row(
                priority=len(next_actions) + 1,
                action_id="wait_for_tester_window",
                urgency="scheduled",
                lane="forexMt5",
                focus_strategy_id=mt5_focus.get("strategyId"),
                action_zh="等待 20:10-23:30 JST tester 窗口后自动刷新 champion tester run gate。",
                blocker_codes=["outside_strategy_tester_window"],
                why_now_zh=(
                    "tester window 还没开；但这一步只能自动清时间窗口本身，不能替代主 terminal/dashboard 恢复。"
                ),
                evidence_summary_zh=mt5_readiness.get("testerSummaryZh"),
                evidence_snapshot=mt5_tester_snapshot,
            ))
        next_actions.append(action_row(
            priority=len(next_actions) + 1,
            action_id="run_forex_ab_tester_forward",
            urgency="after_gate_clear",
            lane="forexMt5",
            focus_strategy_id=mt5_focus.get("strategyId"),
            action_zh="对 G0093/G0102 执行隔离 tester-forward A/B，并把 TP/SL tester-only 变体并排复验。",
            blocker_codes=mt5_blockers,
            why_now_zh=(
                "A/B 主对照和 TP/SL 变体队列都已就绪；当前仍需先清 dashboard/process/window blocker，之后再进入 guarded tester-forward run。"
            ),
            evidence_summary_zh=mt5_readiness.get("testerSummaryZh"),
            evidence_snapshot=mt5_tester_snapshot,
        ))
    lane_snapshots = [
        {
            "lane": "forexMt5",
            "focusStrategyId": mt5_focus.get("strategyId"),
            "currentModeZh": (
                "可进入隔离 tester-forward"
                if mt5_can_run_tester
                else "等待 tester 环境清空 gate"
            ),
            "blockerCount": len(mt5_blockers),
            "topBlockers": mt5_blockers[:3],
            "readinessChecklist": _dict(mt5_readiness.get("readinessChecklist")),
            "evidenceSummaryZh": mt5_readiness.get("testerSummaryZh"),
            "evidenceSnapshot": mt5_tester_snapshot,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        {
            "lane": "btcCryptoCfd",
            "focusStrategyId": btc_focus.get("strategyId"),
            "currentModeZh": (
                "接近独立 release 评审"
                if btc_runtime_ready
                else btc_current_mode_zh
            ),
            "blockerCount": len(btc_blockers),
            "topBlockers": btc_blockers[:3],
            "readinessChecklist": _dict(btc_readiness.get("readinessChecklist")),
            "evidenceSummaryZh": btc_readiness.get("runtimeSummaryZh"),
            "evidenceSnapshot": btc_runtime_snapshot,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
    ]
    closest_lane = "btcCryptoCfd" if btc_runtime_ready or len(btc_blockers) <= len(mt5_blockers) else "forexMt5"
    next_actions = sorted(
        next_actions,
        key=lambda item: 0 if _dict(item).get("lane") == closest_lane else 1,
    )[:3]
    for index, item in enumerate(next_actions, start=1):
        item["priority"] = index
    if next_actions:
        live_upgrade_selection["nextActionZh"] = _dict(next_actions[0]).get("actionZh") or live_upgrade_selection.get("nextActionZh")

    closure_queue: list[dict[str, Any]] = []
    primary_closure_queue: list[dict[str, Any]] = []
    deferred_closure_queue: list[dict[str, Any]] = []
    lane_snapshot_order = sorted(
        lane_snapshots,
        key=lambda item: 0 if item.get("lane") == closest_lane else 1,
    )
    for lane_snapshot in lane_snapshot_order:
        readiness_rows = _list(_dict(lane_snapshot.get("readinessChecklist")).get("rows"))
        readiness_by_id = {
            str(_dict(row).get("id")): _dict(row)
            for row in readiness_rows
            if isinstance(_dict(row).get("id"), str)
        }
        for row in readiness_rows:
            closure_row = _dict(row)
            if closure_row.get("ok"):
                continue
            dependency_check_ids = [
                check_id for check_id in _list(closure_row.get("dependencyCheckIds"))
                if isinstance(check_id, str)
            ]
            blocking_dependency_check_ids = [
                check_id
                for check_id in dependency_check_ids
                if not bool(_dict(readiness_by_id.get(check_id)).get("ok"))
            ]
            closure_entry = {
                "priority": len(closure_queue) + 1,
                "lane": lane_snapshot.get("lane"),
                "focusStrategyId": lane_snapshot.get("focusStrategyId"),
                "currentModeZh": lane_snapshot.get("currentModeZh"),
                "checkId": closure_row.get("id"),
                "labelZh": closure_row.get("labelZh"),
                "sourceArtifact": closure_row.get("sourceArtifact"),
                "evidenceKeyZh": closure_row.get("evidenceKeyZh"),
                "dependencyCheckIds": dependency_check_ids,
                "blockingDependencyCheckIds": blocking_dependency_check_ids,
                "isPrimaryActionable": not blocking_dependency_check_ids,
                "nextActionZh": closure_row.get("nextActionZh"),
                "blockerCount": lane_snapshot.get("blockerCount"),
                "topBlockers": _list(lane_snapshot.get("topBlockers"))[:3],
                "evidenceSummaryZh": lane_snapshot.get("evidenceSummaryZh"),
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
            }
            closure_queue.append(closure_entry)
            if closure_entry["isPrimaryActionable"]:
                primary_closure_queue.append(closure_entry)
            else:
                deferred_closure_queue.append(closure_entry)

    return {
        "status": "EXECUTION_READINESS_BOARD_READY",
        "canProceedToSeparateReleaseLane": can_proceed_to_separate_release_lane,
        "readyStrategyCountForSeparateReleaseLane": ready_for_release,
        "closestResearchLaneNow": closest_lane,
        "selectedLaneForSeparateReleaseReview": live_upgrade_selection.get("selectedLane"),
        "laneSnapshots": lane_snapshots,
        "nextActionsOverall": next_actions,
        "closureQueue": closure_queue,
        "primaryClosureQueue": primary_closure_queue,
        "deferredClosureQueue": deferred_closure_queue,
        "closureSummaryZh": (
            f"当前待闭环 {len(closure_queue)} 项；"
            f"主闭环项 {len(primary_closure_queue)} 项；"
            f"依赖前置项 {len(deferred_closure_queue)} 项；"
            f"优先 lane={closest_lane}；"
            f"首项={_dict(primary_closure_queue[0]).get('checkId') if primary_closure_queue else (_dict(closure_queue[0]).get('checkId') if closure_queue else '无')}。"
        ),
        "releaseReadinessZh": (
            "当前没有候选达到独立 release lane 评审条件。"
            if not can_proceed_to_separate_release_lane
            else "至少一条 lane 已满足独立 release lane 评审前置条件。"
        ),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _promotion_queue(
    strategy_shortlist: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    mt5_readiness = _dict(strategy_shortlist.get("mt5LaneReadiness"))
    btc_readiness = _dict(strategy_shortlist.get("btcLaneReadiness"))
    mt5_items = [_dict(item) for item in _list(strategy_shortlist.get("mt5TopStrategies"))]
    btc_items = [_dict(item) for item in _list(strategy_shortlist.get("btcTopStrategies"))]

    queue: list[dict[str, Any]] = []

    def add_queue_item(
        *,
        priority: int,
        rank_in_lane: int,
        lane: str,
        role: str,
        summary_type: str,
        strategy_id: str | None,
        seed_id: str | None,
        promotion_stage: str,
        can_advance_now: bool,
        lane_ready_for_review: bool,
        blocking_reasons: list[str],
        next_action_zh: str | None,
        tester_only: bool,
    ) -> None:
        queue.append({
            "priority": priority,
            "rankInLane": rank_in_lane,
            "lane": lane,
            "role": role,
            "summaryType": summary_type,
            "strategyId": strategy_id,
            "seedId": seed_id,
            "promotionStage": promotion_stage,
            "canAdvanceNow": can_advance_now,
            "laneReadyForReview": lane_ready_for_review,
            "readyForSeparateReleaseLane": bool(lane_ready_for_review and not blockers and not blocking_reasons),
            "blockingReasons": blocking_reasons,
            "nextActionZh": next_action_zh,
            "testerOnly": tester_only,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })

    mt5_can_run_tester = bool(mt5_readiness.get("canRunTester"))
    mt5_lane_ready_for_review = mt5_can_run_tester and not _list(mt5_readiness.get("blockers"))
    for rank, item in enumerate(mt5_items, start=1):
        if item.get("summaryType") == "tester_forward_variant":
            stage = "tester_variant_forward_next" if mt5_can_run_tester else "wait_tester_gate"
        else:
            stage = "tester_ab_next" if mt5_can_run_tester else "wait_tester_gate"
        add_queue_item(
            priority=len(queue) + 1,
            rank_in_lane=rank,
            lane="forexMt5",
            role=str(item.get("role") or ""),
            summary_type=str(item.get("summaryType") or ""),
            strategy_id=item.get("strategyId"),
            seed_id=item.get("seedId"),
            promotion_stage=stage,
            can_advance_now=mt5_can_run_tester,
            lane_ready_for_review=mt5_lane_ready_for_review,
            blocking_reasons=_merge_unique_codes(mt5_readiness.get("blockers"), item.get("blockers")),
            next_action_zh=item.get("nextActionZh") or mt5_readiness.get("nextActionZh"),
            tester_only=bool(item.get("testerOnly", True)),
        )

    btc_live_review_ready = bool(
        btc_readiness.get("runtimeProbePassed")
        and btc_readiness.get("dataPlaneReadyForLivePilotReview")
        and not _list(btc_readiness.get("blockers"))
    )
    btc_stage_map = {
        "stableAnchor": "focused_retest_next",
        "highYieldTradeoff": "focused_retest_compare",
        "stabilityAlternative": "stability_compare",
        "sampleRichBridge": "sample_density_repair",
    }
    for rank, item in enumerate(btc_items, start=1):
        add_queue_item(
            priority=len(queue) + 1,
            rank_in_lane=rank,
            lane="btcCryptoCfd",
            role=str(item.get("role") or ""),
            summary_type=str(item.get("summaryType") or ""),
            strategy_id=item.get("strategyId"),
            seed_id=item.get("seedId"),
            promotion_stage=btc_stage_map.get(str(item.get("role") or ""), "focused_retest_next"),
            can_advance_now=True,
            lane_ready_for_review=btc_live_review_ready,
            blocking_reasons=_merge_unique_codes(btc_readiness.get("blockers"), item.get("blockers")),
            next_action_zh=item.get("nextActionZh") or btc_readiness.get("nextActionZh"),
            tester_only=bool(item.get("testerOnly", True)),
        )

    actionable_now = sum(1 for item in queue if item.get("canAdvanceNow"))
    blocked_now = len(queue) - actionable_now
    ready_for_release = sum(1 for item in queue if item.get("readyForSeparateReleaseLane"))
    return {
        "status": "PROMOTION_QUEUE_READY",
        "statusZh": "升级推进队列已生成；只读输出，不触发实盘执行。",
        "queue": queue,
        "counts": {
            "total": len(queue),
            "actionableNow": actionable_now,
            "blockedNow": blocked_now,
            "readyForSeparateReleaseLane": ready_for_release,
        },
        "nextActionZh": (
            "MT5 队列等待 tester gate 清空后进入 G0093/G0102 A/B；"
            f"{_btc_focus_retest_order_zh(strategy_shortlist.get('btcLineupBoard'), prefix='BTC 队列按 ', suffix=' 继续 focused retest，并补 runtime preflight 数据面。')}"
        ),
        "safety": {
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesMt5OrderRequest": False,
            "writesLivePreset": False,
        },
    }


def _readiness_progress(readiness_checklist: dict[str, Any]) -> dict[str, Any]:
    ready_count = int(_num(readiness_checklist.get("readyCount")))
    total_count = int(_num(readiness_checklist.get("totalCount")))
    pct = round((ready_count / total_count), 4) if total_count else 0.0
    return {
        "readyCount": ready_count,
        "totalCount": total_count,
        "ratio": f"{ready_count}/{total_count}",
        "pct": pct,
    }


def _launch_board(
    strategy_shortlist: dict[str, Any],
    execution_readiness_board: dict[str, Any],
    live_upgrade_selection: dict[str, Any],
) -> dict[str, Any]:
    selection_consensus = _dict(strategy_shortlist.get("selectionConsensus"))
    lane_verdicts = _dict(strategy_shortlist.get("laneVerdicts"))
    mt5_ab_board = _dict(strategy_shortlist.get("mt5AbBoard"))
    btc_lineup_board = _dict(strategy_shortlist.get("btcLineupBoard")) or _dict(strategy_shortlist.get("btcDuelBoard"))
    mt5_readiness = _dict(strategy_shortlist.get("mt5LaneReadiness"))
    btc_readiness = _dict(strategy_shortlist.get("btcLaneReadiness"))
    go_live_gap = _dict(strategy_shortlist.get("goLiveGap"))

    closest_lane = str(execution_readiness_board.get("closestResearchLaneNow") or "")
    selected_release_lane = str(live_upgrade_selection.get("selectedLane") or "")
    selected_release_strategy = _dict(live_upgrade_selection.get("selectedStrategy"))
    lane_conflict_detected = bool(
        closest_lane and selected_release_lane and closest_lane != selected_release_lane
    )

    mt5_focus = _dict(_dict(lane_verdicts.get("mt5")).get("strongestNow"))
    btc_focus = _dict(_dict(lane_verdicts.get("btc")).get("mostStableNow"))
    mt5_progress = _readiness_progress(_dict(mt5_readiness.get("readinessChecklist")))
    btc_progress = _readiness_progress(_dict(btc_readiness.get("readinessChecklist")))
    mt5_gate = _dict(mt5_readiness.get("gateDiagnostics"))
    btc_gate = _dict(btc_readiness.get("gateDiagnostics"))

    critical_path: list[dict[str, Any]] = []
    for rank, row in enumerate(_list(execution_readiness_board.get("primaryClosureQueue"))[:4], start=1):
        item = _dict(row)
        critical_path.append({
            "priority": rank,
            "lane": item.get("lane"),
            "checkId": item.get("checkId"),
            "labelZh": item.get("labelZh"),
            "nextActionZh": item.get("nextActionZh"),
            "topBlockers": _list(item.get("topBlockers"))[:3],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })

    lane_boards = {
        "mt5": {
            "lane": "forexMt5",
            "focusSeedId": mt5_focus.get("seedId"),
            "focusStrategyId": mt5_focus.get("strategyId"),
            "abContenderSeedId": mt5_ab_board.get("contenderSeedId"),
            "consensusLevel": _dict(selection_consensus.get("mt5")).get("consensusLevel"),
            "supportingSourceCount": _dict(selection_consensus.get("mt5")).get("agreementCount"),
            "readiness": mt5_progress,
            "blockerFamilies": [
                "window" if _list(mt5_gate.get("autoClearAtWindowBlockers")) else None,
                "manual_refresh" if _list(mt5_gate.get("manualRefreshBlockers")) else None,
                "sensitive_sync" if _list(mt5_gate.get("manualSensitiveBlockers")) else None,
            ],
            "topBlockers": _list(_dict(go_live_gap.get("mt5")).get("topBlockers"))[:3],
            "queueCount": _dict(go_live_gap.get("mt5")).get("queueCount"),
            "windowBriefing": _dict(mt5_readiness.get("windowBriefing")),
            "isClosestToLiveNow": closest_lane == "forexMt5",
            "isSelectedReleaseCandidate": selected_release_lane == "forexMt5",
            "canLaunchNow": False,
            "nextMilestoneZh": "先清空 tester gate，再在窗口内跑 G0093/G0102 A/B tester-forward。",
            "activeAbSummaryZh": mt5_ab_board.get("recommendationZh"),
            "summaryZh": (
                f"共识={_dict(selection_consensus.get('mt5')).get('consensusLevel')} "
                f"support={_dict(selection_consensus.get('mt5')).get('agreementCount')} "
                f"readiness={mt5_progress.get('ratio')}；当前仍需先过 tester gate。"
            ),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "btc": {
            "lane": "btcCryptoCfd",
            "focusStrategyId": btc_focus.get("strategyId"),
            "sameParameterSetAs": _list(btc_focus.get("sameParameterSetAs")),
            "nearLiveChallengerStrategyId": btc_lineup_board.get("nearLiveChallengerStrategyId"),
            "nearLiveChallengerSameParameterSetAs": _list(btc_lineup_board.get("nearLiveChallengerSameParameterSetAs")),
            "yieldFrontierStrategyId": btc_lineup_board.get("yieldFrontierStrategyId"),
            "yieldFrontierSameParameterSetAs": _list(btc_lineup_board.get("yieldFrontierSameParameterSetAs")),
            "consensusLevel": _dict(selection_consensus.get("btc")).get("mostStableConsensusLevel"),
            "supportingSourceCount": _dict(selection_consensus.get("btc")).get("mostStableAgreementCount"),
            "readiness": btc_progress,
            "blockerFamilies": [
                "external_refresh" if _list(btc_gate.get("externalRefreshBlockers")) else None,
                "data_plane" if _list(btc_gate.get("dataPlaneBlockers")) else None,
                "execution_mode" if _list(btc_gate.get("executionModeBlockers")) else None,
            ],
            "topBlockers": _list(_dict(go_live_gap.get("btc")).get("topBlockers"))[:3],
            "directExecutionBlockerCode": _dict(go_live_gap.get("btc")).get("directExecutionBlockerCode"),
            "isClosestToLiveNow": closest_lane == "btcCryptoCfd",
            "isSelectedReleaseCandidate": selected_release_lane == "btcCryptoCfd",
            "canLaunchNow": False,
            "nextMilestoneZh": "先刷新 live16 dashboard，再把 livePilot/readOnly/executionEnabled/tradeAllowed 证据补齐。",
            "activeLineupSummaryZh": btc_lineup_board.get("recommendationZh"),
            "activeDuelSummaryZh": btc_lineup_board.get("recommendationZh"),
            "summaryZh": (
                f"共识={_dict(selection_consensus.get('btc')).get('mostStableConsensusLevel')} "
                f"support={_dict(selection_consensus.get('btc')).get('mostStableAgreementCount')} "
                f"readiness={btc_progress.get('ratio')}；当前更接近 live，但 execution-mode 仍未放行。"
            ),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
    }

    recommended_launch_order = [
        {
            "priority": 1 if closest_lane == "btcCryptoCfd" else 2,
            "lane": "btcCryptoCfd",
            "focusStrategyId": lane_boards["btc"].get("focusStrategyId"),
            "whyZh": "当前 readiness 更接近 live，但仍卡 dashboard freshness 与 execution mode。",
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        {
            "priority": 1 if closest_lane == "forexMt5" else 2,
            "lane": "forexMt5",
            "focusStrategyId": lane_boards["mt5"].get("focusStrategyId"),
            "whyZh": "当前是独立 release 候选，但必须先通过 nightly tester gate 和 A/B 决胜。",
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
    ]
    recommended_launch_order.sort(key=lambda row: _num(row.get("priority"), default=99))
    for lane_board in lane_boards.values():
        lane_board["blockerFamilies"] = [
            family for family in _list(lane_board.get("blockerFamilies"))
            if isinstance(family, str) and family
        ]

    return {
        "status": "LAUNCH_BOARD_READY",
        "currentClosestLaneNow": closest_lane,
        "selectedReleaseCandidateLane": selected_release_lane or None,
        "selectedReleaseCandidateStrategyId": selected_release_strategy.get("strategyId"),
        "laneConflictDetected": lane_conflict_detected,
        "laneConflictZh": (
            "BTC 当前更接近 live，但 MT5 仍是独立 release 候选；先补 BTC mode/freshness，再等 MT5 tester gate。"
            if lane_conflict_detected
            else "当前最近的 live lane 与 release 候选 lane 一致。"
        ),
        "laneBoards": lane_boards,
        "criticalPath": critical_path,
        "recommendedLaunchOrder": recommended_launch_order,
        "summaryZh": (
            f"closest={closest_lane or 'unknown'}；"
            f"releaseCandidate={selected_release_lane or 'unknown'}；"
            f"BTC readiness={lane_boards['btc']['readiness']['ratio']}；"
            f"MT5 readiness={lane_boards['mt5']['readiness']['ratio']}；"
            f"首个关键路径={_dict(critical_path[0]).get('checkId') if critical_path else '无'}。"
        ),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _find_candidate_by_lane(ace: dict[str, Any], lane: str) -> dict[str, Any]:
    for candidate in _list(ace.get("candidates")):
        row = _dict(candidate)
        if row.get("lane") == lane:
            return row
    return {}


def _rsi_demotion_review(
    ace: dict[str, Any],
    forex_pack: dict[str, Any],
    btc: dict[str, Any],
    strategy_shortlist: dict[str, Any],
) -> dict[str, Any]:
    raw_rsi = _find_candidate_by_lane(ace, "live12_raw_rsi")
    blockers = _list(raw_rsi.get("blockers"))
    decision = raw_rsi.get("decision")
    should_demote = bool(
        not raw_rsi
        or decision == "DISCARD_AS_ACE"
        or "NET_PROFIT_NOT_POSITIVE" in blockers
        or "PROFIT_FACTOR_LT_1_05" in blockers
        or _num(raw_rsi.get("profitFactor")) < 1.05
    )
    status = "RSI_LIVE_LOGIC_DEMOTE_REVIEW" if should_demote else "RSI_LIVE_LOGIC_KEEP_REVIEW"
    recommended_action = "DEMOTE_RAW_RSI_FROM_ACE" if should_demote else "KEEP_RAW_RSI_SHADOW_REVIEW"
    leaders = _dict(btc.get("middleWindowLeaders"))
    btc_lineup_board = _dict(strategy_shortlist.get("btcLineupBoard"))
    return {
        "status": status,
        "lane": "live12_raw_rsi",
        "decision": decision or ("MISSING_FROM_ACE_SCOUT" if not raw_rsi else None),
        "recommendedAction": recommended_action,
        "recommendedActionZh": (
            "raw Live12 RSI 已降级为 shadow/review，不再作为王牌升级对象。"
            if should_demote
            else "raw Live12 RSI 只保留 shadow 观察，升级前仍需重新通过复验。"
        ),
        "currentEvidence": {
            "strategyId": raw_rsi.get("strategyId"),
            "netProfitUSC": raw_rsi.get("netProfitUSC"),
            "profitFactor": raw_rsi.get("profitFactor"),
            "sharpe": raw_rsi.get("sharpe"),
            "tradeCount": raw_rsi.get("tradeCount"),
            "blockers": blockers,
            "liveUnsafeReason": raw_rsi.get("liveUnsafeReason"),
        },
        "replacementPlan": {
            "primaryForexAce": {
                "seedId": forex_pack.get("seedId"),
                "strategyId": forex_pack.get("strategyId"),
                "status": forex_pack.get("status"),
                "contenderTieBreakRequired": forex_pack.get("contenderTieBreakRequired"),
                "contenders": forex_pack.get("contenders"),
                "metrics": forex_pack.get("metrics"),
            },
            "btcTargetMiddleQuality": _dict(leaders.get("bestTargetMiddleQuality")),
            "btcBestMiddleQuality": _dict(leaders.get("bestMiddleQuality")),
            "nextActionZh": (
                "优先用外币 G0093/G0102 做隔离 tester/forward A/B；"
                f"{_btc_focus_retest_order_zh(btc_lineup_board, prefix='BTC 继续按 ', suffix=' 做 focused retest，')}"
                "不把 raw RSI 直接升回实盘。"
            ),
        },
        "safety": {
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "livePresetMutationAllowed": False,
            "writesMt5OrderRequest": False,
            "writesLivePreset": False,
        },
    }


def _live_upgrade_selection(
    rsi_review: dict[str, Any],
    forex_pack: dict[str, Any],
    btc: dict[str, Any],
) -> dict[str, Any]:
    rsi_demoted = rsi_review.get("status") == "RSI_LIVE_LOGIC_DEMOTE_REVIEW"
    forex_ready = forex_pack.get("status") == "FOREX_CHAMPION_RETEST_PASS" and bool(forex_pack.get("seedId"))
    selected_lane = "forexMt5" if forex_ready else "btcCryptoCfd"
    selected_strategy = {
        "lane": "forexMt5",
        "seedId": forex_pack.get("seedId"),
        "strategyId": forex_pack.get("strategyId"),
        "strategyFamily": forex_pack.get("strategyFamily"),
        "status": forex_pack.get("status"),
        "metrics": forex_pack.get("metrics"),
        "contenderTieBreakRequired": bool(forex_pack.get("contenderTieBreakRequired")),
        "contenders": forex_pack.get("contenders") or [],
        "testerVariantQueue": forex_pack.get("testerVariantQueue") or [],
    } if forex_ready else _btc_candidate(_dict(btc.get("finalAdvisoryPick")), role="selectedDefault")
    excluded: list[dict[str, Any]] = []
    if rsi_demoted:
        excluded.append({
            "lane": rsi_review.get("lane"),
            "strategyId": _dict(rsi_review.get("currentEvidence")).get("strategyId"),
            "reason": rsi_review.get("recommendedAction"),
            "reasonZh": rsi_review.get("recommendedActionZh"),
            "currentEvidence": rsi_review.get("currentEvidence"),
        })
    return {
        "status": (
            "RSI_DEMOTED_FOREX_AB_READY"
            if rsi_demoted and forex_ready and forex_pack.get("contenderTieBreakRequired")
            else ("RSI_DEMOTED_REPLACEMENT_READY" if rsi_demoted else "UPGRADE_SELECTION_REVIEW")
        ),
        "statusZh": (
            "raw RSI 已排除；G0093/G0102 作为外汇王牌 A/B 进入 tester-forward。"
            if rsi_demoted and forex_ready
            else "升级选择器已生成；仍需复验后才能进入独立执行评审。"
        ),
        "selectedLane": selected_lane,
        "selectedStrategy": selected_strategy,
        "excludedAceCandidates": excluded,
        "upgradePrerequisites": [
            "isolated_tester_forward_report_ready",
            "champion_tester_run_gate_ready",
            "separate_execution_release_lane_ready",
        ],
        "nextActionZh": (
            "先跑 G0093/G0102 隔离 tester-forward A/B 和 TP/SL 变体，胜者才允许进入独立 release lane；"
            "raw RSI 继续保持 shadow/review。"
        ),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "writesLivePreset": False,
        "livePresetMutationAllowed": False,
    }


def _execution_blockers(profit_target: dict[str, Any], matrix: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    live_review = _dict(profit_target.get("liveExecutionReview"))
    for row in _list(_dict(live_review.get("executionReleaseGateSummary")).get("blockerCodes")):
        if isinstance(row, str) and row not in blockers:
            blockers.append(row)
    for row in _list(_dict(matrix.get("decision")).get("releaseGateSummary", {}).get("blockerCodes")):
        if isinstance(row, str) and row not in blockers:
            blockers.append(row)
    for row in _list(summary.get("topBlockers")):
        code = row.get("code") if isinstance(row, dict) else row
        if isinstance(code, str) and code not in blockers:
            blockers.append(code)
    for row in _list(profit_target.get("blockers")):
        code = row.get("code") if isinstance(row, dict) else row
        if isinstance(code, str) and code not in blockers:
            blockers.append(code)
    return blockers


def _resolve_ace_strategy_scout(runtime_dir: Path) -> dict[str, Any]:
    try:
        from tools.ace_strategy_scout import read_ace_strategy_scout
    except ModuleNotFoundError:  # pragma: no cover
        from ace_strategy_scout import read_ace_strategy_scout
    return _dict(read_ace_strategy_scout(runtime_dir))


def build_ace_execution_candidate_pack(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    agent_dir = runtime / "agent"
    ace = _resolve_ace_strategy_scout(runtime)
    retest = _read_json(agent_dir / "QuantGod_ChampionRetestReport.json")
    tpsl = _read_json(agent_dir / "QuantGod_TpSlOptimizerReport.json")
    scan = _read_json(agent_dir / "QuantGod_BtcStrategyScanReport.json")
    run_gate = _read_json(agent_dir / "QuantGod_ChampionTesterRunGate.json")
    preflight = _read_json(agent_dir / "QuantGod_LiveRuntimePreflightProbe.json")
    live_evidence_intake = _read_json(agent_dir / "QuantGod_LiveEvidenceIntake.json")
    profit_target = _read_json(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json")
    matrix = _read_json(agent_dir / "QuantGod_ReleaseTokenSignoffEvidenceMatrix.json")
    summary = _read_json(agent_dir / "QuantGod_SimTargetExecutionReviewSummary.json")

    btc = _dict(tpsl.get("btcCryptoCfd"))
    stable = _dict(btc.get("recommendedStable"))
    target = _dict(btc.get("recommendedTargetSeeking"))
    aggressive = _dict(btc.get("bestHighPnl"))
    final_pick = _dict(btc.get("finalAdvisoryPick")) or stable
    final_policy = btc.get("finalAdvisoryPickPolicy") or "STABLE_DEFAULT"
    final_reason = btc.get("finalAdvisoryPickReasonZh") or "默认采用稳健候选继续复验。"

    combined = _dict(profit_target.get("combinedTarget"))
    target_reached = bool(profit_target.get("targetReached") or combined.get("targetReached"))
    blockers = _execution_blockers(profit_target, matrix, summary)
    release_ready = bool(_dict(summary.get("executionReview")).get("releaseReady"))
    order_send_allowed = False

    default_lane = "forexMt5" if _dict(ace.get("topQualifiedForex")) else "btcCryptoCfd"
    if final_pick and not _dict(ace.get("topQualifiedForex")):
        default_lane = "btcCryptoCfd"

    forex = _forex_pack(ace, retest, tpsl)
    strategy_shortlist = _strategy_shortlist(ace, retest, forex, final_pick, btc, scan, run_gate, preflight, blockers)
    rsi_review = _rsi_demotion_review(ace, forex, btc, strategy_shortlist)
    rsi_demoted = rsi_review.get("status") == "RSI_LIVE_LOGIC_DEMOTE_REVIEW"
    live_upgrade_selection = _live_upgrade_selection(rsi_review, forex, btc)
    btc_default_shortlist_item = _btc_item_by_role(
        [_dict(item) for item in _list(strategy_shortlist.get("btcTopStrategies"))],
        "stableAnchor",
    )
    btc_default_candidate = (
        _btc_candidate_from_shortlist_item(btc_default_shortlist_item, role="selectedDefault")
        if btc_default_shortlist_item
        else _btc_candidate(final_pick, role="selectedDefault")
    )
    btc_default_strategy_id = btc_default_candidate.get("strategyId") or final_pick.get("strategyId")
    btc_default_reason_zh = (
        _dict(btc_default_shortlist_item.get("selectionBasis")).get("reasonZh")
        if btc_default_shortlist_item
        else final_reason
    ) or final_reason
    btc_focused_retest_queue = _btc_focused_retest_queue(
        btc=btc,
        strategy_shortlist=strategy_shortlist,
    )
    btc_focus_ids = [
        _dict(item).get("strategyId")
        for item in btc_focused_retest_queue[:3]
        if _dict(item).get("strategyId")
    ]
    btc_focus_summary_zh = " -> ".join(btc_focus_ids)
    live_upgrade_selection["laneSelections"] = {
        "forexMt5": {
            "lane": "forexMt5",
            "seedId": forex.get("seedId"),
            "strategyId": forex.get("strategyId"),
            "strategyFamily": forex.get("strategyFamily"),
            "status": forex.get("status"),
            "contenderTieBreakRequired": bool(forex.get("contenderTieBreakRequired")),
            "contenders": forex.get("contenders") or [],
            "testerVariantQueue": forex.get("testerVariantQueue") or [],
        },
        "btcCryptoCfd": btc_default_candidate,
    }
    live_upgrade_selection["selectedDefault"] = btc_default_candidate
    live_upgrade_selection["selectedDefaultSource"] = (
        "strategyShortlist.btcTopStrategies.stableAnchor"
        if btc_default_shortlist_item
        else "tpSlOptimizer.finalAdvisoryPick"
    )
    btc_lineup_board = _dict(strategy_shortlist.get("btcLineupBoard"))
    selected_default_reason_zh = btc_default_reason_zh
    converged_variant_summary_zh = btc_lineup_board.get("nearLiveConvergedVariantSummaryZh")
    if isinstance(converged_variant_summary_zh, str) and converged_variant_summary_zh:
        if selected_default_reason_zh:
            selected_default_reason_zh = f"{selected_default_reason_zh} {converged_variant_summary_zh}"
        else:
            selected_default_reason_zh = converged_variant_summary_zh
    live_upgrade_selection["selectedDefault"]["selectionReasonZh"] = selected_default_reason_zh
    if btc_lineup_board.get("nearLiveConvergedVariantSummaryZh"):
        live_upgrade_selection["selectedDefault"]["convergedVariantSummaryZh"] = btc_lineup_board.get("nearLiveConvergedVariantSummaryZh")
    if btc_lineup_board.get("nearLiveConvergedVariantStrategyIds"):
        live_upgrade_selection["selectedDefault"]["convergedVariantStrategyIds"] = list(
            _list(btc_lineup_board.get("nearLiveConvergedVariantStrategyIds"))
        )
    if btc_lineup_board.get("nearLiveConvergedVariantStopLossLadder"):
        live_upgrade_selection["selectedDefault"]["convergedVariantStopLossLadder"] = list(
            _list(btc_lineup_board.get("nearLiveConvergedVariantStopLossLadder"))
        )
    live_upgrade_selection["nextActionZh"] = (
        "先跑 G0093/G0102 隔离 tester-forward A/B 和 TP/SL 变体；"
        f"BTC 继续按 {btc_focus_summary_zh} 做 focused retest。"
        if forex.get("seedId")
        else f"BTC 继续按 {btc_focus_summary_zh} 做 focused retest。"
    )
    strategy_shortlist["focusedRetestQueue"] = btc_focused_retest_queue
    strategy_shortlist["selectedDefault"] = btc_default_candidate
    strategy_shortlist["selectedDefaultSource"] = live_upgrade_selection.get("selectedDefaultSource")
    strategy_shortlist["btcLineupBoard"] = {
        **_dict(strategy_shortlist.get("btcLineupBoard")),
        "focusedRetestQueue": btc_focused_retest_queue,
    }
    strategy_shortlist["btcDuelBoard"] = dict(_dict(strategy_shortlist.get("btcLineupBoard")))
    promotion_queue = _promotion_queue(strategy_shortlist, blockers)
    execution_readiness_board = _execution_readiness_board(
        strategy_shortlist=strategy_shortlist,
        promotion_queue=promotion_queue,
        live_upgrade_selection=live_upgrade_selection,
        target_reached=target_reached,
        release_ready=release_ready,
        blockers=blockers,
    )
    launch_board = _launch_board(strategy_shortlist, execution_readiness_board, live_upgrade_selection)
    can_proceed_to_separate_release_lane = bool(execution_readiness_board.get("canProceedToSeparateReleaseLane"))
    ready_for_separate_release_count = int(
        _num(execution_readiness_board.get("readyStrategyCountForSeparateReleaseLane"))
    )
    closest_research_lane_now = execution_readiness_board.get("closestResearchLaneNow")
    top_next_action_row = _dict(_list(execution_readiness_board.get("nextActionsOverall"))[0])
    top_next_action_zh = str(top_next_action_row.get("actionZh") or "").strip()
    if top_next_action_zh:
        btc_first_decision_next_action_zh = (
            f"raw RSI 已降级；当前第一动作是{top_next_action_zh}"
            f" 随后继续按 BTC {btc_focus_summary_zh} 这条稳定优先主线做 focused retest；当前不写订单。"
        )
        neutral_decision_next_action_zh = (
            f"当前第一动作是{top_next_action_zh}"
            f" 随后继续按 BTC {btc_focus_summary_zh} 这条稳定优先主线做 focused retest；当前不写订单。"
        )
    else:
        btc_first_decision_next_action_zh = (
            "raw RSI 已降级；目标已达成但当前仍只把外币 A/B 复验和 "
            f"BTC {btc_focus_summary_zh} 这条稳定优先主线交给独立 release lane，当前不写订单。"
        )
        neutral_decision_next_action_zh = (
            "目标已达成，继续把外币 A/B 复验和 "
            f"BTC {btc_focus_summary_zh} 这条稳定优先主线交给独立 release lane；当前不写订单。"
        )
    if closest_research_lane_now == "forexMt5":
        shortlist_next_action_zh = top_next_action_zh or (
            mt5_readiness.get("nextActionZh")
            or "MT5 先对 G0093/G0102 做隔离 tester/forward A/B。"
        )
    else:
        shortlist_next_action_zh = (
            f"{top_next_action_zh} 随后继续按 BTC {btc_focus_summary_zh} 做 focused retest。"
            if top_next_action_zh
            else (
                "MT5 先对 G0093/G0102 做隔离 tester/forward A/B；"
                f"{_btc_focus_retest_order_zh(strategy_shortlist.get('btcLineupBoard'))}"
            )
        )
    btc_lane_next_action_zh = (
        f"{top_next_action_zh} 随后继续按 BTC {btc_focus_summary_zh} 这条稳定优先主线做 focused retest。"
        if top_next_action_zh
        else (btc.get("nextActionZh") or "BTC 继续多窗口 TP/SL 复验。")
    )
    strategy_shortlist["nextActionZh"] = shortlist_next_action_zh
    strategy_shortlist["btcLaneReadiness"]["nextActionZh"] = (
        top_next_action_zh
        if top_next_action_zh
        else strategy_shortlist["btcLaneReadiness"].get("nextActionZh")
    )
    source_artifact_summaries = _source_artifact_summaries(
        agent_dir=agent_dir,
        ace=ace,
        retest=retest,
        tpsl=tpsl,
        scan=scan,
        run_gate=run_gate,
        preflight=preflight,
        live_evidence_intake=live_evidence_intake,
        profit_target=profit_target,
        matrix=matrix,
        summary=summary,
    )
    tpsl_summary = _dict(source_artifact_summaries.get("tpSlOptimizer"))
    legacy_stable_id = (
        tpsl_summary.get("optimizerLegacyStableStrategyId")
        or tpsl_summary.get("recommendedStableStrategyId")
    )
    legacy_final_pick_id = (
        tpsl_summary.get("optimizerLegacyFinalAdvisoryPickStrategyId")
        or tpsl_summary.get("finalAdvisoryPickStrategyId")
    )
    optimizer_legacy_stable_row = _dict(_dict(tpsl.get("btcCryptoCfd")).get("recommendedStable"))
    optimizer_legacy_final_pick_row = _dict(_dict(tpsl.get("btcCryptoCfd")).get("finalAdvisoryPick"))
    optimizer_legacy_stable_canonical_id = _resolve_current_btc_canonical_strategy_id(
        optimizer_legacy_stable_row,
        strategy_shortlist,
    )
    optimizer_legacy_final_pick_canonical_id = _resolve_current_btc_canonical_strategy_id(
        optimizer_legacy_final_pick_row,
        strategy_shortlist,
    )
    optimizer_legacy_canonical_id = (
        optimizer_legacy_final_pick_canonical_id
        or optimizer_legacy_stable_canonical_id
    )
    if tpsl_summary:
        tpsl_summary.update({
            "recommendedStableStrategyId": btc_default_strategy_id or legacy_stable_id,
            "finalAdvisoryPickStrategyId": btc_default_strategy_id or legacy_final_pick_id,
            "currentConsensusDefaultStrategyId": btc_default_strategy_id,
            "currentConsensusDefaultSource": "strategyShortlist.selectedDefault",
            "optimizerLegacyStableCanonicalStrategyId": optimizer_legacy_stable_canonical_id,
            "optimizerLegacyFinalAdvisoryPickCanonicalStrategyId": optimizer_legacy_final_pick_canonical_id,
            "optimizerLegacyCanonicalStrategyId": optimizer_legacy_canonical_id,
            "currentConsensusDiffersFromOptimizerLegacy": bool(
                btc_default_strategy_id
                and btc_default_strategy_id not in {legacy_stable_id, legacy_final_pick_id}
            ),
            "operatorSummaryZh": (
                f"旧 optimizer lineage 仍指向 {legacy_final_pick_id or legacy_stable_id or 'unknown'}"
                + (
                    f"，其当前 canonical 映射是 {optimizer_legacy_canonical_id}；"
                    if optimizer_legacy_canonical_id
                    else "；"
                )
                + f"当前 strongest/stablest default 已切到 {btc_default_strategy_id or 'unknown'}。"
            ),
        })

    report = {
        "ok": True,
        "schema": REPORT_SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "status": "ACE_EXECUTION_CANDIDATE_PACK_READY",
        "statusZh": "王牌执行候选包已生成；只读 advisory，不执行真实订单。",
        "decision": {
            "defaultResearchLane": default_lane,
            "defaultForexStrategyId": _dict(ace.get("topQualifiedForex")).get("strategyId"),
            "defaultBtcStrategyId": btc_default_strategy_id,
            "btcDefaultPolicy": final_policy,
            "btcDefaultReasonZh": btc_default_reason_zh,
            "profitTargetReached": target_reached,
            "combinedVerifiedUsdProfit": combined.get("combinedVerifiedUsdProfit"),
            "releaseReady": release_ready,
            "canProceedToSeparateReleaseLane": can_proceed_to_separate_release_lane,
            "readyStrategyCountForSeparateReleaseLane": ready_for_separate_release_count,
            "closestResearchLaneNow": closest_research_lane_now,
            "currentClosestLaneNow": launch_board.get("currentClosestLaneNow"),
            "selectedReleaseCandidateLane": launch_board.get("selectedReleaseCandidateLane"),
            "canReleaseExecutionNow": False,
            "orderSendAllowed": order_send_allowed,
            "mt5OrderSendAllowed": False,
            "nextActionZh": (
                btc_first_decision_next_action_zh
                if target_reached and rsi_demoted and closest_research_lane_now == "btcCryptoCfd"
                else (
                    neutral_decision_next_action_zh
                    if target_reached and closest_research_lane_now == "btcCryptoCfd"
                    else (
                        "raw RSI 已降级；目标已达成但当前仍只把外币 A/B 复验和 "
                        f"BTC {btc_focus_summary_zh} 这条稳定优先主线交给独立 release lane，当前不写订单。"
                        if target_reached and rsi_demoted
                        else (
                            "目标已达成，继续把外币 A/B 复验和 "
                            f"BTC {btc_focus_summary_zh} 这条稳定优先主线交给独立 release lane；当前不写订单。"
                            if target_reached
                            else "继续补模拟/forward 证据，直到任一 lane 或合计收益达到目标。"
                        )
                    )
                )
            ),
        },
        "liveUpgradeSelection": live_upgrade_selection,
        "strategyShortlist": strategy_shortlist,
        "promotionQueue": promotion_queue,
        "executionReadinessBoard": execution_readiness_board,
        "launchBoard": launch_board,
        "profitTarget": {
            "status": profit_target.get("status"),
            "targetReached": target_reached,
            "combinedVerifiedUsdProfit": combined.get("combinedVerifiedUsdProfit"),
            "targetUsd": _dict(profit_target.get("target")).get("targetUsd") or combined.get("targetUsd"),
            "qualifyingLaneIds": _list(combined.get("qualifyingLaneIds")),
        },
        "rsiDemotionReview": rsi_review,
        "forexMt5": forex,
        "btcCryptoCfd": {
            "status": btc.get("status") or "BTC_TPSL_REPORT_MISSING",
            "finalAdvisoryPickPolicy": final_policy,
            "finalAdvisoryPickReasonZh": btc_default_reason_zh,
            "defaultStable": btc_default_candidate,
            "optimizerStableLegacy": _btc_candidate(stable, role="stableDefault"),
            "targetSeeking": _btc_candidate(target, role="targetSeeking"),
            "aggressiveHighPnl": _btc_candidate(aggressive, role="aggressiveHighPnl"),
            "selectedDefault": btc_default_candidate,
            "targetTradeoff": _dict(btc.get("targetTradeoff")),
            "windowHealth": _dict(btc.get("windowHealth")),
            "middleWindowLeaders": _dict(btc.get("middleWindowLeaders")),
            "focusedRetestQueue": btc_focused_retest_queue,
            "nextActionZh": btc_lane_next_action_zh,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "releaseBlockers": blockers,
        "releaseEvidence": {
            "signoffEvidenceStatus": matrix.get("status"),
            "completeSignoffCount": matrix.get("completeSignoffCount"),
            "releaseTokenCount": matrix.get("releaseTokenCount"),
            "canReleaseExecutionNow": False,
            "orderSendAllowed": False,
        },
        "sourceArtifacts": {
            "aceStrategyScout": str(agent_dir / "QuantGod_AceStrategyScout.json"),
            "championRetest": str(agent_dir / "QuantGod_ChampionRetestReport.json"),
            "btcStrategyScan": str(agent_dir / "QuantGod_BtcStrategyScanReport.json"),
            "championTesterRunGate": str(agent_dir / "QuantGod_ChampionTesterRunGate.json"),
            "liveRuntimePreflightProbe": str(agent_dir / "QuantGod_LiveRuntimePreflightProbe.json"),
            "liveEvidenceIntake": str(agent_dir / "QuantGod_LiveEvidenceIntake.json"),
            "tpSlOptimizer": str(agent_dir / "QuantGod_TpSlOptimizerReport.json"),
            "profitTargetTracker": str(runtime / "profit_target" / "QuantGod_ProfitTargetTracker.json"),
            "simTargetExecutionReviewSummary": str(agent_dir / "QuantGod_SimTargetExecutionReviewSummary.json"),
            "releaseTokenSignoffEvidenceMatrix": str(agent_dir / "QuantGod_ReleaseTokenSignoffEvidenceMatrix.json"),
        },
        "sourceArtifactSummaries": source_artifact_summaries,
        "sourceArtifactSummaryZh": _source_artifact_summary_zh(source_artifact_summaries),
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, report)
    return report


def read_ace_execution_candidate_pack(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    payload = _read_json(runtime / REPORT_PATH)
    if payload and not _saved_pack_stale(runtime, payload):
        return payload
    return build_ace_execution_candidate_pack(runtime, write=bool(payload))
