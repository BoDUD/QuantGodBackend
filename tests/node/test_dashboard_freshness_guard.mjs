import assert from 'node:assert';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
const dashboardServerPath = path.join(repoRoot, 'Dashboard', 'dashboard_server.js');

function freePort() {
  return new Promise((resolve, reject) => {
    const reservation = net.createServer();
    reservation.once('error', reject);
    reservation.listen(0, '127.0.0.1', () => {
      const address = reservation.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      reservation.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

function waitForDashboard(child) {
  return new Promise((resolve, reject) => {
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => reject(new Error(`dashboard startup timed out\n${stdout}\n${stderr}`)), 8000);
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8');
      if (stdout.includes('QuantGod Vue workbench running')) {
        clearTimeout(timer);
        resolve();
      }
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
    });
    child.once('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

function requestJson(port, pathname) {
  return new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port, path: pathname }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        body += chunk;
      });
      res.once('end', () => {
        try {
          resolve({ statusCode: res.statusCode, payload: JSON.parse(body) });
        } catch (error) {
          reject(error);
        }
      });
    });
    req.once('error', reject);
  });
}

function localTimestamp(timeMs) {
  const date = new Date(timeMs);
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

test('latest dashboard rejects touched old writer evidence and disables optional secondary by default', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-dashboard-freshness-'));
  const oldWriterTime = Date.now() - 10 * 60 * 1000;
  fs.writeFileSync(
    path.join(runtimeDir, 'QuantGod_Dashboard.json'),
    JSON.stringify({ timestamp: localTimestamp(oldWriterTime), runtime: { tradeStatus: 'READY' } }),
  );
  fs.writeFileSync(
    path.join(runtimeDir, 'QuantGod_MT5_TimerHeartbeat.txt'),
    `localTime=${localTimestamp(oldWriterTime)}\n`,
  );
  const port = await freePort();
  const child = spawn(process.execPath, [dashboardServerPath], {
    cwd: repoRoot,
    env: {
      ...process.env,
      QG_DASHBOARD_HOST: '127.0.0.1',
      QG_DASHBOARD_PORT: String(port),
      QG_RUNTIME_DIR: runtimeDir,
      QG_LATEST_DASHBOARD_FRESH_MS: '180000',
      QG_MT5_SECONDARY_ENABLED: '0',
      QG_MT5_TRADING_ENABLED: '0',
      QG_TELEGRAM_SEND_ENABLED: '0',
      QG_TELEGRAM_COMMANDS_ALLOWED: '0',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => {
    if (child.exitCode === null) child.kill('SIGTERM');
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  });
  await waitForDashboard(child);

  const latest = await requestJson(port, '/api/latest');
  assert.equal(latest.statusCode, 200);
  assert.equal(latest.payload._freshness.status, 'STALE_DASHBOARD_SNAPSHOT');
  assert.equal(latest.payload._freshness.fresh, false);
  assert.equal(latest.payload._freshness.maxAgeSeconds, 180);
  assert.equal(latest.payload._freshness.freshnessBasis, 'oldest_writer_evidence');
  assert.match(latest.payload._freshness.oldestEvidenceSource, /dashboard_timestamp|heartbeat_local_time/);
  assert.equal(latest.payload.safety.orderSendAllowed, false);
  assert.equal(latest.payload.currentRuntimeUsable, false);

  const secondary = await requestJson(port, '/api/mt5-readonly-secondary/snapshot');
  assert.equal(secondary.statusCode, 200);
  assert.equal(secondary.payload.status, 'DISABLED');
  assert.equal(secondary.payload.optional, true);
  assert.equal(secondary.payload.enabled, false);
  assert.equal(secondary.payload.snapshotFresh, true);
  assert.deepEqual(secondary.payload._freshness.blockers, []);
  assert.equal(secondary.payload.safety.orderSendAllowed, false);
});

test('secondary Shadow auth diagnostics expose the reason without leaking the raw login', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-dashboard-primary-'));
  const secondaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-dashboard-secondary-'));
  const secondaryFiles = path.join(secondaryRoot, 'MQL5', 'Files');
  const logDir = path.join(secondaryRoot, 'logs');
  fs.mkdirSync(secondaryFiles, { recursive: true });
  fs.mkdirSync(logDir, { recursive: true });
  const now = new Date();
  const dateName = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
  const logDate = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')}`;
  const privateLogin = '90000002';
  const brokerServer = ['HFMarketsGlobal', 'Live16'].join('-');
  fs.writeFileSync(
    path.join(secondaryFiles, 'QuantGod_Dashboard.json'),
    JSON.stringify({
      timestamp: localTimestamp(now.getTime()),
      account: {
        number: privateLogin,
        server: brokerServer,
        currency: 'USD',
        balance: 1000,
        equity: 1000,
      },
      runtime: {
        terminalConnected: false,
        brokerConnected: false,
        accountAuthorized: true,
        tradeAllowed: false,
      },
    }),
  );
  fs.writeFileSync(
    path.join(logDir, `${dateName}.log`),
    `${logDate} 00:00:01.000 Network '${privateLogin}': authorization on ${brokerServer} failed (Invalid account)\n`,
  );
  const port = await freePort();
  const child = spawn(process.execPath, [dashboardServerPath], {
    cwd: repoRoot,
    env: {
      ...process.env,
      QG_DASHBOARD_HOST: '127.0.0.1',
      QG_DASHBOARD_PORT: String(port),
      QG_RUNTIME_DIR: runtimeDir,
      QG_MT5_SECONDARY_SHADOW_ENABLED: '1',
      QG_MT5_SECONDARY_FILES_DIR: secondaryFiles,
      QG_MT5_TRADING_ENABLED: '0',
      QG_TELEGRAM_SEND_ENABLED: '0',
      QG_TELEGRAM_COMMANDS_ALLOWED: '0',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => {
    if (child.exitCode === null) child.kill('SIGTERM');
    fs.rmSync(runtimeDir, { recursive: true, force: true });
    fs.rmSync(secondaryRoot, { recursive: true, force: true });
  });
  await waitForDashboard(child);

  const secondary = await requestJson(port, '/api/mt5-readonly-secondary/snapshot');
  assert.equal(secondary.statusCode, 200);
  assert.equal(secondary.payload.terminal.authLogStatus, 'AUTH_FAILED');
  assert.equal(secondary.payload.terminal.lastAuthFailure.reason, 'Invalid account');
  assert.equal(secondary.payload.terminal.lastAuthFailure.login, undefined);
  assert.equal(secondary.payload.account.login, undefined);
  assert.equal(secondary.payload.account.loginMasked, '••••0002');
  assert.equal(secondary.payload.connection.accountIdentityPresent, true);
  assert.equal(secondary.payload.connection.accountAuthorized, false);
  assert.equal(secondary.payload.connection.brokerSessionConnected, false);
  assert.equal(secondary.payload.connection.brokerConnected, false);
  assert.equal(secondary.payload.connection.operationalConnected, false);
  assert.equal(secondary.payload.connection.readReady, false);
  assert.equal(secondary.payload.connection.writerFresh, true);
  assert.equal(typeof secondary.payload.connection.processRunning, 'boolean');
  assert.equal(secondary.payload.runtime.accountIdentityPresent, true);
  assert.equal(secondary.payload.runtime.accountAuthorized, false);
  assert.equal(secondary.payload.runtime.brokerSessionConnected, false);
  assert.equal(secondary.payload.runtime.connected, false);
  assert.equal(JSON.stringify(secondary.payload).includes(privateLogin), false);
  assert.equal(secondary.payload.safety.orderSendAllowed, false);

  fs.writeFileSync(
    path.join(secondaryFiles, 'QuantGod_Dashboard.json'),
    JSON.stringify({
      timestamp: localTimestamp(Date.now()),
      account: {
        number: privateLogin,
        server: brokerServer,
        currency: 'USD',
        balance: 1000,
        equity: 1000,
      },
      runtime: {
        terminalConnected: true,
        brokerSessionConnected: true,
        accountIdentityPresent: true,
        accountAuthorized: true,
        tradeAllowed: false,
      },
    }),
  );
  fs.appendFileSync(
    path.join(logDir, `${dateName}.log`),
    `${logDate} 00:00:02.000 Network '${privateLogin}': authorized on ${brokerServer}\n`,
  );

  const recovered = await requestJson(port, '/api/mt5-readonly-secondary/snapshot');
  assert.equal(recovered.payload.terminal.authLogStatus, 'AUTHORIZED');
  assert.equal(recovered.payload.connection.accountIdentityPresent, true);
  assert.equal(recovered.payload.connection.brokerSessionConnected, true);
  assert.equal(recovered.payload.connection.accountAuthorized, true);
  assert.equal(recovered.payload.connection.operationalConnected, true);
  assert.equal(JSON.stringify(recovered.payload).includes(privateLogin), false);
});
