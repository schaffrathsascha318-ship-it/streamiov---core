'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const main = fs.readFileSync(require.resolve('../main.js'), 'utf8');
const preload = fs.readFileSync(require.resolve('../preload.js'), 'utf8');
const regie = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');

test('desktop capture discovery is guarded by trusted Electron IPC', () => {
  assert.match(main, /desktopCapturer\.getSources\(/);
  assert.match(main, /studio:get-capture-sources/);
  assert.match(main, /if \(!isTrustedStudioSender\(event\)\)/);
  assert.match(main, /types: \['screen', 'window'\]/);
  assert.match(preload, /getCaptureSources: \(\) => ipcRenderer\.invoke\('studio:get-capture-sources'\)/);
});

test('Electron grants only the selected desktop source through the standard display media API', () => {
  assert.match(main, /setDisplayMediaRequestHandler\(/);
  assert.match(main, /selectedDesktopCaptureSourceId/);
  assert.match(main, /audio: 'loopback'/);
  assert.match(main, /studio:select-capture-source/);
  assert.match(preload, /selectCaptureSource: \(sourceId\) => ipcRenderer\.invoke\('studio:select-capture-source'/);
  assert.match(regie, /navigator\.mediaDevices\.getDisplayMedia\(/);
  assert.match(regie, /desktopCaptureVideo\.srcObject=stream/);
  assert.match(regie, /track\.readyState!=="live"/);
  assert.match(regie, /stopCapture\("desktop"\)/);
  assert.match(regie, /Noch nicht mit dem Encoder verbunden/);
});

test('desktop capture tracks are stopped when preview is stopped or window closes', () => {
  assert.match(regie, /if\(kind==="desktop"\)[\s\S]*desktopCaptureVideo\.srcObject=null/);
  assert.match(regie, /beforeunload[\s\S]*stopCapture\("desktop"\)/);
});
