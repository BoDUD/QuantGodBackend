import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const ROOT = process.cwd();
const FILES = [
  'tools/run_auto_execution_policy.py',
  'tools/auto_execution_policy/schema.py',
  'tools/auto_execution_policy/policy_engine.py',
  'tools/auto_execution_policy/telegram_text.py',
];

function read(path) {
  return readFileSync(join(ROOT, path), 'utf8');
}

test('auto execution policy does not contain direct MT5 execution primitives', () => {
  const forbidden = [
    /OrderSend\s*\(/,
    /OrderSendAsync\s*\(/,
    /PositionClose\s*\(/,
    /CTrade\b/,
    /TRADE_ACTION_DEAL/,
    /FileWrite\s*\([^\n]*OrderRequest/i,
    /LivePreset\s*=\s*true/i,
  ];
  for (const file of FILES) {
    const text = read(file);
    for (const pattern of forbidden) {
      assert.equal(pattern.test(text), false, `${file} contains forbidden execution primitive ${pattern}`);
    }
  }
});

test('auto execution policy keeps execution flags false in schema', () => {
  const text = read('tools/auto_execution_policy/schema.py');
  for (const key of ['orderSendAllowed', 'closeAllowed', 'cancelAllowed', 'brokerExecutionAllowed', 'writesMt5OrderRequest']) {
    assert.match(text, new RegExp(`"${key}"\\s*:\\s*False`), `${key} must be explicitly false`);
  }
});

test('telegram text is a compact Shadow observation without execution hints', () => {
  const text = read('tools/auto_execution_policy/telegram_text.py');
  assert.match(text, /策略观察/);
  assert.match(text, /Shadow/);
  assert.doesNotMatch(text, /自动执行策略调参|建议仓位|机会入场|出场参数/);
});
