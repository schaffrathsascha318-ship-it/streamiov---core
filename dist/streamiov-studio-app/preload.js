
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('streamiovStudio', Object.freeze({
  getStatus: () => ipcRenderer.invoke('studio:get-status'),
  getPlatformOutputStatus: () => ipcRenderer.invoke('studio:platform-output-status'),
  twitchStatus: () => ipcRenderer.invoke('studio:twitch-status'),
  twitchConnect: () => ipcRenderer.invoke('studio:twitch-connect'),
  twitchAuthorizeChat: () => ipcRenderer.invoke('studio:twitch-connect', { chat: true, events: true }),
  twitchDisconnect: () => ipcRenderer.invoke('studio:twitch-disconnect'),
  twitchPrepareOutput: () => ipcRenderer.invoke('studio:twitch-prepare-output'),
  onTwitchAuthResult: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, result) => callback(result);
    ipcRenderer.on('studio:twitch-auth-result', listener);
    return () => ipcRenderer.removeListener('studio:twitch-auth-result', listener);
  },
  getDisplays: () => ipcRenderer.invoke('studio:get-displays'),
  openProgramOutput: () => ipcRenderer.invoke('studio:open-program-output'),
  moveRegieToDisplay: (displayId) => ipcRenderer.invoke('studio:move-regie-to-display', { displayId }),
  getRuntimeDiagnostics: () => ipcRenderer.invoke('studio:get-runtime-diagnostics'),
  getDeviceCapabilities: (measurements) => ipcRenderer.invoke('studio:get-device-capabilities', measurements),
  runMediaTest: () => ipcRenderer.invoke('studio:run-media-test'),
  recordMusicTest: (payload) => ipcRenderer.invoke('studio:record-music-test', payload),
  getCameraLab: () => ipcRenderer.invoke('studio:get-camera-lab'),
  getNetworkStatus: () => ipcRenderer.invoke('studio:get-network-status'),
  updateStatus: () => ipcRenderer.invoke('studio:update-status'),
  checkUpdate: () => ipcRenderer.invoke('studio:update-check'),
  prepareUpdate: () => ipcRenderer.invoke('studio:update-prepare'),
  installUpdate: () => ipcRenderer.invoke('studio:update-install'),
  clearUpdateError: () => ipcRenderer.invoke('studio:update-clear-error'),
  openRelease: () => ipcRenderer.invoke('studio:update-open-release'),
  getModuleStatus: () => ipcRenderer.invoke('studio:get-module-status'),
  chatAction: (payload) => ipcRenderer.invoke('studio:chat-action', payload),
  chatStatus: () => ipcRenderer.invoke('studio:chat-action', { action: 'status' }),
  chatSend: (text, targets) => ipcRenderer.invoke('studio:chat-action', { action: 'send', text, targets }),
  onChatMessage: handler => {
    const listener = (_event, message) => handler(message);
    ipcRenderer.on('studio:chat-message', listener);
    return () => ipcRenderer.removeListener('studio:chat-message', listener);
  },
  onChatModeration: handler => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('studio:chat-moderation', listener);
    return () => ipcRenderer.removeListener('studio:chat-moderation', listener);
  },
  sceneAction: (payload) => ipcRenderer.invoke('studio:scene-action', payload),
  listMediaAssets: () => ipcRenderer.invoke('studio:list-media-assets'),
  importMediaAssets: (payload) => ipcRenderer.invoke('studio:import-media-assets', payload),
  removeMediaAsset: (id) => ipcRenderer.invoke('studio:remove-media-asset', { id }),
  sendProgramFrame: (frame) => {
    if (frame instanceof Uint8Array) return ipcRenderer.invoke('studio:program-frame', { bytes: frame });
    if (frame instanceof ArrayBuffer) return ipcRenderer.invoke('studio:program-frame', { bytes: new Uint8Array(frame) });
    if (typeof frame === 'string') return ipcRenderer.invoke('studio:program-frame', { dataUrl: frame });
    return Promise.resolve({ ok: false, error: 'Ungültiges Programmbild.' });
  },
  getStreamStatus: () => ipcRenderer.invoke('studio:get-stream-status'),
  startStream: (payload) => ipcRenderer.invoke('studio:start-stream', {
    platforms: Array.isArray(payload?.platforms) ? payload.platforms : (payload?.platform ? [payload.platform] : []),
    resolution: payload?.resolution,
    fps: payload?.fps,
    bitrate: payload?.bitrate
  }),
  writeStreamChunk: (chunk) => ipcRenderer.invoke('studio:write-stream-chunk', chunk),
  recordChunk: (chunk) => ipcRenderer.invoke('studio:record-chunk', chunk),
  recordingStatus: () => ipcRenderer.invoke('studio:recording-status'),
  recordingAction: (action) => ipcRenderer.invoke('studio:recording-action', action),
  recordingList: () => ipcRenderer.invoke('studio:recording-list'),
  recordingFileAction: (id, action) => ipcRenderer.invoke('studio:recording-file-action', { id, action }),
  stopStream: () => ipcRenderer.invoke('studio:stop-stream'),
  listDisplaySources: () => ipcRenderer.invoke('studio:list-display-sources'),
  selectDisplaySource: (sourceId) => ipcRenderer.sendSync('studio:select-display-source', sourceId),
  onStreamStatus: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, status) => callback(status);
    ipcRenderer.on('studio:stream-status', listener);
    return () => ipcRenderer.removeListener('studio:stream-status', listener);
  },
  wishboxOrders: (payload) => ipcRenderer.invoke('studio:wishbox-orders', {
    limit: Number.isInteger(payload?.limit) ? payload.limit : 25,
    kind: payload?.kind === 'music' || payload?.kind === 'game' ? payload.kind : undefined
  }),
  wishboxSubmit: (payload) => {
    const { text, sender, source, territory, priority } = payload || {};
    return ipcRenderer.invoke('studio:wishbox-submit', { text, sender, source, territory, priority });
  },
  wishboxAction: (payload) => ipcRenderer.invoke('studio:wishbox-action', {
    action: payload?.action,
    orderId: payload?.orderId,
    reason: payload?.reason,
    answer: payload?.answer,
    result: payload?.result,
    agent: payload?.agent
  }),
  wishboxHandoffs: (payload) => ipcRenderer.invoke('studio:wishbox-handoffs', {
    limit: Number.isInteger(payload?.limit) ? payload.limit : 25
  }),
  authStatus: () => ipcRenderer.invoke('studio:auth-status'),
  dataQuery: (payload) => ipcRenderer.invoke('studio:data-query', payload),
  musicState: (payload) => ipcRenderer.invoke('studio:music-state', payload),
  eventPublish: (payload) => ipcRenderer.invoke('studio:event-publish', {
    type: payload?.type,
    data: payload?.data,
    severity: payload?.severity
  }),
  eventList: (payload) => ipcRenderer.invoke('studio:event-list', {
    limit: Number.isInteger(payload?.limit) ? payload.limit : 50
  }),
  sourceAction: (payload) => ipcRenderer.invoke('studio:source-action', payload),
  gameAnalysis: (payload) => ipcRenderer.invoke('studio:game-analysis', payload),
  aiLogin: (payload) => ipcRenderer.invoke('studio:ai-login', payload),
  aiLogout: () => ipcRenderer.invoke('studio:ai-logout'),
  aiSubmit: (payload) => ipcRenderer.invoke('studio:ai-submit', payload),
  tiktokStatus: () => ipcRenderer.invoke('studio:tiktok-status'),
  tiktokConnect: () => ipcRenderer.invoke('studio:tiktok-connect'),
  tiktokPrepareOutput: () => ipcRenderer.invoke('studio:tiktok-prepare-output'),
  tiktokDisconnect: () => ipcRenderer.invoke('studio:tiktok-disconnect'),
  onTikTokAuthResult: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, result) => callback(result);
    ipcRenderer.on('studio:tiktok-auth-result', listener);
    return () => ipcRenderer.removeListener('studio:tiktok-auth-result', listener);
  }
}));

