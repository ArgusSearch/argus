import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import assert from 'node:assert/strict';

const [binary, visibility] = process.argv.slice(2);
if (!binary) throw new Error('Pass the path to the packaged Argus executable');
const dir = await mkdtemp(join(tmpdir(), 'argus-desktop-smoke-'));
const report = join(dir, 'report.json');
const child = spawn(resolve(binary), [
  `--smoke-test=${report}`,
  ...(visibility === '--visible' ? ['--smoke-visible'] : []),
], { cwd: dir, stdio: 'inherit', windowsHide: true });
const timeout = setTimeout(() => child.kill('SIGKILL'), 180_000);
try {
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', resolve);
  });
  const result = await readFile(report, 'utf8').then(JSON.parse).catch(() => null);
  console.log(result ?? { ok: false, error: 'Argus exited before writing the smoke result' });
  assert.equal(code, 0);
  assert.equal(result?.ok, true);
} finally {
  clearTimeout(timeout);
  await rm(dir, { recursive: true, force: true, maxRetries: 5 });
}
