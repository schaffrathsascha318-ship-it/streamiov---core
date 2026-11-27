'use strict';

const { FEATURE_KEYS, STATUS, resolveDeviceCapabilities } = require('./device-capabilities');

const PLATFORM_ALIASES = Object.freeze({
  win32: 'windows', darwin: 'macos', linux: 'linux',
  android: 'android', ios: 'ios', chromeos: 'chromeos'
});

const ARCHITECTURE_ALIASES = Object.freeze({
  x64: 'x86_64', x86: 'x86', ia32: 'x86', arm64: 'arm64', arm: 'arm'
});

const MAX_DEVICES = 200;
const MAX_SOURCE_LENGTH = 120;

function cleanSource(source, fallback) {
  if (typeof source !== 'string') return fallback;
  const cleaned = source.replace(/[^A-Za-z0-9._:/-]+/g, ' ').trim();
  return cleaned ? cleaned.slice(0, MAX_SOURCE_LENGTH) : fallback;
}

function parseMeasurement(input, fallbackSource) {
  let value = input;
  let source = fallbackSource;
  if (input && typeof input === 'object' && !Array.isArray(input)) {
    value = input.value;
    source = cleanSource(input.source, fallbackSource);
  }
  if (value === true || value === STATUS.AVAILABLE) {
    return { status: STATUS.AVAILABLE, source };
  }
  if (value === false || value === STATUS.UNSUPPORTED) {
    return { status: STATUS.UNSUPPORTED, source };
  }
  if (value === STATUS.LIMITED) {
    return { status: STATUS.LIMITED, source };
  }
  return null;
}

function countMediaDevices(devices) {
  if (!Array.isArray(devices)) return null;
  const counts = { videoinput: 0, audioinput: 0, audiooutput: 0 };
  for (const device of devices.slice(0, MAX_DEVICES)) {
    if (!device || typeof device.kind !== 'string') continue;
    if (Object.hasOwn(counts, device.kind)) counts[device.kind] += 1;
  }
  return Object.freeze(counts);
}

function evaluateMediaDevices(devices) {
  const counts = countMediaDevices(devices);
  if (!counts) return {};
  return {
    camera: counts.videoinput > 0,
    microphone: counts.audioinput > 0,
    audioOutput: counts.audiooutput > 0
  };
}

function collectRendererMeasurements(payload) {
  const measurements = {};
  const source = 'navigator.mediaDevices.enumerateDevices';
  const fromDevices = evaluateMediaDevices(payload && payload.devices);
  for (const feature of ['camera', 'microphone', 'audioOutput']) {
    if (Object.hasOwn(fromDevices, feature)) {
      measurements[feature] = parseMeasurement(fromDevices[feature], source);
    }
  }
  const features = payload && payload.features;
  if (features && typeof features === 'object' && !Array.isArray(features)) {
    for (const feature of FEATURE_KEYS) {
      if (!Object.hasOwn(features, feature)) continue;
      const parsed = parseMeasurement(features[feature], 'renderer');
      if (parsed) measurements[feature] = parsed;
    }
  }
  return Object.freeze(measurements);
}

function createDeviceCapabilityReport({
  platform = 'unknown',
  architecture = 'unknown',
  measurements = {},
  observedAt
} = {}) {
  const features = {};
  const evidence = {};
  for (const feature of FEATURE_KEYS) {
    const parsed = parseMeasurement(measurements[feature], 'adapter');
    if (!parsed) continue;
    features[feature] = parsed.status;
    evidence[feature] = Object.freeze({ status: parsed.status, source: parsed.source });
  }
  const normalizedPlatform = PLATFORM_ALIASES[String(platform).toLowerCase()] || 'unknown';
  const normalizedArchitecture = ARCHITECTURE_ALIASES[String(architecture).toLowerCase()] || 'unknown';
  const timestamp = typeof observedAt === 'string' && !Number.isNaN(Date.parse(observedAt))
    ? new Date(observedAt).toISOString()
    : new Date().toISOString();
  return Object.freeze({
    ...resolveDeviceCapabilities({
      platform: normalizedPlatform,
      architecture: normalizedArchitecture,
      features
    }),
    evidence: Object.freeze(evidence),
    observedAt: timestamp
  });
}

function summarizeDeviceCapabilities(report) {
  if (!report || !report.capabilities) return 'Geräteprofil nicht verfügbar.';
  const labels = Object.freeze({
    camera: 'Kamera', microphone: 'Mikrofon', screenCapture: 'Bildschirm',
    multiDisplay: 'Mehrere Displays', fileAccess: 'Dateizugriff',
    audioOutput: 'Audioausgang', notifications: 'Benachrichtigungen', touchInput: 'Touch'
  });
  const statusLabels = Object.freeze({
    [STATUS.AVAILABLE]: 'verfügbar',
    [STATUS.LIMITED]: 'ungeprüft',
    [STATUS.UNSUPPORTED]: 'nicht verfügbar'
  });
  return `${report.platform}/${report.architecture}: ` + FEATURE_KEYS
    .map(feature => `${labels[feature]} ${statusLabels[report.capabilities[feature].status]}`)
    .join(' · ');
}

module.exports = {
  PLATFORM_ALIASES,
  ARCHITECTURE_ALIASES,
  countMediaDevices,
  evaluateMediaDevices,
  collectRendererMeasurements,
  createDeviceCapabilityReport,
  summarizeDeviceCapabilities
};
