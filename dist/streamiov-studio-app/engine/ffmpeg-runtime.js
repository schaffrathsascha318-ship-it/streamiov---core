'use strict';

const fs = require('node:fs');
const path = require('node:path');

/**
 * Resolve FFmpeg from a packaged Streamiov resource first, then an explicit
 * user override, and finally PATH. This resolver does not download binaries.
 */
function resolveFfmpegExecutable(options = {}) {
  const platform = options.platform || process.platform;
  const env = options.env || process.env;
  const executableName = platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg';
  const resourcesPath = options.resourcesPath;
  const appPath = options.appPath;

  const candidates = [];
  // Packaged binaries are the deterministic default for end users.
  if (resourcesPath) {
    candidates.push(path.join(resourcesPath, 'ffmpeg', 'bin', executableName));
    candidates.push(path.join(resourcesPath, 'ffmpeg', executableName));
  }
  if (appPath) {
    candidates.push(path.join(appPath, 'ffmpeg', 'bin', executableName));
    candidates.push(path.join(appPath, 'ffmpeg', executableName));
  }
  if (typeof env.STREAMIOV_FFMPEG_PATH === 'string' && env.STREAMIOV_FFMPEG_PATH.trim()) {
    candidates.push(env.STREAMIOV_FFMPEG_PATH.trim());
  }

  for (const candidate of candidates) {
    if (path.isAbsolute(candidate) && fs.existsSync(candidate)) return candidate;
  }

  // Keep PATH as the final compatibility fallback for development installs.
  return env.STREAMIOV_FFMPEG_PATH && !path.isAbsolute(env.STREAMIOV_FFMPEG_PATH)
    ? env.STREAMIOV_FFMPEG_PATH.trim()
    : 'ffmpeg';
}

module.exports = { resolveFfmpegExecutable };
