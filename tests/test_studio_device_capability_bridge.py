"""Regression coverage for the measured Studio device-capability bridge."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "dist" / "streamiov-studio-app"
MAIN = STUDIO / "main.js"
PRELOAD = STUDIO / "preload.js"
UI = STUDIO / "regie-v2.html"
BRIDGE = STUDIO / "engine" / "device-capabilities-bridge.js"


class StudioDeviceCapabilityBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.preload = PRELOAD.read_text(encoding="utf-8")
        cls.ui = UI.read_text(encoding="utf-8")
        cls.bridge = BRIDGE.read_text(encoding="utf-8")

    def test_bridge_normalises_only_measured_capabilities(self):
        self.assertIn("return null;", self.bridge)
        self.assertIn("features[feature] = parsed.status;", self.bridge)
        self.assertIn("evidence[feature] = Object.freeze", self.bridge)
        self.assertIn("PLATFORM_ALIASES[String(platform).toLowerCase()]", self.bridge)
        self.assertIn("ARCHITECTURE_ALIASES[String(architecture).toLowerCase()]", self.bridge)

    def test_main_handler_is_sender_guarded_and_uses_real_probes(self):
        handler = self.main.split("ipcMain.handle('studio:get-device-capabilities'", 1)[1].split(
            "let selectedDisplaySourceId", 1
        )[0]
        self.assertIn("isTrustedStudioSender(event)", handler)
        self.assertIn("collectRendererMeasurements(rendererPayload)", handler)
        self.assertIn("screen.getAllDisplays()", handler)
        self.assertIn("desktopCapturer.getSources", handler)
        self.assertIn("fs.access(app.getPath('userData'), fsConstants.W_OK)", handler)
        self.assertIn("Notification.isSupported()", handler)
        self.assertIn("process.platform", handler)
        self.assertIn("os.arch()", handler)
        self.assertIn("createDeviceCapabilityReport({", handler)

    def test_preload_exposes_the_bridge_without_bypassing_ipc(self):
        self.assertIn(
            "getDeviceCapabilities: (measurements) => ipcRenderer.invoke('studio:get-device-capabilities', measurements)",
            self.preload,
        )

    def test_regie_shows_a_measured_profile_in_the_runtime_check(self):
        self.assertIn('id="deviceCapabilityStatus"', self.ui)
        self.assertIn("navigator.mediaDevices.enumerateDevices()", self.ui)
        self.assertIn('features.touchInput={value:window.matchMedia("(pointer: coarse)").matches', self.ui)
        self.assertIn("window.streamiovStudio.getDeviceCapabilities?.(rendererMeasurements)", self.ui)
        self.assertIn("capabilityOutput.textContent", self.ui)
        self.assertIn("statusLabels[value?.status]", self.ui)


if __name__ == "__main__":
    unittest.main()
