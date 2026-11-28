'use strict';

const { spawn } = require('node:child_process');
const { StreamHealth } = require('./stream-health');

const PLATFORMS = Object.freeze(['twitch', 'tiktok']);
const MAX_RETRIES = 3;
const RETRY_DELAYS_MS = Object.freeze([1000, 2000, 4000]);
const MAX_CHUNK_BYTES = 4 * 1024 * 1024;
const MAX_STDIN_QUEUE_BYTES = 8 * 1024 * 1024;

class LiveOutputManager {
  constructor({ spawnImpl = spawn, setTimeoutImpl = setTimeout, clearTimeoutImpl = clearTimeout, onEvent = () => {}, onHealthEvent = () => {}, health = null } = {}) {
    this.outputs = new Map();
    this.spawnImpl = spawnImpl;
    this.setTimeoutImpl = setTimeoutImpl;
    this.clearTimeoutImpl = clearTimeoutImpl;
    this.onEvent = typeof onEvent === 'function' ? onEvent : () => {};
    this.health = health || new StreamHealth({
      onEvent: (platform, status, details) => {
        if (typeof onHealthEvent === 'function') onHealthEvent(platform, status, details);
      }
    });
  }

  isActive(platform) {
    if (platform === undefined || platform === null) return this.outputs.size > 0;
    return this.outputs.has(platform);
  }

  activePlatforms() {
    return [...this.outputs.keys()];
  }

  start({ platform, executable, args, destination }) {
    if (!PLATFORMS.includes(platform)) return { ok: false, error: 'Unbekannte LIVE-Plattform.' };
    if (typeof executable !== 'string' || !executable || !Array.isArray(args) || !args.length || !destination) {
      return { ok: false, error: 'Ungültige Encoder-Konfiguration.' };
    }
    if (this.outputs.has(platform)) return { ok: false, error: 'Für diese Plattform läuft bereits eine Ausgabe.' };
    this.health.reset(platform);
    return this.#launch({ platform, executable, args, destination, attempt: 0 });
  }

  #launch(config) {
    const output = {
      platform: config.platform,
      config,
      attempt: config.attempt,
      child: null,
      retryTimer: null,
      stopping: false,
      ready: false,
      settled: false,
      retrying: false
    };
    try {
      output.child = this.spawnImpl(config.executable, config.args, { stdio: ['pipe', 'ignore', 'pipe'], windowsHide: true });
    } catch (error) {
      this.health.recordFailure(config.platform, 'Encoder konnte nicht gestartet werden.');
      this.health.stop(config.platform);
      this.onEvent(config.platform, 'error', { detail: 'Encoder konnte nicht gestartet werden.', attempt: config.attempt });
      return { ok: false, error: 'Encoder konnte nicht gestartet werden.' };
    }
    this.outputs.set(config.platform, output);
    this.onEvent(config.platform, 'starting', { detail: 'RTMP-Ausgabe wird gestartet.', attempt: config.attempt });

    output.child.once('spawn', () => {
      if (this.outputs.get(config.platform) === output && !output.stopping) {
        this.onEvent(config.platform, 'connecting', { detail: 'RTMP-Verbindung wird hergestellt.', attempt: config.attempt });
      }
    });
    if (output.child.stderr && typeof output.child.stderr.on === 'function') {
      output.child.stderr.on('data', chunk => {
        if (this.outputs.get(config.platform) !== output || output.ready || output.stopping) return;
        const text = chunk.toString('utf8');
        if (text.includes('Output #0, flv')) {
          output.ready = true;
          this.onEvent(config.platform, 'output_ready', { detail: 'Encoder-Ausgabe initialisiert; RTMP-Empfang nicht bestätigt.', attempt: config.attempt });
        }
      });
    }
    output.child.once('error', () => this.#unexpectedExit(output));
    output.child.once('close', () => this.#unexpectedExit(output));
    return { ok: true, platform: config.platform, status: 'starting' };
  }

  #unexpectedExit(output) {
    if (output.settled || output.stopping) return;
    output.settled = true;
    output.child = null;
    if (output.attempt >= MAX_RETRIES) {
      if (this.outputs.get(output.platform) === output) this.outputs.delete(output.platform);
      const detail = 'Die RTMP-Verbindung wurde wiederholt unterbrochen. Bitte Ziel, Stream-Key und Netzwerk prüfen.';
      this.health.recordFailure(output.platform, detail);
      this.health.stop(output.platform);
      this.onEvent(output.platform, 'error', {
        detail,
        attempt: output.attempt
      });
      return;
    }
    const delay = RETRY_DELAYS_MS[output.attempt] || RETRY_DELAYS_MS[RETRY_DELAYS_MS.length - 1];
    const nextAttempt = output.attempt + 1;
    output.retrying = true;
    this.health.recordRetry(output.platform, nextAttempt, 'RTMP-Verbindung unterbrochen.');
    this.onEvent(output.platform, 'reconnecting', {
      detail: `RTMP-Verbindung unterbrochen; neuer Versuch in ${delay} ms.`,
      attempt: nextAttempt
    });
    output.retryTimer = this.setTimeoutImpl(() => {
      if (output.stopping) return;
      this.#launch({ ...output.config, attempt: nextAttempt });
    }, delay);
    if (typeof output.retryTimer?.unref === 'function') output.retryTimer.unref();
  }

  async write(chunk) {
    const isBytes = Buffer.isBuffer(chunk) || ArrayBuffer.isView(chunk) ||
      Object.prototype.toString.call(chunk) === '[object ArrayBuffer]';
    if (!isBytes) return { ok: false, errors: ['Ungültiger Medienblock.'] };
    if (chunk.byteLength > MAX_CHUNK_BYTES) return { ok: false, errors: ['Medienblock zu groß.'] };
    const active = [...this.outputs.values()].filter(output => !output.stopping && output.child && !output.retrying);
    if (!active.length) return { ok: false, errors: ['Kein aktiver LIVE-Ausgang.'] };
    const results = await Promise.all(active.map(output => new Promise(resolve => {
      const input = output.child.stdin;
      if (!input || input.destroyed || input.writableLength > MAX_STDIN_QUEUE_BYTES) {
        this.health.recordFailure(output.platform, 'Der Encoder kann Medien nicht schnell genug verarbeiten.');
        resolve({ platform: output.platform, ok: false, error: 'Der Encoder kann Medien nicht schnell genug verarbeiten.' });
        return;
      }
      const bytes = Buffer.from(chunk);
      input.write(bytes, error => {
        if (error) this.health.recordFailure(output.platform, 'Medien konnten nicht an den Encoder gesendet werden.');
        else this.health.recordWrite(output.platform, bytes.byteLength);
        resolve({
          platform: output.platform,
          ok: !error,
          error: error ? 'Medien konnten nicht an den Encoder gesendet werden.' : null
        });
      });
    })));
    const errors = results.filter(result => !result.ok);
    return errors.length ? { ok: false, errors } : { ok: true, written: results.length };
  }

  async stop(platform) {
    const output = this.outputs.get(platform);
    if (!output) return { ok: true, platform, stopped: false };
    output.stopping = true;
    if (output.retryTimer) this.clearTimeoutImpl(output.retryTimer);
    if (this.outputs.get(platform) === output) this.outputs.delete(platform);
    this.health.stop(platform);
    if (!output.child || output.retrying) {
      this.onEvent(platform, 'offline', { detail: 'LIVE-Ausgabe beendet.' });
      return { ok: true, platform, stopped: false };
    }
    const child = output.child;
    const input = child.stdin;
    if (input && !input.destroyed) input.end();
    const killTimer = this.setTimeoutImpl(() => {
      if (child.exitCode === null && child.signalCode === null) {
        try { child.kill('SIGINT'); } catch {}
      }
    }, 3000);
    if (typeof killTimer.unref === 'function') killTimer.unref();
    await new Promise(resolve => {
      if (child.exitCode !== null || child.signalCode !== null) { resolve(); return; }
      child.once('close', resolve);
      const guard = this.setTimeoutImpl(resolve, 5000);
      if (typeof guard.unref === 'function') guard.unref();
    });
    this.clearTimeoutImpl(killTimer);
    this.onEvent(platform, 'offline', { detail: 'LIVE-Ausgabe beendet.' });
    return { ok: true, platform, stopped: true };
  }

  async stopAll() {
    const platforms = this.activePlatforms();
    const results = [];
    for (const platform of platforms) results.push(await this.stop(platform));
    return results;
  }

  snapshot() {
    return Object.fromEntries([...this.outputs.values()].map(output => [output.platform, Object.freeze({
      platform: output.platform,
      attempt: output.attempt,
      ready: output.ready,
      retrying: output.retrying,
      stopping: output.stopping,
      health: this.health.snapshot(output.platform)
    })]));
  }

  healthSnapshot() {
    return this.health.snapshotAll();
  }
}

module.exports = { LiveOutputManager, PLATFORMS, MAX_RETRIES, RETRY_DELAYS_MS };
