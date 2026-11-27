'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appRoot = path.resolve(__dirname, '..');
const main = fs.readFileSync(require.resolve('../main.js'), 'utf8');
const preload = fs.readFileSync(require.resolve('../preload.js'), 'utf8');
const ui = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');
const packageJson = JSON.parse(fs.readFileSync(path.join(appRoot, 'package.json'), 'utf8'));

test('Studio exposes only narrow game analysis IPC', () => {
  assert.match(main, /studio:game-analysis/);
  assert.doesNotMatch(main, /studio:list-games/);
  assert.doesNotMatch(main, /studio:open-game/);
  assert.match(preload, /gameAnalysis: \(payload\) => ipcRenderer\.invoke\('studio:game-analysis', payload\)/);
  assert.doesNotMatch(preload, /listGames/);
  assert.doesNotMatch(preload, /openGame/);
});

test('Studio never creates a game window or bundles game packages', () => {
  assert.doesNotMatch(main, /const gameWindow = new BrowserWindow/);
  assert.match(JSON.stringify(packageJson.build.files), /!games\/\*\*/);
  for (const script of Object.values(packageJson.scripts)) {
    assert.doesNotMatch(String(script), /sync-studio-games/);
  }
});

test('Regie exposes analysis only and no game gallery or launch controls', () => {
  assert.match(ui, /data-tool="Spielanalyse"/);
  assert.match(ui, /renderGameAnalysisTool\(body\)/);
  assert.match(ui, /studio\.gameplay\.observation/);
  assert.match(ui, /studio\.game\.replay_marker/);
  assert.doesNotMatch(ui, /game-library-panel/);
  assert.doesNotMatch(ui, /SPIEL ÖFFNEN/);
  assert.doesNotMatch(ui, /openGame\(game\.id\)/);
});
