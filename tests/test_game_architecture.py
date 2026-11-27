from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "dist" / "streamiov-studio-app"
HOMEPAGE = ROOT / "dist" / "streamiov-homepage-worker" / "public"
DOWNLOAD_PAGE = HOMEPAGE / "download" / "index.html"
INDEX_PAGE = HOMEPAGE / "index.html"


class GameArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (STUDIO / "main.js").read_text(encoding="utf-8")
        cls.preload = (STUDIO / "preload.js").read_text(encoding="utf-8")
        cls.ui = (STUDIO / "regie-v2.html").read_text(encoding="utf-8")
        cls.download = DOWNLOAD_PAGE.read_text(encoding="utf-8")
        cls.home = INDEX_PAGE.read_text(encoding="utf-8")

    def test_studio_has_no_game_gallery_download_or_launch(self):
        for marker in ("studio:list-games", "studio:open-game", "game-library-panel", "loadGameLibrary",
                       "SPIEL ÖFFNEN", "listGames", "openGame", "sync-studio-games.py"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.main + self.preload + self.ui)

    def test_studio_analysis_is_wired_through_main_preload_and_regie(self):
        self.assertIn("studio:game-analysis", self.main)
        self.assertIn("gameAnalysis:", self.preload)
        self.assertIn('data-tool="Spielanalyse"', self.ui)
        self.assertIn("renderGameAnalysisTool", self.ui)
        self.assertIn("studio.gameplay.observation", self.ui)
        self.assertIn("studio.game.replay_marker", self.ui)
        self.assertTrue((STUDIO / "engine" / "game-analysis.js").is_file())
        self.assertTrue((STUDIO / "engine" / "game-process-detector.js").is_file())

    def test_homepage_presents_official_game_downloads_without_running_games(self):
        section = self.download.split('<section id="spiele">', 1)[1].split("</section>", 1)[0]
        for name in ("Echo Grid", "Neon Relay", "Pulse Defender", "Signal Weave", "Star Defender"):
            with self.subTest(name=name):
                self.assertIn(name, section)
        for archive in (
            "streamiov-echo-grid-0.1.0-prototype.zip",
            "streamiov-neon-relay-0.1.0-prototype.zip",
            "streamiov-pulse-defender-0.1.0-prototype.zip",
            "streamiov-signal-weave-0.1.0-prototype.zip",
            "streamiov-star-defender-0.2.0-prototype.zip",
        ):
            with self.subTest(archive=archive):
                self.assertIn(f'href="/downloads/{archive}"', section)
        for marker in ("Version 0.1.0", "Version 0.2.0", "OS:", "Update:", "SHA-256",
                       "Screenshot nicht veröffentlicht", "SHA256SUMS-games.txt"):
            with self.subTest(marker=marker):
                self.assertIn(marker, section)
        self.assertNotIn("<iframe", section)
        self.assertNotIn("openGame", section)
        self.assertNotIn("studio:open-game", section)

    def test_home_index_points_game_downloads_to_the_official_hub(self):
        self.assertIn('href="/download/#spiele"', self.home)
        self.assertIn("ausschließlich über die offizielle Download-Seite", self.home)
        self.assertIn("kein Spielstart", self.home)

    def test_event_contracts_use_analysis_events_instead_of_launch_events(self):
        client = (STUDIO / "engine" / "studio-event-client.js").read_text(encoding="utf-8")
        store = (ROOT / "host" / "event_store.py").read_text(encoding="utf-8")
        for event in ("studio.game.detected", "studio.gameplay.observation", "studio.game.highlight",
                      "studio.game.replay_marker", "studio.game.assistant_advice"):
            with self.subTest(event=event):
                self.assertIn(event, client)
                self.assertIn(event, store)
        self.assertNotIn("studio.game.opened", client + store)
        self.assertNotIn("game.launched", client + store)


if __name__ == "__main__":
    unittest.main()
