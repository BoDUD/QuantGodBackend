import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
const health = require(path.join(repoRoot, 'Dashboard', 'health_api_routes.js'));

function writeJson(filePath, payload, mtimeMs) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload));
  const observedAt = new Date(mtimeMs);
  fs.utimesSync(filePath, observedAt, observedAt);
}

function setDiskMaintenanceStatusFile(t, filePath, statusRoot = '') {
  const previous = process.env.QG_DISK_MAINTENANCE_STATUS_FILE;
  const previousRoot = process.env.QG_LAUNCHD_STATUS_ROOT;
  const previousFreshness = process.env.QG_DISK_MAINTENANCE_FRESH_SECONDS;
  process.env.QG_DISK_MAINTENANCE_STATUS_FILE = filePath;
  if (statusRoot) process.env.QG_LAUNCHD_STATUS_ROOT = statusRoot;
  else delete process.env.QG_LAUNCHD_STATUS_ROOT;
  delete process.env.QG_DISK_MAINTENANCE_FRESH_SECONDS;
  t.after(() => {
    if (previous === undefined) delete process.env.QG_DISK_MAINTENANCE_STATUS_FILE;
    else process.env.QG_DISK_MAINTENANCE_STATUS_FILE = previous;
    if (previousRoot === undefined) delete process.env.QG_LAUNCHD_STATUS_ROOT;
    else process.env.QG_LAUNCHD_STATUS_ROOT = previousRoot;
    if (previousFreshness === undefined) delete process.env.QG_DISK_MAINTENANCE_FRESH_SECONDS;
    else process.env.QG_DISK_MAINTENANCE_FRESH_SECONDS = previousFreshness;
  });
}

function withoutDiskMaintenanceEnv(callback) {
  const previous = process.env.QG_DISK_MAINTENANCE_STATUS_FILE;
  const previousRoot = process.env.QG_LAUNCHD_STATUS_ROOT;
  const previousFreshness = process.env.QG_DISK_MAINTENANCE_FRESH_SECONDS;
  delete process.env.QG_DISK_MAINTENANCE_STATUS_FILE;
  delete process.env.QG_LAUNCHD_STATUS_ROOT;
  delete process.env.QG_DISK_MAINTENANCE_FRESH_SECONDS;
  try {
    return callback();
  } finally {
    if (previous === undefined) delete process.env.QG_DISK_MAINTENANCE_STATUS_FILE;
    else process.env.QG_DISK_MAINTENANCE_STATUS_FILE = previous;
    if (previousRoot === undefined) delete process.env.QG_LAUNCHD_STATUS_ROOT;
    else process.env.QG_LAUNCHD_STATUS_ROOT = previousRoot;
    if (previousFreshness === undefined) delete process.env.QG_DISK_MAINTENANCE_FRESH_SECONDS;
    else process.env.QG_DISK_MAINTENANCE_FRESH_SECONDS = previousFreshness;
  }
}

test('weekend market is neutral closed instead of READY or quote failure', () => {
  const session = health.marketSession(Date.parse('2026-08-01T12:00:00Z'), false);
  assert.deepEqual(session, { state: 'CLOSED', reasonCode: 'WEEKEND' });
});

test('operator overview separates writer, broker, authorization, quote, data and automation truth', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-01T12:00:00Z');

  writeJson(path.join(runtimeDir, 'QuantGod_Dashboard.json'), {
    timestamp: '2026-08-01T11:59:50Z',
    account: { number: 123456, server: 'Synthetic-Live' },
    runtime: {
      processRunning: true,
      terminalConnected: true,
      brokerSessionConnected: true,
      accountIdentityPresent: true,
      accountAuthorized: true,
      connected: true,
      tickAgeSeconds: 58000,
      shadowMode: true,
      readOnlyMode: true,
    },
    symbols: [{ symbol: 'USDJPYc', status: 'READY', tickAgeSeconds: 0, entryTradeAllowed: true }],
  }, nowMs - 10000);
  writeJson(path.join(runtimeDir, 'backtest', 'QuantGod_USDJPYHistoryProductionStatus.json'), {
    productionStatus: 'PASS',
  }, nowMs - 10000);
  writeJson(path.join(runtimeDir, 'automation', 'QuantGod_AutomationChainLatest.json'), {
    state: 'NOT_RUN',
  }, nowMs - 10000);
  writeJson(path.join(runtimeDir, 'production_validation', 'QuantGod_ProductionEvidenceValidationReport.json'), {
    report: { status: 'FAIL' },
  }, nowMs - 10000);

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(overview.mode, 'SHADOW_READONLY');
  assert.equal(overview.mt5.writerFresh, true);
  assert.equal(overview.mt5.processRunning, true);
  assert.equal(overview.mt5.brokerSessionConnected, true);
  assert.equal(overview.mt5.brokerConnected, true);
  assert.equal(overview.mt5.accountIdentityPresent, true);
  assert.equal(overview.mt5.accountAuthorized, true);
  assert.equal(overview.mt5.quoteFresh, false);
  assert.deepEqual(overview.mt5.marketSession, { state: 'CLOSED', reasonCode: 'WEEKEND' });
  assert.equal(overview.mt5.monitorReady, true);
  assert.equal(overview.mt5.tradingReady, false);
  assert.equal(overview.data.ready, true);
  assert.equal(overview.automation.ready, false);
  assert.equal(overview.evidence.ready, false);
  assert.equal(overview.operationalReady, false);
  assert.equal(overview.overallStatus, 'BLOCKED');
  assert.match(overview.blockedReasons.join(','), /AUTOMATION_NOT_RUN_FRESH/);
  assert.match(overview.blockedReasons.join(','), /EVIDENCE_FAIL_FRESH/);
  assert.equal(overview.safety.executionLaneExists, false);
  assert.equal(overview.safety.liveExpansionAllowed, false);
  assert.equal(overview.safety.operatorApprovalRequired, true);
  assert.ok(overview.canonicalDataRoot.id.length >= 12);
});

test('identity and fresh writer do not imply an authorized broker session', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-auth-failed-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-03T12:00:00Z');

  writeJson(path.join(runtimeDir, 'QuantGod_Dashboard.json'), {
    timestamp: '2026-08-03T11:59:50Z',
    account: { number: 123456, server: 'Synthetic-Live' },
    runtime: {
      processRunning: true,
      brokerSessionConnected: false,
      accountIdentityPresent: true,
      // Legacy/broken writers could leave this true after AUTH_FAILED.
      accountAuthorized: true,
      tickAgeSeconds: 10,
    },
  }, nowMs - 10000);

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(overview.mt5.writerFresh, true);
  assert.equal(overview.mt5.processRunning, true);
  assert.equal(overview.mt5.accountIdentityPresent, true);
  assert.equal(overview.mt5.brokerSessionConnected, false);
  assert.equal(overview.mt5.brokerConnected, false);
  assert.equal(overview.mt5.accountAuthorized, false);
  assert.equal(overview.mt5.monitorReady, false);
  assert.match(overview.blockedReasons.join(','), /BROKER_NOT_CONFIRMED/);
  assert.match(overview.blockedReasons.join(','), /ACCOUNT_NOT_AUTHORIZED/);
});

test('old PASS artifacts are stale and cannot make readiness pass', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-stale-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-03T12:00:00Z');
  const oldMs = nowMs - 48 * 60 * 60 * 1000;

  writeJson(path.join(runtimeDir, 'QuantGod_Dashboard.json'), {
    timestamp: '2026-08-03T11:59:50Z',
    runtime: { terminalConnected: true, accountAuthorized: true, tickAgeSeconds: 10 },
  }, nowMs - 10000);
  writeJson(path.join(runtimeDir, 'backtest', 'QuantGod_USDJPYHistoryProductionStatus.json'), {
    productionStatus: 'PASS',
  }, oldMs);
  writeJson(path.join(runtimeDir, 'automation', 'QuantGod_AutomationChainLatest.json'), {
    state: 'COMPLETED',
  }, oldMs);
  writeJson(path.join(runtimeDir, 'production_validation', 'QuantGod_ProductionEvidenceValidationReport.json'), {
    report: { status: 'PASS' },
  }, oldMs);

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(overview.data.history.status, 'PASS');
  assert.equal(overview.data.history.freshness, 'STALE');
  assert.equal(overview.data.ready, false);
  assert.equal(overview.automation.ready, false);
  assert.equal(overview.evidence.ready, false);
  assert.equal(overview.operationalReady, false);
  assert.match(overview.blockedReasons.join(','), /HISTORY_PASS_STALE/);
});

test('stale writer evidence cannot claim current broker connection or account authorization', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-stale-writer-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-03T12:00:00Z');

  writeJson(path.join(runtimeDir, 'QuantGod_Dashboard.json'), {
    timestamp: '2026-08-03T11:00:00Z',
    runtime: {
      terminalConnected: true,
      accountAuthorized: true,
      tickAgeSeconds: 10,
      shadowMode: true,
      readOnlyMode: true,
    },
  }, nowMs - 60 * 60 * 1000);

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(overview.mt5.writerFresh, false);
  assert.equal(overview.mt5.processRunning, false);
  assert.equal(overview.mt5.brokerSessionConnected, false);
  assert.equal(overview.mt5.brokerConnected, false);
  assert.equal(overview.mt5.brokerConnectionKnown, false);
  assert.equal(overview.mt5.accountAuthorized, false);
  assert.equal(overview.mt5.accountAuthorizationKnown, false);
  assert.equal(overview.mt5.quoteFresh, false);
  assert.match(overview.blockedReasons.join(','), /MT5_WRITER_STALE/);
  assert.doesNotMatch(overview.blockedReasons.join(','), /BROKER_NOT_CONFIRMED/);
  assert.doesNotMatch(overview.blockedReasons.join(','), /ACCOUNT_NOT_AUTHORIZED/);
});

test('fresh SHADOW_ADVISORY_READY evidence satisfies report readiness', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-shadow-ready-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-03T12:00:00Z');

  writeJson(
    path.join(runtimeDir, 'production_validation', 'QuantGod_ProductionEvidenceValidationReport.json'),
    { report: { status: 'SHADOW_ADVISORY_READY' } },
    nowMs - 10000,
  );

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(overview.evidence.production.status, 'SHADOW_ADVISORY_READY');
  assert.equal(overview.evidence.production.freshness, 'FRESH');
  assert.equal(overview.evidence.ready, true);
  assert.doesNotMatch(overview.blockedReasons.join(','), /EVIDENCE_SHADOW_ADVISORY_READY/);
});

test('SHADOW_ADVISORY_READY is accepted for automation but not history', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-shadow-scope-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-03T12:00:00Z');

  writeJson(path.join(runtimeDir, 'backtest', 'QuantGod_USDJPYHistoryProductionStatus.json'), {
    productionStatus: 'SHADOW_ADVISORY_READY',
  }, nowMs - 10000);
  writeJson(path.join(runtimeDir, 'automation', 'QuantGod_AutomationChainLatest.json'), {
    state: 'SHADOW_ADVISORY_READY',
  }, nowMs - 10000);

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(overview.automation.status, 'SHADOW_ADVISORY_READY');
  assert.equal(overview.automation.ready, true);
  assert.equal(overview.data.history.status, 'SHADOW_ADVISORY_READY');
  assert.equal(overview.data.history.ready, false);
  assert.equal(overview.data.ready, false);
  assert.match(overview.blockedReasons.join(','), /HISTORY_SHADOW_ADVISORY_READY_FRESH/);
  assert.doesNotMatch(overview.blockedReasons.join(','), /AUTOMATION_SHADOW_ADVISORY_READY_FRESH/);
});

test('disk health exposes only the recent maintenance summary', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-disk-maintenance-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-06T01:00:00Z');
  const statusFile = path.join(runtimeDir, 'QuantGod_DiskSpaceMaintenanceStatus.json');
  writeJson(statusFile, {
    schema: 'quantgod.disk_space_maintenance.v1',
    generatedAtIso: '2026-08-06T00:59:00Z',
    status: 'PRESSURE_REMAINS',
    mode: 'EXECUTE',
    appliedPressureLevel: 'CRITICAL',
    pressureLevel: 'CRITICAL',
    pressureActive: true,
    pressureReason: 'critical_threshold',
    pressureRemainingBytes: 67108864,
    summary: {
      candidateCount: 12,
      reclaimableCount: 10,
      reclaimableBytes: 100000000,
      deletedCount: 4,
      deletedBytes: 13107200,
      errorCount: 0,
    },
    deleted: [{ path: '/private/path/must-not-leak' }],
    allowedRoots: ['/private/path/must-not-leak'],
    safety: {
      localOnly: true,
      userDataDeletionAllowed: false,
      mt5MutationAllowed: false,
      orderSendAllowed: false,
    },
  }, nowMs - 60000);
  fs.chmodSync(statusFile, 0o600);
  setDiskMaintenanceStatusFile(t, statusFile);

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.deepEqual(overview.disk.maintenance, {
    available: true,
    status: 'PRESSURE_REMAINS',
    schema: 'quantgod.disk_space_maintenance.v1',
    generatedAtIso: '2026-08-06T00:59:00Z',
    ageSeconds: 60,
    maxAgeSeconds: 7200,
    freshness: 'FRESH',
    mode: 'EXECUTE',
    appliedPressureLevel: 'CRITICAL',
    pressureLevel: 'CRITICAL',
    pressureActive: true,
    pressureReason: 'critical_threshold',
    pressureRemainingBytes: 67108864,
    summary: {
      candidateCount: 12,
      reclaimableCount: 10,
      reclaimableBytes: 100000000,
      deletedCount: 4,
      deletedBytes: 13107200,
      errorCount: 0,
    },
    safety: {
      localOnly: true,
      userDataDeletionAllowed: false,
      mt5MutationAllowed: false,
      orderSendAllowed: false,
    },
  });
  assert.equal(JSON.stringify(overview.disk.maintenance).includes('must-not-leak'), false);
});

test('stale maintenance evidence is observable but does not change statfs', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-disk-stale-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-06T04:00:00Z');
  const baseline = withoutDiskMaintenanceEnv(
    () => health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs).disk,
  );
  const statusFile = path.join(runtimeDir, 'QuantGod_DiskSpaceMaintenanceStatus.json');
  writeJson(statusFile, {
    schema: 'quantgod.disk_space_maintenance.v1',
    generatedAtIso: '2026-08-06T01:00:00Z',
    status: 'SUCCESS',
  }, nowMs - 3 * 60 * 60 * 1000);
  fs.chmodSync(statusFile, 0o600);
  setDiskMaintenanceStatusFile(t, statusFile);

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(overview.disk.maintenance.available, true);
  assert.equal(overview.disk.maintenance.status, 'SUCCESS');
  assert.equal(overview.disk.maintenance.freshness, 'STALE');
  assert.equal(overview.disk.maintenance.ageSeconds, 10800);
  assert.equal(overview.disk.maintenance.maxAgeSeconds, 7200);
  assert.equal(overview.disk.status, baseline.status);
  assert.equal(overview.disk.available, baseline.available);
});

test('invalid or implausibly future maintenance timestamps are unavailable', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-disk-time-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-06T04:00:00Z');
  const statusFile = path.join(runtimeDir, 'QuantGod_DiskSpaceMaintenanceStatus.json');
  writeJson(statusFile, {
    schema: 'quantgod.disk_space_maintenance.v1',
    generatedAtIso: 'not-a-timestamp',
    status: 'SUCCESS',
  }, nowMs - 60000);
  fs.chmodSync(statusFile, 0o600);
  setDiskMaintenanceStatusFile(t, statusFile);

  const invalid = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(invalid.disk.maintenance.status, 'UNAVAILABLE');
  assert.equal(invalid.disk.maintenance.reason, 'STATUS_TIMESTAMP_INVALID');

  writeJson(statusFile, {
    schema: 'quantgod.disk_space_maintenance.v1',
    generatedAtIso: '2026-08-07T04:00:00Z',
    status: 'SUCCESS',
  }, nowMs - 60000);
  fs.chmodSync(statusFile, 0o600);
  const future = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(future.disk.maintenance.status, 'UNAVAILABLE');
  assert.equal(future.disk.maintenance.reason, 'STATUS_TIMESTAMP_IN_FUTURE');
  assert.equal(future.disk.status, invalid.disk.status);
});

test('unreadable maintenance evidence is unavailable without changing statfs readiness', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-disk-unavailable-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-06T01:00:00Z');

  const baseline = withoutDiskMaintenanceEnv(
    () => health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs).disk,
  );

  const invalid = path.join(runtimeDir, 'invalid-maintenance.json');
  fs.writeFileSync(invalid, '{invalid json');
  fs.chmodSync(invalid, 0o600);
  const symlink = path.join(runtimeDir, 'maintenance-link.json');
  fs.symlinkSync(invalid, symlink);
  setDiskMaintenanceStatusFile(t, symlink);

  const overview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(overview.disk.maintenance.status, 'UNAVAILABLE');
  assert.equal(overview.disk.maintenance.reason, 'STATUS_FILE_NOT_REGULAR');
  assert.equal(overview.disk.status, baseline.status);
  assert.equal(overview.disk.available, baseline.available);
  assert.equal(typeof overview.disk.freeBytes, typeof baseline.freeBytes);

  process.env.QG_DISK_MAINTENANCE_STATUS_FILE = invalid;
  const invalidOverview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(invalidOverview.disk.maintenance.status, 'UNAVAILABLE');
  assert.equal(invalidOverview.disk.maintenance.reason, 'STATUS_READ_FAILED');
  assert.equal(invalidOverview.disk.status, baseline.status);
  assert.equal(invalidOverview.disk.available, baseline.available);
  assert.equal(typeof invalidOverview.disk.freeBytes, typeof baseline.freeBytes);
});

test('maintenance status rejects broad permissions and hard links without changing statfs', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-disk-file-safety-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-06T01:00:00Z');
  const payload = {
    schema: 'quantgod.disk_space_maintenance.v1',
    generatedAtIso: '2026-08-06T00:59:00Z',
    status: 'SUCCESS',
  };
  const baseline = withoutDiskMaintenanceEnv(
    () => health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs).disk,
  );

  const broad = path.join(runtimeDir, 'broad-maintenance.json');
  writeJson(broad, payload, nowMs - 60000);
  fs.chmodSync(broad, 0o644);
  setDiskMaintenanceStatusFile(t, broad);

  const broadOverview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(broadOverview.disk.maintenance.status, 'UNAVAILABLE');
  assert.equal(broadOverview.disk.maintenance.reason, 'STATUS_FILE_PERMISSIONS_TOO_OPEN');
  assert.equal(broadOverview.disk.status, baseline.status);

  const original = path.join(runtimeDir, 'single-owner-maintenance.json');
  const linked = path.join(runtimeDir, 'linked-maintenance.json');
  writeJson(original, payload, nowMs - 60000);
  fs.chmodSync(original, 0o600);
  fs.linkSync(original, linked);
  process.env.QG_DISK_MAINTENANCE_STATUS_FILE = linked;

  const linkedOverview = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(linkedOverview.disk.maintenance.status, 'UNAVAILABLE');
  assert.equal(linkedOverview.disk.maintenance.reason, 'STATUS_FILE_HARDLINKED');
  assert.equal(linkedOverview.disk.status, baseline.status);
  assert.equal(linkedOverview.disk.available, baseline.available);
});

test('configured launchd status root requires the exact maintenance filename', (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-health-disk-boundary-'));
  t.after(() => fs.rmSync(runtimeDir, { recursive: true, force: true }));
  const nowMs = Date.parse('2026-08-06T01:00:00Z');
  const statusRoot = path.join(runtimeDir, 'status');
  const statusFile = path.join(statusRoot, 'QuantGod_DiskSpaceMaintenanceStatus.json');
  const payload = {
    schema: 'quantgod.disk_space_maintenance.v1',
    generatedAtIso: '2026-08-06T00:59:00Z',
    status: 'SUCCESS',
  };
  writeJson(statusFile, payload, nowMs - 60000);
  fs.chmodSync(statusFile, 0o600);
  setDiskMaintenanceStatusFile(t, statusFile, statusRoot);

  const valid = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(valid.disk.maintenance.available, true);

  const wrongFile = path.join(statusRoot, 'other-maintenance.json');
  writeJson(wrongFile, payload, nowMs - 60000);
  fs.chmodSync(wrongFile, 0o600);
  process.env.QG_DISK_MAINTENANCE_STATUS_FILE = wrongFile;

  const rejected = health.buildOperatorOverview({ defaultRuntimeDir: runtimeDir }, nowMs);
  assert.equal(rejected.disk.maintenance.status, 'UNAVAILABLE');
  assert.equal(rejected.disk.maintenance.reason, 'STATUS_FILE_PATH_MISMATCH');
  assert.equal(rejected.disk.status, valid.disk.status);
});
