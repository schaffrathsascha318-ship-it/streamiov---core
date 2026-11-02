'use strict';

/**
 * Local multi-bus Web Audio mixer.
 *
 * Each source has its own gain node and explicit routes. Each output bus has
 * a second, independent gain/mute stage before its MediaStreamDestination.
 * This is a real local Web Audio graph, not a native device/encoder adapter.
 */
class StudioAudioMixer {
  constructor({ AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext } = {}) {
    if (typeof AudioContextClass !== 'function') throw new Error('Web Audio is not available.');
    this.context = new AudioContextClass();
    this.buses = new Map();
    this.channels = new Map();
    this.outputElements = new Map();
    this.closed = false;
    for (const name of ['stream', 'monitor', 'headphones', 'communications']) this.createBus(name);
  }

  async resume() {
    this.#assertOpen();
    if (this.context.state === 'suspended') await this.context.resume();
  }

  createBus(name) {
    this.#assertOpen();
    this.#validateName(name, 'bus');
    if (this.buses.has(name)) return this.buses.get(name).destination.stream;
    const destination = this.context.createMediaStreamDestination();
    const gainNode = this.context.createGain();
    gainNode.connect(destination);
    this.buses.set(name, { destination, gainNode, gain: 1, muted: false });
    return destination.stream;
  }

  connect(name, stream, { gain = 1, muted = false, routes = ['stream'] } = {}) {
    this.#assertOpen();
    this.#validateName(name, 'channel');
    if (!stream || typeof stream.getAudioTracks !== 'function' || stream.getAudioTracks().length === 0) {
      throw new TypeError('A MediaStream with at least one audio track is required.');
    }
    this.#validateGain(gain);
    this.#validateBoolean(muted, 'channel mute');
    const normalizedRoutes = this.#normalizeRoutes(routes);
    this.disconnect(name);
    const input = this.context.createMediaStreamSource(stream);
    const gainNode = this.context.createGain();
    gainNode.gain.value = muted ? 0 : gain;
    input.connect(gainNode);
    const channel = { input, gainNode, stream, gain, muted, routes: normalizedRoutes };
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
    this.#validateBoolean(muted, 'channel mute');
    channel.muted = muted;
    channel.gainNode.gain.setTargetAtTime(channel.muted ? 0 : channel.gain, this.context.currentTime, 0.015);
    return this.snapshot(name);
  }

  setOutputGain(name, gain) {
    this.#assertOpen();
    const bus = this.buses.get(name);
    if (!bus) throw new Error('Mixer output bus not found.');
    this.#validateGain(gain);
    bus.gain = gain;
    bus.gainNode.gain.setTargetAtTime(bus.muted ? 0 : gain, this.context.currentTime, 0.015);
    return this.getOutputSnapshot(name);
  }

  setOutputMuted(name, muted) {
    this.#assertOpen();
    const bus = this.buses.get(name);
    if (!bus) throw new Error('Mixer output bus not found.');
    this.#validateBoolean(muted, 'output mute');
    bus.muted = muted;
    bus.gainNode.gain.setTargetAtTime(muted ? 0 : bus.gain, this.context.currentTime, 0.015);
    return this.getOutputSnapshot(name);
  }

  getOutputSnapshot(name) {
    const bus = this.buses.get(name);
    if (!bus) return null;
    return {
      name,
      gain: bus.gain,
      muted: bus.muted,
      streamAvailable: Boolean(bus.destination && bus.destination.stream),
      playbackAttached: this.outputElements.has(name)
    };
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
    const output = this.buses.get(bus);
    if (!output) throw new Error('Mixer output bus not found.');
    return output.destination.stream;
  }

  async attachOutput(busName, element, { deviceId = '' } = {}) {
    this.#assertOpen();
    if (!this.buses.has(busName)) throw new Error('Mixer output bus not found.');
    if (!element || typeof element !== 'object') throw new TypeError('An audio element is required.');
    const previous = this.outputElements.get(busName);
    if (previous && previous !== element) this.detachOutput(busName, previous);
    const stream = this.getOutputStream(busName);
    element.autoplay = true;
    element.playsInline = true;
    try {
      if (element.srcObject !== stream) element.srcObject = stream;
      if (deviceId) {
        if (typeof element.setSinkId !== 'function') {
          throw new Error('Selecting a physical audio output is not supported by this runtime.');
        }
        await element.setSinkId(deviceId);
      }
      await this.resume();
      await element.play();
      this.outputElements.set(busName, element);
      return {
        connected: true,
        bus: busName,
        deviceId: typeof element.sinkId === 'string' ? element.sinkId : '',
        physicalTargetSelected: Boolean(deviceId),
        sinkSelectionSupported: typeof element.setSinkId === 'function'
      };
    } catch (error) {
      // A failed device selection or playback must not leave an untracked
      // stream attached to an audio element.
      try { element.pause?.(); } catch {}
      if (element.srcObject === stream) element.srcObject = null;
      if (this.outputElements.get(busName) === element) this.outputElements.delete(busName);
      throw error;
    }
  }

  detachOutput(busName, element = this.outputElements.get(busName)) {
    if (!element || typeof element !== 'object') return false;
    element.pause?.();
    if ('srcObject' in element) element.srcObject = null;
    if (this.outputElements.get(busName) === element) this.outputElements.delete(busName);
    return true;
  }

  async attachMonitor(element, options = {}) {
    return this.attachOutput('monitor', element, options);
  }

  detachMonitor(element) {
    return this.detachOutput('monitor', element);
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
    if (!Array.isArray(routes)) throw new TypeError('Output routes must be an array.');
    const normalized = [...new Set(routes)];
    for (const name of normalized) {
      this.#validateName(name, 'bus');
      if (!this.buses.has(name)) throw new Error('Mixer output bus not found: ' + name);
    }
    return normalized;
  }

  #applyRoutes(channel) {
    try { channel.gainNode.disconnect(); } catch {}
    for (const name of channel.routes) channel.gainNode.connect(this.buses.get(name).gainNode);
  }

  #validateName(name, kind) {
    if (typeof name !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/i.test(name)) {
      throw new TypeError('Invalid mixer ' + kind + ' name.');
    }
  }

  #validateGain(gain) {
    if (!Number.isFinite(gain) || gain < 0 || gain > 2) throw new RangeError('Gain must be between 0 and 2.');
  }

  #validateBoolean(value, label) {
    if (typeof value !== 'boolean') throw new TypeError(label + ' must be a boolean.');
  }

  #assertOpen() {
    if (this.closed) throw new Error('Audio mixer is closed.');
  }

  async close() {
    if (this.closed) return;
    for (const name of [...this.channels.keys()]) this.disconnect(name);
    for (const [name, element] of this.outputElements) this.detachOutput(name, element);
    for (const bus of this.buses.values()) {
      try { bus.gainNode.disconnect(); } catch {}
      for (const track of bus.destination.stream.getTracks()) track.stop();
    }
    this.buses.clear();
    this.closed = true;
    await this.context.close();
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { StudioAudioMixer };
if (typeof globalThis !== 'undefined') globalThis.StreamiovAudioMixer = StudioAudioMixer;
