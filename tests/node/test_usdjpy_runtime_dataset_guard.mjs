import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const repo = process.cwd();

function read(rel) {
  return fs.readFileSync(path.join(repo, rel), 'utf8');
}

test('USDJPY evolution core remains read-only and focus-only', () => {
  const cli = read('tools/run_usdjpy_runtime_dataset.py');
  const schema = read('tools/usdjpy_runtime_dataset/schema.py');
  const replay = read('tools/usdjpy_runtime_dataset/replay.py');
  assert.match(cli, /USDJPY\/USDJPYc/);
  assert.doesNotMatch(cli, /USDJPYc,EURUSDc,XAUUSDc/);
  assert.match(schema, /"orderSendAllowed": False/);
  assert.match(schema, /"livePresetMutationAllowed": False/);
  assert.match(schema, /"autoApplyAllowed": "shadow_only"/);
  assert.match(schema, /"requiresAutonomousGovernance": True/);
  assert.match(schema, /"operatorApprovalRequired": True/);
  assert.match(schema, /"unattendedLiveExpansionAllowed": False/);
  assert.match(schema, /"liveExpansionAllowed": False/);
  assert.match(schema, /"completedByAgent": True/);
  assert.doesNotMatch(schema, /requiresManualReview|manualReview|readyForReview/);
  assert.match(replay, /unitPolicy/);
  assert.match(replay, /scenarioComparisons/);
  assert.doesNotMatch(replay, /profit_r\s*[*/+-]\s*profit_usc|profit_usc\s*[*/+-]\s*mfe_r|profit\s*\*\s*1\.8/);
});

test('USDJPY evolution API routes are exposed through strategy lab only', () => {
  const routes = read('Dashboard/usdjpy_strategy_lab_api_routes.js');
  assert.match(routes, /\/api\/usdjpy-strategy-lab\/evolution\/status/);
  assert.match(routes, /run_usdjpy_runtime_dataset\.py/);
  assert.doesNotMatch(routes, /\/api\/trade|OrderSend|writesMt5OrderRequest: true/);
});
