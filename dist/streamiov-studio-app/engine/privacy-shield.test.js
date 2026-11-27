'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { PrivacyShield, DEFAULT_PAUSE_SCENE_ID } = require('./privacy-shield');

test('shield starts inactive and documents its honest limits', () => {
  const shield = new PrivacyShield();
  const state = shield.snapshot();
  assert.equal(state.active, false);
  assert.equal(state.pauseSceneId, DEFAULT_PAUSE_SCENE_ID);
  assert.equal(state.scope, 'program-scene-local-mic-mix-and-local-output-stop-requests');
  assert.equal(state.stopsEncoder, true);
  assert.equal(state.stopsRecording, true);
  assert.equal(state.autoResumesOutputs, false);
  assert.equal(state.guaranteesPlatformPrivacy, false);
});

test('activate remembers program scene and mic level and targets pause plus mute', () => {
  const shield = new PrivacyShield();
  const result = shield.activate({ programSceneId: 'gameplay', micPercent: 75 });
  assert.equal(result.changed, true);
  assert.equal(result.reason, 'activated');
  assert.equal(result.requestsOutputStops, true);
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
  assert.equal(second.requestsOutputStops, true);
  assert.deepEqual(second.restore, { programSceneId: 'live', micPercent: 42 });
  assert.equal(shield.snapshot().activationCount, 1);
});

test('deactivate restores only scene and mic and never resumes stopped outputs', () => {
  const shield = new PrivacyShield();
  shield.activate({ programSceneId: 'gameplay', micPercent: 63 });
  const result = shield.deactivate();
  assert.equal(result.changed, true);
  assert.equal(result.resumesOutputs, false);
  assert.deepEqual(result.restore, { programSceneId: 'gameplay', micPercent: 63 });
  assert.equal(result.state.active, false);
  assert.equal(result.state.autoResumesOutputs, false);
  assert.equal(result.state.restoreState, null);
  const repeat = shield.deactivate();
  assert.equal(repeat.changed, false);
  assert.equal(repeat.resumesOutputs, false);
});

test('restore is an explicit alias for deactivation', () => {
  const shield = new PrivacyShield();
  shield.activate({ programSceneId: 'live', micPercent: 12 });
  const result = shield.restore();
  assert.equal(result.changed, true);
  assert.equal(result.resumesOutputs, false);
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
