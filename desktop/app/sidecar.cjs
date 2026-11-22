const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const { once } = require('node:events');
const { createInterface } = require('node:readline');
const { setTimeout: delay } = require('node:timers/promises');

const AUTH_HEADER = 'X-Argus-Desktop';

function startProcess(executable, command, stdio, signal) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([name]) =>
    !/^(ARGUS_|ANTHROPIC_|OPENAI_|PYTHON|KEYRING_|KEYCHAIN_PATH$)/i.test(name)));
  const child = spawn(executable, [], {
    env: { ...env, OMP_NUM_THREADS: '2', OPENBLAS_NUM_THREADS: '2', VECLIB_MAXIMUM_THREADS: '2' },
    stdio: ['pipe', stdio, 'ignore'],
    signal,
    windowsHide: true,
  });
  child.stdin.on('error', () => {});
  const done = new Promise((resolve) => {
    child.once('error', () => resolve(1));
    child.once('exit', (code) => resolve(code ?? 1));
  });
  child.stdin.write(`${JSON.stringify(command)}\n`);
  return { child, done };
}

async function stopProcess(child, done) {
  child.stdin.end();
  const force = setTimeout(() => child.kill('SIGKILL'), 40_000);
  try {
    return await done;
  } finally {
    clearTimeout(force);
  }
}

function launch(executable, { data, replayOnly }) {
  const token = randomBytes(32).toString('hex');
  const { child, done } = startProcess(executable, { operation: 'serve', data, replayOnly, token }, 'pipe');
  const abort = new AbortController();
  const timeout = AbortSignal.any([abort.signal, AbortSignal.timeout(120_000)]);
  const headers = { [AUTH_HEADER]: token };
  let stopping = false;
  let stopPromise;
  let origin;
  const lines = createInterface({ input: child.stdout });
  const announcement = once(lines, 'line', { signal: timeout });
  void done.then(() => {
    abort.abort();
    lines.close();
  });

  async function request(path, init = {}) {
    return fetch(new URL(path, origin), {
      ...init,
      headers: { ...init.headers, ...headers },
      redirect: 'error',
      signal: AbortSignal.any([abort.signal, AbortSignal.timeout(4000)]),
    });
  }

  const ready = (async () => {
    const [line] = await announcement;
    const info = JSON.parse(line);
    if (!Number.isInteger(info.port) || info.port < 1 || info.port > 65535 ||
        !['replay', 'live'].includes(info.mode)) {
      throw new Error('Invalid local API startup response');
    }
    origin = `http://127.0.0.1:${info.port}`;
    while (!timeout.aborted) {
      const health = await request('/health').then((res) => res.ok && res.json()).catch(() => false);
      if (health?.status === 'ok' && health.mode === info.mode) return { ...info, origin };
      await delay(200, undefined, { signal: timeout });
    }
    throw new Error('The local API did not become ready');
  })();

  return {
    headers,
    done,
    ready,
    request,
    get stopping() { return stopping; },
    stop() {
      stopping = true;
      abort.abort();
      return stopPromise ??= stopProcess(child, done);
    },
  };
}

async function changeKey(executable, key, signal) {
  const command = key === null ? { operation: 'remove' } : { operation: 'save', key };
  const { child, done } = startProcess(executable, command, 'ignore', signal);
  child.stdin.end();
  // The OS can display a permission prompt while the credential store is unlocked.
  const force = setTimeout(() => child.kill('SIGKILL'), 90_000);
  try {
    return (await done) === 0;
  } finally {
    clearTimeout(force);
  }
}

module.exports = { launch, changeKey };
