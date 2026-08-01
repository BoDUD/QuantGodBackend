from pathlib import Path
from unittest.mock import patch

from tools.live_automation_readiness.builder import build_live_automation_readiness
from tools.live_automation_readiness.preflight import build_live_runtime_preflight_probe


def test_readiness_exposes_only_usdjpy_mt5_lane_and_stays_disabled(tmp_path: Path) -> None:
    report = build_live_automation_readiness(tmp_path)
    assert set(report["lanes"]) == {"usdjpyMt5"}
    assert report["canPromoteToLiveNow"] is False
    assert report["orderSendAllowed"] is False
    assert report["safety"]["writesMt5OrderRequest"] is False


def test_readiness_marks_qualified_forex_as_review_candidate_only(tmp_path: Path) -> None:
    policy = {
        "usdDeploymentGate": {"liveAllowed": True, "targetStage": "USD_MICRO_LIVE", "blockers": []},
        "topLiveEligiblePolicy": {"symbol": "USDJPYc"},
        "topPolicy": {"symbol": "USDJPYc", "strategy": "RSI_Reversal", "direction": "LONG"},
    }
    promotion = {"stage": "MICRO_LIVE", "hardRollback": {"hardBlockers": []}}
    handoff = {"status": "READY", "runtimeFreshness": {"fresh": True, "blockers": []}}
    with patch("tools.live_automation_readiness.builder.build_usdjpy_policy", return_value=policy), patch(
        "tools.live_automation_readiness.builder.build_promotion_decision", return_value=promotion
    ), patch(
        "tools.live_automation_readiness.builder._build_forex_live12_runtime_handoff", return_value=handoff
    ):
        report = build_live_automation_readiness(tmp_path, refresh_sources=True)
    assert report["status"] == "READY_FOR_EXECUTION_REVIEW"
    assert report["lanes"]["usdjpyMt5"]["reviewCandidate"] is True
    assert report["liveExecutionAllowed"] is False


def test_runtime_preflight_fails_closed_without_dashboard(tmp_path: Path) -> None:
    report = build_live_runtime_preflight_probe(tmp_path)
    codes = {row["code"] for row in report["blockers"]}
    assert "MT5_DASHBOARD_SNAPSHOT_MISSING" in codes
    assert report["runtimeProbePassed"] is False
    assert report["orderSendAllowed"] is False
