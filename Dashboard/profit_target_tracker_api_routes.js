const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const hfmCryptoCfdApiRoutes = require('./hfm_crypto_cfd_api_routes');

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
    Pragma: 'no-cache',
    Expires: '0',
  });
  res.end(JSON.stringify(payload, null, 2));
}

function safetyPayload() {
  return {
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
    liveExecutionCutoverAllowed: false,
  };
}

function sendError(res, statusCode, requestUrl, error) {
  sendJson(res, statusCode, {
    ok: false,
    endpoint: requestUrl,
    error: error && error.message ? error.message : String(error),
    safety: safetyPayload(),
  });
}

function isProfitTargetTrackerPath(requestUrl) {
  const pathname = String(requestUrl || '').split('?')[0];
  return pathname === '/api/profit-target' || pathname.startsWith('/api/profit-target/');
}

function runPythonJson(repoRoot, args, timeoutMs = 120000) {
  return new Promise((resolve) => {
    const pythonBin = process.env.QG_PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
    const script = path.join(repoRoot, 'tools', 'run_profit_target_tracker.py');
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

function truthyParam(value, defaultValue = false) {
  if (value == null || value === '') return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

function targetUsd(url) {
  const value = Number(url.searchParams.get('targetUsd') || url.searchParams.get('targetUSD') || 50);
  return Number.isFinite(value) && value > 0 ? value : 50;
}

function repoRuntimeDir(ctx = {}) {
  return path.join(ctx.repoRoot || process.cwd(), 'runtime');
}

function resolveHfmScope(ctx = {}, url = new URL('/', 'http://127.0.0.1')) {
  const scopedUrl = new URL(url.toString());
  const requestedScope =
    scopedUrl.searchParams.get('scope') ||
    scopedUrl.searchParams.get('accountScope') ||
    scopedUrl.searchParams.get('account') ||
    '';
  if (!requestedScope) {
    scopedUrl.searchParams.set('scope', 'secondary');
  }
  return hfmCryptoCfdApiRoutes.resolveHfmCryptoRuntimeScope(ctx, scopedUrl);
}

function runtimeScopeMeta(runtimeScope = {}) {
  return {
    scope: runtimeScope.scope || 'secondary',
    requestedScope: runtimeScope.requestedScope || runtimeScope.scope || 'secondary',
    accountLabel: runtimeScope.accountLabel || '',
    runtimeDir: runtimeScope.runtimeDir || '',
  };
}

function buildArgs(ctx, url, runtimeScope, write = true) {
  const runtimeDir = repoRuntimeDir(ctx);
  const args = [
    '--runtime-dir',
    runtimeDir,
    '--report-runtime-dir',
    runtimeDir,
    '--target-usd',
    String(targetUsd(url)),
  ];
  if (runtimeScope.runtimeDir) args.push('--hfm-runtime-dir', runtimeScope.runtimeDir);
  args.push('build');
  if (write) args.push('--write');
  return args;
}

function withMeta(payload, requestUrl, runtimeScope) {
  return {
    ok: statusCodeFor(payload) < 400,
    endpoint: requestUrl,
    ...payload,
    runtimeScope: runtimeScopeMeta(runtimeScope),
    safety: {
      ...safetyPayload(),
      ...(payload && typeof payload.safety === 'object' ? payload.safety : {}),
    },
  };
}

async function handle(req, res, ctx = {}) {
  const requestUrl = req.url || '';
  const url = new URL(requestUrl, 'http://127.0.0.1');
  const pathname = url.pathname;
  const runtimeScope = resolveHfmScope(ctx, url);

  if (req.method === 'GET' && (pathname === '/api/profit-target' || pathname === '/api/profit-target/status')) {
    const write = truthyParam(url.searchParams.get('write'), true);
    const payload = await runPythonJson(ctx.repoRoot, buildArgs(ctx, url, runtimeScope, write));
    sendJson(res, statusCodeFor(payload), withMeta(payload, requestUrl, runtimeScope));
    return;
  }

  if (req.method === 'POST' && pathname === '/api/profit-target/build') {
    const payload = await runPythonJson(ctx.repoRoot, buildArgs(ctx, url, runtimeScope, true));
    sendJson(res, statusCodeFor(payload), withMeta(payload, requestUrl, runtimeScope));
    return;
  }

  sendJson(res, 404, {
    ok: false,
    endpoint: pathname,
    error: 'PROFIT_TARGET_TRACKER_NOT_FOUND',
    safety: safetyPayload(),
  });
}

module.exports = {
  handle,
  isProfitTargetTrackerPath,
  sendError,
};
