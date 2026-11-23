'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { TwitchOAuth, TwitchTokenStore, REQUIRED_SCOPES, safeRedirect } = require('./twitch-oauth');

const key = Buffer.alloc(32, 7).toString('base64');
function setup(fetch) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-twitch-'));
  const store = new TwitchTokenStore({ filePath: path.join(dir, 'tokens.json'), key });
  const oauth = new TwitchOAuth({ clientId: 'client', clientSecret: 'secret',
    redirectUri: 'http://127.0.0.1:43210/callback', encryptionKey: key, store, fetch });
  return { oauth, store, dir };
}
test('Twitch OAuth requires the stream-key permission and validates loopback callback', () => {
  assert.deepEqual(REQUIRED_SCOPES, ['channel:read:stream_key']);
  assert.equal(safeRedirect('http://127.0.0.1:43210/callback'), 'http://127.0.0.1:43210/callback');
  assert.throws(() => safeRedirect('https://example.com/callback'));
  assert.throws(() => safeRedirect('http://127.0.0.1:43210/callback?x=1'));
});
test('authorization callback persists only encrypted tokens and checks granted scope', async () => {
  const { oauth, store, dir } = setup(async () => ({ ok: true, json: async () => ({
    access_token: 'access-secret', refresh_token: 'refresh-secret', expires_in: 3600, scope: [...REQUIRED_SCOPES]
  }) }));
  const auth = oauth.createAuthorizationUrl();
  const result = await oauth.callback({ code: 'one-time-code', state: auth.state });
  assert.equal(result.status, 'connected');
  const raw = fs.readFileSync(path.join(dir, 'tokens.json'), 'utf8');
  assert.equal(raw.includes('access-secret'), false);
  assert.equal(raw.includes('refresh-secret'), false);
  assert.deepEqual(store.load().scopes, [...REQUIRED_SCOPES]);
});
test('missing stream-key scope is rejected', async () => {
  const { oauth } = setup(async () => ({ ok: true, json: async () => ({
    access_token: 'a', refresh_token: 'r', expires_in: 3600, scope: []
  }) }));
  const auth = oauth.createAuthorizationUrl();
  await assert.rejects(oauth.callback({ code: 'c', state: auth.state }), /scope_not_granted/);
});
test('fetches broadcaster stream key automatically and never includes it in status', async () => {
  const calls = [];
  const { oauth, store } = setup(async (url) => {
    calls.push(url);
    if (url.includes('/users')) return { ok: true, json: async () => ({ data: [{ id: '123' }] }) };
    return { ok: true, json: async () => ({ data: [{ stream_key: 'never-log-this' }] }) };
  });
  store.save({ accessToken: 'a', refreshToken: 'r', expiresAt: Date.now() + 3600000, scopes: [...REQUIRED_SCOPES] });
  const credentials = await oauth.getStreamCredentials();
  assert.equal(credentials.ingestUrl, 'rtmps://live.twitch.tv:443/app');
  assert.equal(credentials.streamKey, 'never-log-this');
  assert.equal(calls.length, 2);
  assert.equal(JSON.stringify(oauth.status()).includes('never-log-this'), false);
});
test('403 stream key denial is surfaced as permission failure', async () => {
  const { oauth, store } = setup(async () => ({ ok: false, status: 403, json: async () => ({}) }));
  store.save({ accessToken: 'a', refreshToken: 'r', expiresAt: Date.now() + 3600000, scopes: [...REQUIRED_SCOPES] });
  await assert.rejects(oauth.getStreamCredentials(), /twitch_stream_key_access_denied/);
});
