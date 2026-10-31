'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { buildSyntheticAvPipelineArgs } = require('../dist/streamiov-studio-app/media-pipeline');
const execFileAsync = promisify(execFile);

async function main() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'streamiov-ci-av-smoke-'));
  try {
    const output = path.join(directory, 'combined audio video test.webm');
    const args = buildSyntheticAvPipelineArgs(output);
    await execFileAsync('gst-launch-1.0', args, { timeout: 45000, windowsHide: true, maxBuffer: 512 * 1024 });
    const stat = await fs.stat(output);
    assert.equal(stat.isFile(), true);
    assert.ok(stat.size > 1024, 'encoded audio/video output must not be empty');
    process.stdout.write(JSON.stringify({ ok: true, test: 'synthetic_audio_video', container: 'webm', bytes: stat.size }) + '\n');
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
}

main().catch(error => {
  process.stderr.write(String(error.stack || error) + '\n');
  process.exitCode = 1;
});
