'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');
const main = fs.readFileSync(require.resolve('../main.js'), 'utf8');
const preload = fs.readFileSync(require.resolve('../preload.js'), 'utf8');

test('Regie loads the local mixer and routes microphone capture into it', () => {
  assert.ok(html.includes('<script src="./engine/audio-mixer.js"></script>'));
  assert.ok(html.includes('connectAudioSource("microphone",stream'));
  assert.ok(html.includes('studioAudioMixer.disconnect("microphone")'));
  assert.ok(html.includes('studioAudioMixer.setGain(name,state.gain/100)'));
  assert.ok(html.includes('noch nicht mit Encoder/LIVE verbunden'));
});

test('local mixer output is not falsely reported as a live encoder connection', () => {
  assert.ok(html.includes('Audio-Ausgang vorbereitet; noch nicht mit Encoder/LIVE verbunden'));
});

test('Regie exposes selectable local monitor output controls', () => {
  assert.ok(html.includes('id="audioMonitorDevice"'));
  assert.ok(html.includes('id="audioMonitorConnect"'));
  assert.ok(html.includes('id="audioMonitorDisconnect"'));
  assert.ok(html.includes('studioAudioMixer.attachMonitor(monitorElement'));
  assert.ok(html.includes('studioAudioMixer.detachMonitor(monitorElement)'));
});

test('Regie connects local music and alert media files to their own mixer channels', () => {
  assert.ok(html.includes('id="musicAudioFile"'));
  assert.ok(html.includes('id="musicAudioPlayer"'));
  assert.ok(html.includes('id="alertAudioFile"'));
  assert.ok(html.includes('id="alertAudioPlayer"'));
  assert.ok(html.includes('bindMediaFile("music"'));
  assert.ok(html.includes('bindMediaFile("alerts"'));
  assert.ok(html.includes('connectAudioSource(channel,binding.destination.stream)'));
  assert.ok(html.includes('music:{gain:45,muted:false,routes:["stream","monitor","music_stem"]}'));
  assert.ok(html.includes('alerts:{gain:80,muted:false,routes:["stream","monitor","alerts_stem"]}'));
});

test('invalid media files report a visible status without throwing from the event handler', () => {
  assert.ok(html.includes('id="musicAudioStatus" role="status"'));
  assert.ok(html.includes('id="alertAudioStatus" role="status"'));
  assert.ok(html.includes('status.textContent="Ungültige Datei. Bitte eine Audiodatei auswählen."'));
  assert.ok(!html.includes('throw new Error("Bitte eine Audiodatei auswählen.")'));
});

test('media file object URLs are revoked when replaced and when the Regie closes', () => {
  assert.ok(html.includes('if(previousUrl)URL.revokeObjectURL(previousUrl)'));
  assert.ok(html.includes('window.addEventListener("beforeunload"'));
  assert.ok(html.includes('for(const url of mediaObjectUrls.values())URL.revokeObjectURL(url)'));
});

test('Regie exposes a German TTS test routed through the dedicated mixer channel', () => {
  assert.ok(html.includes('id="ttsTestText"'));
  assert.ok(html.includes('id="ttsTestSpeak"'));
  assert.ok(html.includes('window.streamiovStudio.chatAction({action:"speak",text})'));
  assert.ok(html.includes('createBufferSource()'));
  assert.ok(html.includes('connectAudioSource("tts",ttsOutputDestination.stream)'));
});

test('TTS bridge returns generated WAV audio instead of bypassing the mixer', () => {
  assert.ok(preload.includes("chatAction: (payload) => ipcRenderer.invoke('studio:chat-action', payload)"));
  assert.ok(main.includes("['-v', 'de', '--stdout', text]"));
  assert.ok(main.includes("tts_audio_mime: 'audio/wav'"));
  assert.ok(main.includes('tts_audio_generated: true'));
  assert.ok(main.includes('tts_audio_verified: false'));
});

test('TTS playback cleanup cannot disconnect a newer utterance', () => {
  assert.ok(html.includes('if(activeTtsSource===source)activeTtsSource=null'));
  assert.ok(html.includes('source.onended=()=>{try{source.disconnect();}catch{}'));
});

test('desktop capture uses the standard API and routes a returned audio track into the game mixer', () => {
  assert.ok(html.includes('navigator.mediaDevices.getDisplayMedia({'));
  assert.ok(html.includes('audio:true'));
  assert.ok(html.includes('audioCaptureUnavailable=true'));
  assert.ok(html.includes('connectAudioSource("game",stream)'));
  assert.ok(html.includes('Diese Laufzeit unterstützt kein Desktop-Audio; Bild bleibt verfügbar.'));
});

test('stopping desktop capture disconnects its game-audio mixer input', () => {
  assert.ok(html.includes('if(studioAudioMixer)studioAudioMixer.disconnect("game")'));
  assert.ok(html.includes('renderAudioChannel("game")'));
});

test('Electron main process uses the official display media request handler for selected desktop sources', () => {
  assert.ok(main.includes("setDisplayMediaRequestHandler(async (request, callback)"));
  assert.ok(main.includes("selectedDesktopCaptureSourceId"));
  assert.ok(main.includes("audio: 'loopback'"));
  assert.match(main, /callback\\(\\{\\s*video:\\s*selectedSource/);
  assert.ok(main.includes("ipcMain.handle('studio:select-capture-source'"));
  assert.ok(preload.includes("selectCaptureSource: (sourceId) => ipcRenderer.invoke('studio:select-capture-source', { sourceId })"));
});

test('Regie uses standard getDisplayMedia instead of Chromium legacy chromeMediaSource constraints', () => {
  assert.ok(html.includes('navigator.mediaDevices.getDisplayMedia({'));
  assert.ok(html.includes('audio:true'));
  assert.ok(!html.includes('chromeMediaSourceId:sourceId'));
});
