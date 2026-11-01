'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');

test('Regie loads the local mixer and routes microphone capture into it', () => {
  assert.ok(html.includes('<script src="./engine/audio-mixer.js"></script>'));
  assert.ok(html.includes('connectAudioSource("microphone",stream'));
  assert.ok(html.includes('studioAudioMixer.disconnect("microphone")'));
  assert.ok(html.includes('studioAudioMixer.setGain(name,state.gain/100)'));
  assert.ok(html.includes('noch nicht mit Encoder/LIVE verbunden'));
});

test('local mixer output is not falsely reported as a live encoder connection', () => {
  assert.ok(html.includes('Audio-Ausgang vorbereitet; noch nicht mit Encoder/LIVE verbunden'));
});

test('Regie exposes selectable local monitor output controls', () => {
  assert.ok(html.includes('id="audioMonitorDevice"'));
  assert.ok(html.includes('id="audioMonitorConnect"'));
  assert.ok(html.includes('id="audioMonitorDisconnect"'));
  assert.ok(html.includes('studioAudioMixer.attachMonitor(monitorElement'));
  assert.ok(html.includes('studioAudioMixer.detachMonitor(monitorElement)'));
});

test('Regie connects local music and alert media files to their own mixer channels', () => {
  assert.ok(html.includes('id="musicAudioFile"'));
  assert.ok(html.includes('id="musicAudioPlayer"'));
  assert.ok(html.includes('id="alertAudioFile"'));
  assert.ok(html.includes('id="alertAudioPlayer"'));
  assert.ok(html.includes('bindMediaFile("music"'));
  assert.ok(html.includes('bindMediaFile("alerts"'));
  assert.ok(html.includes('connectAudioSource(channel,binding.destination.stream)'));
  assert.ok(html.includes('music:{gain:45,muted:false,routes:["stream","monitor","music_stem"]}'));
  assert.ok(html.includes('alerts:{gain:80,muted:false,routes:["stream","monitor","alerts_stem"]}'));
});
