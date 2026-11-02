'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { StudioAudioMixer } = require('./audio-mixer');

class FakeNode {
  constructor() {
    this.connections = [];
    this.gain = { value: 1, setTargetAtTime(value) { this.value = value; } };
  }
  connect(node) { this.connections.push(node); }
  disconnect() { this.connections = []; }
}
class FakeContext {
  constructor() {
    this.state = 'suspended';
    this.currentTime = 0;
    this.destination = new FakeNode();
    this.closed = false;
    this.destinations = 0;
  }
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

test('creates four distinct logical output streams', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  assert.deepEqual(mixer.getBusNames(), ['stream', 'monitor', 'headphones', 'communications']);
  const ids = mixer.getBusNames().map(name => mixer.getOutputStream(name).id);
  assert.equal(new Set(ids).size, 4);
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
  assert.equal(mixer.getOutputStream('microphone_stem').id, 'bus-5');
  assert.equal(mixer.getOutputStream('music_stem').id, 'bus-6');
  assert.deepEqual(mixer.snapshot('microphone').routes, ['stream', 'monitor', 'microphone_stem']);
});

test('routes can be changed independently per channel, including routing to silence', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  mixer.connect('microphone', stream);
  mixer.connect('music', stream, { routes: ['monitor'] });
  mixer.setRoutes('microphone', ['headphones']);
  mixer.setRoutes('music', []);
  assert.deepEqual(mixer.snapshot('microphone').routes, ['headphones']);
  assert.deepEqual(mixer.snapshot('music').routes, []);
  assert.equal(mixer.channels.get('microphone').gainNode.connections.length, 1);
  assert.equal(mixer.channels.get('music').gainNode.connections.length, 0);
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

test('output gain and mute are isolated to their own output bus', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  mixer.connect('microphone', stream, { routes: ['stream', 'monitor', 'headphones'] });
  const streamBus = mixer.buses.get('stream');
  const monitorBus = mixer.buses.get('monitor');
  const headphonesBus = mixer.buses.get('headphones');
  mixer.setOutputMuted('monitor', true);
  mixer.setOutputGain('headphones', 0.35);
  assert.equal(monitorBus.gainNode.gain.value, 0);
  assert.equal(headphonesBus.gainNode.gain.value, 0.35);
  assert.equal(streamBus.gainNode.gain.value, 1);
  assert.equal(mixer.getOutputSnapshot('monitor').muted, true);
  assert.equal(mixer.getOutputSnapshot('headphones').gain, 0.35);
  mixer.setOutputMuted('monitor', false);
  assert.equal(monitorBus.gainNode.gain.value, 1);
  assert.equal(streamBus.gainNode.gain.value, 1);
});

test('rejects invalid streams, names, routes, gain values and non-boolean mute values', () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  assert.throws(() => mixer.connect('bad name', stream), /channel name/i);
  assert.throws(() => mixer.connect('music', { getAudioTracks: () => [] }), /audio track/i);
  assert.throws(() => mixer.connect('music', stream, { gain: 3 }), /gain/i);
  assert.throws(() => mixer.connect('music', stream, { muted: 1 }), /boolean/i);
  assert.throws(() => mixer.connect('music', stream, { routes: ['missing_bus'] }), /bus not found/i);
  assert.throws(() => mixer.setRoutes('missing', ['stream']), /channel not found/i);
  mixer.connect('music', stream);
  assert.throws(() => mixer.setMuted('music', 0), /boolean/i);
  assert.throws(() => mixer.setOutputMuted('stream', 'false'), /boolean/i);
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

test('monitor output attaches to a selected physical device and detaches cleanly', async () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  const calls = [];
  const element = {
    autoplay: false, playsInline: false, srcObject: null, sinkId: 'default',
    setSinkId: async id => { calls.push(['sink', id]); element.sinkId = id; },
    play: async () => calls.push(['play']),
    pause: () => calls.push(['pause'])
  };
  const result = await mixer.attachMonitor(element, { deviceId: 'headphones-1' });
  assert.equal(result.connected, true);
  assert.equal(result.deviceId, 'headphones-1');
  assert.equal(result.bus, 'monitor');
  assert.equal(result.physicalTargetSelected, true);
  assert.equal(element.srcObject, mixer.getOutputStream('monitor'));
  assert.equal(element.autoplay, true);
  assert.ok(calls.some(call => call[0] === 'sink' && call[1] === 'headphones-1'));
  assert.equal(mixer.detachMonitor(element), true);
  assert.equal(element.srcObject, null);
  assert.ok(calls.some(call => call[0] === 'pause'));
});

test('headphones and communications buses can attach independently', async () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  const makeElement = () => ({
    srcObject: null, play: async () => {}, pause() {}, sinkId: 'default',
    setSinkId: async function (id) { this.sinkId = id; }
  });
  const headphones = makeElement();
  const communications = makeElement();
  const [h, c] = await Promise.all([
    mixer.attachOutput('headphones', headphones),
    mixer.attachOutput('communications', communications)
  ]);
  assert.equal(h.bus, 'headphones');
  assert.equal(c.bus, 'communications');
  assert.notEqual(headphones.srcObject, communications.srcObject);
  assert.equal(mixer.getOutputSnapshot('headphones').playbackAttached, true);
  assert.equal(mixer.getOutputSnapshot('communications').playbackAttached, true);
});

test('failed output attachment cleans up the untracked media stream', async () => {
  const mixer = new StudioAudioMixer({ AudioContextClass: FakeContext });
  const element = {
    srcObject: null,
    pause() { this.paused = true; },
    play: async () => { throw new Error('playback denied'); }
  };
  await assert.rejects(mixer.attachOutput('headphones', element), /playback denied/);
  assert.equal(element.srcObject, null);
  assert.equal(element.paused, true);
  assert.equal(mixer.getOutputSnapshot('headphones').playbackAttached, false);
});
