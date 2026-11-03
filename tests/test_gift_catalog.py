import json
import tempfile
import unittest
from pathlib import Path

from ai.runtime.gift_catalog import GiftCatalog, GiftCatalogError


class GiftCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        (self.assets / "neon-heart.svg").write_text("<svg></svg>", encoding="utf-8")
        self.catalog_file = self.root / "catalog.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_catalog(self, gifts):
        self.catalog_file.write_text(json.dumps({
            "schema_version": 1,
            "points_note": "STREAMIOV points, not TikTok coins.",
            "gifts": gifts,
        }), encoding="utf-8")

    def gift(self, **changes):
        item = {
            "id": "neon-heart",
            "name": "Neonherz",
            "streamiov_points": 10,
            "svg": "/assets/gifts/neon-heart.svg",
            "status": "released",
            "tiktok_gift_id": None,
        }
        item.update(changes)
        return item

    def test_released_gift_requires_an_existing_asset(self):
        self.write_catalog([self.gift()])
        catalog = GiftCatalog.load(self.catalog_file, asset_root=self.assets)
        self.assertEqual(len(catalog.released_gifts()), 1)
        self.assertTrue(catalog.snapshot()["gifts"][0]["released"])

        self.write_catalog([self.gift(svg="/assets/gifts/missing.svg")])
        missing = GiftCatalog.load(self.catalog_file, asset_root=self.assets)
        self.assertEqual(missing.released_gifts(), ())
        self.assertFalse(missing.snapshot()["gifts"][0]["asset_available"])

    def test_current_repository_catalog_is_not_monetizable_or_released_by_default(self):
        repo_catalog = Path(__file__).resolve().parents[1] / "data/game_actions/gift_catalog.json"
        if not repo_catalog.is_file():
            self.skipTest("Repository gift catalogue is unavailable in this test workspace.")
        catalog = GiftCatalog.load(repo_catalog, asset_root=repo_catalog.parents[2] / "public/assets/gifts")
        snapshot = catalog.snapshot()
        self.assertFalse(snapshot["real_money_enabled"])
        self.assertFalse(snapshot["checkout_enabled"])
        self.assertFalse(snapshot["payout_enabled"])
        self.assertEqual(snapshot["released_count"], 0)

    def test_rejects_duplicate_ids_bad_points_and_tiktok_id_mixing(self):
        for gifts in (
            [self.gift(), self.gift()],
            [self.gift(streamiov_points=True)],
            [self.gift(tiktok_gift_id="native-tiktok-id")],
        ):
            with self.subTest(gifts=gifts), self.assertRaises(GiftCatalogError):
                self.write_catalog(gifts)
                GiftCatalog.load(self.catalog_file, asset_root=self.assets)

    def test_rejects_unsafe_paths_and_unknown_status(self):
        for change in ({"svg": "/assets/gifts/../secret.svg"}, {"status": "published"}):
            with self.subTest(change=change), self.assertRaises(GiftCatalogError):
                self.write_catalog([self.gift(**change)])
                GiftCatalog.load(self.catalog_file, asset_root=self.assets)

    def test_preview_only_gifts_are_not_released(self):
        self.write_catalog([self.gift(status="local_preview_only")])
        catalog = GiftCatalog.load(self.catalog_file, asset_root=self.assets)
        self.assertEqual(len(catalog.previewable_gifts()), 1)
        self.assertEqual(catalog.released_gifts(), ())


    def test_rejects_symlinked_asset(self):
        outside = self.root / "outside.svg"
        outside.write_text("<svg></svg>", encoding="utf-8")
        (self.assets / "linked.svg").symlink_to(outside)
        self.write_catalog([self.gift(svg="/assets/gifts/linked.svg")])
        with self.assertRaisesRegex(GiftCatalogError, "symlink"):
            GiftCatalog.load(self.catalog_file, asset_root=self.assets)


if __name__ == "__main__":
    unittest.main()
