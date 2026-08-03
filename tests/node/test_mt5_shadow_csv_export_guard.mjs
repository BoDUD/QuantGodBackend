import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const repo = process.cwd();
const ea = fs.readFileSync(
  path.join(repo, 'MQL5/Experts/QuantGod_MultiStrategy.mq5'),
  'utf8',
);

function section(startMarker, endMarker) {
  const start = ea.indexOf(startMarker);
  const end = ea.indexOf(endMarker, start + startMarker.length);
  assert.ok(start >= 0, `missing section start: ${startMarker}`);
  assert.ok(end > start, `missing section end: ${endMarker}`);
  return ea.slice(start, end);
}

test('Shadow CSV rebuild is first-run plus hourly instead of every dashboard refresh', () => {
  const due = section('void ExportShadowCsvsIfDue(', 'void InitializeSnapshots(');
  const dashboard = section('void ExportDashboard(', 'void ReconcileExistingPilotPositions(');

  assert.match(ea, /const int SHADOW_CSV_EXPORT_INTERVAL_SECONDS\s*=\s*3600\s*;/);
  assert.match(ea, /datetime g_lastShadowCsvExport\s*=\s*0\s*;/);
  assert.match(due, /firstExport\s*=\s*\(g_lastShadowCsvExport\s*<=\s*0\)/);
  assert.match(due, /now\s*<\s*g_lastShadowCsvExport/);
  assert.match(
    due,
    /\(now\s*-\s*g_lastShadowCsvExport\)\s*<\s*SHADOW_CSV_EXPORT_INTERVAL_SECONDS/,
  );
  assert.ok(
    due.indexOf('g_lastShadowCsvExport = now;') < due.indexOf('ExportShadowCsvs(snapshots'),
    'the interval must be claimed before the heavy export starts',
  );
  assert.match(dashboard, /ExportShadowCsvsIfDue\(snapshots, journal, closedTrades\)/);
  assert.doesNotMatch(dashboard, /ExportShadowCsvs\(snapshots, journal, closedTrades\)/);
  assert.ok(
    dashboard.indexOf('WriteTextFile("QuantGod_Dashboard.json", json);')
      < dashboard.indexOf('ExportShadowCsvsIfDue(snapshots, journal, closedTrades);'),
    'the normal dashboard snapshot must publish before an hourly heavy export',
  );
});

test('long Shadow CSV stages refresh only credible read-only runtime evidence', () => {
  const heartbeat = section(
    'void WriteKlineExporterRuntimeHeartbeat(',
    'int KlineExporterChunkDays(',
  );
  const csvExport = section('void ExportShadowCsvs(', 'void ExportShadowCsvsIfDue(');

  assert.match(heartbeat, /progressContext\s*=\s*"KLINE_EXPORT"/);
  assert.match(heartbeat, /progressContext\s*==\s*"SHADOW_CSV_EXPORT"/);
  assert.match(heartbeat, /quantgod\.mt5\.runtime_snapshot\.shadow_csv_export\.v1/);
  assert.match(
    heartbeat,
    /snapshotEligible\s*=\s*tickFresh && accountAuthorized && ShadowMode && ReadOnlyMode/,
  );
  assert.match(heartbeat, /"executionEnabled\\": false/);
  assert.match(heartbeat, /"readOnlyMode\\": true/);
  assert.match(heartbeat, /"orderSendAllowed\\": false/);
  assert.match(heartbeat, /"livePresetMutationAllowed\\": false/);
  assert.match(
    heartbeat,
    /if\(snapshotEligible\)\s+WriteTextFile\("QuantGod_MT5RuntimeSnapshot_"/,
  );

  assert.match(csvExport, /WriteShadowCsvRuntimeHeartbeat\("BUILD_AGGREGATES", completedStages, true\)/);
  assert.match(csvExport, /WriteShadowCsvRuntimeHeartbeat\("COMPLETE", completedStages, false\)/);
  assert.equal(
    (csvExport.match(/WriteShadowCsvRuntimeHeartbeat\(/g) || []).length,
    13,
    'each heavy stage plus start and completion must refresh progress evidence',
  );
  const artifacts = [
    ['QuantGod_TradeJournal.csv', 'AGGREGATES_READY', 'TRADE_JOURNAL'],
    ['QuantGod_LiveExecutionFeedbackHistory.jsonl', 'TRADE_JOURNAL', 'EXECUTION_FEEDBACK'],
    ['QuantGod_CloseHistory.csv', 'EXECUTION_FEEDBACK', 'CLOSE_HISTORY'],
    ['QuantGod_TradeOutcomeLabels.csv', 'CLOSE_HISTORY', 'TRADE_OUTCOME_LABELS'],
    ['QuantGod_TradeEventLinks.csv', 'TRADE_OUTCOME_LABELS', 'TRADE_EVENT_LINKS'],
    ['QuantGod_ManualAlphaLedger.csv', 'TRADE_EVENT_LINKS', 'MANUAL_ALPHA_LEDGER'],
    ['QuantGod_ShadowOutcomeLedger.csv', 'MANUAL_ALPHA_LEDGER', 'SHADOW_OUTCOME_LEDGER'],
    ['QuantGod_ShadowCandidateOutcomeLedger.csv', 'SHADOW_OUTCOME_LEDGER', 'SHADOW_CANDIDATE_LEDGER'],
    ['QuantGod_StrategyEvaluationReport.csv', 'SHADOW_CANDIDATE_LEDGER', 'STRATEGY_EVALUATION'],
    ['QuantGod_RegimeEvaluationReport.csv', 'STRATEGY_EVALUATION', 'REGIME_EVALUATION'],
    ['QuantGod_OpportunityLabels.csv', 'REGIME_EVALUATION', 'COMPLETE'],
  ];
  for (const [artifact, beforeStage, afterStage] of artifacts) {
    assert.match(csvExport, new RegExp(artifact.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    const before = csvExport.indexOf(`WriteShadowCsvRuntimeHeartbeat("${beforeStage}"`);
    const work = csvExport.indexOf(`WriteTextFile("${artifact}"`);
    const after = csvExport.indexOf(`WriteShadowCsvRuntimeHeartbeat("${afterStage}"`);
    assert.ok(
      before >= 0 && before < work && work < after,
      `${artifact} must be bracketed by credible runtime heartbeats`,
    );
  }
  const aggregateWork = csvExport.indexOf('BuildAggregates(snapshots, closedTrades');
  assert.ok(
    csvExport.indexOf('WriteShadowCsvRuntimeHeartbeat("BUILD_AGGREGATES"') < aggregateWork
      && aggregateWork < csvExport.indexOf('WriteShadowCsvRuntimeHeartbeat("AGGREGATES_READY"'),
    'aggregate construction must be bracketed by credible runtime heartbeats',
  );
  assert.doesNotMatch(
    csvExport,
    /\b(OrderSend|PositionOpen|PositionClose|PositionModify|CTrade|RunPilotExecutionLoop)\b/,
  );
});
