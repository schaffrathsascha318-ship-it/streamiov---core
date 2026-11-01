"use strict";

/**
 * STREAMIOV media runtime coordinator.
 *
 * This module coordinates real adapters; it does not pretend to capture,
 * composite, encode or publish by itself. LIVE is reachable only after the
 * output adapter positively confirms an active transport.
 */
const STATES = Object.freeze({
  IDLE: "idle",
  PREVIEWING: "previewing",
  CONNECTING: "connecting",
  LIVE: "live",
  RECONNECTING: "reconnecting",
  STOPPING: "stopping",
  ERROR: "error",
});

const ALLOWED_OUTPUT_PROTOCOLS = new Set(["rtmp:", "rtmps:"]);

class MediaRuntimeError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "MediaRuntimeError";
    this.code = code;
  }
}

function requireMethod(adapter, method, name) {
  if (!adapter || typeof adapter[method] !== "function") {
    throw new MediaRuntimeError("ADAPTER_UNAVAILABLE", `${name} adapter must implement ${method}().`);
  }
}

function safeDestination(value) {
  let parsed;
  try { parsed = new URL(value); } catch {
    throw new MediaRuntimeError("INVALID_DESTINATION", "A valid RTMP/RTMPS destination is required.");
  }
  if (!ALLOWED_OUTPUT_PROTOCOLS.has(parsed.protocol) || parsed.username || parsed.password) {
    throw new MediaRuntimeError("INVALID_DESTINATION", "Only RTMP/RTMPS destinations without embedded credentials are allowed.");
  }
  return parsed.toString();
}

class MediaRuntime {
  constructor({ compositor, mixer, encoder, output, onState = () => {} }) {
    this.adapters = { compositor, mixer, encoder, output };
    this.onState = onState;
    this.state = STATES.IDLE;
    this.lastError = null;
    this.startedAt = null;
    this.outputConfirmed = false;
    this.busy = false;
  }

  snapshot() {
    return Object.freeze({
      state: this.state,
      previewActive: this.state === STATES.PREVIEWING ||
        this.state === STATES.CONNECTING || this.state === STATES.LIVE ||
        this.state === STATES.RECONNECTING,
      outputConfirmed: this.outputConfirmed,
      live: this.state === STATES.LIVE && this.outputConfirmed,
      startedAt: this.startedAt,
      error: this.lastError,
    });
  }

  _setState(state, error = null) {
    this.state = state;
    this.lastError = error;
    if (state !== STATES.LIVE) this.outputConfirmed = false;
    const snapshot = this.snapshot();
    try { this.onState(snapshot); } catch { /* observers cannot break the media runtime */ }
    return snapshot;
  }

  async startPreview(sceneGraph) {
    if (this.busy) throw new MediaRuntimeError("BUSY", "A media transition is already running.");
    if (this.state !== STATES.IDLE && this.state !== STATES.ERROR) {
      throw new MediaRuntimeError("INVALID_STATE", "Preview can only start from idle or error.");
    }
    requireMethod(this.adapters.compositor, "start", "Compositor");
    requireMethod(this.adapters.mixer, "start", "Mixer");
    this.busy = true;
    try {
      await this.adapters.mixer.start();
      await this.adapters.compositor.start({ sceneGraph, mode: "preview" });
      this._setState(STATES.PREVIEWING);
      return this.snapshot();
    } catch (error) {
      await this._bestEffortStop(["compositor", "mixer"]);
      this._setState(STATES.ERROR, "PREVIEW_START_FAILED");
      throw new MediaRuntimeError("PREVIEW_START_FAILED", "Preview could not be started.");
    } finally {
      this.busy = false;
    }
  }

  async startOutput({ destination, streamKey, profile }) {
    if (this.busy) throw new MediaRuntimeError("BUSY", "A media transition is already running.");
    if (this.state !== STATES.PREVIEWING) {
      throw new MediaRuntimeError("PREVIEW_REQUIRED", "A working preview is required before output can connect.");
    }
    if (typeof streamKey !== "string" || streamKey.length < 8 || streamKey.length > 2048) {
      throw new MediaRuntimeError("INVALID_STREAM_KEY", "A valid stream key is required.");
    }
    const safeUrl = safeDestination(destination);
    for (const [adapter, method, name] of [
      [this.adapters.encoder, "start", "Encoder"],
      [this.adapters.output, "connect", "Output"],
      [this.adapters.output, "isActive", "Output"],
    ]) requireMethod(adapter, method, name);

    this.busy = true;
    this._setState(STATES.CONNECTING);
    try {
      await this.adapters.encoder.start({ profile });
      await this.adapters.output.connect({ destination: safeUrl, streamKey });
      // Transport confirmation is authoritative; a successful connect() call
      // alone is deliberately insufficient to display LIVE.
      if (await this.adapters.output.isActive() === true) {
        this.outputConfirmed = true;
        this.startedAt = new Date().toISOString();
        this._setState(STATES.LIVE);
      }
      return this.snapshot();
    } catch (error) {
      await this._bestEffortStop(["output", "encoder", "compositor", "mixer"]);
      this._setState(STATES.ERROR, "OUTPUT_START_FAILED");
      throw new MediaRuntimeError("OUTPUT_START_FAILED", "Stream output could not be established.");
    } finally {
      this.busy = false;
    }
  }

  confirmOutputActive(active) {
    if (this.state !== STATES.CONNECTING && this.state !== STATES.RECONNECTING &&
        this.state !== STATES.LIVE) {
      throw new MediaRuntimeError("INVALID_STATE", "Output confirmation is not expected in the current state.");
    }
    if (active !== true) return this.outputLost();
    this.outputConfirmed = true;
    this.startedAt ||= new Date().toISOString();
    return this._setState(STATES.LIVE);
  }

  outputLost() {
    if (![STATES.CONNECTING, STATES.LIVE, STATES.RECONNECTING].includes(this.state)) {
      throw new MediaRuntimeError("INVALID_STATE", "No active output can be lost in the current state.");
    }
    this.startedAt = null;
    return this._setState(STATES.RECONNECTING, "OUTPUT_INTERRUPTED");
  }

  async stop() {
    if (this.busy) throw new MediaRuntimeError("BUSY", "A media transition is already running.");
    if (this.state === STATES.IDLE) return this.snapshot();
    this.busy = true;
    this._setState(STATES.STOPPING);
    try {
      await this._bestEffortStop(["output", "encoder", "compositor", "mixer"]);
      this.startedAt = null;
      this._setState(STATES.IDLE);
      return this.snapshot();
    } finally {
      this.busy = false;
    }
  }

  async _bestEffortStop(names) {
    const methods = { output: "disconnect", encoder: "stop", compositor: "stop", mixer: "stop" };
    for (const name of names) {
      const adapter = this.adapters[name];
      const method = methods[name];
      if (adapter && typeof adapter[method] === "function") {
        try { await adapter[method](); } catch { /* continue shutdown of remaining adapters */ }
      }
    }
  }
}

module.exports = { MediaRuntime, MediaRuntimeError, STATES };
