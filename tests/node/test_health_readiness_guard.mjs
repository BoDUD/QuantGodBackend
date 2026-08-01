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
    runtime: {
      terminalConnected: true,
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
  assert.equal(overview.mt5.brokerConnected, true);
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
  assert.equal(overview.mt5.brokerConnected, false);
  assert.equal(overview.mt5.brokerConnectionKnown, false);
  assert.equal(overview.mt5.accountAuthorized, false);
  assert.equal(overview.mt5.accountAuthorizationKnown, false);
  assert.equal(overview.mt5.quoteFresh, false);
  assert.match(overview.blockedReasons.join(','), /MT5_WRITER_STALE/);
  assert.doesNotMatch(overview.blockedReasons.join(','), /BROKER_NOT_CONFIRMED/);
  assert.doesNotMatch(overview.blockedReasons.join(','), /ACCOUNT_NOT_AUTHORIZED/);
});
