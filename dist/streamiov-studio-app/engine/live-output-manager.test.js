'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { LiveOutputManager } = require('./live-output-manager');

class FakeChild extends EventEmitter {
  constructor() {
    super();
    this.writes = [];
    this.ended = false;
    this.exitCode = null;
    this.signalCode = null;
    this.stdin = new EventEmitter();
    this.stdin.destroyed = false;
    this.stdin.writableLength = 0;
    this.stdin.write = (chunk, callback) => { this.writes.push(Buffer.from(chunk)); if (callback) callback(); };
    this.stdin.end = () => { this.ended = true; };
    this.stderr = new EventEmitter();
  }
  kill() {
    this.signalCode = 'SIGINT';
  }
}

function harness() {
  const children = [];
  const timers = [];
  const events = [];
  const spawnImpl = () => {
    const child = new FakeChild();
    children.push(child);
    return child;
  };
  const manager = new LiveOutputManager({
    spawnImpl,
    setTimeoutImpl: (fn, ms) => {
      const timer = { fn, ms, cancelled: false, unref() { return this; } };
      timers.push(timer);
      return timer;
    },
    clearTimeoutImpl: timer => { if (timer) timer.cancelled = true; },
    onEvent: (platform, event, payload) => events.push({ platform, event, ...payload })
  });
  return { manager, children, timers, events };
}

test('keeps separate FFmpeg processes and destinations for each platform', () => {
  const { manager, children } = harness();
  assert.equal(manager.start({ platform: 'twitch', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://twitch/key' }).ok, true);
  assert.equal(manager.start({ platform: 'tiktok', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://tiktok/key' }).ok, true);
  assert.equal(children.length, 2);
  assert.notEqual(children[0], children[1]);
  assert.deepEqual(manager.activePlatforms(), ['twitch', 'tiktok']);
});

test('reports output readiness without claiming remote LIVE', () => {
  const { manager, children, events } = harness();
  manager.start({ platform: 'twitch', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://twitch/key' });
  children[0].emit('spawn');
  children[0].stderr.emit('data', Buffer.from('Output #0, flv to rtmps://hidden'));
  assert.ok(events.some(item => item.platform === 'twitch' && item.event === 'connecting'));
  assert.ok(events.some(item => item.platform === 'twitch' && item.event === 'output_ready'));
  assert.ok(!events.some(item => item.event === 'live'));
});

test('fans media chunks out to every active platform', async () => {
  const { manager, children } = harness();
  manager.start({ platform: 'twitch', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://twitch/key' });
  manager.start({ platform: 'tiktok', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://tiktok/key' });
  const result = await manager.write(Buffer.from([1, 2, 3]));
  assert.deepEqual(result, { ok: true, written: 2 });
  assert.equal(children[0].writes.length, 1);
  assert.equal(children[1].writes.length, 1);
});

test('reconnects an interrupted output with backoff and stops permanently after retries', () => {
  const { manager, children, timers, events } = harness();
  manager.start({ platform: 'twitch', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://twitch/key' });
  children[0].emit('close');
  timers[0].fn();
  assert.ok(events.some(item => item.event === 'reconnecting' && item.attempt === 1));
  children[1].emit('close');
  timers[1].fn();
  children[2].emit('close');
  timers[2].fn();
  children[3].emit('close');
  assert.ok(events.some(item => item.event === 'reconnecting' && item.attempt === 3));
  assert.ok(events.some(item => item.event === 'error' && item.attempt === 3));
  assert.deepEqual(manager.activePlatforms(), []);
});

test('keeps a reconnecting output visible and stoppable before the retry timer fires', async () => {
  const { manager, children, timers } = harness();
  manager.start({ platform: 'twitch', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://twitch/key' });
  children[0].emit('close');
  assert.deepEqual(manager.activePlatforms(), ['twitch']);
  assert.equal(manager.snapshot().twitch.retrying, true);
  assert.equal((await manager.write(Buffer.from([1]))).ok, false);
  const result = await manager.stop('twitch');
  assert.equal(result.ok, true);
  assert.equal(result.stopped, false);
  assert.equal(timers[0].cancelled, true);
  assert.deepEqual(manager.activePlatforms(), []);
});

test('stops cleanly and reports offline', async () => {
  const { manager, children, events } = harness();
  manager.start({ platform: 'twitch', executable: 'ffmpeg', args: ['-i', 'pipe:0'], destination: 'rtmps://twitch/key' });
  const stopping = manager.stop('twitch');
  children[0].emit('close', 0, 'SIGINT');
  const result = await stopping;
  assert.equal(result.ok, true);
  assert.equal(children[0].ended, true);
  assert.ok(events.some(item => item.event === 'offline'));
});
