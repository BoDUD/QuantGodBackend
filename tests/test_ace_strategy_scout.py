import json
from pathlib import Path

from tools.ace_strategy_scout import build_ace_strategy_scout


def _write_elites(runtime: Path, *, sample_count: int = 30, stability: float = 0.9) -> None:
    path = runtime / "ga" / "QuantGod_GAEliteStrategies.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "elites": [{
            "seedId": "GA-USDJPY-G0001-C0001",
            "strategyId": "usd-jpy-elite",
            "strategyFamily": "RSI_Reversal",
            "direction": "LONG",
            "fitness": 8.5,
            "fitnessBreakdown": {
                "strategyBacktest": {
                    "netR": 4.2,
                    "profitFactor": 1.6,
                    "sharpe": 1.4,
                    "maxDrawdownR": 1.1,
                    "tradeCount": sample_count,
                },
                "walkForward": {"summary": {
                    "sampleCount": sample_count,
                    "stabilityScore": stability,
                    "forwardNetR": 1.2,
                    "promotionAllowed": True,
                }},
            },
        }],
    }), encoding="utf-8")


def test_scout_selects_only_qualified_usdjpy_forex(tmp_path: Path) -> None:
    _write_elites(tmp_path)
    report = build_ace_strategy_scout(tmp_path, write=True)
    assert report["status"] == "ACE_FOREX_SCOUT_READY"
    assert report["topQualifiedForex"]["seedId"] == "GA-USDJPY-G0001-C0001"
    assert report["topQualifiedForex"]["lane"] == "usdjpy_ga_elite"
    assert report["safety"]["orderSendAllowed"] is False


def test_scout_fails_closed_for_weak_evidence(tmp_path: Path) -> None:
    _write_elites(tmp_path, sample_count=5, stability=0.4)
    report = build_ace_strategy_scout(tmp_path)
    assert report["status"] == "ACE_FOREX_SCOUT_WAITING_EVIDENCE"
    assert report["topQualifiedForex"] == {}
    assert report["candidates"][0]["qualified"] is False
