'use strict';

// Argument builder shared by the Electron runtime and the CI smoke test.
// The output path is passed as one argv item; no shell interpolation is used.
function buildSyntheticAvPipelineArgs(outputFile) {
  if (typeof outputFile !== 'string' || !outputFile || outputFile.includes('\0')) {
    throw new TypeError('A valid output file path is required.');
  }

  return [
    '-e',
    'webmmux', 'name=mux', '!', 'filesink', 'location=' + outputFile,
    'videotestsrc', 'num-buffers=90', '!',
    'video/x-raw,width=640,height=360,framerate=30/1', '!',
    'videoconvert', '!', 'vp8enc', 'deadline=1', '!', 'queue', '!', 'mux.',
    'audiotestsrc', 'num-buffers=141', '!',
    'audio/x-raw,rate=48000,channels=2', '!',
    'audioconvert', '!', 'vorbisenc', '!', 'queue', '!', 'mux.'
  ];
}

module.exports = { buildSyntheticAvPipelineArgs };
