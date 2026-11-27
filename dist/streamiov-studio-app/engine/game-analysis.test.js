'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { GameAnalysis } = require('./game-analysis');

function fixture(now) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-analysis-'));
  return {
    directory,
    analysis: new GameAnalysis({ filePath: path.join(directory, 'analysis.json'), now: () => now }),
  };
}

test('detection only registers reported processes and never launches a game', () => {
  const { directory, analysis } = fixture(1000);
  const snapshot = analysis.detect([
    { processName: 'Neon Relay.exe', windowTitle: 'Neon Relay', source: 'streamiov' },
    { processName: 'external-game', windowTitle: 'External Game' },
  ]);
  assert.equal(snapshot.games.length, 2);
  assert.equal(snapshot.games[0].source, 'streamiov');
  assert.equal(snapshot.games[1].source, 'external');
  assert.equal(snapshot.games[0].status, 'NEEDS_REVIEW');
  assert.equal(snapshot.games[0].session.active, false);
  fs.rmSync(directory, { recursive: true, force: true });
});

test('observations create highlights, replay markers and deterministic local advice', () => {
  const { directory, analysis } = fixture(1000);
  analysis.detect([{ processName: 'Arena', source: 'external' }]);
  analysis.startSession('arena');
  analysis.observe({ id: 'arena', kind: 'kill', detail: ' Gegner ausgeschaltet ' });
  analysis.observe({ id: 'arena', kind: 'death', detail: 'Kern verloren' });
  analysis.observe({ id: 'arena', kind: 'death', detail: 'Zweiter Rückzug' });
  analysis.observe({ id: 'arena', kind: 'objective', detail: 'Punkt erobert' });
  const result = analysis.observe({ id: 'arena', kind: 'victory', detail: 'Runde gewonnen' });
  assert.equal(result.observation.highlight, true);
  assert.equal(result.snapshot.games[0].highlights.length, 3);
  assert.equal(result.snapshot.games[0].replayMarkers.length, 3);
  assert.equal(result.snapshot.games[0].stats.kills, 1);
  assert.equal(result.snapshot.games[0].stats.deaths, 2);
  assert.equal(result.snapshot.games[0].stats.objectives, 1);
  const advice = analysis.assistant('arena');
  assert.match(advice.advice.detail, /Positionen und Rückzugswege/);
  assert.equal(advice.snapshot.games[0].advice.length, 1);
  analysis.stopSession('arena');
  assert.equal(analysis.replay('arena').markers.length, 3);
  fs.rmSync(directory, { recursive: true, force: true });
});

test('analysis state is persisted with private permissions and rejects unknown observations', () => {
  const { directory, analysis } = fixture(1000);
  analysis.detect([{ processName: 'Puzzle', source: 'external' }]);
  analysis.observe({ id: 'puzzle', kind: 'combo', detail: 'Vier Züge' });
  const restored = new GameAnalysis({ filePath: path.join(directory, 'analysis.json'), now: () => 2000 });
  assert.equal(restored.snapshot().games[0].stats.combos, 1);
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(path.join(directory, 'analysis.json')).mode & 0o777, 0o600);
  }
  assert.throws(() => restored.observe({ id: 'puzzle', kind: 'launch' }), /Unbekannte Gameplay-Beobachtung/);
  fs.rmSync(directory, { recursive: true, force: true });
});

test('repeated persistence ignores stale temporary files', () => {
  const { directory, analysis } = fixture(1000);
  const staleName = 'analysis.json.' + process.pid + '.tmp';
  fs.writeFileSync(path.join(directory, staleName), 'stale');
  analysis.detect([{ processName: 'Arena', likelyGame: true }]);
  analysis.profile('arena', { notes: 'first' });
  analysis.profile('arena', { notes: 'second' });
  assert.deepEqual(fs.readdirSync(directory).filter(name => name.endsWith('.tmp')), [staleName]);
  assert.equal(new GameAnalysis({ filePath: path.join(directory, 'analysis.json') }).snapshot().games[0].profile.notes, 'second');
  fs.rmSync(directory, { recursive: true, force: true });
});

function frame(red, green, blue) {
  const width = 16;
  const height = 9;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let index = 0; index < width * height; index += 1) {
    data[index * 4] = red;
    data[index * 4 + 1] = green;
    data[index * 4 + 2] = blue;
    data[index * 4 + 3] = 255;
  }
  return { width, height, data: data.buffer };
}

test('automatic detection registers only likely games and keeps the setting private', () => {
  const { directory, analysis } = fixture(1000);
  analysis.setAutoDetection({ enabled: true, intervalMs: 5000 });
  const snapshot = analysis.detect([
    { processName: 'Neon Relay.exe', likelyGame: true, confidenceScore: 0.92, streamiovGame: true },
    { processName: 'browser', likelyGame: false, confidenceScore: 0.12 },
  ], { automatic: true });
  assert.equal(snapshot.games.length, 1);
  assert.equal(snapshot.games[0].source, 'streamiov');
  assert.equal(snapshot.games[0].detection, 'process_list_auto');
  const restored = new GameAnalysis({ filePath: path.join(directory, 'analysis.json'), now: () => 2000 });
  assert.equal(restored.snapshot().autoDetection.enabled, true);
  assert.equal(restored.snapshot().autoDetection.intervalMs, 5000);
  fs.rmSync(directory, { recursive: true, force: true });
});

test('frames create situations, performance statistics and progress without storing images', () => {
  const { directory, analysis } = fixture(1000);
  analysis.detect([{ processName: 'Arena', likelyGame: true }]);
  analysis.startSession('arena');
  const first = analysis.frame({ id: 'arena', ...frame(20, 20, 20) });
  const second = analysis.frame({ id: 'arena', ...frame(230, 230, 230) });
  assert.equal(second.snapshot.games[0].stats.frameAnalyses, 2);
  assert.equal(second.analysis.situation, 'szenenwechsel');
  assert.equal(analysis.situations('arena').situations.length, 2);
  const stats = analysis.stats('arena');
  assert.equal(stats.frameCount, 2);
  assert.equal(stats.situationCounts.szenenwechsel, 1);
  assert.ok(second.snapshot.games[0].progress.totalXp >= 2);
  assert.ok(!fs.readFileSync(path.join(directory, 'analysis.json'), 'utf8').includes('Uint8'));
  fs.rmSync(directory, { recursive: true, force: true });
});

test('profiles, voice commands, strategy and replay analysis stay local and persisted', () => {
  const { directory, analysis } = fixture(1000);
  analysis.detect([{ processName: 'Arena', likelyGame: true }]);
  const profile = analysis.profile('arena', { notes: 'Rückzug üben', goals: ['10 Ziele'], visionSensitivity: 60 });
  assert.deepEqual(profile.profile.goals, ['10 Ziele']);
  const voice = analysis.voice('arena', 'ziel mehr objectives');
  assert.equal(voice.intent, 'goal');
  assert.deepEqual(voice.snapshot.games[0].profile.goals, ['10 Ziele', 'mehr objectives']);
  analysis.observe({ id: 'arena', kind: 'victory', reactionMs: 420 });
  const strategy = analysis.strategy('arena');
  assert.ok(strategy.recommendations.length >= 1);
  assert.equal(strategy.advice.kind, 'strategy');
  assert.ok(strategy.snapshot.games[0].advice.length >= 2);
  const replay = analysis.replayImport({
    id: 'arena', name: 'runde.webm', durationMs: 6000, sizeBytes: 4096,
    frames: [frame(20, 20, 20), frame(220, 20, 20), frame(40, 220, 40)],
  });
  assert.equal(replay.analysis.frames, 3);
  assert.ok(replay.snapshot.games[0].replays.length === 1);
  assert.equal(analysis.replay('arena').analyses.length, 1);
  const restored = new GameAnalysis({ filePath: path.join(directory, 'analysis.json'), now: () => 2000 });
  assert.equal(restored.snapshot().games[0].profile.notes, 'Rückzug üben');
  fs.rmSync(directory, { recursive: true, force: true });
});
