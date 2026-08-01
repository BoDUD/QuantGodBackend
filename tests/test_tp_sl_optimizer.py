import csv
from pathlib import Path

from tools.tp_sl_optimizer import build_tp_sl_optimizer_report


def test_tp_sl_optimizer_builds_usdjpy_forex_grid(tmp_path: Path) -> None:
    path = tmp_path / "backtest" / "QuantGod_StrategyTrades.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "riskPips", "mfeR", "maeR", "grossProfitPips", "profitPips", "costPips", "exitReason"])
        writer.writeheader()
        for index in range(30):
            writer.writerow({
                "symbol": "USDJPYc",
                "riskPips": 10,
                "mfeR": 2 if index % 3 else 0.5,
                "maeR": 0.4 if index % 4 else 1.2,
                "grossProfitPips": 12 if index % 3 else -10,
                "profitPips": 11 if index % 3 else -11,
                "costPips": 1,
                "exitReason": "TEST",
            })
    report = build_tp_sl_optimizer_report(tmp_path, write=True)
    assert report["status"] == "TPSL_OPTIMIZER_READY"
    assert report["forexMt5"]["sourceTradeCount"] == 30
    assert report["forexMt5"]["topCandidates"]
    assert report["decision"]["mayPlaceOrders"] is False
    assert report["safety"]["livePresetMutationAllowed"] is False
