'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');

test('Regie loads the local mixer and routes microphone capture into it', () => {
  assert.ok(html.includes('<script src="./engine/audio-mixer.js"></script>'));
  assert.ok(html.includes('studioAudioMixer.connect("microphone",stream'));
  assert.ok(html.includes('studioAudioMixer.disconnect("microphone")'));
  assert.ok(html.includes('studioAudioMixer.setGain("microphone"'));
  assert.ok(html.includes('noch nicht mit Encoder/LIVE verbunden'));
});

test('local mixer output is not falsely reported as a live encoder connection', () => {
  assert.ok(html.includes('Audio-Ausgang vorbereitet; noch nicht mit Encoder/LIVE verbunden'));
});
