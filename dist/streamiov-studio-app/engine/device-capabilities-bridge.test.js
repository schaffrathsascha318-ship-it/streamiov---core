'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { STATUS, FEATURE_KEYS } = require('./device-capabilities');
const {
  countMediaDevices,
  evaluateMediaDevices,
  collectRendererMeasurements,
  createDeviceCapabilityReport,
  summarizeDeviceCapabilities
} = require('./device-capabilities-bridge');

test('media device counts are bounded and never guessed', () => {
  assert.deepEqual(
    { ...countMediaDevices([{ kind: 'videoinput' }, { kind: 'videoinput' }, { kind: 'audioinput' }, null]) },
    { videoinput: 2, audioinput: 1, audiooutput: 0 }
  );
  assert.equal(countMediaDevices(null), null);
  assert.equal(Object.isFrozen(countMediaDevices([])), true);
  assert.equal(countMediaDevices(Array.from({ length: 500 }, () => ({ kind: 'videoinput' }))).videoinput, 200);
});

test('media device enumeration is measured, bounded, and never guessed', () => {
  assert.deepEqual(evaluateMediaDevices([
    { kind: 'videoinput' },
    { kind: 'audioinput' },
    { kind: 'audiooutput' },
    { kind: 'unknown' }
  ]), { camera: true, microphone: true, audioOutput: true });
  assert.deepEqual(evaluateMediaDevices([]), {
    camera: false, microphone: false, audioOutput: false
  });
  assert.deepEqual(evaluateMediaDevices(null), {});
  const oversized = Array.from({ length: 500 }, () => ({ kind: 'videoinput' }));
  assert.equal(Object.keys(evaluateMediaDevices(oversized)).length, 3);
});

test('renderer measurements become normalised evidence with their source', () => {
  const measurements = collectRendererMeasurements({
    devices: [{ kind: 'videoinput' }, { kind: 'audioinput' }],
    features: {
      touchInput: { value: true, source: '<script>matchMedia</script>' },
      screenCapture: { value: 'unsupported', source: 'adapter' },
      camera: false
    }
  });
  assert.equal(measurements.camera.status, STATUS.UNSUPPORTED);
  assert.equal(measurements.microphone.status, STATUS.AVAILABLE);
  assert.equal(measurements.audioOutput.status, STATUS.UNSUPPORTED);
  assert.equal(measurements.touchInput.status, STATUS.AVAILABLE);
  assert.equal(measurements.touchInput.source, 'script matchMedia /script');
  assert.equal(measurements.screenCapture.status, STATUS.UNSUPPORTED);
});

test('capability report maps platform and architecture to stable names', () => {
  const report = createDeviceCapabilityReport({
    platform: 'win32',
    architecture: 'x64',
    measurements: { camera: { value: true, source: 'device-enumeration' } },
    observedAt: '2026-11-25T00:00:00Z'
  });
  assert.equal(report.platform, 'windows');
  assert.equal(report.architecture, 'x86_64');
  assert.equal(report.observedAt, '2026-11-25T00:00:00.000Z');
  assert.equal(report.capabilities.camera.status, STATUS.AVAILABLE);
  assert.deepEqual(report.evidence.camera, {
    status: STATUS.AVAILABLE,
    source: 'device-enumeration'
  });
  assert.equal(Object.isFrozen(report), true);
  assert.equal(Object.isFrozen(report.evidence), true);
});

test('unmeasured features stay limited and raw invalid values are discarded', () => {
  const report = createDeviceCapabilityReport({
    platform: 'unknown-platform',
    architecture: 'mystery',
    measurements: { camera: 'probably', microphone: null, screenCapture: false }
  });
  assert.equal(report.platform, 'unknown');
  assert.equal(report.architecture, 'unknown');
  assert.equal(report.capabilities.camera.status, STATUS.LIMITED);
  assert.equal(report.capabilities.microphone.status, STATUS.LIMITED);
  assert.equal(report.capabilities.screenCapture.status, STATUS.UNSUPPORTED);
  for (const feature of FEATURE_KEYS) {
    assert.ok(report.capabilities[feature]);
  }
  assert.deepEqual(Object.keys(report.evidence), ['screenCapture']);
});

test('summary exposes only measured states and is usable in the Regie', () => {
  const report = createDeviceCapabilityReport({
    platform: 'darwin',
    architecture: 'arm64',
    measurements: { camera: true, microphone: STATUS.LIMITED }
  });
  const summary = summarizeDeviceCapabilities(report);
  assert.match(summary, /^macos\/arm64:/);
  assert.match(summary, /Kamera verfügbar/);
  assert.match(summary, /Mikrofon ungeprüft/);
  assert.match(summary, /Bildschirm ungeprüft/);
});
