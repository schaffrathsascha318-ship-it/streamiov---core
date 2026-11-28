'use strict';

const RESOLUTIONS = Object.freeze({
  '720p': Object.freeze([1280, 720]),
  '1080p': Object.freeze([1920, 1080]),
  '1440p': Object.freeze([2560, 1440])
});

const PROFILES = Object.freeze({
  performance: Object.freeze({
    id: 'performance', label: 'Performance', preset: 'ultrafast',
    tune: 'zerolatency', keyframeFactor: 2, maxBitrate: 10000
  }),
  balanced: Object.freeze({
    id: 'balanced', label: 'Ausgewogen', preset: 'veryfast',
    tune: 'zerolatency', keyframeFactor: 2, maxBitrate: 15000
  }),
  quality: Object.freeze({
    id: 'quality', label: 'Qualität', preset: 'faster',
    tune: 'zerolatency', keyframeFactor: 3, maxBitrate: 20000
  })
});

const DEFAULT_PROFILE = 'balanced';
const FPS_VALUES = Object.freeze([30, 60]);
const MIN_BITRATE = 500;
const MAX_BITRATE = 20000;
const RECOMMENDED_BITRATES = Object.freeze({
  '720p': Object.freeze({ 30: 1500, 60: 2500 }),
  '1080p': Object.freeze({ 30: 3000, 60: 4500 }),
  '1440p': Object.freeze({ 30: 6000, 60: 8000 })
});

function normalizeEncoderProfile(value) {
  if (value === undefined || value === null || value === '') return DEFAULT_PROFILE;
  if (typeof value !== 'string' || !Object.prototype.hasOwnProperty.call(PROFILES, value)) {
    throw new TypeError('Unbekanntes Encoder-Profil.');
  }
  return value;
}

function recommendedBitrate(resolution, fps) {
  if (!Object.prototype.hasOwnProperty.call(RECOMMENDED_BITRATES, resolution) || !FPS_VALUES.includes(fps)) return null;
  return RECOMMENDED_BITRATES[resolution][fps];
}

function validateStreamSettings(settings = {}) {
  const value = settings && typeof settings === 'object' ? settings : {};
  const resolution = typeof value.resolution === 'string' ? value.resolution : '1080p';
  const fps = Number(value.fps);
  const bitrate = Number(value.bitrate);
  if (!Object.prototype.hasOwnProperty.call(RESOLUTIONS, resolution)) {
    return { ok: false, error: 'Ungültige Auflösung.' };
  }
  if (!FPS_VALUES.includes(fps)) return { ok: false, error: 'Ungültige Bildrate.' };
  if (!Number.isInteger(bitrate) || bitrate < MIN_BITRATE || bitrate > MAX_BITRATE) {
    return { ok: false, error: 'Ungültige Bitrate.' };
  }
  let profile;
  try {
    profile = normalizeEncoderProfile(value.profile);
  } catch (error) {
    return { ok: false, error: String(error.message || error) };
  }
  if (bitrate > PROFILES[profile].maxBitrate) {
    return { ok: false, error: `Für das Profil ${PROFILES[profile].label} sind maximal ${PROFILES[profile].maxBitrate} kbps zulässig.` };
  }
  return {
    ok: true,
    settings: Object.freeze({ resolution, fps, bitrate, profile }),
    recommendedBitrate: recommendedBitrate(resolution, fps)
  };
}

function encoderArgsForProfile(profile, fps) {
  const id = normalizeEncoderProfile(profile);
  const selected = PROFILES[id];
  if (!FPS_VALUES.includes(fps)) throw new RangeError('Ungültige Bildrate für das Encoder-Profil.');
  return Object.freeze([
    '-preset', selected.preset, '-tune', selected.tune,
    '-g', String(fps * selected.keyframeFactor), '-keyint_min', String(fps), '-sc_threshold', '0'
  ]);
}

const api = Object.freeze({
  PROFILES, DEFAULT_PROFILE, RESOLUTIONS, FPS_VALUES, MIN_BITRATE, MAX_BITRATE,
  normalizeEncoderProfile, recommendedBitrate, validateStreamSettings, encoderArgsForProfile
});

if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof globalThis !== 'undefined') globalThis.StreamiovEncoderProfiles = api;
