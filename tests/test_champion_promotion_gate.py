import json
from pathlib import Path
from unittest.mock import patch

from tools.champion_promotion_gate import build_champion_promotion_gate


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_promotion_gate_selects_forex_and_never_promotes_live(tmp_path: Path) -> None:
    seed_id = "GA-USDJPY-G0005-C0001"
    _write(tmp_path / "agent" / "QuantGod_AceStrategyScout.json", {
        "topQualifiedForex": {"seedId": seed_id, "strategyId": "usd-jpy-promotion"},
    })
    _write(tmp_path / "agent" / "QuantGod_ChampionRetestReport.json", {
        "forexChampion": {"seedId": seed_id, "status": "FOREX_CHAMPION_RETEST_PASS"},
    })
    with patch("tools.champion_promotion_gate.build_champion_tester_run_gate") as gate:
        gate.return_value = {"status": "BLOCKED", "gate": {"blockers": ["TESTER_LOCK_MISSING"]}}
        report = build_champion_promotion_gate(tmp_path)
    assert report["selectedChampion"]["lane"] == "usdjpy_ga_elite"
    assert report["promotionDecision"]["canPromoteToLiveNow"] is False
    assert report["safety"]["mt5OrderSendAllowed"] is False
