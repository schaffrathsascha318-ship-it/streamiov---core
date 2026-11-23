from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate-native-games.py"


class NativeGameGeneratorSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.template = self.root / "template"
        self.destination = self.root / "games" / "native"
        self.template.mkdir(parents=True)
        (self.template / "main.gd").write_text("extends Node2D\n", encoding="utf-8")
        (self.template / "main.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
        (self.template / "icon.svg").write_text("<svg/>\n", encoding="utf-8")
        self.generator = runpy.run_path(str(SCRIPT))
        self.generator["TEMPLATE"] = self.template
        self.generator["DEST"] = self.destination
        self.generator["GAMES"] = [("neon-relay", "Neon Relay", "Arcade")]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_refuses_to_overwrite_unowned_directory(self) -> None:
        project = self.destination / "neon-relay"
        project.mkdir(parents=True)
        important = project / "creator-work.txt"
        important.write_text("keep this work", encoding="utf-8")

        with self.assertRaisesRegex(SystemExit, "not owned by this generator"):
            self.generator["main"]()

        self.assertEqual(important.read_text(encoding="utf-8"), "keep this work")

    def test_regenerates_only_directory_with_matching_ownership_marker(self) -> None:
        self.generator["main"]()
        project = self.destination / "neon-relay"
        marker = project / ".streamiov-generated-native-game"
        self.assertEqual(marker.read_text(encoding="utf-8").strip(), "neon-relay")

        (project / "stale-generated-file.tmp").write_text("stale", encoding="utf-8")
        self.generator["main"]()

        self.assertTrue((project / "game.json").is_file())
        self.assertFalse((project / "stale-generated-file.tmp").exists())
        self.assertEqual(marker.read_text(encoding="utf-8").strip(), "neon-relay")

    def test_refuses_symlinked_game_directory(self) -> None:
        self.destination.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("safe", encoding="utf-8")
        link = self.destination / "neon-relay"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Directory symlinks are unavailable on this platform.")

        with self.assertRaisesRegex(SystemExit, "symlinked game directory"):
            self.generator["main"]()

        self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "safe")


if __name__ == "__main__":
    unittest.main()
