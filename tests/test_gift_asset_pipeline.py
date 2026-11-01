import json
import tempfile
import unittest
from pathlib import Path

from ai.runtime.gift_asset_pipeline import (
    GiftAssetError,
    build_gift_pack,
    validate_svg,
)


VALID_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><circle cx="64" cy="64" r="42" fill="#7c70ff"/></svg>'


class GiftAssetPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.svg"
        self.source.write_bytes(VALID_SVG)

    def tearDown(self):
        self.temp.cleanup()

    def test_validates_svg_and_calculates_checksum(self):
        result = validate_svg(VALID_SVG)
        self.assertEqual(result["format"], "image/svg+xml")
        self.assertEqual(result["width"], 128)
        self.assertEqual(len(result["sha256"]), 64)

    def test_rejects_script_external_reference_and_event_handler(self):
        for content in (
            b'<svg viewBox="0 0 10 10"><script>alert(1)</script></svg>',
            b'<svg viewBox="0 0 10 10"><image href="https://example.com/a.png"/></svg>',
            b'<svg viewBox="0 0 10 10"><rect onclick="alert(1)"/></svg>',
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg viewBox="0 0 10 10"/>',
        ):
            with self.subTest(content=content), self.assertRaises(GiftAssetError):
                validate_svg(content)

    def test_builds_deterministic_review_required_pack(self):
        assets = [{
            "id": "neon-heart",
            "name": "Neonherz",
            "source": str(self.source),
            "streamiov_points": 10,
            "accessibility_text": "Ein violettes Neonherz mit türkisfarbenem Leuchten.",
        }]
        first = build_gift_pack(pack_id="neon-starters", assets=assets, output_root=self.root / "packs")
        manifest_path = self.root / "packs/neon-starters/manifest.json"
        first_bytes = manifest_path.read_bytes()
        self.assertEqual(first["pack_status"], "REVIEW_REQUIRED")
        self.assertFalse(first["published"])
        self.assertFalse(first["real_money_enabled"])
        self.assertEqual(first["gifts"][0]["price_unit"], "STREAMIOV_POINTS")
        self.assertIsNone(first["gifts"][0]["tiktok_coin_price"])
        self.assertTrue((manifest_path.parent / "neon-heart.svg").is_file())

        second_root = self.root / "second-packs"
        build_gift_pack(pack_id="neon-starters", assets=assets, output_root=second_root)
        second_bytes = (second_root / "neon-starters/manifest.json").read_bytes()
        self.assertEqual(first_bytes, second_bytes)

    def test_rejects_duplicate_ids_and_invalid_point_values(self):
        entry = {"id": "gift-one", "name": "Gift", "source": str(self.source)}
        with self.assertRaises(GiftAssetError):
            build_gift_pack(pack_id="neon-starters", assets=[entry, entry], output_root=self.root / "out")
        with self.assertRaises(GiftAssetError):
            build_gift_pack(
                pack_id="neon-starters",
                assets=[{**entry, "streamiov_points": True}],
                output_root=self.root / "other",
            )

    def test_refuses_overwrite(self):
        entry = {"id": "gift-one", "name": "Gift", "source": str(self.source)}
        output = self.root / "out"
        build_gift_pack(pack_id="neon-starters", assets=[entry], output_root=output)
        with self.assertRaises(GiftAssetError):
            build_gift_pack(pack_id="neon-starters", assets=[entry], output_root=output)


if __name__ == "__main__":
    unittest.main()
