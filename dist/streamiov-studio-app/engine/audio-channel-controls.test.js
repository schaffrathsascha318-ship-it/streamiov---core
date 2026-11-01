'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');

for (const channel of ['microphone', 'music', 'game', 'alerts', 'tts']) {
  test(channel + ' has an independent gain and mute control', () => {
    assert.ok(html.includes('data-mix-gain="' + channel + '"'));
    assert.ok(html.includes('data-mix-mute="' + channel + '"'));
    assert.ok(html.includes('data-mix-state="' + channel + '"'));
  });
}

test('mixer UI routes real streams through a shared channel connection API', () => {
  assert.ok(html.includes('window.streamiovAudioInputs={connect:connectAudioSource'));
  assert.ok(html.includes('studioAudioMixer.setGain(name,state.gain/100)'));
  assert.ok(html.includes('studioAudioMixer.setMuted(name,state.muted)'));
  assert.ok(html.includes('connectAudioSource("microphone",stream)'));
});

test('unconnected audio channels are not represented as active', () => {
  assert.ok(html.includes('Quelle noch nicht verbunden'));
});
