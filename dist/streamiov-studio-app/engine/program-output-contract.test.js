'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const main = fs.readFileSync(require.resolve('../main.js'), 'utf8');
const preload = fs.readFileSync(require.resolve('../preload.js'), 'utf8');
const outputPreload = fs.readFileSync(require.resolve('../program-output-preload.js'), 'utf8');
const outputHtml = fs.readFileSync(require.resolve('../program-output.html'), 'utf8');

test('Program output is opened through trusted IPC and Electron display detection', () => {
  assert.match(main, /studio:get-displays/);
  assert.match(main, /studio:open-program-output/);
  assert.match(main, /screen\.getAllDisplays\(\)/);
  assert.match(preload, /openProgramOutput/);
});

test('Program output receives the current scene and labels missing video honestly', () => {
  assert.match(main, /did-finish-load/);
  assert.match(main, /studio:program-scene/);
  assert.match(main, /renderedVideo: false/);
  assert.match(outputPreload, /ipcRenderer\.on\('studio:program-scene'/);
  assert.match(outputHtml, /VIDEO-COMPOSITOR NOCH NICHT ANGESCHLOSSEN/);
});
