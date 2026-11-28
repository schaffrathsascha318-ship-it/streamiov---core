'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { SCENE_VERSION, StudioSceneEngine } = require('./scene-engine');

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
test('setProgramScene switches only the program and keeps the preview', () => {
  const engine = new StudioSceneEngine();
  engine.selectPreview('GAMEPLAY');
  const result = engine.setProgramScene('PAUSE');
  assert.equal(result.ok, true);
  assert.equal(result.state.programSceneId, 'pause');
  assert.equal(result.state.previewSceneId, 'gameplay');
  assert.equal(engine.setProgramScene('missing').ok, false);
  assert.equal(engine.snapshot().programSceneId, 'pause');
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
test('scene sources preserve validated settings for capture and media runtimes', () => {
  const engine = new StudioSceneEngine();
  engine.createScene('Runtime');
  const added = engine.addSource({ type: 'image', name: 'Logo', settings: { assetId: 'asset-1', loop: true }, x: 0.1, y: 0.2, w: 0.3, h: 0.25 });
  assert.equal(added.ok, true);
  const scene = added.state.scenes.find(item => item.id === added.state.previewSceneId);
  const source = scene.sources.find(item => item.type === 'image');
  assert.deepEqual(source.settings, { assetId: 'asset-1', loop: true });
  const snapshot = engine.snapshot();
  snapshot.scenes.find(item => item.id === scene.id).sources.find(item => item.id === source.id).settings.assetId = 'tampered';
  assert.equal(engine.snapshot().scenes.find(item => item.id === scene.id).sources.find(item => item.id === source.id).settings.assetId, 'asset-1');
  assert.equal(engine.addSource({ type: 'video', settings: { assetId: '' } }).ok, false);
  const updated = engine.updateSource(source.id, { type: 'video', settings: { assetId: 'asset-2', loop: false, volume: 0.5 } });
  assert.equal(updated.ok, true);
  const changed = updated.state.scenes.find(item => item.id === scene.id).sources.find(item => item.id === source.id);
  assert.equal(changed.type, 'video');
  assert.deepEqual(changed.settings, { assetId: 'asset-2', loop: false, volume: 0.5 });
});
test('free-form source geometry is persisted and clamped', () => {
  const engine = new StudioSceneEngine();
  engine.createScene('Geometry');
  const added = engine.addSource({
    type: 'text', name: 'Upper third', text: 'HELLO',
    x: 0.42, y: 0.33, w: 0.27, h: 0.19
  });
  assert.equal(added.ok, true);
  const source = added.state.scenes.find(item => item.id === added.state.previewSceneId)
    .sources.find(item => item.name === 'Upper third');
  assert.deepEqual(
    { x: source.x, y: source.y, w: source.w, h: source.h },
    { x: 0.42, y: 0.33, w: 0.27, h: 0.19 }
  );
  const clamped = engine.addSource({
    type: 'color', name: 'Clamped', settings: { color: '#35e0d0' },
    x: 2, y: -1, w: 0, h: 9
  });
  assert.equal(clamped.ok, true);
  const clampedSource = clamped.state.scenes.find(item => item.id === clamped.state.previewSceneId)
    .sources.find(item => item.name === 'Clamped');
  assert.deepEqual(
    { x: clampedSource.x, y: clampedSource.y, w: clampedSource.w, h: clampedSource.h },
    { x: 0.95, y: 0, w: 0.05, h: 1 }
  );
  const persisted = new StudioSceneEngine(engine.toJSON());
  const restored = persisted.scenes.find(item => item.id === added.state.previewSceneId)
    .sources.find(item => item.id === source.id);
  assert.deepEqual(
    { x: restored.x, y: restored.y, w: restored.w, h: restored.h },
    { x: 0.42, y: 0.33, w: 0.27, h: 0.19 }
  );
});
test('scene dependencies are validated, acyclic and protected from deletion', () => {
  const engine = new StudioSceneEngine();
  const first = engine.createScene('First');
  const firstId = first.state.previewSceneId;
  const second = engine.createScene('Second');
  const secondId = second.state.previewSceneId;
  engine.createScene('Third');
  assert.equal(engine.setSceneDependencies(secondId, [firstId, secondId, 'missing']).ok, false);
  const saved = engine.setSceneDependencies(secondId, [firstId]);
  assert.equal(saved.ok, true);
  assert.deepEqual(saved.state.scenes.find(scene => scene.id === secondId).dependsOn, [firstId]);
  assert.equal(engine.deleteScene(firstId).ok, false);
  assert.equal(engine.setSceneDependencies(firstId, [secondId]).ok, false);
  assert.equal(engine.setSceneDependencies('live', [firstId]).ok, false);
  const persisted = new StudioSceneEngine(engine.toJSON());
  assert.deepEqual(persisted.scenes.find(scene => scene.id === secondId).dependsOn, [firstId]);
  assert.equal(engine.setSceneDependencies(secondId, []).ok, true);
  assert.equal(engine.deleteScene(firstId).ok, true);
  const reloaded = new StudioSceneEngine(engine.toJSON());
  assert.deepEqual(reloaded.scenes.find(scene => scene.id === secondId).dependsOn, []);
});
test('source transforms are bounded and persisted with the scene', () => {
  const engine = new StudioSceneEngine();
  engine.createScene('Transform');
  const added = engine.addSource({
    type: 'image', name: 'Transform', settings: { assetId: 'asset-transform' },
    transform: {
      alpha: 2, rotationDeg: 500, flipH: true, flipV: 'yes', fit: 'weird',
      crop: { x: 2, y: -1, w: 0, h: 9 }
    }
  });
  assert.equal(added.ok, true);
  const source = added.state.scenes.find(scene => scene.id === added.state.previewSceneId)
    .sources.find(item => item.name === 'Transform');
  assert.deepEqual(source.transform, {
    alpha: 1, rotationDeg: 180, flipH: true, flipV: false, fit: 'cover',
    crop: { x: 0.95, y: 0, w: 0.05, h: 1 }
  });
  const updated = engine.updateSource(source.id, {
    transform: {
      alpha: 0.4, rotationDeg: -30, flipV: true, fit: 'contain',
      crop: { x: 0.1, y: 0.2, w: 0.8, h: 0.7 }
    }
  });
  assert.equal(updated.ok, true);
  const persisted = new StudioSceneEngine(engine.toJSON());
  assert.deepEqual(
    persisted.scenes.find(scene => scene.id === added.state.previewSceneId)
      .sources.find(item => item.id === source.id).transform,
    {
      alpha: 0.4, rotationDeg: -30, flipH: false, flipV: true, fit: 'contain',
      crop: { x: 0.1, y: 0.2, w: 0.8, h: 0.7 }
    }
  );
});
test('scene collection can be duplicated, reordered, exported and imported', () => {
  const engine = new StudioSceneEngine();
  const first = engine.createScene('First');
  const firstId = first.state.previewSceneId;
  engine.addSource({ type: 'text', name: 'Intro', text: 'INTRO', x: 0.1, y: 0.2, w: 0.3, h: 0.2 });
  const second = engine.createScene('Second');
  const secondId = second.state.previewSceneId;
  assert.equal(engine.setSceneDependencies(secondId, [firstId]).ok, true);
  const reversed = [secondId, firstId, ...engine.scenes.map(scene => scene.id).filter(id => id !== firstId && id !== secondId)];
  assert.equal(engine.reorderScenes(reversed).ok, true);
  assert.deepEqual(engine.scenes.map(scene => scene.id), reversed);
  assert.equal(engine.reorderScenes([firstId, firstId]).ok, false);
  const duplicate = engine.duplicateScene(firstId);
  assert.equal(duplicate.ok, true, duplicate);
  const clone = duplicate.state.scenes.find(scene => scene.id === duplicate.state.previewSceneId);
  assert.equal(clone.name, 'First (Kopie)');
  assert.equal(clone.kind, 'custom');
  const originalSources = engine.scenes.find(scene => scene.id === firstId).sources;
  const originalIds = new Set(originalSources.map(source => source.id));
  assert.equal(clone.sources.length, originalSources.length);
  assert.ok(clone.sources.every(source => !originalIds.has(source.id)));
  const packResult = engine.exportScenePack();
  assert.equal(packResult.ok, true);
  assert.equal(packResult.pack.kind, 'streamiov-scene-pack');
  assert.equal(packResult.pack.version, SCENE_VERSION);
  assert.equal(packResult.pack.scenes.length, 3);
  const imported = new StudioSceneEngine();
  const importResult = imported.importScenePack(packResult.pack);
  assert.equal(importResult.ok, true, importResult);
  const importedSecond = importResult.state.scenes.find(scene => scene.name === 'Second');
  const importedFirst = importResult.state.scenes.find(scene => scene.name === 'First');
  assert.ok(importedFirst && importedSecond);
  assert.deepEqual(importedSecond.dependsOn, [importedFirst.id]);
  assert.equal(imported.scenes.filter(scene => scene.name.startsWith('First')).length, 2);
  assert.equal(imported.importScenePack({ kind: 'other', version: SCENE_VERSION, scenes: [] }).ok, false);
});
test('capture sources persist real device constraints and audio routing choices', () => {
  const engine = new StudioSceneEngine();
  engine.createScene('Capture');
  const camera = engine.addSource({
    type: 'camera', name: 'Main Camera',
    settings: { deviceId: 'camera-1', width: 1920, height: 1080, fps: 30, audioEnabled: true }
  });
  assert.equal(camera.ok, true);
  const cameraSource = camera.state.scenes.find(item => item.id === camera.state.previewSceneId)
    .sources.find(item => item.type === 'camera');
  assert.deepEqual(cameraSource.settings, {
    deviceId: 'camera-1', width: 1920, height: 1080, fps: 30, audioEnabled: true
  });
  const screen = engine.addSource({
    type: 'screen', name: 'Display', settings: { sourceId: 'screen:1:0', width: 1280, height: 720, fps: 60 }
  });
  assert.equal(screen.ok, true);
  const audioFile = engine.addSource({
    type: 'audio', name: 'Clip', settings: { assetId: 'asset-audio', loop: true, volume: 0.4, muted: true }
  });
  assert.equal(audioFile.ok, true);
  const audioSource = audioFile.state.scenes.find(item => item.id === audioFile.state.previewSceneId)
    .sources.find(item => item.type === 'audio');
  assert.deepEqual(audioSource.settings, { assetId: 'asset-audio', loop: true, volume: 0.4, muted: true });
  assert.equal(cameraSource.audio.enabled, true);
  assert.deepEqual(audioSource.audio, { enabled: true, gain: 1, muted: true, solo: false, pan: 0, routes: ['stream'] });
  assert.equal(engine.addSource({ type: 'camera', settings: { width: 9999 } }).ok, false);
  assert.equal(engine.addSource({ type: 'camera', settings: { fps: 5 } }).ok, false);
});
test('source audio is bounded, persisted and migrated with scene packs', () => {
  const engine = new StudioSceneEngine();
  const created = engine.createScene('Audio');
  const sceneId = created.state.previewSceneId;
  const added = engine.addSource({
    type: 'screen', name: 'Display',
    settings: { sourceId: 'screen:1:0', audioEnabled: true },
    audio: { gain: 3, pan: -2, routes: ['stream', 'bogus', 'monitor', 'stream'], solo: true }
  });
  assert.equal(added.ok, true);
  const source = added.state.scenes.find(scene => scene.id === sceneId).sources.find(item => item.name === 'Display');
  assert.deepEqual(source.audio, { enabled: true, gain: 2, muted: false, solo: true, pan: -1, routes: ['stream', 'monitor'] });
  const updated = engine.updateSource(source.id, { audio: { ...source.audio, gain: 0.5, solo: false } }, sceneId);
  assert.equal(updated.ok, true);
  const changed = updated.state.scenes.find(scene => scene.id === sceneId).sources.find(item => item.id === source.id);
  assert.deepEqual(changed.audio, { enabled: true, gain: 0.5, muted: false, solo: false, pan: -1, routes: ['stream', 'monitor'] });
  const tampered = engine.snapshot();
  tampered.scenes.find(scene => scene.id === sceneId).sources.find(item => item.id === source.id).audio.routes.push('bogus');
  assert.deepEqual(engine.snapshot().scenes.find(scene => scene.id === sceneId).sources.find(item => item.id === source.id).audio.routes, ['stream', 'monitor']);
  const pack = engine.exportScenePack([sceneId]);
  assert.equal(pack.ok, true);
  assert.equal(pack.pack.version, SCENE_VERSION);
  assert.deepEqual(pack.pack.scenes[0].sources.find(item => item.id === source.id).audio, changed.audio);
  const legacy = new StudioSceneEngine({ version: 3, scenes: [
    { id: 'legacy', name: 'Legacy', kind: 'custom', sources: [
      { id: 'camera-legacy', type: 'camera', name: 'Cam', settings: { audioEnabled: true } },
      { id: 'audio-legacy', type: 'audio', name: 'Clip', settings: { assetId: 'asset', muted: true } }
    ] }
  ], previewSceneId: 'legacy', programSceneId: 'legacy' });
  const migrated = legacy.snapshot().scenes[0].sources;
  assert.equal(migrated[0].audio.enabled, true);
  assert.equal(migrated[1].audio.enabled, true);
  assert.equal(migrated[1].audio.muted, true);
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
test('persisted transitions survive TAKE and reject invalid values', () => {
  const engine = new StudioSceneEngine();
  assert.deepEqual(engine.snapshot().transition, { type: 'cut', durationMs: 0 });
  assert.equal(engine.setTransition({ type: 'fade', durationMs: 650 }).ok, true);
  engine.selectPreview('LIVE');
  const taken = engine.take();
  assert.equal(taken.ok, true);
  assert.deepEqual(taken.state.transition, { type: 'fade', durationMs: 650 });
  assert.equal(taken.previousSceneId, 'starting-soon');
  assert.equal(engine.take('dissolve').ok, false);
  assert.equal(engine.setTransition({ type: 'fade', durationMs: 50 }).ok, false);
  assert.deepEqual(new StudioSceneEngine(JSON.parse(JSON.stringify(engine.toJSON()))).snapshot().transition, { type: 'fade', durationMs: 650 });
});
test('slide and wipe transitions are validated and persisted', () => {
  const engine = new StudioSceneEngine();
  assert.equal(engine.setTransition({ type: 'slide', durationMs: 450 }).ok, true);
  assert.deepEqual(engine.snapshot().transition, { type: 'slide', durationMs: 450 });
  assert.equal(engine.setTransition({ type: 'wipe', durationMs: 50 }).ok, false);
  assert.equal(engine.setTransition({ type: 'wipe', durationMs: 900 }).ok, true);
  assert.equal(engine.take('dissolve').ok, false);
  assert.deepEqual(new StudioSceneEngine(JSON.parse(JSON.stringify(engine.toJSON()))).snapshot().transition, { type: 'wipe', durationMs: 900 });
});
test('scene overlays are persisted per scene and sanitized', () => {
  const engine = new StudioSceneEngine();
  assert.equal(engine.setOverlay({ style: 'standard', text: '', opacity: 0.8 }).ok, true);
  assert.deepEqual(engine.snapshot().scenes.find(scene => scene.id === 'starting-soon').overlay, { style: 'standard', text: '', opacity: 0.8 });
  assert.equal(engine.setOverlay({ style: 'custom', text: '   ' }).ok, false);
  assert.equal(engine.setOverlay({ style: 'custom', text: 'SPONSOR', opacity: 0.9 }).ok, true);
  const persisted = new StudioSceneEngine(JSON.parse(JSON.stringify(engine.toJSON()))).snapshot();
  assert.deepEqual(persisted.scenes.find(scene => scene.id === 'starting-soon').overlay, { style: 'custom', text: 'SPONSOR', opacity: 0.9 });
  const tampered = engine.snapshot();
  tampered.scenes[0].overlay.text = 'tampered';
  assert.equal(engine.snapshot().scenes[0].overlay.text, 'SPONSOR');
});
test('v2 scenes migrate to transitions and overlays without losing scenes', () => {
  const engine = new StudioSceneEngine({ version: 2, scenes: [
    { id: 'legacy', name: 'Legacy', kind: 'custom', background: '#112233', sources: [] }
  ], previewSceneId: 'legacy', programSceneId: 'legacy' });
  const state = engine.snapshot();
  assert.equal(state.version, SCENE_VERSION);
  assert.equal(state.scenes[0].name, 'Legacy');
  assert.deepEqual(state.scenes[0].overlay, { style: 'none', text: '', opacity: 0.85 });
  assert.deepEqual(state.transition, { type: 'cut', durationMs: 0 });
});
