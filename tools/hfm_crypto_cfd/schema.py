from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.state.v1"
EXECUTION_SPEC_REVIEW_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.execution_spec_review.v1"
CONTRACT_SPEC_EXPORT_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.contract_spec_export.v1"
EVIDENCE_KIT_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.evidence_kit.v1"
SIMULATION_PROFILE_REVIEW_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.simulation_profile_review.v1"
RATES_EXPORT_REVIEW_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.rates_export_review.v1"
MT5_EXPORTER_REVIEW_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.mt5_exporter_review.v1"
MT5_EXPORTER_UPGRADE_BUNDLE_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.mt5_exporter_upgrade_bundle.v1"
MT5_EXPORTER_DEPLOY_PLAN_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.mt5_exporter_deploy_plan.v1"
STANDALONE_EXPORTER_BUNDLE_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.standalone_exporter_bundle.v1"
MT5_POST_UPGRADE_VERIFY_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.mt5_post_upgrade_verify.v1"
POST_UPGRADE_CONTROLLER_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.post_upgrade_controller.v1"
FILLED_INPUT_VALIDATOR_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.filled_input_validator.v1"
EVIDENCE_BOOTSTRAP_SCHEMA_VERSION = "quantgod.hfm_crypto_cfd.evidence_bootstrap.v1"
STATE_FILE = "QuantGod_HFMCryptoCfdState.json"
MOSS_BACKTEST_FILE = "QuantGod_HFMCryptoMossBacktestProfile.json"
EXECUTION_SPEC_REVIEW_FILE = "QuantGod_HFMCryptoExecutionSpecReview.json"
CONTRACT_SPEC_EXPORT_FILE = "QuantGod_HFMCryptoContractSpecExport.json"
EA_SYMBOL_SPECS_FILE = "QuantGod_HFMCryptoSymbolSpecs.json"
EA_RUNTIME_PROBE_FILE = "QuantGod_HFMCryptoRuntimeProbe.json"
EVIDENCE_KIT_FILE = "QuantGod_HFMCryptoEvidenceKit.json"
CONTRACT_SPEC_TEMPLATE_FILE = "QuantGod_HFMCryptoContractSpecTemplate.json"
CONTRACT_SPEC_TEMPLATE_CSV_FILE = "QuantGod_HFMCryptoContractSpecTemplate.csv"
SIMULATION_PROFILE_REVIEW_FILE = "QuantGod_HFMCryptoSimulationProfileReview.json"
EA_RATES_EXPORT_FILE = "QuantGod_HFMCryptoRatesExport.json"
RATES_EXPORT_REVIEW_FILE = "QuantGod_HFMCryptoRatesExportReview.json"
RATES_AUTOGEN_PROFILE_FILE = "hfm_crypto_simulation_profile.autogen.json"
SIMULATION_PROFILE_TEMPLATE_FILE = "QuantGod_HFMCryptoSimulationProfileTemplate.json"
MT5_EXPORTER_REVIEW_FILE = "QuantGod_HFMCryptoMt5ExporterReview.json"
MT5_EXPORTER_UPGRADE_BUNDLE_FILE = "QuantGod_HFMCryptoMt5ExporterUpgradeBundle.json"
MT5_EXPORTER_DEPLOY_PLAN_FILE = "QuantGod_HFMCryptoMt5ExporterDeployPlan.json"
MT5_EXPORTER_UPGRADE_BUNDLE_DIR = "mt5_ea_upgrade_bundle"
STANDALONE_EXPORTER_BUNDLE_FILE = "QuantGod_HFMCryptoStandaloneExporterBundle.json"
STANDALONE_EXPORTER_BUNDLE_DIR = "standalone_exporter_bundle"
MT5_POST_UPGRADE_VERIFY_FILE = "QuantGod_HFMCryptoMt5PostUpgradeVerify.json"
POST_UPGRADE_CONTROLLER_FILE = "QuantGod_HFMCryptoPostUpgradeController.json"
FILLED_INPUT_VALIDATOR_FILE = "QuantGod_HFMCryptoFilledInputValidator.json"
EVIDENCE_BOOTSTRAP_FILE = "QuantGod_HFMCryptoEvidenceBootstrap.json"
FILLED_CONTRACT_SPEC_FILE = "hfm_crypto_contract_specs.filled.json"
FILLED_SIMULATION_PROFILE_FILE = "hfm_crypto_simulation_profile.filled.json"
CONTRACT_SPEC_DRAFT_FILE = "hfm_crypto_contract_specs.draft.json"
SIMULATION_PROFILE_DRAFT_FILE = "hfm_crypto_simulation_profile.draft.json"
OPERATOR_APPROVAL_DRAFT_FILE = "operator_approval.draft.json"

SAFETY: dict[str, Any] = {
    "readOnly": True,
    "shadowOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "mt5OrderSendAllowed": False,
    "mt5SymbolSelectAllowed": False,
    "walletAuthorizationAllowed": False,
    "credentialStorageAllowed": False,
    "copyTradeExecutionAllowed": False,
    "mossExecutionAllowed": False,
    "hyperliquidExecutionAllowed": False,
    "livePresetMutationAllowed": False,
    "externalMarketRemoved": True,
}

EXECUTION_FLAG_KEYS = {
    "adapterExecutionAllowed",
    "autoPromotionToLiveAllowed",
    "brokerCallsMade",
    "brokerExecutionAllowed",
    "canPromoteToLiveNow",
    "closeAllowed",
    "copyTradeExecutionAllowed",
    "credentialStorageAllowed",
    "deployCommandExecuted",
    "hfmCryptoExecutionAllowed",
    "hyperliquidExecutionAllowed",
    "installedFilesMutated",
    "livePresetMutationAllowed",
    "mossExecutionAllowed",
    "mt5OrderSendAllowed",
    "orderSendAllowed",
    "requestFilesWritten",
    "requestWritesAllowed",
    "rollbackCommandExecuted",
    "scriptRunAttempted",
    "walletAuthorizationAllowed",
    "writesMt5OrderRequest",
    "writesMt5Preset",
}

HFM_CRYPTO_USD_CANONICALS: tuple[str, ...] = (
    "AAVEUSD",
    "ADAUSD",
    "ALGOUSD",
    "APTUSD",
    "ATOMUSD",
    "AVAXUSD",
    "BCHUSD",
    "BNBUSD",
    "BTCUSD",
    "CRVUSD",
    "DOGEUSD",
    "DOTUSD",
    "ETCUSD",
    "ETHUSD",
    "FETUSD",
    "FILUSD",
    "FLOWUSD",
    "GALAUSD",
    "GRTUSD",
    "HBARUSD",
    "ICPUSD",
    "IMXUSD",
    "IOTAUSD",
    "LINKUSD",
    "LTCUSD",
    "NEARUSD",
    "SANDUSD",
    "SHIBUSD",
    "SOLUSD",
    "THETAUSD",
    "TRXUSD",
    "UNIUSD",
    "XLMUSD",
    "XRPUSD",
    "XTZUSD",
)

HFM_KATANA_CRYPTO_USD_CANONICALS: tuple[str, ...] = (
    "BTCUSD",
    "ETHUSD",
    "XRPUSD",
)

HFM_CRYPTO_CFD_CANDIDATES: tuple[str, ...] = tuple(dict.fromkeys([
    *(f"#{symbol}" for symbol in HFM_CRYPTO_USD_CANONICALS),
    *(f"#{symbol}r" for symbol in HFM_CRYPTO_USD_CANONICALS),
    *(f"#{symbol}x" for symbol in HFM_KATANA_CRYPTO_USD_CANONICALS),
    *HFM_CRYPTO_USD_CANONICALS,
]))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def hfm_crypto_dir(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "hfm_crypto"


def state_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / STATE_FILE


def moss_backtest_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / MOSS_BACKTEST_FILE


def execution_spec_review_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / EXECUTION_SPEC_REVIEW_FILE


def contract_spec_export_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / CONTRACT_SPEC_EXPORT_FILE


def filled_contract_spec_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / FILLED_CONTRACT_SPEC_FILE


def contract_spec_draft_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / CONTRACT_SPEC_DRAFT_FILE


def ea_symbol_specs_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / EA_SYMBOL_SPECS_FILE


def ea_runtime_probe_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / EA_RUNTIME_PROBE_FILE


def evidence_kit_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / EVIDENCE_KIT_FILE


def contract_spec_template_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / CONTRACT_SPEC_TEMPLATE_FILE


def contract_spec_template_csv_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / CONTRACT_SPEC_TEMPLATE_CSV_FILE


def simulation_profile_review_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / SIMULATION_PROFILE_REVIEW_FILE


def ea_rates_export_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / EA_RATES_EXPORT_FILE


def rates_export_review_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / RATES_EXPORT_REVIEW_FILE


def rates_autogen_profile_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / RATES_AUTOGEN_PROFILE_FILE


def simulation_profile_template_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / SIMULATION_PROFILE_TEMPLATE_FILE


def filled_simulation_profile_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / FILLED_SIMULATION_PROFILE_FILE


def simulation_profile_draft_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / SIMULATION_PROFILE_DRAFT_FILE


def operator_approval_draft_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / OPERATOR_APPROVAL_DRAFT_FILE


def mt5_exporter_review_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / MT5_EXPORTER_REVIEW_FILE


def mt5_exporter_upgrade_bundle_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / MT5_EXPORTER_UPGRADE_BUNDLE_FILE


def mt5_exporter_deploy_plan_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / MT5_EXPORTER_DEPLOY_PLAN_FILE


def mt5_exporter_upgrade_bundle_dir(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / MT5_EXPORTER_UPGRADE_BUNDLE_DIR


def standalone_exporter_bundle_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / STANDALONE_EXPORTER_BUNDLE_FILE


def standalone_exporter_bundle_dir(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / STANDALONE_EXPORTER_BUNDLE_DIR


def mt5_post_upgrade_verify_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / MT5_POST_UPGRADE_VERIFY_FILE


def post_upgrade_controller_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / POST_UPGRADE_CONTROLLER_FILE


def filled_input_validator_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / FILLED_INPUT_VALIDATOR_FILE


def evidence_bootstrap_path(runtime_dir: Path) -> Path:
    return hfm_crypto_dir(runtime_dir) / EVIDENCE_BOOTSTRAP_FILE


def assert_no_execution_flags(payload: Any, path: str = "root") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in EXECUTION_FLAG_KEYS and bool(value):
                raise ValueError(f"truthy execution flag is forbidden at {path}.{key}")
            assert_no_execution_flags(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            assert_no_execution_flags(item, f"{path}[{index}]")
