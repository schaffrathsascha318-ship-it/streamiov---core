'use strict';

const path = require('node:path');

const LIMITS = Object.freeze({
  width: [320, 3840],
  height: [180, 2160],
  fps: [15, 60]
});

function integerInRange(value, key) {
  const [min, max] = LIMITS[key];
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new RangeError(`${key} must be an integer between ${min} and ${max}.`);
  }
  return value;
}

function quoteGstValue(value) {
  return '"' + String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
}

/**
 * Builds a real GStreamer compositor + audio-mixer graph using deterministic
 * test sources. This is a CI/diagnostic graph, not a camera or LIVE adapter.
 * Arguments are passed directly to spawn/execFile; no shell is involved.
 */
function buildCompositeAvPipelineArgs(options = {}) {
  const outputFile = options.outputFile;
  if (typeof outputFile !== 'string' || !outputFile.trim() || outputFile.includes('\0')) {
    throw new TypeError('A valid output file path is required.');
  }
  if (path.extname(outputFile).toLowerCase() !== '.webm') {
    throw new TypeError('The compositor smoke output must use the .webm container.');
  }

  const width = integerInRange(options.width ?? 1280, 'width');
  const height = integerInRange(options.height ?? 720, 'height');
  const fps = integerInRange(options.fps ?? 30, 'fps');
  const frames = fps * 3;
  const caps = `video/x-raw,width=${width},height=${height},framerate=${fps}/1`;

  return [
    '-e',
    'compositor', 'name=scene', 'background=black', '!', caps, '!',
    'videoconvert', '!', 'vp8enc', 'deadline=1', 'keyframe-max-dist=' + fps,
    '!', 'queue', '!', 'webmmux', 'name=mux', '!', 'filesink',
    'location=' + quoteGstValue(outputFile),

    'videotestsrc', 'num-buffers=' + frames, 'pattern=smpte', '!',
    caps, '!', 'videoconvert', '!', 'queue', '!', 'scene.',
    'videotestsrc', 'num-buffers=' + frames, 'pattern=ball', '!',
    caps, '!', 'videoconvert', '!', 'queue', '!', 'scene.',

    'audiomixer', 'name=audio_mix', '!', 'audioconvert', '!', 'audioresample', '!',
    'audio/x-raw,rate=48000,channels=2', '!', 'vorbisenc', '!', 'queue', '!', 'mux.',
    'audiotestsrc', 'num-buffers=141', 'wave=sine', 'freq=440', '!',
    'audio/x-raw,rate=48000,channels=2', '!', 'queue', '!', 'audio_mix.',
    'audiotestsrc', 'num-buffers=141', 'wave=sine', 'freq=660', 'volume=0.2', '!',
    'audio/x-raw,rate=48000,channels=2', '!', 'queue', '!', 'audio_mix.'
  ];
}

module.exports = { buildCompositeAvPipelineArgs };
