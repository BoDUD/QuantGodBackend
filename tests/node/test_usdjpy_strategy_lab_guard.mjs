import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const repoRoot = path.resolve(process.cwd());
const files = [
  'tools/usdjpy_strategy_lab/schema.py',
  'tools/usdjpy_strategy_lab/strategy_catalog.py',
  'tools/usdjpy_strategy_lab/strategy_signals.py',
  'tools/usdjpy_strategy_lab/risk_governor.py',
  'tools/usdjpy_strategy_lab/backtest_plan_builder.py',
  'tools/usdjpy_strategy_lab/backtest_importer.py',
  'tools/usdjpy_strategy_lab/policy_builder.py',
  'tools/usdjpy_strategy_lab/dry_run_bridge.py',
  'tools/run_usdjpy_strategy_lab.py',
  'Dashboard/usdjpy_strategy_lab_api_routes.js',
  'tools/usdjpy_strategy_lab/QuantGodUSDJPYPolicyDryRun.mq5',
];

const forbidden = /\b(OrderSend|OrderSendAsync|PositionClose|OrderModify|TRADE_ACTION_DEAL|CTrade\s*\(|MT5OrderRequest|writesMt5OrderRequest\s*[:=]\s*true|telegramCommandExecutionAllowed\s*[:=]\s*true|livePresetMutationAllowed\s*[:=]\s*true)\b/;

test('USDJPY strategy lab files exist', () => {
  for (const file of files) {
    assert.ok(fs.existsSync(path.join(repoRoot, file)), `${file} should exist`);
  }
});

test('USDJPY strategy lab is focus-only and dry-run only', () => {
  const schema = fs.readFileSync(path.join(repoRoot, 'tools/usdjpy_strategy_lab/schema.py'), 'utf8');
  assert.match(schema, /FOCUS_SYMBOL\s*=\s*["']USDJPYc["']/);
  assert.match(schema, /dryRunOnly["']?\s*:\s*True/);
  assert.match(schema, /orderSendAllowed["']?\s*:\s*False/);
  assert.match(schema, /livePresetMutationAllowed["']?\s*:\s*False/);
});

test('USDJPY strategy lab does not contain execution primitives', () => {
  for (const file of files) {
    const text = fs.readFileSync(path.join(repoRoot, file), 'utf8');
    assert.doesNotMatch(text, forbidden, `${file} must not contain execution primitives`);
  }
});

test('USDJPY API route exposes only /api/usdjpy-strategy-lab', () => {
  const route = fs.readFileSync(path.join(repoRoot, 'Dashboard/usdjpy_strategy_lab_api_routes.js'), 'utf8');
  assert.match(route, /\/api\/usdjpy-strategy-lab\/status/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/catalog/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/signals/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/candidate-policy/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/backtest-plan/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/imported-backtests/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/import-backtest/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/risk-check/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/telegram-text/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/live-loop/);
  assert.match(route, /\/api\/usdjpy-strategy-lab\/run/);
});

test('USDJPY policy separates shadow winner from live-eligible route', () => {
  const policy = fs.readFileSync(path.join(repoRoot, 'tools/usdjpy_strategy_lab/policy_builder.py'), 'utf8');
  assert.match(policy, /FASTLANE_PASS_STATES/);
  assert.match(policy, /"FAST"/);
  assert.match(policy, /"EA_DASHBOARD_OK"/);
  assert.doesNotMatch(policy, /QuantGod_AutoExecutionPolicy\.json/);
  assert.match(policy, /topShadowPolicy/);
  assert.match(policy, /topLiveEligiblePolicy/);
  assert.match(policy, /LIVE_ELIGIBLE_STRATEG(?:Y|IES)\s*=/);
  assert.match(policy, /RSI_Reversal/);
  if (/LIVE_ELIGIBLE_STRATEGIES\s*=/.test(policy)) {
    const liveEligibleMatch = policy.match(/LIVE_ELIGIBLE_STRATEGIES\s*=\s*\{([^}]+)\}/);
    assert.ok(liveEligibleMatch, 'LIVE_ELIGIBLE_STRATEGIES must be a literal RSI-only set');
    assert.match(liveEligibleMatch[1], /RSI_Reversal/);
    assert.doesNotMatch(liveEligibleMatch[1], /MA_Cross/);
    assert.doesNotMatch(liveEligibleMatch[1], /USDJPY_NIGHT_REVERSION_SAFE/);
    assert.match(policy, /not in LIVE_ELIGIBLE_STRATEGIES/);
    assert.match(policy, /strategy in LIVE_ELIGIBLE_STRATEGIES/);
  } else {
    assert.match(policy, /LIVE_ELIGIBLE_STRATEGY\s*=\s*["']RSI_Reversal["']/);
  }
  assert.match(policy, /LIVE_ELIGIBLE_DIRECTION\s*=\s*["']LONG["']/);
});
