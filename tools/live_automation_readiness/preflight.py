from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .approval_context import operator_approval_json_for_refresh
from .dry_run_replay import build_dry_run_intent_replay, read_dry_run_intent_replay
from .execution_lane import build_live_execution_lane_spec, read_live_execution_lane_spec
from .schema import (
    RUNTIME_PREFLIGHT_SCHEMA_VERSION,
    SAFETY,
    assert_no_execution_flags,
    runtime_preflight_path,
    utc_now_iso,
)

try:  # pragma: no cover - import style differs when called as a standalone script.
    from tools.mt5_readonly_bridge import ea_snapshot_max_age_seconds, runtime_dir_candidates
except Exception:  # pragma: no cover
    try:
        from mt5_readonly_bridge import ea_snapshot_max_age_seconds, runtime_dir_candidates
    except Exception:  # pragma: no cover
        ea_snapshot_max_age_seconds = None
        runtime_dir_candidates = None


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, reason_zh: str, value: Any = None) -> dict[str, Any]:
    row = {"code": code, "reasonZh": reason_zh}
    if value not in (None, ""):
        row["value"] = value
    return row


_EXECUTION_MODE_BLOCKER_CODES = {
    "MT5_LIVE_PILOT_MODE_FIELD_MISSING",
    "MT5_LIVE_PILOT_MODE_NOT_CONFIRMED",
    "MT5_READ_ONLY_MODE_FIELD_MISSING",
    "MT5_READ_ONLY_MODE_STILL_ACTIVE",
    "MT5_EXECUTION_ENABLED_FIELD_MISSING",
    "MT5_EXECUTION_NOT_ENABLED_FOR_PILOT",
    "MT5_TRADE_ALLOWED_FIELD_MISSING",
    "MT5_TRADE_ALLOWED_NOT_CONFIRMED",
}


def _truthy(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "enabled", "active"}:
            return True
        if text in {"0", "false", "no", "off", "disabled", "inactive"}:
            return False
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return None, str(exc)
    return (payload, "") if isinstance(payload, dict) else (None, "json_root_is_not_object")


def _repo_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime"


def _dashboard_candidates(runtime_dir: Path) -> list[Path]:
    runtime_dir = Path(runtime_dir)
    candidates = [
        runtime_dir / "QuantGod_Dashboard.json",
        runtime_dir / "mac_import" / "mt5_files_snapshot" / "QuantGod_Dashboard.json",
        runtime_dir.parent / "Dashboard" / "QuantGod_Dashboard.json",
    ]
    for env_name in ("QG_HFM_CRYPTO_RUNTIME_DIR", "QG_MT5_SECONDARY_FILES_DIR"):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw).expanduser() / "QuantGod_Dashboard.json")
    secondary_root = os.environ.get("QG_MT5_SECONDARY_ROOT")
    if secondary_root:
        candidates.append(Path(secondary_root).expanduser() / "MQL5" / "Files" / "QuantGod_Dashboard.json")
    secondary_prefix = os.environ.get("QG_MT5_SECONDARY_WINE_PREFIX")
    if secondary_prefix:
        candidates.append(
            Path(secondary_prefix).expanduser()
            / "drive_c"
            / "Program Files"
            / "MetaTrader 5"
            / "MQL5"
            / "Files"
            / "QuantGod_Dashboard.json"
        )
    include_global = runtime_dir.resolve() == _repo_runtime_dir().resolve()
    include_global = include_global or str(os.environ.get("QG_LIVE_PREFLIGHT_INCLUDE_GLOBAL_MT5", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if include_global:
        candidates.append(
            Path.home()
            / "Library"
            / "Application Support"
            / "net.metaquotes.wine.metatrader5-live16"
            / "drive_c"
            / "Program Files"
            / "MetaTrader 5"
            / "MQL5"
            / "Files"
            / "QuantGod_Dashboard.json"
        )
    if include_global and callable(runtime_dir_candidates):
        candidates.extend(Path(item) / "QuantGod_Dashboard.json" for item in runtime_dir_candidates())
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate.expanduser())
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate.expanduser())
    return unique


def _read_dashboard_snapshot(runtime_dir: Path) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    found: list[tuple[float, Path, dict[str, Any]]] = []
    parse_errors: list[dict[str, Any]] = []
    checked: list[str] = []
    for candidate in _dashboard_candidates(runtime_dir):
        checked.append(str(candidate))
        if not candidate.exists() or not candidate.is_file():
            continue
        payload, error = _read_json(candidate)
        if payload is None:
            parse_errors.append({"path": str(candidate), "error": error})
            continue
        found.append((candidate.stat().st_mtime, candidate, payload))
    if not found:
        source = {
            "found": False,
            "path": "",
            "checked": checked,
            "parseErrors": parse_errors,
            "fresh": False,
            "ageSeconds": None,
            "maxAgeSeconds": _max_age_seconds(),
        }
        blockers = [_blocker("MT5_DASHBOARD_SNAPSHOT_MISSING", "没有找到 QuantGod_Dashboard.json 运行时快照。")]
        blockers.extend(_blocker("MT5_DASHBOARD_SNAPSHOT_PARSE_ERROR", "发现快照但解析失败。", row) for row in parse_errors)
        return None, source, blockers
    _, path, payload = sorted(found, key=lambda item: item[0], reverse=True)[0]
    stat = path.stat()
    age = max(0.0, time.time() - float(stat.st_mtime))
    max_age = _max_age_seconds()
    fresh = age <= max_age
    source = {
        "found": True,
        "path": str(path),
        "checked": checked,
        "mtimeIso": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        "fresh": fresh,
        "ageSeconds": round(age, 3),
        "maxAgeSeconds": max_age,
        "parseErrors": parse_errors,
    }
    blockers = []
    if not fresh:
        blockers.append(_blocker("MT5_DASHBOARD_SNAPSHOT_STALE", "QuantGod_Dashboard.json 运行时快照已过期。", source["ageSeconds"]))
    return payload, source, blockers


def _max_age_seconds() -> int:
    if callable(ea_snapshot_max_age_seconds):
        try:
            return max(300, int(ea_snapshot_max_age_seconds()))
        except Exception:
            pass
    return 300


def _runtime_block(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = _safe_dict(snapshot)
    return _safe_dict(snapshot.get("runtime"))


def _account_block(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return _safe_dict(_safe_dict(snapshot).get("account"))


def _symbol_rows(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    snapshot = _safe_dict(snapshot)
    rows = [row for row in _safe_list(snapshot.get("symbols")) if isinstance(row, dict)]
    symbol = snapshot.get("symbol") or snapshot.get("brokerSymbol")
    if symbol and not rows:
        rows.append({"symbol": symbol})
    return rows


def _sidecar_symbol_rows(runtime_dir: Path, snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    specs = _safe_dict(_safe_dict(snapshot).get("hfmCryptoSymbolSpecs"))
    rows.extend(row for row in _safe_list(specs.get("symbols")) if isinstance(row, dict))
    for path in (
        Path(runtime_dir) / "hfm_crypto" / "QuantGod_HFMCryptoSymbolSpecs.json",
        Path(runtime_dir) / "hfm_crypto" / "QuantGod_HFMCryptoContractSpecExport.json",
    ):
        if not path.exists() or not path.is_file():
            continue
        payload, _ = _read_json(path)
        if not isinstance(payload, dict):
            continue
        for row in _safe_list(payload.get("symbols")):
            if isinstance(row, dict):
                rows.append(row)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = "|".join(str(row.get(field) or "") for field in ("brokerSymbol", "symbol", "canonicalSymbol", "name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _hfm_crypto_runtime_probe_paths(runtime_dir: Path) -> list[Path]:
    runtime_dir = Path(runtime_dir)
    roots: list[Path] = [
        runtime_dir / "hfm_crypto",
        runtime_dir,
    ]
    for env_name in ("QG_HFM_CRYPTO_RUNTIME_DIR", "QG_MT5_SECONDARY_FILES_DIR"):
        raw = os.environ.get(env_name)
        if raw:
            roots.append(Path(raw).expanduser())
    secondary_root = os.environ.get("QG_MT5_SECONDARY_ROOT")
    if secondary_root:
        roots.append(Path(secondary_root).expanduser() / "MQL5" / "Files")
    secondary_prefix = os.environ.get("QG_MT5_SECONDARY_WINE_PREFIX")
    if secondary_prefix:
        roots.append(
            Path(secondary_prefix).expanduser()
            / "drive_c"
            / "Program Files"
            / "MetaTrader 5"
            / "MQL5"
            / "Files"
        )
    include_default_live16 = runtime_dir.resolve() == _repo_runtime_dir().resolve()
    include_default_live16 = include_default_live16 or str(
        os.environ.get("QG_LIVE_PREFLIGHT_INCLUDE_GLOBAL_MT5", "")
    ).lower() in {"1", "true", "yes", "on"}
    if include_default_live16:
        roots.append(
            Path.home()
            / "Library"
            / "Application Support"
            / "net.metaquotes.wine.metatrader5-live16"
            / "drive_c"
            / "Program Files"
            / "MetaTrader 5"
            / "MQL5"
            / "Files"
        )

    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / "QuantGod_HFMCryptoRuntimeProbe.json")
        candidates.append(root / "hfm_crypto" / "QuantGod_HFMCryptoRuntimeProbe.json")
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate.expanduser())
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate.expanduser())
    return unique


def _runtime_probe_rank(row: dict[str, Any]) -> tuple[int, float, int]:
    fresh = _truthy(row.get("_runtimeProbeFresh"))
    age = _number(row.get("_runtimeProbeAgeSeconds"))
    age_value = age if age is not None else float("inf")
    source = str(row.get("_runtimeProbeSource") or "")
    source_rank = 0 if source == "dashboard" else 1
    return (0 if fresh is True else 1, age_value, source_rank)


def _runtime_probe_symbol_rows(runtime_dir: Path, snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    probe = _safe_dict(_safe_dict(snapshot).get("hfmCryptoRuntimeProbe"))
    for row in _safe_list(probe.get("symbols")):
        if isinstance(row, dict):
            rows.append({
                **row,
                "_runtimeProbeSource": "dashboard",
                "_runtimeProbeFresh": True,
                "_runtimeProbeAgeSeconds": 0.0,
            })
    for path in _hfm_crypto_runtime_probe_paths(runtime_dir):
        if not path.exists() or not path.is_file():
            continue
        payload, _ = _read_json(path)
        if not isinstance(payload, dict):
            continue
        try:
            age = max(0.0, time.time() - float(path.stat().st_mtime))
        except OSError:
            age = _max_age_seconds() + 1
        fresh = age <= _max_age_seconds()
        for row in _safe_list(payload.get("symbols")):
            if isinstance(row, dict):
                rows.append({
                    **row,
                    "_runtimeProbeSource": str(path),
                    "_runtimeProbeFresh": fresh,
                    "_runtimeProbeAgeSeconds": round(age, 3),
                })
    unique: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for row in rows:
        key = "|".join(str(row.get(field) or "") for field in ("brokerSymbol", "symbol", "canonicalSymbol", "name"))
        if key not in seen:
            seen[key] = len(unique)
            unique.append(row)
            continue
        current_index = seen[key]
        if _runtime_probe_rank(row) < _runtime_probe_rank(unique[current_index]):
            unique[current_index] = row
    return unique


def _symbol_names(rows: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for row in rows:
        for key in ("symbol", "brokerSymbol", "name", "canonicalSymbol"):
            value = str(row.get(key) or "").strip()
            if value:
                names.add(value)
                names.add(value.replace("#", ""))
    return names


def _symbol_spread(row: dict[str, Any]) -> float | None:
    for key in ("spreadPoints", "spread", "spreadPips"):
        value = _number(row.get(key))
        if value is not None:
            return value
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    if bid is not None and ask is not None and ask >= bid:
        return ask - bid
    return None


def _sidecar_live_spread(row: dict[str, Any]) -> float | None:
    tick_ok = _truthy(row.get("tickOk"))
    fresh = _truthy(row.get("_runtimeProbeFresh"))
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    if fresh is True and tick_ok is True and bid is not None and ask is not None and ask > bid:
        return ask - bid
    return None


def _row_for_symbol(rows: list[dict[str, Any]], broker_symbol: str, canonical_symbol: str) -> dict[str, Any] | None:
    aliases = {broker_symbol, canonical_symbol, broker_symbol.replace("#", ""), canonical_symbol.replace("#", "")}
    aliases = {item for item in aliases if item}
    for row in rows:
        values = {
            str(row.get("symbol") or ""),
            str(row.get("brokerSymbol") or ""),
            str(row.get("name") or ""),
            str(row.get("canonicalSymbol") or ""),
        }
        values.update(value.replace("#", "") for value in list(values))
        if aliases.intersection(values):
            return row
    return None


def _kill_switch_state(snapshot: dict[str, Any] | None) -> tuple[bool, bool, Any]:
    snapshot = _safe_dict(snapshot)
    runtime = _runtime_block(snapshot)
    for key in ("pilotKillSwitch", "killSwitchActive", "killSwitch", "kill_switch_active"):
        if key in runtime:
            value = _truthy(runtime.get(key))
            if value is not None:
                return True, not value, runtime.get(key)
        if key in snapshot:
            value = _truthy(snapshot.get(key))
            if value is not None:
                return True, not value, snapshot.get(key)
    return False, False, None


def _permission_layers(runtime: dict[str, Any], symbols: list[dict[str, Any]]) -> dict[str, Any]:
    focus_symbol = symbols[0] if symbols else {}
    focus_symbol_trade_allowed_raw = runtime.get(
        "focusSymbolTradeAllowed",
        focus_symbol.get("entryTradeAllowed", focus_symbol.get("tradeEnabled")),
    )
    return {
        "terminalConnected": _truthy(runtime.get("terminalConnected", runtime.get("connected"))),
        "accountAuthorized": _truthy(runtime.get("accountAuthorized")),
        "terminalTradeAllowed": _truthy(runtime.get("terminalTradeAllowed")),
        "programTradeAllowed": _truthy(runtime.get("programTradeAllowed")),
        "accountTradeAllowed": _truthy(runtime.get("accountTradeAllowed")),
        "accountExpertTradeAllowed": _truthy(runtime.get("accountExpertTradeAllowed")),
        "focusSymbolTradeAllowed": _truthy(focus_symbol_trade_allowed_raw),
        "focusSymbolTradeAllowedRaw": focus_symbol_trade_allowed_raw,
        "focusSymbolTradeMode": runtime.get("focusSymbolTradeMode", focus_symbol.get("tradeMode", "")),
        "tradePermissionBlocker": runtime.get("tradePermissionBlocker", ""),
    }


def _permission_layers_passed(layers: dict[str, Any]) -> bool:
    required = (
        "terminalConnected",
        "accountAuthorized",
        "terminalTradeAllowed",
        "programTradeAllowed",
        "accountTradeAllowed",
        "accountExpertTradeAllowed",
        "focusSymbolTradeAllowed",
    )
    return all(layers.get(key) is True for key in required) and str(layers.get("focusSymbolTradeMode") or "").upper() in {
        "FULL",
        "SYMBOL_TRADE_MODE_FULL",
        "4",
    }


def _execution_gate_diagnostics(
    *,
    live_pilot_raw: Any,
    read_only_raw: Any,
    execution_enabled_raw: Any,
    trade_allowed_raw: Any,
    runtime: dict[str, Any],
    permission_layers: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    trade_status = runtime.get("tradeStatus", "")
    permission_blocker = str(permission_layers.get("tradePermissionBlocker") or "")
    permission_layers_ok = _permission_layers_passed(permission_layers)
    trade_allowed_detail = (
        "MT5 terminal/account/program/symbol 交易权限均已通过；当前 composite tradeAllowed=false 的直接阻塞为 "
        f"{permission_blocker}。"
        if permission_layers_ok and permission_blocker
        else "MT5 terminal/account/program/symbol 任一权限仍未全部证明为 true。"
    )
    return {
        "livePilotMode": {
            "layer": "EA live-pilot mode",
            "rawValue": live_pilot_raw,
            "detailZh": f"EA runtime 仍未确认 livePilotMode=true；当前 tradeStatus={trade_status or 'UNKNOWN'}。",
        },
        "readOnlyMode": {
            "layer": "EA read-only fuse",
            "rawValue": read_only_raw,
            "detailZh": f"EA runtime readOnlyMode 仍为 true；当前 tradePermissionBlocker={permission_blocker or 'UNKNOWN'}。",
        },
        "executionEnabled": {
            "layer": "EA execution switch",
            "rawValue": execution_enabled_raw,
            "detailZh": "EA runtime executionEnabled=false；当前只做 shadow/review，不允许写 MT5 request 或调用 broker。",
        },
        "tradeAllowed": {
            "layer": "MT5 permission composite",
            "rawValue": trade_allowed_raw,
            "detailZh": trade_allowed_detail,
            "permissionLayers": permission_layers,
        },
    }


def _dashboard_summary(snapshot: dict[str, Any] | None, source: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_block(snapshot)
    snapshot_dict = _safe_dict(snapshot)
    account = _account_block(snapshot)
    symbols = _symbol_rows(snapshot)
    kill_present, kill_ok, kill_value = _kill_switch_state(snapshot)
    read_only_raw = runtime.get("readOnlyMode", snapshot_dict.get("readOnlyMode"))
    execution_enabled_raw = runtime.get("executionEnabled", snapshot_dict.get("executionEnabled"))
    live_pilot_raw = runtime.get("livePilotMode", snapshot_dict.get("livePilotMode"))
    trade_allowed_raw = runtime.get("tradeAllowed", snapshot_dict.get("tradeAllowed"))
    permission_layers = _permission_layers(runtime, symbols)
    return {
        "found": bool(source.get("found")),
        "path": source.get("path", ""),
        "fresh": bool(source.get("fresh")),
        "ageSeconds": source.get("ageSeconds"),
        "maxAgeSeconds": source.get("maxAgeSeconds"),
        "tradeStatus": runtime.get("tradeStatus") or snapshot_dict.get("tradeStatus") or "",
        "executionEnabled": _truthy(execution_enabled_raw),
        "executionEnabledRaw": execution_enabled_raw,
        "executionEnabledFieldPresent": "executionEnabled" in runtime or "executionEnabled" in snapshot_dict,
        "readOnlyMode": _truthy(read_only_raw),
        "readOnlyModeRaw": read_only_raw,
        "readOnlyModeFieldPresent": "readOnlyMode" in runtime or "readOnlyMode" in snapshot_dict,
        "livePilotMode": _truthy(live_pilot_raw),
        "livePilotModeRaw": live_pilot_raw,
        "livePilotModeFieldPresent": "livePilotMode" in runtime or "livePilotMode" in snapshot_dict,
        "tradeAllowed": _truthy(trade_allowed_raw),
        "tradeAllowedRaw": trade_allowed_raw,
        "tradeAllowedFieldPresent": "tradeAllowed" in runtime or "tradeAllowed" in snapshot_dict,
        "permissionLayers": permission_layers,
        "executionGateDiagnostics": _execution_gate_diagnostics(
            live_pilot_raw=live_pilot_raw,
            read_only_raw=read_only_raw,
            execution_enabled_raw=execution_enabled_raw,
            trade_allowed_raw=trade_allowed_raw,
            runtime=runtime,
            permission_layers=permission_layers,
        ),
        "tickAgeSeconds": runtime.get("tickAgeSeconds", snapshot_dict.get("tickAgeSeconds")),
        "killSwitchFieldPresent": kill_present,
        "killSwitchOk": kill_ok,
        "killSwitchValue": kill_value,
        "account": {
            "number": account.get("number") or account.get("login") or account.get("account"),
            "server": account.get("server") or account.get("company") or "",
            "currency": account.get("currency") or "",
        },
        "symbolCount": len(symbols),
        "symbolNames": sorted(_symbol_names(symbols))[:32],
    }


def _lane_runtime_checks(
    replay: dict[str, Any],
    lane_spec: dict[str, Any],
    runtime_dir: Path,
    snapshot: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _symbol_rows(snapshot)
    names = _symbol_names(rows)
    sidecar_rows = _sidecar_symbol_rows(runtime_dir, snapshot)
    runtime_probe_rows = _runtime_probe_symbol_rows(runtime_dir, snapshot)
    contracts = {
        str(row.get("dryRunIntentId") or ""): row
        for row in _safe_list(lane_spec.get("laneContracts"))
        if isinstance(row, dict)
    }
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for intent in _safe_list(replay.get("replayedIntents")):
        if not isinstance(intent, dict):
            continue
        intent_id = str(intent.get("intentId") or "")
        contract = _safe_dict(contracts.get(intent_id))
        broker_symbol = str(intent.get("brokerSymbol") or contract.get("brokerSymbol") or "")
        canonical_symbol = str(intent.get("canonicalSymbol") or contract.get("canonicalSymbol") or "")
        row = _row_for_symbol(rows, broker_symbol, canonical_symbol)
        sidecar_row = _row_for_symbol(sidecar_rows, broker_symbol, canonical_symbol)
        runtime_probe_row = _row_for_symbol(runtime_probe_rows, broker_symbol, canonical_symbol)
        symbol_ok = bool(row)
        sidecar_symbol_ok = bool(sidecar_row)
        runtime_probe_symbol_ok = bool(runtime_probe_row)
        mapping_ok = bool(symbol_ok or sidecar_symbol_ok or runtime_probe_symbol_ok)
        spread = _symbol_spread(row or {})
        sidecar_spread = _sidecar_live_spread(runtime_probe_row or {})
        spread_ok = spread is not None
        sidecar_live_tick_ok = sidecar_spread is not None
        runtime_symbol_ok = bool(symbol_ok or sidecar_live_tick_ok)
        risk_limits = _safe_dict(contract.get("riskLimits"))
        risk_ok = all(
            key in risk_limits and risk_limits.get(key) not in (None, "")
            for key in ("maxNotionalUsd", "maxDailyLossPct", "maxDailyLossR", "maxConsecutiveLosses")
        )
        if not runtime_symbol_ok and sidecar_symbol_ok:
            blockers.append(_blocker(
                "MT5_SYMBOL_NOT_SELECTED_IN_RUNTIME_DASHBOARD",
                "HFM specs 已证明 broker symbol 存在，但当前 MT5 dashboard/watchlist 尚未选中该 symbol 并输出实时 tick。",
                broker_symbol or canonical_symbol,
            ))
        elif not runtime_symbol_ok:
            blockers.append(_blocker("MT5_SYMBOL_NOT_IN_RUNTIME_SNAPSHOT", "dry-run intent 的 broker symbol 不在当前 MT5 快照或 runtime probe 中。", broker_symbol or canonical_symbol))
        if not (spread_ok or sidecar_live_tick_ok):
            blockers.append(_blocker(
                "MT5_SYMBOL_LIVE_TICK_OR_SPREAD_MISSING",
                "当前 MT5 dashboard/runtime probe 尚未输出该 symbol 的实时 bid/ask 或 spread，无法做价差预检。",
                broker_symbol or canonical_symbol,
            ))
        if not risk_ok:
            blockers.append(_blocker("DRY_RUN_RISK_LIMITS_INCOMPLETE", "execution lane spec 缺少完整 dry-run 风险边界。", intent_id))
        checks.append({
            "intentId": intent_id,
            "lane": intent.get("lane") or contract.get("lane") or "",
            "brokerSymbol": broker_symbol,
            "canonicalSymbol": canonical_symbol,
            "symbolPresentInSnapshot": symbol_ok,
            "symbolPresentInSidecarSpecs": sidecar_symbol_ok,
            "symbolPresentInRuntimeProbe": runtime_probe_symbol_ok,
            "symbolMappingOk": mapping_ok,
            "symbolPresentInNames": broker_symbol in names or canonical_symbol in names,
            "spreadFieldPresent": spread_ok,
            "spreadValue": spread,
            "sidecarLiveTickPresent": sidecar_live_tick_ok,
            "sidecarSpreadValue": sidecar_spread,
            "runtimeProbeSource": runtime_probe_row.get("_runtimeProbeSource") if runtime_probe_row else "",
            "runtimeProbeFresh": runtime_probe_row.get("_runtimeProbeFresh") if runtime_probe_row else False,
            "runtimeProbeAgeSeconds": runtime_probe_row.get("_runtimeProbeAgeSeconds") if runtime_probe_row else None,
            "riskLimitsPresent": risk_ok,
            "passed": bool(runtime_symbol_ok and (spread_ok or sidecar_live_tick_ok) and risk_ok),
        })
    return checks, blockers


def build_live_runtime_preflight_probe(
    runtime_dir: Path,
    *,
    operator_approval_json: str = "",
    write: bool = False,
    refresh_sources: bool = False,
    moss_backtest_json: str = "",
    hfm_simulation_profile_json: str = "",
    hfm_contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    operator_approval_json, operator_approval_reuse = operator_approval_json_for_refresh(
        runtime_dir,
        operator_approval_json,
        refresh_sources=refresh_sources,
    )
    should_rebuild = bool(
        refresh_sources
        or operator_approval_json
        or moss_backtest_json
        or hfm_simulation_profile_json
        or hfm_contract_spec_json
        or extra_bases_roots
    )
    replay = (
        build_dry_run_intent_replay(
            runtime_dir,
            write=bool(refresh_sources),
            refresh_sources=refresh_sources,
            operator_approval_json=operator_approval_json,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_dry_run_intent_replay(runtime_dir)
    )
    lane_spec = (
        build_live_execution_lane_spec(
            runtime_dir,
            write=bool(refresh_sources),
            refresh_sources=refresh_sources,
            operator_approval_json=operator_approval_json,
            moss_backtest_json=moss_backtest_json,
            hfm_simulation_profile_json=hfm_simulation_profile_json,
            hfm_contract_spec_json=hfm_contract_spec_json,
            extra_bases_roots=extra_bases_roots or [],
        )
        if should_rebuild
        else read_live_execution_lane_spec(runtime_dir)
    )
    snapshot, source, source_blockers = _read_dashboard_snapshot(runtime_dir)
    dashboard = _dashboard_summary(snapshot, source)
    blockers: list[dict[str, Any]] = []
    blockers.extend(source_blockers)
    if not bool(replay.get("replayPassed")):
        blockers.append(_blocker("DRY_RUN_REPLAY_NOT_PASSED", "dry-run intent 回放尚未通过。", replay.get("status")))
    if not bool(lane_spec.get("readyForImplementationReview")):
        blockers.append(_blocker("EXECUTION_LANE_SPEC_NOT_READY", "execution lane spec 尚未进入实现评审。", lane_spec.get("status")))
    if dashboard.get("found"):
        if not dashboard.get("livePilotModeFieldPresent"):
            blockers.append(_blocker("MT5_LIVE_PILOT_MODE_FIELD_MISSING", "MT5 dashboard 缺少 livePilotMode 字段，不能证明终端处在实盘 pilot 配置。"))
        elif dashboard.get("livePilotMode") is not True:
            blockers.append(_blocker("MT5_LIVE_PILOT_MODE_NOT_CONFIRMED", "MT5 dashboard 尚未证明 livePilotMode=true。", dashboard.get("livePilotModeRaw")))
        if not dashboard.get("readOnlyModeFieldPresent"):
            blockers.append(_blocker("MT5_READ_ONLY_MODE_FIELD_MISSING", "MT5 dashboard 缺少 readOnlyMode 字段，不能确认 live pilot 执行环境。"))
        elif dashboard.get("readOnlyMode") is not False:
            blockers.append(_blocker("MT5_READ_ONLY_MODE_STILL_ACTIVE", "MT5 dashboard 仍处于 readOnly/shadow 模式，不能进入 live pilot 预检通过态。", dashboard.get("readOnlyModeRaw")))
        if not dashboard.get("executionEnabledFieldPresent"):
            blockers.append(_blocker("MT5_EXECUTION_ENABLED_FIELD_MISSING", "MT5 dashboard 缺少 executionEnabled 字段。"))
        elif dashboard.get("executionEnabled") is not True:
            blockers.append(_blocker("MT5_EXECUTION_NOT_ENABLED_FOR_PILOT", "MT5 dashboard 尚未证明 live pilot 执行环境已显式启用。", dashboard.get("executionEnabledRaw")))
        if not dashboard.get("tradeAllowedFieldPresent"):
            blockers.append(_blocker("MT5_TRADE_ALLOWED_FIELD_MISSING", "MT5 dashboard 缺少 tradeAllowed 字段。"))
        elif dashboard.get("tradeAllowed") is not True:
            blockers.append(_blocker("MT5_TRADE_ALLOWED_NOT_CONFIRMED", "MT5 dashboard 尚未证明账户、终端、EA 和 symbol 交易权限均允许。", dashboard.get("tradeAllowedRaw")))
        if not dashboard.get("killSwitchFieldPresent"):
            blockers.append(_blocker("MT5_KILL_SWITCH_FIELD_MISSING", "MT5 dashboard 缺少明确的 kill switch 字段。"))
        elif not dashboard.get("killSwitchOk"):
            blockers.append(_blocker("MT5_KILL_SWITCH_ACTIVE", "MT5 dashboard 显示 kill switch 正在阻断交易。", dashboard.get("killSwitchValue")))
        account = _safe_dict(dashboard.get("account"))
        if not account.get("number") or not account.get("server"):
            blockers.append(_blocker("MT5_ACCOUNT_OR_SERVER_MISSING", "MT5 dashboard 缺少账户号或 broker server。", account))
        if not dashboard.get("symbolCount"):
            blockers.append(_blocker("MT5_SYMBOL_SNAPSHOT_EMPTY", "MT5 dashboard 没有 symbol 行，无法核对 broker symbol。"))
    lane_checks, lane_blockers = _lane_runtime_checks(replay, lane_spec, runtime_dir, snapshot)
    blockers.extend(lane_blockers)
    non_execution_blockers = [
        row for row in blockers if str(row.get("code") or "") not in _EXECUTION_MODE_BLOCKER_CODES
    ]
    account = _safe_dict(dashboard.get("account"))
    data_plane_ready = bool(
        replay.get("replayPassed")
        and lane_spec.get("readyForImplementationReview")
        and dashboard.get("found")
        and dashboard.get("fresh")
        and dashboard.get("killSwitchFieldPresent")
        and dashboard.get("killSwitchOk")
        and account.get("number")
        and account.get("server")
        and lane_checks
        and all(row.get("passed") for row in lane_checks)
        and not non_execution_blockers
    )
    execution_mode_ready = bool(
        dashboard.get("livePilotMode") is True
        and dashboard.get("readOnlyMode") is False
        and dashboard.get("executionEnabled") is True
        and dashboard.get("tradeAllowed") is True
    )
    execution_mode_only_blocked = bool(data_plane_ready and not execution_mode_ready)
    runtime_probe_passed = bool(data_plane_ready and execution_mode_ready and not blockers)
    status = "WAITING_RUNTIME_PREFLIGHT_INPUTS"
    status_zh = "等待运行时预检证据"
    next_required_action_zh = "先补齐 dry-run replay、MT5 dashboard 新鲜快照、kill switch、账户、symbol 和价差证据。"
    if runtime_probe_passed:
        status = "READY_FOR_RUNTIME_PREFLIGHT_REVIEW"
        status_zh = "运行时预检通过，但真实执行仍关闭"
        next_required_action_zh = "运行时预检可进入单独 execution adapter 代码评审；当前仍不会写订单。"
    elif execution_mode_only_blocked:
        status = "WAITING_EXECUTION_MODE_ACTIVATION"
        status_zh = "数据面预检已通过，等待执行模式闸门"
        next_required_action_zh = (
            "HFM/BTC 数据面、账户、kill switch、tick、价差和风险边界已通过；"
            "仅剩 livePilotMode、readOnlyMode、executionEnabled、tradeAllowed 执行模式闸门，"
            "必须走单独 execution lane/live pilot 激活评审，当前仍不会写订单。"
        )
    payload = {
        "ok": True,
        "schema": RUNTIME_PREFLIGHT_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime_dir),
        "status": status,
        "statusZh": status_zh,
        "runtimeProbePassed": runtime_probe_passed,
        "dataPlaneReadyForLivePilotReview": data_plane_ready,
        "executionModeReady": execution_mode_ready,
        "executionModeOnlyBlocked": execution_mode_only_blocked,
        "readyForImplementationReview": bool(lane_spec.get("readyForImplementationReview")),
        "replayPassed": bool(replay.get("replayPassed")),
        "executionReady": False,
        "operatorApprovalJsonProvided": bool(operator_approval_json),
        "operatorApprovalJsonReusedFromPriorEvidence": bool(operator_approval_reuse.get("reused")),
        "operatorApprovalJsonRefreshContext": operator_approval_reuse,
        "reviewPacketHash": replay.get("reviewPacketHash") or lane_spec.get("reviewPacketHash") or "",
        "approvedLanes": _safe_list(lane_spec.get("approvedLanes")),
        "intentCount": int(replay.get("intentCount") or 0),
        "passedIntentCount": int(replay.get("passedIntentCount") or 0),
        "dashboardSnapshot": dashboard,
        "probeResults": {
            "dryRunReplayOk": bool(replay.get("replayPassed")),
            "executionLaneSpecOk": bool(lane_spec.get("readyForImplementationReview")),
            "dashboardFresh": bool(dashboard.get("fresh")),
            "livePilotModeOk": dashboard.get("livePilotMode") is True,
            "readOnlyModeOff": dashboard.get("readOnlyMode") is False,
            "executionEnabledOk": dashboard.get("executionEnabled") is True,
            "tradeAllowedOk": dashboard.get("tradeAllowed") is True,
            "killSwitchOk": bool(dashboard.get("killSwitchOk")),
            "accountModeOk": bool(_safe_dict(dashboard.get("account")).get("number") and _safe_dict(dashboard.get("account")).get("server")),
            "symbolMappingOk": bool(lane_checks and all(row.get("symbolMappingOk") for row in lane_checks)),
            "symbolSelectedInDashboardOk": bool(lane_checks and all(row.get("symbolPresentInSnapshot") for row in lane_checks)),
            "symbolSidecarSpecOk": bool(lane_checks and all(row.get("symbolPresentInSidecarSpecs") for row in lane_checks)),
            "symbolRuntimeProbeOk": bool(lane_checks and all(row.get("symbolPresentInSnapshot") or row.get("sidecarLiveTickPresent") for row in lane_checks)),
            "sidecarLiveTickOk": bool(lane_checks and all(row.get("sidecarLiveTickPresent") for row in lane_checks)),
            "spreadProbeOk": bool(lane_checks and all(row.get("spreadFieldPresent") or row.get("sidecarLiveTickPresent") for row in lane_checks)),
            "riskLimitsOk": bool(lane_checks and all(row.get("riskLimitsPresent") for row in lane_checks)),
        },
        "laneRuntimeChecks": lane_checks,
        "blockers": blockers,
        "nonExecutionBlockers": non_execution_blockers,
        "executionModeBlockers": [
            row for row in blockers if str(row.get("code") or "") in _EXECUTION_MODE_BLOCKER_CODES
        ],
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "writesMt5OrderRequest": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "mt5PendingOrderIntentsWritten": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerExecutionAllowed": False,
        "nextRequiredActionZh": next_required_action_zh,
        "safety": dict(SAFETY),
    }
    assert_no_execution_flags(payload)
    if write:
        out = runtime_preflight_path(runtime_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_live_runtime_preflight_probe(runtime_dir: Path) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    path = runtime_preflight_path(runtime)
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                if (
                    payload.get("status") == "WAITING_RUNTIME_PREFLIGHT_INPUTS"
                    and not bool(payload.get("operatorApprovalJsonProvided"))
                    and operator_approval_json_for_refresh(runtime, "", refresh_sources=True)[0]
                ):
                    return build_live_runtime_preflight_probe(
                        runtime,
                        write=False,
                        refresh_sources=True,
                    )
                return payload
        except Exception:
            pass
    return {
        "ok": False,
        "schema": RUNTIME_PREFLIGHT_SCHEMA_VERSION,
        "generatedAtIso": utc_now_iso(),
        "runtimeDir": str(runtime),
        "status": "RUNTIME_PREFLIGHT_ARTIFACT_MISSING",
        "statusZh": "runtime preflight artifact 尚未生成",
        "runtimeProbePassed": False,
        "dataPlaneReadyForLivePilotReview": False,
        "executionModeReady": False,
        "executionModeOnlyBlocked": False,
        "readyForImplementationReview": False,
        "executionReady": False,
        "operatorApprovalJsonProvided": False,
        "probeResults": {},
        "blockers": [{
            "code": "RUNTIME_PREFLIGHT_ARTIFACT_MISSING",
            "reasonZh": "使用显式 runtime-preflight build 生成；普通读取不会重建或覆盖 runtime 证据。",
        }],
        "canPromoteToLiveNow": False,
        "autoPromotionToLiveAllowed": False,
        "writesMt5OrderRequest": False,
        "requestFilesWritten": False,
        "brokerCallsMade": False,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "brokerExecutionAllowed": False,
        "safety": dict(SAFETY),
    }
