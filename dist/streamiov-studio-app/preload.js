
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('streamiovStudio', Object.freeze({
  getStatus: () => ipcRenderer.invoke('studio:get-status'),
  getDisplays: () => ipcRenderer.invoke('studio:get-displays'),
  openProgramOutput: () => ipcRenderer.invoke('studio:open-program-output'),
  moveRegieToDisplay: (displayId) => ipcRenderer.invoke('studio:move-regie-to-display', { displayId }),
  getRuntimeDiagnostics: () => ipcRenderer.invoke('studio:get-runtime-diagnostics'),
  runMediaTest: () => ipcRenderer.invoke('studio:run-media-test'),
  recordMusicTest: (payload) => ipcRenderer.invoke('studio:record-music-test', payload),
  getCameraLab: () => ipcRenderer.invoke('studio:get-camera-lab'),
  getNetworkStatus: () => ipcRenderer.invoke('studio:get-network-status'),
  getModuleStatus: () => ipcRenderer.invoke('studio:get-module-status'),
  chatAction: (payload) => ipcRenderer.invoke('studio:chat-action', payload),
  sceneAction: (payload) => ipcRenderer.invoke('studio:scene-action', payload),
  sourceAction: (payload) => ipcRenderer.invoke('studio:source-action', payload),
  listGames: () => ipcRenderer.invoke('studio:list-games'),
  openGame: (id) => ipcRenderer.invoke('studio:open-game', { id }),
  aiLogin: (payload) => ipcRenderer.invoke('studio:ai-login', payload),
  aiLogout: () => ipcRenderer.invoke('studio:ai-logout'),
  aiSubmit: (payload) => ipcRenderer.invoke('studio:ai-submit', payload),
  tiktokStatus: () => ipcRenderer.invoke('studio:tiktok-status'),
  tiktokConnect: () => ipcRenderer.invoke('studio:tiktok-connect'),
  tiktokDisconnect: () => ipcRenderer.invoke('studio:tiktok-disconnect'),
  onTikTokAuthResult: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, result) => callback(result);
    ipcRenderer.on('studio:tiktok-auth-result', listener);
    return () => ipcRenderer.removeListener('studio:tiktok-auth-result', listener);
  }
}));

