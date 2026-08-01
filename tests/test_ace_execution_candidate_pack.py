import json
from pathlib import Path

from tools.ace_execution_candidate_pack import build_ace_execution_candidate_pack


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_candidate_pack_contains_forex_lane_only(tmp_path: Path) -> None:
    _write_json(tmp_path / "agent" / "QuantGod_AceStrategyScout.json", {
        "topQualifiedForex": {
            "seedId": "GA-USDJPY-G0002-C0001",
            "strategyId": "usd-jpy-ace",
            "strategyFamily": "RSI_Reversal",
            "direction": "LONG",
            "fitness": 9.0,
            "blockers": [],
        },
        "candidates": [],
        "forexContenderReview": {"contenders": [], "requiresParallelTesterForward": False},
    })
    _write_json(tmp_path / "agent" / "QuantGod_ChampionRetestReport.json", {
        "forexChampion": {
            "status": "FOREX_CHAMPION_RETEST_PASS",
            "seedId": "GA-USDJPY-G0002-C0001",
            "strategyId": "usd-jpy-ace",
            "backtest": {"profitFactor": 1.7, "sharpe": 1.5, "tradeCount": 35},
            "walkForward": {"stabilityScore": 0.91, "forwardNetR": 1.1},
            "blockers": [],
        },
    })
    report = build_ace_execution_candidate_pack(tmp_path, write=True)
    assert report["status"] == "ACE_EXECUTION_CANDIDATE_PACK_READY"
    assert report["liveUpgradeSelection"]["selectedLane"] == "forexMt5"
    assert set(report["strategyShortlist"]) >= {"forexTopStrategies", "comparisonRequired"}
    assert report["finalVerdict"]["canPromoteToLiveNow"] is False
    assert report["safety"]["writesMt5OrderRequest"] is False


def test_candidate_pack_waits_when_forex_evidence_missing(tmp_path: Path) -> None:
    report = build_ace_execution_candidate_pack(tmp_path)
    assert report["status"] == "ACE_EXECUTION_CANDIDATE_PACK_WAITING_EVIDENCE"
    assert report["forexMt5"]["reviewCandidate"] is False
