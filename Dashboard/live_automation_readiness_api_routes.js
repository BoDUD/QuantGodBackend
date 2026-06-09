const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
    Pragma: 'no-cache',
    Expires: '0',
  });
  res.end(JSON.stringify(payload, null, 2));
}

function sendError(res, statusCode, requestUrl, error) {
  sendJson(res, statusCode, {
    ok: false,
    endpoint: requestUrl,
    error: error && error.message ? error.message : String(error),
    safety: {
      readOnlyDataPlane: true,
      advisoryOnly: true,
      dryRunOnly: true,
      operatorApprovalRequired: true,
      executionLaneSpecRequired: true,
      autoPromotionToLiveAllowed: false,
      orderSendAllowed: false,
      closeAllowed: false,
      cancelAllowed: false,
      mt5OrderSendAllowed: false,
      hfmCryptoExecutionAllowed: false,
      copyTradeExecutionAllowed: false,
      mossExecutionAllowed: false,
      livePresetMutationAllowed: false,
      livePilotActivationAllowed: false,
      receiptWritesAllowed: false,
      receiptFilesWritten: false,
      autoDisableMutationAllowed: false,
      eaRequestReaderAllowed: false,
      eaRequestReaderEnabled: false,
      eaRequestFilesRead: false,
      eaRequestFilesConsumed: false,
      eaOrderSendAllowed: false,
      liveExecutionCutoverAllowed: false,
      writesMt5OrderRequest: false,
      credentialStorageAllowed: false,
    },
  });
}

function isLiveAutomationReadinessPath(requestUrl) {
  const pathname = String(requestUrl || '').split('?')[0];
  return pathname === '/api/live-automation' || pathname.startsWith('/api/live-automation/');
}

function runPythonJson(repoRoot, args, timeoutMs = 120000) {
  return new Promise((resolve) => {
    const pythonBin = process.env.QG_PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
    const script = path.join(repoRoot, 'tools', 'run_live_automation_readiness.py');
    if (!fs.existsSync(script)) {
      resolve({ ok: false, skipped: true, reason: 'script_not_found', script });
      return;
    }
    const child = spawn(pythonBin, [script, ...args], {
      cwd: repoRoot,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    let settled = false;
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      resolve({ ok: false, exitCode: -1, stdout, stderr: 'timeout' });
    }, timeoutMs);
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        const parsed = stdout.trim() ? JSON.parse(stdout) : {};
        resolve({ exitCode: code, stderr, ...parsed });
      } catch (error) {
        resolve({ ok: false, exitCode: code, stdout, stderr, parseError: error.message });
      }
    });
  });
}

function readJsonBody(req, limitBytes = 512 * 1024) {
  return new Promise((resolve) => {
    let body = '';
    let tooLarge = false;
    req.on('data', (chunk) => {
      if (tooLarge) return;
      body += chunk.toString();
      if (Buffer.byteLength(body, 'utf8') > limitBytes) {
        tooLarge = true;
        resolve({ ok: false, reason: 'BODY_TOO_LARGE', maxBytes: limitBytes });
      }
    });
    req.on('end', () => {
      if (tooLarge) return;
      const text = body.trim();
      if (!text) {
        resolve({ ok: true, payload: {}, raw: '' });
        return;
      }
      try {
        const parsed = JSON.parse(text);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          resolve({ ok: false, reason: 'BODY_MUST_BE_JSON_OBJECT' });
          return;
        }
        resolve({ ok: true, payload: parsed, raw: text });
      } catch (error) {
        resolve({ ok: false, reason: 'INVALID_JSON_BODY', error: error.message });
      }
    });
    req.on('error', (error) => {
      resolve({ ok: false, reason: 'BODY_READ_ERROR', error: error.message });
    });
  });
}

function statusCodeFor(payload) {
  if (!payload) return 500;
  if (payload.skipped || payload.parseError) return 500;
  if (payload.exitCode != null && payload.exitCode !== 0) return 500;
  return 200;
}

function truthyParam(value) {
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').toLowerCase());
}

function normalizeRuntimeScope(value) {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return '';
  if (['secondary', 'live16', 'hfm-live16', 'hfm_live16', 'crypto', 'hfm-crypto'].includes(text)) return 'secondary';
  if (['primary', 'live12', 'hfm-live12', 'hfm_live12', 'default'].includes(text)) return 'primary';
  return text;
}

function secondaryRuntimeDir(ctx = {}) {
  const candidates = [
    ctx.secondaryRuntimeDir,
    ctx.secondaryMt5FilesDir,
    process.env.QG_MT5_SECONDARY_FILES_DIR,
    process.env.QG_MT5_SECONDARY_ROOT ? path.join(process.env.QG_MT5_SECONDARY_ROOT, 'MQL5', 'Files') : '',
    process.env.QG_MT5_SECONDARY_WINE_PREFIX
      ? path.join(
          process.env.QG_MT5_SECONDARY_WINE_PREFIX,
          'drive_c',
          'Program Files',
          'MetaTrader 5',
          'MQL5',
          'Files',
        )
      : '',
    path.join(
      os.homedir(),
      'Library',
      'Application Support',
      'net.metaquotes.wine.metatrader5-live16',
      'drive_c',
      'Program Files',
      'MetaTrader 5',
      'MQL5',
      'Files',
    ),
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate)) || '';
}

function resolveLiveAutomationRuntimeScope(ctx = {}, url = new URL('/', 'http://127.0.0.1')) {
  const requestedScope =
    url.searchParams.get('scope') ||
    url.searchParams.get('accountScope') ||
    url.searchParams.get('account') ||
    process.env.QG_HFM_CRYPTO_SCOPE ||
    '';
  const scope = normalizeRuntimeScope(requestedScope) || 'primary';
  if (scope === 'secondary') {
    return {
      scope,
      requestedScope: requestedScope || 'secondary',
      accountLabel: 'HFM Live16 crypto CFD',
      runtimeDir: secondaryRuntimeDir(ctx),
    };
  }
  return {
    scope: 'primary',
    requestedScope: requestedScope || 'primary',
    accountLabel: 'HFM primary MT5',
    runtimeDir: ctx.defaultRuntimeDir || ctx.runtimeDir || process.env.QG_RUNTIME_DIR || process.env.QG_MT5_FILES_DIR || '',
  };
}

function runtimeScopeMeta(runtimeScope = {}) {
  const meta = {
    scope: runtimeScope.scope || 'primary',
    requestedScope: runtimeScope.requestedScope || runtimeScope.scope || 'primary',
    accountLabel: runtimeScope.accountLabel || '',
    runtimeDir: runtimeScope.runtimeDir || '',
  };
  if (runtimeScope.accountRuntimeDir) meta.accountRuntimeDir = runtimeScope.accountRuntimeDir;
  if (runtimeScope.fallbackReason) meta.fallbackReason = runtimeScope.fallbackReason;
  return meta;
}

function withRuntimeScope(payload, runtimeScope, extraMeta = {}) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return payload;
  return {
    ...payload,
    runtimeScope: runtimeScopeMeta(runtimeScope),
    ...extraMeta,
  };
}

function repoResearchRuntimeDir(ctx = {}) {
  if (ctx.researchRuntimeDir) return ctx.researchRuntimeDir;
  if (ctx.repoRuntimeDir) return ctx.repoRuntimeDir;
  if (ctx.repoRoot) return path.join(ctx.repoRoot, 'runtime');
  return '';
}

function hasAceResearchArtifacts(runtimeDir) {
  if (!runtimeDir) return false;
  const agentDir = path.join(runtimeDir, 'agent');
  return [
    'QuantGod_AceExecutionCandidatePack.json',
    'QuantGod_AceStrategyScout.json',
    'QuantGod_ChampionRetestReport.json',
    'QuantGod_TpSlOptimizerReport.json',
  ].some((name) => fs.existsSync(path.join(agentDir, name)));
}

function resolveAceResearchRuntimeScope(ctx = {}, runtimeScope = {}) {
  if (hasAceResearchArtifacts(runtimeScope.runtimeDir)) return runtimeScope;
  const researchRuntimeDir = repoResearchRuntimeDir(ctx);
  if (!hasAceResearchArtifacts(researchRuntimeDir)) return runtimeScope;
  return {
    scope: 'research-fallback',
    requestedScope: runtimeScope.requestedScope || runtimeScope.scope || 'primary',
    accountLabel: `${runtimeScope.accountLabel || 'HFM MT5'} + QuantGod research runtime`,
    runtimeDir: researchRuntimeDir,
    accountRuntimeDir: runtimeScope.runtimeDir || '',
    fallbackReason: 'ACE_RESEARCH_ARTIFACTS_MISSING_IN_ACCOUNT_RUNTIME',
  };
}

function runtimeScopeNotFoundPayload(requestUrl, runtimeScope) {
  return {
    ok: false,
    endpoint: requestUrl,
    status: 'LIVE_AUTOMATION_RUNTIME_SCOPE_NOT_FOUND',
    statusZh: '没有找到所选 HFM 账号的 MT5 Files 目录',
    nextRequiredActionZh: '确认 Live16/secondary MT5 已安装并配置 QG_MT5_SECONDARY_FILES_DIR 或 QG_MT5_SECONDARY_WINE_PREFIX。',
    runtimeScope,
    safety: {
      readOnlyDataPlane: true,
      advisoryOnly: true,
      dryRunOnly: true,
      orderSendAllowed: false,
      closeAllowed: false,
      cancelAllowed: false,
      mt5OrderSendAllowed: false,
      hfmCryptoExecutionAllowed: false,
      copyTradeExecutionAllowed: false,
      mossExecutionAllowed: false,
      livePresetMutationAllowed: false,
    },
  };
}

function buildArgs(runtimeDir, url) {
  const args = ['--runtime-dir', runtimeDir, 'build', '--write'];
  if (truthyParam(url.searchParams.get('refreshSources'))) args.push('--refresh-sources');
  const mossBacktestJson = url.searchParams.get('mossBacktestJson') || '';
  if (mossBacktestJson) args.push('--moss-backtest-json', mossBacktestJson);
  const hfmSimulationProfileJson = url.searchParams.get('hfmSimulationProfileJson') || url.searchParams.get('simulationProfileJson') || '';
  if (hfmSimulationProfileJson) args.push('--hfm-simulation-profile-json', hfmSimulationProfileJson);
  const hfmContractSpecJson = url.searchParams.get('hfmContractSpecJson') || url.searchParams.get('contractSpecJson') || '';
  if (hfmContractSpecJson) args.push('--hfm-contract-spec-json', hfmContractSpecJson);
  for (const root of url.searchParams.getAll('extraBasesRoot')) {
    if (root) args.push('--extra-bases-root', root);
  }
  return args;
}

async function handle(req, res, ctx) {
  const requestUrl = req.url || '';
  const url = new URL(requestUrl, 'http://127.0.0.1');
  const pathname = url.pathname;
  const runtimeScope = resolveLiveAutomationRuntimeScope(ctx, url);
  const runtimeDir = runtimeScope.runtimeDir;
  if (!runtimeDir) {
    sendJson(res, 404, runtimeScopeNotFoundPayload(requestUrl, runtimeScope));
    return;
  }
  const aceRuntimeScope = resolveAceResearchRuntimeScope(ctx, runtimeScope);
  const aceRuntimeDir = aceRuntimeScope.runtimeDir || runtimeDir;
  const aceRuntimeMeta = {
    aceResearchRuntimeScope: runtimeScopeMeta(aceRuntimeScope),
    aceEvidenceFallbackAvailable: aceRuntimeScope.scope === 'research-fallback',
  };
  const sendRuntimeJson = (payload) => {
    sendJson(res, statusCodeFor(payload), withRuntimeScope(payload, runtimeScope, aceRuntimeMeta));
  };
  const sendAceRuntimeJson = (payload) => {
    sendJson(res, statusCodeFor(payload), withRuntimeScope(payload, aceRuntimeScope));
  };
  if (req.method === 'GET' && (pathname === '/api/live-automation' || pathname === '/api/live-automation/status')) {
    const args = ['--runtime-dir', runtimeDir, 'status'];
    if (truthyParam(url.searchParams.get('refreshSources'))) {
      args[2] = 'build';
      args.push('--refresh-sources');
    }
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/readiness') {
    const args = ['--runtime-dir', runtimeDir, 'status'];
    if (truthyParam(url.searchParams.get('refreshSources'))) args.push('--refresh-sources');
    const mossBacktestJson = url.searchParams.get('mossBacktestJson') || '';
    if (mossBacktestJson) args.push('--moss-backtest-json', mossBacktestJson);
    const hfmSimulationProfileJson = url.searchParams.get('hfmSimulationProfileJson') || url.searchParams.get('simulationProfileJson') || '';
    if (hfmSimulationProfileJson) args.push('--hfm-simulation-profile-json', hfmSimulationProfileJson);
    const hfmContractSpecJson = url.searchParams.get('hfmContractSpecJson') || url.searchParams.get('contractSpecJson') || '';
    if (hfmContractSpecJson) args.push('--hfm-contract-spec-json', hfmContractSpecJson);
    for (const root of url.searchParams.getAll('extraBasesRoot')) {
      if (root) args.push('--extra-bases-root', root);
    }
    if (args.length > 3) args[2] = 'build';
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/review-packet') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'review-packet-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/approval-draft') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'approval-draft-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/approval-evidence') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'approval-evidence-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/dry-run-plan') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'dry-run-plan-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/execution-lane-spec') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'execution-lane-spec-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/dry-run-replay') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'dry-run-replay-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/runtime-preflight') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'runtime-preflight-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/order-request-contract') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'order-request-contract-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/pipeline') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'pipeline-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/adapter-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'adapter-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/evidence-intake') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'evidence-intake-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/promotion-candidates') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'promotion-candidates-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/promotion-controller') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'promotion-controller-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/champion-promotion-gate') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'champion-promotion-gate-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/champion-tester-forward-request') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'champion-tester-forward-request-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/champion-tester-run-gate') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'champion-tester-run-gate-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/champion-tester-lock-draft') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'champion-tester-lock-draft-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/adapter-sandbox') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'adapter-sandbox-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/adapter-contract-validator') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'adapter-contract-validator-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/orchestrator') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'orchestrator-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/adapter-harness') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'adapter-harness-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/live-pilot-activation-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'live-pilot-activation-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/receipt-reconciliation-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'receipt-reconciliation-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/ea-request-reader-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'ea-request-reader-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/live-execution-cutover-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'live-execution-cutover-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/live-execution-implementation-spec') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'live-execution-implementation-spec-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/live-execution-adapter-write-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'live-execution-adapter-write-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/ea-request-consumption-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'ea-request-consumption-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/broker-order-send-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'broker-order-send-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/live-execution-rollback-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'live-execution-rollback-review-status']);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/release-readiness-refresh') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-readiness-refresh-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/release-minimal-diff-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-minimal-diff-review-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/release-token-evidence-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-evidence-review-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/release-token-signoff-draft') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-draft-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/release-token-signoff-input-template') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-input-template-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/release-token-signoff-input-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-input-review-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/release-token-signoff-handoff') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-handoff-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/release-token-signoff-evidence-matrix') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-evidence-matrix-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/lane-selector') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'lane-selector'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-runtime-handoff') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'forex-live12-runtime-handoff-status'], 30000);
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-capacity-expansion-review') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-capacity-expansion-review-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-capacity-expansion-roadmap') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-capacity-expansion-roadmap-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-micro-expansion-review') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-micro-expansion-review-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-rsi-repair-plan') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-rsi-repair-plan-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-rsi-shadow-candidate') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-rsi-shadow-candidate-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-rsi-tester-request') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-rsi-tester-request-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-rsi-tester-run-gate') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-rsi-tester-run-gate-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-rsi-candidate-promotion-gate') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-rsi-candidate-promotion-gate-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/forex-live12-rsi-tester-lock-draft') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'forex-live12-rsi-tester-lock-draft-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/sim-target-execution-review-summary') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', runtimeDir, 'sim-target-execution-review-summary-status'],
      30000,
    );
    sendRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/ace-execution-candidate-pack') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', aceRuntimeDir, 'ace-execution-candidate-pack-status'],
      30000,
    );
    sendAceRuntimeJson(payload);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/live-automation/ace-upgrade-action-plan') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', aceRuntimeDir, 'ace-upgrade-action-plan-status'],
      30000,
    );
    sendAceRuntimeJson(payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/build') {
    const payload = await runPythonJson(ctx.repoRoot, buildArgs(runtimeDir, url));
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/review-packet/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'review-packet';
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/approval-draft/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'approval-draft';
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/approval-evidence/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'approval-evidence';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/dry-run-plan/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'dry-run-plan';
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/execution-lane-spec/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'execution-lane-spec';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/dry-run-replay/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'dry-run-replay';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/runtime-preflight/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'runtime-preflight';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/order-request-contract/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'order-request-contract';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/pipeline/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'pipeline';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 180000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/adapter-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'adapter-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 180000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/evidence-intake/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'evidence-intake';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 180000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/promotion-candidates/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'promotion-candidates';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 180000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/promotion-controller/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'promotion-controller';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 180000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/champion-promotion-gate/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'champion-promotion-gate', '--write'], 30000);
    sendJson(res, statusCodeFor(payload), withRuntimeScope(payload, runtimeScope));
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/champion-tester-forward-request/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'champion-tester-forward-request', '--write'], 30000);
    sendJson(res, statusCodeFor(payload), withRuntimeScope(payload, runtimeScope));
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/champion-tester-run-gate/build') {
    const args = ['--runtime-dir', runtimeDir, 'champion-tester-run-gate', '--write'];
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), withRuntimeScope(payload, runtimeScope));
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/champion-tester-lock-draft/build') {
    const args = ['--runtime-dir', runtimeDir, 'champion-tester-lock-draft', '--write'];
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), withRuntimeScope(payload, runtimeScope));
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/adapter-sandbox/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'adapter-sandbox';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 180000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/adapter-contract-validator/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'adapter-contract-validator';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 180000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/orchestrator/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'orchestrator';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 240000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/adapter-harness/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'adapter-harness';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 240000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/live-pilot-activation-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'live-pilot-activation-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 240000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/receipt-reconciliation-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'receipt-reconciliation-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const receiptJson = url.searchParams.get('receiptJson') || '';
    if (receiptJson) args.push('--receipt-json', receiptJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 240000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/ea-request-reader-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'ea-request-reader-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const receiptJson = url.searchParams.get('receiptJson') || '';
    if (receiptJson) args.push('--receipt-json', receiptJson);
    const eaSourcePath = url.searchParams.get('eaSourcePath') || '';
    if (eaSourcePath) args.push('--ea-source-path', eaSourcePath);
    const eaStatusJson = url.searchParams.get('eaStatusJson') || '';
    if (eaStatusJson) args.push('--ea-status-json', eaStatusJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 240000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/live-execution-cutover-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'live-execution-cutover-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const receiptJson = url.searchParams.get('receiptJson') || '';
    if (receiptJson) args.push('--receipt-json', receiptJson);
    const eaSourcePath = url.searchParams.get('eaSourcePath') || '';
    if (eaSourcePath) args.push('--ea-source-path', eaSourcePath);
    const eaStatusJson = url.searchParams.get('eaStatusJson') || '';
    if (eaStatusJson) args.push('--ea-status-json', eaStatusJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 300000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/live-execution-implementation-spec/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'live-execution-implementation-spec';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const receiptJson = url.searchParams.get('receiptJson') || '';
    if (receiptJson) args.push('--receipt-json', receiptJson);
    const eaSourcePath = url.searchParams.get('eaSourcePath') || '';
    if (eaSourcePath) args.push('--ea-source-path', eaSourcePath);
    const eaStatusJson = url.searchParams.get('eaStatusJson') || '';
    if (eaStatusJson) args.push('--ea-status-json', eaStatusJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 300000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/live-execution-adapter-write-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'live-execution-adapter-write-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const receiptJson = url.searchParams.get('receiptJson') || '';
    if (receiptJson) args.push('--receipt-json', receiptJson);
    const eaSourcePath = url.searchParams.get('eaSourcePath') || '';
    if (eaSourcePath) args.push('--ea-source-path', eaSourcePath);
    const eaStatusJson = url.searchParams.get('eaStatusJson') || '';
    if (eaStatusJson) args.push('--ea-status-json', eaStatusJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 300000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/ea-request-consumption-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'ea-request-consumption-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const receiptJson = url.searchParams.get('receiptJson') || '';
    if (receiptJson) args.push('--receipt-json', receiptJson);
    const eaSourcePath = url.searchParams.get('eaSourcePath') || '';
    if (eaSourcePath) args.push('--ea-source-path', eaSourcePath);
    const eaStatusJson = url.searchParams.get('eaStatusJson') || '';
    if (eaStatusJson) args.push('--ea-status-json', eaStatusJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 300000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/broker-order-send-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'broker-order-send-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const receiptJson = url.searchParams.get('receiptJson') || '';
    if (receiptJson) args.push('--receipt-json', receiptJson);
    const eaSourcePath = url.searchParams.get('eaSourcePath') || '';
    if (eaSourcePath) args.push('--ea-source-path', eaSourcePath);
    const eaStatusJson = url.searchParams.get('eaStatusJson') || '';
    if (eaStatusJson) args.push('--ea-status-json', eaStatusJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 300000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/live-execution-rollback-review/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'live-execution-rollback-review';
    const operatorApprovalJson = url.searchParams.get('operatorApprovalJson') || '';
    if (operatorApprovalJson) args.push('--operator-approval-json', operatorApprovalJson);
    const requestJson = url.searchParams.get('requestJson') || url.searchParams.get('adapterRequestJson') || '';
    if (requestJson) args.push('--request-json', requestJson);
    const receiptJson = url.searchParams.get('receiptJson') || '';
    if (receiptJson) args.push('--receipt-json', receiptJson);
    const eaSourcePath = url.searchParams.get('eaSourcePath') || '';
    if (eaSourcePath) args.push('--ea-source-path', eaSourcePath);
    const eaStatusJson = url.searchParams.get('eaStatusJson') || '';
    if (eaStatusJson) args.push('--ea-status-json', eaStatusJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 300000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/release-readiness-refresh/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'release-readiness-refresh';
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/release-minimal-diff-review/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-minimal-diff-review', '--write'], 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/release-token-evidence-review/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-evidence-review', '--write'], 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/release-token-signoff-draft/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-draft', '--write'], 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/release-token-signoff-input-template/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-input-template', '--write'], 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/release-token-signoff-input-review/build') {
    const args = ['--runtime-dir', runtimeDir, 'release-token-signoff-input-review', '--write'];
    const body = await readJsonBody(req);
    if (!body.ok) {
      sendJson(res, 400, {
        ok: false,
        status: body.reason,
        statusZh: 'release token 签收输入 body 必须是 512KB 内的 JSON object',
        bodyError: body,
      });
      return;
    }
    const requestBody = body.payload || {};
    const signoffJson =
      url.searchParams.get('signoffJson') ||
      requestBody.signoffJson ||
      (requestBody.schema === 'quantgod.release_token_signoff_input.v1' ? JSON.stringify(requestBody) : '') ||
      '';
    if (signoffJson) args.push('--signoff-json', signoffJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/release-token-signoff-handoff/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-handoff', '--write'], 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/release-token-signoff-evidence-matrix/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'release-token-signoff-evidence-matrix', '--write'], 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/lane-selector/build') {
    const args = buildArgs(runtimeDir, url);
    args[2] = 'lane-selector';
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const profitTargetJson = url.searchParams.get('profitTargetJson') || '';
    if (profitTargetJson) args.push('--profit-target-json', profitTargetJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-runtime-handoff/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-runtime-handoff', '--write'];
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-capacity-expansion-review/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-capacity-expansion-review', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-capacity-expansion-roadmap/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-capacity-expansion-roadmap', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-micro-expansion-review/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-micro-expansion-review', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-rsi-repair-plan/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-rsi-repair-plan', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-rsi-shadow-candidate/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-rsi-shadow-candidate', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-rsi-tester-request/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-rsi-tester-request', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-rsi-tester-run-gate/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-rsi-tester-run-gate', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-rsi-candidate-promotion-gate/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-rsi-candidate-promotion-gate', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/forex-live12-rsi-tester-lock-draft/build') {
    const args = ['--runtime-dir', runtimeDir, 'forex-live12-rsi-tester-lock-draft', '--write'];
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const primaryDashboardJson = url.searchParams.get('primaryDashboardJson') || '';
    if (primaryDashboardJson) args.push('--primary-dashboard-json', primaryDashboardJson);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/sim-target-execution-review-summary/build') {
    const args = ['--runtime-dir', runtimeDir, 'sim-target-execution-review-summary', '--write'];
    const targetUsd = url.searchParams.get('targetUsd') || '50';
    if (targetUsd) args.push('--target-usd', targetUsd);
    const requestedMaxTotalTrades = url.searchParams.get('requestedMaxTotalTrades') || '10';
    if (requestedMaxTotalTrades) args.push('--requested-max-total-trades', requestedMaxTotalTrades);
    const payload = await runPythonJson(ctx.repoRoot, args, 30000);
    sendJson(res, statusCodeFor(payload), payload);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/ace-execution-candidate-pack/build') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', aceRuntimeDir, 'ace-execution-candidate-pack', '--write'],
      30000,
    );
    sendJson(res, statusCodeFor(payload), withRuntimeScope(payload, aceRuntimeScope));
    return;
  }
  if (req.method === 'POST' && pathname === '/api/live-automation/ace-upgrade-action-plan/build') {
    const payload = await runPythonJson(
      ctx.repoRoot,
      ['--runtime-dir', aceRuntimeDir, 'ace-upgrade-action-plan', '--write'],
      30000,
    );
    sendJson(res, statusCodeFor(payload), withRuntimeScope(payload, aceRuntimeScope));
    return;
  }
  sendJson(res, 404, { ok: false, error: 'LIVE_AUTOMATION_READINESS_NOT_FOUND', endpoint: pathname });
}

module.exports = {
  handle,
  isLiveAutomationReadinessPath,
  resolveLiveAutomationRuntimeScope,
  resolveAceResearchRuntimeScope,
  runtimeScopeMeta,
  sendError,
};
