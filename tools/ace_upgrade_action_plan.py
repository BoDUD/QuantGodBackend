"""Build a read-only USDJPY forex upgrade action plan."""

from __future__ import annotations

import json
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _artifact(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "generatedAtIso": payload.get("generatedAtIso") or payload.get("generatedAt"),
    }


def _action(action_id: str, priority: int, title_zh: str, blockers: list[str], command: str | None = None) -> dict[str, Any]:
    row = {
        "id": action_id,
        "priority": priority,
        "titleZh": title_zh,
        "status": "BLOCKED" if blockers else "READY_FOR_REVIEW",
        "blockers": blockers,
        "orderSendAllowed": False,
        "mt5OrderSendAllowed": False,
        "writesMt5OrderRequest": False,
        "writesLivePreset": False,
    }
    if command:
        row["readOnlyCommand"] = command
    return row


def build_ace_upgrade_action_plan(runtime_dir: Path, *, write: bool = False) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    agent = runtime / "agent"
    paths = {
        "aceExecutionCandidatePack": agent / "QuantGod_AceExecutionCandidatePack.json",
        "championPromotionGate": agent / "QuantGod_ChampionPromotionGate.json",
        "championTesterRunGate": agent / "QuantGod_ChampionTesterRunGate.json",
        "liveRuntimePreflightProbe": agent / "QuantGod_LiveRuntimePreflightProbe.json",
        "liveEvidenceIntake": agent / "QuantGod_LiveEvidenceIntake.json",
        "isolatedTesterAccountContextStatus": runtime / "QuantGod_IsolatedTesterAccountContextStatus.json",
    }
    sources = {key: _read_json(path) for key, path in paths.items()}
    pack = sources["aceExecutionCandidatePack"]
    run_gate = sources["championTesterRunGate"]
    preflight = sources["liveRuntimePreflightProbe"]
    account_context = sources["isolatedTesterAccountContextStatus"]
    selected = _dict(_dict(pack.get("liveUpgradeSelection")).get("selectedStrategy"))
    gate_blockers = [str(value) for value in _list(_dict(run_gate.get("gate")).get("blockers")) if value]
    actions = [
        _action(
            "build_forex_candidate_pack",
            1,
            "生成 USDJPY 外汇王牌候选包",
            [] if pack else ["ACE_EXECUTION_CANDIDATE_PACK_MISSING"],
            "python3 tools/run_ace_execution_candidate_pack.py build --write",
        ),
        _action(
            "run_forex_ab_tester_forward",
            2,
            "运行隔离 MT5 tester/forward A/B",
            gate_blockers or ([] if selected else ["FOREX_CHAMPION_MISSING"]),
        ),
        _action(
            "refresh_forex_runtime_preflight",
            3,
            "刷新 USDJPY MT5 runtime 预检",
            [] if preflight else ["LIVE_RUNTIME_PREFLIGHT_MISSING"],
            "python3 tools/run_live_automation_readiness.py preflight --write",
        ),
        _action(
            "review_isolated_account_context",
            4,
            "复核隔离 tester 账户上下文",
            [] if account_context.get("ready") else ["ISOLATED_TESTER_ACCOUNT_CONTEXT_NOT_READY"],
        ),
    ]
    blockers = list(dict.fromkeys(code for row in actions for code in _list(row.get("blockers")) if code))
    payload = {
        "ok": True,
        "schema": SCHEMA,
        "generatedAtIso": _now_iso(),
        "runtimeDir": str(runtime),
        "status": "ACE_UPGRADE_READY_FOR_FOREX_TESTER_REVIEW" if not blockers else "ACE_UPGRADE_WAITING_TESTER_ENVIRONMENT",
        "statusZh": "外汇升级动作已可审查" if not blockers else "外汇升级仍等待 tester/runtime 证据",
        "selectedLane": "forexMt5",
        "selectedStrategy": selected,
        "sourceArtifacts": {key: _artifact(paths[key], value) for key, value in sources.items()},
        "processEvidence": {
            "checked": False,
            "reason": "Action plan is filesystem-only and does not inspect or launch terminal processes.",
            "launchesTerminal": False,
        },
        "processBlockers": [],
        "actions": actions,
        "blockers": blockers,
        "nextRequiredActionZh": "先闭环 tester/runtime 证据，再进入独立 release review；本计划不启动 MT5、不写订单。",
        "safety": dict(SAFETY),
        "reportPath": str(runtime / REPORT_PATH),
    }
    if write:
        _write_json(runtime / REPORT_PATH, payload)
    return payload


def read_ace_upgrade_action_plan(runtime_dir: Path) -> dict[str, Any]:
    payload = _read_json(Path(runtime_dir) / REPORT_PATH)
    return payload if payload else build_ace_upgrade_action_plan(Path(runtime_dir), write=False)
