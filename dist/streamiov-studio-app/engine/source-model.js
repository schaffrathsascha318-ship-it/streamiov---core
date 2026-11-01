'use strict';

const { randomUUID } = require('node:crypto');

const SOURCE_TYPES = Object.freeze([
  'camera', 'capture', 'screen', 'window', 'image', 'video', 'audio', 'text', 'color'
]);
const MAX_SOURCES = 64;
const validId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(value);
const validOpaqueId = value => typeof value === 'string' && value.length > 0 &&
  value.length <= 512 && !/[\u0000-\u001f\u007f]/.test(value);
const validDimension = value => Number.isInteger(value) && value >= 320 && value <= 3840;
const validHeight = value => Number.isInteger(value) && value >= 180 && value <= 2160;
const validFps = value => Number.isInteger(value) && value >= 15 && value <= 60;
const validColor = value => typeof value === 'string' && /^#[0-9a-f]{6}(?:[0-9a-f]{2})?$/i.test(value);

function cleanSettings(type, raw) {
  if (raw === undefined) return undefined;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const allowed = {
    camera: ['deviceId', 'width', 'height', 'fps'],
    audio: ['deviceId'],
    capture: ['sourceId', 'displayId', 'width', 'height', 'fps'],
    screen: ['sourceId', 'displayId', 'width', 'height', 'fps'],
    window: ['sourceId', 'displayId', 'width', 'height', 'fps'],
    image: ['assetId', 'loop'],
    video: ['assetId', 'loop'],
    text: ['text', 'fontSize', 'color'],
    color: ['color']
  }[type] || [];
  if (Object.keys(raw).some(key => !allowed.includes(key))) return null;

  const settings = {};
  for (const key of allowed) {
    if (!Object.prototype.hasOwnProperty.call(raw, key)) continue;
    const value = raw[key];
    if (key === 'deviceId' || key === 'sourceId' || key === 'displayId') {
      if (!validOpaqueId(value)) return null;
      settings[key] = value;
    } else if (key === 'width') {
      if (!validDimension(value)) return null;
      settings[key] = value;
    } else if (key === 'height') {
      if (!validHeight(value)) return null;
      settings[key] = value;
    } else if (key === 'fps') {
      if (!validFps(value)) return null;
      settings[key] = value;
    } else if (key === 'assetId') {
      if (!validId(value)) return null;
      settings[key] = value;
    } else if (key === 'loop') {
      if (typeof value !== 'boolean') return null;
      settings[key] = value;
    } else if (key === 'text') {
      if (typeof value !== 'string' || value.length > 500 ||
          /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)) return null;
      settings[key] = value;
    } else if (key === 'fontSize') {
      if (!Number.isInteger(value) || value < 8 || value > 128) return null;
      settings[key] = value;
    } else if (key === 'color') {
      if (!validColor(value)) return null;
      settings[key] = value.toLowerCase();
    }
  }
  return settings;
}

function cleanSource(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null;
  if (!validId(input.id) || !SOURCE_TYPES.includes(input.type)) return null;
  if (typeof input.name !== 'string') return null;
  const name = input.name.trim();
  if (!name || name.length > 80) return null;
  const volume = Number.isFinite(input.volume) ? Math.min(1, Math.max(0, input.volume)) : 1;
  const settings = cleanSettings(input.type, input.settings);
  if (settings === null) return null;
  const source = {
    id: input.id,
    type: input.type,
    name,
    enabled: input.enabled !== false,
    muted: input.muted === true,
    volume
  };
  if (settings && Object.keys(settings).length) source.settings = settings;
  return source;
}

class StudioSourceModel {
  constructor(saved = {}) {
    const raw = saved && Array.isArray(saved.sources) ? saved.sources : [];
    const seen = new Set();
    this.sources = raw
      .map(cleanSource)
      .filter(source => {
        if (!source || seen.has(source.id)) return false;
        seen.add(source.id);
        return true;
      })
      .slice(0, MAX_SOURCES);
  }

  add(input) {
    if (this.sources.length >= MAX_SOURCES) return { ok: false, error: 'Maximal 64 Quellen sind möglich.' };
    const source = cleanSource({ ...input, id: input?.id || randomUUID() });
    if (!source) return { ok: false, error: 'Ungültige Quelle: Typ, ID, Name oder Einstellungen prüfen.' };
    if (this.sources.some(item => item.id === source.id)) return { ok: false, error: 'Quellen-ID existiert bereits.' };
    this.sources.push(source);
    return { ok: true, state: this.snapshot(), source: { ...source, settings: source.settings ? { ...source.settings } : undefined } };
  }

  update(id, patch = {}) {
    const index = this.sources.findIndex(item => item.id === id);
    if (index < 0) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
    const candidate = cleanSource({ ...this.sources[index], ...patch, id });
    if (!candidate) return { ok: false, error: 'Ungültige Quellenänderung.' };
    this.sources[index] = candidate;
    return { ok: true, state: this.snapshot() };
  }

  remove(id) {
    const index = this.sources.findIndex(item => item.id === id);
    if (index < 0) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
    this.sources.splice(index, 1);
    return { ok: true, state: this.snapshot() };
  }

  reorder(ids) {
    if (!Array.isArray(ids) || ids.length !== this.sources.length) {
      return { ok: false, error: 'Die Reihenfolge muss jede Quelle genau einmal enthalten.' };
    }
    const existing = new Set(this.sources.map(item => item.id));
    if (new Set(ids).size !== ids.length || ids.some(id => !existing.has(id))) {
      return { ok: false, error: 'Ungültige oder doppelte Quellen-ID.' };
    }
    const byId = new Map(this.sources.map(item => [item.id, item]));
    this.sources = ids.map(id => byId.get(id));
    return { ok: true, state: this.snapshot() };
  }

  snapshot() {
    return {
      version: 1,
      sources: this.sources.map(source => ({
        ...source,
        ...(source.settings ? { settings: { ...source.settings } } : {})
      }))
    };
  }

  toJSON() {
    return this.snapshot();
  }
}

module.exports = { SOURCE_TYPES, MAX_SOURCES, StudioSourceModel, cleanSettings };
