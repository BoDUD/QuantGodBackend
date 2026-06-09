import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';

const root = process.cwd();
const files = [
  'tools/ai_analysis/providers/base.py',
  'tools/ai_analysis/providers/deepseek_provider.py',
  'tools/ai_analysis/providers/mock_provider.py',
  'tools/ai_analysis/providers/openrouter_provider.py',
  'tools/ai_analysis/providers/router.py',
  'tools/run_ai_provider.py',
];

function read(path) {
  return readFileSync(join(root, path), 'utf8');
}

test('AI provider router does not introduce trading or receiver APIs', () => {
  const code = files.map(read).join('\n');
  const forbiddenCodePatterns = [
    /\.o\s*r\s*d\s*e\s*r\s*_\s*s\s*e\s*n\s*d\s*\(/i,
    /T\s*R\s*A\s*D\s*E\s*_\s*A\s*C\s*T\s*I\s*O\s*N\s*_\s*D\s*E\s*A\s*L/i,
    /M\s*e\s*t\s*a\s*T\s*r\s*a\s*d\s*e\s*r\s*5\s*\.\s*o\s*r\s*d\s*e\s*r/i,
    /p\s*l\s*a\s*c\s*e\s*_\s*o\s*r\s*d\s*e\s*r\s*\(/i,
    /c\s*a\s*n\s*c\s*e\s*l\s*_\s*o\s*r\s*d\s*e\s*r\s*\(/i,
    /s\s*e\s*t\s*W\s*e\s*b\s*h\s*o\s*o\s*k\s*\(/i,
    /g\s*e\s*t\s*U\s*p\s*d\s*a\s*t\s*e\s*s\s*\(/i,
  ];
  for (const pattern of forbiddenCodePatterns) {
    assert.equal(pattern.test(code), false, `forbidden pattern found: ${pattern}`);
  }
});

test('AI provider router exposes required false safety flags', () => {
  const code = read('tools/ai_analysis/providers/base.py');
  const requiredFalseFlags = [
    'orderSendAllowed',
    'closeAllowed',
    'cancelAllowed',
    'credentialStorageAllowed',
    'livePresetMutationAllowed',
    'canOverrideKillSwitch',
    'telegramCommandExecutionAllowed',
    'telegramWebhookReceiverAllowed',
    'webhookReceiverAllowed',
    'emailDeliveryAllowed',
    'walletIntegrationAllowed',
    'externalMarketOrderAllowed',
  ];
  for (const flag of requiredFalseFlags) {
    assert.match(code, new RegExp(`"${flag}"\\s*:\\s*False`), `${flag} must be false in provider safety payload`);
  }
});

test('AI provider env example contains no secret value', () => {
  const example = read('.env.ai.local.example');
  assert.match(example, /QG_AI_API_KEY=\s*$/m);
  assert.doesNotMatch(example, /(sk-|ds-|or-)[A-Za-z0-9_-]{12,}/);
  assert.match(example, /QG_ORDER_SEND_ALLOWED=0/);
  assert.match(example, /QG_TELEGRAM_COMMANDS_ALLOWED=0/);
});
