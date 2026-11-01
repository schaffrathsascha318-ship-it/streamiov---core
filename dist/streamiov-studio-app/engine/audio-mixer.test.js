'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { StudioAudioMixer } = require('./audio-mixer');

class FakeNode {
  constructor() { this.connections = []; this.gain = { value: 1, setTargetAtTime(value) { this.value = value; } }; }
  connect(node) { this.connections.push(node); }
  disconnect() { this.connections = []; }
}
class FakeContext {
  constructor() { this.state = 'suspended'; this.currentTime = 0; this.destination = new FakeNode(); this.closed = false; this.destinations = 0; }
  createMediaStreamDestination() {
    const id = 'bus-' + (++this.destinations);
    return { stream: { id, getTracks: () => [{ stop() {} }] } };
  }
  createMediaStreamSource(stream) { const node = new FakeNode(); node.stream = stream; return node; }
  createGain() { return new FakeNode(); }
  async resume() { this.state = 'running'; }
  async close() { this.closed = true; this.state = 'closed'; }
}
const stream = { getAudioTracks: () => [{ readyState: 'live' }] };

test('creates distinct stream and monitor outputs', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  assert.notEqual(mixer.getOutputStream('stream').id, mixer.getOutputStream('monitor').id);
  assert.deepEqual(mixer.getBusNames(), ['stream', 'monitor']);
});

test('routes individual inputs to separate buses without mixing the outputs together', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  mixer.createBus('microphone_stem');
  mixer.createBus('music_stem');
  mixer.connect('microphone', stream, { gain: 0.75, routes: ['stream', 'monitor', 'microphone_stem'] });
  mixer.connect('music', stream, { gain: 0.4, routes: ['stream', 'music_stem'] });
  const mic = mixer.channels.get('microphone').gainNode;
  const music = mixer.channels.get('music').gainNode;
  assert.equal(mic.connections.length, 3);
  assert.equal(music.connections.length, 2);
  assert.equal(mixer.getOutputStream('microphone_stem').id, 'bus-3');
  assert.equal(mixer.getOutputStream('music_stem').id, 'bus-4');
  assert.deepEqual(mixer.snapshot('microphone').routes, ['stream', 'monitor', 'microphone_stem']);
});

test('routes can be changed independently per channel', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  mixer.createBus('alerts');
  mixer.connect('microphone', stream);
  mixer.setRoutes('microphone', ['monitor']);
  assert.deepEqual(mixer.snapshot('microphone').routes, ['monitor']);
  assert.equal(mixer.channels.get('microphone').gainNode.connections.length, 1);
});

test('gain and mute update the channel gain node', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  mixer.connect('microphone', stream, { gain: 0.8 });
  mixer.setMuted('microphone', true);
  assert.equal(mixer.snapshot('microphone').muted, true);
  mixer.setGain('microphone', 0.5);
  assert.equal(mixer.snapshot('microphone').gain, 0.5);
  assert.equal(mixer.channels.get('microphone').gainNode.gain.value, 0);
  mixer.setMuted('microphone', false);
  assert.equal(mixer.channels.get('microphone').gainNode.gain.value, 0.5);
});

test('rejects invalid streams, names, routes and gain values', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  assert.throws(() => mixer.connect('bad name', stream), /channel name/i);
  assert.throws(() => mixer.connect('music', { getAudioTracks: () => [] }), /audio track/i);
  assert.throws(() => mixer.connect('music', stream, { gain: 3 }), /gain/i);
  assert.throws(() => mixer.connect('music', stream, { routes: ['missing_bus'] }), /bus not found/i);
  assert.throws(() => mixer.setRoutes('missing', ['stream']), /channel not found/i);
});

test('disconnect and close release graph nodes and prevent reuse', async () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  mixer.connect('microphone', stream);
  assert.equal(mixer.disconnect('microphone'), true);
  assert.equal(mixer.disconnect('microphone'), false);
  await mixer.close();
  assert.throws(() => mixer.getOutputStream(), /closed/i);
  assert.equal(mixer.context.closed, true);
  assert.throws(() => mixer.getBusNames(), /closed/i);
});
