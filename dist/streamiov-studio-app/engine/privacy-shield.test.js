'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { PrivacyShield, DEFAULT_PAUSE_SCENE_ID } = require('./privacy-shield');

test('shield starts inactive and documents its honest limits', () => {
  const shield = new PrivacyShield();
  const state = shield.snapshot();
  assert.equal(state.active, false);
  assert.equal(state.pauseSceneId, DEFAULT_PAUSE_SCENE_ID);
  assert.equal(state.scope, 'program-scene-and-local-mic-mix');
  assert.equal(state.stopsEncoder, false);
  assert.equal(state.stopsRecording, false);
  assert.equal(state.guaranteesPlatformPrivacy, false);
});

test('activate remembers program scene and mic level and targets pause plus mute', () => {
  const shield = new PrivacyShield();
  const result = shield.activate({ programSceneId: 'gameplay', micPercent: 75 });
  assert.equal(result.changed, true);
  assert.equal(result.reason, 'activated');
  assert.deepEqual(result.target, { programSceneId: 'pause', micPercent: 0 });
  assert.deepEqual(result.restore, { programSceneId: 'gameplay', micPercent: 75 });
  assert.equal(shield.snapshot().active, true);
  assert.equal(shield.snapshot().activationCount, 1);
});

test('activating twice never overwrites the original restore values', () => {
  const shield = new PrivacyShield();
  shield.activate({ programSceneId: 'live', micPercent: 42 });
  const second = shield.activate({ programSceneId: 'ending', micPercent: 99 });
  assert.equal(second.changed, false);
  assert.equal(second.reason, 'already-active');
  assert.deepEqual(second.restore, { programSceneId: 'live', micPercent: 42 });
  assert.equal(shield.snapshot().activationCount, 1);
});

test('deactivate returns the saved values and clears the shield', () => {
  const shield = new PrivacyShield();
  shield.activate({ programSceneId: 'gameplay', micPercent: 63 });
  const result = shield.deactivate();
  assert.equal(result.changed, true);
  assert.deepEqual(result.restore, { programSceneId: 'gameplay', micPercent: 63 });
  assert.equal(result.state.active, false);
  assert.equal(result.state.restoreState, null);
  assert.equal(shield.deactivate().changed, false);
});

test('restore is an explicit alias for deactivation', () => {
  const shield = new PrivacyShield();
  shield.activate({ programSceneId: 'live', micPercent: 12 });
  const result = shield.restore();
  assert.equal(result.changed, true);
  assert.deepEqual(result.restore, { programSceneId: 'live', micPercent: 12 });
  assert.equal(shield.snapshot().active, false);
});

test('hydrated state is sanitized and snapshots do not leak mutable state', () => {
  const shield = new PrivacyShield({
    active: true,
    activationCount: 4,
    restoreState: { programSceneId: 'bad id!', micPercent: 180 }
  });
  const snapshot = shield.snapshot();
  assert.equal(snapshot.active, true);
  assert.deepEqual(snapshot.restoreState, { programSceneId: null, micPercent: 100 });
  snapshot.restoreState.micPercent = 1;
  assert.equal(shield.snapshot().restoreState.micPercent, 100);
});

test('an active flag without restore data is ignored', () => {
  const shield = new PrivacyShield({ active: true });
  assert.equal(shield.snapshot().active, false);
  assert.equal(shield.snapshot().restoreState, null);
});
