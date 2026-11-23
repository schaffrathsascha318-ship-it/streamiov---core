'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { PlatformOutputRegistry } = require('./platform-output-registry');

test('TikTok and Twitch output states are isolated', () => {
  const outputs = new PlatformOutputRegistry();
  outputs.transition('tiktok', 'authorizing');
  outputs.transition('tiktok', 'ready');
  outputs.transition('tiktok', 'connecting');
  assert.equal(outputs.snapshot().tiktok.state, 'connecting');
  assert.equal(outputs.snapshot().twitch.state, 'offline');
});

test('a local encoder state cannot be promoted to LIVE without remote evidence', () => {
  const outputs = new PlatformOutputRegistry();
  outputs.transition('tiktok', 'authorizing');
  outputs.transition('tiktok', 'ready');
  outputs.transition('tiktok', 'connecting');
  assert.throws(() => outputs.transition('tiktok', 'live'), /Remote-Plattform/);
  assert.equal(outputs.snapshot().tiktok.liveConfirmed, false);
});

test('LIVE requires platform-matching, timestamped remote confirmation', () => {
  const outputs = new PlatformOutputRegistry();
  outputs.transition('twitch', 'authorizing');
  outputs.transition('twitch', 'ready');
  outputs.transition('twitch', 'connecting');
  assert.throws(() => outputs.transition('twitch', 'live', {
    evidence: { type: 'remote_platform_confirmation', platform: 'tiktok', confirmationId: 'x', confirmedAt: new Date().toISOString() }
  }), /Remote-Plattform/);
  const confirmedAt = new Date().toISOString();
  const state = outputs.transition('twitch', 'live', {
    evidence: { type: 'remote_platform_confirmation', platform: 'twitch', confirmationId: 'twitch-live-1', confirmedAt }
  });
  assert.equal(state.liveConfirmed, true);
  assert.equal(state.confirmationId, 'twitch-live-1');
});

test('disconnecting one output does not change the other output', () => {
  const outputs = new PlatformOutputRegistry();
  for (const platform of ['tiktok', 'twitch']) {
    outputs.transition(platform, 'authorizing');
    outputs.transition(platform, 'ready');
    outputs.transition(platform, 'connecting');
  }
  outputs.transition('tiktok', 'offline');
  assert.equal(outputs.snapshot().tiktok.liveConfirmed, false);
  assert.equal(outputs.snapshot().twitch.state, 'connecting');
});

test('invalid transitions and platform identifiers are rejected', () => {
  const outputs = new PlatformOutputRegistry();
  assert.throws(() => outputs.transition('discord', 'connecting'), /Unbekannte LIVE-Plattform/);
  assert.throws(() => outputs.transition('tiktok', 'live'), /Unzulässiger Statuswechsel/);
});
