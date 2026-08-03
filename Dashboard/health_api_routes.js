const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const DEFAULT_WRITER_FRESH_MS = 180000;
const DEFAULT_QUOTE_FRESH_SECONDS = 30;

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
  sendJson(res, statusCode, {
    ok: false,
    endpoint,
    error: error && error.message ? error.message : String(error),
  });
}

function isHealthPath(url) {
  const pathname = String(url || '').split('?')[0];
  return pathname === '/healthz'
    || pathname === '/readyz'
    || pathname === '/api/operator/overview';
}

function readJson(filePath) {
  if (!fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''));
  } catch (_) {
    return null;
  }
}

function firstExistingJson(candidates) {
  for (const filePath of candidates) {
    const payload = readJson(filePath);
    if (payload && typeof payload === 'object') {
      return { filePath, payload, stat: fs.statSync(filePath) };
    }
  }
  return null;
}

function parseEvidenceTime(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const normalized = value.trim().replace(
    /^(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/,
    '$1-$2-$3T$4:$5:$6',
  );
  const parsed = Date.parse(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function valueAt(payload, dottedPath) {
  return dottedPath.split('.').reduce((current, key) => (
    current && typeof current === 'object' ? current[key] : undefined
  ), payload);
}

function firstValue(payload, paths, fallback = undefined) {
  for (const dottedPath of paths) {
    const value = valueAt(payload, dottedPath);
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return fallback;
}

function booleanValue(value) {
  if (value === true || value === false) return value;
  const normalized = String(value ?? '').trim().toLowerCase();
  if (['1', 'true', 'yes', 'connected', 'authorized'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'disconnected', 'unauthorized'].includes(normalized)) return false;
  return null;
}

function finiteNumber(value, fallback = null) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function canonicalRootIdentity(runtimeDir) {
  const resolved = fs.existsSync(runtimeDir)
    ? fs.realpathSync(runtimeDir)
    : path.resolve(runtimeDir);
  return {
    resolved,
    id: crypto.createHash('sha256').update(resolved).digest('hex').slice(0, 16),
    exists: fs.existsSync(resolved),
  };
}

function writerEvidence(runtimeDir, nowMs, maxAgeMs) {
  const filePath = path.join(runtimeDir, 'QuantGod_Dashboard.json');
  if (!fs.existsSync(filePath)) {
    return { available: false, fresh: false, filePath, ageSeconds: null, observedAt: '' };
  }
  const stat = fs.statSync(filePath);
  const payload = readJson(filePath);
  if (!payload) {
    return {
      available: false,
      fresh: false,
      parseError: true,
      filePath,
      ageSeconds: Math.max(0, (nowMs - stat.mtimeMs) / 1000),
      observedAt: stat.mtime.toISOString(),
    };
  }
  const embeddedTime = parseEvidenceTime(firstValue(payload, [
    'timestamp',
    'generatedAt',
    'observedAt',
    'runtime.localTime',
  ], ''));
  // A touched stale file must not become fresh. Use the older of the writer
  // timestamp and file mtime whenever both are present.
  const observedMs = embeddedTime === null
    ? stat.mtimeMs
    : Math.min(embeddedTime, stat.mtimeMs);
  const ageSeconds = Math.max(0, (nowMs - observedMs) / 1000);
  return {
    available: true,
    fresh: ageSeconds * 1000 <= maxAgeMs,
    filePath,
    ageSeconds,
    observedAt: new Date(observedMs).toISOString(),
    payload,
  };
}

function marketSession(nowMs, quoteFresh) {
  const now = new Date(nowMs);
  const day = now.getUTCDay();
  const hour = now.getUTCHours();
  // Conservative FX weekend envelope. The broker session remains the future
  // source of truth; this fallback only prevents a weekend from looking READY.
  const weekendClosed = day === 6 || (day === 0 && hour < 21) || (day === 5 && hour >= 22);
  if (weekendClosed) {
    return { state: 'CLOSED', reasonCode: 'WEEKEND' };
  }
  if (quoteFresh) {
    return { state: 'OPEN', reasonCode: 'QUOTE_FRESH' };
  }
  return { state: 'UNKNOWN', reasonCode: 'QUOTE_STALE' };
}

function reportState(report, statusPaths, nowMs, maxAgeSeconds) {
  if (!report) {
    return {
      available: false,
      status: 'MISSING',
      freshness: 'MISSING',
      ready: false,
      observedAt: '',
      ageSeconds: null,
      maxAgeSeconds,
    };
  }
  const status = String(firstValue(report.payload, statusPaths, 'UNKNOWN')).toUpperCase();
  const ageSeconds = Math.max(0, (nowMs - report.stat.mtimeMs) / 1000);
  const fresh = ageSeconds <= maxAgeSeconds;
  const ready = fresh && ['PASS', 'READY', 'OK', 'COMPLETED', 'FRESH'].includes(status);
  return {
    available: true,
    ready,
    status,
    freshness: fresh ? 'FRESH' : 'STALE',
    ageSeconds,
    maxAgeSeconds,
    observedAt: report.stat.mtime.toISOString(),
    filePath: report.filePath,
  };
}

function diskState(runtimeDir) {
  if (typeof fs.statfsSync !== 'function' || !fs.existsSync(runtimeDir)) {
    return { available: false, freeRatio: null, status: 'UNKNOWN' };
  }
  try {
    const stats = fs.statfsSync(runtimeDir);
    const totalBytes = Number(stats.blocks) * Number(stats.bsize);
    const freeBytes = Number(stats.bavail) * Number(stats.bsize);
    const freeRatio = totalBytes > 0 ? freeBytes / totalBytes : null;
    return {
      available: true,
      totalBytes,
      freeBytes,
      freeRatio,
      status: freeRatio === null ? 'UNKNOWN' : freeRatio < 0.1 ? 'CRITICAL' : freeRatio < 0.2 ? 'WARN' : 'PASS',
    };
  } catch (error) {
    return { available: false, freeRatio: null, status: 'UNKNOWN', error: error.message };
  }
}

function buildOperatorOverview(ctx, nowMs = Date.now()) {
  const runtimeRoot = canonicalRootIdentity(ctx.defaultRuntimeDir);
  const maxWriterAgeMs = finiteNumber(process.env.QG_LATEST_DASHBOARD_FRESH_MS, DEFAULT_WRITER_FRESH_MS);
  const maxQuoteAgeSeconds = finiteNumber(process.env.QG_QUOTE_FRESH_SECONDS, DEFAULT_QUOTE_FRESH_SECONDS);
  const writer = writerEvidence(runtimeRoot.resolved, nowMs, maxWriterAgeMs);
  const dashboard = writer.payload || {};
  const runtime = dashboard.runtime && typeof dashboard.runtime === 'object' ? dashboard.runtime : {};
  const account = dashboard.account && typeof dashboard.account === 'object' ? dashboard.account : {};
  const brokerSessionSignal = booleanValue(firstValue(dashboard, [
    'runtime.brokerSessionConnected',
    'runtime.brokerConnected',
    'runtime.terminalConnected',
  ], null));
  const accountAuthorizationSignal = booleanValue(firstValue(dashboard, ['runtime.accountAuthorized'], null));
  const explicitIdentitySignal = booleanValue(firstValue(dashboard, ['runtime.accountIdentityPresent'], null));
  const accountLogin = String(firstValue(account, ['login', 'number', 'loginMasked'], '')).trim();
  const accountLoginDigits = accountLogin.replace(/[^0-9]/g, '');
  const accountLoginPresent = Boolean(accountLoginDigits && /[1-9]/.test(accountLoginDigits));
  const accountServer = String(firstValue(account, ['server'], '')).trim();
  const accountIdentityPresent = explicitIdentitySignal === null
    ? Boolean(accountLoginPresent && accountServer)
    : explicitIdentitySignal;
  const processSignal = booleanValue(firstValue(runtime, ['processRunning'], null));
  // A fresh writer proves the EA process was active recently for legacy
  // snapshots that predate the explicit processRunning field.
  const processRunning = writer.fresh && (processSignal === null || processSignal === true);
  const processRunningKnown = writer.fresh;
  const brokerConnectionKnown = writer.fresh && brokerSessionSignal !== null;
  const brokerSessionConnected = brokerConnectionKnown && brokerSessionSignal === true;
  const accountAuthorizationKnown = writer.fresh
    && accountAuthorizationSignal !== null
    && brokerConnectionKnown;
  const accountAuthorized = accountAuthorizationKnown
    && accountAuthorizationSignal === true
    && brokerSessionConnected
    && accountIdentityPresent;
  const quoteAgeSeconds = finiteNumber(firstValue(dashboard, ['runtime.tickAgeSeconds'], null), null);
  const quoteFresh = writer.fresh && quoteAgeSeconds !== null && quoteAgeSeconds <= maxQuoteAgeSeconds;
  const session = marketSession(nowMs, quoteFresh);

  const history = reportState(firstExistingJson([
    path.join(runtimeRoot.resolved, 'backtest', 'QuantGod_USDJPYHistoryProductionStatus.json'),
    path.join(runtimeRoot.resolved, 'QuantGod_USDJPYHistoryProductionStatus.json'),
  ]), ['productionStatus', 'status', 'state'], nowMs, finiteNumber(process.env.QG_HISTORY_STATUS_FRESH_SECONDS, 7200));
  const automation = reportState(firstExistingJson([
    path.join(runtimeRoot.resolved, 'automation', 'QuantGod_AutomationChainLatest.json'),
  ]), ['state', 'status', 'runStatus'], nowMs, finiteNumber(process.env.QG_AUTOMATION_STATUS_FRESH_SECONDS, 900));
  const productionEvidence = reportState(firstExistingJson([
    path.join(runtimeRoot.resolved, 'production_validation', 'QuantGod_ProductionEvidenceValidationReport.json'),
    path.join(runtimeRoot.resolved, 'QuantGod_ProductionEvidenceValidationReport.json'),
  ]), ['report.status', 'status', 'overallStatus'], nowMs, finiteNumber(process.env.QG_PRODUCTION_EVIDENCE_FRESH_SECONDS, 86400));
  const disk = diskState(runtimeRoot.resolved);

  const marketNeutral = session.state === 'CLOSED';
  const mt5MonitorReady = writer.fresh
    && processRunning
    && brokerSessionConnected
    && accountAuthorized
    && (quoteFresh || marketNeutral);
  const dataReady = history.ready;
  const automationReady = automation.ready;
  const evidenceReady = productionEvidence.ready;
  const diskReady = disk.status !== 'CRITICAL';
  const serviceReady = runtimeRoot.exists && writer.available;
  const operationalReady = serviceReady
    && mt5MonitorReady
    && dataReady
    && automationReady
    && evidenceReady
    && diskReady;

  const blockedReasons = [];
  if (!runtimeRoot.exists) blockedReasons.push('CANONICAL_RUNTIME_MISSING');
  if (!writer.available) blockedReasons.push('MT5_WRITER_MISSING');
  else if (!writer.fresh) blockedReasons.push('MT5_WRITER_STALE');
  if (writer.fresh && !processRunning) blockedReasons.push('MT5_PROCESS_NOT_RUNNING');
  if (writer.fresh && !brokerSessionConnected) blockedReasons.push('BROKER_NOT_CONFIRMED');
  if (writer.fresh && !accountAuthorized) blockedReasons.push('ACCOUNT_NOT_AUTHORIZED');
  if (!quoteFresh && !marketNeutral) blockedReasons.push('QUOTE_STALE');
  if (!dataReady) blockedReasons.push(`HISTORY_${history.status}_${history.freshness}`);
  if (!automationReady) blockedReasons.push(`AUTOMATION_${automation.status}_${automation.freshness}`);
  if (!evidenceReady) blockedReasons.push(`EVIDENCE_${productionEvidence.status}_${productionEvidence.freshness}`);
  if (!diskReady) blockedReasons.push('DISK_CRITICAL');

  return {
    schema: 'quantgod.operator_overview.v1',
    generatedAt: new Date(nowMs).toISOString(),
    mode: 'SHADOW_READONLY',
    service: {
      processAlive: true,
      serviceReady,
      uptimeSeconds: process.uptime(),
      pid: process.pid,
      build: process.env.QG_BUILD_ID || process.env.GIT_COMMIT || 'local',
    },
    canonicalDataRoot: runtimeRoot,
    mt5: {
      writerFresh: writer.fresh,
      writerAgeSeconds: writer.ageSeconds,
      writerObservedAt: writer.observedAt,
      processRunning,
      processRunningKnown,
      brokerSessionConnected,
      // Compatibility alias retained for existing frontend clients.
      brokerConnected: brokerSessionConnected,
      brokerConnectionKnown,
      accountIdentityPresent,
      accountIdentityKnown: writer.available,
      accountAuthorized,
      accountAuthorizationKnown,
      quoteFresh,
      quoteAgeSeconds,
      marketSession: session,
      monitorReady: mt5MonitorReady,
      tradingReady: false,
    },
    data: { history, ready: dataReady },
    automation: { ...automation, ready: automationReady },
    evidence: { production: productionEvidence, ready: evidenceReady },
    disk,
    operationalReady,
    overallStatus: operationalReady ? 'PASS' : blockedReasons.length ? 'BLOCKED' : 'WARN',
    blockedReasons,
    safety: {
      advisoryOnly: true,
      executionLaneExists: false,
      orderSendAllowed: false,
      closeAllowed: false,
      cancelAllowed: false,
      liveExpansionAllowed: false,
      unattendedLiveExpansionAllowed: false,
      operatorApprovalRequired: true,
      mutatesMt5: false,
    },
  };
}

async function handle(req, res, ctx) {
  const pathname = String(req.url || '').split('?')[0];
  if (req.method !== 'GET') {
    sendJson(res, 405, { ok: false, endpoint: pathname, error: 'method_not_allowed' });
    return;
  }
  if (pathname === '/healthz') {
    sendJson(res, 200, {
      ok: true,
      status: 'UP',
      generatedAt: new Date().toISOString(),
      uptimeSeconds: process.uptime(),
      pid: process.pid,
      mode: 'SHADOW_READONLY',
      safety: { orderSendAllowed: false, executionLaneExists: false },
    });
    return;
  }
  const overview = buildOperatorOverview(ctx);
  if (pathname === '/readyz') {
    sendJson(res, overview.operationalReady ? 200 : 503, {
      ok: overview.operationalReady,
      status: overview.operationalReady ? 'READY' : 'NOT_READY',
      ...overview,
    });
    return;
  }
  if (pathname === '/api/operator/overview') {
    sendJson(res, 200, { ok: true, endpoint: pathname, payload: overview });
    return;
  }
  sendJson(res, 404, { ok: false, endpoint: pathname, error: 'health_route_not_found' });
}

module.exports = {
  buildOperatorOverview,
  isHealthPath,
  handle,
  marketSession,
  sendError,
};
