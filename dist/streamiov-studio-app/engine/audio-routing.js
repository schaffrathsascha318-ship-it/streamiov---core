'use strict';

// Platform-neutral audio routing state contract. This module stores intent only;
// a native capture/mixer/output adapter must apply it before audio is considered active.
const OUTPUT_IDS = Object.freeze(['stream', 'monitor', 'headphones', 'communications']);
const SOURCE_IDS = Object.freeze(['microphone', 'music', 'game', 'alerts', 'tts']);

function assertId(value, allowed, label) {
  if (!allowed.includes(value)) throw new TypeError(`Unknown audio ${label}: ${String(value)}`);
}

function normalizeVolume(value) {
  if (!Number.isInteger(value) || value < 0 || value > 100) {
    throw new RangeError('Audio output volume must be an integer from 0 to 100.');
  }
  return value;
}

function normalizeDeviceId(value) {
  if (typeof value !== 'string' || value.length > 256 || /[\u0000-\u001f]/.test(value)) {
    throw new TypeError('Audio output device ID must be a string of at most 256 safe characters.');
  }
  return value || 'default';
}

function createAudioRoutingState(saved = {}) {
  const outputs = {};
  for (const id of OUTPUT_IDS) {
    const input = saved.outputs && saved.outputs[id] || {};
    outputs[id] = Object.freeze({
      id,
      deviceId: normalizeDeviceId(input.deviceId ?? 'default'),
      volume: normalizeVolume(input.volume ?? 100),
      muted: input.muted === true,
      adapterStatus: 'not_connected'
    });
  }

  const routes = {};
  for (const source of SOURCE_IDS) {
    const supplied = saved.routes && saved.routes[source];
    const destinations = Array.isArray(supplied)
      ? [...new Set(supplied)]
      : ['stream', 'monitor'];
    for (const destination of destinations) assertId(destination, OUTPUT_IDS, 'output');
    routes[source] = Object.freeze(destinations);
  }

  return Object.freeze({
    version: 1,
    status: 'configuration_only',
    outputs: Object.freeze(outputs),
    routes: Object.freeze(routes)
  });
}

function updateOutput(state, outputId, patch) {
  assertId(outputId, OUTPUT_IDS, 'output');
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
    throw new TypeError('Audio output update must be an object.');
  }
  const current = state.outputs[outputId];
  const next = {
    ...current,
    ...(Object.hasOwn(patch, 'volume') ? { volume: normalizeVolume(patch.volume) } : {}),
    ...(Object.hasOwn(patch, 'muted') ? { muted: patch.muted === true } : {}),
    ...(Object.hasOwn(patch, 'deviceId') ? { deviceId: normalizeDeviceId(patch.deviceId) } : {})
  };
  return Object.freeze({
    ...state,
    outputs: Object.freeze({ ...state.outputs, [outputId]: Object.freeze(next) })
  });
}

function setSourceRoutes(state, sourceId, outputIds) {
  assertId(sourceId, SOURCE_IDS, 'source');
  if (!Array.isArray(outputIds)) throw new TypeError('Audio routes must be an array.');
  const destinations = [...new Set(outputIds)];
  for (const outputId of destinations) assertId(outputId, OUTPUT_IDS, 'output');
  return Object.freeze({
    ...state,
    routes: Object.freeze({ ...state.routes, [sourceId]: Object.freeze(destinations) })
  });
}

function serializeAudioRoutingState(state) {
  const outputs = {};
  for (const id of OUTPUT_IDS) {
    const { deviceId, volume, muted } = state.outputs[id];
    outputs[id] = { deviceId, volume, muted };
  }
  const routes = {};
  for (const source of SOURCE_IDS) routes[source] = [...state.routes[source]];
  return { version: 1, outputs, routes };
}

module.exports = {
  OUTPUT_IDS,
  SOURCE_IDS,
  createAudioRoutingState,
  updateOutput,
  setSourceRoutes,
  serializeAudioRoutingState
};
