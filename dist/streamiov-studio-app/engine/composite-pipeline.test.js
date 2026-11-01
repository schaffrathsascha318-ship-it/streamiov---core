'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { buildCompositeAvPipelineArgs } = require('./composite-pipeline');

test('builds an actual two-layer compositor and two-input audio mixer graph', () => {
  const args = buildCompositeAvPipelineArgs({ outputFile: '/tmp/streamiov composite.webm' });
  assert.equal(args[0], '-e');
  assert.ok(args.includes('compositor'));
  assert.ok(args.includes('name=scene'));
  assert.ok(args.includes('audiomixer'));
  assert.ok(args.includes('name=audio_mix'));
  assert.equal(args.filter(value => value === 'scene.').length, 2);
  assert.equal(args.filter(value => value === 'audio_mix.').length, 2);
  assert.ok(args.includes('webmmux'));
  assert.ok(args.includes('location="/tmp/streamiov composite.webm"'));
});

test('allows bounded custom output dimensions and frame rate', () => {
  const args = buildCompositeAvPipelineArgs({
    outputFile: 'capture.webm', width: 1920, height: 1080, fps: 60
  });
  assert.ok(args.includes('video/x-raw,width=1920,height=1080,framerate=60/1'));
  assert.ok(args.includes('num-buffers=180'));
});

test('rejects unsafe or unsupported output configuration', () => {
  assert.throws(() => buildCompositeAvPipelineArgs({ outputFile: '' }), /output file/i);
  assert.throws(() => buildCompositeAvPipelineArgs({ outputFile: 'capture.mp4' }), /\.webm/i);
  assert.throws(() => buildCompositeAvPipelineArgs({ outputFile: 'capture.webm', width: 10000 }), /width/i);
  assert.throws(() => buildCompositeAvPipelineArgs({ outputFile: 'capture.webm', fps: 5 }), /fps/i);
  assert.throws(() => buildCompositeAvPipelineArgs({ outputFile: 'bad\0path.webm' }), /output file/i);
});
