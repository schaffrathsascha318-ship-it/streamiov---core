'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { listRunningProcesses, parsePosix, parseWindows } = require('./game-process-detector');

test('POSIX process output becomes sanitized analysis candidates', () => {
  const rows = parsePosix('123 streamiov-neon /opt/games/neon --fullscreen\n456 system /usr/lib/systemd --quiet\n');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].processName, 'streamiov-neon');
  assert.equal(rows[0].confidence, 'possible');
  assert.equal(rows[1].confidence, 'unconfirmed');
  assert.equal(rows[0].windowTitle, '');
});

test('Windows tasklist CSV output is parsed without shell commands', () => {
  const rows = parseWindows('"Image Name","PID","Session Name","Session#","Mem Usage"\r\n"Neon Relay.exe","1234","Console","1","80,000 K"\r\n');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].processName, 'Neon Relay');
  assert.equal(rows[0].likelyGame, true);
});

test('Windows no-header tasklist output keeps the first process', () => {
  const rows = parseWindows('"Neon Relay.exe","1234","Console","1","80,000 K"\r\n"explorer.exe","55","Console","1","20,000 K"\r\n');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].processName, 'Neon Relay');
  assert.equal(rows[0].likelyGame, true);
});

test('process reading uses injected command runner and fails closed', async () => {
  const processes = await listRunningProcesses({
    platform: 'linux',
    run: async () => ({ stdout: '7 minecraft /usr/bin/minecraft\n' }),
  });
  assert.equal(processes.length, 1);
  assert.equal(processes[0].processName, 'minecraft');
  const failed = await listRunningProcesses({
    platform: 'linux',
    run: async () => { throw new Error('ps missing'); },
  });
  assert.deepEqual(failed, []);
});
