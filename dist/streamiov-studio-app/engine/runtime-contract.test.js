'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const mainProcess = fs.readFileSync(require.resolve('../main.js'), 'utf8');

test('packaged Studio does not call repository-only Python modules', () => {
  assert.doesNotMatch(mainProcess, /modules\.broadcast|modules\.devices|studio\.modules\.module_loader/);
  assert.doesNotMatch(mainProcess, /execFileAsync\(['"]python3['"]/);
});

test('runtime reports implemented renderer compositor and RTMP encoder', () => {
  assert.doesNotMatch(mainProcess, /compositor: 'not_implemented'/);
  assert.doesNotMatch(mainProcess, /encoder: 'not_implemented'/);
  assert.match(mainProcess, /compositor: 'renderer_canvas_program_output'/);
  assert.match(mainProcess, /encoder: encoder\.available \? 'ffmpeg_h264_aac_rtmp' : 'ffmpeg_missing'/);
  assert.doesNotMatch(mainProcess, /stage: 'not_implemented'/);
  assert.match(mainProcess, /stage: 'completed'/);
  assert.match(mainProcess, /named_scene_switching_implemented: true/);
  assert.match(mainProcess, /audiotestsrc', 'wave=sine'/);
  assert.match(mainProcess, /wavenc/);
  assert.match(mainProcess, /live_stream_verified: liveConfirmed/);
});

test('production encoder consumes real composited video and required mixer audio', () => {
  assert.match(mainProcess, /'-f', 'webm', '-i', 'pipe:0'/);
  assert.match(mainProcess, /'-map', '0:v:0', '-map', '0:a:0'/);
  assert.match(mainProcess, /'-fps_mode', 'cfr'/);
  assert.match(mainProcess, /'-af', 'aresample=async=1:first_pts=0'/);
  assert.match(mainProcess, /'-f', 'flv', destination/);
});

test('Studio package does not bundle an unofficial TikTok LIVE connector', () => {
  const packageJson = JSON.parse(fs.readFileSync(require('node:path').join(__dirname, '..', 'package.json'), 'utf8'));
  assert.equal(packageJson.dependencies?.['tiktok-live-connector'], undefined);
});
