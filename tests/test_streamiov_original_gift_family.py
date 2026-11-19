import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/game_actions/streamiov_original_gift_family.json"


class StreamiovOriginalGiftFamilyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_family_has_exactly_twelve_original_concepts(self):
        gifts = self.family["gifts"]
        self.assertEqual(len(gifts), 12)
        self.assertEqual(len({gift["id"] for gift in gifts}), 12)
        self.assertEqual(len({gift["name"] for gift in gifts}), 12)

    def test_every_concept_has_individual_geometry_and_animation_brief(self):
        for gift in self.family["gifts"]:
            with self.subTest(gift=gift["id"]):
                self.assertTrue(gift["silhouette"].strip())
                self.assertTrue(gift["materials"])
                animation = gift["animation"]
                self.assertTrue(animation["intro"].strip())
                self.assertTrue(animation["hero"].strip())
                self.assertTrue(animation["outro"].strip())
                self.assertGreater(gift["runtime_seconds"], 0)

    def test_rose_is_explicitly_preserved_and_not_redefined(self):
        self.assertEqual(
            self.family["policy"]["rose"],
            "preserve_unchanged",
        )
        self.assertNotIn("rose", {gift["id"] for gift in self.family["gifts"]})

    def test_family_is_not_misrepresented_as_tiktok_approved_or_released(self):
        self.assertEqual(
            self.family["policy"]["release_status"],
            "design_specification_only",
        )
        self.assertEqual(
            self.family["policy"]["official_tiktok_gallery"],
            "requires_explicit_written_tiktok_approval_and_platform_integration",
        )
        self.assertEqual(
            self.family["visual_system"]["technical_target"],
            "authored 3D asset (glTF 2.0 or equivalent) plus optimized runtime animation; SVG is preview art only, never a 3D completion claim",
        )


if __name__ == "__main__":
    unittest.main()
