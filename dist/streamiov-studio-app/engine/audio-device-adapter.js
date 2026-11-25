'use strict';

/**
 * Browser/Electron audio-device adapter. It reports only browser-exposed
 * capabilities and never upgrades a device to connected without a live stream.
 */
class StudioAudioDeviceAdapter {
  constructor({ mediaDevices = globalThis.navigator?.mediaDevices, mixer = null, platform = globalThis.navigator?.platform || 'unknown' } = {}) {
    this.mediaDevices = mediaDevices;
    this.mixer = mixer;
    this.platform = String(platform).toLowerCase();
    this.closed = false;
  }

  async listDevices() {
    this.#assertOpen();
    if (!this.mediaDevices?.enumerateDevices) return { inputs: [], outputs: [], available: false };
    const devices = await this.mediaDevices.enumerateDevices();
    return {
      available: true,
      inputs: devices.filter(device => ['audioinput', 'videoinput'].includes(device.kind)),
      outputs: devices.filter(device => device.kind === 'audiooutput')
    };
  }

  capabilities() {
    return Object.freeze({
      audioInput: typeof this.mediaDevices?.getUserMedia === 'function',
      displayCapture: typeof this.mediaDevices?.getDisplayMedia === 'function',
      deviceEnumeration: typeof this.mediaDevices?.enumerateDevices === 'function',
      outputDeviceSelection: typeof globalThis.HTMLMediaElement !== 'undefined' &&
        typeof globalThis.HTMLMediaElement.prototype?.setSinkId === 'function',
      platform: this.platform,
      state: 'capability_report_only'
    });
  }

  async openMicrophone({ deviceId = '', echoCancellation = false, noiseSuppression = false, autoGainControl = false } = {}) {
    this.#assertOpen();
    if (!this.mediaDevices?.getUserMedia) throw new Error('Mikrofonaufnahme wird von diesem Geräteadapter nicht unterstützt.');
    const audio = {
      echoCancellation: Boolean(echoCancellation),
      noiseSuppression: Boolean(noiseSuppression),
      autoGainControl: Boolean(autoGainControl)
    };
    if (deviceId) audio.deviceId = { exact: deviceId };
    const stream = await this.mediaDevices.getUserMedia({ video: false, audio });
    const track = stream.getAudioTracks().find(item => item.readyState === 'live');
    if (!track) {
      for (const item of stream.getTracks()) item.stop();
      throw new Error('Das ausgewählte Gerät hat keinen aktiven Mikrofon-Audiotrack geliefert.');
    }
    return stream;
  }

  async attachOutput(bus, element, { deviceId = '' } = {}) {
    this.#assertOpen();
    if (!this.mixer) throw new Error('Audio-Mixer ist nicht verbunden.');
    return this.mixer.attachOutput(bus, element, { deviceId });
  }

  detachOutput(bus, element) {
    if (this.closed || !this.mixer) return false;
    return this.mixer.detachOutput(bus, element);
  }

  watchDevices(callback) {
    this.#assertOpen();
    if (typeof callback !== 'function' || !this.mediaDevices?.addEventListener) return () => {};
    const listener = () => callback();
    this.mediaDevices.addEventListener('devicechange', listener);
    return () => this.mediaDevices.removeEventListener('devicechange', listener);
  }

  #assertOpen() {
    if (this.closed) throw new Error('Audio-Geräteadapter ist geschlossen.');
  }

  close() {
    this.closed = true;
    this.mixer = null;
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { StudioAudioDeviceAdapter };
if (typeof globalThis !== 'undefined') globalThis.StreamiovAudioDeviceAdapter = StudioAudioDeviceAdapter;
