'use strict';

/**
 * Local multi-bus Web Audio mixer.
 * Each input has independent gain/mute and can be routed to one or more
 * isolated MediaStreamDestination buses (for example stream, monitor,
 * or a per-source stem). No network output is created here.
 */
class StudioAudioMixer {
  constructor({ AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext } = {}) {
    if (typeof AudioContextClass !== 'function') throw new Error('Web Audio is not available.');
    this.context = new AudioContextClass();
    this.buses = new Map();
    this.channels = new Map();
    this.closed = false;
    this.createBus('stream');
    this.createBus('monitor');
  }

  async resume() {
    this.#assertOpen();
    if (this.context.state === 'suspended') await this.context.resume();
  }

  createBus(name) {
    this.#assertOpen();
    this.#validateName(name, 'bus');
    if (this.buses.has(name)) return this.buses.get(name).stream;
    const destination = this.context.createMediaStreamDestination();
    this.buses.set(name, destination);
    return destination.stream;
  }

  connect(name, stream, { gain = 1, muted = false, routes = ['stream'] } = {}) {
    this.#assertOpen();
    this.#validateName(name, 'channel');
    if (!stream || typeof stream.getAudioTracks !== 'function' || stream.getAudioTracks().length === 0) {
      throw new TypeError('A MediaStream with at least one audio track is required.');
    }
    this.#validateGain(gain);
    const normalizedRoutes = this.#normalizeRoutes(routes);
    this.disconnect(name);
    const input = this.context.createMediaStreamSource(stream);
    const gainNode = this.context.createGain();
    gainNode.gain.value = muted ? 0 : gain;
    input.connect(gainNode);
    const channel = { input, gainNode, stream, gain, muted: muted === true, routes: normalizedRoutes };
    this.channels.set(name, channel);
    this.#applyRoutes(channel);
    return this.snapshot(name);
  }

  setRoutes(name, routes) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error('Mixer channel not found.');
    channel.routes = this.#normalizeRoutes(routes);
    this.#applyRoutes(channel);
    return this.snapshot(name);
  }

  setGain(name, gain) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error('Mixer channel not found.');
    this.#validateGain(gain);
    channel.gain = gain;
    channel.gainNode.gain.setTargetAtTime(channel.muted ? 0 : gain, this.context.currentTime, 0.015);
    return this.snapshot(name);
  }

  setMuted(name, muted) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error('Mixer channel not found.');
    channel.muted = muted === true;
    channel.gainNode.gain.setTargetAtTime(channel.muted ? 0 : channel.gain, this.context.currentTime, 0.015);
    return this.snapshot(name);
  }

  disconnect(name) {
    const channel = this.channels.get(name);
    if (!channel) return false;
    try { channel.input.disconnect(); } catch {}
    try { channel.gainNode.disconnect(); } catch {}
    this.channels.delete(name);
    return true;
  }

  getOutputStream(bus = 'stream') {
    this.#assertOpen();
    const destination = this.buses.get(bus);
    if (!destination) throw new Error('Mixer output bus not found.');
    return destination.stream;
  }

  async attachMonitor(element, { deviceId = '' } = {}) {
    this.#assertOpen();
    if (!element || typeof element !== 'object') throw new TypeError('An audio element is required.');
    const stream = this.getOutputStream('monitor');
    element.autoplay = true;
    element.playsInline = true;
    if (element.srcObject !== stream) element.srcObject = stream;
    if (deviceId) {
      if (typeof element.setSinkId !== 'function') throw new Error('Selecting a physical audio output is not supported by this runtime.');
      await element.setSinkId(deviceId);
    }
    await this.resume();
    await element.play();
    return { connected: true, deviceId: typeof element.sinkId === 'string' ? element.sinkId : '' };
  }

  detachMonitor(element) {
    if (!element || typeof element !== 'object') return false;
    element.pause?.();
    if ('srcObject' in element) element.srcObject = null;
    return true;
  }

  getBusNames() {
    this.#assertOpen();
    return [...this.buses.keys()];
  }

  snapshot(name) {
    const channel = this.channels.get(name);
    if (!channel) return null;
    return { name, gain: channel.gain, muted: channel.muted, routes: [...channel.routes], connected: true };
  }

  #normalizeRoutes(routes) {
    if (!Array.isArray(routes) || routes.length === 0) throw new TypeError('At least one output bus is required.');
    const normalized = [...new Set(routes)];
    for (const name of normalized) {
      this.#validateName(name, 'bus');
      if (!this.buses.has(name)) throw new Error('Mixer output bus not found: ' + name);
    }
    return normalized;
  }

  #applyRoutes(channel) {
    try { channel.gainNode.disconnect(); } catch {}
    for (const name of channel.routes) channel.gainNode.connect(this.buses.get(name));
  }

  #validateName(name, kind) {
    if (typeof name !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/i.test(name)) {
      throw new TypeError('Invalid mixer ' + kind + ' name.');
    }
  }

  #validateGain(gain) {
    if (!Number.isFinite(gain) || gain < 0 || gain > 2) throw new RangeError('Gain must be between 0 and 2.');
  }

  #assertOpen() {
    if (this.closed) throw new Error('Audio mixer is closed.');
  }

  async close() {
    if (this.closed) return;
    for (const name of [...this.channels.keys()]) this.disconnect(name);
    for (const bus of this.buses.values()) {
      for (const track of bus.stream.getTracks()) track.stop();
    }
    this.buses.clear();
    this.closed = true;
    await this.context.close();
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { StudioAudioMixer };
if (typeof globalThis !== 'undefined') globalThis.StreamiovAudioMixer = StudioAudioMixer;
