"""Static regression checks for the Electron Studio scene and runtime bridges."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "dist" / "streamiov-studio-app" / "main.js"
UI = ROOT / "dist" / "streamiov-studio-app" / "regie-v2.html"
PRELOAD = ROOT / "dist" / "streamiov-studio-app" / "preload.js"


class StudioRuntimeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.ui = UI.read_text(encoding="utf-8")
        cls.preload = PRELOAD.read_text(encoding="utf-8")

    def test_preload_exposes_scene_and_runtime_diagnostics(self):
        self.assertIn("sceneAction: (payload) => ipcRenderer.invoke('studio:scene-action', payload)", self.preload)
        self.assertIn("getRuntimeDiagnostics: () => ipcRenderer.invoke('studio:get-runtime-diagnostics')", self.preload)

    def test_runtime_diagnostics_is_sender_guarded_and_reports_missing_dependencies(self):
        handler = self.main.split("ipcMain.handle('studio:get-runtime-diagnostics'", 1)[1].split(
            "// Crostini-Kompatibilität", 1
        )[0]
        self.assertIn("isTrustedStudioSender(event)", handler)
        self.assertIn("gst-inspect-1.0", handler)
        self.assertIn("gst-launch-1.0", handler)
        self.assertIn("x264enc", handler)
        self.assertIn("rtmpsink", handler)
        self.assertIn("live_stream_verified: false", handler)

    def test_regie_exposes_a_real_diagnostics_action(self):
        self.assertIn('id="runtimeCheck"', self.ui)
        self.assertIn('window.streamiovStudio.getRuntimeDiagnostics()', self.ui)
        self.assertIn("LIVE wurde nicht gestartet.", self.ui)

    def test_scene_actions_remain_persistent(self):
        self.assertIn("studio:scene-action", self.main)
        self.assertIn("await save(state)", self.main)
        self.assertIn('window.streamiovStudio.sceneAction({action:"take"})', self.ui)

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


if __name__ == "__main__":
    unittest.main()
