import json
from pathlib import Path

from tools.profit_target_tracker.builder import build_profit_target_tracker


def test_profit_tracker_counts_only_verified_forex_usd(tmp_path: Path) -> None:
    path = tmp_path / "evidence_os" / "QuantGod_LiveExecutionFeedback.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        {"feedbackId": "fx-1", "eventType": "ORDER_CLOSE", "symbol": "USDJPYc", "profitUsd": 32.0},
        {"feedbackId": "fx-2", "eventType": "ORDER_CLOSE", "symbol": "EURUSD", "profitUsd": 21.0},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    report = build_profit_target_tracker(tmp_path, target_usd=50, write=True)
    assert report["targetReached"] is True
    assert report["combinedTarget"]["combinedVerifiedUsdProfit"] == 53.0
    assert set(report["laneTargets"]) == {"forexMt5"}
    assert report["simToLiveDecision"]["canPromoteToLiveNow"] is False


def test_profit_tracker_waits_for_verifiable_forex_evidence(tmp_path: Path) -> None:
    report = build_profit_target_tracker(tmp_path)
    assert report["targetReached"] is False
    assert report["progress"]["verifiedUsdProfit"] == 0.0
    assert report["safety"]["orderSendAllowed"] is False
