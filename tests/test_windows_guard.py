"""Windows must fail closed until the handle-relative backend exists."""
import os
import tempfile
import unittest
from pathlib import Path

from ai.runtime.project_tools import ProjectTools, ToolError


@unittest.skipUnless(os.name == "nt", "Windows-only workspace security smoke test")
class WindowsWorkspaceGuardTests(unittest.TestCase):
    def test_file_access_fails_closed_without_posix_dirfd_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "existing.txt").write_text("must remain protected", encoding="utf-8")
            tools = ProjectTools(root, writable_prefixes=("src/",))
            try:
                with self.assertRaisesRegex(ToolError, "POSIX openat/O_NOFOLLOW"):
                    tools.read_file("src/existing.txt")
                with self.assertRaisesRegex(ToolError, "POSIX openat/O_NOFOLLOW"):
                    tools.write_file("src/new.txt", "must not be created")
                self.assertFalse((root / "src" / "new.txt").exists())
                self.assertEqual(
                    (root / "src" / "existing.txt").read_text(encoding="utf-8"),
                    "must remain protected",
                )
            finally:
                tools.close()


if __name__ == "__main__":
    unittest.main()
