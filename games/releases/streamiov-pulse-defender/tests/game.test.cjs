'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

test('Pulse Defender exposes enemy waves, projectiles, shield, and touch controls', () => {
  for (const feature of [/addEnemy/, /bullets/, /ArrowLeft/, /pointerdown/, /shield/, /StreamiovGameBranding\.playIntro/]) {
    assert.match(html, feature);
  }
});
