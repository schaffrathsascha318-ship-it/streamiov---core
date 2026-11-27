"""Regression coverage for the Studio-to-Core rights-gated music bridge."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "dist" / "streamiov-studio-app"
MAIN = STUDIO / "main.js"
UI = STUDIO / "regie-v2.html"
HOST = ROOT / "host" / "server.py"


class StudioMusicBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.ui = UI.read_text(encoding="utf-8")
        cls.host = HOST.read_text(encoding="utf-8")

    def test_main_allowlists_only_the_known_music_queries(self):
        paths = self.main.split("const STUDIO_DATA_PATHS", 1)[1].split("const STUDIO_DATA_PARAM_RULES", 1)[0]
        self.assertIn("music: '/api/v1/music/library'", paths)
        self.assertIn("musicGate: '/api/v1/music/gate'", paths)
        self.assertIn("musicDossier: '/api/v1/music/dossier'", paths)
        self.assertNotIn("'/api/v1/music/audio/'", paths)

    def test_main_validates_query_parameters_before_fetching(self):
        rules = self.main.split("const STUDIO_DATA_PARAM_RULES", 1)[1].split("ipcMain.handle('studio:data-query'", 1)[0]
        self.assertIn("territory: /^[A-Z]{2}$/", rules)
        self.assertIn("track: /^[a-z0-9][a-z0-9_-]{1,63}$/", rules)
        self.assertIn("usage: /^(local_playback|live_stream|saved_vod|download)$/", rules)
        handler = self.main.split("ipcMain.handle('studio:data-query'", 1)[1].split(
            "// STREAMIOV_STUDIO_AI_BRIDGE_END", 1
        )[0]
        self.assertIn("isTrustedStudioSender(event)", handler)
        self.assertIn("const rules = STUDIO_DATA_PARAM_RULES[kind] || {}", handler)
        self.assertIn("if (!pattern.test(value))", handler)
        self.assertIn("const requestUrl = STREAMIOV_API + dataPath + (suffix ? '?' + suffix : '')", handler)
        self.assertIn("fetch(requestUrl", handler)

    def test_regie_uses_the_gate_before_queueing_catalogue_audio(self):
        section = self.ui.split("async function renderMusicTool(body){", 1)[1].split(
            "async function playMusicQueueItem(index){", 1
        )[0]
        self.assertIn('dataApi({kind:"musicGate",params:{territory:code,usage:musicUsage}})', section)
        self.assertIn('dataApi({kind:"musicDossier",params:{track:trackId,territory:currentTerritory(),usage:musicUsage}})', section)
        self.assertIn('"/api/v1/music/audio/"+id', self.ui)
        self.assertIn('if(track.allowed&&track.state==="playable"){', section)
        self.assertIn("track.state", section)
        self.assertIn("Array.isArray(track.reasons)", section)
        self.assertNotIn("track.local_file", section)
        self.assertNotIn("track.local_path", section)

    def test_regie_keeps_local_blobs_and_remote_audio_safe(self):
        section = self.ui.split("async function renderMusicTool(body){", 1)[1].split(
            "async function playMusicQueueItem(index){", 1
        )[0]
        self.assertIn('musicPlayerAudio.crossOrigin="anonymous"', section)
        self.assertIn('const importApi=window.streamiovStudio?.importMediaAssets;', section)
        self.assertIn('await importApi({kind:"audio"})', section)
        self.assertIn('streamiov-media://asset/', self.ui)
        self.assertNotIn("URL.createObjectURL", section)
        self.assertIn("musicQueue.length>=100", section)

    def test_host_audio_is_loopback_only_and_cors_limited_to_file_origin(self):
        handler = self.host.split("def _music_request", 1)[1].split("def _forum_request", 1)[0]
        self.assertIn("peer.is_loopback", handler)
        self.assertIn('"error": "audio_loopback_only"', handler)
        self.assertIn('cors_origin="null"', handler)
        self.assertIn("playable_audio(track_id, territory, usage)", handler)


if __name__ == "__main__":
    unittest.main()
