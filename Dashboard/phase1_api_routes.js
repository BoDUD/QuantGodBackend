'use strict';

/**
 * QuantGod Phase 1 local dashboard routes.
 *
 * This module is intentionally self-contained so it can be inserted near the
 * start of Dashboard/dashboard_server.js without depending on the server's
 * internal helpers. Every endpoint shells out to read-only/advisory Python
 * tools and returns JSON only on localhost.
 */

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const MAX_BODY_BYTES = 128 * 1024;
const JSON_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
};

const PHASE1_API_SAFETY = Object.freeze({
  localOnly: true,
  readOnly: true,
  advisoryOnly: true,
  orderSendAllowed: false,
  closeAllowed: false,
  cancelAllowed: false,
  credentialStorageAllowed: false,
  livePresetMutationAllowed: false,
  canOverrideKillSwitch: false,
  canMutateGovernanceDecision: false,
});

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(statusCode, JSON_HEADERS);
  res.end(body);
}

function isPhase1Path(urlValue) {
  const url = new URL(urlValue || '/', 'http://127.0.0.1');
  const urlPath = url.pathname.replace(/\/+$/, '') || '/';
  return (
    urlPath === '/api/shadow-signals' ||
    urlPath.startsWith('/api/ai-analysis') ||
    urlPath === '/api/mt5-readonly/kline' ||
    urlPath === '/api/mt5-readonly/trades' ||
    urlPath === '/api/mt5-readonly/shadow-signals'
  );
}

function sendUnhandledError(res, error, endpoint = '/api/phase1') {
  sendJson(res, 500, {
    ok: false,
    mode: 'QUANTGOD_PHASE1_API_V1',
    endpoint,
    error: error && error.message ? error.message : String(error),
    safety: PHASE1_API_SAFETY,
  });
}

function notFoundPayload(urlPath) {
  return {
    ok: false,
    mode: 'QUANTGOD_PHASE1_API_V1',
    endpoint: urlPath,
    error: 'Unsupported Phase 1 endpoint',
    safety: PHASE1_API_SAFETY,
  };
}

function cleanSymbol(value) {
  const symbol = String(value || '').trim();
  if (!symbol) return '';
  return symbol.slice(0, 64);
}

function cleanSymbols(value) {
  const raw = Array.isArray(value) ? value : String(value || '').split(',');
  return raw
    .map((item) => cleanSymbol(item))
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index)
    .slice(0, 8);
}

function cleanTimeframes(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim().toUpperCase()).filter(Boolean);
  }
  return String(value || 'M15,H1,H4,D1')
    .split(',')
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
}

function boolValue(value, fallback = false) {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'boolean') return value;
  return ['1', 'true', 'yes', 'y', 'on'].includes(String(value).trim().toLowerCase());
}

function strictBoolValue(value) {
  if (typeof value === 'boolean') return value;
  if (value === undefined || value === null || value === '') return null;
  const normalized = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'y', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'n', 'off'].includes(normalized)) return false;
  return null;
}

function explicitTelegramDelivery(sendValue, dryRunValues = []) {
  const suppliedDryRunValues = dryRunValues.filter(
    (value) => value !== undefined && value !== null && value !== '',
  );
  const sendExplicitlyRequested = strictBoolValue(sendValue) === true;
  const dryRunExplicitlyDisabled = (
    suppliedDryRunValues.length > 0
    && suppliedDryRunValues.every((value) => strictBoolValue(value) === false)
  );
  const send = sendExplicitlyRequested && dryRunExplicitlyDisabled;
  return {
    send,
    dryRun: !send,
    sendExplicitlyRequested,
    dryRunExplicitlyDisabled,
  };
}

function intInRange(value, fallback, min, max) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new Error('Request body is too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (!chunks.length) {
        resolve({});
        return;
      }
      const raw = Buffer.concat(chunks).toString('utf8');
      try {
        resolve(JSON.parse(raw));
      } catch (error) {
        reject(new Error(`Invalid JSON body: ${error.message}`));
      }
    });
    req.on('error', reject);
  });
}

function runPythonJson(repoRoot, args, envOverrides = {}, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    const pythonBin = process.env.QG_PYTHON_BIN || process.env.QG_PYTHON || process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    const child = spawn(pythonBin, args, {
      cwd: repoRoot,
      env: { ...process.env, ...envOverrides },
      shell: false,
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill('SIGTERM');
      reject(new Error(`python timed out after ${timeoutMs}ms`));
    }, Math.max(1000, timeoutMs));
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
    });
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code !== 0) {
        reject(new Error(`python exited ${code}: ${stderr || stdout || 'no output'}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout || '{}'));
      } catch (error) {
        reject(new Error(`python returned non-JSON output: ${error.message}; stdout=${stdout.slice(0, 400)}`));
      }
    });
  });
}

function withPhase1Envelope(payload, endpoint) {
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    return {
      ...payload,
      _phase1: {
        mode: 'QUANTGOD_PHASE1_API_V1',
        endpoint,
        safety: PHASE1_API_SAFETY,
      },
    };
  }
  return {
    ok: true,
    mode: 'QUANTGOD_PHASE1_API_V1',
    endpoint,
    value: payload,
    safety: PHASE1_API_SAFETY,
  };
}

function isUnsupportedRuntimePath(value) {
  const text = String(value || '').trim();
  return process.platform !== 'win32' && /^[A-Za-z]:\\/.test(text);
}

function runtimeDirCandidates(ctx, repoRoot) {
  const rawValues = [
    ctx && (ctx.defaultRuntimeDir || ctx.runtimeDir),
    process.env.QG_RUNTIME_DIR,
    process.env.QG_MT5_FILES_DIR,
    process.env.QG_HFM_FILES,
    path.join(repoRoot, 'runtime'),
  ];
  const seen = new Set();
  return rawValues
    .map((value) => String(value || '').trim())
    .filter((value) => value && !isUnsupportedRuntimePath(value))
    .map((value) => path.resolve(value))
    .filter((value) => {
      if (seen.has(value)) return false;
      seen.add(value);
      return true;
    });
}

function runtimeDir(ctx, repoRoot) {
  const candidates = runtimeDirCandidates(ctx, repoRoot);
  const existing = candidates.find((candidate) => fs.existsSync(candidate));
  return existing || candidates[0] || path.join(repoRoot, 'runtime');
}

function runtimeEnv(ctx, repoRoot = path.resolve(__dirname, '..')) {
  const overrides = {};
  overrides.QG_RUNTIME_DIR = runtimeDir(ctx, repoRoot);
  return overrides;
}

function readRuntimeJson(ctx, repoRoot, filename) {
  const errors = [];
  for (const candidate of runtimeDirCandidates(ctx, repoRoot)) {
    const filePath = path.join(candidate, filename);
    try {
      const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      return { ok: true, filePath, payload };
    } catch (error) {
      errors.push({ filePath, error: error && error.message ? error.message : String(error) });
    }
  }
  const fallbackPath = path.join(path.join(repoRoot, 'runtime'), filename);
  return { ok: false, filePath: fallbackPath, errors };
}

async function handle(req, res, ctx = {}) {
  const repoRoot = ctx.repoRoot || path.resolve(__dirname, '..');
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  const method = String(req.method || 'GET').toUpperCase();
  const urlPath = url.pathname.replace(/\/+$/, '') || '/';

  try {
    if (urlPath === '/api/ai-analysis/deepseek-telegram/config') {
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'run_mt5_ai_telegram_monitor.py'), 'config'],
        runtimeEnv(ctx),
        30000,
      );
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/ai-analysis/deepseek-telegram/latest') {
      const latest = readRuntimeJson(ctx, repoRoot, 'QuantGod_MT5AiTelegramMonitorLatest.json');
      if (!latest.ok) {
        sendJson(res, 404, withPhase1Envelope({ ok: false, error: 'DeepSeek Telegram latest report not found', filePath: latest.filePath }, urlPath));
        return true;
      }
      sendJson(res, 200, withPhase1Envelope(latest.payload, urlPath));
      return true;
    }

    if (urlPath === '/api/ai-analysis/deepseek-telegram/run') {
      if (method !== 'POST') {
        sendJson(res, 405, { ok: false, error: 'POST required', safety: PHASE1_API_SAFETY });
        return true;
      }
      const body = await readJsonBody(req);
      const symbols = cleanSymbols(body.symbols || body.symbol || url.searchParams.get('symbols') || url.searchParams.get('symbol'));
      if (!symbols.length) {
        sendJson(res, 400, { ok: false, error: 'symbol is required', safety: PHASE1_API_SAFETY });
        return true;
      }
      const timeframes = cleanTimeframes(body.timeframes || url.searchParams.get('timeframes')).join(',');
      const delivery = explicitTelegramDelivery(
        body.send ?? url.searchParams.get('send'),
        [
          body.dryRun,
          body.dry_run,
          url.searchParams.get('dryRun'),
          url.searchParams.get('dry_run'),
        ],
      );
      const sendTelegram = delivery.send;
      const force = strictBoolValue(body.force ?? url.searchParams.get('force')) === true;
      const noDeepseek = boolValue(body.noDeepseek ?? url.searchParams.get('noDeepseek'), false);
      const minInterval = intInRange(body.minIntervalSeconds ?? url.searchParams.get('minIntervalSeconds'), force ? 0 : 900, 0, 86400);
      const minConfidence = intInRange(body.minConfidencePct ?? url.searchParams.get('minConfidencePct'), 70, 1, 100);
      const args = [
        path.join('tools', 'run_mt5_ai_telegram_monitor.py'),
        'scan-once',
        '--repo-root',
        repoRoot,
        '--symbols',
        symbols.join(','),
        '--timeframes',
        timeframes,
        '--min-interval-seconds',
        String(minInterval),
        '--min-confidence-pct',
        String(minConfidence),
      ];
      if (sendTelegram) args.push('--send', '--push-hold-summary');
      if (force) args.push('--force');
      if (noDeepseek) args.push('--no-deepseek');
      const payload = await runPythonJson(repoRoot, args, runtimeEnv(ctx), 120000);
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/ai-analysis/run') {
      if (method !== 'POST') {
        sendJson(res, 405, { ok: false, error: 'POST required', safety: PHASE1_API_SAFETY });
        return true;
      }
      const body = await readJsonBody(req);
      const symbol = cleanSymbol(body.symbol || url.searchParams.get('symbol'));
      if (!symbol) {
        sendJson(res, 400, { ok: false, error: 'symbol is required', safety: PHASE1_API_SAFETY });
        return true;
      }
      const timeframes = cleanTimeframes(body.timeframes || url.searchParams.get('timeframes')).join(',');
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'run_ai_analysis.py'), 'run', '--symbol', symbol, '--timeframes', timeframes],
        runtimeEnv(ctx),
      );
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/ai-analysis/latest') {
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'run_ai_analysis.py'), 'latest', '--allow-empty'],
        runtimeEnv(ctx),
      );
      sendJson(res, 200, withPhase1Envelope(payload || { ok: false, error: 'latest analysis not found' }, urlPath));
      return true;
    }

    if (urlPath === '/api/ai-analysis/history') {
      const symbol = cleanSymbol(url.searchParams.get('symbol'));
      const limit = intInRange(url.searchParams.get('limit'), 20, 1, 200);
      const args = [path.join('tools', 'run_ai_analysis.py'), 'history', '--limit', String(limit)];
      if (symbol) args.push('--symbol', symbol);
      const payload = await runPythonJson(repoRoot, args, runtimeEnv(ctx));
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath.startsWith('/api/ai-analysis/history/')) {
      const id = decodeURIComponent(urlPath.split('/').pop() || '').slice(0, 180);
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'run_ai_analysis.py'), 'history-item', '--id', id],
        runtimeEnv(ctx),
      );
      sendJson(res, payload && payload.ok === false ? 404 : 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/ai-analysis/config') {
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'run_ai_analysis.py'), 'config'],
        runtimeEnv(ctx),
      );
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/ai-analysis/agent-health') {
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'run_ai_analysis.py'), 'agent-health'],
        runtimeEnv(ctx),
        30000,
      );
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/ai-analysis/agent-health/history') {
      const limit = intInRange(url.searchParams.get('limit'), 20, 1, 200);
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'run_ai_analysis.py'), 'agent-health-history', '--limit', String(limit)],
        runtimeEnv(ctx),
        30000,
      );
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/mt5-readonly/kline') {
      const symbol = cleanSymbol(url.searchParams.get('symbol'));
      if (!symbol) {
        sendJson(res, 400, { ok: false, error: 'symbol is required', safety: PHASE1_API_SAFETY });
        return true;
      }
      const tf = String(url.searchParams.get('tf') || 'H1').trim().toUpperCase();
      const bars = intInRange(url.searchParams.get('bars'), 200, 1, 2000);
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'mt5_chart_readonly.py'), 'kline', '--symbol', symbol, '--tf', tf, '--bars', String(bars)],
        runtimeEnv(ctx),
      );
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/mt5-readonly/trades') {
      const symbol = cleanSymbol(url.searchParams.get('symbol'));
      if (!symbol) {
        sendJson(res, 400, { ok: false, error: 'symbol is required', safety: PHASE1_API_SAFETY });
        return true;
      }
      const days = intInRange(url.searchParams.get('days'), 30, 1, 365);
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'mt5_chart_readonly.py'), 'trades', '--symbol', symbol, '--days', String(days)],
        runtimeEnv(ctx),
      );
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath === '/api/shadow-signals' || urlPath === '/api/mt5-readonly/shadow-signals') {
      const symbol = cleanSymbol(url.searchParams.get('symbol'));
      if (!symbol) {
        sendJson(res, 400, { ok: false, error: 'symbol is required', safety: PHASE1_API_SAFETY });
        return true;
      }
      const days = intInRange(url.searchParams.get('days'), 7, 1, 365);
      const payload = await runPythonJson(
        repoRoot,
        [path.join('tools', 'mt5_chart_readonly.py'), 'shadow-signals', '--symbol', symbol, '--days', String(days)],
        runtimeEnv(ctx),
      );
      sendJson(res, 200, withPhase1Envelope(payload, urlPath));
      return true;
    }

    if (urlPath.startsWith('/api/ai-analysis/') || urlPath === '/api/shadow-signals') {
      sendJson(res, 404, notFoundPayload(urlPath));
      return true;
    }

    return false;
  } catch (error) {
    sendJson(res, 500, {
      ok: false,
      mode: 'QUANTGOD_PHASE1_API_V1',
      endpoint: urlPath,
      error: error && error.message ? error.message : String(error),
      safety: PHASE1_API_SAFETY,
    });
    return true;
  }
}

module.exports = {
  PHASE1_API_SAFETY,
  explicitTelegramDelivery,
  handle,
  isPhase1Path,
  sendUnhandledError,
};
