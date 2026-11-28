'use strict';

/**
 * Local multi-bus Web Audio mixer.
 * Source gain/mute and output gain/mute are independent. Each bus owns a
 * separate MediaStreamDestination; physical playback is opt-in via attachOutput.
 */
class StudioAudioMixer {
  constructor({ AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext } = {}) {
    if (typeof AudioContextClass !== 'function') throw new Error('Web Audio is not available.');
    this.context = new AudioContextClass();
    this.buses = new Map();
    this.channels = new Map();
    this.outputElements = new Map();
    this.soloChannels = new Set();
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
    const limiter = this.context.createDynamicsCompressor();
    const analyser = this.context.createAnalyser();
    analyser.fftSize = 256;
    limiter.threshold.value = -1;
    limiter.knee.value = 0;
    limiter.ratio.value = 20;
    limiter.attack.value = 0.003;
    limiter.release.value = 0.12;
    gainNode.connect(limiter).connect(analyser).connect(destination);
    this.buses.set(name, { destination, gainNode, limiter, analyser, gain: 1, muted: false });
    return destination.stream;
  }

  connect(name, stream, { gain = 1, muted = false, routes = ['stream', 'monitor'] } = {}) {
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
    const highpass = this.context.createBiquadFilter();
    highpass.type = "highpass";
    highpass.frequency.value = 20;
    const compressor = this.context.createDynamicsCompressor();
    const gateAnalyser = this.context.createAnalyser();
    gateAnalyser.fftSize = 256;
    const gateGain = this.context.createGain();
    gateGain.gain.value = 1;
    compressor.threshold.value = 0;
    compressor.knee.value = 0;
    compressor.ratio.value = 1;
    compressor.attack.value = 0.003;
    compressor.release.value = 0.15;
    const gainNode = this.context.createGain();
    const panner = this.context.createStereoPanner ? this.context.createStereoPanner() : this.context.createPanner();
    const analyser = this.context.createAnalyser();
    analyser.fftSize = 256;
    gainNode.gain.value = muted ? 0 : gain;
    input.connect(highpass).connect(compressor).connect(gateAnalyser).connect(gateGain).connect(gainNode).connect(panner).connect(analyser);
    const channel = { input, highpass, compressor, gateAnalyser, gateGain, gateOpen: true, gate: { enabled: false, thresholdDb: -50, attenuationDb: -60 }, gainNode, panner, analyser, stream, gain, muted, pan: 0, solo: false, routes: normalizedRoutes,
      processing: { highpassHz: 20, compressorEnabled: false } };
    this.channels.set(name, channel);
    this.#applyRoutes(channel);
    return this.snapshot(name);
  }

  setGate(name, { enabled = false, thresholdDb = -50, attenuationDb = -60 } = {}) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error("Mixer channel not found.");
    this.#validateBoolean(enabled, "noise gate");
    if (!Number.isFinite(thresholdDb) || thresholdDb < -80 || thresholdDb > -20) throw new RangeError("Gate threshold must be between -80 and -20 dB.");
    if (!Number.isFinite(attenuationDb) || attenuationDb < -80 || attenuationDb > 0) throw new RangeError("Gate attenuation must be between -80 and 0 dB.");
    channel.gate = { enabled, thresholdDb, attenuationDb };
    if (!enabled) { channel.gateOpen = true; channel.gateGain.gain.setTargetAtTime(1, this.context.currentTime, 0.02); }
    return this.snapshot(name);
  }

  updateGate(name) {
    const channel = this.channels.get(name);
    if (!channel || !channel.gate.enabled) return null;
    const level = this.#measure(channel.gateAnalyser).rms;
    const db = level > 0 ? 20 * Math.log10(level) : -Infinity;
    const threshold = channel.gate.thresholdDb;
    const shouldOpen = channel.gateOpen ? db > threshold - 6 : db >= threshold;
    if (shouldOpen !== channel.gateOpen) {
      channel.gateOpen = shouldOpen;
      const gain = shouldOpen ? 1 : Math.pow(10, channel.gate.attenuationDb / 20);
      channel.gateGain.gain.setTargetAtTime(gain, this.context.currentTime, shouldOpen ? 0.012 : 0.09);
    }
    return { open: channel.gateOpen, levelDb: Number.isFinite(db) ? db : -100 };
  }

  setPan(name, pan) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error("Mixer channel not found.");
    if (!Number.isFinite(pan) || pan < -1 || pan > 1) throw new RangeError("Pan must be between -1 and 1.");
    channel.pan = pan;
    if ("pan" in channel.panner) channel.panner.pan.setTargetAtTime(pan, this.context.currentTime, 0.015);
    else channel.panner.setPosition(pan, 0, 1 - Math.abs(pan));
    return this.snapshot(name);
  }

  setSolo(name, solo) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error("Mixer channel not found.");
    this.#validateBoolean(solo, "solo");
    channel.solo = solo;
    if (solo) this.soloChannels.add(name); else this.soloChannels.delete(name);
    this.#applySoloState();
    return this.snapshot(name);
  }

  #applySoloState() {
    const hasSolo = this.soloChannels.size > 0;
    for (const [name, channel] of this.channels) {
      const silent = channel.muted || (hasSolo && !channel.solo);
      channel.gainNode.gain.setTargetAtTime(silent ? 0 : channel.gain, this.context.currentTime, 0.015);
    }
  }

  setProcessing(name, { highpassHz = 20, compressorEnabled = false } = {}) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error("Mixer channel not found.");
    if (!Number.isFinite(highpassHz) || highpassHz < 20 || highpassHz > 500) throw new RangeError("High-pass frequency must be between 20 and 500 Hz.");
    this.#validateBoolean(compressorEnabled, "compressor");
    channel.highpass.frequency.setTargetAtTime(highpassHz, this.context.currentTime, 0.02);
    channel.compressor.threshold.setTargetAtTime(compressorEnabled ? -18 : 0, this.context.currentTime, 0.02);
    channel.compressor.knee.setTargetAtTime(compressorEnabled ? 12 : 0, this.context.currentTime, 0.02);
    channel.compressor.ratio.setTargetAtTime(compressorEnabled ? 3 : 1, this.context.currentTime, 0.02);
    channel.compressor.attack.setTargetAtTime(0.006, this.context.currentTime, 0.02);
    channel.compressor.release.setTargetAtTime(0.18, this.context.currentTime, 0.02);
    channel.processing = { highpassHz, compressorEnabled };
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
    this.#applySoloState();
    return this.snapshot(name);
  }

  setMuted(name, muted) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error('Mixer channel not found.');
    this.#validateBoolean(muted, 'channel mute');
    channel.muted = muted;
    this.#applySoloState();
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

  getChannelMeter(name) {
    const channel = this.channels.get(name);
    return channel ? this.#measure(channel.analyser) : { rms: 0, peak: 0 };
  }

  getOutputMeter(name) {
    const bus = this.buses.get(name);
    return bus ? this.#measure(bus.analyser) : { rms: 0, peak: 0 };
  }

  #measure(analyser) {
    const samples = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(samples);
    let sum = 0, peak = 0;
    for (const sample of samples) {
      const value = (sample - 128) / 128;
      const absolute = Math.abs(value);
      sum += value * value;
      if (absolute > peak) peak = absolute;
    }
    const normalizedPeak = Math.min(1, peak);
    return { rms: Math.min(1, Math.sqrt(sum / samples.length)), peak: normalizedPeak, clipping: normalizedPeak >= 0.98 };
  }

  getOutputSnapshot(name) {
    const bus = this.buses.get(name);
    if (!bus) return null;
    return {
      name, gain: bus.gain, muted: bus.muted,
      streamAvailable: Boolean(bus.destination?.stream),
      playbackAttached: this.outputElements.has(name)
    };
  }

  getOutputStream(name = 'stream') {
    this.#assertOpen();
    const bus = this.buses.get(name);
    if (!bus) throw new Error('Mixer output bus not found.');
    return bus.destination.stream;
  }

  async attachOutput(name, element, { deviceId = '' } = {}) {
    this.#assertOpen();
    if (!this.buses.has(name)) throw new Error('Mixer output bus not found.');
    if (!element || typeof element !== 'object') throw new TypeError('An audio element is required.');
    const previous = this.outputElements.get(name);
    if (previous && previous !== element) this.detachOutput(name, previous);
    const stream = this.getOutputStream(name);
    element.autoplay = true;
    element.playsInline = true;
    try {
      if (element.srcObject !== stream) element.srcObject = stream;
      if (deviceId) {
        if (typeof element.setSinkId !== 'function') {
          throw new Error('Physical output selection is not supported by this runtime.');
        }
        await element.setSinkId(deviceId);
      }
      await this.resume();
      await element.play();
      this.outputElements.set(name, element);
      return {
        connected: true, bus: name,
        deviceId: typeof element.sinkId === 'string' ? element.sinkId : '',
        physicalTargetSelected: Boolean(deviceId),
        sinkSelectionSupported: typeof element.setSinkId === 'function'
      };
    } catch (error) {
      try { element.pause?.(); } catch {}
      if (element.srcObject === stream) element.srcObject = null;
      if (this.outputElements.get(name) === element) this.outputElements.delete(name);
      throw error;
    }
  }

  detachOutput(name, element = this.outputElements.get(name)) {
    if (!element || typeof element !== 'object') return false;
    try { element.pause?.(); } catch {}
    if ('srcObject' in element) element.srcObject = null;
    if (this.outputElements.get(name) === element) this.outputElements.delete(name);
    return true;
  }

  hasSolo() {
    return this.soloChannels.size > 0;
  }

  isAudibleOn(name, bus = 'stream') {
    const channel = this.channels.get(name);
    if (!channel || channel.muted || !channel.routes.includes(bus)) return false;
    return this.soloChannels.size === 0 || channel.solo === true;
  }

  snapshot(name) {
    const channel = this.channels.get(name);
    if (!channel) return null;
    return { name, gain: channel.gain, muted: channel.muted, routes: [...channel.routes], connected: true,
      processing: { ...channel.processing }, gate: { ...channel.gate }, pan: channel.pan, solo: channel.solo };
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
    try { channel.analyser.disconnect(); } catch {}
    for (const name of channel.routes) channel.analyser.connect(this.buses.get(name).gainNode);
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
      try { bus.limiter.disconnect(); } catch {}
      try { bus.analyser.disconnect(); } catch {}
      for (const track of bus.destination.stream.getTracks()) track.stop();
    }
    this.buses.clear();
    this.closed = true;
    await this.context.close();
  }

  disconnect(name) {
    const channel = this.channels.get(name);
    if (!channel) return false;
    try { channel.input.disconnect(); } catch {}
    try { channel.highpass.disconnect(); } catch {}
    try { channel.compressor.disconnect(); } catch {}
    try { channel.gateAnalyser.disconnect(); } catch {}
    try { channel.gateGain.disconnect(); } catch {}
    try { channel.gainNode.disconnect(); } catch {}
    try { channel.panner.disconnect(); } catch {}
    try { channel.analyser.disconnect(); } catch {}
    this.soloChannels.delete(name);
    this.channels.delete(name);
    this.#applySoloState();
    return true;
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { StudioAudioMixer };
if (typeof globalThis !== 'undefined') globalThis.StreamiovAudioMixer = StudioAudioMixer;
