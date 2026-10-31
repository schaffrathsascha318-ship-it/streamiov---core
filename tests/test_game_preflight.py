import json
import tempfile
import unittest
from pathlib import Path

from ai.buildbot.game_preflight import validate_game_package


class GamePreflightTests(unittest.TestCase):
    def make_game(self, root: Path, entry: str = "index.html") -> Path:
        game = root / "sample"
        game.mkdir()
        (game / "streamiov-game.json").write_text(
            json.dumps({"id": "sample", "title": "Sample", "entry": entry}),
            encoding="utf-8",
        )
        (game / "index.html").write_text(
            '<!doctype html><html><head></head><body><script src="game.js"></script></body></html>',
            encoding="utf-8",
        )
        (game / "game.js").write_text("document.body.dataset.ready = 'yes';", encoding="utf-8")
        return game

    def test_valid_static_package_never_claims_playability_or_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_game_package(self.make_game(Path(tmp)))
        self.assertTrue(result["static_valid"])
        self.assertEqual(result["checked_local_resource_references"], 1)
        self.assertFalse(result["browser_playability_verified"])
        self.assertFalse(result["download_ready"])
        self.assertEqual(result["release_status"], "NOT_RELEASED")

    def test_rejects_path_traversal_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.make_game(Path(tmp), "../outside.html")
            result = validate_game_package(game)
        self.assertFalse(result["static_valid"])
        self.assertIn("entry_path_unsafe", result["errors"])

    def test_detects_missing_local_runtime_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.make_game(Path(tmp))
            (game / "game.js").unlink()
            result = validate_game_package(game)
        self.assertIn("local_runtime_resource_missing", result["errors"])

    def test_reports_external_runtime_resource_without_claiming_it_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.make_game(Path(tmp))
            (game / "index.html").write_text(
                '<html><body><script src="https://example.invalid/game.js"></script></body></html>',
                encoding="utf-8",
            )
            result = validate_game_package(game)
        self.assertTrue(result["static_valid"])
        self.assertIn("external_runtime_resources_detected", result["warnings"])
        self.assertEqual(result["external_resources"][0]["type"], "script")

    def test_rejects_invalid_manifest_and_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.make_game(Path(tmp))
            (game / "streamiov-game.json").write_text("{", encoding="utf-8")
            result = validate_game_package(game)
            self.assertIn("manifest_invalid_json", result["errors"])
            (game / "streamiov-game.json").unlink()
            result = validate_game_package(game)
        self.assertIn("manifest_missing", result["errors"])

    def test_rejects_incomplete_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.make_game(Path(tmp))
            (game / "index.html").write_text("<html><body>unfinished", encoding="utf-8")
            result = validate_game_package(game)
        self.assertIn("entry_html_incomplete", result["errors"])


if __name__ == "__main__":
    unittest.main()
