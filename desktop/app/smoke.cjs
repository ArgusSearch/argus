const assert = require('node:assert/strict');
const { setTimeout: delay } = require('node:timers/promises');

async function verify(win, service, info, settings) {
  const health = await service.request('/health');
  assert.equal(health.status, 200, 'The bundled API answers /health');
  assert.equal((await health.json()).mode, 'replay');
  assert.equal((await fetch(`${info.origin}/health`, { signal: AbortSignal.timeout(4000) })).status, 403);
  assert.equal(win.getTitle(), 'Argus · Simulated shop · Sealed replay');
  assert.deepEqual(await settings.webContents.executeJavaScript('window.argusSettings.status()'),
    { mode: 'replay', keychainUnavailable: false });

  // The actual React workspace must start and follow the sealed agent recording.
  let runId;
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline && !runId) {
    runId = await win.webContents.executeJavaScript(`
      document.querySelector('[aria-label="agent demo"]') &&
        new URLSearchParams(location.search).get('agentrun')
    `);
    if (!runId) await delay(250);
  }
  if (!runId) {
    const replay = await service.request('/demo/start', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ scenario: 's4', variant: 'agent', speed: 1 }),
    });
    const diagnosis = replay.ok ? 'the API can start S4 directly' : `${replay.status} ${await replay.text()}`;
    assert.fail(`Mission Control did not start the sealed agent recording (${diagnosis})`);
  }
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
