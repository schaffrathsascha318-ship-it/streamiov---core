'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  TwitchChatReceiver, parsePrivmsg, IRC_URL, REQUIRED_READ_SCOPE
} = require('./twitch-chat-receiver');

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

function fakeOAuth({ ircGranted = [REQUIRED_READ_SCOPE] } = {}) {
  return {
    status: () => ({ status: 'connected', chatScopes: { ircGranted } }),
    accessToken: async () => 'test-token',
    helix: async pathname => {
      assert.equal(pathname, '/users');
      return { data: [{ login: 'TestStreamer' }] };
    }
  };
}

test('Twitch IRC scope and endpoint are explicit', () => {
  assert.equal(REQUIRED_READ_SCOPE, 'chat:read');
  assert.equal(IRC_URL, 'wss://irc-ws.chat.twitch.tv:443');
});

test('parsePrivmsg normalizes official IRC chat messages', () => {
  const message = parsePrivmsg(
    '@id=abc123;display-name=Viewer\\sOne;tmi-sent-ts=1760000000000;user-id=42;badges=subscriber/3,moderator/1 ' +
    ':viewerone!viewerone@viewerone.tmi.twitch.tv PRIVMSG #teststreamer :Hallo Stream'
  );
  assert.equal(message.source, 'twitch');
  assert.equal(message.id, 'abc123');
  assert.equal(message.author, 'Viewer One');
  assert.equal(message.channel, '#teststreamer');
  assert.equal(message.text, 'Hallo Stream');
  assert.equal(message.createdAt, new Date(1760000000000).toISOString());
  assert.equal(message.platform_user_id, '42');
  assert.deepEqual(message.roles, ['subscriber', 'moderator']);
  assert.equal(parsePrivmsg('PING :tmi.twitch.tv'), null);
});

test('receiver refuses to connect without chat:read', async () => {
  const previous = globalThis.WebSocket;
  globalThis.WebSocket = FakeWebSocket;
  try {
    const receiver = new TwitchChatReceiver({
      getOAuth: () => fakeOAuth({ ircGranted: [] }),
      onMessage: () => assert.fail('should not receive messages')
    });
    await assert.rejects(() => receiver.start(), /oauth_permission_required/);
    assert.equal(FakeWebSocket.instances.length, 0);
  } finally {
    globalThis.WebSocket = previous;
  }
});

test('receiver connects, parses chat, answers ping and stops cleanly', async () => {
  const previous = globalThis.WebSocket;
  globalThis.WebSocket = FakeWebSocket;
  FakeWebSocket.instances.length = 0;
  const received = [];
  try {
    const receiver = new TwitchChatReceiver({
      getOAuth: () => fakeOAuth(),
      onMessage: message => received.push(message)
    });
    const initial = await receiver.start();
    assert.equal(initial.state, 'connecting');
    const socket = FakeWebSocket.instances.at(-1);
    assert.equal(socket.url, IRC_URL);
    socket.open();
    assert.ok(socket.sent.includes('CAP REQ :twitch.tv/tags twitch.tv/commands'));
    assert.ok(socket.sent.includes('PASS oauth:test-token'));
    assert.ok(socket.sent.includes('NICK teststreamer'));
    socket.emit('message', ':viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #teststreamer :Hallo\r\nPING :tmi.twitch.tv\r\n');
    assert.equal(received.length, 1);
    assert.equal(received[0].text, 'Hallo');
    assert.ok(socket.sent.includes('PONG :tmi.twitch.tv'));
    socket.emit('message', ':tmi.twitch.tv 001 teststreamer :Welcome\r\n');
    assert.equal(receiver.status().state, 'connected');
    receiver.stop();
    assert.equal(receiver.status().state, 'stopped');
    assert.equal(socket.readyState, 3);
  } finally {
    globalThis.WebSocket = previous;
  }
});
