'use strict';
const { randomUUID } = require('node:crypto');

const SCENE_VERSION = 2;
const MAX_SCENES = 100;
const MAX_SOURCES = 30;
const DEFAULT_BACKGROUND = '#10151e';
const SOURCE_TYPES = Object.freeze(['camera', 'screen', 'title', 'text']);
const DEFAULT_SCENES = Object.freeze([
  Object.freeze({ id: 'starting-soon', name: 'STARTING SOON', kind: 'built-in' }),
  Object.freeze({ id: 'live', name: 'LIVE', kind: 'built-in' }),
  Object.freeze({ id: 'pause', name: 'PAUSE', kind: 'built-in' }),
  Object.freeze({ id: 'ending', name: 'ENDING', kind: 'built-in' }),
  Object.freeze({ id: 'gameplay', name: 'GAMEPLAY', kind: 'built-in' }),
  Object.freeze({ id: 'just-chatting', name: 'JUST CHATTING', kind: 'built-in' })
]);

const validId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(value);
const clamp = (value, min, max, fallback) => {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : fallback;
};

function cleanSource(raw, index) {
  if (!raw || typeof raw !== 'object' || !SOURCE_TYPES.includes(raw.type)) return null;
  const id = validId(raw.id) ? raw.id : randomUUID();
  const name = typeof raw.name === 'string' ? raw.name.trim().slice(0, 60) : '';
  const text = typeof raw.text === 'string' ? raw.text.slice(0, 200) : '';
  return {
    id,
    type: raw.type,
    name: name || raw.type,
    text,
    x: clamp(raw.x, 0, 0.95, 0),
    y: clamp(raw.y, 0, 0.95, 0),
    w: clamp(raw.w, 0.05, 1, 1),
    h: clamp(raw.h, 0.05, 1, 1),
    z: Math.trunc(clamp(raw.z, 0, 100, index)),
    visible: raw.visible !== false
  };
}

function defaultSources(sceneId, sceneName) {
  const title = text => ({
    id: randomUUID(), type: 'title', name: 'Titelkarte', text,
    x: 0, y: 0, w: 1, h: 1, z: 0, visible: true
  });
  const camera = (overrides = {}) => ({
    id: randomUUID(), type: 'camera', name: 'Kamera', text: '',
    x: 0, y: 0, w: 1, h: 1, z: 0, visible: true, ...overrides
  });
  const screen = (overrides = {}) => ({
    id: randomUUID(), type: 'screen', name: 'Bildschirm', text: '',
    x: 0, y: 0, w: 1, h: 1, z: 0, visible: true, ...overrides
  });
  if (sceneId === 'starting-soon') return [title('STARTING SOON')];
  if (sceneId === 'pause') return [title('PAUSE')];
  if (sceneId === 'ending') return [title('ENDING')];
  if (sceneId === 'live') return [camera()];
  if (sceneId === 'just-chatting') return [camera({ name: 'Kamera' })];
  if (sceneId === 'gameplay') {
    return [screen(), camera({ name: 'Kamera-Overlay', x: 0.72, y: 0.72, w: 0.25, h: 0.25, z: 1 })];
  }
  return [title(sceneName)];
}

function cleanScene(raw) {
  if (!raw || typeof raw.id !== 'string' || typeof raw.name !== 'string') return null;
  if (!validId(raw.id)) return null;
  const name = raw.name.trim();
  if (!name || name.length > 60) return null;
  const sources = Array.isArray(raw.sources)
    ? raw.sources.map(cleanSource).filter(Boolean).slice(0, MAX_SOURCES)
    : defaultSources(raw.id, name);
  return {
    id: raw.id,
    name,
    kind: raw.kind === 'custom' ? 'custom' : 'built-in',
    background: /^#[0-9a-fA-F]{6}$/.test(raw.background || '') ? raw.background : DEFAULT_BACKGROUND,
    sources
  };
}

function defaultState() {
  return {
    version: SCENE_VERSION,
    scenes: DEFAULT_SCENES.map(scene => cleanScene({ ...scene, background: DEFAULT_BACKGROUND, sources: defaultSources(scene.id, scene.name) })),
    previewSceneId: 'starting-soon',
    programSceneId: 'starting-soon',
    updatedAt: new Date().toISOString()
  };
}

function cleanState(savedState) {
  if (!savedState || !Array.isArray(savedState.scenes)) {
    return defaultState();
  }
  if (savedState.version != null && ![1, SCENE_VERSION].includes(savedState.version)) {
    return defaultState();
  }
  const seen = new Set();
  const scenes = savedState.scenes
    .map(cleanScene)
    .filter(scene => {
      if (!scene || seen.has(scene.id)) return false;
      seen.add(scene.id);
      return true;
    })
    .slice(0, MAX_SCENES);
  if (!scenes.length) return defaultState();
  const ids = new Set(scenes.map(scene => scene.id));
  return {
    version: SCENE_VERSION,
    scenes,
    previewSceneId: ids.has(savedState.previewSceneId) ? savedState.previewSceneId : scenes[0].id,
    programSceneId: ids.has(savedState.programSceneId) ? savedState.programSceneId : scenes[0].id,
    updatedAt: typeof savedState.updatedAt === 'string' ? savedState.updatedAt : new Date().toISOString()
  };
}

class StudioSceneEngine {
  constructor(savedState = {}) {
    const state = cleanState(savedState);
    this.scenes = state.scenes;
    this.previewSceneId = state.previewSceneId;
    this.programSceneId = state.programSceneId;
    this.outputConnected = false;
    this.outputActive = false;
  }
  _preview() {
    return this.scenes.find(scene => scene.id === this.previewSceneId) || null;
  }
  _result() {
    return { ok: true, state: this.snapshot() };
  }
  selectPreview(sceneNameOrId) {
    const value = typeof sceneNameOrId === 'string' ? sceneNameOrId.trim() : '';
    const scene = this.scenes.find(item => item.name === value) ||
      this.scenes.find(item => item.id === value);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    this.previewSceneId = scene.id;
    return this._result();
  }
  createScene(sceneName) {
    const name = typeof sceneName === 'string' ? sceneName.trim() : '';
    if (!name || name.length > 60) return { ok: false, error: 'Szenenname muss 1 bis 60 Zeichen lang sein.' };
    if (this.scenes.length >= MAX_SCENES) return { ok: false, error: `Maximal ${MAX_SCENES} Szenen sind möglich.` };
    if (this.scenes.some(scene => scene.name.toLowerCase() === name.toLowerCase())) return { ok: false, error: 'Eine Szene mit diesem Namen existiert bereits.' };
    const scene = {
      id: randomUUID(), name, kind: 'custom', background: DEFAULT_BACKGROUND,
      sources: defaultSources('custom', name)
    };
    this.scenes.push(scene);
    this.previewSceneId = scene.id;
    return this._result();
  }
  renameScene(sceneId, sceneName) {
    const scene = this.scenes.find(item => item.id === sceneId);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    if (scene.kind !== 'custom') return { ok: false, error: 'Eingebaute Szenen können nicht umbenannt werden.' };
    const name = typeof sceneName === 'string' ? sceneName.trim() : '';
    if (!name || name.length > 60) return { ok: false, error: 'Szenenname muss 1 bis 60 Zeichen lang sein.' };
    if (this.scenes.some(item => item.id !== scene.id && item.name.toLowerCase() === name.toLowerCase())) {
      return { ok: false, error: 'Eine Szene mit diesem Namen existiert bereits.' };
    }
    scene.name = name;
    return this._result();
  }
  deleteScene(sceneId) {
    const scene = this.scenes.find(item => item.id === sceneId);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    if (scene.kind !== 'custom') return { ok: false, error: 'Eingebaute Szenen können nicht gelöscht werden.' };
    if (this.scenes.length <= 1) return { ok: false, error: 'Mindestens eine Szene muss bestehen bleiben.' };
    this.scenes = this.scenes.filter(item => item.id !== scene.id);
    if (this.previewSceneId === scene.id) this.previewSceneId = this.scenes[0].id;
    if (this.programSceneId === scene.id) this.programSceneId = this.scenes[0].id;
    return this._result();
  }
  take() {
    this.programSceneId = this.previewSceneId;
    return this._result();
  }
  // Directly switch the program scene without changing the preview. Used by
  // Schutzregie and future emergency actions; TAKE remains the normal path.
  setProgramScene(sceneNameOrId) {
    const value = typeof sceneNameOrId === 'string' ? sceneNameOrId.trim() : '';
    const scene = this.scenes.find(item => item.name === value) ||
      this.scenes.find(item => item.id === value);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    this.programSceneId = scene.id;
    return this._result();
  }
  addSource(input = {}) {
    const scene = this._preview();
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    if (scene.sources.length >= MAX_SOURCES) return { ok: false, error: `Maximal ${MAX_SOURCES} Quellen pro Szene sind möglich.` };
    const source = cleanSource({ ...input, id: randomUUID() }, scene.sources.length);
    if (!source) return { ok: false, error: 'Unbekannter Quellentyp.' };
    source.z = scene.sources.reduce((max, item) => Math.max(max, item.z), -1) + 1;
    scene.sources.push(source);
    return this._result();
  }
  updateSource(sourceId, patch = {}) {
    const scene = this._preview();
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    const source = scene.sources.find(item => item.id === sourceId);
    if (!source) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
    const safe = patch && typeof patch === 'object' ? patch : {};
    if (typeof safe.name === 'string' && safe.name.trim()) source.name = safe.name.trim().slice(0, 60);
    if (typeof safe.text === 'string') source.text = safe.text.slice(0, 200);
    for (const key of ['x', 'y', 'w', 'h', 'z']) {
      if (safe[key] !== undefined) {
        source[key] = key === 'z'
          ? Math.trunc(clamp(safe[key], 0, 100, source[key]))
          : clamp(safe[key], key === 'w' || key === 'h' ? 0.05 : 0, key === 'w' || key === 'h' ? 1 : 0.95, source[key]);
      }
    }
    if (safe.visible !== undefined) source.visible = safe.visible !== false;
    return this._result();
  }
  removeSource(sourceId) {
    const scene = this._preview();
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    const before = scene.sources.length;
    scene.sources = scene.sources.filter(item => item.id !== sourceId);
    if (scene.sources.length === before) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
    return this._result();
  }
  moveSource(sourceId, direction) {
    const scene = this._preview();
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    const index = scene.sources.findIndex(item => item.id === sourceId);
    if (index < 0) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
    const target = direction === 'up' ? index + 1 : index - 1;
    if (target >= 0 && target < scene.sources.length) {
      const [source] = scene.sources.splice(index, 1);
      scene.sources.splice(target, 0, source);
      scene.sources.forEach((item, order) => { item.z = order; });
    }
    return this._result();
  }
  setBackground(color) {
    const scene = this._preview();
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    if (!/^#[0-9a-fA-F]{6}$/.test(color || '')) {
      return { ok: false, error: 'Hintergrundfarbe muss ein Hex-Wert wie #10151e sein.' };
    }
    scene.background = color;
    return this._result();
  }
  setOutputStatus({ connected = false, outputActive = false } = {}) {
    this.outputConnected = connected === true;
    this.outputActive = outputActive === true;
    return this.snapshot();
  }
  snapshot() {
    return {
      version: SCENE_VERSION,
      scenes: this.scenes.map(scene => ({
        ...scene,
        sources: scene.sources.map(source => ({ ...source }))
      })),
      previewSceneId: this.previewSceneId,
      programSceneId: this.programSceneId,
      outputConnected: this.outputConnected,
      outputActive: this.outputActive,
      liveConfirmed: this.outputConnected && this.outputActive
    };
  }
  toJSON() {
    const state = this.snapshot();
    return {
      version: state.version,
      scenes: state.scenes,
      previewSceneId: state.previewSceneId,
      programSceneId: state.programSceneId,
      updatedAt: new Date().toISOString()
    };
  }
}
module.exports = {
  DEFAULT_SCENES,
  DEFAULT_BACKGROUND,
  MAX_SCENES,
  MAX_SOURCES,
  SCENE_VERSION,
  SOURCE_TYPES,
  StudioSceneEngine
};
