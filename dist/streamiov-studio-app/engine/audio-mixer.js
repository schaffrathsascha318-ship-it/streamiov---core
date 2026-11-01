'use strict';

/**
 * Local Web Audio mixer for real MediaStream inputs.
 * The returned destination stream is ready for a future encoder adapter;
 * this module does not publish or transmit audio itself.
 */
class StudioAudioMixer {
  constructor({ AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext } = {}) {
    if (typeof AudioContextClass !== 'function') throw new Error('Web Audio is not available.');
    this.context = new AudioContextClass();
    this.destination = this.context.createMediaStreamDestination();
    this.channels = new Map();
    this.closed = false;
  }

  async resume() {
    this.#assertOpen();
    if (this.context.state === 'suspended') await this.context.resume();
  }

  connect(name, stream, { gain = 1, muted = false } = {}) {
    this.#assertOpen();
    if (typeof name !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/i.test(name)) {
      throw new TypeError('Invalid mixer channel name.');
    }
    if (!stream || typeof stream.getAudioTracks !== 'function' || stream.getAudioTracks().length === 0) {
      throw new TypeError('A MediaStream with at least one audio track is required.');
    }
    if (!Number.isFinite(gain) || gain < 0 || gain > 2) throw new RangeError('Gain must be between 0 and 2.');
    this.disconnect(name);
    const input = this.context.createMediaStreamSource(stream);
    const gainNode = this.context.createGain();
    gainNode.gain.value = muted ? 0 : gain;
    input.connect(gainNode);
    gainNode.connect(this.destination);
    this.channels.set(name, { input, gainNode, stream, gain: muted ? 0 : gain, muted: muted === true });
    return this.snapshot(name);
  }

  setGain(name, gain) {
    this.#assertOpen();
    const channel = this.channels.get(name);
    if (!channel) throw new Error('Mixer channel not found.');
    if (!Number.isFinite(gain) || gain < 0 || gain > 2) throw new RangeError('Gain must be between 0 and 2.');
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

  getOutputStream() {
    this.#assertOpen();
    return this.destination.stream;
  }

  snapshot(name) {
    const channel = this.channels.get(name);
    if (!channel) return null;
    return { name, gain: channel.gain, muted: channel.muted, connected: true };
  }

  #assertOpen() {
    if (this.closed) throw new Error('Audio mixer is closed.');
  }

  async close() {
    if (this.closed) return;
    for (const name of [...this.channels.keys()]) this.disconnect(name);
    this.closed = true;
    await this.context.close();
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { StudioAudioMixer };
if (typeof globalThis !== 'undefined') globalThis.StreamiovAudioMixer = StudioAudioMixer;
