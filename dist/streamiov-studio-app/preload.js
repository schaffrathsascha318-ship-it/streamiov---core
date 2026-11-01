
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
  sourceAction: (payload) => ipcRenderer.invoke('studio:source-action', payload),
  aiLogin: (payload) => ipcRenderer.invoke('studio:ai-login', payload),
  aiLogout: () => ipcRenderer.invoke('studio:ai-logout'),
  aiSubmit: (payload) => ipcRenderer.invoke('studio:ai-submit', payload)
}));

