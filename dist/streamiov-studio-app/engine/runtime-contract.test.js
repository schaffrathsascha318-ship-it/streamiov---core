'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const mainProcess = fs.readFileSync(require.resolve('../main.js'), 'utf8');

test('packaged Studio does not call repository-only Python modules', () => {
  assert.doesNotMatch(mainProcess, /modules\.broadcast|modules\.devices|studio\.modules\.module_loader/);
  assert.doesNotMatch(mainProcess, /execFileAsync\(['"]python3['"]/);
});

test('runtime reports implemented local pipeline without claiming a verified live stream', () => {
  assert.match(mainProcess, /compositor: 'canvas_2d_scene_capture'/);
  assert.match(mainProcess, /encoder: 'ffmpeg_rtmp_pipe'/);
  assert.match(mainProcess, /local_four_bus_engine/);
  assert.match(mainProcess, /live_stream_verified: false/);
  assert.match(mainProcess, /output_ready bestätigt nur initialisierten FLV-Encoder-Output/);
});

test('Studio package does not bundle an unofficial TikTok LIVE connector', () => {
  const packageJson = JSON.parse(fs.readFileSync(require('node:path').join(__dirname, '..', 'package.json'), 'utf8'));
  assert.equal(packageJson.dependencies?.['tiktok-live-connector'], undefined);
});
