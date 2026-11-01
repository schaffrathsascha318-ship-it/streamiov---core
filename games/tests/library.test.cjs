'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const registry = JSON.parse(fs.readFileSync(path.join(root, 'registry.json'), 'utf8'));

test('registry contains unique independent game entries', () => {
  assert.equal(registry.schemaVersion, 1);
  const ids = registry.games.map(game => game.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const game of registry.games) {
    assert.match(game.id, /^[a-z0-9-]+$/);
    assert.equal(game.independent, true);
    assert.ok(fs.existsSync(path.join(root, game.path.replace(/^games\//, ''), 'game.json')));
  }
});

test('Neon Relay manifest is self-contained and not falsely released', () => {
  const dir = path.join(root, 'neon-relay');
  const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'game.json'), 'utf8'));
  const html = fs.readFileSync(path.join(dir, manifest.entry), 'utf8');
  assert.equal(manifest.id, 'neon-relay');
  assert.deepEqual(manifest.dependencies, []);
  assert.equal(manifest.status, 'development');
  assert.equal(manifest.release.gameplayVerified, false);
  assert.equal(manifest.release.released, false);
  assert.match(html, /requestAnimationFrame/);
  assert.match(html, /pointerdown/);
  assert.match(html, /keydown/);
  assert.match(html, /Spiel starten/);
  assert.match(html, /GAME OVER/);
});
