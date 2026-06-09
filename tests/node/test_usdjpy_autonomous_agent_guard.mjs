import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const repo = process.cwd();

function read(rel) {
  return fs.readFileSync(path.join(repo, rel), 'utf8');
}

test('autonomous agent keeps hard safety boundaries', () => {
  const schema = read('tools/usdjpy_autonomous_agent/schema.py');
  const patch = read('tools/usdjpy_autonomous_agent/config_patch.py');
  const rollback = read('tools/usdjpy_autonomous_agent/rollback.py');
  const cli = read('tools/run_usdjpy_autonomous_agent.py');

  for (const text of [schema, patch, rollback, cli]) {
    assert.doesNotMatch(text, /OrderSend|TRADE_ACTION_DEAL|PositionClose|OrderSendAsync|CTrade/);
    assert.doesNotMatch(text, /telegramCommandExecutionAllowed["']?\s*:\s*True/);
    assert.doesNotMatch(text, /livePresetMutationAllowed["']?\s*:\s*True/);
  }
  assert.match(schema, /"requiresAutonomousGovernance": True/);
  assert.match(schema, /"autoApplyAllowed": "stage_gated"/);
  assert.match(schema, /"operatorApprovalRequired": False/);
  assert.match(schema, /"unattendedLiveExpansionAllowed": True/);
  assert.match(schema, /"patchWritable": True/);
  assert.match(schema, /"liveMutationAllowed": False/);
  assert.match(schema, /"deepSeekCanApproveLive": False/);
  assert.match(schema, /"externalMarketRealMoneyAllowed": False/);
  assert.match(schema, /"hfmCryptoExecutionAllowed": False/);
  assert.match(patch, /patchWritable/);
  assert.match(patch, /unattendedLiveExpansionAllowed/);
  assert.doesNotMatch(patch, /patchAllowed/);
  assert.match(patch, /executionStage/);
  assert.match(patch, /liveMutationAllowed/);
  assert.match(patch, /stageMaxLot/);
  assert.match(patch, /QuantGod_AutonomousConfigPatch_EA\.txt/);
  assert.match(patch, /newsHardBypassAllowed/);
  assert.match(patch, /runtimeFreshnessBypassAllowed/);
  assert.match(patch, /fastlaneBypassAllowed/);
  assert.match(rollback, /consecutiveLosses/);
  assert.match(rollback, /dailyLossR/);
});

test('MT5 EA reads autonomous config patch through a narrow runtime adapter', () => {
  const ea = read('MQL5/Experts/QuantGod_MultiStrategy.mq5');

  for (const marker of [
    'EnableAutonomousConfigPatchRuntimeAdapter',
    'AutonomousConfigPatchRuntimeFile',
    'QuantGod_AutonomousConfigPatch_EA.txt',
    'QuantGod_AutonomousConfigPatchEAStatus.json',
    'appliedPatchId',
    'activeParameters',
    'rejectedFields',
    'operatorApprovalRequired',
    'unattendedLiveExpansionAllowed',
    'AutonomousPatchEffectiveRsiBuyBand',
    'AutonomousPatchEffectiveRsiCrossbackThreshold',
    'AutonomousPatchEffectiveStageLotCap',
    'g_autonomousPatchBreakevenDelayR',
    'g_autonomousPatchTrailStartR',
    'g_autonomousPatchMfeGivebackPct',
  ]) {
    assert.match(ea, new RegExp(marker));
  }
  assert.match(ea, /symbol != "USDJPYc"/);
  assert.match(ea, /strategy != "RSI_Reversal"/);
  assert.match(ea, /direction != "LONG"/);
  assert.match(ea, /newsBypassAllowed \|\| runtimeBypassAllowed \|\| fastlaneBypassAllowed/);
  assert.match(ea, /maxLot <= 0\.0 \|\| maxLot > 2\.0/);
  assert.match(ea, /stageMaxLot < 0\.0 \|\| stageMaxLot > 2\.0/);
  assert.match(ea, /PATCH_REJECTED/);
  assert.match(ea, /PATCH_ACTIVE/);
});

test('strategy lab exposes walk-forward and autonomous endpoints only', () => {
  const routes = read('Dashboard/usdjpy_strategy_lab_api_routes.js');
  for (const marker of [
    '/api/usdjpy-strategy-lab/walk-forward/status',
    '/api/usdjpy-strategy-lab/walk-forward/build',
    '/api/usdjpy-strategy-lab/autonomous-agent/state',
    '/api/usdjpy-strategy-lab/autonomous-agent/run',
    '/api/usdjpy-strategy-lab/autonomous-agent/lifecycle',
    '/api/usdjpy-strategy-lab/autonomous-agent/lanes',
    'run_usdjpy_walk_forward.py',
    'run_usdjpy_autonomous_agent.py',
    'resolveHfmCryptoRuntimeScope',
    '--hfm-crypto-runtime-dir',
    'HFM Live16 crypto CFD',
  ]) {
    assert.match(routes, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(routes, /\/api\/trade|writesMt5OrderRequest:\s*true|OrderSend/);
});
