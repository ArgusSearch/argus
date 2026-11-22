const assert = require('node:assert/strict');
const { setTimeout: delay } = require('node:timers/promises');

function evaluate(win, code) {
  const timeout = delay(8000, undefined, { ref: false }).then(() => { throw new Error('Renderer did not respond'); });
  return Promise.race([win.webContents.executeJavaScript(code), timeout]);
}

async function verify(win, service, info, settings) {
  const health = await service.request('/health');
  assert.equal(health.status, 200, 'The bundled API answers /health');
  assert.equal((await health.json()).mode, 'replay');
  assert.equal((await fetch(`${info.origin}/health`, { signal: AbortSignal.timeout(4000) })).status, 403);
  assert.equal(win.getTitle(), 'Argus · Simulated shop · Sealed replay');
  assert.deepEqual(await evaluate(settings, 'window.argusSettings.status()'),
    { mode: 'replay', keychainUnavailable: false });

  const script = await evaluate(win, 'document.querySelector(\'script[type=module][src]\')?.getAttribute(\'src\')');
  assert.ok(script?.startsWith('/assets/'), 'The page references the bundled entry module');
  const asset = await service.request(script);
  assert.equal(asset.status, 200, 'The local server responds with the entry module');
  assert.match(asset.headers.get('content-type') ?? '', /^text\/javascript\b/);
  await asset.body?.cancel();

  // Require the bundled React workspace to mount, even when its native window is hidden.
  let rendered;
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline && !rendered) {
    rendered = await evaluate(win, `Boolean(document.querySelector('#root nav[aria-label="sections"]'))`);
    if (!rendered) await delay(250);
  }
  if (!rendered) assert.fail(`Mission Control did not render (${await evaluate(win, 'document.body.innerText.slice(0, 200)')})`);

  const runId = new URL(win.webContents.getURL()).searchParams.get('agentrun');
  assert.ok(runId, 'The workspace opened the sealed replay');
  const snapshot = await service.request(`/demo/snapshot?run_id=${encodeURIComponent(runId)}`);
  assert.equal(snapshot.status, 200);
  const { state } = await snapshot.json();
  assert.equal(state.variant, 'agent');
  assert.equal(state.scenario, 's4');

  assert.equal(await service.stop(), 0, 'The sidecar shut down gracefully');
  await assert.rejects(fetch(`${info.origin}/health`, { signal: AbortSignal.timeout(4000) }),
    'The loopback listener closed when the sidecar exited');
  return { ok: true, mode: state.variant, scenario: state.scenario, health: health.status, sidecar: 'stopped' };
}

module.exports = { verify };
