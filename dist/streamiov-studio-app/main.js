const { app, BrowserWindow, session, ipcMain, desktopCapturer, screen, shell, Notification, dialog, protocol } = require('electron');

const path = require('node:path');
const fs = require('node:fs/promises');
const { constants: fsConstants } = require('node:fs');
const { randomUUID } = require('node:crypto');
const os = require('node:os');
const http = require('node:http');
const { pathToFileURL } = require('node:url');
const { execFile, spawn } = require('node:child_process');
const { promisify } = require('node:util');
const execFileAsync = promisify(execFile);
const { buildSyntheticAvPipelineArgs } = require('./media-pipeline');
const { StudioSourceModel } = require('./engine/source-model');
const { StudioSceneEngine } = require('./engine/scene-engine');
const { resolveFfmpegExecutable } = require('./engine/ffmpeg-runtime');
const { PlatformOutputRegistry } = require('./engine/platform-output-registry');
const { LiveOutputManager, PLATFORMS: LIVE_PLATFORMS } = require('./engine/live-output-manager');
const { encoderArgsForProfile, validateStreamSettings } = require('./engine/encoder-profiles');
const { collectRendererMeasurements, countMediaDevices, createDeviceCapabilityReport } = require('./engine/device-capabilities-bridge');
const { redactUrlForLog } = require('./engine/log-redaction');
const { isWavBuffer } = require('./engine/audio-file-validation');
const { StreamiovAppUpdater, releaseTagUrl } = require('./engine/app-updater');
const { GameAnalysis } = require('./engine/game-analysis');
const { listRunningProcesses } = require('./engine/game-process-detector');
const { createStudioEvent } = require('./engine/studio-event-client');
const { createMediaAssetStore } = require('./engine/media-asset-store');
const platformOutputRegistry = new PlatformOutputRegistry();
const mediaAssetStore = createMediaAssetStore({ rootDir: path.join(app.getPath('userData'), 'media') });
const gameAnalysis = new GameAnalysis({ filePath: path.join(app.getPath('userData'), 'game-analysis.json') });
let mediaAssetsLoaded = mediaAssetStore.load().then(() => true).catch(() => false);
function mediaAssetUrl(id) {
  return 'streamiov-media://asset/' + encodeURIComponent(id);
}
function mediaAssetsWithUrls() {
  return mediaAssetStore.list().map(asset => ({ ...asset, url: mediaAssetUrl(asset.id) }));
}
if (typeof protocol?.registerSchemesAsPrivileged === 'function') {
  protocol.registerSchemesAsPrivileged([{
    scheme: 'streamiov-media',
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true }
  }]);
}

const liveOutputManager = new LiveOutputManager({ spawnImpl: spawn, onEvent: handleLiveOutputEvent, onHealthEvent: handleLiveHealthEvent });
const liveOutputStatus = new Map(LIVE_PLATFORMS.map(platform => [platform, { status: 'idle', detail: '' }]));
let lastEncoderProfile = null;
let remoteConfirmationTimer = null;
let remoteConfirmationRunning = false;

function platformOutputState(platform) {
  return platformOutputRegistry.snapshot()[platform]?.state || 'offline';
}
function transitionPlatformOutput(platform, nextState, detail = '') {
  const current = platformOutputState(platform);
  if (current === nextState) return;
  const options = detail ? { detail: String(detail).slice(0, 300) } : {};
  const attempt = (state, stateOptions = options) => platformOutputRegistry.transition(platform, state, stateOptions);
  try {
    attempt(nextState);
    return;
  } catch (error) {
    if (nextState === 'live') throw error;
  }
  let state = platformOutputState(platform);
  if (state !== 'offline') {
    try { attempt('offline', { detail: 'Ausgangszustand zurückgesetzt.' }); } catch {}
    state = platformOutputState(platform);
  }
  if (state === 'offline' && ['ready', 'connecting', 'error'].includes(nextState)) {
    try { attempt('authorizing'); } catch {}
    if (nextState === 'connecting' && platformOutputState(platform) === 'authorizing') {
      try { attempt('ready'); } catch {}
    }
  }
  try { attempt(nextState); } catch {}
}
function preparePlatformOutput(platform, detail) {
  if (platformOutputState(platform) === 'offline') transitionPlatformOutput(platform, 'authorizing', detail);
  transitionPlatformOutput(platform, 'ready', detail);
}
function syncPlatformOutputWithStreamStatus(status, detail = '') {
  const active = liveOutputManager.activePlatforms();
  const message = detail ? String(detail) : '';
  if (!active.length && status === 'offline') {
    for (const platform of LIVE_PLATFORMS) {
      if (platformOutputState(platform) !== 'offline') transitionPlatformOutput(platform, 'offline', message || 'Ausgabe beendet.');
    }
    return;
  }
  for (const platform of active) {
    const current = platformOutputState(platform);
    if (status === 'connecting' && ['ready', 'authorizing'].includes(current)) {
      transitionPlatformOutput(platform, 'connecting', message || 'Lokale RTMP-Ausgabe wird initialisiert; LIVE nicht bestätigt.');
    } else if (status === 'output_ready' && ['connecting', 'ready'].includes(current)) {
      transitionPlatformOutput(platform, 'ready', message || 'Encoder-Ausgabe initialisiert; Remote-Plattform nicht bestätigt.');
    } else if (status === 'reconnecting' && ['connecting', 'live'].includes(current)) {
      transitionPlatformOutput(platform, 'reconnecting', message || 'Verbindung unterbrochen; Wiederverbindung läuft.');
    } else if (status === 'error' && current !== 'error') {
      transitionPlatformOutput(platform, 'error', message || 'Ausgabe fehlgeschlagen.');
    } else if (status === 'offline' && current !== 'offline') {
      transitionPlatformOutput(platform, 'offline', message || 'Ausgabe beendet.');
    }
  }
}

const STREAMIOV_API = process.env.STREAMIOV_HOST_URL || 'http://127.0.0.1:8765';
const STREAMIOV_CLIENT_HEADER = 'studio';

function synthesizeWindowsSpeech({ text, outputFile, speed, amplitude }) {
  return new Promise((resolve, reject) => {
    const script = [
      "$ErrorActionPreference = 'Stop'",
      "$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json",
      "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer",
      "$germanVoice = $speaker.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'de-*' } | Select-Object -First 1",
      "if (-not $germanVoice) { throw 'Keine deutsche Windows-Systemstimme installiert.' }",
      "$speaker.SelectVoice($germanVoice.VoiceInfo.Name)",
      "$speaker.Rate = [int]$payload.rate",
      "$speaker.Volume = [int]$payload.volume",
      "$speaker.SetOutputToWaveFile($env:STREAMIOV_TTS_OUTPUT)",
      "$speaker.Speak([string]$payload.text)",
      "$speaker.Dispose()"
    ].join("; ");
    const child = spawn('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script], {
      windowsHide: true,
      env: { ...process.env, STREAMIOV_TTS_OUTPUT: outputFile },
      stdio: ['pipe', 'ignore', 'pipe']
    });
    let stderr = '';
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error); else resolve();
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(new Error('Windows-Sprachausgabe hat das Zeitlimit überschritten.'));
    }, 60000);
    child.stderr.on('data', chunk => { stderr = (stderr + chunk.toString()).slice(-4000); });
    child.stdin.on('error', finish);
    child.once('error', finish);
    child.once('close', code => {
      if (code === 0) finish();
      else finish(new Error(stderr.trim() || 'Windows-Systemsprachausgabe fehlgeschlagen.'));
    });
    const rate = Math.max(-10, Math.min(10, Math.round((speed - 175) / 12.5)));
    child.stdin.end(JSON.stringify({ text, rate, volume: Math.max(0, Math.min(100, amplitude)) }));
  });
}
const studioUrl = pathToFileURL(path.join(__dirname, 'regie-v2.html')).href;
let liveStreamState = 'offline';
const RECORDING_MAX_BYTES = 2 * 1024 * 1024 * 1024;
let streamRecording = null;
let lastStreamRecording = null;
let recordingWriteQueue = Promise.resolve();
let studioAppUpdater = null;
let studioUpdaterRecovery = null;

async function getStudioUpdater() {
  if (!studioAppUpdater) {
    studioAppUpdater = new StreamiovAppUpdater({
      currentVersion: app.getVersion(),
      userDataDir: app.getPath('userData'),
      packaged: Boolean(app.isPackaged),
      fetchImpl: fetch,
      spawnImpl: spawn,
      isUpdateAllowed: () => !liveOutputManager.isActive() && liveStreamState === 'offline'
    });
  }
  if (!studioUpdaterRecovery) {
    studioUpdaterRecovery = studioAppUpdater.recover().then(() => true).catch(() => true);
  }
  await studioUpdaterRecovery;
  return studioAppUpdater;
}

ipcMain.handle('studio:platform-output-status', (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  return platformOutputRegistry.snapshot();
});

let observedMediaDeviceCounts = null;
let observedMediaDevicesAt = null;

ipcMain.handle('studio:get-device-capabilities', async (event, rendererPayload) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const counts = countMediaDevices(rendererPayload?.devices);
  if (counts) {
    observedMediaDeviceCounts = counts;
    observedMediaDevicesAt = new Date().toISOString();
  }
  const measurements = { ...collectRendererMeasurements(rendererPayload) };
  const displays = screen.getAllDisplays();
  measurements.multiDisplay = {
    value: displays.length > 1,
    source: 'electron.screen.getAllDisplays'
  };
  try {
    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: 16, height: 9 }
    });
    measurements.screenCapture = {
      value: sources.length > 0,
      source: 'electron.desktopCapturer.getSources'
    };
  } catch (_error) {
    measurements.screenCapture = {
      value: false,
      source: 'electron.desktopCapturer.getSources'
    };
  }
  try {
    await fs.access(app.getPath('userData'), fsConstants.W_OK);
    measurements.fileAccess = { value: true, source: 'app.getPath(userData)' };
  } catch (_error) {
    measurements.fileAccess = { value: false, source: 'app.getPath(userData)' };
  }
  if (typeof Notification?.isSupported === 'function') {
    let supported = false;
    try {
      supported = Notification.isSupported();
    } catch (_error) {
      supported = false;
    }
    measurements.notifications = {
      value: supported,
      source: 'electron.Notification.isSupported'
    };
  }
  return createDeviceCapabilityReport({
    platform: process.platform,
    architecture: os.arch(),
    measurements
  });
});

let selectedDisplaySourceId = null;

ipcMain.handle('studio:list-display-sources', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const sources = await desktopCapturer.getSources({
    types: ['screen', 'window'],
    thumbnailSize: { width: 320, height: 180 },
    fetchWindowIcons: true
  });
  return sources.map((source) => ({
    id: source.id,
    name: source.name,
    thumbnail: source.thumbnail.toDataURL(),
    icon: source.appIcon ? source.appIcon.toDataURL() : null
  }));
});

ipcMain.on('studio:select-display-source', (event, sourceId) => {
  if (!isTrustedStudioSender(event) || typeof sourceId !== 'string' || sourceId.length > 500) {
    event.returnValue = false;
    return;
  }
  selectedDisplaySourceId = sourceId;
  event.returnValue = true;
});

ipcMain.handle('studio:list-media-assets', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  await mediaAssetsLoaded;
  return { ok: true, assets: mediaAssetsWithUrls() };
});

ipcMain.handle('studio:import-media-assets', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (typeof dialog?.showOpenDialog !== 'function') {
    return { ok: false, error: 'Dateiauswahl ist in dieser Laufzeit nicht verfügbar.' };
  }
  const kind = typeof payload?.kind === 'string' ? payload.kind : '';
  const filters = kind === 'image'
    ? [{ name: 'Bilder', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }]
    : kind === 'video'
      ? [{ name: 'Videos', extensions: ['webm', 'mp4', 'ogg', 'mov'] }]
      : kind === 'audio'
        ? [{ name: 'Audio', extensions: ['wav', 'mp3', 'ogg', 'm4a', 'flac'] }]
        : [{ name: 'Medien', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'webm', 'mp4', 'ogg', 'mov', 'wav', 'mp3', 'm4a', 'flac'] }];
  const selection = await dialog.showOpenDialog(mainWindow || undefined, {
    title: 'Mediendatei für STREAMIOV importieren',
    properties: ['openFile', 'multiSelect'],
    filters
  });
  if (selection.canceled) return { ok: true, canceled: true, assets: [] };
  await mediaAssetsLoaded;
  const assets = [];
  const errors = [];
  for (const filePath of (selection.filePaths || []).slice(0, 20)) {
    try {
      assets.push({ ...await mediaAssetStore.importFile(filePath, kind || undefined), url: '' });
    } catch (error) {
      errors.push(String(error.message || error).slice(0, 180));
    }
  }
  return {
    ok: assets.length > 0,
    error: assets.length ? null : (errors[0] || 'Keine Mediendatei importiert.'),
    errors,
    assets: assets.map(asset => ({ ...asset, url: mediaAssetUrl(asset.id) }))
  };
});

ipcMain.handle('studio:remove-media-asset', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  await mediaAssetsLoaded;
  const removed = await mediaAssetStore.remove(payload?.id);
  return { ok: removed, assets: mediaAssetsWithUrls() };
});

function recordingsDirectory() {
  return path.join(app.getPath('userData'), 'recordings');
}
function isRecordingFileName(id) {
  return typeof id === 'string' && id === path.basename(id) && /^[A-Za-z0-9][A-Za-z0-9._-]*\.webm$/.test(id);
}
function recordingFilePath(id) {
  if (!isRecordingFileName(id)) throw new Error('Ungültiger Aufzeichnungsdateiname.');
  return path.join(recordingsDirectory(), id);
}
function recordingSnapshot() {
  const recording = streamRecording || lastStreamRecording;
  if (!recording) {
    return { ok: true, active: false, mode: null, path: null, bytes: 0, queuedBytes: 0, startedAt: null, stoppedAt: null, reason: null, limitReached: false, error: null };
  }
  return {
    ok: true,
    active: Boolean(streamRecording),
    mode: recording.mode || 'stream',
    path: recording.filePath,
    bytes: recording.bytes,
    queuedBytes: recording.queuedBytes,
    startedAt: recording.startedAt,
    stoppedAt: recording.stoppedAt,
    reason: recording.reason,
    limitReached: recording.limitReached,
    error: recording.error
  };
}
async function startStreamRecording(mode = 'stream') {
  if (streamRecording) return { ok: false, error: 'Eine lokale Aufzeichnung läuft bereits.', recording: recordingSnapshot() };
  const directory = recordingsDirectory();
  await fs.mkdir(directory, { recursive: true });
  const prefix = mode === 'local' ? 'local' : 'stream';
  const name = prefix + '-' + new Date().toISOString().replace(/[:.]/g, '-') + '-' + randomUUID().slice(0, 8) + '.webm';
  const filePath = path.join(directory, name);
  const handle = await fs.open(filePath, 'wx');
  streamRecording = {
    filePath, handle, bytes: 0, queuedBytes: 0, mode,
    startedAt: new Date().toISOString(), stoppedAt: null,
    reason: null, limitReached: false, error: null
  };
  lastStreamRecording = streamRecording;
  return { ok: true, recording: recordingSnapshot() };
}
async function appendStreamRecording(chunk) {
  const recording = streamRecording;
  if (!recording) return;
  if (recording.queuedBytes + chunk.byteLength > RECORDING_MAX_BYTES) {
    recording.limitReached = true;
    recording.reason = 'limit';
    recording.stoppedAt = new Date().toISOString();
    streamRecording = null;
    await recordingWriteQueue.catch(() => {});
    try { await recording.handle.close(); } catch {}
    return;
  }
  recording.queuedBytes += chunk.byteLength;
  recordingWriteQueue = recordingWriteQueue.then(async () => {
    if (streamRecording !== recording) return;
    await recording.handle.write(chunk);
    recording.bytes += chunk.byteLength;
  }).catch(async error => {
    if (streamRecording === recording) streamRecording = null;
    recording.reason = 'error';
    recording.stoppedAt = new Date().toISOString();
    recording.error = String(error?.message || error).slice(0, 300);
    try { await recording.handle.close(); } catch {}
  });
  await recordingWriteQueue;
}
async function stopStreamRecording(reason = 'user') {
  const recording = streamRecording;
  if (!recording) return { ok: true, recording: recordingSnapshot() };
  streamRecording = null;
  recording.reason = reason;
  recording.stoppedAt = new Date().toISOString();
  await recordingWriteQueue.catch(() => {});
  try {
    await recording.handle.close();
  } catch (error) {
    recording.error = String(error?.message || error).slice(0, 300);
  }
  return { ok: true, recording: recordingSnapshot() };
}
async function listRecordingFiles() {
  const directory = recordingsDirectory();
  await fs.mkdir(directory, { recursive: true });
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.filter(entry => entry.isFile() && isRecordingFileName(entry.name)).map(async entry => {
    const filePath = path.join(directory, entry.name);
    const stats = await fs.stat(filePath);
    return { id: entry.name, name: entry.name, path: filePath, bytes: stats.size, modifiedAt: stats.mtime.toISOString() };
  }));
  return files.sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt)).slice(0, 100);
}
async function recordingFileAction(id, action) {
  const filePath = recordingFilePath(id);
  if (action !== 'open' && action !== 'reveal' && action !== 'delete') return { ok: false, error: 'Unbekannte Aufzeichnungsaktion.' };
  if (action === 'delete' && streamRecording && path.basename(streamRecording.filePath) === id) {
    return { ok: false, error: 'Die aktive Aufzeichnung kann nicht gelöscht werden.' };
  }
  let stats;
  try {
    stats = await fs.lstat(filePath);
  } catch (error) {
    return { ok: false, error: error?.code === 'ENOENT' ? 'Aufzeichnung wurde nicht gefunden.' : String(error?.message || error).slice(0, 300) };
  }
  if (!stats.isFile()) return { ok: false, error: 'Keine reguläre Aufzeichnungsdatei.' };
  if (action === 'delete') {
    await fs.unlink(filePath);
    return { ok: true, path: filePath };
  }
  if (action === 'reveal') {
    shell.showItemInFolder(filePath);
    return { ok: true, path: filePath };
  }
  const openError = await shell.openPath(filePath);
  return openError ? { ok: false, error: String(openError).slice(0, 300) } : { ok: true, path: filePath };
}
ipcMain.handle('studio:recording-status', (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  return recordingSnapshot();
});
ipcMain.handle('studio:recording-action', async (event, action) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (action === 'start') {
    try { return await startStreamRecording(liveOutputManager.isActive() ? 'stream' : 'local'); }
    catch (error) { return { ok: false, error: String(error?.message || error).slice(0, 300), recording: recordingSnapshot() }; }
  }
  if (action === 'stop') return stopStreamRecording('user');
  return { ok: false, error: 'Unbekannte Aufzeichnungsaktion.', recording: recordingSnapshot() };
});
ipcMain.handle('studio:record-chunk', async (event, chunk) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (!streamRecording) return { ok: false, error: 'Keine aktive lokale Aufzeichnung.', recording: recordingSnapshot() };
  if (Object.prototype.toString.call(chunk) !== '[object ArrayBuffer]' || chunk.byteLength > 4 * 1024 * 1024) {
    return { ok: false, error: 'Ungültiger Medienblock.', recording: recordingSnapshot() };
  }
  await appendStreamRecording(new Uint8Array(chunk));
  return { ok: true, recording: recordingSnapshot() };
});
ipcMain.handle('studio:recording-list', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  try { return { ok: true, files: await listRecordingFiles() }; }
  catch (error) { return { ok: false, error: String(error?.message || error).slice(0, 300), files: [] }; }
});
ipcMain.handle('studio:recording-file-action', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  try { return await recordingFileAction(payload?.id, payload?.action); }
  catch (error) { return { ok: false, error: String(error?.message || error).slice(0, 300) }; }
});

function publishGlobalStreamStatus(status, detail = '') {
  liveStreamState = status;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('studio:stream-status', { status, detail });
  }
}
function publishStreamStatus(status, detail = '') {
  liveStreamState = status;
  syncPlatformOutputWithStreamStatus(status, detail);
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('studio:stream-status', { status, detail });
  }
}
function handleLiveHealthEvent(platform, status, health) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send('studio:stream-telemetry', {
    platform,
    status,
    health: liveOutputManager.healthSnapshot(),
    encoderProfile: lastEncoderProfile
  });
}
function handleLiveOutputEvent(platform, event, payload = {}) {
  const detail = typeof payload.detail === 'string' ? payload.detail : '';
  liveOutputStatus.set(platform, { status: event, detail, attempt: payload.attempt ?? 0 });
  const current = platformOutputState(platform);
  if (event === 'starting') {
    preparePlatformOutput(platform, detail || 'RTMP-Ausgabe wird gestartet.');
    if (platformOutputState(platform) === 'ready') transitionPlatformOutput(platform, 'connecting', detail);
  } else if (event === 'connecting') {
    if (['offline', 'authorizing'].includes(current)) preparePlatformOutput(platform, detail);
    if (platformOutputState(platform) === 'ready') transitionPlatformOutput(platform, 'connecting', detail);
  } else if (event === 'output_ready') {
    if (['offline', 'authorizing'].includes(platformOutputState(platform))) preparePlatformOutput(platform, detail);
    transitionPlatformOutput(platform, 'ready', detail);
  } else if (event === 'reconnecting') {
    if (['offline', 'authorizing', 'ready'].includes(platformOutputState(platform))) preparePlatformOutput(platform, detail);
    if (platformOutputState(platform) === 'ready') transitionPlatformOutput(platform, 'connecting', detail);
    if (['connecting', 'live'].includes(platformOutputState(platform))) transitionPlatformOutput(platform, 'reconnecting', detail);
  } else if (event === 'error') {
    transitionPlatformOutput(platform, 'error', detail);
  } else if (event === 'offline') {
    transitionPlatformOutput(platform, 'offline', detail);
  }
  const active = liveOutputManager.activePlatforms();
  if (!active.length) {
    if (streamRecording?.mode === 'stream') void stopStreamRecording('stream_ended');
    publishGlobalStreamStatus('offline', detail);
  }
  else if (event === 'reconnecting') publishGlobalStreamStatus('reconnecting', detail);
  else if (event === 'error') publishGlobalStreamStatus('error', detail);
  else if (active.length) publishGlobalStreamStatus(event === 'output_ready' ? 'output_ready' : 'connecting', detail);
}

const TWITCH_INGEST_URL = 'rtmps://live.twitch.tv:443/app';

function parseRtmpUrl(value) {
  if (typeof value !== 'string' || value.trim().length > 2048) return null;
  try {
    const url = new URL(value.trim());
    if (!['rtmp:', 'rtmps:'].includes(url.protocol) || !url.hostname || !url.pathname ||
        url.username || url.password || url.hash) return null;
    return url;
  } catch {
    return null;
  }
}

function normalizeRtmpDestination(value) {
  const url = parseRtmpUrl(value);
  return url ? url.toString() : null;
}

function normalizeTwitchDestination(credentials) {
  const streamKey = credentials && typeof credentials.streamKey === 'string' ? credentials.streamKey : '';
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(streamKey)) return null;
  const ingest = parseRtmpUrl(credentials && credentials.ingestUrl);
  if (!ingest || ingest.protocol !== 'rtmps:' || ingest.hostname !== 'live.twitch.tv' ||
      ingest.port !== '443' || ingest.pathname !== '/app' || ingest.search || ingest.hash) return null;
  return normalizeRtmpDestination(`${TWITCH_INGEST_URL}/${streamKey}`);
}
function normalizePlatformDestination(credentials) {
  const streamKey = credentials && typeof credentials.streamKey === 'string' ? credentials.streamKey.trim() : '';
  if (!streamKey || streamKey.length > 512 || /[\r\n\s]/.test(streamKey)) return null;
  const ingest = parseRtmpUrl(credentials && credentials.ingestUrl);
  if (!ingest) return null;
  return normalizeRtmpDestination(`${ingest.toString().replace(/\/$/, '')}/${streamKey}`);
}
function buildRtmpEncoderArgs(destination, settings, dimensions) {
  return [
    '-hide_banner', '-loglevel', 'info', '-fflags', '+genpts', '-analyzeduration', '0', '-probesize', '33554432',
    '-f', 'webm', '-i', 'pipe:0',
    '-map', '0:v:0', '-map', '0:a:0', '-vf', `scale=${dimensions[0]}:${dimensions[1]}:force_original_aspect_ratio=decrease,pad=${dimensions[0]}:${dimensions[1]}:(ow-iw)/2:(oh-ih)/2`,
    '-r', String(settings.fps), '-fps_mode', 'cfr', '-c:v', 'libx264', ...encoderArgsForProfile(settings.profile, settings.fps),
    '-pix_fmt', 'yuv420p',
    '-b:v', `${settings.bitrate}k`, '-maxrate', `${settings.bitrate}k`, '-bufsize', `${settings.bitrate * 2}k`,
    '-af', 'aresample=async=1:first_pts=0', '-c:a', 'aac', '-b:a', '128k', '-ar', '48000', '-ac', '2', '-f', 'flv', destination
  ];
}
async function resolveOutputCredentials(platform) {
  if (platform === 'twitch') {
    const credentials = await getTwitchOAuth().getStreamCredentials();
    const destination = normalizeTwitchDestination(credentials);
    return destination ? { platform, destination } : { platform, error: 'Twitch-Ausgabeziel ungültig.' };
  }
  if (platform === 'tiktok') {
    const credentials = await getTikTokOAuth().getStreamCredentials();
    const destination = normalizePlatformDestination(credentials);
    return destination ? { platform, destination } : { platform, error: 'TikTok-Ausgabeziel ungültig.' };
  }
  return { platform, error: 'Unbekannte LIVE-Plattform.' };
}
async function confirmRemoteLiveStatuses() {
  if (remoteConfirmationRunning) return;
  remoteConfirmationRunning = true;
  try {
    for (const platform of liveOutputManager.activePlatforms()) {
      const snapshot = platformOutputRegistry.snapshot()[platform];
      if (!snapshot || !['ready', 'connecting', 'reconnecting', 'live'].includes(snapshot.state)) continue;
      let status;
      try {
        if (platform === 'twitch') status = await getTwitchOAuth().getLiveStatus();
        else status = await getTikTokOAuth().getLiveStatus();
      } catch (_error) {
        continue;
      }
      if (!status) continue;
      if (status.live && status.confirmationId && snapshot.state !== 'live') {
        transitionPlatformOutput(platform, 'live', {
          detail: status.title ? `LIVE remote bestätigt: ${status.title}` : 'LIVE von der Plattform bestätigt.',
          evidence: {
            type: 'remote_platform_confirmation',
            platform,
            confirmationId: status.confirmationId,
            confirmedAt: new Date().toISOString()
          }
        });
      } else if (!status.live && snapshot.liveConfirmed) {
        transitionPlatformOutput(platform, 'reconnecting', 'Plattform meldet kein aktives LIVE mehr.');
      }
    }
  } finally {
    remoteConfirmationRunning = false;
  }
}
function startRemoteConfirmationPolling() {
  if (remoteConfirmationTimer) return;
  void confirmRemoteLiveStatuses();
  remoteConfirmationTimer = setInterval(() => void confirmRemoteLiveStatuses(), 5000);
  if (typeof remoteConfirmationTimer.unref === 'function') remoteConfirmationTimer.unref();
}
function stopRemoteConfirmationPolling() {
  if (!remoteConfirmationTimer) return;
  clearInterval(remoteConfirmationTimer);
  remoteConfirmationTimer = null;
}

ipcMain.handle('studio:start-stream', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (liveOutputManager.isActive() || liveStreamState === 'stopping') return { ok: false, error: 'Ein Stream läuft bereits.' };

  const options = payload && typeof payload === 'object' ? payload : {};
  const requested = Array.isArray(options.platforms) ? options.platforms : (options.platform ? [options.platform] : []);
  const platforms = [...new Set(requested.map(platform => typeof platform === 'string' ? platform.trim().toLowerCase() : platform))];
  if (!platforms.length) return { ok: false, error: 'Keine LIVE-Plattform ausgewählt.' };
  if (platforms.some(platform => !LIVE_PLATFORMS.includes(platform))) {
    return { ok: false, error: 'Mindestens eine ausgewählte LIVE-Plattform wird nicht unterstützt.' };
  }
  const validated = validateStreamSettings({
    resolution: options.resolution, fps: options.fps, bitrate: options.bitrate, profile: options.profile
  });
  if (!validated.ok) return { ok: false, error: validated.error };
  const { resolution, fps, bitrate, profile } = validated.settings;
  const encoder = await probeFfmpegRtmp();
  if (!encoder.available) {
    for (const platform of platforms) transitionPlatformOutput(platform, 'error', 'Encoder nicht verfügbar: ' + encoder.missing.join(', ') + '.');
    return {
      ok: false,
      error: 'RTMP-Streaming benötigt FFmpeg mit libx264, AAC und RTMP/RTMPS. Fehlend: ' + encoder.missing.join(', ') + '.'
    };
  }
  const outputs = await Promise.all(platforms.map(async platform => {
    try {
      return await resolveOutputCredentials(platform);
    } catch (error) {
      return { platform, error: String(error.message || error) };
    }
  }));
  const failed = outputs.filter(output => output.error);
  if (failed.length) {
    for (const output of failed) transitionPlatformOutput(output.platform, 'error', output.error);
    return { ok: false, error: failed.map(output => output.platform + ': ' + output.error).join('; ') };
  }
  const dimensions = { '720p': [1280, 720], '1080p': [1920, 1080], '1440p': [2560, 1440] }[resolution];
  const startedPlatforms = [];
  for (const output of outputs) {
    preparePlatformOutput(output.platform, 'Autorisierte Ausgabe vorbereitet; LIVE nicht bestätigt.');
    const started = liveOutputManager.start({
      platform: output.platform,
      executable: encoder.executable,
      args: buildRtmpEncoderArgs(output.destination, { fps, bitrate, profile }, dimensions),
      destination: output.destination
    });
    if (!started.ok) {
      for (const platform of startedPlatforms) await liveOutputManager.stop(platform);
      transitionPlatformOutput(output.platform, 'error', started.error);
      lastEncoderProfile = null;
      publishStreamStatus('offline', started.error);
      return { ok: false, error: started.error };
    }
    startedPlatforms.push(output.platform);
    liveOutputStatus.set(output.platform, { status: 'starting', detail: 'RTMP-Ausgabe wird gestartet.', attempt: 0 });
  }
  lastEncoderProfile = profile;
  startRemoteConfirmationPolling();
  publishGlobalStreamStatus('connecting', 'Lokale RTMP-Ausgaben werden initialisiert; LIVE nicht bestätigt.');
  return { ok: true, status: 'connecting', platforms: liveOutputManager.activePlatforms() };
});

ipcMain.handle('studio:write-stream-chunk', async (event, chunk) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (!liveOutputManager.isActive() || liveStreamState === 'stopping') return { ok: false, error: 'Kein aktiver Stream.' };
  if (Object.prototype.toString.call(chunk) !== '[object ArrayBuffer]' || chunk.byteLength > 4 * 1024 * 1024) {
    return { ok: false, error: 'Ungültiger Medienblock.' };
  }
  const bytes = new Uint8Array(chunk);
  const written = await liveOutputManager.write(bytes);
  if (written.ok !== false && streamRecording?.mode === 'stream') await appendStreamRecording(bytes);
  return { ...written, recording: recordingSnapshot() };
});

ipcMain.handle('studio:stop-stream', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  stopRemoteConfirmationPolling();
  if (!liveOutputManager.isActive()) {
    publishStreamStatus('offline');
    return { ok: true, status: 'offline' };
  }
  liveStreamState = 'stopping';
  publishGlobalStreamStatus('stopping', 'LIVE-Ausgaben werden beendet.');
  await liveOutputManager.stopAll();
  const recording = streamRecording?.mode === 'stream' ? await stopStreamRecording('stream_stopped') : { recording: recordingSnapshot() };
  lastEncoderProfile = null;
  publishStreamStatus('offline');
  return { ok: true, status: 'offline', recording: recording.recording };
});


function isTrustedStudioSender(event) {
  const frame = event.senderFrame;
  if (!frame || frame.parent !== null) return false;

  const isStudioDocument = (value) => {
    try {
      const actual = new URL(value);
      const expected = new URL(studioUrl);
      return actual.protocol === 'file:' &&
        actual.host === expected.host &&
        actual.pathname === expected.pathname;
    } catch {
      return false;
    }
  };

  return isStudioDocument(event.sender.getURL()) &&
    isStudioDocument(frame.url);
}

const { StreamiovChatHub } = require('./engine/chat-hub');
const { platformChatStatuses, resolveChatPermissions, connectedPlatformAdapters } = require('./engine/platform-chat-adapters');
const { TwitchChatReceiver } = require('./engine/twitch-chat-receiver');
const { TwitchEventSubReceiver } = require('./engine/twitch-eventsub-receiver');
const { ChatModeration } = require('./engine/chat-moderation');
const streamiovChatHub = new StreamiovChatHub();
const streamiovChatState = { chat: 'offline', tts: 'offline' };
let ttsAudioVerified = false;
const chatModeration = new ChatModeration({
  filePath: path.join(app.getPath('userData'), 'streamiov-chat-moderation.json')
});

function broadcastChatMessage(message) {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed() && !win.webContents.isDestroyed() && !win.webContents.isLoading()) {
      win.webContents.send('studio:chat-message', message);
    }
  }
}
function broadcastChatModeration(payload) {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed() && !win.webContents.isDestroyed() && !win.webContents.isLoading()) {
      win.webContents.send('studio:chat-moderation', payload);
    }
  }
}
function acceptChatMessage(message) {
  const decision = chatModeration.evaluate(message);
  if (!decision.allowed) {
    broadcastChatModeration({
      reason: decision.reason,
      word: decision.word || null,
      author: String(message?.author || 'Unbekannt').slice(0, 120),
      source: String(message?.source || 'unknown').slice(0, 40)
    });
    return false;
  }
  const result = streamiovChatHub.receive({ ...message, roles: decision.roles });
  if (result.accepted) broadcastChatMessage(result.message);
  return result.accepted;
}
const twitchChatReceiver = new TwitchChatReceiver({
  getOAuth: getTwitchOAuth,
  onMessage: message => {
    try { acceptChatMessage(message); } catch {}
  }
});
const twitchEventSubReceiver = new TwitchEventSubReceiver({
  getOAuth: getTwitchOAuth,
  onEvent: event => {
    try { acceptChatMessage(event); } catch {}
  }
});

function currentPlatformChatStatuses() {
  return platformChatStatuses({ getOAuth: getTwitchOAuth });
}
function moduleEventStatuses() {
  const irc = twitchChatReceiver.status();
  const events = twitchEventSubReceiver.status();
  const giftSubscribed = events.subscribed.includes('channel.subscription.gift');
  return {
    chat: Object.freeze({
      status: irc.connected ? 'twitch_irc_connected' : irc.state === 'connecting' ? 'twitch_irc_connecting' : 'twitch_irc_offline',
      note: irc.error ? String(irc.error).slice(0, 200) : 'Offizieller Twitch-IRC-WebSocket; nur bei connected sind Nachrichten eingegangen.'
    }),
    gift: Object.freeze({
      status: !giftSubscribed ? 'twitch_eventsub_gift_subs_not_subscribed'
        : events.connected ? 'twitch_eventsub_gift_subs_connected'
          : events.state === 'connecting' ? 'twitch_eventsub_gift_subs_connecting' : 'twitch_eventsub_gift_subs_offline',
      note: !giftSubscribed ? 'Kein bestätigtes EventSub-Abonnement für channel.subscription.gift.'
        : 'Nur bestätigte offizielle Twitch-Gift-Subscription-Ereignisse; kein Streamiov-Geschenkversand.'
    })
  };
}
function chatStateResponse() {
  const snapshot = streamiovChatHub.snapshot();
  const platformChat = currentPlatformChatStatuses();
  const connectedAdapters = connectedPlatformAdapters(platformChat);
  return { ok: true, chat: streamiovChatState.chat, tts: streamiovChatState.tts,
    message_count: snapshot.messageCount, messages: snapshot.messages,
    connected_adapters: connectedAdapters,
    external_platform_connected: connectedAdapters.length > 0,
    platform_chat: platformChat, irc_chat: twitchChatReceiver.status(),
    eventsub: twitchEventSubReceiver.status(), moderation: chatModeration.snapshot(),
    tts_audio_verified: ttsAudioVerified };
}

ipcMain.handle('studio:chat-action', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const action = payload.action;
  if (action === 'status') {
    return chatStateResponse();
  }
  if (action === 'connect-platform') {
    if (payload.platform !== 'twitch') {
      return { ok: false, error: 'Eingehender Plattform-Chat ist derzeit nur über Twitch IRC verfügbar.' };
    }
    try {
      if (streamiovChatState.chat !== 'online') streamiovChatState.chat = 'online';
      await twitchChatReceiver.start();
      return chatStateResponse();
    } catch (error) { return { ok: false, error: String(error?.message || error), ...chatStateResponse() }; }
  }
  if (action === 'disconnect-platform') {
    twitchChatReceiver.stop();
    return chatStateResponse();
  }
  if (action === 'connect-events') {
    if (payload.platform !== 'twitch') {
      return { ok: false, error: 'Eingehende Plattformereignisse sind derzeit nur über Twitch EventSub verfügbar.' };
    }
    try {
      if (streamiovChatState.chat !== 'online') streamiovChatState.chat = 'online';
      await twitchEventSubReceiver.start();
      return chatStateResponse();
    } catch (error) { return { ok: false, error: String(error?.message || error), ...chatStateResponse() }; }
  }
  if (action === 'disconnect-events') {
    twitchEventSubReceiver.stop();
    return chatStateResponse();
  }
  if (action === 'moderation-status') {
    return { ok: true, moderation: chatModeration.snapshot() };
  }
  if (action === 'moderation-set') {
    try {
      if (Array.isArray(payload.blockedWords)) chatModeration.setBlockedWords(payload.blockedWords);
      if (Array.isArray(payload.bannedUsers)) chatModeration.setBannedUsers(payload.bannedUsers);
      if (payload.slowModeSeconds !== undefined) chatModeration.setSlowMode(payload.slowModeSeconds);
      if (payload.permissions) chatModeration.setRolePermissions(payload.permissions);
      return { ok: true, moderation: chatModeration.snapshot() };
    } catch (error) { return { ok: false, error: String(error?.message || error), moderation: chatModeration.snapshot() }; }
  }
  if (action === 'moderation-ban') {
    try { return { ok: true, moderation: chatModeration.ban({ source: payload.platform, author: payload.author }) }; }
    catch (error) { return { ok: false, error: String(error?.message || error), moderation: chatModeration.snapshot() }; }
  }
  if (action === 'moderation-unban') {
    try { return { ok: true, moderation: chatModeration.unban({ source: payload.platform, author: payload.author }) }; }
    catch (error) { return { ok: false, error: String(error?.message || error), moderation: chatModeration.snapshot() }; }
  }
  if (action === 'toggle-chat') {
    streamiovChatState.chat = streamiovChatState.chat === 'online' ? 'offline' : 'online';
    if (streamiovChatState.chat === 'offline') {
      twitchChatReceiver.stop();
      twitchEventSubReceiver.stop();
    }
  } else if (action === 'toggle-tts') {
    streamiovChatState.tts = streamiovChatState.tts === 'online' ? 'offline' : 'online';
  } else if (action === 'receive') {
    if (streamiovChatState.chat !== 'online') return { ok: false, error: 'Chat ist ausgeschaltet.' };
    try { acceptChatMessage({ source: 'local_test', author: 'Lokaler Test', text: payload.text, channel: 'Studio' }); }
    catch (error) { return { ok: false, error: error.message }; }
  } else if (action === 'send') {
    if (streamiovChatState.chat !== 'online') return { ok: false, error: 'Chat ist ausgeschaltet.' };
    if (!chatModeration.can(String(payload.role || 'broadcaster'), 'send')) return { ok: false, error: 'Die ausgewählte Rolle darf nicht in den Plattform-Chat senden.' };
    try {
      const statuses = currentPlatformChatStatuses();
      const result = await streamiovChatHub.send({
        text: payload.text, targets: payload.targets,
        permissions: resolveChatPermissions(statuses)
      });
      return { ...result, results: result.results.map(item =>
        item.platform === 'tiktok' && !item.ok ? { ...item, error: statuses.tiktok.error } : item) };
    } catch (error) { return { ok: false, error: error.message }; }
  } else if (action === 'speak') {
    ttsAudioVerified = false;
    const text = typeof payload.text === 'string' ? payload.text.trim() : '';
    if (!text || text.length > 1000) return { ok: false, error: 'TTS-Text muss 1–1000 Zeichen lang sein.' };
    if (streamiovChatState.tts !== 'online') return { ok: false, error: 'TTS ist ausgeschaltet.' };
    if (!chatModeration.can(String(payload.role || 'broadcaster'), 'speak')) return { ok: false, error: 'Die ausgewählte Rolle darf keine Sprachausgabe auslösen.' };
    const speed = Number(payload.speed ?? 175);
    const amplitude = Number(payload.amplitude ?? 100);
    if (!Number.isInteger(speed) || speed < 80 || speed > 300) return { ok: false, error: 'TTS-Geschwindigkeit muss zwischen 80 und 300 Wörtern pro Minute liegen.' };
    if (!Number.isInteger(amplitude) || amplitude < 0 || amplitude > 100) return { ok: false, error: 'TTS-Sprachlautstärke muss zwischen 0 und 100 liegen.' };
    const outputFile = path.join(os.tmpdir(), 'streamiov-tts-' + randomUUID() + '.wav');
    try {
      try {
        await execFileAsync('espeak-ng', ['-v', 'de', '-s', String(speed), '-a', String(amplitude), '-w', outputFile, text], { timeout: 60000, windowsHide: true });
      } catch (error) {
        if (process.platform !== 'win32' || error.code !== 'ENOENT') throw error;
        await synthesizeWindowsSpeech({ text, outputFile, speed, amplitude });
      }
      const audio = await fs.readFile(outputFile);
      if (!audio.length || audio.length > 8 * 1024 * 1024) return { ok: false, error: 'TTS-Audiodatei ist leer oder überschreitet das lokale Größenlimit.' };
      if (!isWavBuffer(audio)) return { ok: false, error: 'TTS-Ausgabe ist keine gültige WAV-Datei.', tts_audio_verified: false };
      ttsAudioVerified = true;
      return {
        ok: true, chat: streamiovChatState.chat, tts: streamiovChatState.tts,
        audio_base64: audio.toString('base64'), audio_mime: 'audio/wav',
        tts_audio_verified: true
      };
    } catch (error) {
      return { ok: false, error: error.code === 'ENOENT' ? 'espeak-ng ist auf diesem Gerät nicht verfügbar.' : 'Sprachausgabe fehlgeschlagen: ' + (error.message || 'unbekannter Fehler'), tts_audio_verified: false };
    } finally {
      await fs.unlink(outputFile).catch(() => {});
    }
  } else { return { ok: false, error: 'Unbekannte Chat-Aktion.' }; }
  return chatStateResponse();
});

// Dauerhafte lokale Szenenverwaltung. Keine Videoausgabe oder Plattformaktion.
ipcMain.handle('studio:scene-action', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const file = path.join(app.getPath('userData'), 'streamiov-scenes.json');
  let savedState = {};

  try {
    savedState = JSON.parse(await fs.readFile(file, 'utf8'));
  } catch (error) {
    if (error.code !== 'ENOENT') {
      return { ok: false, error: 'Szenendatei konnte nicht gelesen werden: ' + String(error.message || error) };
    }
  }

  const engine = new StudioSceneEngine(savedState);

  const action = payload && payload.action;
  if (action === 'export-scenes') return engine.exportScenePack(payload.sceneIds);
  let result;
  if (action === 'load') {
    return { ok: true, state: engine.snapshot() };
  } else if (action === 'select') {
    result = engine.selectPreview(payload.id || payload.name);
  } else if (action === 'take') {
    result = engine.take(payload.transition);
  } else if (action === 'set-transition') {
    result = engine.setTransition(payload.transition);
  } else if (action === 'set-overlay') {
    result = engine.setOverlay(payload.overlay);
  } else if (action === 'set-scene-dependencies') {
    result = engine.setSceneDependencies(payload.id || payload.sceneId, payload.dependsOn);
  } else if (action === 'set-program') {
    result = engine.setProgramScene(payload.id || payload.name);
  } else if (action === 'create') {
    result = engine.createScene(payload.name);
  } else if (action === 'rename-scene') {
    result = engine.renameScene(payload.id, payload.name);
  } else if (action === 'delete-scene') {
    result = engine.deleteScene(payload.id);
  } else if (action === 'duplicate-scene') {
    result = engine.duplicateScene(payload.id);
  } else if (action === 'reorder-scenes') {
    result = engine.reorderScenes(payload.order);
  } else if (action === 'import-scene-pack') {
    result = engine.importScenePack(payload.pack);
  } else if (action === 'add-source') {
    result = engine.addSource(payload.source || {});
  } else if (action === 'update-source') {
    result = engine.updateSource(payload.sourceId, payload.patch || {}, payload.sceneId);
  } else if (action === 'remove-source') {
    result = engine.removeSource(payload.sourceId);
  } else if (action === 'move-source') {
    result = engine.moveSource(payload.sourceId, payload.direction);
  } else if (action === 'set-background') {
    result = engine.setBackground(payload.color);
  } else {
    return { ok: false, error: 'Unbekannte Szenenaktion.' };
  }

  if (!result.ok) return result;
  if (programOutputWindow && !programOutputWindow.isDestroyed()) {
    publishProgramScene(result.state);
  }

  try {
    const directory = path.dirname(file);
    await fs.mkdir(directory, { recursive: true });
    const temporary = file + '.' + randomUUID() + '.tmp';
    await fs.writeFile(temporary, JSON.stringify(engine.toJSON(), null, 2), { mode: 0o600 });
    await fs.rename(temporary, file);
  } catch (error) {
    return { ok: false, error: 'Szenen konnten nicht gespeichert werden: ' + String(error.message || error).slice(0, 180) };
  }
  return { ok: true, state: engine.snapshot() };
});

ipcMain.handle('studio:game-analysis', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  try {
    const action = String(payload.action || 'snapshot');
    if (action === 'processes') {
      return { ok: true, processes: await listRunningProcesses(), snapshot: gameAnalysis.snapshot() };
    }
    if (action === 'detect') {
      if (!Array.isArray(payload.games)) throw new Error('Prozessliste fehlt.');
      return { ok: true, snapshot: gameAnalysis.detect(payload.games, { automatic: payload.automatic === true }) };
    }
    if (action === 'auto-detection') return { ok: true, snapshot: gameAnalysis.setAutoDetection(payload) };
    if (action === 'session-start') return { ok: true, snapshot: gameAnalysis.startSession(payload.id) };
    if (action === 'session-stop') return { ok: true, snapshot: gameAnalysis.stopSession(payload.id) };
    if (action === 'observe') return gameAnalysis.observe(payload);
    if (action === 'frame') return gameAnalysis.frame(payload);
    if (action === 'situations') return gameAnalysis.situations(payload.id);
    if (action === 'stats') return gameAnalysis.stats(payload.id);
    if (action === 'strategy') return gameAnalysis.strategy(payload.id);
    if (action === 'profile') return gameAnalysis.profile(payload.id, payload);
    if (action === 'voice') return gameAnalysis.voice(payload.id, payload.text);
    if (action === 'replay-import') return gameAnalysis.replayImport(payload);
    if (action === 'assistant') return gameAnalysis.assistant(payload.id);
    if (action === 'replay') return gameAnalysis.replay(payload.id);
    return { ok: true, snapshot: gameAnalysis.snapshot() };
  } catch (error) {
    return { ok: false, error: String(error.message || error).slice(0, 220) };
  }
});


// Dauerhafte Verwaltung von Quellen-Metadaten. Diese IPC-Stelle ist
// bewusst metadata-only: echte Medien-Tracks öffnet die Regie lokal, und
// der Encoder erhält ausschließlich den komponierten Programm-Mediastream.
ipcMain.handle('studio:source-action', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const file = path.join(app.getPath('userData'), 'streamiov-sources.json');
  let saved = { version: 1, sources: [] };
  try {
    saved = JSON.parse(await fs.readFile(file, 'utf8'));
  } catch (error) {
    if (error.code !== 'ENOENT') {
      return { ok: false, error: 'Quelldatei konnte nicht gelesen werden: ' + String(error.message || error).slice(0, 180) };
    }
  }

  const model = new StudioSourceModel(saved);
  const action = payload && payload.action;
  if (action === 'load') {
    return { ok: true, state: model.snapshot(), metadata_only: true };
  }

  let result;
  if (action === 'add') {
    result = model.add(payload.source || {});
  } else if (action === 'update') {
    result = model.update(payload.id, payload.patch || {});
  } else if (action === 'remove') {
    result = model.remove(payload.id);
  } else if (action === 'reorder') {
    result = model.reorder(payload.ids);
  } else {
    return { ok: false, error: 'Unbekannte Quellenaktion.' };
  }

  if (!result.ok) return result;

  try {
    await fs.mkdir(path.dirname(file), { recursive: true });
    const temporary = file + '.' + randomUUID() + '.tmp';
    await fs.writeFile(temporary, JSON.stringify(model.toJSON(), null, 2), { mode: 0o600 });
    await fs.rename(temporary, file);
  } catch (error) {
    return { ok: false, error: 'Quellen konnten nicht gespeichert werden: ' + String(error.message || error).slice(0, 180) };
  }

  return { ok: true, state: model.snapshot(), metadata_only: true };
});



async function probeExecutable(command, args = ['--version']) {
  try {
    const result = await execFileAsync(command, args, {
      timeout: 8000,
      windowsHide: true,
      maxBuffer: 256 * 1024
    });
    return {
      available: true,
      version: String(result.stdout || result.stderr || '').trim().split(String.fromCharCode(10)).slice(0, 2).join(' ').slice(0, 240)
    };
  } catch (error) {
    return {
      available: false,
      reason: error.code === 'ENOENT' ? 'not_installed_or_not_in_PATH' : String(error.message || error).slice(0, 180)
    };
  }
}

async function probeGStreamerPlugin(plugin) {
  try {
    await execFileAsync('gst-inspect-1.0', [plugin], {
      timeout: 8000,
      windowsHide: true,
      maxBuffer: 256 * 1024
    });
    return { available: true };
  } catch (error) {
    return { available: false, reason: error.code === 'ENOENT' ? 'gstreamer_not_installed' : 'plugin_not_available' };
  }
}

async function probeFfmpegRtmp() {
  const executable = resolveFfmpegExecutable({
    resourcesPath: process.resourcesPath,
    appPath: app.getAppPath(),
    platform: process.platform,
    env: process.env
  });
  try {
    const [{ stdout: encoders }, { stdout: protocols }] = await Promise.all([
      execFileAsync(executable, ['-hide_banner', '-encoders'], {
        timeout: 10000, windowsHide: true, maxBuffer: 1024 * 1024
      }),
      execFileAsync(executable, ['-hide_banner', '-protocols'], {
        timeout: 10000, windowsHide: true, maxBuffer: 1024 * 1024
      })
    ]);
    const video = /\blibx264\b/.test(encoders);
    const audio = /\baac\b/.test(encoders);
    const rtmp = /(?:^|\s)rtmp(?:s)?(?:\s|$)/m.test(protocols);
    return {
      available: video && audio && rtmp,
      ffmpeg_available: true,
      executable,
      video_encoder_available: video,
      audio_encoder_available: audio,
      rtmp_protocol_available: rtmp,
      missing: [
        ...(!video ? ['libx264'] : []),
        ...(!audio ? ['AAC'] : []),
        ...(!rtmp ? ['RTMP/RTMPS'] : [])
      ]
    };
  } catch (error) {
    return {
      available: false,
      ffmpeg_available: false,
      executable,
      video_encoder_available: false,
      audio_encoder_available: false,
      rtmp_protocol_available: false,
      missing: [error.code === 'ENOENT' ? 'FFmpeg' : 'FFmpeg-Prüfung fehlgeschlagen']
    };
  }
}

ipcMain.handle('studio:get-runtime-diagnostics', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const [gstInspect, gstLaunch] = await Promise.all([
    probeExecutable('gst-inspect-1.0'),
    probeExecutable('gst-launch-1.0')
  ]);
  // Use the exact same packaged/override/PATH resolution for diagnostics
  // and streaming. A bundled FFmpeg must not appear missing just because it
  // is not separately installed on the user's system PATH.
  const rtmp = await probeFfmpegRtmp();
  const ffmpeg = {
    available: rtmp.ffmpeg_available,
    executable: rtmp.executable
  };

  let plugins = {};
  if (gstInspect.available) {
    const names = ['videotestsrc', 'audiotestsrc', 'vp8enc', 'vorbisenc', 'webmmux', 'x264enc', 'rtmpsink'];
    const results = await Promise.all(names.map(async name => [name, await probeGStreamerPlugin(name)]));
    plugins = Object.fromEntries(results);
  }

  return {
    ok: true,
    platform: process.platform,
    runtime: {
      gstreamer_inspect: gstInspect,
      gstreamer_launch: gstLaunch,
      ffmpeg
    },
    plugins,
    local_test_sources_available: Boolean(plugins.videotestsrc?.available && plugins.audiotestsrc?.available),
    media_test_pipeline_available: Boolean(plugins.videotestsrc?.available && plugins.audiotestsrc?.available && plugins.vp8enc?.available && plugins.vorbisenc?.available && plugins.webmmux?.available),
    ffmpeg_rtmp: rtmp,
    rtmp_pipeline_dependencies_available: rtmp.available,
    missing_rtmp_dependencies: rtmp.missing,
    camera_screen_rtmp_implemented: true,
    screen_camera_compositing_implemented: true,
    named_scene_switching_implemented: true,
    live_stream_verified: false,
    note: 'Dies ist eine Abhängigkeitsprüfung. Gerätezugriff, Encoder-Pipeline, Plattformautorisierung und Live-Ausgabe sind damit nicht getestet.'
  };
});

/**
 * STREAMIOV_TIKTOK_STUDIO_BRIDGE
 * Native Electron OAuth callback. Credentials are read only from process.env;
 * tokens are handled by the encrypted OAuth service in the main process.
 */
let TikTokOAuthClass = null;
let tikTokOAuthLoadError = null;
let tikTokOAuth = null;
let tikTokCallbackServer = null;
let tikTokCallbackTimeout = null;
let tikTokConnectInProgress = false;

function getTikTokOAuth() {
  if (tikTokOAuthLoadError) throw new Error(tikTokOAuthLoadError);
  if (!TikTokOAuthClass) {
    try {
      TikTokOAuthClass = require('./tiktok-oauth.js').TikTokOAuth;
      if (typeof TikTokOAuthClass !== 'function') throw new TypeError('TikTokOAuth export missing');
    } catch {
      tikTokOAuthLoadError = 'tiktok_oauth_service_unavailable';
      throw new Error(tikTokOAuthLoadError);
    }
  }
  if (!tikTokOAuth) {
    tikTokOAuth = new TikTokOAuthClass({
      environment: 'sandbox',
      env: process.env,
      tokenFile: path.join(app.getPath('userData'), 'oauth', 'tiktok-sandbox.json')
    });
  }
  return tikTokOAuth;
}

function sendTikTokAuthResult(result) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('studio:tiktok-auth-result', result);
  }
}

ipcMain.handle('studio:tiktok-status', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  try {
    return { ok: true, environment: 'sandbox', ...getTikTokOAuth().status() };
  } catch (error) {
    return {
      ok: false,
      status: error.message === 'tiktok_oauth_service_unavailable' ? error.message : 'configuration_required',
      environment: 'sandbox',
      error: String(error.message || error)
    };
  }
});

ipcMain.handle('studio:tiktok-prepare-output', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  try {
    const credentials = await getTikTokOAuth().getStreamCredentials();
    const destination = normalizePlatformDestination(credentials);
    if (!destination) throw new Error('tiktok_live_ingest_invalid');
    preparePlatformOutput('tiktok', 'TikTok-Ausgabe bereit; LIVE nicht bestätigt.');
    return { ok: true, platform: 'tiktok', status: 'ready', ingestUrl: parseRtmpUrl(destination)?.origin || null };
  } catch (error) {
    transitionPlatformOutput('tiktok', 'error', 'TikTok-Ausgabe konnte nicht vorbereitet werden.');
    return { ok: false, platform: 'tiktok', status: 'blocked', error: String(error.message || error) };
  }
});

ipcMain.handle('studio:tiktok-connect', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (tikTokConnectInProgress) return { ok: false, error: 'TikTok-Anmeldung läuft bereits.' };

  let oauth;
  try {
    oauth = getTikTokOAuth();
    const authorization = oauth.createAuthorizationUrl();
    const redirect = new URL(process.env.STREAMIOV_TIKTOK_SANDBOX_REDIRECT_URI);
    if (redirect.hostname !== '127.0.0.1' || redirect.protocol !== 'http:' ||
        !redirect.port || redirect.pathname !== '/callback' || redirect.search || redirect.hash) {
      throw new Error('TikTok-Sandbox-Callback muss exakt http://127.0.0.1:<Port>/callback sein.');
    }

    if (tikTokCallbackServer) {
      await new Promise(resolve => tikTokCallbackServer.close(resolve));
      tikTokCallbackServer = null;
    }

    tikTokConnectInProgress = true;
    tikTokCallbackServer = http.createServer(async (request, response) => {
      const callbackUrl = new URL(request.url, 'http://127.0.0.1');
      if (request.method !== 'GET' || callbackUrl.pathname !== '/callback') {
        response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        response.end('Nicht gefunden');
        return;
      }
      try {
        const result = await oauth.callback({
          code: callbackUrl.searchParams.get('code'),
          state: callbackUrl.searchParams.get('state'),
          error: callbackUrl.searchParams.get('error')
        });
        response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
        response.end('<!doctype html><html lang="de"><meta charset="utf-8"><title>STREAMIOV</title><body><h1>TikTok verbunden</h1><p>Du kannst dieses Fenster schließen und zu STREAMIOV Studio zurückkehren.</p></body></html>');
        sendTikTokAuthResult({ ok: true, ...result });
      } catch (error) {
        response.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
        response.end('<!doctype html><html lang="de"><meta charset="utf-8"><title>STREAMIOV</title><body><h1>Anmeldung fehlgeschlagen</h1><p>Bitte zu STREAMIOV Studio zurückkehren.</p></body></html>');
        sendTikTokAuthResult({ ok: false, error: String(error.message || error) });
      } finally {
        if (tikTokCallbackTimeout) clearTimeout(tikTokCallbackTimeout);
        tikTokCallbackTimeout = null;
        tikTokConnectInProgress = false;
        const server = tikTokCallbackServer;
        tikTokCallbackServer = null;
        if (server) server.close();
      }
    });
    await new Promise((resolve, reject) => {
      tikTokCallbackServer.once('error', reject);
      tikTokCallbackServer.listen(Number(redirect.port), '127.0.0.1', resolve);
    });
    tikTokCallbackTimeout = setTimeout(() => {
      tikTokConnectInProgress = false;
      const server = tikTokCallbackServer;
      tikTokCallbackServer = null;
      if (server) server.close();
      sendTikTokAuthResult({ ok: false, error: 'oauth_state_expired' });
    }, 600000);
    if (typeof tikTokCallbackTimeout.unref === 'function') tikTokCallbackTimeout.unref();
    await shell.openExternal(authorization.url);
    return { ok: true, status: 'authorization_opened', environment: 'sandbox' };
  } catch (error) {
    if (tikTokCallbackTimeout) clearTimeout(tikTokCallbackTimeout);
    tikTokCallbackTimeout = null;
    tikTokConnectInProgress = false;
    if (tikTokCallbackServer) {
      try { tikTokCallbackServer.close(); } catch {}
      tikTokCallbackServer = null;
    }
    return { ok: false, error: String(error.message || error) };
  }
});

ipcMain.handle('studio:tiktok-disconnect', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  try {
    const result = await getTikTokOAuth().disconnect();
    sendTikTokAuthResult({ ok: true, ...result });
    return result;
  } catch (error) {
    return { ok: false, error: String(error.message || error) };
  }
});



/** Official Twitch account connection and on-demand Helix stream-key retrieval. */
const { TwitchOAuth } = require('./twitch-oauth.js');
const { createTwitchChatAdapter } = require('./engine/platform-chat-adapters');
let twitchOAuth = null;
let twitchCallbackServer = null;
let twitchCallbackTimeout = null;
let twitchConnectInProgress = false;
function getTwitchOAuth() {
  if (!twitchOAuth) twitchOAuth = new TwitchOAuth({
    env: process.env,
    tokenFile: path.join(app.getPath('userData'), 'oauth', 'twitch.json'),
    fetch
  });
  return twitchOAuth;
}
streamiovChatHub.registerAdapter('twitch', createTwitchChatAdapter({ getOAuth: getTwitchOAuth }));
function sendTwitchAuthResult(result) {
  if (result?.ok === false || result?.status === 'disconnected') {
    transitionPlatformOutput('twitch', 'offline', result?.error ? String(result.error) : 'Twitch-Ausgabe nicht verbunden.');
  }
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('studio:twitch-auth-result', result);
}
ipcMain.handle('studio:twitch-status', (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  try { return { ok: true, ...getTwitchOAuth().status() }; }
  catch (error) { return { ok: false, status: 'configuration_required', error: String(error.message || error) }; }
});
ipcMain.handle('studio:twitch-connect', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (twitchConnectInProgress) return { ok: false, error: 'Twitch-Anmeldung läuft bereits.' };
  try {
    const oauth = getTwitchOAuth();
    const authorization = oauth.createAuthorizationUrl({ chat: payload?.chat === true, events: payload?.events === true });
    const redirect = new URL(oauth.redirectUri);
    if (redirect.protocol !== 'http:' || redirect.hostname !== '127.0.0.1' || !redirect.port ||
        redirect.pathname !== '/callback' || redirect.search || redirect.hash) throw new Error('Ungültiger Twitch-Loopback-Callback.');
    if (twitchCallbackServer) { await new Promise(resolve => twitchCallbackServer.close(resolve)); twitchCallbackServer = null; }
    twitchConnectInProgress = true;
    twitchCallbackServer = http.createServer(async (request, response) => {
      const callbackUrl = new URL(request.url, 'http://127.0.0.1');
      if (request.method !== 'GET' || callbackUrl.pathname !== '/callback') {
        response.writeHead(404); response.end('Nicht gefunden'); return;
      }
      try {
        const result = await oauth.callback({ code: callbackUrl.searchParams.get('code'), state: callbackUrl.searchParams.get('state'), error: callbackUrl.searchParams.get('error') });
        if (result?.ok === false) {
          response.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
          response.end('<!doctype html><html lang="de"><meta charset="utf-8"><title>Streamiov</title><body><h1>OAuth-Berechtigung erforderlich</h1><p>Deine bestehende Twitch-Verbindung wurde nicht verändert. Bitte zu Streamiov zurückkehren.</p></body></html>');
          sendTwitchAuthResult({ ok: false, status: result.status, error: result.error });
          return;
        }
        response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
        response.end('<!doctype html><html lang="de"><meta charset="utf-8"><title>Streamiov</title><body><h1>Twitch verbunden</h1><p>Du kannst dieses Fenster schließen.</p></body></html>');
        sendTwitchAuthResult({ ok: true, ...result });
      } catch (error) {
        response.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
        response.end('<!doctype html><html lang="de"><meta charset="utf-8"><title>Streamiov</title><body><h1>Twitch-Anmeldung fehlgeschlagen</h1><p>Bitte zu Streamiov zurückkehren.</p></body></html>');
        sendTwitchAuthResult({ ok: false, error: String(error.message || error) });
      } finally {
        if (twitchCallbackTimeout) clearTimeout(twitchCallbackTimeout);
        twitchCallbackTimeout = null; twitchConnectInProgress = false;
        const server = twitchCallbackServer; twitchCallbackServer = null; if (server) server.close();
      }
    });
    await new Promise((resolve, reject) => { twitchCallbackServer.once('error', reject); twitchCallbackServer.listen(Number(redirect.port), '127.0.0.1', resolve); });
    twitchCallbackTimeout = setTimeout(() => {
      twitchConnectInProgress = false; const server = twitchCallbackServer; twitchCallbackServer = null;
      if (server) server.close(); sendTwitchAuthResult({ ok: false, error: 'twitch_oauth_timeout' });
    }, 600000);
    if (typeof twitchCallbackTimeout.unref === 'function') twitchCallbackTimeout.unref();
    transitionPlatformOutput('twitch', 'authorizing', 'Twitch-Anmeldung im Browser wurde geöffnet.');
    await shell.openExternal(authorization.url);
    return { ok: true, status: 'authorization_opened' };
  } catch (error) {
    if (twitchCallbackTimeout) clearTimeout(twitchCallbackTimeout);
    twitchCallbackTimeout = null; twitchConnectInProgress = false;
    transitionPlatformOutput('twitch', 'offline', 'Twitch-Anmeldung konnte nicht gestartet werden.');
    if (twitchCallbackServer) { try { twitchCallbackServer.close(); } catch {} twitchCallbackServer = null; }
    return { ok: false, error: String(error.message || error) };
  }
});
ipcMain.handle('studio:twitch-disconnect', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  try { const result = await getTwitchOAuth().disconnect(); sendTwitchAuthResult({ ok: true, ...result }); return result; }
  catch (error) {
    transitionPlatformOutput('twitch', 'offline', 'Twitch-Verbindung konnte nicht getrennt werden.');
    return { ok: false, error: String(error.message || error) };
  }
});
ipcMain.handle('studio:twitch-prepare-output', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  try {
    const credentials = await getTwitchOAuth().getStreamCredentials();
    preparePlatformOutput('twitch', 'Twitch-Ausgabe bereit; LIVE nicht bestätigt.');
    // Keep the stream key in the main process. Never return it to the renderer.
    return { ok: true, platform: 'twitch', status: 'ready', ingestUrl: credentials.ingestUrl };
  } catch (error) {
    transitionPlatformOutput('twitch', 'error', 'Twitch-Ausgabe konnte nicht vorbereitet werden.');
    return { ok: false, platform: 'twitch', status: 'blocked', error: String(error.message || error) };
  }
});

// Crostini-Kompatibilität: GPU-Beschleunigung vor app.whenReady deaktivieren.
app.disableHardwareAcceleration();

ipcMain.handle('studio:get-module-status', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const encoder = await probeFfmpegRtmp();
  const registry = platformOutputRegistry.snapshot();
  const liveConfirmed = LIVE_PLATFORMS.some(platform => registry[platform]?.liveConfirmed === true);
  const incomingEvents = moduleEventStatuses();

  return {
    ok: true,
    verification: 'local_runtime_capability_inventory',
    live_stream_verified: liveConfirmed,
    modules: [
      { id: 'scene-engine', status: 'automated_tested', note: 'Preview/Program-Zustand und TAKE; Programmszene wird im Renderer gerendert.' },
      { id: 'source-model', status: 'automated_tested', note: 'Quellen-Metadaten, Aufnahmeauflösung, Bildrate, Lautstärke, Stumm und Kamera-Audio-Opt-in werden lokal validiert und gespeichert.' },
      { id: 'local-camera-preview', status: 'renderer_local_only', note: 'Kamera-, Bildschirm-, Fenster- und Medienquellen laufen im Renderer, werden in die Programmszene gezeichnet und mit ihren echten Medien-Tracks in den Stream-Bus geroutet.' },
      { id: 'synthetic-av-test', status: 'dependency_gated', note: 'Lokaler Test mit installierten GStreamer-Komponenten.' },
      { id: 'compositor', status: 'renderer_canvas_program_output', note: 'Die Programmszene wird mit festem Frame-Takt aus echten Quell-Tracks gerendert und als WebM-Mediastream an den lokalen Encoder gesendet.' },
      { id: 'local-recording', status: 'local_webm_file', note: 'Der komponierte WebM-Mediastream kann ohne RTMP und zusätzlich während eines aktiven Streams als lokale Datei im Benutzerprofil aufgezeichnet, aufgelistet, geöffnet und gelöscht werden; es erfolgt kein Upload und keine Plattformveröffentlichung.' },
      { id: 'production-encoder', status: encoder.available ? 'ffmpeg_available' : 'ffmpeg_missing', note: encoder.available ? `FFmpeg ${encoder.executable} mit libx264, AAC und RTMP/RTMPS ist verfügbar.` : 'Fehlend: ' + encoder.missing.join(', ') + '.' },
      { id: 'stream-telemetry', status: 'local_write_telemetry', note: 'Für jeden aktiven Ausgang werden echte, an den Encoder geschriebene Medienblöcke, Bytes, Wiederholungen, Backpressure-Fehler und eine lokale Bitraten-Schätzung erfasst. Status „degraded“/„stalled“ beschreibt ausschließlich die lokale Schreibverbindung; LIVE bleibt nur nach remote bestätigter Plattformmeldung wahr. Encoderprofile steuern Preset, Tune und Keyframe-Abstand.' },
      { id: 'audio-mixer-routing', status: 'local_four_bus_engine', note: 'Mikrofon, Bildschirm-Systemton, lokaler Musikplayer, Soundboard-Pads, deutsches TTS und manuelle Alert-Töne werden über getrennte Stream-, Monitor-, Kopfhörer- und Kommunikationsbusse geroutet. Jeder Ausgang besitzt einen Limiter; ein plattformneutraler Geräteadapter übernimmt Geräteinventar, Mikrofonöffnung, Ausgabeverbindung und Hot-plug-Beobachtung. Mikrofon bietet Hochpass, optionalen Sprachkompressor, Noise Gate/Expander mit Hysterese, Pan, Solo und konfigurierbare OS-Echo-/Rauschunterdrückung sowie automatische Pegelregelung. Live-RMS-/Peak-Meter zeigen Quellen- und Stream-Ausgangspegel samt Clipping-Hinweis. Der Stream-Bus speist den lokalen MediaRecorder/Encoder-Eingang. Spiel-/Fensterton wird über den ausgewählten Capture-Track aufgenommen, sofern Windows/Electron einen Loopback-Audiotrack liefert; separate App-Audio-Kanäle und Voice-Räume bleiben ohne autorisiertes Geräte-/Dienstinterface. Bestätigte Twitch-Chat- und EventSub-Ereignisse lösen lokal gespeicherte Alertregeln aus, ohne Plattformereignisse zu erfinden. TTS nutzt espeak-ng, wenn vorhanden, und unter Windows zusätzlich die native System.Speech-Fallback-Ausgabe. Physische Geräteausgabe und LIVE-Übertragung sind nicht hardwareverifiziert.' },
      { id: 'tiktok-live-output', status: registry.tiktok?.state === 'live' ? 'remote_live_confirmed' : 'rtmp_transport_ready', note: 'RTMP-Transport und getrennter Encoder sind integriert; LIVE gilt nur nach remote bestätigter Plattformmeldung.' },
      { id: 'chat-events', status: incomingEvents.chat.status, note: incomingEvents.chat.note },
      { id: 'gift-events', status: incomingEvents.gift.status, note: incomingEvents.gift.note },
      { id: 'music-mixing', status: 'local_file_stream_mix', note: 'Lokale Musikdatei und Sitzung-Queue werden über eine eigene Web-Audio-Quelle in Stream- und Monitor-Bus geroutet; Fader und Mute bleiben unabhängig. Ein rechtlich freigegebener Musik-Katalog und automatische Playlist-Synchronisierung sind noch nicht vollständig umgesetzt.' }
    ]
  };

});

ipcMain.handle('studio:get-stream-status', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  return {
    ok: true,
    status: liveStreamState,
    active: liveOutputManager.isActive(),
    stopping: liveStreamState === 'stopping',
    platforms: liveOutputManager.activePlatforms(),
    outputs: liveOutputManager.snapshot(),
    health: liveOutputManager.healthSnapshot(),
    encoderProfile: lastEncoderProfile,
    registry: platformOutputRegistry.snapshot(),
    recording: recordingSnapshot(),
    programFramesDelivered
  };
});

ipcMain.handle('studio:get-status', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const encoder = await probeFfmpegRtmp();
  const registry = platformOutputRegistry.snapshot();
  const active = liveOutputManager.isActive();
  const liveConfirmed = LIVE_PLATFORMS.some(platform => registry[platform]?.liveConfirmed === true);
  return {
    ok: true,
    bridge: 'ready',
    backend: {
      connected: true,
      state: 'studio_runtime_ready',
      engine: {
        name: 'STREAMIOV Studio Runtime',
        scene_engine: 'available',
        source_metadata_store: 'available',
        compositor: 'renderer_canvas_program_output',
        encoder: encoder.available ? 'ffmpeg_h264_aac_rtmp' : 'ffmpeg_missing',
        output_connected: active,
        output_active: active,
        live_stream_verified: liveConfirmed
      },
      note: 'Lokale Programmszene, FFmpeg-Encoder und getrennte RTMP-Ausgänge sind integriert; LIVE gilt nur nach Remote-Bestätigung.'
    }
  };

});

ipcMain.handle('studio:run-media-test', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const requiredPlugins = ['videotestsrc', 'audiotestsrc', 'vp8enc', 'vorbisenc', 'webmmux'];
  const gstLaunch = await probeExecutable('gst-launch-1.0');
  if (!gstLaunch.available) {
    return {
      ok: false,
      stage: 'dependencies',
      missing: ['gst-launch-1.0'],
      device_capture_verified: false,
      live_stream_verified: false
    };
  }

  const pluginResults = await Promise.all(
    requiredPlugins.map(async (name) => [name, await probeGStreamerPlugin(name)])
  );
  const missing = pluginResults.filter(([, result]) => !result.available).map(([name]) => name);
  if (missing.length) {
    return {
      ok: false,
      stage: 'dependencies',
      missing,
      device_capture_verified: false,
      live_stream_verified: false
    };
  }

  let testDirectory;
  try {
    testDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'streamiov-av-smoke-'));
    const outputFile = path.join(testDirectory, 'audio-video-smoke-test.webm');
    const args = buildSyntheticAvPipelineArgs(outputFile);

    await execFileAsync('gst-launch-1.0', args, {
      timeout: 45000,
      windowsHide: true,
      maxBuffer: 512 * 1024
    });

    const result = await fs.stat(outputFile);
    if (!result.isFile() || result.size < 1024) {
      throw new Error('Die erzeugte Audio-/Video-Testdatei ist leer oder unvollständig.');
    }

    return {
      ok: true,
      stage: 'completed',
      test_type: 'synthetic_audio_video',
      container: 'webm',
      width: 640,
      height: 360,
      fps: 30,
      audio_rate: 48000,
      output_bytes: result.size,
      device_capture_verified: false,
      live_stream_verified: false,
      note: 'Video- und Audiotestsignale wurden lokal gemeinsam encodiert. Physische Geräte und Live-Ausgabe wurden nicht getestet.'
    };
  } catch (error) {
    return {
      ok: false,
      stage: 'pipeline',
      error: String(error.message || error).slice(0, 500),
      device_capture_verified: false,
      live_stream_verified: false
    };
  } finally {
    if (testDirectory) {
      await fs.rm(testDirectory, { recursive: true, force: true }).catch(() => {});
    }
  }
});

ipcMain.handle('studio:record-music-test', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const gstLaunch = await probeExecutable('gst-launch-1.0');
  if (!gstLaunch.available) {
    return {
      ok: false, stage: 'dependencies', missing: ['gst-launch-1.0'],
      device_capture_verified: false, live_stream_verified: false
    };
  }
  const pluginResults = await Promise.all(
    ['audiotestsrc', 'wavenc', 'filesink'].map(async name => [name, await probeGStreamerPlugin(name)])
  );
  const missing = pluginResults.filter(([, result]) => !result.available).map(([name]) => name);
  if (missing.length) {
    return {
      ok: false, stage: 'dependencies', missing,
      device_capture_verified: false, live_stream_verified: false
    };
  }

  let testDirectory;
  try {
    const seconds = Math.max(1, Math.min(10, Number(payload?.seconds) || 2));
    const buffers = Math.round(seconds * 48);
    testDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'streamiov-music-smoke-'));
    const outputFile = path.join(testDirectory, 'music-smoke-test.wav');
    const args = [
      '-e', 'audiotestsrc', 'wave=sine', 'freq=440', 'num-buffers=' + String(buffers), '!',
      'audioconvert', '!', 'audio/x-raw,format=S16LE,rate=48000,channels=2', '!',
      'wavenc', '!', 'filesink', 'location=' + outputFile
    ];
    await execFileAsync('gst-launch-1.0', args, {
      timeout: 45000,
      windowsHide: true,
      maxBuffer: 512 * 1024
    });
    const audio = await fs.readFile(outputFile);
    if (!audio.length || audio.length > 8 * 1024 * 1024 || !isWavBuffer(audio)) {
      throw new Error('Die erzeugte Musik-Testdatei ist leer, zu groß oder keine gültige WAV-Datei.');
    }
    return {
      ok: true,
      stage: 'completed',
      test_type: 'synthetic_music',
      container: 'wav',
      duration_seconds: seconds,
      sample_rate: 48000,
      channels: 2,
      output_bytes: audio.length,
      audio_base64: audio.toString('base64'),
      audio_mime: 'audio/wav',
      device_capture_verified: false,
      live_stream_verified: false,
      note: 'Ein lokales Musiksignal wurde encodiert. Physische Geräte und LIVE-Ausgabe wurden nicht getestet.'
    };
  } catch (error) {
    return {
      ok: false,
      stage: 'pipeline',
      error: String(error.message || error).slice(0, 500),
      device_capture_verified: false,
      live_stream_verified: false
    };
  } finally {
    if (testDirectory) await fs.rm(testDirectory, { recursive: true, force: true }).catch(() => {});
  }
});

ipcMain.handle('studio:get-network-status', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const interfaces = Object.values(os.networkInterfaces())
    .flat()
    .filter((item) => item && !item.internal);

  const localDevice = {
    interfaceCount: interfaces.length,
    status: interfaces.length ? 'interface_available' : 'no_local_interface'
  };

  try {
    const response = await fetch(STREAMIOV_API + '/api/v1/status', {
      headers: { 'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER },
      signal: AbortSignal.timeout(6000)
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.service !== 'streamiov-host') {
      throw new Error('Core antwortet mit HTTP ' + response.status);
    }

    return {
      ok: true,
      localDevice,
      core: {
        reachable: true,
        apiReady: payload.api_ready === true,
        stage: typeof payload.stage === 'string' ? payload.stage : 'unknown'
      },
      internetProbe: null
    };
  } catch (error) {
    return {
      ok: true,
      localDevice,
      core: {
        reachable: false,
        error: String(error.message || error).slice(0, 200)
      },
      internetProbe: null
    };
  }
});

ipcMain.handle('studio:update-status', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const updater = await getStudioUpdater();
  return updater.status();
});

ipcMain.handle('studio:update-check', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const updater = await getStudioUpdater();
  return updater.check();
});

ipcMain.handle('studio:update-prepare', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const updater = await getStudioUpdater();
  return updater.prepare();
});

ipcMain.handle('studio:update-install', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const updater = await getStudioUpdater();
  return updater.install();
});

ipcMain.handle('studio:update-clear-error', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const updater = await getStudioUpdater();
  return updater.clearError();
});

ipcMain.handle('studio:update-open-release', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const updater = await getStudioUpdater();
  const version = updater.state.latestVersion || updater.currentVersion;
  const url = releaseTagUrl(version);
  await shell.openExternal(url);
  return { ok: true, opened: 'release', version };
});

ipcMain.handle('studio:get-camera-lab', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  return {
    ok: true,
    report: {
      discovery: observedMediaDeviceCounts ? 'renderer_media_devices_enumerated' : 'not_reported',
      device_counts: observedMediaDeviceCounts,
      local_camera_count: observedMediaDeviceCounts ? observedMediaDeviceCounts.videoinput : null,
      local_microphone_count: observedMediaDeviceCounts ? observedMediaDeviceCounts.audioinput : null,
      observed_at: observedMediaDevicesAt,
      live_stream_verified: false,
      note: observedMediaDeviceCounts
        ? 'Anzahlen aus navigator.mediaDevices.enumerateDevices im Renderer; ohne Gerätelabels und ohne Hardware- oder LIVE-Verifikation.'
        : 'Es wurde noch keine Renderer-Gerätezählung gemeldet. Kamera- und Mikrofonvorschau laufen im Renderer; eine native Geräteinventur gibt es nicht.'
    }
  };

});

// STREAMIOV_STUDIO_AI_BRIDGE
// API-Zugang und Session bleiben ausschließlich im Electron-Hauptprozess.
// Contract: host/server.py exposes cookie auth under /api/v1/auth/* and a
// guarded read-only local inference endpoint under /api/v1/ai/tasks.
let streamiovSessionCookie = null;
let streamiovSessionUser = null;

function readSessionCookie(response) {
  const values = typeof response.headers.getSetCookie === 'function'
    ? response.headers.getSetCookie()
    : [response.headers.get('set-cookie')].filter(Boolean);
  for (const value of values) {
    const first = String(value).split(';', 1)[0].trim();
    if (first.startsWith('streamiov_session=')) return first;
  }
  return null;
}

async function publishLocalEvent(type, data = {}, severity = 'info') {
  if (!streamiovSessionCookie) {
    return { ok: false, delivered: false, error: 'Bitte zuerst im KI-Manager anmelden.' };
  }
  let built;
  try {
    built = createStudioEvent({
      type,
      data,
      severity,
      eventId: randomUUID(),
      occurredAt: new Date().toISOString(),
    });
  } catch (error) {
    return { ok: false, delivered: false, error: String(error.message || error) };
  }
  try {
    const response = await fetch(STREAMIOV_API + '/api/v1/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: streamiovSessionCookie,
        'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER
      },
      body: JSON.stringify({ event: built }),
      signal: AbortSignal.timeout(8000)
    });
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) {
      streamiovSessionCookie = null;
      streamiovSessionUser = null;
    }
    const delivered = response.ok && result.ok === true;
    return {
      ok: delivered,
      delivered,
      statusCode: response.status,
      eventId: built.event_id,
      duplicate: result.duplicate === true,
      error: delivered ? null : (result.error || 'Ereignis konnte nicht übertragen werden.')
    };
  } catch (error) {
    return { ok: false, delivered: false, error: 'Streamiov-Host nicht erreichbar: ' + String(error.message || error).slice(0, 250) };
  }
}

ipcMain.handle('studio:event-publish', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const options = payload && typeof payload === 'object' ? payload : {};
  return publishLocalEvent(options.type, options.data || {}, options.severity || 'info');
});

ipcMain.handle('studio:event-list', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (!streamiovSessionCookie) {
    return { ok: false, events: [], error: 'Bitte zuerst im KI-Manager anmelden.' };
  }
  const limit = Number.isInteger(payload?.limit) ? Math.max(1, Math.min(payload.limit, 100)) : 50;
  try {
    const response = await fetch(STREAMIOV_API + `/api/v1/events?limit=${limit}`, {
      headers: {
        Cookie: streamiovSessionCookie,
        'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER
      },
      signal: AbortSignal.timeout(8000)
    });
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) {
      streamiovSessionCookie = null;
      streamiovSessionUser = null;
    }
    return {
      ok: response.ok && result.ok === true,
      statusCode: response.status,
      schemaVersion: result.schema_version || null,
      events: Array.isArray(result.events) ? result.events : [],
      error: response.ok ? null : (result.error || 'Ereignisse konnten nicht geladen werden.')
    };
  } catch (error) {
    return { ok: false, events: [], error: 'Streamiov-Host nicht erreichbar: ' + String(error.message || error).slice(0, 250) };
  }
});

const WISHBOX_ACTIONS = Object.freeze({
  dispatch: Object.freeze([]),
  claim: Object.freeze(['agent']),
  reject: Object.freeze(['reason']),
  clarify: Object.freeze(['answer']),
  complete: Object.freeze(['result', 'agent'])
});
const WISHBOX_ID_PATTERN = /^wish-[a-f0-9]{32}$/;
const WISHBOX_AGENT_PATTERN = /^[a-z0-9_-]{1,40}$/;
const WISHBOX_ACTION_FIELDS = Object.freeze({
  reason: Object.freeze({ max: 240, required: false }),
  answer: Object.freeze({ max: 1200, required: true }),
  result: Object.freeze({ max: 2000, required: true }),
  agent: Object.freeze({ max: 40, required: false })
});

function wishboxActionBody(action, payload) {
  const body = {};
  for (const key of WISHBOX_ACTIONS[action]) {
    const value = payload?.[key];
    if (value === undefined || value === null || value === '') continue;
    if (typeof value !== 'string') return { error: `Ungültiges Feld: ${key}.` };
    const rule = WISHBOX_ACTION_FIELDS[key];
    const cleaned = value.trim();
    if (cleaned.length > rule.max) return { error: `Feld ${key} ist zu lang.` };
    if (cleaned && key === 'agent' && !WISHBOX_AGENT_PATTERN.test(cleaned)) {
      return { error: 'Ungültiger Agentenname.' };
    }
    if (cleaned) body[key] = cleaned;
  }
  for (const key of WISHBOX_ACTIONS[action]) {
    if (WISHBOX_ACTION_FIELDS[key].required && !body[key]) {
      return { error: `Feld ${key} fehlt.` };
    }
  }
  return { body };
}

async function wishboxRequest(path, options = {}) {
  if (!streamiovSessionCookie) {
    return { ok: false, authRequired: true, error: 'Bitte zuerst im KI-Manager anmelden.' };
  }
  try {
    const response = await fetch(STREAMIOV_API + path, {
      ...options,
      headers: {
        Cookie: streamiovSessionCookie,
        'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER,
        ...(options.body ? { 'Content-Type': 'application/json' } : {})
      },
      signal: AbortSignal.timeout(8000)
    });
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) {
      streamiovSessionCookie = null;
      streamiovSessionUser = null;
    }
    const ok = response.ok && result.ok === true;
    return {
      ok,
      statusCode: response.status,
      authRequired: response.status === 401,
      result,
      error: ok ? null : (result.error || (response.ok
        ? 'Wunschbox-Antwort ohne Erfolgsbestätigung.'
        : 'Wunschbox-Anfrage fehlgeschlagen.'))
    };
  } catch (error) {
    return { ok: false, error: 'Streamiov-Host nicht erreichbar: ' + String(error.message || error).slice(0, 250) };
  }
}

ipcMain.handle('studio:wishbox-orders', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const limit = Number.isInteger(payload?.limit) ? Math.max(1, Math.min(payload.limit, 100)) : 25;
  const kind = payload?.kind === 'music' || payload?.kind === 'game' ? payload.kind : '';
  const query = `?limit=${limit}${kind ? '&kind=' + encodeURIComponent(kind) : ''}`;
  const response = await wishboxRequest('/api/v1/wishbox/orders' + query);
  return {
    ok: response.ok,
    statusCode: response.statusCode || null,
    authRequired: response.authRequired === true,
    orders: Array.isArray(response.result?.orders) ? response.result.orders : [],
    error: response.error
  };
});

ipcMain.handle('studio:wishbox-handoffs', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const limit = Number.isInteger(payload?.limit) ? Math.max(1, Math.min(payload.limit, 100)) : 25;
  const response = await wishboxRequest(`/api/v1/wishbox/handoffs?limit=${limit}`);
  return {
    ok: response.ok,
    statusCode: response.statusCode || null,
    authRequired: response.authRequired === true,
    handoffs: Array.isArray(response.result?.handoffs) ? response.result.handoffs : [],
    error: response.error
  };
});

ipcMain.handle('studio:wishbox-submit', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const body = {};
  for (const key of ['text', 'sender', 'source', 'territory', 'priority']) {
    if (payload?.[key] !== undefined) body[key] = payload[key];
  }
  if (typeof body.text !== 'string' || !body.text.trim() || body.text.trim().length > 1200) {
    return { ok: false, error: 'Auftragstext fehlt oder ist zu lang.' };
  }
  let encoded;
  try {
    encoded = JSON.stringify(body);
  } catch {
    return { ok: false, error: 'Auftragstext konnte nicht übertragen werden.' };
  }
  const response = await wishboxRequest('/api/v1/wishbox/orders', {
    method: 'POST', body: encoded
  });
  return {
    ok: response.ok,
    statusCode: response.statusCode || null,
    authRequired: response.authRequired === true,
    order: response.result?.order || null,
    error: response.error
  };
});

ipcMain.handle('studio:wishbox-action', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const action = payload?.action;
  const orderId = payload?.orderId;
  if (!Object.hasOwn(WISHBOX_ACTIONS, action) || !WISHBOX_ID_PATTERN.test(orderId || '')) {
    return { ok: false, error: 'Ungültige Wunschbox-Aktion.' };
  }
  const validated = wishboxActionBody(action, payload);
  if (validated.error) return { ok: false, error: validated.error };
  let encoded;
  try {
    encoded = JSON.stringify(validated.body);
  } catch {
    return { ok: false, error: 'Aktion konnte nicht übertragen werden.' };
  }
  const response = await wishboxRequest(
    `/api/v1/wishbox/orders/${orderId}/${action}`,
    { method: 'POST', body: encoded }
  );
  return {
    ok: response.ok,
    statusCode: response.statusCode || null,
    authRequired: response.authRequired === true,
    order: response.result?.order || null,
    error: response.error
  };
});

ipcMain.handle('studio:auth-status', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (!streamiovSessionCookie) {
    return { ok: true, authenticated: false, user: null, statusCode: null, error: null };
  }
  try {
    const response = await fetch(STREAMIOV_API + '/api/v1/auth/me', {
      headers: {
        Cookie: streamiovSessionCookie,
        'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER
      },
      signal: AbortSignal.timeout(8000)
    });
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) {
      streamiovSessionCookie = null;
      streamiovSessionUser = null;
    }
    return {
      ok: response.ok && result.ok === true,
      authenticated: response.ok && result.ok === true && Boolean(result.user),
      user: result.user || null,
      statusCode: response.status,
      error: response.ok ? null : (result.error || 'Sitzung konnte nicht geprüft werden.')
    };
  } catch (error) {
    return { ok: false, authenticated: false, user: null, error: 'Streamiov-Host nicht erreichbar: ' + String(error.message || error).slice(0, 250) };
  }
});

const MUSIC_STATE_ROUTES = Object.freeze({
  state: { path: '/api/v1/music/state', actions: Object.freeze(['load', 'saveQueue']) },
  playlist: { path: '/api/v1/music/playlist', actions: Object.freeze(['save', 'delete', 'load', 'combine']) },
  'ai-playlist': { path: '/api/v1/music/ai-playlist', actions: Object.freeze(['create', 'improve']) }
});

ipcMain.handle('studio:music-state', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (!streamiovSessionCookie) {
    return { ok: false, error: 'Bitte zuerst im KI-Manager anmelden.' };
  }
  const kind = String(payload?.kind || '');
  const action = String(payload?.action || '');
  const route = Object.hasOwn(MUSIC_STATE_ROUTES, kind) ? MUSIC_STATE_ROUTES[kind] : null;
  if (!route || !route.actions.includes(action)) {
    return { ok: false, error: 'Ungültige Music-Anfrage.' };
  }
  const details = payload && typeof payload.payload === 'object' && payload.payload !== null ? payload.payload : {};
  if (Object.hasOwn(details, '__proto__')) {
    return { ok: false, error: 'Ungültige Music-Daten.' };
  }
  let body;
  try {
    body = JSON.stringify(details);
  } catch {
    return { ok: false, error: 'Music-Daten konnten nicht serialisiert werden.' };
  }
  if (body.length > 256 * 1024) {
    return { ok: false, error: 'Music-Daten sind zu groß.' };
  }
  try {
    const isLoad = action === 'load' && kind === 'state';
    const response = await fetch(STREAMIOV_API + route.path, {
      method: isLoad ? 'GET' : 'POST',
      headers: isLoad ? {
        Cookie: streamiovSessionCookie,
        'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER
      } : {
        'Content-Type': 'application/json',
        Cookie: streamiovSessionCookie,
        'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER
      },
      body: isLoad ? undefined : JSON.stringify({ action, payload: details }),
      signal: AbortSignal.timeout(9000)
    });
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) {
      streamiovSessionCookie = null;
      streamiovSessionUser = null;
    }
    return {
      ok: response.ok && result.ok === true,
      statusCode: response.status,
      queue: Array.isArray(result.queue) ? result.queue : [],
      playlists: Array.isArray(result.playlists) ? result.playlists : [],
      settings: result.settings || null,
      error: response.ok ? null : (result.error || 'Music-Daten konnten nicht gespeichert werden.')
    };
  } catch (error) {
    return { ok: false, error: 'Streamiov-Host nicht erreichbar: ' + String(error.message || error).slice(0, 250) };
  }
});

ipcMain.handle('studio:ai-login', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const username = String(payload.username || '').trim();
  const password = String(payload.password || '');

  if (!username || !password || username.length > 200 || password.length > 500) {
    return { ok: false, error: 'Bitte Benutzername und Passwort eingeben.' };
  }

  try {
    const response = await fetch(STREAMIOV_API + '/api/v1/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER
      },
      body: JSON.stringify({ username, password }),
      signal: AbortSignal.timeout(10000)
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok || data.ok !== true || !data.user) {
      return {
        ok: false,
        error: data.error || data.detail || 'Anmeldung fehlgeschlagen.'
      };
    }

    const cookie = readSessionCookie(response);
    if (!cookie) {
      streamiovSessionCookie = null;
      streamiovSessionUser = null;
      return { ok: false, error: 'Der Host hat keine gültige Sitzung gesetzt.' };
    }

    streamiovSessionCookie = cookie;
    streamiovSessionUser = {
      id: data.user.id || null,
      username: data.user.username || username,
      created_at: data.user.created_at || null
    };

    return { ok: true, user: streamiovSessionUser };
  } catch (error) {
    return {
      ok: false,
      error: 'Streamiov-Host nicht erreichbar: ' + String(error.message || error).slice(0, 250)
    };
  }
});

ipcMain.handle('studio:ai-logout', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  if (streamiovSessionCookie) {
    try {
      await fetch(STREAMIOV_API + '/api/v1/auth/logout', {
        method: 'POST',
        headers: {
          Cookie: streamiovSessionCookie,
          'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER
        },
        signal: AbortSignal.timeout(5000)
      });
    } catch {}
  }
  streamiovSessionCookie = null;
  streamiovSessionUser = null;
  return { ok: true };
});

ipcMain.handle('studio:ai-submit', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  if (!streamiovSessionCookie) {
    return { ok: false, error: 'Bitte zuerst im KI-Manager anmelden.' };
  }

  const request = String(payload.request || '').trim();
  if (!request || request.length > 2000) {
    return { ok: false, error: 'Auftrag muss zwischen 1 und 2000 Zeichen lang sein.' };
  }

  try {
    const response = await fetch(STREAMIOV_API + '/api/v1/ai/tasks', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: streamiovSessionCookie,
        'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER
      },
      body: JSON.stringify({ request }),
      signal: AbortSignal.timeout(30000)
    });

    const data = await response.json().catch(() => ({}));

    if (response.status === 401) {
      streamiovSessionCookie = null;
      streamiovSessionUser = null;
    }

    return {
      ok: response.ok,
      statusCode: response.status,
      data,
      error: response.ok ? null : (data.detail || data.error || 'KI-Anfrage fehlgeschlagen.')
    };
  } catch (error) {
    return {
      ok: false,
      error: 'KI-Host nicht erreichbar: ' + String(error.message || error).slice(0, 250)
    };
  }
});
// Read-only catalog bridge. The allowlist maps Studio panel names to host
// endpoints; arbitrary paths are never forwarded from the renderer.
const STUDIO_DATA_PATHS = Object.freeze({
  summary: '/api/v1/catalog',
  gifts: '/api/v1/catalog/gifts',
  music: '/api/v1/music/library',
  musicGate: '/api/v1/music/gate',
  musicDossier: '/api/v1/music/dossier',
  templates: '/api/v1/studio/templates'
});
const STUDIO_DATA_PARAM_RULES = Object.freeze({
  musicGate: Object.freeze({
    territory: /^[A-Z]{2}$/,
    usage: /^(local_playback|live_stream|saved_vod|download)$/
  }),
  musicDossier: Object.freeze({
    track: /^[a-z0-9][a-z0-9_-]{1,63}$/,
    territory: /^[A-Z]{2}$/,
    usage: /^(local_playback|live_stream|saved_vod|download)$/
  })
});

ipcMain.handle('studio:data-query', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const kind = String(payload.kind || '');
  const dataPath = Object.hasOwn(STUDIO_DATA_PATHS, kind) ? STUDIO_DATA_PATHS[kind] : undefined;
  if (!dataPath) {
    return { ok: false, error: 'Unbekannte Datenabfrage.' };
  }
  const rules = STUDIO_DATA_PARAM_RULES[kind] || {};
  const supplied = payload.params && typeof payload.params === 'object' && !Array.isArray(payload.params)
    ? payload.params
    : {};
  const query = new URLSearchParams();
  for (const [key, pattern] of Object.entries(rules)) {
    if (!Object.hasOwn(supplied, key)) continue;
    const value = String(supplied[key]);
    if (!pattern.test(value)) {
      return { ok: false, error: 'Ungültiger Abfrageparameter: ' + key };
    }
    query.set(key, value);
  }
  const suffix = query.toString();
  const requestUrl = STREAMIOV_API + dataPath + (suffix ? '?' + suffix : '');
  try {
    const response = await fetch(requestUrl, {
      headers: { 'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER },
      signal: AbortSignal.timeout(10000)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok !== true) {
      return {
        ok: false,
        statusCode: response.status,
        error: data.detail || data.error || 'Rohdaten-Katalog nicht erreichbar.'
      };
    }
    return { ok: true, kind, data, assetBase: STREAMIOV_API };
  } catch (error) {
    return {
      ok: false,
      error: 'Streamiov-Host nicht erreichbar: ' + String(error.message || error).slice(0, 250)
    };
  }
});
// STREAMIOV_STUDIO_AI_BRIDGE_END


let mainWindow = null;
let programOutputWindow = null;
let programFramesDelivered = 0;
function sendProgramAssets() {
  if (!programOutputWindow || programOutputWindow.isDestroyed()) return;
  programOutputWindow.webContents.send('studio:program-assets', { assets: mediaAssetsWithUrls() });
}
function publishProgramScene(snapshot) {
  if (!programOutputWindow || programOutputWindow.isDestroyed()) return;
  const state = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const scenes = Array.isArray(state.scenes) ? state.scenes : [];
  const activeScene = scenes.find(scene => scene && scene.id === state.programSceneId);
  const scene = activeScene || { name: 'STREAMIOV' };
  programOutputWindow.webContents.send('studio:program-scene', {
    id: typeof scene.id === 'string' ? scene.id.slice(0, 80) : '',
    name: typeof scene.name === 'string' ? scene.name.slice(0, 60) : 'STREAMIOV',
    background: scene.background,
    overlay: scene.overlay,
    transition: state.transition,
    sources: Array.isArray(scene.sources) ? scene.sources.slice(0, 20) : [],
    snapshot,
    assets: mediaAssetsWithUrls()
  });
}
function getExternalDisplay() {
  const displays = screen.getAllDisplays();
  const primary = screen.getPrimaryDisplay();
  return displays.find(display => display.id !== primary.id) || null;
}
function openProgramOutput() {
  if (programOutputWindow && !programOutputWindow.isDestroyed()) {
    programOutputWindow.focus();
    return { ok: true, alreadyOpen: true };
  }
  const display = getExternalDisplay();
  const bounds = display ? display.bounds : { x: 140, y: 120, width: 1280, height: 720 };
  programOutputWindow = new BrowserWindow({
    ...bounds, title: 'STREAMIOV · Programmausgabe', backgroundColor: '#070914',
    autoHideMenuBar: true, fullscreen: Boolean(display),
    webPreferences: {
      preload: path.join(__dirname, 'program-output-preload.js'),
      nodeIntegration: false, contextIsolation: true, sandbox: true
    }
  });
  programOutputWindow.setMenuBarVisibility(false);
  programOutputWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  programOutputWindow.webContents.once('did-finish-load', async () => {
    if (!programOutputWindow || programOutputWindow.isDestroyed()) return;
    try {
      const sceneFile = path.join(app.getPath('userData'), 'streamiov-scenes.json');
      let savedState = {};
      try {
        savedState = JSON.parse(await fs.readFile(sceneFile, 'utf8'));
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
      const snapshot = new StudioSceneEngine(savedState).snapshot();
      sendProgramAssets();
      publishProgramScene(snapshot);
    } catch (error) {
      console.error('[PROGRAM_OUTPUT] INITIAL_SCENE_FAILED', error);
    }
  });
  programOutputWindow.loadFile(path.join(__dirname, 'program-output.html')).catch(error => console.error('[PROGRAM_OUTPUT] LOAD_FAILED', error));
  programOutputWindow.on('closed', () => { programOutputWindow = null; });
  programFramesDelivered = 0;
  return { ok: true, externalDisplay: Boolean(display), displayBounds: bounds, outputWindowOpened: true, renderedVideo: false, programFramesDelivered };
}
ipcMain.handle('studio:get-displays', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const primary = screen.getPrimaryDisplay();
  return {
    ok: true,
    displays: screen.getAllDisplays().map(display => ({ id: display.id, bounds: display.bounds, scaleFactor: display.scaleFactor, primary: display.id === primary.id })),
    externalDisplayAvailable: Boolean(getExternalDisplay())
  };
});
ipcMain.handle('studio:open-program-output', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  return openProgramOutput();
});

ipcMain.handle('studio:program-frame', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (payload?.bytes instanceof Uint8Array || Buffer.isBuffer(payload?.bytes)) {
    const bytes = Buffer.isBuffer(payload.bytes)
      ? payload.bytes
      : Buffer.from(payload.bytes.buffer, payload.bytes.byteOffset, payload.bytes.byteLength);
    if (bytes.length > 4 * 1024 * 1024 || bytes.length < 4 ||
        bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes[2] !== 0xff) {
      return { ok: false, error: 'Ungültiges Programmbild.' };
    }
    if (!programOutputWindow || programOutputWindow.isDestroyed()) return { ok: true, delivered: false };
    programOutputWindow.webContents.send('studio:program-frame', new Uint8Array(bytes));
    programFramesDelivered += 1;
    return { ok: true, delivered: true, programFramesDelivered };
  }
  const frame = typeof payload === 'string' ? payload : payload?.dataUrl;
  if (typeof frame !== 'string' || !frame.startsWith('data:image/jpeg;base64,') || frame.length > 4 * 1024 * 1024) {
    return { ok: false, error: 'Ungültiges Programmbild.' };
  }
  if (!programOutputWindow || programOutputWindow.isDestroyed()) return { ok: true, delivered: false };
  programOutputWindow.webContents.send('studio:program-frame', frame);
  programFramesDelivered += 1;
  return { ok: true, delivered: true, programFramesDelivered };
});

let regieDisplayId = null;
function placeRegieOnDisplay(displayId) {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false, error: 'Regie-Fenster ist noch nicht bereit.' };
  const displays = screen.getAllDisplays();
  const target = displays.find(display => String(display.id) === String(displayId))
    || displays.find(display => display.id !== screen.getPrimaryDisplay().id)
    || screen.getPrimaryDisplay();
  if (!target) return { ok: false, error: 'Kein verwendbarer Bildschirm erkannt.' };
  regieDisplayId = target.id;
  const bounds = target.workArea || target.bounds;
  const width = Math.max(800, Math.min(1600, bounds.width));
  const height = Math.max(600, Math.min(1000, bounds.height));
  mainWindow.setFullScreen(false);
  mainWindow.setBounds({
    x: bounds.x + Math.max(0, Math.floor((bounds.width - width) / 2)),
    y: bounds.y + Math.max(0, Math.floor((bounds.height - height) / 2)),
    width: Math.min(width, bounds.width),
    height: Math.min(height, bounds.height)
  });
  mainWindow.show();
  mainWindow.focus();
  return {
    ok: true,
    displayId: target.id,
    primary: target.id === screen.getPrimaryDisplay().id,
    displayBounds: target.bounds,
    regieWindowMoved: true
  };
}

ipcMain.handle('studio:move-regie-to-display', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  return placeRegieOnDisplay(payload.displayId);
});

function reconcileRegieDisplay() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const displays = screen.getAllDisplays();
  const selectedStillExists = displays.some(display => display.id === regieDisplayId);
  if (selectedStillExists) return;
  const fallback = displays.find(display => display.id !== screen.getPrimaryDisplay().id)
    || screen.getPrimaryDisplay();
  if (fallback) placeRegieOnDisplay(fallback.id);
}

app.whenReady().then(async () => {
  if (typeof protocol?.registerFileProtocol === 'function') {
    protocol.registerFileProtocol('streamiov-media', async (request, callback) => {
      let assetId = '';
      try {
        const parsed = new URL(request.url);
        if (parsed.host !== 'asset') throw new Error('Ungültiger Medien-Host');
        assetId = decodeURIComponent(parsed.pathname.slice(1));
      } catch {}
      await mediaAssetsLoaded;
      const location = mediaAssetStore.resolve(assetId);
      if (!location) {
        callback({ error: -6 });
        return;
      }
      try {
        await fs.access(location, fsConstants.R_OK);
        callback({ path: location });
      } catch {
        callback({ error: -6 });
      }
    });
  }
  const ses = session.defaultSession;

  ses.setPermissionRequestHandler((webContents, permission, callback) => {
    const trusted = webContents.getURL() === studioUrl;
    callback(['media', 'display-capture'].includes(permission) && trusted);
  });

  ses.setPermissionCheckHandler((webContents, permission) => {
    return ['media', 'display-capture'].includes(permission) && webContents.getURL() === studioUrl;
  });

  ses.setDisplayMediaRequestHandler((request, callback) => {
    const frame = request.frame;
    const sourceId = selectedDisplaySourceId;
    selectedDisplaySourceId = null;
    if (!frame || frame.parent !== null || frame.url !== studioUrl || !sourceId) {
      callback(null);
      return;
    }
    desktopCapturer.getSources({
      types: ['screen', 'window'],
      thumbnailSize: { width: 0, height: 0 }
    }).then((sources) => {
      const source = sources.find((item) => item.id === sourceId);
      if (!source) {
        callback(null);
        return;
      }
      const media = { video: source };
      if (request.audioRequested && process.platform === 'win32') media.audio = 'loopback';
      callback(media);
    }).catch(() => callback(null));
  });

  const initialRegieDisplay = getExternalDisplay() || screen.getPrimaryDisplay();
  const initialRegieArea = initialRegieDisplay.workArea || initialRegieDisplay.bounds;
  regieDisplayId = initialRegieDisplay.id;
  mainWindow = new BrowserWindow({
    x: initialRegieArea.x + Math.max(0, Math.floor((initialRegieArea.width - Math.min(1600, initialRegieArea.width)) / 2)),
    y: initialRegieArea.y + Math.max(0, Math.floor((initialRegieArea.height - Math.min(900, initialRegieArea.height)) / 2)),
    width: Math.min(1600, initialRegieArea.width),
    height: Math.min(900, initialRegieArea.height),
    minWidth: 800,
    minHeight: 600,
    title: 'Streamiov Studio',
    backgroundColor: '#10131b',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true
    }
  });
  const win = mainWindow;

  win.once('ready-to-show', () => {
    console.error('[TRACE] READY_TO_SHOW');
  });

  win.on('closed', () => console.error('[TRACE] WINDOW_CLOSED'));
  win.webContents.on('did-finish-load', () => console.error('[TRACE] DID_FINISH_LOAD', redactUrlForLog(win.webContents.getURL())));
  win.webContents.on('render-process-gone', (_e, details) => console.error('[TRACE] RENDER_GONE', details));
  win.webContents.on('unresponsive', () => console.error('[TRACE] RENDER_UNRESPONSIVE'));
  win.webContents.on('did-fail-load', (_e, code, desc, url) => console.error('[TRACE] LOAD_FAILED', code, desc, redactUrlForLog(url)));
  win.loadFile(path.join(__dirname, 'regie-v2.html')).catch(e => console.error('[TRACE] LOAD_PROMISE_REJECTED', e));

  screen.on('display-added', reconcileRegieDisplay);
  screen.on('display-removed', reconcileRegieDisplay);
  screen.on('display-metrics-changed', reconcileRegieDisplay);

  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

  win.webContents.on('will-navigate', (event, url) => {
    let allowed = false;

    try {
      const actual = new URL(url);
      const expected = new URL(studioUrl);

      allowed =
        actual.protocol === 'file:' &&
        actual.host === expected.host &&
        actual.pathname === expected.pathname;
    } catch {
      allowed = false;
    }

    console.error('[TRACE] NAVIGATION_REQUEST', redactUrlForLog(url), 'ALLOWED:', allowed);

    if (!allowed) {
      console.error('[TRACE] NAVIGATION_BLOCKED', redactUrlForLog(url));
      event.preventDefault();
    }
  });
});

app.on('before-quit', () => {
  stopRemoteConfirmationPolling();
  if (liveOutputManager.isActive()) void liveOutputManager.stopAll();
  console.error('[TRACE] BEFORE_QUIT', new Error('before-quit-stack').stack);
});
app.on('will-quit', () => console.error('[TRACE] WILL_QUIT'));

app.on('window-all-closed', () => {
  console.error('[TRACE] WINDOW_ALL_CLOSED');
  if (process.platform !== 'darwin') app.quit();
});
