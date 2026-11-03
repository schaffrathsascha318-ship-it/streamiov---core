const { app, BrowserWindow, session, dialog, ipcMain, desktopCapturer } = require('electron');
const path = require('node:path');
const fs = require('node:fs/promises');
const { randomUUID } = require('node:crypto');
const os = require('node:os');
const http = require('node:http');
const { pathToFileURL } = require('node:url');
const { buildSyntheticAvPipelineArgs } = require('./media-pipeline');

const { execFile, spawn } = require('node:child_process');
const { promisify } = require('node:util');
const execFileAsync = promisify(execFile);
// In development this is the repository root. In an installed build it points
// at the packaged resources directory. Python module features are optional and
// must report a clear "not bundled" state instead of crashing.
const projectRoot = app.isPackaged
  ? process.resourcesPath
  : path.resolve(__dirname, '..', '..');
const studioUrl = pathToFileURL(path.join(__dirname, 'regie-v2.html')).href;
let liveStreamProcess = null;
let liveStreamState = 'offline';
let selectedDisplaySourceId = null;

async function missingPythonModules(relativePaths) {
  const missing = [];
  for (const relative of relativePaths) {
    try {
      await fs.access(path.join(projectRoot, relative));
    } catch {
      missing.push(relative);
    }
  }
  return missing;
}

function notBundledResult(missing) {
  return {
    ok: false,
    verification: 'not_bundled',
    error: 'Die Python-Module sind im installierten Studio nicht enthalten. ' +
      'Diese Funktion benötigt eine Entwicklungsinstallation mit modules/ und studio/.',
    missing
  };
}

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
  const SCENE_VERSION = 2;
  const MAX_SCENES = 100;
  const MAX_SOURCES = 30;
  const SOURCE_TYPES = new Set(['camera', 'screen', 'title', 'text']);
  const clamp = (value, min, max, fallback) => {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : fallback;
  };
  const titleSource = (text) => ({
    id: randomUUID(), type: 'title', name: 'Titelkarte', text,
    x: 0, y: 0, w: 1, h: 1, z: 0, visible: true
  });
  const cameraSource = (overrides = {}) => ({
    id: randomUUID(), type: 'camera', name: 'Kamera', text: '',
    x: 0, y: 0, w: 1, h: 1, z: 0, visible: true, ...overrides
  });
  const screenSource = (overrides = {}) => ({
    id: randomUUID(), type: 'screen', name: 'Bildschirm', text: '',
    x: 0, y: 0, w: 1, h: 1, z: 0, visible: true, ...overrides
  });
  const defaultSources = (sceneId, sceneName) => {
    if (sceneId === 'starting-soon') return [titleSource('STARTING SOON')];
    if (sceneId === 'pause') return [titleSource('PAUSE')];
    if (sceneId === 'ending') return [titleSource('ENDING')];
    if (sceneId === 'live') return [cameraSource()];
    if (sceneId === 'just-chatting') return [cameraSource({ name: 'Kamera' })];
    if (sceneId === 'gameplay') {
      return [screenSource(), cameraSource({ name: 'Kamera-Overlay', x: 0.72, y: 0.72, w: 0.25, h: 0.25, z: 1 })];
    }
    return [titleSource(sceneName)];
  };
  const defaults = () => {
    const scenes = [
      ['starting-soon', 'STARTING SOON'],
      ['live', 'LIVE'],
      ['pause', 'PAUSE'],
      ['ending', 'ENDING'],
      ['gameplay', 'GAMEPLAY'],
      ['just-chatting', 'JUST CHATTING']
    ].map(([id, name]) => ({
      id, name, kind: 'built-in', background: '#10151e', sources: defaultSources(id, name)
    }));
    return {
      version: SCENE_VERSION,
      scenes,
      previewSceneId: 'starting-soon',
      programSceneId: 'starting-soon',
      updatedAt: new Date().toISOString()
    };
  };

  const normalizeSource = (raw, index) => {
    if (!raw || typeof raw !== 'object' || !SOURCE_TYPES.has(raw.type)) return null;
    const id = typeof raw.id === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(raw.id) ? raw.id : randomUUID();
    const name = typeof raw.name === 'string' ? raw.name.trim().slice(0, 60) : '';
    const text = typeof raw.text === 'string' ? raw.text.slice(0, 200) : '';
    return {
      id,
      type: raw.type,
      name: name || raw.type,
      text,
      x: clamp(raw.x, 0, 0.95, 0),
      y: clamp(raw.y, 0, 0.95, 0),
      w: clamp(raw.w, 0.05, 1, 1),
      h: clamp(raw.h, 0.05, 1, 1),
      z: Math.trunc(clamp(raw.z, 0, 100, index)),
      visible: raw.visible !== false
    };
  };

  const normalizeScene = (raw) => {
    if (!raw || typeof raw.id !== 'string' || typeof raw.name !== 'string') return null;
    if (!/^[a-zA-Z0-9_-]{1,80}$/.test(raw.id)) return null;
    const name = raw.name.trim();
    if (!name || name.length > 60) return null;
    const sources = Array.isArray(raw.sources)
      ? raw.sources.map(normalizeSource).filter(Boolean).slice(0, MAX_SOURCES)
      : defaultSources(raw.id, name);
    return {
      id: raw.id,
      name,
      kind: raw.kind === 'custom' ? 'custom' : 'built-in',
      background: /^#[0-9a-fA-F]{6}$/.test(raw.background || '') ? raw.background : '#10151e',
      sources
    };
  };

  const normalize = (value) => {
    if (!value || ![1, SCENE_VERSION].includes(value.version) || !Array.isArray(value.scenes)) {
      return defaults();
    }
    const scenes = value.scenes.map(normalizeScene).filter(Boolean).slice(0, MAX_SCENES);
    if (!scenes.length) return defaults();
    const ids = new Set(scenes.map(s => s.id));
    return {
      version: SCENE_VERSION,
      scenes,
      previewSceneId: ids.has(value.previewSceneId) ? value.previewSceneId : scenes[0].id,
      programSceneId: ids.has(value.programSceneId) ? value.programSceneId : scenes[0].id,
      updatedAt: typeof value.updatedAt === 'string' ? value.updatedAt : new Date().toISOString()
    };
  };

  const save = async (state) => {
    state.updatedAt = new Date().toISOString();
    await fs.mkdir(path.dirname(file), { recursive: true });
    const temp = file + '.' + process.pid + '.tmp';
    await fs.writeFile(temp, JSON.stringify(state, null, 2), { mode: 0o600 });
    await fs.rename(temp, file);
  };

  let state;
  try {
    state = normalize(JSON.parse(await fs.readFile(file, 'utf8')));
  } catch (error) {
    if (error.code !== 'ENOENT') {
      return { ok: false, error: 'Szenendatei konnte nicht gelesen werden: ' + String(error.message || error) };
    }
    state = defaults();
    await save(state);
  }

  const sceneById = (id) => state.scenes.find(s => s.id === id);
  const sceneByName = (name) => state.scenes.find(s => s.name === name);
  const action = payload && payload.action;
  if (action === 'load') {
    return { ok: true, state };
  }

  if (action === 'select') {
    const name = typeof payload.name === 'string' ? payload.name.trim() : '';
    const id = typeof payload.id === 'string' ? payload.id : '';
    const scene = sceneByName(name) || sceneById(id);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    state.previewSceneId = scene.id;
  } else if (action === 'take') {
    state.programSceneId = state.previewSceneId;
  } else if (action === 'create') {
    const name = typeof payload.name === 'string' ? payload.name.trim() : '';
    if (!name || name.length > 60) {
      return { ok: false, error: 'Szenenname muss 1 bis 60 Zeichen lang sein.' };
    }
    if (state.scenes.length >= MAX_SCENES) {
      return { ok: false, error: 'Maximal ' + MAX_SCENES + ' Szenen sind möglich.' };
    }
    if (state.scenes.some(s => s.name.toLowerCase() === name.toLowerCase())) {
      return { ok: false, error: 'Eine Szene mit diesem Namen existiert bereits.' };
    }
    const scene = {
      id: randomUUID(), name, kind: 'custom', background: '#10151e',
      sources: defaultSources('custom', name)
    };
    state.scenes.push(scene);
    state.previewSceneId = scene.id;
  } else if (action === 'add-source') {
    const scene = sceneById(state.previewSceneId);
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    if (scene.sources.length >= MAX_SOURCES) {
      return { ok: false, error: 'Maximal ' + MAX_SOURCES + ' Quellen pro Szene sind möglich.' };
    }
    const source = normalizeSource({ ...payload.source, id: randomUUID() }, scene.sources.length);
    if (!source) return { ok: false, error: 'Unbekannter Quellentyp.' };
    source.z = scene.sources.reduce((max, item) => Math.max(max, item.z), -1) + 1;
    scene.sources.push(source);
  } else if (action === 'update-source') {
    const scene = sceneById(state.previewSceneId);
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    const source = scene.sources.find(s => s.id === payload.sourceId);
    if (!source) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
    const patch = payload.patch && typeof payload.patch === 'object' ? payload.patch : {};
    if (typeof patch.name === 'string' && patch.name.trim()) source.name = patch.name.trim().slice(0, 60);
    if (typeof patch.text === 'string') source.text = patch.text.slice(0, 200);
    for (const key of ['x', 'y', 'w', 'h', 'z']) {
      if (patch[key] !== undefined) {
        source[key] = key === 'z'
          ? Math.trunc(clamp(patch[key], 0, 100, source[key]))
          : clamp(patch[key], key === 'w' || key === 'h' ? 0.05 : 0, key === 'w' || key === 'h' ? 1 : 0.95, source[key]);
      }
    }
    if (patch.visible !== undefined) source.visible = patch.visible !== false;
  } else if (action === 'remove-source') {
    const scene = sceneById(state.previewSceneId);
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    const before = scene.sources.length;
    scene.sources = scene.sources.filter(s => s.id !== payload.sourceId);
    if (scene.sources.length === before) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
  } else if (action === 'move-source') {
    const scene = sceneById(state.previewSceneId);
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    const index = scene.sources.findIndex(s => s.id === payload.sourceId);
    if (index < 0) return { ok: false, error: 'Quelle wurde nicht gefunden.' };
    const target = payload.direction === 'up' ? index + 1 : index - 1;
    if (target >= 0 && target < scene.sources.length) {
      const [source] = scene.sources.splice(index, 1);
      scene.sources.splice(target, 0, source);
      scene.sources.forEach((item, order) => { item.z = order; });
    }
  } else if (action === 'set-background') {
    const scene = sceneById(state.previewSceneId);
    if (!scene) return { ok: false, error: 'Vorschauszene wurde nicht gefunden.' };
    if (!/^#[0-9a-fA-F]{6}$/.test(payload.color || '')) {
      return { ok: false, error: 'Hintergrundfarbe muss ein Hex-Wert wie #10151e sein.' };
    }
    scene.background = payload.color;
  } else if (action === 'delete-scene') {
    const scene = sceneById(payload.id);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    if (scene.kind !== 'custom') return { ok: false, error: 'Eingebaute Szenen können nicht gelöscht werden.' };
    if (state.scenes.length <= 1) return { ok: false, error: 'Mindestens eine Szene muss bestehen bleiben.' };
    state.scenes = state.scenes.filter(s => s.id !== scene.id);
    if (state.previewSceneId === scene.id) state.previewSceneId = state.scenes[0].id;
    if (state.programSceneId === scene.id) state.programSceneId = state.scenes[0].id;
  } else if (action === 'rename-scene') {
    const scene = sceneById(payload.id);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    if (scene.kind !== 'custom') return { ok: false, error: 'Eingebaute Szenen können nicht umbenannt werden.' };
    const name = typeof payload.name === 'string' ? payload.name.trim() : '';
    if (!name || name.length > 60) return { ok: false, error: 'Szenenname muss 1 bis 60 Zeichen lang sein.' };
    if (state.scenes.some(s => s.id !== scene.id && s.name.toLowerCase() === name.toLowerCase())) {
      return { ok: false, error: 'Eine Szene mit diesem Namen existiert bereits.' };
    }
    scene.name = name;
  } else {
    return { ok: false, error: 'Unbekannte Szenenaktion.' };
  }

  await save(state);
  return { ok: true, state };
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

// Crostini-Kompatibilität: GPU-Beschleunigung vor app.whenReady deaktivieren.
app.disableHardwareAcceleration();

ipcMain.handle('studio:get-module-status', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const missing = await missingPythonModules(['studio/modules/module_loader.py']);
  if (missing.length) return notBundledResult(missing);

  const code =
    'import json; from studio.modules.module_loader import ModuleLoader; ' +
    'loader = ModuleLoader(); result = loader.load_modules(); ' +
    'print(json.dumps({"ok": True, "verification": "discovery_only", ' +
    '"modules": result}, ensure_ascii=False))';

  try {
    const { stdout } = await execFileAsync(
      'python3',
      ['-c', code],
      { cwd: projectRoot, timeout: 15000, maxBuffer: 1048576 }
    );
    const report = JSON.parse(stdout.trim());
    return {
      ok: true,
      verification: 'discovery_only',
      note: 'Dateien gefunden; Funktion und Integration nicht automatisch verifiziert.',
      modules: report.modules
    };
  } catch (error) {
    return {
      ok: false,
      verification: 'failed',
      error: String(error.message || error).slice(0, 1000)
    };
  }
});

ipcMain.handle('studio:get-status', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }

  const missing = await missingPythonModules(['modules/broadcast/gstreamer_engine.py']);
  if (missing.length) {
    return {
      ok: false,
      bridge: 'not_bundled',
      backend: { connected: false, error: notBundledResult(missing).error }
    };
  }

  const code =
    'import json; from modules.broadcast.gstreamer_engine import GStreamerEngine; ' +
    'print(json.dumps(GStreamerEngine().status()))';

  try {
    const { stdout } = await execFileAsync(
      'python3',
      ['-c', code],
      { cwd: projectRoot, timeout: 15000, maxBuffer: 1048576 }
    );

    const engine = JSON.parse(stdout.trim());
    return {
      ok: true,
      bridge: 'ready',
      backend: { connected: true, engine }
    };
  } catch (error) {
    return {
      ok: false,
      bridge: 'ready',
      backend: {
        connected: false,
        error: String(error.message || error).slice(0, 1000)
      }
    };
  }
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

  const missing = await missingPythonModules(['modules/broadcast/gstreamer_engine.py']);
  if (missing.length) {
    return { ok: false, stage: 'not_bundled', error: notBundledResult(missing).error, missing };
  }

  const chosen = await dialog.showOpenDialog({
    title: 'Musikdatei für den Streamiov-Mischtest auswählen',
    properties: ['openFile'],
    filters: [{
      name: 'Audiodateien',
      extensions: ['wav', 'mp3', 'ogg', 'opus', 'flac', 'm4a', 'aac']
    }]
  });

  if (chosen.canceled || !chosen.filePaths.length) {
    return { ok: false, cancelled: true, stage: 'file_selection' };
  }

  const volume = Number(payload.volume);
  if (!Number.isFinite(volume) || volume < 0 || volume > 1) {
    return { ok: false, stage: 'input', error: 'Ungültige Lautstärke.' };
  }

  const code =
    'import json,sys; from modules.broadcast.gstreamer_engine import GStreamerEngine; ' +
    'print(json.dumps(GStreamerEngine().record_music_test(sys.argv[1], float(sys.argv[2]))))';

  try {
    const { stdout } = await execFileAsync(
      'python3',
      ['-c', code, chosen.filePaths[0], String(volume)],
      { cwd: projectRoot, timeout: 105000, maxBuffer: 1048576 }
    );
    return JSON.parse(stdout.trim());
  } catch (error) {
    return {
      ok: false,
      stage: 'bridge_error',
      error: String(error.message || error).slice(0, 1000),
      live_stream_verified: false
    };
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

  const missing = await missingPythonModules(['modules/devices/universal_hub.py']);
  if (missing.length) {
    return { ok: false, stage: 'not_bundled', error: notBundledResult(missing).error, missing };
  }

  const code =
    'import json; from modules.devices.universal_hub import UniversalDeviceHub; ' +
    'report = UniversalDeviceHub().scan(include_network=True); ' +
    'devices = report["devices"]; ' +
    'cameras = [d for d in devices if d["type"] == "camera"]; ' +
    'print(json.dumps({'
    + '"devices": devices, '
    + '"local_camera_count": len(cameras), '
    + '"network_report": report.get("network_report", {}), '
    + '"network_discovery": report.get("network_discovery"), '
    + '"platform": report.get("platform"), '
    + '"protocols": {}, '
    + '"live_stream_verified": False, '
    + '"note": "Lokale Geräteerkennung und passiver Netzwerk-Cache; kein aktiver Netzwerk-Scan und kein Livebildtest"'
    + '}))';

  try {
    const { stdout } = await execFileAsync(
      'python3',
      ['-c', code],
      { cwd: projectRoot, timeout: 15000, maxBuffer: 1048576 }
    );
    return { ok: true, report: JSON.parse(stdout.trim()) };
  } catch (error) {
    return {
      ok: false,
      error: String(error.message || error).slice(0, 1000)
    };
  }
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

  mainWindow = new BrowserWindow({
    x: 100,
    y: 80,
    width: 1600,
    height: 900,
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
