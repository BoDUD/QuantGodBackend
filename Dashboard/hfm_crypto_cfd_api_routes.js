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
      readOnly: true,
      shadowOnly: true,
      orderSendAllowed: false,
      closeAllowed: false,
      cancelAllowed: false,
      mt5OrderSendAllowed: false,
      mossExecutionAllowed: false,
      livePresetMutationAllowed: false,
      externalMarketRemoved: true,
    },
  });
}

function isHFMCryptoCfdPath(requestUrl) {
  const pathname = String(requestUrl || '').split('?')[0];
  return pathname === '/api/hfm-crypto' || pathname.startsWith('/api/hfm-crypto/');
}

function runPythonJson(repoRoot, args, timeoutMs = 120000) {
  return new Promise((resolve) => {
    const pythonBin = process.env.QG_PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
    const script = path.join(repoRoot, 'tools', 'run_hfm_crypto_cfd.py');
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

function statusCodeFor(payload) {
  if (!payload) return 500;
  if (payload.skipped || payload.parseError) return 500;
  if (payload.exitCode != null && payload.exitCode !== 0) return 500;
  return 200;
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

function resolveHfmCryptoRuntimeScope(ctx = {}, url = new URL('/', 'http://127.0.0.1')) {
  const requestedScope =
    url.searchParams.get('scope') ||
    url.searchParams.get('accountScope') ||
    url.searchParams.get('account') ||
    process.env.QG_HFM_CRYPTO_SCOPE ||
    '';
  const scope = normalizeRuntimeScope(requestedScope) || 'secondary';
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
  return {
    scope: runtimeScope.scope || 'primary',
    requestedScope: runtimeScope.requestedScope || runtimeScope.scope || 'primary',
    accountLabel: runtimeScope.accountLabel || '',
    runtimeDir: runtimeScope.runtimeDir || '',
  };
}

function withRuntimeScope(payload, runtimeScope) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return payload;
  return {
    ...payload,
    runtimeScope: runtimeScopeMeta(runtimeScope),
  };
}

function sendScopedJson(res, payload, runtimeScope, transform = null) {
  const body = typeof transform === 'function' ? transform(payload) : payload;
  sendJson(res, statusCodeFor(payload), withRuntimeScope(body, runtimeScope));
}

function runtimeScopeNotFoundPayload(requestUrl, runtimeScope) {
  return {
    ok: false,
    endpoint: requestUrl,
    status: 'HFM_CRYPTO_RUNTIME_SCOPE_NOT_FOUND',
    statusZh: '没有找到所选 HFM 账号的 MT5 Files 目录',
    nextRequiredActionZh: '确认 Live16/secondary MT5 已安装并配置 QG_MT5_SECONDARY_FILES_DIR 或 QG_MT5_SECONDARY_WINE_PREFIX。',
    runtimeScope: runtimeScopeMeta(runtimeScope),
    safety: {
      readOnly: true,
      shadowOnly: true,
      orderSendAllowed: false,
      closeAllowed: false,
      cancelAllowed: false,
      mt5OrderSendAllowed: false,
      mossExecutionAllowed: false,
      livePresetMutationAllowed: false,
      externalMarketRemoved: true,
    },
  };
}

function compactBrokerSymbolDiagnostics(diagnostics = {}) {
  const samples = Array.isArray(diagnostics.brokerSymbolSamples)
    ? diagnostics.brokerSymbolSamples.slice(0, 20).map((row) => ({
        brokerSymbol: row.brokerSymbol,
        canonicalSymbol: row.canonicalSymbol,
        description: row.description,
        path: row.path,
        currencyBase: row.currencyBase,
        currencyProfit: row.currencyProfit,
        visible: row.visible,
        selected: row.selected,
        digits: row.digits,
        point: row.point,
        spread: row.spread,
        tradeMode: row.tradeMode,
        calcMode: row.calcMode,
        looksLikeCrypto: row.looksLikeCrypto,
      }))
    : [];
  return {
    brokerSymbolTotalAll: diagnostics.brokerSymbolTotalAll,
    brokerSymbolTotalMarketWatch: diagnostics.brokerSymbolTotalMarketWatch,
    brokerCryptoLikeCountAll: diagnostics.brokerCryptoLikeCountAll,
    brokerCryptoLikeCountMarketWatch: diagnostics.brokerCryptoLikeCountMarketWatch,
    brokerSymbolSampleCount: diagnostics.brokerSymbolSampleCount,
    brokerSymbolSamples: samples,
  };
}

function compactStatusPayload(payload = {}) {
  const symbolEvidence = payload.symbolEvidence || {};
  const diagnostics = symbolEvidence.brokerSymbolDiagnostics || payload.brokerSymbolDiagnostics || {};
  const standalone = compactStandaloneExporterBundle(payload.standaloneExporterBundle || {});
  return {
    exitCode: payload.exitCode,
    stderr: payload.stderr,
    ok: payload.ok,
    compactView: true,
    schema: payload.schema,
    generatedAt: payload.generatedAt,
    status: payload.status,
    statusZh: payload.statusZh,
    nextRequiredActionZh: payload.nextRequiredActionZh,
    operatorChecklist: Array.isArray(payload.operatorChecklist) ? payload.operatorChecklist : [],
    targetSymbols: Array.isArray(payload.targetSymbols) ? payload.targetSymbols : [],
    symbolEvidence: {
      found: Boolean(symbolEvidence.found),
      localBasesFound: Boolean(symbolEvidence.localBasesFound),
      contractSpecExportReady: Boolean(symbolEvidence.contractSpecExportReady),
      executionSpecReady: Boolean(symbolEvidence.executionSpecReady),
      canonicalSymbols: Array.isArray(symbolEvidence.canonicalSymbols) ? symbolEvidence.canonicalSymbols : [],
      brokerSymbols: Array.isArray(symbolEvidence.brokerSymbols) ? symbolEvidence.brokerSymbols : [],
      sources: Array.isArray(symbolEvidence.sources) ? symbolEvidence.sources : [],
      brokerSymbolDiagnostics: compactBrokerSymbolDiagnostics(diagnostics),
    },
    standaloneExporterBundle: standalone,
    mossBacktestProfile: payload.mossBacktestProfile
      ? {
          profileFound: Boolean(payload.mossBacktestProfile.profileFound),
          profileJsonPath: payload.mossBacktestProfile.profileJsonPath,
          metrics: payload.mossBacktestProfile.metrics || {},
        }
      : undefined,
    shadowPlan: payload.shadowPlan,
    riskBoundary: payload.riskBoundary,
    blockers: Array.isArray(payload.blockers) ? payload.blockers : [],
    sourceFiles: payload.sourceFiles,
    safety: payload.safety,
  };
}

function compactStandaloneExporterBundle(bundle = {}) {
  if (!bundle || typeof bundle !== 'object' || !bundle.schema) return undefined;
  const target = bundle.target || {};
  const output = bundle.output || {};
  const startupConfig = bundle.startupConfig || {};
  return {
    schema: bundle.schema,
    status: bundle.status,
    statusZh: bundle.statusZh,
    nextRequiredActionZh: bundle.nextRequiredActionZh,
    standaloneExporterReady: Boolean(bundle.standaloneExporterReady),
    targetInstalledAndCompiled: Boolean(bundle.targetInstalledAndCompiled),
    targetExpertInstalledAndCompiled: Boolean(bundle.targetExpertInstalledAndCompiled),
    targetScriptInstalledAndCompiled: Boolean(bundle.targetScriptInstalledAndCompiled),
    runtimeProbeMissingAfterSpecs: Boolean(bundle.runtimeProbeMissingAfterSpecs),
    runtimeProbeTickDetected: Boolean(bundle.runtimeProbeTickDetected),
    startupSymbol: startupConfig.configSource && startupConfig.configSource.startupSymbol,
    stagedExpertPath: bundle.bundle && bundle.bundle.stagedExpertPath,
    targetExpertPath: target.targetExpertPath,
    targetExpertInstalledMatchesBundle: Boolean(target.targetExpertInstalledMatchesBundle),
    targetExpertCompiledExists: Boolean(target.targetExpertCompiledExists),
    expectedRuntimeProbePath: output.expectedRuntimeProbePath,
    expectedRuntimeProbeExists: Boolean(output.expectedRuntimeProbeExists),
    expectedRuntimeProbeLiveTickCount: Number(output.expectedRuntimeProbeLiveTickCount || 0),
  };
}

function buildArgs(runtimeDir, url) {
  const args = ['--runtime-dir', runtimeDir, 'build', '--write'];
  const mossBacktestJson = url.searchParams.get('mossBacktestJson') || '';
  if (mossBacktestJson) args.push('--moss-backtest-json', mossBacktestJson);
  const simulationProfileJson = url.searchParams.get('simulationProfileJson') || url.searchParams.get('hfmSimulationProfileJson') || '';
  if (simulationProfileJson) args.push('--simulation-profile-json', simulationProfileJson);
  const contractSpecJson = url.searchParams.get('contractSpecJson') || url.searchParams.get('hfmContractSpecJson') || '';
  if (contractSpecJson) args.push('--contract-spec-json', contractSpecJson);
  for (const root of url.searchParams.getAll('extraBasesRoot')) {
    if (root) args.push('--extra-bases-root', root);
  }
  return args;
}

async function handle(req, res, ctx) {
  const requestUrl = req.url || '';
  const url = new URL(requestUrl, 'http://127.0.0.1');
  const pathname = url.pathname;
  const runtimeScope = resolveHfmCryptoRuntimeScope(ctx, url);
  const runtimeDir = runtimeScope.runtimeDir;
  if (!runtimeDir) {
    sendJson(res, 404, runtimeScopeNotFoundPayload(requestUrl, runtimeScope));
    return;
  }
  if (req.method === 'GET' && (pathname === '/api/hfm-crypto' || pathname === '/api/hfm-crypto/status')) {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'status']);
    const view = String(url.searchParams.get('view') || '').toLowerCase();
    sendScopedJson(
      res,
      payload,
      runtimeScope,
      (value) => (view === 'summary' || view === 'compact' ? compactStatusPayload(value) : value),
    );
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/symbols') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'build']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/execution-spec') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'execution-spec-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/contract-spec-export') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'contract-spec-export-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/simulation-profile') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'simulation-profile-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/evidence-kit') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'evidence-kit-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/evidence-bootstrap') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'evidence-bootstrap-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/mt5-exporter-review') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'mt5-exporter-review-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/mt5-upgrade-bundle') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'mt5-upgrade-bundle-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/mt5-exporter-deploy-plan') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'mt5-exporter-deploy-plan-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/standalone-exporter-bundle') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'standalone-exporter-bundle-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/mt5-post-upgrade-verify') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'mt5-post-upgrade-verify-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/post-upgrade-controller') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'post-upgrade-controller-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'GET' && pathname === '/api/hfm-crypto/filled-input-validator') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'filled-input-validator-status']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/build') {
    const payload = await runPythonJson(ctx.repoRoot, buildArgs(runtimeDir, url));
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/execution-spec/build') {
    const args = ['--runtime-dir', runtimeDir, 'execution-spec', '--write'];
    const contractSpecJson = url.searchParams.get('contractSpecJson') || url.searchParams.get('hfmContractSpecJson') || '';
    if (contractSpecJson) args.push('--contract-spec-json', contractSpecJson);
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/contract-spec-export/build') {
    const args = ['--runtime-dir', runtimeDir, 'contract-spec-export', '--write'];
    const symbolRegistryJson = url.searchParams.get('symbolRegistryJson') || url.searchParams.get('hfmSymbolRegistryJson') || '';
    if (symbolRegistryJson) args.push('--symbol-registry-json', symbolRegistryJson);
    if (url.searchParams.get('liveMt5') === 'true' || url.searchParams.get('liveMt5') === '1') {
      args.push('--live-mt5');
    }
    const terminalPath = url.searchParams.get('terminalPath') || '';
    if (terminalPath) args.push('--terminal-path', terminalPath);
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/simulation-profile/build') {
    const args = ['--runtime-dir', runtimeDir, 'simulation-profile', '--write'];
    const simulationProfileJson = url.searchParams.get('simulationProfileJson') || url.searchParams.get('hfmSimulationProfileJson') || url.searchParams.get('mossBacktestJson') || '';
    if (simulationProfileJson) args.push('--simulation-profile-json', simulationProfileJson);
    const payload = await runPythonJson(ctx.repoRoot, args);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/evidence-kit/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'evidence-kit', '--write']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/evidence-bootstrap/build') {
    const args = ['--runtime-dir', runtimeDir, 'evidence-bootstrap', '--write'];
    if (url.searchParams.get('overwriteDrafts') === 'true' || url.searchParams.get('overwriteDrafts') === '1') {
      args.push('--overwrite-drafts');
    }
    const payload = await runPythonJson(ctx.repoRoot, args, 180000);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/mt5-exporter-review/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'mt5-exporter-review', '--write']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/mt5-upgrade-bundle/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'mt5-upgrade-bundle', '--write']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/mt5-exporter-deploy-plan/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'mt5-exporter-deploy-plan', '--write']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/standalone-exporter-bundle/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'standalone-exporter-bundle', '--write']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/mt5-post-upgrade-verify/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'mt5-post-upgrade-verify', '--write']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/post-upgrade-controller/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'post-upgrade-controller', '--write']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  if (req.method === 'POST' && pathname === '/api/hfm-crypto/filled-input-validator/build') {
    const payload = await runPythonJson(ctx.repoRoot, ['--runtime-dir', runtimeDir, 'filled-input-validator', '--write']);
    sendScopedJson(res, payload, runtimeScope);
    return;
  }
  sendJson(res, 404, { ok: false, error: 'HFM_CRYPTO_CFD_NOT_FOUND', endpoint: pathname });
}

module.exports = {
  compactStatusPayload,
  handle,
  isHFMCryptoCfdPath,
  resolveHfmCryptoRuntimeScope,
  sendError,
};
