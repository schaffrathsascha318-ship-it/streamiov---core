'use strict';

/**
 * Shared capability detection for Streamiov Studio.
 *
 * This module deliberately reports capabilities instead of assuming that
 * every device can perform every capture/encoding operation. Native mobile
 * adapters can be added without changing the scene/Regie model.
 */

function detectPlatform(input = {}) {
  const runtime = input.runtime || {};
  const userAgent = String(input.userAgent || '').toLowerCase();
  const platform = String(input.platform || '').toLowerCase();

  if (runtime.capacitor && runtime.capacitor.isNativePlatform) {
    const nativePlatform = String(runtime.capacitor.getPlatform?.() || '').toLowerCase();
    if (nativePlatform === 'android' || nativePlatform === 'ios') return nativePlatform;
  }

  if (runtime.electron) {
    const nodePlatform = String(input.nodePlatform || '').toLowerCase();
    if (nodePlatform === 'win32') return 'windows';
    if (nodePlatform === 'darwin') return 'macos';
    if (nodePlatform === 'linux') return 'linux';
  }

  if (/android/.test(userAgent)) return 'android';
  if (/iphone|ipad|ipod/.test(userAgent) || (platform === 'macintel' && input.maxTouchPoints > 1)) return 'ios';
  if (/cros/.test(userAgent)) return 'chromeos';
  if (/win/.test(platform)) return 'windows';
  if (/linux/.test(platform)) return 'linux';
  if (/mac/.test(platform)) return 'macos';
  return 'unknown';
}

function getStudioCapabilities(input = {}) {
  const platform = detectPlatform(input);
  const runtime = input.runtime || {};
  const mediaDevices = input.mediaDevices || {};
  const mediaStream = input.mediaStream || {};
  const audioElement = input.audioElement || {};

  const isElectron = Boolean(runtime.electron);
  const isNativeMobile = Boolean(runtime.capacitor && runtime.capacitor.isNativePlatform);
  const isMobile = platform === 'android' || platform === 'ios';
  const browserCapture = typeof mediaDevices.getUserMedia === 'function';
  const screenCapture = typeof mediaDevices.getDisplayMedia === 'function';
  const audioOutputRouting = typeof audioElement.setSinkId === 'function';

  return Object.freeze({
    platform,
    runtime: isElectron ? 'electron' : isNativeMobile ? 'capacitor' : 'web',
    deviceClass: isMobile ? 'mobile' : platform === 'chromeos' ? 'chromebook' :
      ['windows', 'linux', 'macos'].includes(platform) ? 'desktop' : 'unknown',
    capabilities: Object.freeze({
      camera: browserCapture || isNativeMobile,
      microphone: browserCapture || isNativeMobile,
      screenCapture: isElectron || screenCapture,
      systemAudioCapture: isElectron,
      independentAudioOutputs: audioOutputRouting || isElectron || isNativeMobile,
      nativeNotifications: isElectron || isNativeMobile,
      localFileAccess: isElectron || isNativeMobile,
      hardwareEncoding: isElectron || isNativeMobile
    }),
    limitations: Object.freeze({
      browserScreenCaptureRequiresUserGesture: !isElectron && !isNativeMobile,
      systemAudioCapturePlatformDependent: true,
      hardwareEncodingMustBeProbedAtRuntime: true,
      nativeMobileAdapterRequired: isMobile
    })
  });
}

module.exports = { detectPlatform, getStudioCapabilities };
