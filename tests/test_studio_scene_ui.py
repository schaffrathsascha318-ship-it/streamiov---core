"""Static regression checks for the Electron Studio scene bridge.

These checks do not claim to verify video composition or live output.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "dist" / "streamiov-studio-app" / "main.js"
UI = ROOT / "dist" / "streamiov-studio-app" / "regie-v2.html"
PRELOAD = ROOT / "dist" / "streamiov-studio-app" / "preload.js"


class StudioSceneBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.ui = UI.read_text(encoding="utf-8")
        cls.preload = PRELOAD.read_text(encoding="utf-8")

    def test_preload_exposes_scene_action(self):
        self.assertIn("sceneAction: (payload) => ipcRenderer.invoke('studio:scene-action', payload)", self.preload)

    def test_main_process_checks_sender_and_persists_scenes(self):
        handler = self.main.split("ipcMain.handle('studio:scene-action'", 1)[1].split(
            "// Crostini-Kompatibilität", 1
        )[0]
        self.assertIn("isTrustedStudioSender(event)", handler)
        self.assertIn("app.getPath('userData')", handler)
        self.assertIn("await save(state)", handler)
        self.assertIn("action === 'create'", handler)
        self.assertIn("state.programSceneId = state.previewSceneId", handler)

    def test_regie_loads_selects_and_takes_persistent_scenes(self):
        self.assertIn('window.streamiovStudio.sceneAction({action:"load"})', self.ui)
        self.assertIn('window.streamiovStudio.sceneAction({action:"select",name})', self.ui)
        self.assertIn('window.streamiovStudio.sceneAction({action:"take"})', self.ui)
        self.assertIn('id="createScene"', self.ui)

    def test_live_button_does_not_claim_to_start_a_stream(self):
        self.assertIn('LIVE wurde nicht gestartet.', self.ui)
        self.assertIn('keine Live-Ausgabe', self.ui)


if __name__ == "__main__":
    unittest.main()
