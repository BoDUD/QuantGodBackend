const http = require('http');
const fs = require('fs');
const path = require('path');
const phase1ApiRoutes = require('./phase1_api_routes');
const phase2ApiRoutes = require('./phase2_api_routes');
const phase3ApiRoutes = require('./phase3_api_routes');
const automationChainApiRoutes = require('./automation_chain_api_routes');
const usdjpyStrategyLabApiRoutes = require('./usdjpy_strategy_lab_api_routes');
const caseMemoryApiRoutes = require('./case_memory_api_routes');
const strategyGAFactoryApiRoutes = require('./strategy_ga_factory_api_routes');
const hfmCryptoCfdApiRoutes = require('./hfm_crypto_cfd_api_routes');
const liveAutomationReadinessApiRoutes = require('./live_automation_readiness_api_routes');
const profitTargetTrackerApiRoutes = require('./profit_target_tracker_api_routes');
const gaFactoryApiRoutes = require('./ga_factory_api_routes');
const telegramGatewayOpsApiRoutes = require('./telegram_gateway_ops_api_routes');
const productionEvidenceValidationApiRoutes = require('./production_evidence_validation_api_routes');
const stateApiRoutes = require('./state_api_routes');
const { readJsonFileCached, stringifyJson } = require('./api_perf_cache');
const os = require('os');
const { spawn } = require('child_process');

const rootDir = __dirname;
const repoRoot = path.resolve(rootDir, '..');

function loadEnvFile(envPath) {
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const match = trimmed.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match || process.env[match[1]] !== undefined) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    process.env[match[1]] = value;
  }
}

loadEnvFile(path.join(repoRoot, '.env.local'));
loadEnvFile(path.join(repoRoot, '.env'));

const host = process.env.QG_DASHBOARD_HOST || '127.0.0.1';
const port = Number.parseInt(process.env.QG_DASHBOARD_PORT || '8080', 10) || 8080;
const latestDashboardFreshMs = Number.parseInt(process.env.QG_LATEST_DASHBOARD_FRESH_MS || '1800000', 10) || 1800000;
const pythonBin = process.env.QG_PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
const configuredRuntimeDir = process.env.QG_RUNTIME_DIR
  || process.env.QG_MT5_FILES_DIR
  || 'C:\\Program Files\\HFM Metatrader 5\\MQL5\\Files';
const configuredRuntimeDirResolved = path.isAbsolute(configuredRuntimeDir)
  ? configuredRuntimeDir
  : path.resolve(repoRoot, configuredRuntimeDir);

function isMacImportSnapshotDir(dir) {
  return String(dir || '').replace(/\\/g, '/').includes('/runtime/mac_import/mt5_files_snapshot');
}

function getMacMt5RootDir() {
  return path.join(
    os.homedir(),
    'Library',
    'Application Support',
    'net.metaquotes.wine.metatrader5',
    'drive_c',
    'Program Files',
    'MetaTrader 5'
  );
}

function getMacMt5FilesDir() {
  return path.join(getMacMt5RootDir(), 'MQL5', 'Files');
}

function isWindowsAbsolutePath(value) {
  return /^[A-Za-z]:[\\/]/.test(String(value || '').trim());
}

function resolveRuntimeDir() {
  const sourceMode = String(process.env.QG_MAC_RUNTIME_SOURCE || 'auto').trim().toLowerCase();
  const macMt5FilesDir = getMacMt5FilesDir();
  if (
    process.platform === 'darwin'
    && fs.existsSync(macMt5FilesDir)
    && (sourceMode === 'mt5' || (sourceMode === 'auto' && isWindowsAbsolutePath(configuredRuntimeDir)))
  ) {
    return macMt5FilesDir;
  }
  if (
    process.platform === 'darwin'
    && fs.existsSync(macMt5FilesDir)
    && (
      sourceMode === 'mt5'
      || (sourceMode === 'auto' && isMacImportSnapshotDir(configuredRuntimeDirResolved))
    )
  ) {
    return macMt5FilesDir;
  }
  return configuredRuntimeDirResolved;
}

const defaultRuntimeDir = resolveRuntimeDir();
const mt5ReadonlyBridgeScript = path.join(repoRoot, 'tools', 'mt5_readonly_bridge.py');
const mt5SymbolRegistryScript = path.join(repoRoot, 'tools', 'mt5_symbol_registry.py');
const mt5BackendBacktestScript = path.join(repoRoot, 'tools', 'run_mt5_backend_backtest_loop.py');
const mt5TradingClientScript = path.join(repoRoot, 'tools', 'mt5_trading_client.py');
const mt5PendingWorkerScript = path.join(repoRoot, 'tools', 'mt5_pending_order_worker.py');
const mt5PlatformStoreScript = path.join(repoRoot, 'tools', 'mt5_platform_store.py');
const mt5AdaptiveControlScript = path.join(repoRoot, 'tools', 'mt5_adaptive_control_executor.py');
const paramLabAutoTesterScript = path.join(repoRoot, 'tools', 'run_param_lab_auto_tester_window.py');
const dailyReviewScript = path.join(repoRoot, 'tools', 'build_daily_review.py');
const mt5ReadonlyEndpoints = new Set(['status', 'account', 'positions', 'orders', 'symbols', 'quote', 'snapshot']);
const mt5SymbolRegistryEndpoints = new Set(['registry', 'resolve']);
const mt5TradingEndpoints = new Set(['status', 'profiles', 'save-profile', 'login', 'order', 'close', 'cancel']);
const mt5PlatformEndpoints = new Set([
  'status',
  'operator',
  'credentials',
  'credential',
  'connect',
  'disconnect',
  'strategies',
  'strategy',
  'queue',
  'enqueue',
  'quick-trade',
  'dispatch',
  'queue-retry',
  'queue-cancel',
  'queue-archive',
  'worker-run',
  'ledger',
  'quick-trades',
  'task-runs',
  'positions',
  'trades',
  'symbols',
  'reconcile'
]);
const mt5BackendBacktestName = 'QuantGod_MT5BackendBacktest.json';
const mt5PendingWorkerName = 'QuantGod_MT5PendingOrderWorker.json';
const mt5PlatformStateName = 'QuantGod_MT5PlatformState.json';
const mt5AdaptiveControlName = 'QuantGod_MT5AdaptiveControlActions.json';
const paramLabAutoTesterName = 'QuantGod_AutoTesterWindow.json';
const paramLabAutoTesterLockName = 'QuantGod_AutoTesterWindow.lock.json';
const paramLabAutoTesterLaunchName = 'QuantGod_AutoTesterWindowLaunch.json';
const dailyReviewName = 'QuantGod_DailyReview.json';
const dailyAutopilotName = 'QuantGod_DailyAutopilot.json';
const configuredParamLabHfmRoot = process.env.QG_PARAMLAB_HFM_ROOT
  || path.join(repoRoot, 'runtime', 'ParamLab_Tester_Sandbox', 'live_hfm_placeholder');
const configuredParamLabTesterRoot = process.env.QG_PARAMLAB_TESTER_ROOT
  || process.env.QG_MT5_TESTER_ROOT
  || path.join(repoRoot, 'runtime', 'HFM_MT5_Tester_Isolated');
const defaultParamLabHfmRoot = path.isAbsolute(configuredParamLabHfmRoot)
  ? configuredParamLabHfmRoot
  : path.resolve(repoRoot, configuredParamLabHfmRoot);
const defaultParamLabTesterRoot = path.isAbsolute(configuredParamLabTesterRoot)
  ? configuredParamLabTesterRoot
  : path.resolve(repoRoot, configuredParamLabTesterRoot);
const dailyReadOnlyJsonFiles = new Set([
  dailyReviewName,
  dailyAutopilotName
]);
const quantGodReadOnlyJsonFiles = new Set([
  ...dailyReadOnlyJsonFiles
]);

const contentTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon'
};

const runtimeTextExtensions = new Set(['.json', '.csv', '.txt']);
const utf8Decoder = new TextDecoder('utf-8', { fatal: true });
const shiftJisDecoder = new TextDecoder('shift_jis');

const ALLOWED_ORIGINS = new Set([
  'http://127.0.0.1:5173',
  'http://localhost:5173',
  'http://127.0.0.1:8080',
  'http://localhost:8080',
]);

function corsHeadersFor(req) {
  const origin = (req.headers.origin || '').replace(/\/+$/, '');
  if (ALLOWED_ORIGINS.has(origin)) {
    return {
      'Access-Control-Allow-Origin': origin,
      'Vary': 'Origin'
    };
  }
  return {};
}

function corsPreflightHeadersFor(req) {
  const origin = (req.headers.origin || '').replace(/\/+$/, '');
  if (ALLOWED_ORIGINS.has(origin)) {
    return {
      'Access-Control-Allow-Origin': origin,
      'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, X-QuantGod-Local',
      'Vary': 'Origin'
    };
  }
  return {};
}

const CSRF_SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

function isCsrfSafe(req) {
  if (CSRF_SAFE_METHODS.has((req.method || 'GET').toUpperCase())) {
    return true;
  }
  return (req.headers['x-quantgod-local'] || '').trim() === '1';
}

function send(res, statusCode, headers, body) {
  for (const [k, v] of Object.entries(headers)) {
    res.setHeader(k, v);
  }
  res.writeHead(statusCode);
  res.end(body);
}

function sendJson(res, statusCode, payload, req) {
  const cors = req ? corsHeadersFor(req) : {};
  send(res, statusCode, Object.assign({
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
    Pragma: 'no-cache',
    Expires: '0',
  }, cors), stringifyJson(payload));
}

function latestDashboardFreshness(stat) {
  const ageMs = Math.max(0, Date.now() - Number(stat?.mtimeMs || 0));
  const fresh = ageMs <= latestDashboardFreshMs;
  return {
    mode: 'LATEST_DASHBOARD_MTIME_WATCH',
    status: fresh ? 'FRESH_DASHBOARD_SNAPSHOT' : 'STALE_DASHBOARD_SNAPSHOT',
    statusZh: fresh ? 'MT5 dashboard 快照新鲜' : 'MT5 dashboard 快照已过期',
    fresh,
    stale: !fresh,
    ageMs,
    ageSeconds: Math.round(ageMs / 100) / 10,
    maxAgeMs: latestDashboardFreshMs,
    maxAgeSeconds: Math.round(latestDashboardFreshMs / 100) / 10,
    blockers: fresh ? [] : ['live_dashboard_snapshot_stale'],
    nextActionZh: fresh
      ? '继续读取最新 MT5 dashboard。'
      : '恢复主 MT5/EA 进程并刷新 QuantGod_Dashboard.json；不要把旧快照当成当前实盘状态。',
    orderSendAllowed: false,
    mt5OrderSendAllowed: false,
    brokerCallsMade: false,
    mutatesMt5: false,
  };
}

function cloneJsonObject(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {};
  return JSON.parse(JSON.stringify(payload));
}

function withDashboardFreshnessOverlay(payload, freshness) {
  const next = cloneJsonObject(payload);
  next._freshness = freshness;
  next._runtimeUsability = {
    currentRuntimeFresh: freshness.fresh === true,
    currentTradingStateUsable: freshness.fresh === true,
    staleDashboardSnapshot: freshness.stale === true,
    nextActionZh: freshness.nextActionZh,
  };
  next.safety = {
    ...(next.safety || {}),
    orderSendAllowed: false,
    mt5OrderSendAllowed: false,
    brokerCallsMade: false,
    mutatesMt5: false,
    staleDashboardSnapshot: freshness.stale === true,
    currentRuntimeFresh: freshness.fresh === true,
  };
  if (freshness.stale === true) {
    const trading = next.trading && typeof next.trading === 'object' ? next.trading : {};
    next.trading = {
      ...trading,
      historicalTradeStatus: trading.tradeStatus,
      tradeStatus: 'STALE_DASHBOARD_SNAPSHOT',
      executionEnabled: false,
      tradeAllowed: false,
      currentRuntimeUsable: false,
      staleDashboardSnapshot: true,
      statusZh: freshness.statusZh,
      nextActionZh: freshness.nextActionZh,
    };
    next.runtimeState = 'STALE_DASHBOARD_SNAPSHOT';
    next.currentRuntimeUsable = false;
  }
  return next;
}

function readRequestBody(req, maxBytes = 64 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    req.on('data', (chunk) => {
      total += chunk.length;
      if (total > maxBytes) {
        reject(new Error('Request body too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function safeJsonPayload(text) {
  try {
    let normalized = String(text || '{}').replace(/^\uFEFF/, '').trim();
    if ((normalized.startsWith("'") && normalized.endsWith("'")) || (normalized.startsWith('"') && normalized.endsWith('"'))) {
      normalized = normalized.slice(1, -1);
    }
    normalized = normalized.replace(/\\"/g, '"');
    let payload = JSON.parse(normalized || '{}');
    if (typeof payload === 'string') {
      payload = JSON.parse(payload);
    }
    return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {};
  } catch (_) {
    return {};
  }
}

function runJsonPython(script, args = [], timeoutMs = 15000, extraEnv = {}) {
  return new Promise((resolve) => {
    if (!fs.existsSync(script)) {
      resolve({ ok: false, skipped: true, reason: 'script_not_found', script });
      return;
    }
    const child = spawn(pythonBin, [script, ...args], {
      cwd: repoRoot,
      windowsHide: true,
      env: { ...process.env, ...extraEnv, PYTHONIOENCODING: 'utf-8' }
    });
    let settled = false;
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      resolve({ ok: false, skipped: false, exitCode: -1, stdout, stderr: 'timeout' });
    }, timeoutMs);
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, skipped: false, exitCode: -1, stdout, stderr: error.message });
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code !== 0) {
        resolve({ ok: false, skipped: false, exitCode: code, stdout, stderr: stderr.trim() });
        return;
      }
      try {
        resolve({ ok: true, skipped: false, exitCode: code, payload: JSON.parse(stdout) });
      } catch (error) {
        resolve({ ok: false, skipped: false, exitCode: code, stdout, stderr: `json_parse_failed: ${error.message}` });
      }
    });
  });
}

function runPlainPython(script, args = [], timeoutMs = 15000) {
  return new Promise((resolve) => {
    if (!fs.existsSync(script)) {
      resolve({ ok: false, skipped: true, reason: 'script_not_found', script });
      return;
    }
    const child = spawn(pythonBin, [script, ...args], {
      cwd: repoRoot,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
    });
    let settled = false;
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      resolve({ ok: false, skipped: false, exitCode: -1, stdout, stderr: 'timeout' });
    }, timeoutMs);
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, skipped: false, exitCode: -1, stdout, stderr: error.message });
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        ok: code === 0,
        skipped: false,
        exitCode: code,
        stdout: stdout.trim(),
        stderr: stderr.trim()
      });
    });
  });
}

async function runJsonPythonPayload(script, args = [], payload = {}, timeoutMs = 15000) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-mt5-payload-'));
  const payloadPath = path.join(tempDir, 'payload.json');
  fs.writeFileSync(payloadPath, JSON.stringify(payload || {}, null, 2), 'utf8');
  try {
    return await runJsonPython(script, [...args, '--payload-file', payloadPath], timeoutMs);
  } finally {
    try { fs.unlinkSync(payloadPath); } catch (_) {}
    try { fs.rmdirSync(tempDir); } catch (_) {}
  }
}

function readQuantGodJsonFile(fileName) {
  const base = path.basename(fileName || '');
  if (!quantGodReadOnlyJsonFiles.has(base)) {
    throw new Error(`unsupported read-only json file: ${base}`);
  }
  const candidates = [path.join(rootDir, base)];
  if (fs.existsSync(defaultRuntimeDir)) {
    candidates.push(path.join(defaultRuntimeDir, base));
  }
  const existing = candidates
    .filter((candidate) => fs.existsSync(candidate))
    .map((candidate) => ({ candidate, mtimeMs: fs.statSync(candidate).mtimeMs }))
    .sort((a, b) => b.mtimeMs - a.mtimeMs);
  let lastError = null;
  for (const item of existing) {
    try {
      const read = readJsonFileCached(item.candidate);
      return { payload: read.payload, filePath: item.candidate };
    } catch (error) {
      lastError = error;
    }
  }
  if (lastError) throw lastError;
  throw new Error(`file not found: ${base}`);
}

function withServiceMeta(payload, endpoint, filePath) {
  const source = {
    service: 'quantgod_dashboard_local_api',
    endpoint,
    filePath,
    readOnly: true,
    walletWriteAllowed: false,
    orderSendAllowed: false,
    mutatesMt5: false
  };
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    return { ...payload, _api: source };
  }
  return { payload, _api: source };
}

function jstDateKey(date = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(date);
}

function dateKeyFromValue(value) {
  if (!value) return '';
  const text = String(value).trim();
  const match = text.match(/(\d{4})[./-](\d{2})[./-](\d{2})/);
  if (match) return `${match[1]}-${match[2]}-${match[3]}`;
  const parsed = Date.parse(text);
  if (!Number.isFinite(parsed)) return '';
  return jstDateKey(new Date(parsed));
}

function dailyReviewDateKeys(payload = {}) {
  return [
    payload.generatedAtIso,
    payload.generatedAt,
    payload.timestamp,
    payload.summary?.dailyReviewGeneratedAtIso,
    payload.summary?.generatedAtIso,
    payload.dailyPnl?.date,
    payload.summary?.dailyReviewDateJst
  ].map(dateKeyFromValue).filter(Boolean);
}

function isDailyReviewFresh(payload = {}, filePath = '') {
  const today = jstDateKey();
  const keys = dailyReviewDateKeys(payload);
  if (keys.includes(today)) return true;
  if (keys.length) return false;
  if (filePath && fs.existsSync(filePath)) {
    return jstDateKey(fs.statSync(filePath).mtime) === today;
  }
  return false;
}

function recentMt5LogDateNames(days = 3) {
  const names = [];
  for (let offset = 0; offset < days; offset += 1) {
    const date = new Date();
    date.setDate(date.getDate() - offset);
    const y = String(date.getFullYear());
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    names.push(`${y}${m}${d}`);
  }
  return names;
}

function readTailLines(filePath, maxBytes = 256 * 1024) {
  const stat = fs.statSync(filePath);
  const size = Math.min(stat.size, maxBytes);
  const buffer = Buffer.alloc(size);
  const fd = fs.openSync(filePath, 'r');
  try {
    fs.readSync(fd, buffer, 0, size, Math.max(0, stat.size - size));
  } finally {
    fs.closeSync(fd);
  }
  const hasUtf16Nuls = buffer.includes(0);
  const text = buffer
    .toString(hasUtf16Nuls ? 'utf16le' : 'utf8')
    .replace(/^\uFEFF/, '')
    .replace(/\u0000/g, '');
  return text.split(/\r?\n/).filter(Boolean);
}

function logDatePrefix(dateName) {
  const match = String(dateName || '').match(/^(\d{4})(\d{2})(\d{2})$/);
  return match ? `${match[1]}.${match[2]}.${match[3]}` : '';
}

function parseMt5AuthorizationLine(line, dateName = '') {
  const accountRejected = String(line || '').match(/(?:^|\s)(?:(\d{4}\.\d{2}\.\d{2} )?(\d{2}:\d{2}:\d{2}\.\d+)\s+)?Accounts\s+deleted due security reason/i);
  if (accountRejected) {
    const prefix = accountRejected[1] ? accountRejected[1].trim() : logDatePrefix(dateName);
    return {
      type: 'AUTH_CONFIG_REJECTED',
      logTime: [prefix, accountRejected[2]].filter(Boolean).join(' '),
      login: '',
      server: '',
      reason: 'accounts.dat deleted due security reason',
      message: 'copied MT5 account store was rejected by terminal security'
    };
  }
  const failure = String(line || '').match(/^(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}\.\d+)\s+Network\s+'([^']+)':\s+authorization on ([^\s]+) failed \(([^)]+)\)/i);
  const shortFailure = failure || String(line || '').match(/(?:^|\s)(\d{2}:\d{2}:\d{2}\.\d+)\s+Network\s+'([^']+)':\s+authorization on ([^\s]+) failed \(([^)]+)\)/i);
  if (shortFailure) {
    const hasDate = /^\d{4}\./.test(shortFailure[1]);
    const logTime = hasDate ? shortFailure[1] : [logDatePrefix(dateName), shortFailure[1]].filter(Boolean).join(' ');
    return {
      type: 'AUTH_FAILED',
      logTime,
      login: shortFailure[2],
      server: shortFailure[3],
      reason: shortFailure[4],
      message: `authorization failed: ${shortFailure[4]}`
    };
  }
  const success = String(line || '').match(/^(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}\.\d+)\s+Network\s+'([^']+)':\s+(?:authorized|authorization).*\b(?:on|to)\s+([^\s]+)/i);
  const shortSuccess = success || String(line || '').match(/(?:^|\s)(\d{2}:\d{2}:\d{2}\.\d+)\s+Network\s+'([^']+)':\s+(?:authorized|authorization).*\b(?:on|to)\s+([^\s]+)/i);
  if (shortSuccess && !/failed/i.test(line)) {
    const hasDate = /^\d{4}\./.test(shortSuccess[1]);
    const logTime = hasDate ? shortSuccess[1] : [logDatePrefix(dateName), shortSuccess[1]].filter(Boolean).join(' ');
    return {
      type: 'AUTHORIZED',
      logTime,
      login: shortSuccess[2],
      server: shortSuccess[3],
      reason: '',
      message: 'authorized'
    };
  }
  return null;
}

function readMt5TerminalStatus(rootOverride = '') {
  if (process.platform !== 'darwin') return null;
  const root = rootOverride || getMacMt5RootDir();
  if (!fs.existsSync(root)) return null;
  const candidates = recentMt5LogDateNames(4).flatMap((dateName) => [
    path.join(root, 'logs', `${dateName}.log`),
    path.join(root, 'Logs', `${dateName}.log`),
    path.join(root, 'MQL5', 'logs', `${dateName}.log`),
    path.join(root, 'MQL5', 'Logs', `${dateName}.log`)
  ].map((filePath) => ({ filePath, dateName })));
  const files = candidates
    .filter((candidate) => fs.existsSync(candidate.filePath))
    .map((candidate) => ({ ...candidate, stat: fs.statSync(candidate.filePath) }))
    .sort((a, b) => b.stat.mtimeMs - a.stat.mtimeMs);
  const events = [];
  for (const file of files) {
    try {
      for (const line of readTailLines(file.filePath)) {
        const event = parseMt5AuthorizationLine(line, file.dateName);
        if (event) events.push({ ...event, filePath: file.filePath });
      }
    } catch (_) {
      // Ignore unreadable Wine log tails; this endpoint must stay read-only and best-effort.
    }
  }
  events.sort((a, b) => String(a.logTime).localeCompare(String(b.logTime)));
  const lastAuthorization = [...events].reverse().find((event) => event.type === 'AUTHORIZED') || null;
  const lastAuthFailure = [...events].reverse().find((event) => event.type === 'AUTH_FAILED') || null;
  const latestEvent = events[events.length - 1] || null;
  return {
    status: latestEvent?.type || 'NO_AUTH_EVENT',
    lastAuthFailure,
    lastAuthorization,
    logFile: latestEvent?.filePath || files[0]?.filePath || '',
    logMtimeIso: files[0]?.stat?.mtime ? files[0].stat.mtime.toISOString() : '',
    readOnly: true,
    orderSendAllowed: false,
    mutatesMt5: false
  };
}

function cleanMt5ReadonlyParam(value, maxLength = 160) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function clampMt5ReadonlyLimit(value, fallback = 120, max = 2000) {
  const parsed = Number.parseInt(String(value || ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(parsed, max));
}

function buildMt5ReadonlyArgs(endpoint, parsedUrl) {
  const params = parsedUrl.searchParams;
  const args = ['--endpoint', endpoint];
  const symbol = cleanMt5ReadonlyParam(params.get('symbol') || params.get('focusSymbol') || '');
  const group = cleanMt5ReadonlyParam(params.get('group') || '*', 120) || '*';
  const query = cleanMt5ReadonlyParam(params.get('q') || params.get('query') || '', 120);
  const limit = clampMt5ReadonlyLimit(params.get('limit'), 120);
  const symbolsLimit = clampMt5ReadonlyLimit(params.get('symbolsLimit') || params.get('symbols_limit'), 120);

  if (symbol) args.push('--symbol', symbol);
  args.push('--group', group);
  if (query) args.push('--query', query);
  args.push('--limit', String(limit));
  args.push('--symbols-limit', String(symbolsLimit));
  return args;
}

function secondaryMt5FilesDir() {
  const candidates = [
    process.env.QG_MT5_SECONDARY_FILES_DIR,
    process.env.QG_MT5_SECONDARY_ROOT
      ? path.join(process.env.QG_MT5_SECONDARY_ROOT, 'MQL5', 'Files')
      : '',
    process.env.QG_MT5_SECONDARY_WINE_PREFIX
      ? path.join(
          process.env.QG_MT5_SECONDARY_WINE_PREFIX,
          'drive_c',
          'Program Files',
          'MetaTrader 5',
          'MQL5',
          'Files'
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
      'Files'
    )
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate)) || '';
}

function secondaryMt5RootDir() {
  const filesDir = secondaryMt5FilesDir();
  return filesDir ? path.resolve(filesDir, '..', '..') : '';
}

function mt5ReadonlyEnv(scope = 'primary') {
  if (scope !== 'secondary') return {};
  const filesDir = secondaryMt5FilesDir();
  if (!filesDir) return null;
  return {
    QG_RUNTIME_DIR: filesDir,
    QG_MT5_FILES_DIR: filesDir,
    QG_MT5_EA_SNAPSHOT_EXPLICIT_ONLY: '1'
  };
}

async function handleMt5Readonly(req, res, endpoint, options = {}) {
  if (!mt5ReadonlyEndpoints.has(endpoint)) {
    sendJson(res, 404, {
      ok: false,
      status: 'NOT_FOUND',
      endpoint,
      error: 'unsupported_mt5_readonly_endpoint',
      supportedEndpoints: Array.from(mt5ReadonlyEndpoints).sort(),
      safety: {
        readOnly: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        credentialStorageAllowed: false,
        livePresetMutationAllowed: false,
        mutatesMt5: false
      }
    });
    return;
  }
  const normalizedEndpoint = endpoint;
  const scope = options.scope === 'secondary' ? 'secondary' : 'primary';
  const extraEnv = mt5ReadonlyEnv(scope);
  if (extraEnv === null) {
    sendJson(res, 200, {
      ok: false,
      status: 'UNCONFIGURED',
      endpoint: normalizedEndpoint,
      scope,
      error: 'secondary_mt5_runtime_not_found',
      safety: {
        readOnly: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        credentialStorageAllowed: false,
        livePresetMutationAllowed: false,
        mutatesMt5: false
      }
    });
    return;
  }
  try {
    const parsed = new URL(req.url || '/', `http://${host}:${port}`);
    const result = await runJsonPython(
      mt5ReadonlyBridgeScript,
      buildMt5ReadonlyArgs(normalizedEndpoint, parsed),
      12000,
      extraEnv
    );
    if (!result.ok) {
      const terminal =
        scope === 'secondary' ? readMt5TerminalStatus(secondaryMt5RootDir()) : readMt5TerminalStatus();
      sendJson(res, 200, {
        ok: false,
        status: 'UNAVAILABLE',
        endpoint: normalizedEndpoint,
        scope,
        error: result.stderr || result.reason || 'mt5_readonly_bridge_failed',
        detail: result,
        ...(terminal ? { terminal } : {}),
        safety: {
          readOnly: true,
          orderSendAllowed: false,
          closeAllowed: false,
          cancelAllowed: false,
          credentialStorageAllowed: false,
          livePresetMutationAllowed: false,
          mutatesMt5: false
        }
      });
      return;
    }
    const payload = result.payload && typeof result.payload === 'object' ? result.payload : {};
    const terminal =
      (payload?.ok === false || String(payload?.status || '').toUpperCase() === 'UNAVAILABLE')
        ? scope === 'secondary'
          ? readMt5TerminalStatus(secondaryMt5RootDir())
          : readMt5TerminalStatus()
        : null;
    sendJson(res, 200, {
      ...payload,
      scope,
      ...(terminal ? { terminal } : {}),
      _api: {
        service: 'quantgod_dashboard_mt5_readonly_bridge',
        endpoint: scope === 'secondary'
          ? `/api/mt5-readonly-secondary/${normalizedEndpoint}`
          : `/api/mt5-readonly/${normalizedEndpoint}`,
        script: mt5ReadonlyBridgeScript,
        readOnly: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        mutatesMt5: false
      }
    });
  } catch (error) {
    sendJson(res, 200, {
      ok: false,
      status: 'UNAVAILABLE',
      endpoint: normalizedEndpoint,
      error: error.message || String(error),
      safety: {
        readOnly: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        credentialStorageAllowed: false,
        livePresetMutationAllowed: false,
        mutatesMt5: false
      }
    });
  }
}

function buildMt5SymbolRegistryArgs(endpoint, parsedUrl) {
  const params = parsedUrl.searchParams;
  const args = ['--endpoint', endpoint];
  const symbol = cleanMt5ReadonlyParam(params.get('symbol') || params.get('canonical') || params.get('brokerSymbol') || '', 160);
  const group = cleanMt5ReadonlyParam(params.get('group') || '*', 120) || '*';
  const query = cleanMt5ReadonlyParam(params.get('q') || params.get('query') || '', 120);
  const limit = clampMt5ReadonlyLimit(params.get('limit'), 2000, 5000);

  if (symbol) args.push('--symbol', symbol);
  args.push('--group', group);
  if (query) args.push('--query', query);
  args.push('--limit', String(limit));
  return args;
}

async function handleMt5SymbolRegistry(req, res, endpoint) {
  if (!mt5SymbolRegistryEndpoints.has(endpoint)) {
    sendJson(res, 404, {
      ok: false,
      status: 'NOT_FOUND',
      endpoint,
      error: 'unsupported_mt5_symbol_registry_endpoint',
      supportedEndpoints: Array.from(mt5SymbolRegistryEndpoints).sort(),
      safety: {
        readOnly: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        symbolSelectAllowed: false,
        credentialStorageAllowed: false,
        livePresetMutationAllowed: false,
        mutatesMt5: false
      }
    });
    return;
  }
  try {
    const parsed = new URL(req.url || '/', `http://${host}:${port}`);
    const result = await runJsonPython(mt5SymbolRegistryScript, buildMt5SymbolRegistryArgs(endpoint, parsed), 15000);
    if (!result.ok) {
      sendJson(res, 200, {
        ok: false,
        status: 'UNAVAILABLE',
        endpoint,
        error: result.stderr || result.reason || 'mt5_symbol_registry_failed',
        detail: result,
        safety: {
          readOnly: true,
          orderSendAllowed: false,
          closeAllowed: false,
          cancelAllowed: false,
          symbolSelectAllowed: false,
          credentialStorageAllowed: false,
          livePresetMutationAllowed: false,
          mutatesMt5: false
        }
      });
      return;
    }
    const payload = result.payload && typeof result.payload === 'object' ? result.payload : {};
    sendJson(res, 200, {
      ...payload,
      _api: {
        service: 'quantgod_dashboard_mt5_symbol_registry',
        endpoint: endpoint === 'resolve' ? '/api/mt5-symbol-registry/resolve' : '/api/mt5-symbol-registry',
        script: mt5SymbolRegistryScript,
        readOnly: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        symbolSelectAllowed: false,
        mutatesMt5: false
      }
    });
  } catch (error) {
    sendJson(res, 200, {
      ok: false,
      status: 'UNAVAILABLE',
      endpoint,
      error: error.message || String(error),
      safety: {
        readOnly: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        symbolSelectAllowed: false,
        credentialStorageAllowed: false,
        livePresetMutationAllowed: false,
        mutatesMt5: false
      }
    });
  }
}

function clampMt5BackendDays(value, fallback = 180) {
  const parsed = Number.parseInt(String(value || ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(7, Math.min(parsed, 730));
}

function clampMt5BackendTasks(value, fallback = 20) {
  const parsed = Number.parseInt(String(value || ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(1, Math.min(parsed, 80));
}

function clampParamLabAutoTesterTasks(value, fallback = 8) {
  const parsed = Number.parseInt(String(value || ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(1, Math.min(parsed, 12));
}

function clampParamLabAutoTesterMinutes(value, fallback = 90) {
  const parsed = Number.parseInt(String(value || ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(15, Math.min(parsed, 180));
}

function clampParamLabTesterLookbackDays(value, fallback = 2) {
  const parsed = Number.parseInt(String(value || ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(1, Math.min(parsed, 14));
}

function clampParamLabTesterTimeout(value, fallback = 900) {
  const parsed = Number.parseInt(String(value || ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(300, Math.min(parsed, 3600));
}

function formatTesterDateJst(date) {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${year}.${month}.${day}`;
}

function buildDailyTesterBounds(options = {}) {
  const lookbackDays = clampParamLabTesterLookbackDays(
    options.testerLookbackDays || options.tester_lookback_days || process.env.QG_DAILY_AUTOPILOT_TESTER_LOOKBACK_DAYS,
    2
  );
  const terminalTimeoutSeconds = clampParamLabTesterTimeout(
    options.terminalTimeoutSeconds || options.terminal_timeout_seconds || process.env.QG_DAILY_AUTOPILOT_TESTER_TIMEOUT_SECONDS,
    900
  );
  const nowJst = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const startJst = new Date(nowJst.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
  const fromDate = cleanMt5ReadonlyParam(options.fromDate || options.from || '', 32) || formatTesterDateJst(startJst);
  const toDate = cleanMt5ReadonlyParam(options.toDate || options.to || '', 32) || formatTesterDateJst(nowJst);
  return { fromDate, toDate, lookbackDays, terminalTimeoutSeconds };
}

function readJsonIfExists(filePath) {
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''));
}

function paramLabAutoTesterPaths() {
  return {
    output: path.join(defaultRuntimeDir, paramLabAutoTesterName),
    lock: path.join(defaultRuntimeDir, paramLabAutoTesterLockName),
    launch: path.join(defaultRuntimeDir, paramLabAutoTesterLaunchName)
  };
}

function buildParamLabAutoTesterArgs(options = {}) {
  const maxTasks = clampParamLabAutoTesterTasks(options.maxTasks || options.max_tasks, 8);
  const dailyBounds = buildDailyTesterBounds(options);
  const args = [
    '--repo-root',
    repoRoot,
    '--runtime-dir',
    defaultRuntimeDir,
    '--hfm-root',
    defaultParamLabHfmRoot,
    '--tester-root',
    defaultParamLabTesterRoot,
    '--max-tasks',
    String(maxTasks),
    '--login',
    String(process.env.QG_MT5_LOGIN || process.env.QG_HFM_LOGIN || '186054398'),
    '--server',
    String(process.env.QG_MT5_SERVER || process.env.QG_HFM_SERVER || 'HFMarketsGlobal-Live12'),
    '--from-date',
    dailyBounds.fromDate,
    '--to-date',
    dailyBounds.toDate,
    '--terminal-timeout-seconds',
    String(dailyBounds.terminalTimeoutSeconds)
  ];
  if (options.continuousWatch) {
    args.push('--continuous-watch');
  }
  if (options.runTerminal) {
    args.push('--run-terminal', '--authorized-strategy-tester');
  }
  return args;
}

function writeParamLabAutoTesterLock(options = {}) {
  const paths = paramLabAutoTesterPaths();
  const minutes = clampParamLabAutoTesterMinutes(options.minutes, 90);
  const maxTasks = clampParamLabAutoTesterTasks(options.maxTasks || options.max_tasks, 8);
  const now = new Date();
  const expires = new Date(now.getTime() + minutes * 60 * 1000);
  const lock = {
    schemaVersion: 1,
    purpose: 'PARAM_LAB_STRATEGY_TESTER_ONLY',
    authorized: true,
    testerOnly: true,
    allowRunTerminal: true,
    livePresetMutation: false,
    allowOutsideWindow: false,
    createdAtIso: now.toISOString(),
    expiresAtIso: expires.toISOString(),
    runtimeDir: defaultRuntimeDir,
    hfmRoot: defaultParamLabTesterRoot,
    maxTasks,
    source: 'dashboard_paramlab_auto_tester_button'
  };
  fs.mkdirSync(path.dirname(paths.lock), { recursive: true });
  fs.writeFileSync(paths.lock, JSON.stringify(lock, null, 2), 'utf8');
  return { lock, lockPath: paths.lock };
}

async function evaluateParamLabAutoTester(payload = {}) {
  const args = buildParamLabAutoTesterArgs({
    maxTasks: payload.maxTasks || payload.max_tasks
  });
  const processResult = await runPlainPython(paramLabAutoTesterScript, args, 120000);
  const paths = paramLabAutoTesterPaths();
  let status = null;
  try {
    status = readJsonIfExists(paths.output);
  } catch (error) {
    status = { parseError: error.message || String(error) };
  }
  return {
    ok: processResult.ok,
    action: 'evaluate',
    status,
    process: processResult,
    safety: {
      testerOnly: true,
      guardRequired: true,
      runTerminalRequested: false,
      orderSendAllowed: false,
      livePresetMutationAllowed: false,
      mutatesLiveMt5: false
    }
  };
}

async function handleParamLabAutoTester(req, res, action) {
  const body = req.method === 'POST' ? await readRequestBody(req) : '{}';
  const payload = safeJsonPayload(body);
  if (action === 'lock') {
    const lockResult = writeParamLabAutoTesterLock(payload);
    const evalResult = await evaluateParamLabAutoTester(payload);
    sendJson(res, 200, {
      ok: evalResult.ok,
      action,
      lock: lockResult.lock,
      lockPath: lockResult.lockPath,
      status: evalResult.status,
      process: evalResult.process,
      safety: {
        testerOnly: true,
        shortLivedAuthorization: true,
        runTerminalRequested: false,
        orderSendAllowed: false,
        livePresetMutationAllowed: false,
        mutatesLiveMt5: false
      }
    });
    return;
  }
  if (action === 'evaluate') {
    sendJson(res, 200, await evaluateParamLabAutoTester(payload));
    return;
  }
  if (action !== 'run') {
    sendJson(res, 404, { ok: false, error: 'unsupported_paramlab_auto_tester_action', action });
    return;
  }

  const preflight = await evaluateParamLabAutoTester(payload);
  const summary = preflight.status && preflight.status.summary ? preflight.status.summary : {};
  const gate = preflight.status && preflight.status.gate ? preflight.status.gate : {};
  if (!summary.canRunTerminal) {
    sendJson(res, 200, {
      ok: false,
      action,
      started: false,
      status: preflight.status,
      process: preflight.process,
      blockers: Array.isArray(gate.blockers) ? gate.blockers : [],
      error: 'AUTO_TESTER_WINDOW_BLOCKED',
      safety: {
        testerOnly: true,
        guardRequired: true,
        runTerminalRequested: true,
        runTerminalStarted: false,
        orderSendAllowed: false,
        livePresetMutationAllowed: false,
        mutatesLiveMt5: false
      }
    });
    return;
  }

  const args = buildParamLabAutoTesterArgs({
    maxTasks: payload.maxTasks || payload.max_tasks,
    runTerminal: true,
    continuousWatch: true
  });
  const paths = paramLabAutoTesterPaths();
  const launch = {
    ok: true,
    action,
    started: true,
    launchedAtIso: new Date().toISOString(),
    script: paramLabAutoTesterScript,
    args,
    runtimeDir: defaultRuntimeDir,
    testerRoot: defaultParamLabTesterRoot,
    statusPath: paths.output,
    logPath: paths.launch,
    safety: {
      testerOnly: true,
      guardRequired: true,
      runTerminalRequested: true,
      orderSendAllowed: false,
      livePresetMutationAllowed: false,
      mutatesLiveMt5: false
    }
  };
  fs.mkdirSync(path.dirname(paths.launch), { recursive: true });
  fs.writeFileSync(paths.launch, JSON.stringify(launch, null, 2), 'utf8');
  const child = spawn(pythonBin, [paramLabAutoTesterScript, ...args], {
    cwd: repoRoot,
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
  });
  child.unref();
  sendJson(res, 202, launch);
}

function buildMt5BackendBacktestArgs(parsedUrl) {
  const params = parsedUrl.searchParams;
  const args = [
    '--repo-root',
    repoRoot,
    '--runtime-dir',
    defaultRuntimeDir,
    '--days',
    String(clampMt5BackendDays(params.get('days'), 180)),
    '--max-tasks',
    String(clampMt5BackendTasks(params.get('maxTasks') || params.get('max_tasks'), 20)),
  ];
  const fromDate = cleanMt5ReadonlyParam(params.get('from') || params.get('fromDate') || '', 32);
  const toDate = cleanMt5ReadonlyParam(params.get('to') || params.get('toDate') || '', 32);
  const route = cleanMt5ReadonlyParam(params.get('route') || '', 80);
  if (fromDate) args.push('--from-date', fromDate);
  if (toDate) args.push('--to-date', toDate);
  if (route) args.push('--route', route);
  return args;
}

async function handleMt5BackendBacktest(req, res, forceRun = false) {
  const parsed = new URL(req.url || '/', `http://${host}:${port}`);
  const refresh = forceRun || ['1', 'true', 'yes'].includes(String(parsed.searchParams.get('refresh') || parsed.searchParams.get('run') || '').toLowerCase());
  const target = path.join(defaultRuntimeDir, mt5BackendBacktestName);
  if (!refresh && fs.existsSync(target)) {
    try {
      const payload = JSON.parse(fs.readFileSync(target, 'utf8').replace(/^\uFEFF/, ''));
      sendJson(res, 200, {
        ...payload,
        _api: {
          service: 'quantgod_dashboard_mt5_backend_backtest',
          endpoint: '/api/mt5-backtest-loop',
          filePath: target,
          readOnly: true,
          pythonBacktestOnly: true,
          orderSendAllowed: false,
          closeAllowed: false,
          cancelAllowed: false,
          livePresetMutationAllowed: false,
          mutatesMt5: false
        }
      });
      return;
    } catch (error) {
      sendJson(res, 200, {
        ok: false,
        status: 'UNAVAILABLE',
        error: `mt5_backend_backtest_artifact_unreadable: ${error.message}`,
        safety: {
          readOnly: true,
          pythonBacktestOnly: true,
          orderSendAllowed: false,
          closeAllowed: false,
          cancelAllowed: false,
          livePresetMutationAllowed: false,
          mutatesMt5: false
        }
      });
      return;
    }
  }

  const result = await runJsonPython(mt5BackendBacktestScript, buildMt5BackendBacktestArgs(parsed), 120000);
  if (!result.ok) {
    sendJson(res, 200, {
      ok: false,
      status: 'UNAVAILABLE',
      error: result.stderr || result.reason || 'mt5_backend_backtest_failed',
      detail: result,
      safety: {
        readOnly: true,
        pythonBacktestOnly: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        livePresetMutationAllowed: false,
        mutatesMt5: false
      }
    });
    return;
  }
  const payload = result.payload && typeof result.payload === 'object' ? result.payload : {};
  sendJson(res, 200, {
    ...payload,
    _api: {
      service: 'quantgod_dashboard_mt5_backend_backtest',
      endpoint: '/api/mt5-backtest-loop/run',
      script: mt5BackendBacktestScript,
      readOnly: true,
      pythonBacktestOnly: true,
      orderSendAllowed: false,
      closeAllowed: false,
      cancelAllowed: false,
      livePresetMutationAllowed: false,
      mutatesMt5: false
    }
  });
}

function mt5TradingEndpointFromPath(pathPart) {
  const base = pathPart.replace(/^\/api\/mt5-trading\/?/, '').replace(/^\/api\/mt5\/?/, '');
  if (!base || base === 'status') return 'status';
  if (base === 'profile') return 'save-profile';
  if (base === 'account-profiles') return 'profiles';
  const first = base.split('/').filter(Boolean)[0] || 'status';
  return first === 'profile' ? 'save-profile' : first;
}

function buildMt5TradingArgs(endpoint) {
  return ['--endpoint', endpoint, '--runtime-dir', defaultRuntimeDir];
}

async function handleMt5Trading(req, res, endpoint, extraPayload = {}) {
  const normalized = endpoint === 'profile' ? 'save-profile' : endpoint;
  if (!mt5TradingEndpoints.has(normalized)) {
    sendJson(res, 404, {
      ok: false,
      status: 'NOT_FOUND',
      endpoint: normalized,
      error: 'unsupported_mt5_trading_endpoint',
      supportedEndpoints: Array.from(mt5TradingEndpoints).sort(),
      safety: {
        readOnly: false,
        dryRun: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        credentialStorageAllowed: false,
        livePresetMutationAllowed: false,
        auditLedgerRequired: true,
        mutatesMt5: false
      }
    });
    return;
  }

  try {
    let payload = { ...extraPayload };
    if (req.method === 'POST' || req.method === 'DELETE') {
      const raw = await readRequestBody(req, 128 * 1024).catch(() => '');
      payload = { ...safeJsonPayload(raw), ...payload };
    }
    const parsed = new URL(req.url || '/', `http://${host}:${port}`);
    if (['1', 'true', 'yes'].includes(String(parsed.searchParams.get('dryRun') || '').toLowerCase())) {
      payload.dryRun = true;
    }
    const result = ['status', 'profiles'].includes(normalized)
      ? await runJsonPython(mt5TradingClientScript, buildMt5TradingArgs(normalized), 15000)
      : await runJsonPythonPayload(mt5TradingClientScript, buildMt5TradingArgs(normalized), payload, 20000);
    if (!result.ok) {
      sendJson(res, 200, {
        ok: false,
        status: 'UNAVAILABLE',
        endpoint: normalized,
        error: result.stderr || result.reason || 'mt5_trading_bridge_failed',
        detail: result,
        safety: {
          readOnly: false,
          dryRun: true,
          orderSendAllowed: false,
          closeAllowed: false,
          cancelAllowed: false,
          credentialStorageAllowed: false,
          livePresetMutationAllowed: false,
          auditLedgerRequired: true,
          mutatesMt5: false
        }
      });
      return;
    }
    const body = result.payload && typeof result.payload === 'object' ? result.payload : {};
    sendJson(res, 200, {
      ...body,
      _api: {
        service: 'quantgod_dashboard_mt5_trading_bridge',
        endpoint: `/api/mt5/${normalized}`,
        script: mt5TradingClientScript,
        readOnly: false,
        guardedMutation: true,
        auditLedgerRequired: true,
        credentialStorageAllowed: false,
        livePresetMutationAllowed: false
      }
    });
  } catch (error) {
    sendJson(res, 200, {
      ok: false,
      status: 'UNAVAILABLE',
      endpoint: normalized,
      error: error.message || String(error),
      safety: {
        readOnly: false,
        dryRun: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        credentialStorageAllowed: false,
        livePresetMutationAllowed: false,
        auditLedgerRequired: true,
        mutatesMt5: false
      }
    });
  }
}

function buildMt5PendingWorkerArgs(parsedUrl, payloadPath = '') {
  const params = parsedUrl.searchParams;
  const maxIntents = clampMt5ReadonlyLimit(params.get('maxIntents') || params.get('max_intents'), 20, 100);
  const args = ['--runtime-dir', defaultRuntimeDir, '--max-intents', String(maxIntents)];
  if (['1', 'true', 'yes'].includes(String(params.get('dryRun') || '').toLowerCase())) {
    args.push('--dry-run');
  }
  if (payloadPath) {
    args.push('--intents', payloadPath);
  }
  return args;
}

async function handleMt5PendingWorker(req, res, forceRun = false) {
  const parsed = new URL(req.url || '/', `http://${host}:${port}`);
  const useDbWorker = ['1', 'true', 'yes'].includes(String(parsed.searchParams.get('dbWorker') || parsed.searchParams.get('platformDb') || '').toLowerCase());
  if (useDbWorker) {
    const result = await runJsonPythonPayload(
      mt5PlatformStoreScript,
      ['--runtime-dir', defaultRuntimeDir, '--endpoint', 'worker-run'],
      { maxOrders: clampMt5ReadonlyLimit(parsed.searchParams.get('maxIntents') || parsed.searchParams.get('maxOrders'), 20, 100), dryRun: true, source: 'dashboard_pending_worker_db_mode' },
      60000
    );
    const payload = result.payload && typeof result.payload === 'object' ? result.payload : {};
    sendJson(res, 200, {
      ...payload,
      _api: {
        service: 'quantgod_dashboard_mt5_platform_db_worker',
        endpoint: '/api/mt5-pending-worker/run?dbWorker=true',
        script: mt5PlatformStoreScript,
        guardedMutation: true,
        dryRunRequired: true,
        auditLedgerRequired: true
      }
    });
    return;
  }
  const target = path.join(defaultRuntimeDir, mt5PendingWorkerName);
  if (!forceRun && req.method === 'GET' && fs.existsSync(target)) {
    try {
      const payload = JSON.parse(fs.readFileSync(target, 'utf8').replace(/^\uFEFF/, ''));
      sendJson(res, 200, {
        ...payload,
        _api: {
          service: 'quantgod_dashboard_mt5_pending_order_worker',
          endpoint: '/api/mt5-pending-worker/status',
          filePath: target,
          guardedMutation: true,
          auditLedgerRequired: true
        }
      });
      return;
    } catch (_) {}
  }

  let tempDir = '';
  let intentsPath = '';
  try {
    if (req.method === 'POST') {
      const body = safeJsonPayload(await readRequestBody(req, 256 * 1024).catch(() => ''));
      if (Array.isArray(body.intents) || Array.isArray(body.orders)) {
        tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-mt5-intents-'));
        intentsPath = path.join(tempDir, 'intents.json');
        fs.writeFileSync(intentsPath, JSON.stringify(body, null, 2), 'utf8');
      }
    }
    const result = await runJsonPython(mt5PendingWorkerScript, buildMt5PendingWorkerArgs(parsed, intentsPath), 60000);
    if (!result.ok) {
      sendJson(res, 200, {
        ok: false,
        status: 'UNAVAILABLE',
        endpoint: '/api/mt5-pending-worker/run',
        error: result.stderr || result.reason || 'mt5_pending_worker_failed',
        detail: result,
        safety: {
          readOnly: false,
          dryRun: true,
          orderSendAllowed: false,
          closeAllowed: false,
          cancelAllowed: false,
          auditLedgerRequired: true,
          mutatesMt5: false
        }
      });
      return;
    }
    const payload = result.payload && typeof result.payload === 'object' ? result.payload : {};
    sendJson(res, 200, {
      ...payload,
      _api: {
        service: 'quantgod_dashboard_mt5_pending_order_worker',
        endpoint: '/api/mt5-pending-worker/run',
        script: mt5PendingWorkerScript,
        guardedMutation: true,
        auditLedgerRequired: true
      }
    });
  } finally {
    if (intentsPath) {
      try { fs.unlinkSync(intentsPath); } catch (_) {}
    }
    if (tempDir) {
      try { fs.rmdirSync(tempDir); } catch (_) {}
    }
  }
}

function mt5PlatformEndpointFromPath(pathPart) {
  if (pathPart === '/api/mt5-platform') return 'status';
  const endpoint = path.basename(pathPart);
  return endpoint || 'status';
}

async function handleMt5PlatformStore(req, res, endpoint = 'status') {
  const normalized = mt5PlatformEndpoints.has(endpoint) ? endpoint : 'status';
  try {
    let requestPayload = {};
    if (req.method === 'POST' || req.method === 'DELETE') {
      requestPayload = safeJsonPayload(await readRequestBody(req, 256 * 1024).catch(() => ''));
    }
    const args = ['--runtime-dir', defaultRuntimeDir, '--endpoint', normalized];
    const result = (req.method === 'POST' || req.method === 'DELETE')
      ? await runJsonPythonPayload(mt5PlatformStoreScript, args, requestPayload, normalized === 'dispatch' || normalized === 'worker-run' || normalized === 'symbols' || normalized === 'reconcile' ? 60000 : 20000)
      : await runJsonPython(mt5PlatformStoreScript, args, normalized === 'symbols' || normalized === 'reconcile' ? 60000 : 20000);
    if (!result.ok) {
      sendJson(res, 200, {
        ok: false,
        status: 'UNAVAILABLE',
        endpoint: normalized,
        error: result.stderr || result.reason || 'mt5_platform_store_failed',
        detail: result,
        safety: {
          readOnly: false,
          controlPlaneOnly: true,
          orderSendAllowed: false,
          closeAllowed: false,
          cancelAllowed: false,
          credentialStorageAllowed: false,
          rawPasswordStorageAllowed: false,
          dryRunRequired: true,
          mutatesMt5: false
        }
      });
      return;
    }
    const payload = result.payload && typeof result.payload === 'object' ? result.payload : {};
    sendJson(res, 200, {
      ...payload,
      _api: {
        service: 'quantgod_dashboard_mt5_platform_store',
        endpoint: `/api/mt5-platform/${normalized}`,
        script: mt5PlatformStoreScript,
        controlPlaneOnly: true,
        orderSendAllowed: false,
        rawPasswordStorageAllowed: false,
        dryRunRequired: true
      }
    });
  } catch (error) {
    sendJson(res, 200, {
      ok: false,
      status: 'UNAVAILABLE',
      endpoint: normalized,
      error: error.message || String(error)
    });
  }
}

async function handleMt5AdaptiveControl(req, res, forceRun = false) {
  const target = path.join(defaultRuntimeDir, mt5AdaptiveControlName);
  if (!forceRun && req.method === 'GET' && fs.existsSync(target)) {
    try {
      const payload = JSON.parse(fs.readFileSync(target, 'utf8').replace(/^\uFEFF/, ''));
      sendJson(res, 200, {
        ...payload,
        _api: {
          service: 'quantgod_dashboard_mt5_adaptive_control',
          endpoint: '/api/mt5-adaptive-control/status',
          filePath: target,
          guardedMutation: true,
          livePresetMutationAllowed: false
        }
      });
      return;
    } catch (_) {}
  }
  const parsed = new URL(req.url || '/', `http://${host}:${port}`);
  const applyStaging = forceRun || ['1', 'true', 'yes'].includes(String(parsed.searchParams.get('applyStaging') || parsed.searchParams.get('staging') || '').toLowerCase());
  const applyLive = ['1', 'true', 'yes'].includes(String(parsed.searchParams.get('applyLive') || parsed.searchParams.get('live') || '').toLowerCase());
  const args = ['--runtime-dir', defaultRuntimeDir, '--repo-root', repoRoot];
  if (applyStaging) args.push('--apply-staging');
  if (applyLive) args.push('--apply-live');
  const result = await runJsonPython(mt5AdaptiveControlScript, args, 30000);
  if (!result.ok) {
    sendJson(res, 200, {
      ok: false,
      status: 'UNAVAILABLE',
      error: result.stderr || result.reason || 'mt5_adaptive_control_failed',
      detail: result,
      safety: {
        readOnly: false,
        adaptiveControlExecutor: true,
        orderSendAllowed: false,
        closeAllowed: false,
        cancelAllowed: false,
        livePresetMutationAllowed: false,
        mutatesMt5: false
      }
    });
    return;
  }
  const payload = result.payload && typeof result.payload === 'object' ? result.payload : {};
  sendJson(res, 200, {
    ...payload,
    _api: {
      service: 'quantgod_dashboard_mt5_adaptive_control',
      endpoint: applyStaging ? '/api/mt5-adaptive-control/run' : '/api/mt5-adaptive-control/status',
      script: mt5AdaptiveControlScript,
      guardedMutation: true,
      auditLedgerRequired: true
    }
  });
}

async function handleQuantGodReadOnlyJson(req, res, fileName, endpoint) {
  try {
    const { payload, filePath } = readQuantGodJsonFile(fileName);
    sendJson(res, 200, withServiceMeta(payload, endpoint, filePath));
  } catch (error) {
    sendJson(res, 404, {
      ok: false,
      error: error.message || String(error),
      endpoint,
      safety: {
        walletWriteAllowed: false,
        orderSendAllowed: false,
        mutatesMt5: false,
        readOnly: true
      }
    });
  }
}

async function handleDailyReviewJson(req, res) {
  let refreshResult = null;
  let shouldRefresh = false;
  try {
    const requestUrl = new URL(req.url || '/api/daily-review', 'http://localhost');
    shouldRefresh = requestUrl.searchParams.get('refresh') === '1';
  } catch (_) {
    shouldRefresh = false;
  }
  try {
    const current = readQuantGodJsonFile(dailyReviewName);
    if (!isDailyReviewFresh(current.payload, current.filePath)) shouldRefresh = true;
  } catch (_) {
    shouldRefresh = true;
  }
  if (shouldRefresh) {
    refreshResult = await runPlainPython(dailyReviewScript, ['--runtime-dir', defaultRuntimeDir], 90000);
  }
  try {
    const { payload, filePath } = readQuantGodJsonFile(dailyReviewName);
    sendJson(res, 200, {
      ...withServiceMeta(payload, '/api/daily-review', filePath),
      _dailyReviewFresh: isDailyReviewFresh(payload, filePath),
      _dailyReviewRefresh: refreshResult || { ok: true, skipped: true, reason: 'fresh' }
    });
  } catch (error) {
    sendJson(res, 404, {
      ok: false,
      error: error.message || String(error),
      endpoint: '/api/daily-review',
      refresh: refreshResult,
      safety: {
        walletWriteAllowed: false,
        orderSendAllowed: false,
        mutatesMt5: false,
        readOnly: true
      }
    });
  }
}

function maybeTranscodeRuntimeText(target, ext, data) {
  const base = path.basename(target);
  if (!runtimeTextExtensions.has(ext) || !base.startsWith('QuantGod_')) {
    return data;
  }

  try {
    utf8Decoder.decode(data);
    return data;
  } catch (_) {
    // Some MT4/MT5 runtime CSV files are written in the terminal locale; keep
    // the legacy Shift-JIS compatibility path only when bytes are not UTF-8.
  }

  try {
    const utf8Text = shiftJisDecoder.decode(data);
    return Buffer.from(utf8Text, 'utf8');
  } catch (err) {
    console.warn(`QuantGod dashboard server transcode fallback for ${base}: ${err.message}`);
    return data;
  }
}

function safeResolve(urlPath) {
  const pathname = decodeURIComponent(urlPath.split('?')[0] || '/');
  const normalized = pathname;
  const target = path.resolve(rootDir, '.' + normalized);
  if (!target.startsWith(rootDir)) {
    return null;
  }
  return target;
}

function shouldRedirectToVue(urlPath) {
  const pathname = decodeURIComponent(urlPath.split('?')[0] || '/');
  return pathname === '/' || pathname === '/QuantGod_Dashboard.html';
}

function redirectToVue(urlPath, res) {
  const query = urlPath.includes('?') ? `?${urlPath.split('?').slice(1).join('?')}` : '';
  send(res, 302, {
    Location: `/vue/${query}`,
    'Content-Type': 'text/plain; charset=utf-8',
    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'
  }, 'Redirecting to QuantGod Vue workbench');
}

function safeResolveVue(urlPath) {
  const pathname = decodeURIComponent(urlPath.split('?')[0] || '/');
  if (pathname !== '/vue' && pathname !== '/vue/' && !pathname.startsWith('/vue/')) {
    return null;
  }

  const vueRoot = path.join(rootDir, 'vue-dist');
  const indexPath = path.join(vueRoot, 'index.html');
  if (pathname === '/vue' || pathname === '/vue/') {
    return indexPath;
  }

  const relative = pathname.slice('/vue/'.length);
  const target = path.resolve(vueRoot, relative);
  if (!target.startsWith(vueRoot)) {
    return null;
  }

  if (fs.existsSync(target)) {
    return target;
  }

  return path.extname(target) ? target : indexPath;
}

function resolveRuntimeFallback(target) {
  const base = path.basename(target || '');
  if (!base.startsWith('QuantGod_')) return null;
  const runtimeTarget = path.join(defaultRuntimeDir, base);
  if (!runtimeTarget.startsWith(defaultRuntimeDir)) return null;
  return fs.existsSync(runtimeTarget) ? runtimeTarget : null;
}

function sendStaticFile(target, res) {
  fs.stat(target, (statErr, stats) => {
    if (statErr || !stats.isFile()) {
      send(res, 404, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Not Found');
      return;
    }

    const ext = path.extname(target).toLowerCase();
    const contentType = contentTypes[ext] || 'application/octet-stream';

    fs.readFile(target, (readErr, data) => {
      if (readErr) {
        send(res, 500, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Read Failed');
        return;
      }

      const body = maybeTranscodeRuntimeText(target, ext, data);

      send(res, 200, {
        'Content-Type': contentType,
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        Pragma: 'no-cache',
        Expires: '0'
      }, body);
    });
  });
}

const server = http.createServer((req, res) => {
  const requestUrl = req.url || '/';

  // Set CORS origin header early so it persists through writeHead in send/sendJson
  const origin = (req.headers.origin || '').replace(/\/+$/, '');
  if (ALLOWED_ORIGINS.has(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }

  if (req.method === 'OPTIONS') {
    const preflightHeaders = corsPreflightHeadersFor(req);
    if (Object.keys(preflightHeaders).length > 0) {
      send(res, 204, Object.assign({ 'Content-Type': 'application/json; charset=utf-8' }, preflightHeaders), JSON.stringify({}));
    } else {
      send(res, 204, { 'Content-Type': 'application/json; charset=utf-8' }, JSON.stringify({}));
    }
    return;
  }

  // CSRF guard: non-safe methods require X-QuantGod-Local: 1 header
  if (!isCsrfSafe(req)) {
    sendJson(res, 403, { ok: false, error: 'CSRF_FORBIDDEN', detail: 'Non-safe methods require X-QuantGod-Local: 1 header' }, req);
    return;
  }

  if (usdjpyStrategyLabApiRoutes.isUSDJPYStrategyLabPath(requestUrl)) {
    usdjpyStrategyLabApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => usdjpyStrategyLabApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (caseMemoryApiRoutes.isCaseMemoryPath(requestUrl)) {
    caseMemoryApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => caseMemoryApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (strategyGAFactoryApiRoutes.isStrategyGAFactoryPath(requestUrl)) {
    strategyGAFactoryApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => strategyGAFactoryApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (hfmCryptoCfdApiRoutes.isHFMCryptoCfdPath(requestUrl)) {
    hfmCryptoCfdApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => hfmCryptoCfdApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (liveAutomationReadinessApiRoutes.isLiveAutomationReadinessPath(requestUrl)) {
    liveAutomationReadinessApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => liveAutomationReadinessApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (profitTargetTrackerApiRoutes.isProfitTargetTrackerPath(requestUrl)) {
    profitTargetTrackerApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => profitTargetTrackerApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (gaFactoryApiRoutes.isGAFactoryPath(requestUrl)) {
    gaFactoryApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => gaFactoryApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (productionEvidenceValidationApiRoutes.isProductionEvidenceValidationPath(requestUrl)) {
    productionEvidenceValidationApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => productionEvidenceValidationApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (telegramGatewayOpsApiRoutes.isTelegramGatewayOpsPath(requestUrl)) {
    telegramGatewayOpsApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => telegramGatewayOpsApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (automationChainApiRoutes.isAutomationChainPath(requestUrl)) {
    automationChainApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => automationChainApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (stateApiRoutes.isStatePath(requestUrl)) {
    stateApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => stateApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (phase3ApiRoutes.isPhase3Path(requestUrl)) {
    phase3ApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => phase3ApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (phase2ApiRoutes.isPhase2Path(requestUrl)) {
    phase2ApiRoutes
      .handle(req, res, { repoRoot, rootDir, defaultRuntimeDir })
      .catch((error) => phase2ApiRoutes.sendError(res, 500, requestUrl, error));
    return;
  }
  if (phase1ApiRoutes.isPhase1Path(requestUrl)) {
    phase1ApiRoutes
      .handle(req, res, { repoRoot, defaultRuntimeDir })
      .catch((error) => phase1ApiRoutes.sendUnhandledError(res, error, requestUrl));
    return;
  }
  if (req.method === 'GET' && shouldRedirectToVue(requestUrl)) {
    redirectToVue(requestUrl, res);
    return;
  }
  if (req.method === 'GET' && requestUrl.split('?')[0] === '/api/latest') {
    const latestDashboard = path.join(defaultRuntimeDir, 'QuantGod_Dashboard.json');
    if (fs.existsSync(latestDashboard)) {
      try {
        const { payload, stat } = readJsonFileCached(latestDashboard);
        const terminal = readMt5TerminalStatus();
        const freshness = latestDashboardFreshness(stat);
        const safePayload = withDashboardFreshnessOverlay(payload, freshness);
        sendJson(res, 200, withServiceMeta({
          ...safePayload,
          ...(terminal ? { _terminal: terminal } : {}),
          _freshness: freshness,
          _file: {
            path: latestDashboard,
            mtimeIso: stat.mtime.toISOString(),
            mtimeMs: stat.mtimeMs
          }
        }, '/api/latest', latestDashboard));
      } catch (error) {
        sendJson(res, 500, {
          ok: false,
          status: 'PARSE_FAILED',
          endpoint: '/api/latest',
          error: error.message,
          filePath: latestDashboard
        });
      }
      return;
    }
    send(res, 404, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Not Found');
    return;
  }
  if (req.method === 'GET' && requestUrl.split('?')[0] === '/api/daily-review') {
    handleDailyReviewJson(req, res);
    return;
  }
  if (req.method === 'GET' && requestUrl.split('?')[0] === '/api/daily-autopilot') {
    handleQuantGodReadOnlyJson(req, res, dailyAutopilotName, '/api/daily-autopilot');
    return;
  }
  if (req.method === 'GET' && (requestUrl.split('?')[0] === '/api/mt5-readonly' || requestUrl.split('?')[0].startsWith('/api/mt5-readonly/'))) {
    const pathPart = requestUrl.split('?')[0];
    const endpoint = pathPart === '/api/mt5-readonly' ? 'snapshot' : path.basename(pathPart);
    handleMt5Readonly(req, res, endpoint);
    return;
  }
  if (
    req.method === 'GET' &&
    (requestUrl.split('?')[0] === '/api/mt5-readonly-secondary' ||
      requestUrl.split('?')[0].startsWith('/api/mt5-readonly-secondary/'))
  ) {
    const pathPart = requestUrl.split('?')[0];
    const endpoint = pathPart === '/api/mt5-readonly-secondary' ? 'snapshot' : path.basename(pathPart);
    handleMt5Readonly(req, res, endpoint, { scope: 'secondary' });
    return;
  }
  if (req.method === 'GET' && (requestUrl.split('?')[0] === '/api/mt5-symbol-registry' || requestUrl.split('?')[0].startsWith('/api/mt5-symbol-registry/'))) {
    const pathPart = requestUrl.split('?')[0];
    const endpoint = pathPart === '/api/mt5-symbol-registry' ? 'registry' : path.basename(pathPart);
    handleMt5SymbolRegistry(req, res, endpoint);
    return;
  }
  if (req.method === 'GET' && requestUrl.split('?')[0] === '/api/mt5-backtest-loop') {
    handleMt5BackendBacktest(req, res, false);
    return;
  }
  if (req.method === 'GET' && requestUrl.split('?')[0] === '/api/mt5-backtest-loop/run') {
    handleMt5BackendBacktest(req, res, true);
    return;
  }
  if (req.method === 'POST' && requestUrl.split('?')[0].startsWith('/api/paramlab/auto-tester/')) {
    const action = path.basename(requestUrl.split('?')[0]);
    handleParamLabAutoTester(req, res, action);
    return;
  }
  if ((req.method === 'GET' || req.method === 'POST' || req.method === 'DELETE') && (requestUrl.split('?')[0] === '/api/mt5-platform' || requestUrl.split('?')[0].startsWith('/api/mt5-platform/'))) {
    const pathPart = requestUrl.split('?')[0];
    const endpoint = mt5PlatformEndpointFromPath(pathPart);
    handleMt5PlatformStore(req, res, endpoint);
    return;
  }
  if (req.method === 'GET' && requestUrl.split('?')[0] === '/api/mt5-pending-worker/status') {
    handleMt5PendingWorker(req, res, false);
    return;
  }
  if (req.method === 'POST' && requestUrl.split('?')[0] === '/api/mt5-pending-worker/run') {
    handleMt5PendingWorker(req, res, true);
    return;
  }
  if (req.method === 'GET' && requestUrl.split('?')[0] === '/api/mt5-adaptive-control/status') {
    handleMt5AdaptiveControl(req, res, false);
    return;
  }
  if (req.method === 'POST' && requestUrl.split('?')[0] === '/api/mt5-adaptive-control/run') {
    handleMt5AdaptiveControl(req, res, true);
    return;
  }
  if ((req.method === 'GET' || req.method === 'POST') && (requestUrl.split('?')[0] === '/api/mt5-trading' || requestUrl.split('?')[0].startsWith('/api/mt5-trading/'))) {
    const pathPart = requestUrl.split('?')[0];
    const endpoint = pathPart === '/api/mt5-trading' ? 'status' : mt5TradingEndpointFromPath(pathPart);
    handleMt5Trading(req, res, endpoint);
    return;
  }
  if ((req.method === 'GET' || req.method === 'POST') && (requestUrl.split('?')[0] === '/api/mt5' || requestUrl.split('?')[0].startsWith('/api/mt5/'))) {
    const pathPart = requestUrl.split('?')[0];
    const endpoint = pathPart === '/api/mt5' ? 'status' : mt5TradingEndpointFromPath(pathPart);
    handleMt5Trading(req, res, endpoint);
    return;
  }
  if (req.method === 'DELETE' && requestUrl.split('?')[0].startsWith('/api/mt5/order/')) {
    const ticket = path.basename(requestUrl.split('?')[0]);
    handleMt5Trading(req, res, 'cancel', { ticket, orderTicket: ticket });
    return;
  }
  const vueTarget = safeResolveVue(req.url || '/');
  if (vueTarget) {
    sendStaticFile(vueTarget, res);
    return;
  }
  const target = safeResolve(req.url || '/');
  if (!target) {
    send(res, 403, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Forbidden');
    return;
  }

  const fallback = fs.existsSync(target) ? target : resolveRuntimeFallback(target);
  sendStaticFile(fallback || target, res);
});

const LOOPBACK_IPS = new Set(['127.0.0.1', '::1', 'localhost']);
if (!LOOPBACK_IPS.has(host)) {
  if (host === '0.0.0.0' || host === '::') {
    console.warn('[WARN] QG_DASHBOARD_HOST=' + host + ' binds the dashboard to ALL network interfaces. ' +
      'This exposes the dashboard to your LAN and any reachable network. ' +
      'Set QG_DASHBOARD_HOST=127.0.0.1 unless you know what you are doing.');
  } else {
    console.warn('[WARN] QG_DASHBOARD_HOST=' + host + ' is non-loopback. ' +
      'The dashboard server will be exposed to the network.');
  }
}

server.listen(port, host, () => {
  console.log(`QuantGod Vue workbench running at http://${host}:${port}/vue/`);
  console.log(`Legacy QuantGod_Dashboard.html redirects to /vue/.`);
});

server.on('error', (err) => {
  console.error('QuantGod dashboard server failed:', err.message);
  process.exit(1);
});
