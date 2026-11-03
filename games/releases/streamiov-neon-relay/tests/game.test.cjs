'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

test('Neon Relay exposes keyboard and pointer movement, collection, and restart', () => {
  for (const feature of [/ArrowLeft/, /pointerdown/, /score\+=10/, /Nochmal spielen/, /StreamiovGameBranding\.playIntro/]) {
    assert.match(html, feature);
  }
});
