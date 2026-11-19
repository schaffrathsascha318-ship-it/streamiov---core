const { app, BrowserWindow, session, ipcMain, desktopCapturer, screen, shell } = require('electron');

const path = require('node:path');
const fs = require('node:fs/promises');
const { randomUUID } = require('node:crypto');
const os = require('node:os');
const http = require('node:http');
const { pathToFileURL } = require('node:url');
const { buildSyntheticAvPipelineArgs } = require('./media-pipeline');
const { StudioSourceModel } = require('./engine/source-model');
const { StudioSceneEngine } = require('./engine/scene-engine');
const { getStudioCapabilities } = require('./platform-capabilities');
const { createGameAiAnalysis } = require('./engine/game-ai-engine');

const { execFile, spawn } = require('node:child_process');
const { promisify } = require('node:util');
const execFileAsync = promisify(execFile);
const studioUrl = pathToFileURL(path.join(__dirname, 'regie-v2.html')).href;
let liveStreamProcess = null;
let liveStreamState = 'offline';
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

function publishStreamStatus(status, detail = '') {
  liveStreamState = status;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('studio:stream-status', { status, detail });
  }
}

function normalizeRtmpDestination(value) {
  if (typeof value !== 'string' || value.trim().length > 2048) return null;
  try {
    const url = new URL(value.trim());
    if (!['rtmp:', 'rtmps:'].includes(url.protocol) || !url.hostname || !url.pathname ||
        url.username || url.password || url.hash) return null;
    return url.toString();
  } catch {
    return null;
  }
}

ipcMain.handle('studio:start-stream', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (liveStreamProcess) return { ok: false, error: 'Ein Stream läuft bereits.' };

  const destination = normalizeRtmpDestination(payload.destination);
  const resolution = ['720p', '1080p', '1440p'].includes(payload.resolution) ? payload.resolution : '1080p';
  const fps = Number(payload.fps);
  const bitrate = Number(payload.bitrate);
  if (!destination) return { ok: false, error: 'Bitte eine gültige rtmp://- oder rtmps://-Adresse ohne Benutzername und Passwort eingeben.' };
  if (![30, 60].includes(fps) || !Number.isInteger(bitrate) || bitrate < 500 || bitrate > 20000) {
    return { ok: false, error: 'Stream-Einstellungen sind ungültig.' };
  }
  const encoder = await probeFfmpegRtmp();
  if (!encoder.available) {
    return {
      ok: false,
      error: 'RTMP-Streaming benötigt FFmpeg mit libx264, AAC und RTMP/RTMPS. Fehlend: ' + encoder.missing.join(', ') + '.'
    };
  }

  const dimensions = { '720p': [1280, 720], '1080p': [1920, 1080], '1440p': [2560, 1440] }[resolution];
  const args = [
    '-hide_banner', '-loglevel', 'info', '-f', 'webm', '-i', 'pipe:0',
    '-map', '0:v:0', '-map', '0:a:0?', '-vf', `scale=${dimensions[0]}:${dimensions[1]}:force_original_aspect_ratio=decrease,pad=${dimensions[0]}:${dimensions[1]}:(ow-iw)/2:(oh-ih)/2`,
    '-r', String(fps), '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
    '-pix_fmt', 'yuv420p', '-b:v', `${bitrate}k`, '-maxrate', `${bitrate}k`, '-bufsize', `${bitrate * 2}k`,
    '-c:a', 'aac', '-b:a', '128k', '-ar', '48000', '-ac', '2', '-f', 'flv', destination
  ];

  try {
    const child = spawn('ffmpeg', args, { stdio: ['pipe', 'ignore', 'pipe'], windowsHide: true });
    liveStreamProcess = child;
    publishStreamStatus('connecting');

    child.once('error', (error) => {
      if (liveStreamProcess === child) liveStreamProcess = null;
      publishStreamStatus('error', error.code === 'ENOENT'
        ? 'FFmpeg wurde nicht gefunden. Installiere FFmpeg mit libx264 und RTMP-Unterstützung.'
        : 'Der Encoder konnte nicht gestartet werden.');
    });
    let diagnosticBuffer = '';
    child.stderr.on('data', (data) => {
      // Encoder diagnostics can contain the RTMP destination and stream key.
      // Never forward or persist raw FFmpeg output.
      diagnosticBuffer = (diagnosticBuffer + data.toString('utf8')).slice(-8192);
      if (diagnosticBuffer.includes('Output #0, flv')) {
        publishStreamStatus('live');
        diagnosticBuffer = '';
      }
    });
    child.once('close', (code, signal) => {
      if (liveStreamProcess === child) liveStreamProcess = null;
      if (liveStreamState !== 'stopping') {
        publishStreamStatus(code === 0 ? 'offline' : 'error',
          code === 0 ? 'Stream beendet.' : 'Stream-Verbindung beendet. Prüfe Zieladresse, Stream-Key und Encoder.');
      } else {
        publishStreamStatus('offline');
      }
    });
    child.once('spawn', () => publishStreamStatus('connecting'));
    return { ok: true, status: 'connecting' };
  } catch (error) {
    publishStreamStatus('error', 'FFmpeg konnte nicht gestartet werden.');
    return { ok: false, error: error.code === 'ENOENT'
      ? 'FFmpeg wurde nicht gefunden. Installiere FFmpeg mit libx264 und RTMP-Unterstützung.'
      : 'Der Encoder konnte nicht gestartet werden.' };
  }
});

ipcMain.handle('studio:write-stream-chunk', async (event, chunk) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (!liveStreamProcess || liveStreamState === 'stopping') return { ok: false, error: 'Kein aktiver Stream.' };
  if (!(chunk instanceof ArrayBuffer) || chunk.byteLength > 4 * 1024 * 1024) {
    return { ok: false, error: 'Ungültiger Medienblock.' };
  }
  const input = liveStreamProcess.stdin;
  if (!input || input.destroyed || input.writableLength > 8 *  1024 * 1024) {
    return { ok: false, error: 'Der Encoder kann die Medien nicht schnell genug verarbeiten.' };
  }
  return new Promise((resolve) => {
    input.write(Buffer.from(chunk), (error) => resolve(error
      ? { ok: false, error: 'Medien konnten nicht an den Encoder gesendet werden.' }
      : { ok: true }));
  });
});

ipcMain.handle('studio:stop-stream', async (event) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  if (!liveStreamProcess) {
    publishStreamStatus('offline');
    return { ok: true, status: 'offline' };
  }
  const child = liveStreamProcess;
  liveStreamState = 'stopping';
  publishStreamStatus('stopping');
  child.stdin?.end();
  setTimeout(() => {
    if (liveStreamProcess === child) child.kill('SIGINT');
  }, 3000).unref();
  return { ok: true, status: 'stopping' };
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


ipcMain.handle('studio:get-platform-capabilities', async (event, rendererFeatures = {}) => {
  if (!isTrustedStudioSender(event)) throw new Error('Nicht autorisierter Studio-Aufruf');
  const safeFeatures = {
    getUserMedia: rendererFeatures.camera === true,
    getDisplayMedia: rendererFeatures.screenCapture === true
  };
  return getStudioCapabilities({
    runtime: { electron: true },
    nodePlatform: process.platform,
    mediaDevices: safeFeatures,
    audioElement: { setSinkId: rendererFeatures.audioOutputRouting === true }
  });
});

const streamiovChatState = {
  chat: 'offline',
  tts: 'offline',
  messages: []
};

ipcMain.handle('studio:chat-action', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const action = payload.action;
  if (action === 'status') {
    return {
      ok: true,
      chat: streamiovChatState.chat,
      tts: streamiovChatState.tts,
      message_count: streamiovChatState.messages.length,
      messages: streamiovChatState.messages.slice(-100),
      external_platform_connected: false,
      tts_audio_verified: false
    };
  }
  if (action === 'toggle-chat') {
    streamiovChatState.chat =
      streamiovChatState.chat === 'online' ? 'offline' : 'online';
  } else if (action === 'toggle-tts') {
    streamiovChatState.tts =
      streamiovChatState.tts === 'online' ? 'offline' : 'online';
  } else if (action === 'receive') {
    const text = typeof payload.text === 'string' ? payload.text.trim() : '';
    if (!text || text.length > 2000) {
      return { ok: false, error: 'Nachricht muss 1–2000 Zeichen lang sein.' };
    }
    if (streamiovChatState.chat !== 'online') {
      return { ok: false, error: 'Chat ist ausgeschaltet.' };
    }
    streamiovChatState.messages.push({
      text: text,
      time: new Date().toISOString(),
      source: 'local_test'
    });
    streamiovChatState.messages = streamiovChatState.messages.slice(-500);
  } else if (action === 'speak') {
    const text = typeof payload.text === 'string' ? payload.text.trim() : '';
    if (!text || text.length > 1000) {
      return { ok: false, error: 'TTS-Text muss 1–1000 Zeichen lang sein.' };
    }
    if (streamiovChatState.tts !== 'online') {
      return { ok: false, error: 'TTS ist ausgeschaltet.' };
    }
    try {
      await execFileAsync('espeak-ng', ['-v', 'de', text], {
        timeout: 60000,
        windowsHide: true
      });
    } catch (error) {
      return {
        ok: false,
        error: error.code === 'ENOENT'
          ? 'espeak-ng ist auf diesem Gerät nicht verfügbar.'
          : 'Sprachausgabe fehlgeschlagen: ' + (error.message || 'unbekannter Fehler'),
        tts_audio_verified: false
      };
    }
  } else {
    return { ok: false, error: 'Unbekannte Chat-Aktion.' };
  }

  return {
    ok: true,
    chat: streamiovChatState.chat,
    tts: streamiovChatState.tts,
    message_count: streamiovChatState.messages.length,
    messages: streamiovChatState.messages.slice(-100),
    external_platform_connected: false,
    tts_audio_verified: false
  };
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
  let result;
  if (action === 'load') {
    return { ok: true, state: engine.snapshot() };
  } else if (action === 'select') {
    result = engine.selectPreview(payload.id || payload.name);
  } else if (action === 'take') {
    result = engine.take();
  } else if (action === 'set-program') {
    result = engine.setProgramScene(payload.id || payload.name);
  } else if (action === 'create') {
    result = engine.createScene(payload.name);
  } else if (action === 'rename-scene') {
    result = engine.renameScene(payload.id, payload.name);
  } else if (action === 'delete-scene') {
    result = engine.deleteScene(payload.id);
  } else if (action === 'add-source') {
    result = engine.addSource(payload.source || {});
  } else if (action === 'update-source') {
    result = engine.updateSource(payload.sourceId, payload.patch || {});
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
  if ((action === 'take' || action === 'set-program') && programOutputWindow && !programOutputWindow.isDestroyed()) {
    const activeScene = result.state.scenes.find(scene => scene.id === result.state.programSceneId);
    programOutputWindow.webContents.send('studio:program-scene', activeScene || { name: 'STREAMIOV' });
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

// Eigene, lokal paketierte Spielebibliothek. Spiele laufen in isolierten Fenstern
// und erhalten keinen Node-/Preload-Zugriff auf das Studio.
async function readGameLibrary() {
  const root = path.join(__dirname, 'games');
  const registry = JSON.parse(await fs.readFile(path.join(root, 'registry.json'), 'utf8'));
  if (!registry || registry.schemaVersion !== 1 || !Array.isArray(registry.games)) {
    throw new Error('Ungültige Spielebibliothek.');
  }
  const games = [];
  for (const item of registry.games) {
    if (!item || typeof item.id !== 'string' || !/^[a-z0-9-]{2,64}$/.test(item.id)) continue;
    const directory = path.resolve(root, item.id);
    if (!directory.startsWith(root + path.sep)) continue;
    const manifest = JSON.parse(await fs.readFile(path.join(directory, 'game.json'), 'utf8'));
    if (manifest.id !== item.id || typeof manifest.name !== 'string') continue;
    games.push({
      id: item.id,
      name: manifest.name,
      version: manifest.version,
      description: manifest.description || '',
      status: item.status || manifest.status || 'unknown',
      gameplayVerified: manifest.release?.gameplayVerified === true,
      released: manifest.release?.released === true
    });
  }
  return games;
}

ipcMain.handle('studio:list-games', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  try {
    return { ok: true, games: await readGameLibrary() };
  } catch (error) {
    return { ok: false, error: 'Spielebibliothek konnte nicht geladen werden: ' + String(error.message || error).slice(0, 180) };
  }
});

ipcMain.handle('studio:open-game', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const id = typeof payload.id === 'string' ? payload.id : '';
  if (!/^[a-z0-9-]{2,64}$/.test(id)) return { ok: false, error: 'Ungültige Spiel-ID.' };

  try {
    const root = path.join(__dirname, 'games');
    const games = await readGameLibrary();
    const game = games.find(item => item.id === id);
    if (!game) return { ok: false, error: 'Spiel ist nicht in der lokalen Bibliothek.' };

    const directory = path.resolve(root, id);
    const manifest = JSON.parse(await fs.readFile(path.join(directory, 'game.json'), 'utf8'));
    const entry = typeof manifest.entry === 'string' ? manifest.entry : '';
    if (!entry || path.isAbsolute(entry) || entry.split(/[\\/]/).includes('..')) {
      return { ok: false, error: 'Ungültiger Spieleinstiegspunkt.' };
    }
    const entryPath = path.resolve(directory, entry);
    if (!entryPath.startsWith(directory + path.sep)) return { ok: false, error: 'Spieleinstiegspunkt außerhalb des Pakets.' };
    await fs.access(entryPath);

    const gameWindow = new BrowserWindow({
      width: 1200,
      height: 820,
      minWidth: 640,
      minHeight: 480,
      title: game.name + ' · STREAMIOV',
      backgroundColor: '#080b18',
      autoHideMenuBar: true,
      parent: mainWindow || undefined,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true
      }
    });
    gameWindow.setMenuBarVisibility(false);
    gameWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    gameWindow.webContents.on('will-navigate', (navigationEvent, url) => {
      let allowed = false;
      try {
        const actual = new URL(url);
        const expected = pathToFileURL(entryPath);
        allowed = actual.protocol === 'file:' && actual.pathname === expected.pathname;
      } catch {}
      if (!allowed) navigationEvent.preventDefault();
    });
    await gameWindow.loadFile(entryPath);
    return { ok: true, id, status: game.status, released: game.released, windowOpened: true };
  } catch (error) {
    return { ok: false, error: 'Spiel konnte nicht gestartet werden: ' + String(error.message || error).slice(0, 180) };
  }
});


// Dauerhafte Verwaltung von Quellen-Metadaten. Dies verbindet noch keine
// Kamera-/Capture-Quelle mit der Encoder-Pipeline.
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
    return { ok: true, state: model.snapshot(), capture_pipeline_connected: false };
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

  return { ok: true, state: model.snapshot(), capture_pipeline_connected: false };
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
  try {
    const [{ stdout: encoders }, { stdout: protocols }] = await Promise.all([
      execFileAsync('ffmpeg', ['-hide_banner', '-encoders'], {
        timeout: 10000, windowsHide: true, maxBuffer: 1024 * 1024
      }),
      execFileAsync('ffmpeg', ['-hide_banner', '-protocols'], {
        timeout: 10000, windowsHide: true, maxBuffer: 1024 * 1024
      })
    ]);
    const video = /\blibx264\b/.test(encoders);
    const audio = /\baac\b/.test(encoders);
    const rtmp = /(?:^|\s)rtmp(?:s)?(?:\s|$)/m.test(protocols);
    return {
      available: video && audio && rtmp,
      ffmpeg_available: true,
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

  const [gstInspect, gstLaunch, ffmpeg] = await Promise.all([
    probeExecutable('gst-inspect-1.0'),
    probeExecutable('gst-launch-1.0'),
    probeExecutable('ffmpeg')
  ]);
  const rtmp = await probeFfmpegRtmp();

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
    named_scene_switching_implemented: false,
    live_stream_verified: false,
    note: 'Dies ist eine Abhängigkeitsprüfung. Gerätezugriff, Encoder-Pipeline, Plattformautorisierung und Live-Ausgabe sind damit nicht getestet.'
  };
});

/**
 * STREAMIOV_TIKTOK_STUDIO_BRIDGE
 * Native Electron OAuth callback. Credentials are read only from process.env;
 * tokens are handled by the encrypted OAuth service in the main process.
 */
const { TikTokOAuth } = require('./tiktok-oauth.js');
let tikTokOAuth = null;
let tikTokCallbackServer = null;
let tikTokCallbackTimeout = null;
let tikTokConnectInProgress = false;

function getTikTokOAuth() {
  if (!tikTokOAuth) {
    tikTokOAuth = new TikTokOAuth({
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
      status: 'configuration_required',
      environment: 'sandbox',
      error: String(error.message || error)
    };
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


// Crostini-Kompatibilität: GPU-Beschleunigung vor app.whenReady deaktivieren.
app.disableHardwareAcceleration();

ipcMain.handle('studio:get-module-status', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  return {
    ok: true,
    verification: 'repository_capability_inventory',
    live_stream_verified: false,
    modules: [
      { id: 'ai-game-analyzer', status: 'foundation_ready', note: 'Spieltyp, Spielsituation und Ereignisse aus belegten Signalen erkennen.' },
      { id: 'ai-interaction-ai', status: 'foundation_ready', note: 'Zuschaueraktionen und Challenges passend zum Spiel entwerfen.' },
      { id: 'ai-overlay-ai', status: 'foundation_ready', note: 'Overlay-, Ranglisten- und Animationskonzepte vorbereiten.' },
      { id: 'ai-event-ai', status: 'foundation_ready', note: 'Freigegebene LIVE-Ereignisse zu sicheren Aktionsvorschlägen zuordnen.' },
      { id: 'ai-balance-ai', status: 'foundation_ready', note: 'Fairness, Missbrauchsrisiken und Spielbalance bewerten.' },
      { id: 'ai-learning-ai', status: 'foundation_ready', note: 'Ergebnisse auswerten und überprüfbare Verbesserungen ableiten.' },
      { id: 'scene-engine', status: 'automated_tested', note: 'Preview/Program-Zustand und TAKE; keine gerenderte Videoausgabe.' },
      { id: 'source-model', status: 'automated_tested', note: 'Quellen-Metadaten werden lokal gespeichert; keine Capture-/Encoder-Verbindung.' },
      { id: 'local-camera-preview', status: 'renderer_local_only', note: 'Getrennte lokale MediaDevices-Vorschau; nicht in Program/Encoder eingebunden.' },
      { id: 'synthetic-av-test', status: 'dependency_gated', note: 'Lokaler Test mit installierten GStreamer-Komponenten.' },
      { id: 'compositor', status: 'not_implemented' },
      { id: 'production-encoder', status: 'not_implemented' },
      { id: 'audio-mixer-routing', status: 'ui_only' },
      { id: 'tiktok-live-output', status: 'oauth_and_live_verification_pending' },
      { id: 'chat-events', status: 'not_connected' },
      { id: 'gift-events', status: 'not_connected' },
      { id: 'music-mixing', status: 'not_implemented' }
    ]
  };

});

ipcMain.handle('studio:get-status', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  return {
    ok: true,
    bridge: 'ready',
    backend: {
      connected: false,
      state: 'foundation_only',
      engine: {
        name: 'STREAMIOV Studio Runtime',
        scene_engine: 'available',
        source_metadata_store: 'available',
        compositor: 'not_implemented',
        encoder: 'not_implemented',
        output_connected: false,
        output_active: false,
        live_stream_verified: false
      },
      note: 'Die eigene Medienpipeline und der produktive Encoder sind noch nicht integriert.'
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

ipcMain.handle('studio:record-music-test', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  return {
    ok: false,
    stage: 'not_implemented',
    error: 'Der native Audio-Mixer und die Musik-Encoding-Pipeline sind noch nicht integriert.',
    live_stream_verified: false
  };

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
    const payload = await new Promise((resolve, reject) => {
      const req = http.get(
        'http://127.0.0.1:18180/api/network/status',
        { timeout: 6000 },
        (res) => {
          let body = '';
          res.setEncoding('utf8');
          res.on('data', (chunk) => {
            body += chunk;
            if (body.length > 65536) {
              req.destroy(new Error('Antwort zu groß'));
            }
          });
          res.on('end', () => {
            if (res.statusCode !== 200) {
              reject(new Error('Core antwortet mit HTTP ' + res.statusCode));
              return;
            }
            try {
              resolve(JSON.parse(body));
            } catch {
              reject(new Error('Ungültige Core-Antwort'));
            }
          });
        }
      );
      req.on('timeout', () => req.destroy(new Error('Zeitlimit erreicht')));
      req.on('error', reject);
    });

    return {
      ok: true,
      localDevice,
      core: { reachable: payload.ok === true },
      internetProbe: payload.internetProbe || null
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

ipcMain.handle('studio:get-camera-lab', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  return {
    ok: true,
    report: {
      discovery: 'renderer_media_devices',
      devices: [],
      local_camera_count: null,
      live_stream_verified: false,
      note: 'Kamera- und Mikrofonvorschau werden im Renderer über MediaDevices getestet. Eine native Geräteinventur und Verbindung zur Produktionspipeline sind noch nicht implementiert.'
    }
  };

});

// STREAMIOV_STUDIO_AI_BRIDGE
// API-Zugang und Session bleiben ausschließlich im Electron-Hauptprozess.
// Contract: host/server.py exposes cookie auth under /api/v1/auth/* and a
// guarded AI task placeholder under /api/v1/ai/tasks.
const STREAMIOV_API = process.env.STREAMIOV_HOST_URL || 'http://127.0.0.1:8765';
const STREAMIOV_CLIENT_HEADER = 'studio';
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
ipcMain.handle('studio:game-ai-analyze', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  return createGameAiAnalysis(payload);
});

// Read-only catalog bridge. The allowlist maps Studio panel names to host
// endpoints; arbitrary paths are never forwarded from the renderer.
const STUDIO_DATA_PATHS = Object.freeze({
  summary: '/api/v1/catalog',
  gifts: '/api/v1/catalog/gifts',
  games: '/api/v1/catalog/games',
  music: '/api/v1/music/library',
  templates: '/api/v1/studio/templates'
});

ipcMain.handle('studio:data-query', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  const kind = String(payload.kind || '');
  const dataPath = STUDIO_DATA_PATHS[kind];
  if (!dataPath) {
    return { ok: false, error: 'Unbekannte Datenabfrage.' };
  }
  try {
    const response = await fetch(STREAMIOV_API + dataPath, {
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
      const activeScene = snapshot.scenes.find(scene => scene.id === snapshot.programSceneId);
      programOutputWindow.webContents.send('studio:program-scene', activeScene || { name: 'STARTING SOON' });
    } catch (error) {
      console.error('[PROGRAM_OUTPUT] INITIAL_SCENE_FAILED', error);
    }
  });
  programOutputWindow.loadFile(path.join(__dirname, 'program-output.html')).catch(error => console.error('[PROGRAM_OUTPUT] LOAD_FAILED', error));
  programOutputWindow.on('closed', () => { programOutputWindow = null; });
  return { ok: true, externalDisplay: Boolean(display), displayBounds: bounds, outputWindowOpened: true, renderedVideo: false };
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

app.whenReady().then(() => {
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
  win.webContents.on('did-finish-load', () => console.error('[TRACE] DID_FINISH_LOAD', win.webContents.getURL()));
  win.webContents.on('render-process-gone', (_e, details) => console.error('[TRACE] RENDER_GONE', details));
  win.webContents.on('unresponsive', () => console.error('[TRACE] RENDER_UNRESPONSIVE'));
  win.webContents.on('did-fail-load', (_e, code, desc, url) => console.error('[TRACE] LOAD_FAILED', code, desc, url));
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

    console.error('[TRACE] NAVIGATION_REQUEST', url, 'ALLOWED:', allowed);

    if (!allowed) {
      console.error('[TRACE] NAVIGATION_BLOCKED', url);
      event.preventDefault();
    }
  });
});

app.on('before-quit', () => {
  if (liveStreamProcess) liveStreamProcess.kill('SIGINT');
  console.error('[TRACE] BEFORE_QUIT', new Error('before-quit-stack').stack);
});
app.on('will-quit', () => console.error('[TRACE] WILL_QUIT'));

app.on('window-all-closed', () => {
  console.error('[TRACE] WINDOW_ALL_CLOSED');
  if (process.platform !== 'darwin') app.quit();
});
