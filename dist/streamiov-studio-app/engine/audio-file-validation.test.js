'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { isWavBuffer } = require('./audio-file-validation.js');

test('akzeptiert eine gültige WAV-Datei', () => {
  const wav = Buffer.alloc(44);
  wav.write('RIFF', 0, 'ascii');
  wav.write('WAVE', 8, 'ascii');
  assert.equal(isWavBuffer(wav), true);
});

test('lehnt leere und zu kurze Dateien ab', () => {
  assert.equal(isWavBuffer(Buffer.alloc(0)), false);
  assert.equal(isWavBuffer(Buffer.alloc(11)), false);
  assert.equal(isWavBuffer(null), false);
  assert.equal(isWavBuffer('RIFF____WAVE'), false);
});

test('lehnt Nicht-WAV-Dateien ab', () => {
  const mp3 = Buffer.alloc(16);
  mp3.write('ID3', 0, 'ascii');
  assert.equal(isWavBuffer(mp3), false);
  const fake = Buffer.alloc(16);
  fake.write('RIFF', 0, 'ascii');
  fake.write('AVI ', 8, 'ascii');
  assert.equal(isWavBuffer(fake), false);
});
