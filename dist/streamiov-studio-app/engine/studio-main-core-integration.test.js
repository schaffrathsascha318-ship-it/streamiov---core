'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { loadStudioMain } = require('./studio-main-harness.cjs');
const { isWavBuffer } = require('./audio-file-validation.js');

const ROOT = path.resolve(__dirname, '../../..');
const CORE_HELPER = path.join(ROOT, 'tests', 'support', 'studio_core_server.py');
const PYTHON = spawnSync('python3', ['--version'], { stdio: 'ignore' }).status === 0 ? 'python3' : null;

async function startCore(extraEnv = {}) {
  const child = spawn(PYTHON, [CORE_HELPER], {
    cwd: ROOT,
    env: { ...process.env, STREAMIOV_TOKEN_KEY: 'studio-integration-token-key-0123456789', ...extraEnv },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  let stdout = '';
  let stderr = '';
  child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
  const stop = async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    child.kill('SIGTERM');
    await Promise.race([
      new Promise((resolve) => child.once('exit', resolve)),
      new Promise((resolve) => setTimeout(resolve, 3000))
    ]);
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  };
  const port = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Core start timeout: ${stderr}`)), 10000);
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
      const line = stdout.split(/\r?\n/).find((item) => /^\d{2,5}$/.test(item.trim()));
      if (!line) return;
      clearTimeout(timer);
      resolve(Number(line.trim()));
    });
    child.once('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`Core helper exited with ${code}: ${stderr}`));
    });
  });
  const base = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const response = await fetch(`${base}/api/v1/status`, { signal: AbortSignal.timeout(5000) });
      if (response.ok) return { base, stop };
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  await stop();
  throw new Error(`Core did not become ready: ${stderr}`);
}

test('Studio-Status und Rechte-Gate sprechen mit dem echten lokalen Core',
  { timeout: 120000, skip: PYTHON ? false : 'python3 is required for the Core integration' }, async (t) => {
    const core = await startCore();
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-integration-core-'));
    t.after(async () => {
      await core.stop();
      fs.rmSync(userDataDir, { recursive: true, force: true });
    });
    const studio = loadStudioMain({
      env: { STREAMIOV_HOST_URL: core.base },
      userDataDir
    });

    const network = await studio.invoke('studio:get-network-status');
    assert.equal(network.ok, true);
    assert.equal(network.core.reachable, true);
    assert.equal(network.core.stage, 'local-account-api');
    assert.equal(typeof network.core.apiReady, 'boolean');
    assert.equal(network.internetProbe, null);
    assert.ok(Number.isInteger(network.localDevice.interfaceCount));
    assert.equal(studio.source.includes('127.0.0.1:18180'), false);

    const gate = await studio.invoke('studio:data-query', {
      kind: 'musicGate',
      params: { territory: 'DE', usage: 'local_playback' }
    });
    assert.equal(gate.ok, true, gate);
    assert.equal(gate.kind, 'musicGate');
    assert.equal(gate.assetBase, core.base);
    assert.equal(gate.data.ok, true);
    assert.equal(gate.data.territory, 'DE');
    assert.equal(gate.data.usage, 'local_playback');
    assert.ok(Array.isArray(gate.data.tracks));
    assert.equal(gate.data.count, gate.data.tracks.length);
  });

test('Core-Status meldet nur eine tatsächlich erreichbare Core-Antwort als erreichbar', async (t) => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-integration-offline-'));
  t.after(() => fs.rmSync(userDataDir, { recursive: true, force: true }));
  const studio = loadStudioMain({
    fetchImpl: async () => { throw new Error('Core offline'); },
    userDataDir
  });

  const network = await studio.invoke('studio:get-network-status');
  assert.equal(network.ok, true);
  assert.equal(network.core.reachable, false);
  assert.match(network.core.error, /Core offline/);
  assert.equal(network.internetProbe, null);
});

test('Plattform-Ausgaben bleiben ohne Remote-Bestätigung nicht LIVE', async (t) => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-integration-outputs-'));
  t.after(() => fs.rmSync(userDataDir, { recursive: true, force: true }));
  const studio = loadStudioMain({
    fetchImpl: async () => { throw new Error('Kein Host für diesen Test nötig'); },
    userDataDir
  });

  const initial = await studio.invoke('studio:platform-output-status');
  assert.equal(initial.twitch.state, 'offline');
  assert.equal(initial.tiktok.state, 'offline');
  assert.equal(initial.twitch.liveConfirmed, false);
  assert.equal(initial.tiktok.liveConfirmed, false);

  const prepared = await studio.invoke('studio:twitch-prepare-output');
  assert.equal(prepared.ok, false);
  const after = await studio.invoke('studio:platform-output-status');
  assert.equal(after.twitch.liveConfirmed, false);
  assert.notEqual(after.twitch.state, 'live');
  assert.equal(after.tiktok.state, 'offline');
});

test('Chat, Quellen, Szenen-Take und TTS laufen über die echten Studio-Engines', async (t) => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-integration-engines-'));
  t.after(() => fs.rmSync(userDataDir, { recursive: true, force: true }));
  const studio = loadStudioMain({
    fetchImpl: async () => { throw new Error('Kein Host für diesen Test nötig'); },
    userDataDir
  });

  const initial = await studio.invoke('studio:chat-action', { action: 'status' });
  assert.equal(initial.ok, true);
  assert.equal(initial.external_platform_connected, false);
  assert.deepEqual(initial.connected_adapters, []);

  await studio.invoke('studio:chat-action', { action: 'toggle-chat' });
  const received = await studio.invoke('studio:chat-action', {
    action: 'receive', text: 'Integrationstest', channel: 'Lokal'
  });
  assert.equal(received.ok, true);
  assert.equal(received.message_count, 1);
  assert.equal(received.messages[0].text, 'Integrationstest');

  const outbound = await studio.invoke('studio:chat-action', {
    action: 'send', text: 'Keine Plattform verbunden', targets: ['twitch']
  });
  assert.equal(outbound.ok, false);
  assert.equal(outbound.results[0].ok, false);

  await studio.invoke('studio:chat-action', { action: 'toggle-tts' });
  const tts = await studio.invoke('studio:chat-action', { action: 'speak', text: 'Test' });
  if (tts.ok) {
    assert.equal(tts.audio_mime, 'audio/wav');
    assert.equal(isWavBuffer(Buffer.from(tts.audio_base64, 'base64')), true);
    assert.equal(tts.tts_audio_verified, true);
  } else {
    assert.equal(tts.tts_audio_verified, false);
  }
  const chatStatus = await studio.invoke('studio:chat-action', { action: 'status' });
  assert.equal(chatStatus.tts_audio_verified, tts.tts_audio_verified);

  const moduleStatus = await studio.invoke('studio:get-module-status');
  const chatEvents = moduleStatus.modules.find(module => module.id === 'chat-events');
  const giftEvents = moduleStatus.modules.find(module => module.id === 'gift-events');
  assert.match(chatEvents.status, /twitch_irc_(connected|connecting|offline)/);
  assert.match(giftEvents.status, /twitch_eventsub_gift_subs_(connected|connecting|offline|not_subscribed)/);

  const runtime = await studio.invoke('studio:get-runtime-diagnostics');
  assert.equal(runtime.named_scene_switching_implemented, true);

  const source = await studio.invoke('studio:source-action', {
    action: 'add',
    source: { type: 'audio', name: 'Test-Mikrofon', settings: { deviceId: 'integration-device' } }
  });
  assert.equal(source.ok, true, source);
  assert.equal(source.capture_pipeline_connected, false);
  const sourceId = source.state.sources[0].id;
  const muted = await studio.invoke('studio:source-action', {
    action: 'update', id: sourceId, patch: { muted: true }
  });
  assert.equal(muted.ok, true);
  assert.equal(muted.state.sources[0].muted, true);

  const created = await studio.invoke('studio:scene-action', { action: 'create', name: 'Integration' });
  assert.equal(created.ok, true, created);
  const sceneId = created.state.scenes.find((scene) => scene.name === 'Integration').id;
  const taken = await studio.invoke('studio:scene-action', { action: 'take' });
  assert.equal(taken.state.programSceneId, sceneId);
  const loaded = await studio.invoke('studio:scene-action', { action: 'load' });
  assert.equal(loaded.state.programSceneId, sceneId);

  await studio.invoke('studio:get-device-capabilities', {
    devices: [{ kind: 'videoinput' }, { kind: 'videoinput' }, { kind: 'audioinput' }]
  });
  const cameraLab = await studio.invoke('studio:get-camera-lab');
  assert.equal(cameraLab.report.discovery, 'renderer_media_devices_enumerated');
  assert.equal(cameraLab.report.local_camera_count, 2);
  assert.equal(cameraLab.report.local_microphone_count, 1);
  assert.equal(cameraLab.report.live_stream_verified, false);

  const output = await studio.invoke('studio:open-program-output');
  assert.equal(output.outputWindowOpened, true);
  assert.equal(output.renderedVideo, false);
  const frame = await studio.invoke('studio:program-frame', {
    bytes: Buffer.from([0xff, 0xd8, 0xff, 0x00])
  });
  assert.equal(frame.delivered, true);
  const streamStatus = await studio.invoke('studio:get-stream-status');
  assert.equal(streamStatus.programFramesDelivered, 1);
});

test('Studio-Event-IPC baut vertrauenswürdige v1-Ereignisse und redigiert Geheimnisse', async (t) => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-integration-events-'));
  t.after(() => fs.rmSync(userDataDir, { recursive: true, force: true }));
  const requests = [];
  const response = (status, payload, setCookie = null) => ({
    status,
    ok: status >= 200 && status < 300,
    headers: {
      get: (name) => name.toLowerCase() === 'set-cookie' ? setCookie : null,
      getSetCookie: () => setCookie ? [setCookie] : [],
    },
    json: async () => payload,
  });
  let stored = null;
  const studio = loadStudioMain({
    userDataDir,
    fetchImpl: async (url, options = {}) => {
      const target = String(url);
      requests.push({ target, options });
      if (target.endsWith('/api/v1/auth/login')) {
        return response(200, {
          ok: true,
          user: { id: 'owner', username: 'EventOwner', created_at: 0 },
        }, 'streamiov_session=session-token; HttpOnly; SameSite=Strict');
      }
      if (target.includes('/api/v1/events') && options.method === 'POST') {
        stored = JSON.parse(options.body).event;
        return response(201, { ok: true, event: stored, duplicate: false });
      }
      if (target.includes('/api/v1/events')) {
        return response(200, {
          ok: true,
          schema_version: 1,
          events: stored ? [stored] : [],
        });
      }
      throw new Error(`Unexpected request: ${target}`);
    },
  });

  const login = await studio.invoke('studio:ai-login', {
    username: 'EventOwner', password: 'a-long-local-password',
  });
  assert.equal(login.ok, true);

  const published = await studio.invoke('studio:event-publish', {
    type: 'studio.scene.take',
    data: { scene: 'LIVE', streamKey: 'secret', destination: 'rtmps://evil.example/app/key' },
    source: 'renderer',
    event_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    occurred_at: '2020-01-01T00:00:00Z',
  });
  assert.equal(published.ok, true, published);
  assert.equal(published.delivered, true);
  assert.equal(stored.source, 'studio');
  assert.equal(stored.schema_version, 1);
  assert.equal(stored.type, 'studio.scene.take');
  assert.equal(stored.data.scene, 'LIVE');
  assert.equal(stored.data.streamKey, '[REDACTED]');
  assert.equal(stored.data.destination, '[REDACTED]');
  assert.notEqual(stored.event_id, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');
  assert.notEqual(stored.occurred_at, '2020-01-01T00:00:00Z');
  assert.equal(Object.hasOwn(stored, 'source'), true);

  const listed = await studio.invoke('studio:event-list', { limit: 5 });
  assert.equal(listed.ok, true);
  assert.equal(listed.schemaVersion, 1);
  assert.equal(listed.events[0].event_id, stored.event_id);
  assert.match(requests.find((entry) => !entry.options.method).target, /limit=5$/);
});

test('Wunschbox-Lebenszyklus läuft im echten Studio gegen den lokalen Core',
  { timeout: 120000, skip: PYTHON ? false : 'python3 is required for the Core integration' }, async (t) => {
    const username = 'WishOwner';
    const password = 'a-long-local-password';
    const core = await startCore({
      STREAMIOV_TEST_USERNAME: username,
      STREAMIOV_TEST_PASSWORD: password,
    });
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-integration-wishbox-'));
    t.after(async () => {
      await core.stop();
      fs.rmSync(userDataDir, { recursive: true, force: true });
    });
    const studio = loadStudioMain({ env: { STREAMIOV_HOST_URL: core.base }, userDataDir });

    const login = await studio.invoke('studio:ai-login', { username, password });
    assert.equal(login.ok, true, login);
    const auth = await studio.invoke('studio:auth-status');
    assert.equal(auth.ok, true, auth);
    assert.equal(auth.authenticated, true, auth);

    const submitted = await studio.invoke('studio:wishbox-submit', {
      text: 'Kannst du mir eine Challenge in Neon Relay analysieren?',
      sender: 'Viewer', source: 'chat', territory: 'DE',
    });
    assert.equal(submitted.ok, true, submitted);
    assert.equal(submitted.statusCode, 201, submitted);
    assert.equal(submitted.order.kind, 'game');
    assert.equal(submitted.order.status, 'queued');

    const listed = await studio.invoke('studio:wishbox-orders', { limit: 10 });
    assert.equal(listed.ok, true, listed);
    assert.ok(listed.orders.some((order) => order.id === submitted.order.id));

    const dispatched = await studio.invoke('studio:wishbox-action', {
      action: 'dispatch', orderId: submitted.order.id,
    });
    assert.equal(dispatched.ok, true, dispatched);
    assert.equal(dispatched.order.status, 'assigned');

    const handoffs = await studio.invoke('studio:wishbox-handoffs', { limit: 10 });
    assert.equal(handoffs.ok, true, handoffs);
    const handoff = handoffs.handoffs.find((item) => item.id === submitted.order.id);
    assert.ok(handoff, handoffs);
    assert.equal(handoff.handoff.agent, 'gaming');

    const claimed = await studio.invoke('studio:wishbox-action', {
      action: 'claim', orderId: submitted.order.id, agent: 'gaming-ki',
    });
    assert.equal(claimed.ok, true, claimed);
    assert.equal(claimed.order.status, 'in_progress');
    assert.equal(claimed.order.agent, 'gaming-ki');

    const incomplete = await studio.invoke('studio:wishbox-action', {
      action: 'complete', orderId: submitted.order.id,
    });
    assert.equal(incomplete.ok, false, incomplete);
    assert.match(incomplete.error, /result|Ergebnis/);

    const completed = await studio.invoke('studio:wishbox-action', {
      action: 'complete', orderId: submitted.order.id,
      result: 'Analysiert; der Streamer entscheidet.', agent: 'gaming-ki',
    });
    assert.equal(completed.ok, true, completed);
    assert.equal(completed.order.status, 'completed');
    assert.equal(completed.order.result, 'Analysiert; der Streamer entscheidet.');

    const ledger = await studio.invoke('studio:event-list', { limit: 20 });
    assert.equal(ledger.ok, true, ledger);
    const wishboxEvents = ledger.events.filter((event) => event.data?.order_id === submitted.order.id);
    for (const type of ['wishbox.order.received', 'wishbox.order.status', 'wishbox.order.result']) {
      assert.ok(wishboxEvents.some((event) => event.type === type), { type, wishboxEvents });
    }

    const invalid = await studio.invoke('studio:wishbox-action', {
      action: 'dispatch', orderId: '../etc/passwd',
    });
    assert.equal(invalid.ok, false, invalid);
    assert.match(invalid.error, /Ungültige/);

    const logout = await studio.invoke('studio:ai-logout');
    assert.equal(logout.ok, true, logout);
    const afterLogout = await studio.invoke('studio:wishbox-orders', { limit: 5 });
    assert.equal(afterLogout.ok, false, afterLogout);
    assert.equal(afterLogout.authRequired, true, afterLogout);
  });

test('Stream-Start akzeptiert kein vom Renderer vorgegebenes RTMP-Ziel', async (t) => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-integration-destination-'));
  t.after(() => fs.rmSync(userDataDir, { recursive: true, force: true }));
  const studio = loadStudioMain({
    fetchImpl: async () => { throw new Error('Kein Host für diesen Test nötig'); },
    userDataDir
  });

  const result = await studio.invoke('studio:start-stream', {
    platforms: ['custom'],
    destination: 'rtmp://evil.example/live/key',
    resolution: '720p',
    fps: 30,
    bitrate: 2500
  });
  assert.equal(result.ok, false);
  assert.match(result.error, /nicht unterstützt/);
  assert.equal(studio.source.includes('payload.destination'), false);
  assert.match(studio.source, /resolveOutputCredentials/);
});

test('Studio verbindet den Renderer mit getrennten RTMP-Ausgängen und Remote-LIVE-Prüfung', () => {
  const studio = loadStudioMain({ fetchImpl: async () => { throw new Error('Kein Host für diesen Test nötig'); } });
  assert.match(studio.source, /Array\.isArray\(options\.platforms\)/);
  assert.match(studio.source, /liveOutputManager\.start/);
  assert.match(studio.source, /liveOutputManager\.write/);
  assert.match(studio.source, /getLiveStatus/);
  assert.match(studio.source, /remote_platform_confirmation/);
  assert.match(studio.source, /\['connecting', 'live'\]\.includes\(platformOutputState\(platform\)\)/);
  assert.doesNotMatch(studio.source, /Nur die autorisierte Twitch-Ausgabe wird unterstützt/);
  assert.equal(studio.source.includes('payload.destination'), false);
});
