'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('streamiovProgramOutput', Object.freeze({
  onScene: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, scene) => callback(scene);
    ipcRenderer.on('studio:program-scene', listener);
    return () => ipcRenderer.removeListener('studio:program-scene', listener);
  },
  onAssets: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('studio:program-assets', listener);
    return () => ipcRenderer.removeListener('studio:program-assets', listener);
  },
  onFrame: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, frame) => callback(frame);
    ipcRenderer.on('studio:program-frame', listener);
    return () => ipcRenderer.removeListener('studio:program-frame', listener);
  }
}));
