'use strict';

const FEATURE_KEYS = Object.freeze([
  'camera', 'microphone', 'screenCapture', 'multiDisplay',
  'fileAccess', 'audioOutput', 'notifications', 'touchInput'
]);

const STATUS = Object.freeze({
  AVAILABLE: 'available',
  LIMITED: 'limited',
  UNSUPPORTED: 'unsupported'
});

function normalizeCapability(value) {
  if (value === true || value === STATUS.AVAILABLE) {
    return { status: STATUS.AVAILABLE, reason: 'Vom Geräteadapter erkannt und verfügbar.' };
  }
  if (value === false || value === STATUS.UNSUPPORTED) {
    return { status: STATUS.UNSUPPORTED, reason: 'Dieser Geräteadapter stellt die Funktion nicht bereit.' };
  }
  if (value === STATUS.LIMITED) {
    return { status: STATUS.LIMITED, reason: 'Die Funktion ist nur eingeschränkt verfügbar.' };
  }
  return { status: STATUS.LIMITED, reason: 'Noch nicht durch den Geräteadapter geprüft.' };
}

/**
 * Creates the platform-neutral capability report consumed by every Regie UI.
 * Feature values must come from measured adapter results; the core never guesses.
 */
function resolveDeviceCapabilities({ platform = 'unknown', architecture = 'unknown', features = {} } = {}) {
  const capabilities = {};
  for (const feature of FEATURE_KEYS) capabilities[feature] = normalizeCapability(features[feature]);
  return Object.freeze({
    platform: String(platform).toLowerCase(),
    architecture: String(architecture).toLowerCase(),
    capabilities: Object.freeze(capabilities)
  });
}

/** Select presentation density only; this never changes which Regie features exist. */
function resolveRegieLayout({ width = 1024, height = 768, coarsePointer = false } = {}) {
  const safeWidth = Number.isFinite(Number(width)) ? Math.max(0, Number(width)) : 1024;
  const safeHeight = Number.isFinite(Number(height)) ? Math.max(0, Number(height)) : 768;
  let formFactor = 'desktop';
  if (safeWidth < 720) formFactor = 'phone';
  else if (safeWidth < 1100) formFactor = 'tablet';
  return Object.freeze({
    formFactor,
    inputMode: coarsePointer ? 'touch' : 'pointer',
    orientation: safeWidth >= safeHeight ? 'landscape' : 'portrait',
    navigation: formFactor === 'phone' ? 'compact' : 'expanded',
    columns: formFactor === 'phone' ? 1 : formFactor === 'tablet' ? 2 : 3
  });
}

module.exports = { FEATURE_KEYS, STATUS, resolveDeviceCapabilities, resolveRegieLayout };
