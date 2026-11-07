import tempfile
import unittest
from pathlib import Path

from ai.runtime.project_tools import ProjectTools, ToolError


class WorkspaceScopeTests(unittest.TestCase):
    def test_custom_scopes_allow_external_project_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            tools = ProjectTools(root, writable_prefixes=("src", "tests/"))
            tools.write_file("src/module.py", "VALUE = 1\n")
            tools.write_file("tests/test_module.py", "def test_ok(): pass\n")
            self.assertTrue((root / "src/module.py").is_file())
            self.assertEqual(tools.writable_prefixes, ("src/", "tests/"))

    def test_custom_scope_does_not_allow_writes_outside_configured_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = ProjectTools(tmp, writable_prefixes=("src/",))
            with self.assertRaises(ToolError):
                tools.write_file("docs/readme.md", "no")
            with self.assertRaises(ToolError):
                tools.write_file(".env", "secret")

    def test_invalid_or_dangerous_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for scope in ("../outside/", "/absolute/", ".git/", ".env/", r"src\private/"):
                with self.subTest(scope=scope):
                    with self.assertRaises(ToolError):
                        ProjectTools(tmp, writable_prefixes=(scope,))

    def test_symlinked_parent_is_rejected_for_reads_and_writes(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / "src").mkdir()
            outside_root = Path(outside)
            (outside_root / "private.txt").write_text("outside", encoding="utf-8")
            (root / "src" / "linked").symlink_to(outside_root, target_is_directory=True)
            tools = ProjectTools(root, writable_prefixes=("src/",))
            with self.assertRaises(ToolError):
                tools.read_file("src/linked/private.txt")
            with self.assertRaises(ToolError):
                tools.write_file("src/linked/new.txt", "no")

    def test_missing_workspace_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-created"
            with self.assertRaises(ToolError):
                ProjectTools(missing, writable_prefixes=("src/",))


if __name__ == "__main__":
    unittest.main()
