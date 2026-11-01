'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const appRoot = require('node:path').resolve(__dirname, '..');
const main = fs.readFileSync(require.resolve('../main.js'), 'utf8');
const preload = fs.readFileSync(require.resolve('../preload.js'), 'utf8');
const ui = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');
const packageJson = JSON.parse(fs.readFileSync(require('node:path').join(appRoot, 'package.json'), 'utf8'));

test('Studio exposes only narrow game library IPC methods', () => {
  assert.match(main, /studio:list-games/);
  assert.match(main, /studio:open-game/);
  assert.match(preload, /listGames: \(\) => ipcRenderer\.invoke\('studio:list-games'\)/);
  assert.match(preload, /openGame: \(id\) => ipcRenderer\.invoke\('studio:open-game'/);
});

test('game windows are isolated from the Studio preload and Node runtime', () => {
  const start = main.indexOf('const gameWindow = new BrowserWindow');
  assert.ok(start >= 0);
  const section = main.slice(start, start + 1200);
  assert.match(section, /nodeIntegration: false/);
  assert.match(section, /contextIsolation: true/);
  assert.match(section, /sandbox: true/);
  assert.doesNotMatch(section, /preload:/);
});

test('Regie exposes the packaged game library and labels unreleased games', () => {
  assert.match(ui, /game-library-panel/);
  assert.match(ui, /loadGameLibrary/);
  assert.match(ui, /TESTVERSION/);
  assert.match(ui, /openGame\(game\.id\)/);
});

test('Studio launch and installer preparation sync registered game packages', () => {
  assert.match(packageJson.scripts.prestart, /sync-studio-games\.py/);
  assert.match(packageJson.scripts['pre-dist:win'], /sync-studio-games\.py/);
  assert.match(packageJson.scripts['pre-dist:linux'], /sync-studio-games\.py/);
});
