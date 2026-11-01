'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { FEATURE_KEYS, STATUS, resolveDeviceCapabilities, resolveRegieLayout } = require('./device-capabilities');

test('same complete capability set is exposed on every platform', () => {
  const report = resolveDeviceCapabilities({
    platform: 'ChromeOS', architecture: 'ARM64',
    features: { camera: true, microphone: 'limited', multiDisplay: false }
  });
  assert.equal(report.platform, 'chromeos');
  assert.equal(report.architecture, 'arm64');
  assert.deepEqual(Object.keys(report.capabilities), [...FEATURE_KEYS]);
  assert.equal(report.capabilities.camera.status, STATUS.AVAILABLE);
  assert.equal(report.capabilities.microphone.status, STATUS.LIMITED);
  assert.equal(report.capabilities.multiDisplay.status, STATUS.UNSUPPORTED);
  assert.equal(report.capabilities.screenCapture.status, STATUS.LIMITED);
});

test('unknown hardware support is never guessed as available', () => {
  const report = resolveDeviceCapabilities({ platform: 'ios' });
  for (const feature of FEATURE_KEYS) {
    assert.equal(report.capabilities[feature].status, STATUS.LIMITED);
    assert.match(report.capabilities[feature].reason, /noch nicht/i);
  }
});

test('responsive layout changes density, not the shared Regie feature model', () => {
  assert.deepEqual(resolveRegieLayout({ width: 390, height: 844, coarsePointer: true }), {
    formFactor: 'phone', inputMode: 'touch', orientation: 'portrait', navigation: 'compact',
    columns: 1, contentRegieArrangement: 'stacked'
  });
  assert.equal(resolveRegieLayout({ width: 900, height: 600 }).columns, 2);
  assert.equal(resolveRegieLayout({ width: 1440, height: 900 }).columns, 3);
});

test('invalid viewport values fall back safely', () => {
  assert.equal(resolveRegieLayout({ width: 'not-a-number' }).formFactor, 'tablet');
});

test('capability reports and their nested map are immutable', () => {
  const report = resolveDeviceCapabilities();
  assert.equal(Object.isFrozen(report), true);
  assert.equal(Object.isFrozen(report.capabilities), true);
});
