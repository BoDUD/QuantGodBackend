import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
const bridgeDir = path.join(repoRoot, 'tools', 'mt5_runtime_bridge');
const monitorPath = path.join(repoRoot, 'tools', 'run_mt5_ai_telegram_monitor.py');
const dashboardServerPath = path.join(repoRoot, 'Dashboard', 'dashboard_server.js');

function readIfExists(filePath) {
  return fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : '';
}

test('MT5 runtime bridge files exist', () => {
  assert.ok(fs.existsSync(path.join(bridgeDir, 'reader.py')));
  assert.ok(fs.existsSync(path.join(bridgeDir, 'schema.py')));
  assert.ok(fs.existsSync(path.join(repoRoot, 'tools', 'run_mt5_runtime_bridge.py')));
});

test('runtime bridge keeps trading execution disabled', () => {
  const combined = ['reader.py', 'schema.py', 'freshness.py']
    .map((name) => readIfExists(path.join(bridgeDir, name)))
    .join('\n');
  assert.match(combined, /orderSendAllowed"?: False/);
  assert.match(combined, /telegramCommandExecutionAllowed"?: False/);
  assert.doesNotMatch(combined, /\.order_send\s*\(/);
  assert.doesNotMatch(combined, /OrderSend\s*\(/);
});

test('MT5 AI Telegram monitor reports runtime freshness fields when patched', () => {
  const text = readIfExists(monitorPath);
  assert.match(text, /runtimeFresh/);
  assert.match(text, /runtimeAgeSeconds/);
  assert.match(text, /fallback/);
});

test('MT5 symbol registry exposes frontend symbols alias without MT5 mutation', () => {
  const text = readIfExists(dashboardServerPath);
  assert.match(text, /mt5SymbolRegistryEndpoints = new Set\(\['registry', 'resolve', 'symbols'\]\)/);
  assert.match(text, /endpoint === 'symbols' \? 'registry' : endpoint/);
  assert.match(text, /\/api\/mt5-symbol-registry\/symbols/);
  assert.match(text, /symbolSelectAllowed:\s*false/);
  assert.match(text, /orderSendAllowed:\s*false/);
  assert.doesNotMatch(text, /symbol_select\s*\(/i);
});

test('dashboard registers only the MT5 read-only lane', () => {
  const text = readIfExists(dashboardServerPath);

  assert.match(text, /mt5ReadonlyEndpoints = new Set\(\['status', 'account', 'positions'/);
  assert.match(text, /requestUrl[^\n]+=== '\/api\/mt5-readonly'/);
  assert.doesNotMatch(text, /\/api\/mt5-trading/);
  assert.doesNotMatch(text, /mt5TradingClientScript|mt5TradingEndpoints|handleMt5Trading/);
  assert.doesNotMatch(text, /requestUrl[^\n]+=== '\/api\/mt5'/);
  assert.doesNotMatch(text, /\/api\/mt5\/order\//);
});
