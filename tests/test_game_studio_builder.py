import json
import tempfile
import unittest
from pathlib import Path

from ai.game_studio.builder import (
    GameBriefError,
    create_design_workspace,
    validate_game_brief,
)


def brief():
    return {
        "id": "crystal-frontier",
        "title": "Crystal Frontier",
        "genre": "3D action adventure",
        "vision": "Explore a living alien frontier and defend its settlements.",
        "core_gameplay": "Traversal, tactical combat and resource discovery.",
        "progression": "Unlock abilities and new regions through meaningful choices.",
        "art_direction": "Original stylized sci-fi world with readable silhouettes.",
        "audio_direction": "Adaptive orchestral-electronic score and spatial effects.",
        "accessibility": "Remappable controls, subtitles, scalable UI and difficulty aids.",
        "test_plan": "Automated gameplay simulation plus real device playthroughs.",
        "target_platforms": ["Windows 11 x64", "Linux x86_64", "Android ARM64"],
        "signature_mechanics": ["Gravity-shift traversal", "Reactive settlement defence"],
        "core_loop": ["Explore a region", "Discover resources", "Defend an outpost"],
        "level_plan": ["Frontier arrival", "Storm ravine", "Crystal citadel"],
        "controls": {"keyboard": "WASD move; mouse aim", "touch": "Virtual stick and action buttons"},
        "rights": {"original_concept": True, "third_party_components": []},
    }


class GameStudioBuilderTests(unittest.TestCase):
    def test_validates_substantial_original_brief_without_claiming_release(self):
        result = validate_game_brief(brief())
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "DESIGN_BRIEF_VALIDATED")
        self.assertFalse(result["playability_verified"])
        self.assertFalse(result["release_ready"])
        self.assertEqual(result["planned_levels_or_challenges"], 3)

    def test_rejects_non_original_concept(self):
        spec = brief()
        spec["rights"]["original_concept"] = False
        with self.assertRaises(GameBriefError):
            validate_game_brief(spec)

    def test_rejects_thin_gameplay_brief(self):
        spec = brief()
        spec["signature_mechanics"] = ["Generic score counter"]
        with self.assertRaises(GameBriefError):
            validate_game_brief(spec)

    def test_creates_audited_workspace_without_overwriting_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_design_workspace(brief(), root)
            project = root / result["workspace"]
            self.assertTrue((project / "design-brief.json").is_file())
            self.assertTrue((project / "builder-audit.json").is_file())
            self.assertIn("not a playable game", (project / "README.md").read_text())
            with self.assertRaises(FileExistsError):
                create_design_workspace(brief(), root)

    def test_rejects_invalid_project_identifier(self):
        spec = brief()
        spec["id"] = "../outside"
        with self.assertRaises(GameBriefError):
            validate_game_brief(spec)


if __name__ == "__main__":
    unittest.main()
