'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  OUTPUT_IDS, SOURCE_IDS, createAudioRoutingState, updateOutput,
  setSourceRoutes, serializeAudioRoutingState
} = require('./audio-routing');

test('creates independent controls for every named output', () => {
  const state = createAudioRoutingState();
  assert.deepEqual(Object.keys(state.outputs), OUTPUT_IDS);
  for (const id of OUTPUT_IDS) {
    assert.equal(state.outputs[id].id, id);
    assert.equal(state.outputs[id].volume, 100);
    assert.equal(state.outputs[id].muted, false);
    assert.equal(state.outputs[id].adapterStatus, 'not_connected');
  }
  assert.equal(state.status, 'configuration_only');
});

test('changing one output never changes another output', () => {
  const initial = createAudioRoutingState();
  const changed = updateOutput(initial, 'headphones', {
    volume: 37, muted: true, deviceId: 'usb-headset-01'
  });
  assert.deepEqual(changed.outputs.headphones, {
    id: 'headphones', deviceId: 'usb-headset-01', volume: 37,
    muted: true, adapterStatus: 'not_connected'
  });
  assert.equal(changed.outputs.stream.volume, 100);
  assert.equal(changed.outputs.monitor.muted, false);
  assert.equal(initial.outputs.headphones.volume, 100);
});

test('rejects unknown outputs and unsafe volume/device values', () => {
  const state = createAudioRoutingState();
  assert.throws(() => updateOutput(state, 'unknown', { volume: 10 }), /Unknown audio output/);
  for (const volume of [-1, 101, 1.5, '50']) {
    assert.throws(() => updateOutput(state, 'stream', { volume }), /integer from 0 to 100/);
  }
  assert.throws(() => updateOutput(state, 'monitor', { deviceId: 'bad\u0000id' }), /safe characters/);
});

test('source routes are explicit, deduplicated and isolated per source', () => {
  const initial = createAudioRoutingState();
  const changed = setSourceRoutes(initial, 'music', ['headphones', 'stream', 'headphones']);
  assert.deepEqual(changed.routes.music, ['headphones', 'stream']);
  assert.deepEqual(changed.routes.microphone, ['stream', 'monitor']);
  assert.throws(() => setSourceRoutes(initial, 'music', ['unlisted']), /Unknown audio output/);
  assert.throws(() => setSourceRoutes(initial, 'unknown', []), /Unknown audio source/);
});

test('serializes user settings without runtime adapter claims', () => {
  const state = updateOutput(createAudioRoutingState(), 'communications', {
    volume: 22, muted: true, deviceId: 'default'
  });
  const saved = serializeAudioRoutingState(state);
  assert.equal(saved.version, 1);
  assert.equal(saved.outputs.communications.volume, 22);
  assert.equal(saved.outputs.communications.muted, true);
  assert.equal('adapterStatus' in saved.outputs.communications, false);
  assert.deepEqual(Object.keys(saved.routes).sort(), [...SOURCE_IDS].sort());
});
