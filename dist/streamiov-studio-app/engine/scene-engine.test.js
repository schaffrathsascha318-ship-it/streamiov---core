'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { StudioSceneEngine } = require('./scene-engine');

test('loads built-in scenes and keeps preview separate from program', () => {
  const engine = new StudioSceneEngine();
  const result = engine.selectPreview('LIVE');
  assert.equal(result.ok, true);
  assert.equal(result.state.previewSceneId, 'live');
  assert.equal(result.state.programSceneId, 'starting-soon');
  assert.equal(result.state.liveConfirmed, false);
});
test('TAKE switches program only to the selected preview', () => {
  const engine = new StudioSceneEngine();
  engine.selectPreview('GAMEPLAY');
  const result = engine.take();
  assert.equal(result.state.previewSceneId, 'gameplay');
  assert.equal(result.state.programSceneId, 'gameplay');
  assert.equal(result.state.liveConfirmed, false);
});
test('custom scenes are validated and selected for preview', () => {
  const engine = new StudioSceneEngine();
  const result = engine.createScene('Community');
  assert.equal(result.ok, true);
  assert.equal(result.state.scenes.at(-1).name, 'Community');
  assert.equal(result.state.previewSceneId, result.state.scenes.at(-1).id);
  assert.equal(engine.createScene('community').ok, false);
  assert.equal(engine.createScene('   ').ok, false);
});
test('LIVE confirmation requires both a connection and active output', () => {
  const engine = new StudioSceneEngine();
  assert.equal(engine.setOutputStatus({ connected: true, outputActive: false }).liveConfirmed, false);
  assert.equal(engine.setOutputStatus({ connected: false, outputActive: true }).liveConfirmed, false);
  assert.equal(engine.setOutputStatus({ connected: true, outputActive: true }).liveConfirmed, true);
});
test('saved scene data is sanitized and snapshots do not leak mutable state', () => {
  const engine = new StudioSceneEngine({ scenes: [
    { id: 'good', name: 'Good', kind: 'custom' },
    { id: 'bad id', name: 'Bad' },
    { id: 'good', name: 'Duplicate' }
  ], previewSceneId: 'missing', programSceneId: 'good' });
  const snapshot = engine.snapshot();
  assert.deepEqual(snapshot.scenes.map(scene => scene.id), ['good']);
  snapshot.scenes[0].name = 'tampered';
  assert.equal(engine.snapshot().scenes[0].name, 'Good');
  assert.equal(engine.snapshot().previewSceneId, 'good');
  assert.equal(engine.toJSON().programSceneId, 'good');
});
