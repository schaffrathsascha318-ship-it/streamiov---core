
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('streamiovStudio', Object.freeze({
  getStatus: () => ipcRenderer.invoke('studio:get-status'),
  getRuntimeDiagnostics: () => ipcRenderer.invoke('studio:get-runtime-diagnostics'),
  runMediaTest: () => ipcRenderer.invoke('studio:run-media-test'),
  recordMusicTest: (payload) => ipcRenderer.invoke('studio:record-music-test', payload),
  getCameraLab: () => ipcRenderer.invoke('studio:get-camera-lab'),
  getNetworkStatus: () => ipcRenderer.invoke('studio:get-network-status'),
  getModuleStatus: () => ipcRenderer.invoke('studio:get-module-status'),
  chatAction: (payload) => ipcRenderer.invoke('studio:chat-action', payload),
  sceneAction: (payload) => ipcRenderer.invoke('studio:scene-action', payload),
  startStream: (payload) => ipcRenderer.invoke('studio:start-stream', payload),
  writeStreamChunk: (chunk) => ipcRenderer.invoke('studio:write-stream-chunk', chunk),
  stopStream: () => ipcRenderer.invoke('studio:stop-stream'),
  listDisplaySources: () => ipcRenderer.invoke('studio:list-display-sources'),
  selectDisplaySource: (sourceId) => ipcRenderer.sendSync('studio:select-display-source', sourceId),
  onStreamStatus: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, status) => callback(status);
    ipcRenderer.on('studio:stream-status', listener);
    return () => ipcRenderer.removeListener('studio:stream-status', listener);
  },
  aiLogin: (payload) => ipcRenderer.invoke('studio:ai-login', payload),
  aiLogout: () => ipcRenderer.invoke('studio:ai-logout'),
  aiSubmit: (payload) => ipcRenderer.invoke('studio:ai-submit', payload)
}));

