import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import test from 'node:test';

const root = process.cwd();
const require = createRequire(import.meta.url);
const files = [
  'tools/run_hfm_crypto_cfd.py',
  'tools/hfm_crypto_cfd/schema.py',
  'tools/hfm_crypto_cfd/builder.py',
  'tools/hfm_crypto_cfd/contract_spec_export.py',
  'tools/hfm_crypto_cfd/execution_spec.py',
  'tools/hfm_crypto_cfd/evidence_kit.py',
  'tools/hfm_crypto_cfd/evidence_bootstrap.py',
  'tools/hfm_crypto_cfd/simulation_profile.py',
  'tools/hfm_crypto_cfd/mt5_exporter_review.py',
  'tools/hfm_crypto_cfd/mt5_upgrade_bundle.py',
  'tools/hfm_crypto_cfd/mt5_exporter_deploy_plan.py',
  'tools/hfm_crypto_cfd/standalone_exporter_bundle.py',
  'tools/hfm_crypto_cfd/mt5_post_upgrade_verify.py',
  'tools/hfm_crypto_cfd/post_upgrade_controller.py',
  'tools/hfm_crypto_cfd/filled_input_validator.py',
  'Dashboard/hfm_crypto_cfd_api_routes.js',
];

function read(rel) {
  return readFileSync(join(root, rel), 'utf8');
}

test('HFM Crypto CFD lane remains shadow-only', () => {
  const combined = files.map((file) => read(file)).join('\n');
  for (const marker of [
    'quantgod.hfm_crypto_cfd.state.v1',
    'quantgod.hfm_crypto_cfd.contract_spec_export.v1',
    'quantgod.hfm_crypto_cfd.execution_spec_review.v1',
    'quantgod.hfm_crypto_cfd.evidence_kit.v1',
    'quantgod.hfm_crypto_cfd.simulation_profile_review.v1',
    'quantgod.hfm_crypto_cfd.mt5_exporter_review.v1',
    'quantgod.hfm_crypto_cfd.mt5_exporter_upgrade_bundle.v1',
    'quantgod.hfm_crypto_cfd.mt5_exporter_deploy_plan.v1',
    'quantgod.hfm_crypto_cfd.standalone_exporter_bundle.v1',
    'quantgod.hfm_crypto_cfd.mt5_post_upgrade_verify.v1',
    'quantgod.hfm_crypto_cfd.post_upgrade_controller.v1',
    'quantgod.hfm_crypto_cfd.filled_input_validator.v1',
    'quantgod.hfm_crypto_cfd.evidence_bootstrap.v1',
    'QuantGod_HFMCryptoContractSpecExport.json',
    'QuantGod_HFMCryptoExecutionSpecReview.json',
    'QuantGod_HFMCryptoEvidenceKit.json',
    'QuantGod_HFMCryptoMt5ExporterReview.json',
    'QuantGod_HFMCryptoMt5ExporterUpgradeBundle.json',
    'QuantGod_HFMCryptoMt5ExporterDeployPlan.json',
    'QuantGod_HFMCryptoStandaloneExporterBundle.json',
    'QuantGod_HFMCryptoMt5PostUpgradeVerify.json',
    'QuantGod_HFMCryptoPostUpgradeController.json',
    'QuantGod_HFMCryptoFilledInputValidator.json',
    'QuantGod_HFMCryptoEvidenceBootstrap.json',
    'mt5_ea_upgrade_bundle',
    'standalone_exporter_bundle',
    'QuantGod_HFMCryptoSpecExporter.mq5',
    'QuantGod_HFMCryptoSpecExporterEA.mq5',
    'QuantGod_HFMCryptoSpecExporter_startup.ini',
    'QuantGod_HFMCryptoContractSpecTemplate.json',
    'QuantGod_HFMCryptoSymbolSpecs.json',
    'QuantGod_HFMCryptoRuntimeProbe.json',
    'QuantGod_Dashboard.json',
    'QuantGod_HFMCryptoSimulationProfileReview.json',
    'EA_SYMBOL_SPECS_JSON',
    'EA_DASHBOARD_HFM_CRYPTO_SYMBOL_SPECS',
    'autoDiscoveredEaExport',
    'autoDiscoveredEaDashboardExport',
    'hfmCryptoSymbolSpecs',
    'WAITING_MT5_EA_EXPORTER_UPGRADE',
    'HFM_CRYPTO_MT5_EXPORT_AVAILABLE',
    'READY_FOR_MANUAL_MT5_EA_UPGRADE',
    'READY_FOR_OPERATOR_MT5_EA_DEPLOY_REVIEW',
    'WAITING_OPERATOR_MT5_EA_DEPLOY_REVIEW_INPUTS',
    'READY_FOR_MANUAL_STANDALONE_MT5_SPEC_EXPORT',
    'READY_TO_RUN_STANDALONE_MT5_SPEC_EXPORT',
    'STANDALONE_MT5_SPEC_EXPORT_OUTPUT_DETECTED',
    'WAITING_STANDALONE_MT5_SPEC_EXPORTER_INPUTS',
    'WAITING_MANUAL_MT5_EA_UPGRADE',
    'WAITING_HFM_CRYPTO_SPECS_AFTER_UPGRADE',
    'HFM_CRYPTO_MT5_POST_UPGRADE_VERIFIED',
    'HFM_CRYPTO_POST_UPGRADE_REVIEW_AUTOMATED',
    'FILLED_HFM_INPUTS_READY_FOR_REVIEW_CHAIN',
    'WAITING_FILLED_HFM_INPUTS',
    'WAITING_HFM_EVIDENCE_BOOTSTRAP_INPUTS',
    'HFM_EVIDENCE_BOOTSTRAP_READY_FOR_REVIEW_REFRESH',
    'READY_FOR_HFM_CONTRACT_SPEC_REVIEW',
    'copyIntoMt5Allowed',
    'compileAttempted',
    'deployCommandExecuted',
    'rollbackCommandExecuted',
    'scriptRunAttempted',
    'startupConfig',
    'postRunRefreshPlan',
    'run_live_automation_readiness.py',
    'refreshCommands',
    'AllowLiveTrading=0',
    'Expert=QuantGod_HFMCryptoSpecExporterEA',
    'ShutdownTerminal=1',
    'targetInstalledAndCompiled',
    'targetExpertInstalledAndCompiled',
    'targetCompiledExists',
    'targetExpertCompiledExists',
    'expectedSpecsRowCount',
    'HFM_CRYPTO_STANDALONE_EXPORTER_READY_TO_RUN',
    'HFM_CRYPTO_STANDALONE_EXPORTER_READY_FOR_INSTALL',
    'postUpgradeVerified',
    'postUpgradeReviewAutomated',
    'installedFilesMutated',
    'HFM_CRYPTO_CFD_SHADOW_ONLY',
    'WAITING_HFM_CRYPTO_SYMBOLS',
    'READY_FOR_SHADOW_RESEARCH',
    'READY_FOR_CONTRACT_SPEC_REVIEW_INPUT',
    'READY_FOR_EXECUTION_CONTRACT_REVIEW',
    'priceDiffProtectionPct',
    'mossBacktestProfile',
    'readyForExecutionSpecReview',
    'SIMULATION_PROFILE_QUALIFIED',
    'autoProfileCandidates',
    'auto_discovered_simulation_profile',
    'filledInputsValid',
    'reviewInputsValid',
    'contract_spec_export',
    'simulation_profile_review_artifact',
    'hfm_crypto_contract_specs.filled.json',
    'hfm_crypto_simulation_profile.filled.json',
    'hfm_crypto_contract_specs.draft.json',
    'hfm_crypto_simulation_profile.draft.json',
    'operator_approval.draft.json',
    'READY_FOR_OPERATOR_EXPORT',
    'externalMarketRemoved',
  ]) {
    assert.match(combined, new RegExp(marker));
  }
  assert.doesNotMatch(
    combined,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|\bCTrade\b/,
  );
  assert.doesNotMatch(combined, /walletAuthorizationAllowed["']?\s*:\s*True/);
  assert.doesNotMatch(combined, /copyTradeExecutionAllowed["']?\s*:\s*True/);
  assert.doesNotMatch(combined, /mossExecutionAllowed["']?\s*:\s*True/);
});

test('MQL5 HFM crypto symbol-spec exporter is read-only', () => {
  const source = read('MQL5/Experts/QuantGod_MultiStrategy.mq5');
  const begin = '// HFM Crypto Symbol Spec Export BEGIN';
  const end = '// HFM Crypto Symbol Spec Export END';
  assert.match(source, new RegExp(begin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(source, new RegExp(end.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const block = source.split(begin, 2)[1].split(end, 1)[0];
  for (const marker of [
    'BuildHfmCryptoSymbolSpecsJson',
    'BuildHfmCryptoRuntimeProbeJson',
    'QuantGod_HFMCryptoSymbolSpecs.json',
    'QuantGod_HFMCryptoRuntimeProbe.json',
    'quantgod.mql5.hfm_crypto_symbol_specs.v1',
    'quantgod.mql5.hfm_crypto_runtime_probe.v1',
    'MQL5_SYMBOLINFO_READONLY',
    'MQL5_SYMBOLINFO_READONLY_MULTISTRATEGY_RUNTIME_PROBE',
    'SymbolInfoDouble',
    'SymbolInfoInteger',
    'SymbolInfoString',
    'SymbolInfoTick',
  ]) {
    assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    block,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|\bCTrade\b|SymbolSelect\s*\(/,
  );
});

test('MQL5 standalone HFM crypto spec exporter is read-only', () => {
  const source = read('MQL5/Scripts/QuantGod_HFMCryptoSpecExporter.mq5');
  const begin = '// Standalone HFM Crypto Spec Exporter BEGIN';
  const end = '// Standalone HFM Crypto Spec Exporter END';
  assert.match(source, new RegExp(begin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(source, new RegExp(end.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const block = source.split(begin, 2)[1].split(end, 1)[0];
  for (const marker of [
    'BuildStandaloneHfmCryptoSymbolSpecsJson',
    'QuantGod_HFMCryptoSymbolSpecs.json',
    'quantgod.mql5.hfm_crypto_symbol_specs.v1',
    'MQL5_SYMBOLINFO_READONLY_STANDALONE',
    'SymbolInfoDouble',
    'SymbolInfoInteger',
    'SymbolInfoString',
    'SymbolInfoTick',
  ]) {
    assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    block,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|\bCTrade\b|SymbolSelect\s*\(|FileRead/,
  );

  const expertSource = read('MQL5/Experts/QuantGod_HFMCryptoSpecExporterEA.mq5');
  const expertBegin = '// Standalone HFM Crypto Spec Exporter EA BEGIN';
  const expertEnd = '// Standalone HFM Crypto Spec Exporter EA END';
  assert.match(expertSource, new RegExp(expertBegin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(expertSource, new RegExp(expertEnd.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const expertBlock = expertSource.split(expertBegin, 2)[1].split(expertEnd, 1)[0];
  for (const marker of [
    'BuildStandaloneHfmCryptoSymbolSpecsJson',
    'QuantGod_HFMCryptoSymbolSpecs.json',
    'quantgod.mql5.hfm_crypto_symbol_specs.v1',
    'QuantGod_HFMCryptoRuntimeProbe.json',
    'quantgod.mql5.hfm_crypto_runtime_probe.v1',
    'MQL5_SYMBOLINFO_READONLY_STANDALONE_EA',
    'MQL5_SYMBOLINFO_READONLY_STANDALONE_EA_RUNTIME_PROBE',
    'SymbolInfoDouble',
    'SymbolInfoInteger',
    'SymbolInfoString',
    'SymbolInfoTick',
    'RuntimeProbeWarmupSeconds',
    'ExpertRemove',
  ]) {
    assert.match(expertSource, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    expertBlock,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|\bCTrade\b|SymbolSelect\s*\(|FileRead/,
  );
});

test('MQL5 EA request reader review harness stays disabled', () => {
  const source = read('MQL5/Experts/QuantGod_MultiStrategy.mq5');
  const begin = '// EA Request Reader Review Harness BEGIN';
  const end = '// EA Request Reader Review Harness END';
  assert.match(source, new RegExp(begin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(source, new RegExp(end.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const block = source.split(begin, 2)[1].split(end, 1)[0];
  for (const marker of [
    'QG_EA_REQUEST_READER_DISABLED_BY_DEFAULT',
    'QG_EA_REQUEST_SCHEMA_VALIDATION_REQUIRED',
    'QG_EA_IDEMPOTENCY_REQUEST_ID_REQUIRED',
    'QG_EA_KILL_SWITCH_REQUIRED',
    'QG_EA_RECEIPT_WRITER_REQUIRED',
    'QG_EA_ORDER_SEND_REQUIRES_SEPARATE_REVIEW',
    'BuildEARequestReaderReviewStatusJson',
    'QuantGod_EARequestReaderReviewStatus.json',
    'quantgod.mql5.ea_request_reader_review_status.v1',
    'effectiveEnabled',
    'requestFilesRead',
    'receiptFilesWritten',
    'orderSendAllowed',
  ]) {
    assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    block,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|FileOpen\s*\(|FileRead|FileWrite|\bCTrade\b/,
  );
});

test('MQL5 EA request reader execution skeleton stays disabled', () => {
  const source = read('MQL5/Experts/QuantGod_MultiStrategy.mq5');
  const begin = '// EA Request Reader Execution Skeleton BEGIN';
  const end = '// EA Request Reader Execution Skeleton END';
  assert.match(source, new RegExp(begin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(source, new RegExp(end.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const block = source.split(begin, 2)[1].split(end, 1)[0];
  for (const marker of [
    'QG_EA_REQUEST_READER_EXECUTION_DISABLED_BY_DEFAULT',
    'QG_EA_REQUEST_READER_EXECUTION_SEPARATE_FROM_REVIEW_HARNESS',
    'QG_EA_REQUEST_READER_EXECUTION_REQUIRES_PYTHON_WRITER',
    'QG_EA_REQUEST_READER_EXECUTION_REQUIRES_RECEIPT_RECONCILIATION',
    'QG_EA_REQUEST_READER_EXECUTION_REQUIRES_BROKER_SEND_REVIEW',
    'QG_EA_REQUEST_READER_EXECUTION_VALIDATION_MATRIX',
    'QG_EA_REQUEST_READER_EXECUTION_REJECTION_RECEIPT_PLAN',
    'QG_EA_REQUEST_READER_EXECUTION_RELEASE_TOKEN_REQUIRED',
    'QG_REVIEWED_EA_REQUEST_READER_RELEASE_V1',
    'REQUEST_READER_RELEASE_TOKEN_MISSING',
    'BuildEARequestReaderExecutionStatusJson',
    'BuildEARequestReaderExecutionRequiredFieldsJson',
    'BuildEARequestReaderExecutionRequiredTrueFusesJson',
    'BuildEARequestReaderExecutionAllowedValuesJson',
    'BuildEARequestReaderExecutionRejectionMatrixJson',
    'QuantGod_EARequestReaderExecutionStatus.json',
    'quantgod.mql5.ea_request_reader_execution_status.v1',
    'EXECUTION_READER_DISABLED_BY_DEFAULT',
    'request_contract_validation_matrix',
    'rejection_receipt_plan',
    'REQUEST_SCHEMA_MISMATCH',
    'REQUEST_DUPLICATE_REQUEST_ID',
    'KILL_SWITCH_ACTIVE',
    'request_file_polling',
    'request_file_parse',
    'broker_order_send',
    'requestFilesRead',
    'receiptFilesWritten',
    'orderSendAllowed',
    'eaRequestReaderExecution',
  ]) {
    assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    block,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|FileOpen\s*\(|FileRead|FileWrite|\bCTrade\b/,
  );
});

test('MQL5 broker order send review wrapper stays disabled', () => {
  const source = read('MQL5/Experts/QuantGod_MultiStrategy.mq5');
  const begin = '// Broker Order Send Review Wrapper BEGIN';
  const end = '// Broker Order Send Review Wrapper END';
  assert.match(source, new RegExp(begin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(source, new RegExp(end.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const block = source.split(begin, 2)[1].split(end, 1)[0];
  for (const marker of [
    'QG_BROKER_ORDER_SEND_WRAPPER_DISABLED_BY_DEFAULT',
    'QG_BROKER_ORDER_SEND_WRAPPER_REQUIRES_VALIDATED_REQUEST',
    'QG_BROKER_ORDER_SEND_WRAPPER_REQUIRES_ACCOUNT_SERVER_BINDING',
    'QG_BROKER_ORDER_SEND_WRAPPER_REQUIRES_RISK_FUSES',
    'QG_BROKER_ORDER_SEND_WRAPPER_REQUIRES_RECEIPT_OUTPUT',
    'BuildBrokerOrderSendWrapperStatusJson',
    'BuildBrokerOrderSendWrapperRequiredFusesJson',
    'BuildBrokerOrderSendWrapperRetcodePlanJson',
    'QuantGod_BrokerOrderSendWrapperStatus.json',
    'quantgod.mql5.broker_order_send_wrapper_status.v1',
    'BROKER_SEND_WRAPPER_DISABLED_BY_DEFAULT',
    'QG_BROKER_ORDER_SEND_WRAPPER_RELEASE_TOKEN_REQUIRED',
    'QG_REVIEWED_BROKER_ORDER_SEND_RELEASE_V1',
    'BROKER_ORDER_SEND_RELEASE_TOKEN_MISSING',
    'validated_ea_request_reader_only',
    'broker_order_send_call',
    'ticket_receipt_write',
    'brokerCallsMade',
    'orderSendAllowed',
    'mt5OrderSendAllowed',
    'brokerOrderSendWrapper',
  ]) {
    assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    block,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|FileOpen\s*\(|FileRead|FileWrite|\bCTrade\b/,
  );
});

test('MQL5 receipt writer reconciliation skeleton stays disabled', () => {
  const source = read('MQL5/Experts/QuantGod_MultiStrategy.mq5');
  const begin = '// Receipt Writer Reconciliation Skeleton BEGIN';
  const end = '// Receipt Writer Reconciliation Skeleton END';
  assert.match(source, new RegExp(begin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(source, new RegExp(end.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const block = source.split(begin, 2)[1].split(end, 1)[0];
  for (const marker of [
    'QG_RECEIPT_WRITER_RECONCILIATION_DISABLED_BY_DEFAULT',
    'QG_RECEIPT_WRITER_RECONCILIATION_REQUIRES_REQUEST_ID',
    'QG_RECEIPT_WRITER_RECONCILIATION_REQUIRES_ATOMIC_WRITE',
    'QG_RECEIPT_WRITER_RECONCILIATION_REQUIRES_ONE_RECEIPT_PER_REQUEST',
    'QG_RECEIPT_WRITER_RECONCILIATION_BLOCKS_ORPHAN_TICKET',
    'QG_RECEIPT_WRITER_RECONCILIATION_RELEASE_TOKEN_REQUIRED',
    'QG_REVIEWED_RECEIPT_WRITER_RELEASE_V1',
    'RECEIPT_WRITER_RELEASE_TOKEN_MISSING',
    'BuildReceiptWriterReconciliationStatusJson',
    'BuildReceiptWriterRequiredFieldsJson',
    'BuildReceiptReconciliationBlockMatrixJson',
    'QuantGod_ReceiptWriterReconciliationStatus.json',
    'quantgod.mql5.receipt_writer_reconciliation_status.v1',
    'RECEIPT_WRITER_RECONCILIATION_DISABLED_BY_DEFAULT',
    'MISSING_RECEIPT_FOR_REQUEST',
    'ORPHAN_RECEIPT_WITHOUT_REQUEST',
    'REVIEW_ONLY_RECEIPT_HAS_TICKET',
    'receipt_file_atomic_write',
    'receiptFilesWritten',
    'receiptDirectoryScanned',
    'autoDisableMutationAllowed',
    'receiptWriterReconciliation',
  ]) {
    assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    block,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|FileOpen\s*\(|FileRead|FileWrite|\bCTrade\b/,
  );
});

test('MQL5 rollback auto-disable skeleton stays disabled', () => {
  const source = read('MQL5/Experts/QuantGod_MultiStrategy.mq5');
  const begin = '// Rollback Auto Disable Skeleton BEGIN';
  const end = '// Rollback Auto Disable Skeleton END';
  assert.match(source, new RegExp(begin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(source, new RegExp(end.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const block = source.split(begin, 2)[1].split(end, 1)[0];
  for (const marker of [
    'QG_ROLLBACK_AUTO_DISABLE_DISABLED_BY_DEFAULT',
    'QG_ROLLBACK_AUTO_DISABLE_REQUIRES_RECEIPT_RECONCILIATION',
    'QG_ROLLBACK_AUTO_DISABLE_REQUIRES_RUNTIME_STALE_CHECK',
    'QG_ROLLBACK_AUTO_DISABLE_REQUIRES_MANUAL_REARM_REVIEW',
    'QG_ROLLBACK_AUTO_DISABLE_FORBIDS_LIVE_PRESET_MUTATION',
    'QG_ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_REQUIRED',
    'QG_REVIEWED_ROLLBACK_AUTO_DISABLE_RELEASE_V1',
    'ROLLBACK_AUTO_DISABLE_RELEASE_TOKEN_MISSING',
    'BuildRollbackAutoDisableStatusJson',
    'BuildRollbackAutoDisableTriggerMatrixJson',
    'BuildRollbackManualRearmRequirementsJson',
    'QuantGod_RollbackAutoDisableStatus.json',
    'quantgod.mql5.rollback_auto_disable_status.v1',
    'ROLLBACK_AUTO_DISABLE_DISABLED_BY_DEFAULT',
    'MISSING_RECEIPT_FOR_REQUEST',
    'BROKER_RETCODE_ERROR',
    'SLIPPAGE_EXCEEDS_LIMIT',
    'EA_STATUS_STALE',
    'UNEXPECTED_READER_ENABLED_BEFORE_REVIEW',
    'fresh_operator_approval',
    'receipt_reconciliation_passed',
    'auto_disable_state_write',
    'runtime_rearm',
    'autoDisableMutationAllowed',
    'livePresetMutationAllowed',
    'writesMt5Preset',
    'orderSendAllowed',
    'mt5OrderSendAllowed',
    'rollbackAutoDisable',
  ]) {
    assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(
    block,
    /OrderSend\s*\(|OrderSendAsync\s*\(|TRADE_ACTION_DEAL|PositionClose\s*\(|FileOpen\s*\(|FileRead|FileWrite|\bCTrade\b/,
  );
});

test('dashboard exposes HFM Crypto CFD local API namespace', () => {
  const server = read('Dashboard/dashboard_server.js');
  const routes = read('Dashboard/hfm_crypto_cfd_api_routes.js');
  for (const marker of [
    "require('./hfm_crypto_cfd_api_routes')",
    'isHFMCryptoCfdPath',
    '/api/hfm-crypto/status',
    '/api/hfm-crypto/symbols',
    '/api/hfm-crypto/contract-spec-export',
    '/api/hfm-crypto/contract-spec-export/build',
    '/api/hfm-crypto/execution-spec',
    '/api/hfm-crypto/execution-spec/build',
    '/api/hfm-crypto/simulation-profile',
    '/api/hfm-crypto/simulation-profile/build',
    '/api/hfm-crypto/evidence-kit',
    '/api/hfm-crypto/evidence-kit/build',
    '/api/hfm-crypto/evidence-bootstrap',
    '/api/hfm-crypto/evidence-bootstrap/build',
    '/api/hfm-crypto/mt5-exporter-review',
    '/api/hfm-crypto/mt5-exporter-review/build',
    '/api/hfm-crypto/mt5-upgrade-bundle',
    '/api/hfm-crypto/mt5-upgrade-bundle/build',
    '/api/hfm-crypto/mt5-exporter-deploy-plan',
    '/api/hfm-crypto/mt5-exporter-deploy-plan/build',
    '/api/hfm-crypto/standalone-exporter-bundle',
    '/api/hfm-crypto/standalone-exporter-bundle/build',
    '/api/hfm-crypto/mt5-post-upgrade-verify',
    '/api/hfm-crypto/mt5-post-upgrade-verify/build',
    '/api/hfm-crypto/post-upgrade-controller',
    '/api/hfm-crypto/post-upgrade-controller/build',
    '/api/hfm-crypto/filled-input-validator',
    '/api/hfm-crypto/filled-input-validator/build',
    '/api/hfm-crypto/build',
    'run_hfm_crypto_cfd.py',
    'resolveHfmCryptoRuntimeScope',
    'scope',
    'secondaryRuntimeDir',
  ]) {
    assert.match(`${server}\n${routes}`, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});

test('HFM Crypto API can resolve the secondary Live16 runtime scope', () => {
  const { resolveHfmCryptoRuntimeScope } = require(join(root, 'Dashboard/hfm_crypto_cfd_api_routes.js'));
  const defaultScope = resolveHfmCryptoRuntimeScope(
    { defaultRuntimeDir: '/tmp/qg-primary', secondaryRuntimeDir: root },
    new URL('/api/hfm-crypto/status?view=summary', 'http://127.0.0.1'),
  );
  const secondary = resolveHfmCryptoRuntimeScope(
    { defaultRuntimeDir: '/tmp/qg-primary', secondaryRuntimeDir: root },
    new URL('/api/hfm-crypto/status?view=summary&scope=live16', 'http://127.0.0.1'),
  );
  const primary = resolveHfmCryptoRuntimeScope(
    { defaultRuntimeDir: '/tmp/qg-primary', secondaryRuntimeDir: root },
    new URL('/api/hfm-crypto/status?scope=primary', 'http://127.0.0.1'),
  );

  assert.equal(defaultScope.scope, 'secondary');
  assert.equal(defaultScope.accountLabel, 'HFM Live16 crypto CFD');
  assert.equal(defaultScope.runtimeDir, root);
  assert.equal(secondary.scope, 'secondary');
  assert.equal(secondary.accountLabel, 'HFM Live16 crypto CFD');
  assert.equal(secondary.runtimeDir, root);
  assert.equal(primary.scope, 'primary');
  assert.equal(primary.runtimeDir, '/tmp/qg-primary');
});

test('HFM Crypto status summary keeps account diagnostics without bulky review payloads', () => {
  const { compactStatusPayload } = require(join(root, 'Dashboard/hfm_crypto_cfd_api_routes.js'));
  const compact = compactStatusPayload({
    exitCode: 0,
    stderr: '',
    ok: true,
    schema: 'quantgod.hfm_crypto_cfd.state.v1',
    generatedAt: '2026-05-31T00:00:00Z',
    status: 'WAITING_HFM_ACCOUNT_CRYPTO_CFD_SYMBOLS',
    statusZh: '当前 HFM 账号未下发 Crypto CFD symbols',
    nextRequiredActionZh: '需要换用开通 HFM crypto CFD 的 HFM 账号/服务器。',
    operatorChecklist: [
      {
        id: 'hfm_account_crypto_cfd_symbols',
        labelZh: 'HFM 账号/服务器下发 crypto CFD symbols',
        status: 'BLOCKED',
        statusZh: '当前账号/服务器没有 crypto CFD symbols',
        blocking: true,
        required: true,
        automated: false,
        nextActionZh: '换用开通 HFM crypto CFD 的 HFM MT5 账号/服务器。',
      },
    ],
    targetSymbols: ['BTCUSD', 'ETHUSD'],
    symbolEvidence: {
      found: false,
      canonicalSymbols: [],
      brokerSymbols: [],
      sources: [],
      brokerSymbolDiagnostics: {
        brokerSymbolTotalAll: 56,
        brokerSymbolTotalMarketWatch: 13,
        brokerCryptoLikeCountAll: 0,
        brokerCryptoLikeCountMarketWatch: 0,
        brokerSymbolSampleCount: 2,
        brokerSymbolSamples: [
          {
            brokerSymbol: 'USDJPYc',
            canonicalSymbol: 'USDJPY',
            path: 'ForexCent\\USDJPYc',
            looksLikeCrypto: false,
          },
          {
            brokerSymbol: 'XAUUSDc',
            canonicalSymbol: 'XAUUSD',
            path: 'Metals\\XAUUSDc',
            looksLikeCrypto: false,
          },
        ],
      },
    },
    standaloneExporterBundle: {
      schema: 'quantgod.hfm_crypto_cfd.standalone_exporter_bundle.v1',
      status: 'WAITING_STANDALONE_MT5_RUNTIME_PROBE_INSTALL',
      statusZh: '等待安装/编译带 runtime probe 的只读 HFM crypto exporter EA',
      nextRequiredActionZh: 'staged EA 已包含 runtime probe。',
      standaloneExporterReady: true,
      targetInstalledAndCompiled: true,
      targetExpertInstalledAndCompiled: false,
      targetScriptInstalledAndCompiled: true,
      runtimeProbeMissingAfterSpecs: true,
      runtimeProbeTickDetected: false,
      startupConfig: { configSource: { startupSymbol: '#BTCUSD' } },
      bundle: { stagedExpertPath: '/tmp/staged/QuantGod_HFMCryptoSpecExporterEA.mq5' },
      target: {
        targetExpertPath: '/tmp/Experts/QuantGod_HFMCryptoSpecExporterEA.mq5',
        targetExpertInstalledMatchesBundle: false,
        targetExpertCompiledExists: true,
      },
      output: {
        expectedRuntimeProbePath: '/tmp/Files/hfm_crypto/QuantGod_HFMCryptoRuntimeProbe.json',
        expectedRuntimeProbeExists: false,
        expectedRuntimeProbeLiveTickCount: 0,
      },
      commandsForHumanReview: Array.from({ length: 100 }, (_, index) => ({ index })),
    },
    safety: {
      readOnly: true,
      shadowOnly: true,
      orderSendAllowed: false,
      mt5OrderSendAllowed: false,
    },
  });

  assert.equal(compact.compactView, true);
  assert.equal(compact.status, 'WAITING_HFM_ACCOUNT_CRYPTO_CFD_SYMBOLS');
  assert.equal(compact.symbolEvidence.brokerSymbolDiagnostics.brokerSymbolTotalAll, 56);
  assert.equal(compact.symbolEvidence.brokerSymbolDiagnostics.brokerCryptoLikeCountAll, 0);
  assert.equal(compact.symbolEvidence.brokerSymbolDiagnostics.brokerSymbolSamples.length, 2);
  assert.equal(compact.operatorChecklist.length, 1);
  assert.equal(compact.operatorChecklist[0].id, 'hfm_account_crypto_cfd_symbols');
  assert.equal(compact.operatorChecklist[0].status, 'BLOCKED');
  assert.equal(compact.safety.mt5OrderSendAllowed, false);
  assert.equal(compact.standaloneExporterBundle.status, 'WAITING_STANDALONE_MT5_RUNTIME_PROBE_INSTALL');
  assert.equal(compact.standaloneExporterBundle.runtimeProbeMissingAfterSpecs, true);
  assert.equal(compact.standaloneExporterBundle.startupSymbol, '#BTCUSD');
  assert.equal(compact.standaloneExporterBundle.expectedRuntimeProbeLiveTickCount, 0);
  assert.equal(compact.standaloneExporterBundle.commandsForHumanReview, undefined);
});

test('non HFM event-market API namespace is absent from phase2 routes', () => {
  const server = read('Dashboard/dashboard_server.js');
  const phase2 = read('Dashboard/phase2_api_routes.js');
  assert.equal(server.toLowerCase().includes('poly' + 'market'), false);
  assert.equal(server.toLowerCase().includes('event-market'), false);
  assert.equal(phase2.includes('/api/' + 'poly' + 'market'), false);
});

test('non HFM market env examples are absent', () => {
  const envExample = read('.env.example');
  const telegramExample = read('.env.telegram.local.example');
  assert.doesNotMatch(envExample, /CLOB|PRIVATE_KEY/i);
  assert.doesNotMatch(telegramExample, /TELETHON_SESSION=.*market/i);
});
