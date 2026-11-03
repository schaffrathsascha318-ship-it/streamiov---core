"""Tests for the read-only catalog seeded from repository raw-data JSON."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from host.data_store import DataSeedError, DataStore, DEFAULT_RAW_DATA_ROOT


class DataStoreSeedTests(unittest.TestCase):
    def test_seeds_the_repository_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(directory)
            summary = store.summary()

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["errors"], [])
            self.assertTrue(summary["read_only"])
            self.assertFalse(summary["legacy_databases_read"])
            self.assertEqual(summary["counts"], {
                "gifts": 18,
                "gift_rules": 2,
                "like_milestones": 3,
                "music_playlists": 1,
                "music_tracks": 1,
                "music_rights": 0,
                "games": 2,
                "game_actions": 3,
                "studio_templates": 5,
            })
            self.assertTrue(store.database.name == "streamiov-data.sqlite3")
            self.assertEqual(store.database.parent, Path(directory).resolve())

            gifts = store.gifts()
            self.assertEqual(gifts["counts"], {"gifts": 18, "rules": 2, "like_milestones": 3})
            self.assertFalse(gifts["tiktok_gift_ids_present"])
            self.assertEqual(gifts["like_milestones"], [10000, 15000, 20000])
            self.assertTrue(all(gift["tiktok_gift_id"] is None for gift in gifts["gifts"]))
            self.assertTrue(all(rule["status"] == "planned" for rule in gifts["rules"]))
            rose = next(gift for gift in gifts["gifts"] if gift["id"] == "rose")
            self.assertEqual(rose["streamiov_points"], 1)
            self.assertEqual(rose["svg"], "/assets/gifts/rose.svg")

            games = store.games()
            self.assertEqual(games["counts"], {"games": 2, "actions": 3})
            self.assertTrue(all(game["interface_status"] == "test" for game in games["games"]))
            self.assertEqual(
                sum(len(game["actions"]) for game in games["games"]),
                3,
            )

            music = store.music()
            self.assertEqual(music["counts"], {"playlists": 1, "tracks": 1, "rights_tracks": 0})
            self.assertEqual(music["playlists"][0]["tracks"][0]["rights_status"], "test-only")

            templates = store.templates()
            self.assertEqual(templates["counts"], {"templates": 5})
            self.assertTrue(all(template["local_only"] for template in templates["templates"]))

    def test_reseeding_is_idempotent_and_preserves_non_seed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(directory)
            with closing(sqlite3.connect(store.database)) as db:
                db.execute(
                    """INSERT INTO gifts(gift_id,name,streamiov_points,source,updated_at)
                       VALUES('manual-gift','Manuell',7,'manual',0)"""
                )
                db.commit()
            first = store.summary()["counts"]
            store.seed()
            second = store.summary()["counts"]

            self.assertEqual(second["gifts"], first["gifts"])
            self.assertEqual(second["gift_rules"], first["gift_rules"])
            self.assertEqual(second["like_milestones"], first["like_milestones"])
            with closing(sqlite3.connect(store.database)) as db:
                manual = db.execute(
                    "SELECT name,streamiov_points FROM gifts WHERE gift_id='manual-gift'"
                ).fetchone()
            self.assertEqual(manual, ("Manuell", 7))

    def test_missing_sources_are_reported_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as raw:
            store = DataStore(directory, raw)
            summary = store.summary()
            self.assertFalse(summary["ok"])
            self.assertTrue(summary["errors"])
            self.assertEqual(summary["counts"]["gifts"], 0)
            self.assertTrue(all("missing" in error for error in summary["errors"]))

    def test_invalid_source_keeps_the_previous_catalog_rows(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as raw:
            raw_root = Path(raw)
            shutil.copytree(
                DEFAULT_RAW_DATA_ROOT, raw_root, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("db", "backups", "connector", "oauth", "ai", "gift-gallery"),
            )
            store = DataStore(directory, raw_root)
            self.assertEqual(store.summary()["counts"]["gifts"], 18)
            self.assertEqual(store.summary()["counts"]["studio_templates"], 5)

            (raw_root / "game_actions" / "gift_catalog.json").write_text("{not json", encoding="utf-8")
            summary = store.seed()
            self.assertFalse(summary["ok"])
            self.assertEqual(summary["counts"]["gifts"], 18)
            self.assertEqual(summary["counts"]["studio_templates"], 5)
            self.assertTrue(any("not valid JSON" in error for error in summary["errors"]))

    def test_legacy_databases_are_never_read_or_modified(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as raw:
            raw_root = Path(raw)
            legacy_dir = raw_root / "db"
            legacy_dir.mkdir()
            legacy = legacy_dir / "streaminivo.sqlite3"
            with closing(sqlite3.connect(legacy)) as db:
                db.execute("CREATE TABLE users(user_id TEXT PRIMARY KEY, username TEXT)")
                db.execute("INSERT INTO users VALUES('u1','real-user')")
                db.commit()
            before = hashlib.sha256(legacy.read_bytes()).hexdigest()

            opened: list[str] = []
            real_connect = sqlite3.connect

            def recording_connect(database, *args, **kwargs):
                opened.append(str(database))
                return real_connect(database, *args, **kwargs)

            with patch("host.data_store.sqlite3.connect", side_effect=recording_connect):
                store = DataStore(directory, raw_root)
                store.summary()
                store.gifts()
                store.games()
                store.music()
                store.templates()

            after = hashlib.sha256(legacy.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertFalse(any("streaminivo" in path or "streamiov.sqlite3" in path for path in opened))
            self.assertFalse(store.summary()["legacy_databases_read"])
            with closing(sqlite3.connect(store.database)) as db:
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
            self.assertNotIn("users", tables)
            self.assertNotIn("auth_credentials", tables)

    def test_raw_data_path_cannot_escape_the_configured_root(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "secret.json"
            outside_file.write_text("{}", encoding="utf-8")
            store = DataStore(directory, Path(directory))
            with self.assertRaises(DataSeedError):
                store._read_source("../secret.json")

    def test_catalog_dispatch_rejects_unknown_kinds(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(directory)
            for kind in ("summary", "gifts", "games", "music", "templates"):
                with self.subTest(kind=kind):
                    self.assertTrue(store.catalog(kind)["read_only"])
            with self.assertRaises(KeyError):
                store.catalog("users")


if __name__ == "__main__":
    unittest.main()
