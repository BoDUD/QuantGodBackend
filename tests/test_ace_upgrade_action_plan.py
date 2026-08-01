import json
from pathlib import Path

from tools.ace_upgrade_action_plan import build_ace_upgrade_action_plan


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_upgrade_plan_is_forex_only_and_review_only(tmp_path: Path) -> None:
    _write(tmp_path / "agent" / "QuantGod_AceExecutionCandidatePack.json", {
        "schema": "quantgod.ace_execution_candidate_pack.v1",
        "status": "ACE_EXECUTION_CANDIDATE_PACK_READY",
        "liveUpgradeSelection": {"selectedStrategy": {"seedId": "GA-USDJPY-G0003-C0001"}},
    })
    _write(tmp_path / "agent" / "QuantGod_ChampionTesterRunGate.json", {"gate": {"blockers": []}})
    _write(tmp_path / "agent" / "QuantGod_LiveRuntimePreflightProbe.json", {"status": "WAITING_EXECUTION_MODE_ACTIVATION"})
    _write(tmp_path / "QuantGod_IsolatedTesterAccountContextStatus.json", {"ready": True})
    report = build_ace_upgrade_action_plan(tmp_path, write=True)
    assert report["selectedLane"] == "forexMt5"
    assert report["status"] == "ACE_UPGRADE_READY_FOR_FOREX_TESTER_REVIEW"
    assert report["processEvidence"]["launchesTerminal"] is False
    assert report["safety"]["orderSendAllowed"] is False


def test_upgrade_plan_fails_closed_when_sources_are_missing(tmp_path: Path) -> None:
    report = build_ace_upgrade_action_plan(tmp_path)
    assert report["status"] == "ACE_UPGRADE_WAITING_TESTER_ENVIRONMENT"
    assert report["blockers"]
