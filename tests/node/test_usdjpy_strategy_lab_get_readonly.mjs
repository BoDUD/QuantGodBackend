import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..');
const source = fs.readFileSync(
  path.join(repoRoot, 'Dashboard', 'usdjpy_strategy_lab_api_routes.js'),
  'utf8',
);
const require = createRequire(import.meta.url);
const strategyLabRoutes = require('../../Dashboard/usdjpy_strategy_lab_api_routes.js');

test('USDJPY Strategy Lab GET routes never promote query parameters into write flags', () => {
  assert.doesNotMatch(
    source,
    /searchParams\.get\(['"]write['"]\)[^\n]*args\.push\(['"]--write['"]\)/,
  );
  assert.match(
    source,
    /const readonlyArgs = args\.filter\(\(arg\) => !\[['"]--write['"], ['"]--refresh['"], ['"]--send['"]\]\.includes\(arg\)\)/,
  );
});

test('GA GET status is read-only and GA mutation remains POST-only', () => {
  const gaGet = source.match(
    /if \(req\.method === 'GET' && \(pathname === '\/api\/usdjpy-strategy-lab\/ga'[\s\S]*?\n  }/,
  );
  assert.ok(gaGet);
  assert.doesNotMatch(gaGet[0], /--write|run-generation/);
  assert.match(
    source,
    /req\.method === 'POST' && pathname === '\/api\/usdjpy-strategy-lab\/ga\/run-generation'[\s\S]*?'run-generation', '--write'/,
  );
});

test('GET telegram-text is always a delivery-false preview', () => {
  const payload = strategyLabRoutes.normalizeTelegramPreviewPayload({ ok: true, text: 'preview' });
  assert.equal(payload.ok, true);
  assert.equal(payload.previewOnly, true);
  assert.equal(payload.sendRequested, false);
  assert.equal(payload.sent, false);
  assert.equal(payload.deliveryOk, false);
  assert.equal(payload.delivery.status, 'PREVIEW_ONLY');
  assert.equal(payload.delivery.ok, false);

  const sendPromotions = source.match(/searchParams\.get\('send'\)[^\n]*args\.push\('--send'\)/g) || [];
  assert.equal(sendPromotions.length, 0);
  assert.match(
    source,
    /req\.method === 'POST' && pathname === '\/api\/usdjpy-strategy-lab\/telegram-gateway\/dispatch'[\s\S]*?explicitTelegramDelivery\(body\)[\s\S]*?delivery\.send\) args\.push\('--send'\)/,
  );
});

test('Telegram Gateway dispatch requires body send=true and dryRun=false', () => {
  for (const body of [
    {},
    { send: true },
    { dryRun: false },
    { send: true, dryRun: true },
    { send: 'yes', dry_run: 'invalid' },
  ]) {
    assert.equal(strategyLabRoutes.explicitTelegramDelivery(body).send, false);
  }
  assert.deepEqual(strategyLabRoutes.explicitTelegramDelivery({ send: true, dryRun: false }), {
    send: true,
    dryRun: false,
    sendExplicitlyRequested: true,
    dryRunExplicitlyDisabled: true,
  });
  assert.match(source, /url\.searchParams\.has\('send'\)/);
  assert.match(source, /TELEGRAM_SEND_QUERY_REJECTED/);
});

test('GET telegram-text rejects every send query before running a sender', async () => {
  let statusCode = null;
  let responseBody = '';
  const response = {
    writeHead(code) {
      statusCode = code;
    },
    end(body) {
      responseBody = body;
    },
  };
  await strategyLabRoutes.handle(
    {
      method: 'GET',
      url: '/api/usdjpy-strategy-lab/ga/telegram-text?send=1',
    },
    response,
    { defaultRuntimeDir: 'runtime', repoRoot },
  );

  assert.equal(statusCode, 400);
  const payload = JSON.parse(responseBody);
  assert.equal(payload.ok, false);
  assert.equal(payload.previewOnly, true);
  assert.equal(payload.sendRequested, true);
  assert.equal(payload.sendRejected, true);
  assert.equal(payload.sent, false);
  assert.equal(payload.deliveryOk, false);
  assert.equal(payload.delivery.status, 'REJECTED');
});
