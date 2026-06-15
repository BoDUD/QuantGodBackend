import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import test from 'node:test';

const repo = process.cwd();

function gitLines(args) {
  return execFileSync('git', args, {
    cwd: repo,
    encoding: 'utf8',
  })
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

test('Backend product repo does not track local Codex skills', () => {
  const trackedCodexFiles = gitLines(['ls-files', '.codex']);
  const gitignore = fs.readFileSync('.gitignore', 'utf8');

  assert.deepEqual(trackedCodexFiles, []);
  assert.match(gitignore, /^\.codex\/$/m);
});
