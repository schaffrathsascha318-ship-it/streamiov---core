'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { StudioAudioMixer } = require('./audio-mixer');

class FakeParam {
  constructor(value = 0) {
    this.value = value;
  }
  setTargetAtTime(value) {
    this.value = value;
  }
}

class FakeNode {
  connect(target) {
    return target;
  }
  disconnect() {}
}

class FakeAudioContext {
  constructor() {
    this.currentTime = 0;
    this.state = 'running';
  }
  createGain() {
    return Object.assign(new FakeNode(), { gain: new FakeParam(1) });
  }
  createBiquadFilter() {
    return Object.assign(new FakeNode(), { frequency: new FakeParam(20) });
  }
  createDynamicsCompressor() {
    return Object.assign(new FakeNode(), {
      threshold: new FakeParam(0), knee: new FakeParam(0), ratio: new FakeParam(1),
      attack: new FakeParam(0), release: new FakeParam(0)
    });
  }
  createAnalyser() {
    return Object.assign(new FakeNode(), {
      fftSize: 256,
      getByteTimeDomainData(samples) { samples.fill(128); }
    });
  }
  createMediaStreamDestination() {
    return { stream: { getAudioTracks: () => [], getTracks: () => [] } };
  }
  createMediaStreamSource() {
    return new FakeNode();
  }
  createStereoPanner() {
    return Object.assign(new FakeNode(), { pan: new FakeParam(0) });
  }
  async resume() {}
  async close() {}
}

function audioStream() {
  return { getAudioTracks: () => [{ readyState: 'live', addEventListener() {} }] };
}

test('mixer connects channels with bounded gain and explicit routes', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeAudioContext });
  const snapshot = mixer.connect('camera-source', audioStream(), { gain: 0.75, routes: ['stream', 'stream', 'monitor'] });
  assert.deepEqual(snapshot, {
    name: 'camera-source', gain: 0.75, muted: false, routes: ['stream', 'monitor'], connected: true,
    processing: { highpassHz: 20, compressorEnabled: false },
    gate: { enabled: false, thresholdDb: -50, attenuationDb: -60 },
    pan: 0, solo: false
  });
  assert.equal(mixer.channels.get('camera-source').gainNode.gain.value, 0.75);
  assert.throws(() => mixer.connect('bad-gain', audioStream(), { gain: 3 }), /Gain must be between 0 and 2/);
});

test('mixer mute, solo and routes affect what reaches the stream bus', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeAudioContext });
  mixer.connect('program-source', audioStream(), { routes: ['stream'] });
  mixer.connect('preview-source', audioStream(), { routes: ['stream'] });
  mixer.setSolo('program-source', true);
  assert.equal(mixer.hasSolo(), true);
  assert.equal(mixer.channels.get('preview-source').gainNode.gain.value, 0);
  assert.equal(mixer.snapshot('program-source').solo, true);
  assert.equal(mixer.isAudibleOn('program-source'), true);
  assert.equal(mixer.isAudibleOn('preview-source'), false);
  mixer.setSolo('program-source', false);
  mixer.setMuted('program-source', true);
  assert.equal(mixer.channels.get('program-source').gainNode.gain.value, 0);
  mixer.setMuted('program-source', false);
  mixer.setRoutes('program-source', ['monitor']);
  assert.deepEqual(mixer.snapshot('program-source').routes, ['monitor']);
  assert.equal(mixer.isAudibleOn('program-source'), false);
  assert.equal(mixer.isAudibleOn('program-source', 'monitor'), true);
  mixer.setGain('program-source', 1.5);
  mixer.setPan('program-source', -0.5);
  assert.equal(mixer.channels.get('program-source').gainNode.gain.value, 1.5);
  assert.equal(mixer.snapshot('program-source').pan, -0.5);
  assert.equal(mixer.disconnect('program-source'), true);
  assert.equal(mixer.hasSolo(), false);
  assert.equal(mixer.snapshot('program-source'), null);
});

test('mixer rejects invalid channels and unknown output routes', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeAudioContext });
  assert.throws(() => mixer.connect('no-track', { getAudioTracks: () => [] }), /at least one audio track/);
  assert.throws(() => mixer.connect('bad name', audioStream()), /Invalid mixer channel name/);
  assert.throws(() => mixer.connect('bad-route', audioStream(), { routes: ['broadcast'] }), /Mixer output bus not found/);
  assert.equal(mixer.channels.has('no-track'), false);
  assert.equal(mixer.channels.has('bad name'), false);
  assert.equal(mixer.channels.has('bad-route'), false);
});

test('mixer gate validates bounds and reopens when disabled', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeAudioContext });
  mixer.connect('microphone', audioStream());
  assert.throws(() => mixer.setGate('microphone', { thresholdDb: -10 }), /Gate threshold/);
  assert.throws(() => mixer.setGate('microphone', { attenuationDb: 10 }), /Gate attenuation/);
  const gated = mixer.setGate('microphone', { enabled: true, thresholdDb: -40, attenuationDb: -60 });
  assert.deepEqual(gated.gate, { enabled: true, thresholdDb: -40, attenuationDb: -60 });
  assert.equal(mixer.updateGate('microphone').open, false);
  assert.equal(mixer.channels.get('microphone').gateGain.gain.value, Math.pow(10, -3));
  assert.equal(mixer.setGate('microphone', { enabled: false }).gate.enabled, false);
  assert.equal(mixer.channels.get('microphone').gateGain.gain.value, 1);
});

test('mixer output gain and mute remain independent from channel gain', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeAudioContext });
  mixer.connect('camera-source', audioStream(), { gain: 0.8, routes: ['monitor'] });
  assert.equal(mixer.setOutputGain('monitor', 0.5).gain, 0.5);
  assert.equal(mixer.setOutputMuted('monitor', true).muted, true);
  assert.deepEqual(mixer.getOutputSnapshot('monitor'), {
    name: 'monitor', gain: 0.5, muted: true, streamAvailable: true, playbackAttached: false
  });
  assert.equal(mixer.snapshot('camera-source').gain, 0.8);
  assert.equal(mixer.snapshot('camera-source').muted, false);
  assert.throws(() => mixer.setOutputGain('missing', 1), /Mixer output bus not found/);
});

test('mixer attachOutput clears a failed physical playback attempt', async () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeAudioContext });
  const element = {
    sinkId: '',
    async setSinkId(deviceId) { this.sinkId = deviceId; },
    async play() { throw new Error('play blocked'); },
    pause() {}
  };
  await assert.rejects(mixer.attachOutput('monitor', element, { deviceId: 'speaker-1' }), /play blocked/);
  assert.equal(element.srcObject, null);
  assert.equal(mixer.outputElements.has('monitor'), false);
  assert.equal(mixer.getOutputSnapshot('monitor').playbackAttached, false);
});

test('mixer close disconnects channels and rejects later use', async () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeAudioContext });
  mixer.connect('camera-source', audioStream());
  await mixer.close();
  assert.equal(mixer.snapshot('camera-source'), null);
  assert.throws(() => mixer.connect('camera-source', audioStream()), /Audio mixer is closed/);
  assert.throws(() => mixer.getOutputStream('stream'), /Audio mixer is closed/);
  await mixer.close();
});
