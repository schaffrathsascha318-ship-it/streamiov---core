'use strict';

const PLATFORMS = Object.freeze(['tiktok', 'twitch']);
const STATES = Object.freeze(['offline', 'authorizing', 'ready', 'connecting', 'live', 'reconnecting', 'error']);
const TRANSITIONS = Object.freeze({
  offline: ['authorizing'],
  authorizing: ['offline', 'ready', 'error'],
  ready: ['offline', 'connecting', 'authorizing', 'error', 'live'],
  connecting: ['ready', 'live', 'reconnecting', 'offline', 'error'],
  live: ['reconnecting', 'offline', 'error'],
  reconnecting: ['connecting', 'live', 'offline', 'error'],
  error: ['offline', 'authorizing', 'connecting']
});

class PlatformOutputRegistry {
  constructor() {
    this.outputs = new Map(PLATFORMS.map(platform => [platform, {
      platform,
      state: 'offline',
      updatedAt: new Date().toISOString(),
      detail: 'Noch nicht verbunden.',
      liveConfirmed: false,
      confirmationId: null
    }]));
  }

  transition(platform, nextState, options = {}) {
    if (!PLATFORMS.includes(platform)) throw new TypeError('Unbekannte LIVE-Plattform.');
    if (!STATES.includes(nextState)) throw new TypeError('Unbekannter Ausgangsstatus.');
    const current = this.outputs.get(platform);
    if (!TRANSITIONS[current.state].includes(nextState)) {
      throw new Error('Unzulässiger Statuswechsel: ' + current.state + ' → ' + nextState);
    }

    let confirmationId = null;
    if (nextState === 'live') {
      const evidence = options.evidence;
      if (!evidence || evidence.type !== 'remote_platform_confirmation' ||
          evidence.platform !== platform || typeof evidence.confirmationId !== 'string' ||
          !evidence.confirmationId.trim() || typeof evidence.confirmedAt !== 'string' ||
          !Number.isFinite(Date.parse(evidence.confirmedAt))) {
        throw new Error('LIVE benötigt eine gültige Bestätigung der jeweiligen Remote-Plattform.');
      }
      confirmationId = evidence.confirmationId.trim().slice(0, 200);
    }

    const liveConfirmed = nextState === 'live';
    const detail = typeof options.detail === 'string' ? options.detail.slice(0, 300) : '';
    const next = Object.freeze({
      platform,
      state: nextState,
      updatedAt: new Date().toISOString(),
      detail,
      liveConfirmed,
      confirmationId
    });
    this.outputs.set(platform, next);
    return next;
  }

  snapshot() {
    return Object.freeze(Object.fromEntries(
      [...this.outputs.entries()].map(([platform, state]) => [platform, Object.freeze({ ...state })])
    ));
  }
}

module.exports = { PlatformOutputRegistry, PLATFORMS, STATES };
