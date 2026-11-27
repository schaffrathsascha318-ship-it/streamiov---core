'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  EVENT_SCHEMA_VERSION,
  StudioEventValidationError,
  normaliseData,
  createStudioEvent,
} = require('./studio-event-client');

test('Studio event payloads are versioned and source is set by the trusted client', () => {
  const event = createStudioEvent({
    type: 'studio.scene.take',
    data: { scene: ' LIVE ', take: 2 },
    eventId: '11111111-1111-4111-8111-111111111111',
    occurredAt: '2026-11-26T12:00:00Z',
  });
  assert.equal(event.schema_version, EVENT_SCHEMA_VERSION);
  assert.equal(event.source, 'studio');
  assert.equal(event.type, 'studio.scene.take');
  assert.equal(event.severity, 'info');
  assert.equal(event.occurred_at, '2026-11-26T12:00:00.000Z');
  assert.deepEqual(event.data, { scene: 'LIVE', take: 2 });
  assert.equal(Object.isFrozen(event), true);
});

test('Studio event client accepts a local gift effect preview event', () => {
  const event = createStudioEvent({
    type: 'studio.gift.effect_preview',
    data: { template_id: 'rose', template_name: 'Rose', effect_id: 'heart', effect_symbol: '♥', local_points: 1 },
    eventId: '22222222-2222-4222-8222-222222222222',
    occurredAt: '2026-11-26T12:00:00Z',
  });
  assert.equal(event.type, 'studio.gift.effect_preview');
  assert.deepEqual(event.data, { template_id: 'rose', template_name: 'Rose', effect_id: 'heart', effect_symbol: '♥', local_points: 1 });
});

test('Studio event client rejects invalid types and renderer-controlled fields', () => {
  assert.throws(() => createStudioEvent({
    type: 'platform.gift.fake',
    eventId: '11111111-1111-4111-8111-111111111111',
  }), StudioEventValidationError);
  assert.throws(() => createStudioEvent({
    type: 'studio.scene.take',
    eventId: 'not-a-uuid',
  }), StudioEventValidationError);
  assert.throws(() => normaliseData({ nested: { value: true } }), StudioEventValidationError);
});

test('Studio event client redacts credentials and RTMP destinations', () => {
  const data = normaliseData({
    streamKey: 'secret',
    password: 'secret',
    destination: 'rtmps://live.example/app/key',
    note: 'stream rtmps://live.example/app/key end',
    scene: 'LIVE',
  });
  assert.equal(data.streamKey, '[REDACTED]');
  assert.equal(data.password, '[REDACTED]');
  assert.equal(data.destination, '[REDACTED]');
  assert.equal(data.note, 'stream [RTMP-URL REDACTED] end');
  assert.equal(data.scene, 'LIVE');
  assert.equal(JSON.stringify(data).includes('secret'), false);
  assert.equal(JSON.stringify(data).includes('rtmps://'), false);
});
