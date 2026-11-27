'use strict';
// Schutzregie / Privacy Shield: a local, free state machine for an emergency
// program scene and microphone mute. On activation the renderer requests a stop
// of the local encoder output and any active local recording before applying
// the target values. Deactivation restores only scene and mic; the operator
// must restart the broadcast manually. Platform-side capture stays out of scope.
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
          requestsOutputStops: true,
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
        requestsOutputStops: true,
        target: this._target(),
        restore: this._copyRestore(),
        state: this.snapshot()
      };
    }

    // Deactivate and return the exact scene/mic values that should be restored.
    // The renderer owns the actual application; stopped outputs stay stopped and
    // the operator restarts the broadcast manually.
    deactivate() {
      if (!this.active) {
        return {
          ok: true,
          changed: false,
          reason: 'not-active',
          target: null,
          restore: null,
          resumesOutputs: false,
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
        resumesOutputs: false,
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
        scope: 'program-scene-local-mic-mix-and-local-output-stop-requests',
        stopsEncoder: true,
        stopsRecording: true,
        autoResumesOutputs: false,
        guaranteesPlatformPrivacy: false
      };
    }
  }

  return { SHIELD_VERSION, DEFAULT_PAUSE_SCENE_ID, PrivacyShield };
});
