'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const contract = require('./source-contract');

test('normalizes legacy capture sources into the scene screen contract', () => {
  assert.equal(contract.normalizeType('capture'), 'screen');
  assert.deepEqual(contract.SUPPORTED_TYPES, [
    'camera', 'screen', 'window', 'title', 'text', 'image', 'video', 'audio', 'color'
  ]);
  assert.equal(contract.sourceDescriptor({ id: 'old', type: 'capture', name: 'Screen' }).type, 'screen');
});

test('describes only opaque identifiers and bounded source metadata', () => {
  const descriptor = contract.sourceDescriptor({
    id: 'cam-main',
    type: 'camera',
    name: 'Main Camera',
    volume: 9,
    settings: { deviceId: 'opaque-device-id\n', width: 1920, fps: 30, password: 'secret' }
  });
  assert.equal(descriptor.id, 'cam-main');
  assert.equal(descriptor.deviceId, null);
  assert.equal(descriptor.volume, 1);
  assert.equal(descriptor.password, undefined);
  assert.equal(contract.sourceDescriptor({ id: 'bad id', type: 'camera', name: 'Camera' }), null);
  assert.equal(contract.sourceDescriptor({ id: 'x', type: 'external', name: 'External' }), null);
});

test('detects stale cameras, display sources and media assets before capture opens', () => {
  const availability = {
    devices: [
      { kind: 'videoinput', deviceId: 'camera-new' },
      { kind: 'audioinput', deviceId: 'mic-new' }
    ],
    displaySources: [{ id: 'screen:2:0', sourceId: 'screen:2:0', displayId: '2' }],
    assets: [{ id: 'asset-new' }]
  };
  const camera = { id: 'cam', type: 'camera', name: 'Camera', settings: { deviceId: 'camera-old' } };
  const cameraCheck = contract.validateAvailability(camera, availability);
  assert.equal(cameraCheck.ok, false);
  assert.equal(cameraCheck.status, 'stale');
  assert.match(cameraCheck.findings[0], /Kamera/);
  assert.equal(contract.validateAvailability({ ...camera, settings: { deviceId: 'camera-new' } }, availability).ok, true);

  const screen = { id: 'screen', type: 'screen', name: 'Screen', settings: { sourceId: 'screen:1:0' } };
  assert.equal(contract.validateAvailability(screen, availability).status, 'stale');
  assert.equal(contract.validateAvailability({ ...screen, settings: { displayId: '2' } }, availability).ok, true);
  assert.equal(contract.validateAvailability({ ...screen, settings: {} }, availability).ok, false);

  const clip = { id: 'clip', type: 'video', name: 'Clip', settings: { assetId: 'asset-old' } };
  assert.equal(contract.validateAvailability(clip, availability).status, 'stale');
  assert.equal(contract.validateAvailability({ ...clip, settings: { assetId: 'asset-new' } }, availability).ok, true);
});

test('classifies capture failures into actionable source statuses', () => {
  assert.equal(contract.classifyError({ name: 'NotAllowedError', message: 'denied' }), 'permission-denied');
  assert.equal(contract.classifyError({ name: 'NotFoundError', message: 'missing' }), 'stale');
  assert.equal(contract.classifyError({ name: 'NotReadableError', message: 'busy' }), 'device-busy');
  assert.equal(contract.classifyError({ name: 'AbortError', message: 'stopped' }), 'device-busy');
  assert.equal(contract.classifyError({ message: 'Quelle beendet' }), 'ended');
  assert.equal(contract.classifyError('unknown failure'), 'error');
});

test('reports source health without treating a stopped renderer as live', () => {
  const availability = { devices: [{ kind: 'videoinput', deviceId: 'camera-1' }] };
  const source = { id: 'cam', type: 'camera', name: 'Camera', settings: { deviceId: 'camera-1' } };
  assert.equal(contract.sourceHealth(source, null, availability).status, 'connecting');
  assert.equal(contract.sourceHealth(source, { status: 'ready' }, availability).status, 'ready');
  assert.equal(contract.sourceHealth(source, { error: { name: 'NotAllowedError' } }, availability).status, 'permission-denied');
  assert.equal(contract.sourceHealth(source, { stream: { getTracks: () => [{ readyState: 'ended' }] } }, availability).status, 'ended');
  assert.equal(contract.sourceHealth({ id: 'title', type: 'title', name: 'Title' }, null, availability).status, 'not-applicable');
  assert.equal(contract.sourceHealth({ ...source, settings: { deviceId: 'gone' } }, { status: 'ready' }, availability).status, 'stale');
});

test('exposes stable German health labels for every status', () => {
  for (const status of contract.STATUS) {
    assert.equal(typeof contract.healthLabel(status), 'string');
    assert.ok(contract.healthLabel(status).length > 0);
  }
  assert.equal(contract.healthLabel('stale'), 'veraltet');
});
