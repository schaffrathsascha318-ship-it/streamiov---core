'use strict';
const { randomUUID } = require('node:crypto');
const sourceContract = require('./source-contract');

const SCENE_VERSION = 4;
const MAX_SCENES = 100;
const MAX_SOURCES = 30;
const MAX_DEPENDENCIES = 10;
const DEFAULT_BACKGROUND = '#10151e';
const TRANSITION_TYPES = Object.freeze(['cut', 'fade', 'slide', 'wipe']);
const OVERLAY_STYLES = Object.freeze(['none', 'standard', 'custom']);
const DEFAULT_TRANSITION = Object.freeze({ type: 'cut', durationMs: 0 });
const DEFAULT_OVERLAY = Object.freeze({ style: 'none', text: '', opacity: 0.85 });
const SOURCE_TRANSFORM_FIT_MODES = Object.freeze(['cover', 'contain', 'stretch']);
const AUDIO_ROUTES = Object.freeze(['stream', 'monitor', 'headphones', 'communications']);
const AUDIO_CAPABLE_TYPES = Object.freeze(['camera', 'screen', 'window', 'video', 'audio']);
const SOURCE_TYPES = sourceContract.SUPPORTED_TYPES;
const SOURCE_SETTINGS = Object.freeze({
  camera: Object.freeze(['deviceId', 'width', 'height', 'fps', 'audioEnabled']),
  screen: Object.freeze(['sourceId', 'displayId', 'width', 'height', 'fps', 'audioEnabled']),
  window: Object.freeze(['sourceId', 'displayId', 'width', 'height', 'fps', 'audioEnabled']),
  image: Object.freeze(['assetId', 'loop']),
  video: Object.freeze(['assetId', 'loop', 'volume', 'muted']),
  audio: Object.freeze(['assetId', 'loop', 'volume', 'muted']),
  color: Object.freeze(['color'])
});
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
const validOpaqueId = value => typeof value === 'string' && value.length > 0 && value.length <= 512 && !/[\u0000-\u001f\u007f]/.test(value);
const validColor = value => typeof value === 'string' && /^#[0-9a-f]{6}(?:[0-9a-f]{2})?$/i.test(value);
const validWidth = value => Number.isInteger(value) && value >= 320 && value <= 3840;
const validHeight = value => Number.isInteger(value) && value >= 180 && value <= 2160;
const validFps = value => Number.isInteger(value) && value >= 15 && value <= 60;

function cleanDependencyIds(raw) {
  if (!Array.isArray(raw)) return [];
  const seen = new Set();
  const ids = [];
  for (const value of raw) {
    if (!validId(value) || seen.has(value)) continue;
    seen.add(value);
    ids.push(value);
    if (ids.length >= MAX_DEPENDENCIES) break;
  }
  return ids;
}
function hasDependencyCycle(dependencyMap, sceneId, dependencyId) {
  const stack = [dependencyId];
  const seen = new Set();
  while (stack.length) {
    const current = stack.pop();
    if (current === sceneId) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    for (const next of dependencyMap.get(current) || []) stack.push(next);
  }
  return false;
}
function sanitizeSceneDependencies(scenes) {
  const ids = new Set(scenes.map(scene => scene.id));
  for (const scene of scenes) {
    scene.dependsOn = scene.dependsOn.filter(id => ids.has(id) && id !== scene.id);
  }
  const dependencyMap = new Map(scenes.map(scene => [scene.id, scene.dependsOn]));
  for (const scene of scenes) {
    scene.dependsOn = scene.dependsOn.filter(id => !hasDependencyCycle(dependencyMap, scene.id, id));
    dependencyMap.set(scene.id, scene.dependsOn);
  }
  return scenes;
}

function transitionFromInput(raw) {
  const source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : { type: raw };
  const type = source.type;
  if (!TRANSITION_TYPES.includes(type)) return null;
  const defaultDurationMs = type === 'cut' ? 0 : 300;
  const durationMs = source.durationMs === undefined ? defaultDurationMs : Number(source.durationMs);
  const minimum = type === 'cut' ? 0 : 100;
  if (!Number.isInteger(durationMs) || durationMs < minimum || durationMs > 2000) return null;
  return { type, durationMs: type === 'cut' ? 0 : durationMs };
}

function cleanTransition(raw) {
  return transitionFromInput(raw) || { ...DEFAULT_TRANSITION };
}

function overlayFromInput(raw) {
  if (raw === undefined || raw === null) return { ...DEFAULT_OVERLAY };
  const source = typeof raw === 'string' ? { style: raw } : raw;
  if (!source || typeof source !== 'object' || Array.isArray(source)) return null;
  const style = source.style === undefined ? 'none' : source.style;
  if (!OVERLAY_STYLES.includes(style)) return null;
  const value = source.text === undefined ? '' : source.text;
  if (typeof value !== 'string' || value.length > 80) return null;
  const opacity = source.opacity === undefined ? DEFAULT_OVERLAY.opacity : Number(source.opacity);
  if (!Number.isFinite(opacity) || opacity < 0.1 || opacity > 1) return null;
  return { style, text: value.slice(0, 80), opacity };
}

function cleanOverlay(raw) {
  return overlayFromInput(raw) || { ...DEFAULT_OVERLAY };
}

function cleanSourceSettings(type, raw) {
  if (raw === undefined || raw === null) return undefined;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const allowed = SOURCE_SETTINGS[type] || [];
  if (Object.keys(raw).some(key => !allowed.includes(key))) return null;
  const settings = {};
  for (const key of allowed) {
    if (!Object.prototype.hasOwnProperty.call(raw, key)) continue;
    const value = raw[key];
    if (key === 'deviceId' || key === 'sourceId' || key === 'displayId' || key === 'assetId') {
      if (!validOpaqueId(value)) return null;
      settings[key] = value;
    } else if (key === 'loop' || key === 'muted' || key === 'audioEnabled') {
      if (typeof value !== 'boolean') return null;
      settings[key] = value;
    } else if (key === 'volume') {
      const volume = Number(value);
      if (!Number.isFinite(volume) || volume < 0 || volume > 1) return null;
      settings[key] = volume;
    } else if (key === 'width') {
      if (!validWidth(value)) return null;
      settings[key] = value;
    } else if (key === 'height') {
      if (!validHeight(value)) return null;
      settings[key] = value;
    } else if (key === 'fps') {
      if (!validFps(value)) return null;
      settings[key] = value;
    } else if (key === 'color') {
      if (!validColor(value)) return null;
      settings[key] = value.toLowerCase();
    }
  }
  return settings;
}

function cleanSourceTransform(raw) {
  const input = raw && typeof raw === 'object' ? raw : {};
  const cropInput = input.crop && typeof input.crop === 'object' ? input.crop : {};
  const cropX = clamp(cropInput.x, 0, 0.95, 0);
  const cropY = clamp(cropInput.y, 0, 0.95, 0);
  return {
    alpha: clamp(input.alpha, 0.1, 1, 1),
    rotationDeg: Math.trunc(clamp(input.rotationDeg, -180, 180, 0)),
    flipH: input.flipH === true,
    flipV: input.flipV === true,
    fit: SOURCE_TRANSFORM_FIT_MODES.includes(input.fit) ? input.fit : 'cover',
    crop: {
      x: cropX,
      y: cropY,
      w: clamp(cropInput.w, 0.05, 1 - cropX, 1 - cropX),
      h: clamp(cropInput.h, 0.05, 1 - cropY, 1 - cropY)
    }
  };
}

function cleanSourceAudio(raw, type, settings) {
  const input = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  const capable = AUDIO_CAPABLE_TYPES.includes(type);
  const media = type === 'video' || type === 'audio';
  const defaultEnabled = capable && (media || settings?.audioEnabled === true);
  const routes = Array.isArray(input.routes)
    ? [...new Set(input.routes.filter(route => AUDIO_ROUTES.includes(route)))].slice(0, AUDIO_ROUTES.length)
    : ['stream'];
  return {
    enabled: typeof input.enabled === 'boolean' ? input.enabled : defaultEnabled,
    gain: clamp(input.gain, 0, 2, 1),
    muted: typeof input.muted === 'boolean' ? input.muted : settings?.muted === true,
    solo: input.solo === true,
    pan: clamp(input.pan, -1, 1, 0),
    routes: routes.length ? routes : ['stream']
  };
}

function cleanSource(raw, index) {
  if (!raw || typeof raw !== 'object') return null;
  const type = sourceContract.normalizeType(raw.type);
  if (!SOURCE_TYPES.includes(type)) return null;
  const id = validId(raw.id) ? raw.id : randomUUID();
  const name = typeof raw.name === 'string' ? raw.name.trim().slice(0, 60) : '';
  const text = typeof raw.text === 'string' ? raw.text.slice(0, 200) : '';
  const settings = cleanSourceSettings(type, raw.settings);
  if (settings === null) return null;
  const source = {
    id,
    type,
    name: name || raw.type,
    text,
    x: clamp(raw.x, 0, 0.95, 0),
    y: clamp(raw.y, 0, 0.95, 0),
    w: clamp(raw.w, 0.05, 1, 1),
    h: clamp(raw.h, 0.05, 1, 1),
    z: Math.trunc(clamp(raw.z, 0, 100, index)),
    visible: raw.visible !== false,
    transform: cleanSourceTransform(raw.transform),
    audio: cleanSourceAudio(raw.audio, type, settings)
  };
  if (settings && Object.keys(settings).length) source.settings = settings;
  return source;
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
    overlay: cleanOverlay(raw.overlay),
    dependsOn: cleanDependencyIds(raw.dependsOn),
    sources
  };
}

function defaultState() {
  return {
    version: SCENE_VERSION,
    scenes: DEFAULT_SCENES.map(scene => cleanScene({ ...scene, background: DEFAULT_BACKGROUND, sources: defaultSources(scene.id, scene.name) })),
    previewSceneId: 'starting-soon',
    programSceneId: 'starting-soon',
    transition: { ...DEFAULT_TRANSITION },
    updatedAt: new Date().toISOString()
  };
}

function cleanState(savedState) {
  if (!savedState || !Array.isArray(savedState.scenes)) {
    return defaultState();
  }
  if (savedState.version != null && ![1, 2, 3, SCENE_VERSION].includes(savedState.version)) {
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
  sanitizeSceneDependencies(scenes);
  return {
    version: SCENE_VERSION,
    scenes,
    previewSceneId: ids.has(savedState.previewSceneId) ? savedState.previewSceneId : scenes[0].id,
    programSceneId: ids.has(savedState.programSceneId) ? savedState.programSceneId : scenes[0].id,
    transition: cleanTransition(savedState.transition),
    updatedAt: typeof savedState.updatedAt === 'string' ? savedState.updatedAt : new Date().toISOString()
  };
}

class StudioSceneEngine {
  constructor(savedState = {}) {
    const state = cleanState(savedState);
    this.scenes = state.scenes;
    this.previewSceneId = state.previewSceneId;
    this.programSceneId = state.programSceneId;
    this.transition = state.transition;
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
      overlay: { ...DEFAULT_OVERLAY },
      dependsOn: [],
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
    if (this.scenes.some(item => item.dependsOn.includes(sceneId))) {
      return { ok: false, error: 'Szene wird von einer anderen Szene benötigt.' };
    }
    if (this.scenes.length <= 1) return { ok: false, error: 'Mindestens eine Szene muss bestehen bleiben.' };
    this.scenes = this.scenes.filter(item => item.id !== scene.id);
    if (this.previewSceneId === scene.id) this.previewSceneId = this.scenes[0].id;
    if (this.programSceneId === scene.id) this.programSceneId = this.scenes[0].id;
    return this._result();
  }
  duplicateScene(sceneId) {
    const scene = this.scenes.find(item => item.id === sceneId);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    if (this.scenes.length >= MAX_SCENES) return { ok: false, error: `Maximal ${MAX_SCENES} Szenen sind möglich.` };
    const base = `${scene.name} (Kopie)`.slice(0, 60);
    let name = base;
    let counter = 2;
    while (this.scenes.some(item => item.name.toLowerCase() === name.toLowerCase())) {
      name = `${base.slice(0, 57)} ${counter}`;
      counter += 1;
      if (counter > 999) return { ok: false, error: 'Kein eindeutiger Szenenname verfügbar.' };
    }
    const clone = cleanScene(JSON.parse(JSON.stringify(scene)));
    clone.id = randomUUID();
    clone.name = name;
    clone.kind = 'custom';
    clone.sources = clone.sources.map(item => ({ ...item, id: randomUUID() }));
    const ids = new Set(this.scenes.map(item => item.id));
    clone.dependsOn = clone.dependsOn.filter(id => ids.has(id) && id !== clone.id);
    this.scenes.push(clone);
    this.previewSceneId = clone.id;
    return this._result();
  }
  reorderScenes(order) {
    if (!Array.isArray(order)) return { ok: false, error: 'Szenenreihenfolge muss eine Liste sein.' };
    const ids = new Set(order);
    if (order.length !== this.scenes.length || ids.size !== order.length ||
        this.scenes.some(scene => !ids.has(scene.id))) {
      return { ok: false, error: 'Szenenreihenfolge muss jede Szene genau einmal enthalten.' };
    }
    const byId = new Map(this.scenes.map(scene => [scene.id, scene]));
    this.scenes = order.map(id => byId.get(id));
    return this._result();
  }
  exportScenePack(sceneIds) {
    const requested = Array.isArray(sceneIds) ? sceneIds : null;
    const eligible = this.scenes.filter(scene => scene.kind === 'custom');
    const selected = requested
      ? eligible.filter(scene => requested.includes(scene.id))
      : eligible;
    if (requested && selected.length !== new Set(requested).size) {
      return { ok: false, error: 'Mindestens eine ausgewählte Szene ist nicht exportierbar.' };
    }
    return {
      ok: true,
      pack: {
        kind: 'streamiov-scene-pack',
        version: SCENE_VERSION,
        transition: { ...this.transition },
        scenes: JSON.parse(JSON.stringify(selected))
      }
    };
  }
  importScenePack(raw) {
    const pack = raw && typeof raw === 'object' ? raw : {};
    if (pack.kind !== 'streamiov-scene-pack' || pack.version !== SCENE_VERSION ||
        !Array.isArray(pack.scenes) || !pack.scenes.length) {
      return { ok: false, error: 'Kein gültiges Streamiov-Szenenpaket.' };
    }
    if (this.scenes.length + pack.scenes.length > MAX_SCENES) {
      return { ok: false, error: `Maximal ${MAX_SCENES} Szenen sind möglich.` };
    }
    const existingNames = new Set(this.scenes.map(scene => scene.name.toLowerCase()));
    const imported = [];
    const dependencies = [];
    const idMap = new Map();
    for (const rawScene of pack.scenes) {
      const scene = cleanScene(rawScene);
      if (!scene || scene.kind !== 'custom') return { ok: false, error: 'Szenenpaket enthält eine ungültige Szene.' };
      const originalId = scene.id;
      scene.id = randomUUID();
      idMap.set(originalId, scene.id);
      let name = scene.name;
      let counter = 2;
      while (existingNames.has(name.toLowerCase())) {
        name = `${scene.name.slice(0, 57)} ${counter}`;
        counter += 1;
        if (counter > 999) return { ok: false, error: 'Kein eindeutiger Szenenname verfügbar.' };
      }
      existingNames.add(name.toLowerCase());
      scene.name = name;
      scene.sources = scene.sources.map(item => ({ ...item, id: randomUUID() }));
      dependencies.push(cleanDependencyIds(rawScene.dependsOn));
      scene.dependsOn = [];
      imported.push(scene);
    }
    imported.forEach((scene, index) => {
      scene.dependsOn = dependencies[index]
        .map(id => idMap.get(id))
        .filter(id => id && id !== scene.id)
        .slice(0, MAX_DEPENDENCIES);
    });
    sanitizeSceneDependencies([...this.scenes, ...imported]);
    this.scenes.push(...imported);
    this.transition = cleanTransition(pack.transition);
    this.previewSceneId = imported[0].id;
    return this._result();
  }
  take(transitionInput) {
    let transition;
    if (transitionInput === undefined) {
      transition = { ...this.transition };
    } else {
      transition = transitionFromInput(transitionInput);
      if (!transition) return { ok: false, error: 'Ungültiger Übergang.' };
    }
    const previousSceneId = this.programSceneId;
    this.transition = transition;
    this.programSceneId = this.previewSceneId;
    const result = this._result();
    result.previousSceneId = previousSceneId;
    return result;
  }
  // Directly switch the program scene without changing the preview. Used by
  // Schutzregie and future emergency actions; TAKE remains the normal path.
  setProgramScene(sceneNameOrId) {
    const value = typeof sceneNameOrId === 'string' ? sceneNameOrId.trim() : '';
    const scene = this.scenes.find(item => item.name === value) ||
      this.scenes.find(item => item.id === value);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    this.transition = { ...DEFAULT_TRANSITION };
    this.programSceneId = scene.id;
    return this._result();
  }
  setTransition(raw) {
    const transition = transitionFromInput(raw);
    if (!transition) return { ok: false, error: 'Übergang muss CUT, FADE, SLIDE oder WIPE mit 100 bis 2000 ms sein.' };
    this.transition = transition;
    return this._result();
  }
  setOverlay(raw) {
    const scene = this._preview();
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    const overlay = overlayFromInput(raw);
    if (!overlay) return { ok: false, error: 'Ungültige Overlay-Einstellung.' };
    if (overlay.style === 'custom' && !overlay.text.trim()) {
      return { ok: false, error: 'Eigenes Overlay benötigt einen Text.' };
    }
    scene.overlay = overlay;
    return this._result();
  }
  setSceneDependencies(sceneId, raw) {
    const scene = this.scenes.find(item => item.id === sceneId);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    if (scene.kind !== 'custom') return { ok: false, error: 'Nur eigene Szenen können Abhängigkeiten haben.' };
    const ids = new Set(this.scenes.map(item => item.id));
    const requested = cleanDependencyIds(raw);
    if (requested.some(id => id === sceneId || !ids.has(id))) {
      return { ok: false, error: 'Abhängigkeiten müssen andere vorhandene Szenen sein.' };
    }
    const dependencyMap = new Map(this.scenes.map(item => [item.id, item.id === sceneId ? [] : item.dependsOn]));
    for (const id of requested) {
      if (hasDependencyCycle(dependencyMap, sceneId, id)) {
        return { ok: false, error: 'Szenenabhängigkeiten dürfen keinen Zyklus bilden.' };
      }
    }
    scene.dependsOn = requested;
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
  updateSource(sourceId, patch = {}, sceneId) {
    const scene = sceneId ? this.scenes.find(item => item.id === sceneId) : this._preview();
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    const source = scene.sources.find(item => item.id === sourceId);
    if (!source) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
    const safe = patch && typeof patch === 'object' ? patch : {};
    const candidate = cleanSource({ ...source, ...safe, id: source.id }, source.z);
    if (!candidate) return { ok: false, error: 'Ungültige Quellenänderung.' };
    Object.assign(source, candidate);
    if (!candidate.settings) delete source.settings;
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
        overlay: { ...scene.overlay },
        sources: scene.sources.map(source => ({
          ...source,
          ...(source.settings ? { settings: { ...source.settings } } : {}),
          ...(source.audio ? { audio: { ...source.audio, routes: [...source.audio.routes] } } : {})
        }))
      })),
      previewSceneId: this.previewSceneId,
      programSceneId: this.programSceneId,
      transition: { ...this.transition },
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
      transition: state.transition,
      updatedAt: new Date().toISOString()
    };
  }
}
module.exports = {
  DEFAULT_SCENES,
  DEFAULT_BACKGROUND,
  MAX_SCENES,
  MAX_SOURCES,
  MAX_DEPENDENCIES,
  SCENE_VERSION,
  SOURCE_TYPES,
  AUDIO_ROUTES,
  AUDIO_CAPABLE_TYPES,
  SOURCE_TRANSFORM_FIT_MODES,
  TRANSITION_TYPES,
  OVERLAY_STYLES,
  StudioSceneEngine
};
