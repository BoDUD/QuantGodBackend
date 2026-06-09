from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.live_automation_readiness.live_execution_adapter import build_live_execution_adapter_write_review
from tools.live_automation_readiness.live_execution_request_writer import (
    REVIEWED_REQUEST_WRITE_RELEASE_TOKEN,
    canonical_request_json,
    commit_request_file,
    prepare_request_writer_decision,
)
from tools.live_automation_readiness.schema import (
    adapter_contract_validator_path,
    adapter_sandbox_review_path,
    execution_adapter_harness_path,
    live_execution_adapter_write_review_path,
    live_execution_implementation_spec_path,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class LiveExecutionAdapterWriterTests(unittest.TestCase):
    def test_disabled_writer_contract_serializes_requests_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request = {
                "requestId": "sandbox-review-btc-001",
                "schema": "quantgod.mt5_reviewed_order_request.v1",
                "createdAtIso": "1970-01-01T00:00:00Z",
                "reviewPacketHash": "review-hash",
                "runtimePreflightHash": "preflight-hash",
                "operatorApprovalId": "review-only-operator-approval",
                "lane": "HFM_CRYPTO_CFD",
                "brokerSymbol": "#BTCUSD",
                "canonicalSymbol": "BTCUSD",
                "side": "BUY",
                "orderType": "MARKET",
                "volumeLots": 0.0,
                "slPrice": None,
                "tpPrice": None,
                "maxSlippagePoints": 0.0,
                "maxSpreadPoints": 0.0,
                "maxDailyLossPct": 0.0,
                "maxDailyLossR": 0.0,
                "maxConsecutiveLosses": 0,
                "killSwitchOk": True,
                "runtimeFresh": True,
                "spreadProbeOk": True,
                "symbolMappingOk": True,
                "dryRunReplayPassed": True,
            }
            _write_json(adapter_sandbox_review_path(runtime), {
                "schema": "quantgod.adapter_sandbox_review_bundle.v1",
                "sampleRequests": [request],
            })
            _write_json(live_execution_implementation_spec_path(runtime), {
                "schema": "quantgod.live_execution_implementation_spec.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "dataPlaneImplementationSpecReady": True,
                "executionModeOnlyBlocked": True,
                "readyForLiveExecutionImplementationSpecReview": False,
                "implementationSteps": [{"stepId": "live_execution_adapter_write_path"}],
                "blockers": [
                    {
                        "code": "MT5_READ_ONLY_MODE_STILL_ACTIVE",
                        "reasonZh": "read only",
                        "value": True,
                    }
                ],
                "cutoverReview": {
                    "implementationHandoff": {
                        "reviewPacketHash": "review-hash",
                        "runtimePreflightHash": "preflight-hash",
                    }
                },
            })
            _write_json(adapter_contract_validator_path(runtime), {
                "schema": "quantgod.adapter_contract_validator.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "validationPassed": False,
                "dataPlaneValidationReady": True,
                "contractExecutionModeOnlyBlocked": True,
                "validationResults": [
                    {
                        "requestId": "sandbox-review-btc-001",
                        "passed": True,
                    }
                ],
            })
            _write_json(execution_adapter_harness_path(runtime), {
                "schema": "quantgod.execution_adapter_harness.v1",
                "status": "WAITING_EXECUTION_MODE_ACTIVATION",
                "readyForDisabledAdapterImplementationReview": False,
                "dataPlaneHarnessReady": True,
                "executionModeOnlyBlocked": True,
                "plannedWrites": [
                    {
                        "requestId": "sandbox-review-btc-001",
                        "targetRequestDir": "runtime/agent/mt5_order_requests",
                        "targetReceiptDir": "runtime/agent/mt5_order_receipts",
                        "requestFilename": "sandbox-review-btc-001.json",
                        "plannedRequestPath": "runtime/agent/mt5_order_requests/sandbox-review-btc-001.json",
                        "plannedReceiptPath": "runtime/agent/mt5_order_receipts/sandbox-review-btc-001.receipt.json",
                        "atomicTempFilePattern": "sandbox-review-btc-001.json.tmp.<pid>",
                        "atomicWriteRequired": True,
                        "idempotencyKey": "sandbox-review-btc-001",
                    }
                ],
            })

            review = build_live_execution_adapter_write_review(runtime, write=True)
            plan = review["writePlans"][0]
            contract = review["disabledWriterImplementationContract"]
            writer_preflight = review["writerRuntimePreflight"]

            self.assertEqual(review["status"], "WAITING_EXECUTION_MODE_ACTIVATION")
            self.assertTrue(review["dataPlaneAdapterWriteReady"])
            self.assertTrue(review["executionModeOnlyBlocked"])
            self.assertFalse(review["readyForLiveExecutionAdapterWriteReview"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertFalse(review["writesMt5OrderRequest"])
            self.assertEqual(contract["mode"], "DISABLED_WRITER_CONTRACT_ONLY")
            self.assertFalse(contract["canWriteNow"])
            self.assertFalse(contract["requestWritesAllowed"])
            self.assertTrue(contract["releaseGate"]["tokenRequired"])
            self.assertFalse(contract["releaseGate"]["tokenProvidedInThisArtifact"])
            self.assertEqual(contract["releaseGate"]["blockerCode"], "REQUEST_WRITE_RELEASE_TOKEN_MISSING")
            self.assertEqual(contract["requestDirectories"], ["runtime/agent/mt5_order_requests"])
            self.assertEqual(contract["receiptDirectories"], ["runtime/agent/mt5_order_receipts"])
            self.assertIn("fsync and atomic rename tmp file to final request path", contract["commitAlgorithm"])
            self.assertEqual(contract["idempotencyPolicy"]["key"], "requestId")
            self.assertTrue(plan["canonicalJsonPreview"].endswith("\n"))
            self.assertTrue(plan["atomicWriteRequired"])
            self.assertTrue(plan["contractValidationPassed"])
            self.assertFalse(plan["allowedToWriteLiveRequest"])
            self.assertFalse(plan["wouldWriteToMt5RequestDirectory"])
            self.assertEqual(writer_preflight["mode"], "WRITER_RUNTIME_PREFLIGHT_ONLY_NO_FILE_WRITES")
            self.assertEqual(writer_preflight["status"], "PASS")
            self.assertTrue(writer_preflight["pathGuardPassed"])
            self.assertEqual(writer_preflight["duplicateRequestIds"], [])
            self.assertEqual(writer_preflight["duplicateFinalRequestPaths"], [])
            self.assertFalse(writer_preflight["requestFilesWritten"])
            self.assertFalse(writer_preflight["orderSendAllowed"])
            self.assertTrue(writer_preflight["releaseTokenRequired"])
            self.assertFalse(writer_preflight["releaseTokenProvided"])
            self.assertEqual(writer_preflight["releaseTokenBlockerCode"], "REQUEST_WRITE_RELEASE_TOKEN_MISSING")
            self.assertTrue(writer_preflight["rows"][0]["tempPatternAtomic"])
            self.assertTrue(writer_preflight["rows"][0]["pathGuardPassed"])
            self.assertFalse(plan["requestFilesWritten"])
            self.assertFalse(plan["receiptFilesWritten"])
            self.assertFalse(plan["brokerCallsMade"])
            self.assertTrue(live_execution_adapter_write_review_path(runtime).exists())
            self.assertFalse((runtime / "runtime" / "agent" / "mt5_order_requests").exists())
            self.assertFalse((runtime / "runtime" / "agent" / "mt5_order_receipts").exists())

    def test_writer_runtime_preflight_blocks_existing_request_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request = {
                "requestId": "sandbox-review-btc-existing",
                "schema": "quantgod.mt5_reviewed_order_request.v1",
                "createdAtIso": "1970-01-01T00:00:00Z",
                "reviewPacketHash": "review-hash",
                "runtimePreflightHash": "preflight-hash",
                "operatorApprovalId": "review-only-operator-approval",
                "lane": "HFM_CRYPTO_CFD",
                "brokerSymbol": "#BTCUSD",
                "canonicalSymbol": "BTCUSD",
                "side": "BUY",
                "orderType": "MARKET",
                "volumeLots": 0.0,
                "slPrice": None,
                "tpPrice": None,
                "maxSlippagePoints": 0.0,
                "maxSpreadPoints": 0.0,
                "maxDailyLossPct": 0.0,
                "maxDailyLossR": 0.0,
                "maxConsecutiveLosses": 0,
                "killSwitchOk": True,
                "runtimeFresh": True,
                "spreadProbeOk": True,
                "symbolMappingOk": True,
                "dryRunReplayPassed": True,
            }
            final_path = "runtime/agent/mt5_order_requests/sandbox-review-btc-existing.json"
            existing = runtime / final_path
            existing.parent.mkdir(parents=True)
            existing.write_text("already-there", encoding="utf-8")
            _write_json(adapter_sandbox_review_path(runtime), {
                "schema": "quantgod.adapter_sandbox_review_bundle.v1",
                "sampleRequests": [request],
            })
            _write_json(live_execution_implementation_spec_path(runtime), {
                "schema": "quantgod.live_execution_implementation_spec.v1",
                "status": "READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW",
                "readyForLiveExecutionImplementationSpecReview": True,
                "dataPlaneImplementationSpecReady": True,
                "implementationSteps": [{"stepId": "live_execution_adapter_write_path"}],
            })
            _write_json(adapter_contract_validator_path(runtime), {
                "schema": "quantgod.adapter_contract_validator.v1",
                "status": "READY_FOR_ADAPTER_CONTRACT_VALIDATION_REVIEW",
                "validationPassed": True,
                "dataPlaneValidationReady": True,
                "validationResults": [{"requestId": request["requestId"], "passed": True}],
            })
            _write_json(execution_adapter_harness_path(runtime), {
                "schema": "quantgod.execution_adapter_harness.v1",
                "status": "READY_FOR_DISABLED_ADAPTER_IMPLEMENTATION_HARNESS_REVIEW",
                "readyForDisabledAdapterImplementationReview": True,
                "dataPlaneHarnessReady": True,
                "plannedWrites": [{
                    "requestId": request["requestId"],
                    "targetRequestDir": "runtime/agent/mt5_order_requests",
                    "targetReceiptDir": "runtime/agent/mt5_order_receipts",
                    "requestFilename": "sandbox-review-btc-existing.json",
                    "plannedRequestPath": final_path,
                    "plannedReceiptPath": "runtime/agent/mt5_order_receipts/sandbox-review-btc-existing.receipt.json",
                    "atomicTempFilePattern": "sandbox-review-btc-existing.json.tmp.<pid>",
                    "atomicWriteRequired": True,
                    "idempotencyKey": request["requestId"],
                }],
            })

            review = build_live_execution_adapter_write_review(runtime, write=True)
            writer_preflight = review["writerRuntimePreflight"]

            self.assertEqual(review["status"], "WAITING_LIVE_EXECUTION_ADAPTER_WRITE_INPUTS")
            self.assertFalse(review["readyForLiveExecutionAdapterWriteReview"])
            self.assertFalse(review["dataPlaneAdapterWriteReady"])
            self.assertFalse(review["requestFilesWritten"])
            self.assertFalse(review["orderSendAllowed"])
            self.assertEqual(writer_preflight["status"], "BLOCKED")
            self.assertFalse(writer_preflight["pathGuardPassed"])
            self.assertTrue(writer_preflight["rows"][0]["finalRequestFileExists"])
            self.assertIn("FINAL_REQUEST_FILE_ALREADY_EXISTS", writer_preflight["rows"][0]["blockerCodes"])
            self.assertIn("LIVE_ADAPTER_WRITER_PREFLIGHT_BLOCKED", {row["code"] for row in review["blockers"]})
            self.assertEqual(existing.read_text(encoding="utf-8"), "already-there")


class LiveExecutionRequestWriterImplementationTests(unittest.TestCase):
    def _request(self, request_id: str = "sandbox-review-btc-writer-001") -> dict:
        return {
            "requestId": request_id,
            "schema": "quantgod.mt5_reviewed_order_request.v1",
            "createdAtIso": "1970-01-01T00:00:00Z",
            "reviewPacketHash": "review-hash",
            "runtimePreflightHash": "preflight-hash",
            "operatorApprovalId": "review-only-operator-approval",
            "lane": "HFM_CRYPTO_CFD",
            "brokerSymbol": "#BTCUSD",
            "canonicalSymbol": "BTCUSD",
            "side": "BUY",
            "orderType": "MARKET",
            "volumeLots": 0.01,
            "slPrice": None,
            "tpPrice": None,
            "maxSlippagePoints": 30.0,
            "maxSpreadPoints": 200.0,
            "maxDailyLossPct": 0.5,
            "maxDailyLossR": 1.0,
            "maxConsecutiveLosses": 2,
            "killSwitchOk": True,
            "runtimeFresh": True,
            "spreadProbeOk": True,
            "symbolMappingOk": True,
            "dryRunReplayPassed": True,
        }

    def _plan(self, request_id: str = "sandbox-review-btc-writer-001") -> dict:
        return {
            "finalRequestPath": f"runtime/agent/mt5_order_requests/{request_id}.json",
            "plannedReceiptPath": f"runtime/agent/mt5_order_receipts/{request_id}.receipt.json",
            "atomicWriteRequired": True,
            "idempotencyKey": request_id,
        }

    def test_request_writer_defaults_to_disabled_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request = self._request()
            plan = self._plan()

            decision = prepare_request_writer_decision(runtime, request, plan)

            self.assertFalse(decision.ok)
            self.assertEqual(decision.status, "BLOCKED")
            self.assertIn("WRITER_EXECUTION_DISABLED", decision.blocker_codes)
            self.assertIn("REQUEST_WRITE_NOT_RELEASED", decision.blocker_codes)
            self.assertIn("REQUEST_WRITE_RELEASE_TOKEN_MISSING", decision.blocker_codes)
            self.assertFalse(decision.wrote_request_file)
            self.assertFalse((runtime / plan["finalRequestPath"]).exists())

    def test_request_writer_blocks_path_traversal_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request = self._request()
            plan = self._plan()
            plan["finalRequestPath"] = "../mt5_order_requests/sandbox-review-btc-writer-001.json"

            decision = commit_request_file(
                runtime,
                request,
                plan,
                execution_enabled=True,
                allow_request_write=True,
            )

            self.assertFalse(decision.ok)
            self.assertIn("PATH_TRAVERSAL_FORBIDDEN", decision.blocker_codes)
            self.assertIn("PATH_PREFIX_MISMATCH", decision.blocker_codes)
            self.assertIn("REQUEST_WRITE_RELEASE_TOKEN_MISSING", decision.blocker_codes)
            self.assertFalse(decision.wrote_request_file)
            self.assertFalse((runtime / "../mt5_order_requests/sandbox-review-btc-writer-001.json").exists())

    def test_request_writer_requires_review_release_token_even_when_flags_are_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request = self._request()
            plan = self._plan()

            decision = commit_request_file(
                runtime,
                request,
                plan,
                execution_enabled=True,
                allow_request_write=True,
            )

            final_path = runtime / plan["finalRequestPath"]
            self.assertFalse(decision.ok)
            self.assertEqual(decision.status, "BLOCKED")
            self.assertIn("REQUEST_WRITE_RELEASE_TOKEN_MISSING", decision.blocker_codes)
            self.assertFalse(decision.wrote_request_file)
            self.assertFalse(final_path.exists())

    def test_request_writer_commits_atomically_only_with_review_release_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request = self._request()
            plan = self._plan()

            decision = commit_request_file(
                runtime,
                request,
                plan,
                execution_enabled=True,
                allow_request_write=True,
                review_release_token=REVIEWED_REQUEST_WRITE_RELEASE_TOKEN,
            )

            final_path = runtime / plan["finalRequestPath"]
            self.assertTrue(decision.ok)
            self.assertEqual(decision.status, "REQUEST_FILE_COMMITTED")
            self.assertTrue(decision.wrote_request_file)
            self.assertFalse(decision.wrote_receipt_file)
            self.assertFalse(decision.called_broker)
            self.assertTrue(final_path.exists())
            self.assertEqual(final_path.read_text(encoding="utf-8"), canonical_request_json(request))
            self.assertFalse(Path(decision.temp_request_path).exists())

    def test_request_writer_rejects_duplicate_request_id_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            request = self._request()
            plan = self._plan()
            final_path = runtime / plan["finalRequestPath"]
            final_path.parent.mkdir(parents=True)
            final_path.write_text("existing-request\n", encoding="utf-8")

            decision = commit_request_file(
                runtime,
                request,
                plan,
                execution_enabled=True,
                allow_request_write=True,
                review_release_token=REVIEWED_REQUEST_WRITE_RELEASE_TOKEN,
            )

            self.assertFalse(decision.ok)
            self.assertIn("FINAL_REQUEST_FILE_ALREADY_EXISTS", decision.blocker_codes)
            self.assertEqual(final_path.read_text(encoding="utf-8"), "existing-request\n")


if __name__ == "__main__":
    unittest.main()
