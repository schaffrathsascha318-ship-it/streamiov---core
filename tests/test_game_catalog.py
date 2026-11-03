import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from games.catalog import audit_game


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REAL_MANIFEST = REPOSITORY_ROOT / "games/releases/streamiov-star-defender/manifest.json"


class GameCatalogTests(unittest.TestCase):
    def test_existing_prototype_manifest_and_package_are_valid_but_not_release_ready(self):
        result = audit_game(REAL_MANIFEST, REPOSITORY_ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["release_ready"])
        self.assertEqual(result["status"], "PROTOTYPE")

    def test_released_game_requires_all_review_gates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "games/example"
            project.mkdir(parents=True)
            (project / "game.py").write_text("pass\n", encoding="utf-8")
            archive_path = root / "games/example.zip"
            manifest = {
                "schema_version": 1, "id": "example-game", "title": "Example", "status": "RELEASED",
                "genre": ["puzzle"], "entrypoint": "game.py",
                "package": "games/example.zip", "package_checksum": "games/example.zip.sha256",
                "package_manifest": "example/manifest.json",
                "package_files": ["game.py", "manifest.json"],
                "provenance": {**{key: "recorded" for key in ("concept", "code", "art", "fonts", "audio")}, "ownership_review": "pending", "external_assets": []},
                "verification": {"unit_tests": "passed"},
            }
            manifest_path = project / "manifest.json"
            encoded = json.dumps(manifest, sort_keys=True).encode("utf-8")
            with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
                archive.writestr("example/game.py", "pass\n")
                archive.writestr("example/manifest.json", encoded)
            import hashlib
            checksum_path = root / "games/example.zip.sha256"
            checksum_path.write_text(
                f"{hashlib.sha256(archive_path.read_bytes()).hexdigest()}  {archive_path.name}\n",
                encoding="ascii",
            )
            manifest_path.write_bytes(encoded)
            (project / "game.py").write_text("changed after package\n", encoding="utf-8")
            result = audit_game(manifest_path, root)
            self.assertTrue(any("accessibility_review" in error for error in result["errors"]))
            self.assertTrue(any("ownership_review" in error for error in result["errors"]))
            self.assertTrue(any("differs from project file" in error for error in result["errors"]))
            self.assertFalse(result["release_ready"])

    def test_package_digest_mismatch_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "games/example"
            project.mkdir(parents=True)
            (project / "game.py").write_text("pass\n", encoding="utf-8")
            (root / "games/example.zip").write_bytes(b"not a zip")
            (root / "games/example.zip.sha256").write_text("0" * 64 + "  example.zip\n", encoding="ascii")
            manifest = {
                "schema_version": 1, "id": "example", "title": "Example", "status": "PROTOTYPE",
                "genre": ["puzzle"], "entrypoint": "game.py", "package": "games/example.zip",
                "package_checksum": "games/example.zip.sha256", "package_manifest": "example/manifest.json",
                "package_files": ["game.py", "manifest.json"],
                "provenance": {"concept": "a", "code": "b", "art": "c", "fonts": "d", "audio": "e", "ownership_review": "pending", "external_assets": []},
                "verification": {},
            }
            manifest_path = project / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = audit_game(manifest_path, root)
            self.assertFalse(result["valid"])
            self.assertTrue(any("checksum" in error for error in result["errors"]))
            self.assertTrue(any("ZIP" in error for error in result["errors"]))

    def test_package_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "games/example"
            project.mkdir(parents=True)
            (project / "game.py").write_text("pass\n", encoding="utf-8")
            manifest = {
                "schema_version": 1, "id": "example", "title": "Example", "status": "PROTOTYPE",
                "genre": ["puzzle"], "entrypoint": "game.py", "package": "../secret.zip",
                "package_checksum": "../secret.sha256", "package_manifest": "example/manifest.json",
                "package_files": ["game.py", "manifest.json"],
                "provenance": {"concept": "a", "code": "b", "art": "c", "fonts": "d", "audio": "e", "ownership_review": "pending", "external_assets": []},
                "verification": {},
            }
            manifest_path = project / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = audit_game(manifest_path, root)
            self.assertFalse(result["valid"])
            self.assertTrue(any("repository-relative" in error for error in result["errors"]))

    def test_manifest_outside_repository_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as repository, tempfile.TemporaryDirectory() as outside:
            secret_like_file = Path(outside) / "manifest.json"
            secret_like_file.write_text('{"title":"should not be read"}', encoding="utf-8")
            result = audit_game(secret_like_file, repository)
            self.assertFalse(result["valid"])
            self.assertIn("manifest file is outside the repository", result["errors"])


if __name__ == "__main__":
    unittest.main()
