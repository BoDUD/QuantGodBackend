import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..');
const source = fs.readFileSync(
  path.join(repoRoot, 'Dashboard', 'usdjpy_strategy_lab_api_routes.js'),
  'utf8',
);

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
