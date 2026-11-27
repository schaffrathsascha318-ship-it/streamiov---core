'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const main = fs.readFileSync(require.resolve('../main.js'), 'utf8');
const preload = fs.readFileSync(require.resolve('../preload.js'), 'utf8');
const outputPreload = fs.readFileSync(require.resolve('../program-output-preload.js'), 'utf8');
const outputHtml = fs.readFileSync(require.resolve('../program-output.html'), 'utf8');
const regie = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');

test('Program output is opened through trusted IPC and Electron display detection', () => {
  assert.match(main, /studio:get-displays/);
  assert.match(main, /studio:open-program-output/);
  assert.match(main, /screen\.getAllDisplays\(\)/);
  assert.match(preload, /openProgramOutput/);
  assert.match(regie, /PROGRAMMAUSGABE FENSTER/);
  assert.match(regie, /window\.streamiovStudio\.openProgramOutput\(\)/);
});

test('Program output receives every persisted scene change honestly', () => {
  assert.match(main, /did-finish-load/);
  assert.match(main, /function publishProgramScene\(snapshot\)/);
  assert.match(main, /publishProgramScene\(result\.state\)/);
  assert.match(main, /publishProgramScene\(snapshot\)/);
  assert.match(main, /programFramesDelivered = 0/);
  assert.match(main, /renderedVideo: false, programFramesDelivered/);
  assert.match(main, /programFramesDelivered \+= 1;/);
  assert.match(outputPreload, /ipcRenderer\.on\('studio:program-scene'/);
});

test('Program output renders the local scene on a canvas without claiming live video', () => {
  assert.match(outputHtml, /<canvas id="program" width="1280" height="720"/);
  assert.match(outputHtml, /LOKALE CANVAS · NOCH KEIN LIVE-VIDEO/);
  assert.match(outputHtml, /fillText/);
  assert.match(outputHtml, /createLinearGradient/);
  assert.match(outputHtml, /Bildschirm nicht geteilt/);
  assert.doesNotMatch(outputHtml, /VIDEO-COMPOSITOR NOCH NICHT ANGESCHLOSSEN/);
});

test('Studio relays trusted media assets and canvas frames into the program output', () => {
  assert.match(main, /ipcMain\.handle\('studio:list-media-assets'/);
  assert.match(main, /ipcMain\.handle\('studio:import-media-assets'/);
  assert.match(main, /ipcMain\.handle\('studio:remove-media-asset'/);
  assert.match(main, /ipcMain\.handle\('studio:program-frame'/);
  assert.match(main, /isTrustedStudioSender\(event\)/);
  assert.match(main, /payload\?\.bytes instanceof Uint8Array/);
  assert.match(main, /bytes\[0\] !== 0xff \|\| bytes\[1\] !== 0xd8 \|\| bytes\[2\] !== 0xff/);
  assert.match(main, /data:image\/jpeg;base64,/);
  assert.match(main, /streamiov-media:\/\/asset\//);
  assert.match(main, /protocol\.registerFileProtocol\('streamiov-media'/);
  assert.match(main, /parsed\.host !== 'asset'/);
  assert.match(preload, /listMediaAssets: \(\) => ipcRenderer\.invoke\('studio:list-media-assets'\)/);
  assert.match(preload, /sendProgramFrame: \(frame\) => \{/);
  assert.match(preload, /frame instanceof Uint8Array/);
  assert.match(outputPreload, /ipcRenderer\.on\('studio:program-assets'/);
  assert.match(outputPreload, /ipcRenderer\.on\('studio:program-frame'/);
  assert.match(outputHtml, /window\.streamiovProgramOutput\?\.onFrame/);
  assert.match(outputHtml, /startsWith\('data:image\/jpeg;base64,'\)/);
  assert.match(outputHtml, /createImageBitmap\(blob\)/);
  assert.match(outputHtml, /frameSequence/);
  assert.match(regie, /toBlob\(blob=>/);
  assert.match(regie, /sendProgramFrame\(buffer\)/);
  assert.match(regie, /now-lastProgramFrameAt>33/);
  assert.match(regie, /getDisplayMedia/);
  assert.match(regie, /sourceMute/);
});
