'use strict';
const { randomUUID } = require('node:crypto');
const DEFAULT_SCENES = Object.freeze([
  Object.freeze({ id: 'starting-soon', name: 'STARTING SOON', kind: 'built-in' }),
  Object.freeze({ id: 'live', name: 'LIVE', kind: 'built-in' }),
  Object.freeze({ id: 'pause', name: 'PAUSE', kind: 'built-in' }),
  Object.freeze({ id: 'ending', name: 'ENDING', kind: 'built-in' }),
  Object.freeze({ id: 'gameplay', name: 'GAMEPLAY', kind: 'built-in' }),
  Object.freeze({ id: 'just-chatting', name: 'JUST CHATTING', kind: 'built-in' })
]);
const validId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(value);
class StudioSceneEngine {
  constructor(savedState = {}) {
    const input = savedState && Array.isArray(savedState.scenes) ? savedState.scenes : DEFAULT_SCENES;
    const seen = new Set();
    const scenes = input
      .filter(scene => scene && validId(scene.id) && typeof scene.name === 'string')
      .map(scene => ({ id: scene.id, name: scene.name.trim(), kind: scene.kind === 'custom' ? 'custom' : 'built-in' }))
      .filter(scene => scene.name.length > 0 && scene.name.length <= 60)
      .filter(scene => { if (seen.has(scene.id)) return false; seen.add(scene.id); return true; })
      .slice(0, 100);
    this.scenes = scenes.length ? scenes : DEFAULT_SCENES.map(scene => ({ ...scene }));
    const ids = new Set(this.scenes.map(scene => scene.id));
    this.previewSceneId = ids.has(savedState.previewSceneId) ? savedState.previewSceneId : this.scenes[0].id;
    this.programSceneId = ids.has(savedState.programSceneId) ? savedState.programSceneId : this.scenes[0].id;
    this.outputConnected = false;
    this.outputActive = false;
  }
  selectPreview(sceneName) {
    const name = typeof sceneName === 'string' ? sceneName.trim() : '';
    const scene = this.scenes.find(item => item.name === name);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    this.previewSceneId = scene.id;
    return { ok: true, state: this.snapshot() };
  }
  createScene(sceneName) {
    const name = typeof sceneName === 'string' ? sceneName.trim() : '';
    if (!name || name.length > 60) return { ok: false, error: 'Szenenname muss 1 bis 60 Zeichen lang sein.' };
    if (this.scenes.length >= 100) return { ok: false, error: 'Maximal 100 Szenen sind möglich.' };
    if (this.scenes.some(scene => scene.name.toLowerCase() === name.toLowerCase())) return { ok: false, error: 'Eine Szene mit diesem Namen existiert bereits.' };
    const scene = { id: randomUUID(), name, kind: 'custom' };
    this.scenes.push(scene);
    this.previewSceneId = scene.id;
    return { ok: true, state: this.snapshot() };
  }
  take() {
    this.programSceneId = this.previewSceneId;
    return { ok: true, state: this.snapshot() };
  }
  setOutputStatus({ connected = false, outputActive = false } = {}) {
    this.outputConnected = connected === true;
    this.outputActive = outputActive === true;
    return this.snapshot();
  }
  snapshot() {
    return {
      version: 1,
      scenes: this.scenes.map(scene => ({ ...scene })),
      previewSceneId: this.previewSceneId,
      programSceneId: this.programSceneId,
      outputConnected: this.outputConnected,
      outputActive: this.outputActive,
      liveConfirmed: this.outputConnected && this.outputActive
    };
  }
  toJSON() {
    const state = this.snapshot();
    return { version: state.version, scenes: state.scenes, previewSceneId: state.previewSceneId, programSceneId: state.programSceneId, updatedAt: new Date().toISOString() };
  }
}
module.exports = { DEFAULT_SCENES, StudioSceneEngine };
