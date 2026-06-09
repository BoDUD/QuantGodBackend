"""Read-only ace upgrade action plan.

This artifact turns the ace selection, champion promotion gate, tester gate,
and sim-to-live summary into an operator/automation action queue. It never
writes tester locks, account context, live presets, order requests, or receipts.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "quantgod.ace_upgrade_action_plan.v1"
REPORT_PATH = Path("agent") / "QuantGod_AceUpgradeActionPlan.json"


SAFETY = {
    "readOnly": True,
    "advisoryOnly": True,
    "testerOnly": True,
    "writesTesterLock": False,
    "launchesTerminal": False,
    "copiesAccountContext": False,
    "storesSecrets": False,
    "orderSendAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "writesMt5OrderReceipt": False,
    "writesLivePreset": False,
    "livePresetMutationAllowed": False,
    "brokerCallsMade": False,
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
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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
    if kind == "aceExecutionCandidatePack":
        board = _dict(payload.get("executionReadinessBoard"))
        summary.update({
            "closestResearchLaneNow": board.get("closestResearchLaneNow"),
            "selectedLaneForSeparateReleaseReview": board.get("selectedLaneForSeparateReleaseReview"),
            "primaryClosureQueueCount": len(_list(board.get("primaryClosureQueue"))),
        })
    elif kind == "championTesterRunGate":
        gate = _dict(payload.get("gate"))
        live_session = _dict(gate.get("liveSession"))
        next_window = _resolved_next_tester_window(_dict(payload.get("nextTesterWindow")))
        summary.update({
            "blockerCount": len(_unique(_list(gate.get("blockers")))),
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
    return summary


def _source_artifact_summaries(
    *,
    runtime: Path,
    agent: Path,
    pack: dict[str, Any],
    summary: dict[str, Any],
    promotion_gate: dict[str, Any],
    run_gate: dict[str, Any],
    forward_request: dict[str, Any],
    lock_draft: dict[str, Any],
    preflight: dict[str, Any],
    live_evidence_intake: dict[str, Any],
    account_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "aceExecutionCandidatePack": _artifact_summary(agent / "QuantGod_AceExecutionCandidatePack.json", pack, kind="aceExecutionCandidatePack"),
        "simTargetExecutionReviewSummary": _artifact_summary(agent / "QuantGod_SimTargetExecutionReviewSummary.json", summary, kind="generic"),
        "championPromotionGate": _artifact_summary(agent / "QuantGod_ChampionPromotionGate.json", promotion_gate, kind="generic"),
        "championTesterRunGate": _artifact_summary(agent / "QuantGod_ChampionTesterRunGate.json", run_gate, kind="championTesterRunGate"),
        "championTesterForwardRequest": _artifact_summary(agent / "QuantGod_ChampionTesterForwardRequest.json", forward_request, kind="generic"),
        "championTesterLockDraft": _artifact_summary(agent / "QuantGod_ChampionTesterLockDraft.json", lock_draft, kind="generic"),
        "liveRuntimePreflightProbe": _artifact_summary(agent / "QuantGod_LiveRuntimePreflightProbe.json", preflight, kind="liveRuntimePreflightProbe"),
        "liveEvidenceIntake": _artifact_summary(agent / "QuantGod_LiveEvidenceIntake.json", live_evidence_intake, kind="liveEvidenceIntake"),
        "isolatedTesterAccountContextStatus": _artifact_summary(runtime / "QuantGod_IsolatedTesterAccountContextStatus.json", account_context, kind="generic"),
    }


def _source_artifact_summary_zh(source_summaries: dict[str, Any]) -> str:
    pack = _dict(source_summaries.get("aceExecutionCandidatePack"))
    run_gate = _dict(source_summaries.get("championTesterRunGate"))
    preflight = _dict(source_summaries.get("liveRuntimePreflightProbe"))
    intake = _dict(source_summaries.get("liveEvidenceIntake"))
    return (
        f"pack@{pack.get('generatedAtIso') or 'unknown'} lane={pack.get('closestResearchLaneNow') or 'unknown'}；"
        f"runGate@{run_gate.get('generatedAtIso') or 'unknown'} "
        f"windowStart={run_gate.get('nextTesterWindowStartJstIso') or 'unknown'} "
        f"minutesUntilStart={run_gate.get('nextTesterWindowMinutesUntilStart')}；"
        f"preflight@{preflight.get('generatedAtIso') or 'unknown'} "
        f"dashboardFresh={preflight.get('dashboardFresh')} ageSeconds={preflight.get('dashboardAgeSeconds')}；"
        f"evidenceIntake@{intake.get('generatedAtIso') or 'unknown'} "
        f"presentInputs={intake.get('presentInputCount')} "
        f"tradeBlocker={intake.get('tradePermissionBlocker') or 'unknown'}。"
    )


def _unique(values: list[Any]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.append(value)
    return seen


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


def _find_btc_cluster(strategy_shortlist: dict[str, Any], strategy_id: Any) -> dict[str, Any]:
    strategy_id_str = str(strategy_id or "")
    if not strategy_id_str:
        return {}
    rows = [_dict(row) for row in _list(_dict(strategy_shortlist.get("btcParameterClusters")).get("rows"))]
    for item in rows:
        canonical_id = str(item.get("canonicalStrategyId") or "")
        if strategy_id_str == canonical_id:
            return item
    for item in rows:
        canonical_id = str(item.get("canonicalStrategyId") or "")
        member_ids = [value for value in _list(item.get("memberStrategyIds")) if isinstance(value, str)]
        alias_ids = [value for value in _list(item.get("aliasStrategyIds")) if isinstance(value, str)]
        if strategy_id_str == canonical_id or strategy_id_str in member_ids or strategy_id_str in alias_ids:
            return item
    return {}


def _cluster_aliases(cluster: dict[str, Any], canonical_strategy_id: Any) -> list[str]:
    canonical = str(canonical_strategy_id or "")
    aliases: list[str] = []
    for value in _list(cluster.get("aliasStrategyIds")):
        if isinstance(value, str) and value and value != canonical and value not in aliases:
            aliases.append(value)
    return aliases


def _cluster_summary_zh(cluster: dict[str, Any], canonical_strategy_id: Any) -> str | None:
    canonical = str(canonical_strategy_id or "")
    if not canonical:
        return None
    aliases = _cluster_aliases(cluster, canonical)
    if aliases:
        return f"参数簇主 ID={canonical}；同参别名: {', '.join(aliases)}"
    return f"参数簇主 ID={canonical}"


def _append_sentence_zh(prefix: str, text: Any) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    suffix = "" if value.endswith(("。", "！", "？")) else "。"
    return f" {prefix}{value}{suffix}"


def _btc_near_live_converged_cluster_display(
    btc_duel_board: dict[str, Any],
    canonical_strategy_id: Any,
    *,
    role: str = "focus",
) -> dict[str, Any]:
    canonical = str(canonical_strategy_id or "")
    if not canonical:
        return {}
    rows = [_dict(item) for item in _list(btc_duel_board.get("nearLiveConvergedVariantRows")) if _dict(item)]
    if not rows:
        rows = [_dict(item) for item in _list(btc_duel_board.get("nearLiveMiddleWindowVariantRows")) if _dict(item)]
    variant_ids = [
        str(item.get("strategyId") or "")
        for item in rows
        if isinstance(item.get("strategyId"), str) and item.get("strategyId")
    ]
    if not variant_ids:
        variant_ids = [
            item
            for item in _list(btc_duel_board.get("nearLiveConvergedVariantStrategyIds"))
            if isinstance(item, str) and item
        ]
    if not variant_ids:
        variant_ids = [
            item
            for item in _list(btc_duel_board.get("nearLiveMiddleWindowVariantStrategyIds"))
            if isinstance(item, str) and item
        ]
    if canonical not in variant_ids:
        return {}
    summary_zh = btc_duel_board.get("nearLiveConvergedVariantSummaryZh")
    if not isinstance(summary_zh, str) or not summary_zh.strip():
        summary_zh = btc_duel_board.get("nearLiveMiddleWindowVariantSummaryZh")
    if isinstance(summary_zh, str):
        summary_zh = summary_zh.strip()
    aliases = [item for item in variant_ids if item != canonical]
    if role == "challenger" and summary_zh:
        summary_zh = f"当前 next distinct contender={canonical}；{summary_zh}"
    elif role == "yield" and summary_zh:
        summary_zh = f"当前高收益 leader 已收敛在同一 near-live 参数簇；{summary_zh}"
    return {
        "canonicalStrategyId": canonical,
        "aliasStrategyIds": aliases,
        "summaryZh": summary_zh,
        "variantStrategyIds": variant_ids,
    }


def _lane_label_zh(lane: Any) -> str:
    lane_str = str(lane or "")
    if lane_str == "btcCryptoCfd":
        return "BTC"
    if lane_str == "forexMt5":
        return "MT5"
    if lane_str == "shared_release_lane":
        return "shared release lane"
    return lane_str or "当前 lane"


def _seed_short_label(seed_id: Any) -> str | None:
    seed = str(seed_id or "").strip()
    if not seed:
        return None
    match = re.search(r"(G\d{4})", seed, flags=re.IGNORECASE)
    return match.group(1).upper() if match else seed


def _derive_seed_id_from_candidate_id(candidate_id: Any, *, reference_seed_id: Any) -> str | None:
    candidate = str(candidate_id or "").strip()
    if not candidate:
        return None
    match = re.search(r"\b(g\d{4})\b", candidate, flags=re.IGNORECASE)
    if not match:
        return None
    generation_token = match.group(1).upper()
    reference_seed = str(reference_seed_id or "").strip()
    reference_match = re.match(r"^(.*-)(G\d{4})(-.+)$", reference_seed, flags=re.IGNORECASE)
    if reference_match:
        return f"{reference_match.group(1)}{generation_token}{reference_match.group(3)}"
    return f"GA-USDJPY-{generation_token}-C0004"


def _select_btc_scan_comparison_cluster(
    strategy_shortlist: dict[str, Any],
    *,
    excluded_canonical_ids: list[str],
) -> dict[str, Any]:
    clusters = [
        _dict(row)
        for row in _list(_dict(strategy_shortlist.get("btcParameterClusters")).get("rows"))
    ]
    excluded = {item for item in excluded_canonical_ids if isinstance(item, str) and item}
    candidates = [
        row for row in clusters
        if str(row.get("canonicalStrategyId") or "") not in excluded
    ]
    if not candidates:
        return {}
    return min(
        candidates,
        key=lambda row: (
            _num(row.get("recommendedResearchPriority"), default=999),
            -_num(row.get("bestValidWindowCount"), default=0),
            -_num(row.get("bestPnlUsd"), default=0),
            -_num(row.get("bestSharpe"), default=0),
        ),
    )


def _btc_lane_selection_from_shortlist_item(item: dict[str, Any]) -> dict[str, Any]:
    item = _dict(item)
    metrics = _dict(item.get("metrics"))
    params = _dict(item.get("params"))
    return {
        "lane": "btcCryptoCfd",
        "role": item.get("role") or "selectedDefault",
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
        "validWindowCount": item.get("validWindowCount") or metrics.get("validWindowCount"),
        "windowCount": item.get("windowCount") or metrics.get("windowCount"),
        "blockers": _list(item.get("blockers")),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _derive_btc_lane_selection(
    *,
    pack: dict[str, Any],
    strategy_shortlist: dict[str, Any],
    execution_readiness_board: dict[str, Any],
) -> dict[str, Any]:
    btc_pack = _dict(pack.get("btcCryptoCfd"))
    direct_candidate = _dict(
        btc_pack.get("selectedDefault")
        or btc_pack.get("defaultStable")
    )
    if direct_candidate.get("strategyId"):
        return direct_candidate

    btc_top = [_dict(item) for item in _list(strategy_shortlist.get("btcTopStrategies"))]
    if not btc_top:
        return {}

    lineup = _dict(strategy_shortlist.get("btcLineupBoard")) or _dict(strategy_shortlist.get("btcDuelBoard"))
    btc_snapshot = next(
        (
            _dict(item)
            for item in _list(execution_readiness_board.get("laneSnapshots"))
            if _dict(item).get("lane") == "btcCryptoCfd"
        ),
        {},
    )
    preferred_ids = [
        btc_snapshot.get("focusStrategyId"),
        lineup.get("stableAnchorStrategyId"),
        lineup.get("defaultStableStrategyId"),
    ]
    preferred_ids.extend(
        _dict(row).get("strategyId")
        for row in btc_top
        if _dict(row).get("role") in {"stableAnchor", "selectedDefault", "mostStable", "stabilityAlternative"}
    )
    for strategy_id in preferred_ids:
        strategy_id = str(strategy_id or "")
        if not strategy_id:
            continue
        matched = next(
            (row for row in btc_top if str(_dict(row).get("strategyId") or "") == strategy_id),
            {},
        )
        if matched:
            return _btc_lane_selection_from_shortlist_item(matched)

    return _btc_lane_selection_from_shortlist_item(btc_top[0])


def _command_hint(command_id: str, command: str, when_zh: str | None = None) -> dict[str, Any]:
    return {
        "id": command_id,
        "command": command,
        "whenZh": when_zh,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "writesLivePreset": False,
    }


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


def _saved_plan_stale(runtime_dir: Path, payload: dict[str, Any]) -> bool:
    embedded = _dict(payload.get("sourceArtifactSummaries"))
    if not embedded:
        return False
    runtime = Path(runtime_dir)
    agent = runtime / "agent"
    current_sources = {
        "aceExecutionCandidatePack": _read_json(agent / "QuantGod_AceExecutionCandidatePack.json"),
        "championTesterRunGate": _read_json(agent / "QuantGod_ChampionTesterRunGate.json"),
        "liveRuntimePreflightProbe": _read_json(agent / "QuantGod_LiveRuntimePreflightProbe.json"),
        "liveEvidenceIntake": _read_json(agent / "QuantGod_LiveEvidenceIntake.json"),
    }
    for key, current_payload in current_sources.items():
        source_path = {
            "aceExecutionCandidatePack": agent / "QuantGod_AceExecutionCandidatePack.json",
            "championTesterRunGate": agent / "QuantGod_ChampionTesterRunGate.json",
            "liveRuntimePreflightProbe": agent / "QuantGod_LiveRuntimePreflightProbe.json",
            "liveEvidenceIntake": agent / "QuantGod_LiveEvidenceIntake.json",
        }[key]
        embedded_generated = _parse_iso(_dict(embedded.get(key)).get("generatedAtIso"))
        current_generated = _parse_iso(_artifact_generated_at_from_path(source_path, current_payload))
        if embedded_generated and current_generated and current_generated > embedded_generated:
            return True
    return False


def _resolve_candidate_pack(runtime: Path, *, write: bool) -> dict[str, Any]:
    # Reuse the candidate-pack self-healing path so the action plan evaluates
    # against the freshest shortlist evidence available, but keep an existing
    # saved pack as fallback when test fixtures intentionally omit the upstream
    # candidate-pack source artifacts.
    try:
        from tools.ace_execution_candidate_pack import read_ace_execution_candidate_pack
    except ModuleNotFoundError:  # pragma: no cover
        from ace_execution_candidate_pack import read_ace_execution_candidate_pack

    saved_pack = _read_json(runtime / REPORT_PATH.parent / "QuantGod_AceExecutionCandidatePack.json")
    resolved_pack = read_ace_execution_candidate_pack(runtime)
    resolved_selected = _dict(_dict(resolved_pack.get("liveUpgradeSelection")).get("selectedStrategy"))
    saved_selected = _dict(_dict(saved_pack.get("liveUpgradeSelection")).get("selectedStrategy"))
    if resolved_selected.get("seedId") or resolved_selected.get("strategyId"):
        return resolved_pack
    if saved_selected.get("seedId") or saved_selected.get("strategyId"):
        return saved_pack
    return resolved_pack


def _pack_source_freshness_diagnostics(
    *,
    pack: dict[str, Any],
    scout: dict[str, Any],
    scan: dict[str, Any],
    tpsl: dict[str, Any],
    run_gate: dict[str, Any],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    embedded = _dict(pack.get("sourceArtifactSummaries"))
    comparisons: list[dict[str, Any]] = []
    stale_count = 0
    checked_count = 0
    for key, current_payload, label_zh in (
        ("aceStrategyScout", scout, "ACE strategy scout"),
        ("btcStrategyScan", scan, "BTC focused scan"),
        ("tpSlOptimizer", tpsl, "BTC/MT5 TP-SL optimizer"),
        ("championTesterRunGate", run_gate, "MT5 champion tester gate"),
        ("liveRuntimePreflightProbe", preflight, "live runtime preflight"),
    ):
        embedded_row = _dict(embedded.get(key))
        embedded_generated = embedded_row.get("generatedAtIso")
        current_generated = _artifact_generated_at(current_payload)
        embedded_dt = _parse_iso(embedded_generated)
        current_dt = _parse_iso(current_generated)
        is_stale = bool(
            embedded_dt
            and current_dt
            and current_dt > embedded_dt
        )
        if embedded_generated or current_generated:
            checked_count += 1
        if is_stale:
            stale_count += 1
        comparisons.append({
            "id": key,
            "labelZh": label_zh,
            "embeddedGeneratedAtIso": embedded_generated,
            "currentGeneratedAtIso": current_generated,
            "packSnapshotStale": is_stale,
            "status": (
                "PACK_SOURCE_STALE"
                if is_stale
                else ("PACK_SOURCE_ALIGNED" if embedded_generated and current_generated else "PACK_SOURCE_TIME_UNKNOWN")
            ),
        })
    return {
        "status": "PACK_SOURCE_FRESHNESS_READY",
        "checkedCount": checked_count,
        "staleCount": stale_count,
        "packSnapshotUpToDate": stale_count == 0,
        "comparisons": comparisons,
        "summaryZh": (
            "候选包已对齐当前 scout/scan/tpsl/preflight/runGate。"
            if stale_count == 0
            else f"候选包有 {stale_count} 个上游源已更新，需先重建 pack 再看升级计划。"
        ),
    }


def _mt5_instance_label(path_text: Any) -> str:
    text = str(path_text or "")
    if text == "dashboard":
        return "embedded_dashboard_probe"
    if "net.metaquotes.wine.metatrader5-live16" in text:
        return "live16"
    if "net.metaquotes.wine.metatrader5" in text:
        return "main"
    return "unknown"


def _preflight_blocker_details(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for row in _list(preflight.get("blockers")):
        item = _dict(row)
        code = item.get("code")
        if isinstance(code, str) and code:
            details.append({
                "code": code,
                "reasonZh": item.get("reasonZh"),
                "value": item.get("value"),
            })
    return details


def _btc_runtime_evidence_snapshot(
    *,
    strategy_shortlist: dict[str, Any],
    preflight: dict[str, Any],
    live_evidence_intake: dict[str, Any],
) -> dict[str, Any]:
    btc_readiness = _dict(strategy_shortlist.get("btcLaneReadiness"))
    dashboard = _dict(preflight.get("dashboardSnapshot"))
    permission_layers = _dict(dashboard.get("permissionLayers"))
    execution_gate_diagnostics = _dict(dashboard.get("executionGateDiagnostics"))
    trade_allowed_diagnostics = _dict(execution_gate_diagnostics.get("tradeAllowed"))
    lane_checks = [
        _dict(row)
        for row in _list(preflight.get("laneRuntimeChecks"))
        if _dict(row).get("lane") == "HFM_CRYPTO_CFD"
    ]
    lane_check = lane_checks[0] if lane_checks else {}
    probe_results = _dict(preflight.get("probeResults"))
    file_summary = _dict(live_evidence_intake.get("fileInputSummary"))
    dashboard_path = dashboard.get("path")
    runtime_probe_source = lane_check.get("runtimeProbeSource")
    dashboard_instance = _mt5_instance_label(dashboard_path)
    runtime_probe_instance = _mt5_instance_label(runtime_probe_source)
    if runtime_probe_source == "dashboard":
        runtime_probe_instance = dashboard_instance
    permission_chain_healthy = _permission_chain_healthy(permission_layers)
    trade_permission_blocker = permission_layers.get("tradePermissionBlocker")
    raw_dashboard_selected = bool(probe_results.get("symbolSelectedInDashboardOk"))
    runtime_probe_symbol_ok = bool(probe_results.get("symbolRuntimeProbeOk"))
    runtime_probe_fresh = lane_check.get("runtimeProbeFresh")
    symbol_present_in_runtime_probe = lane_check.get("symbolPresentInRuntimeProbe")
    symbol_selection_effective_ok = _effective_symbol_selection_ok(
        raw_dashboard_selected=raw_dashboard_selected,
        runtime_probe_symbol_ok=runtime_probe_symbol_ok,
        symbol_present_in_runtime_probe=symbol_present_in_runtime_probe,
        runtime_probe_fresh=runtime_probe_fresh,
    )
    source_alignment_status = (
        "MISMATCHED_MT5_INSTANCE"
        if runtime_probe_source and dashboard_path and dashboard_instance != runtime_probe_instance
        else "ALIGNED_OR_UNKNOWN"
    )
    return {
        "targetSymbol": lane_check.get("brokerSymbol") or btc_readiness.get("focusSymbol") or "#BTCUSD",
        "dashboardPath": dashboard_path,
        "dashboardFresh": bool(dashboard.get("fresh")),
        "dashboardAgeSeconds": dashboard.get("ageSeconds"),
        "dashboardMaxAgeSeconds": dashboard.get("maxAgeSeconds"),
        "dashboardSymbolCount": dashboard.get("symbolCount"),
        "dashboardSymbolNames": _list(dashboard.get("symbolNames")),
        "symbolSelectedInDashboardOk": raw_dashboard_selected,
        "symbolSelectionEffectiveOk": symbol_selection_effective_ok,
        "symbolPresentInRuntimeProbe": symbol_present_in_runtime_probe,
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
        "runtimeProbeSource": runtime_probe_source,
        "runtimeProbeFresh": runtime_probe_fresh,
        "runtimeProbeAgeSeconds": lane_check.get("runtimeProbeAgeSeconds"),
        "symbolPresentInSnapshot": lane_check.get("symbolPresentInSnapshot"),
        "symbolPresentInNames": lane_check.get("symbolPresentInNames"),
        "spreadFieldPresent": lane_check.get("spreadFieldPresent"),
        "dashboardInstance": dashboard_instance,
        "runtimeProbeInstance": runtime_probe_instance,
        "sourceAlignmentStatus": source_alignment_status,
        "sourceAlignmentZh": (
            f"dashboard 来自 {dashboard_instance}，runtime probe 来自 {runtime_probe_instance}；当前是跨 MT5 实例取证。"
            if source_alignment_status == "MISMATCHED_MT5_INSTANCE"
            else "dashboard 和 runtime probe 来源一致，或暂时无法判断实例是否一致。"
        ),
        "symbolSelectionEvidenceZh": (
            "dashboard symbol 列未显示目标，但 fresh runtime probe 已证明该 symbol 已被选中并输出只读 tick。"
            if symbol_selection_effective_ok and not raw_dashboard_selected
            else (
                "dashboard symbol 列已直接显示目标 symbol。"
                if raw_dashboard_selected
                else "当前仍缺目标 symbol 的 dashboard/watchlist 选中证据。"
            )
        ),
        "readOnlyEvidenceInputCount": file_summary.get("presentInputCount"),
        "missingChecklistCount": file_summary.get("missingChecklistCount"),
    }


def _btc_refresh_outcome(
    *,
    preflight: dict[str, Any],
    live_evidence_intake: dict[str, Any],
    runtime_snapshot: dict[str, Any],
) -> dict[str, Any]:
    intake_time = _parse_iso(live_evidence_intake.get("generatedAtIso"))
    preflight_time = _parse_iso(preflight.get("generatedAtIso"))
    seconds_apart: float | None = None
    if intake_time and preflight_time:
        seconds_apart = abs((intake_time - preflight_time).total_seconds())
    refresh_attempted = seconds_apart is not None and seconds_apart <= 120
    dashboard_fresh = bool(runtime_snapshot.get("dashboardFresh"))
    live_tick_ok = bool(runtime_snapshot.get("sidecarLiveTickOk"))
    spread_ok = bool(runtime_snapshot.get("spreadProbeOk"))
    symbol_selected = bool(runtime_snapshot.get("symbolSelectionEffectiveOk"))
    external_runtime_needed = bool(refresh_attempted and (not dashboard_fresh or not symbol_selected or not spread_ok))
    if refresh_attempted and live_tick_ok and spread_ok and not dashboard_fresh:
        status = "REFRESH_ATTEMPTED_EXECUTION_MODE_OR_FRESHNESS_BLOCKED"
        outcome_zh = (
            "evidence-intake 已重刷，live16 runtime probe 已补出 #BTCUSD tick/spread；"
            "当前主要卡在 dashboard freshness 和 execution mode 字段，而不是 crypto symbol 取证能力。"
        )
    elif external_runtime_needed:
        status = "REFRESH_ATTEMPTED_RUNTIME_STILL_STALE"
        outcome_zh = (
            "evidence-intake 已重刷，但新的 MT5 runtime 快照仍未补出 #BTCUSD dashboard/tick/spread；"
            "当前需要外部 MT5 runtime/watchlist 继续产出新快照。"
        )
    elif refresh_attempted:
        status = "REFRESH_ATTEMPTED"
        outcome_zh = "evidence-intake 已重刷；当前等待下一步研究/评审动作。"
    else:
        status = "REFRESH_STATE_UNKNOWN"
        outcome_zh = "尚未确认最近一次 evidence-intake 是否已和当前 runtime preflight 同步。"
    return {
        "status": status,
        "attemptedAtIso": live_evidence_intake.get("generatedAtIso"),
        "preflightGeneratedAtIso": preflight.get("generatedAtIso"),
        "artifactAgeGapSeconds": seconds_apart,
        "externalRuntimeInterventionRequired": external_runtime_needed,
        "sourceAlignmentStatus": runtime_snapshot.get("sourceAlignmentStatus"),
        "sourceAlignmentZh": runtime_snapshot.get("sourceAlignmentZh"),
        "outcomeZh": outcome_zh,
    }


def _btc_runtime_preflight_focus(runtime_snapshot: dict[str, Any], blocker_codes: list[str]) -> tuple[str, str]:
    blocker_set = {code for code in blocker_codes if isinstance(code, str)}
    focus_symbol = runtime_snapshot.get("targetSymbol") or "#BTCUSD"
    dashboard_instance = runtime_snapshot.get("dashboardInstance")
    dashboard_label = "live16 dashboard" if dashboard_instance == "live16" else "MT5 dashboard"
    if blocker_set & BTC_RUNTIME_DATA_PLANE_BLOCKERS:
        return (
            f"先补 BTC runtime/data-plane 证据，确认 {focus_symbol} 已在 dashboard/watchlist 输出实时 tick/spread。",
            "BTC 是当前唯一还能继续推进研究的 lane，但缺实时 dashboard/tick/spread 证据。",
        )
    if blocker_set & BTC_EXECUTION_MODE_BLOCKERS or "MT5_DASHBOARD_SNAPSHOT_STALE" in blocker_set:
        permission_blocker = runtime_snapshot.get("tradePermissionBlocker")
        permission_chain_healthy = runtime_snapshot.get("permissionChainHealthy")
        return (
            f"先刷新 {dashboard_label}，并确认 livePilotMode/readOnlyMode/executionEnabled/tradeAllowed 进入可评审状态。",
            (
                "BTC 的 runtime probe 已经有 #BTCUSD 实时 tick/spread；当前主要卡在 dashboard freshness 和执行模式字段，"
                f"permission chain healthy={permission_chain_healthy}，直接交易阻塞为 {permission_blocker or 'UNKNOWN'}，而不是 symbol 取证。"
            ),
        )
    return (
        "继续刷新 BTC runtime 证据并核对 execution lane 审查前置条件。",
        "BTC 仍是当前最接近实盘评审的研究线，先把 runtime 证据和执行闸门核对清楚。",
    )


def _btc_runtime_evidence_summary_zh(runtime_snapshot: dict[str, Any]) -> str:
    target_symbol = runtime_snapshot.get("targetSymbol") or "#BTCUSD"
    symbol_names = _list(runtime_snapshot.get("dashboardSymbolNames"))
    symbol_label = ",".join(str(item) for item in symbol_names[:3]) if symbol_names else "无"
    permission_blocker = runtime_snapshot.get("tradePermissionBlocker")
    permission_chain_healthy = runtime_snapshot.get("permissionChainHealthy")
    return (
        f"dashboardFresh={runtime_snapshot.get('dashboardFresh')} ageSeconds={runtime_snapshot.get('dashboardAgeSeconds')}；"
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
        f"runtimeProbeAgeSeconds={runtime_snapshot.get('runtimeProbeAgeSeconds')}。"
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
        "dashboardInstance": runtime_snapshot.get("dashboardInstance"),
        "targetSymbol": runtime_snapshot.get("targetSymbol"),
        "summaryZh": (
            f"需外部刷新/新快照={','.join(external_refresh_blockers) if external_refresh_blockers else '无'}；"
            f"需补 data-plane={','.join(data_plane_blockers) if data_plane_blockers else '无'}；"
            f"需切换 execution mode={','.join(execution_mode_blockers) if execution_mode_blockers else '无'}；"
            f"permissionChainHealthy={permission_chain_healthy}；"
            f"directExecutionBlocker={direct_execution_blocker or '无'}。"
        ),
    }


def _process_evidence() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["ps", "ax"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "PROCESS_SCAN_UNAVAILABLE",
            "scanSupported": False,
            "error": str(exc),
            "launchesTerminal": False,
            "brokerCallsMade": False,
        }
    text = proc.stdout or ""
    lowered = text.lower()
    main_terminal_running = "terminal64" in lowered and "hfm_mt5_tester_isolated" not in lowered
    isolated_tester_terminal_running = "terminal64" in lowered and "hfm_mt5_tester_isolated" in lowered
    dashboard_server_running = "dashboard/dashboard_server.js" in lowered
    autopilot_running = "run_daily_autopilot_v2.py" in lowered
    feedback_running = "run_live_execution_feedback.py" in lowered
    blockers: list[str] = []
    if not main_terminal_running:
        blockers.append("mt5_terminal_process_missing")
    return {
        "status": "PROCESS_SCAN_READY",
        "scanSupported": True,
        "mainMt5TerminalRunning": main_terminal_running,
        "isolatedTesterTerminalRunning": isolated_tester_terminal_running,
        "dashboardServerRunning": dashboard_server_running,
        "dailyAutopilotRunning": autopilot_running,
        "liveExecutionFeedbackRunning": feedback_running,
        "blockers": blockers,
        "nextActionZh": (
            "未发现主 MT5 terminal64 进程；live dashboard 可能不会继续刷新。"
            if "mt5_terminal_process_missing" in blockers
            else "主 MT5 terminal64 进程存在，继续用 dashboard freshness 判断 live session。"
        ),
        "launchesTerminal": False,
        "brokerCallsMade": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _mt5_preferred_terminal_path(run_gate: dict[str, Any]) -> str:
    return str(_dict(run_gate.get("supportingProcessEvidence")).get("preferredTerminalPath") or "")


def _mt5_terminal_restore_action_zh(run_gate: dict[str, Any]) -> str:
    preferred_terminal_path = _mt5_preferred_terminal_path(run_gate)
    if preferred_terminal_path:
        return (
            f"未发现主 MT5 terminal64 进程；先恢复 {preferred_terminal_path} 并恢复 "
            "live dashboard 刷新，否则不能确认 live session freshness。"
        )
    return "未发现主 MT5 terminal64 进程；先恢复主 terminal 并恢复 live dashboard 刷新，否则不能确认 live session freshness。"


def _mt5_terminal_restore_required_action_zh(run_gate: dict[str, Any]) -> str:
    preferred_terminal_path = _mt5_preferred_terminal_path(run_gate)
    if preferred_terminal_path:
        return (
            f"先恢复主 MT5 terminal64 进程（优先: {preferred_terminal_path}）并恢复 "
            "dashboard freshness，再重建 tester gate。"
        )
    return "先恢复主 MT5 terminal64 进程并恢复 dashboard freshness，再重建 tester gate。"


def _hfm_review_artifacts(runtime_dir: Path) -> dict[str, dict[str, Any]]:
    hfm_root = Path(runtime_dir) / "hfm_crypto"
    return {
        "postUpgradeController": _read_json(hfm_root / "QuantGod_HFMCryptoPostUpgradeController.json"),
        "mt5PostUpgradeVerify": _read_json(hfm_root / "QuantGod_HFMCryptoMt5PostUpgradeVerify.json"),
        "mt5UpgradeBundle": _read_json(hfm_root / "QuantGod_HFMCryptoMt5ExporterUpgradeBundle.json"),
    }


def _annotate_btc_preflight_command(
    command: dict[str, Any],
    *,
    hfm_review: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    annotated = dict(command)
    command_id = str(command.get("id") or "")
    controller = _dict(hfm_review.get("postUpgradeController"))
    verify = _dict(hfm_review.get("mt5PostUpgradeVerify"))
    bundle = _dict(hfm_review.get("mt5UpgradeBundle"))
    if command_id == "refresh_evidence_intake":
        annotated["conditionStatus"] = "REQUIRED_NOW"
        annotated["neededNow"] = True
        annotated["conditionReasonZh"] = "当前最直接补 dashboard / #BTCUSD tick-spread 证据的刷新命令。"
    elif command_id == "run_hfm_post_upgrade_controller":
        annotated["conditionStatus"] = "CONDITIONAL_REFRESH_ONLY"
        annotated["neededNow"] = False
        annotated["conditionReasonZh"] = (
            "HFM specs、contract-spec 和 execution-spec 已就绪；除非人工升级/重载 EA 后需要整链重刷，否则现在不是主 blocker。"
            if controller.get("readyForHfmContractSpecReview") and controller.get("executionSpecReviewReady")
            else "当 HFM 审查链不完整时，用这一条重刷整套只读证据。"
        )
        annotated["sourceArtifactStatus"] = controller.get("status")
    elif command_id == "verify_mt5_ea_post_upgrade":
        annotated["conditionStatus"] = "POST_MANUAL_UPGRADE_ONLY"
        annotated["neededNow"] = False
        annotated["conditionReasonZh"] = (
            "当前升级后验证已通过；只有在人工复制/编译/重载 EA 后才需要再跑。"
            if verify.get("status") == "HFM_CRYPTO_MT5_POST_UPGRADE_VERIFIED"
            else "人工升级或编译后，用这一条确认 specs 是否重新可用。"
        )
        annotated["sourceArtifactStatus"] = verify.get("status")
    elif command_id == "build_mt5_ea_upgrade_bundle":
        annotated["conditionStatus"] = "SKIP_UNLESS_EXPORTER_MISSING"
        annotated["neededNow"] = False
        annotated["conditionReasonZh"] = (
            "当前 MT5 已能提供 HFM crypto specs，通常不需要再生成升级包。"
            if bundle.get("status") == "MT5_EXPORTER_ALREADY_AVAILABLE"
            else "只有安装目录 EA 确认偏旧且确实缺 exporter 时，才需要生成手工升级包。"
        )
        annotated["sourceArtifactStatus"] = bundle.get("status")
    else:
        annotated["conditionStatus"] = "OPTIONAL"
        annotated["neededNow"] = False
        annotated["conditionReasonZh"] = "当前不是首要 blocker，对应命令仅在特定条件下使用。"
    annotated["orderSendAllowed"] = False
    annotated["mt5OrderSendAllowed"] = False
    return annotated


def _action(
    action_id: str,
    status: str,
    action_zh: str,
    *,
    blockers: list[str] | None = None,
    lane: str | None = None,
    stage: str | None = None,
    commands: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "status": status,
        "lane": lane,
        "stage": stage,
        "actionZh": action_zh,
        "blockers": blockers or [],
        "commands": commands or [],
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "writesLivePreset": False,
        "livePresetMutationAllowed": False,
    }


def _review_command_map(live_evidence_intake: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in _list(live_evidence_intake.get("readOnlyReviewCommands")):
        item = _dict(row)
        command_id = item.get("id")
        command = item.get("command")
        if isinstance(command_id, str) and command_id and isinstance(command, str) and command:
            mapping[command_id] = _command_hint(command_id, command, item.get("whenZh"))
    return mapping


def _champion_forward_command_hints(forward_request: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for row in _list(forward_request.get("selectedTasks"))[:limit]:
        task = _dict(row)
        candidate_id = str(task.get("candidateId") or f"candidate_{len(hints)+1}")
        config_command = task.get("configOnlyCommand")
        if isinstance(config_command, str) and config_command:
            hints.append(_command_hint(
                f"{candidate_id}_config_only",
                config_command,
                f"{task.get('label') or candidate_id} 参数物化，只生成 tester 配置。",
            ))
        guarded_command = task.get("guardedRunTerminalCommand")
        if isinstance(guarded_command, str) and guarded_command:
            hints.append(_command_hint(
                f"{candidate_id}_guarded_run",
                guarded_command,
                f"{task.get('label') or candidate_id} 隔离 tester guarded run，仅在独立 tester 窗口内使用。",
            ))
    return hints


def _forward_queue_summary(forward_request: dict[str, Any]) -> dict[str, Any]:
    tasks = [_dict(row) for row in _list(forward_request.get("selectedTasks"))]
    candidate_ids = [
        row.get("candidateId")
        for row in tasks
        if isinstance(row.get("candidateId"), str)
    ]
    ab_candidate_ids = [candidate_id for candidate_id in candidate_ids if "tpsl" not in candidate_id][:2]
    variant_candidate_ids = [candidate_id for candidate_id in candidate_ids if "tpsl" in candidate_id][:4]
    return {
        "queueCount": len(candidate_ids),
        "candidateIds": candidate_ids,
        "abCandidateIds": ab_candidate_ids,
        "variantCandidateIds": variant_candidate_ids,
        "queueSummaryZh": (
            f"A/B 主对照={', '.join(ab_candidate_ids) if ab_candidate_ids else '无'}；"
            f"TP/SL 变体前列={', '.join(variant_candidate_ids) if variant_candidate_ids else '无'}；"
            f"queueCount={len(candidate_ids)}。"
        ),
    }


def _mt5_gate_diagnostics(run_gate: dict[str, Any]) -> dict[str, Any]:
    blockers = _unique(_list(_dict(run_gate.get("gate")).get("blockers")))
    blockers = _unique(blockers + _unique(_list(_dict(run_gate.get("supportingProcessEvidence")).get("blockers"))))
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


def _mt5_window_briefing(release_snapshot: dict[str, Any], tester_forward_action: dict[str, Any]) -> dict[str, Any]:
    gate = _dict(tester_forward_action.get("gateDiagnostics"))
    readiness = _dict(release_snapshot.get("readinessChecklist"))
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
            for row in failed_rows + [
                _dict(row)
                for row in _list(readiness.get("rows"))
                if bool(_dict(row).get("ok"))
            ]
        }
    ] if phase == "IN_WINDOW" and any(
        str(_dict(row).get("id")) == "tester_window_open" and bool(_dict(row).get("ok"))
        for row in _list(readiness.get("rows"))
    ) else []
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
    ab_candidate_ids = _list(tester_forward_action.get("abCandidateIds"))
    variant_candidate_ids = _list(tester_forward_action.get("variantCandidateIds"))

    if phase == "IN_WINDOW":
        summary_zh = (
            "tester window 已打开；如果 refresh/sensitive gate 已转绿，"
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


def _btc_research_actions(
    *,
    strategy_shortlist: dict[str, Any],
    preflight: dict[str, Any],
    live_evidence_intake: dict[str, Any],
    hfm_review: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    btc_readiness = _dict(strategy_shortlist.get("btcLaneReadiness"))
    btc_top = [_dict(item) for item in _list(strategy_shortlist.get("btcTopStrategies"))]
    if not btc_readiness and not btc_top:
        return []

    btc_duel_board = _dict(strategy_shortlist.get("btcLineupBoard")) or _dict(strategy_shortlist.get("btcDuelBoard"))
    strategy_by_id = {
        str(item.get("strategyId") or ""): item
        for item in btc_top
        if isinstance(item.get("strategyId"), str) and item.get("strategyId")
    }
    stable = _dict(strategy_by_id.get(str(btc_duel_board.get("stableAnchorStrategyId") or ""))) or (btc_top[0] if btc_top else {})
    challenger = _dict(strategy_by_id.get(str(btc_duel_board.get("nearLiveChallengerStrategyId") or "")))
    if not challenger:
        challenger = btc_top[1] if len(btc_top) > 1 else {}
    frontier = _dict(strategy_by_id.get(str(btc_duel_board.get("yieldFrontierStrategyId") or "")))
    if not frontier:
        frontier = btc_top[1] if len(btc_top) > 1 else {}
    bridge = btc_top[2] if len(btc_top) > 2 else {}
    stable_cluster = _find_btc_cluster(strategy_shortlist, stable.get("strategyId"))
    challenger_cluster = _find_btc_cluster(strategy_shortlist, challenger.get("strategyId"))
    frontier_cluster = _find_btc_cluster(strategy_shortlist, frontier.get("strategyId"))
    bridge_cluster = _find_btc_cluster(strategy_shortlist, bridge.get("strategyId"))
    scanner_comparison_cluster = _select_btc_scan_comparison_cluster(
        strategy_shortlist,
        excluded_canonical_ids=[
            str(stable_cluster.get("canonicalStrategyId") or stable.get("strategyId") or ""),
            str(frontier_cluster.get("canonicalStrategyId") or frontier.get("strategyId") or ""),
        ],
    ) or bridge_cluster
    blocker_codes = _unique([
        code
        for code in _list(btc_readiness.get("blockers"))
        if isinstance(code, str)
    ])
    command_map = _review_command_map(live_evidence_intake)
    blocker_details = _preflight_blocker_details(preflight)
    runtime_snapshot = _btc_runtime_evidence_snapshot(
        strategy_shortlist=strategy_shortlist,
        preflight=preflight,
        live_evidence_intake=live_evidence_intake,
    )
    btc_gate_diagnostics = _btc_gate_diagnostics(runtime_snapshot, blocker_codes)
    refresh_outcome = _btc_refresh_outcome(
        preflight=preflight,
        live_evidence_intake=live_evidence_intake,
        runtime_snapshot=runtime_snapshot,
    )
    preflight_action_zh, preflight_why_now_zh = _btc_runtime_preflight_focus(runtime_snapshot, blocker_codes)
    preflight_evidence_summary_zh = _btc_runtime_evidence_summary_zh(runtime_snapshot)
    stable_cluster_summary = _cluster_summary_zh(stable_cluster, stable_cluster.get("canonicalStrategyId") or stable.get("strategyId"))
    challenger_cluster_summary = _cluster_summary_zh(challenger_cluster, challenger_cluster.get("canonicalStrategyId") or challenger.get("strategyId"))
    frontier_cluster_summary = _cluster_summary_zh(frontier_cluster, frontier_cluster.get("canonicalStrategyId") or frontier.get("strategyId"))
    bridge_cluster_summary = _cluster_summary_zh(bridge_cluster, bridge_cluster.get("canonicalStrategyId") or bridge.get("strategyId"))
    scanner_comparison_cluster_summary = _cluster_summary_zh(
        scanner_comparison_cluster,
        scanner_comparison_cluster.get("canonicalStrategyId"),
    )
    stable_converged_display = _btc_near_live_converged_cluster_display(
        btc_duel_board,
        stable_cluster.get("canonicalStrategyId") or stable.get("strategyId"),
        role="focus",
    )
    challenger_converged_display = _btc_near_live_converged_cluster_display(
        btc_duel_board,
        challenger_cluster.get("canonicalStrategyId") or challenger.get("strategyId"),
        role="challenger",
    )
    frontier_converged_display = _btc_near_live_converged_cluster_display(
        btc_duel_board,
        frontier_cluster.get("canonicalStrategyId") or frontier.get("strategyId"),
        role="yield",
    )
    comparison_converged_display = _btc_near_live_converged_cluster_display(
        btc_duel_board,
        scanner_comparison_cluster.get("canonicalStrategyId"),
        role="challenger",
    )
    stable_cluster_aliases = (
        _list(stable_converged_display.get("aliasStrategyIds"))
        if stable_converged_display
        else _cluster_aliases(stable_cluster, stable_cluster.get("canonicalStrategyId") or stable.get("strategyId"))
    )
    challenger_cluster_aliases = (
        _list(challenger_converged_display.get("aliasStrategyIds"))
        if challenger_converged_display
        else _cluster_aliases(challenger_cluster, challenger_cluster.get("canonicalStrategyId") or challenger.get("strategyId"))
    )
    frontier_cluster_aliases = (
        _list(frontier_converged_display.get("aliasStrategyIds"))
        if frontier_converged_display
        else _cluster_aliases(frontier_cluster, frontier_cluster.get("canonicalStrategyId") or frontier.get("strategyId"))
    )
    comparison_cluster_aliases = (
        _list(comparison_converged_display.get("aliasStrategyIds"))
        if comparison_converged_display
        else _cluster_aliases(scanner_comparison_cluster, scanner_comparison_cluster.get("canonicalStrategyId") or bridge.get("strategyId"))
    )
    stable_cluster_summary = stable_converged_display.get("summaryZh") or stable_cluster_summary
    challenger_cluster_summary = challenger_converged_display.get("summaryZh") or challenger_cluster_summary
    frontier_cluster_summary = frontier_converged_display.get("summaryZh") or frontier_cluster_summary
    scanner_comparison_cluster_summary = comparison_converged_display.get("summaryZh") or scanner_comparison_cluster_summary
    scanner_comparison_strategy_id = (
        scanner_comparison_cluster.get("canonicalStrategyId")
        or bridge.get("strategyId")
        or "sample-rich bridge"
    )
    scanner_comparison_priority = scanner_comparison_cluster.get("recommendedResearchPriority")
    scanner_comparison_reason_zh = scanner_comparison_cluster.get("recommendedResearchReasonZh")
    recommended_focused_retest_order = [
        str(item)
        for item in _list(btc_duel_board.get("recommendedFocusedRetestOrder"))
        if isinstance(item, str) and item
    ]

    queue = [
        _action(
            "refresh_btc_runtime_preflight_inputs",
            "READY",
            preflight_action_zh,
            lane="btcCryptoCfd",
            stage="runtime_preflight",
            blockers=blocker_codes,
            commands=[
                hint for key in (
                    "refresh_evidence_intake",
                    "run_hfm_post_upgrade_controller",
                    "verify_mt5_ea_post_upgrade",
                    "build_mt5_ea_upgrade_bundle",
                )
                if (hint := command_map.get(key))
            ],
        ),
        _action(
            "rerun_btc_tp_sl_optimizer",
            "READY",
            (
                f"围绕稳健默认 {stable.get('strategyId') or 'BTC stable anchor'} 继续修复 middle_third，"
                f"同时先和 {challenger.get('strategyId') or 'near-live challenger'} 做稳定性对照。"
                f"{_append_sentence_zh('', stable_cluster_summary)}"
                f"{_append_sentence_zh('稳定 challenger 簇: ', challenger_cluster_summary)}"
            ),
            lane="btcCryptoCfd",
            stage="focused_retest",
            blockers=_unique(_list(stable.get("blockers"))),
            commands=[
                _command_hint(
                    "run_tp_sl_optimizer_build",
                    "python3 tools/run_tp_sl_optimizer.py --runtime-dir runtime build",
                    "刷新 BTC TP/SL 候选、middle_third 修复方向和 focusedRetestQueue。",
                )
            ],
        ),
        _action(
            "rerun_btc_strategy_scanner",
            "READY",
            (
                f"复扫 BTC 候选，比较 {frontier.get('strategyId') or 'yield frontier'} 与 "
                f"{scanner_comparison_strategy_id} 是否出现更稳替代。"
                f"{_append_sentence_zh('当前高收益簇: ', frontier_cluster_summary)}"
                f"{_append_sentence_zh('样本/替补簇: ', scanner_comparison_cluster_summary)}"
                f"{' 该对照簇研究优先级=' + str(scanner_comparison_priority) + '。' if scanner_comparison_priority is not None else ''}"
                f"{' 原因: ' + scanner_comparison_reason_zh if scanner_comparison_reason_zh else ''}"
            ),
            lane="btcCryptoCfd",
            stage="candidate_scan",
            commands=[
                _command_hint(
                    "run_btc_strategy_scanner_build",
                    "python3 tools/run_btc_strategy_scanner.py --runtime-dir runtime build",
                    "刷新 BTC focused scan，重排高收益、质量修复、样本密度候选。",
                )
            ],
        ),
    ]
    queue[0]["whyNowZh"] = preflight_why_now_zh
    queue[0]["evidenceSummaryZh"] = preflight_evidence_summary_zh
    queue[0]["blockerDetails"] = blocker_details
    queue[0]["evidenceSnapshot"] = runtime_snapshot
    queue[0]["nextRequiredActionZh"] = preflight.get("nextRequiredActionZh")
    queue[0]["refreshOutcome"] = refresh_outcome
    queue[0]["focusClusterCanonicalStrategyId"] = stable_cluster.get("canonicalStrategyId") or stable.get("strategyId")
    queue[0]["focusClusterAliasStrategyIds"] = stable_cluster_aliases
    queue[0]["focusClusterSummaryZh"] = stable_cluster_summary
    queue[0]["directExecutionBlockerCode"] = runtime_snapshot.get("directExecutionBlockerCode")
    queue[0]["directExecutionBlockerDetailZh"] = runtime_snapshot.get("directExecutionBlockerDetailZh")
    queue[0]["permissionChainHealthy"] = runtime_snapshot.get("permissionChainHealthy")
    queue[0]["gateDiagnostics"] = btc_gate_diagnostics
    queue[0]["commands"] = [
        _annotate_btc_preflight_command(command, hfm_review=hfm_review)
        for command in _list(queue[0].get("commands"))
    ]
    queue[1]["focusClusterCanonicalStrategyId"] = stable_cluster.get("canonicalStrategyId") or stable.get("strategyId")
    queue[1]["focusClusterAliasStrategyIds"] = stable_cluster_aliases
    queue[1]["focusClusterSummaryZh"] = stable_cluster_summary
    queue[1]["comparisonClusterCanonicalStrategyId"] = challenger_cluster.get("canonicalStrategyId") or challenger.get("strategyId")
    queue[1]["comparisonClusterAliasStrategyIds"] = challenger_cluster_aliases
    queue[1]["comparisonClusterSummaryZh"] = challenger_cluster_summary
    queue[1]["comparisonClusterRecommendedResearchPriority"] = challenger_cluster.get("recommendedResearchPriority")
    queue[1]["comparisonClusterRecommendedResearchReasonZh"] = challenger_cluster.get("recommendedResearchReasonZh")
    queue[1]["yieldFrontierClusterCanonicalStrategyId"] = frontier_cluster.get("canonicalStrategyId") or frontier.get("strategyId")
    queue[1]["yieldFrontierClusterAliasStrategyIds"] = frontier_cluster_aliases
    queue[1]["yieldFrontierClusterSummaryZh"] = frontier_cluster_summary
    queue[1]["whyNowZh"] = (
        challenger_cluster.get("recommendedResearchReasonZh")
        or btc_duel_board.get("recommendationZh")
        or "默认稳健锚点与当前 challenger 仍需继续做稳定性对照。"
    )
    queue[1]["evidenceSummaryZh"] = (
        f"稳定主线={stable.get('strategyId') or '无'}；"
        f"对照 challenger={challenger.get('strategyId') or '无'}；"
        f"focusedRetestOrder={(' -> '.join(recommended_focused_retest_order) if recommended_focused_retest_order else '未提供')}。"
    )
    queue[1]["evidenceSnapshot"] = {
        "stableAnchorStrategyId": stable.get("strategyId"),
        "challengerStrategyId": challenger.get("strategyId"),
        "yieldFrontierStrategyId": frontier.get("strategyId"),
        "recommendedFocusedRetestOrder": recommended_focused_retest_order,
        "focusClusterCanonicalStrategyId": queue[1]["focusClusterCanonicalStrategyId"],
        "comparisonClusterCanonicalStrategyId": queue[1]["comparisonClusterCanonicalStrategyId"],
    }
    queue[2]["focusClusterCanonicalStrategyId"] = frontier_cluster.get("canonicalStrategyId") or frontier.get("strategyId")
    queue[2]["focusClusterAliasStrategyIds"] = frontier_cluster_aliases
    queue[2]["focusClusterSummaryZh"] = frontier_cluster_summary
    queue[2]["comparisonClusterCanonicalStrategyId"] = scanner_comparison_cluster.get("canonicalStrategyId") or bridge.get("strategyId")
    queue[2]["comparisonClusterAliasStrategyIds"] = comparison_cluster_aliases
    queue[2]["comparisonClusterSummaryZh"] = scanner_comparison_cluster_summary or bridge_cluster_summary
    queue[2]["comparisonClusterRecommendedResearchPriority"] = scanner_comparison_priority
    queue[2]["comparisonClusterRecommendedResearchReasonZh"] = scanner_comparison_reason_zh
    queue[2]["whyNowZh"] = (
        scanner_comparison_reason_zh
        or "当前需要继续复扫 BTC comparison cluster，确认是否出现更稳替代。"
    )
    queue[2]["evidenceSummaryZh"] = (
        f"高收益簇={frontier.get('strategyId') or '无'}；"
        f"对照簇={scanner_comparison_strategy_id}；"
        f"researchPriority={scanner_comparison_priority if scanner_comparison_priority is not None else '未提供'}；"
        f"focusedRetestOrder={(' -> '.join(recommended_focused_retest_order) if recommended_focused_retest_order else '未提供')}。"
    )
    queue[2]["evidenceSnapshot"] = {
        "yieldFrontierStrategyId": frontier.get("strategyId"),
        "comparisonClusterCanonicalStrategyId": queue[2]["comparisonClusterCanonicalStrategyId"],
        "comparisonClusterRecommendedResearchPriority": scanner_comparison_priority,
        "comparisonClusterRecommendedResearchReasonZh": scanner_comparison_reason_zh,
        "recommendedFocusedRetestOrder": recommended_focused_retest_order,
    }
    return queue


def _build_action_queue(
    *,
    selected_lane: str | None,
    selected_seed: str | None,
    selected_strategy: str | None,
    prerequisites: list[str],
    run_gate_blockers: list[str],
    process_blockers: list[str],
    can_run_tester: bool,
    lock_ready: bool,
    target_reached: bool,
    forward_request: dict[str, Any],
    next_tester_window: dict[str, Any],
    strategy_shortlist: dict[str, Any],
    preflight: dict[str, Any],
    live_evidence_intake: dict[str, Any],
    hfm_review: dict[str, dict[str, Any]],
    run_gate: dict[str, Any],
    account_context: dict[str, Any],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    forward_commands = _champion_forward_command_hints(forward_request)
    forward_queue_summary = _forward_queue_summary(forward_request)
    mt5_lane_readiness = _dict(strategy_shortlist.get("mt5LaneReadiness"))
    mt5_window_briefing = _dict(mt5_lane_readiness.get("windowBriefing"))
    mt5_readiness = _dict(mt5_lane_readiness.get("readinessChecklist"))
    run_gate_live_session = _dict(_dict(run_gate.get("gate")).get("liveSession"))
    run_gate_lock = _dict(_dict(run_gate.get("gate")).get("authorizationLock"))
    lock_refresh_guidance = _mt5_lock_refresh_guidance(run_gate)
    run_gate_decision = _dict(run_gate.get("decision"))
    mt5_gate_diagnostics = _mt5_gate_diagnostics({
        "gate": {"blockers": run_gate_blockers},
        "nextTesterWindow": next_tester_window,
    })

    def _mt5_tester_residual_gate_reason() -> str:
        blockers_zh: list[str] = []
        if "authorization_lock_expired" in run_gate_blockers:
            blockers_zh.append("authorization lock")
        if "live_dashboard_snapshot_stale" in run_gate_blockers:
            blockers_zh.append("dashboard freshness")
        if "outside_strategy_tester_window" in run_gate_blockers:
            blockers_zh.append("tester window")
        if any(code in run_gate_blockers for code in (
            "isolated_tester_account_context_not_ready",
            "sensitive_account_context_sync_required",
        )):
            blockers_zh.append("isolated account context")
        if not blockers_zh:
            return "当前前置 gate 已基本齐备，剩余 blocker 很少；tester-forward run 仍要继续按 guard 顺序启动。"
        if len(blockers_zh) == 1:
            blocker_phrase = blockers_zh[0]
        elif len(blockers_zh) == 2:
            blocker_phrase = f"{blockers_zh[0]} 和 {blockers_zh[1]}"
        else:
            blocker_phrase = "、".join(blockers_zh[:-1]) + f" 和 {blockers_zh[-1]}"
        return (
            "A/B 主对照和 TP/SL 变体队列都已就绪；"
            f"当前仍需先清 {blocker_phrase}，才能进入 guarded tester-forward run。"
        )

    if not target_reached:
        queue.append(_action(
            "profit_target_refresh",
            "WAITING",
            "继续刷新 forex/BTC 模拟收益证据，直到任一 lane 或合计达到目标。",
            stage="target_evidence",
        ))
    if "outside_strategy_tester_window" in run_gate_blockers:
        queue.append(_action(
            "wait_for_tester_window",
            "WAITING",
            "等待 20:10-23:30 JST tester 窗口后自动刷新 champion tester run gate。",
            lane="forexMt5",
            stage="tester_window",
            blockers=["outside_strategy_tester_window"],
        ))
    process_evidence_blockers = [
        code for code in ("mt5_terminal_process_missing",)
        if code in process_blockers
    ]
    terminal_blockers = [
        code for code in ("live_dashboard_snapshot_stale",)
        if code in run_gate_blockers
    ]
    if not terminal_blockers and process_evidence_blockers:
        terminal_blockers = list(process_evidence_blockers)
    if terminal_blockers:
        restore_action_zh = (
            _mt5_terminal_restore_action_zh(run_gate)
            if process_evidence_blockers
            else "主 MT5/EA 未持续刷新 live dashboard；恢复前不能确认 live session freshness。"
        )
        restore_action_blockers = _unique(terminal_blockers + process_evidence_blockers)
        queue.append(_action(
            "restore_live_mt5_dashboard_refresh",
            "BLOCKED",
            restore_action_zh,
            lane="forexMt5",
            stage="runtime_freshness",
            blockers=restore_action_blockers,
        ))
        queue[-1]["whyNowZh"] = (
            (
                "当前最值钱的是先恢复主 MT5 terminal64 进程并恢复 dashboard freshness；"
                "tester window 到点后只会自动清掉 outside_strategy_tester_window，不能替代主 terminal/dash 刷新。"
            )
            if process_evidence_blockers
            else mt5_window_briefing.get("postWindowPrimarySummaryZh")
            or mt5_window_briefing.get("summaryZh")
            or "当前仍需先恢复主 MT5 dashboard freshness，tester window 已开也不能替代这一项。"
        )
        queue[-1]["evidenceSummaryZh"] = (
            f"{mt5_lane_readiness.get('testerSummaryZh') or 'testerSummaryZh=missing'} "
            f"{mt5_readiness.get('summaryZh') or ''}"
        ).strip()
        queue[-1]["evidenceSnapshot"] = {
            "snapshotTimestamp": run_gate_live_session.get("snapshotTimestamp"),
            "snapshotAgeMinutes": run_gate_live_session.get("snapshotAgeMinutes"),
            "maxSnapshotAgeMinutes": run_gate_live_session.get("maxSnapshotAgeMinutes"),
            "liveSessionOk": bool(run_gate_live_session.get("ok")),
            "processEvidenceBlockers": process_evidence_blockers,
            "windowPhase": mt5_window_briefing.get("phase"),
            "readinessRatio": _dict(mt5_window_briefing.get("readinessNow")).get("ratio"),
            "highestLeveragePostWindowCheckIds": _list(mt5_window_briefing.get("highestLeveragePostWindowCheckIds")),
        }
        process_evidence = _dict(run_gate.get("supportingProcessEvidence"))
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
                queue[-1]["evidenceSnapshot"][key] = value
        if process_evidence_blockers:
            queue[-1]["supportingProcessBlockers"] = process_evidence_blockers
        queue[-1]["nextRequiredActionZh"] = (
            _mt5_terminal_restore_required_action_zh(run_gate)
            if process_evidence_blockers
            else "先恢复主 MT5 dashboard freshness，再重建 tester gate。"
        )
    if any(code in run_gate_blockers for code in (
        "isolated_tester_account_context_not_ready",
        "sensitive_account_context_sync_required",
    )):
        queue.append(_action(
            "separate_account_context_sync_review",
            "BLOCKED",
            "隔离 tester 缺账号上下文；只允许单独受控同步，本计划不复制账号文件。",
            lane="forexMt5",
            stage="account_context",
            blockers=[
                code for code in (
                    "isolated_tester_account_context_not_ready",
                    "sensitive_account_context_sync_required",
                ) if code in run_gate_blockers
            ],
        ))
        queue[-1]["whyNowZh"] = (
            mt5_window_briefing.get("postWindowPrimarySummaryZh")
            or "开窗后仍需优先清隔离 tester account context，否则 tester_can_run_now 不会转绿。"
        )
        queue[-1]["evidenceSummaryZh"] = (
            f"mode={account_context.get('mode') or 'unknown'} "
            f"missingTarget={','.join(_list(account_context.get('missingTarget'))) or 'none'} "
            f"sensitiveSyncRequired={bool(account_context.get('sensitiveAccountContextSyncRequired'))}"
        )
        queue[-1]["evidenceSnapshot"] = {
            "ready": bool(account_context.get("ready")),
            "mode": account_context.get("mode"),
            "missingTarget": _list(account_context.get("missingTarget")),
            "sensitiveAccountContextSyncRequired": bool(account_context.get("sensitiveAccountContextSyncRequired")),
            "highestLeveragePostWindowCheckIds": _list(mt5_window_briefing.get("highestLeveragePostWindowCheckIds")),
        }
        queue[-1]["nextRequiredActionZh"] = (
            account_context.get("nextActionZh")
            or "完成隔离 tester account context 的受控补齐后再复核。"
        )
    if "authorization_lock_expired" in run_gate_blockers or not lock_ready:
        queue.append(_action(
            "tester_lock_refresh",
            "WAITING",
            "需要短期 tester-only lock 刷新；本计划只暴露草案，不写 lock 文件。",
            lane="forexMt5",
            stage="tester_lock",
            blockers=["authorization_lock_expired"] if "authorization_lock_expired" in run_gate_blockers else [],
        ))
        queue[-1]["whyNowZh"] = (
            lock_refresh_guidance.get("summaryZh")
            or "tester window 已开，但 authorization lock 仍过期；不刷新 tester-only lock，就不能进入 guarded tester run。"
        )
        queue[-1]["evidenceSummaryZh"] = (
            f"lockStatus={run_gate_lock.get('status') or 'unknown'} "
            f"expiresAtIso={run_gate_lock.get('expiresAtIso') or 'missing'} "
            f"recommendedEarliestRefreshJstIso={lock_refresh_guidance.get('recommendedEarliestRefreshJstIso') or 'missing'} "
            f"canRunIsolatedTester={bool(run_gate_decision.get('canRunIsolatedTester'))}"
        )
        queue[-1]["evidenceSnapshot"] = {
            "status": run_gate_lock.get("status"),
            "expiresAtIso": run_gate_lock.get("expiresAtIso"),
            "createdAtIso": run_gate_lock.get("createdAtIso"),
            "allowOutsideWindow": bool(run_gate_lock.get("allowOutsideWindow")),
            "canRunIsolatedTester": bool(run_gate_decision.get("canRunIsolatedTester")),
            "refreshGuidance": dict(lock_refresh_guidance),
        }
        queue[-1]["nextRequiredActionZh"] = (
            lock_refresh_guidance.get("nextRequiredActionZh")
            or "刷新 tester-only lock 草案和授权状态。"
        )
    tester_downstream_requirements = [
        code for code in prerequisites
        if code in (
            "isolated_tester_forward_report_ready",
            "champion_tester_run_gate_ready",
            "separate_execution_release_lane_ready",
        )
    ]
    tester_action_blockers = [] if can_run_tester else list(run_gate_blockers)
    if not tester_action_blockers and process_evidence_blockers:
        tester_action_blockers = list(process_evidence_blockers)
    queue.append(_action(
        "run_forex_ab_tester_forward",
        "READY" if can_run_tester else "GATED",
        (
            f"对 {selected_seed or 'selected champion'} / G0102 执行隔离 tester-forward A/B 和 TP/SL 变体复验。"
            if selected_lane == "forexMt5"
            else f"继续复验 {selected_strategy or 'BTC TP/SL'} 多窗口稳定性。"
        ),
        lane=selected_lane or "forexMt5",
        stage="tester_forward",
        blockers=tester_action_blockers,
        commands=forward_commands,
    ))
    queue[-1]["queueCount"] = forward_queue_summary.get("queueCount")
    queue[-1]["queuedCandidateIds"] = _list(forward_queue_summary.get("candidateIds"))
    queue[-1]["abCandidateIds"] = _list(forward_queue_summary.get("abCandidateIds"))
    queue[-1]["variantCandidateIds"] = _list(forward_queue_summary.get("variantCandidateIds"))
    queue[-1]["queueSummaryZh"] = forward_queue_summary.get("queueSummaryZh")
    queue[-1]["gateDiagnostics"] = dict(mt5_gate_diagnostics)
    if process_evidence_blockers:
        gate_diag = queue[-1]["gateDiagnostics"]
        gate_diag["processRecoveryBlockers"] = _unique(
            _list(gate_diag.get("processRecoveryBlockers")) + process_evidence_blockers
        )
        summary_zh = str(gate_diag.get("summaryZh") or "")
        if "需恢复进程=" not in summary_zh:
            summary_zh = (
                summary_zh.rstrip("。")
                + f"；需恢复进程={','.join(process_evidence_blockers)}。"
            ).lstrip("；")
        elif "需恢复进程=无" in summary_zh:
            summary_zh = summary_zh.replace(
                "需恢复进程=无",
                f"需恢复进程={','.join(process_evidence_blockers)}",
            )
        gate_diag["summaryZh"] = summary_zh
    queue[-1]["whyNowZh"] = _mt5_tester_residual_gate_reason()
    queue[-1]["evidenceSummaryZh"] = (
        f"{mt5_lane_readiness.get('testerSummaryZh') or 'testerSummaryZh=missing'} "
        f"{forward_queue_summary.get('queueSummaryZh') or ''}"
    ).strip()
    queue[-1]["evidenceSnapshot"] = {
        "windowPhase": mt5_window_briefing.get("phase"),
        "queueCount": forward_queue_summary.get("queueCount"),
        "abCandidateIds": _list(forward_queue_summary.get("abCandidateIds")),
        "variantCandidateIds": _list(forward_queue_summary.get("variantCandidateIds")),
        "highestLeveragePostWindowCheckIds": _list(mt5_window_briefing.get("highestLeveragePostWindowCheckIds")),
        "canRunIsolatedTester": bool(run_gate_decision.get("canRunIsolatedTester")),
        "processEvidenceBlockers": process_evidence_blockers,
        "downstreamReleaseRequirementIds": tester_downstream_requirements,
    }
    process_evidence = _dict(run_gate.get("supportingProcessEvidence"))
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
            queue[-1]["evidenceSnapshot"][key] = value
    if process_evidence_blockers:
        queue[-1]["supportingProcessBlockers"] = process_evidence_blockers
    queue[-1]["downstreamReleaseRequirementIds"] = tester_downstream_requirements
    queue[-1]["nextRequiredActionZh"] = (
        _mt5_terminal_restore_required_action_zh(run_gate)
        if process_evidence_blockers
        else mt5_lane_readiness.get("nextActionZh")
        or "先清空 tester gate blocker，再尝试 guarded tester-forward A/B。"
    )
    queue.extend(_btc_research_actions(
        strategy_shortlist=strategy_shortlist,
        preflight=preflight,
        live_evidence_intake=live_evidence_intake,
        hfm_review=hfm_review,
    ))
    queue.append(_action(
        "separate_execution_release_lane",
        "GATED",
        "tester-forward 胜者确认后，才进入单独 execution release lane；当前不写订单。",
        lane="shared_release_lane",
        stage="release_review",
        blockers=["isolated_tester_forward_report_ready", "separate_execution_release_lane_ready"],
    ))
    return queue


def _priority_summary(
    *,
    strategy_shortlist: dict[str, Any],
    execution_readiness_board: dict[str, Any],
    live_selection: dict[str, Any],
    action_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    btc_duel_board = _dict(strategy_shortlist.get("btcLineupBoard")) or _dict(strategy_shortlist.get("btcDuelBoard"))
    btc_top_strategies = [_dict(row) for row in _list(strategy_shortlist.get("btcTopStrategies"))]
    mt5_ab_board = _dict(strategy_shortlist.get("mt5AbBoard"))
    lane_verdicts = _dict(strategy_shortlist.get("laneVerdicts"))
    mt5_verdict = _dict(lane_verdicts.get("mt5"))
    mt5_strongest = _dict(mt5_verdict.get("strongestNow"))
    mt5_top_strategies = [_dict(row) for row in _list(strategy_shortlist.get("mt5TopStrategies"))]
    selected_strategy = _dict(live_selection.get("selectedStrategy"))
    closest_lane = execution_readiness_board.get("closestResearchLaneNow")
    selected_release_lane = (
        execution_readiness_board.get("selectedLaneForSeparateReleaseReview")
        or live_selection.get("selectedLane")
    )
    legacy_next_actions = [_dict(row) for row in _list(execution_readiness_board.get("nextActionsOverall"))]
    indexed_action_queue = [
        (index, _dict(row))
        for index, row in enumerate(_list(action_queue))
    ]
    stage_rank = {
        "runtime_preflight": 0,
        "focused_retest": 1,
        "candidate_scan": 2,
        "runtime_freshness": 3,
        "account_context": 4,
        "tester_lock": 5,
        "tester_window": 6,
        "tester_forward": 7,
        "release_review": 8,
        "target_evidence": 9,
    }

    def _priority_preview_bucket(item: dict[str, Any]) -> int:
        lane = item.get("lane")
        if isinstance(lane, str) and lane == closest_lane:
            return 0
        if isinstance(lane, str) and lane == selected_release_lane:
            return 1
        if lane == "shared_release_lane":
            return 2
        return 3

    def _lane_stage_priority(item: dict[str, Any], fallback_index: int) -> int:
        action_id = str(item.get("id") or "")
        stage = str(item.get("stage") or "")
        if action_id == "wait_for_tester_window":
            return max(stage_rank.get(stage, 999), stage_rank["tester_window"])
        return stage_rank.get(stage, fallback_index)

    next_actions = []
    sorted_indexed_actions = sorted(
        indexed_action_queue,
        key=lambda pair: (
            _priority_preview_bucket(pair[1]),
            _lane_stage_priority(pair[1], pair[0]),
            pair[0],
        ),
    )
    for _, item in sorted_indexed_actions[:3]:
        action_id = item.get("id")
        next_actions.append({
            "id": action_id,
            "actionId": action_id,
            "lane": item.get("lane"),
            "actionZh": item.get("actionZh"),
            "whyNowZh": item.get("whyNowZh"),
            "evidenceSummaryZh": item.get("evidenceSummaryZh"),
            "evidenceSnapshot": _dict(item.get("evidenceSnapshot")),
            "gateDiagnostics": _dict(item.get("gateDiagnostics")),
            "blockers": _list(item.get("blockers")),
            "checkIds": _list(item.get("checkIds")),
            "nextRequiredActionZh": item.get("nextRequiredActionZh"),
            "directExecutionBlockerCode": item.get("directExecutionBlockerCode"),
            "status": item.get("status"),
            "recommendedOrder": item.get("recommendedOrder"),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })
    if not next_actions:
        next_actions = legacy_next_actions
    focus_strategy_id: str | None = None
    for row in _list(execution_readiness_board.get("laneSnapshots")):
        item = _dict(row)
        if item.get("lane") == closest_lane:
            focus_strategy_id = item.get("focusStrategyId")
            break
    if not focus_strategy_id:
        focus_strategy_id = _dict(live_selection.get("selectedStrategy")).get("strategyId")
    focus_cluster_canonical_strategy_id: str | None = None
    focus_cluster_alias_strategy_ids: list[str] = []
    focus_cluster_summary_zh: str | None = None
    comparison_cluster_canonical_strategy_id: str | None = None
    comparison_cluster_alias_strategy_ids: list[str] = []
    comparison_cluster_summary_zh: str | None = None
    comparison_cluster_research_priority: int | None = None
    comparison_cluster_research_reason_zh: str | None = None
    yield_frontier_cluster_summary_zh: str | None = None
    for row in _list(action_queue):
        item = _dict(row)
        if item.get("lane") == closest_lane and item.get("focusClusterCanonicalStrategyId"):
            focus_cluster_canonical_strategy_id = item.get("focusClusterCanonicalStrategyId")
            focus_cluster_alias_strategy_ids = _list(item.get("focusClusterAliasStrategyIds"))
            focus_cluster_summary_zh = item.get("focusClusterSummaryZh")
            break
    for row in _list(action_queue):
        item = _dict(row)
        if item.get("lane") == closest_lane and item.get("comparisonClusterCanonicalStrategyId"):
            comparison_cluster_canonical_strategy_id = item.get("comparisonClusterCanonicalStrategyId")
            comparison_cluster_alias_strategy_ids = _list(item.get("comparisonClusterAliasStrategyIds"))
            comparison_cluster_summary_zh = item.get("comparisonClusterSummaryZh")
            if isinstance(item.get("comparisonClusterRecommendedResearchPriority"), int):
                comparison_cluster_research_priority = item.get("comparisonClusterRecommendedResearchPriority")
            comparison_cluster_research_reason_zh = item.get("comparisonClusterRecommendedResearchReasonZh")
            break
    for row in _list(action_queue):
        item = _dict(row)
        if item.get("lane") == closest_lane and isinstance(item.get("yieldFrontierClusterSummaryZh"), str):
            yield_frontier_cluster_summary_zh = item.get("yieldFrontierClusterSummaryZh")
            break
    stable_btc_item = next(
        (item for item in btc_top_strategies if item.get("role") == "stableAnchor"),
        btc_top_strategies[0] if btc_top_strategies else {},
    )
    near_live_btc_item = next(
        (
            item for item in btc_top_strategies
            if item.get("role") in ("stabilityAlternative", "stableAlternative")
        ),
        btc_top_strategies[1] if len(btc_top_strategies) > 1 else {},
    )
    yield_btc_item = next(
        (item for item in btc_top_strategies if item.get("role") == "highYieldTradeoff"),
        btc_top_strategies[2] if len(btc_top_strategies) > 2 else (btc_top_strategies[1] if len(btc_top_strategies) > 1 else {}),
    )
    btc_context_recommended_order = [
        item
        for item in _list(btc_duel_board.get("recommendedFocusedRetestOrder"))
        if isinstance(item, str) and item
    ]
    if not btc_context_recommended_order:
        btc_context_recommended_order = [
            str(_dict(item).get("strategyId"))
            for item in (stable_btc_item, near_live_btc_item, yield_btc_item)
            if isinstance(_dict(item).get("strategyId"), str) and _dict(item).get("strategyId")
        ]
    stability_first_top3_strategy_ids = [
        item
        for item in _list(btc_duel_board.get("stabilityFirstTop3StrategyIds"))
        if isinstance(item, str) and item
    ]
    if not stability_first_top3_strategy_ids:
        stability_first_top3_strategy_ids = [
            item
            for item in [
                btc_duel_board.get("stableAnchorStrategyId") or stable_btc_item.get("strategyId"),
                btc_duel_board.get("nearLiveChallengerStrategyId") or near_live_btc_item.get("strategyId"),
                btc_duel_board.get("stableMiddleTradeoffFollowupBestStrategyId"),
            ]
            if isinstance(item, str) and item
        ]
    yield_inclusive_top3_strategy_ids = [
        item
        for item in _list(btc_duel_board.get("yieldInclusiveTop3StrategyIds"))
        if isinstance(item, str) and item
    ]
    if not yield_inclusive_top3_strategy_ids:
        yield_inclusive_top3_strategy_ids = [
            item
            for item in [
                btc_duel_board.get("stableAnchorStrategyId") or stable_btc_item.get("strategyId"),
                btc_duel_board.get("nearLiveChallengerStrategyId") or near_live_btc_item.get("strategyId"),
                btc_duel_board.get("yieldFrontierStrategyId") or yield_btc_item.get("strategyId"),
            ]
            if isinstance(item, str) and item
        ]
    stability_first_summary_zh = btc_duel_board.get("stabilityFirstSummaryZh")
    if not isinstance(stability_first_summary_zh, str) or not stability_first_summary_zh.strip():
        stability_first_summary_zh = (
            "稳定优先 top3: " + " -> ".join(stability_first_top3_strategy_ids)
            if stability_first_top3_strategy_ids
            else None
        )
    yield_inclusive_summary_zh = btc_duel_board.get("yieldInclusiveSummaryZh")
    if not isinstance(yield_inclusive_summary_zh, str) or not yield_inclusive_summary_zh.strip():
        yield_inclusive_summary_zh = (
            "收益纳入 top3: " + " -> ".join(yield_inclusive_top3_strategy_ids)
            if yield_inclusive_top3_strategy_ids
            else None
        )
    btc_context_snapshot = {
        "lane": "btcCryptoCfd",
        "stableAnchorStrategyId": btc_duel_board.get("stableAnchorStrategyId") or stable_btc_item.get("strategyId"),
        "nearLiveChallengerStrategyId": btc_duel_board.get("nearLiveChallengerStrategyId") or near_live_btc_item.get("strategyId"),
        "yieldFrontierStrategyId": btc_duel_board.get("yieldFrontierStrategyId") or yield_btc_item.get("strategyId"),
        "stabilityFirstTop3StrategyIds": stability_first_top3_strategy_ids,
        "yieldInclusiveTop3StrategyIds": yield_inclusive_top3_strategy_ids,
        "stabilityFirstSummaryZh": stability_first_summary_zh,
        "yieldInclusiveSummaryZh": yield_inclusive_summary_zh,
        "nearLiveMiddleWindowVariantStrategyIds": [
            item
            for item in _list(btc_duel_board.get("nearLiveMiddleWindowVariantStrategyIds"))
            if isinstance(item, str) and item
        ],
        "nearLiveMiddleWindowVariantRows": [
            _dict(item)
            for item in _list(btc_duel_board.get("nearLiveMiddleWindowVariantRows"))
            if _dict(item)
        ],
        "nearLiveMiddleWindowVariantStopLossLadder": [
            item
            for item in _list(btc_duel_board.get("nearLiveMiddleWindowVariantStopLossLadder"))
            if item is not None
        ],
        "nearLiveMiddleWindowVariantSummaryZh": btc_duel_board.get("nearLiveMiddleWindowVariantSummaryZh"),
        "nearLiveConvergedVariantStrategyIds": [
            item
            for item in _list(btc_duel_board.get("nearLiveConvergedVariantStrategyIds"))
            if isinstance(item, str) and item
        ],
        "nearLiveConvergedVariantRows": [
            _dict(item)
            for item in _list(btc_duel_board.get("nearLiveConvergedVariantRows"))
            if _dict(item)
        ],
        "nearLiveConvergedVariantStopLossLadder": [
            item
            for item in _list(btc_duel_board.get("nearLiveConvergedVariantStopLossLadder"))
            if item is not None
        ],
        "nearLiveConvergedVariantSummaryZh": btc_duel_board.get("nearLiveConvergedVariantSummaryZh"),
        "yieldLeaderStrategyId": btc_duel_board.get("yieldFrontierStrategyId") or yield_btc_item.get("strategyId"),
        "yieldLeaderConfirmationBestStrategyId": btc_duel_board.get("yieldLeaderConfirmationBestStrategyId"),
        "yieldLeaderConfirmationImprovesBaseline": btc_duel_board.get("yieldLeaderConfirmationImprovesBaseline"),
        "yieldLeaderConfirmationOutcomeZh": btc_duel_board.get("yieldLeaderConfirmationOutcomeZh"),
        "stableMiddleThirdFollowupBestStrategyId": btc_duel_board.get("stableMiddleThirdFollowupBestStrategyId"),
        "stableMiddleThirdFollowupImprovesAggregate": btc_duel_board.get("stableMiddleThirdFollowupImprovesAggregate"),
        "stableMiddleThirdFollowupImprovesWeakWindow": btc_duel_board.get("stableMiddleThirdFollowupImprovesWeakWindow"),
        "stableMiddleThirdFollowupImprovesRepair": btc_duel_board.get("stableMiddleThirdFollowupImprovesRepair"),
        "stableMiddleThirdFollowupOutcomeZh": btc_duel_board.get("stableMiddleThirdFollowupOutcomeZh"),
        "stableMiddleWeakWindowConfirmationBestStrategyId": btc_duel_board.get("stableMiddleWeakWindowConfirmationBestStrategyId"),
        "stableMiddleWeakWindowConfirmationImprovesBaseline": btc_duel_board.get("stableMiddleWeakWindowConfirmationImprovesBaseline"),
        "stableMiddleWeakWindowConfirmationOutcomeZh": btc_duel_board.get("stableMiddleWeakWindowConfirmationOutcomeZh"),
        "stableMiddleWeakWindowBridgeBestStrategyId": btc_duel_board.get("stableMiddleWeakWindowBridgeBestStrategyId"),
        "stableMiddleWeakWindowBridgeImprovesAggregate": btc_duel_board.get("stableMiddleWeakWindowBridgeImprovesAggregate"),
        "stableMiddleWeakWindowBridgeImprovesWeakWindow": btc_duel_board.get("stableMiddleWeakWindowBridgeImprovesWeakWindow"),
        "stableMiddleWeakWindowBridgeImprovesBaseline": btc_duel_board.get("stableMiddleWeakWindowBridgeImprovesBaseline"),
        "stableMiddleWeakWindowBridgeOutcomeZh": btc_duel_board.get("stableMiddleWeakWindowBridgeOutcomeZh"),
        "stableMiddleTradeoffFollowupBestTradeoff": _dict(btc_duel_board.get("stableMiddleTradeoffFollowupBestTradeoff")),
        "stableMiddleTradeoffFollowupBestStrategyId": btc_duel_board.get("stableMiddleTradeoffFollowupBestStrategyId"),
        "stableMiddleTradeoffFollowupImprovesBridge": btc_duel_board.get("stableMiddleTradeoffFollowupImprovesBridge"),
        "stableMiddleTradeoffFollowupImprovesWeakWindow": btc_duel_board.get("stableMiddleTradeoffFollowupImprovesWeakWindow"),
        "stableMiddleTradeoffFollowupImprovesBaseline": btc_duel_board.get("stableMiddleTradeoffFollowupImprovesBaseline"),
        "stableMiddleTradeoffFollowupOutcomeZh": btc_duel_board.get("stableMiddleTradeoffFollowupOutcomeZh"),
        "nearLiveRepairBestStrategyId": btc_duel_board.get("nearLiveRepairBestStrategyId"),
        "nearLiveRepairImprovesBaseline": btc_duel_board.get("nearLiveRepairImprovesBaseline"),
        "nearLiveRepairOutcomeZh": btc_duel_board.get("nearLiveRepairOutcomeZh"),
        "nearLiveFollowupBestStrategyId": btc_duel_board.get("nearLiveFollowupBestStrategyId"),
        "nearLiveFollowupImprovesRepair": btc_duel_board.get("nearLiveFollowupImprovesRepair"),
        "nearLiveFollowupOutcomeZh": btc_duel_board.get("nearLiveFollowupOutcomeZh"),
        "nearLiveRefinementBestStrategyId": btc_duel_board.get("nearLiveRefinementBestStrategyId"),
        "nearLiveRefinementImprovesFollowup": btc_duel_board.get("nearLiveRefinementImprovesFollowup"),
        "nearLiveRefinementOutcomeZh": btc_duel_board.get("nearLiveRefinementOutcomeZh"),
        "nearLiveMiddleWindowFollowupBestStrategyId": btc_duel_board.get("nearLiveMiddleWindowFollowupBestStrategyId"),
        "nearLiveMiddleWindowFollowupImprovesFollowup": btc_duel_board.get("nearLiveMiddleWindowFollowupImprovesFollowup"),
        "nearLiveMiddleWindowFollowupOutcomeZh": btc_duel_board.get("nearLiveMiddleWindowFollowupOutcomeZh"),
        "nearLiveSignalRefinementBestStrategyId": btc_duel_board.get("nearLiveSignalRefinementBestStrategyId"),
        "nearLiveSignalRefinementImprovesContender": btc_duel_board.get("nearLiveSignalRefinementImprovesContender"),
        "nearLiveSignalRefinementOutcomeZh": btc_duel_board.get("nearLiveSignalRefinementOutcomeZh"),
        "nearLiveClusterRefinementBestStrategyId": btc_duel_board.get("nearLiveClusterRefinementBestStrategyId"),
        "nearLiveClusterRefinementImprovesContender": btc_duel_board.get("nearLiveClusterRefinementImprovesContender"),
        "nearLiveClusterRefinementOutcomeZh": btc_duel_board.get("nearLiveClusterRefinementOutcomeZh"),
        "nearLiveTempoRefinementBestStrategyId": btc_duel_board.get("nearLiveTempoRefinementBestStrategyId"),
        "nearLiveTempoRefinementImprovesContender": btc_duel_board.get("nearLiveTempoRefinementImprovesContender"),
        "nearLiveTempoRefinementOutcomeZh": btc_duel_board.get("nearLiveTempoRefinementOutcomeZh"),
        "nearLiveStoplossLadderRefinementBestStrategyId": btc_duel_board.get("nearLiveStoplossLadderRefinementBestStrategyId"),
        "nearLiveStoplossLadderRefinementImprovesContender": btc_duel_board.get("nearLiveStoplossLadderRefinementImprovesContender"),
        "nearLiveStoplossLadderRefinementOutcomeZh": btc_duel_board.get("nearLiveStoplossLadderRefinementOutcomeZh"),
        "nearLiveStoplossLadderFollowupMicroBestStrategyId": btc_duel_board.get("nearLiveStoplossLadderFollowupMicroBestStrategyId"),
        "nearLiveStoplossLadderFollowupMicroImprovesRefinement": btc_duel_board.get("nearLiveStoplossLadderFollowupMicroImprovesRefinement"),
        "nearLiveStoplossLadderFollowupMicroImprovesContender": btc_duel_board.get("nearLiveStoplossLadderFollowupMicroImprovesContender"),
        "nearLiveStoplossLadderFollowupMicroOutcomeZh": btc_duel_board.get("nearLiveStoplossLadderFollowupMicroOutcomeZh"),
        "nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId": btc_duel_board.get(
            "nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId"
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro": btc_duel_board.get(
            "nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro"
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupImprovesContender": btc_duel_board.get(
            "nearLiveStoplossLadderFollowupMicroFollowupImprovesContender"
        ),
        "nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh": btc_duel_board.get(
            "nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh"
        ),
        "nearLiveExitRefinementBestStrategyId": btc_duel_board.get("nearLiveExitRefinementBestStrategyId"),
        "nearLiveExitRefinementImprovesContender": btc_duel_board.get("nearLiveExitRefinementImprovesContender"),
        "nearLiveExitRefinementOutcomeZh": btc_duel_board.get("nearLiveExitRefinementOutcomeZh"),
        "nearLiveMiddleTradeoffBestStrategyId": btc_duel_board.get("nearLiveMiddleTradeoffBestStrategyId"),
        "nearLiveMiddleTradeoffImprovesContender": btc_duel_board.get("nearLiveMiddleTradeoffImprovesContender"),
        "nearLiveMiddleTradeoffOutcomeZh": btc_duel_board.get("nearLiveMiddleTradeoffOutcomeZh"),
        "nearLiveMiddleDensityLiftBestStrategyId": btc_duel_board.get("nearLiveMiddleDensityLiftBestStrategyId"),
        "nearLiveMiddleDensityLiftImprovesContender": btc_duel_board.get("nearLiveMiddleDensityLiftImprovesContender"),
        "nearLiveMiddleDensityLiftOutcomeZh": btc_duel_board.get("nearLiveMiddleDensityLiftOutcomeZh"),
        "duelSummaryZh": (
            btc_duel_board.get("recommendationZh")
            or "默认继续拿稳健锚点做主研究对象，先复验稳定 challenger，再把当前高收益 leader 作为第三顺位收益对照。"
        ),
        "recommendedFocusedRetestOrder": btc_context_recommended_order,
    }
    current_research_yield_frontier_strategy_id = (
        btc_duel_board.get("yieldFrontierStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_challenger_strategy_id = (
        btc_duel_board.get("nearLiveChallengerStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_repair_best_strategy_id = (
        btc_duel_board.get("nearLiveRepairBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_repair_improves_baseline = (
        btc_duel_board.get("nearLiveRepairImprovesBaseline")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_repair_outcome_zh = (
        btc_duel_board.get("nearLiveRepairOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_followup_best_strategy_id = (
        btc_duel_board.get("nearLiveFollowupBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_followup_improves_repair = (
        btc_duel_board.get("nearLiveFollowupImprovesRepair")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_followup_outcome_zh = (
        btc_duel_board.get("nearLiveFollowupOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_signal_refinement_best_strategy_id = (
        btc_duel_board.get("nearLiveSignalRefinementBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_signal_refinement_improves_contender = (
        btc_duel_board.get("nearLiveSignalRefinementImprovesContender")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_signal_refinement_outcome_zh = (
        btc_duel_board.get("nearLiveSignalRefinementOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_tempo_refinement_best_strategy_id = (
        btc_duel_board.get("nearLiveTempoRefinementBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_tempo_refinement_improves_contender = (
        btc_duel_board.get("nearLiveTempoRefinementImprovesContender")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_tempo_refinement_outcome_zh = (
        btc_duel_board.get("nearLiveTempoRefinementOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_best_strategy_id = (
        btc_duel_board.get("nearLiveStoplossLadderRefinementBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_improves_contender = (
        btc_duel_board.get("nearLiveStoplossLadderRefinementImprovesContender")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_outcome_zh = (
        btc_duel_board.get("nearLiveStoplossLadderRefinementOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_followup_micro_best_strategy_id = (
        btc_duel_board.get("nearLiveStoplossLadderFollowupMicroBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_followup_micro_improves_refinement = (
        btc_duel_board.get("nearLiveStoplossLadderFollowupMicroImprovesRefinement")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_followup_micro_improves_contender = (
        btc_duel_board.get("nearLiveStoplossLadderFollowupMicroImprovesContender")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_followup_micro_outcome_zh = (
        btc_duel_board.get("nearLiveStoplossLadderFollowupMicroOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_followup_micro_followup_best_strategy_id = (
        btc_duel_board.get("nearLiveStoplossLadderFollowupMicroFollowupBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_followup_micro_followup_improves_micro = (
        btc_duel_board.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesMicro")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_followup_micro_followup_improves_contender = (
        btc_duel_board.get("nearLiveStoplossLadderFollowupMicroFollowupImprovesContender")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_stoploss_ladder_followup_micro_followup_outcome_zh = (
        btc_duel_board.get("nearLiveStoplossLadderFollowupMicroFollowupOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_exit_refinement_best_strategy_id = (
        btc_duel_board.get("nearLiveExitRefinementBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_exit_refinement_improves_contender = (
        btc_duel_board.get("nearLiveExitRefinementImprovesContender")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_exit_refinement_outcome_zh = (
        btc_duel_board.get("nearLiveExitRefinementOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_refinement_best_strategy_id = (
        btc_duel_board.get("nearLiveRefinementBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_refinement_improves_followup = (
        btc_duel_board.get("nearLiveRefinementImprovesFollowup")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_refinement_outcome_zh = (
        btc_duel_board.get("nearLiveRefinementOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_middle_window_best_strategy_id = (
        btc_duel_board.get("nearLiveMiddleWindowFollowupBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_middle_window_improves_followup = (
        btc_duel_board.get("nearLiveMiddleWindowFollowupImprovesFollowup")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_middle_window_outcome_zh = (
        btc_duel_board.get("nearLiveMiddleWindowFollowupOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_cluster_refinement_best_strategy_id = (
        btc_duel_board.get("nearLiveClusterRefinementBestStrategyId")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_cluster_refinement_improves_contender = (
        btc_duel_board.get("nearLiveClusterRefinementImprovesContender")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    current_research_near_live_cluster_refinement_outcome_zh = (
        btc_duel_board.get("nearLiveClusterRefinementOutcomeZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    if not current_research_yield_frontier_strategy_id and closest_lane == "btcCryptoCfd":
        current_research_yield_frontier_strategy_id = comparison_cluster_canonical_strategy_id
    if not current_research_near_live_challenger_strategy_id and closest_lane == "btcCryptoCfd":
        current_research_near_live_challenger_strategy_id = comparison_cluster_canonical_strategy_id
    current_research_duel_summary_zh = (
        btc_duel_board.get("recommendationZh")
        if closest_lane == "btcCryptoCfd"
        else None
    )
    if not current_research_duel_summary_zh and closest_lane == "btcCryptoCfd":
        current_research_duel_summary_zh = (
            "默认继续拿稳健锚点做主研究对象，同时保留当前收益对照簇做第二对照。"
            if comparison_cluster_canonical_strategy_id
            else None
        )
    selected_release_ab_contender_seed_id = (
        mt5_ab_board.get("contenderSeedId")
        if selected_release_lane == "forexMt5"
        else None
    )
    if not selected_release_ab_contender_seed_id and selected_release_lane == "forexMt5":
        tie_with_seed_ids = _list(mt5_strongest.get("tieWithSeedIds"))
        selected_release_ab_contender_seed_id = tie_with_seed_ids[0] if tie_with_seed_ids else None
    if not selected_release_ab_contender_seed_id and selected_release_lane == "forexMt5":
        if len(mt5_top_strategies) > 1:
            selected_release_ab_contender_seed_id = mt5_top_strategies[1].get("seedId")
    if not selected_release_ab_contender_seed_id and selected_release_lane == "forexMt5":
        strongest_seed = mt5_strongest.get("seedId") or selected_strategy.get("seedId")
        tester_forward_action = next(
            (
                _dict(item)
                for item in action_queue
                if _dict(item).get("id") == "run_forex_ab_tester_forward"
            ),
            {},
        )
        ab_candidate_ids = _list(tester_forward_action.get("abCandidateIds"))
        derived_seed_ids = [
            _derive_seed_id_from_candidate_id(candidate_id, reference_seed_id=strongest_seed)
            for candidate_id in ab_candidate_ids
        ]
        selected_seed = selected_strategy.get("seedId")
        for derived_seed_id in derived_seed_ids:
            if (
                derived_seed_id
                and derived_seed_id != selected_seed
                and derived_seed_id != strongest_seed
            ):
                selected_release_ab_contender_seed_id = derived_seed_id
                break
        if not selected_release_ab_contender_seed_id:
            for derived_seed_id in derived_seed_ids:
                if derived_seed_id and derived_seed_id != strongest_seed:
                    selected_release_ab_contender_seed_id = derived_seed_id
                    break
    selected_release_ab_summary_zh = (
        mt5_ab_board.get("recommendationZh")
        if selected_release_lane == "forexMt5"
        else None
    )
    if not selected_release_ab_summary_zh and selected_release_lane == "forexMt5":
        strongest_seed = mt5_strongest.get("seedId") or selected_strategy.get("seedId")
        contender_seed = selected_release_ab_contender_seed_id
        if strongest_seed and contender_seed:
            strongest_label = _seed_short_label(strongest_seed) or str(strongest_seed)
            contender_label = _seed_short_label(contender_seed) or str(contender_seed)
            selected_release_ab_summary_zh = (
                f"默认继续把 {strongest_label} 视为暂时主冠军，"
                f"但任何 release 判断都必须等 {strongest_label}/{contender_label} 的隔离 tester-forward A/B 结果。"
            )
    queue_focus_ids = [
        _dict(item).get("id")
        for _, item in sorted_indexed_actions
        if _dict(item).get("lane") == closest_lane and isinstance(_dict(item).get("id"), str)
    ]
    lane_conflict = bool(
        isinstance(closest_lane, str)
        and isinstance(selected_release_lane, str)
        and closest_lane != selected_release_lane
    )
    return {
        "status": "PRIORITY_SUMMARY_READY",
        "closestResearchLaneNow": closest_lane,
        "currentResearchFocusLane": closest_lane,
        "currentResearchFocusStrategyId": focus_strategy_id,
        "currentResearchFocusClusterCanonicalStrategyId": focus_cluster_canonical_strategy_id or focus_strategy_id,
        "currentResearchFocusClusterAliasStrategyIds": focus_cluster_alias_strategy_ids,
        "currentResearchFocusClusterSummaryZh": focus_cluster_summary_zh,
        "currentResearchComparisonClusterCanonicalStrategyId": comparison_cluster_canonical_strategy_id,
        "currentResearchComparisonClusterAliasStrategyIds": comparison_cluster_alias_strategy_ids,
        "currentResearchComparisonClusterSummaryZh": comparison_cluster_summary_zh,
        "currentResearchComparisonClusterRecommendedResearchPriority": comparison_cluster_research_priority,
        "currentResearchComparisonClusterRecommendedResearchReasonZh": comparison_cluster_research_reason_zh,
        "currentResearchDuelSummaryZh": current_research_duel_summary_zh,
        "currentResearchNearLiveChallengerStrategyId": current_research_near_live_challenger_strategy_id,
        "currentResearchNearLiveRepairBestStrategyId": current_research_near_live_repair_best_strategy_id,
        "currentResearchNearLiveRepairImprovesBaseline": current_research_near_live_repair_improves_baseline,
        "currentResearchNearLiveRepairOutcomeZh": current_research_near_live_repair_outcome_zh,
        "currentResearchNearLiveFollowupBestStrategyId": current_research_near_live_followup_best_strategy_id,
        "currentResearchNearLiveFollowupImprovesRepair": current_research_near_live_followup_improves_repair,
        "currentResearchNearLiveFollowupOutcomeZh": current_research_near_live_followup_outcome_zh,
        "currentResearchNearLiveRefinementBestStrategyId": current_research_near_live_refinement_best_strategy_id,
        "currentResearchNearLiveRefinementImprovesFollowup": current_research_near_live_refinement_improves_followup,
        "currentResearchNearLiveRefinementOutcomeZh": current_research_near_live_refinement_outcome_zh,
        "currentResearchNearLiveTempoRefinementBestStrategyId": current_research_near_live_tempo_refinement_best_strategy_id,
        "currentResearchNearLiveTempoRefinementImprovesContender": current_research_near_live_tempo_refinement_improves_contender,
        "currentResearchNearLiveTempoRefinementOutcomeZh": current_research_near_live_tempo_refinement_outcome_zh,
        "currentResearchNearLiveStoplossLadderRefinementBestStrategyId": current_research_near_live_stoploss_ladder_best_strategy_id,
        "currentResearchNearLiveStoplossLadderRefinementImprovesContender": current_research_near_live_stoploss_ladder_improves_contender,
        "currentResearchNearLiveStoplossLadderRefinementOutcomeZh": current_research_near_live_stoploss_ladder_outcome_zh,
        "currentResearchNearLiveStoplossLadderFollowupMicroBestStrategyId": (
            current_research_near_live_stoploss_ladder_followup_micro_best_strategy_id
        ),
        "currentResearchNearLiveStoplossLadderFollowupMicroImprovesRefinement": (
            current_research_near_live_stoploss_ladder_followup_micro_improves_refinement
        ),
        "currentResearchNearLiveStoplossLadderFollowupMicroImprovesContender": (
            current_research_near_live_stoploss_ladder_followup_micro_improves_contender
        ),
        "currentResearchNearLiveStoplossLadderFollowupMicroOutcomeZh": (
            current_research_near_live_stoploss_ladder_followup_micro_outcome_zh
        ),
        "currentResearchNearLiveStoplossLadderFollowupMicroFollowupBestStrategyId": (
            current_research_near_live_stoploss_ladder_followup_micro_followup_best_strategy_id
        ),
        "currentResearchNearLiveStoplossLadderFollowupMicroFollowupImprovesMicro": (
            current_research_near_live_stoploss_ladder_followup_micro_followup_improves_micro
        ),
        "currentResearchNearLiveStoplossLadderFollowupMicroFollowupImprovesContender": (
            current_research_near_live_stoploss_ladder_followup_micro_followup_improves_contender
        ),
        "currentResearchNearLiveStoplossLadderFollowupMicroFollowupOutcomeZh": (
            current_research_near_live_stoploss_ladder_followup_micro_followup_outcome_zh
        ),
        "currentResearchNearLiveExitRefinementBestStrategyId": current_research_near_live_exit_refinement_best_strategy_id,
        "currentResearchNearLiveExitRefinementImprovesContender": current_research_near_live_exit_refinement_improves_contender,
        "currentResearchNearLiveExitRefinementOutcomeZh": current_research_near_live_exit_refinement_outcome_zh,
        "currentResearchNearLiveMiddleWindowBestStrategyId": current_research_near_live_middle_window_best_strategy_id,
        "currentResearchNearLiveMiddleWindowImprovesFollowup": current_research_near_live_middle_window_improves_followup,
        "currentResearchNearLiveMiddleWindowOutcomeZh": current_research_near_live_middle_window_outcome_zh,
        "currentResearchNearLiveClusterRefinementBestStrategyId": current_research_near_live_cluster_refinement_best_strategy_id,
        "currentResearchNearLiveClusterRefinementImprovesContender": current_research_near_live_cluster_refinement_improves_contender,
        "currentResearchNearLiveClusterRefinementOutcomeZh": current_research_near_live_cluster_refinement_outcome_zh,
        "currentResearchYieldFrontierStrategyId": current_research_yield_frontier_strategy_id,
        "currentResearchYieldFrontierClusterSummaryZh": yield_frontier_cluster_summary_zh,
        "btcContextSnapshot": btc_context_snapshot,
        "selectedLaneForSeparateReleaseReview": selected_release_lane,
        "selectedReleaseStrategyId": _dict(live_selection.get("selectedStrategy")).get("strategyId"),
        "selectedReleaseAbSummaryZh": selected_release_ab_summary_zh,
        "selectedReleaseAbContenderSeedId": selected_release_ab_contender_seed_id,
        "canProceedToSeparateReleaseLane": bool(execution_readiness_board.get("canProceedToSeparateReleaseLane")),
        "readyStrategyCountForSeparateReleaseLane": execution_readiness_board.get("readyStrategyCountForSeparateReleaseLane"),
        "laneConflictDetected": lane_conflict,
        "laneConflictZh": (
            "当前应先推进 BTC 研究动作；MT5 仍是独立 release 评审候选，但要等 tester gate 清空后再继续。"
            if lane_conflict
            else "当前研究焦点和独立 release 评审候选没有冲突。"
        ),
        "nextActionsOverall": next_actions,
        "currentLaneActionQueueIds": queue_focus_ids,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _decision_next_action_why(
    *,
    action_queue: list[dict[str, Any]],
    priority_summary: dict[str, Any],
) -> str | None:
    if not action_queue:
        return None
    first_action = _dict(action_queue[0])
    base = first_action.get("whyNowZh")
    if not isinstance(base, str) or not base:
        return None
    if first_action.get("lane") != "btcCryptoCfd":
        return base
    repair_outcome = priority_summary.get("currentResearchNearLiveRepairOutcomeZh")
    if not isinstance(repair_outcome, str) or not repair_outcome:
        return base
    if repair_outcome in base:
        return base
    return f"{base} {repair_outcome}"


def _recommended_action_queue(
    *,
    action_queue: list[dict[str, Any]],
    priority_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    current_lane = priority_summary.get("currentResearchFocusLane")
    release_lane = priority_summary.get("selectedLaneForSeparateReleaseReview")
    next_actions = [_dict(item) for item in _list(priority_summary.get("nextActionsOverall"))]
    next_action_map: dict[str, dict[str, Any]] = {
        str(_dict(item).get("id")): _dict(item)
        for item in next_actions
        if isinstance(_dict(item).get("id"), str)
    }
    legacy_next_action_map = {
        "refresh_btc_runtime_preflight_inputs": _dict(next_actions[0]) if len(next_actions) > 0 else {},
        "rerun_btc_tp_sl_optimizer": _dict(next_actions[1]) if len(next_actions) > 1 else {},
        "restore_live_mt5_dashboard_refresh": _dict(next_actions[2]) if len(next_actions) > 2 else {},
        "wait_for_tester_window": _dict(next_actions[2]) if len(next_actions) > 2 else {},
        "run_forex_ab_tester_forward": _dict(next_actions[2]) if len(next_actions) > 2 else {},
    }
    current_lane_ids = [
        item for item in _list(priority_summary.get("currentLaneActionQueueIds"))
        if isinstance(item, str)
    ]
    current_lane_id_rank = {action_id: index for index, action_id in enumerate(current_lane_ids)}
    stage_rank = {
        "runtime_preflight": 0,
        "focused_retest": 1,
        "candidate_scan": 2,
        "runtime_freshness": 3,
        "account_context": 4,
        "tester_lock": 5,
        "tester_window": 6,
        "tester_forward": 7,
        "release_review": 8,
        "target_evidence": 9,
    }

    def bucket(item: dict[str, Any]) -> str:
        action_id = item.get("id")
        lane = item.get("lane")
        if isinstance(action_id, str) and action_id in current_lane_id_rank:
            return "current_research_focus"
        if isinstance(lane, str) and lane == release_lane:
            return "release_lane_gate"
        if lane == "shared_release_lane":
            return "shared_release_gate"
        return "background"

    bucket_rank = {
        "current_research_focus": 0,
        "release_lane_gate": 1,
        "shared_release_gate": 2,
        "background": 3,
    }

    def sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
        action_id = str(item.get("id") or "")
        lane = item.get("lane")
        item_bucket = bucket(item)
        if item_bucket == "current_research_focus":
            lane_priority = current_lane_id_rank.get(action_id, 999)
        else:
            lane_priority = stage_rank.get(str(item.get("stage") or ""), 999)
        lane_bias = 0 if lane == current_lane else 1
        return (
            bucket_rank.get(item_bucket, 999),
            lane_priority,
            lane_bias,
            action_id,
        )

    ordered_items: list[dict[str, Any]] = []
    for index, item in enumerate(sorted((_dict(row) for row in action_queue), key=sort_key), start=1):
        enriched = dict(item)
        summary_context = next_action_map.get(str(enriched.get("id") or ""), {})
        if not summary_context:
            summary_context = legacy_next_action_map.get(str(enriched.get("id") or ""), {})
        item_bucket = bucket(enriched)
        enriched["priorityBucket"] = item_bucket
        enriched["recommendedNow"] = item_bucket == "current_research_focus"
        enriched["recommendedOrder"] = index
        if summary_context:
            if "whyNowZh" not in enriched:
                enriched["whyNowZh"] = summary_context.get("whyNowZh")
            if "evidenceSummaryZh" not in enriched:
                enriched["evidenceSummaryZh"] = summary_context.get("evidenceSummaryZh")
            if "evidenceSnapshot" not in enriched:
                enriched["evidenceSnapshot"] = _dict(summary_context.get("evidenceSnapshot"))
        enriched["orderSendAllowed"] = False
        enriched["mt5OrderSendAllowed"] = False
        ordered_items.append(enriched)
    return ordered_items


def _workstream_status(
    *,
    priority_summary: dict[str, Any],
    live_selection: dict[str, Any],
    tester_environment: dict[str, Any],
    action_queue: list[dict[str, Any]],
    execution_readiness_board: dict[str, Any],
) -> dict[str, Any]:
    research_lane = priority_summary.get("currentResearchFocusLane")
    release_lane = priority_summary.get("selectedLaneForSeparateReleaseReview") or live_selection.get("selectedLane")
    selected_strategy = _dict(live_selection.get("selectedStrategy"))
    queue_items = [_dict(item) for item in _list(action_queue)]
    research_actions = [
        item for item in queue_items
        if item.get("priorityBucket") == "current_research_focus"
    ]
    release_actions = [
        item for item in queue_items
        if item.get("priorityBucket") == "release_lane_gate"
    ]
    lane_snapshots = [_dict(item) for item in _list(execution_readiness_board.get("laneSnapshots"))]
    closure_queue = [_dict(item) for item in _list(execution_readiness_board.get("closureQueue"))]
    primary_closure_queue = [_dict(item) for item in _list(execution_readiness_board.get("primaryClosureQueue"))]
    deferred_closure_queue = [_dict(item) for item in _list(execution_readiness_board.get("deferredClosureQueue"))]
    research_snapshot = next((item for item in lane_snapshots if item.get("lane") == research_lane), {})
    release_snapshot = next((item for item in lane_snapshots if item.get("lane") == release_lane), {})
    if not closure_queue:
        lane_snapshot_order = sorted(
            lane_snapshots,
            key=lambda item: 0 if item.get("lane") == research_lane else 1,
        )
        for lane_snapshot in lane_snapshot_order:
            readiness_rows = _list(_dict(lane_snapshot.get("readinessChecklist")).get("rows"))
            for row in readiness_rows:
                closure_row = _dict(row)
                if closure_row.get("ok"):
                    continue
                closure_queue.append({
                    "priority": len(closure_queue) + 1,
                    "lane": lane_snapshot.get("lane"),
                    "focusStrategyId": lane_snapshot.get("focusStrategyId"),
                    "currentModeZh": lane_snapshot.get("currentModeZh"),
                    "checkId": closure_row.get("id"),
                    "labelZh": closure_row.get("labelZh"),
                    "sourceArtifact": closure_row.get("sourceArtifact"),
                    "evidenceKeyZh": closure_row.get("evidenceKeyZh"),
                    "dependencyCheckIds": _list(closure_row.get("dependencyCheckIds")),
                    "blockingDependencyCheckIds": [],
                    "isPrimaryActionable": True,
                    "nextActionZh": closure_row.get("nextActionZh"),
                    "blockerCount": lane_snapshot.get("blockerCount"),
                    "topBlockers": _list(lane_snapshot.get("topBlockers"))[:3],
                    "evidenceSummaryZh": lane_snapshot.get("evidenceSummaryZh"),
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                })
    if not primary_closure_queue and closure_queue:
        primary_closure_queue = [
            item for item in closure_queue
            if bool(_dict(item).get("isPrimaryActionable"))
        ] or [_dict(closure_queue[0])]
    if not deferred_closure_queue and closure_queue:
        deferred_closure_queue = [
            item for item in closure_queue
            if not bool(_dict(item).get("isPrimaryActionable"))
        ]

    tester_forward_action = next((
        item for item in queue_items
        if item.get("id") == "run_forex_ab_tester_forward"
    ), {})
    run_gate_blockers = _list(tester_environment.get("runGateBlockers"))
    can_run_tester = bool(tester_environment.get("canRunIsolatedTester"))
    can_proceed_release = bool(priority_summary.get("canProceedToSeparateReleaseLane"))

    research_lane_label = _lane_label_zh(research_lane)
    release_lane_label = _lane_label_zh(release_lane)

    if research_actions:
        research_status = "RESEARCH_ACTIVE"
        research_status_zh = f"当前优先推进 {research_lane_label} 动作。"
    else:
        research_status = "RESEARCH_IDLE"
        research_status_zh = "当前没有可继续推进的研究动作。"

    if can_proceed_release:
        release_status = "RELEASE_REVIEW_READY"
        release_status_zh = "可进入独立 release lane 评审。"
    elif can_run_tester:
        release_status = "RELEASE_WAITING_TESTER_FORWARD"
        release_status_zh = "release 候选已可进入 tester-forward。"
    else:
        release_status = "RELEASE_WAITING_GATE"
        release_status_zh = "release 候选仍在等待 tester gate 清空。"

    overall_mode = (
        "DUAL_TRACK_RESEARCH_ACTIVE_RELEASE_WAITING"
        if research_actions and not can_proceed_release
        else ("RELEASE_REVIEW_READY" if can_proceed_release else "REVIEW_QUEUE_IDLE")
    )
    overall_mode_zh = (
        (
            f"{research_lane_label} 当前优先推进；{release_lane_label} release 线仍等待 gate。"
            if research_lane != release_lane
            else f"{research_lane_label} 当前优先推进，但 release 线仍等待 residual gate 清空。"
        )
        if overall_mode == "DUAL_TRACK_RESEARCH_ACTIVE_RELEASE_WAITING"
        else (
            "至少一条候选已可进入独立 release lane 评审。"
            if overall_mode == "RELEASE_REVIEW_READY"
            else "当前没有新的研究或 release 动作。"
        )
    )
    if research_lane == "btcCryptoCfd":
        secondary_lane_context = {
            "lane": release_lane,
            "focusStrategyId": selected_strategy.get("strategyId"),
            "seedId": selected_strategy.get("seedId"),
            "abSummaryZh": priority_summary.get("selectedReleaseAbSummaryZh"),
            "abContenderSeedId": priority_summary.get("selectedReleaseAbContenderSeedId"),
            "status": release_status,
            "statusZh": release_status_zh,
            "blockers": run_gate_blockers[:5],
            "windowBriefing": _mt5_window_briefing(release_snapshot, tester_forward_action),
            "readinessChecklist": _dict(release_snapshot.get("readinessChecklist")),
            "nextActionZh": _dict(release_actions[0]).get("actionZh") if release_actions else None,
        }
    else:
        secondary_lane_context = _dict(priority_summary.get("btcContextSnapshot"))
    return {
        "status": "WORKSTREAM_STATUS_READY",
        "overallMode": overall_mode,
        "overallModeZh": overall_mode_zh,
        "closureQueue": closure_queue,
        "primaryClosureQueue": primary_closure_queue,
        "deferredClosureQueue": deferred_closure_queue,
        "closureSummaryZh": (
            execution_readiness_board.get("closureSummaryZh")
            or (
                f"当前待闭环 {len(closure_queue)} 项；"
                f"优先 lane={research_lane}；"
                f"首项={_dict(closure_queue[0]).get('checkId') if closure_queue else '无'}。"
            )
        ),
        "researchWorkstream": {
            "lane": research_lane,
            "focusStrategyId": priority_summary.get("currentResearchFocusStrategyId"),
            "focusClusterCanonicalStrategyId": priority_summary.get("currentResearchFocusClusterCanonicalStrategyId"),
            "focusClusterAliasStrategyIds": _list(priority_summary.get("currentResearchFocusClusterAliasStrategyIds")),
            "focusClusterSummaryZh": priority_summary.get("currentResearchFocusClusterSummaryZh"),
            "duelSummaryZh": priority_summary.get("currentResearchDuelSummaryZh"),
            "nearLiveChallengerStrategyId": priority_summary.get("currentResearchNearLiveChallengerStrategyId"),
            "nearLiveRepairBestStrategyId": priority_summary.get("currentResearchNearLiveRepairBestStrategyId"),
            "nearLiveRepairImprovesBaseline": priority_summary.get("currentResearchNearLiveRepairImprovesBaseline"),
            "nearLiveRepairOutcomeZh": priority_summary.get("currentResearchNearLiveRepairOutcomeZh"),
            "nearLiveFollowupBestStrategyId": priority_summary.get("currentResearchNearLiveFollowupBestStrategyId"),
            "nearLiveFollowupImprovesRepair": priority_summary.get("currentResearchNearLiveFollowupImprovesRepair"),
            "nearLiveFollowupOutcomeZh": priority_summary.get("currentResearchNearLiveFollowupOutcomeZh"),
            "nearLiveRefinementBestStrategyId": priority_summary.get("currentResearchNearLiveRefinementBestStrategyId"),
            "nearLiveRefinementImprovesFollowup": priority_summary.get("currentResearchNearLiveRefinementImprovesFollowup"),
            "nearLiveRefinementOutcomeZh": priority_summary.get("currentResearchNearLiveRefinementOutcomeZh"),
            "nearLiveMiddleWindowFollowupBestStrategyId": priority_summary.get("currentResearchNearLiveMiddleWindowBestStrategyId"),
            "nearLiveMiddleWindowFollowupImprovesFollowup": priority_summary.get("currentResearchNearLiveMiddleWindowImprovesFollowup"),
            "nearLiveMiddleWindowFollowupOutcomeZh": priority_summary.get("currentResearchNearLiveMiddleWindowOutcomeZh"),
            "yieldFrontierStrategyId": priority_summary.get("currentResearchYieldFrontierStrategyId"),
            "yieldFrontierClusterSummaryZh": priority_summary.get("currentResearchYieldFrontierClusterSummaryZh"),
            "comparisonClusterCanonicalStrategyId": priority_summary.get("currentResearchComparisonClusterCanonicalStrategyId"),
            "comparisonClusterAliasStrategyIds": _list(priority_summary.get("currentResearchComparisonClusterAliasStrategyIds")),
            "comparisonClusterSummaryZh": priority_summary.get("currentResearchComparisonClusterSummaryZh"),
            "comparisonClusterRecommendedResearchPriority": priority_summary.get("currentResearchComparisonClusterRecommendedResearchPriority"),
            "comparisonClusterRecommendedResearchReasonZh": priority_summary.get("currentResearchComparisonClusterRecommendedResearchReasonZh"),
            "status": research_status,
            "statusZh": research_status_zh,
            "recommendedActionIds": [
                item.get("id") for item in research_actions if isinstance(item.get("id"), str)
            ],
            "gateDiagnostics": _dict(_dict(research_actions[0]).get("gateDiagnostics")) if research_actions else {},
            "readinessChecklist": _dict(research_snapshot.get("readinessChecklist")),
            "nextActionZh": _dict(research_actions[0]).get("actionZh") if research_actions else None,
            "secondaryLaneContext": secondary_lane_context,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "releaseWorkstream": {
            "lane": release_lane,
            "focusStrategyId": selected_strategy.get("strategyId"),
            "seedId": selected_strategy.get("seedId"),
            "abSummaryZh": priority_summary.get("selectedReleaseAbSummaryZh"),
            "abContenderSeedId": priority_summary.get("selectedReleaseAbContenderSeedId"),
            "status": release_status,
            "statusZh": release_status_zh,
            "blockers": run_gate_blockers[:5],
            "queueCount": _dict(tester_forward_action).get("queueCount"),
            "abCandidateIds": _list(_dict(tester_forward_action).get("abCandidateIds")),
            "variantCandidateIds": _list(_dict(tester_forward_action).get("variantCandidateIds")),
            "queueSummaryZh": _dict(tester_forward_action).get("queueSummaryZh"),
            "gateDiagnostics": _dict(tester_forward_action).get("gateDiagnostics"),
            "windowBriefing": _mt5_window_briefing(release_snapshot, tester_forward_action),
            "readinessChecklist": _dict(release_snapshot.get("readinessChecklist")),
            "nextActionZh": _dict(release_actions[0]).get("actionZh") if release_actions else None,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        },
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _operator_command_deck(
    *,
    workstream_status: dict[str, Any],
    action_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    research = _dict(workstream_status.get("researchWorkstream"))
    recommended_ids = [
        item for item in _list(research.get("recommendedActionIds"))
        if isinstance(item, str)
    ]
    action_map = {
        str(_dict(item).get("id")): _dict(item)
        for item in _list(action_queue)
        if isinstance(_dict(item).get("id"), str)
    }
    steps: list[dict[str, Any]] = []
    flat_command_queue: list[dict[str, Any]] = []
    required_now_command_ids: list[str] = []
    required_now_flat_queue: list[dict[str, Any]] = []
    conditional_flat_queue: list[dict[str, Any]] = []
    for step_index, action_id in enumerate(recommended_ids, start=1):
        action = action_map.get(action_id, {})
        commands = [_dict(command) for command in _list(action.get("commands"))]
        steps.append({
            "step": step_index,
            "actionId": action_id,
            "lane": action.get("lane"),
            "actionZh": action.get("actionZh"),
            "recommendedOrder": action.get("recommendedOrder"),
            "blockers": _list(action.get("blockers")),
            "gateDiagnostics": _dict(action.get("gateDiagnostics")),
            "whyNowZh": action.get("whyNowZh"),
            "evidenceSummaryZh": action.get("evidenceSummaryZh"),
            "evidenceSnapshot": _dict(action.get("evidenceSnapshot")),
            "nextRequiredActionZh": action.get("nextRequiredActionZh"),
            "refreshOutcome": _dict(action.get("refreshOutcome")),
            "commands": commands,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })
        for command_index, command in enumerate(commands, start=1):
            command_id = command.get("id")
            if command.get("neededNow") and isinstance(command_id, str) and command_id not in required_now_command_ids:
                required_now_command_ids.append(command_id)
            flat_item = {
                "step": step_index,
                "stepActionId": action_id,
                "stepActionZh": action.get("actionZh"),
                "stepWhyNowZh": action.get("whyNowZh"),
                "stepEvidenceSummaryZh": action.get("evidenceSummaryZh"),
                "commandIndex": command_index,
                "id": command_id,
                "command": command.get("command"),
                "whenZh": command.get("whenZh"),
                "conditionStatus": command.get("conditionStatus"),
                "neededNow": bool(command.get("neededNow")),
                "conditionReasonZh": command.get("conditionReasonZh"),
                "sourceArtifactStatus": command.get("sourceArtifactStatus"),
                "orderSendAllowed": False,
                "mt5OrderSendAllowed": False,
                "writesMt5OrderRequest": False,
                "writesLivePreset": False,
            }
            flat_command_queue.append(flat_item)
            if command.get("neededNow"):
                required_now_flat_queue.append(flat_item)
            else:
                conditional_flat_queue.append(flat_item)
    return {
        "status": "OPERATOR_COMMAND_DECK_READY",
        "currentWorkstreamLane": research.get("lane"),
        "focusStrategyId": research.get("focusStrategyId"),
        "stepCount": len(steps),
        "flatCommandCount": len(flat_command_queue),
        "requiredNowFlatCommandCount": len(required_now_flat_queue),
        "conditionalFlatCommandCount": len(conditional_flat_queue),
        "requiredNowCommandIds": required_now_command_ids,
        "steps": steps,
        "flatCommandQueue": flat_command_queue,
        "requiredNowFlatCommandQueue": required_now_flat_queue,
        "conditionalFlatCommandQueue": conditional_flat_queue,
        "nextActionZh": research.get("nextActionZh"),
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def _next_hour_action_board(
    *,
    workstream_status: dict[str, Any],
    action_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    research = _dict(workstream_status.get("researchWorkstream"))
    release = _dict(workstream_status.get("releaseWorkstream"))
    gate = _dict(release.get("gateDiagnostics"))
    window_briefing = _dict(release.get("windowBriefing"))
    release_phase = str(window_briefing.get("phase") or "WINDOW_UNKNOWN")
    research_priority_rows = _readiness_priority_rows(_dict(research.get("readinessChecklist")))
    recommended_queue = [_dict(item) for item in _list(action_queue)]
    primary_action = recommended_queue[0] if recommended_queue else {}
    primary_lane = str(primary_action.get("lane") or "")

    if release_phase in {"PRE_WINDOW_FINAL_5_MIN", "PRE_WINDOW_FINAL_15_MIN"}:
        mt5_priority_check_ids = _list(window_briefing.get("finalSprintCheckIds"))
    elif release_phase == "IN_WINDOW":
        mt5_priority_check_ids = _list(window_briefing.get("highestLeveragePostWindowCheckIds"))
    else:
        mt5_priority_check_ids = _list(window_briefing.get("highestLeveragePreWindowCheckIds"))

    if primary_lane == "btcCryptoCfd":
        primary_action_check_ids = ["dashboard_fresh", "live_pilot_mode", "read_only_mode_off", "execution_enabled", "trade_allowed"]
    elif primary_lane == "forexMt5":
        primary_action_check_ids = mt5_priority_check_ids
    else:
        primary_action_check_ids = []

    steps: list[dict[str, Any]] = []
    if primary_action:
        steps.append({
            "priority": 1,
            "lane": primary_action.get("lane"),
            "actionId": primary_action.get("id"),
            "actionZh": primary_action.get("actionZh"),
            "whyNowZh": primary_action.get("whyNowZh"),
            "checkIds": primary_action_check_ids,
            "commandIds": [
                _dict(command).get("id")
                for command in _list(primary_action.get("commands"))
                if isinstance(_dict(command).get("id"), str) and bool(_dict(command).get("neededNow"))
            ],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })
    if release_phase in {"PRE_WINDOW_FINAL_5_MIN", "PRE_WINDOW_FINAL_15_MIN", "PRE_WINDOW_FINAL_30_MIN", "PRE_WINDOW_FINAL_HOUR"}:
        steps.append({
            "priority": 2,
            "lane": release.get("lane"),
            "actionId": "mt5_pre_window_clearance",
            "actionZh": (
                "在 tester window 打开前只盯 MT5 单个最高杠杆 gate。"
                if release_phase == "PRE_WINDOW_FINAL_5_MIN"
                else
                "在 tester window 打开前清 MT5 最后冲刺 gate。"
                if release_phase == "PRE_WINDOW_FINAL_15_MIN"
                else "在 tester window 打开前清 MT5 refresh/sensitive gate。"
            ),
            "whyNowZh": window_briefing.get("summaryZh"),
            "checkIds": (
                _list(window_briefing.get("finalSprintCheckIds"))
                if release_phase in {"PRE_WINDOW_FINAL_5_MIN", "PRE_WINDOW_FINAL_15_MIN"}
                else _list(window_briefing.get("preWindowCheckIds"))
            ),
            "commandIds": [],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })
        steps.append({
            "priority": 3,
            "lane": release.get("lane"),
            "actionId": "mt5_in_window_ab_first",
            "actionZh": "tester window 一开先跑 MT5 A/B 主对照。",
            "whyNowZh": (
                f"自动解除={', '.join(_list(window_briefing.get('autoClearCheckIds'))) or '无'}；"
                f"首批 A/B={', '.join(_list(window_briefing.get('abCandidateIds'))) or '无'}。"
            ),
            "checkIds": _list(window_briefing.get("inWindowCheckIds")),
            "commandIds": _list(window_briefing.get("abCandidateIds")),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })
    elif release_phase == "IN_WINDOW":
        steps.append({
            "priority": 2,
            "lane": release.get("lane"),
            "actionId": "mt5_in_window_residual_clearance",
            "actionZh": "tester window 已开，先清 MT5 开窗后最高杠杆 residual gate。",
            "whyNowZh": window_briefing.get("postWindowPrimarySummaryZh") or window_briefing.get("summaryZh"),
            "checkIds": _list(window_briefing.get("highestLeveragePostWindowCheckIds")),
            "commandIds": [],
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })
        steps.append({
            "priority": 3,
            "lane": release.get("lane"),
            "actionId": "mt5_in_window_ab_first",
            "actionZh": "residual gate 清掉后立即跑 MT5 A/B 主对照。",
            "whyNowZh": (
                f"窗口已开；首批 A/B={', '.join(_list(window_briefing.get('abCandidateIds'))) or '无'}；"
                f"当前仍受 {', '.join(_list(window_briefing.get('highestLeveragePostWindowCheckIds'))) or '无'} 约束。"
            ),
            "checkIds": _list(window_briefing.get("inWindowCheckIds")),
            "commandIds": _list(window_briefing.get("abCandidateIds")),
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
        })
    summary_parts = []
    if primary_action and not (primary_lane == "forexMt5" and release_phase == "IN_WINDOW"):
        summary_parts.append(
            "先补 BTC dashboard freshness / execution-mode 证据"
            if primary_lane == "btcCryptoCfd"
            else "先清 MT5 当前最高杠杆 residual gate"
            if primary_lane == "forexMt5"
            else "先处理当前第一优先 residual gate"
        )
    if release_phase in {"PRE_WINDOW_FINAL_5_MIN", "PRE_WINDOW_FINAL_15_MIN", "PRE_WINDOW_FINAL_30_MIN", "PRE_WINDOW_FINAL_HOUR"}:
        summary_parts.append("然后清 MT5 窗口前 refresh/sensitive gate")
        summary_parts.append("到点后先跑 G0093/G0102 A/B")
    elif release_phase == "IN_WINDOW":
        summary_parts.append("MT5 窗口已开，先清开窗后最高杠杆 residual gate")
        summary_parts.append("residual 转绿后立即跑 G0093/G0102 A/B")
    return {
        "status": "NEXT_HOUR_ACTION_BOARD_READY",
        "releasePhase": release_phase,
        "minutesUntilWindow": window_briefing.get("minutesUntilStart"),
        "nextWindowStartJstIso": gate.get("nextWindowStartJstIso"),
        "readinessNow": _dict(window_briefing.get("readinessNow")),
        "expectedReadinessAfterWindowOpen": _dict(window_briefing.get("expectedReadinessAfterWindowOpen")),
        "windowOpenGainCount": int(_num(window_briefing.get("windowOpenGainCount"))),
        "windowOpenGainRatio": float(_num(window_briefing.get("windowOpenGainRatio"))),
        "postWindowStillBlocked": bool(window_briefing.get("postWindowStillBlocked")),
        "residualAfterWindowOpenCheckIds": _list(window_briefing.get("residualAfterWindowOpenCheckIds")),
        "residualAfterWindowOpenCount": int(_num(window_briefing.get("residualAfterWindowOpenCount"))),
        "mt5PostWindowPrimaryCheckIds": _list(window_briefing.get("highestLeveragePostWindowCheckIds")),
        "mt5PostWindowPrimarySummaryZh": window_briefing.get("postWindowPrimarySummaryZh"),
        "windowOpenEffectZh": window_briefing.get("windowOpenEffectZh"),
        "windowOpenRealizedCheckIds": _list(window_briefing.get("windowOpenRealizedCheckIds")),
        "btcPriorityCheckIds": [str(row.get("id")) for row in research_priority_rows[:3]],
        "mt5PriorityCheckIds": mt5_priority_check_ids,
        "focusResearchLane": research.get("lane"),
        "focusReleaseLane": release.get("lane"),
        "steps": steps,
        "actions": steps,
        "summaryZh": "；".join(summary_parts) if summary_parts else "当前没有新的 next-hour 动作。",
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
    }


def build_ace_upgrade_action_plan(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    agent = runtime / "agent"
    pack = _resolve_candidate_pack(runtime, write=write)
    scout = _read_json(agent / "QuantGod_AceStrategyScout.json")
    scan = _read_json(agent / "QuantGod_BtcStrategyScanReport.json")
    tpsl = _read_json(agent / "QuantGod_TpSlOptimizerReport.json")
    summary = _read_json(agent / "QuantGod_SimTargetExecutionReviewSummary.json")
    promotion_gate = _read_json(agent / "QuantGod_ChampionPromotionGate.json")
    run_gate = _read_json(agent / "QuantGod_ChampionTesterRunGate.json")
    forward_request = _read_json(agent / "QuantGod_ChampionTesterForwardRequest.json")
    lock_draft = _read_json(agent / "QuantGod_ChampionTesterLockDraft.json")
    preflight = _read_json(agent / "QuantGod_LiveRuntimePreflightProbe.json")
    live_evidence_intake = _read_json(agent / "QuantGod_LiveEvidenceIntake.json")
    account_context = _read_json(runtime / "QuantGod_IsolatedTesterAccountContextStatus.json")
    process_evidence = _process_evidence()
    hfm_review = _hfm_review_artifacts(runtime)

    live_selection = _dict(pack.get("liveUpgradeSelection"))
    strategy_shortlist = _dict(pack.get("strategyShortlist"))
    execution_readiness_board = _dict(pack.get("executionReadinessBoard"))
    selected_strategy = _dict(live_selection.get("selectedStrategy"))
    lane_selections = _dict(live_selection.get("laneSelections"))
    if not lane_selections:
        forex_pack = _dict(pack.get("forexMt5"))
        forex_lane_selection = {
            "lane": "forexMt5",
            "seedId": forex_pack.get("seedId"),
            "strategyId": forex_pack.get("strategyId"),
            "strategyFamily": forex_pack.get("strategyFamily"),
            "status": forex_pack.get("status"),
            "contenderTieBreakRequired": bool(forex_pack.get("contenderTieBreakRequired")),
            "contenders": _list(forex_pack.get("contenders")),
            "testerVariantQueue": _list(forex_pack.get("testerVariantQueue")),
        }
        if live_selection.get("selectedLane") == "forexMt5":
            forex_lane_selection = {
                **forex_lane_selection,
                "seedId": selected_strategy.get("seedId") or forex_lane_selection.get("seedId"),
                "strategyId": selected_strategy.get("strategyId") or forex_lane_selection.get("strategyId"),
                "strategyFamily": selected_strategy.get("strategyFamily") or forex_lane_selection.get("strategyFamily"),
                "status": selected_strategy.get("status") or forex_lane_selection.get("status"),
                "contenderTieBreakRequired": bool(
                    selected_strategy.get("contenderTieBreakRequired")
                    if selected_strategy.get("contenderTieBreakRequired") is not None
                    else forex_lane_selection.get("contenderTieBreakRequired")
                ),
                "contenders": _list(selected_strategy.get("contenders")) or forex_lane_selection.get("contenders"),
                "testerVariantQueue": _list(selected_strategy.get("testerVariantQueue")) or forex_lane_selection.get("testerVariantQueue"),
            }
        lane_selections = {
            "forexMt5": forex_lane_selection,
            "btcCryptoCfd": _derive_btc_lane_selection(
                pack=pack,
                strategy_shortlist=strategy_shortlist,
                execution_readiness_board=execution_readiness_board,
            ),
        }
        live_selection["laneSelections"] = lane_selections
    elif not _dict(lane_selections.get("btcCryptoCfd")).get("strategyId"):
        lane_selections["btcCryptoCfd"] = _derive_btc_lane_selection(
            pack=pack,
            strategy_shortlist=strategy_shortlist,
            execution_readiness_board=execution_readiness_board,
        )
        live_selection["laneSelections"] = lane_selections
    target = _dict(summary.get("targetEvidence")) or _dict(pack.get("profitTarget"))
    target_reached = bool(target.get("targetReached"))
    run_gate_blockers = _unique(
        _list(_dict(run_gate.get("gate")).get("blockers"))
        or _list(_dict(promotion_gate.get("championTesterRunGate")).get("blockers"))
    )
    process_blockers = _unique(_list(process_evidence.get("blockers")))
    can_run_tester = bool(_dict(run_gate.get("decision")).get("canRunIsolatedTester"))
    lock_ready = bool(_dict(lock_draft.get("decision")).get("draftReadyForSeparateLockWriter") or lock_draft.get("ready"))
    prerequisites = _unique(_list(live_selection.get("upgradePrerequisites")))

    if not live_selection:
        status = "ACE_UPGRADE_SELECTION_MISSING"
        status_zh = "缺少 liveUpgradeSelection；需要先生成王牌候选包。"
    elif can_run_tester:
        status = "ACE_UPGRADE_TESTER_READY"
        status_zh = "王牌升级 tester 条件已满足，可交给隔离 tester-only runner。"
    elif any(code in run_gate_blockers for code in (
        "outside_strategy_tester_window",
        "isolated_tester_account_context_not_ready",
        "sensitive_account_context_sync_required",
    )):
        status = "ACE_UPGRADE_WAITING_TESTER_ENVIRONMENT"
        status_zh = "王牌升级对象已选定，等待 tester 窗口和隔离账户上下文。"
    else:
        status = "ACE_UPGRADE_REVIEW_GATED"
        status_zh = "王牌升级对象已选定，等待复验和独立 release lane。"

    action_queue = _build_action_queue(
        selected_lane=live_selection.get("selectedLane"),
        selected_seed=selected_strategy.get("seedId"),
        selected_strategy=selected_strategy.get("strategyId"),
        prerequisites=prerequisites,
        run_gate_blockers=run_gate_blockers,
        process_blockers=process_blockers,
        can_run_tester=can_run_tester,
        lock_ready=lock_ready,
        target_reached=target_reached,
        forward_request=forward_request,
        next_tester_window=_resolved_next_tester_window(_dict(run_gate.get("nextTesterWindow"))),
        strategy_shortlist=strategy_shortlist,
        preflight=preflight,
        live_evidence_intake=live_evidence_intake,
        hfm_review=hfm_review,
        run_gate=run_gate,
        account_context=account_context,
    )
    priority_summary = _priority_summary(
        strategy_shortlist=strategy_shortlist,
        execution_readiness_board=execution_readiness_board,
        live_selection=live_selection,
        action_queue=action_queue,
    )
    recommended_action_queue = _recommended_action_queue(
        action_queue=action_queue,
        priority_summary=priority_summary,
    )
    priority_summary["recommendedActionQueueIds"] = [
        _dict(item).get("id") for item in recommended_action_queue if isinstance(_dict(item).get("id"), str)
    ]
    tester_environment = {
        "runGateStatus": run_gate.get("status"),
        "runGateBlockers": run_gate_blockers,
        "processBlockers": process_blockers,
        "canRunIsolatedTester": can_run_tester,
        "nextTesterWindow": _resolved_next_tester_window(_dict(run_gate.get("nextTesterWindow"))),
        "liveSession": {
            "status": _dict(_dict(run_gate.get("gate")).get("liveSession")).get("status"),
            "ok": bool(_dict(_dict(run_gate.get("gate")).get("liveSession")).get("ok")),
            "openTradeCount": _dict(_dict(run_gate.get("gate")).get("liveSession")).get("openTradeCount"),
            "marginInUse": _dict(_dict(run_gate.get("gate")).get("liveSession")).get("marginInUse"),
            "accountNumber": _dict(_dict(run_gate.get("gate")).get("liveSession")).get("accountNumber"),
            "server": _dict(_dict(run_gate.get("gate")).get("liveSession")).get("server"),
        },
        "accountContext": {
            "ready": bool(account_context.get("ready")),
            "mode": account_context.get("mode"),
            "missingTarget": account_context.get("missingTarget") or [],
            "sensitiveAccountContextSyncRequired": bool(account_context.get("sensitiveAccountContextSyncRequired")),
            "separateSyncReview": _dict(account_context.get("separateSyncReview")),
        },
        "lockDraft": {
            "status": lock_draft.get("status"),
            "readyForSeparateLockWriter": lock_ready,
            "lockFileWritten": False,
        },
        "processEvidence": process_evidence,
    }
    workstream_status = _workstream_status(
        priority_summary=priority_summary,
        live_selection=live_selection,
        tester_environment=tester_environment,
        action_queue=recommended_action_queue,
        execution_readiness_board=execution_readiness_board,
    )
    next_hour_action_board = _next_hour_action_board(
        workstream_status=workstream_status,
        action_queue=recommended_action_queue,
    )
    operator_command_deck = _operator_command_deck(
        workstream_status=workstream_status,
        action_queue=recommended_action_queue,
    )
    pack_source_freshness = _pack_source_freshness_diagnostics(
        pack=pack,
        scout=scout,
        scan=scan,
        tpsl=tpsl,
        run_gate=run_gate,
        preflight=preflight,
    )
    source_artifact_summaries = _source_artifact_summaries(
        runtime=runtime,
        agent=agent,
        pack=pack,
        summary=summary,
        promotion_gate=promotion_gate,
        run_gate=run_gate,
        forward_request=forward_request,
        lock_draft=lock_draft,
        preflight=preflight,
        live_evidence_intake=live_evidence_intake,
        account_context=account_context,
    )

    report = {
        "ok": True,
        "schema": SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "status": status,
        "statusZh": status_zh,
        "targetEvidence": {
            "targetReached": target_reached,
            "combinedVerifiedUsdProfit": target.get("combinedVerifiedUsdProfit"),
            "combinedTargetStatus": target.get("combinedTargetStatus") or target.get("status"),
        },
        "selectedUpgrade": {
            "status": live_selection.get("status"),
            "selectedLane": live_selection.get("selectedLane"),
            "seedId": selected_strategy.get("seedId"),
            "strategyId": selected_strategy.get("strategyId"),
            "strategyFamily": selected_strategy.get("strategyFamily"),
            "contenderTieBreakRequired": bool(selected_strategy.get("contenderTieBreakRequired")),
            "laneSelections": _dict(live_selection.get("laneSelections")),
            "excludedAceCandidates": _list(live_selection.get("excludedAceCandidates")),
            "upgradePrerequisites": prerequisites,
        },
        "testerEnvironment": tester_environment,
        "prioritySummary": priority_summary,
        "workstreamStatus": workstream_status,
        "nextHourActionBoard": next_hour_action_board,
        "operatorCommandDeck": operator_command_deck,
        "packSourceFreshnessDiagnostics": pack_source_freshness,
        "actionQueue": recommended_action_queue,
        "decision": {
            "safeAutomationCanContinue": True,
            "nextActionZh": (
                _dict(_list(recommended_action_queue)[0]).get("actionZh")
                if _list(recommended_action_queue)
                else "按 actionQueue 自动刷新窗口、账户上下文预检、tester gate 和 A/B 复验证据；当前不写订单。"
            ),
            "nextActionWhyZh": _decision_next_action_why(
                action_queue=recommended_action_queue,
                priority_summary=priority_summary,
            ),
            "nextActionEvidenceSummaryZh": (
                _dict(_list(recommended_action_queue)[0]).get("evidenceSummaryZh")
                if _list(recommended_action_queue)
                else None
            ),
            "nextActionDirectExecutionBlockerCode": (
                _dict(_list(recommended_action_queue)[0]).get("directExecutionBlockerCode")
                if _list(recommended_action_queue)
                else None
            ),
            "nextActionDirectExecutionBlockerDetailZh": (
                _dict(_list(recommended_action_queue)[0]).get("directExecutionBlockerDetailZh")
                if _list(recommended_action_queue)
                else None
            ),
            "nextActionPermissionChainHealthy": (
                _dict(_list(recommended_action_queue)[0]).get("permissionChainHealthy")
                if _list(recommended_action_queue)
                else None
            ),
            "nextActionRefreshOutcome": (
                _dict(_list(recommended_action_queue)[0]).get("refreshOutcome")
                if _list(recommended_action_queue)
                else None
            ),
            "currentResearchFocusLane": priority_summary.get("currentResearchFocusLane"),
            "currentResearchFocusStrategyId": priority_summary.get("currentResearchFocusStrategyId"),
            "selectedLaneForSeparateReleaseReview": priority_summary.get("selectedLaneForSeparateReleaseReview"),
            "canProceedToSeparateReleaseLane": bool(priority_summary.get("canProceedToSeparateReleaseLane")),
            "overallMode": workstream_status.get("overallMode"),
            "overallModeZh": workstream_status.get("overallModeZh"),
            "packSnapshotUpToDate": bool(pack_source_freshness.get("packSnapshotUpToDate")),
            "packSourceFreshnessSummaryZh": pack_source_freshness.get("summaryZh"),
            "nextHourSummaryZh": next_hour_action_board.get("summaryZh"),
            "recommendedCommandIds": [
                _dict(item).get("id")
                for item in _list(operator_command_deck.get("flatCommandQueue"))
                if isinstance(_dict(item).get("id"), str)
            ],
            "requiredNowCommandIds": [
                item for item in _list(operator_command_deck.get("requiredNowCommandIds"))
                if isinstance(item, str)
            ],
            "canRunTesterHere": False,
            "canPromoteToLiveHere": False,
            "orderSendAllowed": False,
            "mt5OrderSendAllowed": False,
            "writesTesterLock": False,
            "copiesAccountContext": False,
            "writesMt5OrderRequest": False,
            "writesLivePreset": False,
        },
        "sourceArtifacts": {
            "aceExecutionCandidatePack": str(agent / "QuantGod_AceExecutionCandidatePack.json"),
            "simTargetExecutionReviewSummary": str(agent / "QuantGod_SimTargetExecutionReviewSummary.json"),
            "championPromotionGate": str(agent / "QuantGod_ChampionPromotionGate.json"),
            "championTesterRunGate": str(agent / "QuantGod_ChampionTesterRunGate.json"),
            "championTesterForwardRequest": str(agent / "QuantGod_ChampionTesterForwardRequest.json"),
            "championTesterLockDraft": str(agent / "QuantGod_ChampionTesterLockDraft.json"),
            "liveRuntimePreflightProbe": str(agent / "QuantGod_LiveRuntimePreflightProbe.json"),
            "liveEvidenceIntake": str(agent / "QuantGod_LiveEvidenceIntake.json"),
            "isolatedTesterAccountContextStatus": str(runtime / "QuantGod_IsolatedTesterAccountContextStatus.json"),
        },
        "sourceArtifactSummaries": source_artifact_summaries,
        "sourceArtifactSummaryZh": _source_artifact_summary_zh(source_artifact_summaries),
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, report)
    return report


def read_ace_upgrade_action_plan(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    payload = _read_json(runtime / REPORT_PATH)
    if payload and not _saved_plan_stale(runtime, payload):
        return payload
    return build_ace_upgrade_action_plan(runtime, write=bool(payload))
