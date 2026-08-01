import json
from pathlib import Path

from tools.champion_retest import build_champion_retest_report


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_champion_retest_accepts_stable_usdjpy_candidate(tmp_path: Path) -> None:
    seed_id = "GA-USDJPY-G0004-C0001"
    _write(tmp_path / "agent" / "QuantGod_AceStrategyScout.json", {
        "topQualifiedForex": {"seedId": seed_id},
        "forexContenderReview": {"contenders": [], "requiresParallelTesterForward": False},
    })
    _write(tmp_path / "ga" / "QuantGod_GAEliteStrategies.json", {"elites": [{
        "seedId": seed_id,
        "strategyId": "usd-jpy-champion",
        "fitness": 9.1,
        "fitnessBreakdown": {
            "strategyBacktest": {"netR": 4, "profitFactor": 1.5, "sharpe": 1.3, "maxDrawdownR": 1, "tradeCount": 30},
            "walkForward": {
                "summary": {"sampleCount": 30, "stabilityScore": 0.9, "promotionAllowed": True, "forwardNetR": 1.2},
                "segments": [{"segment": "validation", "netR": 1, "profitFactor": 1.3, "sharpe": 1.1, "tradeCount": 10}],
            },
        },
    }]})
    report = build_champion_retest_report(tmp_path, write=True)
    assert report["status"] == "CHAMPION_RETEST_PASS"
    assert report["forexChampion"]["status"] == "FOREX_CHAMPION_RETEST_PASS"
    assert report["safety"]["orderSendAllowed"] is False


def test_champion_retest_blocks_missing_forex_metrics(tmp_path: Path) -> None:
    report = build_champion_retest_report(tmp_path)
    assert report["status"] == "CHAMPION_RETEST_NEEDS_MORE_EVIDENCE"
    assert report["forexChampion"]["blockers"]
