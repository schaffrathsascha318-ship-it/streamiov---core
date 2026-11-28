'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');

function loadStudioMain({ env = {}, fetchImpl = globalThis.fetch, userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'streamiov-studio-main-')), childProcessImpl = {} } = {}) {
  const studioDir = path.resolve(__dirname, '..');
  const mainPath = path.join(studioDir, 'main.js');
  const studioUrl = pathToFileURL(path.join(studioDir, 'regie-v2.html')).href;
  const handlers = new Map();
  const sentEvents = [];
  let resolveReady = null;
  const proc = Object.create(process);
  proc.env = { ...process.env, ...env };

  const webContents = () => ({
    on() {}, once() {}, send: (channel, payload) => sentEvents.push({ channel, payload }), getURL: () => studioUrl,
    setWindowOpenHandler() {}, loadFile: async () => {}, openDevTools() {}
  });

  class BrowserWindow {
    constructor() {
      this.webContents = webContents();
      this.isDestroyed = () => false;
      this.isFocused = () => true;
      this.focus = () => {};
      this.setMenuBarVisibility = () => {};
      this.close = () => {};
      this.on = () => {};
      this.once = () => {};
      this.loadFile = async () => {};
    }
    static getAllWindows() { return []; }
  }

  const electron = {
    app: {
      disableHardwareAcceleration() {},
      whenReady: () => new Promise((resolve) => { resolveReady = resolve; }),
      getAppPath: () => studioDir,
      getPath: (name) => name === 'userData' ? userDataDir : path.join(userDataDir, name),
      getVersion: () => '1.0.4',
      getName: () => 'Streamiov Studio',
      isPackaged: false,
      on() {}, quit() {}
    },
    BrowserWindow,
    session: {
      defaultSession: {
        setPermissionRequestHandler() {},
        setPermissionCheckHandler() {},
        setDisplayMediaRequestHandler() {}
      }
    },
    ipcMain: {
      handle: (name, handler) => handlers.set(name, handler),
      on() {}, once() {}, removeHandler() {}
    },
    desktopCapturer: { getSources: async () => [] },
    screen: {
      getAllDisplays: () => [],
      getPrimaryDisplay: () => ({
        id: 1,
        bounds: { x: 0, y: 0, width: 1280, height: 720 },
        workArea: { x: 0, y: 0, width: 1280, height: 720 },
        scaleFactor: 1
      }),
      on() {}
    },
    shell: { openExternal: async () => ({}), openPath: async () => '', showItemInFolder() {} },
    Notification: { isSupported: () => false }
  };

  const projectRequire = createRequire(mainPath);
  const injectedChildProcess = Object.assign({}, require('node:child_process'), childProcessImpl);
  const sandbox = {
    require: (id) => id === 'electron' ? electron : id === 'node:child_process' ? injectedChildProcess : projectRequire(id),
    process: proc,
    console,
    Buffer,
    URL,
    URLSearchParams,
    AbortSignal,
    TextEncoder,
    TextDecoder,
    fetch: fetchImpl,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    queueMicrotask,
    module: { exports: {} },
    exports: {},
    __dirname: studioDir
  };
  vm.createContext(sandbox);
  const source = fs.readFileSync(mainPath, 'utf8');
  vm.runInContext(source, sandbox, { filename: mainPath });

  const event = {
    sender: { getURL: () => studioUrl },
    senderFrame: { parent: null, url: studioUrl }
  };

  return {
    source,
    studioUrl,
    userDataDir,
    handlers,
    sentEvents,
    ready: async () => {
      if (resolveReady) resolveReady();
      await new Promise((resolve) => setImmediate(resolve));
    },
    invoke: (name, payload = {}) => {
      const handler = handlers.get(name);
      if (!handler) throw new Error(`Unknown Studio IPC handler: ${name}`);
      return handler(event, payload);
    }
  };
}

module.exports = { loadStudioMain };
