'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('streamiovProgramOutput', Object.freeze({
  onScene: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, scene) => callback(scene);
    ipcRenderer.on('studio:program-scene', listener);
    return () => ipcRenderer.removeListener('studio:program-scene', listener);
  }
}));
