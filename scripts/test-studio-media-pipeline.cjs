'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { buildSyntheticAvPipelineArgs } = require('../dist/streamiov-studio-app/media-pipeline');
const { buildCompositeAvPipelineArgs } = require('../dist/streamiov-studio-app/engine/composite-pipeline');
const execFileAsync = promisify(execFile);

async function runPipeline(args, output, testName) {
  await execFileAsync('gst-launch-1.0', args, {
    timeout: 60000, windowsHide: true, maxBuffer: 512 * 1024
  });
  const stat = await fs.stat(output);
  assert.equal(stat.isFile(), true);
  assert.ok(stat.size > 1024, testName + ' output must not be empty');
  process.stdout.write(JSON.stringify({ ok: true, test: testName, container: 'webm', bytes: stat.size }) + '\n');
}

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'streamiov-ci-av-smoke-'));
  try {
    const syntheticOutput = path.join(directory, 'synthetic audio video.webm');
    await runPipeline(buildSyntheticAvPipelineArgs(syntheticOutput), syntheticOutput, 'synthetic_audio_video');

    const compositeOutput = path.join(directory, 'composited mixed audio video.webm');
    await runPipeline(buildCompositeAvPipelineArgs({ outputFile: compositeOutput }), compositeOutput, 'two_layer_compositor_and_audio_mixer');
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
}

main().catch(error => {
  process.stderr.write(String(error.stack || error) + '\n');
  process.exitCode = 1;
});
