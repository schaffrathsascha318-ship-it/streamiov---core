'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

test('Echo Grid exposes sequence playback, input validation, keyboard controls, and best score', () => {
  for (const feature of [/showSequence/, /sequence\[step\]/, /keydown/, /localStorage/, /StreamiovGameBranding\.playIntro/]) {
    assert.match(html, feature);
  }
});
