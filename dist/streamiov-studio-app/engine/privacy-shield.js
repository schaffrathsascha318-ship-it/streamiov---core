'use strict';
// Schutzregie / Privacy Shield: a local, free state machine for an emergency
// program scene and microphone mute. It deliberately does not stop the encoder,
// recording, or any platform-side capture. The renderer applies the returned
// target/restore values to the scene engine and audio mixer.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.StreamioVPrivacyShield = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const SHIELD_VERSION = 1;
  const DEFAULT_PAUSE_SCENE_ID = 'pause';

  const validSceneId = value => {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return /^[a-zA-Z0-9_-]{1,80}$/.test(trimmed) ? trimmed : null;
  };
  const clampPercent = (value, fallback) => {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0, Math.min(100, Math.round(number))) : fallback;
  };

  class PrivacyShield {
    constructor(options = {}) {
      const safe = options && typeof options === 'object' ? options : {};
      this.pauseSceneId = validSceneId(safe.pauseSceneId) || DEFAULT_PAUSE_SCENE_ID;
      this.active = false;
      this.restoreState = null;
      this.activationCount = 0;
      this.lastActivatedAt = null;
      this.lastRestoredAt = null;

      // Hydration from local storage is only trusted when a real restore state
      // exists. An active flag without restore data is treated as inactive.
      if (safe.active === true && safe.restoreState && typeof safe.restoreState === 'object') {
        this.active = true;
        this.restoreState = {
          programSceneId: validSceneId(safe.restoreState.programSceneId),
          micPercent: clampPercent(safe.restoreState.micPercent, 100)
        };
        const count = Number(safe.activationCount);
        this.activationCount = Number.isFinite(count) && count >= 0 ? Math.trunc(count) : 1;
        this.lastActivatedAt = typeof safe.lastActivatedAt === 'string' ? safe.lastActivatedAt : null;
      }
    }

    _target() {
      return { programSceneId: this.pauseSceneId, micPercent: 0 };
    }

    _copyRestore() {
      return this.restoreState ? { ...this.restoreState } : null;
    }

    activate(context = {}) {
      const safe = context && typeof context === 'object' ? context : {};
      if (this.active) {
        return {
          ok: true,
          changed: false,
          reason: 'already-active',
          target: this._target(),
          restore: this._copyRestore(),
          state: this.snapshot()
        };
      }
      this.restoreState = {
        programSceneId: validSceneId(safe.programSceneId),
        micPercent: clampPercent(safe.micPercent, 100)
      };
      this.active = true;
      this.activationCount += 1;
      this.lastActivatedAt = new Date().toISOString();
      return {
        ok: true,
        changed: true,
        reason: 'activated',
        target: this._target(),
        restore: this._copyRestore(),
        state: this.snapshot()
      };
    }

    // Deactivate and return the exact values that should be restored. The
    // renderer owns the actual scene/mixer application.
    deactivate() {
      if (!this.active) {
        return {
          ok: true,
          changed: false,
          reason: 'not-active',
          target: null,
          restore: null,
          state: this.snapshot()
        };
      }
      const restore = this._copyRestore();
      this.active = false;
      this.restoreState = null;
      this.lastRestoredAt = new Date().toISOString();
      return {
        ok: true,
        changed: true,
        reason: 'deactivated',
        target: null,
        restore,
        state: this.snapshot()
      };
    }

    // Explicit alias: restoring means deactivating and handing the saved values
    // back to the caller.
    restore() {
      return this.deactivate();
    }

    snapshot() {
      return {
        version: SHIELD_VERSION,
        active: this.active,
        pauseSceneId: this.pauseSceneId,
        activationCount: this.activationCount,
        restoreState: this._copyRestore(),
        lastActivatedAt: this.lastActivatedAt,
        lastRestoredAt: this.lastRestoredAt,
        target: this.active ? this._target() : null,
        scope: 'program-scene-and-local-mic-mix',
        stopsEncoder: false,
        stopsRecording: false,
        guaranteesPlatformPrivacy: false
      };
    }
  }

  return { SHIELD_VERSION, DEFAULT_PAUSE_SCENE_ID, PrivacyShield };
});
