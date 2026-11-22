import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repo = dirname(desktop);
const build = join(desktop, 'build');
const output = join(build, 'sidecar');
const windows = process.platform === 'win32';
const target = windows ? '--win' : '--mac';
if (!windows && process.platform !== 'darwin') throw new Error('Build on macOS or Windows');
if (windows && process.arch !== 'x64') throw new Error('Use x64 Node.js for the Windows installer');

function run(command, args, cwd, env = process.env) {
  const result = spawnSync(command, args, { cwd, env, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

run(process.execPath, [process.env.npm_execpath, 'run', 'build', '--', '--outDir', join(build, 'web'),
  '--emptyOutDir', '--mode', 'desktop'], join(repo, 'web'), {
  ...process.env,
  VITE_ARGUS_API_URL: '',
  VITE_ARGUS_STATIC_REPLAY: '0',
  RAYON_NUM_THREADS: '2',
});

run('uv', [
  'run', '--frozen', '--no-dev', '--python', '3.13',
  '--with', 'pyinstaller==6.22.3', '--with', 'keyring==25.7.0',
  'python', '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'argus-sidecar',
  '--contents-directory', 'src', '--paths', join(repo, 'src'), '--python-option', 'X utf8',
  '--workpath', join(build, 'pyinstaller'), '--specpath', build, '--distpath', output,
  '--hidden-import', 'uvicorn.loops.asyncio', '--hidden-import', 'uvicorn.protocols.http.h11_impl',
  '--hidden-import', 'uvicorn.lifespan.on', '--collect-data', 'sqlglot',
  join(desktop, 'sidecar', 'entry.py'),
], repo, { ...process.env, PYINSTALLER_CONFIG_DIR: join(build, 'pyinstaller-cache') });

run(process.execPath, [join(desktop, 'node_modules', 'electron-builder', 'out', 'cli', 'cli.js'),
  target, '--publish', 'never', `--${process.arch}`], desktop, { ...process.env, CSC_IDENTITY_AUTO_DISCOVERY: 'false' });
