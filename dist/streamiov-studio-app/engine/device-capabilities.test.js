'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { FEATURE_KEYS, STATUS, resolveDeviceCapabilities, resolveRegieLayout } = require('./device-capabilities');

test('all devices expose the same Regie capability keys', () => {
  const report = resolveDeviceCapabilities({
    platform: 'Android', architecture: 'arm64',
    features: { camera: true, touchInput: true, multiDisplay: false }
  });
  assert.deepEqual(Object.keys(report.capabilities), [...FEATURE_KEYS]);
  assert.equal(report.capabilities.camera.status, STATUS.AVAILABLE);
  assert.equal(report.capabilities.multiDisplay.status, STATUS.UNSUPPORTED);
  assert.equal(report.capabilities.microphone.status, STATUS.LIMITED);
});

test('unknown device features remain limited instead of being guessed available', () => {
  const report = resolveDeviceCapabilities({ platform: 'ios' });
  for (const feature of FEATURE_KEYS) {
    assert.equal(report.capabilities[feature].status, STATUS.LIMITED);
  }
});

test('phone stacks content above Regie while desktop keeps separate surfaces', () => {
  const phone = resolveRegieLayout({ width: 390, height: 844, coarsePointer: true });
  assert.equal(phone.formFactor, 'phone');
  assert.equal(phone.inputMode, 'touch');
  assert.equal(phone.contentRegieArrangement, 'stacked');
  assert.equal(phone.navigation, 'compact');
  const desktop = resolveRegieLayout({ width: 1440, height: 900 });
  assert.equal(desktop.contentRegieArrangement, 'separate-surfaces');
  assert.equal(desktop.columns, 3);
});

test('tablet uses a two-column touch-friendly layout', () => {
  const tablet = resolveRegieLayout({ width: 900, height: 1200, coarsePointer: true });
  assert.equal(tablet.formFactor, 'tablet');
  assert.equal(tablet.contentRegieArrangement, 'separate-surfaces');
  assert.equal(tablet.columns, 2);
});
