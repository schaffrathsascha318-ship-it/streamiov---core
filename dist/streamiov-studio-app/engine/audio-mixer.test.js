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
  constructor() { this.state = 'suspended'; this.currentTime = 0; this.destination = new FakeNode(); this.closed = false; }
  createMediaStreamDestination() { return { ...new FakeNode(), stream: { id: 'mixed-output' } }; }
  createMediaStreamSource(stream) { const node = new FakeNode(); node.stream = stream; return node; }
  createGain() { return new FakeNode(); }
  async resume() { this.state = 'running'; }
  async close() { this.closed = true; this.state = 'closed'; }
}
const stream = { getAudioTracks: () => [{ readyState: 'live' }] };

test('mixes multiple real audio streams into one output stream', async () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  await mixer.resume();
  mixer.connect('microphone', stream, { gain: 0.75 });
  mixer.connect('music', stream, { gain: 0.4 });
  assert.equal(mixer.getOutputStream().id, 'mixed-output');
  assert.equal(mixer.snapshot('microphone').gain, 0.75);
  assert.equal(mixer.snapshot('music').connected, true);
  await mixer.close();
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

test('rejects invalid streams, names and gain values', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  assert.throws(() => mixer.connect('bad name', stream), /channel name/i);
  assert.throws(() => mixer.connect('music', { getAudioTracks: () => [] }), /audio track/i);
  assert.throws(() => mixer.connect('music', stream, { gain: 3 }), /gain/i);
});

test('disconnect and close release graph nodes and prevent reuse', async () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  mixer.connect('microphone', stream);
  assert.equal(mixer.disconnect('microphone'), true);
  assert.equal(mixer.disconnect('microphone'), false);
  await mixer.close();
  assert.throws(() => mixer.getOutputStream(), /closed/i);
  assert.equal(mixer.context.closed, true);
});
