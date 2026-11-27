'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { ChatModeration } = require('./chat-moderation');

function fixture(now) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-mod-'));
  return {
    directory,
    moderation: new ChatModeration({ filePath: path.join(directory, 'moderation.json'), now: () => now }),
  };
}

test('blocked words and banned users hide incoming messages locally', () => {
  const { directory, moderation } = fixture(1000);
  moderation.setBlockedWords([' Spam ']);
  moderation.ban({ source: 'twitch', author: 'BadUser' });
  assert.equal(moderation.evaluate({ source: 'twitch', author: 'Viewer', text: 'noch mehr SPAM hier' }).reason, 'blocked_word');
  assert.equal(moderation.evaluate({ source: 'twitch', author: 'BadUser', text: 'hallo' }).reason, 'banned_user');
  assert.equal(moderation.evaluate({ source: 'twitch', author: 'Viewer', text: 'hallo' }).allowed, true);
  fs.rmSync(directory, { recursive: true, force: true });
});

test('slow mode throttles repeated messages and role permissions stay local', () => {
  const { directory, moderation } = fixture(1000);
  moderation.setSlowMode(5);
  assert.equal(moderation.evaluate({ source: 'twitch', author: 'Viewer', text: 'eins' }).allowed, true);
  assert.equal(moderation.evaluate({ source: 'twitch', author: 'Viewer', text: 'zwei' }).reason, 'slow_mode');
  moderation.setRolePermissions({ viewer: { speak: true } });
  assert.equal(moderation.can('viewer', 'speak'), true);
  assert.equal(moderation.can('moderator', 'speak'), true);
  assert.equal(moderation.can('viewer', 'unknown'), false);
  fs.rmSync(directory, { recursive: true, force: true });
});

test('moderation state is persisted and roles come from official Twitch badges', () => {
  const { directory, moderation } = fixture(1000);
  moderation.setBlockedWords(['werbung']);
  moderation.ban({ source: 'tiktok', author: 'Bot' });
  const restored = new ChatModeration({ filePath: path.join(directory, 'moderation.json'), now: () => 1000 });
  assert.deepEqual([...restored.snapshot().blockedWords], ['werbung']);
  assert.deepEqual([...restored.snapshot().bannedUsers], ['tiktok:bot']);
  assert.deepEqual(restored.rolesFor({ badges: 'badges=subscriber/3,moderator/1' }), ['subscriber', 'moderator']);
  fs.rmSync(directory, { recursive: true, force: true });
});
