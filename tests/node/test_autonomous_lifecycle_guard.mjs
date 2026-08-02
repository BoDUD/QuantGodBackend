import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const repo = process.cwd();
const readableSourceRoots = [
  'tools/daily_autopilot_v2',
  'tools/news_gate',
  'tools/autonomous_lifecycle',
  'tools/usdjpy_bar_replay',
  'tools/usdjpy_autonomous_agent',
  'tools/usdjpy_walk_forward',
  'tools/strategy_json',
  'tools/strategy_ga',
];

function read(rel) {
  return fs.readFileSync(path.join(repo, rel), 'utf8');
}

function listPythonFiles(relDir) {
  const dir = path.join(repo, relDir);
  return fs.readdirSync(dir)
    .filter((name) => name.endsWith('.py'))
    .map((name) => path.join(relDir, name));
}

test('autonomous lifecycle keeps the forex safety model explicit', () => {
  const lifecycle = read('tools/autonomous_lifecycle/lifecycle.py');
  const mt5 = read('tools/autonomous_lifecycle/mt5_shadow_lane.py');
  const cent = read('tools/autonomous_lifecycle/cent_account_rules.py');
  const daily = read('tools/daily_autopilot_v2/report.py');
  const orchestrator = read('tools/daily_autopilot_v2/orchestrator.py');

  for (const marker of [
    '实盘要窄，模拟要宽，升降级要快，回滚要硬',
    'USDJPYc',
    'RSI_Reversal',
    'MT5_SHADOW',
    'externalMarketRealMoneyAllowed',
    'liveMutationAllowed',
    'operatorApprovalRequired',
    'unattendedLiveExpansionAllowed',
    'liveExpansionAllowed',
  ]) {
    assert.match(lifecycle + mt5 + daily + orchestrator, new RegExp(marker));
  }
  assert.match(cent, /QG_AUTO_MAX_LOT/);
  assert.match(cent, /2\.0/);
  assert.doesNotMatch(
    lifecycle + mt5 + cent + daily,
    /\b(TRADE_ACTION_DEAL|PositionClose|OrderSendAsync|CTrade)\b|OrderSend\s*\(/
  );
  assert.doesNotMatch(lifecycle + mt5 + daily, /"operatorApprovalRequired": False/);
  assert.doesNotMatch(lifecycle + mt5 + daily, /"unattendedLiveExpansionAllowed": True/);
  assert.doesNotMatch(lifecycle + mt5 + daily, /"liveExpansionAllowed": True/);
});

test('strategy policy no longer uses manual promotion language', () => {
  const policy = read('tools/usdjpy_strategy_lab/policy_builder.py');
  const patch = read('tools/usdjpy_autonomous_agent/config_patch.py');
  const state = read('tools/usdjpy_autonomous_agent/agent_state.py');

  assert.doesNotMatch(policy, /manualPromotionRequired["']?\s*:\s*True/);
  assert.match(patch, /patchWritable/);
  assert.doesNotMatch(patch, /patchAllowed/);
  assert.match(patch, /liveMutationAllowed/);
  assert.match(state, /executionStage/);
});

test('API exposes lifecycle and lane endpoints', () => {
  const routes = read('Dashboard/usdjpy_strategy_lab_api_routes.js');
  for (const endpoint of [
    '/api/usdjpy-strategy-lab/autonomous-agent/lifecycle',
    '/api/usdjpy-strategy-lab/autonomous-agent/lanes',
    '/api/usdjpy-strategy-lab/autonomous-agent/mt5-shadow',
    '/api/usdjpy-strategy-lab/autonomous-agent/ea-repro',
    '/api/usdjpy-strategy-lab/autonomous-agent/daily-autopilot-v2',
    '/api/usdjpy-strategy-lab/autonomous-agent/daily-autopilot-v2/run',
    '/api/usdjpy-strategy-lab/autonomous-agent/daily-autopilot-v2/telegram-text',
    '/api/usdjpy-strategy-lab/daily-todo',
    '/api/usdjpy-strategy-lab/daily-todo/run',
    '/api/usdjpy-strategy-lab/daily-todo/telegram-text',
    '/api/usdjpy-strategy-lab/daily-review',
    '/api/usdjpy-strategy-lab/daily-review/run',
    '/api/usdjpy-strategy-lab/daily-review/telegram-text',
  ]) {
    assert.match(routes, new RegExp(endpoint.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});

test('daily autopilot v2 keeps Chinese autonomous reporting and push-only safety', () => {
  const runner = read('tools/run_daily_autopilot_v2.py');
  const report = read('tools/daily_autopilot_v2/report.py');
  const orchestrator = read('tools/daily_autopilot_v2/orchestrator.py');
  const text = read('tools/daily_autopilot_v2/telegram_text.py');
  const template = read('tools/telegram_digest.py');
  const routes = read('Dashboard/usdjpy_strategy_lab_api_routes.js');

  for (const marker of ['今日自动作战计划', '今日自动复盘', 'MT5 模拟车道']) {
    assert.match(report + text, new RegExp(marker));
  }
  for (const marker of [
    'dailyTodo',
    'dailyReview',
    'completedByAgent',
    'autoAppliedByAgent',
    'requiresAutonomousGovernance',
    'strategyJsonTodo',
    'gaEvolutionTodo',
    'telegramGatewayTodo',
    'historyProductionStatus',
    'QuantGod_USDJPYHistoryProductionStatus.json',
    'COMPLETED_BY_AGENT',
  ]) {
    assert.match(report + orchestrator, new RegExp(marker));
  }
  for (const marker of [
    'run-cycle',
    'RUN_GA_GENERATION',
    'RUN_PARITY_AND_EXECUTION_FEEDBACK',
    'QuantGod_DailyAutopilotV2RunLatest.json',
    'QuantGod_DailyAutopilotV2RunLedger.jsonl',
  ]) {
    assert.match(runner + orchestrator + routes, new RegExp(marker));
  }
  assert.match(routes, /run-cycle', '--write'/);
  for (const marker of ['Strategy JSON', 'GA Evolution', 'Telegram Gateway', '独立 Telegram Gateway 已接入']) {
    assert.match(report, new RegExp(marker));
  }
  for (const marker of ['生产级 PASS', 'promotionGateStatus']) {
    assert.match(runner + report, new RegExp(marker));
  }
  for (const marker of ['每日状态', '结论：', '关键：', '下一步：', '永久 Shadow', '无执行通道']) {
    assert.match(text + template, new RegExp(marker));
  }
  for (const marker of ['实盘车道', '建议阶段仓位', 'Live 阶段', '实盘执行质量']) {
    assert.doesNotMatch(text, new RegExp(marker));
  }
  assert.doesNotMatch(report, /requiresManualReview|manualReview|readyForReview/);
  assert.match(runner, /dispatch_cli_text/);
  assert.doesNotMatch(runner, /(?<!cli_)dispatch_text\s*\(/);
  assert.match(runner, /telegramGateway/);
  assert.match(read('tools/usdjpy_evidence_os/telegram_gateway.py'), /QG_TELEGRAM_COMMANDS_ALLOWED/);
  assert.doesNotMatch(runner + report + text, /privateKeyAllowed\s*["']?\s*:\s*true/);
});

test('autonomous lifecycle Python sources stay readable and multi-line', () => {
  const files = readableSourceRoots.flatMap(listPythonFiles);
  for (const file of files) {
    const source = read(file);
    const lines = source.split(/\r?\n/);
    const isInit = file.endsWith('__init__.py');
    if (!isInit) {
      assert.ok(lines.length >= 20, `${file} should stay readable and multi-line`);
    }
    lines.forEach((line, index) => {
      assert.ok(line.length <= 160, `${file}:${index + 1} should not exceed 160 characters`);
    });
    assert.doesNotMatch(source, /^\s*from .* import .*def /m, `${file} looks compressed`);
    assert.doesNotMatch(source, /^\s*import .*def /m, `${file} looks compressed`);
    assert.doesNotMatch(source, /;\s*(def|class)\s+/m, `${file} contains compressed definitions`);
  }
});
