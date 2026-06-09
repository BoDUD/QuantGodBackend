from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from tools.mt5_readonly_bridge import read_ea_dashboard_snapshot, read_usdjpy_rsi_entry_diagnostics
except Exception:  # pragma: no cover - direct script imports can run without package root.
    try:
        from mt5_readonly_bridge import read_ea_dashboard_snapshot, read_usdjpy_rsi_entry_diagnostics  # type: ignore[no-redef]
    except Exception:
        read_ea_dashboard_snapshot = None  # type: ignore[assignment]
        read_usdjpy_rsi_entry_diagnostics = None  # type: ignore[assignment]


SCHEMA = "quantgod.entry_latency.v1"
REPORT_NAME = "QuantGod_EntryLatencyReport.json"
LEDGER_NAME = "QuantGod_EntryLatencyLedger.csv"
FOCUS_SYMBOL = "USDJPYc"

PASS_STATES = {"FAST", "OK", "PASS", "PASSED", "GOOD", "HEALTHY", "EA_DASHBOARD_OK"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def latency_dir(runtime_dir: str | Path) -> Path:
    return Path(runtime_dir) / "latency"


def report_path(runtime_dir: str | Path) -> Path:
    return latency_dir(runtime_dir) / REPORT_NAME


def ledger_path(runtime_dir: str | Path) -> Path:
    return latency_dir(runtime_dir) / LEDGER_NAME


def safety_payload() -> Dict[str, Any]:
    return {
        "localOnly": True,
        "focusOnly": True,
        "focusSymbol": FOCUS_SYMBOL,
        "readOnlyDataPlane": True,
        "advisoryOnly": True,
        "latencyAttributionOnly": True,
        "orderSendAllowed": False,
        "closeAllowed": False,
        "cancelAllowed": False,
        "modifyAllowed": False,
        "brokerExecutionAllowed": False,
        "writesMt5OrderRequest": False,
        "livePresetMutationAllowed": False,
        "credentialStorageAllowed": False,
        "telegramCommandExecutionAllowed": False,
        "walletIntegrationAllowed": False,
    }


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def _file_mtime(path: Path | None) -> float:
    try:
        if path and path.exists():
            return path.stat().st_mtime
    except Exception:
        return 0.0
    return 0.0


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _repo_runtime_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime"


def _include_global_mt5_candidates(runtime_dir: Path) -> bool:
    if _truthy_env("QG_ENTRY_LATENCY_INCLUDE_GLOBAL_MT5") or _truthy_env("QG_USDJPY_INCLUDE_GLOBAL_MT5"):
        return True
    if _truthy_env("QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY") and (os.environ.get("QG_MT5_FILES_DIR") or os.environ.get("QG_HFM_FILES_DIR")):
        return True
    try:
        return runtime_dir.resolve() == _repo_runtime_dir().resolve()
    except Exception:
        return False


def _read_latest_ea_diagnostics(runtime_dir: Path) -> tuple[Dict[str, Any], Path]:
    fallback_path = runtime_dir / "QuantGod_USDJPYRsiEntryDiagnostics.json"
    diagnostics = _read_json(fallback_path)
    diagnostics_path = fallback_path
    diagnostics_mtime = _file_mtime(fallback_path) if diagnostics else 0.0
    if _include_global_mt5_candidates(runtime_dir) and read_usdjpy_rsi_entry_diagnostics is not None:
        payload, path, _error = read_usdjpy_rsi_entry_diagnostics()
        if isinstance(payload, dict) and payload:
            diagnostics = payload
            diagnostics_path = path or fallback_path
            diagnostics_mtime = _file_mtime(path)
    if _include_global_mt5_candidates(runtime_dir) and read_ea_dashboard_snapshot is not None:
        dashboard, dashboard_path, _error = read_ea_dashboard_snapshot()
        embedded = dashboard.get("usdJpyRsiEntryDiagnostics") if isinstance(dashboard, dict) else None
        dashboard_mtime = _file_mtime(dashboard_path)
        if isinstance(embedded, dict) and embedded and dashboard_mtime >= diagnostics_mtime:
            result = dict(embedded)
            result.setdefault("_source", "QuantGod_Dashboard.json.usdJpyRsiEntryDiagnostics")
            return result, dashboard_path or fallback_path
    return diagnostics, diagnostics_path


def _parse_time(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        try:
            return datetime.fromtimestamp(raw, timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _file_time(path: Path) -> Optional[datetime]:
    try:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except Exception:
        return None
    return None


def _time_from_payload(payload: Dict[str, Any], path: Path) -> Optional[datetime]:
    for key in ("generatedAt", "generatedAtIso", "timestamp", "timeIso", "time"):
        parsed = _parse_time(payload.get(key))
        if parsed is not None:
            return parsed
    return _file_time(path)


def _age_seconds(at: Optional[datetime], now: datetime) -> Optional[float]:
    if at is None:
        return None
    return round(max(0.0, (now - at).total_seconds()), 3)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _normalize_direction(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"LONG", "BUY", "1"}:
        return "LONG"
    if text in {"SHORT", "SELL", "-1"}:
        return "SHORT"
    return ""


def _demoted_out_of_scope_signal(policy_direction: str, ea_signal_direction: str, ea: Dict[str, Any]) -> Dict[str, Any]:
    eval_code = str(ea.get("evalCode") or "").upper()
    if policy_direction == "LONG" and ea_signal_direction == "SHORT" and eval_code == "SIGNAL_SELL":
        return {
            "demoted": True,
            "code": "sell_side_demoted_after_loss_review",
            "reasonZh": "SELL 侧已因 live loss review 降级为 shadow/candidate；不能用当前 SHORT 信号直接扩大 live 方向。",
            "requiredStage": "SHADOW/TESTER_ONLY",
        }
    return {}


def _compact_reasons(values: Iterable[Any], limit: int = 8) -> List[str]:
    rows: List[str] = []
    for value in values:
        if isinstance(value, dict):
            text = value.get("reasonZh") or value.get("label") or value.get("detail") or value.get("reason")
        else:
            text = value
        for part in str(text or "").replace("\n", "；").split("；"):
            clean = part.strip()
            if clean:
                rows.append(clean)
    return list(dict.fromkeys(rows))[:limit]


def _first_reason(*values: Any) -> str:
    rows = _compact_reasons(values, limit=1)
    return rows[0] if rows else ""


def _latest_jsonl_event(paths: List[Path]) -> Dict[str, Any]:
    latest: Dict[str, Any] = {}
    latest_at: Optional[datetime] = None
    for path in paths:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        except Exception:
            continue
        for raw in lines[-500:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            event_type = str(row.get("eventType") or row.get("type") or row.get("event") or "").lower()
            if event_type and not any(token in event_type for token in ("send", "fill", "reject", "order", "entry")):
                continue
            at = None
            for key in ("eventTime", "timestamp", "generatedAt", "time", "timeIso"):
                at = _parse_time(row.get(key))
                if at:
                    break
            if at is None:
                at = _file_time(path)
            if latest_at is None or (at is not None and at > latest_at):
                latest = dict(row)
                latest["_sourceFile"] = str(path)
                latest_at = at
    if latest_at:
        latest["_eventAtIso"] = _iso(latest_at)
    return latest


def _fastlane_stage(runtime_dir: Path, now: datetime, symbol: str) -> Dict[str, Any]:
    path = runtime_dir / "quality" / "QuantGod_MT5FastLaneQuality.json"
    payload = _read_json(path)
    at = _time_from_payload(payload, path) if payload else None
    if not payload:
        return {
            "stage": "market_data",
            "labelZh": "行情/快通道",
            "status": "MISSING",
            "statusZh": "缺少快通道质量报告",
            "at": None,
            "ageSeconds": None,
            "reasonZh": "缺少快通道质量证据：没有看到 P3-7 快通道质量报告，策略只能 fail-closed。",
            "source": str(path),
        }
    heartbeat_ok = bool(payload.get("heartbeatFresh"))
    symbols = payload.get("symbols")
    rows = symbols.values() if isinstance(symbols, dict) else symbols
    matched: List[Dict[str, Any]] = []
    if isinstance(rows, list):
        for item in rows:
            if isinstance(item, dict) and str(item.get("symbol") or symbol).upper() == symbol.upper():
                matched.append(item)
    quality = str(payload.get("quality") or "").upper()
    if matched:
        quality = str(matched[0].get("quality") or matched[0].get("state") or quality).upper()
    ok = heartbeat_ok or quality in PASS_STATES
    reason = payload.get("reason") or payload.get("summary") or ""
    if matched:
        first = matched[0]
        reason = (
            f"quality={quality or 'UNKNOWN'}；tick年龄={first.get('tickAgeSeconds')}秒；"
            f"指标年龄={first.get('indicatorAgeSeconds')}秒；点差={first.get('spreadPoints')}"
        )
    return {
        "stage": "market_data",
        "labelZh": "行情/快通道",
        "status": "READY" if ok else "DEGRADED",
        "statusZh": "快通道可用" if ok else "快通道降级",
        "at": _iso(at),
        "ageSeconds": _age_seconds(at, now),
        "reasonZh": reason or ("快通道质量通过。" if ok else "快通道质量未通过。"),
        "quality": quality or ("FAST" if ok else "UNKNOWN"),
        "heartbeatFresh": heartbeat_ok,
        "source": str(path),
    }


def _policy_stage(runtime_dir: Path, now: datetime) -> Dict[str, Any]:
    path = runtime_dir / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json"
    payload = _read_json(path)
    at = _time_from_payload(payload, path) if payload else None
    top = payload.get("topLiveEligiblePolicy") or payload.get("topPolicy") or payload.get("liveRecoveryCandidate") or {}
    if not payload:
        return {
            "stage": "policy",
            "labelZh": "策略政策",
            "status": "MISSING",
            "statusZh": "缺少策略政策",
            "at": None,
            "ageSeconds": None,
            "reasonZh": "没有 USDJPYAutoExecutionPolicy，无法判断是否策略慢。",
            "source": str(path),
        }
    entry_mode = str(top.get("entryMode") or "UNKNOWN")
    allowed = bool(top.get("allowed")) and entry_mode in {"STANDARD_ENTRY", "OPPORTUNITY_ENTRY"}
    reasons = _compact_reasons(top.get("reasons") or [top.get("reason")])
    hard_reasons = _compact_reasons(top.get("hardGateReasons") or [])
    hard_gate_status = str(top.get("hardGateStatus") or "").upper()
    if hard_gate_status not in {"PASS", "PASSED", "OK"}:
        reasons.extend(reason for reason in hard_reasons if reason not in reasons)
    signal_quorum = _num(top.get("signalQuorum"), -1.0)
    signal_quorum_required = _num(top.get("signalQuorumRequired"), -1.0)
    if signal_quorum >= 0 and signal_quorum_required > 0 and signal_quorum < signal_quorum_required:
        quorum_reason = f"signal quorum 未满足：{signal_quorum:.0f}/{signal_quorum_required:.0f}"
        if quorum_reason not in reasons:
            reasons.insert(0, quorum_reason)
    confirmations = top.get("tacticalConfirmations") if isinstance(top.get("tacticalConfirmations"), dict) else {}
    confirmation_map = confirmations.get("confirmations") if isinstance(confirmations.get("confirmations"), dict) else {}
    if confirmation_map.get("影子样本未显示负期望") is False:
        sample_reason = "影子样本仍未证明非负期望，保持观察。"
        if sample_reason not in reasons:
            reasons.append(sample_reason)
    shadow = payload.get("topShadowPolicy") if isinstance(payload.get("topShadowPolicy"), dict) else {}
    return {
        "stage": "policy",
        "labelZh": "策略政策",
        "status": "READY" if allowed else "BLOCKED",
        "statusZh": "政策已放行" if allowed else "政策阻断",
        "at": _iso(at),
        "ageSeconds": _age_seconds(at, now),
        "entryMode": entry_mode,
        "allowed": allowed,
        "recommendedLot": top.get("recommendedLot", 0.0),
        "strategy": top.get("strategy", "UNKNOWN"),
        "direction": top.get("direction", "UNKNOWN"),
        "score": top.get("score"),
        "entryStrictness": top.get("entryStrictness"),
        "signalQuorum": top.get("signalQuorum"),
        "signalQuorumRequired": top.get("signalQuorumRequired"),
        "tacticalConfirmations": confirmations,
        "topShadowPolicy": {
            "strategy": shadow.get("strategy", "UNKNOWN"),
            "direction": shadow.get("direction", "UNKNOWN"),
            "entryMode": shadow.get("entryMode", "UNKNOWN"),
            "entryStrictness": shadow.get("entryStrictness", ""),
            "signalQuorum": shadow.get("signalQuorum"),
            "signalQuorumRequired": shadow.get("signalQuorumRequired"),
            "score": shadow.get("score"),
            "reasonZh": "；".join(_compact_reasons(shadow.get("reasons") or [shadow.get("reason")], limit=4)),
        } if shadow else {},
        "reasonZh": "；".join(reasons) or ("策略政策已放行。" if allowed else "策略政策未放行。"),
        "source": str(path),
    }


def _ea_stage(runtime_dir: Path, now: datetime) -> Dict[str, Any]:
    path = runtime_dir / "QuantGod_USDJPYRsiEntryDiagnostics.json"
    payload, source_path = _read_latest_ea_diagnostics(runtime_dir)
    path = source_path
    at = _time_from_payload(payload, path) if payload else None
    if not payload:
        return {
            "stage": "ea_guard",
            "labelZh": "EA 入场守门",
            "status": "MISSING",
            "statusZh": "缺少 EA 入场诊断",
            "at": None,
            "ageSeconds": None,
            "reasonZh": "MT5 尚未写出 USDJPY RSI 入场诊断。",
            "source": str(path),
        }
    guards = payload.get("guards") if isinstance(payload.get("guards"), dict) else {}
    rsi = payload.get("rsi") if isinstance(payload.get("rsi"), dict) else {}
    state = str(payload.get("state") or guards.get("state") or "UNKNOWN")
    startup = bool(guards.get("startupGuardActive"))
    spread_allowed = guards.get("spreadAllowed")
    spread_pips = guards.get("spreadPips")
    status = "READY"
    if startup or state == "STARTUP_GUARD":
        status = "STARTUP_GUARD"
    elif spread_allowed is False or state in {"SPREAD_BLOCK", "SPREAD_HARD_BLOCK"}:
        status = "SPREAD_BLOCK"
    elif state not in {"READY_BUY_SIGNAL", "READY", "NO_SIGNAL", "WAIT_SIGNAL"}:
        status = "BLOCKED"
    reasons = _compact_reasons(payload.get("whyNoEntry") or [guards.get("startupGuardReason"), guards.get("newsReason")])
    reason = "；".join(reasons)
    if not reason:
        reason = "EA 守门未阻断，等待 RSI/价格信号。" if status == "READY" else f"EA 状态：{state}"
    return {
        "stage": "ea_guard",
        "labelZh": "EA 入场守门",
        "status": status,
        "statusZh": {
            "READY": "EA 守门可用",
            "STARTUP_GUARD": "启动保护中",
            "SPREAD_BLOCK": "点差阻断",
            "BLOCKED": "EA 守门阻断",
        }.get(status, status),
        "at": _iso(at),
        "ageSeconds": _age_seconds(at, now),
        "state": state,
        "startupGuardActive": startup,
        "startupGuardReason": guards.get("startupGuardReason", ""),
        "spreadPips": spread_pips,
        "spreadAllowed": spread_allowed,
        "configuredDirection": _normalize_direction(payload.get("direction")),
        "signalReady": bool(rsi.get("signalReady")),
        "signalDirection": _normalize_direction(rsi.get("signalDirection")),
        "signalDirectionRaw": rsi.get("signalDirection") or "",
        "signalScore": rsi.get("signalScore"),
        "evalCode": rsi.get("evalCode") or "",
        "evalReason": rsi.get("evalReason") or "",
        "reasonZh": reason,
        "source": str(path),
    }


def _order_stage(runtime_dir: Path, now: datetime) -> Dict[str, Any]:
    event = _latest_jsonl_event([
        runtime_dir / "evidence_os" / "QuantGod_LiveExecutionFeedback.jsonl",
        runtime_dir / "execution" / "QuantGod_LiveExecutionFeedback.jsonl",
        runtime_dir / "QuantGod_RuntimeTradeEvents.jsonl",
    ])
    at = _parse_time(event.get("_eventAtIso"))
    if not event:
        return {
            "stage": "order_attempt",
            "labelZh": "订单尝试/成交反馈",
            "status": "NO_ATTEMPT",
            "statusZh": "未看到订单尝试",
            "at": None,
            "ageSeconds": None,
            "reasonZh": "尚未看到 send/fill/reject/entry 类执行反馈；如果政策已放行但这里为空，慢点在 EA 信号或订单触发之前。",
            "source": "",
        }
    event_type = str(event.get("eventType") or event.get("type") or event.get("event") or "UNKNOWN")
    age_seconds = _age_seconds(at, now)
    stale = age_seconds is not None and age_seconds > 3600
    return {
        "stage": "order_attempt",
        "labelZh": "订单尝试/成交反馈",
        "status": "STALE_ATTEMPT" if stale else "ATTEMPTED",
        "statusZh": "订单/成交反馈已过期" if stale else "已看到订单/成交反馈",
        "at": _iso(at),
        "ageSeconds": age_seconds,
        "eventType": event_type,
        "latencyMs": event.get("latencyMs"),
        "slippagePips": event.get("slippagePips"),
        "rejectReason": event.get("rejectReason"),
        "reasonZh": (
            f"最近执行反馈事件已超过一小时：{event_type}，只作为历史证据。"
            if stale
            else event.get("rejectReason") or f"最近执行反馈事件：{event_type}"
        ),
        "source": event.get("_sourceFile", ""),
    }


def _dt(stage: Dict[str, Any]) -> Optional[datetime]:
    return _parse_time(stage.get("at"))


def _diff_ms(left: Dict[str, Any], right: Dict[str, Any]) -> Optional[int]:
    a = _dt(left)
    b = _dt(right)
    if a is None or b is None:
        return None
    diff = int((b - a).total_seconds() * 1000)
    return diff if diff >= 0 else None


def _primary_attribution(stages: List[Dict[str, Any]]) -> Dict[str, Any]:
    for stage in stages:
        status = str(stage.get("status") or "")
        if status in {"MISSING", "DEGRADED", "BLOCKED", "STARTUP_GUARD", "SPREAD_BLOCK"}:
            return {
                "stage": stage.get("stage"),
                "labelZh": stage.get("labelZh"),
                "status": status,
                "reasonZh": stage.get("reasonZh"),
            }
    order = next((stage for stage in stages if stage.get("stage") == "order_attempt"), {})
    if order.get("status") == "NO_ATTEMPT":
        return {
            "stage": "order_attempt",
            "labelZh": "订单尝试/成交反馈",
            "status": "NO_ATTEMPT",
            "reasonZh": order.get("reasonZh"),
        }
    if order.get("status") == "STALE_ATTEMPT":
        return {
            "stage": "order_attempt",
            "labelZh": "订单尝试/成交反馈",
            "status": "STALE_ATTEMPT",
            "reasonZh": order.get("reasonZh"),
        }
    return {"stage": "complete", "labelZh": "完整链路", "status": "OK", "reasonZh": "入场链路已看到执行反馈。"}


def _recovery_action_for_stage(stage: Dict[str, Any]) -> Dict[str, Any]:
    stage_id = str(stage.get("stage") or "")
    status = str(stage.get("status") or "")
    reason = str(stage.get("reasonZh") or "")
    if stage_id == "market_data":
        if status == "MISSING":
            return {
                "actionId": "restore_fastlane_quality_report",
                "stage": stage_id,
                "labelZh": "恢复快通道质量报告",
                "priority": 10,
                "reasonZh": reason or "缺少快通道质量报告。",
                "nextRequiredActionZh": "先恢复 MT5 快通道 exporter/EA 现场数据，生成 QuantGod_MT5FastLaneQuality.json 后再刷新策略。",
                "expectedEvidence": {
                    "file": str(stage.get("source") or ""),
                    "fields": ["heartbeatFresh=true", "tickRows>0", "quality=FAST/EA_DASHBOARD_OK"],
                },
            }
        if status == "DEGRADED":
            return {
                "actionId": "refresh_fastlane_ticks_and_indicators",
                "stage": stage_id,
                "labelZh": "刷新 tick/指标快通道",
                "priority": 20,
                "reasonZh": reason or "快通道质量降级。",
                "nextRequiredActionZh": "优先让 MT5 快通道写出新 tick、指标和 heartbeat；快通道恢复前策略只能 fail-closed。",
                "expectedEvidence": {
                    "file": str(stage.get("source") or ""),
                    "fields": ["heartbeatFresh=true 或 quality=FAST", "tickAgeSeconds 在阈值内", "indicatorAgeSeconds 在阈值内"],
                },
            }
    if stage_id == "policy":
        signal_quorum = _num(stage.get("signalQuorum"), -1.0)
        signal_quorum_required = _num(stage.get("signalQuorumRequired"), -1.0)
        if signal_quorum >= 0 and signal_quorum_required > 0 and signal_quorum < signal_quorum_required:
            return {
                "actionId": "wait_for_signal_quorum_or_shadow_sample",
                "stage": stage_id,
                "labelZh": "等待信号 quorum / 影子样本",
                "priority": 25,
                "reasonZh": reason or "策略信号 quorum 或影子样本未通过。",
                "nextRequiredActionZh": "当前硬风控可过但信号 quorum 不足；继续刷新 tick、策略和影子样本，等 RSI_Reversal LONG 达到 quorum 后再进入下一步复核。",
                "expectedEvidence": {
                    "file": str(stage.get("source") or ""),
                    "fields": ["signalQuorum >= signalQuorumRequired", "entryMode=STANDARD_ENTRY/OPPORTUNITY_ENTRY", "shadow sample non-negative"],
                },
            }
        return {
            "actionId": "refresh_adaptive_policy_after_data",
            "stage": stage_id,
            "labelZh": "刷新策略政策",
            "priority": 30,
            "reasonZh": reason or "策略政策未放行。",
            "nextRequiredActionZh": "快通道恢复后重新生成 adaptive policy，确认 RSI_Reversal LONG 是否出现 STANDARD_ENTRY 或合规机会入场。",
            "expectedEvidence": {
                "file": str(stage.get("source") or ""),
                "fields": ["topLiveEligiblePolicy", "entryMode", "signalQuorum", "recommendedLot"],
            },
        }
    if stage_id == "ea_guard":
        if status == "STARTUP_GUARD":
            return {
                "actionId": "wait_or_refresh_ea_startup_guard",
                "stage": stage_id,
                "labelZh": "等待/刷新 EA 启动保护",
                "priority": 40,
                "reasonZh": reason or "EA 启动保护中。",
                "nextRequiredActionZh": "等待下一根 H1 bar 或刷新 EA 入场诊断；启动保护解除后再看点差和信号。",
                "expectedEvidence": {
                    "file": str(stage.get("source") or ""),
                    "fields": ["startupGuardActive=false", "state!=STARTUP_GUARD"],
                },
            }
        if status == "SPREAD_BLOCK":
            return {
                "actionId": "wait_for_normal_spread",
                "stage": stage_id,
                "labelZh": "等待点差恢复",
                "priority": 35,
                "reasonZh": reason or "EA 点差守门阻断。",
                "nextRequiredActionZh": "等待 USDJPY 点差回到策略阈值内；点差硬阻断时不应扩大仓位或绕过守门。",
                "expectedEvidence": {
                    "file": str(stage.get("source") or ""),
                    "fields": ["spreadAllowed=true", "spreadPips<=limit"],
                },
            }
        return {
            "actionId": "inspect_ea_entry_guard",
            "stage": stage_id,
            "labelZh": "检查 EA 入场守门",
            "priority": 40,
            "reasonZh": reason or "EA 入场守门阻断。",
            "nextRequiredActionZh": "检查 EA 入场诊断里的 no-entry 原因，确认不是启动保护、点差、新闻或信号缺失。",
            "expectedEvidence": {
                "file": str(stage.get("source") or ""),
                "fields": ["state", "whyNoEntry", "guards"],
            },
        }
    if stage_id == "order_attempt":
        return {
            "actionId": "inspect_order_attempt_feedback",
            "stage": stage_id,
            "labelZh": "检查订单触发反馈",
            "priority": 50,
            "reasonZh": reason or "尚未看到订单尝试反馈。",
            "nextRequiredActionZh": "若前置阶段均已放行但仍无反馈，检查 EA 触发日志和执行反馈文件；当前工具仍不写单。",
            "expectedEvidence": {
                "file": str(stage.get("source") or ""),
                "fields": ["send/fill/reject/entry event"],
            },
        }
    return {
        "actionId": "review_latency_blocker",
        "stage": stage_id,
        "labelZh": "复核入场阻断",
        "priority": 90,
        "reasonZh": reason,
        "nextRequiredActionZh": "复核入场延迟时间线，先修复最早的 hard blocker。",
        "expectedEvidence": {"file": str(stage.get("source") or ""), "fields": []},
    }


def _recovery_actions(stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for stage in stages:
        if stage.get("status") in {"MISSING", "DEGRADED", "BLOCKED", "STARTUP_GUARD", "SPREAD_BLOCK", "NO_ATTEMPT", "STALE_ATTEMPT"}:
            rows.append(_recovery_action_for_stage(stage))
    rows.sort(key=lambda item: int(item.get("priority") or 99))
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = str(row.get("actionId") or "")
        if key and key not in seen:
            deduped.append(row)
            seen.add(key)
    return deduped


def _recovery_actions_for_gaps(gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    mismatch = next((gap for gap in gaps if gap.get("gapId") == "policy_ea_signal_alignment" and not gap.get("passed")), {})
    if mismatch:
        detail = mismatch.get("detail") if isinstance(mismatch.get("detail"), dict) else {}
        demoted = detail.get("demotedOutOfScopeSignal") if isinstance(detail.get("demotedOutOfScopeSignal"), dict) else {}
        demoted_reason = str(demoted.get("reasonZh") or "").strip()
        rows.append({
            "actionId": "evaluate_signal_direction_shadow_lane",
            "stage": "policy",
            "labelZh": "评估信号方向影子车道",
            "priority": 28,
            "reasonZh": demoted_reason or str(mismatch.get("current") or "live policy 与 EA RSI 当前信号方向不一致。"),
            "nextRequiredActionZh": (
                "SELL 侧已降级时，继续把该方向保持在 shadow/tester 里补齐样本、动态止盈止损和复盘证据；不要直接扩大 live 方向。"
                if demoted
                else "当前 EA RSI 信号方向与 live policy 方向不一致；先把该方向保持在 shadow/tester 里补齐样本、动态止盈止损和评审证据，不要直接扩大 live 方向。"
            ),
            "expectedEvidence": {
                "file": "adaptive/QuantGod_USDJPYAutoExecutionPolicy.json",
                "fields": [
                    "topShadowPolicy direction matches EA signal",
                    "shadow sample non-negative",
                    "dynamic SLTP matches direction",
                    "live preset mutation remains false",
                ],
            },
        })
    return rows


def _stage_map(stages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(stage.get("stage") or ""): stage for stage in stages}


def _readiness_gap(
    gap_id: str,
    stage: str,
    label_zh: str,
    passed: bool,
    current: Any,
    required: Any,
    next_required_action_zh: str,
    *,
    essential: bool = True,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "gapId": gap_id,
        "stage": stage,
        "labelZh": label_zh,
        "passed": bool(passed),
        "essential": bool(essential),
        "current": current,
        "required": required,
        "nextRequiredActionZh": next_required_action_zh,
    }
    if detail:
        row["detail"] = detail
    return row


def _readiness_gaps(stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_stage = _stage_map(stages)
    market = by_stage.get("market_data", {})
    policy = by_stage.get("policy", {})
    ea = by_stage.get("ea_guard", {})
    order = by_stage.get("order_attempt", {})

    market_status = str(market.get("status") or "MISSING")
    policy_status = str(policy.get("status") or "MISSING")
    ea_status = str(ea.get("status") or "MISSING")
    order_status = str(order.get("status") or "NO_ATTEMPT")

    signal_quorum = _num(policy.get("signalQuorum"), -1.0)
    signal_required = _num(policy.get("signalQuorumRequired"), -1.0)
    has_quorum = signal_quorum >= 0 and signal_required > 0
    signal_gap = max(0.0, signal_required - signal_quorum) if has_quorum else None
    signal_passed = (
        (signal_quorum >= signal_required)
        if has_quorum
        else policy_status == "READY"
    )

    confirmations = policy.get("tacticalConfirmations") if isinstance(policy.get("tacticalConfirmations"), dict) else {}
    confirmation_map = confirmations.get("confirmations") if isinstance(confirmations.get("confirmations"), dict) else {}
    shadow_sample = confirmation_map.get("影子样本未显示负期望")
    shadow_passed = bool(shadow_sample) if shadow_sample is not None else policy_status == "READY"

    entry_mode = str(policy.get("entryMode") or "UNKNOWN")
    policy_entry_passed = (
        policy_status == "READY"
        and bool(policy.get("allowed"))
        and entry_mode in {"STANDARD_ENTRY", "OPPORTUNITY_ENTRY"}
    )

    startup_active = bool(ea.get("startupGuardActive")) or ea_status == "STARTUP_GUARD"
    spread_allowed = ea.get("spreadAllowed")
    spread_passed = ea_status != "SPREAD_BLOCK" and spread_allowed is not False
    ea_guard_passed = ea_status == "READY"
    policy_direction = _normalize_direction(policy.get("direction"))
    ea_signal_direction = _normalize_direction(ea.get("signalDirection"))
    ea_signal_ready = bool(ea.get("signalReady"))
    signal_alignment_passed = not (ea_signal_ready and policy_direction and ea_signal_direction and policy_direction != ea_signal_direction)
    shadow = policy.get("topShadowPolicy") if isinstance(policy.get("topShadowPolicy"), dict) else {}
    demoted_signal = _demoted_out_of_scope_signal(policy_direction, ea_signal_direction, ea)

    gaps = [
        _readiness_gap(
            "market_data_ready",
            "market_data",
            "快通道行情可用",
            market_status == "READY",
            market_status,
            "READY",
            "恢复 MT5 快通道质量报告，确认 heartbeat、tick 和指标都新鲜。",
            detail={
                "quality": market.get("quality"),
                "heartbeatFresh": market.get("heartbeatFresh"),
                "ageSeconds": market.get("ageSeconds"),
            },
        ),
        _readiness_gap(
            "policy_entry_mode",
            "policy",
            "策略政策允许入场复核",
            policy_entry_passed,
            entry_mode,
            "STANDARD_ENTRY/OPPORTUNITY_ENTRY",
            "刷新 adaptive policy，直到 top policy 给出合规 entryMode 和 allowed=true。",
            detail={
                "allowed": policy.get("allowed"),
                "strategy": policy.get("strategy"),
                "direction": policy.get("direction"),
                "score": policy.get("score"),
                "entryStrictness": policy.get("entryStrictness"),
            },
        ),
        _readiness_gap(
            "policy_ea_signal_alignment",
            "policy",
            "Live policy 与 EA RSI 信号方向一致",
            signal_alignment_passed,
            (
                f"policy={policy_direction or 'UNKNOWN'} / ea={ea_signal_direction or 'UNKNOWN'}"
                if ea_signal_ready
                else "EA_SIGNAL_NOT_READY"
            ),
            "方向一致，或不一致方向保持 shadow/tester 评审",
            "当前 EA RSI 信号与 live policy 方向不一致；先补齐该方向 shadow/tester 样本和动态 SLTP，不直接扩大实盘方向。",
            detail={
                "policyStrategy": policy.get("strategy"),
                "policyDirection": policy_direction or policy.get("direction"),
                "eaSignalReady": ea_signal_ready,
                "eaSignalDirection": ea_signal_direction or ea.get("signalDirectionRaw"),
                "eaEvalCode": ea.get("evalCode"),
                "eaEvalReason": ea.get("evalReason"),
                "demotedOutOfScopeSignal": demoted_signal or None,
                "topShadowPolicy": shadow,
            },
        ),
        _readiness_gap(
            "signal_quorum",
            "policy",
            "信号 quorum 达标",
            signal_passed,
            f"{signal_quorum:.0f}/{signal_required:.0f}" if has_quorum else "UNKNOWN",
            "signalQuorum >= signalQuorumRequired",
            "继续刷新 tick、策略和影子样本，等信号 quorum 达标后再进入下一步复核。",
            detail={
                "signalQuorum": policy.get("signalQuorum"),
                "signalQuorumRequired": policy.get("signalQuorumRequired"),
                "signalQuorumGap": signal_gap,
            },
        ),
        _readiness_gap(
            "shadow_sample_non_negative",
            "policy",
            "影子样本未显示负期望",
            shadow_passed,
            shadow_sample if shadow_sample is not None else "UNKNOWN",
            True,
            "继续累积 shadow 样本；样本没有证明非负期望前不要进入执行复核。",
            detail={"confirmationKey": "影子样本未显示负期望"},
        ),
        _readiness_gap(
            "ea_startup_guard_clear",
            "ea_guard",
            "EA 启动保护解除",
            not startup_active and ea_status != "MISSING",
            ea.get("startupGuardActive") if ea.get("startupGuardActive") is not None else ea_status,
            "startupGuardActive=false",
            "等待下一根 H1 bar 或刷新 EA 入场诊断，直到启动保护解除。",
            detail={"state": ea.get("state"), "startupGuardReason": ea.get("startupGuardReason")},
        ),
        _readiness_gap(
            "ea_spread_gate",
            "ea_guard",
            "EA 点差守门通过",
            spread_passed and ea_status != "MISSING",
            ea.get("spreadPips") if ea.get("spreadPips") not in (None, "") else ea_status,
            "spreadAllowed=true",
            "等待 USDJPY 点差恢复到策略阈值内，保持点差硬守门不绕过。",
            detail={"spreadAllowed": spread_allowed, "spreadPips": ea.get("spreadPips")},
        ),
        _readiness_gap(
            "ea_entry_guard_ready",
            "ea_guard",
            "EA 入场守门可复核",
            ea_guard_passed,
            ea_status,
            "READY",
            "检查 EA 入场诊断里的 whyNoEntry/guards，确认非启动保护、非点差、非新闻硬阻断。",
            detail={"state": ea.get("state"), "reasonZh": ea.get("reasonZh")},
        ),
        _readiness_gap(
            "order_attempt_feedback_seen",
            "order_attempt",
            "订单反馈只读证据",
            order_status == "ATTEMPTED",
            order_status,
            "ATTEMPTED after reviewed execution lane",
            "前置阶段都放行后，再用只读反馈检查 EA 是否出现 send/fill/reject/entry 事件；当前链路仍不写单。",
            essential=False,
            detail={"eventType": order.get("eventType"), "rejectReason": order.get("rejectReason")},
        ),
    ]
    return gaps


def _entry_readiness(gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    essential = [gap for gap in gaps if gap.get("essential")]
    passed = [gap for gap in essential if gap.get("passed")]
    failed = [gap for gap in essential if not gap.get("passed")]
    score = round((len(passed) / len(essential)) * 100.0, 1) if essential else 0.0
    first_failed = failed[0] if failed else {}
    return {
        "score": score,
        "passedEssentialCount": len(passed),
        "essentialCount": len(essential),
        "failedEssentialCount": len(failed),
        "readyForEntryReview": bool(essential) and not failed,
        "failedGapIds": [str(gap.get("gapId") or "") for gap in failed],
        "firstFailedGapId": first_failed.get("gapId"),
        "firstFailedLabelZh": first_failed.get("labelZh"),
        "nextRequiredActionZh": (
            first_failed.get("nextRequiredActionZh")
            if first_failed
            else "所有前置就绪缺口已通过；只允许进入单独审查过的执行复核，不自动下单。"
        ),
    }


def build_report(runtime_dir: str | Path, *, symbol: str = FOCUS_SYMBOL, write: bool = False) -> Dict[str, Any]:
    runtime = Path(runtime_dir)
    now = datetime.now(timezone.utc)
    stages = [
        _fastlane_stage(runtime, now, symbol),
        _policy_stage(runtime, now),
        _ea_stage(runtime, now),
        _order_stage(runtime, now),
    ]
    attribution = _primary_attribution(stages)
    latency = {
        "marketDataToPolicyMs": _diff_ms(stages[0], stages[1]),
        "policyToEaMs": _diff_ms(stages[1], stages[2]),
        "eaToOrderAttemptMs": _diff_ms(stages[2], stages[3]),
    }
    missing = [stage["stage"] for stage in stages if stage.get("status") == "MISSING"]
    blockers = [
        {
            "stage": stage.get("stage"),
            "labelZh": stage.get("labelZh"),
            "status": stage.get("status"),
            "reasonZh": stage.get("reasonZh"),
            "hard": stage.get("status") in {"MISSING", "DEGRADED", "BLOCKED", "STARTUP_GUARD", "SPREAD_BLOCK"},
        }
        for stage in stages
        if stage.get("status") in {"MISSING", "DEGRADED", "BLOCKED", "STARTUP_GUARD", "SPREAD_BLOCK"}
    ]
    readiness_gaps = _readiness_gaps(stages)
    recovery_actions = _recovery_actions(stages) + _recovery_actions_for_gaps(readiness_gaps)
    recovery_actions.sort(key=lambda item: int(item.get("priority") or 99))
    deduped_recovery_actions: List[Dict[str, Any]] = []
    seen_recovery_action_ids = set()
    for row in recovery_actions:
        action_id = str(row.get("actionId") or "")
        if action_id and action_id not in seen_recovery_action_ids:
            deduped_recovery_actions.append(row)
            seen_recovery_action_ids.add(action_id)
    recovery_actions = deduped_recovery_actions
    entry_readiness = _entry_readiness(readiness_gaps)
    next_required_action = (
        recovery_actions[0].get("nextRequiredActionZh")
        if recovery_actions
        else entry_readiness.get("nextRequiredActionZh")
    )
    summary = {
        "state": attribution["status"],
        "stateZh": attribution["labelZh"],
        "primaryStage": attribution["stage"],
        "primaryReasonZh": attribution["reasonZh"],
        "nextRequiredActionZh": next_required_action,
        "readinessScore": entry_readiness.get("score"),
        "readyForEntryReview": entry_readiness.get("readyForEntryReview"),
        "failedReadinessGapIds": entry_readiness.get("failedGapIds"),
        "firstFailedReadinessGapId": entry_readiness.get("firstFailedGapId"),
        "recoveryActionCount": len(recovery_actions),
        "missingStages": missing,
        "startupGuardActive": any(bool(stage.get("startupGuardActive")) for stage in stages),
        "spreadPips": next((stage.get("spreadPips") for stage in stages if stage.get("spreadPips") not in (None, "")), None),
        "orderAttemptSeen": any(stage.get("status") == "ATTEMPTED" for stage in stages),
    }
    payload = {
        "schema": SCHEMA,
        "generatedAt": utc_now_iso(),
        "runtimeDir": str(runtime),
        "symbol": symbol,
        "summary": summary,
        "timeline": stages,
        "latency": latency,
        "blockers": blockers,
        "recoveryActions": recovery_actions,
        "readinessGaps": readiness_gaps,
        "entryReadiness": entry_readiness,
        "nextRequiredActionZh": next_required_action,
        "sourceFiles": {
            "fastlane": str(runtime / "quality" / "QuantGod_MT5FastLaneQuality.json"),
            "policy": str(runtime / "adaptive" / "QuantGod_USDJPYAutoExecutionPolicy.json"),
            "eaDiagnostics": str(runtime / "QuantGod_USDJPYRsiEntryDiagnostics.json"),
            "executionFeedback": str(runtime / "evidence_os" / "QuantGod_LiveExecutionFeedback.jsonl"),
        },
        "safety": safety_payload(),
    }
    if write:
        write_report(runtime, payload)
    return payload


def write_report(runtime_dir: str | Path, payload: Dict[str, Any]) -> None:
    target = report_path(runtime_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    ledger = ledger_path(runtime_dir)
    exists = ledger.exists()
    summary = payload.get("summary") or {}
    latency = payload.get("latency") or {}
    with ledger.open("a", encoding="utf-8", newline="") as handle:
        fields = [
            "generatedAt",
            "symbol",
            "state",
            "primaryStage",
            "primaryReasonZh",
            "policyToEaMs",
            "eaToOrderAttemptMs",
            "startupGuardActive",
            "spreadPips",
            "orderAttemptSeen",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "generatedAt": payload.get("generatedAt"),
            "symbol": payload.get("symbol"),
            "state": summary.get("state"),
            "primaryStage": summary.get("primaryStage"),
            "primaryReasonZh": str(summary.get("primaryReasonZh") or "")[:400],
            "policyToEaMs": latency.get("policyToEaMs"),
            "eaToOrderAttemptMs": latency.get("eaToOrderAttemptMs"),
            "startupGuardActive": str(bool(summary.get("startupGuardActive"))).lower(),
            "spreadPips": summary.get("spreadPips"),
            "orderAttemptSeen": str(bool(summary.get("orderAttemptSeen"))).lower(),
        })


def load_or_build(runtime_dir: str | Path, *, symbol: str = FOCUS_SYMBOL) -> Dict[str, Any]:
    path = report_path(runtime_dir)
    payload = _read_json(path)
    if payload:
        return payload
    return build_report(runtime_dir, symbol=symbol, write=False)
