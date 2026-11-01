'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const registry = JSON.parse(fs.readFileSync(path.join(root, 'registry.json'), 'utf8'));

test('registry contains unique independent game entries with complete package files', () => {
  assert.equal(registry.schemaVersion, 1);
  assert.equal(registry.games.length >= 3, true);
  const ids = registry.games.map(game => game.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const game of registry.games) {
    assert.match(game.id, /^[a-z0-9-]+$/);
    assert.equal(game.independent, true);
    assert.equal(game.status, 'development');
    assert.equal(game.gameplayVerified, false);
    assert.equal(game.released, false);
    const directory = path.join(root, game.path.replace(/^games\\//, ''));
    assert.ok(fs.existsSync(path.join(directory, 'game.json')));
    assert.ok(fs.existsSync(path.join(directory, 'README.md')));
    assert.ok(fs.existsSync(path.join(directory, 'index.html')));
  }
});

test('every registered browser game is self-contained and not falsely released', () => {
  for (const game of registry.games) {
    const directory = path.join(root, game.path.replace(/^games\\//, ''));
    const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'game.json'), 'utf8'));
    const html = fs.readFileSync(path.join(directory, manifest.entry), 'utf8');
    assert.equal(manifest.id, game.id);
    assert.deepEqual(manifest.dependencies, []);
    assert.equal(manifest.status, 'development');
    assert.equal(manifest.release.gameplayVerified, false);
    assert.equal(manifest.release.released, false);
    assert.match(html, /<canvas|<button/);
    assert.match(html, /addEventListener/);
    assert.match(html, /<title>/);
  }
});

test('Neon Relay has movement, collection and restart mechanics', () => {
  const html = fs.readFileSync(path.join(root, 'neon-relay', 'index.html'), 'utf8');
  assert.match(html, /ArrowLeft/);
  assert.match(html, /pointerdown/);
  assert.match(html, /score\+=10/);
  assert.match(html, /Nochmal spielen/);
});

test('Echo Grid has sequence playback, input checking and keyboard controls', () => {
  const html = fs.readFileSync(path.join(root, 'echo-grid', 'index.html'), 'utf8');
  assert.match(html, /showSequence/);
  assert.match(html, /sequence\[step\]/);
  assert.match(html, /keydown/);
  assert.match(html, /localStorage/);
});

test('Pulse Defender has enemy waves, projectiles and player controls', () => {
  const html = fs.readFileSync(path.join(root, 'pulse-defender', 'index.html'), 'utf8');
  assert.match(html, /addEnemy/);
  assert.match(html, /bullets/);
  assert.match(html, /ArrowLeft/);
  assert.match(html, /pointerdown/);
  assert.match(html, /shield/);
});
