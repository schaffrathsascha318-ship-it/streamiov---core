"""Static regression checks for the Electron Studio scene and runtime bridges."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "dist" / "streamiov-studio-app" / "main.js"
UI = ROOT / "dist" / "streamiov-studio-app" / "regie-v2.html"
PRELOAD = ROOT / "dist" / "streamiov-studio-app" / "preload.js"
ENGINE = ROOT / "dist" / "streamiov-studio-app" / "engine" / "scene-engine.js"
SOURCE_CONTRACT = ROOT / "dist" / "streamiov-studio-app" / "engine" / "source-contract.js"
SOURCE_MODEL = ROOT / "dist" / "streamiov-studio-app" / "engine" / "source-model.js"
OUTPUT = ROOT / "dist" / "streamiov-studio-app" / "program-output.html"
SHIELD = ROOT / "dist" / "streamiov-studio-app" / "engine" / "privacy-shield.js"


class StudioRuntimeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.ui = UI.read_text(encoding="utf-8")
        cls.preload = PRELOAD.read_text(encoding="utf-8")

    def test_preload_exposes_scene_and_runtime_diagnostics(self):
        self.assertIn("sceneAction: (payload) => ipcRenderer.invoke('studio:scene-action', payload)", self.preload)
        self.assertIn("getRuntimeDiagnostics: () => ipcRenderer.invoke('studio:get-runtime-diagnostics')", self.preload)

    def test_runtime_diagnostics_is_sender_guarded_and_reports_encoder_requirements(self):
        handler = self.main.split("ipcMain.handle('studio:get-runtime-diagnostics'", 1)[1].split(
            "// Crostini-Kompatibilität", 1
        )[0]
        self.assertIn("isTrustedStudioSender(event)", handler)
        self.assertIn("gst-inspect-1.0", handler)
        self.assertIn("gst-launch-1.0", handler)
        self.assertIn("ffmpeg_rtmp: rtmp", handler)
        self.assertIn("missing_rtmp_dependencies: rtmp.missing", handler)
        self.assertIn("live_stream_verified: false", handler)

    def test_regie_exposes_a_real_diagnostics_action(self):
        self.assertIn('id="runtimeCheck"', self.ui)
        self.assertIn('window.streamiovStudio.getRuntimeDiagnostics()', self.ui)

    def test_electron_loads_the_existing_regie_as_its_trusted_studio_page(self):
        self.assertIn("path.join(__dirname, 'regie-v2.html')", self.main)
        self.assertIn("win.loadFile(path.join(__dirname, 'regie-v2.html'))", self.main)
        self.assertNotIn("win.loadFile(path.join(__dirname, 'index.html'))", self.main)
        self.assertTrue((ROOT / "dist" / "streamiov-studio-app" / "regie-v2.html").is_file())

    def test_music_player_routes_local_audio_through_independent_stream_mixer_channel(self):
        self.assertIn('id="mixerMusic"', self.ui)
        self.assertIn('id="mixerMusicMute"', self.ui)
        self.assertIn("musicMediaSource=broadcastAudioContext.createMediaElementSource(musicPlayerAudio)", self.ui)
        self.assertIn("musicMediaSource.connect(musicChannelGain);", self.ui)
        self.assertIn("musicChannelGain.connect(musicBridgeDestination);", self.ui)
        self.assertIn('studioAudioMixer.connect("music",musicBridgeDestination.stream,{gain:1,routes:effectiveAuxRoutes("music")})', self.ui)
        self.assertIn('musicChannelGain.gain.setTargetAtTime(musicMuted?0:mixerValue("mixerMusic")*(duckingActive?0.25:1)', self.ui)
        self.assertIn("musicPlayerAudio.src=musicTrackUrl(track)", self.ui)
        self.assertIn("Keep the AudioContext and the single MediaElementAudioSourceNode alive.", self.ui)
        self.assertIn("const musicQueue=[];", self.ui)
        self.assertIn("async function playMusicQueueItem(index)", self.ui)
        self.assertIn("Shuffle: AUS", self.ui)
        self.assertIn("Repeat: AUS", self.ui)
        self.assertIn("musicPlayerAudio.onended", self.ui)
        self.assertIn("Queue ist leer.", self.ui)

    def test_music_queue_playlists_and_ai_are_persistent_and_live_rights_gated(self):
        self.assertIn("musicState: (payload) => ipcRenderer.invoke('studio:music-state', payload)", self.preload)
        self.assertIn("ipcMain.handle('studio:music-state'", self.main)
        self.assertIn("'/api/v1/music/state'", self.main)
        self.assertIn("'/api/v1/music/playlist'", self.main)
        self.assertIn("'/api/v1/music/ai-playlist'", self.main)
        self.assertIn("async function persistMusicState()", self.ui)
        self.assertIn("function musicTrackLiveAllowed(track)", self.ui)
        self.assertIn("KI-Playlist erstellen", self.ui)
        self.assertIn("KI-Playlist verbessern", self.ui)
        self.assertIn("Auswahl kombinieren", self.ui)
        self.assertIn("Audio importieren", self.ui)
        self.assertIn("Die aktuelle Musik ist nicht rechtegeprüft", self.ui)
        self.assertIn("Ungeprüfte Musik darf nicht in einen laufenden LIVE-Stream gemischt werden.", self.ui)
        self.assertNotIn("URL.createObjectURL(chosen)", self.ui)

    def test_soundboard_routes_local_pads_into_shared_stream_and_monitor_mix(self):
        self.assertIn('data-tool="Soundboard"', self.ui)
        self.assertIn("async function renderSoundboardTool(body)", self.ui)
        self.assertIn("createMediaElementSource(pad.audio)", self.ui)
        self.assertIn("pad.source.connect(pad.gain).connect(pad.destination)", self.ui)
        self.assertIn('studioAudioMixer.connect(pad.channelName,pad.destination.stream,{gain:1,routes:effectiveAuxRoutes("soundboard")});', self.ui)
        self.assertIn("installSoundboardHotkeys()", self.ui)
        self.assertIn("event.key", self.ui)
        self.assertIn("soundboardPads.length>=32", self.ui)
        self.assertIn("soundboardFavoritesKey", self.ui)
        self.assertIn("soundboardPadsKey", self.ui)
        self.assertIn("function saveSoundboardPads()", self.ui)
        self.assertIn('studio.importMediaAssets({kind:"audio"})', self.ui)
        self.assertIn("studio.listMediaAssets()", self.ui)
        self.assertIn("favorite.textContent", self.ui)
        self.assertIn('hotkey.addEventListener("change"', self.ui)
        self.assertNotIn("URL.createObjectURL(file)", self.ui)

    def test_studio_gift_gallery_is_internal_preview_and_assignment_only(self):
        self.assertIn('data-tool="Geschenke"', self.ui)
        self.assertIn("async function renderGiftsTool(body)", self.ui)
        self.assertIn('api({kind:"gifts"})', self.ui)
        self.assertIn("!gift.tiktok_gift_id", self.ui)
        self.assertIn('recordEvent("studio.gift.effect_preview"', self.ui)
        self.assertIn("showGiftEffect(symbol)", self.ui)
        self.assertIn("Vorschau auslösen", self.ui)
        self.assertIn("Zuordnung speichern", self.ui)
        self.assertIn("Echte Plattformgeschenke werden ausschließlich aus autorisierten Plattformereignissen übernommen.", self.ui)
        self.assertIn("LOKALE EFFEKTVORLAGEN · VERWALTUNG", self.ui)
        self.assertNotIn('"studio.gift.sent"', self.ui)
        self.assertNotIn("GESCHENKE / GALERIEBOX", self.ui)
        self.assertNotIn("keine eigene Geschenke-Galerie", self.ui)
        self.assertIn("function showGiftEffect(symbol)", self.ui)

        self.assertNotIn('id="rtmpDestination"', self.ui)
        self.assertIn("● LIVE STARTEN", self.ui)
        self.assertIn("window.streamiovStudio?.stopStream?.()", self.ui)

    def test_rtmp_process_controls_are_sender_guarded_and_validate_destination(self):
        for channel in ("studio:start-stream", "studio:write-stream-chunk", "studio:stop-stream"):
            self.assertIn(f"ipcMain.handle('{channel}'", self.main)
            self.assertIn("isTrustedStudioSender(event)", self.main)
        self.assertIn("['rtmp:', 'rtmps:'].includes(url.protocol)", self.main)
        self.assertIn("url.username || url.password || url.hash", self.main)
        self.assertIn("liveOutputManager", self.main)
        self.assertIn("'-c:v', 'libx264'", self.main)
        self.assertIn("'-c:a', 'aac'", self.main)

    def test_screen_capture_requires_trusted_source_selection(self):
        self.assertIn("studio:list-display-sources", self.main)
        self.assertIn("studio:select-display-source", self.main)
        self.assertIn("frame.parent !== null || frame.url !== studioUrl || !sourceId", self.main)
        self.assertIn("['media', 'display-capture'].includes(permission)", self.main)
        self.assertIn("getDisplayMedia({video:captureVideoConstraints(settings),audio:audioEnabled})", self.ui)

    def test_real_capture_and_media_sources_use_runtime_settings_and_mixer(self):
        self.assertIn("function captureVideoConstraints(settings={})", self.ui)
        self.assertIn("constraints.frameRate={ideal:settings.fps}", self.ui)
        self.assertIn("getUserMedia({video:device,audio})", self.ui)
        self.assertIn("settings.audioEnabled===true", self.ui)
        self.assertIn("connectRuntimeAudio(runtime,source,runtime.stream,sourceAudioState(source).routes)", self.ui)
        self.assertIn("element.muted=settings.muted===true||audio.enabled===false", self.ui)
        self.assertIn("element.volume=volume", self.ui)
        self.assertIn('id="sourceCameraAudioField" hidden>Quellen-Audio aktivieren', self.ui)
        self.assertIn('id="sourceVolumeField" hidden', self.ui)

    def test_broadcast_frames_are_paced_independently_of_window_animation_frames(self):
        self.assertIn("broadcastFrameTimer=setInterval(drawFrame,Math.max(1,Math.round(1000/streamFps)))", self.ui)
        self.assertIn("if(broadcastFrameTimer)clearInterval(broadcastFrameTimer)", self.ui)
        self.assertIn("recorder.start(250)", self.ui)

    def test_encoder_maps_required_audio_and_keeps_av_synchronised(self):
        self.assertIn("'-map', '0:a:0'", self.main)
        self.assertNotIn("'-map', '0:a:0?'", self.main)
        self.assertIn("'-fps_mode', 'cfr'", self.main)
        self.assertIn("'-g', String(settings.fps * 2)", self.main)
        self.assertIn("aresample=async=1:first_pts=0", self.main)
        self.assertIn("'-fflags', '+genpts'", self.main)

    def test_scene_actions_remain_persistent(self):
        self.assertIn("studio:scene-action", self.main)
        self.assertIn("streamiov-scenes.json", self.main)
        self.assertIn("await fs.writeFile(temporary, JSON.stringify(engine.toJSON()", self.main)
        self.assertIn("await fs.rename(temporary, file)", self.main)
        self.assertIn('sceneCommand({action:"take"})', self.ui)

    def test_multiview_renders_real_scenes_and_can_take_directly(self):
        self.assertIn('id="multiviewGrid"', self.ui)
        self.assertIn("function renderMultiview(scenes)", self.ui)
        self.assertIn("multiviewCanvases.set(scene.id,canvas)", self.ui)
        self.assertIn("for(const [id,canvas] of multiviewCanvases)drawSceneToCanvas(canvas,id,1)", self.ui)
        self.assertIn("function updateMultiviewState()", self.ui)
        self.assertIn("async function takeMultiviewScene(id)", self.ui)
        self.assertIn('sceneCommand({action:"select",id})', self.ui)
        self.assertIn("tile.classList.toggle(\"preview\",isPreview)", self.ui)
        self.assertIn("tile.classList.toggle(\"program\",isProgram)", self.ui)
        self.assertIn("renderMultiview(state.scenes)", self.ui)
        self.assertIn("renderMultiview(demoScenes())", self.ui)

    def test_scene_engine_supports_layout_sources_and_v1_migration(self):
        engine = ENGINE.read_text(encoding="utf-8")
        contract = SOURCE_CONTRACT.read_text(encoding="utf-8")
        self.assertIn("const SCENE_VERSION = 4;", engine)
        self.assertIn("const SOURCE_TYPES = sourceContract.SUPPORTED_TYPES;", engine)
        for source_type in ("'camera'", "'screen'", "'title'", "'text'"):
            self.assertIn(source_type, contract)
        for action in ("addSource", "updateSource", "removeSource", "moveSource",
                       "setBackground", "setTransition", "setOverlay", "deleteScene", "renameScene"):
            with self.subTest(action=action):
                self.assertIn(f"  {action}(", engine)
        self.assertIn("savedState.version != null && ![1, 2, 3, SCENE_VERSION].includes(savedState.version)", engine)
        self.assertIn("function cleanSource(raw, index)", engine)
        self.assertIn("Math.trunc(clamp(raw.z, 0, 100, index))", engine)
        self.assertIn("direction === 'up' ? index + 1 : index - 1", engine)
        self.assertIn("MAX_SOURCES", engine)
        self.assertIn("MAX_SCENES", engine)

    def test_source_audio_is_wired_from_engine_through_regie_to_ipc(self):
        engine = ENGINE.read_text(encoding="utf-8")
        for identifier in (
            "const AUDIO_ROUTES = Object.freeze(['stream', 'monitor', 'headphones', 'communications'])",
            "const AUDIO_CAPABLE_TYPES = Object.freeze(['camera', 'screen', 'window', 'video', 'audio'])",
            "function cleanSourceAudio(raw, type, settings)",
            "audio: cleanSourceAudio(raw.audio, type, settings)",
            "routes: [...source.audio.routes]",
            "audioEnabled",
            "AUDIO_ROUTES,"
        ):
            with self.subTest(engine_identifier=identifier):
                self.assertIn(identifier, engine)
        for identifier in (
            'id="sourceAudioGroup"',
            'data-source-audio-route="stream"',
            'id="sourceMixerChannels"',
            "const audioCapableSourceTypes=new Set([\"camera\",\"screen\",\"window\",\"video\",\"audio\"])",
            "function sourceAudioState(source)",
            "function applySceneAudioRouting()",
            "function renderSourceMixer()",
            "function channelAudibleOnStream(name)",
            "studioAudioMixer.connect(runtime.channelName,runtime.destination.stream,{gain:audio.gain,muted:audio.muted,routes});",
            "studioAudioMixer.setSolo(runtime.channelName,audio.solo)",
            "applySceneAudioRouting();",
            "channelAudibleOnStream(runtime.channelName)"
        ):
            with self.subTest(ui_identifier=identifier):
                self.assertIn(identifier, self.ui)
        signature_block = self.ui.split("function sourceRuntimeSignature(source){", 1)[1].split("\n}", 1)[0]
        self.assertIn("audioEnabled:audio.enabled===true", signature_block)
        for mutable_audio in ("audio.gain", "audio.muted", "audio.solo", "audio.pan", "audio.routes"):
            with self.subTest(mutable_audio=mutable_audio):
                self.assertNotIn(mutable_audio, signature_block)
        self.assertIn("const signature=sourceRuntimeSignature(source);", self.ui)
        self.assertNotIn("audio:sourceAudioState(source),volume:source.volume", self.ui)
        self.assertIn("engine.updateSource(payload.sourceId, payload.patch || {}, payload.sceneId)", self.main)
        for identifier in (
            "function sourceAudioRouteGroup(source)",
            'effectiveAudioRoutes(audio.routes||["stream"],sourceAudioRouteGroup(source))',
            '$("streamAudio").addEventListener("change",()=>{applyMonitorFeedbackGuard();});',
            'if(!studioAudioMixer)throw new Error("Die zentrale Audio-Bus-Engine ist nicht verfügbar.");',
            "broadcastMixerSource.connect(broadcastMasterGain);",
            "const sourceAudioSaveTimers=new Map();",
            "function applySourceMixerChannelState(source)",
            "function refreshSourceMixerRow(source)",
            "sourceAudioSaveTimers.set(sourceId,setTimeout(()=>{sourceAudioSaveTimers.delete(sourceId);void persistSourceAudio(sourceId);},240));",
            "updateSourceAudioFromMixer(event.target,true)",
        ):
            with self.subTest(audio_identifier=identifier):
                self.assertIn(identifier, self.ui)
        for forbidden in (
            "broadcastMasterGain.connect(broadcastAudioContext.destination)",
            "else musicChannelGain.connect(broadcastMasterGain)",
            "else pad.source.connect(pad.gain).connect(broadcastMasterGain)",
            "else ttsMediaSource.connect(ttsChannelGain).connect(broadcastMasterGain)",
            'await sceneCommand({action:"update-source",sceneId,sourceId,patch:{audio}});',
        ):
            with self.subTest(forbidden_audio_identifier=forbidden):
                self.assertNotIn(forbidden, self.ui)

    def test_scene_handler_dispatches_to_the_engine(self):
        handler = self.main.split("ipcMain.handle('studio:scene-action'", 1)[1].split(
            "ipcMain.handle('studio:game-analysis'", 1
        )[0]
        for action in ("select", "take", "create", "rename-scene", "delete-scene",
                       "duplicate-scene", "reorder-scenes", "import-scene-pack",
                       "add-source", "update-source", "remove-source",
                       "move-source", "set-background", "set-transition", "set-overlay", "set-scene-dependencies", "set-program"):
            with self.subTest(action=action):
                self.assertIn(f"action === '{action}'", handler)
        for method in ("selectPreview", "take", "createScene", "renameScene",
                       "deleteScene", "duplicateScene", "reorderScenes", "importScenePack",
                       "addSource", "updateSource", "removeSource",
                         "moveSource", "setBackground", "setTransition", "setOverlay", "setSceneDependencies", "setProgramScene"):
            with self.subTest(method=method):
                self.assertIn(f"engine.{method}(", handler)
        self.assertIn("if (action === 'export-scenes') return engine.exportScenePack(payload.sceneIds);", handler)
        self.assertIn("publishProgramScene(result.state)", handler)

    def test_regie_persists_transitions_and_overlay_settings(self):
        self.assertIn('id="transitionType"', self.ui)
        self.assertIn('id="transitionDuration"', self.ui)
        self.assertIn('id="saveTransition"', self.ui)
        self.assertIn('id="sceneOverlayStyle"', self.ui)
        self.assertIn('id="sceneOverlayText"', self.ui)
        self.assertIn('id="sceneOverlayOpacity"', self.ui)
        self.assertIn('id="saveSceneOverlay"', self.ui)
        self.assertIn('action:"set-transition"', self.ui)
        self.assertIn('action:"set-overlay"', self.ui)
        self.assertIn('<option value="slide">SLIDE</option>', self.ui)
        self.assertIn('<option value="wipe">WIPE</option>', self.ui)
        self.assertIn('function paintTransition(type,progress,from,to,output)', self.ui)
        self.assertIn("function drawSceneOverlay(context,scene,width,height)", self.ui)
        self.assertIn("drawSceneOverlay(context,scene,width,height);", self.ui)
        self.assertIn("activeProgramTransition=hasTimedTransition(active)", self.ui)
        self.assertIn("function drawProgramFrame(target,fromBuffer,toBuffer,now)", self.ui)
        self.assertIn('drawProgramFrame($("programCanvas"),programFrameFromCanvas,programFrameToCanvas,now)', self.ui)
        self.assertIn("const drawFrame=()=>drawProgramFrame(canvas,transitionFromCanvas,transitionToCanvas,performance.now())", self.ui)
        self.assertNotIn("screen.style.opacity=\".25\"", self.ui)

    def test_program_output_window_uses_a_separate_button_and_local_canvas(self):
        self.assertIn('id="openProgramOutput" type="button">REGIE AUF 2. BILDSCHIRM', self.ui)
        self.assertIn('id="openProgramOutputWindow" type="button">PROGRAMMAUSGABE FENSTER', self.ui)
        self.assertIn('window.streamiovStudio.openProgramOutput()', self.ui)
        self.assertIn("function publishProgramScene(snapshot)", self.main)
        self.assertIn("publishProgramScene(result.state)", self.main)
        output = (ROOT / "dist" / "streamiov-studio-app" / "program-output.html").read_text(encoding="utf-8")
        self.assertIn('<canvas id="program" width="1280" height="720"', output)
        self.assertIn("LOKALE CANVAS · NOCH KEIN LIVE-VIDEO", output)
        self.assertIn("fillText", output)
        self.assertNotIn("VIDEO-COMPOSITOR NOCH NICHT ANGESCHLOSSEN", output)
        self.assertIn("createImageBitmap(blob)", output)
        self.assertIn("frameSequence", output)
        self.assertIn("function frameReady(frame)", output)
        self.assertIn("let frameExpiryTimer=0", output)
        self.assertIn("function expireFrame()", output)
        self.assertIn("setTimeout(expireFrame,FRAME_LIVE_WINDOW_MS+250)", output)
        self.assertIn("REGIE-CANVAS · KEIN AKTUELLES BILD", output)
        self.assertIn("const assetElements=new Map()", output)
        self.assertIn("function drawAsset(targetContext,asset,source,x,y,w,h)", output)
        self.assertIn("assetById(source.settings.assetId)", output)

    def test_studio_sources_import_media_control_audio_and_relay_program_frames(self):
        for element_id in ("sourceDevice", "sourceImport", "sourceColor", "sourceLoop",
                           "sourceVolume", "sourceVolumeValue", "sourceMute", "sourceTextField",
                           "manageMedia", "mediaDialog", "mediaManagerList", "closeMediaManager"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.ui)
        self.assertIn('<option value="window">Fenster</option>', self.ui)
        self.assertIn('<option value="image">Bild</option>', self.ui)
        self.assertIn('<option value="video">Video</option>', self.ui)
        self.assertIn('<option value="audio">Audiodatei</option>', self.ui)
        self.assertIn("importMediaAssets: (payload) => ipcRenderer.invoke('studio:import-media-assets', payload)", self.preload)
        self.assertIn("removeMediaAsset: (id) => ipcRenderer.invoke('studio:remove-media-asset', { id })", self.preload)
        self.assertIn("sendProgramFrame: (frame) => {", self.preload)
        self.assertIn("frame instanceof Uint8Array", self.preload)
        self.assertIn("protocol.registerFileProtocol('streamiov-media'", self.main)
        self.assertIn("createMediaAssetStore", self.main)
        self.assertIn("sendProgramAssets()", self.main)
        self.assertIn("sendProgramFrame(buffer)", self.ui)
        self.assertIn("$(\"programCanvas\").toBlob(blob=>", self.ui)
        self.assertIn("retrySourceRuntime", self.ui)
        self.assertIn("activeProgramSourceRuntime", self.ui)
        self.assertIn("sourceRuntimeHasLiveVideo", self.ui)
        self.assertIn("sourceRuntimeHasStreamAudio", self.ui)
        self.assertIn("!element.paused", self.ui)
        self.assertIn("Programmszene aktivieren", self.ui)
        self.assertIn("||sourceAudioActive", self.ui)
        self.assertIn("openMediaManager", self.ui)
        self.assertIn("removeManagedAsset", self.ui)
        self.assertIn("mediaAssetUsage", self.ui)
        self.assertIn("createMediaElementSource", self.ui)
        self.assertIn("Number.isFinite(settings.volume)", self.ui)

    def test_sources_share_one_contract_with_availability_and_health_checks(self):
        contract = SOURCE_CONTRACT.read_text(encoding="utf-8")
        model = SOURCE_MODEL.read_text(encoding="utf-8")
        engine = ENGINE.read_text(encoding="utf-8")
        self.assertIn("const sourceContract = require('./source-contract');", model)
        self.assertIn("const sourceContract = require('./source-contract');", engine)
        for identifier in (
            "CONTRACT_VERSION = 1",
            "capture: 'screen'",
            "function normalizeType(type)",
            "function validateAvailability(source, availability)",
            "function sourceHealth(source, runtime, availability)",
            "permission-denied",
            "device-busy"
        ):
            with self.subTest(contract_identifier=identifier):
                self.assertIn(identifier, contract)
        for identifier in (
            '<script src="engine/source-contract.js"></script>',
            "const sourceContract=window.StreamiovSourceContract;",
            "const sourceAvailability={devices:[],displaySources:[],assets:[],checkedAt:0};",
            "async function refreshSourceAvailability()",
            "function assertSourceSelection(source)",
            "assertSourceSelection(source);",
            "runtime.status=error?.streamiovSourceStatus||sourceContract.classifyError(error);",
            "sourceContract.sourceHealth(source,sourceRuntime.get(source.id),sourceAvailabilitySnapshot())",
            "row.dataset.sourceHealth=health.status;",
            "await refreshSourceAvailability();"
        ):
            with self.subTest(ui_identifier=identifier):
                self.assertIn(identifier, self.ui)

    def test_regie_edits_free_form_source_geometry_and_persists_it(self):
        for element_id in ("sourcePosition", "sourceX", "sourceY", "sourceW", "sourceH"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.ui)
        self.assertIn('<option value="custom">Freie Position</option>', self.ui)
        self.assertIn("const SOURCE_GEOMETRY_LIMITS=Object.freeze({minSize:0.05,maxSize:1,maxPosition:0.95});", self.ui)
        self.assertIn("function sourceGeometryFromDialog()", self.ui)
        self.assertIn("const position=sourceGeometryFromDialog();", self.ui)
        self.assertIn("setSourceGeometryFields(source||sourcePosition(\"full\"));", self.ui)
        self.assertIn("function formatSourceGeometry(source)", self.ui)
        self.assertIn(" · Position \"+formatSourceGeometry(source)", self.ui)
        self.assertIn("function drawSourceSelection(context,scene,width,height)", self.ui)
        self.assertIn('$("previewCanvas").addEventListener("pointerdown"', self.ui)
        self.assertIn('$("previewCanvas").addEventListener("pointermove"', self.ui)
        self.assertIn('$("previewCanvas").addEventListener("pointerup"', self.ui)
        self.assertIn("canvas.setPointerCapture(event.pointerId)", self.ui)
        self.assertIn('action:"update-source",sourceId:state.id,patch', self.ui)
        self.assertIn("renderSources();\n event.preventDefault();\n});\n$(\"previewCanvas\").addEventListener(\"pointermove\"", self.ui)

    def test_regie_manages_validated_scene_dependencies(self):
        for element_id in ("sceneDependencies", "dependenciesDialog", "dependencyList",
                           "saveDependencies", "closeDependencies"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.ui)
        self.assertIn('$("sceneDependencies").disabled=!custom;', self.ui)
        self.assertIn("function openDependenciesDialog()", self.ui)
        self.assertIn('action:"set-scene-dependencies",id:scene.id,dependsOn', self.ui)
        self.assertIn("check.dataset.dependencyScene=candidate.id;", self.ui)
        self.assertIn(" · ABH \"+scene.dependsOn.length", self.ui)
        self.assertIn("Abhängigkeiten dürfen keinen Kreis bilden", self.ui)
        self.assertIn("const MAX_DEPENDENCIES = 10;", ENGINE.read_text(encoding="utf-8"))
        engine_text = ENGINE.read_text(encoding="utf-8")
        self.assertIn("function cleanDependencyIds(raw)", engine_text)
        self.assertIn("function hasDependencyCycle(dependencyMap, sceneId, dependencyId)", engine_text)
        self.assertIn("dependsOn: cleanDependencyIds(raw.dependsOn)", engine_text)
        self.assertIn("setSceneDependencies(sceneId, raw)", engine_text)
        self.assertIn("Szene wird von einer anderen Szene benötigt.", engine_text)

    def test_regie_exposes_bounded_source_visual_transforms(self):
        for element_id in ("sourceAlpha", "sourceAlphaValue", "sourceRotation", "sourceFlipH",
                           "sourceFlipV", "sourceFit", "sourceCropX", "sourceCropY",
                           "sourceCropW", "sourceCropH"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.ui)
        self.assertIn("function sourceTransformFromDialog()", self.ui)
        self.assertIn("function setSourceTransformFields(transform)", self.ui)
        self.assertIn("function formatSourceTransform(transform)", self.ui)
        self.assertIn("function drawMediaFit(", self.ui)
        self.assertIn("function withSourceTransform(context, source, x, y, width, height, drawFn)", self.ui)
        self.assertIn("const payload={type,name,text,...position,transform,settings,...(audio?{audio}:{})};", self.ui)
        self.assertIn('" · "+formatSourceTransform(source.transform)', self.ui)
        engine_text = ENGINE.read_text(encoding="utf-8")
        self.assertIn("SOURCE_TRANSFORM_FIT_MODES = Object.freeze(['cover', 'contain', 'stretch'])", engine_text)
        self.assertIn("function cleanSourceTransform(raw)", engine_text)
        self.assertIn("transform: cleanSourceTransform(raw.transform)", engine_text)
        output_text = OUTPUT.read_text(encoding="utf-8")
        self.assertIn("function sanitizeTransform(value)", output_text)
        self.assertIn("transform:sanitizeTransform(source.transform)", output_text)
        self.assertIn("function withSourceTransform(targetContext,source,x,y,w,h,drawFn)", output_text)
        self.assertIn("targetContext.globalAlpha*=transform.alpha", output_text)

    def test_regie_manages_scene_duplication_order_and_packs(self):
        for element_id in ("duplicateScene", "moveSceneLeft", "moveSceneRight",
                           "exportScenes", "importScenes", "scenePackInput"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.ui)
        self.assertIn('$("duplicateScene").disabled=!scene;', self.ui)
        self.assertIn('$("moveSceneLeft").disabled=index<=0;', self.ui)
        self.assertIn('$("moveSceneRight").disabled=index<0||index>=scenes.length-1;', self.ui)
        self.assertIn('action:"duplicate-scene",id:scene.id', self.ui)
        self.assertIn('action:"reorder-scenes",order', self.ui)
        self.assertIn('action:"import-scene-pack",pack', self.ui)
        self.assertIn('action:"export-scenes"', self.ui)
        self.assertIn('link.download="streamiov-szenen.json"', self.ui)
        self.assertIn("URL.createObjectURL(blob)", self.ui)
        engine_text = ENGINE.read_text(encoding="utf-8")
        self.assertIn("duplicateScene(sceneId)", engine_text)
        self.assertIn("reorderScenes(order)", engine_text)
        self.assertIn("exportScenePack(sceneIds)", engine_text)
        self.assertIn("importScenePack(raw)", engine_text)
        self.assertIn("kind: 'streamiov-scene-pack'", engine_text)

    def test_music_tool_records_a_real_local_wav_test_file(self):
        handler = self.main.split("ipcMain.handle('studio:record-music-test'", 1)[1].split(
            "ipcMain.handle('studio:get-network-status'", 1
        )[0]
        self.assertIn("isTrustedStudioSender(event)", handler)
        self.assertNotIn("stage: 'not_implemented'", handler)
        self.assertIn("stage: 'completed'", handler)
        self.assertIn("audiotestsrc", handler)
        self.assertIn("wavenc", handler)
        self.assertIn("isWavBuffer(audio)", handler)
        self.assertIn("audio_base64: audio.toString('base64')", handler)
        self.assertIn("recordMusicTest: (payload) => ipcRenderer.invoke('studio:record-music-test', payload)", self.preload)
        self.assertIn("LOKALEN MUSIK-TEST AUFNEHMEN", self.ui)
        self.assertIn("window.streamiovStudio?.recordMusicTest?.({seconds:2})", self.ui)
        self.assertIn("keine LIVE-Ausgabe", self.ui)

    def test_media_test_uses_native_gstreamer_pipeline_not_missing_python_module(self):
        handler = self.main.split("ipcMain.handle('studio:run-media-test'", 1)[1].split(
            "ipcMain.handle('studio:record-music-test'", 1
        )[0]
        self.assertIn("isTrustedStudioSender(event)", handler)
        self.assertIn("gst-launch-1.0", handler)
        self.assertIn("videotestsrc", handler)
        self.assertIn("audiotestsrc", handler)
        self.assertIn("vp8enc", handler)
        self.assertIn("vorbisenc", handler)
        self.assertIn("webmmux", handler)
        self.assertIn("execFileAsync('gst-launch-1.0', args", handler)
        self.assertIn("device_capture_verified: false", handler)
        self.assertIn("live_stream_verified: false", handler)
        self.assertNotIn("modules.broadcast.gstreamer_engine", handler)
        self.assertIn("await fs.rm(testDirectory", handler)

    def test_static_capability_handlers_do_not_claim_missing_python_modules(self):
        for channel in ("studio:get-module-status", "studio:get-status",
                        "studio:record-music-test", "studio:get-camera-lab"):
            with self.subTest(channel=channel):
                handler = self.main.split(f"ipcMain.handle('{channel}'", 1)[1].split(
                    "ipcMain.handle('", 1
                )[0]
                self.assertNotIn("missingPythonModules", handler)
        self.assertIn("local_runtime_capability_inventory", self.main)
        self.assertIn("live_stream_verified: liveConfirmed", self.main)
        self.assertIn("local_four_bus_engine", self.main)
        self.assertIn("local_file_stream_mix", self.main)
        self.assertIn("incomingEvents.chat.status", self.main)
        self.assertIn("incomingEvents.gift.status", self.main)
        self.assertIn("observedMediaDeviceCounts", self.main)
        self.assertNotIn("missingPythonModules", self.main)
        self.assertNotIn("notBundledResult", self.main)
        self.assertIn("resolveFfmpegExecutable", self.main)
        self.assertIn("process.resourcesPath", self.main)

    def test_ai_bridge_uses_the_documented_host_contract(self):
        self.assertIn(
            "const STREAMIOV_API = process.env.STREAMIOV_HOST_URL || 'http://127.0.0.1:8765'",
            self.main,
        )
        self.assertIn("/api/v1/auth/login", self.main)
        self.assertIn("/api/v1/auth/logout", self.main)
        self.assertIn("/api/v1/ai/tasks", self.main)
        self.assertIn("X-Streamiov-Client", self.main)
        self.assertIn("readSessionCookie", self.main)
        self.assertNotIn("/api/ai/wunschbox", self.main)
        self.assertNotIn("http://127.0.0.1:8080", self.main)

    def test_media_test_is_available_from_regie_and_reports_result(self):
        self.assertIn('id="mediaTest"', self.ui)
        self.assertIn('id="mediaTestResult"', self.ui)
        self.assertIn("window.streamiovStudio.runMediaTest()", self.ui)
        self.assertIn("Lokaler Audio-/Video-Test erfolgreich", self.ui)

    def test_runtime_diagnostics_checks_local_media_test_plugins(self):
        handler = self.main.split("ipcMain.handle('studio:get-runtime-diagnostics'", 1)[1].split(
            "// Crostini-Kompatibilität", 1
        )[0]
        for plugin in ("videotestsrc", "audiotestsrc", "vp8enc", "vorbisenc", "webmmux"):
            self.assertIn(plugin, handler)
        self.assertIn("media_test_pipeline_available", handler)

    def test_download_page_marks_unreleased_broadcast_feature_accurately(self):
        download = (ROOT / "dist" / "streamiov-homepage-worker" / "public" / "download" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Regie-Oberfläche enthalten, Encoder noch extern.", download)
        if "FFmpeg mit libx264, AAC und RTMP-Unterstützung" not in download:
            # The desktop-download-only page uses the newer, equally explicit
            # wording for the separately required FFmpeg runtime.
            self.assertIn("benötigt FFmpeg noch separat", download)
            self.assertIn("Veröffentlichung bleibt bis zum vollständigen GPL-Quellcodepaket gesperrt", download)


    def test_regie_exposes_real_camera_and_microphone_capture_controls(self):
        for element_id in ("cameraDeviceSelect", "cameraStart", "cameraPreview",
                           "cameraCaptureStatus", "microphoneDeviceSelect",
                           "microphoneStart", "microphoneCaptureStatus",
                           "microphoneLevel", "refreshDevices"):
            self.assertIn(f'id="{element_id}"', self.ui)

    def test_device_capture_uses_real_media_devices_and_stops_tracks(self):
        self.assertIn("navigator.mediaDevices.enumerateDevices()", self.ui)
        self.assertIn("navigator.mediaDevices.getUserMedia", self.ui)
        self.assertIn("video:deviceId?{deviceId:{exact:deviceId}}:true", self.ui)
        self.assertIn("audio:deviceId?{deviceId:{exact:deviceId}}:true", self.ui)
        self.assertIn("track.stop()", self.ui)
        self.assertIn("track.readyState!==\"live\"", self.ui)
        self.assertIn("createMediaStreamSource(stream)", self.ui)
        self.assertIn("beforeunload", self.ui)

    def test_device_capture_reports_permissions_and_never_claims_live_stream(self):
        self.assertIn("NotAllowedError", self.ui)
        self.assertIn("NotFoundError", self.ui)
        self.assertIn("Nur lokale Vorschau", self.ui)
        self.assertIn("kein Ton wird übertragen", self.ui)
        self.assertIn("Echte Kamera liefert einen lokalen Videostream.", self.ui)
        self.assertIn("Echtes Mikrofon liefert einen lokalen Audiostream.", self.ui)

    def test_media_pipeline_builder_is_shared_with_ci_smoke_test(self):
        self.assertIn("require('./media-pipeline')", self.main)
        self.assertIn("buildSyntheticAvPipelineArgs(outputFile)", self.main)
        helper = (ROOT / "dist" / "streamiov-studio-app" / "media-pipeline.js").read_text(encoding="utf-8")
        self.assertIn("videotestsrc", helper)
        self.assertIn("audiotestsrc", helper)
        self.assertIn("webmmux", helper)
        ci_script = (ROOT / "scripts" / "test-studio-media-pipeline.cjs").read_text(encoding="utf-8")
        self.assertIn("buildSyntheticAvPipelineArgs(output)", ci_script)
        self.assertIn("assert.ok(stat.size > 1024", ci_script)

    def test_audio_mixer_controls_real_microphone_and_system_sources(self):
        for element_id in ("mixerMic", "mixerSystem", "mixerMusic", "mixerMaster",
                           "mixerMicValue", "mixerSystemValue", "mixerMusicValue",
                           "mixerMasterValue", "mixerMusicMute", "mixerStatus"):
            self.assertIn(f'id="{element_id}"', self.ui)
        self.assertIn("<b>Musik</b><div class=\"meter\">", self.ui)
        self.assertNotIn("<b>Spiel</b><div class=\"meter\">", self.ui)
        self.assertIn("<b>Alerts</b><div class=\"meter\">", self.ui)

    def test_audio_mixer_gains_are_applied_to_the_stream_mix(self):
        self.assertIn('studioAudioMixer.setGain("microphone",Number($("audioMicGain").value)/100*mixerValue("mixerMic"))', self.ui)
        self.assertIn('studioAudioMixer.setGain("system",Number($("audioSystemGain").value)/100*mixerValue("mixerSystem"))', self.ui)
        self.assertIn('studioAudioMixer.connect("music",musicBridgeDestination.stream,{gain:1,routes:effectiveAuxRoutes("music")})', self.ui)
        self.assertIn('studioAudioMixer.setMuted("music",musicMuted)', self.ui)
        self.assertIn('studioAudioMixer.setGain("tts",mixerValue("mixerTts"))', self.ui)
        self.assertIn('studioAudioMixer.connect("tts",ttsBridgeDestination.stream,{gain:mixerValue("mixerTts"),routes:effectiveAuxRoutes("tts")})', self.ui)
        self.assertIn("if(studioAudioMixer)await studioAudioMixer.resume()", self.ui)
        self.assertIn("studioAudioDeviceAdapter.attachOutput(\"monitor\",audioBusElements.monitor", self.ui)
        self.assertIn("studioAudioMixer.attachOutput(\"monitor\",audioBusElements.monitor)", self.ui)
        self.assertIn("if(alertToneGain)alertToneGain.gain.setTargetAtTime(mixerValue(\"mixerAlert\"),now,0.02)", self.ui)
        self.assertIn("localStorage.setItem(mixerStorageKey", self.ui)

    def test_privacy_shield_module_is_local_and_honest_about_its_limits(self):
        shield = SHIELD.read_text(encoding="utf-8")
        self.assertIn("class PrivacyShield", shield)
        for method in ("activate(", "deactivate(", "restore(", "snapshot("):
            with self.subTest(method=method):
                self.assertIn(f"  {method}", shield)
        self.assertIn("root.StreamioVPrivacyShield = factory();", shield)
        self.assertIn("requestsOutputStops: true", shield)
        self.assertIn("resumesOutputs: false", shield)
        self.assertIn("stopsEncoder: true", shield)
        self.assertIn("stopsRecording: true", shield)
        self.assertIn("autoResumesOutputs: false", shield)
        self.assertIn("guaranteesPlatformPrivacy: false", shield)
        self.assertIn("program-scene-local-mic-mix-and-local-output-stop-requests", shield)
        self.assertNotIn("stopsEncoder: false", shield)
        self.assertNotIn("stopsRecording: false", shield)
        self.assertTrue((SHIELD.parent / "privacy-shield.test.js").is_file())

    def test_regie_wires_the_privacy_shield_to_scene_and_microphone_mix(self):
        self.assertIn('id="privacyShield"', self.ui)
        self.assertIn('id="privacyBanner"', self.ui)
        self.assertIn('src="engine/privacy-shield.js"', self.ui)
        self.assertIn("new PrivacyShieldClass(", self.ui)
        self.assertIn("streamiov.studio.privacy-shield.v1", self.ui)
        self.assertIn("privacyShield.activate({programSceneId:programSceneId,micPercent:mixerPercent(\"mixerMic\")})", self.ui)
        self.assertIn("sceneCommand({action:\"set-program\",id:target.programSceneId})", self.ui)
        self.assertIn("setMixerPercent(\"mixerMic\",target?.micPercent??0)", self.ui)
        self.assertIn("setMixerPercent(\"mixerMic\",restore.micPercent)", self.ui)
        self.assertIn("event.shiftKey&&String(event.key).toLowerCase()===\"p\"", self.ui)
        self.assertIn("if(mic)mic.disabled=active;", self.ui)
        self.assertIn("Schutzregie aktiv: TAKE ist gesperrt.", self.ui)
        self.assertIn("Plattformseitige Privatsphäre ist nicht garantiert.", self.ui)
        self.assertIn("den Broadcast manuell neu starten", self.ui)
        self.assertIn("guaranteesPlatformPrivacy", SHIELD.read_text(encoding="utf-8"))

    def test_privacy_shield_stops_live_outputs_before_pause_and_does_not_resume(self):
        shield_block = self.ui.split("// Schutzregie / Privacy Shield:", 1)[1].split(
            "let lastStreamError", 1
        )[0]
        stop_block = shield_block.split("async function stopPrivacyShieldOutputs(){", 1)[1].split(
            "async function togglePrivacyShield(){", 1
        )[0]
        for token in (
            "studio.getStreamStatus()",
            "status?.ok===true&&status?.active===true",
            "studio.stopStream()",
            "studio.recordingStatus()",
            'studio.recordingAction("stop")',
            "recording?.ok!==true||recording?.active!==true",
            "stopped?.ok!==true",
            "kein Stop behauptet",
        ):
            with self.subTest(token=token):
                self.assertIn(token, stop_block)
        activation = shield_block.split("if(!snapshot.active){", 1)[1].split(
            "    }else{", 1
        )[0]
        self.assertLess(
            activation.index("await stopPrivacyShieldOutputs();"),
            activation.index("await applyPrivacyShieldOn();"),
        )
        self.assertIn("Stream und Aufzeichnung starten nicht automatisch wieder", shield_block)
        self.assertNotIn("Encoder und Aufnahme laufen weiter", shield_block)
        self.assertNotIn("Der Encoder läuft weiter", shield_block)
        note = self.ui.split('id="privacyShieldNote"', 1)[1].split("</p>", 1)[0]
        self.assertIn("Plattformseitige Privatsphäre ist nicht garantiert.", note)
        title = self.ui.split('id="privacyShield"', 1)[1].split(">", 1)[0]
        self.assertIn("Plattformseitige Privatsphäre ist nicht garantiert.", title)
        self.assertIn("Lokaler Encoder- und Aufzeichnungs-Stop werden angefordert", self.ui)

    def test_browser_demo_keeps_scene_selection_and_take_local_without_core(self):
        self.assertIn("const builtInSceneIds=Object.fromEntries", self.ui)
        self.assertIn('if(payload?.action==="take")', self.ui)
        self.assertIn("Demo ohne Desktop-Core: Programm lokal auf ", self.ui)
        self.assertIn("Demo ohne Desktop-Core: Vorschau lokal auf ", self.ui)
        self.assertIn("Keine Live-Ausgabe.", self.ui)
        self.assertIn('document.querySelectorAll("#scenes .scene").forEach(button=>{', self.ui)

    def test_privacy_shield_does_not_persist_the_muted_mixer_as_the_saved_level(self):
        # The shield sets the mic slider directly and only persists its own restore
        # state. It must not call saveMixerSettings with the temporary 0 % value.
        shield_block = self.ui.split("function setMixerPercent(id,percent)", 1)[1].split(
            "function savePrivacyShield", 1
        )[0]
        self.assertNotIn("saveMixerSettings()", shield_block)
        self.assertIn("applyMixerGains()", shield_block)
        self.assertIn("localStorage.setItem(shieldStorageKey", self.ui)

    def test_build_configuration_requires_node_22_and_syncs_generated_studio_assets(self):
        package = (ROOT / "dist" / "streamiov-studio-app" / "package.json").read_text(encoding="utf-8")
        self.assertIn('"node": ">=22.12.0"', package)
        self.assertIn('"main": "main.js"', package)
        self.assertNotIn("sync-studio-games.py", package)
        self.assertIn("sync-studio-tiktok-oauth.py", package)
        self.assertNotIn("sync-studio-ui.py", package)
        for hook in ("prestart", "predist:win", "predist:linux"):
            self.assertIn(f'"{hook}":', package)
        for excluded in ("!games/**", "!release/**", "!squashfs-root/**", "!index-before-*.html",
                         "!**/*.bak-*", "!**/*.before-*"):
            self.assertIn(excluded, package)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Node.js 22.12", readme)
        self.assertIn("Electron loads `regie-v2.html` directly", readme)

    def test_studio_exposes_separate_tiktok_twitch_outputs_without_manual_rtmp_keys(self):
        self.assertIn('id="platformConnectionState"', self.ui)
        self.assertIn('id="twitchConnectionState"', self.ui)
        self.assertIn("TIKTOK LIVE · EIGENER AUSGANG", self.ui)
        self.assertIn("TWITCH LIVE · EIGENER AUSGANG", self.ui)
        self.assertIn("Discord ist ein Community-/Chat-Kanal und kein LIVE-Ausgang.", self.ui)
        self.assertNotIn('id="platformSelect"', self.ui)
        self.assertNotIn('id="rtmpDestination"', self.ui)
        self.assertIn("● LIVE STARTEN", self.ui)
        self.assertIn("Kein manueller RTMP-Key", self.ui)
        self.assertIn("OAuth und LIVE-Ausgang sind getrennte Integrationen.", self.ui)

    def test_connection_metrics_are_verified_and_never_claim_live_without_remote_evidence(self):
        self.assertIn('id="coreConnection"', self.ui)
        self.assertIn('id="platformMetric"', self.ui)
        block = self.ui.split("async function refreshConnectionMetrics(){", 1)[1].split(
            "void refreshConnectionMetrics();", 1)[0]
        for token in (
            "studio.getNetworkStatus?.()",
            "studio.twitchStatus?.()",
            "studio.tiktokStatus?.()",
            "studio.getPlatformOutputStatus?.()",
            'network?.ok===true&&network?.core?.reachable===true',
            'twitch?.status==="connected"',
            'tiktok?.status==="connected"',
            'outputs?.[platform]?.liveConfirmed===true',
            'outputs[platform].state==="live"',
            '"AUSGABE BEREIT · NICHT LIVE"',
            '"VERBINDE · NICHT LIVE"',
            '"AUSGABEFEHLER · NICHT LIVE"',
        ):
            self.assertIn(token, block)
        self.assertNotIn("status===\"output_ready\"", block)
        self.assertNotIn('liveButton.textContent="LIVE"', block)
        header = self.ui.split("<header>", 1)[1].split("</header>", 1)[0]
        self.assertIn('id="coreConnection"', header)
        self.assertIn('id="connection"', header)

    def test_platform_output_registry_is_wired_without_local_live_transition(self):
        self.assertIn("ipcMain.handle('studio:platform-output-status'", self.main)
        self.assertIn("platformOutputRegistry.snapshot()", self.main)
        self.assertIn("syncPlatformOutputWithStreamStatus(status, detail);", self.main)
        self.assertIn("preparePlatformOutput(output.platform, 'Autorisierte Ausgabe vorbereitet; LIVE nicht bestätigt.')", self.main)
        self.assertIn("preparePlatformOutput('twitch', 'Twitch-Ausgabe bereit; LIVE nicht bestätigt.')", self.main)
        self.assertIn("transitionPlatformOutput(platform, 'error', 'Encoder nicht verfügbar:", self.main)
        self.assertNotIn("transitionPlatformOutput('twitch', 'live'", self.main)
        self.assertIn("confirmRemoteLiveStatuses", self.main)
        registry = (ROOT / "dist/streamiov-studio-app/engine/platform-output-registry.js").read_text(encoding="utf-8")
        self.assertIn("evidence.type !== 'remote_platform_confirmation'", registry)
        self.assertIn("throw new Error('LIVE benötigt eine gültige Bestätigung der jeweiligen Remote-Plattform.')", registry)

    def test_inline_scripts_reference_only_existing_dom_ids(self):
        import re

        dom_ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', self.ui))
        referenced = (set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", self.ui))
                      | set(re.findall(r"byId\('([A-Za-z0-9_-]+)'\)", self.ui)))
        self.assertTrue(referenced)
        self.assertEqual(sorted(referenced - dom_ids), [])

    def test_tiktok_connect_handler_has_no_dead_platform_selector(self):
        block = self.ui.split("connectButton.addEventListener('click'", 1)[1].split("});", 1)[0]
        self.assertIn("window.streamiovStudio.tiktokConnect()", block)
        self.assertNotIn("platformSelect", block)
        self.assertNotIn("platformSelect", self.ui)

    def test_blocked_stream_state_is_explicit_and_does_not_lock_sources(self):
        block = self.ui.split("function setBroadcastStatus(status,detail", 1)[1].split(
            "async function releaseBroadcastMedia", 1)[0]
        self.assertIn('blocked:"Nicht gestartet · "', block)
        self.assertIn('blocked:"GESPERRT"', block)
        self.assertIn('["offline","blocked","error"].includes(status)', block)
        self.assertIn('setSourceControlsLocked(["connecting","output_ready","reconnecting","stopping"].includes(status))', block)
        self.assertIn('if(status==="blocked")log(', block)

    def test_chat_connection_claims_are_derived_from_verified_platform_status(self):
        block = self.main.split("function chatStateResponse()", 1)[1].split(
            "ipcMain.handle('studio:chat-action'", 1)[0]
        self.assertIn("connectedPlatformAdapters(platformChat)", block)
        self.assertIn("external_platform_connected: connectedAdapters.length > 0", block)
        self.assertNotIn("snapshot.connectedAdapters.length > 0", block)

    def test_twitch_irc_receiver_brings_real_incoming_chat_into_the_regie(self):
        receiver = (ROOT / "dist" / "streamiov-studio-app" / "engine" / "twitch-chat-receiver.js").read_text(encoding="utf-8")
        self.assertIn("wss://irc-ws.chat.twitch.tv:443", receiver)
        self.assertIn("CAP REQ :twitch.tv/tags twitch.tv/commands", receiver)
        self.assertIn("PASS oauth:' + token", receiver)
        self.assertIn("PRIVMSG", receiver)
        self.assertIn("PONG :tmi.twitch.tv", receiver)
        self.assertIn("oauth_permission_required", receiver)
        self.assertIn("require('./engine/twitch-chat-receiver')", self.main)
        self.assertIn("win.webContents.send('studio:chat-message', message)", self.main)
        self.assertIn("action === 'connect-platform'", self.main)
        self.assertIn("action === 'disconnect-platform'", self.main)
        self.assertIn("irc_chat: twitchChatReceiver.status()", self.main)
        self.assertIn("onChatMessage: handler => {", self.preload)
        self.assertIn("ipcRenderer.on('studio:chat-message', listener)", self.preload)
        self.assertIn("window.streamiovStudio.onChatMessage", self.ui)
        self.assertIn("chatMessageUnsubscribe", self.ui)
        self.assertIn("Twitch-Chat verbinden", self.ui)
        oauth = (ROOT / "dist" / "streamiov-studio-app" / "twitch-oauth.js").read_text(encoding="utf-8")
        self.assertIn("const IRC_READ_SCOPES = Object.freeze(['chat:read']);", oauth)
        self.assertIn("...IRC_READ_SCOPES", oauth)
        adapters = (ROOT / "dist" / "streamiov-studio-app" / "engine" / "platform-chat-adapters.js").read_text(encoding="utf-8")
        self.assertIn("ircReadable: IRC_READ_SCOPES.every", adapters)

    def test_chat_moderation_and_role_gated_tts_are_wired_into_the_regie(self):
        moderation = (ROOT / "dist" / "streamiov-studio-app" / "engine" / "chat-moderation.js").read_text(encoding="utf-8")
        self.assertIn("class ChatModeration", moderation)
        self.assertIn("blockedWords", moderation)
        self.assertIn("bannedUsers", moderation)
        self.assertIn("slowModeSeconds", moderation)
        self.assertIn("evaluate(message)", moderation)
        self.assertTrue((ROOT / "dist" / "streamiov-studio-app" / "engine" / "chat-moderation.test.js").is_file())
        self.assertIn("require('./engine/chat-moderation')", self.main)
        self.assertIn("action === 'moderation-set'", self.main)
        self.assertIn("action === 'moderation-ban'", self.main)
        self.assertIn("action === 'moderation-unban'", self.main)
        self.assertIn("chatModeration.can(String(payload.role || 'broadcaster'), 'send')", self.main)
        self.assertIn("chatModeration.can(String(payload.role || 'broadcaster'), 'speak')", self.main)
        self.assertIn("onChatModeration", self.preload)
        self.assertIn('ipcRenderer.on(\'studio:chat-moderation\', listener)', self.preload)
        self.assertIn("twitchAuthorizeChat: () => ipcRenderer.invoke('studio:twitch-connect', { chat: true, events: true })", self.preload)
        self.assertIn("window.streamiovStudio.onChatModeration", self.ui)
        self.assertIn("chatModerationUnsubscribe", self.ui)
        self.assertIn('action:"moderation-set"', self.ui)
        self.assertIn('action:"moderation-ban"', self.ui)
        self.assertIn('action:"moderation-unban"', self.ui)
        self.assertIn('action:"speak"', self.ui)
        self.assertIn("void speakChatMessage(message);", self.ui)
        self.assertIn("Moderation speichern", self.ui)
        self.assertIn("Nachrichten vorlesen", self.ui)

    def test_twitch_eventsub_feeds_official_events_into_alerts(self):
        receiver = (ROOT / "dist" / "streamiov-studio-app" / "engine" / "twitch-eventsub-receiver.js").read_text(encoding="utf-8")
        self.assertIn("wss://eventsub.wss.twitch.tv/ws", receiver)
        self.assertIn("channel.cheer", receiver)
        self.assertIn("channel.raid", receiver)
        self.assertIn("channel.follow", receiver)
        self.assertIn("channel.subscribe", receiver)
        self.assertIn("channel.subscription.gift", receiver)
        self.assertIn("moderator:read:followers", receiver)
        self.assertIn("channel:read:subscriptions", receiver)
        self.assertIn("session_welcome", receiver)
        self.assertIn("transport: { method: 'websocket', session_id: this.sessionId }", receiver)
        self.assertIn("require('./engine/twitch-eventsub-receiver')", self.main)
        self.assertIn("action === 'connect-events'", self.main)
        self.assertIn("action === 'disconnect-events'", self.main)
        self.assertIn("eventsub: twitchEventSubReceiver.status()", self.main)
        self.assertIn("TWITCH-EVENTS VERBINDEN", self.ui)
        self.assertIn('action:"connect-events"', self.ui)
        self.assertIn('action:"disconnect-events"', self.ui)

    def test_chat_keyword_rules_trigger_real_local_alerts(self):
        self.assertIn('const alertRulesStorageKey="streamiov.alert.rules.v1"', self.ui)
        self.assertIn("function loadAlertRules()", self.ui)
        self.assertIn("function saveAlertRules()", self.ui)
        self.assertIn("function applyChatAlertRules(message)", self.ui)
        self.assertIn("applyChatAlertRules(message);", self.ui)
        self.assertIn("void showAlert(rule.text).catch(()=>{})", self.ui)
        self.assertIn('recordEvent("studio.alert.keyword"', self.ui)
        self.assertIn("Chat-Alert-Regel speichern", self.ui)
        self.assertIn("Keine Chat-Alert-Regel gespeichert.", self.ui)
        self.assertIn("alertRules=loadAlertRules();", self.ui)
        self.assertIn("alert-rule-row", self.ui)

    def test_platform_event_rules_only_use_official_events(self):
        self.assertIn('const platformEventRulesStorageKey="streamiov.alert.platform-events.v1"', self.ui)
        self.assertIn("function loadPlatformEventRules()", self.ui)
        self.assertIn("function savePlatformEventRules()", self.ui)
        self.assertIn("function applyPlatformEventRules(message)", self.ui)
        self.assertIn("applyPlatformEventRules(message);", self.ui)
        self.assertIn('recordEvent("studio.alert.platform_event"', self.ui)
        self.assertIn('const platformEventKinds=["follow","subscribe","gift_subscription","cheer","raid"]', self.ui)
        self.assertIn('recordEvent("studio.platform.event.received"', self.ui)
        self.assertNotIn('"studio.gift.sent"', self.ui)
        self.assertIn("Plattform-Event-Regel speichern", self.ui)
        self.assertIn("OFFIZIELLE PLATTFORMEREIGNISSE", self.ui)

    def test_navigation_trace_logs_redact_urls_before_writing_them(self):
        self.assertIn("require('./engine/log-redaction')", self.main)
        block = self.main.split("win.webContents.on('did-finish-load'", 1)[1].split(
            "app.on('before-quit'", 1)[0]
        self.assertEqual(block.count('redactUrlForLog('), 4)
        self.assertNotIn("'TRACE] LOAD_FAILED', code, desc, url)", block)
        self.assertNotIn("'TRACE] NAVIGATION_REQUEST', url,", block)
        self.assertNotIn("'TRACE] NAVIGATION_BLOCKED', url)", block)

    def test_studio_data_query_rejects_inherited_lookup_keys(self):
        block = self.main.split("ipcMain.handle('studio:data-query'", 1)[1].split(
            "// STREAMIOV_STUDIO_AI_BRIDGE_END", 1)[0]
        self.assertIn(
            "Object.hasOwn(STUDIO_DATA_PATHS, kind) ? STUDIO_DATA_PATHS[kind] : undefined",
            block,
        )

    def test_mixer_bootstrap_runs_after_the_state_it_reads_is_initialized(self):
        init_call = self.ui.index('refreshMixerMuteButtons();')
        music_muted = self.ui.index('let musicMuted=')
        mute_state = self.ui.index('const mixerSourceMuteState=')
        self.assertGreater(init_call, music_muted)
        self.assertGreater(init_call, mute_state)

    def test_tiktok_oauth_module_is_loaded_lazily(self):
        self.assertNotIn("const { TikTokOAuth } = require('./tiktok-oauth.js');", self.main)
        self.assertIn("TikTokOAuthClass = require('./tiktok-oauth.js').TikTokOAuth;", self.main)
        self.assertIn("tiktok_oauth_service_unavailable", self.main)
        status = self.main.split("ipcMain.handle('studio:tiktok-status'", 1)[1].split(
            "ipcMain.handle('studio:tiktok-connect'", 1
        )[0]
        self.assertIn("error.message === 'tiktok_oauth_service_unavailable'", status)

    def test_stream_start_requires_routed_unmuted_auxiliary_audio(self):
        self.assertIn('function hasStreamRoute(name)', self.ui)
        self.assertIn('function channelAudibleOnStream(name){return Boolean(studioAudioMixer?.isAudibleOn(name,"stream"));}', self.ui)
        self.assertIn('!snapshot.muted&&snapshot.routes.includes("stream")', self.ui)
        for source in ('"music"', '"tts"', '"alert"', 'pad.channelName'):
            with self.subTest(source=source):
                self.assertIn(f'channelAudibleOnStream({source})', self.ui)
        self.assertIn('channelAudibleOnStream("tts")&&!mixerSourceMuteState.tts', self.ui)
        self.assertIn('primaryAudioChannels.some(channelAudibleOnStream)', self.ui)
        self.assertIn('hasStreamRoute("music")&&!musicCurrentLiveAllowed()', self.ui)
        self.assertNotIn('!ttsAudio.paused&&studioAudioMixer.snapshot("tts")', self.ui)
        self.assertNotIn('alertToneActive&&studioAudioMixer.snapshot("alert")', self.ui)

    def test_alert_trigger_reports_when_the_local_tone_is_unavailable(self):
        block = self.ui.split("function renderAlertsTool(body){", 1)[1].split(
            "async function renderChatTool", 1
        )[0]
        self.assertIn("await showAlert(text)", block)
        self.assertIn("Ton nicht verfügbar", block)
        self.assertIn("trigger.disabled=true", block)
        self.assertNotIn('log("Lokaler Alert ausgelöst.")', self.ui)

    def test_twitch_disconnect_reports_a_failed_provider_revoke(self):
        block = self.ui.split("twitchDisconnect.addEventListener('click'", 1)[1].split(
            "twitchPrepare.addEventListener('click'", 1
        )[0]
        self.assertIn("result.revoked === false", block)
        self.assertIn("Widerruf bei Twitch fehlgeschlagen", block)
        self.assertIn("await refreshTwitchStatus()", block)

    def test_tts_output_must_be_a_real_wav_file(self):
        self.assertIn("require('./engine/audio-file-validation')", self.main)
        self.assertIn("isWavBuffer(audio)", self.main)

    def test_studio_ships_no_unofficial_platform_client(self):
        """Only official, approved platform interfaces are allowed."""
        import json

        package = json.loads(
            (ROOT / "dist" / "streamiov-studio-app" / "package.json").read_text(encoding="utf-8")
        )
        self.assertFalse(package.get("dependencies"), "runtime dependencies must stay empty")
        self.assertNotIn("tiktok-live-connector", json.dumps(package))
        lock = (ROOT / "dist" / "streamiov-studio-app" / "package-lock.json").read_text(encoding="utf-8")
        self.assertNotIn("tiktok-live-connector", lock)


    def test_local_recording_writes_composed_webm_chunks_without_upload(self):
        self.assertIn('id="recordingToggle"', self.ui)
        self.assertIn('id="recordingStatus"', self.ui)
        self.assertIn("recordingStatus: () => ipcRenderer.invoke('studio:recording-status')", self.preload)
        self.assertIn("recordingAction: (action) => ipcRenderer.invoke('studio:recording-action', action)", self.preload)
        self.assertIn("ipcMain.handle('studio:recording-status'", self.main)
        self.assertIn("ipcMain.handle('studio:recording-action'", self.main)
        self.assertIn("const RECORDING_MAX_BYTES = 2 * 1024 * 1024 * 1024;", self.main)
        self.assertIn("path.join(app.getPath('userData'), 'recordings')", self.main)
        self.assertIn("fs.open(filePath, 'wx')", self.main)
        self.assertIn("await recording.handle.write(chunk)", self.main)
        self.assertIn("if (written.ok !== false && streamRecording?.mode === 'stream') await appendStreamRecording(bytes);", self.main)
        self.assertIn("const recording = streamRecording?.mode === 'stream' ? await stopStreamRecording('stream_stopped')", self.main)
        self.assertIn("if(sent?.recording?.ok)updateRecordingUi(sent.recording);", self.ui)
        self.assertIn('const result=await studio.recordingAction("stop");', self.ui)
        self.assertIn('const result=await studio.recordingAction("start");', self.ui)
        self.assertIn("{ id: 'local-recording', status: 'local_webm_file'", self.main)
        self.assertIn("ipcMain.handle('studio:record-chunk'", self.main)
        self.assertIn("ipcMain.handle('studio:recording-list'", self.main)
        self.assertIn("ipcMain.handle('studio:recording-file-action'", self.main)
        self.assertIn("recordChunk: (chunk) => ipcRenderer.invoke('studio:record-chunk', chunk)", self.preload)
        self.assertIn("recordingList: () => ipcRenderer.invoke('studio:recording-list')", self.preload)
        self.assertIn("recordingFileAction: (id, action) => ipcRenderer.invoke('studio:recording-file-action', { id, action })", self.preload)
        self.assertIn('id="recordingRefresh"', self.ui)
        self.assertIn('id="recordingFiles"', self.ui)
        self.assertIn("async function startLocalRecorder()", self.ui)
        self.assertIn("async function stopLocalRecording()", self.ui)
        self.assertIn("localRecordingCanvasStream=canvas.captureStream(fps)", self.ui)
        self.assertIn("if(!streamState?.active){", self.ui)
        self.assertIn("await stopLocalRecording();", self.ui)
        self.assertIn("async function refreshRecordingFiles()", self.ui)
        self.assertIn("void refreshRecordingFiles();", self.ui)


if __name__ == "__main__":
    unittest.main()
