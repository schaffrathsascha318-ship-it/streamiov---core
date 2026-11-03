'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { StudioSourceModel, MAX_SOURCES } = require('./source-model');

test('adds typed sources with safe defaults and bounded volume', () => {
  const model = new StudioSourceModel();
  const result = model.add({ id: 'cam-1', type: 'camera', name: 'Main Camera', volume: 4 });
  assert.equal(result.ok, true);
  assert.deepEqual(result.source, {
    id: 'cam-1', type: 'camera', name: 'Main Camera',
    enabled: true, muted: false, volume: 1
  });
});

test('rejects unsupported types, invalid names and duplicate IDs', () => {
  const model = new StudioSourceModel();
  assert.equal(model.add({ id: 'x', type: 'tiktok', name: 'External platform' }).ok, false);
  assert.equal(model.add({ id: 'x', type: 'camera', name: '   ' }).ok, false);
  assert.equal(model.add({ id: 'x', type: 'camera', name: 'Camera' }).ok, true);
  assert.equal(model.add({ id: 'x', type: 'audio', name: 'Mic' }).ok, false);
});

test('updates only validated source properties and supports removal', () => {
  const model = new StudioSourceModel();
  model.add({ id: 'mic', type: 'audio', name: 'Microphone' });
  assert.equal(model.update('mic', { muted: true, volume: 0.35 }).ok, true);
  assert.equal(model.snapshot().sources[0].muted, true);
  assert.equal(model.snapshot().sources[0].volume, 0.35);
  assert.equal(model.update('mic', { type: 'unknown' }).ok, false);
  assert.equal(model.remove('mic').ok, true);
  assert.equal(model.remove('mic').ok, false);
});

test('reorders all sources atomically and rejects incomplete or duplicate orders', () => {
  const model = new StudioSourceModel();
  model.add({ id: 'a', type: 'camera', name: 'A' });
  model.add({ id: 'b', type: 'audio', name: 'B' });
  assert.equal(model.reorder(['b', 'a']).ok, true);
  assert.deepEqual(model.snapshot().sources.map(item => item.id), ['b', 'a']);
  assert.equal(model.reorder(['a', 'a']).ok, false);
  assert.deepEqual(model.snapshot().sources.map(item => item.id), ['b', 'a']);
});

test('sanitizes persisted sources and enforces the source limit', () => {
  const model = new StudioSourceModel({
    sources: [
      { id: 'ok', type: 'video', name: 'Clip' },
      { id: 'bad id', type: 'camera', name: 'Invalid' },
      { id: 'ok', type: 'audio', name: 'Duplicate' }
    ]
  });
  assert.deepEqual(model.snapshot().sources.map(item => item.id), ['ok']);
  const full = new StudioSourceModel();
  for (let i = 0; i < MAX_SOURCES; i++) {
    assert.equal(full.add({ id: 's' + i, type: 'color', name: 'Source ' + i }).ok, true);
  }
  assert.equal(full.add({ id: 'overflow', type: 'color', name: 'Overflow' }).ok, false);
});

test('snapshots do not expose mutable internal source records', () => {
  const model = new StudioSourceModel();
  model.add({ id: 'cam', type: 'camera', name: 'Camera' });
  const snapshot = model.snapshot();
  snapshot.sources[0].name = 'Tampered';
  assert.equal(model.snapshot().sources[0].name, 'Camera');
});
