import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from games.package import build_package


class GamePackageBuilderTests(unittest.TestCase):
    def make_project(self, root: Path):
        project = root / "games/demo"
        project.mkdir(parents=True)
        (project / "game.js").write_text("console.log('demo')\n", encoding="utf-8")
        (project / "README.md").write_text("Demo game\n", encoding="utf-8")
        manifest = {
            "id": "demo-game",
            "entrypoint": "game.js",
            "package": "games/releases/demo-game-0.1.0.zip",
            "package_checksum": "games/releases/demo-game-0.1.0.zip.sha256",
            "package_manifest": "demo-game/manifest.json",
            "package_files": ["README.md", "manifest.json", "game.js"],
        }
        (project / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        return project / "manifest.json"

    def test_package_is_repeatable_and_matches_every_listed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.make_project(root)
            first = build_package(manifest, root)
            package = root / first["package"]
            first_bytes = package.read_bytes()
            second = build_package(manifest, root)
            self.assertEqual(first, second)
            self.assertEqual(package.read_bytes(), first_bytes)
            self.assertEqual(first["sha256"], hashlib.sha256(first_bytes).hexdigest())
            sidecar = Path(str(package) + ".sha256").read_text(encoding="ascii").strip()
            self.assertEqual(sidecar, f"{first['sha256']}  {package.name}")
            with ZipFile(package) as zipped:
                self.assertIsNone(zipped.testzip())
                self.assertEqual(set(zipped.namelist()), {
                    "demo-game/README.md", "demo-game/manifest.json", "demo-game/game.js"
                })

    def test_changed_package_requires_explicit_force_and_updates_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.make_project(root)
            first = build_package(manifest, root)
            package = root / first["package"]
            old_bytes = package.read_bytes()
            (manifest.parent / "game.js").write_text("console.log('changed')\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                build_package(manifest, root)
            second = build_package(manifest, root, force=True)
            self.assertNotEqual(old_bytes, package.read_bytes())
            self.assertEqual(second["sha256"], hashlib.sha256(package.read_bytes()).hexdigest())

    def test_traversal_and_symlink_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            manifest_path = self.make_project(root)
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["package"] = "../../outside.zip"
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_package(manifest_path, root)

            data["package"] = "games/releases/demo-game-0.1.0.zip"
            (manifest_path.parent / "outside-link").symlink_to(Path(outside), target_is_directory=True)
            data["package_files"] = ["manifest.json", "outside-link/secret.txt"]
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_package(manifest_path, root)


if __name__ == "__main__":
    unittest.main()
