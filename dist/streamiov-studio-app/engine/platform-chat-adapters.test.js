'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  TIKTOK_CHAT_STATUS,
  platformChatStatuses,
  resolveChatPermissions,
  connectedPlatformAdapters,
  createTwitchChatAdapter
} = require('./platform-chat-adapters');

function statusesFor(state) {
  return platformChatStatuses({ getOAuth: () => ({ status: () => state }) });
}

test('TikTok chat stays unsupported and never claims a connection', () => {
  assert.equal(TIKTOK_CHAT_STATUS.supported, false);
  assert.equal(TIKTOK_CHAT_STATUS.sendable, false);
  const statuses = platformChatStatuses();
  assert.equal(statuses.tiktok.status, 'not_supported');
  assert.equal(resolveChatPermissions(statuses).tiktok, false);
  assert.deepEqual(connectedPlatformAdapters(statuses), []);
});

test('Twitch chat sendability follows the observed OAuth grant and token state', () => {
  const disconnected = statusesFor({ status: 'not_connected' });
  assert.equal(disconnected.twitch.status, 'disconnected');
  assert.equal(disconnected.twitch.sendable, false);
  assert.deepEqual(connectedPlatformAdapters(disconnected), []);

  const missingScope = statusesFor({
    status: 'connected', chatScopes: { sufficientForHelix: false }
  });
  assert.equal(missingScope.twitch.status, 'oauth_permission_required');
  assert.equal(missingScope.twitch.sendable, false);
  assert.deepEqual(connectedPlatformAdapters(missingScope), []);

  const ready = statusesFor({
    status: 'connected', chatScopes: { sufficientForHelix: true }
  });
  assert.equal(ready.twitch.status, 'ready');
  assert.equal(ready.twitch.sendable, true);
  assert.deepEqual(connectedPlatformAdapters(ready), ['twitch']);
  assert.equal(resolveChatPermissions(ready).twitch, true);

  const refreshable = statusesFor({
    status: 'token_expired', refreshAvailable: true,
    chatScopes: { sufficientForHelix: true }
  });
  assert.equal(refreshable.twitch.status, 'refresh_required');
  assert.deepEqual(connectedPlatformAdapters(refreshable), ['twitch']);

  const expired = statusesFor({
    status: 'token_expired', refreshAvailable: false,
    chatScopes: { sufficientForHelix: true }
  });
  assert.deepEqual(connectedPlatformAdapters(expired), []);
});

test('registering an adapter does not make a platform externally connected', async () => {
  const disconnected = statusesFor({ status: 'not_connected' });
  const adapter = createTwitchChatAdapter({
    getOAuth: () => ({ sendChatMessage: async () => ({ ok: true, isSent: false }) })
  });
  assert.equal(typeof adapter.sendMessage, 'function');
  assert.deepEqual(connectedPlatformAdapters(disconnected), []);
  assert.equal((await adapter.sendMessage('hallo')).ok, false);
});

test('twitch adapter reports success only for a confirmed Helix message id', async () => {
  const confirmed = createTwitchChatAdapter({
    getOAuth: () => ({ sendChatMessage: async () => ({ ok: true, isSent: true, messageId: 'm-1' }) })
  });
  const result = await confirmed.sendMessage('hallo');
  assert.equal(result.ok, true);
  assert.equal(result.isSent, true);
  assert.equal(result.messageId, 'm-1');
});
