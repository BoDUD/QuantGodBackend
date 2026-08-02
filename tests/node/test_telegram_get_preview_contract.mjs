import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test, { after, before } from 'node:test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const repoRoot = process.cwd();
const automationRoutes = require('../../Dashboard/automation_chain_api_routes.js');
const caseMemoryRoutes = require('../../Dashboard/case_memory_api_routes.js');
const gaFactoryAliasRoutes = require('../../Dashboard/ga_factory_api_routes.js');
const productionEvidenceRoutes = require('../../Dashboard/production_evidence_validation_api_routes.js');
const strategyFactoryRoutes = require('../../Dashboard/strategy_ga_factory_api_routes.js');
const telegramGatewayRoutes = require('../../Dashboard/telegram_gateway_ops_api_routes.js');
const usdjpyRoutes = require('../../Dashboard/usdjpy_strategy_lab_api_routes.js');

const endpointCases = [
  ['automation-chain', '/api/automation-chain/telegram-text', automationRoutes],
  ['case-memory', '/api/case-memory/telegram-text', caseMemoryRoutes],
  ['strategy-ga-factory', '/api/strategy-ga-factory/telegram-text', strategyFactoryRoutes],
  ['ga-factory-alias', '/api/ga-factory/telegram-text', gaFactoryAliasRoutes],
  ['production-evidence', '/api/production-evidence-validation/telegram-text', productionEvidenceRoutes],
  ['telegram-gateway', '/api/telegram-gateway/telegram-text', telegramGatewayRoutes],
  ['usdjpy-live-loop', '/api/usdjpy-strategy-lab/live-loop/telegram-text', usdjpyRoutes],
  ['usdjpy-evolution', '/api/usdjpy-strategy-lab/evolution/telegram-text', usdjpyRoutes],
  ['usdjpy-bar-replay', '/api/usdjpy-strategy-lab/bar-replay/telegram-text', usdjpyRoutes],
  ['usdjpy-walk-forward', '/api/usdjpy-strategy-lab/walk-forward/telegram-text', usdjpyRoutes],
  ['usdjpy-autonomous', '/api/usdjpy-strategy-lab/autonomous-agent/telegram-text', usdjpyRoutes],
  [
    'usdjpy-daily-autopilot',
    '/api/usdjpy-strategy-lab/autonomous-agent/daily-autopilot-v2/telegram-text',
    usdjpyRoutes,
  ],
  ['usdjpy-daily-todo', '/api/usdjpy-strategy-lab/daily-todo/telegram-text', usdjpyRoutes],
  ['usdjpy-daily-review', '/api/usdjpy-strategy-lab/daily-review/telegram-text', usdjpyRoutes],
  ['usdjpy-strategy-lab', '/api/usdjpy-strategy-lab/telegram-text', usdjpyRoutes],
  ['usdjpy-backtest', '/api/usdjpy-strategy-lab/strategy-backtest/telegram-text', usdjpyRoutes],
  ['usdjpy-evidence-os', '/api/usdjpy-strategy-lab/evidence-os/telegram-text', usdjpyRoutes],
  ['usdjpy-ga', '/api/usdjpy-strategy-lab/ga/telegram-text', usdjpyRoutes],
  ['usdjpy-contract', '/api/usdjpy-strategy-lab/strategy-contract/telegram-text', usdjpyRoutes],
];

let tempDir;
let fakePython;
let argvLog;
let previousPythonBin;
let previousArgvLog;
let previousFailure;

before(() => {
  tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-telegram-preview-contract-'));
  fakePython = path.join(tempDir, 'fake-python');
  argvLog = path.join(tempDir, 'argv.jsonl');
  fs.writeFileSync(
    fakePython,
    `#!/usr/bin/env node
const fs = require('node:fs');
fs.appendFileSync(process.env.QG_FAKE_PYTHON_ARGV_LOG, JSON.stringify(process.argv.slice(2)) + '\\n');
if (process.env.QG_FAKE_PYTHON_FAIL === '1') {
  process.stderr.write('synthetic runner failure');
  process.exit(7);
}
process.stdout.write(JSON.stringify({
  ok: true,
  originalField: 'preserved',
  sent: true,
  deliveryOk: true,
  delivery: { ok: true, status: 'SENT', sourceField: 'preserved' },
}));
`,
    { encoding: 'utf8', mode: 0o755 },
  );
  previousPythonBin = process.env.QG_PYTHON_BIN;
  previousArgvLog = process.env.QG_FAKE_PYTHON_ARGV_LOG;
  previousFailure = process.env.QG_FAKE_PYTHON_FAIL;
  process.env.QG_PYTHON_BIN = fakePython;
  process.env.QG_FAKE_PYTHON_ARGV_LOG = argvLog;
});

after(() => {
  restoreEnv('QG_PYTHON_BIN', previousPythonBin);
  restoreEnv('QG_FAKE_PYTHON_ARGV_LOG', previousArgvLog);
  restoreEnv('QG_FAKE_PYTHON_FAIL', previousFailure);
  fs.rmSync(tempDir, { recursive: true, force: true });
});

function restoreEnv(key, value) {
  if (value === undefined) delete process.env[key];
  else process.env[key] = value;
}

async function invoke(routes, requestUrl) {
  let statusCode = null;
  let body = '';
  const response = {
    writeHead(code) {
      statusCode = code;
    },
    end(value) {
      body = String(value || '');
    },
  };
  await routes.handle(
    { method: 'GET', url: requestUrl },
    response,
    { defaultRuntimeDir: tempDir, repoRoot },
  );
  return { statusCode, payload: JSON.parse(body) };
}

function invocationCount() {
  if (!fs.existsSync(argvLog)) return 0;
  return fs.readFileSync(argvLog, 'utf8').trim().split(/\r?\n/).filter(Boolean).length;
}

function loggedArgv() {
  if (!fs.existsSync(argvLog)) return [];
  return fs.readFileSync(argvLog, 'utf8').trim().split(/\r?\n/).filter(Boolean).map(JSON.parse);
}

function assertPreviewTruth(payload) {
  assert.equal(payload.previewOnly, true);
  assert.equal(payload.sendRequested, false);
  assert.equal(payload.sent, false);
  assert.equal(payload.deliveryOk, false);
  assert.equal(payload.delivery.ok, false);
  assert.equal(payload.delivery.status, 'PREVIEW_ONLY');
}

test('all GET telegram-text routes return a preserved delivery-false preview', async () => {
  process.env.QG_FAKE_PYTHON_FAIL = '0';
  for (const [name, endpoint, routes] of endpointCases) {
    const result = await invoke(routes, `${endpoint}?refresh=1`);
    assert.equal(result.statusCode, 200, name);
    assertPreviewTruth(result.payload);
    if (name === 'automation-chain') {
      assert.match(result.payload.text, /originalField/);
    } else {
      assert.equal(result.payload.originalField, 'preserved', name);
    }
  }
  for (const args of loggedArgv()) {
    assert.equal(args.includes('--send'), false, JSON.stringify(args));
    assert.equal(args.includes('--write'), false, JSON.stringify(args));
    assert.equal(args.includes('--refresh'), false, JSON.stringify(args));
  }
});

test('every send query value is rejected before a Python runner starts', async () => {
  const beforeCount = invocationCount();
  for (const [name, endpoint, routes] of endpointCases) {
    for (const query of ['send', 'send=', 'send=0', 'send=false', 'send=1']) {
      const result = await invoke(routes, `${endpoint}?${query}`);
      assert.equal(result.statusCode, 400, `${name}?${query}`);
      assert.equal(result.payload.previewOnly, true);
      assert.equal(result.payload.sendRequested, true);
      assert.equal(result.payload.sendRejected, true);
      assert.equal(result.payload.sent, false);
      assert.equal(result.payload.deliveryOk, false);
      assert.equal(result.payload.delivery.status, 'REJECTED');
    }
  }
  assert.equal(invocationCount(), beforeCount);
});

test('runner failures still return the explicit preview delivery contract', async () => {
  process.env.QG_FAKE_PYTHON_FAIL = '1';
  try {
    for (const [name, endpoint, routes] of endpointCases) {
      const result = await invoke(routes, endpoint);
      assert.equal(result.statusCode, 500, name);
      assertPreviewTruth(result.payload);
      assert.equal(result.payload.ok, false, name);
    }
  } finally {
    process.env.QG_FAKE_PYTHON_FAIL = '0';
  }
});
