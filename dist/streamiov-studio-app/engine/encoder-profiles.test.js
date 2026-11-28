'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  PROFILES, DEFAULT_PROFILE, normalizeEncoderProfile, recommendedBitrate,
  validateStreamSettings, encoderArgsForProfile
} = require('./encoder-profiles');

test('unknown encoder profiles are rejected and the default stays balanced', () => {
  assert.equal(DEFAULT_PROFILE, 'balanced');
  assert.equal(normalizeEncoderProfile(undefined), 'balanced');
  assert.equal(normalizeEncoderProfile(''), 'balanced');
  assert.equal(normalizeEncoderProfile('quality'), 'quality');
  assert.throws(() => normalizeEncoderProfile('unlimited'), /Unbekanntes Encoder-Profil/);
  assert.equal(Object.keys(PROFILES).length, 3);
  for (const profile of Object.values(PROFILES)) {
    assert.equal(profile.tune, 'zerolatency');
    assert.ok(profile.maxBitrate >= 10000 && profile.maxBitrate <= 20000);
  }
});

test('stream settings reject invalid resolution, fps, bitrate and profile', () => {
  assert.deepEqual(
    validateStreamSettings({ resolution: '1080p', fps: 60, bitrate: 4500, profile: 'balanced' }).settings,
    { resolution: '1080p', fps: 60, bitrate: 4500, profile: 'balanced' }
  );
  assert.equal(validateStreamSettings({ resolution: '8k', fps: 60, bitrate: 4500 }).ok, false);
  assert.equal(validateStreamSettings({ resolution: '1080p', fps: 24, bitrate: 4500 }).ok, false);
  assert.equal(validateStreamSettings({ resolution: '1080p', fps: 60, bitrate: 100 }).ok, false);
  assert.equal(validateStreamSettings({ resolution: '1080p', fps: 60, bitrate: 4500.5 }).ok, false);
  assert.equal(validateStreamSettings({ resolution: '1080p', fps: 60, bitrate: 4500, profile: 'magic' }).ok, false);
  assert.match(validateStreamSettings({ resolution: '1080p', fps: 60, bitrate: 12000, profile: 'performance' }).error, /maximal 10000 kbps/);
  assert.equal(validateStreamSettings({ resolution: '1080p', fps: 60, bitrate: 12000, profile: 'quality' }).ok, true);
});

test('recommended bitrates cover every supported resolution and frame rate', () => {
  assert.equal(recommendedBitrate('720p', 30), 1500);
  assert.equal(recommendedBitrate('720p', 60), 2500);
  assert.equal(recommendedBitrate('1080p', 30), 3000);
  assert.equal(recommendedBitrate('1080p', 60), 4500);
  assert.equal(recommendedBitrate('1440p', 30), 6000);
  assert.equal(recommendedBitrate('1440p', 60), 8000);
  assert.equal(recommendedBitrate('2160p', 60), null);
  assert.equal(validateStreamSettings({ resolution: '1440p', fps: 60, bitrate: 8000 }).recommendedBitrate, 8000);
});

test('encoder profiles only emit allowlisted FFmpeg arguments', () => {
  const balanced = encoderArgsForProfile('balanced', 60);
  assert.deepEqual([...balanced], [
    '-preset', 'veryfast', '-tune', 'zerolatency',
    '-g', '120', '-keyint_min', '60', '-sc_threshold', '0'
  ]);
  assert.deepEqual([...encoderArgsForProfile('performance', 30)], [
    '-preset', 'ultrafast', '-tune', 'zerolatency',
    '-g', '60', '-keyint_min', '30', '-sc_threshold', '0'
  ]);
  assert.equal(encoderArgsForProfile('quality', 30)[5], '90');
  assert.throws(() => encoderArgsForProfile('balanced', 45), /Ungültige Bildrate/);
  assert.throws(() => encoderArgsForProfile('bogus', 30), /Unbekanntes Encoder-Profil/);
});
