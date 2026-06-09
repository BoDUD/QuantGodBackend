import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import test from 'node:test';

const root = process.cwd();
const require = createRequire(import.meta.url);
const files = [
  'tools/run_live_automation_readiness.py',
  'tools/live_automation_readiness/adapter_sandbox.py',
  'tools/live_automation_readiness/schema.py',
  'tools/live_automation_readiness/builder.py',
  'tools/live_automation_readiness/review_packet.py',
  'tools/live_automation_readiness/approval.py',
  'tools/live_automation_readiness/execution_lane.py',
  'tools/live_automation_readiness/dry_run_replay.py',
  'tools/live_automation_readiness/preflight.py',
  'tools/live_automation_readiness/order_request_contract.py',
  'tools/live_automation_readiness/pipeline.py',
  'tools/live_automation_readiness/execution_adapter_review.py',
  'tools/live_automation_readiness/evidence_intake.py',
  'tools/live_automation_readiness/promotion_candidates.py',
  'tools/live_automation_readiness/promotion_controller.py',
  'tools/live_automation_readiness/adapter_contract_validator.py',
  'tools/live_automation_readiness/orchestrator.py',
  'tools/live_automation_readiness/execution_adapter_harness.py',
  'tools/live_automation_readiness/live_pilot_activation.py',
  'tools/live_automation_readiness/receipt_reconciliation.py',
  'tools/live_automation_readiness/ea_request_reader_review.py',
  'tools/live_automation_readiness/live_execution_cutover.py',
  'tools/live_automation_readiness/live_execution_implementation_spec.py',
  'tools/live_automation_readiness/live_execution_adapter.py',
  'tools/live_automation_readiness/live_execution_request_writer.py',
  'tools/live_automation_readiness/ea_request_consumption.py',
  'tools/live_automation_readiness/broker_order_send.py',
  'tools/live_automation_readiness/live_execution_rollback.py',
  'tools/live_automation_readiness/release_readiness_refresh.py',
  'tools/live_automation_readiness/release_minimal_diff_review.py',
  'tools/live_automation_readiness/release_token_evidence_review.py',
  'tools/live_automation_readiness/release_token_signoff_draft.py',
  'tools/live_automation_readiness/release_token_signoff_input_template.py',
  'tools/live_automation_readiness/release_token_signoff_input_review.py',
  'tools/live_automation_readiness/release_token_signoff_handoff.py',
  'tools/live_automation_readiness/lane_selector.py',
  'tools/live_automation_readiness/forex_live12_runtime_handoff.py',
  'tools/ace_execution_candidate_pack.py',
  'tools/ace_upgrade_action_plan.py',
  'Dashboard/live_automation_readiness_api_routes.js',
];

function read(rel) {
  return readFileSync(join(root, rel), 'utf8');
}

test('live automation readiness remains review-only', () => {
  const combined = files.map((file) => read(file)).join('\n');
  for (const marker of [
    'quantgod.live_automation_readiness.v1',
    'READY_FOR_EXECUTION_REVIEW',
    'executionReviewSummary',
    'REVIEW_READY_EXECUTION_DISABLED',
    'SIMULATION_READY_EXECUTION_BLOCKED',
    'liveExecutionAllowed',
    'orderSendAllowed',
    'mt5OrderSendAllowed',
    'blockerCodesByLane',
    'executionLaneSpecRequired',
    'canPromoteToLiveNow',
    'HFM_CRYPTO_EXECUTION_SPEC_REVIEW_REQUIRED',
    'HFM_CRYPTO_EXECUTION_LANE_REVIEW_REQUIRED',
    'HFM_MT5_ACCOUNT_NO_CRYPTO_CFD_SYMBOLS',
    'accountNoCryptoSymbols',
    'accountCryptoAvailability',
    'operatorChecklist',
    'readyForExecutionSpecReview',
    'MT5_EXECUTION_LANE_REVIEW_REQUIRED',
    'quantgod.live_execution_review_packet.v1',
    'dryRunOrderIntentSpec',
    'QuantGod_LiveExecutionReviewPacket.json',
    'quantgod.live_operator_approval_draft.v1',
    'quantgod.dry_run_live_execution_plan.v1',
    'QuantGod_LiveOperatorApprovalDraft.json',
    'quantgod.live_operator_approval_evidence_review.v1',
    'QuantGod_LiveOperatorApprovalEvidenceReview.json',
    'OPERATOR_APPROVAL_EVIDENCE_ACCEPTED_EXECUTION_STILL_DISABLED',
    'QuantGod_DryRunLiveExecutionPlan.json',
    'quantgod.live_execution_lane_spec.v1',
    'quantgod.execution_lane_post_target_release_audit.v1',
    'quantgod.authorization_boundary.v1',
    'QuantGod_LiveExecutionLaneSpec.json',
    'READY_FOR_EXECUTION_LANE_IMPLEMENTATION_REVIEW',
    'postTargetReleaseAudit',
    'authorizationBoundary',
    'requiredBeforeCodeCanWriteOrders',
    'quantgod.live_dry_run_intent_replay.v1',
    'QuantGod_LiveDryRunIntentReplay.json',
    'DRY_RUN_INTENT_REPLAY_ACCEPTED_EXECUTION_STILL_DISABLED',
    'quantgod.live_runtime_preflight_probe.v1',
    'QuantGod_LiveRuntimePreflightProbe.json',
    'READY_FOR_RUNTIME_PREFLIGHT_REVIEW',
    'WAITING_EXECUTION_MODE_ACTIVATION',
    'dataPlaneReadyForLivePilotReview',
    'executionModeOnlyBlocked',
    'runtimePreflightDataPlaneReadyForReview',
    'runtimePreflightExecutionModeOnlyBlocked',
    'EXECUTION_MODE_GATES_NOT_ACTIVE',
    'quantgod.mt5_order_request_contract.v1',
    'QuantGod_MT5OrderRequestContract.json',
    'READY_FOR_ORDER_REQUEST_CONTRACT_REVIEW',
    'requestWritesAllowed',
    'quantgod.sim_to_live_automation_pipeline.v1',
    'QuantGod_SimToLiveAutomationPipeline.json',
    'READY_FOR_SEPARATE_EXECUTION_ADAPTER_REVIEW',
    'quantgod.execution_adapter_review.v1',
    'QuantGod_ExecutionAdapterReview.json',
    'READY_FOR_EXECUTION_ADAPTER_CODE_REVIEW',
    'adapterExecutionAllowed',
    'requestFilesWritten',
    'brokerCallsMade',
    'quantgod.live_evidence_intake.v1',
    'QuantGod_LiveEvidenceIntake.json',
    'WAITING_HFM_LIVE_EVIDENCE_INPUTS',
    'HFM_REVIEW_INPUTS_PRESENT',
    'evidence-intake',
    'post_upgrade_controller',
    'post-upgrade-controller',
    'filled-input-validator',
    'filledInputValidator',
    'readyForEvidenceIntakeRefresh',
    'externalMarketRemoved',
    'quantgod.live_promotion_candidates.v1',
    'QuantGod_LivePromotionCandidates.json',
    'READY_FOR_OPERATOR_REVIEW_PACKET',
    'WAITING_LIVE_PROMOTION_CANDIDATES',
    'promotion-candidates',
    'quantgod.live_promotion_controller.v1',
    'QuantGod_LivePromotionController.json',
    'OPERATOR_REVIEW_PACKET_AUTOMATED',
    'WAITING_PROMOTION_CANDIDATE',
    'promotion-controller',
    'SIM_TO_LIVE_REVIEW_AUTOMATION_ONLY',
    'quantgod.adapter_sandbox_review_bundle.v1',
    'QuantGod_AdapterSandboxReviewBundle.json',
    'READY_FOR_ADAPTER_SANDBOX_REVIEW',
    'WAITING_ADAPTER_SANDBOX_INPUTS',
    'adapter-sandbox',
    'SANDBOX_REVIEW_ONLY',
    'quantgod.adapter_contract_validator.v1',
    'QuantGod_AdapterContractValidator.json',
    'READY_FOR_ADAPTER_CONTRACT_VALIDATION_REVIEW',
    'WAITING_ADAPTER_CONTRACT_VALIDATION_INPUTS',
    'adapter-contract-validator',
    'REVIEW_ONLY_CONTRACT_VALIDATION',
    'quantgod.sim_to_live_orchestrator.v1',
    'QuantGod_SimToLiveOrchestrator.json',
    'WAITING_SIM_TO_LIVE_ORCHESTRATOR_INPUTS',
    'READY_FOR_EXECUTION_ADAPTER_IMPLEMENTATION_REVIEW',
    'READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_REVIEW',
    'readyForLiveExecutionImplementationReview',
    'liveExecutionStages',
    'currentLiveExecutionStage',
    'LIVE_EXECUTION_REVIEW_STAGE_BLOCKED',
    'orchestrator',
    'SIM_TO_LIVE_REVIEW_AUTOMATION_ONLY',
    'quantgod.execution_adapter_harness.v1',
    'QuantGod_ExecutionAdapterHarness.json',
    'READY_FOR_DISABLED_ADAPTER_IMPLEMENTATION_HARNESS_REVIEW',
    'WAITING_EXECUTION_ADAPTER_HARNESS_INPUTS',
    'adapter-harness',
    'DISABLED_REVIEW_ONLY_NO_SIDE_EFFECTS',
    'quantgod.live_pilot_activation_review.v1',
    'QuantGod_LivePilotActivationReview.json',
    'READY_FOR_LIVE_PILOT_ACTIVATION_REVIEW',
    'WAITING_LIVE_PILOT_ACTIVATION_INPUTS',
    'live-pilot-activation-review',
    'LIVE_PILOT_ACTIVATION_REVIEW_ONLY_NO_EXECUTION',
    'quantgod.receipt_reconciliation_review.v1',
    'QuantGod_ReceiptReconciliationReview.json',
    'READY_FOR_RECEIPT_RECONCILIATION_REVIEW',
    'WAITING_RECEIPT_RECONCILIATION_INPUTS',
    'receipt-reconciliation-review',
    'RECEIPT_RECONCILIATION_REVIEW_ONLY_NO_SIDE_EFFECTS',
    'quantgod.ea_request_reader_review.v1',
    'QuantGod_EARequestReaderReview.json',
    'READY_FOR_EA_REQUEST_READER_IMPLEMENTATION_REVIEW',
    'WAITING_EA_REQUEST_READER_INPUTS',
    'ea-request-reader-review',
    '--ea-status-json',
    'EA_REQUEST_READER_REVIEW_ONLY_NO_SIDE_EFFECTS',
    'EA_REQUEST_READER_RUNTIME_STATUS_MISSING',
    'runtimeStatusSafetyChecks',
    'quantgod.mql5.ea_request_reader_review_status.v1',
    'QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT',
    'quantgod.live_execution_cutover_review.v1',
    'QuantGod_LiveExecutionCutoverReview.json',
    'READY_FOR_SEPARATE_LIVE_EXECUTION_CUTOVER_IMPLEMENTATION_REVIEW',
    'WAITING_LIVE_EXECUTION_CUTOVER_INPUTS',
    'live-execution-cutover-review',
    'LIVE_EXECUTION_CUTOVER_REVIEW_ONLY_NO_SIDE_EFFECTS',
    'readyForSeparateLiveExecutionCutoverImplementationReview',
    'quantgod.live_execution_implementation_spec.v1',
    'QuantGod_LiveExecutionImplementationSpec.json',
    'READY_FOR_LIVE_EXECUTION_IMPLEMENTATION_SPEC_REVIEW',
    'WAITING_LIVE_EXECUTION_IMPLEMENTATION_SPEC_INPUTS',
    'live-execution-implementation-spec',
    'IMPLEMENTATION_SPEC_REVIEW_ONLY_NO_EXECUTION',
    'readyForLiveExecutionImplementationSpecReview',
    'microLiveExecutionBlueprint',
    'MICRO_LIVE_EXECUTION_IMPLEMENTATION_BLUEPRINT_REVIEW_ONLY',
    'READY_TO_IMPLEMENT_DISABLED_FIRST',
    'mql5_broker_order_send_wrapper',
    'live_execution_adapter_write_path',
    'quantgod.live_execution_adapter_write_review.v1',
    'QuantGod_LiveExecutionAdapterWriteReview.json',
    'READY_FOR_LIVE_EXECUTION_ADAPTER_WRITE_REVIEW',
    'WAITING_LIVE_EXECUTION_ADAPTER_WRITE_INPUTS',
    'live-execution-adapter-write-review',
    'ADAPTER_WRITE_REVIEW_ONLY_NO_MT5_REQUEST_FILES',
    'readyForLiveExecutionAdapterWriteReview',
    'canonicalJsonPreview',
    'writerRuntimePreflight',
    'WRITER_RUNTIME_PREFLIGHT_ONLY_NO_FILE_WRITES',
    'REQUEST_FILE_COMMITTED',
    'WRITER_EXECUTION_DISABLED',
    'REQUEST_WRITE_NOT_RELEASED',
    'REQUEST_WRITE_RELEASE_TOKEN_MISSING',
    'releaseTokenRequired',
    'FINAL_REQUEST_FILE_ALREADY_EXISTS',
    'quantgod.ea_request_consumption_review.v1',
    'QuantGod_EARequestConsumptionReview.json',
    'READY_FOR_EA_REQUEST_CONSUMPTION_REVIEW',
    'WAITING_EA_REQUEST_CONSUMPTION_INPUTS',
    'ea-request-consumption-review',
    'EA_REQUEST_CONSUMPTION_REVIEW_ONLY_NO_FILE_READS',
    'readyForEaRequestConsumptionReview',
    'wouldReadRequestFile',
    'REQUEST_READER_RELEASE_TOKEN_MISSING',
    'rejectionReceiptPlan',
    'REJECTION_RECEIPT_PLAN_REVIEW_ONLY_NO_FILE_WRITES',
    'DUPLICATE_REQUEST_ID',
    'EXPIRED_OR_STALE_REQUEST',
    'RECEIPT_WRITER_RELEASE_TOKEN_MISSING',
    'quantgod.broker_order_send_review.v1',
    'QuantGod_BrokerOrderSendReview.json',
    'READY_FOR_BROKER_ORDER_SEND_REVIEW',
    'WAITING_BROKER_ORDER_SEND_INPUTS',
    'broker-order-send-review',
    'BROKER_ORDER_SEND_REVIEW_ONLY_NO_BROKER_CALLS',
    'readyForBrokerOrderSendReview',
    'wouldCallBroker',
    'BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING',
    'brokerReleaseGate',
    'broker_order_send_path',
    'mt5PendingOrderIntentsWritten',
    'quantgod.live_execution_rollback_review.v1',
    'QuantGod_LiveExecutionRollbackReview.json',
    'READY_FOR_LIVE_EXECUTION_ROLLBACK_REVIEW',
    'WAITING_LIVE_EXECUTION_ROLLBACK_INPUTS',
    'live-execution-rollback-review',
    'LIVE_EXECUTION_ROLLBACK_REVIEW_ONLY_NO_MUTATION',
    'readyForLiveExecutionRollbackReview',
    'rollback_and_auto_disable_path',
    'rollbackMatrix',
    'ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING',
    'quantgod.release_unblock_plan.v1',
    'TARGET_REACHED_REVIEW_ONLY_UNBLOCK_PLAN',
    'releaseUnblockPlan',
    'reviewOnlyProposedFileChanges',
    'quantgod.release_minimal_diff_review.v1',
    'quantgod.release_minimal_diff_package.v1',
    'REVIEW_ONLY_MINIMAL_DIFF_NO_FILE_WRITE',
    'release-minimal-diff-review',
    'QuantGod_ReleaseMinimalDiffReview.json',
    'quantgod.release_token_evidence_review.v1',
    'QuantGod_ReleaseTokenEvidenceReview.json',
    'release-token-evidence-review',
    'WAITING_RELEASE_TOKEN_EVIDENCE_AND_SEPARATE_REVIEW',
    'releaseTokenCanBeAutoMinted',
    'quantgod.release_token_signoff_draft.v1',
    'QuantGod_ReleaseTokenSignoffDraft.json',
    'release-token-signoff-draft',
    'READY_FOR_SEPARATE_SIGNOFF_INPUT',
    'cannotBeUsedAsReleaseToken',
    'quantgod.release_token_signoff_input_template.v1',
    'QuantGod_ReleaseTokenSignoffInputTemplate.json',
    'release-token-signoff-input-template',
    'READY_FOR_SIGNOFF_INPUT_FILL',
    'signoffInputTemplate',
    'quantgod.release_token_signoff_input_review.v1',
    'QuantGod_ReleaseTokenSignoffInputReview.json',
    'release-token-signoff-input-review',
    'SIGNOFF_INPUT_READY_FOR_SEPARATE_RELEASE_REVIEW',
    'forbiddenSecretFieldPaths',
    'readJsonBody',
    'BODY_TOO_LARGE',
    'BODY_MUST_BE_JSON_OBJECT',
    'quantgod.release_token_signoff_handoff.v1',
    'QuantGod_ReleaseTokenSignoffHandoff.json',
    'release-token-signoff-handoff',
    'WAITING_SIGNOFF_INPUT_HANDOFF',
    'SIGNOFF_HANDOFF_READY_FOR_SEPARATE_RELEASE_LANE',
    'quantgod.live_execution_lane_selector.v1',
    'QuantGod_LiveExecutionLaneSelector.json',
    'lane-selector',
    'LANE_SELECTOR_REVIEW_ONLY',
    'quantgod.ace_execution_candidate_pack.v1',
    'QuantGod_AceExecutionCandidatePack.json',
    'ACE_EXECUTION_CANDIDATE_PACK_READY',
    'ace-execution-candidate-pack',
    'btcDefaultPolicy',
    'quantgod.ace_upgrade_action_plan.v1',
    'QuantGod_AceUpgradeActionPlan.json',
    'ace-upgrade-action-plan',
    'ACE_UPGRADE_WAITING_TESTER_ENVIRONMENT',
    'processEvidence',
    'processBlockers',
    'mt5_terminal_process_missing',
    'restore_live_mt5_dashboard_refresh',
    'run_forex_ab_tester_forward',
    'resolveAceResearchRuntimeScope',
    'aceResearchRuntimeScope',
    'aceEvidenceFallbackAvailable',
    'research-fallback',
    'ACE_RESEARCH_ARTIFACTS_MISSING_IN_ACCOUNT_RUNTIME',
    'quantgod.forex_live12_runtime_handoff.v1',
    'QuantGod_ForexLive12RuntimeHandoff.json',
    'forex-live12-runtime-handoff',
    'FOREX_LIVE12_ACTIVE_PORTFOLIO_FULL',
    'FOREX_LIVE12_RUNTIME_REFRESH_BLOCKED',
    'runtimeFreshness',
    'runtimeFresh',
    'runtimeFreshnessBlockers',
    'live12RuntimeHandoffReadable',
    'live12RuntimeHandoffFresh',
    'live12RuntimeHandoffStatus',
    'LIVE12_RUNTIME_REFRESH_BLOCKED',
    'LIVE12_DASHBOARD_AND_PROCESS_WATCH',
  ]) {
    assert.match(combined, new RegExp(marker));
  }
  assert.doesNotMatch(
    combined,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|\bCTrade\b/,
  );
  assert.doesNotMatch(combined, /orderSendAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /mt5OrderSendAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /hfmCryptoExecutionAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /copyTradeExecutionAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /walletAuthorizationAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /livePresetMutationAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /livePilotActivationAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /receiptWritesAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /receiptFilesWritten["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /autoDisableMutationAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /eaRequestReaderAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /eaRequestReaderEnabled["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /eaRequestFilesRead["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /eaRequestFilesConsumed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /eaOrderSendAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /mt5PendingOrderIntentsWritten["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /brokerExecutionAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /requestWritesAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /adapterExecutionAllowed["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /requestFilesWritten["']?\s*[:=]\s*True/);
  assert.doesNotMatch(combined, /brokerCallsMade["']?\s*[:=]\s*True/);
});

test('dashboard exposes live automation readiness namespace', () => {
  const server = read('Dashboard/dashboard_server.js');
  const routes = read('Dashboard/live_automation_readiness_api_routes.js');
  for (const marker of [
    "require('./live_automation_readiness_api_routes')",
    'latestDashboardFreshness',
    'LATEST_DASHBOARD_MTIME_WATCH',
    'STALE_DASHBOARD_SNAPSHOT',
    'live_dashboard_snapshot_stale',
    'isLiveAutomationReadinessPath',
    '/api/live-automation/status',
    '/api/live-automation/readiness',
    '/api/live-automation/build',
    '/api/live-automation/review-packet',
    '/api/live-automation/review-packet/build',
    '/api/live-automation/approval-draft',
    '/api/live-automation/approval-draft/build',
    '/api/live-automation/approval-evidence',
    '/api/live-automation/approval-evidence/build',
    '/api/live-automation/dry-run-plan',
    '/api/live-automation/dry-run-plan/build',
    '/api/live-automation/execution-lane-spec',
    '/api/live-automation/execution-lane-spec/build',
    '/api/live-automation/dry-run-replay',
    '/api/live-automation/dry-run-replay/build',
    '/api/live-automation/runtime-preflight',
    '/api/live-automation/runtime-preflight/build',
    '/api/live-automation/order-request-contract',
    '/api/live-automation/order-request-contract/build',
    '/api/live-automation/pipeline',
    '/api/live-automation/pipeline/build',
    '/api/live-automation/adapter-review',
    '/api/live-automation/adapter-review/build',
    '/api/live-automation/evidence-intake',
    '/api/live-automation/evidence-intake/build',
    '/api/live-automation/promotion-candidates',
    '/api/live-automation/promotion-candidates/build',
    '/api/live-automation/promotion-controller',
    '/api/live-automation/promotion-controller/build',
    '/api/live-automation/adapter-sandbox',
    '/api/live-automation/adapter-sandbox/build',
    '/api/live-automation/adapter-contract-validator',
    '/api/live-automation/adapter-contract-validator/build',
    '/api/live-automation/orchestrator',
    '/api/live-automation/orchestrator/build',
    '/api/live-automation/adapter-harness',
    '/api/live-automation/adapter-harness/build',
    '/api/live-automation/live-pilot-activation-review',
    '/api/live-automation/live-pilot-activation-review/build',
    '/api/live-automation/receipt-reconciliation-review',
    '/api/live-automation/receipt-reconciliation-review/build',
    '/api/live-automation/ea-request-reader-review',
    '/api/live-automation/ea-request-reader-review/build',
    '/api/live-automation/live-execution-cutover-review',
    '/api/live-automation/live-execution-cutover-review/build',
    '/api/live-automation/live-execution-implementation-spec',
    '/api/live-automation/live-execution-implementation-spec/build',
    '/api/live-automation/live-execution-adapter-write-review',
    '/api/live-automation/live-execution-adapter-write-review/build',
    '/api/live-automation/ea-request-consumption-review',
    '/api/live-automation/ea-request-consumption-review/build',
    '/api/live-automation/broker-order-send-review',
    '/api/live-automation/broker-order-send-review/build',
    '/api/live-automation/live-execution-rollback-review',
    '/api/live-automation/live-execution-rollback-review/build',
    '/api/live-automation/release-minimal-diff-review',
    '/api/live-automation/release-minimal-diff-review/build',
    '/api/live-automation/release-token-evidence-review',
    '/api/live-automation/release-token-evidence-review/build',
    '/api/live-automation/release-token-signoff-draft',
    '/api/live-automation/release-token-signoff-draft/build',
    '/api/live-automation/release-token-signoff-input-review',
    '/api/live-automation/release-token-signoff-input-review/build',
    '/api/live-automation/release-token-signoff-handoff',
    '/api/live-automation/release-token-signoff-handoff/build',
    'requestBody.signoffJson',
    "requestBody.schema === 'quantgod.release_token_signoff_input.v1'",
    '/api/live-automation/lane-selector',
    '/api/live-automation/lane-selector/build',
    '/api/live-automation/ace-execution-candidate-pack',
    '/api/live-automation/ace-execution-candidate-pack/build',
    '/api/live-automation/ace-upgrade-action-plan',
    '/api/live-automation/ace-upgrade-action-plan/build',
    '/api/live-automation/forex-live12-runtime-handoff',
    '/api/live-automation/forex-live12-runtime-handoff/build',
    'run_live_automation_readiness.py',
  ]) {
    assert.match(`${server}\n${routes}`, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(
    routes,
    /\['--runtime-dir', runtimeDir, 'lane-selector'\]/,
    'GET lane-selector should refresh read-only current lane state instead of returning stale status only',
  );
});

test('Live Automation API exposes explicit runtime scope metadata', () => {
  const {
    resolveLiveAutomationRuntimeScope,
    runtimeScopeMeta,
  } = require(join(root, 'Dashboard/live_automation_readiness_api_routes.js'));
  const defaultScope = resolveLiveAutomationRuntimeScope(
    { defaultRuntimeDir: '/tmp/qg-primary', secondaryRuntimeDir: root },
    new URL('/api/live-automation/status', 'http://127.0.0.1'),
  );
  const secondary = resolveLiveAutomationRuntimeScope(
    { defaultRuntimeDir: '/tmp/qg-primary', secondaryRuntimeDir: root },
    new URL('/api/live-automation/status?scope=live16', 'http://127.0.0.1'),
  );

  assert.equal(defaultScope.scope, 'primary');
  assert.equal(defaultScope.accountLabel, 'HFM primary MT5');
  assert.equal(defaultScope.runtimeDir, '/tmp/qg-primary');
  assert.deepEqual(runtimeScopeMeta(secondary), {
    scope: 'secondary',
    requestedScope: 'live16',
    accountLabel: 'HFM Live16 crypto CFD',
    runtimeDir: root,
  });
});

test('Live Automation API falls back to repo research runtime for ace evidence', () => {
  const {
    resolveAceResearchRuntimeScope,
    runtimeScopeMeta,
  } = require(join(root, 'Dashboard/live_automation_readiness_api_routes.js'));
  const accountRuntime = mkdtempSync(join(tmpdir(), 'qg-live-account-runtime-'));
  const researchRuntime = mkdtempSync(join(tmpdir(), 'qg-live-research-runtime-'));
  mkdirSync(join(researchRuntime, 'agent'), { recursive: true });
  writeFileSync(
    join(researchRuntime, 'agent', 'QuantGod_AceExecutionCandidatePack.json'),
    JSON.stringify({ ok: true, schema: 'quantgod.ace_execution_candidate_pack.v1' }),
  );

  const resolved = resolveAceResearchRuntimeScope(
    { researchRuntimeDir: researchRuntime },
    {
      scope: 'primary',
      requestedScope: 'primary',
      accountLabel: 'HFM primary MT5',
      runtimeDir: accountRuntime,
    },
  );

  assert.equal(resolved.scope, 'research-fallback');
  assert.equal(resolved.runtimeDir, researchRuntime);
  assert.equal(resolved.accountRuntimeDir, accountRuntime);
  assert.deepEqual(runtimeScopeMeta(resolved), {
    scope: 'research-fallback',
    requestedScope: 'primary',
    accountLabel: 'HFM primary MT5 + QuantGod research runtime',
    runtimeDir: researchRuntime,
    accountRuntimeDir: accountRuntime,
    fallbackReason: 'ACE_RESEARCH_ARTIFACTS_MISSING_IN_ACCOUNT_RUNTIME',
  });
});

function jsonRequest({ method = 'POST', url = '/', body = {} } = {}) {
  const req = Readable.from([JSON.stringify(body)]);
  req.method = method;
  req.url = url;
  return req;
}

function jsonResponse() {
  const res = {
    statusCode: 0,
    body: '',
    headers: {},
    writeHead(statusCode, headers) {
      this.statusCode = statusCode;
      this.headers = headers || {};
    },
    end(body) {
      this.body = String(body || '');
    },
  };
  return res;
}

test('signoff input review POST body validates without releasing execution', async () => {
  const { handle } = require(join(root, 'Dashboard/live_automation_readiness_api_routes.js'));
  const runtime = mkdtempSync(join(tmpdir(), 'qg-live-signoff-route-'));
  const agentDir = join(runtime, 'agent');
  mkdirSync(agentDir, { recursive: true });
  writeFileSync(
    join(agentDir, 'QuantGod_ReleaseTokenSignoffDraft.json'),
    JSON.stringify({
      ok: true,
      schema: 'quantgod.release_token_signoff_draft.v1',
      status: 'READY_FOR_SEPARATE_SIGNOFF_INPUT',
      releaseTokenCount: 1,
      readyForSeparateSignoffCount: 1,
      signoffDraftTemplate: {
        schema: 'quantgod.release_token_signoff_input.v1',
        operatorId: '',
        reviewedAtIso: '',
        releaseTokenSignoffs: [
          {
            gateId: 'broker_order_send_release',
            labelZh: 'Broker OrderSend',
            tokenName: 'QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1',
            blockerCode: 'BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING',
            sideEffectZh: '调用 MT5 OrderSend',
            readyForSeparateSignoffReview: true,
            canSignOffHere: false,
            canMintTokenHere: false,
            canReleaseExecutionNow: false,
            orderSendAllowed: false,
            mt5OrderSendAllowed: false,
          },
        ],
      },
      orderSendAllowed: false,
      mt5OrderSendAllowed: false,
      writesMt5OrderRequest: false,
      brokerCallsMade: false,
    }),
  );
  const req = jsonRequest({
    url: '/api/live-automation/release-token-signoff-input-review/build',
    body: {
      schema: 'quantgod.release_token_signoff_input.v1',
      operatorId: 'route-test-review-only',
      reviewedAtIso: '2026-06-03T00:00:00Z',
      releaseTokenSignoffs: [
        {
          gateId: 'broker_order_send_release',
          acknowledgeNoSideEffectEvidence: true,
          acknowledgeKillSwitch: true,
          acknowledgeRollback: true,
          acknowledgeRiskLimits: true,
          acknowledgeExecutionModeSeparatelyReviewed: true,
          finalSignoffText:
            'QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1 BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING route body review only',
        },
      ],
    },
  });
  const res = jsonResponse();

  await handle(req, res, { repoRoot: root, defaultRuntimeDir: runtime });
  const payload = JSON.parse(res.body);
  assert.equal(res.statusCode, 200);
  assert.equal(payload.status, 'SIGNOFF_INPUT_READY_FOR_SEPARATE_RELEASE_REVIEW');
  assert.equal(payload.signoffInputSource, 'inline_json');
  assert.equal(payload.completeSignoffCount, 1);
  assert.equal(payload.releaseTokenCount, 1);
  assert.equal(payload.orderSendAllowed, false);
  assert.equal(payload.mt5OrderSendAllowed, false);
  assert.equal(payload.writesMt5OrderRequest, false);
  assert.equal(payload.brokerCallsMade, false);
});

test('signoff input review rejects non-object POST body', async () => {
  const { handle } = require(join(root, 'Dashboard/live_automation_readiness_api_routes.js'));
  const runtime = mkdtempSync(join(tmpdir(), 'qg-live-signoff-route-invalid-'));
  const req = Readable.from(['[]']);
  req.method = 'POST';
  req.url = '/api/live-automation/release-token-signoff-input-review/build';
  const res = jsonResponse();

  await handle(req, res, { repoRoot: root, defaultRuntimeDir: runtime });
  const payload = JSON.parse(res.body);
  assert.equal(res.statusCode, 400);
  assert.equal(payload.status, 'BODY_MUST_BE_JSON_OBJECT');
  assert.match(payload.statusZh, /JSON object/);
});
