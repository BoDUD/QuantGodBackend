from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.hfm_crypto_cfd.builder import build_hfm_crypto_cfd_state, read_hfm_crypto_cfd_state
from tools.hfm_crypto_cfd.contract_spec_export import (
    build_hfm_crypto_contract_spec_export,
    read_hfm_crypto_contract_spec_export,
)
from tools.hfm_crypto_cfd.execution_spec import (
    build_hfm_crypto_execution_spec_review,
    read_hfm_crypto_execution_spec_review,
)
from tools.hfm_crypto_cfd.evidence_kit import build_hfm_crypto_evidence_kit, read_hfm_crypto_evidence_kit
from tools.hfm_crypto_cfd.evidence_bootstrap import (
    build_hfm_crypto_evidence_bootstrap,
    read_hfm_crypto_evidence_bootstrap,
)
from tools.hfm_crypto_cfd.filled_input_validator import (
    build_hfm_crypto_filled_input_validator,
    read_hfm_crypto_filled_input_validator,
)
from tools.hfm_crypto_cfd.mt5_exporter_review import (
    build_hfm_crypto_mt5_exporter_review,
    read_hfm_crypto_mt5_exporter_review,
)
from tools.hfm_crypto_cfd.mt5_upgrade_bundle import (
    build_hfm_crypto_mt5_upgrade_bundle,
    read_hfm_crypto_mt5_upgrade_bundle,
)
from tools.hfm_crypto_cfd import mt5_upgrade_runner as hfm_crypto_mt5_upgrade_runner
from tools.hfm_crypto_cfd.mt5_exporter_deploy_plan import (
    build_hfm_crypto_mt5_exporter_deploy_plan,
    read_hfm_crypto_mt5_exporter_deploy_plan,
)
from tools.hfm_crypto_cfd.mt5_post_upgrade_verify import (
    build_hfm_crypto_mt5_post_upgrade_verify,
    read_hfm_crypto_mt5_post_upgrade_verify,
)
from tools.hfm_crypto_cfd.post_upgrade_controller import (
    build_hfm_crypto_post_upgrade_controller,
    read_hfm_crypto_post_upgrade_controller,
)
from tools.hfm_crypto_cfd.standalone_exporter_bundle import (
    build_hfm_crypto_standalone_exporter_bundle,
    read_hfm_crypto_standalone_exporter_bundle,
)
from tools.hfm_crypto_cfd import standalone_exporter_runner as hfm_crypto_standalone_runner
from tools.hfm_crypto_cfd.simulation_profile import (
    build_hfm_crypto_simulation_profile_review,
    read_hfm_crypto_simulation_profile_review,
)
from tools.hfm_crypto_cfd.rates_export import (
    build_hfm_crypto_rates_export_review,
    read_hfm_crypto_rates_export_review,
)
from tools.hfm_crypto_cfd.schema import (
    HFM_CRYPTO_CFD_CANDIDATES,
    HFM_CRYPTO_USD_CANONICALS,
    contract_spec_export_path,
    contract_spec_draft_path,
    filled_contract_spec_path,
    filled_simulation_profile_path,
    moss_backtest_path,
    operator_approval_draft_path,
    rates_autogen_profile_path,
    rates_export_review_path,
    simulation_profile_review_path,
    simulation_profile_draft_path,
)
from tools.hfm_crypto_cfd.runtime_scope import hfm_crypto_runtime_scope_meta, resolve_hfm_crypto_runtime_dir
from tools.mt5_symbol_registry import normalize_symbol_row


class HFMCryptoCfdTests(unittest.TestCase):
    def test_hfm_crypto_runtime_scope_prefers_explicit_live16_files_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = root / "primary" / "Files"
            secondary = root / "secondary" / "Files"
            primary.mkdir(parents=True)
            secondary.mkdir(parents=True)

            with patch.dict("os.environ", {"QG_MT5_SECONDARY_FILES_DIR": str(secondary), "QG_HFM_CRYPTO_SCOPE": "secondary"}, clear=True):
                resolved = resolve_hfm_crypto_runtime_dir(primary)
                meta = hfm_crypto_runtime_scope_meta(primary)

            self.assertEqual(resolved, secondary)
            self.assertEqual(meta["scope"], "secondary")
            self.assertEqual(meta["accountLabel"], "HFM Live16 crypto CFD")
            self.assertEqual(meta["runtimeDir"], str(secondary))

    def test_hfm_crypto_runtime_scope_keeps_primary_when_not_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary" / "Files"
            primary.mkdir(parents=True)

            with patch.dict("os.environ", {}, clear=True):
                resolved = resolve_hfm_crypto_runtime_dir(primary)
                meta = hfm_crypto_runtime_scope_meta(primary)

            self.assertEqual(resolved, primary)
            self.assertEqual(meta["scope"], "primary")

    def test_hfm_official_crypto_cfd_catalog_covers_minor_usd_symbols(self) -> None:
        expected = {
            "#AAVEUSD",
            "#ADAUSD",
            "#AVAXUSD",
            "#BNBUSD",
            "#LINKUSD",
            "#NEARUSD",
            "#SHIBUSD",
            "#BTCUSDr",
            "#ETHUSDx",
        }

        self.assertTrue(expected.issubset(set(HFM_CRYPTO_CFD_CANDIDATES)))
        self.assertIn("LINKUSD", HFM_CRYPTO_USD_CANONICALS)
        self.assertEqual(normalize_symbol_row({"name": "#LINKUSDr", "path": "Crypto CFD"})["canonicalSymbol"], "LINKUSD")
        shib_row = normalize_symbol_row({"name": "#SHIBUSD", "path": "Crypto CFD"})
        self.assertEqual(shib_row["marketType"], "crypto_cfd")
        self.assertEqual(shib_row["baseCurrency"], "SHIB")
        self.assertEqual(normalize_symbol_row({"name": "DOGEUSD", "path": "Crypto CFD"})["baseCurrency"], "DOGE")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            kit = build_hfm_crypto_evidence_kit(runtime, write=True)
            template_symbols = {row["brokerSymbol"] for row in kit["contractSpecTemplate"]["symbols"]}

            self.assertTrue(expected.issubset(template_symbols))
            self.assertIn("pnlUsd", kit["simulationProfileTemplate"]["metrics"])

            bootstrap = build_hfm_crypto_evidence_bootstrap(runtime, write=True)
            self.assertEqual(bootstrap["schema"], "quantgod.hfm_crypto_cfd.evidence_bootstrap.v1")
            self.assertEqual(bootstrap["status"], "WAITING_HFM_EVIDENCE_BOOTSTRAP_INPUTS")
            self.assertFalse(bootstrap["filledInputsValid"])
            self.assertFalse(bootstrap["executionReady"])
            self.assertFalse(bootstrap["orderSendAllowed"])
            self.assertFalse(bootstrap["mt5OrderSendAllowed"])
            self.assertFalse(bootstrap["writesMt5OrderRequest"])
            self.assertFalse(bootstrap["requestFilesWritten"])
            self.assertFalse(bootstrap["brokerCallsMade"])
            self.assertTrue(contract_spec_draft_path(runtime).exists())
            self.assertTrue(simulation_profile_draft_path(runtime).exists())
            self.assertTrue(operator_approval_draft_path(runtime).exists())
            self.assertFalse(filled_contract_spec_path(runtime).exists())
            self.assertFalse(filled_simulation_profile_path(runtime).exists())
            saved_bootstrap = read_hfm_crypto_evidence_bootstrap(runtime)
            self.assertEqual(saved_bootstrap["schema"], bootstrap["schema"])

            registry_export = runtime / "official_hfm_crypto_specs.json"
            registry_export.write_text(json.dumps({
                "source": "HFM_OFFICIAL_CRYPTO_CFD_CONTRACT_SPEC",
                "symbols": [
                    {
                        "brokerSymbol": "#BNBUSD",
                        "canonicalSymbol": "BNBUSD",
                        "contractSize": 1,
                        "tickSize": 0.01,
                        "tickValue": 0.01,
                        "minLot": 0.01,
                        "lotStep": 0.01,
                        "maxLot": 5,
                    },
                    {
                        "brokerSymbol": "#AVAXUSD",
                        "canonicalSymbol": "AVAXUSD",
                        "contractSize": 1,
                        "tickSize": 0.01,
                        "tickValue": 0.01,
                        "minLot": 0.01,
                        "lotStep": 0.01,
                        "maxLot": 5,
                    },
                ],
            }), encoding="utf-8")

            export = build_hfm_crypto_contract_spec_export(
                runtime,
                symbol_registry_json=str(registry_export),
                write=True,
            )
            self.assertEqual(export["status"], "READY_FOR_CONTRACT_SPEC_REVIEW_INPUT")
            self.assertEqual(export["validRowCount"], 2)
            self.assertEqual(export["coveredCanonicalSymbols"], ["AVAXUSD", "BNBUSD"])
            self.assertFalse(export["orderSendAllowed"])

            review = build_hfm_crypto_execution_spec_review(
                runtime,
                contract_spec_json=export["contractSpecJsonPath"],
                write=False,
            )
            self.assertEqual(review["status"], "READY_FOR_EXECUTION_CONTRACT_REVIEW")
            self.assertEqual(review["coveredCanonicalSymbols"], ["AVAXUSD", "BNBUSD"])
            self.assertFalse(review["writesMt5OrderRequest"])

    def test_detects_local_hfm_crypto_symbols_and_moss_backtest_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            bases = runtime / "Bases"
            btc_history = bases / "HFMarketsGlobal-Live12" / "history" / "#BTCUSD"
            eth_ticks = bases / "HFMarketsGlobal-Live12" / "ticks" / "#ETHUSDx"
            btc_history.mkdir(parents=True)
            eth_ticks.mkdir(parents=True)
            (btc_history / "2026.hcc").write_text("fixture", encoding="utf-8")
            (eth_ticks / "ticks.dat").write_text("fixture", encoding="utf-8")
            profile_path = runtime / "moss_backtest.json"
            profile_path.write_text(json.dumps({
                "agentId": "agt_crypto_demo",
                "metrics": {
                    "pnlUsd": 24.2,
                    "roi": "12.4%",
                    "sharpe": "1.7",
                    "maxDrawdown": "8.5%",
                    "liquidations": 0,
                    "trades": 42,
                },
                "backtest": {"dateRange": "2026-04-01..2026-05-01"},
            }), encoding="utf-8")

            payload = build_hfm_crypto_cfd_state(
                runtime,
                moss_backtest_json=str(profile_path),
                write=True,
            )

            self.assertEqual(payload["schema"], "quantgod.hfm_crypto_cfd.state.v1")
            self.assertEqual(payload["status"], "READY_FOR_SHADOW_RESEARCH")
            self.assertIn("BTCUSD", payload["targetSymbols"])
            self.assertIn("ETHUSD", payload["targetSymbols"])
            self.assertTrue(payload["localEvidence"]["found"])
            self.assertEqual(payload["mossBacktestProfile"]["metrics"]["agentId"], "agt_crypto_demo")
            self.assertEqual(payload["mossBacktestProfile"]["metrics"]["roiPct"], 12.4)
            self.assertEqual(payload["mossBacktestProfile"]["metrics"]["liquidationCount"], 0)
            self.assertFalse(payload["shadowPlan"]["writesOrders"])
            self.assertFalse(payload["safety"]["mt5OrderSendAllowed"])
            self.assertFalse(payload["safety"]["mossExecutionAllowed"])

            saved = read_hfm_crypto_cfd_state(runtime)
            self.assertEqual(saved["status"], "READY_FOR_SHADOW_RESEARCH")

    def test_waits_when_no_local_symbols_and_keeps_execution_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_hfm_crypto_cfd_state(Path(tmp), write=False)

            self.assertEqual(payload["status"], "WAITING_HFM_CRYPTO_SYMBOLS")
            self.assertGreaterEqual(len(payload["blockers"]), 1)
            self.assertEqual(payload["riskBoundary"]["followRatio"], 0.0)
            self.assertFalse(payload["riskBoundary"]["autoFlattenAllowed"])
            self.assertFalse(payload["safety"]["orderSendAllowed"])
            self.assertFalse(payload["safety"]["copyTradeExecutionAllowed"])

    def test_reviews_hfm_crypto_contract_spec_without_execution_rights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            spec_path = runtime / "hfm_crypto_contract_specs.json"
            spec_path.write_text(json.dumps({
                "symbols": [
                    {
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                        "contractSize": 1,
                        "tickSize": 0.01,
                        "tickValue": 0.01,
                        "minLot": 0.01,
                        "lotStep": 0.01,
                        "maxLot": 10,
                        "spreadMaxPips": 50,
                        "swapLong": -0.03,
                        "swapShort": -0.02,
                    }
                ],
            }), encoding="utf-8")

            review = build_hfm_crypto_execution_spec_review(
                runtime,
                contract_spec_json=str(spec_path),
                write=True,
            )

            self.assertEqual(review["schema"], "quantgod.hfm_crypto_cfd.execution_spec_review.v1")
            self.assertEqual(review["status"], "READY_FOR_EXECUTION_CONTRACT_REVIEW")
            self.assertTrue(review["readyForExecutionSpecReview"])
            self.assertFalse(review["executionReady"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])
            self.assertEqual(review["coveredBrokerSymbols"], ["#BTCUSD"])
            self.assertEqual(review["validRowCount"], 1)

            saved = read_hfm_crypto_execution_spec_review(runtime)
            self.assertEqual(saved["status"], "READY_FOR_EXECUTION_CONTRACT_REVIEW")

            state = build_hfm_crypto_cfd_state(
                runtime,
                contract_spec_json=str(spec_path),
                write=False,
            )
            self.assertEqual(state["status"], "READY_FOR_SHADOW_RESEARCH")
            self.assertTrue(state["symbolEvidence"]["found"])
            self.assertFalse(state["symbolEvidence"]["localBasesFound"])
            self.assertTrue(state["symbolEvidence"]["executionSpecReady"])
            self.assertEqual(state["targetSymbols"], ["BTCUSD"])
            self.assertTrue(state["executionSpecReview"]["readyForExecutionSpecReview"])

    def test_filled_contract_spec_overrides_empty_generated_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            export_path = contract_spec_export_path(runtime)
            export_path.parent.mkdir(parents=True)
            export_path.write_text(json.dumps({
                "schema": "quantgod.hfm_crypto_cfd.contract_spec_export.v1",
                "status": "WAITING_HFM_CRYPTO_CONTRACT_SPEC_EXPORT",
                "readyForContractSpecReviewInput": False,
                "symbols": [],
            }), encoding="utf-8")
            filled_path = filled_contract_spec_path(runtime)
            filled_path.write_text(json.dumps({
                "symbols": [
                    {
                        "brokerSymbol": "#ETHUSD",
                        "canonicalSymbol": "ETHUSD",
                        "contractSize": 1,
                        "tickSize": 0.01,
                        "tickValue": 0.01,
                        "minLot": 0.01,
                        "lotStep": 0.01,
                        "maxLot": 3,
                    }
                ],
            }), encoding="utf-8")

            state = build_hfm_crypto_cfd_state(runtime, write=False)

            self.assertEqual(state["status"], "READY_FOR_SHADOW_RESEARCH")
            self.assertEqual(state["executionSpecReview"]["contractSpecJsonPath"], str(filled_path))
            self.assertEqual(state["executionSpecReview"]["coveredBrokerSymbols"], ["#ETHUSD"])
            self.assertTrue(state["symbolEvidence"]["found"])
            self.assertEqual(state["symbolEvidence"]["brokerSymbols"], ["#ETHUSD"])
            self.assertEqual(state["targetSymbols"], ["ETHUSD"])
            self.assertFalse(state["safety"]["mt5OrderSendAllowed"])

    def test_filled_input_validator_accepts_complete_manual_inputs_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            filled_spec = filled_contract_spec_path(runtime)
            filled_spec.parent.mkdir(parents=True)
            filled_spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#SOLUSD",
                    "canonicalSymbol": "SOLUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 4,
                }],
            }), encoding="utf-8")
            filled_profile = filled_simulation_profile_path(runtime)
            filled_profile.write_text(json.dumps({
                "agentId": "agt_manual_ready",
                "metrics": {
                    "pnlUsd": 62.0,
                    "roiPct": 11.5,
                    "sharpe": 1.4,
                    "maxDrawdownPct": 9.0,
                    "tradeCount": 32,
                    "liquidationCount": 0,
                },
            }), encoding="utf-8")

            validator = build_hfm_crypto_filled_input_validator(runtime, write=True)

            self.assertEqual(validator["schema"], "quantgod.hfm_crypto_cfd.filled_input_validator.v1")
            self.assertEqual(validator["status"], "FILLED_HFM_INPUTS_READY_FOR_REVIEW_CHAIN")
            self.assertTrue(validator["filledInputsValid"])
            self.assertTrue(validator["readyForEvidenceIntakeRefresh"])
            self.assertEqual(validator["coveredBrokerSymbols"], ["#SOLUSD"])
            self.assertEqual(validator["simulationMetrics"]["agentId"], "agt_manual_ready")
            self.assertTrue(all(row["passed"] for row in validator["checklist"]))
            self.assertFalse(validator["orderSendAllowed"])
            self.assertFalse(validator["mt5OrderSendAllowed"])
            self.assertFalse(validator["writesMt5OrderRequest"])
            self.assertFalse(validator["requestWritesAllowed"])
            self.assertFalse(validator["brokerCallsMade"])
            self.assertTrue((runtime / "hfm_crypto" / "QuantGod_HFMCryptoFilledInputValidator.json").exists())

            saved = read_hfm_crypto_filled_input_validator(runtime)
            self.assertEqual(saved["status"], "FILLED_HFM_INPUTS_READY_FOR_REVIEW_CHAIN")

    def test_filled_input_validator_accepts_auto_review_artifacts_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            export_path = contract_spec_export_path(runtime)
            export_path.parent.mkdir(parents=True)
            export_path.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 5,
                }],
            }), encoding="utf-8")
            profile = runtime / "moss_profile.json"
            profile.write_text(json.dumps({
                "agentId": "agt_auto_ready",
                "metrics": {
                    "pnlUsd": 63.0,
                    "roiPct": 18.0,
                    "sharpe": 1.8,
                    "maxDrawdownPct": 6.5,
                    "tradeCount": 44,
                    "liquidationCount": 0,
                },
            }), encoding="utf-8")
            build_hfm_crypto_simulation_profile_review(runtime, simulation_profile_json=str(profile), write=True)

            validator = build_hfm_crypto_filled_input_validator(runtime, write=True)

            self.assertEqual(validator["status"], "FILLED_HFM_INPUTS_READY_FOR_REVIEW_CHAIN")
            self.assertTrue(validator["filledInputsValid"])
            self.assertTrue(validator["reviewInputsValid"])
            self.assertEqual(validator["inputSources"]["contractSpecSource"], "contract_spec_export")
            self.assertEqual(validator["inputSources"]["simulationProfileSource"], "simulation_profile_review_artifact")
            self.assertEqual(validator["inputSources"]["simulationProfileSourcePath"], str(simulation_profile_review_path(runtime)))
            self.assertEqual(validator["coveredBrokerSymbols"], ["#BTCUSD"])
            self.assertEqual(validator["simulationMetrics"]["agentId"], "agt_auto_ready")
            self.assertTrue(all(row["passed"] for row in validator["checklist"]))
            self.assertFalse(validator["orderSendAllowed"])
            self.assertFalse(validator["mt5OrderSendAllowed"])
            self.assertFalse(validator["writesMt5OrderRequest"])
            self.assertFalse(validator["requestWritesAllowed"])
            self.assertFalse(validator["brokerCallsMade"])

    def test_filled_input_validator_blocks_incomplete_manual_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            filled_spec = filled_contract_spec_path(runtime)
            filled_spec.parent.mkdir(parents=True)
            filled_spec.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#DOGEUSD",
                    "canonicalSymbol": "DOGEUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 4,
                }],
            }), encoding="utf-8")

            validator = build_hfm_crypto_filled_input_validator(runtime, write=False)

            self.assertEqual(validator["status"], "WAITING_FILLED_HFM_INPUTS")
            self.assertFalse(validator["filledInputsValid"])
            self.assertFalse(validator["readyForEvidenceIntakeRefresh"])
            codes = {row["code"] for row in validator["blockers"]}
            self.assertIn("HFM_SIMULATION_PROFILE_REVIEW_INPUT_MISSING", codes)
            self.assertIn("FILLED_CONTRACT_SPEC_HFM_CRYPTO_SPEC_FIELD_MISSING", codes)
            self.assertFalse(validator["orderSendAllowed"])
            self.assertFalse(validator["writesMt5OrderRequest"])

    def test_builds_evidence_kit_and_accepts_symbol_registry_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            kit = build_hfm_crypto_evidence_kit(runtime, write=True)

            self.assertEqual(kit["schema"], "quantgod.hfm_crypto_cfd.evidence_kit.v1")
            self.assertEqual(kit["status"], "READY_FOR_OPERATOR_EXPORT")
            self.assertFalse(kit["mt5OrderSendAllowed"])
            self.assertFalse(kit["writesMt5OrderRequest"])
            self.assertIn("contractSize", kit["requiredContractSpecFields"])
            self.assertIn("pnlUsd", kit["simulationProfileTemplate"]["metrics"])
            self.assertTrue((runtime / "hfm_crypto" / "QuantGod_HFMCryptoContractSpecTemplate.json").exists())
            self.assertTrue((runtime / "hfm_crypto" / "QuantGod_HFMCryptoContractSpecTemplate.csv").exists())
            self.assertIn("contractSpecExportJson", kit["outputFiles"])
            self.assertIn("eaSymbolSpecsJson", kit["outputFiles"])

            saved = read_hfm_crypto_evidence_kit(runtime)
            self.assertEqual(saved["status"], "READY_FOR_OPERATOR_EXPORT")

            registry_export = runtime / "mt5_symbol_registry_crypto.json"
            registry_export.write_text(json.dumps({
                "mappings": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 5,
                }],
            }), encoding="utf-8")

            export = build_hfm_crypto_contract_spec_export(
                runtime,
                symbol_registry_json=str(registry_export),
                write=True,
            )
            self.assertEqual(export["schema"], "quantgod.hfm_crypto_cfd.contract_spec_export.v1")
            self.assertEqual(export["status"], "READY_FOR_CONTRACT_SPEC_REVIEW_INPUT")
            self.assertTrue(export["readyForContractSpecReviewInput"])
            self.assertFalse(export["mt5OrderSendAllowed"])
            self.assertFalse(export["writesMt5OrderRequest"])
            self.assertEqual(export["validRowCount"], 1)
            self.assertEqual(export["contractSpecJsonPath"], str(runtime / "hfm_crypto" / "QuantGod_HFMCryptoContractSpecExport.json"))

            saved_export = read_hfm_crypto_contract_spec_export(runtime)
            self.assertEqual(saved_export["status"], "READY_FOR_CONTRACT_SPEC_REVIEW_INPUT")

            review = build_hfm_crypto_execution_spec_review(
                runtime,
                contract_spec_json=export["contractSpecJsonPath"],
                write=False,
            )
            self.assertEqual(review["status"], "READY_FOR_EXECUTION_CONTRACT_REVIEW")
            self.assertEqual(review["validRowCount"], 1)

    def test_auto_discovers_ea_hfm_crypto_symbol_specs_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            ea_export = runtime / "hfm_crypto" / "QuantGod_HFMCryptoSymbolSpecs.json"
            ea_export.parent.mkdir(parents=True)
            ea_export.write_text(json.dumps({
                "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                "source": "MQL5_SYMBOLINFO_READONLY",
                "enabled": True,
                "symbols": [
                    {
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                        "description": "Bitcoin vs US Dollar",
                        "path": "Crypto CFD",
                        "tradeContractSize": 1,
                        "tradeTickSize": 0.01,
                        "tradeTickValue": 0.01,
                        "volumeMin": 0.01,
                        "volumeStep": 0.01,
                        "volumeMax": 5,
                        "tradeEnabled": True,
                    }
                ],
                "safety": {
                    "readOnly": True,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                },
            }), encoding="utf-8")

            export = build_hfm_crypto_contract_spec_export(runtime, write=True)

            self.assertEqual(export["status"], "READY_FOR_CONTRACT_SPEC_REVIEW_INPUT")
            self.assertEqual(export["sourceFormat"], "EA_SYMBOL_SPECS_JSON")
            self.assertTrue(export["autoDiscoveredEaExport"])
            self.assertEqual(export["eaSymbolSpecsJsonPath"], str(ea_export))
            self.assertEqual(export["validRowCount"], 1)
            self.assertFalse(export["orderSendAllowed"])
            self.assertFalse(export["mt5OrderSendAllowed"])

            review = build_hfm_crypto_execution_spec_review(
                runtime,
                contract_spec_json=export["contractSpecJsonPath"],
                write=False,
            )
            self.assertEqual(review["status"], "READY_FOR_EXECUTION_CONTRACT_REVIEW")
            self.assertEqual(review["validRowCount"], 1)

    def test_ea_symbol_specs_export_reports_account_without_crypto_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            ea_export = runtime / "hfm_crypto" / "QuantGod_HFMCryptoSymbolSpecs.json"
            ea_export.parent.mkdir(parents=True)
            ea_export.write_text(json.dumps({
                "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                "source": "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA",
                "enabled": True,
                "scanAllBrokerSymbols": True,
                "candidateSymbolsScanned": 108,
                "brokerSymbolTotalAll": 3,
                "brokerSymbolTotalMarketWatch": 2,
                "brokerCryptoLikeCountAll": 0,
                "brokerCryptoLikeCountMarketWatch": 0,
                "brokerSymbolSampleCount": 3,
                "symbols": [],
                "brokerSymbolSamples": [
                    {"brokerSymbol": "EURUSDc", "path": "Forex", "looksLikeCrypto": False},
                    {"brokerSymbol": "USDJPYc", "path": "Forex", "looksLikeCrypto": False},
                    {"brokerSymbol": "XAUUSDc", "path": "Metals", "looksLikeCrypto": False},
                ],
                "safety": {
                    "readOnly": True,
                    "orderSendAllowed": False,
                    "mt5OrderSendAllowed": False,
                    "writesMt5OrderRequest": False,
                },
            }), encoding="utf-8")

            export = build_hfm_crypto_contract_spec_export(runtime, write=True)

            self.assertEqual(export["sourceFormat"], "EA_SYMBOL_SPECS_JSON")
            self.assertEqual(export["status"], "WAITING_HFM_CRYPTO_CONTRACT_SPEC_EXPORT")
            self.assertEqual(export["statusZh"], "当前 HFM 账号未下发 crypto CFD symbol")
            self.assertEqual(export["brokerSymbolDiagnostics"]["brokerSymbolTotalAll"], 3)
            self.assertEqual(export["brokerSymbolDiagnostics"]["brokerCryptoLikeCountAll"], 0)
            self.assertIn("HFM_MT5_ACCOUNT_NO_CRYPTO_CFD_SYMBOLS", {item["code"] for item in export["blockers"]})
            self.assertFalse(export["mt5OrderSendAllowed"])
            self.assertFalse(export["writesMt5OrderRequest"])

            state = build_hfm_crypto_cfd_state(runtime, write=False)

            self.assertEqual(state["status"], "WAITING_HFM_ACCOUNT_CRYPTO_CFD_SYMBOLS")
            self.assertEqual(state["statusZh"], "当前 HFM 账号未下发 Crypto CFD symbols")
            self.assertIn("HFM_MT5_ACCOUNT_NO_CRYPTO_CFD_SYMBOLS", {item["code"] for item in state["blockers"]})
            self.assertEqual(state["symbolEvidence"]["brokerSymbolDiagnostics"]["brokerSymbolTotalAll"], 3)
            checklist_by_id = {item["id"]: item for item in state["operatorChecklist"]}
            self.assertEqual(checklist_by_id["mt5_account_symbol_inventory"]["status"], "PASS")
            self.assertEqual(checklist_by_id["hfm_account_crypto_cfd_symbols"]["status"], "BLOCKED")
            self.assertTrue(checklist_by_id["hfm_account_crypto_cfd_symbols"]["blocking"])
            self.assertIn("换用开通 HFM crypto CFD", checklist_by_id["hfm_account_crypto_cfd_symbols"]["nextActionZh"])
            self.assertEqual(checklist_by_id["hfm_crypto_contract_specs"]["status"], "LOCKED")
            self.assertFalse(checklist_by_id["review_only_execution_boundary"]["mt5OrderSendAllowed"])
            self.assertFalse(state["safety"]["mt5OrderSendAllowed"])

    def test_auto_discovers_dashboard_embedded_hfm_crypto_symbol_specs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            dashboard = runtime / "QuantGod_Dashboard.json"
            dashboard.write_text(json.dumps({
                "build": "QuantGod-v3.17-test",
                "timestamp": "2026-05-28 09:00:00",
                "hfmCryptoSymbolSpecs": {
                    "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                    "source": "MQL5_SYMBOLINFO_READONLY",
                    "enabled": True,
                    "symbols": [
                        {
                            "brokerSymbol": "#ETHUSD",
                            "canonicalSymbol": "ETHUSD",
                            "description": "Ethereum vs US Dollar",
                            "path": "Crypto CFD",
                            "tradeContractSize": 1,
                            "tradeTickSize": 0.01,
                            "tradeTickValue": 0.01,
                            "volumeMin": 0.01,
                            "volumeStep": 0.01,
                            "volumeMax": 3,
                            "tradeEnabled": True,
                        }
                    ],
                    "safety": {
                        "readOnly": True,
                        "orderSendAllowed": False,
                        "mt5OrderSendAllowed": False,
                        "writesMt5OrderRequest": False,
                    },
                },
            }), encoding="utf-8")

            with patch.dict("os.environ", {"QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1"}, clear=False):
                export = build_hfm_crypto_contract_spec_export(runtime, write=True)

            self.assertEqual(export["status"], "READY_FOR_CONTRACT_SPEC_REVIEW_INPUT")
            self.assertEqual(export["sourceFormat"], "EA_DASHBOARD_HFM_CRYPTO_SYMBOL_SPECS")
            self.assertTrue(export["autoDiscoveredEaDashboardExport"])
            self.assertFalse(export["autoDiscoveredEaExport"])
            self.assertEqual(export["eaDashboardJsonPath"], str(dashboard))
            self.assertEqual(export["validRowCount"], 1)
            self.assertEqual(export["coveredBrokerSymbols"], ["#ETHUSD"])
            self.assertFalse(export["orderSendAllowed"])
            self.assertFalse(export["mt5OrderSendAllowed"])

            review = build_hfm_crypto_execution_spec_review(
                runtime,
                contract_spec_json=export["contractSpecJsonPath"],
                write=False,
            )
            self.assertEqual(review["status"], "READY_FOR_EXECUTION_CONTRACT_REVIEW")
            self.assertEqual(review["coveredBrokerSymbols"], ["#ETHUSD"])

            state = build_hfm_crypto_cfd_state(runtime, write=False)
            checklist = {row["id"]: row for row in state["operatorChecklist"]}
            self.assertEqual(checklist["hfm_account_crypto_cfd_symbols"]["status"], "PASS")
            self.assertEqual(checklist["hfm_crypto_contract_specs"]["status"], "PASS")
            self.assertEqual(checklist["hfm_crypto_copyrates_history"]["status"], "PASS")
            self.assertIn("profile", checklist["hfm_crypto_copyrates_history"]["nextActionZh"])
            self.assertEqual(checklist["moss_or_simulation_profile"]["status"], "PENDING")
            self.assertIn("pnlUsd", checklist["moss_or_simulation_profile"]["reasonZh"])
            self.assertIn("pnlUsd", checklist["separate_sim_to_live_review"]["nextActionZh"])
            self.assertFalse(state["safety"]["mt5OrderSendAllowed"])

    def test_mql5_hfm_crypto_symbol_spec_exporter_is_read_only(self) -> None:
        mql_path = Path(__file__).resolve().parents[1] / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"
        source = mql_path.read_text(encoding="utf-8")
        begin = "// HFM Crypto Symbol Spec Export BEGIN"
        end = "// HFM Crypto Symbol Spec Export END"
        self.assertIn(begin, source)
        self.assertIn(end, source)
        block = source.split(begin, 1)[1].split(end, 1)[0]

        for marker in [
            "BuildHfmCryptoSymbolSpecsJson",
            "BuildHfmCryptoRuntimeProbeJson",
            "QuantGod_HFMCryptoSymbolSpecs.json",
            "QuantGod_HFMCryptoRuntimeProbe.json",
            "quantgod.mql5.hfm_crypto_symbol_specs.v1",
            "quantgod.mql5.hfm_crypto_runtime_probe.v1",
            "MQL5_SYMBOLINFO_READONLY",
            "MQL5_SYMBOLINFO_READONLY_MULTISTRATEGY_RUNTIME_PROBE",
            "SymbolInfoDouble",
            "SymbolInfoInteger",
            "SymbolInfoString",
            "SymbolInfoTick",
        ]:
            self.assertIn(marker, source)

        for forbidden in [
            "OrderSend(",
            "OrderSendAsync(",
            "TRADE_ACTION_DEAL",
            "PositionClose(",
            "CTrade",
            "SymbolSelect(",
        ]:
            self.assertNotIn(forbidden, block)

    def test_mql5_ea_request_reader_harness_is_review_only(self) -> None:
        mql_path = Path(__file__).resolve().parents[1] / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"
        source = mql_path.read_text(encoding="utf-8")
        begin = "// EA Request Reader Review Harness BEGIN"
        end = "// EA Request Reader Review Harness END"
        self.assertIn(begin, source)
        self.assertIn(end, source)
        block = source.split(begin, 1)[1].split(end, 1)[0]

        for marker in [
            "QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT",
            "QG_EA_REQUEST_SCHEMA_VALIDATION_REQUIRED",
            "QG_EA_IDEMPOTENCY_REQUEST_ID_REQUIRED",
            "QG_EA_KILL_SWITCH_REQUIRED",
            "QG_EA_RECEIPT_WRITER_REQUIRED",
            "QG_EA_ORDER_SEND_REQUIRES_SEPARATE_REVIEW",
            "BuildEARequestReaderReviewStatusJson",
            "QuantGod_EARequestReaderReviewStatus.json",
            "quantgod.mql5.ea_request_reader_review_status.v1",
            "effectiveEnabled",
            "requestFilesRead",
            "receiptFilesWritten",
            "orderSendAllowed",
        ]:
            self.assertIn(marker, source)

        for forbidden in [
            "OrderSend(",
            "OrderSendAsync(",
            "TRADE_ACTION_DEAL",
            "PositionClose(",
            "FileOpen(",
            "FileRead",
            "FileWrite",
            "CTrade",
        ]:
            self.assertNotIn(forbidden, block)

    def test_mt5_exporter_review_detects_installed_ea_upgrade_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            experts = runtime / "Experts"
            experts.mkdir()
            (experts / "QuantGod_MultiStrategy.mq5").write_text(
                "#property strict\nvoid OnTick() {}\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                review = build_hfm_crypto_mt5_exporter_review(runtime, write=True)

            self.assertEqual(review["schema"], "quantgod.hfm_crypto_cfd.mt5_exporter_review.v1")
            self.assertEqual(review["status"], "WAITING_MT5_EA_EXPORTER_UPGRADE")
            self.assertTrue(review["repoEaSource"]["hasExporter"])
            self.assertFalse(review["installedMt5Ea"]["sourceHasExporter"])
            self.assertTrue(review["mt5EaUpgradeRequired"])
            self.assertFalse(review["exporterReadyForEvidenceIntake"])
            self.assertFalse(review["installedFilesMutated"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])

            saved = read_hfm_crypto_mt5_exporter_review(runtime)
            self.assertEqual(saved["status"], "WAITING_MT5_EA_EXPORTER_UPGRADE")

    def test_mt5_exporter_review_accepts_dashboard_specs_without_mutating_mt5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            experts = runtime / "Experts"
            experts.mkdir()
            repo_mql = Path(__file__).resolve().parents[1] / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"
            (experts / "QuantGod_MultiStrategy.mq5").write_text(repo_mql.read_text(encoding="utf-8"), encoding="utf-8")
            (experts / "QuantGod_MultiStrategy.ex5").write_text("compiled fixture", encoding="utf-8")
            (runtime / "QuantGod_Dashboard.json").write_text(json.dumps({
                "build": "QuantGod-v3.17-test",
                "timestamp": "2026.05.28 09:00:00",
                "hfmCryptoSymbolSpecs": {
                    "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                    "source": "MQL5_SYMBOLINFO_READONLY",
                    "symbolCount": 1,
                    "symbols": [{"brokerSymbol": "#BTCUSD", "canonicalSymbol": "BTCUSD"}],
                },
            }), encoding="utf-8")

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                review = build_hfm_crypto_mt5_exporter_review(runtime, write=True)

            self.assertEqual(review["status"], "HFM_CRYPTO_MT5_EXPORT_AVAILABLE")
            self.assertTrue(review["installedMt5Ea"]["sourceHasExporter"])
            self.assertTrue(review["installedMt5Ea"]["binaryExists"])
            self.assertTrue(review["dashboard"]["hasHfmCryptoSymbolSpecs"])
            self.assertEqual(review["dashboard"]["hfmCryptoSymbolCount"], 1)
            self.assertFalse(review["mt5EaUpgradeRequired"])
            self.assertTrue(review["exporterReadyForEvidenceIntake"])
            self.assertFalse(review["installedFilesMutated"])
            self.assertEqual(review["blockers"], [])

    def test_mt5_exporter_review_prefers_runtime_scope_over_global_mt5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary_files = root / "primary" / "MQL5" / "Files"
            primary_experts = root / "primary" / "MQL5" / "Experts"
            secondary_files = root / "live16" / "MQL5" / "Files"
            secondary_experts = root / "live16" / "MQL5" / "Experts"
            primary_experts.mkdir(parents=True)
            primary_files.mkdir(parents=True)
            secondary_experts.mkdir(parents=True)
            secondary_files.mkdir(parents=True)
            (primary_experts / "QuantGod_MultiStrategy.mq5").write_text(
                "#property strict\nvoid OnTick() {}\n",
                encoding="utf-8",
            )
            repo_mql = Path(__file__).resolve().parents[1] / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"
            (secondary_experts / "QuantGod_MultiStrategy.mq5").write_text(
                repo_mql.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (secondary_experts / "QuantGod_MultiStrategy.ex5").write_text("compiled fixture", encoding="utf-8")
            (secondary_files / "QuantGod_Dashboard.json").write_text(json.dumps({
                "build": "QuantGod-v3.17-live16-test",
                "timestamp": "2026.05.31 16:20:00",
                "hfmCryptoSymbolSpecs": {
                    "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                    "source": "MQL5_SYMBOLINFO_READONLY",
                    "symbolCount": 1,
                    "symbols": [{"brokerSymbol": "#ETHUSD", "canonicalSymbol": "ETHUSD"}],
                },
            }), encoding="utf-8")

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(primary_experts),
                "QG_RUNTIME_DIR": str(primary_files),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                review = build_hfm_crypto_mt5_exporter_review(secondary_files, write=True)

            self.assertEqual(review["status"], "HFM_CRYPTO_MT5_EXPORT_AVAILABLE")
            self.assertIn("/live16/MQL5/Experts/QuantGod_MultiStrategy.mq5", review["installedMt5Ea"]["sourcePath"])
            self.assertTrue(review["installedMt5Ea"]["sourceHasExporter"])
            self.assertIn("/live16/MQL5/Files/QuantGod_Dashboard.json", review["dashboard"]["path"])
            self.assertEqual(review["dashboard"]["hfmCryptoSymbols"], ["#ETHUSD"])
            self.assertFalse(review["mt5EaUpgradeRequired"])

    def test_mt5_upgrade_bundle_stages_ea_without_mutating_installed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            experts = runtime / "Experts"
            experts.mkdir()
            installed = experts / "QuantGod_MultiStrategy.mq5"
            old_source = "#property strict\nvoid OnTick() {}\n"
            installed.write_text(old_source, encoding="utf-8")

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                bundle = build_hfm_crypto_mt5_upgrade_bundle(runtime, write=True)

            self.assertEqual(bundle["schema"], "quantgod.hfm_crypto_cfd.mt5_exporter_upgrade_bundle.v1")
            self.assertEqual(bundle["status"], "READY_FOR_MANUAL_MT5_EA_UPGRADE")
            self.assertTrue(bundle["bundleReadyForManualUpgrade"])
            self.assertTrue(bundle["bundleWritten"])
            self.assertTrue(Path(bundle["bundle"]["stagedSourcePath"]).exists())
            self.assertTrue(Path(bundle["bundle"]["helperScriptPath"]).exists())
            self.assertEqual(bundle["bundle"]["stagedSourceSha256"], bundle["source"]["repoEaSha256"])
            self.assertEqual(installed.read_text(encoding="utf-8"), old_source)
            self.assertFalse(bundle["installedFilesMutated"])
            self.assertFalse(bundle["compileAttempted"])
            self.assertFalse(bundle["copyIntoMt5Allowed"])
            self.assertFalse(bundle["mt5OrderSendAllowed"])
            self.assertFalse(bundle["writesMt5OrderRequest"])

            saved = read_hfm_crypto_mt5_upgrade_bundle(runtime)
            self.assertEqual(saved["status"], "READY_FOR_MANUAL_MT5_EA_UPGRADE")

    def test_mt5_exporter_deploy_plan_is_manual_and_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            experts = runtime / "Experts"
            experts.mkdir()
            installed = experts / "QuantGod_MultiStrategy.mq5"
            old_source = "#property strict\nvoid OnTick() {}\n"
            installed.write_text(old_source, encoding="utf-8")

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                build_hfm_crypto_mt5_upgrade_bundle(runtime, write=True)
                plan = build_hfm_crypto_mt5_exporter_deploy_plan(runtime, write=True)

            self.assertEqual(plan["schema"], "quantgod.hfm_crypto_cfd.mt5_exporter_deploy_plan.v1")
            self.assertEqual(plan["status"], "READY_FOR_OPERATOR_MT5_EA_DEPLOY_REVIEW")
            self.assertTrue(plan["deployPlanReady"])
            self.assertTrue(plan["rollbackPlanReady"])
            self.assertTrue(plan["source"]["stagedSourceExists"])
            self.assertTrue(plan["source"]["sourceHashMatchesBundle"])
            self.assertTrue(plan["target"]["stagedDiffersFromInstalled"])
            self.assertIn("backups", plan["backupPlan"]["backupPath"])
            self.assertEqual(plan["rollbackPlan"]["rollbackTargetPath"], str(installed))
            self.assertEqual(installed.read_text(encoding="utf-8"), old_source)
            self.assertFalse(plan["installedFilesMutated"])
            self.assertFalse(plan["compileAttempted"])
            self.assertFalse(plan["copyIntoMt5Allowed"])
            self.assertFalse(plan["deployCommandExecuted"])
            self.assertFalse(plan["rollbackCommandExecuted"])
            self.assertFalse(plan["mt5OrderSendAllowed"])
            self.assertFalse(plan["writesMt5OrderRequest"])
            self.assertTrue(all(row["manualOnly"] for row in plan["commandsForHumanReview"]))
            self.assertTrue(any("cp -p" in row["command"] for row in plan["commandsForHumanReview"]))

            saved = read_hfm_crypto_mt5_exporter_deploy_plan(runtime)
            self.assertEqual(saved["status"], "READY_FOR_OPERATOR_MT5_EA_DEPLOY_REVIEW")

    def test_standalone_hfm_crypto_spec_exporter_is_read_only(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "MQL5" / "Scripts" / "QuantGod_HFMCryptoSpecExporter.mq5"
        source = script_path.read_text(encoding="utf-8")
        begin = "// Standalone HFM Crypto Spec Exporter BEGIN"
        end = "// Standalone HFM Crypto Spec Exporter END"
        self.assertIn(begin, source)
        self.assertIn(end, source)
        block = source.split(begin, 1)[1].split(end, 1)[0]

        for marker in [
            "BuildStandaloneHfmCryptoSymbolSpecsJson",
            "QuantGod_HFMCryptoSymbolSpecs.json",
            "QuantGod_HFMCryptoRatesExport.json",
            "quantgod.mql5.hfm_crypto_symbol_specs.v1",
            "quantgod.mql5.hfm_crypto_rates_export.v1",
            "MQL5_SYMBOLINFO_READONLY_STANDALONE",
            "SymbolInfoDouble",
            "SymbolInfoInteger",
            "SymbolInfoString",
            "SymbolInfoTick",
            "CopyRates",
        ]:
            self.assertIn(marker, source)

        for forbidden in [
            "OrderSend(",
            "OrderSendAsync(",
            "TRADE_ACTION_DEAL",
            "PositionClose(",
            "CTrade",
            "SymbolSelect(",
            "FileRead",
        ]:
            self.assertNotIn(forbidden, block)

        expert_path = Path(__file__).resolve().parents[1] / "MQL5" / "Experts" / "QuantGod_HFMCryptoSpecExporterEA.mq5"
        expert_source = expert_path.read_text(encoding="utf-8")
        expert_begin = "// Standalone HFM Crypto Spec Exporter EA BEGIN"
        expert_end = "// Standalone HFM Crypto Spec Exporter EA END"
        self.assertIn(expert_begin, expert_source)
        self.assertIn(expert_end, expert_source)
        expert_block = expert_source.split(expert_begin, 1)[1].split(expert_end, 1)[0]
        for marker in [
            "BuildStandaloneHfmCryptoSymbolSpecsJson",
            "QuantGod_HFMCryptoSymbolSpecs.json",
            "QuantGod_HFMCryptoRatesExport.json",
            "quantgod.mql5.hfm_crypto_symbol_specs.v1",
            "quantgod.mql5.hfm_crypto_rates_export.v1",
            "MQL5_SYMBOLINFO_READONLY_STANDALONE_EA",
            "SymbolInfoDouble",
            "SymbolInfoInteger",
            "SymbolInfoString",
            "SymbolInfoTick",
            "RuntimeProbeWarmupSeconds",
            "CopyRates",
            "ExpertRemove",
        ]:
            self.assertIn(marker, expert_source)

        for forbidden in [
            "OrderSend(",
            "OrderSendAsync(",
            "TRADE_ACTION_DEAL",
            "PositionClose(",
            "CTrade",
            "SymbolSelect(",
            "FileRead",
        ]:
            self.assertNotIn(forbidden, expert_block)

    def test_standalone_exporter_bundle_stages_script_without_mutating_mt5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            scripts = runtime.parent / "Scripts"
            experts = runtime.parent / "Experts"
            scripts.mkdir(parents=True)
            experts.mkdir(parents=True)
            installed_before = sorted(path.name for path in scripts.iterdir())
            experts_before = sorted(path.name for path in experts.iterdir())

            with patch.dict("os.environ", {
                "QG_MT5_SCRIPTS_DIR": str(scripts),
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
            }, clear=False):
                bundle = build_hfm_crypto_standalone_exporter_bundle(runtime, write=True)

            self.assertEqual(bundle["schema"], "quantgod.hfm_crypto_cfd.standalone_exporter_bundle.v1")
            self.assertEqual(bundle["status"], "READY_FOR_MANUAL_STANDALONE_MT5_SPEC_EXPORT")
            self.assertTrue(bundle["standaloneExporterReady"])
            self.assertTrue(bundle["bundleReadyForManualScriptInstall"])
            self.assertFalse(bundle["targetInstalledAndCompiled"])
            self.assertTrue(Path(bundle["bundle"]["stagedScriptPath"]).exists())
            self.assertTrue(Path(bundle["bundle"]["stagedExpertPath"]).exists())
            self.assertEqual(bundle["bundle"]["stagedScriptSha256"], bundle["source"]["repoScriptSha256"])
            self.assertEqual(bundle["bundle"]["stagedExpertSha256"], bundle["source"]["repoExpertSha256"])
            self.assertEqual(bundle["target"]["mt5ScriptsDir"], str(scripts))
            self.assertEqual(bundle["target"]["mt5ExpertsDir"], str(experts))
            self.assertFalse(bundle["target"]["targetScriptExists"])
            self.assertFalse(bundle["target"]["targetCompiledExists"])
            self.assertFalse(bundle["target"]["targetExpertExists"])
            self.assertFalse(bundle["target"]["targetExpertCompiledExists"])
            self.assertTrue(Path(bundle["startupConfig"]["configPath"]).exists())
            startup_text = Path(bundle["startupConfig"]["configPath"]).read_text(encoding="utf-8")
            self.assertIn("AllowLiveTrading=0", startup_text)
            self.assertIn("Expert=QuantGod_HFMCryptoSpecExporterEA", startup_text)
            self.assertIn("ShutdownTerminal=1", startup_text)
            self.assertEqual(bundle["startupConfig"]["preferredStartupMode"], "Expert")
            self.assertTrue(bundle["startupConfig"]["manualOnly"])
            self.assertFalse(bundle["startupConfig"]["executedByCodex"])
            self.assertFalse(bundle["startupConfig"]["scriptRunAttempted"])
            self.assertFalse(bundle["startupConfig"]["allowLiveTrading"])
            self.assertIn("terminal64.exe", bundle["startupConfig"]["command"])
            self.assertTrue(bundle["postRunRefreshPlan"]["manualOnly"])
            self.assertFalse(bundle["postRunRefreshPlan"]["executedByCodex"])
            self.assertFalse(bundle["postRunRefreshPlan"]["orderSendAllowed"])
            self.assertFalse(bundle["postRunRefreshPlan"]["mt5OrderSendAllowed"])
            refresh_commands = bundle["postRunRefreshPlan"]["refreshCommands"]
            self.assertEqual(len(refresh_commands), 6)
            self.assertTrue(all(row["manualOnly"] for row in refresh_commands))
            self.assertTrue(any("rates-export --write --write-profile" in row["command"] for row in refresh_commands))
            self.assertTrue(any("simulation-profile --write" in row["command"] for row in refresh_commands))
            self.assertTrue(any("run_live_automation_readiness.py" in row["command"] for row in refresh_commands))
            self.assertEqual(sorted(path.name for path in scripts.iterdir()), installed_before)
            self.assertEqual(sorted(path.name for path in experts.iterdir()), experts_before)
            self.assertFalse(bundle["installedFilesMutated"])
            self.assertFalse(bundle["copyIntoMt5Allowed"])
            self.assertFalse(bundle["compileAttempted"])
            self.assertFalse(bundle["scriptRunAttempted"])
            self.assertFalse(bundle["mt5OrderSendAllowed"])
            self.assertFalse(bundle["writesMt5OrderRequest"])
            self.assertTrue(all(row["manualOnly"] for row in bundle["commandsForHumanReview"]))

            saved = read_hfm_crypto_standalone_exporter_bundle(runtime)
            self.assertEqual(saved["status"], "READY_FOR_MANUAL_STANDALONE_MT5_SPEC_EXPORT")

    def test_standalone_exporter_bundle_prefers_live16_secondary_seed_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = (
                Path(tmp)
                / "wine"
                / "drive_c"
                / "Program Files"
                / "MetaTrader 5"
                / "MQL5"
                / "Files"
            )
            qg_dir = Path(tmp) / "wine" / "drive_c" / "qg"
            (runtime.parent / "Scripts").mkdir(parents=True)
            (runtime.parent / "Experts").mkdir(parents=True)
            qg_dir.mkdir(parents=True)
            (qg_dir / "QuantGod_MT5_HFM_LivePilot_mac.ini").write_text(
                "[Common]\nLogin=186054398\nServer=HFMarketsGlobal-Live12\n[StartUp]\nSymbol=USDJPYc\n",
                encoding="utf-8",
            )
            (qg_dir / "QuantGod_MT5_HFM_LiveSecondary_mac.ini").write_text(
                "[Common]\nLogin=198135388\nServer=HFMarketsGlobal-Live16\n[StartUp]\nSymbol=EURUSD\n",
                encoding="utf-8",
            )

            bundle = build_hfm_crypto_standalone_exporter_bundle(runtime, write=True)

            config_source = bundle["startupConfig"]["configSource"]
            self.assertIn("QuantGod_MT5_HFM_LiveSecondary_mac.ini", config_source["seedConfigPath"])
            self.assertTrue(config_source["loginPresent"])
            self.assertTrue(config_source["serverPresent"])
            self.assertEqual(config_source["startupSymbol"], "#BTCUSD")
            startup_text = Path(bundle["startupConfig"]["configPath"]).read_text(encoding="utf-8")
            self.assertIn("Login=198135388", startup_text)
            self.assertIn("Server=HFMarketsGlobal-Live16", startup_text)
            self.assertIn("Symbol=#BTCUSD", startup_text)

    def test_standalone_exporter_bundle_detects_installed_compiled_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            scripts = runtime.parent / "Scripts"
            experts = runtime.parent / "Experts"
            scripts.mkdir(parents=True)
            experts.mkdir(parents=True)

            with patch.dict("os.environ", {
                "QG_MT5_SCRIPTS_DIR": str(scripts),
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
            }, clear=False):
                staged = build_hfm_crypto_standalone_exporter_bundle(runtime, write=True)
                source = Path(staged["bundle"]["stagedScriptPath"])
                target = scripts / "QuantGod_HFMCryptoSpecExporter.mq5"
                compiled = scripts / "QuantGod_HFMCryptoSpecExporter.ex5"
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                compiled.write_bytes(b"compiled fixture")
                expert_source = Path(staged["bundle"]["stagedExpertPath"])
                target_expert = experts / "QuantGod_HFMCryptoSpecExporterEA.mq5"
                compiled_expert = experts / "QuantGod_HFMCryptoSpecExporterEA.ex5"
                target_expert.write_text(expert_source.read_text(encoding="utf-8"), encoding="utf-8")
                compiled_expert.write_bytes(b"compiled fixture")
                bundle = build_hfm_crypto_standalone_exporter_bundle(runtime, write=False)

            self.assertEqual(bundle["status"], "READY_TO_RUN_STANDALONE_MT5_SPEC_EXPORT")
            self.assertTrue(bundle["targetInstalledAndCompiled"])
            self.assertTrue(bundle["targetExpertInstalledAndCompiled"])
            self.assertTrue(bundle["target"]["targetScriptExists"])
            self.assertTrue(bundle["target"]["targetCompiledExists"])
            self.assertTrue(bundle["target"]["targetInstalledMatchesBundle"])
            self.assertTrue(bundle["target"]["targetExpertExists"])
            self.assertTrue(bundle["target"]["targetExpertCompiledExists"])
            self.assertTrue(bundle["target"]["targetExpertInstalledMatchesBundle"])
            self.assertFalse(bundle["orderSendAllowed"])
            self.assertFalse(bundle["mt5OrderSendAllowed"])
            self.assertFalse(bundle["writesMt5OrderRequest"])
            self.assertIn("Expert", bundle["nextRequiredActionZh"])

    def test_standalone_exporter_runner_compiles_from_drive_c_qg_and_syncs_ex5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = (
                Path(tmp)
                / "wine"
                / "drive_c"
                / "Program Files"
                / "MetaTrader 5"
                / "MQL5"
                / "Files"
            )
            scripts = runtime.parent / "Scripts"
            workdir = runtime.parents[1]
            scripts.mkdir(parents=True)
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "metaeditor64.exe").write_bytes(b"fake metaeditor")
            source = scripts / "QuantGod_HFMCryptoSpecExporter.mq5"
            source.write_text("// read-only exporter fixture\n", encoding="utf-8")
            commands = []

            def fake_run_command(command, *, cwd, wineprefix, timeout):
                commands.append(command)
                work_source = Path(tmp) / "wine" / "drive_c" / "qg" / source.name
                work_source.with_suffix(".ex5").write_bytes(b"compiled exporter")
                return {
                    "attempted": True,
                    "returnCode": 0,
                    "stdoutTail": "",
                    "stderrTail": "",
                    "command": command,
                    "cwd": str(cwd),
                }

            with patch.object(hfm_crypto_standalone_runner, "_default_wine64_path", return_value=Path("/fake/wine64")):
                with patch.object(hfm_crypto_standalone_runner, "_run_command", side_effect=fake_run_command):
                    result = hfm_crypto_standalone_runner._compile_source(
                        runtime,
                        source,
                        "QuantGod_HFMCryptoSpecExporter_compile.log",
                    )

            self.assertTrue(commands)
            self.assertIn(r"C:\Program Files\MetaTrader 5\metaeditor64.exe", commands[0])
            self.assertIn(r"/compile:C:\qg\QuantGod_HFMCryptoSpecExporter.mq5", commands[0])
            self.assertTrue((scripts / "QuantGod_HFMCryptoSpecExporter.ex5").exists())
            self.assertTrue(result["copiedCompiledBack"])
            self.assertTrue(result["compiledFresh"])
            self.assertTrue(result["workCompiledExists"])

    def test_mt5_upgrade_runner_installs_and_compiles_multistrategy_ea(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = (
                Path(tmp)
                / "wine"
                / "drive_c"
                / "Program Files"
                / "MetaTrader 5"
                / "MQL5"
                / "Files"
            )
            experts = runtime.parent / "Experts"
            workdir = runtime.parents[1]
            experts.mkdir(parents=True)
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "metaeditor64.exe").write_bytes(b"fake metaeditor")
            installed = experts / "QuantGod_MultiStrategy.mq5"
            installed.write_text("// old ea without hfm exporter\n", encoding="utf-8")
            commands = []

            def fake_run_command(command, *, cwd, wineprefix, timeout):
                commands.append(command)
                work_source = Path(tmp) / "wine" / "drive_c" / "qg" / installed.name
                work_source.with_suffix(".ex5").write_bytes(b"compiled multistrategy")
                return {
                    "attempted": True,
                    "returnCode": 0,
                    "stdoutTail": "",
                    "stderrTail": "",
                    "command": command,
                    "cwd": str(cwd),
                }

            with patch.object(hfm_crypto_standalone_runner, "_default_wine64_path", return_value=Path("/fake/wine64")):
                with patch.object(hfm_crypto_standalone_runner, "_run_command", side_effect=fake_run_command):
                    result = hfm_crypto_mt5_upgrade_runner.build_hfm_crypto_mt5_upgrade_runner(
                        runtime,
                        install=True,
                        compile_source=True,
                        write=True,
                    )

            self.assertTrue(commands)
            self.assertEqual(result["status"], "MT5_UPGRADE_RUNNER_INSTALLED_AND_COMPILED")
            self.assertTrue(result["installedFilesMutated"])
            self.assertTrue(result["compileResult"]["compiledFresh"])
            self.assertTrue((experts / "QuantGod_MultiStrategy.ex5").exists())
            self.assertIn("BuildHfmCryptoRuntimeProbeJson", installed.read_text(encoding="utf-8"))
            self.assertTrue(Path(result["installResult"]["backupPath"]).exists())
            self.assertFalse(result["orderSendAllowed"])
            self.assertFalse(result["mt5OrderSendAllowed"])
            self.assertFalse(result["writesMt5OrderRequest"])

    def test_mt5_upgrade_runner_detects_orphan_live16_terminal_by_config(self) -> None:
        ps_output = (
            "  PID   TT  STAT      TIME COMMAND\n"
            "35088 s002  R+    17:02.23 /fake/wine64-preloader terminal64.exe /portable /config:C:\\qg\\QuantGod_MT5_HFM_LiveSecondary_mac.ini\n"
            "17202 s000  R+  5576:33.85 /fake/wine64-preloader terminal64.exe /portable /config:C:\\qg\\QuantGod_MT5_HFM_LivePilot_mac.ini\n"
        )

        def fake_run(command, **kwargs):
            self.assertEqual(command, ["ps", "ax"])
            return subprocess.CompletedProcess(command, 0, stdout=ps_output, stderr="")

        with patch.object(hfm_crypto_mt5_upgrade_runner.subprocess, "run", side_effect=fake_run):
            rows = hfm_crypto_mt5_upgrade_runner._matching_terminal_processes(
                wineprefix=Path("/Users/bowen/Library/Application Support/net.metaquotes.wine.metatrader5-live16"),
                windows_config="C:\\qg\\QuantGod_MT5_HFM_LiveSecondary_mac.ini",
            )

        self.assertEqual([row["pid"] for row in rows], [35088])
        self.assertTrue(rows[0]["matchedWindowsConfig"])

    def test_standalone_exporter_bundle_detects_specs_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            scripts = runtime.parent / "Scripts"
            experts = runtime.parent / "Experts"
            scripts.mkdir(parents=True)
            experts.mkdir(parents=True)

            with patch.dict("os.environ", {
                "QG_MT5_SCRIPTS_DIR": str(scripts),
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
            }, clear=False):
                staged = build_hfm_crypto_standalone_exporter_bundle(runtime, write=True)
                source = Path(staged["bundle"]["stagedScriptPath"])
                (scripts / "QuantGod_HFMCryptoSpecExporter.mq5").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                (scripts / "QuantGod_HFMCryptoSpecExporter.ex5").write_bytes(b"compiled fixture")
                expert_source = Path(staged["bundle"]["stagedExpertPath"])
                (experts / "QuantGod_HFMCryptoSpecExporterEA.mq5").write_text(expert_source.read_text(encoding="utf-8"), encoding="utf-8")
                (experts / "QuantGod_HFMCryptoSpecExporterEA.ex5").write_bytes(b"compiled fixture")
                specs = runtime / "hfm_crypto" / "QuantGod_HFMCryptoSymbolSpecs.json"
                specs.parent.mkdir(parents=True, exist_ok=True)
                specs.write_text(json.dumps({
                    "symbols": [{
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                        "contractSize": 1,
                        "tickSize": 0.01,
                        "tickValue": 0.01,
                        "minLot": 0.01,
                        "lotStep": 0.01,
                        "maxLot": 5,
                    }]
                }), encoding="utf-8")
                probe = runtime / "hfm_crypto" / "QuantGod_HFMCryptoRuntimeProbe.json"
                probe.write_text(json.dumps({
                    "symbols": [{
                        "brokerSymbol": "#BTCUSD",
                        "canonicalSymbol": "BTCUSD",
                        "tickOk": True,
                        "bid": 65000.0,
                        "ask": 65005.0,
                    }]
                }), encoding="utf-8")
                bundle = read_hfm_crypto_standalone_exporter_bundle(runtime)

            self.assertEqual(bundle["status"], "STANDALONE_MT5_SPEC_EXPORT_OUTPUT_DETECTED")
            self.assertTrue(bundle["output"]["expectedSpecsExists"])
            self.assertTrue(bundle["output"]["expectedSpecsReadable"])
            self.assertEqual(bundle["output"]["expectedSpecsRowCount"], 1)
            self.assertTrue(bundle["runtimeProbeTickDetected"])
            self.assertFalse(bundle["runtimeProbeMissingAfterSpecs"])
            self.assertIn("刷新", bundle["nextRequiredActionZh"])
            self.assertFalse(bundle["scriptRunAttempted"])
            self.assertFalse(bundle["mt5OrderSendAllowed"])

    def test_standalone_exporter_bundle_distinguishes_probe_file_from_live_tick(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            specs = runtime / "hfm_crypto" / "QuantGod_HFMCryptoSymbolSpecs.json"
            specs.parent.mkdir(parents=True, exist_ok=True)
            specs.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 5,
                }]
            }), encoding="utf-8")
            probe = runtime / "hfm_crypto" / "QuantGod_HFMCryptoRuntimeProbe.json"
            probe.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "tickOk": False,
                    "bid": 0.0,
                    "ask": 0.0,
                }]
            }), encoding="utf-8")

            bundle = read_hfm_crypto_standalone_exporter_bundle(runtime)

            self.assertEqual(bundle["status"], "STANDALONE_MT5_SPEC_EXPORT_OUTPUT_DETECTED")
            self.assertTrue(bundle["runtimeProbeDetected"])
            self.assertFalse(bundle["runtimeProbeTickDetected"])
            self.assertFalse(bundle["runtimeProbeMissingAfterSpecs"])
            self.assertTrue(bundle["output"]["expectedRuntimeProbeReadable"])
            self.assertEqual(bundle["output"]["expectedRuntimeProbeSymbolCount"], 1)
            self.assertIn("刷新", bundle["nextRequiredActionZh"])

    def test_standalone_exporter_bundle_surfaces_missing_runtime_probe_after_specs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            specs = runtime / "hfm_crypto" / "QuantGod_HFMCryptoSymbolSpecs.json"
            specs.parent.mkdir(parents=True, exist_ok=True)
            specs.write_text(json.dumps({
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 5,
                }]
            }), encoding="utf-8")

            bundle = read_hfm_crypto_standalone_exporter_bundle(runtime)

            self.assertEqual(bundle["status"], "WAITING_STANDALONE_MT5_RUNTIME_PROBE_INSTALL")
            self.assertFalse(bundle["runtimeProbeDetected"])
            self.assertTrue(bundle["runtimeProbeMissingAfterSpecs"])
            self.assertFalse(bundle["runtimeProbeTickDetected"])
            self.assertTrue(bundle["output"]["expectedSpecsExists"])
            self.assertFalse(bundle["output"]["expectedRuntimeProbeExists"])
            self.assertIn("runtime probe", bundle["nextRequiredActionZh"])
            self.assertFalse(bundle["mt5OrderSendAllowed"])
            self.assertFalse(bundle["copyIntoMt5Allowed"])

    def test_hfm_crypto_state_surfaces_ready_to_run_standalone_exporter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            scripts = runtime.parent / "Scripts"
            experts = runtime.parent / "Experts"
            scripts.mkdir(parents=True)
            experts.mkdir(parents=True)

            with patch.dict("os.environ", {
                "QG_MT5_SCRIPTS_DIR": str(scripts),
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
            }, clear=False):
                staged = build_hfm_crypto_standalone_exporter_bundle(runtime, write=True)
                source = Path(staged["bundle"]["stagedScriptPath"])
                (scripts / "QuantGod_HFMCryptoSpecExporter.mq5").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                (scripts / "QuantGod_HFMCryptoSpecExporter.ex5").write_bytes(b"compiled fixture")
                expert_source = Path(staged["bundle"]["stagedExpertPath"])
                (experts / "QuantGod_HFMCryptoSpecExporterEA.mq5").write_text(expert_source.read_text(encoding="utf-8"), encoding="utf-8")
                (experts / "QuantGod_HFMCryptoSpecExporterEA.ex5").write_bytes(b"compiled fixture")
                state = build_hfm_crypto_cfd_state(runtime, write=False)

            self.assertEqual(state["status"], "WAITING_HFM_CRYPTO_SYMBOLS")
            self.assertEqual(state["statusZh"], "等待运行独立只读 Specs 导出 EA")
            self.assertEqual(state["standaloneExporterBundle"]["status"], "READY_TO_RUN_STANDALONE_MT5_SPEC_EXPORT")
            self.assertTrue(state["standaloneExporterBundle"]["targetInstalledAndCompiled"])
            self.assertTrue(state["standaloneExporterBundle"]["targetExpertInstalledAndCompiled"])
            self.assertEqual(state["blockers"][0]["code"], "HFM_CRYPTO_STANDALONE_EXPORTER_READY_TO_RUN")
            self.assertIn("Expert", state["nextRequiredActionZh"])
            self.assertFalse(state["safety"]["orderSendAllowed"])
            self.assertFalse(state["safety"]["mt5OrderSendAllowed"])

    def test_state_rebuilds_stale_contract_export_after_specs_output_arrives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            scripts = runtime.parent / "Scripts"
            scripts.mkdir(parents=True)
            stale_export = contract_spec_export_path(runtime)
            stale_export.parent.mkdir(parents=True)
            stale_export.write_text(json.dumps({
                "schema": "quantgod.hfm_crypto_cfd.contract_spec_export.v1",
                "status": "WAITING_HFM_CRYPTO_CONTRACT_SPEC_EXPORT",
                "readyForContractSpecReviewInput": False,
                "symbols": [],
            }), encoding="utf-8")

            with patch.dict("os.environ", {
                "QG_MT5_SCRIPTS_DIR": str(scripts),
                "QG_RUNTIME_DIR": str(runtime),
            }, clear=False):
                staged = build_hfm_crypto_standalone_exporter_bundle(runtime, write=True)
                source = Path(staged["bundle"]["stagedScriptPath"])
                (scripts / "QuantGod_HFMCryptoSpecExporter.mq5").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                (scripts / "QuantGod_HFMCryptoSpecExporter.ex5").write_bytes(b"compiled fixture")
                specs = runtime / "hfm_crypto" / "QuantGod_HFMCryptoSymbolSpecs.json"
                specs.write_text(json.dumps({
                    "symbols": [{
                        "brokerSymbol": "#ETHUSD",
                        "canonicalSymbol": "ETHUSD",
                        "contractSize": 1,
                        "tickSize": 0.01,
                        "tickValue": 0.01,
                        "minLot": 0.01,
                        "lotStep": 0.01,
                        "maxLot": 5,
                    }]
                }), encoding="utf-8")
                state = build_hfm_crypto_cfd_state(runtime, write=True)

            self.assertEqual(state["status"], "READY_FOR_SHADOW_RESEARCH")
            self.assertTrue(state["contractSpecExport"]["readyForContractSpecReviewInput"])
            self.assertEqual(state["contractSpecExport"]["sourceFormat"], "EA_SYMBOL_SPECS_JSON")
            self.assertEqual(state["contractSpecExport"]["coveredBrokerSymbols"], ["#ETHUSD"])
            self.assertTrue(state["executionSpecReview"]["readyForExecutionSpecReview"])
            self.assertTrue(state["symbolEvidence"]["found"])
            self.assertFalse(state["safety"]["orderSendAllowed"])
            self.assertFalse(state["safety"]["mt5OrderSendAllowed"])

    def test_hfm_crypto_copyrates_export_builds_autogen_profile_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            hfm = runtime / "hfm_crypto"
            rates_dir = hfm / "rates"
            rates_dir.mkdir(parents=True)
            contract_spec_export_path(runtime).write_text(json.dumps({
                "schema": "quantgod.hfm_crypto_cfd.contract_spec_export.v1",
                "readyForContractSpecReviewInput": True,
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "description": "Bitcoin vs US Dollar",
                    "path": "Crypto CFD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 2,
                }],
            }), encoding="utf-8")
            csv_path = rates_dir / "BTCUSD.csv"
            rows = ["epoch,timestamp,open,high,low,close,tick_volume,spread,real_volume"]
            price = 50000.0
            epoch = 1_800_000_000
            for cycle in range(24):
                direction = 1 if cycle % 2 == 0 else -1
                for step in range(40):
                    open_price = price
                    price += direction * 220.0
                    high = max(open_price, price)
                    low = min(open_price, price)
                    rows.append(f"{epoch},2026.05.31 00:{step:02d}:00,{open_price:.2f},{high:.2f},{low:.2f},{price:.2f},100,0,0")
                    epoch += 900
            csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            manifest = hfm / "QuantGod_HFMCryptoRatesExport.json"
            manifest.write_text(json.dumps({
                "schema": "quantgod.mql5.hfm_crypto_rates_export.v1",
                "source": "MQL5_COPYRATES_READONLY_STANDALONE_EA",
                "timeframe": "M15",
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "timeframe": "M15",
                    "file": "rates/BTCUSD.csv",
                    "copiedBars": 960,
                    "ok": True,
                }],
                "safety": {"readOnly": True, "orderSendAllowed": False},
            }), encoding="utf-8")

            review = build_hfm_crypto_rates_export_review(runtime, write=True, write_profile=True)

            self.assertEqual(review["schema"], "quantgod.hfm_crypto_cfd.rates_export_review.v1")
            self.assertTrue(review["ratesReadyForSimulation"])
            self.assertTrue(review["autogenProfileReady"])
            self.assertTrue(rates_autogen_profile_path(runtime).exists())
            self.assertTrue(rates_export_review_path(runtime).exists())
            self.assertGreaterEqual(review["profileCandidate"]["pnlUsd"], 20.0)
            self.assertFalse(review["safety"]["orderSendAllowed"])
            saved = read_hfm_crypto_rates_export_review(runtime)
            self.assertTrue(saved["autogenProfileReady"])

            sim_review = build_hfm_crypto_simulation_profile_review(runtime, write=True)
            self.assertTrue(sim_review["simulationQualified"])
            self.assertEqual(sim_review["sourceSelection"]["path"], str(rates_autogen_profile_path(runtime)))
            self.assertGreaterEqual(sim_review["metrics"]["pnl"], 20.0)
            self.assertFalse(sim_review["mt5OrderSendAllowed"])

    def test_hfm_crypto_copyrates_export_reconstructs_manifest_from_partial_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "MQL5" / "Files"
            hfm = runtime / "hfm_crypto"
            rates_dir = hfm / "rates"
            rates_dir.mkdir(parents=True)
            contract_spec_export_path(runtime).write_text(json.dumps({
                "schema": "quantgod.hfm_crypto_cfd.contract_spec_export.v1",
                "readyForContractSpecReviewInput": True,
                "symbols": [{
                    "brokerSymbol": "#BTCUSD",
                    "canonicalSymbol": "BTCUSD",
                    "contractSize": 1,
                    "tickSize": 0.01,
                    "tickValue": 0.01,
                    "minLot": 0.01,
                    "lotStep": 0.01,
                    "maxLot": 2,
                }],
            }), encoding="utf-8")
            csv_path = rates_dir / "BTCUSD___BTCUSD__M15.csv"
            rows = ["epoch,timestamp,open,high,low,close,tick_volume,spread,real_volume"]
            price = 50000.0
            epoch = 1_800_000_000
            for cycle in range(24):
                direction = 1 if cycle % 2 == 0 else -1
                for step in range(40):
                    open_price = price
                    price += direction * 220.0
                    high = max(open_price, price)
                    low = min(open_price, price)
                    rows.append(f"{epoch},2026.05.31 00:{step:02d}:00,{open_price:.2f},{high:.2f},{low:.2f},{price:.2f},100,0,0")
                    epoch += 900
            csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

            review = build_hfm_crypto_rates_export_review(runtime, write=True, write_profile=True)

            manifest = hfm / "QuantGod_HFMCryptoRatesExport.json"
            self.assertTrue(manifest.exists())
            self.assertEqual(review["manifestPath"], str(manifest))
            self.assertTrue(review["manifestFromPartialCsvs"])
            self.assertTrue(review["ratesReadyForSimulation"])
            self.assertTrue(review["autogenProfileReady"])
            self.assertEqual(review["selectedSeries"]["canonicalSymbol"], "BTCUSD")
            self.assertGreaterEqual(review["profileCandidate"]["pnlUsd"], 20.0)
            self.assertFalse(review["safety"]["mt5OrderSendAllowed"])

    def test_mt5_post_upgrade_verify_waits_until_manual_upgrade_is_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            experts = runtime / "Experts"
            experts.mkdir()
            installed = experts / "QuantGod_MultiStrategy.mq5"
            installed.write_text("#property strict\nvoid OnTick() {}\n", encoding="utf-8")

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                build_hfm_crypto_mt5_upgrade_bundle(runtime, write=True)
                verify = build_hfm_crypto_mt5_post_upgrade_verify(runtime, write=True)

            self.assertEqual(verify["schema"], "quantgod.hfm_crypto_cfd.mt5_post_upgrade_verify.v1")
            self.assertEqual(verify["status"], "WAITING_MANUAL_MT5_EA_UPGRADE")
            self.assertFalse(verify["postUpgradeVerified"])
            self.assertFalse(verify["checks"]["installedSourceHasExporter"])
            self.assertFalse(verify["checks"]["sourceHashMatchesBundle"])
            self.assertFalse(verify["installedFilesMutated"])
            self.assertFalse(verify["compileAttempted"])
            self.assertFalse(verify["mt5OrderSendAllowed"])

            saved = read_hfm_crypto_mt5_post_upgrade_verify(runtime)
            self.assertEqual(saved["status"], "WAITING_MANUAL_MT5_EA_UPGRADE")

    def test_mt5_post_upgrade_verify_runs_contract_review_when_specs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            experts = runtime / "Experts"
            experts.mkdir()
            repo_mql = Path(__file__).resolve().parents[1] / "MQL5" / "Experts" / "QuantGod_MultiStrategy.mq5"
            installed = experts / "QuantGod_MultiStrategy.mq5"
            installed.write_text("#property strict\nvoid OnTick() {}\n", encoding="utf-8")
            binary = experts / "QuantGod_MultiStrategy.ex5"

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                bundle = build_hfm_crypto_mt5_upgrade_bundle(runtime, write=True)
                installed.write_text(Path(bundle["bundle"]["stagedSourcePath"]).read_text(encoding="utf-8"), encoding="utf-8")
                binary.write_text("compiled fixture", encoding="utf-8")
                dashboard = runtime / "QuantGod_Dashboard.json"
                dashboard.write_text(json.dumps({
                    "build": "QuantGod-v3.17-test",
                    "timestamp": "2026.05.28 09:00:00",
                    "hfmCryptoSymbolSpecs": {
                        "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                        "source": "MQL5_SYMBOLINFO_READONLY",
                        "symbolCount": 1,
                        "symbols": [{
                            "brokerSymbol": "#BTCUSD",
                            "canonicalSymbol": "BTCUSD",
                            "description": "Bitcoin vs US Dollar",
                            "path": "Crypto CFD",
                            "tradeContractSize": 1,
                            "tradeTickSize": 0.01,
                            "tradeTickValue": 0.01,
                            "volumeMin": 0.01,
                            "volumeStep": 0.01,
                            "volumeMax": 2,
                            "tradeEnabled": True,
                        }],
                    },
                }), encoding="utf-8")
                verify = build_hfm_crypto_mt5_post_upgrade_verify(runtime, write=True)

            self.assertEqual(verify["status"], "HFM_CRYPTO_MT5_POST_UPGRADE_VERIFIED")
            self.assertTrue(verify["postUpgradeVerified"])
            self.assertTrue(verify["checks"]["installedSourceHasExporter"])
            self.assertTrue(verify["checks"]["sourceHashMatchesBundle"])
            self.assertTrue(verify["checks"]["installedBinaryNotOlderThanSource"])
            self.assertTrue(verify["checks"]["hfmCryptoSpecsAvailable"])
            self.assertTrue(verify["readyForContractSpecReview"])
            self.assertTrue(verify["executionSpecReviewReady"])
            self.assertEqual(verify["contractSpecExport"]["coveredBrokerSymbols"], ["#BTCUSD"])
            self.assertFalse(verify["orderSendAllowed"])
            self.assertFalse(verify["brokerCallsMade"])

    def test_post_upgrade_controller_waits_and_stages_manual_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            experts = runtime / "Experts"
            experts.mkdir()
            installed = experts / "QuantGod_MultiStrategy.mq5"
            installed.write_text("#property strict\nvoid OnTick() {}\n", encoding="utf-8")

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                controller = build_hfm_crypto_post_upgrade_controller(runtime, write=True)

            self.assertEqual(controller["schema"], "quantgod.hfm_crypto_cfd.post_upgrade_controller.v1")
            self.assertEqual(controller["status"], "WAITING_MANUAL_MT5_EA_UPGRADE")
            self.assertTrue(controller["artifacts"]["mt5UpgradeBundle"]["bundleReadyForManualUpgrade"])
            self.assertFalse(controller["postUpgradeReviewAutomated"])
            self.assertFalse(controller["controllerChecks"]["installedSourceHasExporter"])
            self.assertFalse(controller["installedFilesMutated"])
            self.assertFalse(controller["compileAttempted"])
            self.assertFalse(controller["copyIntoMt5Allowed"])
            self.assertFalse(controller["orderSendAllowed"])
            self.assertFalse(controller["mt5OrderSendAllowed"])
            self.assertFalse(controller["writesMt5OrderRequest"])
            self.assertTrue((runtime / "hfm_crypto" / "QuantGod_HFMCryptoPostUpgradeController.json").exists())

            saved = read_hfm_crypto_post_upgrade_controller(runtime)
            self.assertEqual(saved["status"], "WAITING_MANUAL_MT5_EA_UPGRADE")

    def test_post_upgrade_controller_automates_review_when_specs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            experts = runtime / "Experts"
            experts.mkdir()
            installed = experts / "QuantGod_MultiStrategy.mq5"
            installed.write_text("#property strict\nvoid OnTick() {}\n", encoding="utf-8")
            binary = experts / "QuantGod_MultiStrategy.ex5"

            with patch.dict("os.environ", {
                "QG_MT5_EXPERTS_DIR": str(experts),
                "QG_RUNTIME_DIR": str(runtime),
                "QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY": "1",
            }, clear=False):
                bundle = build_hfm_crypto_mt5_upgrade_bundle(runtime, write=True)
                installed.write_text(Path(bundle["bundle"]["stagedSourcePath"]).read_text(encoding="utf-8"), encoding="utf-8")
                binary.write_text("compiled fixture", encoding="utf-8")
                (runtime / "QuantGod_Dashboard.json").write_text(json.dumps({
                    "build": "QuantGod-v3.17-test",
                    "timestamp": "2026.05.28 09:00:00",
                    "hfmCryptoSymbolSpecs": {
                        "schema": "quantgod.mql5.hfm_crypto_symbol_specs.v1",
                        "source": "MQL5_SYMBOLINFO_READONLY",
                        "symbolCount": 1,
                        "symbols": [{
                            "brokerSymbol": "#ETHUSD",
                            "canonicalSymbol": "ETHUSD",
                            "description": "Ethereum vs US Dollar",
                            "path": "Crypto CFD",
                            "tradeContractSize": 1,
                            "tradeTickSize": 0.01,
                            "tradeTickValue": 0.01,
                            "volumeMin": 0.01,
                            "volumeStep": 0.01,
                            "volumeMax": 3,
                            "tradeEnabled": True,
                        }],
                    },
                }), encoding="utf-8")
                controller = build_hfm_crypto_post_upgrade_controller(runtime, write=True)

            self.assertEqual(controller["status"], "HFM_CRYPTO_POST_UPGRADE_REVIEW_AUTOMATED")
            self.assertTrue(controller["postUpgradeReviewAutomated"])
            self.assertTrue(controller["readyForHfmContractSpecReview"])
            self.assertTrue(controller["executionSpecReviewReady"])
            self.assertTrue(controller["controllerChecks"]["hfmCryptoSpecsAvailable"])
            self.assertTrue(controller["controllerChecks"]["contractSpecExportReady"])
            self.assertTrue(controller["controllerChecks"]["executionSpecReviewReady"])
            self.assertEqual(controller["artifacts"]["contractSpecExport"]["validRowCount"], 1)
            self.assertEqual(controller["artifacts"]["executionSpec"]["validRowCount"], 1)
            self.assertTrue((runtime / "hfm_crypto" / "QuantGod_HFMCryptoContractSpecExport.json").exists())
            self.assertTrue((runtime / "hfm_crypto" / "QuantGod_HFMCryptoExecutionSpecReview.json").exists())
            self.assertFalse(controller["requestWritesAllowed"])
            self.assertFalse(controller["brokerCallsMade"])
            self.assertFalse(controller["hfmCryptoExecutionAllowed"])

    def test_reviews_simulation_profile_without_execution_rights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            profile_path = runtime / "hfm_crypto_simulation_profile.json"
            profile_path.write_text(json.dumps({
                "agentId": "agt_hfm_crypto_sim",
                "metrics": {
                    "pnlUsd": 65.5,
                    "roi": "21.2%",
                    "sharpe": 1.8,
                    "maxDrawdown": "6.5%",
                    "trades": 64,
                    "liquidations": 0,
                },
                "backtest": {"dateRange": "2026-04-01..2026-05-01"},
            }), encoding="utf-8")

            review = build_hfm_crypto_simulation_profile_review(
                runtime,
                simulation_profile_json=str(profile_path),
                write=True,
            )

            self.assertEqual(review["schema"], "quantgod.hfm_crypto_cfd.simulation_profile_review.v1")
            self.assertEqual(review["status"], "SIMULATION_PROFILE_QUALIFIED")
            self.assertTrue(review["simulationQualified"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])
            self.assertEqual(review["metrics"]["agentId"], "agt_hfm_crypto_sim")
            self.assertEqual(review["metrics"]["pnl"], 65.5)
            self.assertIn("pnlUsd", review["requiredFields"])

            saved = read_hfm_crypto_simulation_profile_review(runtime)
            self.assertEqual(saved["status"], "SIMULATION_PROFILE_QUALIFIED")

            state = build_hfm_crypto_cfd_state(
                runtime,
                simulation_profile_json=str(profile_path),
                write=False,
            )
            self.assertTrue(state["simulationProfileReview"]["simulationQualified"])

    def test_simulation_profile_requires_positive_usd_pnl_for_combined_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            profile_path = runtime / "hfm_crypto_simulation_profile.json"
            profile_path.write_text(json.dumps({
                "agentId": "agt_hfm_crypto_no_pnl",
                "metrics": {
                    "roi": "21.2%",
                    "sharpe": 1.8,
                    "maxDrawdown": "6.5%",
                    "trades": 64,
                    "liquidations": 0,
                },
            }), encoding="utf-8")

            review = build_hfm_crypto_simulation_profile_review(
                runtime,
                simulation_profile_json=str(profile_path),
                write=False,
            )

            self.assertEqual(review["status"], "WAITING_HFM_CRYPTO_SIMULATION_PROFILE")
            self.assertFalse(review["simulationQualified"])
            codes = {row["code"] for row in review["blockers"]}
            self.assertIn("HFM_PNL_USD_NOT_POSITIVE", codes)
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])

    def test_auto_discovers_saved_moss_profile_without_execution_rights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            saved_profile = moss_backtest_path(runtime)
            saved_profile.parent.mkdir(parents=True)
            saved_profile.write_text(json.dumps({
                "agentId": "agt_auto_moss_profile",
                "metrics": {
                    "pnlUsd": 66.0,
                    "roi": "16.4%",
                    "sharpe": 1.35,
                    "maxDrawdown": "8.5%",
                    "trades": 41,
                    "liquidations": 0,
                },
            }), encoding="utf-8")

            review = build_hfm_crypto_simulation_profile_review(runtime, write=True)

            self.assertEqual(review["status"], "SIMULATION_PROFILE_QUALIFIED")
            self.assertTrue(review["simulationQualified"])
            self.assertTrue(review["sourceSelection"]["autoDiscovered"])
            self.assertEqual(review["sourceSelection"]["path"], str(saved_profile))
            self.assertEqual(review["metrics"]["agentId"], "agt_auto_moss_profile")
            self.assertTrue(any(row["path"] == str(saved_profile) and row["qualified"] for row in review["autoProfileCandidates"]))
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["mt5OrderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])

            state = build_hfm_crypto_cfd_state(runtime, write=False)
            self.assertTrue(state["mossBacktestProfile"]["profileFound"])
            self.assertEqual(state["mossBacktestProfile"]["source"], "simulation_profile_review_artifact")
            self.assertEqual(state["mossBacktestProfile"]["profileJsonPath"], str(saved_profile))
            self.assertEqual(state["mossBacktestProfile"]["metrics"]["agentId"], "agt_auto_moss_profile")
            self.assertTrue(state["simulationProfileReview"]["simulationQualified"])
            self.assertFalse(state["shadowPlan"]["writesOrders"])
            self.assertFalse(state["riskBoundary"]["autoFlattenAllowed"])


if __name__ == "__main__":
    unittest.main()
