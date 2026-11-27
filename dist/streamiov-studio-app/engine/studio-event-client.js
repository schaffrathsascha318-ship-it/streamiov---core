'use strict';

const EVENT_SCHEMA_VERSION = 1;
const SOURCES = Object.freeze(['core', 'studio', 'game', 'ai']);
const TYPES = Object.freeze([
  'studio.scene.take',
  'studio.scene.program',
  'studio.game.detected',
  'studio.gameplay.observation',
  'studio.game.highlight',
  'studio.game.replay_marker',
  'studio.game.assistant_advice',
  'studio.game.frame_analysis',
  'studio.game.situation',
  'studio.game.replay_analyzed',
  'studio.game.profile_updated',
  'studio.game.strategy',
  'studio.game.voice_command',
  'studio.game.auto_detection',
  'studio.gift.effect_preview',
  'studio.platform.event.received',
  'studio.alert.keyword',
  'studio.alert.platform_event',
  'studio.stream.started',
  'studio.stream.stopped',
  'studio.stream.error',
  'studio.shield.changed',
  'studio.connection.changed',
  'core.health.changed',
  'ai.task.submitted',
]);
const SEVERITIES = Object.freeze(['info', 'warning', 'error']);
const KEY_PATTERN = /^[A-Za-z][A-Za-z0-9_.-]{0,48}$/;
const SENSITIVE_KEY_PATTERN = /token|secret|password|passwort|stream.?key|authorization|cookie|rtmp|destination|credential|state|code/i;
const RTMP_PATTERN = /\brtmps?:\/\/[^\s]+/gi;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_DATA_KEYS = 30;
const MAX_STRING = 240;
const MAX_EVENT_BYTES = 4096;

class StudioEventValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'StudioEventValidationError';
  }
}

function normaliseData(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).length > MAX_DATA_KEYS) {
    throw new StudioEventValidationError(`data must be an object with at most ${MAX_DATA_KEYS} fields.`);
  }
  const result = {};
  for (const [key, value] of Object.entries(input)) {
    if (!KEY_PATTERN.test(key)) {
      throw new StudioEventValidationError('data keys must be short identifiers.');
    }
    if (SENSITIVE_KEY_PATTERN.test(key)) {
      result[key] = '[REDACTED]';
      continue;
    }
    if (value === null || typeof value === 'boolean') {
      result[key] = value;
    } else if (typeof value === 'number') {
      if (!Number.isFinite(value) || Math.abs(value) > 1e12) {
        throw new StudioEventValidationError('data numbers are out of range.');
      }
      result[key] = value;
    } else if (typeof value === 'string') {
      const text = value.replace(/\u0000/g, '').trim().replace(/\s+/g, ' ').slice(0, MAX_STRING);
      result[key] = text.replace(RTMP_PATTERN, '[RTMP-URL REDACTED]');
    } else {
      throw new StudioEventValidationError('data values must be scalar.');
    }
  }
  const encoded = JSON.stringify(result);
  const bytes = typeof TextEncoder !== 'undefined' ? new TextEncoder().encode(encoded).length : encoded.length;
  if (bytes > MAX_EVENT_BYTES) {
    throw new StudioEventValidationError(`data must stay below ${MAX_EVENT_BYTES} bytes.`);
  }
  return Object.freeze(result);
}

function createStudioEvent({ type, data = {}, eventId, occurredAt, severity = 'info' }) {
  if (!TYPES.includes(type)) {
    throw new StudioEventValidationError('unsupported event type.');
  }
  if (!SEVERITIES.includes(severity)) {
    throw new StudioEventValidationError('unsupported event severity.');
  }
  if (typeof eventId !== 'string' || !UUID_PATTERN.test(eventId)) {
    throw new StudioEventValidationError('eventId must be a UUID.');
  }
  const timestamp = typeof occurredAt === 'string' ? new Date(occurredAt) : new Date();
  if (!Number.isFinite(timestamp.getTime())) {
    throw new StudioEventValidationError('occurredAt must be a valid timestamp.');
  }
  return Object.freeze({
    event_id: eventId.toLowerCase(),
    schema_version: EVENT_SCHEMA_VERSION,
    source: 'studio',
    type,
    severity,
    occurred_at: timestamp.toISOString(),
    data: normaliseData(data),
  });
}

const api = Object.freeze({
  EVENT_SCHEMA_VERSION,
  SOURCES,
  TYPES,
  SEVERITIES,
  StudioEventValidationError,
  normaliseData,
  createStudioEvent,
});

if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (typeof window !== 'undefined') window.StreamioVStudioEventClient = api;
