"""Windows workspace backend security and functionality tests."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from ai.runtime.project_tools import ProjectTools, ToolError


@unittest.skipUnless(os.name == "nt", "Windows-only workspace security tests")
class WindowsWorkspaceBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "existing.txt").write_text("original value", encoding="utf-8")
        self.outside = self.root.parent / (self.root.name + "-outside")
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("outside secret", encoding="utf-8")
        self.tools = ProjectTools(self.root, writable_prefixes=("src/",))

    def tearDown(self):
        self.tools.close()
        import shutil
        shutil.rmtree(self.outside, ignore_errors=True)
        self.tmp.cleanup()

    def test_read_create_replace_and_list(self):
        self.assertEqual(self.tools.read_file("src/existing.txt"), "original value")
        self.tools.write_file("src/new.txt", "created safely")
        self.assertEqual(self.tools.read_file("src/new.txt"), "created safely")
        self.tools.replace_text("src/existing.txt", "original", "updated")
        self.assertEqual(self.tools.read_file("src/existing.txt"), "updated value")
        listing = self.tools.list_files("src")
        self.assertIn("file existing.txt", listing)
        self.assertIn("file new.txt", listing)

    def test_existing_file_is_never_overwritten_by_create(self):
        with self.assertRaises(ToolError):
            self.tools.write_file("src/existing.txt", "overwrite attempt")
        self.assertEqual(self.tools.read_file("src/existing.txt"), "original value")

    def test_path_traversal_and_scope_escape_are_rejected(self):
        with self.assertRaises(ToolError):
            self.tools.read_file("src/../outside/secret.txt")
        with self.assertRaises(ToolError):
            self.tools.write_file("outside/new.txt", "not allowed")

    def test_junction_reparse_point_is_rejected(self):
        junction = self.root / "src" / "outside-junction"
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(junction), str(self.outside)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            self.skipTest("Windows runner does not permit creating a junction")
        try:
            with self.assertRaises(ToolError):
                self.tools.read_file("src/outside-junction/secret.txt")
            with self.assertRaises(ToolError):
                self.tools.write_file("src/outside-junction/new.txt", "must not escape")
            self.assertFalse((self.outside / "new.txt").exists())
            self.assertEqual((self.outside / "secret.txt").read_text(encoding="utf-8"), "outside secret")
        finally:
            junction.rmdir()


if __name__ == "__main__":
    unittest.main()
