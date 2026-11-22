'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { resolveFfmpegExecutable } = require('./ffmpeg-runtime');

test('prefers packaged FFmpeg under Electron resources', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-ffmpeg-'));
  try {
    const binary = path.join(root, 'ffmpeg', 'bin', process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg');
    fs.mkdirSync(path.dirname(binary), { recursive: true });
    fs.writeFileSync(binary, '');
    assert.equal(resolveFfmpegExecutable({
      resourcesPath: root,
      appPath: '/app',
      platform: process.platform,
      env: {}
    }), binary);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('uses a valid explicit absolute override before packaged resources', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-ffmpeg-'));
  try {
    const override = path.join(root, 'custom-ffmpeg');
    fs.writeFileSync(override, '');
    assert.equal(resolveFfmpegExecutable({
      resourcesPath: '/resources',
      platform: process.platform,
      env: { STREAMIOV_FFMPEG_PATH: override }
    }), override);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('falls back to PATH command when no packaged or explicit binary exists', () => {
  assert.equal(resolveFfmpegExecutable({
    resourcesPath: '/missing/resources',
    appPath: '/missing/app',
    platform: process.platform,
    env: {}
  }), 'ffmpeg');
});
