import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
const dashboardServerPath = path.join(repoRoot, 'Dashboard', 'dashboard_server.js');

function readDashboardServer() {
  return fs.readFileSync(dashboardServerPath, 'utf8');
}

test('daily autopilot missing evidence returns structured read-only envelope', () => {
  const text = readDashboardServer();

  assert.match(text, /function missingReadOnlyJsonPayload\(fileName, endpoint, error\)/);
  assert.match(text, /schema:\s*'quantgod\.read_only_json_missing\.v1'/);
  assert.match(text, /status:\s*'MISSING'/);
  assert.match(text, /message\.startsWith\('file not found:'\)/);
  assert.match(text, /sendJson\(res,\s*200,\s*missingReadOnlyJsonPayload\(fileName, endpoint, error\)\)/);
  assert.match(text, /requestUrl\.split\('\?'\)\[0\]\s*===\s*'\/api\/daily-autopilot'/);
  assert.match(text, /orderSendAllowed:\s*false/);
  assert.match(text, /livePresetMutationAllowed:\s*false/);
  assert.match(text, /mutatesMt5:\s*false/);
});
