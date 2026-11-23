'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { StreamiovChatHub } = require('./chat-hub');

test('merges TikTok, Twitch and Discord messages in chronological order with source labels', () => {
  const hub = new StreamiovChatHub();
  hub.receive({ source: 'twitch', id: 'tw-1', author: 'TwitchUser', channel: 'channel', text: 'Later', createdAt: '2026-01-01T00:00:02Z' });
  hub.receive({ source: 'discord', id: 'dc-1', author: 'DiscordUser', channel: 'community', text: 'Earlier', createdAt: '2026-01-01T00:00:01Z' });
  hub.receive({ source: 'tiktok', id: 'tt-1', author: 'TikTokUser', channel: 'live', text: 'Middle', createdAt: '2026-01-01T00:00:01.500Z' });
  const messages = hub.list();
  assert.deepEqual(messages.map(item => item.source), ['discord', 'tiktok', 'twitch']);
  assert.equal(messages[0].channel, 'community');
});

test('deduplicates platform events and supports source/search filters', () => {
  const hub = new StreamiovChatHub();
  const message = { source: 'twitch', id: 'same', author: 'Sascha', text: 'Hallo Twitch' };
  assert.equal(hub.receive(message).accepted, true);
  assert.equal(hub.receive(message).duplicate, true);
  assert.equal(hub.list({ source: 'twitch', query: 'hallo' }).length, 1);
  assert.equal(hub.list({ source: 'tiktok' }).length, 0);
});

test('Discord is inbound community chat only, never an outbound LIVE chat target', async () => {
  const hub = new StreamiovChatHub();
  assert.throws(() => hub.registerAdapter('discord', { sendMessage: async () => ({ ok: true }) }), /Unbekannte Chat-Ausgabe/);
  await assert.rejects(() => hub.send({ text: 'hello', targets: ['discord'] }), /Sendeziele/);
});

test('outbound sending requires explicit target and permission, then uses only registered adapter', async () => {
  const hub = new StreamiovChatHub();
  let sent = 0;
  hub.registerAdapter('twitch', { sendMessage: async text => { sent++; return { ok: true, text }; } });
  const denied = await hub.send({ text: 'hello', targets: ['twitch'], permissions: { twitch: false } });
  assert.equal(denied.ok, false);
  assert.equal(sent, 0);
  const accepted = await hub.send({ text: 'hello', targets: ['twitch'], permissions: { twitch: true } });
  assert.equal(accepted.ok, true);
  assert.equal(sent, 1);
  const missing = await hub.send({ text: 'hello', targets: ['tiktok'], permissions: { tiktok: true } });
  assert.equal(missing.ok, false);
});

test('rejects invalid sources, malformed timestamps and oversized text', () => {
  const hub = new StreamiovChatHub();
  assert.throws(() => hub.receive({ source: 'youtube', text: 'x' }), /Nachrichtenquelle/);
  assert.throws(() => hub.receive({ source: 'tiktok', text: 'x', createdAt: 'invalid' }), /Nachrichtenzeitpunkt/i);
  assert.throws(() => hub.receive({ source: 'tiktok', text: 'x'.repeat(2001) }), /1–2000/);
});
