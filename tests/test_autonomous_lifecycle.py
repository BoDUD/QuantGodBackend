from pathlib import Path

from tools.autonomous_lifecycle.cent_account_rules import cent_account_config
from tools.autonomous_lifecycle.lifecycle import build_autonomous_lifecycle
from tools.autonomous_lifecycle.mt5_shadow_lane import build_mt5_shadow_lane


def test_lifecycle_contains_only_forex_mt5_lanes(tmp_path: Path) -> None:
    payload = build_autonomous_lifecycle(tmp_path, write=True)
    assert set(payload["lanes"]) == {
        "live",
        "centLive",
        "usdDeployment",
        "globalUsdJpyExposureGuard",
        "mt5Shadow",
    }
    assert payload["symbol"] == "USDJPYc"
    assert payload["safety"]["orderSendAllowed"] is False
    assert payload["safety"]["operatorApprovalRequired"] is True
    assert payload["safety"]["unattendedLiveExpansionAllowed"] is False
    assert payload["safety"]["liveExpansionAllowed"] is False
    assert payload["lanes"]["live"]["enabled"] is False
    assert payload["accountRegistry"]["accounts"][0]["defaultStage"] == "CENT_PAPER"
    assert payload["accountRegistry"]["accounts"][0]["liveStages"] == []
    assert payload["accountRegistry"]["accounts"][1]["defaultStage"] == "USD_PAPER_MIRROR"
    assert payload["accountRegistry"]["accounts"][1]["liveStages"] == []
    assert (tmp_path / "agent" / "QuantGod_AutonomousLifecycle.json").exists()


def test_mt5_shadow_lane_keeps_strategy_pool_non_live(tmp_path: Path) -> None:
    payload = build_mt5_shadow_lane(tmp_path, write=True)
    assert payload["safety"]["orderSendAllowed"] is False
    assert payload["safety"]["livePresetMutationAllowed"] is False
    assert payload["safety"]["operatorApprovalRequired"] is True
    assert payload["safety"]["unattendedLiveExpansionAllowed"] is False
    assert payload["safety"]["liveExpansionAllowed"] is False


def test_cent_account_configuration_keeps_lot_cap() -> None:
    config = cent_account_config()
    assert config["accountMode"] == "cent"
    assert config["maxLot"] <= 2.0
    assert config["centAccountAcceleration"] is False
    assert config["centFastPromotion"] is False
    assert config["microLiveLot"] == 0.0
    assert config["liveExpansionAllowed"] is False
