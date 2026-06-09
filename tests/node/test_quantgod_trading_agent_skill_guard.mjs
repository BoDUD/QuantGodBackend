import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const repo = process.cwd();
const skillDir = path.join(repo, '.codex', 'skills', 'quantgod-trading-agent');

function read(rel) {
  return fs.readFileSync(path.join(skillDir, rel), 'utf8');
}

test('QuantGod trading-agent skill is present and safe', () => {
  const skill = read('SKILL.md');
  const currentSystem = read(path.join('references', 'current-system.md'));
  const openaiYaml = read(path.join('agents', 'openai.yaml'));
  const combined = `${skill}\n${currentSystem}\n${openaiYaml}`;

  for (const marker of [
    'name: quantgod-trading-agent',
    'Plain-language Strategy Factory',
    'Entry-latency attribution',
    'centSamplingGate',
    'PilotStartupEntryGuardMode',
    'personality_lock.py',
    'run_hyperliquid_shadow_lane.py',
    '不授权钱包',
    '$quantgod-trading-agent',
  ]) {
    assert.match(combined, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  assert.doesNotMatch(combined, /orderSendAllowed\s*:\s*true/i);
  assert.doesNotMatch(combined, /walletAuthorizationAllowed\s*:\s*true/i);
  assert.doesNotMatch(combined, /privateKeyAllowed\s*:\s*true/i);
  assert.doesNotMatch(combined, /credentialStorageAllowed\s*:\s*true/i);
});
