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
    child.once('exit', (code) => {
      if (!stdout.includes('QuantGod Vue workbench running')) {
        clearTimeout(timer);
        reject(new Error(`dashboard exited before startup (${code})\n${stdout}\n${stderr}`));
      }
    });
  });
}

function request(port, pathname, { method = 'GET', headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { hostname: '127.0.0.1', port, path: pathname, method, headers },
      (res) => {
        res.resume();
        res.once('end', () => resolve({ statusCode: res.statusCode, headers: res.headers }));
      },
    );
    req.once('error', reject);
    req.end();
  });
}

function assertSecurityHeaders(response) {
  assert.match(response.headers['content-security-policy'] || '', /frame-ancestors 'none'/);
  assert.equal(response.headers['x-frame-options'], 'DENY');
  assert.equal(response.headers['x-content-type-options'], 'nosniff');
  assert.equal(response.headers['referrer-policy'], 'no-referrer');
  assert.equal(
    response.headers['permissions-policy'],
    'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  );
}

test('dashboard applies security headers to static, API, module, preflight, and error responses', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'quantgod-dashboard-security-'));
  const port = await freePort();
  const child = spawn(process.execPath, [dashboardServerPath], {
    cwd: repoRoot,
    env: {
      ...process.env,
      QG_DASHBOARD_HOST: '127.0.0.1',
      QG_DASHBOARD_PORT: String(port),
      QG_RUNTIME_DIR: runtimeDir,
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

  const responses = await Promise.all([
    request(port, '/api_perf_cache.js'),
    request(port, '/api/daily-autopilot'),
    request(port, '/api/state/status', {
      method: 'POST',
      headers: { 'X-QuantGod-Local': '1' },
    }),
    request(port, '/', { method: 'OPTIONS' }),
    request(port, '/api/daily-autopilot', { method: 'POST' }),
    request(port, '/quantgod-security-header-not-found.txt'),
  ]);

  assert.equal(responses[0].statusCode, 200);
  assert.equal(responses[1].statusCode, 200);
  assert.equal(responses[2].statusCode, 405);
  assert.equal(responses[3].statusCode, 204);
  assert.equal(responses[4].statusCode, 403);
  assert.equal(responses[5].statusCode, 404);
  responses.forEach(assertSecurityHeaders);
});
