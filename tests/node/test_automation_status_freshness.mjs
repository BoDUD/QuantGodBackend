import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const root = process.cwd();
const routes = require(path.join(root, 'Dashboard', 'automation_chain_api_routes.js'));

test('missing automation report is NOT_STARTED instead of successful', () => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-automation-missing-'));
  try {
    const status = routes.automationStatus(path.join(runtime, 'missing.json'), runtime, 'USDJPYc');
    assert.equal(status.runStatus, 'NOT_STARTED');
    assert.equal(status.schedulerState, 'NOT_STARTED');
    assert.equal(status.stepCount, 0);
    assert.equal(status.safety.executionLaneExists, false);
    assert.equal(status.safety.liveExpansionAllowed, false);
    assert.equal(status.safety.operatorApprovalRequired, true);
  } finally {
    fs.rmSync(runtime, { recursive: true, force: true });
  }
});

test('old successful automation report becomes stale without rewriting its evidence', () => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-automation-stale-'));
  const latest = path.join(runtime, 'latest.json');
  try {
    fs.writeFileSync(latest, JSON.stringify({
      cycleId: 'cycle-old',
      runStatus: 'COMPLETED',
      state: 'READY',
      heartbeatAt: '2026-05-01T00:00:00Z',
      safety: { orderSendAllowed: false },
    }));
    const old = new Date('2026-05-01T00:00:00Z');
    fs.utimesSync(latest, old, old);
    const status = routes.automationStatus(latest, runtime, 'USDJPYc');
    assert.equal(status.runStatus, 'COMPLETED');
    assert.equal(status.schedulerState, 'STALE');
    assert.equal(status.freshness.status, 'STALE');
    assert.match(status.blockedReasons.join(','), /AUTOMATION_HEARTBEAT_STALE/);
    assert.equal(status.safety.unattendedLiveExpansionAllowed, false);
  } finally {
    fs.rmSync(runtime, { recursive: true, force: true });
  }
});
