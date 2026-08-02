const fs = require('fs');
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

function sendError(res, statusCode, endpoint, error) {
  sendJson(res, statusCode, { ok: false, endpoint, error: error && error.message ? error.message : String(error) });
}

function isAutomationChainPath(url) {
  const pathname = String(url || '').split('?')[0];
  return pathname === '/api/automation-chain' || pathname.startsWith('/api/automation-chain/');
}

function readJsonBody(req) {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk.toString();
      if (body.length > 1024 * 1024) req.destroy();
    });
    req.on('end', () => {
      if (!body.trim()) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        resolve({ __jsonError: error.message });
      }
    });
    req.on('error', () => resolve({}));
  });
}

function strictBoolValue(value) {
  if (typeof value === 'boolean') return value;
  if (value === undefined || value === null || value === '') return null;
  const normalized = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'y', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'n', 'off'].includes(normalized)) return false;
  return null;
}

function explicitTelegramDelivery(body = {}) {
  const dryRunValues = [body.dryRun, body.dry_run].filter(
    (value) => value !== undefined && value !== null && value !== '',
  );
  const sendExplicitlyRequested = strictBoolValue(body.send) === true;
  const dryRunExplicitlyDisabled =
    dryRunValues.length > 0 && dryRunValues.every((value) => strictBoolValue(value) === false);
  const send = sendExplicitlyRequested && dryRunExplicitlyDisabled;
  return { send, dryRun: !send, sendExplicitlyRequested, dryRunExplicitlyDisabled };
}

function readJsonIfExists(filePath) {
  if (!fs.existsSync(filePath)) return null;
  try {
    const text = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '');
    return JSON.parse(text);
  } catch (_) {
    return null;
  }
}

function automationStatus(latest, runtimeDir, symbols) {
  if (!fs.existsSync(latest)) {
    return {
      schema: 'quantgod.automation_chain.v1',
      cycleId: null,
      runStatus: 'NOT_STARTED',
      schedulerState: 'NOT_STARTED',
      state: 'NOT_RUN',
      stateZh: '尚未运行',
      startedAt: null,
      completedAt: null,
      heartbeatAt: null,
      lastSuccessAt: null,
      nextDueAt: null,
      retryCount: 0,
      currentStep: 'not_started',
      stepCount: 0,
      runtimeDir,
      symbols: symbols.split(',').map((x) => x.trim()).filter(Boolean),
      freshness: { status: 'MISSING', ageSeconds: null, maxAgeSeconds: 900 },
      missingEvidence: ['尚未生成自动化链路运行报告'],
      blockedReasons: ['后台自动化调度尚未产生首个周期'],
      nextAction: '检查 local-shadow automation supervisor 与周期日志',
      safety: {
        mode: 'SHADOW_READONLY',
        advisoryOnly: true,
        executionLaneExists: false,
        orderSendAllowed: false,
        liveExpansionAllowed: false,
        unattendedLiveExpansionAllowed: false,
        operatorApprovalRequired: true,
        telegramCommandsAllowed: false,
      },
    };
  }
  const payload = readJsonIfExists(latest);
  const stat = fs.statSync(latest);
  if (!payload) {
    return {
      schema: 'quantgod.automation_chain.v1',
      cycleId: null,
      runStatus: 'FAILED',
      schedulerState: 'CORRUPT',
      state: 'FAILED',
      stateZh: '自动化状态文件损坏',
      runtimeDir,
      symbols: symbols.split(',').map((x) => x.trim()).filter(Boolean),
      freshness: { status: 'INVALID', ageSeconds: null, maxAgeSeconds: 900 },
      missingEvidence: ['自动化链路状态无法解析'],
      blockedReasons: ['AUTOMATION_STATUS_PARSE_FAILED'],
      safety: {
        mode: 'SHADOW_READONLY',
        advisoryOnly: true,
        executionLaneExists: false,
        orderSendAllowed: false,
        liveExpansionAllowed: false,
        unattendedLiveExpansionAllowed: false,
        operatorApprovalRequired: true,
      },
    };
  }
  const observedMs = Date.parse(payload?.heartbeatAt || payload?.completedAt || payload?.generatedAt || '') || stat.mtimeMs;
  const ageSeconds = Math.max(0, (Date.now() - Math.min(observedMs, stat.mtimeMs)) / 1000);
  const maxAgeSeconds = Number.parseInt(process.env.QG_AUTOMATION_STATUS_FRESH_SECONDS || '900', 10) || 900;
  const fresh = ageSeconds <= maxAgeSeconds;
  const blockedReasons = Array.isArray(payload?.blockedReasons) ? [...payload.blockedReasons] : [];
  if (!fresh && !blockedReasons.includes('AUTOMATION_HEARTBEAT_STALE')) {
    blockedReasons.unshift('AUTOMATION_HEARTBEAT_STALE');
  }
  return {
    ...payload,
    schedulerState: fresh ? (payload?.runStatus || payload?.state || 'UNKNOWN') : 'STALE',
    freshness: {
      status: fresh ? 'FRESH' : 'STALE',
      ageSeconds,
      maxAgeSeconds,
      observedAt: new Date(observedMs).toISOString(),
    },
    blockedReasons,
    safety: {
      ...(payload?.safety || {}),
      mode: 'SHADOW_READONLY',
      executionLaneExists: false,
      orderSendAllowed: false,
      liveExpansionAllowed: false,
      unattendedLiveExpansionAllowed: false,
      operatorApprovalRequired: true,
    },
  };
}

function parseQuery(url) {
  const parsed = new URL(url, 'http://127.0.0.1');
  return parsed.searchParams;
}

function scriptPath(ctx) {
  return path.join(ctx.repoRoot, 'tools', 'run_automation_chain.py');
}

function pythonBin() {
  return process.env.QG_PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
}

const DEFAULT_SYMBOLS = 'USDJPYc';

function normalizeSymbols(raw) {
  const items = String(raw || DEFAULT_SYMBOLS)
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  const focus = items.filter((item) => item.toUpperCase().startsWith('USDJPY'));
  return (focus.length ? focus : [DEFAULT_SYMBOLS]).join(',');
}

function runPython(ctx, args, timeoutMs = 180000) {
  return new Promise((resolve) => {
    const script = scriptPath(ctx);
    if (!fs.existsSync(script)) {
      resolve({ ok: false, skipped: true, reason: 'script_not_found', script });
      return;
    }
    const child = spawn(pythonBin(), [script, ...args], {
      cwd: ctx.repoRoot,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    let stdout = '';
    let stderr = '';
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      resolve({ ok: false, exitCode: -1, stdout, stderr: 'timeout' });
    }, timeoutMs);
    child.stdout.on('data', (chunk) => { stdout += chunk.toString(); });
    child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, exitCode: -1, stdout, stderr: error.message });
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: code === 0, exitCode: code, stdout: stdout.trim(), stderr: stderr.trim() });
    });
  });
}

async function handle(req, res, ctx) {
  const pathname = String(req.url || '').split('?')[0];
  const params = parseQuery(req.url || '/');
  const runtimeDir = params.get('runtimeDir') || ctx.defaultRuntimeDir;
  const symbols = normalizeSymbols(params.get('symbols') || process.env.QG_AUTOMATION_SYMBOLS || DEFAULT_SYMBOLS);

  if (req.method === 'GET' && (pathname === '/api/automation-chain' || pathname === '/api/automation-chain/status')) {
    const latest = path.join(runtimeDir, 'automation', 'QuantGod_AutomationChainLatest.json');
    const payload = automationStatus(latest, runtimeDir, symbols);
    sendJson(res, 200, { ok: true, endpoint: pathname, payload });
    return;
  }

  if (req.method === 'POST' && pathname === '/api/automation-chain/run') {
    const body = await readJsonBody(req);
    if (body.__jsonError) {
      sendJson(res, 400, { ok: false, endpoint: pathname, error: 'INVALID_JSON_BODY', detail: body.__jsonError });
      return;
    }
    if (params.has('send')) {
      sendJson(res, 400, {
        ok: false,
        endpoint: pathname,
        error: 'TELEGRAM_SEND_QUERY_REJECTED',
        sendRequested: true,
        sent: false,
        deliveryOk: false,
      });
      return;
    }
    const args = ['--runtime-dir', runtimeDir, '--symbols', symbols, 'once'];
    if (explicitTelegramDelivery(body).send) args.push('--send');
    const result = await runPython(ctx, args, 240000);
    if (!result.ok) {
      sendJson(res, 500, { ok: false, endpoint: pathname, result });
      return;
    }
    try {
      sendJson(res, 200, { ok: true, endpoint: pathname, payload: JSON.parse(result.stdout), stderr: result.stderr });
    } catch (error) {
      sendJson(res, 200, { ok: true, endpoint: pathname, stdout: result.stdout, stderr: result.stderr });
    }
    return;
  }

  if (req.method === 'GET' && pathname === '/api/automation-chain/telegram-text') {
    const args = ['--runtime-dir', runtimeDir, '--symbols', symbols, 'telegram-text'];
    if (params.get('refresh') === '1') args.push('--refresh');
    const result = await runPython(ctx, args, 180000);
    if (!result.ok) {
      sendJson(res, 500, { ok: false, endpoint: pathname, result });
      return;
    }
    sendJson(res, 200, { ok: true, endpoint: pathname, text: result.stdout, stderr: result.stderr });
    return;
  }

  sendJson(res, 404, { ok: false, endpoint: pathname, error: 'automation_chain_route_not_found' });
}

module.exports = { automationStatus, explicitTelegramDelivery, isAutomationChainPath, handle, sendError };
