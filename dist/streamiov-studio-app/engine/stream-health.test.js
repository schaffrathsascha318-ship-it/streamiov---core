'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { StreamHealth } = require('./stream-health');
const { LiveOutputManager } = require('./live-output-manager');

class FakeChild extends EventEmitter {
  constructor() {
    super();
    this.stdin = new EventEmitter();
    this.stdin.destroyed = false;
    this.stdin.writableLength = 0;
    this.stdin.write = (chunk, callback) => { if (callback) callback(); };
    this.stdin.end = () => {};
    this.stderr = new EventEmitter();
    this.exitCode = null;
    this.signalCode = null;
  }
  kill() {}
}

function clock(start = 1000) {
  let now = start;
  return { now: () => now, advance: ms => { now += ms; } };
}

test('health records real writes and estimates a local bitrate', () => {
  const time = clock();
  const health = new StreamHealth({ clock: time.now });
  assert.equal(health.recordWrite('twitch', 1000, time.now()), 'healthy');
  time.advance(100);
  health.recordWrite('twitch', 1000, time.now());
  const snapshot = health.snapshot('twitch', time.now());
  assert.equal(snapshot.chunks, 2);
  assert.equal(snapshot.bytes, 2000);
  assert.equal(snapshot.status, 'healthy');
  assert.equal(snapshot.kbps, 16);
  assert.equal(snapshot.uptimeMs, 100);
  assert.equal(snapshot.lastWriteAt, 1100);
});

test('health degrades on bounded backpressure failures and recovers on writes', () => {
  const time = clock();
  const events = [];
  const health = new StreamHealth({ clock: time.now, onEvent: (platform, status) => events.push([platform, status]) });
  health.recordWrite('twitch', 100, time.now());
  health.recordFailure('twitch', 'Encoder zu langsam', time.now());
  health.recordFailure('twitch', 'Encoder zu langsam', time.now());
  assert.equal(health.recordFailure('twitch', 'Encoder zu langsam', time.now()), 'degraded');
  health.recordRetry('twitch', 1, 'Verbindung unterbrochen', time.now());
  assert.equal(health.snapshot('twitch', time.now()).retries, 1);
  assert.match(health.snapshot('twitch', time.now()).lastReason, /Verbindung unterbrochen/);
  assert.equal(health.recordWrite('twitch', 100, time.now()), 'healthy');
  assert.equal(health.snapshot('twitch', time.now()).status, 'healthy');
  assert.deepEqual(events, [['twitch', 'healthy'], ['twitch', 'degraded'], ['twitch', 'healthy']]);
  assert.equal(health.entries.get('twitch').events.length, 0);
});

test('health marks a silent output as stalled and a stopped output offline', () => {
  const time = clock();
  const health = new StreamHealth({ clock: time.now, stallMs: 1000 });
  health.recordWrite('tiktok', 500, time.now());
  time.advance(1001);
  assert.equal(health.snapshot('tiktok', time.now()).status, 'stalled');
  assert.equal(health.stop('tiktok', time.now()).status, 'offline');
  assert.equal(health.snapshot('tiktok', time.now()).status, 'offline');
  health.reset('tiktok');
  assert.equal(health.snapshot('tiktok', time.now()).chunks, 0);
});

test('health rejects invalid input and bounds its sample history', () => {
  const time = clock();
  const health = new StreamHealth({ clock: time.now });
  assert.throws(() => new StreamHealth({ clock: time.now, windowMs: 10 }), /Telemetriefenster/);
  assert.throws(() => new StreamHealth({ clock: time.now, failureThreshold: 0 }), /Fehlergrenze/);
  assert.throws(() => health.recordWrite('twitch', -1, time.now()), /Medienblockgröße/);
  assert.throws(() => health.recordWrite('../evil', 1, time.now()), /Ungültige Plattform/);
  for (let index = 0; index < 200; index += 1) health.recordWrite('twitch', 10, time.now());
  assert.ok(health.entries.get('twitch').samples.length <= 120);
  assert.equal(health.entries.get('twitch').chunks, 200);
});

test('live output manager exposes health from actual encoder writes', async () => {
  const children = [];
  const healthEvents = [];
  const manager = new LiveOutputManager({
    spawnImpl: () => { const child = new FakeChild(); children.push(child); return child; },
    setTimeoutImpl: (fn, ms) => ({ fn, ms, unref() { return this; } }),
    clearTimeoutImpl: () => {},
    onHealthEvent: (platform, status) => healthEvents.push([platform, status])
  });
  assert.equal(manager.start({ platform: 'twitch', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://twitch/key' }).ok, true);
  await manager.write(Buffer.from([1, 2, 3, 4]));
  const snapshot = manager.snapshot().twitch;
  assert.equal(snapshot.health.status, 'healthy');
  assert.equal(snapshot.health.bytes, 4);
  assert.equal(snapshot.health.chunks, 1);
  assert.equal(manager.healthSnapshot().twitch.bytes, 4);
  assert.deepEqual(healthEvents, [['twitch', 'healthy']]);
  const stopping = manager.stop('twitch');
  children[0].emit('close', 0, 'SIGINT');
  await stopping;
  assert.equal(manager.healthSnapshot().twitch.status, 'offline');
});

test('live output manager records backpressure failures per platform', async () => {
  const manager = new LiveOutputManager({
    spawnImpl: () => {
      const child = new FakeChild();
      child.stdin.destroyed = true;
      return child;
    }
  });
  manager.start({ platform: 'tiktok', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://tiktok/key' });
  const result = await manager.write(Buffer.from([1]));
  assert.equal(result.ok, false);
  const health = manager.healthSnapshot().tiktok;
  assert.equal(health.failures, 1);
  assert.equal(health.status, 'waiting');
  assert.match(health.lastReason, /nicht schnell genug/);
});
