'use strict';

const { randomUUID } = require('node:crypto');

const SOURCE_TYPES = Object.freeze([
  'camera', 'capture', 'screen', 'window', 'image', 'video', 'audio', 'text', 'color'
]);
const MAX_SOURCES = 64;
const validId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(value);

function cleanSource(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null;
  if (!validId(input.id) || !SOURCE_TYPES.includes(input.type)) return null;
  if (typeof input.name !== 'string') return null;
  const name = input.name.trim();
  if (!name || name.length > 80) return null;
  const volume = Number.isFinite(input.volume) ? Math.min(1, Math.max(0, input.volume)) : 1;
  return {
    id: input.id,
    type: input.type,
    name,
    enabled: input.enabled !== false,
    muted: input.muted === true,
    volume
  };
}

class StudioSourceModel {
  constructor(saved = {}) {
    const raw = saved && Array.isArray(saved.sources) ? saved.sources : [];
    const seen = new Set();
    this.sources = raw
      .map(cleanSource)
      .filter(source => {
        if (!source || seen.has(source.id) || this.sources?.length >= MAX_SOURCES) return false;
        seen.add(source.id);
        return true;
      })
      .slice(0, MAX_SOURCES);
  }

  add(input) {
    if (this.sources.length >= MAX_SOURCES) return { ok: false, error: 'Maximal 64 Quellen sind möglich.' };
    const source = cleanSource({ ...input, id: input?.id || randomUUID() });
    if (!source) return { ok: false, error: 'Ungültige Quelle: Typ, ID und Name prüfen.' };
    if (this.sources.some(item => item.id === source.id)) return { ok: false, error: 'Quellen-ID existiert bereits.' };
    this.sources.push(source);
    return { ok: true, state: this.snapshot(), source: { ...source } };
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
    return { version: 1, sources: this.sources.map(source => ({ ...source })) };
  }

  toJSON() {
    return this.snapshot();
  }
}

module.exports = { SOURCE_TYPES, MAX_SOURCES, StudioSourceModel };
