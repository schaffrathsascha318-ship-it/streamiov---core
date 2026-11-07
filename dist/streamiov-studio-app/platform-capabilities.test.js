'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { detectPlatform, getStudioCapabilities } = require('./platform-capabilities');

test('detects Windows Electron runtime', () => {
  assert.equal(detectPlatform({ runtime: { electron: true }, nodePlatform: 'win32' }), 'windows');
});

test('detects Linux Electron runtime', () => {
  assert.equal(detectPlatform({ runtime: { electron: true }, nodePlatform: 'linux' }), 'linux');
});

test('detects ChromeOS from the browser user agent', () => {
  assert.equal(detectPlatform({ userAgent: 'Mozilla/5.0 (X11; CrOS x86_64 15600.0.0)' }), 'chromeos');
});

test('detects native Android and iOS Capacitor runtimes', () => {
  const capacitor = { isNativePlatform: true, getPlatform: () => 'android' };
  assert.equal(detectPlatform({ runtime: { capacitor } }), 'android');
  assert.equal(detectPlatform({ runtime: { capacitor: { ...capacitor, getPlatform: () => 'ios' } } }), 'ios');
});

test('reports only APIs actually available in a browser runtime', () => {
  const result = getStudioCapabilities({
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
    platform: 'Linux x86_64',
    mediaDevices: { getUserMedia() {}, getDisplayMedia() {} },
    audioElement: {}
  });
  assert.equal(result.platform, 'linux');
  assert.equal(result.capabilities.camera, true);
  assert.equal(result.capabilities.microphone, true);
  assert.equal(result.capabilities.screenCapture, true);
  assert.equal(result.capabilities.independentAudioOutputs, false);
  assert.equal(result.limitations.hardwareEncodingMustBeProbedAtRuntime, true);
});

test('does not promise unsupported browser system-audio capture', () => {
  const result = getStudioCapabilities({
    userAgent: 'Mozilla/5.0 (Linux; Android 15)',
    mediaDevices: { getUserMedia() {} }
  });
  assert.equal(result.platform, 'android');
  assert.equal(result.deviceClass, 'mobile');
  assert.equal(result.capabilities.systemAudioCapture, false);
  assert.equal(result.limitations.nativeMobileAdapterRequired, true);
});
