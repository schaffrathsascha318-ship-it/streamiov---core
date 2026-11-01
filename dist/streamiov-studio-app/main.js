const { app, BrowserWindow, session, dialog, ipcMain } = require('electron');
const path = require('node:path');
const fs = require('node:fs/promises');
const { randomUUID } = require('node:crypto');
const os = require('node:os');
const http = require('node:http');
const { pathToFileURL } = require('node:url');

const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const execFileAsync = promisify(execFile);
const projectRoot = path.resolve(__dirname, '..', '..');
const studioUrl = pathToFileURL(path.join(__dirname, 'index.html')).href;

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
  const defaults = () => ({
    version: 1,
    scenes: [
      { id: 'standard', name: 'Streamiov Standard', kind: 'built-in' },
      { id: 'gameplay', name: 'Gameplay', kind: 'built-in' },
      { id: 'fullscreen', name: 'Full Screen', kind: 'built-in' }
    ],
    previewSceneId: 'standard',
    programSceneId: 'standard',
    updatedAt: new Date().toISOString()
  });

  const normalize = (value) => {
    if (!value || value.version !== 1 || !Array.isArray(value.scenes)) return defaults();
    const scenes = value.scenes
      .filter(s => s && typeof s.id === 'string' && typeof s.name === 'string')
      .filter(s => /^[a-zA-Z0-9_-]{1,80}$/.test(s.id))
      .filter(s => s.name.trim().length > 0 && s.name.length <= 60)
      .slice(0, 100)
      .map(s => ({
        id: s.id,
        name: s.name.trim(),
        kind: s.kind === 'custom' ? 'custom' : 'built-in'
      }));

    if (!scenes.length) return defaults();
    const ids = new Set(scenes.map(s => s.id));
    return {
      version: 1,
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

  const action = payload && payload.action;
  if (action === 'load') {
    return { ok: true, state };
  }

  if (action === 'select') {
    const name = typeof payload.name === 'string' ? payload.name.trim() : '';
    const scene = state.scenes.find(s => s.name === name);
    if (!scene) return { ok: false, error: 'Szene wurde nicht gefunden.' };
    state.previewSceneId = scene.id;
  } else if (action === 'take') {
    state.programSceneId = state.previewSceneId;
  } else if (action === 'create') {
    const name = typeof payload.name === 'string' ? payload.name.trim() : '';
    if (!name || name.length > 60) {
      return { ok: false, error: 'Szenenname muss 1 bis 60 Zeichen lang sein.' };
    }
    if (state.scenes.length >= 100) {
      return { ok: false, error: 'Maximal 100 Szenen sind möglich.' };
    }
    if (state.scenes.some(s => s.name.toLowerCase() === name.toLowerCase())) {
      return { ok: false, error: 'Eine Szene mit diesem Namen existiert bereits.' };
    }
    const scene = { id: randomUUID(), name, kind: 'custom' };
    state.scenes.push(scene);
    state.previewSceneId = scene.id;
  } else {
    return { ok: false, error: 'Unbekannte Szenenaktion.' };
  }

  await save(state);
  return { ok: true, state };
});



/**
 * STREAMIOV_TIKTOK_STUDIO_BRIDGE
 * Native Electron OAuth callback. Credentials are read only from process.env;
 * tokens are handled by the encrypted OAuth service in the main process.
 */
const { shell } = require('electron');
const { TikTokOAuth } = require('./tiktok-oauth.js');
let tikTokOAuth = null;
let tikTokCallbackServer = null;
let tikTokConnectInProgress = false;

function getTikTokOAuth() {
  if (!tikTokOAuth) {
    tikTokOAuth = new TikTokOAuth({
      environment: 'sandbox',
      env: process.env
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
    await shell.openExternal(authorization.url);
    return { ok: true, status: 'authorization_opened', environment: 'sandbox' };
  } catch (error) {
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

  const code =
    'import json; from modules.broadcast.gstreamer_engine import GStreamerEngine; ' +
    'print(json.dumps(GStreamerEngine().record_test_av(duration_seconds=3)))';

  try {
    const { stdout } = await execFileAsync(
      'python3',
      ['-c', code],
      { cwd: projectRoot, timeout: 45000, maxBuffer: 1048576 }
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

ipcMain.handle('studio:record-music-test', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
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
const STREAMIOV_API = 'http://127.0.0.1:8080';
let streamiovSessionToken = null;
let streamiovSessionUser = null;

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
    const response = await fetch(STREAMIOV_API + '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      signal: AbortSignal.timeout(10000)
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok || data.status !== 'authenticated' || !data.token) {
      return {
        ok: false,
        error: data.message || data.error || 'Anmeldung fehlgeschlagen.'
      };
    }

    if (!data.user || data.user.role !== 'streamer') {
      streamiovSessionToken = null;
      streamiovSessionUser = null;
      return { ok: false, error: 'Für den KI-Manager ist ein Streamer-Konto erforderlich.' };
    }

    streamiovSessionToken = data.token;
    streamiovSessionUser = {
      username: data.user.username || data.user.name || username,
      role: data.user.role,
      expires_at: data.expires_at || null
    };

    return { ok: true, user: streamiovSessionUser };
  } catch (error) {
    return {
      ok: false,
      error: 'Streamiov-Server nicht erreichbar: ' + String(error.message || error).slice(0, 250)
    };
  }
});

ipcMain.handle('studio:ai-logout', async (event) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  if (streamiovSessionToken) {
    try {
      await fetch(STREAMIOV_API + '/api/auth/logout', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + streamiovSessionToken },
        signal: AbortSignal.timeout(5000)
      });
    } catch {}
  }
  streamiovSessionToken = null;
  streamiovSessionUser = null;
  return { ok: true };
});

ipcMain.handle('studio:ai-submit', async (event, payload = {}) => {
  if (!isTrustedStudioSender(event)) {
    throw new Error('Nicht autorisierter Studio-Aufruf');
  }
  if (!streamiovSessionToken) {
    return { ok: false, error: 'Bitte zuerst im KI-Manager anmelden.' };
  }

  const request = String(payload.request || '').trim();
  if (!request || request.length > 2000) {
    return { ok: false, error: 'Auftrag muss zwischen 1 und 2000 Zeichen lang sein.' };
  }

  try {
    const response = await fetch(STREAMIOV_API + '/api/ai/wunschbox', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + streamiovSessionToken
      },
      body: JSON.stringify({ request }),
      signal: AbortSignal.timeout(30000)
    });

    const data = await response.json().catch(() => ({}));

    if (response.status === 401) {
      streamiovSessionToken = null;
      streamiovSessionUser = null;
    }

    return {
      ok: response.ok,
      statusCode: response.status,
      data,
      error: response.ok ? null : (data.error || 'KI-Anfrage fehlgeschlagen.')
    };
  } catch (error) {
    return {
      ok: false,
      error: 'KI-Server nicht erreichbar: ' + String(error.message || error).slice(0, 250)
    };
  }
});
// STREAMIOV_STUDIO_AI_BRIDGE_END


let mainWindow = null;

app.whenReady().then(() => {
  const ses = session.defaultSession;

  ses.setPermissionRequestHandler((webContents, permission, callback) => {
    const trusted = webContents.getURL() === studioUrl;
    callback(permission === 'media' && trusted);
  });

  ses.setPermissionCheckHandler((webContents, permission) => {
    return permission === 'media' && webContents.getURL() === studioUrl;
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
  win.loadFile(path.join(__dirname, 'index.html')).catch(e => console.error('[TRACE] LOAD_PROMISE_REJECTED', e));

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

app.on('before-quit', () => console.error('[TRACE] BEFORE_QUIT', new Error('before-quit-stack').stack));
app.on('will-quit', () => console.error('[TRACE] WILL_QUIT'));

app.on('window-all-closed', () => {
  console.error('[TRACE] WINDOW_ALL_CLOSED');
  if (process.platform !== 'darwin') app.quit();
});
