'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const main = fs.readFileSync(require.resolve('../main.js'), 'utf8');
const preload = fs.readFileSync(require.resolve('../preload.js'), 'utf8');
const outputPreload = fs.readFileSync(require.resolve('../program-output-preload.js'), 'utf8');
const outputHtml = fs.readFileSync(require.resolve('../program-output.html'), 'utf8');
const regie = fs.readFileSync(require.resolve('../regie-v2.html'), 'utf8');

test('Program output is opened through trusted IPC and Electron display detection', () => {
  assert.match(main, /studio:get-displays/);
  assert.match(main, /studio:open-program-output/);
  assert.match(main, /screen\.getAllDisplays\(\)/);
  assert.match(preload, /openProgramOutput/);
  assert.match(regie, /PROGRAMMAUSGABE FENSTER/);
  assert.match(regie, /window\.streamiovStudio\.openProgramOutput\(\)/);
});

test('Program output receives every persisted scene change honestly', () => {
  assert.match(main, /did-finish-load/);
  assert.match(main, /function publishProgramScene\(snapshot\)/);
  assert.match(main, /publishProgramScene\(result\.state\)/);
  assert.match(main, /publishProgramScene\(snapshot\)/);
  assert.match(main, /programFramesDelivered = 0/);
  assert.match(main, /renderedVideo: false, programFramesDelivered/);
  assert.match(main, /programFramesDelivered \+= 1;/);
  assert.match(outputPreload, /ipcRenderer\.on\('studio:program-scene'/);
});

test('Program output publishes durable transitions and scene overlays', () => {
  assert.match(main, /action === 'set-transition'/);
  assert.match(main, /action === 'set-overlay'/);
  assert.match(main, /engine\.setTransition\(payload\.transition\)/);
  assert.match(main, /engine\.setOverlay\(payload\.overlay\)/);
  assert.match(main, /engine\.take\(payload\.transition\)/);
  assert.match(main, /overlay: scene\.overlay/);
  assert.match(main, /transition: state\.transition/);
  assert.match(regie, /id="transitionType"/);
  for (const type of ['cut', 'fade', 'slide', 'wipe']) {
    assert.match(regie, new RegExp(`<option value="${type}">`));
  }
  assert.match(regie, /function paintTransition\(type,progress,from,to,output\)/);
  assert.match(regie, /activeProgramTransition=hasTimedTransition\(active\)/);
  assert.ok(regie.includes('function drawProgramFrame(target,fromBuffer,toBuffer,now)'));
  assert.ok(regie.includes('drawProgramFrame($("programCanvas"),programFrameFromCanvas,programFrameToCanvas,now)'));
  assert.ok(regie.includes('const drawFrame=()=>drawProgramFrame(canvas,transitionFromCanvas,transitionToCanvas,performance.now())'));
  assert.match(regie, /\$\("slide"\)\.onclick=\(\)=>take\(\{type:"slide"/);
  assert.match(regie, /\$\("wipe"\)\.onclick=\(\)=>take\(\{type:"wipe"/);
  assert.match(regie, /id="sceneOverlayStyle"/);
  assert.match(regie, /function drawSceneOverlay\(/);
  assert.match(outputHtml, /function paintOverlay\(/);
  assert.match(outputHtml, /function startTransition\(/);
  assert.match(outputHtml, /function animateTransition\(/);
  assert.match(outputHtml, /function paintTransition\(type,progress,from,to,targetContext\)/);
  assert.match(outputHtml, /\['cut','fade','slide','wipe'\]\.includes\(transitionSource\.type\)/);
  assert.match(outputHtml, /paintTransition\(current\.transition\.type,progress,transitionCanvas,frameCanvas,context\)/);
  assert.match(outputHtml, /let lastFrameAt=0/);
  assert.match(outputHtml, /const FRAME_LIVE_WINDOW_MS=1500/);
  assert.match(outputHtml, /function frameStreaming\(\)/);
  assert.match(outputHtml, /const frameLive=frameStreaming\(\)/);
  assert.match(outputHtml, /if\(frameLive\)\{/);
  assert.match(outputHtml, /lastFrameAt=performance\.now\(\)/);
  assert.match(outputHtml, /let frameExpiryTimer=0/);
  assert.match(outputHtml, /function clearFrame\(\)/);
  assert.match(outputHtml, /function expireFrame\(\)/);
  assert.match(outputHtml, /setTimeout\(expireFrame,FRAME_LIVE_WINDOW_MS\+250\)/);
  assert.ok(outputHtml.includes('REGIE-CANVAS · KEIN AKTUELLES BILD'));
  assert.match(outputHtml, /function frameReady\(frame\)/);
  assert.match(outputHtml, /transitionCanvas/);
  assert.match(outputHtml, /overlay\.style==='standard'/);
});

test('Regie exposes free-form source geometry with direct preview manipulation', () => {
  assert.match(regie, /id="sourcePosition"/);
  assert.match(regie, /<option value="custom">Freie Position<\/option>/);
  for (const id of ['sourceX', 'sourceY', 'sourceW', 'sourceH']) {
    assert.match(regie, new RegExp(`id="${id}"`));
  }
  assert.match(regie, /const SOURCE_GEOMETRY_LIMITS=Object\.freeze\(\{minSize:0\.05,maxSize:1,maxPosition:0\.95\}\)/);
  assert.match(regie, /function sourceGeometryFromDialog\(\)/);
  assert.match(regie, /const position=sourceGeometryFromDialog\(\)/);
  assert.match(regie, /function drawSourceSelection\(/);
  assert.match(regie, /previewCanvas"\)\.addEventListener\("pointerdown"/);
  assert.match(regie, /previewCanvas"\)\.addEventListener\("pointermove"/);
  assert.match(regie, /previewCanvas"\)\.addEventListener\("pointerup"/);
  assert.match(regie, /setPointerCapture\(event\.pointerId\)/);
  assert.match(regie, /action:"update-source",sourceId:state\.id,patch/);
  assert.match(outputHtml, /x:number\(source\.x,0,0\.95,0\)/);
  assert.match(outputHtml, /w:number\(source\.w,0\.05,1,1\)/);
  assert.match(outputHtml, /const x=source\.x\*width,y=source\.y\*height,w=source\.w\*width,h=source\.h\*height/);
});

test('Regie and program output render bounded per-source visual transforms', () => {
  for (const id of ['sourceAlpha', 'sourceRotation', 'sourceFlipH', 'sourceFlipV', 'sourceFit',
    'sourceCropX', 'sourceCropY', 'sourceCropW', 'sourceCropH']) {
    assert.match(regie, new RegExp(`id="${id}"`));
  }
  assert.match(regie, /function sourceTransformFromDialog\(\)/);
  assert.match(regie, /function setSourceTransformFields\(transform\)/);
  assert.match(regie, /function formatSourceTransform\(transform\)/);
  assert.match(regie, /function drawMediaFit\(/);
  assert.match(regie, /function withSourceTransform\(context, source, x, y, width, height, drawFn\)/);
  assert.match(regie, /const payload=\{type,name,text,\.\.\.position,transform,settings,\.\.\.\(audio\?\{audio\}:\{\}\)\};/);
  assert.match(regie, /context\.globalAlpha\*=alpha/);
  assert.match(regie, /context\.rotate\(rotation\*Math\.PI\/180\)/);
  assert.match(outputHtml, /function sanitizeTransform\(value\)/);
  assert.match(outputHtml, /transform:sanitizeTransform\(source\.transform\)/);
  assert.match(outputHtml, /function withSourceTransform\(targetContext,source,x,y,w,h,drawFn\)/);
  assert.match(outputHtml, /targetContext\.globalAlpha\*=transform\.alpha/);
  assert.match(outputHtml, /\['cover','contain','stretch'\]\.includes\(raw\.fit\)/);
});

test('Program output renders the local scene on a canvas without claiming live video', () => {
  assert.match(outputHtml, /<canvas id="program" width="1280" height="720"/);
  assert.match(outputHtml, /LOKALE CANVAS · NOCH KEIN LIVE-VIDEO/);
  assert.match(outputHtml, /fillText/);
  assert.match(outputHtml, /createLinearGradient/);
  assert.match(outputHtml, /Bildschirm nicht geteilt/);
  assert.doesNotMatch(outputHtml, /VIDEO-COMPOSITOR NOCH NICHT ANGESCHLOSSEN/);
});

test('Studio relays trusted media assets and canvas frames into the program output', () => {
  assert.match(main, /ipcMain\.handle\('studio:list-media-assets'/);
  assert.match(main, /ipcMain\.handle\('studio:import-media-assets'/);
  assert.match(main, /ipcMain\.handle\('studio:remove-media-asset'/);
  assert.match(main, /ipcMain\.handle\('studio:program-frame'/);
  assert.match(main, /isTrustedStudioSender\(event\)/);
  assert.match(main, /payload\?\.bytes instanceof Uint8Array/);
  assert.match(main, /bytes\[0\] !== 0xff \|\| bytes\[1\] !== 0xd8 \|\| bytes\[2\] !== 0xff/);
  assert.match(main, /data:image\/jpeg;base64,/);
  assert.match(main, /streamiov-media:\/\/asset\//);
  assert.match(main, /protocol\.registerFileProtocol\('streamiov-media'/);
  assert.match(main, /parsed\.host !== 'asset'/);
  assert.match(preload, /listMediaAssets: \(\) => ipcRenderer\.invoke\('studio:list-media-assets'\)/);
  assert.match(preload, /sendProgramFrame: \(frame\) => \{/);
  assert.match(preload, /frame instanceof Uint8Array/);
  assert.match(outputPreload, /ipcRenderer\.on\('studio:program-assets'/);
  assert.match(outputPreload, /ipcRenderer\.on\('studio:program-frame'/);
  assert.match(outputHtml, /window\.streamiovProgramOutput\?\.onFrame/);
  assert.match(outputHtml, /startsWith\('data:image\/jpeg;base64,'\)/);
  assert.match(outputHtml, /createImageBitmap\(blob\)/);
  assert.match(outputHtml, /frameSequence/);
  assert.match(outputHtml, /lastFrameAt=performance\.now\(\)/);
  assert.match(outputHtml, /if\(transitionRequest\)\{cancelAnimationFrame\(transitionRequest\);transitionRequest=0;\}/);
  assert.match(outputHtml, /const assetElements=new Map\(\)/);
  assert.match(outputHtml, /function assetElement\(asset\)/);
  assert.match(outputHtml, /function drawAsset\(targetContext,asset,source,x,y,w,h\)/);
  assert.match(outputHtml, /assetById\(source\.settings\.assetId\)/);
  assert.match(regie, /toBlob\(blob=>/);
  assert.match(regie, /sendProgramFrame\(buffer\)/);
  assert.match(regie, /now-lastProgramFrameAt>33/);
  assert.match(regie, /getDisplayMedia/);
  assert.match(regie, /sourceMute/);
});

test('Regie routes per-scene source audio through the mixer and broadcast guard', () => {
  for (const id of ['sourceCameraAudio', 'sourceAudioGain', 'sourceAudioPan', 'sourceAudioMuted',
    'sourceAudioSolo', 'sourceAudioRoutesField', 'sourceMixerChannels']) {
    assert.ok(regie.includes(`id="${id}"`), `missing ${id}`);
  }
  for (const route of ['stream', 'monitor', 'headphones', 'communications']) {
    assert.ok(regie.includes(`data-source-audio-route="${route}"`), `missing route ${route}`);
  }
  assert.ok(regie.includes('function sourceAudioState(source)'));
  assert.ok(regie.includes('function sourceRuntimeSignature(source)'));
  assert.ok(regie.includes('const signature=sourceRuntimeSignature(source);'));
  assert.ok(!regie.includes('audio:sourceAudioState(source),volume:source.volume'));
  assert.ok(regie.includes('function applySceneAudioRouting()'));
  assert.ok(regie.includes('function renderSourceMixer()'));
  assert.ok(regie.includes('studioAudioMixer?.isAudibleOn(name,"stream")'));
  assert.ok(regie.includes('channelAudibleOnStream(runtime.channelName)'));
  assert.ok(regie.includes('applySceneAudioRouting();'));
  assert.ok(main.includes('engine.updateSource(payload.sourceId, payload.patch || {}, payload.sceneId)'));
});

test('Regie audio buses are explicit, mode-aware and slider-stable', () => {
  assert.ok(regie.includes('function sourceAudioRouteGroup(source)'));
  assert.ok(regie.includes('effectiveAudioRoutes(audio.routes||["stream"],sourceAudioRouteGroup(source))'));
  assert.ok(regie.includes('$("streamAudio").addEventListener("change",()=>{applyMonitorFeedbackGuard();});'));
  assert.ok(regie.includes('if(!studioAudioMixer)throw new Error("Die zentrale Audio-Bus-Engine ist nicht verfügbar.");'));
  assert.ok(!regie.includes('broadcastMasterGain.connect(broadcastAudioContext.destination)'));
  assert.ok(!regie.includes('else musicChannelGain.connect(broadcastMasterGain)'));
  assert.ok(!regie.includes('else pad.source.connect(pad.gain).connect(broadcastMasterGain)'));
  assert.ok(!regie.includes('else ttsMediaSource.connect(ttsChannelGain).connect(broadcastMasterGain)'));
  assert.ok(regie.includes('broadcastMixerSource.connect(broadcastMasterGain);'));
  assert.ok(regie.includes('const sourceAudioSaveTimers=new Map();'));
  assert.ok(regie.includes('function applySourceMixerChannelState(source)'));
  assert.ok(regie.includes('function refreshSourceMixerRow(source)'));
  assert.ok(regie.includes('sourceAudioSaveTimers.set(sourceId,setTimeout(()=>{sourceAudioSaveTimers.delete(sourceId);void persistSourceAudio(sourceId);},240));'));
  assert.ok(regie.includes('updateSourceAudioFromMixer(event.target,true)'));
  assert.ok(!regie.includes('await sceneCommand({action:"update-source",sceneId,sourceId,patch:{audio}});'));
});
