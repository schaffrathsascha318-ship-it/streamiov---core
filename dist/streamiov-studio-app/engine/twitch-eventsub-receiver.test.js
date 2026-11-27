'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  TwitchEventSubReceiver, EVENTSUB_URL, SUBSCRIPTIONS, normalizeNotification
} = require('./twitch-eventsub-receiver');

class FakeWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.listeners = new Map();
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  emit(type, data) {
    for (const listener of this.listeners.get(type) || []) listener({ data });
  }
  send(line) { this.sent.push(line); }
  close() { this.readyState = 3; this.emit('close', undefined); }
  open() { this.readyState = 1; this.emit('open', undefined); }
}

function fakeResponse(ok, data) {
  return { ok, status: ok ? 200 : 400, json: async () => data };
}

function fakeOAuth() {
  const calls = [];
  return {
    calls,
    clientId: 'client-id',
    clientSecret: 'client-secret',
    status: () => ({ status: 'connected', scopes: ['channel:read:subscriptions', 'moderator:read:followers'] }),
    accessToken: async () => 'user-token',
    helix: async pathname => {
      assert.equal(pathname, '/users');
      return { data: [{ id: '12345' }] };
    },
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      if (url.includes('oauth2/token')) return fakeResponse(true, { access_token: 'app-token' });
      if (url.includes('eventsub/subscriptions')) return fakeResponse(true, { data: [] });
      throw new Error('unexpected_url:' + url);
    }
  };
}

test('EventSub uses only official Twitch endpoints and authorized event subscriptions', () => {
  assert.equal(EVENTSUB_URL, 'wss://eventsub.wss.twitch.tv/ws');
  assert.deepEqual(SUBSCRIPTIONS.map(item => item.type), [
    'channel.cheer', 'channel.raid', 'channel.follow', 'channel.subscribe', 'channel.subscription.gift'
  ]);
  assert.deepEqual(SUBSCRIPTIONS.find(item => item.type === 'channel.follow').conditionKeys, ['broadcaster_user_id', 'moderator_user_id']);
});

test('normalizeNotification turns official events into hub-compatible messages', () => {
  const cheer = normalizeNotification({
    metadata: { subscription_type: 'channel.cheer', message_id: 'm1', message_timestamp: '2026-11-26T00:00:00Z' },
    event: { user_name: 'Viewer', bits: 100, message: 'Danke' }
  });
  assert.equal(cheer.source, 'twitch');
  assert.equal(cheer.kind, 'cheer');
  assert.equal(cheer.author, 'Viewer');
  assert.match(cheer.text, /100 Bits/);
  const raid = normalizeNotification({
    metadata: { subscription_type: 'channel.raid', message_id: 'm2', message_timestamp: '2026-11-26T00:00:00Z' },
    event: { from_broadcaster_user_name: 'OtherChannel', viewers: 25 }
  });
  assert.equal(raid.kind, 'raid');
  assert.match(raid.text, /25 Zuschauer/);
  const follow = normalizeNotification({
    metadata: { subscription_type: 'channel.follow', message_id: 'm3', message_timestamp: '2026-11-26T00:00:00Z' },
    event: { user_name: 'Neuer Fan' }
  });
  assert.equal(follow.kind, 'follow');
  assert.match(follow.text, /Neuer Fan/);
  const subscription = normalizeNotification({
    metadata: { subscription_type: 'channel.subscribe', message_id: 'm4', message_timestamp: '2026-11-26T00:00:00Z' },
    event: { user_name: 'Abonnent', tier: '1000', is_gift: false }
  });
  assert.equal(subscription.kind, 'subscribe');
  assert.match(subscription.text, /Tier 1000/);
  const gift = normalizeNotification({
    metadata: { subscription_type: 'channel.subscription.gift', message_id: 'm5', message_timestamp: '2026-11-26T00:00:00Z' },
    event: { user_name: 'Großzügig', total: 3, tier: '1000' }
  });
  assert.equal(gift.kind, 'gift_subscription');
  assert.match(gift.text, /3 Subscription/);
  assert.equal(normalizeNotification({ metadata: {}, event: {} }), null);
});

test('EventSub connects, subscribes and forwards confirmed notifications', async () => {
  const previous = globalThis.WebSocket;
  globalThis.WebSocket = FakeWebSocket;
  FakeWebSocket.instances.length = 0;
  const events = [];
  const oauth = fakeOAuth();
  try {
    const receiver = new TwitchEventSubReceiver({
      getOAuth: () => oauth,
      onEvent: event => events.push(event)
    });
    await receiver.start();
    const socket = FakeWebSocket.instances.at(-1);
    assert.equal(socket.url, EVENTSUB_URL);
    socket.open();
    socket.emit('message', JSON.stringify({
      metadata: { message_type: 'session_welcome' },
      payload: { session: { id: 'session-1' } }
    }));
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(receiver.status().state, 'connected');
    const subscriptions = oauth.calls.filter(call => call.url.includes('eventsub/subscriptions'));
    assert.equal(subscriptions.length, 5);
    assert.ok(subscriptions.every(call => JSON.parse(call.options.body).transport.session_id === 'session-1'));
    socket.emit('message', JSON.stringify({
      metadata: { message_type: 'notification', subscription_type: 'channel.cheer', message_id: 'e1', message_timestamp: '2026-11-26T00:00:00Z' },
      payload: { subscription: { type: 'channel.cheer' }, event: { user_name: 'Viewer', bits: 50 } }
    }));
    assert.equal(events.length, 1);
    assert.match(events[0].text, /50 Bits/);
    receiver.stop();
    assert.equal(receiver.status().state, 'stopped');
  } finally {
    globalThis.WebSocket = previous;
  }
});
