"""Static regression checks for the Electron Studio scene and runtime bridges."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "dist" / "streamiov-studio-app" / "main.js"
UI = ROOT / "dist" / "streamiov-studio-app" / "regie-v2.html"
PRELOAD = ROOT / "dist" / "streamiov-studio-app" / "preload.js"
ENGINE = ROOT / "dist" / "streamiov-studio-app" / "engine" / "scene-engine.js"


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

    def test_gift_gallery_keeps_tiktok_payouts_external_and_streamiov_gifts_free(self):
        self.assertIn("TikTok wickelt Kauf, Zuordnung und mögliche Auszahlung direkt ab.", self.ui)
        self.assertIn("StreamioV zieht nichts ab und nimmt kein Geld entgegen.", self.ui)
        self.assertIn("eine 1:1-Umrechnung des Kaufpreises ist nicht zugesichert.", self.ui)
        self.assertIn("Eigene Galerieeffekte sind kostenlos", self.ui)
        self.assertIn("keine offizielle TikTok-Geschenkefreigabe", self.ui)

        self.assertIn('id="rtmpDestination"', self.ui)
        self.assertIn("window.streamiovStudio.startStream({", self.ui)
        self.assertIn("window.streamiovStudio.stopStream()", self.ui)

    def test_rtmp_process_controls_are_sender_guarded_and_validate_destination(self):
        for channel in ("studio:start-stream", "studio:write-stream-chunk", "studio:stop-stream"):
            self.assertIn(f"ipcMain.handle('{channel}'", self.main)
            self.assertIn("isTrustedStudioSender(event)", self.main)
        self.assertIn("['rtmp:', 'rtmps:'].includes(url.protocol)", self.main)
        self.assertIn("url.username || url.password || url.hash", self.main)
        self.assertIn("Never forward or persist raw FFmpeg output", self.main)
        self.assertIn("'-c:v', 'libx264'", self.main)
        self.assertIn("'-c:a', 'aac'", self.main)

    def test_screen_capture_requires_trusted_source_selection(self):
        self.assertIn("studio:list-display-sources", self.main)
        self.assertIn("studio:select-display-source", self.main)
        self.assertIn("frame.parent !== null || frame.url !== studioUrl || !sourceId", self.main)
        self.assertIn("['media', 'display-capture'].includes(permission)", self.main)
        self.assertIn("getDisplayMedia({video:true,audio:true})", self.ui)

    def test_scene_actions_remain_persistent(self):
        self.assertIn("studio:scene-action", self.main)
        self.assertIn("streamiov-scenes.json", self.main)
        self.assertIn("await fs.writeFile(temporary, JSON.stringify(engine.toJSON()", self.main)
        self.assertIn("await fs.rename(temporary, file)", self.main)
        self.assertIn('sceneCommand({action:"take"})', self.ui)

    def test_scene_engine_supports_layout_sources_and_v1_migration(self):
        engine = ENGINE.read_text(encoding="utf-8")
        self.assertIn("const SCENE_VERSION = 2;", engine)
        for source_type in ("'camera'", "'screen'", "'title'", "'text'"):
            self.assertIn(source_type, engine)
        for action in ("addSource", "updateSource", "removeSource", "moveSource",
                       "setBackground", "deleteScene", "renameScene"):
            with self.subTest(action=action):
                self.assertIn(f"  {action}(", engine)
        self.assertIn("savedState.version != null && ![1, SCENE_VERSION].includes(savedState.version)", engine)
        self.assertIn("function cleanSource(raw, index)", engine)
        self.assertIn("Math.trunc(clamp(raw.z, 0, 100, index))", engine)
        self.assertIn("direction === 'up' ? index + 1 : index - 1", engine)
        self.assertIn("MAX_SOURCES", engine)
        self.assertIn("MAX_SCENES", engine)

    def test_scene_handler_dispatches_to_the_engine(self):
        handler = self.main.split("ipcMain.handle('studio:scene-action'", 1)[1].split(
            "// Eigene, lokal paketierte Spielebibliothek", 1
        )[0]
        for action in ("select", "take", "create", "rename-scene", "delete-scene",
                       "add-source", "update-source", "remove-source",
                       "move-source", "set-background"):
            with self.subTest(action=action):
                self.assertIn(f"action === '{action}'", handler)
        for method in ("selectPreview", "take", "createScene", "renameScene",
                       "deleteScene", "addSource", "updateSource", "removeSource",
                       "moveSource", "setBackground"):
            with self.subTest(method=method):
                self.assertIn(f"engine.{method}(", handler)


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
        self.assertIn("repository_capability_inventory", self.main)
        self.assertIn("foundation_only", self.main)
        self.assertIn("not_implemented", self.main)
        self.assertNotIn("missingPythonModules", self.main)
        self.assertNotIn("notBundledResult", self.main)
        self.assertNotIn("process.resourcesPath", self.main)

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
        self.assertIn("FFmpeg mit libx264, AAC und RTMP-Unterstützung", download)


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
        for element_id in ("mixerMic", "mixerSystem", "mixerMaster",
                           "mixerMicValue", "mixerSystemValue", "mixerMasterValue",
                           "mixerStatus"):
            self.assertIn(f'id="{element_id}"', self.ui)
        self.assertNotIn("<b>Musik</b><div class=\"meter\">", self.ui)
        self.assertNotIn("<b>Spiel</b><div class=\"meter\">", self.ui)
        self.assertNotIn("<b>Alerts</b><div class=\"meter\">", self.ui)

    def test_audio_mixer_gains_are_applied_to_the_stream_mix(self):
        self.assertIn("broadcastTrackGains.push({kind,gain:volume})", self.ui)
        self.assertIn("broadcastMasterGain.connect(audioOutput)", self.ui)
        self.assertIn("source.connect(volume).connect(broadcastMasterGain)", self.ui)
        self.assertIn("entry.gain.gain.setTargetAtTime(target,now,0.02)", self.ui)
        self.assertIn("broadcastMasterGain.gain.setTargetAtTime(mixerValue(\"mixerMaster\"),now,0.02)", self.ui)
        self.assertIn("localStorage.setItem(mixerStorageKey", self.ui)

    def test_build_configuration_requires_node_22_and_syncs_generated_studio_assets(self):
        package = (ROOT / "dist" / "streamiov-studio-app" / "package.json").read_text(encoding="utf-8")
        self.assertIn('"node": ">=22.12.0"', package)
        self.assertIn('"main": "main.js"', package)
        self.assertIn("sync-studio-games.py", package)
        self.assertIn("sync-studio-tiktok-oauth.py", package)
        self.assertNotIn("sync-studio-ui.py", package)
        for hook in ("prestart", "predist:win", "predist:linux"):
            self.assertIn(f'"{hook}":', package)
        for excluded in ("!release/**", "!squashfs-root/**", "!index-before-*.html",
                         "!**/*.bak-*", "!**/*.before-*"):
            self.assertIn(excluded, package)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Node.js 22.12", readme)
        self.assertIn("Electron loads `regie-v2.html` directly", readme)

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


if __name__ == "__main__":
    unittest.main()
