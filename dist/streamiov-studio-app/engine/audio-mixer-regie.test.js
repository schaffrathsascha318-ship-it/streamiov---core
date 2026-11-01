'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');

test('Regie loads the local mixer and routes microphone capture into it', () => {
  assert.match(html, /<script src="\\.\\/engine\\/audio-mixer\\.js"><\\/script>/);
  assert.match(html, /studioAudioMixer\\.connect\\("microphone",stream/);
  assert.match(html, /studioAudioMixer\\.disconnect\\("microphone"\\)/);
  assert.match(html, /studioAudioMixer\\.setGain\\("microphone"/);
  assert.match(html, /noch nicht mit Encoder\\/LIVE verbunden/i);
});

test('local mixer output is not falsely reported as a live encoder connection', () => {
  assert.match(html, /Audio-Ausgang vorbereitet; noch nicht mit Encoder\\/LIVE verbunden/);
});
