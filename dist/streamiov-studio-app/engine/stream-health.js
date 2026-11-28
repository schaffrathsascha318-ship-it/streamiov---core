'use strict';

const STATUSES = Object.freeze(['waiting', 'healthy', 'degraded', 'stalled', 'offline']);
const MAX_SAMPLES = 120;
const MAX_EVENTS = 50;
const MAX_CHUNK_BYTES = 4 * 1024 * 1024;

class StreamHealth {
  constructor({ windowMs = 10000, stallMs = 5000, failureThreshold = 3, clock = Date.now, onEvent = () => {} } = {}) {
    if (!Number.isFinite(windowMs) || windowMs < 1000 || windowMs > 300000) throw new RangeError('Ungültiges Telemetriefenster.');
    if (!Number.isFinite(stallMs) || stallMs < 500 || stallMs > 60000) throw new RangeError('Ungültige Stillstandsgrenze.');
    if (!Number.isInteger(failureThreshold) || failureThreshold < 1 || failureThreshold > 20) throw new RangeError('Ungültige Fehlergrenze.');
    if (typeof clock !== 'function') throw new TypeError('Eine Uhr ist erforderlich.');
    if (typeof onEvent !== 'function') throw new TypeError('Ein Ereignis-Handler ist erforderlich.');
    this.windowMs = windowMs;
    this.stallMs = stallMs;
    this.failureThreshold = failureThreshold;
    this.clock = clock;
    this.onEvent = onEvent;
    this.entries = new Map();
  }

  #entry(platform) {
    if (typeof platform !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/.test(platform)) {
      throw new TypeError('Ungültige Plattform für die Stromtelemetrie.');
    }
    let entry = this.entries.get(platform);
    if (!entry) {
      entry = {
        platform, samples: [], events: [], chunks: 0, bytes: 0,
        failures: 0, retries: 0, firstWriteAt: null, lastWriteAt: null,
        lastReason: '', status: 'waiting', stopped: false
      };
      this.entries.set(platform, entry);
    }
    return entry;
  }

  #prune(entry, now) {
    entry.samples = entry.samples.filter(sample => now - sample.t <= this.windowMs).slice(-MAX_SAMPLES);
    entry.events = entry.events.filter(event => now - event.t <= this.windowMs).slice(-MAX_EVENTS);
  }

  #evaluate(entry, now) {
    this.#prune(entry, now);
    let next;
    if (entry.stopped) next = 'offline';
    else if (entry.lastWriteAt === null) next = 'waiting';
    else if (now - entry.lastWriteAt > this.stallMs) next = 'stalled';
    else if (entry.events.length >= this.failureThreshold) next = 'degraded';
    else next = 'healthy';
    if (next !== entry.status) {
      entry.status = next;
      this.onEvent(entry.platform, next, this.snapshot(entry.platform, now));
    }
    return entry.status;
  }

  recordWrite(platform, byteLength, now = this.clock()) {
    if (!Number.isFinite(byteLength) || byteLength < 0 || byteLength > MAX_CHUNK_BYTES) {
      throw new RangeError('Ungültige Medienblockgröße.');
    }
    const entry = this.#entry(platform);
    entry.stopped = false;
    entry.chunks += 1;
    entry.bytes += byteLength;
    if (entry.firstWriteAt === null) entry.firstWriteAt = now;
    entry.lastWriteAt = now;
    entry.events = [];
    entry.samples.push({ t: now, bytes: byteLength });
    return this.#evaluate(entry, now);
  }

  recordFailure(platform, reason = '', now = this.clock()) {
    const entry = this.#entry(platform);
    entry.failures += 1;
    entry.events.push({ t: now, kind: 'failure' });
    entry.lastReason = typeof reason === 'string' ? reason.trim().slice(0, 160) : 'Medienblock abgelehnt';
    return this.#evaluate(entry, now);
  }

  recordRetry(platform, attempt = 0, detail = '', now = this.clock()) {
    const entry = this.#entry(platform);
    entry.retries += 1;
    entry.events.push({ t: now, kind: 'retry' });
    entry.lastReason = typeof detail === 'string' && detail.trim()
      ? detail.trim().slice(0, 160) : 'Wiederverbindung ' + String(Number(attempt) || 0);
    return this.#evaluate(entry, now);
  }

  stop(platform, now = this.clock()) {
    const entry = this.#entry(platform);
    if (entry.stopped) return this.snapshot(platform, now);
    entry.stopped = true;
    entry.status = 'offline';
    this.onEvent(platform, 'offline', this.snapshot(platform, now));
    return this.snapshot(platform, now);
  }

  reset(platform) {
    if (typeof platform !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/.test(platform)) {
      throw new TypeError('Ungültige Plattform für die Stromtelemetrie.');
    }
    this.entries.delete(platform);
  }

  snapshot(platform, now = this.clock()) {
    if (typeof platform !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/.test(platform)) {
      throw new TypeError('Ungültige Plattform für die Stromtelemetrie.');
    }
    const entry = this.entries.get(platform);
    if (!entry) {
      return Object.freeze({
        platform, status: 'offline', chunks: 0, bytes: 0, failures: 0, retries: 0,
        kbps: 0, uptimeMs: 0, lastWriteAt: null, lastReason: '', windowMs: this.windowMs
      });
    }
    this.#evaluate(entry, now);
    const windowBytes = entry.samples.reduce((sum, sample) => sum + sample.bytes, 0);
    const elapsed = entry.samples.length > 1 ? Math.max(1000, now - entry.samples[0].t) : 1000;
    const kbps = Math.round((windowBytes * 8 / elapsed) * 10) / 10;
    const uptimeMs = entry.firstWriteAt === null ? 0 : Math.max(0, now - entry.firstWriteAt);
    return Object.freeze({
      platform, status: entry.status, chunks: entry.chunks, bytes: entry.bytes,
      failures: entry.failures, retries: entry.retries,
      kbps, uptimeMs, lastWriteAt: entry.lastWriteAt,
      lastReason: entry.lastReason, windowMs: this.windowMs
    });
  }

  snapshotAll(now = this.clock()) {
    return Object.freeze(Object.fromEntries(
      [...this.entries.keys()].map(platform => [platform, this.snapshot(platform, now)])
    ));
  }
}

const api = Object.freeze({ StreamHealth, STATUSES });

if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof globalThis !== 'undefined') globalThis.StreamiovStreamHealth = api;
